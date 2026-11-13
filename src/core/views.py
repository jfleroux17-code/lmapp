from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import HttpResponse
from django.db import connection
from django.http import JsonResponse


def sante(request):
    """Vérification de santé pour Docker et la surveillance : l'app et la base répondent."""
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        return JsonResponse({"app": "ok", "base": "ok"})
    except Exception:
        return JsonResponse({"app": "ok", "base": "erreur"}, status=503)


@csrf_exempt
@require_POST
def csp_rapport(request):
    """Rapports de la politique de sécurité du contenu (audit, point 6), en mode « rapport seulement » d'abord : le
    navigateur signale ce qu'il aurait bloqué. Rien n'est gardé dans la base : une ligne au journal (docker compose logs
    app | grep csp), assez pour voir s'il faut permettre une source avant d'activer le blocage."""
    import json
    import logging

    if len(request.body) > 10_000:
        return HttpResponse(status=413)
    try:
        d = json.loads(request.body or b"{}")
        r = d.get("csp-report") or (d[0].get("body") if isinstance(d, list) and d else d) or {}
    except (ValueError, AttributeError, IndexError):
        return HttpResponse(status=400)
    champ = lambda *noms: next((str(r.get(n))[:200] for n in noms if r.get(n)), "?")  # noqa: E731
    logging.getLogger("csp").warning("csp : %s bloquerait %s sur %s", champ("violated-directive", "effectiveDirective"),
                                     champ("blocked-uri", "blockedURL"), champ("document-uri", "documentURL"))
    return HttpResponse(status=204)
