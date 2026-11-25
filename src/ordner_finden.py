"""
Ordnernamen vergleichen und Ablageordner finden (aus auto_pilot ausgelagert, Etappe 14, 23.11.2026): Kernname,
Buchstabengruppe, Namensvergleich exakt und ähnlich, Hinweise aus Tags und Dateiname, dazu Posteingang und Ordnerliste
der Sammlung. Aufrufer dürfen weiter `auto_pilot.<name>` schreiben (Weiterleitung).
"""

import functools
import os
import re
from collections import Counter

import app_paths
import mail_lesen
import ordnernamen
from titel_datum import _VERBOTENE_ZEICHEN

# Ordnernamen für neue Sammlungen (Ziffern-Präfix sortiert in JEDER Ansicht vor
# Buchstaben, siehe KONZEPT_SENIORENMODUS.md); bestehende Sammlungen werden über
# finde_posteingang() flexibel erkannt (z.B. "00_Posteingang" beim Entwickler).
POSTEINGANG_ORDNER = "0_Posteingang"
UNSICHER_ORDNER = "0_Unsicher"
# Sammelablage einzelner Mails (E17, Peter 06.11.2026): je Buchstabengruppe einer, nie Ziel für etwas anderes
SAMMEL_ORDNER = "Einzelne Mails"

# Gerätenamen, die Windows als Datei-/Ordnernamen ablehnt - maßgeblich ist der Teil vor dem ersten Punkt
# ("Aux.Bank" ist ebenso gesperrt). Analyse der Firmen-KI 17.11.2026.
_RESERVIERTE_NAMEN = re.compile(r"^(con|prn|aux|nul|com[1-9]|lpt[1-9])$", re.IGNORECASE)

# Kürzere Ordnernamen werden nie als Absender-Treffer gewertet (Fehlalarm-Schutz,
# siehe finde_passenden_ordner) - unter dieser Länge wären Teilstring-Treffer zu
# beliebig (z.B. ein zweibuchstabiger Ordner, der zufällig überall vorkommt).
MIN_ORDNER_MATCH_LAENGE = 4

# Neue Ordnernamen werden auf diese Länge gekürzt (an einer Wortgrenze) - Praxisnamen
# mit mehreren Ärzten oder volle Firmenbezeichnungen sind sonst im Baum unlesbar.
MAX_ORDNER_LAENGE = 40

# Anreden/Titel/Zusätze, die beim Kernnamen (Sortier- und Vergleichsbasis) am Anfang
# übersprungen werden: "Dr. Emil Carius" sortiert unter C, nicht unter D.
_ANREDEN = re.compile(
    r"^(?:(?:herr|frau|firma|fa\.|praxis|kanzlei|dr\.?|prof\.?|med\.?|dent\.?|dipl\.?[-\w.]*|"
    r"ing\.?|rechtsanwalt|rechtsanwältin|zahnarztpraxis|arztpraxis)\s+)+",
    re.IGNORECASE)
_UMLAUT_MAP = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "s", "Ä": "A", "Ö": "O", "Ü": "U"})
# Buchstabengruppen-Ordner der Standard-Struktur: "A - B - C - D - E - F" (Einzelbuchstaben,
# durch Bindestriche getrennt) bzw. "[0-9]" für Ziffern.
_BUCHSTABENGRUPPE = re.compile(r"^\s*[A-Za-z](?:\s*-\s*[A-Za-z])*\s*$")
# Bereichs-Form der Standard-Ordnerstruktur aus folder_default.json: "[A-F]", "[G-L]" (auch ohne
# Klammern, auch mit Gedankenstrich). Praxistest 30.08.2026: die frisch generierte Struktur beim
# Ein Beta-Tester nutzt genau diese Form - ohne Erkennung landeten alle neuen Ordner flach im Hauptordner.
_BUCHSTABENBEREICH = re.compile(r"^\s*\[?\s*([A-Za-z])\s*[-–]\s*([A-Za-z])\s*\]?\s*$")
_ZIFFERNGRUPPE = re.compile(r"^\s*\[?\s*0\s*-\s*9\s*\]?\s*$")


def kernname(name):
    """
    Reduziert einen Ordner-/Absendernamen auf seinen Kern - die Basis für Vergleich
    und Buchstaben-Einsortierung. Telefonbuch-Form 'Carius, Dr. Emil (Zahnarzt)' ->
    'Carius' (Teil vor dem Komma); Anreden/Titel am Anfang werden übersprungen
    ('Dr. Maier' -> 'Maier'); Klammerzusätze fallen weg.
    """
    if not name:
        return ""
    kern = name.split(",", 1)[0]
    kern = re.sub(r"\(.*?\)", " ", kern)
    kern = _ANREDEN.sub("", kern.strip())
    return " ".join(kern.split()).strip()


