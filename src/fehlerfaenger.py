"""
Zentraler Fehlerfänger (Beta-Vorbereitung 13.09.2026).

Die Release-EXE läuft ohne Konsole. Eine Ausnahme in einem Tk-Callback (Knopf, Timer,
Ereignis) landete bisher nur auf stderr - also im Nichts: der Nutzer sah „es passiert
nichts“, im Protokoll stand nichts, und für eine Rückmeldung fehlte jede Spur. Dasselbe
galt für Hintergrund-Threads (Vollautomatik, Index, KI-Aufrufe).

Der Fehlerfänger hängt sich an die drei Stellen, an denen unbehandelte Ausnahmen
auflaufen (Tk-Callbacks über `report_callback_exception`, Hauptprogramm über
`sys.excepthook`, Threads über `threading.excepthook`), schreibt den vollständigen
Traceback ins Protokoll und zeigt EINEN kurzen Dialog mit der Möglichkeit, das Protokoll
zu öffnen. Damit ein Dauerfehler (z.B. in einem Timer) den Nutzer nicht mit Dialogen
zuschüttet, kommt dieselbe Meldung höchstens alle SPERRE_SEKUNDEN erneut. Der Dialog
läuft immer im Tk-Hauptthread (aus Threads per `root.after`).

Startfehler (Absturz schon beim Aufbau des Hauptfensters) haben noch keinen Logger:
`startfehler_sichern` schreibt den Traceback neben die EXE, `main.py` zeigt den Pfad an.
"""

import atexit
import datetime
import faulthandler
import os
import sys
import threading
import time
import traceback
from tkinter import messagebox

SPERRE_SEKUNDEN = 30
STARTFEHLER_DATEI = "startfehler.txt"
ABSTURZ_DATEI = "absturz.txt"

vorheriger_absturz = ""     # Text eines Absturzes beim letzten Lauf, gui schreibt ihn ins Protokoll


def kurztext(typ, wert):
    """'ValueError: ungültig' - Typname plus Meldung, ohne Traceback."""
    name = getattr(typ, "__name__", str(typ))
    meldung = str(wert).strip() if wert is not None else ""
    return f"{name}: {meldung}" if meldung else name


class Fehlerfaenger:
    def __init__(self, root, logger, log_oeffnen=None, dialog=None):
        """
        root: Tk-Hauptfenster; logger: AppLogger (braucht .error); log_oeffnen: Callable, das
        die Protokolldatei öffnet (Datei → Protokoll-Datei (Log) öffnen); dialog: Ersatz für den
        Standard-Dialog (Tests) - bekommt (kurztext, quelle).
        """
        self.root = root
        self.logger = logger
        self.log_oeffnen = log_oeffnen
        self._dialog = dialog or self._standard_dialog
        self._zuletzt = {}
        self.anzahl = 0
        self._vorherige = None

    def installieren(self):
        """Hängt sich an Tk, sys und threading. Rückgängig mit deinstallieren()."""
        self._vorherige = (sys.excepthook, threading.excepthook)
        self.root.report_callback_exception = self.tk_fehler
        sys.excepthook = self.sys_fehler
        threading.excepthook = self.thread_fehler
        return self

    def deinstallieren(self):
        if self._vorherige:
            sys.excepthook, threading.excepthook = self._vorherige
            self._vorherige = None

    # ------------------------------------------------------------ Einstiege
    def tk_fehler(self, typ, wert, tb):
        self.melde(typ, wert, tb, "Bedienung/Oberfläche")

    def sys_fehler(self, typ, wert, tb):
        if issubclass(typ, KeyboardInterrupt):
            sys.__excepthook__(typ, wert, tb)
            return
        self.melde(typ, wert, tb, "Hauptprogramm")

    def thread_fehler(self, args):
        if args.exc_type is SystemExit:
            return
        name = getattr(args.thread, "name", "?") if args.thread else "?"
        self.melde(args.exc_type, args.exc_value, args.exc_traceback, f"Hintergrund ({name})")

    # ------------------------------------------------------------ Kern
    def melde(self, typ, wert, tb, quelle):
        """Protokolliert immer; Dialog nur, wenn dieselbe Meldung nicht gerade erst gezeigt wurde. Liefert True, wenn ein Dialog ausgelöst wurde."""
        self.anzahl += 1
        kurz = kurztext(typ, wert)
        text = "".join(traceback.format_exception(typ, wert, tb))
        try:
            self.logger.error(f"Unbehandelter Fehler ({quelle}): {kurz}\n{text.rstrip()}")
        except Exception:
            pass
        jetzt = time.monotonic()
        if jetzt - self._zuletzt.get(kurz, -1e9) < SPERRE_SEKUNDEN:
            return False
        self._zuletzt[kurz] = jetzt
        if threading.current_thread() is threading.main_thread():
            self._dialog(kurz, quelle)
        else:
            try:
                self.root.after(0, lambda: self._dialog(kurz, quelle))
            except Exception:
                pass
        return True

    def _standard_dialog(self, kurz, quelle):
        text = ("Im Programm ist ein interner Fehler aufgetreten:\n\n"
                f"{kurz}\n\n"
                "Das Programm läuft weiter. Die Einzelheiten stehen im Protokoll "
                "(Datei → Protokoll-Datei (Log) öffnen) - bitte bei einer Rückmeldung mitschicken.\n\n"
                "Protokoll jetzt öffnen?")
        try:
            if messagebox.askyesno("Interner Fehler", text, icon="error", parent=self.root) and self.log_oeffnen:
                self.log_oeffnen()
        except Exception:
            pass


