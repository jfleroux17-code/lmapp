"""Export pour le comptable (PRD C12) : factures et paiements d'une période, en CSV qu'Excel ouvre tel quel
(point-virgule, UTF-8 avec BOM, virgule décimale). Format générique : un format propre à QuickBooks, Sage ou
Acomba se fera quand on saura quel logiciel le comptable utilise. Ouvert au rôle lecture seule (le comptable)."""
import csv
from datetime import date

from django.http import HttpResponse
from django.shortcuts import render

from core.acces import membre_requis
from facturation.models import Facture, Paiement


def _date(texte, defaut):
    try:
        return date.fromisoformat(texte)
    except (TypeError, ValueError):
        return defaut


def _argent(v):
    return f"{v:.2f}".replace(".", ",")


def _csv(nom, entetes, lignes):
    r = HttpResponse(content_type="text/csv; charset=utf-8")
    r["Content-Disposition"] = f'attachment; filename="{nom}"'
    r["Cache-Control"] = "private, no-store"
    r.write("﻿")  # Excel reconnaît l'UTF-8
    w = csv.writer(r, delimiter=";")
    w.writerow(entetes)
    w.writerows(lignes)
    return r


@membre_requis
def export(request):
    from clients.importation import saison_en_cours

    saison = saison_en_cours(request.entreprise)
    du = _date(request.GET.get("du"), saison.debut)
    au = _date(request.GET.get("au"), saison.fin)
    quoi = request.GET.get("quoi")
    suffixe = f"{du:%Y-%m-%d}_au_{au:%Y-%m-%d}.csv"
    if quoi == "factures":
        factures = (Facture.objects.filter(entreprise=request.entreprise, date_facture__gte=du, date_facture__lte=au)
                    .exclude(statut=Facture.Statut.BROUILLON).avec_solde().select_related("client").order_by("date_facture", "numero", "pk"))
        return _csv(f"factures_{suffixe}", ["Numéro", "Date", "Genre", "Client", "Statut", "Sous-total", "TPS", "TVQ", "Total",
                                            "Payé", "Solde", "Échéance", "Annulée le", "Raison de l'annulation"], [
            [f.numero or "", f"{f.date_facture:%Y-%m-%d}", "Solde antérieur" if f.genre == Facture.Genre.SOLDE_OUVERTURE else "Facture",
             f.client.nom_affiche, f.get_statut_display(), _argent(f.sous_total), _argent(f.tps), _argent(f.tvq), _argent(f.total),
             _argent(f.montant_paye), _argent(f.solde_du if f.statut == Facture.Statut.EMISE else 0),
             f"{f.date_echeance:%Y-%m-%d}" if f.date_echeance else "", f"{f.annulee_le:%Y-%m-%d}" if f.annulee_le else "",
             f.raison_annulation] for f in factures])
    if quoi == "paiements":
        paiements = (Paiement.objects.filter(entreprise=request.entreprise, date__gte=du, date__lte=au)
                     .select_related("facture__client").order_by("date", "pk"))
        from facturation.models import Credit

        lignes = [[f"{p.date:%Y-%m-%d}", p.facture.numero or "Solde antérieur", p.facture.client.nom_affiche, p.get_mode_display(),
                   _argent(p.montant), p.reference, p.note] for p in paiements]
        # D7 : l'argent reçu en trop est une entrée d'argent; son application (mode « crédit au compte ») n'en est pas une
        lignes += [[f"{c.date:%Y-%m-%d}", "Surplus en crédit", c.client.nom_affiche, c.get_mode_display(), _argent(c.montant), c.reference,
                    c.note] for c in Credit.objects.filter(entreprise=request.entreprise, date__gte=du, date__lte=au).select_related("client")]
        lignes.sort(key=lambda l: l[0])
        return _csv(f"paiements_{suffixe}", ["Date", "Facture", "Client", "Mode", "Montant", "Référence", "Note"], lignes)
    if quoi == "depenses":
        from facturation.models import Depense

        depenses = Depense.objects.filter(entreprise=request.entreprise, date__gte=du, date__lte=au).defer("photo").order_by("date", "pk")
        return _csv(f"depenses_{suffixe}", ["Date", "Catégorie", "Fournisseur", "Avant taxes", "TPS", "TVQ", "Total", "Note", "Photo du reçu"], [
            [f"{d.date:%Y-%m-%d}", d.get_categorie_display(), d.fournisseur, _argent(d.avant_taxes), _argent(d.tps), _argent(d.tvq),
             _argent(d.total), d.note, "oui" if d.photo_taille else "non"] for d in depenses])
    return render(request, "terrain/argent/export.html", {"du": du, "au": au, "saison": saison})
