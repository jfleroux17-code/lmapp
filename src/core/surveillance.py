"""Surveillance de LMAPP (PRD 6.7), par un service à part du worker (`manage.py surveiller`, service
`surveillance` du Compose de la prod) : il peut ainsi signaler un worker bloqué.

Vérifications :
  - graves (texto et courriel) : site en HTTPS (à travers Caddy), base, worker (battement de Procrastinate),
    file de tâches (tâche en attente depuis 10 minutes, sauf le géocodage, lent exprès; message « En file » depuis 10 minutes);
  - à surveiller (courriel seulement) : disque à 70 % et plus, sauvegarde de plus de 13 heures, certificat qui
    expire dans moins de 14 jours, lecture de la boîte courriel en erreur, boîte pleine à 90 %.
Une alerte part au 2e échec de suite pour le HTTPS (un raté isolé n'est pas une panne), au 1er pour le reste;
elle est répétée toutes les 6 heures tant que ça dure, et un message « Rétabli » suit.
Silence (décision de JF, 9 novembre 2026) : pendant un déploiement ou une mise en service, aucune alerte de
panne ne part (`sh outils/silence.sh <minutes>`, appelé par `outils/deployer_prod.sh`; fichier témoin
LMAPP_SILENCE_FICHIER, monté en lecture seule), ni pendant les GRACE premières minutes après le démarrage du
service (le worker redémarre en même temps). Les vérifications continuent : une panne qui dure encore à la
fin du silence est signalée normalement. Un « Rétabli » pendant le silence part par courriel seulement.
Ce que ce service ne voit pas : ld1 éteint au complet ou le routeur en panne. Pour ça, une vérification
externe de /sante/ (ex. UptimeRobot), chez JF.
"""
import logging
import shutil
import socket
import ssl
import time
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from django.conf import settings
from django.db import connection
from django.utils import timezone

log = logging.getLogger("lmapp.surveillance")

GRAVES = {"https", "base", "worker", "file"}
SEUIL_ECHECS = {"https": 2}
REPETER = timedelta(hours=6)
GRACE = timedelta(minutes=3)


def silence_jusqu_a():
    """Fin du silence demandé (outils/silence.sh), ou None. Fichier absent ou illisible : pas de silence."""
    try:
        with open(settings.LMAPP_SILENCE_FICHIER) as f:
            fin = timezone.datetime.fromtimestamp(int(f.read().strip()), tz=timezone.get_current_timezone())
    except (OSError, ValueError, OverflowError):
        return None
    return fin if fin > timezone.now() else None


def _hotes():
    return settings.LMAPP_SURVEILLANCE_HOTES or [h for h in settings.ALLOWED_HOSTS
                                                 if h not in ("localhost", "127.0.0.1", settings.LMAPP_HOTE_ADMIN) and "." in h]


def verifier_https():
    """Chaque site, à travers Caddy (réseau edge) : /sante/ en 200 avec la base, et jours restants au certificat."""
    resultats = {}
    caddy = settings.LMAPP_PROXIES_DE_CONFIANCE[0] if settings.LMAPP_PROXIES_DE_CONFIANCE else "127.0.0.1"
    for hote in _hotes():
        try:
            with socket.create_connection((caddy, 443), timeout=10) as brut:
                with ssl.create_default_context().wrap_socket(brut, server_hostname=hote) as s:
                    reste = (ssl.cert_time_to_seconds(s.getpeercert()["notAfter"]) - time.time()) / 86400
                    s.sendall(f"GET /sante/ HTTP/1.1\r\nHost: {hote}\r\nUser-Agent: LMAPP-surveillance\r\nConnection: close\r\n\r\n".encode())
                    reponse = b""
                    while len(reponse) < 4096:
                        bout = s.recv(1024)
                        if not bout:
                            break
                        reponse += bout
            premiere = reponse.split(b"\r\n", 1)[0].decode(errors="replace")
            ok = " 200 " in premiere + " " and b'"base": "ok"' in reponse
            resultats[hote] = (ok, "" if ok else f"réponse « {premiere[:80]} »", reste)
        except (OSError, ssl.SSLError, KeyError, ValueError) as e:
            resultats[hote] = (False, f"{type(e).__name__} : {e}"[:150], None)
    return resultats


def verifier_base():
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
        return True, ""
    except Exception as e:  # noqa: BLE001 : toute panne de la base compte
        connection.close()
        return False, f"{type(e).__name__} : {e}"[:150]


