import tkinter as tk
import unittest
from types import SimpleNamespace

from gui import DokumentenVerwaltung
from preview_manager import DATUM_VORSCHLAG_FARBE


class _Fenster:
    """Nur die Datumsfeld-Methoden des Hauptfensters, mit echtem Tk-Entry (FALLSTRICKE #86)."""
    setze_datum_stil = DokumentenVerwaltung.setze_datum_stil
    datum_aus_liste_tippen = DokumentenVerwaltung.datum_aus_liste_tippen
    datum_feld_betreten = DokumentenVerwaltung.datum_feld_betreten
    datum_vorschlag_zurueck = DokumentenVerwaltung.datum_vorschlag_zurueck


class TestDatumsfeld(unittest.TestCase):
    """Peters Idee 28.10.2026: vermutetes Datum orange hinterlegt, Ziffer in der Liste überschreibt es."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.f = _Fenster()
        self.f.date_entry = tk.Entry(self.root)
        self.f.date_entry_hintergrund = "white"
        self.f.tree_files = tk.Frame(self.root)
        self.f.datum_feld = {"pfad": "x.pdf", "gespeichert": "", "notbehelf": None, "angezeigt": "2025-01-31"}
        self.f.date_entry.insert(0, "2025-01-31")
        self.f.setze_datum_stil(vermutet=True)

    def tearDown(self):
        self.root.destroy()

    def test_vermutet_orange_hinterlegt(self):
        self.assertEqual(self.f.date_entry.cget("background"), DATUM_VORSCHLAG_FARBE)
        self.assertEqual(self.f.date_entry.cget("foreground"), "white")

    def test_ziffer_aus_der_liste_ersetzt_den_vorschlag(self):
        self.assertEqual(self.f.datum_aus_liste_tippen(SimpleNamespace(char="0")), "break")
        self.assertEqual(self.f.date_entry.get(), "0")
        self.assertEqual((self.f.date_entry.cget("foreground"), self.f.date_entry.cget("background")),
                         ("black", "white"))

    def test_andere_tasten_und_gespeichertes_datum_bleiben_in_der_liste(self):
        self.assertIsNone(self.f.datum_aus_liste_tippen(SimpleNamespace(char="a")))
        self.assertIsNone(self.f.datum_aus_liste_tippen(SimpleNamespace(char="")))   # Pfeiltasten
        self.f.setze_datum_stil(vermutet=False)
        self.assertIsNone(self.f.datum_aus_liste_tippen(SimpleNamespace(char="3")))
        self.assertEqual(self.f.date_entry.get(), "2025-01-31")

    def test_esc_stellt_den_vorschlag_wieder_her(self):
        self.f.datum_aus_liste_tippen(SimpleNamespace(char="1"))
        self.f.datum_vorschlag_zurueck()
        self.assertEqual(self.f.date_entry.get(), "2025-01-31")
        self.assertEqual(self.f.date_entry.cget("background"), DATUM_VORSCHLAG_FARBE)

    def test_klick_ins_orange_feld_markiert_alles(self):
        self.f.datum_feld_betreten()
        self.assertEqual(self.f.date_entry.cget("foreground"), "black")
        self.assertTrue(self.f.date_entry.selection_present())

    def test_ungueltig_rot(self):
        self.f.setze_datum_stil(fehler=True)
        self.assertEqual(self.f.date_entry.cget("foreground"), "red")


if __name__ == "__main__":
    unittest.main()
