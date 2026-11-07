from unittest import mock

from django.contrib.gis.geos import Point
from django.test import SimpleTestCase, TestCase

from clients import geocodage
from clients.models import Adresse, Client
from clients.tasks import geocoder_maintenant
from core.models import Entreprise

MAISON = [{"lat": "45.9502", "lon": "-74.1338", "addresstype": "place", "type": "house",
           "address": {"house_number": "120", "road": "Rue des Essais"}, "display_name": "120, Rue des Essais, Sainte-Adèle"}]
RUE = [{"lat": "45.9505", "lon": "-74.1330", "addresstype": "road", "type": "residential",
        "address": {"road": "Rue des Essais"}, "display_name": "Rue des Essais, Sainte-Adèle"}]
VILLE = [{"lat": "45.9500", "lon": "-74.1300", "addresstype": "town", "type": "administrative",
          "address": {"town": "Sainte-Adèle"}, "display_name": "Sainte-Adèle, Québec"}]


class GeocodageTests(SimpleTestCase):
    def test_adresse_exacte(self):
        with mock.patch.object(geocodage, "_requete", return_value=MAISON) as req:
            r = geocodage.geocoder("120, rue des Essais", "Sainte-Adèle")
        self.assertEqual((r.precision, r.latitude, r.longitude), ("adresse", 45.9502, -74.1338))
        params = req.call_args.args[0]
        self.assertEqual(params["street"], "120 rue des Essais")  # virgule retirée
        self.assertEqual(params["state"], "Québec")
        self.assertNotIn("nom", str(params).lower())  # jamais le nom du client

    def test_rue_seulement(self):
        with mock.patch.object(geocodage, "_requete", return_value=RUE):
            self.assertEqual(geocodage.geocoder("120 rue des Essais", "Sainte-Adèle").precision, "rue")

    def test_repli_sur_la_ville(self):
        with mock.patch.object(geocodage, "_requete", side_effect=[[], VILLE]) as req:
            r = geocodage.geocoder("9, rang Fictif", "Val-David")
        self.assertEqual(r.precision, "ville")
        self.assertEqual(req.call_count, 2)

    def test_introuvable(self):
        with mock.patch.object(geocodage, "_requete", return_value=[]):
            self.assertIsNone(geocodage.geocoder("1 rue X", "Nulle-Part"))


class GeocoderMaintenantTests(TestCase):
    def setUp(self):
        self.ent = Entreprise.objects.create(nom="E", slug="e", domaine="e.exemple.test")
        self.c = Client.objects.create(entreprise=self.ent, nom="Tremblay")

    def _adresse(self, **kw):
        return Adresse.objects.create(entreprise=self.ent, client=self.c, ligne1="120, rue des Essais", ville="Sainte-Adèle", **kw)

    def test_enregistre_la_position(self):
        a = self._adresse()
        with mock.patch.object(geocodage, "_requete", return_value=MAISON):
            geocoder_maintenant(a)
        a.refresh_from_db()
        self.assertEqual((a.position_source, a.position_precision), ("geocodage", "adresse"))
        self.assertAlmostEqual(a.latitude, 45.9502)
        self.assertFalse(a.position_a_verifier)

    def test_ville_seulement_a_verifier(self):
        a = self._adresse()
        with mock.patch.object(geocodage, "_requete", side_effect=[[], VILLE]):
            geocoder_maintenant(a)
        a.refresh_from_db()
        self.assertEqual(a.position_precision, "ville")
        self.assertTrue(a.position_a_verifier)

    def test_introuvable_a_verifier(self):
        a = self._adresse()
        with mock.patch.object(geocodage, "_requete", return_value=[]):
            geocoder_maintenant(a)
        a.refresh_from_db()
        self.assertIsNone(a.position)
        self.assertEqual(a.position_precision, "introuvable")
        self.assertTrue(a.position_a_verifier)

    def test_position_manuelle_jamais_ecrasee(self):
        a = self._adresse(position=Point(-74.0, 45.0, srid=4326), position_source="manuelle")
        with mock.patch.object(geocodage, "_requete", return_value=MAISON) as req:
            geocoder_maintenant(a)
        req.assert_not_called()
        a.refresh_from_db()
        self.assertAlmostEqual(a.latitude, 45.0)


