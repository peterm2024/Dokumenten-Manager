import os
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox

import app_paths
import bestaetigung
from pdf_handler import PDFHandler
from config import Config
from folder_monitor import FolderMonitor
from app_logger import AppLogger

from file_operations import FileOperations
from tag_manager import TagManager
from preview_manager import PreviewManager, DATUM_VORSCHLAG_FARBE
from tag_editor import TagEditor
from search_manager import SearchManager
from folder_manager import FolderManager
from save_manager import SaveManager, tags_bereinigen
from index_manager import IndexManager
from layout_builder import (LayoutBuilder, STANDARD_SPALTEN, STANDARD_BREITEN, GESPEICHERTE_SPALTEN,
                            breiten_fuer_bildschirm, breiten_zum_speichern)
import menue_hilfe
import menue_tooltip
from kurzbefehle import Kurzbefehle
from tool_manager import ToolManager
from auto_pilot_service import AutoPilotService
from ki_status import KiStatus
import fehlerfaenger
import sicher_speichern
from fehlerfaenger import Fehlerfaenger, ausgabe_absichern
import versionspruefung
import ollama_client
from help_window import open_help, fenstertitel
from ui_utils import UIUtils


# --- Trennlinien (Sash) des Haupt-PanedWindows ---------------------------------------
# ttk.PanedWindow kürzt sashpos() immer auf die AKTUELL vorhandene Breite. Wird die
# gespeicherte Position gesetzt, bevor Tk das Fenster vermessen hat (winfo_width() == 1),
# werden aus z.B. 260/700 die Werte 0/5 — die beiden linken Spalten sind dann dauerhaft
# zugeklappt und beim Beenden wird dieser Unsinn auch noch gespeichert, wodurch die App
# ab dann bei jedem Start kaputt hochkommt (FALLSTRICKE #41).
MIN_SASH = 60        # schmaler als das ist keine sinnvolle Spalte
SASH_RESERVE = 120   # so viel Platz muss rechts der zweiten Trennlinie bleiben


def sashes_gueltig(sashes):
    """Prüft, ob gespeicherte Trennlinien-Positionen überhaupt eine sinnvolle Aufteilung ergeben."""
    if not isinstance(sashes, (list, tuple)) or len(sashes) != 2:
        return False
    try:
        erste, zweite = int(sashes[0]), int(sashes[1])
    except (TypeError, ValueError):
        return False
    return erste >= MIN_SASH and zweite >= erste + MIN_SASH


def sashes_passen(sashes, breite):
    """Prüft zusätzlich, ob das Fenster breit genug ist, um die Positionen ungekürzt zu setzen."""
    return sashes_gueltig(sashes) and breite >= int(sashes[1]) + SASH_RESERVE


