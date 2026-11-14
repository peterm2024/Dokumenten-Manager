"""
Mail-Import auf Abruf (KONZEPT_MAIL_AUF_ABRUF.md, seit 08.11.2026; davor KONZEPT_MAIL_IMPORT.md): eine Quelle (.pst/.ost,
mbox, .eml, ein Ordner mit Mail-Dateien oder die Kopie aus einem Mail-Programm) einlesen, darin suchen und die
angehakten Mails als Mail-PDFs übernehmen - in den Posteingang (die Vollautomatik legt ab) oder direkt in einen Ordner.

Ohne KI: Der Mensch sucht und hakt an, der Code übernimmt. Doppelte (Message-ID bzw. Fingerabdruck, auch schon
importierte) erkennt `lies_quelle`, der Vorfilter (mail_lesen.vorfilter: Spam, Papierkorb, Entwürfe, Lesebestätigungen)
blendet nur aus. Bis 08.11.2026 stufte die KI jede Mail ein, dazu Absender-Regeln und Beziehungen je Gegenüber
(Etappe 6 „Zurückrudern“, Bauschritt 4 hat das entfernt; `mail_absender.json` und `mail_beziehungen.json` bleiben im
Daten-Ordner liegen und werden nicht mehr gelesen).

Journal `mail_import.json` im Daten-Ordner: eigene Adressen, importierte Schlüssel, Quelle und Zeitraum des letzten
Laufs - ein abgebrochener Import macht dort weiter, wo er stand, ein zweiter Lauf legt nichts doppelt an. Die Quelle
wird nie verändert. Datenschutz: das Protokoll (logger) bekommt nur Zahlen, nie Adressen oder Betreffs; der Suchtext
bleibt im Arbeitsspeicher.

GUI-frei; PyMuPDF nur über pdf_handler.
"""

import collections
import datetime
import fnmatch
import json
import os
import re

import app_paths
import sicher_speichern
import suchsyntax
import mail_lesen
import mail_pst
import mail_quellen
import scan_date
from pdf_handler import MailZuLang, PDFHandler

JOURNAL = "mail_import.json"

# Ergebnis je Mail: angehakt = übernehmen (Fenster `_setze_ergebnisse`), "importiert", "zeitraum" oder "" (offen)
UEBERNEHMEN = "übernehmen"

# ---------------------------------------------------------------- Dateien im Daten-Ordner
def _pfad(master, name):
    return os.path.join(app_paths.data_dir(master), name)


def _lade_json(pfad, leer):
    try:
        with open(pfad, encoding="utf-8") as f:
            daten = json.load(f)
        return daten if isinstance(daten, dict) else leer
    except FileNotFoundError:
        return leer
    except (OSError, ValueError) as e:
        # eine kaputte Datei wird nie still überschrieben - sie trägt Entscheidungen von Hand
        raise OSError(f"{os.path.basename(pfad)} ist nicht lesbar: {e}") from e


def _schreibe_json(pfad, daten):
    sicher_speichern.schreibe_json(pfad, daten, ensure_ascii=False, indent=1)


class Journal:
    """Gedächtnis des Imports: {"eigene": [...], "importiert": {schlüssel: {"dateien", "am"}}, "zuletzt": {...}}.
    Unbekannte Schlüssel (die KI-Einstufungen „ki“ und Entscheidungen „hand“ bis 08.11.2026) bleiben beim Speichern
    unverändert stehen - im Daten-Ordner wird nichts gelöscht (KONZEPT_MAIL_AUF_ABRUF)."""
    BEKANNT = ("hinweis", "eigene", "nicht_eigene", "importiert", "zuletzt", "newsletter")

    def __init__(self, master):
        self.master = master
        self.pfad = _pfad(master, JOURNAL)
        d = _lade_json(self.pfad, {})
        self.eigene = [str(a).lower() for a in d.get("eigene") or []]
        # aus den gesendeten Mails vorgeschlagen und abgelehnt: nicht wieder fragen (eigene_vorschlaege)
        self.nicht_eigene = [str(a).lower() for a in d.get("nicht_eigene") or []]
        self.importiert = dict(d.get("importiert") or {})
        self.zuletzt = dict(d.get("zuletzt") or {})     # {"quelle", "ab", "bis"}: Fenster öffnet mit dem letzten Lauf
        # Absender und Domänen („@firma.de“), die der Nutzer als Newsletter behandelt (Rechtsklick, Peter 12.11.2026)
        self.newsletter = [str(a).lower() for a in d.get("newsletter") or []]
        self._rest = {k: v for k, v in d.items() if k not in self.BEKANNT}

    def speichere(self):
        _schreibe_json(self.pfad, {"hinweis": "Mail-Import: Journal (eigene Adressen, importierte Mails, letzter Lauf, "
                                              "Newsletter-Absender). Nicht von Hand ändern.",
                                   "eigene": self.eigene, "nicht_eigene": self.nicht_eigene,
                                   "importiert": self.importiert, "zuletzt": self.zuletzt, "newsletter": self.newsletter,
                                   **self._rest})


ANBIETER = mail_lesen.ANBIETER


# ---------------------------------------------------------------- Quelle einlesen
def quelle_art(pfad):
    """'pst', 'mbox', 'eml', 'kopie' (Kopie aus einem Mail-Programm), 'ordner' (alle Mail-Dateien darin) oder None."""
    if os.path.isdir(pfad):
        return "kopie" if mail_quellen.ist_kopie(pfad) else "ordner"
    endung = os.path.splitext(pfad)[1].lower()
    if endung in (".pst", ".ost"):
        return "pst"
    if endung == ".eml":
        return "eml"
    if mail_lesen.ist_mbox(pfad):
        return "mbox"
    return None


def _mbox_roh(pfad, zahlen):
    """Mails einer mbox wie _roh_mails. Was Thunderbird als gelöscht führt, liegt nur noch bis zum Komprimieren in der
    Datei und kommt nicht wieder (Spike S5); gekürzte Mails bleiben drin und werden gezählt."""
    for ort, daten in mail_lesen.mbox_mails(pfad, zahlen):
        zustand = mail_lesen.mozilla_zustand(daten)
        if zustand:
            zahlen[zustand] += 1
        if zustand != mail_lesen.GELOESCHT:
            yield ort, "", daten


MBOX_ENDUNGEN = ("", ".mbox", ".mbx")


