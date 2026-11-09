"""Écrans de terrain de Louis : recherche de clients et fiche client (PRD A8, F6).

Mobile d'abord, une main, des gants. Tout est filtré par request.entreprise
(l'entreprise du domaine) : un client d'une autre entreprise donne une 404.
"""
import re
from urllib.parse import quote

from django.conf import settings
from django.contrib.auth import views as auth_views
from django.db.models import F, Min, Prefetch, Q
from django.shortcuts import get_object_or_404, render

from clients.models import Adresse, Client
from core.acces import membre_requis, peut_ecrire, peut_modifier_clients
from core import telephone
from terrain.argent import resume_client
from tournee.models import Passage

MAX_RESULTATS = 50


class Connexion(auth_views.LoginView):
    template_name = "terrain/connexion.html"
    redirect_authenticated_user = True

    def form_invalid(self, form):
        # core.connexions marque la requête quand le refus vient d'un blocage
        bloquee = getattr(self.request, "connexion_bloquee", False)
        return self.render_to_response(self.get_context_data(form=form, bloquee=bloquee, fenetre_min=settings.LMAPP_CONNEXION_FENETRE_MIN), status=429 if bloquee else 200)


def _recherche(entreprise, q):
    qs = Client.objects.filter(entreprise=entreprise).prefetch_related(
        Prefetch("adresses", queryset=Adresse.objects.filter(active=True).select_related("secteur").order_by("secteur__ordre", "ordre_tournee"))
    )
    q = (q or "").strip()
    if not q:
        # Sans recherche : clients servis (actifs et en recouvrement), dans l'ordre de la tournée.
        # Inactifs et liste noire : seulement par la recherche.
        # (trié sur le premier arrêt de chaque client : un client à deux adresses n'apparaît qu'une fois)
        return (qs.filter(statut__in=[Client.Statut.ACTIF, Client.Statut.RECOUVREMENT])
                .annotate(o_secteur=Min("adresses__secteur__ordre"), o_rang=Min("adresses__ordre_tournee"))
                .order_by(F("o_secteur").asc(nulls_last=True), F("o_rang").asc(nulls_last=True), "nom")[:MAX_RESULTATS], False)
    filtre = Q()
    for mot in q.split():
        f = (Q(nom__unaccent__icontains=mot) | Q(prenom__unaccent__icontains=mot)
             | Q(organisation__unaccent__icontains=mot)
             | Q(adresses__ligne1__unaccent__icontains=mot) | Q(courriel__icontains=mot))
        chiffres = re.sub(r"\D", "", mot)
        if len(chiffres) >= 3:
            f |= Q(cellulaire__contains=chiffres) | Q(telephone_autre__contains=chiffres)
        filtre &= f
    resultats = qs.filter(filtre).order_by("nom", "prenom").distinct()
    return resultats[:MAX_RESULTATS], True


@membre_requis
def accueil(request):
    clients, recherche = _recherche(request.entreprise, request.GET.get("q"))
    contexte = {"clients": clients, "q": request.GET.get("q", ""), "recherche": recherche,
                "modifier_clients": peut_modifier_clients(request)}
    # HTMX : seulement la liste, pendant la frappe
    gabarit = "terrain/_resultats.html" if request.headers.get("HX-Request") else "terrain/accueil.html"
    return render(request, gabarit, contexte)


def _liens_navigation(adresse):
    """Boutons Apple Plans, Google Maps et Waze (F6). Position précise si on l'a, sinon l'adresse."""
    texte = f"{adresse.ligne1}, {adresse.ville}, {adresse.province}"
    if adresse.position is not None and not adresse.position_a_verifier:
        lat, lon = f"{adresse.latitude:.6f}", f"{adresse.longitude:.6f}"
        return [
            ("Apple Plans", f"https://maps.apple.com/?daddr={lat},{lon}&dirflg=d"),
            ("Google Maps", f"https://www.google.com/maps/dir/?api=1&destination={lat},{lon}&travelmode=driving"),
            ("Waze", f"https://waze.com/ul?ll={lat},{lon}&navigate=yes"),
        ]
    t = quote(texte)
    return [
        ("Apple Plans", f"https://maps.apple.com/?daddr={t}&dirflg=d"),
        ("Google Maps", f"https://www.google.com/maps/dir/?api=1&destination={t}&travelmode=driving"),
        ("Waze", f"https://waze.com/ul?q={t}&navigate=yes"),
    ]


def _passages_avec_photos(client):
    """Dix derniers passages, chacun avec ses photos (F7) : sans les octets, avec « avant » ou « après »."""
    from tournee.models import PhotoPassage

    passages = list(Passage.objects.filter(adresse__client=client).select_related("operation", "adresse").order_by("-heure")[:10])
    cles = {(p.operation_id, p.adresse_id): p for p in passages}
    for p in passages:
        p.photos = []
    photos = PhotoPassage.objects.filter(operation_id__in={k[0] for k in cles}, adresse__client=client).only(
        "pk", "prise_le", "operation_id", "adresse_id")
    for ph in photos:
        p = cles.get((ph.operation_id, ph.adresse_id))
        if p is not None:
            ph.quand = ph.moment(p)
            p.photos.append(ph)
    return passages


