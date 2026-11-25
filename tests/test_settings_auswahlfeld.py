"""Auswahlfelder der Einstellungen (Etappe 13 Schritt 1): Modellliste vom Server, kein Umstellen per Mausrad."""
import glob
import os
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import ollama_client
from tools.settings_editor import (SettingsEditorWindow, auswahlfeld, fehlende_modelle_text, modell_aus_anzeige,
                                   modelle_beschriftet, zuletzt_verwendet)


class TestVermerke(unittest.TestCase):
    """Peter 19.11.2026: Standardmodell und zuletzt verwendetes Modell in der Liste markieren; seit 23.11.2026 heißt
    das Standardmodell dort „empfohlen“ (Etappe 13 Schritt 5)."""

    def test_empfohlen_und_zuletzt_verwendet_markiert(self):
        liste = modelle_beschriftet(["a:1", "qwen3.5:9b", "x:2"], "qwen3.5:9b", "x:2")
        self.assertEqual(liste[0], "a:1")
        self.assertIn("empfohlen", liste[1])
        self.assertIn("zuletzt verwendet", liste[2])
        beide = modelle_beschriftet(["qwen3.5:9b"], "qwen3.5:9b", "qwen3.5:9b")[0]
        self.assertIn("empfohlen, zuletzt verwendet", beide)
        self.assertEqual([modell_aus_anzeige(e) for e in liste], ["a:1", "qwen3.5:9b", "x:2"])
        self.assertEqual(modell_aus_anzeige(beide), "qwen3.5:9b")

    def test_zuletzt_verwendet_ohne_aenderung_ist_das_eingestellte(self):
        self.assertEqual(zuletzt_verwendet("", "qwen3.5:9b"), "qwen3.5:9b")
        self.assertEqual(zuletzt_verwendet("gemma4:12b", "qwen3.5:9b"), "gemma4:12b")


class TestFehlendeModelle(unittest.TestCase):
    """Etappe 13 Schritt 5: „Verbindung testen“ prüft Lese-Modell UND Zweitmeinung und nennt den Befehl zum Laden."""

    def test_alles_da_oder_zweitmeinung_aus(self):
        self.assertEqual(fehlende_modelle_text(["qwen3.5:9b", "clef-flash:9b"], "qwen3.5:9b", "clef-flash:9b"), "")
        self.assertEqual(fehlende_modelle_text(["qwen3.5:9b"], "qwen3.5:9b", ""), "")
        self.assertEqual(fehlende_modelle_text(["qwen3.5:9b"], "qwen3.5", ""), "")      # ohne Etikett wie bisher

    def test_zweitmeinung_fehlt(self):
        text = fehlende_modelle_text(["qwen3.5:9b"], "qwen3.5:9b", "clef-flash:9b")
        self.assertIn("ollama pull clef-flash:9b", text)
        self.assertNotIn("ollama pull qwen3.5:9b", text)
        self.assertIn("Zweitmeinung", text)

    def test_beide_fehlen(self):
        text = fehlende_modelle_text([], "qwen3.5:9b", "clef-flash:9b")
        self.assertIn("ollama pull qwen3.5:9b", text)
        self.assertIn("ollama pull clef-flash:9b", text)

    def _verbindungstest(self, modelle, zweit):
        fenster = MagicMock()
        fenster.var_ollama_url.get.return_value = "http://localhost:11434"
        fenster.var_ollama_model.get.return_value = "qwen3.5:9b"
        fenster.var_entscheidungsmodell.get.return_value = zweit
        with patch("tools.settings_editor.ollama_client.is_reachable", return_value=True), \
                patch("tools.settings_editor.ollama_client.list_models", return_value=modelle), \
                patch("tools.settings_editor.ollama_client.gpu_status", return_value=("gpu", "6,6 GB")), \
                patch("tools.settings_editor.threading.Thread") as thread, \
                patch("tools.settings_editor.messagebox") as box:
            SettingsEditorWindow._test_ollama_connection(fenster)
            if thread.called:
                thread.call_args.kwargs["target"]()
                fenster.after.call_args.args[1]()
        return fenster, box

    def test_verbindungstest_ohne_lese_modell_warnt_mit_befehl(self):
        fenster, box = self._verbindungstest(["clef-flash:9b"], "clef-flash:9b")
        self.assertIn("ollama pull qwen3.5:9b", box.showwarning.call_args.args[1])
        fenster._zeige_gpu_status.assert_not_called()

    def test_verbindungstest_ohne_zweitmeinung_prueft_weiter_und_nennt_den_befehl(self):
        fenster, box = self._verbindungstest(["qwen3.5:9b"], "clef-flash:9b   ← empfohlen")
        box.showwarning.assert_not_called()
        text = fenster._zeige_gpu_status.call_args.args[0]
        self.assertIn("ollama pull clef-flash:9b", text)
        self.assertNotIn("←", text)

    def test_verbindungstest_mit_beiden_ohne_hinweis(self):
        fenster, box = self._verbindungstest(["qwen3.5:9b", "clef-flash:9b"], "clef-flash:9b")
        self.assertNotIn("ollama pull", fenster._zeige_gpu_status.call_args.args[0])


