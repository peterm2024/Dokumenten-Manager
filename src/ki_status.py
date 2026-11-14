"""
Verbindungsanzeige für den KI-Server (Nutzerwunsch 13.09.2026): Bei einem Beta-Tester war der Server
aus, ein KI-Werkzeug lief trotzdem los und blieb ohne Hinweis stehen. Seitdem prüft ein
Hintergrund-Thread regelmäßig, ob der Ollama-Server antwortet, eine LED in der Suchleiste
zeigt den Zustand, und der ToolManager sperrt die Menüeinträge aller Werkzeuge, die den
Server brauchen (`BaseTool.braucht_ki`), solange er nicht erreichbar ist.

Warum eine LED im Fenster und nicht in der Menüleiste: Die Windows-Menüleiste zeichnet
das System - Bilder erscheinen dort als „(Image)", Farben und Emojis werden grau
(Spike 13.09.2026). Ein kleines Canvas in der Suchleiste kann dagegen wirklich grün/rot.

Arbeitsteilung: `KiStatus` (Logik + Thread, testbar über `pruefe_einmal`) meldet Änderungen
über `root.after` an Abonnenten; `KiLed` (Tk) ist ein Abonnent. Die Prüfung selbst ist ein
`GET /api/tags` mit kurzem Timeout - nie im Tk-Thread.

Wecken (01.11.2026): Doppelklick auf die rote LED schickt ein Wake-on-LAN-Paket an die MAC aus der
Einstellung `ki_wol_mac` (server_wecken.py). Bis der Server antwortet, leuchtet die LED orange und der
Thread prüft alle WECK_TAKT Sekunden statt alle 20 s; nach WECK_DAUER gibt er auf (LED wieder rot,
Tooltip nennt den gescheiterten Versuch).
"""

import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import ollama_client
import server_wecken
from ui_utils import Tooltip

PRUEF_INTERVALL = 20.0        # Sekunden zwischen zwei Prüfungen
PRUEF_TIMEOUT = 3.0           # Sekunden, die eine Prüfung höchstens wartet
FARBE_VERBUNDEN = "#2ecc40"
FARBE_GETRENNT = "#ff4136"
FARBE_UNBEKANNT = "#b0b0b0"
FARBE_WECKT = "#ff9f1a"
EINSTELLUNG_MAC = "ki_wol_mac"
WECK_DAUER = 180.0            # so lange wird nach dem Wecken auf den Server gewartet (gemessen: ~40 s)
WECK_TAKT = 5.0               # Prüfabstand während des Weckens
# Kurz gehalten: die Suchleiste ist bei 1400 px Fensterbreite schon gut gefüllt
TEXTE = {True: "KI verbunden", False: "KI nicht erreichbar", None: "KI: prüfe…"}


