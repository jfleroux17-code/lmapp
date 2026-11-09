from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from core import surveillance


class VeilleurTests(TestCase):
    """Alertes : seuils, répétition aux 6 heures, « Rétabli », texto seulement pour les pannes graves."""

    def setUp(self):
        self.textos, self.courriels, self.t = [], [], timezone.now()
        self.fin_silence = None
        self.v = surveillance.Veilleur(envoyer_texto=self.textos.append, envoyer_courriel=lambda s, t: self.courriels.append(s),
                                       maintenant=lambda: self.t, silence=lambda: self.fin_silence)
        self.v.demarre_le = self.t - timedelta(minutes=10)  # délai de grâce du démarrage passé

    def test_silence_puis_alerte_si_la_panne_dure(self):
        self.fin_silence = self.t + timedelta(minutes=20)
        self.v.traiter({"worker": (False, "pas de battement")})
        self.v.traiter({"worker": (False, "pas de battement")})
        self.assertEqual((self.textos, self.courriels), ([], []))
        self.fin_silence = None
        self.v.traiter({"worker": (False, "pas de battement")})
        self.assertEqual(len(self.textos), 1)

    def test_silence_panne_reglee_pendant_le_silence_rien_ne_part(self):
        self.fin_silence = self.t + timedelta(minutes=20)
        self.v.traiter({"worker": (False, "x")})
        self.v.traiter({"worker": (True, "")})
        self.fin_silence = None
        self.v.traiter({"worker": (True, "")})
        self.assertEqual((self.textos, self.courriels), ([], []))

    def test_retabli_pendant_le_silence_par_courriel_seulement(self):
        self.v.traiter({"worker": (False, "x")})
        self.assertEqual(len(self.textos), 1)
        self.fin_silence = self.t + timedelta(minutes=20)
        self.v.traiter({"worker": (True, "")})
        self.assertEqual(len(self.textos), 1)
        self.assertEqual(self.courriels[-1][:len("[Le Déneigeur")], "[Le Déneigeur")
        self.assertIn("Rétabli", self.courriels[-1])

    def test_grace_au_demarrage(self):
        self.v.demarre_le = self.t - timedelta(minutes=1)
        self.v.traiter({"worker": (False, "x")})
        self.assertEqual(self.textos, [])
        self.t += timedelta(minutes=3)
        self.v.traiter({"worker": (False, "x")})
        self.assertEqual(len(self.textos), 1)

    def test_fichier_de_silence(self):
        import tempfile
        from django.test import override_settings
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(str(int((timezone.now() + timedelta(minutes=10)).timestamp())))
        with override_settings(LMAPP_SILENCE_FICHIER=f.name):
            self.assertIsNotNone(surveillance.silence_jusqu_a())
            with open(f.name, "w") as g:
                g.write(str(int((timezone.now() - timedelta(minutes=1)).timestamp())))
            self.assertIsNone(surveillance.silence_jusqu_a())
            with open(f.name, "w") as g:
                g.write("n'importe quoi")
            self.assertIsNone(surveillance.silence_jusqu_a())
        with override_settings(LMAPP_SILENCE_FICHIER="/nexiste/pas"):
            self.assertIsNone(surveillance.silence_jusqu_a())

    def test_https_au_deuxieme_echec_puis_retabli(self):
        self.v.traiter({"https louis.x": (False, "délai")})
        self.assertEqual(self.textos, [])
        self.v.traiter({"https louis.x": (False, "délai")})
        self.assertEqual(len(self.textos), 1)
        self.assertIn("Panne : https louis.x", self.textos[0])
        self.v.traiter({"https louis.x": (True, "")})
        self.assertIn("Rétabli", self.textos[-1])

    def test_repetition_aux_6_heures(self):
        for _ in range(3):
            self.v.traiter({"worker": (False, "rien")})
        self.assertEqual(len(self.textos), 1)
        self.t += timedelta(hours=6, minutes=1)
        self.v.traiter({"worker": (False, "rien")})
        self.assertIn("Toujours en panne", self.textos[-1])

    def test_disque_par_courriel_seulement(self):
        self.v.traiter({"disque": (False, "à 75 %")})
        self.assertEqual(self.textos, [])
        self.assertEqual(len(self.courriels), 1)


