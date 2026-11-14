"""
Fernsteuerung für interaktive Tests (Entwickler-Werkzeug, kein Teil der App/EXE).

Nutzerwunsch 25.10.2026: Statt einer langen Checkliste steuert Claude die App selbst,
prüft, was sich prüfen lässt, und fragt Peter nur nach dem, was ein Mensch beurteilen
muss (ruckelt es, ist es lesbar, fühlt es sich richtig an).

    python fernsteuerung.py start                 App starten und auf Befehle warten
    python fernsteuerung.py start schrift125      dasselbe, simuliert 125 % Skalierung + Textgröße
    python fernsteuerung.py start vollautomatik   dasselbe, Vollautomatik bleibt an (Betatest: Neustart im Betrieb)
    python fernsteuerung.py hinweis "Text"        Hinweisfenster: Peter bestätigt mit „Los"
    python fernsteuerung.py fertig ["Text"]       Steuerung zurückgeben
    python fernsteuerung.py frage "Text" Ja Nein  Frage im Fenster, wartet auf die Antwort
    python fernsteuerung.py py "Ausdruck"         Python im Tk-Thread (app, root, Helfer)
    python fernsteuerung.py foto Datei.png        Hauptfenster fotografieren
    python fernsteuerung.py klick X Y [rechts|doppelt|""] [ctrl|shift|alt …]
    python fernsteuerung.py bewege X Y            Maus nur hinbewegen (Verweilen, z.B. Menü-Erklärung)
    python fernsteuerung.py ziehe X1 Y1 X2 Y2 [alt]
    python fernsteuerung.py rad X Y Schritte [ctrl]  (negativ = nach unten, ctrl = Zoom)
    python fernsteuerung.py tasten ctrl+a         Tastenkombination
    python fernsteuerung.py tippe "Text"
    python fernsteuerung.py beenden

Sicherheit:
- Läuft nur mit der Test-Sammlung KID-Test und einer KOPIE der settings.json im
  Arbeitsordner `.fernsteuerung/` - Peters Einstellungen bleiben unangetastet.
- Maus und Tastatur werden nur übernommen, nachdem Peter im Hinweisfenster „Los"
  geklickt hat. „Stopp" oder eine Mausbewegung von Peter hält sofort an.
- Befehle nur über 127.0.0.1 und mit einem Zufalls-Token aus `.fernsteuerung/token.txt`.

Eingaben laufen über die Windows-Schnittstelle (SetCursorPos/SendInput), also wie
echte Maus und Tastatur - inklusive Drag & Drop, Alt-Taste und Mausrad. Sie werden im
App-Prozess erzeugt, damit Bildschirmkoordinaten von Tk und Windows zusammenpassen.
"""

import json
import os
import queue
import secrets
import shutil
import socket
import socketserver
import sys
import threading
import time

PROJEKT = os.path.dirname(os.path.abspath(__file__))
ARBEITSORDNER = os.path.join(PROJEKT, ".fernsteuerung")
TOKEN_DATEI = os.path.join(ARBEITSORDNER, "token.txt")
TESTORDNER = os.path.join(os.path.expanduser("~"), "KID-Test")
PORT = 47811
MAUS_TOLERANZ = 3          # Pixel: mehr Abweichung = Peter hat die Maus bewegt -> anhalten
HINWEIS_BREITE, HINWEIS_HOEHE = 420, 230

# ---------------------------------------------------------------- reine Funktionen (testbar)
VK = {
    "ctrl": 0x11, "strg": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
    "return": 0x0D, "enter": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20, "leer": 0x20,
    "backspace": 0x08, "delete": 0x2E, "entf": 0x2E, "insert": 0x2D, "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pagedown": 0x22, "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "plus": 0xBB, "minus": 0xBD,
    **{f"f{i}": 0x6F + i for i in range(1, 13)},
}
# Tasten, die Windows als "erweitert" sendet (sonst landen Pfeile/Entf u.U. auf dem Ziffernblock)
ERWEITERT = {0x2E, 0x2D, 0x24, 0x23, 0x21, 0x22, 0x26, 0x28, 0x25, 0x27}


