"""Clients, adresses de service et secteurs (PRD section 5 A, F2, K6).

Un client (le payeur) peut avoir plusieurs adresses de service (A4, V2) : le
modèle le permet dès maintenant, même si l'interface V1 n'en montre qu'une.
"""
from django.contrib.gis.db import models as gis
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from core import telephone
from core.models import Entreprise, Horodate


def _code_postal(valeur):
    v = (valeur or "").upper().replace(" ", "")
    return f"{v[:3]} {v[3:]}" if len(v) == 6 else v


class Secteur(Horodate):
    """Regroupement de clients par secteur ou par route (F2)."""

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="secteurs")
    nom = models.CharField(max_length=100)
    ordre = models.PositiveIntegerField("ordre dans la tournée", default=0)
    actif = models.BooleanField(default=True)

    class Meta:
        verbose_name = "secteur"
        verbose_name_plural = "secteurs"
        ordering = ["entreprise", "ordre", "nom"]
        constraints = [
            models.UniqueConstraint(fields=["entreprise", "nom"], name="secteur_nom_unique_par_entreprise"),
        ]

    def __str__(self):
        return self.nom


class Client(Horodate):
    class Statut(models.TextChoices):
        ACTIF = "actif", "Actif"
        INACTIF = "inactif", "Inactif"
        RECOUVREMENT = "recouvrement", "En recouvrement"
        LISTE_NOIRE = "liste_noire", "Liste noire"

    class Canal(models.TextChoices):
        TEXTO = "texto", "Texto"
        COURRIEL = "courriel", "Courriel"
        LES_DEUX = "les_deux", "Texto et courriel"

    class Langue(models.TextChoices):
        FR = "fr", "Français"
        EN = "en", "Anglais"

    class ModePaiement(models.TextChoices):
        INTERAC = "interac", "Virement Interac"
        COMPTANT = "comptant", "Comptant"
        CARTE = "carte", "Carte de crédit"
        CHEQUE = "cheque", "Chèque"

    class SourceConsentement(models.TextChoices):
        IMPORT = "import", "Noté à l'import (papiers de Louis)"
        VERBAL = "verbal", "Verbal"
        ECRIT = "ecrit", "Écrit (texto, courriel, formulaire)"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="clients")

    # Identité (A1). Un client commercial a un nom d'organisation (question 12 du PRD).
    prenom = models.CharField("prénom", max_length=100, blank=True)
    nom = models.CharField(max_length=100, blank=True)
    organisation = models.CharField("organisation", max_length=150, blank=True, help_text="Pour un client commercial : entreprise, syndicat de copropriété, etc.")

    # Coordonnées (A1). Téléphones normalisés au format +1XXXXXXXXXX.
    cellulaire = models.CharField(max_length=16, blank=True, db_index=True, help_text="Sert aux textos et à rattacher les textos reçus.")
    telephone_autre = models.CharField("autre téléphone", max_length=16, blank=True)
    courriel = models.EmailField(blank=True, db_index=True)

    # Adresse de facturation, seulement si différente de l'adresse de service (A1)
    facturation_ligne1 = models.CharField("adresse de facturation", max_length=200, blank=True)
    facturation_ligne2 = models.CharField("adresse de facturation (suite)", max_length=200, blank=True)
    facturation_ville = models.CharField("ville de facturation", max_length=100, blank=True)
    facturation_province = models.CharField("province de facturation", max_length=2, blank=True)
    facturation_code_postal = models.CharField("code postal de facturation", max_length=7, blank=True)

    # Préférences (A6, D1)
    canal_prefere = models.CharField("canal préféré", max_length=10, choices=Canal.choices, default=Canal.TEXTO)
    langue = models.CharField(max_length=2, choices=Langue.choices, default=Langue.FR)
    mode_paiement = models.CharField("mode de paiement préféré", max_length=10, choices=ModePaiement.choices, blank=True)

    # Statut (A7)
    statut = models.CharField(max_length=15, choices=Statut.choices, default=Statut.ACTIF)

    # LCAP (K6, E11). Les avis de service et les factures ne demandent pas de
    # consentement; les messages commerciaux, oui.
    consentement_commercial = models.BooleanField("consentement aux messages commerciaux", default=False)
    consentement_date = models.DateField("date du consentement", null=True, blank=True)
    consentement_source = models.CharField("source du consentement", max_length=10, choices=SourceConsentement.choices, blank=True)
    desabonne_le = models.DateTimeField(
        "désabonné le", null=True, blank=True,
        help_text="A texté ARRÊT ou STOP : plus de messages commerciaux, mais reçoit encore les avis de service.",
    )

    notes = models.TextField(blank=True)
    avis_operations = models.BooleanField(
        "avis pendant les opérations", default=True,
        help_text="Décoché : ce client ne reçoit ni l'avis de début, ni l'avis de proximité, ni le « c'est fait » (demande du client).")
    proprietaire_non_occupant = models.BooleanField(
        "propriétaire non occupant", default=False,
        help_text="Les avis des opérations vont aux locataires inscrits (« Autre personne à joindre », rôle locataire), jamais "
                  "au propriétaire; factures, relances, reçus et contrat restent au propriétaire, jamais aux locataires.")
    ne_pas_relancer = models.BooleanField("ne pas relancer", default=False,
                                          help_text="Jamais proposé dans les relances du matin (entente de paiement, cas délicat). La relance à la main reste possible.")
    relance_reportee_au = models.DateField("relance reportée au", null=True, blank=True)
    efface_le = models.DateTimeField("renseignements effacés le", null=True, blank=True, editable=False,
                                     help_text="Demande de suppression du client (Loi 25) : voir clients/effacement.py.")

    class Meta:
        verbose_name = "client"
        verbose_name_plural = "clients"
        ordering = ["nom", "prenom", "organisation"]
        indexes = [
            models.Index(fields=["entreprise", "statut"], name="client_entreprise_statut"),
            models.Index(Lower("nom"), "entreprise", name="client_nom_minuscules"),
        ]

    def __str__(self):
        return self.nom_affiche or f"Client n° {self.pk}"

    @property
    def nom_affiche(self):
        personne = " ".join(p for p in (self.prenom, self.nom) if p)
        if self.organisation and personne:
            return f"{self.organisation} ({personne})"
        return self.organisation or personne

    @property
    def peut_recevoir_commercial(self):
        return self.consentement_commercial and self.desabonne_le is None

    def clean_fields(self, exclude=None):
        # Nettoyer avant la validation du format : « Ginette@Exemple.CA » avec
        # une espace en trop (fréquent à l'import) doit passer, pas être refusé.
        self.courriel = (self.courriel or "").strip().lower()
        super().clean_fields(exclude=exclude)

    def clean(self):
        if not (self.nom or self.prenom or self.organisation):
            raise ValidationError("Il faut au moins un nom, un prénom ou une organisation.")
        erreurs = {}
        for champ in ("cellulaire", "telephone_autre"):
            try:
                setattr(self, champ, telephone.normaliser(getattr(self, champ)))
            except ValidationError as e:
                erreurs[champ] = e
        if erreurs:
            raise ValidationError(erreurs)
        self.facturation_code_postal = _code_postal(self.facturation_code_postal)
        if self.consentement_commercial and not self.consentement_date:
            raise ValidationError({"consentement_date": "Indiquer la date du consentement (preuve exigée par la LCAP)."})


