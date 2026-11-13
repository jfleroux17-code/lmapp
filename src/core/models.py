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
from django.utils import timezone

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
    # Abonnement à la plateforme (PRD Q2) : facture du mois préparée par l'app, émise et envoyée par JF
    class Tarif(models.TextChoices):
        STANDARD = "standard", "Standard (99 $ par mois, utilisateurs, textos)"
        TEXTOS_AU_COUT = "textos_cout", "Textos au coût seulement"

    tarif_plateforme = models.CharField(
        "tarif de la plateforme", max_length=12, choices=Tarif.choices, default=Tarif.STANDARD,
        help_text="Textos au coût seulement : ni abonnement ni utilisateurs, le coût réel des textos chez Twilio (dollars US) "
                  "converti au taux PLATEFORME_TAUX_USD_CAD (décision de JF pour Louis, 13 novembre 2026).")
    abonnement_facture = models.BooleanField(
        "abonnement facturé", default=False,
        help_text="Coché : la facture de la plateforme du mois passé est préparée le 1er du mois (brouillon, rien ne part sans JF).")
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
    # Jobs à la pièce (déneigement manuel, paysagement) : taux de Louis, à remplir (question à Louis, 12 novembre 2026)
    taux_horaire = models.DecimalField("taux horaire", max_digits=8, decimal_places=2, null=True, blank=True,
                                       help_text="Main-d'œuvre d'une job à la pièce, avant taxes, par heure.")
    taux_km = models.DecimalField("taux par kilomètre", max_digits=6, decimal_places=2, null=True, blank=True,
                                  help_text="Déplacement d'une job, aller-retour, par kilomètre.")
    minimum_job = models.DecimalField("minimum facturé par job", max_digits=8, decimal_places=2, null=True, blank=True)
    position_auto = models.BooleanField(
        "activer la position automatiquement", default=True,
        help_text="Au début de chaque opération, la position du cellulaire s'allume toute seule (statistiques et, avec les avis, "
                  "avis de proximité). Sinon : bouton « Activer la position » sur l'écran de tournée.")

    # Relances proposées (PRD C9) : l'app prépare, le déneigeur envoie d'une tape. Rien ne part tout seul.
    relances_proposees = models.BooleanField(
        "relances proposées chaque matin", default=False,
        help_text="Les jours de semaine, l'app dresse la liste des relances dues (15, 30 et 60 jours après l'échéance) et avise le cellulaire. Rien ne part sans une tape.",
    )
    relances_soldes_anterieurs = models.BooleanField(
        "proposer aussi les soldes antérieurs", default=False,
        help_text="Éteint : un client qui ne doit qu'un solde d'une saison antérieure se relance à la main.",
    )
    relances_avisees_le = models.DateField("relances avisées le", null=True, blank=True, editable=False)

    # Échéancier des contrats saisonniers (PRD B3, C5) : 1er versement à l'approbation, les autres aux dates ci-dessous
    versements_par_defaut = models.PositiveSmallIntegerField(
        "versements par défaut", default=1, validators=[MinValueValidator(1), MaxValueValidator(4)],
        help_text="Nombre de versements d'un nouveau contrat saisonnier (import, administration), sauf indication contraire.")
    dates_versements = models.CharField(
        "dates des versements suivants", max_length=60, blank=True,
        help_text="Jour/mois, séparés par des espaces, ex. « 15/01 15/02 ». Le 1er versement est à l'approbation du contrat; "
                  "avec 2 versements, le 2e est à la 1re date; avec 3, aux deux premières.")
    jours_avance_versement = models.PositiveSmallIntegerField(
        "jours d'avance des rappels de versement", default=0, validators=[MaxValueValidator(30)],
        help_text="Le rappel d'un versement est proposé ce nombre de jours avant sa date, ex. 5 : le 10 janvier pour le 15. "
                  "Le cellulaire est avisé; rien ne part sans une tape.")
    jours_paiement_passage = models.PositiveSmallIntegerField(
        "délai de paiement des factures au passage (jours)", default=0, validators=[MaxValueValidator(60)],
        help_text="0 : payable sur réception (décision de JF, 12 novembre 2026).")

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

    def liste_dates_versements(self):
        """[(jour, mois)] des versements après le premier, d'après « 15/01 15/02 ». ValueError si mal écrit."""
        from datetime import date

        dates = []
        for morceau in self.dates_versements.replace(",", " ").replace(";", " ").split():
            try:
                jour, mois = (int(x) for x in morceau.split("/"))
                date(2028, mois, jour)  # année bissextile : 29/02 accepté
            except ValueError:
                raise ValueError(f"« {morceau} » : écrire jour/mois, ex. 15/01.") from None
            dates.append((jour, mois))
        return dates

    def clean(self):
        from django.core.exceptions import ValidationError

        try:
            self.liste_dates_versements()
        except ValueError as e:
            raise ValidationError({"dates_versements": str(e)}) from e
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


