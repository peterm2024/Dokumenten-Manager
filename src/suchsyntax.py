"""
Suchsyntax ohne Oberfläche (08.11.2026, KONZEPT_MAIL_AUF_ABRUF): was die Dokumentsuche des Hauptfensters
(`search_manager`) und die Mail-Suche (`mail_import`) gemeinsam verstehen, dazu die leichte Unschärfe der Mail-Suche.
Nur Standardbibliothek: `mail_import` muss frei von Tkinter bleiben, `search_manager` ist es nicht.

- `split_terms`: Suchtext → Begriffe (mehrere Wörter = UND, Anführungszeichen, Platzhalter).
- `datum_grenze`: „2024“, „03.2024“, „15.03.2024“ → Datum (Anfang oder Ende des Zeitraums).
- `normalisiere`: klein, Umlaute und ß ausgeschrieben, Leerraum zusammengefasst - für Suchtext UND Suchbegriff.
- `aehnliche_woerter`: Wörter aus einem Wortschatz mit höchstens einem Tippfehler (ab 9 Buchstaben zwei).
"""
import calendar
import datetime
import re

_NUR_JAHR = re.compile(r"^\d{4}$")
_MONAT_JAHR = re.compile(r"^(\d{1,2})\.(\d{4})$")


def split_terms(search_text):
    """
    Zerlegt den Suchtext in die einzeln zu prüfenden Begriffe (Mehrwort-Suche = UND).
    Wildcard-Muster bleiben ein Begriff. Text in Anführungszeichen wird EIN Begriff
    mit Leerzeichen ("Max Mustermann" -> 'max mustermann', ein fehlendes schließendes
    Anführungszeichen beim Tippen gilt bis zum Ende). Ein einzelnes Wort in Anführungszeichen
    behält sie als Kennzeichen für die genaue Suche ('"ramen"', siehe SearchManager.begriff_matcher),
    mit Platzhalter bleibt es ein Muster. Leerer Text -> leere Liste.
    """
    search_text = (search_text or "").strip().lower()
    if not search_text:
        return []
    if '"' in search_text:
        begriffe = []
        for i, teil in enumerate(search_text.split('"')):
            if i % 2 == 1:
                phrase = " ".join(teil.split())
                if phrase:
                    muster = " " in phrase or "*" in phrase or "?" in phrase
                    begriffe.append(phrase if muster else f'"{phrase}"')
            else:
                begriffe.extend(split_terms(teil))
        return begriffe
    if "*" in search_text or "?" in search_text:
        return [search_text]
    return search_text.split()


def datum_grenze(text, ende=False):
    """
    Eingabe eines Von-/Bis-Feldes → date, sonst None. Neben dem vollen Datum (TT.MM.JJJJ) auch gröbere
    Angaben (Nutzerwunsch 01.09.2026: „Von 2020 – Bis 2022“ findet 2020, 2021 und 2022):
        "2020"    →  Von: 01.01.2020   Bis: 31.12.2020
        "07.2020" →  Von: 01.07.2020   Bis: 31.07.2020
    :param ende: True für das Bis-Feld (füllt ans ENDE des Jahres/Monats auf).
    """
    text = (text or "").strip()
    if not text or text == "TT.MM.JJJJ":
        return None
    try:
        return datetime.datetime.strptime(text, "%d.%m.%Y").date()
    except ValueError:
        pass
    if _NUR_JAHR.match(text):
        jahr = int(text)
        return datetime.date(jahr, 12, 31) if ende else datetime.date(jahr, 1, 1)
    treffer = _MONAT_JAHR.match(text)
    if treffer:
        monat, jahr = int(treffer.group(1)), int(treffer.group(2))
        if 1 <= monat <= 12:
            if not ende:
                return datetime.date(jahr, monat, 1)
            return datetime.date(jahr, monat, calendar.monthrange(jahr, monat)[1])
    return None


# ---------------------------------------------------------------- leichte Unschärfe (Mail-Suche)
_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})

# Wörter des Wortschatzes: nur Buchstaben. Zahlen sucht man genau, ein „Tippfehler“ in einer Rechnungsnummer
# fände eine andere Rechnung
WORT = re.compile(r"[^\W\d_]+")

