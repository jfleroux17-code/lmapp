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
        self.assertEqual(importation.appliquer(a, self.ent), (2, 2))
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
        self.assertEqual(importation.appliquer(a, self.ent, sauter_erreurs=True), (1, 1))
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

    def test_montants_et_colonnes_plus_tard(self):
        a = self._analyser(_csv("nom;adresse;ville;prix_saison;solde_du\nRoy;1 rue A;X;450;1 250,50 $\n"))
        self.assertEqual(a.lignes[0].plus_tard, {"prix_saison": Decimal("450.00"), "solde_du": Decimal("1250.50")})
        self.assertEqual(sorted(a.colonnes_plus_tard), ["prix_saison", "solde_du"])

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
        self.assertEqual(a.lignes[0].statut, "a_creer")

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
