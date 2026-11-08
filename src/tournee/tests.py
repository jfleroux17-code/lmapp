from datetime import date
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings

from clients.models import Adresse, Client, Secteur
from core.models import Entreprise, Membre
from facturation.models import Contrat, Facture, Saison
from tournee import services
from tournee.models import Operation, Passage, arrets

HOTE = "louis.exemple.test"


class TourneeBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE, inscrit_taxes=True)
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.exemple.test")
        village = Secteur.objects.create(entreprise=cls.ent, nom="Village", ordre=1)
        mont = Secteur.objects.create(entreprise=cls.ent, nom="Mont", ordre=2)

        def arret(nom, secteur, rang, statut="actif"):
            c = Client.objects.create(entreprise=cls.ent, nom=nom, statut=statut)
            return Adresse.objects.create(entreprise=cls.ent, client=c, secteur=secteur, ordre_tournee=rang, ligne1=f"{rang}, rue {nom}", ville="Sainte-Adèle")

        cls.a_mont = arret("Pelletier", mont, 1)
        cls.a2 = arret("Côté", village, 2, statut="recouvrement")
        cls.a1 = arret("Tremblay", village, 1)
        cls.a_sans_rang = arret("Roy", None, None)
        arret("Inactif", village, 3, statut="inactif")
        arret("Noir", village, 4, statut="liste_noire")
        cls.saison = Saison.objects.create(entreprise=cls.ent, nom="2026-2027", debut=date(2026, 11, 1), fin=date(2027, 4, 30))


class ModeleTests(TourneeBase):
    def test_ordre_de_la_tournee(self):
        self.assertEqual(list(arrets(self.ent)), [self.a1, self.a2, self.a_mont, self.a_sans_rang])

    def test_une_seule_operation_en_cours(self):
        op = Operation.objects.create(entreprise=self.ent)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Operation.objects.create(entreprise=self.ent)
        op.terminer()
        Operation.objects.create(entreprise=self.ent)  # après la fin : permis
        Operation.objects.create(entreprise=self.autre)  # autre entreprise : indépendante

    def test_retaper_corrige_le_passage(self):
        op = Operation.objects.create(entreprise=self.ent)
        services.marquer(op, self.a1, "fait")
        p = services.marquer(op, self.a1, "saute", raison="auto")
        self.assertEqual(Passage.objects.count(), 1)
        self.assertEqual((p.statut, p.raison), ("saute", "auto"))
        with self.assertRaises(ValidationError):
            services.marquer(op, self.a2, "saute")  # sauté sans raison

    def test_facturation_au_passage(self):
        c = Contrat.objects.create(entreprise=self.ent, client=self.a1.client, adresse=self.a1, saison=self.saison,
                                   type="au_passage", prix=D("45"))
        for jour in (5, 12):
            op = Operation.objects.create(entreprise=self.ent)
            from django.utils import timezone
            from datetime import datetime
            quand = timezone.make_aware(datetime(2026, 12, jour, 4, 30))
            p = services.marquer(op, self.a1, "fait", quand=quand)
            services.marquer(op, self.a2, "fait", quand=quand)  # pas de contrat au passage : rien
            op.terminer()
        f = Facture.objects.get(contrat=c)
        self.assertEqual(f.statut, "brouillon")
        self.assertEqual([l.description for l in f.lignes.all()], ["Passage du 5 décembre (neige)", "Passage du 12 décembre (neige)"])
        self.assertEqual(f.total, D("103.48"))  # 90 $ + taxes
        self.assertEqual(Facture.objects.count(), 1)
        # Corrigé en « sauté » : la ligne est retirée de la facture
        services.marquer(p.operation, self.a1, "saute", raison="auto")
        f.refresh_from_db()
        self.assertEqual((f.lignes.count(), f.sous_total), (1, D("45.00")))
        # Facture émise : le passage suivant ouvre une nouvelle facture
        f.emettre()
        op = Operation.objects.create(entreprise=self.ent)
        services.marquer(op, self.a1, "fait", quand=timezone.make_aware(datetime(2026, 12, 20, 5, 0)))
        self.assertEqual(Facture.objects.filter(contrat=c).count(), 2)

    def test_contrat_d_une_autre_saison_ou_saisonnier_pas_facture(self):
        Contrat.objects.create(entreprise=self.ent, client=self.a1.client, adresse=self.a1, saison=self.saison, type="saisonnier", prix=D("450"))
        op = Operation.objects.create(entreprise=self.ent)
        services.marquer(op, self.a1, "fait")
        self.assertFalse(Facture.objects.exists())


