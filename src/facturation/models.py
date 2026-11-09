"""Volet argent (PRD sections B, C, D) : saisons, contrats, factures, paiements.

Règles comptables :
  - Une facture naît « brouillon » : modifiable, sans numéro. À l'émission,
    elle reçoit le prochain numéro de l'entreprise (séquentiel, sans trou) et
    une copie des taux et des numéros de taxes du moment. Ensuite, ses lignes et
    ses montants ne changent plus : on l'annule (le numéro reste utilisé), on ne
    l'efface pas.
  - Le solde d'une facture = total moins les paiements. « Payée » se déduit du
    solde, ce n'est pas un champ qu'on coche.
  - Les soldes d'ouverture (C6 : montants dus des saisons passées) sont des
    factures de genre « solde d'ouverture » : sans taxes (déjà facturées sur le
    papier), sans numéro de la série. Les paiements, les comptes à recevoir et
    les relances les traitent comme les autres factures.
  - V1 : pas de trop-perçu (un paiement ne dépasse pas le solde de sa facture;
    D7 est en V2).
"""
import secrets
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import F, Sum
from django.db.models.functions import Coalesce
from django.utils import timezone

from clients.models import Adresse, Client
from core.models import Entreprise, Horodate
from facturation.calculs import arrondir, repartir, taxes

ZERO = Decimal("0.00")


def _argent(nom, **kw):
    return models.DecimalField(nom, max_digits=10, decimal_places=2, **kw)


def _meme_entreprise(objet, *lies):
    """clean() : les objets liés doivent appartenir à l'entreprise de l'objet."""
    erreurs = {}
    for champ in lies:
        lie = getattr(objet, champ, None)
        if lie is not None and objet.entreprise_id and lie.entreprise_id != objet.entreprise_id:
            erreurs[champ] = "Appartient à une autre entreprise."
    if erreurs:
        raise ValidationError(erreurs)


class Saison(Horodate):
    """Saison d'hiver (B5), ex. « 2026-2027 »."""

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="saisons")
    nom = models.CharField(max_length=20, help_text="Ex. 2026-2027")
    debut = models.DateField("début")
    fin = models.DateField()

    class Meta:
        verbose_name = "saison"
        verbose_name_plural = "saisons"
        ordering = ["entreprise", "-debut"]
        constraints = [models.UniqueConstraint(fields=["entreprise", "nom"], name="saison_unique_par_entreprise")]

    def __str__(self):
        return self.nom

    def clean(self):
        if self.debut and self.fin and self.fin <= self.debut:
            raise ValidationError({"fin": "La fin doit venir après le début."})


class Service(Horodate):
    """Catalogue des services d'une entreprise (B4) : entrée, bordage, pelletage, abrasif, toiture…"""

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="services")
    nom = models.CharField(max_length=100)
    prix_suggere = _argent("prix suggéré", null=True, blank=True, help_text="Proposé quand on l'ajoute à une facture; modifiable chaque fois.")
    taxable = models.BooleanField(default=True)
    actif = models.BooleanField(default=True)
    ordre = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "service"
        verbose_name_plural = "services"
        ordering = ["entreprise", "ordre", "nom"]
        constraints = [models.UniqueConstraint(fields=["entreprise", "nom"], name="service_unique_par_entreprise")]

    def __str__(self):
        return self.nom


