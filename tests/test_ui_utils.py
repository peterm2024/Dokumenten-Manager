import unittest
from unittest.mock import MagicMock, patch

from ui_utils import ProgressDialog, UIUtils


class TestFormatDuration(unittest.TestCase):
    """Reine Formatierungslogik der Restzeit-Schätzung in ProgressDialog.update_progress - kein Tk-Fenster nötig (@staticmethod)."""

    def test_unter_einer_minute(self):
        self.assertEqual(ProgressDialog._format_duration(45), "45 Sek.")

    def test_minuten_und_sekunden(self):
        self.assertEqual(ProgressDialog._format_duration(125), "2 Min. 5 Sek.")

    def test_volle_stunde(self):
        self.assertEqual(ProgressDialog._format_duration(3661), "1 Std. 1 Min.")

    def test_null_sekunden(self):
        self.assertEqual(ProgressDialog._format_duration(0), "0 Sek.")



class TestSkalierung(unittest.TestCase):
    """Umrechnung fester Pixelmasse auf die Bildschirm-Skalierung (FALLSTRICKE #42)."""

    @staticmethod
    def _widget(dpi):
        widget = MagicMock()
        widget.winfo_fpixels.return_value = dpi
        return widget

    def test_hundert_prozent(self):
        self.assertAlmostEqual(UIUtils.skalierung(self._widget(96.0)), 1.0)
        self.assertEqual(UIUtils.px(self._widget(96.0), 330), 330)

    def test_125_prozent_wie_bei_den_eltern(self):
        self.assertAlmostEqual(UIUtils.skalierung(self._widget(120.0)), 1.25)
        self.assertEqual(UIUtils.px(self._widget(120.0), 330), 412)

    def test_nie_kleiner_als_hundert_prozent(self):
        """Verkleinern wuerde Texte abschneiden - nach unten wird nicht skaliert."""
        self.assertEqual(UIUtils.skalierung(self._widget(72.0)), 1.0)

    def test_fehler_faellt_auf_hundert_prozent_zurueck(self):
        widget = MagicMock()
        widget.winfo_fpixels.side_effect = RuntimeError("kein Fenster")
        self.assertEqual(UIUtils.px(widget, 100), 100)


class TestSchriftfaktor(unittest.TestCase):
    """
    Windows-Textgröße (Barrierefreiheit) vergrößert nur die Systemschrift, nicht die
    Auflösung - der Tester-PC fährt 125 % Skalierung UND 125 % Textgröße (FALLSTRICKE #69).
    """

    @staticmethod
    def _widget(dpi):
        widget = MagicMock()
        widget.winfo_fpixels.return_value = dpi
        return widget

    def _mit_schrift(self, groesse):
        font = MagicMock()
        font.actual.return_value = groesse
        return patch("ui_utils.tkfont.nametofont", return_value=font)

    def test_standardschrift_neun_punkt_ist_faktor_eins(self):
        with self._mit_schrift(9), patch("ui_utils.sys.platform", "win32"):
            self.assertEqual(UIUtils.schriftgroesse(self._widget(96.0)), 9)
            self.assertEqual(UIUtils.schriftfaktor(self._widget(96.0)), 1.0)

    def test_textgroesse_125_prozent_wie_bei_den_eltern(self):
        """9 pt -> 11 pt; zusammen mit 125 % Auflösung wächst jedes feste Maß um gut die Hälfte."""
        with self._mit_schrift(11), patch("ui_utils.sys.platform", "win32"):
            self.assertAlmostEqual(UIUtils.schriftfaktor(self._widget(120.0)), 11 / 9)
            self.assertAlmostEqual(UIUtils.skalierung(self._widget(120.0)), 1.25 * 11 / 9)
            self.assertEqual(UIUtils.px(self._widget(120.0), 600), 917)
            self.assertEqual(UIUtils.schriftgroesse(self._widget(120.0), 1), 12)

    def test_kleinere_schrift_verkleinert_nicht(self):
        with self._mit_schrift(8), patch("ui_utils.sys.platform", "win32"):
            self.assertEqual(UIUtils.schriftfaktor(self._widget(96.0)), 1.0)

    def test_pixelangabe_wird_in_punkt_umgerechnet(self):
        """Negative Tk-Schriftgrößen sind Pixel: -15 px bei 96 dpi = 11 pt."""
        with self._mit_schrift(-15), patch("ui_utils.sys.platform", "win32"):
            self.assertEqual(UIUtils.schriftgroesse(self._widget(96.0)), 11)

    def test_nur_unter_windows(self):
        with self._mit_schrift(11), patch("ui_utils.sys.platform", "linux"):
            self.assertEqual(UIUtils.schriftfaktor(self._widget(96.0)), 1.0)
            self.assertAlmostEqual(UIUtils.skalierung(self._widget(120.0)), 1.25)

    def test_ohne_tk_faellt_auf_neun_punkt_zurueck(self):
        with patch("ui_utils.tkfont.nametofont", side_effect=RuntimeError("kein Tk")):
            self.assertEqual(UIUtils.schriftgroesse(None), 9)
            self.assertEqual(UIUtils.schriftfaktor(None), 1.0)


