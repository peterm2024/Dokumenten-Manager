"""
Entscheidungslogik der Vollautomatik (Seniorenmodus, siehe KONZEPT_SENIORENMODUS.md).

Grundprinzip: Die KI (ollama_client.suggest_filing) macht VORSCHLÄGE - ob ein
Dokument wirklich automatisch abgelegt werden darf ("sicher"), entscheidet
ausschließlich der deterministische, testbare Code hier. Bei jedem Zweifel wird
das Dokument als "unsicher" markiert und wandert später in den Unsicher-Ordner,
statt falsch einsortiert zu werden.

Schritt 1 (Analyse) ist reine Entscheidungslogik ohne Dateizugriffe. Schritt 2
(fuehre_entscheidung_aus) führt die geprüfte Entscheidung tatsächlich aus -
Metadaten/Umbenennen/Verschieben -, delegiert das eigentliche Verschieben aber
an einen von außen übergebenen Callable, um von Tkinter/der App unabhängig zu
bleiben (siehe dortige Docstring).
"""

import os
import functools
import re
from collections import Counter
from datetime import datetime

import app_paths
import mail_lesen
import ollama_client
import ordner_aliase
import scan_date
import spell_correct
from pdf_handler import PDFHandler
from personen_namen import (MIN_TAGLAENGE_FUZZY, ZUSTELLVERMERKE, editierdistanz_max1, finde_personen_schreibweise, ist_personenname,
                            ohne_anschrift, ohne_eigene_namen, tausche_namensform, teile_empfaenger)

# Ordnernamen für neue Sammlungen (Ziffern-Präfix sortiert in JEDER Ansicht vor
# Buchstaben, siehe KONZEPT_SENIORENMODUS.md); bestehende Sammlungen werden über
# finde_posteingang() flexibel erkannt (z.B. "00_Posteingang" beim Entwickler).
POSTEINGANG_ORDNER = "0_Posteingang"
UNSICHER_ORDNER = "0_Unsicher"
# Sammelablage einzelner Mails (E17, Peter 06.11.2026): je Buchstabengruppe einer, nie Ziel für etwas anderes
SAMMEL_ORDNER = "Einzelne Mails"

# Windows-verbotene Dateinamen-Zeichen (gleiche Menge wie file_operations.rename_file)
_VERBOTENE_ZEICHEN = re.compile(r'[\\/:*?"<>|]')
_DATUM_FORMAT = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Schreibweisen, die KI und Nutzer trotz "JJJJ-MM-TT"-Vorgabe liefern (Praxistest 30.08.2026:
# '20.07.2026' von der KI -> Zeile unsicher, und die Nutzer-Korrektur lehnte dieselbe deutsche
# Form ab): deutsch TT.MM.JJJJ, ISO mit Punkt/Schrägstrich, zweistelliges Jahr.
_DATUM_DEUTSCH = re.compile(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})$")
_DATUM_ISO_LOCKER = re.compile(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})$")
MAX_TITEL_LAENGE = 80

# Kürzere Ordnernamen werden nie als Absender-Treffer gewertet (Fehlalarm-Schutz,
# siehe finde_passenden_ordner) - unter dieser Länge wären Teilstring-Treffer zu
# beliebig (z.B. ein zweibuchstabiger Ordner, der zufällig überall vorkommt).
MIN_ORDNER_MATCH_LAENGE = 4

# Ab dieser Länge wird ein Name zum NEUEN Ordner (Peter 05.11.2026: kurze Firmennamen sind häufig). Der Vergleich mit
# vorhandenen Ordnern bleibt bei MIN_ORDNER_MATCH_LAENGE, sonst passte 'Eis' auch auf 'Eisenwaren'.
MIN_NEUER_ORDNER = 3

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
    """Erster Buchstabe des Kernnamens, Umlaute aufgelöst (Ä -> A); Ziffer -> '0-9'; '' wenn unbestimmbar."""
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


def _verschiedene_absender(name, ordner):
    """
    Teilen ein neuer Name und ein vorhandener Ordner genau ein Wort, und hat jeder noch eigene Wörter, sind es
    verschiedene Absender: 'MVZ Musterstadt' neben 'Bürgerbüro Musterstadt'. Echter Mail-Lauf 05.11.2026: 11 von 17
    PDFs in 0_Unsicher waren solche Fälle; Korpus: 52 Dokumente mehr ohne Rückfrage, 17 falsche Vorauswahlen weg,
    dafür 6 Doppelordner mehr ('Zweckverband Musterdorf' neben 'WZV Musterdorf'). Ein Doppelordner ist sichtbar und
    schnell behoben. Steckt ein Name ganz im anderen, bleibt es ähnlich ('Vivafone' / 'Vivafone Kabel').
    """
    eigene = _namenswoerter(name)
    fremde = _namenswoerter(re.sub(r"\([^)]*\)", " ", os.path.basename(ordner)))
    gleiche_eigene = {w for w in eigene if any(_woerter_aehnlich(w, f) for f in fremde)}
    gleiche_fremde = {f for f in fremde if any(_woerter_aehnlich(w, f) for w in eigene)}
    return len(gleiche_fremde) == 1 and bool(eigene - gleiche_eigene) and bool(fremde - gleiche_fremde)


def _aehnlicher_ordner(namen, vorhandene_ordner, **optionen):
    """finde_aehnlichen_ordner ohne Ordner, die laut _verschiedene_absender zu jemand anderem gehören.
    :param namen: Absender und vorgeschlagener Ordnername (der steht zuletzt und wird verglichen)"""
    treffer = finde_aehnlichen_ordner(namen, vorhandene_ordner, **optionen)
    return None if treffer and _verschiedene_absender(namen[-1], treffer) else treffer


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
    Zweistellige Jahre: 00-49 -> 20xx, 50-99 -> 19xx. Liefert den Text unverändert
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
            jahr = ("20" if int(jahr) < 50 else "19") + jahr
    return f"{int(jahr):04d}-{int(monat):02d}-{int(tag):02d}"


def _datum_ist_plausibel(datum):
    """JJJJ-MM-TT, echtes Kalenderdatum, nicht in der Zukunft und nicht älter als 1950."""
    if not _DATUM_FORMAT.match(datum or ""):
        return False
    try:
        wert = datetime.strptime(datum, "%Y-%m-%d")
    except ValueError:
        return False
    return 1950 <= wert.year and wert.date() <= datetime.now().date()


# Katalog-Kategorie, unter der Empfänger-Namen als Tags landen (Nutzerwunsch 30.08.2026:
# "bekannte Namen und Adressen als Tags" - Teil der ausgelieferten tags_default.json).
KATEGORIE_PERSONEN = "Personen"
KATEGORIE_OBJEKTE = "Objekte & Adressen"

# Wie diese beiden Kategorien in einem GEWACHSENEN Katalog heissen koennen (Praxisfund
# 01.09.2026: die reale Sammlung hatte "Wohnen & Immobilien / Adressen" statt des
# ausgelieferten "Objekte & Adressen"). Reihenfolge = Suchreihenfolge.
KATEGORIE_VARIANTEN = {
    KATEGORIE_PERSONEN: ("Personen", "Person", "Namen"),
    KATEGORIE_OBJEKTE: ("Objekte & Adressen", "Adressen", "Objekte", "Adresse",
                        "Objekte und Adressen", "Immobilien"),
}


def korrigiere_tag(tag, known_tags=None, vocabulary=None):
    """
    Rechtschreib-Schutz für KI-Tags (Nutzerfund 30.08.2026: 'Mustereheim' landete neben
    'Musterheim' im Katalog). 1. Steht ein Katalog-Tag in Editierdistanz <= 1, gewinnt dessen
    Schreibweise (nur ab MIN_TAGLAENGE_FUZZY Zeichen). 2. Sonst Wort für Wort gegen den
    Sammlungs-Wortschatz wie bei Titeln (korrigiere_titel / correct_proper_noun).
    Personen-Tags aus dem Empfänger durchlaufen das bewusst NICHT - 'Maier' und 'Meier'
    sind zwei Menschen.
    """
    tag = (tag or "").strip()
    if not tag:
        return tag
    if known_tags and len(tag) >= MIN_TAGLAENGE_FUZZY:
        kandidaten = [k for k in known_tags
                      if k and abs(len(k) - len(tag)) <= 1 and editierdistanz_max1(tag.lower(), k.lower())]
        if kandidaten:
            kandidaten.sort(key=lambda k: k.lower() != tag.lower())  # exakte Schreibweise zuerst
            return kandidaten[0]
    if vocabulary:
        tag, _korrekturen = korrigiere_titel(tag, vocabulary)
    return tag


def tags_mit_empfaenger(ki_antwort, ignorierte=None, known_tags=None, vocabulary=None, kategorien=None):
    """
    Tags der KI-Antwort plus Empfänger als Personen-Tag (Nutzerwunsch 30.08.2026: die
    angesprochene Person wird eigenes Tag unter der Kategorie "Personen" - so
    unterscheidet die Dubletten-Erkennung den gleichen Serienbrief an beide Ehepartner).
    Ein fehlender Empfänger ist KEIN Fehler - viele Dokumente haben schlicht keinen.
    :param ignorierte: kleingeschriebene Tags der Ignorierliste (tag_ignorierliste.lade) -
                       werden kommentarlos herausgefiltert, auch als Empfänger
    :param known_tags/vocabulary: für den Rechtschreib-Schutz der Sach-Tags (korrigiere_tag)
    :return: (tags, tag_kategorien)
    """
    ignorierte = ignorierte or ()
    tag_kategorien = ki_antwort.get("tag_kategorien")
    tag_kategorien = dict(tag_kategorien) if isinstance(tag_kategorien, dict) else {}
    tags = []
    katalog_namen = list(known_tags or ()) + [k for k in (kategorien or ()) if isinstance(k, str)]
    # Welche KI-Tags hat die KI selbst als Person bzw. Objekt eingestuft? Die laufen über
    # dieselben Wege wie Empfänger und Objekt-Feld (Wiederholungslauf 08.09.2026: '12345
    # Musterstadt', 'Hermann Mustermann Peter Mustermann' und 'Kunden der iqua Deutschland GmbH' kamen als
    # KI-Tag mit Kategorie 'Personen' an allen Personen-Regeln vorbei in den Katalog).
    varianten_personen = {v.lower() for v in KATEGORIE_VARIANTEN[KATEGORIE_PERSONEN]}
    varianten_objekte = {v.lower() for v in KATEGORIE_VARIANTEN[KATEGORIE_OBJEKTE]}
    ki_kategorie = {str(k).strip().lower(): str(v).strip().lower() for k, v in tag_kategorien.items()}
    personen_roh = []
    objekte_roh = []
    for roh in ki_antwort.get("tags", []):
        # Komma ist das Trennzeichen des PDF-Schlagwortfelds - ein Tag mit Komma zerfiele
        # beim nächsten Speichern ohnehin in seine Teile (FALLSTRICKE #38): hier sauber trennen.
        kategorie = ki_kategorie.get(str(roh or "").strip().lower(), "")
        if kategorie not in varianten_personen and _SAMMEL_HAUSNUMMERN.search(str(roh or "")):
            # "Zum alten Fass 1 u. 3" ohne Kategorie (steht so im Katalog, Betatest 27.10.2026):
            # mehrere Hausnummern = mehrere Objekte, zerlegt wie das Objekt-Feld (teile_objekte)
            objekte_roh.append(str(roh))
            continue
        # Schrägstrich trennt zwei Dinge ("Musterstadt / Musterheim", "Heizung/Lüftung") - je ein Tag
        for teil in re.split(r"[,/]", str(roh or "")):
            if kategorie in varianten_personen:
                personen_roh.append(teil)
                continue
            if kategorie in varianten_objekte:
                objekte_roh.append(teil)
                continue
            if re.search(r"\d", teil) and finde_objekt_schreibweise(teil, katalog_namen) is not None:
                # Bekannte Adresse ohne Kategorie ("Zum Alten Fass Nr.1", Test T13.9 27.10.2026):
                # als Objekt einrasten - sonst verwirft die Ziffern-Regel sie als neues Sach-Tag
                objekte_roh.append(teil)
                continue
            teil = korrigiere_tag(teil, known_tags, vocabulary)
            if teil and teil.lower() not in ignorierte and teil.lower() not in {t.lower() for t in tags}:
                tags.append(teil)

    def person_tag(person):
        if "," in person:
            person = tausche_namensform(person)
        # Angeklebte Anschrift weg ('Hermann Mustermann Weidenstr. 8'); bleibt nichts übrig,
        # war es gar keine Person ('Weidenstraße 8' als Empfänger). Was danach noch
        # Ziffern, Rechtsform oder Sammelanrede trägt, ist ebenfalls keine Person.
        person = ohne_anschrift(person)
        if not person or not ist_personenname(person):
            return
        # Schreibvarianten auf die Katalog-Form schnappen (Namensdreher, Tippfehler im
        # Vornamen, Wortmenge, eindeutiger Nachname) - siehe finde_personen_schreibweise.
        bekannt = finde_personen_schreibweise(person, katalog_namen)
        if bekannt is not None:
            person = bekannt
        if person.lower() not in ignorierte and person.lower() not in {t.lower() for t in tags}:
            tags.append(person)
            tag_kategorien.setdefault(person, KATEGORIE_PERSONEN)

    # Mehrere angesprochene Personen ('Hermann Mustermann und Werner Mustermann') werden zu je
    # einem eigenen Personen-Tag - siehe teile_empfaenger. Eine einzelne Person in
    # Telefonbuch-Form ('Mustermann, Uta') wird kommalos: 'Uta Mustermann'.
    for quelle in [ki_antwort.get("empfaenger")] + personen_roh:
        for person in teile_empfaenger(quelle):
            person_tag(person)
