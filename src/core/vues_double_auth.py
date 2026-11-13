"""Écrans de la double authentification (core/double_auth.py) : code à la connexion, activation, codes de secours.
Mêmes écrans sur le sous-domaine d'un déneigeur et sur l'administration (sous /admin/, seule partie que Caddy laisse
passer sur admin.ledeneigeur.com)."""
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme

from core import double_auth as da
from core.models import DoubleAuthentification


def cote_admin(request):
    hote = getattr(settings, "LMAPP_HOTE_ADMIN", "")
    return request.path.startswith("/admin") or bool(hote and request.get_host().split(":")[0] == hote)


def url_code(request):
    return reverse("da_code_admin" if cote_admin(request) else "da_code")


def url_activer(request):
    return reverse("da_activer_admin" if cote_admin(request) else "da_activer")


def _suivant(request, defaut):
    s = request.POST.get("suivant") or request.GET.get("suivant") or ""
    if s.startswith("/") and url_has_allowed_host_and_scheme(s, allowed_hosts={request.get_host()}):
        return s
    return defaut


def _accueil(request):
    return "/admin/" if cote_admin(request) else "/"


def _rendre(request, **contexte):
    contexte.setdefault("admin", cote_admin(request))
    return render(request, "core/double_auth.html", contexte)


@login_required
def code(request):
    """Le code à 6 chiffres après le mot de passe (ou un code de secours)."""
    if not request.session.get(da.SESSION_ATTENTE):
        return redirect(_suivant(request, _accueil(request)))
    if request.method == "POST":
        with transaction.atomic():
            bon = da.verifier(request.user, request.POST.get("code", ""))
        if bon:
            request.session.pop(da.SESSION_ATTENTE, None)
            request.session.pop(da.SESSION_ESSAIS, None)
            request.session.cycle_key()
            return redirect(_suivant(request, _accueil(request)))
        essais = request.session.get(da.SESSION_ESSAIS, 0) + 1
        request.session[da.SESSION_ESSAIS] = essais
        if essais >= da.ESSAIS_MAX:
            logout(request)
            messages.error(request, "Trop de codes faux : reconnecte-toi avec ton mot de passe.")
            return redirect("/admin/login/" if cote_admin(request) else reverse("terrain:connexion"))
        messages.error(request, f"Code refusé. Prends le code affiché en ce moment dans Google Authenticator ({da.ESSAIS_MAX - essais} essai{'s' if da.ESSAIS_MAX - essais > 1 else ''} restant{'s' if da.ESSAIS_MAX - essais > 1 else ''}).")
    return _rendre(request, etape="code", suivant=_suivant(request, ""))


@login_required
def activer(request):
    """Activer (ou refaire, nouveau téléphone), voir l'état, nouveaux codes de secours, désactiver si permis."""
    if request.session.get(da.SESSION_ATTENTE):
        return redirect(url_code(request))
    user = request.user
    existante = DoubleAuthentification.objects.filter(utilisateur=user).first()
    obligatoire = da.obligatoire(user)
    action = request.POST.get("action") if request.method == "POST" else request.GET.get("action")

    if request.method == "POST" and action == "desactiver" and existante and not obligatoire:
        existante.delete()
        messages.success(request, "Double authentification désactivée.")
        return redirect(url_activer(request))

    if request.method == "POST" and action == "codes" and existante:
        with transaction.atomic():
            bon = da.verifier(user, request.POST.get("code", ""))
            if bon:
                codes, empreintes = da.nouveaux_codes_secours()
                DoubleAuthentification.objects.filter(pk=existante.pk).update(codes_secours=empreintes)
        if bon:
            return _rendre(request, etape="codes", codes=codes, suite=_accueil(request))
        messages.error(request, "Code refusé.")
        return redirect(url_activer(request))

    if existante and action != "refaire" and not (request.method == "POST" and action == "confirmer"):
        return _rendre(request, etape="etat", da_obj=existante, obligatoire=obligatoire,
                       restants=len(existante.codes_secours), suite=_accueil(request))

    secret = request.session.get(da.SESSION_SECRET_PROPOSE)
    if not secret or (request.method == "GET"):
        secret = da.nouveau_secret()
        request.session[da.SESSION_SECRET_PROPOSE] = secret
    if request.method == "POST" and action == "confirmer":
        pas = da.verifier_code(secret, request.POST.get("code", ""))
        if pas is not None:
            codes, empreintes = da.nouveaux_codes_secours()
            DoubleAuthentification.objects.update_or_create(utilisateur=user, defaults={
                "secret": secret, "dernier_pas": pas, "codes_secours": empreintes, "active_le": timezone.now()})
            request.session.pop(da.SESSION_SECRET_PROPOSE, None)
            request.session["double_auth_ok"] = True
            return _rendre(request, etape="codes", codes=codes, suite=_suivant(request, _accueil(request)), nouvelle=True)
        messages.error(request, "Code refusé : vérifie que c'est bien le compte « Le Déneigeur » ajouté à l'instant, puis tape le code affiché.")
    lien = da.lien_otpauth(secret, user)
    return _rendre(request, etape="activer", lien=lien, qr=da.qr_svg(lien), secret=" ".join(secret[i:i + 4] for i in range(0, len(secret), 4)),
                   obligatoire=obligatoire, refaire=bool(existante), suivant=_suivant(request, ""))