class TestSichereFenstergeometrie(unittest.TestCase):
    """Nutzerfund 06.09.2026: App startete bei '+-4028+-921' unsichtbar im Nirgendwo."""

    def test_position_im_nirgendwo_wird_verworfen_groesse_bleibt(self):
        self.assertEqual(
            UIUtils.sichere_fenstergeometrie("1440x1237+-4028+-921", punkt_pruefer=lambda x, y: False),
            "1440x1237")

    def test_sichtbare_position_bleibt_unangetastet(self):
        self.assertEqual(
            UIUtils.sichere_fenstergeometrie("1400x900+100+50", punkt_pruefer=lambda x, y: True),
            "1400x900+100+50")

    def test_teilweise_sichtbar_reicht(self):
        """Ragt nur die rechte Ecke der Titelleiste auf einen Monitor, ist sie greifbar."""
        rechts_sichtbar = lambda x, y: x > 0
        self.assertEqual(
            UIUtils.sichere_fenstergeometrie("800x600+-700+10", punkt_pruefer=rechts_sichtbar),
            "800x600+-700+10")

    def test_unbekanntes_format_bleibt_unveraendert(self):
        for geometry in ("1400x900", "", None, "kaputt"):
            self.assertEqual(
                UIUtils.sichere_fenstergeometrie(geometry, punkt_pruefer=lambda x, y: False),
                geometry)

    def test_titelleiste_zaehlt_nicht_die_fenstermitte(self):
        """Geprüft wird knapp unter der OBERkante - ein tief hineinragendes Fenster, dessen Titelleiste über allen Monitoren liegt, gilt als unsichtbar."""
        aufrufe = []
        def pruefer(x, y):
            aufrufe.append((x, y))
            return False
        UIUtils.sichere_fenstergeometrie("1000x800+0+-500", punkt_pruefer=pruefer)
        self.assertTrue(all(y == -488 for _x, y in aufrufe), aufrufe)


