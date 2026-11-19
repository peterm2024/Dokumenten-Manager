"""
Wiki von Hand (KONZEPT_WIKI_VON_HAND.md, „Neuer Aufbau: freie Angaben statt fester Felder“, 12.11.2026, Schritt N2): die
bestätigte Wissensbasis einer Sammlung. Es steht nur drin, was ein Mensch angelegt oder bestätigt hat.

Ein Eintrag hat
- eine Schublade (`art`): nur die Ordnung der Liste, ohne eigene Felder. Die Schubladen stehen in der Datei und sind
  erweiterbar (`art_neu`, `art_umbenennen`, `arten_zusammenlegen`); neu angelegte Dateien bekommen `START_ARTEN`.
- eine Bezeichnung und eine Notiz,
- Angaben (seit 19.11.2026, Schema 5, KONZEPT_WIKI_VON_HAND „Umbau: Angaben als ‚Merkmal: Wert‘“): ein Merkmal mit
  einem Wert („Telefon“ / „01234 56789“, „Beitrag“ / „140,86 €“). Von Hand darf das Merkmal fehlen (freie Zeile).
  Gleiches Merkmal mit gleichem Wert gibt es je Eintrag nur einmal; jedes Dokument, aus dem sie stammt, ist eine
  Quelle (Dokument-ID, Titel, wörtliches Zitat, Dokumentdatum). Gleiches Merkmal mit verschiedenen Werten ist ein
  Verlauf: `lade` liefert je Merkmal den Wert mit der jüngsten Quelle zuerst (`aktuell`).
- Belege: die Dokumente des Eintrags (über ihre KID_ID, also auch nach Verschieben und Umbenennen). Das Dokument einer
  Angabe ist immer auch Beleg.
- Verbindungen zu anderen Einträgen („Verbunden mit“), ohne Richtung.

Abgelehntes (13.11.2026): Was der Mensch aus einem Dokument nicht ins Wiki wollte (im Fenster „Aus dem Dokument“
abgehakt, oder eine Angabe aus einem Dokument entfernt), steht je Dokument-ID in `abgelehnt` (`ablehnen`,
`abgelehnte`). Ein neuer Lauf über dasselbe Dokument schlägt es nicht wieder vor (tools/wiki_dinge.py).

Ausgeschlossene Merkmale (15.11.2026, KONZEPT_ORDNER_STECKBRIEF.md Schritt 3): Der Ordner-Steckbrief wird berechnet,
nicht gespeichert; hier steht nur, welches Merkmal (Art, Wert) der Mensch für einen Ablageordner verworfen hat
(`merkmal_ausschliessen`, `merkmal_zulassen`, `ausgeschlossene_merkmale`). Der Ordner steht mit seinem Namen in der
Sammlung - nach dem Umbenennen gilt der Ausschluss nicht mehr (dann bildet sich auch der Steckbrief neu).

Bis 12.11.2026 hatte jede Art feste Felder (Kennzeichen, Halter …). Peters Test an einer Rechnung zeigte: Dokumente
passen selten in ein Schema. Eine Datei im alten Aufbau wird beim ersten Zugriff als `wissen_alt.sqlite` beiseitegelegt
und leer neu begonnen (Peter: keine Rücksicht auf vorhandene Einträge). Neuere Dateien werden nachgerüstet
(`_NACHRUESTEN`, Version 2 → 3: Tabelle `abgelehnt`, 3 → 4: `merkmal_aus`). Beim Schritt 4 → 5 werden die Angaben
geleert (freie Sätze lassen sich nicht sinnvoll in Merkmal und Wert zerlegen, Peter 19.11.2026: „Angaben leeren“ - die
KI liest die Belege neu) und mit ihnen das Abgelehnte (es waren Sätze); Schubladen, Einträge, Belege, Verbindungen und
die Ausschlüsse der Ablageordner bleiben.

Speicher: `wissen.sqlite` im Daten-Ordner der Sammlung (app_paths.wissen_path). Jede Änderung ist eine Transaktion;
`sichere()` legt beim Öffnen des Fensters `wissen.sqlite.bak` an. Verbindungen sind kurzlebig (je Aufruf eine), damit
das Modul aus jedem Thread nutzbar bleibt. Die Spalte `geprueft` stammt aus dem Plan für Bauschritt 3b (Prüfung der
Texte durch die KI, am 13.11.2026 verworfen) und wird nur noch geleert.

GUI-frei, nur Standardbibliothek. Datenschutz: ins Protokoll gehen nur Zahlen.
"""
import datetime
import logging
import os
import re
import sqlite3

import app_paths

