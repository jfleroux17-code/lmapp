"""État de compte d'un client (PRD C10) : factures émises et paiements, dans l'ordre des dates, avec le solde courant.

Les factures annulées et les brouillons n'y sont pas. Le solde final est ce que le client doit
(aucun trop-perçu en V1). PDF refait à chaque demande, comme les factures.
"""
from django.template.loader import render_to_string
from django.utils import timezone

from core import telephone
from facturation.models import ZERO, Facture, Paiement


def mouvements(client):
    factures = list(client.factures.filter(statut=Facture.Statut.EMISE))
    lignes = []
    for f in factures:
        quoi = f"Solde antérieur{f' ({f.saison_origine})' if f.saison_origine else ''}" if f.genre == Facture.Genre.SOLDE_OUVERTURE else f"Facture n° {f.numero}"
        lignes.append({"date": f.date_facture, "ordre": (0, f.pk), "quoi": quoi, "debit": f.total, "credit": None})
    for p in Paiement.objects.filter(facture__in=factures).select_related("facture"):
        sur = f"facture n° {p.facture.numero}" if p.facture.numero else "solde antérieur"
        mode = p.get_mode_display()
        mode = mode[:1].lower() + mode[1:]  # « virement Interac » garde sa majuscule
        lignes.append({"date": p.date, "ordre": (1, p.pk), "quoi": f"Paiement, {mode} ({sur})",
                       "debit": None, "credit": p.montant})
    lignes.sort(key=lambda l: (l["date"], l["ordre"]))
    solde = ZERO
    for l in lignes:
        solde += (l["debit"] or ZERO) - (l["credit"] or ZERO)
        l["solde"] = solde
    return lignes, solde


def html(client):
    ent = client.entreprise
    lignes, solde = mouvements(client)
    a = client.adresses.filter(active=True).first()
    if client.facturation_ligne1:
        adresse = [client.facturation_ligne1, client.facturation_ligne2,
                   " ".join(x for x in (client.facturation_ville, client.facturation_province, client.facturation_code_postal) if x)]
    else:
        adresse = [a.ligne1, a.ligne2, " ".join(x for x in (a.ville, a.province, a.code_postal) if x)] if a else []
    return render_to_string("facturation/etat_compte_pdf.html", {
        "ent": ent, "client": client, "adresse": [x for x in adresse if x], "lignes": lignes, "solde": solde,
        "date": timezone.localdate(), "telephone_affiche": telephone.afficher(ent.telephone)})


def rendre(client):
    from weasyprint import HTML

    return HTML(string=html(client)).write_pdf()
