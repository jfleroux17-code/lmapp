"""Dépenses par photo (PRD S1, S2) : saisie au cellulaire, taxes tirées du total, rapport et export."""
from datetime import date, timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Entreprise, Membre
from facturation import depenses, rapports
from facturation.models import Depense, Saison

HOTE = "essai.exemple.test"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200


@override_settings(ALLOWED_HOSTS=["*"])
class DepensesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE, inscrit_taxes=True)
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.exemple.test")
        cls.louis = U.objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")
        cls.comptable = U.objects.create_user("comptable", password="x" * 12)
        Membre.objects.create(utilisateur=cls.comptable, entreprise=cls.ent, role="lecture")
        cls.saison = Saison.objects.create(entreprise=cls.ent, nom="2026-2027", debut=date(2020, 11, 1), fin=date(2099, 4, 30))

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)

    def test_taxes_tirees_du_total(self):
        self.assertEqual(depenses.taxes_du_total(D("114.98"), self.ent), (D("5.00"), D("9.98")))
        self.ent.inscrit_taxes = False
        self.assertEqual(depenses.taxes_du_total(D("114.98"), self.ent), (D("0"), D("0")))

    def test_photo_du_recu_au_cellulaire(self):
        r = self.client.post("/depenses/nouvelle/", {"total": "87,45 $", "categorie": "carburant", "fournisseur": "Ultramar",
                                                      "photo": SimpleUploadedFile("recu.jpg", JPEG, "image/jpeg")})
        self.assertRedirects(r, "/depenses/")
        d = Depense.objects.get()
        self.assertEqual((d.total, d.tps, d.tvq, d.categorie, d.photo_type, d.saisie_par), (D("87.45"), D("3.80"), D("7.59"), "carburant", "image/jpeg", self.louis))
        self.assertEqual(self.client.get(f"/depenses/{d.pk}/photo/").content, JPEG)
        page = self.client.get("/depenses/")
        self.assertContains(page, "Essence et carburant")
        self.assertContains(page, "11,39")  # taxes payées : 3,80 + 7,59 (pas arrondies à l'entier)

    def test_taxes_tapees_ou_a_zero(self):
        self.client.post("/depenses/nouvelle/", {"total": "1200", "categorie": "vehicule", "tps": "0", "tvq": "0"})
        self.assertEqual((Depense.objects.get().tps, Depense.objects.get().tvq), (D("0"), D("0")))  # assurance : pas de taxes

    def test_refus(self):
        demain = (timezone.localdate() + timedelta(days=1)).isoformat()
        self.client.post("/depenses/nouvelle/", {"total": "", "categorie": "carburant"})
        self.client.post("/depenses/nouvelle/", {"total": "50", "date": demain})
        self.client.post("/depenses/nouvelle/", {"total": "50", "photo": SimpleUploadedFile("x.jpg", b"pas une image", "image/jpeg")})
        self.client.post("/depenses/nouvelle/", {"total": "10", "tps": "5", "tvq": "6"})
        self.assertFalse(Depense.objects.exists())

    def test_corriger_supprimer_et_autre_entreprise(self):
        d = Depense.objects.create(entreprise=self.ent, total=D("50"), categorie="pieces")
        self.client.post(f"/depenses/{d.pk}/", {"total": "60", "categorie": "reparation", "tps": "2,61", "tvq": "5,20"})
        d.refresh_from_db()
        self.assertEqual((d.total, d.categorie, d.tps), (D("60.00"), "reparation", D("2.61")))
        e = Depense.objects.create(entreprise=self.autre, total=D("10"))
        self.assertEqual(self.client.get(f"/depenses/{e.pk}/").status_code, 404)
        self.client.post(f"/depenses/{d.pk}/supprimer/")
        self.assertFalse(Depense.objects.filter(pk=d.pk).exists())

    def test_lecture_seule_voit_sans_modifier(self):
        d = Depense.objects.create(entreprise=self.ent, total=D("50"))
        self.client.force_login(self.comptable)
        self.assertEqual(self.client.get(f"/depenses/{d.pk}/").status_code, 200)
        self.assertNotEqual(self.client.post("/depenses/nouvelle/", {"total": "1"}).status_code, 302)
        self.client.post(f"/depenses/{d.pk}/supprimer/")
        self.assertTrue(Depense.objects.filter(pk=d.pk).exists())

    def test_rapport_et_export(self):
        jour = timezone.localdate()
        Depense.objects.create(entreprise=self.ent, date=jour, total=D("114.98"), tps=D("5.00"), tvq=D("9.98"), categorie="carburant")
        Depense.objects.create(entreprise=self.ent, date=jour, total=D("100.00"), categorie="vehicule")
        b = rapports.saison(self.ent, self.saison)["depenses"]
        self.assertEqual((b["nombre"], b["total"], b["tps"], b["avant_taxes"]), (2, D("214.98"), D("5.00"), D("200.00")))
        self.assertEqual(b["par_categorie"][0]["categorie"], "Essence et carburant")
        self.assertContains(self.client.get("/comptes/rapport/"), "Dépenses de la saison")
        r = self.client.get("/comptes/export/", {"quoi": "depenses"})
        texte = r.content.decode("utf-8-sig")
        self.assertIn("Essence et carburant", texte)
        self.assertIn("100,00", texte)