START_ARTEN = ("Person", "Firma", "Behörde", "Immobilie", "Fahrzeug", "Vertrag", "Versicherung", "Sonstiges")
MAX_ANGABE = 300                      # Zeichen je Angabe - eine Zeile, kein Aufsatz
MAX_MERKMAL = 40                      # ein Merkmal ist ein kurzer Name („Versicherungsnummer“), kein Satz
# Peter 19.11.2026: Die eigene Adresse steht in jedem Dokument - ab so vielen Quellen ist eine Angabe „in vielen
# Dokumenten belegt“: weitere Dokumente zählen als Quelle (Anzahl, Stand), werden aber nicht mehr Beleg des Eintrags.
MAX_BELEG_QUELLEN = 5
SCHEMA = 5                            # 3 (13.11.2026): `abgelehnt`; 4 (15.11.2026): `merkmal_aus`; 5 (19.11.2026): Merkmal + Wert
ALTER_AUFBAU = 2                      # darunter: feste Felder (bis 12.11.2026), wird beiseitegelegt
_TABELLEN = """
CREATE TABLE art (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, reihe INTEGER NOT NULL);
CREATE TABLE eintrag (
    id INTEGER PRIMARY KEY, art INTEGER NOT NULL REFERENCES art(id), bezeichnung TEXT NOT NULL,
    notiz TEXT NOT NULL DEFAULT '', geprueft TEXT NOT NULL DEFAULT '', angelegt TEXT NOT NULL, geaendert TEXT NOT NULL);
CREATE TABLE beleg (
    id INTEGER PRIMARY KEY, eintrag INTEGER NOT NULL REFERENCES eintrag(id) ON DELETE CASCADE, kid_id TEXT NOT NULL,
    titel TEXT NOT NULL DEFAULT '', UNIQUE (eintrag, kid_id));
CREATE TABLE verbindung (
    a INTEGER NOT NULL REFERENCES eintrag(id) ON DELETE CASCADE,
    b INTEGER NOT NULL REFERENCES eintrag(id) ON DELETE CASCADE, PRIMARY KEY (a, b), CHECK (a < b));
"""
# Was der Mensch aus einem Dokument abgelehnt hat (abgehakt oder entfernt) - je Dokument, damit ein neuer Lauf über
# dasselbe Dokument es nicht wieder vorschlägt (Peter 13.11.2026).
_ABGELEHNT = """
CREATE TABLE abgelehnt (
    id INTEGER PRIMARY KEY, kid_id TEXT NOT NULL, text TEXT NOT NULL, zitat TEXT NOT NULL DEFAULT '',
    wann TEXT NOT NULL, UNIQUE (kid_id, text, zitat));
"""
# Merkmale, die der Mensch aus dem Steckbrief eines Ablageordners verworfen hat (Schritt 3 Ordner-Steckbrief)
_MERKMAL_AUS = """
CREATE TABLE merkmal_aus (
    id INTEGER PRIMARY KEY, ordner TEXT NOT NULL COLLATE NOCASE, art TEXT NOT NULL, wert TEXT NOT NULL,
    wann TEXT NOT NULL, UNIQUE (ordner, art, wert));
"""
# Angaben als Merkmal + Wert (Schema 5): eine Angabe je Merkmal und Wert, jedes Dokument dazu eine Quelle
_ANGABEN = """
CREATE TABLE angabe (
    id INTEGER PRIMARY KEY, eintrag INTEGER NOT NULL REFERENCES eintrag(id) ON DELETE CASCADE,
    merkmal TEXT NOT NULL DEFAULT '', wert TEXT NOT NULL);
CREATE TABLE quelle (
    id INTEGER PRIMARY KEY, angabe INTEGER NOT NULL REFERENCES angabe(id) ON DELETE CASCADE, kid_id TEXT NOT NULL,
    titel TEXT NOT NULL DEFAULT '', zitat TEXT NOT NULL DEFAULT '', datum TEXT NOT NULL DEFAULT '',
    UNIQUE (angabe, kid_id));
"""
# Von Version n auf n + 1. Bis 4 kommt nur etwas dazu; 4 → 5 leert die Angaben (freie Sätze) und das Abgelehnte.
_NACHRUESTEN = {2: _ABGELEHNT, 3: _MERKMAL_AUS, 4: "DROP TABLE angabe;" + _ANGABEN + "DELETE FROM abgelehnt;"}

# Gleiche Merkmale verschieden geschrieben - beim Vergleichen gleich (die Anzeige behält die erste Schreibweise)
_MERKMAL_GLEICH = {"telefonnummer": "telefon", "tel": "telefon", "tel.": "telefon", "rufnummer": "telefon",
                   "faxnummer": "fax", "e-mail-adresse": "e-mail", "email": "e-mail", "mail": "e-mail",
                   "anschrift": "adresse", "internet": "webseite", "website": "webseite", "homepage": "webseite",
                   "spezialgebiet": "fachgebiet", "schwerpunkt": "fachgebiet", "tätigkeitsschwerpunkt": "fachgebiet",
                   "telefax": "fax", "fax-nr.": "fax", "fax-nr": "fax", "tel.-nr.": "telefon", "telefon-nr.": "telefon",
                   "mobilnummer": "mobil", "mobiltelefon": "mobil", "handy": "mobil", "mobilfunk": "mobil",
                   "kunden-nr.": "kundennummer", "kunden-nr": "kundennummer", "kundennr.": "kundennummer",
                   "kundennr": "kundennummer", "kd.-nr.": "kundennummer", "kd-nr.": "kundennummer",
                   "kd-nr": "kundennummer", "kunden-nummer": "kundennummer"}
_TELEFONISCH = {"telefon", "fax", "mobil"}
# Länderkennung vor der Postleitzahl („D-12345“) - beim Vergleichen egal
LAND_VOR_PLZ = re.compile(r"\b(?:d|de)-\s?(?=\d{5}\b)", re.I)
_STR = re.compile(r"str(\.|asse)?(?=[^a-z]|$)")
_MERKMAL_VORSPANN = re.compile(r"^[^\W\d_][^:\d]{0,%d}$" % (MAX_MERKMAL - 1))


def _leer(text):
    return " ".join(str(text or "").split())


_NUMMER = re.compile(r"\d(?:[\d\s./\-]*\d)?")      # eine Nummer samt Leer- und Trennzeichen: „01234 / 5678“
_TRENNER = re.compile(r"[\s./\-]")


def _passt_wort(wort, text):
    """Kommt ein Suchwort im Text vor? Groß-/Kleinschreibung und ß/ss egal; eine Nummer (ab 3 Ziffern) auch mit anderen
    Leer- und Trennzeichen („01234 5678“ findet „01234/5678“)."""
    if wort in text:
        return True
    ziffern = _TRENNER.sub("", wort)
    return len(ziffern) >= 3 and any(
        ziffern in _TRENNER.sub("", n) for n in _NUMMER.findall(text))


def suche_woerter(suche):
    return str(suche or "").casefold().split()


def passt(suche, texte):
    """Trifft die Suche einen Eintrag? Jedes Wort muss in einem der Texte vorkommen (Bezeichnung, Notiz, Angaben).
    :param texte: wie `suchtexte()[id]`"""
    woerter, klein = suche_woerter(suche), [str(t).casefold() for t in texte]
    return all(any(_passt_wort(w, t) for t in klein) for w in woerter)


def fundstellen(suche, texte):
    """Indizes der Texte, in denen mindestens ein Suchwort vorkommt - zum Markieren der passenden Angaben."""
    woerter = suche_woerter(suche)
    return [i for i, t in enumerate(texte) if woerter and any(_passt_wort(w, str(t).casefold()) for w in woerter)]


def _gleich(text):
    """Zum Vergleichen: Groß-/Kleinschreibung und Leerzeichen egal."""
    return _leer(text).casefold()


def merkmal_kern(merkmal):
    """Zum Vergleichen von Merkmalen: Schreibweise, ß/ss, Doppelpunkt und gängige Synonyme egal („Telefonnummer“ =
    „Tel.:“ = „Telefon“)."""
    kern = _gleich(merkmal).rstrip(":").strip().replace("ß", "ss")
    return _MERKMAL_GLEICH.get(kern, kern)


