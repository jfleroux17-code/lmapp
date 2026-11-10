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
        self.assertContains(self.client.get("/admin/"), "Courriels, textos, factures, espace par entreprise")
        csv = self.client.get("/admin/plateforme/?format=csv")
        self.assertEqual(csv["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("Louis;louis;2;1;1;2", csv.content.decode("utf-8-sig"))


class AjouterDeneigeurTests(TestCase):
    def appeler(self, *args):
        from io import StringIO
        from django.core.management import call_command
        sortie = StringIO()
        call_command("ajouter_deneigeur", *args, stdout=sortie)
        return sortie.getvalue()

    def test_essai_a_blanc_puis_creation(self):
        from core.models import Membre, VilleDesservie
        base = ["martin", "--nom", "Déneigement Martin", "--ville", "Saint-Sauveur", "--utilisateur", "martin"]
        self.assertIn("ESSAI À BLANC", self.appeler(*base))
        self.assertFalse(Entreprise.objects.filter(slug="martin").exists())
        sortie = self.appeler(*base, "--appliquer")
        e = Entreprise.objects.get(slug="martin")
        self.assertEqual((e.domaine, e.courriel_reponse, e.envois_actifs, e.mode), ("martin.ledeneigeur.com", "martin@ledeneigeur.com", False, "seul"))
        self.assertTrue(VilleDesservie.objects.get(entreprise=e).par_defaut)
        m = Membre.objects.get(entreprise=e)
        self.assertEqual((m.utilisateur.username, m.role, m.utilisateur.has_usable_password()), ("martin", "admin", False))
        self.assertIn("reverse_proxy lmapp-prod-app:8000", sortie)
        self.assertIn("changepassword martin", sortie)

    def test_refus(self):
        from django.core.management.base import CommandError
        with self.assertRaisesMessage(CommandError, "minuscules"):
            self.appeler("Martin Gagné", "--nom", "x", "--ville", "x", "--utilisateur", "x")
        Entreprise.objects.create(nom="Louis", slug="louis", domaine="louis.ledeneigeur.com")
        with self.assertRaisesMessage(CommandError, "existe déjà"):
            self.appeler("louis", "--nom", "x", "--ville", "x", "--utilisateur", "x", "--appliquer")


@override_settings(ALLOWED_HOSTS=["*"])
class AdminNeutreTests(TestCase):
    def test_admin_seulement_sur_l_adresse_neutre(self):
        jf = get_user_model().objects.create_superuser("jf", password="x" * 12)
        self.client.force_login(jf)
        self.assertEqual(self.client.get("/admin/", HTTP_HOST="louis.exemple.test").status_code, 200)  # variable vide : comme avant
        with self.settings(LMAPP_HOTE_ADMIN="admin.exemple.test"):
            self.assertEqual(self.client.get("/admin/", HTTP_HOST="louis.exemple.test").status_code, 404)
            self.assertEqual(self.client.get("/admin/plateforme/", HTTP_HOST="louis.exemple.test").status_code, 404)
            self.assertEqual(self.client.get("/admin/", HTTP_HOST="admin.exemple.test").status_code, 200)
            self.assertEqual(self.client.get("/sante/", HTTP_HOST="louis.exemple.test").status_code, 200)


class NotificationsTests(TestCase):
    """E8 : Web Push. Chiffrement vérifié en le déchiffrant comme le ferait le téléphone."""

    @classmethod
    def setUpTestData(cls):
        from core.models import Membre
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine="essai.exemple.test")
        U = get_user_model()
        cls.louis = U.objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")
        cls.lecteur = U.objects.create_user("lecteur", password="x" * 12)
        Membre.objects.create(utilisateur=cls.lecteur, entreprise=cls.ent, role="lecture")

    def setUp(self):
        from core.notifications import nouvelles_cles
        self.prive, self.public = nouvelles_cles()

    def _telephone(self):
        """Clés d'un faux téléphone abonné."""
        import base64, os
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        cle = ec.generate_private_key(ec.SECP256R1())
        b = lambda o: base64.urlsafe_b64encode(o).decode().rstrip("=")  # noqa: E731
        pub = cle.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return cle, os.urandom(16), b(pub)

    def test_chiffrement_et_envoi(self):
        import json
        from unittest import mock
        import http_ece
        from core import notifications
        from core.models import AbonnementNotification
        cle_tel, auth, p256dh = self._telephone()
        import base64
        a = AbonnementNotification.objects.create(utilisateur=self.louis, entreprise=self.ent, endpoint="https://push.exemple.test/abc",
                                                  p256dh=p256dh, auth=base64.urlsafe_b64encode(auth).decode().rstrip("="))
        with override_settings(VAPID_CLE_PRIVEE=self.prive, VAPID_CLE_PUBLIQUE=self.public), \
             mock.patch("core.notifications.urlopen") as u:
            self.assertTrue(notifications.envoyer(a, "Courriel de Tremblay", "Je paie demain", "/messages/1/"))
        req = u.call_args.args[0]
        self.assertEqual((req.full_url, req.get_header("Content-encoding"), req.get_header("Ttl")), ("https://push.exemple.test/abc", "aes128gcm", "86400"))
        self.assertTrue(req.get_header("Authorization").startswith("vapid t="))
        clair = http_ece.decrypt(req.data, private_key=cle_tel, auth_secret=auth, version="aes128gcm")
        self.assertEqual(json.loads(clair), {"titre": "Courriel de Tremblay", "corps": "Je paie demain", "url": "/messages/1/"})
        a.refresh_from_db()
        self.assertIsNotNone(a.dernier_envoi)

    def test_abonnement_expire_efface(self):
        import io
        from unittest import mock
        from urllib.error import HTTPError
        from core import notifications
        from core.models import AbonnementNotification
        _, _, p256dh = self._telephone()
        a = AbonnementNotification.objects.create(utilisateur=self.louis, entreprise=self.ent, endpoint="https://push.exemple.test/x",
                                                  p256dh=p256dh, auth="AAAAAAAAAAAAAAAAAAAAAA")
        with override_settings(VAPID_CLE_PRIVEE=self.prive, VAPID_CLE_PUBLIQUE=self.public), \
             mock.patch("core.notifications.urlopen", side_effect=HTTPError("u", 410, "Gone", {}, io.BytesIO(b""))):
            self.assertFalse(notifications.envoyer(a, "t", "c"))
        self.assertFalse(AbonnementNotification.objects.exists())

    def test_tache_pas_pour_la_lecture_seule(self):
        from unittest import mock
        from core.models import AbonnementNotification
        from core.tasks import notifier
        _, _, p256dh = self._telephone()
        AbonnementNotification.objects.create(utilisateur=self.louis, entreprise=self.ent, endpoint="https://push.exemple.test/1", p256dh=p256dh, auth="AA")
        AbonnementNotification.objects.create(utilisateur=self.lecteur, entreprise=self.ent, endpoint="https://push.exemple.test/2", p256dh=p256dh, auth="AA")
        with override_settings(VAPID_CLE_PRIVEE=self.prive, VAPID_CLE_PUBLIQUE=self.public), \
             mock.patch("core.notifications.envoyer", return_value=True) as e:
            self.assertEqual(notifier.func(self.ent.pk, "t", "c"), 1)
        self.assertEqual(e.call_args.args[0].endpoint, "https://push.exemple.test/1")
        with override_settings(VAPID_CLE_PRIVEE=""):
            self.assertEqual(notifier.func(self.ent.pk, "t", "c"), 0)

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_abonnement_par_le_navigateur(self):
        import json
        from core.models import AbonnementNotification
        self.client.defaults["HTTP_HOST"] = "essai.exemple.test"
        self.client.force_login(self.louis)
        corps = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": "BXYZ", "auth": "AUTH"}}
        r = self.client.post("/notifications/abonnement/", json.dumps(corps), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        a = AbonnementNotification.objects.get()
        self.assertEqual((a.utilisateur, a.entreprise, a.auth), (self.louis, self.ent, "AUTH"))
        self.assertEqual(self.client.post("/notifications/abonnement/", "{}", content_type="application/json").status_code, 400)
        self.client.generic("DELETE", "/notifications/abonnement/", json.dumps({"endpoint": "https://web.push.apple.com/abc"}), content_type="application/json")
        self.assertFalse(AbonnementNotification.objects.exists())
        with override_settings(VAPID_CLE_PUBLIQUE="CLE"):
            self.assertContains(self.client.get("/messages/"), "Être averti quand un client écrit.")
