"""Helles Design (ui_theme, Etappe 11): Options-Datenbank, Knopf-Stile, Vorrang der Bedeutungsfarben."""
import tkinter as tk
import unittest
from tkinter import ttk

import ui_theme


class TestFarbwert(unittest.TestCase):
    def test_colorref_ist_bgr(self):
        self.assertEqual(ui_theme.colorref("#0067c0"), 0xC06700)
        self.assertEqual(ui_theme.colorref("#ffffff"), 0xFFFFFF)


class TestWendeAn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        ui_theme.wende_an(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def test_klassische_elemente_bekommen_die_palette(self):
        f = ui_theme.FARBEN
        self.assertEqual(tk.Label(self.root).cget("background"), f["fenster"])
        self.assertEqual(tk.Frame(self.root).cget("background"), f["fenster"])
        self.assertEqual(tk.Entry(self.root).cget("background"), f["flaeche"])
        self.assertEqual(tk.Text(self.root).cget("background"), f["flaeche"])
        self.assertEqual(str(tk.Button(self.root).cget("relief")), "flat")

    def test_auswahl_und_hervorhebung_bleiben_systemfarben(self):
        # Peter 17.11.2026: „Die Auswahlfarbe Schwarz ist zu intensiv“ - "*Foreground" (KLASSE) traf auch die
        # Menü-Hervorhebung, die Listen-/Text-Auswahl und die Hover-Schrift der Häkchen (Tk-Optionsklassen)
        f = ui_theme.FARBEN
        self.assertNotEqual(str(tk.Menu(self.root).cget("activebackground")), f["text"])
        self.assertNotEqual(str(tk.Listbox(self.root).cget("selectbackground")), f["text"])
        self.assertNotEqual(str(tk.Text(self.root).cget("selectbackground")), f["text"])
        self.assertNotEqual(str(tk.Checkbutton(self.root).cget("activeforeground")), f["fenster"])
        self.assertEqual(str(tk.Label(self.root).cget("foreground")), f["text"])

    def test_spaltenkoepfe_mit_feiner_linie(self):
        # Peter 17.11.2026: weiße Spaltenköpfe ohne Linie auf weißem Grund - unten/rechts 1 px in `rand`
        s = ttk.Style(self.root)
        self.assertEqual(str(s.lookup("Treeview.Heading", "relief")), "raised")
        self.assertEqual(s.lookup("Treeview.Heading", "darkcolor"), ui_theme.FARBEN["rand"])
        self.assertEqual(s.lookup("Treeview.Heading", "bordercolor"), ui_theme.FARBEN["kopf"])

    def test_wurzelfenster_ohne_grauen_rand(self):
        # Das Wurzelfenster entsteht vor der Options-Datenbank - ohne eigenes Färben blieb ein Rand in #f0f0f0
        self.assertEqual(str(self.root.cget("background")), ui_theme.FARBEN["fenster"])

    def test_ausdrueckliche_bedeutungsfarbe_geht_vor(self):
        # Zeilenstatus, Suchfeld gelb/grün, Tag-Markierung ... setzen ihre Farbe ausdrücklich
        self.assertEqual(tk.Label(self.root, bg="#fffbe6").cget("background"), "#fffbe6")

    def test_reset_knopf_auf_leistenfarbe(self):
        # Peter 17.11.2026: das „✖“ hatte ein eigenes Grau, weder Feld noch Leiste
        s = ttk.Style(self.root)
        self.assertEqual(s.lookup("Danger.TButton", "background"), ui_theme.FARBEN["fenster"])
        self.assertEqual(s.lookup("Danger.TButton", "foreground"), ui_theme.FARBEN["gefahr"])
        self.assertEqual(s.lookup("Accent.TButton", "background"), ui_theme.FARBEN["akzent"])

    def test_auswahlfeld_readonly_bleibt_hell(self):
        # Peter 18.11.2026: „Mail-Programm“ in „Mails importieren“ war mit Fokus dunkelblau (clam: #4a6984)
        s = ttk.Style(self.root)
        f = ui_theme.FARBEN
        self.assertEqual(s.lookup("TCombobox", "fieldbackground", ("readonly", "focus")), f["flaeche"])
        self.assertEqual(s.lookup("TCombobox", "fieldbackground", ("readonly",)), f["flaeche"])
        self.assertEqual(s.lookup("TCombobox", "foreground", ("readonly", "focus")), f["text"])
        self.assertEqual(s.lookup("TCombobox", "bordercolor", ("focus",)), f["akzent"])

    def test_theme_clam_und_zeilenhoehe(self):
        s = ttk.Style(self.root)
        self.assertEqual(s.theme_use(), "clam")
        self.assertGreaterEqual(int(s.lookup("Treeview", "rowheight")), 20)

    def test_reiter_der_einstellungen_passen_ins_fenster(self):
        # Peter 17.11.2026: mit 12 px Polster schnitt Tk die Titel der 8 Reiter ab („Allgemeir“, „KI-Serve“)
        import tkinter.font as tkfont
        from ui_utils import UIUtils
        titel = ["Allgemein", "Dokumentenliste", "Eigenschaften", "Vorschau", "Suche & Volltext", "KI-Server",
                 "Vollautomatik", "Experten"]          # wie settings_editor._reiter(...)
        polster = ttk.Style(self.root).lookup("TNotebook.Tab", "padding")
        links_rechts = int(str(polster).split()[0])
        schrift = tkfont.nametofont("TkDefaultFont", root=self.root)
        bedarf = sum(schrift.measure(t) + 2 * links_rechts + 4 for t in titel)   # 4 px Reiterrahmen
        platz = UIUtils.px(self.root, 730) - 2 * 12                              # Fensterbreite minus Innenrand
        self.assertLessEqual(bedarf, platz)

    def test_auswahl_ohne_nicht_ausgewaehlt_eintraege(self):
        # Ein "!selected"-Eintrag in der Map überdeckte wieder die Schriftfarben der Zeilen-Tags (Tk 8.6.9)
        for option in ("foreground", "background"):
            for eintrag in ttk.Style(self.root).map("Treeview", query_opt=option):
                self.assertNotIn("!selected", eintrag[:-1])


if __name__ == "__main__":
    unittest.main()
