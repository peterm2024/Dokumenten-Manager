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

import aktivitaet
import app_paths
import bestaetigung
import dateinamen
import ollama_client
from tools.ai_title_suggest import render_first_page_png
from tools.base_tool import BaseTool, ToolContext
from ui_utils import Tooltip, UIUtils


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
        self.window = self.oeffne_fenster(lambda: DateinamenFenster(context.app, auswahl), auswahl)
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


def aendert_sich(z):
    """Bekäme die Zeile einen anderen Namen?"""
    return bool(z["vorschlag"]) and z["vorschlag"] != z["name"]


def hat_anderen_original(z):
    return bool(z["originalname"]) and z["originalname"] != z["name"]


def ist_muell(z):
    """Müll-Titel aus der Scanner-OCR (⚠), für den die KI noch nicht gefragt wurde."""
    return bool(z["verdaechtig"]) and not z.get("ki_titel")


def umbenenn_kandidaten(zeilen):
    """Angehakte Zeilen, die wirklich einen anderen Namen bekämen - die Zahl steht auf dem Umbenennen-Knopf."""
    return [iid for iid, z in zeilen.items() if z["markiert"] and aendert_sich(z)]


def ki_ziele(zeilen):
    """Wofür „KI-Titel“ fragt (B6, Peter 21.11.2026: EINE Auswahl statt Haken + Tabellenmarkierung): die angehakten
    Zeilen, ohne Haken alle mit Müll-Titel ⚠. :return: (Zeilen, Art) - Art „angehakte“ oder „⚠“"""
    angehakt = [iid for iid, z in zeilen.items() if z["markiert"] and not z.get("ki_laeuft")]
    if angehakt:
        return angehakt, "angehakte"
    return [iid for iid, z in zeilen.items() if ist_muell(z) and not z.get("ki_laeuft")], "⚠"


def alle_umschalten(zeilen):
    """Klick auf den ✓-Spaltenkopf: fehlt noch ein Haken bei einer Zeile mit neuem Namen, alle diese anhaken -
    sonst alle Haken weg (ersetzt die Knöpfe „Abweichende anhaken“ und „Alle abwählen“)."""
    offen = any(aendert_sich(z) and not z["markiert"] for z in zeilen.values())
    for z in zeilen.values():
        z["markiert"] = offen and aendert_sich(z)


def menue_eintraege(zeilen, iid):
    """Rechtsklick-Menü einer Zeile: (Aktion, Beschriftung). Seltenes wie „Originalnamen wiederherstellen“ steht
    nur hier (B6) - und nur, wenn es einen anderen Originalnamen gibt."""
    z = zeilen[iid]
    eintraege = [("vorschlag", "Neuen Namen bearbeiten…"),
                 ("check", "Haken entfernen" if z["markiert"] else "Haken setzen"),
                 ("ki", "KI-Titel vorschlagen")]
    if hat_anderen_original(z):
        eintraege.append(("original", f"Originalnamen wiederherstellen ({z['originalname']})"))
    return eintraege


