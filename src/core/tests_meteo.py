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
        patcher = mock.patch("core.meteo_point.relever_point")  # pas d'Internet pendant les tests
        patcher.start()
        self.addCleanup(patcher.stop)
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

    def test_choisir_la_ville_dans_l_app(self):
        from django.contrib.auth import get_user_model
        from core.models import Membre
        reponses = [VILLES, VILLE]
        with mock.patch("core.meteo._lire", side_effect=lambda *a, **k: reponses.pop(0)):
            m = meteo.relever(self.ent)
        self.assertEqual([v[1] for v in m.villes_proches], ["Saint-Sauveur", "Saint-Jérôme"])  # la plus proche d'abord
        u = get_user_model().objects.create_user("l-met2", password="x" * 12)
        Membre.objects.create(utilisateur=u, entreprise=self.ent, role="operateur")
        self.client.force_login(u)
        with override_settings(ALLOWED_HOSTS=["*"]):
            page = self.client.get("/plus/meteo/", HTTP_HOST="met.exemple.test")
            self.assertContains(page, "Saint-Jérôme")
            with mock.patch("core.tasks.relever_meteo_de.defer") as defer, self.captureOnCommitCallbacks(execute=True):
                r = self.client.post("/plus/meteo/", {"ville": "qc-13"}, HTTP_HOST="met.exemple.test", follow=True)
            self.assertContains(r, "prévisions de Saint-Jérôme")
            defer.assert_called_once_with(entreprise_id=self.ent.pk)
            self.assertContains(self.client.post("/plus/meteo/", {"ville": "qc-999"}, HTTP_HOST="met.exemple.test", follow=True),
                                "Choisir une ville de la liste")
        m.refresh_from_db()
        self.assertEqual((m.ville_id, m.ville_nom, m.ville_choisie, m.periodes), ("qc-13", "Saint-Jérôme", True, []))
        # La lecture suivante garde le choix
        with mock.patch("core.meteo._lire", return_value=VILLE):
            self.assertEqual(meteo.relever(self.ent).ville_id, "qc-13")


@override_settings(METEO_WMS="https://geo.exemple.test/geomet")
class MeteoAuPointTests(TestCase):
    """Prévision au point exact de la ville desservie (HRDPS, option 1 de JF)."""

    def test_tranches_de_six_heures(self):
        from datetime import datetime, timezone as tz

        from core import meteo_point

        # Accumulations depuis le début du modèle, aux heures 0, 6, 12... : 5 mm d'eau entre 0 et 6 h, dont 1 mm de pluie
        accum = {"HRDPS.CONTINENTAL_PR": [0, 5, 5, 7, 7, 7, 7], "HRDPS.CONTINENTAL_RN": [0, 1, 1, 1, 1, 1, 1],
                 "HRDPS.CONTINENTAL_FR": [0, 0, 0, 2, 2, 2, 2], "HRDPS.CONTINENTAL_TT": [-3, -5, -8, -1, 0, 2, 1]}
        compteur = {}

        def faux(couche, lat, lon, quand, reference=None):
            i = compteur.get(couche, 0)
            compteur[couche] = i + 1
            if couche == "HRDPS.CONTINENTAL_PR" and reference is None:  # première requête : l'exécution du modèle
                compteur[couche] = 0
            return float(accum[couche][compteur[couche] - 1 if reference else 0]), "2026-11-13T00:00:00Z"

        with mock.patch("core.meteo_point._valeur", side_effect=faux):
            tranches, ref = meteo_point.prevoir(45.95, -74.13, datetime(2026, 11, 13, 4, 30, tzinfo=tz.utc))
        self.assertEqual(ref, "2026-11-13T00:00:00Z")
        self.assertEqual(len(tranches), 6)
        self.assertEqual((tranches[0]["debut"], tranches[0]["fin"]), ("2026-11-13T05:00:00Z", "2026-11-13T11:00:00Z"))
        self.assertEqual((tranches[0]["neige_cm"], tranches[0]["pluie_mm"], tranches[0]["temp_min"], tranches[0]["temp_max"]), (4.0, 1.0, -5, -3))
        self.assertEqual((tranches[2]["neige_cm"], tranches[2]["verglas_mm"]), (0.0, 2.0))

    def test_carte_avec_la_prevision_au_point(self):
        from django.contrib.auth import get_user_model
        from core.models import Membre
        ent = Entreprise.objects.create(nom="E", slug="e-pt", domaine="pt.exemple.test")
        Meteo.objects.create(entreprise=ent, lue_le=timezone.now(), point_lieu="Sainte-Adèle", point=[
            {"debut": "2026-11-13T05:00:00Z", "fin": "2026-11-13T11:00:00Z", "neige_cm": 4.0, "pluie_mm": 0, "verglas_mm": 0, "temp_min": -5, "temp_max": -3},
            {"debut": "2026-11-13T11:00:00Z", "fin": "2026-11-13T17:00:00Z", "neige_cm": 2.5, "pluie_mm": 0, "verglas_mm": 1.0, "temp_min": -3, "temp_max": 0}])
        u = get_user_model().objects.create_user("l-pt", password="x" * 12)
        Membre.objects.create(utilisateur=u, entreprise=ent, role="operateur")
        self.client.force_login(u)
        with override_settings(ALLOWED_HOSTS=["*"]):
            r = self.client.get("/tournee/", HTTP_HOST="pt.exemple.test")
        self.assertContains(r, "24 h à Sainte-Adèle")
        self.assertContains(r, "neige 6.5 cm".replace(".", ","))
        self.assertContains(r, "verglas 1,0 mm")
