from datetime import date
from decimal import Decimal as D
from unittest import mock

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
        # Une facture par passage, payable sur réception (décision de JF, 12 novembre 2026)
        factures = list(Facture.objects.filter(contrat=c).order_by("date_facture"))
        self.assertEqual(len(factures), 2)
        self.assertEqual(Facture.objects.count(), 2)
        f = factures[1]
        self.assertEqual((f.statut, f.total, f.date_echeance), ("brouillon", D("51.74"), f.date_facture))  # payable sur réception
        self.assertTrue(f.lignes.get().description.startswith("Déneigement du 12 décembre (neige)"))
        self.assertEqual(list(services.factures_des_passages(self.ent)), factures)
        # Corrigé en « sauté » : la facture du passage (brouillon) disparaît
        services.marquer(p.operation, self.a1, "saute", raison="auto")
        self.assertEqual(Facture.objects.filter(contrat=c).count(), 1)
        # Facture émise : un nouveau passage fait sa propre facture
        factures[0].emettre()
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

    def donnees(self, url="/tournee/"):
        return self.client.get(url).context["donnees"]

    def test_carte_des_entrees_numerotees(self):
        from django.contrib.gis.geos import Point
        Adresse.objects.filter(pk=self.a1.pk).update(position=Point(-74.13, 45.95, srid=4326), position_source="manuelle", position_precision="adresse")
        Adresse.objects.filter(pk=self.a2.pk).update(position=Point(-74.12, 45.96, srid=4326), position_source="geocodage", position_precision="ville")
        self.client.post("/tournee/demarrer/", {"type": "neige", "avis_clients": "0"})
        op = Operation.en_cours_de(self.ent)
        services.marquer(op, self.a1, "fait")
        d = self.client.get("/tournee/carte/arrets/").json()
        self.assertEqual([(a["rang"], a["adresse"], a["etat"]) for a in d["arrets"]], [(1, "1, rue Tremblay", "fait")])
        self.assertEqual([a["rang"] for a in d["a_placer"]], [2, 3, 4])  # à la ville près, ou sans position
        self.assertIn("/position/", d["a_placer"][0]["lien"])
        self.assertContains(self.client.get("/tournee/ordre/"), "carte-ordre")
        self.client.force_login(get_user_model().objects.create_user("x", password="x" * 12))
        self.assertNotEqual(self.client.get("/tournee/carte/arrets/").status_code, 200)  # pas membre

    def synchro(self, *passages):
        import json
        return self.client.post("/tournee/synchro/", json.dumps({"passages": list(passages)}), content_type="application/json")

    def test_une_operation_complete(self):
        self.assertContains(self.client.get("/tournee/"), "Démarrer : Neige")
        r = self.client.post("/tournee/demarrer/", {"type": "neige", "avis_clients": "1"}, follow=True)
        self.assertContains(r, "Opération « Neige » commencée.")
        d = r.context["donnees"]
        self.assertEqual([a["id"] for a in d["arrets"]], [self.a1.pk, self.a2.pk, self.a_mont.pk, self.a_sans_rang.pk])
        self.assertTrue(d["arrets"][1]["recouvrement"])
        self.assertIn("maps.apple.com", d["arrets"][0]["navigation"][0][1])
        op = d["operation"]["id"]
        r = self.synchro({"cle": "a", "operation": op, "adresse": self.a1.pk, "statut": "fait", "note": "Boîte aux lettres croche",
                          "quand": "2026-11-08T09:15:00+00:00"},
                         {"cle": "b", "operation": op, "adresse": self.a2.pk, "statut": "saute", "raison": "non_paye"})
        self.assertEqual([x["cle"] for x in r.json()["acceptes"]], ["a", "b"])
        self.assertEqual(r.json()["refuses"], [])
        arrets_ = self.donnees()["arrets"]
        self.assertEqual((arrets_[0]["passage"]["statut"], arrets_[1]["passage"]["raison"]), ("fait", "non_paye"))
        r = self.client.post("/tournee/terminer/", follow=True)
        self.assertContains(r, "Opération terminée : 1 fait, 1 sauté, 2 pas visités.")
        fiche = self.client.get(f"/clients/{self.a1.client.pk}/")
        self.assertContains(fiche, "Boîte aux lettres croche")
        self.assertContains(self.client.get(f"/clients/{self.a2.client.pk}/"), "Sauté : compte non payé")

    def test_synchro_hors_ligne_garde_l_heure_de_la_tape(self):
        from django.utils import timezone
        from datetime import timedelta
        self.client.post("/tournee/demarrer/", {"type": "neige", "avis_clients": "1"})
        op = Operation.objects.get()
        tape = timezone.now() - timedelta(minutes=20)
        Operation.objects.filter(pk=op.pk).update(debut=timezone.now() - timedelta(hours=1))
        self.synchro({"cle": "x", "operation": op.pk, "adresse": self.a1.pk, "statut": "fait", "quand": tape.isoformat()})
        self.assertLess(abs((Passage.objects.get().heure - tape).total_seconds()), 1)
        # Heure dans le futur (horloge du téléphone déréglée) : ramenée à maintenant
        self.synchro({"cle": "y", "operation": op.pk, "adresse": self.a2.pk, "statut": "fait", "quand": (timezone.now() + timedelta(days=1)).isoformat()})
        self.assertLessEqual(Passage.objects.get(adresse=self.a2).heure, timezone.now())
        # La même tape envoyée deux fois (réponse perdue) : un seul passage
        self.synchro({"cle": "x", "operation": op.pk, "adresse": self.a1.pk, "statut": "fait", "quand": tape.isoformat()})
        self.assertEqual(Passage.objects.filter(adresse=self.a1).count(), 1)

    def test_synchro_apres_la_fin_de_l_operation(self):
        self.client.post("/tournee/demarrer/", {"type": "neige", "avis_clients": "1"})
        op = Operation.objects.get()
        self.client.post("/tournee/terminer/")
        # Tapé hors ligne avant la fin, arrivé après : accepté dans son opération
        r = self.synchro({"cle": "z", "operation": op.pk, "adresse": self.a1.pk, "statut": "fait"})
        self.assertEqual(len(r.json()["acceptes"]), 1)

    def test_synchro_refuse_ce_qui_ne_va_pas(self):
        self.client.post("/tournee/demarrer/", {"type": "neige", "avis_clients": "1"})
        op = Operation.objects.get()
        etrangere = Adresse.objects.create(entreprise=self.autre, client=Client.objects.create(entreprise=self.autre, nom="X"),
                                           ligne1="1, rue X", ville="Ailleurs")
        op_autre = Operation.objects.create(entreprise=self.autre)
        r = self.synchro({"cle": "1", "operation": op.pk, "adresse": etrangere.pk, "statut": "fait"},
                         {"cle": "2", "operation": op_autre.pk, "adresse": self.a1.pk, "statut": "fait"},
                         {"cle": "3", "operation": op.pk, "adresse": self.a1.pk, "statut": "saute"},
                         {"cle": "4", "operation": op.pk, "adresse": self.a1.pk, "statut": "n'importe quoi"},
                         {"cle": "5", "operation": "abc", "adresse": self.a1.pk, "statut": "fait"})
        self.assertEqual(r.json(), {"acceptes": [], "refuses": ["1", "2", "3", "4", "5"]})
        self.assertFalse(Passage.objects.exists())
        self.assertEqual(self.client.post("/tournee/synchro/", "pas du json", content_type="application/json").status_code, 400)

    def test_service_worker(self):
        r = self.client.get("/sw.js")
        self.assertEqual(r["Content-Type"], "application/javascript; charset=utf-8")
        self.assertEqual(r["Service-Worker-Allowed"], "/")
        self.assertContains(r, "terrain/tournee.")
        self.assertContains(self.client.get("/"), "serviceWorker.register")

    def test_saute_sans_raison_refuse_et_pas_d_operation(self):
        self.client.post(f"/tournee/passages/{self.a1.pk}/", {"statut": "fait"})
        self.assertFalse(Passage.objects.exists())  # aucune opération en cours
        self.client.post("/tournee/demarrer/", {"type": "neige", "avis_clients": "1"})
        self.client.post(f"/tournee/passages/{self.a1.pk}/", {"statut": "saute"})
        self.assertFalse(Passage.objects.exists())

    def test_double_demarrage(self):
        self.client.post("/tournee/demarrer/", {"type": "neige", "avis_clients": "1"})
        r = self.client.post("/tournee/demarrer/", {"type": "verglas", "avis_clients": "1"}, follow=True)
        self.assertContains(r, "déjà en cours")
        self.assertEqual(Operation.objects.count(), 1)

    def test_lecture_seule_et_autre_entreprise(self):
        self.client.post("/tournee/demarrer/", {"type": "neige", "avis_clients": "1"})
        etrangere = Adresse.objects.create(entreprise=self.autre, client=Client.objects.create(entreprise=self.autre, nom="X"),
                                           ligne1="1, rue X", ville="Ailleurs")
        self.assertEqual(self.client.post(f"/tournee/passages/{etrangere.pk}/", {"statut": "fait"}).status_code, 404)
        self.client.force_login(self.lecteur)
        page = self.client.get("/tournee/")
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context["donnees"]["ecriture"])
        self.assertNotContains(page, "Terminer l'opération")
        self.assertEqual(self.client.post("/tournee/synchro/", '{"passages": []}', content_type="application/json").status_code, 403)
        self.assertEqual(self.client.post(f"/tournee/passages/{self.a1.pk}/", {"statut": "fait"}).status_code, 403)


