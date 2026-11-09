from unittest import mock

from django.contrib.gis.geos import Point
from django.test import TestCase, override_settings
from django.utils import timezone

from core import meteo
from core.models import Entreprise, Meteo, VilleDesservie

VILLES = {"features": [
    {"id": "qc-13", "geometry": {"coordinates": [-73.96, 45.82]}, "properties": {"name": {"fr": "Saint-Jérôme"}}},
    {"id": "qc-c3", "geometry": {"coordinates": [-73.92, 46.01]}, "properties": {"name": {"fr": "Saint-Sauveur"}}},
]}
VILLE = {"properties": {
    "url": {"fr": "https://meteo.gc.ca/fr/location/index.html?coords=46.01,-73.92"},
    "warnings": [{"event": [{"description": {"fr": "Avertissement de neige"}}]}],
    "forecastGroup": {"timestamp": {"fr": "2026-11-08T20:45:00Z"}, "forecasts": [
        {"period": {"textForecastName": {"fr": "Ce soir et cette nuit"}}, "textSummary": {"fr": "Neige. Accumulation de 15 cm."},
         "precipitation": {"accumulation": {"name": {"fr": "neige"}, "amount": {"value": {"fr": 15}}}}},
        {"period": {"textForecastName": {"fr": "Lundi"}}, "textSummary": {"fr": "Nuageux."}},
    ]}}}


@override_settings(METEO_API="https://api.exemple.test")
class MeteoTests(TestCase):
    def setUp(self):
        self.ent = Entreprise.objects.create(nom="E", slug="e-met", domaine="met.exemple.test")
        VilleDesservie.objects.create(entreprise=self.ent, nom="Sainte-Adèle", par_defaut=True, centre=Point(-74.13, 45.95, srid=4326))

    def test_ville_la_plus_proche_et_previsions(self):
        reponses = [VILLES, VILLE]
        with mock.patch("core.meteo._lire", side_effect=lambda *a, **k: reponses.pop(0)):
            m = meteo.relever(self.ent)
        self.assertEqual((m.ville_id, m.ville_nom, m.erreur), ("qc-c3", "Saint-Sauveur", ""))
        self.assertEqual(m.periodes[0]["neige_cm"], 15)
        self.assertIsNone(m.periodes[1]["neige_cm"])
        self.assertEqual(m.avertissements, ["Avertissement de neige"])

    def test_panne_garde_les_dernieres_previsions(self):
        Meteo.objects.create(entreprise=self.ent, ville_id="qc-c3", periodes=[{"nom": "Lundi"}], lue_le=timezone.now())
        with mock.patch("core.meteo._lire", side_effect=OSError("injoignable")):
            m = meteo.relever(self.ent)
        self.assertEqual(m.periodes, [{"nom": "Lundi"}])
        self.assertIn("injoignable", m.erreur)

    def test_affichage_sur_la_tournee(self):
        from django.contrib.auth import get_user_model
        from core.models import Membre
        p, *_ = meteo.analyser(VILLE["properties"])
        Meteo.objects.create(entreprise=self.ent, ville_nom="Saint-Sauveur", periodes=p, avertissements=["Avertissement de neige"],
                             lue_le=timezone.now())
        u = get_user_model().objects.create_user("l-met", password="x" * 12)
        Membre.objects.create(utilisateur=u, entreprise=self.ent, role="operateur")
        self.client.force_login(u)
        with override_settings(ALLOWED_HOSTS=["*"]):
            r = self.client.get("/tournee/", HTTP_HOST="met.exemple.test")
        self.assertContains(r, "Neige 15 cm")
        self.assertContains(r, "Avertissement de neige")
        self.assertContains(r, "Environnement et Changement climatique Canada")