class DateinamenFenster(tk.Toplevel):
    # „Neuer Name“ direkt neben dem aktuellen (B6); Spalten immer über ihre ID ansprechen (FALLSTRICKE #140)
    SPALTEN = ("check", "name", "vorschlag", "titel", "ordner")

    def __init__(self, app, auswahl):
        super().__init__(app.root)
        UIUtils.werkzeugfenster(self, app.root)   # über KID, nicht modal (Peter 04.11.2026)
        self.app = app
        self.title("Dateinamen aufräumen")
        UIUtils.position_near_mouse(self, UIUtils.px(self, 1100), UIUtils.px(self, 600))
        self.minsize(UIUtils.px(self, 700), UIUtils.px(self, 350))
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
        """B6 (Peter 21.11.2026: „zu komplex und umständlich“): Haken sind die EINZIGE Auswahl, unten nur noch
        KI-Titel, Umbenennen (n) und Schließen; Seltenes im Rechtsklick-Menü; Knöpfe ausgegraut statt
        „Nichts angehakt“-Meldungen."""
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

        # Knöpfe und Statuszeile ZUERST und von unten packen: sie bleiben so auch dann im
        # Fenster, wenn die Tabelle mehr Platz verlangt, als da ist (Lehre aus dem Test-Wizard).
        unten = ttk.Frame(self)
        unten.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 10))
        self.btn_ki = ttk.Button(unten, text="KI-Titel", command=self._ki_titel)
        self.btn_ki.pack(side=tk.LEFT)
        Tooltip(self.btn_ki, "Die KI liest den Titel von der ersten Seite - für die angehakten Zeilen, ohne Haken "
                             "für alle mit Müll-Titel ⚠. Die KI setzt keinen Haken: erst ansehen, dann anhaken.")
        ttk.Button(unten, text="Schließen", command=self.destroy).pack(side=tk.RIGHT)
        self.btn_umbenennen = ttk.Button(unten, text="Umbenennen", command=self._umbenennen, style="Accent.TButton")
        self.btn_umbenennen.pack(side=tk.RIGHT, padx=(0, 8))
        Tooltip(self.btn_umbenennen, "Benennt die angehakten Dateien um. Der bisherige Name bleibt als Originalname "
                                     "im PDF und lässt sich per Rechtsklick wiederherstellen.")
        self.status = ttk.Label(self, anchor="w", foreground="gray40")
        self.status.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 5))

        rahmen = ttk.Frame(self)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 5))
        self.tree = ttk.Treeview(rahmen, columns=self.SPALTEN, show="headings", selectmode="extended")
        for col, text, width, stretch in (
            ("check", "✓", 32, False), ("name", "Aktueller Name", 260, True),
            ("vorschlag", "Neuer Name", 300, True), ("titel", "Titel (PDF)", 220, True),
            ("ordner", "Ordner", 140, True),
        ):
            self.tree.heading(col, text=text)
            breite = UIUtils.px(self, width)
            self.tree.column(col, width=breite, minwidth=min(breite, UIUtils.px(self, 32)), stretch=stretch, anchor="w")
        self.tree.heading("check", command=self._alle_umschalten)
        self.tree.tag_configure("gleich", foreground="gray50")
        # Müll-Titel (Datenmüll aus der Scanner-OCR): orange - hier lohnt "KI-Titel"
        self.tree.tag_configure("verdaechtig", foreground="#b35c00")
        scroll = ttk.Scrollbar(rahmen, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        UIUtils.tabelle_bearbeitbar(self.tree, self._bearbeite, menue=lambda iid: menue_eintraege(self.zeilen, iid),
                                    f2_spalte="vorschlag")
        self.tree.bind("<space>", lambda e: (self._umschalten(), "break")[1])
        self.tree.bind("<Button-1>", self._klick, add="+")
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
        if not z["vorschlag"]:
            self.tree.set(iid, "vorschlag", "(Datum oder Titel fehlt)")
        else:
            self.tree.set(iid, "vorschlag", z["vorschlag"] if aendert_sich(z) else "(unverändert)")
        if ist_muell(z):
            self.tree.item(iid, tags=("verdaechtig",))
        else:
            self.tree.item(iid, tags=() if aendert_sich(z) else ("gleich",))

    def _status(self, zusatz=""):
        zeilen = self.zeilen.values()
        markiert = sum(1 for z in zeilen if z["markiert"])
        abweichend = sum(1 for z in zeilen if aendert_sich(z))
        muell = sum(1 for z in zeilen if ist_muell(z))
        teile = [f"{markiert} angehakt", f"{abweichend} würden sich ändern"]
        if muell:
            teile.append(f"{muell} mit ⚠ Müll-Titel")
        text = " · ".join(teile) + "   (Klick auf ☐ hakt an, auf den Kopf ✓ alle mit neuem Namen; Rechtsklick = mehr)"
        self.status.config(text=f"{zusatz}  |  {text}" if zusatz else text)
        self._knoepfe()

    def _knoepfe(self):
        """Zahlen auf die Knöpfe, ausgegraut statt „Nichts angehakt“-Meldung (B6)."""
        n = len(umbenenn_kandidaten(self.zeilen))
        self.btn_umbenennen.config(text=f"Umbenennen ({n})" if n else "Umbenennen")
        self.btn_umbenennen.state(["!disabled"] if n else ["disabled"])
        ziele, art = ki_ziele(self.zeilen)
        self.btn_ki.config(text=f"KI-Titel für {art} ({len(ziele)})" if ziele else "KI-Titel")
        self.btn_ki.state(["!disabled"] if ziele and not self._ki_laeuft else ["disabled"])

    def pfad_nachziehen(self, alt, neu):
        """Datei wurde anderswo verschoben/umbenannt: Zeile aktualisieren statt ins Leere zu laufen."""
        for iid, z in self.zeilen.items():
            if os.path.normcase(z["pfad"]) == os.path.normcase(alt):
                z["pfad"] = neu
                z["name"] = os.path.basename(neu)
                if self.tree.exists(iid):
                    self._zeichne_zeile(iid)

    # ------------------------------------------------------------------ Bedienung
    def _bearbeite(self, iid, spalte):
        """Doppelklick, Rechtsklick-Menü oder F2 (UIUtils.tabelle_bearbeitbar): der Vorschlag wird bearbeitet, der
        Haken umgeschaltet (Doppelklick auf ☐ = zwei Klicks); aus dem Menü außerdem KI-Titel und Originalname.
        Andere Zellen tun beim Doppelklick nichts mehr (Peter 21.11.2026: „anhaken sollte man mit nur einem
        Klick, Doppelklick auch hier ist ungewöhnlich“ - der Einzelklick auf ☐ hakt an, `_klick`). Vorher fragte
        der Doppelklick „#3“ ab - eine neue Spalte verschob still sein Ziel (FALLSTRICKE #140)."""
        if iid not in self.zeilen:
            return
        if spalte == "vorschlag":
            self._bearbeite_vorschlag(iid)
        elif spalte == "ki":
            self._ki_titel(self._betroffene(iid))
        elif spalte == "original":
            self._wiederherstellen(self._betroffene(iid))
        elif spalte == "check":
            self._umschalten(iid)

    def _klick(self, event):
        """Einzelklick auf ☐/☑ hakt an/ab (wie in jeder Haken-Liste); die Zeile wird dabei auch ausgewählt."""
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.column(self.tree.identify_column(event.x), "id") != "check":
            return
        iid = self.tree.identify_row(event.y)
        if iid in self.zeilen:
            self._umschalten(iid)

    def _betroffene(self, iid):
        """Rechtsklick auf eine angehakte Zeile wirkt auf alle angehakten, sonst nur auf diese Zeile."""
        if self.zeilen[iid]["markiert"]:
            return [i for i, z in self.zeilen.items() if z["markiert"]]
        return [iid]

    def _umschalten(self, iid=None):
        ziele = [iid] if iid else list(self.tree.selection())
        for iid in ziele:
            if iid in self.zeilen:
                self.zeilen[iid]["markiert"] = not self.zeilen[iid]["markiert"]
                self._zeichne_zeile(iid)
        self._status()

    def _alle_umschalten(self):
        alle_umschalten(self.zeilen)
        for iid in self.zeilen:
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

    # ------------------------------------------------------------------ KI-Titel
    def _ki_titel(self, ziele=None):
        """
        Lässt die KI einen Titel von der ersten Seite ablesen - für `ziele`, ohne Angabe für die angehakten
        Zeilen bzw. ohne Haken alle mit Müll-Titel ⚠ (`ki_ziele`). Der Vorschlag wird zu
        'JJJJMMTT_KI-Titel.pdf'. Die KI setzt keinen Haken (⚠-Zeilen erst ansehen, dann anhaken), vorhandene
        bleiben. Beim Umbenennen wandert der KI-Titel auch in die PDF-Metadaten, damit
        Dateiname und Titel zusammenpassen.
        """
        if self._ki_laeuft:
            return
        if ziele is None:
            ziele = ki_ziele(self.zeilen)[0]
        ziele = [iid for iid in ziele if iid in self.zeilen]
        if not ziele:
            return
        base_url = self.app.config.get("ollama_url", ollama_client.DEFAULT_URL)
        model = ollama_client.eingestelltes_modell(self.app.config)
        if not ollama_client.is_reachable(base_url):
            mb.showwarning("Ollama nicht erreichbar",
                           f"Der KI-Server unter {base_url} antwortet nicht.\n"
                           "Server-Adresse in den Einstellungen prüfen, oder Ollama lokal/im Netzwerk starten.", parent=self)
            return
        self._ki_laeuft = True
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
        elif erledigt:
            aktivitaet.erledigt(f"{titel}: {erledigt} Datei(en)")

    def _umbenennen(self):
        kandidaten = [(iid, self.zeilen[iid]) for iid in umbenenn_kandidaten(self.zeilen)]
        if not kandidaten:
            return   # der Knopf ist dann ausgegraut
        if not bestaetigung.frage("Dateinamen aufräumen",
                                  f"{len(kandidaten)} Datei(en) umbenennen?\n"
                                  "Der bisherige Name wird als Originalname im PDF gespeichert und lässt sich "
                                  "jederzeit wiederherstellen (Rechtsklick auf die Zeile).", parent=self):
            return
        # KI-Titel wandert mit ins PDF (Dateiname und Titel passen dann zusammen)
        self._fuehre_aus("Umbenannt", kandidaten,
                         lambda z: dateinamen.benenne_um(z["pfad"], z["vorschlag"],
                                                         zusatz_metadaten={"title": z["ki_titel"]} if z.get("ki_titel") else None))

    def _wiederherstellen(self, ziele):
        """Originalnamen zurück - aus dem Rechtsklick-Menü für die Zeile bzw. alle angehakten (B6)."""
        kandidaten = [(iid, self.zeilen[iid]) for iid in ziele
                      if iid in self.zeilen and hat_anderen_original(self.zeilen[iid])]
        if not kandidaten:
            return
        if not bestaetigung.frage("Originalnamen wiederherstellen",
                                  f"{len(kandidaten)} Datei(en) auf ihren Originalnamen zurückbenennen?", parent=self):
            return
        self._fuehre_aus("Wiederhergestellt", kandidaten,
                         lambda z: dateinamen.stelle_wieder_her(z["pfad"], z["originalname"]))
