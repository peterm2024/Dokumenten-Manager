"""
Tests für suchfeld.py (13.09.2026): bekannte Tags im Suchtext erkennen, Entry-kompatibles
Suchfeld auf tk.Text-Basis, Tag-Autovervollständigung im Suchfeld (Leerzeichen als Trenner,
Phrasen in Anführungszeichen).
"""

import tkinter as tk
import unittest
from unittest.mock import MagicMock

import suchfeld
from suchfeld import SuchFeld, bekannte_tag_spannen
from tag_autocomplete import TagAutocomplete


class TestBekannteTagSpannen(unittest.TestCase):
    TAGS = ["Rechnung", "Versicherung", "Musterstraße 12", "Gas"]

    def test_einzelwoerter_egal_wie_geschrieben(self):
        self.assertEqual(bekannte_tag_spannen("rechnung 2021 GAS", self.TAGS), [(0, 8), (14, 17)])

    def test_phrase_in_anfuehrungszeichen_samt_zeichen(self):
        text = 'Versicherung "Musterstraße 12" 2021'
        self.assertEqual(bekannte_tag_spannen(text, self.TAGS), [(0, 12), (13, 30)])

    def test_unbekanntes_und_platzhalter_bleiben_schwarz(self):
        self.assertEqual(bekannte_tag_spannen("Rech* Rechn Heizung", self.TAGS), [])

    def test_leer(self):
        self.assertEqual(bekannte_tag_spannen("", self.TAGS), [])
        self.assertEqual(bekannte_tag_spannen("Rechnung", []), [])


