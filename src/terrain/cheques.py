"""Écrans des chèques postdatés (PRD D9) : noter un chèque reçu d'avance, liste à déposer, déposé d'une tape."""
from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from clients.models import Client
from core.acces import ecriture_requise, membre_requis, peut_ecrire
from facturation import cheques as logique
from facturation.models import ChequePostdate, Facture, Versement
from facturation.templatetags.argent import argent
from terrain.argent import MontantField
from terrain.retour import retour_ou

S = ChequePostdate.Statut


@membre_requis
def liste(request):
    ent = request.entreprise
    jour = timezone.localdate()
    qs = ChequePostdate.objects.filter(entreprise=ent).select_related("client", "facture", "versement__contrat__saison")
    return render(request, "terrain/argent/cheques.html", {
        "a_deposer": qs.filter(statut=S.EN_MAIN, date_cheque__lte=jour),
        "a_venir": qs.filter(statut=S.EN_MAIN, date_cheque__gt=jour),
        "recents": qs.exclude(statut=S.EN_MAIN).filter(modifie_le__gte=timezone.now() - timedelta(days=60)).order_by("-modifie_le")[:30],
        "resume": logique.resume(ent, jour), "ecriture": peut_ecrire(request), "aujourdhui": jour,
    })


@ecriture_requise
def nouveau(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk, entreprise=request.entreprise)
    cibles = logique.cibles(client)
    valeurs = {"pour": request.POST.get("pour", ""), "numero": request.POST.get("numero", "").strip()[:30],
               "montant": request.POST.get("montant", ""), "date_cheque": request.POST.get("date_cheque", "")}
    if request.method == "POST":
        erreurs = []
        try:
            montant = MontantField(max_digits=10, decimal_places=2, min_value=Decimal("0.01")).clean(valeurs["montant"])
        except ValidationError:
            montant = None
            erreurs.append("Indiquer le montant du chèque.")
        date_cheque = parse_date(valeurs["date_cheque"] or "")
        if date_cheque is None:
            erreurs.append("Indiquer la date écrite sur le chèque.")
        c = ChequePostdate(entreprise=request.entreprise, client=client, numero=valeurs["numero"], montant=montant or 0,
                           date_cheque=date_cheque or timezone.localdate())
        pour = valeurs["pour"]
        if pour.startswith("v"):
            c.versement = Versement.objects.filter(pk=pour[1:] or 0, contrat__client=client).first()
        elif pour.startswith("f"):
            c.facture = Facture.objects.filter(pk=pour[1:] or 0, client=client).first()
        if pour not in [x[0] for x in cibles]:
            erreurs.append("Choisir ce que le chèque paie.")
        doublon = ChequePostdate.objects.filter(client=client, montant=c.montant, date_cheque=c.date_cheque, numero=c.numero,
                                                cree_le__gte=timezone.now() - timedelta(minutes=1)).exists()
        if not erreurs and doublon:  # double tape
            messages.info(request, "Ce chèque est déjà noté.")
            return retour_ou(request, "terrain:fiche", pk=client.pk)
        if not erreurs:
            try:
                c.full_clean()
                c.save()
                messages.success(request, f"Chèque de {argent(c.montant)} daté du {c.date_cheque:%d/%m/%Y} noté (en main)."
                                 + (" À déposer dès aujourd'hui." if c.date_cheque <= timezone.localdate() else ""))
                if request.POST.get("autre"):
                    return redirect("terrain:nouveau_cheque", client_pk=client.pk)
                return retour_ou(request, "terrain:fiche", pk=client.pk)
            except ValidationError as e:
                erreurs.extend(e.messages)
        for e in erreurs:
            messages.error(request, e)
    return render(request, "terrain/argent/nouveau_cheque.html", {
        "client": client, "cibles": [{"valeur": v, "libelle": l, "montant": f"{m:.2f}".replace(".", ",") if m is not None else "",
                                      "date": d.isoformat() if d else ""} for v, l, m, d in cibles],
        "valeurs": valeurs, "deja": client.cheques.filter(statut=S.EN_MAIN).order_by("date_cheque"),
    })


@require_POST
@ecriture_requise
def action(request, pk):
    c = get_object_or_404(ChequePostdate, pk=pk, entreprise=request.entreprise)
    quoi = request.POST.get("action")
    try:
        if quoi == "deposer":
            p, credit = logique.deposer(c)
            if p:
                f = p.facture
                messages.success(request, f"Chèque de {argent(c.montant)} déposé : {f} " + ("payée au complet." if f.solde <= 0 else f"(reste {argent(f.solde)})."))
            else:
                messages.success(request, f"Chèque de {argent(c.montant)} déposé : en crédit au compte de {c.client.nom_affiche}"
                                 + (", appliqué à ce qui était dû." if credit and credit.restant < credit.montant else
                                    ", il paiera la prochaine facture émise."))
        elif quoi == "retourner":
            logique.retourner(c, request.POST.get("raison", "").strip())
            messages.success(request, f"Chèque de {argent(c.montant)} retourné : le paiement est retiré, le montant redevient dû.")
        elif quoi == "rendre":
            logique.rendre(c)
            messages.success(request, f"Chèque de {argent(c.montant)} rendu au client.")
    except ValidationError as e:
        messages.error(request, " ".join(e.messages))
    suivant = request.POST.get("suivant", "")
    if suivant.startswith("/") and not suivant.startswith("//"):
        return redirect(suivant)
    return redirect("terrain:cheques")