def verifier_worker():
    with connection.cursor() as c:
        c.execute("SELECT max(last_heartbeat) FROM procrastinate_workers")
        dernier = c.fetchone()[0]
    if dernier is None:
        return False, "aucun worker inscrit"
    retard = timezone.now() - dernier
    return retard < timedelta(minutes=3), f"dernier signe de vie il y a {int(retard.total_seconds() // 60)} min"


def verifier_file():
    from communications.models import Message

    limite = timezone.now() - timedelta(minutes=10)
    with connection.cursor() as c:
        c.execute("SELECT count(*) FROM procrastinate_jobs j WHERE j.status = 'todo' AND j.queue_name <> 'geocodage' "
                  "AND coalesce(j.scheduled_at, '-infinity') <= %s "
                  "AND EXISTS (SELECT 1 FROM procrastinate_events e WHERE e.job_id = j.id AND e.type = 'deferred' AND e.at <= %s)",
                  [limite, limite])
        attente = c.fetchone()[0]
        c.execute("SELECT count(*) FROM procrastinate_jobs j WHERE j.status = 'doing' AND NOT EXISTS "
                  "(SELECT 1 FROM procrastinate_events e WHERE e.job_id = j.id AND e.type = 'started' AND e.at > %s)",
                  [timezone.now() - timedelta(minutes=30)])
        longues = c.fetchone()[0]
    en_file = Message.objects.filter(statut=Message.Statut.EN_FILE, modifie_le__lte=limite).count()
    if attente or longues or en_file:
        return False, f"{attente} tâche(s) en attente depuis 10 min, {longues} en cours depuis 30 min, {en_file} message(s) « En file » depuis 10 min"
    return True, ""


def verifier_disque():
    u = shutil.disk_usage("/")
    pct = 100 * u.used / u.total
    return pct < settings.LMAPP_DISQUE_SEUIL, f"disque de ld1 à {pct:.0f} % ({u.free / 1e9:.0f} Go libres; seuil {settings.LMAPP_DISQUE_SEUIL} %)"


def verifier_sauvegarde():
    try:
        with open(settings.LMAPP_SAUVEGARDE_TEMOIN) as f:
            quand = int(f.read().strip())
    except (OSError, ValueError) as e:
        return False, f"témoin de sauvegarde illisible ({e})"
    heures = (time.time() - quand) / 3600
    return heures < 13, f"dernière sauvegarde réussie il y a {heures:.0f} heures"


def verifier_boite():
    from communications.models import EtatBoite

    if not settings.COURRIEL_LECTURE_ACTIVE:
        return True, ""
    problemes = []
    for e in EtatBoite.objects.select_related("entreprise"):
        if e.erreur and e.lue_le and timezone.now() - e.lue_le > timedelta(minutes=30):
            problemes.append(f"{e} : {e.erreur[:80]}")
        if e.quota_max_ko and e.quota_utilise_ko and e.quota_utilise_ko >= 0.9 * e.quota_max_ko:
            problemes.append(f"{e} : boîte pleine à {100 * e.quota_utilise_ko // e.quota_max_ko} %")
    return not problemes, "; ".join(problemes)


def tout_verifier(complet=True):
    """{clé: (ok, détail)}. `complet` : aussi les vérifications lentes à changer (disque, sauvegarde, boîte, certificats)."""
    r = {}
    for hote, (ok, detail, jours) in verifier_https().items():
        r[f"https {hote}"] = (ok, detail)
        if complet and jours is not None:
            r[f"certificat {hote}"] = (jours >= 14, f"certificat de {hote} : expire dans {jours:.0f} jours")
    r["base"] = verifier_base()
    if r["base"][0]:
        r["worker"] = verifier_worker()
        r["file"] = verifier_file()
        if complet:
            r["boite"] = verifier_boite()
    if complet:
        r["disque"] = verifier_disque()
        r["sauvegarde"] = verifier_sauvegarde()
    return r


# Envoi des alertes : directement (pas par Message ni par le worker, qui est peut-être justement en panne)

def compte_alertes():
    """(adresse, mot de passe) d'envoi des alertes : la boîte de la plateforme (info@), sinon celle du déneigeur."""
    if settings.PLATEFORME_IMAP_UTILISATEUR and settings.PLATEFORME_IMAP_MOT_DE_PASSE:
        return settings.PLATEFORME_IMAP_UTILISATEUR, settings.PLATEFORME_IMAP_MOT_DE_PASSE
    return settings.IMAP_UTILISATEUR, settings.IMAP_MOT_DE_PASSE


