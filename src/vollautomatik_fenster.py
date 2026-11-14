"""
Statusfenster der Watchdog-Vollautomatik (Nutzerwunsch 31.08.2026): Solange der
Automatikmodus eingeschaltet ist, steht ein kleines, offenes Fenster mit einer
laufenden Animation auf dem Schirm - man sieht SOFORT, dass die Vollautomatik an ist.
Es zeigt den aktuellen Zustand ("Warte auf Dokumente", "Dokument 3 von 47 wird von
der KI gelesen" mit Countdown, "wird einsortiert", Ergebnis) und ZWEI Vorschaubilder
nebeneinander (Nutzerwunsch 04.09.2026): links das zuletzt fertige Dokument samt
"Abgelegt in…", rechts das gerade verarbeitete mit Countdown — vorher stand unter dem
Bild des AKTUELLEN Dokuments das Ergebnis des VORIGEN, das las sich wie eine falsche
Zuordnung.

Arbeitsteilung: auto_pilot_service (Hintergrund-Thread) meldet Ereignisse über
root.after an melde()/synchronisiere() - alles hier läuft NUR auf dem Hauptthread.
Fenster offen <=> Vollautomatik eingeschaltet: Das Schließen (X oder Knopf) schaltet
den Automatikmodus aus, das Einschalten öffnet das Fenster (synchronisiere).
"""

import io
import os
import time
import tkinter as tk
from tkinter import ttk

from pdf_handler import PDFHandler
from ui_utils import UIUtils

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:  # pragma: no cover - Pillow ist Laufzeit-Abhängigkeit
    HAS_PIL = False

CONFIG_KEY = "auto_pilot_enabled"
# Alle Maße gelten für 100 % Skalierung und werden über _px() hochgerechnet.
BASIS_BREITE = 410                 # Fensterbreite (zwei Vorschau-Spalten nebeneinander)
THUMB_BREITE = 170                 # Breite eines Vorschaubilds in Pixeln
THUMB_HOEHE = 226                  # Höhe des Vorschaubild-Felds (A4-Verhältnis)
ANIMATION_MS = 120                 # Drehgeschwindigkeit des Aktivitätsrings
COUNTDOWN_MS = 500                 # Aktualisierung der Restzeit-Anzeige
MAX_GRUND = 160                    # längere Begründungen werden für die Anzeige gekürzt


