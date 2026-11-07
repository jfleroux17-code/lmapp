from django.contrib import admin
from django.db.models import Q
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


class AVerifierFiltre(admin.SimpleListFilter):
    title = "position à vérifier"
    parameter_name = "a_verifier"

    def lookups(self, request, model_admin):
        return [("oui", "À vérifier (absente ou trop vague)"), ("non", "Bonne")]

    def queryset(self, request, qs):
        vague = Q(position__isnull=True) | Q(position_precision__in=[Adresse.Precision.VILLE, Adresse.Precision.INTROUVABLE])
        manuelle = Q(position_source__in=[Adresse.SourcePosition.MANUELLE, Adresse.SourcePosition.GPS])
        if self.value() == "oui":
            return qs.filter(vague & ~manuelle)
        if self.value() == "non":
            return qs.filter(~vague | manuelle)
        return qs


@admin.register(Adresse)
class AdresseAdmin(GISModelAdmin):
    list_display = ["__str__", "client", "secteur", "ordre_tournee", "position_precision", "position_source", "verifier", "active"]
    list_filter = [AVerifierFiltre, "entreprise", "secteur", "active", "position_precision", "position_source"]
    readonly_fields = ["position_precision", "geocodage_note"]
    actions = ["geocoder_de_nouveau"]
    search_fields = ["ligne1", "ville", "code_postal", "client__nom", "client__prenom", "client__organisation"]
    autocomplete_fields = ["client"]
    # Carte centrée sur les Laurentides (Saint-Jérôme) pour corriger une position à la main
    gis_widget_kwargs = {"attrs": {"default_lon": -74.0, "default_lat": 45.78, "default_zoom": 10}}

    @admin.display(description="à vérifier", boolean=True)
    def verifier(self, obj):
        return obj.position_a_verifier

    def save_model(self, request, obj, form, change):
        # Un point déplacé sur la carte devient une position manuelle : le
        # géocodage ne l'écrasera plus.
        if "position" in form.changed_data and obj.position is not None:
            obj.position_source = Adresse.SourcePosition.MANUELLE
            obj.position_precision = Adresse.Precision.ADRESSE
            obj.geocodage_note = f"Placée à la main par {request.user} sur la carte."
        super().save_model(request, obj, form, change)

    @admin.action(description="Géocoder de nouveau (sauf les positions manuelles)")
    def geocoder_de_nouveau(self, request, queryset):
        from clients.tasks import geocoder_adresse

        n = 0
        for a in queryset.exclude(position_source__in=[Adresse.SourcePosition.MANUELLE, Adresse.SourcePosition.GPS]):
            geocoder_adresse.defer(adresse_id=a.pk)
            n += 1
        self.message_user(request, f"{n} adresse(s) mise(s) en file pour le géocodage (environ une par seconde).")
