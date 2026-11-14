"""
Mail lesen für den Mail-Import (KONZEPT_MAIL_IMPORT.md, Schritt 2; Code aus Spike S1 übernommen): eine Mail (.eml-
Bytes) in ihre Kopfwerte und ihren Inhalt zerlegen, Richtung und Gegenüber bestimmen, den Vorfilter ohne KI
anwenden, den Schlüssel gegen Doppelte bilden und den Inhalt als entschärftes HTML für das Mail-PDF aufbereiten
(das PDF selbst baut pdf_handler.PDFHandler.schreibe_mail_pdf). Eingänge .eml und mbox hier, .pst in mail_pst.py.

GUI-frei, nur Standardbibliothek. Kaputte Mails werfen nie: was nicht lesbar ist, steht in `probleme`.
"""

import datetime
import hashlib
import html
import os
import re
from email import policy
from email.header import decode_header
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser

BETREFF_PRAEFIX = re.compile(r"^\s*((AW|RE|WG|FW|FWD|Antw|Antwort)\s*(\[\d+\])?\s*:\s*)+", re.IGNORECASE)

# Ordner, deren Inhalt nie übernommen wird (Server, Outlook, Thunderbird; deutsch und englisch)
ORDNER_RAUS = re.compile(r"(^|[\\/])\s*(spam|junk|junk-e-mail|junk e-mail|junk-mail|bulk mail|gelöschte elemente|"
                         r"gelöschte objekte|deleted items|deleted messages|papierkorb|trash|müll)\s*$", re.IGNORECASE)
# Was hier liegt, wurde nie abgeschickt (Peter 05.11.2026). Gilt nur für den Ordner selbst, wie ORDNER_RAUS: „Entwürfe
# Haus“ und Unterordner von „Vorlagen“ bleiben drin. Ein eigener Ordner „Kunden/Vorlagen“ fällt mit heraus, sein Grund
# steht in den Zahlen, und eine Entscheidung von Hand geht vor.
ORDNER_ENTWURF = re.compile(r"(^|[\\/])\s*(entwürfe|entwurf|drafts|draft|vorlagen|templates)\s*$", re.IGNORECASE)
GRUND_ENTWURF = "Entwürfe oder Vorlagen"
# Gesendete Mails: wer dort als Absender steht, ist der Nutzer selbst (Peter 08.11.2026: eigene Adressen nicht jedes Mal
# von Hand eintragen). Wie oben nur der Ordner selbst, Outlook deutsch/englisch, Thunderbird, Gmail („[Gmail]/Gesendet“).
ORDNER_GESENDET = re.compile(r"(^|[\\/])\s*(gesendet|gesendete elemente|gesendete objekte|gesendete nachrichten|"
                             r"sent|sent items|sent mail|sent messages|postausgang|outbox)\s*$", re.IGNORECASE)

CSS = """
* { font-family: sans-serif; font-size: 10pt; }
.kopf { border-bottom: 1px solid #888; margin-bottom: 8pt; padding-bottom: 4pt; }
.kopf .feld { color: #555; font-weight: bold; }
.betreff { font-size: 13pt; font-weight: bold; margin-bottom: 4pt; }
.zitat { color: #666; }
.anhaenge { border-top: 1px solid #888; margin-top: 10pt; padding-top: 4pt; }
.hinweis { color: #a00; }
.ersatz { color: #888; font-style: italic; }
"""


# ---------------------------------------------------------------- Kopf
def _parse(daten):
    msg = BytesParser(policy=policy.default).parsebytes(daten)
    msg.kid_roh = BytesParser(policy=policy.compat32).parsebytes(daten, headersonly=True)
    return msg


def _repariere(text):
    """Ungeschützte 8-Bit-Bytes in alten Kopfzeilen kommen als Surrogate an („M\\udcfcller“) - als cp1252 deuten,
    das war bei deutschen Mails der 2000er fast immer richtig (Spike S1). U+FFFD hat die PDF-Schrift nicht → „?“."""
    if any("\udc80" <= z <= "\udcff" for z in text):
        text = text.encode("utf-8", "surrogateescape").decode("cp1252", errors="replace")
    return text.replace("�", "?")


def _kopf(msg, name):
    """Kopfzeile als Text - kaputte Kodierungen nie als Fehler, sondern als Rohtext. policy.default macht aus
    ungeschützten 8-Bit-Bytes schon U+FFFD; dann die Zeile aus der compat32-Fassung nachlesen."""
    try:
        wert = msg.get(name)
        text = "" if wert is None else str(wert)
    except Exception:          # noqa: BLE001 - jede kaputte Kopfzeile, auch exotische Parser-Fehler
        text = "�"
    if "�" in text and getattr(msg, "kid_roh", None) is not None:
        roh = msg.kid_roh.get(name)
        if roh is not None:
            stuecke = []
            # das Header-Objekt selbst übergeben, nicht str(roh): nur so kommen die Bytes als „unknown-8bit“ an
            for teil, zs in decode_header(roh):
                if isinstance(teil, bytes):
                    zs = zs if zs and zs != "unknown-8bit" else "cp1252"
                    try:
                        teil = teil.decode(zs, errors="replace")
                    except LookupError:
                        teil = teil.decode("cp1252", errors="replace")
                stuecke.append(teil)
            text = "".join(stuecke)
    return " ".join(_repariere(text).split())


