"""Rappels de versement (décision de JF, 12 novembre 2026) : une seule facture par saison; à la date d'un versement
(ou Entreprise.jours_avance_versement jours avant), un rappel au client, pas une nouvelle facture. Proposés à Louis
dans « Versements à envoyer » (tout coché, une tape); rien ne part sans lui. Par courriel : PDF de la facture joint;
par texto : le lien de la facture."""
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import formats, timezone

from communications import envoi, segments
from communications.models import Genre, Message
from facturation.models import Facture, Versement
from facturation.templatetags.argent import argent


def a_rappeler(entreprise, jour=None):
    """[(versement, montant taxes comprises)] : versements 2 et suivants arrivés à leur date (ou bientôt), facture de
    saison émise, pas encore couverts par les paiements, rappel pas encore envoyé."""
    jour = jour or timezone.localdate()
    limite = jour + timedelta(days=entreprise.jours_avance_versement)
    qs = (Versement.objects.filter(contrat__entreprise=entreprise, contrat__actif=True, rang__gte=2, date_prevue__lte=limite,
                                   rappel_envoye_le=None, facture__statut=Facture.Statut.EMISE)
          .select_related("facture__client", "contrat__saison").order_by("date_prevue", "facture__client__nom", "pk"))
    sortie = []
    for v in qs:
        for vv, m, paye in v.facture.echeancier():
            if vv.pk == v.pk and not paye:
                sortie.append((v, m))
    return sortie


def _rang(v):
    return f"{v.rang}{'er' if v.rang == 1 else 'e'} versement"


def texte_courriel(v, montant):
    f, ent = v.facture, v.facture.entreprise
    lignes = [f"Bonjour {f.client.nom_affiche},",
              f"Petit rappel : le {_rang(v)} de votre contrat de déneigement (saison {v.contrat.saison}), soit {argent(montant)}, "
              f"est payable le {formats.date_format(v.date_prevue, 'j F Y')}. Facture n° {f.numero} jointe (solde actuel : {argent(f.solde)})."]
    if ent.interac_courriel:
        lignes.append(f"Paiement par virement Interac à {ent.interac_courriel}, en indiquant le numéro de facture {f.numero}.")
    lignes += ["Merci!", ent.signature_messages or ent.nom]
    return "\n\n".join(lignes)


def texte_texto(v, montant):
    f, ent = v.facture, v.facture.entreprise
    sig, lien, date = ent.signature_messages or ent.nom, f.lien_public(), formats.date_format(v.date_prevue, "j F")
    interac = f" Interac : {ent.interac_courriel}" if ent.interac_courriel else ""
    return segments.premier_qui_entre(
        f"Bonjour {f.client.nom_affiche}, rappel : {_rang(v)} de {argent(montant)} payable le {date}.{interac} Facture : {lien}\n{sig}",
        f"Rappel : {_rang(v)} de {argent(montant)} payable le {date}.{interac} {lien}\n{sig}",
        f"Rappel : {_rang(v)} de {argent(montant)} payable le {date}. {lien}\n{sig}",
    )


def envoyer_rappel(v, montant, canal):
    f = v.facture
    if canal == Message.Canal.TEXTO:
        if not f.client.cellulaire:
            raise ValidationError("Ce client n'a pas de cellulaire.")
        m = Message.objects.create(entreprise=f.entreprise, client=f.client, genre=Genre.RAPPEL_VERSEMENT, canal=canal,
                                   destinataire=f.client.cellulaire, contenu=texte_texto(v, montant), facture=f)
    else:
        if not f.client.courriel:
            raise ValidationError("Ce client n'a pas d'adresse courriel.")
        m = Message.objects.create(entreprise=f.entreprise, client=f.client, genre=Genre.RAPPEL_VERSEMENT, canal=Message.Canal.COURRIEL,
                                   destinataire=f.client.courriel, contenu=texte_courriel(v, montant), facture=f,
                                   sujet=f"Rappel : {_rang(v)}, {f.entreprise.nom}")
    return envoi.envoyer(m)
