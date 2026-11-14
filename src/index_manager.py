import itertools
import os
import re
import sqlite3
from collections import Counter

import app_paths
import aktivitaet
import ollama_client
import spell_correct
from pdf_handler import PDFHandler

# Wortgrenze der unscharfen Suche (auch am Unterstrich trennen) - search_manager benutzt dieselbe
WORT = re.compile(r"[^\W_]+")


def muster_fuer_aehnliche(aehnliche, woerter, paare):
    """
    Ein Regex, der genau die Dokumente findet, in denen eines der `aehnliche`n Wörter als GANZES
    Wort steht oder als Wortpaar (zwei benachbarte Wörter, dazwischen nur Trenner - so klebt
    SearchManager.begriff_matcher von der Texterkennung zerrissene Wörter wieder zusammen).
    Damit trifft die schnelle Volltextsuche exakt dieselben Dokumente wie der Matcher je Dokument.
    :param woerter/paare: Wortschatz der Sammlung (Einzelwörter bzw. zusammengeklebte Paare)
    :return: kompiliertes Muster oder None, wenn es kein ähnliches Wort gibt
    """
    teile = []
    for w in sorted(aehnliche, key=len, reverse=True):
        if w in woerter:
            teile.append(re.escape(w))
        if w in paare:
            for k in range(1, len(w)):
                if w[:k] in woerter and w[k:] in woerter:
                    teile.append(re.escape(w[:k]) + r"[\W_]+" + re.escape(w[k:]))
    if not teile:
        return None
    return re.compile(r"(?<![^\W_])(?:" + "|".join(teile) + r")(?![^\W_])")


def vermutete_daten_sicher(app, pfade, melde=None):
    """
    IndexManager.vermutete_daten für Ordner- und Trefferliste, aber nie mit Fehler: ohne Index
    (abgeschaltet, defekt, keine Sammlung) leer - die Listen zeigen dann wie früher das Datei-Datum.
    """
    index = getattr(app, "index_manager", None)
    if not pfade or index is None or not app.config.get("use_index", True):
        return {}
    try:
        return index.vermutete_daten(pfade, melde)
    except Exception as e:
        if hasattr(app, "logger"):
            app.logger.error(f"Vermutetes Dokumentdatum nicht verfügbar, zeige Datei-Datum: {e}")
        return {}


_UPSERT_FILES = ("INSERT OR REPLACE INTO files (rel_path, mtime, size, title, keywords, kid_date, creation_date, "
                 "scan_zeit, kid_id, absender, erfasst, mail_id, richtung) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)")
_SPALTEN_FILES = ("rel_path, mtime, size, title, keywords, kid_date, creation_date, scan_zeit, kid_id, absender, erfasst, "
                  "mail_id, richtung")


def mails_ausgeblendet(app):
    """Ansicht → „Mails ausblenden“. Nur echtes True zählt, eine Attrappe in Tests schaltet nichts aus."""
    schalter = getattr(app, "mails_ausblenden_var", None)
    return schalter is not None and schalter.get() is True


def ist_ausgeblendet(rel_path, richtung):
    """Bleibt dieses Dokument bei „Mails ausblenden“ verborgen? Nur Mail-PDFs (KID_RICHTUNG, Anhänge haben es nicht) und
    nie in `0_Posteingang` oder `0_Unsicher`: Was noch auf eine Entscheidung wartet, soll man sehen."""
    return bool(richtung) and not any(t.startswith("0_") for t in os.path.dirname(rel_path).split(os.sep))


def _werte_aus_pdf(pfad):
    """Die Index-Werte eines PDFs (title, keywords, kid_date, creation_date, scan_zeit, kid_id, absender, erfasst,
    mail_id, richtung)."""
    meta = PDFHandler.get_metadata(pfad)
    return (meta.get("title", ""), meta.get("keywords", ""), meta.get("KID_DokumentenDatum", ""),
            meta.get("creationDate", ""), meta.get("KID_ScanZeitpunkt", ""), meta.get("KID_ID", "") or "",
            meta.get("KID_Absender", "") or "", meta.get("KID_Erfasst", "") or "", meta.get("KID_MailID", "") or "",
            meta.get("KID_Richtung", "") or "")


def _zeile_frisch(row, mtime, size):
    """Gilt die files-Zeile (rel_path, mtime, size, …, kid_id, absender, erfasst, mail_id, richtung) noch für die Datei
    auf der Platte? kid_id/absender/mail_id NULL = Zeile aus der Zeit vor diesen Spalten, einmal frisch lesen. Bei
    richtung nur, wenn das PDF eine KID_MailID hat: Andere können keine Mails sein, eine große Sammlung bleibt ungelesen."""
    return (row is not None and abs(row[1] - mtime) < 1e-6 and row[2] == size and row[8] is not None
            and row[9] is not None and row[11] is not None and (row[12] is not None or not row[11]))


def metadaten_sicher(app, pfade, melde=None):
    """
    IndexManager.metadaten für die Ordnerliste, aber nie mit Fehler: ohne Index (abgeschaltet, defekt,
    keine Sammlung) leer - die Liste liest dann wie früher jedes PDF selbst.
    """
    index = getattr(app, "index_manager", None)
    if not pfade or index is None or not app.config.get("use_index", True):
        return {}
    try:
        return index.metadaten(pfade, melde)
    except Exception as e:
        if hasattr(app, "logger"):
            app.logger.error(f"Index für die Ordnerliste nicht verfügbar, lese die PDFs: {e}")
        return {}


def als_listendatum(datum):
    """'JJJJ-MM-TT' -> (Anzeige 'TT.MM.JJJJ', Sortierschlüssel 'JJJJMMTT', Jahr) oder None."""
    try:
        y, m, d = datum.split("-")
        return f"{d}.{m}.{y}", f"{y}{m}{d}", int(y)
    except (AttributeError, ValueError):
        return None


