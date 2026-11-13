"""Tâches du volet argent, exécutées par le worker (Procrastinate)."""
import logging

from django.db import transaction
from django.utils import timezone
from procrastinate.contrib.django import app


log = logging.getLogger(__name__)


def aviser_rappels_de_versement(aujourdhui=None):
    """Une seule facture par saison (décision de JF, 12 novembre 2026) : à l'approche de la date d'un versement,
    un avis au cellulaire « rappels à envoyer » (écran Versements à envoyer). Rien ne part sans Louis.
    Avisé une seule fois par versement (le même jour, le suivant n'en refait pas un)."""
    from datetime import timedelta

    from communications.rappels import a_rappeler
    from core.models import Entreprise
    from core.tasks import notifier_plus_tard

    from facturation.models import Contrat

    aujourdhui = aujourdhui or timezone.localdate()
    n = 0
    for ent in Entreprise.objects.filter(active=True):
        # Contrats saisonniers sans facture (import, saison suivante) dont le 1er versement arrive : brouillon prêt
        limite = aujourdhui + timedelta(days=ent.jours_avance_versement)
        sans_facture = (Contrat.objects.filter(entreprise=ent, actif=True, type=Contrat.Type.SAISONNIER, versements__rang=1,
                                               versements__date_prevue__lte=limite, versements__facture=None).distinct())
        prets = 0
        for c in sans_facture:
            c.facturer_saison()
            prets += 1
        if prets:
            notifier_plus_tard(ent.pk, "Factures de la saison prêtes",
                               f"{prets} facture{'s' if prets > 1 else ''} de saison à vérifier et envoyer. Rien ne part sans vous.",
                               url="/factures/versements/")
        n += prets
        # Factures de saison dont l'envoi était prévu pour aujourd'hui (client inscrit d'avance)
        from facturation.models import Facture

        prevues = Facture.objects.filter(entreprise=ent, statut=Facture.Statut.BROUILLON, envoyer_le=aujourdhui).count()
        if prevues:
            notifier_plus_tard(ent.pk, "Factures prévues pour aujourd'hui",
                               f"{prevues} facture{'s' if prevues > 1 else ''} de saison à envoyer aujourd'hui. Rien ne part sans vous.",
                               url="/factures/versements/")
        n += prevues
        # Avisé le jour où le rappel devient possible (pas tous les jours ensuite)
        nouveaux = [v for v, _ in a_rappeler(ent, aujourdhui) if v.date_prevue - timedelta(days=ent.jours_avance_versement) == aujourdhui]
        if nouveaux:
            notifier_plus_tard(ent.pk, "Rappels de versement à envoyer",
                               f"{len(nouveaux)} rappel{'s' if len(nouveaux) > 1 else ''} de versement à envoyer. Rien ne part sans vous.",
                               url="/factures/versements/")
        n += len(nouveaux)
    if n:
        log.info("rappels de versement : %s à envoyer", n)
    return n


# Procrastinate compte en UTC : 6 h UTC = 1 h à Sainte-Adèle (2 h en été), avant la journée de Louis
@app.periodic(cron="0 6 * * *")
@app.task(queue="facturation", queueing_lock="aviser_rappels_de_versement")
def aviser_rappels_de_versement_chaque_nuit(timestamp):
    return aviser_rappels_de_versement()


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
