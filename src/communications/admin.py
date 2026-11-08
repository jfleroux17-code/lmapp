from django.contrib import admin

from communications.models import GABARITS_PAR_DEFAUT, EtatBoite, Gabarit, Message


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
    list_display = ["entreprise", "dernier_uid", "lue_le", "erreur"]
    readonly_fields = ["uidvalidite", "lue_le", "erreur"]
