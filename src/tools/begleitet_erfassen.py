"""
Begleitet erfassen (KONZEPT_BEGLEITETES_ERFASSEN.md, Peter 04.11.2026) - der Prüfplatz für den Posteingang.

Dokument für Dokument in Scan-Reihenfolge (B3): das Hauptfenster zeigt das Dokument, dieses schlanke Fenster den
Vorschlag - Zielordner (grün = KID ist sicher, gelb mit Grund), Titel, Datum, Tags, Absender. Der Nutzer korrigiert
und legt mit Return ab; das nächste Dokument ist dann meist schon gelesen (im Voraus, bis zu begleitet.VORAUS) und
wird erst jetzt entschieden - mit den eben angelegten Ordnern und dem fortgeschriebenen Ablage-Gedächtnis.

Grün heißt hier nur „KID wäre sicher“ - in der Simulation waren 6-7 % der grünen Vorschläge falsch, deshalb
prüft der Nutzer auch Grün. „Rest der Vollautomatik geben“ schaltet die Hintergrund-Automatik ein, sobald die
Prognose („von den nächsten 12 gelesenen wären jetzt 9 grün“) gut genug aussieht.

Threads: ein Leser (KI, Hintergrund) und je Dokument ein kurzer Entscheider (Code + Dubletten-Prüfung); beide melden
nur über app.root.after zurück, nie Tkinter aus dem Thread. Abgelegt wird im Tk-Thread (wie die Ablage-Vorschau).
"""

import os
import queue
import threading
import time
import tkinter as tk
import tkinter.messagebox as mb
from tkinter import ttk

import ablage_gedaechtnis
import auto_pilot
import begleitet
import dubletten_pruefung
import ollama_client
import ordner_aliase
import tag_ignorierliste
from pdf_handler import PDFHandler
from tools.auto_filer import ZielordnerDialog
from tools.base_tool import BaseTool, ToolContext
from ui_utils import UIUtils

GRUEN, GELB = "#d9f2d9", "#fdf3d7"


