"""Tâches du worker pour core : notifier les appareils des membres d'une entreprise (PRD E8)."""
from procrastinate.contrib.django import app


@app.task(queue="communications")
def notifier(entreprise_id, titre, corps, url="/"):
    from core import notifications
    from core.models import AbonnementNotification, Membre

    if not notifications.configure():
        return 0
    qs = (AbonnementNotification.objects.filter(entreprise_id=entreprise_id)
          .exclude(utilisateur__membres__entreprise_id=entreprise_id, utilisateur__membres__role=Membre.Role.LECTURE))
    return sum(1 for a in qs if notifications.envoyer(a, titre, corps, url))


def notifier_plus_tard(entreprise_id, titre, corps, url="/"):
    """À appeler dans une transaction : la notification part après l'enregistrement."""
    from django.db import transaction

    from core import notifications

    if notifications.configure():
        transaction.on_commit(lambda: notifier.defer(entreprise_id=entreprise_id, titre=titre, corps=corps, url=url))


# 7 h UTC = 2 h à Sainte-Adèle (3 h en été)
@app.periodic(cron="0 7 * * *")
@app.task(queue="facturation", queueing_lock="purger_journal")
def purger_journal_chaque_nuit(timestamp):
    """Journal des actions (K4) : on ne garde que LMAPP_JOURNAL_JOURS jours (Loi 25 : pas plus longtemps que nécessaire)."""
    from datetime import timedelta

    from django.conf import settings
    from django.utils import timezone

    from core.models import JournalAction

    limite = timezone.now() - timedelta(days=settings.LMAPP_JOURNAL_JOURS)
    return JournalAction.objects.filter(moment__lt=limite).delete()[0]


@app.periodic(cron="*/30 * * * *")
@app.task(queue="communications", queueing_lock="releve_meteo")
def relever_meteo(timestamp):
    """I1 : prévisions d'Environnement Canada pour chaque entreprise active, aux 30 minutes."""
    from core import meteo
    from core.models import Entreprise

    for e in Entreprise.objects.filter(active=True):
        meteo.relever(e)
