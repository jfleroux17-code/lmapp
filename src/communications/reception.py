"""Courriels reçus dans la boîte de l'entreprise (PRD E5) : rattachés au client, rebonds, rapports ignorés.

`traiter(entreprise, octets)` reçoit un courriel brut (RFC 822) et retourne le Message créé, ou None
si le courriel est ignoré (doublon, rapport DMARC, copie de nos envois) ou si c'est un rebond
(le message d'origine passe alors en échec).
"""
import email
import hashlib
import html
import re
from email import policy
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from django.utils import timezone
from django.utils.html import strip_tags

from clients.models import Client
from communications.models import Genre, Message

NOTRE_ID = re.compile(r"\.lmapp(\d+)@")  # Message-ID des courriels de l'app (communications.courriel.construire)
CITATION = re.compile(r"^(>|Le .{3,200}a écrit\s*:|On .{3,200}wrote:|-{2,} ?(Original Message|Message d'origine)|De ?: .+@|From: .+@)",
                      re.MULTILINE | re.IGNORECASE)
LONGUEUR_MAX = 10000


def _corps(msg):
    partie = msg.get_body(preferencelist=("plain", "html"))
    if partie is None:
        return ""
    try:
        texte = partie.get_content()
    except (LookupError, ValueError):
        texte = partie.get_payload(decode=True).decode("utf-8", errors="replace")
    if partie.get_content_type() == "text/html":
        texte = html.unescape(strip_tags(re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", texte)))
    return texte


def nettoyer(texte):
    """Garde la réponse, pas l'historique cité en dessous."""
    texte = texte.replace("\r\n", "\n")
    m = CITATION.search(texte)
    if m and m.start() > 0:
        texte = texte[:m.start()]
    texte = re.sub(r"\n{3,}", "\n\n", texte).strip()
    return texte[:LONGUEUR_MAX]


def _notre_message(entreprise, *textes):
    for t in textes:
        for pk in NOTRE_ID.findall(t or ""):
            m = Message.objects.filter(pk=int(pk), entreprise=entreprise, sens=Message.Sens.SORTANT).first()
            if m:
                return m
    return None


def _est_rebond(expediteur, msg):
    local = expediteur.split("@")[0]
    return local in ("mailer-daemon", "postmaster") or msg.get_content_type() == "multipart/report"


def _raison_du_rebond(brut):
    m = re.search(r"Diagnostic-Code:\s*(?:smtp;\s*)?(.+)", brut, re.IGNORECASE) or re.search(r"Status:\s*(\S+)", brut, re.IGNORECASE)
    return (m.group(1).strip() if m else "adresse refusée")[:200]


def traiter(entreprise, octets):
    msg = email.message_from_bytes(octets, policy=policy.default)
    mid = (str(msg.get("Message-ID", "")).strip() or "sha256:" + hashlib.sha256(octets).hexdigest())[:300]
    if Message.objects.filter(entreprise=entreprise, message_id_externe=mid).exists():
        return None
    expediteur = parseaddr(str(msg.get("From", "")))[1].lower()
    sujet = str(msg.get("Subject", "")).strip()[:200]
    if expediteur == (entreprise.courriel_reponse or "").lower():
        return None  # une copie de nos propres envois
    if sujet.lower().startswith("report domain:") or "dmarc" in expediteur:
        return None  # rapport DMARC quotidien, pas un message de client
    brut = octets.decode("utf-8", errors="replace")
    if _est_rebond(expediteur, msg):
        origine = _notre_message(entreprise, brut)
        if origine and origine.statut != Message.Statut.ECHEC:
            origine.statut, origine.erreur = Message.Statut.ECHEC, f"Courriel revenu : {_raison_du_rebond(brut)}"
            origine.save(update_fields=["statut", "erreur", "modifie_le"])
        return None
    origine = _notre_message(entreprise, str(msg.get("In-Reply-To", "")), str(msg.get("References", "")))
    client = origine.client if origine and origine.client_id else None
    if client is None and expediteur:
        client = Client.objects.filter(entreprise=entreprise, courriel__iexact=expediteur).order_by("pk").first()
    try:
        date = parsedate_to_datetime(str(msg["Date"])) if msg.get("Date") else timezone.now()
        if timezone.is_naive(date):
            date = timezone.make_aware(date)
    except (TypeError, ValueError):
        date = timezone.now()
    contenu = nettoyer(_corps(msg))
    pieces = [p.get_filename() or "sans nom" for p in msg.iter_attachments()]
    if pieces:
        contenu += f"\n\n[{len(pieces)} pièce{'s' if len(pieces) > 1 else ''} jointe{'s' if len(pieces) > 1 else ''} : " \
                   f"{', '.join(pieces)[:200]}, à voir dans la boîte courriel]"
    return Message.objects.create(
        entreprise=entreprise, client=client, genre=Genre.RECU, canal=Message.Canal.COURRIEL, sens=Message.Sens.ENTRANT,
        statut=Message.Statut.RECU, lu=False, expediteur=expediteur,
        destinataire=", ".join(a for _, a in getaddresses([str(msg.get("To", ""))]))[:254], sujet=sujet,
        contenu=contenu or "(message vide)", reponse_a=origine, message_id_externe=mid, envoye_le=date,
    )
