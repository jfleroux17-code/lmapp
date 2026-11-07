"""Importe des clients et leurs adresses depuis un fichier CSV ou Excel (PRD A9).

Essai à blanc par défaut : rien n'est écrit sans --appliquer.

Le conteneur est en lecture seule : monter le fichier à l'exécution, ex. :
  docker compose run --rm -v /chemin/clients.xlsx:/import/clients.xlsx:ro \\
      app python manage.py importer_clients /import/clients.xlsx --entreprise essai
"""
from django.core.management.base import BaseCommand, CommandError

from clients import importation
from core.models import Entreprise


class Command(BaseCommand):
    help = "Importe des clients depuis un fichier CSV ou Excel. Essai à blanc par défaut."

    def add_arguments(self, parser):
        parser.add_argument("fichier", help="Chemin du fichier .csv ou .xlsx (dans le conteneur)")
        parser.add_argument("--entreprise", required=True, help="Identifiant (slug) de l'entreprise, ex. louis")
        parser.add_argument("--appliquer", action="store_true", help="Enregistrer pour vrai (sinon : essai à blanc)")
        parser.add_argument("--sauter-erreurs", action="store_true", help="Avec --appliquer : importer les lignes valides et laisser les lignes en erreur")

    def handle(self, *args, **o):
        try:
            entreprise = Entreprise.objects.get(slug=o["entreprise"])
        except Entreprise.DoesNotExist:
            raise CommandError(f"Aucune entreprise avec l'identifiant « {o['entreprise']} ».")
        try:
            fichier = importation.lire(o["fichier"])
        except FileNotFoundError:
            raise CommandError(f"Fichier introuvable : {o['fichier']} (est-il monté dans le conteneur?)")

        a = importation.analyser(fichier, entreprise)
        w = self.stdout.write
        details = f", {fichier.encodage}, séparateur {fichier.separateur}" if fichier.format == "CSV" else ""
        w(f"Fichier : {o['fichier']} ({fichier.format}{details})")
        w(f"Entreprise : {entreprise} ({entreprise.slug})")
        w(f"Colonnes reconnues : {len(a.colonnes)} sur {len(importation.COLONNES)}")
        if a.inconnues:
            w(self.style.WARNING(f"Colonnes ignorées (inconnues) : {', '.join(a.inconnues)}"))
        if a.manquantes:
            raise CommandError(f"Colonnes obligatoires manquantes : {', '.join(a.manquantes)}. Rien n'est importé.")
        if a.colonnes_plus_tard:
            w(f"Colonnes lues pour plus tard (contrats et soldes, pas encore importées) : {', '.join(a.colonnes_plus_tard)}")

        for l in a.lignes:
            if l.statut == "erreur":
                w(self.style.ERROR(f"  ligne {l.numero} : ERREUR : {' | '.join(l.erreurs)}"))
            for av in l.avertissements:
                w(self.style.WARNING(f"  ligne {l.numero} : avertissement : {av}"))
            if l.statut == "existe":
                w(f"  ligne {l.numero} : déjà en base, ignorée ({l.description})")

        nb_plus_tard = sum(1 for l in a.lignes if l.plus_tard and l.statut != "erreur")
        w("")
        w(f"Résumé : {a.nb_clients} client(s) et {len(a.a_creer)} adresse(s) à créer, "
          f"{len(a.secteurs_nouveaux)} secteur(s) nouveau(x){' (' + ', '.join(a.secteurs_nouveaux) + ')' if a.secteurs_nouveaux else ''}, "
          f"{len(a.existantes)} ligne(s) déjà en base, {len(a.erreurs)} ligne(s) en erreur.")
        if nb_plus_tard:
            w(f"         {nb_plus_tard} ligne(s) avec prix ou solde dû, à importer à l'étape des contrats et des soldes.")

        if not o["appliquer"]:
            w(self.style.WARNING("ESSAI À BLANC : rien n'a été enregistré. Relancer avec --appliquer pour importer."))
            return
        try:
            nb_clients, nb_adresses = importation.appliquer(a, entreprise, sauter_erreurs=o["sauter_erreurs"])
        except ValueError as e:
            raise CommandError(str(e))
        w(self.style.SUCCESS(f"Importé : {nb_clients} client(s), {nb_adresses} adresse(s)."))
