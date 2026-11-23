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

Dazu seit 22.11.2026 die Arzt-Ordner „Dr. Nachname, Vorname (Fachrichtung)“ (`arzt_im_text`, `arzt_ordner`, unten).

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


# ---------------------------------------------------------------------------------------------------------------------
# Arzt-Ordner (Peter 22.11.2026, Dreifach-Vergleich Etappe 13): „Dr. Nachname, Vorname (Fachrichtung)“. „Gerade die
# Ärzte, die man selten besucht, findet man so schneller … normalerweise sucht kein Mensch nach ‚Hausarztpraxis am
# Markt‘, sondern geht gleich nach dem Namen oder der Fachrichtung. Durch das ‚Dr.‘ am Anfang sind die meisten Ärzte
# zusätzlich vorsortiert.“ Die KI nannte alle drei Arztbriefe des Prüfsatzes nach der Praxis. Entscheidungen Peter:
# Hausarzt ohne Fachrichtung, Fachärzte, Zahn- und Tierärzte mit; das „Dr.“ nur bei Ärzten nach vorn (andere Personen
# bleiben in Telefonbuch-Form „Kehr, Dr. Anna (Rechtsanwältin)“).

# „Dr. med. Eva Beispiel“, „Dr. med. vet. Jana Probst“, „Dr. med. dent. …“; im Scan auch „Dr, med. vet Jana“. Nur mit
# „med.“ - erst das macht den Doktor zum Arzt (Dr. jur., Dr. rer. nat. und ein bloßes „Dr.“ bleiben außen vor).
_NAME_TEIL = r"[A-ZÄÖÜ][a-zäöüß]+(?:-[A-ZÄÖÜ][a-zäöüß]+)?"
_ARZT_IM_TEXT = re.compile(r"\bDr[.,]?\s*med[.,]?\s*(?:(vet|dent)[.,]?\s*)?(?:univ[.,]?\s*)?(" + _NAME_TEIL + r")[ \t]+("
                           + _NAME_TEIL + r")\b")
# „Fachärztin für Innere Medizin und Kardiologie“: bis zum Zeilenende bzw. Satzzeichen, höchstens vier Wörter
_FACHARZT_FUER = re.compile(r"Fach(?:ärztin|arzt)[ \t]+für[ \t]+([A-ZÄÖÜ][A-Za-zÄÖÜäöüß-]*"
                            r"(?:[ \t]+[A-Za-zÄÖÜäöüß-]+){0,3})")
# Allgemeinmedizin am Anfang der Fachrichtung = Hausarzt, auch wenn auf derselben Zeile noch etwas folgt
_ALLGEMEIN_VORN = re.compile(r"^(?:innere\s+(?:medizin\s+)?und\s+)?allgemeinmedizin\b", re.IGNORECASE)
# Hausarzt = ohne Fachrichtung (Peter: „Dr. Beispiel, Eva“)
_HAUSARZT = re.compile(r"^(?:haus(?:arzt|ärztin)|allgemein(?:medizin|arzt|ärztin)|praktische[rn]?\s+(?:arzt|ärztin)"
                       r"|(?:fach)?(?:arzt|ärztin)\s+für\s+(?:innere\s+(?:medizin\s+)?und\s+)?allgemeinmedizin"
                       r"|innere\s+(?:medizin\s+)?und\s+allgemeinmedizin)$", re.IGNORECASE)
_TIERARZT = re.compile(r"tier(?:arzt|ärzt)", re.IGNORECASE)
_ZAHNARZT = re.compile(r"zahn(?:arzt|ärzt)", re.IGNORECASE)
_ARZTWORT = re.compile(r"arzt|ärzt|praxis|medizin", re.IGNORECASE)
_TELEFONBUCH_ARZT = re.compile(r"^\s*([^,()]+?)\s*,\s*Dr[.,]?\s*(?:med[.,]?\s*)?(?:(?:vet|dent)[.,]?\s*)?([^,()]+?)\s*"
                               r"\(([^()]+)\)\s*$")


def fachrichtung(beschreibung):
    """'Fachärztin für Dermatologie' -> 'Dermatologie', 'Tierärztin' -> 'Tierarzt', 'Zahnärztin' -> 'Zahnarzt',
    'Hausärztin'/'Allgemeinmedizin' -> '' (Hausarzt ohne Klammer), sonst die Beschreibung mit männlicher Berufsform
    ('Kinderärztin' -> 'Kinderarzt'). Rein."""
    text = " ".join((beschreibung or "").split())
    if not text or _HAUSARZT.match(text):
        return ""
    if _TIERARZT.search(text):
        return "Tierarzt"
    if _ZAHNARZT.search(text):
        return "Zahnarzt"
    m = _FACHARZT_FUER.search(text)
    if m:
        return "" if _ALLGEMEIN_VORN.match(m.group(1)) else m.group(1)
    return re.sub(r"ärztin\b", "arzt", text)


