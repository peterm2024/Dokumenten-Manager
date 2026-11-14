"""
Vollautomatik-Tools des Seniorenmodus - Schritte 1-3 (KONZEPT_SENIORENMODUS.md).

Beide Tools teilen sich dasselbe Fenster (AutoFilerPreviewWindow), unterscheiden
sich nur darin, WOHER die Arbeitsliste kommt:
- AutoFilerTool ("Ablage-Vorschau"): die aktuell markierten Dokumente.
- AutoFilerInboxTool ("Posteingang verarbeiten", Schritt 3): der komplette
  Posteingang, ohne dass vorher etwas markiert werden muss - ein Knopf für den
  ganzen Stapel, Analyse startet von selbst.

Innerhalb eines Laufs wachsen neu vorgeschlagene Ordner sofort in die Abgleich-
liste hinein, damit Schreibvarianten desselben Absenders ("Gentilia" / "Gentilia
Deutschland Versicherung AG") EINEN Ordner ergeben statt mehrerer.

Das Fenster zeigt, WAS die Vollautomatik täte: Titel, Tags, Dokumentdatum,
Zielordner (ggf. neu) und ob die Ablage als "sicher" gelten würde - inklusive
Begründung, wenn nicht. Ein Klick auf die Zielordner-Zelle öffnet eine Auswahl
(Tippen filtert die Ordnerliste); der gewählte Ordner gilt für ALLE Zeilen dieses
Absenders und wird als Alias gemerkt (ordner_aliase.py) - so lernt die Automatik
Weltwissen wie "Landesbrandversicherung -> Versicherungskasse Musterland". Titel und
Datum lassen sich per Klick ebenfalls korrigieren (zeilenlokal, kein Alias) - ein
fehlendes Datum ist sonst der häufigste Grund, warum ein Dokument nach Unsicher wandert.
Ein Klick auf die Ergebnis-Zelle gibt eine unsichere Zeile nach eigener Prüfung manuell
frei (z.B. geprüfter Dubletten-Verdacht) - die Gründe bleiben sichtbar und stehen mit
im Protokoll. Der Button "Jetzt einsortieren" führt die Entscheidung
anschließend tatsächlich aus (Metadaten schreiben, umbenennen, verschieben bzw.
unverändert nach 0_Unsicher) - erst auf expliziten Klick, die reine Analyse
verändert nichts.
"""

import os
import threading
import tkinter as tk
import tkinter.messagebox as mb
import bestaetigung
from tkinter import ttk

import ablage_gedaechtnis
import aktivitaet
import app_paths
import auto_pilot
import dubletten_pruefung
import ollama_client
import ordner_aliase
import tag_ignorierliste
from auto_pilot_service import STAPEL_GROESSE
from tools.base_tool import BaseTool, ToolContext
from ui_utils import UIUtils, ProgressDialog


class AutoFilerTool(BaseTool):
    def __init__(self):
        self.window = None

    @property
    def name(self) -> str:
        return "Vollautomatik: Ablage-Vorschau"

    @property
    def menu_group(self) -> str:
        return "Vollautomatik"

    @property
    def menu_label(self) -> str:
        return "Ablage-Vorschau für markierte Dokumente…"

    @property
    def absicht(self) -> str:
        return ("Vertrauen in die Vollautomatik aufbauen: zeigt Zielordner, Titel und Datum, die die Automatik vergeben würde, BEVOR etwas passiert; Tags setzt sie keine, sie lassen sich hier von Hand eintragen. Ein Klick auf den richtigen Zielordner lehrt sie einen Alias.")

    @property
    def description(self) -> str:
        return "Zeigt, wie die Vollautomatik die ausgewählten Dokumente ablegen würde (ohne etwas zu verändern)."

    @property
    def braucht_ki(self) -> bool:
        return True   # ohne KI-Server sinnlos - Menüeintrag wird dann gesperrt (ki_status)

    @property
    def menu_hooks(self) -> list:
        return ["context_menu", "main_menu"]

    @property
    def required_input(self) -> str:
        return "multiple_files"

    def execute(self, context: ToolContext) -> bool:
        pdf_paths = [p for p in context.selected_files if p.lower().endswith(".pdf")]
        if not pdf_paths:
            mb.showinfo("Hinweis", "Bitte mindestens ein PDF auswählen.")
            return False
        if self.window and self.window.winfo_exists():
            self.window.destroy()
        self.window = AutoFilerPreviewWindow(context.app, pdf_paths)
        return True


class ZielordnerDialog(tk.Toplevel):
    """
    Kleine Ordner-Auswahl: Eingabefeld mit Autovervollständigung (jeder Tastendruck filtert
    die Liste darunter, Groß/Klein egal), Enter/Doppelklick übernimmt den markierten
    Listeneintrag - oder den getippten Text, wenn kein Eintrag passt (dann wird der Ordner
    neu angelegt). Ergebnis in self.ergebnis (None = abgebrochen).
    """

    def __init__(self, parent, ordnerliste, vorgabe, absender, ueberschrift=None, mit_reichweite=True, art="Absender",
                 titel="Zielordner wählen"):
        super().__init__(parent)
        self.ergebnis = None
        self.fuer_alle = False   # nach dem Schließen: galt die Wahl für den ganzen Absender?
        self.ordnerliste = sorted(ordnerliste, key=str.lower)
        self.title(titel)        # auch für andere Listen nutzbar („Person ist dieselbe wie…“)
        self.transient(parent)
        UIUtils.position_near_mouse(self, UIUtils.px(self, 520), UIUtils.px(self, 480))

        ttk.Label(self, text=ueberschrift or "Zielordner für dieses Dokument wählen:",
                  wraplength=UIUtils.px(self, 500),
                  anchor="w").pack(fill=tk.X, padx=10, pady=(10, 5))
        self.var = tk.StringVar(value=vorgabe or "")
        self.entry = ttk.Entry(self, textvariable=self.var)
        self.entry.pack(fill=tk.X, padx=10)
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.liste = tk.Listbox(frame, activestyle="dotbox", exportselection=False)
        scroll = ttk.Scrollbar(frame, command=self.liste.yview)
        self.liste.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.liste.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Reichweite der Korrektur (Nutzerfund 31.08.2026): Bisher wurde JEDE Wahl sofort
        # als Absender-Alias gespeichert und auf alle Zeilen des Absenders angewandt - ein
        # einziger Klick konnte damit ganze Absender dauerhaft in den falschen Ordner lenken
        # ("Landratsamt Musterstadt -> Haus- und Grund Musterstadt"). Deshalb ist "nur dieses eine
        # Dokument" jetzt die Vorgabe; das Alias-Lernen ist eine bewusste Entscheidung.
        self._reichweite = tk.IntVar(value=0)
        if absender and mit_reichweite:
            wahl = ttk.Frame(self)
            wahl.pack(fill=tk.X, padx=10, pady=(0, 4))
            ttk.Radiobutton(wahl, text="Nur dieses eine Dokument",
                            variable=self._reichweite, value=0).pack(anchor="w")
            if art == "Objekt":
                # Eigenbeleg ohne Absender: der Alias hängt am Objekt (ordner_aliase.OBJEKT_PRAEFIX)
                text = (f"Alle Belege ohne Absender zu '{ordner_aliase.objekt_aus_schluessel(absender)}'"
                        " — auch künftige (Objekt-Alias)")
            else:
                text = f"Alle Dokumente von '{absender}' — auch künftige (wird als Alias gemerkt)"
            # Umbrechen statt rechts abschneiden - bei langen Absendernamen fehlte sonst das Ende
            # des Satzes (Release-Check T0.12, 25.10.2026)
            ttk.Style(self).configure("Umbruch.TRadiobutton", wraplength=UIUtils.px(self, 480))
            ttk.Radiobutton(wahl, variable=self._reichweite, value=1, text=text,
                            style="Umbruch.TRadiobutton").pack(anchor="w")

        buttons = ttk.Frame(self)
        buttons.pack(pady=(0, 10))
        ttk.Button(buttons, text="Übernehmen", command=self._uebernehmen).pack(side=tk.LEFT, padx=5)
        ttk.Button(buttons, text="Abbrechen", command=self.destroy).pack(side=tk.LEFT, padx=5)

        self.entry.bind("<KeyRelease>", self._filtern)
        self.entry.bind("<Down>", lambda e: self._bewegen(1))
        self.entry.bind("<Up>", lambda e: self._bewegen(-1))
        self.entry.bind("<Return>", lambda e: self._uebernehmen())
        self.liste.bind("<Return>", lambda e: self._uebernehmen())
        self.liste.bind("<Double-Button-1>", lambda e: self._uebernehmen())
        self.bind("<Escape>", lambda e: self.destroy())
        self._filtern()
        self.entry.focus_set()
        self.entry.select_range(0, tk.END)
        self.grab_set()

    def _filtern(self, event=None):
        """Liste auf Einträge einschränken, die den getippten Text enthalten; ersten Treffer markieren."""
        if event is not None and event.keysym in ("Up", "Down", "Return", "Escape"):
            return
        gesucht = self.var.get().strip().lower()
        self.liste.delete(0, tk.END)
        for ordner in self.ordnerliste:
            if gesucht in ordner.lower():
                self.liste.insert(tk.END, ordner)
        if self.liste.size():
            self.liste.selection_set(0)
            self.liste.activate(0)

    def _bewegen(self, schritt):
        """Pfeiltasten im Eingabefeld wandern durch die gefilterte Liste."""
        if not self.liste.size():
            return "break"
        aktuell = self.liste.curselection()
        neu = min(max((aktuell[0] if aktuell else 0) + schritt, 0), self.liste.size() - 1)
        self.liste.selection_clear(0, tk.END)
        self.liste.selection_set(neu)
        self.liste.activate(neu)
        self.liste.see(neu)
        return "break"

    def _uebernehmen(self):
        """Markierter Listeneintrag gewinnt; ohne Treffer in der Liste zählt der getippte Text (neuer Ordner)."""
        auswahl = self.liste.curselection()
        getippt = self.var.get().strip().strip("\\/")
        if auswahl:
            wert = self.liste.get(auswahl[0])
        else:
            wert = getippt
        if not wert:
            return
        self.ergebnis = wert
        self.fuer_alle = bool(self._reichweite.get())
        self.destroy()


