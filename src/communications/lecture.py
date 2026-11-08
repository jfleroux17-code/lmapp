"""Lecture de la boîte IMAP de l'entreprise par le worker (PRD E5).

Boîte ouverte en lecture seule et courriels lus avec BODY.PEEK : rien n'est marqué lu ni déplacé,
Louis garde sa boîte telle quelle. On retient le dernier UID traité (EtatBoite); à la première
lecture (ou si la boîte est recréée), on part de maintenant, sans importer l'historique.
"""
import imaplib
import logging
import ssl

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from communications import reception
from communications.models import EtatBoite
from core.models import Entreprise

log = logging.getLogger(__name__)
PAR_PASSE = 50  # au plus 50 courriels par lecture : la suite à la prochaine


def entreprise_de_la_boite():
    if not (settings.IMAP_HOTE and settings.IMAP_UTILISATEUR and settings.IMAP_MOT_DE_PASSE):
        return None
    return Entreprise.objects.filter(active=True, courriel_reponse__iexact=settings.IMAP_UTILISATEUR).first()


def lire(entreprise):
    etat, _ = EtatBoite.objects.get_or_create(entreprise=entreprise)
    nouveaux = 0
    try:
        with imaplib.IMAP4_SSL(settings.IMAP_HOTE, settings.IMAP_PORT, ssl_context=ssl.create_default_context(), timeout=30) as i:
            i.login(settings.IMAP_UTILISATEUR, settings.IMAP_MOT_DE_PASSE)
            i.select("INBOX", readonly=True)
            uidvalidite = int(i.response("UIDVALIDITY")[1][0])
            if etat.uidvalidite != uidvalidite:
                _, d = i.uid("search", None, "ALL")
                uids = [int(x) for x in d[0].split()]
                etat.uidvalidite, etat.dernier_uid = uidvalidite, max(uids, default=0)
                log.info("boîte de %s : départ au UID %s (historique non importé)", entreprise, etat.dernier_uid)
            else:
                _, d = i.uid("search", None, f"UID {etat.dernier_uid + 1}:*")
                for uid in sorted(int(x) for x in d[0].split() if int(x) > etat.dernier_uid)[:PAR_PASSE]:
                    _, data = i.uid("fetch", str(uid), "(BODY.PEEK[])")
                    octets = next((x[1] for x in data if isinstance(x, tuple)), None)
                    try:
                        with transaction.atomic():
                            if octets and reception.traiter(entreprise, octets):
                                nouveaux += 1
                    except Exception:  # un courriel illisible ne doit pas bloquer les suivants
                        log.exception("courriel UID %s illisible, sauté", uid)
                    etat.dernier_uid = uid
                    etat.save(update_fields=["dernier_uid"])
        etat.erreur = ""
    except (OSError, imaplib.IMAP4.error) as e:
        etat.erreur = str(e)[:300]
        log.warning("lecture de la boîte impossible : %s", e)
    etat.lue_le = timezone.now()
    etat.save()
    return nouveaux