def mail_dateien(ordner):
    """Alle Mail-Dateien unter einem Ordner (KONZEPT_MAIL_AUF_ABRUF F7), in fester Reihenfolge: .pst/.ost, .eml und
    mbox - die erkennt man am Inhalt, Thunderbird-Dateien haben keine Endung.
    :return: [(Pfad, Ordnername für den Vorfilter)]; bei .pst steht der Ordner in der Datei selbst"""
    funde = []
    for wurzel, unter, namen in os.walk(ordner):
        unter.sort()
        for name in sorted(namen):
            pfad = os.path.join(wurzel, name)
            relativ = os.path.relpath(pfad, ordner)
            endung = os.path.splitext(name)[1].lower()
            if endung in (".pst", ".ost"):
                funde.append((pfad, ""))
            elif endung == ".eml":
                funde.append((pfad, os.path.dirname(relativ)))
            elif endung in MBOX_ENDUNGEN and mail_lesen.ist_mbox(pfad):
                # Thunderbird: „Inbox.sbd/Junk“ ist der Unterordner Junk von Inbox
                funde.append((pfad, os.path.splitext(relativ)[0].replace(".sbd" + os.sep, "/")))
    return funde


def _merke_stand(stand, pfad):
    """Größe und Änderungszeit beim Einlesen, für die Prüfung vor dem Übernehmen (veraenderte_dateien)."""
    if stand is None:
        return
    try:
        s = os.stat(pfad)
        stand[os.path.abspath(pfad)] = (s.st_size, s.st_mtime_ns)
    except OSError:
        stand[os.path.abspath(pfad)] = None


def _groessen(pfade):
    """Dateigrößen als Gewichte für den Fortschritt über mehrere Dateien (eine unlesbare zählt 1 Byte)."""
    groessen = []
    for pfad in pfade:
        try:
            groessen.append(max(1, os.path.getsize(pfad)))
        except OSError:
            groessen.append(1)
    return groessen


_LEERZEILE = re.compile(rb"\r?\n\r?\n")


def _kopf_oder_ganz(daten, nur_kopf):
    """mbox und .eml in Phase 1 (S3): nur die Kopfzeilen bis zur ersten Leerzeile - es sei denn, `nur_kopf` sagt,
    die Mail wird ganz gebraucht (ohne Message-ID). Die Anhänge sind dann erst nach Phase 2 bekannt."""
    if nur_kopf is None or not daten:
        return daten
    leer = _LEERZEILE.search(daten)
    kopf = daten[:leer.end()] if leer else daten
    return daten if nur_kopf(kopf) else kopf


def _pst_lesen(m, nur_kopf=None, direkt=False):
    """Eine Mail aus einer .pst zum Einlesen. `direkt` oder `nur_kopf` (S3b): als `mail_lesen.KopfMail` ohne den
    Umweg über eine .eml - an Peters .pst 5.000 Mails: Kennung und Adressen gleich, nur 3 Anzeigenamen anders, 8
    Betreffe ohne das falsche Leerzeichen des Umbruchs. Mails ohne Message-ID (nur_kopf sagt ja) und alles, was
    direkt nicht klappt, gehen den alten Weg: Ihre Kennung braucht den Textanfang genau wie bisher."""
    if nur_kopf is None and not direkt:
        return mail_pst.baue_eml(m, anhaenge=False, ein_text=True)
    try:
        mail = mail_lesen.KopfMail(mail_pst.kopfzeilen(m), mail_pst.anhang_namen(m),
                                   mail_pst.text_teil(m) if nur_kopf is None else None)
    except Exception:                      # noqa: BLE001 - dann eben der alte Weg
        return mail_pst.baue_eml(m, anhaenge=False, ein_text=True)
    if nur_kopf is not None and nur_kopf(mail):
        return mail_pst.baue_eml(m, anhaenge=False, ein_text=True)
    return mail


def _roh_mails(quelle, zahlen=None, stand=None, fehler=None, lage=None, nur_kopf=None, direkt=False):
    """(Ort, Ordner, Bytes oder None) je Mail; None = Eintrag unlesbar.
    :param zahlen: Counter für das, was beim Lesen auffällt (mbox)
    :param stand: dict, bekommt je gelesener Datei (Größe, Änderungszeit)
    :param fehler: Liste, bekommt bei einem Ordner die Dateien, die sich nicht lesen ließen (etwa von Outlook gesperrt)
    :param lage: dict für die Fortschrittsanzeige: „teil“ = gelesener Anteil 0…1, bei mehreren Dateien „nr“/„gesamt“
    :param nur_kopf: Phase 1 (KONZEPT_MAIL_AUF_ABRUF „Schneller einlesen“): Callable(Bytes) → True, wenn diese Mail
                     trotzdem ganz gebraucht wird. .pst/.ost liefern dann eine `KopfMail` (S3b), mbox und .eml nur
                     ihre Kopfzeilen (S3).
    :param direkt: Phase 2 (S3b): .pst/.ost liefern eine `KopfMail` samt Text statt .eml-Bytes"""
    zahlen = collections.Counter() if zahlen is None else zahlen
    lage = {} if lage is None else lage
    art = quelle_art(quelle)
    if art == "pst":
        _merke_stand(stand, quelle)
        datei = mail_pst.oeffne(quelle)
        try:
            gesamt = mail_pst.zaehle(datei) or 1
            for i, (ort, ordner, m) in enumerate(mail_pst.mails(datei), 1):
                lage["teil"] = min(1.0, i / gesamt)
                if m is None:
                    yield ort, ordner, None
                    continue
                try:
                    daten = _pst_lesen(m, nur_kopf, direkt)
                except Exception:          # noqa: BLE001 - eine kaputte Mail hält den Lauf nicht auf
                    daten = None
                yield ort, ordner, daten
            lage["teil"] = 1.0
        finally:
            datei.close()
    elif art == "mbox":
        _merke_stand(stand, quelle)
        groesse = _groessen([quelle])[0]
        for ort, ordner, daten in _mbox_roh(quelle, zahlen):
            lage["teil"] = min(1.0, int(ort) / groesse)
            yield ort, ordner, _kopf_oder_ganz(daten, nur_kopf)
        lage["teil"] = 1.0
    elif art == "kopie":
        # Kopie aus einem Mail-Programm (mail_quellen): mehrere Dateien, der Ort sagt, in welcher die Mail liegt
        dateien = mail_quellen.kopie_dateien(quelle)
        groessen, vorher = _groessen([p for p, _ in dateien]), 0
        for nr, (pfad, ordner) in enumerate(dateien, 1):
            lage.update(nr=nr, gesamt=len(dateien))
            innen_lage = {}
            for ort, innen, daten in _roh_mails(pfad, zahlen, stand, lage=innen_lage, nur_kopf=nur_kopf,
                                                direkt=direkt):
                lage["teil"] = (vorher + innen_lage.get("teil", 0) * groessen[nr - 1]) / sum(groessen)
                yield (os.path.basename(pfad), ort), ordner or innen, daten
            vorher += groessen[nr - 1]
        lage["teil"] = 1.0                 # die letzte Datei meldet ihr Ende erst nach der letzten Mail
    elif art == "ordner":
        # F7: ein Ordner mit beliebig vielen Mail-Dateien wird zu EINEM Bestand, gelesen wird direkt (Archiv-Dateien
        # ändern sich nicht, eine Kopie brächte nur Wartezeit). Eine gesperrte oder kaputte Datei fehlt allein.
        dateien = mail_dateien(quelle)
        groessen, vorher = _groessen([p for p, _ in dateien]), 0
        for nr, (pfad, ordner) in enumerate(dateien, 1):
            lage.update(nr=nr, gesamt=len(dateien))
            relativ = os.path.relpath(pfad, quelle)
            innen_lage = {}
            try:
                for ort, innen, daten in _roh_mails(pfad, zahlen, stand, lage=innen_lage, nur_kopf=nur_kopf,
                                                    direkt=direkt):
                    lage["teil"] = (vorher + innen_lage.get("teil", 0) * groessen[nr - 1]) / sum(groessen)
                    yield (relativ, ort), innen or ordner, daten
            except Exception:              # noqa: BLE001 - gezählt und gemeldet, die übrigen Dateien laufen weiter
                zahlen[DATEI_NICHT_LESBAR] += 1
                if fehler is not None:
                    fehler.append(relativ)
            vorher += groessen[nr - 1]
        lage["teil"] = 1.0
    elif art == "eml":
        _merke_stand(stand, quelle)
        try:
            with open(quelle, "rb") as f:
                daten = f.read()
        except OSError:
            daten = None
        lage["teil"] = 1.0
        yield quelle, "", _kopf_oder_ganz(daten, nur_kopf)
    else:
        raise ValueError("Unbekannte Quelle - erwartet wird eine .pst/.ost, eine mbox-Datei, eine .eml oder ein "
                         "Ordner mit Mail-Dateien.")


