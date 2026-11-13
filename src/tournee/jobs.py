"""Jobs à la pièce (tournee.models.Job) : déneigement manuel, paysagement. Règles et facture."""
from datetime import timedelta
from decimal import ROUND_UP, Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.formats import date_format

from facturation.models import Facture
from tournee.models import Job
from tournee.temps import distance_m

FACTEUR_ROUTE = Decimal("1.3")  # la route n'est pas à vol d'oiseau


def en_cours(entreprise, client=None):
    qs = Job.objects.filter(entreprise=entreprise, fin_le=None)
    return qs.filter(client=client) if client else qs


def noter_position(job, quoi, point):
    """quoi : « depart » ou « arrivee ». La distance est estimée dès qu'on a les deux, ou départ et adresse du client."""
    if quoi == "depart" and job.depart_position is None:
        job.depart_position = point
    elif quoi == "arrivee":
        job.arrivee_position = point
    _distance(job)
    job.save()


def _distance(job):
    a = job.depart_position
    b = job.arrivee_position or (job.adresse.position if job.adresse_id and job.adresse.position else None)
    if a is not None and b is not None:
        km = Decimal(str(distance_m(a.x, a.y, b.x, b.y) / 1000)) * FACTEUR_ROUTE
        job.distance_km = km.quantize(Decimal("0.1"))


def arrivee(job, point=None):
    if job.arrivee_le is None:
        job.arrivee_le = timezone.now()
    if point is not None:
        job.arrivee_position = point
    _distance(job)
    job.save()


def terminer(job):
    if job.fin_le is None:
        job.fin_le = timezone.now()
        if job.arrivee_le is None:
            job.arrivee_le = job.depart_le
        job.save()


def heures(job):
    """Main-d'œuvre facturée : temps sur place, au quart d'heure supérieur."""
    minutes = Decimal(job.sur_place_min or 0)
    return (minutes / 60 * 4).to_integral_value(rounding=ROUND_UP) / 4


def facturer(job):
    """Facture en brouillon : main-d'œuvre et déplacement aux taux de l'entreprise (vides : à remplir sur la facture),
    minimum de l'entreprise s'il y en a un. Le matériel s'ajoute sur la facture (boutons des services)."""
    if job.fin_le is None:
        raise ValidationError("Terminer la job d'abord.")
    if job.facture_id:
        return job.facture
    ent = job.entreprise
    with transaction.atomic():
        f = Facture.objects.create(entreprise=ent, client=job.client, adresse=job.adresse, date_facture=timezone.localdate(),
                                   date_echeance=timezone.localdate() + timedelta(days=ent.jours_paiement_passage))
        jour = date_format(timezone.localtime(job.depart_le), "j F")
        h = heures(job)
        f.lignes.create(ordre=1, description=f"{job.get_genre_display()} du {jour} : main-d'œuvre ({str(h).replace('.', ',')} h)",
                        quantite=h or Decimal("0.25"), prix_unitaire=ent.taux_horaire or Decimal("0"))
        if job.distance_km:
            km = job.distance_km * 2
            f.lignes.create(ordre=2, description=f"Déplacement aller-retour ({str(km).replace('.', ',')} km estimés)",
                            quantite=km, prix_unitaire=ent.taux_km or Decimal("0"))
        f.recalculer()
        if ent.minimum_job and f.sous_total < ent.minimum_job:
            f.lignes.create(ordre=3, description="Ajustement au minimum par job", quantite=1, prix_unitaire=ent.minimum_job - f.sous_total)
            f.recalculer()
        job.facture = f
        job.save(update_fields=["facture"])
    return f