class KiStatus:
    """Hält den letzten Prüfstand (`erreichbar`: True/False/None = noch nicht geprüft) und benachrichtigt Abonnenten."""

    def __init__(self, app, intervall=PRUEF_INTERVALL, timeout=PRUEF_TIMEOUT):
        self.app = app
        self.intervall = intervall
        self.timeout = timeout
        self.erreichbar = None
        self.weckt = False
        self.weckversuch_gescheitert = False
        self._weck_ende = 0.0
        self._abonnenten = []
        self._stop = threading.Event()
        self._jetzt = threading.Event()
        self._thread = None

    # ------------------------------------------------------------------ Abonnenten
    def abonniere(self, fn):
        """fn(erreichbar) wird im Tk-Thread bei jeder Änderung gerufen - und sofort einmal mit dem aktuellen Stand."""
        self._abonnenten.append(fn)
        try:
            fn(self.erreichbar)
        except Exception:
            pass

    def _benachrichtige(self):
        for fn in list(self._abonnenten):
            try:
                fn(self.erreichbar)
            except Exception as e:
                self._log("warning", f"KI-Status: Abonnent fehlgeschlagen: {e}")

    # ------------------------------------------------------------------ Prüfung
    def url(self):
        try:
            return self.app.config.get("ollama_url", ollama_client.DEFAULT_URL)
        except Exception:
            return ollama_client.DEFAULT_URL

    def pruefe_einmal(self):
        """Eine Prüfung (blockierend, für Thread und Tests). Liefert True, wenn sich der Stand geändert hat."""
        neu = bool(ollama_client.is_reachable(self.url(), timeout=self.timeout))
        geaendert = self.setze(neu)
        if self.weckt and (neu or time.monotonic() > self._weck_ende):
            self.weckt = False
            self.weckversuch_gescheitert = not neu
            if not neu:
                self._log("warning", f"KI-Server nach {WECK_DAUER:.0f} s nicht aufgewacht (Wake-on-LAN).")
            self._auf_hauptthread(self._benachrichtige)
        return geaendert

    def setze(self, erreichbar):
        """Stand von außen setzen (z.B. Ergebnis eines Verbindungstests); benachrichtigt bei Änderung."""
        erreichbar = None if erreichbar is None else bool(erreichbar)
        if erreichbar == self.erreichbar:
            return False
        vorher = self.erreichbar
        self.erreichbar = erreichbar
        if vorher is not None or erreichbar is False:
            self._log("info" if erreichbar else "warning",
                      f"KI-Server {self.url()} {'wieder erreichbar' if erreichbar else 'nicht erreichbar'}"
                      + ("" if erreichbar else " - KI-Werkzeuge im Menü gesperrt."))
        self._auf_hauptthread(self._benachrichtige)
        return True

    def pruefe_jetzt(self):
        """Nächste Prüfung sofort (z.B. nach Änderung der Server-Adresse)."""
        self._jetzt.set()

    # ------------------------------------------------------------------ Wecken
    def mac(self):
        try:
            return server_wecken.mac_normalisieren(self.app.config.get(EINSTELLUNG_MAC, ""))
        except Exception:
            return None

    def wecke(self):
        """Wake-on-LAN-Paket schicken und in den Weck-Modus gehen. Liefert "laeuft" (Server antwortet schon),
        "keine_mac", "weckt" (Versuch läuft bereits), "gesendet" oder "fehler: …"."""
        if self.erreichbar:
            return "laeuft"
        mac = self.mac()
        if not mac:
            return "keine_mac"
        if self.weckt:
            return "weckt"
        try:
            server_wecken.sende(mac)
        except OSError as e:
            self._log("warning", f"Wake-on-LAN an {mac} fehlgeschlagen: {e}")
            return f"fehler: {e}"
        self._log("info", f"Wake-on-LAN an {mac} gesendet, warte bis {WECK_DAUER:.0f} s auf den KI-Server.")
        self.weckt = True
        self.weckversuch_gescheitert = False
        self._weck_ende = time.monotonic() + WECK_DAUER
        self._auf_hauptthread(self._benachrichtige)
        self._jetzt.set()
        return "gesendet"

    def wecken_per_klick(self):
        """Doppelklick auf die LED (Tk-Thread): wecken und nur bei Problemen eine Meldung zeigen."""
        ergebnis = self.wecke()
        if ergebnis == "keine_mac":
            messagebox.showinfo("KI-Server wecken",
                                "Zum Aufwecken braucht KID die MAC-Adresse der Netzwerkkarte des Server-PCs.\n\n"
                                "Datei → Einstellungen… → Reiter „KI-Server“ → „Wecken (MAC)“.")
        elif ergebnis.startswith("fehler"):
            messagebox.showwarning("KI-Server wecken", f"Das Weck-Signal ließ sich nicht senden:\n{ergebnis[8:]}")
        return ergebnis

    # ------------------------------------------------------------------ Thread
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._schleife, name="KI-Status", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._jetzt.set()

    def _schleife(self):
        while not self._stop.is_set():
            try:
                self.pruefe_einmal()
            except Exception as e:
                self._log("warning", f"KI-Status: Prüfung fehlgeschlagen: {e}")
            self._jetzt.wait(WECK_TAKT if self.weckt else self.intervall)
            self._jetzt.clear()

    # ------------------------------------------------------------------ Helfer
    def _auf_hauptthread(self, fn):
        root = getattr(self.app, "root", None)
        try:
            root.after(0, fn)
        except Exception:
            fn()

    def _log(self, stufe, text):
        logger = getattr(self.app, "logger", None)
        if logger is not None:
            try:
                getattr(logger, stufe, logger.info)(text)
            except Exception:
                pass


class KiLed(ttk.Frame):
    """
    Farbpunkt für die Suchleiste; der Text („KI verbunden" / „KI nicht erreichbar" /
    „KI: prüfe…") erscheint als Tooltip beim Verweilen (Peter 13.09.2026: Platz sparen).
    """

    def __init__(self, master, durchmesser=14, **kw):
        super().__init__(master, **kw)
        self._d = durchmesser
        self._canvas = tk.Canvas(self, width=durchmesser + 2, height=durchmesser + 2,
                                 highlightthickness=0, bd=0)
        self._punkt = self._canvas.create_oval(1, 1, durchmesser + 1, durchmesser + 1,
                                               fill=FARBE_UNBEKANNT, outline="#666666")
        self._canvas.pack(side=tk.LEFT)
        self.zustand = None
        self.status = None           # KiStatus, für Weck-Zustand und MAC (verbinde)
        self.tooltip = Tooltip(self._canvas, self.text)

    def verbinde(self, status):
        """An einen KiStatus hängen: Anzeige abonnieren, Doppelklick weckt den Server."""
        self.status = status
        self._canvas.bind("<Double-Button-1>", lambda e: status.wecken_per_klick())
        status.abonniere(self.zeige)

    def zeige(self, erreichbar):
        """Abonnenten-Funktion für KiStatus."""
        self.zustand = erreichbar
        if self.status is not None and self.status.weckt and not erreichbar:
            farbe = FARBE_WECKT
        else:
            farbe = {True: FARBE_VERBUNDEN, False: FARBE_GETRENNT}.get(erreichbar, FARBE_UNBEKANNT)
        self._canvas.itemconfigure(self._punkt, fill=farbe)

    def text(self):
        """Zustand in Worten (Tooltip, Tests)."""
        s = self.status
        if s is not None and s.weckt and not self.zustand:
            return "KI-Server wird geweckt…"
        text = TEXTE.get(self.zustand, TEXTE[None])
        if self.zustand is False and s is not None:
            if s.weckversuch_gescheitert:
                text += " - Wecken hat nicht geklappt"
            text += " (Doppelklick: Server wecken)" if s.mac() else ""
        return text
