from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from core.middleware import IPReelleMiddleware
from core.models import Entreprise

CADDY = "172.20.0.250"


def _ip_vue(remote_addr, xff=None):
    entetes = {"REMOTE_ADDR": remote_addr}
    if xff is not None:
        entetes["HTTP_X_FORWARDED_FOR"] = xff
    requete = RequestFactory().get("/", **entetes)
    vue = {}

    def reponse(r):
        vue["ip"] = r.META["REMOTE_ADDR"]
        return HttpResponse()

    IPReelleMiddleware(reponse)(requete)
    return vue["ip"]


@override_settings(LMAPP_PROXIES_DE_CONFIANCE=[CADDY])
class IPReelleTests(SimpleTestCase):
    def test_ip_reelle_venant_de_caddy(self):
        self.assertEqual(_ip_vue(CADDY, "203.0.113.7"), "203.0.113.7")

    def test_derniere_valeur_seulement(self):
        # Une valeur inventée par le visiteur, puis celle ajoutée par Caddy
        self.assertEqual(_ip_vue(CADDY, "1.2.3.4, 203.0.113.7"), "203.0.113.7")

    def test_en_tete_ignore_si_pas_caddy(self):
        # L'app de test (ou n'importe qui d'autre) ne peut pas fausser l'IP
        self.assertEqual(_ip_vue("172.20.0.4", "203.0.113.7"), "172.20.0.4")

    def test_valeur_invalide(self):
        self.assertEqual(_ip_vue(CADDY, "pas-une-ip"), CADDY)

    def test_sans_en_tete(self):
        self.assertEqual(_ip_vue(CADDY), CADDY)

    def test_ipv6(self):
        self.assertEqual(_ip_vue(CADDY, "2001:db8::1"), "2001:db8::1")


class TelephoneTests(SimpleTestCase):
    def test_formes_courantes(self):
        from core.telephone import normaliser
        for forme in ("450-555-1234", "(450) 555-1234", "1 450 555 1234", "+1 450.555.1234", "4505551234"):
            self.assertEqual(normaliser(forme), "+14505551234", forme)

    def test_vide(self):
        from core.telephone import normaliser
        self.assertEqual(normaliser(""), "")
        self.assertEqual(normaliser(None), "")

    def test_invalides(self):
        from django.core.exceptions import ValidationError
        from core.telephone import normaliser
        for forme in ("555-1234", "450-555-12345", "050-555-1234", "450-155-1234", "450-555-1234 poste 12", "abc"):
            with self.assertRaises(ValidationError, msg=forme):
                normaliser(forme)

    def test_affichage(self):
        from core.telephone import afficher
        self.assertEqual(afficher("+14505551234"), "450 555-1234")
        self.assertEqual(afficher(""), "")


@override_settings(ALLOWED_HOSTS=["*"])
class PlateformeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from decimal import Decimal as D
        from clients.models import Client
        from communications.models import ArchiveCourriel, EtatBoite, Message
        from facturation.models import Facture
        cls.louis = Entreprise.objects.create(nom="Louis", slug="louis", domaine="louis.exemple.test")
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.exemple.test")
        c = Client.objects.create(entreprise=cls.louis, nom="Tremblay")
        m = dict(entreprise=cls.louis, client=c, genre="manuel", contenu="Bonjour")
        Message.objects.create(canal="courriel", destinataire="a@b.c", statut="envoye", fournisseur_id="<1@x>", **m)
        Message.objects.create(canal="courriel", destinataire="a@b.c", statut="prepare", **m)  # pas parti : ne compte pas
        Message.objects.create(canal="courriel", sens="entrant", statut="recu", **m)
        Message.objects.create(canal="texto", destinataire="+1", statut="envoye", fournisseur_id="SM1", **{**m, "contenu": "ê" + "a" * 80})
        Message.objects.create(canal="texto", destinataire="+1", statut="echec", **m)
        Message.objects.create(canal="courriel", destinataire="a@b.c", statut="envoye", fournisseur_id="<2@x>", **{**m, "genre": "relance_1"})
        f = Facture.objects.create(entreprise=cls.louis, client=c)
        f.lignes.create(description="Déneigement", quantite=1, prix_unitaire=D("400.00"), taxable=False)
        f.recalculer()
        f.emettre()
        EtatBoite.objects.create(entreprise=cls.louis, dossier="INBOX", quota_utilise_ko=1800000, quota_max_ko=2097152)
        ArchiveCourriel.objects.create(entreprise=cls.louis, dossier="INBOX", uidvalidite=1, uid=1, taille=3 * 1024 * 1024, empreinte="x", brut=b"")
        U = get_user_model()
        cls.jf = U.objects.create_superuser("jf", password="x" * 12)
        cls.employe = U.objects.create_user("employe", password="x" * 12, is_staff=True)

    def test_chiffres_du_mois(self):
        from django.utils import timezone
        from core import plateforme
        aujourdhui = timezone.localdate()
        lignes, total = plateforme.statistiques(*plateforme.mois(aujourdhui.year, aujourdhui.month))
        louis = next(l for l in lignes if l["entreprise"] == self.louis)
        self.assertEqual((louis["courriels_envoyes"], louis["courriels_recus"], louis["textos_envoyes"], louis["segments"], louis["echecs"]),
                         (2, 1, 1, 2, 1))
        self.assertEqual((louis["relances"], louis["factures_emises"], louis["montant_facture"], louis["clients_servis"]), (1, 1, 400, 1))
        self.assertEqual((louis["boite_utilisee_mo"], louis["boite_permise_mo"], louis["boite_pourcent"], louis["archives_mo"]), (1757.8, 2048, 86, 3.0))
        autre = next(l for l in lignes if l["entreprise"] == self.autre)
        self.assertEqual((autre["courriels_envoyes"], autre["boite_utilisee_mo"]), (0, None))
        self.assertEqual(total["courriels_envoyes"], 2)
        lignes, _ = plateforme.statistiques(*plateforme.mois(2020, 1))
        self.assertEqual(next(l for l in lignes if l["entreprise"] == self.louis)["courriels_envoyes"], 0)

    def test_ecran_reserve_au_superutilisateur(self):
        self.client.defaults["HTTP_HOST"] = "louis.exemple.test"
        self.client.force_login(self.employe)
        self.assertEqual(self.client.get("/admin/plateforme/").status_code, 403)
        self.client.force_login(self.jf)
        page = self.client.get("/admin/plateforme/")
        self.assertContains(page, "Segments de textos")
        self.assertContains(page, 'class="alerte"')  # boîte à 86 %
        self.assertContains(self.client.get("/admin/"), "Usage par entreprise")
        csv = self.client.get("/admin/plateforme/?format=csv")
        self.assertEqual(csv["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Louis;louis;2;1;1;2", csv.content.decode("utf-8-sig"))
