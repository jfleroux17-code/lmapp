"""Messages aux clients (PRD section E, G) et gabarits modifiables (E9).

Tant qu'aucun fournisseur n'est configuré (Twilio, SMTP2GO), un message est
« préparé » et rien ne part. Hors prod, un envoi réel ne vise que les
destinataires permis (LMAPP_DESTINATAIRES_TEST), tous les autres sont bloqués.
"""
from django.db import models

from clients.models import Client
from core.models import Entreprise, Horodate


class Genre(models.TextChoices):
    DEBUT = "debut", "Début d'opération"
    PROXIMITE = "proximite", "Avis de proximité"
    PASSAGE_FAIT = "passage_fait", "Passage terminé"
    MANUEL = "manuel", "Message manuel"
    FACTURE = "facture", "Facture"
    RELANCE_1 = "relance_1", "Rappel"
    RELANCE_2 = "relance_2", "Deuxième avis"
    RELANCE_3 = "relance_3", "Dernier avis"


RELANCES = [Genre.RELANCE_1, Genre.RELANCE_2, Genre.RELANCE_3]


# Textes par défaut, sans nom de déneigeur (CLAUDE.md, règle 7) : la signature de
# l'entreprise est ajoutée à la fin de chaque message (identification exigée par la LCAP).
GABARITS_PAR_DEFAUT = {
    Genre.DEBUT: "Bonjour, les opérations de déneigement commencent. Les passages se font dans l'ordre habituel de la tournée.",
    Genre.PROXIMITE: "Bonjour, on arrive au {adresse} d'ici environ {minutes} minutes.",
    Genre.PASSAGE_FAIT: "Bonjour, le déneigement au {adresse} est fait ({heure}).",
    # Relances (C8) : ton gradué, sans menace que Louis n'aurait pas décidée (modifiables dans l'administration)
    Genre.RELANCE_1: "Bonjour {client}, petit rappel : votre compte montre un solde de {montant} ({factures}). {paiement}",
    Genre.RELANCE_2: "Bonjour {client}, deuxième avis : le solde de {montant} ({factures}) est impayé depuis le {depuis}. Merci de le régler dès que possible. {paiement}",
    Genre.RELANCE_3: "Bonjour {client}, dernier avis : le solde de {montant} ({factures}) est impayé depuis le {depuis}. Merci de le régler sans tarder, ou de nous appeler si le paiement pose problème. {paiement}",
}
VARIABLES = "{adresse}, {minutes}, {heure}, {client}; relances : {montant}, {factures}, {depuis}, {paiement}"


class Gabarit(Horodate):
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, related_name="gabarits")
    genre = models.CharField(max_length=15, choices=Genre.choices)
    texte = models.TextField(help_text=f"Variables : {VARIABLES}. La signature de l'entreprise est ajoutée à la fin.")

    class Meta:
        verbose_name = "gabarit de message"
        verbose_name_plural = "gabarits de messages"
        constraints = [models.UniqueConstraint(fields=["entreprise", "genre"], name="un_gabarit_par_genre")]

    def __str__(self):
        return self.get_genre_display()

    @classmethod
    def texte_pour(cls, entreprise, genre):
        g = cls.objects.filter(entreprise=entreprise, genre=genre).first()
        return g.texte if g else GABARITS_PAR_DEFAUT.get(genre, "")


class Message(Horodate):
    class Canal(models.TextChoices):
        TEXTO = "texto", "Texto"
        COURRIEL = "courriel", "Courriel"

    class Statut(models.TextChoices):
        PREPARE = "prepare", "Préparé, pas envoyé"
        EN_FILE = "en_file", "En file d'envoi"
        ENVOYE = "envoye", "Envoyé"
        ECHEC = "echec", "Échec"
        BLOQUE = "bloque", "Bloqué (environnement de test, destinataire non permis)"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="messages")
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages")
    operation = models.ForeignKey("tournee.Operation", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages")
    genre = models.CharField(max_length=15, choices=Genre.choices)
    canal = models.CharField(max_length=10, choices=Canal.choices)
    destinataire = models.CharField(max_length=254)
    sujet = models.CharField(max_length=200, blank=True, help_text="Courriels seulement.")
    contenu = models.TextField()
    facture = models.ForeignKey("facturation.Facture", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages",
                                help_text="Courriel : PDF de la facture joint.")
    factures_jointes = models.ManyToManyField("facturation.Facture", blank=True, related_name="relances",
                                              help_text="Relance par courriel : PDF de chaque facture jointe.")
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.PREPARE)
    envoye_le = models.DateTimeField(null=True, blank=True)
    erreur = models.CharField(max_length=300, blank=True)
    fournisseur_id = models.CharField("identifiant chez le fournisseur", max_length=64, blank=True)

    class Meta:
        verbose_name = "message"
        verbose_name_plural = "messages"
        ordering = ["-cree_le"]
        constraints = [
            # G3 : un seul avis de chaque genre par client et par opération
            models.UniqueConstraint(fields=["operation", "client", "genre"], condition=models.Q(genre__in=["debut", "proximite", "passage_fait"]),
                                    name="un_avis_par_client_et_operation"),
        ]
        indexes = [models.Index(fields=["entreprise", "-cree_le"], name="message_entreprise_date")]

    def __str__(self):
        return f"{self.get_genre_display()} à {self.client or self.destinataire}"
