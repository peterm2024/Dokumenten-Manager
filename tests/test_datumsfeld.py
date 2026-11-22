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


class TestKalenderAmDatumsfeld(unittest.TestCase):
    """B4e (Peter 21.11.2026): „▼“/Alt+↓ klappt unter dem Datumsfeld einen Kalender auf, ein Tag wird gespeichert wie
    mit Return. Ohne echtes Fenster."""

    def test_tag_aus_dem_kalender_wird_gespeichert(self):
        from datetime import date
        from unittest.mock import MagicMock
        f = MagicMock()
        DokumentenVerwaltung.datum_aus_kalender(f, date(2026, 7, 20))
        f.date_entry.delete.assert_called_once_with(0, tk.END)
        f.date_entry.insert.assert_called_once_with(0, "2026-07-20")
        f.save_manual_date.assert_called_once_with()

    def test_kalender_zeigt_den_monat_des_feldes(self):
        from unittest.mock import MagicMock, patch
        f = MagicMock()
        f.date_entry.get.return_value = "15.4.60"
        with patch("gui.UIUtils.kalender_aufklappen") as aufklappen:
            self.assertEqual(DokumentenVerwaltung.datum_kalender(f), "break")   # Alt+↓ bewegt sonst den Cursor
        unter, waehle, iso = aufklappen.call_args.args
        self.assertIs(unter, f.datum_zelle)
        self.assertEqual((waehle, iso), (f.datum_aus_kalender, "1960-04-15"))

    def test_knopf_und_kurzbefehl_im_layout(self):
        import inspect
        import layout_builder
        quelle = inspect.getsource(layout_builder)
        self.assertIn('self.app.date_entry.bind("<Alt-Down>", self.app.datum_kalender)', quelle)
        self.assertIn('beschriftung_klickbar(\n            "datum", self.app.datum_kalender', quelle)
        # T0.16 (22.11.2026): kein Knopf mehr im Feld - er nahm bei 125 % ein Drittel der Breite
        self.assertNotIn('ttk.Button(self.app.datum_zelle', quelle)
        self.assertIn('fluss={"datum": self.app.datum_zelle}', quelle)


class TestBeschriftungKlickbar(unittest.TestCase):
    """T0.16 (22.11.2026): bei 125 % nahm der „▼“-Knopf im Feld ein Drittel der Breite - der Auslöser sitzt jetzt in
    der Beschriftung „Datum ▼“, das Feld behält seine Breite."""

    def test_beschriftung_bekommt_pfeil_und_klick(self):
        from unittest.mock import MagicMock, patch
        from dokument_eigenschaften import EigenschaftenPanel
        panel, lbl, befehl = MagicMock(), MagicMock(), MagicMock()
        panel._label.return_value = lbl
        with patch("dokument_eigenschaften.Tooltip"):
            self.assertIs(EigenschaftenPanel.beschriftung_klickbar(panel, "datum", befehl, "Kalender"), lbl)
        panel._label.assert_called_once_with("Datum")
        self.assertEqual(lbl.config.call_args.kwargs["text"], "Datum  ▼")
        ereignis, rueckruf = lbl.bind.call_args.args
        self.assertEqual(ereignis, "<Button-1>")
        rueckruf(None)
        befehl.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
