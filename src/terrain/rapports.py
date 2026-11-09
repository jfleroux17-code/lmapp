"""Rapport de la saison (J2, J3), aussi pour le rôle lecture seule (le comptable)."""
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from clients.importation import saison_en_cours
from core.acces import membre_requis
from facturation import rapports
from facturation.models import Saison


def _saison(request, pk=None):
    if pk:
        return get_object_or_404(Saison, pk=pk, entreprise=request.entreprise)
    return saison_en_cours(request.entreprise)


@membre_requis
def saison(request):
    s = _saison(request, request.GET.get("saison") if (request.GET.get("saison") or "").isdigit() else None)
    if s.pk is None:
        return redirect("terrain:comptes")
    return render(request, "terrain/argent/rapport_saison.html", {
        **rapports.saison(request.entreprise, s), "saisons": Saison.objects.filter(entreprise=request.entreprise).order_by("-debut")})


@membre_requis
def saison_pdf(request, pk):
    s = _saison(request, pk)
    r = HttpResponse(rapports.pdf(request.entreprise, s), content_type="application/pdf")
    r["Content-Disposition"] = f'inline; filename="rapport-saison-{s.nom}.pdf"'
    r["Cache-Control"] = "private, no-store"
    return r
