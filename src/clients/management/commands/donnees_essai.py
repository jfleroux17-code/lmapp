"""Crée une entreprise fictive et des clients inventés pour l'environnement de test.

Refuse de s'exécuter en prod (LMAPP_ENV=prod). Aucune donnée réelle :
  - cellulaires dans la plage 555-0100 à 555-0199, réservée à la fiction en
    Amérique du Nord (aucun texto ne peut aboutir chez quelqu'un);
  - courriels en @example.com (domaine réservé aux exemples);
  - rues inventées, positions approximatives dans de vraies villes.

Utilisation : docker compose run --rm app python manage.py donnees_essai
"""
from datetime import date, datetime
from decimal import Decimal

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from clients.models import Adresse, Client, Secteur
from core.models import Entreprise, VilleDesservie
from facturation.models import Contrat, Facture, Paiement, Saison, Service

ENTREPRISE = {
    "slug": "essai",
    "nom": "Déneigement Essai",
    "domaine": "test.ledeneigeur.com",
    "telephone": "450 555-0100",
    "courriel": "info@example.com",
    "ville": "Sainte-Adèle",
    "signature_messages": "Déneigement Essai",
    # Numéros de taxes fictifs (format seulement), numérotation à partir de 1001
    "inscrit_taxes": True,
    "numero_tps": "123456789 RT0001",
    "numero_tvq": "1234567890 TQ0001",
    "prochain_numero_facture": 1001,
    "interac_courriel": "paiement@example.com",
    "interac_instructions": "Virement Interac à paiement@example.com (dépôt automatique, aucune question). Indiquez votre numéro de facture.",
}

SECTEURS = [("Village", 1), ("Mont-Rolland", 2), ("Chantecler", 3)]

# Ville desservie et sa zone (centre approximatif de Sainte-Adèle, rayon 8 km)
VILLE = ("Sainte-Adèle", -74.1313, 45.9502, "8.0")

# (prénom, nom, organisation, cellulaire, courriel, statut, paiement, canal, consentement, désabonné, secteur, adresses)
# adresses : liste de (ligne1, ville, code postal, longitude, latitude, rang)
CLIENTS = [
    ("Ginette", "Tremblay", "", "450 555-0101", "ginette.tremblay@example.com", "actif", "comptant", "texto", True, False,
     "Village", [("120, rue des Essais", "Sainte-Adèle", "J8B 1A1", -74.1338, 45.9502, 1)]),
    ("Réjean", "Gagnon", "", "450 555-0102", "", "actif", "comptant", "texto", False, False,
     "Village", [("134, rue des Essais", "Sainte-Adèle", "J8B 1A1", -74.1329, 45.9508, 2)]),
    ("Sylvie", "Roy", "", "450 555-0103", "sylvie.roy@example.com", "actif", "interac", "les_deux", True, False,
     "Village", [("8, montée Fictive", "Sainte-Adèle", "J8B 1A2", -74.1302, 45.9531, 3)]),
    ("Marcel", "Côté", "", "450 555-0104", "marcel.cote@example.com", "recouvrement", "comptant", "texto", False, False,
     "Village", [("45, chemin de l'Exemple", "Sainte-Adèle", "J8B 1A3", -74.1275, 45.9550, 4)]),
    ("Nathalie", "Bouchard", "", "450 555-0105", "nathalie.bouchard@example.com", "actif", "interac", "courriel", True, True,
     "Mont-Rolland", [("210, rue du Modèle", "Sainte-Adèle", "J8B 1B1", -74.1100, 45.9655, 1)]),
    ("Pierre", "Lavoie", "", "450 555-0106", "pierre.lavoie@example.com", "actif", "cheque", "texto", False, False,
     "Mont-Rolland", [("17, rue du Modèle", "Sainte-Adèle", "J8B 1B1", -74.1085, 45.9662, 2)]),
    ("", "Fortin", "Syndicat de copropriété Les Sapins fictifs", "450 555-0107", "gestion.sapins@example.com", "actif", "interac", "courriel", False, False,
     "Mont-Rolland", [("300, boulevard Imaginaire", "Sainte-Adèle", "J8B 1B2", -74.1050, 45.9680, 3)]),
    ("Luc", "Pelletier", "", "450 555-0108", "luc.pelletier@example.com", "actif", "comptant", "texto", True, False,
     "Chantecler", [("2, rue de la Démo", "Sainte-Adèle", "J8B 1C1", -74.1620, 45.9405, 1),
                    ("4, rue de la Démo", "Sainte-Adèle", "J8B 1C1", -74.1616, 45.9408, 2)]),
    ("Francine", "Morin", "", "450 555-0109", "", "inactif", "comptant", "texto", False, False,
     "Chantecler", [("55, chemin du Test", "Sainte-Adèle", "J8B 1C2", -74.1680, 45.9370, 3)]),
    ("Gaston", "Bélanger", "", "450 555-0110", "", "liste_noire", "comptant", "texto", False, False,
     "Chantecler", [("9, rang Fictif", "Sainte-Adèle", "J8B 1C3", None, None, None)]),
]