UNSCHARF_AB = 5          # kürzere Wörter nur genau („Bank“ und „Dank“)
ZWEI_FEHLER_AB = 9       # ab hier zwei Tippfehler


def normalisiere(text):
    """Klein, „ä“ → „ae“ usw., Leerraum zu einem Leerzeichen: „Kündigung“ und „Kuendigung“ werden gleich."""
    return " ".join((text or "").lower().translate(_UMLAUTE).split())


def erlaubte_fehler(begriff):
    """0 unter UNSCHARF_AB Buchstaben, 1 darüber, 2 ab ZWEI_FEHLER_AB."""
    n = len(begriff)
    return 0 if n < UNSCHARF_AB else 1 if n < ZWEI_FEHLER_AB else 2


def abstand_hoechstens(a, b, grenze):
    """True, wenn sich a und b um höchstens `grenze` Tippfehler unterscheiden: Buchstabe falsch, zu viel, zu wenig,
    zwei Nachbarn vertauscht (eingeschränkte Damerau-Levenshtein-Distanz). Bricht ab, sobald eine Zeile über der
    Grenze liegt."""
    if abs(len(a) - len(b)) > grenze:
        return False
    if a == b:
        return True
    vorvorige, vorige = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        zeile = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            kosten = 0 if a[i - 1] == b[j - 1] else 1
            wert = min(vorige[j] + 1, zeile[j - 1] + 1, vorige[j - 1] + kosten)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                wert = min(wert, vorvorige[j - 2] + 1)
            zeile[j] = wert
        if min(zeile) > grenze:
            return False
        vorvorige, vorige = vorige, zeile
    return vorige[-1] <= grenze


def _passt(begriff, buchstaben, wort, grenze):
    """Gleicher erster Buchstabe, dann ein billiger Vorfilter (jeder Tippfehler ändert höchstens zwei Buchstaben der
    Menge), erst dann die Distanz."""
    return (wort[:1] == begriff[:1] and len(buchstaben.symmetric_difference(wort)) <= 2 * grenze
            and abstand_hoechstens(begriff, wort, grenze))


def aehnliche_woerter(begriff, wortschatz):
    """
    Wörter aus `wortschatz` (normalisiert), die dem normalisierten `begriff` bis auf die erlaubten Tippfehler gleichen,
    ohne den Begriff selbst und ohne Wörter, die ihn wörtlich enthalten (die findet die Suche ohnehin).
    Längere Wörter: Verglichen wird jeder Wortteil, der mit dem ersten Buchstaben des Begriffs beginnt - so findet
    „rechnug“ auch „rechnungen“, „stromrechnung“ und „stromrechnungen“.
    Der erste Buchstabe muss stimmen (am Wortanfang vertippt man sich selten): Sonst fände „mahnung“ mit einem
    fehlenden Buchstaben „ahnung“ - Vormessung 08.11.2026, auch „autovervollstaendigung“ zu „kuendigung“.
    :return: set
    """
    grenze = erlaubte_fehler(begriff)
    if not grenze:
        return set()
    n, buchstaben = len(begriff), set(begriff)
    gefunden = set()
    for wort in wortschatz:
        if begriff in wort:
            continue
        lang = len(wort)
        if lang < n - grenze:
            continue
        if lang <= n + grenze:
            if _passt(begriff, buchstaben, wort, grenze):
                gefunden.add(wort)
            continue
        if _passt_im_wort(begriff, buchstaben, wort, grenze):
            gefunden.add(wort)
    return gefunden


def _passt_im_wort(begriff, buchstaben, wort, grenze):
    """Passt ein Wortteil, der mit dem ersten Buchstaben des Begriffs beginnt? Erste Buchstaben sind selten genug,
    dass nur wenige Stellen je Wort zu prüfen sind."""
    n, anfang = len(begriff), wort.find(begriff[0])
    while anfang != -1 and anfang <= len(wort) - (n - grenze):
        for laenge in range(n - grenze, n + grenze + 1):
            teil = wort[anfang:anfang + laenge]
            if len(teil) == laenge and _passt(begriff, buchstaben, teil, grenze):
                return True
        anfang = wort.find(begriff[0], anfang + 1)
    return False
