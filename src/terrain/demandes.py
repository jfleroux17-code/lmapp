"""Écrans des demandes des clients (PRD H1, H2) : liste, nouvelle demande (à la main ou depuis un message reçu), suivi."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from clients.models import Client
from communications.models import Message
from core.acces import ecriture_requise, membre_requis, peut_ecrire
from demandes.models import Demande

SOURCE_PAR_CANAL = {Message.Canal.TEXTO: Demande.Source.TEXTO, Message.Canal.COURRIEL: Demande.Source.COURRIEL}


@membre_requis
def liste(request):
    qs = Demande.objects.filter(entreprise=request.entreprise).select_related("client", "adresse")
    vue = request.GET.get("vue", "a_traiter")
    if vue == "reglees":
        liste_ = qs.filter(statut=Demande.Statut.REGLEE).order_by("-reglee_le")[:100]
    else:
        vue, liste_ = "a_traiter", qs.exclude(statut=Demande.Statut.REGLEE).order_by("-urgent", "statut", "cree_le")
    return render(request, "terrain/demandes/liste.html", {"liste": liste_, "vue": vue, "ecriture": peut_ecrire(request)})


@membre_requis
def demande(request, pk):
    d = get_object_or_404(Demande.objects.select_related("client", "adresse", "message"), pk=pk, entreprise=request.entreprise)
    return render(request, "terrain/demandes/demande.html", {"d": d, "ecriture": peut_ecrire(request), "statuts": Demande.Statut})


@ecriture_requise
def nouvelle(request):
    ent = request.entreprise
    msg = Message.objects.filter(pk=request.GET.get("message") or request.POST.get("message") or 0, entreprise=ent).first()
    client = Client.objects.filter(pk=request.GET.get("client") or request.POST.get("client") or 0, entreprise=ent).first()
    if client is None and msg is not None:
        client = msg.client
    adresses = list(client.adresses.filter(active=True)) if client else []
    if request.method == "POST":
        genre = request.POST.get("genre", "")
        d = Demande(entreprise=ent, client=client, genre=genre if genre in Demande.Genre.values else Demande.Genre.AUTRE,
                    urgent=bool(request.POST.get("urgent")), description=request.POST.get("description", "").strip(),
                    contact=request.POST.get("contact", "").strip()[:200], message=msg,
                    source=SOURCE_PAR_CANAL.get(msg.canal, Demande.Source.MANUEL) if msg else Demande.Source.MANUEL)
        adresse_pk = request.POST.get("adresse")
        d.adresse = next((a for a in adresses if str(a.pk) == adresse_pk), adresses[0] if len(adresses) == 1 else None)
        if not d.description:
            messages.error(request, "Décrire la demande.")
        else:
            try:
                d.full_clean()
                d.save()
                messages.success(request, f"Demande notée : {d.get_genre_display().lower()}.")
                return redirect("terrain:demande", pk=d.pk)
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))
    return render(request, "terrain/demandes/nouvelle.html", {
        "client": client, "message": msg, "adresses": adresses, "genres": Demande.Genre.choices,
        "urgents": [g.value for g in Demande.URGENTS],
        "description": request.POST.get("description") or (msg.contenu if msg else ""),
        "contact": request.POST.get("contact") or ("" if client or not msg else msg.expediteur),
    })


@require_POST
@ecriture_requise
def changer(request, pk):
    d = get_object_or_404(Demande, pk=pk, entreprise=request.entreprise)
    statut = request.POST.get("statut")
    if statut not in Demande.Statut.values:
        return redirect("terrain:demande", pk=d.pk)
    if statut == Demande.Statut.PLANIFIEE:
        d.prevue_le = parse_date(request.POST.get("prevue_le") or "") or d.prevue_le
        d.save(update_fields=["prevue_le"])
    d.changer_statut(statut, request.POST.get("reglement", "").strip())
    messages.success(request, f"Demande {d.get_statut_display().lower()}.")
    if statut == Demande.Statut.REGLEE:
        return redirect("terrain:demandes")
    return redirect("terrain:demande", pk=d.pk)
