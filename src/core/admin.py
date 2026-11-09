from django.conf import settings
from django.contrib import admin, messages
from django.contrib.gis.geos import Point

from core.models import (AbonnementNotification, EchecConnexion, Entreprise, IncidentConfidentialite, JournalAction, Membre,
                         VilleDesservie)

_titre = "LMAPP : administration"
if settings.LMAPP_ENV != "prod":
    _titre = f"LMAPP : administration (ENVIRONNEMENT DE {settings.LMAPP_ENV.upper()})"

admin.site.site_header = _titre
admin.site.site_title = _titre
admin.site.index_title = "Tableau de bord"
admin.site.index_template = "admin/index_lmapp.html"  # ajoute le lien vers l'écran de la plateforme


class MembreEnLigne(admin.TabularInline):
    model = Membre
    extra = 0
    autocomplete_fields = ["utilisateur"]


class VilleDesservieEnLigne(admin.TabularInline):
    model = VilleDesservie
    extra = 0
    fields = ["nom", "province", "rayon_km", "par_defaut", "centre_affiche"]
    readonly_fields = ["centre_affiche"]

    @admin.display(description="centre")
    def centre_affiche(self, obj):
        if obj.centre is None:
            return "(rempli à l'enregistrement)"
        return f"{obj.centre.y:.5f}, {obj.centre.x:.5f}"


@admin.register(Entreprise)
class EntrepriseAdmin(admin.ModelAdmin):
    list_display = ["nom", "domaine", "inscrit_taxes", "active"]
    search_fields = ["nom", "nom_legal", "slug", "domaine"]
    prepopulated_fields = {"slug": ["nom"]}
    inlines = [VilleDesservieEnLigne, MembreEnLigne]
    fieldsets = [
        (None, {"fields": ["nom", "nom_legal", "slug", "domaine", "active", "mode"]}),
        ("Coordonnées", {"fields": ["telephone", "courriel", "adresse_ligne1", "adresse_ligne2", "ville", "province", "code_postal"]}),
        ("Taxes et factures", {"fields": ["inscrit_taxes", "numero_tps", "numero_tvq", "taux_tps", "taux_tvq", "prochain_numero_facture"]}),
        ("Communications", {"fields": ["envois_actifs", "numero_texto", "courriel_reponse", "signature_messages"]}),
        ("Avis pendant les opérations", {"fields": ["avis_proximite_actif", "avis_rayon_m", "minutes_par_arret", "avis_passage_fait"]}),
        ("Paiement Interac", {"fields": ["interac_courriel", "interac_instructions"]}),
    ]

    def save_formset(self, request, form, formset, change):
        super().save_formset(request, form, formset, change)
        if formset.model is VilleDesservie:
            remplir_centres(request, form.instance)


def remplir_centres(request, entreprise):
    """Centre des villes desservies sans centre : une requête Nominatim par ville."""
    from clients import geocodage

    for ville in VilleDesservie.objects.filter(entreprise=entreprise, centre__isnull=True):
        try:
            centre = geocodage.centre_ville(ville.nom, ville.province)
        except geocodage.ServiceIndisponible:
            centre = None
        if centre is None:
            messages.warning(request, f"Centre de « {ville} » introuvable : le géocodage de ses adresses ne sera pas limité à la zone.")
            continue
        ville.centre = Point(centre[1], centre[0], srid=4326)
        ville.save(update_fields=["centre", "modifie_le"])
        messages.info(request, f"Centre de « {ville} » : {centre[0]:.5f}, {centre[1]:.5f} (rayon {ville.rayon_km} km).")


@admin.register(Membre)
class MembreAdmin(admin.ModelAdmin):
    list_display = ["utilisateur", "entreprise", "role"]
    list_filter = ["entreprise", "role"]
    autocomplete_fields = ["utilisateur"]


@admin.register(EchecConnexion)
class EchecConnexionAdmin(admin.ModelAdmin):
    """Consultation des essais ratés. Supprimer les lignes d'une IP ou d'un nom lève son blocage."""

    list_display = ("moment", "nom_utilisateur", "ip")
    list_filter = ("moment",)
    search_fields = ("nom_utilisateur", "ip")
    readonly_fields = ("moment", "nom_utilisateur", "ip")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AbonnementNotification)
class AbonnementNotificationAdmin(admin.ModelAdmin):
    list_display = ["utilisateur", "entreprise", "appareil", "cree_le", "dernier_envoi"]
    list_filter = ["entreprise"]
    readonly_fields = ["endpoint", "p256dh", "auth", "appareil", "cree_le", "dernier_envoi"]


@admin.register(IncidentConfidentialite)
class IncidentConfidentialiteAdmin(admin.ModelAdmin):
    """Registre exigé par la Loi 25 : on inscrit, on n'efface pas (pas de suppression permise)."""
    list_display = ["constate_le", "entreprise", "resume", "personnes", "risque_serieux", "cai_avisee_le"]
    list_filter = ["risque_serieux", "entreprise"]
    fieldsets = [
        (None, {"fields": ["entreprise", ("survenu_le", "constate_le"), "description", "renseignements", "personnes"]}),
        ("Risque", {"fields": ["risque_serieux", "evaluation", "mesures"]}),
        ("Avis (obligatoires si risque sérieux)", {"fields": ["cai_avisee_le", "personnes_avisees_le"]}),
    ]

    @admin.display(description="description")
    def resume(self, obj):
        return obj.description[:80]

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(JournalAction)
class JournalActionAdmin(admin.ModelAdmin):
    """Journal des actions (K4) : consultation seulement."""
    list_display = ["moment", "nom_utilisateur", "action", "modele", "objet", "resume", "entreprise"]
    list_filter = ["action", "modele", "entreprise", "nom_utilisateur"]
    search_fields = ["objet", "nom_utilisateur", "=objet_id", "=client_id"]
    date_hierarchy = "moment"
    readonly_fields = ["moment", "entreprise", "nom_utilisateur", "ip", "action", "modele", "objet_id", "objet", "client_id", "detail"]
    exclude = ["utilisateur", "changements"]

    @admin.display(description="champs")
    def resume(self, obj):
        return ", ".join(list(obj.changements)[:6]) + (" ..." if len(obj.changements) > 6 else "")

    @admin.display(description="changements (avant → après)")
    def detail(self, obj):
        from django.utils.html import format_html_join

        return format_html_join("", "<div><strong>{}</strong> : {} → {}</div>",
                                ((k, "(vide)" if a in (None, "") else a, "(vide)" if b in (None, "") else b)
                                 for k, (a, b) in obj.changements.items())) or "(rien)"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return request.method in ("GET", "HEAD")  # la fiche s'affiche, rien ne s'enregistre

    def has_delete_permission(self, request, obj=None):
        return False
