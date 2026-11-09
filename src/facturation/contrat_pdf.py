"""Contrat de la saison en PDF (PRD B6), refait à chaque demande comme les factures.
Les notes internes du contrat n'y paraissent jamais; « l'entente en mots » (ce qui a été dit au client), oui."""
from django.template.loader import render_to_string
from django.utils import timezone

from core import telephone
from facturation.calculs import taxes
from facturation.models import Contrat

ZERO = 0


def contexte(c):
    ent = c.entreprise
    inscrit = ent.inscrit_taxes

    def avec_taxes(montant):
        if not inscrit:
            return montant, 0, 0
        tps, tvq = taxes(montant, ent.taux_tps, ent.taux_tvq)
        return montant + tps + tvq, tps, tvq

    total, tps, tvq = avec_taxes(c.prix)
    versements = [{"v": v, "total": avec_taxes(v.montant)[0]} for v in c.versements.all()]
    a = c.adresse or c.client.adresses.filter(active=True).first()
    return {"c": c, "ent": ent, "client": c.client, "adresse": a, "inscrit": inscrit, "tps": tps, "tvq": tvq, "total": total,
            "versements": versements, "services": list(c.services.all()), "date": timezone.localdate(),
            "telephone_affiche": telephone.afficher(ent.telephone), "au_passage": c.type == Contrat.Type.AU_PASSAGE}


def html(c):
    return render_to_string("facturation/contrat_pdf.html", contexte(c))


def rendre(c):
    from weasyprint import HTML

    return HTML(string=html(c)).write_pdf()


def nom_fichier(c):
    return f"contrat-{c.saison.nom}-{c.pk}.pdf"
