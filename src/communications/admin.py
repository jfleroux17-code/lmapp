from django.contrib import admin

from django.http import HttpResponse

from communications.models import VARIABLES_PAR_GENRE, ArchiveCourriel, EtatBoite, Gabarit, GabaritParDefaut, Message


@admin.register(Gabarit)
class GabaritAdmin(admin.ModelAdmin):
    list_display = ["genre", "entreprise", "texte"]
    list_filter = ["entreprise", "genre"]

    def get_changeform_initial_data(self, request):
        genre = request.GET.get("genre")
        return {"texte": GabaritParDefaut.texte_de(genre)} if genre else {}


@admin.register(GabaritParDefaut)
class GabaritParDefautAdmin(admin.ModelAdmin):
    """Console de JF : les textes par défaut de toute la plateforme. Superutilisateur seulement."""
    list_display = ["genre", "texte", "modifie_le"]
    readonly_fields = ["variables", "copies", "modifie_le"]
    fields = ["genre", "texte", "variables", "copies", "modifie_le"]

    def has_module_permission(self, request):
        return request.user.is_superuser

    has_view_permission = has_change_permission = has_add_permission = lambda self, request, obj=None: request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False  # sans texte par défaut, le message retomberait sur le texte du code : on le modifie plutôt

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (["genre"] if obj else [])

    @admin.display(description="variables permises")
    def variables(self, obj):
        noms = VARIABLES_PAR_GENRE.get(obj.genre, []) if obj and obj.genre else []
        return ", ".join("{" + v + "}" for v in noms) or "aucune"

    @admin.display(description="entreprises qui ont leur propre copie")
    def copies(self, obj):
        if not obj or not obj.genre:
            return "-"
        noms = list(Gabarit.objects.filter(genre=obj.genre).values_list("entreprise__nom", flat=True))
        return ", ".join(noms) if noms else "aucune : toutes utilisent ce texte"


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["cree_le", "sens", "client", "genre", "canal", "destinataire", "expediteur", "statut"]
    list_filter = ["entreprise", "sens", "genre", "canal", "statut", "lu"]
    search_fields = ["client__nom", "destinataire", "expediteur", "sujet", "contenu"]
    readonly_fields = [f.name for f in Message._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(EtatBoite)
class EtatBoiteAdmin(admin.ModelAdmin):
    list_display = ["entreprise", "dossier", "dernier_uid", "uid_depart", "lue_le", "erreur"]
    readonly_fields = ["uidvalidite", "lue_le", "erreur"]


@admin.register(ArchiveCourriel)
class ArchiveCourrielAdmin(admin.ModelAdmin):
    """Seule copie d'un courriel effacé de la boîte : consultation et téléchargement, jamais de modification."""
    list_display = ["archive_le", "dossier", "expediteur", "destinataires", "sujet", "taille", "efface_le"]
    list_filter = ["entreprise", "dossier", ("efface_le", admin.EmptyFieldListFilter)]
    search_fields = ["expediteur", "destinataires", "sujet", "entete_message_id"]
    exclude = ["brut"]
    readonly_fields = [f.name for f in ArchiveCourriel._meta.fields if f.name != "brut"]
    actions = ["telecharger"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.action(description="Télécharger le courriel (.eml, un seul à la fois)")
    def telecharger(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, "Choisir un seul courriel.", level="error")
            return None
        a = queryset.get()
        r = HttpResponse(a.octets(), content_type="message/rfc822")
        r["Content-Disposition"] = f'attachment; filename="courriel-{a.pk}.eml"'
        return r
