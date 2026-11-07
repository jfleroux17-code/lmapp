"""Accès aux écrans de terrain : connecté, et membre de l'entreprise du domaine."""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from core.models import Membre


def membre_requis(vue):
    @login_required
    @wraps(vue)
    def enveloppe(request, *args, **kwargs):
        if request.entreprise is None:
            return render(request, "terrain/sans_entreprise.html", status=404)
        u = request.user
        if not (u.is_superuser or Membre.objects.filter(utilisateur=u, entreprise=request.entreprise).exists()):
            return render(request, "terrain/refuse.html", status=403)
        return vue(request, *args, **kwargs)

    return enveloppe