def standard_sashes(breite, mitte=440):
    """Liefert eine vernünftige Standardaufteilung für eine gegebene Fensterbreite.
    :param mitte: Platzbedarf der mittleren Spalte (die Suchleiste); höchstens so viel, dass der Vorschau 30 % bleiben"""
    erste = max(MIN_SASH, min(280, breite // 4))
    zweite = max(erste + MIN_SASH, min(erste + max(440, mitte), breite - max(SASH_RESERVE, breite * 3 // 10)))
    return [erste, zweite]


def vorschau_zu_schmal(breite, zweite):
    """Bleiben der Vorschau rechts der zweiten Trennlinie weniger als 10 % der Fensterbreite? Bei großer Schrift ergab
    sich beim Erststart sonst eine fast unsichtbare Vorschau (FALLSTRICKE #109)."""
    return breite > 200 and breite - zweite < breite // 10


class DokumentenVerwaltung:

    def __init__(self, root):
        """
        Haupt-Initialisierung der GUI. Lädt Einstellungen, baut UI auf und startet Hintergrunddienste.
        :param root: Das Haupt-Tkinter-Fenster (tk.Tk).
        """
        self.root = root
        # Basis-Titel merken: preview_manager hängt Dateiname/Seite/Zoom an (statt einer
        # eigenen Kopfzeile über der Vorschau - spart Höhe bei großer Schrift, 31.08.2026)
        self.base_title = fenstertitel()
        self.root.title(self.base_title)
        # Fenstersymbol (icon/app.ico, erzeugt von icon/icon_erzeugen.py; in der EXE per
        # --add-data eingebettet). Fehlt die Datei, bleibt das Tk-Standardsymbol.
        try:
            self.root.iconbitmap(app_paths.bundled_default_path(os.path.join("icon", "app.ico")))
        except Exception:
            pass
        
        # Konfiguration laden
        self.config = Config()
        bestaetigung.konfigurieren(self.config)  # Routine-Rückfragen abschaltbar (Einstellungen -> Allgemein)
        
        # Fenstergröße und Position wiederherstellen - aber nur, wenn die gespeicherte
        # Position noch auf einem angeschlossenen Monitor liegt (Nutzerfund 06.09.2026:
        # App startete bei '+-4028+-921' unsichtbar im Nirgendwo, Titelleiste unerreichbar).
        saved_geom = UIUtils.sichere_fenstergeometrie(self.config.get("window_geometry", "1400x900"))
        self.root.geometry(saved_geom)
        # Gespeichert wird immer die NORMALGRÖSSE (Nutzerwunsch 06.09.2026: maximiert
        # beendet -> vorher stand die Maximiert-Geometrie in der settings.json und der
        # Neustart öffnete ein bildschirmfüllendes, aber nicht maximiertes Fenster).
        # Tk verrät die Normalgröße im zoomed-Zustand nicht mehr - deshalb wird sie
        # bei jeder Änderung im Normalzustand mitgeführt (billige Zuweisung, kein
        # Rendern - die Debounce-Regel für <Configure> zielt auf teures Neuzeichnen).
        self._normale_geometrie = saved_geom
        self.root.bind("<Configure>", self._merke_normale_geometrie, add="+")
        if self.config.get("window_maximized", False):
            self.root.state("zoomed")
        
        # --- Schutz vor gigantischen Zoom-Werten (RAM-Overflow) ---
        raw_zoom = self.config.get("custom_zoom", None)
        if raw_zoom is not None:
            try:
                z_val = float(raw_zoom)
                if z_val > 5.0:  # Alles über 500% wird als Fehler gewertet
                    self.custom_zoom = None
                    self.config.set("custom_zoom", None)
                else:
                    self.custom_zoom = z_val
            except Exception:
                self.custom_zoom = None
        else:
            self.custom_zoom = None
            
        self.last_zoom_pct = 100
        
        # Variablen und Flags
        self.autosave_var = tk.BooleanVar(value=self.config.get("autosave", False))
        self.show_trash_var = tk.BooleanVar(value=self.config.get("show_trash", False))
        self.mails_ausblenden_var = tk.BooleanVar(value=self.config.get("mails_ausblenden", False))
        self.master_folder = self.config.get("master_folder")
        self.photo_preview = None
        self.is_moving = False
        self.is_saving = False

        # Altbestände in den KID-Daten-Ordner umziehen — VOR dem Logger,
        # damit die alte Logdatei noch nicht geöffnet und mit-migriert ist
        migration_actions = app_paths.migrate_legacy_layout(self.master_folder)

        # Logger initialisieren
        self.logger = AppLogger()
        self.update_log_location()
        self.logger.info("Anwendung gestartet.")
        # Zentraler Fehlerfänger (fehlerfaenger.py): unbehandelte Ausnahmen aus
        # Tk-Callbacks, Threads und dem Hauptprogramm landen im Protokoll und in
        # EINEM Dialog statt unsichtbar auf stderr (die EXE hat keine Konsole).
        self.fehlerfaenger = Fehlerfaenger(self.root, self.logger, self.open_log_file).installieren()
        # Umgeleitete Ausgabe (cp1252) darf an Dateinamen wie „□vmc.pdf“ nicht scheitern (FALLSTRICKE #78)
        ausgabe_absichern()
        # KI ohne Grafikkarte zugelassen (Einstellung ki_cpu_erlauben): der Ollama-Client
        # wartet dann pro Anfrage entsprechend länger (ollama_client.setze_langsamen_modus).
        ollama_client.setze_langsamen_modus(bool(self.config.get("ki_cpu_erlauben", False)))
        for action in migration_actions:
            self.logger.info(f"KID-Daten-Ordner: {action}")
        if fehlerfaenger.vorheriger_absturz:
            self.logger.error("Der letzte Lauf endete mit einem Absturz:\n" + fehlerfaenger.vorheriger_absturz)
        
        # Controller initialisieren
        self.file_ops = FileOperations(self)
        self.tag_manager = TagManager(self)
        self.preview_manager = PreviewManager(self)
        self.tag_editor = TagEditor(self)
        self.search_manager = SearchManager(self)
        self.folder_manager = FolderManager(self)
        self.save_manager = SaveManager(self)
        self.index_manager = IndexManager(self)

        # Hintergrund-Dienste (nach folder_manager, da dessen on_filesystem_event als Callback dient)
        self.monitor = FolderMonitor(self.folder_manager.on_filesystem_event)
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # UI-Style setzen
        style = ttk.Style()
        if "clam" in style.theme_names():
            style.theme_use("clam")

        # --- FIX: Tk-8.6.9-Bug, der Treeview-Tag-Schriftfarben (foreground) ignoriert ---
        # Seit Tk 8.6.9 überschreibt die Theme-eigene Zustands-Map von "Treeview" die
        # per tag_configure() gesetzte Schriftfarbe einzelner Zeilen (Hintergrundfarben
        # sind davon nicht betroffen). Ohne diesen Fix bleiben z.B. "untouched" (orange)
        # und "search_local" (steelblue) unsichtbar, obwohl tag_configure korrekt gesetzt ist.
        def _fixed_style_map(option):
            return [elm for elm in style.map("Treeview", query_opt=option) if elm[:2] != ("!disabled", "!selected")]
        style.map("Treeview", foreground=_fixed_style_map("foreground"), background=_fixed_style_map("background"))
        # Zeilenhöhe aller Tabellen/Bäume an die Schrift koppeln: Tk nimmt fest 20 px, bei
        # 125 % Windows-Textgröße (Tester-PC) sind die Buchstaben aber ~24 px hoch - die
        # Unterlängen wurden abgeschnitten („Fahrzeua & Verkehr"), FALLSTRICKE #69.
        # 20 px entsprechen bei 100 % (Zeilenabstand 15 px) dem Faktor 4/3.
        zeilenabstand = tkfont.nametofont("TkDefaultFont").metrics("linespace")
        style.configure("Treeview", rowheight=max(20, int(round(zeilenabstand * 4 / 3))))

        # Kurzbefehl-Fenster (F1, Ansicht-Menü) - VOR dem Layout, das Menü-Häkchen braucht seine Variable
        self.kurzbefehle = Kurzbefehle(self)

        # UI über den ausgelagerten LayoutBuilder aufbauen
        LayoutBuilder(self.root, self).build()
        
        # Layout-Wiederherstellung verzögert ausführen
        self.root.after(200, self.apply_saved_layout)
        
        # Überwachung starten
        if self.master_folder and os.path.isdir(self.master_folder):
            self.folder_manager.refresh_folder_tree()  
            self.monitor.start_watching(self.master_folder) 

        # --- TOOL MANAGER INITIALISIERUNG ---
        self.tool_manager = ToolManager(self)
        
        # 1. In die BEREITS EXISTIERENDE Haupt-Menüleiste einklinken
        # Wir fragen das Fenster nach seinem aktuellen Menü, anstatt ein neues zu erzwingen!
        menubar_name = self.root.cget("menu")
        if menubar_name:
            existing_menubar = self.root.nametowidget(menubar_name)
            self.tool_manager.populate_main_menu(existing_menubar)
        
        # 2. Direkt in das Rechtsklick-Menü der Dateiliste einklinken
        if hasattr(self, 'file_context_menu'):
            self.tool_manager.populate_context_menu(self.file_context_menu)

        # Menü-Hilfe Stufe 3: Erklärung beim Verweilen auf einem Menüeintrag (menue_tooltip.py).
        # Erst NACH den Tools, damit deren Einträge und Untermenüs bekannt sind.
        self.menue_tooltip = menue_tooltip.MenueTooltip(
            self.root,
            lambda: menue_hilfe.alle_eintraege(self.tool_manager.tools),
            zusatz_menues={"Rechtsklick Ordner": self.folder_context_menu,
                           "Rechtsklick Dokument": self.file_context_menu},
            aktiv_fn=lambda: bool(self.config.get("menue_erklaerungen", True)))

        # Vollautomatik-Dienst (Seniorenmodus Schritt 4): läuft als Hintergrund-Thread,
        # tut aber nur etwas, wenn "auto_pilot_enabled" in den Einstellungen gesetzt ist.
        self.auto_pilot_service = AutoPilotService(self)
        self.auto_pilot_service.start()

        # Verbindungsanzeige KI-Server (ki_status.py, 13.09.2026): Hintergrund-Prüfung,
        # LED in der Suchleiste, Menüeinträge der KI-Werkzeuge gesperrt, solange der
        # Server nicht antwortet. NACH dem ToolManager, damit die Einträge bekannt sind.
        self.ki_status = KiStatus(self)
        self.ki_status.abonniere(self.tool_manager.setze_ki_verfuegbar)
        if hasattr(self, "ki_led"):
            self.ki_led.verbinde(self.ki_status)   # inkl. Doppelklick = Server wecken
        self.ki_status.start()

        # Start-Dialoge in EINEM after-Callback nacheinander: Ersteinrichtung
        # (Seniorenmodus Schritt 5, ohne gültigen Hauptordner) zuerst, DANACH die
        # Schnellstart-Hilfe. Bewusst nicht zwei getrennte Timer (300/400 ms) -
        # Tk-Timer feuern auch, während ein modaler Dialog offen ist, und das
        # Hilfe-Fenster legte sich mitten über die Ersteinrichtungs-Frage
        # (Nutzerfund 04.09.2026, FALLSTRICKE #51). Leicht verzögert, damit das
        # Hauptfenster fertig aufgebaut ist und das Zentrieren funktioniert.
        def _start_dialoge():
            self.melde_beschaedigte()
            if not (self.master_folder and os.path.isdir(self.master_folder)):
                self.folder_manager.ersteinrichtung_anbieten()  # modal, blockiert hier
            if self.config.get("show_help_on_start", True):
                open_help(self, 0, modal=True)
        self.root.after(300, _start_dialoge)
        # Stille Versionsprüfung (versionspruefung.py): meldet sich nur, wenn auf GitHub ein
        # neueres Release liegt; abschaltbar unter Einstellungen → Allgemein.
        if self.config.get(versionspruefung.EINSTELLUNG, True):
            self.root.after(5000, lambda: versionspruefung.pruefe(self, still=True))

    def melde_beschaedigte(self):
        """Zeigt, welche beschädigten Dateien beiseitegelegt wurden (sicher_speichern.py). Nichts davon wurde überschrieben."""
        namen = sicher_speichern.nimm_beiseite_gelegte()
        if not namen:
            return
        for name in namen:
            self.logger.warning(f"Beschädigte Datei beiseitegelegt: {name}")
        messagebox.showwarning(
            "Beschädigte Dateien",
            "Diese Dateien waren beschädigt und wurden nicht überschrieben, sondern beiseitegelegt:\n\n"
            + "\n".join(namen)
            + "\n\nKID arbeitet ohne sie weiter. Fehlt danach die Sammlung, lässt sie sich unter Datei → Sammlung öffnen… neu wählen. "
              "Der Tag-Katalog wird, wenn möglich, aus seiner Sicherung wiederhergestellt.")

    def update_log_location(self):
        """Setzt den Speicherort der Logdatei in den KID-Daten-Ordner der aktuellen Sammlung."""
        self.logger.set_log_file(app_paths.log_path(self.master_folder))

    def _merke_normale_geometrie(self, event=None):
        """Führt die letzte NICHT-maximierte Fenstergeometrie mit (siehe Kommentar im Konstruktor)."""
        try:
            if self.root.state() == "normal":
                self._normale_geometrie = self.root.geometry()
        except tk.TclError:
            pass

    def on_closing(self):
        """Speichert das aktuelle Layout ab und beendet die App sicher."""
        try:
            maximiert = False
            try:
                maximiert = self.root.state() == "zoomed"
            except tk.TclError:
                pass
            self.config.set("window_maximized", maximiert)
            self.config.set("window_geometry",
                            self._normale_geometrie if maximiert else self.root.geometry())
            widths = {col: self.tree_files.column(col, "width") for col in GESPEICHERTE_SPALTEN}
            self.config.set("column_widths", breiten_zum_speichern(widths, UIUtils.skalierung(self.root)))
            # Zugeklappte/unplausible Trennlinien NIE speichern — sonst startet die App
            # beim nächsten Mal wieder mit unsichtbaren Spalten (FALLSTRICKE #41).
            aktuelle_sashes = [self.main_pane.sashpos(0), self.main_pane.sashpos(1)]
            if sashes_gueltig(aktuelle_sashes):
                self.config.set("sash_positions", aktuelle_sashes)
            else:
                self.logger.warning(
                    f"Trennlinien {aktuelle_sashes} nicht plausibel — die bisherige Aufteilung bleibt erhalten.")
            self.config.set("custom_zoom", getattr(self, 'custom_zoom', None))
        except Exception as e:
            self.logger.error(f"Fehler beim Speichern des Layouts: {e}")

        self.logger.info("Anwendung wird beendet.\n" + "-"*40)
        if hasattr(self, 'auto_pilot_service'):
            self.auto_pilot_service.stop()
        if hasattr(self, 'ki_status'):
            self.ki_status.stop()
        self.monitor.stop_watching()
        self.index_manager.close()
        self.root.quit()

    def apply_saved_layout(self, versuche=0):
        """Stellt die Positionen der UI-Trennlinien wieder her — aber erst, wenn das Fenster steht.

        Solange Tk das PanedWindow noch nicht vermessen hat, würde ttk die Werte auf die
        noch fehlende Breite kürzen und die linken Spalten blieben zugeklappt; deshalb wird
        in diesem Fall erneut nachgesehen (FALLSTRICKE #41). Passt die gespeicherte Aufteilung
        gar nicht mehr (z.B. kleinerer Bildschirm), bleibt bewusst die Standardaufteilung stehen.
        """
        sashes = self.config.get("sash_positions", [])
        if not sashes_gueltig(sashes):
            self._vorschau_freihalten(versuche)
            return
        if not sashes_passen(sashes, self.main_pane.winfo_width()):
            if versuche < 20:   # bis zu 2 Sekunden auf das fertige Layout warten
                self.root.after(100, lambda: self.apply_saved_layout(versuche + 1))
            return
        try:
            self.main_pane.sashpos(0, int(sashes[0]))
            self.main_pane.sashpos(1, int(sashes[1]))
        except Exception:
            pass

    def _vorschau_freihalten(self, versuche=0):
        """Erststart ohne gespeicherte Aufteilung: Die Spalten ergeben sich von selbst, nur eine fast unsichtbare Vorschau
        wird korrigiert. Reicht der Platz dann nicht für die ganze Suchleiste, lässt sie sich aufziehen."""
        breite = self.main_pane.winfo_width()
        if breite <= 200 and versuche < 20:
            self.root.after(100, lambda: self._vorschau_freihalten(versuche + 1))
            return
        try:
            if vorschau_zu_schmal(breite, self.main_pane.sashpos(1)):
                erste, zweite = standard_sashes(breite, self.lbl_treffer.master.winfo_reqwidth())
                self.main_pane.sashpos(0, erste)
                self.main_pane.sashpos(1, zweite)
        except Exception as e:
            self.logger.warning(f"Trennlinien konnten nicht gesetzt werden: {e}")

    def oeffne_einstellungen(self):
        """Datei -> Einstellungen...: startet das Einstellungs-Tool (tools/settings_editor.py)."""
        tool = self.tool_manager.finde_tool("SettingsEditorTool") if hasattr(self, "tool_manager") else None
        if tool is None:
            messagebox.showwarning("Einstellungen", "Das Einstellungs-Tool wurde nicht geladen (siehe Log-Datei).")
            return
        self.tool_manager.execute_tool(tool)

    def reset_layout(self):
        """Setzt alle Fenstergrößen und Spaltenbreiten auf Standardwerte zurück."""
        if bestaetigung.frage("Layout zurücksetzen", "Möchtest du das Layout auf den Standard zurücksetzen?"):
            self.config.set("window_geometry", "1400x900")
            self.config.set("window_maximized", False)
            try:
                self.root.state("normal")   # sonst griffe das geometry() unten erst nach dem Wiederherstellen
            except tk.TclError:
                pass
            self.config.set("column_widths", {})
            self.config.set("sash_positions", [])
            self.config.set("custom_zoom", None)
            self.config.set("visible_columns", list(STANDARD_SPALTEN))

            self.root.geometry("1400x900")
            self.custom_zoom = None

            # Trennlinien sofort sichtbar zurücksetzen — genau das ist die Rettung, wenn die
            # linken Spalten einmal zugeklappt sind und man sie nicht mehr aufziehen kann.
            try:
                self.root.update_idletasks()
                erste, zweite = standard_sashes(self.main_pane.winfo_width(), self.lbl_treffer.master.winfo_reqwidth())
                self.main_pane.sashpos(0, erste)
                self.main_pane.sashpos(1, zweite)
            except Exception as e:
                self.logger.warning(f"Trennlinien konnten nicht zurückgesetzt werden: {e}")

            for col, breite in breiten_fuer_bildschirm(STANDARD_BREITEN, UIUtils.skalierung(self.root)).items():
                self.tree_files.column(col, width=breite)

            # Spalten-Sichtbarkeit sofort auf den Standard zurücksetzen (inkl. Menü-Häkchen)
            self.tree_files["displaycolumns"] = list(STANDARD_SPALTEN)
            if hasattr(self, 'column_vars'):
                for col, var in self.column_vars.items():
                    var.set(col in STANDARD_SPALTEN)
            
            # Alles oben wirkt sofort - der frühere Satz „bitte die App neu starten“ war veraltet (T0.10)
            messagebox.showinfo("Zurückgesetzt", "Standard-Werte wurden wiederhergestellt.")
            self.preview_manager.update_preview()

    def on_file_select(self, event):
        """
        Reagiert auf Klicks in der Dokumentenliste: befüllt Titel/Tags-Felder, stößt die Vorschau
        und Plugin-Benachrichtigung an und triggert ggf. Auto-Save für neu generierte Titel.
        Setzt bei aktiver Suche das Such-Schutzschild (ignore_next_select), damit der FolderManager
        die Suchergebnisse nicht durch automatische Ordner-Navigation überschreibt (siehe FALLSTRICKE #14).
        """
        # --- Such-Schutzschild ---
        # Wenn wir gerade suchen, unterdrücken wir jede automatische Ordner-Navigation.
        # Früher zählte schon der Haken „Inhalt (OCR)“ allein als Suche: dann schärfte JEDER
        # Dokument-Klick das Schild und der nächste Ordner-Klick wurde verschluckt (FALLSTRICKE #74).
        is_searching = self.search_manager.is_search_active()

        # Falls wir suchen, setzen wir eine temporäre Sperre für den FolderManager
        if is_searching:
            self.folder_manager.ignore_next_select = True
        # -------------------------------

        # Noch ausstehenden Auto-Save der vorherigen Datei sofort ausführen,
        # bevor die Feldinhalte gleich mit der neuen Datei überschrieben werden.
        self.save_manager.flush_pending()


        items = self.tree_files.selection()
        if not items: 
            return
            
        row_values = self.tree_files.item(items[0], "values")
        rel_path = row_values[4]
        abs_path = os.path.join(self.master_folder, rel_path)

        # Auto-Save: Wer weiterklickt, hat das (orange) vermutete Datum gesehen - es wird gespeichert
        self.save_manager.datum_beim_verlassen(abs_path)
        # Auto-Save: automatisch vergebene Angaben (Dokument-ID, Scan-Zeitpunkt) gleich festschreiben,
        # damit die Eigenschaften sie sofort zeigen (Peter 28.10.2026)
        self.save_manager.kennung_beim_anklicken(abs_path)

        self.current_preview_path = abs_path
        self.entry_title.delete(0, tk.END)
        self.entry_tags.delete("1.0", tk.END)
        
        # Titel (Dateiname oder Meta-Titel) in das Feld schreiben - aus dem PDF, nicht aus der
        # Listenzeile: die kann veraltet sein (Trefferliste nach Alt-Tag-Übertragung, Werkzeuge),
        # und Auto-Save schrieb die alten Werte dann zurück (Peter 28.10.2026). Nur bei gelungenem
        # Lesen ("format" fehlt im Fehler-Dict von get_metadata) - sonst bleibt die Zeile die Quelle.
        current_title = row_values[1]
        tags_text = row_values[2]
        if abs_path.lower().endswith(".pdf"):
            meta = PDFHandler.get_metadata(abs_path)
            if "format" in meta:
                current_title = meta.get("title") or current_title
                tags_text = tags_bereinigen(meta.get("keywords", ""))
        self.entry_title.insert(0, current_title)

        if tags_text not in ("---", ""):
            self.entry_tags.insert("1.0", tags_text)

        # Felder wurden gerade programmatisch neu befüllt — das ist keine Nutzer-Änderung.
        self.save_manager.mark_clean()

        self.preview_manager.update_preview()
        self.tag_manager.sync_tag_tree_selection()
        if hasattr(self, "eigenschaften_panel"):
            self.eigenschaften_panel.zeige(abs_path, rel_path)

        # --- NEU: Alle Plugins über die neue Auswahl informieren! ---
        if hasattr(self, 'tool_manager'):
            self.tool_manager.notify_selection_change()

        # --- Auto-Titel aus dem Dateinamen: bewusst OPT-IN (Standard: aus) ---
        # Sonst verändert ein bloßer Klick das Dokument (schreibt den Dateinamen als
        # Titel) und nimmt ihm damit den "unberührt/orange"-Status. Nur wenn der Nutzer
        # das in den Einstellungen ("auto_fill_on_click") aktiviert, wird das gemacht.
        # Dieselbe Einstellung steuert das automatische Speichern des vorgeschlagenen
        # Dokumentdatums in preview_manager.
        if (self.config.get("auto_fill_on_click", False)
                and getattr(self, 'autosave_var', None) and self.autosave_var.get()):
            # Kurzer Check: Hat das PDF intern wirklich noch keinen Titel?
            meta = PDFHandler.get_metadata(abs_path)
            if not meta.get("title", "") and current_title:
                # Löst den Auto-Save nach 1 Sekunde aus
                self.save_manager.trigger_autosave()

    def leere_dokumentanzeige(self, hinweis=""):
        """
        Kein Dokument mehr anzeigen: Vorschau (optional mit Hinweistext), Titel, Tags und
        Eigenschaften leeren. Ein noch ausstehender Auto-Save des bisherigen Dokuments läuft
        vorher - sonst gingen gerade getippte Änderungen verloren.
        """
        self.save_manager.flush_pending()
        self.preview_manager.leere_vorschau(hinweis)
        self.entry_title.delete(0, tk.END)
        self.entry_tags.delete("1.0", tk.END)
        if hasattr(self, "date_entry"):      # stand sonst noch orange da (FALLSTRICKE #111)
            self.date_entry.delete(0, tk.END)
            self.setze_datum_stil()
        self.save_manager.mark_clean()
        if hasattr(self, "eigenschaften_panel"):
            self.eigenschaften_panel.leeren()
        if hasattr(self, 'tool_manager'):
            self.tool_manager.notify_selection_change()

    def open_log_file(self):
        if os.path.exists(self.logger.log_file): 
            os.startfile(self.logger.log_file) 
        else: 
            messagebox.showinfo("Info", "Die Log-Datei wurde noch nicht erstellt.")
    
    # ==========================================
    # DATUMSFELD: vermutet / normal (FALLSTRICKE #86)
    # ==========================================
    def setze_datum_stil(self, vermutet=False, fehler=False):
        """
        Datumsfeld-Aussehen: vermutet = orange hinterlegt mit weißer Schrift (noch nicht im PDF,
        wirkt wie vorausgewählt), sonst schwarz auf weiß, fehler = rote Schrift (ungültige Eingabe).
        """
        if not hasattr(self, 'date_entry'):
            return
        self.datum_vermutet_angezeigt = vermutet
        if vermutet:
            self.date_entry.config(foreground="white", background=DATUM_VORSCHLAG_FARBE,
                                   insertbackground="white")
        else:
            self.date_entry.config(foreground="red" if fehler else "black",
                                   background=getattr(self, 'date_entry_hintergrund', "white"),
                                   insertbackground="black")

    def datum_aus_liste_tippen(self, event):
        """
        Ziffer in der Dokumentenliste bei vermutetem (orangem) Datum: Feld wird normal, die Ziffer
        ersetzt den Vorschlag, weiter geht es im Datumsfeld (Peters Idee 28.10.2026). Bei schon
        gespeichertem Datum nicht - ein versehentlicher Tastendruck soll es nicht anfassen.
        """
        if not (event.char and event.char.isdigit() and getattr(self, 'datum_vermutet_angezeigt', False)):
            return None
        self.setze_datum_stil(vermutet=False)
        self.date_entry.delete(0, tk.END)
        self.date_entry.insert(0, event.char)
        self.date_entry.focus_set()
        self.date_entry.icursor(tk.END)
        return "break"

    def datum_feld_betreten(self, event=None):
        """Klick/Tab ins orange Feld: normal darstellen und alles markieren - Tippen überschreibt."""
        if getattr(self, 'datum_vermutet_angezeigt', False):
            self.setze_datum_stil(vermutet=False)
            self.date_entry.selection_range(0, tk.END)
            self.date_entry.icursor(tk.END)

    def datum_vorschlag_zurueck(self, event=None):
        """Esc im Datumsfeld: noch nicht gespeicherten Vorschlag wiederherstellen, zurück in die Liste."""
        feld = getattr(self, 'datum_feld', None) or {}
        if feld.get("angezeigt") and not feld.get("gespeichert"):
            self.date_entry.delete(0, tk.END)
            self.date_entry.insert(0, feld["angezeigt"])
            self.setze_datum_stil(vermutet=True)
        if hasattr(self, 'tree_files'):
            self.tree_files.focus_set()
        return "break"

    def aktualisiere_datumszeile(self, item_id, cleaned_date):
        """Zeigt ein gerade gespeichertes Dokumentdatum ('JJJJ-MM-TT') direkt in der Listenzeile an, ohne Neuaufbau."""
        vals = list(self.tree_files.item(item_id, "values"))
        if len(vals) < 5:
            return
        try:
            y, m, d = cleaned_date.split('-')
            ui_date = f"{d}.{m}.{y}"
            bg_tag = "row_even" if int(y) % 2 == 0 else "row_odd"
        except Exception:
            ui_date = cleaned_date
            bg_tag = "row_even"

        vals[0] = ui_date

        # Farb-Tags neu berechnen: Jahres-Hintergrund neu, "untouched" (orange)
        # entfernen (Dokument hat jetzt ein Datum), und bei aktiver Suche die
        # stahlblaue "search_local"-Färbung frisch bestimmen. Ein unberührtes
        # Dokument hatte KEIN search_local (Orange hatte Vorrang) - nach dem
        # Speichern muss es also neu gesetzt werden, sonst bliebe die Zeile
        # fälschlich schwarz statt blau.
        cur_tags = self.tree_files.item(item_id, "tags")
        if isinstance(cur_tags, str):
            cur_tags = (cur_tags,)
        new_tags = [t for t in cur_tags if t not in ("row_even", "row_odd", "untouched", "search_local")]
        new_tags.insert(0, bg_tag)
        rel_path = vals[4]  # der Tree speichert den relativen Pfad in Spalte 4
        if self.search_manager.is_search_active() and self.search_manager.is_local_result(rel_path):
            new_tags.append("search_local")
        self.tree_files.item(item_id, values=vals, tags=tuple(new_tags))

    def save_manual_date(self, event=None):
        """Validiert das Datum, schreibt es ins PDF und aktualisiert die TreeView."""
        if not hasattr(self, 'date_entry'):
            return

        cleaned_date = PDFHandler.normalize_date_input(self.date_entry.get())
        
        if cleaned_date:
            current_pdf = getattr(self, 'current_preview_path', None)
            # Nur echte PDFs: Die Datums-Automatik (auto_fill_on_click, preview_manager)
            # ruft diesen Weg auch für auto-selektierte Nicht-PDFs auf - ein Schreibversuch
            # z.B. in eine desktop.ini endete mit "Failed to open stream" (06.09.2026).
            if current_pdf and current_pdf.lower().endswith(".pdf"):
                # --- FIX: Watchdog-Race-Condition blockieren ---
                # Schaltet den Ordner-Wächter für 1,5 Sekunden stumm, 
                # damit die Suche nicht neu lädt, während Windows die Datei noch sperrt!
                self.is_moving = True 
                
                # 1. Metadaten schreiben
                PDFHandler.write_custom_metadata(current_pdf, {"KID_DokumentenDatum": cleaned_date})
                feld = getattr(self, "datum_feld", None)
                if feld and feld.get("pfad") == current_pdf:
                    feld["gespeichert"] = cleaned_date
                
                # Watchdog nach Ablauf der Zeit wieder aufwecken
                self.root.after(1500, lambda: setattr(self, 'is_moving', False))
                # -------------------------------------------------
                
                # 2. Textfeld aktualisieren
                self.date_entry.delete(0, tk.END)
                self.date_entry.insert(0, cleaned_date)
                self.setze_datum_stil(vermutet=False)
                # Fokus zurück in die Liste: mit den Pfeiltasten gleich weiterblättern
                (self.tree_files if hasattr(self, 'tree_files') else self.root).focus_set()
                
                # --- FIX: Vorschau-Cache killen und zwingen, neu zu zeichnen! ---
                if hasattr(self, 'preview_manager'): 
                    self.preview_manager.verwerfe_cache()             # Gedächtnis löschen
                    self.preview_manager.update_preview()             # Neu laden (mit neuem Marker!)
                # ---------------------------------------------------------------------------
                
                # 3. Direktes Live-Update in der Liste
                if hasattr(self, 'tree_files') and self.tree_files.selection():
                    self.aktualisiere_datumszeile(self.tree_files.selection()[0], cleaned_date)
        else:
            self.setze_datum_stil(fehler=True)