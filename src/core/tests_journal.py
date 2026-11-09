from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from clients.models import Adresse, Client
from core.models import Entreprise, JournalAction, Membre

HOTE = "jr.exemple.test"


@override_settings(ALLOWED_HOSTS=["*"])
class JournalTests(TestCase):
    """Journal des actions (K4)."""

    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai-jr", domaine=HOTE)
        cls.louis = get_user_model().objects.create_user("louis-jr", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="admin")

    def test_creation_modification_suppression_hors_requete(self):
        JournalAction.objects.all().delete()  # l'entreprise et le membre de setUpTestData y sont déjà
        c = Client.objects.create(entreprise=self.ent, prenom="Ginette", nom="Tremblay", cellulaire="+15145550123")
        c.cellulaire = "+15145550199"
        c.save()
        c.save()  # rien de changé : rien d'inscrit
        a = Adresse.objects.create(entreprise=self.ent, client=c, ligne1="1, rue A", ville="Sainte-Adèle")
        a.delete()
        lignes = list(JournalAction.objects.order_by("pk").values_list("action", "modele", "client_id", "nom_utilisateur"))
        self.assertEqual([l[0] for l in lignes], ["creation", "modification", "creation", "suppression"])
        self.assertTrue(all(l[2] == c.pk and l[3] == "système" for l in lignes))
        modif = JournalAction.objects.get(action="modification")
        self.assertEqual(modif.changements, {"cellulaire": ["+15145550123", "+15145550199"]})
        self.assertEqual(modif.entreprise_id, self.ent.pk)

    def test_utilisateur_de_la_requete(self):
        c = Client.objects.create(entreprise=self.ent, nom="Tremblay")
        self.client.force_login(self.louis)
        r = self.client.post(f"/clients/{c.pk}/appel/", {"sens": "recu", "resume": "x"}, HTTP_HOST=HOTE)
        self.assertEqual(r.status_code, 302)
        from facturation.models import Facture
        self.client.post(f"/clients/{c.pk}/factures/nouvelle/", {}, HTTP_HOST=HOTE)
        f = Facture.objects.filter(client=c).first()
        if f:
            j = JournalAction.objects.filter(modele=str(Facture._meta.verbose_name), objet_id=f.pk).first()
            self.assertEqual((j.nom_utilisateur, j.ip), ("louis-jr", "127.0.0.1"))

    def test_effacement_loi25_vide_le_journal_du_client(self):
        from clients.effacement import effacer
        c = Client.objects.create(entreprise=self.ent, prenom="Ginette", nom="Tremblay", cellulaire="+15145550123", notes="Code 1234")
        effacer(c)
        for j in JournalAction.objects.filter(client_id=c.pk).exclude(action="effacement"):
            self.assertEqual(j.changements, {})
            self.assertNotIn("Tremblay", j.objet)
        self.assertTrue(JournalAction.objects.filter(client_id=c.pk, action="effacement").exists())
        self.assertFalse(JournalAction.objects.filter(changements__icontains="1234").exists())

    def test_purge(self):
        from datetime import timedelta
        from django.utils import timezone
        from core.tasks import purger_journal_chaque_nuit
        JournalAction.objects.all().delete()
        Client.objects.create(entreprise=self.ent, nom="Vieux")
        JournalAction.objects.update(moment=timezone.now() - timedelta(days=800))
        Client.objects.create(entreprise=self.ent, nom="Récent")
        self.assertEqual(purger_journal_chaque_nuit(timestamp=0), 1)
        self.assertEqual(JournalAction.objects.count(), 1)

    def test_administration_en_lecture(self):
        jf = get_user_model().objects.create_superuser("jf-jr", password="x" * 12)
        Client.objects.create(entreprise=self.ent, nom="Tremblay", notes="allo")
        j = JournalAction.objects.first()
        self.client.force_login(jf)
        self.assertEqual(self.client.get("/admin/core/journalaction/").status_code, 200)
        r = self.client.get(f"/admin/core/journalaction/{j.pk}/change/")
        self.assertContains(r, "allo")
        self.client.post(f"/admin/core/journalaction/{j.pk}/change/", {"objet": "modifié"})
        j.refresh_from_db()
        self.assertNotEqual(j.objet, "modifié")
