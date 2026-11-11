"""E14 : photos jointes aux messages (pièces jointes par courriel, lien secret par texto)."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from clients.models import Adresse, Client, PhotoAdresse
from communications import courriel
from communications.models import Message
from core.models import Entreprise, Membre
from demandes.models import Demande, PhotoDemande
from tournee.models import Operation, PhotoPassage

HOTE = "louis.exemple.test"
JPEG = b"\xff\xd8\xff\xe0" + b"5" * 100


@override_settings(ALLOWED_HOSTS=["*"], LMAPP_ENV="test", LMAPP_DESTINATAIRES_TEST=["client@example.com", "+14505550101"],
                   SMTP_HOTE="smtp.exemple.test", IMAP_UTILISATEUR="louis@exemple.test", IMAP_MOT_DE_PASSE="secret",
                   TWILIO_ACCOUNT_SID="AC-essai", TWILIO_AUTH_TOKEN="jeton")
class PhotosJointesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.ent = Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE, envois_actifs=True, numero_texto="+14503001166",
                                            courriel_reponse="louis@exemple.test", signature_messages="Déneigement Essai")
        cls.c = Client.objects.create(entreprise=cls.ent, nom="Tremblay", cellulaire="+14505550101", courriel="client@example.com")
        cls.a = Adresse.objects.create(entreprise=cls.ent, client=cls.c, ligne1="12, rue des Pins", ville="Sainte-Adèle")
        cls.pa = PhotoAdresse.objects.create(entreprise=cls.ent, adresse=cls.a, image=JPEG, type_mime="image/jpeg", taille=104)
        op = Operation.objects.create(entreprise=cls.ent, fin=timezone.now())
        cls.pp = PhotoPassage.objects.create(entreprise=cls.ent, operation=op, adresse=cls.a, image=JPEG, type_mime="image/jpeg",
                                             taille=104, prise_le=timezone.now() - timedelta(hours=1))
        cls.d = Demande.objects.create(entreprise=cls.ent, client=cls.c, genre="dommage", description="Haie abîmée")
        cls.pd = PhotoDemande.objects.create(entreprise=cls.ent, demande=cls.d, image=JPEG, type_mime="image/jpeg", taille=104)
        autre = Client.objects.create(entreprise=cls.ent, nom="Roy", cellulaire="+14505550102")
        aa = Adresse.objects.create(entreprise=cls.ent, client=autre, ligne1="3, rue B", ville="Sainte-Adèle")
        cls.photo_autre = PhotoAdresse.objects.create(entreprise=cls.ent, adresse=aa, image=JPEG, type_mime="image/jpeg", taille=104)
        cls.louis = get_user_model().objects.create_user("louis", password="x" * 12)
        Membre.objects.create(utilisateur=cls.louis, entreprise=cls.ent, role="operateur")

    def setUp(self):
        mock.patch("communications.tasks.envoyer_message.defer").start()
        self.addCleanup(mock.patch.stopall)
        self.client.defaults["HTTP_HOST"] = HOTE
        self.client.force_login(self.louis)

    def test_courriel_avec_photos_en_pieces_jointes(self):
        r = self.client.get(f"/clients/{self.c.pk}/ecrire/?demande={self.d.pk}")
        self.assertContains(r, f'value="d{self.pd.pk}" x-model="on" @change="photos = $root.querySelectorAll(\'input[name=photo]:checked\').length" checked')  # photos de la demande cochées d'avance
        self.assertContains(r, f'value="p{self.pp.pk}"')
        self.assertNotContains(r, f'value="a{self.photo_autre.pk}"')
        self.client.post(f"/clients/{self.c.pk}/ecrire/", {"canal": "courriel", "texte": "Voici les photos de la haie.",
                                                         "photo": [f"d{self.pd.pk}", f"p{self.pp.pk}"]})
        m = Message.objects.get()
        self.assertIsNone(m.jeton)  # pas de lien pour un courriel
        e = courriel.construire(m)
        pieces = list(e.iter_attachments())
        self.assertEqual([p.get_filename() for p in pieces], ["photo-1.jpg", "photo-2.jpg"])
        self.assertEqual(pieces[0].get_content(), JPEG)
        r = self.client.get(f"/messages/{m.pk}/")
        self.assertContains(r, "2 photos jointes")

    def test_texto_avec_lien_secret(self):
        self.client.post(f"/clients/{self.c.pk}/ecrire/", {"canal": "texto", "texte": "Photo de votre entrée.", "photo": [f"a{self.pa.pk}"]})
        m = Message.objects.get()
        self.assertEqual(len(m.jeton), 32)
        self.assertEqual(m.contenu, f"Photo de votre entrée.\nPhoto : https://{HOTE}/m/{m.jeton}/\n\nDéneigement Essai")
        self.client.logout()
        r = self.client.get(f"/m/{m.jeton}/")
        self.assertContains(r, "Entrée du 12, rue des Pins")
        self.assertEqual(r["Cache-Control"], "private, no-store")
        self.assertEqual(r["X-Robots-Tag"], "noindex, nofollow")
        r = self.client.get(f"/m/{m.jeton}/1/")
        self.assertEqual((r.status_code, r["Content-Type"], r.content), (200, "image/jpeg", JPEG))
        self.assertEqual(self.client.get(f"/m/{m.jeton}/2/").status_code, 404)
        self.assertEqual(self.client.get("/m/inconnu/").status_code, 404)
        self.assertEqual(self.client.get(f"/m/{m.jeton}/", HTTP_HOST="autre.exemple.test").status_code, 404)

    def test_photo_d_un_autre_client_refusee(self):
        r = self.client.post(f"/clients/{self.c.pk}/ecrire/", {"canal": "courriel", "texte": "x", "photo": [f"a{self.photo_autre.pk}"]})
        self.assertContains(r, "Photo introuvable pour ce client.")
        self.assertFalse(Message.objects.exists())  # tout ou rien

    def test_maximum(self):
        r = self.client.post(f"/clients/{self.c.pk}/ecrire/", {"canal": "courriel", "texte": "x", "photo": ["a1", "a2", "a3", "a4", "a5", "a6"]})
        self.assertContains(r, "Au plus 5 photos")
        self.assertFalse(Message.objects.exists())

    def test_photo_effacee_disparait_du_lien(self):
        self.client.post(f"/clients/{self.c.pk}/ecrire/", {"canal": "texto", "texte": "x", "photo": [f"a{self.pa.pk}"]})
        m = Message.objects.get()
        self.pa.delete()
        self.client.logout()
        self.assertEqual(self.client.get(f"/m/{m.jeton}/").status_code, 404)

    def test_effacement_loi_25_retire_le_lien(self):
        from clients.effacement import effacer
        self.client.post(f"/clients/{self.c.pk}/ecrire/", {"canal": "texto", "texte": "x", "photo": [f"p{self.pp.pk}"]})
        jeton = Message.objects.get().jeton
        effacer(self.c)
        self.client.logout()
        self.assertEqual(self.client.get(f"/m/{jeton}/").status_code, 404)

    def test_lien_depuis_le_dossier_de_dommage(self):
        r = self.client.get(f"/demandes/{self.d.pk}/")
        self.assertContains(r, f"/clients/{self.c.pk}/ecrire/?demande={self.d.pk}")
