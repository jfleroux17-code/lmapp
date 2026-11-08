import json

from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from django.test import TestCase, override_settings

from clients.models import Adresse, Client, Secteur
from communications import avis, envoi
from communications.models import Gabarit, Message
from core.models import Entreprise, Membre
from tournee import services
from tournee.models import Operation, PositionGPS

HOTE = "louis.exemple.test"
# Sainte-Adèle : trois maisons à environ 300 m l'une de l'autre, une loin
ICI = (-74.1300, 45.9500)


def _pt(dx_m, dy_m=0):
    return Point(ICI[0] + dx_m / 77600, ICI[1] + dy_m / 111200, srid=4326)


@override_settings(ALLOWED_HOSTS=["*"], LMAPP_ENV="test", LMAPP_DESTINATAIRES_TEST=[])
class AvisTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Déneigement Essai", slug="essai", domaine=HOTE, signature_messages="Déneigement Essai, 450 555-0100")
        s = Secteur.objects.create(entreprise=cls.ent, nom="Village", ordre=1)
        loin = Secteur.objects.create(entreprise=cls.ent, nom="Loin", ordre=2)

        def arret(nom, rang, point, cell="+14505550101", secteur=s, **kw):
            c = Client.objects.create(entreprise=cls.ent, nom=nom, cellulaire=cell, **kw)
            return Adresse.objects.create(entreprise=cls.ent, client=c, secteur=secteur, ordre_tournee=rang, ligne1=f"{rang}, rue {nom}",
                                          ville="Sainte-Adèle", position=point, position_source="manuelle", position_precision="adresse")

        cls.a1 = arret("Tremblay", 1, _pt(0))
        cls.a2 = arret("Côté", 2, _pt(300), cell="+14505550102", desabonne_le="2026-11-01T00:00:00Z")
        cls.a3 = arret("Roy", 3, _pt(600), cell="")  # pas de cellulaire
        cls.a4 = arret("Loin", 1, _pt(5000), cell="+14505550104", secteur=loin)
        cls.vague = arret("Vague", 4, _pt(100), cell="+14505550105")
        Adresse.objects.filter(pk=cls.vague.pk).update(position_source="geocodage", position_precision="ville")

    def setUp(self):
        self.op = Operation.objects.create(entreprise=self.ent)

    def test_proximite_dans_le_rayon_une_seule_fois(self):
        self.assertEqual(avis.aviser_proximite(self.op, _pt(100)), 2)  # Tremblay et Côté (désabonné du commercial : reçoit quand même); Roy sans cellulaire; Vague trop imprécis
        m = Message.objects.get(client=self.a2.client)
        self.assertEqual(m.statut, "prepare")  # aucun fournisseur : rien ne part
        self.assertEqual(m.destinataire, "+14505550102")
        self.assertEqual(m.contenu, "Bonjour, on arrive au 2, rue Côté d'ici environ 12 minutes.\nDéneigement Essai, 450 555-0100")
        self.assertEqual(avis.aviser_proximite(self.op, _pt(150)), 0)  # G3 : pas de doublon
        self.assertEqual(avis.aviser_proximite(Operation.objects.create(entreprise=Entreprise.objects.create(nom="A", slug="a", domaine="a.test")), _pt(0)), 0)

    def test_pas_d_avis_aux_adresses_deja_faites(self):
        services.marquer(self.op, self.a1, "fait")
        self.assertEqual(avis.aviser_proximite(self.op, _pt(0)), 1)
        self.assertFalse(Message.objects.filter(client=self.a1.client).exists())

    def test_rayon_et_interrupteur_de_l_entreprise(self):
        Entreprise.objects.filter(pk=self.ent.pk).update(avis_rayon_m=100)
        self.op.refresh_from_db()
        self.assertEqual(avis.aviser_proximite(self.op, _pt(0)), 1)
        Entreprise.objects.filter(pk=self.ent.pk).update(avis_proximite_actif=False)
        op2 = self.op
        op2.terminer()
        op3 = Operation.objects.create(entreprise=Entreprise.objects.get(pk=self.ent.pk))
        self.assertEqual(avis.aviser_proximite(op3, _pt(0)), 0)

    def test_debut_prochains_secteur_et_passage_fait(self):
        self.assertEqual(avis.aviser_debut(self.op), 4)  # Roy n'a ni cellulaire ni courriel
        self.assertEqual(avis.aviser_debut(self.op), 0)
        self.assertEqual(avis.aviser_prochains(self.op, 3), 2)  # Tremblay, Côté (Roy : pas de cellulaire)
        self.assertEqual(avis.aviser_secteur(self.op, self.a4.secteur_id), 1)
        self.assertIsNone(services.marquer(self.op, self.a1, "fait") and Message.objects.filter(genre="passage_fait").first())
        Entreprise.objects.filter(pk=self.ent.pk).update(avis_passage_fait=True)
        self.op.refresh_from_db()
        services.marquer(self.op, self.a1, "fait")
        m = Message.objects.get(genre="passage_fait")
        self.assertTrue(m.contenu.startswith("Bonjour, le déneigement au 1, rue Tremblay est fait ("))

    def test_gabarit_modifie_et_variable_inconnue(self):
        Gabarit.objects.create(entreprise=self.ent, genre="proximite", texte="Salut {client}, on arrive ({minutes} min).")
        avis.aviser_prochains(self.op, 1)
        self.assertEqual(Message.objects.get().contenu, "Salut Tremblay, on arrive (6 min).\nDéneigement Essai, 450 555-0100")
        Gabarit.objects.filter(genre="proximite").update(texte="Allo {inconnue}")
        avis.aviser_prochains(self.op, 2)
        self.assertTrue(Message.objects.filter(contenu__startswith="Allo {inconnue}").exists())  # envoyé tel quel, pas bloqué

    def test_garde_fou_hors_prod(self):
        m = Message.objects.create(entreprise=self.ent, genre="manuel", canal="texto", destinataire="+14505550199", contenu="x")
        self.assertEqual(envoi.envoyer(m).statut, "prepare")  # aucun fournisseur : rien ne part
        with override_settings(TWILIO_ACCOUNT_SID="AC-essai", TWILIO_AUTH_TOKEN="essai"):
            self.assertEqual(envoi.envoyer(m).statut, "bloque")  # fournisseur là, mais destinataire non permis en test
            self.assertFalse(envoi.destinataire_permis("+14505550199"))
            with override_settings(LMAPP_DESTINATAIRES_TEST=["+14505550199"]):
                self.assertTrue(envoi.destinataire_permis("+14505550199"))
            with override_settings(LMAPP_ENV="prod"):
                self.assertTrue(envoi.destinataire_permis("+14505550199"))


