"""
„Zuletzt benutzt“ je Sammlung (Peter 29.10.2026).

Vorher stand die Liste der zuletzt vergebenen Tags in der settings.json und galt damit für
JEDE Sammlung - eine frisch angelegte Sammlung zeigte die Tags der alten. Jetzt liegt sie wie
tags.json im Daten-Ordner der Sammlung (zuletzt_benutzt.json, eine geordnete Liste, neueste
zuerst) und wandert mit ihr mit.

Übergang: Gibt es die Datei noch nicht, aber in der settings.json die alte Liste
`recent_tags`, übernimmt die Sammlung, die gerade offen ist, diese Liste EINMAL; der Schlüssel
verschwindet danach aus der settings.json, damit die nächste neue Sammlung leer beginnt.
Ohne gültigen Hauptordner gibt es keine Liste (nichts wird gespeichert).
"""

import os

import app_paths
import sicher_speichern

ALT_SCHLUESSEL = "recent_tags"
MAX_EINTRAEGE = 10


def _master_gueltig(master_folder):
    return bool(master_folder) and os.path.isdir(master_folder)


def _bereinige(daten):
    """Nur Texte, ohne Doppelte, höchstens MAX_EINTRAEGE - Reihenfolge bleibt."""
    if not isinstance(daten, list):
        return []
    ergebnis = []
    for eintrag in daten:
        if isinstance(eintrag, str) and eintrag and eintrag not in ergebnis:
            ergebnis.append(eintrag)
    return ergebnis[:MAX_EINTRAEGE]


def speichere(master_folder, liste):
    """Schreibt die Liste in den Daten-Ordner; False ohne Hauptordner oder bei Schreibfehlern."""
    if not _master_gueltig(master_folder):
        return False
    pfad = app_paths.zuletzt_benutzt_path(master_folder)
    try:
        sicher_speichern.schreibe_json(pfad, _bereinige(liste), ensure_ascii=False, indent=2)
        return True
    except OSError:
        return False


def lade(master_folder, config=None):
    """
    Die Liste der Sammlung (neueste zuerst); leer ohne Hauptordner oder bei Fehlern.
    Mit `config` wird beim ersten Mal die alte Liste aus der settings.json übernommen.
    """
    if not _master_gueltig(master_folder):
        return []
    pfad = app_paths.zuletzt_benutzt_path(master_folder)
    if not os.path.exists(pfad):
        alt = _bereinige(config.data.get(ALT_SCHLUESSEL)) if config is not None else []
        if config is not None and ALT_SCHLUESSEL in config.data:
            if speichere(master_folder, alt):
                config.data.pop(ALT_SCHLUESSEL, None)
                config.save()
        return alt
    try:
        return _bereinige(sicher_speichern.lade_json(pfad))
    except (OSError, ValueError):
        return []


def vorne_einreihen(liste, tags):
    """Neue Liste mit `tags` vorne (in ihrer Reihenfolge), ohne Doppelte, gekürzt. Rein."""
    ergebnis = [t for t in liste if t not in tags]
    return _bereinige(list(tags) + ergebnis)