class BegleitetFenster(tk.Toplevel):
    def __init__(self, app, pfade):
        super().__init__(app.root)
        self.withdraw()                              # erst aufbauen, dann zeigen (FALLSTRICKE #90)
        UIUtils.werkzeugfenster(self, app.root)      # über KID, nicht modal (Peter 04.11.2026)
        self.app = app
        self.title("Begleitet erfassen")
        self.pfade = list(pfade)
        self.nr = 0                                  # Index des aktuellen Dokuments in self.pfade
        self.gelesen = {}                            # Pfad -> gelesen (lies_dokument) oder Exception
        self.entscheidung = None                     # Vorschlag für das aktuelle Dokument
        self.prognose_fuer = {}                      # Pfad -> Entscheidung (nur für die Prognose)
        self.abgelegt = self.zurueckgestellt = self.uebersprungen = 0
        self._stopp = threading.Event()
        self._postfach = queue.Queue()               # Threads -> Tk-Thread (_nach_tk/_abholen)
        self._abhol_id = None
        self._entscheider_lauf = 0                   # verwirft Antworten veralteter Entscheider
        self.base_url = app.config.get("ollama_url", ollama_client.DEFAULT_URL)
        self.model = app.config.get("ollama_model", ollama_client.DEFAULT_MODEL)
        tm = getattr(app, "tag_manager", None)
        # Tag-Baum nur hier im Tk-Thread lesen (wie die Ablage-Vorschau)
        self.known_tags = tm.get_known_tags() if tm else []
        self.kategorien = tm.get_kategorien() if tm else []
        self.tag_eltern = tm.get_tag_eltern() if tm else {}
        self.synonyme = tm.get_synonyme() if tm else {}
        self.merkmale = tm.merkmale_fuer_dubletten() if tm else {}
        self.ordnerliste = auto_pilot.sammle_ordnerliste(app.master_folder)
        self.aliase = ordner_aliase.lade_aliase(app.master_folder)
        self.ignorierte = tag_ignorierliste.lade(app.master_folder)
        self.orte = set()
        self.gedaechtnis = None                      # lädt der Leser (eigene SQLite-Verbindung)
        self.vocabulary = None
        self.dubletten_cache = {}
        self.rueckfragen = begleitet.Rueckfragen()
        self._dienst = getattr(app, "auto_pilot_service", None)
        if self._dienst is not None:
            self._dienst.pausieren()                 # Prüfplatz und Vollautomatik nie gleichzeitig am Posteingang
        self._baue()
        self.protocol("WM_DELETE_WINDOW", self._schliessen)
        self.update_idletasks()                      # Höhe nach dem Inhalt (vorher viel Leerraum)
        UIUtils.position_near_mouse(self, UIUtils.px(self, 640), self.winfo_reqheight())
        self.deiconify()
        threading.Thread(target=self._leser, name="Begleitet-Leser", daemon=True).start()
        self._zeige_aktuelles()
        self._abholen()

    # ---------------------------------------------------------------- Aufbau
    def _baue(self):
        rand = UIUtils.px(self, 10)
        inhalt = ttk.Frame(self)                     # ein ttk-Rahmen: sonst graue Labels auf hellerem Fenstergrund
        inhalt.pack(fill=tk.BOTH, expand=True)
        knoepfe = ttk.Frame(inhalt)                  # Knopfleisten VOR dem Inhalt mit side=BOTTOM (CLAUDE.md)
        knoepfe.pack(side=tk.BOTTOM, fill=tk.X, padx=rand, pady=(6, rand))
        self.btn_ablegen = ttk.Button(knoepfe, text="Ablegen (Return)", command=self._ablegen)
        self.btn_ablegen.pack(side=tk.LEFT)
        ttk.Button(knoepfe, text="Überspringen", command=self._ueberspringen).pack(side=tk.LEFT, padx=6)
        self.btn_unsicher = ttk.Button(knoepfe, text=f"Nach {auto_pilot.UNSICHER_ORDNER}", command=self._zurueckstellen)
        self.btn_unsicher.pack(side=tk.LEFT)
        ttk.Button(knoepfe, text="Schließen", command=self._schliessen).pack(side=tk.RIGHT)
        self.btn_rest = ttk.Button(knoepfe, text="Rest der Vollautomatik geben…", command=self._rest_abgeben)
        self.btn_rest.pack(side=tk.RIGHT, padx=6)

        self.lbl_prognose = ttk.Label(inhalt, foreground="gray40")
        self.lbl_prognose.pack(side=tk.BOTTOM, fill=tk.X, padx=rand, pady=(6, 0))

        self.lbl_kopf = ttk.Label(inhalt, foreground="gray40")
        self.lbl_kopf.pack(fill=tk.X, padx=rand, pady=(rand, 4))
        self.lbl_status = tk.Label(inhalt, anchor="w", justify=tk.LEFT, padx=8, pady=6, bg=GELB,
                                   wraplength=UIUtils.px(self, 600))
        self.lbl_status.pack(fill=tk.X, padx=rand)
        felder = ttk.Frame(inhalt)
        felder.pack(fill=tk.X, padx=rand, pady=(8, 0))
        felder.columnconfigure(1, weight=1)
        self.eingaben = {}
        for zeile, (schluessel, text) in enumerate((("ziel", "Zielordner:"), ("titel", "Titel:"), ("datum", "Datum:"),
                                                     ("tags", "Tags:"))):
            ttk.Label(felder, text=text).grid(row=zeile, column=0, sticky="w", pady=2)
            eingabe = ttk.Entry(felder)
            eingabe.grid(row=zeile, column=1, sticky="ew", padx=(6, 0), pady=2)
            self.eingaben[schluessel] = eingabe
        self.bind("<Return>", lambda _e: self._ablegen())   # im ganzen Fenster, auch auf dem Ablegen-Knopf
        ttk.Button(felder, text="Auswählen…", command=self._ordner_waehlen).grid(row=0, column=2, padx=(6, 0))
        self.lbl_datum_hinweis = ttk.Label(felder, foreground="#a15c00")
        self.lbl_datum_hinweis.grid(row=2, column=2, sticky="w", padx=(6, 0))
        ttk.Label(felder, text="Absender:").grid(row=4, column=0, sticky="w", pady=2)
        self.lbl_absender = ttk.Label(felder, foreground="gray30")
        self.lbl_absender.grid(row=4, column=1, columnspan=2, sticky="w", padx=(6, 0), pady=2)
        ttk.Label(felder, foreground="gray40", wraplength=UIUtils.px(self, 600), justify=tk.LEFT,
                  text="Grün heißt: KID wäre sicher - bitte trotzdem kurz prüfen. Datum als TT.MM.JJJJ, Tags mit "
                       "Komma getrennt (dürfen leer bleiben).").grid(row=5, column=0, columnspan=3, sticky="w", pady=(6, 0))

    # ---------------------------------------------------------------- Lesen (Hintergrund)
    def _regeln(self):
        """Frisch je Aufruf: Ordner, Aliase, Tags und Gedächtnis wachsen mit jeder Ablage."""
        return dict(vocabulary=self.vocabulary, aliase=self.aliase, known_tags=self.known_tags,
                    kategorien=self.kategorien, ignorierte_tags=self.ignorierte, tag_eltern=self.tag_eltern,
                    synonyme=self.synonyme, gedaechtnis=self.gedaechtnis, orte=self.orte)

    def _leser(self):
        """Liest der Reihe nach voraus (KI), höchstens begleitet.VORAUS Dokumente vor dem aktuellen."""
        app = self.app
        try:
            basis = app.index_manager.wortschatz_der_sammlung() if hasattr(app, "index_manager") else None
            self.vocabulary = auto_pilot.baue_titel_wortschatz(self.pfade[:begleitet.VORAUS], basis)
        except Exception as e:
            self._log("warning", f"Begleitet erfassen: Titel-Wortschatz nicht aufgebaut: {e}")
        self.gedaechtnis = ablage_gedaechtnis.lade(getattr(app, "index_manager", None),
                                                   auto_pilot.ordner_fuer_zweitmeinung(self.ordnerliste),
                                                   getattr(app, "logger", None))
        for i, pfad in enumerate(self.pfade):
            while not self._stopp.is_set() and i > self.nr + begleitet.VORAUS:
                time.sleep(0.3)
            if self._stopp.is_set():
                return
            if not os.path.exists(pfad):          # inzwischen von Hand verschoben
                self.gelesen[pfad] = FileNotFoundError(pfad)
            else:
                try:
                    gelesen = auto_pilot.lies_dokument(pfad, self.known_tags, self.base_url, self.model,
                                                       self.kategorien)
                    auto_pilot.merke_orte(self.orte, gelesen)
                    self.gelesen[pfad] = gelesen
                except Exception as e:
                    self._log("warning", f"Begleitet erfassen: Lesen fehlgeschlagen für {pfad}: {e}")
                    self.gelesen[pfad] = e
            self._nach_tk(self._gelesen_dazu)

    def _gelesen_dazu(self):
        if self.entscheidung is None:
            self._zeige_aktuelles()
        else:
            self._kopf()
            self._prognose_anstossen()

    def _kopf(self):
        if self.nr < len(self.pfade):
            self.lbl_kopf.config(text=f"Dokument {self.nr + 1} von {len(self.pfade)}: "
                                      f"{os.path.basename(self.pfade[self.nr])}   ·   "
                                      f"{self._gelesen_voraus()} im Voraus gelesen")

    # ---------------------------------------------------------------- Entscheiden + Anzeigen
    def _zeige_aktuelles(self):
        if not self.winfo_exists():
            return
        if self.nr >= len(self.pfade):
            self._fertig()
            return
        pfad = self.pfade[self.nr]
        self._kopf()
        folder_manager = getattr(self.app, "folder_manager", None)
        if folder_manager is not None and os.path.exists(pfad):
            folder_manager.zeige_dokument(pfad)
        gelesen = self.gelesen.get(pfad)
        if gelesen is None:
            self._setze_status("Wird gelesen … (die KI braucht etwa 15 Sekunden je Dokument)", GELB)
            self._felder_sperren(True)
            return
        if isinstance(gelesen, Exception):
            self._setze_status(f"Nicht lesbar: {gelesen} - „Überspringen“ lässt es im Posteingang.", GELB)
            self._felder_sperren(True)
            return
        self._setze_status("Wird entschieden …", GELB)
        self._felder_sperren(True)
        self._entscheider_lauf += 1
        lauf = self._entscheider_lauf
        threading.Thread(target=self._entscheide, args=(lauf, gelesen), daemon=True).start()

    def _entscheide(self, lauf, gelesen):
        try:
            e = auto_pilot.entscheide_gelesen(gelesen, self.ordnerliste, self.base_url, **self._regeln())
            try:
                dubletten_pruefung.pruefe_entscheidung(
                    e, self.app.master_folder, self.merkmale, self.dubletten_cache,
                    ki_pruefung=lambda neu, alt: auto_pilot.pruefe_dublette_per_ki(neu, alt, self.base_url, self.model))
            except Exception as fehler:
                self._log("warning", f"Begleitet erfassen: Dubletten-Prüfung fehlgeschlagen: {fehler}")
            scan = PDFHandler.scan_tag(gelesen["pdf_path"])      # Vorschlag, falls kein Datum erkannt
        except Exception as fehler:
            e, scan = fehler, ""
        self._nach_tk(self._entschieden, lauf, e, scan)

    def _entschieden(self, lauf, e, scan=""):
        if lauf != self._entscheider_lauf or not self.winfo_exists():
            return
        if isinstance(e, Exception):
            self._setze_status(f"Entscheidung fehlgeschlagen: {e}", GELB)
            return
        self.entscheidung = e
        self._felder_sperren(False)
        datum, ist_scan = begleitet.datum_vorschlag(e, scan)
        self.lbl_datum_hinweis.config(text="Scandatum - kein Datum im Dokument erkannt" if ist_scan else "")
        werte = {"ziel": e["zielordner"], "titel": e["titel"], "datum": datum, "tags": ", ".join(e["tags"])}
        for schluessel, wert in werte.items():
            self.eingaben[schluessel].delete(0, tk.END)
            self.eingaben[schluessel].insert(0, wert or "")
        self.lbl_absender.config(text=e.get("absender") or "(keiner gelesen)")
        self._setze_status(self._statustext(e), GRUEN if e["sicher"] else GELB)
        feld = begleitet.feld_fuer_problem(e)
        if feld:                                     # gleich dorthin, wo etwas fehlt („2024-09-XX“ -> Datum)
            self.eingaben[feld].focus_set()
            self.eingaben[feld].select_range(0, tk.END)
        else:
            self.btn_ablegen.focus_set()             # grün: Return legt ab
        self._prognose_anstossen()

    def _statustext(self, e):
        if e["ordner_neu"]:
            ordner = "neuer Ordner"
        elif e.get("ordner_per_alias"):
            ordner = "Ordner per Alias"
        elif e.get("ordner_gedaechtnis"):
            ordner = f"Ordner aus dem Gedächtnis ({e['ordner_gedaechtnis']} Dokumente)"
        else:
            ordner = "Ordner nach dem Namen"
        if e["sicher"]:
            return f"Grün: KID wäre sicher ({ordner}). Bitte trotzdem kurz prüfen."
        return f"Gelb ({ordner}): " + "; ".join(e["probleme"])

    def _prognose_anstossen(self):
        """Wie viele der schon gelesenen nächsten Dokumente wären mit dem jetzigen Stand grün? Reiner Code, im Thread."""
        if self._stopp.is_set():
            return
        naechste = [p for p in self.pfade[self.nr + 1:self.nr + 1 + begleitet.VORAUS]
                    if isinstance(self.gelesen.get(p), dict)]

        def rechnen():
            entscheidungen = []
            for p in naechste:
                try:
                    entscheidungen.append(auto_pilot.entscheide_gelesen(self.gelesen[p], self.ordnerliste,
                                                                        self.base_url, **self._regeln()))
                except Exception:
                    entscheidungen.append(None)
            self._nach_tk(self._zeige_prognose, begleitet.prognose(entscheidungen))

        threading.Thread(target=rechnen, daemon=True).start()

    def _zeige_prognose(self, zahlen):
        gruen, gesamt = zahlen
        if not self.winfo_exists():
            return
        if gesamt:
            self.lbl_prognose.config(text=f"Von den nächsten {gesamt} schon gelesenen Dokumenten wären mit dem "
                                          f"jetzigen Stand {gruen} grün.")
        else:
            self.lbl_prognose.config(text="")

    # ---------------------------------------------------------------- Aktionen
    def _ordner_waehlen(self):
        if self.entscheidung is None:
            return
        self._ordnerliste_auffrischen()
        dialog = ZielordnerDialog(self, self.ordnerliste, self.eingaben["ziel"].get(),
                                  self.entscheidung.get("absender") or "", mit_reichweite=False)
        self.wait_window(dialog)
        if dialog.ergebnis:
            self.eingaben["ziel"].delete(0, tk.END)
            self.eingaben["ziel"].insert(0, dialog.ergebnis)

    def _ordnerliste_auffrischen(self):
        """Im Hauptfenster angelegte Ordner aufnehmen (nur ergänzen - der Entscheider-Thread liest dieselbe Liste)."""
        try:
            for ordner in auto_pilot.sammle_ordnerliste(self.app.master_folder):
                if ordner not in self.ordnerliste:
                    self.ordnerliste.append(ordner)
        except OSError:
            pass

    def _ablegen(self):
        if self.entscheidung is None:
            return
        self._ordnerliste_auffrischen()
        e, offen = begleitet.uebernimm(
            self.entscheidung, self.eingaben["ziel"].get(), self.eingaben["titel"].get(),
            self.eingaben["datum"].get(), self.eingaben["tags"].get(), self.ordnerliste, self.known_tags,
            self.kategorien)
        if offen:
            mb.showinfo("Erst ergänzen", "Zum Ablegen fehlt noch:\n\n- " + "\n- ".join(offen), parent=self)
            return
        if e["ordner_neu"] and not mb.askyesno(
                "Neuer Ordner", f"Den Ordner „{e['zielordner']}“ gibt es noch nicht.\n\nAnlegen und dort ablegen?",
                parent=self):
            return
        vorschlag = self.entscheidung
        if self._fuehre_aus(e):
            self.abgelegt += 1
            frage = self.rueckfragen.nach_ablage(vorschlag, e, self.gedaechtnis, self.aliase)   # B4/B5
            absender = (e.get("absender") or "").strip()
            if absender and self.gedaechtnis is not None:
                self.gedaechtnis.stimme(absender, e["zielordner"])   # wie der Dienst nach jeder sicheren Ablage
            if frage:
                self._rueckfrage(frage)
            if e["zielordner"] not in self.ordnerliste:
                self.ordnerliste.append(e["zielordner"])
            for tag, _kategorie in e.get("neue_tags", []):
                if tag.lower() not in {k.lower() for k in self.known_tags}:
                    self.known_tags.append(tag)
            self._weiter()

    def _rueckfrage(self, frage):
        """B4/B5: ja = Alias (wirkt ab dem nächsten Dokument, auch in der Vollautomatik), nein = in diesem Durchgang
        nicht wieder fragen."""
        titel = "Gleicher Absender?" if frage["art"] == "Absender" else "Immer dorthin?"
        if not mb.askyesno(titel, frage["text"], parent=self):
            self.rueckfragen.abgelehnt_merken(frage)
            return
        try:
            self.aliase = ordner_aliase.speichere_alias(self.app.master_folder, frage["schluessel"], frage["ordner"])
        except OSError as fehler:
            self.aliase[frage["schluessel"]] = frage["ordner"]
            mb.showwarning("Nicht gespeichert", f"Gilt für diesen Durchgang, ließ sich aber nicht dauerhaft "
                                                f"merken:\n{fehler}", parent=self)
        self._log("info", f"Begleitet erfassen: {frage['art']}-Alias -> {frage['ordner']}")

    def _zurueckstellen(self):
        if self.entscheidung is None:
            return
        if self._fuehre_aus(begleitet.zurueckstellen(self.entscheidung)):
            self.zurueckgestellt += 1
            self._weiter()

    def _ueberspringen(self):
        if self.nr < len(self.pfade):
            self.uebersprungen += 1
            self._weiter()

    def _fuehre_aus(self, e):
        """Wie „Jetzt einsortieren“ der Ablage-Vorschau, für ein Dokument (Tk-Thread, is_moving gesetzt)."""
        app = self.app
        app.is_moving = True
        try:
            ergebnis = auto_pilot.fuehre_entscheidung_aus(
                e, app.master_folder, app.file_ops._verschiebe_ohne_duplikat,
                umbenennen=bool(app.config.get("auto_pilot_umbenennen", True)))
        finally:
            app.is_moving = False
        auto_pilot.protokolliere_ergebnis(e, ergebnis, app.master_folder, getattr(app, "logger", None))
        if not ergebnis["erfolg"]:
            mb.showerror("Nicht abgelegt", f"Das Dokument ließ sich nicht ablegen:\n{ergebnis['fehler']}", parent=self)
            return False
        self._log("info", f"Begleitet erfassen: {os.path.basename(e['pdf_path'])} -> {ergebnis['neuer_pfad']}")
        if hasattr(app, "tool_manager"):
            app.tool_manager.notify_file_moved(e["pdf_path"], ergebnis["neuer_pfad"])
        if e["sicher"] and hasattr(app, "tag_manager") and e.get("neue_tags"):
            app.tag_manager.add_tags_to_catalog(e["neue_tags"])   # von Hand eingetragen, ohne Warteliste (Etappe 6)
        folder_manager = getattr(app, "folder_manager", None)
        if folder_manager is not None:
            folder_manager.refresh_folder_tree()                # neuer Ordner sofort links sichtbar
        return True

    def _weiter(self):
        self.nr += 1
        self.entscheidung = None
        for eingabe in self.eingaben.values():
            eingabe.delete(0, tk.END)
        self.lbl_absender.config(text="")
        self.lbl_datum_hinweis.config(text="")
        self._zeige_aktuelles()

    def _rest_abgeben(self):
        rest = len(self.pfade) - self.nr
        if not rest:
            return
        if not mb.askyesno(
                "Rest der Vollautomatik geben",
                f"Die restlichen {rest} Dokumente im Posteingang legt dann die Vollautomatik im Hintergrund ab - "
                f"sichere in ihren Ordner, unsichere nach {auto_pilot.UNSICHER_ORDNER}.\n\n"
                "Prüfplatz schließen und die Vollautomatik einschalten?", parent=self):
            return
        dienst = self._dienst                    # _schliessen gibt ihn frei
        self._schliessen()
        if not bool(self.app.config.get("auto_pilot_enabled", False)):
            self.app.config.set("auto_pilot_enabled", True)
        if dienst is not None:
            dienst.anstossen()                   # öffnet auch das Statusfenster der Vollautomatik

    def _fertig(self):
        self._setze_status(f"Fertig: {self.abgelegt} abgelegt, {self.zurueckgestellt} nach "
                           f"{auto_pilot.UNSICHER_ORDNER}, {self.uebersprungen} übersprungen.", GRUEN)
        self.lbl_kopf.config(text="Der Posteingang ist durch.")
        self.lbl_prognose.config(text="")
        self._felder_sperren(True)

    def _schliessen(self):
        if not self.winfo_exists():
            return
        self._stopp.set()
        if self._abhol_id is not None:
            self.after_cancel(self._abhol_id)        # sonst „invalid command name …_abholen“ nach dem Schließen
            self._abhol_id = None
        if self._dienst is not None:
            self._dienst.fortsetzen()
            self._dienst = None
        self.destroy()

    # ---------------------------------------------------------------- Helfer
    def _gelesen_voraus(self):
        return sum(1 for p in self.pfade[self.nr + 1:] if p in self.gelesen)

    def _setze_status(self, text, farbe):
        self.lbl_status.config(text=text, bg=farbe)

    def _felder_sperren(self, gesperrt):
        zustand = tk.DISABLED if gesperrt else tk.NORMAL
        for eingabe in self.eingaben.values():
            eingabe.config(state=zustand)
        self.btn_ablegen.config(state=zustand)
        self.btn_unsicher.config(state=zustand)

    def _nach_tk(self, fn, *args):
        """Aus einem Thread zurück in den Tk-Thread: über das Postfach, das _abholen im Tk-Thread leert - ein
        root.after aus dem Thread scheitert, solange Tk nicht in der mainloop steht (Test), und dann still."""
        if not self._stopp.is_set():
            self._postfach.put((fn, args))

    def _abholen(self):
        if not self.winfo_exists():
            return
        while True:
            try:
                fn, args = self._postfach.get_nowait()
            except queue.Empty:
                break
            fn(*args)
            if not self.winfo_exists():
                return
        self._abhol_id = self.after(100, self._abholen)

    def _log(self, stufe, text):
        logger = getattr(self.app, "logger", None)
        if logger is not None:
            getattr(logger, stufe)(text)


