"""
Absender-Aliase der Vollautomatik (KONZEPT_SENIORENMODUS.md, Entscheidung 30.08.2026).

Das deterministische Ordner-Matching (auto_pilot.finde_passenden_ordner) vergleicht
Namensbestandteile - es kann prinzipiell nicht wissen, dass die "Bayerische
Landesbrandversicherung" eine Marke der "Versicherungskasse Musterland" ist und in
deren Ordner gehört. Solches Weltwissen trägt der Nutzer hier einmalig nach: ein
Klick auf den Zielordner in der Ablage-Vorschau legt einen Alias

    Absender (wie von der KI erkannt)  ->  Zielordner (relativer Pfad in der Sammlung)

in der Datei aliase.json im Daten-Ordner der Sammlung an. Der Alias hat Vorrang
vor dem Namens-Matching und gilt ab sofort für alle Dokumente dieses Absenders -
auch für die restlichen Zeilen des laufenden Stapels.

Kein Dateisystem-Link, keine Dublette: der Ordner bleibt der EINE physische Ort,
der Alias ist nur ein Wegweiser der Automatik.

Objekt-Aliase (11.09.2026, Eigenbelege ohne Absender): Notizen, Zählerstände, Mieter-
listen, Verbrauchsaufstellungen haben keinen Briefkopf - im Praxislauf blieben 33 von
84 unsicheren Dokumenten allein deshalb liegen. Was sie haben, ist ein Objekt
("Weidenstr. 8", "Zum Alten Fass 1 Musterheim"). Ein Klick auf den Zielordner mit
"alle Dokumente zu diesem Objekt" legt in derselben Datei einen Eintrag mit dem
Schlüssel "Objekt: <Objekt>" an; er gilt NUR für absenderlose Dokumente (ein Brief der
Stadtwerke über dasselbe Haus geht weiter zu den Stadtwerken) und wird von
finde_alias (Absender-Suche) bewusst übersprungen. Gelernt und verglichen wird auf
HAUS-Ebene (objekt_kern: "Weidenstr. 8 Whg 4" -> "Weidenstr. 8"), exakt statt als
Teilstring - "Weidenstr. 8" darf "Weidenstr. 80" nicht treffen. Ein von Hand
eingetragener Schlüssel MIT Wohnung ("Objekt: Weidenstr. 8 Whg 4") gewinnt für genau
diese Wohnung vor dem Haus-Eintrag.
"""

import os
import re

import app_paths
import sicher_speichern

# Kürzere Alias-Schlüssel werden nur bei exakter Übereinstimmung gewertet, nie als
# Teilstring (gleiche Überlegung wie auto_pilot.MIN_ORDNER_MATCH_LAENGE).
MIN_TEILSTRING_LAENGE = 4

_MEHRFACH_LEERZEICHEN = re.compile(r"\s+")

# Schlüssel-Präfix der Objekt-Aliase in aliase.json (lesbar, von Hand pflegbar)
OBJEKT_PRAEFIX = "Objekt: "

# Wohnungs-Zusatz am Ende einer Objekt-Bezeichnung ("Whg 4", "Whg Nr. 2", "Wohnung 3",
# "WE 12", "Top 5") - Schreibweisen wie in auto_pilot._objekt_normalform
_WOHNUNGS_ZUSATZ = re.compile(r"[\s,]+(?:whg|wgh|wohnung|we|top|app\.?|apartment)\.?\s*(?:nr\.?\s*)?[\w/-]+\s*$",
                              re.IGNORECASE)


def objekt_kern(objekt):
    """Objekt ohne Wohnungs-Zusatz: "Weidenstr. 8 Whg 4" -> "Weidenstr. 8"; ohne Zusatz unverändert."""
    text = (objekt or "").strip()
    kern = _WOHNUNGS_ZUSATZ.sub("", text).strip()
    return kern or text


def _normalisiere(text):
    """Vergleichsform: Kleinschreibung, Leerraum zusammengezogen, Ränder gestutzt."""
    return _MEHRFACH_LEERZEICHEN.sub(" ", (text or "").strip()).lower()


def lade_aliase(master_folder):
    """
    Alias-Tabelle der Sammlung als Dict {Absender: relativer Zielordner}; leer, wenn
    die Datei fehlt oder unlesbar ist (ein kaputtes aliase.json darf die Automatik
    nie anhalten - dann matcht eben nur der Namensvergleich).
    """
    pfad = app_paths.aliase_path(master_folder)
    try:
        daten = sicher_speichern.lade_json(pfad)
    except (OSError, ValueError):
        return {}
    if not isinstance(daten, dict):
        return {}
    return {str(k): str(v) for k, v in daten.items() if str(k).strip() and str(v).strip()}


def speichere_alias(master_folder, absender, zielordner):
    """
    Trägt einen Alias ein (bzw. überschreibt ihn) und schreibt die Datei zurück.
    Der Absender wird so gespeichert, wie ihn die KI geliefert hat - lesbar für den
    Nutzer, der die Datei bei Bedarf von Hand pflegt; verglichen wird normalisiert.

    :return: die aktualisierte Alias-Tabelle
    """
    absender = (absender or "").strip()
    zielordner = (zielordner or "").strip()
    aliase = lade_aliase(master_folder)
    if not absender or not zielordner:
        return aliase
    # Bestehenden Eintrag mit gleicher Vergleichsform ersetzen statt doppelt anlegen
    # ("Gentilia" und "gentilia" sollen nicht zu zwei Zeilen werden).
    for vorhanden in list(aliase):
        if _normalisiere(vorhanden) == _normalisiere(absender):
            del aliase[vorhanden]
    aliase[absender] = zielordner
    pfad = app_paths.aliase_path(master_folder)
    sicher_speichern.schreibe_json(pfad, aliase, ensure_ascii=False, indent=2, sort_keys=True)
    return aliase