class IndexManager:
    """
    Lokaler Suchindex (SQLite, Python-Standardbibliothek — keine neue Abhängigkeit).
    Merkt sich pro PDF: Pfad, Änderungsdatum, Größe, Titel, Tags, Dokumentdatum.
    Die Suche liest dann nur noch den Index; PDFs werden ausschließlich geöffnet,
    wenn sie neu oder verändert sind (Frische-Prüfung über Änderungsdatum + Größe —
    der Index kann dadurch nie veraltete Werte liefern, schlimmstenfalls ist er
    unvollständig und füllt sich nach).

    Die Index-Datei liegt im KID-Daten-Ordner NEBEN dem Hauptordner — bewusst
    außerhalb der Watchdog-Überwachung (FALLSTRICKE #3). Pfade werden relativ
    zum Hauptordner gespeichert, damit der Index einen Umzug der kompletten
    Sammlung übersteht. Siehe KONZEPT_FILE_INDEX.md.
    """

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS files (
            rel_path      TEXT PRIMARY KEY,
            mtime         REAL    NOT NULL,
            size          INTEGER NOT NULL,
            title         TEXT    NOT NULL DEFAULT '',
            keywords      TEXT    NOT NULL DEFAULT '',
            kid_date      TEXT    NOT NULL DEFAULT '',
            creation_date TEXT    NOT NULL DEFAULT '',
            scan_zeit     TEXT    NOT NULL DEFAULT '',
            kid_id        TEXT,
            absender      TEXT,
            erfasst       TEXT    NOT NULL DEFAULT '',
            mail_id       TEXT,
            richtung      TEXT
        )
    """

    # Volltext-Cache für die OCR-Suche (Phase 2, "Standard"-Stufe): der komplette Text
    # der vorhandenen Textebene pro PDF. Bewusst KEIN FTS5: die Suche läuft mit dem
    # bestehenden unscharfen Matcher über die gecachten Texte (identische Suchsemantik
    # inkl. Fuzzy/Wildcards/Teilwort - FTS5-Tokenisierung würde das alles verlieren, und
    # bei einigen hundert Dokumenten ist der Python-Durchlauf ohnehin Millisekundensache).
    # `tier` merkt sich, mit welcher Qualitätsstufe der Text erzeugt wurde ("standard" =
    # nur Textebene gelesen) - höhere Stufen (Re-OCR, KI-Prüfung) können später gezielt
    # nur die Dokumente nachverarbeiten, deren Text von einer niedrigeren Stufe stammt.
    # Verbesserter Text wird dann ERGÄNZT statt ersetzt (eigene Spalte), damit eine
    # stille Fehlkorrektur nie ein Dokument unauffindbar machen kann.
    SCHEMA_FULLTEXT = """
        CREATE TABLE IF NOT EXISTS fulltext (
            rel_path      TEXT PRIMARY KEY,
            mtime         REAL    NOT NULL,
            size          INTEGER NOT NULL,
            text          TEXT    NOT NULL DEFAULT '',
            text_erweitert TEXT   NOT NULL DEFAULT '',
            text_ocr      TEXT    NOT NULL DEFAULT '',
            text_ai       TEXT    NOT NULL DEFAULT '',
            tier          TEXT    NOT NULL DEFAULT 'standard'
        )
    """

    # Persistenter Wortschatz für die "Erweitert"-Stufe (spell_correct.py) - liegt bewusst
    # in einer eigenen Tabelle statt als separate Datei (passt zum bestehenden Muster:
    # alles Index-Bezogene lebt in der index.sqlite). Wird additiv gepflegt (Wort-Häufigkeit
    # wird bei neuen/geänderten Dokumenten HOCHGEZÄHLT, nie exakt zurückgerechnet, wenn ein
    # Dokument sich ändert oder verschwindet) - für einen "dummen" Rate-Mechanismus reicht
    # eine ungefähre Häufigkeit völlig aus, die Komplexität einer exakten Neuberechnung
    # würde den Nutzen nicht rechtfertigen.
    SCHEMA_VOCABULARY = """
        CREATE TABLE IF NOT EXISTS vocabulary (
            word TEXT PRIMARY KEY,
            freq INTEGER NOT NULL DEFAULT 0
        )
    """

    # Vermutetes Dokumentdatum (28.10.2026, FALLSTRICKE #86): für PDFs ohne gespeichertes
    # KID_DokumentenDatum zeigen Ordner- und Trefferliste das aus dem Seitentext gelesene Datum
    # statt des Datei-Datums. Das Lesen kostet ~15 ms je Dokument, daher hier gemerkt - frisch
    # über Änderungsdatum + Größe wie die übrigen Tabellen; datum '' = nichts gefunden.
    SCHEMA_DATUM_VERMUTET = """
        CREATE TABLE IF NOT EXISTS datum_vermutet (
            rel_path      TEXT PRIMARY KEY,
            mtime         REAL    NOT NULL,
            size          INTEGER NOT NULL,
            datum         TEXT    NOT NULL DEFAULT ''
        )
    """

    # Tier, ab dem ein Dokument als "schon hochgestuft" gilt und von upgrade_to_ocr_tier
    # übersprungen wird (Re-OCR ist teuer, siehe dort) - "meister" baut später auf
    # "fortgeschritten" auf, braucht also KEIN eigenes Re-OCR mehr.
    OCR_TIERS = ("fortgeschritten", "meister")

    # Spalten, die nach der ursprünglichen Schema-Version dazugekommen sind - bei
    # bestehenden Index-Dateien fügt CREATE TABLE IF NOT EXISTS sie NICHT nachträglich
    # hinzu, daher die manuelle Migration in _connect() (siehe dort).
    _MIGRATION_COLUMNS = {
        "files": (
            ("creation_date", "TEXT NOT NULL DEFAULT ''"),
            ("scan_zeit", "TEXT NOT NULL DEFAULT ''"),
            # Dokument-ID (25.10.2026) - bewusst OHNE Default: bestehende Zeilen bekommen NULL
            # = „noch nicht gelesen“ und werden beim nächsten Abgleich einmal frisch gelesen;
            # sonst fehlten die IDs aller Dokumente, die sich seitdem nicht geändert haben.
            ("kid_id", "TEXT"),
            # Absender fürs Ablage-Gedächtnis (KID_ABSENDER, 27.10.2026) - ohne Default, wie kid_id
            ("absender", "TEXT"),
            # Spalte „Erfasst“ (KID_ERFASST, 04.11.2026) - MIT Default: das Feld entsteht nur beim Schreiben, und das
            # ändert die Datei; unveränderte Zeilen haben es also sicher nicht, nichts muss neu gelesen werden
            ("erfasst", "TEXT NOT NULL DEFAULT ''"),
            # Bezug zwischen Mail und Anhang (KID_MAILID, 05.11.2026) - ohne Default wie kid_id: importierte PDFs
            # ändern sich dadurch nicht, ihre Zeilen müssen einmal frisch gelesen werden
            ("mail_id", "TEXT"),
            # Mail-PDF oder nicht (KID_RICHTUNG, 06.11.2026, „Mails ausblenden“) - ohne Default, siehe _zeile_frisch
            ("richtung", "TEXT"),
        ),
        "fulltext": (
            ("text_ocr", "TEXT NOT NULL DEFAULT ''"),
            ("text_ai", "TEXT NOT NULL DEFAULT ''"),
            ("text_erweitert", "TEXT NOT NULL DEFAULT ''"),
        ),
    }

    def __init__(self, app):
        """
        Initialisiert den Index-Manager (verbindet noch nicht — lazy beim ersten Zugriff).
        :param app: Referenz auf die Hauptinstanz (DokumentenVerwaltung).
        """
        self.app = app
        self._con = None
        self._con_path = None
        # Wortschatz des Volltext-Cache für die schnelle unscharfe Suche: (Stand, Wörter, Paare) oder
        # None = neu aufbauen. Jede Schreibstelle im Volltext-Cache setzt ihn auf None (auch aus den
        # Hintergrund-Threads der upgrade_to_*-Läufe - eine Zuweisung ist dafür sicher genug)
        self._suchwortschatz = None

    # ==========================================
    # VERBINDUNG
    # ==========================================
    def _open_connection(self, path):
        """Öffnet eine neue, initialisierte (Schema + Migration) Verbindung zu einer index.sqlite - OHNE sie in self._con zu cachen. Für Aufrufer, die aus einem anderen Thread als dem Haupt-UI-Thread eine eigene, isolierte Connection brauchen (siehe upgrade_to_ocr_tier)."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        con = sqlite3.connect(path, timeout=5)
        con.execute(self.SCHEMA)
        con.execute(self.SCHEMA_FULLTEXT)
        con.execute(self.SCHEMA_VOCABULARY)
        con.execute(self.SCHEMA_DATUM_VERMUTET)
        self._migrate(con)
        return con

    def _connect(self):
        """Öffnet (lazy, gecacht) die Index-Datenbank der aktuellen Sammlung für den aufrufenden Thread; wechselt automatisch mit, wenn der Hauptordner gewechselt wurde. NUR für Aufrufe aus dem Haupt-UI-Thread gedacht - sqlite3-Connections sind nicht threadübergreifend nutzbar."""
        master = getattr(self.app, 'master_folder', None)
        if not master or not os.path.isdir(master):
            return None

        path = app_paths.index_path(master)
        if self._con is not None and self._con_path == path:
            return self._con

        self.close()
        con = self._open_connection(path)
        self._con = con
        self._con_path = path
        return con

    def _migrate(self, con):
        """Fügt Spalten nach, die bei einer bereits bestehenden Index-Datei aus einer älteren Schema-Version fehlen (siehe _MIGRATION_COLUMNS)."""
        for table, columns in self._MIGRATION_COLUMNS.items():
            existing = {row[1] for row in con.execute(f"PRAGMA table_info({table})")}
            for name, decl in columns:
                if name not in existing:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")

    def close(self):
        """Schließt die Datenbank-Verbindung (beim App-Ende und beim Sammlungs-Wechsel)."""
        if self._con is not None:
            try:
                self._con.close()
            except sqlite3.Error:
                pass
            self._con = None
            self._con_path = None
        self._suchwortschatz = None

    # ==========================================
    # KERN: ABGLEICH + AUSLIEFERUNG
    # ==========================================
    def iter_documents(self):
        """
        Liefert die Metadaten ALLER PDFs der Sammlung als Liste von Dicts
        (rel_path, name, title, keywords, kid_date, mtime) — Format identisch
        zur Live-Variante in search_manager._iter_documents_live.

        Gleicht dabei den Index mit der Platte ab: neue/veränderte Dateien
        werden nachindiziert (nur DIESE PDFs werden geöffnet), verschwundene
        Einträge entfernt. Wirft bei Problemen eine Exception — der Aufrufer
        fällt dann auf die Live-Suche zurück.
        """
        con = self._connect()
        if con is None:
            raise RuntimeError("Kein gültiger Hauptordner für den Index")
        return self._abgleich(con, os.path.abspath(self.app.master_folder))

    def vermutete_daten(self, pfade, melde=None):
        """
        Vermutetes Dokumentdatum ('JJJJ-MM-TT', '' = keins gefunden) je PDF, für Dokumente ohne
        gespeichertes Datum (PDFHandler.suggest_document_date, dasselbe wie das Datumsfeld). Gemerkte
        Werte gelten, solange Änderungsdatum und Größe passen; nur neue/veränderte PDFs werden gelesen.
        :param pfade: absolute Pfade (Schreibweise egal), Ergebnis ist nach genau diesen Strings geschlüsselt
        :param melde: optional melde(n, gesamt) während des Nachlesens (Aktivitätsanzeige)
        :return: {pfad: datum}; Pfade außerhalb der Sammlung oder nicht lesbare fehlen
        """
        con = self._connect()
        if con is None or not pfade:
            return {}
        master = os.path.abspath(self.app.master_folder)
        gemerkt = {r[0]: r[1:] for r in con.execute("SELECT rel_path, mtime, size, datum FROM datum_vermutet")}
        ergebnis, offen = {}, []
        for pfad in pfade:
            try:
                st = os.stat(pfad)
            except OSError:
                continue
            rel_path = os.path.relpath(os.path.abspath(pfad), master)
            zeile = gemerkt.get(rel_path)
            if zeile is not None and abs(zeile[0] - st.st_mtime) < 1e-6 and zeile[1] == st.st_size:
                ergebnis[pfad] = zeile[2]
            else:
                offen.append((pfad, rel_path, st.st_mtime, st.st_size))
        neu = []
        for n, (pfad, rel_path, mtime, size) in enumerate(offen, start=1):
            if melde and n % 5 == 0:
                melde(n, len(offen))
            datum = PDFHandler.suggest_document_date(pfad) or ""
            ergebnis[pfad] = datum
            neu.append((rel_path, mtime, size, datum))
        if neu:
            with con:
                con.executemany("INSERT OR REPLACE INTO datum_vermutet (rel_path, mtime, size, datum) "
                                "VALUES (?, ?, ?, ?)", neu)
        return ergebnis

    def metadaten(self, pfade, melde=None):
        """
        Titel, Tags und Daten je PDF für die Ordnerliste - aus dem Index, solange Änderungsdatum und
        Größe passen (dieselbe Frische-Regel wie die Suche); nur neue/veränderte PDFs werden geöffnet
        und gleich nachgetragen. Ein großer Ordner öffnet sich so ohne jedes PDF zu lesen (Spike S4:
        5.000 Dateien kalt 35 s, warm 0,6 s statt 0,06 s aus dem Index).
        :param pfade: absolute Pfade, Ergebnis ist nach genau diesen Strings geschlüsselt
        :param melde: optional melde(n, gesamt) alle paar NACHGELESENEN Dateien (Aktivitätsanzeige -
                      jede Meldung zeichnet das Fenster, bei 5.000 Treffern aus dem Index allein 0,8 s)
        :return: {pfad: dict mit den Schlüsseln von PDFHandler.get_metadata (title, keywords,
                 KID_DokumentenDatum, creationDate, KID_ScanZeitpunkt)}; Pfade außerhalb der
                 Sammlung oder nicht lesbare fehlen
        """
        con = self._connect()
        if con is None or not pfade:
            return {}
        master = os.path.abspath(self.app.master_folder)
        ergebnis, to_upsert = {}, []
        for n, pfad in enumerate(pfade, start=1):
            try:
                st = os.stat(pfad)
                rel_path = os.path.relpath(os.path.abspath(pfad), master)
            except (OSError, ValueError):  # ValueError: anderes Laufwerk als die Sammlung
                continue
            if rel_path.startswith(".."):
                continue
            row = con.execute(f"SELECT {_SPALTEN_FILES} FROM files WHERE rel_path = ?", (rel_path,)).fetchone()
            if _zeile_frisch(row, st.st_mtime, st.st_size):
                werte = row[3:13]
            else:
                if melde and len(to_upsert) % 5 == 4:
                    melde(n, len(pfade))
                werte = _werte_aus_pdf(pfad)
                to_upsert.append((rel_path, st.st_mtime, st.st_size) + tuple(werte))
            ergebnis[pfad] = {"title": werte[0], "keywords": werte[1], "KID_DokumentenDatum": werte[2],
                              "creationDate": werte[3], "KID_ScanZeitpunkt": werte[4], "KID_Erfasst": werte[7],
                              "KID_Richtung": werte[9] or ""}
        if to_upsert:
            with con:
                con.executemany(_UPSERT_FILES, to_upsert)
        return ergebnis

    def ablage_absender(self):
        """
        (rel_path, absender) aller PDFs mit gespeichertem Absender (KID_ABSENDER) - die Stimmen
        des Ablage-Gedächtnisses (ablage_gedaechtnis.py). Gleicht vorher wie iter_documents mit der
        Platte ab, aber über eine EIGENE, kurzlebige Verbindung: aus jedem Thread aufrufbar
        (Vollautomatik). Leer ohne Hauptordner.
        """
        master = getattr(self.app, "master_folder", None)
        if not master or not os.path.isdir(master):
            return []
        con = self._open_connection(app_paths.index_path(master))
        try:
            return [(d["rel_path"], d["absender"]) for d in self._abgleich(con, os.path.abspath(master))
                    if d["absender"]]
        finally:
            con.close()

    def mail_verwandte(self, mail_id, eigener_rel_path):
        """
        Die übrigen Dokumente derselben Mail (rel_paths, sortiert): die Anhänge einer Mail oder die Mail und die
        anderen Anhänge eines Anhangs. Der Bezug hängt nur an KID_MAILID, Ordner und Dateiname dürfen sich geändert
        haben. Fragt erst den Index und gleicht nur dann mit der Platte ab, wenn er sichtbar veraltet ist (Dokument
        fehlt noch oder ein Treffer ist verschwunden): der Abgleich läuft durch die ganze Sammlung, das darf nicht bei
        jedem Klick passieren. Eigene Verbindung, aus jedem Thread. Leer ohne Hauptordner.
        """
        master = getattr(self.app, "master_folder", None)
        if not mail_id or not master or not os.path.isdir(master):
            return []
        master = os.path.abspath(master)
        im_papierkorb = eigener_rel_path.startswith("..")     # dort liegt nichts im Index, das wäre nie „frisch“

        con = self._open_connection(app_paths.index_path(master))
        try:
            def frage():
                return [r[0] for r in con.execute("SELECT rel_path FROM files WHERE mail_id = ?", (mail_id,))]

            treffer = frage()
            if ((eigener_rel_path not in treffer and not im_papierkorb)
                    or not all(os.path.exists(os.path.join(master, t)) for t in treffer)):
                self._abgleich(con, master)
                treffer = frage()
        finally:
            con.close()
        return sorted(t for t in treffer if t != eigener_rel_path)

    def pfad_zur_kid_id(self, kid_id):
        """Relativer Pfad des Dokuments mit dieser Dokument-ID oder None - für Belege im Wiki von Hand (wissen.py), die
        ein Dokument über Verschieben und Umbenennen hinweg wiederfinden. Eigene, kurzlebige Verbindung."""
        master = getattr(self.app, "master_folder", None)
        if not kid_id or not master or not os.path.isdir(master):
            return None
        con = self._open_connection(app_paths.index_path(master))
        try:
            zeile = con.execute("SELECT rel_path FROM files WHERE kid_id = ? LIMIT 1", (kid_id,)).fetchone()
        finally:
            con.close()
        return zeile[0] if zeile else None

    def wiki_text(self, rel_path):
        """
        (Text, Kenntext) eines Dokuments aus dem Volltext-Cache, ("", "") wenn es keinen Text hat. Steht das Dokument
        noch nicht im Cache (frisch abgelegt, seither keine Volltextsuche), wird der Cache erst abgeglichen - sonst
        gälte ein lesbares Dokument als „ohne erkannten Text“ (Peter 13.11.2026). Text = Textebene +
        OCR- + KI-Text (an die KI und für die Prüfung der Zitate im Wiki); der rechtschreib-korrigierte Text bleibt draußen,
        er hängt vom Wortschatz ab und doppelt nur. Kenntext = der beim Speichern stabile Teil (Textebene, ohne
        sie der OCR-Text). Eigene Verbindung, aus jedem Thread.
        """
        master = getattr(self.app, "master_folder", None)
        if not master or not os.path.isdir(master):
            return "", ""
        con = self._open_connection(app_paths.index_path(master))
        try:
            frage = "SELECT text, text_ocr, text_ai FROM fulltext WHERE rel_path = ?"
            zeile = con.execute(frage, (rel_path,)).fetchone()
            if zeile is None and os.path.isfile(os.path.join(master, rel_path)):
                self._abgleich(con, os.path.abspath(master))
                self._ensure_fulltext_baseline(con, os.path.abspath(master))
                zeile = con.execute(frage, (rel_path,)).fetchone()
        finally:
            con.close()
        teile = [t for t in (zeile or ()) if t and t.strip()]
        return "\n".join(teile), (teile[0] if teile else "")

    def _abgleich(self, con, master):
        """Kern von iter_documents: Platte gegen Index abgleichen, Veraltetes nachlesen, Liste liefern."""
        # 1. Ist-Zustand der Platte einsammeln (nur Datei-Attribute, keine PDF-Zugriffe)
        disk = {}
        for root_dir, _, files in os.walk(master):
            for name in files:
                if name.startswith('.') or not name.lower().endswith(".pdf"):
                    continue
                abs_path = os.path.join(root_dir, name)
                try:
                    st = os.stat(abs_path)
                except OSError:
                    continue  # Datei gerade verschwunden/gesperrt -> nächster Lauf
                disk[os.path.relpath(abs_path, master)] = (st.st_mtime, st.st_size)

        # 2. Index-Bestand laden
        rows = {r[0]: r for r in con.execute(f"SELECT {_SPALTEN_FILES} FROM files")}

        # 3. Abgleich: frische Einträge direkt verwenden, veraltete/neue nachlesen
        documents = []
        to_upsert = []
        for rel_path, (mtime, size) in disk.items():
            row = rows.get(rel_path)
            if _zeile_frisch(row, mtime, size):
                title, keywords, kid_date, creation_date, scan_zeit, kid_id, absender, erfasst, mail_id, richtung = row[3:13]
            else:
                title, keywords, kid_date, creation_date, scan_zeit, kid_id, absender, erfasst, mail_id, richtung = _werte_aus_pdf(
                    os.path.join(master, rel_path))
                to_upsert.append((rel_path, mtime, size, title, keywords, kid_date, creation_date, scan_zeit, kid_id,
                                  absender, erfasst, mail_id, richtung))

            documents.append({
                "rel_path": rel_path,
                "name": os.path.basename(rel_path),
                "title": title,
                "keywords": keywords,
                "kid_date": kid_date,
                "creation_date": creation_date,
                "scan_zeit_embedded": scan_zeit,
                "kid_id": kid_id,
                "absender": absender,
                "erfasst": erfasst,
                "richtung": richtung or "",
                "mtime": mtime,
            })

        # 4. Index aktualisieren (eine Transaktion), Verschwundenes entfernen
        removed = set(rows) - set(disk)
        with con:
            con.executemany(_UPSERT_FILES, to_upsert)
            if removed:
                con.executemany("DELETE FROM files WHERE rel_path = ?", [(r,) for r in removed])

        return documents

    # ==========================================
    # VOLLTEXT-CACHE (Phase 2)
    # ==========================================
    def _load_vocabulary(self, con):
        """Lädt den persistierten Wortschatz (siehe SCHEMA_VOCABULARY) als Counter - leer, wenn noch nie befüllt."""
        return Counter(dict(con.execute("SELECT word, freq FROM vocabulary")))

    def wortschatz_der_sammlung(self):
        """
        Persistierter Wortschatz der aktuellen Sammlung als Counter - über eine EIGENE,
        kurzlebige Verbindung, daher aus jedem Thread aufrufbar (siehe FALLSTRICKE zur
        geteilten sqlite3-Connection). Leer, wenn kein Hauptordner/Index vorhanden.
        """
        master = getattr(self.app, "master_folder", None)
        if not master or not os.path.isdir(master):
            return Counter()
        try:
            con = self._open_connection(app_paths.index_path(master))
            try:
                return self._load_vocabulary(con)
            finally:
                con.close()
        except sqlite3.Error:
            return Counter()

    def _persist_vocabulary_delta(self, con, delta):
        """Zählt die Wörter aus `delta` additiv auf den bestehenden Wortschatz drauf (siehe SCHEMA_VOCABULARY - Häufigkeit wird nie exakt zurückgerechnet, nur hochgezählt)."""
        if not delta:
            return
        with con:
            con.executemany(
                "INSERT INTO vocabulary (word, freq) VALUES (?, ?) "
                "ON CONFLICT(word) DO UPDATE SET freq = freq + excluded.freq",
                list(delta.items()))

    def _ensure_fulltext_baseline(self, con, master):
        """
        Bringt die "Standard"-Stufe des Volltext-Cache auf den aktuellen Stand: liest nur
        neue/veränderte Dokumente (Frische-Prüfung mtime+Größe gegen die files-Tabelle)
        und entfernt verwaiste Einträge. Gemeinsam genutzt von search_fulltext und den
        upgrade_to_*_tier-Methoden, damit alle auf einer garantiert vollständigen Basis
        arbeiten. Ändert sich eine Datei, wird ihre Zeile per INSERT OR REPLACE komplett
        neu angelegt (auch text_erweitert/text_ocr/text_ai/tier zurückgesetzt) - ein evtl.
        vorhandener verbesserter Text wäre für den geänderten Inhalt ohnehin nicht mehr gültig.

        Ist die Volltext-Qualitätsstufe (settings.json `index_text_mode`) auf mindestens
        "erweitert" gestellt, wird die lokale Rechtschreibkorrektur (spell_correct.py)
        SOFORT beim Einlesen mit angewendet - neue/geänderte Dokumente landen dann direkt
        auf Tier "erweitert" statt "standard". Kein manueller Klick auf "Jetzt ausführen"
        mehr nötig (der Button dort ist seither nur noch ein Nachzieh-Lauf für Dokumente,
        die schon VOR dieser Automatisierung im Cache standen). Der Wortschatz wächst dabei
        additiv mit (siehe _persist_vocabulary_delta) statt bei jedem Aufruf aus dem
        kompletten Cache neu gezählt zu werden.

        Bewusster Unterschied zu upgrade_to_erweitert_tier (Backfill): hier korrigiert
        NUR der bereits VOR diesem Batch bekannte, persistierte Wortschatz - die frisch
        eingelesenen Wörter dieses Batches werden zwar persistiert (kommen künftigen
        Läufen zugute), fließen aber NICHT in die Korrektur DIESES Batches mit ein (sonst
        könnte ein kaputtes Wort durch seine bloße Anwesenheit im Rohtext sofort als
        "bekannt" gelten und sich nie selbst korrigieren). Bei einem einzelnen neu
        gescannten Dokument gäbe es sonst keine verlässliche Gegenprobe. Der manuelle
        Backfill verarbeitet dagegen typischerweise viele Dokumente auf einmal, dort
        überwiegt der Nutzen des vollen Kontexts das kleine Restrisiko.
        """
        stale = con.execute("""
            SELECT f.rel_path, f.mtime, f.size FROM files f
            LEFT JOIN fulltext t ON t.rel_path = f.rel_path
            WHERE t.rel_path IS NULL OR t.mtime != f.mtime OR t.size != f.size
        """).fetchall()

        if stale:
            config = getattr(self.app, 'config', None)
            auto_erweitert = bool(config) and config.get("index_text_mode", "standard") != "standard"

            # Aktivitätsanzeige: nach einem Ablage-Lauf können hier Dutzende Dokumente
            # anstehen - ohne Zähler wirkt die erste Suche danach wie ein Hänger
            texts = {}
            with aktivitaet.phase(f"Suche: {len(stale)} neue Dokumente einlesen…") as p:
                for nr, (rel_path, _, _) in enumerate(stale, start=1):
                    texts[rel_path] = PDFHandler.get_fulltext(os.path.join(master, rel_path))
                    p.melde(f"Suche: neue Dokumente einlesen {nr}/{len(stale)}…")
                    aktivitaet.atme()

            vocabulary = None
            if auto_erweitert:
                # WICHTIG: Korrektur nutzt bewusst NUR den bereits VOR diesem Batch
                # bekannten Wortschatz - würden die frisch eingelesenen (evtl. noch
                # kaputten) Wörter dieses Batches selbst vorher mit eingemischt, würde
                # ein kaputtes Wort durch seine bloße Anwesenheit im Rohtext sofort als
                # "bekannt" gelten (correct_word prüft nur Mitgliedschaft, nicht
                # Häufigkeit) und könnte sich nie selbst korrigieren. Der Batch-eigene
                # Wortschatz wird trotzdem persistiert - er hilft ab dem NÄCHSTEN Lauf.
                vocabulary = self._load_vocabulary(con)
                delta = spell_correct.build_vocabulary(texts.values())
                self._persist_vocabulary_delta(con, delta)

            to_upsert = []
            for rel_path, mtime, size in stale:
                text = texts[rel_path]
                if auto_erweitert:
                    to_upsert.append((rel_path, mtime, size, text,
                                       spell_correct.suggest_corrected_text(text, vocabulary), "erweitert"))
                else:
                    to_upsert.append((rel_path, mtime, size, text, "", "standard"))
            with con:
                con.executemany(
                    "INSERT OR REPLACE INTO fulltext (rel_path, mtime, size, text, text_erweitert, tier) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    to_upsert)
            self._suchwortschatz = None
            logger = getattr(self.app, 'logger', None)
            if logger:
                zusatz = " (inkl. lokaler Rechtschreibkorrektur)" if auto_erweitert else ""
                logger.info(f"Volltext-Cache: {len(stale)} Dokument(e) nachindiziert{zusatz}.")

        with con:
            if con.execute("DELETE FROM fulltext WHERE rel_path NOT IN (SELECT rel_path FROM files)").rowcount:
                self._suchwortschatz = None

    def _wortschatz_fuer_suche(self, con):
        """
        Wortschatz des Volltext-Cache für die schnelle unscharfe Suche: (Einzelwörter, Wortpaare) aus
        denselben zusammengefügten Texten, die search_fulltext durchsucht. Bleibt im Speicher, bis eine
        Schreibstelle ihn verwirft - oder bis sich der Stand ändert (Anzahl/Änderungsdaten/Größen, falls
        z.B. eine zweite KID-Instanz in dieselbe Sammlung schreibt). Bei 20.000 Mails ~1 s.
        """
        stand = (self._con_path,) + tuple(con.execute(
            "SELECT COUNT(*), TOTAL(mtime), TOTAL(size) FROM fulltext").fetchone())
        gemerkt = self._suchwortschatz
        if gemerkt is not None and gemerkt[0] == stand:
            return gemerkt[1], gemerkt[2]
        woerter, paare = set(), set()
        for texte in con.execute("SELECT text, text_erweitert, text_ocr, text_ai FROM fulltext"):
            ws = WORT.findall("\n".join(t for t in texte if t).lower())
            woerter.update(ws)
            paare.update(a + b for a, b in zip(ws, ws[1:]))
        self._suchwortschatz = (stand, woerter, paare)
        return woerter, paare

    def search_fulltext(self, matcher):
        """
        Volltextsuche über den Text-Cache: liefert die Menge der rel_paths, deren Text
        (Original UND ein evtl. vorhandener verbesserter Text jeder Stufe - "ergänzen statt
        ersetzen", siehe upgrade_to_erweitert_tier/upgrade_to_ocr_tier/upgrade_to_meister_tier)
        den `matcher` (siehe SearchManager.build_matcher) erfüllt - identische Suchsemantik
        wie die bisherige Live-OCR-Suche, aber ohne pro Suche jede PDF zu öffnen.

        Erwartet, dass die files-Tabelle frisch ist (execute_search ruft iter_documents
        im selben Suchlauf vorher auf). Wirft bei Problemen eine Exception - der
        Aufrufer fällt dann auf die Live-Suche zurück (gleiches Muster wie iter_documents).

        Schneller Weg für unscharfe Einzelwörter (Matcher mit `begriff`/`aehnliche_woerter`, siehe
        SearchManager.begriff_matcher): die ähnlichen Wörter EINMAL aus dem Wortschatz holen, dann je
        Dokument nur noch wörtlich suchen - dieselben Treffer, aber ohne Millionen Einzelvergleiche
        (Spike S4, KONZEPT_MAIL_IMPORT.md). Andere Matcher (Phrase, Platzhalter, kurz) wie bisher.
        """
        con = self._connect()
        if con is None:
            raise RuntimeError("Kein gültiger Hauptordner für den Index")

        master = os.path.abspath(self.app.master_folder)
        self._ensure_fulltext_baseline(con, master)

        pruefe = matcher
        begriff = getattr(matcher, "begriff", None)
        aehnliche_woerter = getattr(matcher, "aehnliche_woerter", None)
        if begriff and callable(aehnliche_woerter):
            woerter, paare = self._wortschatz_fuer_suche(con)
            muster = muster_fuer_aehnliche(aehnliche_woerter(itertools.chain(woerter, paare)), woerter, paare)

            def pruefe(text):
                return begriff in text or (muster is not None and muster.search(text) is not None)

        hits = set()
        for rel_path, text, text_erweitert, text_ocr, text_ai in con.execute(
                "SELECT rel_path, text, text_erweitert, text_ocr, text_ai FROM fulltext"):
            combined = "\n".join(t for t in (text, text_erweitert, text_ocr, text_ai) if t)
            if combined and pruefe(combined.lower()):
                hits.add(rel_path)
        return hits

    def upgrade_to_erweitert_tier(self, on_progress=None, should_stop=None):
        """
        "Erweitert"-Stufe: die schwächste, aber auch mit Abstand schnellste Stufe - rein
        lokale, KI-freie Korrektur (siehe spell_correct.py: Regel-Cleanup + Editierdistanz-
        Spellchecker gegen einen aus der eigenen Sammlung gebauten Wortschatz), KEIN
        Ollama-Server nötig, kein Netzwerk-Roundtrip pro Dokument (ursprünglich per Ollama
        umgesetzt, aber auf Nutzerwunsch 12.07.2026 durch die lokale Variante ersetzt - war
        genauso langsam wie "Meister", obwohl es die günstige Einstiegsstufe sein sollte).

        Seit derselben Änderung wird diese Stufe außerdem AUTOMATISCH beim Scannen
        angewendet, sobald `index_text_mode` != "standard" ist (siehe
        _ensure_fulltext_baseline) - dieser manuelle Batch-Lauf ist daher nur noch ein
        NACHZIEH-Lauf für Dokumente, die schon VOR der Automatisierung (oder während
        `index_text_mode` noch "standard" war) im Cache standen und auf Tier "standard"
        hängengeblieben sind. Ergänzt deren Wörter additiv in den persistierten Wortschatz
        (siehe SCHEMA_VOCABULARY/_persist_vocabulary_delta). Anders als die automatische
        Anwendung (siehe dortiger Kommentar zur Selbstvergiftungs-Gefahr bei einzelnen
        Dokumenten) fließen die frisch eingelesenen Wörter DIESES Batches hier bewusst
        MIT in die eigene Korrektur ein - bei einem Nachzieh-Lauf über typischerweise
        viele Dokumente auf einmal überwiegt der Nutzen des vollen Kontexts das kleine
        Restrisiko einer Selbstbestätigung. `text_erweitert` bleibt additiv (`text` bleibt
        unangetastet). Verarbeitet bewusst NUR Dokumente auf Tier "standard": bei
        "erweitert"/"fortgeschritten"/"meister" liegt bereits eine gleichwertige oder
        bessere Textquelle vor, ein erneuter Lauf wäre reine Verschwendung.

        :param on_progress: optionaler Callback(erledigt, gesamt) für eine Fortschrittsanzeige.
        :param should_stop: optionaler Callback() -> bool; liefert er True, wird nach dem
                             gerade laufenden Dokument abgebrochen (bereits Verarbeitetes bleibt erhalten).
        :return: Anzahl tatsächlich hochgestufter Dokumente.

        WICHTIG: Öffnet wie upgrade_to_ocr_tier/upgrade_to_meister_tier eine EIGENE,
        kurzlebige Verbindung statt der geteilten self._con - läuft in einem
        Hintergrund-Thread (siehe tools/settings_editor.py), siehe dortiger Kommentar
        zum Thread-Safety-Bug.
        """
        master_folder = getattr(self.app, 'master_folder', None)
        if not master_folder or not os.path.isdir(master_folder):
            raise RuntimeError("Kein gültiger Hauptordner für den Index")

        master = os.path.abspath(master_folder)
        con = self._open_connection(app_paths.index_path(master))
        try:
            self._ensure_fulltext_baseline(con, master)

            todo = con.execute("SELECT rel_path, text FROM fulltext WHERE tier = 'standard'").fetchall()

            vocabulary = self._load_vocabulary(con)
            delta = spell_correct.build_vocabulary(text for _, text in todo)
            vocabulary.update(delta)
            self._persist_vocabulary_delta(con, delta)

            done = 0
            for rel_path, text in todo:
                if should_stop and should_stop():
                    break
                text_erweitert = spell_correct.suggest_corrected_text(text, vocabulary)
                with con:
                    con.execute("UPDATE fulltext SET text_erweitert = ?, tier = 'erweitert' WHERE rel_path = ?",
                                (text_erweitert, rel_path))
                self._suchwortschatz = None
                done += 1
                if on_progress:
                    on_progress(done, len(todo))
            return done
        finally:
            con.close()

    def upgrade_to_ocr_tier(self, tessdata_path, on_progress=None, should_stop=None):
        """
        "Fortgeschritten"-Stufe: erzwingt echtes Bild-OCR (siehe pdf_handler.
        get_fulltext_ocr) für alle Dokumente, deren Cache-Eintrag noch nicht mindestens
        "fortgeschritten" ist, und ergänzt das Ergebnis in `text_ocr` (der ursprüngliche
        `text` bleibt unangetastet). Teuer (~0,4s/Seite, siehe KONZEPT_FILE_INDEX.md) -
        daher ein expliziter Batch-Lauf statt automatisch bei jeder Suche.

        :param on_progress: optionaler Callback(erledigt, gesamt) für eine Fortschrittsanzeige.
        :param should_stop: optionaler Callback() -> bool; liefert er True, wird nach dem
                             gerade laufenden Dokument abgebrochen (bereits Verarbeitetes bleibt erhalten).
        :return: Anzahl tatsächlich hochgestufter Dokumente.

        WICHTIG: Öffnet bewusst eine EIGENE, kurzlebige Verbindung (_open_connection)
        statt der geteilten self._con - diese Methode läuft in einem Hintergrund-Thread
        (siehe tools/settings_editor.py), während im Haupt-Thread weiter gesucht werden
        kann. sqlite3-Connections sind nicht threadübergreifend nutzbar (Python wirft
        ProgrammingError). Eine geteilte, thread-fremde Connection hätte hier einen
        besonders tückischen Bug verursacht: search_fulltext fängt Exceptions ab und
        fällt bei Fehlern still auf die langsame Live-Suche zurück (siehe dort) - sichtbar
        nur als "der Cache hat den Text, die Suche findet ihn trotzdem nicht", ganz ohne
        Fehlermeldung.
        """
        master_folder = getattr(self.app, 'master_folder', None)
        if not master_folder or not os.path.isdir(master_folder):
            raise RuntimeError("Kein gültiger Hauptordner für den Index")

        master = os.path.abspath(master_folder)
        con = self._open_connection(app_paths.index_path(master))
        try:
            self._ensure_fulltext_baseline(con, master)

            placeholders = ",".join("?" * len(self.OCR_TIERS))
            todo = [r[0] for r in con.execute(
                f"SELECT rel_path FROM fulltext WHERE tier NOT IN ({placeholders})", self.OCR_TIERS)]

            done = 0
            for rel_path in todo:
                if should_stop and should_stop():
                    break
                text_ocr = PDFHandler.get_fulltext_ocr(os.path.join(master, rel_path), tessdata_path)
                with con:
                    con.execute("UPDATE fulltext SET text_ocr = ?, tier = 'fortgeschritten' WHERE rel_path = ?",
                                (text_ocr, rel_path))
                self._suchwortschatz = None
                done += 1
                if on_progress:
                    on_progress(done, len(todo))
            return done
        finally:
            con.close()

    def upgrade_to_meister_tier(self, base_url, model, on_progress=None, should_stop=None):
        """
        "Meister"-Stufe: schickt den Re-OCR-Text der "Fortgeschritten"-Stufe (`text_ocr`)
        an ein Ollama-Textmodell zur KI-Prüfung (Rechtschreib-/Plausibilitätskorrektur ohne
        neue Inhalte zu erfinden, siehe ollama_client.suggest_cleaned_text) und ergänzt das
        Ergebnis in `text_ai` (text/text_ocr bleiben unangetastet - "ergänzen statt
        ersetzen"). Baut bewusst auf der Fortgeschritten-Stufe auf statt selbst neu zu
        OCR'en (siehe OCR_TIERS) - Dokumente, die noch nicht re-OCR't wurden, werden
        übersprungen, der Aufrufer soll den Nutzer dafür auf "zuerst Fortgeschritten
        ausführen" hinweisen.

        :param base_url/model: Ollama-Server-Adresse/Modell (siehe settings.json ollama_url/ollama_model).
        :param on_progress: optionaler Callback(erledigt, gesamt) für eine Fortschrittsanzeige.
        :param should_stop: optionaler Callback() -> bool; liefert er True, wird nach dem
                             gerade laufenden Dokument abgebrochen (bereits Verarbeitetes bleibt erhalten).
        :return: (erledigt, übersprungen) - Anzahl tatsächlich hochgestufter bzw. wegen
                 fehlendem Re-OCR übersprungener Dokumente.

        WICHTIG: Öffnet wie upgrade_to_ocr_tier eine EIGENE, kurzlebige Verbindung statt
        der geteilten self._con - läuft in einem Hintergrund-Thread (siehe
        tools/settings_editor.py), siehe dortiger Kommentar zum Thread-Safety-Bug.
        """
        master_folder = getattr(self.app, 'master_folder', None)
        if not master_folder or not os.path.isdir(master_folder):
            raise RuntimeError("Kein gültiger Hauptordner für den Index")

        master = os.path.abspath(master_folder)
        con = self._open_connection(app_paths.index_path(master))
        try:
            self._ensure_fulltext_baseline(con, master)

            rows = con.execute("SELECT rel_path, tier, text_ocr FROM fulltext WHERE tier != 'meister'").fetchall()
            todo = [(rel_path, text_ocr) for rel_path, tier, text_ocr in rows if tier == 'fortgeschritten']
            skipped = len(rows) - len(todo)

            done = 0
            for rel_path, text_ocr in todo:
                if should_stop and should_stop():
                    break
                text_ai = ollama_client.suggest_cleaned_text(text_ocr, base_url=base_url, model=model)
                with con:
                    con.execute("UPDATE fulltext SET text_ai = ?, tier = 'meister' WHERE rel_path = ?",
                                (text_ai, rel_path))
                self._suchwortschatz = None
                done += 1
                if on_progress:
                    on_progress(done, len(todo))
            return done, skipped
        finally:
            con.close()

    def rebuild(self):
        """Verwirft den kompletten Index (Metadaten UND Volltext-Cache) und baut die Metadaten neu auf (für den 'Index neu aufbauen'-Button, Phase 3); der Volltext-Cache füllt sich bei der nächsten OCR-Suche nach."""
        con = self._connect()
        if con is None:
            return 0
        with con:
            con.execute("DELETE FROM files")
            con.execute("DELETE FROM fulltext")
            con.execute("DELETE FROM datum_vermutet")
        self._suchwortschatz = None
        return len(self.iter_documents())
