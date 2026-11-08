"""Écrans de Louis pour l'argent (PRD C1, C7, D1 à D4) : factures et paiements au cellulaire.

Tout passe par les méthodes de facturation.models, qui gardent les règles
(numéro à l'émission, facture émise figée, pas de trop-perçu). Les actions sont
des POST suivis d'une redirection, avec un message de confirmation.
"""
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from clients.models import Client
from core.acces import ecriture_requise, membre_requis, peut_ecrire
from facturation.models import Facture, LigneFacture, Paiement, Service

ZERO = Decimal("0.00")


class MontantField(forms.DecimalField):
    """Accepte « 158,69 », « 158.69 », « 1 200 $ »."""

    def to_python(self, value):
        if isinstance(value, str):
            value = value.replace("$", "").replace(" ", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
        return super().to_python(value)


class LigneForm(forms.Form):
    service = forms.IntegerField(required=False, widget=forms.HiddenInput)
    description = forms.CharField(max_length=200, error_messages={"required": "Écrire ce qui est facturé."})
    quantite = MontantField(max_digits=8, decimal_places=2, min_value=Decimal("0.01"), initial=1)
    prix = MontantField(max_digits=10, decimal_places=2, min_value=ZERO, error_messages={"required": "Indiquer le prix."})


class PaiementForm(forms.Form):
    mode = forms.ChoiceField(choices=Paiement.Mode.choices, error_messages={"required": "Choisir le mode de paiement."})
    montant = MontantField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))
    reference = forms.CharField(max_length=100, required=False)
    date = forms.DateField(required=False)


def _facture(request, pk):
    return get_object_or_404(Facture.objects.select_related("client", "adresse", "contrat__saison"), pk=pk, entreprise=request.entreprise)


def _services(request):
    return Service.objects.filter(entreprise=request.entreprise, actif=True)


def _ajouter_ligne(facture, form, entreprise):
    d = form.cleaned_data
    service = Service.objects.filter(pk=d.get("service"), entreprise=entreprise).first() if d.get("service") else None
    facture.lignes.create(service=service, description=d["description"], quantite=d["quantite"], prix_unitaire=d["prix"],
                          taxable=service.taxable if service else True, ordre=facture.lignes.count())
    facture.recalculer()


@membre_requis
def nouvelle_facture(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk, entreprise=request.entreprise)
    form = LigneForm(request.POST or None)
    if request.method == "POST":
        if not peut_ecrire(request):
            return render(request, "terrain/refuse.html", {"message": "Ton compte est en lecture seule : tu peux consulter, pas modifier."}, status=403)
        if form.is_valid():
            with transaction.atomic():
                f = Facture.objects.create(entreprise=request.entreprise, client=client,
                                           adresse=client.adresses.filter(active=True).first())
                _ajouter_ligne(f, form, request.entreprise)
            return redirect("terrain:facture", pk=f.pk)
    return render(request, "terrain/argent/nouvelle_facture.html", {"client": client, "form": form, "services": _services(request)})


@membre_requis
def facture(request, pk):
    f = _facture(request, pk)
    contexte = {
        "f": f, "client": f.client, "lignes": f.lignes.all(), "paiements": f.paiements.order_by("date", "pk"),
        "ecriture": peut_ecrire(request), "services": _services(request),
        "form_ligne": LigneForm(), "form_paiement": PaiementForm(initial={"montant": f.solde}),
        "modes": Paiement.Mode.choices, "aujourdhui": timezone.localdate(),
        "envois": f.messages.order_by("-cree_le")[:5],
    }
    return render(request, "terrain/argent/facture.html", contexte)


def _brouillon_ou_erreur(request, f):
    if not f.modifiable:
        messages.error(request, "Cette facture est déjà émise : elle ne change plus.")
        return False
    return True


@require_POST
@ecriture_requise
def ajouter_ligne(request, pk):
    f = _facture(request, pk)
    if _brouillon_ou_erreur(request, f):
        form = LigneForm(request.POST)
        if form.is_valid():
            _ajouter_ligne(f, form, request.entreprise)
            messages.success(request, "Ligne ajoutée.")
        else:
            messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
    return redirect("terrain:facture", pk=f.pk)


@require_POST
@ecriture_requise
def retirer_ligne(request, pk, ligne_pk):
    f = _facture(request, pk)
    if _brouillon_ou_erreur(request, f):
        LigneFacture.objects.filter(pk=ligne_pk, facture=f).delete()
        f.recalculer()
        messages.success(request, "Ligne retirée.")
    return redirect("terrain:facture", pk=f.pk)


@require_POST
@ecriture_requise
def emettre(request, pk):
    f = _facture(request, pk)
    try:
        f.emettre()
        messages.success(request, f"Facture n° {f.numero} émise." if f.numero else "Solde émis.")
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    return redirect("terrain:facture", pk=f.pk)


@require_POST
@ecriture_requise
def supprimer_brouillon(request, pk):
    f = _facture(request, pk)
    client = f.client
    if _brouillon_ou_erreur(request, f):
        f.delete()
        messages.success(request, "Brouillon supprimé.")
        return redirect("terrain:fiche", pk=client.pk)
    return redirect("terrain:facture", pk=f.pk)


@require_POST
@ecriture_requise
def annuler(request, pk):
    f = _facture(request, pk)
    try:
        f.annuler(request.POST.get("raison", ""))
        messages.success(request, f"Facture n° {f.numero} annulée.")
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    return redirect("terrain:facture", pk=f.pk)


