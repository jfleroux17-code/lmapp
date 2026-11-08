from django.contrib import admin

from communications.models import GABARITS_PAR_DEFAUT, Gabarit, Message


@admin.register(Gabarit)
class GabaritAdmin(admin.ModelAdmin):
    list_display = ["genre", "entreprise", "texte"]
    list_filter = ["entreprise", "genre"]

    def get_changeform_initial_data(self, request):
        genre = request.GET.get("genre")
        return {"texte": GABARITS_PAR_DEFAUT.get(genre, "")} if genre else {}


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ["cree_le", "client", "genre", "canal", "destinataire", "statut"]
    list_filter = ["entreprise", "genre", "canal", "statut"]
    search_fields = ["client__nom", "destinataire", "contenu"]
    readonly_fields = [f.name for f in Message._meta.fields]

    def has_add_permission(self, request):
        return False
