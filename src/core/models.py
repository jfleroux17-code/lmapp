"""Modèles de base : l'entreprise (le déneigeur) et ses membres.

Tout le reste de LMAPP est rattaché à une Entreprise (PRD section P). Aucune
donnée propre à Louis n'est codée en dur : nom, taxes, numéro de texto,
instructions de paiement, tout est ici, modifiable dans l'administration.
"""
from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core import telephone


class Horodate(models.Model):
    """Dates de création et de modification, pour tous les modèles."""

    cree_le = models.DateTimeField("créé le", auto_now_add=True)
    modifie_le = models.DateTimeField("modifié le", auto_now=True)

    class Meta:
        abstract = True


class Entreprise(Horodate):
    nom = models.CharField("nom commercial", max_length=150, help_text="Le nom que voient les clients, ex. « Louis Méthot Déneigement ».")
    nom_legal = models.CharField("nom légal", max_length=150, blank=True, help_text="Si différent du nom commercial (factures).")
    slug = models.SlugField("identifiant", unique=True, help_text="Court, sans accent ni espace, ex. « louis ».")
    domaine = models.CharField("domaine de l'app", max_length=253, unique=True, help_text="Ex. louis.ledeneigeur.com")
    active = models.BooleanField(default=True)

    # Coordonnées affichées sur les factures et dans les messages
    telephone = models.CharField("téléphone", max_length=16, blank=True, help_text="Numéro que les clients peuvent appeler.")
    courriel = models.EmailField("courriel", blank=True)
    adresse_ligne1 = models.CharField("adresse", max_length=200, blank=True)
    adresse_ligne2 = models.CharField("adresse (suite)", max_length=200, blank=True)
    ville = models.CharField(max_length=100, blank=True)
    province = models.CharField(max_length=2, default="QC")
    code_postal = models.CharField("code postal", max_length=7, blank=True)

    # Taxes (PRD C2 et section 7). Inscription à confirmer avec Louis.
    inscrit_taxes = models.BooleanField(
        "inscrit à la TPS et à la TVQ", default=False,
        help_text="Décoché : petit fournisseur, factures sans taxes.",
    )
    numero_tps = models.CharField("numéro de TPS", max_length=20, blank=True, help_text="Ex. 123456789 RT0001")
    numero_tvq = models.CharField("numéro de TVQ", max_length=20, blank=True, help_text="Ex. 1234567890 TQ0001")
    taux_tps = models.DecimalField(
        "taux de TPS (%)", max_digits=6, decimal_places=3, default=Decimal("5.000"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    taux_tvq = models.DecimalField(
        "taux de TVQ (%)", max_digits=6, decimal_places=3, default=Decimal("9.975"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )

    # Communications (PRD E1, M2). Les clés API restent dans .env, jamais ici.
    numero_texto = models.CharField(
        "numéro de texto d'affaires", max_length=16, blank=True,
        help_text="Numéro Twilio, format +1XXXXXXXXXX.",
    )
    courriel_reponse = models.EmailField(
        "adresse de réponse des courriels", blank=True,
        help_text="La boîte IMAP lue par l'app, ex. info@ledeneigeur.com.",
    )
    signature_messages = models.CharField(
        "signature des messages", max_length=100, blank=True,
        help_text="Identification de l'expéditeur à la fin des textos (LCAP), ex. « Louis Méthot Déneigement ».",
    )

    # Paiement Interac (PRD D4)
    interac_courriel = models.EmailField("courriel Interac", blank=True)
    interac_instructions = models.TextField(
        "instructions de virement Interac", blank=True,
        help_text="Texte affiché sur les factures (dépôt automatique, question de sécurité, etc.).",
    )

    class Meta:
        verbose_name = "entreprise"
        verbose_name_plural = "entreprises"
        ordering = ["nom"]

    def __str__(self):
        return self.nom

    def clean(self):
        self.telephone = telephone.normaliser(self.telephone)
        self.numero_texto = telephone.normaliser(self.numero_texto)
        self.code_postal = self.code_postal.upper().replace(" ", "")
        if len(self.code_postal) == 6:
            self.code_postal = f"{self.code_postal[:3]} {self.code_postal[3:]}"


class Membre(Horodate):
    """Lien entre un utilisateur et une entreprise, avec son rôle (PRD K2)."""

    class Role(models.TextChoices):
        ADMINISTRATEUR = "admin", "Administrateur"
        OPERATEUR = "operateur", "Opérateur"
        LECTURE = "lecture", "Lecture seule"

    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="membres")
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, related_name="membres")
    role = models.CharField("rôle", max_length=10, choices=Role.choices, default=Role.OPERATEUR)

    class Meta:
        verbose_name = "membre"
        verbose_name_plural = "membres"
        constraints = [
            models.UniqueConstraint(fields=["utilisateur", "entreprise"], name="membre_unique_par_entreprise"),
        ]

    def __str__(self):
        return f"{self.utilisateur} : {self.get_role_display()} chez {self.entreprise}"
