"""Tournée (PRD section F) : opérations (bordées) et passages à chaque adresse.

Une opération est en cours tant qu'elle n'a pas d'heure de fin; une seule à la
fois par entreprise (Louis travaille seul; F12, plusieurs véhicules, viendra plus tard).
Un passage par adresse et par opération : retaper « Fait » ou « Sauté » corrige le
passage au lieu d'en créer un deuxième.
"""
from django.conf import settings
from django.contrib.gis.db import models as gis
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from clients.models import Adresse, Client
from core.models import Entreprise, Horodate


class Operation(Horodate):
    class Type(models.TextChoices):
        NEIGE = "neige", "Neige"
        VERGLAS = "verglas", "Verglas (abrasif)"
        BORDAGE = "bordage", "Bordage de la ville"
        FINITION = "finition", "Finition"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="operations")
    type = models.CharField(max_length=10, choices=Type.choices, default=Type.NEIGE)
    debut = models.DateTimeField("début", default=timezone.now)
    fin = models.DateTimeField(null=True, blank=True)
    operateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="operations")
    avis_clients = models.BooleanField(
        "avec avis aux clients", default=True,
        help_text="Choisi au démarrage, chaque fois (décision de JF, 12 novembre 2026). Sans avis (ex. la nuit) : aucun texto ni "
                  "courriel aux clients pendant toute l'opération (début, proximité, terminé, avis manuels); la position reste "
                  "active pour les statistiques.")
    note = models.TextField(blank=True)

    class Meta:
        verbose_name = "opération"
        verbose_name_plural = "opérations"
        ordering = ["entreprise", "-debut"]
        constraints = [
            models.UniqueConstraint(fields=["entreprise"], condition=models.Q(fin=None), name="une_operation_en_cours_par_entreprise"),
        ]

    def __str__(self):
        return f"{self.get_type_display()}, {timezone.localtime(self.debut):%Y-%m-%d %H:%M}"

    @property
    def en_cours(self):
        return self.fin is None

    def clean(self):
        if self.fin and self.fin < self.debut:
            raise ValidationError({"fin": "La fin doit venir après le début."})

    def terminer(self):
        if self.fin is None:
            self.fin = timezone.now()
            self.save(update_fields=["fin", "modifie_le"])
            from tournee.temps import calculer

            calculer(self)  # temps par entrée, gardés avec les passages

    @classmethod
    def en_cours_de(cls, entreprise):
        return cls.objects.filter(entreprise=entreprise, fin=None).first()


def arrets(entreprise):
    """Les adresses de la tournée, dans l'ordre habituel de Louis (F1, F2) : clients servis
    (actifs et en recouvrement), secteur par secteur, puis le rang; sans rang à la fin."""
    return (Adresse.objects.filter(entreprise=entreprise, active=True,
                                   client__statut__in=[Client.Statut.ACTIF, Client.Statut.RECOUVREMENT])
            .exclude(client__saisons=Client.Saisons.ETE)  # clients d'été seulement : pas dans la tournée de déneigement
            .select_related("client", "secteur")
            .order_by(models.F("secteur__ordre").asc(nulls_last=True), "secteur__nom", models.F("ordre_tournee").asc(nulls_last=True), "ligne1"))


class Passage(Horodate):
    class Statut(models.TextChoices):
        FAIT = "fait", "Fait"
        SAUTE = "saute", "Sauté"

    class Raison(models.TextChoices):
        AUTO = "auto", "Auto dans l'entrée"
        ABSENT = "absent", "Pas nécessaire ou client absent"
        NON_PAYE = "non_paye", "Compte non payé"
        INACCESSIBLE = "inaccessible", "Inaccessible"
        AUTRE = "autre", "Autre"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="passages")
    operation = models.ForeignKey(Operation, on_delete=models.CASCADE, related_name="passages")
    adresse = models.ForeignKey(Adresse, on_delete=models.PROTECT, related_name="passages")
    statut = models.CharField(max_length=5, choices=Statut.choices)
    raison = models.CharField("raison", max_length=12, choices=Raison.choices, blank=True)
    heure = models.DateTimeField(default=timezone.now)
    note = models.CharField("note de passage", max_length=300, blank=True, help_text="Dommage constaté, obstacle, demande du client (F8).")
    position = gis.PointField(srid=4326, geography=True, null=True, blank=True)
    # F11 : la ligne de facture créée pour un client « au passage »
    ligne_facture = models.OneToOneField("facturation.LigneFacture", on_delete=models.SET_NULL, null=True, blank=True, related_name="passage")
    # Temps mesurés (demande de Louis, 12 novembre 2026), calculés à la fin de l'opération (tournee/temps.py) et gardés :
    # les positions, elles, sont effacées après 120 jours.
    arrivee = models.DateTimeField("arrivée", null=True, blank=True, help_text="Premier point GPS près de l'entrée.")
    sur_place_s = models.PositiveIntegerField("temps sur place (s)", null=True, blank=True, help_text="De l'arrivée à la tape « Fait ».")
    trajet_s = models.PositiveIntegerField("trajet (s)", null=True, blank=True, help_text="De l'entrée précédente à l'arrivée.")
    depuis_precedent_s = models.PositiveIntegerField("depuis l'entrée précédente (s)", null=True, blank=True,
                                                     help_text="Trajet et travail, de la tape précédente (ou du début) à celle-ci; sert sans GPS.")

    class Meta:
        verbose_name = "passage"
        verbose_name_plural = "passages"
        ordering = ["-heure"]
        constraints = [models.UniqueConstraint(fields=["operation", "adresse"], name="un_passage_par_adresse_et_operation")]
        indexes = [models.Index(fields=["adresse", "-heure"], name="passage_adresse_heure")]

    def __str__(self):
        return f"{self.adresse} : {self.get_statut_display().lower()} ({timezone.localtime(self.heure):%Y-%m-%d %H:%M})"

    def clean(self):
        if self.statut == self.Statut.SAUTE and not self.raison:
            raise ValidationError({"raison": "Indiquer pourquoi le passage est sauté."})
        for champ in ("operation", "adresse"):
            lie = getattr(self, champ, None)
            if lie is not None and self.entreprise_id and lie.entreprise_id != self.entreprise_id:
                raise ValidationError({champ: "Appartient à une autre entreprise."})


