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
    RECU = "recu", "Message reçu"
    INTERAC = "interac", "Avis de virement Interac"
    RECU_PAIEMENT = "recu_paiement", "Reçu de paiement"
    GROUPE_SERVICE = "groupe_service", "Avis à plusieurs clients"
    GROUPE_COMMERCIAL = "groupe_comm", "Message commercial"
    CONTRAT = "contrat", "Contrat"
    APPEL = "appel", "Appel noté"


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
    # Reçu de paiement (C13)
    Genre.RECU_PAIEMENT: "Bonjour {client}, nous avons bien reçu votre paiement de {montant} ({mode}) le {date}, pour {factures}. {solde} Merci!",
}
VARIABLES = ("{adresse}, {minutes}, {heure}, {client}; relances : {montant}, {factures}, {depuis}, {paiement}; "
             "reçu : {montant}, {mode}, {date}, {factures}, {solde}")


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
        APPEL = "appel", "Appel"  # noté à la main par le déneigeur (E6), rien n'est envoyé

    class Statut(models.TextChoices):
        PREPARE = "prepare", "Préparé, pas envoyé"
        EN_FILE = "en_file", "En file d'envoi"
        ENVOYE = "envoye", "Envoyé"
        ECHEC = "echec", "Échec"
        BLOQUE = "bloque", "Bloqué (environnement de test, destinataire non permis)"
        RECU = "recu", "Reçu"

    class Sens(models.TextChoices):
        SORTANT = "sortant", "Envoyé par l'app"
        ENTRANT = "entrant", "Reçu"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="messages")
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="messages")
    operation = models.ForeignKey("tournee.Operation", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages")
    genre = models.CharField(max_length=15, choices=Genre.choices)
    canal = models.CharField(max_length=10, choices=Canal.choices)
    sens = models.CharField(max_length=7, choices=Sens.choices, default=Sens.SORTANT)
    destinataire = models.CharField(max_length=254, blank=True)
    expediteur = models.CharField("expéditeur", max_length=254, blank=True, help_text="Messages reçus.")
    lu = models.BooleanField(default=True, help_text="Messages reçus : faux tant que Louis ne l'a pas ouvert.")
    reponse_a = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="reponses",
                                  help_text="Message de l'app auquel ce message répond.")
    message_id_externe = models.CharField(max_length=300, blank=True, help_text="Message-ID d'un courriel reçu (doublons).")
    sujet = models.CharField(max_length=200, blank=True, help_text="Courriels seulement.")
    contenu = models.TextField()
    facture = models.ForeignKey("facturation.Facture", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages",
                                help_text="Courriel : PDF de la facture joint.")
    contrat = models.ForeignKey("facturation.Contrat", on_delete=models.SET_NULL, null=True, blank=True, related_name="messages",
                                help_text="Courriel : PDF du contrat joint (B6).")
    factures_jointes = models.ManyToManyField("facturation.Facture", blank=True, related_name="relances",
                                              help_text="Relance par courriel : PDF de chaque facture jointe.")
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.PREPARE)
    envoye_le = models.DateTimeField(null=True, blank=True)
    erreur = models.CharField(max_length=300, blank=True)
    fournisseur_id = models.CharField("identifiant chez le fournisseur", max_length=64, blank=True)
    segments = models.PositiveSmallIntegerField(default=0, help_text="Textos : segments facturés par Twilio.")
    livre_le = models.DateTimeField("livré le", null=True, blank=True, help_text="Textos : livraison confirmée par l'opérateur (E13).")
    cout = models.DecimalField("coût", max_digits=8, decimal_places=5, null=True, blank=True,
                               help_text="Textos : prix facturé par Twilio, relevé après l'envoi (E13).")
    cout_devise = models.CharField(max_length=3, blank=True)

    class Meta:
        verbose_name = "message"
        verbose_name_plural = "messages"
        ordering = ["-cree_le"]
        constraints = [
            # G3 : un seul avis de chaque genre par client et par opération
            models.UniqueConstraint(fields=["operation", "client", "genre"], condition=models.Q(genre__in=["debut", "proximite", "passage_fait"]),
                                    name="un_avis_par_client_et_operation"),
            # E5 : un courriel reçu n'est enregistré qu'une fois
            models.UniqueConstraint(fields=["entreprise", "message_id_externe"], condition=~models.Q(message_id_externe=""),
                                    name="un_courriel_recu_une_fois"),
        ]
        indexes = [models.Index(fields=["entreprise", "-cree_le"], name="message_entreprise_date"),
                   models.Index(fields=["entreprise", "sens", "lu"], name="message_non_lus")]

    def save(self, *args, **kwargs):
        if self.canal == self.Canal.TEXTO and not self.segments:
            from communications.segments import compter

            self.segments = compter(self.contenu)
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = list(kwargs["update_fields"]) + ["segments"]
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.get_genre_display()} à {self.client or self.destinataire}"


