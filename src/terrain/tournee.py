"""Écrans de tournée de Louis (PRD F1 à F6, F8) : une opération, l'arrêt suivant, Fait ou Sauté en une tape."""
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from clients.models import Adresse
from core.acces import ecriture_requise, membre_requis, peut_ecrire
from tournee import services
from tournee.models import Operation, Passage, arrets


@membre_requis
def tournee(request):
    from terrain.views import _liens_navigation

    op = Operation.en_cours_de(request.entreprise)
    if op is None:
        return render(request, "terrain/tournee/demarrer.html", {
            "types": Operation.Type.choices, "ecriture": peut_ecrire(request),
            "dernieres": Operation.objects.filter(entreprise=request.entreprise).order_by("-debut")[:5],
        })
    liste = list(arrets(request.entreprise))
    passages = {p.adresse_id: p for p in op.passages.all()}
    choisi = None
    if request.GET.get("arret"):
        choisi = next((a for a in liste if str(a.pk) == request.GET["arret"]), None)
    prochain = next((a for a in liste if a.pk not in passages), None)
    courant = choisi or prochain
    return render(request, "terrain/tournee/en_cours.html", {
        "op": op, "ecriture": peut_ecrire(request),
        "lignes": [{"a": a, "passage": passages.get(a.pk), "rang": i} for i, a in enumerate(liste, start=1)],
        "courant": courant, "passage_courant": passages.get(courant.pk) if courant else None,
        "navigation": _liens_navigation(courant) if courant else [],
        "faits": sum(1 for p in passages.values() if p.statut == Passage.Statut.FAIT),
        "sautes": sum(1 for p in passages.values() if p.statut == Passage.Statut.SAUTE),
        "total": len(liste), "raisons": Passage.Raison.choices,
    })


@require_POST
@ecriture_requise
def demarrer(request):
    t = request.POST.get("type")
    if t not in Operation.Type.values:
        messages.error(request, "Choisir le type d'opération.")
        return redirect("terrain:tournee")
    try:
        with transaction.atomic():  # point de sauvegarde : le refus ne gâche pas le reste de la requête
            op = Operation.objects.create(entreprise=request.entreprise, type=t, operateur=request.user)
        messages.success(request, f"Opération « {op.get_type_display()} » commencée.")
    except IntegrityError:
        messages.info(request, "Une opération est déjà en cours.")
    return redirect("terrain:tournee")


@require_POST
@ecriture_requise
def passage(request, adresse_pk):
    op = Operation.en_cours_de(request.entreprise)
    if op is None:
        messages.error(request, "Aucune opération en cours : la démarrer d'abord.")
        return redirect("terrain:tournee")
    adresse = get_object_or_404(Adresse, pk=adresse_pk, entreprise=request.entreprise)
    statut = request.POST.get("statut")
    raison = request.POST.get("raison", "")
    if statut not in Passage.Statut.values or (statut == Passage.Statut.SAUTE and raison not in Passage.Raison.values):
        messages.error(request, "Choisir Fait, ou Sauté avec une raison.")
        return redirect("terrain:tournee")
    p = services.marquer(op, adresse, statut, raison=raison, note=request.POST.get("note", "").strip()[:300])
    texte = "fait" if p.statut == Passage.Statut.FAIT else f"sauté ({p.get_raison_display().lower()})"
    messages.success(request, f"{adresse.client.nom_affiche}, {adresse.ligne1} : {texte}."
                              + (" Passage ajouté à sa facture." if p.ligne_facture_id else ""))
    return redirect("terrain:tournee")


@require_POST
@ecriture_requise
def terminer(request):
    op = Operation.en_cours_de(request.entreprise)
    if op is not None:
        op.terminer()
        faits = op.passages.filter(statut=Passage.Statut.FAIT).count()
        sautes = op.passages.filter(statut=Passage.Statut.SAUTE).count()
        reste = arrets(request.entreprise).count() - faits - sautes
        messages.success(request, f"Opération terminée : {faits} fait{'s' if faits > 1 else ''}, {sautes} sauté{'s' if sautes > 1 else ''}"
                                  + (f", {reste} pas visité{'s' if reste > 1 else ''}." if reste > 0 else "."))
    return redirect("terrain:tournee")
