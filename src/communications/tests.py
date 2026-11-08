import base64
import hashlib
from datetime import date, timedelta
from decimal import Decimal as D
import io
import json
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.contrib.gis.geos import Point
from django.test import TestCase, override_settings

from clients.models import Adresse, Client, Secteur
from communications import avis, envoi, twilio
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
        with override_settings(TWILIO_ACCOUNT_SID="", TWILIO_AUTH_TOKEN=""):
            self.assertEqual(envoi.envoyer(m).statut, "prepare")  # aucun fournisseur : rien ne part
        with override_settings(TWILIO_ACCOUNT_SID="AC-essai", TWILIO_AUTH_TOKEN="essai"):
            self.assertEqual(envoi.envoyer(m).statut, "prepare")  # envois réels éteints (défaut)
            self.assertIn("éteints", m.erreur)
            Entreprise.objects.filter(pk=self.ent.pk).update(envois_actifs=True)
            m.entreprise.refresh_from_db()
            self.assertEqual(envoi.envoyer(m).statut, "prepare")  # pas de numéro de texto d'affaires
            self.assertIn("Numéro", m.erreur)
            Entreprise.objects.filter(pk=self.ent.pk).update(numero_texto="+14503001166")
            m.entreprise.refresh_from_db()
            self.assertEqual(envoi.envoyer(m).statut, "bloque")  # tout est là, mais destinataire non permis en test
            self.assertFalse(envoi.destinataire_permis("+14505550199"))
            with override_settings(LMAPP_DESTINATAIRES_TEST=["+14505550199"]):
                self.assertTrue(envoi.destinataire_permis("+14505550199"))
                with mock.patch("communications.tasks.envoyer_message.defer") as defer:
                    with self.captureOnCommitCallbacks(execute=True) as rappels:
                        self.assertEqual(envoi.envoyer(m).statut, "en_file")
                        defer.assert_not_called()  # seulement après la transaction
                self.assertEqual(len(rappels), 1)
                defer.assert_called_once_with(message_id=m.pk)
            with override_settings(LMAPP_ENV="prod"):
                self.assertTrue(envoi.destinataire_permis("+14505550199"))


