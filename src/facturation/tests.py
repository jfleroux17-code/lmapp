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


AVIS_FR = """Bonjour LOUIS METHOT,

GINETTE TREMBLAY vous a envoyé 158,69 $ (CAD) et l'argent a été déposé automatiquement dans votre compte bancaire.

Message : Facture 1001 merci!

Numéro de référence : CA1AbCdEfGh2
"""
AVIS_EN = """Hi LOUIS METHOT,
JEAN-PIERRE COTE sent you $1,200.00 (CAD) and the money has been automatically deposited into your bank account.
Reference Number: C1aBcDeFgHiJ
"""


class InteracTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from clients.models import Client
        from core.models import Entreprise
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine="essai.exemple.test", prochain_numero_facture=1001,
                                            courriel_reponse="louis@exemple.test")
        cls.ginette = Client.objects.create(entreprise=cls.ent, prenom="Ginette", nom="Tremblay")
        cls.cote = Client.objects.create(entreprise=cls.ent, prenom="Jean-Pierre", nom="Côté")
        cls.roy = Client.objects.create(entreprise=cls.ent, nom="Roy")

        def facture(client, montant, jour):
            f = Facture.objects.create(entreprise=cls.ent, client=client, date_facture=date(2026, 11, jour))
            f.lignes.create(description="Déneigement", quantite=1, prix_unitaire=D(montant), taxable=False)
            f.recalculer()
            f.emettre()
            return f
        cls.f_ginette = facture(cls.ginette, "158.69", 2)    # n° 1001
        cls.f_cote1 = facture(cls.cote, "700.00", 1)          # n° 1002
        cls.f_cote2 = facture(cls.cote, "600.00", 3)          # n° 1003
        cls.f_roy = facture(cls.roy, "158.69", 4)             # n° 1004 : même montant que Ginette

    def test_lecture_des_avis(self):
        from facturation import interac
        self.assertEqual(interac.extraire("Virement INTERAC : dépôt", AVIS_FR),
                         (D("158.69"), "GINETTE TREMBLAY", "Facture 1001 merci!", "CA1AbCdEfGh2"))
        self.assertEqual(interac.extraire("INTERAC e-Transfer", AVIS_EN), (D("1200.00"), "JEAN-PIERRE COTE", "", "C1aBcDeFgHiJ"))
        self.assertIsNone(interac.extraire("Virement INTERAC", "Votre virement a été annulé."))
        self.assertTrue(interac.est_un_avis("notify@payments.interac.ca", "n'importe quoi"))
        self.assertTrue(interac.est_un_avis("entretiens.louismethot@gmail.com", "Fwd: Virement INTERAC : dépôt automatique"))
        self.assertFalse(interac.est_un_avis("client@example.com", "Re: Facture 1001"))

    def test_facture_proposee(self):
        from facturation import interac
        from facturation.models import VirementInterac

        def v(montant, envoyeur="", message=""):
            return interac.apparier(VirementInterac(entreprise=self.ent, montant=D(montant), envoyeur=envoyeur, message_envoyeur=message))
        self.assertEqual(v("158.69", "Quelqu'un", "facture 1004"), (self.f_roy, "numéro de facture 1004 dans le message"))
        self.assertEqual(v("158.69", "GINETTE TREMBLAY"), (self.f_ginette, "même montant et même nom"))
        self.assertEqual(v("158.69", "Inconnu"), (None, ""))  # deux factures de ce montant, nom inconnu : Louis choisit
        self.assertEqual(v("600.00", "Quelqu'un"), (self.f_cote2, "seule facture due de ce montant"))
        self.assertEqual(v("1300.00", "JEAN-PIERRE COTE"), (self.f_cote1, "même nom que l'envoyeur (plus vieille facture due)"))

    def test_recu_par_courriel_puis_enregistre_sur_plusieurs_factures(self):
        from email.message import EmailMessage
        from communications import reception
        from facturation import interac
        from facturation.models import VirementInterac
        e = EmailMessage()
        e["From"], e["Subject"], e["Message-ID"] = "notify@payments.interac.ca", "INTERAC e-Transfer: deposit", "<i1@interac.ca>"
        e["Date"] = "Sun, 08 Nov 2026 15:42:12 -0500"
        e.set_content(AVIS_EN)
        m = reception.traiter(self.ent, e.as_bytes())
        self.assertEqual((m.genre, m.lu, m.client), ("interac", True, self.cote))  # pas un message à lire : un virement à confirmer
        v = VirementInterac.objects.get()
        self.assertEqual((v.montant, v.facture, v.statut), (D("1200.00"), self.f_cote1, "a_traiter"))
        self.assertIsNone(reception.traiter(self.ent, e.as_bytes()))  # le même avis deux fois
        paiements = interac.enregistrer(v, self.f_cote2)  # Louis choisit la 1003 : elle d'abord, puis la plus vieille
        self.assertEqual([(p.facture, p.montant, p.mode, p.reference) for p in paiements],
                         [(self.f_cote2, D("600.00"), "interac", "C1aBcDeFgHiJ"), (self.f_cote1, D("600.00"), "interac", "C1aBcDeFgHiJ")])
        v.refresh_from_db()
        self.assertEqual(v.statut, "enregistre")
        with self.assertRaisesMessage(ValidationError, "déjà traité"):
            interac.enregistrer(v, self.f_cote1)

    def test_jamais_plus_que_ce_que_le_client_doit(self):
        from facturation import interac
        from facturation.models import VirementInterac
        v = VirementInterac.objects.create(entreprise=self.ent, recu_le="2026-11-08T12:00:00Z", montant=D("200.00"), envoyeur="Ginette")
        with self.assertRaisesMessage(ValidationError, "doit moins que le virement"):
            interac.enregistrer(v, self.f_ginette)
        self.assertFalse(Paiement.objects.exists())  # tout ou rien
        v.refresh_from_db()
        self.assertEqual(v.statut, "a_traiter")

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_ecran_des_virements(self):
        from django.contrib.auth import get_user_model
        from core.models import Membre
        from facturation.models import VirementInterac
        u = get_user_model().objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=u, entreprise=self.ent, role="operateur")
        self.client.defaults["HTTP_HOST"] = "essai.exemple.test"
        self.client.force_login(u)
        v = VirementInterac.objects.create(entreprise=self.ent, recu_le="2026-11-08T12:00:00Z", montant=D("158.69"), envoyeur="GINETTE TREMBLAY",
                                           facture=self.f_ginette, client=self.ginette, raison="même montant et même nom")
        autre = VirementInterac.objects.create(entreprise=self.ent, recu_le="2026-11-08T12:00:00Z", montant=D("5.00"), envoyeur="?")
        self.assertContains(self.client.get("/comptes/"), "2 virements Interac à confirmer")
        page = self.client.get("/virements/")
        self.assertContains(page, "Enregistrer : Ginette Tremblay")
        r = self.client.post(f"/virements/{v.pk}/", {"facture": self.f_ginette.pk}, follow=True)
        self.assertContains(r, "Virement de 158,69")
        self.assertEqual(self.f_ginette.solde, D("0.00"))
        self.client.post(f"/virements/{autre.pk}/", {"action": "ignorer"})
        autre.refresh_from_db()
        self.assertEqual(autre.statut, "ignore")
        self.assertNotContains(self.client.get("/comptes/"), "à confirmer")


