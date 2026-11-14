"""
Tool "Dokument neu erfassen".

Analysiert pro Seite, ob eine neue OCR-Textebene zurück ins PDF geschrieben werden
kann (siehe KONZEPT_PDF_ARTEN.md Abschnitt 4), und führt das auf Wunsch aus:
nur echte Scan-Seiten (vollseitiges Bild + höchstens unsichtbare OCR-Ebene) werden
bearbeitet, Digital-/Misch-Seiten bleiben grundsätzlich unangetastet. Verschlüsselte,
schreibgeschützte und signierte PDFs werden komplett verweigert.

Sicherheitsnetz vor jedem Schreibversuch: eine Kopie der Originaldatei wandert in
den Papierkorb der Sammlung (siehe app_paths.trash_dir), PDFHandler.recapture_document
lehnt zusätzlich ein unplausibel gewachsenes Ergebnis selbst ab (siehe dort).
"""

import os
import shutil
import threading
import tkinter as tk
import tkinter.messagebox as mb
import bestaetigung
from datetime import datetime
from tkinter import ttk

import app_paths
import aktivitaet
from tools.base_tool import BaseTool, ToolContext
from pdf_handler import PDFHandler
from text_quality import textqualitaet_prozent
from ui_utils import UIUtils, ProgressDialog

# Anzeigetexte je Seiten-Typ aus PDFHandler.classify_pages
TYP_BESCHREIBUNG = {
    "scan": "Scan-Seite — wird neu erfasst",
    "digital": "Digital-Seite — bleibt unangetastet",
    "misch": "Misch-Seite — wird übersprungen",
    "leer": "Leere Seite — wird übersprungen",
}

# Schutz-Status aus PDFHandler.get_write_protection, der das Tool komplett sperrt
SPERRENDE_SCHUTZARTEN = ("verschlüsselt", "schreibgeschützt", "signiert")


def baue_zusammenfassung(pages, protection):
    """
    Baut den Zusammenfassungs-Satz unter der Seitentabelle (reine Funktion, damit
    die Entscheidungslogik ohne Tkinter testbar ist).
    """
    if protection in SPERRENDE_SCHUTZARTEN:
        return (f"Dieses PDF ist {protection} — das Neu-Erfassen wird verweigert, "
                "die Datei bleibt unverändert.")
    if not pages:
        return "Das PDF konnte nicht analysiert werden (beschädigt oder nicht lesbar?)."
    scan_seiten = sum(1 for p in pages if p["typ"] == "scan")
    if scan_seiten == 0:
        return (f"Keine der {len(pages)} Seiten ist eine echte Scan-Seite — "
                "es gibt hier nichts neu zu erfassen.")
    return (f"{scan_seiten} von {len(pages)} Seiten sind echte Scan-Seiten "
            "und würden neu erfasst.")


def sicherungskopie_pfad(pdf_path, master_folder):
    """
    Baut einen kollisionsfreien Zielpfad im Papierkorb der Sammlung für die
    Sicherungskopie vor dem Neu-Erfassen (Namensschema wie file_operations.py's
    Wiederherstellen: '_N' anhängen statt überschreiben).
    """
    trash = app_paths.trash_dir(master_folder)
    name_only, ext = os.path.splitext(os.path.basename(pdf_path))
    zeitstempel = datetime.now().strftime("%Y%m%d-%H%M%S")
    ziel = os.path.join(trash, f"{name_only}_vor_neuerfassung_{zeitstempel}{ext}")
    counter = 1
    basis = ziel
    while os.path.exists(ziel):
        ziel = basis[:-len(ext)] + f"_{counter}" + ext
        counter += 1
    return ziel


