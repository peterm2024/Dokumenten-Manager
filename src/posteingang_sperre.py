"""
Sperre des Posteingangs über Rechnergrenzen (Etappe 10 Schritt 4, KONZEPT_DIENSTMODUS F6, Peter 17.11.2026: „eine
.lock-Datei oder so im Eingang, dass ein anderer User weiß, dass der Eingang überwacht wird“). Nur Standardbibliothek.

Liegt die Sammlung auf einem Netzlaufwerk, schützt `einzelstart` (Windows-Mutex, nur auf einem Rechner) nicht davor,
dass ein KID auf einem zweiten PC dieselbe Sammlung öffnet und seine Hintergrund-Automatik denselben Posteingang
abarbeitet. Deshalb zwei Dateien:

- **Hinweis im Posteingang** (`HINWEIS_NAME`, Text): für Menschen im Explorer - wer überwacht, seit wann. Wird nur
  beim Start geschrieben und beim Beenden gelöscht; der Ordner-Wächter sieht ihn also nicht jede Minute.
- **Lebenszeichen im Daten-Ordner** (`app_paths.posteingang_sperre_path`, JSON): Rechner, Prozess, Start und letztes
  Lebenszeichen; der Dienst erneuert es alle `LEBENSZEICHEN_S` Sekunden. Der Daten-Ordner wird nicht überwacht - im
  Posteingang würde jedes Erneuern bei einem KID auf einem anderen PC den Ordnerbaum neu aufbauen.

Ein Lebenszeichen gilt als verwaist, wenn es älter als `VERWAIST_NACH_S` ist (Absturz, Stromausfall) - dann darf ein
anderer übernehmen. Verglichen wird die Uhrzeit IM Lebenszeichen (Uhr des schreibenden PCs) mit der eigenen Uhr, nicht
die Änderungszeit der Datei (Uhr des Netzlaufwerks); die Spanne ist großzügig für leicht abweichende Uhren.
"""

import json
import os
import socket
from datetime import datetime

import app_paths
import sicher_speichern

LEBENSZEICHEN_S = 60
VERWAIST_NACH_S = 600
HINWEIS_NAME = "KID überwacht diesen Posteingang.txt"
_ZEITFORMAT = "%Y-%m-%d %H:%M:%S"


def ich():
    """Wer bin ich? (Rechnername, Prozess)."""
    return {"rechner": socket.gethostname(), "pid": os.getpid()}


def _gleich(a, b):
    return bool(a) and bool(b) and a.get("rechner") == b.get("rechner") and a.get("pid") == b.get("pid")


def lies(master):
    """Das Lebenszeichen im Daten-Ordner, sonst None (fehlt, gesperrt oder unlesbar)."""
    try:
        with open(app_paths.posteingang_sperre_path(master), encoding="utf-8") as f:
            daten = json.load(f)
        return daten if isinstance(daten, dict) else None
    except (OSError, ValueError):
        return None


def ist_frisch(sperre, jetzt=None):
    """Lebt der Halter noch? Ein Lebenszeichen „aus der Zukunft“ (Uhren weichen ab) zählt als frisch."""
    try:
        zuletzt = datetime.strptime(sperre["lebenszeichen"], _ZEITFORMAT)
    except (KeyError, TypeError, ValueError):
        return False
    return ((jetzt or datetime.now()) - zuletzt).total_seconds() < VERWAIST_NACH_S


def fremd_aktiv(master, jetzt=None, wer=None):
    """Überwacht gerade ein ANDERES KID diesen Posteingang? Dann dessen Lebenszeichen (Rechner, seit), sonst None."""
    sperre = lies(master)
    if sperre is None or not ist_frisch(sperre, jetzt) or _gleich(sperre, wer or ich()):
        return None
    return sperre


def belege(master, posteingang, jetzt=None, wer=None):
    """Lebenszeichen schreiben und den Hinweis in den Posteingang legen. Fehler beim Hinweis sind egal (Schreibschutz),
    ein Fehler beim Lebenszeichen geht an den Aufrufer."""
    wer = wer or ich()
    zeit = (jetzt or datetime.now()).strftime(_ZEITFORMAT)
    sicher_speichern.schreibe_json(app_paths.posteingang_sperre_path(master),
                                   dict(wer, seit=zeit, lebenszeichen=zeit), ensure_ascii=False, indent=2)
    if posteingang and os.path.isdir(posteingang):
        try:
            with open(os.path.join(posteingang, HINWEIS_NAME), "w", encoding="utf-8") as f:
                f.write(hinweis_text(wer["rechner"], zeit))
        except OSError:
            pass


def hinweis_text(rechner, seit):
    return (f"Diesen Posteingang überwacht KID (Hintergrund-Automatik) auf dem Rechner {rechner} seit {seit}.\n\n"
            "Neue PDFs, die hier hineinkommen, legt KID automatisch ab. Bitte auf einem anderen Rechner die "
            "Hintergrund-Automatik nicht zusätzlich einschalten - KID lässt sie dort ohnehin aus, solange diese "
            "Überwachung läuft.\n\nDiese Datei verschwindet, wenn der Dienst beendet wird. Bleibt sie nach einem Absturz "
            "liegen, ist das harmlos: Nach zehn Minuten ohne Lebenszeichen gilt die Überwachung als beendet.\n")


def erneuere(master, jetzt=None, wer=None):
    """Lebenszeichen auffrischen. False, wenn inzwischen ein anderes KID die Sperre hält (dann bleibt sie unberührt)."""
    wer = wer or ich()
    sperre = lies(master)
    if sperre is not None and not _gleich(sperre, wer) and ist_frisch(sperre, jetzt):
        return False
    seit = sperre.get("seit") if sperre is not None and _gleich(sperre, wer) else None
    zeit = (jetzt or datetime.now()).strftime(_ZEITFORMAT)
    sicher_speichern.schreibe_json(app_paths.posteingang_sperre_path(master),
                                   dict(wer, seit=seit or zeit, lebenszeichen=zeit), ensure_ascii=False, indent=2)
    return True


def gib_frei(master, posteingang, wer=None):
    """Beim Beenden: beide Dateien weg - aber nur, wenn die Sperre uns gehört."""
    if not _gleich(lies(master), wer or ich()):
        return
    for pfad in (app_paths.posteingang_sperre_path(master),
                 os.path.join(posteingang, HINWEIS_NAME) if posteingang else None):
        if pfad:
            try:
                os.remove(pfad)
            except OSError:
                pass


def beschreibung(sperre):
    """„Rechner PANEL-01 (seit 17.11.2026 08:00)“ für Meldungen."""
    seit = str(sperre.get("seit") or "")
    try:
        seit = datetime.strptime(seit, _ZEITFORMAT).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        pass
    return f"Rechner {sperre.get('rechner') or '?'}" + (f" (seit {seit})" if seit else "")
