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
import math
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


@dataclass(frozen=True)
class Zone:
    """Zone de service d'une ville desservie : centre et rayon en kilomètres."""

    latitude: float
    longitude: float
    rayon_km: float

    def boite(self):
        """Boîte englobante pour le paramètre viewbox de Nominatim (gauche, haut, droite, bas)."""
        dlat = self.rayon_km / 111.0
        dlon = self.rayon_km / (111.0 * math.cos(math.radians(self.latitude)))
        return f"{self.longitude - dlon:.5f},{self.latitude + dlat:.5f},{self.longitude + dlon:.5f},{self.latitude - dlat:.5f}"

    def distance_km(self, latitude, longitude):
        """Distance à vol d'oiseau (formule de haversine)."""
        r = 6371.0
        p1, p2 = math.radians(self.latitude), math.radians(latitude)
        dp, dl = p2 - p1, math.radians(longitude - self.longitude)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    def contient(self, latitude, longitude):
        return self.distance_km(latitude, longitude) <= self.rayon_km


def geocoder(ligne1, ville, province="QC", code_postal="", zone=None):
    """Retourne un Resultat, ou None si l'adresse est introuvable.

    Avec une zone (ville desservie) : la recherche est limitée à la zone, et un
    résultat qui tombe hors du rayon est rejeté (une rue du même nom dans une
    autre ville). Sans zone : recherche dans tout le Canada.

    Essais, du plus précis au moins précis :
      1. rue et ville (recherche structurée);
      2. la ville seulement : le centre de la zone si on le connaît (aucune
         requête), sinon demandé à Nominatim. Précision « ville » : à corriger.
    """
    etat = PROVINCES.get((province or "QC").upper(), province)
    params = {"street": _rue_sans_unite(ligne1), "city": ville, "state": etat, "country": "Canada"}
    if zone is not None:
        params.update({"viewbox": zone.boite(), "bounded": 1})
    if ligne1 and ville:
        reponse = _requete(params)
        for r in reponse or []:
            lat, lon = float(r["lat"]), float(r["lon"])
            if zone is not None and not zone.contient(lat, lon):
                log.warning("Géocodage : résultat hors zone rejeté (%.1f km du centre) : %s", zone.distance_km(lat, lon), r.get("display_name", ""))
                continue
            return Resultat(lat, lon, _precision(r), r.get("display_name", ""))
    if zone is not None:
        return Resultat(zone.latitude, zone.longitude, "ville", f"Centre de la zone de {ville} (adresse non trouvée)")
    if ville:
        reponse = _requete({"city": ville, "state": etat, "country": "Canada"})
        if reponse:
            r = reponse[0]
            return Resultat(float(r["lat"]), float(r["lon"]), "ville", r.get("display_name", ""))
    return None


def centre_ville(ville, province="QC"):
    """Centre d'une ville, pour remplir la zone d'une ville desservie."""
    etat = PROVINCES.get((province or "QC").upper(), province)
    reponse = _requete({"city": ville, "state": etat, "country": "Canada"})
    if not reponse:
        return None
    return float(reponse[0]["lat"]), float(reponse[0]["lon"])
