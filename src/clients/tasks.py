"""Tâches en arrière-plan des clients, exécutées par le worker (Procrastinate)."""
import logging

from django.contrib.gis.geos import Point
from procrastinate import RetryStrategy
from procrastinate.contrib.django import app

from clients import geocodage
from clients.models import Adresse

log = logging.getLogger(__name__)


def geocoder_maintenant(adresse):
    """Géocode une adresse et l'enregistre. Ne touche jamais une position manuelle ou GPS."""
    if adresse.position_source in (Adresse.SourcePosition.MANUELLE, Adresse.SourcePosition.GPS):
        return "ignorée (position manuelle)"
    r = geocodage.geocoder(adresse.ligne1, adresse.ville, adresse.province, adresse.code_postal)
    if r is None:
        adresse.position = None
        adresse.position_source = ""
        adresse.position_precision = Adresse.Precision.INTROUVABLE
        adresse.geocodage_note = "Introuvable, même à la ville : placer à la main sur la carte."
    else:
        adresse.position = Point(r.longitude, r.latitude, srid=4326)
        adresse.position_source = Adresse.SourcePosition.GEOCODAGE
        adresse.position_precision = r.precision
        adresse.geocodage_note = r.libelle[:300]
    # update_fields : ne pas relancer le géocodage (voir signals.py) ni écraser d'autres champs
    adresse.save(update_fields=["position", "position_source", "position_precision", "geocodage_note", "modifie_le"])
    return adresse.get_position_precision_display()


# Une seule file pour le géocodage; le worker en traite une tâche à la fois et
# geocodage.py fait la pause d'une seconde entre deux requêtes.
@app.task(queue="geocodage", retry=RetryStrategy(max_attempts=5, exponential_wait=30, retry_exceptions={geocodage.ServiceIndisponible}))
def geocoder_adresse(adresse_id):
    try:
        adresse = Adresse.objects.get(pk=adresse_id)
    except Adresse.DoesNotExist:
        return
    resultat = geocoder_maintenant(adresse)
    log.info("Géocodage de l'adresse %s : %s", adresse_id, resultat)
