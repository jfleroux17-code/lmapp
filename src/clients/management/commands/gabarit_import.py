"""Produit le gabarit d'import des clients, en Excel et en CSV.

  docker compose run --rm -v /srv/lmapp/gabarits:/sortie app \\
      python manage.py gabarit_import /sortie
"""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from clients.importation import COLONNES


class Command(BaseCommand):
    help = "Écrit gabarit_import_clients.xlsx et .csv dans le dossier indiqué."

    def add_arguments(self, parser):
        parser.add_argument("dossier")

    def handle(self, *args, **o):
        dossier = Path(o["dossier"])
        self._csv(dossier / "gabarit_import_clients.csv")
        self._xlsx(dossier / "gabarit_import_clients.xlsx")
        self.stdout.write(self.style.SUCCESS(f"Gabarits écrits dans {dossier}"))

    def _csv(self, chemin):
        # UTF-8 avec BOM et point-virgule : ce qu'Excel en français ouvre correctement
        with open(chemin, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow([c.titre for c in COLONNES])
            w.writerow([c.exemple1 for c in COLONNES])
            w.writerow([c.exemple2 for c in COLONNES])

    def _xlsx(self, chemin):
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = "Clients"
        ws.append([c.titre for c in COLONNES])
        ws.append([c.exemple1 for c in COLONNES])
        ws.append([c.exemple2 for c in COLONNES])
        gras = Font(bold=True)
        oblig = PatternFill("solid", fgColor="F5C400")
        argent = PatternFill("solid", fgColor="DDEBF7")
        for i, c in enumerate(COLONNES, start=1):
            cellule = ws.cell(row=1, column=i)
            cellule.font = gras
            if c.obligatoire:
                cellule.fill = oblig
            elif c.argent:
                cellule.fill = argent
            ws.column_dimensions[get_column_letter(i)].width = max(14, min(32, len(max(c.titre, c.exemple1, c.exemple2, key=len)) + 2))
            # Numéros et codes en texte : Excel ne doit pas les transformer en nombres
            if c.cle in ("cellulaire", "autre_telephone", "code_postal", "facturation_code_postal", "no_client"):
                for r in range(2, 1001):
                    ws.cell(row=r, column=i).number_format = "@"
        ws.freeze_panes = "A2"

        ex = wb.create_sheet("Explications")
        ex.append(["Colonne", "Obligatoire", "Explication", "Exemple"])
        for cellule in ex[1]:
            cellule.font = gras
        ex.append(["", "", "Une ligne par adresse de service. Un client avec deux adresses : deux lignes avec le même no_client. "
                   "Les exemples (lignes 2 et 3 de l'onglet Clients) sont fictifs : les effacer avant d'envoyer le fichier. "
                   "Colonnes en jaune : obligatoires. Colonnes en bleu : l'argent (prix de la saison, solde dû).", ""])
        for c in COLONNES:
            ex.append([c.titre, "oui" if c.obligatoire else ("argent" if c.argent else ""), c.explication, c.exemple1 or c.exemple2])
        ex.column_dimensions["A"].width = 26
        ex.column_dimensions["B"].width = 12
        ex.column_dimensions["C"].width = 90
        ex.column_dimensions["D"].width = 30
        for rangee in ex.iter_rows(min_row=2):
            for cellule in rangee:
                cellule.alignment = Alignment(wrap_text=True, vertical="top")
        wb.save(chemin)
