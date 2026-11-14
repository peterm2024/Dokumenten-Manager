import os
import tkinter as tk
import aktivitaet
from tkinter import messagebox

from pdf_handler import PDFHandler


def tags_bereinigen(text):
    """Tags-Feld für das PDF aufräumen: leere Einträge raus, einheitlich „, “ - nach einem
    übernommenen Vorschlag stand sonst „…, Testament,“ im PDF (Fund T0.4, 25.10.2026)."""
    return ", ".join(t.strip() for t in (text or "").split(",") if t.strip())


def _gleicher_pfad(a, b):
    """Pfadvergleich unabhängig von der Schrägstrich-Richtung und Groß-/Kleinschreibung (Windows)."""
    return bool(a and b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def datum_zum_mitspeichern(datum_feld, pfad, eingabe):
    """
    Welches Dokumentdatum beim Speichern von Titel/Tags mit ins PDF soll (FALLSTRICKE #86):
    das Datum im Datumsfeld, wenn das Feld zu genau diesem Dokument gehört, gültig ist und
    vom gespeicherten abweicht - also ein nur vorgeschlagenes oder getipptes, aber nicht per
    Return bestätigtes Datum. Der Notbehelf „Datei-Datum“ (Download-/Kopiertag) wird nie
    geschrieben, solange er unverändert im Feld steht.
    :param datum_feld: {"pfad", "gespeichert", "notbehelf"} aus der Vorschau oder None
    :return: 'JJJJ-MM-TT' oder None
    """
    if not datum_feld or not _gleicher_pfad(datum_feld.get("pfad"), pfad):
        return None
    datum = PDFHandler.normalize_date_input(eingabe or "")
    if not datum or datum == datum_feld.get("gespeichert") or datum == datum_feld.get("notbehelf"):
        return None
    return datum


class SaveManager:
    """
    Controller für das Speichern von Titel/Tags in die PDF-Metadaten.
    Bündelt die beiden Eingänge in denselben Workflow: den manuellen
    Speichern-Button (save_selected) und das debouncte Auto-Save
    (toggle/trigger/flush/_perform_autosave).
    """

    def __init__(self, app):
        """
        Initialisiert den Speicher-Controller.
        :param app: Referenz auf die Hauptinstanz (DokumentenVerwaltung).
        """
        self.app = app
        # Merkt sich, ob im Titel-/Tag-Feld eine noch ungespeicherte Änderung ansteht.
        self._dirty = False

    def mark_clean(self):
        """Setzt den Änderungs-Merker zurück — z.B. nachdem beim Dateiwechsel die Felder programmatisch neu befüllt wurden (das ist keine Nutzer-Änderung)."""
        self._dirty = False

    def hat_offene_aenderung(self):
        """
        True, solange eine Eingabe noch nicht in der Datei gelandet ist (Dirty-Flag oder
        laufender Auto-Save-Debounce-Timer). Die Watchdog-Vollautomatik fragt das ab und
        lässt die angezeigte Datei dann in Ruhe (FALLSTRICKE #54) — bloßes Anzeigen
        ohne Eingabe blockiert sie dagegen nicht.
        """
        return self._dirty or hasattr(self, "_autosave_timer")

    def mark_dirty(self):
        """Merkt eine ungespeicherte Änderung vor, OHNE den Auto-Save-Timer zu starten — für Felder, die erst bei expliziter Bestätigung (Return/Fokus-Verlust) speichern sollen."""
        self._dirty = True

    def commit_pending_edits(self, event=None):
        """Löst den Auto-Save aus, aber nur wenn tatsächlich eine ungespeicherte Änderung vorliegt (Bestätigung per Return oder Fokus-Verlust im Tags-Feld)."""
        if self._dirty:
            self.trigger_autosave()

    # ==========================================
    # AUTO-SAVE (Debounce-Timer)
    # ==========================================
    def toggle_autosave(self):
        """
        Speichert die Autosave-Einstellung und (de)aktiviert den manuellen Speichern-Button entsprechend.
        Steht beim Einschalten noch eine ungespeicherte Änderung an (_dirty), wird diese sofort
        gespeichert — sonst müsste der Nutzer Auto-Save erst wieder ausschalten, um an den
        (deaktivierten) Speichern-Button zu kommen. Ohne offene Änderung wird bewusst NICHT
        gespeichert, damit das bloße Umschalten der Einstellung keine Datei anfasst.
        """
        self.app.config.set("autosave", self.app.autosave_var.get())
        if self.app.autosave_var.get():
            self.app.btn_save.config(state=tk.DISABLED)
            if self._dirty:
                self._perform_autosave()
        else:
            self.app.btn_save.config(state=tk.NORMAL)

    def trigger_autosave(self, event=None):
        """
        Merkt die Änderung vor (_dirty) und setzt einen 1-Sekunden-Debounce-Timer für das
        automatische Speichern; ein vorheriger Timer wird zuerst verworfen. Bei ausgeschaltetem
        Auto-Save bleibt nur der Änderungs-Merker gesetzt (für den manuellen Weg bzw. das
        Nachholen beim Einschalten von Auto-Save).
        """
        self._dirty = True
        if not getattr(self.app, 'autosave_var', None) or not self.app.autosave_var.get():
            return
        if hasattr(self, '_autosave_timer'):
            self.app.root.after_cancel(self._autosave_timer)
            delattr(self, '_autosave_timer')
        self._autosave_timer = self.app.root.after(1000, self._perform_autosave)

    def flush_pending(self):
        """
        Führt einen noch ausstehenden Auto-Save sofort aus — bevor beim Dateiwechsel
        die Feldinhalte überschrieben werden. Deckt zwei Fälle ab: einen laufenden
        Debounce-Timer UND eine noch unbestätigte Tags-Feld-Änderung (dirty ohne Timer,
        da das Tags-Feld erst bei Return/Fokus-Verlust speichert) — Letztere würde
        sonst beim Dateiwechsel stillschweigend verloren gehen.
        """
        if hasattr(self, '_autosave_timer'):
            self.app.root.after_cancel(self._autosave_timer)
            delattr(self, '_autosave_timer')
            self._perform_autosave()
        elif self._dirty and getattr(self.app, 'autosave_var', None) and self.app.autosave_var.get():
            self._perform_autosave()

    def _perform_autosave(self):
        """
        Speichert gezielt genau die Datei, die beim Auslösen von trigger_autosave aktiv war,
        mit den zu diesem Zeitpunkt eingegebenen Titel-/Tag-Feldwerten. Nutzt bewusst NICHT
        die aktuelle Baum-Auswahl wie save_selected, da sich diese bis zum Ablauf des
        Debounce-Timers geändert haben kann (z.B. durch eine Shift-Mehrfachauswahl) — sonst
        würden fremde Dokumente versehentlich mit den alten Feldwerten überschrieben.
        """
        if hasattr(self, '_autosave_timer'):
            delattr(self, '_autosave_timer')

        path = getattr(self.app, 'current_preview_path', None)
        if not path or not path.lower().endswith(".pdf"):
            return
        if not os.path.exists(path):
            # Live-Fund 06.09.2026: Die Datei wurde zwischen Eingabe und Debounce-Ablauf
            # verschoben (damals: Watchdog-Vollautomatik griff sich die angezeigte
            # Posteingang-Datei; der Dienst überspringt die inzwischen, aber Explorer &
            # Co. bleiben möglich). Stilles Aufgeben statt Fehler-Messagebox - die
            # Eingabe gehört zu einer Datei, die es an diesem Ort nicht mehr gibt.
            self.app.logger.warning(f"Auto-Save übersprungen - Datei wurde zwischenzeitlich verschoben: {path}")
            self._dirty = False
            return

        titel_val = self.app.entry_title.get().strip()
        tags_val = tags_bereinigen(self.app.entry_tags.get("1.0", tk.END))

        datum = self._feld_datum(path)

        self.app.is_saving = True

        # still=True: Fehler kommen als Rückgabewert und werden unten geloggt/zurückgesetzt -
        # ein modales Fehler-Popup mitten in der laufenden Eingabe wäre hier nur störend.
        with aktivitaet.phase(f"Speichere {os.path.basename(path)}…"):
            erfolg, msg = PDFHandler.save_metadata(path, titel_val, tags_val, still=True, datum=datum)
        if erfolg:
            self.app.logger.info(f"Metadaten automatisch gespeichert für: {path}")
            self._dirty = False
            self._datum_gespeichert(path, datum)

            # Zuletzt-benutzt-Tags aktualisieren
            tags_list = [t.strip() for t in tags_val.split(",") if t.strip()]
            self.app.tag_manager.add_recent_tags(tags_list)
            # add_recent_tags baut die "Zuletzt benutzt"-Einträge neu auf und verwirft dabei
            # deren TAG_ACTIVE-Markierung - ohne erneute Synchronisation verlor ein gerade
            # zugewiesenes Tag dort nach ~1s (Debounce) seine blaue Hervorhebung. Der manuelle
            # Speicherweg (_finish_save) macht denselben Aufruf bereits am Ende.
            self.app.tag_manager.sync_tag_tree_selection()

            # WICHTIG: Der stille Auto-Save baut das Grid bewusst NICHT neu auf, sondern
            # aktualisiert nur die betroffene Zeile direkt (wie save_manual_date beim Datum).
            # Ein voller Neuaufbau + Neuselektion würde das gerade angeklickte Dokument
            # und die Tag-Markierung im Baum stören (Grid-Rebuild verschluckt/koalesziert
            # das Auswahl-Event) - genau das war der "Markierung verschwindet"-Bug.
            rel_path = os.path.relpath(path, self.app.master_folder)
            for item in self.app.tree_files.get_children():
                if self.app.tree_files.item(item, "values")[4] == rel_path:
                    vals = list(self.app.tree_files.item(item, "values"))
                    if titel_val:
                        vals[1] = titel_val
                    vals[2] = ", ".join(tags_list) if tags_list else "---"
                    if datum:
                        jahr, monat, tag = datum.split("-")
                        vals[0] = f"{tag}.{monat}.{jahr}"
                    self.app.tree_files.item(item, values=vals)
                    break
        else:
            self.app.logger.error(f"Fehler beim automatischen Speichern für {path}: {msg}")
            # Ohne diesen Revert blieben Feld-Inhalt, Tag-Baum-Markierung UND (da der
            # Erfolgs-Zweig oben nicht läuft) auch die Dokumentenliste-Zeile unangetastet
            # auf dem NIE gespeicherten, optimistisch eingegebenen Stand stehen (z.B. bei
            # geschützten PDFs, siehe KONZEPT_PDF_ARTEN.md) - die Oberfläche zeigte damit
            # einen Zustand, der auf der Platte gar nicht existiert.
            self._revert_fields_to_disk(path)

        self.app.root.after(1500, lambda: setattr(self.app, 'is_saving', False))

    def datum_beim_verlassen(self, neuer_pfad):
        """
        Auto-Save an und Wechsel auf ein ANDERES Dokument: das vermutete (orange) oder getippte,
        aber nicht bestätigte Datum des bisherigen Dokuments ins PDF schreiben - wer weiterklickt,
        hat es gesehen (Peter 28.10.2026). Nie das Datei-Datum (datum_zum_mitspeichern). Ein
        Neuaufbau der Liste, der dasselbe Dokument wieder auswählt, zählt nicht als Verlassen.
        """
        if not (getattr(self.app, 'autosave_var', None) and self.app.autosave_var.get()):
            return
        feld = getattr(self.app, "datum_feld", None)
        if not feld or not hasattr(self.app, "date_entry") or _gleicher_pfad(feld.get("pfad"), neuer_pfad):
            return
        pfad = feld["pfad"]
        datum = datum_zum_mitspeichern(feld, pfad, self.app.date_entry.get())
        if not datum or not os.path.exists(pfad):
            return
        self.app.is_saving = True
        with aktivitaet.phase(f"Speichere Datum {os.path.basename(pfad)}…"):
            erfolg = PDFHandler.write_custom_metadata(pfad, {"KID_DokumentenDatum": datum}, still=True)
        self.app.root.after(1500, lambda: setattr(self.app, 'is_saving', False))
        if not erfolg:
            self.app.logger.warning(f"Dokumentdatum beim Wechsel nicht gespeichert: {pfad}")
            return
        feld["gespeichert"] = datum
        self.app.logger.info(f"Dokumentdatum {datum} beim Wechsel gespeichert für: {pfad}")
        rel_path = os.path.relpath(pfad, self.app.master_folder)
        for item in self.app.tree_files.get_children():
            if _gleicher_pfad(self.app.tree_files.item(item, "values")[4], rel_path):
                self.app.aktualisiere_datumszeile(item, datum)
                break

    def kennung_beim_anklicken(self, pfad):
        """
        Auto-Save an: Dokument-ID (und mit ihr den Scan-Zeitpunkt, _merge_kid_metadata) beim
        Anklicken einbrennen, falls sie fehlt - beides wird nie von Hand korrigiert, und so steht die
        ID gleich in den Eigenschaften statt erst nach dem ersten Speichern (Peter 28.10.2026).
        """
        if not (getattr(self.app, 'autosave_var', None) and self.app.autosave_var.get()):
            return
        if not pfad or not pfad.lower().endswith(".pdf") or not os.path.exists(pfad):
            return
        if PDFHandler.get_metadata(pfad).get("KID_ID"):
            return
        self.app.is_saving = True
        kid_id = PDFHandler.ensure_kid_id(pfad)
        self.app.root.after(1500, lambda: setattr(self.app, 'is_saving', False))
        if kid_id:
            self.app.logger.info(f"Dokument-ID {kid_id} beim Anklicken vergeben: {pfad}")

    def _feld_datum(self, path):
        """Das mitzuspeichernde Datum aus dem Datumsfeld (siehe datum_zum_mitspeichern) oder None."""
        if not hasattr(self.app, "date_entry"):
            return None
        return datum_zum_mitspeichern(getattr(self.app, "datum_feld", None), path, self.app.date_entry.get())

    def _datum_gespeichert(self, path, datum):
        """Nach erfolgreichem Mitspeichern: Feld gilt als gespeichert (schwarz statt grau)."""
        feld = getattr(self.app, "datum_feld", None)
        if not datum or not feld or not _gleicher_pfad(feld.get("pfad"), path):
            return
        feld["gespeichert"] = datum
        self.app.logger.info(f"Dokumentdatum {datum} mitgespeichert für: {path}")
        if PDFHandler.normalize_date_input(self.app.date_entry.get()) == datum:
            self.app.setze_datum_stil(vermutet=False)

    def _revert_fields_to_disk(self, path):
        """Setzt Titel-/Tags-Feld und die Tag-Baum-Hervorhebung nach einem fehlgeschlagenen Speichern auf den tatsächlichen (unveränderten) Dateiinhalt zurück."""
        meta = PDFHandler.get_metadata(path)
        self.app.entry_title.delete(0, tk.END)
        self.app.entry_title.insert(0, meta.get("title", ""))
        self.app.entry_tags.delete("1.0", tk.END)
        self.app.entry_tags.insert("1.0", meta.get("keywords", ""))
        self._dirty = False
        self.app.tag_manager.sync_tag_tree_selection()

    # ==========================================
    # MANUELLES SPEICHERN (Button / Strg+S)
    # ==========================================
    def save_selected(self, quiet=False):
        """
        Schreibt Titel/Tags für alle aktuell selektierten Dateien in die PDF-Metadaten
        (Titel nur für das primär selektierte Dokument), aktualisiert die Zuletzt-benutzt-Tags
        und stellt die Auswahl nach dem Neuaufbau des Grids wieder her.
        :param quiet: Unterdrückt Erfolgs-/Fehlermeldungen (z.B. beim automatischen Speichern).
        """
        if not getattr(self.app, 'current_preview_path', None) or not self.app.current_preview_path.lower().endswith(".pdf"):
            if not quiet:
                messagebox.showwarning("Hinweis", "Bitte wähle ein PDF aus.")
            return

        auswahl = self.app.tree_files.selection()
        if not auswahl:
            return

        tags_val = tags_bereinigen(self.app.entry_tags.get("1.0", tk.END))
        titel_val = self.app.entry_title.get().strip()

        self.app.is_saving = True
        selected_paths = [self.app.tree_files.item(item, "values")[4] for item in auswahl]

        for sel_id in auswahl:
            row_values = self.app.tree_files.item(sel_id, "values")
            rel_path = row_values[4]
            abs_path = os.path.join(self.app.master_folder, rel_path)

            # Titel nur für das primär selektierte Dokument übernehmen
            current_title = titel_val if sel_id == auswahl[0] else row_values[1]

            # Datum nur für das angezeigte Dokument - nur dessen Datumsfeld sieht man
            datum = self._feld_datum(abs_path)
            with aktivitaet.phase(f"Speichere {os.path.basename(abs_path)}…"):
                erfolg, msg = PDFHandler.save_metadata(abs_path, current_title, tags_val, datum=datum)
            if erfolg:
                self.app.logger.info(f"Metadaten gespeichert für: {abs_path}")
                self._datum_gespeichert(abs_path, datum)
            else:
                self.app.logger.error(f"Fehler beim Speichern der Metadaten für {abs_path}: {msg}")
                if not quiet: messagebox.showerror("Fehler", msg)

        self._dirty = False
        self._finish_save(tags_val, selected_paths)

    def ergaenze_tags_fuer_auswahl(self, tags, entfernen=False):
        """
        Fügt allen markierten Dokumenten dieselben Tags HINZU (bzw. entfernt sie) —
        jedes Dokument behält dabei seine übrigen Tags und seinen Titel.

        Bewusst nicht über das Tags-Eingabefeld wie save_selected: Das Feld zeigt die
        Tags des primär markierten Dokuments, und es zu schreiben würde die individuellen
        Tags aller anderen platt machen. Hier wird pro Datei gelesen, geändert und
        zurückgeschrieben (Nutzerwunsch 01.09.2026: mehrere Dokumente markieren und per
        Doppelklick EIN Tag vergeben).

        :param tags: Liste der Tag-Texte (inkl. mitzuziehender Oberkategorien).
        :param entfernen: True = Tags abziehen statt hinzufügen.
        :return: Anzahl tatsächlich geänderter Dokumente.
        """
        auswahl = self.app.tree_files.selection()
        if not auswahl or not tags:
            return 0

        self.app.is_saving = True
        selected_paths = [self.app.tree_files.item(item, "values")[4] for item in auswahl]
        geaendert = 0
        try:
            for rel_path in selected_paths:
                abs_path = os.path.join(self.app.master_folder, rel_path)
                if not abs_path.lower().endswith(".pdf"):
                    continue
                meta = PDFHandler.get_metadata(abs_path) or {}
                vorhanden = [t.strip() for t in (meta.get("keywords") or "").split(",") if t.strip()]
                klein = {t.lower() for t in vorhanden}
                neu = list(vorhanden)
                if entfernen:
                    neu = [t for t in neu if t.lower() not in {x.lower() for x in tags}]
                else:
                    neu.extend(t for t in tags if t.lower() not in klein)
                if neu == vorhanden:
                    continue
                with aktivitaet.phase(f"Speichere {os.path.basename(abs_path)}…"):
                    erfolg, msg = PDFHandler.save_metadata(abs_path, meta.get("title", ""), ", ".join(neu))
                if erfolg:
                    geaendert += 1
                    self.app.logger.info(
                        f"Tags {'entfernt' if entfernen else 'ergänzt'} für: {abs_path} ({', '.join(tags)})")
                else:
                    self.app.logger.error(f"Fehler beim Tag-Schreiben für {abs_path}: {msg}")
        finally:
            self._dirty = False
            if not entfernen:
                self.app.tag_manager.add_recent_tags(tags)
            self._reload_and_restore(selected_paths)
            self.app.root.after(1500, lambda: setattr(self.app, 'is_saving', False))
        return geaendert

    # ==========================================
    # GEMEINSAMER ABSCHLUSS BEIDER SPEICHERWEGE
    # ==========================================
    def _finish_save(self, tags_val, selected_paths):
        """
        Gemeinsamer Abschluss von Auto-Save und manuellem Speichern:
        aktualisiert die Zuletzt-benutzt-Tags, lädt das Dokumenten-Grid neu,
        stellt die vorherige Auswahl wieder her und löst die is_saving-Sperre
        (Watchdog-Muting) nach 1,5 Sekunden wieder.
        :param tags_val: Der komplette Tag-String aus dem Eingabefeld.
        :param selected_paths: Relative Pfade der vor dem Speichern selektierten Zeilen.
        """
        tags_list = [t.strip() for t in tags_val.split(",") if t.strip()]
        self.app.tag_manager.add_recent_tags(tags_list)
        self._reload_and_restore(selected_paths)
        self.app.root.after(1500, lambda: setattr(self.app, 'is_saving', False))

    def _reload_and_restore(self, selected_paths):
        """
        Lädt die aktive Ansicht neu und stellt die vorherige Auswahl wieder her.
        Von _finish_save und von ergaenze_tags_fuer_auswahl gemeinsam benutzt.
        """
        # Die gerade aktive Ansicht neu laden: bei aktiver Suche die Suchergebnisse,
        # sonst den Ordner. on_folder_select(None) allein würde bei aktiver Suche das
        # Such-Schutzschild umgehen (greift nur bei event != None) und stattdessen den
        # Ordner ins Grid laden - dadurch verschwand die gerade gesetzte Tag-Markierung.
        if self.app.search_manager.is_search_active():
            self.app.search_manager.apply_filters()
        else:
            self.app.folder_manager.on_folder_select(None)

        # Vorherige Auswahl in einem einzigen Aufruf wiederherstellen (statt pro Zeile
        # selection_add: das würde <<TreeviewSelect>> mehrfach feuern und dabei
        # kurzzeitig die von on_folder_select() automatisch gesetzte Erstauswahl zeigen).
        matching_items = [item for item in self.app.tree_files.get_children() if self.app.tree_files.item(item, "values")[4] in selected_paths]
        if matching_items:
            self.app.tree_files.selection_set(matching_items)

        # Tag-Markierung im Baum explizit neu setzen: Der Grid-Neuaufbau löst zwar per
        # Auswahl ein <<TreeviewSelect>> aus, das Tkinter aber koaleszieren/verschlucken
        # kann - dann bliebe die Markierung des gerade zugewiesenen Tags aus. Das Tag-Feld
        # ist zu diesem Zeitpunkt bereits korrekt befüllt, der Aufruf ist idempotent.
        self.app.tag_manager.sync_tag_tree_selection()
