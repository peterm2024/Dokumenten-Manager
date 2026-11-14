"""
.pst/.ost-Eingang des Mail-Imports (KONZEPT_MAIL_IMPORT.md, E4: pypff direkt in KID; Code aus Spike S2).

Eine .pst enthält KEINE Original-.eml, nur Eigenschaften und - bei eingegangenen Mails - die gespeicherten
Kopfzeilen. `baue_eml` rekonstruiert die Mail daraus („so original, wie die .pst es hergibt“). Nicht-Mails
(Kalender, Kontakte, Verteilerlisten) werden an der Nachrichtenklasse erkannt und übersprungen.

pypff (Paket libpff-python, LGPL-3.0) ist optional: ohne es meldet `verfuegbar()` False und der Import nennt den
Grund, statt abzustürzen. Die Funktionen arbeiten nur mit den Attributen der pypff-Objekte - die Tests geben
Nachbauten hinein. GUI-frei.
"""

import datetime
import os
import re
from email import policy
from email.message import EmailMessage
from email.parser import Parser
from email.utils import format_datetime

try:
    import pypff
except ImportError:          # Quellcode-Betrieb ohne das Paket
    pypff = None

# MAPI-Eigenschaften (MS-OXPROPS)
PR_MESSAGE_CLASS = 0x001A
PR_INTERNET_MESSAGE_ID = 0x1035
PR_SENDER_EMAIL = 0x0C1F
PR_SENDER_SMTP = 0x5D01
PR_DISPLAY_TO = 0x0E04
PR_DISPLAY_CC = 0x0E03
PR_INTERNET_CPID = 0x3FDE


def verfuegbar():
    return pypff is not None


def oeffne(pfad):
    if pypff is None:
        raise RuntimeError("Zum Lesen von .pst-Dateien fehlt das Paket libpff-python.")
    f = pypff.file()
    f.open(os.path.abspath(pfad))     # pypff öffnet unter Windows keinen Pfad mit „/“ (S2)
    return f


def eigenschaft(item, kennung):
    for rs in range(item.number_of_record_sets):
        r = item.get_record_set(rs)
        for e in range(r.number_of_entries):
            en = r.get_entry(e)
            if en.entry_type == kennung:
                for art in ("data_as_string", "data_as_integer", "data"):
                    try:
                        return getattr(en, art)
                    except Exception:          # noqa: BLE001 - pypff wirft je nach Typ verschiedenes
                        continue
                return None
    return None


def _text(v, codepage=None):
    if not v:
        return ""
    if isinstance(v, bytes):
        for zs in ([f"cp{codepage}"] if codepage else []) + ["utf-8", "cp1252"]:
            try:
                return v.decode(zs).rstrip("\x00")
            except (UnicodeDecodeError, LookupError):
                continue
    return str(v)


def ist_mail(item):
    return str(eigenschaft(item, PR_MESSAGE_CLASS) or "").upper().startswith("IPM.NOTE")


RTF_HINWEIS = "(Text nur als RTF vorhanden - nicht umgewandelt)"
# Die Kopfzeilen, die KID beim Einlesen braucht (mail_lesen.Mail._lies_kopf), S3b
KOPF_FELDER = ("from", "to", "cc", "subject", "date", "message-id", "list-unsubscribe", "auto-submitted", "x-autoreply",
               "x-autorespond", "precedence")
_KOMPAKT = Parser(policy=policy.compat32)


def _ohne_steuerzeichen(wert):
    return re.sub(r"[\x00-\x1f\x7f]+", " ", wert).strip()


def _setze_kopf(msg, name, wert):
    """Kopfzeile aus den Eigenschaften setzen. Eine leere Zeile aus den gespeicherten Kopfzeilen muss erst weg (es darf
    z.B. nur einen Betreff geben), und Zeilenumbrüche im Wert lehnt EmailMessage ab - beides ließ echte Mails als
    „unlesbar“ durchfallen (FALLSTRICKE #100)."""
    del msg[name]
    msg[name] = _ohne_steuerzeichen(wert)


