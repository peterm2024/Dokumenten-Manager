"""Tests für eingangsstempel: Briefdatum statt Eingangsstempel (Frisch-Versuch 20.11.2026)."""
import unittest

import tests  # noqa: F401  (src/ in den Suchpfad)
import auto_pilot
import eingangsstempel as e

# So kommt der Prüfbrief 1 aus der Textebene: Briefdatum, Fälligkeit im Text, Stempel darunter
BRIEF_DIGITAL = ("Musterversicherung AG\n12.01.2026\nfür Ihre Hausratversicherung wird zum 01.02.2026 der "
                 "Jahresbeitrag fällig.\n16. JAN. 2026\n")


class TestTextdaten(unittest.TestCase):
    def test_stempel_und_briefdatum_getrennt(self):
        d = e.textdaten(BRIEF_DIGITAL)
        self.assertEqual(d["text"], ["2026-01-12", "2026-02-01"])
        self.assertEqual(d["stempel"], [[2026, 1, 16]])

    def test_eingangszeile_ist_stempel_zahlungseingang_nicht(self):
        d = e.textdaten("Eingang 16.01.2026\nZahlungseingang am 20.01.2026\n")
        self.assertEqual(d["stempel"], [[2026, 1, 16]])
        self.assertEqual(d["text"], ["2026-01-20"])

    def test_gemischte_schreibung_ist_kein_stempel(self):
        d = e.textdaten("Musterstadt, 21. Mai 2022\n")
        self.assertEqual(d["stempel"], [])
        self.assertEqual(d["text"], ["2022-05-21"])

    def test_stempel_ohne_jahr_vom_scanner(self):
        self.assertEqual(e.textdaten("24. APR.\n20.04.2026\n")["stempel"], [[0, 4, 24]])

    def test_ohne_textebene_leer(self):
        self.assertEqual(e.textdaten(""), {"text": [], "stempel": []})


class TestBriefdatumStattStempel(unittest.TestCase):
    def test_stempeldatum_wird_briefdatum(self):
        self.assertEqual(e.briefdatum_statt_stempel("2026-01-16", e.textdaten(BRIEF_DIGITAL)), "2026-01-12")

    def test_spaetestes_datum_vor_dem_stempel(self):
        text = "20.04.2026\nIhre Schadenmeldung vom 14.04.2026\n24. APR. 2026\n"
        self.assertEqual(e.briefdatum_statt_stempel("2026-04-24", e.textdaten(text)), "2026-04-20")

    def test_stempel_ohne_jahr_passt_zum_ki_jahr(self):
        self.assertEqual(e.briefdatum_statt_stempel("2026-04-24", e.textdaten("24. APR.\n20.04.2026\n")), "2026-04-20")

    def test_richtiges_ki_datum_bleibt(self):
        self.assertEqual(e.briefdatum_statt_stempel("2026-01-12", e.textdaten(BRIEF_DIGITAL)), "")

    def test_am_selben_tag_eingegangen_bleibt(self):
        text = "Ihr Schreiben vom 02.01.2026\n16.01.2026\n16. JAN. 2026\n"
        self.assertEqual(e.briefdatum_statt_stempel("2026-01-16", e.textdaten(text)), "")

    def test_ohne_datum_davor_bleibt(self):
        self.assertEqual(e.briefdatum_statt_stempel("2022-05-21", e.textdaten("21. MAI 2022\n01.06.2022\n")), "")

    def test_mehr_als_ein_monat_davor_bleibt(self):
        self.assertEqual(e.briefdatum_statt_stempel("2026-03-16", e.textdaten("02.01.2026\n16. MÄR. 2026\n")), "")

    def test_ohne_textdaten_oder_ohne_datum_bleibt(self):
        self.assertEqual(e.briefdatum_statt_stempel("2026-01-16", None), "")
        self.assertEqual(e.briefdatum_statt_stempel("", e.textdaten(BRIEF_DIGITAL)), "")


class TestAblageNimmtBriefdatum(unittest.TestCase):
    """Der Weg durch die echte Entscheidung: baue_entscheidung mit den Textdaten aus lies_dokument."""

    KI = {"title": "Beitragsrechnung Hausrat 2026", "absender": "Musterversicherung AG", "datum": "2026-01-16",
          "ordnername": "Musterversicherung", "tags": []}

    def test_entscheidung_nimmt_briefdatum_und_merkt_den_stempel(self):
        ent = auto_pilot.baue_entscheidung("Scan_0001.pdf", dict(self.KI), ["K - L - M - N - O"],
                                           textdaten=e.textdaten(BRIEF_DIGITAL))
        self.assertEqual(ent["datum"], "2026-01-12")
        self.assertEqual(ent["datum_stempel"], "2026-01-16")
        if ent["neuer_dateiname"]:
            self.assertTrue(ent["neuer_dateiname"].startswith("20260112_"))

    def test_ohne_textdaten_wie_bisher(self):
        ent = auto_pilot.baue_entscheidung("Scan_0001.pdf", dict(self.KI), ["K - L - M - N - O"])
        self.assertEqual(ent["datum"], "2026-01-16")
        self.assertEqual(ent["datum_stempel"], "")


if __name__ == "__main__":
    unittest.main()
