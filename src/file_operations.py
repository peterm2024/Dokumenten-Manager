import os
import shutil
import platform
import subprocess
import time
import tkinter as tk
from tkinter import messagebox, filedialog
import bestaetigung
import aktivitaet

import app_paths
import papierkorb_herkunft
from pdf_handler import PDFHandler
from ui_utils import UIUtils

# Alt-Taste im event.state: Windows meldet Alt als 0x20000 (0x0008 ist dort NumLock), X11 als Mod1.
ALT_MASKE = 0x20000 if platform.system() == "Windows" else 0x0008
TAG_TRANSFER_HINWEIS = "Tags übertragen: beim Ziehen auf ein Dokument die Alt-Taste gedrückt halten"



def vereinige_tags(ziel, quelle):
    """
    Tags für die Alt-Übertragung: die des Ziels in ihrer Reihenfolge, dahinter die neuen der
    Quelle in deren Reihenfolge; Groß-/Kleinschreibung zählt beim Doppelt-Prüfen nicht. Früher
    lief das über eine Menge und würfelte die Reihenfolge im PDF durcheinander (Fund T0.7, 25.10.2026).
    """
    ergebnis, gesehen = [], set()
    for text in (ziel, quelle):
        for tag in (t.strip() for t in (text or "").split(",")):
            if tag and tag != "---" and tag.lower() not in gesehen:
                gesehen.add(tag.lower())
                ergebnis.append(tag)
    return ergebnis


def neue_tags(ziel, quelle):
    """Die Tags der Quelle, die das Ziel noch nicht hat (Groß-/Kleinschreibung egal), in Quell-Reihenfolge."""
    vorhanden = {t.strip().lower() for t in (ziel or "").split(",") if t.strip()}
    return [t for t in vereinige_tags("", quelle) if t.lower() not in vorhanden]


try:
    import fitz  # noqa: F401 -- nur zur Verfügbarkeitsprüfung importiert (siehe HAS_FITZ)
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

