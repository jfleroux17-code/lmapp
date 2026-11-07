from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from clients.models import Adresse, Client, Secteur
from core import telephone


@admin.register(Secteur)
class SecteurAdmin(admin.ModelAdmin):
    list_display = ["nom", "entreprise", "ordre", "actif"]
    list_editable = ["ordre", "actif"]
    list_filter = ["entreprise", "actif"]
    search_fields = ["nom"]


class AdresseEnLigne(admin.StackedInline):
    model = Adresse
    extra = 0
    fields = [
        ("ligne1", "ligne2"), ("ville", "province", "code_postal"),
        ("secteur", "ordre_tournee", "active"),
        ("ou_mettre_neige", "obstacles"), ("borne_fontaine", "entree_en_pente"), "consignes",
    ]
    show_change_link = True


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ["__str__", "cellulaire_affiche", "courriel", "statut", "mode_paiement", "entreprise"]
    list_filter = ["entreprise", "statut", "mode_paiement", "canal_prefere", "consentement_commercial"]
    search_fields = ["nom", "prenom", "organisation", "cellulaire", "telephone_autre", "courriel", "adresses__ligne1", "adresses__ville"]
    inlines = [AdresseEnLigne]
    fieldsets = [
        (None, {"fields": ["entreprise", ("prenom", "nom"), "organisation", "statut"]}),
        ("Coordonnées", {"fields": [("cellulaire", "telephone_autre"), "courriel"]}),
        ("Préférences", {"fields": [("canal_prefere", "langue"), "mode_paiement"]}),
        ("Consentement (LCAP)", {"fields": ["consentement_commercial", ("consentement_date", "consentement_source"), "desabonne_le"]}),
        ("Adresse de facturation (si différente)", {
            "classes": ["collapse"],
            "fields": ["facturation_ligne1", "facturation_ligne2", ("facturation_ville", "facturation_province", "facturation_code_postal")],
        }),
        ("Notes", {"fields": ["notes"]}),
    ]

    @admin.display(description="cellulaire", ordering="cellulaire")
    def cellulaire_affiche(self, obj):
        return telephone.afficher(obj.cellulaire)

    def save_formset(self, request, form, formset, change):
        # Les adresses ajoutées dans la fiche prennent l'entreprise du client
        for adresse in formset.save(commit=False):
            adresse.entreprise_id = form.instance.entreprise_id
            adresse.save()
        for supprimee in formset.deleted_objects:
            supprimee.delete()
        formset.save_m2m()


@admin.register(Adresse)
class AdresseAdmin(GISModelAdmin):
    list_display = ["__str__", "client", "secteur", "ordre_tournee", "position_source", "active"]
    list_filter = ["entreprise", "secteur", "active", "position_source"]
    search_fields = ["ligne1", "ville", "code_postal", "client__nom", "client__prenom", "client__organisation"]
    autocomplete_fields = ["client"]
    # Carte centrée sur les Laurentides (Saint-Jérôme) pour corriger une position à la main
    gis_widget_kwargs = {"attrs": {"default_lon": -74.0, "default_lat": 45.78, "default_zoom": 10}}
