from datetime import date

from django.template import Context, Template
from django.test import SimpleTestCase

from core.templatetags.dates_qc import date_texte


class DatesQcTests(SimpleTestCase):
    def rendre(self, gabarit, **ctx):
        return Template(gabarit).render(Context(ctx))

    def test_premier_du_mois_et_abreviations(self):
        self.assertEqual(self.rendre('{{ d|date_qc:"j F Y" }}', d=date(2026, 9, 1)), "1er septembre 2026")
        self.assertEqual(self.rendre('{{ d|date_qc:"j M" }} au {{ f|date_qc:"j M" }}', d=date(2026, 11, 1), f=date(2027, 4, 15)),
                         "1er nov. au 15 avr.")
        self.assertEqual(self.rendre('{{ d|date_qc:"j F" }}', d=date(2026, 12, 2)), "2 décembre")
        self.assertEqual(self.rendre('{{ d|date_qc:"j F, H \\h i" }}', d=None), "")
        self.assertEqual(date_texte(date(2026, 10, 1)), "1er octobre 2026")