class Contrat(Horodate):
    """Entente avec un client pour une adresse et une saison (B1 à B4)."""

    class Type(models.TextChoices):
        SAISONNIER = "saisonnier", "Saisonnier (forfait)"
        AU_PASSAGE = "au_passage", "Au passage"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="contrats")
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="contrats")
    adresse = models.ForeignKey(Adresse, on_delete=models.PROTECT, related_name="contrats", null=True, blank=True)
    saison = models.ForeignKey(Saison, on_delete=models.PROTECT, related_name="contrats")
    type = models.CharField(max_length=12, choices=Type.choices, default=Type.SAISONNIER)
    prix = _argent("prix", validators=[MinValueValidator(0)],
                   help_text="Avant taxes. Saisonnier : prix de la saison. Au passage : prix d'un passage.")
    prix_texte = models.CharField("entente en mots", max_length=300, blank=True,
                                  help_text="Ce qui a été dit au client, ex. « 450 $ taxes incluses, payable en 2 fois ».")
    services = models.ManyToManyField(Service, blank=True, related_name="contrats", verbose_name="services inclus")
    actif = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "contrat"
        verbose_name_plural = "contrats"
        ordering = ["entreprise", "-saison__debut", "client__nom"]

    def __str__(self):
        return f"{self.client} : {self.saison} ({self.get_type_display().lower()})"

    def clean(self):
        _meme_entreprise(self, "client", "adresse", "saison")
        if self.adresse_id and self.client_id and self.adresse.client_id != self.client_id:
            raise ValidationError({"adresse": "Cette adresse n'est pas celle de ce client."})

    def creer_echeancier(self, dates):
        """Versements égaux du prix aux dates données (B3 : 1 à 4 versements). Remplace les versements pas encore facturés."""
        if self.type != self.Type.SAISONNIER:
            raise ValidationError("Seul un contrat saisonnier a un échéancier.")
        if self.versements.exclude(facture=None).exists():
            raise ValidationError("Des versements sont déjà facturés : modifier l'échéancier à la main.")
        dates = sorted(dates)
        with transaction.atomic():
            self.versements.all().delete()
            return [Versement.objects.create(contrat=self, rang=i, date_prevue=d, montant=m)
                    for i, (d, m) in enumerate(zip(dates, repartir(self.prix, len(dates))), start=1)]


class Versement(models.Model):
    """Un versement prévu au contrat (B3); facturé à sa date (C5)."""

    contrat = models.ForeignKey(Contrat, on_delete=models.CASCADE, related_name="versements")
    rang = models.PositiveSmallIntegerField()
    date_prevue = models.DateField("date prévue")
    montant = _argent("montant", help_text="Avant taxes.", validators=[MinValueValidator(0)])
    facture = models.OneToOneField("Facture", on_delete=models.SET_NULL, null=True, blank=True, related_name="versement")

    class Meta:
        verbose_name = "versement"
        verbose_name_plural = "versements"
        ordering = ["contrat", "rang"]
        constraints = [models.UniqueConstraint(fields=["contrat", "rang"], name="versement_rang_unique")]

    def __str__(self):
        return f"Versement {self.rang} de {self.contrat.versements.count()}, {self.date_prevue:%Y-%m-%d}"

    def facturer(self):
        """Crée la facture du versement (brouillon) et la lie au versement."""
        if self.facture_id:
            return self.facture
        c = self.contrat
        n = c.versements.count()
        with transaction.atomic():
            # Datée du jour où on la crée (jamais dans le futur), payable à la date prévue
            aujourdhui = timezone.localdate()
            f = Facture.objects.create(entreprise=c.entreprise, client=c.client, adresse=c.adresse, contrat=c,
                                       date_facture=aujourdhui, date_echeance=max(self.date_prevue, aujourdhui))
            desc = f"Déneigement, saison {c.saison}" + (f" : versement {self.rang} de {n}" if n > 1 else "")
            f.lignes.create(description=desc, quantite=1, prix_unitaire=self.montant)
            f.recalculer()
            self.facture = f
            self.save(update_fields=["facture"])
        return f


class FactureQuerySet(models.QuerySet):
    def avec_solde(self):
        """Annote montant_paye (somme des paiements) et solde_du (total moins montant_paye)."""
        return self.annotate(montant_paye=Coalesce(Sum("paiements__montant"), ZERO)).annotate(solde_du=F("total") - F("montant_paye"))

    def a_recevoir(self):
        """Émises (ou soldes d'ouverture), pas annulées, avec un solde à payer."""
        return self.filter(statut=Facture.Statut.EMISE).avec_solde().filter(solde_du__gt=0)


def _jeton():
    return secrets.token_urlsafe(24)


