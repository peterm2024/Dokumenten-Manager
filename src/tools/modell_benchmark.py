"""
Werkzeug „Benchmark“ (Etappe 13 Schritt 3, KONZEPT_BENCHMARK.md): misst mit den 40 Prüfdokumenten, wie schnell die
Vollautomatik mit den gewählten Modellen auf dem eingestellten KI-Server ablegt. Die Logik steht in `benchmark`
(ohne Oberfläche), hier nur das Fenster: Modelle und Grafikkarte wählen, Start/Abbrechen, Fortschritt, die
letzten drei Läufe nebeneinander, „Ergebnis kopieren“ für Rückmeldungen.

Während des Laufs pausiert die Vollautomatik dieses KID (F5); überwacht ein Dienst auf einem anderen Rechner den
Posteingang, warnt das Fenster - er rechnet auf demselben Server mit und verfälscht die Zeiten.
"""
import os
import threading
import zipfile
import tkinter as tk
from tkinter import filedialog, ttk

import app_paths
import auto_pilot
import benchmark
import ollama_client
import posteingang_sperre
from help_window import APP_VERSION
from tools.base_tool import BaseTool, ToolContext
from tools.settings_editor import auswahlfeld, modell_aus_anzeige, modelle_beschriftet, zuletzt_verwendet
from ui_utils import Tooltip, UIUtils

OHNE_ZWEITMEINUNG = "(ohne Zweitmeinung)"
SEKUNDEN_JE_DOKUMENT = 10   # grobe Schätzung für den Hinweis vor dem Start (5060 Ti mit beiden Modellen: ~9 s)
LISTE_ZEILEN = 12              # Liste je Brief, aufgeklappt
VERGLEICH_ZEILEN_MIT_LISTE = 9 # der Vergleich, solange die Liste offen ist (Rest per Rollbalken)
MIN_VERGLEICH_ZEILEN = 5       # weniger zeigen Vergleich und Liste auch auf kleinem Bildschirm nicht