class Contact(Horodate):
    """Autre personne à joindre pour un client (PRD A3) : conjoint, locataire, gestionnaire d'immeuble.
    Un texto ou un courriel reçu de ce contact est rattaché à la fiche du client."""

    class Role(models.TextChoices):
        CONJOINT = "conjoint", "Conjoint"
        LOCATAIRE = "locataire", "Locataire"
        GESTIONNAIRE = "gestionnaire", "Gestionnaire d'immeuble"
        FAMILLE = "famille", "Famille"
        AUTRE = "autre", "Autre"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="contacts")
    client = models.ForeignKey("Client", on_delete=models.CASCADE, related_name="contacts")
    nom = models.CharField(max_length=150)
    role = models.CharField("rôle", max_length=12, choices=Role.choices, default=Role.AUTRE)
    cellulaire = models.CharField(max_length=16, blank=True, db_index=True)
    courriel = models.EmailField(blank=True, db_index=True)
    note = models.CharField(max_length=200, blank=True, help_text="Ex. « appeler le soir », « a la clé du garage ».")

    class Meta:
        verbose_name = "contact"
        verbose_name_plural = "contacts"
        ordering = ["client", "nom"]

    def __str__(self):
        return f"{self.nom} ({self.get_role_display().lower()})"

    def clean_fields(self, exclude=None):
        self.courriel = (self.courriel or "").strip().lower()
        super().clean_fields(exclude=exclude)

    def clean(self):
        try:
            self.cellulaire = telephone.normaliser(self.cellulaire)
        except ValidationError as e:
            raise ValidationError({"cellulaire": e})
        if self.client_id and self.entreprise_id and self.client.entreprise_id != self.entreprise_id:
            raise ValidationError("Ce client n'est pas de cette entreprise.")


