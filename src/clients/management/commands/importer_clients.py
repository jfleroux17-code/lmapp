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
        parser.add_argument("--depuis", help="Logiciel d'origine : correspondance des colonnes dans clients/correspondances/<logiciel>.json")
        parser.add_argument("--correspondance", help="Fichier JSON {entête du fichier: colonne du gabarit} (prioritaire sur --depuis)")

    def handle(self, *args, **o):
        try:
            entreprise = Entreprise.objects.get(slug=o["entreprise"])
        except Entreprise.DoesNotExist:
            raise CommandError(f"Aucune entreprise avec l'identifiant « {o['entreprise']} ».")
        try:
            fichier = importation.lire(o["fichier"])
        except FileNotFoundError:
            raise CommandError(f"Fichier introuvable : {o['fichier']} (est-il monté dans le conteneur?)")

        correspondance = None
        try:
            if o.get("correspondance"):
                import json
                with open(o["correspondance"], encoding="utf-8") as f:
                    correspondance = json.load(f)
            elif o.get("depuis"):
                correspondance = importation.correspondance_du_logiciel(o["depuis"])
            a = importation.analyser(fichier, entreprise, correspondance)
        except (FileNotFoundError, ValueError) as e:
            raise CommandError(str(e))
        w = self.stdout.write
        details = f", {fichier.encodage}, séparateur {fichier.separateur}" if fichier.format == "CSV" else ""
        w(f"Fichier : {o['fichier']} ({fichier.format}{details})")
        w(f"Entreprise : {entreprise} ({entreprise.slug})")
        w(f"Colonnes reconnues : {len(a.colonnes)} sur {len(importation.COLONNES)}")
        for i, cle in sorted(a.colonnes.items()):
            brute = fichier.entetes_brutes[i]
            if importation._cle(brute) != cle:  # montrer seulement ce qui a été traduit
                w(f"  « {brute} » va dans {cle}")
        if a.inconnues:
            w(self.style.WARNING(f"Colonnes ignorées (inconnues) : {', '.join(a.inconnues)}"))
        if a.manquantes:
            raise CommandError(f"Colonnes obligatoires manquantes : {', '.join(a.manquantes)}. Rien n'est importé.")
        if a.colonnes_argent:
            w(f"Colonnes d'argent : {', '.join(a.colonnes_argent)} (contrats dans la saison {a.saison}{' : à créer, du 1er novembre au 30 avril, modifiable ensuite' if a.saison and a.saison.pk is None else ''}).")

        for l in a.lignes:
            if l.statut == "erreur":
                w(self.style.ERROR(f"  ligne {l.numero} : ERREUR : {' | '.join(l.erreurs)}"))
            for av in l.avertissements:
                w(self.style.WARNING(f"  ligne {l.numero} : avertissement : {av}"))
            if l.statut == "existe":
                w(f"  ligne {l.numero} : déjà en base, ignorée ({l.description})")

        nb_contrats, nb_soldes = a.nb_contrats, a.nb_soldes
        w("")
        w(f"Résumé : {a.nb_clients} client(s) et {len(a.a_creer)} adresse(s) à créer, "
          f"{len(a.secteurs_nouveaux)} secteur(s) nouveau(x){' (' + ', '.join(a.secteurs_nouveaux) + ')' if a.secteurs_nouveaux else ''}, "
          f"{len(a.existantes)} ligne(s) déjà en base, {len(a.erreurs)} ligne(s) en erreur.")
        if nb_contrats or nb_soldes:
            w(f"         {nb_contrats} contrat(s) et {nb_soldes} solde(s) antérieur(s) à créer.")
        if nb_contrats:
            from collections import Counter

            ent = entreprise
            par_nb = Counter(l.argent.get("versements") or ent.versements_par_defaut for l in a._a_importer("prix_saison")
                             if l.argent.get("type_contrat", "saisonnier") == "saisonnier")
            for nb, combien in sorted(par_nb.items()):
                dates = " et ".join(f"{j:02d}/{m:02d}" for j, m in ent.liste_dates_versements()[:nb - 1])
                w(f"         Échéancier : {combien} contrat(s) en {nb} versement(s) (1er daté de l'import, facture en brouillon la nuit suivante"
                  f"{', puis ' + dates if dates else ''}).")

        if a.statuts:
            w("         Statuts des clients à créer : " + ", ".join(f"{n} {st}" for st, n in sorted(a.statuts.items(), key=lambda x: -x[1]))
              + " (vérifier qu'aucun ex-client n'est « actif »).")
        incluses = [l for l in a._a_importer("prix_saison") if l.argent.get("taxes_incluses") and "prix_contrat" in l.calcul]
        if incluses:
            w(f"         Taxes incluses : {len(incluses)} contrat(s), prix ramené avant taxes (ex. ligne {incluses[0].numero} : "
              f"{importation._argent(incluses[0].argent['prix_saison'] + (incluses[0].argent.get('extra_prix') or 0))} devient "
              f"{importation._argent(incluses[0].calcul['prix_contrat'])} avant taxes).")
        extras = a._a_importer("extra_prix")
        if extras:
            w(f"         Extras : {len(extras)} contrat(s) avec un service ajouté (prix additionné au contrat).")
        if a.services_nouveaux:
            w(f"         Services ajoutés au catalogue : {', '.join(a.services_nouveaux)}.")
        if a.recus:
            total = sum(l.argent["recu_montant"] for l in a.recus)
            w(f"         Déjà reçu : {len(a.recus)} client(s), {importation._argent(total)} au total, en crédit au compte "
              "(paie la 1re facture émise; compté comme reçu à sa date).")

        if not o["appliquer"]:
            w(self.style.WARNING("ESSAI À BLANC : rien n'a été enregistré. Relancer avec --appliquer pour importer."))
            return
        try:
            r = importation.appliquer(a, entreprise, sauter_erreurs=o["sauter_erreurs"])
        except ValueError as e:
            raise CommandError(str(e))
        w(self.style.SUCCESS(f"Importé : {r.clients} client(s), {r.adresses} adresse(s), {r.contrats} contrat(s), {r.soldes} solde(s) antérieur(s), "
                                   f"{r.services} service(s) ajouté(s), {r.credits} montant(s) déjà reçu(s) en crédit."))
