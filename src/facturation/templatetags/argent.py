"""Format québécois : 1 234,56 $ et 9,975 %."""
from decimal import Decimal

from django import template

register = template.Library()
ESPACE_FINE = " "  # espace insécable fine, entre les milliers et avant $ ou %


@register.filter
def argent(valeur):
    if valeur is None or valeur == "":
        return ""
    v = Decimal(valeur).quantize(Decimal("0.01"))
    signe = "-" if v < 0 else ""
    entiers, cents = f"{abs(v):.2f}".split(".")
    groupes = []
    while entiers:
        groupes.insert(0, entiers[-3:])
        entiers = entiers[:-3]
    return f"{signe}{ESPACE_FINE.join(groupes)},{cents}{ESPACE_FINE}$"


@register.filter
def pourcent(valeur):
    texte = format(Decimal(valeur).normalize(), "f").replace(".", ",")
    return f"{texte}{ESPACE_FINE}%"


@register.filter
def quantite(valeur):
    texte = format(Decimal(valeur).normalize(), "f")
    return texte.replace(".", ",")