def loesche_alias(master_folder, absender):
    """
    Entfernt einen Alias wieder (Verwaltungsdialog der Ablage-Vorschau, 31.08.2026:
    ein falsch gelernter Eintrag wie „Landratsamt Musterstadt → Haus- und Grund Musterstadt"
    lenkt sonst dauerhaft ganze Absender in den falschen Ordner).

    :return: die aktualisierte Alias-Tabelle
    """
    aliase = lade_aliase(master_folder)
    vorher = len(aliase)
    for vorhanden in list(aliase):
        if _normalisiere(vorhanden) == _normalisiere(absender):
            del aliase[vorhanden]
    if len(aliase) != vorher:
        pfad = app_paths.aliase_path(master_folder)
        sicher_speichern.schreibe_json(pfad, aliase, ensure_ascii=False, indent=2, sort_keys=True)
    return aliase


def ist_objekt_alias(schluessel):
    """True, wenn der Alias-Schlüssel ein Objekt-Alias ist ("Objekt: Weidenstr. 8")."""
    return _normalisiere(schluessel).startswith(_normalisiere(OBJEKT_PRAEFIX))


def objekt_schluessel(objekt):
    """Alias-Schlüssel für ein Objekt: "Objekt: Weidenstr. 8"."""
    return OBJEKT_PRAEFIX + (objekt or "").strip()


def objekt_aus_schluessel(schluessel):
    """Objekt-Text ohne Präfix ("Objekt: Weidenstr. 8" -> "Weidenstr. 8"); Fremdes unverändert."""
    text = (schluessel or "").strip()
    if ist_objekt_alias(text):
        return text[len(OBJEKT_PRAEFIX):].strip()
    return text


def finde_objekt_alias(objekte, aliase):
    """
    Objekt-Alias für ein absenderloses Dokument: die Objekte des Dokuments (Katalog-
    Schreibweise, auto_pilot.objekte_ohne_ort) gegen die "Objekt: ..."-Einträge - EXAKT
    (normalisiert), erst das ganze Objekt, dann sein Haus-Kern (objekt_kern), damit
    "Weidenstr. 8 Whg 4" den Haus-Alias "Weidenstr. 8" trifft, "Weidenstr. 80" aber nicht.
    Das erste Objekt mit Treffer zählt.

    :return: (relativer Zielordner, getroffenes Objekt) oder (None, None)
    """
    objekt_aliase = {_normalisiere(objekt_aus_schluessel(k)): v
                     for k, v in (aliase or {}).items() if ist_objekt_alias(k)}
    objekt_aliase.pop("", None)
    if not objekt_aliase:
        return None, None
    for objekt in objekte or ():
        for kandidat in (objekt, objekt_kern(objekt)):
            ordner = objekt_aliase.get(_normalisiere(kandidat))
            if ordner:
                return ordner, objekt
    return None, None


def finde_alias(absender, aliase):
    """
    Sucht den zum Absender passenden Alias-Eintrag. Exakte Übereinstimmung (normalisiert)
    gewinnt immer; sonst Teilstring in beide Richtungen (Absender "Bayerische
    Landesbrandversicherung AG" trifft den Alias "Bayerische Landesbrandversicherung"),
    aber nur für Schlüssel ab MIN_TEILSTRING_LAENGE - bei mehreren Treffern der längste.
    Objekt-Aliase ("Objekt: ...") werden hier übersprungen - die gelten nur für
    absenderlose Dokumente (finde_objekt_alias).

    :return: relativer Zielordner oder None
    """
    gesucht = _normalisiere(absender)
    if not gesucht or not aliase:
        return None
    bester = None
    for schluessel, ordner in aliase.items():
        if ist_objekt_alias(schluessel):
            continue
        norm = _normalisiere(schluessel)
        if norm == gesucht:
            return ordner
        if len(norm) >= MIN_TEILSTRING_LAENGE and (norm in gesucht or gesucht in norm):
            if bester is None or len(norm) > len(bester[0]):
                bester = (norm, ordner)
    return bester[1] if bester else None


def loese_alias_ordner(zielordner, vorhandene_ordner):
    """
    Bildet den im Alias gespeicherten Ordner auf die aktuelle Sammlung ab: existiert er
    unverändert, wird er genommen; wurde er inzwischen in eine andere Buchstabengruppe
    verschoben, findet ihn der gleichnamige Ordner (letzter Pfadbestandteil) wieder.
    Sonst kommt der gespeicherte Pfad unverändert zurück - der Aufrufer legt ihn dann
    als neuen Ordner an (der Nutzer hat ihn schließlich ausdrücklich so gewollt).
    """
    if zielordner in vorhandene_ordner:
        return zielordner
    basis = os.path.basename(zielordner).lower()
    for ordner in vorhandene_ordner:
        if os.path.basename(ordner).lower() == basis:
            return ordner
    return zielordner
