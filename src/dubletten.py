"""
Dubletten-Erkennung: doppelt gescannte oder doppelt kopierte Dokumente finden.

Nutzerwunsch 30.08.2026: ein Beta-Tester scannt Briefe gelegentlich zweimal - zwei fast
gleiche PDFs im selben Ordner. Zwei Scans desselben Blatts sind NIE byteidentisch
(anderes Bild, andere OCR-Fehler: '3:-februar 2020' vs. '3:*Februar2020'), darum
drei Ähnlichkeits-Signale, die sich ergänzen:

1. Datei-Hash            - exakte Kopien (zweimal kopiert, '_1'-Dateien)
2. Text der ersten Seite - Wort-Überlappung (Jaccard) ab TEXT_SCHWELLE; unempfindlich
                           gegen Layout, empfindlich gegen sehr schlechte OCR
3. Bild-Fingerabdruck    - dHash von Seite 1 (PDFHandler.get_page_fingerprint):
                           unempfindlich gegen OCR-Müll und leichte Schieflage,
                           Hamming-Distanz bis BILD_SCHWELLE Bits gilt als gleich

Verglichen werden nur Dokumente mit gleicher Seitenzahl. Live-Messung an 411
Dokumenten (30.08.2026): Briefe derselben Vorlage (Jahresrechnungen, Beitragsrechnungen,
Kontoauszüge) haben fast denselben Bild-Fingerabdruck UND 60-85 % gemeinsame Wörter -
Bild und Text allein erzeugten Dutzende Fehlalarme. Der entscheidende Unterschied ist
das DOKUMENTDATUM: zwei Scans desselben Briefs tragen dasselbe Datum, die Jahresrechnung
vom Vorjahr nicht. Darum hängen die Schwellen davon ab, ob die Daten (Metadatum oder
Dateinamen-Präfix) gleich, verschieden oder unbekannt sind.

Reine Funktionen ohne Tkinter - das Tool tools/dubletten_finder.py baut die Oberfläche.
"""

import hashlib
import os
import re

import auto_pilot
import text_quality

# Text-Schwellen (Jaccard der Wortmengen von Seite 1) je nach Datums-Lage:
TEXT_GLEICHES_DATUM = 0.70      # gleiches Dokumentdatum: zwei Scans mit OCR-Fehlern
TEXT_DATUM_UNBEKANNT = 0.85     # kein Datum bekannt: nur sehr ähnlicher Text
TEXT_ANDERES_DATUM = 0.92       # verschiedene Daten: praktisch identischer Text (falsch datierte Kopie)
BILD_SCHWELLE = 6               # max. abweichende Bits im 64-Bit-dHash
TEXT_MIT_BILD_GLEICHES_DATUM = 0.50   # Bild gleich + gleiches Datum: Text darf schlechter sein (OCR-Müll)
TEXT_MIT_BILD_DATUM_UNBEKANNT = 0.75
MIN_WOERTER = 12                # unter so wenigen Wörtern ist der Textvergleich nicht aussagekräftig
TEXT_SICHER = 0.80              # ab hier gilt ein Paar als "sicher" (Vorschlag: eines in den Papierkorb);
                                # darunter nur "bitte prüfen" - Live-Fund: Gas- und Abwasser-Rechnung der
                                # Stadtwerke vom selben Tag sehen gleich aus und teilen 60-70 % der Wörter

_WORT = re.compile(r"[\wäöüß]{3,}", re.IGNORECASE)
# Für die Unterschiede-ANZEIGE zusätzlich 1-2-stellige Zahlen (Hausnummern!, Nutzerfund
# 30.08.2026: "Zum Alten Fass 1" vs. "... 3"). In die Ähnlichkeits-Schwelle fließen
# sie bewusst NICHT ein - einzelne Ziffern sind das OCR-fehleranfälligste überhaupt.
_WORT_ODER_ZAHL = re.compile(r"[\wäöüß]{3,}|\b\d{1,2}\b", re.IGNORECASE)

