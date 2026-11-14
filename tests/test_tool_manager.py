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
