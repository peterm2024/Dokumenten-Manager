"""
Kurzbefehl-Fenster (Peters Idee 28.10.2026: „Ich bin mir oft nicht sicher, was für Möglichkeiten ich
im aktuell aktiven Bereich habe“): ein kleines, zuschaltbares Fenster im Vordergrund, das zum Bereich
unter Tastatur-Fokus oder Maus die gültigen Tasten und Mausaktionen zeigt, darunter grau die überall
gültigen. Ein/aus über Ansicht → „Kurzbefehle anzeigen (F1)“ oder F1, Zustand und Position werden gemerkt.

EINE Quelle für die Inhalte: BEREICHE/UEBERALL unten. Tasten-Einträge tragen ihre Bindung
(Widget-Attribut, Sequenz) - tests/test_kurzbefehle.py prüft, dass es sie im Code wirklich gibt.
"""

import tkinter as tk
import tkinter.font as tkfont

from ui_utils import UIUtils

EINSTELLUNG_AN = "kurzbefehle_anzeigen"
EINSTELLUNG_POSITION = "kurzbefehle_position"


def _e(taste, wirkung, bindung=None):
    """Ein Katalog-Eintrag; bindung = (Widget-Attribut des Hauptfensters, Tk-Sequenz) für den Test."""
    return {"taste": taste, "wirkung": wirkung, "bindung": bindung}


UEBERALL = [
    _e("← / →", "Vorschau: Seite zurück / vor (nicht in Bäumen und Eingabefeldern)", ("root", "<Left>")),
    _e("Bild↑ / Bild↓", "Vorschau: 3 Seiten zurück / vor (ebenso)", ("root", "<Prior>")),
    _e("Pos1 / Ende", "Vorschau: erste / letzte Seite (nicht in Liste, Bäumen, Eingabefeldern)", ("root", "<Home>")),
    _e("F1", "dieses Fenster ein / aus", ("root", "<F1>")),
    _e("Menü: verweilen", "Erklärung zum Menüeintrag"),
    _e("Doppelklick roter KI-Punkt", "KI-Server wecken (Suchleiste rechts)"),
]

