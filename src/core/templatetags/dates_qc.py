"""Dates en français québécois (audit UX) : « 1er novembre », « 1er nov. », abréviations de l'OQLF.

Filtre `date_qc`, chargé partout (builtins des gabarits), même format que `date` de Django :
seul le premier du mois devient « 1er », et M donne l'abréviation québécoise (janv., févr., ...).
"""
from django import template
from django.template.defaultfilters import date as date_django
from django.utils import formats, timezone

register = template.Library()

ABREGES = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juill.", "août", "sept.", "oct.", "nov.", "déc."]


def _echapper(texte):
    return "".join("\\" + c for c in texte)


def format_qc(fmt, jour, mois):
    """Remplace j (si 1er) et M (abréviation) dans un format de Django, en gardant les caractères échappés."""
    sortie, i = [], 0
    while i < len(fmt):
        c = fmt[i]
        if c == "\\" and i + 1 < len(fmt):
            sortie.append(fmt[i:i + 2])
            i += 2
            continue
        if c == "j" and jour == 1:
            sortie.append(_echapper("1er"))
        elif c == "M":
            sortie.append(_echapper(ABREGES[mois - 1]))
        else:
            sortie.append(c)
        i += 1
    return "".join(sortie)


@register.filter(expects_localtime=True, is_safe=False)
def date_qc(valeur, fmt="j F Y"):
    if not valeur:
        return ""
    return date_django(valeur, format_qc(fmt, valeur.day, valeur.month))


def date_texte(valeur, fmt="j F Y"):
    """Même chose dans le code Python (textes aux clients)."""
    if hasattr(valeur, "tzinfo") and timezone.is_aware(valeur):
        valeur = timezone.localtime(valeur)
    return formats.date_format(valeur, format_qc(fmt, valeur.day, valeur.month))
