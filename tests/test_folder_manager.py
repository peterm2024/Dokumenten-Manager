import os
import unittest
from unittest.mock import MagicMock, patch
from folder_manager import FolderManager

class _FakeTreeview:
    """Minimaler Treeview-Ersatz (insert/delete/get_children/item) für Tests ohne Tk-Fenster."""

    def __init__(self):
        self.nodes = {}   # iid -> dict(parent, text, values, open, children)
        self.roots = []
        self._n = 0

    def insert(self, parent, index, text="", values=(), open=False, tags=()):
        self._n += 1
        iid = f"I{self._n}"
        self.nodes[iid] = {"parent": parent, "text": text, "values": tuple(values), "open": open, "children": []}
        (self.roots if parent == "" else self.nodes[parent]["children"]).append(iid)
        return iid

    def delete(self, iid):
        node = self.nodes[iid]
        for child in list(node["children"]):  # erst die Kinder, solange der Elternknoten noch existiert
            self.delete(child)
        self.nodes.pop(iid)
        (self.roots if node["parent"] == "" else self.nodes[node["parent"]]["children"]).remove(iid)

    def get_children(self, parent=""):
        return tuple(self.roots if parent == "" else self.nodes[parent]["children"])

    def item(self, iid, option=None, **kw):
        if kw:
            self.nodes[iid].update(kw)
            return None
        return self.nodes[iid][option]

    def selection(self):
        return getattr(self, "_selection", ())

    def selection_set(self, iid):
        self._selection = (iid,)

    def see(self, iid):
        pass


class TestRefreshBehaeltAufklappZustand(unittest.TestCase):
    """
    Regressionstest FALLSTRICKE #34: Der Watchdog löst refresh_folder_tree() u.a. nach jedem
    Dateiklick aus - dabei klappte bisher der komplette Ordnerbaum zu.
    """

    def setUp(self):
        import os
        import shutil
        import tempfile
        self.master = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.master, ignore_errors=True)
        for pfad in (os.path.join("A", "Gentilia"), os.path.join("A", "HKV"), "B"):
            os.makedirs(os.path.join(self.master, pfad))
        self.app = MagicMock()
        self.app.master_folder = self.master
        self.app.show_trash_var.get.return_value = False
        self.app.tree_folders = _FakeTreeview()
        self.manager = FolderManager(self.app)
        self.manager.refresh_folder_tree()

    def _knoten(self, name):
        return next(iid for iid, n in self.app.tree_folders.nodes.items() if n["text"] == name)

    def test_aufgeklappte_ordner_bleiben_nach_neuaufbau_aufgeklappt(self):
        tree = self.app.tree_folders
        tree.item(self._knoten("A"), open=True)
        tree.item(self._knoten("Gentilia"), open=True)
        self.assertFalse(tree.item(self._knoten("B"), "open"))

        self.manager.refresh_folder_tree()  # z.B. vom Watchdog ausgelöst

        self.assertTrue(tree.item(self._knoten("A"), "open"))
        self.assertTrue(tree.item(self._knoten("Gentilia"), "open"))
        self.assertFalse(tree.item(self._knoten("B"), "open"))
        self.assertTrue(tree.item(self._knoten(os.path.basename(self.master)), "open"))  # Wurzel wie immer offen

    def test_zugeklappter_baum_bleibt_zugeklappt(self):
        tree = self.app.tree_folders
        self.manager.refresh_folder_tree()
        self.assertFalse(tree.item(self._knoten("A"), "open"))


