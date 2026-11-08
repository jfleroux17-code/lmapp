from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.test import TestCase, override_settings

from clients.models import Adresse, Client, Secteur
from core.models import Entreprise, Membre

HOTE = "louis.exemple.test"


@override_settings(ALLOWED_HOSTS=["*"])
class TerrainTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.ent = Entreprise.objects.create(nom="Déneigement Essai", slug="essai", domaine=HOTE)
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.exemple.test")
        cls.louis = U.objects.create_user("louis", password="mot-de-passe-solide-123")
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")
        cls.etranger = U.objects.create_user("etranger", password="mot-de-passe-solide-123")
        Membre.objects.create(utilisateur=cls.etranger, entreprise=cls.autre, role="operateur")
        village = Secteur.objects.create(entreprise=cls.ent, nom="Village", ordre=1)
        mont = Secteur.objects.create(entreprise=cls.ent, nom="Mont-Rolland", ordre=2)

        def client(nom, rang, secteur, cell="", statut="actif", position=True, **kw):
            c = Client.objects.create(entreprise=cls.ent, nom=nom, cellulaire=cell, statut=statut, **kw)
            Adresse.objects.create(entreprise=cls.ent, client=c, secteur=secteur, ordre_tournee=rang,
                                   ligne1=f"{rang}, rue des Essais", ville="Sainte-Adèle",
                                   position=Point(-74.13, 45.95, srid=4326) if position else None,
                                   position_source="manuelle" if position else "")
            return c

        cls.cote = client("Côté", 2, village, cell="+14505550104", statut="recouvrement")
        cls.tremblay = client("Tremblay", 1, village, cell="+14505550101")
        cls.pelletier = client("Pelletier", 1, mont)
        Adresse.objects.create(entreprise=cls.ent, client=cls.pelletier, secteur=mont, ordre_tournee=2, ligne1="4, rue de la Démo", ville="Sainte-Adèle")
        cls.noir = client("Bélanger", 9, mont, statut="liste_noire", position=False)
        cls.secret = Client.objects.create(entreprise=cls.autre, nom="Côté-Ailleurs")

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE

    def _connecte(self, u=None):
        self.client.force_login(u or self.louis)

    def test_non_connecte_va_a_la_connexion(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/connexion/", r["Location"])

    def test_connexion_par_le_formulaire(self):
        r = self.client.post("/connexion/", {"username": "louis", "password": "mot-de-passe-solide-123"})
        self.assertRedirects(r, "/")
        self.client.logout()
        r = self.client.post("/connexion/", {"username": "louis", "password": "faux"})
        self.assertContains(r, "incorrect")

    def test_domaine_inconnu(self):
        self._connecte()
        self.assertEqual(self.client.get("/", HTTP_HOST="inconnu.exemple.test").status_code, 404)

    def test_non_membre_refuse(self):
        self._connecte(self.etranger)
        self.assertEqual(self.client.get("/").status_code, 403)

    def test_liste_dans_l_ordre_de_la_tournee_sans_doublon(self):
        self._connecte()
        noms = [c.nom for c in self.client.get("/").context["clients"]]
        self.assertEqual(noms, ["Tremblay", "Côté", "Pelletier"])  # recouvrement inclus; liste noire et autre entreprise exclues

    def test_recherche_sans_accents(self):
        self._connecte()
        noms = [c.nom for c in self.client.get("/", {"q": "cote"}).context["clients"]]
        self.assertEqual(noms, ["Côté"])  # pas le client de l'autre entreprise

    def test_recherche_par_telephone_et_plusieurs_mots(self):
        self._connecte()
        self.assertEqual([c.nom for c in self.client.get("/", {"q": "555-0101"}).context["clients"]], ["Tremblay"])
        self.assertEqual([c.nom for c in self.client.get("/", {"q": "demo pelletier"}).context["clients"]], ["Pelletier"])
        self.assertEqual(list(self.client.get("/", {"q": "rue des essais 9"}).context["clients"]), [self.noir])

    def test_fragment_htmx(self):
        self._connecte()
        r = self.client.get("/", {"q": "tremblay"}, HTTP_HX_REQUEST="true")
        self.assertNotContains(r, "<html")
        self.assertContains(r, "Tremblay")

    def test_fiche(self):
        self._connecte()
        r = self.client.get(f"/clients/{self.cote.pk}/")
        self.assertContains(r, 'href="tel:+14505550104"')
        self.assertContains(r, "Compte en recouvrement")
        self.assertContains(r, "https://maps.apple.com/?daddr=45.950000,-74.130000")
        self.assertContains(r, "https://waze.com/ul?ll=45.950000,-74.130000")

    def test_fiche_sans_position_navigue_par_l_adresse(self):
        self._connecte()
        r = self.client.get(f"/clients/{self.noir.pk}/")
        self.assertContains(r, "Liste noire : ne pas servir")
        self.assertContains(r, "Position approximative")
        self.assertContains(r, "daddr=9%2C%20rue%20des%20Essais%2C%20Sainte-Ad%C3%A8le")

    def test_fiche_d_une_autre_entreprise(self):
        self._connecte()
        self.assertEqual(self.client.get(f"/clients/{self.secret.pk}/").status_code, 404)

    def test_manifeste(self):
        r = self.client.get("/manifest.webmanifest")
        self.assertEqual(r["Content-Type"], "application/manifest+json")
        self.assertEqual(r.json()["name"], "Déneigement Essai")
        self.assertEqual(r.json()["display"], "standalone")
        icones = {(i["sizes"], i.get("purpose", "any")) for i in r.json()["icons"]}
        self.assertTrue({("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= icones)

    def test_icones(self):
        self._connecte()
        page = self.client.get("/").content.decode()
        self.assertIn('rel="apple-touch-icon"', page)
        self.assertIn("icones/icone-180", page)
        r = self.client.get("/favicon.ico")
        self.assertEqual(r.status_code, 301)
        self.assertIn("icones/icone-192", r["Location"])


@override_settings(ALLOWED_HOSTS=["*"])
class ModifierClientsTests(TestCase):
    """A12 (clients modifiables dans l'app), K9 (mode de l'entreprise), A13 (position), K10 (Annuler)."""

    @classmethod
    def setUpTestData(cls):
        from clients.models import Adresse, Client, Secteur
        from core.models import Membre, VilleDesservie
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine="essai.exemple.test", ville="Sainte-Adèle")
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.exemple.test")
        VilleDesservie.objects.create(entreprise=cls.ent, nom="Sainte-Adèle", centre=Point(-74.13, 45.95, srid=4326))
        cls.secteur = Secteur.objects.create(entreprise=cls.ent, nom="Village")
        Secteur.objects.create(entreprise=cls.autre, nom="Pas le mien")
        cls.c = Client.objects.create(entreprise=cls.ent, nom="Tremblay", cellulaire="+14505550101")
        cls.a = Adresse.objects.create(entreprise=cls.ent, client=cls.c, ligne1="1, rue A", ville="Sainte-Adèle")
        U = get_user_model()
        cls.patron = U.objects.create_user("patron", password="x" * 12)
        Membre.objects.create(utilisateur=cls.patron, entreprise=cls.ent, role="admin")
        cls.operateur = U.objects.create_user("operateur", password="x" * 12)
        Membre.objects.create(utilisateur=cls.operateur, entreprise=cls.ent, role="operateur")
        cls.lecteur = U.objects.create_user("lecteur", password="x" * 12)
        Membre.objects.create(utilisateur=cls.lecteur, entreprise=cls.ent, role="lecture")

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = "essai.exemple.test"
        self.client.force_login(self.operateur)

    def test_nouveau_client_avec_son_adresse(self):
        from clients.models import Client
        page = self.client.get("/clients/nouveau/")
        self.assertContains(page, 'inputmode="tel"')
        self.assertContains(page, "Annuler")
        self.assertEqual(page.context["formulaires"][1][1].initial["ville"], "Sainte-Adèle")
        r = self.client.post("/clients/nouveau/", {"c-prenom": "Ginette", "c-nom": "Roy", "c-cellulaire": "450 555-0102",
                                                   "c-courriel": " Ginette@Example.COM ", "c-canal_prefere": "texto", "c-statut": "actif",
                                                   "a-ligne1": "8, rue des Essais", "a-ville": "Sainte-Adèle", "a-code_postal": "j8b3b3",
                                                   "a-secteur": self.secteur.pk, "a-active": "on", "a-borne_fontaine": "on"})
        c = Client.objects.get(nom="Roy")
        self.assertRedirects(r, f"/clients/{c.pk}/", fetch_redirect_response=False)
        self.assertEqual((c.cellulaire, c.courriel, c.entreprise), ("+14505550102", "ginette@example.com", self.ent))
        adresse = c.adresses.get()
        self.assertEqual((adresse.code_postal, adresse.secteur, adresse.borne_fontaine), ("J8B 3B3", self.secteur, True))

    def test_erreurs_rien_d_enregistre(self):
        from clients.models import Client
        avant = Client.objects.count()
        page = self.client.post("/clients/nouveau/", {"c-nom": "Roy", "c-cellulaire": "123", "c-canal_prefere": "texto",
                                                      "c-statut": "actif", "a-ligne1": "", "a-ville": "Sainte-Adèle"})
        self.assertEqual(page.status_code, 200)
        self.assertEqual(Client.objects.count(), avant)  # tout ou rien
        page = self.client.post("/clients/nouveau/", {"c-nom": "Roy", "c-canal_prefere": "texto", "c-statut": "actif",
                                                      "a-ligne1": "", "a-ville": "Sainte-Adèle"})
        self.assertEqual(Client.objects.count(), avant)  # client valide, adresse manquante : rien

    def test_modifier_client_et_adresse(self):
        page = self.client.get(f"/clients/{self.c.pk}/modifier/")
        self.assertContains(page, 'value="450 555-0101"')  # lisible, pas en E.164
        self.client.post(f"/clients/{self.c.pk}/modifier/", {"c-nom": "Tremblay-Roy", "c-cellulaire": "450-555-0101",
                                                             "c-canal_prefere": "courriel", "c-statut": "recouvrement"})
        self.c.refresh_from_db()
        self.assertEqual((self.c.nom, self.c.cellulaire, self.c.statut), ("Tremblay-Roy", "+14505550101", "recouvrement"))
        self.client.post(f"/clients/{self.c.pk}/adresses/{self.a.pk}/", {"a-ligne1": "1, rue A", "a-ville": "Sainte-Adèle",
                                                                         "a-ou_mettre_neige": "À gauche", "a-active": "on"})
        self.a.refresh_from_db()
        self.assertEqual(self.a.ou_mettre_neige, "À gauche")
        self.client.post(f"/clients/{self.c.pk}/adresses/nouvelle/", {"a-ligne1": "2, rue B", "a-ville": "Sainte-Adèle", "a-active": "on"})
        self.assertEqual(self.c.adresses.count(), 2)

    def test_secteur_d_une_autre_entreprise_refuse(self):
        from clients.models import Secteur
        etranger = Secteur.objects.get(nom="Pas le mien")
        page = self.client.post(f"/clients/{self.c.pk}/adresses/{self.a.pk}/", {"a-ligne1": "1, rue A", "a-ville": "Sainte-Adèle",
                                                                                "a-secteur": etranger.pk})
        self.assertEqual(page.status_code, 200)
        self.a.refresh_from_db()
        self.assertIsNone(self.a.secteur)

    def test_mode_equipe_et_lecture_seule(self):
        self.assertContains(self.client.get(f"/clients/{self.c.pk}/"), "Modifier le client")
        Entreprise.objects.filter(pk=self.ent.pk).update(mode="equipe")
        self.assertNotContains(self.client.get(f"/clients/{self.c.pk}/"), "Modifier le client")
        self.assertEqual(self.client.get(f"/clients/{self.c.pk}/modifier/").status_code, 403)
        self.client.force_login(self.patron)
        self.assertEqual(self.client.get(f"/clients/{self.c.pk}/modifier/").status_code, 200)
        self.client.force_login(self.lecteur)
        Entreprise.objects.filter(pk=self.ent.pk).update(mode="seul")
        self.assertEqual(self.client.get("/clients/nouveau/").status_code, 403)

    def test_autre_entreprise(self):
        from clients.models import Client
        etranger = Client.objects.create(entreprise=self.autre, nom="X")
        self.assertEqual(self.client.get(f"/clients/{etranger.pk}/modifier/").status_code, 404)

    def test_corriger_la_position(self):
        page = self.client.get(f"/adresses/{self.a.pk}/position/")
        self.assertContains(page, "vendor/leaflet-1.9.4/leaflet.")
        self.assertContains(page, "L.map(")
        self.assertEqual((page.context["lat"], page.context["zoom"]), (45.95, 14))  # pas de position : centre de la ville
        self.client.post(f"/adresses/{self.a.pk}/position/", {"lat": "45.9512345", "lng": "-74.1312345", "source": "gps"})
        self.a.refresh_from_db()
        self.assertEqual((round(self.a.position.y, 5), self.a.position_source, self.a.position_precision), (45.95123, "gps", "adresse"))
        self.assertEqual(self.client.get(f"/adresses/{self.a.pk}/position/").context["zoom"], 18)
        self.client.post(f"/adresses/{self.a.pk}/position/", {"lat": "45.95", "lng": "-74.13"})
        self.a.refresh_from_db()
        self.assertEqual(self.a.position_source, "manuelle")
        r = self.client.post(f"/adresses/{self.a.pk}/position/", {"lat": "abc", "lng": "-74"}, follow=True)
        self.assertContains(r, "Position illisible")


@override_settings(ALLOWED_HOSTS=["*"], LMAPP_ENV="test", LMAPP_DESTINATAIRES_TEST=["+14505550101", "t@example.com"],
                   TWILIO_ACCOUNT_SID="AC", TWILIO_AUTH_TOKEN="x", SMTP_HOTE="smtp", IMAP_UTILISATEUR="louis@exemple.test", IMAP_MOT_DE_PASSE="x")
class EcrireTests(TestCase):
    """E2, E3 : écrire à un client depuis sa fiche."""

    def test_texto_et_courriel(self):
        from unittest import mock
        from clients.models import Client
        from communications.models import Message
        from core.models import Membre
        ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine="essai.exemple.test", envois_actifs=True,
                                        numero_texto="+14503001166", courriel_reponse="louis@exemple.test", signature_messages="Essai, 450 555-0100")
        c = Client.objects.create(entreprise=ent, nom="Tremblay", cellulaire="+14505550101", courriel="t@example.com", canal_prefere="courriel")
        u = get_user_model().objects.create_user("operateur", password="x" * 12)
        Membre.objects.create(utilisateur=u, entreprise=ent, role="operateur")
        Entreprise.objects.filter(pk=ent.pk).update(mode="equipe")  # opérateur d'une équipe : peut écrire, pas modifier
        self.client.defaults["HTTP_HOST"] = "essai.exemple.test"
        self.client.force_login(u)
        page = self.client.get(f"/clients/{c.pk}/ecrire/")
        self.assertEqual(page.context["choisi"], "courriel")
        with mock.patch("communications.tasks.envoyer_message.defer"):
            r = self.client.post(f"/clients/{c.pk}/ecrire/", {"canal": "texto", "texte": "On passe vers 8 h."}, follow=True)
            self.assertContains(r, "Message en route vers +14505550101.")
            self.client.post(f"/clients/{c.pk}/ecrire/", {"canal": "courriel", "texte": "Bonjour", "sujet": "Votre entrée"})
        t, m = Message.objects.order_by("pk")
        self.assertEqual((t.canal, t.contenu), ("texto", "On passe vers 8 h.\n\nEssai, 450 555-0100"))
        self.assertEqual((m.canal, m.sujet, m.statut), ("courriel", "Votre entrée", "en_file"))
        r = self.client.post(f"/clients/{c.pk}/ecrire/", {"canal": "texto", "texte": ""}, follow=True)
        self.assertEqual(Message.objects.count(), 2)
