"""Administration du volet argent. Les écrans de Louis viendront ensuite (cellulaire).

Une facture émise est en lecture seule; ses lignes aussi. Les actions
« Émettre » et « Recalculer » passent par les méthodes du modèle, qui gardent
les règles (numéro séquentiel, taxes figées).
"""
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.html import format_html

from facturation.models import ChequePostdate, Contrat, Facture, LigneFacture, Paiement, Saison, Service, Versement, VirementInterac


@admin.register(Saison)
class SaisonAdmin(admin.ModelAdmin):
    list_display = ["nom", "debut", "fin", "entreprise"]
    list_filter = ["entreprise"]


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ["nom", "prix_suggere", "taxable", "actif", "ordre", "entreprise"]
    list_editable = ["prix_suggere", "taxable", "actif", "ordre"]
    list_filter = ["entreprise", "actif"]


class VersementEnLigne(admin.TabularInline):
    model = Versement
    extra = 0
    fields = ["rang", "date_prevue", "montant", "facture"]
    readonly_fields = ["facture"]


@admin.register(Contrat)
class ContratAdmin(admin.ModelAdmin):
    list_display = ["client", "saison", "type", "prix", "actif"]
    list_filter = ["entreprise", "saison", "type", "actif"]
    search_fields = ["client__nom", "client__prenom", "client__organisation", "prix_texte"]
    autocomplete_fields = ["client", "adresse"]
    filter_horizontal = ["services"]
    inlines = [VersementEnLigne]
    actions = ["facturer_versements_dus", "echeancier_2", "echeancier_3"]

    def _echeancier(self, request, queryset, nombre):
        from django.core.exceptions import ValidationError

        faits, refus = 0, []
        for c in queryset.select_related("entreprise", "saison", "client"):
            try:
                c.creer_echeancier_par_defaut(nombre)
                faits += 1
            except ValidationError as e:
                refus.append(f"{c.client} : {' '.join(e.messages)}")
        if faits:
            self.message_user(request, f"{faits} échéancier(s) en {nombre} versements (1er aujourd'hui, puis aux dates de l'entreprise).")
        for r in refus:
            self.message_user(request, r, messages.ERROR)

    @admin.action(description="Échéancier en 2 versements (1er aujourd'hui, dates de l'entreprise)")
    def echeancier_2(self, request, queryset):
        self._echeancier(request, queryset, 2)

    @admin.action(description="Échéancier en 3 versements (1er aujourd'hui, dates de l'entreprise)")
    def echeancier_3(self, request, queryset):
        self._echeancier(request, queryset, 3)

    @admin.action(description="Créer les factures (brouillons) des versements dus aujourd'hui ou avant")
    def facturer_versements_dus(self, request, queryset):
        from django.utils import timezone

        n = 0
        for v in Versement.objects.filter(contrat__in=queryset, facture=None, date_prevue__lte=timezone.localdate()):
            v.facturer()
            n += 1
        self.message_user(request, f"{n} facture(s) créée(s) en brouillon, à vérifier puis émettre.")


class LigneEnLigne(admin.TabularInline):
    model = LigneFacture
    extra = 0
    fields = ["ordre", "service", "description", "quantite", "prix_unitaire", "taxable", "montant"]
    readonly_fields = ["montant"]

    def _modifiable(self, obj):
        return obj is None or obj.modifiable

    def has_add_permission(self, request, obj=None):
        return self._modifiable(obj) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return self._modifiable(obj) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._modifiable(obj) and super().has_delete_permission(request, obj)


