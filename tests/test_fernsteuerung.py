"""Tests für die reinen Teile der Fernsteuerung (fernsteuerung.py, Entwickler-Werkzeug)."""

import os
import unittest

import fernsteuerung as fs


class TestTasten(unittest.TestCase):
    def test_kombinationen(self):
        self.assertEqual(fs.zerlege_tasten("ctrl+a"), [0x11, ord("A")])
        self.assertEqual(fs.zerlege_tasten("Strg + Shift + 5"), [0x11, 0x10, ord("5")])
        self.assertEqual(fs.zerlege_tasten("f2"), [0x71])
        self.assertEqual(fs.zerlege_tasten("alt+down"), [0x12, 0x28])

    def test_unbekanntes_wird_abgelehnt(self):
        for falsch in ("ctrl+", "hyper+a", "ab"):
            with self.assertRaises(ValueError):
                fs.zerlege_tasten(falsch)


class TestSicherheit(unittest.TestCase):
    def test_nur_testsammlung(self):
        heim = os.path.expanduser("~")
        self.assertTrue(fs.ist_testsammlung(os.path.join(heim, "KID-Test")))
        self.assertTrue(fs.ist_testsammlung((heim + "\\kid-test\\").lower()))
        self.assertFalse(fs.ist_testsammlung(os.path.join(heim, "Documents", "KID")))
        self.assertFalse(fs.ist_testsammlung(os.path.join(heim, "KID-Test-Daten")))
        self.assertFalse(fs.ist_testsammlung(""))

    def test_ki_einstellungen_immer_frisch(self):
        # 03.11.2026: die einmal angelegte Kopie weckte mit der alten VM-MAC und las mit einem anderen Modell
        echt = {"ki_wol_mac": "AA:BB:CC:11:22:33", "ollama_model": "neu:9b", "master_folder": "C:/Echt",
                "window_geometry": "echt"}
        kopie = {"ki_wol_mac": "BC:24:11:00:00:01", "ollama_model": "alt:7b", "window_geometry": "test"}
        e = fs.einstellungen_ableiten(echt, kopie)
        self.assertEqual((e["ki_wol_mac"], e["ollama_model"], e["window_geometry"]),
                         ("AA:BB:CC:11:22:33", "neu:9b", "test"))
        self.assertTrue(fs.ist_testsammlung(e["master_folder"]))
        self.assertFalse(e["auto_pilot_enabled"])
        self.assertEqual(fs.einstellungen_ableiten(echt, None)["window_geometry"], "echt")   # erster Start

    def test_kein_start_wenn_die_testsammlung_schon_offen_ist(self):
        """Release-Check v0.9.26 (07.11.2026): Die Fernsteuerung umging die Sammlungssperre aus main.py, kurz liefen
        Peters EXE und das ferngesteuerte KID zugleich auf KID-Test. Jetzt bricht sie ab, bevor sie etwas schreibt."""
        from unittest.mock import patch
        # Ohne die Sperre liefe _starte weiter bis zum echten Fenster - darum scheitert schon der erste Schritt danach
        stopp = AssertionError("_starte lief an der Sperre vorbei")
        with patch("einzelstart.belege", return_value=False) as belege, \
                patch("fernsteuerung.os.makedirs", side_effect=stopp) as anlegen, \
                patch("fernsteuerung.einstellungen_ableiten", side_effect=stopp), \
                patch("fernsteuerung.os.chdir", side_effect=stopp) as wechseln:
            with self.assertRaises(SystemExit) as abbruch:
                fs._starte("token")
        belege.assert_called_once_with(fs.TESTORDNER)
        anlegen.assert_not_called()
        wechseln.assert_not_called()
        self.assertIn("schon offen", str(abbruch.exception))

    def test_start_klaut_keinen_fokus(self):
        """Peter 08.11.2026: Das frisch gestartete KID nahm ihm den Fokus, danach galt KID als aktiv und das nächste
        Werkzeugfenster öffnete sich an seinem Mauszeiger. Hatte vorher ein anderes Programm den Fokus, bekommt es ihn
        zurück - aber nur, wenn KID ihn wirklich genommen hat."""
        import os
        from unittest.mock import call, patch

        class Wurzel:
            def after(self, _ms, fn, *args):
                fn(*args)

            def winfo_viewable(self):
                return True

        self.assertTrue(fs.fokus_zurueckgeben(4711, os.getpid(), os.getpid()))
        self.assertFalse(fs.fokus_zurueckgeben(4711, 4711, os.getpid()))      # nichts genommen
        self.assertFalse(fs.fokus_zurueckgeben(os.getpid(), os.getpid(), os.getpid()))
        self.assertFalse(fs.fokus_zurueckgeben(0, os.getpid(), os.getpid()))  # vorher keins - nicht zurück
        import ctypes
        for jetzt, zurueck in ((os.getpid(), True), (4711, False)):
            with patch("fernsteuerung._vordergrund", return_value=(9, jetzt)), \
                    patch.object(ctypes.windll.user32, "SetForegroundWindow") as setzen:
                fs._fokus_nicht_klauen(Wurzel(), (7, 4711))         # 7 = Fenster, das vorher den Fokus hatte
            self.assertEqual(setzen.call_args_list, [call(7)] if zurueck else [])

    def test_mausbewegung_erkennen(self):
        self.assertFalse(fs.maus_bewegt(None, (5, 5)))
        self.assertFalse(fs.maus_bewegt((100, 100), (102, 99)))   # Zittern innerhalb der Toleranz
        self.assertTrue(fs.maus_bewegt((100, 100), (110, 100)))


