"""Lecture et nettoyage de la boîte IMAP de l'entreprise par le worker (PRD E5, boîtes de 2 Go).

Pour chaque dossier (réception, puis envoyés) :
  1. chaque nouveau courriel est copié au complet dans la base (ArchiveCourriel, compressé, avec son
     empreinte SHA-256), puis traité (message reçu rattaché au client, ou envoi de Louis noté dans la fiche);
     lu avec BODY.PEEK : il garde son état « non lu » chez Louis;
  2. les courriels archivés depuis plus de COURRIEL_GARDER_JOURS jours sont effacés de la boîte, après
     avoir vérifié que l'archive se relit et redonne exactement le même courriel.
On retient le dernier UID archivé (EtatBoite, par dossier). À la première lecture d'un dossier, les
courriels déjà là sont archivés (puis effacés à leur tour), mais pas traités : pas de vieux messages
dans l'app.
"""
import hashlib
import imaplib
import logging
import re
import ssl
import zlib
from datetime import timedelta
from email import policy
from email.parser import BytesHeaderParser
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from communications import reception
from communications.models import ArchiveCourriel, EtatBoite
from core.models import Entreprise

log = logging.getLogger(__name__)
PAR_PASSE = 50  # au plus 50 courriels par dossier et par lecture : la suite à la prochaine
EFFACER_PAR_PASSE = 200


def entreprise_de_la_boite():
    if not (settings.IMAP_HOTE and settings.IMAP_UTILISATEUR and settings.IMAP_MOT_DE_PASSE):
        return None
    return Entreprise.objects.filter(active=True, courriel_reponse__iexact=settings.IMAP_UTILISATEUR).first()


def _entetes(octets):
    h = BytesHeaderParser(policy=policy.default).parsebytes(octets)
    try:
        date = parsedate_to_datetime(str(h["Date"])) if h.get("Date") else None
        if date and timezone.is_naive(date):
            date = timezone.make_aware(date)
    except (TypeError, ValueError):
        date = None
    return {
        "entete_message_id": str(h.get("Message-ID", "")).strip()[:300],
        "expediteur": parseaddr(str(h.get("From", "")))[1].lower()[:254],
        "destinataires": ", ".join(a for _, a in getaddresses([str(h.get("To", "")), str(h.get("Cc", ""))]) if a)[:500],
        "sujet": str(h.get("Subject", "")).strip()[:200],
        "date": date,
    }


def archiver(entreprise, dossier, uidvalidite, uid, octets):
    a, cree = ArchiveCourriel.objects.get_or_create(
        entreprise=entreprise, dossier=dossier, uidvalidite=uidvalidite, uid=uid,
        defaults={"taille": len(octets), "empreinte": hashlib.sha256(octets).hexdigest(),
                  "brut": zlib.compress(octets, 6), **_entetes(octets)})
    return a


def _lire_dossier(i, entreprise, dossier, traiter):
    typ, _ = i.select(f'"{dossier}"')
    if typ != "OK":
        log.warning("dossier %s introuvable dans la boîte", dossier)
        return 0, None
    uidvalidite = int(i.response("UIDVALIDITY")[1][0])
    etat, _ = EtatBoite.objects.get_or_create(entreprise=entreprise, dossier=dossier)
    if etat.uidvalidite != uidvalidite:  # première lecture du dossier (ou dossier recréé)
        _, d = i.uid("search", None, "ALL")
        etat.uidvalidite, etat.dernier_uid = uidvalidite, 0
        etat.uid_depart = max((int(x) for x in d[0].split()), default=0)
        etat.save()
        log.info("%s de %s : %s courriel(s) déjà là, archivés sans être traités", dossier, entreprise, etat.uid_depart)
    _, d = i.uid("search", None, f"UID {etat.dernier_uid + 1}:*")
    nouveaux = 0
    for uid in sorted(int(x) for x in d[0].split() if int(x) > etat.dernier_uid)[:PAR_PASSE]:
        _, data = i.uid("fetch", str(uid), "(BODY.PEEK[])")
        octets = next((x[1] for x in data if isinstance(x, tuple)), None)
        if octets is None:
            continue  # effacé entre-temps
        with transaction.atomic():
            a = archiver(entreprise, dossier, uidvalidite, uid, octets)
            if uid > etat.uid_depart and a.message_id is None:
                try:
                    with transaction.atomic():
                        m = traiter(entreprise, octets)
                    if m is not None:
                        a.message = m
                        a.save(update_fields=["message"])
                        nouveaux += 1
                except Exception:  # un courriel illisible est archivé, mais ne bloque pas les suivants
                    log.exception("%s UID %s : traitement impossible (archivé quand même)", dossier, uid)
            etat.dernier_uid = uid
            etat.save(update_fields=["dernier_uid"])
    return nouveaux, uidvalidite


