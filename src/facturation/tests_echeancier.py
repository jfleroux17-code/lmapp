"""Échéancier par défaut des contrats (B3), factures de versement préparées d'avance et envoyées d'une tape (C5)."""
from datetime import date
from decimal import Decimal as D
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from clients.models import Adresse, Client
from core.models import Entreprise, Membre
from facturation.models import Contrat, Facture, Saison
from facturation.tasks import facturer_versements_dus

HOTE = "essai.exemple.test"


class EcheancierTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE, inscrit_taxes=True, prochain_numero_facture=500,
                                            versements_par_defaut=2, dates_versements="15/01 15/02", jours_avance_versement=5,
                                            courriel_reponse="louis@exemple.test")
        cls.saison = Saison.objects.create(entreprise=cls.ent, nom="2026-2027", debut=date(2026, 11, 1), fin=date(2027, 4, 30))
        cls.c = Client.objects.create(entreprise=cls.ent, nom="Tremblay", courriel="tremblay@example.com", canal_prefere="courriel")
        cls.sans = Client.objects.create(entreprise=cls.ent, nom="Sans coordonnées")
        cls.a = Adresse.objects.create(entreprise=cls.ent, client=cls.c, ligne1="1, rue A", ville="Sainte-Adèle")

    def contrat(self, prix="1000.00", client=None):
        client = client or self.c
        return Contrat.objects.create(entreprise=self.ent, client=client, saison=self.saison, prix=D(prix))

    def test_deux_versements_a_l_approbation_et_le_15_janvier(self):
        v = self.contrat("450.00").creer_echeancier_par_defaut(approbation=date(2026, 11, 9))
        self.assertEqual([(x.date_prevue, x.montant) for x in v], [(date(2026, 11, 9), D("225.00")), (date(2027, 1, 15), D("225.00"))])

    def test_trois_versements_par_tiers(self):
        v = self.contrat("1500.00").creer_echeancier_par_defaut(3, approbation=date(2026, 11, 9))
        self.assertEqual([x.date_prevue for x in v], [date(2026, 11, 9), date(2027, 1, 15), date(2027, 2, 15)])
        self.assertEqual([x.montant for x in v], [D("500.00")] * 3)
        self.assertEqual(sum(x.montant for x in self.contrat("1000.00").creer_echeancier_par_defaut(3)), D("1000.00"))

    def test_approuve_apres_la_date_le_versement_est_du_tout_de_suite(self):
        v = self.contrat().creer_echeancier_par_defaut(3, approbation=date(2027, 1, 20))
        self.assertEqual([x.date_prevue for x in v], [date(2027, 1, 20), date(2027, 1, 20), date(2027, 2, 15)])

    def test_pas_assez_de_dates_dans_la_fiche(self):
        with self.assertRaisesMessage(ValidationError, "il faut 3 date(s)"):
            self.contrat().creer_echeancier_par_defaut(4)

    def test_dates_mal_ecrites_refusees_dans_la_fiche(self):
        self.ent.dates_versements = "15/01 31/02"
        with self.assertRaises(ValidationError) as e:
            self.ent.clean()
        self.assertIn("dates_versements", e.exception.message_dict)
        self.ent.dates_versements = "15/01, 29/02"
        self.ent.clean()  # 29 février accepté (28 les autres années)
        self.assertEqual(self.ent.liste_dates_versements(), [(15, 1), (29, 2)])

    def test_facture_preparee_cinq_jours_d_avance_et_louis_avise(self):
        self.contrat("450.00").creer_echeancier_par_defaut(approbation=date(2026, 11, 9))
        with mock.patch("core.tasks.notifier_plus_tard") as avis:
            self.assertEqual(facturer_versements_dus(date(2026, 11, 9)), 1)  # 1er versement : tout de suite
            self.assertEqual(facturer_versements_dus(date(2027, 1, 9)), 0)
            self.assertEqual(facturer_versements_dus(date(2027, 1, 10)), 1)  # le 10 pour le 15
            self.assertEqual(facturer_versements_dus(date(2027, 1, 10)), 0)  # une seule fois
        f = Facture.objects.get(versement__rang=2)
        self.assertEqual((f.statut, f.date_echeance), ("brouillon", date(2027, 1, 15)))
        self.assertEqual(avis.call_count, 2)
        self.assertEqual(avis.call_args.kwargs["url"], "/factures/versements/")

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_ecran_emet_et_envoie_d_une_tape(self):
        for client in (self.c, self.sans):
            self.contrat("450.00", client).creer_echeancier_par_defaut(approbation=date(2026, 11, 9))
        with mock.patch("core.tasks.notifier_plus_tard"):
            facturer_versements_dus(date(2026, 11, 9))
        louis = get_user_model().objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=louis, entreprise=self.ent, role="operateur")
        self.client.force_login(louis)
        r = self.client.get("/factures/versements/", HTTP_HOST=HOTE)
        self.assertContains(r, "Tremblay")
        self.assertContains(r, "à remettre en main propre")
        self.assertContains(r, "Émettre et envoyer 2 factures")
        self.assertContains(self.client.get("/factures/", HTTP_HOST=HOTE), "2 factures de versement prêtes à envoyer")
        ids = list(Facture.objects.filter(statut="brouillon").values_list("pk", flat=True))
        r = self.client.post("/factures/versements/envoyer/", {"facture": ids}, HTTP_HOST=HOTE, follow=True)
        self.assertEqual(sorted(Facture.objects.values_list("numero", flat=True)), [500, 501])
        self.assertContains(r, "2 factures émises")
        self.assertContains(r, "Sans coordonnées : facture n°")
        f = Facture.objects.get(client=self.c)
        self.assertEqual(list(f.messages.values_list("canal", "destinataire")), [("courriel", "tremblay@example.com")])
        self.assertContains(self.client.get("/factures/versements/", HTTP_HOST=HOTE), "Aucune facture de versement à envoyer")

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_lecture_seule_ne_peut_pas_envoyer(self):
        u = get_user_model().objects.create_user("lecteur", password="x" * 12)
        Membre.objects.create(utilisateur=u, entreprise=self.ent, role="lecture")
        self.client.force_login(u)
        self.assertEqual(self.client.post("/factures/versements/envoyer/", {}, HTTP_HOST=HOTE).status_code, 403)
