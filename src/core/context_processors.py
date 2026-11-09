from django.conf import settings


def environnement(request):
    """Rend LMAPP_ENV disponible dans tous les gabarits (bandeau de test)."""
    return {
        "lmapp_env": settings.LMAPP_ENV,
        "est_test": settings.LMAPP_ENV != "prod",
    }


def messages_non_lus(request):
    """Compteur des messages reçus pas encore ouverts (E7), pour l'en-tête des écrans de Louis."""
    ent = getattr(request, "entreprise", None)
    user = getattr(request, "user", None)
    if ent is None or user is None or not user.is_authenticated:
        return {}
    from communications.models import Message
    from demandes.models import Demande
    from facturation.models import VirementInterac

    return {"non_lus": Message.objects.filter(entreprise=ent, sens=Message.Sens.ENTRANT, lu=False).count(),
            "virements_a_confirmer": VirementInterac.objects.filter(entreprise=ent, statut=VirementInterac.Statut.A_TRAITER).count(),
            # Demandes : rouge = pas encore ouvertes (pas réglées), orange = ouvertes mais toujours « Ouverte »
            "demandes_non_lues": Demande.objects.filter(entreprise=ent, vue_le__isnull=True).exclude(statut=Demande.Statut.REGLEE).count(),
            "demandes_a_traiter": Demande.objects.filter(entreprise=ent, vue_le__isnull=False, statut=Demande.Statut.OUVERTE).count()}