@require_POST
@ecriture_requise
def paiement(request, pk):
    f = _facture(request, pk)
    form = PaiementForm(request.POST)
    if not form.is_valid():
        messages.error(request, " ".join(e for errs in form.errors.values() for e in errs))
        return redirect("terrain:facture", pk=f.pk)
    d = form.cleaned_data
    # Double tape (réseau lent, gants) : le même paiement il y a moins d'une minute n'est pas enregistré deux fois
    if f.paiements.filter(montant=d["montant"], mode=d["mode"], cree_le__gte=timezone.now() - timedelta(minutes=1)).exists():
        messages.info(request, "Ce paiement est déjà enregistré.")
        return redirect("terrain:facture", pk=f.pk)
    p = Paiement(entreprise=request.entreprise, facture=f, montant=d["montant"], mode=d["mode"],
                 reference=d["reference"], date=d["date"] or timezone.localdate())
    try:
        with transaction.atomic():
            Facture.objects.select_for_update().get(pk=f.pk)  # deux paiements en même temps : l'un après l'autre
            p.full_clean()
            p.save()
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return redirect("terrain:facture", pk=f.pk)
    from facturation.templatetags.argent import argent
    reste = f.solde
    messages.success(request, f"{p.get_mode_display()} de {argent(p.montant)} enregistré. "
                              + ("Facture payée au complet." if reste <= 0 else f"Reste {argent(reste)}."))
    return redirect("terrain:facture", pk=f.pk)


@membre_requis
def factures(request):
    """Brouillons à émettre et factures émises récentes."""
    qs = Facture.objects.filter(entreprise=request.entreprise).select_related("client").avec_solde()
    return render(request, "terrain/argent/factures.html", {
        "brouillons": qs.filter(statut=Facture.Statut.BROUILLON).order_by("date_facture", "pk"),
        "recentes": qs.exclude(statut=Facture.Statut.BROUILLON).order_by("-date_facture", "-pk")[:50],
    })


@membre_requis
def comptes(request):
    """Comptes à recevoir (C7, J4) : qui doit quoi, depuis quand. Tri par montant ou par ancienneté."""
    aujourdhui = timezone.localdate()
    dues = Facture.objects.filter(entreprise=request.entreprise).a_recevoir()
    par_client = {}
    for f in dues.select_related("client").order_by("date_facture"):
        c = par_client.setdefault(f.client_id, {"client": f.client, "du": ZERO, "factures": 0, "depuis": f.date_facture})
        c["du"] += f.solde_du
        c["factures"] += 1
    lignes = list(par_client.values())
    from communications.relances import dernieres

    relances = dernieres(par_client.keys())
    for l in lignes:
        l["jours"] = max((aujourdhui - l["depuis"]).days, 0)
        l["relance"] = relances.get(l["client"].pk)
    tri = request.GET.get("tri", "anciennete")
    lignes.sort(key=(lambda l: -l["du"]) if tri == "montant" else (lambda l: l["depuis"]))
    encaisse_30j = (Paiement.objects.filter(entreprise=request.entreprise, date__gt=aujourdhui - timedelta(days=30))
                    .aggregate(s=Sum("montant"))["s"] or ZERO)
    return render(request, "terrain/argent/comptes.html", {
        "lignes": lignes, "tri": tri, "total": sum((l["du"] for l in lignes), ZERO),
        "plus_de_60": sum((l["du"] for l in lignes if l["jours"] > 60), ZERO),
        "encaisse_30j": encaisse_30j,
        "brouillons": Facture.objects.filter(entreprise=request.entreprise, statut=Facture.Statut.BROUILLON).count(),
    })


def resume_client(client):
    """Pour la fiche client : solde dû et dernières factures."""
    from communications import relances
    from communications.models import Message

    qs = client.factures.avec_solde().order_by("-date_facture", "-pk")
    dues = relances.factures_dues(client)
    resume = {"du": sum((f.solde_du for f in dues), ZERO), "factures_client": qs[:10]}
    if dues:
        niveau = relances.niveau_suivant(client, dues)
        resume["relance"] = {
            "niveau": niveau, "niveaux": [(n, g.label) for n, g in enumerate(relances.RELANCES, start=1)],
            "canaux": " et ".join(dict(Message.Canal.choices)[c].lower() for c in relances.canaux(client)),
            "historique": Message.objects.filter(client=client, genre__in=relances.RELANCES).order_by("-cree_le")[:5],
        }
    return resume


@require_POST
@ecriture_requise
def envoyer_facture(request, pk):
    """Envoi de la facture au client par courriel, PDF joint (C4). Le worker envoie; le statut paraît sur la facture."""
    from communications.factures import envoyer_facture as envoyer

    f = _facture(request, pk)
    try:
        m = envoyer(f)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return redirect("terrain:facture", pk=f.pk)
    if m.statut == m.Statut.EN_FILE:
        messages.success(request, f"Facture en route vers {m.destinataire}.")
    else:
        messages.error(request, f"{m.get_statut_display()} : {m.erreur}")
    return redirect("terrain:facture", pk=f.pk)


@require_POST
@ecriture_requise
def relancer(request, client_pk):
    """Relance du client (C8) : tout ce qu'il doit, au niveau proposé ou choisi, par son canal préféré."""
    from communications import relances

    client = get_object_or_404(Client, pk=client_pk, entreprise=request.entreprise)
    niveau = request.POST.get("niveau", "")
    try:
        envoyes = relances.relancer(client, int(niveau) if niveau.isdigit() else None)
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
        return redirect("terrain:fiche", pk=client.pk)
    partis = [m for m in envoyes if m.statut == m.Statut.EN_FILE]
    if partis:
        messages.success(request, f"{envoyes[0].get_genre_display()} en route : " + ", ".join(m.destinataire for m in partis) + ".")
    for m in envoyes:
        if m not in partis:
            messages.error(request, f"{m.get_canal_display()} pas envoyé : {m.erreur}")
    return redirect("terrain:fiche", pk=client.pk)