class FileOperations:
    def __init__(self, app):
        """
        Initialisiert den Datei-Operations-Controller.
        :param app: Referenz auf die Hauptinstanz (DokumentenVerwaltung).
        """
        self.app = app
        self.current_drop_target = None       # Merkt sich den leuchtenden Ziel-Ordner
        self.current_file_drop_target = None  # Merkt sich das leuchtende Ziel-Dokument
        # Läuft gerade ein Drag, der auf einer ZEILE begonnen hat? Nur dann darf das
        # Loslassen etwas auslösen (FALLSTRICKE #61: Spaltenbreite ziehen endete als Drop).
        self._drag_aktiv = False

    def _notify_tools_moved(self, old_path, new_path):
        """Meldet eine Datei-Verschiebung/Umbenennung an alle Tools weiter (z.B. damit ein offener Mini-PDF-Editor seinen Speicherpfad nachzieht)."""
        if hasattr(self.app, 'tool_manager'):
            self.app.tool_manager.notify_file_moved(old_path, new_path)

    def _nachbar_zeile(self, entfernte_items):
        """
        Liefert die Zeile, die nach dem Entfernen von `entfernte_items` an deren Stelle
        "nachrutscht": die nächste nicht entfernte Zeile darunter, sonst die darüber, sonst None.
        """
        alle = list(self.app.tree_files.get_children())
        entfernt = set(entfernte_items)
        positionen = [alle.index(i) for i in entfernte_items if i in alle]
        if not positionen:
            return None
        for i in range(max(positionen) + 1, len(alle)):
            if alle[i] not in entfernt:
                return alle[i]
        for i in range(min(positionen) - 1, -1, -1):
            if alle[i] not in entfernt:
                return alle[i]
        return None

    def _merke_nachbar_als_naechste_auswahl(self, entfernte_items):
        """
        Sorgt dafür, dass nach einem Verschieben/Löschen die nachrutschende Zeile markiert
        und angezeigt wird (Nutzerwunsch 30.08.2026) - statt dass die Auswahl auf die erste
        Zeile springt. Nutzt den bestehenden Mechanismus von folder_manager.on_folder_select:
        das Grid selektiert beim Neuaufbau die Zeile, deren Pfad in current_preview_path
        steht - also wird dort VOR der Datei-Operation der Nachbar eingetragen. Kein
        zusätzliches selection_set nötig (das würde ein zweites Rendern auslösen, FALLSTRICKE #8).
        """
        nachbar = self._nachbar_zeile(entfernte_items)
        if nachbar is None:
            return
        rel_path = self.app.tree_files.item(nachbar, "values")[4]
        self.app.current_preview_path = os.path.join(self.app.master_folder, rel_path)

    # ==========================================
    # VISUELLES FEEDBACK (DRAG & DROP)
    # ==========================================
    def _clear_folder_drop_target(self):
        if self.current_drop_target and self.app.tree_folders.exists(self.current_drop_target):
            old_tags = list(self.app.tree_folders.item(self.current_drop_target, "tags"))
            if "drop_target" in old_tags: 
                old_tags.remove("drop_target")
                self.app.tree_folders.item(self.current_drop_target, tags=old_tags)
        self.current_drop_target = None

    def _clear_file_drop_target(self):
        if self.current_file_drop_target and self.app.tree_files.exists(self.current_file_drop_target):
            old_tags = list(self.app.tree_files.item(self.current_file_drop_target, "tags"))
            if "file_drop_target" in old_tags: 
                old_tags.remove("file_drop_target")
                self.app.tree_files.item(self.current_file_drop_target, tags=old_tags)
        self.current_file_drop_target = None

    def on_folder_drag_motion(self, event):
        item = self.app.tree_folders.identify_row(event.y)
        if item != self.current_drop_target:
            self._clear_folder_drop_target()
            if item:
                tags = list(self.app.tree_folders.item(item, "tags"))
                if "drop_target" not in tags:
                    tags.append("drop_target")
                    self.app.tree_folders.item(item, tags=tags)
                self.current_drop_target = item

    def on_file_drag_motion(self, event):
        item = self.app.tree_files.identify_row(event.y)
        if item != self.current_file_drop_target:
            self._clear_file_drop_target()
            if item:
                tags = list(self.app.tree_files.item(item, "tags"))
                if "file_drop_target" not in tags:
                    tags.append("file_drop_target")
                    self.app.tree_files.item(item, tags=tags)
                self.current_file_drop_target = item

    def on_drag_leave(self, event):
        self._clear_folder_drop_target()
        self._clear_file_drop_target()

    # ==========================================
    # DRAG & DROP EVENT-HANDLER (START / BEWEGUNG / STOPP)
    # ==========================================
    def on_drag_start(self, event):
        """Startet den Drag-Vorgang und erzeugt das visuelle Feedback (schwebendes Fenster). Klick in den leeren Bereich hebt die Auswahl auf."""
        self._drag_start_x = event.x_root
        self._drag_start_y = event.y_root
        self._drag_aktiv = False

        # STRG-/SHIFT-Klicks komplett der Standard-Mehrfachauswahl von Tkinter
        # überlassen: das eigene selection_set unten würde die bestehende Auswahl
        # ersetzen, wodurch STRG-Klick (Toggle) sogar invertiert würde.
        if event.state & 0x0005:  # 0x0001 = Shift, 0x0004 = Control
            return

        item = self.app.tree_files.identify_row(event.y)

        # Klick ins Leere (unterhalb der letzten Zeile): Auswahl aufheben.
        # NUR bei region "nothing" - Klicks auf Kopfzeile/Trennlinien haben auch
        # keine Zeile, dürfen die Auswahl aber nicht anfassen (Sortier-Klick!).
        if not item and self.app.tree_files.identify_region(event.x, event.y) == "nothing":
            self.app.tree_files.selection_remove(*self.app.tree_files.selection())
            return

        if item:
            self.app.tree_files.selection_set(item)
            # Erst ab hier ist es ein Drag: Der Druck lag auf einer Zeile. Druck auf
            # Kopfzeile oder Spalten-Trennlinie (Spaltenbreite ziehen!) setzt das Flag
            # nicht - das Loslassen darf dann weder verschieben noch Tags übertragen,
            # egal wo die Maus landet (Nutzerfund 11.09.2026, FALLSTRICKE #61).
            self._drag_aktiv = True

            # --- Visuelles Feedback: Schwebendes Label erstellen ---
            try:
                file_name = self.app.tree_files.item(item, "values")[3]
                
                self.drag_window = tk.Toplevel(self.app.root)
                self.drag_window.overrideredirect(True) # Entfernt den Windows-Rahmen
                self.drag_window.attributes("-alpha", 0.85) # Leicht transparent
                self.drag_window.attributes("-topmost", True) # Immer im Vordergrund
                
                self._drag_label = tk.Label(self.drag_window, text=f"📄 {file_name}", bg="#0078D7", fg="white",
                                            font=("Segoe UI", 9, "bold"), relief="flat", padx=8, pady=4)
                self._drag_label.pack()
                self._drag_text = f"📄 {file_name}"
                
                # Direkt am Startpunkt der Maus platzieren
                x, y = self.app.root.winfo_pointerxy()
                self.drag_window.geometry(f"+{x+15}+{y+15}")
            except Exception:
                pass

    def on_drag_motion(self, event):
        """Verarbeitet die visuelle Hervorhebung und bewegt das schwebende Fenster."""
        if not getattr(self, "_drag_aktiv", False):
            return  # z.B. Spaltenbreite wird gezogen - kein Drag & Drop
        x, y = self.app.root.winfo_pointerxy()
        
        # --- Visuelles Feedback: Schwebendes Fenster der Maus folgen lassen ---
        if hasattr(self, 'drag_window') and self.drag_window.winfo_exists():
            self.drag_window.geometry(f"+{x+15}+{y+15}")
            
        widget = self.app.root.winfo_containing(x, y)

        if widget == self.app.tree_folders:
            rel_y = y - self.app.tree_folders.winfo_rooty()
            class MockEvent: y = rel_y
            self.on_folder_drag_motion(MockEvent())
            self._clear_file_drop_target()
            
        elif widget == self.app.tree_files:
            rel_y = y - self.app.tree_files.winfo_rooty()
            class MockEvent: y = rel_y
            self.on_file_drag_motion(MockEvent())
            self._clear_folder_drop_target()
            
        else:
            self._clear_folder_drop_target()
            self._clear_file_drop_target()

        # Schwebendes Fensterchen sagt VOR dem Loslassen, was passieren wird: Tags übertragen
        # gibt es seit 15.09.2026 nur noch mit gedrückter Alt-Taste (Fehlgriff-Schutz).
        self._drag_text_setzen("🏷 Tags übertragen →" if (event.state & ALT_MASKE and widget == self.app.tree_files)
                               else getattr(self, "_drag_text", ""))

    def _drag_text_setzen(self, text):
        lbl = getattr(self, "_drag_label", None)
        try:
            if lbl is not None and lbl.winfo_exists() and lbl.cget("text") != text:
                lbl.configure(text=text)
        except tk.TclError:
            pass

    def _hinweis_kurz(self, text, dauer_ms=5000):
        """Kurzer Hinweis in der Aktivitätsanzeige (Menüleiste), verschwindet von selbst."""
        token = aktivitaet.beginne(text)
        try:
            self.app.root.after(dauer_ms, lambda: aktivitaet.beende(token))
        except tk.TclError:
            aktivitaet.beende(token)

    def on_drag_stop(self, event):
        """Löst den eigentlichen Drop (Verschieben/Tag-Transfer) aus und räumt die UI auf."""
        # --- Visuelles Feedback: Schwebendes Fenster wieder löschen ---
        if hasattr(self, 'drag_window') and self.drag_window.winfo_exists():
            self.drag_window.destroy()

        # Kein Drag von einer Zeile aus (Kopfzeile, Trennlinie, STRG-Klick): nichts tun.
        # Vorher lief der Drop trotzdem - mit der ALTEN Auswahl als Quelle (FALLSTRICKE #61).
        if not getattr(self, "_drag_aktiv", False):
            self._clear_folder_drop_target()
            self._clear_file_drop_target()
            return
        self._drag_aktiv = False

        # --- FIX: Deadzone-Check mit den ECHTEN Event-Koordinaten von ButtonRelease-1 ---
        # on_file_drop() bekommt hier unten nur ein MockEvent (ohne x_root/y_root) übergeben,
        # weil identify_row() lediglich die y-Koordinate relativ zum Widget braucht. Dadurch
        # überspringt der interne Deadzone-Check in on_file_drop() seine Prüfung komplett.
        # Das genügte bisher meist trotzdem (Quelle==Ziel-Vergleich), außer wenn sich die
        # Zeilen zwischen Klick und Loslassen verschieben (z.B. Neusortierung durch Autosave) -
        # dann wird ein reiner Klick fälschlich als Drop auf eine andere Zeile interpretiert.
        # Deshalb hier VOR jedem Drop mit den echten Bildschirmkoordinaten prüfen.
        if hasattr(self, '_drag_start_x') and hasattr(self, '_drag_start_y'):
            move_x = abs(event.x_root - self._drag_start_x)
            move_y = abs(event.y_root - self._drag_start_y)
            if move_x <= 2 and move_y <= 2:
                self._clear_folder_drop_target()
                self._clear_file_drop_target()
                return  # Lautloser Abbruch: Es war nur ein Klick!

        x, y = self.app.root.winfo_pointerxy()
        widget = self.app.root.winfo_containing(x, y)

        if widget == self.app.tree_folders:
            rel_y = y - self.app.tree_folders.winfo_rooty()
            class MockEvent: y = rel_y
            self.on_file_drop(MockEvent(), is_folder_drop=True)
            
        elif widget == self.app.tree_files:
            rel_y = y - self.app.tree_files.winfo_rooty()
            class MockEvent: y = rel_y
            self.on_file_drop(MockEvent(), is_folder_drop=False, tags_erlaubt=bool(event.state & ALT_MASKE))
            
        self._clear_folder_drop_target()
        self._clear_file_drop_target()

    # ==========================================
    # HAUPT-DRAG-&-DROP LOGIK
    # ==========================================
    def on_file_drop(self, event, is_folder_drop=False, tags_erlaubt=False):
        """
        Wertet das Ende eines Drag & Drop-Vorgangs aus: verschiebt die Datei in einen Zielordner
        oder überträgt bei einem Drop auf eine andere PDF-Datei deren Tags (Union ohne Duplikate) -
        Letzteres nur mit `tags_erlaubt` (Alt-Taste beim Loslassen, seit 15.09.2026: ein
        versehentlicher Drop auf die Nachbarzeile änderte sonst still die Metadaten); ohne Alt
        gibt es statt dessen einen kurzen Hinweis in der Aktivitätsanzeige.
        Bricht bei minimaler Mausbewegung (<= 2px) lautlos ab, um einen normalen Klick nicht als
        Drop misszuverstehen (siehe FALLSTRICKE #13 "Zitter-Klick"), und erzwingt vor dem Verschieben
        per gc.collect()/sleep die Freigabe des Windows-Datei-Locks von PyMuPDF (siehe FALLSTRICKE #1).
        """
        # --- FIX: Deadzone-Check mit MockEvent-Schutz ---
        if hasattr(self, '_drag_start_x') and hasattr(self, '_drag_start_y'):
            # Wir prüfen, ob es ein echtes Maus-Event ist (MockEvents haben kein x_root)
            if hasattr(event, 'x_root') and hasattr(event, 'y_root'):
                move_x = abs(event.x_root - self._drag_start_x)
                move_y = abs(event.y_root - self._drag_start_y)
                
                if move_x <= 2 and move_y <= 2:
                    self._clear_folder_drop_target()
                    self._clear_file_drop_target()
                    return # Lautloser Abbruch: Es war nur ein Klick!
        # ---------------------------------------------------------

        self._clear_folder_drop_target()
        self._clear_file_drop_target()
        
        selection = self.app.tree_files.selection()
        if not selection: return
        
        source_item = selection[0]
        source_rel_path = self.app.tree_files.item(source_item, "values")[4]
        source_path = os.path.join(self.app.master_folder, source_rel_path)
        
        # Sichern der Metadaten für den Tag-Transfer (Hier öffnet und schließt PyMuPDF die Datei)
        try:
            meta = PDFHandler.get_metadata(source_path)
            source_tags = meta.get("keywords", "")
        except Exception:
            source_tags = ""

        # --- FIX: Windows File-Lock aufheben ---
        import gc
        import time
        gc.collect()      # Zwingt Python, alte Datei-Griffe (PyMuPDF) sofort aus dem RAM zu werfen
        time.sleep(0.1)   # Gibt Windows 100ms Zeit, die Datei physisch freizugeben
        # ---------------------------------------

        self.app.is_moving = True

        try:
            if is_folder_drop:
                # --- Fall 1: Datei in Ordner verschieben ---
                target_item = self.app.tree_folders.identify_row(event.y)
                if not target_item: return
                
                target_path = self.app.tree_folders.item(target_item, "values")[0]
                if app_paths.is_trash_path(target_path, self.app.master_folder):
                    import tkinter.messagebox as messagebox
                    messagebox.showwarning("Hinweis", "Bitte lösche Dateien über die 'Entf'-Taste oder das Rechtsklick-Menü.")
                    return
                    
                target_file_path = os.path.join(target_path, os.path.basename(source_path))
                
                if os.path.dirname(source_path) == target_path:
                    return

                if os.path.exists(target_file_path):
                    import tkinter.messagebox as messagebox
                    if not messagebox.askyesno("Überschreiben", "Eine Datei mit diesem Namen existiert dort bereits. Überschreiben?"):
                        return
                        
                suche_aktiv = self.app.search_manager.is_search_active()
                if not suche_aktiv:
                    self._merke_nachbar_als_naechste_auswahl([source_item])
                import shutil
                shutil.move(source_path, target_file_path)
                self.app.logger.info(f"Datei verschoben: {source_path} -> {target_file_path}")
                self._notify_tools_moved(source_path, target_file_path)
                
                # Ordnerbaum (Datei-Anzahl) neu aufbauen - der Aufklapp-Zustand bleibt seit
                # FALLSTRICKE #34 zentral in refresh_folder_tree erhalten; nur die
                # Selektion muss der Aufrufer wiederherstellen (siehe FALLSTRICKE #31).
                current_sel = self.app.tree_folders.selection()
                selected_path = self.app.tree_folders.item(current_sel[0], "values")[0] if current_sel else None
                self.app.folder_manager.refresh_folder_tree()
                if suche_aktiv:
                    # Aus der Trefferliste verschoben: die Suche bleibt stehen (Peter 25.10.2026 -
                    # vorher wechselte die Ansicht in den Ordner und die Suche war weg). Ordner nur
                    # still wieder markieren, Treffer neu aufbauen; das verschobene Dokument bleibt
                    # markiert, jetzt mit seinem neuen Ordner.
                    if selected_path:
                        self.app.folder_manager._select_and_open_path(selected_path, laden=False)
                    werte = list(self.app.tree_files.item(source_item, "values"))
                    werte[4] = os.path.relpath(target_file_path, self.app.master_folder)
                    self.app.tree_files.item(source_item, values=werte)
                    self.app.search_manager.apply_filters()
                elif selected_path:
                    self.app.folder_manager._select_and_open_path(selected_path)
                else:
                    self.app.folder_manager.on_folder_select(None)
                
            else:
                # --- Fall 2: Datei auf Datei droppen (Direkter Tag-Transfer) ---
                target_item = self.app.tree_files.identify_row(event.y)
                if not target_item or target_item == source_item: return
                if not tags_erlaubt:
                    self._hinweis_kurz(TAG_TRANSFER_HINWEIS)
                    return
                
                target_rel_path = self.app.tree_files.item(target_item, "values")[4]
                target_abs = os.path.join(self.app.master_folder, target_rel_path)
                
                import tkinter.messagebox as messagebox
                if not (source_path.lower().endswith(".pdf") and target_abs.lower().endswith(".pdf")):
                    messagebox.showerror("Fehler", "Tag-Transfer ist nur bei zwei PDF-Dateien möglich.")
                    return

                # Nichts zu übertragen: kurzer Hinweis wie bei der gelungenen Übertragung, kein blockierendes Fenster
                # (Peter 07.11.2026; im Release-Check blieb es unbemerkt offen und schluckte die nächsten Tasten)
                if not source_tags:
                    self._hinweis_kurz("Keine Tags übertragen: Das gezogene Dokument hat keine Tags")
                    return
                
                target_meta = PDFHandler.get_metadata(target_abs)
                target_tags = target_meta.get("keywords", "")
                # Rückmeldung statt Stille (Peter 28.10.2026: „kann die Tags nicht übertragen“ -
                # das Ziel hatte sie alle schon, der Drop schrieb unbemerkt dasselbe zurück)
                hinzu = neue_tags(target_tags, source_tags)
                if not hinzu:
                    self._hinweis_kurz("Keine Tags übertragen: Das Ziel hat sie schon alle "
                                       f"({', '.join(vereinige_tags('', source_tags))})")
                    return

                custom_dict = {"keywords": ", ".join(vereinige_tags(target_tags, source_tags))}
                
                if target_meta.get("KID_DokumentenDatum"):
                    custom_dict["KID_DokumentenDatum"] = target_meta["KID_DokumentenDatum"]
                    
                gc.collect()
                time.sleep(0.1)
                
                if PDFHandler.write_custom_metadata(target_abs, custom_dict):
                    self.app.logger.info(f"Tags übertragen: {source_path} -> {target_abs} ({', '.join(hinzu)})")
                    self._hinweis_kurz(f"Tags übertragen: {', '.join(hinzu)}")
                    # Zielzeile direkt nachziehen: in einer Trefferliste baut on_folder_select nichts neu,
                    # die Zeile zeigte die alten Tags - und das Tags-Feld wird beim Anklicken AUS der Zeile
                    # gefüllt, Auto-Save hätte sie zurückgeschrieben (Peter 28.10.2026)
                    werte = list(self.app.tree_files.item(target_item, "values"))
                    werte[2] = custom_dict["keywords"] or "---"
                    self.app.tree_files.item(target_item, values=werte)
                    if not self.app.search_manager.is_search_active():
                        self.app.folder_manager.on_folder_select(None)
                    
        except Exception as e:
            self.app.logger.error(f"Fehler bei Drag & Drop: {e}")
            import tkinter.messagebox as messagebox
            messagebox.showerror("Fehler", f"Aktion fehlgeschlagen:\n{e}")
        finally:
            self.app.is_moving = False

    # ==========================================
    # DATEI OPERATIONEN (Hinzufügen, Löschen, Umbenennen)
    # ==========================================
    def add_files_dialog(self):
        """Öffnet einen Datei-Auswahldialog und kopiert die gewählten PDFs in den aktuell markierten Ordner (Datum wird dabei automatisch vorgeschlagen, siehe _copy_single_file)."""
        selected_folders = self.app.tree_folders.selection()
        if not selected_folders:
            messagebox.showinfo("Hinweis", "Bitte wähle zuerst einen Zielordner aus.")
            return
            
        target_folder = self.app.tree_folders.item(selected_folders[0], "values")[0]
        
        file_paths = filedialog.askopenfilenames(
            title="Dateien hinzufügen",
            filetypes=[("PDF Dokumente", "*.pdf")],
            parent=self.app.root
        )
        
        if file_paths:
            self.app.is_moving = True
            try:
                for path in file_paths:
                    self._copy_single_file(path, target_folder)
                self.app.folder_manager.on_folder_select(None)
                self.app.logger.info(f"{len(file_paths)} Dateien in {target_folder} importiert.")
            except Exception as e:
                messagebox.showerror("Kopier-Fehler", f"Ein Fehler ist aufgetreten:\n{e}")
            finally:
                self.app.is_moving = False

    def _copy_single_file(self, source_path, target_folder):
        """Kopiert eine Datei und extrahiert automatisch das Datum."""
        filename = os.path.basename(source_path)
        dest_path = os.path.join(target_folder, filename)
        
        # Bei Namenskonflikten hochzählen
        counter = 1
        name_only, ext = os.path.splitext(filename)
        while os.path.exists(dest_path):
            dest_path = os.path.join(target_folder, f"{name_only}_{counter}{ext}")
            counter += 1
            
        shutil.copy2(source_path, dest_path)
        
        if dest_path.lower().endswith(".pdf"):
            suggested_date = PDFHandler.suggest_document_date(dest_path)
            if suggested_date:
                PDFHandler.write_custom_metadata(dest_path, {"KID_DokumentenDatum": suggested_date})

    # Wiederholungsversuche gegen TRANSIENTE Windows-Datei-Sperren ([WinError 32]):
    # kurzzeitige Leser wie Virenscanner, der Windows-Indexdienst oder eine parallel
    # laufende zweite Programm-Instanz (deren Watchdog/Suchindex geänderte Dateien
    # nachliest) halten ein Handle oft nur Sekundenbruchteile - ein sofortiger,
    # einmaliger Move-Versuch scheitert dann unnötig (siehe FALLSTRICKE #27).
    MOVE_VERSUCHE = 3
    MOVE_WARTEZEIT_S = 0.3

    def _verschiebe_ohne_duplikat(self, quelle, ziel):
        """
        Wie shutil.move, aber robust gegen zwei Windows-Realitäten:

        1. KEINE stillen Datei-Duplikate bei einem fehlgeschlagenen Verschieben:
           shutil.move fällt bei einem os.rename()-Fehler (z.B. weil die Datei gerade
           von einem anderen Prozess gelesen wird, siehe FALLSTRICKE #27) intern auf
           Kopieren+Löschen zurück. Schlägt dabei NUR das Löschen der Quelle fehl
           (die Kopie am Ziel steht schon), blieben bisher zwei Kopien derselben Datei
           liegen, ohne dass die Fehlermeldung das erkennen ließ. Die überzählige
           Ziel-Kopie wird in diesem Fall wieder aufgeräumt.

        2. Wiederholungsversuche bei TRANSIENTEN Sperren ([WinError 32]): kurzlebige
           Leser (Virenscanner, zweite Programm-Instanz, Index-Nachlesen) geben die
           Datei meist nach Sekundenbruchteilen wieder frei - erst nach
           MOVE_VERSUCHE gescheiterten Anläufen wird der Fehler weitergereicht.
        """
        for versuch in range(1, self.MOVE_VERSUCHE + 1):
            try:
                shutil.move(quelle, ziel)
                return
            except OSError:
                if os.path.exists(ziel) and os.path.exists(quelle):
                    try:
                        os.remove(ziel)
                    except OSError:
                        pass
                if versuch >= self.MOVE_VERSUCHE:
                    raise
                time.sleep(self.MOVE_WARTEZEIT_S)

    @staticmethod
    def _freier_papierkorb_pfad(trash_dir, pfad):
        """Ziel im Papierkorb, das nichts überschreibt: shutil.move ersetzt eine gleichnamige Datei still
        (zwei „Rechnung.pdf“ aus verschiedenen Ordnern, FALLSTRICKE #104)."""
        stamm, endung = os.path.splitext(os.path.basename(pfad))
        ziel, n = os.path.join(trash_dir, stamm + endung), 1
        while os.path.exists(ziel):
            n += 1
            ziel = os.path.join(trash_dir, f"{stamm} ({n}){endung}")
        return ziel

    def in_papierkorb(self, pfade):
        """
        Verschiebt Dateien ohne Rückfrage und ohne Bezug zur Dateiliste in den Papierkorb, für Werkzeuge mit eigener
        Rückfrage (Mails importieren). Nur im Tk-Thread aufrufen.
        :return: (verschoben, fehlgeschlagen)
        """
        trash_dir = app_paths.trash_dir(self.app.master_folder)
        os.makedirs(trash_dir, exist_ok=True)
        verschoben = fehler = 0
        auswahl = self.app.tree_folders.selection()
        ordner = self.app.tree_folders.item(auswahl[0], "values")[0] if auswahl else None
        self.app.is_moving = True
        try:
            for pfad in pfade:
                ziel = self._freier_papierkorb_pfad(trash_dir, pfad)
                try:
                    self._verschiebe_ohne_duplikat(pfad, ziel)
                except OSError:
                    fehler += 1
                    continue
                papierkorb_herkunft.merke(self.app.master_folder, ziel, pfad)
                self._notify_tools_moved(pfad, ziel)
                verschoben += 1
            self.app.folder_manager.refresh_folder_tree()
            if ordner:
                self.app.folder_manager._select_and_open_path(ordner)
            else:
                self.app.folder_manager.on_folder_select(None)
        finally:
            self.app.is_moving = False
        return verschoben, fehler

    def delete_file(self, event=None):
        """Löscht endgültig, wenn der aktuell gezeigte Ordner der Papierkorb ist, sonst Soft-Delete: verschiebt die Auswahl in den Papierkorb-Ordner."""
        auswahl = self.app.tree_files.selection()
        if not auswahl: return

        # Papierkorb check
        selected_folder = self.app.tree_folders.selection()
        is_in_trash = False
        if selected_folder:
            folder_path = self.app.tree_folders.item(selected_folder[0], "values")[0]
            is_in_trash = app_paths.is_trash_path(folder_path, self.app.master_folder)

        files_to_delete = [
            (item, os.path.join(self.app.master_folder, self.app.tree_files.item(item, "values")[4])) 
            for item in auswahl
        ]

        if is_in_trash:
            # Endgültig löschen
            if messagebox.askyesno("Endgültig löschen", f"Möchtest du {len(files_to_delete)} Datei(en) unwiderruflich löschen?"):
                self._merke_nachbar_als_naechste_auswahl(list(auswahl))
                self.app.is_moving = True
                try:
                    for item, pfad in files_to_delete:
                        if os.path.exists(pfad):
                            os.remove(pfad)
                            papierkorb_herkunft.vergiss(self.app.master_folder, pfad)
                    self.app.folder_manager.on_folder_select(None)
                except Exception as e:
                    messagebox.showerror("Fehler", f"Konnte Datei nicht löschen:\n{e}")
                finally:
                    self.app.is_moving = False
        else:
            # In den Papierkorb verschieben
            if bestaetigung.frage("Löschen", f"Möchtest du {len(files_to_delete)} Datei(en) in den Papierkorb verschieben?"):
                trash_dir = app_paths.trash_dir(self.app.master_folder)
                os.makedirs(trash_dir, exist_ok=True)

                # Aktuell selektierten Ordner merken: refresh_folder_tree() baut den Baum
                # komplett neu auf und verwirft dabei die bisherige Selektion.
                current_folder_sel = self.app.tree_folders.selection()
                current_folder_path = self.app.tree_folders.item(current_folder_sel[0], "values")[0] if current_folder_sel else None

                self._merke_nachbar_als_naechste_auswahl(list(auswahl))
                self.app.is_moving = True
                try:
                    for item, pfad in files_to_delete:
                        if os.path.exists(pfad):
                            trash_target = self._freier_papierkorb_pfad(trash_dir, pfad)
                            self._verschiebe_ohne_duplikat(pfad, trash_target)
                            # Herkunftsordner merken - „Wiederherstellen“ legt die Datei dorthin zurück
                            papierkorb_herkunft.merke(self.app.master_folder, trash_target, pfad)
                            self._notify_tools_moved(pfad, trash_target)
                    self.app.folder_manager.refresh_folder_tree()
                    if current_folder_path:
                        self.app.folder_manager._select_and_open_path(current_folder_path)
                    else:
                        self.app.folder_manager.on_folder_select(None)
                except Exception as e:
                    messagebox.showerror(
                        "Fehler",
                        f"Verschieben in Papierkorb fehlgeschlagen:\n{e}\n\n"
                        "Falls die Datei 'von einem anderen Prozess verwendet' wird: Ist sie in "
                        "einem anderen Programm geöffnet — oder läuft der Dokumenten-Manager "
                        "versehentlich doppelt (z.B. zweimal aus VS Code gestartet)?")
                finally:
                    self.app.is_moving = False

    def rename_file(self, event=None):
        """Fragt einen neuen Dateinamen ab, entfernt unzulässige Windows-Sonderzeichen und stellt sicher, dass die Endung .pdf erhalten bleibt."""
        auswahl = self.app.tree_files.selection()
        if not auswahl: return

        item_id = auswahl[0]
        rel_path = self.app.tree_files.item(item_id, "values")[4]
        old_path = os.path.join(self.app.master_folder, rel_path)
        old_name = os.path.basename(old_path)
        parent_dir = os.path.dirname(old_path)
        
        new_name = UIUtils.ask_string("Datei umbenennen", f"Neuer Name für '{old_name}':", initialvalue=old_name, parent=self.app.root)
        
        if new_name and new_name != old_name:
            new_name = "".join(c for c in new_name if c not in r'\/:*?"<>|')
            if not new_name.lower().endswith(".pdf"):
                new_name += ".pdf"
                
            new_path = os.path.join(parent_dir, new_name)
            if os.path.exists(new_path):
                messagebox.showerror("Fehler", "Eine Datei mit diesem Namen existiert bereits.")
                return
                
            try:
                self.app.is_moving = True
                os.rename(old_path, new_path)
                self._notify_tools_moved(old_path, new_path)
                # Umbenannte Datei bleibt markiert (Fund T0.7, 25.10.2026: sprang auf die erste
                # Zeile) - gleicher Weg wie beim Verschieben: der Neuaufbau wählt current_preview_path
                self.app.current_preview_path = new_path
                self.app.folder_manager.on_folder_select(None)
                self.app.logger.info(f"Datei umbenannt: {old_path} -> {new_path}")
            except Exception as e:
                messagebox.showerror("Fehler", f"Umbenennen fehlgeschlagen. Ist die Datei noch geöffnet?\n{e}")
            finally:
                self.app.is_moving = False

    def restore_file(self):
        """
        Verschiebt die ausgewählten Papierkorb-Dateien zurück in ihren Herkunftsordner (beim Löschen
        gemerkt, papierkorb_herkunft.py; Peter 25.10.2026 - vorher immer in den Hauptordner), ohne
        gemerkten oder noch vorhandenen Ordner in den Hauptordner; hängt bei Namenskonflikten
        '_wiederhergestellt_N' an.
        """
        auswahl = self.app.tree_files.selection()
        if not auswahl: return

        # Aktuell selektierten Ordner merken: refresh_folder_tree() baut den Baum
        # komplett neu auf und verwirft dabei die bisherige Selektion.
        current_folder_sel = self.app.tree_folders.selection()
        current_folder_path = self.app.tree_folders.item(current_folder_sel[0], "values")[0] if current_folder_sel else None

        self._merke_nachbar_als_naechste_auswahl(list(auswahl))
        self.app.is_moving = True
        zielordner = []
        try:
            for item in auswahl:
                rel_path = self.app.tree_files.item(item, "values")[4]
                pfad = os.path.join(self.app.master_folder, rel_path)

                if os.path.exists(pfad):
                    # Zielordner: gemerkter Herkunftsordner, sonst der Hauptordner (Root)
                    ordner = papierkorb_herkunft.zielordner(self.app.master_folder, pfad)
                    name = papierkorb_herkunft.urspruenglicher_name(self.app.master_folder, pfad)
                    ziel_pfad = os.path.join(ordner, name)
                    counter = 1
                    name_only, ext = os.path.splitext(name)

                    while os.path.exists(ziel_pfad):
                        ziel_pfad = os.path.join(ordner, f"{name_only}_wiederhergestellt_{counter}{ext}")
                        counter += 1

                    self._verschiebe_ohne_duplikat(pfad, ziel_pfad)
                    papierkorb_herkunft.vergiss(self.app.master_folder, pfad)
                    self._notify_tools_moved(pfad, ziel_pfad)
                    name = os.path.basename(ordner.rstrip("\\/")) or ordner
                    if name not in zielordner:
                        zielordner.append(name)

            self.app.folder_manager.refresh_folder_tree()
            if current_folder_path:
                self.app.folder_manager._select_and_open_path(current_folder_path)
            else:
                self.app.folder_manager.on_folder_select(None)
            messagebox.showinfo("Erfolg", "Datei(en) wiederhergestellt nach: " + ", ".join(zielordner or ["Hauptordner"]))
        except Exception as e:
            messagebox.showerror(
                "Fehler",
                f"Wiederherstellen fehlgeschlagen:\n{e}\n\n"
                "Falls die Datei 'von einem anderen Prozess verwendet' wird: Ist sie in "
                "einem anderen Programm geöffnet — oder läuft der Dokumenten-Manager "
                "versehentlich doppelt (z.B. zweimal aus VS Code gestartet)?")
        finally:
            self.app.is_moving = False

    # ==========================================
    # TREEVIEW EVENT-HANDLER (DOPPELKLICK & KONTEXTMENÜ)
    # ==========================================
    def on_tree_double_click(self, event):
        """Löst Auto-Resize aus, wenn eine Spaltentrennlinie doppelt angeklickt wird, sonst wird die Datei im OS-Standardprogramm geöffnet."""
        region = self.app.tree_files.identify_region(event.x, event.y)
        if region == "separator":
            col_id = self.app.tree_files.identify_column(event.x)
            UIUtils.auto_resize_column(self.app.tree_files, col_id)
            return "break"
        elif region in ("tree", "cell"):
            row_id = self.app.tree_files.identify_row(event.y)
            if row_id:
                self.open_file_native()

    def show_context_menu(self, event):
        """Öffnet das Rechtsklick-Kontextmenü; erhält eine bestehende Mehrfachauswahl, statt sie zu überschreiben, und blendet Menüpunkte je nach Papierkorb-Status ein/aus."""
        iid = self.app.tree_files.identify_row(event.y)
        if iid:
            # --- FIX: Mehrfachauswahl für Tools erhalten! ---
            # Wenn die angeklickte Datei noch nicht markiert ist, markiere sie exklusiv.
            # Wenn sie aber Teil einer bestehenden Mehrfachauswahl ist, behalte alle bei!
            if iid not in self.app.tree_files.selection():
                self.app.tree_files.selection_set(iid)
            # ------------------------------------------------

            is_trash = app_paths.is_trash_path(self.app.tree_files.item(iid, "values")[4], self.app.master_folder)

            state_normal = tk.DISABLED if is_trash else tk.NORMAL
            state_trash = tk.NORMAL if is_trash else tk.DISABLED

            self.app.file_context_menu.entryconfig("Umbenennen (F2)", state=state_normal)
            self.app.file_context_menu.entryconfig("Löschen (Entf)", state=state_normal)
            self.app.file_context_menu.entryconfig("Wiederherstellen...", state=state_trash)

            self.app.file_context_menu.tk_popup(event.x_root, event.y_root)

    # ==========================================
    # EXTERNE PROGRAMME ÖFFNEN
    # ==========================================
    def open_in_explorer(self):
        """Öffnet den nativen Dateimanager und markiert die ausgewählte Datei."""
        import platform
        import subprocess
        import os

        auswahl = self.app.tree_files.selection()
        if not auswahl: return
        
        # 1. Relativen Pfad auslesen
        rel_path = self.app.tree_files.item(auswahl[0], "values")[4]
        
        # 2. FIX: Zwingend einen absoluten und systemkonformen Pfad erzeugen
        pfad = os.path.abspath(os.path.join(self.app.master_folder, rel_path))
        pfad = os.path.normpath(pfad)
        
        if not os.path.exists(pfad): return
        
        try:
            sys_name = platform.system()
            if sys_name == "Windows":
                # Explorer bekommt jetzt einen perfekten Pfad: C:\Ordner\Unterordner\Datei.pdf
                subprocess.Popen(['explorer', '/select,', pfad])
            elif sys_name == "Darwin":
                subprocess.Popen(['open', '-R', pfad])
            else:
                subprocess.Popen(['xdg-open', os.path.dirname(pfad)])
        except Exception as e:
            self.app.logger.error(f"Konnte Dateimanager nicht öffnen: {e}")

    def open_file_native(self, event=None):
        """Öffnet die Datei mit dem Standardprogramm (z.B. Adobe Reader)."""
        auswahl = self.app.tree_files.selection()
        if not auswahl: return
        
        pfad = os.path.join(self.app.master_folder, self.app.tree_files.item(auswahl[0], "values")[4])
        if not os.path.exists(pfad): return
        
        try:
            sys_name = platform.system()
            if sys_name == "Windows":
                os.startfile(pfad)
            elif sys_name == "Darwin":
                subprocess.call(["open", pfad])
            else: 
                subprocess.call(["xdg-open", pfad])
        except Exception as e:
            self.app.logger.error(f"Konnte Datei nicht öffnen: {e}")