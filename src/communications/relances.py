"""Relances des comptes en souffrance (PRD C8) : en un geste, ton gradué (rappel, deuxième avis, dernier avis).

Une relance porte sur tout ce que le client doit (factures émises avec un solde, soldes d'ouverture
compris). Par courriel, le PDF de chaque facture est joint; par texto, le montant seulement. Canal :
celui que le client préfère, l'autre si le premier manque. Message de recouvrement, pas commercial :
envoyé aussi aux désabonnés (LCAP). Au plus une relance par 24 heures (double tape, erreur).
"""
from datetime import timedelta

from core.templatetags.dates_qc import date_texte
from django.core.exceptions import ValidationError
from django.utils import formats, timezone

from clients.models import Client
from communications import envoi
from communications.models import RELANCES, Gabarit, Genre, Message
from facturation.models import Facture
from facturation.templatetags.argent import argent

COMPTEES = [Message.Statut.ENVOYE, Message.Statut.EN_FILE]  # une relance préparée ou bloquée n'est pas partie


def factures_dues(client):
    return list(Facture.objects.filter(client=client).a_recevoir().order_by("date_facture", "pk"))


def relances_du_client(client):
    return Message.objects.filter(client=client, genre__in=RELANCES, statut__in=COMPTEES)


def plus_haute_relance(client, dues):
    """0 à 3 : la plus haute relance partie depuis la plus vieille facture due (courriel et texto comptent une fois)."""
    genres = set(relances_du_client(client).filter(cree_le__date__gte=dues[0].date_facture).values_list("genre", flat=True))
    return max((RELANCES.index(g) + 1 for g in genres), default=0)


def niveau_suivant(client, dues=None):
    """1, 2 ou 3 : le niveau qui suit la plus haute relance partie depuis la plus vieille facture due."""
    dues = factures_dues(client) if dues is None else dues
    if not dues:
        return None
    return min(plus_haute_relance(client, dues) + 1, 3)


def canaux(client):
    courriel, texto = bool(client.courriel), bool(client.cellulaire)
    if client.canal_prefere == Client.Canal.LES_DEUX:
        choix = [c for c, ok in ((Message.Canal.COURRIEL, courriel), (Message.Canal.TEXTO, texto)) if ok]
    elif client.canal_prefere == Client.Canal.COURRIEL:
        choix = [Message.Canal.COURRIEL] if courriel else [Message.Canal.TEXTO] if texto else []
    else:
        choix = [Message.Canal.TEXTO] if texto else [Message.Canal.COURRIEL] if courriel else []
    return choix


def _description(dues):
    morceaux = []
    for f in dues[:4]:
        if f.genre == Facture.Genre.SOLDE_OUVERTURE:
            morceaux.append(f"solde antérieur{f' {f.saison_origine}' if f.saison_origine else ''}")
        else:
            morceaux.append(f"facture n° {f.numero}")
    if len(dues) > 4:
        morceaux.append(f"et {len(dues) - 4} autre{'s' if len(dues) > 5 else ''}")
    return ", ".join(morceaux)


def _texte(client, dues, genre):
    ent = client.entreprise
    total = sum(f.solde_du for f in dues)
    paiement = ""
    if ent.interac_courriel:
        numeros = [str(f.numero) for f in dues if f.numero]
        ref = f", en indiquant le{'s' if len(numeros) > 1 else ''} numéro{'s' if len(numeros) > 1 else ''} de facture {', '.join(numeros)}" if numeros else ""
        paiement = f"Paiement par virement Interac à {ent.interac_courriel}{ref}."
    gabarit = Gabarit.texte_pour(ent, genre)
    try:
        texte = gabarit.format(client=client.nom_affiche, montant=argent(total), factures=_description(dues),
                               depuis=date_texte(dues[0].date_facture), paiement=paiement)
    except (KeyError, IndexError, ValueError):
        texte = gabarit  # gabarit modifié avec une variable inconnue : envoyé tel quel plutôt que de bloquer
    return f"{texte.strip()}\n\n{ent.signature_messages or ent.nom}", total


def relancer(client, niveau=None):
    """Crée et confie à l'envoi la relance du client (un message par canal). Retourne les messages."""
    dues = factures_dues(client)
    if not dues:
        raise ValidationError("Ce client ne doit rien.")
    choix = canaux(client)
    if not choix:
        raise ValidationError("Ni cellulaire ni courriel dans la fiche du client.")
    if relances_du_client(client).filter(cree_le__gte=timezone.now() - timedelta(hours=24)).exists():
        raise ValidationError("Une relance est déjà partie dans les dernières 24 heures.")
    niveau = niveau or niveau_suivant(client, dues)
    if niveau not in (1, 2, 3):
        raise ValidationError("Niveau de relance inconnu.")
    genre = RELANCES[niveau - 1]
    texte, total = _texte(client, dues, genre)
    sujet = f"{Genre(genre).label} : solde de {argent(total)}, {client.entreprise.nom}"
    resultat = []
    for canal in choix:
        m = Message.objects.create(entreprise=client.entreprise, client=client, genre=genre, canal=canal,
                                   destinataire=client.courriel if canal == Message.Canal.COURRIEL else client.cellulaire,
                                   sujet=sujet if canal == Message.Canal.COURRIEL else "", contenu=texte)
        if canal == Message.Canal.COURRIEL:
            m.factures_jointes.set(dues)
        resultat.append(envoi.envoyer(m))
    return resultat


def dernieres(clients_ids):
    """Dernière relance (partie ou en file) par client, pour l'écran des comptes."""
    d = {}
    for m in Message.objects.filter(client_id__in=clients_ids, genre__in=RELANCES, statut__in=COMPTEES).order_by("-cree_le"):
        d.setdefault(m.client_id, m)
    return d