# Tag-Kategorien, deren Tags zwei ähnliche Dokumente UNTERSCHEIDEN statt verbinden:
# tragen beide Dokumente Tags einer dieser Kategorien und haben dort keinen gemeinsamen,
# ist es derselbe Serienbrief an verschiedene Personen bzw. der gleiche Bescheid für
# verschiedene Objekte - dann nie ein Papierkorb-Vorschlag, nur "Prüfen".
# Eine Quelle der Wahrheit: die Kategorienamen stehen in auto_pilot (dieses Modul
# importiert auto_pilot ohnehin, umgekehrt ginge es nicht). KATEGORIE_VARIANTEN deckt
# gewachsene Kataloge ab, die den Adressen-Zweig anders benannt haben (Praxisfund
# 01.09.2026: 'Wohnen & Immobilien / Adressen' statt 'Objekte & Adressen' - der exakte
# Namensvergleich lief ins Leere und die Objekt-Unterscheidung konnte NIE greifen).
UNTERSCHEIDUNGS_KATEGORIEN = (auto_pilot.KATEGORIE_PERSONEN, auto_pilot.KATEGORIE_OBJEKTE)
KATEGORIE_VARIANTEN = auto_pilot.KATEGORIE_VARIANTEN

def datei_hash(pfad):
    """SHA-256 des Dateiinhalts (exakte Kopien); '' bei Lesefehler."""
    try:
        h = hashlib.sha256()
        with open(pfad, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        return h.hexdigest()
    except OSError:
        return ""


def wortmenge(text):
    return {w.lower() for w in _WORT.findall(text or "")}


def text_aehnlichkeit(text_a, text_b):
    """Jaccard-Ähnlichkeit der Wortmengen zweier Texte (0..1); 0, wenn eine Seite zu wenig Wörter hat."""
    a, b = wortmenge(text_a), wortmenge(text_b)
    if len(a) < MIN_WOERTER or len(b) < MIN_WOERTER:
        return 0.0
    return len(a & b) / len(a | b)


def unterschiede(text_a, text_b, max_woerter=20):
    """
    Wörter, die nur in einem der beiden Texte vorkommen (für die Anzeige unter der
    Vorschau): zwei Scans desselben Briefs unterscheiden sich nur in OCR-Fehlern,
    zwei verschiedene Briefe derselben Vorlage in Rechnungsnummer, Betrag, Anrede,
    Datum oder Hausnummer - genau das soll der Nutzer auf einen Blick sehen (darum
    zählen hier auch 1-2-stellige Zahlen mit). Ziffern-Wörter zuerst, dann
    alphabetisch; auf max_woerter je Seite gekürzt.
    :return: (nur_in_a, nur_in_b) als sortierte Listen
    """
    a = {w.lower() for w in _WORT_ODER_ZAHL.findall(text_a or "")}
    b = {w.lower() for w in _WORT_ODER_ZAHL.findall(text_b or "")}

    def sortierung(w):
        return (not any(c.isdigit() for c in w), w)
    return (sorted(a - b, key=sortierung)[:max_woerter], sorted(b - a, key=sortierung)[:max_woerter])


def hamming(hash_a, hash_b):
    """Anzahl unterschiedlicher Bits zweier 64-Bit-Fingerabdrücke."""
    return bin(int(hash_a) ^ int(hash_b)).count("1")


def dokument_datum(info):
    """Dokumentdatum 'JJJJ-MM-TT' aus den Metadaten (KID_DokumentenDatum), sonst aus dem Dateinamen-Präfix; '' wenn unbekannt."""
    meta = info.get("meta") or {}
    datum = (meta.get("KID_DokumentenDatum") or "").strip()
    return datum or auto_pilot.datum_aus_dateiname(info.get("pfad", ""))


def tags_aus(info, katalog_tags):
    """
    Schnittmenge der PDF-Tags eines Dokuments (Metadaten-keywords) mit einer
    Katalog-Tag-Liste (kleingeschrieben verglichen).
    """
    if not katalog_tags:
        return set()
    meta = info.get("meta") or {}
    tags = {t.strip().lower() for t in (meta.get("keywords") or "").split(",") if t.strip()}
    return tags & {p.strip().lower() for p in katalog_tags}


MIN_NAMENSLAENGE = 4  # kürzere Katalog-Namen werden im Text nicht gesucht (zu viele Zufallstreffer)


def namen_im_text(info, katalog_tags):
    """
    Rückfall, wenn ein Dokument (noch) keine Tags der Kategorie trägt (Praxistest
    30.08.2026: die Zensus-Briefe an Hermann und Uta hatten nur '2022, Zensus' -
    die Namen standen aber im Anschriftenfeld des Seitentexts): sucht die Katalog-Namen
    als ganze Wortfolge im Text der ersten Seite. Mindestlänge gegen Zufallstreffer,
    Wortgrenzen gegen Teilwörter ('Prell' zählt nicht in 'Prellung').
    """
    text = (info.get("text") or "").lower()
    if not text or not katalog_tags:
        return set()
    treffer = set()
    for name in katalog_tags:
        n = (name or "").strip().lower()
        if len(n) >= MIN_NAMENSLAENGE and re.search(
                r"(?<![\wäöüß])" + re.escape(n) + r"(?![\wäöüß])", text):
            treffer.add(n)
    return treffer


def bewerte_paar(a, b, merkmale=None):
    """
    Sind zwei Dokument-Infos (Dicts aus sammle_info) Dubletten? Liefert den Grund als
    lesbaren Text oder None. Reihenfolge: exakte Kopie, Text (Schwelle je nach Datums-
    Lage), Bild + grober Text. Schwache Treffer (Text unter TEXT_SICHER) tragen den
    Vorsatz 'Prüfen:' - das Tool schlägt dort nichts für den Papierkorb vor.
    :param merkmale: {Kategorie: Katalog-Tags} der UNTERSCHEIDUNGS_KATEGORIEN. Jede
        Kategorie wird EINZELN geprüft (sonst würde der gemeinsame Personen-Tag den
        Objekt-Unterschied "Zum Alten Fass 1/3" überdecken): tragen beide Dokumente
        Tags einer Kategorie und haben dort keinen gemeinsamen, ist das Paar IMMER nur
        'Prüfen:' - derselbe Serienbrief an beide Ehepartner bzw. derselbe Bescheid für
        zwei Objekte bekommt nie einen Papierkorb-Vorschlag (Nutzerwunsch 30.08.2026).
        Dokumente ohne Tags der Kategorie: die Katalog-Namen werden stattdessen im
        Seitentext gesucht (namen_im_text).
    """
    grund = _bewerte_paar(a, b)
    if grund is None:
        return None
    for kategorie, katalog_tags in (merkmale or {}).items():
        # Tags des Dokuments sind maßgeblich; ohne Tags dieser Kategorie zählt der Seitentext
        ta = tags_aus(a, katalog_tags) or namen_im_text(a, katalog_tags)
        tb = tags_aus(b, katalog_tags) or namen_im_text(b, katalog_tags)
        if ta and tb and not (ta & tb):
            return (f"Prüfen: {grund} - aber verschiedene Tags aus '{kategorie}' "
                    f"({', '.join(sorted(ta))} / {', '.join(sorted(tb))})")
    if grund.startswith("identische") or ist_sicher(a, b):
        return grund
    return "Prüfen: " + grund


def ist_sicher(a, b):
    """Reicht die Text-Übereinstimmung für einen Papierkorb-Vorschlag ohne Nachfrage?"""
    if a.get("hash") and a.get("hash") == b.get("hash"):
        return True
    return text_aehnlichkeit(a.get("text", ""), b.get("text", "")) >= TEXT_SICHER


def _bewerte_paar(a, b):
    if a.get("seiten") != b.get("seiten"):
        return None
    if a.get("hash") and a.get("hash") == b.get("hash"):
        return "identische Datei"
    datum_a, datum_b = dokument_datum(a), dokument_datum(b)
    if datum_a and datum_b:
        if datum_a == datum_b:
            lage, text_schwelle, bild_schwelle = "gleiches Datum", TEXT_GLEICHES_DATUM, TEXT_MIT_BILD_GLEICHES_DATUM
        else:
            lage, text_schwelle, bild_schwelle = "anderes Datum", TEXT_ANDERES_DATUM, None
    else:
        lage, text_schwelle, bild_schwelle = "Datum unbekannt", TEXT_DATUM_UNBEKANNT, TEXT_MIT_BILD_DATUM_UNBEKANNT
    aehnlich = text_aehnlichkeit(a.get("text", ""), b.get("text", ""))
    if aehnlich >= text_schwelle:
        return f"Text zu {aehnlich:.0%} gleich ({lage})"
    if bild_schwelle is None or a.get("bildhash") is None or b.get("bildhash") is None:
        return None
    abstand = hamming(a["bildhash"], b["bildhash"])
    if abstand > BILD_SCHWELLE:
        return None
    if aehnlich >= bild_schwelle:
        return f"Seite 1 sieht gleich aus, Text zu {aehnlich:.0%} gleich ({lage})"
    ohne_text = (len(wortmenge(a.get("text", ""))) < MIN_WOERTER
                 and len(wortmenge(b.get("text", ""))) < MIN_WOERTER)
    if ohne_text and abstand <= 2 and lage == "gleiches Datum":
        return f"Seite 1 sieht gleich aus ({abstand} Bit Abstand, keine Textebene, gleiches Datum)"
    return None


def finde_dubletten(infos, merkmale=None):
    """
    Gruppiert Dokument-Infos zu Dubletten-Gruppen (Union-Find über alle Paare gleicher
    Seitenzahl). :param merkmale: {Kategorie: Katalog-Tags} (siehe bewerte_paar).
    :return: Liste von Gruppen; jede Gruppe ist (Liste der Infos, Grund-Text
    des ersten Treffers, sicher). 'sicher' ist False, sobald ein schwacher Treffer
    ('Prüfen: ...') die Gruppe zusammenhält. Gruppen mit nur einem Dokument entfallen.
    """
    eltern = list(range(len(infos)))
    gruende = {}
    unsicher = set()

    def finde(i):
        while eltern[i] != i:
            eltern[i] = eltern[eltern[i]]
            i = eltern[i]
        return i

    nach_seiten = {}
    for i, info in enumerate(infos):
        nach_seiten.setdefault(info.get("seiten"), []).append(i)
    for indizes in nach_seiten.values():
        for x in range(len(indizes)):
            for y in range(x + 1, len(indizes)):
                i, j = indizes[x], indizes[y]
                grund = bewerte_paar(infos[i], infos[j], merkmale)
                if grund:
                    wi, wj = finde(i), finde(j)
                    if wi != wj:
                        eltern[wj] = wi
                    gruende.setdefault(wi, grund)
                    if grund.startswith("Prüfen:"):
                        unsicher.add(i)
                        unsicher.add(j)
    gruppen = {}
    for i in range(len(infos)):
        gruppen.setdefault(finde(i), []).append((i, infos[i]))
    ergebnis = []
    for wurzel, mitglieder in gruppen.items():
        if len(mitglieder) > 1:
            sicher = not any(i in unsicher for i, _ in mitglieder)
            ergebnis.append(([info for _, info in mitglieder], gruende.get(wurzel, "ähnlich"), sicher))
    ergebnis.sort(key=lambda g: g[0][0]["pfad"].lower())
    return ergebnis


def empfehlung(gruppe):
    """
    Welches Dokument einer Gruppe behalten? Punkte für bessere Textebene, gesetzte
    Metadaten (Titel/Tags/Datum) und - bei Gleichstand - den kürzeren Dateinamen
    (die Kopie heißt meist '..._1.pdf'). :return: das zu behaltende Info-Dict
    """
    def punkte(info):
        meta = info.get("meta") or {}
        return (
            round(info.get("qualitaet", 0) / 5),                     # 5-%-Stufen: kleine Unterschiede ignorieren
            sum(1 for k in ("title", "keywords", "KID_DokumentenDatum") if (meta.get(k) or "").strip()),
            -len(os.path.basename(info["pfad"])),
        )
    return max(gruppe, key=punkte)


def sammle_info(pfad, text, seiten, bildhash, meta=None, mit_hash=True):
    """Info-Dict für ein Dokument (Aufrufer liefert die PDF-Werte, damit dieses Modul PyMuPDF-frei bleibt)."""
    return {
        "pfad": pfad,
        "seiten": seiten,
        "text": text or "",
        "qualitaet": text_quality.textqualitaet_prozent(text or "") if text else 0,
        "bildhash": bildhash,
        "hash": datei_hash(pfad) if mit_hash else "",
        "meta": meta or {},
    }


def waehle_partner(gruppe, info, gewuenscht=None):
    """
    Welches Dokument der Gruppe steht in der Vorschau RECHTS neben `info` (links)?
    `gewuenscht` (Pfad, per Shift+Klick gewählt) gewinnt, wenn er in der Gruppe liegt und
    nicht das linke Dokument selbst ist; sonst das erste andere Dokument der Gruppe.
    Bei Gruppen mit drei und mehr Einträgen war vorher nicht erkennbar, was rechts liegt
    (Nutzerfund 12.09.2026). None bei einer Gruppe ohne zweites Dokument.
    """
    andere = [i for i in gruppe if i["pfad"] != info["pfad"]]
    if not andere:
        return None
    if gewuenscht:
        for i in andere:
            if i["pfad"] == gewuenscht:
                return i
    return andere[0]
