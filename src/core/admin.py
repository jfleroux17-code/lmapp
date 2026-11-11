from django.conf import settings
from django.contrib import admin, messages
from django.contrib.gis.geos import Point

from core.models import (AbonnementNotification, DemandeSite, EchecConnexion, Entreprise, FacturePlateforme, IncidentConfidentialite,
                         JournalAction, LigneFacturePlateforme, Membre, VilleDesservie)

_titre = "Le Déneigeur : administration"
if settings.LMAPP_ENV != "prod":
    _titre = f"Le Déneigeur : administration (ENVIRONNEMENT DE {settings.LMAPP_ENV.upper()})"

admin.site.site_header = _titre
admin.site.site_title = _titre
admin.site.index_title = "Tableau de bord"
admin.site.index_template = "admin/index_lmapp.html"  # ajoute le lien vers l'écran de la plateforme
_index_django = admin.site.index


def etat_plateforme():
    """Cartes de l'accueil (audit UX) : est-ce que tout roule? Envois en échec, file de tâches, sauvegarde, envois réels."""
    from datetime import timedelta

    from django.utils import timezone

    from communications.models import Message
    from core import surveillance

    file_ok, file_detail = surveillance.verifier_file()
    sauve_ok, sauve_detail = surveillance.verifier_sauvegarde()
    if "illisible" in sauve_detail:
        sauve_detail = "aucun témoin de sauvegarde ici (normal en test : pas de sauvegarde des données fictives)"
    return {
        "echecs_7j": Message.objects.filter(statut=Message.Statut.ECHEC, cree_le__gte=timezone.now() - timedelta(days=7)).count(),
        "file_ok": file_ok, "file_detail": file_detail,
        "sauvegarde_ok": sauve_ok, "sauvegarde_detail": sauve_detail,
        "entreprises_envois": list(Entreprise.objects.filter(active=True).order_by("nom").values_list("nom", "envois_actifs")),
        "demandes_nouvelles": DemandeSite.objects.filter(statut=DemandeSite.Statut.NOUVELLE).count(),
        "factures_plateforme_brouillons": FacturePlateforme.objects.filter(statut=FacturePlateforme.Statut.BROUILLON).count(),
        "factures_plateforme_dues": FacturePlateforme.objects.filter(statut=FacturePlateforme.Statut.EMISE).count(),
    }


def _index_lmapp(request, extra_context=None):
    """Accueil de l'administration : l'état de la plateforme en cartes (superutilisateur)."""
    extra_context = dict(extra_context or {})
    if request.user.is_superuser:
        extra_context.update(etat_plateforme())
    return _index_django(request, extra_context)


admin.site.index = _index_lmapp


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
        ("Communications", {"fields": ["envois_actifs", "numero_texto", "courriel_reponse", "signature_messages"],
                            "description": "« Envois réels activés » : de vrais textos et courriels partent aux clients. "
                                           "À changer seulement avec le go de Jean-François (une confirmation est demandée, le changement va au journal)."}),
        ("Avis pendant les opérations", {"fields": ["avis_proximite_actif", "avis_rayon_m", "minutes_par_arret", "avis_passage_fait"]}),
        ("Versements des contrats", {"fields": ["versements_par_defaut", "dates_versements", "jours_avance_versement"]}),
        ("Relances proposées", {"fields": ["relances_proposees", "relances_soldes_anterieurs"]}),
        ("Paiement Interac", {"fields": ["interac_courriel", "interac_instructions"]}),
        ("Abonnement à la plateforme", {"fields": ["abonnement_facture"],
                                        "description": "Coché : la facture du mois passé est préparée en brouillon le 1er du mois "
                                                       "(Factures de la plateforme). Rien n'est émis ni envoyé sans Jean-François."}),
    ]
    actions = ["preparer_facture_plateforme"]

    @admin.action(description="Préparer la facture de la plateforme du mois passé (brouillon)")
    def preparer_facture_plateforme(self, request, queryset):
        from django.utils import timezone

        from core import abonnement

        premier = abonnement.mois_precedent(abonnement.debut_du_mois(timezone.localdate()))
        for ent in queryset:
            f, cree = abonnement.preparer(ent, premier)
            self.message_user(request, f"{ent.nom} : {'brouillon préparé' if cree else 'facture déjà là'} ({f}).")

    class Media:
        js = ["admin_lmapp/envois_reels.js"]  # confirmation avant d'allumer ou d'éteindre les envois réels

    def has_delete_permission(self, request, obj=None):
        return False  # une entreprise ne s'efface pas d'un clic : la désactiver (case « active »)

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
    list_display = ["quand", "nom_utilisateur", "action", "modele", "objet", "resume", "entreprise"]
    list_filter = ["action", "modele", "entreprise", "nom_utilisateur"]
    search_fields = ["objet", "nom_utilisateur", "=objet_id", "=client_id"]
    date_hierarchy = "moment"
    readonly_fields = ["moment", "entreprise", "nom_utilisateur", "ip", "action", "modele", "objet_id", "objet", "client_id", "detail"]
    exclude = ["utilisateur", "changements"]

    @admin.display(description="moment", ordering="moment")
    def quand(self, obj):
        from django.utils import timezone

        from core.templatetags.dates_qc import date_texte

        return date_texte(timezone.localtime(obj.moment), "j M Y, H \\h i")

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