def zerlege_tasten(kombination):
    """'ctrl+shift+a' -> [VK_CONTROL, VK_SHIFT, 'A']: Modifikatoren zuerst gedrückt, zuletzt losgelassen."""
    codes = []
    for teil in kombination.lower().replace(" ", "").split("+"):
        if not teil:
            raise ValueError(f"Leerer Teil in {kombination!r}")
        if teil in VK:
            codes.append(VK[teil])
        elif len(teil) == 1 and (teil.isalpha() or teil.isdigit()):
            codes.append(ord(teil.upper()))
        else:
            raise ValueError(f"Unbekannte Taste {teil!r} in {kombination!r}")
    return codes


def ist_testsammlung(pfad):
    """Nur die Test-Sammlung darf ferngesteuert werden (schrägstrich- und großschreibungsneutral)."""
    if not pfad:
        return False
    return os.path.normcase(os.path.normpath(pfad)) == os.path.normcase(os.path.normpath(TESTORDNER))


def fokus_zurueckgeben(vorher, jetzt, eigen):
    """Hat sich das eben gestartete KID den Fokus genommen, den vorher ein anderes Programm hatte? (Peter 08.11.2026:
    „klau mir nicht den Fokus“ - er tippte woanders weiter, und weil KID danach als aktiv galt, öffnete sich das
    nächste Werkzeugfenster an seinem Mauszeiger statt über KID, UIUtils._anker.) Werte = Prozess-ID des
    Vordergrundfensters, 0 = keines."""
    return bool(vorher) and vorher != eigen and jetzt == eigen


def _vordergrund():
    """(Fenster-Handle, Prozess-ID) des Vordergrundfensters; (0, 0) außerhalb von Windows."""
    if sys.platform != "win32":
        return 0, 0
    import ctypes
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    pid = ctypes.c_ulong()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return hwnd, pid.value


def _fokus_nicht_klauen(root, vorher, nachlauf=8):
    """Gibt den Fokus einmal an das Fenster zurück, das ihn vor dem Start hatte, falls das erste Zeigen des
    Hauptfensters ihn genommen hat. Geprüft wird nur kurz nach dem Erscheinen (nachlauf × 250 ms), damit ein späterer
    Klick in KID nicht zurückgedreht wird."""
    def pruefen(rest):
        _hwnd, pid = _vordergrund()
        if fokus_zurueckgeben(vorher[1], pid, os.getpid()):
            import ctypes
            ctypes.windll.user32.SetForegroundWindow(vorher[0])
            return
        if not root.winfo_viewable():
            root.after(250, pruefen, rest)          # noch nicht zu sehen: weiter warten
        elif rest:
            root.after(250, pruefen, rest - 1)
    root.after(250, pruefen, nachlauf)


def maus_bewegt(erwartet, aktuell, toleranz=MAUS_TOLERANZ):
    """Hat jemand anderes die Maus bewegt? (erwartet = zuletzt von uns gesetzte Position)"""
    if erwartet is None:
        return False
    return abs(erwartet[0] - aktuell[0]) > toleranz or abs(erwartet[1] - aktuell[1]) > toleranz


TITELLEISTE = 40   # Windows-Titelleiste + Rahmen: geometry() setzt nur die Innengröße


def knopf_zeilen(breiten, verfuegbar, abstand=8):
    """
    Knöpfe gierig auf Zeilen verteilen (Indizes je Zeile), damit nichts rechts abgeschnitten wird
    (Nutzerfund 25.10.2026: fünf Antworten + Abbrechen passten nicht in eine Zeile).
    """
    zeilen, breite = [], 0
    for i, b in enumerate(breiten):
        if zeilen and breite + abstand + b <= verfuegbar:
            zeilen[-1].append(i)
            breite += abstand + b
        else:
            zeilen.append([i])
            breite = b
    return zeilen


def simuliere_grosse_schrift(root, faktor=1.25):
    """
    Bildet den Tester-PC nach (Skalierung 125 % UND Textgröße 125 %, FALLSTRICKE #42/#69), wie der
    Rauchtest von damals: Tk rechnet mit 120 dpi und alle Tk-Schriften werden um den Faktor größer
    (9 pt → 11 pt). Nötig, weil Python/EXE nicht DPI-fähig sind - Windows meldet ihnen 96 dpi und
    vergrößert das Fenster nur als Bild, und die Textgröße kam bei der Systemschrift gar nicht an
    (Release-Check T0.16, 25.10.2026). Muss VOR dem Aufbau der Oberfläche laufen.
    """
    import tkinter.font as tkfont
    root.tk.call("tk", "scaling", 96 * faktor / 72)
    for name in tkfont.names(root):
        schrift = tkfont.nametofont(name, root=root)
        schrift.configure(size=round(schrift.cget("size") * faktor))


