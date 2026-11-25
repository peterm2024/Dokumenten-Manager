"""
Eine geprüfte Ablage-Entscheidung ausführen (aus auto_pilot ausgelagert, Etappe 14, 23.11.2026): Metadaten schreiben,
umbenennen, verschieben, ins Angehörigen-Protokoll eintragen. Was entschieden wird, steht in auto_pilot. Aufrufer dürfen
weiter `auto_pilot.<name>` schreiben (Weiterleitung).
"""

import os
from datetime import datetime

import app_paths
import scan_date
from ordner_finden import UNSICHER_ORDNER
from pdf_handler import PDFHandler


def _gleicher_pfad(a, b):
    """Zeigen beide Pfade auf dieselbe Datei? (Groß-/Kleinschreibung und Schrägstrich-Mix egal, FALLSTRICKE #52)"""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _naechster_freier_pfad(pfad):
    """Hängt bei Namenskonflikten '_1', '_2', ... an (gleiches Muster wie restore_file in file_operations.py)."""
    if not os.path.exists(pfad):
        return pfad
    ordner = os.path.dirname(pfad)
    name, ext = os.path.splitext(os.path.basename(pfad))
    counter = 1
    kandidat = pfad
    while os.path.exists(kandidat):
        kandidat = os.path.join(ordner, f"{name}_{counter}{ext}")
        counter += 1
    return kandidat


def protokolliere(master_folder, zeile, logger=None):
    """
    Eine Zeile ins Angehörigen-Protokoll 'Vollautomatik-Protokoll.txt' im Daten-Ordner
    (eine Aktion pro Zeile, ohne Technik-Kauderwelsch). Gemeinsamer Schreibweg für die
    Watchdog-Vollautomatik UND das Einsortieren aus der Ablage-Vorschau - beim
    Kaltstart-Test 03.09.2026 lagen 71 Unsicher-Dokumente ohne festgehaltenen Grund da,
    weil nur der Watchdog protokollierte und das Vorschau-Fenster längst zu war.
    Ein Fehler hier darf die Ablage nie stoppen.
    """
    try:
        pfad = app_paths.protokoll_path(master_folder)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M}  {zeile}\n")
    except OSError as e:
        if logger is not None:
            logger.warning(f"Vollautomatik: Protokoll nicht schreibbar: {e}")


def protokolliere_ergebnis(entscheidung, ergebnis, master_folder, logger=None):
    """
    Standard-Protokollzeile zu einer ausgeführten Entscheidung (fuehre_entscheidung_aus):
    'abgelegt <name> -> <ziel>', 'unsicher ... (Grund: ...)' oder 'FEHLER ...' -
    dieselben Formate, die auto_pilot_service seit Schritt 4 schreibt.
    """
    name = os.path.basename(entscheidung["pdf_path"])
    if not ergebnis["erfolg"]:
        protokolliere(master_folder, f"FEHLER    {name}  -  {ergebnis['fehler']}", logger)
        return
    ziel_rel = os.path.relpath(ergebnis["neuer_pfad"], master_folder)
    if entscheidung["sicher"]:
        zusatz = ""
        if entscheidung.get("manuell_freigegeben") and entscheidung["probleme"]:
            # Die Freigabe war eine bewusste Nutzer-Entscheidung - das Angehörigen-
            # Protokoll soll zeigen, worüber dabei hinweggegangen wurde.
            zusatz = f"  (manuell freigegeben trotz: {'; '.join(entscheidung['probleme'])})"
        protokolliere(master_folder, f"abgelegt  {name}  ->  {ziel_rel}{zusatz}", logger)
    else:
        grund = "; ".join(entscheidung["probleme"])
        protokolliere(master_folder, f"unsicher  {name}  ->  {ziel_rel}  (Grund: {grund})", logger)


