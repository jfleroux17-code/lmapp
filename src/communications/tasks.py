"""Envoi des messages par le worker (seul à avoir une sortie Internet)."""
import logging

from django.db import transaction
from django.utils import timezone
from procrastinate import RetryStrategy
from procrastinate.contrib.django import app

from communications import courriel, twilio
from communications.erreurs import Incertain, Indisponible, Refuse
from communications.models import Message

log = logging.getLogger(__name__)
ESSAIS = 5


@app.task(queue="communications", pass_context=True,
          retry=RetryStrategy(max_attempts=ESSAIS + 1, exponential_wait=5, retry_exceptions={Indisponible}))
def envoyer_message(context, message_id):
    with transaction.atomic():
        m = Message.objects.select_for_update(of=("self",)).select_related("entreprise", "facture").filter(pk=message_id).first()
        if m is None or m.statut != Message.Statut.EN_FILE:
            return "rien à faire"  # déjà envoyé (tâche en double) ou annulé
        try:
            if m.canal == Message.Canal.COURRIEL:
                m.fournisseur_id = courriel.envoyer_courriel(m)[:64]
            else:
                m.fournisseur_id = twilio.envoyer_texto(m.entreprise.numero_texto, m.destinataire, m.contenu)
            m.statut, m.envoye_le, m.erreur = Message.Statut.ENVOYE, timezone.now(), ""
        except Indisponible as e:
            if context.job.attempts + 1 < ESSAIS:
                log.warning("message %s : %s, on réessaiera", m.pk, e)
                raise
            m.statut, m.erreur = Message.Statut.ECHEC, str(e)[:300]
        except (Refuse, Incertain) as e:
            m.statut, m.erreur = Message.Statut.ECHEC, str(e)[:300]
        m.save(update_fields=["statut", "envoye_le", "erreur", "fournisseur_id", "modifie_le"])
        log.info("message %s : %s", m.pk, m.statut)
        return m.statut
