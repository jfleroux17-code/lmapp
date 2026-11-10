from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from clients.models import Client
from core.models import Entreprise


@override_settings(ALLOWED_HOSTS=["*"])
class AdminAuditUxTests(TestCase):
    """Audit UX : bandeaux, titres en français, pas de suppression d'un clic, état vide."""

    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine="essai.test")
        cls.jf = get_user_model().objects.create_superuser("jf", password="x" * 12)

    def setUp(self):
        self.client.force_login(self.jf)

    def test_bandeaux_et_cartes(self):
        page = self.client.get("/admin/")
        self.assertContains(page, "ENVIRONNEMENT DE TEST")
        self.assertContains(page, "Essai : <span class=\"envois-simulation\">Simulation</span>", html=False)
        self.assertContains(page, "Envois en échec (7 jours)")
        with override_settings(LMAPP_ENV="prod"):
            self.assertContains(self.client.get("/admin/"), "PRODUCTION : vraies données")
        Entreprise.objects.filter(pk=self.ent.pk).update(envois_actifs=True)
        self.assertContains(self.client.get("/admin/"), "Envois réels ACTIVÉS")

    def test_titres_en_francais(self):
        liste = self.client.get("/admin/clients/client/")
        self.assertContains(liste, "<h1>Clients</h1>", html=False)
        self.assertNotContains(liste, "Sélectionnez l")
        self.assertContains(liste, "Aucun client pour l&#x27;instant")
        fiche = self.client.get(f"/admin/core/entreprise/{self.ent.pk}/change/")
        self.assertContains(fiche, "Modifier : entreprise")
        self.assertNotContains(fiche, "(B3")

    def test_pas_de_suppression_d_un_clic(self):
        c = Client.objects.create(entreprise=self.ent, nom="Tremblay")
        self.assertEqual(self.client.get(f"/admin/clients/client/{c.pk}/delete/").status_code, 403)
        self.assertEqual(self.client.get(f"/admin/core/entreprise/{self.ent.pk}/delete/").status_code, 403)
        self.assertNotContains(self.client.get("/admin/clients/client/"), 'value="delete_selected"')
        self.assertContains(self.client.get("/admin/clients/client/"), "Marquer inactifs")
        r = self.client.post("/admin/clients/client/", {"action": "marquer_inactifs", "_selected_action": [c.pk]})
        self.assertEqual(r.status_code, 302)
        c.refresh_from_db()
        self.assertEqual(c.statut, "inactif")

    def test_page_404_en_francais(self):
        r = self.client.get("/nexiste-pas/", HTTP_HOST="essai.test")
        self.assertEqual(r.status_code, 404)
