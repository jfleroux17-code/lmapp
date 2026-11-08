"""Modèles de base : l'entreprise (le déneigeur) et ses membres.

Tout le reste de LMAPP est rattaché à une Entreprise (PRD section P). Aucune
donnée propre à Louis n'est codée en dur : nom, taxes, numéro de texto,
instructions de paiement, tout est ici, modifiable dans l'administration.
"""
from decimal import Decimal

from django.conf import settings
from django.contrib.gis.db import models as gis
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from core import telephone
from core.texte import cle_ville


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

    # Mode de l'entreprise (K9) : qui modifie les clients dans l'app
    class Mode(models.TextChoices):
        SEUL = "seul", "Déneigeur seul (le propriétaire fait tout)"
        EQUIPE = "equipe", "Équipe (seuls les administrateurs modifient les clients)"

    mode = models.CharField("mode", max_length=6, choices=Mode.choices, default=Mode.SEUL)

    # Numérotation des factures (C3) : séquentielle, sans trou, donnée à l'émission
    prochain_numero_facture = models.PositiveIntegerField(
        "numéro de la prochaine facture", default=1,
        help_text="Pour continuer la numérotation du carnet papier, mettre ici le numéro qui suit le dernier utilisé.",
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
    envois_actifs = models.BooleanField(
        "envois réels activés", default=False,
        help_text="Éteint : les textos et courriels restent « Préparé », rien ne part. À allumer seulement quand on est prêt à écrire aux clients.",
    )
    signature_messages = models.CharField(
        "signature des messages", max_length=100, blank=True,
        help_text="Identification de l'expéditeur à la fin des textos (LCAP), ex. « Louis Méthot Déneigement ».",
    )

    # Avis aux clients pendant une opération (PRD G2 à G5)
    avis_proximite_actif = models.BooleanField("avis de proximité", default=True, help_text="Texto aux clients quand le déneigeur approche.")
    avis_rayon_m = models.PositiveIntegerField("rayon des avis (m)", default=800, validators=[MinValueValidator(100), MaxValueValidator(5000)])
    minutes_par_arret = models.PositiveIntegerField("minutes par arrêt", default=6, validators=[MinValueValidator(1), MaxValueValidator(60)],
                                                    help_text="Pour estimer « d'ici environ X minutes ».")
    avis_passage_fait = models.BooleanField("avis « c'est fait »", default=False, help_text="Texto au client quand son passage est fait.")

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


class VilleDesservie(Horodate):
    """Ville où l'entreprise travaille, avec sa zone de service.

    Le géocodage cherche chaque adresse dans la zone de sa ville et rejette un
    résultat hors du rayon. La ville « par défaut » remplit la ville d'une
    adresse importée sans ville. On en ajoute une si l'opération grossit.
    """

    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, related_name="villes")
    nom = models.CharField(max_length=100, help_text="Tel qu'écrit dans les adresses, ex. « Sainte-Adèle ».")
    province = models.CharField(max_length=2, default="QC")
    centre = gis.PointField(
        srid=4326, geography=True, null=True, blank=True,
        help_text="Laisser vide : rempli automatiquement avec le centre de la ville à l'enregistrement.",
    )
    rayon_km = models.DecimalField(
        "rayon de la zone (km)", max_digits=5, decimal_places=1, default=Decimal("8.0"),
        validators=[MinValueValidator(Decimal("0.5")), MaxValueValidator(Decimal("100"))],
        help_text="Assez grand pour couvrir tout le territoire de la ville.",
    )
    par_defaut = models.BooleanField("ville par défaut", default=False)

    class Meta:
        verbose_name = "ville desservie"
        verbose_name_plural = "villes desservies"
        ordering = ["entreprise", "-par_defaut", "nom"]
        constraints = [
            models.UniqueConstraint(fields=["entreprise", "nom"], name="ville_unique_par_entreprise"),
            models.UniqueConstraint(fields=["entreprise"], condition=models.Q(par_defaut=True), name="une_seule_ville_par_defaut"),
        ]

    def __str__(self):
        return self.nom

    def zone(self):
        from clients.geocodage import Zone

        if self.centre is None:
            return None
        return Zone(self.centre.y, self.centre.x, float(self.rayon_km))

    @classmethod
    def pour(cls, entreprise_id, ville):
        """La ville desservie qui correspond au nom d'une adresse (accents et majuscules ignorés)."""
        cible = cle_ville(ville)
        for v in cls.objects.filter(entreprise_id=entreprise_id):
            if cle_ville(v.nom) == cible:
                return v
        return None

    @classmethod
    def par_defaut_de(cls, entreprise_id):
        return cls.objects.filter(entreprise_id=entreprise_id, par_defaut=True).first()


class EchecConnexion(models.Model):
    """Un essai de connexion raté, pour la limitation des essais (core.connexions).

    Gardé 24 heures au plus : l'IP est une donnée personnelle (Loi 25).
    """

    moment = models.DateTimeField(auto_now_add=True, db_index=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    nom_utilisateur = models.CharField(max_length=150, blank=True)

    class Meta:
        verbose_name = "échec de connexion"
        verbose_name_plural = "échecs de connexion"
        ordering = ["-moment"]
        indexes = [
            models.Index(fields=["ip", "moment"], name="echec_ip_moment"),
            models.Index(fields=["nom_utilisateur", "moment"], name="echec_nom_moment"),
        ]

    def __str__(self):
        return f"{self.moment:%Y-%m-%d %H:%M} {self.nom_utilisateur} ({self.ip})"


class AbonnementNotification(models.Model):
    """Un cellulaire (ou navigateur) qui reçoit les notifications de l'app (PRD E8, Web Push).
    Sur iPhone : seulement si l'app est ajoutée à l'écran d'accueil."""
    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="abonnements_notification")
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, related_name="abonnements_notification")
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=100)
    appareil = models.CharField(max_length=200, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    dernier_envoi = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "abonnement aux notifications"
        verbose_name_plural = "abonnements aux notifications"

    def __str__(self):
        return f"{self.utilisateur} ({self.appareil[:40]})"