BEREICHE = {
    "dokumentenliste": ("Dokumentenliste", [
        _e("↑ / ↓", "anderes Dokument"),
        _e("← / → / Bild↑ / Bild↓", "Vorschau blättern"),   # Bindung in einer Schleife (layout_builder)
        _e("Pos1 / Ende", "erstes / letztes Dokument", ("tree_files", "<Home>")),
        _e("Strg / Shift + Klick", "mehrere Dokumente markieren"),
        _e("0 – 9", "oranges (vermutetes) Datum überschreiben", ("tree_files", "<Key>")),
        _e("F2", "Datei umbenennen", ("tree_files", "<F2>")),
        _e("Entf", "in den Papierkorb", ("tree_files", "<Delete>")),
        _e("Return / Doppelklick", "im PDF-Programm öffnen", ("tree_files", "<Return>")),
        _e("Ziehen auf Ordner", "verschieben", ("tree_files", "<ButtonRelease-1>")),
        _e("Alt + Ziehen auf Dokument", "dessen Tags übertragen"),
        _e("Rechtsklick", "Menü (auch KI-Werkzeuge)", ("tree_files", "<Button-3>")),
        _e("Klick Spaltenkopf", "sortieren"),
        _e("Rechtsklick Spaltenkopf", "Spalten ein- / ausblenden"),
        _e("Doppelklick Spaltengrenze", "Spaltenbreite anpassen", ("tree_files", "<Double-1>")),
    ]),
    "ordnerbaum": ("Ordnerbaum", [
        _e("Klick", "Ordner öffnen"),
        _e("Klick auf ▷ / ← →", "auf- / zuklappen, ohne zu öffnen", ("tree_folders", "<Button-1>")),
        _e("Pos1 / Ende", "erster / letzter Ordner", ("tree_folders", "<Home>")),
        _e("F2", "Ordner umbenennen", ("tree_folders", "<F2>")),
        _e("Rechtsklick", "Menü: neu, zusammenführen, auf-/zuklappen …", ("tree_folders", "<Button-3>")),
        _e("Dokument hierher ziehen", "Dokument verschieben"),
    ]),
    "tagsuche": ("Tag-Suche", [
        _e("Tippen", "Tag-Baum filtern", ("entry_tag_search", "<KeyRelease>")),
        _e("Return", "in den Tag-Baum, dort Leertaste = zuweisen", ("entry_tag_search", "<Return>")),
        _e("Esc", "Suche leeren", ("entry_tag_search", "<Escape>")),
        _e("F2", "gefundenes Tag umbenennen", ("entry_tag_search", "<F2>")),
        _e("Strg+I", "gefundenes Tag ignorieren", ("entry_tag_search", "<Control-i>")),
    ]),
    "tagbaum": ("Tag-Baum", [
        _e("Doppelklick / Leertaste", "Tag zuweisen / entfernen", ("tree_tags", "<space>")),
        _e("Tippen", "springt in die Tag-Suche", ("tree_tags", "<KeyPress>")),
        _e("F2", "Tag umbenennen", ("tree_tags", "<F2>")),
        _e("Entf", "Tag löschen", ("tree_tags", "<Delete>")),
        _e("Strg+I", "Tag ignorieren (KI schlägt es nicht mehr vor)", ("tree_tags", "<Control-i>")),
        _e("Strg+X / Strg+V", "Tag ausschneiden / woanders einfügen", ("tree_tags", "<Control-x>")),
        _e("Alt+↑ / Alt+↓", "Tag nach oben / unten", ("tree_tags", "<Alt-Up>")),
        _e("Pos1 / Ende", "erstes / letztes Tag", ("tree_tags", "<Home>")),
        _e("Rechtsklick", "Menü (neu, Kategorie, Synonym …)", ("tree_tags", "<Button-3>")),
    ]),
    "suchfeld": ("Suchfeld", [
        _e("Return", "suchen (Tippen allein sucht nicht)", ("entry_search", "<Return>")),
        _e("Feld leeren", "Suche zurücksetzen", ("entry_search", "<KeyRelease>")),
        _e("\"zwei Wörter\"", "genau diese Wortfolge"),
        _e("↓ / ↑, dann Return", "Tag-Vorschlag übernehmen"),
        _e("Haken „Inhalt (OCR)“", "auch im Dokumenttext suchen"),
    ]),
    "suchdatum": ("Zeitraum (Von / Bis)", [
        _e("TT.MM.JJJJ", "genauer Tag", ("entry_date_from", "<KeyRelease>")),
        _e("JJJJ", "ganzes Jahr, z.B. Von 2020 Bis 2022"),
        _e("Return", "suchen", ("entry_date_from", "<Return>")),
    ]),
    "titel": ("Titel", [
        _e("Tippen", "wird automatisch gespeichert (Auto-Save)", ("entry_title", "<KeyRelease>")),
        _e("Tab", "weiter zu den Tags"),
    ]),
    "tags": ("Tags-Feld", [
        _e("Komma", "trennt die Tags"),
        _e("↓ / ↑", "Vorschlag wählen"),
        _e("Return / Tab", "Vorschlag übernehmen, sonst speichern", ("entry_tags", "<Return>")),
        _e("Esc", "Vorschläge schließen"),
    ]),
    "datum": ("Datumsfeld", [
        _e("Return", "Datum speichern, zurück in die Liste", ("date_entry", "<Return>")),
        _e("Esc", "vermutetes Datum zurückholen", ("date_entry", "<Escape>")),
        _e("31.1.25 / 2025-01-31", "beide Schreibweisen gehen"),
        _e("orange hinterlegt", "nur vermutet, noch nicht gespeichert"),
    ]),
    "vorschau": ("Vorschau", [
        _e("Mausrad", "scrollen, am Seitenende blättern", ("canvas_preview", "<MouseWheel>")),
        _e("← / → / Bild↑ / Bild↓", "1 / 3 Seiten zurück / vor (nach Klick in die Vorschau)", ("root", "<Next>")),
        _e("Pos1 / Ende", "erste / letzte Seite (nach Klick in die Vorschau)", ("root", "<End>")),
        _e("Strg + Mausrad", "zoomen", ("canvas_preview", "<Control-MouseWheel>")),
        _e("Ziehen", "Seite verschieben", ("canvas_preview", "<ButtonPress-1>")),
        _e("Doppelklick", "Zoom zurück (einpassen)", ("canvas_preview", "<Double-Button-1>")),
        _e("Doppelklick rechter Greifer", "ganze Seite einpassen"),
    ]),
    "eigenschaften": ("Eigenschaften", [
        _e("Rechtsklick", "Kopieren / Alles kopieren"),
        _e("Verweilen", "abgeschnittenen Wert ganz zeigen"),
        _e("Haken „Details“", "weitere Zeilen ein / aus"),
    ]),
}

