"""Gabarits par défaut de la plateforme (console de JF) et copies des entreprises (messages types)."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from communications.models import GABARITS_PAR_DEFAUT, Gabarit, GabaritParDefaut
from core.models import Entreprise, Membre

HOTE = "louis.exemple.test"


@override_settings(ALLOWED_HOSTS=["*"])
class GabaritsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE, signature_messages="Déneigement Essai")
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.exemple.test")
        cls.louis = U.objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")
        cls.lecteur = U.objects.create_user("lecteur", password="x" * 12)
        Membre.objects.create(utilisateur=cls.lecteur, entreprise=cls.ent, role="lecture")
        cls.jf = U.objects.create_superuser("jf", password="x" * 12)

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE

    def test_migration_a_rempli_les_textes_par_defaut(self):
        self.assertEqual(set(GabaritParDefaut.objects.values_list("genre", flat=True)), {str(g) for g in GABARITS_PAR_DEFAUT})
        for g in GabaritParDefaut.objects.all():
            self.assertEqual(g.texte, GABARITS_PAR_DEFAUT[g.genre])

    def test_texte_copie_puis_defaut_de_la_base_pour_toutes_les_entreprises(self):
        GabaritParDefaut.objects.filter(genre="proximite").update(texte="On arrive au {adresse} dans {minutes} min.")
        self.assertEqual(Gabarit.texte_pour(self.ent, "proximite"), "On arrive au {adresse} dans {minutes} min.")
        self.assertEqual(Gabarit.texte_pour(self.autre, "proximite"), "On arrive au {adresse} dans {minutes} min.")
        Gabarit.objects.create(entreprise=self.ent, genre="proximite", texte="Louis arrive dans {minutes} min.")
        self.assertEqual(Gabarit.texte_pour(self.ent, "proximite"), "Louis arrive dans {minutes} min.")
        self.assertEqual(Gabarit.texte_pour(self.autre, "proximite"), "On arrive au {adresse} dans {minutes} min.")
        GabaritParDefaut.objects.filter(genre="proximite").delete()
        self.assertEqual(Gabarit.texte_pour(self.autre, "proximite"), GABARITS_PAR_DEFAUT["proximite"])

    def test_cloner_modifier_revenir(self):
        self.client.force_login(self.louis)
        r = self.client.get("/messages/gabarits/")
        self.assertContains(r, "Texte par défaut (lecture seule")
        self.assertContains(r, "Cloner pour le modifier")
        r = self.client.post("/messages/gabarits/proximite/cloner/")
        self.assertRedirects(r, "/messages/gabarits/proximite/", fetch_redirect_response=False)
        copie = Gabarit.objects.get(entreprise=self.ent, genre="proximite")
        self.assertEqual(copie.texte, GabaritParDefaut.texte_de("proximite"))
        r = self.client.post("/messages/gabarits/proximite/", {"texte": "On arrive chez {client}."})
        self.assertContains(r, "Variables inconnues : client. Permises : {adresse}, {minutes}.")
        r = self.client.post("/messages/gabarits/proximite/", {"texte": "On arrive au {adresse dans 5 min."})
        self.assertContains(r, "Variables inconnues : accolades.")
        self.client.post("/messages/gabarits/proximite/", {"texte": "Louis arrive au {adresse} dans {minutes} minutes."})
        copie.refresh_from_db()
        self.assertEqual(copie.texte, "Louis arrive au {adresse} dans {minutes} minutes.")
        self.assertContains(self.client.get("/messages/gabarits/"), "Votre version (c'est elle qui part)")
        self.assertEqual(GabaritParDefaut.objects.get(genre="proximite").texte, GABARITS_PAR_DEFAUT["proximite"])  # défaut intact
        self.client.post("/messages/gabarits/proximite/retirer/")
        self.assertFalse(Gabarit.objects.filter(entreprise=self.ent).exists())

    def test_defaut_change_depuis_la_copie(self):
        self.client.force_login(self.louis)
        self.client.post("/messages/gabarits/debut/cloner/")
        d = GabaritParDefaut.objects.get(genre="debut")
        d.texte = "Nouveau texte de JF."
        d.save()
        self.assertContains(self.client.get("/messages/gabarits/"), "Le texte par défaut a changé")

    def test_lecture_seule_voit_sans_modifier(self):
        self.client.force_login(self.lecteur)
        r = self.client.get("/messages/gabarits/")
        self.assertContains(r, "Texte par défaut (lecture seule")
        self.assertNotContains(r, "Cloner pour le modifier")
        self.assertEqual(self.client.post("/messages/gabarits/debut/cloner/").status_code, 403)
        self.assertFalse(Gabarit.objects.exists())

    def test_equipe_seuls_les_administrateurs_modifient(self):
        Entreprise.objects.filter(pk=self.ent.pk).update(mode="equipe")
        self.client.force_login(self.louis)  # opérateur
        self.assertNotContains(self.client.get("/messages/gabarits/"), "Cloner pour le modifier")
        self.assertEqual(self.client.post("/messages/gabarits/debut/cloner/").status_code, 403)

    def test_copie_d_une_autre_entreprise_invisible(self):
        Gabarit.objects.create(entreprise=self.autre, genre="debut", texte="Texte secret de l'autre.")
        self.client.force_login(self.louis)
        self.assertNotContains(self.client.get("/messages/gabarits/"), "Texte secret")

    def test_genre_inconnu(self):
        self.client.force_login(self.louis)
        self.assertEqual(self.client.post("/messages/gabarits/facture/cloner/").status_code, 404)

    def test_console_de_jf(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.jf)
        g = GabaritParDefaut.objects.get(genre="relance_1")
        r = self.client.get(f"/admin/communications/gabaritpardefaut/{g.pk}/change/")
        self.assertContains(r, "{client}, {montant}, {factures}, {depuis}, {paiement}")
        self.assertContains(r, "aucune : toutes utilisent ce texte")
        self.assertNotContains(r, "/delete/")
        r = self.client.post(f"/admin/communications/gabaritpardefaut/{g.pk}/change/", {"texte": "Rappel {inconnue}"})
        self.assertContains(r, "Variables inconnues : inconnue.")
        self.client.post(f"/admin/communications/gabaritpardefaut/{g.pk}/change/", {"texte": "Rappel : {montant}. {paiement}"})
        self.assertEqual(Gabarit.texte_pour(self.autre, "relance_1"), "Rappel : {montant}. {paiement}")

    def test_console_refusee_a_un_membre_du_personnel(self):
        u = get_user_model().objects.create_user("employe", password="x" * 12, is_staff=True)
        self.client.force_login(u)
        self.assertEqual(self.client.get("/admin/communications/gabaritpardefaut/").status_code, 403)
