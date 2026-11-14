"""
Ignorierliste für KI-Tag-Vorschläge (Nutzerwunsch 30.08.2026, Tool "Tags ergänzen (KI)"):
Tags, die die KI immer wieder vorschlägt, die der Nutzer aber nie will (nichtssagende
Worte, falsch gelesene Namen), landen per Klick hier und werden danach ÜBERALL
herausgefiltert - im Ergänzen-Tool wie in der Vollautomatik (auto_pilot.tags_mit_empfaenger).
Gespeichert als tags_ignoriert.json im Daten-Ordner der Sammlung (wie aliase.json),
in Original-Schreibweise (von Hand pflegbar), verglichen wird kleingeschrieben.
"""


import app_paths
import sicher_speichern


def lade(master_folder):
    """Ignorierte Tags als Menge (kleingeschrieben); leer ohne Datei oder bei Fehlern."""
    try:
        daten = sicher_speichern.lade_json(app_paths.tags_ignoriert_path(master_folder))
    except (OSError, ValueError):
        return set()
    if not isinstance(daten, list):
        return set()
    return {str(t).strip().lower() for t in daten if str(t).strip()}


def lade_liste(master_folder):
    """Ignorierte Tags in Original-Schreibweise, alphabetisch - für die Bearbeiten-Oberfläche."""
    try:
        daten = sicher_speichern.lade_json(app_paths.tags_ignoriert_path(master_folder))
    except (OSError, ValueError):
        return []
    if not isinstance(daten, list):
        return []
    return sorted({str(t).strip() for t in daten if str(t).strip()}, key=str.lower)


def _speichere(master_folder, liste):
    pfad = app_paths.tags_ignoriert_path(master_folder)
    try:
        sicher_speichern.schreibe_json(pfad, sorted(liste, key=str.lower), ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def ergaenze(master_folder, tag):
    """Nimmt ein Tag dauerhaft in die Ignorierliste auf. :return: True, wenn es (jetzt) drinsteht"""
    tag = (tag or "").strip()
    if not tag:
        return False
    if tag.lower() in lade(master_folder):
        return True
    return _speichere(master_folder, lade_liste(master_folder) + [tag])


def entferne(master_folder, tag):
    """Nimmt ein Tag wieder von der Ignorierliste (Nutzerwunsch 03.09.2026: Liste bearbeitbar).
    :return: True, wenn es (jetzt) nicht mehr drinsteht"""
    tag = (tag or "").strip().lower()
    liste = lade_liste(master_folder)
    rest = [t for t in liste if t.lower() != tag]
    if rest == liste:
        return True
    return _speichere(master_folder, rest)
