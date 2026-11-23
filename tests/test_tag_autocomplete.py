"""Tests für tag_autocomplete.py - ohne echte Fenster."""
import types
import unittest
from unittest.mock import MagicMock, patch

from tag_autocomplete import TagAutocomplete


class TestPopupParent(unittest.TestCase):
    """B4a (21.11.2026): im modalen Tag-Dialog (grab_set) muss die Vorschlagsliste am Dialog hängen,
    sonst nimmt sie keine Mausklicks an - Standard bleibt das Hauptfenster."""

    def _zeige(self, popup_parent):
        app = types.SimpleNamespace(root="HAUPTFENSTER")
        text = MagicMock()
        text.bbox.return_value = (0, 0, 5, 10)
        ac = TagAutocomplete(app, text=text, popup_parent=popup_parent)
        ac._matches = ["Strom"]
        with patch("tag_autocomplete.tk.Toplevel") as toplevel, patch("tag_autocomplete.tk.Listbox") as liste:
            liste.return_value.winfo_reqwidth.return_value = 100
            liste.return_value.winfo_reqheight.return_value = 50
            ac._show()
        return toplevel.call_args[0][0]

    def test_standard_hauptfenster(self):
        self.assertEqual(self._zeige(None), "HAUPTFENSTER")

    def test_im_dialog_am_dialog(self):
        self.assertEqual(self._zeige("DIALOG"), "DIALOG")


class TestEsc(unittest.TestCase):
    """Peter 22.11.2026 (Tags bearbeiten): Esc schließt zuerst die Liste; erst ohne Liste läuft es zum Dialog weiter
    (dort = Abbrechen)."""

    def _ac(self, sichtbar):
        ac = TagAutocomplete(types.SimpleNamespace(root=None), text=MagicMock())
        ac.popup = MagicMock()
        ac.popup.winfo_exists.return_value = True
        ac.popup.winfo_viewable.return_value = sichtbar
        return ac

    def test_offene_liste_schliesst_und_stoppt(self):
        ac = self._ac(True)
        self.assertEqual(ac._on_escape(None), "break")
        ac.popup.withdraw.assert_called_once()

    def test_ohne_liste_geht_esc_weiter(self):
        self.assertIsNone(self._ac(False)._on_escape(None))

    def test_beide_bearbeiten_dialoge_brechen_mit_esc_ab(self):
        import inspect
        from tools.ai_title_suggest import TagSuggestionDialog
        from tools.title_cleanup import CandidatePickerDialog
        for klasse in (TagSuggestionDialog, CandidatePickerDialog):
            self.assertIn('self.bind("<Escape>", lambda e: self.destroy())', inspect.getsource(klasse.__init__),
                          klasse.__name__)


if __name__ == "__main__":
    unittest.main()
