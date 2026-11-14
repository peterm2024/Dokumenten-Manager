"""
Gedächtnis des Papierkorbs: aus welchem Ordner kam eine gelöschte Datei? (Peter 25.10.2026)

Vorher legte „Wiederherstellen“ jede Datei in den Hauptordner - man musste sie danach von Hand
in ihren alten Ordner zurückziehen. Jetzt merkt sich das Löschen den Herkunftsordner, und das
Wiederherstellen legt die Datei dorthin zurück; gibt es den Ordner nicht mehr (oder ist nichts
gemerkt, z.B. bei Dateien von vor dieser Änderung), landet sie wie bisher im Hauptordner.

Ablage: papierkorb_herkunft.json im Daten-Ordner der Sammlung (wie aliase.json), Schlüssel =
Dateiname im Papierkorb, Wert = Ordner relativ zum Hauptordner ("" = Hauptordner selbst). Bekam die
Datei im Papierkorb einen anderen Namen, weil der schon belegt war, steht der alte unter „name:<Dateiname
im Papierkorb>“; ein Dateiname kann unter Windows keinen Doppelpunkt enthalten. Die PDF-Dateien selbst
bleiben unverändert.
"""

import os

import app_paths
import sicher_speichern

_NAME = "name:"


def lade(master_folder):
    """{Dateiname im Papierkorb: Herkunftsordner relativ zum Hauptordner}; leer ohne Datei oder bei Fehlern."""
    try:
        daten = sicher_speichern.lade_json(app_paths.papierkorb_herkunft_path(master_folder))
    except (OSError, ValueError):
        return {}
    if not isinstance(daten, dict):
        return {}
    return {k: v for k, v in daten.items() if isinstance(k, str) and isinstance(v, str)}


def _speichere(master_folder, eintraege):
    pfad = app_paths.papierkorb_herkunft_path(master_folder)
    try:
        sicher_speichern.schreibe_json(pfad, dict(sorted(eintraege.items())), ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def merke(master_folder, papierkorb_pfad, herkunft_pfad):
    """Beim Löschen: Datei liegt jetzt unter papierkorb_pfad, kam aus dem Ordner von herkunft_pfad."""
    eintraege = lade(master_folder)
    rel = os.path.relpath(os.path.dirname(os.path.abspath(herkunft_pfad)), os.path.abspath(master_folder))
    name = os.path.basename(papierkorb_pfad)
    eintraege[name] = "" if rel == "." else rel
    if name != os.path.basename(herkunft_pfad):
        eintraege[_NAME + name] = os.path.basename(herkunft_pfad)
    return _speichere(master_folder, eintraege)


def vergiss(master_folder, papierkorb_pfad):
    """Eintrag entfernen (nach Wiederherstellen oder endgültigem Löschen)."""
    eintraege = lade(master_folder)
    name = os.path.basename(papierkorb_pfad)
    weg = [eintraege.pop(k, None) for k in (name, _NAME + name)]
    if any(w is not None for w in weg):
        _speichere(master_folder, eintraege)


def urspruenglicher_name(master_folder, papierkorb_pfad):
    """Wie hieß die Datei vor dem Löschen? „x (2).pdf“ heißt sie nur im Papierkorb, weil „x.pdf“ dort schon lag."""
    name = os.path.basename(papierkorb_pfad)
    return os.path.basename(lade(master_folder).get(_NAME + name, name)) or name


def zielordner(master_folder, papierkorb_pfad):
    """
    Wohin soll die Datei beim Wiederherstellen? Der gemerkte Herkunftsordner, wenn es ihn noch
    gibt und er innerhalb der Sammlung liegt - sonst der Hauptordner.
    """
    rel = lade(master_folder).get(os.path.basename(papierkorb_pfad))
    if rel:
        basis = os.path.abspath(master_folder)
        ziel = os.path.abspath(os.path.join(basis, rel))
        if os.path.isdir(ziel) and os.path.commonpath([basis, ziel]) == basis \
                and not app_paths.is_trash_path(ziel, master_folder):
            return ziel
    return master_folder