@override_settings(ALLOWED_HOSTS=["*"])
class OrdreTests(TourneeBase):
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

    def ordre(self):
        return [a.pk for a in arrets(self.ent)]

    def test_page_ordre(self):
        page = self.client.get("/tournee/ordre/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "Village")
        self.assertContains(page, "Sans secteur")
        self.assertContains(page, f'aria-label="Monter {self.a2.ligne1}"')  # le nom de l'arrêt, pas « l'arrêt »

    def test_monter_et_descendre_un_arret(self):
        r = self.client.post(f"/tournee/ordre/arrets/{self.a2.pk}/", {"sens": "haut"})
        self.assertRedirects(r, f"/tournee/ordre/?bouge=a{self.a2.pk}#a{self.a2.pk}", fetch_redirect_response=False)
        self.assertEqual(self.ordre(), [self.a2.pk, self.a1.pk, self.a_mont.pk, self.a_sans_rang.pk])
        self.client.post(f"/tournee/ordre/arrets/{self.a2.pk}/", {"sens": "bas"})
        self.assertEqual(self.ordre(), [self.a1.pk, self.a2.pk, self.a_mont.pk, self.a_sans_rang.pk])

    def test_rang_tape_directement(self):
        self.client.post(f"/tournee/ordre/arrets/{self.a2.pk}/rang/", {"rang": "1"})
        self.assertEqual(self.ordre(), [self.a2.pk, self.a1.pk, self.a_mont.pk, self.a_sans_rang.pk])
        # Rang hors du secteur : ramené au dernier du Village, sans changer de secteur
        r = self.client.post(f"/tournee/ordre/arrets/{self.a2.pk}/rang/", {"rang": "9"}, HTTP_HX_REQUEST="true")
        self.assertContains(r, "Rang ramené dans le secteur Village (rangs 1 à 2)")
        self.assertEqual(self.ordre(), [self.a1.pk, self.a2.pk, self.a_mont.pk, self.a_sans_rang.pk])
        self.a2.refresh_from_db()
        self.assertEqual(self.a2.secteur.nom, "Village")
        r = self.client.post(f"/tournee/ordre/arrets/{self.a2.pk}/rang/", {"rang": "abc"}, HTTP_HX_REQUEST="true")
        self.assertContains(r, "Taper un numéro de rang.")
        self.assertContains(self.client.get("/tournee/ordre/"), "changer le rang")

    def test_au_bout_rien_ne_bouge_et_reste_dans_son_secteur(self):
        self.client.post(f"/tournee/ordre/arrets/{self.a1.pk}/", {"sens": "haut"})
        self.client.post(f"/tournee/ordre/arrets/{self.a2.pk}/", {"sens": "bas"})  # dernier du Village
        self.assertEqual(self.ordre(), [self.a1.pk, self.a2.pk, self.a_mont.pk, self.a_sans_rang.pk])
        self.a2.refresh_from_db()
        self.assertEqual(self.a2.secteur.nom, "Village")

    def test_renumerote_les_rangs_vides_ou_en_double(self):
        Adresse.objects.filter(pk__in=[self.a1.pk, self.a2.pk]).update(ordre_tournee=None)
        self.client.post(f"/tournee/ordre/arrets/{self.a2.pk}/", {"sens": "haut"})
        rangs = dict(Adresse.objects.filter(secteur__nom="Village", active=True,
                                            client__statut__in=["actif", "recouvrement"]).values_list("pk", "ordre_tournee"))
        self.assertEqual(rangs, {self.a2.pk: 10, self.a1.pk: 20})

    def test_sans_secteur(self):
        autre = Adresse.objects.create(entreprise=self.ent, client=self.a_sans_rang.client, ligne1="9, rue Roy", ville="Sainte-Adèle")
        self.client.post(f"/tournee/ordre/arrets/{autre.pk}/", {"sens": "haut"})
        self.assertEqual(self.ordre()[-2:], [autre.pk, self.a_sans_rang.pk])

    def test_monter_un_secteur(self):
        mont = Secteur.objects.get(nom="Mont")
        self.client.post(f"/tournee/ordre/secteurs/{mont.pk}/", {"sens": "haut"})
        self.assertEqual(self.ordre(), [self.a_mont.pk, self.a1.pk, self.a2.pk, self.a_sans_rang.pk])

    def test_htmx_renvoie_la_liste(self):
        r = self.client.post(f"/tournee/ordre/arrets/{self.a2.pk}/", {"sens": "haut"}, HTTP_HX_REQUEST="true")
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "terrain/tournee/_ordre.html")
        self.assertTemplateNotUsed(r, "terrain/base.html")
        self.assertContains(r, "bg-accent/10")

    def test_autre_entreprise_et_lecture_seule(self):
        etranger = Adresse.objects.create(entreprise=self.autre, client=Client.objects.create(entreprise=self.autre, nom="X"),
                                          ligne1="1, rue X", ville="Ailleurs")
        self.assertEqual(self.client.post(f"/tournee/ordre/arrets/{etranger.pk}/", {"sens": "haut"}).status_code, 404)
        self.client.force_login(self.lecteur)
        page = self.client.get("/tournee/ordre/")
        self.assertNotContains(page, "Monter")
        self.assertEqual(self.client.post(f"/tournee/ordre/arrets/{self.a2.pk}/", {"sens": "haut"}).status_code, 403)
        self.assertEqual(self.ordre(), [self.a1.pk, self.a2.pk, self.a_mont.pk, self.a_sans_rang.pk])


