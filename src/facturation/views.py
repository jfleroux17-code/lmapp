from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from core.acces import membre_requis
from facturation import pdf
from facturation.models import Facture


@membre_requis
def facture_pdf(request, pk):
    """PDF d'une facture de l'entreprise du domaine (une facture d'une autre entreprise donne une 404)."""
    f = get_object_or_404(Facture.objects.select_related("entreprise", "client", "adresse", "contrat__saison"),
                          pk=pk, entreprise=request.entreprise)
    r = HttpResponse(pdf.rendre(f), content_type="application/pdf")
    r["Content-Disposition"] = f'inline; filename="{pdf.nom_fichier(f)}"'
    r["Cache-Control"] = "private, no-store"
    return r
