"""
Titel, Datum und Dateiname eines Dokuments (aus auto_pilot ausgelagert, Etappe 14, 23.11.2026): Titel gegen den
Sammlungs-Wortschatz korrigieren, Datumsschreibweisen von KI und Nutzer lesen und prüfen, daraus den Dateinamen bauen.
Aufrufer dürfen weiter `auto_pilot.<name>` schreiben (Weiterleitung).
"""

import os
import re
from collections import Counter
from datetime import datetime

import spell_correct
from pdf_handler import PDFHandler

# Windows-verbotene Dateinamen-Zeichen (gleiche Menge wie file_operations.rename_file)
_VERBOTENE_ZEICHEN = re.compile(r'[\\/:*?"<>|]')
_DATUM_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Schreibweisen, die KI und Nutzer trotz "JJJJ-MM-TT"-Vorgabe liefern (Praxistest 30.08.2026:
# '20.07.2026' von der KI -> Zeile unsicher, und die Nutzer-Korrektur lehnte dieselbe deutsche
# Form ab): deutsch TT.MM.JJJJ, ISO mit Punkt/Schrägstrich, zweistelliges Jahr.
_DATUM_DEUTSCH = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})$")
_DATUM_ISO_LOCKER = re.compile(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})$")
MAX_TITEL_LAENGE = 80


def baue_titel_wortschatz(pdf_paths, basis=None):
    """
    Wortschatz für die Titel-Korrektur: der persistierte Sammlungs-Wortschatz (basis, aus
    dem Index) plus die Textebenen der ERSTEN Seiten aller Dokumente des aktuellen Stapels.
    Letzteres macht die Korrektur auch bei einer frischen Sammlung ohne Index-Historie
    wirksam - Ortsnamen wie 'Musterheim' stehen in den Adresszeilen des Stapels selbst.
    """
    wortschatz = Counter(basis or {})
    wortschatz.update(spell_correct.build_vocabulary(
        PDFHandler.get_first_page_text(p) for p in pdf_paths))
    return wortschatz


def korrigiere_titel(titel, vocabulary):
    """
    Prüft jedes Titelwort gegen den Sammlungs-Wortschatz (spell_correct.correct_proper_noun):
    ein unbekanntes Wort, dem ein häufiges bekanntes Wort in Editierdistanz <= 2 gegenüber-
    steht, wird ersetzt ('Musterbein' -> 'Musterheim'). Deterministisch, kein Modellaufruf -
    der prüfende Teil vertraut dem erzeugenden nicht blind.
    :return: (korrigierter Titel, Liste von (alt, neu)-Paaren - leer, wenn nichts geändert)
    """
    if not titel or not vocabulary:
        return titel, []
    korrekturen = []

    def ersetzen(match):
        wort = match.group(0)
        neu = spell_correct.correct_proper_noun(wort, vocabulary)
        if neu != wort:
            korrekturen.append((wort, neu))
        return neu

    return spell_correct.WORD_RE.sub(ersetzen, titel), korrekturen


def _bereinige_titel_fuer_dateiname(titel):
    """Entfernt Windows-verbotene Zeichen und kürzt auf eine handhabbare Länge."""
    titel = _VERBOTENE_ZEICHEN.sub("", titel).strip().rstrip(".")
    return titel[:MAX_TITEL_LAENGE].strip()


def baue_dateiname(datum, titel):
    """
    Baut den Ziel-Dateinamen nach dem Sammlungs-Schema 'JJJJMMTT_Titel.pdf'
    (wie die bestehenden Scanner-Dateien). Setzt validierte Eingaben voraus
    (siehe baue_entscheidung) - bei leerem Titel/Datum wäre die Entscheidung
    ohnehin "unsicher" und es wird nie umbenannt.
    """
    return f"{datum.replace('-', '')}_{_bereinige_titel_fuer_dateiname(titel)}.pdf"


_DATEINAME_DATUM = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})(?![\d])")
# Deutsche Reihenfolge TTMMJJJJ ohne Trenner ('01122024_HKV.pdf'), wie sie manche Scanner-
# Apps vergeben (Betatest 25.10.2026). Nie mehrdeutig zu JJJJMMTT: dort stehen an Stelle 5-6
# ein Monat (01-12), hier der Jahrhundertanfang (19/20) - es passt immer höchstens eine Lesart.
_DATEINAME_DATUM_DEUTSCH = re.compile(r"^(\d{2})(\d{2})(\d{4})(?![\d])")


