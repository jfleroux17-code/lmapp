from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from core.acces import membre_requis
from facturation import pdf
from facturation.models import Facture

_LIEES = ("entreprise", "client", "adresse", "contrat__saison")


@membre_requis
def facture_pdf(request, pk):
    """PDF d'une facture de l'entreprise du domaine (une facture d'une autre entreprise donne une 404)."""
    f = get_object_or_404(Facture.objects.select_related(*_LIEES), pk=pk, entreprise=request.entreprise)
    return _pdf(f)


def _pdf(f):
    r = HttpResponse(pdf.rendre(f), content_type="application/pdf")
    r["Content-Disposition"] = f'inline; filename="{pdf.nom_fichier(f)}"'
    r["Cache-Control"] = "private, no-store"
    return r


def _prive(r):
    """Page d'un lien secret : jamais gardée en cache partagé, jamais indexée, jeton jamais envoyé ailleurs."""
    r["Cache-Control"] = "private, no-store"
    r["X-Robots-Tag"] = "noindex, nofollow"
    r["Referrer-Policy"] = "no-referrer"
    return r


def _publique(request, jeton):
    """Facture émise ou annulée de l'entreprise du domaine, par son jeton. Brouillon, autre domaine ou jeton inconnu : 404."""
    if request.entreprise is None:
        raise Http404
    return get_object_or_404(Facture.objects.select_related(*_LIEES), jeton=jeton, entreprise=request.entreprise,
                             statut__in=[Facture.Statut.EMISE, Facture.Statut.ANNULEE])


def facture_publique(request, jeton):
    """Facture vue par le client, sans compte (PRD L1). La première ouverture par quelqu'un de non connecté est notée."""
    f = _publique(request, jeton)
    if not request.user.is_authenticated and f.consultee_le is None:
        Facture.objects.filter(pk=f.pk, consultee_le__isnull=True).update(consultee_le=timezone.now())
    ctx = pdf.contexte(f)
    ctx["solde"] = f.solde
    return _prive(render(request, "facturation/publique.html", ctx))


def facture_publique_pdf(request, jeton):
    return _prive(_pdf(_publique(request, jeton)))
