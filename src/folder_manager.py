import os
import platform
import stat
import subprocess
import datetime
import json
import re
import tkinter as tk
from tkinter import filedialog, messagebox
import bestaetigung
import app_paths
import aktivitaet
import auto_pilot
import einzelstart
import index_manager
import ordner_aliase
import scan_date
import sicher_speichern
from pdf_handler import PDFHandler
from ui_utils import UIUtils


def formatiere_textqualitaet(prozent):
    """Anzeige der Textqualität in der Dokumentenliste: '92 %', bei None (kein bewertbarer Text) '—'."""
    return "—" if prozent is None else f"{int(prozent)} %"


def ist_versteckte_systemdatei(entry):
    """
    Windows-Systemdateien wie desktop.ini/Thumbs.db erkennen (Name oder
    Versteckt-/System-Attribut). Live-Fund 06.09.2026: Eine von Windows angelegte
    desktop.ini stand als "Dokument" in der Liste, wurde beim Ordnerwechsel
    auto-selektiert und bekam über die Datums-Automatik (auto_fill_on_click) einen
    PDF-Metadaten-Schreibversuch ("Failed to open stream"). Was der Explorer
    versteckt, gehört auch hier nicht in die Dokumentenliste.
    :param entry: os.DirEntry (oder ein Objekt mit .name und .stat()).
    """
    # .pdf.tmp: Rest eines abgebrochenen Schreibens. Das Original daneben ist heil (FALLSTRICKE #115), der nächste Schreibvorgang
    # überschreibt den Rest; als Dokument in der Liste hätte er nichts zu suchen (FALLSTRICKE #60).
    if entry.name.lower() in ("desktop.ini", "thumbs.db") or entry.name.lower().endswith(".pdf.tmp"):
        return True
    attribute = getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0) | getattr(stat, "FILE_ATTRIBUTE_SYSTEM", 0)
    try:
        return bool(entry.stat().st_file_attributes & attribute)
    except (OSError, AttributeError):
        return False

SICHERUNGSHINWEIS = (
    "Hinweis: Titel, Tags und Datum werden direkt in die PDF-Dateien geschrieben (in deren "
    "Metadaten, der Inhalt bleibt unverändert). Zum Kennenlernen des Programms am besten mit "
    "Kopien der Dokumente arbeiten. Gelöschte Dateien landen im Papierkorb der Sammlung.")


def enthaelt_pdfs(ordner, max_tiefe=3, max_eintraege=5000):
    """True, wenn im Ordner (bis max_tiefe Ebenen) mindestens eine PDF liegt - begrenzt, damit große Bestände den Dialog nicht verzögern."""
    start_tiefe = ordner.rstrip("\\/").count(os.sep)
    gesehen = 0
    try:
        for wurzel, unterordner, dateien in os.walk(ordner):
            if wurzel.count(os.sep) - start_tiefe >= max_tiefe:
                unterordner[:] = []
            for name in dateien:
                gesehen += 1
                if name.lower().endswith(".pdf"):
                    return True
                if gesehen >= max_eintraege:
                    return False
    except OSError:
        return False
    return False


