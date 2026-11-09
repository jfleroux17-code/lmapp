"""Préparer la saison suivante (B5), au cellulaire : aperçu, puis création."""
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from clients.importation import saison_en_cours
from core.acces import modification_clients_requise
from facturation import nouvelle_saison


def _pourcent(texte):
    try:
        p = Decimal((texte or "0").replace(",", ".").replace("%", "").strip())
    except InvalidOperation:
        return None
    return p if Decimal("-50") <= p <= Decimal("100") else None


@modification_clients_requise
def suivante(request):
    saison = saison_en_cours(request.entreprise)
    if saison.pk is None:
        messages.error(request, "Aucune saison enregistrée : rien à reprendre.")
        return redirect("terrain:comptes")
    donnees = request.POST if request.method == "POST" else request.GET
    pourcent, arrondi = _pourcent(donnees.get("pourcent")), donnees.get("arrondi") or "dollar"
    if pourcent is None:
        messages.error(request, "Ajustement entre -50 % et 100 %.")
        pourcent = Decimal("0")
    if request.method == "POST":
        try:
            nouvelle, a = nouvelle_saison.creer(saison, pourcent, arrondi)
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
        else:
            messages.success(request, f"Saison {nouvelle.nom} prête : {len(a.lignes)} contrat{'s' if len(a.lignes) > 1 else ''}. "
                                      "Rien n'est facturé : les versements deviendront des brouillons à leur date.")
            return redirect("terrain:comptes")
    return render(request, "terrain/argent/saison_suivante.html", {
        "a": nouvelle_saison.apercu(saison, pourcent, arrondi), "pourcent": pourcent, "arrondi": arrondi,
    })