class TestSelectAndOpenPath(unittest.TestCase):
    """
    Regressionstest FALLSTRICKE #52: master_folder steht in settings.json mit
    Vorwärts-Schrägstrichen ('C:/…', so liefern es Tk-Dateidialoge und testzustand.py),
    os.path-Funktionen erzeugen Backslashes — der rohe startswith-Vergleich in
    _select_and_open_path schlug dann still fehl (kein Ordnerwechsel, z.B. beim
    Hintergrund-Sync der Ablage-Vorschau).
    """

    def setUp(self):
        import shutil
        import tempfile
        self.master = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.master, ignore_errors=True)
        os.makedirs(os.path.join(self.master, "A", "Gentilia"))
        self.app = MagicMock()
        # Der Knackpunkt: Hauptordner mit Vorwärts-Schrägstrichen wie aus settings.json
        self.app.master_folder = self.master.replace("\\", "/")
        self.app.show_trash_var.get.return_value = False
        self.app.tree_folders = _FakeTreeview()
        self.manager = FolderManager(self.app)
        self.manager.on_folder_select = MagicMock()
        self.manager.refresh_folder_tree()

    def test_backslash_ziel_findet_vorwaertsschraegstrich_baum(self):
        ziel = os.path.abspath(os.path.join(self.master, "A", "Gentilia"))  # Backslashes
        self.assertTrue(self.manager._select_and_open_path(ziel))
        gewaehlt = self.app.tree_folders.selection()
        self.assertEqual(len(gewaehlt), 1)
        self.assertEqual(self.app.tree_folders.item(gewaehlt[0], "text"), "Gentilia")
        self.manager.on_folder_select.assert_called_once()

    def test_aehnlicher_name_ist_kein_vorfahre(self):
        # 'KID-Test-Daten' beginnt mit 'KID-Test' - ohne Trennzeichen-Prüfung würde die
        # Suche fälschlich in den falschen Ast absteigen bzw. Erfolg melden.
        fremd = self.master + "-Daten"
        self.assertFalse(self.manager._select_and_open_path(fremd))


class TestZeigeDokument(unittest.TestCase):
    """zeige_dokument (gemeinsamer Helfer für Werkzeug-Fenster): Ordner wechseln, Zeile wählen."""

    def setUp(self):
        import shutil
        import tempfile
        self.master = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.master, ignore_errors=True)
        os.makedirs(os.path.join(self.master, "A", "Gentilia"))
        self.pfad = os.path.join(self.master, "A", "Gentilia", "brief.pdf")
        open(self.pfad, "wb").close()
        self.app = MagicMock()
        self.app.master_folder = self.master.replace("\\", "/")
        self.app.show_trash_var.get.return_value = False
        self.app.tree_folders = _FakeTreeview()
        self.app.tree_files = _FakeTreeview()
        self.app.root.after_idle.side_effect = lambda fn, *a: fn(*a)  # verzögerte Zeilenauswahl sofort ausführen
        self.manager = FolderManager(self.app)
        self.manager.refresh_folder_tree()
        # on_folder_select füllt im echten Programm die Dokumentenliste - hier von Hand
        rel = os.path.join("A", "Gentilia", "brief.pdf")
        self.manager.on_folder_select = MagicMock(
            side_effect=lambda e: self.app.tree_files.insert("", "end", values=("2026-01-01", "Brief", "", "", rel)))

    def test_wechselt_ordner_und_waehlt_zeile(self):
        self.assertTrue(self.manager.zeige_dokument(self.pfad))
        self.manager.on_folder_select.assert_called_once()
        self.app.root.after_idle.assert_called_once()  # Zeile erst NACH dem zweiten Listenaufbau (FALLSTRICKE #73)
        gewaehlt = self.app.tree_files.selection()
        self.assertEqual(len(gewaehlt), 1)
        self.assertEqual(self.app.tree_files.item(gewaehlt[0], "values")[4], os.path.join("A", "Gentilia", "brief.pdf"))

    def test_bestehende_einzelauswahl_wird_nicht_neu_gesetzt(self):
        self.manager.zeige_dokument(self.pfad)
        iid = self.app.tree_files.selection()[0]
        self.app.tree_files.selection_set = MagicMock()
        self.assertTrue(self.manager.zeige_dokument(self.pfad))
        self.app.tree_files.selection_set.assert_not_called()  # sonst FALLSTRICKE #8: doppeltes Rendern
        self.assertEqual(self.manager.on_folder_select.call_count, 1)  # Ordner stimmt schon, kein zweiter Wechsel
        self.assertEqual(self.app.tree_files.selection(), (iid,))

    def test_fehlende_datei_liefert_false(self):
        self.assertFalse(self.manager.zeige_dokument(os.path.join(self.master, "gibts_nicht.pdf")))
        self.assertFalse(self.manager.zeige_dokument(""))