# Objekt/Ort als eigenes Tag unter "Objekte & Adressen" - dasselbe Muster wie beim
    # Empfänger (Nutzerfund 01.09.2026: Ortsangaben wie "Musterheim" wurden praktisch nie
    # vergeben, weil sie im 5er-Budget der allgemeinen Schlagworte untergingen). Genau
    # diese Kategorie braucht die Dubletten-Erkennung, um denselben Bescheid für zwei
    # verschiedene Grundstücke auseinanderzuhalten.
    kategorie_objekt = _kategorie_name(KATEGORIE_OBJEKTE, kategorien)
    objekt_normen = set()

    def objekt_tag(objekt):
        # Schreibvarianten auf die Katalog-Schreibweise schnappen (Kaltstart-Test
        # 03.09.2026: dieselbe Adresse stand sonst in einem Dutzend Formen im Katalog).
        # Gegen ALLE Katalog-Namen - Peters Adressen sind graue Struktur-Knoten, die
        # in known_tags fehlen (Neu-Einlese-Lauf 07.09.2026: 'Weidenstr. 8 Whg Nr. 2'
        # stand deshalb neben dem grauen 'Weidenstr. 8 Whg 2').
        objekt = ohne_plz(objekt)
        if not objekt or _NUR_PLZ.match(objekt) or not ist_objektbezeichnung(objekt):
            return
        bekannt = finde_objekt_schreibweise(objekt, katalog_namen)
        if bekannt is not None:
            objekt = bekannt
        norm = normiere_objekt(objekt)
        if (objekt.lower() not in ignorierte and norm not in objekt_normen
                and objekt.lower() not in {t.lower() for t in tags}):
            objekt_normen.add(norm)
            tags.append(objekt)
            tag_kategorien.setdefault(objekt, kategorie_objekt)

    objekte = teile_objekte(ki_antwort.get("objekt"))
    for roh in objekte_roh:
        objekte += [o for o in teile_objekte(roh) if o.lower() not in {x.lower() for x in objekte}]
    ki_ort = ohne_plz(str(ki_antwort.get("ort") or ""))
    orte = []
    for objekt in objekte:
        objekt, ort = trenne_ort(objekt, ki_ort)
        if ort and ort.lower() not in {o.lower() for o in orte}:
            orte.append(ort)
        if len(objekt) >= MIN_OBJEKTLAENGE:
            objekt_tag(objekt)
    # Der Ort zählt nur, wenn es auch ein Objekt gibt - eine Ortsangabe OHNE Objekt ist
    # meist die Stadt aus dem Anschriftenfeld, die würde sonst an fast jedem Brief kleben.
    if objekte:
        for ort in orte:
            for teil in teile_objekte(ort):  # "Musterstadt / Musterheim" -> zwei Orts-Tags
                objekt_tag(teil)
    return tags, tag_kategorien


def ergaenze_oberkategorien(tags, tag_eltern, ignorierte=None):
    """
    Auto-Hierarchie wie beim manuellen Tag-Klick (tag_manager.toggle_tag): Zu jedem
    vergebenen Katalog-Tag kommen seine zuweisbaren Oberkategorien aus dem Tag-Baum
    dazu (Nutzerwunsch 04.09.2026: Wer 'Gebäudebrandversicherung' vergibt, sucht
    später mit dem Tag 'Versicherung' - das Dokument muss beide tragen). Die
    Oberkategorie steht dabei VOR ihrem Unter-Tag; die Ignorierliste gilt auch hier.

    :param tag_eltern: {tag (klein): [Oberkategorien von oben nach unten]} -
                       tag_manager.get_tag_eltern(); None/leer = Tags unverändert
    :param ignorierte: kleingeschriebene Tags der Ignorierliste (tag_ignorierliste.lade)
    """
    if not tag_eltern:
        return list(tags)
    ignorierte = ignorierte or ()
    ergebnis = []
    vorhanden = {t.lower() for t in tags}
    for tag in tags:
        for eltern in tag_eltern.get(tag.lower(), ()):
            if eltern.lower() not in vorhanden and eltern.lower() not in ignorierte:
                ergebnis.append(eltern)
                vorhanden.add(eltern.lower())
        ergebnis.append(tag)
    return ergebnis


def ersetze_synonyme(tags, synonyme):
    """
    Synonym-Knoten des Katalogs anwenden (Nutzeridee 08.09.2026, Gegenstück zu den
    Ordner-Aliasen): steht ein KI-Tag als Synonym im Katalog, bekommt das Dokument
    stattdessen das Tag, für das es steht ('Haftpflichtversicherung' -> 'Haftpflicht');
    der Synonym-Text selbst kommt nie ins Dokument und nie in den Katalog. Reihenfolge
    bleibt, Doppelte fallen weg (zwei Synonyme desselben Tags ergeben es einmal).
    :param synonyme: {synonym (klein): Ziel-Tag} - tag_manager.get_synonyme(); None/leer = aus
    :return: (tags, ersetzungen [(alt, neu)]) - die Ersetzungen zeigt die Ablage-Vorschau
    """
    if not isinstance(synonyme, dict) or not synonyme:
        return list(tags), []
    ergebnis = []
    ersetzungen = []
    vorhanden = set()
    for tag in tags:
        ziel = synonyme.get(tag.strip().lower())
        if ziel:
            ersetzungen.append((tag, ziel))
            tag = ziel
        if tag.lower() not in vorhanden:
            vorhanden.add(tag.lower())
            ergebnis.append(tag)
    return ergebnis, ersetzungen


# "u." / "and" / "+" / "&" trennen seit dem Betatest 27.10.2026 ebenfalls: "Zum Alten Fass 1 u. 3"
# und "Weidenstr. 8 Whg 2 and 4" waren je EIN Tag - die Suche nach Hausnummer 3 fand sie nicht.
_OBJEKT_TRENNER = re.compile(r"\s+und\s+|\s+u\.\s*|\s+and\s+|\s*\+\s*|\s*&\s*|[,;/]|\s+sowie\s+",
                             re.IGNORECASE)
_NUR_PLZ = re.compile(r"^\d{4,5}$")
_PLZ_PRAEFIX = re.compile(r"^\d{4,5}\s+(?=\D)")
MIN_OBJEKTLAENGE = 3
# Teil einer Sammelangabe, der nur aus der Nummer besteht ("3" aus "Zum Alten Fass 1 u. 3")
_NUR_HAUSNUMMER = re.compile(r"^\d{1,3}\s*[a-zA-Z]?$")
_HAUSNUMMER_AM_ENDE = re.compile(r"^(?P<basis>.*\D)\d{1,3}\s*[a-zA-Z]?$")
_HAUSNUMMER_MIT_ORT = re.compile(r"^(?P<nummer>\d{1,3})\s+(?P<ort>[A-ZÄÖÜ][^\W\d_]+(?:[ -][A-ZÄÖÜ][^\W\d_]+)*)$")
# Zwei Nummern mit Verbinder dazwischen: eine Sammelangabe mehrerer Objekte
_SAMMEL_HAUSNUMMERN = re.compile(r"\d\s*[a-zA-Z]?\s*(?:\bu\.|\bund\b|\band\b|\+|&)\s*\d", re.IGNORECASE)
# Ein Objekt braucht ein Wort aus mindestens drei Buchstaben - "Nr. 3", "75m", "14m x 1" sind Bruchstücke
_OBJEKT_WORT = re.compile(r"[^\W\d_]{3,}")


def ist_objektbezeichnung(text):
    """True, wenn der Text als Objekt-Tag taugt: kein reines Bruchstück wie 'Nr. 3' oder '75m'."""
    return bool(_OBJEKT_WORT.search(text or ""))


def ohne_plz(text):
    """
    Vorangestellte Postleitzahl weg: '12345 Musterstadt' -> 'Musterstadt'. Die PLZ sagt nichts,
    was der Ort nicht sagt, und erzeugte im Neu-Einlese-Lauf 07.09.2026 die Objekt-Tags
    '12345' (nach trenne_ort blieb sie allein übrig) und '12345 Musterstadt'.
    """
    return _PLZ_PRAEFIX.sub("", (text or "").strip()).strip()


# "Weidenstr. 8 in Musterstadt": angeklebter Ortsname hinter " in ", großgeschrieben
_ORT_SUFFIX = re.compile(r"^(?P<basis>.*\S)\s+in\s+(?P<ort>[A-ZÄÖÜ][\wäöüß.-]*)$")


def trenne_ort(objekt, ort=""):
    """
    Trennt einen angeklebten Ortsnamen vom Objekt ab (Nutzer-Entscheidung 03.09.2026:
    Ort und Objekt sind GETRENNTE Tags - im Alltag wird meist nur zwischen den
    Ortschaften unterschieden, die genaue Adresse ist die zweite, feinere Ebene;
    zusammengeklebt wäre "Weidenstr. 8 Musterstadt" außerdem ein neues Schreibvarianten-Tag
    neben "Weidenstr. 8", siehe FALLSTRICKE #48).
    :param ort: der von der KI getrennt gemeldete Ort (darf leer sein)
    :return: (objekt_ohne_ort, ort) - ort auch dann, wenn er nur per " in ..." im Objekt klebte
    """
    objekt = (objekt or "").strip()
    ort = (ort or "").strip()
    m = _ORT_SUFFIX.match(objekt)
    if m and (not ort or m.group("ort").lower() == ort.lower()):
        return m.group("basis").strip(" ,-"), (ort or m.group("ort"))
    if ort and objekt.lower() != ort.lower() and objekt.lower().endswith(" " + ort.lower()):
        return objekt[:-len(ort)].strip(" ,-"), ort
    return objekt, ort


