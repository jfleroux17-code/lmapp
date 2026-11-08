from django.contrib import admin

from tournee.models import Operation, Passage


class PassageEnLigne(admin.TabularInline):
    model = Passage
    extra = 0
    fields = ["heure", "adresse", "statut", "raison", "note", "ligne_facture"]
    readonly_fields = ["ligne_facture"]
    autocomplete_fields = ["adresse"]


@admin.register(Operation)
class OperationAdmin(admin.ModelAdmin):
    list_display = ["__str__", "type", "debut", "fin", "operateur", "nb_passages"]
    list_filter = ["entreprise", "type"]
    inlines = [PassageEnLigne]

    @admin.display(description="passages")
    def nb_passages(self, obj):
        return obj.passages.count()


@admin.register(Passage)
class PassageAdmin(admin.ModelAdmin):
    list_display = ["heure", "adresse", "statut", "raison", "note", "operation"]
    list_filter = ["entreprise", "statut", "raison"]
    search_fields = ["adresse__ligne1", "adresse__client__nom", "note"]
    autocomplete_fields = ["adresse"]
    readonly_fields = ["ligne_facture"]