class EtatBoite(models.Model):
    """Où en est la lecture d'un dossier IMAP d'une entreprise (E5) : dernier UID archivé et traité.
    Les courriels jusqu'à `uid_depart` (déjà là à la première lecture) sont archivés sans être traités."""
    entreprise = models.ForeignKey(Entreprise, on_delete=models.CASCADE, related_name="etats_boite")
    dossier = models.CharField(max_length=100, default="INBOX")
    uidvalidite = models.BigIntegerField(default=0)
    uid_depart = models.BigIntegerField(default=0)
    dernier_uid = models.BigIntegerField(default=0)
    lue_le = models.DateTimeField(null=True, blank=True)
    erreur = models.CharField(max_length=300, blank=True)
    quota_utilise_ko = models.PositiveBigIntegerField("espace utilisé (Ko)", null=True, blank=True)
    quota_max_ko = models.PositiveBigIntegerField("espace permis (Ko)", null=True, blank=True)

    class Meta:
        verbose_name = "état de la boîte courriel"
        verbose_name_plural = "états de la boîte courriel"
        constraints = [models.UniqueConstraint(fields=["entreprise", "dossier"], name="un_etat_par_dossier")]

    def __str__(self):
        return f"{self.dossier} de {self.entreprise}"


class ArchiveCourriel(models.Model):
    """Copie intégrale (compressée) d'un courriel de la boîte, gardée avant de l'effacer du serveur.

    Les boîtes de ledeneigeur.com sont limitées à 2 Go : l'app archive chaque courriel reçu ou envoyé,
    puis l'efface de la boîte après COURRIEL_GARDER_JOURS jours. L'archive est la seule copie ensuite :
    elle est dans la base, donc dans les sauvegardes."""
    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="archives_courriel")
    dossier = models.CharField(max_length=100)
    uidvalidite = models.BigIntegerField()
    uid = models.BigIntegerField()
    entete_message_id = models.CharField("Message-ID", max_length=300, blank=True)
    expediteur = models.CharField("expéditeur", max_length=254, blank=True)
    destinataires = models.CharField(max_length=500, blank=True)
    sujet = models.CharField(max_length=200, blank=True)
    date = models.DateTimeField(null=True, blank=True)
    taille = models.PositiveIntegerField(help_text="Octets, avant compression.")
    empreinte = models.CharField("SHA-256", max_length=64)
    brut = models.BinaryField(help_text="Courriel complet (RFC 822), compressé (zlib).")
    message = models.ForeignKey(Message, on_delete=models.SET_NULL, null=True, blank=True, related_name="archives")
    archive_le = models.DateTimeField(auto_now_add=True)
    efface_le = models.DateTimeField("effacé de la boîte le", null=True, blank=True)

    class Meta:
        verbose_name = "courriel archivé"
        verbose_name_plural = "courriels archivés"
        ordering = ["-archive_le"]
        constraints = [models.UniqueConstraint(fields=["entreprise", "dossier", "uidvalidite", "uid"], name="un_courriel_archive_une_fois")]
        indexes = [models.Index(fields=["entreprise", "dossier", "efface_le", "archive_le"], name="archive_a_effacer")]

    def __str__(self):
        return self.sujet or self.entete_message_id

    def octets(self):
        """Le courriel d'origine, vérifié par son empreinte."""
        import hashlib
        import zlib

        o = zlib.decompress(bytes(self.brut))
        if hashlib.sha256(o).hexdigest() != self.empreinte:
            raise ValueError(f"Archive {self.pk} abîmée (empreinte différente).")
        return o
