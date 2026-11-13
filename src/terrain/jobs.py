"""Écrans des jobs à la pièce (déneigement manuel, paysagement), depuis la fiche du client (demandes de Louis)."""
import json

from django.contrib import messages
from django.contrib.gis.geos import Point
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from clients.models import Client
from core.acces import ecriture_requise
from tournee import jobs as regles
from tournee.models import Job


def _point(d):
    try:
        lat, lon = float(d.get("lat")), float(d.get("lon"))
        precision = float(d.get("precision") or 0)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180) or precision > 500:
        return None
    return Point(lon, lat, srid=4326)


@require_POST
@ecriture_requise
def partir(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk, entreprise=request.entreprise)
    deja = regles.en_cours(request.entreprise, client).first()
    if deja:
        return redirect("terrain:job", pk=deja.pk)
    genre = request.POST.get("genre") if request.POST.get("genre") in Job.Genre.values else Job.Genre.DENEIGEMENT
    adresses = list(client.adresses.filter(active=True))
    adresse = next((a for a in adresses if str(a.pk) == request.POST.get("adresse")), adresses[0] if adresses else None)
    job = Job.objects.create(entreprise=request.entreprise, client=client, adresse=adresse, genre=genre, par=request.user)
    return redirect("terrain:job", pk=job.pk)


@ecriture_requise
def job(request, pk):
    j = get_object_or_404(Job.objects.select_related("client", "adresse"), pk=pk, entreprise=request.entreprise)
    return render(request, "terrain/jobs/job.html", {"j": j, "heures": regles.heures(j) if j.fin_le else None,
                                                     "taux": request.entreprise.taux_horaire})


@require_POST
@ecriture_requise
def position(request, pk):
    """Position du départ (dès l'ouverture de l'écran) ou de l'arrivée, en JSON."""
    j = get_object_or_404(Job, pk=pk, entreprise=request.entreprise)
    try:
        d = json.loads(request.body)
    except ValueError:
        return JsonResponse({"erreur": "illisible"}, status=400)
    p = _point(d)
    if p is None or d.get("quoi") not in ("depart", "arrivee"):
        return JsonResponse({"erreur": "position illisible"}, status=400)
    regles.noter_position(j, d["quoi"], p)
    return JsonResponse({"distance_km": float(j.distance_km) if j.distance_km is not None else None})


@require_POST
@ecriture_requise
def etape(request, pk):
    j = get_object_or_404(Job, pk=pk, entreprise=request.entreprise)
    quoi = request.POST.get("quoi")
    if quoi == "arrivee":
        regles.arrivee(j, _point(request.POST))
    elif quoi == "terminer":
        regles.terminer(j)
        messages.success(request, f"Job terminée : {j.sur_place_min} min sur place" + (f", {j.distance_km} km (aller, estimé)." if j.distance_km else "."))
    elif quoi == "facturer":
        try:
            f = regles.facturer(j)
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            return redirect("terrain:job", pk=j.pk)
        if not request.entreprise.taux_horaire:
            messages.warning(request, "Taux horaire et taux par kilomètre pas encore dans les Réglages : mettre les prix sur la facture.")
        messages.success(request, "Facture prête (brouillon) : ajouter le matériel au besoin, puis « Émettre et envoyer ».")
        return redirect("terrain:facture", pk=f.pk)
    elif quoi == "annuler" and j.facture_id is None:
        client_id = j.client_id
        j.delete()
        messages.success(request, "Job annulée.")
        return redirect("terrain:fiche", pk=client_id)
    return redirect("terrain:job", pk=j.pk)
