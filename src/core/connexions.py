"""Limitation des essais de connexion (PRD 6.1.1), pour l'ouverture du 443 à tout Internet.

Deux compteurs d'échecs, sur une fenêtre glissante :
  - par IP réelle (core.middleware.IPReelleMiddleware) : un attaquant qui essaie
    plusieurs comptes;
  - par nom d'utilisateur : un attaquant qui change d'IP.
Le blocage est toujours temporaire (jamais de compte verrouillé pour de bon :
Louis doit pouvoir entrer en pleine tempête). Pendant un blocage, même le bon mot
de passe est refusé, et les essais refusés ne sont pas comptés : le blocage finit
donc au plus tard une fenêtre après le dernier échec compté. Une connexion
réussie efface les échecs de ce nom d'utilisateur.

Passe par le module d'authentification : couvre /connexion/ et /admin/.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.core.exceptions import PermissionDenied
from django.dispatch import receiver
from django.utils import timezone

journal = logging.getLogger("lmapp.connexions")
GARDER = timedelta(hours=24)


def _ip(request):
    return request.META.get("REMOTE_ADDR") if request is not None else None


def _nom(valeur):
    return (valeur or "").strip().lower()[:150]


def _fenetre():
    return timezone.now() - timedelta(minutes=settings.LMAPP_CONNEXION_FENETRE_MIN)


def bloque(ip, nom):
    """Vrai si cette IP ou ce nom d'utilisateur a trop d'échecs récents."""
    from core.models import EchecConnexion

    recents = EchecConnexion.objects.filter(moment__gte=_fenetre())
    if ip and recents.filter(ip=ip).count() >= settings.LMAPP_CONNEXION_MAX_IP:
        return True
    return bool(nom) and recents.filter(nom_utilisateur=nom).count() >= settings.LMAPP_CONNEXION_MAX_COMPTE


class AuthentificationLimitee(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get("username")
        ip, nom = _ip(request), _nom(username)
        if bloque(ip, nom):
            if request is not None:
                request.connexion_bloquee = True
            journal.warning("connexion bloquée (trop d'essais) : utilisateur=%r ip=%s", nom, ip)
            raise PermissionDenied  # arrête l'authentification, même avec le bon mot de passe
        return super().authenticate(request, username=username, password=password, **kwargs)


@receiver(user_login_failed)
def noter_echec(sender, credentials, request=None, **kwargs):
    from core.models import EchecConnexion

    if getattr(request, "connexion_bloquee", False):
        return  # refusé pendant un blocage : pas compté
    ip, nom = _ip(request), _nom(credentials.get("username"))
    EchecConnexion.objects.create(ip=ip, nom_utilisateur=nom)
    EchecConnexion.objects.filter(moment__lt=timezone.now() - GARDER).delete()
    journal.info("échec de connexion : utilisateur=%r ip=%s", nom, ip)


@receiver(user_logged_in)
def effacer_echecs(sender, user, request=None, **kwargs):
    from core.models import EchecConnexion

    EchecConnexion.objects.filter(nom_utilisateur=_nom(user.get_username())).delete()