class DocumentRecaptureTool(BaseTool):
    def __init__(self):
        self.window = None

    @property
    def name(self) -> str:
        return "Dokument neu erfassen"

    @property
    def menu_group(self) -> str:
        return "KI-Helfer"

    @property
    def menu_label(self) -> str:
        return "Dokument neu erfassen (Textebene erneuern)…"

    @property
    def absicht(self) -> str:
        return ("Manche Scanner liefern eine kaputte Textebene (Kauderwelsch, verdrehte Positionen): dann findet die Suche nichts und der Datums-Marker sitzt daneben. Neu erfassen repariert das lokal; das Seitenbild bleibt unverändert.")

    @property
    def description(self) -> str:
        return "Prüft und erneuert die OCR-Textebene echter Scan-Seiten."

    @property
    def menu_hooks(self) -> list:
        return ["context_menu", "main_menu"]

    @property
    def required_input(self) -> str:
        return "single_file"

    def execute(self, context: ToolContext) -> bool:
        pdf_path = context.selected_files[0]
        if not pdf_path.lower().endswith(".pdf"):
            mb.showinfo("Hinweis", "Bitte ein PDF auswählen.")
            return False
        if self.window and self.window.winfo_exists():
            self.window.destroy()
        self.window = RecaptureAnalysisWindow(context.app, pdf_path)
        return True

    def on_selection_changed(self, context: ToolContext) -> None:
        """Wie beim PDF-Inspektor: bei genau EINER neu ausgewählten PDF wechselt das offene Fenster live dorthin, statt das alte Dokument stehen zu lassen."""
        if not (self.window and self.window.winfo_exists()):
            return
        if len(context.selected_files) == 1 and context.selected_files[0].lower().endswith(".pdf"):
            self.window.wechsle_dokument(context.selected_files[0])

    def on_file_moved(self, old_path: str, new_path: str) -> None:
        """Zieht den Pfad eines offenen Analyse-Fensters nach, wenn die Datei verschoben/umbenannt wird."""
        if not (self.window and self.window.winfo_exists()):
            return
        if os.path.normcase(self.window.pdf_path) == os.path.normcase(old_path):
            self.window.update_path(new_path)