def sortierbuchstabe(name):
    """Erster Buchstabe des Kernnamens, Umlaute aufgelöst (Ä -> A); Ziffer -> '0-9'; '' wenn unbestimmbar. Die
    Arzt-Form 'Dr. Beispiel, Eva' sortiert unter D (Peter 22.11.2026: „durch das ‚Dr.‘ am Anfang sind die meisten
    Ärzte zusätzlich vorsortiert“) - verglichen wird weiter mit dem Kern 'Beispiel'."""
    if ordnernamen.ist_arzt_ordnername(name):
        return "D"
    kern = kernname(name).translate(_UMLAUT_MAP)
    for zeichen in kern:
        if zeichen.isdigit():
            return "0-9"
        if zeichen.isalpha() and zeichen.isascii():
            return zeichen.upper()
    return ""


def finde_buchstabengruppe(name, vorhandene_ordner):
    """
    Sucht unter den Ordnern der OBERSTEN Ebene den Buchstabengruppen-Ordner, unter den ein
    neuer Ordner mit diesem Namen gehört ('Carius, Dr. Emil' -> 'A - B - C - D - E - F').
    Liefert None, wenn die Sammlung keine Buchstabengruppen nutzt - dann bleibt der neue
    Ordner flach im Hauptordner (bisheriges Verhalten).
    """
    buchstabe = sortierbuchstabe(name)
    if not buchstabe:
        return None
    for ordner in vorhandene_ordner:
        if os.sep in ordner or "/" in ordner:
            continue  # nur oberste Ebene
        if buchstabe == "0-9":
            if _ZIFFERNGRUPPE.match(ordner):
                return ordner
            continue
        if buchstabe in buchstaben_der_gruppe(ordner):
            return ordner
    return None


def buchstaben_der_gruppe(ordnername):
    """
    Buchstaben, die ein Buchstabengruppen-Ordner abdeckt: 'A - B - C' -> {A, B, C},
    '[A-F]' / 'A-F' -> {A, B, C, D, E, F}. Leere Menge, wenn der Name keine Gruppe ist.
    """
    m = _BUCHSTABENBEREICH.match(ordnername)
    if m:
        von, bis = m.group(1).upper(), m.group(2).upper()
        if von <= bis:
            return {chr(c) for c in range(ord(von), ord(bis) + 1)}
        return set()
    if _BUCHSTABENGRUPPE.match(ordnername):
        return {t.strip().upper() for t in ordnername.split("-")}
    return set()


# Wörter, mit denen ein auf MAX_ORDNER_LAENGE gekürzter Name nicht enden soll
_BINDEWOERTER_AM_ENDE = {"und", "u.", "u", "&", "+", "/", "-", "für", "f.", "der", "die", "das", "des",
                         "dem", "den", "von", "vom", "im", "in", "zu", "zum", "zur", "am", "an", "bei", "mit"}


def bereinige_ordnername(name):
    """
    Macht aus dem KI-Ordnernamen einen gültigen, lesbaren Ordnernamen: verbotene Zeichen
    raus, Leerraum normalisiert, Großschreibung am Anfang, Kürzung auf MAX_ORDNER_LAENGE
    an einer Wortgrenze (kein abgeschnittenes Wort im Baum).
    """
    name = _VERBOTENE_ZEICHEN.sub("", name or "")
    name = " ".join(name.split()).strip(" .")
    if len(name) > MAX_ORDNER_LAENGE:
        gekuerzt = name[:MAX_ORDNER_LAENGE]
        if " " in gekuerzt:
            gekuerzt = gekuerzt.rsplit(" ", 1)[0]
        # Eine durch die Kürzung offen gebliebene Klammer fliegt ganz raus (Prüflauf 28.10.2026:
        # "Wolf Nikolaus (Bevollmächtigter" aus "... (Bevollmächtigter Bezirksschornsteinfeger)")
        if gekuerzt.count("(") > gekuerzt.count(")") and gekuerzt.rfind("(") > 0:
            gekuerzt = gekuerzt[:gekuerzt.rfind("(")]
        name = gekuerzt.strip(" ,.(-")
        # Kein Bindewort am Ende stehen lassen (Betatest 26.10.2026: "Haus- und
        # Grundeigentümer ... und" aus "... und Umgebung e.V.")
        woerter = name.split()
        while len(woerter) > 1 and woerter[-1].lower() in _BINDEWOERTER_AM_ENDE:
            woerter.pop()
        name = " ".join(woerter).strip(" ,.(-")
    if name and name[0].islower():
        name = name[0].upper() + name[1:]
    return _ohne_geraetenamen(name)


def _ohne_geraetenamen(name):
    """Hängt an einen Windows-Gerätenamen ('NUL', 'Aux.Bank') ein '_' an, damit sich der Ordner anlegen lässt."""
    stamm, punkt, rest = name.partition(".")
    if _RESERVIERTE_NAMEN.match(stamm.rstrip()):
        return f"{stamm.rstrip()}_{punkt}{rest}"
    return name