class MiseEnFileTests(TestCase):
    """Le signal met l'adresse en file après la transaction, seulement quand il le faut."""

    def setUp(self):
        self.ent = Entreprise.objects.create(nom="E", slug="e", domaine="e.exemple.test")
        self.c = Client.objects.create(entreprise=self.ent, nom="Tremblay")

    def _en_file(self, fonction):
        with mock.patch("clients.tasks.geocoder_adresse.defer") as defer:
            with self.captureOnCommitCallbacks(execute=True):
                fonction()
        return defer.call_count

    def test_nouvelle_adresse(self):
        self.assertEqual(self._en_file(lambda: Adresse.objects.create(entreprise=self.ent, client=self.c, ligne1="1 rue A", ville="X")), 1)

    def test_nouvelle_adresse_avec_position_manuelle(self):
        self.assertEqual(self._en_file(lambda: Adresse.objects.create(
            entreprise=self.ent, client=self.c, ligne1="1 rue A", ville="X",
            position=Point(-74, 45, srid=4326), position_source="manuelle")), 0)

    def test_changement_de_rue_seulement(self):
        a = Adresse.objects.create(entreprise=self.ent, client=self.c, ligne1="1 rue A", ville="X",
                                   position=Point(-74, 45, srid=4326), position_source="geocodage")
        a.consignes = "Passer tôt"
        self.assertEqual(self._en_file(a.save), 0)  # rien d'important n'a changé
        a.ligne1 = "3 rue A"
        self.assertEqual(self._en_file(a.save), 1)

    def test_resultat_du_geocodage_ne_relance_pas(self):
        a = Adresse.objects.create(entreprise=self.ent, client=self.c, ligne1="1 rue A", ville="X")
        with mock.patch.object(geocodage, "_requete", return_value=MAISON):
            self.assertEqual(self._en_file(lambda: geocoder_maintenant(a)), 0)


SAINTE_ADELE = geocodage.Zone(45.9502, -74.1313, 8.0)
# Une « rue des Essais » qui existerait aussi à Montréal, à environ 70 km
MONTREAL = [{"lat": "45.5017", "lon": "-73.5673", "addresstype": "place", "type": "house",
             "address": {"house_number": "120"}, "display_name": "120, Rue des Essais, Montréal"}]


class ZoneTests(SimpleTestCase):
    def test_boite_et_distance(self):
        g, h, d, b = (float(x) for x in SAINTE_ADELE.boite().split(","))
        self.assertTrue(g < -74.1313 < d and b < 45.9502 < h)
        self.assertTrue(SAINTE_ADELE.contient(45.9655, -74.1100))       # Mont-Rolland
        self.assertFalse(SAINTE_ADELE.contient(45.5017, -73.5673))      # Montréal
        self.assertAlmostEqual(SAINTE_ADELE.distance_km(45.9502, -74.1313), 0)

    def test_recherche_limitee_a_la_zone(self):
        with mock.patch.object(geocodage, "_requete", return_value=MAISON) as req:
            r = geocodage.geocoder("120, rue des Essais", "Sainte-Adèle", zone=SAINTE_ADELE)
        self.assertEqual(r.precision, "adresse")
        params = req.call_args.args[0]
        self.assertEqual(params["bounded"], 1)
        self.assertIn("viewbox", params)

    def test_resultat_hors_zone_rejete(self):
        with mock.patch.object(geocodage, "_requete", return_value=MONTREAL) as req:
            r = geocodage.geocoder("120, rue des Essais", "Sainte-Adèle", zone=SAINTE_ADELE)
        self.assertEqual(r.precision, "ville")                 # repli sur le centre de la zone
        self.assertAlmostEqual(r.latitude, 45.9502)
        self.assertEqual(req.call_count, 1)                    # pas de deuxième requête pour la ville


class VilleDesservieTests(TestCase):
    def setUp(self):
        self.ent = Entreprise.objects.create(nom="E", slug="e", domaine="e.exemple.test")
        from core.models import VilleDesservie
        self.ville = VilleDesservie.objects.create(entreprise=self.ent, nom="Sainte-Adèle", centre=Point(-74.1313, 45.9502, srid=4326), par_defaut=True)

    def test_abreviation_ste(self):
        from core.models import VilleDesservie
        from core.texte import cle_ville
        self.assertEqual(cle_ville("Ste-Adèle"), cle_ville("SAINTE ADELE"))
        self.assertEqual(cle_ville("St-Sauveur"), "saint_sauveur")
        self.assertEqual(cle_ville("Stoneham"), "stoneham")    # « st » au début d'un mot n'est pas « saint »
        self.assertEqual(VilleDesservie.pour(self.ent.pk, "ste-adele"), self.ville)

    def test_une_seule_ville_par_defaut(self):
        from django.db import IntegrityError
        from core.models import VilleDesservie
        with self.assertRaises(IntegrityError):
            VilleDesservie.objects.create(entreprise=self.ent, nom="Piedmont", par_defaut=True)

    def test_tache_utilise_la_zone(self):
        c = Client.objects.create(entreprise=self.ent, nom="Tremblay")
        a = Adresse.objects.create(entreprise=self.ent, client=c, ligne1="120, rue des Essais", ville="Ste-Adèle")
        with mock.patch.object(geocodage, "_requete", return_value=MONTREAL):
            geocoder_maintenant(a)
        a.refresh_from_db()
        self.assertEqual(a.position_precision, "ville")
        self.assertTrue(a.position_a_verifier)
        self.assertAlmostEqual(a.latitude, 45.9502)            # pas à Montréal