@override_settings(TWILIO_ACCOUNT_SID="AC-essai", TWILIO_AUTH_TOKEN="jeton", TWILIO_API="https://api.exemple.test")
class EnvoiTwilioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE, numero_texto="+14503001166", envois_actifs=True)

    def message(self, statut="en_file"):
        return Message.objects.create(entreprise=self.ent, genre="manuel", canal="texto", destinataire="+14505550199",
                                      contenu="Bonjour", statut=statut)

    def tache(self, m, essais_faits=0):
        from types import SimpleNamespace
        from communications.tasks import envoyer_message
        return envoyer_message.func(SimpleNamespace(job=SimpleNamespace(attempts=essais_faits)), message_id=m.pk)

    def test_appel_a_twilio(self):
        reponse = mock.MagicMock()
        reponse.__enter__.return_value = io.BytesIO(b'{"sid": "SM123"}')
        with mock.patch("communications.twilio.urlopen", return_value=reponse) as u:
            self.assertEqual(twilio.envoyer_texto("+14503001166", "+14505550199", "Allo"), "SM123")
        req = u.call_args.args[0]
        self.assertEqual(req.full_url, "https://api.exemple.test/2010-04-01/Accounts/AC-essai/Messages.json")
        self.assertEqual(parse_qs(req.data.decode()), {"From": ["+14503001166"], "To": ["+14505550199"], "Body": ["Allo"]})
        self.assertEqual(req.get_header("Authorization"), "Basic " + base64.b64encode(b"AC-essai:jeton").decode())

    def test_erreurs_de_twilio(self):
        def erreur(code, corps):
            return HTTPError("u", code, "x", {}, io.BytesIO(corps))
        with mock.patch("communications.twilio.urlopen", side_effect=erreur(400, b'{"code": 21211, "message": "Invalid To"}')):
            with self.assertRaisesMessage(twilio.Refuse, "Twilio 21211 : Invalid To"):
                twilio.envoyer_texto("a", "b", "c")
        for e, attendue in [(erreur(503, b"panne"), twilio.Indisponible), (erreur(429, b"{}"), twilio.Indisponible),
                            (URLError("dns"), twilio.Indisponible), (TimeoutError(), twilio.Incertain)]:
            with mock.patch("communications.twilio.urlopen", side_effect=e), self.assertRaises(attendue):
                twilio.envoyer_texto("a", "b", "c")

    def test_tache_envoye(self):
        m = self.message()
        with mock.patch("communications.twilio.envoyer_texto", return_value="SM9") as t:
            self.assertEqual(self.tache(m), "envoye")
        t.assert_called_once_with("+14503001166", "+14505550199", "Bonjour")
        m.refresh_from_db()
        self.assertEqual((m.statut, m.fournisseur_id), ("envoye", "SM9"))
        self.assertIsNotNone(m.envoye_le)
        with mock.patch("communications.twilio.envoyer_texto") as t:
            self.assertEqual(self.tache(m), "rien à faire")  # tâche en double : pas de deuxième texto
        t.assert_not_called()

    def test_tache_refus_et_reessais(self):
        m = self.message()
        with mock.patch("communications.twilio.envoyer_texto", side_effect=twilio.Refuse("Twilio 21610 : désabonné")):
            self.assertEqual(self.tache(m), "echec")
        m.refresh_from_db()
        self.assertEqual(m.erreur, "Twilio 21610 : désabonné")
        m = self.message()
        with mock.patch("communications.twilio.envoyer_texto", side_effect=twilio.Indisponible("panne")):
            with self.assertRaises(twilio.Indisponible):
                self.tache(m, essais_faits=0)  # Procrastinate réessaiera
            m.refresh_from_db()
            self.assertEqual(m.statut, "en_file")
            self.assertEqual(self.tache(m, essais_faits=4), "echec")  # dernier essai
        m = self.message(statut="prepare")
        with mock.patch("communications.twilio.envoyer_texto") as t:
            self.assertEqual(self.tache(m), "rien à faire")
        t.assert_not_called()


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


@override_settings(ALLOWED_HOSTS=["*"], LMAPP_ENV="test", LMAPP_DESTINATAIRES_TEST=["client@example.com"],
                   SMTP_HOTE="smtp.exemple.test", IMAP_HOTE="imap.exemple.test", IMAP_UTILISATEUR="louis@exemple.test",
                   IMAP_MOT_DE_PASSE="secret", COURRIEL_HELO="ld1.exemple.test")
class CourrielTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from facturation.models import Facture
        cls.ent = Entreprise.objects.create(nom="Entretiens Essai", nom_legal="Les Entretiens Essai inc.", slug="essai", domaine=HOTE,
                                            envois_actifs=True, courriel_reponse="louis@exemple.test", telephone="+14505550100",
                                            interac_courriel="paiement@example.com", prochain_numero_facture=57,
                                            signature_messages="Entretiens Essai, 450 555-0100")
        cls.c = Client.objects.create(entreprise=cls.ent, prenom="Ginette", nom="Tremblay", courriel="client@example.com")
        cls.f = Facture.objects.create(entreprise=cls.ent, client=cls.c)
        cls.f.lignes.create(description="Déneigement", quantite=1, prix_unitaire=D("400.00"), taxable=False)
        cls.f.recalculer()
        cls.f.emettre()
        U = get_user_model()
        cls.louis = U.objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")

    def message(self, **kw):
        d = dict(entreprise=self.ent, client=self.c, genre="manuel", canal="courriel", destinataire="client@example.com",
                 sujet="Allo", contenu="Bonjour\n\nDeuxième paragraphe", statut="en_file")
        d.update(kw)
        return Message.objects.create(**d)

    def test_garde_fous_du_courriel(self):
        m = self.message(statut="prepare")
        with mock.patch("communications.tasks.envoyer_message.defer"):
            self.assertEqual(envoi.envoyer(m).statut, "en_file")
            with override_settings(IMAP_UTILISATEUR="autre@exemple.test"):
                self.assertEqual(envoi.envoyer(m).statut, "prepare")  # l'adresse de la fiche n'est pas le compte configuré
                self.assertIn("compte courriel", m.erreur)
            with override_settings(SMTP_HOTE=""):
                self.assertEqual(envoi.envoyer(m).statut, "prepare")
            autre = self.message(destinataire="inconnu@example.com", statut="prepare")
            self.assertEqual(envoi.envoyer(autre).statut, "bloque")

    def test_construction_avec_pdf_et_html(self):
        from communications import courriel
        m = self.message(facture=self.f)
        with mock.patch("facturation.pdf.rendre", return_value=b"%PDF-1.7 essai"):
            e = courriel.construire(m)
        self.assertEqual(e["From"].addresses[0].addr_spec, "louis@exemple.test")
        self.assertEqual(e["From"].addresses[0].display_name, "Entretiens Essai")
        self.assertTrue(e["Message-ID"].endswith("@exemple.test>"))
        types = [p.get_content_type() for p in e.walk()]
        self.assertIn("text/plain", types)
        self.assertIn("text/html", types)
        piece = next(e.iter_attachments())
        self.assertEqual(piece.get_filename(), "facture-57.pdf")
        self.assertEqual(piece.get_content(), b"%PDF-1.7 essai")
        html = e.get_body(("html",)).get_content()
        self.assertIn("<p", html)
        self.assertIn("Deuxième paragraphe", html)
        self.assertIn("450 555-0100", html)  # téléphone lisible, pas en E.164

    def test_envoi_smtp_et_copie_dans_les_envoyes(self):
        from communications import courriel
        m = self.message()
        with mock.patch("communications.courriel.smtplib.SMTP_SSL") as smtp, mock.patch("communications.courriel.imaplib.IMAP4_SSL") as imap:
            mid = courriel.envoyer_courriel(m)
        self.assertEqual(smtp.call_args.kwargs["local_hostname"], "ld1.exemple.test")
        smtp.return_value.login.assert_called_once_with("louis@exemple.test", "secret")
        envoye = smtp.return_value.send_message.call_args.args[0]
        self.assertEqual(envoye["Message-ID"], mid)
        imap.return_value.__enter__.return_value.append.assert_called_once()
        self.assertEqual(imap.return_value.__enter__.return_value.append.call_args.args[0], "INBOX.Sent")

    def test_erreurs_smtp(self):
        import smtplib
        from communications import courriel, erreurs
        m = self.message()
        cas = [
            ({"side_effect": OSError("réseau")}, None, erreurs.Indisponible),
            ({}, ("login", smtplib.SMTPAuthenticationError(535, b"non")), erreurs.Refuse),
            ({}, ("send_message", smtplib.SMTPRecipientsRefused({"client@example.com": (550, b"inconnu")})), erreurs.Refuse),
            ({}, ("send_message", smtplib.SMTPRecipientsRefused({"client@example.com": (451, b"plus tard")})), erreurs.Indisponible),
            ({}, ("send_message", smtplib.SMTPServerDisconnected("coupé")), erreurs.Incertain),
        ]
        for ouverture, methode, attendue in cas:
            with mock.patch("communications.courriel.smtplib.SMTP_SSL", **ouverture) as smtp, \
                 mock.patch("communications.courriel.imaplib.IMAP4_SSL") as imap, self.subTest(attendue=attendue, methode=methode):
                if methode:
                    getattr(smtp.return_value, methode[0]).side_effect = methode[1]
                with self.assertRaises(attendue):
                    courriel.envoyer_courriel(m)
                imap.assert_not_called()  # pas de copie si le courriel n'est pas parti

    def test_copie_impossible_n_empeche_pas_l_envoi(self):
        from communications import courriel
        with mock.patch("communications.courriel.smtplib.SMTP_SSL"), \
             mock.patch("communications.courriel.imaplib.IMAP4_SSL", side_effect=OSError("imap en panne")):
            self.assertTrue(courriel.envoyer_courriel(self.message()))

    def test_tache_courriel(self):
        from types import SimpleNamespace
        from communications.tasks import envoyer_message
        m = self.message()
        with mock.patch("communications.courriel.envoyer_courriel", return_value="<1@exemple.test>") as c:
            self.assertEqual(envoyer_message.func(SimpleNamespace(job=SimpleNamespace(attempts=0)), message_id=m.pk), "envoye")
        c.assert_called_once()
        m.refresh_from_db()
        self.assertEqual(m.fournisseur_id, "<1@exemple.test>")

    def test_envoi_de_la_facture(self):
        from communications import factures
        from facturation.models import Facture
        with mock.patch("communications.tasks.envoyer_message.defer"):
            m = factures.envoyer_facture(self.f)
        self.assertEqual((m.statut, m.genre, m.facture, m.destinataire), ("en_file", "facture", self.f, "client@example.com"))
        self.assertEqual(m.sujet, "Facture n° 57 : Entretiens Essai")
        self.assertIn("Bonjour Ginette Tremblay", m.contenu)
        self.assertIn("facture n° 57", m.contenu)
        self.assertIn("400,00", m.contenu)
        self.assertIn("Interac à paiement@example.com, en indiquant le numéro de facture 57", m.contenu)
        self.assertTrue(m.contenu.endswith("Entretiens Essai, 450 555-0100"))
        brouillon = Facture.objects.create(entreprise=self.ent, client=self.c)
        with self.assertRaises(ValidationError):
            factures.envoyer_facture(brouillon)
        Client.objects.filter(pk=self.c.pk).update(courriel="")
        self.f.client.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "pas d'adresse courriel"):
            factures.envoyer_facture(self.f)

    def test_bouton_sur_la_facture(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)
        page = self.client.get(f"/factures/{self.f.pk}/")
        self.assertContains(page, "Envoyer par courriel")
        with mock.patch("communications.tasks.envoyer_message.defer"):
            r = self.client.post(f"/factures/{self.f.pk}/courriel/", follow=True)
        self.assertContains(r, "Facture en route vers client@example.com")
        self.assertContains(r, "Envoyer par courriel de nouveau")
        self.assertContains(r, "En file")


