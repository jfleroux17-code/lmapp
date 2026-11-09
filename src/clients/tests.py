from datetime import date

from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from django.core.exceptions import ValidationError
from django.test import TestCase

from clients.models import Adresse, Client, Secteur
from core.models import Entreprise


def _entreprise(slug="essai"):
    return Entreprise.objects.create(nom=f"Déneigement {slug}", slug=slug, domaine=f"{slug}.exemple.test")


class ClientTests(TestCase):
    def setUp(self):
        self.ent = _entreprise()

    def test_normalisation_a_la_validation(self):
        c = Client(entreprise=self.ent, prenom="Ginette", nom="Tremblay", cellulaire="(450) 555-1234", courriel=" Ginette@Exemple.CA ")
        c.full_clean()
        self.assertEqual(c.cellulaire, "+14505551234")
        self.assertEqual(c.courriel, "ginette@exemple.ca")

    def test_cellulaire_invalide_refuse(self):
        c = Client(entreprise=self.ent, nom="Tremblay", cellulaire="555-1234")
        with self.assertRaises(ValidationError) as e:
            c.full_clean()
        self.assertIn("cellulaire", e.exception.message_dict)

    def test_nom_obligatoire(self):
        with self.assertRaises(ValidationError):
            Client(entreprise=self.ent).full_clean()

    def test_nom_affiche(self):
        self.assertEqual(Client(prenom="Ginette", nom="Tremblay").nom_affiche, "Ginette Tremblay")
        self.assertEqual(Client(organisation="Syndicat du 12", nom="Roy").nom_affiche, "Syndicat du 12 (Roy)")

    def test_consentement_exige_une_date(self):
        c = Client(entreprise=self.ent, nom="Roy", consentement_commercial=True)
        with self.assertRaises(ValidationError) as e:
            c.full_clean()
        self.assertIn("consentement_date", e.exception.message_dict)

    def test_desabonne_ne_recoit_plus_le_commercial(self):
        from django.utils import timezone
        c = Client(nom="Roy", consentement_commercial=True, consentement_date=date(2026, 11, 7))
        self.assertTrue(c.peut_recevoir_commercial)
        c.desabonne_le = timezone.now()
        self.assertFalse(c.peut_recevoir_commercial)


class AdresseTests(TestCase):
    def setUp(self):
        self.ent = _entreprise()
        self.client_ = Client.objects.create(entreprise=self.ent, nom="Tremblay")

    def test_code_postal_normalise(self):
        a = Adresse(entreprise=self.ent, client=self.client_, ligne1="123, rue Principale", ville="Sainte-Adèle", code_postal="j8b2x1")
        a.full_clean()
        self.assertEqual(a.code_postal, "J8B 2X1")

    def test_isolation_entre_entreprises(self):
        autre = _entreprise("autre")
        secteur_autre = Secteur.objects.create(entreprise=autre, nom="Nord")
        a = Adresse(entreprise=self.ent, client=self.client_, ligne1="1, rue A", ville="X", secteur=secteur_autre)
        with self.assertRaises(ValidationError):
            a.full_clean()
        a = Adresse(entreprise=autre, client=self.client_, ligne1="1, rue A", ville="X")
        with self.assertRaises(ValidationError):
            a.full_clean()

    def test_recherche_par_distance_postgis(self):
        # Deux adresses à Sainte-Adèle, une à Saint-Jérôme (environ 25 km)
        proche1 = Adresse.objects.create(entreprise=self.ent, client=self.client_, ligne1="1, rue A", ville="Sainte-Adèle", position=Point(-74.1340, 45.9500, srid=4326))
        proche2 = Adresse.objects.create(entreprise=self.ent, client=self.client_, ligne1="2, rue A", ville="Sainte-Adèle", position=Point(-74.1300, 45.9520, srid=4326))
        Adresse.objects.create(entreprise=self.ent, client=self.client_, ligne1="3, rue B", ville="Saint-Jérôme", position=Point(-74.0040, 45.7800, srid=4326))
        louis_est_ici = Point(-74.1335, 45.9505, srid=4326)
        a_moins_de_800_m = Adresse.objects.filter(position__dwithin=(louis_est_ici, D(m=800)))
        self.assertEqual(set(a_moins_de_800_m), {proche1, proche2})
        self.assertAlmostEqual(proche1.latitude, 45.95)


