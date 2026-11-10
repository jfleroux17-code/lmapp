"""Réglages du déneigeur dans l'app (Plus, « Réglages »), décision de JF du 10 novembre 2026."""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from clients.models import Adresse, Client, Secteur
from communications.models import Message
from core.models import Entreprise, Membre, VilleDesservie
from facturation.models import Service

HOTE = "louis.exemple.test"


@override_settings(ALLOWED_HOSTS=["*"])
class ReglagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.ent = Entreprise.objects.create(nom="Déneigement Essai", slug="essai", domaine=HOTE, inscrit_taxes=True,
                                            numero_tps="123456789 RT0001")
        cls.autre = Entreprise.objects.create(nom="Autre", slug="autre", domaine="autre.exemple.test")
        cls.patron = U.objects.create_user("patron", password="mot-de-passe-solide-123")
        Membre.objects.create(utilisateur=cls.patron, entreprise=cls.ent, role="admin")
        cls.employe = U.objects.create_user("employe", password="mot-de-passe-solide-123", first_name="Marc")
        cls.m_employe = Membre.objects.create(utilisateur=cls.employe, entreprise=cls.ent, role="operateur")
        cls.secteur = Secteur.objects.create(entreprise=cls.ent, nom="Village", ordre=10)
        cls.vide = Secteur.objects.create(entreprise=cls.ent, nom="Vide", ordre=20)
        c = Client.objects.create(entreprise=cls.ent, nom="Tremblay")
        Adresse.objects.create(entreprise=cls.ent, client=c, secteur=cls.secteur, ligne1="1, rue A", ville="Sainte-Adèle")
        cls.ailleurs = Secteur.objects.create(entreprise=cls.autre, nom="Ailleurs")
        VilleDesservie.objects.create(entreprise=cls.ent, nom="Sainte-Adèle", par_defaut=True)

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.patron)

    def test_fiche_modifiee_par_l_administrateur(self):
        self.assertContains(self.client.get("/plus/reglages/"), "Prochain numéro de facture")
        r = self.client.post("/plus/reglages/fiche/versements/", {"versements_par_defaut": 3, "dates_versements": "15/01 15/02",
                                                                 "jours_avance_versement": 5})
        self.assertRedirects(r, "/plus/reglages/")
        self.ent.refresh_from_db()
        self.assertEqual((self.ent.versements_par_defaut, self.ent.dates_versements), (3, "15/01 15/02"))
        # Date invalide : refusée par les règles du modèle
        r = self.client.post("/plus/reglages/fiche/versements/", {"versements_par_defaut": 2, "dates_versements": "45/13",
                                                                 "jours_avance_versement": 5})
        self.assertEqual(r.status_code, 200)
        numero = self.ent.prochain_numero_facture
        # Les réglages de la plateforme ne passent jamais par ici, même ajoutés à la main au formulaire
        self.client.post("/plus/reglages/fiche/factures/", {"inscrit_taxes": "", "numero_tps": "", "numero_tvq": "",
                                                            "interac_courriel": "", "interac_instructions": "",
                                                            "envois_actifs": "on", "prochain_numero_facture": numero + 50})
        self.ent.refresh_from_db()
        self.assertFalse(self.ent.inscrit_taxes)
        self.assertFalse(self.ent.envois_actifs)
        self.assertEqual(self.ent.prochain_numero_facture, numero)
        self.assertEqual(self.client.get("/plus/reglages/fiche/inconnue/").status_code, 404)

    def test_un_operateur_consulte_sans_modifier(self):
        self.client.force_login(self.employe)
        page = self.client.get("/plus/reglages/fiche/entreprise/")
        self.assertContains(page, "Consultation seulement")
        self.assertContains(page, "disabled")
        self.assertEqual(self.client.post("/plus/reglages/fiche/entreprise/", {"nom": "Pirate"}).status_code, 403)
        self.assertEqual(self.client.post("/plus/reglages/secteurs/nouveau/", {"nom": "X", "actif": "on"}).status_code, 403)
        self.assertEqual(self.client.post("/plus/reglages/utilisateurs/", {"prenom": "X", "cellulaire": "4505550109", "role": "admin"}).status_code, 403)
        self.ent.refresh_from_db()
        self.assertEqual(self.ent.nom, "Déneigement Essai")

    def test_secteurs(self):
        r = self.client.post("/plus/reglages/secteurs/nouveau/", {"nom": "  Chantecler ", "actif": "on"})
        self.assertRedirects(r, "/plus/reglages/secteurs/")
        s = Secteur.objects.get(entreprise=self.ent, nom="Chantecler")
        self.assertEqual(s.ordre, 30)  # à la fin de la tournée
        self.assertContains(self.client.post("/plus/reglages/secteurs/nouveau/", {"nom": "village"}), "Ce nom existe déjà")
        self.client.post(f"/plus/reglages/secteurs/{self.secteur.pk}/retirer/")
        self.assertTrue(Secteur.objects.filter(pk=self.secteur.pk).exists())  # a des adresses
        self.client.post(f"/plus/reglages/secteurs/{self.vide.pk}/retirer/")
        self.assertFalse(Secteur.objects.filter(pk=self.vide.pk).exists())
        # Le secteur d'une autre entreprise est introuvable
        self.assertEqual(self.client.get(f"/plus/reglages/secteurs/{self.ailleurs.pk}/").status_code, 404)
        self.assertEqual(self.client.post(f"/plus/reglages/secteurs/{self.ailleurs.pk}/retirer/").status_code, 404)

    def test_services(self):
        self.client.post("/plus/reglages/services/nouveau/", {"nom": "Entrée", "prix_suggere": "450,00", "taxable": "on", "actif": "on", "ordre": 1})
        s = Service.objects.get(entreprise=self.ent, nom="Entrée")
        self.assertEqual(str(s.prix_suggere), "450.00")
        self.assertContains(self.client.get("/plus/reglages/services/"), "Entrée")

    def test_ville_ajoutee_et_centre_cherche_par_le_worker(self):
        with mock.patch("core.tasks.centre_ville_desservie.defer") as differer:
            self.client.post("/plus/reglages/villes/nouvelle/", {"nom": "Val-Morin", "rayon_km": "6"})
        v = VilleDesservie.objects.get(entreprise=self.ent, nom="Val-Morin")
        differer.assert_called_once_with(ville_id=v.pk)
        self.assertContains(self.client.post("/plus/reglages/villes/nouvelle/", {"nom": "Ste-Adele", "rayon_km": "8"}), "déjà desservie")
        defaut = VilleDesservie.objects.get(entreprise=self.ent, par_defaut=True)
        self.client.post(f"/plus/reglages/villes/{defaut.pk}/retirer/")
        self.assertTrue(VilleDesservie.objects.filter(pk=defaut.pk).exists())
        self.client.post(f"/plus/reglages/villes/{v.pk}/retirer/")
        self.assertFalse(VilleDesservie.objects.filter(pk=v.pk).exists())

    def test_tache_du_centre(self):
        from core.tasks import centre_ville_desservie

        v = VilleDesservie.objects.create(entreprise=self.ent, nom="Val-Morin")
        a = Adresse.objects.create(entreprise=self.ent, client=Client.objects.first(), ligne1="2, rue B", ville="Val-Morin")
        with mock.patch("clients.geocodage.centre_ville", return_value=(46.0, -74.18)), \
             mock.patch("clients.tasks.geocoder_maintenant") as geo:
            centre_ville_desservie(ville_id=v.pk)
        v.refresh_from_db()
        self.assertAlmostEqual(v.centre.y, 46.0)
        geo.assert_called_once()
        self.assertEqual(geo.call_args.args[0].pk, a.pk)

    @override_settings(LMAPP_ENV="test", LMAPP_DESTINATAIRES_TEST=["+14505550109"])
    def test_inviter_puis_choisir_son_mot_de_passe(self):
        r = self.client.post("/plus/reglages/utilisateurs/", {"prenom": "Julie", "nom": "Roy", "cellulaire": "450 555-0109", "role": "operateur"})
        self.assertRedirects(r, "/plus/reglages/utilisateurs/", fetch_redirect_response=False)
        julie = get_user_model().objects.get(first_name="Julie")
        self.assertEqual(julie.username, "julie")
        self.assertFalse(julie.has_usable_password())
        self.assertEqual(Membre.objects.get(utilisateur=julie).entreprise, self.ent)
        m = Message.objects.get(destinataire="+14505550109")
        self.assertIn("Nom d'utilisateur : julie", m.contenu)
        page = self.client.get("/plus/reglages/utilisateurs/")
        self.assertContains(page, "invitation pas encore acceptée")
        lien = page.context["invitation"]["lien"]
        self.assertIn(lien, m.contenu)
        chemin = lien.split(HOTE)[1]

        self.client.logout()
        # Sur le domaine d'une autre entreprise, le lien ne vaut rien
        self.assertEqual(self.client.get(chemin, HTTP_HOST="autre.exemple.test").status_code, 404)
        self.assertContains(self.client.get(chemin), "Choisis ton mot de passe")
        r = self.client.post(chemin, {"new_password1": "Neige-Blanche-2026", "new_password2": "Neige-Blanche-2026"})
        self.assertRedirects(r, "/")
        julie.refresh_from_db()
        self.assertTrue(julie.check_password("Neige-Blanche-2026"))
        # Le lien ne sert qu'une fois
        self.client.logout()
        self.assertContains(self.client.get(chemin), "n'est plus valide", status_code=404)

    def test_role_et_retrait_d_acces(self):
        url = f"/plus/reglages/utilisateurs/{self.m_employe.pk}/"
        self.client.post(url, {"action": "role", "role": "lecture"})
        self.m_employe.refresh_from_db()
        self.assertEqual(self.m_employe.role, "lecture")
        self.client.post(url, {"action": "retirer"})
        self.assertFalse(Membre.objects.filter(pk=self.m_employe.pk).exists())
        self.employe.refresh_from_db()
        self.assertFalse(self.employe.is_active)
        # Jamais son propre accès
        moi = Membre.objects.get(utilisateur=self.patron)
        self.client.post(f"/plus/reglages/utilisateurs/{moi.pk}/", {"action": "retirer"})
        self.assertTrue(Membre.objects.filter(pk=moi.pk).exists())