def startfehler_sichern(traceback_text, verzeichnis):
    """Schreibt einen Startfehler (noch kein Logger) als Textdatei ins Verzeichnis; liefert den Pfad oder None."""
    try:
        pfad = os.path.join(verzeichnis, STARTFEHLER_DATEI)
        with open(pfad, "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n{traceback_text}\n")
        return pfad
    except Exception:
        return None


def letzter_absturz(verzeichnis):
    """Text eines nativen Absturzes beim letzten Lauf, sonst "". Jeder Absturz wird nur einmal geliefert."""
    pfad = os.path.join(verzeichnis, ABSTURZ_DATEI)
    try:
        with open(pfad, encoding="utf-8", errors="replace") as f:
            text = f.read()
        os.remove(pfad)
        return text
    except OSError:
        return ""


def absturz_protokoll_starten(verzeichnis):
    """
    Stürzt der native Code ab (MuPDF, libpff), hilft kein except: Der Prozess ist einfach weg. faulthandler schreibt dann noch
    die Python-Stapel aller Threads in `absturz.txt` neben die EXE, der nächste Start übernimmt sie ins Protokoll. Die Datei
    existiert nur während des Laufs und verschwindet beim normalen Ende wieder. Schlägt das fehl, läuft KID ohne diesen Schutz.
    """
    global vorheriger_absturz
    vorheriger_absturz = letzter_absturz(verzeichnis)
    pfad = os.path.join(verzeichnis, ABSTURZ_DATEI)
    try:
        datei = open(pfad, "w", encoding="utf-8")
        faulthandler.enable(file=datei, all_threads=True)
    except (OSError, ValueError):
        return

    def beenden():
        faulthandler.disable()
        datei.close()
        try:
            if os.path.getsize(pfad) == 0:
                os.remove(pfad)
        except OSError:
            pass

    atexit.register(beenden)


def ausgabe_absichern(stroeme=None):
    """
    Konsolen-Ausgabe so einstellen, dass nicht darstellbare Zeichen ersetzt statt mit
    UnicodeEncodeError abgewiesen werden. Anlass (25.10.2026): Ist die Ausgabe in eine Datei
    umgeleitet (Fernsteuerung, Protokoll-Umleitung), gilt der Windows-Zeichensatz cp1252 - die
    Debug-Zeile „Speichere Metadaten für 20190101_□vmc.pdf“ warf dann einen Fehler, und das
    Speichern solcher Dateien schlug fehl (FALLSTRICKE #78). In der EXE gibt es keine Konsole
    (sys.stdout ist None) - dort ändert sich nichts.
    """
    for strom in (stroeme if stroeme is not None else (sys.stdout, sys.stderr)):
        try:
            if strom is not None and hasattr(strom, "reconfigure"):
                strom.reconfigure(errors="backslashreplace")
        except Exception:
            pass
