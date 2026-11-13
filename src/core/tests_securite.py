"""Audit de sécurité, points 5, 9 et 10 (go de JF, 13 novembre 2026)."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core.models import DoubleAuthentification, Entreprise, Membre

HOTE = "louis.exemple.test"
MDP = "un mot de passe solide 123"


@override_settings(ALLOWED_HOSTS=["*"], LMAPP_HOTE_ADMIN="", LMAPP_DOUBLE_AUTH_OBLIGATOIRE=False)
class SecuriteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE)
        U = get_user_model()
        cls.louis = U.objects.create_user("louis", password=MDP)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")
        cls.jf = U.objects.create_superuser("jf", password=MDP)

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE

    def test_session_courte_pour_l_administration_longue_pour_le_terrain(self):
        with mock.patch("core.securite.alerter") as alerte:
            self.client.post("/connexion/", {"username": "louis", "password": MDP})
            self.assertEqual(self.client.session.get_expiry_age(), 60 * 60 * 24 * 90)
            alerte.assert_not_called()
            self.client.logout()
            self.client.post("/admin/login/", {"username": "jf", "password": MDP})
            self.assertEqual(self.client.session.get_expiry_age(), 12 * 3600)
        self.assertIn("Connexion à l'administration : jf", alerte.call_args.args[0])

    def test_deconnecter_mes_autres_appareils(self):
        from django.test import Client
        autre = Client(HTTP_HOST=HOTE)
        autre.post("/connexion/", {"username": "louis", "password": MDP})
        self.assertEqual(autre.get("/").status_code, 200)
        self.client.post("/connexion/", {"username": "louis", "password": MDP})
        r = self.client.post("/plus/deconnecter-autres/", follow=True)
        self.assertContains(r, "1 autre appareil déconnecté.")
        self.assertEqual(autre.get("/").status_code, 302)  # renvoyé à la connexion
        self.assertEqual(self.client.get("/").status_code, 200)  # celui-ci reste connecté

    @override_settings(LMAPP_CONNEXION_MAX_IP=3, LMAPP_CONNEXION_MAX_COMPTE=50)
    def test_alerte_quand_un_blocage_commence(self):
        with mock.patch("core.securite.alerter") as alerte:
            for _ in range(4):
                self.client.post("/connexion/", {"username": "louis", "password": "mauvais"})
        self.assertEqual(alerte.call_count, 1)
        self.assertIn("3 échecs depuis la même adresse IP", alerte.call_args.args[0])

    def test_alertes_double_auth_et_nouvel_administrateur(self):
        with mock.patch("core.securite.alerter") as alerte:
            da = DoubleAuthentification.objects.create(utilisateur=self.louis, secret="X")
            da.delete()
            m = Membre.objects.get(utilisateur=self.louis)
            m.role = "admin"
            m.save()
            m.save()  # déjà administrateur : pas de deuxième alerte
        sujets = [c.args[0] for c in alerte.call_args_list]
        self.assertEqual(sujets, ["Double authentification activée : louis", "Double authentification réinitialisée : louis",
                                  "Nouvel administrateur : louis (Essai)"])

    def test_mots_de_passe_en_argon2(self):
        self.assertTrue(get_user_model().objects.get(username="louis").password.startswith("argon2"))
