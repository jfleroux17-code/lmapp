"""Prévision au point exact de la ville desservie (demande de Louis, option 1 retenue par JF le 12 novembre 2026).

Environnement Canada n'a pas de page de prévision pour chaque municipalité (aucune pour Sainte-Adèle). Son modèle à
haute résolution (HRDPS, grille de 2,5 km) se lit au point près par le service GeoMet (WMS GetFeatureInfo, gratuit,
licence ouverte du gouvernement, usage commercial permis) : une couche et une heure par requête.

Par tranches de 6 heures, sur 36 heures : précipitations totales, pluie et pluie verglaçante (accumulées depuis le
début de l'exécution du modèle : on fait la différence entre le début et la fin de la tranche), neige = le reste
(équivalent en eau, 1 mm ≈ 1 cm de neige), température au début et à la fin. Toutes les requêtes d'une lecture
utilisent la même exécution du modèle (dim_reference_time de la première réponse).
Lu par le worker (l'app n'a pas Internet), aux 3 heures (le modèle sort aux 6 heures).
"""
import json
from datetime import datetime, timedelta, timezone as tz
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

COUCHES = {"pr": "HRDPS.CONTINENTAL_PR", "rn": "HRDPS.CONTINENTAL_RN", "fr": "HRDPS.CONTINENTAL_FR", "tt": "HRDPS.CONTINENTAL_TT"}
TRANCHE_H = 6
NB_TRANCHES = 6


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _valeur(couche, lat, lon, quand, reference=None):
    d = 0.01
    params = {"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetFeatureInfo", "LAYERS": couche, "QUERY_LAYERS": couche,
              "CRS": "EPSG:4326", "BBOX": f"{lat - d},{lon - d},{lat + d},{lon + d}", "WIDTH": 3, "HEIGHT": 3, "I": 1, "J": 1,
              "INFO_FORMAT": "application/json", "TIME": _iso(quand)}
    if reference:
        params["DIM_REFERENCE_TIME"] = reference
    req = Request(f"{settings.METEO_WMS}?{urlencode(params)}", headers={"User-Agent": "LMAPP"})
    with urlopen(req, timeout=20) as r:
        donnees = json.load(r)
    p = donnees["features"][0]["properties"]
    return float(p["value"]), p.get("dim_reference_time")


def prevoir(lat, lon, maintenant=None):
    """[{debut, fin (ISO, UTC), neige_cm, pluie_mm, verglas_mm, temp_min, temp_max}], exécution du modèle (ISO)."""
    maintenant = maintenant or datetime.now(tz.utc)
    t0 = maintenant.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    heures = [t0 + timedelta(hours=TRANCHE_H * k) for k in range(NB_TRANCHES + 1)]
    _, reference = _valeur(COUCHES["pr"], lat, lon, heures[0])
    valeurs = {}
    for cle, couche in COUCHES.items():
        valeurs[cle] = []
        for h in heures:
            try:
                v, _ = _valeur(couche, lat, lon, h, reference)
            except (KeyError, IndexError, ValueError):  # au-delà de la fin du modèle (48 h)
                break
            valeurs[cle].append(v)
    n = min(len(v) for v in valeurs.values())
    tranches = []
    for k in range(n - 1):
        def delta(cle):
            return max(0.0, valeurs[cle][k + 1] - valeurs[cle][k])

        total, pluie, verglas = delta("pr"), delta("rn"), delta("fr")
        neige = max(0.0, total - pluie - verglas)
        tranches.append({"debut": _iso(heures[k]), "fin": _iso(heures[k + 1]), "neige_cm": round(neige, 1), "pluie_mm": round(pluie, 1),
                         "verglas_mm": round(verglas, 1), "temp_min": round(min(valeurs["tt"][k], valeurs["tt"][k + 1])),
                         "temp_max": round(max(valeurs["tt"][k], valeurs["tt"][k + 1]))})
    return tranches, reference


def relever_point(meteo):
    """Met à jour la prévision au point de la ville desservie par défaut. Les erreurs gardent l'ancienne prévision."""
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    from core.models import VilleDesservie

    ent = meteo.entreprise
    v = (VilleDesservie.objects.filter(entreprise=ent, par_defaut=True).exclude(centre=None).first()
         or VilleDesservie.objects.filter(entreprise=ent).exclude(centre=None).first())
    if v is None:
        return meteo
    tranches, reference = prevoir(v.centre.y, v.centre.x)
    if tranches:
        meteo.point, meteo.point_lieu, meteo.point_lu_le = tranches, v.nom, timezone.now()
        meteo.point_modele_le = parse_datetime(reference) if reference else None
        meteo.save(update_fields=["point", "point_lieu", "point_lu_le", "point_modele_le"])
    return meteo
