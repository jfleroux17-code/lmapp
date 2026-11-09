"""Webhooks de Twilio (PRD E4, E11, M1) : textos reçus et suivi de livraison.

Chaque appel est vérifié par sa signature (`X-Twilio-Signature` : HMAC-SHA1 de l'URL publique suivie des
paramètres triés, avec l'Auth Token) : sans signature valide, 403 et rien n'est enregistré. Twilio ne peut
joindre ld1 que si le 443 lui est ouvert au routeur (aujourd'hui limité à `_SLAPP`).

L'entreprise vient du numéro Twilio appelé (`To` = `Entreprise.numero_texto`), pas du domaine.
"""
import base64
import hashlib
import hmac
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from clients.models import Client
from communications.models import Genre, Message
from core import telephone
from core.models import Entreprise

log = logging.getLogger(__name__)
ARRET = {"stop", "arret", "arrêt", "arreter", "arrêter", "desabonner", "désabonner", "unsubscribe", "stopall", "cancel", "end", "quit"}
REPRISE = {"start", "unstop", "commencer", "reprendre", "oui"}


def signature_valide(request):
    jeton = settings.TWILIO_AUTH_TOKEN
    recue = request.headers.get("X-Twilio-Signature", "")
    if not jeton or not recue:
        return False
    url = f"https://{request.get_host()}{request.get_full_path()}"
    donnees = url + "".join(f"{k}{v}" for k in sorted(request.POST) for v in request.POST.getlist(k))
    attendue = base64.b64encode(hmac.new(jeton.encode(), donnees.encode(), hashlib.sha1).digest()).decode()
    return hmac.compare_digest(attendue, recue)


def _twiml(texte=None):
    from xml.sax.saxutils import escape

    corps = f"<Message>{escape(texte)}</Message>" if texte else ""
    return HttpResponse(f'<?xml version="1.0" encoding="UTF-8"?><Response>{corps}</Response>', content_type="text/xml")


@csrf_exempt
@require_POST
def texto_recu(request):
    if not signature_valide(request):
        log.warning("webhook texto refusé : signature invalide (%s)", request.META.get("REMOTE_ADDR"))
        return HttpResponseForbidden("Signature invalide.")
    sid = request.POST.get("MessageSid", "")[:64]
    try:
        de, a = telephone.normaliser(request.POST.get("From", "")), telephone.normaliser(request.POST.get("To", ""))
    except Exception:
        return _twiml()
    ent = Entreprise.objects.filter(numero_texto=a, active=True).first()
    if ent is None:
        log.warning("texto reçu pour un numéro sans entreprise : %s", a)
        return _twiml()
    if sid and Message.objects.filter(entreprise=ent, message_id_externe=f"twilio:{sid}").exists():
        return _twiml()  # Twilio a réessayé : déjà enregistré
    corps = request.POST.get("Body", "").strip()
    client = Client.objects.filter(entreprise=ent, cellulaire=de).order_by("pk").first()
    medias = int(request.POST.get("NumMedia", "0") or 0)
    if medias:
        corps += f"\n\n[{medias} photo{'s' if medias > 1 else ''} ou pièce{'s' if medias > 1 else ''} jointe{'s' if medias > 1 else ''} : à voir dans la console Twilio]"
    from core.tasks import notifier_plus_tard

    notifier_plus_tard(ent.pk, f"Texto de {client.nom_affiche if client else telephone.afficher(de)}", corps[:150] or "(texto vide)", "/messages/?vue=recus")
    Message.objects.create(entreprise=ent, client=client, genre=Genre.RECU, canal=Message.Canal.TEXTO, sens=Message.Sens.ENTRANT,
                           statut=Message.Statut.RECU, lu=False, expediteur=de, destinataire=a, contenu=corps or "(texto vide)",
                           message_id_externe=f"twilio:{sid}" if sid else "", envoye_le=timezone.now(), fournisseur_id=sid)
    mot = corps.strip().strip(".!").lower()
    if client and mot in ARRET:  # E11 : plus de commercial (les avis de service restent permis par la LCAP)
        if client.desabonne_le is None:
            client.desabonne_le = timezone.now()
            client.save(update_fields=["desabonne_le"])
        if mot.startswith("arr") or mot.startswith("d"):  # STOP en anglais : Twilio répond déjà lui-même
            return _twiml(f"{ent.signature_messages or ent.nom} : vous ne recevrez plus de messages promotionnels. "
                          "Les avis de déneigement et les factures continueront. Répondez COMMENCER pour annuler.")
    elif client and mot in REPRISE:
        etait_desabonne = client.desabonne_le is not None
        if etait_desabonne:
            client.desabonne_le = None
            client.save(update_fields=["desabonne_le"])
        # Confirmation en français (demande de JF, 9 novembre 2026). START anglais : Twilio répond déjà lui-même.
        # « Oui » ne reçoit une réponse que s'il a vraiment réabonné (sinon, c'est une réponse ordinaire).
        if mot in ("commencer", "reprendre") or (mot == "oui" and etait_desabonne):
            return _twiml(f"{ent.signature_messages or ent.nom} : c'est noté, vous recevrez de nouveau nos messages "
                          "promotionnels. Répondez ARRÊT pour arrêter.")
    return _twiml()


@csrf_exempt
@require_POST
def statut_texto(request):
    """Suivi de livraison (StatusCallback) : un texto non livré passe en échec avec le code de Twilio."""
    if not signature_valide(request):
        return HttpResponseForbidden("Signature invalide.")
    sid, statut = request.POST.get("MessageSid", ""), request.POST.get("MessageStatus", "")
    if sid and statut in ("failed", "undelivered"):
        code = request.POST.get("ErrorCode", "")
        Message.objects.filter(fournisseur_id=sid, canal=Message.Canal.TEXTO, sens=Message.Sens.SORTANT).update(
            statut=Message.Statut.ECHEC, erreur=f"Non livré par l'opérateur (Twilio {code or statut}).", modifie_le=timezone.now())
    return HttpResponse(status=204)
