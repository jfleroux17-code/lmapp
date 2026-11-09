"""Boîte de la plateforme (info@) : demandes gardées dans la base, transférées à JF, suivies dans l'administration."""
import smtplib
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from communications.tests import FauxImap, _courriel
from core import boite_plateforme
from core.models import DemandeSite


class ImapInfo(FauxImap):
    def __init__(self, dossiers):
        super().__init__(dossiers)
        self.lecture_seule = None

    def login(self, u, p):
        assert (u, p) == ("info@exemple.test", "secret$info")

    def select(self, dossier, readonly=False):
        self.lecture_seule = readonly
        return super().select(dossier, readonly)


class FauxSmtp:
    envoyes = []
    panne = False

    def __init__(self, *a, **k):
        if FauxSmtp.panne:
            raise OSError("serveur injoignable")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, u, p):
        assert (u, p) == ("info@exemple.test", "secret$info")

    def send_message(self, m):
        FauxSmtp.envoyes.append(m)


@override_settings(IMAP_HOTE="imap.exemple.test", SMTP_HOTE="smtp.exemple.test", PLATEFORME_IMAP_UTILISATEUR="info@exemple.test",
                   PLATEFORME_IMAP_MOT_DE_PASSE="secret$info", PLATEFORME_TRANSFERT_A="jf@exemple.test", COURRIEL_LECTURE_ACTIVE=True)
class BoitePlateformeTests(TestCase):
    def setUp(self):
        FauxSmtp.envoyes, FauxSmtp.panne = [], False

    def passer(self, imap):
        from core.tasks import lire_boite_plateforme_aux_2_minutes

        with mock.patch("core.boite_plateforme.imaplib.IMAP4_SSL", lambda *a, **k: imap), \
                mock.patch("core.boite_plateforme.smtplib.SMTP_SSL", FauxSmtp):
            return lire_boite_plateforme_aux_2_minutes.func(0)

    def test_demande_gardee_et_transferee_une_seule_fois(self):
        e = _courriel(de="Marc Gagnon <marc@example.com>", sujet="Votre logiciel", corps="Bonjour, j'ai 80 clients à Prévost.")
        e.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="liste.pdf")
        imap = ImapInfo({"INBOX": {5: e.as_bytes()}})
        self.assertEqual(self.passer(imap), {"nouvelles": 1, "transferees": 1})
        self.assertTrue(imap.lecture_seule)  # rien n'est marqué lu ni effacé chez nous
        d = DemandeSite.objects.get()
        self.assertEqual((d.nom, d.expediteur, d.sujet, d.statut, d.pieces_jointes), ("Marc Gagnon", "marc@example.com",
                         "Votre logiciel", "nouvelle", ["liste.pdf"]))
        self.assertIn("80 clients", d.texte)
        self.assertEqual(d.octets(), e.as_bytes())
        self.assertIsNotNone(d.transferee_le)
        t, = FauxSmtp.envoyes
        self.assertEqual((t["To"], t["Reply-To"], t["Subject"]), ("jf@exemple.test", "Marc Gagnon <marc@example.com>", "[info@] Votre logiciel"))
        self.assertIn("80 clients", t.get_body(("plain",)).get_content())
        jointe, = t.iter_attachments()
        self.assertEqual(jointe.get_content_type(), "message/rfc822")
        self.assertEqual(self.passer(imap), {"nouvelles": 0, "transferees": 0})  # pas de doublon
        imap.dossiers["INBOX"][6] = _courriel(de="autre@example.com", corps="Prix?").as_bytes()
        self.assertEqual(self.passer(imap), {"nouvelles": 1, "transferees": 1})
        self.assertEqual(DemandeSite.objects.count(), 2)

    def test_messages_automatiques_gardes_sans_transfert(self):
        imap = ImapInfo({"INBOX": {
            1: _courriel(de="MAILER-DAEMON@exemple.test", sujet="Undelivered").as_bytes(),
            2: _courriel(de="vacances@example.com", corps="Absent", Auto_Submitted="auto-replied").as_bytes()}})
        self.assertEqual(self.passer(imap), {"nouvelles": 2, "transferees": 0})
        self.assertEqual(set(DemandeSite.objects.values_list("statut", flat=True)), {"automatique"})
        self.assertEqual(FauxSmtp.envoyes, [])

    def test_transfert_rate_reessaye_puis_abandonne(self):
        imap = ImapInfo({"INBOX": {1: _courriel(de="a@example.com").as_bytes()}})
        FauxSmtp.panne = True
        self.assertEqual(self.passer(imap), {"nouvelles": 1, "transferees": 0})
        d = DemandeSite.objects.get()
        self.assertEqual((d.essais_transfert, d.erreur_transfert, d.transferee_le), (1, "serveur injoignable", None))
        FauxSmtp.panne = False
        self.assertEqual(self.passer(imap)["transferees"], 1)
        DemandeSite.objects.update(transferee_le=None, essais_transfert=boite_plateforme.ESSAIS_MAX)
        self.assertEqual(self.passer(imap)["transferees"], 0)

    def test_boite_illisible_n_empeche_pas_les_transferts_en_attente(self):
        DemandeSite.objects.create(uidvalidite=777, uid=1, recu_le="2026-11-09T10:00:00-05:00", expediteur="a@example.com",
                                   brut=__import__("zlib").compress(b"Subject: x\r\n\r\nallo"))

        def panne(*a, **k):
            raise OSError("pas de réseau")

        with mock.patch("core.boite_plateforme.imaplib.IMAP4_SSL", panne), mock.patch("core.boite_plateforme.smtplib.SMTP_SSL", FauxSmtp):
            from core.tasks import lire_boite_plateforme_aux_2_minutes
            self.assertEqual(lire_boite_plateforme_aux_2_minutes.func(0), {"nouvelles": 0, "transferees": 1})

    def test_rien_hors_prod_ni_sans_configuration(self):
        from core.tasks import lire_boite_plateforme_aux_2_minutes

        with override_settings(COURRIEL_LECTURE_ACTIVE=False):
            self.assertEqual(lire_boite_plateforme_aux_2_minutes.func(0), "lecture désactivée")
        with override_settings(PLATEFORME_IMAP_MOT_DE_PASSE=""):
            self.assertEqual(lire_boite_plateforme_aux_2_minutes.func(0), "boîte de la plateforme non configurée")


