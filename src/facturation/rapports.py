"""Rapport de la saison (PRD J2, J3) : revenus par secteur, et bilan pour le comptable (ventes, taxes perçues,
encaissements par mode, à recevoir). Période : les dates de la saison. Montants des factures émises (les annulées
sont comptées à part), argent reçu sans compter deux fois un crédit au compte (D7)."""
from collections import OrderedDict
from decimal import Decimal

from django.db.models import Count, Sum

from facturation.models import ZERO, Credit, Facture, Paiement


def saison(entreprise, s):
    factures = (Facture.objects.filter(entreprise=entreprise, date_facture__gte=s.debut, date_facture__lte=s.fin)
                .exclude(statut=Facture.Statut.BROUILLON).select_related("adresse__secteur", "client"))
    emises = [f for f in factures if f.statut == Facture.Statut.EMISE]
    ventes = [f for f in emises if f.genre == Facture.Genre.FACTURE]
    soldes_ouverture = [f for f in emises if f.genre == Facture.Genre.SOLDE_OUVERTURE]

    # J2 : par secteur (secteur de l'adresse de la facture, sinon de la première adresse active du client)
    secteurs = OrderedDict()
    for f in ventes:
        a = f.adresse or f.client.adresses.filter(active=True).select_related("secteur").first()
        nom = a.secteur.nom if a and a.secteur else "Sans secteur"
        l = secteurs.setdefault(nom, {"nom": nom, "sous_total": ZERO, "total": ZERO, "clients": set(), "paye": ZERO})
        l["sous_total"] += f.sous_total
        l["total"] += f.total
        l["clients"].add(f.client_id)
        l["paye"] += f.paye
    par_secteur = sorted(secteurs.values(), key=lambda l: -l["sous_total"])
    for l in par_secteur:
        l["clients"] = len(l["clients"])

    # J3 : encaissements par mode (paiements reçus dans la saison, plus les surplus gardés en crédit)
    modes = OrderedDict((m, ZERO) for m, _ in Paiement.MODES_RECUS)
    for r in (Paiement.objects.filter(entreprise=entreprise, date__gte=s.debut, date__lte=s.fin).exclude(mode=Paiement.Mode.CREDIT)
              .values("mode").annotate(t=Sum("montant"))):
        modes[r["mode"]] += r["t"]
    for r in Credit.objects.filter(entreprise=entreprise, date__gte=s.debut, date__lte=s.fin).values("mode").annotate(t=Sum("montant")):
        modes[r["mode"]] += r["t"]
    noms = dict(Paiement.Mode.choices)
    encaissements = [{"mode": noms[m], "montant": t} for m, t in modes.items() if t]

    a_recevoir = Facture.objects.filter(entreprise=entreprise).a_recevoir()
    from facturation.depenses import bilan

    depenses = bilan(entreprise, s.debut, s.fin)
    return {
        "depenses": depenses,
        "saison": s,
        "nb_factures": len(ventes), "sous_total": sum((f.sous_total for f in ventes), ZERO),
        "tps": sum((f.tps for f in ventes), ZERO), "tvq": sum((f.tvq for f in ventes), ZERO),
        "total": sum((f.total for f in ventes), ZERO),
        "soldes_ouverture": sum((f.total for f in soldes_ouverture), ZERO), "nb_soldes_ouverture": len(soldes_ouverture),
        "annulees": [f for f in factures if f.statut == Facture.Statut.ANNULEE],
        "par_secteur": par_secteur, "encaissements": encaissements, "encaisse": sum((e["montant"] for e in encaissements), ZERO),
        "a_recevoir": sum((f.solde_du for f in a_recevoir), ZERO), "nb_a_recevoir": a_recevoir.values("client").distinct().count(),
        "numeros": (min((f.numero for f in ventes if f.numero), default=None), max((f.numero for f in ventes if f.numero), default=None)),
    }


def pdf(entreprise, s):
    from django.template.loader import render_to_string
    from django.utils import timezone
    from weasyprint import HTML

    return HTML(string=render_to_string("facturation/rapport_saison_pdf.html",
                                        {**saison(entreprise, s), "ent": entreprise, "date": timezone.localdate()})).write_pdf()
