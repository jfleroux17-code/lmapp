"""Abonnement des entreprises à la plateforme (PRD Q2) : usage, brouillon du mois, émission, envoi, écran du déneigeur."""
from datetime import date, datetime
from decimal import Decimal as D
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from communications.models import Message
from core import abonnement
from core.models import Entreprise, FacturePlateforme, Membre

HOTE = "louis.exemple.test"
NOVEMBRE = date(2026, 11, 1)


def _le(jour, heure=12):
    return timezone.make_aware(datetime(2026, 11, jour, heure))


@override_settings(ALLOWED_HOSTS=["*"], PLATEFORME_NUMERO_TPS="123456789 RT0001", PLATEFORME_NUMERO_TVQ="1234567890 TQ0001")
class AbonnementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE, abonnement_facture=True, courriel="Patron@Example.com")
        U = get_user_model()
        cls.patron = U.objects.create_user("patron", password="x" * 12)
        Membre.objects.create(utilisateur=cls.patron, entreprise=cls.ent, role="admin")
        for nom, role, actif in (("employe", "operateur", True), ("ancien", "operateur", False), ("comptable", "lecture", True)):
            Membre.objects.create(utilisateur=U.objects.create_user(nom, password="x" * 12, is_active=actif), entreprise=cls.ent, role=role)

        def msg(canal, sens, statut, jour):
            m = Message.objects.create(entreprise=cls.ent, genre="manuel", canal=canal, sens=sens, statut=statut, destinataire="x", contenu="Allo")
            Message.objects.filter(pk=m.pk).update(cree_le=_le(jour))

        for _ in range(3):
            msg("texto", "sortant", "envoye", 5)
        msg("texto", "sortant", "prepare", 5)  # pas parti : pas compté
        msg("texto", "sortant", "bloque", 5)
        msg("texto", "entrant", "recu", 6)
        msg("texto", "entrant", "recu", 6)
        msg("courriel", "sortant", "envoye", 7)
        msg("texto", "sortant", "envoye", 1)
        Message.objects.filter(pk=Message.objects.latest("pk").pk).update(cree_le=timezone.make_aware(datetime(2026, 10, 31, 23)))  # octobre

    def test_usage_et_lignes(self):
        u = abonnement.usage(self.ent, NOVEMBRE)
        self.assertEqual((u["textos_envoyes"], u["textos_recus"], u["textos"]), (3, 2, 5))
        self.assertEqual((u["courriels_envoyes"], u["utilisateurs"], u["lecture_seule"]), (1, 2, 1))  # compte inactif et lecture seule pas facturés
        e = abonnement.estimation(self.ent, NOVEMBRE)
        self.assertEqual([l["montant"] for l in e["lignes"]], [D("99.00"), D("25.00"), D("0.15")])
        self.assertEqual(e["sous_total"], D("124.15"))
        self.assertEqual((e["tps"], e["tvq"]), (D("6.21"), D("12.38")))
        self.assertEqual(e["total"], D("142.74"))

    def test_brouillon_le_1er_puis_emission(self):
        crees = abonnement.preparer_mois_passe(date(2026, 12, 1))
        self.assertEqual(len(crees), 1)
        f = crees[0]
        self.assertEqual((f.mois, f.statut, f.numero, f.total), (NOVEMBRE, "brouillon", None, D("142.74")))
        self.assertEqual(abonnement.preparer_mois_passe(date(2026, 12, 1)), [])  # une seule par mois
        Entreprise.objects.create(nom="Pas facturée", slug="autre", domaine="autre.test")
        self.assertEqual(FacturePlateforme.objects.count(), 1)
        # JF ajoute un rabais au brouillon
        f.lignes.create(ordre=9, description="Rabais du premier mois", quantite=1, prix_unitaire=D("-24.15"))
        abonnement.recalculer(f)
        self.assertEqual(f.sous_total, D("100.00"))
        abonnement.emettre(f, date(2026, 12, 1))
        self.assertEqual((f.numero, f.statut, f.date_echeance, f.total), (1, "emise", date(2026, 12, 16), D("114.98")))
        with self.assertRaises(ValidationError):
            abonnement.emettre(f)
        pdf = abonnement.pdf(f)
        self.assertTrue(pdf.startswith(b"%PDF"))

    @override_settings(PLATEFORME_NUMERO_TPS="")
    def test_pas_d_emission_sans_numeros_de_taxes(self):
        f, _ = abonnement.preparer(self.ent, NOVEMBRE)
        with self.assertRaisesMessage(ValidationError, "PLATEFORME_NUMERO_TPS"):
            abonnement.emettre(f)

    @override_settings(LMAPP_ENV="test", LMAPP_DESTINATAIRES_TEST=["patron@example.com"], SMTP_HOTE="smtp.test",
                       PLATEFORME_IMAP_UTILISATEUR="info@ledeneigeur.com", PLATEFORME_IMAP_MOT_DE_PASSE="x")
    def test_envoi_par_le_worker(self):
        f, _ = abonnement.preparer(self.ent, NOVEMBRE)
        with self.assertRaises(ValidationError):
            abonnement.demander_envoi(f)  # brouillon
        abonnement.emettre(f)
        with mock.patch("core.tasks.envoyer_facture_plateforme.defer") as defer, self.captureOnCommitCallbacks(execute=True):
            self.assertEqual(abonnement.demander_envoi(f), "patron@example.com")
        defer.assert_called_once_with(facture_id=f.pk)
        m = abonnement.courriel(f)
        self.assertEqual(m["To"], "patron@example.com")
        self.assertIn("Facture n° 1", m["Subject"])
        with mock.patch("smtplib.SMTP_SSL") as smtp:
            self.assertTrue(abonnement.envoyer(f))
        smtp.return_value.__enter__.return_value.send_message.assert_called_once()
        f.refresh_from_db()
        self.assertEqual(f.envoyee_a, "patron@example.com")
        # Hors prod, un autre destinataire est refusé
        Entreprise.objects.filter(pk=self.ent.pk).update(courriel="autre@example.com")
        f.refresh_from_db()
        with self.assertRaisesMessage(ValidationError, "pas un destinataire permis"):
            abonnement.demander_envoi(f)

    def test_ecran_du_deneigeur(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.patron)
        f, _ = abonnement.preparer(self.ent, NOVEMBRE)
        with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 12, 3)):
            page = self.client.get("/plus/reglages/abonnement/")
            self.assertContains(page, "Mon abonnement")
            self.assertContains(page, "Total estimé")
            self.assertNotContains(page, "N° 1")  # brouillon : pas montré au déneigeur
            abonnement.emettre(f)
            page = self.client.get("/plus/reglages/abonnement/")
        self.assertContains(page, "N° 1")
        self.assertEqual(page.context["mois"][0]["usage"]["textos"], 5)
        r = self.client.get(f"/plus/reglages/abonnement/factures/{f.pk}/pdf/")
        self.assertEqual(r["Content-Type"], "application/pdf")
        # Opérateur et lecture seule : refusé
        self.client.force_login(get_user_model().objects.get(username="employe"))
        self.assertEqual(self.client.get("/plus/reglages/abonnement/").status_code, 403)
        self.assertEqual(self.client.get(f"/plus/reglages/abonnement/factures/{f.pk}/pdf/").status_code, 403)
        # Une facture d'une autre entreprise : introuvable
        autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.test")
        g, _ = abonnement.preparer(autre, NOVEMBRE)
        abonnement.emettre(g)
        self.client.force_login(self.patron)
        self.assertEqual(self.client.get(f"/plus/reglages/abonnement/factures/{g.pk}/pdf/").status_code, 404)

    def test_administration_reservee_a_jf(self):
        U = get_user_model()
        jf = U.objects.create_superuser("jf", password="x" * 12)
        f, _ = abonnement.preparer(self.ent, NOVEMBRE)
        self.client.force_login(jf)
        self.assertEqual(self.client.get("/admin/core/factureplateforme/").status_code, 200)
        self.assertEqual(self.client.get(f"/admin/core/factureplateforme/{f.pk}/pdf/")["Content-Type"], "application/pdf")
        self.assertContains(self.client.get("/admin/"), "Factures de la plateforme")
        self.client.force_login(self.patron)
        self.assertNotEqual(self.client.get("/admin/core/factureplateforme/").status_code, 200)