@override_settings(ALLOWED_HOSTS=["*"], LMAPP_ENV="test", LMAPP_DESTINATAIRES_TEST=[])
class EcransAvisTests(AvisTests.__bases__[0]):
    @classmethod
    def setUpTestData(cls):
        AvisTests.setUpTestData.__func__(cls)
        cls.louis = get_user_model().objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)

    def pos(self, op, point, precision=10):
        return self.client.post("/tournee/position/", json.dumps({"operation": op, "lat": point.y, "lon": point.x, "precision": precision}),
                                content_type="application/json")

    def test_demarrer_avec_avis_puis_position(self):
        r = self.client.post("/tournee/demarrer/", {"type": "neige", "aviser_debut": "1"}, follow=True)
        self.assertContains(r, "4 avis de début préparés.")
        op = Operation.objects.get()
        self.assertEqual(self.pos(op.pk, _pt(100), precision=500).json()["avis"], 0)  # GPS trop imprécis : gardé, sans avis
        r = self.pos(op.pk, _pt(100))
        self.assertEqual(r.json()["avis"], 2)
        self.assertEqual(PositionGPS.objects.count(), 2)
        self.assertEqual(self.pos(op.pk + 99, _pt(0)).status_code, 409)
        self.assertEqual(self.client.post("/tournee/position/", "{}", content_type="application/json").status_code, 400)
        page = self.client.get("/messages/")
        self.assertContains(page, "on arrive au 1, rue Tremblay")
        self.assertContains(page, "Préparé")

    def test_avis_manuels(self):
        self.client.post("/tournee/demarrer/", {"type": "neige"})
        self.assertFalse(Message.objects.exists())  # case décochée : pas d'avis de début
        r = self.client.post("/tournee/avis/", {"mode": "prochains"}, follow=True)
        self.assertContains(r, "2 avis préparés.")
        r = self.client.post("/tournee/avis/", {"mode": "secteur", "secteur": str(self.a4.secteur_id)}, follow=True)
        self.assertContains(r, "1 avis préparé.")
        r = self.client.post("/tournee/avis/", {"mode": "prochains"}, follow=True)
        self.assertContains(r, "Personne de plus à aviser")
