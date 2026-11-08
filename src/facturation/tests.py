from datetime import date
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from clients.models import Adresse, Client
from core.models import Entreprise
from facturation.calculs import repartir, taxes
from facturation.models import Contrat, Facture, Paiement, Saison, Service


class CalculsTests(TestCase):
    def test_taxes_du_quebec_sur_le_sous_total(self):
        self.assertEqual(taxes(D("100.00"), D("5"), D("9.975")), (D("5.00"), D("9.98")))  # 9,975 arrondi vers le haut
        self.assertEqual(taxes(D("450.00"), D("5"), D("9.975")), (D("22.50"), D("44.89")))

    def test_repartir_au_cent_pres(self):
        self.assertEqual(repartir(D("100"), 3), [D("33.33"), D("33.33"), D("33.34")])
        self.assertEqual(repartir(D("200"), 3), [D("66.66"), D("66.66"), D("66.68")])
        self.assertEqual(sum(repartir(D("451.01"), 4)), D("451.01"))


class FacturationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine="essai.exemple.test", inscrit_taxes=True,
                                            numero_tps="123456789 RT0001", numero_tvq="1234567890 TQ0001", prochain_numero_facture=341)
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.exemple.test")
        cls.client_ = Client.objects.create(entreprise=cls.ent, nom="Tremblay")
        cls.adresse = Adresse.objects.create(entreprise=cls.ent, client=cls.client_, ligne1="1, rue A", ville="Sainte-Adèle")
        cls.saison = Saison.objects.create(entreprise=cls.ent, nom="2026-2027", debut=date(2026, 11, 1), fin=date(2027, 4, 15))

    def facture(self, *lignes, **kw):
        f = Facture.objects.create(entreprise=self.ent, client=self.client_, **kw)
        for desc, qte, prix, *taxable in lignes:
            f.lignes.create(description=desc, quantite=qte, prix_unitaire=prix, taxable=taxable[0] if taxable else True)
        f.recalculer()
        return f

    def test_brouillon_puis_emission_numerotee_avec_taxes_figees(self):
        f = self.facture(("Déneigement", 1, "400.00"), ("Abrasif", 2, "25.00"))
        self.assertIsNone(f.numero)
        self.assertEqual((f.sous_total, f.tps, f.tvq, f.total), (D("450.00"), D("22.50"), D("44.89"), D("517.39")))
        f.emettre()
        self.assertEqual(f.numero, 341)
        self.assertEqual(f.numero_tps, "123456789 RT0001")
        self.assertEqual(f.taux_tvq, D("9.975"))
        # Le taux change ensuite dans la fiche : la facture émise garde le sien
        Entreprise.objects.filter(pk=self.ent.pk).update(taux_tvq=D("10"))
        f.refresh_from_db()
        self.assertEqual(f.tvq, D("44.89"))
        g = self.facture(("Bordage", 1, "50"))
        g.emettre()
        self.assertEqual(g.numero, 342)  # séquentiel, sans trou

    def test_facture_emise_ne_change_plus(self):
        f = self.facture(("Déneigement", 1, "100"))
        f.emettre()
        with self.assertRaises(ValidationError):
            f.lignes.create(description="Ajout", quantite=1, prix_unitaire=10)
        with self.assertRaises(ValidationError):
            f.lignes.first().delete()
        with self.assertRaises(ValidationError):
            f.delete()
        with self.assertRaises(ValidationError):
            f.emettre()

    def test_ligne_non_taxable_et_entreprise_non_inscrite(self):
        f = self.facture(("Déneigement", 1, "100"), ("Frais non taxable", 1, "10", False))
        self.assertEqual((f.tps, f.tvq, f.total), (D("5.00"), D("9.98"), D("124.98")))
        Entreprise.objects.filter(pk=self.autre.pk).update(inscrit_taxes=False)
        c = Client.objects.create(entreprise=self.autre, nom="X")
        g = Facture.objects.create(entreprise=self.autre, client=c)
        g.lignes.create(description="Déneigement", quantite=1, prix_unitaire=100)
        g.emettre()
        self.assertEqual((g.tps, g.tvq, g.total, g.numero_tps), (D("0"), D("0"), D("100.00"), ""))

    def test_sans_ligne_pas_d_emission(self):
        f = Facture.objects.create(entreprise=self.ent, client=self.client_)
        with self.assertRaises(ValidationError):
            f.emettre()

    def test_paiements_partiels_solde_et_payee(self):
        f = self.facture(("Déneigement", 1, "100"))
        p = Paiement(entreprise=self.ent, facture=f, montant=D("50"), mode="comptant")
        with self.assertRaises(ValidationError):
            p.full_clean()  # brouillon : pas de paiement
        f.emettre()
        p.full_clean(); p.save()
        self.assertEqual(f.solde, D("64.98"))
        self.assertFalse(f.payee)
        trop = Paiement(entreprise=self.ent, facture=f, montant=D("65"), mode="interac")
        with self.assertRaises(ValidationError):
            trop.full_clean()  # pas de trop-perçu en V1
        Paiement.objects.create(entreprise=self.ent, facture=f, montant=D("64.98"), mode="interac")
        self.assertTrue(f.payee)
        self.assertFalse(Facture.objects.a_recevoir().filter(pk=f.pk).exists())

    def test_annulation(self):
        f = self.facture(("Déneigement", 1, "100"))
        with self.assertRaises(ValidationError):
            f.annuler("erreur")  # brouillon : on le supprime
        f.emettre()
        with self.assertRaises(ValidationError):
            f.annuler("")
        f.annuler("Mauvais client")
        self.assertEqual((f.statut, f.numero, f.solde), ("annulee", 341, D("0")))
        g = self.facture(("Déneigement", 1, "100"))
        g.emettre()
        self.assertEqual(g.numero, 342)  # le numéro annulé n'est pas réutilisé
        Paiement.objects.create(entreprise=self.ent, facture=g, montant=D("10"), mode="comptant")
        with self.assertRaises(ValidationError):
            g.annuler("paiement reçu")

    def test_solde_d_ouverture(self):
        s = Facture.solde_ouverture(self.client_, D("275.50"), saison_origine="2024-2025", note="Papier de Louis")
        self.assertEqual((s.statut, s.numero, s.tps, s.total), ("emise", None, D("0"), D("275.50")))
        self.assertEqual(self.ent.__class__.objects.get(pk=self.ent.pk).prochain_numero_facture, 341)  # n'use pas la série
        a_recevoir = Facture.objects.a_recevoir()
        self.assertEqual(a_recevoir.get(pk=s.pk).solde_du, D("275.50"))

    def test_contrat_echeancier_et_facturation_des_versements(self):
        entree = Service.objects.create(entreprise=self.ent, nom="Entrée")
        c = Contrat.objects.create(entreprise=self.ent, client=self.client_, adresse=self.adresse, saison=self.saison,
                                   prix=D("450"), prix_texte="450 $ plus taxes, en 2 fois")
        c.services.add(entree)
        v1, v2 = c.creer_echeancier([date(2027, 1, 15), date(2026, 12, 1)])
        self.assertEqual((v1.rang, v1.date_prevue, v1.montant), (1, date(2026, 12, 1), D("225.00")))
        f = v1.facturer()
        self.assertEqual(f.lignes.get().description, "Déneigement, saison 2026-2027 : versement 1 de 2")
        self.assertLessEqual(f.date_facture, date.today())  # jamais datée dans le futur
        self.assertEqual(f.date_echeance, max(date(2026, 12, 1), f.date_facture))
        self.assertEqual(f.total, D("258.69"))  # 225 + 11,25 + 22,44 (22,44375 arrondi)
        self.assertIs(v1.facturer(), f)  # pas de deuxième facture
        with self.assertRaises(ValidationError):
            c.creer_echeancier([date(2026, 12, 1)])  # déjà facturé en partie

    def test_objets_d_une_autre_entreprise_refuses(self):
        etranger = Client.objects.create(entreprise=self.autre, nom="Étranger")
        with self.assertRaises(ValidationError):
            Facture(entreprise=self.ent, client=etranger).full_clean()
        autre_saison = Saison.objects.create(entreprise=self.autre, nom="2026-2027", debut=date(2026, 11, 1), fin=date(2027, 4, 1))
        with self.assertRaises(ValidationError):
            Contrat(entreprise=self.ent, client=self.client_, saison=autre_saison, prix=1).full_clean()
        f = Facture.objects.create(entreprise=self.autre, client=etranger)
        with self.assertRaises(ValidationError):
            Paiement(entreprise=self.ent, facture=f, montant=1, mode="comptant").full_clean()


