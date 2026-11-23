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


class TestHauptfensterMindestgroesse(unittest.TestCase):
    """Peter 22.11.2026: Das Hauptfenster ließ sich auf 200x161 ziehen; die Größe kam nach dem Maximieren wieder."""

    def test_mindestmass_skaliert_mit(self):
        self.assertEqual(UIUtils.hauptfenster_mindestmass(1.0, 1920, 1080), (960, 640))
        self.assertEqual(UIUtils.hauptfenster_mindestmass(1.25, 1920, 1080), (1200, 800))

    def test_kleiner_bildschirm_deckelt(self):
        self.assertEqual(UIUtils.hauptfenster_mindestmass(1.25, 1366, 768), (1092, 614))

    def test_gespeicherte_zwerggroesse_wird_vergroessert_position_bleibt(self):
        self.assertEqual(UIUtils.geometrie_mindestens("200x161+-1618+320", 960, 640), "960x640+-1618+320")
        self.assertEqual(UIUtils.geometrie_mindestens("1400x500", 960, 640), "1400x640")
        self.assertEqual(UIUtils.geometrie_mindestens("1400x900+10+10", 960, 640), "1400x900+10+10")

    def test_unbekanntes_format_bleibt(self):
        for geometry in ("", None, "kaputt"):
            self.assertEqual(UIUtils.geometrie_mindestens(geometry, 960, 640), geometry)

    def test_hauptfenster_setzt_beides(self):
        import os
        quelle = open(os.path.join(os.path.dirname(__file__), "..", "src", "gui.py"), encoding="utf-8").read()
        self.assertIn("self.root.minsize(min_b, min_h)", quelle)
        self.assertIn("UIUtils.geometrie_mindestens(self.config.get(\"window_geometry\"", quelle)


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



class _FensterAttrappe:
    """Nur was _maximierbar_halten braucht: bind, state und der Zustand, den Windows meldet."""
    def __init__(self):
        self.bindungen = {}
        self.zustand = "normal"

    def bind(self, folge, funktion, add=None):
        self.bindungen.setdefault(folge, []).append(funktion)

    def state(self, neu=None):
        if neu is None:
            return self.zustand
        self.zustand = neu

    def feuere(self, folge, widget=None):
        for f in self.bindungen.get(folge, []):
            f(MagicMock(widget=self if widget is None else widget))


class TestMaximierbarHalten(unittest.TestCase):
    """Peter 21.11.2026 (Probefenster, Punkt 5): transient + Maximieren-Schaltfläche - nach Hauptfenster minimiert und
    zurück baut Tk den Rahmen neu, Schaltfläche UND Maximierung waren weg (FALLSTRICKE #137)."""

    def setUp(self):
        self.fenster = _FensterAttrappe()
        knopf = patch("ui_utils._win_maximieren_knopf")
        self.knopf = knopf.start()
        self.addCleanup(knopf.stop)
        self.maximiert = patch("ui_utils._win_ist_maximiert", side_effect=lambda f: f.zustand == "zoomed").start()
        self.addCleanup(patch.stopall)
        UIUtils._maximierbar_halten(self.fenster)

    def test_jedes_zeigen_setzt_die_schaltflaeche(self):
        self.fenster.feuere("<Map>")
        self.fenster.feuere("<Map>")
        self.assertEqual(self.knopf.call_count, 2)

    def test_maximierung_ueberlebt_den_neuaufbau(self):
        self.fenster.zustand = "zoomed"
        self.fenster.feuere("<Unmap>")
        self.fenster.zustand = "normal"          # so steht das Fenster nach dem Neuaufbau durch Tk da
        self.fenster.feuere("<Map>")
        self.assertEqual(self.fenster.zustand, "zoomed")

    def test_merker_gilt_nur_fuer_ein_verbergen(self):
        """Live gefunden 21.11.2026: wiederhergestellt, dann baut Tk den Rahmen ohne <Unmap> neu (resizable) - das
        Fenster maximierte sich ungefragt wieder."""
        self.fenster.zustand = "zoomed"
        self.fenster.feuere("<Unmap>")
        self.fenster.feuere("<Map>")
        self.fenster.zustand = "normal"          # Nutzer stellt wieder her
        self.fenster.feuere("<Map>")
        self.assertEqual(self.fenster.zustand, "normal")

    def test_nicht_maximiertes_bleibt_normal(self):
        self.fenster.feuere("<Unmap>")
        self.fenster.feuere("<Map>")
        self.assertEqual(self.fenster.zustand, "normal")

    def test_kind_widgets_zaehlen_nicht(self):
        self.fenster.zustand = "zoomed"
        self.fenster.feuere("<Unmap>")
        self.fenster.zustand = "normal"          # Nutzer hat wiederhergestellt ...
        self.fenster.feuere("<Unmap>", widget=object())   # ... dann verschwindet nur eine Tabelle im Fenster
        self.fenster.feuere("<Map>", widget=object())
        self.assertEqual(self.knopf.call_count, 0)
        self.assertEqual(self.fenster.zustand, "normal")

    def test_ohne_maximierbar_keine_bindung(self):
        f = _FensterAttrappe()
        f.transient = MagicMock()
        UIUtils.werkzeugfenster(f, object())
        f.transient.assert_called_once()
        self.assertEqual(f.bindungen, {})


