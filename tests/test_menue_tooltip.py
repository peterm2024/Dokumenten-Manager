"""Menü-Hilfe Stufe 3 (menue_tooltip.py): Menü-Erkennung über Label-Folgen, Fensterchen mit Was/Wofür."""
import tkinter as tk
import unittest
from types import SimpleNamespace

import menue_hilfe
import menue_tooltip


class TestReineLogik(unittest.TestCase):
    def test_pfad_fuer_labels(self):
        karte = {"": ("Datei", "Hilfe"), "Datei": ("Öffnen", "Beenden"), "Rechtsklick Ordner": ("Neu", "Umbenennen (F2)")}
        self.assertEqual(menue_tooltip.pfad_fuer_labels(karte, ["Öffnen", "Beenden"]), "Datei")
        self.assertEqual(menue_tooltip.pfad_fuer_labels(karte, ("Datei", "Hilfe")), "")
        self.assertIsNone(menue_tooltip.pfad_fuer_labels(karte, ["Öffnen"]))

    def test_erklaerungs_text(self):
        e = menue_hilfe.Eintrag("Datei", "X", "tut was", "")
        text = menue_tooltip.erklaerungs_text(e)
        self.assertIn("Was: tut was", text)
        self.assertIn("(keine Erklärung hinterlegt)", text)


class TestMitTk(unittest.TestCase):
    """Echte Menüs (Menüleiste mit Kaskade, Kontextmenü), aber ohne Maus: Handler direkt aufrufen."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        mb = tk.Menu(self.root)
        self.root.config(menu=mb)
        self.datei = tk.Menu(mb, tearoff=0)
        self.datei.add_command(label="Einstellungen...")
        self.datei.add_separator()
        self.datei.add_command(label="Umbenennen (F2)")
        mb.add_cascade(label="Datei", menu=self.datei)
        self.kontext = tk.Menu(self.root, tearoff=0)
        self.kontext.add_command(label="Umbenennen (F2)")
        self.eintraege = [
            menue_hilfe.Eintrag("Datei", "Einstellungen...", "öffnet Reiter", "alles an einem Ort"),
            menue_hilfe.Eintrag("Datei", "Umbenennen (F2)", "DATEI-Variante", "x"),
            menue_hilfe.Eintrag("Rechtsklick Ordner", "Umbenennen (F2)", "ORDNER-Variante", "y"),
        ]
        self.aktiv = True
        self.tooltip = menue_tooltip.MenueTooltip(self.root, lambda: list(self.eintraege),
                                                  zusatz_menues={"Rechtsklick Ordner": self.kontext},
                                                  aktiv_fn=lambda: self.aktiv)

    def tearDown(self):
        self.root.destroy()

    def test_menue_karte_und_pfad(self):
        self.assertEqual(self.tooltip._pfad_fuer(str(self.datei)), "Datei")
        self.assertEqual(self.tooltip._pfad_fuer(str(self.kontext)), "Rechtsklick Ordner")
        self.assertEqual(self.tooltip._pfad_fuer(str(self.root.cget("menu"))), "")

    def test_zeigt_richtige_variante_je_menue(self):
        self.tooltip._zeige_fuer(str(self.datei), "Umbenennen (F2)")
        self.assertTrue(self.tooltip.sichtbar())
        self.assertEqual(self.tooltip.letzter_eintrag.was, "DATEI-Variante")
        self.tooltip._zeige_fuer(str(self.kontext), "Umbenennen (F2)")
        self.assertEqual(self.tooltip.letzter_eintrag.was, "ORDNER-Variante")
        self.assertTrue(self.tooltip.sichtbar())

    def test_menueleiste_und_unbekannte_eintraege_zeigen_nichts(self):
        self.tooltip._zeige_fuer(str(self.root.cget("menu")), "Datei")
        self.assertFalse(self.tooltip.sichtbar())
        self.tooltip._zeige_fuer(str(self.datei), "Gibt es nicht")
        self.assertFalse(self.tooltip.sichtbar())

    def test_menu_select_plant_und_abwahl_versteckt(self):
        """<<MenuSelect>> mit aktivem Eintrag plant die Anzeige; „none" (Menü zu) räumt weg.
        (Tk stellt Ereignisse an ungepostete Menüs nicht zu - der Handler wird direkt gerufen.)"""
        self.datei.activate(0)
        self.tooltip._on_menu_select(SimpleNamespace(widget=self.datei))
        self.assertIsNotNone(self.tooltip._job)
        self.root.after_cancel(self.tooltip._job)
        self.tooltip._zeige_fuer(str(self.datei), "Einstellungen...")
        self.assertTrue(self.tooltip.sichtbar())
        self.datei.activate("none")
        self.tooltip._on_menu_select(SimpleNamespace(widget=self.datei))
        self.assertFalse(self.tooltip.sichtbar())

    def test_abgeschaltet_plant_nichts(self):
        self.aktiv = False
        self.datei.activate(0)
        self.tooltip._on_menu_select(SimpleNamespace(widget=self.datei))
        self.assertIsNone(self.tooltip._job)


if __name__ == "__main__":
    unittest.main()
