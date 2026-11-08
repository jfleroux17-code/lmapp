from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import EchecConnexion, Entreprise, Membre

HOTE = "louis.exemple.test"
MDP = "mot-de-passe-solide-123"


@override_settings(ALLOWED_HOSTS=["*"], LMAPP_CONNEXION_MAX_IP=3, LMAPP_CONNEXION_MAX_COMPTE=5, LMAPP_CONNEXION_FENETRE_MIN=15)
class LimitationConnexionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE)
        cls.louis = get_user_model().objects.create_user("louis", password=MDP)
        Membre.objects.create(utilisateur=cls.louis, entreprise=ent, role="operateur")

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE

    def essai(self, mdp, nom="louis", ip="203.0.113.5"):
        return self.client.post("/connexion/", {"username": nom, "password": mdp}, REMOTE_ADDR=ip)

    def test_echecs_puis_blocage_de_l_ip_meme_avec_le_bon_mot_de_passe(self):
        for _ in range(3):
            self.assertContains(self.essai("faux"), "incorrect")
        r = self.essai(MDP)
        self.assertEqual(r.status_code, 429)
        self.assertContains(r, "Trop d'essais. Réessaie dans 15 minutes.", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(EchecConnexion.objects.count(), 3)  # l'essai refusé pendant le blocage n'est pas compté

    def test_autre_ip_pas_bloquee_tant_que_le_compte_ne_l_est_pas(self):
        for _ in range(3):
            self.essai("faux", ip="203.0.113.5")
        self.assertRedirects(self.essai(MDP, ip="198.51.100.7"), "/")

    def test_blocage_du_nom_d_utilisateur_depuis_plusieurs_ip(self):
        for i in range(5):
            self.essai("faux", nom="LOUIS ", ip=f"203.0.113.{i + 10}")  # majuscules et espaces : même compte
        self.assertEqual(self.essai(MDP, ip="198.51.100.7").status_code, 429)

    def test_blocage_temporaire(self):
        for _ in range(3):
            self.essai("faux")
        EchecConnexion.objects.update(moment=timezone.now() - timedelta(minutes=16))
        self.assertRedirects(self.essai(MDP), "/")

    def test_connexion_reussie_efface_les_echecs_du_compte(self):
        self.essai("faux")
        self.essai("faux", nom="inconnu")
        self.assertRedirects(self.essai(MDP), "/")
        self.assertEqual(list(EchecConnexion.objects.values_list("nom_utilisateur", flat=True)), ["inconnu"])

    def test_vieux_echecs_effaces_apres_24_heures(self):
        vieux = EchecConnexion.objects.create(ip="203.0.113.9", nom_utilisateur="x")
        EchecConnexion.objects.filter(pk=vieux.pk).update(moment=timezone.now() - timedelta(hours=25))
        self.essai("faux")
        self.assertFalse(EchecConnexion.objects.filter(pk=vieux.pk).exists())

    def test_l_administration_est_aussi_protegee(self):
        admin = get_user_model().objects.create_superuser("jf", password=MDP)
        for _ in range(3):
            self.client.post("/admin/login/", {"username": "jf", "password": "faux"}, REMOTE_ADDR="203.0.113.5")
        self.client.post("/admin/login/", {"username": "jf", "password": MDP}, REMOTE_ADDR="203.0.113.5")
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(admin.is_active)