class _Fenster:
    def __init__(self, eingabe=None):
        self.zerstoert, self.vorn, self.gezeigt = False, 0, None

    def winfo_exists(self):
        return not self.zerstoert

    def destroy(self):
        self.zerstoert = True

    def deiconify(self):
        pass

    def lift(self):
        self.vorn += 1

    def focus_set(self):
        pass

    def title(self):
        return "Probe"


class TestEinzelfensterMitEingabe(unittest.TestCase):
    """Fenster-Durchsicht B3 (Peter 21.11.2026): alle Werkzeuge öffnen ihr Fenster über BaseTool.oeffne_fenster ->
    UIUtils.einzelfenster; vorher verwarfen vier Werkzeuge das offene Fenster bei jedem Aufruf (Dateinamen
    aufräumen, Erfassungs-Analyse, Dubletten finden, Gedächtnis) und eins öffnete beliebig viele (Begleitet)."""

    def setUp(self):
        UIUtils._einzelfenster.clear()
        self.addCleanup(UIUtils._einzelfenster.clear)
        hinweis = patch("tkinter.messagebox.showinfo")
        self.hinweis = hinweis.start()
        self.addCleanup(hinweis.stop)

    def test_ohne_eingabe_kommt_das_offene_nach_vorn(self):
        erstes = UIUtils.einzelfenster("x", _Fenster)
        self.assertIs(UIUtils.einzelfenster("x", _Fenster), erstes)
        self.assertEqual(erstes.vorn, 1)
        self.hinweis.assert_not_called()

    def test_einzelner_pfad_wie_liste(self):
        erstes = UIUtils.einzelfenster("x", _Fenster, "C:/a.pdf")
        self.assertIs(UIUtils.einzelfenster("x", _Fenster, ["c:\A.pdf"]), erstes)
        self.hinweis.assert_not_called()

    def test_leere_eingabe_laesst_das_offene_stehen(self):
        erstes = UIUtils.einzelfenster("x", _Fenster, ["a.pdf"])
        self.assertIs(UIUtils.einzelfenster("x", _Fenster, []), erstes)
        self.hinweis.assert_not_called()

    def test_fenster_mit_uebernimm_eingabe_wechselt(self):
        class Wechselnd(_Fenster):
            def uebernimm_eingabe(self, pfade):
                self.gezeigt = pfade
        erstes = UIUtils.einzelfenster("x", Wechselnd, ["a.pdf"])
        self.assertIs(UIUtils.einzelfenster("x", Wechselnd, ["b.pdf"]), erstes)
        self.assertEqual(erstes.gezeigt, ["b.pdf"])
        self.assertIs(UIUtils.einzelfenster("x", Wechselnd, ["b.pdf"]), erstes)   # jetzt gleich: kein Wechsel
        self.hinweis.assert_not_called()

    def test_andere_auswahl_ohne_wechsel_gibt_hinweis(self):
        erstes = UIUtils.einzelfenster("x", _Fenster, ["a.pdf"])
        self.assertIs(UIUtils.einzelfenster("x", _Fenster, ["b.pdf"]), erstes)
        self.assertFalse(erstes.zerstoert)
        self.hinweis.assert_called_once()

    def test_geschlossenes_fenster_wird_neu_gebaut(self):
        erstes = UIUtils.einzelfenster("x", _Fenster)
        erstes.destroy()
        self.assertIsNot(UIUtils.einzelfenster("x", _Fenster), erstes)


