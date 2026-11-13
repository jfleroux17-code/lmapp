"""Redémarrage de ld1 confirmé par courriel (audit de sécurité, point 7, choix de JF du 13 novembre 2026).

Quand Ubuntu demande un redémarrage (correctif du noyau), le minuteur root `outils/redemarrage_hote.sh` écrit
`requis` dans le dossier d'échange. La surveillance (aux 10 minutes, sans aucun droit sur ld1) :
1. envoie à JF un courriel de system@ledeneigeur.com, avec un code unique au hasard (sujet et Message-ID);
2. lit les réponses dans la boîte system@ (lecture seule) : acceptée seulement si elle vient de l'adresse de JF
   (LMAPP_REDEMARRAGE_COURRIEL) ET répond à ce courriel-là (In-Reply-To ou le code); une heure sur 24 heures
   (« 4h », « 4:00 », « 16:30 ») donne la prochaine occurrence; « annuler » annule;
3. écrit `demande` (AAAA-MM-JJTHH:MM, heure locale) et confirme à JF par courriel; le minuteur root redémarre à
   cette heure, surveillance en silence 15 minutes; au retour, un courriel « ld1 est revenu ».
"""
import email
import imaplib
import json
import logging
import re
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid, parseaddr
from pathlib import Path

from django.conf import settings
from django.utils import timezone

log = logging.getLogger(__name__)

HEURE = re.compile(r"(?<![\d:])([01]?\d|2[0-3])\s*(?:[:hH]\s*([0-5]\d)?)?(?![\d:])")


def dossier():
    return Path(settings.LMAPP_REDEMARRAGE_DOSSIER)


def _lire_json(nom):
    try:
        return json.loads((dossier() / nom).read_text())
    except (OSError, ValueError):
        return None


def _ecrire(nom, texte):
    tmp = dossier() / f"{nom}.tmp"
    tmp.write_text(texte)
    tmp.replace(dossier() / nom)


def envoyer(sujet, texte, message_id=None, reponse_a=None):
    adresse, mdp = settings.SYSTEME_IMAP_UTILISATEUR, settings.SYSTEME_IMAP_MOT_DE_PASSE
    if not (adresse and mdp and settings.LMAPP_REDEMARRAGE_COURRIEL and settings.SMTP_HOTE):
        return None
    m = EmailMessage()
    m["From"] = formataddr(("ld1, serveur du Déneigeur", adresse))
    m["To"] = settings.LMAPP_REDEMARRAGE_COURRIEL
    m["Subject"] = sujet
    m["Message-ID"] = message_id or make_msgid(domain="ledeneigeur.com")
    if reponse_a:
        m["In-Reply-To"] = m["References"] = reponse_a
    m.set_content(texte)
    with smtplib.SMTP_SSL(settings.SMTP_HOTE, settings.SMTP_PORT, local_hostname=settings.COURRIEL_HELO, timeout=30) as s:
        s.login(adresse, mdp)
        s.send_message(m)
    return m["Message-ID"]


def heure_demandee(texte):
    """Première ligne utile de la réponse (sans la citation) : « annuler », ou (heure, minute) sur 24 heures."""
    for ligne in (texte or "").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith(">"):
            continue
        if re.match(r"^(le |on )?.{0,80}(a écrit|wrote)\s*:?$", ligne, re.I):
            break
        if re.search(r"\bannul", ligne, re.I):
            return "annuler"
        m = HEURE.search(ligne)
        if m:
            return int(m.group(1)), int(m.group(2) or 0)
        return None
    return None


def prochaine(h, mi, maintenant=None):
    maintenant = timezone.localtime(maintenant or timezone.now())
    cible = maintenant.replace(hour=h, minute=mi, second=0, microsecond=0)
    if cible <= maintenant + timedelta(minutes=2):
        cible += timedelta(days=1)
    return cible


def _texte(m):
    if m.is_multipart():
        for p in m.walk():
            if p.get_content_type() == "text/plain" and not p.get_filename():
                return p.get_payload(decode=True).decode(p.get_content_charset() or "utf-8", "replace")
        return ""
    return m.get_payload(decode=True).decode(m.get_content_charset() or "utf-8", "replace")


