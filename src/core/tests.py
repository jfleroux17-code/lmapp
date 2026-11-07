from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings

from core.middleware import IPReelleMiddleware

CADDY = "172.20.0.250"


def _ip_vue(remote_addr, xff=None):
    entetes = {"REMOTE_ADDR": remote_addr}
    if xff is not None:
        entetes["HTTP_X_FORWARDED_FOR"] = xff
    requete = RequestFactory().get("/", **entetes)
    vue = {}

    def reponse(r):
        vue["ip"] = r.META["REMOTE_ADDR"]
        return HttpResponse()

    IPReelleMiddleware(reponse)(requete)
    return vue["ip"]


@override_settings(LMAPP_PROXIES_DE_CONFIANCE=[CADDY])
class IPReelleTests(SimpleTestCase):
    def test_ip_reelle_venant_de_caddy(self):
        self.assertEqual(_ip_vue(CADDY, "203.0.113.7"), "203.0.113.7")

    def test_derniere_valeur_seulement(self):
        # Une valeur inventée par le visiteur, puis celle ajoutée par Caddy
        self.assertEqual(_ip_vue(CADDY, "1.2.3.4, 203.0.113.7"), "203.0.113.7")

    def test_en_tete_ignore_si_pas_caddy(self):
        # L'app de test (ou n'importe qui d'autre) ne peut pas fausser l'IP
        self.assertEqual(_ip_vue("172.20.0.4", "203.0.113.7"), "172.20.0.4")

    def test_valeur_invalide(self):
        self.assertEqual(_ip_vue(CADDY, "pas-une-ip"), CADDY)

    def test_sans_en_tete(self):
        self.assertEqual(_ip_vue(CADDY), CADDY)

    def test_ipv6(self):
        self.assertEqual(_ip_vue(CADDY, "2001:db8::1"), "2001:db8::1")