class BegleitetErfassenTool(BaseTool):
    """Menü-Einstieg: den Posteingang Dokument für Dokument erfassen (Prüfplatz)."""

    def __init__(self):
        self.fenster = None

    @property
    def name(self) -> str:
        return "Vollautomatik: Begleitet erfassen"

    @property
    def menu_group(self) -> str:
        return "Vollautomatik"

    @property
    def menu_label(self) -> str:
        return "Begleitet erfassen (Posteingang)…"

    @property
    def absicht(self) -> str:
        return ("Eine neue oder große Sammlung unter Aufsicht aufbauen: jedes Dokument wird gesehen und mit einem "
                "Klick abgelegt oder korrigiert - nichts landet unbemerkt im falschen Ordner. Wenn die Vorschläge "
                "meist stimmen, übernimmt die Vollautomatik den Rest.")

    @property
    def description(self) -> str:
        return ("Geht den Posteingang Dokument für Dokument durch: zeigt das Dokument im Hauptfenster und den "
                "Vorschlag (Zielordner, Titel, Datum, Tags) zum Prüfen und Korrigieren; Return legt ab. Das nächste "
                "Dokument wird schon im Voraus gelesen.")

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
        app = context.app
        if auto_pilot.finde_posteingang(app.master_folder) is None:
            mb.showinfo("Kein Posteingang gefunden",
                        f"In dieser Sammlung gibt es keinen Ordner „{auto_pilot.POSTEINGANG_ORDNER}“.", parent=app.root)
            return False
        pfade = auto_pilot.sammle_posteingang_dokumente(app.master_folder)
        if not pfade:
            mb.showinfo("Posteingang ist leer", "Im Posteingang liegen keine Dokumente.", parent=app.root)
            return False
        if self.fenster is not None and self.fenster.winfo_exists():
            self.fenster.lift()
            return True
        self.fenster = BegleitetFenster(app, pfade)
        return True
