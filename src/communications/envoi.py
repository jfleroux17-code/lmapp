"""Envoi des messages. Aucun fournisseur pour l'instant : les messages restent « préparés ».

Le jour où Twilio ou SMTP2GO seront configurés (clés dans .env), l'envoi réel se
branchera dans `envoyer()`. Le garde-fou hors prod est déjà en place.
"""
from django.conf import settings

from communications.models import Message


def fournisseur_configure(canal):
    if canal == Message.Canal.TEXTO:
        return bool(getattr(settings, "TWILIO_ACCOUNT_SID", "") and getattr(settings, "TWILIO_AUTH_TOKEN", ""))
    return bool(getattr(settings, "SMTP2GO_API_KEY", ""))


def destinataire_permis(destinataire):
    """Hors prod : seulement les destinataires de LMAPP_DESTINATAIRES_TEST (ceux de JF)."""
    if settings.LMAPP_ENV == "prod":
        return True
    return destinataire.lower() in {d.lower() for d in settings.LMAPP_DESTINATAIRES_TEST}


def envoyer(message):
    if not fournisseur_configure(message.canal):
        message.statut = Message.Statut.PREPARE  # rien ne peut partir
    elif not destinataire_permis(message.destinataire):
        message.statut = Message.Statut.BLOQUE  # hors prod : seulement les destinataires de JF
    else:  # pragma: no cover : branché avec le fournisseur (Twilio, SMTP2GO)
        raise NotImplementedError("Envoi réel pas encore branché.")
    message.save(update_fields=["statut", "modifie_le"])
    return message
