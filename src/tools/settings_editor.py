import json
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import aktivitaet
import app_paths
import bestaetigung
import ollama_client
import server_wecken
import versionspruefung
import dokument_eigenschaften as de
from dokument_eigenschaften import EINSTELLUNG_DETAILS, EINSTELLUNG_FELDER
from preview_manager import EINSTELLUNG_NACHLAUF
from tools.base_tool import BaseTool, ToolContext
from ui_utils import UIUtils, ProgressDialog


# ==========================================
# 1. DIE TOOL-SCHNITTSTELLE (Der Wrapper)
# ==========================================
class SettingsEditorTool(BaseTool):
    def __init__(self):
        self.editor_window = None

    @property
    def name(self) -> str: return "Einstellungen..."

    @property
    def absicht(self) -> str:
        return ("Alle Einstellungen an einem Ort mit Erklärzeile - erreichbar über Datei → Einstellungen. Änderungen wirken sofort, ohne Neustart.")

    @property
    def description(self) -> str: return "Bearbeitet die settings.json mit Live-Übernahme."

    @property
    def menu_hooks(self) -> list: return []  # Seit 07.09.2026 unter Datei -> Einstellungen... (gui.oeffne_einstellungen)

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        if self.editor_window and self.editor_window.winfo_exists():
            self.editor_window.lift()
            self.editor_window.focus()
        else:
            self.editor_window = SettingsEditorWindow(context.app.root, context.app)
        return True


