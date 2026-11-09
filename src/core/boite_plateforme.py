"""Boîte de la plateforme (info@ledeneigeur.com, l'adresse du site Internet) : demandes de clients potentiels.

Le worker la lit aux 2 minutes (en prod seulement, COURRIEL_LECTURE_ACTIVE) :
  1. chaque nouveau courriel de la réception est gardé au complet dans la base (DemandeSite, compressé);
     la boîte est ouverte en lecture seule, avec BODY.PEEK : rien n'est marqué lu, déplacé ni effacé;
  2. il est transféré à JF (PLATEFORME_TRANSFERT_A) : résumé, texte, et le courriel d'origine joint
     (pièces jointes comprises); « Répondre » vise l'expéditeur. Transfert raté : nouvel essai au passage
     suivant, 5 essais au plus.
Pas de transfert pour les messages automatiques (rebonds, réponses d'absence, Auto-Submitted) ni pour nos
propres envois : un rebond de transfert ne doit pas revenir en boucle.
"""
import imaplib
import logging
import smtplib
import ssl
import zlib
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import formataddr, getaddresses, make_msgid, parsedate_to_datetime

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from communications.reception import _corps
from core.models import DemandeSite

log = logging.getLogger(__name__)
PAR_PASSE = 50
ESSAIS_MAX = 5
LONGUEUR_MAX = 20000


def configuree():
    return bool(settings.IMAP_HOTE and settings.PLATEFORME_IMAP_UTILISATEUR and settings.PLATEFORME_IMAP_MOT_DE_PASSE)


def _automatique(msg, expediteur):
    local = expediteur.split("@")[0]
    auto = str(msg.get("Auto-Submitted", "no")).strip().lower()
    return (local in ("mailer-daemon", "postmaster", "noreply", "no-reply") or auto not in ("", "no")
            or msg.get_content_type() == "multipart/report" or bool(msg.get("X-Autoreply")) or bool(msg.get("X-Autorespond"))
            or expediteur == settings.PLATEFORME_IMAP_UTILISATEUR.lower())


def analyser(octets):
    """Champs d'une DemandeSite à partir du courriel brut."""
    msg = BytesParser(policy=policy.default).parsebytes(octets)
    nom, adresse = (getaddresses([str(msg.get("Reply-To") or msg.get("From", ""))]) or [("", "")])[0]
    de_nom, de_adresse = (getaddresses([str(msg.get("From", ""))]) or [("", "")])[0]
    try:
        recu = parsedate_to_datetime(str(msg["Date"])) if msg.get("Date") else None
        if recu and timezone.is_naive(recu):
            recu = timezone.make_aware(recu)
    except (TypeError, ValueError):
        recu = None
    try:
        texte = _corps(msg)
    except Exception:  # noqa: BLE001 : un corps illisible n'empêche pas de garder le courriel
        texte = ""
    jointes = [p.get_filename() for p in msg.iter_attachments() if p.get_filename()]
    expediteur = (adresse or de_adresse).lower()[:254]
    return msg, {
        "recu_le": recu or timezone.now(),
        "entete_message_id": str(msg.get("Message-ID", "")).strip()[:300],
        "expediteur": expediteur,
        "nom": (nom or de_nom)[:200],
        "sujet": str(msg.get("Subject", "")).strip()[:200],
        "texte": texte.replace("\r\n", "\n").strip()[:LONGUEUR_MAX],
        "pieces_jointes": jointes[:20],
        "statut": DemandeSite.Statut.AUTOMATIQUE if _automatique(msg, de_adresse.lower()) else DemandeSite.Statut.NOUVELLE,
    }


