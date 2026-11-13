"""Échéancier par défaut des contrats (B3); une seule facture par saison avec l'échéancier dessus, et rappels de
versement proposés d'avance et envoyés d'une tape (décision de JF, 12 novembre 2026)."""
from datetime import date
from decimal import Decimal as D
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from clients.models import Adresse, Client
from core.models import Entreprise, Membre
from facturation.models import Contrat, Facture, Saison
from communications.rappels import a_rappeler
from facturation.tasks import aviser_rappels_de_versement

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

    def test_une_facture_pour_la_saison_avec_son_echeancier(self):
        c = self.contrat("450.00")
        v1, v2 = c.creer_echeancier_par_defaut(approbation=date(2026, 11, 9))
        f = v1.facturer()
        self.assertEqual(v2.facturer(), f)  # la même facture pour tous les versements
        self.assertEqual(c.facturer_saison(), f)  # relançable
        self.assertEqual((f.statut, f.sous_total, f.total, f.date_echeance), ("brouillon", D("450.00"), D("517.39"), date(2027, 1, 15)))
        self.assertEqual([(v.rang, m) for v, m, paye in f.echeancier()], [(1, D("258.69")), (2, D("258.70"))])
        # Échéancier changé tant que la facture est en brouillon : elle est refaite
        c.prix = D("500.00")
        c.save()
        c.creer_echeancier_par_defaut(3, approbation=date(2026, 11, 9))
        f2 = c.factures.get()
        self.assertEqual((f2.sous_total, f2.versements.count()), (D("500.00"), 3))
        with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 11, 9)):
            f2.emettre()
        with self.assertRaisesMessage(ValidationError, "est émise"):
            c.creer_echeancier_par_defaut(2)

    def test_echu_et_relance_seulement_pour_les_versements_arrives(self):
        from facturation import credits
        c = self.contrat("450.00")
        v1, v2 = c.creer_echeancier_par_defaut(approbation=date(2026, 11, 9))
        f = v1.facturer()
        with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 11, 9)):
            f.emettre()
        self.assertEqual(f.montant_echu(date(2026, 12, 1)), D("258.69"))  # 1er versement seulement
        self.assertEqual(f.date_exigible(), date(2026, 11, 9))
        credits.encaisser(f, D("258.69"), "comptant", date=date(2026, 11, 9))
        f.refresh_from_db()
        self.assertEqual(f.montant_echu(date(2026, 12, 1)), D("0.00"))  # à jour : pas de relance en décembre
        self.assertEqual(f.date_exigible(), date(2027, 1, 15))
        self.assertEqual(f.montant_echu(date(2027, 1, 20)), D("258.70"))
        self.assertEqual([paye for _, _, paye in f.echeancier()], [True, False])

    def test_rappel_propose_cinq_jours_d_avance_et_louis_avise(self):
        c = self.contrat("450.00")
        v1, v2 = c.creer_echeancier_par_defaut(approbation=date(2026, 11, 9))
        f = v1.facturer()
        with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 11, 9)):
            f.emettre()
        self.assertEqual(a_rappeler(self.ent, date(2027, 1, 9)), [])
        self.assertEqual([(v.rang, m) for v, m in a_rappeler(self.ent, date(2027, 1, 10))], [(2, D("258.70"))])  # le 10 pour le 15
        with mock.patch("core.tasks.notifier_plus_tard") as avis:
            self.assertEqual(aviser_rappels_de_versement(date(2027, 1, 10)), 1)
            self.assertEqual(aviser_rappels_de_versement(date(2027, 1, 11)), 0)  # avisé une seule fois
        self.assertEqual(avis.call_args.kwargs["url"], "/factures/versements/")

    def test_contrat_importe_sans_facture_brouillon_prepare_la_nuit(self):
        self.contrat("450.00").creer_echeancier_par_defaut(approbation=date(2026, 11, 9))
        with mock.patch("core.tasks.notifier_plus_tard") as avis:
            self.assertEqual(aviser_rappels_de_versement(date(2026, 11, 9)), 1)
            self.assertEqual(aviser_rappels_de_versement(date(2026, 11, 10)), 0)
        self.assertEqual(Facture.objects.get().statut, "brouillon")
        self.assertIn("Factures de la saison", avis.call_args.args[1])

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_ecran_emet_les_factures_puis_envoie_les_rappels(self):
        for client in (self.c, self.sans):
            c = self.contrat("450.00", client)
            c.creer_echeancier_par_defaut(approbation=date(2026, 11, 9))
            c.facturer_saison()
        louis = get_user_model().objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=louis, entreprise=self.ent, role="operateur")
        self.client.force_login(louis)
        r = self.client.get("/factures/versements/", HTTP_HOST=HOTE)
        self.assertContains(r, "Tremblay")
        self.assertContains(r, "à remettre en main propre")
        self.assertContains(r, "258,70")  # l'échéancier, taxes comprises
        self.assertContains(self.client.get("/factures/", HTTP_HOST=HOTE), "2 factures de saison ou rappels à envoyer")
        ids = list(Facture.objects.filter(statut="brouillon").values_list("pk", flat=True))
        r = self.client.post("/factures/versements/envoyer/", {"facture": ids}, HTTP_HOST=HOTE, follow=True)
        self.assertEqual(sorted(Facture.objects.values_list("numero", flat=True)), [500, 501])
        self.assertContains(r, "2 factures émises")
        self.assertContains(r, "Sans coordonnées : facture n°")
        f = Facture.objects.get(client=self.c)
        m = f.messages.get()
        self.assertEqual((m.canal, m.destinataire), ("courriel", "tremblay@example.com"))
        self.assertIn("2e versement", m.contenu)
        self.assertContains(self.client.get("/factures/versements/", HTTP_HOST=HOTE), "Aucune facture de saison ni rappel")
        # Le 10 janvier : le rappel du 2e versement
        with mock.patch("django.utils.timezone.localdate", return_value=date(2027, 1, 10)):
            v2 = f.versements.get(rang=2)
            r = self.client.get("/factures/versements/", HTTP_HOST=HOTE)
            self.assertContains(r, "Rappels de versement")
            r = self.client.post("/factures/versements/envoyer/", {"rappel": [v2.pk]}, HTTP_HOST=HOTE, follow=True)
        # Envois réels éteints : le rappel est préparé, pas parti; il reste proposé
        self.assertContains(r, "courriel pas envoyé")
        rappel = f.messages.get(genre="rappel_vers")
        self.assertIn("2e versement", rappel.contenu)
        self.assertIn("258,70", rappel.contenu)
        v2.refresh_from_db()
        self.assertIsNone(v2.rappel_envoye_le)
        # Parti (en file) : noté une fois, plus proposé
        with mock.patch("communications.envoi.envoyer", side_effect=lambda m: (setattr(m, "statut", "en_file"), m)[1]), \
             mock.patch("django.utils.timezone.localdate", return_value=date(2027, 1, 10)):
            r = self.client.post("/factures/versements/envoyer/", {"rappel": [v2.pk]}, HTTP_HOST=HOTE, follow=True)
        self.assertContains(r, "1 rappel de versement en route")
        v2.refresh_from_db()
        self.assertIsNotNone(v2.rappel_envoye_le)
        self.assertEqual([v for v, _ in a_rappeler(self.ent, date(2027, 1, 12)) if v.pk == v2.pk], [])  # une seule fois

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_lecture_seule_ne_peut_pas_envoyer(self):
        u = get_user_model().objects.create_user("lecteur", password="x" * 12)
        Membre.objects.create(utilisateur=u, entreprise=self.ent, role="lecture")
        self.client.force_login(u)
        self.assertEqual(self.client.post("/factures/versements/envoyer/", {}, HTTP_HOST=HOTE).status_code, 403)