def hinweis_position(app, monitor, breite=HINWEIS_BREITE, hoehe=HINWEIS_HOEHE, abstand=24, andere=()):
    """
    Wo das Hinweisfenster hin soll, ohne die App zu verdecken: rechts neben die App, sonst
    links daneben, sonst auf einen anderen Monitor (``andere``, unten rechts), sonst unten
    rechts in die Ecke des App-Monitors. Rechtecke = (links, oben, rechts, unten). Die
    Titelleiste kommt zur Innenhöhe dazu - ohne sie ragte das Fenster unten aus dem
    Bildschirm (Nutzerfund 25.10.2026: „leicht abgeschnitten").
    """
    ml, mo, mr, mu = monitor
    al, ao, ar, au = app
    hoehe += TITELLEISTE
    if ar <= ml or al >= mr or au <= mo or ao >= mu:
        # App liegt nicht auf diesem Monitor (z.B. minimiert bei -32000): sichere Ecke statt „daneben"
        return mr - breite - abstand, mu - hoehe - abstand
    y = max(mo, min(ao, mu - hoehe))
    if ar + abstand + breite <= mr:
        return ar + abstand, y
    if al - abstand - breite >= ml:
        return al - abstand - breite, y
    for ol, oo, orr, ou in andere:   # Peter hat zwei Monitore: dort verdeckt es nichts (Nutzerfund 25.10.2026)
        if orr - ol >= breite + 2 * abstand and ou - oo >= hoehe + 2 * abstand:
            return orr - breite - abstand, ou - hoehe - abstand
    return mr - breite - abstand, mu - hoehe - abstand


# ---------------------------------------------------------------- Windows-Eingabe
def _win():
    import ctypes
    from ctypes import wintypes

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    class _U(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _U)]

    return ctypes, wintypes, INPUT, MOUSEINPUT, KEYBDINPUT