class TestTabelleBearbeitbar(unittest.TestCase):
    """B4c (21.11.2026): Doppelklick, Rechtsklick-Menü und F2 rufen in allen Tabellen dieselbe Bearbeiten-Funktion,
    Spalten über ihre ID. Über eine Attrappe statt echtem Treeview."""

    def setUp(self):
        from unittest.mock import MagicMock
        self.tree = MagicMock()
        self.tree.identify_region.return_value = "cell"
        self.tree.identify_row.return_value = "i1"
        self.tree.identify_column.return_value = "#4"
        self.tree.column.side_effect = lambda c, opt: {"#4": "vorschlag"}[c]
        self.tree.selection.return_value = ("i2", "i3")
        self.bearbeitet = []

    def _binde(self, **kw):
        UIUtils.tabelle_bearbeitbar(self.tree, lambda iid, s: self.bearbeitet.append((iid, s)), **kw)
        return {c.args[0]: c.args[1] for c in self.tree.bind.call_args_list}

    def _ereignis(self):
        import types
        return types.SimpleNamespace(x=5, y=5, x_root=50, y_root=50)

    def test_doppelklick_bearbeitet_die_zelle_ueber_ihre_id(self):
        self._binde()["<Double-1>"](self._ereignis())
        self.assertEqual(self.bearbeitet, [("i1", "vorschlag")])

    def test_doppelklick_auf_den_spaltenkopf_bearbeitet_nichts(self):
        self.tree.identify_region.return_value = "heading"
        self._binde()["<Double-1>"](self._ereignis())
        self.assertEqual(self.bearbeitet, [])

    def test_f2_bearbeitet_die_erste_markierte_zeile(self):
        self._binde(f2_spalte="titel")["<F2>"](self._ereignis())
        self.assertEqual(self.bearbeitet, [("i2", "titel")])

    def test_ohne_menue_und_f2_keine_bindung(self):
        self.assertEqual(set(self._binde()), {"<Double-1>"})

    def test_rechtsklick_waehlt_aus_und_zeigt_die_eintraege(self):
        from unittest.mock import patch
        bindungen = self._binde(menue=lambda iid: [("vorschlag", "Bearbeiten…"), ("check", "Haken")])
        with patch("ui_utils.tk.Menu") as menue:
            bindungen["<Button-3>"](self._ereignis())
        self.tree.selection_set.assert_called_once_with("i1")
        eintraege = [c.kwargs for c in menue.return_value.add_command.call_args_list]
        self.assertEqual([e["label"] for e in eintraege], ["Bearbeiten…", "Haken"])
        eintraege[1]["command"]()
        self.assertEqual(self.bearbeitet, [("i1", "check")])

    def test_rechtsklick_ohne_eintraege_zeigt_nichts(self):
        from unittest.mock import patch
        bindungen = self._binde(menue=lambda iid: None)
        with patch("ui_utils.tk.Menu") as menue:
            bindungen["<Button-3>"](self._ereignis())
        menue.assert_not_called()

    def test_einzelklick_in_der_haken_spalte_schaltet_die_angeklickte_zeile(self):
        """Peter 22.11.2026: „Doppelklick Haken ist Mist“ - in Titel vorschlagen und Titel aufräumen."""
        self.tree.column.side_effect = lambda c, opt: {"#1": "check", "#4": "vorschlag"}[c]
        self.tree.identify_column.return_value = "#1"
        self._binde(haken_spalte="check")["<Button-1>"](self._ereignis())
        self.assertEqual(self.bearbeitet, [("i1", "check")])   # die angeklickte, nicht die markierten i2/i3

    def test_einzelklick_in_anderen_spalten_waehlt_nur_aus(self):
        bindungen = self._binde(haken_spalte="check")
        bindungen["<Button-1>"](self._ereignis())   # Spalte #4 = vorschlag
        self.tree.identify_region.return_value = "heading"
        self.tree.identify_column.return_value = "#1"
        self.tree.column.side_effect = lambda c, opt: {"#1": "check"}[c]
        bindungen["<Button-1>"](self._ereignis())
        self.assertEqual(self.bearbeitet, [])


class TestDatumEingabeDialog(unittest.TestCase):
    """B4b (21.11.2026): der Datumsdialog prüft beim Tippen - OK erst mit gültigem Datum, Ergebnis ist das
    geprüfte JJJJ-MM-TT. Über Attrappen statt echtem Fenster."""

    def _dialog(self, text):
        from unittest.mock import MagicMock
        from ui_utils import DatumEingabeDialog
        d = MagicMock()
        d.var.get.return_value = text
        d._pruefe = lambda t: ("2026-07-20", "✓ Montag, 20.07.2026") if t == "200726" else (None, "Kein gültiges Datum")
        DatumEingabeDialog._pruefen(d)
        return d, DatumEingabeDialog

    def test_gueltig_gibt_ok_frei_und_liefert_iso(self):
        d, klasse = self._dialog("200726")
        d.btn_ok.state.assert_called_with(["!disabled"])
        self.assertEqual(d.lbl_hinweis.config.call_args.kwargs["text"], "✓ Montag, 20.07.2026")
        klasse._ok(d)
        self.assertEqual(d.ergebnis, "2026-07-20")
        d.destroy.assert_called_once()

    def test_ungueltig_sperrt_ok_und_enter_schliesst_nicht(self):
        d, klasse = self._dialog("32.13.2026")
        d.btn_ok.state.assert_called_with(["disabled"])
        klasse._ok(d)
        d.destroy.assert_not_called()


