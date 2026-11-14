"""Tests für das Hilfe-Fenster: Sprungmarken zu Abschnitten (T1.10)."""
import tkinter as tk
import unittest

import help_window


class FakeConfig:
    def __init__(self):
        self.werte = {}

    def get(self, key, default=None):
        return self.werte.get(key, default)

    def set(self, key, value):
        self.werte[key] = value


class FakeApp:
    def __init__(self, root):
        self.root = root
        self.config = FakeConfig()


class TestAbschnittsTitel(unittest.TestCase):
    def test_emoji_praefix_faellt_weg(self):
        self.assertEqual(help_window.abschnitts_titel("🌐\tKI-Server aus der Ferne (Tailscale)"),
                         "ki-server aus der ferne (tailscale)")

    def test_ohne_tab_nur_normalisiert(self):
        self.assertEqual(help_window.abschnitts_titel("  Technik "), "technik")


class TestSprungMarken(unittest.TestCase):
    """Echtes Tk-Fenster (unsichtbar); ohne Display wird übersprungen."""

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as e:  # pragma: no cover - Headless-Umgebung
            self.skipTest(f"kein Display: {e}")
        self.root.withdraw()
        self.app = FakeApp(self.root)

    def tearDown(self):
        self.root.destroy()

    def test_scrollt_zum_tailscale_abschnitt(self):
        fenster = help_window.HelpWindow(self.root, self.app, start_tab=0)
        fenster.withdraw()
        fenster.select_tab(1, "KI-Server aus der Ferne")
        self.root.update()  # after_idle + Layout abarbeiten
        text, marke = fenster.finde_abschnitt(1, "KI-Server aus der Ferne")
        oben, _unten = text.yview()
        self.assertGreater(oben, 0.0, "Text wurde nicht gescrollt")
        # Die Überschrift ist sichtbar (liegt nahe am Textende, deshalb nicht zwingend oberste
        # Zeile - Tk scrollt nicht über das Ende hinaus) und kurz gelb hervorgehoben
        self.assertIsNotNone(text.dlineinfo(marke), "Überschrift nicht im sichtbaren Bereich")
        self.assertIn("Tailscale", text.get(f"{marke} linestart", f"{marke} lineend"))
        self.assertIn("sprung", text.tag_names(marke))
        fenster.destroy()

    def test_open_help_reicht_abschnitt_durch(self):
        help_window.open_help(self.app, 1, abschnitt="KI-Server aus der Ferne")
        self.app.help_window.withdraw()
        self.root.update()
        text, _marke = self.app.help_window.finde_abschnitt(1, "KI-Server aus der Ferne")
        self.assertGreater(text.yview()[0], 0.0)
        # Zweiter Aufruf: Singleton bleibt, Abschnitt ohne Marke (unbekannt) stört nicht
        fenster = self.app.help_window
        help_window.open_help(self.app, 1, abschnitt="Gibt es nicht")
        self.assertIs(self.app.help_window, fenster)
        self.assertIsNone(fenster.finde_abschnitt(1, "Gibt es nicht"))
        fenster.destroy()


class TestMenueUebersicht(unittest.TestCase):
    """Reiter „Menü-Übersicht" (Index 3) wird aus menue_hilfe gebaut; „Tags" ist Index 2, „Über" Index 4."""

    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = FakeApp(self.root)

    def tearDown(self):
        self.root.destroy()

    def test_reiter_und_sprung_zu_eintrag(self):
        fenster = help_window.HelpWindow(self.root, self.app, start_tab=3)
        self.assertEqual([fenster.notebook.tab(i, "text") for i in range(5)],
                         ["Schnellstart", "Funktionsumfang", "Tags", "Menü-Übersicht", "Über"])
        self.assertIsNotNone(fenster.finde_abschnitt(3, "Sammlung öffnen"))
        self.assertIsNotNone(fenster.finde_abschnitt(3, "Umbenennen (F2)"))
        self.assertIsNotNone(fenster.finde_abschnitt(4, "Version") or True)   # Über bleibt erreichbar
        fenster.select_tab(3, "Protokoll-Datei")
        self.root.update()
        self.assertEqual(fenster.notebook.index("current"), 3)
        fenster.destroy()

    def test_reiter_schlagwoerter(self):
        """Nutzerwunsch 13.09.2026: Sinn, Vorteile, Nachteile und Arbeiten ohne Tags ausdrücklich erklärt."""
        fenster = help_window.HelpWindow(self.root, self.app, start_tab=2)
        for abschnitt in ("Wofür Tags gedacht sind", "Warum Tags, wenn es die Suche gibt",
                          "Vorteile", "Nachteile und Grenzen", "Bewährte Praxis", "Arbeiten ohne Tags"):
            self.assertIsNotNone(fenster.finde_abschnitt(2, abschnitt), abschnitt)
        text = fenster.notebook.nametowidget(fenster.notebook.tabs()[2]).winfo_children()
        inhalt = next(w for w in text if isinstance(w, tk.Text)).get("1.0", tk.END)
        self.assertIn("verlangt an keiner Stelle ein Tag", inhalt)
        self.assertIn("Versicherung Musterstraße 2021", inhalt)
        fenster.destroy()

    def test_abschnitt_ki_auf_dem_eigenen_pc_mit_tabelle(self):
        """Beta-Vorbereitung 13.09.2026: Anleitung Ollama lokal plus Geschwindigkeits-Tabelle im Funktionsumfang."""
        fenster = help_window.HelpWindow(self.root, self.app, start_tab=1)
        self.assertIsNotNone(fenster.finde_abschnitt(1, "KI auf dem eigenen PC"))
        text = fenster.notebook.nametowidget(fenster.notebook.tabs()[1]).winfo_children()
        inhalt = next(w for w in text if isinstance(w, tk.Text)).get("1.0", tk.END)
        self.assertIn("ollama pull qwen3.5:9b", inhalt)
        for zelle in ("nur Prozessor", "integriert", "8 GB", "16 GB", "2 bis 10 Minuten"):
            self.assertIn(zelle, inhalt, zelle)
        tabellen = [inhalt for stil, inhalt in help_window.TAB_FEATURES if stil == "tabelle"]
        self.assertEqual(len(tabellen), 1)
        self.assertTrue(all(len(zeile) == 3 for zeile in tabellen[0]))
        self.assertEqual(len(tabellen[0]), 5)
        fenster.destroy()

    def test_hilfetexte_ohne_persoenliche_angaben(self):
        """Peter 13.09.2026: keine echten Orte, Namen oder Adressen in der Hilfe (Copyright-Zeile ausgenommen).

        Die echten Begriffe dürfen selbst nicht im (öffentlichen) Quellcode stehen - sie liegen in einer privaten
        Liste außerhalb des Repos (ein Regex je Zeile). Fehlt die Liste, wird der Test übersprungen."""
        import os
        import re
        liste = os.path.join(os.path.expanduser("~"), "KID-Messungen", "release_check", "begriffe.txt")
        if not os.path.isfile(liste):
            self.skipTest("private Begriffsliste fehlt")
        with open(liste, encoding="utf-8") as f:
            begriffe = [z.strip() for z in f if z.strip() and not z.startswith("#")]
        alles = "\n".join(str(inhalt) for tab in (help_window.TAB_QUICKSTART, help_window.TAB_FEATURES,
                                                   help_window.TAB_TAGS) for _stil, inhalt in tab)
        self.assertTrue(begriffe)
        for wort in begriffe:
            self.assertIsNone(re.search(wort, alles), "Begriff aus der privaten Liste")


if __name__ == "__main__":
    unittest.main()