# Adressbestandteile hinter dem Absendernamen (Live-Fund 07.09.2026: die KI las die
# Rücksendezeile über dem Anschriftenfenster "Bay. LfSt, PF 0151 Straubing" als Absender,
# die Vollautomatik legte einen Ordner mit genau diesem Namen an): ab Postfach oder
# "PLZ Ort" wird abgeschnitten, ebenso eine angehängte Straße mit Hausnummer.
_ADRESSTEIL = re.compile(
    r"[\s,;]*(?:\bPostfach\b|\bPostf\.|\bPF\b\.?)\s*\d.*$"      # Postfach 1234 / PF 0151 Straubing
    r"|[\s,;]*\b\d{5}\s+[A-ZÄÖÜ].*$"                            # 94301 Straubing
    r"|[\s,;]*\b\S*(?:str\.?|straße|strasse|weg|platz|gasse|allee|ring)\s*\d+.*$",
    re.IGNORECASE)
# Abgekürztes Wort ("Bay.", "Landesamt f.") bzw. Binnen-Großbuchstaben ("LfSt", "BayLfSt")
_ABKUERZUNG = re.compile(r"^[^\W\d_]{1,5}\.$")
_BINNENVERSAL = re.compile(r"[a-zäöüß][A-ZÄÖÜ]")


def trenne_adresszeile(absender):
    """
    Schneidet Adressbestandteile (Postfach, PLZ + Ort, Straße + Hausnummer) vom Absender ab:
    'Bay. LfSt, PF 0151 Straubing' -> ('Bay. LfSt', True). Liefert (Kern, war_adresszeile);
    ohne Adressteil kommt der Text unverändert mit False zurück.
    """
    text = " ".join((absender or "").split())
    if not text:
        return "", False
    kern = _ADRESSTEIL.sub("", text).strip(" ,;-")
    return (kern, True) if kern != text else (text, False)


def absender_ist_kuerzel(absender):
    """
    Besteht der Absender nur aus Abkürzungen ('Bay. LfSt', 'Bay. LfSt.')? Dann taugt er
    nicht als Ordnername - niemand sucht 'Bayerisches Landesamt für Steuern' unter 'Bay.'.
    Ein Wort gilt als Abkürzung, wenn es mit Punkt endet, Binnen-Großbuchstaben hat oder
    höchstens vier Zeichen lang ist; und es muss mindestens eine Punkt-/Binnenversal-
    Abkürzung dabei sein, damit 'ADAC' oder 'HKV' NICHT als Kürzel gelten (das sind
    gebräuchliche Namen, die als Ordner funktionieren).
    """
    woerter = (absender or "").split()
    if not woerter:
        return False
    abgekuerzt = [w for w in woerter if _ABKUERZUNG.match(w) or _BINNENVERSAL.search(w)]
    if not abgekuerzt:
        return False
    return all(_ABKUERZUNG.match(w) or _BINNENVERSAL.search(w) or len(w.strip(".,")) <= 4 for w in woerter)


def ordnername_passt_zum_absender(ordnername, absender):
    """
    Deterministische Sperre gegen einen Live-Fund (29.08.2026, FALLSTRICKE #32): die KI
    lieferte als Telefonbuch-Ordnernamen den EMPFÄNGER des Briefs ('Mustermann, Hermann' bei
    Absender 'Amsel BKK') - der Prompt verlangte 'Nachname, Vorname' für Personen, und
    der einzige Personenname auf einer Versicherungsrechnung ist nun mal der Adressat.
    Ein Ordnername gilt nur dann als vertrauenswürdig, wenn jedes Wort seines Kerns
    (ab 3 Zeichen) im Absender vorkommt - 'Carius' in 'Dr. Emil Carius ...' ja,
    'Mustermann' in 'Amsel BKK' nein.
    """
    kern_worte = [w for w in kernname(ordnername).lower().split() if len(w) >= 3]
    if not kern_worte or not absender:
        return False
    absender_norm = absender.lower()
    return all(w in absender_norm for w in kern_worte)


# Namenszusätze ohne Unterscheidungskraft für den Wort-Mengen-Vergleich: Rechtsformen
# und Füllwörter. "Iqua Deutschland GmbH" und "Iqua SE" meinen im Alltag denselben
# Absender - unterscheidend ist "Iqua", nicht die Rechtsform.
_NAMENS_RAUSCHEN = {"gmbh", "ag", "se", "kg", "ohg", "mbh", "co", "ev", "e", "v",
                    "inc", "ltd", "team", "deutschland", "und", "der", "die", "das"}