def objekte_ohne_ort(ki_antwort, known_tags=None, kategorien=None):
    """Bereinigte Objekt-Bezeichnungen der KI-Antwort (ohne Ortsnamen), in Katalog-Schreibweise."""
    ki_ort = str(ki_antwort.get("ort") or "").strip()
    katalog_namen = list(known_tags or ()) + [k for k in (kategorien or ()) if isinstance(k, str)]
    ergebnis = []
    for roh in teile_objekte(ki_antwort.get("objekt")):
        basis, _ = trenne_ort(roh, ki_ort)
        basis = ohne_plz(basis)
        if len(basis) >= MIN_OBJEKTLAENGE and not _NUR_PLZ.match(basis) and ist_objektbezeichnung(basis):
            basis = finde_objekt_schreibweise(basis, katalog_namen) or basis
            if basis.lower() not in {e.lower() for e in ergebnis}:
                ergebnis.append(basis)
    return ergebnis


def titel_mit_objekt(titel, objekte):
    """
    Hängt die Objekt-Bezeichnung an den Titel an, wenn sie dort nicht schon steht -
    Nutzerwunsch 03.09.2026: sechsmal 'Beitragsrechnung Gebäudeversicherung' im selben
    Ordner ist nicht unterscheidbar, MIT Objekt schon ('... Gebäudeversicherung
    Weidenstr. 8'); der Titel wird auch der Dateiname. Der Ort bleibt bewusst draußen
    (objekte_ohne_ort). Verglichen wird über die Normalform, damit 'Weidenstraße 8'
    im Titel das Anhängen von 'Weidenstr. 8' verhindert. Ein leerer Titel bleibt leer -
    die Entscheidung ist dann ohnehin 'unsicher'.
    """
    titel = (titel or "").strip()
    if not titel:
        return titel
    for objekt in objekte:
        if normiere_objekt(objekt) not in normiere_objekt(titel):
            titel = f"{titel} {objekt}"
    return titel


def normiere_objekt(text):
    """
    Vergleichsform einer Objekt-/Adressangabe: Schreibvarianten fallen zusammen, Haus-
    und Wohnungsnummern bleiben unterscheidend. Kaltstart-Test 03.09.2026: die KI
    transkribiert wörtlich, was auf dem Brief steht - dieselbe Adresse stand danach in
    einem Dutzend Formen im Katalog ("Zum Alten Fass 1 u. 3 Musterheim" auch mit
    Bindestrichen, "1+3", "u.3", "Schloß"; "Weidenstr. 8" auch als "Weidenstraße 8" und
    mit "Whg.Nr."/"Wgh."-Tippfehler). Verglichen wird deshalb über diese Normalform:
    - klein, ß→ss, Umlaute entschärft, Bindestriche/Punkte/Schrägstriche → Leerraum
    - "...str"-Endung → "...strasse"; wohnung/whg/wgh (Tippfehler) → whg; "nr" und "in" entfallen
    - Zahlverbinder "u"/"und"/"+" → "+" ohne Leerraum ("1 u. 3" == "1+3")
    """
    t = (text or "").lower()
    for alt, neu in (("ß", "ss"), ("ä", "ae"), ("ö", "oe"), ("ü", "ue")):
        t = t.replace(alt, neu)
    t = re.sub(r"[-./]", " ", t)
    t = re.sub(r"str\b", "strasse", t)
    t = re.sub(r"\b(?:wohnung|whg|wgh)\b", "whg", t)
    t = re.sub(r"\bnr\b|\bnr(?=\d)|\bin\b", " ", t)  # "Nr1" (Betatest 27.10.2026) wie "Nr. 1"
    t = re.sub(r"\b(?:u|und)\b", "+", t)
    t = re.sub(r"\s*\+\s*", "+", t)
    return " ".join(t.split())


def finde_objekt_schreibweise(objekt, known_tags):
    """Liefert die Katalog-Schreibweise, wenn ein bekanntes Tag dieselbe Normalform hat - sonst None."""
    gesucht = normiere_objekt(objekt)
    if not gesucht:
        return None
    for bekannt in known_tags or ():
        if normiere_objekt(bekannt) == gesucht:
            return str(bekannt)
    return None


def teile_objekte(roh):
    """
    Zerlegt die Objekt-Angabe der KI in einzelne, garantiert KOMMAFREIE Tags.

    Bewusst nicht teile_empfaenger: das ist auf Personennamen zugeschnitten (Nachnamens-
    Ergänzung, Katalog-Abdeckung) und ließ im Live-Test 01.09.2026 „Weidenstr. 8, Wgh.Nr.5"
    als EIN Tag mit Komma stehen - ein Tag mit Komma überlebt den Rundlauf durchs
    PDF-Schlagwortfeld nicht (FALLSTRICKE #38). Hier zählt jedes Trennzeichen.
    Reine Postleitzahlen fliegen raus, sie sagen nichts, was der Ort nicht sagt.

    Sammelangaben werden zu Einzel-Objekten (Peter 27.10.2026: ein Objekt je Tag):
    "Zum Alten Fass 1 u. 3" -> "Zum Alten Fass 1", "Zum Alten Fass 3" - die nackte
    Nummer bekommt die Straße (bzw. "Weidenstr. 8 Whg ") des Teils davor.
    """
    # Zustellvermerke wie "c/o" vorab neutralisieren (siehe ZUSTELLVERMERKE) -
    # Anreden gibt es in Objekt-Angaben nicht, deshalb nur diese eine Stufe.
    text = ZUSTELLVERMERKE.sub(";", roh or "").strip()
    if not text:
        return []
    ergebnis = []
    basis = ""
    for teil in _OBJEKT_TRENNER.split(text):
        teil = " ".join((teil or "").split()).strip(" .-")
        teile = [teil]
        ort_dahinter = _HAUSNUMMER_MIT_ORT.match(teil)
        if ort_dahinter and basis:
            # "1 u. 3 Musterheim": der Ort klebt an der letzten Nummer - eigenes Objekt (Orts-Tag)
            teile = [basis + ort_dahinter.group("nummer"), ort_dahinter.group("ort")]
        elif _NUR_HAUSNUMMER.match(teil) and basis:
            teile = [basis + teil]
        else:
            treffer = _HAUSNUMMER_AM_ENDE.match(teil)
            basis = treffer.group("basis") if treffer else ""
        for teil in teile:
            if (len(teil) >= MIN_OBJEKTLAENGE and not _NUR_PLZ.match(teil)
                    and teil.lower() not in {x.lower() for x in ergebnis}):
                ergebnis.append(teil)
    return ergebnis


def ohne_zielordner_tags(tags, zielordner, ordnername=""):
    """
    Entfernt Tags, die nichts sagen, was die Ablage nicht schon sagt.

    Verglichen wird auf GLEICHHEIT, nie als Teilstring — „Musterstadt" überlebt also neben
    dem Ordner „Finanzamt Musterstadt", weil es als Ortsangabe eine eigene Information ist.
    Geprüft werden der letzte Pfadbestandteil des Zielordners, sein Kernname
    (Telefonbuch-Ordner „Carius, Dr. Emil (Zahnarzt)" → auch „Carius") und der übergebene
    ordnername.

    :param ordnername: der aus dem Absender abgeleitete Ordnername. Nötig, weil der reale
        Ordner oft kürzer heißt als der Absender (Live-Fund 01.09.2026: Ordner „Finanzamt",
        Tag „Finanzamt Musterstadt" — ohne diesen Vergleich bliebe der Tag stehen).
        Bei einer Alias-Ablage in einen FREMDEN Ordner bewusst leer lassen: dort verrät
        der Ordner den Absender gerade nicht, der Tag ist dann die einzige Spur.
    """
    if not zielordner:
        return tags
    basis = os.path.basename(zielordner.replace("/", os.sep).rstrip("\\/"))
    verboten = {basis.strip().lower(), kernname(basis).strip().lower(),
                (ordnername or "").strip().lower()} - {""}
    return [t for t in tags if t.strip().lower() not in verboten]


def _kategorie_name(kanonisch, kategorien):
    """
    Wie die Kategorie im KONKRETEN Katalog heißt. Die ausgelieferte Vorlage nennt sie
    "Objekte & Adressen", eine gewachsene Sammlung oft nur "Adressen" - ohne diese
    Auflösung landeten neue Orts-Tags in der Sammelkategorie "Neu" und wären für
    die Dubletten-Unterscheidung unsichtbar (siehe dubletten.KATEGORIE_VARIANTEN).
    """
    vorhanden = {str(k).strip().lower(): str(k).strip() for k in (kategorien or ())}
    for name in KATEGORIE_VARIANTEN.get(kanonisch, (kanonisch,)):
        if name.lower() in vorhanden:
            return vorhanden[name.lower()]
    return kanonisch


def ohne_kategorien(tags, kategorien):
    """
    Graue Struktur-Kategorien werden nie vergeben - auch nicht von der Vollautomatik
    (Nutzerfund 08.09.2026: 'Hermann Mustermann' stand als grauer Knoten unter Personen/Familie/
    Musterstadt, kam als Empfänger-Tag trotzdem ins Dokument). Die grauen Namen bleiben für das
    Erkennen von Schreibvarianten wichtig (finde_personen_schreibweise/finde_objekt_schreibweise
    schnappen darauf, damit kein Doppelgänger entsteht), aber das Ergebnis fällt hier heraus -
    genau wie beim Doppelklick im Tag-Baum. Der Titel behält das Objekt (objekte_ohne_ort).
    """
    grau = {str(k).strip().lower() for k in (kategorien or ())}
    return [t for t in tags if t.strip().lower() not in grau]


# Prüfung für NEUE Sach-Tags (Tag-Wildwuchs, Betatest 27.10.2026: "AFP LPD PDF TIFF",
# "3 TAN: 309876", "Sehr geehrter Kunde", "abzubuchender Gesamtbeitrag in Euro",
# "Weidenstr. 8 Whg 2 and 4", "Finanzamt Musterstadt" als Tag neben dem gleichnamigen Ordner).
# Die Regeln der Literatur zu kontrolliertem Vokabular: deutsch, Substantiv, kurz, keine
# Nummern - was an genau einem Dokument hängt, findet die Volltextsuche ohnehin.
MIN_NEUES_TAG = 4
MAX_WOERTER_NEUES_TAG = 3
_ENGLISCHE_FUELLWOERTER = {"and", "of", "the", "for", "with", "to", "on"}  # "in" ist auch deutsch
_DATEIFORMATE = {"pdf", "tif", "tiff", "jpg", "jpeg", "png", "afp", "lpd", "doc", "docx", "xml"}
_ANREDE_IM_TAG = re.compile(r"\b(?:sehr geehrte[rn]?|geehrte[rn]?|liebe[rn]?|hallo)\b", re.IGNORECASE)