# Ein Kopf wie "Name <a@b.de>" ganz in Anführungszeichen (vorkommend in echten .pst, 08.11.2026): getaddresses liefert
# dann „Name <a@b.de>“ als Adresse - die Mail galt als eingegangen, mit dem Nutzer selbst als Gegenüber, und der
# Vorschlag eigener Adressen nannte dieselbe Adresse zweimal
_ADRESSE_INNEN = re.compile(r"^(.*?)<([^<>\s]+@[^<>\s]+)>\s*$")


def _bereinigt(name, adresse):
    """(Name, Adresse klein) - holt die Adresse aus „Name <a@b.de>“, wenn sie dort gelandet ist."""
    adresse = adresse.strip()
    innen = _ADRESSE_INNEN.match(adresse)
    if innen:
        name = name or innen.group(1).strip().strip("\"'").strip()
        adresse = innen.group(2)
    return name, adresse.lower()


def _adressen(text):
    return [_bereinigt("", a)[1] for _, a in getaddresses([text or ""]) if a and "@" in a]


def eigene_namen(mail, eigene):
    """Wie heißt der Nutzer in dieser Mail? „Name;vorname.nachname“: Anzeigenamen der eigenen Adressen und ein zweiteiliger
    Teil vor dem @ (ein Postfach wie info@ ist kein Name). Daran erkennt die Ablage ein Tag, das nur den Empfänger nennt
    (FALLSTRICKE #114)."""
    namen = []
    for name, adresse in _namen_und_adressen(mail.von) + _namen_und_adressen(mail.an) + _namen_und_adressen(mail.cc):
        if ist_eigene(adresse, eigene):
            lokal = adresse.partition("@")[0]
            namen += [n for n in (name, lokal if re.search(r"[._-]", lokal) else "") if n]
    return ";".join(dict.fromkeys(namen))


def _name_aus_kopf(name):
    """Anzeigename ohne umschließende Anführungszeichen; eine Adresse ist kein Name. Aus ihm wird ein Ordner (FALLSTRICKE #113)."""
    name = " ".join((name or "").split()).strip("'\"`´‘’“”").strip()
    return "" if "@" in name else name


def _namen_und_adressen(text):
    return [(_name_aus_kopf(n), a) for n, a in (_bereinigt(n, a) for n, a in getaddresses([text or ""]) if a and "@" in a)]


def ist_gesendet_ordner(ordner):
    """Liegt die Mail in einem Ordner für gesendete Mails (ORDNER_GESENDET)?"""
    return bool(ordner) and ORDNER_GESENDET.search(ordner.strip()) is not None


class Kopf:
    """Nur die Adresszeilen einer Mail - genug für `richtung` und `gegenueber`, wenn sich die eigenen Adressen nach dem
    Einlesen ändern (mail_import.setze_eigene), ohne die Mail neu zu lesen."""
    __slots__ = ("von", "an", "cc", "von_adressen")

    def __init__(self, von, an, cc):
        self.von, self.an, self.cc = von or "", an or "", cc or ""
        self.von_adressen = _adressen(self.von)


def ortszeit(datum):
    """Date-Kopf → Ortszeit (S1: der Kopf steht in der Zeitzone des Absenders, sonst kann der Tag kippen)."""
    if datum is None:
        return None
    if datum.tzinfo is None:
        return datum
    return datum.astimezone().replace(tzinfo=None)


def mail_id(text):
    """Message-ID vergleichbar: ohne spitze Klammern/Leerraum, klein."""
    return re.sub(r"\s+", "", str(text or "")).strip("<>").lower()


class Mail:
    """Eine gelesene Mail. `daten` = die .eml-Bytes (für das Einbetten ins PDF)."""

    def __init__(self, daten):
        self.daten = daten
        self.msg = _parse(daten)
        self._lies_kopf(lambda name: _kopf(self.msg, name))

    def _lies_kopf(self, kopf):
        """Die Felder aus den Kopfzeilen; `kopf(name)` → Text wie `_kopf`. Gemeinsam mit `KopfMail`, damit beide Wege
        dieselben Regeln haben (Titel, Datum, Adressen, Lesebestätigung)."""
        self.von = kopf("From")
        self.an = kopf("To")
        self.cc = kopf("Cc")
        self.betreff = kopf("Subject")
        self.titel = BETREFF_PRAEFIX.sub("", self.betreff).strip() or "(ohne Betreff)"
        self.message_id = mail_id(kopf("Message-ID"))
        self.datum_roh = kopf("Date")
        try:
            self.datum = ortszeit(parsedate_to_datetime(self.datum_roh)) if self.datum_roh else None
        except (TypeError, ValueError, IndexError, OverflowError):
            self.datum = None
        self.von_adressen = _adressen(self.von)
        self.an_adressen = _adressen(self.an) + _adressen(self.cc)
        self.liste = bool(kopf("List-Unsubscribe"))
        auto = kopf("Auto-Submitted").lower()
        self.automatisch = bool((auto and auto != "no") or kopf("X-Autoreply") or kopf("X-Autorespond")
                                or kopf("Precedence").lower() == "auto_reply")
        typ = kopf("Content-Type").lower()
        self.lesebestaetigung = ("disposition-notification" in typ
                                 or bool(re.match(r"(gelesen|read|lesebestätigung)\s*:", self.betreff, re.I)))
        self._koerper = None

    # ------------------------------------------------ Inhalt
    def koerper(self):
        """(art, text, cid_bilder, anhaenge, probleme) - art 'html' oder 'text'; einmal gelesen, dann gemerkt."""
        if self._koerper is None:
            self._koerper = _koerper(self.msg)
        return self._koerper

    def anhaenge_ohne_inhalt(self):
        return anhaenge_ohne_inhalt(self.msg)

    def textanfang(self, zeichen=1500):
        """Klartext für die KI-Einstufung (kein Bild, kein HTML): Betreff und Anfang des Textes."""
        art, text, _, _, _ = self.koerper()
        if art == "html":
            text = html_zu_text(text)
        return " ".join(text.split())[:zeichen]

    def schluessel(self):
        """Gegen Doppelte (Konzept „Doppelte erkennen“): die Message-ID, sonst ein Fingerabdruck aus Datum, Absender,
        Betreff und Textanfang - alte Mails haben meist keine Message-ID (S2: 2 von 238 in 2003)."""
        if self.message_id:
            return "mid:" + self.message_id
        zeit = self.datum.strftime("%Y-%m-%d %H:%M") if self.datum else self.datum_roh
        roh = "|".join([zeit or "", ",".join(sorted(self.von_adressen)), self.titel.lower(), self.textanfang(200).lower()])
        return "fp:" + hashlib.sha1(roh.encode("utf-8", "replace")).hexdigest()[:24]


