"""Redémarrage de ld1 confirmé par courriel (audit, point 7)."""
import json
import tempfile
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from core import redemarrage as r

JF = "jf@exemple.test"


class FausseBoite:
    courriels = []

    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def login(self, *a):
        pass

    def select(self, *a, **k):
        pass

    def search(self, *a):
        return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self.courriels)))]

    def fetch(self, i, quoi):
        return "OK", [(b"", self.courriels[int(i) - 1].as_bytes())]


def reponse(texte, de=JF, reponse_a=None, sujet="Re: ld1", mid="<r1@gmail.com>"):
    m = EmailMessage()
    m["From"], m["Subject"], m["Message-ID"] = de, sujet, mid
    if reponse_a:
        m["In-Reply-To"] = reponse_a
    m.set_content(texte)
    return m


class RedemarrageTests(SimpleTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        reglages = override_settings(LMAPP_REDEMARRAGE_DOSSIER=self.tmp.name, LMAPP_REDEMARRAGE_COURRIEL=JF,
                                     SYSTEME_IMAP_UTILISATEUR="system@x", SYSTEME_IMAP_MOT_DE_PASSE="x", IMAP_HOTE="imap.x")
        reglages.enable()
        self.addCleanup(reglages.disable)
        self.envois = []
        self.d = Path(self.tmp.name)

    def envoyer(self, sujet, texte, message_id=None, reponse_a=None):
        self.envois.append((sujet, texte))
        return message_id

    def test_lecture_de_l_heure(self):
        self.assertEqual(r.heure_demandee("4:00"), (4, 0))
        self.assertEqual(r.heure_demandee("4h"), (4, 0))
        self.assertEqual(r.heure_demandee("  16:30 merci"), (16, 30))
        self.assertEqual(r.heure_demandee("Annuler svp"), "annuler")
        self.assertIsNone(r.heure_demandee("je ne sais pas"))
        self.assertIsNone(r.heure_demandee("25:00"))
        self.assertEqual(r.heure_demandee("\n> 4:00\nLe 13 nov. 2026, ld1 a écrit :\n"), None)  # seulement la citation
        maintenant = timezone.make_aware(datetime(2026, 11, 13, 22, 0))
        self.assertEqual(r.prochaine(4, 0, maintenant).strftime("%Y-%m-%dT%H:%M"), "2026-11-14T04:00")
        self.assertEqual(r.prochaine(23, 0, maintenant).strftime("%Y-%m-%dT%H:%M"), "2026-11-13T23:00")

    def test_parcours_complet(self):
        r.verifier(envoyer_courriel=self.envoyer)  # rien de requis : rien
        self.assertEqual(self.envois, [])
        (self.d / "requis").write_text("2026-11-13T10:00:00-05:00\nlinux-image-generic\n")
        r.verifier(envoyer_courriel=self.envoyer)
        avis = json.loads((self.d / "avis.json").read_text())
        self.assertIn(avis["code"], self.envois[0][0])
        self.assertIn("linux-image-generic", self.envois[0][1])
        # Faux courriel (autre expéditeur) et réponse qui ne vise pas cet avis : ignorés
        FausseBoite.courriels = [reponse("4:00", de="pirate@exemple.test", reponse_a=avis["message_id"], mid="<p@x>"),
                                 reponse("4:00", mid="<sans-lien@x>")]
        r.verifier(envoyer_courriel=self.envoyer, lire=FausseBoite)
        self.assertFalse((self.d / "demande").exists())
        # La vraie réponse de JF
        FausseBoite.courriels.append(reponse("4h\n\n> ld1 : redémarrage requis", reponse_a=avis["message_id"]))
        r.verifier(envoyer_courriel=self.envoyer, lire=FausseBoite, maintenant=timezone.make_aware(datetime(2026, 11, 13, 22, 0)))
        self.assertEqual((self.d / "demande").read_text(), "2026-11-14T04:00")
        self.assertIn("prévu le 14/11 à 04:00", self.envois[-1][0])
        r.verifier(envoyer_courriel=self.envoyer, lire=FausseBoite)  # déjà traitée : pas de deuxième confirmation
        self.assertEqual(len(self.envois), 2)
        # Annuler
        FausseBoite.courriels.append(reponse("annuler", reponse_a=avis["message_id"], mid="<r2@gmail.com>"))
        r.verifier(envoyer_courriel=self.envoyer, lire=FausseBoite)
        self.assertFalse((self.d / "demande").exists())
        # Le minuteur root a redémarré : « ld1 est revenu »
        (self.d / "requis").unlink()
        (self.d / "dernier").write_text("2026-11-14T04:00")
        r.verifier(envoyer_courriel=self.envoyer, lire=FausseBoite)
        self.assertIn("revenu", self.envois[-1][0])
        self.assertFalse((self.d / "avis.json").exists())