def grund_gegen_neues_tag(tag, absender_namen=()):
    """
    Warum ein KI-Tag, das NICHT im Katalog steht, kein Tag werden soll - '' wenn es taugt.
    Gilt nur für Sach-Tags; Personen und Objekte haben eigene Regeln (ist_personenname,
    ist_objektbezeichnung), Katalog-Tags werden nie geprüft.
    :param absender_namen: Absender/Ordnername der Entscheidung - als Tag reine Doppelung
    """
    tag = (tag or "").strip()
    woerter = re.findall(r"[^\W_]+", tag.lower())
    if len(tag) < MIN_NEUES_TAG:
        return "zu kurz"
    if re.search(r"\d", tag):
        return "enthält Ziffern"
    if len(tag.split()) > MAX_WOERTER_NEUES_TAG:
        return "zu lang"
    if not tag[0].isupper():
        return "kein Substantiv"
    if _ANREDE_IM_TAG.search(tag):
        return "Anrede"
    if any(w in _ENGLISCHE_FUELLWOERTER for w in woerter):
        return "englisch"
    if any(w in _DATEIFORMATE for w in woerter):
        return "Dateiformat"
    if tag.lower() in {str(n).strip().lower() for n in absender_namen if n}:
        return "Absender"
    return ""


def ohne_unbrauchbare_neue_tags(tags, tag_kategorien, known_tags, absender_namen=()):
    """
    Wendet grund_gegen_neues_tag auf die neuen Sach-Tags an.
    :return: (behaltene Tags, [(verworfenes Tag, Grund)]) - ohne known_tags (keine
             Katalog-Information) bleibt alles stehen, wie bei bestimme_neue_tags
    """
    if known_tags is None:
        return list(tags), []
    bekannt = {t.lower() for t in known_tags}
    eigene_regeln = {v.lower() for v in KATEGORIE_VARIANTEN[KATEGORIE_PERSONEN] + KATEGORIE_VARIANTEN[KATEGORIE_OBJEKTE]}
    kategorie_von = {str(k).strip().lower(): str(v).strip().lower() for k, v in (tag_kategorien or {}).items()}
    behalten, verworfen = [], []
    for tag in tags:
        grund = ""
        if tag.lower() not in bekannt and kategorie_von.get(tag.lower(), "") not in eigene_regeln:
            grund = grund_gegen_neues_tag(tag, absender_namen)
        if grund:
            verworfen.append((tag, grund))
        else:
            behalten.append(tag)
    return behalten, verworfen


def bestimme_neue_tags(tags, tag_kategorien, known_tags, kategorien):
    """
    Welche der KI-Tags sind noch nicht im Katalog, und in welche Kategorie gehören sie?
    Die Kategorie kommt aus dem KI-Vorschlag (tag_kategorien), zählt aber nur, wenn sie
    wirklich eine Katalog-Kategorie ist (Schreibweise wird auf die des Katalogs
    normalisiert); sonst '' - der Katalog legt sie dann unter 'Neu' ab.
    Als bekannt gelten auch die Namen der Struktur-Kategorien selbst (FALLSTRICKE #59:
    known_tags enthält nur zuweisbare Tags - schlägt die KI 'Gesundheit' vor und das ist
    im Katalog eine graue Kategorie, entstand sonst ein zweites 'Gesundheit' unter
    'Neu' (damals 'Neu (KI)'); 38 solche Doppelgänger nach dem Praxislauf vom 06.09.2026).
    :return: Liste von (Tag, Kategorie) in Tag-Reihenfolge, ohne Dubletten
    """
    if known_tags is None:
        return []  # ohne Katalog-Information nichts melden (reine Entscheidungsprüfung)
    bekannt = {t.lower() for t in known_tags} | {str(k).strip().lower() for k in (kategorien or ())}
    kategorie_nach_name = {k.lower(): k for k in (kategorien or ())}
    vorschlaege = {str(k).strip().lower(): str(v).strip() for k, v in (tag_kategorien or {}).items()}
    neue = []
    gesehen = set()
    for tag in tags or ():
        tag = (tag or "").strip()
        schluessel = tag.lower()
        if not tag or schluessel in bekannt or schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        kategorie = kategorie_nach_name.get(vorschlaege.get(schluessel, "").lower(), "")
        neue.append((tag, kategorie))
    return neue


def ortswoerter_des_dokuments(ki_antwort):
    """Die Wörter des KI-Orts ('12345 Musterstadt' -> {'musterstadt'}), wie finde_aehnlichen_ordner sie vergleicht."""
    return set(_namenswoerter(ohne_plz(str((ki_antwort or {}).get("ort") or ""))))


def merke_orte(orte, gelesen):
    """
    Ortswörter eines gelesenen Dokuments (lies_dokument) in die Menge `orte` des Laufs aufnehmen
    (Peter 29.10.2026, Rest von FALLSTRICKE #83): Ablage-Vorschau und Vollautomatik merken sich so
    die Orte, die die KI bisher gelesen hat, und wählen bei 'Stadtwerke Musterstadt' den Ordner
    'Landratsamt Musterstadt' nicht mehr vor - auch wenn der Ort im Dokument selbst fehlt.
    Nur Wörter, die für die Ähnlichkeit überhaupt zählen (MIN_AEHNLICHKEITS_WORT).
    """
    if gelesen:
        orte.update(w for w in ortswoerter_des_dokuments(gelesen.get("ki_antwort"))
                    if len(w) >= MIN_AEHNLICHKEITS_WORT)
    return orte


