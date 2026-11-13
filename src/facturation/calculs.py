"""Calcul des taxes (PRD C2, section 7).

Au Québec, la TPS et la TVQ se calculent toutes deux sur le sous-total (la TVQ
ne s'applique plus sur la TPS depuis 2013). Chaque taxe est arrondie au cent,
la moitié vers le haut, une fois par facture (pas ligne par ligne).
"""
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def arrondir(montant):
    return Decimal(montant).quantize(CENT, rounding=ROUND_HALF_UP)


def taxes(sous_total_taxable, taux_tps, taux_tvq):
    """(tps, tvq) pour un sous-total taxable et des taux en pour cent."""
    base = Decimal(sous_total_taxable)
    return arrondir(base * Decimal(taux_tps) / 100), arrondir(base * Decimal(taux_tvq) / 100)


def repartir(total, n):
    """Partage un montant en n versements égaux au cent près; les cents qui restent vont au dernier."""
    total = arrondir(total)
    part = (total / n).quantize(CENT, rounding=ROUND_DOWN)
    parts = [part] * (n - 1)
    return parts + [total - sum(parts)]


def prix_avant_taxes(total, taux_tps, taux_tvq, versements=1):
    """Prix « taxes incluses » ramené avant taxes : (prix, exact).

    Cherche le prix avant taxes dont la ou les factures (taxes arrondies sur chacune) redonnent exactement `total`.
    Depuis le 12 novembre 2026, une seule facture par saison : `versements` vaut 1. Sinon (l'arrondi l'empêche) :
    le plus proche, et exact = False."""
    total = arrondir(total)
    taux = (Decimal(taux_tps) + Decimal(taux_tvq)) / 100

    def total_facture(prix):
        return sum((p + sum(taxes(p, taux_tps, taux_tvq)) for p in repartir(prix, versements)), Decimal("0"))

    depart = arrondir(total / (1 + taux))
    candidats = [depart + CENT * d for d in (0, -1, 1, -2, 2, -3, 3)]
    for prix in candidats:
        if prix >= 0 and total_facture(prix) == total:
            return prix, True
    return min((p for p in candidats if p >= 0), key=lambda p: abs(total_facture(p) - total)), False