def datum_aus_dateiname(pdf_path):
    """
    Datums-Präfix des Dateinamens ('20200927_Brief.pdf', '2020-09-27 Brief.pdf', '27092020_Brief.pdf') als
    'JJJJ-MM-TT' - nur als VORBELEGUNG für die Datum-Korrektur durch den Nutzer, nie als
    automatischer Ersatz: bei alten Scans ist das Präfix das Scan-, nicht das Dokumentdatum.
    Leer, wenn kein plausibles Datum vorne steht.
    """
    name = os.path.basename(pdf_path or "")
    m = _DATEINAME_DATUM.match(name)
    if m:
        datum = "-".join(m.groups())
        if _datum_ist_plausibel(datum):
            return datum
    m = _DATEINAME_DATUM_DEUTSCH.match(name)
    if m:
        tag, monat, jahr = m.groups()
        datum = f"{jahr}-{monat}-{tag}"
        if _datum_ist_plausibel(datum):
            return datum
    return ""


def normalisiere_datum(text):
    """
    Bringt ein Datum in die Form JJJJ-MM-TT: akzeptiert '2026-07-20', '20.07.2026',
    '20.7.26', '2026.07.20', '20/07/2026' (auch mit umgebenden Leerzeichen/Punkt am Ende).
    Zweistellige Jahre wie im Hauptfenster (PDFHandler.jahr_vierstellig: bis zum laufenden Jahr 20xx,
    sonst 19xx). Liefert den Text unverändert
    (gestrippt), wenn keine Form passt - die Plausibilitätsprüfung lehnt ihn dann ab.
    """
    text = (text or "").strip().rstrip(".")
    m = _DATUM_ISO_LOCKER.match(text)
    if m:
        jahr, monat, tag = m.groups()
    else:
        m = _DATUM_DEUTSCH.match(text)
        if not m:
            return text
        tag, monat, jahr = m.groups()
        if len(jahr) == 2:
            jahr = str(PDFHandler.jahr_vierstellig(int(jahr)))
    return f"{int(jahr):04d}-{int(monat):02d}-{int(tag):02d}"


WOCHENTAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")


def datum_aus_eingabe(text):
    """
    Prüft eine Datums-Eingabe des Nutzers (B4b, 21.11.2026): alle Formen von normalisiere_datum und zusätzlich
    reine Ziffern TTMMJJ / TTMMJJJJ wie im Datumsfeld des Hauptfensters ('200726' -> 2026-07-20).
    :return: ('JJJJ-MM-TT' oder None, Hinweis für den Dialog) - der Hinweis nennt bei Erfolg den Wochentag
             (Tippfehler fallen so auf), sonst den Grund (Zukunft, vor 1950, kein Datum).
    """
    roh = (text or "").strip()
    if not roh:
        return None, "Bitte ein Datum eingeben, z.B. 20.07.2026."
    if roh.isdigit() and len(roh) in (6, 8):
        roh = f"{roh[:2]}.{roh[2:4]}.{roh[4:]}"
    datum = normalisiere_datum(roh)
    try:
        wert = datetime.strptime(datum, "%Y-%m-%d") if _DATUM_FORMAT.match(datum) else None
    except ValueError:
        wert = None
    if wert is None:
        return None, "Kein gültiges Datum - bitte als TT.MM.JJJJ, JJJJ-MM-TT oder TTMMJJ."
    if wert.date() > datetime.now().date():
        return None, f"{wert:%d.%m.%Y} liegt in der Zukunft."
    if wert.year < 1950:
        return None, f"{wert:%d.%m.%Y} liegt vor 1950 - bitte prüfen."
    return datum, f"✓ {WOCHENTAGE[wert.weekday()]}, {wert:%d.%m.%Y}"


def _datum_ist_plausibel(datum):
    """JJJJ-MM-TT, echtes Kalenderdatum, nicht in der Zukunft und nicht älter als 1950."""
    if not _DATUM_FORMAT.match(datum or ""):
        return False
    try:
        wert = datetime.strptime(datum, "%Y-%m-%d")
    except ValueError:
        return False
    return 1950 <= wert.year and wert.date() <= datetime.now().date()
