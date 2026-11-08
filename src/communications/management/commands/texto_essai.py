"""Texto d'essai (PRD M1) : passe par le même chemin que les avis (garde-fous, worker, Twilio).

  docker compose run --rm app python manage.py texto_essai +15145550100 --entreprise essai

Hors prod, seul un numéro de LMAPP_DESTINATAIRES_TEST reçoit; sinon le message est « Bloqué ».
"""
from django.core.management.base import BaseCommand, CommandError

from communications import envoi
from communications.models import Genre, Message
from core import telephone
from core.models import Entreprise


class Command(BaseCommand):
    help = "Envoie un texto d'essai (voir /messages/ pour le résultat)."

    def add_arguments(self, parser):
        parser.add_argument("numero")
        parser.add_argument("--entreprise", required=True, help="slug de l'entreprise")
        parser.add_argument("--texte", default="Essai de LMAPP : si vous lisez ceci, les textos fonctionnent.")

    def handle(self, numero, entreprise, texte, **_):
        ent = Entreprise.objects.filter(slug=entreprise).first()
        if ent is None:
            raise CommandError(f"Entreprise inconnue : {entreprise}")
        dest = telephone.normaliser(numero)
        m = Message.objects.create(entreprise=ent, genre=Genre.MANUEL, canal=Message.Canal.TEXTO, destinataire=dest,
                                   contenu=f"{texte}\n{ent.signature_messages or ent.nom}")
        envoi.envoyer(m)
        self.stdout.write(f"Message {m.pk} vers {dest} : {m.get_statut_display()}{' (' + m.erreur + ')' if m.erreur else ''}")
