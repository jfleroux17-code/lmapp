"""Envoi groupé (PRD E10, K6) : à tous les clients servis ou à un secteur.

Avis de service (tempête, fin de saison, changement d'horaire) : à tous, désabonnés compris (permis par la LCAP).
Message commercial (renouvellement, offres) : seulement aux clients qui y ont consenti et ne se sont pas désabonnés.
Chaque client reçoit un seul message, par son canal préféré (sinon l'autre). Garde-fous habituels (interrupteur,
destinataires du test).
"""
from clients.models import Client
from communications import envoi
from communications.models import Genre, Message
from communications.relances import canaux


def destinataires(entreprise, secteur=None, commercial=False):
    qs = Client.objects.filter(entreprise=entreprise, statut__in=[Client.Statut.ACTIF, Client.Statut.RECOUVREMENT])
    if secteur is not None:
        qs = qs.filter(adresses__secteur=secteur, adresses__active=True)
    if commercial:
        qs = qs.filter(consentement_commercial=True, desabonne_le__isnull=True)
    clients = list(qs.distinct().order_by("nom", "prenom"))
    joignables = [(c, canaux(c)[0]) for c in clients if canaux(c)]
    return joignables, len(clients) - len(joignables)


def envoyer(entreprise, texte, secteur=None, commercial=False, sujet=""):
    joignables, _ = destinataires(entreprise, secteur, commercial)
    signature = entreprise.signature_messages or entreprise.nom
    corps = f"{texte.strip()}\n\n{signature}"
    if commercial:
        corps += "\nPour ne plus recevoir ces messages, répondez ARRÊT."  # LCAP : mécanisme de désabonnement
    genre = Genre.GROUPE_COMMERCIAL if commercial else Genre.GROUPE_SERVICE
    messages = []
    for client, canal in joignables:
        courriel = canal == Message.Canal.COURRIEL
        m = Message.objects.create(entreprise=entreprise, client=client, genre=genre, canal=canal,
                                   destinataire=client.courriel if courriel else client.cellulaire,
                                   sujet=(sujet or f"Message de {entreprise.nom}") if courriel else "", contenu=corps)
        messages.append(envoi.envoyer(m))
    return messages
