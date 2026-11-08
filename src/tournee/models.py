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

    @classmethod
    def en_cours_de(cls, entreprise):
        return cls.objects.filter(entreprise=entreprise, fin=None).first()


def arrets(entreprise):
    """Les adresses de la tournée, dans l'ordre habituel de Louis (F1, F2) : clients servis
    (actifs et en recouvrement), secteur par secteur, puis le rang; sans rang à la fin."""
    return (Adresse.objects.filter(entreprise=entreprise, active=True,
                                   client__statut__in=[Client.Statut.ACTIF, Client.Statut.RECOUVREMENT])
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
    """Position du cellulaire pendant une opération (G1), envoyée par l'écran de tournée ouvert."""

    operation = models.ForeignKey(Operation, on_delete=models.CASCADE, related_name="positions")
    moment = models.DateTimeField(default=timezone.now)
    position = gis.PointField(srid=4326, geography=True)
    precision_m = models.PositiveIntegerField("précision (m)", null=True, blank=True)

    class Meta:
        verbose_name = "position GPS"
        verbose_name_plural = "positions GPS"
        ordering = ["-moment"]
        indexes = [models.Index(fields=["operation", "-moment"], name="position_operation_moment")]