# ==========================================
# 2. DAS EINSTELLUNGS-FENSTER
# ==========================================
class SettingsEditorWindow(tk.Toplevel):
    """
    Kuratierte Einstellungsseite für die settings.json. Bekannte Einstellungen
    bekommen passende Widgets und werden sofort live übernommen (kein Neustart);
    alle übrigen Keys sind im Experten-Bereich als Roh-JSON editierbar.
    """

    # Diese Keys haben eigene Widgets — alles andere landet im Experten-Reiter
    CURATED_KEYS = ("master_folder", "autosave", "auto_fill_on_click", "visible_columns", "column_min_widths",
                    "custom_zoom", "show_help_on_start", "use_index", "index_text_mode", "ollama_url",
                    "ollama_model", "auto_pilot_enabled",
                    "auto_pilot_nur_bekannte_tags", "auto_pilot_neue_tags_ab",   # seit Etappe 6 ohne Wirkung, ausgeblendet
                    "auto_pilot_umbenennen", "ki_cpu_erlauben", "ki_entscheidungsmodell", "ki_wol_mac", versionspruefung.EINSTELLUNG,
                    bestaetigung.EINSTELLUNG, EINSTELLUNG_DETAILS, EINSTELLUNG_FELDER)

    COLUMN_LABELS = {"datum": "Datum", "titel": "Titel", "tags": "Tags",
                     "name": "Dateiname", "path": "Pfad", "ordner": "Ordner", "scan_zeit": "Scan-Zeitpunkt",
                     "qualitaet": "Textqualität", "erfasst": "Erfasst"}

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app

        breite, hoehe = UIUtils.position_near_mouse(self, UIUtils.px(self, 730), UIUtils.px(self, 620))  # 8 Reiter
        self.transient(parent)
        self.title("⚙️ Einstellungen")
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self._setup_ui()
        # Mindestgröße = was der größte Reiter braucht (gemessen, passt sich 125 % Textgröße an; 100 %: 710 × 619),
        # höchstens die Startgröße - die ist schon auf den Bildschirm begrenzt (Peter 02.11.2026)
        self.update_idletasks()
        self.minsize(min(self.winfo_reqwidth(), breite), min(self.winfo_reqheight(), hoehe))

    # ==========================================
    # UI-AUFBAU (Reiter, seit 07.09.2026 - Nutzerwunsch: "es wird schon einiges eingestellt")
    # ==========================================
    def _reiter(self, titel):
        """Neuer Reiter im Notebook, liefert den Inhalts-Frame."""
        frame = ttk.Frame(self.notebook, padding=12)
        self.notebook.add(frame, text=titel)
        return frame

    def _hinweis(self, parent, text, einzug=28, pady=(0, 8), breite=580):
        """Graue Erklärungszeile unter einer Option - in Klartext, was die Option bewirkt."""
        label = ttk.Label(parent, text=text, foreground="gray40", justify="left",
                          wraplength=UIUtils.px(self, breite))
        label.pack(anchor="w", padx=(einzug, 8), pady=pady)
        return label

    def _schalter(self, parent, text, var, command, pady=(6, 0)):
        ttk.Checkbutton(parent, text=text, variable=var, command=command).pack(anchor="w", padx=8, pady=pady)

    def _setup_ui(self):
        # Fußzeile ZUERST und unten verankert: Tk verteilt den Platz in Pack-Reihenfolge -
        # wird das Notebook (fill/expand) höher als das Fenster, fiele eine danach gepackte
        # Fußzeile samt „Schließen" einfach weg (Tester-PC, 125 % Textgröße, FALLSTRICKE #69).
        fuss = ttk.Frame(self, padding=(8, 4, 8, 8))
        fuss.pack(side=tk.BOTTOM, fill=tk.X)
        ttk.Label(fuss, text="Änderungen gelten sofort und werden in settings.json gespeichert.",
                  foreground="gray40").pack(side=tk.LEFT)
        ttk.Button(fuss, text="Schließen", command=self.destroy).pack(side=tk.RIGHT)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(8, 0))

        self._reiter_allgemein(self._reiter("Allgemein"))
        self._reiter_liste(self._reiter("Dokumentenliste"))
        self._reiter_eigenschaften(self._reiter("Eigenschaften"))
        self._reiter_vorschau(self._reiter("Vorschau"))
        self._reiter_suche(self._reiter("Suche & Volltext"))
        self._reiter_ki(self._reiter("KI-Server"))
        self._reiter_automatik(self._reiter("Vollautomatik"))
        self._reiter_experten(self._reiter("Experten"))

    # ---------- Reiter: Allgemein ----------
    def _reiter_allgemein(self, tab):
        row = ttk.Frame(tab)
        row.pack(fill=tk.X, padx=8, pady=(0, 2))
        ttk.Label(row, text="Sammlung (Hauptordner):").pack(side=tk.LEFT)
        # Knopf VOR dem Pfad packen: ein langer Pfad drängte ihn sonst aus dem Fenster
        ttk.Button(row, text="Ändern...", command=self._change_master_folder).pack(side=tk.RIGHT)
        self.lbl_master = ttk.Label(row, text=self.app.config.get("master_folder", "(nicht gesetzt)"), foreground="#555555")
        self.lbl_master.pack(side=tk.LEFT, padx=8, fill=tk.X)
        self._hinweis(tab, "Der Ordner mit allen Dokumenten. Daneben liegt der Daten-Ordner "
                           "'<Name>-Daten' mit Papierkorb, Tag-Katalog, Suchindex und Protokollen.", einzug=8)

        self.var_autosave = tk.BooleanVar(value=bool(self.app.config.get("autosave", False)))
        self._schalter(tab, "Auto-Save: Titel, Tags und Datum automatisch ins PDF speichern",
                       self.var_autosave, self._apply_autosave)
        self._hinweis(tab, "Gespeichert wird beim Verlassen des Feldes, bei Enter oder beim Wechsel zum "
                           "nächsten Dokument - der Knopf 'Speichern' ist dann überflüssig.")

        self.var_auto_fill = tk.BooleanVar(value=bool(self.app.config.get("auto_fill_on_click", False)))
        self._schalter(tab, "Unbearbeitete Dokumente beim Anklicken automatisch vorbelegen",
                       self.var_auto_fill, lambda: self.app.config.set("auto_fill_on_click", self.var_auto_fill.get()))
        self._hinweis(tab, "Dateiname wird als Titel und das erkannte Datum als Dokumentdatum übernommen - "
                           "das verändert das PDF schon beim bloßen Anklicken (nur mit Auto-Save wirksam). "
                           "Orange Einträge in der Liste sind solche noch unberührten Dokumente.")

        self.var_bestaetigungen = tk.BooleanVar(value=bestaetigung.aktiv())
        self._schalter(tab, "Sicherheitsabfragen anzeigen (Rückfrage vor Papierkorb, Einsortieren, Tag löschen ...)",
                       self.var_bestaetigungen, self._apply_bestaetigungen)
        self._hinweis(tab, "Ausgeschaltet laufen Routine-Aktionen ohne Ja/Nein-Dialog durch. Unumkehrbares fragt "
                           "trotzdem immer: endgültiges Löschen aus dem Papierkorb, Überschreiben einer Datei, Löschen "
                           "einer Tag-Kategorie oder eines Tags mit Unter-Tags.")

        self.var_help_start = tk.BooleanVar(value=bool(self.app.config.get("show_help_on_start", True)))
        self._schalter(tab, "Schnellstart-Hilfe beim Programmstart anzeigen",
                       self.var_help_start, lambda: self.app.config.set("show_help_on_start", self.var_help_start.get()))

        self.var_menue_erklaerungen = tk.BooleanVar(value=bool(self.app.config.get("menue_erklaerungen", True)))
        self._schalter(tab, "Erklärung beim Verweilen auf einem Menüeintrag anzeigen",
                       self.var_menue_erklaerungen,
                       lambda: self.app.config.set("menue_erklaerungen", self.var_menue_erklaerungen.get()))
        self._hinweis(tab, "Bleibt der Mauszeiger gut eine Sekunde auf einem Menüeintrag, erscheint daneben, was der "
                           "Eintrag tut und wofür er gedacht ist. Dieselben Texte stehen unter Hilfe → Menü-Übersicht.")

        self.var_versionspruefung = tk.BooleanVar(value=bool(self.app.config.get(versionspruefung.EINSTELLUNG, True)))
        self._schalter(tab, "Beim Programmstart auf eine neue Version prüfen",
                       self.var_versionspruefung,
                       lambda: self.app.config.set(versionspruefung.EINSTELLUNG, self.var_versionspruefung.get()))
        self._hinweis(tab, "Fragt kurz nach dem Start die Releases-Seite auf github.com ab und meldet sich nur, wenn "
                           "eine neuere Version bereitliegt (keine Meldung bei „aktuell“ oder ohne Internet). Es werden "
                           "keine Angaben über dich oder deine Dokumente übertragen. Jederzeit von Hand: "
                           "Hilfe → Auf neue Version prüfen…")

    # ---------- Reiter: Dokumentenliste ----------
    def _reiter_liste(self, tab):
        ttk.Label(tab, text="Sichtbare Spalten:").pack(anchor="w", padx=8, pady=(0, 2))
        self._hinweis(tab, "Geht auch per Rechtsklick auf die Spaltenköpfe der Dokumentenliste.", einzug=8, pady=(0, 4))
        cols_frame = ttk.Frame(tab)
        cols_frame.pack(fill=tk.X, padx=8)
        visible = list(self.app.tree_files["displaycolumns"])
        self.column_vars = {}
        for i, (col, label) in enumerate(self.COLUMN_LABELS.items()):
            var = tk.BooleanVar(value=(col in visible))
            self.column_vars[col] = var
            ttk.Checkbutton(cols_frame, text=label, variable=var,
                            command=self._apply_visible_columns).grid(row=i // 3, column=i % 3, sticky="w", padx=4, pady=2)

        ttk.Label(tab, text="Mindestbreite je Spalte (Pixel):").pack(anchor="w", padx=8, pady=(14, 2))
        self._hinweis(tab, "Schmaler als das lässt sich eine Spalte nicht ziehen - schützt z.B. das Datum vor "
                           "dem Abschneiden.", einzug=8, pady=(0, 4))
        min_frame = ttk.Frame(tab)
        min_frame.pack(fill=tk.X, padx=8, pady=(0, 6))
        defaults = {"datum": 85, "titel": 150, "tags": 180, "name": 100, "path": 80, "ordner": 80, "scan_zeit": 85, "erfasst": 110}
        saved_min = dict(defaults)
        saved_min.update(self.app.config.get("column_min_widths", {}))
        self.min_width_vars = {}
        for i, (col, label) in enumerate(self.COLUMN_LABELS.items()):
            cell = ttk.Frame(min_frame)
            cell.grid(row=i // 3, column=i % 3, sticky="w", padx=4, pady=2)
            ttk.Label(cell, text=f"{label}:", width=13).pack(side=tk.LEFT)
            var = tk.IntVar(value=int(saved_min.get(col, 80)))
            self.min_width_vars[col] = var
            spin = ttk.Spinbox(cell, from_=20, to=600, width=5, textvariable=var, command=self._apply_min_widths)
            spin.pack(side=tk.LEFT)
            spin.bind("<Return>", lambda e: self._apply_min_widths())
            spin.bind("<FocusOut>", lambda e: self._apply_min_widths())

    # ---------- Reiter: Vorschau ----------
    def _reiter_vorschau(self, tab):
        zoom = self.app.config.get("custom_zoom", None)
        self.var_zoom_mode = tk.StringVar(value="fest" if zoom else "auto")
        self.var_zoom_pct = tk.IntVar(value=int(float(zoom) * 100) if zoom else 100)

        ttk.Label(tab, text="Zoom der PDF-Vorschau:").pack(anchor="w", padx=8, pady=(0, 4))
        ttk.Radiobutton(tab, text="Automatisch: Seite an die Fensterbreite anpassen", value="auto",
                        variable=self.var_zoom_mode, command=self._apply_zoom).pack(anchor="w", padx=8)
        fest = ttk.Frame(tab)
        fest.pack(anchor="w", padx=8, pady=(4, 0))
        ttk.Radiobutton(fest, text="Fester Zoom:", value="fest",
                        variable=self.var_zoom_mode, command=self._apply_zoom).pack(side=tk.LEFT)
        spin_zoom = ttk.Spinbox(fest, from_=10, to=500, increment=25, width=5,
                                textvariable=self.var_zoom_pct, command=self._apply_zoom)
        spin_zoom.pack(side=tk.LEFT, padx=4)
        spin_zoom.bind("<Return>", lambda e: self._apply_zoom())
        spin_zoom.bind("<FocusOut>", lambda e: self._apply_zoom())
        ttk.Label(fest, text="%").pack(side=tk.LEFT)
        self._hinweis(tab, "Höchstens 500 % (Schutz vor Speicherüberlauf). Strg+Mausrad zoomt in der Vorschau, "
                           "ein Doppelklick auf die Seite passt sie wieder ein.", einzug=8, pady=(4, 8))

        self.var_nachlauf = tk.BooleanVar(value=bool(self.app.config.get(EINSTELLUNG_NACHLAUF, True)))
        self._schalter(tab, "Nach dem Blättern mit dem Mausrad kurz innehalten",
                       self.var_nachlauf, lambda: self.app.config.set(EINSTELLUNG_NACHLAUF, self.var_nachlauf.get()))
        self._hinweis(tab, "Dreht man das Mausrad über das Seitenende hinaus, beginnt die nächste Seite oben (rückwärts "
                           "die vorige an ihrem Ende): Weitere Rasten werden 0,3 Sekunden lang nicht beachtet. Aus = das "
                           "Rad scrollt nach dem Seitenwechsel sofort weiter.")

    # ---------- Reiter: Eigenschaften (Tabelle unter der Dokumentenliste, 15.09.2026) ----------
    def _reiter_eigenschaften(self, tab):
        self.var_details = tk.BooleanVar(value=bool(self.app.config.get(EINSTELLUNG_DETAILS, True)))
        self._schalter(tab, "Details anzeigen (die Felder unter dem ersten Trenner)", self.var_details,
                       self._apply_details, pady=(0, 0))
        self._hinweis(tab, "Graue, schreibgeschützte Zellen zum Markieren und Kopieren (Rechtsklick: Kopieren / "
                           "Alles kopieren). Dieselbe Checkbox „Details“ sitzt im Hauptfenster unter der Tabelle.")

        ttk.Label(tab, text="Felder der Eigenschaften-Tabelle - Reihenfolge, Sichtbarkeit und Breite:").pack(anchor="w", padx=8, pady=(6, 2))
        self._hinweis(tab, "Über dem ersten Trenner: immer sichtbar. Dazwischen: nur mit „Details“. Unter dem zweiten: "
                           "nie. Feld markieren und mit den Knöpfen oder Alt+Hoch/Runter verschieben, mit + und - die "
                           "Breite ändern (⅛, ¼, ½, ¾ oder ganze Zeile) - die Tabelle folgt sofort. Titel und Tags stehen fest "
                           "oben; „Datum“ lässt sich im oberen Block verschieben, aber nicht darunter.",
                      einzug=8, pady=(0, 4))
        rahmen = ttk.Frame(tab)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 4))
        knoepfe = ttk.Frame(rahmen)
        knoepfe.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))
        ttk.Button(knoepfe, text="▲ Nach oben", command=lambda: self._felder_verschieben(-1)).pack(fill=tk.X)
        ttk.Button(knoepfe, text="▼ Nach unten", command=lambda: self._felder_verschieben(1)).pack(fill=tk.X, pady=(4, 0))
        ttk.Button(knoepfe, text="+ Breiter", command=lambda: self._felder_breite(1)).pack(fill=tk.X, pady=(12, 0))
        ttk.Button(knoepfe, text="− Schmaler", command=lambda: self._felder_breite(-1)).pack(fill=tk.X, pady=(4, 0))
        ttk.Button(knoepfe, text="Standard", command=self._felder_standard).pack(fill=tk.X, pady=(16, 0))
        scroll = ttk.Scrollbar(rahmen, orient="vertical")
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.liste_felder = tk.Listbox(rahmen, exportselection=False, activestyle="none",
                                       yscrollcommand=scroll.set)
        self.liste_felder.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.configure(command=self.liste_felder.yview)
        self.liste_felder.bind("<Alt-Up>", lambda e: self._felder_verschieben(-1) or "break")
        self.liste_felder.bind("<Alt-Down>", lambda e: self._felder_verschieben(1) or "break")
        for taste in ("<plus>", "<KP_Add>"):
            self.liste_felder.bind(taste, lambda e: self._felder_breite(1) or "break")
        for taste in ("<minus>", "<KP_Subtract>"):
            self.liste_felder.bind(taste, lambda e: self._felder_breite(-1) or "break")
        self._felder_fuellen(self._aktuelle_aufteilung())

    def _aktuelle_aufteilung(self):
        panel = getattr(self.app, "eigenschaften_panel", None)
        if panel is not None:
            return panel.aufteilung()
        return de.feldaufteilung(self.app.config.get(EINSTELLUNG_FELDER, None))

    def _felder_fuellen(self, aufteilung, markiere=None):
        """Listbox aus der Aufteilung neu füllen; Trenner grau, `markiere` (Feld-Schlüssel) wieder auswählen."""
        self._feld_liste = de.aufteilung_als_liste(aufteilung)
        self._feld_breiten = dict(de.feldaufteilung(aufteilung)["breiten"])
        self.liste_felder.delete(0, tk.END)
        for i, eintrag in enumerate(self._feld_liste):
            self.liste_felder.insert(tk.END, de.anzeigetext(eintrag, self._feld_breiten))
            if eintrag in de.TRENNER_TEXTE:
                self.liste_felder.itemconfig(i, foreground="gray50", selectforeground="gray50")
        if markiere in self._feld_liste:
            i = self._feld_liste.index(markiere)
            self.liste_felder.selection_set(i)
            # Auch den Tastatur-Cursor („active“) und den Anker mitnehmen: nach delete/insert stünde
            # er sonst wieder auf 0, und der nächste Pfeil-Druck spränge an den Listenanfang (Peter 15.09.2026)
            self.liste_felder.activate(i)
            self.liste_felder.selection_anchor(i)
            self.liste_felder.see(i)
            self.liste_felder.focus_set()

    def _felder_verschieben(self, richtung):
        auswahl = self.liste_felder.curselection()
        if not auswahl:
            return
        i = auswahl[0]
        j = i + richtung
        eintrag = self._feld_liste[i]
        if eintrag in de.TRENNER_TEXTE or j < 0 or j >= len(self._feld_liste):
            return
        liste = list(self._feld_liste)
        liste[i], liste[j] = liste[j], liste[i]
        self._felder_uebernehmen(de.liste_als_aufteilung(liste, self._feld_breiten), markiere=eintrag)

    def _felder_breite(self, richtung):
        """Breite des markierten Felds eine Stufe ändern (+1 breiter, -1 schmaler: ¼ ↔ ½ ↔ 1)."""
        auswahl = self.liste_felder.curselection()
        if not auswahl:
            return
        eintrag = self._feld_liste[auswahl[0]]
        if eintrag in de.TRENNER_TEXTE:
            return
        breiten = dict(self._feld_breiten)
        breiten[eintrag] = de.naechste_breite(breiten.get(eintrag, de.FELDER[eintrag][1]), richtung)
        self._felder_uebernehmen(de.liste_als_aufteilung(self._feld_liste, breiten), markiere=eintrag)

    def _felder_standard(self):
        self._felder_uebernehmen(de.STANDARD_AUFTEILUNG)

    def _felder_uebernehmen(self, aufteilung, markiere=None):
        """Neue Aufteilung ans Panel (ordnet sofort neu und speichert) bzw. nur in die Einstellungen."""
        panel = getattr(self.app, "eigenschaften_panel", None)
        if panel is not None:
            panel.setze_aufteilung(aufteilung)
            aufteilung = panel.aufteilung()
        else:
            aufteilung = de.feldaufteilung(aufteilung)
            self.app.config.set(EINSTELLUNG_FELDER, aufteilung)
        self._felder_fuellen(aufteilung, markiere=markiere)

    # ---------- Reiter: Suche & Volltext ----------
    def _reiter_suche(self, tab):
        self.var_use_index = tk.BooleanVar(value=bool(self.app.config.get("use_index", True)))
        self._schalter(tab, "Suchindex verwenden (empfohlen)",
                       self.var_use_index, lambda: self.app.config.set("use_index", self.var_use_index.get()), pady=(0, 0))
        self._hinweis(tab, "Kleine Datenbank im Daten-Ordner, die Titel, Tags und Text der Dokumente vorhält - "
                           "dadurch antwortet die Suche sofort statt jedes PDF neu zu öffnen. Ohne Index wird "
                           "live gelesen (langsam, aber immer aktuell).")

        # Qualitätsstufen des Volltext-Index (Phase 2): alle vier Stufen sind umgesetzt.
        # Der eigentliche Batch-Lauf hängt NICHT am Radiobutton-Klick (das würde bedeuten:
        # erneutes Klicken einer bereits gewählten Stufe zum Fortsetzen eines abgebrochenen
        # Laufs - unintuitiv, niemand klickt eine schon aktive Auswahl nochmal an), sondern
        # an einem eigenen "Altbestand nachziehen"-Button je Stufe (funktioniert für Erstlauf
        # UND Fortsetzen gleichermaßen).
        ttk.Label(tab, text="Textqualität für die Inhaltssuche ('Inhalt (OCR)' in der Suchleiste):").pack(anchor="w", padx=8, pady=(6, 0))
        self._hinweis(tab, "Jede Stufe ergänzt die vorherige - der ursprüngliche Text bleibt immer erhalten. "
                           "Neue Dokumente bekommen die gewählte Stufe automatisch; 'Altbestand nachziehen' "
                           "holt die schon vorhandenen Dokumente nach (lässt sich abbrechen und fortsetzen).",
                      einzug=8, pady=(0, 4))
        self.var_index_mode = tk.StringVar(value=self.app.config.get("index_text_mode", "standard"))
        mode_frame = ttk.Frame(tab)
        mode_frame.pack(fill=tk.X, padx=8, pady=(0, 4))
        modes = [
            ("standard", "Standard - Text so, wie er im PDF steht", None),
            ("erweitert", "Erweitert - plus Rechtschreibkorrektur aus dem Wortschatz der Sammlung (ohne KI)", self._run_erweitert_upgrade_now),
            ("fortgeschritten", "Fortgeschritten - plus erneutes Lesen der Seitenbilder (Tesseract-OCR)", self._run_ocr_upgrade_now),
            ("meister", "Meister - plus Prüfung des gelesenen Texts durch den KI-Server", self._run_meister_upgrade_now),
        ]
        for value, label, run_cmd in modes:
            mode_row = ttk.Frame(mode_frame)
            mode_row.pack(fill=tk.X, anchor="w", pady=1)
            if run_cmd:
                # Knopf VOR dem langen Beschriftungstext packen, sonst quetscht ihn der Text
                # auf „Altbestand na…" zusammen (bei 125 % Textgröße erst recht, FALLSTRICKE #69)
                ttk.Button(mode_row, text="Altbestand nachziehen", command=run_cmd).pack(side=tk.RIGHT, padx=(4, 0))
            ttk.Radiobutton(mode_row, text=label, value=value,
                            variable=self.var_index_mode, command=self._on_index_mode_changed).pack(side=tk.LEFT, padx=12)

    # ---------- Reiter: KI-Server ----------
    def _reiter_ki(self, tab):
        self._hinweis(tab, "Ein Ollama-Server im Heimnetz (oder per Tailscale aus der Ferne) mit einem Bild-Modell "
                           "wie qwen3.5:9b. Wird von allen KI-Funktionen benutzt: Titel vorschlagen, "
                           "Vollautomatik, Dubletten-Zweitprüfung und die Meister-Stufe der Suche.",
                      einzug=8, pady=(0, 8))
        row_url = ttk.Frame(tab)
        row_url.pack(fill=tk.X, padx=8, pady=(4, 2))
        ttk.Label(row_url, text="Server-Adresse:", width=16).pack(side=tk.LEFT)
        self.var_ollama_url = tk.StringVar(value=self.app.config.get("ollama_url", ollama_client.DEFAULT_URL))
        entry_url = ttk.Entry(row_url, textvariable=self.var_ollama_url)
        entry_url.pack(side=tk.LEFT, fill=tk.X, expand=True)
        def url_uebernehmen(_event=None):
            self.app.config.set("ollama_url", self.var_ollama_url.get().strip())
            # Verbindungsanzeige sofort gegen die neue Adresse prüfen (ki_status.py)
            status = getattr(self.app, "ki_status", None)
            if status is not None:
                status.pruefe_jetzt()

        entry_url.bind("<FocusOut>", url_uebernehmen)
        entry_url.bind("<Return>", url_uebernehmen)
        self._hinweis(tab, f"z.B. {ollama_client.DEFAULT_URL} oder http://ki-server:11434", einzug=8 + 16 * 7, pady=(0, 4))

        row_model = ttk.Frame(tab)
        row_model.pack(fill=tk.X, padx=8, pady=(2, 4))
        ttk.Label(row_model, text="Modell:", width=16).pack(side=tk.LEFT)
        self.var_ollama_model = tk.StringVar(value=self.app.config.get("ollama_model", ollama_client.DEFAULT_MODEL))
        entry_model = ttk.Entry(row_model, textvariable=self.var_ollama_model)
        entry_model.pack(side=tk.LEFT, fill=tk.X, expand=True)
        entry_model.bind("<FocusOut>", lambda e: self.app.config.set("ollama_model", self.var_ollama_model.get().strip()))
        entry_model.bind("<Return>", lambda e: self.app.config.set("ollama_model", self.var_ollama_model.get().strip()))

        # Zweitmeinung zur Ordnerwahl (Modell-Prüfstand 27.10.2026): ein Entscheidungsmodell
        # bewertet jeden vorhandenen Ordner - leer = aus (auto_pilot.wende_zweitmeinung_an).
        row_wahl = ttk.Frame(tab)
        row_wahl.pack(fill=tk.X, padx=8, pady=(2, 0))
        ttk.Label(row_wahl, text="Ordnerwahl:", width=16).pack(side=tk.LEFT)
        self.var_entscheidungsmodell = tk.StringVar(value=self.app.config.get("ki_entscheidungsmodell", ""))
        entry_wahl = ttk.Entry(row_wahl, textvariable=self.var_entscheidungsmodell)
        entry_wahl.pack(side=tk.LEFT, fill=tk.X, expand=True)
        for ereignis in ("<FocusOut>", "<Return>"):
            entry_wahl.bind(ereignis, lambda e: self.app.config.set("ki_entscheidungsmodell",
                                                                     self.var_entscheidungsmodell.get().strip()))
        self._hinweis(tab, "Optional, z.B. clef-flash:9b: ein Entscheidungsmodell prüft bei der Vollautomatik den "
                           "Zielordner nach. Widerspricht es deutlich, bleibt das Dokument zur Prüfung liegen; ist es "
                           "sich sehr sicher, darf es einen unklaren Fall entscheiden. Leer = aus. Kostet je Dokument "
                           "einige Sekunden (Modellwechsel auf dem Server).", einzug=8 + 16 * 7, pady=(0, 4), breite=540)

        # Wecken per Netzwerk (01.11.2026, ki_status.py / server_wecken.py): Doppelklick auf die rote
        # KI-Anzeige schickt ein Wake-on-LAN-Paket an diese MAC.
        row_mac = ttk.Frame(tab)
        row_mac.pack(fill=tk.X, padx=8, pady=(2, 0))
        ttk.Label(row_mac, text="Wecken (MAC):", width=16).pack(side=tk.LEFT)
        self.var_wol_mac = tk.StringVar(value=self.app.config.get("ki_wol_mac", ""))
        entry_mac = ttk.Entry(row_mac, textvariable=self.var_wol_mac, width=20)
        entry_mac.pack(side=tk.LEFT)
        # Rückmeldung in eigener Zeile unter dem Feld, umbrechend - neben dem Feld lief die VM-Warnung über den
        # Fensterrand hinaus (Peter 02.11.2026); ohne Text ausgeblendet, damit keine Leerzeile stehen bleibt
        lbl_mac = ttk.Label(tab, text="", foreground="gray40", justify="left", wraplength=UIUtils.px(self, 540))

        def mac_meldung(text, farbe="gray40"):
            lbl_mac.configure(text=text, foreground=farbe)
            if text:
                lbl_mac.pack(anchor="w", padx=(8 + 16 * 7, 8), pady=(2, 0), before=hinweis_mac)
            else:
                lbl_mac.pack_forget()

        def mac_pruefen(*_args, abschliessen=False):
            # Läuft bei JEDER Änderung (Tippen, Einfügen): Eine gültige MAC wird sofort gespeichert und die
            # VM-Warnung erscheint gleich beim Einfügen, nicht erst beim Verlassen des Feldes (Peter 02.11.2026).
            # Die Normalform kommt erst mit Enter/Verlassen ins Feld - sonst springt der Cursor beim Tippen.
            roh = self.var_wol_mac.get().strip()
            mac = server_wecken.mac_normalisieren(roh)
            if roh and not mac:
                if abschliessen:
                    mac_meldung("keine gültige MAC-Adresse - nicht gespeichert", "#c0392b")
                else:
                    mac_meldung("noch keine gültige MAC-Adresse")
                return
            if abschliessen and self.var_wol_mac.get() != (mac or ""):
                self.var_wol_mac.set(mac or "")          # löst mac_pruefen erneut aus, harmlos
            if self.app.config.get("ki_wol_mac", "") != (mac or ""):
                self.app.config.set("ki_wol_mac", mac or "")
            if mac and server_wecken.ist_virtuelle_mac(mac):
                mac_meldung("Achtung: Das ist die Karte einer virtuellen Maschine, die lässt sich nicht "
                            "wecken - die MAC des Server-PCs selbst nehmen.", "#c0392b")
            else:
                mac_meldung("gespeichert" if mac else "")

        self.var_wol_mac.trace_add("write", mac_pruefen)
        for ereignis in ("<FocusOut>", "<Return>"):
            entry_mac.bind(ereignis, lambda e: mac_pruefen(abschliessen=True))
        hinweis_mac = self._hinweis(tab, "Optional, z.B. AA:BB:CC:11:22:33: die MAC-Adresse der Netzwerkkarte des Server-PCs. "
                                  "Dann weckt ein Doppelklick auf die rote KI-Anzeige (Punkt rechts in der Suchleiste) den "
                                  "Server per Wake-on-LAN; bis er antwortet, leuchtet sie orange. Geht nur im selben "
                                  "Heimnetz (nicht über Tailscale), und der Server-PC muss Wake-on-LAN erlauben "
                                  "(BIOS/Netzwerkkarte). Die MAC steht z.B. in der FRITZ!Box unter Heimnetz → Netzwerk.",
                             einzug=8 + 16 * 7, pady=(0, 4), breite=540)

        # KI ohne Grafikkarte (Beta-Vorbereitung 13.09.2026): Ollama auf einem PC ohne
        # passende Grafikkarte rechnet auf dem Prozessor - langsam, aber nutzbar. Ohne
        # dieses Häkchen pausiert die Vollautomatik bei CPU-Betrieb (FALLSTRICKE #67),
        # weil das beim eigentlichen Server ein Treiber-Defekt ist.
        self.var_ki_cpu = tk.BooleanVar(value=bool(self.app.config.get("ki_cpu_erlauben", False)))

        def cpu_uebernehmen():
            self.app.config.set("ki_cpu_erlauben", self.var_ki_cpu.get())
            ollama_client.setze_langsamen_modus(self.var_ki_cpu.get())

        self._schalter(tab, "KI ohne Grafikkarte zulassen (Ollama rechnet auf dem Prozessor - langsam)",
                       self.var_ki_cpu, cpu_uebernehmen, pady=(10, 0))
        self._hinweis(tab, "Für Ollama auf diesem oder einem anderen PC ohne passende Grafikkarte. Antworten dauern "
                           f"dann Minuten statt Sekunden; die Wartezeit je Anfrage wird auf das {ollama_client.LANGSAM_FAKTOR}-fache "
                           "verlängert. Ohne dieses Häkchen pausiert die Vollautomatik, sobald das Modell nicht im "
                           "Grafikspeicher liegt, und die Ablage-Vorschau fragt nach - denn bei einem Server mit "
                           "Grafikkarte ist CPU-Betrieb ein Defekt. Siehe Hilfe → \"KI auf dem eigenen PC\".")

        ttk.Button(tab, text="Verbindung testen", command=self._test_ollama_connection).pack(anchor="e", padx=8, pady=(8, 6))

    # ---------- Reiter: Vollautomatik ----------
    def _reiter_automatik(self, tab):
        self.var_auto_pilot = tk.BooleanVar(value=bool(self.app.config.get("auto_pilot_enabled", False)))
        self._schalter(tab, "Hintergrund-Automatik: neue PDFs im Posteingang ohne Knopfdruck ablegen",
                       self.var_auto_pilot, self._apply_auto_pilot, pady=(0, 0))
        self._hinweis(tab, "Der Ordner-Wächter meldet neue PDFs im Posteingang; nach kurzer Ruhezeit werden sie "
                           "per KI analysiert und wie bei 'Posteingang verarbeiten' abgelegt - Unsicheres wandert "
                           "unverändert nach 0_Unsicher. Jede Ablage steht im Vollautomatik-Protokoll im Daten-Ordner "
                           "(Tools -> Vollautomatik -> Protokoll anzeigen). Solange ein Vorschaufenster der "
                           "Vollautomatik offen ist, pausiert der Dienst. Das Statusfenster mit dem drehenden Ring "
                           "zeigt, dass die Automatik läuft - es zu schließen schaltet sie aus.")

        self.var_umbenennen = tk.BooleanVar(value=bool(self.app.config.get("auto_pilot_umbenennen", True)))
        self._schalter(tab, "Dateien beim Ablegen umbenennen (JJJJMMTT_Titel.pdf)", self.var_umbenennen,
                       lambda: self.app.config.set("auto_pilot_umbenennen", bool(self.var_umbenennen.get())))
        self._hinweis(tab, "An = Scanner-Namen wie 'Scan_0001.pdf' werden aus Datum und Titel neu gebildet; der "
                           "bisherige Name wird beim ersten Umbenennen in die PDF-Metadaten eingebrannt (Details-Block: "
                           "'Originalname') und geht nie verloren. Aus = die Datei behält ihren Namen, "
                           "Titel, Datum und Zielordner kommen trotzdem - für Sammlungen mit gepflegten Dateinamen.")


    # ---------- Reiter: Experten ----------
    def _reiter_experten(self, tab):
        self._hinweis(tab, "Alle übrigen Einstellungen der settings.json als Roh-JSON (Fenstergeometrie, "
                           "Spaltenbreiten, zuletzt benutzte Tags ...). Nur bei Bedarf anfassen.",
                      einzug=8, pady=(0, 6))
        self.txt_expert = tk.Text(tab, height=10, font=("Consolas", 9))
        self.txt_expert.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 2))
        self._load_expert_json()

        exp_btns = ttk.Frame(tab)
        exp_btns.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Button(exp_btns, text="Neu laden", command=self._load_expert_json).pack(side=tk.LEFT)
        ttk.Button(exp_btns, text="Übernehmen", command=self._apply_expert_json).pack(side=tk.RIGHT)

    # ==========================================
    # LIVE-ÜBERNAHME DER KURATIERTEN EINSTELLUNGEN
    # ==========================================
    def _change_master_folder(self):
        """Nutzt den bestehenden Auswahl-Dialog des FolderManagers (inkl. Watchdog-/Log-Umzug)."""
        self.app.folder_manager.choose_master_folder()
        self.lbl_master.config(text=self.app.config.get("master_folder", "(nicht gesetzt)"))

    def _apply_autosave(self):
        self.app.autosave_var.set(self.var_autosave.get())
        self.app.save_manager.toggle_autosave()

    def _apply_bestaetigungen(self):
        self.app.config.set(bestaetigung.EINSTELLUNG, bool(self.var_bestaetigungen.get()))

    def _apply_details(self):
        """Detail-Eigenschaften im Hauptfenster ein-/ausklappen (gleiche Checkbox wie dort)."""
        panel = getattr(self.app, "eigenschaften_panel", None)
        if panel is not None:
            panel.var_sichtbar.set(bool(self.var_details.get()))
            panel._umschalten()
        else:
            self.app.config.set(EINSTELLUNG_DETAILS, bool(self.var_details.get()))

    def _apply_visible_columns(self):
        chosen = [c for c in self.app.tree_files["columns"] if self.column_vars[c].get()]
        if not chosen:  # Mindestens eine Spalte muss sichtbar bleiben
            chosen = ["titel"]
            self.column_vars["titel"].set(True)
        vorher = list(self.app.tree_files["displaycolumns"])
        self.app.tree_files["displaycolumns"] = chosen
        self.app.config.set("visible_columns", chosen)
        # Häkchen im Kopfzeilen-Rechtsklick-Menü synchron halten
        if hasattr(self.app, 'column_vars'):
            for col, var in self.app.column_vars.items():
                var.set(col in chosen)
        # Textqualität wird nur bei sichtbarer Spalte gelesen - beim Einblenden Liste neu füllen
        if "qualitaet" in chosen and "qualitaet" not in vorher and hasattr(self.app, "folder_manager"):
            self.app.folder_manager.on_folder_select(None)

    def _apply_min_widths(self):
        try:
            widths = {col: int(var.get()) for col, var in self.min_width_vars.items()}
        except (ValueError, tk.TclError):
            return  # Unfertige Eingabe (z.B. leeres Feld) still ignorieren
        self.app.config.set("column_min_widths", widths)
        for col, w in widths.items():
            self.app.tree_files.column(col, minwidth=w)
            if int(self.app.tree_files.column(col, "width")) < w:
                self.app.tree_files.column(col, width=w)

    def _apply_zoom(self):
        if self.var_zoom_mode.get() == "auto":
            zoom = None
        else:
            try:
                pct = max(10, min(500, int(self.var_zoom_pct.get())))
            except (ValueError, tk.TclError):
                return
            self.var_zoom_pct.set(pct)
            zoom = pct / 100.0
        self.app.custom_zoom = zoom
        self.app.config.set("custom_zoom", zoom)
        if hasattr(self.app, 'preview_manager'):
            self.app.preview_manager.update_preview()

    # ==========================================
    # VOLLTEXT-INDEX-STUFEN (Phase 2)
    # ==========================================
    def _on_index_mode_changed(self):
        """
        Radiobutton-Handler: setzt NUR die Einstellung. Der Batch-Lauf selbst hängt an den
        "Jetzt ausführen"-Buttons (_run_erweitert_upgrade_now/_run_ocr_upgrade_now/
        _run_meister_upgrade_now) - ein Klick auf eine bereits gewählte Stufe (Tk feuert
        command auch dabei) darf keinen Lauf lostreten, siehe Kommentar bei der Erstellung
        der Radiobuttons.
        """
        mode = self.var_index_mode.get()
        self.app.config.set("index_text_mode", mode)

    def _revert_index_mode(self, to="standard"):
        """Setzt die Stufen-Auswahl zurück (z.B. wenn eine Voraussetzung fehlt oder der Nutzer abbricht)."""
        self.var_index_mode.set(to)
        self.app.config.set("index_text_mode", to)

    def _run_erweitert_upgrade_now(self):
        """Handler für den 'Jetzt ausführen'-Button bei 'Erweitert' - wählt die Stufe (falls noch nicht aktiv) und startet/setzt den Batch-Lauf fort."""
        self.var_index_mode.set("erweitert")
        self.app.config.set("index_text_mode", "erweitert")
        self._start_erweitert_upgrade()

    def _run_ocr_upgrade_now(self):
        """Handler für den 'Jetzt ausführen'-Button bei 'Fortgeschritten' - wählt die Stufe (falls noch nicht aktiv) und startet/setzt den Batch-Lauf fort."""
        self.var_index_mode.set("fortgeschritten")
        self.app.config.set("index_text_mode", "fortgeschritten")
        self._start_ocr_upgrade()

    def _run_meister_upgrade_now(self):
        """Handler für den 'Jetzt ausführen'-Button bei 'Meister' - wählt die Stufe (falls noch nicht aktiv) und startet/setzt den Batch-Lauf fort."""
        self.var_index_mode.set("meister")
        self.app.config.set("index_text_mode", "meister")
        self._start_meister_upgrade()

    def _start_erweitert_upgrade(self):
        """
        Rein lokale, KI-freie Korrektur (spell_correct.py) - anders als 'Fortgeschritten'/
        'Meister' KEIN Ollama-Server und KEIN tessdata nötig, dadurch deutlich schneller.
        Schwächste Stufe (siehe FALLSTRICKE #21: Raterei bei stark beschädigtem Text ohne
        Bild-Neulesen). Läuft seit 12.07.2026 automatisch beim Scannen mit, sobald
        'Erweitert' (oder höher) gewählt ist (siehe index_manager._ensure_fulltext_baseline)
        - dieser Button ist daher nur noch ein einmaliger Nachzieh-Lauf für Dokumente, die
        schon VOR der Auswahl im Cache standen.
        """
        if not getattr(self.app, "index_manager", None):
            self._revert_index_mode()
            return

        if not bestaetigung.frage(
                "Erweitert-Stufe: Altbestand nachziehen",
                "Neue oder geänderte Dokumente bekommen die lokale Rechtschreibkorrektur "
                "ab jetzt automatisch beim Scannen - dieser Lauf zieht nur den bestehenden "
                "Altbestand nach (Dokumente, die schon vor der Auswahl im Cache standen). "
                "Korrigiert wird auf Basis des Wortschatzes der eigenen Sammlung, OHNE die "
                "Seitenbilder neu zu lesen (der Original-Text bleibt zusätzlich erhalten). "
                "Bei stark beschädigtem Original-Text bleibt das Ergebnis Raterei; für "
                "sichere Treffer eignet sich eher 'Fortgeschritten'. Jetzt starten?",
                parent=self):
            self._revert_index_mode()
            return

        dialog = ProgressDialog(self, "Volltext-Index: Erweitert", "Wird vorbereitet...")
        index_manager = self.app.index_manager

        def worker():
            try:
                done = index_manager.upgrade_to_erweitert_tier(
                    on_progress=lambda d, t: self.after(0, dialog.update_progress, d, t),
                    should_stop=dialog.should_stop,
                )
                self.after(0, self._on_erweitert_upgrade_done, dialog, done)
            except Exception as e:
                self.after(0, self._on_erweitert_upgrade_failed, dialog, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_erweitert_upgrade_done(self, dialog, done):
        dialog.destroy()
        messagebox.showinfo("Fertig", f"{done} Dokument(e) aus dem Altbestand auf 'Erweitert' hochgestuft.", parent=self)

    def _on_erweitert_upgrade_failed(self, dialog, msg):
        dialog.destroy()
        messagebox.showerror("Fehler", f"Erweitert-Stufe fehlgeschlagen:\n{msg}", parent=self)
        self._revert_index_mode()

    def _start_ocr_upgrade(self):
        tessdata_path = app_paths.tessdata_dir()
        if not os.path.isdir(tessdata_path):
            messagebox.showwarning(
                "Tesseract-Sprachdaten fehlen",
                "Für die Stufe 'Fortgeschritten' werden die Tesseract-Sprachdaten benötigt "
                "(siehe README: tessdata/deu.traineddata).",
                parent=self)
            self._revert_index_mode()
            return

        if not getattr(self.app, "index_manager", None):
            self._revert_index_mode()
            return

        if not bestaetigung.frage(
                "Fortgeschritten-Stufe aufbauen",
                "Alle Dokumente werden per Bild-OCR neu gelesen und der Volltext-Cache ergänzt "
                "(die ursprüngliche Textebene bleibt zusätzlich erhalten). Das kann je nach "
                "Sammlungsgröße mehrere Minuten dauern. Jetzt starten?",
                parent=self):
            self._revert_index_mode()
            return

        dialog = ProgressDialog(self, "Volltext-Index: Fortgeschritten", "Wird vorbereitet...")
        index_manager = self.app.index_manager

        def worker():
            try:
                done = index_manager.upgrade_to_ocr_tier(
                    tessdata_path,
                    on_progress=lambda d, t: self.after(0, dialog.update_progress, d, t),
                    should_stop=dialog.should_stop,
                )
                self.after(0, self._on_ocr_upgrade_done, dialog, done)
            except Exception as e:
                self.after(0, self._on_ocr_upgrade_failed, dialog, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_ocr_upgrade_done(self, dialog, done):
        dialog.destroy()
        messagebox.showinfo("Fertig", f"{done} Dokument(e) auf 'Fortgeschritten' hochgestuft.", parent=self)

    def _on_ocr_upgrade_failed(self, dialog, msg):
        dialog.destroy()
        messagebox.showerror("Fehler", f"Fortgeschritten-Stufe fehlgeschlagen:\n{msg}", parent=self)
        self._revert_index_mode()

    def _start_meister_upgrade(self):
        """Wie _start_ocr_upgrade, aber KI-Prüfung des Re-OCR-Texts per Ollama - braucht daher zusätzlich einen erreichbaren Server statt lokaler Tesseract-Sprachdaten."""
        if not getattr(self.app, "index_manager", None):
            self._revert_index_mode()
            return

        url = self.var_ollama_url.get().strip() or ollama_client.DEFAULT_URL
        if not ollama_client.is_reachable(url):
            messagebox.showwarning(
                "Ollama nicht erreichbar",
                f"Für die Stufe 'Meister' wird ein erreichbarer Ollama-Server benötigt "
                f"(aktuell: {url}). Server-Adresse im Reiter 'KI-Server' prüfen.",
                parent=self)
            self._revert_index_mode()
            return

        if not bestaetigung.frage(
                "Meister-Stufe aufbauen",
                "Der Re-OCR-Text aller bereits auf 'Fortgeschritten' hochgestuften Dokumente "
                "wird per KI geprüft/bereinigt und der Volltext-Cache ergänzt (Original und "
                "Re-OCR bleiben zusätzlich erhalten). Dokumente ohne Re-OCR werden übersprungen "
                "(zuerst 'Fortgeschritten' ausführen). Das kann je nach Sammlungsgröße mehrere "
                "Minuten dauern. Jetzt starten?",
                parent=self):
            self._revert_index_mode()
            return

        dialog = ProgressDialog(self, "Volltext-Index: Meister", "Wird vorbereitet...")
        index_manager = self.app.index_manager
        model = self.var_ollama_model.get().strip() or ollama_client.DEFAULT_MODEL

        def worker():
            try:
                done, skipped = index_manager.upgrade_to_meister_tier(
                    url, model,
                    on_progress=lambda d, t: self.after(0, dialog.update_progress, d, t),
                    should_stop=dialog.should_stop,
                )
                self.after(0, self._on_meister_upgrade_done, dialog, done, skipped)
            except Exception as e:
                self.after(0, self._on_meister_upgrade_failed, dialog, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_meister_upgrade_done(self, dialog, done, skipped):
        dialog.destroy()
        msg = f"{done} Dokument(e) auf 'Meister' hochgestuft."
        if skipped:
            msg += f"\n{skipped} Dokument(e) übersprungen (noch nicht auf 'Fortgeschritten')."
        messagebox.showinfo("Fertig", msg, parent=self)

    def _on_meister_upgrade_failed(self, dialog, msg):
        dialog.destroy()
        messagebox.showerror("Fehler", f"Meister-Stufe fehlgeschlagen:\n{msg}", parent=self)
        self._revert_index_mode()

    def _apply_auto_pilot(self):
        self.app.config.set("auto_pilot_enabled", bool(self.var_auto_pilot.get()))
        dienst = getattr(self.app, "auto_pilot_service", None)
        if dienst is not None:
            # Auch beim AUSschalten anstoßen: das gleicht sofort das Statusfenster ab
            dienst.anstossen()

    def _test_ollama_connection(self):
        """
        Erreichbarkeit, Modellliste und - neu seit 12.09.2026 - ob das eingestellte Modell auf
        der Grafikkarte läuft (ollama_client.gpu_status). Ein still auf der CPU rechnender
        Server sah bisher in diesem Test gesund aus und fiel erst als Timeout in Musterstadt auf.
        Der GPU-Check kann das Modell erst laden (Sekunden) und läuft deshalb im Thread.
        """
        url = self.var_ollama_url.get().strip()
        model = self.var_ollama_model.get().strip() or ollama_client.DEFAULT_MODEL
        erreichbar = ollama_client.is_reachable(url)
        status = getattr(self.app, "ki_status", None)
        if status is not None and url == status.url():
            status.setze(erreichbar)   # LED und Menüsperre sofort nachziehen
        if not erreichbar:
            messagebox.showwarning("Ollama", f"Server unter {url} nicht erreichbar.", parent=self)
            return
        try:
            models = ollama_client.list_models(url)
        except Exception:
            models = []
        text = "Verbindung erfolgreich."
        text += f"\nVerfügbare Modelle: {', '.join(models)}" if models else "\nKeine Modelle gefunden (ollama pull <modell> auf dem Server ausführen?)."
        if not any(ollama_client._passt_modellname(m, model) for m in models):
            text += f"\n\nDas eingestellte Modell „{model}“ ist auf dem Server nicht vorhanden."
            messagebox.showwarning("Ollama", text, parent=self)
            return

        def pruefen():
            with aktivitaet.phase(f"KI-Server: prüfe, ob {model} auf der Grafikkarte läuft…"):
                status, details = ollama_client.gpu_status(url, model)
            self.after(0, lambda: self._zeige_gpu_status(text, model, status, details))

        threading.Thread(target=pruefen, daemon=True).start()

    def _zeige_gpu_status(self, text, model, status, details):
        if not self.winfo_exists():
            return
        if status == "gpu":
            messagebox.showinfo("Ollama", f"{text}\n\nModell {model} läuft auf der Grafikkarte ({details}).", parent=self)
        elif status in ("cpu", "teilweise") and bool(self.app.config.get("ki_cpu_erlauben", False)):
            messagebox.showinfo("Ollama - KI rechnet auf dem Prozessor",
                                f"{text}\n\nModell {model} läuft {'nur teilweise' if status == 'teilweise' else 'nicht'} "
                                f"auf der Grafikkarte ({details}) - laut Einstellung zugelassen.\n"
                                "Antworten dauern Minuten statt Sekunden; Vollautomatik und Werkzeuge warten "
                                "entsprechend länger.", parent=self)
        elif status in ("cpu", "teilweise"):
            messagebox.showwarning("Ollama - KI rechnet auf der CPU",
                                   f"{text}\n\nACHTUNG: Modell {model} läuft {'nur teilweise' if status == 'teilweise' else 'NICHT'} "
                                   f"auf der Grafikkarte ({details}).\nKI-Aufrufe mit Seitenbild dauern dann Minuten und laufen "
                                   "in den Timeout - Vollautomatik und Titel-Vorschlag scheitern still.\n\n"
                                   "Auf dem Server prüfen: nvidia-smi. Meldet es „Driver/library version mismatch“, "
                                   "den Server (die VM) neu starten. Siehe Wiki „KI-Infrastruktur“.", parent=self)
        else:
            messagebox.showinfo("Ollama", f"{text}\n\nGrafikkarten-Prüfung nicht möglich: {details}", parent=self)

    # ==========================================
    # EXPERTEN-BEREICH
    # ==========================================
    def _load_expert_json(self):
        """Zeigt alle nicht kuratierten Keys der settings.json als editierbares JSON."""
        expert = {k: v for k, v in self.app.config.data.items() if k not in self.CURATED_KEYS}
        self.txt_expert.delete("1.0", tk.END)
        self.txt_expert.insert("1.0", json.dumps(expert, indent=4, ensure_ascii=False))

    def _apply_expert_json(self):
        """Validiert das Experten-JSON und übernimmt die Werte (mit Live-Hooks, wo sinnvoll)."""
        try:
            data = json.loads(self.txt_expert.get("1.0", tk.END))
            if not isinstance(data, dict):
                raise ValueError("Es wird ein JSON-Objekt ({...}) erwartet.")
        except Exception as e:
            messagebox.showerror("Ungültiges JSON", f"Die Eingabe konnte nicht übernommen werden:\n{e}", parent=self)
            return

        for key, value in data.items():
            self.app.config.set(key, value)

        # Live-Hooks für Werte, die sich sofort auswirken können
        if "window_geometry" in data:
            try:
                self.app.root.geometry(data["window_geometry"])
            except tk.TclError:
                pass
        if "sash_positions" in data:
            self.app.apply_saved_layout()

        messagebox.showinfo("Übernommen", "Die Experten-Einstellungen wurden gespeichert.", parent=self)
