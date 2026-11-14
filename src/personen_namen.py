"""
Namen von Personen: Empfängerfelder zerlegen, Personennamen erkennen, Schreibweisen im Katalog wiederfinden.

Aus `auto_pilot.py` ausgelagert (07.11.2026, ARCHITEKTUR_REVIEW.md, R9), weil hier das Adressbuch andockt
(KONZEPT_ADRESSBUCH.md). Reine Namenslogik ohne Oberfläche, KI und Dateien. Welche Namen zu Tags werden, entscheidet weiter
`auto_pilot.tags_mit_empfaenger`: Dort kommen Personen, Objekte und Katalog zusammen.
"""
import re


def tausche_namensform(tag):
    """
    Tauscht Vor- und Nachname OHNE Komma: 'Hermann Mustermann' -> 'Mustermann Hermann' (das letzte
    Wort wandert nach vorn). Bewusst kommalos (Nutzerkorrektur 30.08.2026): die KI kann
    Vor-/Nachname teils nicht unterscheiden - mit automatischem Komma entstünde dann
    'Vorname, Nachname'. Das Telefonbuch-Komma ist ein eigener Schritt (wechsle_komma).
    Ein vorhandenes Komma trennt zwei Blöcke, die als Ganzes tauschen
    ('Carius, Dr. Emil' -> 'Dr. Emil Carius'). Einwortige Tags bleiben unverändert.
    """
    tag = (tag or "").strip()
    if "," in tag:
        erster, zweiter = (teil.strip() for teil in tag.split(",", 1))
        return f"{zweiter} {erster}".strip()
    woerter = tag.split()
    if len(woerter) < 2:
        return tag
    return f"{woerter[-1]} {' '.join(woerter[:-1])}"


