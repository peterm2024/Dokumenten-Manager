import tkinter as tk
import aktivitaet
import tkinter.font as tkfont
from tkinter import ttk
import versionspruefung
from ui_utils import UIUtils, Tooltip

# Pos1/Ende in Liste und Vorschau: so weit blättern, dass jedes Dokument an seinem Anfang/Ende landet
SEITEN_BIS_ENDE = 100000
from tag_autocomplete import TagAutocomplete
from suchfeld import SuchFeld
from ki_status import KiLed
from help_window import open_help
from dokument_eigenschaften import EigenschaftenPanel

# Sichtbare Spalten der Dokumentenliste beim ersten Start und nach „Fensteraufteilung zurücksetzen“
# (eine Quelle für beide; „tags“ gehört seit 25.10.2026 dazu - Peter, Release-Check T0.10)
STANDARD_SPALTEN = ("datum", "titel", "tags", "ordner")

# Spaltenbreiten der Dokumentenliste in 100-%-Pixeln - auf dem Bildschirm immer über UIUtils.px()
# hochgerechnet, gespeichert (settings.json "column_widths") wieder durch die Skalierung geteilt.
# Vorher galten sie als echte Pixel: bei 125 % Skalierung + 125 % Textgröße war das Datum
# abgeschnitten („27.04.202“, Release-Check T0.16, 25.10.2026, FALLSTRICKE #77).
STANDARD_BREITEN = {"datum": 85, "titel": 250, "tags": 180, "name": 180, "path": 150, "ordner": 140,
                    "scan_zeit": 85, "qualitaet": 90, "erfasst": 110}
MINDEST_BREITEN = {"datum": 85, "titel": 150, "tags": 180, "name": 100, "path": 80, "ordner": 80,
                   "scan_zeit": 85, "qualitaet": 60, "erfasst": 110}
GESPEICHERTE_SPALTEN = ("datum", "titel", "tags", "name", "path", "ordner")


def breiten_fuer_bildschirm(breiten, skalierung):
    """100-%-Breiten (Standard oder gespeichert) -> Bildschirm-Pixel."""
    return {spalte: int(round(wert * skalierung)) for spalte, wert in breiten.items()}


def breiten_zum_speichern(breiten, skalierung):
    """Bildschirm-Pixel -> 100-%-Breiten für settings.json (Gegenstück zu breiten_fuer_bildschirm)."""
    return {spalte: int(round(wert / skalierung)) for spalte, wert in breiten.items()}


