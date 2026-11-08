"""Envoi d'un courriel par le serveur de courriel de l'entreprise (SMTP en SSL), sans dépendance de plus.

Appelé par le worker seulement (l'app n'a pas de sortie Internet). Après l'envoi, une copie
est déposée dans le dossier des envoyés (IMAP) : Louis la voit s'il ouvre sa boîte ailleurs.
"""
import imaplib
import logging
import smtplib
import ssl
import time
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import formatdate, make_msgid

from django.conf import settings
from django.template.loader import render_to_string

from core import telephone
from communications.erreurs import Incertain, Indisponible, Refuse

log = logging.getLogger(__name__)


def construire(message):
    ent = message.entreprise
    adresse = ent.courriel_reponse
    m = EmailMessage()
    m["From"] = Address(display_name=ent.nom, addr_spec=adresse)
    m["To"] = message.destinataire
    m["Subject"] = message.sujet or ent.nom
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid(idstring=f"lmapp{message.pk}", domain=adresse.split("@")[1])
    m.set_content(message.contenu)
    m.add_alternative(render_to_string("communications/courriel.html", {"m": message, "ent": ent, "telephone": telephone.afficher(ent.telephone),
                                                                        "paragraphes": message.contenu.split("\n\n")}),
                      subtype="html")
    if message.facture_id:
        from facturation import pdf

        m.add_attachment(pdf.rendre(message.facture), maintype="application", subtype="pdf",
                         filename=pdf.nom_fichier(message.facture))
    return m


def _contexte_ssl():
    return ssl.create_default_context()


def envoyer_courriel(message):
    """Retourne le Message-ID du courriel envoyé."""
    m = construire(message)
    try:
        s = smtplib.SMTP_SSL(settings.SMTP_HOTE, settings.SMTP_PORT, local_hostname=settings.COURRIEL_HELO,
                             context=_contexte_ssl(), timeout=30)
    except (OSError, smtplib.SMTPException) as e:
        raise Indisponible(f"Serveur de courriel injoignable : {e}") from e
    try:
        try:
            s.login(settings.IMAP_UTILISATEUR, settings.IMAP_MOT_DE_PASSE)
        except smtplib.SMTPAuthenticationError as e:
            raise Refuse("Le serveur de courriel refuse l'identifiant ou le mot de passe.") from e
        except (OSError, smtplib.SMTPException) as e:
            raise Indisponible(f"Serveur de courriel : {e}") from e
        try:
            s.send_message(m)
        except smtplib.SMTPRecipientsRefused as e:
            code, texte = next(iter(e.recipients.values()))
            erreur = (Indisponible if 400 <= code < 500 else Refuse)(f"Destinataire refusé ({code}) : {texte.decode(errors='replace')[:150]}")
            raise erreur from e
        except (smtplib.SMTPSenderRefused, smtplib.SMTPDataError) as e:
            erreur = (Indisponible if 400 <= e.smtp_code < 500 else Refuse)(f"Courriel refusé ({e.smtp_code}) : {e.smtp_error.decode(errors='replace')[:150]}")
            raise erreur from e
        except (OSError, smtplib.SMTPException) as e:  # coupure pendant l'envoi : peut-être parti
            raise Incertain(f"Pas de confirmation du serveur de courriel ({e}) : vérifier les envoyés avant de renvoyer.") from e
    finally:
        try:
            s.quit()
        except (OSError, smtplib.SMTPException):
            pass
    _copie_envoyes(m)
    return m["Message-ID"]


def _copie_envoyes(m):
    if not settings.IMAP_HOTE:
        return
    try:
        with imaplib.IMAP4_SSL(settings.IMAP_HOTE, settings.IMAP_PORT, ssl_context=_contexte_ssl(), timeout=30) as i:
            i.login(settings.IMAP_UTILISATEUR, settings.IMAP_MOT_DE_PASSE)
            i.append(settings.IMAP_DOSSIER_ENVOYES, r"(\Seen)", imaplib.Time2Internaldate(time.time()), m.as_bytes())
    except Exception as e:  # le courriel est parti : une copie manquante ne doit pas le faire passer en échec
        log.warning("copie dans les envoyés impossible : %s", e)