def _namenswoerter(text):
    """Wörter eines Namens als Menge, klein, ohne Rechtsform-/Füllwort-Rauschen."""
    return {w for w in re.split(r"[^\wäöüß]+", (text or "").lower())
            if w and w not in _NAMENS_RAUSCHEN}


def _mehrdeutige_woerter(vorhandene_ordner):
    """
    Allerweltswörter der Sammlung: Wörter, die in MEHREREN Ordnernamen vorkommen
    ('Musterstadt' steht in 'Musterstadt, VB Musterbk', 'Landratsamt Musterstadt' UND 'Radiologie ...
    MUSTERSTADT'). Solche Wörter sind kein Alleinstellungsmerkmal eines Ordners - die
    Sammlung selbst verrät so, dass 'Musterstadt' eine Ortschaft ist, ohne dass der Code
    Ortsnamen kennen muss (FALLSTRICKE #50).
    """
    zaehler = Counter()
    for ordner in vorhandene_ordner:
        for wort in _namenswoerter(os.path.basename(ordner)):
            zaehler[wort] += 1
    return {wort for wort, anzahl in zaehler.items() if anzahl >= 2}


@functools.lru_cache(maxsize=8192)
def _ganzes_wort(kern):
    """Muster „kern als ganze Wortfolge“ - einmal übersetzt: bei 600 Ordnern reicht der Muster-Speicher von re (512)
    nicht, dann wurde je Ordner und Absender neu übersetzt (Mail-Import 04.11.2026: 2.000 Gegenüber = 46 s)."""
    return re.compile(r"(?<![\w])" + re.escape(kern) + r"(?![\w])")


def _namen_passen(kern, variante, mehrdeutige=None):
    """
    Passt der Kernname eines Ordners zu einer Absender-Variante? Erlaubte Richtungen:
    der Ordnerkern steht als ganze Wortfolge im Absender ('gentilia' in 'gentilia deutschland
    versicherung ag'), oder der Absender ist der ANFANG des Ordnerkerns ('stadtwerke' ->
    'stadtwerke musterstadt'). Bewusst KEIN beliebiger Teilstring mehr - Praxistest 30.08.2026
    (FALLSTRICKE #36): die Variante 'musterstadt' (Kern eines KI-Ordnernamens 'Musterstadt, Landratsamt')
    traf als Teilstring den Ordner 'Radiologie und Nuklearmedizin Musterstadt', und weil der
    längere Kern gewinnt, landeten Finanzamt- und Landratsamt-Post beim Radiologen.

    Dritte Richtung seit dem Kaltstart-Test 03.09.2026 (Ordner-Wildwuchs): WORT-MENGEN-
    Vergleich, damit vertauschte Reihenfolge ('Mustermann Hermann' = 'Hermann Mustermann') und
    Rechtsform-Zusätze ('Iqua' = 'Iqua Deutschland GmbH', siehe _NAMENS_RAUSCHEN) keinen
    zweiten Ordner mehr erzeugen. NUR Ordnerkern ⊆ Absender - die Gegenrichtung wäre
    wieder #36 ('Musterstadt' ⊆ 'Radiologie ... Musterstadt'). Und nur, wenn die Ordner-Wörter
    genug Substanz haben (ein Wort ab MIN_ORDNER_MATCH_LAENGE oder mindestens zwei Wörter).

    Seit 04.09.2026 (FALLSTRICKE #50, 'Musterstadt, VB Musterbk'-Magnet): Der Kern muss
    mindestens EIN Wort enthalten, das es nur in diesem einen Ordner gibt (nicht in
    `mehrdeutige`, siehe _mehrdeutige_woerter) - sonst matcht er gar nicht. Ein Ordner
    ohne solches Wort ist nur noch per Alias oder exaktem vollen Namen erreichbar.
    """
    if mehrdeutige:
        kern_woerter = _namenswoerter(kern)
        if kern_woerter and not (kern_woerter - mehrdeutige):
            return False
    if kern == variante:
        return True
    if _ganzes_wort(kern).search(variante):
        return True
    if kern.startswith(variante) and (len(kern) == len(variante) or not kern[len(variante)].isalnum()):
        return True
    kern_woerter = _namenswoerter(kern)
    varianten_woerter = _namenswoerter(variante)
    if kern_woerter and kern_woerter <= varianten_woerter:
        return (len(kern_woerter) >= 2
                or max(len(w) for w in kern_woerter) >= MIN_ORDNER_MATCH_LAENGE)
    # Abgekürzte Wörter im Ordnernamen zählen nicht mit (Betatest 25.10.2026: Ordner 'Bayr.
    # Landesamt f. Statistik', Absender 'Bayerisches Landesamt für Statistik' - 'bayr' und 'f'
    # stehen nie wörtlich im Absender). Die übrigen, ausgeschriebenen Wörter müssen dann
    # aber ALLE da sein, und es müssen mindestens zwei sein - ein einzelnes Wort wie
    # 'Landesamt' wäre zu beliebig.
    volle_woerter = _namenswoerter(" ".join(t for t in kern.split() if not t.endswith(".")))
    if len(volle_woerter) >= 2 and volle_woerter != kern_woerter and volle_woerter <= varianten_woerter:
        return True
    return False


