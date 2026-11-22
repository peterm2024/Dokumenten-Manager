"""
Namen NEUER Ordner der Vollautomatik bereinigen (Frisch-Versuch 20./21.11.2026, Etappe 13 - Peter: „Ja mach“).

Ein Ordnername bleibt für Jahre. In drei frischen KIDs hießen neue Ordner je nach Laune der KI „Haustechnik
Mustergültig“ oder „… GmbH“, „TSV Musterstadt 1890 e.V“ (Windows verschluckt den Schlusspunkt), „Musterdorf, Autohaus
(Service)“ (eine Firma in Telefonbuch-Form, dadurch unter K-O statt A-E) oder trugen Lesefehler der KI („Haustchnik“,
„Beispielm ann“), obwohl die Textebene des Scans das Wort richtig enthielt. Drei Regeln, alle deterministisch:

- `ohne_rechtsform`: GmbH, AG, eG, e.V., KG, … am Ende weg - ein Mensch nennt den Ordner „Musterversicherung“.
- `ist_firma_in_telefonbuchform`: „Nachname, Vorname (Rolle)“ nur für Personen; bei einer Firma gilt der Absender.
- `schreibweise_aus_text`: Ein Wort des Namens, das nicht in der Textebene steht, bekommt die Schreibweise eines
  fast gleichen Worts aus dem Text (eindeutig, gleicher Anfangsbuchstabe); zerrissene Wörter werden zusammengefügt.

Nur Standardbibliothek plus `personen_namen` (selbst nur Standardbibliothek), GUI-frei (tests/test_modulgrenzen.py).
"""
import re

from personen_namen import ohne_titel

# Rechtsformen am Namensende, auch mehrere hintereinander („… GmbH & Co. KG“). Groß/klein egal, Punkte optional.
_RECHTSFORM = (r"gmbh\s*&\s*co\.?\s*(?:kgaa|kg|ohg)|ggmbh|gmbh|mbh|kgaa|kg|ohg|gbr|ag|se|eg|e\.\s?g\.?|e\.\s?v\.?"
               r"|ev|ug(?:\s*\(haftungsbeschränkt\))?|ltd\.?|inc\.?|co\.?\s*kg|partg(?:\s*mbb)?|mbb")
_RECHTSFORM_AM_ENDE = re.compile(r"(?:[\s,]+(?:" + _RECHTSFORM + r"))+\s*\.?\s*$", re.IGNORECASE)
_RECHTSFORM_WORT = re.compile(r"(?:^|[\s,])(?:" + _RECHTSFORM + r")(?=$|[\s,.])", re.IGNORECASE)

# Woran man im Vornamen-Teil einer Telefonbuch-Form eine Firma erkennt („Musterdorf, Autohaus (Service)“). Nur der
# Teil HINTER dem Komma: Nachnamen wie „Neuhaus“ oder „Bankmann“ enden ebenso.
_FIRMENWORT = re.compile(
    r"(?:haus|praxis|werk|werke|technik|service|bank|kasse|versicherung|verwaltung|amt|zentrum|klinik|apotheke|verlag"
    r"|handel|bau|markt|kanzlei|büro|studio|shop|gruppe|stiftung|verein|schule|bibliothek|gesellschaft|betrieb|dienst"
    r"|agentur|vertrieb|energie|funk|telekom|stadtwerke|versorgung)$", re.IGNORECASE)

_WORT = re.compile(r"[A-Za-zÄÖÜäöüß]{4,}")
_TOKEN = re.compile(r"^(\W*)([A-Za-zÄÖÜäöüß]+)(\W*)$")
MIN_KORREKTUR_LAENGE = 5      # kürzere Wörter („Bank“, „Amt“) nicht unscharf ersetzen
MIN_TEILLAENGE = 3            # zerrissene Wörter nur aus Teilen dieser Länge zusammenfügen
MAX_TEXTWOERTER = 3000        # reicht für mehrseitige Briefe; Kontoauszüge mit 20 Seiten brauchen das nicht alles


def ohne_rechtsform(name):
    """'Musterversicherung AG' -> 'Musterversicherung', 'TSV Musterstadt 1890 e.V.' -> 'TSV Musterstadt 1890'.
    Bliebe weniger als zwei Zeichen übrig, bleibt der Name unverändert."""
    neu = _RECHTSFORM_AM_ENDE.sub("", name or "").strip(" ,.-&")
    return neu if len(neu) >= 2 else (name or "")