def baue_entscheidung(pdf_path, ki_antwort, vorhandene_ordner, schreibschutz=None, vocabulary=None, aliase=None,
                      known_tags=None, kategorien=None, ignorierte_tags=None, tag_eltern=None,
                      synonyme=None, gedaechtnis=None, orte=None):
    """
    Verwandelt den KI-Vorschlag (ollama_client.suggest_filing) in eine geprüfte
    Ablage-Entscheidung - reine Funktion, kein Dateisystem-/Netzwerkzugriff.

    :param vorhandene_ordner: relative Ordnerpfade der Sammlung (sammle_ordnerliste)
    :param schreibschutz: Ergebnis von PDFHandler.get_write_protection (oder None)
    :param vocabulary: Wortschatz (Counter) für die Titel-Korrektur, siehe korrigiere_titel; None = keine Korrektur
    :param aliase: Absender-Aliase {Absender: Zielordner} (ordner_aliase.lade_aliase); haben Vorrang
                   vor dem Namens-Matching. None/leer = keine Aliase
    :param known_tags: Tag-Katalog; KI-Tags, die dort fehlen, werden als neue_tags gemeldet
    :param kategorien: Kategorien des Katalogs (tag_manager.get_kategorien) für die Zuordnung neuer Tags
    :param ignorierte_tags: Ignorierliste (tag_ignorierliste.lade) - diese Tags schlägt die KI nie mehr vor
    :param tag_eltern: Oberkategorien-Zuordnung des Tag-Baums (tag_manager.get_tag_eltern)
                       für die Auto-Hierarchie, siehe ergaenze_oberkategorien; None = aus
    :param synonyme: Synonym-Zuordnung des Tag-Baums (tag_manager.get_synonyme), siehe ersetze_synonyme
    :param gedaechtnis: Ablage-Gedächtnis (ablage_gedaechtnis.Gedaechtnis) - nach den Aliasen, vor den
                        Namensregeln; None = aus
    :param orte: bisher gesehene Ortswörter des Laufs (merke_orte) - zählen wie der Ort des Dokuments
                 bei der Vorauswahl eines ähnlichen Ordners nicht mit (FALLSTRICKE #83); None = nur der eigene
    :return: Dict mit pdf_path, titel, titel_korrekturen, tags, tag_ersetzungen [(alt, neu)],
             neue_tags [(Tag, Kategorie)], datum,
             absender, ordnername, zielordner, ordner_neu, ordner_per_alias,
             ordner_gedaechtnis (Stimmen, 0 = Ordner nicht aus dem Gedächtnis),
             ordner_hinweis ('Tag'/'Dateiname'/''), neuer_dateiname, sicher, probleme (Liste von Gründen).
    """
    titel = (ki_antwort.get("title") or "").strip()
    titel, titel_korrekturen = korrigiere_titel(titel, vocabulary)
    # Objekt in den Titel (Nutzerwunsch 03.09.2026): macht Titel UND Dateinamen im
    # Ordner unterscheidbar - deterministisch aus dem Objekt-Feld, keine zweite KI nötig.
    objekte = objekte_ohne_ort(ki_antwort, known_tags, kategorien)
    titel = titel_mit_objekt(titel, objekte)
    tags, tag_kategorien = tags_mit_empfaenger(ki_antwort, ignorierte_tags, known_tags, vocabulary, kategorien)
    # Synonyme VOR der Katalog-Sperre und der Auto-Hierarchie: das Ziel-Tag ist ein Katalog-Tag
    # und bringt seine Oberkategorien selbst mit.
    tags, tag_ersetzungen = ersetze_synonyme(tags, synonyme)
    tags = ohne_kategorien(tags, kategorien)  # grau = nie vergeben, auch nicht automatisch
    tags = ergaenze_oberkategorien(tags, tag_eltern, ignorierte_tags)
    datum = normalisiere_datum(ki_antwort.get("datum"))
    # Rücksendezeile statt Name ('Bay. LfSt, PF 0151 Straubing'): Adressteil weg, der Rest
    # ist der Alias-Schlüssel und Vergleichsname; ein reines Kürzel wird unten nie zum
    # neuen Ordner (siehe trenne_adresszeile / absender_ist_kuerzel).
    absender, war_adresszeile = trenne_adresszeile(ki_antwort.get("absender"))
    absender_kuerzel = absender_ist_kuerzel(absender)
    # Telefonbuch-Form von der KI ('Carius, Dr. Emil (Zahnarzt)') - aber nur, wenn sie
    # nachweislich aus dem Absender stammt (siehe ordnername_passt_zum_absender: die KI
    # lieferte sonst den Empfänger). Fehlt/verworfen: der Absender selbst ist der Ordnername.
    ordnername_ki, _ = trenne_adresszeile(ki_antwort.get("ordnername"))
    if ordnername_ki and not ordnername_passt_zum_absender(ordnername_ki, absender):
        ordnername_ki = ""
    roh = ordnername_ki or absender
    ordnername = bereinige_ordnername(ordnername_aus_adresse(roh))
    # Mit vorhandenen Ordnern wird eine bloße Adresse nur über den Domainnamen verglichen (FALLSTRICKE #107)
    vergleichsnamen = [_vergleichsname(absender), ordnername if _vergleichsname(roh) == roh else _vergleichsname(roh)]
    tags, tags_verworfen = ohne_unbrauchbare_neue_tags(
        tags, tag_kategorien, known_tags, (absender, ordnername, ki_antwort.get("absender")))

    probleme = []
    if schreibschutz in ("verschlüsselt", "schreibgeschützt"):
        probleme.append(f"PDF ist {schreibschutz}")
    if not titel:
        probleme.append("kein Titel erkannt")
    if not _datum_ist_plausibel(datum):
        probleme.append("kein plausibles Dokumentdatum erkannt")

    # Zielordner-Wahl ist bewusst KEINE KI-Aufgabe (siehe finde_passenden_ordner) - findet
    # sich kein vorhandener Ordner, wird ein neuer vorgeschlagen: unter dem passenden
    # Buchstabengruppen-Ordner der Sammlung, falls sie welche hat, sonst flach.
    # Vorher: ein vom Nutzer hinterlegter Alias schlägt jeden Namensvergleich - das ist
    # der Weg für Weltwissen, das kein String-Vergleich haben kann ("Bayerische
    # Landesbrandversicherung" gehört zur "Versicherungskasse Musterland").
    ordner_neu = False
    ordner_per_alias = False
    ordner_sammel = False
    ordner_gedaechtnis = 0
    ordner_hinweis = ""
    zielordner = ordner_aliase.finde_alias(absender, aliase)
    treffer = gedaechtnis.frage(absender) if gedaechtnis is not None and absender and not zielordner else None
    if zielordner:
        ordner_per_alias = True
        zielordner = ordner_aliase.loese_alias_ordner(zielordner, vorhandene_ordner)
        ordner_neu = zielordner not in vorhandene_ordner
    elif treffer and treffer[0] in vorhandene_ordner:
        # Ablage-Gedächtnis (ablage_gedaechtnis.py): so viele Dokumente dieses Absenders liegen
        # schon dort - das löst auch, was kein Namensvergleich kann (Landesbrandversicherung ->
        # Versicherungskasse). Gilt wie ein Alias: keine Zweitmeinung, keine Ordner-Probleme.
        zielordner, ordner_gedaechtnis = treffer[0], treffer[1]
        ordner_hinweis = f"Gedächtnis, {ordner_gedaechtnis} Dokumente"
    else:
        zielordner = finde_passenden_ordner(vergleichsnamen[0], vorhandene_ordner, ordnername)
    if zielordner is None and not absender:
        # Eigenbelege (Notizen, Zählerstände, Mieterlisten) haben keinen Absender, aber
        # ein Objekt - ein per Klick gelernter Objekt-Alias ordnet sie dem Haus bzw. der
        # Wohnung zu (11.09.2026: 33 der 84 unsicheren Dokumente des Praxislaufs).
        zielordner, _objekt = ordner_aliase.finde_objekt_alias(objekte, aliase)
        if zielordner:
            ordner_per_alias = True
            ordner_hinweis = "Objekt"
            zielordner = ordner_aliase.loese_alias_ordner(zielordner, vorhandene_ordner)
            ordner_neu = zielordner not in vorhandene_ordner
    if zielordner is None and not absender:
        # Ohne Absender (Formulare, Mandate): Tags/Dateiname exakt gegen vorhandene Ordner
        zielordner, ordner_hinweis = finde_ordner_ueber_hinweise(tags, pdf_path, vorhandene_ordner)
        ordner_hinweis = ordner_hinweis or ""
    if zielordner is None and ordnername:
        aus_mailkopf = bool(ki_antwort.get("absender_aus_mailkopf"))
        kern_laenge = len(kernname(ordnername))
        mindestlaenge = 2 if aus_mailkopf else MIN_NEUER_ORDNER
        gleichnamig = next((o for o in vorhandene_ordner
                            if os.path.basename(o).casefold() == ordnername.casefold()), None)
        if gleichnamig and mindestlaenge <= kern_laenge < MIN_ORDNER_MATCH_LAENGE:
            zielordner = gleichnamig       # finde_passenden_ordner vergleicht so kurze Namen bewusst nicht
        elif kern_laenge < mindestlaenge:
            # Ein Kürzel wie 'KM' oder ein einzelner Buchstabe taugt nicht als Ordner -
            # lieber Unsicher als einen Ordner anlegen, den niemand wiederfindet.
            probleme.append(f"Absendername zu kurz für einen Ordner: '{ordnername}'")
        elif absender_kuerzel and not aus_mailkopf:
            # 'Bay. LfSt' (aus der Rücksendezeile) darf kein Ordner werden - Zielordner-Klick
            # legt den Alias 'Bay. LfSt' -> richtiger Ordner an, danach läuft es automatisch.
            probleme.append(
                f"Absender nur als Kürzel{' aus der Adresszeile' if war_adresszeile else ''} erkannt: "
                f"'{absender}' - Zielordner anklicken, dann merkt sich die Automatik den Ordner (Alias)")
            # Ein ähnlicher vorhandener Ordner ('ElsterOnline' -> 'ELSTER') ist schon vorgewählt,
            # dann reicht in der Ablage-Vorschau Enter (Betatest 25.10.2026).
            zielordner = _aehnlicher_ordner(vergleichsnamen, vorhandene_ordner)
        else:
            gruppe = finde_buchstabengruppe(ordnername, vorhandene_ordner)
            neuer_ordner = os.path.join(gruppe, ordnername) if gruppe else ordnername
            aehnlich = _aehnlicher_ordner(vergleichsnamen, vorhandene_ordner)
            vorwahl = aehnlich and _aehnlicher_ordner(
                vergleichsnamen, vorhandene_ordner, ohne_gattungswoerter=True,
                ortswoerter=ortswoerter_des_dokuments(ki_antwort) | set(orte or ()))
            if ki_antwort.get("einzelne_mail"):
                # E17: Eine einzelne Mail ist weder einen eigenen Ordner noch eine Rückfrage wert, auch nicht bei einem ähnlichen
                # Ordner (Peter 06.11.2026). Nichts geht verloren, der Absender steht als Tag dabei.
                zielordner = os.path.join(gruppe, SAMMEL_ORDNER) if gruppe else SAMMEL_ORDNER
                ordner_neu = True
                ordner_sammel = True
                ordner_hinweis = SAMMEL_ORDNER
            elif vorwahl:
                # Kein stiller Doppelordner: der ähnliche Ordner ist vorgewählt, der Mensch
                # bestätigt ihn (oder tippt den neuen Namen) - Betatest 25.10.2026.
                zielordner = vorwahl
                probleme.append(f"{_PROBLEM_AEHNLICHER_ORDNER} '{vorwahl}' - passt er zu '{absender or ordnername}'? "
                                f"Zielordner anklicken (oder neuen Ordner '{ordnername}' eintippen)")
            elif aehnlich:
                # Nur über ein Gattungswort ähnlich ('Versicherung'): trotzdem bremsen, aber der NEUE
                # Ordner ist vorgewählt - Enter in der Ablage-Vorschau legt ihn an. Bleibt das Dokument
                # unsicher, wandert der Ordner NICHT in die Ordnerliste der Runde (auto_pilot_service,
                # auto_filer) - sonst legte das nächste Dokument still in einen nie bestätigten Ordner ab.
                zielordner = neuer_ordner
                ordner_neu = True
                probleme.append(f"{_PROBLEM_AEHNLICHER_ORDNER} '{aehnlich}' - gehört '{absender or ordnername}' "
                                f"dorthin? Sonst wird der neue Ordner '{ordnername}' angelegt - Zielordner "
                                "anklicken oder bestätigen")
            else:
                zielordner = neuer_ordner
                ordner_neu = True
    # Vertrag nach außen: zielordner ist IMMER ein String, nie None - ohne Absender
    # bleibt finde_passenden_ordner() bei None hängen (siehe oben, "and absender"
    # greift dann nicht) und würde sonst tools/auto_filer.py mit einem
    # TypeError beim String-Verketten abstürzen lassen.
    zielordner = zielordner or ""
    if not zielordner:
        # Mit Objekt bekommt der Nutzer den Wink, wie er es dauerhaft löst (Objekt-Alias).
        wink = (f" (Objekt '{objekte[0]}' - Zielordner anklicken und 'alle Dokumente zu diesem Objekt' wählen)"
                if objekte else "")
        probleme.append("kein Zielordner und kein Absender erkannt" + wink)

    # Etappe 6 (Peter 07.11.2026 nach der Prüfung beim Betatest: „fast alle von der KI generierten Tags nicht brauchbar“):
    # Die KI vergibt keine Tags mehr, auch keinen Absender-Tag beim Sammelordner. Ihre Tags dienten oben nur noch als Hinweis
    # für die Ordnerwahl ohne Absender (finde_ordner_ueber_hinweise). Tags setzt der Mensch, etwa in der Ablage-Vorschau;
    # ein Dokument ohne Tags ist darum auch kein Grund mehr für „unsicher“ (FALLSTRICKE #120).
    tags, tag_ersetzungen, tags_verworfen, neue_tags = [], [], [], []

    sicher = not probleme
    return {
        "pdf_path": pdf_path,
        "titel": titel,
        "titel_korrekturen": titel_korrekturen,
        "tags": tags,
        "tag_ersetzungen": tag_ersetzungen,
        "tags_verworfen": tags_verworfen,
        "neue_tags": neue_tags,
        "datum": datum,
        "absender": absender,
        "ordnername": ordnername,
        "zielordner": zielordner,
        "ordner_neu": ordner_neu,
        "ordner_per_alias": ordner_per_alias,
        "ordner_sammel": ordner_sammel,
        "ordner_gedaechtnis": ordner_gedaechtnis,
        "objekte": objekte,
        "ordner_hinweis": ordner_hinweis,
        "neuer_dateiname": baue_dateiname(datum, titel) if sicher else "",
        "sicher": sicher,
        "probleme": probleme,
    }


# Probleme, die allein an der Ordnerwahl hängen - sie erledigen sich, sobald der Nutzer
# den Zielordner selbst bestimmt (wende_zielordner_an).
# "Absender nur als Kürzel" fehlte hier bis zum Betatest 25.10.2026: der Hinweis verlangte
# den Zielordner-Klick, der Klick räumte ihn aber nicht weg - die Zeile blieb gelb.
_PROBLEM_AEHNLICHER_ORDNER = "Ähnlicher Ordner vorhanden:"
_PROBLEM_ZWEITMEINUNG = "Zweitmeinung zum Ordner:"
_ORDNER_PROBLEM_PRAEFIXE = ("Absendername zu kurz für einen Ordner", "kein Zielordner und kein Absender erkannt",
                            "Absender nur als Kürzel", _PROBLEM_AEHNLICHER_ORDNER, _PROBLEM_ZWEITMEINUNG)

# Zweitmeinung eines Entscheidungsmodells zur Ordnerwahl (ollama_client.waehle_ordner,
# Modell-Prüfstand 27.10.2026 am Bestand von 403 Dokumenten). Grundregel bleibt: die KI
# schlägt vor, dieser Code entscheidet.
# - Sperre: legt die Regel-Logik sicher ab, das Modell hält aber mit p >= SPERRE einen
#   ANDEREN Ordner für richtig -> unsicher (still falsch 36 -> 14; bei solchen Widersprüchen
#   hatte die Logik 14x, das Modell 11x recht, 11x beide falsch - deshalb bleibt der Ordner
#   der Logik vorgewählt und der des Modells steht nur im Hinweis).
# - Bestätigung: ist die Logik nur wegen der Ordnerwahl unsicher und das Modell sehr sicher
#   (p >= ERSATZ und Abstand zum Zweitplatzierten >= ABSTAND), gilt dessen Ordner (16 von 17 richtig).
ZWEITMEINUNG_SPERRE_AB = 0.8
ZWEITMEINUNG_ERSATZ_AB = 0.95
ZWEITMEINUNG_ABSTAND = 0.2
ZWEITMEINUNG_HINWEIS = "KI-Ordnerwahl"


def ordner_fuer_zweitmeinung(vorhandene_ordner):
    """Die Ordner, die als Ablageziel infrage kommen: ohne die Buchstabengruppen der obersten Ebene."""
    ziele = []
    for ordner in vorhandene_ordner:
        oben = os.sep not in ordner and "/" not in ordner
        if oben and (buchstaben_der_gruppe(ordner) or _ZIFFERNGRUPPE.match(ordner)):
            continue
        ziele.append(ordner)
    return ziele