@override_settings(ALLOWED_HOSTS=["*"], LMAPP_ENV="test", LMAPP_DESTINATAIRES_TEST=["client@example.com", "+14505550101"],
                   SMTP_HOTE="smtp.exemple.test", IMAP_HOTE="", IMAP_UTILISATEUR="louis@exemple.test", IMAP_MOT_DE_PASSE="secret",
                   TWILIO_ACCOUNT_SID="AC-essai", TWILIO_AUTH_TOKEN="jeton")
class RelanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from facturation.models import Facture
        cls.ent = Entreprise.objects.create(nom="Entretiens Essai", slug="essai", domaine=HOTE, envois_actifs=True,
                                            courriel_reponse="louis@exemple.test", numero_texto="+14503001166",
                                            interac_courriel="paiement@example.com", prochain_numero_facture=57,
                                            signature_messages="Entretiens Essai")
        cls.c = Client.objects.create(entreprise=cls.ent, prenom="Ginette", nom="Tremblay", courriel="client@example.com",
                                      cellulaire="+14505550101", canal_prefere="les_deux", desabonne_le="2026-11-01T00:00:00Z")
        cls.vieux = Facture.solde_ouverture(cls.c, D("120.00"), saison_origine="2024-2025", date_facture=date(2026, 10, 1))
        cls.f = Facture.objects.create(entreprise=cls.ent, client=cls.c, date_facture=date(2026, 11, 2))
        cls.f.lignes.create(description="Déneigement", quantite=1, prix_unitaire=D("400.00"), taxable=False)
        cls.f.recalculer()
        cls.f.emettre()
        U = get_user_model()
        cls.louis = U.objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")

    def setUp(self):
        self.defer = mock.patch("communications.tasks.envoyer_message.defer").start()
        self.addCleanup(mock.patch.stopall)

    def test_relance_par_les_deux_canaux_avec_factures_jointes(self):
        from communications import relances
        ms = relances.relancer(self.c)
        self.assertEqual([(m.canal, m.statut, m.genre) for m in ms], [("courriel", "en_file", "relance_1"), ("texto", "en_file", "relance_1")])
        courriel = ms[0]
        self.assertEqual(courriel.sujet, "Rappel : solde de 520,00 $, Entretiens Essai")
        self.assertIn("Bonjour Ginette Tremblay, petit rappel : votre compte montre un solde de 520,00", courriel.contenu)
        self.assertIn("(solde antérieur 2024-2025, facture n° 57)", courriel.contenu)
        self.assertIn("Interac à paiement@example.com, en indiquant le numéro de facture 57.", courriel.contenu)
        self.assertEqual(list(courriel.factures_jointes.order_by("date_facture")), [self.vieux, self.f])
        self.assertFalse(ms[1].factures_jointes.exists())  # texto : le montant seulement

    def test_ton_gradue_et_une_par_24_heures(self):
        from django.utils import timezone
        from communications import relances
        relances.relancer(self.c)
        with self.assertRaisesMessage(ValidationError, "24 heures"):
            relances.relancer(self.c)
        Message.objects.update(cree_le=timezone.now() - timedelta(days=10))
        self.assertEqual(relances.niveau_suivant(self.c), 2)
        ms = relances.relancer(self.c)
        self.assertEqual(ms[0].genre, "relance_2")
        self.assertIn("impayé depuis le 1 octobre 2026", ms[0].contenu)
        Message.objects.update(cree_le=timezone.now() - timedelta(days=10))
        relances.relancer(self.c)
        Message.objects.update(cree_le=timezone.now() - timedelta(days=10))
        self.assertEqual(relances.niveau_suivant(self.c), 3)  # plafonné au dernier avis
        self.assertEqual(relances.relancer(self.c, niveau=1)[0].genre, "relance_1")  # Louis peut choisir

    def test_les_relances_non_parties_ne_comptent_pas(self):
        from communications import relances
        Entreprise.objects.filter(pk=self.ent.pk).update(envois_actifs=False)
        self.c.entreprise.refresh_from_db()
        ms = relances.relancer(self.c)
        self.assertEqual({m.statut for m in ms}, {"prepare"})
        self.assertEqual(relances.niveau_suivant(self.c), 1)
        relances.relancer(self.c)  # pas bloqué par la règle des 24 heures

    def test_canaux_selon_la_preference(self):
        from communications import relances
        c = self.c
        for pref, cell, courriel, attendu in [("texto", "+1", "a@b.c", ["texto"]), ("courriel", "+1", "a@b.c", ["courriel"]),
                                              ("courriel", "+1", "", ["texto"]), ("texto", "", "a@b.c", ["courriel"]),
                                              ("les_deux", "", "a@b.c", ["courriel"]), ("texto", "", "", [])]:
            c.canal_prefere, c.cellulaire, c.courriel = pref, cell, courriel
            self.assertEqual(relances.canaux(c), attendu, pref)

    def test_rien_a_relancer(self):
        from communications import relances
        autre = Client.objects.create(entreprise=self.ent, nom="Payé", courriel="x@example.com")
        with self.assertRaisesMessage(ValidationError, "ne doit rien"):
            relances.relancer(autre)

    def test_ecrans(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)
        fiche = self.client.get(f"/clients/{self.c.pk}/")
        self.assertContains(fiche, "Relancer : 520,00")
        self.assertContains(fiche, "Par courriel et texto")
        r = self.client.post(f"/clients/{self.c.pk}/relance/", {"niveau": "2"}, follow=True)
        self.assertContains(r, "Deuxième avis en route : client@example.com, +14505550101.")
        self.assertContains(r, "Deuxième avis · courriel")
        comptes = self.client.get("/comptes/")
        self.assertContains(comptes, "Deuxième avis le")
        r = self.client.post(f"/clients/{self.c.pk}/relance/", follow=True)
        self.assertContains(r, "24 heures")

    def test_courriel_de_relance_joint_chaque_facture(self):
        from communications import courriel, relances
        m = relances.relancer(self.c)[0]
        with mock.patch("facturation.pdf.rendre", return_value=b"%PDF"):
            e = courriel.construire(m)
        self.assertEqual([p.get_filename() for p in e.iter_attachments()], [f"solde-{self.vieux.pk}.pdf", "facture-57.pdf"])
        self.assertIn("Les 2 factures sont jointes", e.get_body(("html",)).get_content())


