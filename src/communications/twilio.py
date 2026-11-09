"""Appel à l'API de Twilio pour envoyer un texto (PRD M1), sans dépendance de plus (urllib).

Appelé par le worker seulement : l'app (Gunicorn) n'a pas de sortie Internet.
"""
import base64
import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.conf import settings

from communications.erreurs import Incertain, Indisponible, Refuse  # noqa: F401 (utilisées aussi par les appelants)



def envoyer_texto(de, a, texte):
    """Retourne l'identifiant Twilio du message (SM...)."""
    sid, jeton = settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN
    cle = base64.b64encode(f"{sid}:{jeton}".encode()).decode()
    req = Request(f"{settings.TWILIO_API}/2010-04-01/Accounts/{sid}/Messages.json",
                  data=urlencode({"From": de, "To": a, "Body": texte,
                                  **({"StatusCallback": settings.TWILIO_URL_STATUT} if settings.TWILIO_URL_STATUT else {})}).encode(),
                  headers={"Authorization": f"Basic {cle}", "User-Agent": "LMAPP"})
    try:
        with urlopen(req, timeout=20) as r:
            return json.load(r)["sid"]
    except HTTPError as e:
        try:
            detail = json.load(e)
            raison = f"Twilio {detail.get('code', e.code)} : {detail.get('message', '')}"
        except ValueError:
            raison = f"Twilio HTTP {e.code}"
        if e.code == 429 or e.code >= 500:
            raise Indisponible(raison) from e
        raise Refuse(raison) from e
    except URLError as e:  # connexion impossible : la demande n'est pas partie
        raise Indisponible(f"Twilio injoignable : {e.reason}") from e
    except TimeoutError as e:
        raise Incertain("Pas de réponse de Twilio : vérifier dans la console Twilio avant de renvoyer.") from e


def prix(sid):
    """(prix positif en Decimal, devise) d'un message (E13), ou None si Twilio ne l'a pas encore établi."""
    from decimal import Decimal

    compte, jeton = settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN
    cle = base64.b64encode(f"{compte}:{jeton}".encode()).decode()
    req = Request(f"{settings.TWILIO_API}/2010-04-01/Accounts/{compte}/Messages/{sid}.json",
                  headers={"Authorization": f"Basic {cle}", "User-Agent": "LMAPP"})
    with urlopen(req, timeout=20) as r:
        d = json.load(r)
    if d.get("price") in (None, ""):
        return None
    return abs(Decimal(str(d["price"]))), (d.get("price_unit") or "USD")[:3]
