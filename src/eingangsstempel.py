"""
Eingangsstempel statt Briefdatum erkennen (Frisch-Versuch 20.11.2026, Etappe 13).

Die KI liest das Dokumentdatum vom Bild der ersten Seite. Trägt der Brief einen Eingangsstempel („16. JAN. 2026“,
„EINGANG 16.01.2026“), nahm sie in einem frischen KID bei 4 von 29 Prüfbriefen das Stempeldatum - 3 bis 4 Tage nach
dem Briefdatum. In der Firma bekommt jeder Brief einen Stempel. Die Regel hier ist bewusst eng: Sie greift nur, wenn
das KI-Datum in der Textebene als Stempel steht, NICHT zugleich als gewöhnliches Datum, und es höchstens
MAX_TAGE_VOR_STEMPEL davor ein gewöhnliches Datum gibt - dann gilt das späteste davon als Briefdatum.

Gemessen 21.11.2026: Prüfbriefe digital 25/29 -> 29/29, gescannt niedrig 32/33 -> 33/33; echter Korpus (403
Dokumente): 6 Dokumente geändert, alle 6 von Hand geprüft richtig; nichts verschlechtert.

Nur Standardbibliothek, GUI-frei (tests/test_modulgrenzen.py). Ohne Textebene (reiner Bild-Scan) tut die Regel nichts.
"""
import re
from datetime import date, timedelta

MAX_TAGE_VOR_STEMPEL = 31   # ein Brief, der länger als einen Monat unterwegs war, ist kein Fall für diese Regel

_MONATE = ("januar", "februar", "märz", "april", "mai", "juni", "juli", "august", "september", "oktober",
           "november", "dezember")
# Stempel-Monate: abgekürzt und GROSS („16. JAN. 2026“). Gemischte Schreibung („16. Jan. 2026“, „21. Mai 2022“) ist
# ein gewöhnliches Datum im Brieftext. SEPT vor SEP, sonst bliebe das T übrig.
_STEMPEL_MONATE = {"JAN": 1, "FEB": 2, "MÄR": 3, "MRZ": 3, "MAR": 3, "APR": 4, "MAI": 5, "JUN": 6, "JUL": 7,
                   "AUG": 8, "SEPT": 9, "SEP": 9, "OKT": 10, "NOV": 11, "DEZ": 12}
_ZAHL = re.compile(r"(?<!\d)(\d{1,2})\s?\.\s?(\d{1,2})\s?\.\s?(\d{4}|\d{2})(?!\d)")   # Scanner: „01 .12.2025“
_LANG = re.compile(r"(?<!\d)(\d{1,2})\.\s*(" + "|".join(_MONATE) + r")\s+(\d{4})(?!\d)", re.IGNORECASE)
# Jahr darf fehlen: Der Scanner las „24. APR.“ ohne die Jahreszahl darunter (gescannt hoch, 20.11.2026)
_STEMPEL = re.compile(r"(?<!\d)(\d{1,2})\s?\.\s*(" + "|".join(_STEMPEL_MONATE) + r")(?![A-Za-zÄÖÜäöü])\.?"
                      r"(?:\s*(\d{4})(?!\d))?")
# Zeile eines Stempels: „Eingang“, „Posteingang“, „Eingegangen am“ - aber nicht „Zahlungseingang“ (Kontoauszug)
_EINGANG = re.compile(r"\beingang\b|\bposteingang\b|\beingegangen\b", re.IGNORECASE)


def _datum(jahr, monat, tag):
    jahr = int(jahr)
    if jahr < 100:
        jahr += 2000 if jahr < 50 else 1900
    try:
        return date(jahr, int(monat), int(tag))
    except ValueError:
        return None


def textdaten(text):
    """
    Daten aus der Textebene, getrennt nach gewöhnlichen Daten und Stempeln - klein und JSON-fähig, damit sie in
    `gelesen` mitreisen (auto_pilot.lies_dokument). :return: {"text": ["JJJJ-MM-TT", ...],
    "stempel": [[jahr (0 = fehlt), monat, tag], ...]}
    """
    normal, stempel = set(), set()
    for zeile in (text or "").splitlines():
        hier = {_datum(m[3], m[2], m[1]) for m in _ZAHL.finditer(zeile)}
        hier |= {_datum(m[3], _MONATE.index(m[2].lower()) + 1, m[1]) for m in _LANG.finditer(zeile)}
        hier.discard(None)
        if _EINGANG.search(zeile):
            stempel |= {(d.year, d.month, d.day) for d in hier}
        else:
            normal |= hier
        for m in _STEMPEL.finditer(zeile):
            monat, tag = _STEMPEL_MONATE[m[2]], int(m[1])
            if m[3]:
                d = _datum(m[3], monat, tag)
                if d:
                    stempel.add((d.year, d.month, d.day))
            elif 1 <= tag <= 31:
                stempel.add((0, monat, tag))
    return {"text": sorted(d.isoformat() for d in normal), "stempel": sorted([j, m, t] for j, m, t in stempel)}


def briefdatum_statt_stempel(datum, daten):
    """
    :param datum: Datum der KI, JJJJ-MM-TT
    :param daten: textdaten() des Dokuments oder None
    :return: das Briefdatum (JJJJ-MM-TT), wenn `datum` ein Eingangsstempel ist und davor ein Briefdatum steht -
        sonst "" (Datum bleibt)
    """
    if not daten:
        return ""
    try:
        ki = date.fromisoformat(datum or "")
    except ValueError:
        return ""
    if ki.isoformat() in daten.get("text", ()):
        return ""   # steht auch als gewöhnliches Datum da: am Tag des Briefs eingegangen, oder kein Stempel
    if not any(m == ki.month and t == ki.day and j in (0, ki.year) for j, m, t in daten.get("stempel", ())):
        return ""
    frueher = ki - timedelta(days=MAX_TAGE_VOR_STEMPEL)
    davor = [d for d in (date.fromisoformat(s) for s in daten.get("text", ())) if frueher <= d < ki]
    return max(davor).isoformat() if davor else ""