def wende_zweitmeinung_an(entscheidung, rangliste, vorhandene_ordner):
    """
    Verrechnet die Rangliste des Entscheidungsmodells ([(ordner, p), ...], beste zuerst)
    mit der Entscheidung der Regel-Logik (siehe ZWEITMEINUNG_*). Liefert eine Kopie.
    Per Alias festgelegte Ordner bleiben unberührt - die hat der Mensch selbst beigebracht -,
    ebenso Ordner aus dem Ablage-Gedächtnis (dort liegen schon mehrere Dokumente des Absenders).
    """
    if not rangliste or entscheidung.get("ordner_per_alias") or entscheidung.get("ordner_gedaechtnis") or entscheidung.get("ordner_sammel"):
        return entscheidung
    bester, p1 = rangliste[0]
    p2 = rangliste[1][1] if len(rangliste) > 1 else 0.0
    ziel = entscheidung.get("zielordner") or ""
    if entscheidung["sicher"]:
        if bester == ziel or p1 < ZWEITMEINUNG_SPERRE_AB:
            return entscheidung
        neu = dict(entscheidung)
        neu["probleme"] = list(entscheidung["probleme"]) + [
            f"{_PROBLEM_ZWEITMEINUNG} die KI hält '{bester}' für passender ({p1:.0%}) - "
            f"Zielordner anklicken und bestätigen oder ändern"]
        neu["sicher"] = False
        neu["neuer_dateiname"] = ""
        return neu
    ordner_probleme = [p for p in entscheidung["probleme"] if p.startswith(_ORDNER_PROBLEM_PRAEFIXE)]
    if not ordner_probleme or p1 < ZWEITMEINUNG_ERSATZ_AB or p1 - p2 < ZWEITMEINUNG_ABSTAND:
        return entscheidung
    neu = wende_zielordner_an(entscheidung, bester, vorhandene_ordner)
    neu["ordner_per_alias"] = False
    neu["ordner_hinweis"] = ZWEITMEINUNG_HINWEIS
    return neu
_PROBLEM_KEIN_TITEL = "kein Titel erkannt"
_PROBLEM_KEINE_TAGS = "keine Tags erkannt"
_PROBLEM_KEIN_DATUM = "kein plausibles Dokumentdatum erkannt"


def wende_korrektur_an(entscheidung, titel=None, datum=None, tags=None, known_tags=None, kategorien=None):
    """
    Liefert eine Kopie der Entscheidung mit vom Nutzer korrigiertem Titel, Datum und/oder
    Tags (Klick auf die Zelle in der Ablage-Vorschau). Das jeweilige KI-Problem entfällt
    bzw. kommt zurück, wenn die Eingabe leer/unplausibel ist; 'sicher' und der Dateiname
    werden neu bestimmt. None = Feld unverändert lassen.
    :param tags: kommagetrennter Eingabetext des Nutzers (Nutzerwunsch 01./03.09.2026);
                 Komma ist das Trennzeichen des Schlagwortfelds (FALLSTRICKE #38).
                 known_tags/kategorien dienen dazu, die "(neu→Kategorie)"-Kennzeichnung
                 für hinzugetippte Tags neu zu bestimmen.
    """
    neu = dict(entscheidung)
    # Eine Korrektur ändert die Faktenlage - eine früher erteilte manuelle Freigabe
    # (wende_freigabe_an) gilt dann nicht mehr und muss neu erteilt werden.
    neu.pop("manuell_freigegeben", None)
    probleme = list(entscheidung["probleme"])
    if titel is not None:
        neu["titel"] = titel.strip()
        neu["titel_korrekturen"] = []  # Nutzer-Titel wird nicht mehr "korrigiert"
        probleme = [p for p in probleme if p != _PROBLEM_KEIN_TITEL]
        if not neu["titel"]:
            probleme.append(_PROBLEM_KEIN_TITEL)
    if datum is not None:
        neu["datum"] = normalisiere_datum(datum)
        probleme = [p for p in probleme if p != _PROBLEM_KEIN_DATUM]
        if not _datum_ist_plausibel(neu["datum"]):
            probleme.append(_PROBLEM_KEIN_DATUM)
    if tags is not None:
        liste = []
        for teil in str(tags).split(","):
            teil = " ".join(teil.split())
            if teil and teil.lower() not in {t.lower() for t in liste}:
                liste.append(teil)
        neu["tags"] = liste
        neu["neue_tags"] = bestimme_neue_tags(liste, None, known_tags, kategorien)
        # Leere Tags sind kein Problem mehr (Etappe 6, FALLSTRICKE #120); ein alter Eintrag fällt weg
        probleme = [p for p in probleme if p != _PROBLEM_KEINE_TAGS]
    neu["probleme"] = probleme
    neu["sicher"] = not probleme
    neu["neuer_dateiname"] = baue_dateiname(neu["datum"], neu["titel"]) if neu["sicher"] else ""
    return neu


def korrigierbare_probleme(entscheidung):
    """
    Die Teilmenge der Probleme, für die die Ablage-Vorschau eine eigene Korrektur-Zelle
    hat (Titel/Tags/Datum/Zielordner). Alles andere ("vermutlich Dublette zu ...",
    Schreibschutz, Seite nicht darstellbar) besitzt keine Zelle - dafür gibt es die
    manuelle Freigabe (wende_freigabe_an).
    """
    praefixe = (_PROBLEM_KEIN_TITEL, _PROBLEM_KEINE_TAGS, _PROBLEM_KEIN_DATUM) + _ORDNER_PROBLEM_PRAEFIXE
    return [p for p in entscheidung["probleme"] if p.startswith(praefixe)]


def wende_freigabe_an(entscheidung, freigeben=True):
    """
    Manuelle Freigabe einer 'unsicheren' Zeile (Nutzerwunsch 06.09.2026): Der Nutzer hat
    die verbliebenen Gründe (z.B. "vermutlich Dublette zu ...") selbst geprüft und will
    trotzdem automatisch ablegen. Liefert eine Kopie; die Probleme BLEIBEN im Dict
    stehen, damit Anzeige und Protokoll ehrlich sagen, worüber hinweggegangen wurde.
    Korrigierbare Probleme (korrigierbare_probleme) werden bewusst NICHT überstimmt -
    ohne Titel/Datum gäbe es keinen Dateinamen; sind welche offen, bleibt die
    Entscheidung unsicher. freigeben=False nimmt die Freigabe zurück.
    """
    neu = dict(entscheidung)
    neu["manuell_freigegeben"] = bool(freigeben)
    neu["sicher"] = not neu["probleme"] or (bool(freigeben) and not korrigierbare_probleme(neu))
    neu["neuer_dateiname"] = baue_dateiname(neu["datum"], neu["titel"]) if neu["sicher"] else ""
    return neu


PROBLEM_ZURUECKGESTELLT = "von Hand zurückgestellt"


def wende_zurueckstellung_an(entscheidung, zurueckstellen=True):
    """
    Gegenstück zur Freigabe (Peter 02.11.2026: „Dokumente manuell wieder gelb machen, wenn sie fälschlicherweise
    grün wurden“): eine sichere Zeile wird unsicher und wandert beim Einsortieren nach 0_Unsicher. Als Problem
    vermerkt, damit es Korrekturen an Titel/Datum/Zielordner überlebt (die bestimmen `sicher` aus den Problemen
    neu) und als Grund (KID_GRUND, Protokoll) dasteht. zurueckstellen=False nimmt es zurück.
    """
    neu = dict(entscheidung)
    neu.pop("manuell_freigegeben", None)
    neu["probleme"] = [p for p in entscheidung["probleme"] if p != PROBLEM_ZURUECKGESTELLT]
    if zurueckstellen:
        neu["probleme"].append(PROBLEM_ZURUECKGESTELLT)
    neu["sicher"] = not neu["probleme"]
    neu["neuer_dateiname"] = baue_dateiname(neu["datum"], neu["titel"]) if neu["sicher"] else ""
    return neu


def alias_schluessel(entscheidung):
    """
    Unter welchem Schlüssel ein Zielordner-Klick "für alle" gemerkt wird: der Absender -
    oder, bei Dokumenten ohne Absender (Eigenbelege), das erste Objekt auf Haus-Ebene
    ("Weidenstr. 8 Whg 4" -> "Objekt: Weidenstr. 8", ordner_aliase.objekt_kern), damit
    alle Wohnungen des Hauses denselben Ordner bekommen.
    :return: (Schlüssel, Art 'Absender'/'Objekt') oder ('', '') wenn nichts lernbar ist
    """
    absender = (entscheidung.get("absender") or "").strip()
    if absender:
        return absender, "Absender"
    objekte = entscheidung.get("objekte") or []
    if objekte:
        return ordner_aliase.objekt_schluessel(ordner_aliase.objekt_kern(objekte[0])), "Objekt"
    return "", ""


def alias_trifft(entscheidung, schluessel, zielordner):
    """
    Gilt der frisch gelernte Alias {schluessel: zielordner} auch für diese (andere) Zeile
    des Stapels? Absender-Alias nur über den Absender, Objekt-Alias nur für absenderlose
    Dokumente über deren Objekte - genau wie in baue_entscheidung.
    """
    absender = (entscheidung.get("absender") or "").strip()
    if ordner_aliase.ist_objekt_alias(schluessel):
        if absender:
            return False
        return ordner_aliase.finde_objekt_alias(entscheidung.get("objekte"), {schluessel: zielordner})[0] is not None
    return bool(absender) and ordner_aliase.finde_alias(absender, {schluessel: zielordner}) is not None


def wende_zielordner_an(entscheidung, zielordner, vorhandene_ordner):
    """
    Liefert eine Kopie der Entscheidung mit vom Nutzer festgelegtem Zielordner (Klick auf
    die Zielordner-Zelle in der Ablage-Vorschau). Ordner-bezogene Probleme entfallen,
    'sicher' und der neue Dateiname werden neu bestimmt; Titel/Tags/Datum-Probleme
    bleiben - ein fehlendes Datum wird durch einen richtigen Ordner nicht besser.
    """
    zielordner = (zielordner or "").strip()
    neu = dict(entscheidung)
    # Eine Korrektur ändert die Faktenlage - eine früher erteilte Freigabe gilt dann
    # nicht mehr (der Dubletten-Verdacht bezog sich z.B. auf den ALTEN Zielordner).
    neu.pop("manuell_freigegeben", None)
    neu["zielordner"] = zielordner
    neu["ordner_neu"] = bool(zielordner) and zielordner not in vorhandene_ordner
    neu["ordner_per_alias"] = True
    neu["ordner_sammel"] = False
    neu["ordner_gedaechtnis"] = 0
    neu["ordner_hinweis"] = ""
    neu["probleme"] = [p for p in entscheidung["probleme"] if not p.startswith(_ORDNER_PROBLEM_PRAEFIXE)]
    if not zielordner:
        neu["probleme"].append("kein Zielordner und kein Absender erkannt")
    neu["sicher"] = not neu["probleme"]
    neu["neuer_dateiname"] = baue_dateiname(neu["datum"], neu["titel"]) if neu["sicher"] else ""
    return neu


def _gleicher_pfad(a, b):
    """Zeigen beide Pfade auf dieselbe Datei? (Groß-/Kleinschreibung und Schrägstrich-Mix egal, FALLSTRICKE #52)"""
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _naechster_freier_pfad(pfad):
    """Hängt bei Namenskonflikten '_1', '_2', ... an (gleiches Muster wie restore_file in file_operations.py)."""
    if not os.path.exists(pfad):
        return pfad
    ordner = os.path.dirname(pfad)
    name, ext = os.path.splitext(os.path.basename(pfad))
    counter = 1
    kandidat = pfad
    while os.path.exists(kandidat):
        kandidat = os.path.join(ordner, f"{name}_{counter}{ext}")
        counter += 1
    return kandidat


