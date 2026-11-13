"""Contrats et soldes antérieurs dans la fiche du client (décision de JF, 10 novembre 2026 : sans l'administration).

« + Contrat » : saison, adresse, saisonnier ou au passage, prix (avant taxes, ou taxes incluses ramené avant taxes comme
à l'import), services, entente en mots, nombre de versements (échéancier par défaut de l'entreprise, B3).
Un contrat se modifie ou se supprime tant qu'aucune facture n'y est liée; ensuite il est figé (comme une facture émise).
« + Solde antérieur » : montant dû d'une saison passée (C6), émis tout de suite, sans taxes.
Même droit que modifier les clients (K9).
"""
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from clients.models import Adresse, Client
from core.acces import modification_clients_requise
from facturation import calculs
from facturation.models import Contrat, Facture, Saison, Service
from terrain.argent import MontantField
from terrain.reglages import _habiller


class ContratForm(forms.ModelForm):
    prix = MontantField(label="Prix", max_digits=10, decimal_places=2, min_value=0,
                        help_text="Saisonnier : le prix de la saison. Au passage : le prix d'un passage.")
    taxes_incluses = forms.BooleanField(label="Ce prix comprend déjà les taxes", required=False,
                                        help_text="Coché : l'app calcule le prix avant taxes qui redonne exactement ce total.")
    versements = forms.TypedChoiceField(label="Nombre de versements", coerce=int, choices=[(n, str(n)) for n in range(1, 5)],
                                        help_text="Saisonnier seulement : le 1er aujourd'hui, les suivants aux dates de tes réglages.")

    class Meta:
        model = Contrat
        fields = ["saison", "adresse", "type", "prix", "services", "prix_texte", "notes"]
        widgets = {"services": forms.CheckboxSelectMultiple, "prix": forms.TextInput(attrs={"inputmode": "decimal"})}

    NOUVELLE = "nouvelle"

    def __init__(self, *args, client=None, nouvelle_adresse=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.client = client
        self.nouvelle_adresse = nouvelle_adresse
        ent = client.entreprise
        self.fields["saison"].queryset = Saison.objects.filter(entreprise=ent).order_by("-debut")
        self.fields["saison"].empty_label = None
        self.fields["adresse"].queryset = client.adresses.filter(active=True)
        self.fields["adresse"].empty_label = "Aucune adresse en particulier"
        self.fields["services"].queryset = Service.objects.filter(entreprise=ent, actif=True).order_by("ordre", "nom")
        self.fields["services"].required = False
        self.fields["prix"].widget.attrs.update(inputmode="decimal")
        if not ent.inscrit_taxes:
            del self.fields["taxes_incluses"]
        if not self.is_bound:
            nb = self.instance.versements.count() if self.instance.pk else 0
            self.initial["versements"] = nb or ent.versements_par_defaut
            if not self.instance.pk:
                actives = list(self.fields["adresse"].queryset[:2])
                if len(actives) == 1:
                    self.initial["adresse"] = actives[0].pk
        self.order_fields(["saison", "adresse", "type", "prix", "taxes_incluses", "versements", "services", "prix_texte", "notes"])
        _habiller(self)
        self.fields["services"].widget.attrs = {"class": "h-6 w-6 accent-[#f5c400]"}
        # Une autre adresse du même client, créée sur place (demande de Louis, 12 novembre 2026)
        self.fields["adresse"].widget.choices = list(self.fields["adresse"].choices) + [(self.NOUVELLE, "+ Nouvelle adresse de service")]
        self.fields["adresse"].widget.attrs["x-model"] = "adresse"

    def clean(self):
        d = super().clean()
        if self.errors:
            return d
        ent = self.client.entreprise
        doublon = Contrat.objects.none() if self.nouvelle_adresse else Contrat.objects.filter(client=self.client, saison=d["saison"], adresse=d.get("adresse"), actif=True).exclude(pk=self.instance.pk)
        if doublon.exists():
            raise ValidationError("Ce client a déjà un contrat pour cette adresse et cette saison : le modifier plutôt.")
        saisonnier = d["type"] == Contrat.Type.SAISONNIER
        nb = d["versements"] if saisonnier else 1
        self.exact = True
        if d.get("taxes_incluses"):
            self.total_entendu = d["prix"]
            d["prix"], self.exact = calculs.prix_avant_taxes(d["prix"], ent.taux_tps, ent.taux_tvq, nb)
            if not d.get("prix_texte"):
                d["prix_texte"] = f"{str(self.total_entendu).replace('.', ',')} $ taxes incluses" + (f", en {nb} versements" if nb > 1 else "")
        if saisonnier:
            # Vérifie l'échéancier avant d'enregistrer (il faut assez de dates dans les réglages)
            essai = Contrat(entreprise=ent, client=self.client, saison=d["saison"])
            try:
                essai.dates_par_defaut(nb)
            except ValidationError as e:
                raise ValidationError({"versements": e.messages[0] + " (Plus, Réglages, Versements des contrats)"})
        return d


def _modifiable(contrat):
    return not contrat.factures.exists()


def _enregistrer(request, form, contrat_existant, form_adresse=None):
    d = form.cleaned_data
    with transaction.atomic():
        c = form.save(commit=False)
        if form_adresse is not None:
            c.adresse = form_adresse.save()
        c.prix = d["prix"]
        c.prix_texte = d.get("prix_texte", "")[:300]
        c.save()
        form.save_m2m()
        if c.type == Contrat.Type.SAISONNIER:
            c.creer_echeancier_par_defaut(d["versements"])
        else:
            c.versements.all().delete()
    if not getattr(form, "exact", True):
        messages.warning(request, f"Taxes incluses : impossible au cent près (arrondi des taxes), prix avant taxes {c.prix} $.")
    messages.success(request, f"Contrat {c.saison} {'modifié' if contrat_existant else 'ajouté'}.")
    return redirect(f"/clients/{c.client_id}/?argent=1#argent")


def _formulaires(request, contrat, client):
    """Formulaire du contrat, et celui de la nouvelle adresse si « + Nouvelle adresse de service » est choisie."""
    from terrain.clients import AdresseForm
    ent = request.entreprise
    nouvelle = request.method == "POST" and request.POST.get("adresse") == ContratForm.NOUVELLE
    donnees = None
    if request.method == "POST":
        donnees = request.POST.copy()
        if nouvelle:
            donnees["adresse"] = ""
    form = ContratForm(donnees, instance=contrat, client=client, nouvelle_adresse=nouvelle)
    fa = AdresseForm(request.POST if nouvelle else None, instance=Adresse(entreprise=ent, client=client),
                     prefix="a", entreprise=ent)
    return form, (fa if nouvelle else None)


def _contexte(form, fa, client, **autres):
    from terrain.clients import AdresseForm
    if fa is None:
        ent = client.entreprise
        fa = AdresseForm(instance=Adresse(entreprise=ent, client=client), prefix="a", entreprise=ent)
        nouvelle = False
    else:
        nouvelle = True
    adresse = ContratForm.NOUVELLE if nouvelle else (form["adresse"].value() or "")
    return {"form": form, "form_adresse": fa, "adresse_initiale": adresse, "client": client, **autres}


@modification_clients_requise
def nouveau(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk, entreprise=request.entreprise)
    if not Saison.objects.filter(entreprise=request.entreprise).exists():
        messages.error(request, "Aucune saison : en créer une d'abord (Plus, Réglages, Saisons).")
        return redirect("terrain:fiche", pk=client.pk)
    contrat = Contrat(entreprise=request.entreprise, client=client)
    form, fa = _formulaires(request, contrat, client)
    if request.method == "POST" and form.is_valid() and (fa is None or fa.is_valid()):
        return _enregistrer(request, form, False, fa)
    return render(request, "terrain/argent/contrat.html", _contexte(form, fa, client, titre="Nouveau contrat"))


@modification_clients_requise
def modifier(request, pk):
    contrat = get_object_or_404(Contrat, pk=pk, entreprise=request.entreprise)
    client = contrat.client
    if not _modifiable(contrat):
        messages.error(request, "Ce contrat a déjà des factures : il ne se modifie plus. Ajuster par une facture ou un crédit.")
        return redirect(f"/clients/{client.pk}/?argent=1#argent")
    form, fa = _formulaires(request, contrat, client)
    if request.method == "POST" and form.is_valid() and (fa is None or fa.is_valid()):
        return _enregistrer(request, form, True, fa)
    return render(request, "terrain/argent/contrat.html", _contexte(form, fa, client, titre=f"Contrat {contrat.saison}", contrat=contrat))


@require_POST
@modification_clients_requise
def supprimer(request, pk):
    contrat = get_object_or_404(Contrat, pk=pk, entreprise=request.entreprise)
    client_pk = contrat.client_id
    if not _modifiable(contrat):
        messages.error(request, "Ce contrat a déjà des factures : il ne se supprime pas.")
    else:
        nom = str(contrat.saison)
        contrat.delete()  # ses versements avec lui (aucun n'est facturé)
        messages.success(request, f"Contrat {nom} supprimé.")
    return redirect(f"/clients/{client_pk}/?argent=1#argent")


class SoldeForm(forms.Form):
    montant = MontantField(label="Montant dû", max_digits=10, decimal_places=2, min_value=0.01,
                           widget=forms.TextInput(attrs={"inputmode": "decimal"}), help_text="Sans taxes : c'est ce qu'il doit, tel quel.")
    saison = forms.CharField(label="Saison d'origine", max_length=20, required=False, help_text="Ex. 2025-2026")
    note = forms.CharField(label="Note interne", max_length=300, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _habiller(self)


@modification_clients_requise
def solde_anterieur(request, client_pk):
    client = get_object_or_404(Client, pk=client_pk, entreprise=request.entreprise)
    form = SoldeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        f = Facture.solde_ouverture(client, d["montant"], saison_origine=d["saison"], note=d["note"])
        messages.success(request, f"Solde antérieur de {str(f.total).replace('.', ',')} $ ajouté au compte de {client.nom_affiche}.")
        return redirect(f"/clients/{client.pk}/?argent=1#argent")
    return render(request, "terrain/argent/contrat.html", {"form": form, "client": client, "titre": "Solde antérieur",
                                                           "explication": "Ce que le client devait avant l'app (saison passée). "
                                                                          "Il paraît tout de suite dans ce qu'il doit et dans les relances."})
