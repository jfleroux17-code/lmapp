"""Écrans de tournée de Louis (PRD F1 à F6, F8) : une opération, l'arrêt suivant, Fait ou Sauté en une tape."""
import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from clients.models import Adresse, Client
from core.acces import ecriture_requise, membre_requis, peut_ecrire
from tournee import services
from tournee.models import Operation, Passage, arrets


def _arret_json(a, i, passage):
    from terrain.views import _liens_navigation

    return {
        "id": a.pk, "rang": i, "client_id": a.client_id, "client": a.client.nom_affiche,
        "fiche": reverse("terrain:fiche", args=[a.client_id]),
        "ligne1": a.ligne1, "ligne2": a.ligne2, "secteur": a.secteur.nom if a.secteur else "",
        "ordre": a.ordre_tournee, "recouvrement": a.client.statut == Client.Statut.RECOUVREMENT,
        "neige": a.ou_mettre_neige, "obstacles": a.obstacles, "borne": a.borne_fontaine, "pente": a.entree_en_pente,
        "consignes": a.consignes,
        "navigation": _liens_navigation(a),
        "passage": _passage_json(passage),
    }


def _passage_json(p):
    if p is None:
        return None
    return {"statut": p.statut, "raison": p.raison, "raison_texte": p.get_raison_display() if p.raison else "",
            "heure": timezone.localtime(p.heure).strftime("%H:%M"), "note": p.note}


@membre_requis
def tournee(request):
    op = Operation.en_cours_de(request.entreprise)
    if op is None:
        return render(request, "terrain/tournee/demarrer.html", {
            "types": Operation.Type.choices, "ecriture": peut_ecrire(request),
            "dernieres": Operation.objects.filter(entreprise=request.entreprise).order_by("-debut")[:5],
        })
    passages = {p.adresse_id: p for p in op.passages.all()}
    donnees = {
        "operation": {"id": op.pk, "type": op.get_type_display(), "debut": timezone.localtime(op.debut).strftime("%H h %M")},
        "arrets": [_arret_json(a, i, passages.get(a.pk)) for i, a in enumerate(arrets(request.entreprise), start=1)],
        "raisons": Passage.Raison.choices,
        "synchro": reverse("terrain:synchro"),
        "ecriture": peut_ecrire(request),
        "choisi": int(request.GET["arret"]) if request.GET.get("arret", "").isdigit() else None,
    }
    return render(request, "terrain/tournee/en_cours.html", {"op": op, "donnees": donnees, "ecriture": donnees["ecriture"]})


@require_POST
@ecriture_requise
def synchro(request):
    """Passages tapés sur le cellulaire, envoyés dès que possible (F10) : en direct, ou en
    rafale au retour du réseau. Chaque passage porte son opération et l'heure de la tape.
    Réponse : les identifiants acceptés (le cellulaire les retire de sa file) et refusés."""
    try:
        recu = json.loads(request.body)
        lot = recu["passages"]
        assert isinstance(lot, list) and len(lot) <= 500
    except (ValueError, KeyError, AssertionError, TypeError):
        return JsonResponse({"erreur": "Données illisibles."}, status=400)
    acceptes, refuses, maintenant = [], [], timezone.now()
    for item in lot:
        cle = str(item.get("cle", ""))[:64]
        try:
            op = Operation.objects.get(pk=int(item["operation"]), entreprise=request.entreprise)
            adresse = Adresse.objects.get(pk=int(item["adresse"]), entreprise=request.entreprise)
            statut, raison = item.get("statut"), item.get("raison") or ""
            if statut not in Passage.Statut.values or (statut == Passage.Statut.SAUTE and raison not in Passage.Raison.values):
                raise ValueError("statut")
            quand = parse_datetime(str(item.get("quand", ""))) or maintenant
            # Heure du cellulaire : ni dans le futur, ni avant le début de l'opération
            quand = min(max(quand, op.debut), maintenant)
            p = services.marquer(op, adresse, statut, raison=raison, note=str(item.get("note", "")).strip()[:300], quand=quand)
            acceptes.append({"cle": cle, "adresse": adresse.pk, "passage": _passage_json(p), "facture": bool(p.ligne_facture_id)})
        except (Operation.DoesNotExist, Adresse.DoesNotExist, KeyError, ValueError, TypeError, ValidationError):
            refuses.append(cle)
    return JsonResponse({"acceptes": acceptes, "refuses": refuses})


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