class Eingabe:
    """Echte Maus-/Tastatureingaben über SetCursorPos und SendInput."""
    LINKS_RUNTER, LINKS_HOCH, RECHTS_RUNTER, RECHTS_HOCH, RAD = 0x0002, 0x0004, 0x0008, 0x0010, 0x0800
    TASTE_HOCH, ERWEITERT_FLAG, UNICODE = 0x0002, 0x0001, 0x0004

    def __init__(self):
        self.ctypes, self.wintypes, self.INPUT, self.MOUSEINPUT, self.KEYBDINPUT = _win()
        self.user32 = self.ctypes.windll.user32

    def position(self):
        p = self.wintypes.POINT()
        self.user32.GetCursorPos(self.ctypes.byref(p))
        return p.x, p.y

    def setze(self, x, y):
        self.user32.SetCursorPos(int(x), int(y))

    def _sende(self, *eingaben):
        feld = (self.INPUT * len(eingaben))(*eingaben)
        self.user32.SendInput(len(eingaben), feld, self.ctypes.sizeof(self.INPUT))

    def _maus(self, flags, daten=0):
        e = self.INPUT(type=0)
        e.u.mi = self.MOUSEINPUT(0, 0, daten & 0xFFFFFFFF, flags, 0, 0)
        return e

    def _taste(self, vk, hoch=False, scan=0, unicode=False):
        flags = (self.TASTE_HOCH if hoch else 0) | (self.UNICODE if unicode else 0)
        if not unicode and vk in ERWEITERT:
            flags |= self.ERWEITERT_FLAG
        e = self.INPUT(type=1)
        e.u.ki = self.KEYBDINPUT(0 if unicode else vk, scan, flags, 0, 0)
        return e

    def klick(self, x, y, rechts=False, doppelt=False, tasten=()):
        """Klick an (x, y); ``tasten`` (z.B. ["ctrl"] für Strg+Klick) werden dabei gehalten."""
        mods = [VK[t] for t in tasten]
        self.setze(x, y)
        time.sleep(0.08)
        for vk in mods:
            self._sende(self._taste(vk))
        runter, hoch = (self.RECHTS_RUNTER, self.RECHTS_HOCH) if rechts else (self.LINKS_RUNTER, self.LINKS_HOCH)
        for _ in range(2 if doppelt else 1):
            self._sende(self._maus(runter))
            time.sleep(0.04)
            self._sende(self._maus(hoch))
            time.sleep(0.06)
        for vk in reversed(mods):
            self._sende(self._taste(vk, hoch=True))

    def ziehe(self, x1, y1, x2, y2, tasten=(), schritte=25):
        mods = [VK[t] for t in tasten]
        self.setze(x1, y1)
        time.sleep(0.1)
        self._sende(self._maus(self.LINKS_RUNTER))
        time.sleep(0.15)
        for i in range(1, schritte + 1):
            self.setze(x1 + (x2 - x1) * i / schritte, y1 + (y2 - y1) * i / schritte)
            time.sleep(0.02)
            if i == schritte // 2:
                for vk in mods:   # Modifikator erst unterwegs drücken - wie ein Mensch, der Alt dazunimmt
                    self._sende(self._taste(vk))
        time.sleep(0.3)
        self._sende(self._maus(self.LINKS_HOCH))
        time.sleep(0.1)
        for vk in reversed(mods):
            self._sende(self._taste(vk, hoch=True))

    def rad(self, x, y, schritte, tasten=()):
        """Mausrad an (x, y); positiv = nach oben. ``tasten`` (z.B. ["ctrl"]) werden dabei gehalten."""
        mods = [VK[t] for t in tasten]
        self.setze(x, y)
        time.sleep(0.08)
        for vk in mods:
            self._sende(self._taste(vk))
        richtung = 1 if schritte > 0 else -1
        for _ in range(abs(int(schritte))):
            self._sende(self._maus(self.RAD, 120 * richtung))
            time.sleep(0.12)
        for vk in reversed(mods):
            self._sende(self._taste(vk, hoch=True))

    def tasten(self, kombination):
        codes = zerlege_tasten(kombination)
        for vk in codes:
            self._sende(self._taste(vk))
            time.sleep(0.03)
        for vk in reversed(codes):
            self._sende(self._taste(vk, hoch=True))
            time.sleep(0.03)

    def tippe(self, text):
        for zeichen in text:
            self._sende(self._taste(0, scan=ord(zeichen), unicode=True),
                        self._taste(0, hoch=True, scan=ord(zeichen), unicode=True))
            time.sleep(0.02)