def fuehre_entscheidung_aus(entscheidung, master_folder, verschieben, still=False, umbenennen=True):
    """
    Setzt eine geprüfte Ablage-Entscheidung (baue_entscheidung) tatsächlich um -
    Schritt 2 des Seniorenmodus (KONZEPT_SENIORENMODUS.md).

    sicher:   Titel/Tags/Datum in die PDF-Metadaten schreiben, nach
              'JJJJMMTT_Titel.pdf' umbenennen, in den Zielordner verschieben
              (wird bei Bedarf neu angelegt).
    unsicher: KI-Titel und Grund schreiben (Peter 04.11.2026), Tags/Datum UNVERÄNDERT, kein Umbenennen, nach '0_Unsicher'
              verschieben - nur der Grund kommt als KID_GRUND ins PDF (Status-Zeile der
              Eigenschaften, Peter 28.10.2026); scheitert das Schreiben, wird trotzdem verschoben.

    Umbenennen (Nutzerfund 11.09.2026: ein falscher KI-Titel machte aus "Grundriss
    Hobbyraum" einen "Mietvertrag ..."): mit ``umbenennen=False`` (Einstellung
    auto_pilot_umbenennen) behält die Datei ihren Namen, Metadaten und Zielordner kommen
    trotzdem. Beim Umbenennen wird der bisherige Name als KID_Originalname in die
    PDF-Metadaten eingebrannt (nur beim ersten Mal, siehe pdf_handler._merge_kid_metadata),
    damit der allererste Name nie verloren geht.

    Randfall (05./06.09.2026): Zwischen Analyse und Ausführung kann Zeit vergehen
    (die Ablage-Vorschau steht offen, der Nutzer benennt derweil einen Ordner um).
    Ein bei der Analyse GEFUNDENER Zielordner (ordner_neu=False) muss deshalb hier
    noch existieren - sonst würde makedirs den alten Namen still wieder anlegen.
    In dem Fall wird die Entscheidung direkt im übergebenen Dict auf 'unsicher'
    zurückgestuft (Grundregel: bei Zweifel nie automatisch ablegen), damit auch
    Protokoll und Aufrufer-Anzeige den echten Ausgang zeigen. Bewusst neue Ordner
    (ordner_neu=True) werden weiterhin angelegt.

    Das eigentliche Verschieben übernimmt der übergebene 'verschieben(quelle, ziel)'-
    Callable (in der Praxis file_operations._verschiebe_ohne_duplikat) statt einer
    eigenen Kopie der Windows-Lock-Robustheit (Wiederholungsversuche, Duplikat-
    Aufräumen, siehe FALLSTRICKE #27) - dieses Modul bleibt damit unabhängig von
    Tkinter/der App und ohne echte Dateizugriffe testbar.

    :param still: True = keine Messagebox aus dem Metadaten-Schreiben (Hintergrund-Thread,
                  siehe auto_pilot_service.py); Fehler kommen dann nur als Rückgabewert.
    :return: Dict mit erfolg (bool), neuer_pfad (str oder None), fehler (str oder None).
    """
    pdf_path = entscheidung["pdf_path"]
    erfasst = scan_date.to_storage(datetime.now())   # einmal gesetzt, nie überschrieben (pdf_handler)
    if (entscheidung["sicher"] and not entscheidung.get("ordner_neu")
            and not os.path.isdir(os.path.join(master_folder, entscheidung["zielordner"]))):
        entscheidung["sicher"] = False
        entscheidung["probleme"] = list(entscheidung.get("probleme") or []) + [
            f"Zielordner '{entscheidung['zielordner']}' existiert nicht mehr "
            "(seit der Analyse umbenannt oder gelöscht?)"]
    try:
        if entscheidung["sicher"]:
            zielordner_abs = os.path.join(master_folder, entscheidung["zielordner"])
            os.makedirs(zielordner_abs, exist_ok=True)
            alter_name = os.path.basename(pdf_path)
            neuer_name = entscheidung["neuer_dateiname"] if umbenennen else alter_name
            ziel = os.path.join(zielordner_abs, neuer_name)
            metadaten = {
                "title": entscheidung["titel"],
                "KID_DokumentenDatum": entscheidung["datum"],
                # Stimme fürs Ablage-Gedächtnis: der Absender reist im PDF mit, ein späteres
                # Verschieben von Hand korrigiert sie also von selbst (ablage_gedaechtnis.py)
                "KID_Absender": entscheidung.get("absender") or "",
                "KID_Grund": "",   # ein früherer Unsicher-Grund gilt nicht mehr
                "KID_Erfasst": erfasst,
            }
            if neuer_name != alter_name:
                metadaten["KID_Originalname"] = alter_name
            if entscheidung.get("tags"):
                # Nur, was ein Mensch eingetragen hat (Ablage-Vorschau); ohne Eintrag bleiben vorhandene Tags im PDF stehen
                metadaten["keywords"] = ", ".join(entscheidung["tags"])
            if not PDFHandler.write_custom_metadata(pdf_path, metadaten, still=still):
                return {"erfolg": False, "neuer_pfad": None, "fehler": "Metadaten konnten nicht geschrieben werden."}
        else:
            unsicher_ordner = os.path.join(master_folder, UNSICHER_ORDNER)
            os.makedirs(unsicher_ordner, exist_ok=True)
            grund = "; ".join(entscheidung.get("probleme") or []) or "unsicher"
            felder = {"KID_Grund": grund, "KID_Erfasst": erfasst}
            # Peter 04.11.2026 (T20.3): auch in 0_Unsicher soll man sehen, worum es geht - NUR der Titel;
            # Tags, Datum und Dateiname warten auf die Prüfung
            if (entscheidung.get("titel") or "").strip():
                felder["title"] = entscheidung["titel"]
            PDFHandler.write_custom_metadata(pdf_path, felder, still=True)
            ziel = os.path.join(unsicher_ordner, os.path.basename(pdf_path))

        # Liegt die Datei bereits korrekt benannt am Ziel (Ablage-Vorschau über den
        # Unsicher-Ordner oder über schon abgelegten Bestand), gibt es nichts zu
        # verschieben. Ohne diese Prüfung sähe _naechster_freier_pfad die Datei SELBST
        # als Namenskonflikt und benennt sie an ihrem eigenen Namen vorbei um -
        # Nutzerfund 06.09.2026: bei jedem Durchlauf wuchs ein '_1' an ('X_1_1.pdf').
        if _gleicher_pfad(pdf_path, ziel):
            return {"erfolg": True, "neuer_pfad": pdf_path, "fehler": None}
        ziel = _naechster_freier_pfad(ziel)
        verschieben(pdf_path, ziel)
        return {"erfolg": True, "neuer_pfad": ziel, "fehler": None}
    except Exception as e:
        return {"erfolg": False, "neuer_pfad": None, "fehler": str(e)}