class TestSuchFeldWidget(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.tags = ["Rechnung", "Versicherung", "Musterstraße 12"]
        self.feld = SuchFeld(self.root, lambda: self.tags)
        self.feld.pack()

    def tearDown(self):
        self.root.destroy()

    def test_get_und_delete_wie_entry(self):
        self.feld.setze_text("Rechnung 2021")
        self.assertEqual(self.feld.get(), "Rechnung 2021")
        self.feld.delete(0, tk.END)
        self.assertEqual(self.feld.get(), "")

    def test_bekannte_tags_werden_markiert(self):
        self.feld.setze_text('rechnung "Musterstraße 12" Heizung')
        bereiche = self.feld.tag_ranges(SuchFeld.TAG_NAME)
        texte = [self.feld.get(str(bereiche[i]), str(bereiche[i + 1])) for i in range(0, len(bereiche), 2)]
        self.assertEqual(texte, ["rechnung", '"Musterstraße 12"'])
        self.feld.setze_text("Heizung")
        self.assertEqual(len(self.feld.tag_ranges(SuchFeld.TAG_NAME)), 0)

    def test_markierung_hat_tagbaum_farbe_und_fett(self):
        self.assertEqual(self.feld.tag_cget(SuchFeld.TAG_NAME, "foreground"), suchfeld.TAG_FARBE)
        self.assertEqual(self.feld._fett.cget("weight"), "bold")


class TestSuchAutocomplete(unittest.TestCase):
    """Autovervollständigung im Suchfeld: Leerzeichen trennen, Tags mit Leerzeichen kommen in Anführungszeichen."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = MagicMock()
        self.app.root = self.root
        self.app.tag_manager.get_known_tags.return_value = ["Rechnung", "Rechtsschutz", "Musterstraße 12"]
        self.feld = SuchFeld(self.root, self.app.tag_manager.get_known_tags)
        self.feld.pack()
        self.nachlauf = MagicMock()
        self.ac = TagAutocomplete(self.app, text=self.feld, trenner=None, nach_uebernahme=self.nachlauf)

    def tearDown(self):
        self.root.destroy()

    def _tippe(self, text):
        self.feld.setze_text(text)
        self.feld.mark_set("insert", "end-1c")
        self.ac._on_keyrelease(MagicMock(keysym="r"))

    def test_token_ist_letztes_wort(self):
        self._tippe("Versicherung Rech")
        self.assertEqual(self.ac._matches, ["Rechnung", "Rechtsschutz"])
        self.ac._insert_choice("Rechnung")
        self.assertEqual(self.feld.get(), "Versicherung Rechnung ")
        self.nachlauf.assert_called_once()

    def test_tag_mit_leerzeichen_wird_phrase(self):
        self._tippe("2021 Muster")
        self.assertEqual(self.ac._matches, ["Musterstraße 12"])
        self.ac._insert_choice("Musterstraße 12")
        self.assertEqual(self.feld.get(), '2021 "Musterstraße 12" ')

    def test_offene_phrase_zaehlt_als_ein_begriff(self):
        self._tippe('Rechnung "Muster')
        self.assertEqual(self.ac._current_token(), "Muster")
        self.ac._insert_choice("Musterstraße 12")
        self.assertEqual(self.feld.get(), 'Rechnung "Musterstraße 12" ')

    def test_fertig_getipptes_tag_zeigt_kein_popup(self):
        self._tippe("Rechnung")
        self.assertFalse(self.ac._visible())


class TestTagsFeldUnveraendert(unittest.TestCase):
    """Das Tags-Feld behält Komma-Trennung und Ausschluss schon vergebener Tags."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = MagicMock()
        self.app.root = self.root
        self.app.entry_tags = tk.Text(self.root, height=1)
        self.app.entry_tags.pack()
        self.app.tag_manager.get_known_tags.return_value = ["Rechnung", "Rechtsschutz"]
        self.app.tag_manager._get_current_tags.return_value = ["Rechnung"]
        self.ac = TagAutocomplete(self.app)

    def tearDown(self):
        self.root.destroy()

    def test_komma_trenner_und_ausschluss(self):
        self.app.entry_tags.insert("1.0", "Rechnung, Rech")
        self.app.entry_tags.mark_set("insert", "end-1c")
        self.ac._on_keyrelease(MagicMock(keysym="h"))
        self.assertEqual(self.ac._matches, ["Rechtsschutz"])
        self.ac._insert_choice("Rechtsschutz")
        self.assertEqual(self.app.entry_tags.get("1.0", "end-1c"), "Rechnung, Rechtsschutz, ")
        self.app.tag_manager.sync_tag_tree_selection.assert_called_once()
        self.app.save_manager.trigger_autosave.assert_called_once()


class TestReturnNurNachPfeiltaste(unittest.TestCase):
    """Return übernimmt einen Vorschlag nur nach Pfeiltaste (Fund T0.4: „Test“ wurde zu „Testament“)."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = MagicMock()
        self.app.root = self.root
        self.app.entry_tags = tk.Text(self.root, height=1)
        self.app.entry_tags.pack()
        self.app.tag_manager.get_known_tags.return_value = ["Testament", "Testlauf"]
        self.app.tag_manager._get_current_tags.return_value = []
        self.ac = TagAutocomplete(self.app)
        self.ac._visible = lambda: True   # Popup gilt als offen (im Test nicht gezeichnet)
        self.ac.listbox = MagicMock()

    def tearDown(self):
        self.root.destroy()

    def _tippe(self, text):
        self.app.entry_tags.insert("1.0", text)
        self.app.entry_tags.mark_set("insert", "end-1c")
        self.ac._matches = ["Testament", "Testlauf"]
        self.ac._index = -1

    def test_return_ohne_pfeil_laesst_getipptes_stehen(self):
        self._tippe("Rechnung, Test")
        self.assertIsNone(self.ac._on_accept(None))   # Return läuft weiter zum Speichern
        self.assertEqual(self.app.entry_tags.get("1.0", "end-1c"), "Rechnung, Test")

    def test_pfeil_runter_waehlt_den_ersten(self):
        self._tippe("Rechnung, Test")
        self.ac._on_down(None)
        self.assertEqual(self.ac._index, 0)
        self.assertEqual(self.ac._on_accept(None), "break")
        self.assertEqual(self.app.entry_tags.get("1.0", "end-1c"), "Rechnung, Testament, ")

    def test_pfeil_hoch_waehlt_den_letzten(self):
        self._tippe("Test")
        self.ac._on_up(None)
        self.assertEqual(self.ac._index, 1)


if __name__ == "__main__":
    unittest.main()
