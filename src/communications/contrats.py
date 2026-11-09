"""Envoi du contrat au client (PRD B6) : par courriel, PDF joint; par texto, le lien du PDF."""
from django.core.exceptions import ValidationError

from communications import envoi
from communications.models import Genre, Message
from facturation.templatetags.argent import argent


def envoyer_contrat(c, canal=Message.Canal.COURRIEL):
    ent, client = c.entreprise, c.client
    signature = ent.signature_messages or ent.nom
    quoi = f"votre contrat de déneigement pour la saison {c.saison.nom} ({argent(c.prix)} avant taxes)"
    if canal == Message.Canal.TEXTO:
        if not client.cellulaire:
            raise ValidationError("Ce client n'a pas de cellulaire.")
        m = Message.objects.create(entreprise=ent, client=client, genre=Genre.CONTRAT, canal=canal, destinataire=client.cellulaire,
                                   contrat=c, contenu=f"Bonjour {client.nom_affiche}, voici {quoi} : {c.lien_public()}\n{signature}")
        return envoi.envoyer(m)
    if not client.courriel:
        raise ValidationError("Ce client n'a pas d'adresse courriel.")
    m = Message.objects.create(entreprise=ent, client=client, genre=Genre.CONTRAT, canal=Message.Canal.COURRIEL,
                               destinataire=client.courriel, contrat=c, sujet=f"Contrat, saison {c.saison.nom} : {ent.nom}",
                               contenu=f"Bonjour {client.nom_affiche},\n\nVoici {quoi}, en pièce jointe.\n\n"
                                       f"Pour toute question, répondez simplement à ce courriel.\n\nMerci!\n\n{signature}")
    return envoi.envoyer(m)