# Kürzel-Ordner wie 'HKV', 'WMV', 'LKM': nur Großbuchstaben (und Ziffern), kürzer als
# MIN_ORDNER_MATCH_LAENGE - für den normalen Vergleich zu kurz, aber als GROSS geschriebenes
# ganzes Wort im Absender ('HKV Versicherung AG', 'WMV-Versicherung AG') unverwechselbar.
_KUERZEL_ORDNER = re.compile(r"^[A-ZÄÖÜ][A-ZÄÖÜ0-9]{1,2}$")


def _kuerzel_im_absender(kern, texte):
    """
    Steht der Kürzel-Ordnerkern (z.B. 'HKV') als ganzes Wort in derselben GROSS-Schreibung in
    einem der Texte? Groß/Klein zählt hier bewusst: 'hkv' in einem Fließtext oder ein 'AG'
    am Namensende sollen nicht treffen. Rechtsform-Kürzel (_NAMENS_RAUSCHEN) nie.
    """
    if not _KUERZEL_ORDNER.match(kern or "") or kern.lower() in _NAMENS_RAUSCHEN:
        return False
    muster = re.compile(r"(?<![^\W_])" + re.escape(kern) + r"(?![^\W_])")
    return any(muster.search(t) for t in texte if t)


def finde_passenden_ordner(absender, vorhandene_ordner, ordnername=None):
    """
    Sucht deterministisch (KEINE KI) einen zum Absender passenden vorhandenen
    Ordner. Ersetzt die frühere KI-Ordnerwahl aus einer mitgeschickten Liste -
    Live-Fund (13.07.2026, siehe FALLSTRICKE): bei >50 Ordner-Kandidaten wählte
    das Modell fast immer den Auffangordner ("_Anderes"), SELBST wenn es den
    Absender ("Gentilia") korrekt erkannt hatte und der passende Ordner
    ("G - H - I - J - K - L\\Gentilia") in der Liste stand - ein "in einer langen
    Liste zuverlässig suchen" ist für das Modell offenbar zu unzuverlässig, ein
    simpler String-Vergleich in Python dagegen nicht.

    Vergleicht den letzten Pfadbestandteil (Firmenname) jedes Ordners
    case-insensitiv gegen den Absender - in BEIDE Richtungen, da mal der Ordner
    kürzer ist als der volle Firmenname im Absender (Ordner "Gentilia" vs.
    Absender "Gentilia Deutschland Versicherung AG") und mal umgekehrt (Absender
    "Stadtwerke" vs. Ordner "Stadtwerke Musterstadt"). Bei mehreren Treffern gewinnt
    der mit dem längeren (spezifischeren) Ordnernamen.

    Verglichen wird seit der Telefonbuch-Form (29.08.2026) der KERN des Ordnernamens
    (kernname: 'Carius, Dr. Emil (Zahnarzt)' -> 'Carius'), nicht der volle dekorierte
    Name - sonst fände 'Zahnarztpraxis Dr. Carius' den eigenen Ordner nie wieder.
    Zusätzlich zum Absender kann der KI-Ordnername als zweite Namensvariante
    mitgegeben werden.

    :return: passender Ordnerpfad oder None (dann schlägt der Aufrufer einen
             NEUEN Ordner vor, siehe baue_entscheidung)
    """
    texte = [v.strip() for v in (absender, ordnername) if v and v.strip()]
    alle_varianten = [v.lower() for v in texte]
    alle_varianten += [kernname(v).lower() for v in list(alle_varianten) if kernname(v)]
    varianten = [v for v in alle_varianten if len(v) >= MIN_ORDNER_MATCH_LAENGE]
    if not alle_varianten:
        return None
    mehrdeutige = _mehrdeutige_woerter(vorhandene_ordner)
    treffer = []
    for ordner in vorhandene_ordner:
        basis = os.path.basename(ordner).lower()
        # Exakter voller Ordnername matcht immer - der einzige namensbasierte Weg in
        # einen Ordner ohne Alleinstellungs-Wort wie 'Musterstadt, VB Musterbk' (FALLSTRICKE #50).
        # Auch für kurze Namen: Absender 'WMV' fand den Ordner 'WMV' sonst nicht (Betatest 25.10.2026).
        if basis in alle_varianten:
            treffer.append(ordner)
            continue
        kern_original = kernname(os.path.basename(ordner))
        kern = kern_original.lower()
        if len(kern) < MIN_ORDNER_MATCH_LAENGE:
            # Zu kurz für den unscharfen Vergleich - ein Kürzel-Ordner ('HKV') trifft aber,
            # wenn er GROSS als ganzes Wort im Absender steht (Betatest 25.10.2026: sonst
            # entstand neben 'HKV' der Ordner 'HKV Versicherung AG', ebenso WMV und LKM).
            if _kuerzel_im_absender(kern_original, texte):
                treffer.append(ordner)
            continue
        if any(_namen_passen(kern, v, mehrdeutige) for v in varianten):
            treffer.append(ordner)
    if not treffer:
        return None
    return max(treffer, key=lambda o: len(kernname(os.path.basename(o))))


