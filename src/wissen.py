"""
Wiki von Hand (KONZEPT_WIKI_VON_HAND.md, „Neuer Aufbau: freie Angaben statt fester Felder“, 12.11.2026, Schritt N2): die
bestätigte Wissensbasis einer Sammlung. Es steht nur drin, was ein Mensch angelegt oder bestätigt hat.

Ein Eintrag hat
- eine Schublade (`art`): nur die Ordnung der Liste, ohne eigene Felder. Die Schubladen stehen in der Datei und sind
  erweiterbar (`art_neu`, `art_umbenennen`, `arten_zusammenlegen`); neu angelegte Dateien bekommen `START_ARTEN`.
- eine Bezeichnung und eine Notiz,
- Angaben: kurze freie Zeilen („Telefon: 01234 56789“, „Feuerlöscher geprüft am 19.02.2016“). Stammt eine Angabe aus
  einem Dokument, trägt sie dessen Dokument-ID (KID_ID), Titel und das wörtliche Zitat; von Hand Eingetragenes nicht.
- Belege: die Dokumente des Eintrags (über ihre KID_ID, also auch nach Verschieben und Umbenennen). Das Dokument einer
  Angabe ist immer auch Beleg.
- Verbindungen zu anderen Einträgen („Verbunden mit“), ohne Richtung.

Abgelehntes (13.11.2026): Was der Mensch aus einem Dokument nicht ins Wiki wollte (im Fenster „Aus dem Dokument“
abgehakt, oder eine Angabe aus einem Dokument entfernt), steht je Dokument-ID in `abgelehnt` (`ablehnen`,
`abgelehnte`). Ein neuer Lauf über dasselbe Dokument schlägt es nicht wieder vor (tools/wiki_dinge.py).

Bis 12.11.2026 hatte jede Art feste Felder (Kennzeichen, Halter …). Peters Test an einer Rechnung zeigte: Dokumente
passen selten in ein Schema. Eine Datei im alten Aufbau wird beim ersten Zugriff als `wissen_alt.sqlite` beiseitegelegt
und leer neu begonnen (Peter: keine Rücksicht auf vorhandene Einträge). Neuere Dateien werden nur nachgerüstet
(`_NACHRUESTEN`, Version 2 → 3: Tabelle `abgelehnt`), alles Vorhandene bleibt.

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
SCHEMA = 3                            # 3 (13.11.2026): Tabelle `abgelehnt`
ALTER_AUFBAU = 2                      # darunter: feste Felder (bis 12.11.2026), wird beiseitegelegt
_TABELLEN = """
CREATE TABLE art (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, reihe INTEGER NOT NULL);
CREATE TABLE eintrag (
    id INTEGER PRIMARY KEY, art INTEGER NOT NULL REFERENCES art(id), bezeichnung TEXT NOT NULL,
    notiz TEXT NOT NULL DEFAULT '', geprueft TEXT NOT NULL DEFAULT '', angelegt TEXT NOT NULL, geaendert TEXT NOT NULL);
