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


@app.periodic(cron="*/2 * * * *")
@app.task(queue="communications", queueing_lock="lire_boite")
def lire_boite_aux_2_minutes(timestamp):
    """E5 : courriels reçus. En prod seulement (COURRIEL_LECTURE_ACTIVE), et seulement si une entreprise a
    pour adresse d'affaires le compte configuré."""
    from django.conf import settings

    from communications import lecture

    if not settings.COURRIEL_LECTURE_ACTIVE:
        return "lecture désactivée"
    ent = lecture.entreprise_de_la_boite()
    if ent is None:
        return "aucune entreprise pour cette boîte"
    n = lecture.lire(ent)
    if n:
        log.info("boîte de %s : %s courriel(s) reçu(s)", ent, n)
    return n


@app.periodic(cron="17 * * * *")
@app.task(queue="communications", queueing_lock="relever_couts")
def relever_couts_chaque_heure(timestamp):
    """E13 : prix de chaque texto (envoyé ou reçu), établi par Twilio quelques minutes après; 7 jours au plus."""
    from datetime import timedelta

    from django.conf import settings
    from django.utils import timezone

    from communications import twilio
    from communications.models import Message

    if not (settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN):
        return 0
    maintenant = timezone.now()
    n = 0
    for m in (Message.objects.filter(canal=Message.Canal.TEXTO, cout=None, cree_le__gte=maintenant - timedelta(days=7),
                                     cree_le__lte=maintenant - timedelta(minutes=10)).exclude(fournisseur_id="")[:200]):
        try:
            r = twilio.prix(m.fournisseur_id)
        except Exception:  # noqa: BLE001 : on réessaiera à l'heure suivante
            continue
        if r:
            Message.objects.filter(pk=m.pk).update(cout=r[0], cout_devise=r[1])
            n += 1
    return n


@app.periodic(cron="0 * * * *")
@app.task(queue="communications", queueing_lock="aviser_relances")
def aviser_relances(timestamp):
    """C9 : une fois par jour de semaine, dès 9 h (heure de l'entreprise), avise le cellulaire des relances
    prêtes. Pas pendant une opération de déneigement (on réessaie à l'heure suivante, jusqu'à 16 h).
    N'envoie aucune relance : le déneigeur les envoie lui-même depuis l'écran."""
    from django.utils import timezone

    from communications.relances_proposees import proposees
    from core.models import Entreprise
    from core.tasks import notifier
    from tournee.models import Operation

    maintenant = timezone.localtime()
    if maintenant.weekday() >= 5 or not 9 <= maintenant.hour < 17:
        return "hors des heures"
    aujourdhui = maintenant.date()
    n_avis = 0
    for ent in Entreprise.objects.filter(active=True, relances_proposees=True).exclude(relances_avisees_le=aujourdhui):
        if Operation.en_cours_de(ent):
            continue
        n = len(proposees(ent, aujourdhui))
        Entreprise.objects.filter(pk=ent.pk).update(relances_avisees_le=aujourdhui)  # update() : pas une action à journaliser
        if n:
            notifier.defer(entreprise_id=ent.pk, titre="Relances prêtes",
                           corps=f"{n} relance{'s' if n > 1 else ''} à envoyer. Rien ne part sans vous.", url="/comptes/relances/")
            n_avis += 1
    return n_avis
