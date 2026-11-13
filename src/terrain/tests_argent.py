from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from clients.models import Adresse, Client
from core.models import Entreprise, Membre
from facturation.models import Facture, Paiement, Service

HOTE = "louis.exemple.test"


@override_settings(ALLOWED_HOSTS=["*"])
class ArgentTerrainTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE, inscrit_taxes=True, prochain_numero_facture=500)
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.exemple.test")
        cls.louis = U.objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")
        cls.comptable = U.objects.create_user("comptable", password="x" * 12)
        Membre.objects.create(utilisateur=cls.comptable, entreprise=cls.ent, role="lecture")
        cls.c = Client.objects.create(entreprise=cls.ent, prenom="Ginette", nom="Tremblay", mode_paiement="comptant")
        Adresse.objects.create(entreprise=cls.ent, client=cls.c, ligne1="1, rue A", ville="Sainte-Adèle")
        cls.balcon = Service.objects.create(entreprise=cls.ent, nom="Pelletage du balcon", prix_suggere=D("25"))
        cls.etranger = Client.objects.create(entreprise=cls.autre, nom="Ailleurs")

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)

    def creer(self, prix="100", **kw):
        r = self.client.post(f"/clients/{self.c.pk}/factures/nouvelle/", {"description": "Déneigement", "quantite": "1", "prix": prix, **kw})
        return Facture.objects.latest("pk"), r

    def test_facture_complete_au_cellulaire(self):
        self.assertContains(self.client.get(f"/clients/{self.c.pk}/"), "Nouvelle facture")
        self.assertContains(self.client.get(f"/clients/{self.c.pk}/factures/nouvelle/"), "Pelletage du balcon")
        f, r = self.creer(prix="1 200,50 $")
        self.assertRedirects(r, f"/factures/{f.pk}/")
        self.assertEqual((f.statut, f.sous_total, f.adresse.ligne1), ("brouillon", D("1200.50"), "1, rue A"))
        self.client.post(f"/factures/{f.pk}/lignes/", {"service": self.balcon.pk, "description": "Pelletage du balcon", "quantite": "2", "prix": "25"})
        f.refresh_from_db()
        self.assertEqual(f.sous_total, D("1250.50"))
        self.assertEqual(f.lignes.last().service, self.balcon)
        r = self.client.post(f"/factures/{f.pk}/emettre/", follow=True)
        self.assertContains(r, "Facture n° 500 émise.")
        f.refresh_from_db()
        self.assertEqual((f.statut, f.numero, f.total), ("emise", 500, D("1437.77")))
        # Plus de modification après l'émission
        self.client.post(f"/factures/{f.pk}/lignes/", {"description": "Ajout", "quantite": "1", "prix": "10"})
        self.assertEqual(f.lignes.count(), 2)

    def test_paiements_comptant_puis_interac(self):
        f, _ = self.creer()
        f.emettre()
        page = self.client.get(f"/factures/{f.pk}/")
        self.assertContains(page, "Paiement reçu")
        self.assertContains(page, "montant: '114,98'")  # le solde est proposé
        r = self.client.post(f"/factures/{f.pk}/paiement/", {"mode": "comptant", "montant": "50"}, follow=True)
        self.assertContains(r, "Comptant de 50,00 $ enregistré. Reste 64,98 $.")
        # Écran vert, puis la fiche du client (nouveau solde); une seule fois
        self.assertEqual(r.redirect_chain[-1][0], f"/clients/{f.client_id}/")
        self.assertContains(r, "Reçu 50,00")
        self.assertContains(r, "reste 64,98")
        self.assertNotContains(self.client.get(f"/clients/{f.client_id}/"), 'class="mt-2 text-4xl font-bold"')
        r = self.client.post(f"/factures/{f.pk}/paiement/", {"mode": "comptant", "montant": "50"}, follow=True)
        self.assertContains(r, "déjà enregistré")  # double tape
        self.assertEqual(f.paiements.count(), 1)
        r = self.client.post(f"/factures/{f.pk}/paiement/", {"mode": "interac", "montant": "100"}, follow=True)
        self.assertContains(r, "Plus que le solde")
        r = self.client.post(f"/factures/{f.pk}/paiement/", {"mode": "interac", "montant": "64,98", "reference": "CA1234"}, follow=True)
        self.assertContains(r, "Facture payée au complet.")
        self.assertContains(r, ">Payée<")
        self.assertEqual(f.paiements.get(mode="interac").reference, "CA1234")
        self.assertNotContains(self.client.get(f"/factures/{f.pk}/"), "Paiement reçu")
        # Encaissé depuis les comptes à recevoir : on y revient, avec l'écran vert
        g, _ = self.creer()
        g.emettre()
        r = self.client.post(f"/factures/{g.pk}/paiement/", {"mode": "comptant", "montant": "1", "retour": "/comptes/"}, follow=True)
        self.assertEqual(r.redirect_chain[-1][0], "/comptes/")
        self.assertContains(r, "Reçu 1,00")

    def test_cheque_postdate_depuis_encaisser(self):
        from facturation.models import ChequePostdate
        f, _ = self.creer()
        f.emettre()
        self.assertContains(self.client.get(f"/factures/{f.pk}/?payer=1"), "Chèque postdaté")
        plus_tard = timezone.localdate() + timedelta(days=60)
        r = self.client.post(f"/factures/{f.pk}/paiement/", {"mode": "postdate", "montant": "114,98", "reference": "205",
                                                             "date_cheque": plus_tard.isoformat(), "recu": "1"}, follow=True)
        self.assertContains(r, "noté (en main)")
        c = ChequePostdate.objects.get()
        self.assertEqual((c.facture, c.montant, c.date_cheque, c.numero, c.statut), (f, D("114.98"), plus_tard, "205", "en_main"))
        f.refresh_from_db()
        self.assertEqual(f.paiements.count(), 0)  # pas de l'argent reçu avant le dépôt
        self.assertFalse(f.payee)
        # Double tape : un seul chèque
        self.client.post(f"/factures/{f.pk}/paiement/", {"mode": "postdate", "montant": "114,98", "date_cheque": plus_tard.isoformat()})
        self.assertEqual(ChequePostdate.objects.count(), 1)
        # Sans date : refusé
        r = self.client.post(f"/factures/{f.pk}/paiement/", {"mode": "postdate", "montant": "10"}, follow=True)
        self.assertContains(r, "date écrite sur le chèque")
        # Daté d'aujourd'hui : un chèque ordinaire, encaissé tout de suite
        self.client.post(f"/factures/{f.pk}/paiement/", {"mode": "postdate", "montant": "10", "date_cheque": timezone.localdate().isoformat()})
        self.assertEqual(list(f.paiements.values_list("mode", "montant")), [("cheque", D("10.00"))])

    def test_paiement_d_un_autre_jour(self):
        f, _ = self.creer()
        f.emettre()
        hier = timezone.localdate() - timedelta(days=1)
        self.client.post(f"/factures/{f.pk}/paiement/", {"mode": "cheque", "montant": "10", "date": hier.isoformat(), "reference": "112"})
        self.assertEqual(f.paiements.get().date, hier)

    def test_brouillon_supprime_et_facture_annulee(self):
        f, _ = self.creer()
        self.assertRedirects(self.client.post(f"/factures/{f.pk}/supprimer/"), f"/clients/{self.c.pk}/")
        self.assertFalse(Facture.objects.filter(pk=f.pk).exists())
        g, _ = self.creer()
        g.emettre()
        self.client.post(f"/factures/{g.pk}/supprimer/")
        self.assertTrue(Facture.objects.filter(pk=g.pk).exists())  # émise : jamais effacée
        r = self.client.post(f"/factures/{g.pk}/annuler/", {"raison": "Mauvais client"}, follow=True)
        self.assertContains(r, "annulée")
        g.refresh_from_db()
        self.assertEqual(g.statut, "annulee")

    def test_comptes_a_recevoir(self):
        vieille, _ = self.creer(prix="200")
        vieille.date_facture = timezone.localdate() - timedelta(days=75)
        vieille.save()
        vieille.emettre()
        recente, _ = self.creer(prix="1000")
        recente.emettre()
        autre_c = Client.objects.create(entreprise=self.ent, nom="Côté")
        Facture.solde_ouverture(autre_c, D("50"), saison_origine="2025-2026")
        self.creer(prix="5")  # brouillon : pas à recevoir
        r = self.client.get("/comptes/")
        lignes = r.context["lignes"]
        self.assertEqual([l["client"].nom for l in lignes], ["Tremblay", "Côté"])  # plus vieux d'abord
        self.assertEqual(lignes[0]["du"], D("229.95") + D("1149.75"))
        self.assertEqual(r.context["total"], D("1429.70"))
        self.assertEqual(r.context["plus_de_60"], D("1379.70"))
        self.assertEqual(r.context["brouillons"], 1)
        self.assertEqual([l["client"].nom for l in self.client.get("/comptes/?tri=montant").context["lignes"]], ["Tremblay", "Côté"])
        self.assertContains(self.client.get(f"/clients/{self.c.pk}/"), "1 379,70 $</div>")
        self.assertEqual(len(self.client.get("/factures/").context["brouillons"]), 1)

    def test_lecture_seule_consulte_sans_modifier(self):
        f, _ = self.creer()
        f.emettre()
        self.client.force_login(self.comptable)
        page = self.client.get(f"/factures/{f.pk}/")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Paiement reçu")
        self.assertNotContains(self.client.get(f"/clients/{self.c.pk}/"), "Nouvelle facture")
        self.assertEqual(self.client.post(f"/factures/{f.pk}/paiement/", {"mode": "comptant", "montant": "5"}).status_code, 403)
        self.assertEqual(self.client.post(f"/clients/{self.c.pk}/factures/nouvelle/", {"description": "x", "quantite": "1", "prix": "1"}).status_code, 403)
        self.assertEqual(f.paiements.count(), 0)

    def test_rien_d_une_autre_entreprise(self):
        f2 = Facture.objects.create(entreprise=self.autre, client=self.etranger)
        self.assertEqual(self.client.get(f"/factures/{f2.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/factures/{f2.pk}/emettre/").status_code, 404)
        self.assertEqual(self.client.get(f"/clients/{self.etranger.pk}/factures/nouvelle/").status_code, 404)
        self.assertEqual(self.client.get("/comptes/").context["lignes"], [])

    def test_dates_en_francais_meme_si_le_telephone_est_en_anglais(self):
        f, _ = self.creer()
        f.date_facture = date(2026, 12, 3)
        f.save()
        self.assertContains(self.client.get(f"/factures/{f.pk}/", HTTP_ACCEPT_LANGUAGE="en-US,en"), "3 décembre 2026")

    def test_get_sur_une_action_refuse(self):
        f, _ = self.creer()
        self.assertEqual(self.client.get(f"/factures/{f.pk}/emettre/").status_code, 405)
