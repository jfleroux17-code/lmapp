"""Tâches du volet argent, exécutées par le worker (Procrastinate)."""
import logging

from django.utils import timezone
from procrastinate.contrib.django import app

from facturation.models import Versement

log = logging.getLogger(__name__)


def facturer_versements_dus(aujourdhui=None):
    """C5 : un brouillon de facture pour chaque versement arrivé à sa date et pas encore facturé.

    Seulement des brouillons : rien n'est émis ni envoyé sans Louis. Relançable
    sans danger (un versement déjà facturé est sauté).
    """
    aujourdhui = aujourdhui or timezone.localdate()
    dus = (Versement.objects.filter(facture=None, date_prevue__lte=aujourdhui, contrat__actif=True)
           .select_related("contrat__entreprise", "contrat__client", "contrat__saison").order_by("date_prevue", "pk"))
    n = 0
    for v in dus:
        v.facturer()
        n += 1
    if n:
        log.info("versements dus : %s brouillon(s) de facture créé(s)", n)
    return n


# Procrastinate compte en UTC : 6 h UTC = 1 h à Sainte-Adèle (2 h en été), avant la journée de Louis
@app.periodic(cron="0 6 * * *")
@app.task(queue="facturation", queueing_lock="facturer_versements_dus")
def facturer_versements_dus_chaque_nuit(timestamp):
    return facturer_versements_dus()
