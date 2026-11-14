"""Suchsyntax und leichte Unschärfe (suchsyntax.py, KONZEPT_MAIL_AUF_ABRUF, Peter 08.11.2026)."""
import datetime
import unittest

import suchsyntax


class TestNormalisiere(unittest.TestCase):
    def test_umlaute_ss_und_leerraum(self):
        self.assertEqual(suchsyntax.normalisiere("  Kündigung\n Straße ÄÖÜ "), "kuendigung strasse aeoeue")


class TestAbstand(unittest.TestCase):
    def test_ein_tippfehler_jeder_art(self):
        for falsch in ("rechnnug", "rechnug", "rechnuung", "rechnzng", "erchnung"):
            with self.subTest(falsch):
                self.assertTrue(suchsyntax.abstand_hoechstens(falsch, "rechnung", 1))

    def test_zwei_fehler_sind_zu_viel_bei_grenze_eins(self):
        self.assertFalse(suchsyntax.abstand_hoechstens("rechnxxg", "rechnung", 1))
        self.assertTrue(suchsyntax.abstand_hoechstens("rechnxxg", "rechnung", 2))

    def test_erlaubte_fehler_nach_laenge(self):
        self.assertEqual([suchsyntax.erlaubte_fehler("x" * n) for n in (4, 5, 8, 9)], [0, 1, 1, 2])


class TestAehnlicheWoerter(unittest.TestCase):
    WORTSCHATZ = {"vivafone", "vivafon", "ahnung", "mahnung", "stromrechnung", "rechnungen", "stromrechnungen",
                  "bank", "dank", "abrechnung"}

    def test_vertauschte_buchstaben(self):
        self.assertEqual(suchsyntax.aehnliche_woerter("vivafnoe", self.WORTSCHATZ), {"vivafone"})

    def test_erster_buchstabe_muss_stimmen(self):
        """Vormessung 08.11.2026: ohne die Regel fand „mahnung“ das Wort „ahnung“."""
        self.assertNotIn("ahnung", suchsyntax.aehnliche_woerter("mahnung", self.WORTSCHATZ))

    def test_wortteile_in_laengeren_woertern(self):
        gefunden = suchsyntax.aehnliche_woerter("rechnug", self.WORTSCHATZ)
        self.assertTrue({"rechnungen", "stromrechnung", "stromrechnungen", "abrechnung"} <= gefunden, gefunden)

    def test_kurze_woerter_nur_genau(self):
        self.assertEqual(suchsyntax.aehnliche_woerter("bank", self.WORTSCHATZ), set())

    def test_woerliche_treffer_sind_keine_varianten(self):
        self.assertNotIn("vivafone", suchsyntax.aehnliche_woerter("vivafone", self.WORTSCHATZ))


class TestGemeinsameSyntax(unittest.TestCase):
    def test_split_terms_wie_im_hauptfenster(self):
        self.assertEqual(suchsyntax.split_terms('Rechnung "Max  Mustermann" 2026'), ["rechnung", "max mustermann", "2026"])
        self.assertEqual(suchsyntax.split_terms('"Ramen"'), ['"ramen"'])

    def test_datum_grenze(self):
        self.assertEqual(suchsyntax.datum_grenze("2024"), datetime.date(2024, 1, 1))
        self.assertEqual(suchsyntax.datum_grenze("02.2024", ende=True), datetime.date(2024, 2, 29))
        self.assertIsNone(suchsyntax.datum_grenze("irgendwann"))


if __name__ == "__main__":
    unittest.main()
