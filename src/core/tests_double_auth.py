"""Double authentification par Google Authenticator (TOTP), demande de JF du 12 novembre 2026."""
import re
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from core import double_auth as da
from core.models import DoubleAuthentification, Entreprise, Membre

HOTE = "louis.exemple.test"
MDP = "un mot de passe solide 123"


class TotpTests(TestCase):
    def test_vecteur_de_la_rfc_6238(self):
        secret = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # « 12345678901234567890 »
        self.assertEqual(da.code_pour(secret, 59), "287082")
        self.assertEqual(da.code_pour(secret, 1111111109), "081804")
        self.assertEqual(da.verifier_code(secret, "287 082", maintenant=59), 1)
        self.assertIsNone(da.verifier_code(secret, "287082", dernier_pas=1, maintenant=59))  # déjà utilisé
        self.assertEqual(da.verifier_code(secret, "287082", maintenant=59 + 30), 1)  # horloge décalée d'un pas
        self.assertIsNone(da.verifier_code(secret, "287082", maintenant=59 + 90))


@override_settings(ALLOWED_HOSTS=["*"], LMAPP_DOUBLE_AUTH_OBLIGATOIRE=True, LMAPP_HOTE_ADMIN="")
class ConnexionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE)
        U = get_user_model()
        cls.louis = U.objects.create_user("louis", password=MDP)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="admin")
        cls.employe = U.objects.create_user("employe", password=MDP)
        Membre.objects.create(utilisateur=cls.employe, entreprise=cls.ent, role="operateur")

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE

    def connexion(self, nom="louis"):
        return self.client.post("/connexion/", {"username": nom, "password": MDP})

    def activer(self):
        self.connexion()
        r = self.client.get("/")
        self.assertRedirects(r, "/double-authentification/?suivant=/", fetch_redirect_response=False)
        page = self.client.get("/double-authentification/?suivant=/")
        self.assertContains(page, "otpauth://totp/")
        self.assertContains(page, "<svg")
        secret = self.client.session[da.SESSION_SECRET_PROPOSE]
        r = self.client.post("/double-authentification/", {"action": "confirmer", "code": "000000", "suivant": "/"})
        self.assertContains(r, "Code refusé")
        r = self.client.post("/double-authentification/", {"action": "confirmer", "code": da.code_pour(secret), "suivant": "/"})
        self.assertContains(r, "Double authentification activée.")
        codes = re.findall(r"<li class=\"rounded-lg[^>]*>([a-z2-9]{5}-[a-z2-9]{5})</li>", r.content.decode())
        self.assertEqual(len(codes), 10)
        return secret, codes

    def test_administrateur_mene_a_l_activation_puis_code_a_chaque_connexion(self):
        secret, codes = self.activer()
        self.assertEqual(self.client.get("/").status_code, 200)  # activé : l'app s'ouvre
        da_obj = DoubleAuthentification.objects.get(utilisateur=self.louis)
        self.assertNotIn(codes[0], str(da_obj.codes_secours))  # seulement les empreintes
        # Nouvelle connexion : le mot de passe ne suffit plus
        self.client.post("/deconnexion/")
        self.connexion()
        self.assertRedirects(self.client.get("/clients/"), "/connexion/code/?suivant=/clients/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/plus/").status_code, 302)
        # Le code déjà utilisé à l'activation est refusé (même pas de 30 secondes); le suivant passe
        deja = DoubleAuthentification.objects.get(utilisateur=self.louis).dernier_pas
        r = self.client.post("/connexion/code/", {"code": da._code(secret, deja), "suivant": "/clients/"})
        self.assertContains(r, "Code refusé")
        import time
        plus_tard = (deja + 1) * da.PERIODE + 1  # le pas suivant celui déjà utilisé, quelle que soit l'heure du test
        with mock.patch("core.double_auth.time.time", return_value=plus_tard):
            r = self.client.post("/connexion/code/", {"code": da.code_pour(secret, plus_tard), "suivant": "/clients/"})
        self.assertRedirects(r, "/clients/", fetch_redirect_response=False)
        self.assertEqual(self.client.get("/").status_code, 200)
        # Code de secours : une seule fois
        self.client.post("/deconnexion/")
        self.connexion()
        self.assertRedirects(self.client.post("/connexion/code/", {"code": codes[0].upper()}), "/", fetch_redirect_response=False)
        self.client.post("/deconnexion/")
        self.connexion()
        self.assertContains(self.client.post("/connexion/code/", {"code": codes[0]}), "Code refusé")

    def test_cinq_codes_faux_deconnectent(self):
        self.activer()
        self.client.post("/deconnexion/")
        self.connexion()
        for _ in range(4):
            self.client.post("/connexion/code/", {"code": "123456"})
        r = self.client.post("/connexion/code/", {"code": "123456"})
        self.assertRedirects(r, "/connexion/", fetch_redirect_response=False)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_operateur_pas_oblige_mais_peut_activer(self):
        self.connexion("employe")
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertContains(self.client.get("/plus/"), "Double authentification")
        self.assertContains(self.client.get("/double-authentification/"), "otpauth://")

    def test_reinitialisee_par_un_administrateur(self):
        self.client.force_login(self.employe)
        secret = da.nouveau_secret()
        DoubleAuthentification.objects.create(utilisateur=self.employe, secret=secret)
        self.client.logout()
        self.client.force_login(self.louis)
        session = self.client.session
        session["double_auth_ok"] = True
        session.save()
        DoubleAuthentification.objects.create(utilisateur=self.louis, secret=da.nouveau_secret())
        membre = Membre.objects.get(utilisateur=self.employe)
        self.assertContains(self.client.get("/plus/reglages/utilisateurs/"), "Réinitialiser la double authentification")
        r = self.client.post(f"/plus/reglages/utilisateurs/{membre.pk}/", {"action": "double_auth"}, follow=True)
        self.assertContains(r, "Double authentification réinitialisée")
        self.assertFalse(DoubleAuthentification.objects.filter(utilisateur=self.employe).exists())

    def test_administration_de_jf(self):
        jf = get_user_model().objects.create_superuser("jf", password=MDP)
        self.client.force_login(jf)
        r = self.client.get("/admin/")
        self.assertRedirects(r, "/admin/double-authentification/?suivant=/admin/", fetch_redirect_response=False)
        self.assertContains(self.client.get("/admin/double-authentification/"), "otpauth://")