class AliasVerwaltungDialog(tk.Toplevel):
    """
    Gemerkte Absender-Zuordnungen (aliase.json) ansehen und löschen (Nutzerfund
    31.08.2026: ein falsch gelernter Alias wie „Landratsamt Musterstadt → Haus- und Grund
    Musterstadt" lenkte ganze Absender dauerhaft in den falschen Ordner, und es gab keinen
    Weg, das in der Oberfläche zu sehen oder zu korrigieren). Löschen ist folgenarm:
    bereits abgelegte Dokumente bleiben, wo sie sind — es fällt nur der Wegweiser weg,
    und der Namensvergleich (finde_passenden_ordner) übernimmt wieder.
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("Gemerkte Zuordnungen (Absender und Objekte)")
        self.transient(parent)
        UIUtils.position_near_mouse(self, UIUtils.px(self, 720), UIUtils.px(self, 420))

        ttk.Label(self, wraplength=UIUtils.px(self, 690), anchor="w", justify=tk.LEFT, text=(
            "Diese Zuordnungen hat die Automatik aus deinen Korrekturen gelernt: Dokumente des "
            "Absenders links wandern immer in den Ordner rechts — vor jedem Namensvergleich. "
            "Ein falscher Eintrag lenkt also ganze Absender um. Einträge „Objekt: …“ gelten nur für "
            "Dokumente OHNE Absender (Notizen, Zählerstände, Mieterlisten) und ordnen sie über ihr "
            "Objekt zu. Löschen schadet nicht: schon "
            "abgelegte Dokumente bleiben liegen, künftige werden wieder normal zugeordnet.")
        ).pack(fill=tk.X, padx=10, pady=(10, 5))

        rahmen = ttk.Frame(self)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.tree = ttk.Treeview(rahmen, columns=("absender", "ordner"), show="headings", selectmode="browse")
        self.tree.heading("absender", text="Absender oder „Objekt: …“ (wie von der KI erkannt)")
        self.tree.heading("ordner", text="wandert immer in den Ordner")
        for spalte, breite in (("absender", 300), ("ordner", 360)):
            px = UIUtils.px(self, breite)
            self.tree.column(spalte, width=px, minwidth=px, anchor="w")
        scroll = ttk.Scrollbar(rahmen, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        rahmen.rowconfigure(0, weight=1)
        rahmen.columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<Delete>", lambda e: self._loeschen())

        knoepfe = ttk.Frame(self)
        knoepfe.pack(pady=(0, 10))
        ttk.Button(knoepfe, text="Zuordnung löschen (Entf)", command=self._loeschen).pack(side=tk.LEFT, padx=5)
        ttk.Button(knoepfe, text="Schließen", command=self.destroy).pack(side=tk.LEFT, padx=5)
        self.bind("<Escape>", lambda e: self.destroy())
        self._fuelle()

    def _fuelle(self):
        self.tree.delete(*self.tree.get_children())
        aliase = ordner_aliase.lade_aliase(self.app.master_folder)
        for absender in sorted(aliase, key=str.lower):
            self.tree.insert("", tk.END, values=(absender, aliase[absender]))
        if not aliase:
            self.tree.insert("", tk.END, values=("(keine gemerkten Zuordnungen)", ""))

    def _loeschen(self):
        auswahl = self.tree.selection()
        if not auswahl:
            return
        absender = self.tree.item(auswahl[0], "values")[0]
        if absender == "(keine gemerkten Zuordnungen)":
            return
        try:
            ordner_aliase.loesche_alias(self.app.master_folder, absender)
        except OSError as e:
            mb.showwarning("Löschen fehlgeschlagen", f"Die Zuordnung konnte nicht entfernt werden:\n{e}",
                           parent=self)
            return
        if hasattr(self.app, "logger") and self.app.logger:
            self.app.logger.info(f"Absender-Alias gelöscht: {absender}")
        self._fuelle()


class AutoFilerPreviewWindow(tk.Toplevel):
    """Vorschau-Tabelle: eine Zeile pro Dokument, gefüllt durch die KI-Analyse im Hintergrund."""

    def __init__(self, app, pdf_paths, fenstertitel="Vollautomatik — Ablage-Vorschau", auto_start=False):
        super().__init__(app.root)
        self.app = app
        self.pdf_paths = pdf_paths
        self.ergebnisse = {}  # iid -> entscheidung-Dict (auto_pilot.baue_entscheidung), None bei KI-Fehler
        self.ordnerliste = []  # Abgleichliste des laufenden/letzten Analyse-Laufs (wächst um neue Ordner)
        self.neue_ordner = set()
        self.aliase = {}       # Absender-Aliase der Sammlung (ordner_aliase), von der Analyse geladen
        self.einsortiert = False  # nach "Jetzt einsortieren" ist die Tabelle nur noch Protokoll
        self.title(fenstertitel)
        # Feste Maße mitskalieren: bei 125 % Schrift passte sonst nichts mehr ins Fenster
        UIUtils.position_near_mouse(self, UIUtils.px(self, 1200), UIUtils.px(self, 460))
        # Bewusst KEIN transient(app.root): das nimmt dem Fenster unter Windows die
        # Maximieren-Schaltfläche (Nutzerwunsch 01.09.2026 - bei einem großen Stapel will
        # man die Tabelle aufziehen). Gleiche Lösung wie im Dubletten-Finder.
        self._setup_ui()
        # Watchdog-Vollautomatik (Schritt 4) anhalten, solange dieses Fenster lebt - sonst
        # würden Mensch und Hintergrund-Dienst dieselben Posteingang-Dateien bearbeiten.
        self._dienst = getattr(app, "auto_pilot_service", None)
        # Bisher gelesene KI-Orte (auto_pilot.merke_orte): dieselbe Menge wie die Vollautomatik, damit
        # beide bis zum Programmende voneinander lernen; ohne Dienst nur für dieses Fenster
        self.orte = getattr(self._dienst, "orte", None)
        if not isinstance(self.orte, set):
            self.orte = set()
        if self._dienst is not None:
            self._dienst.pausieren()
            self.bind("<Destroy>", self._bei_zerstoerung)
        if auto_start:
            # Bewusst verzögert: _starte_analyse prüft zuerst die Server-Erreichbarkeit
            # (Netzwerk-Timeout) und öffnet einen ProgressDialog - direkt im Konstruktor
            # aufgerufen würde beides das Zeichnen des noch leeren Fensters blockieren.
            self.after(100, self._starte_analyse)

    def _bei_zerstoerung(self, event):
        # <Destroy> feuert auch für jedes Kind-Widget - nur das Fenster selbst zählt.
        if event.widget is self and self._dienst is not None:
            self._dienst.fortsetzen()
            self._dienst = None

    def _setup_ui(self):
        columns = ("datei", "titel", "tags", "datum", "ziel", "status")
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))
        # selectmode "extended": eine ausgewählte Zeile wird im Hauptfenster angezeigt,
        # mehrere Zeilen lassen sich gemeinsam bearbeiten (Nutzerwunsch 01.09.2026).
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="extended")
        for col, text, width in (
            ("datei", "Datei", 220), ("titel", "Titel (KI)", 220), ("tags", "Tags", 160),
            ("datum", "Datum", 85), ("ziel", "Zielordner", 170), ("status", "Ergebnis", 300),
        ):
            breite = UIUtils.px(self, width)
            self.tree.heading(col, text=text)
            # stretch=False + minwidth: die Spalten behalten ihre Breite, statt sich auf
            # Unlesbarkeit zusammenzuquetschen - dafür gibt es die waagerechte Bildlaufleiste
            # (Nutzerwunsch 31.08.2026: "UNSICHER: kein plausib..." war abgeschnitten).
            self.tree.column(col, width=breite, minwidth=breite,
                             stretch=(col == "status"))   # nur die letzte Spalte füllt Restplatz
        self.tree.tag_configure("sicher", background="#e6f4e6")    # grünlich
        self.tree.tag_configure("unsicher", background="#fdf3d7")  # gelblich
        self.tree.tag_configure("fehler", background="#f8d7da")    # rötlich
        scroll = ttk.Scrollbar(frame, command=self.tree.yview)
        scroll_x = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=scroll_x.set)
        # Gitter statt pack: sonst reicht die senkrechte Leiste über die waagerechte hinweg
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")
        self.tree.bind("<Button-1>", self._on_klick)
        self.tree.bind("<<TreeviewSelect>>", self._sync_hauptfenster)
        self.tree.bind("<<TreeviewSelect>>", self._zeige_ergebnis_volltext, add="+")

        # Volltext der Ergebnis-Spalte (Nutzerwunsch 06.09.2026: "kann die Ergebnis-Spalte
        # nur sehr umständlich lesen"): Die Hinweise sind mit Dubletten-/KI-Zweitprüfungs-
        # Vermerken länger als jede sinnvolle Spaltenbreite - die ausgewählte Zeile zeigt
        # ihr Ergebnis deshalb ungekürzt und umgebrochen direkt unter der Tabelle.
        self.lbl_ergebnis = ttk.Label(self, anchor="w", justify=tk.LEFT,
                                      wraplength=UIUtils.px(self, 1160))
        self.lbl_ergebnis.pack(fill=tk.X, padx=10, pady=(0, 5))
        # Umbruchbreite wächst beim Maximieren mit (siehe _passe_umbruchbreite_an)
        self.lbl_ergebnis.bind("<Configure>", self._passe_umbruchbreite_an)

        self.rows = {}
        for path in self.pdf_paths:
            iid = self.tree.insert("", tk.END, values=(os.path.basename(path), "", "", "", "", "noch nicht analysiert"))
            self.rows[iid] = path

        hinweis = ttk.Label(
            self, anchor="w", foreground="gray40", wraplength=UIUtils.px(self, 1060),
            text=("Erst Analyse starten (verändert nichts). Eine ausgewählte Zeile wird zur Kontrolle "
                  "im Hauptfenster angezeigt, ihr vollständiges Ergebnis steht direkt über diesem Text. "
                  "Grün = würde vollautomatisch abgelegt, "
                  "Gelb = würde in den Unsicher-Ordner wandern (Begründung in 'Ergebnis'). "
                  "Klick auf Zielordner, Titel, Tags oder Datum korrigiert die Zeile - beim Zielordner "
                  "wahlweise für alle Dokumente des Absenders (wird dann als Zuordnung gemerkt, "
                  "einsehbar unter 'Gemerkte Zuordnungen…'). "
                  "Klick auf 'Ergebnis' einer gelben Zeile: nach eigener Prüfung trotzdem "
                  "automatisch ablegen (manuelle Freigabe); bei einer grünen Zeile: doch nicht automatisch "
                  "ablegen, sondern in den Unsicher-Ordner (wird gelb). "
                  "Tags mit '(neu→Kategorie)' kommen beim Einsortieren in den Tag-Katalog. "
                  "'Jetzt einsortieren' führt das dann tatsächlich aus."))
        hinweis.pack(fill=tk.X, padx=10, pady=(0, 5))

        button_frame = ttk.Frame(self)
        button_frame.pack(pady=(0, 10))
        self.btn_analyse = ttk.Button(button_frame, text="Analyse starten (KI)", command=self._starte_analyse)
        self.btn_analyse.pack(side=tk.LEFT, padx=5)
        self.btn_einsortieren = ttk.Button(
            button_frame, text="Jetzt einsortieren", command=self._starte_einsortierung, state=tk.DISABLED)
        self.btn_einsortieren.pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Gemerkte Zuordnungen…",
                   command=self._oeffne_alias_verwaltung).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Schließen", command=self.destroy).pack(side=tk.LEFT, padx=5)

    def _passe_umbruchbreite_an(self, event):
        """
        Hält die wraplength des Volltext-Labels auf der Fensterbreite. Nur bei echter
        Breitenänderung neu setzen - die Debounce-Regel für <Configure> (FALLSTRICKE)
        zielt auf teures Neuzeichnen; hier ändert wraplength nur die Label-HÖHE, die
        Breite bestimmt weiterhin pack(fill=X), daher keine Ereignis-Schleife.
        """
        breite = max(200, event.width - 10)
        try:
            aktuell = int(str(self.lbl_ergebnis.cget("wraplength")))
        except (ValueError, tk.TclError):
            aktuell = 0
        if abs(breite - aktuell) > 20:
            self.lbl_ergebnis.config(wraplength=breite)

    def _zeige_ergebnis_volltext(self, event=None):
        """Volltext der Ergebnis-Spalte für die ausgewählte Zeile (Nutzerwunsch 06.09.2026)."""
        auswahl = self.tree.selection()
        if len(auswahl) == 1 and self.tree.exists(auswahl[0]):
            text = self.tree.set(auswahl[0], "status")
            self.lbl_ergebnis.config(text=f"{self.tree.set(auswahl[0], 'datei')}:  {text}" if text else "")
        else:
            self.lbl_ergebnis.config(text="")

    def _starte_analyse(self):
        base_url = self.app.config.get("ollama_url", ollama_client.DEFAULT_URL)
        model = self.app.config.get("ollama_model", ollama_client.DEFAULT_MODEL)
        if not ollama_client.is_reachable(base_url):
            mb.showwarning(
                "Ollama nicht erreichbar",
                f"Der KI-Server unter {base_url} antwortet nicht.\n"
                "Server-Adresse in den Einstellungen prüfen, oder Ollama lokal/im Netzwerk starten.",
                parent=self)
            return
        # Rechnet das Modell auf der Grafikkarte? Sonst läuft jeder Bild-Aufruf in den
        # Timeout (FALLSTRICKE #67) - vorher fragen statt still scheitern.
        with aktivitaet.phase("Prüfe Grafikkarte des KI-Servers…"):
            status, details = ollama_client.gpu_status(base_url, model)
        # Bei zugelassenem CPU-Betrieb (Einstellung ki_cpu_erlauben) entfällt die Rückfrage.
        if status == "cpu" and not bool(self.app.config.get("ki_cpu_erlauben", False)) and not mb.askyesno(
                "KI rechnet auf der CPU",
                f"Das Modell {model} liegt NICHT im Grafikspeicher ({details}).\n"
                "Jeder Aufruf mit Seitenbild dauert dann Minuten und läuft in den Timeout.\n\n"
                "Auf dem Server prüfen: nvidia-smi - bei „Driver/library version mismatch“ die VM neu starten.\n\n"
                "Trotzdem analysieren?", parent=self, icon="warning"):
            return

        known_tags = self.app.tag_manager.get_known_tags() if hasattr(self.app, "tag_manager") else []
        kategorien = self.app.tag_manager.get_kategorien() if hasattr(self.app, "tag_manager") else []
        # Auto-Hierarchie (Nutzerwunsch 04.09.2026): Oberkategorien des Tag-Baums kommen
        # zu jedem vergebenen Unter-Tag dazu - liest den Tag-Baum, also NUR hier im Hauptthread.
        tag_eltern = self.app.tag_manager.get_tag_eltern() if hasattr(self.app, "tag_manager") else {}
        # Synonym-Knoten (08.09.2026): KI-Text -> Tag darüber; liest ebenfalls den Tag-Baum.
        synonyme = self.app.tag_manager.get_synonyme() if hasattr(self.app, "tag_manager") else {}
        # Unterscheidungs-Tags fuer die Dubletten-Pruefung (Stufe B): NUR hier im Hauptthread
        # lesbar (tags_in_kategorie greift auf den Tag-Baum zu).
        merkmale = (self.app.tag_manager.merkmale_fuer_dubletten()
                    if hasattr(self.app, "tag_manager") else {})
        dubletten_cache = {}
        # Als Attribute, damit die Zielordner-Korrektur (_setze_zielordner) dieselben Listen
        # sieht und erweitert, die der Worker nutzt - ein während der Analyse gesetzter Alias
        # wirkt so schon auf die restlichen Dokumente des Stapels.
        ordnerliste = self.ordnerliste = auto_pilot.sammle_ordnerliste(self.app.master_folder)
        self.aliase = ordner_aliase.lade_aliase(self.app.master_folder)
        ignorierte = tag_ignorierliste.lade(self.app.master_folder)

        self.ergebnisse = {}
        self.neue_ordner = set()  # in DIESEM Lauf vorgeschlagene, noch nicht existierende Ordner
        self.btn_analyse.config(state=tk.DISABLED)
        self.btn_einsortieren.config(state=tk.DISABLED)
        dialog = ProgressDialog(self, "Vollautomatik-Analyse", "Wird analysiert...")
        items = list(self.rows.items())

        def worker():
            # Wortschatz für die Titel-Korrektur (Hebel gegen KI-Lesefehler wie
            # 'Musterbein' statt 'Musterheim'): persistierter Sammlungs-Wortschatz + erste
            # Seiten des Stapels. Läuft hier im Hintergrund-Thread - wortschatz_der_sammlung
            # öffnet dafür seine eigene SQLite-Verbindung.
            vocabulary = None
            try:
                basis = self.app.index_manager.wortschatz_der_sammlung() if hasattr(self.app, "index_manager") else None
                vocabulary = auto_pilot.baue_titel_wortschatz([p for _, p in items], basis)
            except Exception as e:
                if hasattr(self.app, "logger") and self.app.logger:
                    self.app.logger.warning(f"Titel-Wortschatz konnte nicht aufgebaut werden: {e}")
            # Ablage-Gedächtnis (eigene SQLite-Verbindung, daher hier im Hintergrund-Thread erlaubt)
            gedaechtnis = ablage_gedaechtnis.lade(getattr(self.app, "index_manager", None),
                                                  auto_pilot.ordner_fuer_zweitmeinung(ordnerliste),
                                                  getattr(self.app, "logger", None))
            entscheidungsmodell = self.app.config.get("ki_entscheidungsmodell", "")

            def regeln():
                # Frisch je Aufruf: ein während der Analyse gesetzter Alias ersetzt self.aliase, und
                # neue Tags/Kandidaten zählen ab dem nächsten Dokument (siehe unten)
                return dict(vocabulary=vocabulary, aliase=self.aliase, known_tags=known_tags, kategorien=kategorien,
                            ignorierte_tags=ignorierte, tag_eltern=tag_eltern, synonyme=synonyme,
                            gedaechtnis=gedaechtnis, orte=self.orte)

            # Stapelbetrieb je Modell (wie die Vollautomatik, 28.10.2026): je Stapel erst alle Dokumente
            # lesen (Lesemodell), dann alle Zweitmeinungen (Entscheidungsmodell), dann der Reihe nach
            # entscheiden - Ollama lädt so ~2x je Stapel um statt ~2x je Dokument
            fertig = 0
            for anfang in range(0, len(items), STAPEL_GROESSE):
                if dialog.should_stop():
                    break
                stapel = []
                for iid, path in items[anfang:anfang + STAPEL_GROESSE]:
                    if dialog.should_stop():
                        break
                    self.after(0, dialog.update_progress, fertig, len(items),
                               f"Lese {os.path.basename(path)} ({len(stapel) + anfang + 1}/{len(items)})…")
                    try:
                        gelesen = auto_pilot.lies_dokument(path, known_tags, base_url, model, kategorien)
                        auto_pilot.merke_orte(self.orte, gelesen)
                    except Exception as e:
                        if hasattr(self.app, "logger") and self.app.logger:
                            self.app.logger.warning(f"Vollautomatik-Analyse fehlgeschlagen für {path}: {e}")
                        gelesen = None
                    stapel.append((iid, path, gelesen))
                ordner_stand = len(ordnerliste)
                if entscheidungsmodell:
                    self.after(0, dialog.update_progress, fertig, len(items), "Zweitmeinungen zur Ordnerwahl…")
                ranglisten = auto_pilot.zweitmeinungen_fuer_stapel(
                    [g for _, _, g in stapel if g is not None], ordnerliste, base_url, entscheidungsmodell,
                    abbrechen=dialog.should_stop, **regeln())
                for iid, path, gelesen in stapel:
                    if dialog.should_stop():
                        break
                    entscheidung = None
                    if gelesen is not None:
                        try:
                            entscheidung = auto_pilot.entscheide_im_stapel(
                                gelesen, ordnerliste, base_url, entscheidungsmodell=entscheidungsmodell,
                                rangliste=ranglisten.get(path), ordner_stand=ordner_stand, **regeln())
                        except Exception as e:
                            if hasattr(self.app, "logger") and self.app.logger:
                                self.app.logger.warning(f"Vollautomatik-Analyse fehlgeschlagen für {path}: {e}")
                    self._nach_entscheidung(iid, path, entscheidung, base_url, model, merkmale, dubletten_cache,
                                            ordnerliste, known_tags)
                    fertig += 1
                    self.after(0, dialog.update_progress, fertig, len(items))
            self.after(0, self._analyse_fertig, dialog)

        threading.Thread(target=worker, daemon=True).start()

    def _nach_entscheidung(self, iid, path, entscheidung, base_url, model, merkmale, dubletten_cache, ordnerliste,
                           known_tags):
        """Phase 3 je Dokument (im Worker-Thread): Dubletten-Prüfung, Listen fortschreiben, anzeigen."""
        if entscheidung and entscheidung.get("zweitmeinung_fehler") and getattr(self.app, "logger", None):
            self.app.logger.warning(f"Zweitmeinung zum Ordner fehlgeschlagen für {path}: "
                                    f"{entscheidung['zweitmeinung_fehler']}")
        if entscheidung:
            # Stufe B: liegt im Zielordner schon dasselbe Dokument? Dann gelb statt gruen.
            # Die KI-Zweitprüfung (Nutzer-Entscheidung 06.09.2026) darf unscharfe
            # Fehlalarme ausräumen - "wir haben ja Zeit und KI".
            try:
                dubletten_pruefung.pruefe_entscheidung(
                    entscheidung, self.app.master_folder, merkmale, dubletten_cache,
                    ki_pruefung=lambda neu, alt: auto_pilot.pruefe_dublette_per_ki(
                        neu, alt, base_url, model))
            except Exception as e:
                if hasattr(self.app, "logger") and self.app.logger:
                    self.app.logger.warning(f"Dubletten-Prüfung fehlgeschlagen für {path}: {e}")
        if entscheidung and entscheidung["ordner_neu"] and entscheidung["sicher"]:
            # Varianten-Zusammenführung (Nutzer-Entscheidung 29.08.2026): ein in diesem
            # Lauf neu vorgeschlagener Ordner zählt ab sofort als "vorhanden" - das
            # nächste Gentilia-Dokument matcht dann per Kernname darauf, statt mit
            # 'Gentilia Deutschland Versicherung AG' einen zweiten Ordner zu erzeugen.
            # Nur bei SICHER: ein unsicher vorgeschlagener Ordner ist nicht bestätigt, das
            # nächste Dokument legte sonst still dort ab (28.10.2026).
            ordnerliste.append(entscheidung["zielordner"])
            self.neue_ordner.add(entscheidung["zielordner"])
        if entscheidung:
            # Neue Tags zählen ab jetzt als bekannt (gleiche Idee wie bei den Ordnern):
            # das nächste Dokument soll 'Stromverbrauch' wiederverwenden, nicht
            # 'Stromkosten' daneben erfinden.
            for tag, _kategorie in entscheidung.get("neue_tags", []):
                if tag.lower() not in {k.lower() for k in known_tags}:
                    known_tags.append(tag)
        self.after(0, self._zeige_entscheidung, iid, entscheidung)

    def _zeige_entscheidung(self, iid, entscheidung):
        self.ergebnisse[iid] = entscheidung
        if not (self.winfo_exists() and self.tree.exists(iid)):
            return
        if entscheidung is None:
            self.tree.item(iid, tags=("fehler",))
            self.tree.set(iid, "status", "FEHLER: KI-Aufruf fehlgeschlagen (siehe Log)")
            return
        ist_neu = entscheidung["ordner_neu"] or entscheidung["zielordner"] in getattr(self, "neue_ordner", ())
        ziel = entscheidung["zielordner"] + (" (neu)" if ist_neu else "")
        if entscheidung.get("ordner_per_alias"):
            ziel += " [Objekt-Alias]" if entscheidung.get("ordner_hinweis") == "Objekt" else " [Alias]"
        elif entscheidung.get("ordner_hinweis"):
            ziel += f" [aus {entscheidung['ordner_hinweis']}]"
        if entscheidung["sicher"]:
            if self._umbenennen():
                status = f"wird automatisch abgelegt als: {entscheidung['neuer_dateiname']}"
            else:
                status = (f"wird automatisch abgelegt, Dateiname bleibt: "
                          f"{os.path.basename(entscheidung['pdf_path'])} (Titel: {entscheidung['neuer_dateiname']})")
            if entscheidung.get("manuell_freigegeben") and entscheidung["probleme"]:
                status += " — manuell freigegeben trotz: " + "; ".join(entscheidung["probleme"])
            if entscheidung.get("dubletten_zweitpruefung"):
                status += " — " + entscheidung["dubletten_zweitpruefung"]
            markierung = "sicher"
        else:
            status = "UNSICHER: " + "; ".join(entscheidung["probleme"])
            markierung = "unsicher"
        if entscheidung.get("titel_korrekturen"):
            # Sichtbar machen, was der Wortschatz-Abgleich am KI-Titel geändert hat -
            # der Nutzer soll eine Fehlkorrektur sofort erkennen können.
            korrekturen = ", ".join(f"{alt}→{neu}" for alt, neu in entscheidung["titel_korrekturen"])
            status = f"[Titel korrigiert: {korrekturen}] " + status
        if entscheidung.get("tag_ersetzungen"):
            # Synonym-Knoten des Katalogs haben zugeschlagen - sichtbar machen, was wodurch ersetzt wurde
            ersetzt = ", ".join(f"{alt}→{neu}" for alt, neu in entscheidung["tag_ersetzungen"])
            status = f"[Synonym: {ersetzt}] " + status
        self.tree.item(iid, tags=(markierung,))
        neu = {t.lower(): k for t, k in entscheidung.get("neue_tags", [])}
        tags_text = ", ".join(
            f"{t} (neu→{neu[t.lower()] or self.app.tag_manager.KATEGORIE_NEU})" if t.lower() in neu else t
            for t in entscheidung["tags"])
        for col, wert in (("titel", entscheidung["titel"]), ("tags", tags_text),
                           ("datum", entscheidung["datum"]), ("ziel", ziel), ("status", status)):
            self.tree.set(iid, col, wert)
        if iid in self.tree.selection():
            self._zeige_ergebnis_volltext()

    def _on_klick(self, event):
        """Klick in die Zielordner-, Titel-, Tags- oder Datum-Zelle einer analysierten Zeile öffnet die Korrektur."""
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        spalte = self.tree.column(self.tree.identify_column(event.x), "id")
        iid = self.tree.identify_row(event.y)
        if not iid or self.einsortiert or not self.ergebnisse.get(iid):
            return
        entscheidung = self.ergebnisse[iid]
        if spalte == "ziel":
            self._ordnerliste_auffrischen()
            schluessel, art = auto_pilot.alias_schluessel(entscheidung)
            dialog = ZielordnerDialog(self, self.ordnerliste, entscheidung["zielordner"], schluessel, art=art)
            self.wait_window(dialog)
            if dialog.ergebnis:
                self._setze_zielordner(iid, dialog.ergebnis, fuer_alle=dialog.fuer_alle)
        elif spalte == "titel":
            titel = UIUtils.ask_string(
                "Titel korrigieren", "Titel für dieses Dokument (wird Teil des Dateinamens):",
                initialvalue=entscheidung["titel"], parent=self)
            if titel is not None and titel.strip():
                self._zeige_entscheidung(iid, auto_pilot.wende_korrektur_an(entscheidung, titel=titel))
        elif spalte == "tags":
            # Nutzerwunsch 01./03.09.2026: Tags direkt in der Vorschau korrigierbar -
            # "hab da gerade ein Tag gefunden, das nicht passt". Komma trennt (FALLSTRICKE #38).
            text = UIUtils.ask_string(
                "Tags korrigieren", "Tags für dieses Dokument, durch Komma getrennt:",
                initialvalue=", ".join(entscheidung["tags"]), parent=self)
            if text is not None:
                tm = getattr(self.app, "tag_manager", None)
                self._zeige_entscheidung(iid, auto_pilot.wende_korrektur_an(
                    entscheidung, tags=text,
                    known_tags=tm.get_known_tags() if tm else None,
                    kategorien=tm.get_kategorien() if tm else None))
        elif spalte == "datum":
            self._frage_datum(iid, entscheidung)
        elif spalte == "status":
            self._frage_freigabe(iid, entscheidung)

    def _frage_freigabe(self, iid, entscheidung):
        """
        Manuelle Freigabe (Nutzerwunsch 06.09.2026: "ich kann Dokumente nicht manuell als
        sicher markieren"): Klick auf die Ergebnis-Zelle einer gelben Zeile bietet an,
        trotz der verbliebenen Gründe (z.B. Dubletten-Verdacht, den der Nutzer selbst
        geprüft hat) automatisch abzulegen. Gründe MIT eigener Korrektur-Zelle werden
        nicht überstimmt, sondern auf ihre Zelle verwiesen - ohne Titel/Datum/Zielordner
        gäbe es keinen Dateinamen. Erneuter Klick nimmt die Freigabe zurück.
        """
        if entscheidung.get("manuell_freigegeben"):
            self._zeige_entscheidung(iid, auto_pilot.wende_freigabe_an(entscheidung, freigeben=False))
            return
        if auto_pilot.PROBLEM_ZURUECKGESTELLT in entscheidung["probleme"]:
            self._zeige_entscheidung(iid, auto_pilot.wende_zurueckstellung_an(entscheidung, zurueckstellen=False))
            return
        if entscheidung["sicher"]:
            # Gegenrichtung (Peter 02.11.2026): fälschlich grün -> von Hand gelb
            if bestaetigung.frage(
                    "Nicht automatisch ablegen?",
                    "Dieses Dokument würde automatisch abgelegt.\n\nStattdessen beim Einsortieren in den "
                    "Unsicher-Ordner legen (Grund: „" + auto_pilot.PROBLEM_ZURUECKGESTELLT + "“)?\n\n"
                    "Ein erneuter Klick auf die Ergebnis-Zelle nimmt das zurück.",
                    parent=self):
                self._zeige_entscheidung(iid, auto_pilot.wende_zurueckstellung_an(entscheidung))
            return
        korrigierbar = auto_pilot.korrigierbare_probleme(entscheidung)
        if korrigierbar:
            mb.showinfo(
                "Erst korrigieren",
                "Diese Punkte lassen sich direkt beheben - bitte auf die jeweilige Zelle "
                "(Titel, Tags, Datum bzw. Zielordner) klicken:\n\n- " + "\n- ".join(korrigierbar),
                parent=self)
            return
        if bestaetigung.frage(
                "Trotzdem automatisch ablegen?",
                "Dieses Dokument gilt als unsicher:\n\n- " + "\n- ".join(entscheidung["probleme"])
                + "\n\nTrotzdem beim Einsortieren automatisch ablegen (Metadaten schreiben, "
                "umbenennen, in den Zielordner verschieben)?\n\n"
                "Ein erneuter Klick auf die Ergebnis-Zelle nimmt die Freigabe zurück.",
                parent=self):
            self._zeige_entscheidung(iid, auto_pilot.wende_freigabe_an(entscheidung))

    def _sync_hauptfenster(self, event=None):
        """
        Zeigt das Dokument der ausgewählten Zeile im Hauptfenster an (Nutzerwunsch 01.09.2026:
        Kontrolle während der Prüfung). Wechselt dafür nötigenfalls links in dessen Ordner -
        die Vorschau zeigt meist Posteingang-Dateien, während das Hauptfenster woanders steht.
        Bewusst nur selection_set/see: on_file_select feuert Tkinter selbst (FALLSTRICKE #8).
        """
        auswahl = self.tree.selection()
        if len(auswahl) != 1:
            return
        folder_manager = getattr(self.app, "folder_manager", None)
        if folder_manager is not None:
            folder_manager.zeige_dokument(self.rows.get(auswahl[0]))

    def _frage_datum(self, iid, entscheidung):
        """Datum-Eingabe (JJJJ-MM-TT oder TT.MM.JJJJ), vorbelegt mit KI-Datum oder Dateinamen-Präfix; fragt bei Tippfehlern erneut."""
        vorgabe = entscheidung["datum"] or auto_pilot.datum_aus_dateiname(entscheidung["pdf_path"])
        while True:
            datum = UIUtils.ask_string(
                "Dokumentdatum korrigieren",
                "Dokumentdatum (das Datum auf dem Brief, nicht das Scan-Datum),\nz.B. 20.07.2026 oder 2026-07-20:",
                initialvalue=vorgabe, parent=self)
            if datum is None:
                return
            neu = auto_pilot.wende_korrektur_an(entscheidung, datum=datum)
            if auto_pilot._datum_ist_plausibel(neu["datum"]):
                self._zeige_entscheidung(iid, neu)
                return
            mb.showwarning("Ungültiges Datum",
                           f"'{datum}' ist kein plausibles Datum (echtes Kalenderdatum, nicht in der Zukunft). "
                           "Bitte als TT.MM.JJJJ oder JJJJ-MM-TT eingeben, z.B. 27.09.2020.",
                           parent=self)
            vorgabe = datum

    def _setze_zielordner(self, iid, zielordner, fuer_alle=False):
        """
        Nutzer hat für eine Zeile den Zielordner bestimmt. Standard ist NUR diese eine
        Zeile (Nutzerfund 31.08.2026: das automatische Alias-Lernen bei jedem Klick hat
        ganze Absender dauerhaft in den falschen Ordner gelenkt). Nur wenn er es im
        Dialog ausdrücklich gewählt hat (fuer_alle), wird der Absender-Alias gespeichert
        und die Wahl auf alle Zeilen mit passendem Absender angewandt - bei Dokumenten
        ohne Absender entsprechend ein Objekt-Alias (auto_pilot.alias_schluessel).
        """
        entscheidung = self.ergebnisse[iid]
        absender, _art = auto_pilot.alias_schluessel(entscheidung)
        if fuer_alle and absender:
            try:
                self.aliase = ordner_aliase.speichere_alias(self.app.master_folder, absender, zielordner)
            except OSError as e:
                mb.showwarning(
                    "Alias nicht gespeichert",
                    f"Der Zielordner gilt für diesen Lauf, konnte aber nicht dauerhaft gemerkt werden:\n{e}",
                    parent=self)
                self.aliase[absender] = zielordner
        if zielordner not in self.ordnerliste:
            self.ordnerliste.append(zielordner)
            self.neue_ordner.add(zielordner)
        for andere_iid, andere in list(self.ergebnisse.items()):
            if andere is None:
                continue
            passt = andere_iid == iid or (
                fuer_alle and absender and auto_pilot.alias_trifft(andere, absender, zielordner))
            if passt:
                self._zeige_entscheidung(
                    andere_iid, auto_pilot.wende_zielordner_an(andere, zielordner, self.ordnerliste))

    def _ordnerliste_auffrischen(self):
        """Ordner, die seit der Analyse angelegt wurden (z.B. im Hauptfenster), in die Zielordner-Auswahl aufnehmen
        (Peter 02.11.2026: ein eben angelegter Ordner fehlte dort). Nur ergänzen, nie ersetzen - dieselbe Liste
        benutzt ein noch laufender Analyse-Thread."""
        try:
            vorhanden = auto_pilot.sammle_ordnerliste(self.app.master_folder)
        except OSError:
            return
        for ordner in vorhanden:
            if ordner not in self.ordnerliste:
                self.ordnerliste.append(ordner)
            self.neue_ordner.discard(ordner)          # inzwischen angelegt: nicht mehr „(neu)“

    def _umbenennen(self):
        """Einstellung 'Dateien beim Ablegen umbenennen' (Standard an, siehe auto_pilot.fuehre_entscheidung_aus)."""
        return bool(self.app.config.get("auto_pilot_umbenennen", True))

    def _oeffne_alias_verwaltung(self):
        """Gemerkte Absender-Zuordnungen ansehen/löschen; danach die Tabelle neu laden."""
        dialog = AliasVerwaltungDialog(self, self.app)
        self.wait_window(dialog)
        # Für den restlichen Lauf mit dem bereinigten Stand weiterarbeiten
        self.aliase = ordner_aliase.lade_aliase(self.app.master_folder)

    def _analyse_fertig(self, dialog):
        if dialog.winfo_exists():
            dialog.destroy()
        if self.winfo_exists():
            self.btn_analyse.config(state=tk.NORMAL)
            if any(self.ergebnisse.values()):
                self.btn_einsortieren.config(state=tk.NORMAL)

    def _starte_einsortierung(self):
        offene = [(iid, e) for iid, e in self.ergebnisse.items() if e is not None]
        sichere = sum(1 for _, e in offene if e["sicher"])
        unsichere = len(offene) - sichere
        if not offene:
            mb.showinfo("Hinweis", "Bitte zuerst die Analyse starten.", parent=self)
            return
        if not bestaetigung.frage(
                "Jetzt einsortieren",
                f"{sichere} Dokument(e) werden automatisch abgelegt (Metadaten schreiben, "
                f"umbenennen, verschieben).\n{unsichere} Dokument(e) werden unverändert nach "
                f"'{auto_pilot.UNSICHER_ORDNER}' verschoben.\n\nFortfahren?", parent=self):
            return

        self.btn_analyse.config(state=tk.DISABLED)
        self.btn_einsortieren.config(state=tk.DISABLED)
        self.einsortiert = True

        # Aktuell selektierten Ordner merken: refresh_folder_tree() baut den Baum
        # komplett neu auf und verwirft dabei die bisherige Selektion - ein
        # anschließendes on_folder_select(None) wäre dann ein No-Op (bricht sofort
        # ab, da tree_folders.selection() leer ist) und das Dokumenten-Grid links
        # zeigt weiter die inzwischen verschobenen/umbenannten Dateien (gleiches
        # Muster wie file_operations.delete_file/restore_file).
        current_folder_sel = self.app.tree_folders.selection()
        current_folder_path = (
            self.app.tree_folders.item(current_folder_sel[0], "values")[0] if current_folder_sel else None)

        abgelegt = unsicher_verschoben = fehlgeschlagen = 0
        # Läuft bewusst synchron auf dem Hauptthread (Messagebox-Risiko aus Threads, siehe
        # KONZEPT_SENIORENMODUS.md) - damit die App bei einem großen Stapel (Live-Test:
        # 411 Dokumente) nicht "eingefroren" wirkt, zeichnet ein ProgressDialog den
        # Fortschritt und wird per update() zwischen den Dokumenten am Leben gehalten.
        dialog = ProgressDialog(self, "Einsortieren", "Dokumente werden abgelegt...")
        self.app.is_moving = True
        try:
            for i, (iid, entscheidung) in enumerate(offene):
                if dialog.should_stop():
                    break
                ergebnis = auto_pilot.fuehre_entscheidung_aus(
                    entscheidung, self.app.master_folder, self.app.file_ops._verschiebe_ohne_duplikat,
                    umbenennen=self._umbenennen())
                self._zeige_ausfuehrung(iid, entscheidung, ergebnis)
                # Auch die Vorschau-Ablage protokolliert jede Aktion (Kaltstart-Test
                # 03.09.2026: das Fenster war zu, die Unsicher-Gründe unwiederbringlich weg).
                log = getattr(self.app, "logger", None)
                auto_pilot.protokolliere_ergebnis(entscheidung, ergebnis, self.app.master_folder, log)
                if log:
                    log.info(f"Ablage-Vorschau: {os.path.basename(entscheidung['pdf_path'])} -> "
                             f"{ergebnis['neuer_pfad'] or ergebnis['fehler']}")
                if not ergebnis["erfolg"]:
                    fehlgeschlagen += 1
                elif entscheidung["sicher"]:
                    abgelegt += 1
                else:
                    unsicher_verschoben += 1
                if dialog.winfo_exists():
                    dialog.update_progress(i + 1, len(offene))
                self.update()
        finally:
            self.app.is_moving = False
            if dialog.winfo_exists():
                dialog.destroy()
            self.app.folder_manager.refresh_folder_tree()
            if current_folder_path:
                self.app.folder_manager._select_and_open_path(current_folder_path)
            else:
                self.app.folder_manager.on_folder_select(None)

        # Erst NACH dem UI-Refresh melden, damit die Dokumentenliste hinter dem Dialog
        # bereits den neuen Stand zeigt (nicht mehr die gerade verschobenen Dateien).
        self._zeige_zusammenfassung(abgelegt, unsicher_verschoben, fehlgeschlagen)

    def _zeige_zusammenfassung(self, abgelegt, unsicher_verschoben, fehlgeschlagen):
        """Abschlussmeldung nach dem Einsortieren - beim Posteingang-Stapel oft die einzige Rückmeldung, die der Nutzer wirklich liest."""
        zeilen = [f"{abgelegt} Dokument(e) automatisch abgelegt."]
        if unsicher_verschoben:
            zeilen.append(f"{unsicher_verschoben} Dokument(e) nach '{auto_pilot.UNSICHER_ORDNER}' verschoben — "
                          "dort bitte gelegentlich nachschauen.")
        if fehlgeschlagen:
            zeilen.append(f"{fehlgeschlagen} Dokument(e) konnten NICHT verarbeitet werden — "
                          "Details stehen in der Spalte 'Ergebnis' und im Log.")
        mb.showinfo("Einsortieren abgeschlossen", "\n".join(zeilen), parent=self)

    def _zeige_ausfuehrung(self, iid, entscheidung, ergebnis):
        pdf_path = entscheidung["pdf_path"]
        if ergebnis["erfolg"]:
            if entscheidung["sicher"]:
                meldung = f"abgelegt: {ergebnis['neuer_pfad']}"
            else:
                meldung = f"nach {auto_pilot.UNSICHER_ORDNER} verschoben"
            markierung = "sicher"
            if hasattr(self.app, "logger") and self.app.logger:
                self.app.logger.info(f"Vollautomatik: {pdf_path} -> {ergebnis['neuer_pfad']}")
            if hasattr(self.app, "tool_manager"):
                self.app.tool_manager.notify_file_moved(pdf_path, ergebnis["neuer_pfad"])
            if entscheidung["sicher"] and hasattr(self.app, "tag_manager") and entscheidung.get("neue_tags"):
                # Von Hand eingetragene, neue Tags kommen gleich in den Katalog (Etappe 6: keine Warteliste mehr)
                self.app.tag_manager.add_tags_to_catalog(entscheidung["neue_tags"])
        else:
            meldung = f"FEHLER: {ergebnis['fehler']}"
            markierung = "fehler"
            if hasattr(self.app, "logger") and self.app.logger:
                self.app.logger.warning(f"Vollautomatik-Ausführung fehlgeschlagen für {pdf_path}: {ergebnis['fehler']}")
        if self.winfo_exists() and self.tree.exists(iid):
            self.tree.item(iid, tags=(markierung,))
            self.tree.set(iid, "status", meldung)
            if iid in self.tree.selection():
                self._zeige_ergebnis_volltext()


class AutoFilerInboxTool(BaseTool):
    """
    Schritt 3 des Seniorenmodus: EIN Knopf verarbeitet den kompletten Posteingang.
    Bewusst ohne Dateiauswahl (required_input "none") - der spätere Senioren-Einstieg
    (Schritt 5) soll genau diesen Weg benutzen können, ohne dass jemand vorher
    Dokumente in einer Liste markiert.
    """

    def __init__(self):
        self.window = None

    @property
    def name(self) -> str:
        return "Vollautomatik: Posteingang verarbeiten"

    @property
    def menu_group(self) -> str:
        return "Vollautomatik"

    @property
    def menu_label(self) -> str:
        return "Posteingang verarbeiten (Stapel mit Vorschau)…"

    @property
    def absicht(self) -> str:
        return ("Der Stapel vom Scanner auf einen Schlag: jedes Dokument im Posteingang wird analysiert und mit Vorschau abgelegt - statt jedes einzeln zu markieren.")

    @property
    def description(self) -> str:
        return "Analysiert alle Dokumente im Posteingang und schlägt ihre Ablage vor (ein Knopf für den ganzen Stapel)."

    @property
    def braucht_ki(self) -> bool:
        return True   # ohne KI-Server sinnlos - Menüeintrag wird dann gesperrt (ki_status)

    @property
    def menu_hooks(self) -> list:
        # Bewusst NICHT im Kontextmenü der Dateiliste: das Tool arbeitet gerade nicht
        # mit der Auswahl, das wäre dort eine irreführende Nachbarschaft.
        return ["main_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        master_folder = getattr(context.app, "master_folder", "")
        if not master_folder:
            mb.showinfo("Hinweis", "Es ist keine Dokumenten-Sammlung geöffnet.")
            return False

        if auto_pilot.finde_posteingang(master_folder) is None:
            mb.showinfo(
                "Kein Posteingang gefunden",
                "In dieser Sammlung gibt es keinen Posteingang-Ordner.\n\n"
                f"Lege im Hauptordner einen Ordner '{auto_pilot.POSTEINGANG_ORDNER}' an — "
                "dort hinein kommen künftig alle frisch eingescannten Dokumente.")
            return False

        pdf_paths = auto_pilot.sammle_posteingang_dokumente(master_folder)
        if not pdf_paths:
            mb.showinfo("Posteingang ist leer",
                        "Im Posteingang liegen keine Dokumente — es gibt nichts zu tun.")
            return False

        if self.window and self.window.winfo_exists():
            self.window.destroy()
        self.window = AutoFilerPreviewWindow(
            context.app, pdf_paths,
            fenstertitel=f"Vollautomatik — Posteingang ({len(pdf_paths)} Dokumente)",
            auto_start=True)
        return True


class AutoPilotToggleTool(BaseTool):
    """
    Schritt 4: Ein/Aus-Schalter für die Watchdog-Vollautomatik (auto_pilot_service.py) im
    Tools-Menü - dieselbe Einstellung wie die Checkbox in den Einstellungen, nur einen Klick
    näher; Vorstufe zum großen Knopf des Senioren-Einstiegs (Schritt 5).
    """

    @property
    def name(self) -> str:
        return "Vollautomatik: automatisch ein/aus"

    @property
    def menu_group(self) -> str:
        return "Vollautomatik"

    @property
    def menu_label(self) -> str:
        return "Hintergrund-Automatik ein/aus"

    @property
    def absicht(self) -> str:
        return ("Seniorenmodus: neue Dokumente im Posteingang werden ohne Zutun abgelegt, das Statusfenster zeigt, was gerade passiert. Unsichere Fälle landen in 0_Unsicher, nie im falschen Ordner. Fenster zu = Automatik aus.")

    @property
    def description(self) -> str:
        return "Schaltet die automatische Ablage neuer Posteingang-Dokumente im Hintergrund ein oder aus."

    @property
    def menu_hooks(self) -> list:
        return ["main_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        app = context.app
        neu = not bool(app.config.get("auto_pilot_enabled", False))
        app.config.set("auto_pilot_enabled", neu)
        dienst = getattr(app, "auto_pilot_service", None)
        if dienst is not None:
            # Öffnet/schließt auch das Statusfenster - das Fenster selbst IST die
            # Ein/Aus-Rückmeldung (31.08.2026), darum keine Messagebox mehr.
            dienst.anstossen()
        return True


class ProtokollAnzeigenTool(BaseTool):
    """
    Öffnet das Angehörigen-Protokoll der Vollautomatik im Standard-Editor (Nutzerfrage
    03.09.2026: "Wo kann ich das Protokoll ansehen?" - die Datei lag zwar im Daten-
    Ordner, war aber aus der App heraus nicht erreichbar; für den Seniorenmodus muss
    das ohne Datei-Explorer-Wissen gehen).
    """

    @property
    def name(self) -> str:
        return "Vollautomatik: Protokoll anzeigen"

    @property
    def menu_group(self) -> str:
        return "Vollautomatik"

    @property
    def menu_label(self) -> str:
        return "Protokoll anzeigen"

    @property
    def absicht(self) -> str:
        return ("Angehörige können nachvollziehen, was die Automatik abgelegt hat: eine Zeile pro Dokument mit Zielordner und Grund - auch wenn niemand beim Ablegen zugesehen hat.")

    @property
    def description(self) -> str:
        return "Öffnet das Protokoll der automatischen Ablage (eine Zeile pro Dokument) im Editor."

    @property
    def menu_hooks(self) -> list:
        return ["main_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        app = context.app
        pfad = app_paths.protokoll_path(app.master_folder)
        if not os.path.exists(pfad):
            mb.showinfo("Vollautomatik-Protokoll",
                        "Es gibt noch kein Protokoll - die Vollautomatik hat in dieser "
                        "Sammlung noch nichts abgelegt.", parent=app.root)
            return True
        try:
            os.startfile(pfad)  # Windows; die App läuft nur dort (PyInstaller-EXE)
        except OSError as e:
            mb.showerror("Vollautomatik-Protokoll",
                         f"Das Protokoll konnte nicht geöffnet werden:\n{pfad}\n\n{e}",
                         parent=app.root)
        return True