class _MindestFenster:
    """Attrappe eines Toplevels für UIUtils.mindestgroesse - Inhalt verlangt req_*, Fenster ist gerade b x h."""

    def __init__(self, req=(500, 300), groesse=(900, 700), bildschirm=(1920, 1080), minsize=(1, 1), randlos=False):
        self.req, self.groesse, self.bildschirm = req, groesse, bildschirm
        self.minsize, self.randlos, self.gesetzt = minsize, randlos, []

    def winfo_exists(self):
        return True

    def wm_overrideredirect(self):
        return self.randlos

    def wm_minsize(self, *werte):
        if not werte:
            return self.minsize
        self.gesetzt.append(werte)
        self.minsize = werte

    def update_idletasks(self):
        pass

    def winfo_reqwidth(self):
        return self.req[0]

    def winfo_reqheight(self):
        return self.req[1]

    def winfo_width(self):
        return self.groesse[0]

    def winfo_height(self):
        return self.groesse[1]

    def winfo_screenwidth(self):
        return self.bildschirm[0]

    def winfo_screenheight(self):
        return self.bildschirm[1]


class TestMindestgroesse(unittest.TestCase):
    """B5 (Peter 21.11.2026): kein Fenster lässt sich winzig ziehen - Mindestgröße aus dem Inhalt, gedeckelt."""

    def test_mindestens_so_gross_wie_der_inhalt(self):
        f = _MindestFenster(req=(500, 300))
        self.assertEqual(UIUtils.mindestgroesse(f), (500, 300))
        self.assertEqual(f.gesetzt, [(500, 300)])

    def test_grosse_tabelle_auf_den_bildschirmanteil_gedeckelt(self):
        f = _MindestFenster(req=(1800, 1000), groesse=(1900, 1050))
        self.assertEqual(UIUtils.mindestgroesse(f, deckel=0.6), (1152, 648))

    def test_fenster_waechst_dabei_nicht(self):
        # position_near_mouse kann ein Fenster kleiner setzen, als der Inhalt verlangt (kleiner Bildschirm)
        f = _MindestFenster(req=(800, 600), groesse=(700, 500))
        self.assertEqual(UIUtils.mindestgroesse(f), (700, 500))

    def test_eigene_mindestgroesse_bleibt(self):
        f = _MindestFenster(minsize=(900, 600))
        self.assertIsNone(UIUtils.mindestgroesse(f))
        self.assertEqual(f.gesetzt, [])

    def test_windows_vorgabe_zaehlt_nicht_als_eigene(self):
        # Live gefunden: nach dem Zeigen meldet Tk unter Windows (120, 1) - das ist keine eigene Mindestgröße
        f = _MindestFenster(req=(500, 300), minsize=(120, 1))
        self.assertEqual(UIUtils.mindestgroesse(f), (500, 300))

    def test_randlose_fenster_bleiben(self):
        f = _MindestFenster(randlos=True)    # Tooltip, Vervollständigung, Erfolgsfeld
        self.assertIsNone(UIUtils.mindestgroesse(f))
        self.assertEqual(f.gesetzt, [])

    def test_nur_einmal_je_fenster(self):
        # Minimieren/Wiederherstellen feuert <Map> erneut - die Mindestgröße darf dann nicht neu wachsen
        f = _MindestFenster(req=(500, 300))
        UIUtils.mindestgroesse(f)
        f.minsize, f.req = (1, 1), (800, 600)
        self.assertIsNone(UIUtils.mindestgroesse(f))
        self.assertEqual(f.gesetzt, [(500, 300)])

    def test_gilt_fuer_alle_toplevel_ueber_die_klassenbindung(self):
        import tkinter as tk
        root = MagicMock()
        UIUtils.mindestgroesse_ueberall(root)
        klasse, ereignis, rueckruf = root.bind_class.call_args.args
        self.assertEqual((klasse, ereignis, root.bind_class.call_args.kwargs.get("add")), ("Toplevel", "<Map>", "+"))
        fenster = MagicMock(spec=tk.Toplevel)
        rueckruf(MagicMock(widget=fenster))
        fenster.after_idle.assert_called_once_with(UIUtils.mindestgroesse, fenster)

    def test_hauptfenster_und_dienst_richten_es_ein(self):
        import os
        for datei in ("gui.py", "dienstmodus.py"):
            with open(os.path.join(os.path.dirname(__file__), "..", "src", datei), encoding="utf-8") as f:
                self.assertIn("UIUtils.mindestgroesse_ueberall(", f.read(), datei)

    def test_texteingabe_waagrecht_ziehbar(self):
        import inspect
        from ui_utils import TextEingabeDialog
        self.assertIn("self.resizable(True, False)", inspect.getsource(TextEingabeDialog.__init__))