@admin.register(DemandeSite)
class DemandeSiteAdmin(admin.ModelAdmin):
    """Demandes reçues à info@ (site Internet) : suivi des clients potentiels, par JF seulement."""
    list_display = ["recu_le", "nom", "expediteur", "sujet", "statut", "transfert"]
    list_filter = ["statut"]
    list_editable = ["statut"]
    search_fields = ["nom", "expediteur", "sujet", "texte", "note"]
    date_hierarchy = "recu_le"
    fields = ["statut", "note", "recu_le", "nom", "expediteur", "sujet", "texte", "pieces_jointes",
              "transferee_le", "erreur_transfert"]
    readonly_fields = ["recu_le", "nom", "expediteur", "sujet", "texte", "pieces_jointes", "transferee_le", "erreur_transfert"]
    actions = ["telecharger_eml", "transferer_de_nouveau"]

    @admin.display(description="transférée", boolean=True)
    def transfert(self, obj):
        return obj.transferee_le is not None

    @admin.action(description="Télécharger le courriel (.eml)")
    def telecharger_eml(self, request, queryset):
        from django.http import HttpResponse

        if queryset.count() != 1:
            self.message_user(request, "Choisir une seule demande.", messages.WARNING)
            return None
        d = queryset.get()
        r = HttpResponse(d.octets(), content_type="message/rfc822")
        r["Content-Disposition"] = f'attachment; filename="demande-{d.pk}.eml"'
        return r

    @admin.action(description="Transférer de nouveau (au prochain passage du worker)")
    def transferer_de_nouveau(self, request, queryset):
        n = queryset.update(transferee_le=None, essais_transfert=0, erreur_transfert="")
        self.message_user(request, f"{n} demande(s) seront transférées d'ici 2 minutes.")

    def has_add_permission(self, request):
        return False

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


