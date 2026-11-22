import calendar
import datetime
import re
import sys
import time
import tkinter as tk
import aktivitaet
import tkinter.font as tkfont
from tkinter import ttk

_GWL_STYLE = -16
_WS_MAXIMIZEBOX = 0x00010000
_SWP_RAHMEN_NEU = 0x0001 | 0x0002 | 0x0004 | 0x0010 | 0x0020   # NOSIZE|NOMOVE|NOZORDER|NOACTIVATE|FRAMECHANGED
_GWL_EXSTYLE = -20
_GWLP_HWNDPARENT = -8
_WS_EX_NOACTIVATE = 0x08000000
_WS_EX_TOOLWINDOW = 0x00000080
_SW_SHOWNOACTIVATE = 4
_SWP_NUR_ORT = 0x0001 | 0x0004 | 0x0010                         # NOSIZE|NOZORDER|NOACTIVATE

# Erfolgsfeld (aktivitaet.erledigt): Bedeutungsfarben, darum hier und nicht in ui_theme. Peter 21.11.2026 im
# Probefenster: Lime, blinkend, 2,5 s - der Text in der Menüleiste allein „fällt nicht auf“, und die Windows-
# Menüleiste lässt sich nicht färben (auch Emoji bleiben dort schwarz-weiß).
ERFOLG_FARBE = "#00FF00"
ERFOLG_BLASS = "#CCFFCC"
ERFOLG_RAND = "#1E7B1E"
ERFOLG_BLINK_MS = 500
# B5 (Peter 21.11.2026): Fenster und Dialoge lassen sich nicht kleiner ziehen als ihr Inhalt verlangt - höchstens
# auf diesen Anteil des Bildschirms gedeckelt, damit große Tabellen-Fenster trotzdem nebeneinander passen
MINDEST_DECKEL = 0.6


def _win_rahmen(fenster):
    """Fenster-Handle des äußeren Rahmens (den zeichnet Windows, nicht Tk); 0, wenn es noch keinen gibt."""
    try:
        return int(fenster.wm_frame(), 16)
    except (tk.TclError, ValueError):
        return 0


def _win_ist_maximiert(fenster):
    """Ist das Fenster maximiert? Über Windows gefragt: im Moment des Verbergens meldet Tk nur noch 'withdrawn'."""
    import ctypes
    rahmen = _win_rahmen(fenster)
    return bool(rahmen and ctypes.windll.user32.IsZoomed(rahmen))


def _win_maximieren_knopf(fenster):
    """Setzt die Maximieren-Schaltfläche in den Fensterrahmen, falls sie fehlt (transient entfernt sie)."""
    import ctypes
    from ctypes import wintypes
    rahmen = _win_rahmen(fenster)
    if not rahmen:
        return
    user32 = ctypes.WinDLL("user32")   # eigene Instanz: argtypes gelten nur hier, nicht für ctypes.windll
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND] + [ctypes.c_int] * 4 + [ctypes.c_uint]
    stil = user32.GetWindowLongW(rahmen, _GWL_STYLE)
    if not stil & _WS_MAXIMIZEBOX:
        user32.SetWindowLongW(rahmen, _GWL_STYLE, stil | _WS_MAXIMIZEBOX)
        user32.SetWindowPos(rahmen, None, 0, 0, 0, 0, _SWP_RAHMEN_NEU)   # Titelleiste neu zeichnen lassen


def _win_ohne_fokus_zeigen(fenster, besitzer, x, y):
    """Zeigt ein verborgenes overrideredirect-Fenster bei (x, y), ohne den Fokus zu nehmen: Wer gerade tippt,
    tippt weiter. Bewusst an Tk vorbei (deiconify würde aktivieren) - darum Besitzer und Ort selbst setzen, Tk
    wendet geometry() dann nicht an (im Probefenster stand das Feld sonst bei 0,0 hinter allem). Kein
    transient(): das baut den Rahmen neu und verwirft den Stil (FALLSTRICKE #137). Der Besitzer hält das Feld
    über dem Hauptfenster und nimmt es mit hinter andere Programme."""
    import ctypes
    from ctypes import wintypes
    rahmen, haupt = _win_rahmen(fenster), _win_rahmen(besitzer)
    if not rahmen:
        return False
    user32 = ctypes.WinDLL("user32")   # eigene Instanz: argtypes gelten nur hier, nicht für ctypes.windll
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND] + [ctypes.c_int] * 4 + [ctypes.c_uint]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    stil = user32.GetWindowLongW(rahmen, _GWL_EXSTYLE)
    user32.SetWindowLongW(rahmen, _GWL_EXSTYLE, stil | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW)
    if haupt:
        user32.SetWindowLongPtrW(rahmen, _GWLP_HWNDPARENT, haupt)
    user32.SetWindowPos(rahmen, None, x, y, 0, 0, _SWP_NUR_ORT)
    user32.ShowWindow(rahmen, _SW_SHOWNOACTIVATE)
    return True


