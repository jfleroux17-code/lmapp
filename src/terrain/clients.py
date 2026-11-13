"""Ajout et modification des clients et de leurs adresses au cellulaire (PRD A12), sans l'administration.

Qui peut modifier : selon le mode de l'entreprise (K9, `core.acces.peut_modifier_clients`). Chaque écran a
Enregistrer et Annuler (K10). Les règles restent celles du modèle (téléphones en E.164, courriel nettoyé,
code postal, même entreprise); une adresse nouvelle ou déplacée est géocodée par le worker.
"""
from django import forms
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from clients.models import Adresse, Client, Contact, PhotoAdresse, Secteur
from core.acces import ecriture_requise, membre_requis, modification_clients_requise
from core.telephone import afficher
from terrain.retour import retour_ou

CHAMP = "champ"


def _attrs(**kw):
    return {"class": CHAMP, **kw}


class GroupesMixin:
    """Mode court (audit UX) : l'essentiel d'abord, le reste replié sous « Plus de détails ».
    GROUPES : [(titre du repli ou None, [champs])]; un repli s'ouvre s'il contient une erreur ou une valeur."""
    GROUPES = None

    def _defaut(self, nom):
        """Valeur par défaut du modèle : une case cochée par défaut (ex. avis pendant les opérations) n'ouvre pas le repli."""
        try:
            d = self._meta.model._meta.get_field(nom).default
        except Exception:
            return None
        return d if isinstance(d, (bool, int, str)) else None

    def groupes(self):
        if not self.GROUPES:
            return [(None, list(self), True)]
        sortie, vus = [], {n for _, noms in self.GROUPES for n in noms}
        groupes = list(self.GROUPES)
        restants = [n for n in self.fields if n not in vus]
        if restants:  # un champ ajouté au formulaire sans être classé : dans le dernier repli, jamais perdu
            groupes[-1] = (groupes[-1][0], list(groupes[-1][1]) + restants)
        for titre, noms in groupes:
            champs = [self[n] for n in noms if n in self.fields]
            rempli = any(c.errors or (self.instance.pk and c.value() not in (None, "", False, self._defaut(c.name))) for c in champs)
            sortie.append((titre, champs, titre is None or rempli))
        return sortie


