"""Trop-perçu (PRD D7) : le surplus d'un paiement devient un crédit au compte du client, appliqué tout de suite à
ses autres factures dues (la plus vieille d'abord), puis à chaque nouvelle facture émise. Jamais d'argent rendu ni
de solde négatif sur une facture."""
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum

from facturation.models import ZERO, Credit, Facture, Paiement


def credit_restant(client):
    total = client.credits.aggregate(s=Sum("montant"))["s"] or ZERO
    utilise = Paiement.objects.filter(credit__client=client).aggregate(s=Sum("montant"))["s"] or ZERO
    return total - utilise


def appliquer(client):
    """Applique les crédits disponibles aux factures dues du client. Retourne les paiements créés."""
    crees = []
    with transaction.atomic():
        credits = [c for c in Credit.objects.select_for_update().filter(client=client).order_by("date", "pk") if c.restant > 0]
        if not credits:
            return crees
        for f in Facture.objects.filter(client=client).a_recevoir().order_by("date_facture", "pk"):
            du = f.solde_du
            for c in credits:
                if du <= 0:
                    break
                r = c.restant
                if r <= 0:
                    continue
                part = min(r, du)
                crees.append(Paiement.objects.create(entreprise=f.entreprise, facture=f, montant=part, mode=Paiement.Mode.CREDIT,
                                                     credit=c, note="Crédit au compte (trop-perçu)"))
                du -= part
    return crees


def encaisser(facture, montant, mode, reference="", date=None, surplus_permis=False):
    """Paiement reçu pour une facture. Au-delà du solde : refusé, sauf `surplus_permis` (le surplus devient un crédit,
    appliqué aussitôt aux autres factures dues). Retourne (paiement ou None, crédit ou None)."""
    from django.core.exceptions import ValidationError
    from django.utils import timezone

    date = date or timezone.localdate()
    with transaction.atomic():
        f = Facture.objects.select_for_update().get(pk=facture.pk)
        solde = f.solde
        surplus = Decimal(montant) - max(solde, ZERO)
        if surplus > 0 and not surplus_permis:
            raise ValidationError(f"Plus que le solde de la facture ({solde} $). Cocher « Garder le surplus en crédit » si c'est voulu.")
        p = None
        if solde > 0:
            p = Paiement(entreprise=f.entreprise, facture=f, montant=min(Decimal(montant), solde), mode=mode, reference=reference, date=date)
            p.full_clean()
            p.save()
        c = None
        if surplus > 0:
            c = Credit.objects.create(entreprise=f.entreprise, client=f.client, montant=surplus, mode=mode, reference=reference,
                                      date=date, paiement=p, note=f"Surplus du paiement de la facture n° {f.numero or f.pk}")
            appliquer(f.client)
    return p, c


def encaisse(entreprise, **periode):
    """Argent vraiment reçu sur une période : paiements (sans les crédits appliqués) plus les surplus gardés en crédit."""
    p = (Paiement.objects.filter(entreprise=entreprise, **periode).exclude(mode=Paiement.Mode.CREDIT)
         .aggregate(s=Sum("montant"))["s"] or ZERO)
    return p + (Credit.objects.filter(entreprise=entreprise, **periode).aggregate(s=Sum("montant"))["s"] or ZERO)
