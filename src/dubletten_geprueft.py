"""
Gedächtnis des Dubletten-Finders (Nutzerwunsch 12.09.2026: „Können wir uns das irgendwie
merken, wenn ich die Dubletten überprüft habe und auf behalten gesetzt habe? Sonst müsste
ich die immer wieder neu überprüfen.").

Eine Gruppe, die der Nutzer geprüft und als „keine Dublette" bestätigt hat, taucht beim
nächsten Lauf nicht mehr auf. Gemerkt werden PAARE von Dokument-IDs (`KID_ID`, eindeutig
und beim ersten Merken ins PDF eingebrannt - `PDFHandler.ensure_kid_id`; übersteht damit
Umbenennen, Verschieben und Metadaten-Änderungen, anders als der Datei-Hash). Kommt ein
neues Dokument zur Gruppe hinzu, ist mindestens ein Paar ungeprüft und die Gruppe
erscheint wieder - mit allen Mitgliedern, damit man den Neuling einordnen kann.

Ablage: dubletten_geprueft.json im Daten-Ordner der Sammlung (wie aliase.json):
    {"paare": [["3f2a…", "9c1b…"], …]}
"""
from itertools import combinations

import app_paths
import sicher_speichern


def lade(master_folder):
    """Geprüfte Paare als Menge von frozenset({id_a, id_b}); leer ohne Datei oder bei Fehlern."""
    try:
        daten = sicher_speichern.lade_json(app_paths.dubletten_geprueft_path(master_folder))
    except (OSError, ValueError):
        return set()
    paare = set()
    for paar in (daten.get("paare") if isinstance(daten, dict) else []) or []:
        if isinstance(paar, (list, tuple)) and len(paar) == 2 and all(isinstance(p, str) and p.strip() for p in paar):
            if paar[0] != paar[1]:
                paare.add(frozenset(p.strip() for p in paar))
    return paare


def speichere(master_folder, paare):
    """Schreibt die Paare sortiert (von Hand lesbar). :return: True bei Erfolg"""
    pfad = app_paths.dubletten_geprueft_path(master_folder)
    liste = sorted(sorted(paar) for paar in paare)
    try:
        sicher_speichern.schreibe_json(pfad, {"paare": liste}, ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def paare_aus(ids):
    """Alle Paare einer Gruppe von IDs (leere IDs werden ignoriert)."""
    saubere = sorted({(i or "").strip() for i in ids if (i or "").strip()})
    return {frozenset(p) for p in combinations(saubere, 2)}


def ist_geprueft(paare, ids):
    """True, wenn die Gruppe mindestens zwei IDs hat und JEDES Paar darin gemerkt ist."""
    noetig = paare_aus(ids)
    return bool(noetig) and noetig <= paare


def merke(master_folder, ids):
    """Merkt alle Paare der Gruppe als geprüft. :return: True bei Erfolg"""
    neue = paare_aus(ids)
    if not neue:
        return False
    return speichere(master_folder, lade(master_folder) | neue)


def vergiss(master_folder, ids):
    """Hebt die Prüfung für alle Paare der Gruppe auf. :return: True bei Erfolg"""
    weg = paare_aus(ids)
    return speichere(master_folder, lade(master_folder) - weg)


def trenne_gruppen(gruppen, paare, id_von):
    """
    Teilt die gefundenen Gruppen [(infos, grund, sicher)] in (offene, geprüfte).
    `id_von(info)` liefert die KID_ID eines Dokuments ("" ohne ID - dann nie geprüft).
    """
    offene, geprueft = [], []
    for gruppe in gruppen:
        ids = [id_von(info) for info in gruppe[0]]
        if all(ids) and ist_geprueft(paare, ids):
            geprueft.append(gruppe)
        else:
            offene.append(gruppe)
    return offene, geprueft
