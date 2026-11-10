"""Envoi des messages (PRD E2, G2 à G5, M1).

`envoyer(message)` décide du sort du message, puis le worker l'envoie (`communications.tasks`) :
  - Préparé (rien ne part) : fournisseur pas configuré (.env), envois réels éteints dans la fiche
    de l'entreprise (`envois_actifs`, éteint par défaut), ou numéro de texto d'affaires manquant;
  - Bloqué : hors prod, destinataire absent de LMAPP_DESTINATAIRES_TEST (garde-fou du test);
  - En file, puis Envoyé ou Échec.
Courriels : serveur de courriel de l'entreprise (SMTP_HOTE, IMAP_UTILISATEUR dans .env); l'adresse
d'envoi est celle de la fiche (`courriel_reponse`) et doit être ce compte.
"""
from django.conf import settings
from django.db import transaction

from communications.models import Message


def fournisseur_configure(canal):
    if canal == Message.Canal.TEXTO:
        return bool(settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN)
    return bool(settings.SMTP_HOTE and settings.IMAP_UTILISATEUR and settings.IMAP_MOT_DE_PASSE)


def destinataire_permis(destinataire):
    """Hors prod : seulement les destinataires de LMAPP_DESTINATAIRES_TEST (ceux de JF)."""
    if settings.LMAPP_ENV == "prod":
        return True
    return destinataire.lower() in {d.lower() for d in settings.LMAPP_DESTINATAIRES_TEST}


def _pourquoi_pas(message):
    ent = message.entreprise
    if not fournisseur_configure(message.canal):
        return "Aucun fournisseur configuré."
    if not ent.envois_actifs:
        return "Envois réels éteints dans la fiche de l'entreprise."
    if message.canal == Message.Canal.TEXTO and not ent.numero_texto:
        return "Numéro de texto d'affaires manquant dans la fiche de l'entreprise."
    if message.canal == Message.Canal.COURRIEL:
        if not ent.courriel_reponse:
            return "Adresse courriel d'affaires manquante dans la fiche de l'entreprise."
        if ent.courriel_reponse.lower() != settings.IMAP_UTILISATEUR.lower():
            return "L'adresse courriel d'affaires de la fiche n'est pas le compte courriel configuré."
    return ""


def envoyer(message, delai=0):
    """delai (secondes) : envoi retardé, le temps de l'annuler (avis de début d'opération)."""
    raison = _pourquoi_pas(message)
    if raison:
        message.statut, message.erreur = Message.Statut.PREPARE, raison
    elif not destinataire_permis(message.destinataire):
        message.statut, message.erreur = Message.Statut.BLOQUE, "Environnement de test : destinataire non permis."
    else:
        from communications.tasks import envoyer_message

        message.statut, message.erreur = Message.Statut.EN_FILE, ""
        pk = message.pk
        tache = envoyer_message.configure(schedule_in={"seconds": delai}) if delai else envoyer_message
        transaction.on_commit(lambda: tache.defer(message_id=pk))
    message.save(update_fields=["statut", "erreur", "modifie_le"])
    return message