class RecaptureAnalysisWindow(tk.Toplevel):
    """Analyse-Vorschau + Ausführung: Schutz-Status, Seitentabelle, Zusammenfassung, Aktion für EIN PDF."""

    def __init__(self, app, pdf_path):
        super().__init__(app.root)
        self.app = app
        self.pdf_path = pdf_path
        self._verarbeitung_laeuft = False
        UIUtils.position_near_mouse(self, UIUtils.px(self, 720), UIUtils.px(self, 470))
        self.transient(app.root)
        self._setup_ui()
        self._analysiere()

    def _setup_ui(self):
        self.label_schutz = ttk.Label(self, anchor="w", foreground="firebrick")
        # wird nur bei geschützten PDFs per pack() eingeblendet (siehe _analysiere)

        columns = ("seite", "einstufung", "abdeckung", "textebene", "qualitaet")
        frame = ttk.Frame(self)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 5))
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="none")
        self.tree.heading("seite", text="Seite")
        self.tree.heading("einstufung", text="Einstufung")
        self.tree.heading("abdeckung", text="Bild-Abdeckung")
        self.tree.heading("textebene", text="Vorhandener Text")
        self.tree.heading("qualitaet", text="Text-Qualität")
        self.tree.column("seite", width=UIUtils.px(self, 50), anchor="center")
        self.tree.column("einstufung", width=UIUtils.px(self, 260))
        self.tree.column("abdeckung", width=UIUtils.px(self, 100), anchor="center")
        self.tree.column("textebene", width=UIUtils.px(self, 140))
        self.tree.column("qualitaet", width=UIUtils.px(self, 100), anchor="center")
        self.tree.tag_configure("scan", background="#e6f4e6")     # grünlich: wird bearbeitet
        self.tree.tag_configure("digital", background="#f0f0f0")  # neutral: bleibt unangetastet
        self.tree.tag_configure("misch", background="#fdf3d7")    # gelblich: wird übersprungen
        scroll = ttk.Scrollbar(frame, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.label_zusammenfassung = ttk.Label(self, anchor="w", wraplength=UIUtils.px(self, 640))
        self.label_zusammenfassung.pack(fill=tk.X, padx=10, pady=(0, 5))

        hinweis = ttk.Label(
            self, anchor="w", foreground="gray40", wraplength=UIUtils.px(self, 640),
            text=("Text-Qualität ist ein grober Schätzwert (Anteil unauffälliger Wörter) "
                  "nur für Scan-Seiten - keine Garantie, aber ein schneller Blick, ob sich "
                  "das Neu-Erfassen gelohnt hat. Vor jedem Lauf wird automatisch eine "
                  "Sicherungskopie der Originaldatei im Papierkorb der Sammlung angelegt."))
        hinweis.pack(fill=tk.X, padx=10, pady=(0, 5))

        button_frame = ttk.Frame(self)
        button_frame.pack(pady=(0, 10))
        self.btn_ausfuehren = ttk.Button(button_frame, text="Jetzt neu erfassen",
                                          command=self._starte_neuerfassung)
        self.btn_ausfuehren.pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="Schließen", command=self.destroy).pack(side=tk.LEFT, padx=5)

    def update_path(self, new_path):
        """Wird von on_file_moved gerufen - Pfad und Titel nachziehen, Analyse bleibt gültig (Inhalt unverändert)."""
        self.pdf_path = new_path
        self.title(f"Dokument neu erfassen — {os.path.basename(new_path)}")

    def wechsle_dokument(self, new_path):
        """
        Wechselt die Analyse auf ein anderes, neu in der Hauptliste angeklicktes
        Dokument (siehe DocumentRecaptureTool.on_selection_changed). Läuft gerade ein
        Neu-Erfassen im Hintergrund, bleibt dessen Zielpfad davon unberührt (siehe
        _starte_neuerfassung - arbeitet mit einer lokalen Kopie von self.pdf_path);
        nur die sichtbare Analyse wechselt, der "Jetzt neu erfassen"-Button bleibt
        bis zum Abschluss des laufenden Vorgangs gesperrt (siehe _analysiere).
        """
        if new_path == self.pdf_path:
            return
        self.pdf_path = new_path
        self._analysiere()

    def _analysiere(self):
        self.title(f"Dokument neu erfassen — {os.path.basename(self.pdf_path)}")
        self.label_schutz.pack_forget()
        for item in self.tree.get_children():
            self.tree.delete(item)

        protection = PDFHandler.get_write_protection(self.pdf_path)
        pages = PDFHandler.classify_pages(self.pdf_path)
        self._letzte_pages = pages
        self._letzter_schutz = protection

        if protection in SPERRENDE_SCHUTZARTEN:
            self.label_schutz.config(text=f"⚠ Dieses PDF ist {protection}.")
            self.label_schutz.pack(fill=tk.X, padx=10, pady=(10, 0), before=self.tree.master)

        for eintrag in pages:
            typ = eintrag["typ"]
            if eintrag["sichtbarer_text"] and eintrag["unsichtbarer_text"]:
                text_info = "sichtbar + OCR-Ebene"
            elif eintrag["sichtbarer_text"]:
                text_info = "sichtbar"
            elif eintrag["unsichtbarer_text"]:
                text_info = "OCR-Ebene (unsichtbar)"
            else:
                text_info = "keiner"
            if typ == "scan":
                qualitaet = textqualitaet_prozent(eintrag["text"])
                qualitaet_info = f"{qualitaet} %" if qualitaet is not None else "–"
            else:
                qualitaet_info = "–"
            self.tree.insert("", tk.END, tags=(typ,), values=(
                eintrag["seite"],
                TYP_BESCHREIBUNG.get(typ, typ),
                f"{eintrag['bild_abdeckung'] * 100:.0f} %",
                text_info,
                qualitaet_info,
            ))

        self.label_zusammenfassung.config(text=baue_zusammenfassung(pages, protection))

        scan_seiten = sum(1 for p in pages if p["typ"] == "scan")
        kann_ausfuehren = (protection not in SPERRENDE_SCHUTZARTEN and scan_seiten > 0
                            and not self._verarbeitung_laeuft)
        self.btn_ausfuehren.config(state=tk.NORMAL if kann_ausfuehren else tk.DISABLED)

    def _starte_neuerfassung(self):
        tessdata_path = app_paths.tessdata_dir()
        if not os.path.isdir(tessdata_path):
            mb.showwarning(
                "Tesseract-Sprachdaten fehlen",
                "Für das Neu-Erfassen werden die Tesseract-Sprachdaten benötigt "
                "(siehe README: tessdata/deu.traineddata).", parent=self)
            return

        # Lokale Kopie: das laufende Neu-Erfassen darf NICHT dem live wechselbaren
        # self.pdf_path folgen, falls der Nutzer währenddessen ein anderes Dokument
        # anklickt (siehe wechsle_dokument) - sonst würde die Sicherungskopie zum
        # einen, das Neu-Erfassen aber zum anderen Dokument gehören.
        zielpfad = self.pdf_path
        scan_seiten = sum(1 for p in self._letzte_pages if p["typ"] == "scan")
        if not bestaetigung.frage(
                "Dokument neu erfassen",
                f"{scan_seiten} Scan-Seite(n) werden neu per OCR gelesen, die alte "
                "Textebene wird ersetzt. Eine Sicherungskopie der Originaldatei wandert "
                "vorher in den Papierkorb der Sammlung. Jetzt starten?", parent=self):
            return

        try:
            backup_path = sicherungskopie_pfad(zielpfad, self.app.master_folder)
            os.makedirs(os.path.dirname(backup_path), exist_ok=True)
            shutil.copy2(zielpfad, backup_path)
        except OSError as e:
            mb.showerror("Fehler", f"Sicherungskopie fehlgeschlagen — Neu-Erfassen abgebrochen:\n{e}", parent=self)
            return

        self._verarbeitung_laeuft = True
        self.btn_ausfuehren.config(state=tk.DISABLED)
        self.app.is_moving = True
        dialog = ProgressDialog(self, "Dokument neu erfassen", f"Wird verarbeitet: {os.path.basename(zielpfad)}")

        def worker():
            name = os.path.basename(zielpfad)
            with aktivitaet.phase(f"Neu erfassen: {name}…") as p:
                def fortschritt(d, t):
                    p.melde(f"Neu erfassen: {name} Seite {d}/{t}…")
                    self.after(0, dialog.update_progress, d, t)
                ergebnis = PDFHandler.recapture_document(
                    zielpfad, tessdata_path,
                    on_progress=fortschritt,
                    should_stop=dialog.should_stop,
                )
            self.after(0, self._neuerfassung_fertig, dialog, ergebnis, backup_path, zielpfad)

        threading.Thread(target=worker, daemon=True).start()

    def _neuerfassung_fertig(self, dialog, ergebnis, backup_path, zielpfad):
        dialog.destroy()
        self._verarbeitung_laeuft = False
        # Wie tools/pdf_editor.py: Watchdog erst nach Windows-Dateifreigabe wieder aufwecken
        self.app.root.after(1500, lambda: setattr(self.app, 'is_moving', False))

        erfolg, meldung, _bearbeitete = ergebnis
        if hasattr(self.app, 'logger') and self.app.logger:
            self.app.logger.info(f"Dokument neu erfassen ({zielpfad}): {meldung}")

        if erfolg:
            # Spalte "Textqualität" der Dokumentenliste sofort nachziehen (Nutzerwunsch
            # 11.09.2026) - VOR der Messagebox, damit der neue Wert schon dasteht
            if hasattr(self.app, 'folder_manager') and hasattr(self.app.folder_manager, 'aktualisiere_textqualitaet'):
                self.app.folder_manager.aktualisiere_textqualitaet(zielpfad)
            mb.showinfo("Fertig", meldung, parent=self)
            if getattr(self.app, 'current_preview_path', None) == zielpfad and hasattr(self.app, 'preview_manager'):
                self.app.preview_manager.verwerfe_cache()
                self.app.preview_manager.update_preview()
        else:
            mb.showwarning(
                "Nicht abgeschlossen",
                f"{meldung}\n\nDie Sicherungskopie liegt weiterhin im Papierkorb:\n{backup_path}",
                parent=self)

        # Falls der Nutzer währenddessen zu einem ANDEREN Dokument gewechselt hat
        # (siehe wechsle_dokument), gehört die sichtbare Tabelle nicht mehr zu
        # zielpfad - dann nur den Button wieder freigeben (via erneutem _analysiere
        # auf dem AKTUELL gezeigten Dokument), statt die falschen Daten anzuzeigen.
        if self.winfo_exists():
            self._analysiere()
