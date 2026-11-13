"""Revenir d'où l'on vient après un enregistrement (analyse de fluidité, accord de JF du 12 novembre 2026).

Le navigateur ajoute à chaque formulaire envoyé un champ caché « retour » : l'écran d'avant celui du formulaire
(pile de la flèche de retour, base.html). Seules les vues qui l'appellent s'en servent; les autres gardent leur suite.
"""
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme


def adresse_retour(request):
    url = (request.POST.get("retour") or "").strip()
    if url.startswith("/") and not url.startswith("//") and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}):
        return url
    return None


def retour_ou(request, *args, **kwargs):
    """redirect() vers l'écran d'origine s'il est connu et sûr, sinon vers la destination habituelle."""
    url = adresse_retour(request)
    return redirect(url) if url else redirect(*args, **kwargs)