def kopf_aus_text(name, roh):
    """Eine Kopfzeile als Text, wie `_kopf` sie aus einer gelesenen Mail holt - für Kopfzeilen, die nicht aus einer
    .eml kommen (`KopfMail`). Kodierte Wörter entschlüsselt dieselbe Kopfzeilen-Fabrik der Standardbibliothek."""
    try:
        text = str(policy.default.header_factory(name, roh))
    except Exception:          # noqa: BLE001 - jede kaputte Kopfzeile: dann der Rohtext
        text = roh
    return " ".join(_repariere(text).split())


class KopfMail(Mail):
    """Eine Mail aus einzelnen Kopfzeilen, Anhangnamen und auf Wunsch dem Text - ohne .eml (KONZEPT_MAIL_AUF_ABRUF S3b:
    .pst direkt, an Peters .pst gemessen 0,5 statt 2,4 ms je Kopf und 2,5 statt 7,6 ms je Text). Dieselben Felder und
    Regeln wie `Mail` über `_lies_kopf`. `daten` und `msg` gibt es nicht: Für PDF und Übernehmen liest KID die Mail
    weiter ganz (`mail_import.lade_mail`)."""

    def __init__(self, kopfzeilen, anhang_namen, text=None):
        """:param kopfzeilen: {Name klein: Rohwert}; :param anhang_namen: [Name]; :param text: (art, Text) oder None"""
        self.daten = self.msg = None
        werte = {name: kopf_aus_text(name, roh) for name, roh in kopfzeilen.items()}
        self._lies_kopf(lambda name: werte.get(name.lower(), ""))
        self._anhaenge = [{"name": _repariere(n) or "(ohne Namen)",
                           "typ": "application/pdf" if n.lower().endswith(".pdf") else "application/octet-stream",
                           "groesse": 0, "daten": b""} for n in anhang_namen]
        if text is not None:
            art, inhalt = text
            self._koerper = (art, _repariere(inhalt), {}, self._anhaenge, [])

    def koerper(self):
        if self._koerper is None:
            raise ValueError("KopfMail ohne Text")
        return self._koerper

    def anhaenge_ohne_inhalt(self):
        return self._anhaenge


def _text_von(teil, probleme):
    try:
        return teil.get_content()
    except (LookupError, UnicodeError, AssertionError, KeyError) as e:
        probleme.append(f"Zeichensatz: {e}")
        roh = teil.get_payload(decode=True) or b""
        return roh.decode("cp1252", errors="replace")


def anhaenge_ohne_inhalt(msg):
    """Die Anhänge wie in `_koerper`, aber ohne ihren Inhalt zu dekodieren (Phase 1 des Einlesens): Name und Typ,
    `daten` leer. Im Text eingebettete Bilder lassen sich ohne Text nicht erkennen und zählen hier mit."""
    try:
        teile = list(msg.iter_attachments())
    except Exception:          # noqa: BLE001
        return []
    return [{"name": _repariere(str(a.get_filename() or "")) or "(ohne Namen)", "typ": a.get_content_type(),
             "groesse": 0, "daten": b""} for a in teile]


def _koerper(msg):
    probleme = []
    try:
        teil = msg.get_body(preferencelist=("html", "plain"))
    except Exception:          # noqa: BLE001 - kaputte MIME-Struktur
        teil = None
    if teil is None:
        art, text = "text", ""
        if not msg.is_multipart() and msg.get_content_maintype() == "text":
            text = _text_von(msg, probleme)
        else:
            probleme.append("kein Text-Teil gefunden")
    else:
        art = "html" if teil.get_content_subtype() == "html" else "text"
        text = _text_von(teil, probleme)
    text = _repariere(text)
    cid_bilder = {}
    for t in msg.walk():
        cid = t.get("Content-ID")
        if cid and t.get_content_maintype() == "image":
            schluessel = str(cid).strip("<> ")
            endung = re.sub(r"\W", "", t.get_content_subtype() or "") or "png"
            cid_bilder[schluessel] = (f"cid_{len(cid_bilder)}.{endung}", t.get_payload(decode=True) or b"")
    anhaenge = []
    try:
        teile = list(msg.iter_attachments())
    except Exception:          # noqa: BLE001
        teile = []
        probleme.append("Anhänge nicht lesbar")
    for a in teile:
        cid = str(a.get("Content-ID") or "").strip("<> ")
        if cid and cid in cid_bilder and f"cid:{cid}" in text:
            continue  # im Text eingebettetes Bild, kein eigener Anhang
        try:
            daten = a.get_payload(decode=True) or b""
        except Exception:      # noqa: BLE001
            daten = b""
        name = _repariere(str(a.get_filename() or "")) or "(ohne Namen)"
        anhaenge.append({"name": name, "typ": a.get_content_type(), "groesse": len(daten), "daten": daten})
    return art, text, cid_bilder, anhaenge, probleme


