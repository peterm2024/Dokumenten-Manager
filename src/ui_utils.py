import datetime
import re
import sys
import time
import tkinter as tk
import aktivitaet
import tkinter.font as tkfont
from tkinter import ttk

class UIUtils:
    # Suffixe für die Sortier-Anzeige in den Spaltenköpfen
    SORT_ASC_SUFFIX = " ▲"
    SORT_DESC_SUFFIX = " ▼"
    _einzelfenster = {}     # Schlüssel -> offenes Werkzeugfenster (einzelfenster)

    @staticmethod
    def werkzeugfenster(fenster, hauptfenster):
        """Werkzeugfenster über KID halten, ohne modal zu sein (Peter 04.11.2026: „wieder TopMost, aber nicht modal -
        sonst verschwindet ein Fenster aus Versehen im Hintergrund und wird doppelt geöffnet“): transient zum
        Hauptfenster - bleibt darüber, verschwindet mit ihm, blockiert nichts. Kein -topmost: das läge auch über
        allen anderen Programmen."""
        try:
            fenster.transient(hauptfenster)
        except tk.TclError:
            pass

    @staticmethod
    def einzelfenster(schluessel, erzeugen):
        """Höchstens EIN offenes Fenster je Schlüssel: ist es schon offen, kommt es nach vorn statt eines zweiten
        (zwei Fenster auf denselben Daten schreiben sich sonst gegenseitig alte Stände zurück). :return: das Fenster"""
        offen = UIUtils._einzelfenster.get(schluessel)
        try:
            if offen is not None and offen.winfo_exists():
                offen.deiconify()
                offen.lift()
                offen.focus_set()
                return offen
        except tk.TclError:
            pass
        fenster = erzeugen()
        UIUtils._einzelfenster[schluessel] = fenster
        return fenster

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
        self.resizable(False, False)
        self.transient(parent)
        self.ergebnis = None
        ttk.Label(self, text=prompt, anchor="w", justify=tk.LEFT, wraplength=UIUtils.px(self, 420)).pack(padx=15, pady=(12, 4), fill=tk.X)
        self.var = tk.StringVar(value=initialvalue)
        self.entry = ttk.Entry(self, textvariable=self.var, width=48)
        self.entry.pack(padx=15, pady=4, fill=tk.X)
        knoepfe = ttk.Frame(self)
        knoepfe.pack(pady=(6, 12))
        ttk.Button(knoepfe, text="OK", command=self._ok, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(knoepfe, text="Abbrechen", command=self._abbrechen, width=10).pack(side=tk.LEFT, padx=5)
        self.bind("<Return>", lambda e: self._ok())
        self.bind("<Escape>", lambda e: self._abbrechen())
        self.protocol("WM_DELETE_WINDOW", self._abbrechen)
        UIUtils.position_near_mouse_auto(self)
        self.entry.focus_set()
        self.entry.select_range(0, tk.END)
        self.entry.icursor(tk.END)

    def _ok(self):
        self.ergebnis = self.var.get()
        self.destroy()

    def _abbrechen(self):
        self.ergebnis = None
        self.destroy()

    @staticmethod
    def ask(parent, title, prompt, initialvalue=""):
        """Blockiert bis zum Schließen; liefert den Text oder None (Abbrechen/Escape/Schließen)."""
        dialog = TextEingabeDialog(parent, title, prompt, initialvalue)
        try:
            dialog.wait_visibility()
            dialog.grab_set()
        except tk.TclError:
            pass
        dialog.wait_window()
        return dialog.ergebnis