MIN_AEHNLICHKEITS_WORT = 5   # kürzere Wörter ('Haus', 'Bank') sagen über die Ähnlichkeit zweier Namen nichts

# Gattungs- und Herkunftswörter: sie BREMSEN eine Neuanlage weiter (die Bremse hielt im Korpus drei Briefe
# 'Bayerischer Versicherungsverband' auf), taugen aber nicht für die VORAUSWAHL des ähnlichen Ordners -
# in einer frischen Sammlung bekam 'Versicherungskasse Musterland' sonst 'HKV Versicherung AG' vorgewählt und
# der Zensus-Brief 'Bayerisches Landesamt für Statistik' die 'Bayerische Landesbrandversicherung'
# (Release-Check v0.9.21, 28.10.2026). In einer gewachsenen Sammlung erkennt _mehrdeutige_woerter sie selbst.
_GATTUNGSWOERTER = {"versicherung", "versicherungen", "bayern", "bayerische", "bayerischer", "bayerisches",
                    "bayrische", "deutsche", "deutscher", "deutsches", "gesellschaft", "service", "services",
                    "gruppe", "zentrale", "zentralstelle"}


def _editierdistanz(a, b, grenze):
    """Levenshtein-Abstand von a und b; bricht ab, sobald er sicher über grenze liegt (dann grenze + 1)."""
    if abs(len(a) - len(b)) > grenze:
        return grenze + 1
    vorher = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        aktuell = [i]
        for j, y in enumerate(b, 1):
            aktuell.append(min(vorher[j] + 1, aktuell[j - 1] + 1, vorher[j - 1] + (x != y)))
        if min(aktuell) > grenze:
            return grenze + 1
        vorher = aktuell
    return vorher[-1]


def _woerter_aehnlich(a, b):
    """
    Wie ähnlich sind zwei Wörter? 3 = gleich, 2 = eines (ab 6 Zeichen) ist der Wortanfang des
    anderen ('elster'/'elsteronline'), 1 = Tippfehler-Abstand bei langen
    Wörtern ('kornmair'/'kornmeier'), 0 = nicht ähnlich.
    """
    if a == b:
        return 3
    if min(len(a), len(b)) >= 6 and (a.startswith(b) or b.startswith(a)):
        return 2   # ab 6 Zeichen: 'stadt' ist auch der Anfang von 'stadtwerke'
    return 1 if min(len(a), len(b)) >= 8 and _editierdistanz(a, b, 2) <= 2 else 0