def baue_eml(m, anhaenge=True, text=True, ein_text=False):
    """Die Mail eines pypff-Eintrags als .eml-Bytes. `anhaenge=False` (Einlesen): Anhänge nur mit Namen und leerem
    Inhalt - eine 12-GB-Sammlung von .pst-Dateien ist groß wegen der Anhänge (S2), gelesen werden sie erst beim
    Import. Kopf, Text und damit der Schlüssel gegen Doppelte sind in beiden Fällen gleich.
    `text=False` (Phase 1 des Einlesens, KONZEPT_MAIL_AUF_ABRUF „Schneller einlesen“): auch ohne Text, nur Kopf und
    Anhangnamen - gemessen 3,1 statt 14,2 ms je Mail. Die Kopfzeilen sind dieselben wie mit Text.
    `ein_text=True` (Einlesen, S3): nur der Textteil, den `mail_lesen.Mail.koerper` liest - das HTML, sonst der reine
    Text. Kennung und Text bleiben gleich, das Verpacken und Zerlegen der zweiten Fassung fällt weg. Für das PDF beim
    Übernehmen bleiben beide Fassungen (eingebettete Original-Mail)."""
    kopf_roh = _text(m.transport_headers)
    cp = eigenschaft(m, PR_INTERNET_CPID)
    cp = cp if isinstance(cp, int) else None
    msg = EmailMessage()
    if kopf_roh:
        # Kopfzeilen eingegangener Mails übernehmen (ohne MIME-Teile - den Inhalt bauen wir neu)
        alt = Parser(policy=policy.compat32).parsestr(kopf_roh, headersonly=True)
        for k, v in alt.items():
            if k.lower().startswith("content-") or k.lower() == "mime-version":
                continue
            try:
                msg[k] = re.sub(r"\r?\n[ \t]+", " ", str(v))   # umgebrochene Kopfzeilen entfalten (S2)
            except Exception:          # noqa: BLE001 - kaputte Zeile auslassen
                continue
    if not msg["From"]:
        # gesendete/selbst erstellte Mails: Kopf aus den Eigenschaften
        name = _text(m.sender_name)
        adresse = _text(eigenschaft(m, PR_SENDER_SMTP) or eigenschaft(m, PR_SENDER_EMAIL) or "")
        _setze_kopf(msg, "From", f"{name} <{adresse}>" if "@" in adresse else (name or adresse))
    if not msg["To"] and eigenschaft(m, PR_DISPLAY_TO):
        _setze_kopf(msg, "To", _text(eigenschaft(m, PR_DISPLAY_TO)))
    if not msg["Cc"] and eigenschaft(m, PR_DISPLAY_CC):
        _setze_kopf(msg, "Cc", _text(eigenschaft(m, PR_DISPLAY_CC)))
    if not msg["Subject"]:
        _setze_kopf(msg, "Subject", _text(m.subject))
    if not msg["Date"]:
        zeit = m.client_submit_time or m.delivery_time or m.creation_time
        if zeit:
            _setze_kopf(msg, "Date", format_datetime(zeit.replace(tzinfo=datetime.timezone.utc)))
    if not msg["Message-ID"]:
        mid = _text(eigenschaft(m, PR_INTERNET_MESSAGE_ID))
        if mid:
            _setze_kopf(msg, "Message-ID", mid)
    html_ = _text(m.html_body, cp) if text else ""
    plain = _text(m.plain_text_body, cp) if text and not (ein_text and html_) else ""
    if plain:
        msg.set_content(plain)
        if html_:
            msg.add_alternative(html_, subtype="html")
    elif html_:
        msg.set_content(html_, subtype="html")
    elif text and getattr(m, "rtf_body", None):
        msg.set_content(RTF_HINWEIS)
    else:
        msg.set_content("")
    for j in range(m.number_of_attachments):
        a = m.get_attachment(j)
        try:
            daten = a.read_buffer(a.size) if (anhaenge and a.size) else b""
        except Exception:              # noqa: BLE001 - unlesbarer Anhang
            continue
        name = getattr(a, "long_filename", None) or getattr(a, "name", None) or f"anhang_{j}"
        typ = ("application", "pdf") if str(name).lower().endswith(".pdf") else ("application", "octet-stream")
        msg.add_attachment(daten, maintype=typ[0], subtype=typ[1], filename=str(name))
    return msg.as_bytes(policy=policy.SMTP)