@override_settings(ALLOWED_HOSTS=["*"])
class AdminFacturationTests(TestCase):
    def test_pages_de_l_administration(self):
        ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine="essai.exemple.test", inscrit_taxes=True)
        c = Client.objects.create(entreprise=ent, nom="Tremblay")
        f = Facture.objects.create(entreprise=ent, client=c)
        f.lignes.create(description="Déneigement", quantite=1, prix_unitaire=100)
        f.emettre()
        self.client.force_login(get_user_model().objects.create_superuser("jf", password="x" * 12))
        for url in ["/admin/facturation/facture/", f"/admin/facturation/facture/{f.pk}/change/", "/admin/facturation/facture/?q=1",
                    "/admin/facturation/facture/?q=tremblay", "/admin/facturation/contrat/add/", "/admin/facturation/paiement/add/",
                    "/admin/facturation/saison/", "/admin/facturation/service/", "/admin/core/entreprise/"]:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertNotContains(self.client.get(f"/admin/facturation/facture/{f.pk}/change/"), 'name="lignes-0-prix_unitaire"')


class FormatTests(TestCase):
    def test_argent_et_pourcent_a_la_quebecoise(self):
        from facturation.templatetags.argent import argent, pourcent, quantite

        self.assertEqual(argent(D("1234.5")), "1 234,50 $")
        self.assertEqual(argent(D("-100")), "-100,00 $")
        self.assertEqual(argent(D("1234567.891")), "1 234 567,89 $")
        self.assertEqual(pourcent(D("9.975")), "9,975 %")
        self.assertEqual(pourcent(D("5.000")), "5 %")
        self.assertEqual(quantite(D("2.50")), "2,5")