DATEI_NICHT_LESBAR = "Datei nicht lesbar"


def ordner_hinweis(ordner):
    """Warum aus einem Ordner keine Mail kam. Der Aufrufer fragt das erst, wenn nichts gelesen wurde (T20.4: sonst
    steht nur „0 Mails gelesen“ da)."""
    if not mail_dateien(ordner):
        return "In diesem Ordner liegen keine Mail-Dateien (.eml, .pst, .ost, mbox)."
    return "Die Mail-Dateien in diesem Ordner enthalten keine lesbaren Mails."


class QuelleVeraendert(Exception):
    """Eine Mail-Datei hat sich seit dem Einlesen verändert (veraenderte_dateien)."""

    def __init__(self, dateien):
        self.dateien = dateien
        super().__init__("Die Mail-Datei(en) " + ", ".join(dateien[:5]) + (" …" if len(dateien) > 5 else "")
                         + " haben sich seit dem Einlesen verändert. Es wurde nichts übernommen - bitte neu einlesen "
                         "(die Häkchen bleiben).")


def veraenderte_dateien(bestand):
    """Prüfung vor dem Übernehmen (F7): Dateien, deren Größe oder Änderungszeit nicht mehr zum Einlesen passt. KID
    merkt sich nur, WO eine Mail in der Datei steht, und liest sie erst beim Übernehmen ganz - in einer veränderten
    Datei (Thunderbird hat komprimiert, Outlook geschrieben) zeigt diese Stelle womöglich auf eine andere Mail."""
    anders = []
    for pfad, vorher in bestand.stand.items():
        try:
            s = os.stat(pfad)
            jetzt = (s.st_size, s.st_mtime_ns)
        except OSError:
            jetzt = None
        if jetzt != vorher:
            anders.append(os.path.relpath(pfad, bestand.quelle) if os.path.isdir(bestand.quelle)
                          else os.path.basename(pfad))
    return sorted(anders)


class _Offen:
    """Hält eine .pst für die Dauer eines Laufs (KI, Import) offen, statt sie je Mail neu zu öffnen. Bei einer Kopie
    aus einem Mail-Programm (`wechselnd`) liegen die Mails in mehreren .pst: Es bleibt jeweils die zuletzt gelesene offen."""
    datei = None
    pfad = None
    wechselnd = False


def _pst(quelle):
    if _Offen.datei is not None and _Offen.pfad == quelle:
        return _Offen.datei, False
    if _Offen.wechselnd:
        if _Offen.datei is not None:
            _Offen.datei.close()
        _Offen.datei, _Offen.pfad = mail_pst.oeffne(quelle), quelle
        return _Offen.datei, False
    return mail_pst.oeffne(quelle), True


class geoeffnet:
    """`with geoeffnet(quelle): …` - lade_mail benutzt darin dieselbe geöffnete .pst (bei anderen Quellen nichts)."""

    def __init__(self, quelle):
        self.quelle = quelle

    def __enter__(self):
        art = quelle_art(self.quelle)
        self.selbst = _Offen.datei is None and art in ("pst", "kopie", "ordner")
        if self.selbst and art == "pst":
            _Offen.datei, _Offen.pfad = mail_pst.oeffne(self.quelle), self.quelle
        elif self.selbst:
            _Offen.wechselnd = True
        return self

    def __exit__(self, *_):
        if self.selbst:
            datei, _Offen.datei, _Offen.pfad, _Offen.wechselnd = _Offen.datei, None, None, False
            if datei is not None:
                datei.close()
        return False


def lade_mail(quelle, ort):
    """Eine Mail der Quelle noch einmal lesen, mit Anhängen (für KI und PDF - eingelesen wird ohne die Inhalte zu
    behalten)."""
    art = quelle_art(quelle)
    if art in ("kopie", "ordner"):
        return lade_mail(os.path.join(quelle, ort[0]), ort[1])
    if art == "pst":
        datei, selbst = _pst(quelle)
        try:
            return mail_lesen.Mail(mail_pst.baue_eml(mail_pst.hole(datei, ort)))
        finally:
            if selbst:
                datei.close()
    if art == "mbox":
        return mail_lesen.Mail(mail_lesen.mbox_mail(quelle, ort))
    with open(ort, "rb") as f:
        return mail_lesen.Mail(f.read())


# Suchtext je Mail: so viel vom Text, Treffer stehen fast immer vorn (KONZEPT_MAIL_AUF_ABRUF, 5.000 Mails = 34 MB)
SUCHTEXT_ZEICHEN = 20000
VORSCHAU_ZEICHEN = 600         # Textanfang für die Vorschau im Fenster (Konzept F8), wie der Suchtext nur im Speicher