def finde_aehnlichen_ordner(namen, vorhandene_ordner, ohne_gattungswoerter=False, ortswoerter=()):
    """
    Bremse gegen Doppelordner (Betatest 25.10.2026: 28 neue Ordner, 11 % der Ablagen, z.B.
    'Vivafone Deutschland GmbH' neben 'Vivafone Kabel Deutschland', 'ElsterOnline' neben
    'ELSTER', 'Wasserversorgungsgruppe Oberbeispiel' neben 'WZV Oberbeispiel'). Bevor ein NEUER
    Ordner entsteht, wird geprüft, ob ein vorhandener ihm ähnelt: ein gemeinsames Wort ab
    MIN_AEHNLICHKEITS_WORT Zeichen (auch als Wortanfang oder mit Tippfehler, siehe
    _woerter_aehnlich), das kein Allerweltswort der Sammlung ist (_mehrdeutige_woerter,
    FALLSTRICKE #50). Ähnlich heißt NICHT gleich - der Aufrufer legt dann nicht automatisch
    ab, sondern lässt den Menschen entscheiden (ein Klick, danach lernt der Alias).

    Bei mehreren Kandidaten gewinnt der, dessen Wörter zum größeren ANTEIL passen, danach die
    bessere Wortähnlichkeit: 'ELSTER' (1 von 1 Wort) schlägt 'Bayr. Landesamt f. Statistik'
    (1 von 2) für 'Bayerisches Landesamt für Steuern Zentralstelle ElsterOnline'.

    :param namen: Absender und vorgeschlagener Ordnername
    :param ohne_gattungswoerter: True = _GATTUNGSWOERTER zählen nicht (für die Vorauswahl, nicht für die Bremse)
    :param ortswoerter: zählen mit ohne_gattungswoerter ebenfalls nicht - der Ort des Dokuments laut KI.
        In einer frischen Sammlung bekam sonst jeder '… Musterstadt' den ersten Musterstadt-Ordner ('Bürgerbüro
        Musterstadt') vorgewählt, solange 'Musterstadt' erst in EINEM Ordner stand (Rest von FALLSTRICKE #83;
        Korpus: falsche Vorauswahl 31 -> 17, richtige 12 = 12)
    :return: der ähnlichste vorhandene Ordner oder None
    """
    gattung = (_GATTUNGSWOERTER | set(ortswoerter)) if ohne_gattungswoerter else set()
    eigene = set()
    for name in namen:
        eigene |= {w for w in _namenswoerter(name) if len(w) >= MIN_AEHNLICHKEITS_WORT and w not in gattung}
    if not eigene:
        return None
    mehrdeutige = _mehrdeutige_woerter(vorhandene_ordner) | gattung
    bester, beste_wertung = None, (0, 0)
    for ordner in vorhandene_ordner:
        basis = os.path.basename(ordner)
        if buchstaben_der_gruppe(basis) or _ZIFFERNGRUPPE.match(basis):
            continue   # Buchstabengruppen-Ordner sind keine Absender
        if ohne_gattungswoerter:
            # Klammerzusatz beschreibt nur ('Kehrmann, Fritz (Kaminkehrer)') - für die Vorauswahl
            # zählt er nicht, sonst bekam jeder Kaminkehrer Kehrmann vorgewählt (28.10.2026)
            basis = re.sub(r"\([^)]*\)", " ", basis)
        woerter = {w for w in _namenswoerter(basis)
                   if len(w) >= MIN_AEHNLICHKEITS_WORT and w not in mehrdeutige}
        if not woerter:
            continue
        guete = [max(_woerter_aehnlich(w, e) for e in eigene) for w in woerter]
        treffer = [g for g in guete if g]
        if max(treffer, default=0) < 2:
            # Ein Tippfehler allein reicht nicht: 'Bayerische Landesbrandversicherung' ähnelt
            # sonst 'die Bayrische' - 22 von 48 Vorschlägen im Betatest-Korpus waren so falsch.
            # 'Kornmair Landtechnik' -> 'Kornmeier Landtechnik' bleibt ('landtechnik' exakt).
            continue
        wertung = (len(treffer) / len(woerter), sum(treffer))
        if wertung > beste_wertung:
            bester, beste_wertung = ordner, wertung
    return bester


_NUR_ADRESSE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def ordnername_aus_adresse(name):
    """Steht im Mailkopf nur eine Adresse, wird die Domain zum Ordnernamen (info@mail.firma.de -> firma.de; echter
    Lauf 05.11.2026: 51 von 170 Mails hatten keinen Namen, 2 Ordner hießen wie die Adresse). Bei Mail-Anbietern sagt
    die Domain nichts über das Gegenüber, dann bleibt die Adresse. Alles andere bleibt unverändert."""
    if not _NUR_ADRESSE.match(name or ""):
        return name
    domain = mail_lesen.domain_schluessel(name)[1:]
    return name if domain.split(".")[-2] in mail_lesen.ANBIETER else domain


def _vergleichsname(name):
    """Womit eine bloße Adresse mit vorhandenen Ordnern verglichen wird: nur dem Domainnamen (online@firma.de -> firma).
    Der vordere Teil ist bei Firmen meist ein Funktionswort, „online“ traf sonst „… ONLINESHOP“ und „service“ jeden
    Service-Ordner, die Endung ebenso (FALLSTRICKE #107). Bei Mail-Anbietern bleibt die Adresse: Dort steht vorn oft der
    Name der Person. Alles andere bleibt unverändert."""
    if not _NUR_ADRESSE.match(name or ""):
        return name
    domain = ordnername_aus_adresse(name)
    return name if domain == name else domain.split(".")[0]


_HINWEIS_TRENNER = re.compile(r"[\s_\-.,;()\[\]]+")