def telefon_einheitlich(wert):
    """Eine Telefon-/Faxnummer nach DIN 5008: „Vorwahl Rufnummer“ ohne Gruppierung, Ländervorwahl als „+49 “
    („01234/567 89“ → „01234 56789“, „+49 (0)1234-56789“ → „+49 1234 56789“). Mit Buchstaben (Zusätze wie
    „Zentrale“) oder weniger als 5 Ziffern bleibt der Wert, wie er ist (Peter 19.11.2026)."""
    w = _leer(wert)
    if re.search(r"[^\d\s/\-–().+]", w) or len(re.sub(r"\D", "", w)) < 5:
        return w
    land = ""
    m = re.match(r"(?:\+|00)(\d{2})\s*(?:\(0\)\s*)?", w)
    if m:
        land, w = f"+{m.group(1)} ", w[m.end():]
    m = re.match(r"\(\s*([\d\s]+)\)\s*(.*)", w)
    if m:
        vor, rest = m.groups()
    elif "/" in w:
        vor, _, rest = w.partition("/")
    else:
        vor, rest = (re.split(r"[\s\-–.]+", w.strip(), maxsplit=1) + [""])[:2]
    vor, rest = re.sub(r"\D", "", vor), re.sub(r"\D", "", rest)
    return f"{land}{vor} {rest}".strip()


def adresse_einheitlich(wert):
    """Eine Anschrift als „Straße Nr., PLZ Ort“ ohne „D-“ vor der Postleitzahl (DIN 5008: die Länderkennung nur bei
    Auslandsanschriften) - Peter 19.11.2026: „Musterstr. 8, D-12345 …“ neben „Musterstr. 8 12345 …“."""
    w = LAND_VOR_PLZ.sub("", _leer(wert))
    return re.sub(r"(?<=[^\s,])\s*,?\s+(?=\d{5}\s+\S)", ", ", w)


_DATUM = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?!\d|\.\d)")


def datum_einheitlich(wert, heute=None):
    """Daten als TT.MM.JJJJ (DIN 5008, Peter 19.11.2026: „mit 4-stelliger Jahreszahl“): „17.03.19“ → „17.03.2019“,
    „1.2.2019“ → „01.02.2019“. Zweistellige Jahre bis 5 Jahre in die Zukunft gelten als 20.., ältere als 19..
    Was kein gültiger Tag oder Monat ist, bleibt stehen."""
    grenze = (heute or datetime.date.today()).year % 100 + 5

    def ersetze(m):
        tag, monat, jahr = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (1 <= tag <= 31 and 1 <= monat <= 12):
            return m.group(0)
        if len(jahr) == 2:
            jahr = f"{20 if int(jahr) <= grenze else 19}{jahr}"
        return f"{tag:02d}.{monat:02d}.{jahr}"
    return _DATUM.sub(ersetze, wert)


def wert_einheitlich(merkmal, wert):
    """Werte, die es in vielen Schreibweisen gibt, auf eine bringen - Telefon, Fax, Mobil, Adresse und Daten."""
    kern = merkmal_kern(merkmal)
    if kern in _TELEFONISCH:
        return telefon_einheitlich(wert)
    return adresse_einheitlich(wert) if kern == "adresse" else datum_einheitlich(_leer(wert))


def _wert_kern(wert):
    """Zum Vergleichen von Werten: nur Wörter und Zahlen in ihrer Reihenfolge - Schreibweise, Satzzeichen, „D-“ vor der
    Postleitzahl und „Str.“/„Straße“ egal (Peter 19.11.2026: dieselbe Adresse kam zweimal, „Musterstr. 8, D-…“ und
    „Musterstr. 8 …“)."""
    t = LAND_VOR_PLZ.sub("", _gleich(wert).replace("ß", "ss"))
    return " ".join(re.findall(r"[0-9a-zäöü]+", _STR.sub("strasse ", t)))


def angabe_text(merkmal, wert):
    """Eine Angabe als eine Zeile: „Merkmal: Wert“, ohne Merkmal nur der Wert."""
    return f"{_leer(merkmal)}: {_leer(wert)}" if _leer(merkmal) else _leer(wert)


def teile_angabe(angabe):
    """(Merkmal, Wert) aus einem Paar oder einer Zeile „Merkmal: Wert“. Ein Merkmal ist, was vor dem ersten Doppelpunkt
    steht, wenn es mit einem Buchstaben beginnt, keine Ziffer enthält und kurz ist („Telefon: 0123“); sonst ist die
    ganze Zeile der Wert („Heizung erneuert 2019“, „Termin 10:30 Uhr“)."""
    if isinstance(angabe, (tuple, list)):
        merkmal, wert = angabe
        return _leer(merkmal).rstrip(":").strip(), _leer(wert)
    text = _leer(angabe)
    vorn, doppelpunkt, hinten = text.partition(":")
    if doppelpunkt and _leer(hinten) and _MERKMAL_VORSPANN.match(vorn.strip()):
        return vorn.strip(), _leer(hinten)
    return "", text


class Eingabefehler(ValueError):
    """Ein Eintrag lässt sich so nicht speichern; der Text ist für den Nutzer gedacht."""


def _jetzt():
    return datetime.datetime.now().isoformat(timespec="seconds")