def courriel_de_transfert(d):
    m = EmailMessage()
    m["From"] = formataddr(("Le Déneigeur (info@)", settings.PLATEFORME_IMAP_UTILISATEUR))
    m["To"] = settings.PLATEFORME_TRANSFERT_A
    if d.expediteur:
        m["Reply-To"] = formataddr((d.nom, d.expediteur)) if d.nom else d.expediteur
    m["Subject"] = f"[info@] {d.sujet or '(sans sujet)'}"
    m["Message-ID"] = make_msgid(domain=settings.PLATEFORME_IMAP_UTILISATEUR.split("@")[-1])
    m["Auto-Submitted"] = "auto-generated"  # un répondeur automatique ne doit pas répondre au transfert
    jointes = f"Pièces jointes : {', '.join(d.pieces_jointes)}\n" if d.pieces_jointes else ""
    m.set_content(
        f"Nouvelle demande reçue à {settings.PLATEFORME_IMAP_UTILISATEUR}.\n\n"
        f"De : {d.nom + ' ' if d.nom else ''}<{d.expediteur}>\n"
        f"Reçu le : {timezone.localtime(d.recu_le):%Y-%m-%d %H:%M}\n"
        f"Sujet : {d.sujet}\n{jointes}\n"
        f"{d.texte or '(pas de texte)'}\n\n"
        f"Répondre à ce courriel écrit directement à l'expéditeur. Suivi : administration, "
        f"« Demandes reçues à info@ » (no {d.pk}). Le courriel d'origine est joint.\n")
    m.add_attachment(d.octets(), maintype="message", subtype="rfc822", filename="courriel-origine.eml")
    return m


def transferer(d):
    if not settings.PLATEFORME_TRANSFERT_A:
        return False
    try:
        with smtplib.SMTP_SSL(settings.SMTP_HOTE, settings.SMTP_PORT, local_hostname=settings.COURRIEL_HELO,
                              context=ssl.create_default_context(), timeout=30) as s:
            s.login(settings.PLATEFORME_IMAP_UTILISATEUR, settings.PLATEFORME_IMAP_MOT_DE_PASSE)
            s.send_message(courriel_de_transfert(d))
    except (OSError, smtplib.SMTPException) as e:
        DemandeSite.objects.filter(pk=d.pk).update(essais_transfert=d.essais_transfert + 1, erreur_transfert=str(e)[:300])
        log.warning("demande %s : transfert pas parti (%s)", d.pk, e)
        return False
    DemandeSite.objects.filter(pk=d.pk).update(transferee_le=timezone.now(), essais_transfert=d.essais_transfert + 1, erreur_transfert="")
    log.info("demande %s transférée", d.pk)
    return True


def lire():
    """Retourne le nombre de nouvelles demandes gardées."""
    nouvelles = 0
    with imaplib.IMAP4_SSL(settings.IMAP_HOTE, settings.IMAP_PORT, ssl_context=ssl.create_default_context(), timeout=60) as i:
        i.login(settings.PLATEFORME_IMAP_UTILISATEUR, settings.PLATEFORME_IMAP_MOT_DE_PASSE)
        i.select("INBOX", readonly=True)
        uidvalidite = int(i.response("UIDVALIDITY")[1][0])
        dernier = max(DemandeSite.objects.filter(uidvalidite=uidvalidite).values_list("uid", flat=True), default=0)
        _, d = i.uid("search", None, f"UID {dernier + 1}:*")
        for uid in sorted(int(x) for x in d[0].split() if int(x) > dernier)[:PAR_PASSE]:
            _, data = i.uid("fetch", str(uid), "(BODY.PEEK[])")
            octets = next((x[1] for x in data if isinstance(x, tuple)), None)
            if octets is None:
                continue
            _, champs = analyser(octets)
            try:
                with transaction.atomic():
                    DemandeSite.objects.create(uidvalidite=uidvalidite, uid=uid, brut=zlib.compress(octets, 6), **champs)
                nouvelles += 1
            except IntegrityError:
                pass  # déjà gardée (deux lectures en même temps)
    return nouvelles


def a_transferer():
    return DemandeSite.objects.filter(transferee_le=None, essais_transfert__lt=ESSAIS_MAX).exclude(
        statut__in=[DemandeSite.Statut.AUTOMATIQUE, DemandeSite.Statut.POURRIEL]).order_by("pk")