def editierdistanz_max1(a, b):
    """True, wenn sich a und b um höchstens ein Zeichen unterscheiden (Ersetzen, Einfügen, Löschen)."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) == 1
    kurz, lang = (a, b) if len(a) < len(b) else (b, a)
    i = j = 0
    fehler = 0
    while i < len(kurz) and j < len(lang):
        if kurz[i] == lang[j]:
            i += 1
        else:
            fehler += 1
            if fehler > 1:
                return False
        j += 1
    return True


MIN_TAGLAENGE_FUZZY = 6  # kürzere Tags nicht unscharf zusammenlegen ('Auto' und 'Aue' sind zwei Dinge)


_EMPFAENGER_TRENNER = re.compile(r"\s+und\s+|\s+u\.\s+|\s*&\s*|\s*/\s*|\s*[;,]\s*|\s+\+\s+", re.IGNORECASE)

# Zustellvermerke verbinden zwei Namen, sind aber selbst keiner: der Schrägstrich in
# "c/o" ließ den Trenner-Split "Erbengemeinschaft Mustermann c/o Hermann Mustermann" in die
# wertlosen Tags "Erbengemeinschaft Mustermann c" und "o Hermann Mustermann" zerhacken
# (Kaltstart-Test 03.09.2026: 2x16 Dokumente betroffen). Sie werden deshalb VOR dem
# Zerlegen durch ein echtes Trennzeichen ersetzt - beide Namen bleiben als Tags erhalten.
ZUSTELLVERMERKE = re.compile(
    r"\bc\s*/\s*o\b"                     # c/o, C/O, c / o
    r"|\bz\.?\s*hdn?\.?(?=\s|[A-ZÄÖÜ])"  # z.Hd., z. Hdn., auch verklebt: "Z.Hd.Hermann"
    r"|\bzu\s+h(?:ä|ae)nden(?:\s+von)?\b"
    r"|\bp\.\s*adr\.?",                  # p.Adr. - Punkt Pflicht, sonst träfe es "Padre"
    re.IGNORECASE)

# Anreden vor Namen ("Herrn Hermann Mustermann", "Herrn/Frau/Firma Bichler") tragen keine
# Information und verhindern den Abgleich mit den Katalog-Namen. Bewusst eigenes Muster
# statt _ANREDEN: das ist auf Ordner-Kernnamen zugeschnitten (am Anfang verankert,
# inkl. Dr./Praxis, die hier gerade NICHT wegfallen dürfen).
_ANREDE_VOR_NAME = re.compile(r"\b(?:herrn?|frau|firma)\b\s*/?\s*", re.IGNORECASE)


def _bereinige_empfaenger(text):
    """Zustellvermerke durch ';' ersetzen, Anreden entfernen, Leerraum glätten."""
    text = ZUSTELLVERMERKE.sub(";", _ANREDE_VOR_NAME.sub(" ", text or ""))
    return " ".join(text.split()).strip("; ")


def teile_empfaenger(empfaenger, bekannte_personen=None):
    """
    Zerlegt einen Empfänger mit mehreren Personen in einzelne Namen (Nutzerfund
    30.08.2026: KI lieferte den Klumpen 'Hermann Mustermann Werner Mustermann' - als EIN Tag
    wertlos, denn die Dubletten-Unterscheidung matcht ihn mit keinem Katalog-Namen).
    Drei Stufen:
    1. echte Trennzeichen (und/u./&//,;+) - ein geteilter Nachname wird ergänzt
       ('Hermann und Werner Mustermann' -> beide mit 'Mustermann'); liefert der Split einwortige
       Teile (Telefonbuch-Form 'Mustermann, Hermann'), wird NICHT geteilt
    2. bekannte Personen-Tags des Katalogs, wenn sie den Text zusammen komplett abdecken
    3. verklebte Doppelnamen 'A Mustermann B Mustermann' (vier Wörter, gleicher Nachname)
    :return: Liste der Namen; [empfaenger] wenn nichts sicher teilbar, [] bei leer
    """
    empfaenger = _bereinige_empfaenger(empfaenger)
    if not empfaenger:
        return []
    teile = [t.strip() for t in _EMPFAENGER_TRENNER.split(empfaenger) if t.strip()]
    if len(teile) > 1:
        letzter = teile[-1].split()
        nachname = letzter[-1] if len(letzter) >= 2 else ""
        ergaenzt = [t if " " in t else f"{t} {nachname}".strip() for t in teile]
        if all(" " in t for t in ergaenzt):
            return ergaenzt
    if bekannte_personen:
        text = empfaenger.lower()
        treffer = []
        for name in bekannte_personen:
            name = (name or "").strip()
            if len(name) >= MIN_NAMENSLAENGE_EMPFAENGER and re.search(
                    r"(?<![\wäöüß])" + re.escape(name.lower()) + r"(?![\wäöüß])", text):
                treffer.append(name)
        if len(treffer) >= 2:
            woerter_der_treffer = sorted(w for name in treffer for w in name.lower().split())
            if woerter_der_treffer == sorted(text.split()):
                return treffer
    woerter = empfaenger.split()
    if len(woerter) == 4 and woerter[1].lower() == woerter[3].lower():
        return [f"{woerter[0]} {woerter[1]}", f"{woerter[2]} {woerter[3]}"]
    return [empfaenger]


MIN_NAMENSLAENGE_EMPFAENGER = 4  # wie dubletten.MIN_NAMENSLAENGE: kürzere Katalog-Namen sind zu riskant


# Verbinder, die in Personen-/Gemeinschaftsnamen nichts unterscheiden ("Mustermann Hermann & Werner"
# == "Mustermann Hermann und Werner"); Punkte/Kommas fallen ebenfalls weg ("Erbengem." == "Erbengem")
_NAMENS_FUELLWOERTER = {"und", "u", "&", "+"}

# Angeklebte Anschrift hinter einem Personennamen ("Hermann Mustermann Weidenstr. 8"): ab dem
# Straßenwort mit Hausnummer wird abgeschnitten (Neu-Einlese-Lauf 07.09.2026).
_PERSON_ADRESS_SUFFIX = re.compile(
    r"(?:^|\s+)\S*(?:str\.?|straße|strasse|weg|platz|gasse|allee|ring)\s*\d+.*$", re.IGNORECASE)


# Akademische Titel unterscheiden keine Person: 'Johann Schuff' == 'Dr. Johann Schuff'
# (Wiederholungslauf 08.09.2026 - der Katalog hatte den Arzt mit Titel, die KI las ohne).
_AKADEMISCHE_TITEL = re.compile(r"\b(?:prof|dr|dipl|ing|med|dent|jur|rer|nat|phil|habil|vet)\.?\s*|\bh\.\s*c\.\s*",
                                re.IGNORECASE)


def ohne_titel(name):
    """'Dr. med. Emil Carius' -> 'Emil Carius'; Namen ohne Titel bleiben unverändert."""
    return " ".join(_AKADEMISCHE_TITEL.sub(" ", name or "").split()).strip(" -")


def _namenswortmenge(name):
    """Wörter eines Namens als Menge, ohne Verbinder und Satzzeichen - Reihenfolge egal."""
    woerter = re.sub(r"[.,;]", " ", (name or "").lower()).split()
    return frozenset(w for w in woerter if w not in _NAMENS_FUELLWOERTER)


# Empfänger-Texte, die keine Person sind (Neu-Einlese-Lauf 07./08.09.2026): Sammelanreden
# ("An alle Haushalte der Wasserversorgung ...", "Kunden der iqua Deutschland GmbH"),
# Firmenkürzel, Ziffern (PLZ, Hausnummern, Kundennummern) und Bandwurm-Texte.
_KEINE_PERSON = re.compile(
    r"^(?:an\s+alle|alle|kunden|kundin|kunde|sehr\s+geehrte|liebe|bewohner|eigentümer|mieter)\b"
    r"|\b(?:gmbh|ag|kg|ohg|e\.?\s?v\.?|se)\b|\d", re.IGNORECASE)
MAX_PERSON_WOERTER = 5


def ist_personenname(text):
    """
    Grobe Plausibilität: ein Personen-Tag hat keine Ziffern, keine Rechtsform, keine
    Sammelanrede und höchstens MAX_PERSON_WOERTER Wörter ('Dr. Emil Carius', 'Uta
    Berta Mustermann' ja - '12345 Musterstadt', 'Kunden der iqua Deutschland GmbH' nein).
    """
    text = (text or "").strip()
    if not text or len(text.split()) > MAX_PERSON_WOERTER:
        return False
    return not _KEINE_PERSON.search(text)


def ohne_anschrift(person):
    """'Hermann Mustermann Weidenstr. 8' -> 'Hermann Mustermann'; eine reine Anschrift wird leer."""
    return _PERSON_ADRESS_SUFFIX.sub("", (person or "").strip()).strip(" ,-")


def finde_personen_schreibweise(person, katalog_namen):
    """
    Schreibweise eines Personen-Tags an den Katalog angleichen (Tag-Wildwuchs nach dem
    Praxislauf 06.09.2026: 'Mustermann Hermann' neben 'Hermann Mustermann', 'Hemann Mustermann' neben
    'Hermann Mustermann', 'Dorit Richter' neben 'Doris Richter' - für die Suche und die
    Dubletten-Unterscheidung sind das jeweils dieselbe Person, im Katalog aber getrennte
    Einträge). Stufen, die erste passende gewinnt:
    1. exakt (Groß/Klein egal) -> Katalog-Schreibweise
    2. Namensform getauscht ('Mustermann Hermann' <-> 'Hermann Mustermann')
    2b. ohne akademische Titel ('Johann Schuff' == 'Dr. Johann Schuff', Katalog-Form gewinnt)
    3. gleiche Wortmenge - Reihenfolge und Verbinder egal ('Mustermann Hermann & Werner' ==
       'Mustermann Hermann und Werner', 'Mustermann Erbengemeinschaft Hermann und Werner' ==
       'Erbengemeinschaft Mustermann Hermann Mustermann Werner Mustermann'; Neu-Einlese-Lauf 07.09.2026:
       fünf Erbengemeinschaft-Schreibweisen nebeneinander)
    4. Tippfehler: gleicher NACHNAME (letztes Wort, exakt) und Vorname in Editierdistanz
       <= 1 - nur bei mehrwortigen Namen ab MIN_TAGLAENGE_FUZZY Zeichen
    5. bloßer Nachname ('Lehmann'), wenn er im Katalog GENAU EINER mehrwortigen Person
       gehört ('Christian Lehmann'); 'Mustermann' bleibt bei mehreren Mustermann unangetastet
    Bewusst NICHT: unscharfer Nachname ('Maier' und 'Meier' sind zwei Menschen -
    Nutzerentscheidung 30.08.2026).
    :param katalog_namen: alle Katalog-Namen inkl. Struktur-Kategorien (Peters Personen
                          stehen oft als graue Knoten unter ihrer Adresse)
    :return: Katalog-Schreibweise oder None, wenn nichts passt
    """
    person = (person or "").strip()
    if not person or not katalog_namen:
        return None
    formen = [person.lower(), tausche_namensform(person).lower()]
    nach_name = {}
    for name in katalog_namen:
        name = (name or "").strip()
        if name:
            nach_name.setdefault(name.lower(), name)
    for form in formen:
        if form in nach_name:
            return nach_name[form]
    # Ohne akademische Titel vergleichen (beidseitig), Katalog-Form MIT Titel gewinnt
    nach_titel = {}
    for schluessel, original in nach_name.items():
        nach_titel.setdefault(ohne_titel(schluessel), original)
    for form in formen:
        kurz = ohne_titel(form)
        if kurz and kurz in nach_titel:
            return nach_titel[kurz]
    menge = _namenswortmenge(person)
    if len(menge) >= 2:
        for schluessel, original in nach_name.items():
            if _namenswortmenge(schluessel) == menge:
                return original
    woerter = person.lower().split()
    if len(woerter) == 1:
        nachname = woerter[0]
        if len(nachname) >= MIN_NAMENSLAENGE_EMPFAENGER:
            treffer = [original for schluessel, original in nach_name.items()
                       if len(schluessel.split()) >= 2 and schluessel.split()[-1] == nachname]
            if len(treffer) == 1:
                return treffer[0]
        return None
    if len(person) < MIN_TAGLAENGE_FUZZY:
        return None
    for form in formen:
        woerter = form.split()
        if len(woerter) < 2:
            continue
        vorname, nachname = " ".join(woerter[:-1]), woerter[-1]
        for schluessel, original in nach_name.items():
            k_woerter = schluessel.split()
            if len(k_woerter) < 2 or k_woerter[-1] != nachname:
                continue
            if editierdistanz_max1(vorname, " ".join(k_woerter[:-1])):
                return original
    return None


def ohne_eigene_namen(namen_oder_tags, eigen):
    """Ein Tag, das nur den Nutzer selbst nennt, sagt nichts (FALLSTRICKE #114). Nur der ganze Name in beliebiger Schreibweise:
    „Familie“ aus „Familie Mustermann“ bleibt stehen."""
    def worte(text):
        return frozenset(re.findall(r"\w+", text.casefold()))
    eigene = {worte(n) for n in eigen.split(";")} - {frozenset()}
    return [t for t in namen_oder_tags if worte(str(t)) not in eigene]