class VerificationsTests(TestCase):
    def test_base_worker_et_file(self):
        from django.db import connection
        self.assertEqual(surveillance.verifier_base(), (True, ""))
        with connection.cursor() as c:
            c.execute("DELETE FROM procrastinate_workers")
        ok, detail = surveillance.verifier_worker()
        self.assertFalse(ok)
        with connection.cursor() as c:
            c.execute("INSERT INTO procrastinate_workers (last_heartbeat) VALUES (now())")
        self.assertTrue(surveillance.verifier_worker()[0])
        self.assertTrue(surveillance.verifier_file()[0])

    def test_message_en_file_trop_longtemps(self):
        from communications.models import Message
        from core.models import Entreprise
        e = Entreprise.objects.create(nom="E", slug="e-surv", domaine="e.exemple.test")
        m = Message.objects.create(entreprise=e, genre="manuel", canal="texto", destinataire="+15145550123", contenu="x", statut="en_file")
        Message.objects.filter(pk=m.pk).update(modifie_le=timezone.now() - timedelta(minutes=11))
        ok, detail = surveillance.verifier_file()
        self.assertFalse(ok)
        self.assertIn("1 message(s)", detail)

    def test_sauvegarde_et_disque(self):
        import tempfile, time
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(str(int(time.time()) - 14 * 3600))
        with override_settings(LMAPP_SAUVEGARDE_TEMOIN=f.name):
            self.assertFalse(surveillance.verifier_sauvegarde()[0])
        with override_settings(LMAPP_SAUVEGARDE_TEMOIN="/nulle/part"):
            self.assertFalse(surveillance.verifier_sauvegarde()[0])
        with override_settings(LMAPP_DISQUE_SEUIL=101):
            self.assertTrue(surveillance.verifier_disque()[0])
        with override_settings(LMAPP_DISQUE_SEUIL=0):
            self.assertFalse(surveillance.verifier_disque()[0])

    @override_settings(ALLOWED_HOSTS=["louis.exemple.test", "localhost"], LMAPP_HOTE_ADMIN="", LMAPP_SURVEILLANCE_HOTES=[])
    def test_https_injoignable(self):
        with mock.patch("core.surveillance.socket.create_connection", side_effect=OSError("refusé")):
            r = surveillance.verifier_https()
        self.assertEqual(list(r), ["louis.exemple.test"])
        self.assertFalse(r["louis.exemple.test"][0])


class CompteAlertesTests(TestCase):
    def envoyer(self):
        from unittest import mock

        from core import surveillance

        envoi = {}

        class Smtp:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def login(self, u, p):
                envoi["login"] = (u, p)

            def send_message(self, m):
                envoi["de"] = m["From"]

        with mock.patch("smtplib.SMTP_SSL", Smtp):
            self.assertTrue(surveillance.envoyer_courriel("Essai", "texte"))
        return envoi

    @override_settings(LMAPP_ALERTES_COURRIEL="jf@exemple.test", SMTP_HOTE="smtp.exemple.test", IMAP_UTILISATEUR="louis@exemple.test",
                       IMAP_MOT_DE_PASSE="l", PLATEFORME_IMAP_UTILISATEUR="info@exemple.test", PLATEFORME_IMAP_MOT_DE_PASSE="i")
    def test_alertes_partent_de_la_boite_de_la_plateforme(self):
        e = self.envoyer()
        self.assertEqual((e["login"], e["de"]), (("info@exemple.test", "i"), '"Le Déneigeur (surveillance)" <info@exemple.test>'))

    @override_settings(LMAPP_ALERTES_COURRIEL="jf@exemple.test", SMTP_HOTE="smtp.exemple.test", IMAP_UTILISATEUR="louis@exemple.test",
                       IMAP_MOT_DE_PASSE="l", PLATEFORME_IMAP_UTILISATEUR="", PLATEFORME_IMAP_MOT_DE_PASSE="")
    def test_sinon_la_boite_du_deneigeur(self):
        self.assertEqual(self.envoyer()["login"], ("louis@exemple.test", "l"))
