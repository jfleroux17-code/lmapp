from django.conf import settings
from django.contrib import admin

_titre = "LMAPP : administration"
if settings.LMAPP_ENV != "prod":
    _titre = f"LMAPP : administration (ENVIRONNEMENT DE {settings.LMAPP_ENV.upper()})"

admin.site.site_header = _titre
admin.site.site_title = _titre
admin.site.index_title = "Tableau de bord"
