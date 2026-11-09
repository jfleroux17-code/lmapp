"""Photos jointes à un texto (E14), vues par le client sans compte, par lien secret (comme la facture, L1)."""
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render

from communications import photos
from communications.models import Message
from core.telephone import afficher


def _prive(r):
    r["Cache-Control"] = "private, no-store"
    r["X-Robots-Tag"] = "noindex, nofollow"
    r["Referrer-Policy"] = "no-referrer"
    return r


def _message(request, jeton):
    """Message sortant de l'entreprise du domaine, par son jeton. Autre domaine ou jeton inconnu : 404."""
    if request.entreprise is None:
        raise Http404
    return get_object_or_404(Message.objects.select_related("entreprise"), jeton=jeton, entreprise=request.entreprise,
                             sens=Message.Sens.SORTANT)


def page(request, jeton):
    m = _message(request, jeton)
    images = [(i, legende) for i, (_, legende) in enumerate(photos.jointes(m), start=1)]
    if not images:
        raise Http404
    return _prive(render(request, "communications/photos_publiques.html", {"m": m, "ent": m.entreprise, "images": images,
                                                                                  "telephone": afficher(m.entreprise.telephone)}))


def image(request, jeton, n):
    m = _message(request, jeton)
    liste = photos.jointes(m)
    if not 1 <= n <= len(liste):
        raise Http404
    p = liste[n - 1][0]
    return _prive(HttpResponse(bytes(p.image), content_type=p.type_mime))
