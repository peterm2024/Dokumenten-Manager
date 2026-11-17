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

Dokumente nur kurz zeigen (Etappe 10, KONZEPT_DIENSTMODUS F1-F3, Peter 17.11.2026): Vorschaubild, Dateiname,
Zielordner, neuer Name und Grund eines Dokuments sind höchstens `anzeigedauer` Sekunden zu sehen, gerechnet ab dem
ersten Erscheinen im Fenster; danach steht dort nur noch „✓ abgelegt“ bzw. „⚠ unsicher“. Ring, Zustand und der
Zähler „Heute: … abgelegt, … unsicher“ bleiben immer sichtbar. Einstellungen: `vollautomatik_anzeigedauer` mit
Oberfläche (Standard: nie ausblenden, wie bisher), `dienst_anzeigedauer` im Dienstmodus (Standard 30 s), 0 = gar
nicht zeigen; `dienst_fenster_faktor` vergrößert das Fenster im Dienstmodus (Standard 1,5-fach).

Arbeitsteilung: auto_pilot_service (Hintergrund-Thread) meldet Ereignisse über
root.after an melde()/synchronisiere() - alles hier läuft NUR auf dem Hauptthread.
Fenster offen <=> Vollautomatik eingeschaltet: Das Schließen (X oder Knopf) schaltet
den Automatikmodus aus, das Einschalten öffnet das Fenster (synchronisiere).
"""

import io
import os
import time
import tkinter as tk
from tkinter import messagebox, ttk

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

# Dokumente nur kurz zeigen (Etappe 10)
EINSTELLUNG_DAUER = "vollautomatik_anzeigedauer"       # mit Oberfläche; None = nie ausblenden
EINSTELLUNG_DAUER_DIENST = "dienst_anzeigedauer"       # im Dienstmodus
EINSTELLUNG_FAKTOR = "dienst_fenster_faktor"           # Fenstergröße im Dienstmodus
DAUER_DIENST_STANDARD = 30
FAKTOR_STANDARD = 1.5
# Auswahl in den Einstellungen (Text, Wert) - None = nie ausblenden, 0 = nie zeigen
DAUER_WAHL = (("nie ausblenden", None), ("gar nicht zeigen", 0), ("10 Sekunden", 10), ("30 Sekunden", 30),
              ("1 Minute", 60), ("2 Minuten", 120), ("5 Minuten", 300))
FAKTOR_WAHL = (("normal", 1.0), ("1,25-fach", 1.25), ("1,5-fach", 1.5), ("2-fach", 2.0))
AUSGEBLENDET_FARBE = "#d8d8d8"


def anzeigedauer(config, dienst):
    """Sekunden, die ein Dokument im Fenster zu sehen ist; None = nie ausblenden. Unbrauchbare Werte -> Standard."""
    schluessel, standard = ((EINSTELLUNG_DAUER_DIENST, DAUER_DIENST_STANDARD) if dienst else (EINSTELLUNG_DAUER, None))
    try:
        wert = config.get(schluessel, standard)
    except Exception:
        return standard
    if wert is None:
        return None
    try:
        wert = int(wert)
    except (TypeError, ValueError):
        return standard
    return wert if wert >= 0 else standard


def fenster_faktor(config):
    """Vergrößerung des Statusfensters im Dienstmodus, begrenzt auf 1- bis 3-fach."""
    try:
        return min(3.0, max(1.0, float(config.get(EINSTELLUNG_FAKTOR, FAKTOR_STANDARD))))
    except (TypeError, ValueError, AttributeError):
        return FAKTOR_STANDARD


def restzeit(dauer, erst_gesehen, jetzt):
    """Wie lange darf ein Dokument noch zu sehen sein? None = unbegrenzt, 0 = gar nicht mehr."""
    if dauer is None:
        return None
    return max(0.0, dauer - (jetzt - erst_gesehen))


def zaehler_text(abgelegt, unsicher, letzte_runde=None):
    """Zählerzeile ohne Inhalte: „Heute: 3 abgelegt, 1 unsicher · zuletzt nachgesehen 14:32“."""
    text = f"Heute: {abgelegt} abgelegt, {unsicher} unsicher"
    if letzte_runde is not None:
        text += f" · zuletzt nachgesehen {letzte_runde:%H:%M}"
    return text


class VollautomatikFenster(tk.Toplevel):
    """Nur über synchronisiere()/melde() benutzen - siehe Modul-Docstring."""

    def __init__(self, app, ueber_kid=False):
        super().__init__(app.root)
        # Unsichtbar aufbauen, erst platzieren, dann zeigen: sonst ist das Fenster schon während des Aufbaus
        # sichtbar, Windows setzt es auf seine Standardposition (versetzt, oben links) und die eigene
        # Platzierung geht unter (gemessen 02.11.2026: berechnet +1317+745, angezeigt +264+182)
        self.withdraw()
        self.app = app
        # Dienstmodus (dienstmodus.py): einziges Fenster von KID - mittig, eigener Titel, „Dienst beenden“, größer
        self._dienst = bool(getattr(app, "dienstmodus", False))
        self._faktor = fenster_faktor(app.config) if self._dienst else 1.0
        self.title("KID – Hintergrund-Automatik" if self._dienst else "Vollautomatik läuft")
        self._winkel = 0
        self._countdown_ende = None
        self._bild = None              # PhotoImage-Referenz (sonst räumt Tk sie weg)
        self._bild_links = None        # dito für die "Zuletzt abgelegt"-Spalte
        self._anim_id = None
        self._countdown_id = None
        self._aufgebaut = False        # erst nach der ersten Platzierung darf nachjustiert werden
        self._erst_gesehen = {}        # Pfad -> time.monotonic() des ersten Erscheinens (Ausblenden nach Zeit)
        self._pfad_rechts = None       # Dokument der "In Arbeit"-Spalte
        self._ausblenden_ids = {}      # Spalte -> after-Kennung des geplanten Ausblendens
        self._links_sicher = True      # Ergebnis des Dokuments in der linken Spalte (für den Platzhalter)

        # Alle Pixelmaße mit der Bildschirm-Skalierung multiplizieren: der Beta-Tester fährt
        # 125 % Skalierung UND 125 % Schriftgröße - Tk vergrößert dann die Schrift, feste
        # Pixelwerte aber nicht, und der Text lief unten aus dem Fenster (FALLSTRICKE #42).
        self._skalierung = UIUtils.skalierung(self) * self._faktor
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
        ttk.Label(kopf, text="Hintergrund-Automatik läuft" if self._dienst else "Vollautomatik ist EINGESCHALTET",
                  font=self._schrift(1, fett=True), wraplength=umbruch - ring).pack(side=tk.LEFT)

        self.status_var = tk.StringVar()
        ttk.Label(self, textvariable=self.status_var, anchor="w", justify=tk.LEFT,
                  wraplength=umbruch, **self._schrift_kw()).pack(fill=tk.X, padx=rand)
        # Zähler ohne Inhalte (Etappe 10): steht er still, obwohl Post kam, sieht man das
        self.zaehler_var = tk.StringVar()
        ttk.Label(self, textvariable=self.zaehler_var, anchor="w", foreground="gray35",
                  wraplength=umbruch, **self._schrift_kw()).pack(fill=tk.X, padx=rand, pady=(self._px(2), 0))

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
            ttk.Label(spalte, text=titel, anchor="center", font=self._schrift(0, fett=True)).pack(fill=tk.X)
            rahmen = tk.Frame(spalte, width=self._thumb_breite + self._px(12),
                              height=self._thumb_hoehe + self._px(8), bg="#f0f0f0")
            rahmen.pack(pady=(self._px(2), self._px(2)))
            rahmen.pack_propagate(False)
            thumb = tk.Label(rahmen, bg="#e4e4e4", anchor="center")
            thumb.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)
            name_var = tk.StringVar()
            ttk.Label(spalte, textvariable=name_var, anchor="center",
                      foreground="gray30", wraplength=spalten_umbruch, **self._schrift_kw()).pack(fill=tk.X)
            return spalte, thumb, name_var

        spalte_links, self._thumb_links, self.links_name_var = _spalte(0, "Zuletzt abgelegt")
        spalte_rechts, self._thumb, self.doku_var = _spalte(1, "In Arbeit")

        # Ergebnis des zuletzt abgelegten Dokuments: bleibt stehen, bis das nächste fertig
        # ist (Nutzerwunsch 31.08.2026 - man will sehen, WOHIN einsortiert wurde, und bei
        # "unsicher" auch WARUM) - jetzt direkt unter SEINEM Vorschaubild in der linken Spalte.
        self.ergebnis_var = tk.StringVar()
        self._ergebnis_label = ttk.Label(spalte_links, textvariable=self.ergebnis_var, anchor="w",
                                         justify=tk.LEFT, wraplength=spalten_umbruch, **self._schrift_kw())
        self._ergebnis_label.pack(fill=tk.X, pady=(self._px(2), 0))

        # Fortschritt und Countdown gehören zum Dokument in Arbeit -> rechte Spalte.
        self.fortschritt_var = tk.StringVar()
        ttk.Label(spalte_rechts, textvariable=self.fortschritt_var, anchor="center",
                  foreground="gray40", **self._schrift_kw()).pack(fill=tk.X)
        self.countdown_var = tk.StringVar()
        ttk.Label(spalte_rechts, textvariable=self.countdown_var, anchor="center",
                  foreground="gray40", **self._schrift_kw()).pack(fill=tk.X)

        ttk.Button(self, text="Dienst beenden" if self._dienst else "Vollautomatik ausschalten",
                   command=self._ausschalten).pack(side=tk.BOTTOM, pady=(self._px(6), self._px(10)),
                                                   ipadx=self._px(6) if self._dienst else 0,
                                                   ipady=self._px(4) if self._dienst else 0)

        self.protocol("WM_DELETE_WINDOW", self._ausschalten)
        self.melde("warten")
        self._zeige_zaehler()
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

    def _schrift(self, delta=0, fett=False):
        """Schrift, die mit der Windows-Textgröße und im Dienstmodus mit dem Fensterfaktor wächst."""
        groesse = int(round(UIUtils.schriftgroesse(self, delta) * self._faktor))
        return ("TkDefaultFont", groesse, "bold") if fett else ("TkDefaultFont", groesse)

    def _schrift_kw(self):
        """Schrift für normale Textzeilen: ohne Vergrößerung die Standardschrift wie bisher (kein font-Argument)."""
        return {"font": self._schrift()} if self._faktor != 1.0 else {}

    def _passe_groesse_an(self, am_mauszeiger=False, ueber_kid=False):
        """Fenster auf die wirklich benötigte Höhe bringen (nur wachsen, nie springen).

        Die Ergebniszeile ist mal zwei-, mal vierzeilig und bei großer Schrift deutlich
        höher — eine feste Fenstergröße schnitt sie unten ab (FALLSTRICKE #42).
        """
        if not (am_mauszeiger or self._aufgebaut):
            return          # vor der ersten Platzierung gibt es noch keine gültige Geometrie
        self.update_idletasks()
        hoehe = self.winfo_reqheight()
        if am_mauszeiger and self._dienst:
            # Dienstmodus: kein Hauptfenster, an dem man sich ausrichten könnte - mittig auf den Hauptbildschirm
            x = max(0, (self.winfo_screenwidth() - self._breite) // 2)
            y = max(0, (self.winfo_screenheight() - hoehe) // 2)
            self.geometry(f"{self._breite}x{hoehe}+{x}+{y}")
            self._aufgebaut = True
        elif am_mauszeiger:
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
            self.status_var.set(self._ohne_namen(text or "Fertig.", pfad))
            self._countdown_ende = None
            self.countdown_var.set("")
            # Das erledigte Dokument wandert mitsamt Bild von "In Arbeit" nach
            # "Zuletzt abgelegt" - das Ergebnis steht so unter SEINEM Vorschaubild.
            self._uebernimm_links(pfad, ziel, grund)
            self._zeige_dokument(None)
            self._zeige_zaehler()
        elif ereignis == "fremd":
            # Posteingang wird von einem KID auf einem anderen Rechner überwacht (posteingang_sperre.py)
            self.status_var.set(text or "Diesen Posteingang überwacht ein anderes KID - hier pausiert die Automatik.")
            self.fortschritt_var.set("")
            self._countdown_ende = None
            self.countdown_var.set("")
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

    # ------------------------------------------------------------------ Dokumente nur kurz zeigen
    def _dauer(self):
        return anzeigedauer(self.app.config, self._dienst)

    def _rest(self, pfad):
        """Restliche Anzeigezeit dieses Dokuments (None = unbegrenzt); merkt sich das erste Erscheinen."""
        if not pfad:
            return 0.0
        jetzt = time.monotonic()
        return restzeit(self._dauer(), self._erst_gesehen.setdefault(pfad, jetzt), jetzt)

    def _ohne_namen(self, text, pfad):
        """Statuszeile mit Dateinamen („Ablage fehlgeschlagen: x.pdf“): bei abgelaufener Anzeigezeit ohne den Namen."""
        name = os.path.basename(pfad) if pfad else ""
        if name and name in text and self._rest(pfad) == 0:
            return text.replace(name, "ein Dokument")
        return text

    def _plane_ausblenden(self, spalte, rest, ausblenden):
        """Ausblenden einer Spalte nach `rest` Sekunden einplanen (eine geplante Aktion je Spalte)."""
        alt = self._ausblenden_ids.pop(spalte, None)
        if alt:
            try:
                self.after_cancel(alt)
            except Exception:
                pass
        if rest is not None:
            self._ausblenden_ids[spalte] = self.after(int(rest * 1000) + 50, ausblenden)

    def _blende_rechts_aus(self):
        """„In Arbeit“: Bild und Name weg, das Dokument wird weiter bearbeitet (Fortschritt bleibt)."""
        self._ausblenden_ids.pop("rechts", None)
        if not self.winfo_exists():
            return
        self.doku_var.set("")
        self._thumb.config(image="", text="in Arbeit" if self._pfad_rechts else "", bg=AUSGEBLENDET_FARBE,
                           font=self._schrift(2, fett=True))

    def _blende_links_aus(self, sicher=None):
        """„Zuletzt abgelegt“: nur noch ✓ abgelegt / ⚠ unsicher, ohne Bild, Name, Ordner und Grund."""
        self._ausblenden_ids.pop("links", None)
        if not self.winfo_exists():
            return
        if sicher is None:
            sicher = self._links_sicher
        self._bild_links = None
        self.links_name_var.set("")
        self._thumb_links.config(image="", text="✓ abgelegt" if sicher else "⚠ unsicher", bg=AUSGEBLENDET_FARBE,
                                 fg="#2f7d32" if sicher else "#b06000", font=self._schrift(2, fett=True))
        self.ergebnis_var.set("")

    def _zeige_zaehler(self):
        dienst = getattr(self.app, "auto_pilot_service", None)
        if dienst is None or not hasattr(dienst, "zaehler_heute"):
            self.zaehler_var.set("")
            return
        try:
            abgelegt, unsicher = dienst.zaehler_heute()
            self.zaehler_var.set(zaehler_text(abgelegt, unsicher, getattr(dienst, "letzte_runde", None)))
        except Exception:
            self.zaehler_var.set("")

    # ------------------------------------------------------------------ Vorschaubilder
    def _render(self, pfad):
        png = PDFHandler.render_page_png(pfad, dpi=int(40 * self._skalierung))
        bild = Image.open(io.BytesIO(png))
        faktor = min(self._thumb_breite / bild.width, self._thumb_hoehe / bild.height)
        bild = bild.resize((max(1, int(bild.width * faktor)), max(1, int(bild.height * faktor))))
        return ImageTk.PhotoImage(bild)

    def _zeige_dokument(self, pfad):
        """Vorschaubild des gerade bearbeiteten Dokuments — mit pfad=None wird das Feld geleert."""
        self._pfad_rechts = pfad
        if not pfad:
            self._plane_ausblenden("rechts", None, None)
            self._bild = None
            self.doku_var.set("")
            self._thumb.config(image="", text="", bg="#e4e4e4", font="TkDefaultFont")
            return
        rest = self._rest(pfad)
        if rest == 0:
            self._bild = None
            self._blende_rechts_aus()
            return
        self.doku_var.set(os.path.basename(pfad))
        self._thumb.config(bg="#e4e4e4", font="TkDefaultFont")
        self._plane_ausblenden("rechts", rest, self._blende_rechts_aus)
        if not HAS_PIL:
            return
        try:
            self._bild = self._render(pfad)
            self._thumb.config(image=self._bild, text="")
        except Exception:
            self._thumb.config(image="", text="(keine Vorschau)")

    def _uebernimm_links(self, pfad, ziel, grund):
        """
        Erledigtes Dokument in die "Zuletzt abgelegt"-Spalte übernehmen: Das schon
        gerenderte Vorschaubild der "In Arbeit"-Spalte wird weitergereicht (kein
        zweites Rendern); fehlt es (Fenster mitten im Lauf geöffnet), wird aus dem
        Pfad nachgerendert - der zeigt nach dem Verschieben aber meist ins Leere,
        dann bleibt das Feld eben leer. Ist die Anzeigezeit des Dokuments schon um,
        steht dort gleich nur „✓ abgelegt“ / „⚠ unsicher“.
        """
        if not ziel:
            return   # nichts abgelegt (Fehlerfall) - die Meldung steht schon oben im Status
        self._links_sicher = not grund
        rest = self._rest(pfad) if pfad else None
        if pfad:
            self._erst_gesehen.pop(pfad, None)   # das Dokument ist durch; die Anzeige links läuft mit `rest` weiter
        if rest == 0:
            self._plane_ausblenden("links", None, None)
            self._blende_links_aus(self._links_sicher)
            return
        self._thumb_links.config(bg="#e4e4e4", fg="black", font="TkDefaultFont")
        if self._bild is not None:
            self._bild_links = self._bild
            self._thumb_links.config(image=self._bild_links, text="")
        elif pfad and HAS_PIL:
            try:
                self._bild_links = self._render(pfad)
                self._thumb_links.config(image=self._bild_links, text="")
            except Exception:
                self._thumb_links.config(image="", text="(keine Vorschau)")
        self.links_name_var.set(self.doku_var.get() or os.path.basename(pfad or ""))
        self._zeige_ergebnis(ziel, grund)
        self._plane_ausblenden("links", rest, self._blende_links_aus)

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
        r = self._px(26) - self._px(3)
        breite = max(3, self._px(3))
        self._anim.create_oval(self._px(3), self._px(3), r, r, outline="#d0d0d0", width=breite)
        self._anim.create_arc(self._px(3), self._px(3), r, r, start=-self._winkel, extent=100,
                              style=tk.ARC, outline="#2f7d32", width=breite)
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
        self._zeige_zaehler()      # „zuletzt nachgesehen“ läuft auch ohne neue Dokumente mit
        self._countdown_id = self.after(COUNTDOWN_MS, self._tick_countdown)

    # ------------------------------------------------------------------ Aus
    def destroy(self):
        """Laufende Timer abbestellen — sonst meldet Tk nach dem Schließen 'invalid command name'."""
        for kennung in [self._anim_id, self._countdown_id] + list(self._ausblenden_ids.values()):
            if kennung:
                try:
                    self.after_cancel(kennung)
                except Exception:
                    pass
        self._anim_id = self._countdown_id = None
        self._ausblenden_ids = {}
        super().destroy()

    def _ausschalten(self):
        """Fenster zu = Vollautomatik aus (die eine, für Senioren verständliche Regel). Im Dienstmodus beendet das den
        ganzen Dienst - mit Rückfrage, auf einem Touch-Panel tippt man leicht daneben (KONZEPT_DIENSTMODUS F4)."""
        if self._dienst:
            if messagebox.askyesno("Dienst beenden",
                                   "Soll die Hintergrund-Automatik beendet werden?\n\nNeue Dokumente im Posteingang "
                                   "bleiben dann liegen, bis KID wieder gestartet wird.", parent=self, default="no"):
                self.app.beenden()
            return
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
    dienst = bool(getattr(app, "dienstmodus", False))   # Dienstmodus (dienstmodus.py): immer an, kein Hauptfenster
    try:
        aktiv = dienst or bool(app.config.get(CONFIG_KEY, False))
    except Exception:
        return
    fenster = getattr(app, "vollautomatik_fenster", None)
    offen = fenster is not None and fenster.winfo_exists()
    if aktiv and not offen:
        root = getattr(app, "root", None)
        if not dienst and root is not None and not root.winfo_viewable():
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
