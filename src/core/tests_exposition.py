"""Exposition à Internet (avant l'ouverture du 443 à tous) : chaque route de l'app est vérifiée en visiteur anonyme.

La liste des routes vient de Django lui-même : une route ajoutée plus tard est vérifiée automatiquement.
Seules les routes de CHEMINS_PUBLICS répondent sans compte; toutes les autres doivent renvoyer à la connexion
(302 vers /connexion/), refuser (403, 405) ou ne rien trouver (404), en GET comme en POST.
"""
import re

from django.test import TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver

from core.models import Entreprise

HOTE = "louis.exemple.test"

# Nom de la route : pourquoi elle répond sans compte.
CHEMINS_PUBLICS = {
    "sante": "vérification de santé, répond seulement {app, base}",
    "terrain:connexion": "page de connexion (essais limités, core.connexions)",
    "terrain:deconnexion": "déconnexion (POST seulement)",
    "terrain:manifeste": "manifeste de la PWA (nom de l'entreprise)",
    "terrain:favicon": "icône",
    "terrain:service_worker": "service worker (aucune donnée)",
    "facturation:publique": "facture vue par le client, par lien secret de 192 bits (L1)",
    "facturation:publique_pdf": "PDF de la même facture, même lien secret",
    "facturation:contrat_public": "contrat de la saison en PDF, par lien secret de 192 bits (B6)",
    "photos_message": "photos jointes à un texto, par lien secret de 192 bits (E14), message sortant de l'entreprise du domaine",
    "photo_message": "une image de la même page, même lien secret",
    "twilio_texto": "webhook de Twilio : signature X-Twilio-Signature obligatoire, sinon 403",
    "twilio_statut": "webhook de Twilio : signature X-Twilio-Signature obligatoire, sinon 403",
}


def routes(motifs=None, prefixe="", espace=""):
    """(nom complet, chemin d'essai) de chaque route, sauf l'administration (vérifiée à part)."""
    for m in motifs if motifs is not None else get_resolver().url_patterns:
        bout = str(m.pattern)
        if isinstance(m, URLResolver):
            if m.namespace == "admin" or bout.startswith("admin/"):
                continue
            yield from routes(m.url_patterns, prefixe + bout, f"{espace}{m.namespace}:" if m.namespace else espace)
        elif isinstance(m, URLPattern) and m.name:
            if bout.startswith("admin/"):
                continue
            chemin = re.sub(r"<int:[^>]+>", "1", prefixe + bout)
            chemin = re.sub(r"<(str:)?[^>]+>", "essai", chemin)
            yield espace + m.name, "/" + chemin


@override_settings(ALLOWED_HOSTS=["*"], TWILIO_AUTH_TOKEN="jeton-secret")
class ExpositionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        Entreprise.objects.create(nom="Essai", slug="essai", domaine=HOTE)

    def test_toutes_les_routes_privees_refusent_un_anonyme(self):
        vues = list(routes())
        self.assertGreater(len(vues), 50)
        for nom, chemin in vues:
            if nom in CHEMINS_PUBLICS:
                continue
            for methode in ("get", "post"):
                with self.subTest(route=nom, chemin=chemin, methode=methode):
                    r = getattr(self.client, methode)(chemin, HTTP_HOST=HOTE)
                    if r.status_code == 302:
                        self.assertTrue(r["Location"].startswith("/connexion/"), r["Location"])
                    else:
                        self.assertIn(r.status_code, (403, 404, 405))

    def test_la_liste_des_publics_est_a_jour(self):
        noms = {n for n, _ in routes()}
        self.assertEqual(set(CHEMINS_PUBLICS) - noms, set(), "route publique disparue : retirer de CHEMINS_PUBLICS")

    def test_webhooks_sans_signature_valide_refuses(self):
        from communications.models import Message
        for chemin in ("/webhooks/twilio/textos/", "/webhooks/twilio/statut/"):
            donnees = {"MessageSid": "SM" + "0" * 32, "From": "+15145550123", "To": "+14503001166", "Body": "Allo", "MessageStatus": "failed"}
            with self.subTest(chemin=chemin):
                self.assertEqual(self.client.post(chemin, donnees, HTTP_HOST=HOTE).status_code, 403)  # sans en-tête
                self.assertEqual(self.client.post(chemin, donnees, HTTP_HOST=HOTE, HTTP_X_TWILIO_SIGNATURE="fausse").status_code, 403)
                self.assertEqual(self.client.post(chemin, donnees, HTTP_HOST=HOTE, HTTP_X_TWILIO_SIGNATURE="").status_code, 403)
                self.assertIn(self.client.get(chemin, HTTP_HOST=HOTE).status_code, (403, 405))
        self.assertFalse(Message.objects.exists())

    def test_webhook_refuse_si_le_jeton_manque(self):
        with override_settings(TWILIO_AUTH_TOKEN=""):
            r = self.client.post("/webhooks/twilio/textos/", {"Body": "x"}, HTTP_HOST=HOTE, HTTP_X_TWILIO_SIGNATURE="x")
        self.assertEqual(r.status_code, 403)

    def test_facture_publique_jeton_inconnu(self):
        self.assertEqual(self.client.get("/f/devine/", HTTP_HOST=HOTE).status_code, 404)

    def test_sante_ne_dit_rien_de_plus(self):
        r = self.client.get("/sante/", HTTP_HOST=HOTE)
        self.assertEqual(r.json(), {"app": "ok", "base": "ok"})

    def test_administration_anonyme_et_adresse_neutre(self):
        r = self.client.get("/admin/", HTTP_HOST=HOTE)
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith("/admin/login/"))
        with override_settings(LMAPP_HOTE_ADMIN="admin.exemple.test"):
            self.assertEqual(self.client.get("/admin/", HTTP_HOST=HOTE).status_code, 404)
            self.assertEqual(self.client.get("/admin/login/", HTTP_HOST=HOTE).status_code, 404)

    def test_domaine_inconnu(self):
        r = self.client.get("/", HTTP_HOST="inconnu.exemple.test")
        self.assertIn(r.status_code, (302, 404))
