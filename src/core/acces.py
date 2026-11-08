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


def peut_ecrire(request):
    """Rôles administrateur et opérateur (et superutilisateur) : oui; lecture seule : non (K2)."""
    u = request.user
    if u.is_superuser:
        return True
    return Membre.objects.filter(utilisateur=u, entreprise=request.entreprise).exclude(role=Membre.Role.LECTURE).exists()


def ecriture_requise(vue):
    """Pour les actions qui changent quelque chose (POST) : refusé au rôle lecture seule."""
    @membre_requis
    @wraps(vue)
    def enveloppe(request, *args, **kwargs):
        if not peut_ecrire(request):
            return render(request, "terrain/refuse.html", {"message": "Ton compte est en lecture seule : tu peux consulter, pas modifier."}, status=403)
        return vue(request, *args, **kwargs)

    return enveloppe


def peut_modifier_clients(request):
    """A12, K9 : déneigeur seul, quiconque peut écrire; équipe, seulement les administrateurs de l'entreprise."""
    u = request.user
    if u.is_superuser:
        return True
    membre = Membre.objects.filter(utilisateur=u, entreprise=request.entreprise).first()
    if membre is None or membre.role == Membre.Role.LECTURE:
        return False
    return request.entreprise.mode == request.entreprise.Mode.SEUL or membre.role == Membre.Role.ADMINISTRATEUR


def modification_clients_requise(vue):
    @membre_requis
    @wraps(vue)
    def enveloppe(request, *args, **kwargs):
        if not peut_modifier_clients(request):
            return render(request, "terrain/refuse.html",
                          {"message": "Dans cette entreprise, seuls les administrateurs modifient les clients."}, status=403)
        return vue(request, *args, **kwargs)

    return enveloppe