class TestBegrenzungMitRahmen(unittest.TestCase):
    """Release-Check T0.16: unten geöffnete Fenster ragten um die Titelleiste über den Rand."""

    def _fenster(self):
        fenster = MagicMock()
        fenster.winfo_pointerx.return_value = 500
        fenster.winfo_pointery.return_value = 1400
        return fenster

    def test_aussenkante_bleibt_auf_dem_monitor(self):
        with patch.object(UIUtils, "monitor_bounds_at", return_value=(0, 0, 2560, 1440)), \
                patch.object(UIUtils, "fensterrahmen", return_value=(16, 39)):
            x, y = UIUtils._begrenzt_auf_monitor(self._fenster(), 520, 1420, 1000, 900)
        self.assertEqual(y, 1440 - 900 - 39)     # Titelleiste + Rahmen passen noch drauf
        self.assertEqual(x, 520)

    def test_zu_grosses_fenster_wird_samt_rahmen_gekappt(self):
        fenster = self._fenster()
        with patch.object(UIUtils, "monitor_bounds_at", return_value=(0, 0, 1920, 1040)), \
                patch.object(UIUtils, "fensterrahmen", return_value=(16, 39)), \
                patch.object(UIUtils, "app_hat_fokus", return_value=True):
            UIUtils.position_near_mouse(fenster, 3000, 2000)
        self.assertEqual(fenster.geometry.call_args[0][0], "1904x1001+0+0")

    def test_bezug_bestimmt_den_monitor_nicht_die_maus(self):
        """Ein wachsendes Fenster bleibt auf seinem Monitor, auch wenn die Maus auf einem anderen steht."""
        def monitore(_f, x, y):
            return (-2560, 0, 0, 1440) if x < 0 else (0, 0, 2560, 1440)
        fenster = self._fenster()
        fenster.winfo_pointerx.return_value = -1000             # Maus links, Fenster rechts
        with patch.object(UIUtils, "monitor_bounds_at", side_effect=monitore), \
                patch.object(UIUtils, "fensterrahmen", return_value=(16, 39)):
            x, _y = UIUtils._begrenzt_auf_monitor(fenster, 300, 100, 410, 500, bezug=(500, 120))
        self.assertEqual(x, 300)


class TestAnkerNachFokus(unittest.TestCase):
    """Peter 02.11.2026: neue Fenster nur dann an der Maus, wenn man gerade in KID arbeitet."""

    def _fenster(self, haupt_zustand="normal"):
        fenster = MagicMock()
        fenster.winfo_pointerx.return_value = -2900               # Maus in einem anderen Programm, linker Monitor
        fenster.winfo_pointery.return_value = 300
        haupt = fenster._root.return_value
        haupt.state.return_value = haupt_zustand
        haupt.geometry.return_value = "1000x700+358+260"      # maximiert: Tk meldet die Lage VOR dem Maximieren
        haupt.winfo_rootx.return_value, haupt.winfo_rooty.return_value = 100, 50
        haupt.winfo_width.return_value, haupt.winfo_height.return_value = 1400, 900
        return fenster

    def test_mit_fokus_am_mauszeiger(self):
        with patch.object(UIUtils, "app_hat_fokus", return_value=True):
            self.assertEqual(UIUtils._anker(self._fenster(), 400, 300, 20), (-2880, 320, (-2900, 300)))

    def test_ohne_fokus_mittig_ueber_kid(self):
        with patch.object(UIUtils, "app_hat_fokus", return_value=False):
            self.assertEqual(UIUtils._anker(self._fenster(), 400, 300, 20), (600, 350, (800, 500)))

    def test_ohne_fokus_und_kid_minimiert_am_mauszeiger(self):
        with patch.object(UIUtils, "app_hat_fokus", return_value=False):
            self.assertEqual(UIUtils._anker(self._fenster("iconic"), 400, 300, 20)[:2], (-2880, 320))

    def test_ueber_kid_auch_mit_fokus(self):
        """Fenster, die KID von sich aus öffnet (Statusfenster beim Start): immer über dem Hauptfenster."""
        with patch.object(UIUtils, "app_hat_fokus", return_value=True):
            self.assertEqual(UIUtils._anker(self._fenster(), 400, 300, 20, ueber_kid=True)[:2], (600, 350))

    def test_ohne_fokus_und_kid_noch_nicht_gezeichnet_am_mauszeiger(self):
        """Vor dem ersten Zeichnen meldet Tk „1x1“ - dessen „Mitte“ wäre KIDs obere linke Ecke."""
        fenster = self._fenster()
        fenster._root.return_value.winfo_width.return_value = 1
        with patch.object(UIUtils, "app_hat_fokus", return_value=False):
            self.assertEqual(UIUtils._anker(fenster, 400, 300, 20)[:2], (-2880, 320))

    def test_position_ohne_fokus_landet_auf_dem_kid_monitor(self):
        fenster = self._fenster()
        gefragt = []

        def monitor(_f, x, y):
            gefragt.append((x, y))
            return (0, 0, 2560, 1400)
        with patch.object(UIUtils, "app_hat_fokus", return_value=False), \
                patch.object(UIUtils, "monitor_bounds_at", side_effect=monitor), \
                patch.object(UIUtils, "fensterrahmen", return_value=(16, 39)):
            UIUtils.position_near_mouse(fenster, 400, 300)
        self.assertEqual(fenster.geometry.call_args[0][0], "400x300+600+350")
        self.assertTrue(all(p == (800, 500) for p in gefragt), gefragt)

    def test_fokus_abfrage_liefert_wahrheitswert(self):
        self.assertIn(UIUtils.app_hat_fokus(), (True, False))

    def test_rahmen_hat_vernuenftige_groesse(self):
        breite, hoehe = UIUtils.fensterrahmen()
        self.assertTrue(0 <= breite <= 60 and 20 <= hoehe <= 100, (breite, hoehe))


