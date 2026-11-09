"""C9 : relances proposées chaque matin, envoyées seulement par une tape du déneigeur."""
from datetime import date, datetime, timedelta
from decimal import Decimal as D
from unittest import mock
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from clients.models import Client
from communications import relances
from communications.models import Message
from communications.relances_proposees import proposees
from core.models import Entreprise, Membre
from demandes.models import Demande
from facturation.models import Facture

HOTE = "louis.exemple.test"
AUJOURDHUI = date(2026, 11, 20)


@override_settings(ALLOWED_HOSTS=["*"], LMAPP_ENV="test", LMAPP_DESTINATAIRES_TEST=["+14505550101"],
                   TWILIO_ACCOUNT_SID="AC-essai", TWILIO_AUTH_TOKEN="jeton")
class RelancesProposeesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE, envois_actifs=True,
                                            numero_texto="+14503001166", relances_proposees=True)
        cls.c = Client.objects.create(entreprise=cls.ent, nom="Tremblay", cellulaire="+14505550101", canal_prefere="texto")
        cls.louis = get_user_model().objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")

    def setUp(self):
        self.defer = mock.patch("communications.tasks.envoyer_message.defer").start()
        self.addCleanup(mock.patch.stopall)

    def facture(self, client=None, echeance=date(2026, 11, 1), montant="100.00"):
        f = Facture.objects.create(entreprise=self.ent, client=client or self.c, date_facture=min(echeance, date(2026, 10, 25)), date_echeance=echeance)
        f.lignes.create(description="Déneigement", quantite=1, prix_unitaire=D(montant), taxable=False)
        f.recalculer()
        f.emettre()
        return f

    def niveaux(self, jour=AUJOURDHUI):
        return [(p["client"].nom, p["niveau"]) for p in proposees(self.ent, jour)]

    def test_calendrier_15_30_60_puis_plus_rien(self):
        self.facture()  # échéance 1er novembre
        self.assertEqual(self.niveaux(date(2026, 11, 15)), [])  # 14 jours
        self.assertEqual(self.niveaux(date(2026, 11, 16)), [("Tremblay", 1)])
        relances.relancer(self.c, 1)
        Message.objects.update(cree_le=timezone.now() - timedelta(days=8))
        self.assertEqual(self.niveaux(date(2026, 11, 30)), [])  # 29 jours : le deuxième avis attend 30
        self.assertEqual(self.niveaux(date(2026, 12, 1)), [("Tremblay", 2)])
        relances.relancer(self.c, 2)
        Message.objects.update(cree_le=timezone.now() - timedelta(days=8))
        self.assertEqual(self.niveaux(date(2026, 12, 30)), [])
        self.assertEqual(self.niveaux(date(2026, 12, 31)), [("Tremblay", 3)])
        relances.relancer(self.c, 3)
        Message.objects.update(cree_le=timezone.now() - timedelta(days=8))  # pas avant la facture : sinon elles ne comptent plus
        self.assertEqual(self.niveaux(date(2027, 3, 1)), [])  # après le dernier avis : à Louis de jouer

    def test_sept_jours_entre_deux_relances(self):
        self.facture(echeance=date(2026, 9, 1))  # 80 jours : le rappel est dû
        relances.relancer(self.c, 1)
        self.assertEqual(self.niveaux(), [])
        Message.objects.update(cree_le=timezone.now() - timedelta(days=8))
        self.assertEqual(self.niveaux(), [("Tremblay", 2)])  # un niveau à la fois, pas de saut au dernier avis

    def test_exclusions(self):
        f = self.facture()
        self.assertEqual(len(self.niveaux()), 1)
        d = Demande.objects.create(entreprise=self.ent, client=self.c, genre="plainte", description="Bordure brisée")
        self.assertEqual(self.niveaux(), [])  # demande ouverte
        d.changer_statut(Demande.Statut.REGLEE, "Réparée")
        self.assertEqual(len(self.niveaux()), 1)
        Client.objects.filter(pk=self.c.pk).update(ne_pas_relancer=True)
        self.assertEqual(self.niveaux(), [])
        Client.objects.filter(pk=self.c.pk).update(ne_pas_relancer=False, relance_reportee_au=AUJOURDHUI + timedelta(days=1))
        self.assertEqual(self.niveaux(), [])
        self.assertEqual(len(self.niveaux(AUJOURDHUI + timedelta(days=1))), 1)
        Client.objects.filter(pk=self.c.pk).update(relance_reportee_au=None, cellulaire="")
        self.assertEqual(self.niveaux(), [])  # ni cellulaire ni courriel
        Client.objects.filter(pk=self.c.pk).update(cellulaire="+14505550101")
        f.paiements.create(entreprise=self.ent, montant=f.total, mode="comptant", date=AUJOURDHUI)
        self.assertEqual(self.niveaux(), [])  # payé : arrêt

    def test_soldes_anterieurs_selon_le_choix_de_l_entreprise(self):
        Facture.solde_ouverture(self.c, D("120.00"), saison_origine="2024-2025", date_facture=date(2026, 10, 1))
        self.assertEqual(self.niveaux(), [])
        Entreprise.objects.filter(pk=self.ent.pk).update(relances_soldes_anterieurs=True)
        self.c.entreprise.refresh_from_db()
        self.assertEqual(proposees(Entreprise.objects.get(pk=self.ent.pk), AUJOURDHUI)[0]["niveau"], 1)

    def test_ecran_envoi_des_cochees_et_report(self):
        self.facture(echeance=date(2026, 9, 1))
        autre = Client.objects.create(entreprise=self.ent, nom="Roy", cellulaire="+14505550102", canal_prefere="texto")
        self.facture(autre, echeance=date(2026, 9, 1))
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)
        self.assertContains(self.client.get("/comptes/"), "2 relances prêtes à envoyer")
        r = self.client.get("/comptes/relances/")
        self.assertContains(r, "Tremblay")
        self.assertContains(r, "Rien ne part sans votre tape")
        self.assertEqual(Message.objects.count(), 0)  # afficher n'envoie rien
        r = self.client.post("/comptes/relances/envoyer/", {"client": [self.c.pk]}, follow=True)
        self.assertContains(r, "1 relance en route.")
        self.assertEqual(list(Message.objects.values_list("client__nom", "genre")), [("Tremblay", "relance_1")])
        self.client.post(f"/comptes/relances/{autre.pk}/reporter/")
        autre.refresh_from_db()
        self.assertEqual(autre.relance_reportee_au, timezone.localdate() + timedelta(days=7))
        self.assertContains(self.client.get("/comptes/"), "aucune aujourd'hui")

    def test_lecture_seule_ne_peut_pas_envoyer(self):
        self.facture(echeance=date(2026, 9, 1))
        lecteur = get_user_model().objects.create_user("lecteur", password="x" * 12)
        Membre.objects.create(utilisateur=lecteur, entreprise=self.ent, role="lecture")
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(lecteur)
        self.assertNotContains(self.client.get("/comptes/relances/"), 'name="client"')
        self.assertEqual(self.client.post("/comptes/relances/envoyer/", {"client": [self.c.pk]}).status_code, 403)
        self.assertEqual(Message.objects.count(), 0)

    def test_avis_du_matin_une_fois_par_jour_de_semaine_hors_operation(self):
        from communications.tasks import aviser_relances
        from tournee.models import Operation

        self.facture(echeance=date(2026, 1, 1))
        notifier = mock.patch("core.tasks.notifier.defer").start()
        tz = ZoneInfo("America/Toronto")
        with mock.patch("django.utils.timezone.localtime", return_value=datetime(2026, 11, 21, 10, tzinfo=tz)):
            self.assertEqual(aviser_relances(0), "hors des heures")  # samedi
        with mock.patch("django.utils.timezone.localtime", return_value=datetime(2026, 11, 20, 8, tzinfo=tz)):
            self.assertEqual(aviser_relances(0), "hors des heures")
        op = Operation.objects.create(entreprise=self.ent, type="neige")
        with mock.patch("django.utils.timezone.localtime", return_value=datetime(2026, 11, 20, 9, tzinfo=tz)):
            self.assertEqual(aviser_relances(0), 0)  # pendant une opération : on attend
            op.fin = timezone.now()
            op.save()
            self.assertEqual(aviser_relances(0), 1)
            self.assertEqual(aviser_relances(0), 0)  # une fois par jour
        self.assertEqual(notifier.call_count, 1)
        self.assertIn("Rien ne part sans vous", notifier.call_args.kwargs["corps"])
        self.assertEqual(Message.objects.count(), 0)  # l'avis n'envoie aucune relance
