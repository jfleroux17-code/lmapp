"""Crée une entreprise fictive et des clients inventés pour l'environnement de test.

Refuse de s'exécuter en prod (LMAPP_ENV=prod). Aucune donnée réelle :
  - cellulaires dans la plage 555-0100 à 555-0199, réservée à la fiction en
    Amérique du Nord (aucun texto ne peut aboutir chez quelqu'un);
  - courriels en @example.com (domaine réservé aux exemples);
  - rues inventées, positions approximatives dans de vraies villes.

Utilisation : docker compose run --rm app python manage.py donnees_essai
"""
from datetime import date, datetime

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from clients.models import Adresse, Client, Secteur
from core.models import Entreprise

ENTREPRISE = {
    "slug": "essai",
    "nom": "Déneigement Essai",
    "domaine": "test.ledeneigeur.com",
    "telephone": "450 555-0100",
    "courriel": "info@example.com",
    "ville": "Sainte-Adèle",
    "signature_messages": "Déneigement Essai",
    "interac_courriel": "paiement@example.com",
    "interac_instructions": "Virement Interac à paiement@example.com (dépôt automatique, aucune question). Indiquez votre numéro de facture.",
}

SECTEURS = [("Sainte-Adèle, village", 1), ("Mont-Rolland", 2), ("Val-David", 3)]

# (prénom, nom, organisation, cellulaire, courriel, statut, paiement, canal, consentement, désabonné, secteur, adresses)
# adresses : liste de (ligne1, ville, code postal, longitude, latitude, rang)
CLIENTS = [
    ("Ginette", "Tremblay", "", "450 555-0101", "ginette.tremblay@example.com", "actif", "comptant", "texto", True, False,
     "Sainte-Adèle, village", [("120, rue des Essais", "Sainte-Adèle", "J8B 1A1", -74.1338, 45.9502, 1)]),
    ("Réjean", "Gagnon", "", "450 555-0102", "", "actif", "comptant", "texto", False, False,
     "Sainte-Adèle, village", [("134, rue des Essais", "Sainte-Adèle", "J8B 1A1", -74.1329, 45.9508, 2)]),
    ("Sylvie", "Roy", "", "450 555-0103", "sylvie.roy@example.com", "actif", "interac", "les_deux", True, False,
     "Sainte-Adèle, village", [("8, montée Fictive", "Sainte-Adèle", "J8B 1A2", -74.1302, 45.9531, 3)]),
    ("Marcel", "Côté", "", "450 555-0104", "marcel.cote@example.com", "recouvrement", "comptant", "texto", False, False,
     "Sainte-Adèle, village", [("45, chemin de l'Exemple", "Sainte-Adèle", "J8B 1A3", -74.1275, 45.9550, 4)]),
    ("Nathalie", "Bouchard", "", "450 555-0105", "nathalie.bouchard@example.com", "actif", "interac", "courriel", True, True,
     "Mont-Rolland", [("210, rue du Modèle", "Sainte-Adèle", "J8B 1B1", -74.1100, 45.9655, 1)]),
    ("Pierre", "Lavoie", "", "450 555-0106", "pierre.lavoie@example.com", "actif", "cheque", "texto", False, False,
     "Mont-Rolland", [("17, rue du Modèle", "Sainte-Adèle", "J8B 1B1", -74.1085, 45.9662, 2)]),
    ("", "Fortin", "Syndicat de copropriété Les Sapins fictifs", "450 555-0107", "gestion.sapins@example.com", "actif", "interac", "courriel", False, False,
     "Mont-Rolland", [("300, boulevard Imaginaire", "Sainte-Adèle", "J8B 1B2", -74.1050, 45.9680, 3)]),
    ("Luc", "Pelletier", "", "450 555-0108", "luc.pelletier@example.com", "actif", "comptant", "texto", True, False,
     "Val-David", [("2, rue de la Démo", "Val-David", "J0T 2N0", -74.2070, 46.0300, 1),
                   ("4, rue de la Démo", "Val-David", "J0T 2N0", -74.2066, 46.0303, 2)]),
    ("Francine", "Morin", "", "450 555-0109", "", "inactif", "comptant", "texto", False, False,
     "Val-David", [("55, chemin du Test", "Val-David", "J0T 2N0", -74.2120, 46.0350, 3)]),
    ("Gaston", "Bélanger", "", "450 555-0110", "", "liste_noire", "comptant", "texto", False, False,
     "Val-David", [("9, rang Fictif", "Val-David", "J0T 2N0", None, None, None)]),
]


class Command(BaseCommand):
    help = "Crée l'entreprise fictive « Déneigement Essai » et ses clients (environnement de test seulement)."

    def handle(self, *args, **options):
        if settings.LMAPP_ENV == "prod":
            raise CommandError("Refusé : LMAPP_ENV=prod. Les données d'essai ne vont jamais en prod.")

        with transaction.atomic():
            ent, creee = Entreprise.objects.get_or_create(slug=ENTREPRISE["slug"], defaults=ENTREPRISE)
            if not creee:
                self.stdout.write(f"L'entreprise « {ent} » existe déjà : rien n'est ajouté.")
                return
            ent.full_clean()
            ent.save()

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

        self.stdout.write(self.style.SUCCESS(
            f"« {ent} » créée : {len(secteurs)} secteurs, {Client.objects.filter(entreprise=ent).count()} clients, "
            f"{Adresse.objects.filter(entreprise=ent).count()} adresses."
        ))