class TestFolderManager(unittest.TestCase):
    def setUp(self):
        self.mock_app = MagicMock()
        self.mock_app.master_folder = "C:/TestMasterFolder"
        
        self.mock_app.config = MagicMock()
        self.mock_app.config.get.return_value = "C:/TestMasterFolder"
        
        self.manager = FolderManager(self.mock_app)

    # --- FIX 1: Wir blockieren die Messagebox, damit fehlende GUIs nicht crashen ---
    @patch('folder_manager.messagebox')
    @patch('os.listdir')
    @patch('os.path.isdir')
    @patch('os.path.isfile')
    @patch('os.path.exists')
    @patch('os.makedirs')
    @patch('builtins.open', new_callable=unittest.mock.mock_open, read_data='{"01_Posteingang": {}, "02_Ablage": {"Steuern": {}}}')
    @patch('json.load')
    def test_create_default_folders(self, mock_json_load, mock_open, mock_makedirs, mock_exists, mock_isfile, mock_isdir, mock_listdir, mock_msgbox):
        """Testet, ob die JSON-Vorlage korrekt in echte Ordner übersetzt wird."""
        
        mock_isdir.return_value = True
        mock_isfile.return_value = True
        mock_listdir.return_value = []  
        
        def mock_exists_side_effect(path):
            path_str = str(path).replace('\\', '/')
            if "Posteingang" in path_str or "Ablage" in path_str or "Steuern" in path_str:
                return False
            return True
            
        mock_exists.side_effect = mock_exists_side_effect
        
        mock_json_load.return_value = {
            "01_Posteingang": {},
            "02_Ablage": {"Steuern": {}}
        }
        
        # --- FIX 2: Wir verhindern, dass der Test versucht, die GUI zu aktualisieren! ---
        self.manager.refresh_folder_tree = MagicMock()
        
        self.manager.create_default_folders()
        
        # Der Test prüft jetzt erfolgreich und isoliert nur den Erstell-Prozess
        self.assertEqual(mock_makedirs.call_count, 3)

    @patch('os.scandir')
    def test_populate_tree_ignores_hidden(self, mock_scandir):
        """Testet, ob versteckte Dateien (.git) und Nicht-Ordner (Dateien) sauber ignoriert werden."""
        
        def create_direntry(name, is_dir_val):
            entry = MagicMock()
            entry.name = name
            entry.is_dir.return_value = is_dir_val
            entry.path = f"C:/TestMasterFolder/{name}"
            return entry

        def mock_scandir_side_effect(path):
            if path == "C:/TestMasterFolder":
                return [
                    create_direntry("Rechnungen", True),
                    create_direntry(".git", True),
                    create_direntry("-Papierkorb", True),
                    create_direntry("Briefe", True),
                    create_direntry("rechnung.pdf", False)
                ]
            return []
            
        mock_scandir.side_effect = mock_scandir_side_effect
        
        self.mock_app.tree_folders.insert = MagicMock()
        
        self.manager._populate_tree("", "C:/TestMasterFolder")

        self.assertEqual(self.mock_app.tree_folders.insert.call_count, 3)

    def test_toggle_show_trash_persistiert_config_und_baut_baum_neu(self):
        """
        Regressionstest: 'Papierkorb einblenden' wurde bisher NICHT in der Config
        gespeichert (anders als Auto-Save) - die Wahl ging bei jedem Neustart
        verloren, der Nutzer musste die Checkbox jedes Mal neu setzen, um die
        Dokumentenanzahl im Papierkorb überhaupt zu sehen.
        """
        self.mock_app.show_trash_var.get.return_value = True
        self.manager.refresh_folder_tree = MagicMock()

        self.manager.toggle_show_trash()

        self.mock_app.config.set.assert_called_once_with("show_trash", True)
        self.manager.refresh_folder_tree.assert_called_once()


