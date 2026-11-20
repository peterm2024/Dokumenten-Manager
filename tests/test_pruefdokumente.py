"""Prüfdokumente für den Benchmark (Etappe 13 Schritt 2, KONZEPT_BENCHMARK.md)."""
import collections
import os
import re
import tempfile
import unittest

import fitz

import pruefdokumente as p

ANFANG_DER_GRUPPE = {"A - B - C - D - E": "ABCDE", "F - G - H - I - J": "FGHIJ", "K - L - M - N - O": "KLMNO",
                     "P - Q - R - S - T": "PQRST", "U - V - W - X - Y - Z": "UVWXYZ"}


class TestSatz(unittest.TestCase):
    def test_satz_ist_eingefroren(self):
        # Peter 20.11.2026: Der Satz liegt gedruckt und eingescannt als fester Download bei - ändert sich ein Brief,
        # passen Benchmark, Download und Scans nicht mehr zusammen. Gewollte Änderung = neuer Satz mit neuem Namen.
        self.assertEqual(p.fingerabdruck(), p.FINGERABDRUCK)

    def test_aufteilung_wie_vereinbart(self):
        # Peter 19.11.2026 (F2): 40 Briefe, 35 für vorhandene Ordner (davon 10 schwer), 5 ohne passenden Ordner
        self.assertEqual([b["nr"] for b in p.BRIEFE], list(range(1, 41)))
        arten = collections.Counter(p.wahrheit(n)["art"] for n in range(1, 41))
        self.assertEqual(arten, {"eindeutig": 25, "schwer": 10, "neu": 5})
        for n in range(1, 41):
            w = p.wahrheit(n)
            self.assertEqual(w["ordner"] is None, w["art"] == "neu", n)
        ordner = {p.wahrheit(n)["ordner"] for n in range(1, 41)} - {None}
        self.assertEqual(len(ordner), 11)
        self.assertTrue(ordner <= set(p.ordner_der_sammlung()))

    def test_ordner_in_der_richtigen_buchstabengruppe(self):
        for o in {a["ordner"] for a in p.ABSENDER.values() if a["ordner"]}:
            gruppe, name = o.split("/")
            self.assertIn(name[0].upper(), ANFANG_DER_GRUPPE[gruppe], o)

    def test_kein_ordnerwort_doppelt(self):
        # Ein gemeinsames Wort zweier Ordner wäre eine selbstgemachte Schwierigkeit (auto_pilot.finde_aehnlichen_ordner)
        woerter = collections.Counter(w.lower() for a in p.ABSENDER.values() if a["ordner"]
                                      for w in re.findall(r"\w+", a["ordner"].split("/")[1]))
        self.assertEqual([w for w, n in woerter.items() if n > 1], [])

    def test_daten_gueltig(self):
        for b in p.BRIEFE:
            self.assertRegex(b["datum"], r"^\d{2}\.\d{2}\.20\d{2}$")
            if b["stempel"]:   # Eingangsstempel kommt nach dem Briefdatum
                tag = lambda d: tuple(reversed(d.split(".")))   # noqa: E731
                self.assertGreater(tag(b["stempel"]), tag(b["datum"]), b["nr"])
        self.assertEqual(p.datum_im_brief(6), "23. Februar 2026")   # Praxis schreibt das Datum aus
        self.assertEqual(p.datum_im_brief(1), "12.01.2026")


class TestNummer(unittest.TestCase):
    def test_nummer_auch_nach_texterkennung(self):
        self.assertEqual(p.nummer_aus_text("… Prüfdokument 017 · KID-Benchmark"), 17)
        self.assertEqual(p.nummer_aus_text("Prufdokument O17"), 17)
        self.assertEqual(p.nummer_aus_text("Pruefdokument 005"), 5)
        self.assertEqual(p.nummer_aus_text("Prüf-dokument 040"), 40)
        self.assertIsNone(p.nummer_aus_text("Prüfdokument 099"))
        self.assertIsNone(p.nummer_aus_text("Rechnung 017"))


class TestSchreiben(unittest.TestCase):
    def test_satz_schreiben_und_wiederfinden(self):
        with tempfile.TemporaryDirectory() as ziel:
            pfade = p.schreibe_satz(ziel)
            self.assertEqual(len(pfade), 40)
            for nr, pfad in enumerate(pfade, 1):
                with fitz.open(pfad) as doc:
                    text = doc[0].get_text()
                    # Brief passt auf eine Seite, dazu ggf. Hinweisseite und Anlage
                    self.assertEqual(doc.page_count, p.seitenzahl(nr), nr)
                    self.assertFalse(doc.metadata.get("subject"), nr)   # keine KID-Felder - wie frisch gescannt
                    for s in doc:
                        self.assertEqual(p.nummer_aus_text(s.get_text()), nr)
                    alles = "".join(s.get_text() for s in doc)
                self.assertIn(p.datum_im_brief(nr), text)
                self.assertIn("Max Mustermann", text)
                # nur Musterkonten - auch im gezeichneten Kleingedruckten
                self.assertTrue(all(i.startswith("DE00") for i in re.findall(r"DE\d\d[ \d]{10,}", alles)), nr)
            with fitz.open(os.path.join(ziel, p.SAMMEL_PDF)) as doc:
                self.assertEqual(doc.page_count, sum(p.seitenzahl(n) for n in range(1, 41)))
            with self.assertRaises(FileExistsError):   # nie überschreiben
                p.schreibe_satz(ziel)


if __name__ == "__main__":
    unittest.main()
