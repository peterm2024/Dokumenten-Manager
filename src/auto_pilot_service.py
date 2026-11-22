"""
Watchdog-Vollautomatik - Seniorenmodus Schritt 4 (KONZEPT_SENIORENMODUS.md).

Ein Hintergrund-Thread verarbeitet neue PDFs im Posteingang OHNE Knopfdruck: der
Ordner-Wächter (folder_monitor) weckt ihn bei jeder Dateisystem-Änderung, zusätzlich
schaut er alle PRUEF_INTERVALL Sekunden von selbst nach (KI-Server war weg, Datei war
noch gesperrt). Pro Dokument läuft dieselbe Pipeline wie beim manuellen "Posteingang
verarbeiten": auto_pilot.analysiere_dokument -> fuehre_entscheidung_aus.

Regeln, die hier gelten, weil KEIN Mensch danebensitzt:
- Nur aktiv, wenn "auto_pilot_enabled" in den Einstellungen gesetzt ist (wird in jeder
  Runde neu gelesen - Umschalten wirkt sofort, ohne Neustart).
- Nie eine Messagebox aus diesem Thread (Tkinter ist nicht thread-sicher): Schreib-
  fehler laufen über den stillen Pfad (write_custom_metadata(still=True)) ins Log.
- Nur den Dateibaum LESEN; alles, was Tkinter berührt (bekannte Tags aus dem Tag-Baum,
  Tool-Benachrichtigungen), läuft über root.after auf dem Hauptthread.
- Eine Datei gilt erst als "fertig", wenn sie STABIL_MINDESTALTER Sekunden unverändert
  ist und sich öffnen lässt - der Scanner schreibt in Schüben.
- KI-Server nicht erreichbar -> Dokumente bleiben liegen, EIN Log-Eintrag (nicht jede
  Minute einer), nächster Versuch in der nächsten Runde. Fehler bei einer Datei ->
  Wiederholung erst nach WIEDERHOLUNG_NACH_FEHLER Sekunden, damit ein kaputtes PDF den
  Server nicht in Dauerschleife beschäftigt.
- Pause, solange ein Vollautomatik-Vorschaufenster offen ist (sonst würden Mensch und
  Dienst dieselben Dateien bearbeiten).
- Jede Aktion landet zusätzlich im angehörigenfreundlichen Protokoll
  (app_paths.protokoll_path): eine Zeile pro Dokument, ohne Technik-Kauderwelsch.
"""

import os
import aktivitaet
import threading
import time
from datetime import datetime

import ablage_gedaechtnis
import app_paths
import auto_pilot
import ollama_client
import ordner_aliase
import ordner_steckbrief
import tag_ignorierliste
import posteingang_sperre
import tag_katalog
import vollautomatik_fenster
import wissen

RUHEZEIT_NACH_EREIGNIS = 3.0       # Sekunden ohne weiteres Dateisystem-Ereignis, bevor eine Runde startet
STABIL_MINDESTALTER = 5.0          # Sekunden seit der letzten Änderung, bevor eine Datei als fertig gilt
PRUEF_INTERVALL = 60.0             # Sekunden: Fallback-Runde ohne Ereignis
NACHPRUEFEN_NACH = STABIL_MINDESTALTER + 1.0   # Sekunden: nächste Runde, wenn noch unfertige Dateien liegen
WIEDERHOLUNG_NACH_FEHLER = 600.0   # Sekunden bis zum nächsten Versuch bei derselben Datei
HAUPTTHREAD_TIMEOUT = 5.0          # Sekunden, die auf eine Antwort des Hauptthreads gewartet wird
# Stapelbetrieb je Modell (28.10.2026): so viele Dokumente liest das Lesemodell am Stück, bevor das
# Entscheidungsmodell ihre Zweitmeinungen holt - Ollama lädt dann ~2x je Stapel um statt ~2x je Dokument.
# Klein genug, dass die ersten Ablagen bald kommen und neu angelegte Ordner bald zur Wahl stehen.
STAPEL_GROESSE = 10
CONFIG_KEY = "auto_pilot_enabled"