class TestStandardOrdnerstruktur(unittest.TestCase):
    """Ausgelieferte folder_default.json (30.08.2026) passt zur Vollautomatik."""

    def test_vorlage_enthaelt_posteingang_unsicher_und_alle_buchstaben(self):
        import json
        import app_paths
        import auto_pilot
        with open(app_paths.bundled_default_path("folder_default.json"), encoding="utf-8") as f:
            struktur = json.load(f)
        self.assertIn(auto_pilot.POSTEINGANG_ORDNER, struktur)
        self.assertIn(auto_pilot.UNSICHER_ORDNER, struktur)
        abgedeckt = set()
        for name in struktur:
            abgedeckt |= auto_pilot.buchstaben_der_gruppe(name)
        self.assertEqual(abgedeckt, set("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))
        self.assertTrue(any(auto_pilot._ZIFFERNGRUPPE.match(name) for name in struktur))
        # Jeder Buchstabe genau einmal (keine Überschneidung zwischen den Gruppen)
        summe = sum(len(auto_pilot.buchstaben_der_gruppe(name)) for name in struktur)
        self.assertEqual(summe, 26)
        # Beispielordner liegen in der Gruppe ihres Anfangsbuchstabens
        for gruppe, kinder in struktur.items():
            for kind in kinder:
                self.assertIn(kind[0].upper(), auto_pilot.buchstaben_der_gruppe(gruppe), f"{kind} in {gruppe}")
        # Ziffern-Präfix sortiert vor den Gruppen-Ordnern
        self.assertLess(auto_pilot.POSTEINGANG_ORDNER, "[0-9]")

    def test_generator_legt_keinen_zweiten_posteingang_an(self):
        import json
        import shutil
        import tempfile
        from unittest.mock import patch
        master = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, master, ignore_errors=True)
        os.makedirs(os.path.join(master, "00_Posteingang"))
        arbeitsverzeichnis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, arbeitsverzeichnis, ignore_errors=True)
        with open(os.path.join(arbeitsverzeichnis, "folder_default.json"), "w", encoding="utf-8") as f:
            json.dump({"0_Posteingang": {}, "[A-F]": {}}, f)
        app = MagicMock()
        app.master_folder = master
        manager = FolderManager(app)
        alt = os.getcwd()
        os.chdir(arbeitsverzeichnis)
        self.addCleanup(os.chdir, alt)
        with patch("folder_manager.messagebox"), \
             patch("bestaetigung.messagebox") as mb:   # Rückfrage läuft seit 07.09.2026 über bestaetigung.frage
            mb.askyesno.return_value = True
            manager.create_default_folders()
        self.assertTrue(os.path.isdir(os.path.join(master, "[A-F]")))
        self.assertFalse(os.path.isdir(os.path.join(master, "0_Posteingang")))


class TestSicherungshinweis(unittest.TestCase):
    """Beta-Vorbereitung 13.09.2026: erstes Öffnen einer Sammlung mit PDFs nennt den Schreibweg in die Dateien."""

    def setUp(self):
        import tempfile, shutil
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_enthaelt_pdfs_findet_pdf_in_unterordner(self):
        import folder_manager
        os.makedirs(os.path.join(self.tmp, "a", "b"))
        self.assertFalse(folder_manager.enthaelt_pdfs(self.tmp))
        open(os.path.join(self.tmp, "a", "b", "x.PDF"), "wb").close()
        self.assertTrue(folder_manager.enthaelt_pdfs(self.tmp))
        self.assertFalse(folder_manager.enthaelt_pdfs(self.tmp, max_tiefe=1))
        self.assertFalse(folder_manager.enthaelt_pdfs(os.path.join(self.tmp, "gibtsnicht")))

    def _fm(self):
        app = MagicMock()
        fm = FolderManager(app)
        fm.refresh_folder_tree = MagicMock()
        return fm

    def test_hinweis_nur_beim_ersten_oeffnen_mit_pdfs(self):
        open(os.path.join(self.tmp, "x.pdf"), "wb").close()
        fm = self._fm()
        with patch("folder_manager.messagebox.showinfo") as info:
            fm.uebernimm_hauptordner(self.tmp)
        info.assert_called_once()
        self.assertIn("Kopien", info.call_args[0][1])
        # Zweites Öffnen: Daten-Ordner existiert jetzt -> kein Hinweis mehr
        with patch("folder_manager.messagebox.showinfo") as info:
            self._fm().uebernimm_hauptordner(self.tmp)
        info.assert_not_called()

    def test_kein_hinweis_bei_leerem_ordner(self):
        with patch("folder_manager.messagebox.showinfo") as info:
            self._fm().uebernimm_hauptordner(self.tmp)
        info.assert_not_called()

    def test_willkommensdialog_nennt_kopien(self):
        import folder_manager
        self.assertIn("Kopien", folder_manager.SICHERUNGSHINWEIS)


