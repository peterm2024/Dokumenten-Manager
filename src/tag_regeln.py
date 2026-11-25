"""
Regeln für Tags aus der KI-Antwort (aus auto_pilot ausgelagert, Etappe 14, 23.11.2026): Empfänger und Objekte als Tags,
Schreibweise nach dem Katalog, Orte und Adressen, Oberkategorien, Synonyme, unbrauchbare neue Tags. Die Vollautomatik
vergibt seit 07.11.2026 keine Tags mehr (FALLSTRICKE #120); sie nutzt diese Regeln nur als Hinweis für die Ordnerwahl und
für Vorschläge zum Anklicken. Aufrufer dürfen weiter `auto_pilot.<name>` schreiben (Weiterleitung).
"""

import os
import re

from ordner_finden import kernname
from personen_namen import (MIN_TAGLAENGE_FUZZY, ZUSTELLVERMERKE, editierdistanz_max1, finde_personen_schreibweise,
    ist_personenname, ohne_anschrift, tausche_namensform, teile_empfaenger)
from titel_datum import korrigiere_titel

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