class VollautomatikFenster(tk.Toplevel):
    """Nur über synchronisiere()/melde() benutzen - siehe Modul-Docstring."""

    def __init__(self, app, ueber_kid=False):
        super().__init__(app.root)
        # Unsichtbar aufbauen, erst platzieren, dann zeigen: sonst ist das Fenster schon während des Aufbaus
        # sichtbar, Windows setzt es auf seine Standardposition (versetzt, oben links) und die eigene
        # Platzierung geht unter (gemessen 02.11.2026: berechnet +1317+745, angezeigt +264+182)
        self.withdraw()
        self.app = app
        self.title("Vollautomatik läuft")
        self._winkel = 0
        self._countdown_ende = None
        self._bild = None              # PhotoImage-Referenz (sonst räumt Tk sie weg)
        self._bild_links = None        # dito für die "Zuletzt abgelegt"-Spalte
        self._anim_id = None
        self._countdown_id = None
        self._aufgebaut = False        # erst nach der ersten Platzierung darf nachjustiert werden

        # Alle Pixelmaße mit der Bildschirm-Skalierung multiplizieren: der Beta-Tester fährt
        # 125 % Skalierung UND 125 % Schriftgröße - Tk vergrößert dann die Schrift, feste
        # Pixelwerte aber nicht, und der Text lief unten aus dem Fenster (FALLSTRICKE #42).
        self._skalierung = UIUtils.skalierung(self)
        self._breite = self._px(BASIS_BREITE)
        self._thumb_breite = self._px(THUMB_BREITE)
        self._thumb_hoehe = self._px(THUMB_HOEHE)
        umbruch = self._breite - self._px(30)
        rand = self._px(12)

        kopf = ttk.Frame(self)
        kopf.pack(fill=tk.X, padx=rand, pady=(self._px(10), self._px(4)))
        ring = self._px(26)
        self._anim = tk.Canvas(kopf, width=ring, height=ring, highlightthickness=0)
        self._anim.pack(side=tk.LEFT, padx=(0, self._px(8)))
        ttk.Label(kopf, text="Vollautomatik ist EINGESCHALTET",
                  font=("TkDefaultFont", UIUtils.schriftgroesse(self, 1), "bold"), wraplength=umbruch - ring).pack(side=tk.LEFT)

        self.status_var = tk.StringVar()
        ttk.Label(self, textvariable=self.status_var, anchor="w", justify=tk.LEFT,
                  wraplength=umbruch).pack(fill=tk.X, padx=rand)

        # Zwei Spalten (Nutzerwunsch 04.09.2026): LINKS das zuletzt fertige Dokument samt
        # "Abgelegt in…", RECHTS das gerade verarbeitete mit Fortschritt und Countdown -
        # so gehört jede Angabe sichtbar zu IHREM Bild.
        spalten_umbruch = self._thumb_breite + self._px(12)
        mitte = ttk.Frame(self)
        mitte.pack(fill=tk.X, padx=rand, pady=(self._px(6), 0))
        mitte.columnconfigure(0, weight=1, uniform="spalte")
        mitte.columnconfigure(1, weight=1, uniform="spalte")

        def _spalte(spalte_nr, titel):
            spalte = ttk.Frame(mitte)
            spalte.grid(row=0, column=spalte_nr, sticky="new",
                        padx=(0, self._px(8)) if spalte_nr == 0 else 0)
            ttk.Label(spalte, text=titel, anchor="center",
                      font=("TkDefaultFont", UIUtils.schriftgroesse(self), "bold")).pack(fill=tk.X)
            rahmen = tk.Frame(spalte, width=self._thumb_breite + self._px(12),
                              height=self._thumb_hoehe + self._px(8), bg="#f0f0f0")
            rahmen.pack(pady=(self._px(2), self._px(2)))
            rahmen.pack_propagate(False)
            thumb = tk.Label(rahmen, bg="#e4e4e4", anchor="center")
            thumb.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
            name_var = tk.StringVar()
            ttk.Label(spalte, textvariable=name_var, anchor="center",
                      foreground="gray30", wraplength=spalten_umbruch).pack(fill=tk.X)
            return spalte, thumb, name_var

        spalte_links, self._thumb_links, self.links_name_var = _spalte(0, "Zuletzt abgelegt")
        spalte_rechts, self._thumb, self.doku_var = _spalte(1, "In Arbeit")

        # Ergebnis des zuletzt abgelegten Dokuments: bleibt stehen, bis das nächste fertig
        # ist (Nutzerwunsch 31.08.2026 - man will sehen, WOHIN einsortiert wurde, und bei
        # "unsicher" auch WARUM) - jetzt direkt unter SEINEM Vorschaubild in der linken Spalte.
        self.ergebnis_var = tk.StringVar()
        self._ergebnis_label = ttk.Label(spalte_links, textvariable=self.ergebnis_var, anchor="w",
                                         justify=tk.LEFT, wraplength=spalten_umbruch)
        self._ergebnis_label.pack(fill=tk.X, pady=(self._px(2), 0))

        # Fortschritt und Countdown gehören zum Dokument in Arbeit -> rechte Spalte.
        self.fortschritt_var = tk.StringVar()
        ttk.Label(spalte_rechts, textvariable=self.fortschritt_var, anchor="center",
                  foreground="gray40").pack(fill=tk.X)
        self.countdown_var = tk.StringVar()
        ttk.Label(spalte_rechts, textvariable=self.countdown_var, anchor="center",
                  foreground="gray40").pack(fill=tk.X)

        ttk.Button(self, text="Vollautomatik ausschalten",
                   command=self._ausschalten).pack(side=tk.BOTTOM, pady=(self._px(6), self._px(10)))

        self.protocol("WM_DELETE_WINDOW", self._ausschalten)
        self.melde("warten")
        self._passe_groesse_an(am_mauszeiger=True, ueber_kid=ueber_kid)
        self.deiconify()
        # Sichtbar bleiben, aber nichts blockieren: kein grab_set (nicht modal), dafür
        # dauerhaft im Vordergrund - sonst verschwindet der Automatik-Hinweis hinter dem
        # Hauptfenster und man glaubt, es läuft nichts (Nutzerwunsch 31.08.2026).
        self.attributes("-topmost", True)
        self.lift()
        self._animiere()
        self._tick_countdown()

    def _px(self, wert):
        """Rechnet einen bei 100 % gedachten Pixelwert auf die tatsächliche Skalierung um."""
        return int(round(wert * self._skalierung))

    def _passe_groesse_an(self, am_mauszeiger=False, ueber_kid=False):
        """Fenster auf die wirklich benötigte Höhe bringen (nur wachsen, nie springen).

        Die Ergebniszeile ist mal zwei-, mal vierzeilig und bei großer Schrift deutlich
        höher — eine feste Fenstergröße schnitt sie unten ab (FALLSTRICKE #42).
        """
        if not (am_mauszeiger or self._aufgebaut):
            return          # vor der ersten Platzierung gibt es noch keine gültige Geometrie
        self.update_idletasks()
        hoehe = self.winfo_reqheight()
        if am_mauszeiger:
            UIUtils.position_near_mouse(self, self._breite, hoehe, ueber_kid=ueber_kid)
            self._aufgebaut = True
        elif hoehe > self.winfo_height():
            # Bezug ist der eigene Ort, nicht die Maus - sonst sprang das Fenster beim Wachsen auf den Monitor,
            # auf dem man gerade in einem anderen Programm arbeitet (Peter 02.11.2026)
            x, y = UIUtils._begrenzt_auf_monitor(self, self.winfo_x(), self.winfo_y(), self._breite, hoehe,
                                                 bezug=(self.winfo_x() + self._breite // 2, self.winfo_y() + 10))
            self.geometry(f"{self._breite}x{hoehe}+{x}+{y}")

    # ------------------------------------------------------------------ Zustände
    def melde(self, ereignis, pfad=None, nummer=None, gesamt=None, schaetzung=None, text=None,
              ziel=None, grund=None, details=None):
        """Zustandswechsel anzeigen (NUR vom Hauptthread; der Dienst geht über root.after)."""
        if not self.winfo_exists():
            return
        if ereignis == "warten":
            self.status_var.set("Warte auf neue Dokumente im Posteingang…")
            self.fortschritt_var.set("")
            self._countdown_ende = None
        elif ereignis == "runde":
            self.status_var.set(f"{gesamt} Dokument(e) im Posteingang erkannt.")
        elif ereignis == "analyse":
            self.status_var.set("Dokument wird von der KI gelesen…")
            if nummer and gesamt:
                self.fortschritt_var.set(f"Dokument {nummer} von {gesamt}")
            self._countdown_ende = time.monotonic() + (schaetzung or 30.0)
            self._zeige_dokument(pfad)
        elif ereignis in ("zweitmeinung", "ablage"):
            # Stapelbetrieb je Modell (28.10.2026): nach dem Lesen eines Stapels kommen erst die
            # Zweitmeinungen, dann die Ablagen - das Bild zeigt jeweils das Dokument dieser Phase
            self.status_var.set("Zweitmeinung zur Ordnerwahl…" if ereignis == "zweitmeinung"
                                else "Wird geprüft und einsortiert…")
            if nummer and gesamt:
                self.fortschritt_var.set(f"Dokument {nummer} von {gesamt}")
            self._countdown_ende = None
            self.countdown_var.set("")
            self._zeige_dokument(pfad)
        elif ereignis == "einsortieren":
            self.status_var.set("Wird einsortiert…")
            self._countdown_ende = None
            self.countdown_var.set("")
        elif ereignis == "fertig":
            self.status_var.set(text or "Fertig.")
            self._countdown_ende = None
            self.countdown_var.set("")
            # Das erledigte Dokument wandert mitsamt Bild von "In Arbeit" nach
            # "Zuletzt abgelegt" - das Ergebnis steht so unter SEINEM Vorschaubild.
            self._uebernimm_links(pfad, ziel, grund)
            self._zeige_dokument(None)
        elif ereignis == "server_weg":
            self.status_var.set("KI-Server nicht erreichbar – Dokumente bleiben im Posteingang. "
                                "Nächster Versuch in ca. 1 Minute.")
            self.fortschritt_var.set("")
            self._countdown_ende = None
            self.countdown_var.set("")
        elif ereignis == "gpu_weg":
            # FALLSTRICKE #67: Server erreichbar, aber ohne Grafikkarte - jeder Aufruf
            # würde Minuten dauern. Pausieren und den Menschen auf den Server verweisen.
            self.status_var.set("KI-Server rechnet ohne Grafikkarte (viel zu langsam) – Dokumente bleiben "
                                "im Posteingang. Bitte den Server prüfen (nvidia-smi, ggf. VM neu starten). "
                                "Nächster Versuch in ca. 1 Minute.")
            self.fortschritt_var.set(details or "")
            self._countdown_ende = None
            self.countdown_var.set("")
        # Jeder Text kann mehrzeilig werden (lange Dateinamen, große Schrift) — Fenster
        # danach auf die benötigte Höhe nachziehen, damit nichts unten abgeschnitten wird.
        self._passe_groesse_an()

    def _zeige_dokument(self, pfad):
        """Vorschaubild des gerade bearbeiteten Dokuments — mit pfad=None wird das Feld geleert."""
        self.doku_var.set(os.path.basename(pfad) if pfad else "")
        if not pfad:
            self._bild = None
            self._thumb.config(image="", text="")
            return
        if not HAS_PIL:
            return
        try:
            png = PDFHandler.render_page_png(pfad, dpi=int(40 * self._skalierung))
            bild = Image.open(io.BytesIO(png))
            faktor = min(self._thumb_breite / bild.width, self._thumb_hoehe / bild.height)
            bild = bild.resize((max(1, int(bild.width * faktor)), max(1, int(bild.height * faktor))))
            self._bild = ImageTk.PhotoImage(bild)
            self._thumb.config(image=self._bild, text="")
        except Exception:
            self._thumb.config(image="", text="(keine Vorschau)")

    def _uebernimm_links(self, pfad, ziel, grund):
        """
        Erledigtes Dokument in die "Zuletzt abgelegt"-Spalte übernehmen: Das schon
        gerenderte Vorschaubild der "In Arbeit"-Spalte wird weitergereicht (kein
        zweites Rendern); fehlt es (Fenster mitten im Lauf geöffnet), wird aus dem
        Pfad nachgerendert - der zeigt nach dem Verschieben aber meist ins Leere,
        dann bleibt das Feld eben leer.
        """
        if not ziel:
            return   # nichts abgelegt (Fehlerfall) - die Meldung steht schon oben im Status
        if self._bild is not None:
            self._bild_links = self._bild
            self._thumb_links.config(image=self._bild_links, text="")
        elif pfad and HAS_PIL:
            try:
                png = PDFHandler.render_page_png(pfad, dpi=int(40 * self._skalierung))
                bild = Image.open(io.BytesIO(png))
                faktor = min(self._thumb_breite / bild.width, self._thumb_hoehe / bild.height)
                bild = bild.resize((max(1, int(bild.width * faktor)), max(1, int(bild.height * faktor))))
                self._bild_links = ImageTk.PhotoImage(bild)
                self._thumb_links.config(image=self._bild_links, text="")
            except Exception:
                self._thumb_links.config(image="", text="(keine Vorschau)")
        self.links_name_var.set(self.doku_var.get() or os.path.basename(pfad or ""))
        self._zeige_ergebnis(ziel, grund)

    def _zeige_ergebnis(self, ziel, grund):
        """Hält fest, wohin das zuletzt bearbeitete Dokument gewandert ist (und warum unsicher)."""
        ordner = os.path.dirname(ziel) or "(Hauptordner)"
        neuer_name = os.path.basename(ziel)
        if grund and len(grund) > MAX_GRUND:
            grund = grund[:MAX_GRUND].rstrip() + "…"   # Fenster nicht sprengen
        if grund:
            self.ergebnis_var.set(f"⚠ Unsicher – abgelegt in:\n{ordner}\nals: {neuer_name}\nGrund: {grund}")
            self._ergebnis_label.configure(foreground="#b06000")
        else:
            self.ergebnis_var.set(f"✓ Abgelegt in:\n{ordner}\nals: {neuer_name}")
            self._ergebnis_label.configure(foreground="#2f7d32")

    # ------------------------------------------------------------------ Laufende Timer
    def _animiere(self):
        """Drehender Ring als Lebenszeichen - das war der ausdrückliche Wunsch: auf einen Blick sehen, dass es läuft."""
        if not self.winfo_exists():
            return
        self._winkel = (self._winkel + 25) % 360
        self._anim.delete("all")
        self._anim.create_oval(3, 3, 23, 23, outline="#d0d0d0", width=3)
        self._anim.create_arc(3, 3, 23, 23, start=-self._winkel, extent=100,
                              style=tk.ARC, outline="#2f7d32", width=3)
        self._anim_id = self.after(ANIMATION_MS, self._animiere)

    def _tick_countdown(self):
        if not self.winfo_exists():
            return
        if self._countdown_ende is not None:
            rest = self._countdown_ende - time.monotonic()
            if rest > 0:
                self.countdown_var.set(f"KI-Antwort: noch ca. {int(rest) + 1} s")
            else:
                self.countdown_var.set("KI braucht etwas länger als geschätzt…")
        self._countdown_id = self.after(COUNTDOWN_MS, self._tick_countdown)

    # ------------------------------------------------------------------ Aus
    def destroy(self):
        """Laufende Timer abbestellen — sonst meldet Tk nach dem Schließen 'invalid command name'."""
        for kennung in (self._anim_id, self._countdown_id):
            if kennung:
                try:
                    self.after_cancel(kennung)
                except Exception:
                    pass
        self._anim_id = self._countdown_id = None
        super().destroy()

    def _ausschalten(self):
        """Fenster zu = Vollautomatik aus (die eine, für Senioren verständliche Regel)."""
        try:
            self.app.config.set(CONFIG_KEY, False)
        except Exception:
            pass
        dienst = getattr(self.app, "auto_pilot_service", None)
        if dienst is not None:
            dienst.anstossen()
        self.destroy()


def zuruecktreten(app, ja):
    """Solange das Mail-Fenster offen ist, liegt das Statusfenster nicht obenauf, sonst verdeckt es dessen Knöpfe (Abnahme
    06.11.2026). Danach wieder im Vordergrund, siehe __init__."""
    fenster = getattr(app, "vollautomatik_fenster", None)
    if fenster is not None and fenster.winfo_exists():
        fenster.attributes("-topmost", not ja)


def synchronisiere(app, beim_start=False):
    """Fenster öffnen/schließen, passend zur Einstellung (NUR vom Hauptthread aufrufen). `beim_start`: KID öffnet
    das Fenster von sich aus - dann über dem Hauptfenster statt am Mauszeiger (UIUtils._anker)."""
    try:
        aktiv = bool(app.config.get(CONFIG_KEY, False))
    except Exception:
        return
    fenster = getattr(app, "vollautomatik_fenster", None)
    offen = fenster is not None and fenster.winfo_exists()
    if aktiv and not offen:
        root = getattr(app, "root", None)
        if root is not None and not root.winfo_viewable():
            # Beim Programmstart erst, wenn das Hauptfenster steht - vorher kennt Tk seine Größe nicht, und das
            # Fenster könnte sich nicht „über KID“ öffnen, falls man schon in ein anderes Programm gewechselt ist
            root.after(200, lambda: synchronisiere(app, beim_start))
            return
        app.vollautomatik_fenster = VollautomatikFenster(app, ueber_kid=beim_start)
    elif not aktiv and offen:
        fenster.destroy()


def melde(app, ereignis, **daten):
    """Ereignis ans Fenster durchreichen, falls es offen ist (NUR vom Hauptthread aufrufen)."""
    fenster = getattr(app, "vollautomatik_fenster", None)
    if fenster is not None and fenster.winfo_exists():
        fenster.melde(ereignis, **daten)
