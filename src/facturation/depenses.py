"""Dépenses par photo (PRD S1, S2) : taxes tirées du total, totaux par catégorie et par mois."""
from collections import OrderedDict

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth

from facturation.calculs import arrondir
from facturation.models import ZERO, Depense


def taxes_du_total(total, entreprise):
    """(tps, tvq) comprises dans un total payé, aux taux de l'entreprise. Zéro si l'entreprise n'est pas inscrite
    (pas de crédit de taxe à réclamer)."""
    if not entreprise.inscrit_taxes or not total:
        return ZERO, ZERO
    taux_tps, taux_tvq = entreprise.taux_tps / 100, entreprise.taux_tvq / 100
    avant = total / (1 + taux_tps + taux_tvq)
    return arrondir(avant * taux_tps), arrondir(avant * taux_tvq)


def bilan(entreprise, debut, fin):
    """Dépenses d'une période : totaux, par catégorie (plus grosse d'abord) et par mois."""
    qs = Depense.objects.filter(entreprise=entreprise, date__gte=debut, date__lte=fin)
    somme = qs.aggregate(total=Sum("total"), tps=Sum("tps"), tvq=Sum("tvq"), n=Count("pk"))
    total, tps, tvq = somme["total"] or ZERO, somme["tps"] or ZERO, somme["tvq"] or ZERO
    noms = dict(Depense.Categorie.choices)
    par_categorie = [{"categorie": noms[r["categorie"]], "total": r["t"], "tps": r["p"], "tvq": r["q"], "nombre": r["n"],
                      "avant_taxes": r["t"] - r["p"] - r["q"]}
                     for r in qs.values("categorie").annotate(t=Sum("total"), p=Sum("tps"), q=Sum("tvq"), n=Count("pk")).order_by("-t")]
    par_mois = OrderedDict()
    for r in qs.annotate(mois=TruncMonth("date")).values("mois").annotate(t=Sum("total"), n=Count("pk")).order_by("mois"):
        par_mois[r["mois"]] = {"mois": r["mois"], "total": r["t"], "nombre": r["n"]}
    return {"nombre": somme["n"], "total": total, "tps": tps, "tvq": tvq, "taxes": tps + tvq, "avant_taxes": total - tps - tvq,
            "par_categorie": par_categorie, "par_mois": list(par_mois.values())}
