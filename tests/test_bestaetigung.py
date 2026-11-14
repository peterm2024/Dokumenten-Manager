"""Zentrale Sicherheitsabfragen (bestaetigung.py): abschaltbar über die Einstellungen (07.09.2026)."""
import unittest
from unittest.mock import patch

import bestaetigung


class _Config:
    def __init__(self, **werte):
        self.werte = werte

    def get(self, key, default=None):
        return self.werte.get(key, default)


class TestBestaetigung(unittest.TestCase):

    def tearDown(self):
        bestaetigung.konfigurieren(None)

    def test_ohne_config_wird_immer_gefragt(self):
        with patch("bestaetigung.messagebox.askyesno", return_value=False) as frage:
            self.assertFalse(bestaetigung.frage("Titel", "Text"))
        frage.assert_called_once_with("Titel", "Text")

    def test_standard_ist_fragen(self):
        bestaetigung.konfigurieren(_Config())
        self.assertTrue(bestaetigung.aktiv())
        with patch("bestaetigung.messagebox.askyesno", return_value=True) as frage:
            self.assertTrue(bestaetigung.frage("Titel", "Text", parent="fenster"))
        frage.assert_called_once_with("Titel", "Text", parent="fenster")

    def test_abgeschaltet_gilt_als_ja_ohne_dialog(self):
        bestaetigung.konfigurieren(_Config(bestaetigungen_anzeigen=False))
        self.assertFalse(bestaetigung.aktiv())
        with patch("bestaetigung.messagebox.askyesno") as frage:
            self.assertTrue(bestaetigung.frage("Titel", "Text"))
        frage.assert_not_called()

    def test_kaputte_config_faellt_auf_fragen_zurueck(self):
        class Kaputt:
            def get(self, *a):
                raise RuntimeError("boom")
        bestaetigung.konfigurieren(Kaputt())
        self.assertTrue(bestaetigung.aktiv())


if __name__ == "__main__":
    unittest.main()
