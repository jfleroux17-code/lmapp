import tempfile
from decimal import Decimal
from pathlib import Path

from django.test import TestCase

from clients import importation
from clients.models import Adresse, Client, Secteur
from core.models import Entreprise


def _csv(contenu, encodage="utf-8"):
    f = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
    f.write(contenu.encode(encodage))
    f.close()
    return f.name


class ImportationTests(TestCase):
    def setUp(self):
        self.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine="essai.exemple.test")

    def _analyser(self, chemin):
        return importation.analyser(importation.lire(chemin), self.ent)

    def test_csv_excel_francais_windows1252(self):
        # Ce qu'Excel produit en français : Windows-1252, point-virgule, en-têtes accentués
        chemin = _csv("Prénom;Nom;Cellulaire;Adresse;Ville;Mode de paiement\n"
                      "Ginette;Tremblay;(450) 555-0101;120, rue des Essais;Sainte-Adèle;Comptant\n", "cp1252")
        a = self._analyser(chemin)
        self.assertEqual((a.fichier.encodage, a.fichier.separateur), ("Windows-1252", "point-virgule"))
        self.assertEqual(len(a.a_creer), 1)
        l = a.lignes[0]
        self.assertEqual(l.client.cellulaire, "+14505550101")
        self.assertEqual(l.client.mode_paiement, "comptant")
        self.assertEqual(l.adresse.ville, "Sainte-Adèle")
        self.assertEqual(Client.objects.count(), 0)  # essai à blanc : rien d'écrit

    def test_appliquer_puis_relancer(self):
        chemin = _csv("nom,cellulaire,adresse,ville,secteur,rang_tournee\n"
                      "Tremblay,4505550101,1 rue A,Val-David,Village,1\n"
                      "Gagnon,4505550102,2 rue A,Val-David,village,2\n")
        a = self._analyser(chemin)
        self.assertEqual(a.secteurs_nouveaux, ["Village"])  # « village » et « Village » : un seul secteur
        r = importation.appliquer(a, self.ent)
        self.assertEqual((r.clients, r.adresses), (2, 2))
        self.assertEqual(Secteur.objects.get().nom, "Village")
        self.assertEqual(list(Adresse.objects.order_by("ordre_tournee").values_list("ordre_tournee", flat=True)), [1, 2])
        # Relancer le même fichier : tout est déjà en base
        a2 = self._analyser(chemin)
        self.assertEqual(len(a2.existantes), 2)
        self.assertEqual(len(a2.a_creer), 0)

    def test_erreurs_bloquent_tout(self):
        chemin = _csv("nom;cellulaire;adresse;ville;borne_fontaine\n"
                      "Tremblay;4505550101;1 rue A;Val-David;oui\n"
                      ";4505550102;2 rue A;Val-David;non\n"          # pas de nom
                      "Roy;555-0103;3 rue A;Val-David;non\n"          # cellulaire invalide
                      "Côté;4505550104;4 rue A;Val-David;peut-être\n")  # ni oui ni non
        a = self._analyser(chemin)
        self.assertEqual([l.numero for l in a.erreurs], [3, 4, 5])
        with self.assertRaises(ValueError):
            importation.appliquer(a, self.ent)
        self.assertEqual(Client.objects.count(), 0)
        # En sautant les erreurs : seule la ligne valide entre
        r = importation.appliquer(a, self.ent, sauter_erreurs=True)
        self.assertEqual((r.clients, r.adresses), (1, 1))
        self.assertTrue(Adresse.objects.get().borne_fontaine)

    def test_un_client_deux_adresses(self):
        chemin = _csv("no_client;nom;adresse;ville\n"
                      "8;Pelletier;2 rue de la Démo;Val-David\n"
                      "8;Pelletier;4 rue de la Démo;Val-David\n"
                      "8;Autre;6 rue de la Démo;Val-David\n")  # même numéro, autre nom : erreur
        a = self._analyser(chemin)
        self.assertEqual([l.statut for l in a.lignes], ["a_creer", "adresse_seulement", "erreur"])
        importation.appliquer(a, self.ent, sauter_erreurs=True)
        self.assertEqual(Client.objects.count(), 1)
        self.assertEqual(Client.objects.get().adresses.count(), 2)

    def test_groupe_suit_la_premiere_ligne(self):
        Client.objects.create(entreprise=self.ent, nom="Pelletier", cellulaire="+14505550108")
        chemin = _csv("no_client;nom;cellulaire;adresse;ville\n"
                      "8;Pelletier;4505550108;2 rue de la Démo;Val-David\n"
                      "8;Pelletier;4505550108;4 rue de la Démo;Val-David\n")
        a = self._analyser(chemin)
        self.assertEqual([l.statut for l in a.lignes], ["existe", "existe"])  # pas de doublon de client

    def test_colonne_obligatoire_manquante(self):
        a = self._analyser(_csv("nom;ville\nTremblay;Val-David\n"))
        self.assertEqual(a.manquantes, ["adresse"])
        with self.assertRaises(ValueError):
            importation.appliquer(a, self.ent)

    def test_meme_adresse_deux_fois(self):
        a = self._analyser(_csv("nom;adresse;ville\nA;1, rue A;Val-David\nB;1 rue A;VAL-DAVID\n"))
        self.assertEqual(a.lignes[1].statut, "erreur")

    def test_consentement_sans_date(self):
        a = self._analyser(_csv("nom;adresse;ville;consentement_commercial\nRoy;1 rue A;X;oui\n"))
        l = a.lignes[0]
        self.assertEqual(l.statut, "a_creer")
        self.assertIsNotNone(l.client.consentement_date)
        self.assertEqual(l.client.consentement_source, "import")
        self.assertTrue(l.avertissements)

    def test_montants_et_colonnes_d_argent(self):
        a = self._analyser(_csv("nom;adresse;ville;prix_saison;solde_du\nRoy;1 rue A;X;450;1 250,50 $\n"))
        self.assertEqual(a.lignes[0].argent, {"prix_saison": Decimal("450.00"), "solde_du": Decimal("1250.50")})
        self.assertEqual(sorted(a.colonnes_argent), ["prix_saison", "solde_du"])
        self.assertEqual(a.lignes[0].erreurs, [])
        self.assertIsNone(a.saison.pk)  # pas encore de saison : l'import la créera
        r = importation.appliquer(a, self.ent)
        self.assertEqual((r.contrats, r.soldes), (1, 1))
        self.assertEqual((a.saison.debut.month, a.saison.debut.day, a.saison.fin.month), (11, 1, 4))

    def test_contrats_et_soldes_importes(self):
        from datetime import date as d
        from facturation.models import Contrat, Facture, Saison

        Saison.objects.create(entreprise=self.ent, nom="2026-2027", debut=d(2026, 11, 1), fin=d(2027, 4, 15))
        fichier = _csv(
            "no_client;nom;adresse;ville;prix_saison;type_contrat;prix_entendu_texte;solde_du;solde_saison;solde_note\n"
            "1;Roy;1 rue A;X;450;;450 $ en 2 fois;100;2025-2026;Mars pas payé\n"
            "1;Roy;2 rue A;X;30;au passage;;;;\n"
            "2;Côté;3 rue A;X;12;à l'heure;;0;;\n"
            "3;Gagnon;4 rue A;X;;;;80,50;;\n")
        a = self._analyser(fichier)
        self.assertEqual((a.nb_contrats, a.nb_soldes), (2, 2))
        self.assertIn("à créer à la main", " ".join(a.lignes[2].avertissements))
        r = importation.appliquer(a, self.ent)
        self.assertEqual((r.clients, r.adresses, r.contrats, r.soldes), (3, 4, 2, 2))
        roy = Contrat.objects.filter(client__nom="Roy").order_by("prix")
        self.assertEqual([(c.type, c.prix, c.adresse.ligne1) for c in roy], [("au_passage", Decimal("30.00"), "2 rue A"), ("saisonnier", Decimal("450.00"), "1 rue A")])
        self.assertEqual(roy.last().prix_texte, "450 $ en 2 fois")
        s = Facture.objects.get(client__nom="Roy", genre="solde_ouverture")
        saison = Facture.objects.get(client__nom="Roy", genre="facture")  # facture de la saison, en brouillon
        self.assertEqual((saison.statut, saison.sous_total), ("brouillon", Decimal("450.00")))
        self.assertEqual(saison.versements.count(), roy.last().versements.count())
        self.assertEqual((s.genre, s.total, s.saison_origine, s.note_interne, s.statut), ("solde_ouverture", Decimal("100.00"), "2025-2026", "Mars pas payé", "emise"))
        self.assertEqual(Facture.objects.get(client__nom="Gagnon").total, Decimal("80.50"))
        self.assertFalse(Facture.objects.filter(client__nom="Côté").exists())  # solde à 0 : rien

    def test_echeancier_cree_avec_le_contrat(self):
        from datetime import date as d
        from facturation.models import Contrat, Saison

        Entreprise.objects.filter(pk=self.ent.pk).update(versements_par_defaut=2, dates_versements="15/01 15/02")
        self.ent.refresh_from_db()
        Saison.objects.create(entreprise=self.ent, nom="2026-2027", debut=d(2026, 11, 1), fin=d(2027, 4, 30))
        a = self._analyser(_csv("nom;adresse;ville;prix_saison;versements\nRoy;1 rue A;X;450;\nCôté;2 rue A;X;1500;3\nGagnon;3 rue A;X;900;4\n"))
        self.assertIn("la fiche de l'entreprise n'a que 2 date(s)", " ".join(a.lignes[2].erreurs))
        a = self._analyser(_csv("nom;adresse;ville;prix_saison;versements\nRoy;1 rue A;X;450;\nCôté;2 rue A;X;1500;3\n"))
        importation.appliquer(a, self.ent)
        roy, cote = Contrat.objects.get(client__nom="Roy"), Contrat.objects.get(client__nom="Côté")
        self.assertEqual([(v.date_prevue.month, v.montant) for v in roy.versements.all()][1:], [(1, Decimal("225.00"))])
        self.assertEqual(roy.versements.count(), 2)
        self.assertEqual([v.date_prevue for v in cote.versements.all()][1:], [d(2027, 1, 15), d(2027, 2, 15)])
        self.assertEqual({v.montant for v in cote.versements.all()}, {Decimal("500.00")})

    def _saison_et_taxes(self):
        from datetime import date as d
        from facturation.models import Saison

        Entreprise.objects.filter(pk=self.ent.pk).update(versements_par_defaut=2, dates_versements="15/01 15/02", inscrit_taxes=True,
                                                         taux_tps=Decimal("5"), taux_tvq=Decimal("9.975"))
        self.ent.refresh_from_db()
        Saison.objects.create(entreprise=self.ent, nom="2026-2027", debut=d(2020, 11, 1), fin=d(2099, 4, 30))

    def test_taxes_incluses_redonnent_le_montant_exact(self):
        from facturation.models import Contrat

        self._saison_et_taxes()
        a = self._analyser(_csv("nom;adresse;ville;prix_saison;taxes_incluses;versements\n"
                                "Roy;1 rue A;X;792;oui;\nCôté;2 rue A;X;1200;oui;3\nGagnon;3 rue A;X;500;non;\n"))
        self.assertEqual([l.erreurs for l in a.lignes], [[], [], []])
        importation.appliquer(a, self.ent)
        for nom, total in (("Roy", "792.00"), ("Côté", "1200.00")):
            c = Contrat.objects.get(client__nom=nom)
            self.assertEqual(c.facturer_saison().total, Decimal(total), nom)  # une facture pour la saison, taxes une fois
            self.assertIn("taxes incluses", c.prix_texte)
        self.assertEqual(Contrat.objects.get(client__nom="Gagnon").prix, Decimal("500.00"))  # plus taxes : inchangé

    def test_extra_sur_le_meme_contrat(self):
        from facturation.models import Contrat, Service

        self._saison_et_taxes()
        Service.objects.create(entreprise=self.ent, nom="Déneigement de l'entrée")
        a = self._analyser(_csv("nom;adresse;ville;prix_saison;service;extra_service;extra_prix\n"
                                "Bélanger;1 rue A;X;792;déneigement de l'entrée;Sablage;200\nRoy;2 rue A;X;400;;;50\n"))
        self.assertIn("extra_prix sans extra_service", " ".join(a.lignes[1].erreurs))
        a = self._analyser(_csv("nom;adresse;ville;prix_saison;service;extra_service;extra_prix\n"
                                "Bélanger;1 rue A;X;792;déneigement de l'entrée;Sablage;200\n"))
        self.assertEqual(a.services_nouveaux, ["Sablage"])
        r = importation.appliquer(a, self.ent)
        c = Contrat.objects.get()
        self.assertEqual((c.prix, c.prix_texte, r.services), (Decimal("992.00"), "792 $ + 200 $ sablage plus taxes", 1))
        self.assertEqual(sorted(c.services.values_list("nom", flat=True)), ["Déneigement de l'entrée", "Sablage"])

    def test_argent_deja_recu_en_credit(self):
        from facturation import credits
        from facturation.models import Contrat, Credit, Paiement

        self._saison_et_taxes()
        a = self._analyser(_csv("nom;adresse;ville;prix_saison;taxes_incluses;mode_paiement;recu_montant;recu_date;recu_mode\n"
                                "Desrosiers;1 rue A;X;792;oui;interac;280;2026-11-02;\n"
                                "Roy;2 rue A;X;400;;;100;;\n"
                                "Côté;3 rue A;X;400;;;100;2099-01-01;comptant\n"))
        self.assertEqual(a.lignes[0].erreurs, [])
        self.assertIn("recu_mode", " ".join(a.lignes[1].erreurs))
        self.assertIn("dans le futur", " ".join(a.lignes[2].erreurs))
        r = importation.appliquer(a, self.ent, sauter_erreurs=True)
        self.assertEqual(r.credits, 1)
        cr = Credit.objects.get()
        self.assertEqual((cr.montant, cr.mode, str(cr.date)), (Decimal("280.00"), "interac", "2026-11-02"))
        self.assertEqual(credits.encaisse(self.ent), Decimal("280.00"))
        f = Contrat.objects.get().versements.first().facturer()
        f.emettre()
        f.refresh_from_db()
        self.assertEqual(f.paiements.get().mode, Paiement.Mode.CREDIT)
        self.assertEqual(f.solde, Decimal("792.00") - Decimal("280.00"))  # facture de la saison au complet

    def test_commande_essai_a_blanc_puis_appliquer(self):
        """La commande elle-même (pas seulement le module) : essai à blanc, puis --appliquer."""
        from io import StringIO

        from django.core.management import call_command

        self._saison_et_taxes()
        chemin = _csv("nom;adresse;ville;statut;prix_saison;taxes_incluses;extra_service;extra_prix;recu_montant;recu_mode\n"
                      "Roy;1 rue A;X;;792;oui;Sablage;200;280;interac\nCôté;2 rue A;X;inactif;;;;;;\n")
        sortie = StringIO()
        call_command("importer_clients", str(chemin), "--entreprise", "essai", stdout=sortie)
        texte = sortie.getvalue()
        for attendu in ("1 actif, 1 inactif", "Taxes incluses : 1 contrat(s)", "Services ajoutés au catalogue : Sablage",
                        "Déjà reçu : 1 client(s), 280 $", "ESSAI À BLANC"):
            self.assertIn(attendu, texte)
        self.assertFalse(Client.objects.exists())
        sortie = StringIO()
        call_command("importer_clients", str(chemin), "--entreprise", "essai", "--appliquer", stdout=sortie)
        self.assertIn("2 client(s), 2 adresse(s), 1 contrat(s), 0 solde(s) antérieur(s), 1 service(s) ajouté(s), 1 montant(s)", sortie.getvalue())

    def test_decompte_des_statuts(self):
        a = self._analyser(_csv("nom;adresse;ville;statut\nRoy;1 rue A;X;\nCôté;2 rue A;X;inactif\nGagnon;3 rue A;X;actif\n"))
        self.assertEqual(dict(a.statuts), {"actif": 2, "inactif": 1})

    def test_excel_avec_numero_en_nombre(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Clients"
        ws.append(["nom", "cellulaire", "adresse", "ville", "consentement_date"])
        ws.append(["Tremblay", 4505550101, "1 rue A", "Val-David", None])  # Excel a fait du numéro un nombre
        chemin = Path(tempfile.mkdtemp()) / "clients.xlsx"
        wb.save(chemin)
        a = self._analyser(chemin)
        self.assertEqual(a.lignes[0].client.cellulaire, "+14505550101")
        self.assertEqual((a.lignes[0].statut, a.lignes[0].erreurs), ("a_creer", []))

    def test_gabarit_se_reimporte(self):
        # Le gabarit, avec ses deux lignes d'exemple, doit passer sans erreur
        from django.core.management import call_command
        dossier = tempfile.mkdtemp()
        call_command("gabarit_import", dossier, stdout=open("/dev/null", "w"))
        for nom in ("gabarit_import_clients.xlsx", "gabarit_import_clients.csv"):
            a = self._analyser(Path(dossier) / nom)
            self.assertEqual(a.inconnues, [], nom)
            self.assertEqual(len(a.erreurs), 0, [(l.numero, l.erreurs) for l in a.erreurs])
            self.assertEqual(len(a.a_creer), 2, nom)


class ImportVillesTests(TestCase):
    def setUp(self):
        from django.contrib.gis.geos import Point
        from core.models import VilleDesservie
        self.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine="essai.exemple.test")
        VilleDesservie.objects.create(entreprise=self.ent, nom="Sainte-Adèle", centre=Point(-74.13, 45.95, srid=4326), par_defaut=True)

    def test_ville_vide_ville_abregee_ville_non_desservie(self):
        a = importation.analyser(importation.lire(_csv(
            "nom;adresse;ville\nA;1 rue A;\nB;2 rue A;Ste-Adèle\nC;3 rue A;Val-David\n")), self.ent)
        self.assertEqual([l.adresse.ville for l in a.lignes], ["Sainte-Adèle", "Sainte-Adèle", "Val-David"])
        self.assertEqual([l.statut for l in a.lignes], ["a_creer"] * 3)
        self.assertTrue(any("non desservie" in av for av in a.lignes[2].avertissements))
        self.assertFalse(any("non desservie" in av for av in a.lignes[1].avertissements))

    def test_colonne_ville_absente(self):
        a = importation.analyser(importation.lire(_csv("nom;adresse\nA;1 rue A\n")), self.ent)
        self.assertEqual(a.manquantes, [])
        self.assertEqual(a.lignes[0].adresse.ville, "Sainte-Adèle")