CREATE TABLE angabe (
    id INTEGER PRIMARY KEY, eintrag INTEGER NOT NULL REFERENCES eintrag(id) ON DELETE CASCADE, text TEXT NOT NULL,
    kid_id TEXT NOT NULL DEFAULT '', titel TEXT NOT NULL DEFAULT '', zitat TEXT NOT NULL DEFAULT '');
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
_NACHRUESTEN = {2: _ABGELEHNT}                # von Version n auf n + 1, ohne vorhandene Daten anzufassen


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
            con.executescript("BEGIN;" + _TABELLEN + _ABGELEHNT + "".join(
                f"INSERT INTO art (name, reihe) VALUES ('{name}', {n});" for n, name in enumerate(START_ARTEN))
                + f"PRAGMA user_version = {SCHEMA}; COMMIT;")
        elif version < SCHEMA:                                  # neuerer Aufbau: nur nachrüsten, alles bleibt
            con.executescript("BEGIN;" + "".join(_NACHRUESTEN[v] for v in range(version, SCHEMA))
                              + f"PRAGMA user_version = {SCHEMA}; COMMIT;")
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
            for z in con.execute("SELECT eintrag, text FROM angabe ORDER BY id"):
                texte[z["eintrag"]].append(z["text"])
            return texte
        return self._lies(arbeit, {})

    def anzahl(self):
        """Zahl der Einträge - fürs Protokoll (nur Zahlen)."""
        return self._lies(lambda con: con.execute("SELECT COUNT(*) FROM eintrag").fetchone()[0], 0)

    def lade(self, eintrag_id):
        """Ein Eintrag mit allem, oder None: {id, art, art_name, bezeichnung, notiz, geprueft, angelegt, geaendert,
        angaben: [{id, text, kid_id, titel, zitat}], belege: [{id, kid_id, titel}],
        verbunden: [{id, bezeichnung, art_name}]}"""
        def arbeit(con):
            e = con.execute("SELECT e.*, a.name AS art_name FROM eintrag e JOIN art a ON a.id = e.art WHERE e.id = ?",
                            (eintrag_id,)).fetchone()
            if e is None:
                return None
            d = dict(e)
            d["angaben"] = [dict(z) for z in con.execute(
                "SELECT id, text, kid_id, titel, zitat FROM angabe WHERE eintrag = ? ORDER BY id", (eintrag_id,))]
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
        - Angaben ziehen um; steht derselbe Text dort schon (Schreibweise egal), bleibt die vorhandene und bekommt
          Dokument und Zitat der anderen, falls sie selbst keines hat.
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
            da = {_gleich(z["text"]): z for z in con.execute("SELECT id, text, kid_id FROM angabe WHERE eintrag = ?", (bleibt,))}
            for a in con.execute("SELECT id, text, kid_id, titel, zitat FROM angabe WHERE eintrag = ? ORDER BY id",
                                 (geht,)).fetchall():
                schon = da.get(_gleich(a["text"]))
                if schon is None:
                    con.execute("UPDATE angabe SET eintrag = ? WHERE id = ?", (bleibt, a["id"]))
                    zahlen["angaben"] += 1
                elif a["kid_id"] and not schon["kid_id"]:
                    con.execute("UPDATE angabe SET kid_id = ?, titel = ?, zitat = ? WHERE id = ?",
                                (a["kid_id"], a["titel"], a["zitat"], schon["id"]))
            if _gleich(quelle["bezeichnung"]) != _gleich(ziel["bezeichnung"]):
                auch = self._angabe_text(f"Auch: {quelle['bezeichnung']}"[:MAX_ANGABE])
                if _gleich(auch) not in da:
                    con.execute("INSERT INTO angabe (eintrag, text) VALUES (?, ?)", (bleibt, auch))
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
    def _angabe_text(text):
        text = _leer(text)
        if not text:
            raise Eingabefehler("Die Angabe ist leer.")
        if len(text) > MAX_ANGABE:
            raise Eingabefehler(f"Eine Angabe ist eine kurze Zeile (höchstens {MAX_ANGABE} Zeichen). Längeres passt in "
                                "die Notiz.")
        return text

    def angabe_hinzu(self, eintrag_id, text, kid_id="", titel="", zitat=""):
        """Eine Angabe; mit `kid_id` stammt sie aus diesem Dokument (das dann auch Beleg wird). Steht derselbe Text
        schon da (Schreibweise egal), kommt nichts dazu - hatte die vorhandene noch kein Dokument, bekommt sie dieses.
        :return: Id der neuen Angabe oder None"""
        text = self._angabe_text(text)
        if zitat and not kid_id:
            raise Eingabefehler("Ein Zitat braucht das Dokument, aus dem es stammt.")

        def arbeit(con):
            self._gibt_es(con, eintrag_id)
            if kid_id:
                con.execute("INSERT OR IGNORE INTO beleg (eintrag, kid_id, titel) VALUES (?, ?, ?)",
                            (eintrag_id, kid_id, _leer(titel)))
            for z in con.execute("SELECT id, text, kid_id FROM angabe WHERE eintrag = ?", (eintrag_id,)).fetchall():
                if _gleich(z["text"]) == _gleich(text):
                    if kid_id and not z["kid_id"]:
                        con.execute("UPDATE angabe SET kid_id = ?, titel = ?, zitat = ? WHERE id = ?",
                                    (kid_id, _leer(titel), _leer(zitat), z["id"]))
                    return None
            self._beruehrt(con, eintrag_id)
            return con.execute("INSERT INTO angabe (eintrag, text, kid_id, titel, zitat) VALUES (?, ?, ?, ?, ?)",
                               (eintrag_id, text, kid_id or "", _leer(titel), _leer(zitat))).lastrowid
        return self._mit(arbeit)

    def angabe_aendern(self, angabe_id, text):
        """Den Text einer Angabe ändern. Dokument und Zitat bleiben - der Mensch hat das Zitat vor Augen."""
        text = self._angabe_text(text)

        def arbeit(con):
            z = con.execute("SELECT eintrag FROM angabe WHERE id = ?", (angabe_id,)).fetchone()
            if z is None:
                raise Eingabefehler("Die Angabe gibt es nicht mehr.")
            con.execute("UPDATE angabe SET text = ? WHERE id = ?", (text, angabe_id))
            self._beruehrt(con, z["eintrag"])
        self._mit(arbeit)

    def angabe_weg(self, angabe_id):
        """Eine Angabe entfernen. Stammt sie aus einem Dokument, merkt sich das Wiki sie als abgelehnt - ein neuer Lauf
        über dieses Dokument schlägt sie nicht wieder vor."""
        def arbeit(con):
            z = con.execute("SELECT eintrag, text, kid_id, zitat FROM angabe WHERE id = ?", (angabe_id,)).fetchone()
            if z is not None:
                con.execute("DELETE FROM angabe WHERE id = ?", (angabe_id,))
                self._beruehrt(con, z["eintrag"])
                if z["kid_id"] and z["zitat"]:
                    self._merke_abgelehnt(con, z["kid_id"], [z])
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
        """Das Dokument ist nicht mehr Beleg. Angaben aus ihm bleiben stehen, verlieren aber Dokument und Zitat - sie
        gelten dann wie von Hand eingetragen."""
        def arbeit(con):
            z = con.execute("SELECT eintrag, kid_id FROM beleg WHERE id = ?", (beleg_id,)).fetchone()
            if z is None:
                return
            con.execute("DELETE FROM beleg WHERE id = ?", (beleg_id,))
            con.execute("UPDATE angabe SET kid_id = '', titel = '', zitat = '' WHERE eintrag = ? AND kid_id = ?",
                        (z["eintrag"], z["kid_id"]))
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
