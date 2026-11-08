"""Texto ou courriel d'essai : passe par le même chemin que les avis et les factures (garde-fous, worker).

  docker compose run --rm app python manage.py message_essai +15145550100 --entreprise essai
  docker compose run --rm app python manage.py message_essai moi@exemple.com --entreprise essai

Hors prod, seul un numéro de LMAPP_DESTINATAIRES_TEST reçoit; sinon le message est « Bloqué ».
"""
from django.core.management.base import BaseCommand, CommandError

from communications import envoi
from communications.models import Genre, Message
from core import telephone
from core.models import Entreprise


class Command(BaseCommand):
    help = "Envoie un texto ou un courriel d'essai (voir /messages/ pour le résultat)."

    def add_arguments(self, parser):
        parser.add_argument("destinataire", help="cellulaire ou adresse courriel")
        parser.add_argument("--entreprise", required=True, help="slug de l'entreprise")
        parser.add_argument("--texte", default="Essai de LMAPP : si vous lisez ceci, l'envoi fonctionne.")

    def handle(self, destinataire, entreprise, texte, **_):
        ent = Entreprise.objects.filter(slug=entreprise).first()
        if ent is None:
            raise CommandError(f"Entreprise inconnue : {entreprise}")
        if "@" in destinataire:
            canal, dest = Message.Canal.COURRIEL, destinataire.strip().lower()
        else:
            canal, dest = Message.Canal.TEXTO, telephone.normaliser(destinataire)
        m = Message.objects.create(entreprise=ent, genre=Genre.MANUEL, canal=canal, destinataire=dest,
                                   sujet=f"Message de {ent.nom}", contenu=f"{texte}\n\n{ent.signature_messages or ent.nom}")
        envoi.envoyer(m)
        self.stdout.write(f"Message {m.pk} vers {dest} : {m.get_statut_display()}{' (' + m.erreur + ')' if m.erreur else ''}")
