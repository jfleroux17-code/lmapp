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
