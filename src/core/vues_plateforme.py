"""Écran de la plateforme pour JF (superutilisateur), dans l'administration (/admin/ est réservé à ses IP)."""
import csv

from django.contrib import admin
from django.contrib.admin.views.decorators import staff_member_required
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from core import plateforme

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]


@staff_member_required
def tableau(request):
    if not request.user.is_superuser:
        raise PermissionDenied
    aujourdhui = timezone.localdate()
    try:
        annee = int(request.GET.get("annee", aujourdhui.year))
        numero = int(request.GET.get("mois", aujourdhui.month))
        debut, fin = plateforme.mois(annee, numero)
    except ValueError:
        annee, numero = aujourdhui.year, aujourdhui.month
        debut, fin = plateforme.mois(annee, numero)
    lignes, total = plateforme.statistiques(debut, fin)
    titre = f"{MOIS[numero - 1]} {annee}"
    if request.GET.get("format") == "csv":
        r = HttpResponse(content_type="text/csv; charset=utf-8")
        r["Content-Disposition"] = f'attachment; filename="lmapp-usage-{annee}-{numero:02d}.csv"'
        r.write("﻿")  # Excel reconnaît l'UTF-8
        w = csv.writer(r, delimiter=";")
        w.writerow(["Entreprise", "Identifiant"] + [nom for _, nom in plateforme.COLONNES])
        for l in lignes:
            w.writerow([l["entreprise"].nom, l["entreprise"].slug] + [
                (timezone.localtime(l[k]).strftime("%Y-%m-%d %H:%M") if k == "derniere_connexion" and l.get(k)
                 else str(l[k]).replace(".", ",") if l.get(k) is not None else "") for k, _ in plateforme.COLONNES])
        return r
    precedent = plateforme.mois(annee - (numero == 1), (numero - 2) % 12 + 1)[0]
    suivant = fin
    return render(request, "admin/plateforme.html", {
        **admin.site.each_context(request), "title": f"Plateforme : {titre}", "lignes": lignes, "total": total,
        "colonnes": plateforme.COLONNES, "annee": annee, "mois": numero, "titre_mois": titre,
        "precedent": precedent, "suivant": suivant if suivant <= aujourdhui.replace(day=1) else None,
    })