class FolderManager:
    # --- Vorkompilierte Konstanten für massiven Performance-Boost ---
    PATTERN_NUMBERS = re.compile(r'\d+')

    def __init__(self, app):
        """
        Initialisiert den Controller für die Ordnerstruktur und Dateisystem-Navigation.
        :param app: Referenz auf die Hauptinstanz.
        """
        self.app = app

    def choose_master_folder(self):
        """Fragt per Dialog ein Hauptverzeichnis ab und übernimmt es (uebernimm_hauptordner)."""
        path = filedialog.askdirectory()
        if path:
            self.uebernimm_hauptordner(path)

    def uebernimm_hauptordner(self, path):
        """
        Macht 'path' zum Hauptordner der App: speichert ihn in der Config, richtet den
        KID-Daten-Ordner ein, lädt den Tag-Katalog der Sammlung und startet Logging +
        Watchdog neu. Gemeinsamer Weg für die Ordnerwahl per Dialog UND die
        Ersteinrichtung des Seniorenmodus (Schritt 5).
        """
        if not self._sammlung_belegen(path):
            return
        # Sicherungshinweis (Beta-Vorbereitung 13.09.2026): Wer einen Ordner mit
        # vorhandenen PDFs zum ERSTEN Mal öffnet (noch kein Daten-Ordner), soll wissen,
        # dass das Programm in die Dateien selbst schreibt - einmal pro Sammlung.
        erstmals = not os.path.isdir(app_paths.data_dir(path))
        self.app.master_folder = path
        self.app.config.set("master_folder", path)
        if erstmals and enthaelt_pdfs(path):
            messagebox.showinfo("Sammlung zum ersten Mal geöffnet",
                                f"'{path}' wird jetzt als Sammlung verwaltet.\n\n" + SICHERUNGSHINWEIS)

        # KID-Daten-Ordner der neuen Sammlung einrichten (inkl. Migration von Altbeständen)
        for action in app_paths.migrate_legacy_layout(path):
            self.app.logger.info(f"KID-Daten-Ordner: {action}")

        self.app.update_log_location()
        self.app.logger.info(f"Neuer Hauptordner gewählt: {path}")

        # Der Tag-Katalog gehört zur Sammlung: Katalog des neuen Hauptordners laden
        self.app.tag_editor.tags_file = app_paths.tags_path(path)
        self.app.tag_editor.load_tags()
        self.app.tag_manager.sync_tag_tree_selection()
        self.app.melde_beschaedigte()

        self.app.monitor.stop_watching()
        self.refresh_folder_tree()
        self.app.monitor.start_watching(self.app.master_folder)

    def _sammlung_belegen(self, path):
        """Hat ein anderes KID diese Sammlung offen, wird sie hier nicht geöffnet (einzelstart.py). Die bisherige bleibt dann offen."""
        if einzelstart.belege(path):
            return True
        messagebox.showwarning("Sammlung bereits geöffnet",
                               f"'{path}' ist schon in einem anderen Fenster von KID geöffnet.\n\n"
                               "Zwei Fenster auf derselben Sammlung kämen sich in die Quere. Bitte dort weiterarbeiten.")
        return False

    def ersteinrichtung_anbieten(self):
        """
        Seniorenmodus Schritt 5, Ersteinrichtung: Beim Start ohne (gültigen) Hauptordner
        wird EINMAL angeboten, 'Dokumente\\KID' anzulegen und komplett einzurichten -
        Standard-Ordnerstruktur inkl. Posteingang für den Scanner. Ein 'Nein' landet beim
        bisherigen Weg (Datei -> Sammlung öffnen) und wird nicht wiederholt
        genervt - die Frage kommt nur, solange kein Hauptordner gesetzt ist.
        """
        if self.app.master_folder and os.path.isdir(self.app.master_folder):
            return
        dokumente = os.path.join(os.path.expanduser("~"), "Documents")
        basis = dokumente if os.path.isdir(dokumente) else os.path.expanduser("~")
        kid = os.path.join(basis, "KID")

        # Existiert der Ordner schon MIT Inhalt, wird er NIE stillschweigend übernommen
        # (Live-Fund 04.09.2026: ein alter Test-Ordner 'Documents\KID' aus dem Juli wurde
        # kommentarlos zum Hauptordner, die neue Registerstruktur landete mitten in der
        # alten - der folgende Automatik-Lauf sortierte in den Mischmasch ein).
        if os.path.isdir(kid) and os.listdir(kid):
            if messagebox.askyesno(
                    "Willkommen!",
                    f"Es ist noch kein Dokumentenordner eingerichtet - und '{kid}' existiert "
                    f"bereits und ist nicht leer ({len(os.listdir(kid))} Einträge).\n\n"
                    "Damit nichts durcheinandergerät, wird er nicht automatisch übernommen.\n\n"
                    "Möchtest du jetzt selbst einen Dokumentenordner auswählen?\n"
                    "(sonst später über Datei → Sammlung öffnen...)",
                    icon="warning"):
                self.choose_master_folder()
            return

        # Drei Wege (Nutzerwunsch 04.09.2026: den Zielordner auch selbst wählen können):
        # Ja = Standardordner anlegen, Nein = eigenen Ordner auswählen, Abbrechen = später.
        wahl = messagebox.askyesnocancel(
            "Willkommen!",
            "Es ist noch kein Dokumentenordner eingerichtet.\n\n"
            f"Soll ich '{kid}' anlegen und fertig einrichten?\n"
            "(mit Posteingang für den Scanner und der Standard-Ablagestruktur)\n\n"
            "Ja  =  diesen Standardordner anlegen\n"
            "Nein  =  einen eigenen Ordner auswählen\n"
            "Abbrechen  =  später einrichten (Datei → Sammlung öffnen...)\n\n"
            + SICHERUNGSHINWEIS)
        if wahl is None:
            return
        if not wahl:
            # Eigener Ordner: Auswahl-Dialog; danach dieselbe Einrichtung wie beim
            # Standardweg (create_default_folders fragt bei nicht-leeren Ordnern selbst nach)
            self.choose_master_folder()
            if self.app.master_folder and os.path.isdir(self.app.master_folder):
                self.create_default_folders()
            return
        try:
            os.makedirs(kid, exist_ok=True)
        except OSError as e:
            messagebox.showerror("Ersteinrichtung", f"Ordner konnte nicht angelegt werden:\n{e}")
            return
        self.uebernimm_hauptordner(kid)
        self.create_default_folders()

    def create_default_folders(self):
        """Erzeugt die Standard-Ordnerstruktur im Hauptverzeichnis anhand von folder_default.json (legt die Datei mit einer Fallback-Struktur an, falls sie noch fehlt oder beschädigt ist)."""
        if not self.app.master_folder or not os.path.isdir(self.app.master_folder):
            messagebox.showwarning("Hinweis", "Bitte wähle zuerst einen Hauptordner über 'Datei -> Sammlung öffnen...' aus.")
            return

        existing_items = os.listdir(self.app.master_folder)
        if existing_items and not bestaetigung.frage("Ordner anlegen", "Soll die Standard-Ordnerstruktur in diesem Verzeichnis angelegt werden?"):
            return

        # Pfad zur JSON-Konfigurationsdatei
        json_path = "folder_default.json"
        
        # Fallback-Struktur, falls die JSON noch nicht existiert - identisch mit der
        # ausgelieferten folder_default.json (30.08.2026): Posteingang und Unsicher-Ordner
        # der Vollautomatik (Ziffern-Präfix sortiert vor den Buchstabengruppen), fünf
        # Buchstabengruppen zu je 5 Buchstaben in Listenform (Nutzerentscheidung
        # 30.08.2026: im Explorer lesbarer als "[A-F]" und gleichmäßiger gefüllt),
        # dazu nur Beispielordner, die es in jedem Haushalt wirklich gibt (kein
        # erfundener "Dr. Maier" - ein echter Absender "Maier" würde sonst per
        # Kernname dort einsortiert).
        default_structure = {
            auto_pilot.POSTEINGANG_ORDNER: {},
            auto_pilot.UNSICHER_ORDNER: {},
            "[0-9]": {},
            "A - B - C - D - E": {},
            "F - G - H - I - J": {"Finanzamt": {}},
            "K - L - M - N - O": {"Krankenkasse": {}},
            "P - Q - R - S - T": {"Stadtwerke": {}},
            "U - V - W - X - Y - Z": {},
        }

        # Mitgelieferte Vorlage (auch aus der gepackten EXE) hat Vorrang vor der Fallback-Struktur
        app_paths.ensure_default_file(json_path, getattr(self.app, "logger", None))

        # JSON-Datei erstellen, falls nicht vorhanden
        if not os.path.exists(json_path):
            try:
                sicher_speichern.schreibe_json(json_path, default_structure, indent=4, ensure_ascii=False)
                self.app.logger.info(f"Standard-Konfiguration '{json_path}' wurde neu erstellt.")
            except Exception as e:
                self.app.logger.error(f"Konnte '{json_path}' nicht erstellen: {e}")
                
        # JSON-Struktur laden
        structure_to_build = default_structure
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    structure_to_build = json.load(f)
            except Exception as e:
                messagebox.showerror("Fehler", f"Die Datei {json_path} ist beschädigt:\n{e}\n\nEs wird die Fallback-Struktur verwendet.")

        try:
            self.app.monitor.stop_watching()
            
            # --- Smarte, rekursive Ordner-Erstellung ---
            def build_structure(base_path, structure):
                """Legt rekursiv Ordner gemäß der (verschachtelten) JSON-Struktur an; akzeptiert zur Abwärtskompatibilität auch flache Listen."""
                if isinstance(structure, dict):
                    for folder_name, sub_structure in structure.items():
                        new_dir = os.path.join(base_path, folder_name)
                        os.makedirs(new_dir, exist_ok=True)
                        build_structure(new_dir, sub_structure)
                elif isinstance(structure, list):
                    # Abwärtskompatibilität, falls Listen in der JSON genutzt werden
                    for folder_name in structure:
                        new_dir = os.path.join(base_path, folder_name)
                        os.makedirs(new_dir, exist_ok=True)

            # Hat die Sammlung schon einen Posteingang (z.B. "00_Posteingang" aus einer älteren
            # Vorlage), keinen zweiten anlegen - die Vollautomatik nähme sonst den erstbesten.
            vorhandener_posteingang = auto_pilot.finde_posteingang(self.app.master_folder)
            if vorhandener_posteingang and isinstance(structure_to_build, dict):
                structure_to_build = {
                    name: sub for name, sub in structure_to_build.items()
                    if "posteingang" not in name.lower()
                    or os.path.normcase(os.path.join(self.app.master_folder, name)) == os.path.normcase(vorhandener_posteingang)
                }

            build_structure(self.app.master_folder, structure_to_build)
            
            self.refresh_folder_tree()
            self.app.logger.info("Ordnerstruktur wurde aus JSON generiert.")
            messagebox.showinfo("Erfolg", "Die Ordnerstruktur wurde erfolgreich angelegt!")
        except Exception as e:
            self.app.logger.error(f"Fehler beim Erstellen der Ordner: {e}")
            messagebox.showerror("Fehler", f"Ordner konnten nicht erstellt werden:\n{e}")
        finally:
            if self.app.master_folder and os.path.isdir(self.app.master_folder):
                self.app.monitor.start_watching(self.app.master_folder)

    # ==========================================
    # WATCHDOG-SYNCHRONISATION
    # ==========================================
    def on_filesystem_event(self):
        """Watchdog-Callback: ignoriert Events während eigener Datei-Operationen (siehe is_moving/is_saving) und debounced den UI-Sync um 500ms."""
        if getattr(self.app, 'is_moving', False) or getattr(self.app, 'is_saving', False):
            return
        if hasattr(self, '_sync_timer'):
            self.app.root.after_cancel(self._sync_timer)
        self._sync_timer = self.app.root.after(500, self.sync_ui)

    def sync_ui(self):
        """Baut nach einer Dateisystem-Änderung entweder die aktiven Suchfilter neu auf oder aktualisiert den Ordnerbaum unter Beibehaltung der aktuellen Auswahl."""
        if self.app.search_manager.is_search_active():
            self.app.search_manager.apply_filters()
            return

        selected_folder_path = None
        selected_items = self.app.tree_folders.selection()
        if selected_items:
            selected_folder_path = self.app.tree_folders.item(selected_items[0], "values")[0]

        self.refresh_folder_tree()
        if selected_folder_path and not self._select_and_open_path(selected_folder_path):
            if index_manager.mails_ausgeblendet(self.app):      # Die letzte sichtbare Datei des Ordners ist gegangen
                self._select_and_open_path(self.app.master_folder)

    # ==========================================
    # BAUM-GENERIERUNG UND REKURSIVES ZÄHLEN
    # ==========================================
    def toggle_show_trash(self):
        """Callback für die 'Papierkorb einblenden'-Menü-Checkbox - merkt sich die Wahl in der Config (wie Auto-Save), damit sie einen Neustart übersteht."""
        self.app.config.set("show_trash", self.app.show_trash_var.get())
        gewaehlt = self.app.tree_folders.selection()
        war_papierkorb = bool(gewaehlt) and app_paths.is_trash_path(
            self.app.tree_folders.item(gewaehlt[0], "values")[0], self.app.master_folder)
        self.refresh_folder_tree()
        # Ausgeblendet, während er gerade angezeigt wurde: sonst war im Baum nichts markiert, die
        # Liste zeigte aber weiter den Papierkorb (Fund T0.8, 25.10.2026) - auf den Hauptordner wechseln
        if war_papierkorb and not self.app.show_trash_var.get() and self.app.master_folder:
            self._select_and_open_path(self.app.master_folder)

    def toggle_mails(self):
        """Ansicht → „Mails ausblenden“: Dokumente bleiben, wo sie sind, nur Baum, Liste und Suche zeigen sie nicht
        (Peter 06.11.2026, FAHRPLAN Etappe 4b). Gemerkt wie der Papierkorb-Schalter."""
        self.app.config.set("mails_ausblenden", self.app.mails_ausblenden_var.get())
        gewaehlt = self.app.tree_folders.selection()
        ordner = self.app.tree_folders.item(gewaehlt[0], "values")[0] if gewaehlt else None
        self.refresh_folder_tree()
        suche = self.app.search_manager.is_search_active()
        if suche:
            self.app.search_manager.apply_filters()
        if not (ordner and self._select_and_open_path(ordner, laden=not suche)) and self.app.master_folder:
            self._select_and_open_path(self.app.master_folder, laden=not suche)

    def _offene_ordner(self, parent=""):
        """Pfade aller aktuell aufgeklappten Ordner-Knoten (rekursiv) - damit ein Neuaufbau den Aufklapp-Zustand wiederherstellen kann."""
        offen = []
        for child in self.app.tree_folders.get_children(parent):
            if self.app.tree_folders.item(child, "open"):
                offen.append(self.app.tree_folders.item(child, "values")[0])
            offen.extend(self._offene_ordner(child))
        return offen

    def _klappe_auf(self, pfade, parent=""):
        """Klappt nach einem Neuaufbau genau die Knoten wieder auf, deren Pfad in `pfade` steht."""
        for child in self.app.tree_folders.get_children(parent):
            if self.app.tree_folders.item(child, "values")[0] in pfade:
                self.app.tree_folders.item(child, open=True)
            self._klappe_auf(pfade, child)

    def refresh_folder_tree(self):
        """
        Baut den Ordnerbaum links komplett neu auf; blendet den Papierkorb (falls aktiviert)
        als ersten Eintrag ein. Der Aufklapp-Zustand der Ordner bleibt dabei erhalten
        (FALLSTRICKE #34): Der Neuaufbau wird auch vom Watchdog ausgelöst - etwa nach jedem
        im Explorer angelegten/gelöschten Ordner - und klappte bisher jedes Mal alles zu.
        Die Selektion stellt weiterhin der Aufrufer her (_select_and_open_path), weil
        selection_set() ein <<TreeviewSelect>> auslöst und damit das Dokumenten-Grid
        neu lädt - das soll nicht jeder Neuaufbau implizit tun.
        """
        offene_pfade = set(self._offene_ordner())
        for item in self.app.tree_folders.get_children(): self.app.tree_folders.delete(item)
        if not self.app.master_folder: return
        
        if hasattr(self.app, 'show_trash_var') and self.app.show_trash_var.get():
            trash_folder = app_paths.trash_dir(self.app.master_folder)

            if os.path.exists(trash_folder):
                count = len([f for f in os.listdir(trash_folder) if os.path.isfile(os.path.join(trash_folder, f))])
                count_str = str(count) if count > 0 else ""
                self.app.tree_folders.insert("", 0, text="🗑️ Papierkorb", values=(trash_folder, count_str), tags=("trash_folder",))    

        root_node = self.app.tree_folders.insert("", "end", text=os.path.basename(self.app.master_folder), values=(self.app.master_folder, ""), open=True)
        self._populate_tree(root_node, self.app.master_folder)
        if offene_pfade:
            self._klappe_auf(offene_pfade)

    def _populate_tree(self, parent, path):
        """Füllt rekursiv einen Ordner-Knoten mit seinen Unterordnern und zählt PDFs direkt sowie in allen Unterordnern (Anzeige als Badge)."""
        return self._fuelle(parent, path, index_manager.mails_ausgeblendet(self.app))[0]

    def _ohne_mails(self, pdfs):
        """Wie viele der PDFs eines Ordners keine Mail-PDFs sind. Fragt den Index, nur ein unbekanntes PDF wird gelesen."""
        aus_index = index_manager.metadaten_sicher(self.app, pdfs)
        return sum(not (aus_index.get(p) or PDFHandler.get_metadata(p)).get("KID_Richtung") for p in pdfs)

    def _fuelle(self, parent, path, mails_aus):
        """(Zahl der sichtbaren PDFs, liegen hier nur ausgeblendete Mails?). Ein reiner Mail-Ordner verschwindet, auch der
        darüber, wenn darunter nichts anderes liegt. Ein wirklich leerer Ordner bleibt wie bisher sichtbar."""
        filtern = mails_aus and not os.path.basename(path).startswith("0_")
        pdfs = []
        subfolder_count = 0
        verborgen = False

        try:
            for entry in os.scandir(path):
                if entry.is_file() and entry.name.lower().endswith(".pdf"):
                    pdfs.append(entry.path)
                elif entry.is_dir() and not entry.name.startswith('.'):
                    node = self.app.tree_folders.insert(parent, "end", text=entry.name, values=(entry.path, ""))
                    child_total, nur_mails = self._fuelle(node, entry.path, mails_aus)
                    subfolder_count += child_total
                    if nur_mails:
                        self.app.tree_folders.delete(node)
                        verborgen = True
        except PermissionError:
            pass

        direct_count = self._ohne_mails(pdfs) if filtern and pdfs else len(pdfs)
        verborgen = verborgen or direct_count < len(pdfs)
        total_count = direct_count + subfolder_count
        count_str = str(total_count) if total_count > 0 else ""

        self.app.tree_folders.item(parent, values=(path, count_str), tags=())
        return total_count, verborgen and not total_count
    # ==========================================

    def _select_and_open_path(self, target_path, parent="", laden=True):
        """
        Klappt rekursiv alle Vorfahren-Ordner eines Zielpfads auf und selektiert ihn, um ihn
        im Baum sichtbar zu machen (z.B. nach einer Suche oder einem Datei-Move).

        Verglichen wird schrägstrich- und großschreibungs-neutral (FALLSTRICKE #52): Der
        Hauptordner steht in settings.json mit Vorwärts-Schrägstrichen ('C:/…' — so liefern
        ihn Tk-Dateidialoge und testzustand.py), während os.path-Funktionen Backslashes
        erzeugen — ein roher startswith-Vergleich schlug dann still fehl und der Sprung
        zum Ordner unterblieb kommentarlos.
        """
        ziel = os.path.normcase(os.path.normpath(target_path))
        for item in self.app.tree_folders.get_children(parent):
            item_path = os.path.normcase(os.path.normpath(self.app.tree_folders.item(item, "values")[0]))
            if ziel == item_path or ziel.startswith(item_path + os.sep):
                self.app.tree_folders.item(item, open=True)
                if item_path == ziel:
                    self.app.tree_folders.selection_set(item)
                    if laden:
                        self.on_folder_select(None)
                    else:
                        # Nur markieren, Dokumentenliste NICHT neu laden (aktive Suche bleibt stehen):
                        # das <<TreeviewSelect>> dieses selection_set fängt das Such-Schutzschild ab -
                        # sonst beendete es über on_folder_select die Suche (Peter 25.10.2026)
                        self.ignore_next_select = True
                    return True
                if self._select_and_open_path(target_path, item, laden):
                    return True
        return False

    def zeige_dokument(self, pfad):
        """
        Zeigt ein Dokument im Hauptfenster an (Vorschau rechts): wechselt nötigenfalls links in
        seinen Ordner und wählt die Zeile in der Dokumentenliste. Gemeinsamer Helfer für Werkzeug-
        Fenster (Ablage-Vorschau, Titel-Aufräumen), die zur Kontrolle das Original zeigen wollen.
        Bewusst nur selection_set/see: on_file_select feuert Tkinter selbst (FALLSTRICKE #8); eine
        bereits bestehende exakte Einzelauswahl wird nicht noch einmal gesetzt (löst kein Rendern aus).
        Nach einem Ordnerwechsel wird die Zeile erst per after_idle gewählt: der selection_set im
        Ordnerbaum feuert <<TreeviewSelect>> erst NACH dieser Funktion und füllt die Liste ein
        zweites Mal mit der ersten Zeile als Auswahl - sofort gewählt wäre die Zeile eine Viertel-
        sekunde später wieder weg (FALLSTRICKE #73). Liefert True, wenn Zeile bzw. Ordner gefunden wurden.
        """
        tree_files = getattr(self.app, "tree_files", None)
        tree_folders = getattr(self.app, "tree_folders", None)
        master = getattr(self.app, "master_folder", "")
        if not pfad or tree_files is None or not master or not os.path.exists(pfad):
            return False
        # Ein Link „Anhang der Mail: …“ darf nicht ins Leere gehen: Wer eine Mail sehen will, bekommt die Mails zurück
        if index_manager.mails_ausgeblendet(self.app) and index_manager.ist_ausgeblendet(
                os.path.relpath(pfad, master), PDFHandler.get_metadata(pfad).get("KID_Richtung")):
            self.app.mails_ausblenden_var.set(False)
            self.app.config.set("mails_ausblenden", False)
            self.refresh_folder_tree()
        ordner = os.path.dirname(os.path.abspath(pfad))
        if tree_folders is not None:
            gewaehlt = tree_folders.selection()
            aktuell = tree_folders.item(gewaehlt[0], "values")[0] if gewaehlt else ""
            if os.path.normcase(os.path.abspath(aktuell or master)) != os.path.normcase(ordner):
                if not self._select_and_open_path(ordner):
                    return False
                self.app.root.after_idle(self._waehle_dokumentzeile, pfad, 10)
                return True
        return self._waehle_dokumentzeile(pfad)

    def _waehle_dokumentzeile(self, pfad, versuche=0):
        """
        Zeile eines Dokuments in der Dokumentenliste wählen; True, wenn gefunden. Mit ``versuche`` > 0
        wird bei Nichtfinden alle 50 ms erneut geschaut: der Idle-Aufruf kann mitten im zweiten
        Listenaufbau landen (ein update_idletasks beim Zeichnen der Vorschau), wenn die Zeilen
        gerade gelöscht, aber noch nicht neu eingefügt sind (FALLSTRICKE #73).
        """
        tree_files = self.app.tree_files
        master = self.app.master_folder
        ziel = os.path.normcase(os.path.abspath(pfad))
        for item in tree_files.get_children(""):
            values = tree_files.item(item, "values")
            if len(values) > 4 and os.path.normcase(os.path.abspath(os.path.join(master, values[4]))) == ziel:
                if tree_files.selection() != (item,):
                    tree_files.selection_set(item)
                    tree_files.see(item)
                return True
        if versuche > 0:
            self.app.root.after(50, self._waehle_dokumentzeile, pfad, versuche - 1)
        return False

    def aktualisiere_textqualitaet(self, pfad):
        """
        Zeile eines Dokuments in der Liste nach einem Neu-Erfassen mit der frischen
        Textqualität versorgen (Nutzerwunsch 11.09.2026: Änderung sofort sichtbar), ohne
        die ganze Liste neu aufzubauen. Tut nichts, wenn die Spalte ausgeblendet ist oder
        das Dokument nicht in der Liste steht. Liefert den angezeigten Wert oder None.
        """
        if "qualitaet" not in list(self.app.tree_files["displaycolumns"]):
            return None
        rel = os.path.normcase(os.path.relpath(pfad, self.app.master_folder))
        for iid in self.app.tree_files.get_children(""):
            werte = self.app.tree_files.item(iid, "values")
            if len(werte) > 4 and os.path.normcase(werte[4]) == rel:
                anzeige = formatiere_textqualitaet(PDFHandler.get_textqualitaet(pfad))
                self.app.tree_files.set(iid, "qualitaet", anzeige)
                return anzeige
        return None

    def on_folder_select(self, event):
        """
        Lädt beim Anklicken eines Ordners dessen PDFs in das Dokumenten-Grid: liest Metadaten
        (Titel/Tags/Datum, mit Fallback auf Dateiname bzw. Änderungsdatum), sortiert absteigend
        nach Datum und färbt Zeilen nach geradem/ungeradem Jahr ein. Respektiert das Such-Schutzschild
        (ignore_next_select, siehe FALLSTRICKE #14) und bricht bei aktiver Suche zugunsten der
        Suchergebnisse ab.
        """
        # --- NEU: Prüfen, ob wir die Ordner-Navigation ignorieren sollen ---
        if getattr(self.app, 'folder_manager', None):
            if getattr(self.app.folder_manager, 'ignore_next_select', False):
                self.app.folder_manager.ignore_next_select = False # Einmal sperren, dann wieder frei
                return # Abbruch: Der Such-Modus hat Vorrang!
            
        # Klick auf einen Ordner, während die Liste Suchergebnisse zeigt: Suche beenden. Nur noch
        # getippter, nicht mit Return abgeschickter Text hält den Ordner nicht auf (Peter 01.11.2026)
        if event is not None and hasattr(self.app, 'search_manager') and self.app.search_manager.is_search_active():
            self.app.search_manager.reset_search()
            return

        items = self.app.tree_folders.selection()
        if not items: return
        
        path = self.app.tree_folders.item(items[0], "values")[0]
        old_selection_path = getattr(self.app, 'current_preview_path', None)
        
        for row in self.app.tree_files.get_children(): self.app.tree_files.delete(row)
        
        file_data_list = []
        global_tag_counts = {}
        qualitaet_sichtbar = "qualitaet" in list(self.app.tree_files["displaycolumns"])

        # Aktivitätsanzeige: Ordnername + Zähler, damit man auf einem langsamen Rechner
        # sieht, dass die Liste noch gefüllt wird (jede PDF wird einzeln geöffnet)
        ordnername = os.path.basename(path.rstrip("\\/")) or path
        laufende_phase = aktivitaet.phase(f"Lese Ordner „{ordnername}\"…")
        laufende_phase.__enter__()
        gelesen = 0
        ohne_datum = {}  # Position in file_data_list -> Pfad: PDFs ohne gespeichertes Dokumentdatum
        mails_weg = index_manager.mails_ausgeblendet(self.app) and not ordnername.startswith("0_")
        try:
            dateien = [e for e in os.scandir(path)
                       if e.is_file() and not e.name.startswith('.') and not ist_versteckte_systemdatei(e)]
            # Titel/Tags/Daten aus dem Index, solange die Datei unverändert ist - sonst (und ohne
            # Index) wird das PDF wie früher selbst gelesen
            aus_index = index_manager.metadaten_sicher(
                self.app, [e.path for e in dateien if e.name.lower().endswith(".pdf")],
                lambda n, gesamt: (laufende_phase.melde(f"Lese Ordner „{ordnername}\" ({n} Dateien)…"),
                                   aktivitaet.atme()))
            for entry in dateien:
                gelesen += 1
                if gelesen % 5 == 0 and len(aus_index) < len(dateien):
                    laufende_phase.melde(f"Lese Ordner „{ordnername}\" ({gelesen} Dateien)…")
                    aktivitaet.atme()
                file_date = ""
                titel = ""
                raw_keywords = ""
                sortable_date = "00000000"
                is_untouched = False
                jahr = None
                scan_embedded = ""
                erfasst_roh = ""
                creation_date_raw = ""

                if entry.name.lower().endswith(".pdf"):
                    meta = aus_index.get(entry.path) or PDFHandler.get_metadata(entry.path)
                    if mails_weg and meta.get("KID_Richtung"):
                        continue
                    titel = meta.get("title", "")
                    raw_keywords = meta.get("keywords", "")
                    scan_embedded = meta.get("KID_ScanZeitpunkt", "")
                    erfasst_roh = meta.get("KID_Erfasst", "")
                    creation_date_raw = meta.get("creationDate", "")

                    kid_date = meta.get("KID_DokumentenDatum", "") if meta else ""

                    # Noch nie von uns bearbeitet: weder Titel noch Tags noch Dokumentdatum gesetzt.
                    is_untouched = not titel and not raw_keywords and not kid_date

                    if kid_date:
                        nums = self.PATTERN_NUMBERS.findall(kid_date)
                        if len(nums) >= 3:
                            if len(nums[0]) == 4:
                                y, m, d = nums[0], nums[1], nums[2]
                            else:
                                d, m, y = nums[0], nums[1], nums[2]
                            file_date = f"{int(d):02d}.{int(m):02d}.{y}"
                            sortable_date = f"{y}{int(m):02d}{int(d):02d}"
                            jahr = int(y)
                        else:
                            file_date = kid_date

                if not file_date:
                    if entry.name.lower().endswith(".pdf"):
                        ohne_datum[len(file_data_list)] = entry.path
                    mtime = os.path.getmtime(entry.path)
                    dt_obj = datetime.datetime.fromtimestamp(mtime)
                    file_date = dt_obj.strftime("%d.%m.%Y")
                    sortable_date = dt_obj.strftime("%Y%m%d")
                    jahr = dt_obj.year

                if sortable_date == "00000000":
                    try:
                        nums = self.PATTERN_NUMBERS.findall(file_date)
                        if len(nums) >= 3:
                            sortable_date = f"{nums[2]}{int(nums[1]):02d}{int(nums[0]):02d}" if len(nums[0]) != 4 else f"{nums[0]}{int(nums[1]):02d}{int(nums[2]):02d}"
                            if jahr is None:
                                jahr = int(nums[0]) if len(nums[0]) == 4 else int(nums[2])
                    except (ValueError, IndexError):
                        sortable_date = "00000000"

                if not titel:
                    titel = entry.name

                splitted_tags = [t.strip() for t in raw_keywords.replace(";", ",").split(",") if t.strip()]
                for tag in splitted_tags:
                    global_tag_counts[tag] = global_tag_counts.get(tag, 0) + 1

                rel_path = os.path.relpath(entry.path, self.app.master_folder)
                scan_zeit = scan_date.format_scan_timestamp(entry.path, creation_date_raw=creation_date_raw, embedded=scan_embedded)
                # Textqualität nur lesen, wenn die Spalte sichtbar ist (ein zweiter
                # PDF-Zugriff je Datei - bei ausgeblendeter Spalte gespart)
                qualitaet = ""
                if qualitaet_sichtbar and entry.name.lower().endswith(".pdf"):
                    qualitaet = formatiere_textqualitaet(PDFHandler.get_textqualitaet(entry.path))
                file_data_list.append((sortable_date, file_date, titel, splitted_tags, entry.name, rel_path, is_untouched, jahr, scan_zeit, qualitaet,
                                       scan_date.erfasst_anzeige(erfasst_roh, scan_zeit)))
            # Ohne gespeichertes Datum: das aus dem Seitentext vermutete statt des Datei-Datums
            # (Download-/Kopiertag), gemerkt im Index - FALLSTRICKE #86
            vermutet = index_manager.vermutete_daten_sicher(
                self.app, list(ohne_datum.values()),
                lambda n, gesamt: (laufende_phase.melde(f"Lese Dokumentdaten „{ordnername}\" ({n}/{gesamt})…"),
                                   aktivitaet.atme()))
            for i, pfad in ohne_datum.items():
                liste = index_manager.als_listendatum(vermutet.get(pfad))
                if liste:
                    zeile = list(file_data_list[i])
                    zeile[1], zeile[0], zeile[7] = liste
                    file_data_list[i] = tuple(zeile)
        except PermissionError:
            pass
        finally:
            laufende_phase.__exit__(None, None, None)

        file_data_list.sort(key=lambda x: x[0], reverse=True)
        # Standard-Sortierung nach dem Neuaufbau ist Datum absteigend — Spaltenkopf-Anzeige angleichen
        UIUtils.set_sort_indicator(self.app.tree_files, "datum", True)

        for sortable_date, file_date, titel, splitted_tags, name, rel_path, is_untouched, jahr, scan_zeit, qualitaet, erfasst in file_data_list:
            if splitted_tags:
                splitted_tags.sort(key=lambda t: global_tag_counts.get(t, 0), reverse=True)
                sorted_tags_str = ", ".join(splitted_tags)
            else:
                sorted_tags_str = "---"

            # Jahr wird direkt bei der Datums-Ermittlung oben mitgeführt (statt später erneut
            # per Regex aus dem formatierten Text zurückgewonnen) - das war zuvor fehleranfällig
            # und ließ Dokumente bei jedem Parse-Fehler stumm auf Blau (row_even) zurückfallen.
            bg_tag = "row_even" if (jahr is None or jahr % 2 == 0) else "row_odd"

            row_tags = (bg_tag, "untouched") if is_untouched else (bg_tag,)

            # Überordner-Spalte: direkter Elternordner der Datei, im Root der Master-Ordnername
            parent_dir = os.path.dirname(rel_path)
            ordner = os.path.basename(parent_dir) if parent_dir else os.path.basename(self.app.master_folder)

            new_item = self.app.tree_files.insert("", "end", values=(file_date, titel, sorted_tags_str, name, rel_path, ordner, scan_zeit, qualitaet, erfasst), tags=row_tags)

            if old_selection_path and os.path.join(self.app.master_folder, rel_path) == old_selection_path:
                self.app.tree_files.selection_set(new_item)
                self.app.tree_files.focus(new_item)

        if not self.app.tree_files.selection():
            all_items = self.app.tree_files.get_children()
            if all_items:
                first_item = all_items[0]
                self.app.tree_files.selection_set(first_item)
                self.app.tree_files.focus(first_item)
                if hasattr(self.app, 'on_file_select'):
                    self.app.on_file_select(None)
            else:
                # Ordner ohne Dokumente: alles zurücksetzen, Vorschau samt Cache (FALLSTRICKE #43) und auch die
                # Eigenschaften mit „Original-Mail öffnen“: Die standen sonst noch da (FALLSTRICKE #111)
                self.app.leere_dokumentanzeige()
        else:
            if hasattr(self.app, 'on_file_select'):
                self.app.on_file_select(None)

    def on_tree_click(self, event):
        """Klickt der Nutzer exakt auf das Aufklapp-Dreieck, wird nur der Öffnen/Schließen-Zustand umgeschaltet, ohne die Zeile zu selektieren."""
        # Ein echter Klick auf einen Ordner ist ausdrückliche Navigation: ein noch scharfes
        # Such-Schutzschild (gesetzt beim Klick auf einen Treffer, ohne dass ein automatisches
        # Ordner-Ereignis folgte) darf ihn nicht verschlucken (FALLSTRICKE #74).
        self.ignore_next_select = False
        element = self.app.tree_folders.identify_element(event.x, event.y)
        if element == "Treeitem.indicator":
            item_id = self.app.tree_folders.identify_row(event.y)
            if item_id:
                is_open = self.app.tree_folders.item(item_id, "open")
                self.app.tree_folders.item(item_id, open=not is_open)
                return "break"

    def show_folder_context_menu(self, event):
        """Öffnet das Rechtsklick-Kontextmenü für Ordner; deaktiviert 'Neuer Unterordner'/'Umbenennen' für den Papierkorb-Systemordner."""
        iid = self.app.tree_folders.identify_row(event.y)
        if iid:
            self.app.tree_folders.selection_set(iid)
            values = self.app.tree_folders.item(iid, "values")
            if values and app_paths.is_trash_path(values[0], self.app.master_folder):
                self.app.folder_context_menu.entryconfig("Neuer Unterordner...", state=tk.DISABLED)
                self.app.folder_context_menu.entryconfig("Umbenennen (F2)", state=tk.DISABLED)
                self.app.folder_context_menu.entryconfig("Zusammenführen mit…", state=tk.DISABLED)
            else:
                self.app.folder_context_menu.entryconfig("Neuer Unterordner...", state=tk.NORMAL)
                self.app.folder_context_menu.entryconfig("Umbenennen (F2)", state=tk.NORMAL)
                self.app.folder_context_menu.entryconfig("Zusammenführen mit…", state=tk.NORMAL)
                
            self.app.folder_context_menu.tk_popup(event.x_root, event.y_root)

    def create_new_folder(self):
        selected = self.app.tree_folders.selection()
        if not selected: return
        parent_path = self.app.tree_folders.item(selected[0], "values")[0]
        
        new_name = UIUtils.ask_string("Neuer Ordner", "Name des neuen Ordners:", parent=self.app.root)
        if new_name:
            new_name = "".join(c for c in new_name if c not in r'\/:*?"<>|')
            new_path = os.path.join(parent_path, new_name)
            
            try:
                os.makedirs(new_path, exist_ok=True)
                self.refresh_folder_tree()
                self.app.logger.info(f"Neuer Ordner erstellt: {new_path}")
            except Exception as e:
                messagebox.showerror("Fehler", f"Konnte Ordner nicht erstellen:\n{e}")

    def rename_folder(self):
        """Benennt den ausgewählten Ordner um; schützt den Hauptordner und den Papierkorb-Systemordner explizit vor Umbenennung."""
        selected = self.app.tree_folders.selection()
        if not selected: return
        old_path = self.app.tree_folders.item(selected[0], "values")[0]

        if old_path == self.app.master_folder or app_paths.is_trash_path(old_path, self.app.master_folder):
            messagebox.showwarning("Hinweis", "Dieser System- oder Basisordner kann nicht umbenannt werden.")
            return

        old_name = os.path.basename(old_path)
        parent_path = os.path.dirname(old_path)
        
        new_name = UIUtils.ask_string("Ordner umbenennen", f"Neuer Name für '{old_name}':", initialvalue=old_name, parent=self.app.root)
        if new_name and new_name != old_name:
            new_name = "".join(c for c in new_name if c not in r'\/:*?"<>|')
            new_path = os.path.join(parent_path, new_name)
            
            if os.path.exists(new_path):
                messagebox.showerror("Fehler", "Ein Ordner mit diesem Namen existiert bereits.")
                return
                
            try:
                self.app.is_moving = True
                os.rename(old_path, new_path)
                self.refresh_folder_tree()
                self.app.logger.info(f"Ordner umbenannt: {old_path} -> {new_path}")
            except Exception as e:
                messagebox.showerror("Fehler", f"Konnte Ordner nicht umbenennen. Ist noch eine Datei darin geöffnet?\n{e}")
            finally:
                self.app.is_moving = False

    def merge_folder(self):
        """
        Rechtsklick "Zusammenführen mit…" (Nutzerwunsch 03.09.2026): bestehenden
        Ordner-Wildwuchs direkt im Baum aufräumen. Alle Dateien des gewählten Ordners
        wandern in einen vorhandenen Ziel-Ordner, der leere Ordner verschwindet, und
        die Zuordnung wird als Absender-Alias gemerkt (dieselbe Mechanik wie der
        Zielordner-Klick in der Ablage-Vorschau) - künftige Dokumente dieses Absenders
        landen damit gleich im Ziel-Ordner.
        """
        # Bewusster Griff ins Tool-Modul: die Ordner-Auswahl mit Tipp-Filter wohnt beim
        # Vorschau-Tool und soll nur einmal existieren (kein Import-Ringschluss).
        from tools.auto_filer import ZielordnerDialog

        selected = self.app.tree_folders.selection()
        if not selected:
            return
        quelle_abs = self.app.tree_folders.item(selected[0], "values")[0]
        master = self.app.master_folder
        name = os.path.basename(quelle_abs)
        if quelle_abs == master or app_paths.is_trash_path(quelle_abs, master):
            messagebox.showwarning("Hinweis", "Dieser System- oder Basisordner kann nicht zusammengeführt werden.")
            return
        try:
            eintraege = sorted(os.listdir(quelle_abs))
        except OSError as e:
            messagebox.showerror("Zusammenführen", f"Ordner nicht lesbar:\n{e}")
            return
        if any(os.path.isdir(os.path.join(quelle_abs, e)) for e in eintraege):
            messagebox.showwarning(
                "Zusammenführen",
                f"'{name}' enthält Unterordner und wird deshalb nicht angefasst.\n"
                "Bitte zuerst die Unterordner auflösen oder einzeln zusammenführen.")
            return

        quelle_rel = os.path.relpath(quelle_abs, master)
        ordnerliste = [o for o in auto_pilot.sammle_ordnerliste(master) if o != quelle_rel]
        dialog = ZielordnerDialog(
            self.app.root, ordnerliste, "", name, mit_reichweite=False,
            ueberschrift=f"'{name}' zusammenführen mit welchem vorhandenen Ordner?")
        self.app.root.wait_window(dialog)
        ziel_rel = dialog.ergebnis
        if not ziel_rel or ziel_rel == quelle_rel:
            return
        ziel_abs = os.path.join(master, ziel_rel)
        if not os.path.isdir(ziel_abs):
            # Zusammenführen heißt: in einen VORHANDENEN Ordner - für neue Namen gibt es "Umbenennen"
            messagebox.showwarning("Zusammenführen", f"'{ziel_rel}' ist kein vorhandener Ordner.")
            return
        if not bestaetigung.frage(
                "Zusammenführen",
                f"{len(eintraege)} Datei(en) aus '{name}' nach '{ziel_rel}' verschieben und den "
                f"leeren Ordner löschen?\n\n'{name}' wird zusätzlich als Zuordnung gemerkt "
                "(einsehbar in der Ablage-Vorschau unter 'Gemerkte Zuordnungen…')."):
            return

        self.app.is_moving = True
        fehler = 0
        try:
            for datei in eintraege:
                q = os.path.join(quelle_abs, datei)
                z = auto_pilot._naechster_freier_pfad(os.path.join(ziel_abs, datei))
                try:
                    self.app.file_ops._verschiebe_ohne_duplikat(q, z)
                    if hasattr(self.app, "tool_manager"):
                        self.app.tool_manager.notify_file_moved(q, z)
                except OSError as e:
                    fehler += 1
                    self.app.logger.error(f"Zusammenführen: {q} -> {z} fehlgeschlagen: {e}")
            try:
                os.rmdir(quelle_abs)   # klappt nur, wenn wirklich leer - sonst bleibt er stehen
            except OSError:
                pass
        finally:
            self.app.is_moving = False

        try:
            ordner_aliase.speichere_alias(master, name, ziel_rel)
        except OSError as e:
            messagebox.showwarning("Zusammenführen",
                                   f"Dateien sind verschoben, aber die Zuordnung konnte nicht gemerkt werden:\n{e}")
        self.refresh_folder_tree()
        self._select_and_open_path(ziel_abs)
        self.app.logger.info(f"Ordner zusammengeführt: {quelle_rel} -> {ziel_rel} ({len(eintraege) - fehler} Datei(en))")
        if fehler:
            messagebox.showwarning("Zusammenführen",
                                   f"{fehler} Datei(en) konnten nicht verschoben werden (siehe Log) - "
                                   f"'{name}' bleibt deshalb bestehen.")

    def open_folder_in_explorer(self):
        selected = self.app.tree_folders.selection()
        if not selected: return
        path = self.app.tree_folders.item(selected[0], "values")[0]
        
        if os.path.exists(path):
            if platform.system() == "Windows":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.call(["open", path])
            else:
                subprocess.call(["xdg-open", path])

    def expand_all_folders(self):
        self._set_tree_state(self.app.tree_folders.get_children(), True)

    def collapse_all_folders(self):
        self._set_tree_state(self.app.tree_folders.get_children(), False)

    def _set_tree_state(self, items, open_state):
        for item in items:
            self.app.tree_folders.item(item, open=open_state)
            self._set_tree_state(self.app.tree_folders.get_children(item), open_state)