"""Tests für ordnernamen: Namen neuer Ordner der Vollautomatik (Frisch-Versuch 20./21.11.2026). Nur Musterdaten."""
import unittest

import tests  # noqa: F401  (src/ in den Suchpfad)
import auto_pilot
import ordnernamen as o


class TestOhneRechtsform(unittest.TestCase):
    def test_rechtsformen_am_ende(self):
        for alt, neu in (("Musterversicherung AG", "Musterversicherung"), ("Beispielbank eG", "Beispielbank"),
                         ("TSV Musterstadt 1890 e.V.", "TSV Musterstadt 1890"), ("TSV Musterstadt 1890 e.V",
                                                                                 "TSV Musterstadt 1890"),
                         ("Musterwerk Maschinenbau GmbH", "Musterwerk Maschinenbau"),
                         ("Muster Holding GmbH & Co. KG", "Muster Holding"), ("Beispiel UG (haftungsbeschränkt)",
                                                                             "Beispiel")):
            self.assertEqual(o.ohne_rechtsform(alt), neu, alt)

    def test_ohne_rechtsform_oder_zu_kurz_unveraendert(self):
        self.assertEqual(o.ohne_rechtsform("Stadtwerke"), "Stadtwerke")
        self.assertEqual(o.ohne_rechtsform("AG"), "AG")
        self.assertEqual(o.ohne_rechtsform("Agentur Beispiel"), "Agentur Beispiel")


class TestTelefonbuchform(unittest.TestCase):
    def test_firma_als_nachname_vorname(self):
        self.assertTrue(o.ist_firma_in_telefonbuchform("Musterdorf, Autohaus (Service)", "Autohaus Musterdorf GmbH"))
        self.assertTrue(o.ist_firma_in_telefonbuchform("Musterdorf, Autohaus", "Autohaus Musterdorf"))

    def test_person_bleibt(self):
        self.assertFalse(o.ist_firma_in_telefonbuchform("Beispielmann, Kai (Kaminkehrer)", "Kai Beispielmann"))
        self.assertFalse(o.ist_firma_in_telefonbuchform("Beispiel, Dr. med. Eva (Hausarzt)", "Dr. med. Eva Beispiel"))
        self.assertFalse(o.ist_firma_in_telefonbuchform("Neuhaus, Max", "Max Neuhaus"))   # Nachname wie ein Firmenwort

    def test_ohne_komma_nie(self):
        self.assertFalse(o.ist_firma_in_telefonbuchform("Autohaus Musterdorf", "Autohaus Musterdorf GmbH"))


class TestSchreibweiseAusText(unittest.TestCase):
    WOERTER = ["Haustechnik", "Mustergültig", "GmbH", "Beispielmann", "Vorsorgekasse", "Musteria", "QWIE",
               "Zimmerei"]

    def test_lesefehler_der_ki(self):
        self.assertEqual(o.schreibweise_aus_text("Haustchnik Mustergültig GmbH", self.WOERTER),
                         "Haustechnik Mustergültig GmbH")
        self.assertEqual(o.schreibweise_aus_text("Muster", self.WOERTER), "Muster")      # zu kurz für die Unschärfe
        self.assertEqual(o.schreibweise_aus_text("Musterio", self.WOERTER), "Musteria")

    def test_zerrissenes_wort(self):
        self.assertEqual(o.schreibweise_aus_text("Beispielm ann, Kai", self.WOERTER), "Beispielmann, Kai")
        self.assertEqual(o.schreibweise_aus_text("Vor sorgekasse Musterland", self.WOERTER),
                         "Vorsorgekasse Musterland")

    def test_kurze_teile_nicht_zusammenfuegen(self):
        self.assertEqual(o.schreibweise_aus_text("Q wie Quelle", self.WOERTER), "Q wie Quelle")

    def test_klammerzusatz_bleibt(self):
        self.assertEqual(o.schreibweise_aus_text("Mustermann, Max (Zimmerer)", self.WOERTER),
                         "Mustermann, Max (Zimmerer)")

    def test_versalien_aus_dem_briefkopf_nicht_uebernehmen(self):
        self.assertEqual(o.schreibweise_aus_text("Haustchnik", ["HAUSTECHNIK"]), "Haustechnik")

    def test_mehrdeutig_oder_ohne_text_unveraendert(self):
        self.assertEqual(o.schreibweise_aus_text("Meier Bau", ["Maier", "Meyer"]), "Meier Bau")
        self.assertEqual(o.schreibweise_aus_text("Haustchnik", []), "Haustchnik")
        self.assertEqual(o.schreibweise_aus_text("Haustchnik", None), "Haustchnik")

    def test_textwoerter(self):
        self.assertEqual(o.textwoerter("Haustechnik Mustergültig GmbH · Haustechnik 12 ab"),
                         ["Haustechnik", "Mustergültig", "GmbH"])


class TestNeuerOrdnerInDerEntscheidung(unittest.TestCase):
    """Der Weg durch die echte Entscheidung (baue_entscheidung) in einer frischen Sammlung."""
    ORDNER = ["0_Posteingang", "0_Unsicher", "A - B - C - D - E", "F - G - H - I - J", "K - L - M - N - O"]

    def _ent(self, absender, ordnername, woerter=None):
        ki = {"title": "Rechnung März 2026", "absender": absender, "datum": "2026-03-10", "ordnername": ordnername,
              "tags": []}
        return auto_pilot.baue_entscheidung("Scan_0001.pdf", ki, list(self.ORDNER), textwoerter=woerter)

    def test_neuer_ordner_ohne_rechtsform(self):
        e = self._ent("Musterversicherung AG", "Musterversicherung AG")
        self.assertEqual(e["zielordner"].replace("\\", "/"), "K - L - M - N - O/Musterversicherung")

    def test_firma_nicht_in_telefonbuchform(self):
        e = self._ent("Autohaus Musterdorf GmbH", "Musterdorf, Autohaus (Service)")
        self.assertEqual(e["zielordner"].replace("\\", "/"), "A - B - C - D - E/Autohaus Musterdorf")

    def test_lesefehler_aus_der_textebene_berichtigt(self):
        e = self._ent("Haustchnik Mustergültig GmbH", "Haustchnik Mustergültig GmbH",
                      ["Haustechnik", "Mustergültig", "GmbH", "Rechnung"])
        self.assertEqual(e["zielordner"].replace("\\", "/"), "F - G - H - I - J/Haustechnik Mustergültig")


if __name__ == "__main__":
    unittest.main()
