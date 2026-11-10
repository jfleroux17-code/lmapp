"""Titres de l'administration en bon français (audit UX, 9 novembre 2026).

Django écrit « Sélectionnez l'objet client à changer », « Modification de entreprise » et
« Supprimer les entreprises sélectionnés ». On remplace ces titres pour tous les modèles,
sans toucher à chaque ModelAdmin : liste = « Clients », fiche = « Modifier : client »,
ajout = « Ajouter : client », action de suppression = « Supprimer la sélection ».
"""
from django.contrib import admin
from django.contrib.admin.actions import delete_selected


def _avec_titre(vue, titre):
    def enveloppe(request, *args, extra_context=None, **kwargs):
        extra_context = {"title": titre, **(extra_context or {})}
        return vue(request, *args, extra_context=extra_context, **kwargs)
    return enveloppe


def franciser(site=admin.site):
    delete_selected.short_description = "Supprimer la sélection"
    for modele, ma in site._registry.items():
        o = modele._meta
        ma.changelist_view = _avec_titre(ma.changelist_view, str(o.verbose_name_plural)[:1].upper() + str(o.verbose_name_plural)[1:])
        ma.add_view = _avec_titre(ma.add_view, f"Ajouter : {o.verbose_name}")
        ma.change_view = _avec_titre(ma.change_view, f"Modifier : {o.verbose_name}")
