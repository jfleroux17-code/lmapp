"""Longueur des textos (décision de JF, 11 novembre 2026) : 201 caractères au plus, signature et liens compris,
accents gardés. Les textos automatiques se raccourcissent; ceux qu'on écrit sont refusés au-delà."""
from django.test import TestCase

from communications import segments
from communications.models import Gabarit, GabaritParDefaut, Genre, Message, verifier_texto


class SegmentsTests(TestCase):
    def test_limite_et_versions(self):
        self.assertFalse(segments.trop_long("é" * 201))
        self.assertTrue(segments.trop_long("é" * 202))
        self.assertEqual(segments.longueur("❄️"), 2)
        self.assertEqual(segments.compter("ê" * 201), 3)  # 3 segments au plus, même avec les accents
        self.assertEqual(segments.premier_qui_entre("x" * 300, "court"), "court")
        self.assertEqual(segments.premier_qui_entre("x" * 300, "y" * 250), "y" * 250)

    def test_gabarit_trop_long_refuse(self):
        erreur, _ = verifier_texto(Genre.DEBUT, "Bonjour, " + "les opérations commencent. " * 10)
        self.assertIn("Trop long pour un texto", erreur)
        self.assertEqual(verifier_texto(Genre.PROXIMITE, "Bonjour, on arrive au {adresse} d'ici {minutes} minutes."), ("", ""))

    def test_avertissement_quand_interac_sera_enleve(self):
        texte = "Bonjour {client}, " + "x" * 120 + " ({factures}). {paiement}"
        erreur, avertissement = verifier_texto(Genre.RELANCE_1, texte)
        self.assertEqual(erreur, "")
        self.assertIn("Interac", avertissement)

    def test_defauts_tiennent(self):
        for g in GabaritParDefaut.objects.all():
            self.assertEqual(verifier_texto(g.genre, g.texte)[0], "", g.genre)