class TestParseProzent(unittest.TestCase):
    def test_werte_und_leer(self):
        from ui_utils import UIUtils
        self.assertEqual(UIUtils.parse_prozent("92 %"), 92)
        self.assertEqual(UIUtils.parse_prozent("100 %"), 100)
        self.assertEqual(UIUtils.parse_prozent("—"), -1)
        self.assertEqual(UIUtils.parse_prozent(""), -1)
        self.assertEqual(UIUtils.parse_prozent(None), -1)


class TestTooltip(unittest.TestCase):
    """ui_utils.Tooltip (13.09.2026): erscheint nach Verweilen, Text auch als Funktion, verschwindet beim Verlassen."""

    def setUp(self):
        import tkinter as tk
        self.tk = tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.knopf = tk.Label(self.root, text="x")
        self.knopf.pack()

    def tearDown(self):
        self.root.destroy()

    def test_zeigen_und_verstecken(self):
        from ui_utils import Tooltip
        tip = Tooltip(self.knopf, "Hinweis", verzoegerung_ms=1)
        self.assertFalse(tip.sichtbar())
        tip.zeige()
        self.assertTrue(tip.sichtbar())
        tip.verstecke()
        self.assertFalse(tip.sichtbar())

    def test_text_als_funktion(self):
        from ui_utils import Tooltip
        stand = {"t": "eins"}
        tip = Tooltip(self.knopf, lambda: stand["t"])
        self.assertEqual(tip.text(), "eins")
        stand["t"] = "zwei"
        self.assertEqual(tip.text(), "zwei")

    def test_leerer_text_zeigt_nichts(self):
        from ui_utils import Tooltip
        tip = Tooltip(self.knopf, "")
        tip.zeige()
        self.assertFalse(tip.sichtbar())


class TestBaumSpringen(unittest.TestCase):
    """Pos1/Ende im Ordner- und Tag-Baum (Peter 28.10.2026): erster / letzter SICHTBARER Eintrag."""

    def setUp(self):
        import tkinter as tk
        from tkinter import ttk
        self.root = tk.Tk()
        self.root.withdraw()
        self.baum = ttk.Treeview(self.root)
        a = self.baum.insert("", "end", text="A", open=True)
        self.baum.insert(a, "end", text="A1")
        b = self.baum.insert("", "end", text="B", open=True)
        self.b2 = self.baum.insert(b, "end", text="B2")
        self.zu = self.baum.insert(self.b2, "end", text="B2a")   # B2 ist zugeklappt
        self.a = a

    def tearDown(self):
        self.root.destroy()

    def test_ende_letzter_sichtbarer_eintrag(self):
        self.assertEqual(UIUtils.baum_springen(self.baum, ende=True), "break")
        self.assertEqual(self.baum.selection(), (self.b2,))
        self.assertEqual(self.baum.focus(), self.b2)

    def test_pos1_erster_eintrag(self):
        UIUtils.baum_springen(self.baum, ende=False)
        self.assertEqual(self.baum.selection(), (self.a,))

    def test_leerer_baum(self):
        self.baum.delete(*self.baum.get_children(""))
        self.assertEqual(UIUtils.baum_springen(self.baum, ende=True), "break")
        self.assertIsNone(UIUtils.letzter_sichtbarer(self.baum))


if __name__ == "__main__":
    unittest.main()