class FauxImap:
    """Serveur IMAP simulé : dossiers {nom: {uid: octets}}, garde la trace de ce qui est effacé."""
    capabilities = ("IMAP4REV1", "UIDPLUS")

    def __init__(self, dossiers):
        self.dossiers, self.effaces, self.courant, self.marques = dossiers, [], None, set()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        assert (u, p) == ("louis@exemple.test", "secret")

    def select(self, dossier, readonly=False):
        self.courant = dossier.strip('"')
        return ("OK", [b"1"]) if self.courant in self.dossiers else ("NO", [b"inconnu"])

    def response(self, code):
        return code, [b"777"]

    def uid(self, commande, *args):
        boite = self.dossiers[self.courant]
        if commande == "search":
            if args[1] == "ALL":
                return "OK", [b" ".join(str(u).encode() for u in sorted(boite))]
            debut = int(args[1].split()[1].split(":")[0])
            trouves = [u for u in sorted(boite) if u >= debut] or ([max(boite)] if boite else [])
            return "OK", [b" ".join(str(u).encode() for u in trouves)]
        if commande == "fetch":
            assert args[1] == "(BODY.PEEK[])"  # jamais marqué lu
            return "OK", [(b"1 (UID x BODY[] {n}", boite[int(args[0])]), b")"]
        if commande == "store":
            assert args[1:] == ("+FLAGS.SILENT", r"(\Deleted)")
            self.marques |= {(self.courant, int(u)) for u in args[0].split(",")}
            return "OK", []
        if commande == "expunge":
            for u in args[0].split(","):
                assert (self.courant, int(u)) in self.marques
                boite.pop(int(u))
                self.effaces.append((self.courant, int(u)))
            return "OK", []
        raise AssertionError(commande)