class TestMonatskalender(unittest.TestCase):
    """B4e (Peter 21.11.2026): Datumspicker im Datumsdialog - Logik ohne echtes Fenster."""

    def test_wochen_beginnen_am_montag(self):
        from ui_utils import Monatskalender
        wochen = Monatskalender.wochen(2026, 7)       # 1. Juli 2026 ist ein Mittwoch
        self.assertEqual(wochen[0], [0, 0, 1, 2, 3, 4, 5])
        self.assertIn(31, wochen[-1])

    def test_blaettern_ueber_jahresgrenzen(self):
        from ui_utils import Monatskalender
        self.assertEqual(Monatskalender.verschiebe(2026, 1, -1), (2025, 12))
        self.assertEqual(Monatskalender.verschiebe(2026, 12, 1), (2027, 1))
        self.assertEqual(Monatskalender.verschiebe(2026, 7, -12), (2025, 7))
        self.assertEqual(Monatskalender.verschiebe(2026, 3, -27), (2023, 12))

    def test_darstellung_gewaehlt_heute_zukunft(self):
        from datetime import date
        from ui_utils import Monatskalender
        heute, gewaehlt = date(2026, 11, 21), date(2026, 11, 3)
        self.assertEqual(Monatskalender.darstellung(gewaehlt, gewaehlt, heute, heute), ("KalenderGewaehlt.TButton", False))
        self.assertEqual(Monatskalender.darstellung(heute, gewaehlt, heute, heute), ("KalenderHeute.TButton", False))
        self.assertEqual(Monatskalender.darstellung(date(2026, 11, 5), gewaehlt, heute, heute), ("Kalender.TButton", False))
        self.assertTrue(Monatskalender.darstellung(date(2026, 11, 22), gewaehlt, heute, heute)[1])

    def test_klick_waehlt_doppelklick_bestaetigt(self):
        from datetime import date
        from ui_utils import Monatskalender
        k = MagicMock()
        Monatskalender._klick(k, date(2026, 7, 20))
        k._waehle.assert_called_once_with(date(2026, 7, 20))
        k.zeige.assert_called_once_with(2026, 7)
        k._tag_von = {"knopf": date(2026, 7, 20)}
        Monatskalender._doppelklick(k, "knopf")
        k._bestaetige.assert_called_once_with(date(2026, 7, 20))

    def test_dialog_kalender_fuellt_feld_und_folgt_der_eingabe(self):
        from datetime import date
        from ui_utils import DatumEingabeDialog
        d = MagicMock()
        DatumEingabeDialog._aus_kalender(d, date(2026, 7, 20))
        d.var.set.assert_called_once_with("20.07.2026")
        d.var.get.return_value = "200726"
        d._pruefe = lambda t: ("2026-07-20", "✓ Montag, 20.07.2026")
        DatumEingabeDialog._pruefen(d)
        d.kalender.markiere.assert_called_once_with("2026-07-20")


class TestAusserhalb(unittest.TestCase):
    """Klick neben den aufgeklappten Kalender klappt ihn zu, Klick hinein nicht (B4e)."""

    def test_rand_und_daneben(self):
        f = MagicMock()
        f.winfo_rootx.return_value, f.winfo_rooty.return_value = 100, 200
        f.winfo_width.return_value, f.winfo_height.return_value = 50, 40
        self.assertFalse(UIUtils.ausserhalb(f, 100, 200))
        self.assertFalse(UIUtils.ausserhalb(f, 149, 239))
        self.assertTrue(UIUtils.ausserhalb(f, 150, 220))
        self.assertTrue(UIUtils.ausserhalb(f, 120, 199))


if __name__ == "__main__":
    unittest.main()
