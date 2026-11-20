"""Auswahlfelder der Einstellungen (Etappe 13 Schritt 1): Modellliste vom Server, kein Umstellen per Mausrad."""
import tkinter as tk
import unittest

from tools.settings_editor import auswahlfeld, modell_aus_anzeige, modelle_beschriftet, zuletzt_verwendet


class TestVermerke(unittest.TestCase):
    """Peter 19.11.2026: Standardmodell und zuletzt verwendetes Modell in der Liste markieren."""

    def test_standard_und_zuletzt_verwendet_markiert(self):
        liste = modelle_beschriftet(["a:1", "qwen3.5:9b", "x:2"], "qwen3.5:9b", "x:2")
        self.assertEqual(liste[0], "a:1")
        self.assertIn("Standard", liste[1])
        self.assertIn("zuletzt verwendet", liste[2])
        beide = modelle_beschriftet(["qwen3.5:9b"], "qwen3.5:9b", "qwen3.5:9b")[0]
        self.assertIn("Standard, zuletzt verwendet", beide)
        self.assertEqual([modell_aus_anzeige(e) for e in liste], ["a:1", "qwen3.5:9b", "x:2"])
        self.assertEqual(modell_aus_anzeige(beide), "qwen3.5:9b")

    def test_zuletzt_verwendet_ohne_aenderung_ist_das_eingestellte(self):
        self.assertEqual(zuletzt_verwendet("", "qwen3.5:9b"), "qwen3.5:9b")
        self.assertEqual(zuletzt_verwendet("gemma4:12b", "qwen3.5:9b"), "gemma4:12b")


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


if __name__ == "__main__":
    unittest.main()