class TestGrosseSchrift(unittest.TestCase):
    """T0.16: Tester-PC (125 % + Textgröße 125 %) nachbilden, weil Windows es der App nicht meldet."""

    def test_skalierung_wie_am_eltern_pc(self):
        import tkinter as tk
        import tkinter.font as tkfont
        from ui_utils import UIUtils
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("kein Tk verfügbar")
        try:
            root.withdraw()
            fs.simuliere_grosse_schrift(root)
            self.assertAlmostEqual(root.winfo_fpixels("1i"), 120, delta=0.5)
            self.assertEqual(tkfont.nametofont("TkDefaultFont", root=root).cget("size"), 11)
            # DPI-Faktor 1,25 × Schriftfaktor 11/9 - wie FALLSTRICKE #69 es am Tester-PC misst
            self.assertAlmostEqual(UIUtils.skalierung(root), 1.25 * 11 / 9, delta=0.01)
        finally:
            root.destroy()


class TestKnopfZeilen(unittest.TestCase):
    def test_umbruch_wenn_zu_breit(self):
        self.assertEqual(fs.knopf_zeilen([100, 100, 100], 396), [[0, 1, 2]])
        self.assertEqual(fs.knopf_zeilen([150, 150, 150, 80], 396), [[0, 1], [2, 3]])

    def test_ueberbreiter_knopf_bekommt_eigene_zeile(self):
        self.assertEqual(fs.knopf_zeilen([500, 50], 396), [[0], [1]])


class TestHinweisPosition(unittest.TestCase):
    MONITOR = (0, 0, 1920, 1040)

    def test_rechts_neben_der_app(self):
        self.assertEqual(fs.hinweis_position((20, 40, 1420, 940), self.MONITOR, 420, 230), (1444, 40))

    def test_links_daneben_wenn_rechts_kein_platz(self):
        self.assertEqual(fs.hinweis_position((480, 40, 1900, 940), self.MONITOR, 420, 230), (36, 40))

    def test_sonst_ecke_unten_rechts(self):
        self.assertEqual(fs.hinweis_position((0, 0, 1920, 1040), self.MONITOR, 420, 230), (1476, 746))

    def test_anderer_monitor_wenn_die_app_den_eigenen_fuellt(self):
        zweiter = (-2560, 0, 0, 1400)
        self.assertEqual(fs.hinweis_position((0, 0, 1920, 1040), self.MONITOR, 420, 230, andere=[zweiter]),
                         (-444, 1106))
        zu_klein = (-300, 0, 0, 200)
        self.assertEqual(fs.hinweis_position((0, 0, 1920, 1040), self.MONITOR, 420, 230, andere=[zu_klein]),
                         (1476, 746))

    def test_minimierte_app_landet_nicht_ausserhalb(self):
        # Windows meldet ein minimiertes Fenster bei -32000 (Nutzerfund 25.10.2026)
        self.assertEqual(fs.hinweis_position((-32000, -32000, -31840, -31970), self.MONITOR, 420, 230), (1476, 746))

    def test_negativer_monitor(self):
        # Zweiter Monitor links vom Hauptmonitor (negative Koordinaten)
        self.assertEqual(fs.hinweis_position((-2309, 304, -909, 1204), (-2560, 0, 0, 1400), 420, 230), (-885, 304))


if __name__ == "__main__":
    unittest.main()
