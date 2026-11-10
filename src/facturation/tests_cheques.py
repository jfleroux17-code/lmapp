"""Chèques postdatés (PRD D9) : en main, déposés à leur date seulement, retournés, rendus; écrans et avis."""
from datetime import date, timedelta
from decimal import Decimal as D
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone

from clients.models import Adresse, Client
from core.models import Entreprise, Membre
from facturation import cheques, credits
from facturation.models import ChequePostdate, Contrat, Paiement, Saison
from facturation.tasks import aviser_cheques_a_deposer

HOTE = "essai.exemple.test"
S = ChequePostdate.Statut


@override_settings(ALLOWED_HOSTS=["*"])
class ChequesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE, inscrit_taxes=True, prochain_numero_facture=500,
                                            versements_par_defaut=2, dates_versements="15/01 15/02")
        cls.louis = U.objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")
        cls.saison = Saison.objects.create(entreprise=cls.ent, nom="2026-2027", debut=date(2020, 11, 1), fin=date(2099, 4, 30))
        cls.c = Client.objects.create(entreprise=cls.ent, nom="Tremblay", mode_paiement="cheque")
        Adresse.objects.create(entreprise=cls.ent, client=cls.c, ligne1="1, rue A", ville="Sainte-Adèle")

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)
        self.aujourdhui = timezone.localdate()
        self.contrat = Contrat.objects.create(entreprise=self.ent, client=self.c, saison=self.saison, prix=D("688.84"))
        self.v1, self.v2 = self.contrat.creer_echeancier([self.aujourdhui, self.aujourdhui + timedelta(days=60)])

    def cheque(self, versement=None, jours=60, montant="396.00", **kw):
        return ChequePostdate.objects.create(entreprise=self.ent, client=self.c, montant=D(montant), numero="123",
                                             date_cheque=self.aujourdhui + timedelta(days=jours), versement=versement, **kw)

    def test_en_main_n_est_pas_de_l_argent_recu(self):
        self.cheque(self.v2)
        self.assertEqual(credits.encaisse(self.ent), D("0"))
        self.assertEqual(cheques.resume(self.ent)["en_main"], 1)
        self.assertEqual(cheques.resume(self.ent)["a_deposer"], 0)

    def test_pas_deposable_avant_sa_date(self):
        c = self.cheque(self.v2)
        with self.assertRaisesMessage(ValidationError, "pas déposable avant"):
            cheques.deposer(c)
        self.assertEqual(Paiement.objects.count(), 0)

    def test_depose_sur_la_facture_emise_du_versement(self):
        c = self.cheque(self.v2)
        f = self.v2.facturer()
        f.emettre()
        p, credit = cheques.deposer(c, jour=c.date_cheque)
        f.refresh_from_db()
        self.assertEqual((p.facture, p.mode, p.date, p.reference, credit), (f, "cheque", c.date_cheque, "Chèque n° 123", None))
        self.assertTrue(f.payee)
        self.assertEqual((c.statut, c.depose_le), (S.DEPOSE, c.date_cheque))
        with self.assertRaisesMessage(ValidationError, "déjà déposé"):
            cheques.deposer(c, jour=c.date_cheque)

    def test_facture_pas_encore_emise_le_cheque_devient_un_credit(self):
        c = self.cheque(self.v2, jours=0)
        p, credit = cheques.deposer(c)
        self.assertIsNone(p)
        self.assertEqual((credit.montant, credit.mode), (D("396.00"), "cheque"))
        self.assertEqual(credits.encaisse(self.ent), D("396.00"))
        f = self.v2.facturer()
        f.emettre()  # le crédit paie la facture à son émission
        f.refresh_from_db()
        self.assertTrue(f.payee)

    def test_retourne_retire_le_paiement_et_le_credit(self):
        f1 = self.v1.facturer()
        f1.emettre()
        c = self.cheque(None, jours=0, montant="500.00")  # au compte : paie le versement 1, le reste en crédit
        cheques.deposer(c)
        f1.refresh_from_db()
        self.assertTrue(f1.payee)
        cheques.retourner(c, "sans provision")
        f1.refresh_from_db()
        self.assertEqual(f1.solde, f1.total)
        self.assertEqual((Paiement.objects.count(), credits.encaisse(self.ent)), (0, D("0")))
        self.assertEqual((c.statut, c.note), (S.RETOURNE, "Retourné : sans provision"))

    def test_rendu_seulement_en_main(self):
        c = self.cheque(self.v2)
        cheques.rendre(c)
        self.assertEqual(c.statut, S.RENDU)
        with self.assertRaises(ValidationError):
            cheques.rendre(c)

    def test_noter_depuis_la_fiche(self):
        page = self.client.get(f"/clients/{self.c.pk}/cheques/nouveau/")
        self.assertContains(page, "Versement 2 de 2")
        self.assertContains(page, "396,00")  # montant taxes comprises proposé (344,42 avant taxes)
        r = self.client.post(f"/clients/{self.c.pk}/cheques/nouveau/", {"pour": f"v{self.v2.pk}", "montant": "396,00",
                                                                        "date_cheque": self.v2.date_prevue.isoformat(), "numero": "124"})
        self.assertRedirects(r, f"/clients/{self.c.pk}/")
        c = ChequePostdate.objects.get()
        self.assertEqual((c.versement, c.montant, c.numero, c.statut), (self.v2, D("396.00"), "124", S.EN_MAIN))
        self.client.post(f"/clients/{self.c.pk}/cheques/nouveau/", {"pour": f"v{self.v2.pk}", "montant": "396,00",
                                                                     "date_cheque": self.v2.date_prevue.isoformat(), "numero": "124"})
        self.assertEqual(ChequePostdate.objects.count(), 1)  # double tape
        self.assertContains(self.client.get(f"/clients/{self.c.pk}/"), "Chèques postdatés en main")
        self.assertNotContains(self.client.get(f"/clients/{self.c.pk}/cheques/nouveau/"), "Versement 2 de 2 (")  # déjà couvert

    def test_liste_et_depot_d_une_tape(self):
        c = self.cheque(self.v2, jours=0)
        self.cheque(None, jours=30, montant="100.00")
        page = self.client.get("/cheques/")
        self.assertContains(page, "À déposer")
        self.assertContains(page, "À venir")
        self.assertContains(self.client.get("/comptes/"), 'Chèques à déposer (396,00\u202f$)</span><span class="pastille bg-ok text-nuit">1</span>')
        self.client.post(f"/cheques/{c.pk}/", {"action": "deposer"})
        c.refresh_from_db()
        self.assertEqual(c.statut, S.DEPOSE)

    def test_pas_de_relance_proposee_avec_un_cheque_en_main(self):
        from communications.relances_proposees import proposition

        from facturation.models import Facture

        f = self.v1.facturer()
        f.emettre()
        dues = list(Facture.objects.filter(pk=f.pk).a_recevoir())
        self.c.cellulaire = "+14505550101"
        self.c.save()
        plus_tard = self.aujourdhui + timedelta(days=20)
        self.assertIsNotNone(proposition(self.c, dues, plus_tard))
        self.cheque(self.v1, jours=25)
        self.assertIsNone(proposition(self.c, dues, plus_tard))

    def test_avis_le_jour_venu(self):
        self.cheque(self.v2, jours=3)
        with mock.patch("core.tasks.notifier_plus_tard") as avis:
            self.assertEqual(aviser_cheques_a_deposer(self.aujourdhui + timedelta(days=2)), 0)
            self.assertEqual(aviser_cheques_a_deposer(self.aujourdhui + timedelta(days=3)), 1)
        self.assertIn("1 chèque postdaté à déposer", avis.call_args.args[2])

    def test_pdf_de_la_facture_dit_que_le_cheque_est_recu(self):
        from facturation.pdf import contexte

        self.cheque(self.v2)
        f = self.v2.facturer()
        self.assertEqual(len(contexte(f)["cheques"]), 1)
