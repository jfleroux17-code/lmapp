from django.conf import settings
from django.contrib import admin

from core.models import Entreprise, Membre

_titre = "LMAPP : administration"
if settings.LMAPP_ENV != "prod":
    _titre = f"LMAPP : administration (ENVIRONNEMENT DE {settings.LMAPP_ENV.upper()})"

admin.site.site_header = _titre
admin.site.site_title = _titre
admin.site.index_title = "Tableau de bord"


class MembreEnLigne(admin.TabularInline):
    model = Membre
    extra = 0
    autocomplete_fields = ["utilisateur"]


@admin.register(Entreprise)
class EntrepriseAdmin(admin.ModelAdmin):
    list_display = ["nom", "domaine", "inscrit_taxes", "active"]
    search_fields = ["nom", "nom_legal", "slug", "domaine"]
    prepopulated_fields = {"slug": ["nom"]}
    inlines = [MembreEnLigne]
    fieldsets = [
        (None, {"fields": ["nom", "nom_legal", "slug", "domaine", "active"]}),
        ("Coordonnées", {"fields": ["telephone", "courriel", "adresse_ligne1", "adresse_ligne2", "ville", "province", "code_postal"]}),
        ("Taxes", {"fields": ["inscrit_taxes", "numero_tps", "numero_tvq", "taux_tps", "taux_tvq"]}),
        ("Communications", {"fields": ["numero_texto", "courriel_reponse", "signature_messages"]}),
        ("Paiement Interac", {"fields": ["interac_courriel", "interac_instructions"]}),
    ]


@admin.register(Membre)
class MembreAdmin(admin.ModelAdmin):
    list_display = ["utilisateur", "entreprise", "role"]
    list_filter = ["entreprise", "role"]
    autocomplete_fields = ["utilisateur"]