class CorrespondanceTests(TestCase):
    """PRD Q3 : fichiers exportés d'un autre logiciel (entêtes en anglais, noms différents)."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.gis.geos import Point
        from core.models import VilleDesservie
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine="essai.exemple.test", ville="Sainte-Adèle")
        VilleDesservie.objects.create(entreprise=cls.ent, nom="Sainte-Adèle", centre=Point(-74.13, 45.95, srid=4326), par_defaut=True)

    def test_entetes_anglais_reconnus(self):
        chemin = _csv("First Name;Last Name;Mobile Phone;Email Address;Street Address;City;Postal Code;Balance Due\n"
                      "Ginette;Tremblay;450-555-0101;g@example.com;8, rue des Essais;Sainte-Adèle;J8B1A1;120.00\n")
        a = importation.analyser(importation.lire(chemin), self.ent)
        self.assertEqual(a.inconnues, [])
        self.assertEqual(sorted(a.colonnes.values()), sorted(["prenom", "nom", "cellulaire", "courriel", "adresse", "ville", "code_postal", "solde_du"]))

    def test_correspondance_prioritaire(self):
        chemin = _csv("Client;Tél. principal;Lieu;Code interne\nTremblay;450 555-0101;8, rue des Essais;X12\n")
        a = importation.analyser(importation.lire(chemin), self.ent,
                                 {"Tél. principal": "cellulaire", "Lieu": "adresse", "Code interne": ""})
        self.assertEqual(sorted(a.colonnes.values()), ["adresse", "cellulaire", "nom"])
        self.assertEqual(a.inconnues, [])  # « Code interne » ignorée exprès, pas signalée comme inconnue
        self.assertEqual((a.lignes[0].statut, a.lignes[0].erreurs), ("a_creer", []))
        with self.assertRaisesMessage(ValueError, "n'est pas une colonne du gabarit"):
            importation.analyser(importation.lire(chemin), self.ent, {"Lieu": "adresse_civique_inventee"})

    def test_logiciel_inconnu(self):
        with self.assertRaisesMessage(FileNotFoundError, "Pas de correspondance pour"):
            importation.correspondance_du_logiciel("logiciel inexistant")
