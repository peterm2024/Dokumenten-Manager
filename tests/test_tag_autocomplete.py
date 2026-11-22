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


if __name__ == "__main__":
    unittest.main()