class AutoPilotService:
    """Hintergrund-Dienst; eine_runde() ist die synchron testbare Kernlogik."""

    def __init__(self, app, immer_an=False):
        """:param immer_an: Dienstmodus (dienstmodus.py) - läuft unabhängig von `auto_pilot_enabled`."""
        self.app = app
        self._immer_an = immer_an
        self._ereignis = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._pausen = 0
        self._in_runde = False         # eine_runde läuft gerade (beschaeftigt())
        self._unfertige = 0            # Posteingang-Dateien, die in der letzten Runde noch nicht fertig waren
        self._naechster_versuch = {}   # Pfad -> time.monotonic(), vor dem nicht erneut versucht wird
        self._entscheidungsmodell = ""  # Zweitmeinung dieser Runde (auto_pilot.wirksames_entscheidungsmodell)
        self._server_gemeldet = False  # "nicht erreichbar" steht schon im Log
        self._cpu_gemeldet = False     # "rechnet ohne Grafikkarte" steht schon im Log/Protokoll
        self._cpu_erlaubt_gemeldet = False  # dito für den zugelassenen, langsamen CPU-Betrieb
        self._angezeigt_gemeldet = set()  # Pfade, deren "wird gerade angezeigt"-Hinweis schon im Log steht
        self._katalog_gemeldet = False # "tags.json nicht lesbar" steht schon im Log
        self._fremd_gemeldet = False   # "anderer Rechner überwacht den Posteingang" steht schon im Log
        self.letzte_runde = None
        self.verarbeitet = 0           # Dokumente seit Programmstart
        self._heute = (None, 0, 0)     # (Datum, abgelegt, unsicher) - Zähler im Statusfenster (Etappe 10)
        self._analyse_dauer = 30.0     # gleitende Schätzung der KI-Antwortzeit (für den Countdown im Statusfenster)
        self.orte = set()              # bisher gelesene KI-Orte (auto_pilot.merke_orte), bis zum Programmende;
                                       # die Ablage-Vorschau teilt die Menge (tools/auto_filer.py)

    # ------------------------------------------------------------------ Lebenszyklus
    def start(self):
        """Thread starten und beim Ordner-Wächter als Zuhörer anmelden (mehrfach aufrufbar)."""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        monitor = getattr(self.app, "monitor", None)
        if monitor is not None and hasattr(monitor, "add_listener"):
            monitor.add_listener(self.on_filesystem_event)
        # Erste Runde gleich nach dem Start (nach RUHEZEIT_NACH_EREIGNIS), nicht erst nach
        # PRUEF_INTERVALL: Post, die bei geschlossener App eingelegt wurde, lag sonst nach
        # jedem Start eine Minute herum, ohne dass sich etwas tat (Betatest 25.10.2026).
        self._ereignis.set()
        self._thread = threading.Thread(target=self._schleife, name="Vollautomatik", daemon=True)
        self._thread.start()
        self._sync_fenster(beim_start=True)

    def stop(self):
        self._stop.set()
        self._ereignis.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def on_filesystem_event(self):
        """Vom Watchdog-Thread: nur wecken, nichts tun."""
        self._ereignis.set()

    def anstossen(self):
        """Sofort eine Runde auslösen (z.B. nach dem Einschalten in den Einstellungen); gleicht auch das Statusfenster ab."""
        self._ereignis.set()
        self._sync_fenster()

    def pausieren(self):
        """Solange ein Vollautomatik-Fenster offen ist, bleibt der Dienst stehen (zählend, verschachtelbar)."""
        self._pausen += 1

    def fortsetzen(self):
        self._pausen = max(0, self._pausen - 1)
        self._ereignis.set()

    def beschaeftigt(self):
        """True, solange eine Runde läuft oder ein Vollautomatik-Fenster/Werkzeug den Dienst pausiert hat."""
        return self._in_runde or self._pausen > 0

    def ist_aktiv(self):
        """Einstellung wird bei jeder Abfrage neu gelesen - Umschalten wirkt ohne Neustart. Im Dienstmodus immer an."""
        if self._immer_an:
            return True
        try:
            return bool(self.app.config.get(CONFIG_KEY, False))
        except Exception:
            return False

    # ------------------------------------------------------------------ Schleife
    def naechste_wartezeit(self):
        """
        Wie lange bis zur nächsten Runde ohne neues Ereignis? Lag in der letzten Runde eine noch
        unfertige Datei (jünger als STABIL_MINDESTALTER), kurz danach nachsehen - sonst wartete eine
        frisch gescannte Datei bis zur nächsten Fallback-Runde, also rund eine Minute statt ~10 s
        (Release-Check T0.13, 25.10.2026: die Ruhezeit nach dem Ereignis ist kürzer als das Mindestalter).
        """
        return NACHPRUEFEN_NACH if self._unfertige else PRUEF_INTERVALL

    def _schleife(self):
        while not self._stop.is_set():
            geweckt = self._ereignis.wait(self.naechste_wartezeit())
            if self._stop.is_set():
                return
            if geweckt:
                # Scanner schreiben in Schüben: solange weitere Ereignisse eintrudeln, warten.
                self._ereignis.clear()
                while self._ereignis.wait(RUHEZEIT_NACH_EREIGNIS):
                    self._ereignis.clear()
                    if self._stop.is_set():
                        return
            try:
                self.eine_runde()
            except Exception as e:
                self._log("warning", f"Vollautomatik-Runde abgebrochen: {e}")

    # ------------------------------------------------------------------ Kernlogik
    def eine_runde(self):
        """
        Eine Verarbeitungsrunde: fertige Posteingang-Dokumente analysieren und ablegen.
        Synchron und ohne Thread aufrufbar (Tests). :return: Anzahl verarbeiteter Dokumente
        """
        self._in_runde = True
        try:
            return self._runde()
        finally:
            self._in_runde = False

    def _runde(self):
        self.letzte_runde = datetime.now()
        self._unfertige = 0
        if not self.ist_aktiv() or self._pausen > 0:
            return 0
        master = getattr(self.app, "master_folder", None)
        if not master or not os.path.isdir(master):
            return 0
        if not self._immer_an and self._fremd_ueberwacht(master):
            return 0
        faellige = [p for p in auto_pilot.sammle_posteingang_dokumente(master) if self._faellig(p)]
        kandidaten = [p for p in faellige if self._ist_stabil(p)]
        self._unfertige = len(faellige) - len(kandidaten)
        if not kandidaten:
            self._status("warten")
            return 0

        base_url = self.app.config.get("ollama_url", ollama_client.DEFAULT_URL)
        model = self.app.config.get("ollama_model", ollama_client.DEFAULT_MODEL)
        if not ollama_client.is_reachable(base_url):
            if not self._server_gemeldet:
                self._log("warning", f"Vollautomatik: KI-Server {base_url} nicht erreichbar - "
                                     f"{len(kandidaten)} Dokument(e) bleiben im Posteingang liegen.")
                # Auch ins Angehörigen-Protokoll - sonst sieht dort niemand, warum Post liegen
                # blieb (Betatest 25.10.2026; der Grafikkarten-Ausfall stand schon drin).
                self._protokolliere(master, "WARNUNG   KI-Server nicht erreichbar - Post bleibt im Posteingang, "
                                            "bis der Server wieder da ist (Rechner/Netzwerk prüfen)")
                self._server_gemeldet = True
            self._status("server_weg")
            return 0
        if self._server_gemeldet:
            self._log("info", "Vollautomatik: KI-Server wieder erreichbar.")
            self._protokolliere(master, "OK        KI-Server wieder erreichbar - Ablage läuft weiter")
            self._server_gemeldet = False

        # Rechnet das Modell auf der Grafikkarte? Nach dem Treiber-Vorfall vom 12.09.2026
        # (FALLSTRICKE #67) lief der Server STILL auf der CPU: erreichbar, Modell da, aber
        # jeder Bild-Aufruf brauchte Minuten und endete im Timeout - und die Vollautomatik
        # hätte das alle 10 Minuten wiederholt und den Server dabei heiß gerechnet. Deshalb:
        # ohne Grafikkarte pausieren, einmal laut melden (Log, Angehörigen-Protokoll,
        # Statusfenster) und jede Runde neu prüfen. "teilweise"/"unbekannt" bremsen nicht.
        status, details = ollama_client.gpu_status(base_url, model)
        if status == "cpu" and bool(self.app.config.get("ki_cpu_erlauben", False)):
            # Einstellung "KI ohne Grafikkarte zulassen" (Beta-Vorbereitung 13.09.2026):
            # nicht pausieren, nur EINMAL im Log und Protokoll festhalten, dass es langsam wird.
            if not self._cpu_erlaubt_gemeldet:
                self._log("info", f"Vollautomatik: KI-Server {base_url} rechnet ohne Grafikkarte ({details}) - "
                                  "laut Einstellung zugelassen, jede Ablage dauert entsprechend länger.")
                self._protokolliere(master, "HINWEIS   KI-Server rechnet ohne Grafikkarte (laut Einstellung "
                                            "zugelassen) - die Ablage läuft, aber deutlich langsamer")
                self._cpu_erlaubt_gemeldet = True
        elif status == "cpu":
            if not self._cpu_gemeldet:
                self._log("warning", f"Vollautomatik: KI-Server {base_url} rechnet ohne Grafikkarte ({details}) - "
                                     f"{len(kandidaten)} Dokument(e) bleiben im Posteingang liegen. Auf dem Server "
                                     "nvidia-smi prüfen, bei „Driver/library version mismatch“ die VM neu starten "
                                     "(FALLSTRICKE #67).")
                self._protokolliere(master, "WARNUNG   KI-Server rechnet ohne Grafikkarte - Ablage pausiert, "
                                            "bis die Grafikkarte wieder da ist (Server prüfen: nvidia-smi)")
                self._cpu_gemeldet = True
            self._status("gpu_weg", details=details)
            return 0
        if status != "cpu" and (self._cpu_gemeldet or self._cpu_erlaubt_gemeldet):
            self._log("info", f"Vollautomatik: KI-Server rechnet wieder auf der Grafikkarte ({details}).")
            self._protokolliere(master, "OK        KI-Server rechnet wieder auf der Grafikkarte - Ablage läuft weiter")
            self._cpu_gemeldet = False
            self._cpu_erlaubt_gemeldet = False

        katalog = self._lies_katalog(master)
        known_tags, kategorien, tag_eltern, synonyme = (katalog["known_tags"], katalog["kategorien"],
                                                        katalog["tag_eltern"], katalog["synonyme"])
        ordnerliste = auto_pilot.sammle_ordnerliste(master)
        aliase = ordner_aliase.lade_aliase(master)
        ignorierte = tag_ignorierliste.lade(master)
        index_manager = getattr(self.app, "index_manager", None)
        gedaechtnis = ablage_gedaechtnis.lade(index_manager, auto_pilot.ordner_fuer_zweitmeinung(ordnerliste),
                                              getattr(self.app, "logger", None))
        # Ordner-Steckbriefe (Etappe 9): beim ersten Mal liest der Abgleich den Volltext der ganzen Sammlung
        with aktivitaet.phase("Vollautomatik: Ordner-Steckbriefe aus dem Volltext…"):
            steckbriefe = ordner_steckbrief.lade(
                index_manager, auto_pilot.ordner_fuer_zweitmeinung(ordnerliste),
                ausgeschlossen=wissen.ausgeschlossene_merkmale(master, getattr(self.app, "logger", None)),
                logger=getattr(self.app, "logger", None))
        vocabulary = None
        try:
            basis = index_manager.wortschatz_der_sammlung() if index_manager is not None else None
            vocabulary = auto_pilot.baue_titel_wortschatz(kandidaten, basis)
        except Exception as e:
            self._log("warning", f"Vollautomatik: Titel-Wortschatz nicht verfügbar: {e}")

        # Zweitmeinung: je Runde einmal bestimmt (Standard an, wenn der Server das Modell hat - 15.11.2026)
        self._entscheidungsmodell = auto_pilot.wirksames_entscheidungsmodell(self.app.config, base_url)
        anzahl = 0
        self._status("runde", gesamt=len(kandidaten))
        kontext = dict(known_tags=known_tags, kategorien=kategorien, tag_eltern=tag_eltern, synonyme=synonyme,
                       vocabulary=vocabulary, aliase=aliase, ignorierte_tags=ignorierte, gedaechtnis=gedaechtnis,
                       orte=self.orte)
        # Stapelbetrieb je Modell: erst alle Dokumente des Stapels lesen (Lesemodell), dann alle
        # Zweitmeinungen holen (Entscheidungsmodell), dann der Reihe nach entscheiden und ablegen -
        # Gedächtnis und neue Ordner zählen dabei wie bisher nach jeder Ablage sofort mit.
        for anfang in range(0, len(kandidaten), STAPEL_GROESSE):
            if self._abbrechen():
                break
            stapel = self._lies_stapel(kandidaten, anfang, base_url, model, kontext)
            ordner_stand = len(ordnerliste)   # die Liste wächst nur hinten (neue Ordner dieser Runde)
            ranglisten = self._hole_zweitmeinungen(stapel, master, ordnerliste, base_url, kontext, len(kandidaten))
            for nummer, gelesen in stapel:
                if self._abbrechen():
                    break
                if self._verarbeite(gelesen["pdf_path"], master, known_tags, ordnerliste, base_url, model, vocabulary,
                                    aliase, kategorien, ignorierte, nummer=nummer, gesamt=len(kandidaten),
                                    tag_eltern=tag_eltern, synonyme=synonyme,
                                    gedaechtnis=gedaechtnis, gelesen=gelesen,
                                    rangliste=ranglisten.get(gelesen["pdf_path"]), ordner_stand=ordner_stand,
                                    steckbriefe=steckbriefe):
                    anzahl += 1
        self._status("warten")
        return anzahl

    def _abbrechen(self):
        return self._stop.is_set() or self._pausen > 0 or not self.ist_aktiv()

    def _fremd_ueberwacht(self, master):
        """
        Überwacht ein KID im Dienstmodus auf einem anderen Rechner diesen Posteingang (Sammlung auf dem Netzlaufwerk,
        posteingang_sperre.py, Etappe 10 Schritt 4)? Dann pausiert die Hintergrund-Automatik hier - sonst arbeiteten
        zwei Rechner denselben Posteingang ab. Einmal ins Log, das Statusfenster sagt warum.
        """
        fremd = posteingang_sperre.fremd_aktiv(master)
        if fremd is None:
            if self._fremd_gemeldet:
                self._log("info", "Hintergrund-Automatik: Posteingang wieder frei, läuft weiter.")
                self._fremd_gemeldet = False
            return False
        wer = posteingang_sperre.beschreibung(fremd)
        if not self._fremd_gemeldet:
            self._log("warning", f"Hintergrund-Automatik: Posteingang wird von KID auf {wer} überwacht - pausiert hier.")
            self._fremd_gemeldet = True
        self._status("fremd", text=f"Diesen Posteingang überwacht KID auf {wer} - hier pausiert die "
                                   "Hintergrund-Automatik, bis dieser Dienst beendet ist.")
        return True

    def _lies_katalog(self, master):
        """
        Tag-Katalog der Runde direkt aus tags.json (tag_katalog, Etappe 10). Bis 17.11.2026 kam er über den
        Hauptthread aus dem Tag-Baum, mit höchstens HAUPTTHREAD_TIMEOUT Wartezeit: War das Hauptfenster beschäftigt,
        lief die Runde still mit leerem Katalog (Synonyme, Oberkategorien, bekannte Tags fehlten).
        Ohne Hauptfenster (Dienstmodus) gibt es den Baum gar nicht. Jede Änderung im Tag-Baum wird
        sofort gespeichert (tag_editor.save_tags), die Datei ist also aktuell. Nur wenn sie samt Sicherung
        unlesbar ist, fragt der Dienst wie früher den Baum.
        """
        knoten = tag_katalog.lade(app_paths.tags_path(master))
        if knoten is not None:
            self._katalog_gemeldet = False
            return tag_katalog.katalog_fuer_dienst(knoten)
        if not self._katalog_gemeldet:
            self._log("warning", "Vollautomatik: Tag-Katalog (tags.json) nicht lesbar - nehme den Tag-Baum.")
            self._katalog_gemeldet = True
        tm = getattr(self.app, "tag_manager", None)
        if tm is None:
            return {"known_tags": [], "kategorien": [], "tag_eltern": {}, "synonyme": {}}
        return {"known_tags": self._vom_hauptthread(tm.get_known_tags) or [],
                "kategorien": self._vom_hauptthread(tm.get_kategorien) or [],
                "tag_eltern": self._vom_hauptthread(tm.get_tag_eltern) or {},
                "synonyme": self._vom_hauptthread(tm.get_synonyme) or {}}

    def _lies_stapel(self, kandidaten, anfang, base_url, model, kontext):
        """Phase 1 eines Stapels: die Dokumente mit dem Lesemodell lesen. :return: [(nummer, gelesen), ...]"""
        stapel = []
        for nummer, pfad in enumerate(kandidaten[anfang:anfang + STAPEL_GROESSE], start=anfang + 1):
            if self._abbrechen():
                break
            if self._wird_gerade_bearbeitet(pfad):
                # Live-Fund 06.09.2026: Der Dienst verschob eine Posteingang-Datei, während
                # der Nutzer sie im Hauptfenster offen hatte und Titel/Tags tippte - das
                # debouncte Auto-Save schrieb dann ins Leere ("Failed to open stream").
                # Übersprungen wird NUR bei offener, ungespeicherter Eingabe zu genau
                # dieser Datei - bloßes Anzeigen zählt nicht (die Auto-Selektion beim
                # Ordnerwechsel würde sonst jede Verarbeitung dauerhaft blockieren).
                # Die 60-Sekunden-Fallback-Runde holt die Datei nach dem Speichern nach.
                if pfad not in self._angezeigt_gemeldet:
                    self._angezeigt_gemeldet.add(pfad)
                    self._log("info", f"Vollautomatik: {os.path.basename(pfad)} übersprungen - "
                                      "ungespeicherte Eingabe im Hauptfenster.")
                continue
            self._angezeigt_gemeldet.discard(pfad)
            name = os.path.basename(pfad)
            self._status("analyse", pfad=pfad, nummer=nummer, gesamt=len(kandidaten), schaetzung=self._analyse_dauer)
            start_zeit = time.monotonic()
            try:
                # Aktivitätsanzeige (thread-sicher, siehe aktivitaet.py): auch ohne offenes
                # Statusfenster sieht man in der Menüleiste, dass die Vollautomatik arbeitet
                with aktivitaet.phase(f"Vollautomatik liest {nummer} von {len(kandidaten)}: {aktivitaet.kurz(name)}…"):
                    gelesen = auto_pilot.lies_dokument(pfad, kontext["known_tags"], base_url, model,
                                                       kontext["kategorien"])
            except Exception as e:
                # Verbindungs-/Serverfehler: liegen lassen, später erneut (nicht in Dauerschleife)
                self._naechster_versuch[pfad] = time.monotonic() + WIEDERHOLUNG_NACH_FEHLER
                self._log("warning", f"Vollautomatik: Analyse fehlgeschlagen für {name}: {e}")
                self._status("fertig", pfad=pfad, text=f"Fehler bei {name} - nächster Versuch später.")
                continue
            # Countdown-Schätzung fürs Statusfenster mitziehen (gleitend, träge)
            self._analyse_dauer = round(0.6 * self._analyse_dauer + 0.4 * (time.monotonic() - start_zeit), 1)
            auto_pilot.merke_orte(self.orte, gelesen)
            stapel.append((nummer, gelesen))
        return stapel

    def _hole_zweitmeinungen(self, stapel, master, ordnerliste, base_url, kontext, gesamt=None):
        """
        Phase 2 eines Stapels: Zweitmeinungen des Entscheidungsmodells für alle Dokumente, die nach dem
        jetzigen Stand eine brauchen. :return: {pfad: rangliste oder Exception}. Braucht ein Dokument in
        Phase 3 doch eine (das Gedächtnis zählt inzwischen weiter), holt entscheide_gelesen sie einzeln.
        """
        nummern = {gelesen["pdf_path"]: nummer for nummer, gelesen in stapel}
        with aktivitaet.phase("Vollautomatik: Zweitmeinungen zur Ordnerwahl…") as phase:
            def vor_abruf(gelesen):
                self._status("zweitmeinung", pfad=gelesen["pdf_path"], nummer=nummern[gelesen["pdf_path"]],
                             gesamt=gesamt)
                phase.melde(f"Vollautomatik: Zweitmeinung zum Ordner für {aktivitaet.kurz(os.path.basename(gelesen['pdf_path']))}…")
            return auto_pilot.zweitmeinungen_fuer_stapel(
                [gelesen for _, gelesen in stapel], ordnerliste, base_url,
                self._entscheidungsmodell, abbrechen=self._abbrechen, vor_abruf=vor_abruf,
                **kontext)

    def _verarbeite(self, pfad, master, known_tags, ordnerliste, base_url, model, vocabulary, aliase, kategorien=None,
                    ignorierte=None, nummer=None, gesamt=None, tag_eltern=None, synonyme=None,
                    gedaechtnis=None, gelesen=None, rangliste=None, ordner_stand=None, steckbriefe=None):
        """
        Phase 3: ein gelesenes Dokument (lies_dokument) entscheiden und ablegen.
        :param rangliste: in Phase 2 geholte Zweitmeinung (oder Exception), None = bei Bedarf hier holen
        :param ordner_stand: Länge der Ordnerliste, als die Zweitmeinung geholt wurde
        :param steckbriefe: Ordner-Steckbriefe der Runde, lernen wie das Gedächtnis jede sichere Ablage sofort mit
        """
        name = os.path.basename(pfad)
        self._status("ablage", pfad=pfad, nummer=nummer, gesamt=gesamt)
        regeln = dict(vocabulary=vocabulary, aliase=aliase, known_tags=known_tags, kategorien=kategorien,
                      ignorierte_tags=ignorierte, tag_eltern=tag_eltern, synonyme=synonyme, gedaechtnis=gedaechtnis,
                      orte=self.orte)
        with aktivitaet.phase(f"Vollautomatik legt ab {nummer} von {gesamt}: {aktivitaet.kurz(name)}…"
                              if nummer else f"Vollautomatik legt ab: {aktivitaet.kurz(name)}…"):
            # Veraltete Zweitmeinung (neue Ordner seit Phase 2) holt entscheide_im_stapel neu
            entscheidung = auto_pilot.entscheide_im_stapel(
                gelesen, ordnerliste, base_url, entscheidungsmodell=self._entscheidungsmodell,
                rangliste=rangliste, ordner_stand=ordner_stand, steckbriefe=steckbriefe, **regeln)
        if entscheidung.get("zweitmeinung_fehler"):
            # Ohne Zweitmeinung entscheidet die Regel-Logik allein - wie vor dem 27.10.2026
            self._log("warning", f"Vollautomatik: Zweitmeinung zum Ordner fehlgeschlagen für {name}: "
                                 f"{entscheidung['zweitmeinung_fehler']}")
        # Keine Dubletten-Prüfung mehr (Peter 17.11.2026, Etappe 10: „keine Dubletten mehr nach unsicher. Wir haben
        # ja das Dublettentool dafür.“). Bis dahin ging ein Dokument, das im Zielordner schon ähnlich lag, nach
        # 0_Unsicher (Stufe B, KONZEPT_SENIORENMODUS) - mit KI-Zweitprüfung und einem Bild-Vergleich je Kandidat.
        # Doppelte findet jetzt das Werkzeug „Dubletten finden“; ein gleichnamiges Ziel überschreibt die Ablage nie
        # (_naechster_freier_pfad). Ablage-Vorschau und „Begleitet erfassen“ prüfen ebenfalls nicht mehr.

        # Zweite Prüfung NACH der (sekundenlangen) KI-Analyse: Hat der Nutzer inzwischen
        # angefangen, genau diese Datei zu bearbeiten, wird sie doch nicht angefasst.
        if self._wird_gerade_bearbeitet(pfad):
            self._log("info", f"Vollautomatik: {name} übersprungen - "
                              "ungespeicherte Eingabe im Hauptfenster.")
            self._status("fertig", pfad=pfad, text=f"{name} übersprungen (wird gerade bearbeitet).")
            return False

        self._status("einsortieren", pfad=pfad)
        ergebnis = auto_pilot.fuehre_entscheidung_aus(
            entscheidung, master, self.app.file_ops._verschiebe_ohne_duplikat, still=True,
            umbenennen=bool(self.app.config.get("auto_pilot_umbenennen", True)))
        if not ergebnis["erfolg"]:
            self._naechster_versuch[pfad] = time.monotonic() + WIEDERHOLUNG_NACH_FEHLER
            self._log("warning", f"Vollautomatik: Ablage fehlgeschlagen für {name}: {ergebnis['fehler']}")
            self._protokolliere(master, f"FEHLER    {name}  -  {ergebnis['fehler']}")
            self._status("fertig", pfad=pfad, text=f"Ablage fehlgeschlagen: {name}")
            return False

        self.verarbeitet += 1
        self.zaehle(entscheidung["sicher"])
        self._naechster_versuch.pop(pfad, None)
        ziel_rel = os.path.relpath(ergebnis["neuer_pfad"], master)
        grund = "" if entscheidung["sicher"] else "; ".join(entscheidung["probleme"])
        if entscheidung.get("tags_verworfen"):
            # Nur ins technische Protokoll - wer sich über ein fehlendes Tag wundert, findet hier den Grund
            self._log("info", f"Vollautomatik: Tags verworfen für {name}: "
                      + ", ".join(f"{t} ({g})" for t, g in entscheidung["tags_verworfen"]))
        if entscheidung["sicher"]:
            vermerk = ""
            if entscheidung.get("tag_ersetzungen"):
                vermerk += "  (Synonym: " + ", ".join(f"{a} -> {n}" for a, n in entscheidung["tag_ersetzungen"]) + ")"
            if entscheidung.get("ordner_gedaechtnis"):
                vermerk += f"  (Ordner aus dem Gedächtnis: {entscheidung['ordner_gedaechtnis']} Dokumente dieses Absenders)"
            if entscheidung.get("datum_stempel"):
                vermerk += f"  (Datum {entscheidung['datum']} statt Eingangsstempel {entscheidung['datum_stempel']})"
            if entscheidung.get("ordner_hinweis") == auto_pilot.STECKBRIEF_HINWEIS:
                vermerk += "  (Ordner aus dem Steckbrief)"     # nie die Nummern selbst - das Protokoll lesen Angehörige
            self._log("info", f"Vollautomatik: {pfad} -> {ergebnis['neuer_pfad']}{vermerk}")
            self._protokolliere(master, f"abgelegt  {name}  ->  {ziel_rel}{vermerk}")
            if gedaechtnis is not None and not entscheidung.get("ordner_sammel"):
                # Gilt ab dem nächsten Dokument dieser Runde - der Index kennt die Ablage erst später
                gedaechtnis.stimme(entscheidung["absender"], entscheidung["zielordner"])
            if steckbriefe is not None and not entscheidung.get("ordner_sammel"):
                steckbriefe.hinzu(entscheidung["zielordner"], (gelesen or {}).get("merkmale") or ())
            if entscheidung["ordner_neu"] and not entscheidung.get("ordner_sammel") and entscheidung["zielordner"] not in ordnerliste:
                # Varianten-Zusammenführung wie im Vorschau-Tool - NUR für tatsächlich angelegte Ordner.
                # Ein unsicher vorgeschlagener Ordner existiert nicht; in der Liste hielt ihn das nächste
                # Dokument für vorhanden (Nachtlauf 28.10.2026: 15x "Zielordner existiert nicht mehr").
                ordnerliste.append(entscheidung["zielordner"])
        else:
            self._log("info", f"Vollautomatik: {pfad} -> {ergebnis['neuer_pfad']} (unsicher: {grund})")
            self._protokolliere(master, f"unsicher  {name}  ->  {ziel_rel}  (Grund: {grund})")
        # Ziel und Grund getrennt ans Statusfenster: es zeigt sie dauerhaft an, bis das
        # nächste Dokument fertig ist (Nutzerwunsch 31.08.2026).
        self._status("fertig", pfad=pfad, ziel=ziel_rel, grund=grund,
                     text="Einsortiert." if entscheidung["sicher"] else "Einsortiert (unsicher).")
        self._auf_hauptthread(lambda: self.app.tool_manager.notify_file_moved(pfad, ergebnis["neuer_pfad"]))
        # Keine Katalog-Aufnahme mehr: Die Vollautomatik vergibt keine Tags (Etappe 6, FALLSTRICKE #120), Tags kommen nur
        # von Hand dazu - in der Ablage-Vorschau und in „Begleitet erfassen“ nimmt deren Fenster neue in den Katalog auf.
        return True

    # ------------------------------------------------------------------ Helfer
    def _wird_gerade_bearbeitet(self, pfad):
        """
        True, wenn diese Datei aktuell im Hauptfenster angezeigt wird UND dort eine
        ungespeicherte Eingabe offen ist (save_manager.hat_offene_aenderung: Dirty-Flag
        oder laufender Debounce-Timer) - dann lässt der Dienst die Finger davon, siehe
        Live-Fund 06.09.2026 in eine_runde. Bewusst NICHT schon bei bloßer Auswahl:
        Beim Öffnen des Posteingangs selektiert das Hauptfenster automatisch das erste
        Dokument, das würde die Verarbeitung sonst dauerhaft blockieren (Nutzerfund
        06.09.2026 direkt nach dem ersten Fix). Beide Werte gehören Tkinter, werden
        also über den Hauptthread gelesen.
        """
        def lies():
            sm = getattr(self.app, "save_manager", None)
            offen = bool(sm is not None and sm.hat_offene_aenderung())
            return (getattr(self.app, "current_preview_path", None), offen)

        angezeigt, offen = self._vom_hauptthread(lies) or (None, False)
        if not angezeigt or not offen:
            return False
        try:
            return os.path.normcase(os.path.abspath(angezeigt)) == os.path.normcase(os.path.abspath(pfad))
        except (OSError, ValueError, TypeError):
            return False

    def zaehle(self, sicher, heute=None):
        """Eine Ablage für den Tageszähler des Statusfensters; um Mitternacht beginnt er neu."""
        heute = heute or datetime.now().date()
        datum, abgelegt, unsicher = self._heute
        if datum != heute:
            abgelegt = unsicher = 0
        self._heute = (heute, abgelegt + (1 if sicher else 0), unsicher + (0 if sicher else 1))

    def zaehler_heute(self, heute=None):
        """(abgelegt, unsicher) seit Mitternacht bzw. seit Programmstart - ohne Inhalte, fürs Statusfenster."""
        datum, abgelegt, unsicher = self._heute
        return (abgelegt, unsicher) if datum == (heute or datetime.now().date()) else (0, 0)

    def _faellig(self, pfad):
        return self._naechster_versuch.get(pfad, 0.0) <= time.monotonic()

    @staticmethod
    def _ist_stabil(pfad):
        """Fertig geschrieben? Nicht leer, seit STABIL_MINDESTALTER unverändert und zum Schreiben öffenbar."""
        try:
            st = os.stat(pfad)
            if st.st_size == 0 or time.time() - st.st_mtime < STABIL_MINDESTALTER:
                return False
            with open(pfad, "rb+"):
                pass
            return True
        except OSError:
            return False

    def _status(self, ereignis, **daten):
        """Statusfenster füttern (Tkinter -> Hauptthread; ohne offenes Fenster passiert nichts)."""
        self._auf_hauptthread(lambda: vollautomatik_fenster.melde(self.app, ereignis, **daten))

    def _sync_fenster(self, beim_start=False):
        """Statusfenster öffnen/schließen, passend zur Einstellung (Fenster offen <=> Vollautomatik an)."""
        self._auf_hauptthread(lambda: vollautomatik_fenster.synchronisiere(self.app, beim_start))

    def _auf_hauptthread(self, fn):
        """Tkinter-berührende Aufrufe auf den Hauptthread verlegen (feuern und vergessen)."""
        try:
            self.app.root.after(0, fn)
        except Exception:
            pass

    def _vom_hauptthread(self, fn):
        """Wie _auf_hauptthread, wartet aber (begrenzt) auf das Ergebnis; None bei Timeout/Fehler."""
        ergebnis = {}
        fertig = threading.Event()

        def lauf():
            try:
                ergebnis["wert"] = fn()
            except Exception as e:
                ergebnis["fehler"] = e
            finally:
                fertig.set()

        try:
            self.app.root.after(0, lauf)
        except Exception:
            return None
        if not fertig.wait(HAUPTTHREAD_TIMEOUT):
            return None
        return ergebnis.get("wert")

    def _log(self, stufe, text):
        logger = getattr(self.app, "logger", None)
        if logger is not None:
            getattr(logger, stufe, logger.info)(text)

    def _protokolliere(self, master, zeile):
        """Eine Zeile ins Angehörigen-Protokoll (gemeinsamer Schreibweg in auto_pilot)."""
        auto_pilot.protokolliere(master, zeile, getattr(self.app, "logger", None))