class Facture(Horodate):
    class Statut(models.TextChoices):
        BROUILLON = "brouillon", "Brouillon"
        EMISE = "emise", "Émise"
        ANNULEE = "annulee", "Annulée"

    class Genre(models.TextChoices):
        FACTURE = "facture", "Facture"
        SOLDE_OUVERTURE = "solde_ouverture", "Solde d'ouverture"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="factures")
    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="factures")
    adresse = models.ForeignKey(Adresse, on_delete=models.PROTECT, related_name="factures", null=True, blank=True)
    contrat = models.ForeignKey(Contrat, on_delete=models.PROTECT, related_name="factures", null=True, blank=True)
    genre = models.CharField(max_length=16, choices=Genre.choices, default=Genre.FACTURE)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.BROUILLON)
    numero = models.PositiveIntegerField("numéro", null=True, blank=True, help_text="Donné à l'émission.")
    date_facture = models.DateField("date de la facture", default=timezone.localdate)
    date_echeance = models.DateField("date d'échéance", null=True, blank=True)
    saison_origine = models.CharField("saison d'origine", max_length=20, blank=True, help_text="Solde d'ouverture : ex. « 2024-2025 ».")
    note = models.TextField("note sur la facture", blank=True, help_text="Imprimée sur la facture.")
    note_interne = models.TextField("note interne", blank=True, help_text="Jamais montrée au client.")

    # Taxes copiées de l'entreprise à l'émission (la facture garde ce qui était vrai ce jour-là)
    inscrit_taxes = models.BooleanField(default=False)
    taux_tps = models.DecimalField(max_digits=6, decimal_places=3, default=ZERO)
    taux_tvq = models.DecimalField(max_digits=6, decimal_places=3, default=ZERO)
    numero_tps = models.CharField(max_length=20, blank=True)
    numero_tvq = models.CharField(max_length=20, blank=True)

    sous_total = _argent("sous-total", default=ZERO)
    tps = _argent("TPS", default=ZERO)
    tvq = _argent("TVQ", default=ZERO)
    total = _argent("total", default=ZERO)

    emise_le = models.DateTimeField("émise le", null=True, blank=True)
    annulee_le = models.DateTimeField("annulée le", null=True, blank=True)
    raison_annulation = models.CharField("raison de l'annulation", max_length=200, blank=True)
    # Lien public de la facture (L1), difficile à deviner
    jeton = models.CharField(max_length=40, unique=True, default=_jeton, editable=False)
    consultee_le = models.DateTimeField("ouverte par le client le", null=True, blank=True,
                                        help_text="Première ouverture du lien public par quelqu'un qui n'est pas connecté.")

    objects = FactureQuerySet.as_manager()

    class Meta:
        verbose_name = "facture"
        verbose_name_plural = "factures"
        ordering = ["entreprise", "-date_facture", "-numero"]
        constraints = [
            models.UniqueConstraint(fields=["entreprise", "numero"], name="facture_numero_unique_par_entreprise"),
            models.CheckConstraint(condition=~models.Q(statut="emise", genre="facture", numero=None), name="facture_emise_a_un_numero"),
        ]
        indexes = [models.Index(fields=["entreprise", "statut"], name="facture_entreprise_statut")]

    def __str__(self):
        if self.genre == self.Genre.SOLDE_OUVERTURE:
            return f"Solde d'ouverture {self.saison_origine or ''} : {self.client}".replace("  ", " ")
        return f"Facture n° {self.numero}" if self.numero else f"Brouillon ({self.client})"

    def lien_public(self):
        """Lien à donner au client (L1) : voir la facture sans compte. Le jeton est la seule clé : ne pas l'afficher ailleurs."""
        return f"https://{self.entreprise.domaine}/f/{self.jeton}/"

    @property
    def modifiable(self):
        return self.statut == self.Statut.BROUILLON

    def clean(self):
        _meme_entreprise(self, "client", "adresse", "contrat")
        if self.adresse_id and self.client_id and self.adresse.client_id != self.client_id:
            raise ValidationError({"adresse": "Cette adresse n'est pas celle de ce client."})
        if self.contrat_id and self.client_id and self.contrat.client_id != self.client_id:
            raise ValidationError({"contrat": "Ce contrat n'est pas celui de ce client."})
        if self.date_echeance and self.date_echeance < self.date_facture:
            raise ValidationError({"date_echeance": "L'échéance ne peut pas précéder la date de la facture."})

    def recalculer(self):
        """Sous-total, taxes et total à partir des lignes (brouillon seulement)."""
        if not self.modifiable:
            raise ValidationError("Une facture émise ne change plus.")
        lignes = list(self.lignes.all())
        self.sous_total = arrondir(sum((l.montant for l in lignes), ZERO))
        if self.genre == self.Genre.FACTURE and self.entreprise.inscrit_taxes:
            taxable = sum((l.montant for l in lignes if l.taxable), ZERO)
            self.tps, self.tvq = taxes(taxable, self.entreprise.taux_tps, self.entreprise.taux_tvq)
        else:
            self.tps = self.tvq = ZERO
        self.total = self.sous_total + self.tps + self.tvq
        self.save(update_fields=["sous_total", "tps", "tvq", "total", "modifie_le"])

    def emettre(self):
        """Fige la facture : prochain numéro de l'entreprise, taxes du jour. Irréversible (on peut seulement l'annuler)."""
        with transaction.atomic():
            f = Facture.objects.select_for_update().get(pk=self.pk)
            if not f.modifiable:
                raise ValidationError("Cette facture est déjà émise ou annulée.")
            if not f.lignes.exists():
                raise ValidationError("Une facture sans ligne ne peut pas être émise.")
            ent = Entreprise.objects.select_for_update().get(pk=f.entreprise_id)
            f.entreprise = ent
            f.recalculer()
            if f.genre == self.Genre.FACTURE:
                f.numero = ent.prochain_numero_facture
                ent.prochain_numero_facture += 1
                ent.save(update_fields=["prochain_numero_facture"])
                f.inscrit_taxes = ent.inscrit_taxes
                if ent.inscrit_taxes:
                    f.taux_tps, f.taux_tvq = ent.taux_tps, ent.taux_tvq
                    f.numero_tps, f.numero_tvq = ent.numero_tps, ent.numero_tvq
            f.statut = self.Statut.EMISE
            f.emise_le = timezone.now()
            f.save()
        self.refresh_from_db()
        return self

    def annuler(self, raison):
        if self.statut != self.Statut.EMISE:
            raise ValidationError("Seule une facture émise s'annule (un brouillon se supprime).")
        if self.paiements.exists():
            raise ValidationError("Cette facture a des paiements : les retirer avant de l'annuler.")
        if not (raison or "").strip():
            raise ValidationError("Indiquer la raison de l'annulation.")
        self.statut, self.annulee_le, self.raison_annulation = self.Statut.ANNULEE, timezone.now(), raison.strip()
        self.save(update_fields=["statut", "annulee_le", "raison_annulation", "modifie_le"])

    def delete(self, *args, **kwargs):
        if not self.modifiable:
            raise ValidationError("Une facture émise ne s'efface pas : l'annuler.")
        return super().delete(*args, **kwargs)

    @property
    def paye(self):
        return self.paiements.aggregate(s=Sum("montant"))["s"] or ZERO

    @property
    def solde(self):
        return self.total - self.paye if self.statut == self.Statut.EMISE else ZERO

    @property
    def payee(self):
        return self.statut == self.Statut.EMISE and self.solde <= 0

    @classmethod
    def solde_ouverture(cls, client, montant, saison_origine="", note="", date_facture=None):
        """Crée et émet un solde d'ouverture (C6) : montant dû d'une saison passée, sans taxes."""
        with transaction.atomic():
            f = cls.objects.create(entreprise=client.entreprise, client=client, genre=cls.Genre.SOLDE_OUVERTURE,
                                   saison_origine=saison_origine, note_interne=note,
                                   date_facture=date_facture or timezone.localdate())
            f.lignes.create(description=f"Solde dû{', saison ' + saison_origine if saison_origine else ''}",
                            quantite=1, prix_unitaire=montant, taxable=False)
            return f.emettre()