class LigneFacturePlateformeEnLigne(admin.TabularInline):
    model = LigneFacturePlateforme
    extra = 0
    fields = ["ordre", "description", "quantite", "prix_unitaire", "montant_affiche"]
    readonly_fields = ["montant_affiche"]

    @admin.display(description="montant")
    def montant_affiche(self, obj):
        from facturation.templatetags.argent import argent

        return argent(obj.montant) if obj.pk else "-"

    def _brouillon(self, obj):
        return obj is None or obj.modifiable

    def has_add_permission(self, request, obj=None):
        return request.user.is_superuser and self._brouillon(obj)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser and self._brouillon(obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser and self._brouillon(obj)


@admin.register(FacturePlateforme)
class FacturePlateformeAdmin(admin.ModelAdmin):
    """Factures de la plateforme aux déneigeurs (PRD Q2), par JF seulement. Brouillon modifiable (lignes, note),
    puis Émettre, Envoyer par courriel, Payée ou Annuler. Jamais effacée une fois émise."""
    list_display = ["entreprise", "mois_affiche", "statut", "numero", "total", "envoyee_le", "pdf"]
    list_filter = ["statut", "entreprise"]
    inlines = [LigneFacturePlateformeEnLigne]
    actions = ["emettre", "envoyer", "marquer_payee", "annuler"]
    fields = ["entreprise", "mois", "statut", "numero", "date_facture", "date_echeance", "note", "raison_annulation",
              "sous_total", "tps", "tvq", "total", "textos_envoyes", "textos_recus", "courriels", "utilisateurs",
              "envoyee_le", "envoyee_a", "erreur_envoi", "payee_le", "pdf"]

    def get_readonly_fields(self, request, obj=None):
        figes = ["statut", "numero", "date_facture", "date_echeance", "sous_total", "tps", "tvq", "total", "envoyee_le",
                 "envoyee_a", "erreur_envoi", "payee_le", "pdf", "textos_envoyes", "textos_recus", "courriels", "utilisateurs"]
        if obj and not obj.modifiable:
            figes += ["entreprise", "mois", "note"]
        if obj and obj.statut == FacturePlateforme.Statut.ANNULEE:
            figes += ["raison_annulation"]
        return figes

    @admin.display(description="mois", ordering="mois")
    def mois_affiche(self, obj):
        from core.templatetags.dates_qc import date_texte

        return date_texte(obj.mois, "F Y")

    @admin.display(description="PDF")
    def pdf(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html

        return format_html('<a href="{}" target="_blank">Voir le PDF</a>', reverse("admin:core_factureplateforme_pdf", args=[obj.pk])) if obj.pk else "-"

    def get_urls(self):
        from django.urls import path

        return [path("<int:pk>/pdf/", self.admin_site.admin_view(self.vue_pdf), name="core_factureplateforme_pdf")] + super().get_urls()

    def vue_pdf(self, request, pk):
        from django.http import HttpResponse, Http404

        from core import abonnement

        if not request.user.is_superuser:
            raise Http404
        f = FacturePlateforme.objects.filter(pk=pk).select_related("entreprise").first()
        if f is None:
            raise Http404
        r = HttpResponse(abonnement.pdf(f), content_type="application/pdf")
        r["Content-Disposition"] = f'inline; filename="facture-le-deneigeur-{f.numero or "brouillon"}.pdf"'
        return r

    def save_related(self, request, form, formsets, change):
        from core import abonnement

        super().save_related(request, form, formsets, change)
        if form.instance.modifiable:
            abonnement.recalculer(form.instance)

    @admin.action(description="Émettre (numéro, taxes et échéance figés)")
    def emettre(self, request, queryset):
        from django.core.exceptions import ValidationError

        from core import abonnement

        for f in queryset.order_by("mois", "entreprise__nom"):
            try:
                abonnement.emettre(f)
                self.message_user(request, f"{f.entreprise.nom} : facture n° {f.numero} émise.")
            except ValidationError as e:
                self.message_user(request, f"{f} : {' '.join(e.messages)}", messages.ERROR)

    @admin.action(description="Envoyer par courriel (PDF joint, depuis info@)")
    def envoyer(self, request, queryset):
        from django.core.exceptions import ValidationError

        from core import abonnement

        for f in queryset:
            try:
                dest = abonnement.demander_envoi(f)
                self.message_user(request, f"{f} : en route vers {dest} (worker, d'ici quelques secondes).")
            except ValidationError as e:
                self.message_user(request, f"{f} : {' '.join(e.messages)}", messages.ERROR)

    @admin.action(description="Marquer payée (aujourd'hui)")
    def marquer_payee(self, request, queryset):
        from django.utils import timezone

        n = queryset.filter(statut=FacturePlateforme.Statut.EMISE).update(statut=FacturePlateforme.Statut.PAYEE, payee_le=timezone.localdate())
        self.message_user(request, f"{n} facture(s) marquée(s) payée(s).")

    @admin.action(description="Annuler (raison à écrire d'abord dans la facture)")
    def annuler(self, request, queryset):
        for f in queryset:
            if f.statut == FacturePlateforme.Statut.ANNULEE:
                continue
            if not f.raison_annulation.strip():
                self.message_user(request, f"{f} : écrire la raison de l'annulation dans la facture d'abord.", messages.ERROR)
                continue
            f.statut = FacturePlateforme.Statut.ANNULEE
            f.save(update_fields=["statut", "modifie_le"])
            self.message_user(request, f"{f} : annulée.")

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser and (obj is None or obj.modifiable)  # un brouillon s'efface, une facture émise non
