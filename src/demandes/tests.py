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
        # Ouverte en suivant la redirection : pastille orange (ouverte, pas réglée), plus rouge
        self.assertIsNotNone(Demande.objects.get().vue_le)
        self.assertContains(self.client.get("/"), 'aria-label="Demandes : 1 à régler"')
        self.assertContains(self.client.get(f"/messages/{m.pk}/"), "Demande : oublié à la tournée")
        self.assertContains(self.client.get(f"/clients/{self.c.pk}/"), "Oublié ce matin")

    def test_pastille_rouge_puis_orange_puis_rien(self):
        d = Demande.objects.create(entreprise=self.ent, client=self.c, genre="service", description="Bordage svp")
        self.assertContains(self.client.get("/"), 'aria-label="Demandes : 1 pas encore ouverte"')
        self.client.get(f"/demandes/{d.pk}/")
        self.assertContains(self.client.get("/"), 'aria-label="Demandes : 1 à régler"')
        d.changer_statut(Demande.Statut.PLANIFIEE)
        self.assertContains(self.client.get("/"), 'aria-label="Demandes"')

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

    def test_choisir_le_client_d_une_nouvelle_demande(self):
        page = self.client.get("/demandes/nouvelle/")
        self.assertContains(page, "Chercher un client")
        r = self.client.get("/demandes/choisir-client/?q=tremb", HTTP_HX_REQUEST="true")
        self.assertContains(r, f"/demandes/nouvelle/?client={self.c.pk}")
        Client.objects.create(entreprise=self.autre, nom="Tremblay")  # autre entreprise : jamais proposé
        self.assertEqual(len(self.client.get("/demandes/choisir-client/?q=tremb").context["clients"]), 1)
        self.assertContains(self.client.get(f"/demandes/nouvelle/?client={self.c.pk}"), "changer de client")

    def test_lier_une_demande_a_un_client(self):
        m = Message.objects.create(entreprise=self.ent, genre="recu", canal="texto", sens="entrant", statut="recu",
                                   contenu="Mon entrée est bloquée", expediteur="+14505550142")
        d = Demande.objects.create(entreprise=self.ent, genre="oubli", description="Bloquée", contact="+14505550142", message=m)
        page = self.client.get(f"/demandes/{d.pk}/")
        self.assertContains(page, "Lier à un client")
        r = self.client.get(f"/demandes/choisir-client/?q=tremb&demande={d.pk}")
        self.assertContains(r, f"/demandes/{d.pk}/client/")
        r = self.client.post(f"/demandes/{d.pk}/client/", {"client": self.c.pk}, follow=True)
        self.assertContains(r, "Demande liée à Tremblay")
        d.refresh_from_db()
        m.refresh_from_db()
        self.assertEqual((d.client, d.adresse, m.client), (self.c, None, self.c))  # deux adresses : pas de choix au hasard
        self.assertNotContains(self.client.get(f"/demandes/{d.pk}/"), "Lier à un client")
        etranger = Client.objects.create(entreprise=self.autre, nom="X")
        self.assertEqual(self.client.post(f"/demandes/{d.pk}/client/", {"client": etranger.pk}).status_code, 404)
        self.client.force_login(self.lecteur)
        self.assertEqual(self.client.post(f"/demandes/{d.pk}/client/", {"client": self.c.pk}).status_code, 403)


class DossierDommageTests(TestCase):
    """Dossier de dommage (H3) : photo, entente, coût, payé par; effacé avec le client (Loi 25)."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from clients.models import Client
        from core.models import Entreprise, Membre
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai-dd", domaine="dd.exemple.test")
        cls.c = Client.objects.create(entreprise=cls.ent, nom="Tremblay")
        cls.d = Demande.objects.create(entreprise=cls.ent, client=cls.c, genre="dommage", description="Boîte aux lettres accrochée", urgent=True)
        cls.louis = get_user_model().objects.create_user("louis-dd", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")

    def test_dossier_complet(self):
        from decimal import Decimal
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        from demandes.models import PhotoDemande
        self.client.force_login(self.louis)
        h = {"HTTP_HOST": "dd.exemple.test"}
        with override_settings(ALLOWED_HOSTS=["*"]):
            self.client.post(f"/demandes/{self.d.pk}/photos/", {"photo": SimpleUploadedFile("p.jpg", b"\xff\xd8\xff\xe0" + b"2" * 50)}, **h)
            self.client.post(f"/demandes/{self.d.pk}/dossier/", {"entente": "Je remplace le poteau samedi.", "cout": "85,50 $", "paye_par": "deneigeur"}, **h)
            r = self.client.get(f"/demandes/{self.d.pk}/", **h)
        self.d.refresh_from_db()
        self.assertEqual((self.d.cout, self.d.paye_par), (Decimal("85.50"), "deneigeur"))
        self.assertContains(r, "Je remplace le poteau samedi.")
        p = PhotoDemande.objects.get()
        self.assertContains(r, f"/photos-demande/{p.pk}/")
        from clients.effacement import effacer
        effacer(self.c)
        self.assertFalse(PhotoDemande.objects.exists())
        self.d.refresh_from_db()
        self.assertEqual(self.d.entente, "")