def client_par_cellulaire(entreprise, numero):
    """Le client d'un numéro (texto reçu) : son cellulaire, sinon celui d'un de ses contacts (A3)."""
    c = Client.objects.filter(entreprise=entreprise, cellulaire=numero).order_by("pk").first()
    if c is None and numero:
        k = Contact.objects.filter(entreprise=entreprise, cellulaire=numero).select_related("client").order_by("pk").first()
        c = k.client if k else None
    return c


def client_par_courriel(entreprise, adresse):
    c = Client.objects.filter(entreprise=entreprise, courriel__iexact=adresse).order_by("pk").first()
    if c is None and adresse:
        k = Contact.objects.filter(entreprise=entreprise, courriel__iexact=adresse).select_related("client").order_by("pk").first()
        c = k.client if k else None
    return c


class Adresse(Horodate):
    """Adresse de service : là où Louis déneige (A1, A2, A5, F1, F2)."""

    class SourcePosition(models.TextChoices):
        GEOCODAGE = "geocodage", "Géocodage automatique"
        MANUELLE = "manuelle", "Corrigée à la main sur la carte"
        GPS = "gps", "Position GPS prise sur place"

    class Precision(models.TextChoices):
        ADRESSE = "adresse", "Adresse exacte"
        RUE = "rue", "Rue seulement"
        VILLE = "ville", "Ville seulement"
        INTROUVABLE = "introuvable", "Introuvable"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="adresses")
    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="adresses")
    secteur = models.ForeignKey(Secteur, on_delete=models.SET_NULL, null=True, blank=True, related_name="adresses")
    active = models.BooleanField(default=True)

    ligne1 = models.CharField("adresse", max_length=200, help_text="Numéro civique et rue, ex. 123, rue Principale")
    ligne2 = models.CharField("adresse (suite)", max_length=200, blank=True, help_text="App., unité, etc.")
    ville = models.CharField(max_length=100)
    province = models.CharField(max_length=2, default="QC")
    code_postal = models.CharField("code postal", max_length=7, blank=True)

    # Position (A2). SRID 4326 : latitude et longitude du GPS.
    position = gis.PointField("position", srid=4326, null=True, blank=True, geography=True)
    position_source = models.CharField("source de la position", max_length=10, choices=SourcePosition.choices, blank=True)
    position_precision = models.CharField(
        "précision de la position", max_length=12, choices=Precision.choices, blank=True,
        help_text="« Ville seulement » : trop vague pour les avis de proximité, à corriger sur la carte.",
    )
    geocodage_note = models.CharField("résultat du géocodage", max_length=300, blank=True)

    # Tournée (F1) : rang de l'arrêt dans l'ordre habituel de Louis
    ordre_tournee = models.PositiveIntegerField("rang dans la tournée", null=True, blank=True)

    # Particularités du terrain (A5)
    ou_mettre_neige = models.CharField("où mettre la neige", max_length=200, blank=True)
    obstacles = models.CharField(max_length=200, blank=True, help_text="Bordures, aménagement, roches, etc.")
    borne_fontaine = models.BooleanField("borne-fontaine à dégager", default=False)
    entree_en_pente = models.BooleanField("entrée en pente", default=False)
    consignes = models.TextField("consignes spéciales", blank=True)

    class Meta:
        verbose_name = "adresse de service"
        verbose_name_plural = "adresses de service"
        ordering = ["entreprise", "secteur__ordre", "ordre_tournee", "ville", "ligne1"]
        indexes = [
            models.Index(fields=["entreprise", "secteur", "ordre_tournee"], name="adresse_tournee"),
        ]

    def __str__(self):
        return f"{self.ligne1}, {self.ville}"

    @property
    def position_a_verifier(self):
        """Position absente ou trop vague pour les avis de proximité (G2)."""
        if self.position_source in (self.SourcePosition.MANUELLE, self.SourcePosition.GPS):
            return False
        return self.position is None or self.position_precision in (self.Precision.VILLE, self.Precision.INTROUVABLE)

    @property
    def latitude(self):
        return self.position.y if self.position else None

    @property
    def longitude(self):
        return self.position.x if self.position else None

    def clean(self):
        self.code_postal = _code_postal(self.code_postal)
        if self.client_id and self.entreprise_id and self.client.entreprise_id != self.entreprise_id:
            raise ValidationError("L'adresse et le client doivent appartenir à la même entreprise.")
        if self.secteur_id and self.entreprise_id and self.secteur.entreprise_id != self.entreprise_id:
            raise ValidationError({"secteur": "Ce secteur appartient à une autre entreprise."})