class Eintrag:
    """Was der Import über eine Mail weiß. Vom Inhalt nur der Suchtext (normalisiert, gekürzt), und der nur im
    Arbeitsspeicher - er kommt nie auf die Festplatte (KONZEPT_MAIL_AUF_ABRUF, Datenschutz)."""
    __slots__ = ("ort", "ordner", "schluessel", "richtung", "name", "adresse", "datum", "betreff", "vorfilter",
                 "pdf_anhaenge", "anhaenge", "anhang_namen", "personen", "suchtext", "anfang", "ergebnis", "grund", "kopf",
                 "erneut", "voll", "newsletter")

    def __init__(self, ort, ordner, mail, eigene, voll=True):
        """:param voll: False = Phase 1, nur Kopf: Suchtext ohne Text, Vorschau leer, bis `setze_text` den Rest
        bringt (Phase 2, `lies_texte`)."""
        self.ort, self.ordner = ort, ordner
        self.schluessel = mail.schluessel()
        self.kopf = mail_lesen.Kopf(mail.von, mail.an, mail.cc)     # für setze_eigene, nur im Speicher
        self.richtung = mail_lesen.richtung(mail, eigene)
        self.name, self.adresse = mail_lesen.gegenueber(mail, eigene)
        self.datum = mail.datum
        self.betreff = mail.titel
        self.vorfilter = mail_lesen.vorfilter(mail, ordner)
        self.personen = suchsyntax.normalisiere(" ".join((mail.von, mail.an, mail.cc)))
        self.newsletter = mail_lesen.ist_newsletter(mail)    # am Kopf erkannt; dazu die Regeln des Nutzers (ist_newsletter)
        self.ergebnis, self.grund = "", ""
        self.erneut = False            # schon importiert, vom Nutzer bewusst wieder freigegeben (erneut_freigeben)
        self.setze_text(text_felder(mail, self.personen, mit_text=voll))

    def setze_text(self, felder):
        """Ergebnis von `text_felder` übernehmen (Phase 2 im Tk-Thread über `Bestand.setze_text`)."""
        self.pdf_anhaenge, self.anhaenge = felder["pdf_anhaenge"], felder["anhaenge"]
        self.anhang_namen, self.suchtext = felder["anhang_namen"], felder["suchtext"]
        self.anfang, self.voll = felder["anfang"], felder["voll"]


def text_felder(mail, personen, mit_text=True):
    """Was Text und Anhänge zum Eintrag beitragen. Ohne Text (Phase 1) nur Betreff, Personen und Anhangnamen, die
    Anhänge ohne ihren Inhalt. Ändert nichts und darf darum im Hintergrund laufen (Phase 2). Phase 1 und 2 liefern
    zusammen genau dasselbe wie das Einlesen in einem Zug - derselbe Code. :return: dict für `Eintrag.setze_text`"""
    if mit_text:
        art, text, _, anhaenge, _ = mail.koerper()
        if art == "html":
            text = mail_lesen.html_zu_suchtext(text)
    else:
        text, anhaenge = "", mail.anhaenge_ohne_inhalt()
    suchtext = " ".join((suchsyntax.normalisiere(mail.betreff), personen,
                         suchsyntax.normalisiere(" ".join(a["name"] for a in anhaenge)),
                         suchsyntax.normalisiere(text)[:SUCHTEXT_ZEICHEN]))
    return {"pdf_anhaenge": sum(1 for a in anhaenge if _ist_pdf_anhang(a)), "anhaenge": len(anhaenge),
            "anhang_namen": ", ".join(a["name"] for a in anhaenge), "suchtext": suchtext,
            "anfang": " ".join(text.split())[:VORSCHAU_ZEICHEN], "voll": mit_text}


def _ist_pdf_anhang(a):
    return a["daten"][:5] == b"%PDF-" or (a["typ"] == "application/pdf" and a["name"].lower().endswith(".pdf"))


class Bestand:
    """Ergebnis des Einlesens: Einträge (ohne Doppelte) und Zahlen."""

    def __init__(self, quelle):
        self.quelle = quelle
        self.eintraege = []
        self.zahlen = collections.Counter()
        self.wortschatz = set()            # alle Wörter der Suchtexte, für die leichte Unschärfe (suche)
        self._aehnlich = {}                # Begriff → ähnliche Wörter, je Bestand einmal gesucht
        self.stand = {}                    # Pfad → (Größe, Änderungszeit) beim Einlesen (veraenderte_dateien)
        self.fehlende_dateien = []         # Dateien eines Ordners, die sich nicht lesen ließen (relativ)
        self.gesendet_von = collections.Counter()   # Absender-Adressen in Ordnern „Gesendet“ (eigene_vorschlaege)

    def setze_text(self, e, felder):
        """Phase 2: Text einer Mail nachtragen - nur im Tk-Thread, damit eine laufende Suche nichts Halbes sieht."""
        e.setze_text(felder)
        self.wortschatz.update(felder.get("woerter", ()))
        self._aehnlich.clear()             # die Unschärfe kennt jetzt mehr Wörter

    def ohne_text(self):
        return sum(1 for e in self.eintraege if not e.voll)


def _als_mail(daten):
    """.eml-Bytes oder schon eine Mail (`KopfMail` aus einer .pst, S3b)."""
    return daten if isinstance(daten, mail_lesen.Mail) else mail_lesen.Mail(daten)


