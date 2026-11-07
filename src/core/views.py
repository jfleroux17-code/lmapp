from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render


def accueil(request):
    """Page temporaire : confirme que l'app répond."""
    return render(request, "core/accueil.html")


def sante(request):
    """Vérification de santé pour Docker et la surveillance : l'app et la base répondent."""
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        return JsonResponse({"app": "ok", "base": "ok"})
    except Exception:
        return JsonResponse({"app": "ok", "base": "erreur"}, status=503)
