"""Produit une paire de clés VAPID pour les notifications (PRD E8). Les lignes vont dans .env (permissions 600) :

  docker compose run --rm app python manage.py cles_vapid >> .env      (sans jamais les afficher ailleurs)

Changer les clés désabonne tous les appareils (il faudra réactiver les notifications sur chaque cellulaire).
"""
from django.core.management.base import BaseCommand

from core.notifications import nouvelles_cles


class Command(BaseCommand):
    help = "Affiche deux lignes VAPID_CLE_PRIVEE et VAPID_CLE_PUBLIQUE à ajouter au .env."

    def handle(self, *args, **o):
        prive, public = nouvelles_cles()
        self.stdout.write(f"VAPID_CLE_PRIVEE={prive}\nVAPID_CLE_PUBLIQUE={public}")