def kopfzeilen(m):
    """Die Kopfzeilen für `mail_lesen.KopfMail`, ohne .eml (S3b) - aus denselben Quellen wie `baue_eml`: die
    gespeicherten Kopfzeilen (die erste gewinnt), sonst die Eigenschaften. :return: {Name klein: Rohwert}"""
    kopf = {}
    roh = _text(m.transport_headers)
    if roh:
        for name, wert in _KOMPAKT.parsestr(roh, headersonly=True).items():
            name = name.lower()
            if name in KOPF_FELDER and name not in kopf:
                kopf[name] = re.sub(r"\r?\n[ \t]+", " ", str(wert))          # umgebrochene Kopfzeilen entfalten

    def fehlt(name):
        return not kopf.get(name, "").strip()

    if fehlt("from"):
        name = _text(m.sender_name)
        adresse = _text(eigenschaft(m, PR_SENDER_SMTP) or eigenschaft(m, PR_SENDER_EMAIL) or "")
        kopf["from"] = _ohne_steuerzeichen(f"{name} <{adresse}>" if "@" in adresse else (name or adresse))
    for name, kennung in (("to", PR_DISPLAY_TO), ("cc", PR_DISPLAY_CC)):
        if fehlt(name) and eigenschaft(m, kennung):
            kopf[name] = _ohne_steuerzeichen(_text(eigenschaft(m, kennung)))
    if fehlt("subject"):
        kopf["subject"] = _ohne_steuerzeichen(_text(m.subject))
    if fehlt("date"):
        zeit = m.client_submit_time or m.delivery_time or m.creation_time
        if zeit:
            kopf["date"] = format_datetime(zeit.replace(tzinfo=datetime.timezone.utc))
    if fehlt("message-id"):
        mid = _text(eigenschaft(m, PR_INTERNET_MESSAGE_ID))
        if mid:
            kopf["message-id"] = _ohne_steuerzeichen(mid)
    return kopf


def anhang_namen(m):
    """Die Namen der Anhänge wie in `baue_eml`, ohne einen davon zu lesen."""
    namen = []
    for j in range(m.number_of_attachments):
        a = m.get_attachment(j)
        namen.append(str(getattr(a, "long_filename", None) or getattr(a, "name", None) or f"anhang_{j}"))
    return namen


def text_teil(m):
    """(art, Text), wie `mail_lesen.Mail.koerper` ihn aus `baue_eml(…, ein_text=True)` liest: das HTML, sonst der reine
    Text, sonst der RTF-Hinweis (S3b)."""
    cp = eigenschaft(m, PR_INTERNET_CPID)
    cp = cp if isinstance(cp, int) else None
    html_ = _text(m.html_body, cp)
    if html_:
        return "html", html_
    plain = _text(m.plain_text_body, cp)
    if plain:
        return "text", plain
    return "text", RTF_HINWEIS if getattr(m, "rtf_body", None) else ""


def mails(datei):
    """(Ort, Ordnerpfad, pypff-Eintrag) je Mail einer geöffneten .pst; Ort = „ordner.ordner/nachricht“ (Indizes),
    damit `hole` dieselbe Mail später ohne erneuten Durchlauf findet."""
    def durch(ordner, ort, pfad):
        for i in range(ordner.number_of_sub_messages):
            try:
                m = ordner.get_sub_message(i)
            except Exception:          # noqa: BLE001 - kaputter Eintrag: zählt als unlesbar beim Aufrufer
                yield f"{ort}/{i}", pfad, None
                continue
            if ist_mail(m):
                yield f"{ort}/{i}", pfad, m
        for i in range(ordner.number_of_sub_folders):
            unter = ordner.get_sub_folder(i)
            name = _text(getattr(unter, "name", "")) or "?"
            yield from durch(unter, f"{ort}.{i}" if ort else str(i), f"{pfad}/{name}" if pfad else name)
    yield from durch(datei.root_folder, "", "")


def zaehle(datei):
    """Einträge aller Ordner einer geöffneten .pst, für die Fortschrittsanzeige. Kontakte und Termine zählen mit,
    die Zahl ist also eine Obergrenze der Mails. 0, wenn sich die Ordner nicht zählen lassen."""
    def durch(ordner):
        return ordner.number_of_sub_messages + sum(durch(ordner.get_sub_folder(i))
                                                   for i in range(ordner.number_of_sub_folders))
    try:
        return durch(datei.root_folder)
    except Exception:                  # noqa: BLE001 - nur für die Anzeige
        return 0


def hole(datei, ort):
    """Den Eintrag zu einem Ort aus `mails`."""
    ordner_teil, _, nachricht = ort.rpartition("/")
    ordner = datei.root_folder
    for i in filter(None, ordner_teil.split(".")):
        ordner = ordner.get_sub_folder(int(i))
    return ordner.get_sub_message(int(nachricht))