# ---------------------------------------------------------------- Richtung, Gegenüber, Vorfilter
def ist_eigene(adresse, eigene):
    """`eigene` = Menge eigener Adressen, klein; ein Eintrag „@beispiel.de“ steht für die ganze Domain."""
    a = (adresse or "").lower()
    return a in eigene or any(e.startswith("@") and a.endswith(e) for e in eigene)


def richtung(mail, eigene):
    """'aus', wenn der Absender eine eigene Adresse ist (S2: Outlooks Kennzeichen „von mir“ fehlt bei archivierten
    Mails überall - die Richtung kommt allein aus der Liste eigener Adressen), sonst 'ein'."""
    return "aus" if any(ist_eigene(a, eigene) for a in mail.von_adressen) else "ein"


# gängige Mail-Anbieter: deren Domain sagt nichts über das Gegenüber
ANBIETER = {"gmail", "googlemail", "web", "gmx", "t-online", "outlook", "hotmail", "live", "yahoo", "freenet",
            "arcor", "aol", "icloud", "me", "posteo", "mailbox", "online", "email", "mail", "vivafone", "1und1"}
_ZWEITEILIGE_ENDUNGEN = {"co.uk", "org.uk", "ac.uk", "com.au", "co.at", "co.jp", "co.nz", "co.za", "com.br", "com.tr"}


_NEWSLETTER_BETREFF = re.compile(r"\bnewsletter\b", re.I)


def newsletter_adresse(adresse):
    """newsletter@…, newsletter-de@… oder eine Absenderdomain mit einem Teil, der mit „news“ beginnt (…@news.firma.de,
    …@newsletter.firma.de) - die Endung zählt nicht mit (.news gibt es)."""
    lokal, _, domain = (adresse or "").lower().rpartition("@")
    return lokal.startswith("newsletter") or any(teil.startswith("news") for teil in domain.split(".")[:-1])


def ist_newsletter(mail):
    """Peter 12.11.2026: Newsletter erkennen - am Kopf List-Unsubscribe, an der Absenderadresse (`newsletter_adresse`)
    oder am Wort „Newsletter“ im Betreff. Nur zum Ausblenden auf Wunsch, nie als Vorfilter: Shops schicken auch
    Rechnungen und Bestellbestätigungen mit List-Unsubscribe (FALLSTRICKE #101)."""
    return (mail.liste or bool(_NEWSLETTER_BETREFF.search(mail.betreff or ""))
            or any(newsletter_adresse(a) for a in mail.von_adressen))


def domain_schluessel(adresse):
    """Worauf „für die ganze Domain“ gilt: die Hauptdomain (mail.firma.de → @firma.de). Die Unterdomain eines
    Mail-Anbieters bleibt, wie sie ist: Newsletter von mailings.web.de dürfen nicht alle Freunde bei web.de treffen."""
    domain = adresse.lower().rpartition("@")[2]
    teile = domain.split(".")
    stamm = teile[-3:] if ".".join(teile[-2:]) in _ZWEITEILIGE_ENDUNGEN else teile[-2:]
    return "@" + (domain if stamm[0] in ANBIETER else ".".join(stamm))


def gegenueber(mail, eigene):
    """(Name, Adresse) des Gegenübers: bei eingehenden Mails der Absender, bei gesendeten der erste fremde Empfänger.
    Ohne Adresse ("", "")."""
    if richtung(mail, eigene) == "aus":
        kandidaten = _namen_und_adressen(mail.an) + _namen_und_adressen(mail.cc)
    else:
        kandidaten = _namen_und_adressen(mail.von)
    for name, adresse in kandidaten:
        if not ist_eigene(adresse, eigene):
            return name, adresse
    return ("", "")


def vorfilter(mail, ordner=""):
    """Grund, warum die Mail ohne KI herausfällt, sonst "" (Konzept Schritt 4). No-Reply-Absender fallen bewusst
    NICHT heraus: Shops schicken Bestellungen und Rechnungen von solchen Adressen (Peter 30.10.2026). Dasselbe gilt für
    Abmeldelink (List-Unsubscribe) und Kennung „automatisch“: Bestellbestätigungen, AGB-Änderungen und Antworten eines
    Ticket-Systems tragen sie auch - darüber urteilt die KI am Text (Peter 05.11.2026, T20.4, FALLSTRICKE #101)."""
    if ordner and ORDNER_RAUS.search(ordner.strip()):
        return "Spam- oder Papierkorb-Ordner"
    if ordner and ORDNER_ENTWURF.search(ordner.strip()):
        return GRUND_ENTWURF
    if mail.lesebestaetigung:
        return "Lesebestätigung"
    return ""


