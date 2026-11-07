from datetime import date

from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.core.exceptions import ValidationError
from django.test import TestCase

from clients.models import Adresse, Client, Secteur
from core.models import Entreprise


def _entreprise(slug="essai"):
    return Entreprise.objects.create(nom=f"Déneigement {slug}", slug=slug, domaine=f"{slug}.exemple.test")


class ClientTests(TestCase):
    def setUp(self):
        self.ent = _entreprise()

    def test_normalisation_a_la_validation(self):
        c = Client(entreprise=self.ent, prenom="Ginette", nom="Tremblay", cellulaire="(450) 555-1234", courriel=" Ginette@Exemple.CA ")
        c.full_clean()
        self.assertEqual(c.cellulaire, "+14505551234")
        self.assertEqual(c.courriel, "ginette@exemple.ca")

    def test_cellulaire_invalide_refuse(self):
        c = Client(entreprise=self.ent, nom="Tremblay", cellulaire="555-1234")
        with self.assertRaises(ValidationError) as e:
            c.full_clean()
        self.assertIn("cellulaire", e.exception.message_dict)

    def test_nom_obligatoire(self):
        with self.assertRaises(ValidationError):
            Client(entreprise=self.ent).full_clean()

    def test_nom_affiche(self):
        self.assertEqual(Client(prenom="Ginette", nom="Tremblay").nom_affiche, "Ginette Tremblay")
        self.assertEqual(Client(organisation="Syndicat du 12", nom="Roy").nom_affiche, "Syndicat du 12 (Roy)")

    def test_consentement_exige_une_date(self):
        c = Client(entreprise=self.ent, nom="Roy", consentement_commercial=True)
        with self.assertRaises(ValidationError) as e:
            c.full_clean()
        self.assertIn("consentement_date", e.exception.message_dict)

    def test_desabonne_ne_recoit_plus_le_commercial(self):
        from django.utils import timezone
        c = Client(nom="Roy", consentement_commercial=True, consentement_date=date(2026, 11, 7))
        self.assertTrue(c.peut_recevoir_commercial)
        c.desabonne_le = timezone.now()
        self.assertFalse(c.peut_recevoir_commercial)


class AdresseTests(TestCase):
    def setUp(self):
        self.ent = _entreprise()
        self.client_ = Client.objects.create(entreprise=self.ent, nom="Tremblay")

    def test_code_postal_normalise(self):
        a = Adresse(entreprise=self.ent, client=self.client_, ligne1="123, rue Principale", ville="Sainte-Adèle", code_postal="j8b2x1")
        a.full_clean()
        self.assertEqual(a.code_postal, "J8B 2X1")

    def test_isolation_entre_entreprises(self):
        autre = _entreprise("autre")
        secteur_autre = Secteur.objects.create(entreprise=autre, nom="Nord")
        a = Adresse(entreprise=self.ent, client=self.client_, ligne1="1, rue A", ville="X", secteur=secteur_autre)
        with self.assertRaises(ValidationError):
            a.full_clean()
        a = Adresse(entreprise=autre, client=self.client_, ligne1="1, rue A", ville="X")
        with self.assertRaises(ValidationError):
            a.full_clean()

    def test_recherche_par_distance_postgis(self):
        # Deux adresses à Sainte-Adèle, une à Saint-Jérôme (environ 25 km)
        proche1 = Adresse.objects.create(entreprise=self.ent, client=self.client_, ligne1="1, rue A", ville="Sainte-Adèle", position=Point(-74.1340, 45.9500, srid=4326))
        proche2 = Adresse.objects.create(entreprise=self.ent, client=self.client_, ligne1="2, rue A", ville="Sainte-Adèle", position=Point(-74.1300, 45.9520, srid=4326))
        Adresse.objects.create(entreprise=self.ent, client=self.client_, ligne1="3, rue B", ville="Saint-Jérôme", position=Point(-74.0040, 45.7800, srid=4326))
        louis_est_ici = Point(-74.1335, 45.9505, srid=4326)
        a_moins_de_800_m = Adresse.objects.filter(position__dwithin=(louis_est_ici, D(m=800)))
        self.assertEqual(set(a_moins_de_800_m), {proche1, proche2})
        self.assertAlmostEqual(proche1.latitude, 45.95)


class DonneesEssaiTests(TestCase):
    def test_refuse_en_prod(self):
        from django.core.management import CommandError, call_command
        from django.test import override_settings
        with override_settings(LMAPP_ENV="prod"):
            with self.assertRaises(CommandError):
                call_command("donnees_essai", stdout=open("/dev/null", "w"))
        self.assertEqual(Entreprise.objects.count(), 0)

    def test_creation_puis_rien_en_double(self):
        from django.core.management import call_command
        from django.test import override_settings
        with override_settings(LMAPP_ENV="test"):
            call_command("donnees_essai", stdout=open("/dev/null", "w"))
            call_command("donnees_essai", stdout=open("/dev/null", "w"))
        self.assertEqual(Entreprise.objects.count(), 1)
        self.assertEqual(Client.objects.count(), 10)
        self.assertEqual(Adresse.objects.count(), 11)
        # Tous les cellulaires dans la plage fictive 555-01XX
        self.assertTrue(all(c.cellulaire.startswith("+1450555") and c.cellulaire[-4:-2] == "01" for c in Client.objects.all()))


class ReinitialiserTests(TestCase):
    def test_reinitialiser_n_efface_que_l_essai(self):
        from django.core.management import call_command
        from django.test import override_settings
        autre = _entreprise("autre")
        Client.objects.create(entreprise=autre, nom="Garder")
        with override_settings(LMAPP_ENV="test"):
            call_command("donnees_essai", stdout=open("/dev/null", "w"))
            call_command("donnees_essai", "--reinitialiser", stdout=open("/dev/null", "w"))
        self.assertEqual(Client.objects.filter(entreprise__slug="essai").count(), 10)
        self.assertTrue(Client.objects.filter(nom="Garder").exists())
        self.assertFalse(Adresse.objects.filter(entreprise__slug="essai").exclude(ville="Sainte-Adèle").exists())
