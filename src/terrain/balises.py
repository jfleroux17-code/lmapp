"""Balises (piquets) des adresses (PRD A11) : à poser à l'automne, à retirer au printemps, dans l'ordre de la tournée."""
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from clients.models import Adresse, Balisage
from core.acces import ecriture_requise, membre_requis, peut_ecrire
from tournee.models import arrets


@membre_requis
def liste(request):
    ent = request.entreprise
    vue = request.GET.get("vue") or ("poser" if timezone.localdate().month >= 8 else "retirer")
    en_place = {b.adresse_id: b for b in Balisage.objects.filter(entreprise=ent, retirees_le=None)}
    derniers = {}
    for b in Balisage.objects.filter(entreprise=ent).exclude(retirees_le=None).order_by("posees_le"):
        derniers[b.adresse_id] = b.nombre  # le nombre de la dernière saison, proposé pour la pose
    lignes = []
    for a in arrets(ent):
        b = en_place.get(a.pk)
        if (vue == "poser") == (b is None):
            lignes.append({"adresse": a, "balisage": b, "propose": derniers.get(a.pk, 4)})
    return render(request, "terrain/balises.html", {
        "vue": vue, "lignes": lignes, "ecriture": peut_ecrire(request),
        "total_en_place": sum(b.nombre for b in en_place.values()), "adresses_en_place": len(en_place),
    })


@require_POST
@ecriture_requise
def poser(request, adresse_pk):
    a = get_object_or_404(Adresse, pk=adresse_pk, entreprise=request.entreprise)
    try:
        nombre = max(1, min(50, int(request.POST.get("nombre") or 4)))
    except ValueError:
        nombre = 4
    try:
        with transaction.atomic():  # double tape : la contrainte « une seule en place » refuse la deuxième
            Balisage.objects.create(entreprise=request.entreprise, adresse=a, nombre=nombre)
        messages.success(request, f"{a.ligne1} : {nombre} balise{'s' if nombre > 1 else ''} posée{'s' if nombre > 1 else ''}.")
    except IntegrityError:
        messages.error(request, f"{a.ligne1} : des balises y sont déjà notées.")
    return redirect(request.POST.get("retour") or "terrain:balises")


@require_POST
@ecriture_requise
def retirer(request, pk):
    b = get_object_or_404(Balisage, pk=pk, entreprise=request.entreprise, retirees_le=None)
    b.retirees_le = timezone.localdate()
    b.save(update_fields=["retirees_le"])
    messages.success(request, f"{b.adresse.ligne1} : balises retirées.")
    return redirect(request.POST.get("retour") or f"/balises/?vue=retirer")
