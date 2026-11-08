from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from clients.models import Adresse, Client
from communications.models import Message
from core.models import Entreprise, Membre
from demandes.models import Demande

HOTE = "louis.exemple.test"


@override_settings(ALLOWED_HOSTS=["*"])
class DemandesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE)
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.exemple.test")
        cls.c = Client.objects.create(entreprise=cls.ent, nom="Tremblay")
        cls.a1 = Adresse.objects.create(entreprise=cls.ent, client=cls.c, ligne1="1, rue A", ville="Sainte-Adèle")
        cls.a2 = Adresse.objects.create(entreprise=cls.ent, client=cls.c, ligne1="2, rue B", ville="Sainte-Adèle")
        U = get_user_model()
        cls.louis = U.objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")
        cls.lecteur = U.objects.create_user("lecteur", password="x" * 12)
        Membre.objects.create(utilisateur=cls.lecteur, entreprise=cls.ent, role="lecture")

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)

    def test_depuis_un_message_recu(self):
        m = Message.objects.create(entreprise=self.ent, client=self.c, genre="recu", canal="courriel", sens="entrant",
                                   statut="recu", contenu="Vous avez oublié mon entrée ce matin!", expediteur="t@example.com")
        page = self.client.get(f"/demandes/nouvelle/?message={m.pk}")
        self.assertContains(page, "Vous avez oublié mon entrée ce matin!")  # description proposée
        r = self.client.post("/demandes/nouvelle/", {"message": m.pk, "genre": "oubli", "urgent": "1", "adresse": self.a2.pk,
                                                     "description": "Oublié ce matin"}, follow=True)
        d = Demande.objects.get()
        self.assertEqual((d.client, d.adresse, d.genre, d.urgent, d.source, d.message), (self.c, self.a2, "oubli", True, "courriel", m))
        self.assertContains(r, "Demande notée : oublié à la tournée.")
        self.assertContains(self.client.get("/"), "! 1")  # urgente : pastille dans l'en-tête
        self.assertContains(self.client.get(f"/messages/{m.pk}/"), "Demande : oublié à la tournée")
        self.assertContains(self.client.get(f"/clients/{self.c.pk}/"), "Oublié ce matin")

    def test_nouveau_client_inconnu(self):
        self.client.post("/demandes/nouvelle/", {"genre": "nouveau", "contact": "Marc, 450 555-0199", "description": "Prix pour une entrée double"})
        d = Demande.objects.get()
        self.assertEqual((d.client, d.contact, d.urgent), (None, "Marc, 450 555-0199", False))

    def test_suivi_planifiee_reglee_rouverte(self):
        d = Demande.objects.create(entreprise=self.ent, client=self.c, genre="service", description="Pelleter le balcon")
        self.client.post(f"/demandes/{d.pk}/statut/", {"statut": "planifiee", "prevue_le": "2026-11-12"})
        d.refresh_from_db()
        self.assertEqual((d.statut, str(d.prevue_le)), ("planifiee", "2026-11-12"))
        self.client.post(f"/demandes/{d.pk}/statut/", {"statut": "reglee", "reglement": "Fait mardi"})
        d.refresh_from_db()
        self.assertEqual((d.statut, d.reglement), ("reglee", "Fait mardi"))
        self.assertIsNotNone(d.reglee_le)
        self.assertEqual(list(self.client.get("/demandes/?vue=reglees").context["liste"]), [d])
        self.client.post(f"/demandes/{d.pk}/statut/", {"statut": "ouverte"})
        d.refresh_from_db()
        self.assertIsNone(d.reglee_le)

    def test_description_obligatoire_et_acces(self):
        r = self.client.post("/demandes/nouvelle/", {"genre": "autre", "description": " "}, follow=True)
        self.assertContains(r, "Décrire la demande.")
        etrangere = Demande.objects.create(entreprise=self.autre, description="x")
        self.assertEqual(self.client.get(f"/demandes/{etrangere.pk}/").status_code, 404)
        self.client.force_login(self.lecteur)
        self.assertEqual(self.client.get("/demandes/").status_code, 200)
        self.assertEqual(self.client.post("/demandes/nouvelle/", {"genre": "autre", "description": "x"}).status_code, 403)

    def test_client_d_une_autre_entreprise_ignore(self):
        etranger = Client.objects.create(entreprise=self.autre, nom="X")
        self.client.post("/demandes/nouvelle/", {"client": etranger.pk, "genre": "autre", "description": "x"})
        self.assertIsNone(Demande.objects.get().client)