# Widget-Attribut des Hauptfensters (Punkt = verschachtelt) -> Bereich
WIDGETS = {
    "tree_files": "dokumentenliste",
    "tree_folders": "ordnerbaum",
    "entry_tag_search": "tagsuche",
    "tree_tags": "tagbaum",
    "entry_search": "suchfeld",
    "entry_date_from": "suchdatum",
    "entry_date_to": "suchdatum",
    "entry_title": "titel",
    "entry_tags": "tags",
    "date_entry": "datum",
    "canvas_preview": "vorschau",
    "eigenschaften_panel.tabelle": "eigenschaften",
}


def position_sichtbar(position, bildschirm_breite, bildschirm_hoehe, rand=100):
    """Liegt eine gemerkte Position '+x+y' noch auf dem Bildschirm? (Zweiter Monitor abgesteckt -> nein)"""
    try:
        _, x, y = position.split("+")
        x, y = int(x), int(y)
    except (AttributeError, ValueError):
        return False
    return 0 <= x <= bildschirm_breite - rand and 0 <= y <= bildschirm_hoehe - rand


def _attribut(app, pfad):
    obj = app
    for teil in pfad.split("."):
        obj = getattr(obj, teil, None)
        if obj is None:
            return None
    return obj


def bereich_fuer(app, widget):
    """
    Bereich eines Widgets: es selbst oder das nächste Eltern-Widget, das ein bekannter Bereich ist
    (Tk-Pfade wie '.!panedwindow.!frame2.!treeview'). Eingabefelder in der Eigenschaften-Tabelle
    (Titel, Datum) treffen vor der Tabelle. :return: Schlüssel aus BEREICHE oder None
    """
    bekannte = {}
    for attr, bereich in WIDGETS.items():
        w = _attribut(app, attr)
        if w is not None:
            bekannte[str(w)] = bereich
    pfad = str(widget) if widget is not None else ""
    while pfad:
        if pfad in bekannte:
            return bekannte[pfad]
        if pfad == ".":
            return None
        pfad = pfad.rsplit(".", 1)[0] or "."
    return None


