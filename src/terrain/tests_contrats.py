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
        c = Contrat.objects.get(client=self.client_)
        f = c.factures.get()  # la facture de la saison, prête en brouillon : on y va pour l'émettre et l'envoyer
        self.assertRedirects(r, f"/factures/{f.pk}/", fetch_redirect_response=False)
        self.assertEqual((f.statut, f.sous_total, f.versements.count()), ("brouillon", Decimal("450.00"), 2))
        self.assertEqual(c.prix, Decimal("450.00"))
        self.assertEqual(list(c.services.all()), [self.entree])
        self.assertEqual([(v.date_prevue, v.montant) for v in c.versements.all()],
                         [(date(2026, 11, 10), Decimal("225.00")), (date(2027, 1, 15), Decimal("225.00"))])
        fiche = self.client.get(f"/clients/{self.client_.pk}/")
        self.assertContains(fiche, f"/contrats/{c.pk}/modifier/")
        # Le même contrat deux fois : refusé
        self.assertContains(self.client.post(url, self.donnees()), "déjà un contrat")

    @mock.patch("django.utils.timezone.localdate", return_value=date(2026, 11, 10))
    def test_contrat_avec_facture_envoyee_plus_tard(self, _):
        url = f"/clients/{self.client_.pk}/contrats/nouveau/"
        self.assertContains(self.client.get(url), 'name="envoyer_le"')
        self.assertContains(self.client.post(url, self.donnees(envoyer_le="2026-11-01")), "plus tard")  # pas dans le passé
        r = self.client.post(url, self.donnees(envoyer_le="2026-12-01"))
        self.assertRedirects(r, f"/clients/{self.client_.pk}/?argent=1#argent", fetch_redirect_response=False)
        c = Contrat.objects.get(client=self.client_)
        f = c.factures.get()
        self.assertEqual((f.statut, f.envoyer_le), ("brouillon", date(2026, 12, 1)))
        self.assertEqual(c.versements.get(rang=1).date_prevue, date(2026, 12, 1))
        # Modifier le contrat : la date prévue est reprise; remise à aujourd'hui, la facture redevient à envoyer tout de suite
        self.assertContains(self.client.get(f"/contrats/{c.pk}/modifier/"), 'value="2026-12-01"')
        self.client.post(f"/contrats/{c.pk}/modifier/", self.donnees(envoyer_le="2026-11-10"))
        self.assertIsNone(c.factures.get().envoyer_le)

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
        # Facture encore en brouillon : le contrat se modifie, la facture suit
        self.client.post(f"/contrats/{c.pk}/modifier/", self.donnees(prix="500", versements="1"))
        self.assertEqual(c.factures.get().sous_total, Decimal("500.00"))
        c.factures.get().emettre()
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