class IncidentConfidentialite(models.Model):
    """Registre des incidents de confidentialité (Loi 25, art. 3.8; PRD K5).

    Tout accès, utilisation, communication ou perte de renseignements personnels non autorisé est inscrit,
    même sans risque de préjudice sérieux. Risque sérieux : aviser la Commission d'accès à l'information
    et les personnes touchées avec diligence. Garder chaque inscription au moins 5 ans après le constat."""
    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, null=True, blank=True, related_name="incidents",
                                   help_text="Vide : incident touchant toute la plateforme (toutes les entreprises).")
    survenu_le = models.DateField("survenu le", null=True, blank=True, help_text="Vide si la date est inconnue.")
    constate_le = models.DateField("constaté le")
    description = models.TextField(help_text="Ce qui s'est passé, et comment on l'a su.")
    renseignements = models.TextField("renseignements visés", help_text="Quels renseignements (noms, adresses, téléphones, etc.).")
    personnes = models.PositiveIntegerField("nombre de personnes touchées", null=True, blank=True, help_text="Vide si inconnu.")
    risque_serieux = models.BooleanField("risque de préjudice sérieux", default=False)
    evaluation = models.TextField("évaluation du risque", blank=True, help_text="Sensibilité, conséquences possibles, probabilité d'usage malveillant.")
    mesures = models.TextField("mesures prises", blank=True, help_text="Pour réduire le risque et éviter que ça se reproduise.")
    cai_avisee_le = models.DateField("Commission d'accès à l'information avisée le", null=True, blank=True)
    personnes_avisees_le = models.DateField("personnes touchées avisées le", null=True, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "incident de confidentialité"
        verbose_name_plural = "registre des incidents de confidentialité"
        ordering = ["-constate_le", "-pk"]

    def __str__(self):
        return f"{self.constate_le:%Y-%m-%d} : {self.description[:60]}"


class JournalAction(models.Model):
    """Journal des actions (PRD K4) : qui a créé, modifié ou supprimé quoi, champ par champ (avant, après).
    Rempli automatiquement (core/journal.py); consultation dans l'administration seulement, rien ne s'y modifie.
    Gardé LMAPP_JOURNAL_JOURS jours (730 par défaut); vidé pour un client effacé à sa demande (Loi 25)."""

    class Action(models.TextChoices):
        CREATION = "creation", "Création"
        MODIFICATION = "modification", "Modification"
        SUPPRESSION = "suppression", "Suppression"
        EFFACEMENT = "effacement", "Effacement (Loi 25)"

    moment = models.DateTimeField(auto_now_add=True, db_index=True)
    # Sans contrainte en base : le journal survit à ce qu'il décrit (une entreprise ou un utilisateur supprimé)
    entreprise = models.ForeignKey(Entreprise, on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True, related_name="+")
    utilisateur = models.ForeignKey("auth.User", on_delete=models.DO_NOTHING, db_constraint=False, null=True, blank=True, related_name="+")
    nom_utilisateur = models.CharField("auteur", max_length=150, help_text="« système » : worker, tâche ou commande.")
    ip = models.GenericIPAddressField(null=True, blank=True)
    action = models.CharField(max_length=12, choices=Action.choices)
    modele = models.CharField("type", max_length=60)
    objet_id = models.BigIntegerField(null=True)
    objet = models.CharField(max_length=200)
    client_id = models.BigIntegerField(null=True, blank=True, db_index=True, help_text="Client concerné, s'il y en a un.")
    changements = models.JSONField(default=dict, blank=True, help_text="{champ: [avant, après]}")

    class Meta:
        verbose_name = "action du journal"
        verbose_name_plural = "actions du journal"
        ordering = ["-moment", "-pk"]
        indexes = [models.Index(fields=["entreprise", "-moment"], name="journal_entreprise_moment")]

    def __str__(self):
        return f"{self.get_action_display()} : {self.modele} « {self.objet} »"


class Meteo(models.Model):
    """Prévisions d'Environnement Canada pour l'entreprise (PRD I1), relevées par le worker (l'app n'a pas Internet).
    Ville de prévision : la plus proche du centre de la ville desservie par défaut, trouvée une fois."""
    entreprise = models.OneToOneField(Entreprise, on_delete=models.CASCADE, related_name="meteo")
    ville_id = models.CharField(max_length=20, blank=True, help_text="Identifiant GeoMet, ex. qc-c3 (Saint-Sauveur).")
    ville_nom = models.CharField(max_length=100, blank=True)
    ville_choisie = models.BooleanField("ville choisie par le déneigeur", default=False,
                                        help_text="Faux : la plus proche, choisie par l'app.")
    villes_proches = models.JSONField(default=list, blank=True,
                                      help_text="Villes de prévision autour, pour le choix dans l'app : [[id, nom, km]].")
    lien = models.URLField(blank=True)
    periodes = models.JSONField(default=list, blank=True, help_text="[{nom, resume, neige_cm, pluie_mm}]")
    avertissements = models.JSONField(default=list, blank=True)
    publiee_le = models.DateTimeField(null=True, blank=True)
    lue_le = models.DateTimeField(null=True, blank=True)
    # Prévision au point exact de la ville desservie (modèle HRDPS d'Environnement Canada, 2,5 km; option 1 de JF,
    # 12 novembre 2026) : la page de prévision ci-dessus est celle d'une ville voisine (pas de page pour Sainte-Adèle).
    point = models.JSONField(default=list, blank=True, help_text="[{debut, fin, neige_cm, pluie_mm, verglas_mm, temp_min, temp_max}]")
    point_lieu = models.CharField("lieu de la prévision au point", max_length=100, blank=True)
    point_lu_le = models.DateTimeField(null=True, blank=True)
    point_modele_le = models.DateTimeField("exécution du modèle", null=True, blank=True)
    erreur = models.CharField(max_length=300, blank=True)

    class Meta:
        verbose_name = "prévisions météo"
        verbose_name_plural = "prévisions météo"

    def __str__(self):
        return f"Météo de {self.entreprise} ({self.ville_nom})"

    def tranches_point(self):
        """Prévision au point, pour l'affichage : heures locales, neige des 24 prochaines heures."""
        from django.utils.dateparse import parse_datetime

        sortie = []
        for x in self.point or []:
            sortie.append({**x, "debut": timezone.localtime(parse_datetime(x["debut"])), "fin": timezone.localtime(parse_datetime(x["fin"]))})
        return sortie

    @property
    def neige_24h(self):
        return round(sum(x.get("neige_cm") or 0 for x in (self.point or [])[:4]), 1)

    @property
    def verglas_24h(self):
        return round(sum(x.get("verglas_mm") or 0 for x in (self.point or [])[:4]), 1)


class DemandeSite(models.Model):
    """Courriel reçu à l'adresse de la plateforme (info@, celle du site Internet) : clients potentiels, questions.

    Lu par le worker aux 2 minutes (core/boite_plateforme.py, en prod seulement), gardé au complet ici
    (compressé) et transféré à JF (PLATEFORME_TRANSFERT_A). Rien n'est marqué lu ni effacé dans la boîte.
    Suivi par JF dans l'administration (superutilisateur seulement). Effacée après LMAPP_DEMANDES_SITE_JOURS
    jours (2 ans, core.tasks.purger_conservation_chaque_nuit)."""

    class Statut(models.TextChoices):
        NOUVELLE = "nouvelle", "Nouvelle"
        EN_COURS = "en_cours", "En cours"
        CLIENT = "client", "Devenu client"
        SANS_SUITE = "sans_suite", "Sans suite"
        POURRIEL = "pourriel", "Pourriel"
        AUTOMATIQUE = "automatique", "Message automatique"

    recu_le = models.DateTimeField("reçu le", db_index=True)
    uidvalidite = models.BigIntegerField()
    uid = models.BigIntegerField()
    entete_message_id = models.CharField("Message-ID", max_length=300, blank=True)
    expediteur = models.CharField("adresse", max_length=254, blank=True)
    nom = models.CharField(max_length=200, blank=True)
    sujet = models.CharField(max_length=200, blank=True)
    texte = models.TextField(blank=True)
    pieces_jointes = models.JSONField("pièces jointes", default=list, blank=True, help_text="Noms seulement : le courriel complet est gardé.")
    brut = models.BinaryField(help_text="Courriel complet, compressé (zlib).")
    statut = models.CharField(max_length=12, choices=Statut.choices, default=Statut.NOUVELLE, db_index=True)
    note = models.TextField(blank=True, help_text="Suivi : appel fait, offre envoyée, etc.")
    transferee_le = models.DateTimeField("transférée le", null=True, blank=True)
    essais_transfert = models.PositiveSmallIntegerField(default=0)
    erreur_transfert = models.CharField(max_length=300, blank=True)
    cree_le = models.DateTimeField(auto_now_add=True)
    modifie_le = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "demande reçue à info@"
        verbose_name_plural = "demandes reçues à info@ (clients potentiels)"
        ordering = ["-recu_le", "-pk"]
        constraints = [models.UniqueConstraint(fields=["uidvalidite", "uid"], name="demande_site_uid_unique")]

    def __str__(self):
        return f"{self.recu_le:%Y-%m-%d} {self.nom or self.expediteur} : {self.sujet[:60]}"

    def octets(self):
        import zlib

        return zlib.decompress(bytes(self.brut))


class FacturePlateforme(Horodate):
    """Facture de la plateforme à une entreprise de déneigement (PRD Q2) : abonnement, utilisateurs de plus et textos
    d'un mois. Brouillon préparé par l'app (lignes modifiables par JF), puis émise (numéro de la série de la
    plateforme, taux et numéros de taxes copiés, plus rien ne change), envoyée par courriel, payée ou annulée."""

    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        EMISE = "emise", "Émise"
        PAYEE = "payee", "Payée"
        ANNULEE = "annulee", "Annulée"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="factures_plateforme")
    mois = models.DateField(help_text="Premier jour du mois facturé.")
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.BROUILLON)
    numero = models.PositiveIntegerField("numéro", null=True, blank=True, unique=True)
    date_facture = models.DateField("date", null=True, blank=True)
    date_echeance = models.DateField("échéance", null=True, blank=True)
    sous_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    taux_tps = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0"))
    taux_tvq = models.DecimalField(max_digits=6, decimal_places=3, default=Decimal("0"))
    numero_tps = models.CharField(max_length=30, blank=True)
    numero_tvq = models.CharField(max_length=30, blank=True)
    tps = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    tvq = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    # Usage relevé à la préparation (gardé tel quel : la facture dit sur quoi elle se fonde)
    textos_envoyes = models.PositiveIntegerField(default=0)
    textos_recus = models.PositiveIntegerField(default=0)
    courriels = models.PositiveIntegerField("courriels envoyés et reçus", default=0)
    utilisateurs = models.PositiveIntegerField("utilisateurs facturables", default=0)
    note = models.TextField(blank=True, help_text="Imprimée sur la facture (ex. rabais, premier mois).")
    envoyee_le = models.DateTimeField("envoyée le", null=True, blank=True)
    envoyee_a = models.EmailField("envoyée à", blank=True)
    erreur_envoi = models.CharField(max_length=300, blank=True)
    payee_le = models.DateField("payée le", null=True, blank=True)
    raison_annulation = models.CharField("raison de l'annulation", max_length=200, blank=True)

    class Meta:
        verbose_name = "facture de la plateforme"
        verbose_name_plural = "factures de la plateforme"
        ordering = ["-mois", "entreprise__nom"]
        constraints = [models.UniqueConstraint(fields=["entreprise", "mois"], condition=~models.Q(statut="annulee"),
                                               name="une_facture_plateforme_par_mois")]

    def __str__(self):
        quoi = f"n° {self.numero}" if self.numero else "brouillon"
        return f"{self.entreprise.nom}, {self.mois:%Y-%m} ({quoi})"

    @property
    def modifiable(self):
        return self.statut == self.Statut.BROUILLON