class PhotoAdresse(models.Model):
    """Photo de l'entrée (PRD A5), gardée dans la base (donc dans les sauvegardes), servie aux membres seulement.
    Le cellulaire la réduit (environ 1600 px, JPEG) avant l'envoi : Pillow n'est pas une dépendance de l'app."""
    TYPES = {b"\xff\xd8\xff": "image/jpeg", b"\x89PNG": "image/png"}
    MAX_OCTETS = 8 * 1024 * 1024

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="photos_adresses")
    adresse = models.ForeignKey(Adresse, on_delete=models.CASCADE, related_name="photos")
    image = models.BinaryField()
    type_mime = models.CharField(max_length=20)
    taille = models.PositiveIntegerField(help_text="Octets.")
    prise_par = models.ForeignKey("auth.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "photo de l'entrée"
        verbose_name_plural = "photos de l'entrée"
        ordering = ["-cree_le"]

    def __str__(self):
        return f"Photo de {self.adresse} ({self.cree_le:%Y-%m-%d})"

    @classmethod
    def type_de(cls, debut):
        """Type d'image d'après ses premiers octets (jamais d'après le nom ou ce que dit le navigateur)."""
        for signature, mime in cls.TYPES.items():
            if debut.startswith(signature):
                return mime
        if debut[:4] == b"RIFF" and debut[8:12] == b"WEBP":
            return "image/webp"
        if debut[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftyphevc"):
            return "image/heic"
        return None


class Balisage(models.Model):
    """Balises (piquets) posées à une adresse (PRD A11) : combien, quand, et quand elles ont été retirées.
    Une adresse a au plus un balisage en place (sans date de retrait)."""
    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="balisages")
    adresse = models.ForeignKey(Adresse, on_delete=models.CASCADE, related_name="balisages")
    nombre = models.PositiveSmallIntegerField(default=1)
    posees_le = models.DateField("posées le", default=timezone.localdate)
    retirees_le = models.DateField("retirées le", null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "balisage"
        verbose_name_plural = "balises"
        ordering = ["-posees_le", "-pk"]
        constraints = [models.UniqueConstraint(fields=["adresse"], condition=models.Q(retirees_le=None), name="un_balisage_en_place")]

    def __str__(self):
        return f"{self.nombre} balise(s) au {self.adresse}"

    def clean(self):
        if self.retirees_le and self.retirees_le < self.posees_le:
            raise ValidationError({"retirees_le": "Le retrait ne peut pas précéder la pose."})
