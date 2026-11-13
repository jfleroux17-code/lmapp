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
                                        help_text="Saisonnier seulement : le 1er à l'envoi de la facture, les suivants aux dates de tes réglages.")
    envoyer_le = forms.DateField(label="Envoyer la facture le", required=False, widget=forms.DateInput(attrs={"type": "date"}),
                                 help_text="Aujourd'hui : on arrive sur la facture pour l'envoyer. Plus tard (ex. client inscrit en plein "
                                           "été) : elle attend en brouillon et sera proposée ce jour-là dans « Versements à envoyer ».")

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
        from django.utils import timezone

        if not self.is_bound:
            prevue = None
            if self.instance.pk:
                f = self.instance.factures.filter(statut=Facture.Statut.BROUILLON, versements__isnull=False).first()
                prevue = f.envoyer_le if f else None
            self.initial["envoyer_le"] = prevue or timezone.localdate()
        self.fields["envoyer_le"].widget.attrs["min"] = timezone.localdate().isoformat()
        self.order_fields(["saison", "adresse", "type", "prix", "taxes_incluses", "versements", "envoyer_le", "services", "prix_texte", "notes"])
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
            d["prix"], self.exact = calculs.prix_avant_taxes(d["prix"], ent.taux_tps, ent.taux_tvq, 1)  # une facture, taxes une fois
            if not d.get("prix_texte"):
                d["prix_texte"] = f"{str(self.total_entendu).replace('.', ',')} $ taxes incluses" + (f", en {nb} versements" if nb > 1 else "")
        if saisonnier:
            from django.utils import timezone

            envoi = d.get("envoyer_le") or timezone.localdate()
            if envoi < timezone.localdate():
                raise ValidationError({"envoyer_le": "Aujourd'hui ou plus tard."})
            if envoi > d["saison"].fin:
                raise ValidationError({"envoyer_le": f"Au plus tard la fin de la saison ({d['saison'].fin:%d/%m/%Y})."})
            d["envoyer_le"] = envoi
            # Vérifie l'échéancier avant d'enregistrer (il faut assez de dates dans les réglages)
            essai = Contrat(entreprise=ent, client=self.client, saison=d["saison"])
            try:
                essai.dates_par_defaut(nb)
            except ValidationError as e:
                raise ValidationError({"versements": e.messages[0] + " (Plus, Réglages, Versements des contrats)"})
        return d


def _modifiable(contrat):
    """Modifiable tant que sa facture (de saison) n'est pas émise : le brouillon est refait avec le contrat."""
    return not contrat.factures.exclude(statut=Facture.Statut.BROUILLON).exists()


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
        facture = None
        if c.type == Contrat.Type.SAISONNIER:
            envoi = d["envoyer_le"]
            c.creer_echeancier_par_defaut(d["versements"], approbation=envoi)  # 1er versement à l'envoi de la facture
            # Une seule facture pour la saison, prête en brouillon (décision de JF, 12 novembre 2026)
            facture = c.facturer_saison()
            if facture.modifiable:  # prix ou services changés : le brouillon suit le contrat
                facture.lignes.all().delete()
                n = c.versements.count()
                facture.lignes.create(description=f"Déneigement, saison {c.saison}" + (f" (en {n} versements)" if n > 1 else ""),
                                      quantite=1, prix_unitaire=c.prix)
                facture.adresse = c.adresse
                from django.utils import timezone

                facture.envoyer_le = envoi if envoi > timezone.localdate() else None  # envoi prévu plus tard (client d'avance)
                facture.save(update_fields=["adresse", "envoyer_le"])
                facture.recalculer()
        else:
            for f in c.factures.filter(statut=Facture.Statut.BROUILLON, versements__isnull=False).distinct():
                f.lignes.all().delete()
                f.delete()
            c.versements.all().delete()
    if not getattr(form, "exact", True):
        messages.warning(request, f"Taxes incluses : impossible au cent près (arrondi des taxes), prix avant taxes {c.prix} $.")
    if facture is not None and facture.modifiable and facture.envoyer_le:
        messages.success(request, f"Contrat {c.saison} {'modifié' if contrat_existant else 'ajouté'}. Sa facture de la saison attend en "
                                  f"brouillon; elle sera proposée le {facture.envoyer_le:%d/%m/%Y} dans « Versements à envoyer ».")
        return redirect(f"/clients/{c.client_id}/?argent=1#argent")
    if facture is not None:
        messages.success(request, f"Contrat {c.saison} {'modifié' if contrat_existant else 'ajouté'}. Sa facture de la saison est prête "
                                  "(brouillon) : la vérifier, puis l'émettre et l'envoyer.")
        return redirect("terrain:facture", pk=facture.pk)
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
        messages.error(request, "La facture de ce contrat est émise : il ne se modifie plus. Ajuster par une facture ou un crédit, ou annuler la facture.")
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
        messages.error(request, "La facture de ce contrat est émise : il ne se supprime pas (annuler la facture d'abord).")
    else:
        nom = str(contrat.saison)
        with transaction.atomic():
            for f in contrat.factures.filter(statut=Facture.Statut.BROUILLON):
                f.lignes.all().delete()
                f.delete()
            contrat.delete()  # ses versements avec lui (facture encore en brouillon : effacée)
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


