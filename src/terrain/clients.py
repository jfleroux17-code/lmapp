"""Ajout et modification des clients et de leurs adresses au cellulaire (PRD A12), sans l'administration.

Qui peut modifier : selon le mode de l'entreprise (K9, `core.acces.peut_modifier_clients`). Chaque écran a
Enregistrer et Annuler (K10). Les règles restent celles du modèle (téléphones en E.164, courriel nettoyé,
code postal, même entreprise); une adresse nouvelle ou déplacée est géocodée par le worker.
"""
from django import forms
from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from clients.models import Adresse, Client, Secteur
from core.acces import ecriture_requise, modification_clients_requise
from core.telephone import afficher

CHAMP = "champ"


def _attrs(**kw):
    return {"class": CHAMP, **kw}


class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ["prenom", "nom", "organisation", "cellulaire", "telephone_autre", "courriel", "canal_prefere",
                  "mode_paiement", "statut", "facturation_ligne1", "facturation_ligne2", "facturation_ville",
                  "facturation_code_postal", "notes"]
        widgets = {
            "prenom": forms.TextInput(attrs=_attrs(autocomplete="off", autocapitalize="words")),
            "nom": forms.TextInput(attrs=_attrs(autocomplete="off", autocapitalize="words")),
            "organisation": forms.TextInput(attrs=_attrs(autocomplete="off")),
            "cellulaire": forms.TextInput(attrs=_attrs(type="tel", inputmode="tel", autocomplete="off", placeholder="450 555-0100")),
            "telephone_autre": forms.TextInput(attrs=_attrs(type="tel", inputmode="tel", autocomplete="off")),
            "courriel": forms.EmailInput(attrs=_attrs(inputmode="email", autocomplete="off", autocapitalize="none")),
            "canal_prefere": forms.Select(attrs=_attrs()),
            "mode_paiement": forms.Select(attrs=_attrs()),
            "statut": forms.Select(attrs=_attrs()),
            "facturation_ligne1": forms.TextInput(attrs=_attrs()),
            "facturation_ligne2": forms.TextInput(attrs=_attrs()),
            "facturation_ville": forms.TextInput(attrs=_attrs()),
            "facturation_code_postal": forms.TextInput(attrs=_attrs(autocapitalize="characters", maxlength="7")),
            "notes": forms.Textarea(attrs=_attrs(rows=3)),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for champ in ("cellulaire", "telephone_autre"):  # 450 555-0100 plutôt que +14505550100
            if self.instance.pk and not self.is_bound:
                self.initial[champ] = afficher(getattr(self.instance, champ))


class AdresseForm(forms.ModelForm):
    class Meta:
        model = Adresse
        fields = ["ligne1", "ligne2", "ville", "code_postal", "secteur", "active", "ou_mettre_neige", "obstacles",
                  "borne_fontaine", "entree_en_pente", "consignes"]
        widgets = {
            "ligne1": forms.TextInput(attrs=_attrs(autocomplete="off", placeholder="123, rue Principale")),
            "ligne2": forms.TextInput(attrs=_attrs(autocomplete="off")),
            "ville": forms.TextInput(attrs=_attrs(autocomplete="off")),
            "code_postal": forms.TextInput(attrs=_attrs(autocapitalize="characters", maxlength="7")),
            "secteur": forms.Select(attrs=_attrs()),
            "ou_mettre_neige": forms.TextInput(attrs=_attrs()),
            "obstacles": forms.TextInput(attrs=_attrs()),
            "consignes": forms.Textarea(attrs=_attrs(rows=3)),
            "active": forms.CheckboxInput(attrs={"class": "h-6 w-6 accent-[#f5c400]"}),
            "borne_fontaine": forms.CheckboxInput(attrs={"class": "h-6 w-6 accent-[#f5c400]"}),
            "entree_en_pente": forms.CheckboxInput(attrs={"class": "h-6 w-6 accent-[#f5c400]"}),
        }

    def __init__(self, *args, entreprise=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["secteur"].queryset = Secteur.objects.filter(entreprise=entreprise).order_by("ordre", "nom")
        self.fields["secteur"].empty_label = "Aucun secteur"
        if not self.instance.pk and not self.is_bound and entreprise is not None:
            from core.models import VilleDesservie

            defaut = VilleDesservie.objects.filter(entreprise=entreprise, par_defaut=True).first()
            self.initial["ville"] = self.initial.get("ville") or (defaut.nom if defaut else entreprise.ville)


def _enregistrer(form, **attributs):
    """Affecte l'entreprise et le client avant la validation du modèle (clean() vérifie la même entreprise)."""
    for k, v in attributs.items():
        setattr(form.instance, k, v)
    if form.is_valid():
        return form.save()
    return None


@modification_clients_requise
def nouveau(request):
    ent = request.entreprise
    fc = ClientForm(request.POST or None, instance=Client(entreprise=ent), prefix="c")
    fa = AdresseForm(request.POST or None, instance=Adresse(entreprise=ent), prefix="a", entreprise=ent)
    if request.method == "POST":
        with transaction.atomic():
            client = _enregistrer(fc, entreprise=ent)
            adresse = _enregistrer(fa, entreprise=ent, client=client) if client else None
            if client and adresse:
                messages.success(request, f"Client ajouté : {client.nom_affiche}.")
                return redirect("terrain:fiche", pk=client.pk)
            transaction.set_rollback(True)
    return render(request, "terrain/clients/formulaire.html", {
        "titre": "Nouveau client", "formulaires": [("Client", fc), ("Adresse de service", fa)], "annuler": "terrain:accueil",
    })


@modification_clients_requise
def modifier(request, pk):
    client = get_object_or_404(Client, pk=pk, entreprise=request.entreprise)
    form = ClientForm(request.POST or None, instance=client, prefix="c")
    if request.method == "POST" and _enregistrer(form):
        messages.success(request, "Client enregistré.")
        return redirect("terrain:fiche", pk=client.pk)
    return render(request, "terrain/clients/formulaire.html", {
        "titre": f"Modifier : {client.nom_affiche}", "formulaires": [("Client", form)], "annuler_url": client.pk,
    })


@modification_clients_requise
def adresse(request, client_pk, pk=None):
    ent = request.entreprise
    client = get_object_or_404(Client, pk=client_pk, entreprise=ent)
    instance = get_object_or_404(Adresse, pk=pk, client=client) if pk else Adresse(entreprise=ent, client=client)
    form = AdresseForm(request.POST or None, instance=instance, prefix="a", entreprise=ent)
    if request.method == "POST" and _enregistrer(form, entreprise=ent, client=client):
        messages.success(request, "Adresse enregistrée." + ("" if pk else " Sa position sera trouvée dans une minute."))
        return redirect("terrain:fiche", pk=client.pk)
    return render(request, "terrain/clients/formulaire.html", {
        "titre": ("Modifier l'adresse" if pk else "Nouvelle adresse") + f" : {client.nom_affiche}",
        "formulaires": [("Adresse", form)], "annuler_url": client.pk,
    })


@modification_clients_requise
def position(request, pk):
    """Corriger la position d'une adresse (A13) : on déplace la carte sous un repère fixe (gants), ou « Je suis devant »
    (GPS du téléphone). La position devient « manuelle » ou « gps » et le géocodage ne l'écrase plus."""
    from django.contrib.gis.geos import Point
    from django.utils import formats, timezone

    from core.models import VilleDesservie

    a = get_object_or_404(Adresse.objects.select_related("client"), pk=pk, entreprise=request.entreprise)
    if request.method == "POST":
        try:
            lat, lng = float(request.POST["lat"]), float(request.POST["lng"])
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                raise ValueError
        except (KeyError, ValueError):
            messages.error(request, "Position illisible : réessayer.")
            return redirect("terrain:position_adresse", pk=a.pk)
        par_gps = request.POST.get("source") == "gps"
        a.position = Point(lng, lat, srid=4326)
        a.position_source = Adresse.SourcePosition.GPS if par_gps else Adresse.SourcePosition.MANUELLE
        a.position_precision = Adresse.Precision.ADRESSE
        comment = "Prise au GPS devant l'adresse" if par_gps else "Placée sur la carte"
        a.geocodage_note = f"{comment} le {formats.date_format(timezone.localdate(), 'j F Y')}."
        a.save(update_fields=["position", "position_source", "position_precision", "geocodage_note", "modifie_le"])
        messages.success(request, "Position enregistrée.")
        return redirect("terrain:fiche", pk=a.client_id)
    if a.position:
        centre, zoom = (a.position.y, a.position.x), 18
    else:
        ville = VilleDesservie.pour(a.entreprise_id, a.ville) or VilleDesservie.objects.filter(entreprise=a.entreprise_id).first()
        centre, zoom = ((ville.centre.y, ville.centre.x) if ville and ville.centre else (45.95, -74.13)), 14
    return render(request, "terrain/clients/position.html", {"a": a, "lat": centre[0], "lng": centre[1], "zoom": zoom})


@ecriture_requise
def ecrire(request, pk):
    """Écrire à un client (E2, E3) : texto ou courriel, depuis le numéro et l'adresse d'affaires; signature ajoutée."""
    from communications import envoi
    from communications.models import Genre, Message

    client = get_object_or_404(Client, pk=pk, entreprise=request.entreprise)
    ent = request.entreprise
    canaux = [(Message.Canal.TEXTO, f"Texto au {afficher(client.cellulaire)}")] if client.cellulaire else []
    if client.courriel:
        canaux.append((Message.Canal.COURRIEL, f"Courriel à {client.courriel}"))
    if request.method == "POST":
        canal, texte = request.POST.get("canal"), request.POST.get("texte", "").strip()
        sujet = request.POST.get("sujet", "").strip()[:200]
        if canal not in dict(canaux) or not texte:
            messages.error(request, "Choisir le texto ou le courriel, et écrire le message.")
        else:
            courriel = canal == Message.Canal.COURRIEL
            m = Message.objects.create(entreprise=ent, client=client, genre=Genre.MANUEL, canal=canal,
                                       destinataire=client.courriel if courriel else client.cellulaire,
                                       sujet=(sujet or f"Message de {ent.nom}") if courriel else "",
                                       contenu=f"{texte}\n\n{ent.signature_messages or ent.nom}")
            envoi.envoyer(m)
            if m.statut == Message.Statut.EN_FILE:
                messages.success(request, f"Message en route vers {m.destinataire}.")
            else:
                messages.error(request, f"Message pas envoyé : {m.erreur}")
            return redirect("terrain:fiche", pk=client.pk)
    return render(request, "terrain/clients/ecrire.html", {
        "client": client, "canaux": canaux, "signature": ent.signature_messages or ent.nom,
        "choisi": request.POST.get("canal") or (client.canal_prefere if client.canal_prefere in dict(canaux) else (canaux[0][0] if canaux else "")),
    })


@ecriture_requise
def noter_appel(request, pk):
    """Appel noté à la main (E6) : reçu ou fait, avec un résumé. Rien n'est envoyé; l'appel paraît dans le fil du client.
    « Noter et créer une demande » mène à la demande, texte proposé (oubli, plainte, etc.)."""
    from communications.models import Genre, Message

    client = get_object_or_404(Client, pk=pk, entreprise=request.entreprise)
    if request.method == "POST":
        sens = Message.Sens.SORTANT if request.POST.get("sens") == "fait" else Message.Sens.ENTRANT
        resume = request.POST.get("resume", "").strip()
        if not resume:
            messages.error(request, "Écrire un résumé de l'appel.")
        else:
            numero = client.cellulaire or client.telephone_autre
            m = Message.objects.create(
                entreprise=request.entreprise, client=client, genre=Genre.APPEL, canal=Message.Canal.APPEL, sens=sens,
                expediteur=numero if sens == Message.Sens.ENTRANT else "", destinataire=numero if sens == Message.Sens.SORTANT else "",
                statut=Message.Statut.RECU if sens == Message.Sens.ENTRANT else Message.Statut.ENVOYE,
                envoye_le=timezone.now(), lu=True, contenu=resume)
            if request.POST.get("demande"):
                return redirect(f"{reverse('terrain:nouvelle_demande')}?message={m.pk}")
            messages.success(request, "Appel noté.")
            return redirect("terrain:fiche", pk=client.pk)
    return render(request, "terrain/clients/appel.html", {"client": client, "sens": request.POST.get("sens", "recu"),
                                                          "resume": request.POST.get("resume", "")})
