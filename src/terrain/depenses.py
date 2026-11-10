"""Écrans des dépenses par photo (PRD S1, S2) : « + Dépense » (photo du reçu), liste par mois, correction."""
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from clients.models import PhotoAdresse
from core.acces import ecriture_requise, membre_requis, peut_ecrire
from facturation import depenses as logique
from facturation.models import Depense
from facturation.templatetags.argent import argent
from terrain.argent import MontantField


def _montant(texte, obligatoire=False):
    texte = (texte or "").strip()
    if not texte:
        if obligatoire:
            raise ValidationError("Indiquer le total payé.")
        return None
    try:
        return MontantField(max_digits=10, decimal_places=2, min_value=0).clean(texte)
    except ValidationError:
        raise ValidationError(f"Montant « {texte} » illisible.")


def _remplir(request, d):
    """Valeurs du formulaire dans la dépense. TPS et TVQ vides : calculées à partir du total."""
    p = request.POST
    erreurs = []
    try:
        d.total = _montant(p.get("total"), obligatoire=True)
    except ValidationError as e:
        erreurs.extend(e.messages)
    d.date = parse_date(p.get("date") or "") or d.date or timezone.localdate()
    if d.date > timezone.localdate():
        erreurs.append("La date ne peut pas être dans le futur.")
    d.categorie = p.get("categorie") if p.get("categorie") in Depense.Categorie.values else Depense.Categorie.AUTRE
    d.fournisseur = p.get("fournisseur", "").strip()[:100]
    d.note = p.get("note", "").strip()[:200]
    try:
        tps, tvq = _montant(p.get("tps")), _montant(p.get("tvq"))
    except ValidationError as e:
        erreurs.extend(e.messages)
        tps = tvq = None
    if d.total and (tps is None or tvq is None):
        calc_tps, calc_tvq = logique.taxes_du_total(d.total, request.entreprise)
        tps = calc_tps if tps is None else tps
        tvq = calc_tvq if tvq is None else tvq
    d.tps, d.tvq = tps or 0, tvq or 0
    f = request.FILES.get("photo")
    if f is not None:
        if f.size > PhotoAdresse.MAX_OCTETS:
            erreurs.append("Photo trop lourde (8 Mo au plus).")
        else:
            octets = f.read()
            mime = PhotoAdresse.type_de(octets[:16])
            if mime is None:
                erreurs.append("Ce fichier n'est pas une photo.")
            else:
                d.photo, d.photo_type, d.photo_taille = octets, mime, len(octets)
    if not erreurs:
        try:
            d.full_clean(exclude=["entreprise", "saisie_par"])
        except ValidationError as e:
            erreurs.extend(e.messages)
    return erreurs


def _contexte(request, d):
    return {"d": d, "categories": Depense.Categorie.choices, "aujourdhui": timezone.localdate(), "ecriture": peut_ecrire(request),
            "inscrit": request.entreprise.inscrit_taxes}


@membre_requis
def liste(request):
    ent = request.entreprise
    from clients.importation import saison_en_cours

    s = saison_en_cours(ent)
    aujourdhui = timezone.localdate()
    debut_mois = aujourdhui.replace(day=1)
    return render(request, "terrain/depenses/liste.html", {
        "recentes": Depense.objects.filter(entreprise=ent).defer("photo")[:30],
        "saison": s, "bilan": logique.bilan(ent, s.debut, s.fin),
        "ce_mois": logique.bilan(ent, debut_mois, aujourdhui), "debut_mois": debut_mois,
        "ecriture": peut_ecrire(request),
    })


@ecriture_requise
def nouvelle(request):
    d = Depense(entreprise=request.entreprise, saisie_par=request.user)
    if request.method == "POST":
        erreurs = _remplir(request, d)
        if not erreurs:
            d.save()
            messages.success(request, f"Dépense de {argent(d.total)} notée ({d.get_categorie_display().lower()})"
                             + ("." if d.photo else ", sans photo du reçu."))
            return redirect("terrain:depenses")
        for e in erreurs:
            messages.error(request, e)
    return render(request, "terrain/depenses/formulaire.html", _contexte(request, d))


@membre_requis
def depense(request, pk):
    d = get_object_or_404(Depense.objects.defer("photo"), pk=pk, entreprise=request.entreprise)
    if request.method == "POST":
        if not peut_ecrire(request):
            return redirect("terrain:depense", pk=d.pk)
        d = Depense.objects.get(pk=d.pk)
        erreurs = _remplir(request, d)
        if not erreurs:
            d.save()
            messages.success(request, "Dépense corrigée.")
            return redirect("terrain:depenses")
        for e in erreurs:
            messages.error(request, e)
    return render(request, "terrain/depenses/formulaire.html", _contexte(request, d))


@require_POST
@ecriture_requise
def supprimer(request, pk):
    d = get_object_or_404(Depense, pk=pk, entreprise=request.entreprise)
    d.delete()
    messages.success(request, f"Dépense de {argent(d.total)} du {d.date:%d/%m/%Y} supprimée.")
    return redirect("terrain:depenses")


@membre_requis
def photo(request, pk):
    d = get_object_or_404(Depense, pk=pk, entreprise=request.entreprise)
    if not d.photo:
        return HttpResponse(status=404)
    r = HttpResponse(bytes(d.photo), content_type=d.photo_type)
    r["Cache-Control"] = "private, max-age=604800"
    return r