class TestErsteinrichtung(unittest.TestCase):
    """Seniorenmodus Schritt 5: Start ohne Hauptordner bietet 'Dokumente\\KID' an."""

    def setUp(self):
        import tempfile, shutil
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        os.makedirs(os.path.join(self.home, "Documents"))
        self.app = MagicMock()
        self.app.master_folder = None
        self.fm = FolderManager(self.app)
        self.fm.uebernimm_hauptordner = MagicMock()
        self.fm.create_default_folders = MagicMock()

    def _starte(self, antwort):
        """antwort: True=Ja (Standardordner), False=Nein (selbst wählen), None=Abbrechen."""
        with patch("folder_manager.os.path.expanduser", return_value=self.home), \
             patch("folder_manager.messagebox.askyesnocancel", return_value=antwort) as frage:
            self.fm.ersteinrichtung_anbieten()
        return frage

    def test_ja_legt_kid_an_und_richtet_ein(self):
        self._starte(True)
        kid = os.path.join(self.home, "Documents", "KID")
        self.assertTrue(os.path.isdir(kid))
        self.fm.uebernimm_hauptordner.assert_called_once_with(kid)
        self.fm.create_default_folders.assert_called_once()

    def test_nein_oeffnet_eigene_ordnerwahl(self):
        """Nutzerwunsch 04.09.2026: den Zielordner auch selbst auswählen können."""
        def waehle():
            self.app.master_folder = self.home  # Nutzer hat einen Ordner gewählt
        self.fm.choose_master_folder = MagicMock(side_effect=waehle)
        self._starte(False)
        self.fm.choose_master_folder.assert_called_once()
        self.fm.create_default_folders.assert_called_once()   # Einrichtung auch beim eigenen Ordner
        self.assertFalse(os.path.isdir(os.path.join(self.home, "Documents", "KID")))

    def test_nein_und_dialog_abgebrochen_richtet_nichts_ein(self):
        self.fm.choose_master_folder = MagicMock()  # Nutzer bricht die Ordnerwahl ab
        self._starte(False)
        self.fm.create_default_folders.assert_not_called()

    def test_abbrechen_aendert_nichts(self):
        self._starte(None)
        self.assertFalse(os.path.isdir(os.path.join(self.home, "Documents", "KID")))
        self.fm.uebernimm_hauptordner.assert_not_called()

    def test_mit_gueltigem_hauptordner_kommt_keine_frage(self):
        self.app.master_folder = self.home  # existiert
        frage = self._starte(True)
        frage.assert_not_called()

    def test_ohne_documents_ordner_landet_kid_im_home(self):
        import shutil
        shutil.rmtree(os.path.join(self.home, "Documents"))
        self._starte(True)
        self.fm.uebernimm_hauptordner.assert_called_once_with(os.path.join(self.home, "KID"))

    def test_vorhandener_voller_kid_ordner_wird_nie_still_uebernommen(self):
        """Live-Fund 04.09.2026: alter Test-Ordner Documents\\KID wurde kommentarlos zum Hauptordner."""
        kid = os.path.join(self.home, "Documents", "KID")
        os.makedirs(os.path.join(kid, "Altbestand"))
        self.fm.choose_master_folder = MagicMock()
        with patch("folder_manager.os.path.expanduser", return_value=self.home), \
             patch("folder_manager.messagebox.askyesnocancel", return_value=True) as anlegen_frage, \
             patch("folder_manager.messagebox.askyesno", return_value=True) as warn_frage:
            self.fm.ersteinrichtung_anbieten()
        anlegen_frage.assert_not_called()   # keine Anlegen-Frage - nur die Warnung mit Wahl-Angebot
        warn_frage.assert_called_once()
        self.fm.choose_master_folder.assert_called_once()   # 'Ja' zur Warnung = selbst wählen
        self.fm.uebernimm_hauptordner.assert_not_called()

    def test_vorhandener_leerer_kid_ordner_ist_ok(self):
        os.makedirs(os.path.join(self.home, "Documents", "KID"))
        self._starte(True)
        self.fm.uebernimm_hauptordner.assert_called_once()