class LigneFacturePlateforme(models.Model):
    facture = models.ForeignKey(FacturePlateforme, on_delete=models.CASCADE, related_name="lignes")
    ordre = models.PositiveSmallIntegerField(default=0)
    description = models.CharField(max_length=200)
    quantite = models.DecimalField("quantité", max_digits=10, decimal_places=2, default=Decimal("1"))
    prix_unitaire = models.DecimalField("prix", max_digits=10, decimal_places=4)

    class Meta:
        verbose_name = "ligne"
        verbose_name_plural = "lignes"
        ordering = ["ordre", "pk"]

    def __str__(self):
        return self.description

    @property
    def montant(self):
        from facturation.calculs import arrondir

        return arrondir(self.quantite * self.prix_unitaire)


class DoubleAuthentification(models.Model):
    """Double authentification par application (Google Authenticator, TOTP de la RFC 6238), demande de JF du
    12 novembre 2026. Obligatoire pour JF (superutilisateur) et les administrateurs des déneigeurs, au choix pour
    les autres. Le code est demandé à chaque nouvelle connexion (pas à chaque ouverture de l'app). Règles :
    `core/double_auth.py`."""
    utilisateur = models.OneToOneField("auth.User", on_delete=models.CASCADE, related_name="double_auth")
    secret = models.CharField(max_length=64, help_text="Clé partagée avec l'application (base32). Jamais affichée après l'activation.")
    active_le = models.DateTimeField("activée le", default=timezone.now)
    dernier_pas = models.BigIntegerField(default=0, help_text="Dernier pas de 30 secondes accepté : un code ne sert qu'une fois.")
    codes_secours = models.JSONField(default=list, blank=True, help_text="Empreintes SHA-256 des codes de secours pas encore utilisés.")
    derniere_utilisation = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "double authentification"
        verbose_name_plural = "doubles authentifications"

    def __str__(self):
        return f"Double authentification de {self.utilisateur}"