@membre_requis
def fiche(request, pk):
    client = get_object_or_404(Client, pk=pk, entreprise=request.entreprise)
    adresses = [
        {"objet": a, "navigation": _liens_navigation(a), "photos": list(a.photos.only("pk", "cree_le", "adresse_id"))}  # sans les octets
        for a in client.adresses.filter(active=True).select_related("secteur").order_by("secteur__ordre", "ordre_tournee")
    ]
    contexte = {
        "client": client,
        "adresses": adresses,
        "cellulaire": telephone.afficher(client.cellulaire),
        "autre_telephone": telephone.afficher(client.telephone_autre),
        "ecriture": peut_ecrire(request),
        "modifier_clients": peut_modifier_clients(request),
        "passages": _passages_avec_photos(client),
        "messages_client": client.messages.order_by("-cree_le")[:10],
        "demandes_client": client.demandes.order_by("statut", "-cree_le")[:10],
        **resume_client(client),
    }
    return render(request, "terrain/fiche.html", contexte)


def manifeste(request):
    """Manifeste de la PWA : l'app s'installe sur l'écran d'accueil (PRD 6.3, 6.5).
    Le nom vient de l'entreprise du domaine, jamais du code."""
    from django.http import JsonResponse
    from django.templatetags.static import static

    nom = request.entreprise.nom if request.entreprise else "LMAPP"
    reponse = JsonResponse({
        "name": nom,
        "short_name": nom if len(nom) <= 12 else "Déneigement",
        "lang": "fr-CA",
        "start_url": "/",
        "scope": "/",
        "display": "standalone",
        "background_color": "#000000",
        "theme_color": "#000000",
        "icons": [
            {"src": static("icones/icone-192.png"), "sizes": "192x192", "type": "image/png"},
            {"src": static("icones/icone-512.png"), "sizes": "512x512", "type": "image/png"},
            {"src": static("icones/icone-512-maskable.png"), "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
            {"src": static("icones/icone.svg"), "sizes": "any", "type": "image/svg+xml"},
        ],
    }, json_dumps_params={"ensure_ascii": False})
    reponse["Content-Type"] = "application/manifest+json"
    return reponse


def favicon(request):
    """Les navigateurs demandent /favicon.ico d'eux-mêmes : renvoyer vers l'icône."""
    from django.shortcuts import redirect
    from django.templatetags.static import static

    return redirect(static("icones/icone-192.png"), permanent=True)


def service_worker(request):
    """Service worker à la racine (portée « / ») : cache de l'app pour le mode hors ligne (F10).
    La version suit le CSS compilé : un nouveau déploiement remplace le cache des fichiers statiques."""
    import json

    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from django.templatetags.static import static

    fichiers = ["css/app.css", "vendor/htmx-2.0.11.min.js", "vendor/alpine-3.17.5.min.js", "terrain/tournee.js",
                "icones/icone-192.png", "icones/icone-180.png", "icones/icone.svg"]
    urls = [static(f) for f in fichiers]
    import hashlib

    version = hashlib.sha256(json.dumps(urls).encode()).hexdigest()[:12]  # change quand un fichier change (noms à empreinte)
    corps = render_to_string("terrain/sw.js", {"version": version, "prechargement": json.dumps(urls)})
    r = HttpResponse(corps, content_type="application/javascript; charset=utf-8")
    r["Cache-Control"] = "no-cache"
    r["Service-Worker-Allowed"] = "/"
    return r


@membre_requis
def abonner_notifications(request):
    """E8 : le cellulaire s'abonne (POST JSON du navigateur : endpoint et clés) ou se désabonne (DELETE)."""
    import json

    from django.http import HttpResponseBadRequest, JsonResponse

    from core.models import AbonnementNotification

    try:
        d = json.loads(request.body or b"{}")
        endpoint = d["endpoint"]
    except (ValueError, KeyError):
        return HttpResponseBadRequest("Abonnement illisible.")
    if request.method == "DELETE":
        AbonnementNotification.objects.filter(endpoint=endpoint, utilisateur=request.user).delete()
        return JsonResponse({"ok": True})
    if request.method != "POST" or not endpoint.startswith("https://"):
        return HttpResponseBadRequest("Abonnement illisible.")
    try:
        cles = d["keys"]
        AbonnementNotification.objects.update_or_create(endpoint=endpoint[:1000], defaults={
            "utilisateur": request.user, "entreprise": request.entreprise, "p256dh": cles["p256dh"][:200], "auth": cles["auth"][:100],
            "appareil": request.headers.get("User-Agent", "")[:200]})
    except (KeyError, TypeError):
        return HttpResponseBadRequest("Abonnement illisible.")
    return JsonResponse({"ok": True})
