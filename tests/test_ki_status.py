"""
Tests für ki_status.py (13.09.2026): Prüfstand des KI-Servers, Benachrichtigung der Abonnenten,
LED-Zustände, Menüsperre der KI-Werkzeuge im ToolManager.
"""

import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import ki_status
import tool_manager
from ki_status import KiLed, KiStatus


class TestKiStatus(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock()
        self.app.config.get.side_effect = lambda k, d=None: {"ollama_url": "http://srv:11434"}.get(k, d)
        self.app.root.after.side_effect = lambda ms, fn: fn()   # Hauptthread-Aufrufe sofort
        self.status = KiStatus(self.app, intervall=0.01, timeout=0.5)
        self.gesehen = []
        self.status.abonniere(self.gesehen.append)

    def test_abonnent_bekommt_sofort_den_unbekannten_stand(self):
        self.assertEqual(self.gesehen, [None])
        self.assertIsNone(self.status.erreichbar)

    def test_pruefung_meldet_nur_aenderungen(self):
        with patch("ollama_client.is_reachable", return_value=True) as ir:
            self.assertTrue(self.status.pruefe_einmal())
            self.assertFalse(self.status.pruefe_einmal())
            ir.assert_called_with("http://srv:11434", timeout=0.5)
        self.assertEqual(self.gesehen, [None, True])
        with patch("ollama_client.is_reachable", return_value=False):
            self.assertTrue(self.status.pruefe_einmal())
        self.assertEqual(self.gesehen, [None, True, False])
        self.assertTrue(any("nicht erreichbar" in str(k) for k in self.app.logger.warning.call_args_list))
        with patch("ollama_client.is_reachable", return_value=True):
            self.status.pruefe_einmal()
        self.assertTrue(any("wieder erreichbar" in str(k) for k in self.app.logger.info.call_args_list))

    def test_setze_von_aussen(self):
        self.assertTrue(self.status.setze(False))
        self.assertFalse(self.status.setze(False))
        self.assertEqual(self.gesehen, [None, False])

    def test_fehlerhafter_abonnent_stoppt_andere_nicht(self):
        self.status.abonniere(lambda e: 1 / 0)
        spaeter = []
        self.status.abonniere(spaeter.append)
        self.status.setze(True)
        self.assertEqual(spaeter, [None, True])

    def test_thread_prueft_und_stoppt(self):
        import time
        with patch("ollama_client.is_reachable", return_value=True):
            self.status.start()
            for _ in range(50):
                if self.status.erreichbar is True:
                    break
                time.sleep(0.02)
            self.status.stop()
        self.assertTrue(self.status.erreichbar)


class TestWecken(unittest.TestCase):
    """Doppelklick auf die LED = Wake-on-LAN (01.11.2026)."""

    def setUp(self):
        self.werte = {"ollama_url": "http://srv:11434", "ki_wol_mac": "aa-bb-cc-11-22-33"}
        self.app = MagicMock()
        self.app.config.get.side_effect = lambda k, d=None: self.werte.get(k, d)
        self.app.root.after.side_effect = lambda ms, fn: fn()
        self.status = KiStatus(self.app, intervall=0.01, timeout=0.5)
        self.status.erreichbar = False

    def test_sendet_an_normalisierte_mac_und_wartet(self):
        with patch("server_wecken.sende") as sende:
            self.assertEqual(self.status.wecke(), "gesendet")
            sende.assert_called_once_with("AA:BB:CC:11:22:33")
            self.assertTrue(self.status.weckt)
            self.assertEqual(self.status.wecke(), "weckt")       # zweiter Doppelklick schickt nicht noch einmal
            self.assertEqual(sende.call_count, 1)
        with patch("ollama_client.is_reachable", return_value=True):
            self.status.pruefe_einmal()
        self.assertFalse(self.status.weckt)
        self.assertFalse(self.status.weckversuch_gescheitert)
        self.assertEqual(self.status.wecke(), "laeuft")

    def test_gibt_nach_weck_dauer_auf(self):
        with patch("server_wecken.sende"):
            self.status.wecke()
        with patch("ollama_client.is_reachable", return_value=False):
            self.status.pruefe_einmal()
            self.assertTrue(self.status.weckt)                   # innerhalb der Wartezeit: weiter warten
            self.status._weck_ende = 0
            self.status.pruefe_einmal()
        self.assertFalse(self.status.weckt)
        self.assertTrue(self.status.weckversuch_gescheitert)
        self.assertTrue(any("nicht aufgewacht" in str(k) for k in self.app.logger.warning.call_args_list))

    def test_ohne_mac_und_bei_sendefehler(self):
        self.werte["ki_wol_mac"] = ""
        with patch("ki_status.messagebox") as mb:
            self.assertEqual(self.status.wecken_per_klick(), "keine_mac")
            mb.showinfo.assert_called_once()
        self.werte["ki_wol_mac"] = "AA:BB:CC:11:22:33"
        with patch("server_wecken.sende", side_effect=OSError("kein Netz")), patch("ki_status.messagebox") as mb:
            self.assertTrue(self.status.wecken_per_klick().startswith("fehler"))
            mb.showwarning.assert_called_once()
        self.assertFalse(self.status.weckt)


class TestKiLed(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.led = KiLed(self.root)

    def tearDown(self):
        self.root.destroy()

    def test_zustaende(self):
        self.assertEqual(self.led.text(), "KI: prüfe…")
        self.led.zeige(True)
        self.assertEqual(self.led.text(), "KI verbunden")
        self.assertEqual(self.led._canvas.itemcget(self.led._punkt, "fill"), ki_status.FARBE_VERBUNDEN)
        self.led.zeige(False)
        self.assertEqual(self.led.text(), "KI nicht erreichbar")
        self.assertEqual(self.led._canvas.itemcget(self.led._punkt, "fill"), ki_status.FARBE_GETRENNT)
        self.led.zeige(None)
        self.assertEqual(self.led._canvas.itemcget(self.led._punkt, "fill"), ki_status.FARBE_UNBEKANNT)

    def test_text_nur_als_tooltip(self):
        """Peter 13.09.2026: kein Dauertext neben dem Punkt - der Zustand steht im Tooltip."""
        self.assertEqual([type(w).__name__ for w in self.led.winfo_children()], ["Canvas"])
        self.led.zeige(False)
        self.assertEqual(self.led.tooltip.text(), "KI nicht erreichbar")

    def test_weck_zustand_orange_und_tooltip(self):
        app = MagicMock()
        werte = {"ki_wol_mac": "AA:BB:CC:11:22:33"}
        app.config.get.side_effect = lambda k, d=None: werte.get(k, d)
        app.root.after.side_effect = lambda ms, fn: fn()
        status = KiStatus(app)
        status.erreichbar = False
        self.led.verbinde(status)
        self.assertEqual(self.led.text(), "KI nicht erreichbar (Doppelklick: Server wecken)")
        with patch("server_wecken.sende"):
            status.wecke()
        self.assertEqual(self.led._canvas.itemcget(self.led._punkt, "fill"), ki_status.FARBE_WECKT)
        self.assertEqual(self.led.text(), "KI-Server wird geweckt…")
        status._weck_ende = 0
        with patch("ollama_client.is_reachable", return_value=False):
            status.pruefe_einmal()
        self.assertEqual(self.led._canvas.itemcget(self.led._punkt, "fill"), ki_status.FARBE_GETRENNT)
        self.assertIn("Wecken hat nicht geklappt", self.led.text())
        werte["ki_wol_mac"] = ""
        self.assertEqual(self.led.text(), "KI nicht erreichbar - Wecken hat nicht geklappt")
        self.assertIn("<Double-Button-1>", self.led._canvas.bind())


class _Tool:
    def __init__(self, name, braucht_ki, gruppe="KI-Helfer"):
        self.name = name
        self.menu_label = name
        self.menu_group = gruppe
        self.menu_hooks = ["main_menu", "context_menu"]
        self.braucht_ki = braucht_ki
        self.required_input = "none"


class TestMenuesperre(unittest.TestCase):
    """ToolManager sperrt die Menüeinträge der KI-Werkzeuge, solange der Server nicht erreichbar ist."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = MagicMock()
        self.app.root = self.root
        with patch.object(tool_manager.ToolManager, "_load_tools", lambda self: None):
            self.tm = tool_manager.ToolManager(self.app)
        self.ki = _Tool("Titel (KI)", True)
        self.frei = _Tool("Inspektor", False, "PDF-Werkzeuge")
        self.tm.tools = [self.ki, self.frei]
        self.menubar = tk.Menu(self.root)
        self.menubar.add_cascade(label="Hilfe", menu=tk.Menu(self.menubar))
        self.tm.populate_main_menu(self.menubar)
        self.kontext = tk.Menu(self.root)
        self.tm.populate_context_menu(self.kontext)

    def tearDown(self):
        self.root.destroy()

    def _zustaende(self, tool):
        return [menu.entrycget(i, "state") for menu, i in self.tm._eintraege[tool]]

    def test_sperren_und_freigeben(self):
        self.assertEqual(len(self.tm._eintraege[self.ki]), 2)   # Untermenü + Kontextmenü
        self.tm.setze_ki_verfuegbar(False)
        self.assertEqual(self._zustaende(self.ki), ["disabled", "disabled"])
        self.assertEqual(self._zustaende(self.frei), ["normal", "normal"])
        self.tm.setze_ki_verfuegbar(True)
        self.assertEqual(self._zustaende(self.ki), ["normal", "normal"])
        self.tm.setze_ki_verfuegbar(None)   # ungeprüft = nicht sperren
        self.assertEqual(self._zustaende(self.ki), ["normal", "normal"])

    def test_execute_tool_blockt_ki_tool_ohne_server(self):
        self.tm.setze_ki_verfuegbar(False)
        with patch("tool_manager.mb.showwarning") as warnung:
            self.assertFalse(self.tm.execute_tool(self.ki))
            warnung.assert_called_once()

    def test_echte_ki_tools(self):
        """Die Werkzeuge, die ohne Server nichts können, tragen braucht_ki."""
        with patch.object(tool_manager.ToolManager, "_load_tools", lambda self: None):
            tm = tool_manager.ToolManager(MagicMock())
        tm.tools = []
        tm.__init__(MagicMock())   # lädt die echten Tools
        self.assertEqual(sorted(tm.ki_tools()),
                         sorted(["Titel-Vorschlag (KI)", "Vollautomatik: Ablage-Vorschau",
                                 "Vollautomatik: Posteingang verarbeiten",
                                 "Absender nachlesen",
                                 "Vollautomatik: Begleitet erfassen"]))


if __name__ == "__main__":
    unittest.main()
