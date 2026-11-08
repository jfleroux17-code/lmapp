"""Notifications sur le cellulaire (PRD E8) : Web Push, chiffrement aes128gcm (RFC 8291) et signature VAPID (RFC 8292).

Envoyées par le worker (seul à avoir une sortie Internet) aux appareils abonnés des membres de l'entreprise
(pas aux comptes en lecture seule). Un abonnement refusé par le service (404, 410 : appareil désinstallé) est effacé.
Clés VAPID dans .env (`VAPID_CLE_PRIVEE`, `VAPID_CLE_PUBLIQUE`), produites par `manage.py cles_vapid`.
"""
import base64
import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import http_ece
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.conf import settings
from django.utils import timezone

log = logging.getLogger(__name__)


def _b64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def configure():
    return bool(settings.VAPID_CLE_PRIVEE and settings.VAPID_CLE_PUBLIQUE)


def chiffrer(abonnement, donnees):
    cle_serveur = ec.generate_private_key(ec.SECP256R1())
    return http_ece.encrypt(donnees, salt=os.urandom(16), private_key=cle_serveur, dh=_b64(abonnement.p256dh),
                            auth_secret=_b64(abonnement.auth), version="aes128gcm")


def entete_vapid(endpoint):
    from py_vapid import Vapid02

    v = Vapid02.from_raw(settings.VAPID_CLE_PRIVEE.encode())
    s = urlsplit(endpoint)
    claims = {"aud": f"{s.scheme}://{s.netloc}", "exp": int(timezone.now().timestamp()) + 12 * 3600, "sub": settings.VAPID_SUJET}
    return v.sign(claims)["Authorization"]


def envoyer(abonnement, titre, corps, url="/"):
    """True si le service a accepté; efface l'abonnement s'il n'existe plus."""
    donnees = json.dumps({"titre": titre, "corps": corps[:180], "url": url}).encode()
    req = Request(abonnement.endpoint, data=chiffrer(abonnement, donnees), method="POST", headers={
        "Authorization": entete_vapid(abonnement.endpoint), "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream", "TTL": "86400", "Urgency": "high",
    })
    try:
        with urlopen(req, timeout=20):
            pass
    except HTTPError as e:
        if e.code in (404, 410):
            log.info("abonnement %s expiré : effacé", abonnement.pk)
            abonnement.delete()
        else:
            log.warning("notification refusée (%s) pour l'abonnement %s", e.code, abonnement.pk)
        return False
    except (URLError, OSError) as e:
        log.warning("service de notification injoignable : %s", e)
        return False
    type(abonnement).objects.filter(pk=abonnement.pk).update(dernier_envoi=timezone.now())
    return True


def cle_publique_pour_le_navigateur():
    return settings.VAPID_CLE_PUBLIQUE


def nouvelles_cles():
    """(privée en base64url brut, publique en base64url, point non compressé) pour .env."""
    cle = ec.generate_private_key(ec.SECP256R1())
    prive = cle.private_numbers().private_value.to_bytes(32, "big")
    public = cle.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    b = lambda o: base64.urlsafe_b64encode(o).decode().rstrip("=")  # noqa: E731
    return b(prive), b(public)