# Nouveau client en un seul passage (lot E, demande de Louis du 12 novembre 2026) : services choisis avec leur prix
# pour la saison en cours, nombre de versements; le contrat, son échéancier et la facture de la saison (brouillon)
# sont créés avec le client. On arrive ensuite sur la facture : « Émettre et envoyer » d'une tape.

def saison_courante(entreprise):
    from django.utils import timezone

    jour = timezone.localdate()
    qs = Saison.objects.filter(entreprise=entreprise)
    return qs.filter(debut__lte=jour, fin__gte=jour).first() or qs.filter(debut__gt=jour).order_by("debut").first() or qs.order_by("-debut").first()


def contexte_contrat_rapide(request):
    from django.utils import timezone

    ent = request.entreprise
    services = list(Service.objects.filter(entreprise=ent, actif=True).order_by("ordre", "nom"))
    choisis = set(request.POST.getlist("k-service"))
    return {"saison": saison_courante(ent), "versements": range(1, 5), "inscrit": ent.inscrit_taxes,
            "actif": request.method != "POST" or bool(request.POST.get("k-actif")),
            "nb_versements": int(request.POST.get("k-versements") or ent.versements_par_defaut or 1),
            "envoi": request.POST.get("k-envoi") or timezone.localdate().isoformat(), "aujourdhui": timezone.localdate().isoformat(),
            "taxes_incluses": bool(request.POST.get("k-taxes_incluses")),
            "services": [{"s": s, "choisi": str(s.pk) in choisis,
                          "prix": request.POST.get(f"k-prix-{s.pk}", f"{s.prix_suggere:.2f}".replace(".", ",") if s.prix_suggere else "")}
                         for s in services]}


def contrat_rapide(request, client, adresse):
    """Crée le contrat de la saison depuis la section du formulaire. Renvoie (facture brouillon ou None, erreurs)."""
    if not request.POST.get("k-actif"):
        return None, []
    ent = request.entreprise
    saison = saison_courante(ent)
    if saison is None:
        return None, ["Aucune saison : en créer une (Plus, Réglages, Saisons), ou décocher le contrat."]
    champ = MontantField(max_digits=10, decimal_places=2, min_value=0)
    lignes, erreurs = [], []
    for s in Service.objects.filter(entreprise=ent, actif=True, pk__in=[x for x in request.POST.getlist("k-service") if x.isdigit()]).order_by("ordre", "nom"):
        try:
            prix = champ.clean(request.POST.get(f"k-prix-{s.pk}", ""))
        except ValidationError:
            erreurs.append(f"Prix de « {s.nom} » : un montant, ex. 450 ou 450,00.")
            continue
        lignes.append((s, prix))
    if not lignes and not erreurs:
        erreurs.append("Contrat : cocher au moins un service, avec son prix.")
    if erreurs:
        return None, erreurs
    try:
        nb = max(1, min(4, int(request.POST.get("k-versements") or 1)))
    except ValueError:
        nb = 1
    # Date d'envoi de la facture (client qui s'inscrit d'avance, ex. en plein été) : jamais avant aujourd'hui
    from django.utils import timezone
    from django.utils.dateparse import parse_date

    aujourdhui = timezone.localdate()
    envoi = parse_date(request.POST.get("k-envoi") or "") or aujourdhui
    if envoi < aujourdhui:
        return None, ["Date d'envoi de la facture : aujourd'hui ou plus tard."]
    if envoi > saison.fin:
        return None, [f"Date d'envoi de la facture : au plus tard la fin de la saison ({saison.fin:%d/%m/%Y})."]
    total = sum((p for _, p in lignes), 0)
    exact = True
    if request.POST.get("k-taxes_incluses") and ent.inscrit_taxes:
        total_entendu = total
        total, exact = calculs.prix_avant_taxes(total, ent.taux_tps, ent.taux_tvq, 1)
        texte = f"{', '.join(f'{s.nom} {p:.2f} $'.replace('.', ',') for s, p in lignes)} : {str(total_entendu).replace('.', ',')} $ taxes incluses"
    else:
        texte = " + ".join(f"{s.nom} {p:.2f} $".replace(".", ",") for s, p in lignes) + (" plus taxes" if ent.inscrit_taxes else "")
    if nb > 1:
        texte += f", en {nb} versements"
    c = Contrat(entreprise=ent, client=client, adresse=adresse, saison=saison, prix=total, prix_texte=texte[:300])
    try:
        c.full_clean()
        c.save()
        c.services.set([s for s, _ in lignes])
        c.creer_echeancier_par_defaut(nb, approbation=envoi)  # 1er versement à l'envoi de la facture
    except ValidationError as e:
        return None, [" ".join(e.messages) + " (Plus, Réglages, Versements des contrats)"]
    f = c.facturer_saison()
    if envoi > aujourdhui:
        f.envoyer_le = envoi
        f.save(update_fields=["envoyer_le"])
    if not exact:
        messages.warning(request, f"Taxes incluses : impossible au cent près (arrondi des taxes), prix avant taxes {c.prix} $.")
    return f, []