class LigneFacture(models.Model):
    facture = models.ForeignKey(Facture, on_delete=models.CASCADE, related_name="lignes")
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.CharField(max_length=200)
    quantite = models.DecimalField("quantité", max_digits=8, decimal_places=2, default=Decimal("1"))
    prix_unitaire = _argent("prix unitaire")
    montant = _argent("montant", default=ZERO, editable=False)
    taxable = models.BooleanField(default=True)
    ordre = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "ligne de facture"
        verbose_name_plural = "lignes de facture"
        ordering = ["facture", "ordre", "pk"]

    def __str__(self):
        return self.description

    def _verifier_modifiable(self):
        if self.facture_id and not Facture.objects.get(pk=self.facture_id).modifiable:
            raise ValidationError("Une facture émise ne change plus.")

    def clean(self):
        if self.service_id and self.facture_id and self.service.entreprise_id != self.facture.entreprise_id:
            raise ValidationError({"service": "Appartient à une autre entreprise."})

    def save(self, *args, **kwargs):
        self._verifier_modifiable()
        self.quantite, self.prix_unitaire = Decimal(str(self.quantite)), Decimal(str(self.prix_unitaire))
        self.montant = arrondir(self.quantite * self.prix_unitaire)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._verifier_modifiable()
        return super().delete(*args, **kwargs)