def envoyer_courriel(sujet, texte):
    import smtplib

    adresse, mot_de_passe = compte_alertes()
    if not (settings.LMAPP_ALERTES_COURRIEL and settings.SMTP_HOTE and adresse):
        return False
    m = EmailMessage()
    m["From"] = formataddr(("Le Déneigeur (surveillance)", adresse))
    m["To"] = settings.LMAPP_ALERTES_COURRIEL
    m["Subject"] = sujet
    m["Message-ID"] = make_msgid(domain=adresse.split("@")[-1])
    m.set_content(texte)
    try:
        with smtplib.SMTP_SSL(settings.SMTP_HOTE, settings.SMTP_PORT, local_hostname=settings.COURRIEL_HELO, timeout=30) as s:
            s.login(adresse, mot_de_passe)
            s.send_message(m)
        return True
    except (OSError, smtplib.SMTPException) as e:
        log.error("alerte par courriel pas partie : %s", e)
        return False


def envoyer_texto(texte):
    from communications import twilio

    if not (settings.LMAPP_ALERTES_TEXTO and settings.LMAPP_ALERTES_TEXTO_DE and settings.TWILIO_ACCOUNT_SID):
        return False
    try:
        twilio.envoyer_texto(settings.LMAPP_ALERTES_TEXTO_DE, settings.LMAPP_ALERTES_TEXTO, texte[:300])
        return True
    except Exception as e:  # noqa: BLE001 : une alerte ratée ne doit jamais arrêter la surveillance
        log.error("alerte par texto pas partie : %s", e)
        return False


class Veilleur:
    """État des alertes, en mémoire : fonctionne même quand la base est en panne."""

    def __init__(self, envoyer_texto=envoyer_texto, envoyer_courriel=envoyer_courriel, maintenant=timezone.now, silence=silence_jusqu_a):
        self.echecs, self.alerte_le, self.envoyer_texto, self.envoyer_courriel, self.maintenant = {}, {}, envoyer_texto, envoyer_courriel, maintenant
        self.silence, self.demarre_le = silence, maintenant()

    def en_silence(self):
        return self.maintenant() - self.demarre_le < GRACE or self.silence() is not None

    def traiter(self, resultats):
        envois = []
        silence = self.en_silence()
        for cle, (ok, detail) in resultats.items():
            genre = cle.split()[0]
            if ok:
                self.echecs.pop(cle, None)
                if self.alerte_le.pop(cle, None) is not None:
                    envois.append((genre, f"Rétabli : {cle}"))
                continue
            self.echecs[cle] = self.echecs.get(cle, 0) + 1
            if self.echecs[cle] < SEUIL_ECHECS.get(genre, 1):
                continue
            derniere = self.alerte_le.get(cle)
            if silence:
                log.info("en silence, pas d'alerte : %s %s", cle, detail)
                continue
            if derniere is None or self.maintenant() - derniere >= REPETER:
                self.alerte_le[cle] = self.maintenant()
                envois.append((genre, f"{'Toujours en panne' if derniere else 'Panne'} : {cle}. {detail}"))
        for genre, texte in envois:
            log.warning("alerte : %s", texte)
            env = "" if settings.LMAPP_ENV == "prod" else f" ({settings.LMAPP_ENV})"
            self.envoyer_courriel(f"[Le Déneigeur{env}] {texte[:120]}", texte + "\n\nSurveillance de ld1 (service « surveillance »).")
            if genre in GRAVES and not silence:
                self.envoyer_texto(f"Le Déneigeur{env} : {texte}")
        return envois


def boucle(intervalle=60, complet_toutes=10):
    v = Veilleur()
    tour = 0
    log.info("surveillance démarrée : %s", ", ".join(_hotes()) or "aucun site")
    while True:
        try:
            v.traiter(tout_verifier(complet=tour % complet_toutes == 0))
            if tour % complet_toutes == 0:
                from core.redemarrage import verifier as redemarrage

                redemarrage()  # audit, point 7 : redémarrage de ld1 confirmé par courriel
        except Exception:  # noqa: BLE001
            log.exception("vérification en erreur")
        tour += 1
        time.sleep(intervalle)
