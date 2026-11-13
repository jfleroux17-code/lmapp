"""Résumé des rapports DMARC reçus à dmarc@ledeneigeur.com (audit de sécurité, point 4).

Avant de passer DMARC de « none » à « quarantine » puis « reject », on vérifie que tous les vrais envois du domaine
sont conformes (DKIM et SPF) et qu'aucun expéditeur légitime n'est oublié. Boîte ouverte en lecture seule (rien n'est
marqué lu ni effacé). À lancer dans le worker (l'app n'a pas Internet) :

    docker compose exec worker python manage.py rapports_dmarc [--jours 7]
"""
import email
import gzip
import imaplib
import io
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


def _xml(nom, donnees):
    nom = (nom or "").lower()
    if nom.endswith(".gz"):
        return gzip.decompress(donnees)
    if nom.endswith(".zip"):
        z = zipfile.ZipFile(io.BytesIO(donnees))
        return z.read(z.namelist()[0])
    if nom.endswith(".xml"):
        return donnees
    return None


class Command(BaseCommand):
    help = "Résume les rapports DMARC de la boîte dmarc@ (lecture seule)."

    def add_arguments(self, parser):
        parser.add_argument("--jours", type=int, default=30, help="Rapports reçus depuis ce nombre de jours (30 par défaut).")

    def handle(self, *args, **options):
        if not (settings.IMAP_HOTE and settings.DMARC_IMAP_UTILISATEUR and settings.DMARC_IMAP_MOT_DE_PASSE):
            raise CommandError("DMARC_IMAP_UTILISATEUR et DMARC_IMAP_MOT_DE_PASSE manquent dans le .env.")
        depuis = (datetime.now(timezone.utc) - timedelta(days=options["jours"])).strftime("%d-%b-%Y")
        total, rapports = defaultdict(lambda: [0, 0]), 0  # (source, dkim, spf) : [courriels, rapports]
        politiques = set()
        with imaplib.IMAP4_SSL(settings.IMAP_HOTE, settings.IMAP_PORT, timeout=30) as boite:
            boite.login(settings.DMARC_IMAP_UTILISATEUR, settings.DMARC_IMAP_MOT_DE_PASSE)
            boite.select("INBOX", readonly=True)
            _, ids = boite.search(None, "SINCE", depuis)
            for i in ids[0].split():
                _, d = boite.fetch(i, "(BODY.PEEK[])")
                m = email.message_from_bytes(d[0][1])
                for partie in m.walk():
                    donnees = partie.get_payload(decode=True)
                    if not donnees:
                        continue
                    try:
                        xml = _xml(partie.get_filename() or partie.get_content_type().replace("/", "."), donnees)
                        if xml is None:
                            continue
                        r = ElementTree.fromstring(xml)
                    except Exception:  # noqa: BLE001 : pièce illisible, on passe
                        continue
                    rapports += 1
                    politiques.add(r.findtext("policy_published/p") or "?")
                    for rec in r.findall("record"):
                        row = rec.find("row")
                        cle = (row.findtext("source_ip"), row.findtext("policy_evaluated/dkim"), row.findtext("policy_evaluated/spf"))
                        total[cle][0] += int(row.findtext("count") or 0)
                        total[cle][1] += 1
        self.stdout.write(f"{rapports} rapport(s) depuis {options['jours']} jours; politique publiée : {', '.join(sorted(politiques)) or '?'}")
        conformes = sum(v[0] for (ip, dkim, spf), v in total.items() if dkim == "pass" or spf == "pass")
        echecs = {k: v for k, v in total.items() if not (k[1] == "pass" or k[2] == "pass")}
        for (ip, dkim, spf), v in sorted(total.items(), key=lambda x: -x[1][0]):
            self.stdout.write(f"  {ip:<40} {v[0]:>5} courriel(s)  DKIM {dkim:<5} SPF {spf}")
        self.stdout.write(f"Conformes : {conformes}. Non conformes : {sum(v[0] for v in echecs.values())}"
                          + (" (faux courriels, ou un vrai expéditeur à ajouter au SPF ou à DKIM avant de resserrer)" if echecs else "."))
