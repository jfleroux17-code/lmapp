"""Relances proposées (PRD C9, option B choisie par JF le 9 novembre 2026).

L'app dresse chaque jour la liste des relances dues; le déneigeur les envoie d'une tape (écran
« Relances à envoyer », `/comptes/relances/`). **Rien ne part tout seul.**

Calendrier, compté depuis l'échéance (sinon la date) de la plus vieille facture due : rappel à 15 jours,
deuxième avis à 30, dernier avis à 60. Après le dernier avis, plus rien n'est proposé : la suite est
au déneigeur. Au moins ECART_JOURS jours entre deux relances (une relance à la main compte).

Jamais proposé : le client qui ne doit plus rien (arrêt dès que payé), celui qui a une demande ouverte
(plainte, dommage, etc.), celui marqué « ne pas relancer », celui dont la relance est reportée, celui
sans cellulaire ni courriel. Les soldes des saisons antérieures seulement si l'entreprise l'a choisi.
Le message est celui du C8 (tout ce que le client doit, par son canal préféré).
"""
from datetime import timedelta

from django.utils import timezone

from communications import relances
from communications.models import RELANCES, Genre, Message
from demandes.models import Demande
from facturation.models import Facture

SEUILS = {1: 15, 2: 30, 3: 60}
ECART_JOURS = 7
REPORT_JOURS = 7


def _echeance(f):
    return f.date_echeance or f.date_facture


def proposition(client, dues, aujourdhui):
    """Le niveau proposé pour ce client aujourd'hui (avec les détails), ou None."""
    ent = client.entreprise
    if not dues or client.ne_pas_relancer or client.efface_le:
        return None
    if client.relance_reportee_au and client.relance_reportee_au > aujourdhui:
        return None
    visees = dues if ent.relances_soldes_anterieurs else [f for f in dues if f.genre != Facture.Genre.SOLDE_OUVERTURE]
    if not visees:
        return None
    jours = (aujourdhui - min(_echeance(f) for f in visees)).days
    plus_haut = relances.plus_haute_relance(client, dues)
    if plus_haut >= 3:
        return None
    niveau = plus_haut + 1
    if jours < SEUILS[niveau]:
        return None
    derniere = relances.relances_du_client(client).order_by("-cree_le").first()
    if derniere and derniere.cree_le > timezone.now() - timedelta(days=ECART_JOURS):
        return None
    canaux = relances.canaux(client)
    if not canaux:
        return None
    if Demande.objects.filter(client=client).exclude(statut=Demande.Statut.REGLEE).exists():
        return None
    if client.cheques.filter(statut="en_main").exists():
        return None  # D9 : chèque postdaté en main, l'argent s'en vient
    return {"client": client, "niveau": niveau, "genre": RELANCES[niveau - 1], "genre_label": Genre(RELANCES[niveau - 1]).label,
            "jours": jours, "du": sum(f.solde_du for f in dues), "factures": len(dues), "derniere": derniere,
            "canaux_texte": " et ".join(dict(Message.Canal.choices)[c].lower() for c in canaux)}


def proposees(entreprise, aujourdhui=None):
    """Les relances dues aujourd'hui pour l'entreprise, plus vieux compte d'abord."""
    aujourdhui = aujourdhui or timezone.localdate()
    par_client = {}
    for f in (Facture.objects.filter(entreprise=entreprise).a_recevoir()
              .select_related("client", "client__entreprise").order_by("date_facture", "pk")):
        par_client.setdefault(f.client_id, []).append(f)
    resultat = [p for dues in par_client.values() if (p := proposition(dues[0].client, dues, aujourdhui))]
    resultat.sort(key=lambda p: -p["jours"])
    return resultat
