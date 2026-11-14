"""Tests für Konstanten des Layout-Aufbaus."""

import unittest

import layout_builder


class TestStandardSpalten(unittest.TestCase):
    def test_tags_gehoeren_zum_standard(self):
        # Erststart und „Fensteraufteilung zurücksetzen“ nutzen dieselbe Liste (T0.10, 25.10.2026)
        self.assertEqual(layout_builder.STANDARD_SPALTEN, ("datum", "titel", "tags", "ordner"))


if __name__ == "__main__":
    unittest.main()


class TestSpaltenbreitenSkalieren(unittest.TestCase):
    """Release-Check T0.16: bei 125 % + Textgröße 125 % war das Datum abgeschnitten."""

    def test_hin_und_zurueck_ergibt_dieselben_100_prozent_werte(self):
        from layout_builder import breiten_fuer_bildschirm, breiten_zum_speichern, STANDARD_BREITEN
        for faktor in (1.0, 1.25, 1.53):
            bildschirm = breiten_fuer_bildschirm(STANDARD_BREITEN, faktor)
            self.assertEqual(breiten_zum_speichern(bildschirm, faktor), STANDARD_BREITEN)

    def test_datum_waechst_mit(self):
        from layout_builder import breiten_fuer_bildschirm
        self.assertEqual(breiten_fuer_bildschirm({"datum": 85}, 1.0), {"datum": 85})
        self.assertEqual(breiten_fuer_bildschirm({"datum": 85}, 1.53), {"datum": 130})

    def test_mindestbreiten_fuer_alle_spalten(self):
        from layout_builder import MINDEST_BREITEN, STANDARD_BREITEN, GESPEICHERTE_SPALTEN
        self.assertEqual(set(MINDEST_BREITEN), set(STANDARD_BREITEN))
        self.assertTrue(set(GESPEICHERTE_SPALTEN) <= set(STANDARD_BREITEN))

