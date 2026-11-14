"""
Tool "Dubletten finden" (Nutzerwunsch 30.08.2026): doppelt gescannte oder doppelt
kopierte Dokumente in der Sammlung aufspüren, Paare nebeneinander prüfen und das
überzählige Exemplar in den Papierkorb verschieben (Soft-Delete, nie endgültig).

Ablauf: Fingerabdrücke aller PDFs im Hintergrund sammeln (Seitenzahl, Text Seite 1,
Bild-Hash, Datei-Hash, Metadaten) -> dubletten.finde_dubletten gruppiert -> Tabelle mit
einer Zeile pro Dokument, gruppenweise; die Empfehlung "behalten" (bessere Textebene,
mehr Metadaten) ist vorbelegt und pro Zeile umschaltbar. Verschoben wird erst auf Klick.

Layout (Nutzerwunsch 30.08.2026): Tabelle im oberen Drittel, darunter zwei große
Vorschauen (markierte Zeile + Gruppen-Partner), die mit dem Fenster mitwachsen -
das Fenster ist maximierbar (deshalb kein transient(), das nimmt unter Windows die
Titelleisten-Knöpfe). Zwischen beiden steht die Wortliste "nur links / nur rechts":
unterscheiden sich zwei Briefe nur in Rechnungsnummer, Anrede oder Datum, sind es
keine Dubletten und beide bleiben.

Die Vorschauen (SeitenVorschau) blättern und zoomen wie das Hauptfenster: Mausrad
scrollt und blättert am Seitenrand weiter, Strg+Mausrad zoomt, Ziehen mit der Maus
verschiebt, Bild-auf/-ab blättert. Standardmäßig laufen beide synchron (gleiche Seite,
gleicher Zoom, gleiche Scroll-Lage), damit man zwei Scans Zeile für Zeile vergleicht.
"""

import io
import os
import threading
import tkinter as tk
import tkinter.messagebox as mb
import bestaetigung
from tkinter import ttk

import app_paths
import dubletten
import dubletten_geprueft
import dubletten_pruefung
from pdf_handler import PDFHandler
from tools.base_tool import BaseTool, ToolContext
from ui_utils import UIUtils, ProgressDialog

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:  # pragma: no cover - Pillow ist Laufzeit-Abhängigkeit
    HAS_PIL = False

BASIS_DPI = 110             # Render-Auflösung bei Zoom 1.0 bzw. "Anpassen"; höherer Zoom rendert schärfer
MAX_DPI = 330               # Deckel fürs Rendern (RAM: A4 bei 330 dpi ~ 30 MB als RGB)
ZOOM_MIN, ZOOM_MAX = 0.2, 4.0
SKALIER_VERZOEGERUNG = 150  # ms Debounce für <Configure> (Fenster ziehen feuert pro Pixel)
ZOOM_VERZOEGERUNG = 40      # ms Debounce für Strg+Mausrad (wie preview_manager)
BLAETTER_SPERRE = 250       # ms Sperre nach dem Blättern gegen Durchrattern (FALLSTRICKE: Smart-Scroll)


class DublettenFinderTool(BaseTool):
    def __init__(self):
        self.window = None

    @property
    def name(self) -> str:
        return "Dubletten finden"

    @property
    def menu_group(self) -> str:
        return "Aufräumen"

    @property
    def menu_label(self) -> str:
        return "Dubletten finden…"

    @property
    def absicht(self) -> str:
        return ("Doppelt gescannt oder kopiert passiert leicht. Das Tool erkennt Paare über Datei-Hash, Text und "
                "Seitenbild, empfiehlt das bessere Exemplar und legt das andere nur in den Papierkorb - nichts wird "
                "endgültig gelöscht. Eine geprüfte Gruppe, die keine Dublette ist, lässt sich merken und taucht "
                "beim nächsten Lauf nicht mehr auf.")

    @property
    def description(self) -> str:
        return "Findet doppelt gescannte/kopierte Dokumente und verschiebt das überzählige Exemplar in den Papierkorb."

    @property
    def menu_hooks(self) -> list:
        return ["main_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        master = getattr(context.app, "master_folder", "")
        if not master or not os.path.isdir(master):
            mb.showinfo("Hinweis", "Bitte zuerst einen Hauptordner wählen.")
            return False
        if self.window and self.window.winfo_exists():
            self.window.destroy()
        self.window = DublettenFenster(context.app)
        return True


def sammle_pdfs(master_folder):
    """Alle PDFs der Sammlung außer Papierkorb/Daten-Ordner und versteckten Ordnern (sortiert)."""
    pfade = []
    for dirpath, dirnames, filenames in os.walk(master_folder):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")
                       and not app_paths.is_trash_path(os.path.join(dirpath, d), master_folder)]
        for name in filenames:
            if name.lower().endswith(".pdf") and not name.startswith("."):
                pfade.append(os.path.join(dirpath, name))
    return sorted(pfade)


# Der Fingerabdruck eines Dokuments wird auch von der Vollautomatik gebraucht
# (Stufe B, dubletten_pruefung.pruefe_entscheidung) - deshalb wohnt lese_info dort.
lese_info = dubletten_pruefung.lese_info


