"""PDF d'une facture (PRD C3), produit à la demande par WeasyPrint.

Une facture émise ne change plus (taxes et numéros figés à l'émission) : le
PDF est donc refait à chaque demande, sans fichier à garder. Le nom et
l'adresse de l'entreprise viennent de sa fiche du moment.
"""
from django.template.loader import render_to_string

from core import telephone
from facturation.models import Facture


def _cheques(f):
    from facturation.cheques import en_main_pour

    return en_main_pour(f) if f.pk else []


def contexte(facture):
    f, ent = facture, facture.entreprise
    emise = f.statut != Facture.Statut.BROUILLON
    # Brouillon : taxes et numéros actuels de l'entreprise; émise : ceux copiés à l'émission
    if emise:
        inscrit, taux_tps, taux_tvq, no_tps, no_tvq = f.inscrit_taxes, f.taux_tps, f.taux_tvq, f.numero_tps, f.numero_tvq
    else:
        inscrit, taux_tps, taux_tvq, no_tps, no_tvq = ent.inscrit_taxes, ent.taux_tps, ent.taux_tvq, ent.numero_tps, ent.numero_tvq
    if f.genre == Facture.Genre.SOLDE_OUVERTURE:
        inscrit = False
    c = f.client
    if c.facturation_ligne1:
        facturation = [c.facturation_ligne1, c.facturation_ligne2,
                       " ".join(x for x in (c.facturation_ville, c.facturation_province, c.facturation_code_postal) if x)]
    else:
        a = f.adresse or c.adresses.filter(active=True).first()
        facturation = [a.ligne1, a.ligne2, " ".join(x for x in (a.ville, a.province, a.code_postal) if x)] if a else []
    return {
        "f": f, "ent": ent, "client": c, "telephone_affiche": telephone.afficher(ent.telephone),
        "facturation": [l for l in facturation if l],
        # Adresse du service : seulement si la facture va ailleurs (sinon elle serait écrite deux fois)
        "service": f.adresse if c.facturation_ligne1 else None,
        "lignes": f.lignes.all(),
        "paiements": f.paiements.order_by("date", "pk") if emise else [],
        "cheques": _cheques(f),
        "inscrit": inscrit, "taux_tps": taux_tps, "taux_tvq": taux_tvq, "no_tps": no_tps, "no_tvq": no_tvq,
        "brouillon": f.statut == Facture.Statut.BROUILLON,
        "annulee": f.statut == Facture.Statut.ANNULEE,
        "solde_ouverture": f.genre == Facture.Genre.SOLDE_OUVERTURE,
    }


def html(facture):
    return render_to_string("facturation/facture_pdf.html", contexte(facture))


def rendre(facture):
    from weasyprint import HTML

    return HTML(string=html(facture)).write_pdf()


def nom_fichier(facture):
    if facture.genre == Facture.Genre.SOLDE_OUVERTURE:
        return f"solde-{facture.pk}.pdf"
    return f"facture-{facture.numero}.pdf" if facture.numero else f"brouillon-{facture.pk}.pdf"
