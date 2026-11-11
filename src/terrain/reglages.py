"""Réglages du déneigeur dans l'app (Plus, « Réglages ») : ce qu'il gère lui-même, sans l'administration.

Décision de JF (10 novembre 2026) : le déneigeur règle sa fiche (coordonnées, taxes, Interac, versements, avis,
relances), ses secteurs, ses services, ses saisons, ses villes desservies et ses utilisateurs. Restent à la
plateforme (administration de JF) : identifiant, domaine, mode seul ou équipe, envois réels, numéro Twilio,
adresse d'envoi des courriels, prochain numéro de facture et taux des taxes (affichés ici, pas modifiables).

Qui : un administrateur de l'entreprise (ou JF); les autres membres consultent sans rien changer.
Tout passe par le journal des actions (signaux de core.journal).
"""
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.http import require_POST

from clients.models import Adresse, Secteur
from core.acces import est_responsable, membre_requis
from core.models import Entreprise, Membre, VilleDesservie
from core.telephone import afficher, normaliser
from core.texte import cle_ville
from facturation.models import Saison, Service
from terrain.argent import MontantField

CASE = {"class": "h-6 w-6 accent-[#f5c400]"}

# Sections de la fiche de l'entreprise : (titre, champs, explication)
SECTIONS = {
    "entreprise": ("Mon entreprise",
                   ["nom", "nom_legal", "telephone", "courriel", "adresse_ligne1", "adresse_ligne2", "ville", "province",
                    "code_postal", "signature_messages"],
                   "Ce que voient les clients sur les factures, les contrats et à la fin des textos."),
    "factures": ("Factures et taxes", ["inscrit_taxes", "numero_tps", "numero_tvq", "interac_courriel", "interac_instructions"],
                 "Taxes et façon de payer, imprimées sur chaque facture."),
    "versements": ("Versements des contrats", ["versements_par_defaut", "dates_versements", "jours_avance_versement"],
                   "Échéancier proposé pour un nouveau contrat saisonnier, et préparation des factures de versement."),
    "avis": ("Avis aux clients pendant la tournée", ["avis_proximite_actif", "avis_rayon_m", "minutes_par_arret", "avis_passage_fait"],
             "Textos envoyés pendant une opération."),
    "relances": ("Relances proposées", ["relances_proposees", "relances_soldes_anterieurs"],
                 "Liste des clients à relancer, préparée les jours de semaine. Rien ne part sans une tape."),
}


SIGNATURE_MAX = 40  # la signature compte dans les 201 caractères d'un texto (communications.segments.LIMITE)


def _signature_courte(form):
    from django.core.validators import MaxLengthValidator

    champ = form.fields.get("signature_messages")
    if champ:
        champ.validators.append(MaxLengthValidator(SIGNATURE_MAX))
        champ.widget.attrs["maxlength"] = SIGNATURE_MAX
        champ.help_text = (f"À la fin des textos et des courriels (loi anti-pourriel), {SIGNATURE_MAX} caractères au plus : "
                           "elle compte dans les 201 caractères d'un texto. Ex. « Louis Méthot Déneigement ».")
    return form


def _refus(request):
    return render(request, "terrain/refuse.html", {"message": "Seul un administrateur de l'entreprise change les réglages."}, status=403)


def _habiller(form):
    for champ in form.fields.values():
        if isinstance(champ.widget, forms.CheckboxInput):
            champ.widget.attrs.update(CASE)
        else:
            champ.widget.attrs.setdefault("class", "champ")
        if isinstance(champ.widget, forms.Textarea):
            champ.widget.attrs.setdefault("rows", 3)
    return form


