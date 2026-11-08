"""Envoi d'une facture par courriel au client, PDF joint (PRD C4)."""
from django.core.exceptions import ValidationError
from django.utils import formats

from communications import envoi
from communications.models import Genre, Message
from facturation.models import Facture
from facturation.templatetags.argent import argent


def _texte(f):
    ent = f.entreprise
    if f.genre == Facture.Genre.SOLDE_OUVERTURE:
        corps = f"Voici le solde de votre compte{f' (saison {f.saison_origine})' if f.saison_origine else ''} : {argent(f.solde)}."
    else:
        corps = f"Voici votre facture n° {f.numero} du {formats.date_format(f.date_facture, 'j F Y')}, au montant de {argent(f.total)}."
        if f.solde != f.total:
            corps += f" Solde à payer : {argent(f.solde)}."
    if f.date_echeance and f.solde > 0:
        corps += f"\nÀ payer au plus tard le {formats.date_format(f.date_echeance, 'j F Y')}."
    lignes = [f"Bonjour {f.client.nom_affiche},", corps]
    if f.solde > 0 and ent.interac_courriel:
        reference = f", en indiquant le numéro de facture {f.numero}" if f.numero else ""
        lignes.append(f"Paiement par virement Interac à {ent.interac_courriel}{reference}.")
    lignes.append("Merci!")
    lignes.append(ent.signature_messages or ent.nom)
    return "\n\n".join(lignes)


def sujet(f):
    if f.genre == Facture.Genre.SOLDE_OUVERTURE:
        return f"Solde de votre compte : {f.entreprise.nom}"
    return f"Facture n° {f.numero} : {f.entreprise.nom}"


def envoyer_facture(f):
    """Crée le message (PDF joint) et le confie à l'envoi. La facture doit être émise et le client avoir un courriel."""
    if f.statut != Facture.Statut.EMISE:
        raise ValidationError("Seule une facture émise peut être envoyée.")
    if not f.client.courriel:
        raise ValidationError("Ce client n'a pas d'adresse courriel.")
    m = Message.objects.create(entreprise=f.entreprise, client=f.client, genre=Genre.FACTURE, canal=Message.Canal.COURRIEL,
                               destinataire=f.client.courriel, sujet=sujet(f), contenu=_texte(f), facture=f)
    return envoi.envoyer(m)