# ---------------------------------------------------------------- Server im App-Prozess
class Steuerung:
    def __init__(self, root, app):
        self.root = root
        self.app = app
        self.eingabe = Eingabe()
        self.auftraege = queue.Queue()
        self.freigabe = False          # True nur nach „Los" im Hinweisfenster
        self.letzte_pos = None
        self.fenster = None            # aktuelles Hinweis-/Fragefenster
        self.namensraum = {"app": app, "root": root, "os": os, "time": time}
        self.namensraum.update(mitte=self._mitte, zeile=self._zeile, finde=self._finde)
        self.root.after(30, self._abarbeiten)

    # ---------- Tk-Thread
    def _abarbeiten(self):
        try:
            while True:
                fn, fertig, ergebnis = self.auftraege.get_nowait()
                try:
                    ergebnis["wert"] = fn()
                except Exception as e:   # Fehler an den Aufrufer zurückgeben, App läuft weiter
                    ergebnis["fehler"] = f"{type(e).__name__}: {e}"
                fertig.set()
        except queue.Empty:
            pass
        self.root.after(30, self._abarbeiten)

    def im_tk(self, fn, timeout=60):
        fertig, ergebnis = threading.Event(), {}
        self.auftraege.put((fn, fertig, ergebnis))
        if not fertig.wait(timeout):
            raise TimeoutError("Tk-Thread antwortet nicht (modaler Dialog offen?)")
        if "fehler" in ergebnis:
            raise RuntimeError(ergebnis["fehler"])
        return ergebnis.get("wert")

    # ---------- Helfer für `py`
    def _mitte(self, widget, dx=None, dy=None):
        """Bildschirmkoordinaten eines Widgets: Mitte, oder Versatz dx/dy von links oben."""
        widget.update_idletasks()
        x = widget.winfo_rootx() + (widget.winfo_width() // 2 if dx is None else dx)
        y = widget.winfo_rooty() + (widget.winfo_height() // 2 if dy is None else dy)
        return [x, y]

    def _zeile(self, tree, iid, spalte="#0"):
        """Bildschirmkoordinaten der Mitte einer Treeview-Zeile (die Zeile muss sichtbar sein)."""
        tree.see(iid)
        tree.update_idletasks()
        box = tree.bbox(iid, spalte) or tree.bbox(iid)
        if not box:
            raise ValueError(f"Zeile {iid} nicht sichtbar")
        x, y, b, h = box
        return [tree.winfo_rootx() + x + min(b // 2, 120), tree.winfo_rooty() + y + h // 2]

    def _finde(self, tree, text, eltern=""):
        """Erste Zeile (rekursiv), deren Text oder Werte `text` enthalten."""
        for iid in tree.get_children(eltern):
            werte = " ".join(str(v) for v in tree.item(iid, "values"))
            if text in tree.item(iid, "text") or text in werte:
                return iid
            gefunden = self._finde(tree, text, iid)
            if gefunden:
                return gefunden
        return None

    # ---------- Fenster für Peter
    def _app_rechteck(self):
        self.root.update_idletasks()
        x, y = self.root.winfo_rootx(), self.root.winfo_rooty()
        return x, y, x + self.root.winfo_width(), y + self.root.winfo_height()

    def _monitore(self):
        """(Arbeitsbereich des App-Monitors, [Arbeitsbereiche der anderen Monitore])."""
        try:
            ctypes, wintypes = _win()[:2]

            class MONITORINFO(ctypes.Structure):
                _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                            ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

            def arbeitsbereich(mon):
                info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
                ctypes.windll.user32.GetMonitorInfoW(mon, ctypes.byref(info))
                r = info.rcWork
                return r.left, r.top, r.right, r.bottom

            hwnd = int(self.root.wm_frame(), 16)
            eigener = ctypes.windll.user32.MonitorFromWindow(hwnd, 2)
            alle = []
            RUECKRUF = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p,
                                          ctypes.POINTER(wintypes.RECT), ctypes.c_void_p)
            ctypes.windll.user32.EnumDisplayMonitors(None, None, RUECKRUF(lambda m, *_: alle.append(m) or 1), None)
            andere = [arbeitsbereich(m) for m in alle if m != eigener]
            return arbeitsbereich(eigener), andere
        except Exception:
            return (0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()), []

    def _fenster(self, titel, farbe, text, knoepfe, eingabe=False):
        """Baut das (einzige) Hinweis-/Fragefenster neu. knoepfe = [(Beschriftung, Rückruf)]."""
        import tkinter as tk
        if self.fenster is not None and self.fenster.winfo_exists():
            self.fenster.destroy()
        if self.root.state() == "iconic":
            # Minimierte App: Windows meldet sie bei x = -32000 - das Fenster landete unsichtbar
            # weit links (Nutzerfund 25.10.2026: „ich seh das Fenster nicht"). Peter soll die App
            # bei Hinweis und Frage ohnehin sehen - also wiederherstellen.
            self.root.deiconify()
        w = tk.Toplevel(self.root)
        w.title(titel)
        w.configure(bg=farbe)
        w.attributes("-topmost", True)
        w.resizable(False, False)
        tk.Label(w, text=titel, bg=farbe, font=("Segoe UI", 12, "bold"), anchor="w").pack(fill=tk.X, padx=12, pady=(10, 4))
        tk.Label(w, text=text, bg=farbe, font=("Segoe UI", 10), justify=tk.LEFT, anchor="nw",
                 wraplength=HINWEIS_BREITE - 30).pack(fill=tk.BOTH, expand=True, padx=12)
        feld = None
        if eingabe:
            tk.Label(w, text="Notiz (optional):", bg=farbe, font=("Segoe UI", 9), anchor="w").pack(fill=tk.X, padx=12)
            # Drei Zeilen mit Umbruch (Peter 01.11.2026: lange Notizen liefen in der einzeiligen Zeile aus dem Blick)
            feld = tk.Text(w, font=("Segoe UI", 10), height=3, wrap=tk.WORD)
            feld.pack(fill=tk.X, padx=12, pady=(0, 6))
        leiste = tk.Frame(w, bg=farbe)
        leiste.pack(fill=tk.X, padx=12, pady=(4, 10))
        knoepfe_w = [tk.Button(leiste, text=beschriftung, font=("Segoe UI", 10), padx=10, command=rueckruf)
                     for beschriftung, rueckruf in knoepfe]
        for zeile in knopf_zeilen([k.winfo_reqwidth() for k in knoepfe_w], HINWEIS_BREITE - 24):
            reihe = tk.Frame(leiste, bg=farbe)
            reihe.pack(fill=tk.X, pady=(0, 6))
            for i in zeile:
                knoepfe_w[i].pack(in_=reihe, side=tk.LEFT, padx=(0, 8))
                knoepfe_w[i].lift(reihe)   # Knopf entstand vor dem Rahmen - sonst läge er verdeckt darunter
        w.protocol("WM_DELETE_WINDOW", knoepfe[-1][1])   # Schließen = letzter Knopf (Stopp/Abbrechen)
        # Höhe nach dem Inhalt (Nutzerfund 25.10.2026: fest 230 px schnitt den Stopp-Knopf ab)
        w.update_idletasks()
        hoehe = max(HINWEIS_HOEHE, w.winfo_reqheight())
        monitor, andere = self._monitore()
        x, y = hinweis_position(self._app_rechteck(), monitor, HINWEIS_BREITE, hoehe, andere=andere)
        w.geometry(f"{HINWEIS_BREITE}x{hoehe}+{x}+{y}")
        self.fenster = w
        return w, feld

    def hinweis(self, text):
        """Peter bitten, loszulassen; blockiert, bis er „Los" oder „Stopp" klickt."""
        entscheidung, fertig = {}, threading.Event()

        def wahl(wert):
            entscheidung["wert"] = wert
            fertig.set()

        self.freigabe = False
        self.im_tk(lambda: self._fenster(
            "Claude möchte die Steuerung übernehmen", "#fff3cd",
            f"Als Nächstes: {text}\n\nBitte Maus und Tastatur dann nicht benutzen, bis hier „Fertig“ steht. "
            "Mit „Stopp“ oder einer Mausbewegung halte ich sofort an.",
            [("Los – ich lasse los", lambda: wahl("los")), ("Stopp / noch nicht", lambda: wahl("stopp"))]))
        fertig.wait()
        if entscheidung["wert"] != "los":
            self.im_tk(self._zeige_angehalten)
            return "stopp"
        self.im_tk(lambda: self._zeige_steuert(text))
        time.sleep(1.0)   # Zeit, die Hand von der Maus zu nehmen
        self.letzte_pos = self.eingabe.position()
        self.freigabe = True
        return "los"

    def _zeige_steuert(self, text):
        def stopp():
            self.freigabe = False
            self._zeige_angehalten()
        self._fenster("Claude steuert – bitte Hände weg", "#ffe0b2",
                      f"{text}\n\nMaus und Tastatur bitte nicht benutzen.", [("Stopp", stopp)])
        self.root.lift()
        self.root.focus_force()

    def _zeige_angehalten(self, grund="Angehalten."):
        self.freigabe = False
        self._fenster("Angehalten", "#f8d7da", f"{grund}\n\nDu hast wieder die Kontrolle. Claude fragt nach, "
                      "bevor es weitergeht.", [("OK", lambda: self.fenster.destroy())])

    def fertig(self, text=""):
        self.freigabe = False

        def zeigen():
            w, _ = self._fenster("Fertig", "#d4edda", (text + "\n\n" if text else "") +
                                 "Du kannst Maus und Tastatur wieder benutzen.", [("OK", lambda: w.destroy())])
            w.after(4000, lambda: w.winfo_exists() and w.destroy())
        self.im_tk(zeigen)
        return "fertig"

    def frage(self, text, antworten):
        """Frage an Peter im Fenster; blockiert bis zur Antwort. Liefert {antwort, notiz}."""
        self.freigabe = False
        antwort, fertig = {}, threading.Event()

        def bauen():
            def wahl(wert):
                antwort["antwort"] = wert
                antwort["notiz"] = feld.get("1.0", "end").strip()
                w.destroy()
                fertig.set()
            knoepfe = [(a, lambda a=a: wahl(a)) for a in antworten] + [("Abbrechen", lambda: wahl("(abgebrochen)"))]
            w, feld = self._fenster("Frage von Claude", "#e7f0fb", text + "\n\nDu darfst dafür Maus und Tastatur benutzen.",
                                    knoepfe, eingabe=True)
        self.im_tk(bauen)
        fertig.wait()
        return antwort

    # ---------- Eingaben (nur mit Freigabe)
    def _eingabe(self, fn):
        if not self.freigabe:
            raise PermissionError("Keine Freigabe - erst `hinweis` und Peters „Los“ abwarten")
        if maus_bewegt(self.letzte_pos, self.eingabe.position()):
            self.freigabe = False
            self.im_tk(lambda: self._zeige_angehalten("Du hast die Maus bewegt - ich habe sofort angehalten."))
            raise PermissionError("Peter hat die Maus bewegt - angehalten")
        fn()
        self.letzte_pos = self.eingabe.position()
        time.sleep(0.4)   # der App Zeit geben, das Ereignis zu verarbeiten und zu zeichnen
        return {"maus": self.letzte_pos}

    # ---------- sonstiges
    def py(self, code):
        def ausfuehren():
            try:
                return repr(eval(code, self.namensraum))
            except SyntaxError:
                exec(code, self.namensraum)
                return repr(self.namensraum.get("ergebnis"))
        text = self.im_tk(ausfuehren)
        return text if len(text) < 6000 else text[:6000] + " …(gekürzt)"

    def foto(self, pfad):
        def knipsen():
            import ctypes
            from ctypes import wintypes
            from PIL import ImageGrab
            self.root.update()
            hwnd = int(self.root.wm_frame(), 16)
            r = wintypes.RECT()
            ctypes.windll.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r))
            bild = ImageGrab.grab(bbox=(r.left, r.top, r.right, r.bottom), all_screens=True)
            bild.save(pfad)
            return pfad
        return self.im_tk(knipsen)

    def ausfuehren(self, befehl, args):
        e = self.eingabe
        if befehl == "ping":
            return "pong"
        if befehl == "hinweis":
            return self.hinweis(args[0])
        if befehl == "fertig":
            return self.fertig(args[0] if args else "")
        if befehl == "frage":
            return self.frage(args[0], args[1:] or ["Ja", "Nein"])
        if befehl == "py":
            return self.py(args[0])
        if befehl == "foto":
            return self.foto(os.path.abspath(args[0]))
        if befehl == "klick":
            art = args[2] if len(args) > 2 else ""   # "", "rechts" oder "doppelt"; danach Modifikatoren
            return self._eingabe(lambda: e.klick(int(args[0]), int(args[1]), rechts=art == "rechts",
                                                 doppelt=art == "doppelt", tasten=args[3:]))
        if befehl == "ziehe":
            x1, y1, x2, y2 = (int(a) for a in args[:4])
            return self._eingabe(lambda: e.ziehe(x1, y1, x2, y2, tasten=args[4:]))
        if befehl == "rad":
            return self._eingabe(lambda: e.rad(int(args[0]), int(args[1]), int(args[2]), tasten=args[3:]))
        if befehl == "tasten":
            return self._eingabe(lambda: e.tasten(args[0]))
        if befehl == "tippe":
            return self._eingabe(lambda: e.tippe(args[0]))
        if befehl == "bewege":
            return self._eingabe(lambda: e.setze(int(args[0]), int(args[1])))
        if befehl == "beenden":
            self.freigabe = False
            self.root.after(200, self.app.on_closing)
            return "beendet"
        raise ValueError(f"Unbekannter Befehl {befehl!r}")


def einstellungen_ableiten(echt, kopie, vollautomatik=False):
    """Einstellungen der Fernsteuerung: die Kopie bleibt (Fenster, Spalten, Testzustand), beim ersten Start von Peters
    Einstellungen abgeleitet. Die KI-Einstellungen (`ki_*`, `ollama_*`) kommen bei JEDEM Start frisch aus Peters
    settings.json - 03.11.2026 weckte die Kopie den Server mit der alten VM-MAC und las mit einem anderen Modell."""
    echt = echt or {}
    einstellungen = dict(kopie) if kopie is not None else dict(echt)
    einstellungen.update({k: v for k, v in echt.items() if k.startswith(("ki_", "ollama_"))})
    einstellungen.update({"master_folder": TESTORDNER.replace("\\", "/"), "show_help_on_start": False,
                          "versionspruefung_beim_start": False, "auto_pilot_enabled": vollautomatik})
    return einstellungen


def _starte(token, grosse_schrift=False, vollautomatik=False):
    """Arbeitsordner mit Einstellungs-KOPIE vorbereiten, App starten, Befehls-Server öffnen."""
    # Dieselbe Sammlungssperre wie main.py (einzelstart.py), VOR allem anderen: Beim Release-Check v0.9.26 liefen kurz
    # Peters EXE und das ferngesteuerte KID zugleich auf KID-Test, weil hier `gui` direkt startet.
    sys.path.insert(0, os.path.join(PROJEKT, "src"))
    import einzelstart
    if not einzelstart.belege(TESTORDNER):
        sys.exit(f"ABBRUCH: {TESTORDNER} ist schon offen (EXE oder zweite Fernsteuerung) - dort erst schließen.")
    os.makedirs(ARBEITSORDNER, exist_ok=True)
    quelle = os.path.join(PROJEKT, "settings.json")
    ziel = os.path.join(ARBEITSORDNER, "settings.json")
    echt = kopie = None
    for pfad in (quelle, ziel):
        if os.path.exists(pfad):
            with open(pfad, encoding="utf-8") as f:
                if pfad == quelle:
                    echt = json.load(f)
                else:
                    kopie = json.load(f)
    einstellungen = einstellungen_ableiten(echt, kopie, vollautomatik)
    with open(ziel, "w", encoding="utf-8") as f:
        json.dump(einstellungen, f, ensure_ascii=False, indent=2)
    for vorlage in ("tags_default.json", "folder_default.json"):
        shutil.copyfile(os.path.join(PROJEKT, vorlage), os.path.join(ARBEITSORDNER, vorlage))
    os.chdir(ARBEITSORDNER)

    import tkinter as tk
    import gui
    vorher = _vordergrund()                      # wer den Fokus hatte - meist Peters Editor
    root = tk.Tk()
    _fokus_nicht_klauen(root, vorher)
    if grosse_schrift:
        simuliere_grosse_schrift(root)
    app = gui.DokumentenVerwaltung(root)
    if not ist_testsammlung(getattr(app, "master_folder", "")):
        root.destroy()
        sys.exit(f"ABBRUCH: Hauptordner ist nicht {TESTORDNER} - Fernsteuerung nur mit der Test-Sammlung.")
    steuerung = Steuerung(root, app)

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                anfrage = json.loads(self.rfile.readline().decode("utf-8"))
                if anfrage.get("token") != token:
                    raise PermissionError("Falsches Token")
                antwort = {"ok": True, "wert": steuerung.ausfuehren(anfrage["befehl"], anfrage.get("args", []))}
            except Exception as e:
                antwort = {"ok": False, "fehler": f"{type(e).__name__}: {e}"}
            self.wfile.write((json.dumps(antwort, ensure_ascii=False) + "\n").encode("utf-8"))

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer(("127.0.0.1", PORT), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    with open(TOKEN_DATEI, "w", encoding="utf-8") as f:
        f.write(token)
    print(f"Fernsteuerung bereit auf 127.0.0.1:{PORT} (Sammlung {TESTORDNER})", flush=True)
    try:
        root.mainloop()
    finally:
        server.shutdown()
        if os.path.exists(TOKEN_DATEI):
            os.remove(TOKEN_DATEI)
        print("Fernsteuerung beendet", flush=True)


def _sende(befehl, args):
    with open(TOKEN_DATEI, encoding="utf-8") as f:
        token = f.read().strip()
    with socket.create_connection(("127.0.0.1", PORT), timeout=3600) as s:
        s.sendall((json.dumps({"token": token, "befehl": befehl, "args": args}) + "\n").encode("utf-8"))
        daten = b""
        while not daten.endswith(b"\n"):
            stueck = s.recv(65536)
            if not stueck:
                break
            daten += stueck
    return json.loads(daten.decode("utf-8"))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "start":
        _starte(secrets.token_hex(16), grosse_schrift="schrift125" in sys.argv[2:],
                vollautomatik="vollautomatik" in sys.argv[2:])
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        antwort = _sende(sys.argv[1], sys.argv[2:])
        print(json.dumps(antwort, ensure_ascii=False))
        sys.exit(0 if antwort.get("ok") else 1)