def finde_ordner_ueber_hinweise(tags, pdf_path, vorhandene_ordner):
    """
    Rückfall, wenn die KI KEINEN Absender liefert (Live-Fund 30.08.2026: ein SEPA-
    Lastschriftmandat der HKV hat formal keinen Absender - Tag 'HKV', Dateiname
    '20220308_HKV.pdf' und ein Ordner 'HKV' waren trotzdem da). Tags und die
    Wortbestandteile des Dateinamens werden gegen die Kernnamen der vorhandenen
    Ordner geprüft - bewusst nur EXAKT (Groß/Klein egal), nie als Teilstring, darum
    gilt hier auch keine Mindestlänge. Genau ein Ordner-Treffer zählt; keiner oder
    mehrere → None (dann bleibt es bei 'Unsicher'). Neue Ordner entstehen daraus nie.

    :return: (relativer Ordnerpfad, Quelle 'Tag' oder 'Dateiname') oder (None, None)
    """
    hinweise = [(t, "Tag") for t in tags or ()]
    stamm = os.path.splitext(os.path.basename(pdf_path or ""))[0]
    hinweise += [(w, "Dateiname") for w in _HINWEIS_TRENNER.split(stamm) if w and not w.isdigit()]
    # Allerweltswörter der Sammlung taugen nicht als Hinweis (FALLSTRICKE #50): das
    # Tag/Dateinamen-Wort 'Musterstadt' würde sonst exakt auf den Kern von 'Musterstadt, VB
    # Musterbk' treffen und jeden absenderlosen Musterstadt-Beleg zur Bank sortieren.
    mehrdeutige = _mehrdeutige_woerter(vorhandene_ordner)
    treffer = {}
    for hinweis, quelle in hinweise:
        gesucht = hinweis.strip().lower()
        if not gesucht or gesucht in mehrdeutige:
            continue
        for ordner in vorhandene_ordner:
            basis = os.path.basename(ordner)
            if gesucht in (basis.lower(), kernname(basis).lower()):
                treffer.setdefault(ordner, quelle)
    if len(treffer) == 1:
        return next(iter(treffer.items()))
    return None, None


def finde_posteingaenge(master_folder):
    """
    ALLE Posteingang-Ordner der Sammlung (direkte Unterordner, deren Name
    'posteingang' enthält - '0_Posteingang', '00_Posteingang', '_Posteingang' usw.).
    Praxistest 31.08.2026 beim Betatest: es existierten '00_Posteingang' UND
    '0_Posteingang' - der Scanner schrieb in den einen, die Vollautomatik las nur den
    anderen, das Dokument blieb liegen (FALLSTRICKE #40). Darum liefert diese Funktion
    alle Treffer, und die Verarbeitung leert JEDEN davon.
    :return: Liste absoluter Pfade, der Standardname (POSTEINGANG_ORDNER) zuerst
    """
    treffer = []
    try:
        # scandir als Kontextmanager, damit der Verzeichnis-Handle sicher zugeht
        # (vgl. FALLSTRICKE #27 zu offenen Handles unter Windows).
        with os.scandir(master_folder) as eintraege:
            for entry in eintraege:
                if entry.is_dir() and "posteingang" in entry.name.lower():
                    treffer.append(entry.path)
    except OSError:
        return []
    return sorted(treffer, key=lambda pfad: (
        os.path.basename(pfad).lower() != POSTEINGANG_ORDNER.lower(), pfad.lower()))


def finde_posteingang(master_folder):
    """Der bevorzugte Posteingang (Standardname zuerst) oder None - siehe finde_posteingaenge."""
    alle = finde_posteingaenge(master_folder)
    return alle[0] if alle else None


def sammle_posteingang_dokumente(master_folder):
    """
    Alle PDFs, die im Posteingang der Sammlung auf Verarbeitung warten (sortiert
    nach Dateiname) - die Arbeitsliste des Posteingang-Batches (Schritt 3 des
    Seniorenmodus). Bewusst NICHT rekursiv: der Posteingang ist ein flacher
    Ablageort, in den der Scanner schreibt; Unterordner darin wären eine
    Nutzer-Absicht, die die Automatik nicht überfahren soll.

    :return: Liste absoluter Pfade (leer, wenn kein Posteingang existiert oder alle leer sind).
             Existieren mehrere Posteingang-Ordner, werden ALLE geleert (FALLSTRICKE #40).
    """
    dateien = []
    for posteingang in finde_posteingaenge(master_folder):
        try:
            with os.scandir(posteingang) as eintraege:
                dateien += [e.path for e in eintraege
                            if e.is_file() and e.name.lower().endswith(".pdf") and not e.name.startswith(".")]
        except OSError:
            continue
    return sorted(dateien)


def sammle_ordnerliste(master_folder):
    """
    Alle Ablage-Zielordner der Sammlung als relative Pfade (sortiert) - das ist die
    Auswahlliste für die KI. Ausgeschlossen: der Hauptordner selbst, versteckte
    Ordner, der Papierkorb/Daten-Bereich sowie Posteingang/Unsicher (dorthin wird
    nie aktiv "einsortiert").
    """
    ordner = []
    for dirpath, dirnames, _filenames in os.walk(master_folder):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".")
            and "posteingang" not in d.lower()
            and d.lower() != UNSICHER_ORDNER.lower()
            and d.lower() != SAMMEL_ORDNER.lower()   # sonst schickten Gedächtnis und Namensvergleich mehr dorthin
            and not app_paths.is_trash_path(os.path.join(dirpath, d), master_folder)
        ]
        for d in dirnames:
            ordner.append(os.path.relpath(os.path.join(dirpath, d), master_folder))
    return sorted(ordner)