@override_settings(ALLOWED_HOSTS=["*"])
class AdministrationDemandesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        import zlib
        U = get_user_model()
        cls.jf = U.objects.create_superuser("jf", password="x" * 12)
        cls.employe = U.objects.create_user("employe", password="x" * 12, is_staff=True)
        cls.d = DemandeSite.objects.create(uidvalidite=1, uid=1, recu_le="2026-11-09T10:00:00-05:00", nom="Marc Gagnon",
                                           expediteur="marc@example.com", sujet="Votre logiciel",
                                           brut=zlib.compress(b"Subject: Votre logiciel\r\n\r\nallo"))

    def test_jf_voit_le_compteur_la_liste_et_telecharge(self):
        self.client.force_login(self.jf)
        r = self.client.get("/admin/")
        self.assertContains(r, "Demandes reçues à info@")
        self.assertContains(r, "1 nouvelle")
        self.assertContains(self.client.get("/admin/core/demandesite/"), "Marc Gagnon")
        r = self.client.post("/admin/core/demandesite/", {"action": "telecharger_eml", "_selected_action": [self.d.pk]})
        self.assertEqual((r["Content-Type"], r.content), ("message/rfc822", b"Subject: Votre logiciel\r\n\r\nallo"))
        r = self.client.post(f"/admin/core/demandesite/{self.d.pk}/change/", {"statut": "en_cours", "note": "Appelé"})
        self.d.refresh_from_db()
        self.assertEqual((self.d.statut, self.d.note), ("en_cours", "Appelé"))

    def test_seulement_le_superutilisateur(self):
        self.client.force_login(self.employe)
        self.assertNotContains(self.client.get("/admin/"), "Demandes reçues à info@")
        self.assertEqual(self.client.get("/admin/core/demandesite/").status_code, 403)