class PaiementEnLigne(admin.TabularInline):
    model = Paiement
    extra = 0
    fields = ["date", "montant", "mode", "reference", "note"]
    readonly_fields = fields
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Facture)
class FactureAdmin(admin.ModelAdmin):
    list_display = ["__str__", "client", "date_facture", "genre", "statut", "total", "solde_affiche", "lien_pdf"]
    list_filter = ["entreprise", "statut", "genre"]
    search_fields = ["numero", "client__nom", "client__prenom", "client__organisation"]
    autocomplete_fields = ["client", "adresse", "contrat"]
    inlines = [LigneEnLigne, PaiementEnLigne]
    actions = ["emettre", "recalculer"]
    readonly_fields = ["lien_pdf", "numero", "statut", "sous_total", "tps", "tvq", "total", "solde_affiche", "inscrit_taxes",
                       "taux_tps", "taux_tvq", "numero_tps", "numero_tvq", "emise_le", "annulee_le", "raison_annulation"]
    fieldsets = [
        (None, {"fields": ["entreprise", "client", "adresse", "contrat", "genre", "saison_origine"]}),
        ("Facture", {"fields": ["lien_pdf", ("numero", "statut"), ("date_facture", "date_echeance"), "note", "note_interne"]}),
        ("Montants", {"fields": [("sous_total", "tps", "tvq", "total"), "solde_affiche"]}),
        ("Taxes figées à l'émission", {"classes": ["collapse"], "fields": [
            "inscrit_taxes", ("taux_tps", "taux_tvq"), ("numero_tps", "numero_tvq"), ("emise_le", "annulee_le"), "raison_annulation"]}),
    ]

    @admin.display(description="PDF")
    def lien_pdf(self, obj):
        if not obj.pk:
            return "Après l'enregistrement."
        # Même domaine que l'administration : l'entreprise vient du domaine, la facture doit en être
        return format_html('<a href="{}" target="_blank">Voir le PDF</a>', reverse("facturation:pdf", args=[obj.pk]))

    @admin.display(description="solde")
    def solde_affiche(self, obj):
        return obj.solde

    def get_readonly_fields(self, request, obj=None):
        ro = list(self.readonly_fields)
        if obj and not obj.modifiable:
            ro += ["entreprise", "client", "adresse", "contrat", "genre", "saison_origine", "date_facture", "date_echeance", "note"]
        return ro

    def has_delete_permission(self, request, obj=None):
        return (obj is None or obj.modifiable) and super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)  # passerait outre la protection des factures émises
        return actions

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        if form.instance.modifiable:
            form.instance.recalculer()

    def _chaque(self, request, queryset, methode, verbe):
        n = 0
        for f in queryset:
            try:
                getattr(f, methode)()
                n += 1
            except ValidationError as e:
                self.message_user(request, f"{f} : {' '.join(e.messages)}", messages.ERROR)
        if n:
            self.message_user(request, f"{n} facture(s) {verbe}.")

    @admin.action(description="Émettre (numéro définitif, plus de modification)")
    def emettre(self, request, queryset):
        self._chaque(request, queryset.order_by("date_facture", "pk"), "emettre", "émise(s)")

    @admin.action(description="Recalculer les montants (brouillons)")
    def recalculer(self, request, queryset):
        self._chaque(request, queryset.filter(statut=Facture.Statut.BROUILLON), "recalculer", "recalculée(s)")


@admin.register(Paiement)
class PaiementAdmin(admin.ModelAdmin):
    list_display = ["date", "facture", "montant", "mode", "reference"]
    list_filter = ["entreprise", "mode"]
    search_fields = ["facture__numero", "facture__client__nom", "reference"]
    autocomplete_fields = ["facture"]


@admin.register(VirementInterac)
class VirementInteracAdmin(admin.ModelAdmin):
    list_display = ["recu_le", "montant", "envoyeur", "client", "facture", "statut"]
    list_filter = ["entreprise", "statut"]
    search_fields = ["envoyeur", "message_envoyeur", "reference"]
    readonly_fields = ["courriel", "paiements"]


@admin.register(ChequePostdate)
class ChequePostdateAdmin(admin.ModelAdmin):
    """D9 : le dépôt, le retour et le rendu se font dans l'app (/cheques/), qui crée ou retire les paiements."""
    list_display = ["date_cheque", "client", "montant", "numero", "statut", "depose_le"]
    list_filter = ["entreprise", "statut"]
    search_fields = ["client__nom", "client__prenom", "numero"]
    date_hierarchy = "date_cheque"
    autocomplete_fields = ["client", "facture"]
    raw_id_fields = ["versement"]
    readonly_fields = ["statut", "depose_le", "paiement", "credit"]