def _effacer_vieux(i, entreprise, dossier, uidvalidite):
    """Efface de la boîte les courriels archivés depuis assez longtemps (le dossier est déjà sélectionné)."""
    if settings.COURRIEL_GARDER_JOURS < 0 or uidvalidite is None:
        return 0
    limite = timezone.now() - timedelta(days=settings.COURRIEL_GARDER_JOURS)
    a_effacer = []
    for a in ArchiveCourriel.objects.filter(entreprise=entreprise, dossier=dossier, uidvalidite=uidvalidite,
                                            efface_le=None, archive_le__lt=limite).order_by("uid")[:EFFACER_PAR_PASSE]:
        try:
            a.octets()  # l'archive se relit et redonne le même courriel : sinon on n'efface pas
        except Exception:
            log.error("archive %s illisible : courriel UID %s gardé dans la boîte", a.pk, a.uid)
            continue
        a_effacer.append(a)
    if not a_effacer:
        return 0
    uids = ",".join(str(a.uid) for a in a_effacer)
    i.uid("store", uids, "+FLAGS.SILENT", r"(\Deleted)")
    if "UIDPLUS" in getattr(i, "capabilities", ()):
        i.uid("expunge", uids)  # seulement ceux-là, pas ce que Louis aurait marqué de son côté
    else:
        i.expunge()
    ArchiveCourriel.objects.filter(pk__in=[a.pk for a in a_effacer]).update(efface_le=timezone.now())
    log.info("%s de %s : %s courriel(s) archivé(s) effacé(s) de la boîte", dossier, entreprise, len(a_effacer))
    return len(a_effacer)


def _quota(i):
    """(utilisé, permis) en Ko pour la boîte, ou (None, None) si le serveur ne le dit pas."""
    try:
        _, d = i.getquotaroot("INBOX")
        for ligne in d[1] if len(d) > 1 else []:
            m = re.search(rb"STORAGE (\d+) (\d+)", ligne if isinstance(ligne, bytes) else str(ligne).encode())
            if m:
                return int(m.group(1)), int(m.group(2))
    except (imaplib.IMAP4.error, OSError, AttributeError, IndexError):
        pass
    return None, None


def lire(entreprise):
    nouveaux = 0
    dossiers = [("INBOX", reception.traiter), (settings.IMAP_DOSSIER_ENVOYES, reception.traiter_envoye)]
    try:
        with imaplib.IMAP4_SSL(settings.IMAP_HOTE, settings.IMAP_PORT, ssl_context=ssl.create_default_context(), timeout=60) as i:
            i.login(settings.IMAP_UTILISATEUR, settings.IMAP_MOT_DE_PASSE)
            utilise, permis = _quota(i)
            for dossier, traiter in dossiers:
                n, uidvalidite = _lire_dossier(i, entreprise, dossier, traiter)
                nouveaux += n
                _effacer_vieux(i, entreprise, dossier, uidvalidite)
                EtatBoite.objects.filter(entreprise=entreprise, dossier=dossier).update(
                    lue_le=timezone.now(), erreur="", quota_utilise_ko=utilise, quota_max_ko=permis)
    except (OSError, imaplib.IMAP4.error) as e:
        EtatBoite.objects.filter(entreprise=entreprise).update(erreur=str(e)[:300], lue_le=timezone.now())
        log.warning("lecture de la boîte impossible : %s", e)
    return nouveaux