class SeitenVorschau(ttk.Frame):
    """
    Blätterbare, zoombare Vorschau eines Dokuments (Nutzerwunsch 30.08.2026: "durch die
    Seiten scrollen und vergrößern wie im Hauptfenster"). Bewusst schlank gehalten,
    ohne den PreviewManager des Hauptfensters anzutasten (der hängt an dessen Widgets).
    on_change(vorschau, art) meldet "seite" / "zoom" / "scroll", damit das Fenster
    die Partner-Vorschau synchron halten kann.
    """

    def __init__(self, master, on_change=None):
        super().__init__(master)
        self.on_change = on_change
        self.pfad = None
        self.seiten = 0
        self.seite = 0
        self.zoom = None              # None = ganze Seite ins Feld einpassen
        self._cache = {}              # (pfad, seite, dpi) -> PIL.Image
        self._foto = None             # aktuelles PhotoImage (Referenz halten!)
        self._zoom_ziel = None
        self._zoom_timer = None
        self._skalier_timer = None
        self._sperre = False
        self._sperr_timer = None
        self._rand_erreicht = False
        self.stumm = False            # True, während der Partner uns steuert (keine Rückmeldung)
        self.titel_praefix = ""       # z.B. "Markiert: " - Rolle der Vorschau vor dem Dateinamen

        kopf = ttk.Frame(self)
        kopf.pack(fill=tk.X)
        # width=10: der Dateiname darf die Vorschau nicht breiter machen als die Partner-
        # Vorschau (pack/grid rechnen die Wunschbreite des Inhalts mit) - er wird gestreckt,
        # notfalls abgeschnitten. Siehe lege_vorschauen_nebeneinander.
        self.titel = ttk.Label(kopf, text="", anchor="w", width=10)
        self.titel.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(kopf, text="◀", width=3, command=lambda: self.blaettere(-1)).pack(side=tk.LEFT)
        self.seiten_label = ttk.Label(kopf, text="", width=10, anchor="center")
        self.seiten_label.pack(side=tk.LEFT)
        ttk.Button(kopf, text="▶", width=3, command=lambda: self.blaettere(1)).pack(side=tk.LEFT)
        ttk.Button(kopf, text="−", width=3, command=lambda: self.zoome(1 / 1.25)).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(kopf, text="+", width=3, command=lambda: self.zoome(1.25)).pack(side=tk.LEFT)
        ttk.Button(kopf, text="Anpassen", command=self.anpassen).pack(side=tk.LEFT, padx=(2, 0))

        rumpf = ttk.Frame(self)
        rumpf.pack(fill=tk.BOTH, expand=True)
        self.canvas = tk.Canvas(rumpf, bg="#f4f4f4", highlightthickness=0)
        vs = ttk.Scrollbar(rumpf, orient=tk.VERTICAL, command=self.canvas.yview)
        hs = ttk.Scrollbar(rumpf, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self._vs = vs
        self.canvas.configure(yscrollcommand=self._on_yscroll, xscrollcommand=hs.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        rumpf.rowconfigure(0, weight=1)
        rumpf.columnconfigure(0, weight=1)

        self.canvas.bind("<MouseWheel>", self._on_wheel)
        self.canvas.bind("<Control-MouseWheel>", self._on_zoom_wheel)
        self.canvas.bind("<ButtonPress-1>", lambda e: (self.canvas.focus_set(), self.canvas.scan_mark(e.x, e.y)))
        self.canvas.bind("<B1-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<Prior>", lambda e: self.blaettere(-1))
        self.canvas.bind("<Next>", lambda e: self.blaettere(1))
        self.canvas.bind("<Configure>", self._on_configure)

    # -------------------------------------------------------------- Steuerung
    def setze_datei(self, pfad, seite=0):
        """Zeigt ein Dokument (None = leeren). Der Zoom bleibt, die Seite startet bei 'seite'."""
        self.pfad = pfad
        if not pfad or not HAS_PIL:
            self.seiten, self.seite = 0, 0
            self.titel.config(text="")
            self.seiten_label.config(text="")
            self.canvas.delete("all")
            self._foto = None
            return
        self.seiten = max(1, PDFHandler.get_page_count(pfad) or 1)
        self.seite = min(max(0, seite), self.seiten - 1)
        self.titel.config(text=f"{self.titel_praefix}{os.path.basename(pfad)}")
        self._render()

    def blaettere(self, delta):
        if not self.pfad:
            return
        neu = min(max(0, self.seite + delta), self.seiten - 1)
        if neu == self.seite:
            return
        self.seite = neu
        self._render()
        self.canvas.yview_moveto(0.0 if delta > 0 else 1.0)
        self._melde("seite")

    def zoome(self, faktor):
        if not self.pfad:
            return
        basis = self.zoom if self.zoom is not None else self._einpass_zoom()
        self.zoom = min(ZOOM_MAX, max(ZOOM_MIN, basis * faktor))
        self._render()
        self._melde("zoom")

    def anpassen(self):
        self.zoom = None
        self._render()
        self._melde("zoom")

    def uebernimm(self, anderer, art):
        """Partner-Vorschau hat sich geändert - nachziehen, ohne zurückzumelden."""
        if not self.pfad:
            return
        self.stumm = True
        try:
            if art == "seite":
                ziel = min(anderer.seite, self.seiten - 1)
                if ziel != self.seite:
                    self.seite = ziel
                    self._render()
                self.canvas.yview_moveto(anderer.canvas.yview()[0])
            elif art == "zoom":
                self.zoom = anderer.zoom
                self._render()
            elif art == "scroll":
                self.canvas.yview_moveto(anderer.canvas.yview()[0])
        finally:
            self.stumm = False

    def _melde(self, art):
        if self.on_change and not self.stumm:
            self.on_change(self, art)

    # -------------------------------------------------------------- Rendern
    def _einpass_zoom(self):
        """Zoom, bei dem die ganze Seite ins Feld passt (bezogen auf BASIS_DPI)."""
        bild = self._seitenbild(BASIS_DPI)
        if bild is None:
            return 1.0
        breite = max(50, self.canvas.winfo_width() - 4)
        hoehe = max(50, self.canvas.winfo_height() - 4)
        return min(breite / bild.width, hoehe / bild.height)

    def _seitenbild(self, dpi):
        schluessel = (self.pfad, self.seite, dpi)
        bild = self._cache.get(schluessel)
        if bild is None:
            try:
                png = PDFHandler.render_page_png(self.pfad, page_number=self.seite, dpi=dpi)
                bild = Image.open(io.BytesIO(png))
            except Exception:
                return None
            if len(self._cache) > 24:
                self._cache.clear()
            self._cache[schluessel] = bild
        return bild

    def _render(self):
        self.seiten_label.config(text=f"{self.seite + 1} / {self.seiten}")
        zoom = self.zoom if self.zoom is not None else self._einpass_zoom()
        dpi = int(min(MAX_DPI, max(50, BASIS_DPI * zoom)))
        bild = self._seitenbild(dpi)
        self.canvas.delete("all")
        if bild is None:
            self.canvas.create_text(10, 10, anchor="nw", text="(keine Vorschau)")
            return
        # Zielgröße = Größe bei BASIS_DPI mal Zoom, unabhängig davon, mit welchem dpi gerendert wurde
        faktor = BASIS_DPI * zoom / dpi
        groesse = (max(1, int(bild.width * faktor)), max(1, int(bild.height * faktor)))
        if groesse != bild.size:
            bild = bild.resize(groesse)
        self._foto = ImageTk.PhotoImage(bild)
        cw = max(1, self.canvas.winfo_width())
        x = max(0, (cw - groesse[0]) // 2)
        self.canvas.create_image(x, 0, anchor="nw", image=self._foto)
        self.canvas.configure(scrollregion=(0, 0, max(cw, groesse[0]), groesse[1]))

    # -------------------------------------------------------------- Ereignisse
    def _on_configure(self, event=None):
        if self._skalier_timer:
            self.after_cancel(self._skalier_timer)
        self._skalier_timer = self.after(SKALIER_VERZOEGERUNG, self._nach_configure)

    def _nach_configure(self):
        self._skalier_timer = None
        if self.pfad and self.winfo_exists():
            self._render()

    def _on_yscroll(self, erster, letzter):
        self._vs.set(erster, letzter)
        self._melde("scroll")

    def _sperre_setzen(self):
        self._sperre = True
        if self._sperr_timer:
            self.after_cancel(self._sperr_timer)
        self._sperr_timer = self.after(BLAETTER_SPERRE, self._sperre_loesen)

    def _sperre_loesen(self):
        self._sperre = False

    def _on_wheel(self, event):
        """Scrollen; am Seitenrand blättern (ganz sichtbare Seite: sofort, sonst zweiter Tick) - wie preview_manager."""
        if not self.pfad:
            return
        richtung = -1 if event.delta > 0 else 1
        oben, unten = self.canvas.yview()
        if oben <= 0.0 and unten >= 1.0:
            if not self._sperre:
                self._sperre_setzen()
                self.blaettere(richtung)
            return "break"
        am_rand = (richtung < 0 and oben <= 0.0) or (richtung > 0 and unten >= 1.0)
        if am_rand:
            if not self._rand_erreicht:
                self._rand_erreicht = True
                self._sperre_setzen()
            elif not self._sperre:
                self._rand_erreicht = False
                self.blaettere(richtung)
        else:
            self._rand_erreicht = False
            self.canvas.yview_scroll(richtung * 2, "units")
        return "break"

    def _on_zoom_wheel(self, event):
        if not self.pfad:
            return
        basis = self._zoom_ziel if self._zoom_ziel is not None else (
            self.zoom if self.zoom is not None else self._einpass_zoom())
        faktor = 1.1 if event.delta > 0 else 1 / 1.1
        self._zoom_ziel = min(ZOOM_MAX, max(ZOOM_MIN, basis * faktor))
        if self._zoom_timer:
            self.after_cancel(self._zoom_timer)
        self._zoom_timer = self.after(ZOOM_VERZOEGERUNG, self._zoom_anwenden)
        return "break"

    def _zoom_anwenden(self):
        self._zoom_timer = None
        if self._zoom_ziel is None:
            return
        self.zoom = self._zoom_ziel
        self._zoom_ziel = None
        self._render()
        self._melde("zoom")


def lege_vorschauen_nebeneinander(rahmen, vorschauen):
    """
    Ordnet die Vorschauen in gleich breiten Spalten an. Mit pack(expand=True) bekam jede
    Vorschau ihre Wunschbreite plus die Hälfte des Rests - der Teiler wanderte also mit der
    Länge des angezeigten Dateinamens (Nutzerfund 12.09.2026, FALLSTRICKE #66). grid mit
    uniform-Spalten teilt die Breite unabhängig vom Inhalt.
    """
    rahmen.rowconfigure(0, weight=1)
    for spalte, vorschau in enumerate(vorschauen):
        rahmen.columnconfigure(spalte, weight=1, uniform="vorschau")
        vorschau.grid(row=0, column=spalte, sticky="nsew", padx=2)


def kid_id_von(info):
    """Dokument-ID eines Info-Dicts (aus den Metadaten), "" ohne ID."""
    return ((info.get("meta") or {}).get("KID_ID") or "").strip()


class DublettenFenster(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        UIUtils.werkzeugfenster(self, app.root)   # über KID, nicht modal (Peter 04.11.2026)
        self.app = app
        self.title("Dubletten finden")
        UIUtils.position_near_mouse(self, UIUtils.px(self, 1400), UIUtils.px(self, 900))
        self.minsize(UIUtils.px(self, 900), UIUtils.px(self, 600))
        self.gruppen = []          # [(infos, grund, sicher)]
        self.zeilen = {}           # iid -> info
        self.behalten = set()      # Pfade, die bleiben sollen
        self._wrap_timer = None
        self._setup_ui()
        self.after(100, self._starte_suche)

    def _setup_ui(self):
        self.paned = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))

        oben = ttk.Frame(self.paned)
        self.paned.add(oben, weight=1)
        columns = ("vorschau", "aktion", "datei", "ordner", "seiten", "qualitaet", "datum", "titel", "grund")
        self.tree = ttk.Treeview(oben, columns=columns, show="headings", selectmode="browse")
        for col, text, width, stretch in (
            ("vorschau", "Vorschau", 70, False),
            ("aktion", "Vorschlag", 85, False), ("datei", "Datei", 330, True), ("ordner", "Ordner", 250, True),
            ("seiten", "S.", 35, False), ("qualitaet", "Text %", 55, False), ("datum", "Datum", 85, False),
            ("titel", "Titel", 260, True), ("grund", "Grund", 300, True),
        ):
            self.tree.heading(col, text=text)
            breite = UIUtils.px(self, width)
            # minwidth = volle Spaltenbreite: lieber waagerecht scrollen als Spalten
            # zusammenquetschen, bis "Grund" unlesbar ist (wie in der Ablage-Vorschau).
            self.tree.column(col, width=breite, minwidth=breite, stretch=stretch, anchor="w")
        self.tree.tag_configure("behalten", background="#e6f4e6")
        self.tree.tag_configure("papierkorb", background="#fdf3d7")
        self.tree.tag_configure("trenner", background="#e8e8e8")
        self.tree.tag_configure("geprueft", background="#e9eef5", foreground="gray30")
        scroll = ttk.Scrollbar(oben, command=self.tree.yview)
        scroll_x = ttk.Scrollbar(oben, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=scroll_x.set)
        oben.rowconfigure(0, weight=1)
        oben.columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        # Shift+Klick: diese Zeile der Gruppe RECHTS zeigen (Auswahl links bleibt) - bei Gruppen
        # mit drei und mehr Dokumenten war sonst nicht erkennbar, was verglichen wird.
        self.tree.bind("<Shift-Button-1>", self._partner_waehlen)
        self.tree.bind("<Double-Button-1>", lambda e: self._umschalten())
        self.tree.bind("<space>", lambda e: self._umschalten())
        self.tree.bind("<F2>", lambda e: self._umbenennen())

        unten = ttk.Frame(self.paned)
        self.paned.add(unten, weight=2)
        kopfzeile = ttk.Frame(unten)
        kopfzeile.pack(fill=tk.X, pady=(4, 2))
        self.synchron = tk.BooleanVar(value=True)
        ttk.Checkbutton(kopfzeile, text="Synchron blättern/zoomen", variable=self.synchron).pack(side=tk.RIGHT)
        # Gedächtnis (dubletten_geprueft.py): gemerkte Gruppen sind normalerweise ausgeblendet
        self.zeige_geprueft = tk.BooleanVar(value=False)
        ttk.Checkbutton(kopfzeile, text="Geprüfte Gruppen anzeigen", variable=self.zeige_geprueft,
                        command=self._fuelle_tabelle).pack(side=tk.RIGHT, padx=(0, 16))
        self.unterschiede = ttk.Label(kopfzeile, anchor="w", justify=tk.LEFT, foreground="gray20")
        self.unterschiede.pack(side=tk.LEFT, fill=tk.X, expand=True)
        bilder = ttk.Frame(unten)
        bilder.pack(fill=tk.BOTH, expand=True)
        self.vorschauen = []
        for praefix in ("Markiert: ", "Vergleich: "):
            vorschau = SeitenVorschau(bilder, on_change=self._vorschau_geaendert)
            vorschau.titel_praefix = praefix
            self.vorschauen.append(vorschau)
        lege_vorschauen_nebeneinander(bilder, self.vorschauen)
        self.partner_wahl = {}   # Gruppen-Nr -> Pfad, der rechts gezeigt werden soll (Shift+Klick)
        self._meldung = ""       # einmalige Rückmeldung („Gruppe 3 gemerkt …") vor dem Hinweistext
        self.bind("<Configure>", self._on_configure)

        self.hinweis = ttk.Label(self, anchor="w", justify=tk.LEFT, foreground="gray40", wraplength=UIUtils.px(self, 1350),
                                 text="Suche läuft... Grün = bleibt, Gelb = wandert in den Papierkorb. "
                                      "Doppelklick/Leertaste tauscht den Vorschlag innerhalb einer Gruppe.")
        self.hinweis.pack(fill=tk.X, padx=10, pady=(0, 5))
        buttons = ttk.Frame(self)
        buttons.pack(pady=(0, 10))
        self.btn_ausfuehren = ttk.Button(buttons, text="Gelbe in den Papierkorb verschieben",
                                         command=self._ausfuehren, state=tk.DISABLED)
        self.btn_ausfuehren.pack(side=tk.LEFT, padx=5)
        self.btn_geprueft = ttk.Button(buttons, text="Gruppe als geprüft merken", command=self._geprueft_umschalten,
                                       state=tk.DISABLED)
        self.btn_geprueft.pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons, text="Markierte Datei öffnen", command=self._oeffnen).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons, text="Umbenennen (F2)", command=self._umbenennen).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons, text="Erneut suchen", command=self._starte_suche).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons, text="Schließen", command=self.destroy).pack(side=tk.LEFT, padx=5)
        # Teiler erst setzen, wenn das Fenster seine Größe hat: Tabelle oben ein Drittel
        self.after(200, self._setze_teiler)

    def _setze_teiler(self):
        if not self.winfo_exists():
            return
        self.update_idletasks()
        hoehe = self.paned.winfo_height()
        if hoehe > 100:
            self.paned.sashpos(0, hoehe // 3)

    def _on_configure(self, event=None):
        """Fenstergröße geändert - Umbruchbreite der Textzeilen verzögert nachziehen (Vorschauen skalieren sich selbst)."""
        if event is not None and event.widget is not self:
            return
        if self._wrap_timer:
            self.after_cancel(self._wrap_timer)
        self._wrap_timer = self.after(SKALIER_VERZOEGERUNG, self._umbruch_anpassen)

    def _umbruch_anpassen(self):
        self._wrap_timer = None
        if not self.winfo_exists():
            return
        rand = UIUtils.px(self, 30)
        self.hinweis.config(wraplength=max(UIUtils.px(self, 300), self.winfo_width() - rand))
        self.unterschiede.config(wraplength=max(UIUtils.px(self, 300),
                                                self.winfo_width() - UIUtils.px(self, 260)))

    def _vorschau_geaendert(self, quelle, art):
        """Eine Vorschau wurde geblättert/gezoomt/gescrollt - Partner nachziehen, falls 'Synchron' an ist."""
        if not self.synchron.get():
            return
        for andere in self.vorschauen:
            if andere is not quelle and not andere.stumm:
                andere.uebernimm(quelle, art)

    # ------------------------------------------------------------------ Suche
    def _starte_suche(self):
        pfade = sammle_pdfs(self.app.master_folder)
        if not pfade:
            mb.showinfo("Dubletten finden", "Keine PDF-Dokumente in der Sammlung gefunden.", parent=self)
            return
        # Unterscheidungs-Tags (Personen, Objekte & Adressen) VOR dem Hintergrund-Thread holen (Tkinter)
        merkmale = (self.app.tag_manager.merkmale_fuer_dubletten()
                    if hasattr(self.app, "tag_manager") else {})
        dialog = ProgressDialog(self, "Dubletten finden", "Dokumente werden verglichen...")

        def worker():
            infos = []
            for i, pfad in enumerate(pfade):
                if dialog.should_stop():
                    break
                try:
                    infos.append(lese_info(pfad))
                except Exception as e:
                    if getattr(self.app, "logger", None):
                        self.app.logger.warning(f"Dubletten: {pfad} nicht lesbar: {e}")
                self.after(0, dialog.update_progress, i + 1, len(pfade))
            gruppen = dubletten.finde_dubletten(infos, merkmale)
            self.after(0, self._zeige_gruppen, gruppen, dialog, len(infos))

        threading.Thread(target=worker, daemon=True).start()

    def _zeige_gruppen(self, gruppen, dialog, anzahl):
        if dialog.winfo_exists():
            dialog.destroy()
        if not self.winfo_exists():
            return
        self.alle_gruppen = gruppen
        self.anzahl = anzahl
        self._fuelle_tabelle()

    def _fuelle_tabelle(self):
        """
        Tabelle aus alle_gruppen aufbauen. Gemerkte Gruppen (dubletten_geprueft.py) bleiben
        weg, außer „Geprüfte Gruppen anzeigen" ist an - dann stehen sie grau am Ende.
        """
        if not hasattr(self, "alle_gruppen"):
            return
        paare = dubletten_geprueft.lade(self.app.master_folder)
        offene, geprueft = dubletten_geprueft.trenne_gruppen(self.alle_gruppen, paare, kid_id_von)
        gruppen = offene + (geprueft if self.zeige_geprueft.get() else [])
        self.gruppen = gruppen
        self.geprueft_nrn = set(range(len(offene), len(gruppen)))
        self.trenner = {}
        self.zeilen = {}
        self.behalten = set()
        self.partner_wahl = {}
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        master = self.app.master_folder
        for nr, (infos, grund, sicher) in enumerate(gruppen, start=1):
            ist_geprueft = (nr - 1) in self.geprueft_nrn
            self.trenner[nr - 1] = self.tree.insert(
                "", tk.END, values=("", f"— Gruppe {nr} —", "", "", "", "", "", "", self._grund_text(grund, ist_geprueft)),
                tags=("trenner",))
            if sicher and not ist_geprueft:
                self.behalten.add(dubletten.empfehlung(infos)["pfad"])
            else:
                # Schwacher Treffer (z.B. zwei verschiedene Rechnungen vom selben Tag auf gleichem
                # Briefpapier) oder bereits geprüft: nichts vorschlagen, alles bleibt.
                for info in infos:
                    self.behalten.add(info["pfad"])
            for info in infos:
                meta = info.get("meta") or {}
                iid = self.tree.insert("", tk.END, values=(
                    "", "", os.path.basename(info["pfad"]),
                    os.path.relpath(os.path.dirname(info["pfad"]), master),
                    info.get("seiten", ""), info.get("qualitaet", ""),
                    meta.get("KID_DokumentenDatum", ""), meta.get("title", ""), ""))
                self.zeilen[iid] = info
                self._zeichne_zeile(iid)
        gemerkt = f" ({len(geprueft)} bereits geprüfte Gruppe(n) gemerkt)" if geprueft else ""
        meldung, self._meldung = self._meldung, ""
        self.hinweis.config(text=meldung + (
            f"{self.anzahl} Dokumente verglichen, {len(offene)} offene Dubletten-Gruppe(n){gemerkt}. "
            "Grün = bleibt, Gelb = wandert in den Papierkorb. Bei 'Prüfen:'-Gruppen (schwache Ähnlichkeit, "
            "z.B. zwei Briefe vom selben Tag) bleibt alles grün, bis du per Doppelklick/Leertaste entscheidest. "
            "Doppelklick auf die Gruppenzeile (oder „Gruppe als geprüft merken“) merkt eine geprüfte Gruppe als "
            "„keine Dublette“ und blendet sie aus - rückgängig über „Geprüfte Gruppen anzeigen“. "
            "Vorschau: links die markierte Zeile, rechts ihr Vergleichs-Dokument (Spalte „Vorschau“ zeigt links/rechts); "
            "Shift+Klick auf eine andere Zeile der Gruppe legt fest, was rechts liegt."
            if gruppen else f"{self.anzahl} Dokumente verglichen - keine offenen Dubletten-Gruppen{gemerkt}."))
        self.btn_ausfuehren.config(state=tk.NORMAL if gruppen else tk.DISABLED)
        self.btn_geprueft.config(state=tk.DISABLED, text="Gruppe als geprüft merken")
        for vorschau in self.vorschauen:
            vorschau.setze_datei(None)
        self.unterschiede.config(text="")

    @staticmethod
    def _grund_text(grund, ist_geprueft):
        return f"Geprüft, keine Dublette - {grund}" if ist_geprueft else grund

    def _zeichne_zeile(self, iid):
        info = self.zeilen[iid]
        if self._gruppen_nr(info) in self.geprueft_nrn:
            self.tree.set(iid, "aktion", "geprüft")
            self.tree.item(iid, tags=("geprueft",))
            return
        bleibt = info["pfad"] in self.behalten
        self.tree.set(iid, "aktion", "behalten" if bleibt else "Papierkorb")
        self.tree.item(iid, tags=("behalten" if bleibt else "papierkorb",))

    def _gruppe_von(self, info):
        for infos, _grund, _sicher in self.gruppen:
            if any(i["pfad"] == info["pfad"] for i in infos):
                return infos
        return [info]

    def _gruppen_nr(self, info):
        for nr, (infos, _grund, _sicher) in enumerate(self.gruppen):
            if any(i["pfad"] == info["pfad"] for i in infos):
                return nr
        return -1

    def _partner_waehlen(self, event):
        """Shift+Klick: die angeklickte Zeile rechts zeigen, sofern sie zur Gruppe der markierten Zeile gehört."""
        iid = self.tree.identify_row(event.y)
        auswahl = self.tree.selection()
        if iid not in self.zeilen or not auswahl or auswahl[0] not in self.zeilen:
            return "break"
        info, gewaehlt = self.zeilen[auswahl[0]], self.zeilen[iid]
        if gewaehlt["pfad"] != info["pfad"] and self._gruppen_nr(gewaehlt) == self._gruppen_nr(info):
            self.partner_wahl[self._gruppen_nr(info)] = gewaehlt["pfad"]
            self._on_select()
        return "break"   # Auswahl (links) nicht verschieben

    def _markiere_vorschau_zeilen(self, links, rechts):
        """Spalte „Vorschau“: „links“ an der markierten Zeile, „rechts“ am Vergleichs-Dokument."""
        for iid, i in self.zeilen.items():
            wert = "links" if i["pfad"] == links else ("rechts" if rechts and i["pfad"] == rechts else "")
            self.tree.set(iid, "vorschau", wert)

    # ------------------------------------------------------------------ Bedienung
    def _gruppen_nr_der_auswahl(self):
        """Gruppen-Nr der markierten Zeile - Dokumentzeile oder Gruppenzeile („— Gruppe n —"); -1 ohne Auswahl."""
        auswahl = self.tree.selection()
        if not auswahl:
            return -1
        if auswahl[0] in self.zeilen:
            return self._gruppen_nr(self.zeilen[auswahl[0]])
        for nr, iid in self.trenner.items():
            if iid == auswahl[0]:
                return nr
        return -1

    def _umschalten(self):
        auswahl = self.tree.selection()
        if auswahl and auswahl[0] not in self.zeilen and auswahl[0] in self.trenner.values():
            # Doppelklick auf die Gruppenzeile (Nutzerwunsch 12.09.2026): Gruppe als geprüft
            # merken und ausblenden (bzw. bei einer gemerkten Gruppe die Prüfung aufheben)
            self._geprueft_umschalten()
            return
        if not auswahl or auswahl[0] not in self.zeilen:
            return
        info = self.zeilen[auswahl[0]]
        gruppe = self._gruppe_von(info)
        if self._gruppen_nr(info) in self.geprueft_nrn:
            return   # gemerkte Gruppe: erst „Prüfung aufheben", dann entscheiden
        if info["pfad"] in self.behalten:
            # Diese Zeile soll in den Papierkorb - dann muss eine andere der Gruppe bleiben
            andere = [i for i in gruppe if i["pfad"] != info["pfad"]]
            if not andere:
                return
            self.behalten.discard(info["pfad"])
            if not any(i["pfad"] in self.behalten for i in andere):
                self.behalten.add(andere[0]["pfad"])
        else:
            self.behalten.add(info["pfad"])
        for iid, i in self.zeilen.items():
            if any(i["pfad"] == g["pfad"] for g in gruppe):
                self._zeichne_zeile(iid)

    def _on_select(self, event=None):
        auswahl = self.tree.selection()
        if auswahl and auswahl[0] in self.trenner.values():
            nr = self._gruppen_nr_der_auswahl()
            self.btn_geprueft.config(state=tk.NORMAL, text="Prüfung dieser Gruppe aufheben"
                                     if nr in self.geprueft_nrn else "Gruppe als geprüft merken")
            return
        if not auswahl or auswahl[0] not in self.zeilen:
            return
        info = self.zeilen[auswahl[0]]
        gruppe = self._gruppe_von(info)
        partner = dubletten.waehle_partner(gruppe, info, self.partner_wahl.get(self._gruppen_nr(info)))
        self.vorschauen[0].setze_datei(info["pfad"])
        self.vorschauen[1].setze_datei(partner["pfad"] if partner else None)
        self._markiere_vorschau_zeilen(info["pfad"], partner["pfad"] if partner else None)
        self._zeige_unterschiede(info, partner)
        geprueft = self._gruppen_nr(info) in self.geprueft_nrn
        self.btn_geprueft.config(state=tk.NORMAL,
                                 text="Prüfung dieser Gruppe aufheben" if geprueft else "Gruppe als geprüft merken")

    # ------------------------------------------------------------------ Gedächtnis
    def _geprueft_umschalten(self):
        """
        Markierte Gruppe als „geprüft, keine Dublette" merken (oder die Prüfung aufheben).
        Beim Merken bekommt jedes Dokument der Gruppe eine Dokument-ID (KID_ID), falls es
        noch keine hat - das ist ein Metadaten-Schreibvorgang je Datei.
        """
        nr = self._gruppen_nr_der_auswahl()
        if nr < 0:
            return
        infos = self.gruppen[nr][0]
        master = self.app.master_folder
        if nr in self.geprueft_nrn:
            dubletten_geprueft.vergiss(master, [kid_id_von(i) for i in infos])
            self.geprueft_nrn.discard(nr)
        else:
            ids = []
            self.app.is_saving = True
            try:
                for i in infos:
                    kid = kid_id_von(i) or PDFHandler.ensure_kid_id(i["pfad"])
                    if not kid:
                        mb.showerror("Dubletten finden",
                                     f"Die Dokument-ID konnte nicht gespeichert werden:\n{os.path.basename(i['pfad'])}\n\n"
                                     "Ist die Datei geöffnet oder schreibgeschützt? Die Gruppe wird nicht gemerkt.",
                                     parent=self)
                        return
                    if i.get("meta") is None:
                        i["meta"] = {}
                    i["meta"]["KID_ID"] = kid
                    ids.append(kid)
            finally:
                self.app.root.after(1500, lambda: setattr(self.app, "is_saving", False))
            if not dubletten_geprueft.merke(master, ids):
                mb.showerror("Dubletten finden", "Das Gedächtnis (dubletten_geprueft.json) konnte nicht geschrieben werden.",
                             parent=self)
                return
            for i in infos:
                self.behalten.add(i["pfad"])
            self.geprueft_nrn.add(nr)
            if getattr(self.app, "logger", None):
                self.app.logger.info(f"Dubletten: Gruppe als geprüft gemerkt: {[os.path.basename(i['pfad']) for i in infos]}")
        # Tabelle neu aufbauen: die gemerkte Gruppe verschwindet sofort (bzw. steht grau am
        # Ende, wenn „Geprüfte Gruppen anzeigen" an ist); nach dem Aufheben ist sie wieder offen.
        namen = ", ".join(os.path.basename(i["pfad"]) for i in infos)
        self._meldung = (f"Gruppe {nr + 1} ({namen}) als geprüft gemerkt und ausgeblendet. "
                         if nr in self.geprueft_nrn else f"Prüfung für Gruppe {nr + 1} ({namen}) aufgehoben. ")
        self._fuelle_tabelle()

    def _zeige_unterschiede(self, info, partner):
        if partner is None:
            self.unterschiede.config(text="")
            return
        nur_links, nur_rechts = dubletten.unterschiede(info.get("text", ""), partner.get("text", ""))
        if not nur_links and not nur_rechts:
            text = "Text von Seite 1 ist wortgleich."
        else:
            text = (f"Nur links: {', '.join(nur_links) or '–'}\n"
                    f"Nur rechts: {', '.join(nur_rechts) or '–'}")
        self.unterschiede.config(text=text)

    def _oeffnen(self):
        auswahl = self.tree.selection()
        if auswahl and auswahl[0] in self.zeilen:
            try:
                os.startfile(self.zeilen[auswahl[0]]["pfad"])
            except OSError as e:
                mb.showerror("Öffnen fehlgeschlagen", str(e), parent=self)

    def _umbenennen(self):
        """
        Markierte Datei umbenennen (Nutzerwunsch 30.08.2026: beim Prüfen zweier ähnlicher
        Briefe fällt oft auf, dass ein Name nichtssagend ist - '..._1.pdf'). Gleiche Regeln
        wie FileOperations.rename_file; die Zeile, die Gruppen und die Vorschau ziehen den
        neuen Pfad nach, die Suche muss nicht neu laufen.
        """
        auswahl = self.tree.selection()
        if not auswahl or auswahl[0] not in self.zeilen:
            return
        iid = auswahl[0]
        info = self.zeilen[iid]
        alt = info["pfad"]
        alter_name = os.path.basename(alt)
        neuer_name = UIUtils.ask_string("Datei umbenennen", f"Neuer Name für '{alter_name}':",
                                            initialvalue=alter_name, parent=self)
        if not neuer_name or neuer_name == alter_name:
            return
        neuer_name = "".join(c for c in neuer_name if c not in r'\/:*?"<>|').strip()
        if not neuer_name:
            return
        if not neuer_name.lower().endswith(".pdf"):
            neuer_name += ".pdf"
        neu = os.path.join(os.path.dirname(alt), neuer_name)
        if os.path.exists(neu):
            mb.showerror("Fehler", "Eine Datei mit diesem Namen existiert bereits.", parent=self)
            return
        self.app.is_moving = True
        try:
            os.rename(alt, neu)
        except OSError as e:
            mb.showerror("Fehler", f"Umbenennen fehlgeschlagen. Ist die Datei noch geöffnet?\n{e}", parent=self)
            return
        finally:
            self.app.is_moving = False
        # Zeile/Gruppen teilen sich dasselbe Info-Dict - Pfad einmal nachziehen reicht
        info["pfad"] = neu
        if alt in self.behalten:
            self.behalten.discard(alt)
            self.behalten.add(neu)
        self.tree.set(iid, "datei", neuer_name)
        if getattr(self.app, "logger", None):
            self.app.logger.info(f"Dubletten: umbenannt {alt} -> {neu}")
        if hasattr(self.app, "tool_manager"):
            self.app.tool_manager.notify_file_moved(alt, neu)
        self.app.folder_manager.sync_ui()
        for vorschau in self.vorschauen:
            if vorschau.pfad == alt:
                vorschau.setze_datei(neu, vorschau.seite)

    def _ausfuehren(self):
        kandidaten = [info for info in self.zeilen.values() if info["pfad"] not in self.behalten]
        if not kandidaten:
            mb.showinfo("Dubletten finden", "Nichts zu verschieben - alle Zeilen stehen auf 'behalten'.", parent=self)
            return
        if not bestaetigung.frage("In den Papierkorb",
                           f"{len(kandidaten)} Datei(en) in den Papierkorb verschieben?\n"
                           "(Nichts wird endgültig gelöscht - der Papierkorb lässt sich wiederherstellen.)",
                           parent=self):
            return
        trash = app_paths.trash_dir(self.app.master_folder)
        os.makedirs(trash, exist_ok=True)
        verschoben, fehler = 0, []
        self.app.is_moving = True
        try:
            for info in kandidaten:
                pfad = info["pfad"]
                ziel = os.path.join(trash, os.path.basename(pfad))
                try:
                    self.app.file_ops._verschiebe_ohne_duplikat(pfad, ziel)
                    verschoben += 1
                    if getattr(self.app, "logger", None):
                        self.app.logger.info(f"Dubletten: {pfad} -> Papierkorb")
                    if hasattr(self.app, "tool_manager"):
                        self.app.tool_manager.notify_file_moved(pfad, ziel)
                except Exception as e:
                    fehler.append(f"{os.path.basename(pfad)}: {e}")
        finally:
            self.app.is_moving = False
            self.app.folder_manager.sync_ui()
        text = f"{verschoben} Datei(en) in den Papierkorb verschoben."
        if fehler:
            text += "\n\nFehler:\n" + "\n".join(fehler)
        mb.showinfo("Dubletten finden", text, parent=self)
        self._starte_suche()