@override_settings(ALLOWED_HOSTS=["*"])
class PdfTests(TestCase):
    HOTE = "essai.exemple.test"

    @classmethod
    def setUpTestData(cls):
        from core.models import Membre

        cls.ent = Entreprise.objects.create(nom="Entretiens Essai", nom_legal="Les Entretiens Essai inc.", slug="essai", domaine=cls.HOTE,
                                            inscrit_taxes=True, numero_tps="123456789 RT0001", numero_tvq="1234567890 TQ0001",
                                            prochain_numero_facture=57, interac_courriel="paiement@example.com")
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.exemple.test")
        U = get_user_model()
        cls.louis = U.objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")
        cls.c = Client.objects.create(entreprise=cls.ent, prenom="Ginette", nom="Tremblay", facturation_ligne1="C.P. 12",
                                      facturation_ville="Saint-Jérôme", facturation_province="QC", facturation_code_postal="J7Z 1A1")
        cls.a = Adresse.objects.create(entreprise=cls.ent, client=cls.c, ligne1="8, rue des Essais", ville="Sainte-Adèle")
        cls.f = Facture.objects.create(entreprise=cls.ent, client=cls.c, adresse=cls.a, date_facture=date(2026, 12, 1))
        cls.f.lignes.create(description="Déneigement de l'entrée", quantite=1, prix_unitaire=D("1000"))
        cls.f.emettre()
        Paiement.objects.create(entreprise=cls.ent, facture=cls.f, date=date(2026, 12, 5), montant=D("150"), mode="interac")

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = self.HOTE

    def test_contenu_de_la_facture(self):
        from facturation import pdf

        h = pdf.html(self.f)
        for attendu in ["Entretiens Essai", "Les Entretiens Essai inc.", "FACTURE", ">57<", "1 décembre 2026",
                        "C.P. 12", "Saint-Jérôme QC J7Z 1A1", "8, rue des Essais",  # facturation ailleurs : adresse du service aussi
                        "n° 123456789 RT0001", "n° 1234567890 TQ0001", "1 000,00 $", "50,00 $", "99,75 $",
                        "1 149,75 $", "-150,00 $", "999,75 $", "paiement@example.com", "numéro de facture 57"]:
            self.assertIn(attendu, h)
        self.assertNotIn("BROUILLON", h)

    def test_brouillon_annulee_et_solde(self):
        from facturation import pdf

        b = Facture.objects.create(entreprise=self.ent, client=self.c)
        b.lignes.create(description="Abrasif", quantite=1, prix_unitaire=15)
        self.assertIn("BROUILLON", pdf.html(b))
        self.assertEqual(pdf.nom_fichier(b), f"brouillon-{b.pk}.pdf")
        g = Facture.objects.create(entreprise=self.ent, client=self.c)
        g.lignes.create(description="Bordage", quantite=1, prix_unitaire=40)
        g.emettre()
        g.annuler("Erreur de client")
        h = pdf.html(g)
        self.assertIn("ANNULÉE", h)
        self.assertIn("Erreur de client", h)
        self.assertNotIn("Pour payer", h)
        s = Facture.solde_ouverture(self.c, D("380"), saison_origine="2025-2026")
        h = pdf.html(s)
        self.assertIn("SOLDE ANTÉRIEUR", h)
        self.assertNotIn("TPS", h)
        self.assertNotIn("Quantité", h)

    def test_pdf_pour_un_membre_seulement(self):
        url = f"/factures/{self.f.pk}/pdf/"
        self.assertEqual(self.client.get(url).status_code, 302)  # pas connecté
        self.client.force_login(self.louis)
        r = self.client.get(url)
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))
        self.assertIn('filename="facture-57.pdf"', r["Content-Disposition"])
        self.assertEqual(r["Cache-Control"], "private, no-store")
        c2 = Client.objects.create(entreprise=self.autre, nom="Ailleurs")
        f2 = Facture.objects.create(entreprise=self.autre, client=c2)
        self.assertEqual(self.client.get(f"/factures/{f2.pk}/pdf/").status_code, 404)


class VersementsDusTests(TestCase):
    def test_brouillons_pour_les_versements_dus_seulement(self):
        from facturation.tasks import facturer_versements_dus

        ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine="essai.exemple.test", inscrit_taxes=True)
        c = Client.objects.create(entreprise=ent, nom="Tremblay")
        s = Saison.objects.create(entreprise=ent, nom="2026-2027", debut=date(2026, 11, 1), fin=date(2027, 4, 15))
        contrat = Contrat.objects.create(entreprise=ent, client=c, saison=s, prix=D("400"))
        v1, v2 = contrat.creer_echeancier([date(2026, 11, 15), date(2027, 1, 15)])
        inactif = Contrat.objects.create(entreprise=ent, client=c, saison=s, prix=D("100"), actif=False)
        inactif.creer_echeancier([date(2026, 11, 1)])
        self.assertEqual(facturer_versements_dus(date(2026, 12, 1)), 1)
        v1.refresh_from_db()
        self.assertEqual((v1.facture.statut, v1.facture.total), ("brouillon", D("229.95")))
        self.assertEqual(facturer_versements_dus(date(2026, 12, 2)), 0)  # relançable
        self.assertEqual(facturer_versements_dus(date(2027, 1, 15)), 1)
