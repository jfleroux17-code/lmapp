from django.contrib import admin

from django.http import HttpResponse

from communications.models import GABARITS_PAR_DEFAUT, ArchiveCourriel, EtatBoite, Gabarit, Message


@admin.register(Gabarit)
class GabaritAdmin(admin.ModelAdmin):
    list_display = ["genre", "entreprise", "texte"]
    list_filter = ["entreprise", "genre"]

    def get_changeform_initial_data(self, request):
        genre = request.GET.get("genre")
        return {"texte": GABARITS_PAR_DEFAUT.get(genre, "")} if genre else {}


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
