import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import app_paths
import papierkorb_herkunft
from file_operations import FileOperations, neue_tags, vereinige_tags


class TestVerschiebeOhneDuplikat(unittest.TestCase):
    """
    Regressionstest für _verschiebe_ohne_duplikat: shutil.move fällt bei einem
    os.rename()-Fehler (z.B. Datei noch von einem anderen Tool geöffnet, wie beim
    PDF-Inspektor-Handle-Leak) intern auf Kopieren+Löschen zurück. Schlägt dabei
    NUR das Löschen der Quelle fehl, blieb bisher eine stille Kopie am Ziel liegen.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.ops = FileOperations(MagicMock())
        self.quelle = os.path.join(self.tmp, "quelle.pdf")
        with open(self.quelle, "wb") as f:
            f.write(b"dummy")
        self.ziel = os.path.join(self.tmp, "ziel.pdf")

    def test_normaler_move_funktioniert_wie_gewohnt(self):
        self.ops._verschiebe_ohne_duplikat(self.quelle, self.ziel)

        self.assertFalse(os.path.exists(self.quelle))
        self.assertTrue(os.path.exists(self.ziel))

    @patch("file_operations.time.sleep")
    def test_partieller_fehlschlag_hinterlaesst_kein_duplikat(self, mock_sleep):
        def move_kopiert_aber_loescht_nicht(src, dst, *args, **kwargs):
            shutil.copy2(src, dst)
            raise OSError("[WinError 32] Der Prozess kann nicht auf die Datei zugreifen")

        with patch("file_operations.shutil.move", side_effect=move_kopiert_aber_loescht_nicht):
            with self.assertRaises(OSError):
                self.ops._verschiebe_ohne_duplikat(self.quelle, self.ziel)

        # Quelle bleibt unverändert liegen (Datei war ja "noch offen"), das
        # überzählige Ziel-Duplikat wird wieder entfernt statt stehen zu bleiben.
        self.assertTrue(os.path.exists(self.quelle))
        self.assertFalse(os.path.exists(self.ziel))

    @patch("file_operations.time.sleep")
    def test_fehlschlag_ohne_vorherige_kopie_raeumt_nichts_unnoetig_auf(self, mock_sleep):
        with patch("file_operations.shutil.move", side_effect=OSError("Fehler vor jeder Kopie")):
            with self.assertRaises(OSError):
                self.ops._verschiebe_ohne_duplikat(self.quelle, self.ziel)

        self.assertTrue(os.path.exists(self.quelle))
        self.assertFalse(os.path.exists(self.ziel))

    @patch("file_operations.time.sleep")
    def test_transiente_sperre_wird_per_wiederholung_ueberwunden(self, mock_sleep):
        """
        Regressionstest (FALLSTRICKE #27, zweiter Live-Fund): kurzzeitige Sperren
        durch fremde Leser (Virenscanner, zweite Programm-Instanz mit eigenem
        Watchdog/Suchindex) geben die Datei nach Sekundenbruchteilen wieder frei -
        ein Wiederholungsversuch muss das abfangen, statt sofort aufzugeben.
        """
        echte_move = shutil.move
        aufrufe = []

        def erst_gesperrt_dann_frei(src, dst, *args, **kwargs):
            aufrufe.append(1)
            if len(aufrufe) < 3:
                raise OSError("[WinError 32] Der Prozess kann nicht auf die Datei zugreifen")
            echte_move(src, dst)

        with patch("file_operations.shutil.move", side_effect=erst_gesperrt_dann_frei):
            self.ops._verschiebe_ohne_duplikat(self.quelle, self.ziel)

        self.assertEqual(len(aufrufe), 3)
        self.assertEqual(mock_sleep.call_count, 2)  # zwischen den Versuchen gewartet
        self.assertFalse(os.path.exists(self.quelle))
        self.assertTrue(os.path.exists(self.ziel))

    @patch("file_operations.time.sleep")
    def test_dauerhafte_sperre_gibt_nach_allen_versuchen_auf(self, mock_sleep):
        with patch("file_operations.shutil.move",
                   side_effect=OSError("[WinError 32]")) as mock_move:
            with self.assertRaises(OSError):
                self.ops._verschiebe_ohne_duplikat(self.quelle, self.ziel)

        self.assertEqual(mock_move.call_count, self.ops.MOVE_VERSUCHE)


class TestPapierkorb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.master = os.path.join(self.tmp, "Sammlung")
        self.app = MagicMock(master_folder=self.master)
        self.ops = FileOperations(self.app)
        self.a = self._datei("Ordner A", "gleich.pdf", b"aus A")
        self.b = self._datei("Ordner B", "gleich.pdf", b"aus B")
        self.trash = app_paths.trash_dir(self.master)

    def _datei(self, ordner, name, inhalt):
        pfad = os.path.join(self.master, ordner, name)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, "wb") as f:
            f.write(inhalt)
        return pfad

    def _inhalte(self):
        inhalte = []
        for n in os.listdir(self.trash):
            with open(os.path.join(self.trash, n), "rb") as f:
                inhalte.append(f.read())
        return sorted(inhalte)

    def test_gleichnamige_ueberschreiben_sich_nicht(self):
        self.assertEqual(self.ops.in_papierkorb([self.a, self.b]), (2, 0))
        self.assertEqual(self._inhalte(), [b"aus A", b"aus B"])
        self.assertFalse(self.app.is_moving)
        self.app.folder_manager.refresh_folder_tree.assert_called_once()
        # Herkunft bleibt je Datei erhalten: „Wiederherstellen“ findet beide Ordner
        herkunft = {papierkorb_herkunft.zielordner(self.master, os.path.join(self.trash, n))
                    for n in os.listdir(self.trash)}
        self.assertEqual(herkunft, {os.path.dirname(self.a), os.path.dirname(self.b)})

    def test_wiederherstellen_gibt_den_alten_namen_zurueck(self):
        # Release-Check v0.9.24 (T1.15): Die zweite Datei hieß danach weiter „… (2).pdf“
        self.ops.in_papierkorb([self.a, self.b])
        zeilen = {n: ("", "", "", "", os.path.relpath(os.path.join(self.trash, n), self.master)) for n in os.listdir(self.trash)}
        self.assertEqual(len(zeilen), 2)
        self.assertEqual(len({os.path.basename(z[4]) for z in zeilen.values()}), 2)
        self.app.tree_files.selection.return_value = tuple(zeilen)
        self.app.tree_files.item.side_effect = lambda iid, was: zeilen[iid]
        self.app.tree_folders.selection.return_value = ()
        with patch("file_operations.messagebox.showinfo"), patch.object(self.ops, "_merke_nachbar_als_naechste_auswahl"):
            self.ops.restore_file()
        for pfad, inhalt in ((self.a, b"aus A"), (self.b, b"aus B")):
            with open(pfad, "rb") as f:
                self.assertEqual(f.read(), inhalt)
        self.assertEqual(os.listdir(self.trash), [])
        self.assertEqual(papierkorb_herkunft.lade(self.master), {})

    def test_wiederherstellen_mit_belegtem_namen_ueberschreibt_nicht(self):
        self.ops.in_papierkorb([self.a])
        with open(self.a, "wb") as f:
            f.write(b"neu")
        name = os.listdir(self.trash)[0]
        self.app.tree_files.selection.return_value = ("zeile",)
        self.app.tree_files.item.side_effect = lambda iid, was: ("", "", "", "", os.path.relpath(os.path.join(self.trash, name), self.master))
        self.app.tree_folders.selection.return_value = ()
        with patch("file_operations.messagebox.showinfo"), patch.object(self.ops, "_merke_nachbar_als_naechste_auswahl"):
            self.ops.restore_file()
        with open(self.a, "rb") as f:
            self.assertEqual(f.read(), b"neu")
        stamm, endung = os.path.splitext(self.a)
        with open(f"{stamm}_wiederhergestellt_1{endung}", "rb") as f:
            self.assertEqual(f.read(), b"aus A")

    def test_fehler_wird_gezaehlt(self):
        self.assertEqual(self.ops.in_papierkorb([os.path.join(self.master, "fehlt.pdf"), self.a]), (1, 1))

    def test_loeschen_von_hand_ueberschreibt_den_papierkorb_nicht(self):
        # Wer nacheinander zwei gleichnamige Dateien löschte, verlor die erste still
        for pfad in (self.a, self.b):
            self.app.tree_files.selection.return_value = ("zeile",)
            self.app.tree_files.item.return_value = ("", "", "", "", os.path.relpath(pfad, self.master))
            self.app.tree_folders.selection.return_value = ()
            with patch("file_operations.bestaetigung.frage", return_value=True):
                self.ops.delete_file()
        self.assertEqual(self._inhalte(), [b"aus A", b"aus B"])


class TestNachbarZeile(unittest.TestCase):
    """Nach Verschieben/Löschen soll die nachrutschende Zeile markiert werden (Nutzerwunsch 30.08.2026)."""

    def setUp(self):
        self.app = MagicMock()
        self.app.master_folder = "C:/KID"
        self.app.tree_files.get_children.return_value = ["a", "b", "c", "d"]
        self.app.tree_files.item.side_effect = lambda iid, what: ("", "", "", "", f"{iid}.pdf", "", "")
        self.ops = FileOperations(self.app)

    def test_naechste_zeile_darunter_rutscht_nach(self):
        self.assertEqual(self.ops._nachbar_zeile(["b"]), "c")

    def test_bei_letzter_zeile_rutscht_die_darueber_nach(self):
        self.assertEqual(self.ops._nachbar_zeile(["d"]), "c")

    def test_mehrfachauswahl_ueberspringt_alle_entfernten(self):
        self.assertEqual(self.ops._nachbar_zeile(["b", "c"]), "d")
        self.assertEqual(self.ops._nachbar_zeile(["c", "d"]), "b")

    def test_ohne_verbleibende_zeile_kein_nachbar(self):
        self.assertIsNone(self.ops._nachbar_zeile(["a", "b", "c", "d"]))

    def test_merken_setzt_current_preview_path_auf_den_nachbarn(self):
        self.ops._merke_nachbar_als_naechste_auswahl(["b"])
        self.assertEqual(self.app.current_preview_path, os.path.join("C:/KID", "c.pdf"))


if __name__ == "__main__":
    unittest.main()


class TestDragNurVonZeile(unittest.TestCase):
    """
    FALLSTRICKE #61 (Nutzerfund 11.09.2026): Spaltenbreite per Kopfzeilen-Trennlinie ziehen
    und außerhalb loslassen löste einen Drop aus - mit dem zuvor markierten Dokument als
    Quelle (Tag-Transfer/Verschieben). Nur ein Druck auf eine ZEILE darf einen Drag starten.
    """

    def setUp(self):
        self.app = MagicMock()
        self.ops = FileOperations(self.app)
        self.ops.on_file_drop = MagicMock()
        self.app.root.winfo_pointerxy.return_value = (500, 300)
        self.app.root.winfo_containing.return_value = self.app.tree_files  # Maus landet über der Liste
        self.app.tree_files.winfo_rooty.return_value = 100

    def _druck(self, region, item, x=10, y=5):
        self.app.tree_files.identify_row.return_value = item
        self.app.tree_files.identify_region.return_value = region
        self.ops.on_drag_start(MagicMock(x=x, y=y, x_root=100, y_root=100, state=0))

    def _loslassen(self, dx=80, dy=40):
        self.ops.on_drag_stop(MagicMock(x_root=100 + dx, y_root=100 + dy))

    def test_trennlinie_ziehen_ist_kein_drop(self):
        self._druck("separator", "")
        self.ops.on_drag_motion(MagicMock())
        self._loslassen()
        self.ops.on_file_drop.assert_not_called()
        self.app.tree_files.selection_remove.assert_not_called()  # Auswahl bleibt (Sortier-/Kopfklick)

    def test_kopfzeile_ziehen_ist_kein_drop(self):
        self._druck("heading", "")
        self._loslassen()
        self.ops.on_file_drop.assert_not_called()

    def test_drag_von_zeile_loest_drop_aus(self):
        with patch("file_operations.tk.Toplevel"):
            self._druck("cell", "I001")
        self.assertTrue(self.ops._drag_aktiv)
        self._loslassen()
        self.ops.on_file_drop.assert_called_once()
        self.assertFalse(self.ops._drag_aktiv)  # nach dem Drop wieder scharf für den nächsten Kopfzeilen-Zug

    def test_zitterklick_auf_zeile_bleibt_klick(self):
        with patch("file_operations.tk.Toplevel"):
            self._druck("cell", "I001")
        self._loslassen(dx=1, dy=1)
        self.ops.on_file_drop.assert_not_called()

    def test_tags_uebertragen_nur_mit_alt(self):
        """Seit 15.09.2026: Der Drop auf ein Dokument überträgt Tags nur mit gedrückter Alt-Taste
        (Fehlgriff-Schutz) - der Alt-Zustand beim Loslassen wird als tags_erlaubt weitergereicht."""
        import file_operations as fo
        with patch("file_operations.tk.Toplevel"):
            self._druck("cell", "I001")
        self.ops.on_drag_stop(MagicMock(x_root=180, y_root=140, state=0))
        self.assertFalse(self.ops.on_file_drop.call_args.kwargs["tags_erlaubt"])
        with patch("file_operations.tk.Toplevel"):
            self._druck("cell", "I001")
        self.ops.on_drag_stop(MagicMock(x_root=180, y_root=140, state=fo.ALT_MASKE))
        self.assertTrue(self.ops.on_file_drop.call_args.kwargs["tags_erlaubt"])

    def test_drop_auf_dokument_ohne_alt_aendert_nichts_und_gibt_hinweis(self):
        """Echter on_file_drop: ohne tags_erlaubt wird kein PDF angefasst, nur ein Hinweis gezeigt."""
        import file_operations as fo
        ops = FileOperations(self.app)
        ops._hinweis_kurz = MagicMock()
        self.app.tree_files.selection.return_value = ("I001",)
        self.app.tree_files.item.side_effect = lambda iid, was=None: ("", "", "", "a.pdf", "a.pdf") if was == "values" else ()
        self.app.tree_files.identify_row.return_value = "I002"
        self.app.master_folder = "C:/x"
        with patch("file_operations.PDFHandler.get_metadata", return_value={"keywords": "Rechnung"}),              patch("file_operations.PDFHandler.write_custom_metadata") as schreiben:
            ops.on_file_drop(MagicMock(y=10, spec=["y"]), is_folder_drop=False, tags_erlaubt=False)
        schreiben.assert_not_called()
        ops._hinweis_kurz.assert_called_once_with(fo.TAG_TRANSFER_HINWEIS)

    def _alt_drop(self, quelle_tags, ziel_tags):
        """Alt-Drop von a.pdf auf b.pdf, gibt (Hinweis-Mock, Meldungsfenster-Mock, Schreib-Mock) zurück."""
        ops = FileOperations(self.app)
        ops._hinweis_kurz = MagicMock()
        self.app.tree_files.selection.return_value = ("I001",)
        werte = {"I001": ("", "", "", "a.pdf", "a.pdf"), "I002": ("", "", "", "b.pdf", "b.pdf")}
        self.app.tree_files.item.side_effect = lambda iid, was=None: werte[iid] if was == "values" else ()
        self.app.tree_files.identify_row.return_value = "I002"
        self.app.master_folder = "C:/x"
        meta = lambda pfad: {"keywords": quelle_tags if pfad.endswith("a.pdf") else ziel_tags}
        with patch("file_operations.PDFHandler.get_metadata", side_effect=meta), \
                patch("file_operations.PDFHandler.write_custom_metadata") as schreiben, \
                patch("tkinter.messagebox.showinfo") as meldung:
            ops.on_file_drop(MagicMock(y=10, spec=["y"]), is_folder_drop=False, tags_erlaubt=True)
        return ops._hinweis_kurz, meldung, schreiben

    def test_alt_drop_ohne_tags_der_quelle_nur_hinweis(self):
        """Peter 07.11.2026: kurzer Hinweis wie bei der gelungenen Übertragung statt blockierendem Meldungsfenster -
        das Fenster blieb im Release-Check unbemerkt offen und schluckte die nächsten Tasten."""
        hinweis, meldung, schreiben = self._alt_drop("", "Rechnung")
        meldung.assert_not_called()
        schreiben.assert_not_called()
        self.assertIn("keine Tags", hinweis.call_args.args[0])

    def test_alt_drop_ziel_hat_schon_alle_tags_nur_hinweis(self):
        hinweis, meldung, schreiben = self._alt_drop("Rechnung", "Rechnung, Strom")
        meldung.assert_not_called()
        schreiben.assert_not_called()
        self.assertIn("schon", hinweis.call_args.args[0])
        self.assertIn("Rechnung", hinweis.call_args.args[0])

    def test_strg_klick_startet_keinen_drag(self):
        self.app.tree_files.identify_row.return_value = "I001"
        self.ops.on_drag_start(MagicMock(x=10, y=5, x_root=100, y_root=100, state=0x0004))
        self._loslassen()
        self.ops.on_file_drop.assert_not_called()


class TestVereinigeTags(unittest.TestCase):
    def test_reihenfolge_bleibt(self):
        self.assertEqual(vereinige_tags("Rechnung, Handwerker, Musterheim", "Musterheim, Kaminkehrer, Nebenkosten"),
                         ["Rechnung", "Handwerker", "Musterheim", "Kaminkehrer", "Nebenkosten"])

    def test_gross_klein_und_leeres(self):
        self.assertEqual(vereinige_tags("---", "Rechnung,, rechnung , Strom"), ["Rechnung", "Strom"])
        self.assertEqual(vereinige_tags("", None), [])

    def test_neue_tags_nur_was_dem_ziel_fehlt(self):
        """Peter 28.10.2026: Übertragung „ging nicht“ - das Ziel hatte schon alle Tags."""
        ziel = "Mieter, Nebenkosten, Rechnung, Musterheim"
        self.assertEqual(neue_tags(ziel, "Nebenkosten, musterheim"), [])
        self.assertEqual(neue_tags(ziel, "Nebenkosten, Heizung, Musterheim, Iqua"), ["Heizung", "Iqua"])
        self.assertEqual(neue_tags("", "Strom,, strom"), ["Strom"])


class TestUmbenennenBehaeltMarkierung(unittest.TestCase):
    def test_umbenannte_datei_wird_wieder_gewaehlt(self):
        with tempfile.TemporaryDirectory() as d:
            alt = os.path.join(d, "a.pdf")
            open(alt, "wb").close()
            app = MagicMock()
            app.master_folder = d
            app.tree_files.selection.return_value = ("I001",)
            app.tree_files.item.return_value = ("", "", "", "a.pdf", "a.pdf")
            gewaehlt = []
            app.folder_manager.on_folder_select.side_effect = lambda e: gewaehlt.append(app.current_preview_path)
            ops = FileOperations(app)
            with patch("file_operations.UIUtils.ask_string", return_value="b"):
                ops.rename_file()
            self.assertEqual(gewaehlt, [os.path.join(d, "b.pdf")])
            self.assertTrue(os.path.exists(os.path.join(d, "b.pdf")))


class TestVerschiebenAusDerSuche(unittest.TestCase):
    """Dokument aus der Trefferliste auf einen Ordner ziehen: Suche bleibt (Peter 25.10.2026)."""

    def _verschiebe(self, suche_aktiv):
        with tempfile.TemporaryDirectory() as d:
            quelle, ziel = os.path.join(d, "A"), os.path.join(d, "B")
            os.makedirs(quelle)
            os.makedirs(ziel)
            open(os.path.join(quelle, "a.pdf"), "wb").close()
            app = MagicMock()
            app.master_folder = d
            app.search_manager.is_search_active.return_value = suche_aktiv
            zeilen = {"I001": ["", "", "", "a.pdf", os.path.join("A", "a.pdf")]}
            gesetzt = {}

            def item(iid, was=None, **kw):
                if "values" in kw:
                    gesetzt[iid] = list(kw["values"])
                    return None
                return tuple(zeilen[iid]) if was == "values" else ()
            app.tree_files.selection.return_value = ("I001",)
            app.tree_files.item.side_effect = item
            app.tree_files.get_children.return_value = ("I001",)
            app.tree_folders.identify_row.return_value = "F2"
            app.tree_folders.selection.return_value = ("F1",)
            app.tree_folders.item.side_effect = lambda iid, was=None: (ziel if iid == "F2" else quelle,)
            ops = FileOperations(app)
            with patch("file_operations.PDFHandler.get_metadata", return_value={}):
                ops.on_file_drop(MagicMock(y=10, spec=["y"]), is_folder_drop=True)
            self.assertTrue(os.path.exists(os.path.join(ziel, "a.pdf")))
            return app, gesetzt

    def test_suche_bleibt_und_dokument_bleibt_markiert(self):
        app, gesetzt = self._verschiebe(suche_aktiv=True)
        app.search_manager.apply_filters.assert_called_once()
        app.folder_manager.on_folder_select.assert_not_called()
        app.folder_manager._select_and_open_path.assert_called_once()
        self.assertEqual(app.folder_manager._select_and_open_path.call_args.kwargs, {"laden": False})
        self.assertEqual(gesetzt["I001"][4], os.path.join("B", "a.pdf"))

    def test_ohne_suche_wie_bisher_ordner_neu_laden(self):
        app, _ = self._verschiebe(suche_aktiv=False)
        app.search_manager.apply_filters.assert_not_called()
        self.assertEqual(app.folder_manager._select_and_open_path.call_args.kwargs, {})

