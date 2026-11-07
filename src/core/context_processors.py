from django.conf import settings


def environnement(request):
    """Rend LMAPP_ENV disponible dans tous les gabarits (bandeau de test)."""
    return {
        "lmapp_env": settings.LMAPP_ENV,
        "est_test": settings.LMAPP_ENV != "prod",
    }
