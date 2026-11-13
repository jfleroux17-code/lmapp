"""Double authentification par Google Authenticator (TOTP, RFC 6238), sans service externe.

- Activation : clé secrète au hasard (160 bits), montrée une seule fois (code QR, lien otpauth:// qui ouvre
  l'application sur le cellulaire, ou clé à taper); confirmée par un premier code; 10 codes de secours (une fois chacun).
- Connexion : après le bon mot de passe, la session est « en attente » (`SESSION_ATTENTE`) jusqu'au code à 6 chiffres
  (`core.middleware.DoubleAuthMiddleware` bloque tout le reste). Une fois par nouvelle connexion : les sessions
  durent 90 jours sur le cellulaire.
- Obligatoire (recommandation acceptée par JF) pour les superutilisateurs et les administrateurs d'une entreprise
  (`obligatoire`); ils sont menés à l'activation dès la connexion. Au choix pour les opérateurs et la lecture seule.
- 5 codes faux de suite : déconnexion, il faut retaper le mot de passe (qui, lui, est limité par core.connexions).
- Téléphone perdu : un code de secours, sinon un administrateur de l'entreprise (Réglages, Utilisateurs) ou JF
  (administration) réinitialise; la personne refait l'activation à sa prochaine connexion.
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from django.conf import settings

PERIODE = 30
CHIFFRES = 6
FENETRE = 1  # un pas avant ou après : horloge du téléphone un peu décalée
SESSION_ATTENTE = "double_auth_en_attente"
SESSION_ESSAIS = "double_auth_essais"
SESSION_SECRET_PROPOSE = "double_auth_secret_propose"
ESSAIS_MAX = 5
NB_CODES_SECOURS = 10


def nouveau_secret():
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _code(secret, pas):
    cle = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    h = hmac.new(cle, struct.pack(">Q", pas), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    n = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** CHIFFRES)
    return str(n).zfill(CHIFFRES)


def pas_actuel(maintenant=None):
    return int((maintenant if maintenant is not None else time.time()) // PERIODE)


def code_pour(secret, maintenant=None):
    """Le code que l'application affiche en ce moment (pour les tests)."""
    return _code(secret, pas_actuel(maintenant))


def verifier_code(secret, code, dernier_pas=0, maintenant=None):
    """Renvoie le pas accepté (à garder pour refuser une deuxième utilisation), ou None."""
    code = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(code) != CHIFFRES:
        return None
    pas = pas_actuel(maintenant)
    for p in range(pas - FENETRE, pas + FENETRE + 1):
        if p > dernier_pas and hmac.compare_digest(_code(secret, p), code):
            return p
    return None


def lien_otpauth(secret, utilisateur):
    emetteur = "Le Déneigeur"
    compte = f"{emetteur}:{utilisateur.username}"
    return (f"otpauth://totp/{quote(compte)}?secret={secret}&issuer={quote(emetteur)}"
            f"&algorithm=SHA1&digits={CHIFFRES}&period={PERIODE}")


def qr_svg(texte):
    import io

    import segno

    tampon = io.BytesIO()
    segno.make(texte, error="m").save(tampon, kind="svg", scale=6, border=2, dark="#000", light="#fff", xmldecl=False, svgns=True)
    return tampon.getvalue().decode()


def _empreinte(code):
    return hashlib.sha256(code.replace("-", "").replace(" ", "").lower().encode()).hexdigest()


def nouveaux_codes_secours():
    """(codes à montrer une fois, empreintes à garder)."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    codes = ["".join(secrets.choice(alphabet) for _ in range(5)) + "-" + "".join(secrets.choice(alphabet) for _ in range(5))
             for _ in range(NB_CODES_SECOURS)]
    return codes, [_empreinte(c) for c in codes]


def obligatoire(user):
    if not getattr(settings, "LMAPP_DOUBLE_AUTH_OBLIGATOIRE", True) or not user.is_authenticated:
        return False
    from core.models import Membre

    return user.is_superuser or Membre.objects.filter(utilisateur=user, role=Membre.Role.ADMINISTRATEUR).exists()


def active(user):
    from core.models import DoubleAuthentification

    return user.is_authenticated and DoubleAuthentification.objects.filter(utilisateur=user).exists()


def verifier(user, code):
    """Code de l'application, ou code de secours (effacé une fois utilisé). Vrai si accepté."""
    from django.utils import timezone

    from core.models import DoubleAuthentification

    da = DoubleAuthentification.objects.select_for_update().filter(utilisateur=user).first()
    if da is None:
        return False
    pas = verifier_code(da.secret, code, da.dernier_pas)
    if pas is not None:
        da.dernier_pas = pas
        da.derniere_utilisation = timezone.now()
        da.save(update_fields=["dernier_pas", "derniere_utilisation"])
        return True
    e = _empreinte(code or "")
    if len((code or "").replace("-", "").replace(" ", "")) == 10 and e in da.codes_secours:
        da.codes_secours = [c for c in da.codes_secours if c != e]
        da.derniere_utilisation = timezone.now()
        da.save(update_fields=["codes_secours", "derniere_utilisation"])
        return True
    return False


def marquer_en_attente(sender, request, user, **kwargs):
    """Signal user_logged_in : un compte qui a la double authentification doit d'abord donner son code."""
    if request is not None and hasattr(request, "session") and active(user):
        request.session[SESSION_ATTENTE] = True
        request.session[SESSION_ESSAIS] = 0
