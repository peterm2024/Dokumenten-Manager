import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

from save_manager import SaveManager, datum_zum_mitspeichern


class TestPerformAutosave(unittest.TestCase):
    """Tests für den stillen Auto-Save (Debounce-Pfad, ohne Grid-Vollneuaufbau)."""

    def setUp(self):
        self.mock_app = MagicMock()
        self.mock_app.current_preview_path = r"C:\KID\Ordner\doc.pdf"
        self.mock_app.master_folder = r"C:\KID"
        self.mock_app.entry_title.get.return_value = "Titel"
        self.mock_app.entry_tags.get.return_value = "TagA, TagB"
        self.mock_app.tree_files.get_children.return_value = []
        self.manager = SaveManager(self.mock_app)
        # Der Fake-Pfad existiert nicht wirklich - den Verschoben-Schutz (06.09.2026)
        # hier neutralisieren, die eigentlichen Tests dazu stehen weiter unten.
        patcher = patch("save_manager.os.path.exists", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("save_manager.PDFHandler.save_metadata", return_value=(True, ""))
    def test_syncs_tag_tree_after_recent_tags_rebuild(self, mock_save):
        """
        Regressionstest: add_recent_tags baut die "Zuletzt benutzt"-Einträge neu auf und
        verwirft deren TAG_ACTIVE-Markierung. Ohne anschließendes sync_tag_tree_selection
        verlor ein gerade zugewiesenes Tag dort nach dem Auto-Save-Debounce (~1s) seine
        blaue Hervorhebung (der manuelle Weg über _finish_save macht den Aufruf schon immer).
        """
        self.manager._perform_autosave()

        self.mock_app.tag_manager.add_recent_tags.assert_called_once_with(["TagA", "TagB"])
        self.mock_app.tag_manager.sync_tag_tree_selection.assert_called_once()

    @patch("save_manager.PDFHandler.save_metadata", return_value=(True, ""))
    def test_clears_dirty_flag_on_success(self, mock_save):
        self.manager._dirty = True
        self.manager._perform_autosave()
        self.assertFalse(self.manager._dirty)

    @patch("save_manager.PDFHandler.get_metadata", return_value={"title": "Alter Titel", "keywords": "AlteTags"})
    @patch("save_manager.PDFHandler.save_metadata", return_value=(False, "Fehler"))
    def test_clears_dirty_flag_on_failure_after_revert(self, mock_save, mock_meta):
        """
        Nach einem fehlgeschlagenen Speichern (z.B. geschütztes PDF, siehe
        KONZEPT_PDF_ARTEN.md) wird die eingegebene Änderung verworfen und auf den
        Datei-Ist-Zustand zurückgesetzt - danach gibt es nichts mehr offen zu speichern,
        _dirty muss also False sein (nicht True wie vor dem Revert-Fix: ein "Speichern
        erneut versuchen" würde bei einer dauerhaft geschützten Datei ohnehin nie klappen).
        """
        self.manager._dirty = True
        self.manager._perform_autosave()
        self.assertFalse(self.manager._dirty)

    @patch("save_manager.PDFHandler.get_metadata", return_value={"title": "Alter Titel", "keywords": "AlteTags"})
    @patch("save_manager.PDFHandler.save_metadata", return_value=(False, "Fehler"))
    def test_reverts_fields_to_disk_on_failure(self, mock_save, mock_meta):
        """Regressionstest: Titel-/Tags-Feld zeigten nach einem fehlgeschlagenen Speichern weiterhin den nie gespeicherten Eingabewert - die Oberfläche log damit über den tatsächlichen Dateiinhalt."""
        self.manager._perform_autosave()

        self.mock_app.entry_title.delete.assert_called_once_with(0, tk.END)
        self.mock_app.entry_title.insert.assert_called_once_with(0, "Alter Titel")
        self.mock_app.entry_tags.delete.assert_called_once_with("1.0", tk.END)
        self.mock_app.entry_tags.insert.assert_called_once_with("1.0", "AlteTags")

    @patch("save_manager.PDFHandler.get_metadata", return_value={"title": "", "keywords": ""})
    @patch("save_manager.PDFHandler.save_metadata", return_value=(False, "Fehler"))
    def test_does_not_touch_tree_row_or_recent_tags_on_failure(self, mock_save, mock_meta):
        """Regressionstest: Die Dokumentenliste-Zeile und die 'Zuletzt benutzt'-Tags dürfen bei einem fehlgeschlagenen Speichern NICHT optimistisch mit dem nie gespeicherten Wert aktualisiert werden."""
        self.manager._perform_autosave()

        self.mock_app.tag_manager.add_recent_tags.assert_not_called()
        self.mock_app.tree_files.item.assert_not_called()

    @patch("save_manager.PDFHandler.get_metadata", return_value={"title": "", "keywords": ""})
    @patch("save_manager.PDFHandler.save_metadata", return_value=(False, "Fehler"))
    def test_syncs_tag_tree_after_revert(self, mock_save, mock_meta):
        """Auch nach dem Revert muss die Baum-Hervorhebung neu synchronisiert werden - sonst bliebe ein nie gespeichertes Tag dort weiterhin blau markiert."""
        self.manager._perform_autosave()
        self.mock_app.tag_manager.sync_tag_tree_selection.assert_called_once()

    @patch("save_manager.PDFHandler.save_metadata")
    def test_does_nothing_without_pdf_path(self, mock_save):
        self.mock_app.current_preview_path = None
        self.manager._perform_autosave()
        mock_save.assert_not_called()

    @patch("save_manager.PDFHandler.save_metadata")
    def test_verschobene_datei_wird_still_uebersprungen(self, mock_save):
        """
        Live-Fund 06.09.2026: Die Datei wurde zwischen Eingabe und Debounce-Ablauf
        verschoben (damals von der Watchdog-Vollautomatik) - kein Schreibversuch,
        kein Fehler-Popup, der Änderungs-Merker wird verworfen.
        """
        with patch("save_manager.os.path.exists", return_value=False):
            self.manager._dirty = True
            self.manager._perform_autosave()
        mock_save.assert_not_called()
        self.assertFalse(self.manager._dirty)

    @patch("save_manager.PDFHandler.save_metadata", return_value=(True, ""))
    def test_autosave_speichert_still(self, mock_save):
        """Auto-Save darf nie ein modales Fehler-Popup in die laufende Eingabe werfen (still=True)."""
        self.manager._perform_autosave()
        self.assertTrue(mock_save.call_args.kwargs.get("still"))

    @patch("save_manager.PDFHandler.save_metadata", return_value=(True, ""))
    def test_autosave_schreibt_vorgeschlagenes_datum_mit(self, mock_save):
        """Peter 28.10.2026: Titel gespeichert, Datum stand nur als Vorschlag im Feld - die Liste zeigte den Download-Tag."""
        self.mock_app.datum_feld = {"pfad": self.mock_app.current_preview_path, "gespeichert": "", "notbehelf": None}
        self.mock_app.date_entry.get.return_value = "2025-01-31"
        self.mock_app.tree_files.get_children.return_value = ["i1"]
        self.mock_app.tree_files.item.return_value = ["28.10.2026", "", "---", "", r"Ordner\doc.pdf"]
        self.manager._perform_autosave()
        self.assertEqual(mock_save.call_args.kwargs.get("datum"), "2025-01-31")
        self.assertEqual(self.mock_app.datum_feld["gespeichert"], "2025-01-31")
        self.mock_app.setze_datum_stil.assert_called_with(vermutet=False)
        zeile = self.mock_app.tree_files.item.call_args_list[-1].kwargs["values"]
        self.assertEqual(zeile[0], "31.01.2025")


class TestDatumBeimVerlassen(unittest.TestCase):
    """Peter 28.10.2026: Mit Auto-Save genügt Anklicken und Weiterklicken, um das vermutete Datum zu speichern."""

    ALT = r"C:\KID\A\konto.pdf"

    def setUp(self):
        self.app = MagicMock()
        self.app.master_folder = r"C:\KID"
        self.app.autosave_var.get.return_value = True
        self.app.datum_feld = {"pfad": self.ALT, "gespeichert": "", "notbehelf": None}
        self.app.date_entry.get.return_value = "2025-01-31"
        self.app.tree_files.get_children.return_value = ["i1"]
        self.app.tree_files.item.return_value = ["31.01.2025", "Konto", "---", "konto.pdf", r"A\konto.pdf"]
        self.manager = SaveManager(self.app)
        for ziel in ("save_manager.os.path.exists",):
            patcher = patch(ziel, return_value=True)
            patcher.start()
            self.addCleanup(patcher.stop)

    @patch("save_manager.PDFHandler.write_custom_metadata", return_value=True)
    def test_wechsel_speichert_vermutetes_datum(self, mock_schreib):
        self.manager.datum_beim_verlassen(r"C:\KID\A\anderes.pdf")
        mock_schreib.assert_called_once_with(self.ALT, {"KID_DokumentenDatum": "2025-01-31"}, still=True)
        self.assertEqual(self.app.datum_feld["gespeichert"], "2025-01-31")
        self.app.aktualisiere_datumszeile.assert_called_once_with("i1", "2025-01-31")

    @patch("save_manager.PDFHandler.write_custom_metadata", return_value=True)
    def test_dasselbe_dokument_wieder_ausgewaehlt_ist_kein_wechsel(self, mock_schreib):
        """Neuaufbau der Liste (Watchdog, Speichern) wählt dasselbe Dokument erneut aus."""
        self.manager.datum_beim_verlassen("C:/KID/A/konto.pdf")
        mock_schreib.assert_not_called()

    @patch("save_manager.PDFHandler.write_custom_metadata", return_value=True)
    def test_ohne_auto_save_nichts(self, mock_schreib):
        self.app.autosave_var.get.return_value = False
        self.manager.datum_beim_verlassen(r"C:\KID\A\anderes.pdf")
        mock_schreib.assert_not_called()

    @patch("save_manager.PDFHandler.write_custom_metadata", return_value=True)
    def test_datei_datum_und_schon_gespeichertes_nie(self, mock_schreib):
        self.app.datum_feld["notbehelf"] = "2025-01-31"
        self.manager.datum_beim_verlassen(r"C:\KID\A\anderes.pdf")
        self.app.datum_feld.update(notbehelf=None, gespeichert="2025-01-31")
        self.manager.datum_beim_verlassen(r"C:\KID\A\anderes.pdf")
        mock_schreib.assert_not_called()


class TestKennungBeimAnklicken(unittest.TestCase):
    """Peter 28.10.2026: Dokument-ID erschien erst nach dem ersten Speichern."""

    def setUp(self):
        self.app = MagicMock()
        self.app.autosave_var.get.return_value = True
        self.manager = SaveManager(self.app)
        patcher = patch("save_manager.os.path.exists", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("save_manager.PDFHandler.ensure_kid_id", return_value="K7M4-Q2XP")
    @patch("save_manager.PDFHandler.get_metadata", return_value={"KID_ID": ""})
    def test_fehlende_id_wird_vergeben(self, _meta, mock_id):
        self.manager.kennung_beim_anklicken("C:/KID/brief.pdf")
        mock_id.assert_called_once_with("C:/KID/brief.pdf")

    @patch("save_manager.PDFHandler.ensure_kid_id")
    @patch("save_manager.PDFHandler.get_metadata", return_value={"KID_ID": "K7M4-Q2XP"})
    def test_vorhandene_id_schreibt_nichts(self, _meta, mock_id):
        self.manager.kennung_beim_anklicken("C:/KID/brief.pdf")
        mock_id.assert_not_called()

    @patch("save_manager.PDFHandler.ensure_kid_id")
    @patch("save_manager.PDFHandler.get_metadata", return_value={"KID_ID": ""})
    def test_ohne_auto_save_oder_kein_pdf_nichts(self, _meta, mock_id):
        self.manager.kennung_beim_anklicken("C:/KID/notiz.txt")
        self.app.autosave_var.get.return_value = False
        self.manager.kennung_beim_anklicken("C:/KID/brief.pdf")
        mock_id.assert_not_called()


class TestDatumZumMitspeichern(unittest.TestCase):
    PFAD = r"C:\KID\doc.pdf"

    def feld(self, gespeichert="", notbehelf=None, pfad=PFAD):
        return {"pfad": pfad, "gespeichert": gespeichert, "notbehelf": notbehelf}

    def test_vorschlag_ohne_gespeichertes_datum(self):
        self.assertEqual(datum_zum_mitspeichern(self.feld(), self.PFAD, "2025-01-31"), "2025-01-31")

    def test_getipptes_abweichendes_datum(self):
        self.assertEqual(datum_zum_mitspeichern(self.feld("2025-01-31"), self.PFAD, "01.02.2025"), "2025-02-01")

    def test_unveraendert_gespeichertes_datum_nicht_nochmal(self):
        self.assertIsNone(datum_zum_mitspeichern(self.feld("2025-01-31"), self.PFAD, "2025-01-31"))

    def test_datei_datum_als_notbehelf_nie(self):
        self.assertIsNone(datum_zum_mitspeichern(self.feld(notbehelf="2026-10-28"), self.PFAD, "2026-10-28"))

    def test_feld_eines_anderen_dokuments_nie(self):
        """Mehrfachauswahl/Dokumentwechsel: das Datumsfeld gehört nur dem angezeigten Dokument."""
        self.assertIsNone(datum_zum_mitspeichern(self.feld(pfad=r"C:\KID\anderes.pdf"), self.PFAD, "2025-01-31"))
        self.assertIsNone(datum_zum_mitspeichern(None, self.PFAD, "2025-01-31"))

    def test_schreibweise_des_pfads_egal(self):
        """Die Vorschau merkt Pfade mit gemischten Schrägstrichen, save_selected baut den Pfad aus Hauptordner + relativem Pfad."""
        self.assertEqual(datum_zum_mitspeichern(self.feld(pfad="C:/KID/doc.pdf"), self.PFAD, "2025-01-31"), "2025-01-31")

    def test_ungueltiges_datum_nie(self):
        self.assertIsNone(datum_zum_mitspeichern(self.feld(), self.PFAD, "31.13.2025"))
        self.assertIsNone(datum_zum_mitspeichern(self.feld(), self.PFAD, ""))


class TestTagsBereinigen(unittest.TestCase):
    def test_komma_am_ende_und_leere_eintraege(self):
        from save_manager import tags_bereinigen
        self.assertEqual(tags_bereinigen("Rechnung, Testament, "), "Rechnung, Testament")
        self.assertEqual(tags_bereinigen(" Strom ,, Gas,"), "Strom, Gas")
        self.assertEqual(tags_bereinigen(""), "")


if __name__ == "__main__":
    unittest.main()


class TestErgaenzeTagsFuerAuswahl(unittest.TestCase):
    """
    Mehrere Dokumente markieren und per Doppelklick EIN Tag vergeben (Nutzerwunsch
    01.09.2026). Anders als save_selected darf dabei NICHT das Tags-Eingabefeld auf
    alle geschrieben werden - jedes Dokument behaelt seine eigenen Tags und den Titel.
    """

    ZEILEN = {
        "i1": ("", "Grundsteuerbescheid", "Grundsteuer, Werner Mustermann", "a.pdf", "a.pdf"),
        "i2": ("", "SEPA", "---", "b.pdf", "b.pdf"),
    }
    META = {
        r"C:\KID\a.pdf": {"title": "Grundsteuerbescheid", "keywords": "Grundsteuer, Werner Mustermann"},
        r"C:\KID\b.pdf": {"title": "SEPA", "keywords": ""},
    }

    def setUp(self):
        self.mock_app = MagicMock()
        self.mock_app.master_folder = r"C:\KID"
        self.mock_app.tree_files.selection.return_value = ("i1", "i2")
        self.mock_app.tree_files.item.side_effect = lambda iid, key=None: self.ZEILEN[iid]
        self.mock_app.tree_files.get_children.return_value = []
        self.mock_app.search_manager.is_search_active.return_value = False
        self.manager = SaveManager(self.mock_app)

    def _patches(self):
        return (patch("save_manager.PDFHandler.get_metadata", side_effect=lambda p: dict(self.META[p])),
                patch("save_manager.PDFHandler.save_metadata", return_value=(True, "")))

    def test_ergaenzt_tag_und_behaelt_eigene_tags_und_titel(self):
        meta, save = self._patches()
        with meta, save as mock_save:
            self.assertEqual(self.manager.ergaenze_tags_fuer_auswahl(["Steuer"]), 2)
        geschrieben = {aufruf.args[0]: aufruf.args[1:] for aufruf in mock_save.call_args_list}
        self.assertEqual(geschrieben[r"C:\KID\a.pdf"],
                         ("Grundsteuerbescheid", "Grundsteuer, Werner Mustermann, Steuer"))
        self.assertEqual(geschrieben[r"C:\KID\b.pdf"], ("SEPA", "Steuer"))

    def test_vorhandenes_tag_wird_nicht_verdoppelt(self):
        meta, save = self._patches()
        with meta, save as mock_save:
            # "Grundsteuer" hat nur a.pdf - b.pdf bekommt es, a.pdf bleibt unberuehrt
            self.assertEqual(self.manager.ergaenze_tags_fuer_auswahl(["grundsteuer"]), 1)
        self.assertEqual([aufruf.args[0] for aufruf in mock_save.call_args_list], [r"C:\KID\b.pdf"])

    def test_entfernen_zieht_das_tag_ab(self):
        meta, save = self._patches()
        with meta, save as mock_save:
            self.assertEqual(self.manager.ergaenze_tags_fuer_auswahl(["Werner Mustermann"], entfernen=True), 1)
        self.assertEqual(mock_save.call_args_list[0].args[1:], ("Grundsteuerbescheid", "Grundsteuer"))

    def test_zuletzt_benutzt_nur_beim_ergaenzen(self):
        meta, save = self._patches()
        with meta, save:
            self.manager.ergaenze_tags_fuer_auswahl(["Steuer"])
        self.mock_app.tag_manager.add_recent_tags.assert_called_once_with(["Steuer"])
        self.mock_app.tag_manager.add_recent_tags.reset_mock()
        meta, save = self._patches()
        with meta, save:
            self.manager.ergaenze_tags_fuer_auswahl(["Steuer"], entfernen=True)
        self.mock_app.tag_manager.add_recent_tags.assert_not_called()

    def test_ohne_auswahl_oder_ohne_tags_passiert_nichts(self):
        meta, save = self._patches()
        with meta, save as mock_save:
            self.assertEqual(self.manager.ergaenze_tags_fuer_auswahl([]), 0)
            self.mock_app.tree_files.selection.return_value = ()
            self.assertEqual(self.manager.ergaenze_tags_fuer_auswahl(["Steuer"]), 0)
        mock_save.assert_not_called()