class Paiement(Horodate):
    """Argent reçu pour une facture (D1 à D4). Le reçu au client (C13) viendra avec les envois."""

    class Mode(models.TextChoices):
        COMPTANT = "comptant", "Comptant"
        INTERAC = "interac", "Virement Interac"
        CHEQUE = "cheque", "Chèque"
        DEBIT = "debit", "Carte débit"
        CARTE = "carte", "Carte de crédit"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="paiements")
    facture = models.ForeignKey(Facture, on_delete=models.PROTECT, related_name="paiements")
    date = models.DateField(default=timezone.localdate)
    montant = _argent("montant", validators=[MinValueValidator(Decimal("0.01"))])
    mode = models.CharField(max_length=10, choices=Mode.choices)
    reference = models.CharField("référence", max_length=100, blank=True, help_text="N° de chèque, référence Interac, etc.")
    note = models.CharField(max_length=200, blank=True)
    recu_envoye_le = models.DateTimeField("reçu envoyé le", null=True, blank=True)

    class Meta:
        verbose_name = "paiement"
        verbose_name_plural = "paiements"
        ordering = ["entreprise", "-date", "-pk"]

    def __str__(self):
        return f"{self.montant} $ ({self.get_mode_display().lower()}), {self.date:%Y-%m-%d}"

    def clean(self):
        _meme_entreprise(self, "facture")
        if not self.facture_id:
            return
        f = self.facture
        if f.statut != Facture.Statut.EMISE:
            raise ValidationError({"facture": "On ne paie qu'une facture émise (pas un brouillon ni une facture annulée)."})
        deja = f.paiements.exclude(pk=self.pk).aggregate(s=Sum("montant"))["s"] or ZERO
        if self.montant is not None and self.montant > f.total - deja:
            raise ValidationError({"montant": f"Plus que le solde de la facture ({f.total - deja} $)."})


class VirementInterac(Horodate):
    """Avis de virement Interac reçu par courriel (PRD D5) : l'app propose la facture, Louis confirme
    d'une tape. Jamais enregistré tout seul (appariement semi-automatique, PRD section 6)."""

    class Statut(models.TextChoices):
        A_TRAITER = "a_traiter", "À confirmer"
        ENREGISTRE = "enregistre", "Enregistré"
        IGNORE = "ignore", "Ignoré"

    entreprise = models.ForeignKey(Entreprise, on_delete=models.PROTECT, related_name="virements")
    recu_le = models.DateTimeField("reçu le")
    montant = _argent("montant")
    envoyeur = models.CharField("envoyé par", max_length=150, blank=True)
    message_envoyeur = models.CharField("message de l'envoyeur", max_length=400, blank=True)
    reference = models.CharField("référence Interac", max_length=60, blank=True)
    courriel = models.ForeignKey("communications.Message", on_delete=models.SET_NULL, null=True, blank=True, related_name="virements")
    client = models.ForeignKey(Client, on_delete=models.SET_NULL, null=True, blank=True, related_name="virements",
                               help_text="Client proposé (ou choisi).")
    facture = models.ForeignKey(Facture, on_delete=models.SET_NULL, null=True, blank=True, related_name="virements",
                                help_text="Facture proposée (ou choisie).")
    raison = models.CharField("pourquoi cette facture", max_length=200, blank=True)
    statut = models.CharField(max_length=10, choices=Statut.choices, default=Statut.A_TRAITER)
    paiements = models.ManyToManyField(Paiement, blank=True, related_name="virements")

    class Meta:
        verbose_name = "virement Interac"
        verbose_name_plural = "virements Interac"
        ordering = ["-recu_le"]
        constraints = [models.UniqueConstraint(fields=["entreprise", "reference"], condition=~models.Q(reference=""),
                                               name="un_virement_par_reference")]

    def __str__(self):
        return f"{self.montant} $ de {self.envoyeur or '?'}"