class ClientForm(GroupesMixin, forms.ModelForm):
    GROUPES = [
        (None, ["prenom", "nom", "cellulaire"]),
        ("Plus de détails : courriel, autre numéro, paiement, statut, notes",
         ["organisation", "courriel", "telephone_autre", "canal_prefere", "mode_paiement", "statut", "notes", "ne_pas_relancer",
          "avis_operations", "proprietaire_non_occupant"]),
        ("Adresse de facturation différente de l'adresse de service",
         ["facturation_ligne1", "facturation_ligne2", "facturation_ville", "facturation_code_postal"]),
    ]

    class Meta:
        model = Client
        fields = ["prenom", "nom", "organisation", "cellulaire", "telephone_autre", "courriel", "canal_prefere",
                  "mode_paiement", "statut", "facturation_ligne1", "facturation_ligne2", "facturation_ville",
                  "facturation_code_postal", "notes", "ne_pas_relancer", "avis_operations", "proprietaire_non_occupant"]
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
            "ne_pas_relancer": forms.CheckboxInput(attrs={"class": "h-6 w-6 accent-[#f5c400]"}),
            "avis_operations": forms.CheckboxInput(attrs={"class": "h-6 w-6 accent-[#f5c400]"}),
            "proprietaire_non_occupant": forms.CheckboxInput(attrs={"class": "h-6 w-6 accent-[#f5c400]"}),
        }
        help_texts = {"ne_pas_relancer": "", "avis_operations": "", "proprietaire_non_occupant": ""}
        labels = {"avis_operations": "Recevoir les avis pendant les opérations (début, proximité, c'est fait)",
                  "proprietaire_non_occupant": "Propriétaire non occupant : avis aux locataires seulement (factures au propriétaire)"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for champ in ("cellulaire", "telephone_autre"):  # 450 555-0100 plutôt que +14505550100
            if self.instance.pk and not self.is_bound:
                self.initial[champ] = afficher(getattr(self.instance, champ))


class AdresseForm(GroupesMixin, forms.ModelForm):
    GROUPES = [
        # Adresse complète toujours visible : suite et code postal avec la rue (demande de Louis, 12 novembre 2026)
        (None, ["ligne1", "ligne2", "ville", "code_postal", "secteur"]),
        ("Plus de détails : terrain, consignes",
         ["ou_mettre_neige", "obstacles", "borne_fontaine", "entree_en_pente", "consignes", "active"]),
    ]

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


class ContactForm(GroupesMixin, forms.ModelForm):
    class Meta:
        model = Contact
        fields = ["nom", "role", "cellulaire", "courriel", "note"]
        widgets = {
            "nom": forms.TextInput(attrs=_attrs(autocomplete="off", autocapitalize="words")),
            "role": forms.Select(attrs=_attrs()),
            "cellulaire": forms.TextInput(attrs=_attrs(type="tel", inputmode="tel", autocomplete="off", placeholder="450 555-0100")),
            "courriel": forms.EmailInput(attrs=_attrs(inputmode="email", autocomplete="off", autocapitalize="none")),
            "note": forms.TextInput(attrs=_attrs()),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk and not self.is_bound:
            self.initial["cellulaire"] = afficher(self.instance.cellulaire)


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
    from terrain import contrats

    fc = ClientForm(request.POST or None, instance=Client(entreprise=ent), prefix="c")
    fa = AdresseForm(request.POST or None, instance=Adresse(entreprise=ent), prefix="a", entreprise=ent)
    erreurs_contrat = []
    if request.method == "POST":
        with transaction.atomic():
            client = _enregistrer(fc, entreprise=ent)
            adresse = _enregistrer(fa, entreprise=ent, client=client) if client else None
            if client and adresse:
                # Contrat de la saison, son échéancier et sa facture (lot E) : tout ou rien avec le client
                facture, erreurs_contrat = contrats.contrat_rapide(request, client, adresse)
                if not erreurs_contrat:
                    if facture is not None:
                        messages.success(request, f"Client ajouté : {client.nom_affiche}, avec son contrat. Sa facture de la saison "
                                                  "est prête : « Émettre et envoyer ».")
                        return redirect("terrain:facture", pk=facture.pk)
                    messages.success(request, f"Client ajouté : {client.nom_affiche}.")
                    return redirect("terrain:fiche", pk=client.pk)
            transaction.set_rollback(True)
    return render(request, "terrain/clients/formulaire.html", {
        "titre": "Nouveau client", "formulaires": [("Client", fc), ("Adresse de service", fa)], "annuler": "terrain:accueil",
        "contrat_rapide": contrats.contexte_contrat_rapide(request), "erreurs_contrat": erreurs_contrat,
    })


@modification_clients_requise
def modifier(request, pk):
    client = get_object_or_404(Client, pk=pk, entreprise=request.entreprise)
    form = ClientForm(request.POST or None, instance=client, prefix="c")
    if request.method == "POST" and _enregistrer(form):
        messages.success(request, "Client enregistré.")
        return retour_ou(request, "terrain:fiche", pk=client.pk)
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
        return retour_ou(request, "terrain:fiche", pk=client.pk)
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
        return retour_ou(request, "terrain:fiche", pk=a.client_id)
    if a.position:
        centre, zoom = (a.position.y, a.position.x), 18
    else:
        ville = VilleDesservie.pour(a.entreprise_id, a.ville) or VilleDesservie.objects.filter(entreprise=a.entreprise_id).first()
        centre, zoom = ((ville.centre.y, ville.centre.x) if ville and ville.centre else (45.95, -74.13)), 14
    return render(request, "terrain/clients/position.html", {"a": a, "lat": centre[0], "lng": centre[1], "zoom": zoom})


@ecriture_requise
def ecrire(request, pk):
    """Écrire à un client (E2, E3) : texto ou courriel, depuis le numéro et l'adresse d'affaires; signature ajoutée.
    Photos jointes (E14) : en pièces jointes par courriel, par un lien secret par texto."""
    from django.core.exceptions import ValidationError

    from communications import envoi, photos, segments
    from communications.models import Genre, Message
    from demandes.models import Demande

    client = get_object_or_404(Client, pk=pk, entreprise=request.entreprise)
    ent = request.entreprise
    demande = Demande.objects.filter(pk=request.GET.get("demande") or 0, client=client).first() if request.GET.get("demande", "").isdigit() else None
    disponibles = photos.disponibles(client, demande)
    # « Répondre » depuis un message reçu : même canal, message cité au-dessus, même fil de courriel
    reponse_a = Message.objects.filter(pk=request.GET.get("reponse") or request.POST.get("reponse") or 0, client=client).first() \
        if (request.GET.get("reponse") or request.POST.get("reponse") or "").isdigit() else None
    canaux = [(Message.Canal.TEXTO, f"Texto au {afficher(client.cellulaire)}")] if client.cellulaire else []
    if client.courriel:
        canaux.append((Message.Canal.COURRIEL, f"Courriel à {client.courriel}"))
    if request.method == "POST":
        canal, texte = request.POST.get("canal"), request.POST.get("texte", "").strip()
        sujet = request.POST.get("sujet", "").strip()[:200]
        choisies = request.POST.getlist("photo")
        for d in disponibles:
            d["choisie"] = d["cle"] in choisies
        if canal not in dict(canaux) or not texte:
            messages.error(request, "Choisir le texto ou le courriel, et écrire le message.")
        elif len(set(choisies)) > photos.MAXIMUM:
            messages.error(request, f"Au plus {photos.MAXIMUM} photos par message.")
        else:
            courriel = canal == Message.Canal.COURRIEL
            signature = ent.signature_messages or ent.nom
            try:
                with transaction.atomic():
                    m = Message.objects.create(entreprise=ent, client=client, genre=Genre.MANUEL, canal=canal, reponse_a=reponse_a,
                                               destinataire=client.courriel if courriel else client.cellulaire,
                                               sujet=(sujet or f"Message de {ent.nom}") if courriel else "",
                                               contenu=f"{texte}\n\n{signature}")
                    n = photos.joindre(m, choisies)
                    if n and not courriel:
                        m.contenu = f"{texte}\nPhoto{'s' if n > 1 else ''} : {photos.lien_public(m)}\n\n{signature}"
                        m.save(update_fields=["contenu"])
                    if not courriel and segments.trop_long(m.contenu):
                        raise ValidationError(f"Texto trop long : {segments.longueur(m.contenu)} caractères avec la signature"
                                              f"{' et le lien des photos' if n else ''} ({segments.LIMITE} au plus). "
                                              f"Enlevez {segments.longueur(m.contenu) - segments.LIMITE} caractères.")
            except ValidationError as e:
                messages.error(request, " ".join(e.messages))
            else:
                envoi.envoyer(m)
                if m.statut == Message.Statut.EN_FILE:
                    messages.success(request, f"Message en route vers {m.destinataire}.")
                else:
                    messages.error(request, f"Message pas envoyé : {m.erreur}")
                return retour_ou(request, "terrain:fiche", pk=client.pk)
    return render(request, "terrain/clients/ecrire.html", {
        "client": client, "canaux": canaux, "signature": ent.signature_messages or ent.nom,
        "choisi": request.POST.get("canal") or (reponse_a.canal if reponse_a and reponse_a.canal in dict(canaux) else None)
                   or (client.canal_prefere if client.canal_prefere in dict(canaux) else (canaux[0][0] if canaux else "")),
        "reponse_a": reponse_a,
        "sujet": request.POST.get("sujet") or (("" if (reponse_a.sujet or "").lower().startswith("re:") else "Re: ") + reponse_a.sujet if reponse_a and reponse_a.sujet else ""),
        "photos": disponibles, "maximum": photos.MAXIMUM, "texte": request.POST.get("texte", ""),
        # Compteur du texto : ce qui reste pour le message, une fois la signature (et le lien des photos) comptée
        "photos_choisies": sum(1 for d in disponibles if d["choisie"]), "limite": segments.LIMITE, "reserve_signature": segments.longueur(f"\n\n{ent.signature_messages or ent.nom}"),
        "reserve_photos": segments.longueur(f"\nPhotos : https://{ent.domaine}/m/{'x' * 32}/"),
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
            return retour_ou(request, "terrain:fiche", pk=client.pk)
    return render(request, "terrain/clients/appel.html", {"client": client, "sens": request.POST.get("sens", "recu"),
                                                          "resume": request.POST.get("resume", "")})


# Photo de l'entrée (A5)

@require_POST
@ecriture_requise
def ajouter_photo(request, pk):
    a = get_object_or_404(Adresse, pk=pk, entreprise=request.entreprise)
    f = request.FILES.get("photo")
    if f is None:
        messages.error(request, "Aucune photo reçue.")
    elif f.size > PhotoAdresse.MAX_OCTETS:
        messages.error(request, "Photo trop lourde (plus de 8 Mo).")
    else:
        octets = f.read()
        mime = PhotoAdresse.type_de(octets[:16])
        if mime is None:
            messages.error(request, "Ce fichier n'est pas une photo (JPEG, PNG, WebP ou HEIC).")
        else:
            PhotoAdresse.objects.create(entreprise=request.entreprise, adresse=a, image=octets, type_mime=mime,
                                        taille=len(octets), prise_par=request.user)
            messages.success(request, "Photo ajoutée.")
    return redirect("terrain:fiche", pk=a.client_id)


@membre_requis
def photo(request, pk):
    p = get_object_or_404(PhotoAdresse, pk=pk, entreprise=request.entreprise)
    r = HttpResponse(bytes(p.image), content_type=p.type_mime)
    r["Cache-Control"] = "private, max-age=604800, immutable"  # une photo ne change jamais
    r["X-Content-Type-Options"] = "nosniff"
    return r


@require_POST
@ecriture_requise
def retirer_photo(request, pk):
    p = get_object_or_404(PhotoAdresse.objects.select_related("adresse"), pk=pk, entreprise=request.entreprise)
    client_id = p.adresse.client_id
    p.delete()
    messages.success(request, "Photo retirée.")
    return redirect("terrain:fiche", pk=client_id)


# Autres personnes à joindre (A3)

@modification_clients_requise
def contact(request, client_pk, pk=None):
    ent = request.entreprise
    client = get_object_or_404(Client, pk=client_pk, entreprise=ent)
    instance = get_object_or_404(Contact, pk=pk, client=client) if pk else Contact(entreprise=ent, client=client)
    form = ContactForm(request.POST or None, instance=instance, prefix="k")
    if request.method == "POST" and _enregistrer(form, entreprise=ent, client=client):
        messages.success(request, "Contact enregistré.")
        return retour_ou(request, "terrain:fiche", pk=client.pk)
    return render(request, "terrain/clients/formulaire.html", {
        "titre": ("Modifier le contact" if pk else "Nouveau contact") + f" : {client.nom_affiche}",
        "formulaires": [("Contact", form)], "annuler_url": client.pk,
        "retirer_url": reverse("terrain:retirer_contact", args=[client.pk, pk]) if pk else "",
        "retirer_libelle": "Retirer ce contact", "retirer_question": "Retirer ce contact de la fiche?",
    })


@require_POST
@modification_clients_requise
def retirer_contact(request, client_pk, pk):
    k = get_object_or_404(Contact, pk=pk, client_id=client_pk, entreprise=request.entreprise)
    k.delete()
    messages.success(request, "Contact retiré.")
    return redirect("terrain:fiche", pk=client_pk)