@override_settings(ALLOWED_HOSTS=["*"])
class ACollecterTests(TourneeBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        U = get_user_model()
        cls.louis = U.objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")
        Client.objects.filter(pk__in=[cls.a2.client_id, cls.a_mont.client_id]).update(mode_paiement="comptant")
        Client.objects.filter(pk=cls.a1.client_id).update(mode_paiement="interac")
        for adresse, montant in [(cls.a2, "120.00"), (cls.a1, "80.00")]:
            f = Facture.objects.create(entreprise=cls.ent, client=adresse.client)
            f.lignes.create(description="Déneigement", quantite=1, prix_unitaire=D(montant), taxable=False)
            f.recalculer()
            f.emettre()

    def setUp(self):
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)

    def test_liste_dans_l_ordre_de_la_tournee(self):
        page = self.client.get("/tournee/collecter/")
        lignes = page.context["lignes"]
        self.assertEqual([l["client"].pk for l in lignes], [self.a2.client_id])  # comptant et doit; Pelletier ne doit rien, Tremblay paie par Interac
        self.assertEqual(page.context["total"], D("120.00"))
        self.assertContains(page, "120,00")

    def test_montant_sur_la_carte_de_l_arret(self):
        op = Operation.objects.create(entreprise=self.ent)
        arrets_ = {a["id"]: a for a in self.client.get("/tournee/").context["donnees"]["arrets"]}
        self.assertEqual((arrets_[self.a2.pk]["du"], arrets_[self.a2.pk]["comptant"]), ("120,00 $", True))
        self.assertEqual((arrets_[self.a1.pk]["du"], arrets_[self.a1.pk]["comptant"]), ("80,00 $", False))
        self.assertEqual(arrets_[self.a_mont.pk]["du"], "")
        services.marquer(op, self.a2, "fait")
        self.assertTrue(self.client.get("/tournee/collecter/").context["lignes"][0]["fait"])


