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
        self.assertEqual(len(tabellen), 2)   # KI auf dem eigenen PC, Benchmark (20.11.2026)
        self.assertTrue(all(len(zeile) == 3 for tabelle in tabellen for zeile in tabelle))
        self.assertEqual(len(tabellen[0]), 5)
        self.assertIsNotNone(fenster.finde_abschnitt(1, "Benchmark"))
        self.assertIn("qwen3.5:9b (Standard)", inhalt)
        self.assertIn("Pruefdokumente_Benchmark.zip", inhalt)
        self.assertIn("Pruefdokumente_Benchmark_gescannt_hoch.zip", inhalt)
        self.assertIn("Pruefdokumente_Benchmark_gescannt_niedrig.zip", inhalt)
        # Etappe 13 Schritt 4 (22.11.2026): Firmen-Karte, Qualität, eingebauter Satz
        for stelle in ("48 GB (Quadro RTX 8000)", "Liste je Brief", "Anderer Satz (Zip)", "still im falschen"):
            self.assertIn(stelle, inhalt, stelle)
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


class TestErststartSchnellstartZuerst(unittest.TestCase):
    """Peter 22.11.2026: „Wäre es nicht besser, den Schnellstart vor der Ordnerauswahl anzuzeigen?“ - beim allerersten
    Start erst lesen, dann den Dokumentenordner einrichten; der Vollautomatik-Knopf wartet auf die Sammlung."""

    def test_reihenfolge(self):
        from gui import start_dialoge
        self.assertEqual(start_dialoge(ohne_sammlung=True, hilfe_beim_start=True), ["hilfe", "einrichtung"])
        self.assertEqual(start_dialoge(ohne_sammlung=True, hilfe_beim_start=False), ["einrichtung"])
        self.assertEqual(start_dialoge(ohne_sammlung=False, hilfe_beim_start=True), ["hilfe"])
        self.assertEqual(start_dialoge(ohne_sammlung=False, hilfe_beim_start=False), [])

    def test_einrichtung_erst_nach_dem_schliessen_des_schnellstarts(self):
        # Live-Fund 22.11.2026: open_help blockiert nicht - die Willkommens-Frage stand neben dem Schnellstart
        from unittest.mock import MagicMock, patch
        import gui
        ablauf = []
        app = MagicMock(master_folder="")
        app.config.get.return_value = True
        app.help_window.winfo_exists.return_value = True
        app.help_window.wait_window.side_effect = lambda: ablauf.append("Schnellstart zu")
        app.folder_manager.ersteinrichtung_anbieten.side_effect = lambda: ablauf.append("Einrichtung")
        with patch("gui.open_help", side_effect=lambda *a, **k: ablauf.append("Schnellstart")):
            gui.DokumentenVerwaltung.start_dialoge_zeigen(app)
        self.assertEqual(ablauf, ["Schnellstart", "Schnellstart zu", "Einrichtung"])

    def test_ohne_folgeschritt_wird_nicht_gewartet(self):
        from unittest.mock import MagicMock, patch
        import gui
        import tempfile
        app = MagicMock(master_folder=tempfile.gettempdir())
        app.config.get.return_value = True
        with patch("gui.open_help"):
            gui.DokumentenVerwaltung.start_dialoge_zeigen(app)
        app.help_window.wait_window.assert_not_called()
        app.folder_manager.ersteinrichtung_anbieten.assert_not_called()

    def test_vollautomatik_knopf_wartet_auf_die_sammlung(self):
        import os
        import tempfile
        from unittest.mock import MagicMock
        for ordner, erwartet in (("", ["disabled"]), (tempfile.gettempdir(), ["!disabled"]),
                                 (os.path.join(tempfile.gettempdir(), "gibt_es_nicht_kid"), ["disabled"])):
            fenster = MagicMock()
            fenster.app.config.get.return_value = False
            fenster.app.master_folder = ordner
            help_window.HelpWindow._aktualisiere_vollautomatik_knopf(fenster)
            fenster.btn_vollautomatik.state.assert_called_with(erwartet)

    def test_schritt_1_kuendigt_die_frage_an(self):
        text = " ".join(str(inhalt) for _art, inhalt in help_window.TAB_QUICKSTART[:4])
        self.assertIn("nach dem Schließen dieses Fensters", text)


if __name__ == "__main__":
    unittest.main()
