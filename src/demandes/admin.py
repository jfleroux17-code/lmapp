from django.contrib import admin

from demandes.models import Demande


@admin.register(Demande)
class DemandeAdmin(admin.ModelAdmin):
    list_display = ["cree_le", "genre", "client", "contact", "statut", "urgent", "source"]
    list_filter = ["entreprise", "statut", "genre", "urgent", "source"]
    search_fields = ["client__nom", "contact", "description", "reglement"]
    raw_id_fields = ["client", "adresse", "message"]