@override_settings(ALLOWED_HOSTS=["*"])
class PhotoPassageTests(TestCase):
    """Photo du passage (F7) : opération en cours, heure bornée, position, avant ou après, fiche, effacement."""
    JPEG = b"\xff\xd8\xff\xe0" + b"1" * 200

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from core.models import Membre
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai-pp", domaine="pp.exemple.test")
        cls.c = Client.objects.create(entreprise=cls.ent, nom="Tremblay")
        cls.a = Adresse.objects.create(entreprise=cls.ent, client=cls.c, ligne1="1, rue A", ville="Sainte-Adèle")
        cls.louis = get_user_model().objects.create_user("louis-pp", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")

    def envoyer(self, **extra):
        from django.core.files.uploadedfile import SimpleUploadedFile
        d = {"adresse": self.a.pk, "photo": SimpleUploadedFile("p.jpg", self.JPEG), **extra}
        return self.client.post("/tournee/photos/", d, HTTP_HOST="pp.exemple.test")

    def test_sans_operation_refusee(self):
        self.client.force_login(self.louis)
        self.assertEqual(self.envoyer().status_code, 400)

    def test_avant_apres_et_fiche(self):
        from datetime import timedelta
        from django.utils import timezone
        from tournee.models import PhotoPassage
        self.client.force_login(self.louis)
        op = Operation.objects.create(entreprise=self.ent, type="neige", debut=timezone.now() - timedelta(hours=1))
        avant = (timezone.now() - timedelta(minutes=20)).isoformat()
        r = self.envoyer(quand=avant, lat="45.95", lng="-74.13", precision="12")
        self.assertEqual(r.json()["photos"], 1)
        Passage.objects.create(entreprise=self.ent, operation=op, adresse=self.a, statut="fait", heure=timezone.now() - timedelta(minutes=10))
        self.envoyer(quand=(timezone.now() + timedelta(days=1)).isoformat())  # heure du futur : bornée à maintenant
        p1, p2 = PhotoPassage.objects.order_by("prise_le")
        self.assertEqual((p1.moment(), p2.moment()), ("avant", "après"))
        self.assertEqual((round(p1.position.y, 2), p1.precision_m), (45.95, 12))
        self.assertLessEqual(p2.prise_le, timezone.now())
        r = self.client.get(f"/clients/{self.c.pk}/", HTTP_HOST="pp.exemple.test")
        self.assertContains(r, f"/photos-passage/{p1.pk}/")
        self.assertContains(r, "Avant")
        self.assertEqual(self.client.get(f"/photos-passage/{p1.pk}/", HTTP_HOST="pp.exemple.test").content, self.JPEG)
        from clients.effacement import effacer
        effacer(self.c)
        self.assertFalse(PhotoPassage.objects.exists())

    def test_pas_une_photo(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.utils import timezone
        self.client.force_login(self.louis)
        Operation.objects.create(entreprise=self.ent, type="neige", debut=timezone.now())
        r = self.client.post("/tournee/photos/", {"adresse": self.a.pk, "photo": SimpleUploadedFile("p.jpg", b"<svg>")}, HTTP_HOST="pp.exemple.test")
        self.assertEqual(r.status_code, 400)


@override_settings(ALLOWED_HOSTS=["*"])
class CarteDirectTests(TestCase):
    """G6 : position du cellulaire pendant l'opération, pour les administrateurs seulement."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.gis.geos import Point
        from django.utils import timezone
        from tournee.models import PositionGPS
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai-cd", domaine="cd.exemple.test")
        U = get_user_model()
        cls.admin = U.objects.create_user("admin-cd", password="x" * 12)
        Membre.objects.create(utilisateur=cls.admin, entreprise=cls.ent, role="admin")
        cls.op_ = U.objects.create_user("oper-cd", password="x" * 12)
        Membre.objects.create(utilisateur=cls.op_, entreprise=cls.ent, role="operateur")
        op = Operation.objects.create(entreprise=cls.ent, type="neige", debut=timezone.now())
        PositionGPS.objects.create(operation=op, position=Point(-74.13, 45.95, srid=4326), precision_m=12)

    def test_admin_voit_la_position(self):
        self.client.force_login(self.admin)
        h = {"HTTP_HOST": "cd.exemple.test"}
        self.assertEqual(self.client.get("/tournee/carte/", **h).status_code, 200)
        d = self.client.get("/tournee/carte/donnees/", **h).json()
        self.assertEqual((round(d["dernier"]["lat"], 2), d["dernier"]["precision"], len(d["trace"])), (45.95, 12, 1))

    def test_operateur_refuse(self):
        self.client.force_login(self.op_)
        self.assertEqual(self.client.get("/tournee/carte/donnees/", HTTP_HOST="cd.exemple.test").status_code, 403)


class TempsParEntreeTests(TourneeBase):
    """Lot C (demande de Louis) : temps sur place mesuré par la position, gardé sur le passage; statistiques par client."""

    def test_temps_sur_place_trajet_et_sans_gps(self):
        from datetime import datetime, timedelta

        from django.contrib.gis.geos import Point
        from django.utils import timezone

        from tournee.models import PositionGPS
        from tournee.temps import calculer

        Adresse.objects.filter(pk=self.a1.pk).update(position=Point(-74.1300, 45.9500, srid=4326))
        Adresse.objects.filter(pk=self.a2.pk).update(position=Point(-74.1200, 45.9600, srid=4326))
        debut = timezone.make_aware(datetime(2026, 12, 5, 3, 0))
        op = Operation.objects.create(entreprise=self.ent, debut=debut)
        services.marquer(op, self.a1, "fait", quand=debut + timedelta(minutes=20))
        services.marquer(op, self.a2, "fait", quand=debut + timedelta(minutes=40))
        services.marquer(op, self.a_mont, "fait", quand=debut + timedelta(minutes=55))  # pas de position : depuis la précédente
        PositionGPS.objects.create(operation=op, position=Point(-74.1395, 45.9450, srid=4326), moment=debut + timedelta(minutes=5), precision_m=10)  # en route
        PositionGPS.objects.create(operation=op, position=Point(-74.13005, 45.95002, srid=4326), moment=debut + timedelta(minutes=12), precision_m=10)
        PositionGPS.objects.create(operation=op, position=Point(-74.1201, 45.9600, srid=4326), moment=debut + timedelta(minutes=31), precision_m=400)  # trop imprécis
        PositionGPS.objects.create(operation=op, position=Point(-74.1201, 45.9600, srid=4326), moment=debut + timedelta(minutes=33), precision_m=20)
        self.assertEqual(calculer(op), 3)
        p1, p2, p3 = op.passages.order_by("heure")
        self.assertEqual((p1.sur_place_s, p1.trajet_s, p1.depuis_precedent_s), (8 * 60, 12 * 60, 20 * 60))
        self.assertEqual((p2.sur_place_s, p2.trajet_s), (7 * 60, 13 * 60))
        self.assertEqual((p3.sur_place_s, p3.depuis_precedent_s), (None, 15 * 60))

    @override_settings(ALLOWED_HOSTS=["*"])
    def test_rapport_et_statistiques(self):
        from django.contrib.auth import get_user_model

        u = get_user_model().objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=u, entreprise=self.ent, role="operateur")
        Contrat.objects.create(entreprise=self.ent, client=self.a1.client, adresse=self.a1, saison=self.saison, prix=D("450"))
        op = Operation.objects.create(entreprise=self.ent)
        p = services.marquer(op, self.a1, "fait")
        Passage.objects.filter(pk=p.pk).update(sur_place_s=15 * 60)
        op.fin = op.debut
        op.save()
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(u)
        self.assertContains(self.client.get(f"/tournee/operations/{op.pk}/"), "1, rue Tremblay")
        with mock.patch("django.utils.timezone.localdate", return_value=date(2026, 12, 1)):
            r = self.client.get("/tournee/statistiques/")
        self.assertEqual([(l["client"].nom, l["moyenne"], l["par_heure"]) for l in r.context["lignes"]], [("Tremblay", 15, D("1800"))])


@override_settings(ALLOWED_HOSTS=["*"])
class JobsTests(TourneeBase):
    """Jobs à la pièce (déneigement manuel, paysagement) et clients d'été (demandes de Louis)."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.u = get_user_model().objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=self.u, entreprise=self.ent, role="operateur")
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.u)

    def test_job_complete_puis_facture(self):
        import json
        from datetime import timedelta

        from django.contrib.gis.geos import Point
        from django.utils import timezone

        from tournee.models import Job

        Entreprise.objects.filter(pk=self.ent.pk).update(taux_horaire=D("60"), taux_km=D("0.75"), minimum_job=D("75"))
        Adresse.objects.filter(pk=self.a1.pk).update(position=Point(-74.1400, 45.9000, srid=4326))
        r = self.client.post(f"/clients/{self.a1.client_id}/jobs/partir/", {"genre": "deneigement"})
        j = Job.objects.get()
        self.assertRedirects(r, f"/jobs/{j.pk}/", fetch_redirect_response=False)
        self.assertContains(self.client.get(f"/clients/{self.a1.client_id}/"), "en cours depuis")
        r = self.client.post(f"/jobs/{j.pk}/position/", json.dumps({"quoi": "depart", "lat": 45.95, "lon": -74.14, "precision": 10}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 200)
        j.refresh_from_db()
        self.assertEqual(j.distance_km, D("7.2"))  # 5,56 km à vol d'oiseau × 1,3
        Job.objects.filter(pk=j.pk).update(depart_le=timezone.now() - timedelta(minutes=50))
        self.client.post(f"/jobs/{j.pk}/etape/", {"quoi": "arrivee"})
        Job.objects.filter(pk=j.pk).update(arrivee_le=timezone.now() - timedelta(minutes=40))
        self.client.post(f"/jobs/{j.pk}/etape/", {"quoi": "terminer"})
        j.refresh_from_db()
        self.assertEqual((j.trajet_min, j.sur_place_min), (10, 40))
        r = self.client.post(f"/jobs/{j.pk}/etape/", {"quoi": "facturer"})
        f = j.facture or Job.objects.get(pk=j.pk).facture
        self.assertRedirects(r, f"/factures/{f.pk}/", fetch_redirect_response=False)
        lignes = list(f.lignes.order_by("ordre").values_list("quantite", "prix_unitaire"))
        self.assertEqual(lignes, [(D("0.75"), D("60.00")), (D("14.40"), D("0.75")), (D("1.00"), D("19.20"))])  # 45 min au quart d heure; aller-retour; minimum
        self.assertEqual(f.sous_total, D("75.00"))  # 45,00 + 10,80 < 75 : ajusté au minimum
        self.assertEqual(f.statut, "brouillon")

    def test_client_d_ete_pas_dans_la_tournee_ni_les_avis(self):
        from communications import avis
        Client.objects.filter(pk=self.a1.client_id).update(saisons="ete")
        self.assertNotIn(self.a1, list(arrets(self.ent)))
        Client.objects.filter(pk=self.a2.client_id).update(saisons="les_deux")
        self.assertIn(self.a2, list(arrets(self.ent)))
        self.assertNotIn(self.a1.client, list(avis.clients_a_aviser_au_debut(self.ent)))
        page = self.client.get(f"/clients/{self.a1.client_id}/")
        self.assertContains(page, "été seulement")
        self.assertContains(page, 'value="paysagement"')