def _courriel(de="client@example.com", sujet="Re: Facture", corps="Allo", **entetes):
    from email.message import EmailMessage
    e = EmailMessage()
    e["From"], e["To"], e["Subject"] = de, "louis@exemple.test", sujet
    e["Message-ID"] = entetes.pop("mid", f"<{abs(hash((de, sujet, corps)))}@exemple.com>")
    e["Date"] = "Sun, 08 Nov 2026 15:42:12 -0500"
    for k, v in entetes.items():
        del e[k.replace("_", "-")]
        e[k.replace("_", "-")] = v
    e.set_content(corps)
    return e


@override_settings(ALLOWED_HOSTS=["*"], IMAP_HOTE="imap.exemple.test", IMAP_UTILISATEUR="louis@exemple.test", IMAP_MOT_DE_PASSE="secret",
                   IMAP_DOSSIER_ENVOYES="INBOX.Sent", COURRIEL_GARDER_JOURS=30)
class ReceptionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Entretiens Essai", slug="essai", domaine=HOTE, courriel_reponse="louis@exemple.test")
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.exemple.test")
        cls.c = Client.objects.create(entreprise=cls.ent, nom="Tremblay", courriel="client@example.com")
        Client.objects.create(entreprise=cls.autre, nom="Pas le bon", courriel="client@example.com")
        U = get_user_model()
        cls.louis = U.objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")

    def traiter(self, e):
        from communications import reception
        return reception.traiter(self.ent, e.as_bytes())

    def test_rattache_par_l_adresse_et_garde_seulement_la_reponse(self):
        corps = "Je paie demain.\n\nLe 8 nov. 2026 à 15 h 42, Entretiens Essai <louis@exemple.test> a écrit :\n> Bonjour, rappel..."
        m = self.traiter(_courriel(de="Client Tremblay <Client@Example.com>", corps=corps, mid="<r1@example.com>"))
        self.assertEqual((m.client, m.sens, m.statut, m.lu, m.expediteur), (self.c, "entrant", "recu", False, "client@example.com"))
        self.assertEqual(m.contenu, "Je paie demain.")
        self.assertEqual(m.sujet, "Re: Facture")
        self.assertIsNone(self.traiter(_courriel(de="client@example.com", corps=corps, mid="<r1@example.com>")))  # une seule fois

    def test_rattache_par_la_reponse_a_un_message_de_l_app(self):
        envoye = Message.objects.create(entreprise=self.ent, client=self.c, genre="relance_1", canal="courriel",
                                        destinataire="client@example.com", contenu="x", statut="envoye")
        m = self.traiter(_courriel(de="conjoint@example.com", In_Reply_To=f"<1794.1.123.lmapp{envoye.pk}@exemple.test>"))
        self.assertEqual((m.client, m.reponse_a), (self.c, envoye))

    def test_expediteur_inconnu_html_et_piece_jointe(self):
        from email.message import EmailMessage
        e = EmailMessage()
        e["From"], e["Subject"], e["Message-ID"] = "inconnu@example.com", "Prix?", "<x1@example.com>"
        e.set_content("<p>Combien pour <b>mon entrée</b>?</p><p>Merci</p>", subtype="html")
        e.add_attachment(b"\xff\xd8", maintype="image", subtype="jpeg", filename="entree.jpg")
        m = self.traiter(e)
        self.assertIsNone(m.client)
        self.assertIn("Combien pour mon entrée?", m.contenu)
        self.assertNotIn("<b>", m.contenu)
        self.assertIn("[1 pièce jointe : entree.jpg", m.contenu)

    def test_ignores_et_rebond(self):
        self.assertIsNone(self.traiter(_courriel(de="noreply-dmarc-support@google.com", sujet="Report domain: exemple.test")))
        self.assertIsNone(self.traiter(_courriel(de="louis@exemple.test", sujet="copie")))
        parti = Message.objects.create(entreprise=self.ent, client=self.c, genre="facture", canal="courriel",
                                       destinataire="mauvais@example.com", contenu="x", statut="envoye")
        rebond = _courriel(de="Mail Delivery System <Mailer-Daemon@woww.exemple.test>", sujet="Mail delivery failed",
                           corps=f"This message was created automatically.\nDiagnostic-Code: smtp; 550 5.1.1 User unknown\n"
                                 f"Message-ID: <1794.1.99.lmapp{parti.pk}@exemple.test>")
        self.assertIsNone(self.traiter(rebond))
        parti.refresh_from_db()
        self.assertEqual(parti.statut, "echec")
        self.assertEqual(parti.erreur, "Courriel revenu : 550 5.1.1 User unknown")
        self.assertFalse(Message.objects.filter(sens="entrant").exists())

    def test_lecture_archive_traite_puis_efface(self):
        from django.utils import timezone
        from communications import lecture
        from communications.models import ArchiveCourriel, EtatBoite
        imap = FauxImap({"INBOX": {1: _courriel(corps="vieux").as_bytes(), 2: _courriel(corps="vieux 2").as_bytes()},
                         "INBOX.Sent": {7: _courriel(de="louis@exemple.test", corps="envoi de Louis", To="client@example.com").as_bytes()}})
        with mock.patch("communications.lecture.imaplib.IMAP4_SSL", lambda *a, **k: imap):
            self.assertEqual(lecture.lire(self.ent), 0)  # première lecture : tout est archivé, rien n'est traité
            self.assertEqual(ArchiveCourriel.objects.count(), 3)
            self.assertFalse(Message.objects.exists())
            self.assertEqual(EtatBoite.objects.get(entreprise=self.ent, dossier="INBOX").uid_depart, 2)
            imap.dossiers["INBOX"][3] = _courriel(corps="plante").as_bytes()
            imap.dossiers["INBOX"][4] = _courriel(corps="Je paie demain").as_bytes()
            imap.dossiers["INBOX.Sent"][8] = _courriel(de="louis@exemple.test", sujet="Prix", corps="C'est 400 $", To="Client@Example.com").as_bytes()
            vrai = lecture.reception.traiter
            with mock.patch("communications.lecture.reception.traiter",
                            side_effect=lambda e, o: (_ for _ in ()).throw(ValueError("illisible")) if b"plante" in o else vrai(e, o)):
                self.assertEqual(lecture.lire(self.ent), 2)
        self.assertEqual(ArchiveCourriel.objects.count(), 6)  # le courriel qui plante est archivé quand même
        recu = Message.objects.get(sens="entrant")
        self.assertEqual(recu.contenu, "Je paie demain")
        self.assertEqual(ArchiveCourriel.objects.get(message=recu).octets(), imap.dossiers["INBOX"][4])
        envoi_louis = Message.objects.get(sens="sortant")
        self.assertEqual((envoi_louis.client, envoi_louis.statut, envoi_louis.contenu), (self.c, "envoye", "C'est 400 $"))
        self.assertEqual(imap.effaces, [])  # trop récents : rien d'effacé
        # 31 jours plus tard : effacés de la boîte, sauf une archive abîmée
        ArchiveCourriel.objects.update(archive_le=timezone.now() - timedelta(days=31))
        abimee = ArchiveCourriel.objects.get(dossier="INBOX", uid=1)
        ArchiveCourriel.objects.filter(pk=abimee.pk).update(empreinte="0" * 64)
        with mock.patch("communications.lecture.imaplib.IMAP4_SSL", lambda *a, **k: imap):
            lecture.lire(self.ent)
        self.assertEqual(sorted(imap.effaces), [("INBOX", 2), ("INBOX", 3), ("INBOX", 4), ("INBOX.Sent", 7), ("INBOX.Sent", 8)])
        self.assertIsNone(ArchiveCourriel.objects.get(pk=abimee.pk).efface_le)
        self.assertEqual(ArchiveCourriel.objects.exclude(efface_le=None).count(), 5)
        # Archive réparée, mais effacement désactivé (-1) : le courriel 1 reste dans la boîte
        ArchiveCourriel.objects.filter(pk=abimee.pk).update(empreinte=hashlib.sha256(imap.dossiers["INBOX"][1]).hexdigest())
        with override_settings(COURRIEL_GARDER_JOURS=-1), mock.patch("communications.lecture.imaplib.IMAP4_SSL", lambda *a, **k: imap):
            lecture.lire(self.ent)
        self.assertIn(1, imap.dossiers["INBOX"])

    def test_copie_de_nos_envois_rattachee(self):
        from communications import reception
        parti = Message.objects.create(entreprise=self.ent, client=self.c, genre="facture", canal="courriel",
                                       destinataire="client@example.com", contenu="x", statut="envoye")
        copie = _courriel(de="louis@exemple.test", mid=f"<1794.1.5.lmapp{parti.pk}@exemple.test>")
        self.assertEqual(reception.traiter_envoye(self.ent, copie.as_bytes()), parti)
        self.assertEqual(Message.objects.count(), 1)

    def test_tache_en_prod_seulement(self):
        from communications.tasks import lire_boite_aux_2_minutes
        with override_settings(COURRIEL_LECTURE_ACTIVE=False):
            self.assertEqual(lire_boite_aux_2_minutes.func(0), "lecture désactivée")
        with override_settings(COURRIEL_LECTURE_ACTIVE=True), mock.patch("communications.lecture.lire", return_value=2) as lire:
            self.assertEqual(lire_boite_aux_2_minutes.func(0), 2)
        lire.assert_called_once_with(self.ent)
        with override_settings(COURRIEL_LECTURE_ACTIVE=True, IMAP_UTILISATEUR="autre@exemple.test"):
            self.assertEqual(lire_boite_aux_2_minutes.func(0), "aucune entreprise pour cette boîte")

    def test_ecrans(self):
        m = self.traiter(_courriel(corps="Je paie demain."))
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)
        accueil = self.client.get("/")
        self.assertContains(accueil, "✉ 1")
        liste = self.client.get("/messages/")
        self.assertEqual(liste.context["vue"], "recus")
        self.assertContains(liste, "Nouveau")
        fiche = self.client.get(f"/clients/{self.c.pk}/")
        self.assertContains(fiche, "Je paie demain.")
        page = self.client.get(f"/messages/{m.pk}/")
        self.assertContains(page, "Reçu de client@example.com")
        self.assertContains(page, "Fiche de Tremblay")
        m.refresh_from_db()
        self.assertTrue(m.lu)
        self.assertNotContains(self.client.get("/"), "✉")
        etranger = Message.objects.create(entreprise=self.autre, genre="recu", canal="courriel", sens="entrant", contenu="x")
        self.assertEqual(self.client.get(f"/messages/{etranger.pk}/").status_code, 404)