def ist_firma_in_telefonbuchform(ordnername, absender):
    """
    True, wenn die KI eine Firma als 'Nachname, Vorname' liefert ('Musterdorf, Autohaus (Service)' für 'Autohaus
    Musterdorf GmbH'). Die Telefonbuch-Form ist für Personen gedacht ('Carius, Dr. Emil (Zahnarzt)'): Trägt der
    Absender eine Rechtsform oder Ziffern oder ist der Vornamen-Teil ein Firmenwort, gilt sie nicht.
    """
    if "," not in (ordnername or ""):
        return False
    # Nur die Rechtsform zählt, nicht die Länge: 'Dr. Emil Carius Dr. Maximilian Carius' (Gemeinschaftspraxis) hat
    # mehr Wörter, als ist_personenname einer Person zutraut, und bleibt trotzdem 'Carius, Dr. Emil (Zahnarzt)'
    if _RECHTSFORM_WORT.search(absender or ""):
        return True
    vorname = ohne_titel(re.sub(r"\(.*?\)", " ", ordnername.split(",", 1)[1]))
    return any(_FIRMENWORT.search(w) for w in vorname.split())


def textwoerter(text):
    """Wörter der Textebene ab 4 Buchstaben, jede Schreibweise einmal - klein und JSON-fähig, damit sie in `gelesen`
    mitreisen (auto_pilot.lies_dokument). Leer ohne Textebene."""
    gesehen = {}
    for w in _WORT.findall(text or ""):
        gesehen.setdefault(w, None)
        if len(gesehen) >= MAX_TEXTWOERTER:
            break
    return list(gesehen)


def _abstand(a, b, grenze):
    """Editierabstand von a und b, oder grenze + 1, sobald er grenze überschreitet."""
    if abs(len(a) - len(b)) > grenze:
        return grenze + 1
    vorher = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        jetzt = [i]
        for j, y in enumerate(b, 1):
            jetzt.append(min(vorher[j] + 1, jetzt[j - 1] + 1, vorher[j - 1] + (x != y)))
        if min(jetzt) > grenze:
            return grenze + 1
        vorher = jetzt
    return vorher[-1]


def _schreibweisen(woerter):
    """{kleingeschrieben: Schreibweise im Text} - eine nicht durchgehend GROSS geschriebene Form hat Vorrang
    (Briefköpfe schreiben Namen oft in Versalien)."""
    form = {}
    for w in woerter or ():
        k = w.casefold()
        if k not in form or (form[k].isupper() and not w.isupper()):
            form[k] = w
    return form


def _wie(vorlage, wort):
    """Schreibweise aus dem Text, aber nicht lauter als die KI: 'HAUSTECHNIK' für 'Haustchnik' -> 'Haustechnik'."""
    if wort.isupper() and not vorlage.isupper():
        return wort[:1] + wort[1:].lower()
    return wort


def schreibweise_aus_text(name, woerter):
    """
    'Haustchnik Mustergültig GmbH' -> 'Haustechnik Mustergültig GmbH', 'Beispielm ann, Kai' -> 'Beispielmann, Kai',
    wenn die Textebene 'Haustechnik' bzw. 'Beispielmann' enthält. Ohne Textebene (woerter leer) unverändert.
    Ersetzt wird nur ein Wort ab MIN_KORREKTUR_LAENGE Buchstaben, das selbst nicht im Text steht, durch das EINZIGE
    Textwort mit gleichem Anfangsbuchstaben und Abstand 1 (ab 8 Buchstaben: 2).
    """
    form = _schreibweisen(woerter)
    if not name or not form:
        return name or ""
    teile = name.split(" ")
    # Der Klammerzusatz („(Zimmerer)“, „(Hausarzt)“) ist die Beschreibung der KI, kein Wort aus dem Brief - bleibt.
    tiefe, zerlegt = 0, []
    for t in teile:
        zerlegt.append(_TOKEN.match(t) if tiefe == 0 and "(" not in t else None)
        tiefe += t.count("(") - t.count(")")
    aus, i = [], 0
    while i < len(teile):
        a = zerlegt[i]
        b = zerlegt[i + 1] if i + 1 < len(teile) else None
        # Zusammenfügen nur aus Teilen ab MIN_TEILLAENGE: „Beispielm ann“, „Vor sorgekasse“ - aber nicht „Q wie“ (ein
        # Logo „QWIE“ steht so im Text; so ein Fall im Korpus 21.11.2026)
        if a and b and not a[3] and not b[1] and min(len(a[2]), len(b[2])) >= MIN_TEILLAENGE:
            zusammen = (a[2] + b[2]).casefold()
            if zusammen in form and a[2].casefold() not in form and b[2].casefold() not in form:
                aus.append(a[1] + _wie(a[2], form[zusammen]) + b[3])
                i += 2
                continue
        if a and len(a[2]) >= MIN_KORREKTUR_LAENGE and a[2].casefold() not in form:
            wort = a[2].casefold()
            grenze = 2 if len(wort) >= 8 else 1
            kandidaten = [k for k in form if k[:1] == wort[:1] and _abstand(wort, k, grenze) <= grenze]
            if len(kandidaten) == 1:
                aus.append(a[1] + _wie(a[2], form[kandidaten[0]]) + a[3])
                i += 1
                continue
        aus.append(teile[i])
        i += 1
    return " ".join(aus)