class BenchmarkTool(BaseTool):
    fenster_schluessel = "benchmark"

    def __init__(self):
        self.window = None

    @property
    def name(self) -> str:
        return "Benchmark"

    @property
    def menu_group(self) -> str:
        return "KI-Helfer"

    @property
    def menu_label(self) -> str:
        return "Benchmark (KI-Modelle messen)…"

    @property
    def description(self) -> str:
        return ("Misst mit 40 erfundenen Prüfdokumenten, wie viele Sekunden die Vollautomatik je Dokument braucht - "
                "mit den gewählten Modellen auf dem eingestellten KI-Server. Die Sammlung bleibt unberührt.")

    @property
    def absicht(self) -> str:
        return ("Modelle und Grafikkarten vergleichen: Lohnt ein anderes Modell, reicht die Karte, wie schnell ist "
                "der Server in der Firma? Das Ergebnis lässt sich als Text kopieren und weitergeben.")

    @property
    def braucht_ki(self) -> bool:
        return True

    @property
    def menu_hooks(self) -> list:
        return ["main_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        self.window = self.oeffne_fenster(lambda: BenchmarkFenster(context.app))
        return True


class BenchmarkFenster(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.withdraw()   # unsichtbar aufbauen, dann platzieren (FALLSTRICKE #90)
        self.app = app
        self.title("Benchmark")
        UIUtils.werkzeugfenster(self, app.root, maximierbar=True)   # Vergleich + Liste je Brief: große Tabellen
        cfg = app.config
        self.base_url = cfg.get("ollama_url", ollama_client.DEFAULT_URL)
        self.ergebnis_pfad = app_paths.benchmark_path(app.master_folder)
        self._satz = benchmark.eingebauter_satz()   # Schritt 4: fester Satz, wählbar die Release-Zips
        self._laeuft = False
        self._stopp = threading.Event()
        self._stand = {}          # vom Mess-Thread geschrieben, vom Hauptthread gelesen (kein Tk im Thread)
        self._ansehen = []        # Wegwerf-Ordner der per Doppelklick geöffneten Prüfbriefe, beim Schließen weg
        self._letzter = None      # letzter Lauf (für den Satz hinter der Liste je Brief)

        breite = UIUtils.px(self, 640)
        ttk.Label(self, wraplength=breite, justify=tk.LEFT, text=(
            "Misst mit 40 erfundenen Prüfdokumenten, wie schnell die Vollautomatik mit diesen Modellen auf dem "
            "KI-Server ablegt - so wie im Betrieb: erst lesen, dann die Zweitmeinung zum Ordner. Ihre Sammlung "
            "wird weder gelesen noch verändert, die Vollautomatik pausiert während des Laufs.")).pack(
            fill=tk.X, padx=10, pady=(10, 6))

        # Knopfleiste und Fortschritt VOR dem dehnbaren Inhalt (side=BOTTOM)
        knoepfe = ttk.Frame(self)
        knoepfe.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 10))
        self.btn_start = ttk.Button(knoepfe, text="Start", command=self._start)
        self.btn_start.pack(side=tk.LEFT)
        self.btn_stopp = ttk.Button(knoepfe, text="Abbrechen", command=self._stopp.set, state=tk.DISABLED)
        self.btn_stopp.pack(side=tk.LEFT, padx=5)
        ttk.Button(knoepfe, text="Schließen", command=self._schliessen).pack(side=tk.RIGHT)
        self.btn_kopieren = ttk.Button(knoepfe, text="Ergebnis kopieren", command=self._kopieren)
        self.btn_kopieren.pack(side=tk.RIGHT, padx=5)
        self.status = ttk.Label(self, anchor="w")
        self.status.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 4))
        self.fortschritt = ttk.Progressbar(self, maximum=40)
        self.fortschritt.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 4))

        form = ttk.Frame(self)
        form.pack(fill=tk.X, padx=10)
        form.columnconfigure(1, weight=1)
        ttk.Label(form, text="KI-Server:").grid(row=0, column=0, sticky="w", pady=2)
        ttk.Label(form, text=self.base_url).grid(row=0, column=1, sticky="w", pady=2)
        self.var_lesen = tk.StringVar(value=cfg.get("ollama_model", ollama_client.DEFAULT_MODEL))
        self.var_zweit = tk.StringVar(value=cfg.get("ki_entscheidungsmodell", None)
                                      or auto_pilot.STANDARD_ENTSCHEIDUNGSMODELL)
        letzte = benchmark.lade_ergebnisse(self.ergebnis_pfad)
        self.var_karte = tk.StringVar(value=cfg.get("benchmark_grafikkarte", "")
                                      or (letzte[-1]["grafikkarte"] if letzte else ""))
        ttk.Label(form, text="Lese-Modell:").grid(row=1, column=0, sticky="w", pady=2)
        self.feld_lesen = auswahlfeld(form, self.var_lesen, lambda: None, bereinige=modell_aus_anzeige, width=40)
        self.feld_lesen.grid(row=1, column=1, sticky="w", pady=2)
        ttk.Label(form, text="Zweitmeinung zum Ordner:").grid(row=2, column=0, sticky="w", pady=2, padx=(0, 8))
        self.feld_zweit = auswahlfeld(form, self.var_zweit, lambda: None, bereinige=modell_aus_anzeige, width=40)
        self.feld_zweit.grid(row=2, column=1, sticky="w", pady=2)
        ttk.Label(form, text="Grafikkarte des Servers:").grid(row=3, column=0, sticky="w", pady=2)
        auswahlfeld(form, self.var_karte, lambda: None, values=benchmark.GRAFIKKARTEN, width=40).grid(
            row=3, column=1, sticky="w", pady=2)
        ttk.Label(form, foreground="gray40", text="KI-Server nennen ihre Grafikkarte nicht - bitte auswählen oder "
                  "eintragen, sonst lassen sich Ergebnisse nicht vergleichen.", wraplength=breite).grid(
            row=4, column=0, columnspan=2, sticky="w")
        ttk.Label(form, text="Prüfbriefe:").grid(row=5, column=0, sticky="w", pady=(6, 2))
        satzzeile = ttk.Frame(form)
        satzzeile.grid(row=5, column=1, sticky="ew", pady=(6, 2))
        self.lbl_satz = ttk.Label(satzzeile)
        self.lbl_satz.pack(side=tk.LEFT)
        self.btn_eingebaut = ttk.Button(satzzeile, text="Eingebauter Satz", command=self._satz_eingebaut)
        self.btn_eingebaut.pack(side=tk.RIGHT)
        self.btn_zip = ttk.Button(satzzeile, text="Anderer Satz (Zip)…", command=self._satz_waehlen)
        self.btn_zip.pack(side=tk.RIGHT, padx=5)
        Tooltip(self.btn_zip, "Einen der Zips mit Prüfbriefen aus dem Release wählen (digital, gescannt hoch oder "
                              "niedrig). Nur Läufe mit demselben Satz lassen sich vergleichen.")
        self.hinweis = ttk.Label(self, foreground="#a33", wraplength=breite, justify=tk.LEFT)
        self.hinweis.pack(fill=tk.X, padx=10, pady=(4, 0))

        rahmen = ttk.Frame(self)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)
        # Liste je Brief (Peter 22.11.2026: „Dazu Liste je Brief“) - aufklappbar unter dem Vergleich. Aufgeklappt zeigt
        # der Vergleich weniger Zeilen (Rollbalken), sonst wüchse das Fenster aus dem Bildschirm (Demo: 1156 px)
        self.var_liste = tk.BooleanVar(value=False)
        ttk.Checkbutton(rahmen, text="Liste je Brief (letzter Lauf)", variable=self.var_liste,
                        command=self._liste_umschalten).pack(side=tk.BOTTOM, anchor="w", pady=(6, 0))
        vergleich = ttk.Frame(rahmen)
        vergleich.pack(fill=tk.BOTH, expand=True)
        self.tabelle = ttk.Treeview(vergleich, columns=("wert", "l1", "l2", "l3"), show="headings",
                                    height=len(benchmark.ZEILEN), selectmode="none")
        self.tabelle.heading("wert", text="")
        self.tabelle.column("wert", width=UIUtils.px(self, 170), anchor="w", stretch=False)
        for spalte in ("l1", "l2", "l3"):
            self.tabelle.column(spalte, width=UIUtils.px(self, 200), anchor="w")
        self.rollen_vergleich = ttk.Scrollbar(vergleich, orient=tk.VERTICAL, command=self.tabelle.yview)
        self.tabelle.configure(yscrollcommand=self.rollen_vergleich.set)
        self.tabelle.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.liste = ttk.Frame(rahmen)        # erst beim Aufklappen gepackt
        self.briefe = ttk.Treeview(self.liste, columns=("nr", "ergebnis", "erwartet", "gewaehlt", "datum", "absender"),
                                   show="headings", height=LISTE_ZEILEN, selectmode="browse")
        for spalte, titel, b, dehnen in (("nr", "Nr.", 45, False), ("ergebnis", "Ergebnis", 110, False),
                                         ("erwartet", "Richtiger Ordner", 250, True),
                                         ("gewaehlt", "Gewählter Ordner", 250, True),
                                         ("datum", "Datum", 60, False), ("absender", "Absender", 75, False)):
            self.briefe.heading(spalte, text=titel)
            self.briefe.column(spalte, width=UIUtils.px(self, b), stretch=dehnen,
                               anchor="center" if spalte in ("nr", "datum", "absender") else "w")
        # Bedeutungsfarben wie in der Ablage-Vorschau: still falsch rötlich, Rückfrage gelblich
        self.briefe.tag_configure("falsch", background="#f8d7da")
        self.briefe.tag_configure("pruefen", background="#fdf3d7")
        rollen = ttk.Scrollbar(self.liste, orient=tk.VERTICAL, command=self.briefe.yview)
        self.briefe.configure(yscrollcommand=rollen.set)
        rollen.pack(side=tk.RIGHT, fill=tk.Y)
        self.briefe.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.briefe.bind("<Double-1>", self._brief_oeffnen)
        self.briefe.bind("<Return>", self._brief_oeffnen)
        Tooltip(self.briefe, "Doppelklick öffnet den Prüfbrief im PDF-Programm. Still falsch: sicher abgelegt, aber "
                             "nicht im Ordner der Sammlung - „neu angelegt“ heißt, die KI hätte einen zweiten Ordner "
                             "neben dem vorhandenen angelegt.")
        self._zeige_satz()

        self.protocol("WM_DELETE_WINDOW", self._schliessen)
        self.bind("<Escape>", lambda e: self._schliessen())
        self._zeige_ergebnisse(letzte)
        self._pruefe_fremden_dienst()
        self._modelle_holen()
        self._in_den_bildschirm()
        UIUtils.position_near_mouse_auto(self)
        self.deiconify()

    # ------------------------------------------------------------------ Anzeige
    def _zeige_ergebnisse(self, alle):
        """Die letzten drei Läufe nebeneinander, neuester links."""
        drei = list(reversed(alle[-3:]))
        self.tabelle.delete(*self.tabelle.get_children())
        for i, spalte in enumerate(("l1", "l2", "l3")):
            self.tabelle.heading(spalte, text=("Letzter Lauf" if i == 0 else f"{i + 1}. letzter") if i < len(drei)
                                 else "")
        for titel, wert in benchmark.ZEILEN:
            self.tabelle.insert("", tk.END, values=(titel, *[wert(e) for e in drei]))
        self.briefe.delete(*self.briefe.get_children())
        self._letzter = drei[0] if drei else None
        for f in (drei[0].get("faelle") or []) if drei else []:
            self.briefe.insert("", tk.END, tags=(f["ergebnis"],), values=(
                f["nr"], benchmark.ERGEBNIS_TEXTE[f["ergebnis"]], f["erwartet"], benchmark.gewaehlt_text(f),
                "✓" if f["datum"] else "✗", "✓" if f["absender"] else "✗"))
        self.btn_kopieren.config(state=tk.NORMAL if drei else tk.DISABLED)
        if not self._laeuft:
            self.status.config(text="Noch kein Lauf." if not drei else
                               f"Ein Lauf dauert mit 40 Dokumenten etwa {40 * SEKUNDEN_JE_DOKUMENT // 60} Minuten.")

    def _zeige_satz(self):
        eingebaut = os.path.normcase(os.path.abspath(self._satz)) == os.path.normcase(
            os.path.abspath(benchmark.eingebauter_satz()))
        anzahl = benchmark.briefe_im_zip(self._satz)
        self.lbl_satz.config(text=f"{benchmark.satz_name(self._satz)}" + (" (eingebaut)" if eingebaut else "")
                             + f" - {anzahl} Briefe")
        if not self._laeuft:
            self.btn_eingebaut.config(state=tk.DISABLED if eingebaut else tk.NORMAL)

    def _satz_waehlen(self):
        pfad = filedialog.askopenfilename(parent=self, title="Zip mit Prüfbriefen wählen",
                                          filetypes=[("Zip-Dateien", "*.zip"), ("Alle Dateien", "*.*")])
        if not pfad:
            return
        if not benchmark.briefe_im_zip(pfad):
            self.status.config(text="In diesem Zip liegen keine Prüfbriefe (Scan_0001.pdf …).")
            return
        self._satz = pfad
        self._zeige_satz()
        self.status.config(text="")

    def _brief_oeffnen(self, _event=None):
        """Doppelklick/Return in der Liste je Brief: den Prüfbrief aus dem Zip des letzten Laufs im PDF-Programm
        zeigen (Peter, T21.4: „Gewählter Ordner sieht richtiger aus“ - nachsehen können, was im Brief steht)."""
        auswahl = self.briefe.selection()
        if not auswahl or not self._letzter:
            return "break"
        nr = int(self.briefe.item(auswahl[0], "values")[0])
        zip_pfad = benchmark.satz_des_laufs(self._letzter, [self._satz, benchmark.eingebauter_satz()])
        if not zip_pfad:
            self.status.config(text=f"Die Prüfbriefe des letzten Laufs ({self._letzter.get('satz', '?')}) sind nicht "
                                    "gewählt - bitte über „Anderer Satz (Zip)…“ denselben Zip wählen.")
            return "break"
        try:
            ordner, pfad = benchmark.brief_auspacken(zip_pfad, nr)
        except (OSError, zipfile.BadZipFile) as e:
            self.status.config(text=f"Prüfbrief {nr} lässt sich nicht öffnen ({type(e).__name__}).")
            return "break"
        if not pfad:
            self.status.config(text=f"Prüfbrief {nr} fehlt im Zip.")
            return "break"
        self._ansehen.append(ordner)
        try:
            os.startfile(pfad)   # Windows; die App läuft nur dort (PyInstaller-EXE)
        except OSError as e:
            self.status.config(text=f"Kein PDF-Programm für Prüfbrief {nr} gefunden ({type(e).__name__}).")
        return "break"

    def _satz_eingebaut(self):
        self._satz = benchmark.eingebauter_satz()
        self._zeige_satz()

    def _liste_umschalten(self):
        """Liste je Brief auf/zu. Offen teilen sich Vergleich und Liste den Platz, beide mit Rollbalken - das Fenster
        bleibt etwa so hoch wie zugeklappt."""
        if self.var_liste.get():
            self.tabelle.config(height=VERGLEICH_ZEILEN_MIT_LISTE)
            self.liste.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        else:
            self.liste.pack_forget()
            self.tabelle.config(height=len(benchmark.ZEILEN))
        self._in_den_bildschirm()

    def _in_den_bildschirm(self):
        """Der Vergleich hat 21 Zeilen - bei großer Schrift auf einem Laptop wäre das Fenster höher als der Bildschirm
        und Knöpfe lägen unten außerhalb. Dann zeigt er weniger Zeilen, der Rest per Rollbalken."""
        grenze = int(self.winfo_screenheight() * 0.9)
        self.update_idletasks()
        zeilen = int(self.tabelle.cget("height"))
        while self.winfo_reqheight() > grenze and zeilen > MIN_VERGLEICH_ZEILEN:
            zeilen -= 1
            self.tabelle.config(height=zeilen)
            self.update_idletasks()
        # reicht das nicht, gibt auch die aufgeklappte Liste Zeilen ab
        liste = LISTE_ZEILEN
        self.briefe.config(height=liste)
        self.update_idletasks()
        while self.var_liste.get() and self.winfo_reqheight() > grenze and liste > MIN_VERGLEICH_ZEILEN:
            liste -= 1
            self.briefe.config(height=liste)
            self.update_idletasks()
        if zeilen < len(benchmark.ZEILEN):
            if not self.rollen_vergleich.winfo_ismapped():
                self.rollen_vergleich.pack(side=tk.RIGHT, fill=tk.Y, before=self.tabelle)
        else:
            self.rollen_vergleich.pack_forget()
        if self.winfo_ismapped():
            # aufgeklappt wächst das Fenster nach unten - stand es weit unten, rückt es nach oben in den Bildschirm
            self.update_idletasks()
            x, y = self.winfo_x(), self.winfo_y()
            nx, ny = UIUtils._begrenzt_auf_monitor(self, x, y, self.winfo_reqwidth(), self.winfo_reqheight(),
                                                   bezug=(x, y))
            if (nx, ny) != (x, y):
                self.geometry(f"+{nx}+{ny}")

    def _pruefe_fremden_dienst(self):
        fremd = posteingang_sperre.fremd_aktiv(self.app.master_folder) if self.app.master_folder else None
        if fremd is not None:
            self.hinweis.config(text=f"Achtung: KID auf {posteingang_sperre.beschreibung(fremd)} legt gerade im "
                                     "Hintergrund ab. Rechnet er auf demselben KI-Server, werden die Zeiten zu lang.")

    def _modelle_holen(self):
        def holen():
            try:
                arten = ollama_client.modelle_nach_art(self.base_url)
            except Exception:
                arten = ([], [])
            self._stand["modelle"] = arten
        threading.Thread(target=holen, daemon=True).start()
        self.after(200, self._modelle_eintragen)

    def _modelle_eintragen(self):
        if not self.winfo_exists():
            return
        if "modelle" not in self._stand:
            self.after(200, self._modelle_eintragen)
            return
        namen, entscheider = self._stand.pop("modelle")
        cfg = self.app.config
        # Vermerke wie in den Einstellungen („Standard“, „zuletzt verwendet“); als Zweitmeinung nur Entscheidungsmodelle
        self.feld_lesen["values"] = modelle_beschriftet(namen, ollama_client.DEFAULT_MODEL, zuletzt_verwendet(
            cfg.get("ollama_model_zuletzt", ""), cfg.get("ollama_model", ollama_client.DEFAULT_MODEL)))
        self.feld_zweit["values"] = [OHNE_ZWEITMEINUNG] + modelle_beschriftet(
            entscheider, auto_pilot.STANDARD_ENTSCHEIDUNGSMODELL, zuletzt_verwendet(
                cfg.get("ki_entscheidungsmodell_zuletzt", ""), cfg.get("ki_entscheidungsmodell", "") or ""))
        if not namen:
            self.hinweis.config(text="Der KI-Server liefert keine Modellliste - ist er erreichbar?")

    # ------------------------------------------------------------------ Lauf
    def _start(self):
        lesen = modell_aus_anzeige(self.var_lesen.get())
        zweit = modell_aus_anzeige(self.var_zweit.get())
        zweit = "" if zweit in ("", OHNE_ZWEITMEINUNG) else zweit
        karte = self.var_karte.get().strip()
        if not lesen:
            self.status.config(text="Bitte ein Lese-Modell wählen.")
            return
        self.app.config.set("benchmark_grafikkarte", karte)
        self._laeuft = True
        self._stopp.clear()
        self._stand.update(text="Prüfbriefe werden ausgepackt…", erledigt=0, fertig=None)
        for knopf in (self.btn_start, self.btn_zip, self.btn_eingebaut):
            knopf.config(state=tk.DISABLED)
        self.btn_stopp.config(state=tk.NORMAL)
        self.fortschritt.config(value=0)
        dienst = getattr(self.app, "auto_pilot_service", None)
        if dienst is not None:
            dienst.pausieren()
        satz = self._satz

        def melde(phase, erledigt, gesamt):
            self._stand.update(text=f"{phase}: Dokument {erledigt + 1} von {gesamt}…", erledigt=erledigt)

        def arbeite():
            ordner = None
            try:
                summe = benchmark.pruefsumme(satz)
                ordner, pfade = benchmark.bereite_satz(satz)
                m = benchmark.lauf(pfade, self.base_url, lesen, zweit, abbrechen=self._stopp.is_set, melde=melde)
                if m["dokumente"]:
                    self._stand["fertig"] = ("ok", benchmark.zusammenfassen(
                        m, lesen, zweit, karte, APP_VERSION, satz=benchmark.satz_name(satz), pruefsumme=summe))
                else:   # kein Ergebnis - aber die Ursache gehört trotzdem in Anzeige und Protokoll (Firmen-Lauf)
                    self._stand["fertig"] = ("leer", benchmark.ursachen_text(m.get("fehler_liste", [])))
            except Exception as e:
                self._stand["fertig"] = ("fehler", str(e))
            finally:
                benchmark.raeume_satz(ordner)

        threading.Thread(target=arbeite, daemon=True).start()
        self.app.root.after(300, self._beobachte, dienst)

    def _beobachte(self, dienst):
        """Fortschritt vom Mess-Thread übernehmen (Polling statt Tk-Aufrufen aus dem Thread). Läuft über das
        Hauptfenster weiter, auch wenn dieses Fenster schon zu ist - sonst bliebe die Vollautomatik pausiert."""
        offen = bool(self.app.root.winfo_exists() and self.winfo_exists())
        fertig = self._stand.get("fertig")
        if fertig is None:
            if offen:
                self.status.config(text=self._stand.get("text", ""))
                self.fortschritt.config(value=self._stand.get("erledigt", 0))
            self.app.root.after(300, self._beobachte, dienst)
            return
        self._laeuft = False
        if dienst is not None:
            dienst.fortsetzen()
        art, inhalt = fertig
        alle = benchmark.speichere_ergebnis(self.ergebnis_pfad, inhalt) if art == "ok" else None
        log = getattr(self.app, "logger", None)
        if log is not None and art == "leer":
            log.warning("Benchmark: kein Dokument gelesen" + (f" ({inhalt})" if inhalt else ""))
        if log is not None and alle:
            log.info("Benchmark: " + benchmark.als_text(inhalt).replace("\n", "; "))
            if benchmark.protokoll_text(inhalt):
                log.info("Benchmark, Einzelheiten: " + benchmark.protokoll_text(inhalt))
        if not offen:
            return
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stopp.config(state=tk.DISABLED)
        self.btn_zip.config(state=tk.NORMAL)
        self._zeige_satz()
        if art == "fehler":
            self.status.config(text=f"Lauf fehlgeschlagen: {inhalt}")
        elif art == "leer":
            self.status.config(text="Kein Dokument gelesen" + (f" ({inhalt})" if inhalt else "")
                               + " - KI-Server oder Modell prüfen.")
        else:
            self.fortschritt.config(value=40)
            self._zeige_ergebnisse(alle)
            self.status.config(text=("Abgebrochen - " if inhalt["abgebrochen"] else "Fertig - ")
                               + f"{benchmark.wert(inhalt, 'Sekunden je Dokument')} je Dokument, "
                               f"{benchmark.wert(inhalt, 'Still falsch abgelegt')} still falsch.")

    def _kopieren(self):
        alle = benchmark.lade_ergebnisse(self.ergebnis_pfad)
        if not alle:
            return
        self.clipboard_clear()
        self.clipboard_append(benchmark.als_text(alle[-1]))
        self.status.config(text="Letztes Ergebnis kopiert - zum Einfügen in eine Rückmeldung.")

    def _schliessen(self):
        if self._laeuft:
            self._stopp.set()   # der Lauf endet nach dem laufenden Aufruf, _beobachte setzt die Vollautomatik fort
        for ordner in self._ansehen:   # ein noch offenes PDF-Programm hält die Datei - dann bleibt der Ordner liegen
            benchmark.raeume_satz(ordner)
        self.destroy()