class Wissen:
    """Die Wissensbasis einer Sammlung. Alle Methoden öffnen ihre eigene, kurzlebige Verbindung."""

    def __init__(self, master_folder=None, pfad=None):
        self.pfad = pfad or app_paths.wissen_path(master_folder)

    @property
    def pfad_alt(self):
        return os.path.join(os.path.dirname(self.pfad), "wissen_alt.sqlite")

    @property
    def pfad_vor_umbau(self):
        """Kopie vom Stand vor dem Umbau auf Merkmal + Wert (Schema 4 → 5), einmalig angelegt."""
        return os.path.join(os.path.dirname(self.pfad), "wissen_vor_umbau.sqlite")

    def _verbinde(self):
        os.makedirs(os.path.dirname(self.pfad), exist_ok=True)
        con = sqlite3.connect(self.pfad, timeout=5)
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if 0 < version < ALTER_AUFBAU:                          # alter Aufbau mit festen Feldern: beiseite, leer neu
            con.close()
            os.replace(self.pfad, self.pfad_alt)
            logging.getLogger("DocManager").info("Wiki: Datei im alten Aufbau beiseitegelegt, das Wiki beginnt leer")
            con = sqlite3.connect(self.pfad, timeout=5)
            version = 0
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        if version == 0:
            con.executescript("BEGIN;" + _TABELLEN + _ANGABEN + _ABGELEHNT + _MERKMAL_AUS + "".join(
                f"INSERT INTO art (name, reihe) VALUES ('{name}', {n});" for n, name in enumerate(START_ARTEN))
                + f"PRAGMA user_version = {SCHEMA}; COMMIT;")
        elif version < SCHEMA:                                  # neuerer Aufbau: nachrüsten (4 → 5 leert die Angaben)
            alte = con.execute("SELECT COUNT(*) FROM angabe").fetchone()[0] if version < 5 else 0
            if version < 5 and not os.path.exists(self.pfad_vor_umbau):   # einmal den Stand davor aufheben
                kopie = sqlite3.connect(self.pfad_vor_umbau)
                try:
                    con.backup(kopie)
                finally:
                    kopie.close()
            con.executescript("BEGIN;" + "".join(_NACHRUESTEN[v] for v in range(version, SCHEMA))
                              + f"PRAGMA user_version = {SCHEMA}; COMMIT;")
            if version < 5:
                logging.getLogger("DocManager").info(f"Wiki: Angaben auf Merkmal und Wert umgestellt, {alte} alte "
                                                     "Angaben geleert")
        return con

    def _mit(self, arbeit):
        con = self._verbinde()
        try:
            with con:                                           # eine Transaktion: alles oder nichts
                return arbeit(con)
        finally:
            con.close()

    def _lies(self, arbeit, leer):
        """Lesen legt keine Datei an: ohne Datei gibt es `leer`."""
        return self._mit(arbeit) if os.path.exists(self.pfad) else leer

    def sichere(self):
        """Kopie `wissen.sqlite.bak` neben der Datei (SQLite-Backup, auch bei offener Verbindung stimmig).
        :return: True, wenn gesichert wurde (ohne Datei gibt es nichts zu sichern)"""
        if not os.path.exists(self.pfad):
            return False
        quelle, ziel = sqlite3.connect(self.pfad, timeout=5), sqlite3.connect(self.pfad + ".bak")
        try:
            quelle.backup(ziel)
        finally:
            ziel.close()
            quelle.close()
        return True

    # ------------------------------------------------------------ Schubladen
    def arten(self):
        """[{id, name, anzahl}] in der Reihenfolge der Schubladen. Ohne Datei die Start-Schubladen (id None)."""
        return self._lies(lambda con: [dict(z) for z in con.execute(
            "SELECT a.id, a.name, COUNT(e.id) AS anzahl FROM art a LEFT JOIN eintrag e ON e.art = a.id "
            "GROUP BY a.id ORDER BY a.reihe, a.id")], [{"id": None, "name": n, "anzahl": 0} for n in START_ARTEN])

    def art_neu(self, name):
        """Neue Schublade am Ende; gibt es sie schon (Schreibweise egal), deren Id. :return: Id"""
        name = _leer(name)
        if not name:
            raise Eingabefehler("Bitte einen Namen für die Schublade eintragen.")

        return self._mit(lambda con: self._art_id(con, name))

    @staticmethod
    def _art_id(con, art):
        """Schublade als Id oder als Name (dann gesucht, sonst am Ende angelegt) → Id."""
        if not isinstance(art, str):
            if con.execute("SELECT 1 FROM art WHERE id = ?", (art,)).fetchone() is None:
                raise Eingabefehler("Die Schublade gibt es nicht (mehr).")
            return art
        da = con.execute("SELECT id FROM art WHERE name = ?", (art,)).fetchone()
        if da:
            return da["id"]
        reihe = con.execute("SELECT COALESCE(MAX(reihe), -1) + 1 FROM art").fetchone()[0]
        return con.execute("INSERT INTO art (name, reihe) VALUES (?, ?)", (art, reihe)).lastrowid

    def art_umbenennen(self, art_id, name):
        name = _leer(name)
        if not name:
            raise Eingabefehler("Bitte einen Namen für die Schublade eintragen.")

        def arbeit(con):
            da = con.execute("SELECT id FROM art WHERE name = ?", (name,)).fetchone()
            if da and da["id"] != art_id:
                raise Eingabefehler(f"Eine Schublade „{name}“ gibt es schon - zum Vereinen bitte zusammenlegen.")
            con.execute("UPDATE art SET name = ? WHERE id = ?", (name, art_id))
        self._mit(arbeit)

    def art_loeschen(self, art_id):
        """Eine LEERE Schublade entfernen. Mit Einträgen oder als letzte: Eingabefehler - Einträge gehen so nie
        verloren (dafür gibt es `arten_zusammenlegen`)."""
        def arbeit(con):
            if con.execute("SELECT 1 FROM eintrag WHERE art = ?", (art_id,)).fetchone():
                raise Eingabefehler("In der Schublade liegen noch Einträge - bitte erst mit einer anderen zusammenlegen.")
            if con.execute("SELECT COUNT(*) FROM art").fetchone()[0] <= 1:
                raise Eingabefehler("Die letzte Schublade bleibt.")
            con.execute("DELETE FROM art WHERE id = ?", (art_id,))
        self._mit(arbeit)

    def arten_zusammenlegen(self, von, nach):
        """Alle Einträge der Schublade `von` kommen nach `nach`, `von` verschwindet. :return: Zahl der Einträge"""
        if von == nach:
            return 0

        def arbeit(con):
            if con.execute("SELECT COUNT(*) FROM art WHERE id IN (?, ?)", (von, nach)).fetchone()[0] != 2:
                raise Eingabefehler("Die Schublade gibt es nicht mehr.")
            n = con.execute("UPDATE eintrag SET art = ? WHERE art = ?", (nach, von)).rowcount
            con.execute("DELETE FROM art WHERE id = ?", (von,))
            return n
        return self._mit(arbeit)

    # ------------------------------------------------------------ Lesen
    def liste(self):
        """[{id, art, art_name, bezeichnung, geprueft}] in der Reihenfolge der Schubladen, darin alphabetisch."""
        zeilen = self._lies(lambda con: [dict(z) for z in con.execute(
            "SELECT e.id, e.art, a.name AS art_name, a.reihe, e.bezeichnung, e.geprueft FROM eintrag e "
            "JOIN art a ON a.id = e.art")], [])
        zeilen.sort(key=lambda z: (z.pop("reihe"), z["art"], z["bezeichnung"].casefold()))
        return zeilen

    def suchtexte(self):
        """{eintrag_id: [Bezeichnung, Notiz, Angaben …]} - wonach der Filter im Fenster sucht (`passt`). Liest nur."""
        def arbeit(con):
            texte = {z["id"]: [z["bezeichnung"], z["notiz"]] for z in con.execute("SELECT id, bezeichnung, notiz FROM eintrag")}
            for e, angaben in self._angaben(con).items():
                texte[e] += [a["text"] for a in angaben]
            return texte
        return self._lies(arbeit, {})

    @staticmethod
    def _angaben(con, eintrag_id=None):
        """{eintrag_id: [Angabe]} geordnet zum Anzeigen. Eine Angabe: {id, merkmal, wert, text, quellen, stand,
        aktuell, kid_id, titel, zitat} - `quellen` [{kid_id, titel, zitat, datum}] die jüngste zuerst, `stand` deren
        Datum ('' ohne datierte Quelle); `kid_id`/`titel`/`zitat` die der jüngsten Quelle (leer: von Hand).
        Reihenfolge: Merkmale in der Reihenfolge ihres ersten Auftretens, darin der Verlauf mit dem jüngsten Wert
        zuerst (`aktuell` nur bei diesem); freie Zeilen ohne Merkmal am Ende."""
        wo, werte = ("WHERE eintrag = ?", (eintrag_id,)) if eintrag_id is not None else ("", ())
        angaben = {z["id"]: dict(z, quellen=[]) for z in con.execute(
            f"SELECT id, eintrag, merkmal, wert FROM angabe {wo} ORDER BY id", werte)}
        for q in con.execute(f"SELECT q.angabe, q.kid_id, q.titel, q.zitat, q.datum FROM quelle q JOIN angabe a "
                             f"ON a.id = q.angabe {wo.replace('eintrag', 'a.eintrag')} ORDER BY q.id", werte):
            angaben[q["angabe"]]["quellen"].append({k: q[k] for k in ("kid_id", "titel", "zitat", "datum")})
        je_eintrag = {}
        for a in angaben.values():
            a["quellen"].sort(key=lambda q: q["datum"], reverse=True)
            jung = a["quellen"][0] if a["quellen"] else {"kid_id": "", "titel": "", "zitat": "", "datum": ""}
            a.update(text=angabe_text(a["merkmal"], a["wert"]), stand=jung["datum"], kid_id=jung["kid_id"],
                     titel=jung["titel"], zitat=jung["zitat"], aktuell=False)
            je_eintrag.setdefault(a.pop("eintrag"), []).append(a)
        for e, liste in je_eintrag.items():
            gruppen = {}                                        # merkmal_kern → Angaben, in Reihenfolge des Auftretens
            for a in liste:
                gruppen.setdefault(merkmal_kern(a["merkmal"]), []).append(a)
            geordnet = []
            for kern, gruppe in sorted(gruppen.items(), key=lambda g: (g[0] == "", g[1][0]["id"])):
                if kern:
                    gruppe.sort(key=lambda a: (a["stand"], a["id"]), reverse=True)
                    gruppe[0]["aktuell"] = True
                geordnet += gruppe
            je_eintrag[e] = geordnet
        return je_eintrag

    def merkmale(self, art=None):
        """Merkmale, die in einer Schublade (Id) schon benutzt werden, die häufigsten zuerst - als Auswahl im Fenster
        und als Vorgabe für die KI (gleiche Namen statt neuer Schreibweisen). Ohne `art`: alle."""
        wo, werte = ("WHERE e.art = ?", (art,)) if art is not None else ("", ())

        def arbeit(con):
            zahl, schreibweise = {}, {}
            for z in con.execute(f"SELECT a.merkmal FROM angabe a JOIN eintrag e ON e.id = a.eintrag {wo} "
                                 "ORDER BY a.id", werte):
                kern = merkmal_kern(z["merkmal"])
                if kern:
                    zahl[kern] = zahl.get(kern, 0) + 1
                    schreibweise.setdefault(kern, z["merkmal"])
            return [schreibweise[k] for k in sorted(zahl, key=lambda k: -zahl[k])]
        return self._lies(arbeit, [])

    def anzahl(self):
        """Zahl der Einträge - fürs Protokoll (nur Zahlen)."""
        return self._lies(lambda con: con.execute("SELECT COUNT(*) FROM eintrag").fetchone()[0], 0)

    def lade(self, eintrag_id):
        """Ein Eintrag mit allem, oder None: {id, art, art_name, bezeichnung, notiz, geprueft, angelegt, geaendert,
        angaben: [wie `_angaben`], belege: [{id, kid_id, titel}], verbunden: [{id, bezeichnung, art_name}]}"""
        def arbeit(con):
            e = con.execute("SELECT e.*, a.name AS art_name FROM eintrag e JOIN art a ON a.id = e.art WHERE e.id = ?",
                            (eintrag_id,)).fetchone()
            if e is None:
                return None
            d = dict(e)
            d["angaben"] = self._angaben(con, eintrag_id).get(eintrag_id, [])
            d["belege"] = [dict(z) for z in con.execute(
                "SELECT id, kid_id, titel FROM beleg WHERE eintrag = ? ORDER BY titel COLLATE NOCASE, id", (eintrag_id,))]
            d["verbunden"] = [dict(z) for z in con.execute(
                "SELECT e.id, e.bezeichnung, a.name AS art_name FROM verbindung v "
                "JOIN eintrag e ON e.id = CASE WHEN v.a = ? THEN v.b ELSE v.a END JOIN art a ON a.id = e.art "
                "WHERE v.a = ? OR v.b = ? ORDER BY e.bezeichnung COLLATE NOCASE", (eintrag_id,) * 3)]
            return d
        return self._lies(arbeit, None)

    def bezeichnung(self, eintrag_id):
        e = self.lade(eintrag_id) if eintrag_id else None
        return e["bezeichnung"] if e else ""

    def gleichnamige(self, art_id, bezeichnung, ausser=None):
        """Ids in derselben Schublade mit derselben Bezeichnung (Groß-/Kleinschreibung und Leerzeichen egal)."""
        name = _gleich(bezeichnung)
        return [e["id"] for e in self.liste()
                if e["art"] == art_id and e["bezeichnung"].casefold() == name and e["id"] != ausser]

    def eintraege_mit_beleg(self, kid_ids):
        """Einträge (wie `liste`), die eines dieser Dokumente (Dokument-IDs) als Beleg haben - für den Rechtsklick in der
        Dokumentenliste."""
        kid_ids = sorted({k for k in kid_ids if k})
        if not kid_ids:
            return []
        fragen = ", ".join("?" * len(kid_ids))
        ids = self._lies(lambda con: {z[0] for z in con.execute(
            f"SELECT DISTINCT eintrag FROM beleg WHERE kid_id IN ({fragen})", kid_ids)}, set())
        return [e for e in self.liste() if e["id"] in ids]

    # ------------------------------------------------------------ Schreiben: Eintrag
    @staticmethod
    def _beruehrt(con, eintrag_id):
        """Jede Änderung: Zeitstempel neu, die KI-Prüfung gilt nicht mehr."""
        con.execute("UPDATE eintrag SET geprueft = '', geaendert = ? WHERE id = ?", (_jetzt(), eintrag_id))

    @staticmethod
    def _gibt_es(con, eintrag_id):
        if con.execute("SELECT 1 FROM eintrag WHERE id = ?", (eintrag_id,)).fetchone() is None:
            raise Eingabefehler("Den Eintrag gibt es nicht mehr.")

    def speichere(self, art, bezeichnung, notiz="", eintrag_id=None):
        """Legt einen Eintrag an oder ändert Schublade, Bezeichnung und Notiz eines vorhandenen. Angaben, Belege und
        Verbindungen bleiben unberührt.
        :param art: Id der Schublade oder ihr Name (solange es die Datei noch nicht gibt, haben Schubladen keine Id)
        :return: Id"""
        if isinstance(art, str) and not _leer(art):
            raise Eingabefehler("Bitte eine Schublade wählen.")
        bezeichnung = _leer(bezeichnung)
        if not bezeichnung:
            raise Eingabefehler("Bitte eine Bezeichnung eintragen.")
        notiz = str(notiz or "").strip()

        def arbeit(con):
            art_id = self._art_id(con, _leer(art) if isinstance(art, str) else art)
            jetzt = _jetzt()
            if eintrag_id is None:
                return con.execute("INSERT INTO eintrag (art, bezeichnung, notiz, angelegt, geaendert) VALUES (?, ?, ?, ?, ?)",
                                   (art_id, bezeichnung, notiz, jetzt, jetzt)).lastrowid
            self._gibt_es(con, eintrag_id)
            con.execute("UPDATE eintrag SET art = ?, bezeichnung = ?, notiz = ?, geprueft = '', geaendert = ? WHERE id = ?",
                        (art_id, bezeichnung, notiz, jetzt, eintrag_id))
            return eintrag_id
        return self._mit(arbeit)

    def loesche(self, eintrag_id):
        """Löscht den Eintrag samt Angaben, Belegen und Verbindungen. Die Dokumente bleiben unberührt."""
        self._mit(lambda con: con.execute("DELETE FROM eintrag WHERE id = ?", (eintrag_id,)))

    def eintraege_zusammenlegen(self, bleibt, geht):
        """Zwei Einträge sind dasselbe (Peter 13.11.2026: zwei Einträge für dieselbe Versicherung): Alles von
        `geht` kommt zu `bleibt`, `geht` verschwindet - in EINER Transaktion, nichts geht verloren.
        - Angaben ziehen um; steht dasselbe Merkmal mit demselben Wert dort schon (Schreibweise egal), bleibt die
          vorhandene und bekommt die Quellen der anderen dazu.
        - Belege und Verbindungen ziehen um, ohne Doppelte; die Verbindung der beiden untereinander entfällt.
        - Die Notiz von `geht` wird angehängt, seine Bezeichnung steht als Angabe „Auch: …“ dabei, wenn sie anders lautet.
        :return: {"angaben": …, "belege": …, "verbunden": …} - was dazukam"""
        if bleibt == geht:
            raise Eingabefehler("Ein Eintrag lässt sich nicht mit sich selbst zusammenlegen.")

        def arbeit(con):
            self._gibt_es(con, bleibt)
            self._gibt_es(con, geht)
            ziel = con.execute("SELECT bezeichnung, notiz FROM eintrag WHERE id = ?", (bleibt,)).fetchone()
            quelle = con.execute("SELECT bezeichnung, notiz FROM eintrag WHERE id = ?", (geht,)).fetchone()
            zahlen = {"angaben": 0, "belege": 0, "verbunden": 0}
            for a in con.execute("SELECT id, merkmal, wert FROM angabe WHERE eintrag = ? ORDER BY id", (geht,)).fetchall():
                schon = self._gleiche_angabe(con, bleibt, a["merkmal"], a["wert"])
                if schon is None:
                    con.execute("UPDATE angabe SET eintrag = ? WHERE id = ?", (bleibt, a["id"]))
                    zahlen["angaben"] += 1
                else:
                    self._quellen_umziehen(con, a["id"], schon)
            if _gleich(quelle["bezeichnung"]) != _gleich(ziel["bezeichnung"]):
                merkmal, wert = self._angabe_werte(("Auch", quelle["bezeichnung"][:MAX_ANGABE - 10]))
                if self._gleiche_angabe(con, bleibt, merkmal, wert) is None:
                    con.execute("INSERT INTO angabe (eintrag, merkmal, wert) VALUES (?, ?, ?)", (bleibt, merkmal, wert))
            zahlen["belege"] = con.execute(
                "INSERT OR IGNORE INTO beleg (eintrag, kid_id, titel) SELECT ?, kid_id, titel FROM beleg WHERE eintrag = ? "
                "ORDER BY id", (bleibt, geht)).rowcount
            for z in con.execute("SELECT a, b FROM verbindung WHERE a = ? OR b = ?", (geht, geht)).fetchall():
                anderer = z["b"] if z["a"] == geht else z["a"]
                if anderer != bleibt:
                    zahlen["verbunden"] += con.execute("INSERT OR IGNORE INTO verbindung (a, b) VALUES (?, ?)",
                                                       (min(bleibt, anderer), max(bleibt, anderer))).rowcount
            notiz = "\n".join(t for t in (ziel["notiz"].strip(), quelle["notiz"].strip()) if t)
            con.execute("UPDATE eintrag SET notiz = ? WHERE id = ?", (notiz, bleibt))
            con.execute("DELETE FROM eintrag WHERE id = ?", (geht,))          # nimmt seine Reste mit (ON DELETE CASCADE)
            self._beruehrt(con, bleibt)
            return zahlen
        return self._mit(arbeit)

    # ------------------------------------------------------------ Schreiben: Angaben
    @staticmethod
    def _angabe_werte(angabe):
        """(Merkmal, Wert) geprüft - `angabe` als Paar oder Zeile „Merkmal: Wert“ (`teile_angabe`)."""
        merkmal, wert = teile_angabe(angabe)
        if not wert:
            raise Eingabefehler("Die Angabe braucht einen Wert." if merkmal else "Die Angabe ist leer.")
        if len(merkmal) > MAX_MERKMAL:
            raise Eingabefehler(f"Ein Merkmal ist ein kurzer Name (höchstens {MAX_MERKMAL} Zeichen), etwa „Telefon“ "
                                "oder „Versicherungsnummer“.")
        if len(angabe_text(merkmal, wert)) > MAX_ANGABE:
            raise Eingabefehler(f"Eine Angabe ist eine kurze Zeile (höchstens {MAX_ANGABE} Zeichen). Längeres passt in "
                                "die Notiz.")
        return merkmal, wert_einheitlich(merkmal, wert)

    @staticmethod
    def _gleiche_angabe(con, eintrag_id, merkmal, wert, ausser=None):
        """Id der Angabe des Eintrags mit demselben Merkmal und Wert (Schreibweise egal) oder None."""
        schluessel = (merkmal_kern(merkmal), _wert_kern(wert))
        return next((z["id"] for z in con.execute("SELECT id, merkmal, wert FROM angabe WHERE eintrag = ?", (eintrag_id,))
                     if (merkmal_kern(z["merkmal"]), _wert_kern(z["wert"])) == schluessel and z["id"] != ausser), None)

    @staticmethod
    def _quellen_umziehen(con, von, nach):
        """Die Quellen der Angabe `von` kommen zu `nach` (ohne doppelte Dokumente), `von` verschwindet."""
        con.execute("INSERT OR IGNORE INTO quelle (angabe, kid_id, titel, zitat, datum) "
                    "SELECT ?, kid_id, titel, zitat, datum FROM quelle WHERE angabe = ? ORDER BY id", (nach, von))
        con.execute("DELETE FROM angabe WHERE id = ?", (von,))

    def angabe_hinzu(self, eintrag_id, angabe, kid_id="", titel="", zitat="", datum=""):
        """Eine Angabe; mit `kid_id` stammt sie aus diesem Dokument (das dann Quelle der Angabe und Beleg des Eintrags
        wird - Beleg nur, solange die Angabe weniger als `MAX_BELEG_QUELLEN` Quellen hat). Steht dasselbe Merkmal mit
        demselben Wert schon da (Schreibweise egal), kommt nur die Quelle dazu.
        :param angabe: (Merkmal, Wert) oder eine Zeile „Merkmal: Wert“ (`teile_angabe`)
        :param datum: Dokumentdatum JJJJ-MM-TT der Quelle - ordnet den Verlauf
        :return: Id der neuen Angabe oder None"""
        merkmal, wert = self._angabe_werte(angabe)
        if zitat and not kid_id:
            raise Eingabefehler("Ein Zitat braucht das Dokument, aus dem es stammt.")

        def arbeit(con):
            self._gibt_es(con, eintrag_id)
            da = self._gleiche_angabe(con, eintrag_id, merkmal, wert)
            quellen = con.execute("SELECT COUNT(*) FROM quelle WHERE angabe = ?", (da,)).fetchone()[0] if da else 0
            if kid_id and quellen < MAX_BELEG_QUELLEN:
                con.execute("INSERT OR IGNORE INTO beleg (eintrag, kid_id, titel) VALUES (?, ?, ?)",
                            (eintrag_id, kid_id, _leer(titel)))
            neu = None
            if da is None:
                da = neu = con.execute("INSERT INTO angabe (eintrag, merkmal, wert) VALUES (?, ?, ?)",
                                       (eintrag_id, merkmal, wert)).lastrowid
                self._beruehrt(con, eintrag_id)
            if kid_id:
                con.execute("INSERT OR IGNORE INTO quelle (angabe, kid_id, titel, zitat, datum) VALUES (?, ?, ?, ?, ?)",
                            (da, kid_id, _leer(titel), _leer(zitat), _leer(datum)))
            return neu
        return self._mit(arbeit)

    def angabe_aendern(self, angabe_id, angabe):
        """Merkmal und Wert einer Angabe ändern. Die Quellen bleiben - der Mensch hat das Zitat vor Augen. Gibt es das
        Ergebnis im Eintrag schon, werden beide eine Angabe mit allen Quellen.
        :param angabe: (Merkmal, Wert) oder eine Zeile „Merkmal: Wert“ :return: Id der Angabe danach"""
        merkmal, wert = self._angabe_werte(angabe)

        def arbeit(con):
            z = con.execute("SELECT eintrag FROM angabe WHERE id = ?", (angabe_id,)).fetchone()
            if z is None:
                raise Eingabefehler("Die Angabe gibt es nicht mehr.")
            self._beruehrt(con, z["eintrag"])
            andere = self._gleiche_angabe(con, z["eintrag"], merkmal, wert, ausser=angabe_id)
            if andere is not None:
                self._quellen_umziehen(con, angabe_id, andere)
                return andere
            con.execute("UPDATE angabe SET merkmal = ?, wert = ? WHERE id = ?", (merkmal, wert, angabe_id))
            return angabe_id
        return self._mit(arbeit)

    def angabe_weg(self, angabe_id):
        """Eine Angabe entfernen. Stammt sie aus Dokumenten, merkt sich das Wiki sie je Dokument als abgelehnt - ein
        neuer Lauf über diese Dokumente schlägt sie nicht wieder vor."""
        def arbeit(con):
            z = con.execute("SELECT eintrag, merkmal, wert FROM angabe WHERE id = ?", (angabe_id,)).fetchone()
            if z is None:
                return
            text = angabe_text(z["merkmal"], z["wert"])
            for q in con.execute("SELECT kid_id, zitat FROM quelle WHERE angabe = ?", (angabe_id,)).fetchall():
                if q["kid_id"] and q["zitat"]:
                    self._merke_abgelehnt(con, q["kid_id"], [{"text": text, "zitat": q["zitat"]}])
            con.execute("DELETE FROM angabe WHERE id = ?", (angabe_id,))
            self._beruehrt(con, z["eintrag"])
        self._mit(arbeit)

    # ------------------------------------------------------------ Abgelehntes
    @staticmethod
    def _merke_abgelehnt(con, kid_id, angaben):
        jetzt = _jetzt()
        return sum(con.execute("INSERT OR IGNORE INTO abgelehnt (kid_id, text, zitat, wann) VALUES (?, ?, ?, ?)",
                               (kid_id, _leer(a["text"]), _leer(a["zitat"]), jetzt)).rowcount
                   for a in angaben if _leer(a["text"]))

    def ablehnen(self, kid_id, angaben):
        """Angaben aus dem Dokument `kid_id`, die der Mensch nicht ins Wiki wollte. Ohne Dokument-ID wird nichts
        gemerkt. :param angaben: [{text, zitat}] :return: Zahl der neu gemerkten"""
        if not kid_id or not angaben:
            return 0
        return self._mit(lambda con: self._merke_abgelehnt(con, kid_id, angaben))

    def abgelehnte(self, kid_ids):
        """{kid_id: [{text, zitat}]} - was aus diesen Dokumenten schon einmal abgelehnt wurde. Liest nur."""
        kid_ids = [k for k in set(kid_ids) if k]
        if not kid_ids:
            return {}

        def arbeit(con):
            ergebnis = {}
            for z in con.execute(f"SELECT kid_id, text, zitat FROM abgelehnt WHERE kid_id IN ({','.join('?' * len(kid_ids))})"
                                 " ORDER BY id", kid_ids):
                ergebnis.setdefault(z["kid_id"], []).append({"text": z["text"], "zitat": z["zitat"]})
            return ergebnis
        return self._lies(arbeit, {})

    # ------------------------------------------------------------ Ordner-Steckbrief: ausgeschlossene Merkmale
    def merkmal_ausschliessen(self, ordner, art, wert):
        """Das Merkmal zählt für diesen Ablageordner nicht mehr (ordner_steckbrief.Steckbriefe(ausgeschlossen=)).
        :return: True, wenn neu"""
        if not ordner or not art or not wert:
            raise Eingabefehler("Ordner und Merkmal fehlen.")
        return self._mit(lambda con: con.execute(
            "INSERT OR IGNORE INTO merkmal_aus (ordner, art, wert, wann) VALUES (?, ?, ?, ?)",
            (ordner, art, wert, _jetzt())).rowcount == 1)

    def merkmal_zulassen(self, ordner, art, wert):
        """Ein ausgeschlossenes Merkmal zählt wieder. :return: True, wenn es ausgeschlossen war"""
        return self._lies(lambda con: con.execute(
            "DELETE FROM merkmal_aus WHERE ordner = ? AND art = ? AND wert = ?", (ordner, art, wert)).rowcount == 1,
            False)

    def ausgeschlossene_merkmale(self):
        """[(ordner, art, wert)] - für ordner_steckbrief.lade. Liest nur, ohne Datei leer."""
        return self._lies(lambda con: [(z["ordner"], z["art"], z["wert"]) for z in con.execute(
            "SELECT ordner, art, wert FROM merkmal_aus ORDER BY id")], [])

    # ------------------------------------------------------------ Schreiben: Belege, Verbindungen
    def beleg_hinzu(self, eintrag_id, kid_id, titel=""):
        """Ein Dokument (über seine KID_ID) als Beleg. Doppelt eingetragen wird nichts. :return: True, wenn neu"""
        if not kid_id:
            raise Eingabefehler("Das Dokument hat keine Dokument-ID.")

        def arbeit(con):
            self._gibt_es(con, eintrag_id)
            return con.execute("INSERT OR IGNORE INTO beleg (eintrag, kid_id, titel) VALUES (?, ?, ?)",
                               (eintrag_id, kid_id, _leer(titel))).rowcount == 1
        return self._mit(arbeit)

    def beleg_weg(self, beleg_id):
        """Das Dokument ist nicht mehr Beleg. Angaben aus ihm bleiben stehen, verlieren aber diese Quelle - ohne
        weitere Quelle gelten sie wie von Hand eingetragen."""
        def arbeit(con):
            z = con.execute("SELECT eintrag, kid_id FROM beleg WHERE id = ?", (beleg_id,)).fetchone()
            if z is None:
                return
            con.execute("DELETE FROM beleg WHERE id = ?", (beleg_id,))
            con.execute("DELETE FROM quelle WHERE kid_id = ? AND angabe IN (SELECT id FROM angabe WHERE eintrag = ?)",
                        (z["kid_id"], z["eintrag"]))
        self._mit(arbeit)

    def verbinde(self, a, b):
        """„Verbunden mit“ - ohne Richtung, nie doppelt, nie mit sich selbst. :return: True, wenn neu"""
        if a == b:
            raise Eingabefehler("Ein Eintrag lässt sich nicht mit sich selbst verbinden.")

        def arbeit(con):
            self._gibt_es(con, a)
            self._gibt_es(con, b)
            return con.execute("INSERT OR IGNORE INTO verbindung (a, b) VALUES (?, ?)", (min(a, b), max(a, b))).rowcount == 1
        return self._mit(arbeit)

    def trenne(self, a, b):
        self._mit(lambda con: con.execute("DELETE FROM verbindung WHERE a = ? AND b = ?", (min(a, b), max(a, b))))


def ausgeschlossene_merkmale(master_folder, logger=None):
    """Für Vollautomatik und Ablage-Vorschau: die ausgeschlossenen Steckbrief-Merkmale der Sammlung. Ein Fehler
    (Datei gesperrt, kaputt) liefert [] - die Ablage darf am Wiki nie hängen bleiben."""
    try:
        return Wissen(master_folder).ausgeschlossene_merkmale() if master_folder else []
    except Exception as e:                                   # noqa: BLE001
        if logger is not None:
            logger.warning(f"Wiki: ausgeschlossene Merkmale nicht lesbar ({type(e).__name__})")
        return []
