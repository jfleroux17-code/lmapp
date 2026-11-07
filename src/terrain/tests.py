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
