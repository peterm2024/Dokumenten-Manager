"""
Werkzeug „Benchmark“ (Etappe 13 Schritt 3, KONZEPT_BENCHMARK.md): misst mit den 40 Prüfdokumenten, wie schnell die
Vollautomatik mit den gewählten Modellen auf dem eingestellten KI-Server ablegt. Die Logik steht in `benchmark`
(ohne Oberfläche), hier nur das Fenster: Modelle und Grafikkarte wählen, Start/Abbrechen, Fortschritt, die
letzten drei Läufe nebeneinander, „Ergebnis kopieren“ für Rückmeldungen.

Während des Laufs pausiert die Vollautomatik dieses KID (F5); überwacht ein Dienst auf einem anderen Rechner den
Posteingang, warnt das Fenster - er rechnet auf demselben Server mit und verfälscht die Zeiten.
"""
import threading
import tkinter as tk
from tkinter import ttk

import app_paths
import auto_pilot
import benchmark
import ollama_client
import posteingang_sperre
from help_window import APP_VERSION
from tools.base_tool import BaseTool, ToolContext
from tools.settings_editor import auswahlfeld, modell_aus_anzeige, modelle_beschriftet, zuletzt_verwendet
from ui_utils import UIUtils

OHNE_ZWEITMEINUNG = "(ohne Zweitmeinung)"
SEKUNDEN_JE_DOKUMENT = 10   # grobe Schätzung für den Hinweis vor dem Start (5060 Ti mit beiden Modellen: ~9 s)


class BenchmarkTool(BaseTool):
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
        self.window = UIUtils.einzelfenster("benchmark", lambda: BenchmarkFenster(context.app))
        return True


class BenchmarkFenster(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.withdraw()   # unsichtbar aufbauen, dann platzieren (FALLSTRICKE #90)
        self.app = app
        self.title("Benchmark")
        UIUtils.werkzeugfenster(self, app.root)
        cfg = app.config
        self.base_url = cfg.get("ollama_url", ollama_client.DEFAULT_URL)
        self.ergebnis_pfad = app_paths.benchmark_path(app.master_folder)
        self._laeuft = False
        self._stopp = threading.Event()
        self._stand = {}          # vom Mess-Thread geschrieben, vom Hauptthread gelesen (kein Tk im Thread)

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
        self.hinweis = ttk.Label(self, foreground="#a33", wraplength=breite, justify=tk.LEFT)
        self.hinweis.pack(fill=tk.X, padx=10, pady=(4, 0))

        rahmen = ttk.Frame(self)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=10, pady=6)
        self.tabelle = ttk.Treeview(rahmen, columns=("wert", "l1", "l2", "l3"), show="headings",
                                    height=len(benchmark.ZEILEN), selectmode="none")
        self.tabelle.heading("wert", text="")
        self.tabelle.column("wert", width=UIUtils.px(self, 170), anchor="w", stretch=False)
        for spalte in ("l1", "l2", "l3"):
            self.tabelle.column(spalte, width=UIUtils.px(self, 200), anchor="w")
        self.tabelle.pack(fill=tk.BOTH, expand=True)

        self.protocol("WM_DELETE_WINDOW", self._schliessen)
        self.bind("<Escape>", lambda e: self._schliessen())
        self._zeige_ergebnisse(letzte)
        self._pruefe_fremden_dienst()
        self._modelle_holen()
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
        self.btn_kopieren.config(state=tk.NORMAL if drei else tk.DISABLED)
        if not self._laeuft:
            self.status.config(text="Noch kein Lauf." if not drei else
                               f"Ein Lauf dauert mit 40 Dokumenten etwa {40 * SEKUNDEN_JE_DOKUMENT // 60} Minuten.")

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
        self._stand.update(text="Prüfdokumente werden erzeugt…", erledigt=0, fertig=None)
        self.btn_start.config(state=tk.DISABLED)
        self.btn_stopp.config(state=tk.NORMAL)
        self.fortschritt.config(value=0)
        dienst = getattr(self.app, "auto_pilot_service", None)
        if dienst is not None:
            dienst.pausieren()

        def melde(phase, erledigt, gesamt):
            self._stand.update(text=f"{phase}: Dokument {erledigt + 1} von {gesamt}…", erledigt=erledigt)

        def arbeite():
            ordner = None
            try:
                ordner, pfade = benchmark.bereite_satz()
                m = benchmark.lauf(pfade, self.base_url, lesen, zweit, abbrechen=self._stopp.is_set, melde=melde)
                ergebnis = benchmark.zusammenfassen(m, lesen, zweit, karte, APP_VERSION) if m["dokumente"] else None
                self._stand["fertig"] = ("ok", ergebnis)
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
        alle = benchmark.speichere_ergebnis(self.ergebnis_pfad, inhalt) if art == "ok" and inhalt else None
        log = getattr(self.app, "logger", None)
        if log is not None and alle:
            log.info("Benchmark: " + benchmark.als_text(inhalt).replace("\n", "; "))
        if not offen:
            return
        self.btn_start.config(state=tk.NORMAL)
        self.btn_stopp.config(state=tk.DISABLED)
        if art == "fehler":
            self.status.config(text=f"Lauf fehlgeschlagen: {inhalt}")
        elif inhalt is None:
            self.status.config(text="Kein Dokument gelesen - KI-Server oder Modell prüfen.")
        else:
            self.fortschritt.config(value=40)
            self._zeige_ergebnisse(alle)
            self.status.config(text=("Abgebrochen - " if inhalt["abgebrochen"] else "Fertig - ")
                               + f"{benchmark.ZEILEN[5][1](inhalt)} je Dokument.")

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
        self.destroy()
