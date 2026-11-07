"""Géocodage des adresses de service avec Nominatim (OpenStreetMap) (PRD A2, M3).

Règles d'utilisation du service public (operations.osmfoundation.org/policies/nominatim) :
  - au plus une requête par seconde : une seule requête à la fois, pause d'au
    moins NOMINATIM_PAUSE secondes entre deux requêtes de ce processus;
  - application identifiée par l'en-tête User-Agent;
  - pas de gros volumes : chaque adresse est géocodée une fois, puis gardée.

On n'envoie que l'adresse (rue, ville, code postal), jamais le nom du client.
NOMINATIM_URL permet de passer plus tard à un Nominatim installé sur ld1.
"""
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

log = logging.getLogger(__name__)

NOMINATIM_URL = os.environ.get("NOMINATIM_URL", "https://nominatim.openstreetmap.org").rstrip("/")
NOMINATIM_PAUSE = float(os.environ.get("NOMINATIM_PAUSE", "1.1"))
USER_AGENT = "LMAPP/0.1 (gestion de deneigement; +https://ledeneigeur.com)"

PROVINCES = {"QC": "Québec", "ON": "Ontario", "NB": "Nouveau-Brunswick"}

# Types de lieux Nominatim (addresstype) qui désignent un bâtiment ou un terrain précis
_BATIMENT = {"building", "house", "amenity", "shop", "office", "craft", "tourism", "leisure"}

@dataclass
class Resultat:
    latitude: float
    longitude: float
    precision: str  # "adresse", "rue" ou "ville"
    libelle: str


class ServiceIndisponible(Exception):
    """Nominatim ne répond pas (réseau, limite de débit) : réessayer plus tard."""


_verrou = threading.Lock()
_derniere_requete = 0.0


def _requete(params):
    global _derniere_requete
    url = f"{NOMINATIM_URL}/search?" + urllib.parse.urlencode({**params, "format": "jsonv2", "countrycodes": "ca", "limit": 1, "addressdetails": 1})
    with _verrou:
        attente = _derniere_requete + NOMINATIM_PAUSE - time.monotonic()
        if attente > 0:
            time.sleep(attente)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "fr"})
            with urllib.request.urlopen(req, timeout=15) as rep:
                return json.load(rep)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                raise ServiceIndisponible(f"Nominatim : HTTP {e.code}")
            raise
        except (urllib.error.URLError, TimeoutError) as e:
            raise ServiceIndisponible(f"Nominatim injoignable : {e}")
        finally:
            _derniere_requete = time.monotonic()


def _precision(resultat):
    """Du plus sûr au moins sûr : numéro civique trouvé, bâtiment, rue, sinon la ville.

    Attention : dans OpenStreetMap, une rue résidentielle a le type « residential »;
    c'est le type de lieu (addresstype) qui dit si c'est une rue ou un bâtiment.
    """
    if resultat.get("address", {}).get("house_number"):
        return "adresse"
    type_lieu = resultat.get("addresstype", "")
    if type_lieu in _BATIMENT:
        return "adresse"
    if type_lieu == "road" or resultat.get("category") == "highway":
        return "rue"
    return "ville"


def _rue_sans_unite(ligne1):
    """« 120, rue des Essais » -> « 120 rue des Essais » (Nominatim n'aime pas la virgule)."""
    return " ".join(ligne1.replace(",", " ").split())


def geocoder(ligne1, ville, province="QC", code_postal=""):
    """Retourne un Resultat, ou None si l'adresse est introuvable même à la ville.

    Essais, du plus précis au moins précis :
      1. rue et ville (recherche structurée);
      2. la ville seulement (précision « ville » : à corriger à la main).
    """
    etat = PROVINCES.get((province or "QC").upper(), province)
    essais = [
        {"street": _rue_sans_unite(ligne1), "city": ville, "state": etat, "country": "Canada"},
        {"city": ville, "state": etat, "country": "Canada"},
    ]
    for i, params in enumerate(essais):
        if not all(params.values()):
            continue
        reponse = _requete(params)
        if reponse:
            r = reponse[0]
            precision = "ville" if i == 1 else _precision(r)
            return Resultat(float(r["lat"]), float(r["lon"]), precision, r.get("display_name", ""))
    return None