def protokolliere(master_folder, zeile, logger=None):
    """
    Eine Zeile ins Angehörigen-Protokoll 'Vollautomatik-Protokoll.txt' im Daten-Ordner
    (eine Aktion pro Zeile, ohne Technik-Kauderwelsch). Gemeinsamer Schreibweg für die
    Watchdog-Vollautomatik UND das Einsortieren aus der Ablage-Vorschau - beim
    Kaltstart-Test 03.09.2026 lagen 71 Unsicher-Dokumente ohne festgehaltenen Grund da,
    weil nur der Watchdog protokollierte und das Vorschau-Fenster längst zu war.
    Ein Fehler hier darf die Ablage nie stoppen.
    """
    try:
        pfad = app_paths.protokoll_path(master_folder)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now():%Y-%m-%d %H:%M}  {zeile}\n")
    except OSError as e:
        if logger is not None:
            logger.warning(f"Vollautomatik: Protokoll nicht schreibbar: {e}")


def protokolliere_ergebnis(entscheidung, ergebnis, master_folder, logger=None):
    """
    Standard-Protokollzeile zu einer ausgeführten Entscheidung (fuehre_entscheidung_aus):
    'abgelegt <name> -> <ziel>', 'unsicher ... (Grund: ...)' oder 'FEHLER ...' -
    dieselben Formate, die auto_pilot_service seit Schritt 4 schreibt.
    """
    name = os.path.basename(entscheidung["pdf_path"])
    if not ergebnis["erfolg"]:
        protokolliere(master_folder, f"FEHLER    {name}  -  {ergebnis['fehler']}", logger)
        return
    ziel_rel = os.path.relpath(ergebnis["neuer_pfad"], master_folder)
    if entscheidung["sicher"]:
        zusatz = ""
        if entscheidung.get("manuell_freigegeben") and entscheidung["probleme"]:
            # Die Freigabe war eine bewusste Nutzer-Entscheidung - das Angehörigen-
            # Protokoll soll zeigen, worüber dabei hinweggegangen wurde.
            zusatz = f"  (manuell freigegeben trotz: {'; '.join(entscheidung['probleme'])})"
        if entscheidung.get("dubletten_zweitpruefung"):
            # Gleiches Prinzip für die KI-Zweitprüfung: falls sie sich doch irrte,
            # ist nachvollziehbar, warum trotz Verdacht abgelegt wurde.
            zusatz += f"  ({entscheidung['dubletten_zweitpruefung']})"
        protokolliere(master_folder, f"abgelegt  {name}  ->  {ziel_rel}{zusatz}", logger)
    else:
        grund = "; ".join(entscheidung["probleme"])
        protokolliere(master_folder, f"unsicher  {name}  ->  {ziel_rel}  (Grund: {grund})", logger)


def fuehre_entscheidung_aus(entscheidung, master_folder, verschieben, still=False, umbenennen=True):
    """
    Setzt eine geprüfte Ablage-Entscheidung (baue_entscheidung) tatsächlich um -
    Schritt 2 des Seniorenmodus (KONZEPT_SENIORENMODUS.md).

    sicher:   Titel/Tags/Datum in die PDF-Metadaten schreiben, nach
              'JJJJMMTT_Titel.pdf' umbenennen, in den Zielordner verschieben
              (wird bei Bedarf neu angelegt).
    unsicher: KI-Titel und Grund schreiben (Peter 04.11.2026), Tags/Datum UNVERÄNDERT, kein Umbenennen, nach '0_Unsicher'
              verschieben - nur der Grund kommt als KID_GRUND ins PDF (Status-Zeile der
              Eigenschaften, Peter 28.10.2026); scheitert das Schreiben, wird trotzdem verschoben.

    Umbenennen (Nutzerfund 11.09.2026: ein falscher KI-Titel machte aus "Grundriss
    Hobbyraum" einen "Mietvertrag ..."): mit ``umbenennen=False`` (Einstellung
    auto_pilot_umbenennen) behält die Datei ihren Namen, Metadaten und Zielordner kommen
    trotzdem. Beim Umbenennen wird der bisherige Name als KID_Originalname in die
    PDF-Metadaten eingebrannt (nur beim ersten Mal, siehe pdf_handler._merge_kid_metadata),
    damit der allererste Name nie verloren geht.

    Randfall (05./06.09.2026): Zwischen Analyse und Ausführung kann Zeit vergehen
    (die Ablage-Vorschau steht offen, der Nutzer benennt derweil einen Ordner um).
    Ein bei der Analyse GEFUNDENER Zielordner (ordner_neu=False) muss deshalb hier
    noch existieren - sonst würde makedirs den alten Namen still wieder anlegen.
    In dem Fall wird die Entscheidung direkt im übergebenen Dict auf 'unsicher'
    zurückgestuft (Grundregel: bei Zweifel nie automatisch ablegen), damit auch
    Protokoll und Aufrufer-Anzeige den echten Ausgang zeigen. Bewusst neue Ordner
    (ordner_neu=True) werden weiterhin angelegt.

    Das eigentliche Verschieben übernimmt der übergebene 'verschieben(quelle, ziel)'-
    Callable (in der Praxis file_operations._verschiebe_ohne_duplikat) statt einer
    eigenen Kopie der Windows-Lock-Robustheit (Wiederholungsversuche, Duplikat-
    Aufräumen, siehe FALLSTRICKE #27) - dieses Modul bleibt damit unabhängig von
    Tkinter/der App und ohne echte Dateizugriffe testbar.

    :param still: True = keine Messagebox aus dem Metadaten-Schreiben (Hintergrund-Thread,
                  siehe auto_pilot_service.py); Fehler kommen dann nur als Rückgabewert.
    :return: Dict mit erfolg (bool), neuer_pfad (str oder None), fehler (str oder None).
    """
    pdf_path = entscheidung["pdf_path"]
    erfasst = scan_date.to_storage(datetime.now())   # einmal gesetzt, nie überschrieben (pdf_handler)
    if (entscheidung["sicher"] and not entscheidung.get("ordner_neu")
            and not os.path.isdir(os.path.join(master_folder, entscheidung["zielordner"]))):
        entscheidung["sicher"] = False
        entscheidung["probleme"] = list(entscheidung.get("probleme") or []) + [
            f"Zielordner '{entscheidung['zielordner']}' existiert nicht mehr "
            "(seit der Analyse umbenannt oder gelöscht?)"]
    try:
        if entscheidung["sicher"]:
            zielordner_abs = os.path.join(master_folder, entscheidung["zielordner"])
            os.makedirs(zielordner_abs, exist_ok=True)
            alter_name = os.path.basename(pdf_path)
            neuer_name = entscheidung["neuer_dateiname"] if umbenennen else alter_name
            ziel = os.path.join(zielordner_abs, neuer_name)
            metadaten = {
                "title": entscheidung["titel"],
                "KID_DokumentenDatum": entscheidung["datum"],
                # Stimme fürs Ablage-Gedächtnis: der Absender reist im PDF mit, ein späteres
                # Verschieben von Hand korrigiert sie also von selbst (ablage_gedaechtnis.py)
                "KID_Absender": entscheidung.get("absender") or "",
                "KID_Grund": "",   # ein früherer Unsicher-Grund gilt nicht mehr
                "KID_Erfasst": erfasst,
            }
            if neuer_name != alter_name:
                metadaten["KID_Originalname"] = alter_name
            if entscheidung.get("tags"):
                # Nur, was ein Mensch eingetragen hat (Ablage-Vorschau); ohne Eintrag bleiben vorhandene Tags im PDF stehen
                metadaten["keywords"] = ", ".join(entscheidung["tags"])
            if not PDFHandler.write_custom_metadata(pdf_path, metadaten, still=still):
                return {"erfolg": False, "neuer_pfad": None, "fehler": "Metadaten konnten nicht geschrieben werden."}
        else:
            unsicher_ordner = os.path.join(master_folder, UNSICHER_ORDNER)
            os.makedirs(unsicher_ordner, exist_ok=True)
            grund = "; ".join(entscheidung.get("probleme") or []) or "unsicher"
            felder = {"KID_Grund": grund, "KID_Erfasst": erfasst}
            # Peter 04.11.2026 (T20.3): auch in 0_Unsicher soll man sehen, worum es geht - NUR der Titel;
            # Tags, Datum und Dateiname warten auf die Prüfung
            if (entscheidung.get("titel") or "").strip():
                felder["title"] = entscheidung["titel"]
            PDFHandler.write_custom_metadata(pdf_path, felder, still=True)
            ziel = os.path.join(unsicher_ordner, os.path.basename(pdf_path))

        # Liegt die Datei bereits korrekt benannt am Ziel (Ablage-Vorschau über den
        # Unsicher-Ordner oder über schon abgelegten Bestand), gibt es nichts zu
        # verschieben. Ohne diese Prüfung sähe _naechster_freier_pfad die Datei SELBST
        # als Namenskonflikt und benennt sie an ihrem eigenen Namen vorbei um -
        # Nutzerfund 06.09.2026: bei jedem Durchlauf wuchs ein '_1' an ('X_1_1.pdf').
        if _gleicher_pfad(pdf_path, ziel):
            return {"erfolg": True, "neuer_pfad": pdf_path, "fehler": None}
        ziel = _naechster_freier_pfad(ziel)
        verschieben(pdf_path, ziel)
        return {"erfolg": True, "neuer_pfad": ziel, "fehler": None}
    except Exception as e:
        return {"erfolg": False, "neuer_pfad": None, "fehler": str(e)}


def pruefe_dublette_per_ki(pdf_neu, pdf_alt, base_url, model):
    """
    KI-Zweitprüfung eines Dubletten-Verdachts (Nutzer-Entscheidung 06.09.2026): rendert
    Seite 1 beider Dokumente und lässt das Vision-Modell die konkreten Angaben
    (Rechnungsnummer, Datum, Beträge) vergleichen - genau das, was die deterministische
    Text-/Bild-Ähnlichkeit nicht kann. Liefert das Antwort-Dict von
    ollama_client.pruefe_dublette oder None, wenn eine Seite nicht darstellbar ist.
    Wirft Verbindungs-/Server-Fehler weiter; was mit der Antwort passiert, entscheidet
    dubletten_pruefung.pruefe_entscheidung (nur ein klares 'nein' zählt).
    """
    bild_neu = PDFHandler.render_page_png(pdf_neu)
    bild_alt = PDFHandler.render_page_png(pdf_alt)
    if bild_neu is None or bild_alt is None:
        return None
    return ollama_client.pruefe_dublette(bild_neu, bild_alt, base_url=base_url, model=model)


def analysiere_dokument(pdf_path, known_tags, vorhandene_ordner, base_url, model, vocabulary=None, aliase=None,
                        kategorien=None, ignorierte_tags=None, tag_eltern=None,
                        synonyme=None, entscheidungsmodell="", gedaechtnis=None, orte=None):
    """
    Komplette Analyse EINES Dokuments: Schreibschutz prüfen, Seite 1 rendern,
    KI befragen, Entscheidung bauen. Wirft Verbindungs-/Serverfehler des
    KI-Aufrufs weiter (Aufrufer entscheidet - im Batch läuft der Rest weiter,
    in der Vollautomatik bleibt das Dokument im Posteingang liegen).

    Mit entscheidungsmodell holt sie zusätzlich die Zweitmeinung zur Ordnerwahl
    (wende_zweitmeinung_an). Scheitert nur diese, bleibt es bei der Entscheidung der
    Regel-Logik (wie ohne Zweitmeinung); der Grund steht dann in "zweitmeinung_fehler".
    """
    gelesen = lies_dokument(pdf_path, known_tags, base_url, model, kategorien)
    return entscheide_gelesen(gelesen, vorhandene_ordner, base_url, vocabulary=vocabulary, aliase=aliase,
                              known_tags=known_tags, kategorien=kategorien, ignorierte_tags=ignorierte_tags,
                              tag_eltern=tag_eltern, synonyme=synonyme, entscheidungsmodell=entscheidungsmodell,
                              gedaechtnis=gedaechtnis, orte=orte)