class DonneesEssaiTests(TestCase):
    def test_refuse_en_prod(self):
        from django.core.management import CommandError, call_command
        from django.test import override_settings
        with override_settings(LMAPP_ENV="prod"):
            with self.assertRaises(CommandError):
                call_command("donnees_essai", stdout=open("/dev/null", "w"))
        self.assertEqual(Entreprise.objects.count(), 0)

    def test_creation_puis_rien_en_double(self):
        from django.core.management import call_command
        from django.test import override_settings
        with override_settings(LMAPP_ENV="test"):
            call_command("donnees_essai", stdout=open("/dev/null", "w"))
            call_command("donnees_essai", stdout=open("/dev/null", "w"))
        self.assertEqual(Entreprise.objects.count(), 1)
        self.assertEqual(Client.objects.count(), 10)
        self.assertEqual(Adresse.objects.count(), 11)
        # Tous les cellulaires dans la plage fictive 555-01XX
        self.assertTrue(all(c.cellulaire.startswith("+1450555") and c.cellulaire[-4:-2] == "01" for c in Client.objects.all()))


class ReinitialiserTests(TestCase):
    def test_reinitialiser_n_efface_que_l_essai(self):
        from django.core.management import call_command
        from django.test import override_settings
        autre = _entreprise("autre")
        Client.objects.create(entreprise=autre, nom="Garder")
        with override_settings(LMAPP_ENV="test"):
            call_command("donnees_essai", stdout=open("/dev/null", "w"))
            call_command("donnees_essai", "--reinitialiser", stdout=open("/dev/null", "w"))
        self.assertEqual(Client.objects.filter(entreprise__slug="essai").count(), 10)
        self.assertTrue(Client.objects.filter(nom="Garder").exists())
        self.assertFalse(Adresse.objects.filter(entreprise__slug="essai").exclude(ville="Sainte-Adèle").exists())


class EffacementLoi25Tests(TestCase):
    """Demande de suppression (K5) : coordonnées et contenus effacés, factures émises gardées."""

    @classmethod
    def setUpTestData(cls):
        from decimal import Decimal
        from communications.models import ArchiveCourriel, Message
        from demandes.models import Demande
        from facturation.models import Facture
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai-eff", domaine="eff.exemple.test")
        cls.avec = Client.objects.create(entreprise=cls.ent, prenom="Ginette", nom="Tremblay", cellulaire="+15145550123",
                                         courriel="g@example.com", notes="Chien méchant")
        a = Adresse.objects.create(entreprise=cls.ent, client=cls.avec, ligne1="120, rue des Essais", ville="Sainte-Adèle", consignes="Code 1234")
        f = Facture.objects.create(entreprise=cls.ent, client=cls.avec, adresse=a)
        f.lignes.create(description="Déneigement", quantite=1, prix_unitaire=Decimal("100.00"), taxable=False)
        f.recalculer()
        f.emettre()
        Facture.objects.create(entreprise=cls.ent, client=cls.avec)  # brouillon
        m = Message.objects.create(entreprise=cls.ent, client=cls.avec, genre="recu", canal="courriel", sens="entrant",
                                   expediteur="g@example.com", sujet="Allo", contenu="Mon code est 1234", statut="recu")
        ArchiveCourriel.objects.create(entreprise=cls.ent, dossier="INBOX", uidvalidite=1, uid=1, taille=3, empreinte="x", brut=b"abc", message=m)
        Demande.objects.create(entreprise=cls.ent, client=cls.avec, description="Plainte détaillée", contact="Voisin")
        cls.sans = Client.objects.create(entreprise=cls.ent, prenom="Paul", nom="Sansfacture", cellulaire="+15145550124")
        Adresse.objects.create(entreprise=cls.ent, client=cls.sans, ligne1="1, rue Privée", ville="Sainte-Adèle")

    def test_avec_factures_le_nom_reste(self):
        from clients.effacement import EFFACE, effacer
        from communications.models import ArchiveCourriel
        b = effacer(self.avec)
        c = Client.objects.get(pk=self.avec.pk)
        self.assertEqual((c.cellulaire, c.courriel, c.notes, c.nom, c.statut), ("", "", "", "Tremblay", "inactif"))
        self.assertIsNotNone(c.efface_le)
        a = c.adresses.get()
        self.assertEqual((a.ligne1, a.consignes, a.active), ("120, rue des Essais", "", False))
        self.assertEqual(c.factures.count(), 1)  # brouillon supprimé, facture émise gardée
        self.assertEqual(c.messages.get().contenu, EFFACE)
        self.assertEqual(c.messages.get().expediteur, "")
        self.assertFalse(ArchiveCourriel.objects.exists())
        self.assertEqual(c.demandes.get().contact, "")
        self.assertTrue(b["factures_gardees"])

    def test_sans_facture_tout_part(self):
        from clients.effacement import effacer
        effacer(self.sans)
        c = Client.objects.get(pk=self.sans.pk)
        self.assertEqual((c.prenom, c.nom, c.cellulaire), ("", "Client effacé", ""))
        self.assertEqual(c.adresses.get().ligne1, "Adresse effacée")

    def test_action_admin_demande_confirmation(self):
        from django.contrib.auth import get_user_model
        from django.test import override_settings
        jf = get_user_model().objects.create_superuser("jf", password="x" * 12)
        self.client.force_login(jf)
        donnees = {"action": "effacer_a_la_demande", "_selected_action": [self.sans.pk]}
        with override_settings(ALLOWED_HOSTS=["*"]):
            r = self.client.post("/admin/clients/client/", donnees)
            self.assertContains(r, "Irréversible")
            self.assertIsNone(Client.objects.get(pk=self.sans.pk).efface_le)
            self.client.post("/admin/clients/client/", {**donnees, "confirmer": "oui"})
        self.assertIsNotNone(Client.objects.get(pk=self.sans.pk).efface_le)