def reponses(avis, lire=None):
    """Réponses de JF au courriel d'avis, pas encore traitées : [(message_id, texte)]."""
    attendu = settings.LMAPP_REDEMARRAGE_COURRIEL.lower()
    sortie = []
    with (lire or imaplib.IMAP4_SSL)(settings.IMAP_HOTE, settings.IMAP_PORT, timeout=30) as boite:
        boite.login(settings.SYSTEME_IMAP_UTILISATEUR, settings.SYSTEME_IMAP_MOT_DE_PASSE)
        boite.select("INBOX", readonly=True)
        _, ids = boite.search(None, "SINCE", (datetime.fromisoformat(avis["envoye_le"]) - timedelta(days=1)).strftime("%d-%b-%Y"))
        for i in ids[0].split():
            _, d = boite.fetch(i, "(BODY.PEEK[])")
            m = email.message_from_bytes(d[0][1])
            mid = (m["Message-ID"] or "").strip()
            if mid in avis.get("traites", []):
                continue
            if parseaddr(m["From"] or "")[1].lower() != attendu:
                continue
            lien = f"{m['In-Reply-To'] or ''} {m['References'] or ''}"
            if avis["message_id"] not in lien and avis["code"] not in (m["Subject"] or ""):
                continue
            sortie.append((mid, _texte(m)))
    return sortie


def verifier(maintenant=None, lire=None, envoyer_courriel=None):
    """Appelée par la surveillance aux 10 minutes. Ne lève jamais : une erreur est notée au journal."""
    envoyer_courriel = envoyer_courriel or envoyer
    try:
        d = dossier()
        if not d.is_dir():
            return
        avis = _lire_json("avis.json")
        dernier = d / "dernier"
        if dernier.exists():  # le minuteur root a redémarré ld1 : il est revenu
            heure = dernier.read_text().strip()
            dernier.unlink()
            (d / "avis.json").unlink(missing_ok=True)
            envoyer_courriel("ld1 est revenu après le redémarrage",
                             f"Le redémarrage prévu pour {heure.replace('T', ' à ')} est fait; ld1 et l'app répondent de nouveau.",
                             reponse_a=avis["message_id"] if avis else None)
            return
        requis = d / "requis"
        if not requis.exists():
            if avis:
                (d / "avis.json").unlink(missing_ok=True)
                (d / "demande").unlink(missing_ok=True)
            return
        if avis is None:
            code = secrets.token_hex(4).upper()
            paquets = [l for l in requis.read_text().splitlines()[1:] if l.strip()]
            mid = make_msgid(idstring=f"redemarrage-{code}", domain="ledeneigeur.com")
            envoyer_courriel(
                f"ld1 : redémarrage requis [{code}]",
                "Ubuntu a installé un correctif qui demande un redémarrage de ld1"
                + (f" ({', '.join(paquets[:5])})" if paquets else "") + ".\n\n"
                "Pour confirmer, répondez à ce courriel avec l'heure voulue, sur 24 heures, sur la première ligne : "
                "par exemple « 4:00 », « 4h » ou « 16:30 ». ld1 redémarrera à la prochaine occurrence de cette heure "
                "(une à deux minutes de coupure; la surveillance est mise en silence). Choisir un moment hors tempête.\n\n"
                "Répondre « annuler » annule un redémarrage prévu. Sans réponse, rien n'est fait.\n\n"
                f"Code de cette demande : {code}", message_id=mid)
            _ecrire("avis.json", json.dumps({"code": code, "message_id": mid, "envoye_le": timezone.now().isoformat(), "traites": []}))
            return
        for mid, texte in reponses(avis, lire=lire):
            avis["traites"].append(mid)
            choix = heure_demandee(texte)
            if choix == "annuler":
                (d / "demande").unlink(missing_ok=True)
                envoyer_courriel(f"ld1 : redémarrage annulé [{avis['code']}]", "Annulé : aucun redémarrage n'est prévu. "
                                 "Répondez avec une heure (ex. 4:00) quand vous voudrez le faire.", reponse_a=mid)
            elif choix is None:
                envoyer_courriel(f"ld1 : heure pas comprise [{avis['code']}]",
                                 "Je n'ai pas trouvé d'heure sur la première ligne de votre réponse. Répondez par exemple « 4:00 », "
                                 "« 4h » ou « 16:30 » (24 heures), ou « annuler ».", reponse_a=mid)
            else:
                cible = prochaine(*choix, maintenant=maintenant)
                _ecrire("demande", cible.strftime("%Y-%m-%dT%H:%M"))
                envoyer_courriel(f"ld1 : redémarrage prévu le {cible:%d/%m} à {cible:%H:%M} [{avis['code']}]",
                                 f"C'est noté : ld1 redémarrera le {cible:%d/%m/%Y} à {cible:%H:%M} (heure de Montréal). "
                                 "Répondez « annuler » pour annuler, ou une autre heure pour changer.", reponse_a=mid)
            _ecrire("avis.json", json.dumps(avis))
    except Exception:  # noqa: BLE001 : la surveillance ne doit jamais tomber pour ça
        log.exception("redémarrage par courriel : erreur")