# Die drei Bausteine von analysiere_dokument einzeln - für den Stapelbetrieb je Modell
# (auto_pilot_service): erst alle Dokumente eines Stapels mit dem Lesemodell lesen, dann alle
# Zweitmeinungen mit dem Entscheidungsmodell holen, dann der Reihe nach entscheiden und ablegen.
# Beide Modelle passen nicht gleichzeitig in 16 GB - je Dokument gewechselt, lud Ollama jedes
# Mal neu (~22 s statt ~9 s je Dokument, Modell-Prüfstand 27.10.2026).

def lies_dokument(pdf_path, known_tags, base_url, model, kategorien=None):
    """
    Lesemodell-Teil: Schreibschutz prüfen, Seite 1 rendern, KI befragen. Wirft Verbindungs-/
    Serverfehler des KI-Aufrufs weiter. :return: {"pdf_path", "schreibschutz", "png", "ki_antwort"}
    (png None = Seite nicht darstellbar, dann ohne KI-Aufruf)
    """
    schreibschutz = PDFHandler.get_write_protection(pdf_path)
    png = PDFHandler.render_page_png(pdf_path)
    ki_antwort = None
    if png is not None:
        ki_antwort = ollama_client.suggest_filing(
            png, known_tags=known_tags, base_url=base_url, model=model, kategorien=kategorien)
        ki_antwort = mit_mailkopf(ki_antwort, PDFHandler.get_metadata(pdf_path))
    return {"pdf_path": pdf_path, "schreibschutz": schreibschutz, "png": png, "ki_antwort": ki_antwort}


def mit_mailkopf(ki_antwort, meta):
    """Mail-PDF (KID_MAILID, Mail-Import 04.11.2026): Datum und Gegenüber stehen im Mailkopf fest - sie gehen dem
    KI-Lesewert vor (Konzept „Ablage“: sicherer als bei Scans; die KI las sonst auch ein Datum aus dem Text oder
    bei gesendeten Mails den eigenen Namen als Absender). Ein PDF-Anhang (KID_MAILID ohne KID_RICHTUNG) gilt wie ein
    Scan: eine weitergeleitete Rechnung gehört zu ihrem Aussteller - das Gegenüber der Mail nur, wenn auf dem Dokument
    kein brauchbarer Absender zu lesen ist (leer, nur ein Kürzel, unter drei Buchstaben). `absender_aus_mailkopf` lockert in baue_entscheidung die Sperre für kurze Namen: Im Kopf
    steht der Name fest, er ist kein Lesefehler. Andere PDFs unverändert."""
    if not isinstance(ki_antwort, dict) or not (meta or {}).get("KID_MailID"):
        return ki_antwort
    neu = dict(ki_antwort)
    if not meta.get("KID_Richtung"):
        if meta.get("KID_Absender") and _absender_unbrauchbar(neu.get("absender")):
            neu["absender"] = meta["KID_Absender"]
            neu["absender_aus_mailkopf"] = True
        # das Mail-Datum nur als Ersatz: das Dokumentdatum einer Rechnung steht auf der Rechnung
        if meta.get("KID_DokumentenDatum") and not _datum_ist_plausibel(normalisiere_datum(neu.get("datum"))):
            neu["datum"] = meta["KID_DokumentenDatum"]
        return neu
    if meta.get("KID_DokumentenDatum"):
        neu["datum"] = meta["KID_DokumentenDatum"]
    if meta.get("KID_Absender"):
        neu["absender"] = meta["KID_Absender"]   # der KI-Ordnername gilt nur, wenn er dazu passt (baue_entscheidung)
        neu["absender_aus_mailkopf"] = True
    if meta.get("KID_Einzeln"):
        neu["einzelne_mail"] = True              # vom Import gesetzt, er kennt alle Mails des Laufs (E17)
    if meta.get("KID_Eigen"):
        if isinstance(neu.get("tags"), list):
            neu["tags"] = ohne_eigene_namen(neu["tags"], meta["KID_Eigen"])
        if neu.get("empfaenger"):                # der Hauptweg: Daraus macht tags_mit_empfaenger Personen-Tags
            neu["empfaenger"] = "; ".join(ohne_eigene_namen(teile_empfaenger(neu["empfaenger"]), meta["KID_Eigen"]))
    return neu


def _absender_unbrauchbar(absender):
    """Taugt der gelesene Absender nicht für einen Ordner? Leer, reines Kürzel oder zu kurz (wie in baue_entscheidung)."""
    name, _ = trenne_adresszeile(absender)
    return (not name or absender_ist_kuerzel(name)
            or len(kernname(bereinige_ordnername(name))) < MIN_NEUER_ORDNER)


def braucht_zweitmeinung(entscheidung):
    """Bekommt diese Entscheidung eine Zweitmeinung zur Ordnerwahl? (sicher oder nur wegen des Ordners
    unsicher - aber nie bei Alias- oder Gedächtnis-Ordnern, die gelten ohnehin)"""
    if entscheidung.get("ordner_per_alias") or entscheidung.get("ordner_gedaechtnis") or entscheidung.get("ordner_sammel"):
        return False
    return entscheidung["sicher"] or any(p.startswith(_ORDNER_PROBLEM_PRAEFIXE) for p in entscheidung["probleme"])


def hole_zweitmeinung(gelesen, vorhandene_ordner, base_url, entscheidungsmodell):
    """Entscheidungsmodell-Teil: Rangliste [(ordner, p), ...] zur Seite 1 des gelesenen Dokuments.
    Wirft Fehler weiter."""
    return ollama_client.waehle_ordner(gelesen["png"], ordner_fuer_zweitmeinung(vorhandene_ordner),
                                       base_url=base_url, model=entscheidungsmodell)


def entscheide_gelesen(gelesen, vorhandene_ordner, base_url, vocabulary=None, aliase=None, known_tags=None,
                       kategorien=None, ignorierte_tags=None, tag_eltern=None,
                       synonyme=None, entscheidungsmodell="", gedaechtnis=None, rangliste=None,
                       orte=None):
    """
    Entscheidung aus einem gelesenen Dokument (lies_dokument) bauen und - mit entscheidungsmodell -
    die Zweitmeinung verrechnen. Eine im Stapel schon geholte Zweitmeinung kommt als rangliste
    (Liste oder Exception); fehlt sie, wird sie hier geholt. Scheitert nur die Zweitmeinung, bleibt
    es bei der Regel-Logik, der Grund steht in "zweitmeinung_fehler".
    """
    if gelesen["png"] is None:
        return {
            "pdf_path": gelesen["pdf_path"], "titel": "", "titel_korrekturen": [], "tags": [], "tag_ersetzungen": [],
            "neue_tags": [], "datum": "",
            "absender": "", "ordnername": "", "zielordner": "", "ordner_neu": False,
            "ordner_per_alias": False, "ordner_gedaechtnis": 0, "objekte": [], "ordner_hinweis": "", "neuer_dateiname": "", "sicher": False,
            "probleme": ["Seite 1 nicht darstellbar (beschädigt oder geschützt?)"],
        }
    entscheidung = baue_entscheidung(gelesen["pdf_path"], gelesen["ki_antwort"], vorhandene_ordner,
                                     schreibschutz=gelesen["schreibschutz"], vocabulary=vocabulary, aliase=aliase,
                                     known_tags=known_tags, kategorien=kategorien, ignorierte_tags=ignorierte_tags,
                                     tag_eltern=tag_eltern, synonyme=synonyme, gedaechtnis=gedaechtnis, orte=orte)
    if entscheidungsmodell and braucht_zweitmeinung(entscheidung):
        try:
            if rangliste is None:
                rangliste = hole_zweitmeinung(gelesen, vorhandene_ordner, base_url, entscheidungsmodell)
            if isinstance(rangliste, Exception):
                raise rangliste
            entscheidung = wende_zweitmeinung_an(entscheidung, rangliste, vorhandene_ordner)
        except Exception as e:
            entscheidung = dict(entscheidung, zweitmeinung_fehler=str(e))
    return entscheidung


def zweitmeinungen_fuer_stapel(stapel, vorhandene_ordner, base_url, entscheidungsmodell, abbrechen=None,
                               vor_abruf=None, **regeln):
    """
    Phase 2 des Stapelbetriebs je Modell (28.10.2026, Vollautomatik und Ablage-Vorschau): für jedes
    gelesene Dokument (lies_dokument), das nach dem jetzigen Stand eine Zweitmeinung braucht, das
    Entscheidungsmodell fragen - alle am Stück, damit Ollama nicht je Dokument das Modell wechselt.
    :param stapel: Liste gelesener Dokumente
    :param abbrechen: optional () -> True bricht ab
    :param vor_abruf: optional (gelesen) -> None, vor jeder Abfrage (Statusanzeige)
    :param regeln: übrige Argumente von entscheide_gelesen (known_tags, aliase, gedaechtnis, ...)
    :return: {pdf_path: rangliste oder Exception}
    """
    ranglisten = {}
    if not entscheidungsmodell:
        return ranglisten
    for gelesen in stapel:
        if abbrechen and abbrechen():
            break
        if gelesen.get("png") is None:
            continue
        if not braucht_zweitmeinung(entscheide_gelesen(gelesen, vorhandene_ordner, base_url, **regeln)):
            continue
        if vor_abruf:
            vor_abruf(gelesen)
        try:
            ranglisten[gelesen["pdf_path"]] = hole_zweitmeinung(gelesen, vorhandene_ordner, base_url,
                                                                entscheidungsmodell)
        except Exception as e:
            ranglisten[gelesen["pdf_path"]] = e
    return ranglisten


def entscheide_im_stapel(gelesen, vorhandene_ordner, base_url, entscheidungsmodell="", rangliste=None,
                         ordner_stand=None, **regeln):
    """
    Phase 3 des Stapelbetriebs: wie entscheide_gelesen mit der in Phase 2 geholten Rangliste.
    :param ordner_stand: Länge der Ordnerliste, als die Rangliste geholt wurde. Sind seitdem im selben
        Stapel neue Ordner entstanden und will dieses Dokument wieder einen NEUEN Ordner anlegen, wird
        die Zweitmeinung mit der aktuellen Liste neu geholt - sonst kann das Entscheidungsmodell den
        gerade angelegten Zwilling nicht nennen (Messlauf 28.10.2026: sicher „Bayerische Vers.kammer“
        neben dem zwei Dokumente älteren „Versicherungskasse Musterland“).
    """
    if rangliste is not None and ordner_stand is not None and len(vorhandene_ordner) > ordner_stand:
        if entscheide_gelesen(gelesen, vorhandene_ordner, base_url, **regeln)["ordner_neu"]:
            rangliste = None
    return entscheide_gelesen(gelesen, vorhandene_ordner, base_url, entscheidungsmodell=entscheidungsmodell,
                              rangliste=rangliste, **regeln)