class TestVersteckteSystemdatei(unittest.TestCase):
    """desktop.ini & Co. gehören nicht in die Dokumentenliste (Live-Fund 06.09.2026:
    auto-selektierte desktop.ini bekam einen PDF-Metadaten-Schreibversuch)."""

    class _Entry:
        def __init__(self, name, attribute=None):
            self.name = name
            self._attribute = attribute

        def stat(self):
            if self._attribute is None:
                raise OSError("kein Zugriff")
            st = MagicMock()
            st.st_file_attributes = self._attribute
            return st

    def test_bekannte_systemnamen_werden_erkannt(self):
        import folder_manager
        self.assertTrue(folder_manager.ist_versteckte_systemdatei(self._Entry("desktop.ini")))
        self.assertTrue(folder_manager.ist_versteckte_systemdatei(self._Entry("Thumbs.db")))

    def test_versteckt_attribut_wird_erkannt(self):
        import folder_manager
        import stat as stat_modul
        versteckt = getattr(stat_modul, "FILE_ATTRIBUTE_HIDDEN", 2)
        self.assertTrue(folder_manager.ist_versteckte_systemdatei(
            self._Entry("geheim.pdf", attribute=versteckt)))

    def test_normale_datei_bleibt_sichtbar(self):
        import folder_manager
        self.assertFalse(folder_manager.ist_versteckte_systemdatei(self._Entry("Rechnung.pdf", attribute=0)))
        # Stat-Fehler: im Zweifel anzeigen statt verstecken
        self.assertFalse(folder_manager.ist_versteckte_systemdatei(self._Entry("Rechnung.pdf")))


class TestFormatiereTextqualitaet(unittest.TestCase):
    def test_prozent_und_unbekannt(self):
        import folder_manager
        self.assertEqual(folder_manager.formatiere_textqualitaet(92), "92 %")
        self.assertEqual(folder_manager.formatiere_textqualitaet(100.0), "100 %")
        self.assertEqual(folder_manager.formatiere_textqualitaet(None), "—")


