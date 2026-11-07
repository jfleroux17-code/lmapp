"""Clients, adresses de service et secteurs (PRD section 5 A, F2, K6).

Un client (le payeur) peut avoir plusieurs adresses de service (A4, V2) : le
modèle le permet dès maintenant, même si l'interface V1 n'en montre qu'une.
"""
from django.contrib.gis.db import models as gis
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

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
    consentement_commercial = models.BooleanField("consent aux messages commerciaux", default=False)
    consentement_date = models.DateField("date du consentement", null=True, blank=True)
    consentement_source = models.CharField("source du consentement", max_length=10, choices=SourceConsentement.choices, blank=True)
    desabonne_le = models.DateTimeField(
        "désabonné le", null=True, blank=True,
        help_text="A texté ARRÊT ou STOP : plus de messages commerciaux, mais reçoit encore les avis de service.",
    )

    notes = models.TextField(blank=True)

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


class Adresse(Horodate):
    """Adresse de service : là où Louis déneige (A1, A2, A5, F1, F2)."""

    class SourcePosition(models.TextChoices):
        GEOCODAGE = "geocodage", "Géocodage automatique"
        MANUELLE = "manuelle", "Corrigée à la main sur la carte"
        GPS = "gps", "Position GPS prise sur place"

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