class PhotoEntreeTests(TestCase):
    """Photo de l'entrée (A5) : gardée dans la base, servie aux membres, type vérifié par les octets."""
    JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from core.models import Membre
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai-ph", domaine="ph.exemple.test")
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre-ph", domaine="autre-ph.exemple.test")
        cls.c = Client.objects.create(entreprise=cls.ent, nom="Tremblay")
        cls.a = Adresse.objects.create(entreprise=cls.ent, client=cls.c, ligne1="120, rue des Essais", ville="Sainte-Adèle")
        U = get_user_model()
        cls.louis = U.objects.create_user("louis-ph", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")

    def envoyer(self, contenu, nom="entree.jpg"):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings
        with override_settings(ALLOWED_HOSTS=["*"]):
            return self.client.post(f"/adresses/{self.a.pk}/photos/", {"photo": SimpleUploadedFile(nom, contenu)}, HTTP_HOST="ph.exemple.test")

    def test_ajout_affichage_et_retrait(self):
        from django.test import override_settings
        from clients.models import PhotoAdresse
        self.client.force_login(self.louis)
        self.envoyer(self.JPEG)
        p = PhotoAdresse.objects.get()
        self.assertEqual((p.type_mime, p.taille, p.entreprise_id), ("image/jpeg", len(self.JPEG), self.ent.pk))
        with override_settings(ALLOWED_HOSTS=["*"]):
            r = self.client.get(f"/photos/{p.pk}/", HTTP_HOST="ph.exemple.test")
            self.assertEqual((r.status_code, r["Content-Type"], r.content), (200, "image/jpeg", self.JPEG))
            self.assertContains(self.client.get(f"/clients/{self.c.pk}/", HTTP_HOST="ph.exemple.test"), f"/photos/{p.pk}/")
            self.assertEqual(self.client.get(f"/photos/{p.pk}/", HTTP_HOST="autre-ph.exemple.test").status_code, 403)  # pas membre de cette entreprise
            self.client.logout()
            self.assertEqual(self.client.get(f"/photos/{p.pk}/", HTTP_HOST="ph.exemple.test").status_code, 302)
            self.client.force_login(self.louis)
            self.client.post(f"/photos/{p.pk}/retirer/", HTTP_HOST="ph.exemple.test")
        self.assertFalse(PhotoAdresse.objects.exists())

    def test_fichier_qui_nest_pas_une_photo(self):
        from clients.models import PhotoAdresse
        self.client.force_login(self.louis)
        self.envoyer(b"<html>pas une photo</html>", nom="photo.jpg")
        self.assertFalse(PhotoAdresse.objects.exists())

    def test_effacement_loi25_retire_les_photos(self):
        from clients.effacement import effacer
        from clients.models import PhotoAdresse
        PhotoAdresse.objects.create(entreprise=self.ent, adresse=self.a, image=self.JPEG, type_mime="image/jpeg", taille=10)
        effacer(self.c)
        self.assertFalse(PhotoAdresse.objects.exists())
