"""Prévisions d'Environnement et Changement climatique Canada (PRD I1), par l'API GeoMet (OGC API, JSON, gratuite).
Appelée par le worker aux 30 minutes; l'app lit la copie gardée dans la base (core.Meteo)."""
import json
import math
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

COLLECTION = "/collections/citypageweather-realtime/items"


def _lire(chemin, **params):
    req = Request(f"{settings.METEO_API}{chemin}?{urlencode({'f': 'json', 'lang': 'fr', **params})}", headers={"User-Agent": "LMAPP"})
    with urlopen(req, timeout=20) as r:
        return json.load(r)


def _fr(v):
    return v.get("fr") if isinstance(v, dict) else v


def ville_proche(lat, lng):
    """(identifiant, nom) de la ville de prévision la plus proche, cherchée dans un carré de 1,2 degré."""
    d = _lire(COLLECTION, bbox=f"{lng - 0.6},{lat - 0.6},{lng + 0.6},{lat + 0.6}", limit=50)
    meilleure = None
    for f in d.get("features", []):
        x, y = f["geometry"]["coordinates"][:2]
        dist = math.hypot((x - lng) * math.cos(math.radians(lat)), y - lat)
        if meilleure is None or dist < meilleure[0]:
            meilleure = (dist, f["id"], _fr(f["properties"]["name"]))
    return (meilleure[1], meilleure[2]) if meilleure else (None, None)


def analyser(p):
    """Propriétés GeoMet d'une ville -> (périodes, avertissements, publiée le, lien)."""
    periodes = []
    for f in (p.get("forecastGroup") or {}).get("forecasts", [])[:6]:
        acc = (f.get("precipitation") or {}).get("accumulation") or {}
        genre, quantite = _fr(acc.get("name") or {}), _fr((acc.get("amount") or {}).get("value"))
        periodes.append({
            "nom": _fr(f["period"]["textForecastName"]),
            "resume": _fr(f.get("textSummary") or ""),
            "neige_cm": quantite if genre in ("neige", "snow") else None,
            "pluie_mm": quantite if genre in ("pluie", "rain") else None,
        })
    avertissements = []
    for w in p.get("warnings") or []:
        for e in (w.get("event") if isinstance(w.get("event"), list) else [w.get("event") or w]):
            texte = _fr((e or {}).get("description") or (e or {}).get("name") or "")
            if texte:
                avertissements.append(texte)
    publiee = parse_datetime(_fr((p.get("forecastGroup") or {}).get("timestamp") or "") or "")
    return periodes, avertissements, publiee, _fr(p.get("url") or "")


def relever(entreprise):
    from core.models import Meteo, VilleDesservie

    m, _ = Meteo.objects.get_or_create(entreprise=entreprise)
    try:
        if not m.ville_id:
            v = VilleDesservie.objects.filter(entreprise=entreprise, par_defaut=True).exclude(centre=None).first() or \
                VilleDesservie.objects.filter(entreprise=entreprise).exclude(centre=None).first()
            if v is None:
                m.erreur = "Aucune ville desservie avec un centre : impossible de choisir la ville de prévision."
                m.save(update_fields=["erreur"])
                return m
            m.ville_id, m.ville_nom = ville_proche(v.centre.y, v.centre.x)
            if not m.ville_id:
                m.erreur = "Aucune ville de prévision trouvée près de la ville desservie."
                m.save(update_fields=["erreur", "ville_id", "ville_nom"])
                return m
        p = _lire(f"{COLLECTION}/{m.ville_id}")["properties"]
        m.periodes, m.avertissements, m.publiee_le, m.lien = analyser(p)
        m.lue_le, m.erreur = timezone.now(), ""
    except Exception as e:  # noqa: BLE001 : on garde les dernières prévisions et on réessaie plus tard
        m.erreur = f"{type(e).__name__} : {e}"[:300]
    m.save()
    return m
