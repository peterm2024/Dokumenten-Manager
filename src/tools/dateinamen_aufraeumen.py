"""
Tool "Dateinamen aufräumen" (Nutzerwunsch 11.09.2026, Stufe 2 der Dateinamen-Entschärfung):
Tabelle mit aktuellem Namen, bearbeitbarem Vorschlag aus Dokumentdatum + Titel und dem im
PDF gespeicherten Originalnamen. Umbenannt wird NUR, was ausdrücklich angehakt ist
(Standard: kein Haken); der bisherige Name wird dabei als Originalname eingebrannt.
"Originalnamen wiederherstellen" macht Fehlgriffe (z.B. der Vollautomatik) rückgängig.
Die Regeln selbst liegen in `dateinamen.py` (testbar ohne Tk).
"""
import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox as mb

import app_paths
import bestaetigung
import dateinamen
import ollama_client
from tools.ai_title_suggest import render_first_page_png
from tools.base_tool import BaseTool, ToolContext
from ui_utils import UIUtils


class DateinamenAufraeumenTool(BaseTool):
    def __init__(self):
        self.window = None

    @property
    def name(self) -> str:
        return "Dateinamen aufräumen"

    @property
    def menu_group(self) -> str:
        return "Aufräumen"

    @property
    def menu_label(self) -> str:
        return "Dateinamen aufräumen…"

    @property
    def absicht(self) -> str:
        return ("Dateinamen vom Scanner (Scan_0001.pdf) sagen nichts. Ein einheitliches JJJJMMTT_Titel.pdf macht den Ordner auch im Explorer lesbar; der bisherige Name bleibt als Originalname im PDF und ist wiederherstellbar.")

    @property
    def description(self) -> str:
        return ("Vorschläge 'JJJJMMTT_Titel.pdf' aus Datum und Titel; umbenannt wird nur, was angehakt ist. "
                "Originalnamen lassen sich wiederherstellen.")

    @property
    def menu_hooks(self) -> list:
        return ["main_menu", "context_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        master = getattr(context.app, "master_folder", "")
        if not master or not os.path.isdir(master):
            mb.showinfo("Hinweis", "Bitte zuerst einen Hauptordner wählen.")
            return False
        auswahl = [p for p in (context.selected_files or []) if p.lower().endswith(".pdf")]
        if self.window and self.window.winfo_exists():
            self.window.destroy()
        self.window = DateinamenFenster(context.app, auswahl)
        return True

    def on_file_moved(self, old_path, new_path):
        if self.window and self.window.winfo_exists():
            self.window.pfad_nachziehen(old_path, new_path)


def aktueller_ordner(app):
    """Der im Ordnerbaum markierte Ordner (absolut), sonst der Hauptordner."""
    try:
        sel = app.tree_folders.selection()
        if sel:
            werte = app.tree_folders.item(sel[0], "values")
            if werte and os.path.isdir(werte[0]):
                return werte[0]
    except Exception:
        pass
    return app.master_folder


class DateinamenFenster(tk.Toplevel):
    SPALTEN = ("check", "name", "titel", "vorschlag", "original", "ordner")

    def __init__(self, app, auswahl):
        super().__init__(app.root)
        UIUtils.werkzeugfenster(self, app.root)   # über KID, nicht modal (Peter 04.11.2026)
        self.app = app
        self.title("Dateinamen aufräumen")
        UIUtils.position_near_mouse(self, UIUtils.px(self, 1200), UIUtils.px(self, 600))
        self.minsize(UIUtils.px(self, 800), UIUtils.px(self, 400))
        self.zeilen = {}   # iid -> Zeile aus dateinamen.zeile_fuer + "markiert"
        self.auswahl = list(auswahl)
        self._ki_laeuft = False
        self.var_bereich = tk.StringVar(value="auswahl" if auswahl else "ordner")
        self.var_rekursiv = tk.BooleanVar(value=False)
        self._setup_ui()
        self._laden()
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    # ------------------------------------------------------------------ Aufbau
    def _setup_ui(self):
        kopf = ttk.Frame(self)
        kopf.pack(fill=tk.X, padx=10, pady=(10, 4))
        ttk.Label(kopf, text="Dateien:").pack(side=tk.LEFT)
        rb = ttk.Radiobutton(kopf, text=f"markierte ({len(self.auswahl)})", value="auswahl",
                             variable=self.var_bereich, command=self._laden)
        rb.pack(side=tk.LEFT, padx=(6, 0))
        if not self.auswahl:
            rb.state(["disabled"])
        ttk.Radiobutton(kopf, text="aktueller Ordner", value="ordner",
                        variable=self.var_bereich, command=self._laden).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Checkbutton(kopf, text="mit Unterordnern", variable=self.var_rekursiv,
                        command=self._laden).pack(side=tk.LEFT, padx=(12, 0))
        ttk.Button(kopf, text="Neu laden", command=self._laden).pack(side=tk.RIGHT)

        # Statuszeile und Knöpfe ZUERST und von unten packen: sie bleiben so auch dann im
        # Fenster, wenn die Tabelle mehr Platz verlangt, als da ist (Lehre aus dem Test-Wizard).
        buttons = ttk.Frame(self)
        buttons.pack(side=tk.BOTTOM, pady=(0, 10))
        self.btn_ki = ttk.Button(buttons, text="KI-Titel vorschlagen (markierte Zeilen)", command=self._ki_titel)
        self.btn_ki.pack(side=tk.LEFT, padx=4)
        ttk.Button(buttons, text="Abweichende Vorschläge anhaken", command=self._abweichende_anhaken).pack(side=tk.LEFT, padx=(16, 4))
        ttk.Button(buttons, text="Alle abwählen", command=self._alle_abwaehlen).pack(side=tk.LEFT, padx=4)
        ttk.Button(buttons, text="Angehakte umbenennen", command=self._umbenennen, style="Accent.TButton").pack(side=tk.LEFT, padx=(16, 4))
        ttk.Button(buttons, text="Originalnamen wiederherstellen (angehakte)", command=self._wiederherstellen).pack(side=tk.LEFT, padx=4)
        ttk.Button(buttons, text="Schließen", command=self.destroy).pack(side=tk.LEFT, padx=(16, 4))
        self.status = ttk.Label(self, anchor="w", foreground="gray40")
        self.status.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 5))

        rahmen = ttk.Frame(self)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        self.tree = ttk.Treeview(rahmen, columns=self.SPALTEN, show="headings", selectmode="extended")
        for col, text, width, stretch in (
            ("check", "✓", 32, False), ("name", "Aktueller Name", 260, True),
            ("titel", "Titel (PDF)", 220, True),
            ("vorschlag", "Vorschlag (Doppelklick bearbeitet)", 300, True),
            ("original", "Originalname", 200, True), ("ordner", "Ordner", 140, True),
        ):
            self.tree.heading(col, text=text)
            breite = UIUtils.px(self, width)
            self.tree.column(col, width=breite, minwidth=min(breite, UIUtils.px(self, 32)), stretch=stretch, anchor="w")
        self.tree.tag_configure("gleich", foreground="gray50")
        # Müll-Titel (Datenmüll aus der Scanner-OCR): orange - hier lohnt "KI-Titel vorschlagen"
        self.tree.tag_configure("verdaechtig", foreground="#b35c00")
        scroll = ttk.Scrollbar(rahmen, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-Button-1>", self._on_doppelklick)
        self.tree.bind("<space>", lambda e: (self._umschalten(), "break")[1])
        self.tree.bind("<<TreeviewSelect>>", self._sync_hauptfenster)

    # ------------------------------------------------------------------ Daten
    def _pfade(self):
        if self.var_bereich.get() == "auswahl" and self.auswahl:
            return [p for p in self.auswahl if os.path.isfile(p)]
        ordner = aktueller_ordner(self.app)
        master = self.app.master_folder
        return dateinamen.sammle_pdfs(ordner, rekursiv=self.var_rekursiv.get(),
                                      ist_papierkorb=lambda p: app_paths.is_trash_path(p, master))

    def _laden(self):
        self.tree.delete(*self.tree.get_children(""))
        self.zeilen.clear()
        master = self.app.master_folder
        for pfad in self._pfade():
            zeile = dateinamen.zeile_fuer(pfad)
            zeile["markiert"] = False
            iid = self.tree.insert("", tk.END, values=("", "", "", "", os.path.relpath(os.path.dirname(pfad), master) or "."))
            self.zeilen[iid] = zeile
            self._zeichne_zeile(iid)
        self._status()

    def _zeichne_zeile(self, iid):
        z = self.zeilen[iid]
        self.tree.set(iid, "check", "☑" if z["markiert"] else "☐")
        self.tree.set(iid, "name", z["name"])
        if z.get("ki_titel"):
            self.tree.set(iid, "titel", f"(KI) {z['ki_titel']}")
        elif z.get("ki_laeuft"):
            self.tree.set(iid, "titel", "KI fragt nach…")
        else:
            self.tree.set(iid, "titel", ("⚠ " if z["verdaechtig"] else "") + (z["titel"] or "(kein Titel)"))
        self.tree.set(iid, "vorschlag", z["vorschlag"] or "(kein Vorschlag: Datum oder Titel fehlt)")
        self.tree.set(iid, "original", z["originalname"] or "—")
        if z["verdaechtig"] and not z.get("ki_titel"):
            self.tree.item(iid, tags=("verdaechtig",))
        else:
            self.tree.item(iid, tags=("gleich",) if not z["vorschlag"] or z["vorschlag"] == z["name"] else ())

    def _status(self, zusatz=""):
        gesamt = len(self.zeilen)
        abweichend = sum(1 for z in self.zeilen.values() if z["vorschlag"] and z["vorschlag"] != z["name"])
        markiert = sum(1 for z in self.zeilen.values() if z["markiert"])
        mit_original = sum(1 for z in self.zeilen.values() if z["originalname"] and z["originalname"] != z["name"])
        verdaechtig = sum(1 for z in self.zeilen.values() if z["verdaechtig"] and not z.get("ki_titel"))
        text = (f"{gesamt} Datei(en), {abweichend} mit abweichendem Vorschlag, {verdaechtig} mit Müll-Titel (⚠, KI fragen), "
                f"{mit_original} mit anderem Originalnamen, {markiert} angehakt. "
                "Doppelklick auf ✓ oder Leertaste hakt an/ab, Doppelklick auf den Vorschlag bearbeitet ihn.")
        if zusatz:
            text = zusatz + "  |  " + text
        self.status.config(text=text)

    def pfad_nachziehen(self, alt, neu):
        """Datei wurde anderswo verschoben/umbenannt: Zeile aktualisieren statt ins Leere zu laufen."""
        for iid, z in self.zeilen.items():
            if os.path.normcase(z["pfad"]) == os.path.normcase(alt):
                z["pfad"] = neu
                z["name"] = os.path.basename(neu)
                if self.tree.exists(iid):
                    self._zeichne_zeile(iid)

    # ------------------------------------------------------------------ Bedienung
    def _on_doppelklick(self, event):
        iid = self.tree.identify_row(event.y)
        if not iid or iid not in self.zeilen:
            return
        if self.tree.identify_column(event.x) == "#3":
            self._bearbeite_vorschlag(iid)
        else:
            self._umschalten(iid)

    def _umschalten(self, iid=None):
        ziele = [iid] if iid else list(self.tree.selection())
        for iid in ziele:
            if iid in self.zeilen:
                self.zeilen[iid]["markiert"] = not self.zeilen[iid]["markiert"]
                self._zeichne_zeile(iid)
        self._status()

    def _bearbeite_vorschlag(self, iid):
        z = self.zeilen[iid]
        neu = UIUtils.ask_string("Dateiname bearbeiten", f"Neuer Name für '{z['name']}':",
                                 initialvalue=z["vorschlag"] or z["name"], parent=self)
        if neu is None:
            return
        neu = dateinamen.bereinige_dateiname(neu)
        if not neu:
            return
        z["vorschlag"] = neu
        z["markiert"] = neu != z["name"]
        self._zeichne_zeile(iid)
        self._status()

    def _abweichende_anhaken(self):
        for iid, z in self.zeilen.items():
            z["markiert"] = bool(z["vorschlag"]) and z["vorschlag"] != z["name"]
            self._zeichne_zeile(iid)
        self._status()

    def _alle_abwaehlen(self):
        for iid, z in self.zeilen.items():
            z["markiert"] = False
            self._zeichne_zeile(iid)
        self._status()

    # ------------------------------------------------------------------ KI-Titel
    def _ki_titel(self):
        """
        Lässt die KI für die in der Tabelle markierten Zeilen (ohne Markierung: alle mit
        Müll-Titel ⚠) einen Titel von der ersten Seite ablesen. Der Vorschlag wird zu
        'JJJJMMTT_KI-Titel.pdf', die Zeile bleibt bewusst OHNE Haken - der Nutzer sieht
        den Vorschlag erst an und hakt dann selbst an. Beim Umbenennen wandert der KI-Titel
        auch in die PDF-Metadaten, damit Dateiname und Titel zusammenpassen.
        """
        if self._ki_laeuft:
            return
        ziele = [iid for iid in self.tree.selection() if iid in self.zeilen]
        if not ziele:
            ziele = [iid for iid, z in self.zeilen.items() if z["verdaechtig"] and not z.get("ki_titel")]
        if not ziele:
            mb.showinfo("KI-Titel vorschlagen", "Keine Zeilen markiert und kein Müll-Titel (⚠) in der Tabelle.", parent=self)
            return
        base_url = self.app.config.get("ollama_url", ollama_client.DEFAULT_URL)
        model = self.app.config.get("ollama_model", ollama_client.DEFAULT_MODEL)
        if not ollama_client.is_reachable(base_url):
            mb.showwarning("Ollama nicht erreichbar",
                           f"Der KI-Server unter {base_url} antwortet nicht.\n"
                           "Server-Adresse in den Einstellungen prüfen, oder Ollama lokal/im Netzwerk starten.", parent=self)
            return
        self._ki_laeuft = True
        self.btn_ki.config(state=tk.DISABLED)
        auftraege = []
        for iid in ziele:
            self.zeilen[iid]["ki_laeuft"] = True
            self._zeichne_zeile(iid)
            auftraege.append((iid, self.zeilen[iid]["pfad"]))
        self._status(f"KI liest {len(auftraege)} Dokument(e)…")

        def worker():
            for nr, (iid, pfad) in enumerate(auftraege, start=1):
                titel = ""
                try:
                    bild = render_first_page_png(pfad)
                    if bild:
                        titel = ollama_client.suggest_title(bild, base_url=base_url, model=model)
                except Exception as e:
                    if getattr(self.app, "logger", None):
                        self.app.logger.warning(f"KI-Titel fehlgeschlagen für {pfad}: {e}")
                self.after(0, self._ki_fertig, iid, titel, nr, len(auftraege))

        threading.Thread(target=worker, daemon=True).start()

    def _ki_fertig(self, iid, titel, nr, gesamt):
        """Im Tk-Thread: KI-Ergebnis in die Zeile eintragen (Vorschlag neu bauen, kein Haken)."""
        if not self.winfo_exists():
            return
        z = self.zeilen.get(iid)
        if z is not None:
            z["ki_laeuft"] = False
            if titel:
                z["ki_titel"] = titel
                z["vorschlag"] = dateinamen.baue_vorschlag(z["datum"], titel) or dateinamen.bereinige_dateiname(titel)
            if self.tree.exists(iid):
                self._zeichne_zeile(iid)
        if nr >= gesamt:
            self._ki_laeuft = False
            self.btn_ki.config(state=tk.NORMAL)
            self._status("KI fertig - Vorschläge prüfen und anhaken")
        else:
            self._status(f"KI: {nr}/{gesamt}…")

    def _sync_hauptfenster(self, event=None):
        """Klick auf eine Zeile wählt das Dokument auch im Hauptfenster (nur selection_set/see -
        Tkinter feuert on_file_select selbst, siehe FALLSTRICKE Render-Deadlock)."""
        auswahl = self.tree.selection()
        if len(auswahl) != 1 or auswahl[0] not in self.zeilen or not hasattr(self.app, "tree_files"):
            return
        rel = os.path.normcase(os.path.relpath(self.zeilen[auswahl[0]]["pfad"], self.app.master_folder))
        for item in self.app.tree_files.get_children(""):
            values = self.app.tree_files.item(item, "values")
            if len(values) > 4 and os.path.normcase(values[4]) == rel:
                if self.app.tree_files.selection() != (item,):
                    self.app.tree_files.selection_set(item)
                    self.app.tree_files.see(item)
                break

    # ------------------------------------------------------------------ Aktionen
    def _fuehre_aus(self, titel, kandidaten, aktion):
        """Gemeinsamer Ablauf für Umbenennen und Wiederherstellen: Watchdog stilllegen,
        je Zeile die Aktion, Pfade in App und Tools nachziehen, Ergebnis melden."""
        fehler = []
        erledigt = 0
        self.app.is_moving = True
        try:
            for iid, z in kandidaten:
                neuer_pfad, meldung = aktion(z)
                if meldung:
                    fehler.append(f"{z['name']}: {meldung}")
                    continue
                if neuer_pfad != z["pfad"]:
                    alter_pfad = z["pfad"]
                    if getattr(self.app, "logger", None):
                        self.app.logger.info(f"{titel}: {alter_pfad} -> {neuer_pfad}")
                    if hasattr(self.app, "file_ops"):
                        self.app.file_ops._notify_tools_moved(alter_pfad, neuer_pfad)
                    erledigt += 1
                    # Zeile frisch aus dem PDF (Originalname ist jetzt eingebrannt)
                    self.zeilen[iid] = dict(dateinamen.zeile_fuer(neuer_pfad), markiert=False)
                    self._zeichne_zeile(iid)
        finally:
            self.app.is_moving = False
        if hasattr(self.app, "folder_manager"):
            self.app.folder_manager.on_folder_select(None)
        self._status(f"{titel}: {erledigt} Datei(en) umbenannt" + (f", {len(fehler)} Fehler" if fehler else ""))
        if fehler:
            mb.showerror(f"{titel} - teilweise fehlgeschlagen", "\n".join(fehler), parent=self)

    def _umbenennen(self):
        kandidaten = [(iid, z) for iid, z in self.zeilen.items()
                      if z["markiert"] and z["vorschlag"] and z["vorschlag"] != z["name"]]
        if not kandidaten:
            mb.showinfo("Dateinamen aufräumen", "Nichts angehakt, das einen anderen Namen bekäme.", parent=self)
            return
        if not bestaetigung.frage("Dateinamen aufräumen",
                                  f"{len(kandidaten)} Datei(en) umbenennen?\n"
                                  "Der bisherige Name wird als Originalname im PDF gespeichert und lässt sich "
                                  "jederzeit wiederherstellen.", parent=self):
            return
        # KI-Titel wandert mit ins PDF (Dateiname und Titel passen dann zusammen)
        self._fuehre_aus("Umbenannt", kandidaten,
                         lambda z: dateinamen.benenne_um(z["pfad"], z["vorschlag"],
                                                         zusatz_metadaten={"title": z["ki_titel"]} if z.get("ki_titel") else None))

    def _wiederherstellen(self):
        kandidaten = [(iid, z) for iid, z in self.zeilen.items()
                      if z["markiert"] and z["originalname"] and z["originalname"] != z["name"]]
        if not kandidaten:
            mb.showinfo("Originalnamen wiederherstellen",
                        "Nichts angehakt, das einen gespeicherten Originalnamen hat (Spalte 'Originalname').", parent=self)
            return
        if not bestaetigung.frage("Originalnamen wiederherstellen",
                                  f"{len(kandidaten)} Datei(en) auf ihren Originalnamen zurückbenennen?", parent=self):
            return
        self._fuehre_aus("Wiederhergestellt", kandidaten,
                         lambda z: dateinamen.stelle_wieder_her(z["pfad"], z["originalname"]))