class TestLeeresModell(unittest.TestCase):
    """Peter 23.11.2026 beim Test T9c.8: beide Felder geleert, gespeichert wurde "" - die KI fragte nach einem Modell
    ohne Namen (FALLSTRICKE #145)."""

    def _uebernehmen(self, feld, gespeichert):
        fenster = MagicMock()
        fenster.app.config.get.return_value = gespeichert
        fenster.var_ollama_model.get.return_value = feld
        SettingsEditorWindow._modell_uebernehmen(fenster)
        return fenster

    def test_leeres_feld_springt_auf_das_empfohlene(self):
        fenster = self._uebernehmen("  ", "gemma4:12b")
        fenster.var_ollama_model.set.assert_called_once_with(ollama_client.DEFAULT_MODEL)
        fenster.app.config.set.assert_any_call("ollama_model", ollama_client.DEFAULT_MODEL)
        fenster.app.config.set.assert_any_call("ollama_model_zuletzt", "gemma4:12b")

    def test_leeres_feld_beim_empfohlenen_speichert_nichts(self):
        fenster = self._uebernehmen("", ollama_client.DEFAULT_MODEL)
        fenster.var_ollama_model.set.assert_called_once_with(ollama_client.DEFAULT_MODEL)
        fenster.app.config.set.assert_not_called()

    def test_schon_leer_gespeichert_gilt_als_das_empfohlene(self):
        for wert, erwartet in (("", ollama_client.DEFAULT_MODEL), ("  ", ollama_client.DEFAULT_MODEL),
                               (None, ollama_client.DEFAULT_MODEL), ("gemma4:12b", "gemma4:12b")):
            self.assertEqual(ollama_client.eingestelltes_modell({"ollama_model": wert}), erwartet, repr(wert))
        self.assertEqual(ollama_client.eingestelltes_modell({}), ollama_client.DEFAULT_MODEL)

    def test_niemand_liest_das_modell_am_helfer_vorbei(self):
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
        vorbei = []
        for pfad in glob.glob(os.path.join(src, "**", "*.py"), recursive=True):
            with open(pfad, encoding="utf-8") as f:
                if 'get("ollama_model"' in f.read():
                    vorbei.append(os.path.basename(pfad))
        # settings_editor vergleicht beim Speichern mit dem rohen Wert
        self.assertEqual(sorted(vorbei), ["ollama_client.py", "settings_editor.py"])


class TestAuswahlfeld(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.geometry("+-3000+-3000")   # gezeichnet, aber außerhalb des Bildschirms (Ereignisse brauchen ein Fenster)

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_mausrad_stellt_nichts_um(self):
        # FALLSTRICKE #133: das Rad blätterte die Werte durch und meldete <<ComboboxSelected>> - beim Scrollen über
        # die Einstellungen stellte sich so still das KI-Modell um
        var = tk.StringVar(value="b:1")
        gespeichert = []
        feld = auswahlfeld(self.root, var, lambda: gespeichert.append(var.get()), values=["a:1", "b:1", "c:1"])
        feld.pack()
        self.root.update()
        feld.event_generate("<MouseWheel>", delta=-120)
        feld.event_generate("<MouseWheel>", delta=120)
        feld.event_generate("<MouseWheel>", delta=120)
        self.root.update()
        self.assertEqual(var.get(), "b:1")
        self.assertEqual(gespeichert, [])
        feld.destroy()

    def test_auswahl_wird_uebernommen(self):
        var = tk.StringVar(value="a:1")
        gespeichert = []
        feld = auswahlfeld(self.root, var, lambda: gespeichert.append(var.get()), values=["a:1", "b:1"])
        feld.pack()
        self.root.update()
        feld.current(1)
        feld.event_generate("<<ComboboxSelected>>")
        self.assertEqual(gespeichert, ["b:1"])
        feld.destroy()

    def test_gespeichert_wird_der_name_ohne_vermerk(self):
        var = tk.StringVar(value="a:1")
        gespeichert = []
        werte = modelle_beschriftet(["a:1", "b:1"], "b:1", "a:1")
        feld = auswahlfeld(self.root, var, lambda: gespeichert.append(var.get()), bereinige=modell_aus_anzeige,
                           values=werte)
        feld.pack()
        self.root.update()
        feld.current(1)
        feld.event_generate("<<ComboboxSelected>>")
        self.assertEqual(gespeichert, ["b:1"])
        self.assertEqual(var.get(), "b:1")
        feld.destroy()


class TestStartgroesseNachInhalt(unittest.TestCase):
    """Peter 21.11.2026 bei T9c.7: im Reiter „KI-Server“ war „Verbindung testen“ abgeschnitten - der Reiter brauchte
    630 px, das Fenster öffnete fest mit 620. Die Startgröße wächst jetzt auf den größten Reiter (bildschirmbegrenzt)."""

    def test_startgroesse_waechst_auf_den_inhalt(self):
        import inspect
        from tools.settings_editor import SettingsEditorWindow
        quelle = inspect.getsource(SettingsEditorWindow.__init__)
        self.assertIn("max(hoehe, self.winfo_reqheight())", quelle)
        self.assertIn("max(breite, self.winfo_reqwidth())", quelle)
        self.assertLess(quelle.index("self._setup_ui()"), quelle.index("max(hoehe, self.winfo_reqheight())"))


if __name__ == "__main__":
    unittest.main()
