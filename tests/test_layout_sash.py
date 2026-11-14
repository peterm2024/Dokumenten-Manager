"""Tests für die Plausibilitätsprüfung der Trennlinien-Positionen (FALLSTRICKE #41).

Hintergrund: ttk.PanedWindow kürzt sashpos() auf die aktuell vorhandene Breite. Wurde die
gespeicherte Position gesetzt, bevor Tk das Fenster vermessen hatte, entstanden Werte wie
[0, 5] — die App startete danach dauerhaft mit zugeklappten linken Spalten. Die reinen
Rechenfunktionen aus gui.py verhindern das und sind hier ohne Tkinter prüfbar.
"""

import unittest

from gui import MIN_SASH, SASH_RESERVE, sashes_gueltig, sashes_passen, standard_sashes, vorschau_zu_schmal


class TestSashesGueltig(unittest.TestCase):

    def test_normale_aufteilung_ist_gueltig(self):
        self.assertTrue(sashes_gueltig([260, 700]))

    def test_zugeklappte_spalten_sind_ungueltig(self):
        """Genau der Wert, der beim Betatest gespeichert wurde."""
        self.assertFalse(sashes_gueltig([0, 5]))

    def test_negative_werte_sind_ungueltig(self):
        self.assertFalse(sashes_gueltig([-10, -5]))

    def test_zweite_linie_muss_rechts_der_ersten_liegen(self):
        self.assertFalse(sashes_gueltig([700, 260]))
        self.assertFalse(sashes_gueltig([260, 260 + MIN_SASH - 1]))

    def test_falsche_laenge_oder_typ(self):
        self.assertFalse(sashes_gueltig([]))
        self.assertFalse(sashes_gueltig([260]))
        self.assertFalse(sashes_gueltig([260, 700, 900]))
        self.assertFalse(sashes_gueltig("260,700"))
        self.assertFalse(sashes_gueltig([None, 700]))

    def test_zahlen_als_text_werden_akzeptiert(self):
        """settings.json ist von Hand editierbar — "260" darf nicht zum Verwerfen führen."""
        self.assertTrue(sashes_gueltig(["260", "700"]))


class TestSashesPassen(unittest.TestCase):

    def test_breites_fenster_passt(self):
        self.assertTrue(sashes_passen([260, 700], 1400))

    def test_noch_nicht_vermessenes_fenster_passt_nie(self):
        """winfo_width() liefert vor dem ersten Layout 1 — dann darf nichts gesetzt werden."""
        self.assertFalse(sashes_passen([260, 700], 1))

    def test_zu_schmales_fenster_passt_nicht(self):
        self.assertFalse(sashes_passen([260, 700], 700 + SASH_RESERVE - 1))
        self.assertTrue(sashes_passen([260, 700], 700 + SASH_RESERVE))

    def test_ungueltige_werte_passen_nie(self):
        self.assertFalse(sashes_passen([0, 5], 1400))


class TestStandardSashes(unittest.TestCase):

    def test_ergebnis_ist_immer_gueltig(self):
        for breite in (800, 1024, 1400, 1920, 3840):
            with self.subTest(breite=breite):
                sashes = standard_sashes(breite)
                self.assertTrue(sashes_gueltig(sashes), sashes)
                self.assertTrue(sashes_passen(sashes, breite), sashes)

    def test_vorschau_zu_schmal(self):
        # Release-Check v0.9.24: Erststart bei großer Schrift, 1400 Pixel: Die Vorschau bekam nur 23 Pixel
        self.assertTrue(vorschau_zu_schmal(1400, 1351))
        self.assertFalse(vorschau_zu_schmal(1400, 923))     # normale Schrift bleibt, wie sie sich ergibt
        self.assertFalse(vorschau_zu_schmal(1, 0))          # noch nicht vermessen

    def test_linke_spalte_bleibt_massvoll(self):
        self.assertLessEqual(standard_sashes(3840)[0], 280)

    def test_mitte_bekommt_den_platz_der_suchleiste(self):
        # Release-Check v0.9.24: Nach „Fensteraufteilung zurücksetzen“ waren Reset und Trefferzahl abgeschnitten
        erste, zweite = standard_sashes(1600, mitte=698)
        self.assertEqual(zweite - erste, 698)
        erste, zweite = standard_sashes(2560, mitte=698)
        self.assertEqual(zweite - erste, 698)

    def test_vorschau_behaelt_ihren_platz_bei_grosser_schrift(self):
        # 125 % Skalierung und Textgröße: Die Suchleiste darf die Vorschau nicht zusammendrücken
        erste, zweite = standard_sashes(1400, mitte=979)
        self.assertGreaterEqual(1400 - zweite, 400)
        self.assertTrue(sashes_passen([erste, zweite], 1400))
        # Ohne Angabe bleibt es bei der gewohnten Aufteilung
        self.assertEqual(standard_sashes(1400), [280, 720])


if __name__ == "__main__":
    unittest.main()
