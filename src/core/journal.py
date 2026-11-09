"""Journal des actions (PRD K4), rempli par les signaux de Django.

Chaque création, modification (champ par champ, avant et après) ou suppression des modèles de SUIVIS est inscrite,
avec l'utilisateur et l'IP de la requête en cours (JournalMiddleware), ou « système » hors requête (worker,
commandes). Limite connue : les mises à jour en bloc (`QuerySet.update()`) ne passent pas par les signaux.
"""
import contextvars
from datetime import date, datetime
from decimal import Decimal

from django.apps import apps
from django.db.models.signals import post_delete, post_save, pre_save

SUIVIS = [
    "core.Entreprise", "core.Membre", "core.VilleDesservie",
    "clients.Secteur", "clients.Client", "clients.Contact", "clients.Adresse", "clients.Balisage", "clients.PhotoAdresse",
    "facturation.Saison", "facturation.Service", "facturation.Contrat", "facturation.Versement", "facturation.Facture",
    "facturation.LigneFacture", "facturation.Paiement", "facturation.Credit", "facturation.VirementInterac",
    "communications.Gabarit", "communications.GabaritParDefaut", "demandes.Demande", "tournee.PhotoPassage",
]
IGNORES = {"cree_le", "modifie_le", "image", "jeton", "password"}

_requete = contextvars.ContextVar("journal_requete", default=None)


class JournalMiddleware:
    """Retient la requête en cours pour savoir qui fait l'action (après AuthenticationMiddleware)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        jeton = _requete.set(request)
        try:
            return self.get_response(request)
        finally:
            _requete.reset(jeton)


def _texte(v):
    if v is None or isinstance(v, (bool, int)):
        return v
    if isinstance(v, (Decimal, date, datetime)):
        return str(v)
    if hasattr(v, "coords"):  # point géographique
        return f"{v.y:.6f}, {v.x:.6f}"
    s = str(v)
    return s if len(s) <= 300 else s[:297] + "..."


def _valeurs(obj):
    return {f.attname: _texte(getattr(obj, f.attname)) for f in obj._meta.concrete_fields if f.attname not in IGNORES}


def _client_id(obj):
    nom = obj._meta.label
    if nom == "clients.Client":
        return obj.pk
    if getattr(obj, "client_id", None):
        return obj.client_id
    for lien in ("adresse", "facture", "contrat"):
        parent = getattr(obj, f"{lien}_id", None) and getattr(obj, lien, None)
        if parent is not None and getattr(parent, "client_id", None):
            return parent.client_id
    return None


def inscrire(obj, action, changements, entreprise_id=None):
    from core.models import JournalAction

    requete = _requete.get()
    user = getattr(requete, "user", None)
    connecte = user is not None and user.is_authenticated
    JournalAction.objects.create(
        entreprise_id=entreprise_id or (obj.pk if obj._meta.label == "core.Entreprise" else getattr(obj, "entreprise_id", None)),
        utilisateur=user if connecte else None, nom_utilisateur=user.get_username() if connecte else "système",
        ip=getattr(requete, "META", {}).get("REMOTE_ADDR") if requete else None,
        action=action, modele=str(obj._meta.verbose_name), objet_id=obj.pk, objet=str(obj)[:200],
        client_id=_client_id(obj), changements=changements)


def _avant(sender, instance, raw=False, **kwargs):
    if raw:
        return
    vieux = sender._default_manager.filter(pk=instance.pk).first() if instance.pk else None
    instance._journal_avant = _valeurs(vieux) if vieux else None


def _apres(sender, instance, created, raw=False, **kwargs):
    from core.models import JournalAction

    if raw:
        return
    apres = _valeurs(instance)
    avant = getattr(instance, "_journal_avant", None)
    if created or avant is None:
        inscrire(instance, JournalAction.Action.CREATION, {k: [None, v] for k, v in apres.items() if v not in (None, "", False)})
    else:
        diff = {k: [avant.get(k), v] for k, v in apres.items() if avant.get(k) != v}
        if diff:
            inscrire(instance, JournalAction.Action.MODIFICATION, diff)
    instance._journal_avant = apres


def _supprime(sender, instance, **kwargs):
    from core.models import JournalAction

    inscrire(instance, JournalAction.Action.SUPPRESSION, {k: [v, None] for k, v in _valeurs(instance).items() if v not in (None, "", False)})


def brancher():
    for nom in SUIVIS:
        m = apps.get_model(nom)
        pre_save.connect(_avant, sender=m, dispatch_uid=f"journal-avant-{nom}")
        post_save.connect(_apres, sender=m, dispatch_uid=f"journal-apres-{nom}")
        post_delete.connect(_supprime, sender=m, dispatch_uid=f"journal-supprime-{nom}")


def effacer_client(client):
    """Loi 25 : les valeurs gardées dans le journal pour ce client sont effacées aussi; une ligne note l'effacement."""
    from core.models import JournalAction

    JournalAction.objects.filter(client_id=client.pk).update(changements={}, objet="[effacé à la demande du client]")
    inscrire(client, JournalAction.Action.EFFACEMENT, {})
