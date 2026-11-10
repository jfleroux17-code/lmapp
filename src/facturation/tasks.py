"""Tâches du volet argent, exécutées par le worker (Procrastinate)."""
import logging

from django.db import transaction
from django.utils import timezone
from procrastinate.contrib.django import app

from facturation.models import Versement

log = logging.getLogger(__name__)


def facturer_versements_dus(aujourdhui=None):
    """C5 : un brouillon de facture pour chaque versement arrivé à sa date et pas encore facturé.

    Seulement des brouillons : rien n'est émis ni envoyé sans Louis. Relançable
    sans danger (un versement déjà facturé est sauté).
    """
    from datetime import timedelta

    from core.models import Entreprise
    from core.tasks import notifier_plus_tard

    aujourdhui = aujourdhui or timezone.localdate()
    n = 0
    for ent in Entreprise.objects.filter(active=True):
        # Préparées d'avance (ex. 5 jours : le 10 janvier pour le 15), payables à la date prévue
        limite = aujourdhui + timedelta(days=ent.jours_avance_versement)
        dus = (Versement.objects.filter(facture=None, date_prevue__lte=limite, contrat__actif=True, contrat__entreprise=ent)
               .select_related("contrat__entreprise", "contrat__client", "contrat__saison").order_by("date_prevue", "pk"))
        n_ent = 0
        with transaction.atomic():
            for v in dus:
                v.facturer()
                n_ent += 1
            if n_ent:
                notifier_plus_tard(ent.pk, "Factures de versement prêtes",
                                   f"{n_ent} facture{'s' if n_ent > 1 else ''} de versement à vérifier et envoyer. Rien ne part sans vous.",
                                   url="/factures/versements/")
        n += n_ent
    if n:
        log.info("versements dus : %s brouillon(s) de facture créé(s)", n)
    return n


# Procrastinate compte en UTC : 6 h UTC = 1 h à Sainte-Adèle (2 h en été), avant la journée de Louis
@app.periodic(cron="0 6 * * *")
@app.task(queue="facturation", queueing_lock="facturer_versements_dus")
def facturer_versements_dus_chaque_nuit(timestamp):
    return facturer_versements_dus()


def aviser_cheques_a_deposer(aujourdhui=None):
    """D9 : avis au cellulaire le jour où des chèques postdatés arrivent à leur date (une fois, le matin)."""
    from django.db.models import Sum

    from core.models import Entreprise
    from core.tasks import notifier_plus_tard
    from facturation import cheques
    from facturation.templatetags.argent import argent

    aujourdhui = aujourdhui or timezone.localdate()
    n = 0
    for ent in Entreprise.objects.filter(active=True):
        du_jour = cheques.en_main(ent).filter(date_cheque=aujourdhui)
        if not du_jour.exists():
            continue
        tous = cheques.a_deposer(ent, aujourdhui)
        nb, total = tous.count(), tous.aggregate(s=Sum("montant"))["s"]
        notifier_plus_tard(ent.pk, "Chèques à déposer",
                           f"{nb} chèque{'s' if nb > 1 else ''} postdaté{'s' if nb > 1 else ''} à déposer ({argent(total)}). "
                           "Tapez « Déposé » une fois à la banque.", url="/cheques/")
        n += 1
    return n


# 13 h UTC = 8 h à Sainte-Adèle l'hiver (9 h l'été)
@app.periodic(cron="0 13 * * *")
@app.task(queue="facturation", queueing_lock="aviser_cheques")
def aviser_cheques_chaque_matin(timestamp):
    return aviser_cheques_a_deposer()