class LayoutBuilder:
    def __init__(self, root, app):
        """
        Kapselt den gesamten visuellen Aufbau der Tkinter-GUI.
        :param root: Das Haupt-Tkinter-Fenster.
        :param app: Die Instanz der Hauptanwendung (DokumentenVerwaltung).
        """
        self.root = root
        self.app = app

    def build(self):
        """Führt den kompletten Layout-Aufbau durch."""
        self._setup_menu()
        self._setup_ui()

    def _setup_column_menu(self, headings):
        """
        Baut das Rechtsklick-Menü der Dokumentenlisten-Kopfzeile zum Ein-/Ausblenden
        von Spalten. Die Auswahl wird als 'visible_columns' in der settings.json
        persistiert; die Datenspalten (values) bleiben immer vollständig, nur die
        Anzeige (displaycolumns) wird gefiltert.
        :param headings: Dict Spalten-ID -> Anzeigename für die Menü-Beschriftung.
        """
        self.app.column_vars = {}
        menu = tk.Menu(self.app.root, tearoff=0)
        visible = list(self.app.tree_files["displaycolumns"])

        def apply_columns():
            chosen = [c for c in self.app.tree_files["columns"] if self.app.column_vars[c].get()]
            if not chosen:  # Mindestens eine Spalte muss sichtbar bleiben
                chosen = ["titel"]
                self.app.column_vars["titel"].set(True)
            vorher = list(self.app.tree_files["displaycolumns"])
            self.app.tree_files["displaycolumns"] = chosen
            self.app.config.set("visible_columns", chosen)
            # Textqualität wird nur bei sichtbarer Spalte gelesen (folder_manager) -
            # beim Einblenden die Liste einmal neu füllen, sonst bleibt sie leer
            if "qualitaet" in chosen and "qualitaet" not in vorher and hasattr(self.app, "folder_manager"):
                self.app.folder_manager.on_folder_select(None)

        for col in self.app.tree_files["columns"]:
            var = tk.BooleanVar(value=(col in visible))
            self.app.column_vars[col] = var
            menu.add_checkbutton(label=headings[col], variable=var, command=apply_columns)

        def show_column_menu(event):
            if self.app.tree_files.identify_region(event.x, event.y) == "heading":
                menu.tk_popup(event.x_root, event.y_root)

        # add="+": das bestehende Button-3-Binding (Datei-Kontextmenü) bleibt aktiv;
        # es reagiert nur auf Zeilen, dieses hier nur auf die Kopfzeile.
        self.app.tree_files.bind("<Button-3>", show_column_menu, add="+")

    def _setup_menu(self):
        """Konfiguriert die obere Menüleiste (Datei, Ansicht, Einstellungen)."""
        self.app.menu_bar = tk.Menu(self.root)
        
        # Datei-Menü
        self.app.file_menu = tk.Menu(self.app.menu_bar, tearoff=0)
        # Bezeichnungen seit 07.09.2026 in Klartext (Nutzerwunsch: "ich tue mir mit den
        # Bedeutungen schwer") - der Hauptordner heißt in der Oberfläche "Sammlung".
        self.app.file_menu.add_command(label="Sammlung öffnen (Hauptordner wählen)...", command=self.app.folder_manager.choose_master_folder)
        self.app.file_menu.add_command(label="Standard-Ordnerstruktur in der Sammlung anlegen...", command=self.app.folder_manager.create_default_folders)
        self.app.file_menu.add_separator()
        self.app.file_menu.add_command(label="Einstellungen...", command=self.app.oeffne_einstellungen)
        self.app.file_menu.add_separator()
        self.app.file_menu.add_command(label="Protokoll-Datei (Log) öffnen", command=self.app.open_log_file)
        self.app.file_menu.add_separator()
        self.app.file_menu.add_command(label="Beenden", command=self.app.on_closing)
        self.app.menu_bar.add_cascade(label="Datei", menu=self.app.file_menu)

        # Ansicht-Menü
        self.app.view_menu = tk.Menu(self.app.menu_bar, tearoff=0)
        self.app.view_menu.add_command(label="Vorschau einpassen (Auto-Zoom, auch Doppelklick auf die Seite)", command=self.app.preview_manager.reset_zoom)
        self.app.view_menu.add_separator()
        self.app.view_menu.add_checkbutton(label="Papierkorb im Ordnerbaum anzeigen", variable=self.app.show_trash_var, command=self.app.folder_manager.toggle_show_trash)
        self.app.view_menu.add_checkbutton(label="Mails ausblenden", variable=self.app.mails_ausblenden_var,
                                           command=self.app.folder_manager.toggle_mails)
        self.app.view_menu.add_checkbutton(label="Kurzbefehle anzeigen (F1)", variable=self.app.kurzbefehle.var,
                                           command=self.app.kurzbefehle.anwenden)
        self.app.view_menu.add_separator()
        self.app.view_menu.add_command(label="Fensteraufteilung zurücksetzen (Standard-Layout)", command=self.app.reset_layout)
        self.app.menu_bar.add_cascade(label="Ansicht", menu=self.app.view_menu)

        # Das frühere "Einstellungen"-Menü wurde entfernt: Hauptordner und Standard-
        # Ordnerstruktur liegen im Datei-Menü, alle übrigen Einstellungen im Settings-
        # Editor-Tool, das seit 07.09.2026 ebenfalls über Datei -> Einstellungen... öffnet.

        # Hilfe-Menü (das Tools-Menü fügt sich zur Laufzeit DAVOR ein, siehe ToolManager)
        self.app.help_menu = tk.Menu(self.app.menu_bar, tearoff=0)
        self.app.help_menu.add_command(label="Schnellstart", command=lambda: open_help(self.app, 0))
        self.app.help_menu.add_command(label="Funktionsumfang", command=lambda: open_help(self.app, 1))
        self.app.help_menu.add_command(label="Tags: Sinn und Grenzen", command=lambda: open_help(self.app, 2))
        self.app.help_menu.add_command(label="Menü-Übersicht (jeder Eintrag erklärt)", command=lambda: open_help(self.app, 3))
        self.app.help_menu.add_separator()
        # Fernzugriff auf den KI-Server: Erklärung samt klickbarem Tailscale-Link steht
        # im Funktionsumfang (help_window, Abschnitt "KI-Server aus der Ferne").
        self.app.help_menu.add_command(label="KI auf dem eigenen PC (Ollama lokal)",
                                       command=lambda: open_help(self.app, 1, abschnitt="KI auf dem eigenen PC"))
        self.app.help_menu.add_command(label="KI-Server aus der Ferne (Tailscale)",
                                       command=lambda: open_help(self.app, 1, abschnitt="KI-Server aus der Ferne"))
        self.app.help_menu.add_separator()
        self.app.help_menu.add_command(label="Auf neue Version prüfen...",
                                       command=lambda: versionspruefung.pruefe(self.app))
        self.app.help_menu.add_command(label="Über...", command=lambda: open_help(self.app, 4))
        self.app.menu_bar.add_cascade(label="Hilfe", menu=self.app.help_menu)

        # Aktivitätsanzeige: ausgegrauter Eintrag ganz rechts, zeigt die laufende Phase
        # in Klartext („Lese Ordner … 12/80", „Wartet auf deine Antwort: …"), siehe aktivitaet.py.
        # Der ToolManager fügt „Tools" VOR „Hilfe" ein und lässt diesen Eintrag am Ende.
        self.app.menu_bar.add_command(label=aktivitaet.RUHE_TEXT, state="disabled")
        self.app.aktivitaet = aktivitaet.Anzeige(self.root, self.app.menu_bar, self.app.menu_bar.index("end"))
        aktivitaet.registriere(self.app.aktivitaet)

        self.root.config(menu=self.app.menu_bar)

    def _setup_ui(self):
        """Baut das gesamte Tkinter-Layout mit PanedWindows, Treeviews, Canvas und der Filterleiste auf."""
        self.app.main_pane = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        # Doppelklick auf den rechten Greifer passt die Seite ein (preview_manager)
        self.app.main_pane.bind("<Double-Button-1>", lambda e: self.app.preview_manager.on_sash_doppelklick(e))
        self.app.main_pane.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.app.col1_pane = ttk.PanedWindow(self.app.main_pane, orient=tk.VERTICAL)
        self.app.main_pane.add(self.app.col1_pane, weight=0)

        self.app.col2_pane = ttk.PanedWindow(self.app.main_pane, orient=tk.VERTICAL)
        self.app.main_pane.add(self.app.col2_pane, weight=0) 

        # --- Visuelle Akzente für Buttons (Theme: clam) ---
        style = ttk.Style()
        # Schriftgröße aus TkDefaultFont statt fest 9 pt: wächst mit der Windows-Textgröße mit (FALLSTRICKE #69)
        style.configure("Danger.TButton", foreground="#d9534f", font=("", UIUtils.schriftgroesse(), "bold"))
        style.map("Danger.TButton", foreground=[('active', '#c9302c')])
        style.configure("Accent.TButton", background="#0078D7", foreground="white", font=("", UIUtils.schriftgroesse(), "bold"))
        style.map("Accent.TButton", background=[('active', '#005a9e')])

        # Bewusst OHNE LabelFrame-Überschrift (31.08.2026): Dateiname/Seite/Zoom stehen in
        # der Fenster-Titelleiste (preview_manager.setze_vorschau_info) - bei 125-%-Schrift
        # kostete die Kopfzeile spürbar Vorschau-Höhe.
        self.app.col3_frame = ttk.Frame(self.app.main_pane)
        self.app.main_pane.add(self.app.col3_frame, weight=1)

        # Ordnerbaum
        # Die fünf Bereichs-Rahmen tragen seit 13.09.2026 keine Titel mehr (Nutzerwunsch:
        # Platz sparen - Ordnerbaum, Tag-Baum, Suchleiste, Liste und Eigenschaften erklären
        # sich durch ihren Inhalt); der Rahmen selbst bleibt als optische Trennung.
        frame_folders = ttk.Frame(self.app.col1_pane, relief="groove", borderwidth=1)
        self.app.col1_pane.add(frame_folders, weight=1)

        # Senkrechte Bildlaufleiste wie beim Tag-Baum und der Dokumentenliste (Nutzerfund
        # 01.09.2026: der Ordnerbaum war der einzige ohne - aufgeklappte Buchstabengruppen
        # ragten unten aus dem Feld und man kam nur per Mausrad weiter).
        scroll_folders_y = ttk.Scrollbar(frame_folders, orient="vertical")
        self.app.tree_folders = ttk.Treeview(frame_folders, selectmode="extended", columns=("path", "count"),
                                             displaycolumns=("count",), yscrollcommand=scroll_folders_y.set)
        scroll_folders_y.config(command=self.app.tree_folders.yview)
        self.app.tree_folders.heading("#0", text="Ordner", anchor="w")
        self.app.tree_folders.heading("count", text="📄")
        self.app.tree_folders.column("#0", width=UIUtils.px(self.app.root, 150), stretch=True)
        self.app.tree_folders.column("count", width=UIUtils.px(self.app.root, 35), stretch=False, anchor="center")
        scroll_folders_y.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 5), pady=5)
        self.app.tree_folders.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0), pady=5)
        
        self.app.tree_folders.tag_configure("drop_target", background="#0078D7", foreground="white")
        self.app.tree_folders.tag_configure("trash_folder", foreground="#a0a0a0", font=("", 10, "italic"))
        
        self.app.tree_folders.bind("<<TreeviewSelect>>", self.app.folder_manager.on_folder_select)

        # --- NEU: Fängt den Klick auf das Aufklapp-Dreieck ab ---
        self.app.tree_folders.bind("<Button-1>", self.app.folder_manager.on_tree_click)

        # --- NEU: Kontextmenü für den Ordnerbaum ---
        self.app.folder_context_menu = tk.Menu(self.root, tearoff=0)
        self.app.folder_context_menu.add_command(label="Neuer Unterordner...", command=self.app.folder_manager.create_new_folder)
        self.app.folder_context_menu.add_command(label="Umbenennen (F2)", command=self.app.folder_manager.rename_folder)
        self.app.folder_context_menu.add_command(label="Zusammenführen mit…", command=self.app.folder_manager.merge_folder)
        self.app.folder_context_menu.add_separator()
        self.app.folder_context_menu.add_command(label="Im Explorer / Finder öffnen", command=self.app.folder_manager.open_folder_in_explorer)
        self.app.folder_context_menu.add_separator()
        self.app.folder_context_menu.add_command(label="Alle Unterordner aufklappen", command=self.app.folder_manager.expand_all_folders)
        self.app.folder_context_menu.add_command(label="Alle Unterordner zuklappen", command=self.app.folder_manager.collapse_all_folders)
        self.app.folder_context_menu.add_command(label="Aktualisieren", command=self.app.folder_manager.refresh_folder_tree)

        # Rechtsklick öffnet das Menü, F2 triggert die Umbenennen-Funktion direkt
        self.app.tree_folders.bind("<Button-3>", self.app.folder_manager.show_folder_context_menu)
        self.app.tree_folders.bind("<F2>", lambda e: self.app.folder_manager.rename_folder())

        # Tag-Editor
        frame_tags = ttk.Frame(self.app.col1_pane, relief="groove", borderwidth=1)
        self.app.col1_pane.add(frame_tags, weight=1)
        
        mode_frame = tk.Frame(frame_tags)
        mode_frame.pack(fill=tk.X, padx=5, pady=(5,0))
        
        self.app.tag_mode_var = tk.StringVar(value="assign")
        rb_assign = ttk.Radiobutton(mode_frame, text="🏷️ Zuweisen", variable=self.app.tag_mode_var, value="assign", command=self.app.tag_manager.on_tag_mode_change)
        rb_filter = ttk.Radiobutton(mode_frame, text="🔍 Filtern", variable=self.app.tag_mode_var, value="filter", command=self.app.tag_manager.on_tag_mode_change)
        rb_assign.pack(side=tk.LEFT, expand=True)
        rb_filter.pack(side=tk.LEFT, expand=True)
        
        # Echtes Suchfeld über dem Tag-Baum statt eines gebastelten Headers: ein ttk.Entry
        # bekommt den blauen Fokus-Rahmen automatisch vom Theme (genau wie entry_search bei
        # der Volltextsuche) - kein eigenes Fokus-Styling nötig. Tippen synchronisiert live
        # mit dem Baum darunter (siehe TagManager.on_tag_search_changed).
        self.app.entry_tag_search = ttk.Entry(frame_tags)
        self.app.entry_tag_search.insert(0, self.app.tag_manager.TAG_SEARCH_PLACEHOLDER)
        self.app.entry_tag_search.pack(side=tk.TOP, fill=tk.X, padx=5, pady=(5, 0))
        self.app.entry_tag_search.bind("<FocusIn>", lambda e: UIUtils.clear_placeholder(self.app.entry_tag_search, self.app.tag_manager.TAG_SEARCH_PLACEHOLDER))
        self.app.entry_tag_search.bind("<FocusOut>", lambda e: UIUtils.add_placeholder(self.app.entry_tag_search, self.app.tag_manager.TAG_SEARCH_PLACEHOLDER))
        self.app.entry_tag_search.bind("<KeyRelease>", self.app.tag_manager.on_tag_search_changed)
        self.app.entry_tag_search.bind("<Escape>", self.app.tag_manager.reset_tag_search)
        # Enter übergibt den Tastatur-Fokus an den Baum (Leertaste kann den gefundenen Tag
        # dann direkt zu-/abschalten); umgekehrt springt der Fokus beim Loslegen im Baum
        # zurück ins Suchfeld (siehe on_tag_tree_typed, unten am tree_tags-Binding-Block).
        self.app.entry_tag_search.bind("<Return>", self.app.tag_manager.on_tag_search_return)
        # F2/Strg+I direkt aus dem Suchfeld auf den gefundenen Tag (siehe on_tag_search_shortcut)
        self.app.entry_tag_search.bind("<F2>", lambda e: self.app.tag_manager.on_tag_search_shortcut(e, self.app.tag_editor.rename_tag))
        self.app.entry_tag_search.bind("<Control-i>", lambda e: self.app.tag_manager.on_tag_search_shortcut(e, self.app.tag_editor.ignoriere_tag))

        scroll_tags_y = ttk.Scrollbar(frame_tags, orient="vertical")
        # Eigener, dauerhafter Style-Name (statt zwischen "Treeview"/"FilterTree.Treeview" zu wechseln):
        # erbt über die ttk-Style-Kaskade weiterhin den Tk-8.6.9-Fix auf "Treeview" (siehe gui.py).
        # show="tree" (ohne "headings"): den Header brauchen wir aktuell nicht, das Suchfeld
        # oben übernimmt seine Rolle.
        self.app.tree_tags = ttk.Treeview(frame_tags, selectmode="extended", show="tree", style="Tags.Treeview", yscrollcommand=scroll_tags_y.set)
        scroll_tags_y.config(command=self.app.tree_tags.yview)

        scroll_tags_y.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 5), pady=5)
        self.app.tree_tags.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0), pady=5)
        
        self.app.tree_tags.tag_configure("active_tag", font=("", 10, "bold"), foreground="#0055a4")
        self.app.tree_tags.tag_configure("temp_tag", font=("", 10, "italic"), foreground="#0055a4")
        self.app.tree_tags.tag_configure("separator_tag", foreground="#cccccc")
        
        self.app.tag_editor.load_tags()
        
        self.app.tree_tags.bind("<<TreeviewSelect>>", self.app.tag_manager.on_tag_select)
        self.app.tree_tags.bind("<Double-1>", self.app.tag_manager.on_tag_double_click)
        self.app.tree_tags.bind("<space>", self.app.tag_manager.on_space_toggle)
        # Lostippen im Baum schickt den Fokus zurück ins Suchfeld (siehe entry_tag_search
        # oben) und übernimmt das erste Zeichen. add="+", damit Leertaste/Navigation/
        # Kürzel unangetastet bleiben (FALLSTRICKE #19).
        self.app.tree_tags.bind("<KeyPress>", self.app.tag_manager.on_tag_tree_typed, add="+")
        self.app.tree_tags.bind("<Button-3>", self.app.tag_editor.show_menu)
        self.app.tree_tags.bind("<F2>", self.app.tag_editor.rename_tag)
        self.app.tree_tags.bind("<Delete>", self.app.tag_editor.delete_tag)
        self.app.tree_tags.bind("<Control-i>", self.app.tag_editor.ignoriere_tag)
        self.app.tree_tags.bind("<Control-x>", self.app.tag_editor.cut_tag)
        self.app.tree_tags.bind("<Control-v>", self.app.tag_editor.paste_tag)
        self.app.tree_tags.bind("<Alt-Up>", self.app.tag_editor.move_tag_up)
        self.app.tree_tags.bind("<Alt-Down>", self.app.tag_editor.move_tag_down)

        # Such- & Filterleiste
        frame_search = ttk.Frame(self.app.col2_pane, relief="groove", borderwidth=1)
        self.app.col2_pane.add(frame_search, weight=0)

        search_inner = tk.Frame(frame_search)
        search_inner.pack(fill=tk.X, padx=5, pady=5)

        # LED „KI verbunden / KI nicht erreichbar" ganz rechts (ki_status.py, 13.09.2026);
        # ZUERST gepackt, damit bei schmalem Fenster das Suchfeld schrumpft und nicht die LED.
        # Gefüttert wird sie von gui.py, sobald der KiStatus-Thread läuft.
        self.app.ki_led = KiLed(search_inner)
        self.app.ki_led.pack(side=tk.RIGHT, padx=(10, 8))  # rechts etwas Luft zum Rand (Peter 13.09.2026)

        tk.Label(search_inner, text="Text:").pack(side=tk.LEFT, padx=(0,5))
        # Seit 13.09.2026 ein einzeiliges Text-Feld (suchfeld.SuchFeld) statt ttk.Entry:
        # bekannte Tags im Suchtext erscheinen blau-fett wie im Tag-Baum, und dieselbe
        # Autovervollständigung wie im Tags-Feld schlägt beim Tippen Tags vor.
        self.app.entry_search = SuchFeld(search_inner, self.app.tag_manager.get_known_tags, width=15)
        self.app.entry_search.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,10))
        # Gesucht wird erst mit Return (Peter 01.11.2026) - Tippen sucht nicht, nur ein geleertes Feld
        # setzt die angezeigte Suche sofort zurück (search_manager.feld_geleert)
        self.app.entry_search.bind("<KeyRelease>", self.app.search_manager.feld_geleert, add="+")

        def nach_tag_uebernahme():
            self.app.entry_search.markiere_tags()
            self.app.search_manager.trigger_search()

        self.app.such_autocomplete = TagAutocomplete(self.app, text=self.app.entry_search, trenner=None,
                                                     nach_uebernahme=nach_tag_uebernahme)

        # Return im einzeiligen Feld: kein Zeilenumbruch, sondern sofort suchen. NACH der
        # Autovervollständigung binden - deren Return-Handler übernimmt zuerst einen
        # offenen Vorschlag und stoppt dann per "break".
        def suche_sofort(event):
            self.app.search_manager.apply_filters()
            return "break"

        self.app.entry_search.bind("<Return>", suche_sofort, add="+")
        self.app.entry_search.bind("<KP_Enter>", suche_sofort, add="+")

        # --- NEU: OCR Checkbox wird nur 1x beim Start gezeichnet ---
        self.app.use_ocr_var = tk.BooleanVar(value=False)
        chk_ocr = ttk.Checkbutton(
            search_inner, 
            text="Inhalt (OCR)", 
            variable=self.app.use_ocr_var,
            command=self.app.search_manager.trigger_search
        )
        chk_ocr.pack(side=tk.LEFT, padx=(0, 10))
        # -----------------------------------------------------------

        tk.Label(search_inner, text="Von:").pack(side=tk.LEFT, padx=(0,5))
        self.app.entry_date_from = ttk.Entry(search_inner, width=11)
        self.app.entry_date_from.pack(side=tk.LEFT, padx=(0,10))
        self.app.entry_date_from.insert(0, "TT.MM.JJJJ")
        self.app.entry_date_from.bind("<FocusIn>", lambda e: UIUtils.clear_placeholder(self.app.entry_date_from, "TT.MM.JJJJ"))
        self.app.entry_date_from.bind("<FocusOut>", lambda e: UIUtils.add_placeholder(self.app.entry_date_from, "TT.MM.JJJJ"))
        self.app.entry_date_from.bind("<KeyRelease>", self.app.search_manager.feld_geleert)
        self.app.entry_date_from.bind("<Return>", lambda e: self.app.search_manager.apply_filters())
        self.app.entry_date_from.bind("<KP_Enter>", lambda e: self.app.search_manager.apply_filters())

        tk.Label(search_inner, text="Bis:").pack(side=tk.LEFT, padx=(0,5))
        self.app.entry_date_to = ttk.Entry(search_inner, width=11)
        self.app.entry_date_to.pack(side=tk.LEFT, padx=(0,10))
        self.app.entry_date_to.insert(0, "TT.MM.JJJJ")
        self.app.entry_date_to.bind("<FocusIn>", lambda e: UIUtils.clear_placeholder(self.app.entry_date_to, "TT.MM.JJJJ"))
        self.app.entry_date_to.bind("<FocusOut>", lambda e: UIUtils.add_placeholder(self.app.entry_date_to, "TT.MM.JJJJ"))
        self.app.entry_date_to.bind("<KeyRelease>", self.app.search_manager.feld_geleert)
        self.app.entry_date_to.bind("<Return>", lambda e: self.app.search_manager.apply_filters())
        self.app.entry_date_to.bind("<KP_Enter>", lambda e: self.app.search_manager.apply_filters())

        # Hinweis auf die gröberen Eingaben (Nutzerwunsch 01.09.2026): "2020"/"2022" grenzt
        # auf ganze Jahre ein, "07.2020" auf einen Monat - im Bis-Feld jeweils bis zum Ende.
        # Seit 13.09.2026 als Tooltip statt Dauertext (Platz in der Suchleiste).
        datums_hinweis = ('Tag.Monat.Jahr, oder gröber: "2020" = ganzes Jahr, "07.2020" = ganzer Monat '
                          '- im Bis-Feld jeweils bis zum Ende.')
        Tooltip(self.app.entry_date_from, datums_hinweis)
        Tooltip(self.app.entry_date_to, datums_hinweis)

        btn_reset_search = ttk.Button(search_inner, text="✖ Reset", command=self.app.search_manager.reset_search, style="Danger.TButton")
        btn_reset_search.pack(side=tk.LEFT)

        # Feste Breite: die Suchleiste soll nicht springen, wenn die Zahl erscheint oder wächst
        self.app.lbl_treffer = tk.Label(search_inner, text="", width=13, anchor="w")
        self.app.lbl_treffer.pack(side=tk.LEFT, padx=(10, 0))
        Tooltip(self.app.entry_search,
                'Tippfehler werden verziehen. Mehrere Wörter müssen alle vorkommen.\n'
                '"Wort" in Anführungszeichen findet nur genau dieses Wort, "zwei Wörter" genau diese Folge.\n'
                '* und ? sind Platzhalter. Gesucht wird mit der Eingabetaste.')


        # Dokumenten Grid
        frame_files = ttk.Frame(self.app.col2_pane, relief="groove", borderwidth=1)
        self.app.col2_pane.add(frame_files, weight=2)
        frame_files.grid_rowconfigure(0, weight=1)
        frame_files.grid_columnconfigure(0, weight=1)
        
        # WICHTIG: neue Spalten immer ANHÄNGEN, nie dazwischen einfügen — der restliche
        # Code greift per festem Index auf values zu (z.B. values[4] = rel_path), Anhängen
        # hält die bestehenden Indizes stabil. Sichtbarkeit wird separat über
        # displaycolumns gesteuert.
        columns = ("datum", "titel", "tags", "name", "path", "ordner", "scan_zeit", "qualitaet", "erfasst")
        self.app.tree_files = ttk.Treeview(frame_files, columns=columns, show="headings", selectmode="extended")

        # Sichtbare Spalten aus der Config (Standard: STANDARD_SPALTEN)
        visible = self.app.config.get("visible_columns", list(STANDARD_SPALTEN))
        visible = [c for c in visible if c in columns] or list(STANDARD_SPALTEN)
        self.app.tree_files["displaycolumns"] = visible

        scroll_y = ttk.Scrollbar(frame_files, orient="vertical", command=self.app.tree_files.yview)
        scroll_x = ttk.Scrollbar(frame_files, orient="horizontal", command=self.app.tree_files.xview)
        self.app.tree_files.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)

        self.app.tree_files.grid(row=0, column=0, sticky="nsew", padx=(5,0), pady=(5,0))
        scroll_y.grid(row=0, column=1, sticky="ns", padx=(0,5), pady=(5,0))
        scroll_x.grid(row=1, column=0, sticky="ew", padx=(5,0), pady=(0,5))

        # Headings & Spalteneinstellungen
        headings = {"datum": "Datum", "titel": "Titel", "tags": "Tags", "name": "Dateiname", "path": "Pfad (relativ)", "ordner": "Ordner", "scan_zeit": "Scan-Zeitpunkt", "qualitaet": "Textqualität", "erfasst": "Erfasst"}
        for col, text in headings.items():
            self.app.tree_files.heading(col, text=text, command=lambda _col=col: UIUtils.sort_treeview(self.app.tree_files, _col, False))

        # Minimale Spaltenbreiten: Defaults, überschreibbar per settings.json
        # (Key "column_min_widths", z.B. {"titel": 200})
        # Alle Breiten in 100-%-Pixeln, hochgerechnet mit der Skalierung (siehe STANDARD_BREITEN)
        skalierung = UIUtils.skalierung(self.app.root)
        min_widths = dict(MINDEST_BREITEN)
        min_widths.update(self.app.config.get("column_min_widths", {}))
        breiten = dict(STANDARD_BREITEN)
        breiten.update({k: v for k, v in self.app.config.get("column_widths", {}).items() if k in breiten})
        min_widths = breiten_fuer_bildschirm(min_widths, skalierung)
        breiten = breiten_fuer_bildschirm(breiten, skalierung)
        for col, breite in breiten.items():
            self.app.tree_files.column(col, width=breite, minwidth=min_widths[col], stretch=False,
                                       anchor="e" if col == "qualitaet" else "w")
        
        self.app.tree_files.tag_configure("dragged", font=("", 10, "italic"))
        self.app.tree_files.tag_configure("trash_file", foreground="#a0a0a0", font=("", 10, "italic"))
        
        # --- NEU: Farbe für lokale Suchtreffer ---
        self.app.tree_files.tag_configure("search_local", foreground="steelblue")

        # --- NEU: Pastell-Farben für abwechselnde Zeilen ---
        self.app.tree_files.tag_configure("row_even", background="#E8F0FE") # Leichtes Blau
        self.app.tree_files.tag_configure("row_odd", background="#E6F4EA")  # Leichtes Grün

        # --- NEU: Kennzeichnung für Dokumente ohne eigene Titel/Tags/Datum (noch nie bearbeitet) ---
        self.app.tree_files.tag_configure("untouched", foreground="#E07800")

        # Events binden
        self.app.tree_files.bind("<<TreeviewSelect>>", self.app.on_file_select)
        self.app.tree_files.bind("<Button-3>", self.app.file_ops.show_context_menu)
        self.app.tree_files.bind("<Double-1>", self.app.file_ops.on_tree_double_click)
        self.app.tree_files.bind("<F2>", self.app.file_ops.rename_file)
        self.app.tree_files.bind("<Delete>", self.app.file_ops.delete_file)
        self.app.tree_files.bind("<Return>", self.app.file_ops.open_file_native)
        self.app.tree_files.bind("<Key>", self.app.datum_aus_liste_tippen)
        self.app.tree_files.bind("<ButtonPress-1>", self.app.file_ops.on_drag_start)
        self.app.tree_files.bind("<B1-Motion>", self.app.file_ops.on_drag_motion)
        self.app.tree_files.bind("<ButtonRelease-1>", self.app.file_ops.on_drag_stop)

        # Rechtsklick auf die Kopfzeile: Spalten ein-/ausblenden (persistiert in settings.json).
        # WICHTIG: muss NACH dem Button-3-Binding oben registriert werden — bind() ohne
        # add="+" ersetzt alle vorherigen Bindings desselben Events (siehe FALLSTRICKE #19).
        self._setup_column_menu(headings)

        # Hinweis: Der PDF-Inspektor hängt sich als Tool-Plugin selbst unten an
        # dieses Menü an (🛠-Einträge via ToolManager.populate_context_menu).
        self.app.file_context_menu = tk.Menu(self.root, tearoff=0)
        self.app.file_context_menu.add_command(label="Öffnen (Enter / Doppelklick)", command=self.app.file_ops.open_file_native)
        self.app.file_context_menu.add_command(label="Im Ordner anzeigen (Explore...)", command=self.app.file_ops.open_in_explorer)
        self.app.file_context_menu.add_separator()
        self.app.file_context_menu.add_command(label="Wiederherstellen...", command=self.app.file_ops.restore_file)
        self.app.file_context_menu.add_separator()
        self.app.file_context_menu.add_command(label="Umbenennen (F2)", command=self.app.file_ops.rename_file)
        self.app.file_context_menu.add_command(label="Löschen (Entf)", command=self.app.file_ops.delete_file)

        # Eigenschaften-Panel: seit 14.09.2026 EINE Tabelle mit Linien (dokument_eigenschaften.py).
        # Das Panel besitzt den Raster-Frame `tabelle`; Titel, Tags und Datum werden hier MIT
        # diesem Frame als Master angelegt (flache tk-Widgets ohne eigenen Rand, damit sie wie
        # Zellen wirken) und dem Panel übergeben, das sie zusammen mit den grauen
        # schreibgeschützten Zellen anordnet. Darunter die Knopfzeile Speichern / Auto-Save / Details.
        frame_props = ttk.Frame(self.app.col2_pane, relief="groove", borderwidth=1)
        self.app.col2_pane.add(frame_props, weight=0)
        # Knopfzeile ZUERST und unten verankert (Regel aus ui_utils: Knopfleisten vor dem dehnbaren
        # Inhalt mit side=BOTTOM packen) - sonst schiebt die aufgeklappte Tabelle Speichern/Details
        # aus dem Bereich (Peter 15.09.2026). Das Panel fordert zusätzlich beim Aufklappen den
        # nötigen Platz vom PanedWindow an, so dass sich der Bereich nach oben entfaltet.
        knopfzeile = ttk.Frame(frame_props)
        knopfzeile.pack(side=tk.BOTTOM, fill=tk.X, padx=4, pady=(0, 4))
        self.app.eigenschaften_panel = EigenschaftenPanel(self.app, frame_props, chk_parent=knopfzeile)
        tabelle = self.app.eigenschaften_panel.tabelle
        tabelle.pack(side=tk.TOP, fill=tk.X, padx=4, pady=(4, 2))

        default_font = tkfont.nametofont("TkDefaultFont")
        self.app.entry_title = tk.Entry(tabelle, relief="flat", bd=0, font=default_font)
        self.app.entry_title.bind("<KeyRelease>", self.app.save_manager.trigger_autosave)

        # Einzeilig seit 07.09.2026 (Nutzerwunsch: Platz für die Detail-Eigenschaften darunter);
        # bleibt ein Text-Widget wegen Autovervollständigung und Live-Sync - ohne Umbruch
        # scrollt es beim Tippen waagerecht mit.
        self.app.entry_tags = tk.Text(tabelle, height=1, wrap="none", font=default_font, relief="flat", bd=0,
                                      padx=UIUtils.px(tabelle, 2), pady=UIUtils.px(tabelle, 3))  # padx wie der Text-Einzug eines Entry

        def on_tags_keyrelease(event):
            # Beim Tippen nur die Baum-Hervorhebung live mitführen und die Änderung
            # vormerken - der Auto-Save wird bewusst NICHT pro Tastendruck getriggert,
            # sonst landen halbfertige Tags ("Rech" statt "Rechnung") im PDF und in
            # der Zuletzt-benutzt-Liste. Gespeichert wird erst bei Bestätigung
            # (Return/Enter, Fokus-Verlust) oder Dateiwechsel (flush_pending).
            self.app.tag_manager.sync_tag_tree_selection(event)
            if event.keysym not in ("Up", "Down", "Left", "Right", "Home", "End", "Return", "KP_Enter",
                                    "Escape", "Tab", "Shift_L", "Shift_R", "Control_L", "Control_R"):
                self.app.save_manager.mark_dirty()

        self.app.entry_tags.bind("<KeyRelease>", on_tags_keyrelease)

        # Autovervollständigung mit existierenden Tags (Dropdown unter dem Cursor)
        self.app.tag_autocomplete = TagAutocomplete(self.app)

        # Bestätigung: erst Return/Enter oder Fokus-Verlust löst den Auto-Save aus.
        # WICHTIG: nach dem TagAutocomplete binden - dessen Return-Handler läuft dann
        # zuerst und stoppt per "break", wenn er einen Vorschlag übernimmt.
        def on_tags_confirm(event):
            self.app.save_manager.commit_pending_edits()
            return "break"  # verhindert Zeilenumbruch im Tags-Feld

        self.app.entry_tags.bind("<Return>", on_tags_confirm, add="+")
        self.app.entry_tags.bind("<KP_Enter>", on_tags_confirm, add="+")
        self.app.entry_tags.bind("<FocusOut>", self.app.save_manager.commit_pending_edits, add="+")
        
        # Dokumenten-Datum: seit 31.08.2026 bei den Eigenschaften statt über der Vorschau (Enter
        # speichert wie bisher); als bearbeitbare Zelle im Raster, teilt sich die Zeile mit
        # Scan-Zeitpunkt, Seiten und Größe (Standard-Aufteilung).
        self.app.date_entry = tk.Entry(tabelle, relief="flat", bd=0, font=default_font)
        self.app.date_entry.bind("<Return>", self.app.save_manual_date)
        # Orange hinterlegt = nur vermutet (FALLSTRICKE #86): Ziffer in der Liste springt ins Feld,
        # Klick ins Feld markiert alles, Esc stellt den Vorschlag wieder her
        self.app.date_entry_hintergrund = self.app.date_entry.cget("background")
        self.app.date_entry.bind("<FocusIn>", self.app.datum_feld_betreten, add="+")
        self.app.date_entry.bind("<Escape>", self.app.datum_vorschlag_zurueck)
        Tooltip(self.app.date_entry,
                "Orange hinterlegt = aus dem Dokument gelesenes, vermutetes Datum - noch nicht gespeichert. "
                "Zum Ändern einfach in der Dokumentenliste das richtige Datum tippen (Esc = zurück). "
                "Return speichert; Speichern von Titel/Tags und mit Auto-Save das Weiterklicken auch.")

        self.app.eigenschaften_panel.setze_eingabefelder(
            feste=[("Titel", self.app.entry_title), ("Tags", self.app.entry_tags)],
            fluss={"datum": self.app.date_entry})

        # Knopfzeile unter der Tabelle: Speichern, Auto-Save, Details (klappt die Zone
        # „nur ausgeklappt“ der Tabelle ein/aus, siehe dokument_eigenschaften.py)
        self.app.btn_save = ttk.Button(knopfzeile, text="Speichern", command=self.app.save_manager.save_selected, style="Accent.TButton")
        self.app.btn_save.pack(side=tk.LEFT)
        self.app.chk_autosave = ttk.Checkbutton(knopfzeile, text="Auto-Save", variable=self.app.autosave_var, command=self.app.save_manager.toggle_autosave)
        self.app.chk_autosave.pack(side=tk.LEFT, padx=8)
        self.app.eigenschaften_panel.chk.pack(side=tk.LEFT)
        self.app.eigenschaften_panel.leiste_mail.pack(side=tk.LEFT, padx=(UIUtils.px(knopfzeile, 16), 0))

        if self.app.autosave_var.get():
            self.app.btn_save.config(state=tk.DISABLED)

        # (Das Dokumenten-Datum sitzt seit 31.08.2026 unten bei den Eigenschaften -
        # die eigene Zeile hier oben kostete Vorschau-Höhe, siehe MANUELLE_TESTS 10k.)
        # Vorschau-Bereich
        self.app.preview_inner = tk.Frame(self.app.col3_frame, bg="#2b2b2b")
        self.app.preview_inner.pack(fill=tk.BOTH, expand=True)

        self.app.canvas_preview = tk.Canvas(self.app.preview_inner, bg="#8f8f8f", highlightthickness=0)
        # Die Leiste steht für das GANZE Dokument, nicht nur die aktuelle Seite (Nutzerwunsch
        # 25.10.2026) - der PreviewManager rechnet zwischen Seiten- und Dokument-Bildlauf um
        self.app.scroll_preview = ttk.Scrollbar(self.app.preview_inner, orient="vertical",
                                                command=self.app.preview_manager.on_scrollbar)
        self.app.canvas_preview.configure(yscrollcommand=self.app.preview_manager.on_canvas_yview)
        # Waagerecht nur bei Bedarf (gezoomte Seite breiter als die Vorschau) - blendet sich selbst ein/aus
        self.app.scroll_preview_x = ttk.Scrollbar(self.app.preview_inner, orient="horizontal",
                                                  command=self.app.canvas_preview.xview)
        self.app.canvas_preview.configure(xscrollcommand=self.app.preview_manager.on_canvas_xview)

        self.app.scroll_preview.pack(side=tk.RIGHT, fill=tk.Y)
        self.app.canvas_preview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.app.canvas_preview.bind("<Configure>", self.app.preview_manager.on_canvas_resize)
        self.app.canvas_preview.bind("<MouseWheel>", self.app.preview_manager.on_preview_mousewheel)
        # Linux MouseWheel Bindings
        self.app.canvas_preview.bind("<Button-4>", self.app.preview_manager.on_preview_mousewheel)
        self.app.canvas_preview.bind("<Button-5>", self.app.preview_manager.on_preview_mousewheel)
        # Optional: Auch für den Zoom unter Linux
        self.app.canvas_preview.bind("<Control-Button-4>", self.app.preview_manager.on_zoom_mousewheel)
        self.app.canvas_preview.bind("<Control-Button-5>", self.app.preview_manager.on_zoom_mousewheel)
        self.app.canvas_preview.bind("<Control-MouseWheel>", self.app.preview_manager.on_zoom_mousewheel)
        self.app.canvas_preview.bind("<ButtonPress-1>", self.app.preview_manager.on_canvas_click)
        self.app.canvas_preview.bind("<B1-Motion>", self.app.preview_manager.on_canvas_drag)
        self.app.canvas_preview.bind("<Double-Button-1>", self.app.preview_manager.reset_zoom)

        self.app.col3_frame.bind("<Double-Button-1>", self.app.preview_manager.reset_zoom)

        self.root.bind("<Prior>", lambda e: self.app.preview_manager.flip_page(-3, e))
        self.root.bind("<Next>",  lambda e: self.app.preview_manager.flip_page(3, e))
        self.root.bind("<Left>",  lambda e: self.app.preview_manager.flip_page(-1, e))
        self.root.bind("<Right>", lambda e: self.app.preview_manager.flip_page(1, e))
        # Pos1/Ende: erste/letzte Seite (der Sprung wird in _blaettern auf das Dokument begrenzt)
        self.root.bind("<Home>", lambda e: self.app.preview_manager.flip_page(-SEITEN_BIS_ENDE, e))
        self.root.bind("<End>", lambda e: self.app.preview_manager.flip_page(SEITEN_BIS_ENDE, e))
        # Dokumentenliste: ↑/↓ wählen, ←/→ und Bild↑/↓ blättern die Vorschau - mit "break", sonst scrollte
        # die Liste bei Bild↑/↓ mit. Ordner- und Tag-Baum behalten ihre Tasten (flip_page, Peter 28.10.2026)
        for taste, delta in (("<Prior>", -3), ("<Next>", 3), ("<Left>", -1), ("<Right>", 1)):
            self.app.tree_files.bind(taste, lambda e, d=delta: (self.app.preview_manager.flip_page(d, e), "break")[1])
        # Pos1/Ende springen in Liste und Bäumen auf den ersten/letzten (sichtbaren) Eintrag, wie im Explorer -
        # in der Liste also aufs erste/letzte DOKUMENT, nicht auf die Seite (Peter 28.10.2026)
        self.app.tree_files.bind("<Home>", lambda e: UIUtils.baum_springen(self.app.tree_files, ende=False))
        self.app.tree_files.bind("<End>", lambda e: UIUtils.baum_springen(self.app.tree_files, ende=True))
        self.app.tree_folders.bind("<Home>", lambda e: UIUtils.baum_springen(self.app.tree_folders, ende=False))
        self.app.tree_folders.bind("<End>", lambda e: UIUtils.baum_springen(self.app.tree_folders, ende=True))
        self.app.tree_tags.bind("<Home>", lambda e: UIUtils.baum_springen(self.app.tree_tags, ende=False))
        self.app.tree_tags.bind("<End>", lambda e: UIUtils.baum_springen(self.app.tree_tags, ende=True))
        
        self.app.current_preview_path = None