@override_settings(ALLOWED_HOSTS=["*"])
class BilanSaisonTests(TestCase):
    def test_bilan_de_la_saison_dans_les_comptes(self):
        from django.contrib.auth import get_user_model
        from django.utils import timezone
        from core.models import Membre
        ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine="essai.exemple.test", inscrit_taxes=True,
                                        numero_tps="1", numero_tvq="2")
        aujourdhui = timezone.localdate()
        Saison.objects.create(entreprise=ent, nom="Saison test", debut=aujourdhui.replace(day=1), fin=aujourdhui)
        c = Client.objects.create(entreprise=ent, nom="Tremblay")
        f = Facture.objects.create(entreprise=ent, client=c)
        f.lignes.create(description="Déneigement", quantite=1, prix_unitaire=D("100.00"))
        f.recalculer()
        f.emettre()
        Paiement.objects.create(entreprise=ent, facture=f, montant=D("50.00"), mode="comptant")
        u = get_user_model().objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=u, entreprise=ent, role="operateur")
        self.client.defaults["HTTP_HOST"] = "essai.exemple.test"
        self.client.force_login(u)
        page = self.client.get("/comptes/")
        b = page.context["saison"]
        self.assertEqual((b["nom"], b["facture"], b["encaisse"], b["clients"], b["taxes"], b["tvq"]),
                         ("Saison test", D("114.98"), D("50.00"), 1, D("5.00"), D("9.98")))
        self.assertContains(page, "Saison Saison test")


class EtatCompteTests(TestCase):
    """État de compte (C10) : factures émises et paiements dans l'ordre, solde courant, annulées exclues."""

    @classmethod
    def setUpTestData(cls):
        from datetime import date as d
        from decimal import Decimal as D
        from django.contrib.auth import get_user_model
        from clients.models import Client
        from core.models import Entreprise, Membre
        from facturation.models import Facture, Paiement
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai-ec", domaine="ec.exemple.test", prochain_numero_facture=10)
        cls.c = Client.objects.create(entreprise=cls.ent, prenom="Ginette", nom="Tremblay")
        Facture.solde_ouverture(cls.c, D("50.00"), saison_origine="2025-2026", date_facture=d(2026, 11, 1))
        f = Facture.objects.create(entreprise=cls.ent, client=cls.c, date_facture=d(2026, 11, 2))
        f.lignes.create(description="Saison", quantite=1, prix_unitaire=D("300.00"), taxable=False)
        f.recalculer()
        f.emettre()
        Paiement.objects.create(entreprise=cls.ent, facture=f, date=d(2026, 11, 5), montant=D("100.00"), mode="comptant")
        a = Facture.objects.create(entreprise=cls.ent, client=cls.c)
        a.lignes.create(description="Erreur", quantite=1, prix_unitaire=D("999.00"), taxable=False)
        a.recalculer()
        a.emettre()
        a.annuler("Erreur de saisie")
        cls.louis = get_user_model().objects.create_user("louis-ec", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")

    def test_mouvements_et_solde(self):
        from decimal import Decimal as D
        from facturation import etat_compte
        lignes, solde = etat_compte.mouvements(self.c)
        self.assertEqual([l["quoi"] for l in lignes], ["Solde antérieur (2025-2026)", "Facture n° 10", "Paiement, comptant (facture n° 10)"])
        self.assertEqual([l["solde"] for l in lignes], [D("50.00"), D("350.00"), D("250.00")])
        self.assertEqual(solde, D("250.00"))

    def test_pdf_pour_les_membres(self):
        from django.test import override_settings
        self.client.force_login(self.louis)
        with override_settings(ALLOWED_HOSTS=["*"]):
            r = self.client.get(f"/clients/{self.c.pk}/etat-de-compte/", HTTP_HOST="ec.exemple.test")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.content.startswith(b"%PDF"))