@override_settings(ALLOWED_HOSTS=["*"])
class EcransTests(TourneeBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        U = get_user_model()
        cls.louis = U.objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")
        cls.lecteur = U.objects.create_user("lecteur", password="x" * 12)
        Membre.objects.create(utilisateur=cls.lecteur, entreprise=cls.ent, role="lecture")

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)

    def test_une_operation_complete(self):
        self.assertContains(self.client.get("/tournee/"), "Démarrer : Neige")
        r = self.client.post("/tournee/demarrer/", {"type": "neige"}, follow=True)
        self.assertContains(r, "Opération « Neige » commencée.")
        self.assertEqual(r.context["courant"], self.a1)  # premier arrêt
        r = self.client.post(f"/tournee/passages/{self.a1.pk}/", {"statut": "fait", "note": "Boîte aux lettres croche"}, follow=True)
        self.assertContains(r, "Tremblay, 1, rue Tremblay : fait.")
        self.assertEqual(r.context["courant"], self.a2)  # le suivant
        r = self.client.post(f"/tournee/passages/{self.a2.pk}/", {"statut": "saute", "raison": "non_paye"}, follow=True)
        self.assertEqual(r.context["courant"], self.a_mont)
        self.assertEqual((r.context["faits"], r.context["sautes"], r.context["total"]), (1, 1, 4))
        # Choisir un arrêt hors de l'ordre
        self.assertEqual(self.client.get(f"/tournee/?arret={self.a_sans_rang.pk}").context["courant"], self.a_sans_rang)
        r = self.client.post("/tournee/terminer/", follow=True)
        self.assertContains(r, "Opération terminée : 1 fait, 1 sauté, 2 pas visités.")
        self.assertIsNotNone(Operation.objects.get().fin)
        # Historique dans la fiche (F5, F8)
        fiche = self.client.get(f"/clients/{self.a1.client.pk}/")
        self.assertContains(fiche, "Boîte aux lettres croche")
        self.assertContains(self.client.get(f"/clients/{self.a2.client.pk}/"), "Sauté : compte non payé")

    def test_saute_sans_raison_refuse_et_pas_d_operation(self):
        self.client.post(f"/tournee/passages/{self.a1.pk}/", {"statut": "fait"})
        self.assertFalse(Passage.objects.exists())  # aucune opération en cours
        self.client.post("/tournee/demarrer/", {"type": "neige"})
        self.client.post(f"/tournee/passages/{self.a1.pk}/", {"statut": "saute"})
        self.assertFalse(Passage.objects.exists())

    def test_double_demarrage(self):
        self.client.post("/tournee/demarrer/", {"type": "neige"})
        r = self.client.post("/tournee/demarrer/", {"type": "verglas"}, follow=True)
        self.assertContains(r, "déjà en cours")
        self.assertEqual(Operation.objects.count(), 1)

    def test_lecture_seule_et_autre_entreprise(self):
        self.client.post("/tournee/demarrer/", {"type": "neige"})
        etrangere = Adresse.objects.create(entreprise=self.autre, client=Client.objects.create(entreprise=self.autre, nom="X"),
                                           ligne1="1, rue X", ville="Ailleurs")
        self.assertEqual(self.client.post(f"/tournee/passages/{etrangere.pk}/", {"statut": "fait"}).status_code, 404)
        self.client.force_login(self.lecteur)
        page = self.client.get("/tournee/")
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, "Terminer l'opération")
        self.assertEqual(self.client.post(f"/tournee/passages/{self.a1.pk}/", {"statut": "fait"}).status_code, 403)