def lies_quelle(quelle, journal, ab=None, bis=None, abbrechen=None, fortschritt=None, nur_kopf=False, lage=None):
    """
    Liest alle Mails der Quelle einmal (Inhalte werden nicht behalten) und zählt: gesamt, unlesbar, doppelt
    (innerhalb der Quelle), schon importiert, außerhalb des Zeitraums, je Vorfilter-Grund.
    :param ab, bis: datetime.date oder None (E7: der Zeitraum wird je Lauf gewählt)
    :param abbrechen: Callable → True bricht ab (Bestand bis dahin)
    :param fortschritt: Callable(anzahl, datei) alle 200 Mails; datei = „Datei 7 von 25“ bei einem Ordner, sonst ""
    :param nur_kopf: Phase 1 (Peter 09.11.2026): Einträge nur aus dem Kopf, den Text holt `lies_texte` nach. Mails
                     ohne Message-ID werden trotzdem ganz gelesen: ihre Kennung braucht den Textanfang (0,5 % gemessen).
    :param lage: dict für die Fortschrittsanzeige, wird laufend gefüllt: „n“ Mails, „teil“ 0…1, „nr“/„gesamt“ Dateien
    """
    eigene = set(journal.eigene)
    bestand = Bestand(quelle)
    gesehen = set()
    lage = {} if lage is None else lage
    lage.update(n=0, teil=0.0)
    zuletzt = {}                           # die eben für `nur_kopf` zerlegte Mail, damit sie nicht zweimal zerlegt wird

    def ganz_noetig(daten):
        mail = _als_mail(daten)
        zuletzt["daten"], zuletzt["mail"] = daten, mail
        return not mail.message_id

    roh = _roh_mails(quelle, bestand.zahlen, bestand.stand, bestand.fehlende_dateien, lage,
                     ganz_noetig if nur_kopf else None)
    for n, (ort, ordner, daten) in enumerate(roh, 1):
        lage["n"] = n
        if abbrechen and abbrechen():
            bestand.zahlen["abgebrochen"] = 1
            break
        if fortschritt and n % 200 == 0:
            fortschritt(n, f"Datei {lage['nr']} von {lage['gesamt']}" if lage.get("gesamt", 0) > 1 else "")
        bestand.zahlen["gesamt"] += 1
        if not daten:
            bestand.zahlen["unlesbar"] += 1
            continue
        try:
            mail = zuletzt["mail"] if zuletzt.get("daten") is daten else _als_mail(daten)
            zuletzt.clear()
            e = Eintrag(ort, ordner, mail, eigene, voll=not nur_kopf or not mail.message_id)
        except Exception:                  # noqa: BLE001 - nie still verwerfen: wird gezählt und gemeldet
            bestand.zahlen["unlesbar"] += 1
            continue
        if e.schluessel in gesehen:
            bestand.zahlen["doppelt"] += 1
            continue
        gesehen.add(e.schluessel)
        if mail_lesen.ist_gesendet_ordner(ordner):
            bestand.gesendet_von.update(mail.von_adressen)
        bestand.wortschatz.update(suchsyntax.WORT.findall(e.suchtext))
        bestand.zahlen[e.richtung] += 1
        if e.schluessel in journal.importiert:
            e.ergebnis = "importiert"
            e.grund = GRUND_ZURUECKGENOMMEN if journal.importiert[e.schluessel].get("zurueckgenommen") else "schon importiert"
            bestand.zahlen["schon importiert"] += 1
        elif e.datum and ((ab and e.datum.date() < ab) or (bis and e.datum.date() > bis)):
            # ohne Datum lässt sich der Zeitraum nicht prüfen - dann bleibt die Mail drin (nie still verwerfen)
            e.ergebnis, e.grund = "zeitraum", "außerhalb des Zeitraums"
            bestand.zahlen["außerhalb des Zeitraums"] += 1
        elif e.vorfilter:
            bestand.zahlen["Vorfilter: " + e.vorfilter] += 1
        bestand.eintraege.append(e)
    return bestand


class Einzelleser:
    """Einzelne Mails der Quelle gezielt lesen (Phase 2, die sichtbaren zuerst - Peter 09.11.2026). Liefert dieselben
    Bytes wie `_roh_mails`. Hält je .pst eine eigene geöffnete Datei: `_Offen` gehört dem Übernehmen, das gleichzeitig
    laufen darf. Nur in einem Thread benutzen, danach `schliesse`."""

    def __init__(self, quelle):
        self.quelle = quelle
        self._pst = {}
        self._art = {}

    def _art_von(self, pfad):
        if pfad not in self._art:
            self._art[pfad] = quelle_art(pfad)
        return self._art[pfad]

    def hole(self, ort):
        pfad = self.quelle
        if self._art_von(pfad) in ("kopie", "ordner"):
            pfad, ort = os.path.join(self.quelle, ort[0]), ort[1]
        art = self._art_von(pfad)
        if art == "pst":
            if pfad not in self._pst:
                self._pst[pfad] = mail_pst.oeffne(pfad)
            return _pst_lesen(mail_pst.hole(self._pst[pfad], ort), direkt=True)
        if art == "mbox":
            return mail_lesen.mbox_mail(pfad, ort)
        with open(ort, "rb") as f:
            return f.read()

    def schliesse(self):
        for datei in self._pst.values():
            datei.close()
        self._pst.clear()


def lies_texte(bestand, melde, abbrechen=None, lage=None, vorne=None):
    """Phase 2 (KONZEPT_MAIL_AUF_ABRUF „Schneller einlesen“): den Text der Mails nachlesen, die Phase 1 nur mit dem
    Kopf kennt - ein zweiter Durchgang durch die Quelle. Läuft im Hintergrund und ändert den Bestand NICHT selbst:
    `melde(eintrag, felder)` bekommt je Mail das Ergebnis von `text_felder` samt „woerter“, übernommen wird im
    Tk-Thread mit `Bestand.setze_text`. Passt die Kennung nicht mehr (Datei inzwischen verändert), bleibt die Mail
    ohne Text. :param lage: dict, laufend „n“ (erledigt) und „gesamt“.
    :param vorne: Callable → Liste von Einträgen, die vor der Reihe dran sind (die sichtbaren Zeilen, Bauschritt S2);
                  geholt über `Einzelleser`. Eine neue Liste (anderes Objekt) wird beim nächsten Schritt abgearbeitet.
    :return: Zahl der Mails mit Text"""
    offen = {e.ort: e for e in bestand.eintraege if not e.voll}
    lage = {} if lage is None else lage
    lage.update(n=0, gesamt=len(offen))
    gelesen = 0
    if not offen:
        return 0
    roh = _roh_mails(bestand.quelle, collections.Counter(), direkt=True)
    leser = Einzelleser(bestand.quelle)
    try:
        gelesen = _lies_texte(roh, offen, melde, abbrechen, lage, vorne, leser)
    finally:
        roh.close()                        # Dateien sofort zu: die Kopie soll sich gleich danach löschen lassen
        leser.schliesse()
    return gelesen


def _text_melden(e, daten, melde):
    """:return: 1, wenn die Mail ihren Text bekommen hat"""
    try:
        mail = _als_mail(daten)
        if mail.schluessel() != e.schluessel:
            return 0
        felder = text_felder(mail, e.personen)
    except Exception:                      # noqa: BLE001 - die Mail bleibt ohne Text, der Kopf ist ja da
        return 0
    felder["woerter"] = set(suchsyntax.WORT.findall(felder["suchtext"]))
    melde(e, felder)
    return 1


def _lies_texte(roh, offen, melde, abbrechen, lage, vorne, leser):
    gelesen, liste = 0, None
    for ort, _ordner, daten in roh:
        neu = vorne() if vorne is not None else None
        if neu is not None and neu is not liste:
            liste = neu
            for e in liste:                # die sichtbaren zuerst, gezielt geholt
                if abbrechen and abbrechen():
                    return gelesen
                if offen.pop(e.ort, None) is None:
                    continue
                lage["n"] += 1
                try:
                    einzeln = leser.hole(e.ort)
                except Exception:          # noqa: BLE001 - dann eben der Reihe nach (die Mail ist aus offen heraus)
                    continue
                gelesen += _text_melden(e, einzeln, melde)
        if abbrechen and abbrechen():
            break
        e = offen.pop(ort, None)
        if e is None:
            continue
        lage["n"] += 1
        gelesen += _text_melden(e, daten, melde)
        if not offen:
            break
    return gelesen


# ---------------------------------------------------------------- Eigene Adressen aus gesendeten Mails
# Ab so vielen Mails im Ordner „Gesendet“ gilt ein Absender als Vorschlag: Einzelne fremde Mails dort (verschoben,
# weitergeleitet) sollen nicht als eigene Adresse durchgehen.
EIGENE_MINDESTENS = 3