@override_settings(ALLOWED_HOSTS=["*"])
class NouveauClientEnUnPassageTests(TestCase):
    """Lot E : client, contrat de la saison, échéancier et facture en un seul passage; émettre et envoyer d'une tape."""

    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE, inscrit_taxes=True, ville="Sainte-Adèle",
                                            versements_par_defaut=2, dates_versements="15/01", prochain_numero_facture=700,
                                            courriel_reponse="louis@exemple.test")
        cls.louis = U.objects.create_user("louis", password="mot-de-passe-solide-123")
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="admin")
        cls.saison = Saison.objects.create(entreprise=cls.ent, nom="2026-2027", debut=date(2026, 11, 1), fin=date(2027, 4, 30))
        cls.entree = Service.objects.create(entreprise=cls.ent, nom="Entrée", prix_suggere=Decimal("450"))
        cls.abrasif = Service.objects.create(entreprise=cls.ent, nom="Abrasif", prix_suggere=Decimal("50"))

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)

    def donnees(self, **kw):
        d = {"c-prenom": "Marc", "c-nom": "Dubé", "c-cellulaire": "450 555-0198", "c-courriel": "marc@example.com", "c-canal_prefere": "courriel",
             "c-mode_paiement": "interac", "c-statut": "actif", "c-avis_operations": "on",
             "a-ligne1": "10, rue des Essais", "a-ville": "Sainte-Adèle", "a-code_postal": "J8B 1A1",
             "k-actif": "1", "k-service": [self.entree.pk, self.abrasif.pk], f"k-prix-{self.entree.pk}": "480",
             f"k-prix-{self.abrasif.pk}": "60", "k-versements": "2"}
        d.update(kw)
        return d

    @mock.patch("django.utils.timezone.localdate", return_value=date(2026, 11, 13))
    def test_client_contrat_et_facture_puis_emettre_et_envoyer(self, _):
        page = self.client.get("/clients/nouveau/")
        self.assertContains(page, "Contrat de la saison 2026-2027")
        self.assertContains(page, 'name="k-prix-')
        r = self.client.post("/clients/nouveau/", self.donnees())
        c = Contrat.objects.get(client__nom="Dubé")
        f = c.factures.get()
        self.assertRedirects(r, f"/factures/{f.pk}/", fetch_redirect_response=False)
        self.assertEqual((c.prix, sorted(c.services.values_list("nom", flat=True)), c.versements.count()), (Decimal("540.00"), ["Abrasif", "Entrée"], 2))
        self.assertEqual(c.prix_texte, "Abrasif 60,00 $ + Entrée 480,00 $ plus taxes, en 2 versements")  # ordre du catalogue
        self.assertEqual((f.statut, f.sous_total), ("brouillon", Decimal("540.00")))
        page = self.client.get(f"/factures/{f.pk}/")
        self.assertContains(page, "Émettre et envoyer par courriel")
        r = self.client.post(f"/factures/{f.pk}/emettre/", {"envoyer": "1"}, follow=True)
        f.refresh_from_db()
        self.assertEqual((f.statut, f.numero), ("emise", 700))
        self.assertEqual(f.messages.get().destinataire, "marc@example.com")
        self.assertContains(self.client.get(f"/clients/{c.client_id}/"), "Prix : ")

    def test_erreur_dans_le_contrat_rien_n_est_cree(self):
        r = self.client.post("/clients/nouveau/", self.donnees(**{"k-service": []}))
        self.assertContains(r, "cocher au moins un service")
        self.assertFalse(Client.objects.filter(nom="Dubé").exists())
        r = self.client.post("/clients/nouveau/", self.donnees(**{"k-actif": ""}))  # sans contrat : le client seul
        self.assertRedirects(r, f"/clients/{Client.objects.get(nom='Dubé').pk}/", fetch_redirect_response=False)
        self.assertFalse(Contrat.objects.exists())


    @mock.patch("django.utils.timezone.localdate", return_value=date(2026, 7, 10))
    def test_client_inscrit_en_ete_facture_envoyee_plus_tard(self, _):
        from facturation.models import Facture
        from unittest import mock as m
        r = self.client.post("/clients/nouveau/", self.donnees(**{"k-envoi": "2026-11-01"}))
        c = Contrat.objects.get(client__nom="Dubé")
        f = c.factures.get()
        self.assertRedirects(r, f"/clients/{c.client_id}/", fetch_redirect_response=False)
        self.assertEqual((f.statut, f.envoyer_le), ("brouillon", date(2026, 11, 1)))
        self.assertEqual(c.versements.order_by("rang").first().date_prevue, date(2026, 11, 1))  # 1er versement à l'envoi
        self.assertContains(self.client.get(f"/clients/{c.client_id}/"), "À envoyer le")  # (affiche aussi le message de confirmation)
        self.assertNotContains(self.client.get("/factures/versements/"), "Dubé")  # pas encore proposée
        # Le jour venu : proposée, puis datée du jour de l'émission
        with m.patch("django.utils.timezone.localdate", return_value=date(2026, 11, 1)):
            self.assertContains(self.client.get("/factures/versements/"), "Dubé")
            f.emettre()
        f.refresh_from_db()
        self.assertEqual(f.date_facture, date(2026, 11, 1))
        r = self.client.post("/clients/nouveau/", self.donnees(**{"c-nom": "Autre", "c-cellulaire": "", "k-envoi": "2026-07-01"}))
        self.assertContains(r, "ou plus tard")  # apostrophe échappée dans la page
