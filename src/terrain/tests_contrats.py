"""Contrats et soldes antérieurs dans la fiche du client (sans l'administration)."""
from datetime import date
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from clients.models import Adresse, Client
from core.models import Entreprise, Membre
from facturation.models import Contrat, Facture, Saison, Service

HOTE = "louis.exemple.test"


@override_settings(ALLOWED_HOSTS=["*"])
class ContratsFicheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE, inscrit_taxes=True,
                                            versements_par_defaut=2, dates_versements="15/01")
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.exemple.test")
        cls.louis = U.objects.create_user("louis", password="mot-de-passe-solide-123")
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="admin")
        cls.lecteur = U.objects.create_user("lecteur", password="mot-de-passe-solide-123")
        Membre.objects.create(utilisateur=cls.lecteur, entreprise=cls.ent, role="lecture")
        cls.saison = Saison.objects.create(entreprise=cls.ent, nom="2026-2027", debut=date(2026, 11, 1), fin=date(2027, 4, 30))
        cls.entree = Service.objects.create(entreprise=cls.ent, nom="Entrée")
        cls.client_ = Client.objects.create(entreprise=cls.ent, nom="Tremblay")
        cls.adresse = Adresse.objects.create(entreprise=cls.ent, client=cls.client_, ligne1="1, rue A", ville="Sainte-Adèle")
        cls.etranger = Client.objects.create(entreprise=cls.autre, nom="Ailleurs")

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)

    def donnees(self, **kw):
        d = {"saison": self.saison.pk, "adresse": self.adresse.pk, "type": "saisonnier", "prix": "450,00",
             "versements": "2", "services": [self.entree.pk], "prix_texte": "", "notes": ""}
        d.update(kw)
        return d

    @mock.patch("django.utils.timezone.localdate", return_value=date(2026, 11, 10))
    def test_nouveau_contrat_avec_echeancier(self, _):
        url = f"/clients/{self.client_.pk}/contrats/nouveau/"
        self.assertContains(self.client.get(url), "Nouveau contrat")
        r = self.client.post(url, self.donnees())
        self.assertRedirects(r, f"/clients/{self.client_.pk}/?argent=1#argent", fetch_redirect_response=False)
        c = Contrat.objects.get(client=self.client_)
        self.assertEqual(c.prix, Decimal("450.00"))
        self.assertEqual(list(c.services.all()), [self.entree])
        self.assertEqual([(v.date_prevue, v.montant) for v in c.versements.all()],
                         [(date(2026, 11, 10), Decimal("225.00")), (date(2027, 1, 15), Decimal("225.00"))])
        fiche = self.client.get(f"/clients/{self.client_.pk}/")
        self.assertContains(fiche, f"/contrats/{c.pk}/modifier/")
        # Le même contrat deux fois : refusé
        self.assertContains(self.client.post(url, self.donnees()), "déjà un contrat")

    def test_deuxieme_adresse_creee_dans_le_contrat(self):
        url = f"/clients/{self.client_.pk}/contrats/nouveau/"
        self.client.post(url, self.donnees())
        page = self.client.get(url)
        self.assertContains(page, "+ Nouvelle adresse de service")
        self.assertContains(page, 'name="a-code_postal"')
        nouvelle = {"adresse": "nouvelle", "a-ligne1": "", "a-ville": "Sainte-Adèle"}
        r = self.client.post(url, self.donnees(**nouvelle))  # rue manquante : rien d'enregistré, la nouvelle adresse reste ouverte
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "adresse: 'nouvelle'")
        self.assertEqual((Contrat.objects.count(), self.client_.adresses.count()), (1, 1))
        nouvelle.update({"a-ligne1": "22, chemin du Lac", "a-ligne2": "app. 3", "a-code_postal": "j8b 1a1"})
        r = self.client.post(url, self.donnees(**nouvelle))
        self.assertEqual(r.status_code, 302)
        a = self.client_.adresses.get(ligne1="22, chemin du Lac")
        self.assertEqual((a.ligne2, a.code_postal), ("app. 3", "J8B 1A1"))
        self.assertEqual(Contrat.objects.get(adresse=a).saison, self.saison)
        self.assertEqual(Contrat.objects.filter(client=self.client_, saison=self.saison).count(), 2)

    def test_taxes_incluses_et_trop_de_versements(self):
        url = f"/clients/{self.client_.pk}/contrats/nouveau/"
        # 3 versements : une seule date dans les réglages, refusé avec la piste
        self.assertContains(self.client.post(url, self.donnees(versements="3")), "Réglages")
        self.client.post(url, self.donnees(prix="517,39", taxes_incluses="on", versements="1"))
        c = Contrat.objects.get(client=self.client_)
        self.assertEqual(c.prix, Decimal("450.00"))
        self.assertIn("taxes incluses", c.prix_texte)

    def test_modifier_puis_fige_apres_facture(self):
        c = Contrat.objects.create(entreprise=self.ent, client=self.client_, adresse=self.adresse, saison=self.saison, prix=400)
        c.creer_echeancier_par_defaut(2)
        self.client.post(f"/contrats/{c.pk}/modifier/", self.donnees(prix="500", versements="1"))
        c.refresh_from_db()
        self.assertEqual((c.prix, c.versements.count()), (Decimal("500.00"), 1))
        c.versements.first().facturer()
        r = self.client.post(f"/contrats/{c.pk}/modifier/", self.donnees(prix="1"))
        c.refresh_from_db()
        self.assertEqual(c.prix, Decimal("500.00"))
        self.client.post(f"/contrats/{c.pk}/supprimer/")
        self.assertTrue(Contrat.objects.filter(pk=c.pk).exists())
        self.assertNotContains(self.client.get(f"/clients/{self.client_.pk}/"), f"/contrats/{c.pk}/modifier/")

    def test_supprimer_sans_facture(self):
        c = Contrat.objects.create(entreprise=self.ent, client=self.client_, saison=self.saison, prix=400)
        c.creer_echeancier_par_defaut(2)
        self.client.post(f"/contrats/{c.pk}/supprimer/")
        self.assertFalse(Contrat.objects.filter(pk=c.pk).exists())

    def test_solde_anterieur(self):
        r = self.client.post(f"/clients/{self.client_.pk}/solde-anterieur/", {"montant": "120,50", "saison": "2025-2026", "note": ""})
        self.assertEqual(r.status_code, 302)
        f = Facture.objects.get(client=self.client_)
        self.assertEqual((f.genre, f.total, f.statut), (Facture.Genre.SOLDE_OUVERTURE, Decimal("120.50"), Facture.Statut.EMISE))

    def test_droits_et_entreprise(self):
        self.assertEqual(self.client.get(f"/clients/{self.etranger.pk}/contrats/nouveau/").status_code, 404)
        self.assertEqual(self.client.post(f"/clients/{self.etranger.pk}/solde-anterieur/", {"montant": "5"}).status_code, 404)
        self.client.force_login(self.lecteur)
        self.assertEqual(self.client.post(f"/clients/{self.client_.pk}/contrats/nouveau/", self.donnees()).status_code, 403)
        self.assertEqual(self.client.post(f"/clients/{self.client_.pk}/solde-anterieur/", {"montant": "5"}).status_code, 403)
        self.assertFalse(Contrat.objects.exists())
