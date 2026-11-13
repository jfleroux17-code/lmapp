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


class EntrepriseMiddleware:
    """Associe chaque requête à l'entreprise de son domaine (request.entreprise).

    louis.ledeneigeur.com -> l'entreprise dont le champ « domaine » vaut ce nom.
    C'est ce qui isole les déneigeurs les uns des autres (PRD section P).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from core.models import Entreprise

        hote = request.get_host().split(":")[0].lower()
        request.entreprise = Entreprise.objects.filter(domaine=hote, active=True).first()
        return self.get_response(request)


class AdminAdresseNeutreMiddleware:
    """PRD Q6 : avec LMAPP_HOTE_ADMIN (ex. admin.ledeneigeur.com), /admin/ ne répond que sur cette adresse,
    jamais sur le sous-domaine d'un déneigeur; ailleurs, 404 (on ne dit même pas que l'administration existe).
    Vide : /admin/ répond partout (situation d'avant, un seul déneigeur)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings
        from django.http import Http404

        hote = settings.LMAPP_HOTE_ADMIN
        if hote and request.path.startswith("/admin") and request.get_host().split(":")[0] != hote:
            raise Http404
        return self.get_response(request)


class DoubleAuthMiddleware:
    """Double authentification (core/double_auth.py) : une session « en attente » ne voit que l'écran du code;
    un compte pour qui elle est obligatoire et pas encore activée ne voit que l'écran d'activation.
    Vérifié une fois par session (drapeau `double_auth_ok`), pour ne pas interroger la base à chaque page."""

    LIBRES = ("/static/", "/deconnexion/", "/admin/logout/", "/sw.js", "/manifest.webmanifest", "/favicon", "/sante/", "/webhooks/")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from urllib.parse import quote

        from django.shortcuts import redirect

        from core import double_auth as da
        from core import vues_double_auth as vues

        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or request.path.startswith(self.LIBRES):
            return self.get_response(request)
        session = request.session
        if session.get(da.SESSION_ATTENTE):
            cible = vues.url_code(request)
            if request.path != cible:
                return redirect(f"{cible}?suivant={quote(request.get_full_path()) if request.method == 'GET' else ''}")
        elif not session.get("double_auth_ok"):
            if da.obligatoire(user) and not da.active(user):
                cible = vues.url_activer(request)
                if request.path != cible:
                    return redirect(f"{cible}?suivant={quote(request.get_full_path()) if request.method == 'GET' else ''}")
            else:
                session["double_auth_ok"] = True
        return self.get_response(request)
