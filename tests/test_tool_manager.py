"""Tools-Menü mit Untermenüs (tool_manager.gruppiere_tools, 07.09.2026)."""
import unittest

import tool_manager


class _Tool:
    def __init__(self, name, gruppe="", label=None):
        self.name = name
        self.menu_group = gruppe
        self.menu_label = label or name


class TestUntermenue(unittest.TestCase):
    """Ein Tool mit `fuelle_kontextmenue` bekommt im Rechtsklick ein Untermenü, frisch gefüllt bei jedem Öffnen
    (Wiki, 12.11.2026); ein Fehler darin kostet nur das Untermenü."""

    def setUp(self):
        import tkinter as tk
        from unittest.mock import MagicMock, patch
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        app = MagicMock()
        app.tree_files.selection.return_value = ()
        with patch.object(tool_manager.ToolManager, "_load_tools", lambda self: None):
            self.tm = tool_manager.ToolManager(app)
        self.menu = tk.Menu(self.root, tearoff=0)

    def test_untermenue_frisch_und_fehler_bleibt_drin(self):
        import tkinter as tk
        aufrufe = []

        class MitUntermenue(_Tool):
            def fuelle_kontextmenue(self, menu, context):
                aufrufe.append(context.selected_files)
                unter = tk.Menu(menu, tearoff=0)
                unter.add_command(label="tief")
                menu.add_cascade(label=f"Lauf {len(aufrufe)}", menu=unter)
                if len(aufrufe) == 3:
                    raise RuntimeError("kaputt")

        t, schlicht = MitUntermenue("Wiki", ""), _Tool("Inspektor", "")
        t.menu_hooks = schlicht.menu_hooks = ["context_menu"]
        self.tm.tools = [t, schlicht]
        self.tm.populate_context_menu(self.menu)
        self.assertEqual([self.menu.type(i) for i in range(3)], ["separator", "cascade", "command"])
        self.assertEqual(self.menu.entrycget(1, "label"), "🛠 Wiki")
        unter = self.root.nametowidget(self.menu.entrycget(1, "menu"))
        for _ in range(2):
            self.root.tk.eval(unter.cget("postcommand"))               # wie Tk vor dem Aufklappen
        self.assertEqual((unter.index("end"), unter.entrycget(0, "label")), (0, "Lauf 2"))   # nicht angehängt
        self.assertEqual(len(unter.winfo_children()), 1)                                       # altes Unter-Untermenü weg
        with self.assertLogs("DocManager", "ERROR"):
            self.tm.fuelle_untermenue(t, unter)
        self.assertEqual((unter.index("end"), unter.entrycget(0, "state")), (0, "disabled"))
        self.assertEqual(unter.winfo_children(), [])
        self.assertEqual(aufrufe, [[], [], []])

    def test_rechtsklick_im_ordnerbaum(self):
        """Tools mit "folder_menu" (25.11.2026): grau, wenn sie mit dem angeklickten Ordner nichts anfangen können."""
        from unittest.mock import patch
        gewaehlt = []

        class FuerOrdner(_Tool):
            ordner_label, menu_hooks = "Wiki: Dokumente lesen…", ["folder_menu"]

            def ordner_moeglich(self, app, pfad):
                return pfad != "C:/S/0_Posteingang"

            def oeffne_ordner(self, app, pfad):
                gewaehlt.append(pfad)
                if len(gewaehlt) == 2:
                    raise RuntimeError("kaputt")

        anderes = _Tool("Inspektor")
        anderes.menu_hooks = ["context_menu"]
        self.menu.add_command(label="Aktualisieren")
        self.tm.tools = [anderes]
        self.tm.populate_folder_menu(self.menu)
        self.assertEqual(self.menu.index("end"), 0)                    # kein Tool für Ordner: auch keine Trennlinie
        self.tm.tools = [FuerOrdner("Wiki"), anderes]
        self.tm.populate_folder_menu(self.menu)
        self.assertEqual([self.menu.type(i) for i in range(3)], ["command", "separator", "command"])
        self.assertEqual(self.menu.entrycget(2, "label"), "🛠 Wiki: Dokumente lesen…")
        baum = self.tm.app.tree_folders
        for auswahl, pfad, zustand in (((), None, "disabled"), (("i1",), "C:/S/0_Posteingang", "disabled"),
                                       (("i2",), "C:/S/Stadtwerke", "normal")):
            baum.selection.return_value, baum.item.return_value = auswahl, (pfad,) if pfad else ()
            self.root.tk.eval(self.menu.cget("postcommand"))           # wie Tk vor dem Aufklappen
            self.assertEqual(self.menu.entrycget(2, "state"), zustand)
        self.menu.invoke(2)
        self.assertEqual(gewaehlt, ["C:/S/Stadtwerke"])
        with patch("tool_manager.mb.showerror") as fehler:
            self.menu.invoke(2)
        fehler.assert_called_once()
        baum.selection.return_value = ()
        self.menu.invoke(2)                                            # nichts markiert: nichts geschieht
        self.assertEqual(len(gewaehlt), 2)


class TestGruppiereTools(unittest.TestCase):

    def test_feste_reihenfolge_dann_unbekannte_dann_ohne_gruppe(self):
        tools = [
            _Tool("Inspektor", "PDF-Werkzeuge"),
            _Tool("Sonstiges"),
            _Tool("Protokoll", "Vollautomatik"),
            _Tool("Fremd", "Experimente"),
            _Tool("Dubletten", "Aufräumen"),
            _Tool("Vorschau", "Vollautomatik"),
        ]
        gruppen = tool_manager.gruppiere_tools(tools)
        self.assertEqual([g for g, _ in gruppen], ["Vollautomatik", "Aufräumen", "PDF-Werkzeuge", "Experimente", ""])
        self.assertEqual([t.name for t in dict(gruppen)["Vollautomatik"]], ["Protokoll", "Vorschau"])  # Ladereihenfolge
        self.assertEqual([t.name for t in dict(gruppen)[""]], ["Sonstiges"])

    def test_ohne_gruppen_nur_oberste_ebene(self):
        gruppen = tool_manager.gruppiere_tools([_Tool("A"), _Tool("B", "  ")])
        self.assertEqual(gruppen, [("", gruppen[0][1])])
        self.assertEqual([t.name for t in gruppen[0][1]], ["A", "B"])

    def test_leer(self):
        self.assertEqual(tool_manager.gruppiere_tools([]), [])

    def test_echte_tools_haben_gruppe_und_kurzlabel(self):
        """Jedes ausgelieferte Tool im Tools-Menü gehört zu einer der festen Gruppen."""
        from unittest.mock import MagicMock
        manager = tool_manager.ToolManager(MagicMock())
        im_menue = [t for t in manager.tools if "main_menu" in t.menu_hooks]
        self.assertGreaterEqual(len(im_menue), 10)
        for tool in im_menue:
            self.assertIn(tool.menu_group, tool_manager.GRUPPEN_REIHENFOLGE, tool.name)
            self.assertTrue(tool.menu_label.strip(), tool.name)
        # Einstellungen sitzen im Datei-Menü, nicht mehr unter Tools - aber auffindbar
        self.assertNotIn("Einstellungen...", [t.name for t in im_menue])
        self.assertIsNotNone(manager.finde_tool("SettingsEditorTool"))
        self.assertIsNotNone(manager.finde_tool("Einstellungen..."))
        self.assertIsNone(manager.finde_tool("Gibt es nicht"))


if __name__ == "__main__":
    unittest.main()