# ---------------------------------------------------------------- Eingänge .eml und mbox
def eml_dateien(pfad):
    """Alle .eml unter einer Datei oder einem Ordner, sortiert."""
    if os.path.isfile(pfad):
        return [pfad]
    funde = []
    for wurzel, _, dateien in os.walk(pfad):
        funde += [os.path.join(wurzel, d) for d in dateien if d.lower().endswith(".eml")]
    return sorted(funde)


def ist_mbox(pfad):
    """mbox erkennt man am Inhalt („From “ am Anfang), nicht an der Endung - Thunderbird-Dateien haben keine."""
    try:
        with open(pfad, "rb") as f:
            return f.read(5) == b"From "
    except OSError:
        return False


# Trennzeile einer mbox: „From - Fri Mar 01 10:00:00 2024“, „From a@b Fri Mar  1 10:00:00 +0100 2024“. Eine Zeile „From
# Hamburg nach Berlin“ im Mailtext trennt nichts: mailbox.mbox zerlegte die Mail dort (FALLSTRICKE #105). Bewusst
# großzügig, weil eine zu strenge Regel Mails verschmelzen würde: Wochentag, Tag und Monat, Uhrzeit; die Zeile muss
# das Datum nicht am Ende tragen.
_MONATE = rb"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
_MBOX_TRENNER = re.compile(rb"^From .*?\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun),? +(?:" + _MONATE + rb" +\d{1,2}|\d{1,2} +"
                           + _MONATE + rb")(?: +\d{4})? +\d{1,2}:\d{2}")
ZAHL_FROM_IM_TEXT = "From-Zeilen im Mailtext"


def _ohne_letzte_leerzeile(zeilen):
    """Die Leerzeile vor der nächsten Trennzeile gehört zur mbox, nicht zur Mail."""
    if zeilen and zeilen[-1] in (b"\n", b"\r\n"):
        zeilen = zeilen[:-1]
    return b"".join(zeilen)


def mbox_mails(pfad, zahlen=None):
    """
    (Ort, Bytes) je Mail einer mbox-Datei, zeilenweise: eine Thunderbird-Datei kann viele GB groß sein. Ort ist die
    Byte-Position der Trennzeile (für mbox_mail).
    :param zahlen: Counter; zählt „From “-Zeilen im Text. Viele davon bei wenigen Mails hieße, dass diese Datei
                   eine unbekannte Trennzeile benutzt - der Nutzer sieht die Zahl, statt dass Mails still verschmelzen.
    """
    position = 0
    start = None
    zeilen = []
    with open(pfad, "rb") as f:
        for zeile in f:
            if start is None and zeile.startswith(b"From "):      # die erste Zeile der Datei trennt immer
                start = position
            elif zeile.startswith(b"From "):
                if _MBOX_TRENNER.match(zeile):
                    yield str(start), _ohne_letzte_leerzeile(zeilen)
                    start, zeilen = position, []
                else:
                    if zahlen is not None:
                        zahlen[ZAHL_FROM_IM_TEXT] += 1
                    zeilen.append(zeile)
            elif start is not None:
                zeilen.append(zeile)
            position += len(zeile)
    if start is not None:
        yield str(start), _ohne_letzte_leerzeile(zeilen)


def mbox_mail(pfad, ort):
    """Die eine Mail an der Byte-Position `ort` aus mbox_mails."""
    zeilen = []
    with open(pfad, "rb") as f:
        f.seek(int(ort))
        f.readline()
        for zeile in f:
            if _MBOX_TRENNER.match(zeile):
                break
            zeilen.append(zeile)
    return _ohne_letzte_leerzeile(zeilen)


# Thunderbird merkt sich den Zustand einer Mail im Kopf (nsMsgMessageFlags). Gelöschte bleiben bis zum Komprimieren in
# der Datei und kämen sonst wieder (Spike S5).
_MOZ_STATUS = re.compile(rb"^X-Mozilla-Status: *([0-9a-fA-F]{1,4})\s*$", re.M)
_MOZ_STATUS2 = re.compile(rb"^X-Mozilla-Status2: *([0-9a-fA-F]{1,8})\s*$", re.M)
_MOZ_GELOESCHT, _MOZ_TEILWEISE, _MOZ_AUF_SERVER_GELOESCHT = 0x0008, 0x0400, 0x00200000
GELOESCHT, TEILWEISE = "im Mail-Programm gelöscht", "nur teilweise geladen"


def mozilla_zustand(daten):
    """GELOESCHT, TEILWEISE (Text fehlt, der Kopf ist da) oder ""; sieht nur den Mailkopf an."""
    ende = daten.find(b"\n\n")
    ende_crlf = daten.find(b"\r\n\r\n")
    kopf = daten[:min(e for e in (ende, ende_crlf, len(daten)) if e >= 0)]
    status = _MOZ_STATUS.search(kopf)
    status2 = _MOZ_STATUS2.search(kopf)
    wert = int(status.group(1), 16) if status else 0
    wert2 = int(status2.group(1), 16) if status2 else 0
    if wert & _MOZ_GELOESCHT or wert2 & _MOZ_AUF_SERVER_GELOESCHT:
        return GELOESCHT
    return TEILWEISE if wert & _MOZ_TEILWEISE else ""


# ---------------------------------------------------------------- HTML entschärfen und Seite aufbauen
LANGES_WORT = re.compile(r"\S{61,}")