def eigene_vorschlaege(bestand, eigene, abgelehnt=(), mindestens=EIGENE_MINDESTENS):
    """Absender aus Ordnern für gesendete Mails, die noch nicht als eigene gelten (Peter 08.11.2026: nicht jedes Mal
    alle alten Adressen eintippen). Ohne die schon abgelehnten. :return: [(Adresse, Anzahl)], häufigste zuerst"""
    abgelehnt = {a.lower() for a in abgelehnt}
    funde = [(a, n) for a, n in bestand.gesendet_von.items()
             if n >= mindestens and a not in abgelehnt and not mail_lesen.ist_eigene(a, eigene)]
    return sorted(funde, key=lambda f: (-f[1], f[0]))


def setze_eigene(bestand, eigene):
    """Richtung und Gegenüber aller Einträge nach geänderten eigenen Adressen neu - aus den gemerkten Adresszeilen,
    ohne die Quelle neu zu lesen. Die Zahlen „eingegangen“/„gesendet“ werden nachgezogen."""
    for e in bestand.eintraege:
        e.richtung = mail_lesen.richtung(e.kopf, eigene)
        e.name, e.adresse = mail_lesen.gegenueber(e.kopf, eigene)
    richtungen = collections.Counter(e.richtung for e in bestand.eintraege)
    bestand.zahlen["ein"], bestand.zahlen["aus"] = richtungen["ein"], richtungen["aus"]


# ---------------------------------------------------------------- Suchen (KONZEPT_MAIL_AUF_ABRUF)
JAHR = re.compile(r"^(19[89]\d|20\d\d)$")


def ist_newsletter(e, regeln=()):
    """Newsletter: am Kopf erkannt (`Eintrag.newsletter`) oder Absender bzw. dessen Domäne in den Regeln des Nutzers
    (`Journal.newsletter`, Einträge wie „info@firma.de“ oder „@firma.de“)."""
    return e.newsletter or any(a in regeln or mail_lesen.domain_schluessel(a) in regeln for a in e.kopf.von_adressen)


def newsletter_regel(regeln, adressen, domaene=False, an=True):
    """Absender (oder ihre Domänen) in die Liste `regeln` aufnehmen bzw. daraus nehmen - beim Herausnehmen beides,
    Adresse und Domäne. :return: Zahl der Änderungen"""
    vorher = len(regeln)
    for a in adressen:
        if an:
            eintrag = mail_lesen.domain_schluessel(a) if domaene else a
            if eintrag not in regeln:
                regeln.append(eintrag)
        else:
            for eintrag in (a, mail_lesen.domain_schluessel(a)):
                while eintrag in regeln:
                    regeln.remove(eintrag)
    return abs(len(regeln) - vorher)


class Suchergebnis:
    """Was `suche` findet.
    treffer: [(Eintrag, unscharf)], neueste zuerst, ohne Datum am Ende; unscharf = passt nur über eine ähnliche
    Schreibweise (das Fenster zeigt „≈“). varianten: Counter der ähnlichen Schreibweisen, die zusätzlich getroffen
    haben („auch gefunden als“). jahre: (erstes, letztes) aus dem Suchtext oder None."""

    def __init__(self):
        self.treffer, self.varianten, self.jahre = [], collections.Counter(), None
        self.newsletter = 0                # so viele passten, sind aber als Newsletter ausgeblendet

    @property
    def schon_drin(self):
        return sum(1 for e, _ in self.treffer if e.ergebnis == "importiert")


def zerlege_suche(text, zeitraum_frei=True):
    """Suchtext → (normalisierte Begriffe, (erstes, letztes Jahr) oder None). Eine allein stehende Jahreszahl gilt
    als Zeitraum, solange die Zeitraum-Felder leer sind (Konzept F4 b, Peters Beispiel „Vivafone 2024“); in
    Anführungszeichen bleibt sie Text, bei ausgefülltem Zeitraum auch."""
    begriffe, jahre = [], []
    for b in suchsyntax.split_terms(text):
        if zeitraum_frei and JAHR.match(b):
            jahre.append(int(b))
        else:
            begriffe.append(suchsyntax.normalisiere(b))
    return begriffe, ((min(jahre), max(jahre)) if jahre else None)


def _pruefer(begriff, bestand):
    """Prüf-Funktion für einen Begriff: Suchtext → (passt, Variante); Variante = die ähnliche Schreibweise, über die
    er passt, None bei einem wörtlichen Treffer. Genau gelten "Wort in Anführungszeichen", Phrasen und Platzhalter."""
    if len(begriff) > 2 and begriff[0] == '"' and begriff[-1] == '"':
        genau = re.compile(r"(?<![^\W_])" + re.escape(begriff[1:-1]) + r"(?![^\W_])")
        return lambda t: (genau.search(t) is not None, None)
    if "*" in begriff or "?" in begriff:
        muster = re.compile(fnmatch.translate(f"*{begriff}*"), re.DOTALL)
        return lambda t: (muster.match(t) is not None, None)
    if " " in begriff:
        return lambda t: (begriff in t, None)
    if begriff not in bestand._aehnlich:
        bestand._aehnlich[begriff] = sorted(suchsyntax.aehnliche_woerter(begriff, bestand.wortschatz))
    varianten = bestand._aehnlich[begriff]

    def pruefe(t):
        if begriff in t:
            return True, None
        for v in varianten:
            if v in t:
                return True, v
        return False, None
    return pruefe