class UIUtils:
    # Suffixe für die Sortier-Anzeige in den Spaltenköpfen
    SORT_ASC_SUFFIX = " ▲"
    SORT_DESC_SUFFIX = " ▼"
    _einzelfenster = {}     # Schlüssel -> offenes Werkzeugfenster (einzelfenster)

    @staticmethod
    def tabelle_bearbeitbar(tree, bearbeite, menue=None, f2_spalte=None):
        """
        Einheitliche Auslöser für Tabellen mit bearbeitbaren Zellen (Fenster-Durchsicht B4c, 21.11.2026):
        Einzelklick wählt nur aus, Doppelklick auf eine Zelle ruft `bearbeite(iid, spalte)`, Rechtsklick zeigt
        `menue(iid)` -> [(spalte, Beschriftung)] als Menü (wählt die Zeile vorher aus; None/leer = kein Menü),
        F2 bearbeitet `f2_spalte` der ersten markierten Zeile. Spalten immer über ihre ID, nie über „#3“: eine
        neue Spalte verschob in „Dateinamen aufräumen“ unbemerkt das Ziel des Doppelklicks (FALLSTRICKE #140).
        """
        def doppelklick(event):
            if tree.identify_region(event.x, event.y) != "cell":
                return None
            iid = tree.identify_row(event.y)
            if iid:
                bearbeite(iid, tree.column(tree.identify_column(event.x), "id"))
            return "break"

        def rechtsklick(event):
            iid = tree.identify_row(event.y)
            eintraege = menue(iid) if (iid and menue is not None) else None
            if not eintraege:
                return None
            if iid not in tree.selection():
                tree.selection_set(iid)   # <<TreeviewSelect>> folgt von selbst (FALLSTRICKE #8)
            m = tk.Menu(tree, tearoff=0)
            for spalte, text in eintraege:
                m.add_command(label=text, command=lambda s=spalte: bearbeite(iid, s))
            try:
                m.tk_popup(event.x_root, event.y_root)
            finally:
                m.grab_release()
            return "break"

        def f2(event):
            auswahl = tree.selection()
            if auswahl:
                bearbeite(auswahl[0], f2_spalte)
            return "break"

        tree.bind("<Double-1>", doppelklick)
        if menue is not None:
            tree.bind("<Button-3>", rechtsklick)
        if f2_spalte:
            tree.bind("<F2>", f2)

    @staticmethod
    def erfolgsfeld(hauptfenster, text, dauer_ms):
        """Lime-grünes Feld „✓ text“ oben rechts im Hauptfenster, blinkt und verschwindet nach dauer_ms von selbst
        (aktivitaet.erledigt). Nimmt nie den Fokus. Ein neues ersetzt ein noch stehendes. Ist das Hauptfenster
        nicht zu sehen (minimiert, Dienstmodus), kein Feld - die Meldung steht dann nur in Leiste und Log.
        :return: das Feld oder None"""
        alt = getattr(hauptfenster, "_kid_erfolgsfeld", None)
        if alt is not None:
            try:
                alt.destroy()
            except tk.TclError:
                pass
            hauptfenster._kid_erfolgsfeld = None
        try:
            if not hauptfenster.winfo_viewable():
                return None
        except tk.TclError:
            return None
        feld = tk.Toplevel(hauptfenster)
        feld.withdraw()
        feld.overrideredirect(True)
        rand = tk.Frame(feld, bg=ERFOLG_RAND, padx=2, pady=2)
        rand.pack()
        schrift = tkfont.nametofont("TkDefaultFont", root=hauptfenster).actual("family")
        etikett = tk.Label(rand, text="✓ " + text, bg=ERFOLG_FARBE, fg="black",
                           font=(schrift, UIUtils.schriftgroesse(hauptfenster, 2), "bold"),
                           padx=UIUtils.px(hauptfenster, 14), pady=UIUtils.px(hauptfenster, 6))
        etikett.pack()
        feld.update_idletasks()
        x = hauptfenster.winfo_rootx() + hauptfenster.winfo_width() - feld.winfo_reqwidth() - UIUtils.px(hauptfenster, 12)
        y = hauptfenster.winfo_rooty() + UIUtils.px(hauptfenster, 8)
        if sys.platform == "win32":
            if not _win_ohne_fokus_zeigen(feld, hauptfenster, x, y):
                feld.destroy()
                return None
        else:
            feld.geometry(f"+{x}+{y}")
            feld.deiconify()
        hauptfenster._kid_erfolgsfeld = feld

        def blinke(schritt):
            if etikett.winfo_exists():
                etikett.config(bg=ERFOLG_FARBE if schritt % 2 == 0 else ERFOLG_BLASS)

        def weg():
            if feld.winfo_exists():
                feld.destroy()
            if getattr(hauptfenster, "_kid_erfolgsfeld", None) is feld:
                hauptfenster._kid_erfolgsfeld = None

        for schritt in range(1, max(1, dauer_ms // ERFOLG_BLINK_MS)):
            hauptfenster.after(schritt * ERFOLG_BLINK_MS, blinke, schritt)
        hauptfenster.after(dauer_ms, weg)
        return feld

    @staticmethod
    def werkzeugfenster(fenster, hauptfenster, maximierbar=False):
        """Werkzeugfenster über KID halten, ohne modal zu sein (Peter 04.11.2026: „wieder TopMost, aber nicht modal -
        sonst verschwindet ein Fenster aus Versehen im Hintergrund und wird doppelt geöffnet“): transient zum
        Hauptfenster - bleibt darüber, verschwindet mit ihm, blockiert nichts. Kein -topmost: das läge auch über
        allen anderen Programmen.

        `maximierbar`: transient nimmt dem Fenster unter Windows die Maximieren-Schaltfläche. Für große Tabellen
        (Ablage-Vorschau, Dubletten-Finder; Peter 01.09. und 21.11.2026) wird sie bei jedem Zeigen neu gesetzt -
        Tk baut den Fensterrahmen bei manchen Vorgängen neu auf (Hauptfenster minimiert/zurück, resizable, erneutes
        transient) und verliert dabei Schaltfläche UND Maximierung; beides stellt <Map> wieder her (FALLSTRICKE #137)."""
        try:
            fenster.transient(hauptfenster)
        except tk.TclError:
            pass
        if maximierbar and sys.platform == "win32":
            UIUtils._maximierbar_halten(fenster)

    @staticmethod
    def mindestgroesse(fenster, deckel=None):
        """Mindestgröße eines Fensters aus seinem Inhalt (B5, Peter 21.11.2026: „sinnvolle (default) Mindestgröße,
        so dass man das Fenster nicht winzig ziehen kann“). Mindestens so groß, wie der Inhalt verlangt
        (`winfo_req*`), aber nie größer als das Fenster gerade ist (es soll dabei nicht wachsen) und nie größer als
        `deckel` (Anteil des Bildschirms, Vorgabe MINDEST_DECKEL). Läuft einmal je Fenster; ein Fenster mit eigener
        Mindestgröße (Dateinamen, Dubletten, Einstellungen) und randlose Fenster (Tooltip, Vervollständigung,
        Erfolgsfeld) bleiben, wie sie sind. :return: (Breite, Höhe) oder None, wenn nichts gesetzt wurde"""
        try:
            if not fenster.winfo_exists() or getattr(fenster, "_mindestgroesse_gesetzt", False):
                return None
            fenster._mindestgroesse_gesetzt = True
            if fenster.wm_overrideredirect():
                return None
            eigene_b, eigene_h = fenster.wm_minsize()
            # Windows meldet nach dem Zeigen eine Vorgabe wie (120, 1) - eigene Mindestgrößen haben BEIDE Werte > 1
            if eigene_b > 1 and eigene_h > 1:
                return None
            fenster.update_idletasks()
            anteil = MINDEST_DECKEL if deckel is None else deckel
            breite = min(fenster.winfo_reqwidth(), fenster.winfo_width(), int(fenster.winfo_screenwidth() * anteil))
            hoehe = min(fenster.winfo_reqheight(), fenster.winfo_height(),
                        int(fenster.winfo_screenheight() * anteil))
            if breite <= 1 or hoehe <= 1:
                return None
            fenster.wm_minsize(breite, hoehe)
            return breite, hoehe
        except tk.TclError:
            return None

    @staticmethod
    def mindestgroesse_ueberall(root):
        """Jedes Toplevel bekommt beim ersten Erscheinen seine Mindestgröße (`mindestgroesse`) - an EINER Stelle statt
        in 30 Fensterklassen, und neue Fenster haben sie von selbst. Die Klassenbindung „Toplevel“ trifft nur die
        Fenster selbst, nicht ihre Kinder und nicht das Hauptfenster (Klasse „Tk“). after_idle: beim ersten <Map>
        steht die Geometrie mancher Fenster noch aus."""
        def erschienen(event):
            fenster = event.widget
            if isinstance(fenster, tk.Toplevel) and not getattr(fenster, "_mindestgroesse_gesetzt", False):
                fenster.after_idle(UIUtils.mindestgroesse, fenster)

        root.bind_class("Toplevel", "<Map>", erschienen, add="+")

    @staticmethod
    def _maximierbar_halten(fenster):
        """Maximieren-Schaltfläche und Maximierung über jeden Neuaufbau des Fensterrahmens retten (siehe oben)."""
        zustand = {"maximiert": False}

        def verborgen(event):
            if event.widget is fenster:   # <Unmap>/<Map> feuern auch für jedes Kind-Widget
                zustand["maximiert"] = _win_ist_maximiert(fenster)

        def gezeigt(event):
            if event.widget is not fenster:
                return
            _win_maximieren_knopf(fenster)
            if zustand["maximiert"] and fenster.state() != "zoomed":
                fenster.state("zoomed")
            # Nur für EIN Verbergen/Zeigen merken: baut Tk den Rahmen ohne <Unmap> neu (z.B. resizable), nachdem
            # der Nutzer wiederhergestellt hat, maximierte ein alter Merker das Fenster sonst ungefragt
            zustand["maximiert"] = False

        fenster.bind("<Unmap>", verborgen, add="+")
        fenster.bind("<Map>", gezeigt, add="+")

    @staticmethod
    def einzelfenster(schluessel, erzeugen, eingabe=None):
        """Höchstens EIN offenes Fenster je Schlüssel: ist es schon offen, kommt es nach vorn statt eines zweiten
        (zwei Fenster auf denselben Daten schreiben sich sonst gegenseitig alte Stände zurück). Werkzeuge rufen das
        über `BaseTool.oeffne_fenster` auf (Fenster-Durchsicht B3, Peter 21.11.2026).

        `eingabe` (Pfad oder Liste von Pfaden, z.B. die markierten Dokumente): Zeigt das offene Fenster andere
        Dokumente, entscheidet das Fenster selbst - `uebernimm_eingabe(pfade)` wechselt es dorthin (PDF-Inspektor,
        Erfassungs-Analyse), `ist_verwerfbar()` = True lässt es einem neuen weichen (Ablage-Vorschau nach dem
        Einsortieren); sonst bleibt es mit seinen Änderungen stehen und ein Hinweis sagt, warum die neue Auswahl nicht
        erscheint. Früher verwarfen manche Werkzeuge das offene Fenster samt Korrekturen (A3). :return: das Fenster"""
        pfade = UIUtils._pfadliste(eingabe)
        offen = UIUtils._einzelfenster.get(schluessel)
        try:
            if offen is not None and offen.winfo_exists():
                alt = getattr(offen, "_werkzeug_eingabe", [])
                if not pfade or UIUtils._pfadmenge(alt) == UIUtils._pfadmenge(pfade):
                    UIUtils._nach_vorn(offen)
                    return offen
                if callable(getattr(offen, "uebernimm_eingabe", None)):
                    offen.uebernimm_eingabe(pfade)
                    offen._werkzeug_eingabe = pfade
                    UIUtils._nach_vorn(offen)
                    return offen
                if not (callable(getattr(offen, "ist_verwerfbar", None)) and offen.ist_verwerfbar()):
                    UIUtils._nach_vorn(offen)
                    from tkinter import messagebox
                    messagebox.showinfo(
                        "Fenster ist schon offen",
                        f"„{offen.title()}“ ist schon offen und zeigt andere Dokumente.\n\n"
                        "Bitte dort erst fertig werden oder das Fenster schließen, dann die neue Auswahl öffnen - "
                        "sonst gingen die Änderungen im offenen Fenster verloren.", parent=offen)
                    return offen
                offen.destroy()
        except tk.TclError:
            pass
        fenster = erzeugen()
        try:
            fenster._werkzeug_eingabe = pfade
        except AttributeError:
            pass
        UIUtils._einzelfenster[schluessel] = fenster
        return fenster

    @staticmethod
    def _nach_vorn(fenster):
        fenster.deiconify()
        fenster.lift()
        fenster.focus_set()

    @staticmethod
    def _pfadliste(eingabe):
        if not eingabe:
            return []
        return [eingabe] if isinstance(eingabe, str) else list(eingabe)

    @staticmethod
    def _pfadmenge(pfade):
        import os
        return {os.path.normcase(os.path.abspath(p)) for p in pfade}

    @staticmethod
    def clear_placeholder(entry, placeholder):
        """Entfernt den Platzhalter-Text, wenn das Feld fokussiert wird."""
        if entry.get() == placeholder: 
            entry.delete(0, tk.END)

    @staticmethod
    def add_placeholder(entry, placeholder):
        """Fügt den Platzhalter-Text wieder ein, wenn das Feld leer verlassen wird."""
        if not entry.get().strip(): 
            entry.insert(0, placeholder)

    @staticmethod
    def monitor_bounds_at(window, x, y):
        """
        Arbeitsbereich (ohne Taskleiste) des Monitors, auf dem der Punkt (x, y) liegt, als
        (links, oben, rechts, unten). Tk kennt bei mehreren Monitoren nur den Hauptmonitor
        (winfo_screenwidth/-height) - wer daran begrenzt, schiebt Dialoge vom zweiten
        Monitor zurück auf den ersten (ToDo 30.08.2026). Unter Windows fragt daher die
        Win32-API nach dem Monitor unter dem Punkt; andere Systeme/Fehler: Hauptmonitor.
        """
        try:
            import ctypes
            from ctypes import wintypes

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            user32 = ctypes.windll.user32
            MONITOR_DEFAULTTONEAREST = 2
            handle = user32.MonitorFromPoint(wintypes.POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST)
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if handle and user32.GetMonitorInfoW(handle, ctypes.byref(info)):
                r = info.rcWork
                return r.left, r.top, r.right, r.bottom
        except Exception:
            pass
        return 0, 0, window.winfo_screenwidth(), window.winfo_screenheight()

    @staticmethod
    def punkt_auf_einem_monitor(x, y):
        """
        True, wenn der Punkt auf IRGENDEINEM angeschlossenen Monitor liegt (Win32,
        MONITOR_DEFAULTTONULL liefert 0 fürs Nirgendwo). Andere Systeme oder Fehler:
        True - im Zweifel wird eine gespeicherte Fensterposition nicht verworfen.
        """
        try:
            import ctypes
            from ctypes import wintypes
            MONITOR_DEFAULTTONULL = 0
            return bool(ctypes.windll.user32.MonitorFromPoint(
                wintypes.POINT(int(x), int(y)), MONITOR_DEFAULTTONULL))
        except Exception:
            return True

    @staticmethod
    def sichere_fenstergeometrie(geometry, punkt_pruefer=None):
        """
        Prüft eine gespeicherte Tk-Geometrie ('BxH+X+Y') darauf, ob die Titelleiste
        noch auf einem angeschlossenen Monitor liegt. Nutzerfund 06.09.2026: Nach
        geänderter Monitor-Anordnung startete die App bei '+-4028+-921' - komplett
        unsichtbar, die Titelleiste zum Zurückziehen unerreichbar. Liegt keiner der
        drei Titelleisten-Prüfpunkte (links/Mitte/rechts, leicht unterhalb der
        Oberkante) auf einem Monitor, wird NUR die Position verworfen - die Größe
        bleibt, Tk platziert das Fenster dann selbst auf dem Hauptmonitor.
        :param punkt_pruefer: Testeinschleusung; Standard ist punkt_auf_einem_monitor.
        """
        pruefer = punkt_pruefer or UIUtils.punkt_auf_einem_monitor
        m = re.match(r"^(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", geometry or "")
        if not m:
            return geometry   # unbekanntes Format (z.B. nur 'BxH'): unverändert lassen
        breite, hoehe, x, y = (int(g) for g in m.groups())
        titelleiste_y = y + 12
        for punkt_x in (x + 12, x + breite // 2, x + breite - 12):
            if pruefer(punkt_x, titelleiste_y):
                return geometry
        return f"{breite}x{hoehe}"

    @staticmethod
    def fensterrahmen():
        """
        Zusätzlicher Platz, den Windows um den Innenbereich eines Fensters legt, als
        (breite, hoehe): Rahmen links+rechts bzw. Titelleiste + Rahmen oben/unten. Tk zählt bei
        geometry("BxH+X+Y") B×H als INNENmaß, X/Y aber als Außenkante - ohne diesen Zuschlag
        ragte ein unten am Bildschirm geöffnetes Fenster um gut 30 px über den Rand und die
        Knöpfe der Fußzeile waren abgeschnitten (Release-Check T0.16, 25.10.2026, FALLSTRICKE #77).
        """
        try:
            import ctypes
            m = ctypes.windll.user32.GetSystemMetrics
            rahmen = m(33) + m(92)            # SM_CYSIZEFRAME + SM_CXPADDEDBORDER
            titel = m(4)                      # SM_CYCAPTION
            if titel > 0:
                return 2 * rahmen, titel + 2 * rahmen
        except Exception:
            pass
        return 16, 39

    @staticmethod
    def _begrenzt_auf_monitor(window, x, y, width, height, bezug=None):
        """Verschiebt die gewünschte Position so, dass das Fenster ganz auf EINEM Monitor liegt: dem unter `bezug`
        (x, y), ohne Angabe dem unter dem Mauszeiger. Ein schon offenes Fenster, das nur wächst, gibt seinen eigenen
        Ort als Bezug an - sonst springt es auf den Monitor, auf dem gerade die Maus ist (Peter 02.11.2026: das
        Vollautomatik-Fenster folgte bei jedem Wachsen der Maus in ein anderes Programm)."""
        bx, by = bezug if bezug is not None else (window.winfo_pointerx(), window.winfo_pointery())
        links, oben, rechts, unten = UIUtils.monitor_bounds_at(window, bx, by)
        rahmen_b, rahmen_h = UIUtils.fensterrahmen()
        x = max(links, min(x, rechts - width - rahmen_b))
        y = max(oben, min(y, unten - height - rahmen_h))
        return x, y

    #: Windows-Standardschrift „Segoe UI 9" - Bezugsgröße für den Schriftfaktor (Textgröße 100 %)
    BASIS_SCHRIFTGROESSE_PT = 9

    @staticmethod
    def schriftgroesse(widget=None, delta=0):
        """
        Punktgröße der Standardschrift (TkDefaultFont) plus `delta` - für eigene Schriften
        wie „fett" oder „eine Stufe größer", die mit der Windows-Textgröße mitwachsen sollen
        statt fest bei 9 pt zu bleiben (FALLSTRICKE #69). Ohne Tk-Fenster: 9 + delta.
        """
        try:
            groesse = int(tkfont.nametofont("TkDefaultFont", root=widget).actual("size"))
            if groesse < 0:   # negative Werte sind Pixel
                groesse = int(round(-groesse * 72.0 / max(1.0, widget.winfo_fpixels("1i") if widget else 96.0)))
            if groesse <= 0:
                raise ValueError(groesse)
        except Exception:
            groesse = UIUtils.BASIS_SCHRIFTGROESSE_PT
        return groesse + delta

    @staticmethod
    def schriftfaktor(widget=None):
        """
        Verhältnis der Windows-Textgröße (Einstellungen → Barrierefreiheit → Textgröße) zu 100 %.

        Diese Einstellung vergrößert nur die Systemschriften - Tk übernimmt sie in
        TkDefaultFont (9 pt → 11 pt bei 125 %) -, NICHT die Bildschirmauflösung:
        winfo_fpixels merkt davon nichts. Der Beta-Tester fährt beides, 125 % Skalierung UND
        125 % Textgröße; nur mit der Auflösung skaliert blieben die Fenster ein Viertel zu
        klein und Knöpfe wurden weggequetscht (FALLSTRICKE #69). Nur unter Windows, sonst 1.0.
        """
        if sys.platform != "win32":
            return 1.0
        return max(1.0, UIUtils.schriftgroesse(widget) / float(UIUtils.BASIS_SCHRIFTGROESSE_PT))

    @staticmethod
    def skalierung(widget):
        """
        Verhältnis der tatsächlichen Bildschirmauflösung zu 96 dpi (= 100 %), multipliziert
        mit dem Schriftfaktor der Windows-Textgröße (`schriftfaktor`).

        Windows skaliert Schrift und Bedienelemente (beim Betatest 125 %), feste
        Pixelwerte im Code aber nicht - Texte liefen dort aus den Fenstern heraus
        (FALLSTRICKE #42). Jedes Fenster mit fester Größe multipliziert seine Maße
        deshalb mit diesem Faktor.
        """
        try:
            dpi_faktor = max(1.0, widget.winfo_fpixels("1i") / 96.0)
        except Exception:
            return 1.0
        return dpi_faktor * UIUtils.schriftfaktor(widget)

    @staticmethod
    def letzter_sichtbarer(baum):
        """Letzter Eintrag, den man im Baum sieht (in aufgeklappten Knoten weiter nach unten), sonst None."""
        kinder = baum.get_children("")
        if not kinder:
            return None
        eintrag = kinder[-1]
        while baum.item(eintrag, "open") and baum.get_children(eintrag):
            eintrag = baum.get_children(eintrag)[-1]
        return eintrag

    @staticmethod
    def baum_springen(baum, ende=False):
        """Pos1/Ende in einem Treeview: ersten bzw. letzten sichtbaren Eintrag wählen und zeigen."""
        kinder = baum.get_children("")
        eintrag = UIUtils.letzter_sichtbarer(baum) if ende else (kinder[0] if kinder else None)
        if eintrag:
            baum.selection_set(eintrag)
            baum.focus(eintrag)
            baum.see(eintrag)
        return "break"

    @staticmethod
    def px(widget, wert):
        """Rechnet einen für 100 % gedachten Pixelwert auf die aktuelle Skalierung um."""
        return int(round(wert * UIUtils.skalierung(widget)))

    @staticmethod
    def app_hat_fokus(window=None):
        """
        Ist KID gerade das aktive Programm? Unter Windows: gehört das Vordergrundfenster zu diesem Prozess
        (deckt auch Dialoge und Werkzeugfenster ab); sonst: hat irgendein Tk-Widget den Fokus. Im Zweifel True -
        dann bleibt es beim bisherigen Verhalten (am Mauszeiger).
        """
        try:
            if sys.platform == "win32":
                import ctypes
                import os
                pid = ctypes.c_ulong()
                ctypes.windll.user32.GetWindowThreadProcessId(ctypes.windll.user32.GetForegroundWindow(),
                                                              ctypes.byref(pid))
                return pid.value == os.getpid()
            return window is not None and window.focus_get() is not None
        except Exception:
            return True

    @staticmethod
    def _anker(window, width, height, offset, ueber_kid=False):
        """
        Wo ein neues Fenster hin soll: (x, y, Bezugspunkt für den Monitor). Arbeitet man in KID, neben dem
        Mauszeiger - dort schaut man hin. Arbeitet man gerade in einem ANDEREN Programm (Vollautomatik, Werkzeug
        oder Meldung aus dem Hintergrund), mittig über dem KID-Hauptfenster statt mitten in das fremde Programm
        (Peter 02.11.2026). Ist das Hauptfenster minimiert, bleibt es beim Mauszeiger. `ueber_kid=True`: immer
        über dem Hauptfenster - für Fenster, die KID von sich aus öffnet (Statusfenster beim Programmstart: dann
        ist KID zwar aktiv, die Maus aber noch im Programm, aus dem man KID gestartet hat).
        """
        maus = (window.winfo_pointerx(), window.winfo_pointery())
        if not ueber_kid and UIUtils.app_hat_fokus(window):
            return maus[0] + offset, maus[1] + offset, maus
        try:
            haupt = window._root()
            # Die tatsächlichen Maße des gezeichneten Fensters: geometry() meldet bei maximiertem Fenster noch die
            # Lage VOR dem Maximieren (gemessen +358+260 statt +82+43 - Peter: „nicht mittig“). Vor dem ersten
            # Zeichnen ist es 1 Pixel breit, seine Mitte unbekannt - dann bleibt es beim Mauszeiger
            # (Abnahme T4.15: Fenster landete an KIDs oberer linker Ecke)
            b, h = haupt.winfo_width(), haupt.winfo_height()
            x, y = haupt.winfo_rootx(), haupt.winfo_rooty()
            if haupt is not window and b > 1 and h > 1 and haupt.state() not in ("iconic", "withdrawn"):
                mitte = (x + b // 2, y + h // 2)
                return mitte[0] - width // 2, mitte[1] - height // 2, mitte
        except Exception:
            pass
        return maus[0] + offset, maus[1] + offset, maus

    @staticmethod
    def position_near_mouse(window, width, height, offset=20, ueber_kid=False):
        """
        Platziert ein Toplevel-Fenster in der Nähe des Mauszeigers, begrenzt auf den
        Monitor, auf dem der Mauszeiger steht (Fenster ragt nie über dessen Rand hinaus).
        Hat KID gerade nicht den Fokus, stattdessen mittig über dem Hauptfenster (`_anker`).
        :param window: Das zu platzierende Toplevel-Fenster.
        :param width/height: Gewünschte Fenstergröße in Pixeln.
        :param offset: Abstand zum Mauszeiger, damit dieser nicht direkt auf dem Fenster landet.
        :return: (Breite, Höhe) wie tatsächlich gesetzt, also ggf. auf den Monitor verkleinert.
        """
        # Größe auf den Arbeitsbereich begrenzen: hochskalierte Maße (125 %) können sonst
        # größer werden als der Bildschirm - dann läge die Knopfleiste unter der Taskleiste.
        _x, _y, bezug = UIUtils._anker(window, width, height, offset, ueber_kid)
        links, oben, rechts, unten = UIUtils.monitor_bounds_at(window, *bezug)
        rahmen_b, rahmen_h = UIUtils.fensterrahmen()
        width = min(width, rechts - links - rahmen_b)
        height = min(height, unten - oben - rahmen_h)
        x, y, bezug = UIUtils._anker(window, width, height, offset, ueber_kid)
        x, y = UIUtils._begrenzt_auf_monitor(window, x, y, width, height, bezug=bezug)
        window.geometry(f"{width}x{height}+{x}+{y}")
        return width, height

    @staticmethod
    def ausserhalb(fenster, x_root, y_root):
        """Liegt der Bildschirmpunkt außerhalb des Fensters? (Klick neben eine Aufklapp-Liste klappt sie zu.)"""
        x, y = fenster.winfo_rootx(), fenster.winfo_rooty()
        return not (x <= x_root < x + fenster.winfo_width() and y <= y_root < y + fenster.winfo_height())

    @staticmethod
    def kalender_aufklappen(unter, waehle, iso=None, bis=None):
        """Monatskalender als Aufklapp-Liste direkt unter einem Datumsfeld (B4e, Peter 21.11.2026: „bau den Kalender
        auch ins Hauptfenster“). Klick auf einen Tag klappt zu und ruft `waehle(date)`; Esc, ein Klick daneben oder
        ein Wechsel in ein anderes Programm klappen ohne Wahl zu. Randlos wie die Tag-Vervollständigung; der
        lokale Grab leitet Klicks neben die Liste an sie weiter (wie bei ttk::combobox).
        :param iso: Datum im Feld ('JJJJ-MM-TT') - der Kalender zeigt dessen Monat, sonst den aktuellen
        :return: das Aufklappfenster"""
        klappe = tk.Toplevel(unter)
        klappe.withdraw()
        klappe.overrideredirect(True)
        rahmen = ttk.Frame(klappe, style="Klappe.TFrame", padding=UIUtils.px(klappe, 4))
        rahmen.pack(fill=tk.BOTH, expand=True)

        def zu(_event=None):
            try:
                klappe.grab_release()
                klappe.destroy()
            except tk.TclError:
                pass

        def gewaehlt(datum):
            zu()
            waehle(datum)

        def fokus_weg(_event):
            # FocusOut kommt auch, wenn der Fokus nur auf einen Tagesknopf wandert - erst danach nachsehen
            def pruefen():
                try:
                    fokus = klappe.focus_get()
                except (tk.TclError, KeyError):
                    fokus = None
                if fokus is None or not str(fokus).startswith(str(klappe)):
                    zu()
            klappe.after_idle(pruefen)

        kalender = Monatskalender(rahmen, waehle=gewaehlt, bestaetige=None, bis=bis)
        kalender.pack()
        if iso:
            kalender.markiere(iso)
        klappe.update_idletasks()
        breite, hoehe = klappe.winfo_reqwidth(), klappe.winfo_reqheight()
        x, y = unter.winfo_rootx(), unter.winfo_rooty() + unter.winfo_height()
        x, y = UIUtils._begrenzt_auf_monitor(klappe, x, y, breite, hoehe, bezug=(x, y))
        klappe.geometry(f"+{x}+{y}")
        klappe.deiconify()
        klappe.lift()
        klappe.bind("<Escape>", zu)
        klappe.bind("<Button-1>", lambda e: zu() if UIUtils.ausserhalb(klappe, e.x_root, e.y_root) else None,
                    add="+")
        klappe.bind("<FocusOut>", fokus_weg, add="+")
        try:
            klappe.focus_force()     # der Nutzer hat geklickt/Alt+↓ gedrückt - Esc soll sofort gehen
            klappe.grab_set()
        except tk.TclError:
            pass
        klappe.kalender = kalender
        return klappe

    @staticmethod
    def ask_datum(title, prompt, initialvalue=None, pruefe=None, parent=None):
        """
        Datumsdialog mit eingebauter Prüfung (B4b, 21.11.2026): `pruefe(text)` -> ('JJJJ-MM-TT' oder None,
        Hinweis) läuft bei jedem Tastendruck, der Hinweis steht unter dem Feld („✓ Montag, 20.07.2026“ oder der
        Grund), OK/Enter gehen erst mit gültigem Datum. Vorher: Eingabe, Fehlermeldung, nochmal von vorn.
        :return: das geprüfte Datum ('JJJJ-MM-TT') oder None bei Abbrechen
        """
        if parent is None:
            parent = tk._get_default_root("Dialog anzeigen")
        with aktivitaet.warte_auf_antwort(title):
            return DatumEingabeDialog.ask(parent, title, prompt, initialvalue or "", pruefe=pruefe)

    @staticmethod
    def ask_string(title, prompt, initialvalue=None, parent=None):
        """
        Drop-in-Ersatz für tkinter.simpledialog.askstring, aber am Mauszeiger auf dem
        Monitor unter dem Zeiger platziert (Nutzerfund 30.08.2026: das „Neues Tag"-Fenster
        erschien weiter am Hauptfenster-Ursprung, weil simpledialog seine Position selbst
        aus dem Parent ableitet - unerreichbar für position_near_mouse). Gleiche Signatur
        und Rückgabe (Text oder None bei Abbrechen), gleiche Tastenbelegung (Enter/Escape).
        """
        if parent is None:
            parent = tk._get_default_root("Dialog anzeigen")
        with aktivitaet.warte_auf_antwort(title):
            return TextEingabeDialog.ask(parent, title, prompt, initialvalue or "")

    @staticmethod
    def position_near_mouse_auto(window, offset=20):
        """
        Wie position_near_mouse, aber ohne feste Größe: für Dialoge, die sich nach ihrem
        Inhalt bemessen (z.B. CandidatePickerDialog). update_idletasks() zwingt Tk, die
        angeforderte Größe erst zu berechnen, damit die Randbegrenzung stimmt.
        """
        window.update_idletasks()
        width = window.winfo_reqwidth()
        height = window.winfo_reqheight()
        x, y, bezug = UIUtils._anker(window, width, height, offset)
        x, y = UIUtils._begrenzt_auf_monitor(window, x, y, width, height, bezug=bezug)
        window.geometry(f"+{x}+{y}")

    @staticmethod
    def set_sort_indicator(tree, col, reverse):
        """
        Zeigt die aktuelle Sortierung als Pfeil im Spaltenkopf an (▲ aufsteigend, ▼ absteigend)
        und entfernt den Pfeil aus allen anderen Spalten. Mit col=None werden alle Pfeile gelöscht.
        """
        for c in tree["columns"]:
            base = tree.heading(c)["text"].replace(UIUtils.SORT_ASC_SUFFIX, "").replace(UIUtils.SORT_DESC_SUFFIX, "")
            tree.heading(c, text=base)
        if col is not None:
            suffix = UIUtils.SORT_DESC_SUFFIX if reverse else UIUtils.SORT_ASC_SUFFIX
            tree.heading(col, text=tree.heading(col)["text"] + suffix)

    @staticmethod
    def parse_display_date(text):
        """
        Wandelt einen Anzeige-Datumswert (DD.MM.YYYY, optional mit HH:MM) für die
        Spalten-Sortierung in ein datetime um. Leere/unparsebare Zellen sortieren als
        datetime.min ans Ende (statt wie früher die GANZE Spalte bei einem einzigen
        unlesbaren Wert auf String-Sortierung zurückfallen zu lassen).
        """
        for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y"):
            try:
                return datetime.datetime.strptime(text.strip(), fmt)
            except ValueError:
                pass
        return datetime.datetime.min

    @staticmethod
    def parse_prozent(text):
        """'92 %' -> 92; leer oder '—' -> -1 (sortiert hinter alle echten Werte)."""
        ziffern = "".join(c for c in (text or "") if c.isdigit())
        return int(ziffern) if ziffern else -1

    @staticmethod
    def sort_treeview(tree, col, reverse):
        """Sortiert die Spalten im übergebenen Treeview (Alphabetisch oder nach Datum) und aktualisiert die Sortier-Anzeige im Spaltenkopf."""
        l = [(tree.set(k, col), k) for k in tree.get_children('')]
        if col in ("datum", "scan_zeit", "erfasst"):
            l.sort(key=lambda t: UIUtils.parse_display_date(t[0]), reverse=reverse)
        elif col == "qualitaet":
            # "92 %" numerisch, "—"/leer ans Ende (bzw. bei absteigend an den Anfang)
            l.sort(key=lambda t: UIUtils.parse_prozent(t[0]), reverse=reverse)
        else:
            l.sort(key=lambda t: t[0].lower(), reverse=reverse)

        for index, (val, k) in enumerate(l):
            tree.move(k, '', index)

        UIUtils.set_sort_indicator(tree, col, reverse)

        # Klick-Event für die umgekehrte Sortierung beim nächsten Klick neu binden
        tree.heading(col, command=lambda: UIUtils.sort_treeview(tree, col, not reverse))

    @staticmethod
    def auto_resize_column(tree, col_id):
        """Passt die Spaltenbreite automatisch an den längsten Inhalt an."""
        # identify_column liefert den ANZEIGE-Index (#1 = erste sichtbare Spalte).
        # Bei ausgeblendeten Spalten (displaycolumns) muss darüber aufgelöst werden,
        # sonst würde die falsche Datenspalte angepasst.
        col_index = int(col_id.replace('#', '')) - 1
        display = tree["displaycolumns"]
        if display and display[0] != "#all":
            col_name = display[col_index]
        else:
            col_name = tree["columns"][col_index]
        if col_name == "datum": 
            return "break"
        
        font = tkfont.nametofont("TkDefaultFont")
        header_text = tree.heading(col_name)["text"].replace(UIUtils.SORT_ASC_SUFFIX, "").replace(UIUtils.SORT_DESC_SUFFIX, "")
        max_width = font.measure(header_text)
        
        for item in tree.get_children(''):
            val = tree.set(item, col_name)
            w = font.measure(str(val))
            if w > max_width:
                max_width = w

        tree.column(col_name, width=max_width + 20)


class Tooltip:
    """
    Kleiner Hinweis, der nach kurzem Verweilen des Mauszeigers neben einem Widget erscheint
    (13.09.2026, Nutzerwunsch „Platz sparen": Erklärtexte nicht mehr dauerhaft neben den
    Feldern, sondern erst bei Bedarf). `text` darf ein String oder eine Funktion sein, die
    den aktuellen Text liefert (z.B. der Zustand der KI-LED).
    """

    VERZOEGERUNG_MS = 600
    HINTERGRUND = "#ffffe0"

    def __init__(self, widget, text, verzoegerung_ms=VERZOEGERUNG_MS):
        self.widget = widget
        self._text = text
        self._verzoegerung = verzoegerung_ms
        self._timer = None
        self._fenster = None
        widget.bind("<Enter>", self._bei_eintritt, add="+")
        widget.bind("<Leave>", self._bei_austritt, add="+")
        widget.bind("<ButtonPress>", self._bei_austritt, add="+")

    def text(self):
        return self._text() if callable(self._text) else self._text

    def _bei_eintritt(self, _event=None):
        self._abbrechen()
        self._timer = self.widget.after(self._verzoegerung, self.zeige)

    def _bei_austritt(self, _event=None):
        self._abbrechen()
        self.verstecke()

    def _abbrechen(self):
        if self._timer is not None:
            try:
                self.widget.after_cancel(self._timer)
            except Exception:
                pass
            self._timer = None

    def zeige(self):
        """Hinweis unter dem Widget einblenden (Test: auch direkt aufrufbar)."""
        self._timer = None
        text = self.text()
        if not text or self._fenster is not None:
            return
        try:
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        except Exception:
            return
        self._fenster = tk.Toplevel(self.widget)
        self._fenster.overrideredirect(True)
        self._fenster.attributes("-topmost", True)
        tk.Label(self._fenster, text=text, justify="left", bg=self.HINTERGRUND,
                 relief="solid", borderwidth=1, padx=6, pady=3,
                 wraplength=UIUtils.px(self.widget, 360)).pack()
        self._fenster.geometry(f"+{x}+{y}")

    def verstecke(self):
        if self._fenster is not None:
            try:
                self._fenster.destroy()
            except Exception:
                pass
            self._fenster = None

    def sichtbar(self):
        return self._fenster is not None and bool(self._fenster.winfo_exists())


class ProgressDialog(tk.Toplevel):
    """
    Kleines, wiederverwendbares Fortschrittsfenster für Hintergrund-Batch-Läufe (z.B.
    index_manager.upgrade_to_ocr_tier) - Determinate-Fortschrittsbalken, Statuszeile und
    ein Abbrechen-Button. Der Worker-Thread aktualisiert per `self.after(0, dialog.update_progress, ...)`
    (wie im Titel-Aufräumen-Tool); `should_stop` ist als Callback für den Worker gedacht,
    er prüft es selbst zwischen Dokumenten - dieser Dialog bricht nichts von sich aus ab.
    """
    def __init__(self, parent, title, initial_text=""):
        super().__init__(parent)
        self.title(title)
        self.resizable(False, False)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self._cancelled = False
        # Zeitschätzung startet erst beim ERSTEN erledigten Dokument, nicht schon bei der
        # Dialog-Erstellung - die vorgelagerte Cache-Frische-Prüfung (siehe
        # index_manager._ensure_fulltext_baseline) hat eine eigene, ungleichmäßige Laufzeit
        # und würde die Rate sonst verfälschen.
        self._start_time = None

        UIUtils.position_near_mouse(self, UIUtils.px(self, 360), UIUtils.px(self, 120))

        self.label_var = tk.StringVar(value=initial_text)
        ttk.Label(self, textvariable=self.label_var, anchor="w").pack(padx=15, pady=(15, 5), fill=tk.X)
        self.progress = ttk.Progressbar(self, mode="determinate", maximum=100)
        self.progress.pack(padx=15, pady=5, fill=tk.X)
        self.btn_cancel = ttk.Button(self, text="Abbrechen", command=self.cancel)
        self.btn_cancel.pack(pady=(5, 15))

    def update_progress(self, done, total, text=None):
        """Für self.after(0, ...) aus einem Worker-Thread gedacht - läuft dann im Tk-Hauptthread."""
        if not self.winfo_exists():
            return
        if done > 0 and self._start_time is None:
            self._start_time = time.monotonic()
        self.progress["maximum"] = max(total, 1)
        self.progress["value"] = done
        label = text if text else f"{done} / {total}"
        if self._start_time is not None and 0 < done < total:
            rate = (time.monotonic() - self._start_time) / done
            label += f" — noch ca. {self._format_duration(rate * (total - done))}"
        self.label_var.set(label)

    @staticmethod
    def _format_duration(seconds):
        """Grobe, für eine Restzeit-Anzeige ausreichende Formatierung (keine Sekunden-Genauigkeit bei größeren Werten)."""
        seconds = int(seconds)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours} Std. {minutes} Min."
        if minutes:
            return f"{minutes} Min. {seconds} Sek."
        return f"{seconds} Sek."

    def cancel(self):
        """Merkt den Abbruch-Wunsch vor (should_stop) - der Worker beendet erst noch das gerade laufende Dokument, daher der Hinweistext statt sofortigem Schließen."""
        self._cancelled = True
        self.btn_cancel.config(state=tk.DISABLED)
        self.label_var.set("Wird abgebrochen...")

    def should_stop(self):
        return self._cancelled


class TextEingabeDialog(tk.Toplevel):
    """
    Modaler Eingabedialog (eine Zeile) als Ersatz für simpledialog.askstring - siehe
    UIUtils.ask_string. Positioniert sich per position_near_mouse_auto, damit er wie alle
    anderen Dialoge der App auf dem Monitor unter dem Mauszeiger erscheint.
    """

    def __init__(self, parent, title, prompt, initialvalue=""):
        super().__init__(parent)
        self.title(title)
        self.resizable(True, False)   # B5: waagrecht ziehbar, das Eingabefeld wächst mit (fill=X)
        self.transient(parent)
        self.ergebnis = None
        ttk.Label(self, text=prompt, anchor="w", justify=tk.LEFT, wraplength=UIUtils.px(self, 420)).pack(padx=15, pady=(12, 4), fill=tk.X)
        self.var = tk.StringVar(value=initialvalue)
        self.entry = ttk.Entry(self, textvariable=self.var, width=48)
        self.entry.pack(padx=15, pady=4, fill=tk.X)
        self._unter_der_eingabe()
        knoepfe = ttk.Frame(self)
        knoepfe.pack(pady=(6, 12))
        self.btn_ok = ttk.Button(knoepfe, text="OK", command=self._ok, width=10)
        self.btn_ok.pack(side=tk.LEFT, padx=5)
        ttk.Button(knoepfe, text="Abbrechen", command=self._abbrechen, width=10).pack(side=tk.LEFT, padx=5)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._abbrechen())
        self.protocol("WM_DELETE_WINDOW", self._abbrechen)
        UIUtils.position_near_mouse_auto(self)
        self.entry.focus_set()
        self.entry.select_range(0, tk.END)
        self.entry.icursor(tk.END)
        self._nach_aufbau()

    def _unter_der_eingabe(self):
        """Platz für Zusatzzeilen zwischen Eingabe und Knöpfen (DatumEingabeDialog)."""

    def _nach_aufbau(self):
        """Wird am Ende des Aufbaus aufgerufen (DatumEingabeDialog: erste Prüfung)."""

    def _ok(self):
        self.ergebnis = self.var.get()
        self.destroy()

    def _abbrechen(self):
        self.ergebnis = None
        self.destroy()

    @classmethod
    def ask(cls, parent, title, prompt, initialvalue="", **extra):
        """Blockiert bis zum Schließen; liefert den Text oder None (Abbrechen/Escape/Schließen)."""
        dialog = cls(parent, title, prompt, initialvalue, **extra)
        try:
            dialog.wait_visibility()
            dialog.grab_set()
        except tk.TclError:
            pass
        dialog.wait_window()
        return dialog.ergebnis


MONATE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember")
WOCHENTAGE_KURZ = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


class Monatskalender(ttk.Frame):
    """Kleiner Monatskalender zum Anklicken (B4e, Peter 21.11.2026: „einen Datumspicker ohne viel Aufwand“) - selbst
    gebaut aus `calendar` und ttk statt tkcalendar (GPL, zieht babel nach). Klick auf einen Tag ruft `waehle(date)`,
    Doppelklick zusätzlich `bestaetige(date)`; Tage nach `bis` (Vorgabe heute) sind gesperrt. «/» blättern ein
    Jahr, ‹/› einen Monat. Stile (Kalender*.TButton) in ui_theme."""

    def __init__(self, parent, waehle, bestaetige=None, bis=None):
        super().__init__(parent)
        self._waehle, self._bestaetige = waehle, bestaetige
        self._bis = bis or datetime.date.today()
        self._gewaehlt = None
        heute = datetime.date.today()
        self.jahr, self.monat = heute.year, heute.month
        kopf = ttk.Frame(self)
        kopf.pack(fill=tk.X)
        for text, schritt, hinweis in (("«", -12, "Ein Jahr zurück"), ("‹", -1, "Einen Monat zurück")):
            knopf = ttk.Button(kopf, text=text, width=3, style="Kalender.TButton",
                               command=lambda s=schritt: self.blaettern(s))
            knopf.pack(side=tk.LEFT)
            Tooltip(knopf, hinweis)
        for text, schritt, hinweis in (("»", 12, "Ein Jahr vor"), ("›", 1, "Einen Monat vor")):
            knopf = ttk.Button(kopf, text=text, width=3, style="Kalender.TButton",
                               command=lambda s=schritt: self.blaettern(s))
            knopf.pack(side=tk.RIGHT)
            Tooltip(knopf, hinweis)
        self.lbl_monat = ttk.Label(kopf, anchor="center")
        self.lbl_monat.pack(side=tk.LEFT, fill=tk.X, expand=True)
        raster = ttk.Frame(self)
        raster.pack()
        for spalte, name in enumerate(WOCHENTAGE_KURZ):
            ttk.Label(raster, text=name, anchor="center", style="KalenderKopf.TLabel").grid(
                row=0, column=spalte, sticky="ew")
        self._tage = []          # 6 Wochen x 7 Tage, Knopf -> Tag über self._tag_von
        self._tag_von = {}
        for zeile in range(6):
            for spalte in range(7):
                knopf = ttk.Button(raster, width=3, style="Kalender.TButton")
                knopf.grid(row=zeile + 1, column=spalte, padx=1, pady=1)
                knopf.bind("<Double-1>", lambda e, k=knopf: self._doppelklick(k))
                self._tage.append(knopf)
        self.zeige(self.jahr, self.monat)

    @staticmethod
    def wochen(jahr, monat):
        """Tage des Monats als Wochen Mo-So, 0 = Tag eines Nachbarmonats (leer)."""
        return calendar.Calendar(firstweekday=0).monthdayscalendar(jahr, monat)

    @staticmethod
    def verschiebe(jahr, monat, schritt):
        """(jahr, monat) um `schritt` Monate verschoben, über Jahresgrenzen hinweg."""
        index = jahr * 12 + (monat - 1) + schritt
        return index // 12, index % 12 + 1

    @staticmethod
    def darstellung(tag, gewaehlt, heute, bis):
        """(Stil, gesperrt) eines Tages: gewählt gefüllt, heute hervorgehoben, nach `bis` gesperrt."""
        if tag == gewaehlt:
            stil = "KalenderGewaehlt.TButton"
        elif tag == heute:
            stil = "KalenderHeute.TButton"
        else:
            stil = "Kalender.TButton"
        return stil, tag > bis

    def blaettern(self, schritt):
        self.zeige(*self.verschiebe(self.jahr, self.monat, schritt))

    def zeige(self, jahr, monat):
        self.jahr, self.monat = jahr, monat
        self.lbl_monat.config(text=f"{MONATE[monat - 1]} {jahr}")
        tage = [t for woche in self.wochen(jahr, monat) for t in woche]
        tage += [0] * (len(self._tage) - len(tage))
        heute = datetime.date.today()
        self._tag_von = {}
        for knopf, tag in zip(self._tage, tage):
            if not tag:
                knopf.config(text="", style="Kalender.TButton", command="")
                knopf.state(["disabled"])
                continue
            datum = datetime.date(jahr, monat, tag)
            stil, gesperrt = self.darstellung(datum, self._gewaehlt, heute, self._bis)
            knopf.config(text=str(tag), style=stil, command=lambda d=datum: self._klick(d))
            knopf.state(["disabled"] if gesperrt else ["!disabled"])
            if not gesperrt:
                self._tag_von[str(knopf)] = datum

    def markiere(self, iso):
        """Getipptes Datum ('JJJJ-MM-TT') im Kalender zeigen: blättert in seinen Monat und hebt den Tag hervor."""
        try:
            datum = datetime.date.fromisoformat(iso)
        except (TypeError, ValueError):
            return
        if datum != self._gewaehlt or (datum.year, datum.month) != (self.jahr, self.monat):
            self._gewaehlt = datum
            self.zeige(datum.year, datum.month)

    def _klick(self, datum):
        self._gewaehlt = datum
        self.zeige(datum.year, datum.month)
        self._waehle(datum)

    def _doppelklick(self, knopf):
        datum = self._tag_von.get(str(knopf))
        if datum is not None and self._bestaetige:
            self._bestaetige(datum)


class DatumEingabeDialog(TextEingabeDialog):
    """Texteingabe mit Datumsprüfung beim Tippen (UIUtils.ask_datum). Ergebnis ist das geprüfte 'JJJJ-MM-TT'."""

    HINWEIS_OK = "#1E7B1E"       # Bedeutungsfarben: grün = gültig, rot = Grund steht daneben
    HINWEIS_FEHLER = "#B00020"

    def __init__(self, parent, title, prompt, initialvalue="", pruefe=None):
        self._pruefe = pruefe
        self._datum = None
        super().__init__(parent, title, prompt, initialvalue)

    def _unter_der_eingabe(self):
        self.lbl_hinweis = ttk.Label(self, text="", anchor="w")
        self.lbl_hinweis.pack(padx=15, pady=(0, 2), fill=tk.X)
        # B4e: Kalender zum Anklicken - Klick füllt das Feld (die Prüfung läuft wie beim Tippen), Doppelklick = OK
        self.kalender = Monatskalender(self, waehle=self._aus_kalender, bestaetige=lambda _d: self._ok())
        self.kalender.pack(padx=15, pady=(2, 4))

    def _aus_kalender(self, datum):
        self.var.set(datum.strftime("%d.%m.%Y"))

    def _nach_aufbau(self):
        self.var.trace_add("write", lambda *_: self._pruefen())
        self._pruefen()

    def _pruefen(self):
        self._datum, hinweis = self._pruefe(self.var.get()) if self._pruefe else (self.var.get().strip() or None, "")
        self.lbl_hinweis.config(text=hinweis, foreground=self.HINWEIS_OK if self._datum else self.HINWEIS_FEHLER)
        self.btn_ok.state(["!disabled"] if self._datum else ["disabled"])
        if self._datum:
            self.kalender.markiere(self._datum)   # getipptes Datum im Kalender zeigen

    def _ok(self):
        if not self._datum:          # Enter bei ungültiger Eingabe: der Hinweis sagt schon, warum
            self.bell()
            return
        self.ergebnis = self._datum
        self.destroy()