def brich_lange_woerter(text):
    """Wörter über 60 Zeichen (meist Links) alle 40 Zeichen mit U+200B umbrechbar machen - Story bricht sonst nicht
    und schreibt über den Seitenrand (Spike S1)."""
    return LANGES_WORT.sub(lambda m: "​".join(m.group(0)[i:i + 40] for i in range(0, len(m.group(0)), 40)), text)


def _ohne_polster_bei_farbe(regeln):
    """CSS-Regeln eines Blocks: Mit Hintergrundfarbe fällt das Polster weg, MuPDF malt es sonst farbig oben auf jede
    weitere Seite, über den Text (echte Tabellenzellen betrifft das nicht)."""
    namen = [r.split(":")[0].strip().lower() for r in regeln]
    if not any(n in ("background", "background-color") for n in namen):
        return regeln
    return [r for r, n in zip(regeln, namen) if not n.startswith("padding")]


class _Bereiniger(HTMLParser):
    """Baut das HTML neu auf: keine Skripte/Frames/Formulare, keine on*-Attribute, keine externen Bilder
    (Zählpixel!), cid-Bilder auf Archiv-Namen umgebogen (Konzept „Bewusst nicht: externe Inhalte laden“)."""
    WEG_MIT_INHALT = {"script", "iframe", "object", "embed", "noscript", "title", "head", "template", "form",
                      "svg", "math", "audio", "video"}
    LEER = {"br", "hr", "img", "meta", "link", "input", "col", "area", "base", "wbr"}
    ERLAUBT = {"p", "div", "span", "br", "hr", "b", "strong", "i", "em", "u", "s", "small", "big",
               "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "dl", "dt", "dd",
               "table", "thead", "tbody", "tfoot", "tr", "td", "th", "caption", "colgroup", "col",
               "blockquote", "pre", "code", "tt", "font", "center", "a", "img", "sup", "sub",
               "html", "body"}
    ATTRIBUTE = {"class", "style", "width", "height", "align", "valign", "colspan", "rowspan",
                 "border", "cellpadding", "cellspacing", "color", "size", "face", "bgcolor", "href", "src", "alt"}

    def __init__(self, cid_namen):
        super().__init__(convert_charrefs=True)
        self.cid_namen = cid_namen
        self.aus = []
        self.stile = []
        self.im_stil = False
        self.weg_tiefe = 0
        self.externe_bilder = 0
        self.tabellen = 0

    def handle_starttag(self, tag, attrs):
        if tag == "style":
            self.im_stil = True
            return
        if tag in self.WEG_MIT_INHALT:
            if tag not in self.LEER:
                self.weg_tiefe += 1
            return
        if self.weg_tiefe or tag not in self.ERLAUBT:
            return
        if tag == "table":
            self.tabellen += 1
        a = {k: (v or "") for k, v in attrs if k in self.ATTRIBUTE}
        if "style" in a:
            a["style"] = re.sub(r"url\s*\([^)]*\)|expression\s*\([^)]*\)", "", a["style"], flags=re.I)
            if tag not in ("td", "th"):
                a["style"] = ";".join(_ohne_polster_bei_farbe([r for r in a["style"].split(";") if r.strip()]))
        if "href" in a and not re.match(r"(https?|mailto):", a["href"], re.I):
            del a["href"]
        if tag == "img":
            src = a.get("src", "")
            if src.lower().startswith("cid:") and src[4:] in self.cid_namen:
                a["src"] = self.cid_namen[src[4:]]
            else:
                self.externe_bilder += 1
                klein = any(a.get(k, "").strip() in ("0", "1", "2") for k in ("width", "height"))
                # In einer Layout-Zelle drückt der lange Text die Spalten zusammen, die Zahl steht im Hinweis (#110)
                if not klein and not self.tabellen:
                    self.aus.append('<span class="ersatz">[Bild nicht geladen]</span>')
                return
        elif "src" in a:
            del a["src"]
        teile = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in a.items())
        self.aus.append(f"<{tag}{teile}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in self.WEG_MIT_INHALT and tag not in self.LEER:
            self.weg_tiefe = max(0, self.weg_tiefe - 1)     # <iframe/> öffnet nichts

    def handle_endtag(self, tag):
        if tag == "style":
            self.im_stil = False
            return
        if tag in self.WEG_MIT_INHALT:
            self.weg_tiefe = max(0, self.weg_tiefe - 1)
            return
        if self.weg_tiefe or tag not in self.ERLAUBT or tag in self.LEER:
            return
        if tag == "table":
            self.tabellen = max(0, self.tabellen - 1)
        self.aus.append(f"</{tag}>")

    def handle_data(self, data):
        if self.im_stil:
            self.stile.append(re.sub(r"@import[^;]*;|url\s*\([^)]*\)", "", data, flags=re.I))
            return
        if self.weg_tiefe:
            return
        self.aus.append(html.escape(brich_lange_woerter(data), quote=False))


_CSS_KOMMENTAR = re.compile(r"/\*.*?(?:\*/|\Z)|<!--|-->", re.S)


def _nur_ganze_regeln(css):
    """Stile der Mail bis auf das, was nie geschlossen wird: Unsere Regeln hängen dahinter, eine offene Klammer oder ein
    offener Kommentar nähme sie mit (FALLSTRICKE #110). Fremde Klammern und Reste außerhalb einer Regel fallen weg."""
    css = _CSS_KOMMENTAR.sub(" ", css)
    aus, anfang, tiefe = [], 0, 0
    for i, z in enumerate(css):
        if z == "{":
            tiefe += 1
        elif z == "}" and not tiefe:
            anfang = i + 1
        elif z == "}":
            tiefe -= 1
            if not tiefe:
                aus.append(css[anfang:i + 1])
                anfang = i + 1
    return "".join(aus)


def bereinige_html(roh, cid_namen=None):
    """(sicheres HTML, Zahl externer Bilder, gesammelte Stile)."""
    b = _Bereiniger(cid_namen or {})
    b.feed(roh)
    b.close()
    text = re.sub(r"</?(html|body)[^>]*>", "", "".join(b.aus), flags=re.I)   # Story kennt nur EIN body
    return text, b.externe_bilder, _nur_ganze_regeln("\n".join(b.stile))


class _NurText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.teile, self.weg = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head", "title"):
            self.weg += 1
        elif tag in ("br", "p", "div", "tr", "li"):
            self.teile.append("\n")
        elif tag in ("td", "th"):
            self.teile.append(" ")          # sonst klebt „Betrag49,90“ zusammen

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head", "title"):
            self.weg = max(0, self.weg - 1)

    def handle_data(self, data):
        if not self.weg:
            self.teile.append(data)


def html_zu_text(roh):
    p = _NurText()
    p.feed(roh or "")
    p.close()
    return "".join(p.teile)


_HTML_KOMMENTAR = re.compile(r"<!--.*?-->", re.S)
_HTML_WEG = re.compile(r"<(script|style|head|title)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_HTML_ZEILE = re.compile(r"<(?:br|p|div|tr|li)\b[^>]*>", re.I)
_HTML_ZELLE = re.compile(r"<t[dh]\b[^>]*>", re.I)
_HTML_TAG = re.compile(r"</?[A-Za-z!?][^>]*>")     # „< und >“ im Text ist kein Tag - wie bei HTMLParser


def html_zu_suchtext(roh):
    """Wie `html_zu_text`, aber mit regulären Ausdrücken statt HTMLParser: gemessen siebenmal so schnell (98 KB
    Newsletter-HTML 0,8 statt 5,9 ms), derselbe Suchtext. Nur für Suchtext und Vorschau beim Einlesen
    (KONZEPT_MAIL_AUF_ABRUF S3) - die Kennung einer Mail ohne Message-ID bleibt bei `html_zu_text` (`textanfang`),
    sonst erschienen schon übernommene Mails als neu."""
    text = _HTML_KOMMENTAR.sub("", roh or "")
    text = _HTML_WEG.sub("", text)
    text = _HTML_ZEILE.sub("\n", text)
    text = _HTML_ZELLE.sub(" ", text)              # sonst klebt „Betrag49,90“ zusammen
    return html.unescape(_HTML_TAG.sub("", text))


def zeichenzahl(text):
    """Buchstaben und Ziffern: Füllzeichen im Vorspann eines Newsletters zählen nicht, Wörter wären dafür zu grob."""
    return sum(c.isalnum() for c in text)


_VERSTECKT = re.compile(r"display\s*:\s*none|max-height\s*:\s*0(?![\d.])|mso-hide\s*:\s*all", re.I)
_OHNE_ENDE = {"area", "base", "br", "col", "hr", "img", "input", "link", "meta", "wbr"}
_KEIN_TEXT = {"head", "script", "style", "title"}


class _SichtbarerText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.zeichen, self.stapel = 0, []       # stapel: (Tag, versteckt)

    def handle_starttag(self, tag, attrs):
        if tag not in _OHNE_ENDE:
            self.stapel.append((tag, tag in _KEIN_TEXT or bool(_VERSTECKT.search(dict(attrs).get("style") or ""))))

    def handle_endtag(self, tag):
        # Ein offener <p> darf den Stapel nicht verschieben: bis zum passenden Tag abbauen, ein fremdes Ende übergehen
        if any(t == tag for t, _ in self.stapel):
            while self.stapel.pop()[0] != tag:
                pass

    def handle_data(self, data):
        if not any(versteckt for _, versteckt in self.stapel):
            self.zeichen += zeichenzahl(data)


def sichtbare_zeichen(roh):
    """Wie viel Text von diesem HTML auf den Seiten stehen sollte, ohne Verstecktes (FALLSTRICKE #108)."""
    p = _SichtbarerText()
    p.feed(roh or "")
    p.close()
    return p.zeichen


def text_als_html(text):
    zeilen = []
    for z in text.replace("\r\n", "\n").split("\n"):
        e = html.escape(brich_lange_woerter(z), quote=False) or "&nbsp;"
        e = e.replace("  ", "&nbsp; ")
        zeilen.append(f'<div class="zitat">{e}</div>' if z.lstrip().startswith(">") else f"<div>{e}</div>")
    return "\n".join(zeilen)


def groesse_text(n):
    return f"{n} Byte" if n < 1024 else f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1048576:.1f} MB"


_TABELLEN_TAG = re.compile(r"<(/?)(table|thead|tbody|tfoot|tr|td|th|caption|colgroup|col)\b([^>]*)>", re.I)
_GROESSEN = {"width", "height", "min-width", "min-height", "max-width", "max-height"}


def _block_statt_tabelle(attribute):
    """<div> mit dem, was vom Aussehen einer Tabellenzelle bleibt: Farben und Abstände ja, feste Größen nicht
    (weiße Schrift bräuchte sonst ihren Hintergrund, und feste Höhen waren das Problem)."""
    def wert(name):
        treffer = re.search(rf'\b{name}="([^"]*)"', attribute, re.I)
        return treffer.group(1) if treffer else ""
    regeln = [r.strip() for r in wert("style").split(";")
              if r.strip() and r.split(":")[0].strip().lower() not in _GROESSEN]
    if wert("bgcolor"):
        regeln.insert(0, f"background-color:{wert('bgcolor')}")
    regeln = _ohne_polster_bei_farbe(regeln)
    teile = (f' class="{wert("class")}"' if wert("class") else "") + (f' style="{";".join(regeln)}"' if regeln else "")
    return f"<div{teile}>"


def loese_tabellen(inhalt, alle=False):
    """Bereinigtes Mail-HTML ohne Layout-Tabellen: Eine Tabellenzeile lässt sich nicht über Seiten teilen, und viele
    Newsletter stecken ihren ganzen Inhalt in eine (FALLSTRICKE #103). Tabellen mit einer Tabelle darin werden zu
    Blöcken, innere Datentabellen bleiben; `alle=True` löst auch diese auf."""
    aeussere, offen, nummer = set(), [], 0
    for m in _TABELLEN_TAG.finditer(inhalt):
        if m.group(2).lower() != "table":
            continue
        if m.group(1):
            if offen:
                offen.pop()
        else:
            nummer += 1
            aeussere.update(offen)
            offen.append(nummer)

    aufloesen, nummer = [], 0

    def ersetze(m):
        nonlocal nummer
        zu, tag = m.group(1), m.group(2).lower()
        if tag == "table" and not zu:
            nummer += 1
            aufloesen.append(alle or nummer in aeussere)
            return _block_statt_tabelle(m.group(3)) if aufloesen[-1] else m.group(0)
        if tag == "table":
            return "</div>" if (aufloesen.pop() if aufloesen else True) else m.group(0)
        if aufloesen and not aufloesen[-1]:
            return m.group(0)
        if tag in ("thead", "tbody", "tfoot", "colgroup", "col"):
            return ""
        return "</div>" if zu else _block_statt_tabelle(m.group(3))

    return _TABELLEN_TAG.sub(ersetze, inhalt)


# Darstellung einer Mail im PDF: passt sie so nicht auf Seiten, kommt die nächste Stufe (mail_import._importiere)
VOLL, OHNE_LAYOUT, OHNE_TABELLEN, NUR_TEXT = range(4)
_STEUERZEICHEN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def seite_html(mail, richtung_="ein", konto="", stufe=VOLL):
    """(Stile, HTML, cid_bilder) der Mail-Seiten: Kopf als Zeilen „Von: …“ (keine Tabelle - der Textauszug machte
    daraus „VonMax …“, S1), darunter der Text, unten die Anhänge. `stufe`: siehe oben, ab OHNE_LAYOUT mit Hinweis."""
    art, text, cid_bilder, anhaenge, probleme = mail.koerper()
    cid_namen = {k: v[0] for k, v in cid_bilder.items()}
    if stufe != VOLL:
        probleme = [*probleme, "Vereinfachte Darstellung, die vollständige Mail ist eingebettet"]
    if stufe == NUR_TEXT:
        text = html_zu_text(text) if art == "html" else text
        art, cid_bilder = "text", {}
    if art == "html":
        inhalt, externe, stile = bereinige_html(text, cid_namen)
        if stufe != VOLL:
            inhalt = loese_tabellen(inhalt, alle=stufe == OHNE_TABELLEN)
    else:
        inhalt, externe, stile = text_als_html(text), 0, ""
    datum = mail.datum.strftime("%d.%m.%Y %H:%M") if mail.datum else (mail.datum_roh or "(ohne Datum)")
    zeilen = [("Von", mail.von), ("An", mail.an)]
    if mail.cc:
        zeilen.append(("Cc", mail.cc))
    zeilen += [("Datum", datum), ("Richtung", "eingegangen" if richtung_ == "ein" else "gesendet")]
    if konto:
        zeilen.append(("Konto", konto))
    kopf_html = "".join(f'<div><span class="feld">{f}:</span> {html.escape(w)}</div>' for f, w in zeilen)
    hinweise = ([f"{externe} externe(s) Bild(er) nicht geladen"] if externe else []) + probleme
    hinweis_html = f'<p class="hinweis">{html.escape("; ".join(hinweise))}</p>' if hinweise else ""
    anh_html = ""
    if anhaenge:
        punkte = "".join(f"<li>{html.escape(a['name'])} ({html.escape(a['typ'])}, {groesse_text(a['groesse'])})</li>"
                         for a in anhaenge)
        anh_html = (f'<div class="anhaenge"><b>Anhänge ({len(anhaenge)})</b> - in der eingebetteten Original-Mail '
                    f'enthalten<ul>{punkte}</ul></div>')
    seite = (f'<div class="betreff">{html.escape(mail.betreff or "(ohne Betreff)")}</div>'
             f'<div class="kopf">{kopf_html}</div>{hinweis_html}<div>{inhalt}</div>{anh_html}')
    # Die Story liest das HTML nur bis zum ersten Nullzeichen, alles dahinter fehlte im PDF (FALLSTRICKE #108)
    return stile, _STEUERZEICHEN.sub("", seite), cid_bilder


def datum_text(mail):
    """'JJJJ-MM-TT' für KID_DokumentenDatum (sicher, nicht vermutet) oder ""."""
    return mail.datum.strftime("%Y-%m-%d") if isinstance(mail.datum, datetime.datetime) else ""
