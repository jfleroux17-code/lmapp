"""Envoi d'une facture au client (PRD C4) : par courriel, PDF joint; par texto, avec le lien public de la facture (L1)."""
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


def _texto(f):
    """Court : le montant, l'échéance et le lien vers la page de la facture (le PDF s'y télécharge)."""
    ent = f.entreprise
    if f.genre == Facture.Genre.SOLDE_OUVERTURE:
        quoi = f"le solde de votre compte : {argent(f.solde)}"
    else:
        quoi = f"votre facture n° {f.numero} : {argent(f.total)}"
        if f.solde != f.total:
            quoi += f", solde à payer {argent(f.solde)}"
    echeance = f", à payer au plus tard le {formats.date_format(f.date_echeance, 'j F')}" if f.date_echeance and f.solde > 0 else ""
    return f"Bonjour {f.client.nom_affiche}, voici {quoi}{echeance}. Pour la voir : {f.lien_public()}\n{ent.signature_messages or ent.nom}"


def sujet(f):
    if f.genre == Facture.Genre.SOLDE_OUVERTURE:
        return f"Solde de votre compte : {f.entreprise.nom}"
    return f"Facture n° {f.numero} : {f.entreprise.nom}"


def envoyer_facture(f, canal=Message.Canal.COURRIEL):
    """Crée le message et le confie à l'envoi. La facture doit être émise, et le client avoir un courriel
    (PDF joint) ou un cellulaire (lien vers la facture)."""
    if f.statut != Facture.Statut.EMISE:
        raise ValidationError("Seule une facture émise peut être envoyée.")
    if canal == Message.Canal.TEXTO:
        if not f.client.cellulaire:
            raise ValidationError("Ce client n'a pas de cellulaire.")
        m = Message.objects.create(entreprise=f.entreprise, client=f.client, genre=Genre.FACTURE, canal=canal,
                                   destinataire=f.client.cellulaire, contenu=_texto(f), facture=f)
        return envoi.envoyer(m)
    if not f.client.courriel:
        raise ValidationError("Ce client n'a pas d'adresse courriel.")
    m = Message.objects.create(entreprise=f.entreprise, client=f.client, genre=Genre.FACTURE, canal=Message.Canal.COURRIEL,
                               destinataire=f.client.courriel, sujet=sujet(f), contenu=_texte(f), facture=f)
    return envoi.envoyer(m)