class PositionGPS(models.Model):
    """Position du cellulaire pendant une opération (G1), envoyée par l'écran de tournée ouvert.
    Effacée après LMAPP_POSITIONS_JOURS jours (120, core.tasks.purger_conservation_chaque_nuit; Loi 25)."""

    operation = models.ForeignKey(Operation, on_delete=models.CASCADE, related_name="positions")
    moment = models.DateTimeField(default=timezone.now)
    position = gis.PointField(srid=4326, geography=True)
    precision_m = models.PositiveIntegerField("précision (m)", null=True, blank=True)

    class Meta:
        verbose_name = "position GPS"
        verbose_name_plural = "positions GPS"
        ordering = ["-moment"]
        indexes = [models.Index(fields=["operation", "-moment"], name="position_operation_moment")]


class PhotoPassage(models.Model):
    """Photo prise à un arrêt pendant une opération (PRD F7) : heure de la prise et position du cellulaire.
    Gardée dans la base, comme la photo de l'entrée (clients.PhotoAdresse), servie aux membres seulement.
    « Avant » ou « après » se déduit de l'heure du passage noté pour cet arrêt."""
    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="photos_passages")
    operation = models.ForeignKey(Operation, on_delete=models.CASCADE, related_name="photos")
    adresse = models.ForeignKey(Adresse, on_delete=models.CASCADE, related_name="photos_passages")
    image = models.BinaryField()
    type_mime = models.CharField(max_length=20)
    taille = models.PositiveIntegerField(help_text="Octets.")
    prise_le = models.DateTimeField("prise le")
    position = gis.PointField(srid=4326, geography=True, null=True, blank=True)
    precision_m = models.PositiveIntegerField("précision (m)", null=True, blank=True)
    prise_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    cree_le = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "photo de passage"
        verbose_name_plural = "photos de passage"
        ordering = ["prise_le"]

    def __str__(self):
        return f"Photo du {self.prise_le:%Y-%m-%d %H:%M} ({self.adresse})"

    def moment(self, passage=None):
        """« avant » ou « après » le passage noté (heure comparée), sinon « pendant l'opération »."""
        if passage is None:
            passage = Passage.objects.filter(operation_id=self.operation_id, adresse_id=self.adresse_id).first()
        if passage is None or passage.statut != Passage.Statut.FAIT:
            return "pendant l'opération"
        return "avant" if self.prise_le < passage.heure else "après"



class Job(models.Model):
    """Job à la pièce (demandes de Louis, 12 novembre 2026) : déneigement manuel facturé au temps et au déplacement
    (ex. à Saint-Sauveur), paysagement l'été. Partie de la fiche du client : départ (position du cellulaire), arrivée,
    fin; distance estimée à vol d'oiseau × 1,3 (l'app n'a pas Internet pour un vrai itinéraire); facture en brouillon
    avec la main-d'œuvre et le déplacement aux taux de l'entreprise, le matériel ajouté sur la facture."""

    class Genre(models.TextChoices):
        DENEIGEMENT = "deneigement", "Déneigement manuel"
        PAYSAGEMENT = "paysagement", "Paysagement"
        AUTRE = "autre", "Autre travail"

    entreprise = models.ForeignKey("core.Entreprise", on_delete=models.PROTECT, related_name="jobs")
    client = models.ForeignKey("clients.Client", on_delete=models.PROTECT, related_name="jobs")
    adresse = models.ForeignKey("clients.Adresse", on_delete=models.PROTECT, related_name="jobs", null=True, blank=True)
    genre = models.CharField(max_length=12, choices=Genre.choices, default=Genre.DENEIGEMENT)
    depart_le = models.DateTimeField("départ", default=timezone.now)
    depart_position = gis.PointField(srid=4326, geography=True, null=True, blank=True)
    arrivee_le = models.DateTimeField("arrivée", null=True, blank=True)
    arrivee_position = gis.PointField(srid=4326, geography=True, null=True, blank=True)
    fin_le = models.DateTimeField("fin", null=True, blank=True)
    distance_km = models.DecimalField("distance estimée (km, aller)", max_digits=7, decimal_places=1, null=True, blank=True)
    note = models.CharField(max_length=300, blank=True)
    facture = models.ForeignKey("facturation.Facture", on_delete=models.SET_NULL, null=True, blank=True, related_name="jobs")
    par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    class Meta:
        verbose_name = "job à la pièce"
        verbose_name_plural = "jobs à la pièce"
        ordering = ["-depart_le"]

    def __str__(self):
        return f"{self.get_genre_display()} : {self.client} ({self.depart_le:%Y-%m-%d})"

    def clean(self):
        if self.client_id and self.client.entreprise_id != self.entreprise_id:
            raise ValidationError("Ce client n'est pas de cette entreprise.")
        if self.adresse_id and self.client_id and self.adresse.client_id != self.client_id:
            raise ValidationError("Cette adresse n'est pas celle de ce client.")

    @property
    def trajet_min(self):
        return round((self.arrivee_le - self.depart_le).total_seconds() / 60) if self.arrivee_le else None

    @property
    def sur_place_min(self):
        return round((self.fin_le - (self.arrivee_le or self.depart_le)).total_seconds() / 60) if self.fin_le else None
