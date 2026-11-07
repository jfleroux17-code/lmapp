"""Géocode les adresses sans position (ou trop vagues), sauf les positions manuelles.

Par défaut, met les adresses en file pour le worker. Avec --maintenant, les
traite tout de suite dans cette commande (une par seconde), sans worker.

  docker compose run --rm app python manage.py geocoder_adresses --entreprise louis
"""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from clients.models import Adresse
from clients.tasks import geocoder_adresse, geocoder_maintenant
from core.models import Entreprise


class Command(BaseCommand):
    help = "Géocode les adresses sans position ou trop vagues (sauf les positions manuelles)."

    def add_arguments(self, parser):
        parser.add_argument("--entreprise", required=True)
        parser.add_argument("--maintenant", action="store_true", help="Traiter ici, sans passer par le worker")
        parser.add_argument("--inclure-ville", action="store_true", help="Réessayer aussi les positions « ville seulement »")

    def handle(self, *args, **o):
        try:
            ent = Entreprise.objects.get(slug=o["entreprise"])
        except Entreprise.DoesNotExist:
            raise CommandError(f"Aucune entreprise « {o['entreprise']} ».")
        a_faire = Q(position__isnull=True)
        if o["inclure_ville"]:
            a_faire |= Q(position_precision=Adresse.Precision.VILLE)
        qs = (Adresse.objects.filter(entreprise=ent, active=True).filter(a_faire)
              .exclude(position_source__in=[Adresse.SourcePosition.MANUELLE, Adresse.SourcePosition.GPS]))
        total = qs.count()
        self.stdout.write(f"{total} adresse(s) à géocoder.")
        for i, a in enumerate(qs.order_by("pk"), start=1):
            if o["maintenant"]:
                resultat = geocoder_maintenant(a)
                self.stdout.write(f"  {i}/{total} {a} : {resultat}")
            else:
                geocoder_adresse.defer(adresse_id=a.pk)
        if not o["maintenant"] and total:
            self.stdout.write(self.style.SUCCESS(f"{total} adresse(s) en file; le worker les traite à environ une par seconde."))
