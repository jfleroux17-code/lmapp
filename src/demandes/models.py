"""Demandes des clients (PRD H1, H2) : oubli, plainte, dommage, service, changement de contrat, report de
versement, nouveau client. Créées à la main par Louis, à partir d'un message reçu (texto, courriel), et
plus tard par l'assistant IA (O9) et le module voix (R). Suivi : ouverte, planifiée, réglée."""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from clients.models import Adresse, Client
from core.models import Entreprise, Horodate


class Demande(Horodate):
    class Genre(models.TextChoices):
        OUBLI = "oubli", "Oublié à la tournée"
        PLAINTE = "plainte", "Plainte"
        DOMMAGE = "dommage", "Dommage"
        SERVICE = "service", "Demande de service"
        CONTRAT = "contrat", "Changement au contrat"
        VERSEMENT = "versement", "Report de versement"
        FACTURE = "facture", "Demande de facture"
        NOUVEAU = "nouveau", "Nouveau client (prix demandé)"
        AUTRE = "autre", "Autre"

    class Statut(models.TextChoices):
        OUVERTE = "ouverte", "Ouverte"
        PLANIFIEE = "planifiee", "Planifiée"
        REGLEE = "reglee", "Réglée"

    class Source(models.TextChoices):
        MANUEL = "manuel", "Notée par le déneigeur"
        TEXTO = "texto", "Texto"
        COURRIEL = "courriel", "Courriel"
        APPEL = "appel", "Appel"

    URGENTS = [Genre.OUBLI, Genre.PLAINTE, Genre.DOMMAGE]

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="demandes")
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="demandes")
    adresse = models.ForeignKey(Adresse, on_delete=models.SET_NULL, null=True, blank=True, related_name="demandes")
    contact = models.CharField("personne à joindre", max_length=200, blank=True,
                               help_text="Nouveau client ou appelant inconnu : nom, téléphone, courriel.")
    genre = models.CharField(max_length=10, choices=Genre.choices, default=Genre.AUTRE)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.OUVERTE)
    urgent = models.BooleanField(default=False)
    description = models.TextField()
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUEL)
    message = models.ForeignKey("communications.Message", on_delete=models.SET_NULL, null=True, blank=True, related_name="demandes",
                                help_text="Le message reçu d'où vient la demande.")
    prevue_le = models.DateField("prévue le", null=True, blank=True)
    reglement = models.TextField("ce qui a été fait", blank=True)
    reglee_le = models.DateTimeField("réglée le", null=True, blank=True)

    class Meta:
        verbose_name = "demande"
        verbose_name_plural = "demandes"
        ordering = ["-cree_le"]
        indexes = [models.Index(fields=["entreprise", "statut", "-cree_le"], name="demande_a_traiter")]

    def __str__(self):
        return f"{self.get_genre_display()} : {self.client or self.contact or 'inconnu'}"

    def clean(self):
        for champ in ("client", "adresse"):
            obj = getattr(self, champ)
            if obj is not None and obj.entreprise_id != self.entreprise_id:
                raise ValidationError({champ: "Appartient à une autre entreprise."})
        if self.adresse_id and self.client_id and self.adresse.client_id != self.client_id:
            raise ValidationError({"adresse": "Cette adresse n'est pas celle de ce client."})

    def changer_statut(self, statut, reglement=""):
        self.statut = statut
        if statut == self.Statut.REGLEE:
            self.reglee_le = timezone.now()
            if reglement:
                self.reglement = reglement
        else:
            self.reglee_le = None
        self.save(update_fields=["statut", "reglee_le", "reglement", "modifie_le"])
