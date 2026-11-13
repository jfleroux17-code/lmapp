"""Sécurité (audit du 13 novembre 2026, points 5 et 9, go de JF).

Point 5 : sessions de 12 heures pour l'administration et les superutilisateurs (90 jours gardés pour le cellulaire de
tournée); « Déconnecter mes autres appareils » dans Plus.
Point 9 : alertes par courriel à JF (LMAPP_ALERTES_COURRIEL, boîte de la plateforme, envoyées par le worker) pour les
gestes rares qui devraient toujours être connus : connexion à l'administration ou d'un superutilisateur, connexion
bloquée après trop d'échecs, double authentification activée ou réinitialisée, nouvel administrateur d'entreprise.
"""
import logging

from django.conf import settings
from django.db import transaction

log = logging.getLogger(__name__)


def alerter(sujet, texte):
    """Courriel d'alerte à JF, par le worker (l'app n'a pas Internet), après la transaction."""
    if not getattr(settings, "LMAPP_ALERTES_SECURITE", True):
        return
    log.warning("alerte de sécurité : %s", sujet)

    def envoyer():
        from core.tasks import alerte_securite

        try:
            alerte_securite.defer(sujet=sujet, texte=texte)
        except Exception as e:  # noqa: BLE001 : une alerte ratée ne doit jamais bloquer une connexion
            log.error("alerte de sécurité pas mise en file : %s", e)

    transaction.on_commit(envoyer)


def _ip(request):
    from core.connexions import _ip as ip

    return ip(request) if request is not None else "?"


def _qui(user):
    nom = user.get_full_name() or user.get_username()
    return f"{nom} ({user.get_username()})" if nom != user.get_username() else nom


def a_la_connexion(sender, request, user, **kwargs):
    """Point 5 (session courte) et point 9 (alerte) pour l'administration et les superutilisateurs."""
    admin = request is not None and request.path.startswith("/admin")
    if user.is_superuser or admin:
        if request is not None and hasattr(request, "session"):
            request.session.set_expiry(settings.LMAPP_SESSION_ADMIN_HEURES * 3600)
        lieu = "à l'administration" if admin else f"à l'app ({request.META.get('HTTP_HOST', '?') if request else '?'})"
        alerter(f"Connexion {lieu} : {user.get_username()}",
                f"Connexion réussie {lieu} : {_qui(user)}, depuis l'adresse IP {_ip(request)}.\n\n"
                "Si ce n'est pas vous : changer le mot de passe tout de suite et réinitialiser la double authentification.")


def blocage(ip, nom, raison):
    alerter(f"Connexion bloquée : {raison}",
            f"Trop d'échecs de connexion ({raison}). Utilisateur essayé : {nom or '?'}; adresse IP : {ip or '?'}.\n"
            f"Blocage temporaire de {settings.LMAPP_CONNEXION_FENETRE_MIN} minutes (core.connexions). "
            "Plusieurs alertes de suite : quelqu'un essaie peut-être de deviner un mot de passe.")


def double_auth_changee(sender, instance, created=False, **kwargs):
    from django.db.models.signals import post_delete

    u = instance.utilisateur
    if kwargs.get("signal") is post_delete:
        alerter(f"Double authentification réinitialisée : {u.get_username()}",
                f"La double authentification de {_qui(u)} a été réinitialisée (téléphone perdu?). "
                "La personne la refera à sa prochaine connexion.")
    elif created:
        alerter(f"Double authentification activée : {u.get_username()}",
                f"{_qui(u)} a activé la double authentification (Google Authenticator).")


def membre_avant(sender, instance, **kwargs):
    instance._role_avant = sender.objects.filter(pk=instance.pk).values_list("role", flat=True).first() if instance.pk else None


def membre_apres(sender, instance, created, **kwargs):
    if instance.role == sender.Role.ADMINISTRATEUR and getattr(instance, "_role_avant", None) != sender.Role.ADMINISTRATEUR:
        alerter(f"Nouvel administrateur : {instance.utilisateur.get_username()} ({instance.entreprise.nom})",
                f"{_qui(instance.utilisateur)} est maintenant administrateur de {instance.entreprise.nom}.")


def brancher():
    from django.contrib.auth.signals import user_logged_in
    from django.db.models.signals import post_delete, post_save, pre_save

    from core.models import DoubleAuthentification, Membre

    user_logged_in.connect(a_la_connexion, dispatch_uid="securite_connexion")
    post_save.connect(double_auth_changee, sender=DoubleAuthentification, dispatch_uid="securite_da_cree")
    post_delete.connect(double_auth_changee, sender=DoubleAuthentification, dispatch_uid="securite_da_efface")
    pre_save.connect(membre_avant, sender=Membre, dispatch_uid="securite_membre_avant")
    post_save.connect(membre_apres, sender=Membre, dispatch_uid="securite_membre_apres")
