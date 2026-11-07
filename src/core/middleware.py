import ipaddress

from django.conf import settings


class IPReelleMiddleware:
    """Remplace REMOTE_ADDR (l'IP de Caddy) par l'IP réelle du visiteur.

    On ne lit X-Forwarded-For que si la requête arrive d'un proxy de confiance
    (LMAPP_PROXIES_DE_CONFIANCE : l'IP fixe de Caddy sur le réseau edge).
    Caddy remplace tout X-Forwarded-For envoyé par le visiteur par l'IP qu'il
    voit; on prend quand même la dernière valeur de la liste, la seule ajoutée
    par Caddy, pour ne jamais croire une valeur fournie par le visiteur.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.proxies = set(settings.LMAPP_PROXIES_DE_CONFIANCE)

    def __call__(self, request):
        meta = request.META
        if meta.get("REMOTE_ADDR") in self.proxies:
            transmis = meta.get("HTTP_X_FORWARDED_FOR", "")
            derniere = transmis.split(",")[-1].strip() if transmis else ""
            try:
                meta["REMOTE_ADDR"] = str(ipaddress.ip_address(derniere))
            except ValueError:
                pass  # en-tête absent ou invalide : on garde l'IP de Caddy
        return self.get_response(request)
