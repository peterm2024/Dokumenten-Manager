"""
Sicher schreiben: Ein Abbruch darf nie eine halbe Datei am Platz des Originals hinterlassen (ARCHITEKTUR_REVIEW.md, R1, R2).

Alle Schreibwege für JSON-Dateien und das Ersetzen von PDFs laufen hierüber. Das Muster: Die neue Fassung geht in eine
Temp-Datei daneben, wird auf die Platte gezwungen und ersetzt das Ziel dann mit `os.replace` in einem Schritt.
`shutil.move` kann das nicht: Unter Windows scheitert dort das Umbenennen auf ein vorhandenes Ziel, und es kopiert
stattdessen über das Original (FALLSTRICKE #115). Hält ein anderes Programm das Ziel offen, gibt es einen Notweg: an Ort und
Stelle überschreiben, die Temp-Datei bleibt bis zum Schluss, bei einem Fehler kommt das Original zurück (FALLSTRICKE #118).

Unlesbares wird nie überschrieben: `lade_json` legt eine beschädigte Datei als `<Name>.kaputt` beiseite und meldet das über
`beiseite_gelegt`, das `gui` beim Start anzeigt. Nur Standardbibliothek, ohne tkinter.
"""
import json
import logging
import os
import shutil
import threading
import time

VERSUCHE = 3
WARTEZEIT_S = 0.3

_log = logging.getLogger("DocManager")
_sperre = threading.Lock()
beiseite_gelegt = []     # Pfade der .kaputt-Dateien, die noch niemand angezeigt hat


def ersetze_datei(temp, ziel, versuche=VERSUCHE, wartezeit=WARTEZEIT_S):
    """Temp-Datei ersetzt das Ziel in einem Schritt, das Ziel bleibt bei einem Fehler unberührt. Kurze Sperren durch Explorer-
    Vorschau, Virenscanner oder Indexdienst überbrückt die Wiederholung (FALLSTRICKE #27, #60). Hält ein Programm das Ziel
    offen und erlaubt nur das Löschen nicht, wird es nach den Versuchen an Ort und Stelle überschrieben (`_ueberschreibe`,
    FALLSTRICKE #118). Erlaubt es auch das Schreiben nicht, kommt der OSError beim Aufrufer an, das Ziel bleibt unberührt."""
    with open(temp, "rb+") as f:
        os.fsync(f.fileno())
    for versuch in range(1, versuche + 1):
        try:
            os.replace(temp, ziel)
            return
        except PermissionError as gesperrt:
            if versuch >= versuche:
                if not os.path.exists(ziel):
                    raise
                try:
                    _ueberschreibe(temp, ziel)
                except PermissionError:
                    raise gesperrt from None     # auch Schreiben verboten: die ursprüngliche Meldung (WinError 32) ist klarer
                return
            time.sleep(wartezeit)
        except OSError:
            if versuch >= versuche:
                raise
            time.sleep(wartezeit)


def _ueberschreibe(temp, ziel):
    """Notweg, wenn ein anderes Programm das Ziel offen hält (WinError 32): den Inhalt an Ort und Stelle ersetzen, so wie
    `shutil.move` es bis v0.9.25 immer tat. Das geschieht nicht in einem Schritt. Darum bleibt die Temp-Datei bis zum Schluss
    liegen, und scheitert das Schreiben, kommt das Original zurück (FALLSTRICKE #118)."""
    with open(temp, "rb") as f:
        neu = f.read()
    with open(ziel, "r+b") as z:      # scheitert sofort und ohne Schaden, wenn der Halter auch kein Schreiben erlaubt
        alt = z.read()
        try:
            z.seek(0)
            z.write(neu)
            z.truncate()
            z.flush()
            os.fsync(z.fileno())
        except Exception:
            z.seek(0)
            z.write(alt)
            z.truncate()
            z.flush()
            raise
    _entferne_leise(temp)
    _log.warning(f"{os.path.basename(ziel)} war von einem anderen Programm geöffnet und wurde an Ort und Stelle überschrieben")


def _entferne_leise(pfad):
    try:
        os.remove(pfad)
    except OSError:
        pass


def schreibe_json(pfad, daten, **dump_optionen):
    """Schreibt JSON atomar, legt den Ordner bei Bedarf an. Die Temp-Datei trägt Prozess und Thread im Namen, zwei Schreiber
    kommen sich also nicht in die Quere. Fehler gehen als Ausnahme an den Aufrufer, das Ziel bleibt dann unverändert."""
    ordner = os.path.dirname(pfad)
    if ordner:
        os.makedirs(ordner, exist_ok=True)
    temp = f"{pfad}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(daten, f, **dump_optionen)
        ersetze_datei(temp, pfad)
    except Exception:
        _entferne_leise(temp)
        raise


def sichere_kopie(pfad, ziel):
    """Kopie, die auch bei einem Abbruch entweder ganz oder gar nicht am Ziel liegt (für tags.json.bak)."""
    temp = f"{ziel}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        shutil.copy2(pfad, temp)
        ersetze_datei(temp, ziel)
    except Exception:
        _entferne_leise(temp)
        raise


def lege_beiseite(pfad):
    """Benennt eine unlesbare Datei in `<Name>.kaputt` um (`.kaputt2` usw., wenn es die schon gibt) und merkt sie für die
    Anzeige. Liefert den neuen Pfad, None wenn auch das nicht ging."""
    ziel = pfad + ".kaputt"
    nummer = 1
    while os.path.exists(ziel):
        nummer += 1
        ziel = f"{pfad}.kaputt{nummer}"
    try:
        os.replace(pfad, ziel)
    except OSError as e:
        _log.error(f"Beschädigte Datei konnte nicht beiseitegelegt werden: {pfad}: {e}")
        return None
    _log.warning(f"Beschädigte Datei beiseitegelegt: {ziel}")
    with _sperre:
        beiseite_gelegt.append(ziel)
    return ziel


def lade_json(pfad):
    """JSON lesen. Ist die Datei beschädigt, kommt sie aus dem Weg, bevor der ValueError beim Aufrufer ankommt: Was der danach
    speichert, überschreibt sie nicht. Fehlt die Datei oder ist sie gesperrt, kommt der OSError unverändert an."""
    try:
        with open(pfad, encoding="utf-8") as f:
            return json.load(f)
    except ValueError:
        lege_beiseite(pfad)
        raise


def nimm_beiseite_gelegte():
    """Die noch nicht angezeigten .kaputt-Dateien, danach ist die Liste leer."""
    with _sperre:
        namen = list(beiseite_gelegt)
        beiseite_gelegt.clear()
    return namen
