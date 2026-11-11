"""Messages types (E9) : les gabarits par défaut de la plateforme (modifiés par JF dans sa console), en lecture
seule, et les copies de l'entreprise. Cloner un gabarit par défaut en fait une copie modifiable, qui remplace le
texte par défaut pour cette entreprise seulement; « Revenir au texte par défaut » efface la copie.
Modifier : même droit que modifier les clients (K9)."""
from django import forms
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from communications.models import GABARITS_PAR_DEFAUT, VARIABLES_PAR_GENRE, Gabarit, GabaritParDefaut, Genre, verifier_texto
from core.acces import membre_requis, modification_clients_requise, peut_modifier_clients

AIDE_VARIABLES = {
    "adresse": "adresse du client", "minutes": "minutes avant l'arrivée", "heure": "heure du passage",
    "client": "nom du client", "montant": "montant", "factures": "factures visées", "depuis": "date de la plus vieille facture",
    "paiement": "instructions Interac", "mode": "mode de paiement", "date": "date du paiement", "solde": "solde restant",
}


def _genre(genre):
    if genre not in GABARITS_PAR_DEFAUT:
        raise Http404
    return genre


def _variables(genre):
    return [("{" + v + "}", AIDE_VARIABLES.get(v, "")) for v in VARIABLES_PAR_GENRE.get(genre, [])]


@membre_requis
def liste(request):
    defauts = {g.genre: g for g in GabaritParDefaut.objects.all()}
    copies = {g.genre: g for g in Gabarit.objects.filter(entreprise=request.entreprise)}
    lignes = []
    for genre in GABARITS_PAR_DEFAUT:
        d = defauts.get(genre)
        c = copies.get(genre)
        lignes.append({"genre": genre, "nom": Genre(genre).label, "defaut": d.texte if d else GABARITS_PAR_DEFAUT[genre],
                       "copie": c, "defaut_change": bool(c and d and d.modifie_le > c.modifie_le),
                       "variables": _variables(genre)})
    return render(request, "terrain/gabarits/liste.html", {"lignes": lignes, "peut_modifier": peut_modifier_clients(request),
                                                           "signature": request.entreprise.signature_messages or request.entreprise.nom})


@require_POST
@modification_clients_requise
def cloner(request, genre):
    genre = _genre(genre)
    _, cree = Gabarit.objects.get_or_create(entreprise=request.entreprise, genre=genre,
                                            defaults={"texte": GabaritParDefaut.texte_de(genre)})
    if cree:
        messages.success(request, "Copie créée : modifiez-la à votre goût.")
    return redirect("terrain:modifier_gabarit", genre=genre)


class GabaritForm(forms.ModelForm):
    class Meta:
        model = Gabarit
        fields = ["texte"]
        widgets = {"texte": forms.Textarea(attrs={"class": "champ", "rows": 6})}
        labels = {"texte": "Votre texte"}
        help_texts = {"texte": ""}


@modification_clients_requise
def modifier(request, genre):
    genre = _genre(genre)
    copie = Gabarit.objects.filter(entreprise=request.entreprise, genre=genre).first()
    if copie is None:
        return redirect("terrain:gabarits")
    form = GabaritForm(request.POST or None, instance=copie)
    if request.method == "POST" and form.is_valid():
        copie = form.save()
        messages.success(request, f"« {Genre(genre).label} » enregistré.")
        _, avertissement = verifier_texto(genre, copie.texte, copie.signature_pour_texto())
        if avertissement:
            messages.warning(request, avertissement)
        return redirect("terrain:gabarits")
    return render(request, "terrain/gabarits/modifier.html", {
        "form": form, "nom": Genre(genre).label, "genre": genre, "defaut": GabaritParDefaut.texte_de(genre),
        "variables": _variables(genre), "signature": request.entreprise.signature_messages or request.entreprise.nom})


@require_POST
@modification_clients_requise
def retirer(request, genre):
    genre = _genre(genre)
    Gabarit.objects.filter(entreprise=request.entreprise, genre=genre).delete()
    messages.success(request, f"« {Genre(genre).label} » : retour au texte par défaut.")
    return redirect("terrain:gabarits")