def arzt_im_text(text):
    """
    Die Ärztin/der Arzt eines Arztbriefs aus der Textebene: {"vorname", "nachname", "fach"} oder None. Gezählt werden
    alle „Dr. med. Vorname Nachname“; es gilt der häufigste Name (Briefkopf + Unterschrift schlagen den Kollegen der
    Gemeinschaftspraxis), bei Gleichstand keiner - dann bleibt der Praxisname. Fach: „med. vet.“ -> Tierarzt,
    „med. dent.“ -> Zahnarzt, sonst „Facharzt/Fachärztin für …“ bzw. Tierärztin/Zahnarzt im Text (siehe fachrichtung).
    JSON-fähig, reist wie `textwoerter` in `gelesen` mit. Rein.
    """
    zaehler, art = {}, {}
    for m in _ARZT_IM_TEXT.finditer(text or ""):
        name = (m.group(2), m.group(3))
        zaehler[name] = zaehler.get(name, 0) + 1
        if m.group(1):
            art[name] = m.group(1).lower()
    if not zaehler:
        return None
    rang = sorted(zaehler.items(), key=lambda kv: -kv[1])
    if len(rang) > 1 and rang[0][1] == rang[1][1]:
        return None
    (vorname, nachname), _ = rang[0]
    # Reihenfolge: Titel („med. vet.“) vor „Facharzt für …“ vor einem bloßen Berufswort - ein „Zahnarzt“ im Brieftext
    # eines Hausarztes (Überweisung) macht ihn nicht zum Zahnarzt
    facharzt = _FACHARZT_FUER.search(text)
    if art.get((vorname, nachname)) == "vet":
        fach = "Tierarzt"
    elif art.get((vorname, nachname)) == "dent":
        fach = "Zahnarzt"
    elif facharzt:
        fach = fachrichtung(facharzt.group(0))
    elif _TIERARZT.search(text):
        fach = "Tierarzt"
    elif _ZAHNARZT.search(text):
        fach = "Zahnarzt"
    else:
        fach = ""
    return {"vorname": vorname, "nachname": nachname, "fach": fach}


def arzt_ordnername(nachname, vorname, fach=""):
    """'Dr. Beispiel, Eva' bzw. 'Dr. Probst, Jana (Tierarzt)'. Rein."""
    return f"Dr. {nachname}, {vorname}" + (f" ({fach})" if fach else "")


def arzt_aus_telefonbuch(ordnername):
    """Die Telefonbuch-Form der KI für eine Ärztin ('Carius, Dr. Emil (Zahnarzt)', 'Beispiel, Dr. Eva (Hausärztin)')
    in die Arzt-Form ('Dr. Carius, Emil (Zahnarzt)', 'Dr. Beispiel, Eva'). Nur mit „Dr.“ und einem Arzt-Beruf in der
    Klammer - 'Kehr, Dr. Anna (Rechtsanwältin)' und 'Kehrmann, Fritz (Kaminkehrer)' bleiben. Sonst None. Rein."""
    m = _TELEFONBUCH_ARZT.match(ordnername or "")
    if not m or not _ARZTWORT.search(m.group(3)):
        return None
    return arzt_ordnername(m.group(1), m.group(2), fachrichtung(m.group(3)))


def arzt_ordner(ordnername_ki, absender, arzt, empfaenger=""):
    """
    Ordnername für einen Arztbrief oder None (dann gilt der bisherige Weg). Aus der Textebene (`arzt`, siehe
    arzt_im_text), wenn der Absender oder der KI-Name nach Arzt/Praxis klingt oder schon die Ärztin nennt - aber nie
    die Empfängerin (ein angeschriebener Arzt steht auch als „Dr. med.“ im Text). Ohne Textebene aus der
    Telefonbuch-Form der KI (arzt_aus_telefonbuch). Rein.
    """
    if arzt:
        nachname = arzt.get("nachname", "")
        genannt = nachname and (nachname.casefold() in (ordnername_ki or "").casefold())
        if (nachname and nachname.casefold() not in (empfaenger or "").casefold()
                and (genannt or _ARZTWORT.search(absender or "") or _ARZTWORT.search(ordnername_ki or ""))):
            return arzt_ordnername(nachname, arzt.get("vorname", ""), arzt.get("fach", ""))
    return arzt_aus_telefonbuch(ordnername_ki)


def ist_arzt_ordnername(name):
    """'Dr. Beispiel, Eva (…)' - die Arzt-Form; sie sortiert unter D (auto_pilot.sortierbuchstabe). Rein."""
    return bool(re.match(r"^\s*Dr\.\s+[^,]+,", name or ""))
