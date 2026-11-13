"""Temps passé à chaque entrée (demande de Louis, 12 novembre 2026) : pour savoir si le prix d'un client tient.

À la fin d'une opération, pour chaque passage « Fait », dans l'ordre des tapes :
- arrivée = premier point GPS à moins de RAYON_M de l'entrée (précision du point comprise, 50 m au plus), entre la tape
  précédente (ou le début) et la tape de ce passage;
- sur place = de l'arrivée à la tape « Fait »; trajet = de la tape précédente à l'arrivée;
- depuis la tape précédente : toujours calculé (trajet et travail ensemble), utile sans GPS.
Sans position (GPS éteint, écran fermé) : seulement « depuis la tape précédente ». Relançable (commande
`calculer_temps`). Les valeurs restent sur les passages : les positions, elles, sont effacées après 120 jours.
"""
import math

RAYON_M = 60
PRECISION_MAX_M = 150
ECART_MAX_S = 3 * 3600  # au-delà (pause, dîner), « depuis la précédente » n'a pas de sens


def distance_m(lon1, lat1, lon2, lat2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def calculer(operation):
    from tournee.models import Passage

    passages = list(operation.passages.filter(statut=Passage.Statut.FAIT).select_related("adresse").order_by("heure", "pk"))
    points = [(pos.x, pos.y, moment, prec or 0) for pos, moment, prec
              in operation.positions.order_by("moment").values_list("position", "moment", "precision_m") if (prec or 0) <= PRECISION_MAX_M]
    precedent = operation.debut
    for p in passages:
        p.arrivee = p.sur_place_s = p.trajet_s = None
        ecart = (p.heure - precedent).total_seconds()
        p.depuis_precedent_s = int(ecart) if 0 <= ecart <= ECART_MAX_S else None
        a = p.adresse.position
        if a is not None:
            for lon, lat, moment, prec in points:
                if precedent <= moment <= p.heure and distance_m(lon, lat, a.x, a.y) <= RAYON_M + min(prec, 50):
                    p.arrivee = moment
                    p.sur_place_s = int((p.heure - moment).total_seconds())
                    p.trajet_s = int((moment - precedent).total_seconds()) if (moment - precedent).total_seconds() <= ECART_MAX_S else None
                    break
        precedent = p.heure
    Passage.objects.bulk_update(passages, ["arrivee", "sur_place_s", "trajet_s", "depuis_precedent_s"])
    return len(passages)


def minutes(secondes):
    """En minutes entières (au moins 1 si quelque chose a été mesuré)."""
    return None if secondes is None else max(1, round(secondes / 60)) if secondes > 0 else 0
