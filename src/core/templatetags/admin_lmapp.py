"""Bandeaux de l'administration : environnement (PRODUCTION ou test) et état des envois réels par entreprise."""
from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def etat_admin():
    from core.models import Entreprise

    return {"prod": settings.LMAPP_ENV == "prod", "env": settings.LMAPP_ENV.upper(),
            "entreprises": list(Entreprise.objects.filter(active=True).order_by("nom").values_list("nom", "envois_actifs"))}
