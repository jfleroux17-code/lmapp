from django.contrib import admin, messages
from django.db.models import Q
from django.template.response import TemplateResponse
from django.contrib.gis.admin import GISModelAdmin

from clients.models import Adresse, Client, Contact, Secteur
from core import telephone
from core.models import Entreprise, VilleDesservie


@admin.register(Secteur)
class SecteurAdmin(admin.ModelAdmin):
    list_display = ["nom", "entreprise", "ordre", "actif"]
    list_editable = ["ordre", "actif"]
    list_filter = ["entreprise", "actif"]
    search_fields = ["nom"]


class ContactEnLigne(admin.TabularInline):
    model = Contact
    extra = 0
    fields = ["nom", "role", "cellulaire", "courriel", "note"]


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
    inlines = [ContactEnLigne, AdresseEnLigne]
    actions = ["effacer_a_la_demande"]
    readonly_fields = ["efface_le"]
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
        ("Loi 25", {"classes": ["collapse"], "fields": ["efface_le"]}),
    ]

    @admin.action(description="Effacer ses renseignements à sa demande (Loi 25, irréversible)")
    def effacer_a_la_demande(self, request, queryset):
        """Page de confirmation d'abord; l'effacement se fait seulement au second envoi (« confirmer »)."""
        from clients.effacement import effacer

        if request.POST.get("confirmer") == "oui":
            for c in queryset:
                b = effacer(c)
                garde = "factures gardées (6 ans, lois fiscales) avec le nom" if b["factures_gardees"] else "nom et adresses effacés aussi"
                self.message_user(request, f"Client n° {c.pk} effacé : {b['messages']} message(s), {b['archives']} courriel(s) archivé(s), "
                                           f"{b['demandes']} demande(s), {b['adresses']} adresse(s), {b['brouillons']} brouillon(s); {garde}. "
                                           "Les courriels encore dans la boîte (moins de 30 jours) s'effacent à leur date.", messages.SUCCESS)
            return None
        return TemplateResponse(request, "admin/clients/effacer_confirmation.html", {
            **self.admin_site.each_context(request), "title": "Effacer à la demande du client (Loi 25)",
            "clients": queryset, "opts": self.model._meta, "action": "effacer_a_la_demande",
            "selection": request.POST.getlist(admin.helpers.ACTION_CHECKBOX_NAME)})

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
    # Sans ville par défaut connue : carte centrée sur les Laurentides
    gis_widget_kwargs = {"attrs": {"default_lon": -74.0, "default_lat": 45.78, "default_zoom": 10}}

    def get_form(self, request, obj=None, **kwargs):
        request._adresse_en_cours = obj
        return super().get_form(request, obj, **kwargs)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        champ = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "position" and champ is not None:
            # Carte ouverte sur la ville par défaut de l'entreprise de l'adresse
            obj = getattr(request, "_adresse_en_cours", None)
            entreprise_id = obj.entreprise_id if obj else Entreprise.objects.filter(active=True).values_list("pk", flat=True).first()
            ville = VilleDesservie.par_defaut_de(entreprise_id) if entreprise_id else None
            if ville and ville.centre:
                champ.widget.attrs.update({"default_lon": ville.centre.x, "default_lat": ville.centre.y, "default_zoom": 13})
        return champ

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