def suche(bestand, text="", ab=None, bis=None, von_an="", richtung=None, nur_anhang=False, auch_vorfilter=False,
          ohne_newsletter=False, newsletter_regeln=()):
    """
    Filtert die eingelesenen Mails, ohne die Quelle erneut zu lesen (KONZEPT_MAIL_AUF_ABRUF).
    :param text: wie die Dokumentsuche: mehrere Wörter = UND, "…" genau, * und ? Platzhalter; dazu die leichte
                 Unschärfe ab 5 Buchstaben (suchsyntax.aehnliche_woerter) und Umlaute = ae/oe/ue/ss
    :param ab, bis: datetime.date oder None; sind beide leer, gilt eine Jahreszahl im Suchtext als Zeitraum
    :param von_an: Text in Absender oder Empfängern, genau (Umlaute gleich)
    :param richtung: "ein", "aus" oder None
    :param auch_vorfilter: auch Spam, Papierkorb, Entwürfe und Lesebestätigungen (Konzept F3)
    :param ohne_newsletter: Newsletter ausblenden (`ist_newsletter` mit `newsletter_regeln`), gezählt in
                            `Suchergebnis.newsletter` - nur auf Wunsch (Peter 12.11.2026)
    :return: Suchergebnis. Mails ohne Datum fallen bei keinem Zeitraum heraus (nie still verwerfen).
    """
    ergebnis = Suchergebnis()
    begriffe, jahre = zerlege_suche(text, zeitraum_frei=not (ab or bis))
    if jahre:
        ergebnis.jahre = jahre
        ab, bis = datetime.date(jahre[0], 1, 1), datetime.date(jahre[1], 12, 31)
    pruefer = [_pruefer(b, bestand) for b in begriffe]
    von_an = suchsyntax.normalisiere(von_an)
    for e in bestand.eintraege:
        if (e.vorfilter and not auch_vorfilter) or (richtung and e.richtung != richtung) or (nur_anhang and not e.anhaenge):
            continue
        if e.datum and ((ab and e.datum.date() < ab) or (bis and e.datum.date() > bis)):
            continue
        if von_an and von_an not in e.personen:
            continue
        varianten = set()
        for p in pruefer:                  # billige Prüfungen oben zuerst, die Unschärfe zuletzt
            passt, variante = p(e.suchtext)
            if not passt:
                break
            if variante:
                varianten.add(variante)
        else:
            if ohne_newsletter and ist_newsletter(e, newsletter_regeln):
                ergebnis.newsletter += 1
                continue
            ergebnis.treffer.append((e, bool(varianten)))
            ergebnis.varianten.update(varianten)
    ergebnis.treffer.sort(key=lambda t: (t[0].datum is None, -t[0].datum.timestamp() if t[0].datum else 0))
    return ergebnis


# ---------------------------------------------------------------- Ausführen
_UNERLAUBT = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def dateiname(datum, titel, endung=".pdf"):
    """`JJJJMMTT_Betreff.pdf` nach der bestehenden Regel (dateinamen.py), Windows-tauglich gekürzt."""
    stamm = _UNERLAUBT.sub(" ", titel or "").strip(" .") or "ohne Betreff"
    stamm = " ".join(stamm.split())[:80].rstrip(" .")
    return f"{datum.strftime('%Y%m%d') if datum else '00000000'}_{stamm}{endung}"


def _frei(ordner, name):
    """Ein freier Dateiname: bei Gleichstand „ (2)“, „ (3)“ … - zwei Mails desselben Tages mit gleichem Betreff
    sind zwei Dokumente (anders als beim Umbenennen gibt es hier kein Original, das ersetzt würde)."""
    stamm, endung = os.path.splitext(name)
    kandidat, i = name, 1
    while os.path.exists(os.path.join(ordner, kandidat)):
        i += 1
        kandidat = f"{stamm} ({i}){endung}"
    return os.path.join(ordner, kandidat)


def importiere(bestand, journal, ziel_ordner, abbrechen=None, fortschritt=None, anhaenge=True, direkt=False):
    """
    Legt jede Mail mit Ergebnis UEBERNEHMEN als Mail-PDF in `ziel_ordner` (Posteingang), PDF-Anhänge zusätzlich
    als eigene Dokumente (E2) - alle mit derselben KID_MAILID. Jede fertige Mail kommt sofort ins Journal
    (Fortsetzen nach Abbruch, nie doppelt).
    :param anhaenge: False = PDF-Anhänge stecken nur in der eingebetteten Original-Mail
    :param direkt: `ziel_ordner` ist ein gewählter Ordner der Sammlung, kein Posteingang (KONZEPT_MAIL_AUF_ABRUF F6):
        ohne KI und ohne Sammelablage (E17); die Mail trägt den Betreff als Titel ohnehin, ein Anhang bekommt seinen
        Dateinamen als Titel (im Posteingang gibt ihm die Vollautomatik einen)
    :return: Counter mit "mails", "anhaenge", "fehler"
    """
    zahlen = collections.Counter()
    offen = [e for e in bestand.eintraege
             if e.ergebnis == UEBERNEHMEN and (e.schluessel not in journal.importiert or e.erneut)]
    if offen:
        anders = veraenderte_dateien(bestand)
        if anders:
            raise QuelleVeraendert(anders)
    os.makedirs(ziel_ordner, exist_ok=True)
    einzelne = frozenset() if direkt else einzelne_mails(bestand)
    with geoeffnet(bestand.quelle):
        return _importiere(bestand, offen, journal, ziel_ordner, abbrechen, fortschritt, anhaenge, zahlen, einzelne,
                           direkt)


def _ablage_schluessel(e):
    """Wem eine Mail in der Sammlung gehört: der Name, ohne Namen die Domain, bei Mail-Anbietern die Adresse."""
    if e.name:
        return e.name.casefold()
    domain = (e.adresse or "").rpartition("@")[2].split(".")
    if len(domain) >= 2 and domain[-2] not in ANBIETER:
        return ".".join(domain[-2:])
    return e.adresse or ""


def _je_absender(bestand):
    """{Absender: [Einträge]} aller Mails, die in der Sammlung sind oder hinein sollen."""
    gruppen = collections.defaultdict(list)
    for e in bestand.eintraege:
        if e.ergebnis in (UEBERNEHMEN, "importiert"):
            gruppen[_ablage_schluessel(e)].append(e)
    return gruppen


def einzelne_mails(bestand):
    """E17: Schlüssel der Mails ohne PDF-Anhang, die allein von ihrem Absender kommen. Sie bekommen keinen eigenen Ordner,
    die Vollautomatik legt sie in die Sammelablage (auto_pilot.SAMMEL_ORDNER): Betatest, 66 von 192 Ordnern mit einem
    einzigen Dokument. Nur der Import kennt alle Mails eines Laufs, darum entscheidet er das und nicht die Vollautomatik."""
    return {g[0].schluessel for g in _je_absender(bestand).values()
            if len(g) == 1 and g[0].ergebnis == UEBERNEHMEN and not g[0].pdf_anhaenge}


def vorschau(bestand, bekannt=None):
    """Was „Übernehmen“ bewirkt: {"mails", "anhaenge", "einzelne", "neue_ordner"}. Die Ordner sind eine Schätzung: Die
    Vollautomatik liest erst den Text und führt ähnliche Namen zusammen."""
    neu = [e for e in bestand.eintraege if e.ergebnis == UEBERNEHMEN]
    einzelne = einzelne_mails(bestand)
    ordner = sum(1 for g in _je_absender(bestand).values()
                 if not (len(g) == 1 and g[0].schluessel in einzelne)
                 and any(e.ergebnis == UEBERNEHMEN for e in g)
                 and not (bekannt and bekannt(g[0].name, g[0].adresse)))
    return {"mails": len(neu), "anhaenge": sum(e.pdf_anhaenge for e in neu), "einzelne": len(einzelne), "neue_ordner": ordner}


# Gemessen an 394 echten Mails (06.11.2026): Mit 70 % bleibt 1 unter 75 % ihres Textes, mit 50 % wären es 51.
MIN_ANTEIL_TEXT = 0.7


