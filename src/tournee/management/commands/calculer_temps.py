"""Recalcule les temps par entrée des opérations terminées (tournee/temps.py) : après un correctif, ou pour les
opérations d'avant le 13 novembre 2026. Les positions de plus de 120 jours sont effacées : seulement « depuis la
tape précédente » pour celles-là."""
from django.core.management.base import BaseCommand

from tournee.models import Operation
from tournee.temps import calculer


class Command(BaseCommand):
    help = "Recalcule les temps passés à chaque entrée (opérations terminées)."

    def add_arguments(self, parser):
        parser.add_argument("--entreprise", help="Identifiant (slug) de l'entreprise; toutes par défaut.")

    def handle(self, *args, **options):
        qs = Operation.objects.exclude(fin=None)
        if options["entreprise"]:
            qs = qs.filter(entreprise__slug=options["entreprise"])
        n = sum(calculer(op) for op in qs.order_by("debut"))
        self.stdout.write(f"{qs.count()} opérations, {n} passages recalculés.")
