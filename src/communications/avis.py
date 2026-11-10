"""Avis aux clients pendant une opération (PRD G2 à G5).

Messages de service (permis par la LCAP sans consentement) : envoyés aussi aux
clients désabonnés des messages commerciaux. Un seul avis de chaque genre par
client et par opération (G3), garanti par la base.
"""
from django.contrib.gis.measure import D
from django.db import IntegrityError, transaction
from django.utils import timezone

from clients.models import Adresse, Client
from communications import envoi
from communications.models import Gabarit, Genre, Message
from tournee.models import Passage, arrets


def _signature(entreprise):
    return entreprise.signature_messages or entreprise.nom


def _canal(client, genre):
    """Texto si le client a un cellulaire; courriel pour le début d'opération seulement (trop lent pour la proximité)."""
    if client.cellulaire and client.canal_prefere in (Client.Canal.TEXTO, Client.Canal.LES_DEUX):
        return Message.Canal.TEXTO, client.cellulaire
    if client.cellulaire and genre != Genre.DEBUT:
        return Message.Canal.TEXTO, client.cellulaire
    if genre == Genre.DEBUT and client.courriel:
        return Message.Canal.COURRIEL, client.courriel
    if client.cellulaire:
        return Message.Canal.TEXTO, client.cellulaire
    return None, None


def _creer(operation, client, genre, delai=0, **variables):
    canal, dest = _canal(client, genre)
    if canal is None:
        return None
    ent = operation.entreprise
    texte = Gabarit.texte_pour(ent, genre)
    try:
        texte = texte.format(client=client.nom_affiche, **variables)
    except (KeyError, IndexError, ValueError):
        pass  # gabarit modifié avec une variable inconnue : on l'envoie tel quel plutôt que de bloquer l'avis
    try:
        with transaction.atomic():
            m = Message.objects.create(entreprise=ent, client=client, operation=operation, genre=genre, canal=canal,
                                       destinataire=dest, contenu=f"{texte}\n{_signature(ent)}")
    except IntegrityError:
        return None  # déjà avisé pour cette opération (G3)
    return envoi.envoyer(m, delai=delai)


def _deja(operation, genre):
    return set(Message.objects.filter(operation=operation, genre=genre).values_list("client_id", flat=True))


def _minutes(entreprise, arrets_avant):
    return max(5, (arrets_avant + 1) * entreprise.minutes_par_arret)


DELAI_ANNULATION_DEBUT = 10  # secondes pour annuler les avis de début après « Démarrer » (tap accidentel)


def clients_a_aviser_au_debut(entreprise):
    """Clients servis joignables (cellulaire ou courriel) : ceux qui recevront l'avis de début."""
    from django.db.models import Q

    return (Client.objects.filter(entreprise=entreprise, statut__in=[Client.Statut.ACTIF, Client.Statut.RECOUVREMENT],
                                  adresses__active=True).exclude(Q(cellulaire="") & Q(courriel="")).distinct())


def aviser_debut(operation, delai=0):
    """G5 : à chaque client servi, une fois, au début de l'opération. delai : secondes avant l'envoi
    réel, le temps d'annuler (annuler_avis_debut)."""
    deja, n = _deja(operation, Genre.DEBUT), 0
    for c in Client.objects.filter(entreprise=operation.entreprise, statut__in=[Client.Statut.ACTIF, Client.Statut.RECOUVREMENT],
                                   adresses__active=True).distinct():
        if c.pk not in deja and _creer(operation, c, Genre.DEBUT, delai=delai):
            n += 1
    return n


def annuler_avis_debut(operation):
    """Avis de début encore en file (pas partis) : retenus. Renvoie le nombre retenu."""
    return Message.objects.filter(operation=operation, genre=Genre.DEBUT, statut=Message.Statut.EN_FILE).update(
        statut=Message.Statut.PREPARE, erreur="Avis de début annulé avant l'envoi.", modifie_le=timezone.now())


def _restants(operation):
    faits = set(operation.passages.values_list("adresse_id", flat=True))
    return [a for a in arrets(operation.entreprise) if a.pk not in faits]


def _aviser_adresses(operation, cibles, restants):
    """Un avis de proximité par client des adresses cibles, avec l'estimation selon le rang dans ce qui reste."""
    deja, n = _deja(operation, Genre.PROXIMITE), 0
    rang = {a.pk: i for i, a in enumerate(restants)}
    for a in sorted(cibles, key=lambda x: rang.get(x.pk, 0)):
        if a.client_id in deja:
            continue
        if _creer(operation, a.client, Genre.PROXIMITE, adresse=a.ligne1, minutes=_minutes(operation.entreprise, rang.get(a.pk, 0))):
            deja.add(a.client_id)
            n += 1
    return n


def aviser_proximite(operation, point):
    """G2 : clients dans le rayon de la position de Louis, pas encore servis, position précise."""
    ent = operation.entreprise
    if not ent.avis_proximite_actif:
        return 0
    restants = _restants(operation)
    ids = {a.pk for a in restants}
    proches = (Adresse.objects.filter(pk__in=ids, position__dwithin=(point, D(m=ent.avis_rayon_m)))
               .exclude(position_precision__in=[Adresse.Precision.VILLE, Adresse.Precision.INTROUVABLE], position_source="geocodage")
               .select_related("client"))
    return _aviser_adresses(operation, list(proches), restants)


def aviser_prochains(operation, nombre=3):
    """G4 : avis de secours aux N prochains arrêts (géolocalisation en panne)."""
    restants = _restants(operation)
    return _aviser_adresses(operation, restants[:nombre], restants)


def aviser_secteur(operation, secteur_id):
    """G4 : avis de secours à tout un secteur."""
    restants = _restants(operation)
    return _aviser_adresses(operation, [a for a in restants if a.secteur_id == secteur_id], restants)


def aviser_passage_fait(passage):
    """G5 : « c'est fait », si l'entreprise l'a activé."""
    op = passage.operation
    if not op.entreprise.avis_passage_fait or passage.statut != Passage.Statut.FAIT:
        return None
    return _creer(op, passage.adresse.client, Genre.PASSAGE_FAIT, adresse=passage.adresse.ligne1,
                  heure=timezone.localtime(passage.heure).strftime("%H h %M"))