def _schreibe_in_passender_stufe(pfad, mail, richtung, felder, zahlen):
    """Mail-PDF in der ersten Darstellung, die auf Seiten passt und genug vom sichtbaren Text zeigt (FALLSTRICKE #103,
    #108). Reiner Text ist der letzte Ausweg."""
    for stufe, zaehler in ((mail_lesen.VOLL, ""), (mail_lesen.OHNE_LAYOUT, "layout_aufgeloest"),
                           (mail_lesen.OHNE_TABELLEN, "layout_aufgeloest"), (mail_lesen.NUR_TEXT, "vereinfacht")):
        stile, seite, bilder = mail_lesen.seite_html(mail, richtung, stufe=stufe)
        mindest = 0 if stufe == mail_lesen.NUR_TEXT else int(MIN_ANTEIL_TEXT * mail_lesen.sichtbare_zeichen(seite))
        try:
            PDFHandler.schreibe_mail_pdf(pfad, seite, stile, bilder, mail.daten, felder, mindest_zeichen=mindest)
        except MailZuLang:
            if stufe == mail_lesen.NUR_TEXT:
                raise
            continue
        if zaehler:
            zahlen[zaehler] += 1
        return


def anhang_titel(name):
    """Titel eines PDF-Anhangs beim direkten Ablegen: sein Dateiname ohne Endung, „_“ als Leerzeichen."""
    return " ".join(os.path.splitext(name or "")[0].replace("_", " ").split())


def _importiere(bestand, offen, journal, ziel_ordner, abbrechen, fortschritt, anhaenge, zahlen, einzelne=frozenset(),
                direkt=False):
    eigene = set(journal.eigene)
    try:
        for i, e in enumerate(offen, 1):
            if abbrechen and abbrechen():
                break
            if fortschritt:
                fortschritt(i, len(offen))
            try:
                mail = lade_mail(bestand.quelle, e.ort)
                richtung = mail_lesen.richtung(mail, eigene)
                name, adresse = mail_lesen.gegenueber(mail, eigene)
                felder = {"title": mail.titel, "author": mail.von, "KID_DokumentenDatum": mail_lesen.datum_text(mail),
                          "KID_Absender": name or adresse, "KID_MailID": e.schluessel, "KID_Richtung": richtung,
                          "KID_Einzeln": "1" if e.schluessel in einzelne else "",
                          "KID_Eigen": mail_lesen.eigene_namen(mail, eigene)}
                pfad = _frei(ziel_ordner, dateiname(mail.datum, mail.titel))
                _schreibe_in_passender_stufe(pfad, mail, richtung, felder, zahlen)
            except Exception:              # noqa: BLE001 - gezählt, die Mail bleibt offen für den nächsten Lauf
                zahlen["fehler"] += 1
                continue
            zahlen["mails"] += 1
            dateien = [os.path.basename(pfad)]
            if anhaenge:
                for a in mail.koerper()[3]:
                    if not _ist_pdf_anhang(a):
                        continue
                    stamm = os.path.splitext(a["name"])[0]
                    ziel = _frei(ziel_ordner, dateiname(mail.datum, stamm))
                    try:
                        PDFHandler.schreibe_anhang_pdf(ziel, a["daten"], {
                            "KID_MailID": e.schluessel, "KID_Absender": name or adresse,
                            "KID_DokumentenDatum": mail_lesen.datum_text(mail),      # Ersatz: auto_pilot.mit_mailkopf
                            "KID_Erfasst": scan_date.to_storage(datetime.datetime.now()),
                            "title": anhang_titel(a["name"]) if direkt else ""})
                    except (ValueError, OSError):
                        zahlen["anhang_fehler"] += 1
                        continue
                    zahlen["anhaenge"] += 1
                    dateien.append(os.path.basename(ziel))
            journal.importiert[e.schluessel] = {"dateien": dateien, "am": datetime.date.today().isoformat()}
            e.ergebnis, e.grund, e.erneut = "importiert", "eben importiert", False
            if zahlen["mails"] % 20 == 0:
                journal.speichere()
    finally:
        journal.speichere()
    return zahlen


def finde_importierte(master_folder, schluessel, abbrechen=None):
    """
    Wo liegen die PDFs importierter Mails heute? Die Vollautomatik hat sie verschoben und umbenannt, sicher ist nur die
    KID_MAILID im PDF - auch die PDF-Anhänge tragen sie. Liest die Metadaten aller PDFs, also nur im Hintergrund.
    :param schluessel: Schlüssel aus dem Journal
    :return: {Schlüssel: [Pfade]}, ohne Mails, von denen nichts mehr da ist
    """
    # Im PDF steht die bereinigte Form (build_kid_subject): ein Zeilenumbruch in der Message-ID ist dort weg
    gesucht = {PDFHandler.bereinige_absender(s): s for s in schluessel}
    gefunden = collections.defaultdict(list)
    for wurzel, _ordner, dateien in os.walk(master_folder):
        for name in dateien:
            if abbrechen and abbrechen():
                return dict(gefunden)
            if name.lower().endswith(".pdf"):
                pfad = os.path.join(wurzel, name)
                s = gesucht.get(PDFHandler.get_metadata(pfad).get("KID_MailID"))
                if s:
                    gefunden[s].append(pfad)
    return dict(gefunden)


GRUND_ZURUECKGENOMMEN = "aus der Sammlung genommen"


def erneut_freigeben(bestand, schluessel):
    """Schon importierte Mails wieder anhakbar machen (Peter 09.11.2026: von Hand aus KID gelöschte Mails bleiben
    ausgegraut, zurück nur bewusst über „Erneut übernehmen…“). Das Journal bleibt unberührt, bis wirklich übernommen
    wird - ohne Übernehmen sind sie beim nächsten Einlesen wieder ausgegraut. :return: Zahl freigegebener Mails"""
    n = 0
    for e in bestand.eintraege:
        if e.schluessel in schluessel and e.ergebnis == "importiert":
            e.ergebnis, e.grund, e.erneut = "", "", True
            n += 1
    return n


def merke_zurueckgenommen(bestand, journal, schluessel):
    """Die Mails bleiben als importiert im Journal - sonst kämen sie beim nächsten Einlesen wieder. Danach
    `journal.speichere()`."""
    for e in bestand.eintraege:
        if e.schluessel in schluessel and e.schluessel in journal.importiert:
            journal.importiert[e.schluessel]["zurueckgenommen"] = datetime.date.today().isoformat()
            e.grund = GRUND_ZURUECKGENOMMEN


def protokoll_zeile(zahlen):
    """Nur Zahlen (Datenschutz): „gesamt 120, doppelt 3, …“."""
    return ", ".join(f"{k} {v}" for k, v in sorted(zahlen.items()) if v)