class UniqueParEntreprise:
    """Le nom est unique par entreprise (contrainte en base) : vérifié ici, l'entreprise n'étant pas dans le formulaire."""

    def __init__(self, *args, entreprise=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.entreprise = entreprise
        _habiller(self)

    def clean_nom(self):
        nom = " ".join((self.cleaned_data.get("nom") or "").split())
        autres = self._meta.model.objects.filter(entreprise=self.entreprise, nom__iexact=nom).exclude(pk=self.instance.pk)
        if autres.exists():
            raise forms.ValidationError("Ce nom existe déjà.")
        return nom


class SecteurForm(UniqueParEntreprise, forms.ModelForm):
    class Meta:
        model = Secteur
        fields = ["nom", "actif"]
        help_texts = {"actif": "Décoché : ne paraît plus dans les choix d'une adresse."}


class ServiceForm(UniqueParEntreprise, forms.ModelForm):
    class Meta:
        model = Service
        fields = ["nom", "prix_suggere", "taxable", "actif", "ordre"]
        field_classes = {"prix_suggere": MontantField}
        widgets = {"prix_suggere": forms.TextInput(attrs={"inputmode": "decimal"}), "ordre": forms.NumberInput(attrs={"inputmode": "numeric"})}
        help_texts = {"ordre": "Ordre des boutons sur la facture (le plus petit d'abord).", "actif": "Décoché : n'est plus proposé sur les factures."}


class SaisonForm(UniqueParEntreprise, forms.ModelForm):
    class Meta:
        model = Saison
        fields = ["nom", "debut", "fin"]
        widgets = {"debut": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
                   "fin": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}


class VilleForm(UniqueParEntreprise, forms.ModelForm):
    class Meta:
        model = VilleDesservie
        fields = ["nom", "rayon_km"]
        field_classes = {"rayon_km": MontantField}
        widgets = {"rayon_km": forms.TextInput(attrs={"inputmode": "decimal"})}

    def clean_nom(self):
        nom = super().clean_nom()
        if any(cle_ville(v.nom) == cle_ville(nom) for v in VilleDesservie.objects.filter(entreprise=self.entreprise).exclude(pk=self.instance.pk)):
            raise forms.ValidationError("Cette ville est déjà desservie.")
        return nom


class InvitationForm(forms.Form):
    prenom = forms.CharField(label="Prénom", max_length=150)
    nom = forms.CharField(label="Nom", max_length=150, required=False)
    cellulaire = forms.CharField(label="Cellulaire", max_length=20, widget=forms.TextInput(attrs={"type": "tel", "inputmode": "tel", "placeholder": "450 555-0100"}))
    role = forms.ChoiceField(label="Rôle", choices=Membre.Role.choices, initial=Membre.Role.OPERATEUR,
                             help_text="Administrateur : tout, réglages compris. Opérateur : la tournée, les clients et l'argent. "
                                       "Lecture seule : consulte, ne change rien.")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _habiller(self)

    def clean_cellulaire(self):
        try:
            return normaliser(self.cleaned_data["cellulaire"])
        except Exception:
            raise forms.ValidationError("Numéro de cellulaire invalide.")


def _virgule(champ, **kwargs):
    """Les nombres décimaux de la fiche acceptent la virgule (« 2,5 »), comme partout dans l'app."""
    from django.db import models

    if isinstance(champ, models.DecimalField):
        kwargs["form_class"] = MontantField
    return champ.formfield(**kwargs)


def _operation(entreprise):
    from tournee.models import Operation

    return Operation.objects.filter(entreprise=entreprise, fin=None).first()


def _contexte(request, **extra):
    """Pendant une opération (décision de JF, 10 novembre 2026) : rien n'est bloqué au bureau, sauf l'accès de la
    personne en tournée; la personne en tournée confirme chaque enregistrement (gaffe sur la route)."""
    op = _operation(request.entreprise)
    return {"peut": est_responsable(request), "operation": op,
            "en_tournee": bool(op and op.operateur_id == request.user.pk), **extra}


@membre_requis
def accueil(request):
    ent = request.entreprise
    return render(request, "terrain/reglages/accueil.html", _contexte(
        request, sections=[(cle, titre) for cle, (titre, _, _) in SECTIONS.items()],
        nb_secteurs=Secteur.objects.filter(entreprise=ent, actif=True).count(),
        nb_services=Service.objects.filter(entreprise=ent, actif=True).count(),
        saison=Saison.objects.filter(entreprise=ent).order_by("-debut").first(),
        villes=list(VilleDesservie.objects.filter(entreprise=ent).values_list("nom", flat=True)),
        nb_membres=Membre.objects.filter(entreprise=ent).count(), ent=ent,
        numero_texto=afficher(ent.numero_texto) if ent.numero_texto else ""))


@membre_requis
def section(request, cle):
    if cle not in SECTIONS:
        return render(request, "terrain/refuse.html", {"message": "Section inconnue."}, status=404)
    titre, champs, explication = SECTIONS[cle]
    ent = request.entreprise
    Form = forms.modelform_factory(Entreprise, fields=champs, formfield_callback=_virgule)
    if request.method == "POST":
        if not est_responsable(request):
            return _refus(request)
        form = _signature_courte(_habiller(Form(request.POST, instance=ent)))
        if form.is_valid():
            form.save()
            messages.success(request, f"{titre} : enregistré.")
            return redirect("terrain:reglages")
    else:
        form = _signature_courte(_habiller(Form(instance=ent)))
    return render(request, "terrain/reglages/section.html", _contexte(request, titre=titre, explication=explication, form=form, cle=cle, ent=ent))


def _formulaire(request, Form, modele, pk, titre_nouveau, titre_modifier, retour, apres=None):
    """Ajout ou modification d'un élément (secteur, service, saison, ville) de l'entreprise du domaine."""
    ent = request.entreprise
    instance = get_object_or_404(modele, pk=pk, entreprise=ent) if pk else modele(entreprise=ent)
    if request.method == "POST":
        if not est_responsable(request):
            return _refus(request)
        form = Form(request.POST, instance=instance, entreprise=ent)
        if form.is_valid():
            nouveau = instance.pk is None
            obj = form.save()
            if apres:
                apres(request, obj, nouveau)
            messages.success(request, f"« {obj} » enregistré.")
            return redirect(retour)
    else:
        form = Form(instance=instance, entreprise=ent)
    return render(request, "terrain/reglages/formulaire.html", _contexte(
        request, titre=titre_modifier if pk else titre_nouveau, form=form, retour=retour, objet=instance if pk else None))


# Secteurs ------------------------------------------------------------------------------------------------------

@membre_requis
def secteurs(request):
    qs = Secteur.objects.filter(entreprise=request.entreprise).annotate(
        nb=Count("adresses", filter=Q(adresses__active=True))).order_by("ordre", "nom")
    return render(request, "terrain/reglages/secteurs.html", _contexte(request, secteurs=qs))


def _ordre_nouveau_secteur(request, obj, nouveau):
    if nouveau:  # à la fin de la tournée
        dernier = Secteur.objects.filter(entreprise=obj.entreprise).exclude(pk=obj.pk).aggregate(m=Max("ordre"))["m"] or 0
        obj.ordre = dernier + 10
        obj.save(update_fields=["ordre", "modifie_le"])


@membre_requis
def secteur(request, pk=None):
    return _formulaire(request, SecteurForm, Secteur, pk, "Nouveau secteur", "Modifier le secteur", "terrain:reglages_secteurs",
                       apres=_ordre_nouveau_secteur)


@require_POST
@membre_requis
def retirer_secteur(request, pk):
    if not est_responsable(request):
        return _refus(request)
    s = get_object_or_404(Secteur, pk=pk, entreprise=request.entreprise)
    if Adresse.objects.filter(secteur=s).exists():
        messages.error(request, f"« {s} » a encore des adresses : les changer de secteur d'abord, ou le décocher « actif ».")
    else:
        s.delete()
        messages.success(request, f"Secteur « {s} » retiré.")
    return redirect("terrain:reglages_secteurs")


# Services ------------------------------------------------------------------------------------------------------

@membre_requis
def services(request):
    return render(request, "terrain/reglages/services.html", _contexte(
        request, services=Service.objects.filter(entreprise=request.entreprise).order_by("-actif", "ordre", "nom")))


@membre_requis
def service(request, pk=None):
    return _formulaire(request, ServiceForm, Service, pk, "Nouveau service", "Modifier le service", "terrain:reglages_services")


# Saisons -------------------------------------------------------------------------------------------------------

@membre_requis
def saisons(request):
    return render(request, "terrain/reglages/saisons.html", _contexte(
        request, saisons=Saison.objects.filter(entreprise=request.entreprise).annotate(nb=Count("contrats")).order_by("-debut")))


@membre_requis
def saison(request, pk=None):
    return _formulaire(request, SaisonForm, Saison, pk, "Nouvelle saison", "Modifier la saison", "terrain:reglages_saisons")


# Villes desservies ---------------------------------------------------------------------------------------------

def _trouver_centre(request, ville, nouveau):
    """Le centre de la ville est cherché par le worker (l'app n'a pas Internet), puis ses adresses sont regéocodées."""
    from core.tasks import centre_ville_desservie

    if nouveau or ville.centre is None:
        centre_ville_desservie.defer(ville_id=ville.pk)
        messages.info(request, f"Le centre de {ville} sera trouvé dans une minute, puis ses adresses replacées.")


@membre_requis
def villes(request):
    return render(request, "terrain/reglages/villes.html", _contexte(
        request, villes=VilleDesservie.objects.filter(entreprise=request.entreprise).order_by("-par_defaut", "nom")))


@membre_requis
def ville(request, pk=None):
    return _formulaire(request, VilleForm, VilleDesservie, pk, "Nouvelle ville desservie", "Modifier la ville", "terrain:reglages_villes",
                       apres=_trouver_centre)


@require_POST
@membre_requis
def retirer_ville(request, pk):
    if not est_responsable(request):
        return _refus(request)
    v = get_object_or_404(VilleDesservie, pk=pk, entreprise=request.entreprise)
    if v.par_defaut:
        messages.error(request, "La ville par défaut ne se retire pas.")
    else:
        v.delete()
        messages.success(request, f"{v} n'est plus desservie. Ses adresses gardent leur position.")
    return redirect("terrain:reglages_villes")


# Utilisateurs --------------------------------------------------------------------------------------------------

def _nom_utilisateur(prenom, nom):
    from django.utils.text import slugify

    User = get_user_model()
    base = slugify(prenom).replace("-", "")[:20] or "membre"
    choix = [base, base + slugify(nom[:1])] if nom else [base]
    for c in choix:
        if not User.objects.filter(username__iexact=c).exists():
            return c
    i = 2
    while User.objects.filter(username__iexact=f"{base}{i}").exists():
        i += 1
    return f"{base}{i}"


def lien_invitation(entreprise, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return f"https://{entreprise.domaine}/invitation/{uid}/{default_token_generator.make_token(user)}/"


def _envoyer_invitation(request, membre, cellulaire=""):
    """Texto avec le lien pour choisir le mot de passe (3 jours). Le lien est aussi montré à l'écran : si les envois
    réels sont éteints, l'administrateur le donne lui-même."""
    from communications.envoi import envoyer
    from communications.models import Genre, Message

    ent, user = request.entreprise, membre.utilisateur
    lien = lien_invitation(ent, user)
    if cellulaire:
        m = Message.objects.create(
            entreprise=ent, genre=Genre.MANUEL, canal=Message.Canal.TEXTO, destinataire=cellulaire,
            contenu=f"{ent.nom} : ton compte dans l'app est prêt (utilisateur : {user.username}). "
                    f"Choisis ton mot de passe d'ici 3 jours : {lien}")
        envoyer(m)
    request.session["invitation"] = {"membre": membre.pk, "lien": lien}


@membre_requis
def utilisateurs(request):
    ent = request.entreprise
    if request.method == "POST":
        if not est_responsable(request):
            return _refus(request)
        form = InvitationForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            User = get_user_model()
            with transaction.atomic():
                user = User(username=_nom_utilisateur(d["prenom"], d["nom"]), first_name=d["prenom"], last_name=d["nom"])
                user.set_unusable_password()
                user.save()
                membre = Membre.objects.create(utilisateur=user, entreprise=ent, role=d["role"])
            _envoyer_invitation(request, membre, d["cellulaire"])
            messages.success(request, f"Compte créé pour {d['prenom']} (nom d'utilisateur : {user.username}). Invitation envoyée au {afficher(d['cellulaire'])}.")
            return redirect("terrain:reglages_utilisateurs")
    else:
        form = InvitationForm()
    invitation = request.session.pop("invitation", None)
    membres = Membre.objects.filter(entreprise=ent).select_related("utilisateur").order_by("utilisateur__first_name", "utilisateur__username")
    return render(request, "terrain/reglages/utilisateurs.html", _contexte(
        request, form=form, membres=membres, invitation=invitation, moi=request.user, roles=Membre.Role.choices))


@require_POST
@membre_requis
def utilisateur(request, pk):
    """Changer le rôle, renvoyer l'invitation ou retirer l'accès d'un membre (jamais soi-même)."""
    if not est_responsable(request):
        return _refus(request)
    membre = get_object_or_404(Membre, pk=pk, entreprise=request.entreprise)
    user = membre.utilisateur
    if user == request.user:
        messages.error(request, "Tu ne peux pas changer ton propre accès.")
        return redirect("terrain:reglages_utilisateurs")
    action = request.POST.get("action")
    op = _operation(request.entreprise)
    if action in ("role", "retirer") and op and op.operateur_id == user.pk:
        messages.error(request, "En tournée en ce moment : possible après la fin de l'opération.")
        return redirect("terrain:reglages_utilisateurs")
    if action == "role" and request.POST.get("role") in Membre.Role.values:
        membre.role = request.POST["role"]
        membre.save(update_fields=["role", "modifie_le"])
        messages.success(request, f"{user.get_full_name() or user.username} : {membre.get_role_display().lower()}.")
    elif action == "inviter" and not user.has_usable_password():
        try:
            cell = normaliser(request.POST.get("cellulaire", "")) if request.POST.get("cellulaire") else ""
        except Exception:
            cell = ""
        _envoyer_invitation(request, membre, cell)
        messages.success(request, "Nouveau lien d'invitation" + (f" envoyé au {afficher(cell)}." if cell else " (à donner toi-même)."))
    elif action == "retirer":
        with transaction.atomic():
            membre.delete()
            if not user.is_staff and not Membre.objects.filter(utilisateur=user).exists():
                user.set_unusable_password()  # ferme aussi ses sessions ouvertes
                user.is_active = False
                user.save(update_fields=["password", "is_active"])
        messages.success(request, f"Accès retiré à {user.get_full_name() or user.username}.")
    return redirect("terrain:reglages_utilisateurs")


def invitation(request, uidb64, jeton):
    """Page publique du lien d'invitation : choisir son mot de passe, puis entrer dans l'app.
    Le jeton de Django ne sert qu'une fois (il dépend du mot de passe) et expire après PASSWORD_RESET_TIMEOUT (3 jours)."""
    User = get_user_model()
    try:
        user = User.objects.get(pk=urlsafe_base64_decode(uidb64).decode(), is_active=True)
    except (User.DoesNotExist, ValueError, TypeError, OverflowError):
        user = None
    valide = (user is not None and request.entreprise is not None and default_token_generator.check_token(user, jeton)
              and Membre.objects.filter(utilisateur=user, entreprise=request.entreprise).exists())
    if not valide:
        return render(request, "terrain/reglages/invitation.html", {"expire": True}, status=404)
    form = SetPasswordForm(user, request.POST or None)
    _habiller(form)
    if request.method == "POST" and form.is_valid():
        form.save()
        login(request, user, backend="core.connexions.AuthentificationLimitee")
        messages.success(request, f"Bienvenue, {user.first_name or user.username}.")
        return redirect("terrain:accueil")
    return render(request, "terrain/reglages/invitation.html", {"form": form, "utilisateur": user})


# Mon abonnement (PRD Q2) : ce que la plateforme compte et facture, pour les administrateurs de l'entreprise

@membre_requis
def abonnement(request):
    from core import abonnement as ab
    from core.models import FacturePlateforme

    if not est_responsable(request):
        return _refus(request)
    ent = request.entreprise
    premier = ab.debut_du_mois(timezone.localdate())
    factures = {f.mois: f for f in FacturePlateforme.objects.filter(entreprise=ent).exclude(
        statut__in=[FacturePlateforme.Statut.BROUILLON, FacturePlateforme.Statut.ANNULEE])}
    mois, m = [], premier
    for _ in range(6):
        m = ab.mois_precedent(m)
        mois.append({"mois": m, "usage": ab.usage(ent, m), "facture": factures.get(m)})
    return render(request, "terrain/reglages/abonnement.html", _contexte(
        request, ent=ent, courant=ab.estimation(ent, premier), premier=premier, mois=mois, facture=ent.abonnement_facture,
        factures=sorted(factures.values(), key=lambda f: f.mois, reverse=True)))


@membre_requis
def facture_plateforme_pdf(request, pk):
    from django.http import HttpResponse

    from core import abonnement as ab
    from core.models import FacturePlateforme

    if not est_responsable(request):
        return _refus(request)
    f = get_object_or_404(FacturePlateforme.objects.exclude(statut=FacturePlateforme.Statut.BROUILLON), pk=pk, entreprise=request.entreprise)
    r = HttpResponse(ab.pdf(f), content_type="application/pdf")
    r["Content-Disposition"] = f'inline; filename="facture-le-deneigeur-{f.numero}.pdf"'
    return r
