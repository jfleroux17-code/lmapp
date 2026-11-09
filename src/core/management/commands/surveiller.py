from django.core.management.base import BaseCommand

from core import surveillance


class Command(BaseCommand):
    help = "Surveillance de LMAPP (PRD 6.7) : boucle sans fin, ou --une-fois pour voir l'état, --essai-courriel ou --essai-texto pour une alerte d'essai."

    def add_arguments(self, parser):
        parser.add_argument("--une-fois", action="store_true", help="Une seule ronde, affichée, sans alerte.")
        parser.add_argument("--essai-courriel", action="store_true", help="Envoie un courriel d'essai à LMAPP_ALERTES_COURRIEL.")
        parser.add_argument("--essai-texto", action="store_true", help="Envoie un texto d'essai à LMAPP_ALERTES_TEXTO, du numéro LMAPP_ALERTES_TEXTO_DE.")

    def handle(self, *args, **o):
        if o["essai_courriel"]:
            ok = surveillance.envoyer_courriel("[Le Déneigeur] Essai de la surveillance",
                                               "Essai : les alertes de la surveillance de ld1 arriveront ainsi.")
            self.stdout.write("courriel d'essai parti" if ok else "courriel d'essai PAS parti (voir le journal)")
            return
        if o["essai_texto"]:
            ok = surveillance.envoyer_texto("Le Déneigeur : essai de la surveillance. Les alertes de ld1 arriveront de ce numéro.")
            self.stdout.write("texto d'essai parti" if ok else "texto d'essai PAS parti (voir le journal)")
            return
        if o["une_fois"]:
            fin = surveillance.silence_jusqu_a()
            if fin:
                self.stdout.write(f"EN SILENCE jusqu'à {fin:%H:%M} : aucune alerte de panne ne part")
            for cle, (ok, detail) in surveillance.tout_verifier().items():
                self.stdout.write(f"{'ok  ' if ok else 'PANNE'} {cle} {detail}")
            return
        surveillance.boucle()