class Command(BaseCommand):
    help = "Crée l'entreprise fictive « Déneigement Essai » et ses clients (environnement de test seulement)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reinitialiser", action="store_true",
            help="Effacer d'abord l'entreprise d'essai et toutes ses données (test seulement).",
        )

    def handle(self, *args, **options):
        if settings.LMAPP_ENV == "prod":
            raise CommandError("Refusé : LMAPP_ENV=prod. Les données d'essai ne vont jamais en prod.")

        with transaction.atomic():
            if options["reinitialiser"]:
                ancienne = Entreprise.objects.filter(slug=ENTREPRISE["slug"]).first()
                if ancienne is not None:
                    # Ordre imposé par les clés protégées : l'argent, puis adresses, clients, secteurs, l'entreprise
                    Paiement.objects.filter(entreprise=ancienne).delete()
                    Facture.objects.filter(entreprise=ancienne).delete()
                    Contrat.objects.filter(entreprise=ancienne).delete()
                    Service.objects.filter(entreprise=ancienne).delete()
                    Saison.objects.filter(entreprise=ancienne).delete()
                    Adresse.objects.filter(entreprise=ancienne).delete()
                    Client.objects.filter(entreprise=ancienne).delete()
                    Secteur.objects.filter(entreprise=ancienne).delete()
                    ancienne.delete()
                    self.stdout.write(f"Entreprise d'essai « {ancienne} » effacée.")
            ent, creee = Entreprise.objects.get_or_create(slug=ENTREPRISE["slug"], defaults=ENTREPRISE)
            if not creee:
                self.stdout.write(f"L'entreprise « {ent} » existe déjà : rien n'est ajouté.")
                return
            ent.full_clean()
            ent.save()

            nom_ville, lon, lat, rayon = VILLE
            VilleDesservie.objects.create(entreprise=ent, nom=nom_ville, centre=Point(lon, lat, srid=4326), rayon_km=Decimal(rayon), par_defaut=True)
            secteurs = {nom: Secteur.objects.create(entreprise=ent, nom=nom, ordre=o) for nom, o in SECTEURS}

            for (prenom, nom, org, cell, courriel, statut, paiement, canal, consent, desabonne, secteur, adresses) in CLIENTS:
                c = Client(
                    entreprise=ent, prenom=prenom, nom=nom, organisation=org,
                    cellulaire=cell, courriel=courriel, statut=statut,
                    mode_paiement=paiement, canal_prefere=canal,
                    consentement_commercial=consent,
                    consentement_date=date(2026, 10, 15) if consent else None,
                    consentement_source="import" if consent else "",
                    desabonne_le=timezone.make_aware(datetime(2026, 11, 2, 9, 30)) if desabonne else None,
                    notes="Client fictif (données d'essai).",
                )
                if org:
                    c.facturation_ligne1 = "C.P. 123, succursale Exemple"
                    c.facturation_ville = "Saint-Jérôme"
                    c.facturation_province = "QC"
                    c.facturation_code_postal = "J7Z 1A1"
                c.full_clean()
                c.save()
                for ligne1, ville, cp, lon, lat, rang in adresses:
                    a = Adresse(
                        entreprise=ent, client=c, secteur=secteurs[secteur],
                        ligne1=ligne1, ville=ville, code_postal=cp,
                        position=Point(lon, lat, srid=4326) if lon is not None else None,
                        position_source="manuelle" if lon is not None else "",
                        ordre_tournee=rang,
                    )
                    a.full_clean()
                    a.save()

            # Quelques particularités du terrain (A5)
            Adresse.objects.filter(entreprise=ent, ligne1="8, montée Fictive").update(
                entree_en_pente=True, ou_mettre_neige="À gauche de l'entrée, pas sur la haie",
            )
            Adresse.objects.filter(entreprise=ent, ligne1="300, boulevard Imaginaire").update(
                borne_fontaine=True, obstacles="Bordure de béton à droite", consignes="Stationnement de 12 places, passer avant 7 h.",
            )

            factures = self._argent(ent)

        self.stdout.write(self.style.SUCCESS(
            f"« {ent} » créée : ville desservie {nom_ville}, {len(secteurs)} secteurs, {Client.objects.filter(entreprise=ent).count()} clients, "
            f"{Adresse.objects.filter(entreprise=ent).count()} adresses, {factures}."
        ))

    def _argent(self, ent):
        """Saison, services, contrats à versements, factures, un paiement et un solde d'ouverture (fictifs)."""
        saison = Saison.objects.create(entreprise=ent, nom="2026-2027", debut=date(2026, 11, 1), fin=date(2027, 4, 15))
        services = {nom: Service.objects.create(entreprise=ent, nom=nom, prix_suggere=prix, ordre=o)
                    for o, (nom, prix) in enumerate([("Entrée", None), ("Bordage de la rue", Decimal("40")),
                                                     ("Pelletage du balcon", Decimal("25")), ("Abrasif", Decimal("15"))])}
        servis = Client.objects.filter(entreprise=ent, statut__in=["actif", "recouvrement"]).order_by("pk")
        for i, c in enumerate(servis[:4]):
            contrat = Contrat.objects.create(entreprise=ent, client=c, adresse=c.adresses.first(), saison=saison,
                                             prix=Decimal("450") + 50 * i, prix_texte="Prix de la saison, plus taxes, en 2 versements")
            contrat.services.add(services["Entrée"])
            v1, _ = contrat.creer_echeancier([date(2026, 11, 15), date(2027, 1, 15)])
            f = v1.facturer()
            f.emettre()
            if i == 0:
                Paiement.objects.create(entreprise=ent, facture=f, date=f.date_facture, montant=Decimal("100"), mode="comptant", note="Paiement partiel (essai)")
        extra = Facture.objects.create(entreprise=ent, client=servis[0], adresse=servis[0].adresses.first())
        extra.lignes.create(service=services["Pelletage du balcon"], description="Pelletage du balcon", quantite=2, prix_unitaire=Decimal("25"))
        extra.recalculer()  # laissée en brouillon
        recouvrement = Client.objects.filter(entreprise=ent, statut="recouvrement").first()
        if recouvrement:
            Facture.solde_ouverture(recouvrement, Decimal("380"), saison_origine="2025-2026", note="Solde fictif (essai)")
        return f"saison {saison}, {Facture.objects.filter(entreprise=ent).count()} factures (dont un brouillon et un solde d'ouverture)"