class Kurzbefehle:
    """Steuert das Fenster: an/aus (Menü, F1), verfolgt den aktiven Bereich, merkt Zustand und Position."""

    def __init__(self, app):
        self.app = app
        self.fenster = None
        self.inhalt = None
        self.bereich = "dokumentenliste"
        self._positions_timer = None
        self.var = tk.BooleanVar(value=bool(app.config.get(EINSTELLUNG_AN, False)))
        root = app.root
        root.bind_all("<FocusIn>", self._ereignis, add="+")
        root.bind_all("<Enter>", self._ereignis, add="+")
        root.bind("<F1>", self.umschalten)
        if self.var.get():
            root.after(800, self._zeigen)

    # ---------------------------------------------------------------- an / aus
    def umschalten(self, event=None):
        """F1: Fenster ein/aus."""
        self.var.set(not self.var.get())
        self.anwenden()
        return "break"

    def anwenden(self):
        """Menü-Häkchen bzw. umschalten: Zustand übernehmen, merken, Fenster zeigen/schließen."""
        self.app.config.set(EINSTELLUNG_AN, bool(self.var.get()))
        if self.var.get():
            self._zeigen()
        else:
            self._verstecken()

    def _schliessen_x(self):
        self.var.set(False)
        self.anwenden()

    # ---------------------------------------------------------------- Bereich verfolgen
    def _ereignis(self, event):
        try:
            bereich = bereich_fuer(self.app, event.widget)
        except (tk.TclError, AttributeError):
            return
        if bereich and bereich != self.bereich:
            self.bereich = bereich
            if self.fenster is not None:
                self._fuellen()

    # ---------------------------------------------------------------- Fenster
    def _zeigen(self):
        if self.fenster is not None:
            try:
                self.fenster.lift()
                return
            except tk.TclError:
                self.fenster = None
        root = self.app.root
        vorher = root.focus_get()
        bereich = bereich_fuer(self.app, vorher)
        if bereich:
            self.bereich = bereich
        f = tk.Toplevel(root)
        f.title("Kurzbefehle")
        f.transient(root)
        try:
            f.attributes("-toolwindow", True)
        except tk.TclError:
            pass
        f.resizable(False, False)
        f.protocol("WM_DELETE_WINDOW", self._schliessen_x)
        f.bind("<F1>", self.umschalten)
        position = self.app.config.get(EINSTELLUNG_POSITION, "")
        if not position_sichtbar(position, root.winfo_screenwidth(), root.winfo_screenheight()):
            root.update_idletasks()
            x = root.winfo_rootx() + root.winfo_width() - UIUtils.px(root, 420)
            y = root.winfo_rooty() + root.winfo_height() - UIUtils.px(root, 470)
            position = f"+{max(x, 0)}+{max(y, 0)}"
        f.geometry(position)
        f.bind("<Configure>", self._position_spaeter)
        self.fenster = f
        self.inhalt = tk.Frame(f, padx=UIUtils.px(f, 10), pady=UIUtils.px(f, 8))
        self.inhalt.pack(fill=tk.BOTH, expand=True)
        self._fuellen()
        # Das neue Fenster soll die Tastatur nicht wegnehmen: Fokus zurück, wo er war
        if vorher is not None:
            root.after(50, lambda: self._fokus_zurueck(vorher))

    @staticmethod
    def _fokus_zurueck(widget):
        try:
            widget.focus_force()
        except tk.TclError:
            pass

    def _verstecken(self):
        if self.fenster is None:
            return
        self._position_merken()
        try:
            self.fenster.destroy()
        except tk.TclError:
            pass
        self.fenster = None
        self.inhalt = None

    def _position_spaeter(self, event=None):
        # <Configure> feuert bei jedem Pixel - gemerkt wird erst, wenn Ruhe ist (CLAUDE.md: Debounce)
        if self._positions_timer is not None:
            self.app.root.after_cancel(self._positions_timer)
        self._positions_timer = self.app.root.after(500, self._position_merken)

    def _position_merken(self):
        self._positions_timer = None
        try:
            if self.fenster is not None and self.fenster.winfo_exists():
                self.app.config.set(EINSTELLUNG_POSITION, f"+{self.fenster.winfo_x()}+{self.fenster.winfo_y()}")
        except tk.TclError:
            pass

    def _fuellen(self):
        if self.inhalt is None:
            return
        for kind in self.inhalt.winfo_children():
            kind.destroy()
        titel, eintraege = BEREICHE.get(self.bereich, BEREICHE["dokumentenliste"])
        fett = tkfont.nametofont("TkDefaultFont").copy()
        fett.configure(weight="bold")
        self._fett = fett   # Referenz halten, sonst räumt Python die Schrift ab
        breite = UIUtils.px(self.inhalt, 250)
        tk.Label(self.inhalt, text=f"Hier: {titel}", font=fett, anchor="w").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, UIUtils.px(self.inhalt, 4)))
        zeile = 1
        for eintrag in eintraege:
            tk.Label(self.inhalt, text=eintrag["taste"], font=fett, anchor="nw", justify="left").grid(
                row=zeile, column=0, sticky="nw", padx=(0, UIUtils.px(self.inhalt, 12)))
            tk.Label(self.inhalt, text=eintrag["wirkung"], anchor="nw", justify="left", wraplength=breite).grid(
                row=zeile, column=1, sticky="nw")
            zeile += 1
        tk.Frame(self.inhalt, height=1, bg="#c8c8c8").grid(
            row=zeile, column=0, columnspan=2, sticky="ew", pady=UIUtils.px(self.inhalt, 6))
        zeile += 1
        tk.Label(self.inhalt, text="Überall", fg="#777777", anchor="w").grid(row=zeile, column=0, sticky="w")
        zeile += 1
        for eintrag in UEBERALL:
            tk.Label(self.inhalt, text=eintrag["taste"], fg="#777777", anchor="nw", justify="left").grid(
                row=zeile, column=0, sticky="nw", padx=(0, UIUtils.px(self.inhalt, 12)))
            tk.Label(self.inhalt, text=eintrag["wirkung"], fg="#777777", anchor="nw", justify="left",
                     wraplength=breite).grid(row=zeile, column=1, sticky="nw")
            zeile += 1