class TestAktualisiereTextqualitaet(unittest.TestCase):
    """Nach 'Dokument neu erfassen' bekommt NUR die betroffene Zeile den frischen Wert (Nutzerwunsch 11.09.2026)."""

    def _app(self, sichtbar):
        from unittest.mock import MagicMock
        app = MagicMock()
        app.master_folder = r"C:\Sammlung"
        tree = app.tree_files
        tree.__getitem__ = lambda self, key: ("datum", "titel", "qualitaet") if sichtbar else ("datum", "titel")
        tree.get_children.return_value = ["i1", "i2"]
        tree.item.side_effect = lambda iid, was: {"i1": ("01.01.2024", "A", "", "a.pdf", "Ordner\\a.pdf", "Ordner", "", "20 %"),
                                                  "i2": ("01.01.2024", "B", "", "b.pdf", "Ordner\\b.pdf", "Ordner", "", "90 %")}[iid]
        return app

    def test_setzt_neuen_wert_in_die_richtige_zeile(self):
        from unittest.mock import patch
        import folder_manager
        app = self._app(sichtbar=True)
        fm = folder_manager.FolderManager(app)
        with patch("folder_manager.PDFHandler.get_textqualitaet", return_value=97):
            wert = fm.aktualisiere_textqualitaet(r"C:\Sammlung\Ordner\a.pdf")
        self.assertEqual(wert, "97 %")
        app.tree_files.set.assert_called_once_with("i1", "qualitaet", "97 %")

    def test_ausgeblendete_spalte_liest_nichts(self):
        from unittest.mock import patch
        import folder_manager
        app = self._app(sichtbar=False)
        fm = folder_manager.FolderManager(app)
        with patch("folder_manager.PDFHandler.get_textqualitaet") as lesen:
            self.assertIsNone(fm.aktualisiere_textqualitaet(r"C:\Sammlung\Ordner\a.pdf"))
            lesen.assert_not_called()
        app.tree_files.set.assert_not_called()

    def test_dokument_nicht_in_liste(self):
        from unittest.mock import patch
        import folder_manager
        app = self._app(sichtbar=True)
        fm = folder_manager.FolderManager(app)
        with patch("folder_manager.PDFHandler.get_textqualitaet", return_value=50):
            self.assertIsNone(fm.aktualisiere_textqualitaet(r"C:\Sammlung\Anderswo\x.pdf"))
        app.tree_files.set.assert_not_called()


class TestKlickEntschaerftSchild(unittest.TestCase):
    """FALLSTRICKE #74: ein liegengebliebenes Such-Schutzschild schluckte den nächsten Ordner-Klick."""

    def test_klick_auf_ordner_loescht_schild(self):
        app = MagicMock()
        app.tree_folders.identify_element.return_value = "text"
        fm = FolderManager(app)
        fm.ignore_next_select = True
        fm.on_tree_click(MagicMock(x=10, y=10))
        self.assertFalse(fm.ignore_next_select)


class TestOrdnerStillMarkieren(unittest.TestCase):
    def test_laden_false_markiert_ohne_neu_laden_und_schaerft_schild(self):
        app = MagicMock()
        app.tree_folders.get_children.return_value = ("F1",)
        app.tree_folders.item.side_effect = lambda iid, was=None, **kw: ("C:/x/A",) if was == "values" else None
        fm = FolderManager(app)
        fm.on_folder_select = MagicMock()
        self.assertTrue(fm._select_and_open_path("C:/x/A", laden=False))
        app.tree_folders.selection_set.assert_called_once_with("F1")
        fm.on_folder_select.assert_not_called()
        self.assertTrue(fm.ignore_next_select)


class TestPapierkorbAusblenden(unittest.TestCase):
    """Fund T0.8: Papierkorb ausblenden, während er angezeigt wird -> Hauptordner wählen."""

    def _fm(self, gewaehlt_pfad, zeigen):
        app = MagicMock()
        app.master_folder = "C:/Sammlung"
        app.show_trash_var.get.return_value = zeigen
        app.tree_folders.selection.return_value = ("P",)
        app.tree_folders.item.return_value = (gewaehlt_pfad,)
        fm = FolderManager(app)
        fm.refresh_folder_tree = MagicMock()
        fm._select_and_open_path = MagicMock()
        return fm

    def test_ausblenden_aus_dem_papierkorb_wechselt_zum_hauptordner(self):
        with patch("folder_manager.app_paths.is_trash_path", return_value=True):
            fm = self._fm("C:/Sammlung-Daten/Papierkorb", zeigen=False)
            fm.toggle_show_trash()
        fm._select_and_open_path.assert_called_once_with("C:/Sammlung")

    def test_ausblenden_aus_normalem_ordner_laesst_auswahl(self):
        with patch("folder_manager.app_paths.is_trash_path", return_value=False):
            fm = self._fm("C:/Sammlung/A", zeigen=False)
            fm.toggle_show_trash()
        fm._select_and_open_path.assert_not_called()

