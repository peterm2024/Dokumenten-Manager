import os
import re
import fnmatch
import datetime
import tkinter as tk
from difflib import SequenceMatcher
import app_paths
import aktivitaet
import index_manager
import scan_date
import suchsyntax
from ui_utils import UIUtils
from pdf_handler import PDFHandler

# Steht in der leeren Vorschau, wenn eine Textsuche ohne „Inhalt (OCR)“ nichts findet: die
# Vorschau markiert Treffer im Seitentext auch ohne OCR - ohne Erklärung wirkte es, als fände
# die Suche das Dokument und zeige es trotzdem nicht in der Liste (Peter 25.10.2026).
HINWEIS_OHNE_OCR = ("Keine Treffer in Name, Titel, Tags und Dokument-ID.\n\n"
                    "Mit dem Häkchen „Inhalt (OCR)“ wird auch im Dokumenttext gesucht.")

# Wortgrenze der unscharfen Suche - dieselbe wie im Wortschatz des Volltext-Cache
WORT = index_manager.WORT

# Hintergrund des Suchfelds (Peter 01.11.2026): sieht man, ob der Text schon gesucht ist?
SUCHFELD_UNGESENDET = "#fff6cc"   # dezent gelb: getippt, noch nicht mit Return gesucht
SUCHFELD_GESENDET = "#e6f4e4"     # dezent grün: die Liste zeigt genau diese Suche


def suchfeld_zustand(eingegeben, angezeigt):
    """'leer' / 'ungesendet' / 'gesendet' für den Suchfeld-Hintergrund.
    :param eingegeben: Text im Suchfeld
    :param angezeigt: Suchtext der angezeigten Suche (SearchManager._angezeigt[0]) oder None"""
    text = (eingegeben or "").strip()
    if not text:
        return "leer"
    return "gesendet" if angezeigt is not None and text == angezeigt.strip() else "ungesendet"


TREFFER_BREITE = 13     # Zeichen, wie in layout_builder: Die Suchleiste soll nicht springen, wenn die Zahl wächst


class SearchManager:
    # Unscharfe Suche: Mindest-Ähnlichkeit (0..1) und Mindestlänge des Suchbegriffs.
    # 0.8 kalibriert an echten Fällen: Tippfehler/OCR-Fehler wie "Rechnnug"->"Rechnung"
    # (0.87+) werden gefunden, verschiedene Wörter wie "Steuer"/"Feuer" (0.73) nicht.
    FUZZY_THRESHOLD = 0.8
    FUZZY_MIN_LEN = 4
    # Ist das Wort im Dokument KÜRZER als der Suchbegriff, muss es ähnlicher sein: ein
    # Bruchstück wie "Stal" (aus dem Müll-Token "Sta(l^'tc^ke", der Texterkennung von
    # "Stadtwerke") liegt zu "kostal" genau bei 0.8 und markierte in der Vorschau
    # "Stadtwerke" (Nutzerfund 11.09.2026, FALLSTRICKE #64). Ein einzelner fehlender
    # Buchstabe ("Rechnug" für "rechnung", 0.93; "stadtvverke" ~ "stadtwerke", 0.857)
    # bleibt darüber.
    FUZZY_THRESHOLD_KUERZER = 0.85

    def __init__(self, app):
        """
        Initialisiert den Controller für die globale Dateisuche und Filterung.
        :param app: Referenz auf die Hauptinstanz.
        """
        self.app = app
        # Filter der gerade ANGEZEIGTEN Suche (Text, Von, Bis, Filter-Tags) - None = Ordneransicht.
        # Seit die Textsuche erst mit Return startet (Peter 01.11.2026), kann im Feld Text stehen,
        # der noch nicht gesucht wurde; „läuft eine Suche?“ fragt deshalb hiernach, nicht nach dem Feld.
        self._angezeigt = None

    @staticmethod
    def build_matcher(search_text):
        """
        Baut aus dem Suchtext eine Prüf-Funktion (String -> bool).
        - Mit * oder ? im Suchtext: Wildcard-Matching (z.B. "Rechnung*2026").
        - Einzelwort ab 4 Zeichen: Enthält-Suche PLUS unscharfer Wortvergleich,
          der Tippfehler und Texterkennungs-Fehler verzeiht ("Rechnnug" findet
          "Rechnung").
        - Mehrere Wörter: UND-Verknüpfung - jedes Wort muss irgendwo im Ziel
          vorkommen, Reihenfolge egal, jedes für sich nach der Einzelwort-Regel
          ("steuer 2023" findet "Grundsteuerbescheid ... 2023, Steuern"; Nutzerfund
          30.08.2026: vorher musste die ganze Wortfolge zusammenhängend vorkommen).
        - In Anführungszeichen: nur der zusammenhängende Text ("Max Mustermann" findet
          NICHT "Mustermann, Max"; Nutzerwunsch 11.09.2026), siehe begriff_matcher. Ein einzelnes
          Wort in Anführungszeichen gilt genau: "Ramen" findet weder "Rahmen" noch "Ramensuppe"
          (Peter 05.11.2026, die Unschärfe lässt sich so gezielt abschalten).
        - Sehr kurze Begriffe (< 4 Zeichen): klassische Enthält-Suche.
        Der Suchtext wird als "kommt irgendwo vor" interpretiert, Muster
        müssen also nicht den kompletten Text abdecken.
        """
        search_text = search_text.strip().lower()
        if not search_text:
            return lambda target: True

        begriffe = SearchManager.split_terms(search_text)
        if len(begriffe) == 1:
            return SearchManager.begriff_matcher(begriffe[0])
        teil_matcher = [SearchManager.begriff_matcher(b) for b in begriffe]
        return lambda target: all(m(target) for m in teil_matcher)

    @staticmethod
    def begriff_matcher(begriff):
        """
        Prüf-Funktion für EINEN Begriff aus split_terms. Eine Phrase (enthält Leerzeichen,
        kommt nur aus Anführungszeichen) muss exakt zusammenhängend vorkommen - Zeilen-
        umbrüche und mehrfache Leerzeichen im Ziel zählen dabei als ein Leerzeichen, weil
        die Texterkennung Namen gern über den Zeilenumbruch zieht. Sonst gilt die
        Einzelwort-Regel aus build_matcher (Wildcard / kurz exakt / unscharf). Ein Begriff in
        Anführungszeichen (kommt so aus split_terms) ist genau dieses ganze Wort; die Wortgrenze
        ist dieselbe wie sonst, auch am Unterstrich („ramen_2024.pdf“ trifft). Dieser Matcher hat
        bewusst kein `begriff`: der Volltext-Cache fragt ihn direkt, ohne ähnliche Wörter.
        """
        search_text = begriff.strip().lower()
        if not search_text:
            return lambda target: True

        if len(search_text) > 2 and search_text[0] == '"' and search_text[-1] == '"':
            genau = re.compile(r"(?<![^\W_])" + re.escape(search_text[1:-1]) + r"(?![^\W_])")
            return lambda target: genau.search(target.lower()) is not None

        if " " in search_text:
            return lambda target: search_text in " ".join(target.lower().split())

        if "*" in search_text or "?" in search_text:
            # fnmatch.translate liefert ein verankertes Regex -> mit *...* entankern
            pattern = re.compile(fnmatch.translate(f"*{search_text}*"), re.IGNORECASE | re.DOTALL)
            return lambda target: pattern.match(target) is not None

        # Sehr kurze Begriffe: nur exakte Enthält-Suche
        # (unscharf wäre bei kurzen Wörtern zu treffsicher-los: "Bank" ~ "Dank")
        if len(search_text) < SearchManager.FUZZY_MIN_LEN:
            return lambda target: search_text in target.lower()

        def matcher(target):
            target = target.lower()
            if search_text in target:
                return True

            # Unscharfer Vergleich Wort für Wort (Regeln in _aehnlichkeits_pruefer).
            # [^\W_]+ statt \w+: auch am Unterstrich trennen, sonst bliebe ein
            # Dateiname wie "stadtwerke_rechnung_2026" ein einziges langes Token.
            aehnlich = SearchManager._aehnlichkeits_pruefer(search_text)
            words = WORT.findall(target)

            # Zusätzlich benachbarte Wort-Paare zusammengeklebt prüfen: Texterkennung
            # zerreißt Wörter gern mitten durch ("schornsteinl'eger", "Steiier-zwecken") —
            # als Paar geheilt matchen sie wieder ("schornsteinleger" ~ "schornsteinfeger").
            candidates = words + [a + b for a, b in zip(words, words[1:])]
            return any(aehnlich(word) for word in candidates)

        # Für den Volltext-Cache (index_manager.search_fulltext, Spike S4 01.11.2026): statt jedes
        # Wort jedes Dokuments einzeln unscharf zu vergleichen, holt der Index die ähnlichen Wörter
        # EINMAL aus dem Wortschatz der Sammlung und sucht danach nur noch wörtlich - gleiche Treffer,
        # bei 20.000 Dokumenten 0,3 statt 3,5 s für ein Wort ohne Treffer
        matcher.begriff = search_text

        def aehnliche_woerter(wortschatz):
            aehnlich = SearchManager._aehnlichkeits_pruefer(search_text)
            return {w for w in wortschatz if aehnlich(w)}

        matcher.aehnliche_woerter = aehnliche_woerter
        return matcher

    @staticmethod
    def _aehnlichkeits_pruefer(search_text):
        """
        Prüf-Funktion "ist dieses Wort dem Suchbegriff ähnlich genug?" - die Regeln der unscharfen
        Suche an EINER Stelle (begriff_matcher je Dokument, aehnliche_woerter für den Wortschatz).
        Billige Vorfilter (Längenfenster, quick_ratio), bevor der teure ratio() rechnet. Hält einen
        eigenen SequenceMatcher - je Aufruf neu anlegen, nicht zwischen Threads teilen.
        """
        sm = SequenceMatcher()
        sm.set_seq2(search_text)
        max_len_diff = max(1, round(len(search_text) * 0.25))

        def aehnlich(word):
            if abs(len(word) - len(search_text)) > max_len_diff:
                return False
            schwelle = (SearchManager.FUZZY_THRESHOLD_KUERZER if len(word) < len(search_text)
                        else SearchManager.FUZZY_THRESHOLD)
            sm.set_seq1(word)
            return sm.quick_ratio() >= schwelle and sm.ratio() >= schwelle

        return aehnlich

    @staticmethod
    def split_terms(search_text):
        """Suchtext → Begriffe (Mehrwort-Suche = UND, Anführungszeichen, Platzhalter); seit 08.11.2026 in
        suchsyntax.split_terms, damit die Mail-Suche dieselbe Syntax versteht."""
        return suchsyntax.split_terms(search_text)

    def _iter_documents(self, master_folder):
        """
        Liefert die Metadaten aller PDFs der Sammlung als Dicts (rel_path, name,
        title, keywords, kid_date, creation_date, scan_zeit_embedded, mtime) —
        bevorzugt aus dem Suchindex (schnell, öffnet nur neue/veränderte PDFs), bei
        abgeschaltetem oder defektem Index transparent live von der Platte (bisheriges
        Verhalten).
        """
        if self.app.config.get("use_index", True) and getattr(self.app, 'index_manager', None):
            try:
                return self.app.index_manager.iter_documents()
            except Exception as e:
                if hasattr(self.app, 'logger'):
                    self.app.logger.error(f"Suchindex nicht verfügbar, nutze Live-Suche: {e}")
        return self._iter_documents_live(master_folder)

    @staticmethod
    def _iter_documents_live(master_folder):
        """Live-Variante ohne Index: öffnet jede PDF für die Metadaten (langsam, aber immer verfügbar)."""
        documents = []
        for root_dir, _, files in os.walk(master_folder):
            for entry_name in files:
                if entry_name.startswith('.') or not entry_name.lower().endswith(".pdf"):
                    continue
                abs_path = os.path.join(root_dir, entry_name)
                meta = PDFHandler.get_metadata(abs_path)
                documents.append({
                    "rel_path": os.path.relpath(abs_path, master_folder),
                    "name": entry_name,
                    "title": meta.get("title", ""),
                    "keywords": meta.get("keywords", ""),
                    "kid_date": meta.get("KID_DokumentenDatum", ""),
                    "creation_date": meta.get("creationDate", ""),
                    "scan_zeit_embedded": meta.get("KID_ScanZeitpunkt", ""),
                    "erfasst": meta.get("KID_Erfasst", "") or "",
                    "kid_id": meta.get("KID_ID", "") or "",
                    "richtung": meta.get("KID_Richtung", "") or "",
                    "mtime": os.path.getmtime(abs_path),
                })
        return documents

    def parse_date(self, date_str, ende=False):
        """Von-/Bis-Feld → date: „15.03.2021“, „2020“, „07.2020“ (Nutzerwunsch 01.09.2026); seit 08.11.2026 in
        suchsyntax.datum_grenze, damit die Mail-Suche dieselben Formen versteht.
        :param ende: True für das Bis-Feld (füllt ans ENDE des Jahres/Monats auf)."""
        return suchsyntax.datum_grenze(date_str, ende)

    def execute_search(self, master_folder, search_text, date_from_str, date_to_str, filter_tags):
        """
        Durchsucht den gesamten Master-Ordner nach Kriterien.
        Gibt eine formatierte Liste von Datei-Einträgen für den Treeview zurück.
        """
        if not master_folder or not os.path.isdir(master_folder):
            return []

        date_from = self.parse_date(date_from_str)
        date_to = self.parse_date(date_to_str, ende=True)
        search_text = search_text.strip().lower()
        # Mehrwort-Suche: jeder Begriff darf in einem ANDEREN Feld stehen ("steuer" im
        # Titel, "2023" nur im Volltext) - darum je Begriff ein eigener Matcher und ein
        # eigener Volltext-Treffer-Satz, verknüpft mit UND.
        terms = self.split_terms(search_text)
        term_matchers = [self.begriff_matcher(t) for t in terms]

        file_data_list = []
        global_tag_counts = {}
        mails_aus = index_manager.mails_ausgeblendet(self.app)
        self.ausgeblendete_treffer = 0

        # 1. Dokument-Metadaten beschaffen: bevorzugt aus dem Index (Millisekunden,
        #    keine PDF-Zugriffe), sonst live von der Platte (siehe _iter_documents).
        #    Muss VOR search_fulltext laufen: das aktualisiert die files-Tabelle,
        #    gegen die der Volltext-Cache seine Frische-Prüfung macht.
        documents = self._iter_documents(master_folder)

        # OCR-Volltextsuche: bevorzugt über den Volltext-Cache des Index (EINE Abfrage
        # statt jede PDF zu öffnen; die erste Suche nach Änderungen indiziert nur die
        # neuen/veränderten Dokumente nach). Schlägt der Cache fehl oder ist der Index
        # abgeschaltet, bleibt fulltext_hits None -> Live-Lesen pro Dokument wie bisher.
        use_ocr = bool(getattr(self.app, 'use_ocr_var', None) and self.app.use_ocr_var.get())
        fulltext_hits = None  # Liste von Treffer-Mengen, eine je Begriff
        if search_text and use_ocr and self.app.config.get("use_index", True) and getattr(self.app, 'index_manager', None):
            try:
                fulltext_hits = [self.app.index_manager.search_fulltext(m) for m in term_matchers]
            except Exception as e:
                if hasattr(self.app, 'logger'):
                    self.app.logger.error(f"Volltext-Cache nicht verfügbar, nutze Live-OCR-Suche: {e}")

        # Ohne gespeichertes Datum zählt das aus dem Seitentext vermutete (auch für Von/Bis),
        # erst danach das Datei-Datum - gemerkt im Index, FALLSTRICKE #86
        with aktivitaet.phase("Suche: Dokumentdaten lesen…") as phase:
            vermutet = index_manager.vermutete_daten_sicher(
                self.app, [os.path.join(master_folder, d["rel_path"]) for d in documents if not d["kid_date"]],
                lambda n, gesamt: (phase.melde(f"Suche: Dokumentdaten lesen {n}/{gesamt}…"), aktivitaet.atme()))

        for doc in documents:
                entry_name = doc["name"]

                # Datumspriorität: 1. KID_DokumentenDatum -> 2. vermutetes Datum -> 3. Festplatten-Änderungsdatum
                kid_date_str = doc["kid_date"]
                display_date = None
                sort_date = None

                if not kid_date_str:
                    kid_date_str = vermutet.get(os.path.join(master_folder, doc["rel_path"]), "")
                if kid_date_str:
                    try:
                        # Erwartetes Format aus den Metadaten: YYYY-MM-DD
                        y, m, d = kid_date_str.split('-')
                        display_date = f"{d}.{m}.{y}"
                        sort_date = datetime.date(int(y), int(m), int(d))
                    except Exception:
                        pass

                # Fallback, falls kein gültiges KID_Datum gefunden wurde
                if not sort_date:
                    sort_date = datetime.date.fromtimestamp(doc["mtime"])
                    display_date = sort_date.strftime("%d.%m.%Y")

                # Datum abgleichen (Nutzt jetzt das echte Dokumentendatum!)
                if date_from and sort_date < date_from: continue
                if date_to and sort_date > date_to: continue

                titel = doc["title"] or entry_name
                raw_keywords = doc["keywords"]
                # Noch nie bearbeitet (orange): weder Titel noch Tags noch Datum gesetzt —
                # identische Definition wie in folder_manager.on_folder_select
                is_untouched = not doc["title"] and not raw_keywords and not doc["kid_date"]
                splitted_tags = [t.strip() for t in raw_keywords.replace(";", ",").split(",") if t.strip()]
                splitted_tags_lower = [t.lower() for t in splitted_tags]

                # Tags abgleichen
                if filter_tags:
                    if not all(ft in splitted_tags_lower for ft in filter_tags):
                        continue

                # Text abgleichen (mit * und ? als Wildcards, siehe build_matcher)
                if search_text:
                    # Dokument-ID mit im Ziel (25.10.2026): „K7M4“ findet über den Anfang, „K7M4Q2XP“
                    # ohne Bindestrich über die zusammengeklebten Wortpaare des Matchers
                    search_target = (f"{entry_name.lower()} {titel.lower()} {' '.join(splitted_tags_lower)} "
                                     f"{(doc.get('kid_id') or '').lower()}")

                    def begriff_trifft(i):
                        if term_matchers[i](search_target):
                            return True
                        # OCR-Volltextsuche zuschalten: aus dem Volltext-Cache (schnell),
                        # sonst Live-Lesen der PDF (Fallback, bisheriges Verhalten)
                        if not use_ocr:
                            return False
                        if fulltext_hits is not None:
                            return doc["rel_path"] in fulltext_hits[i]
                        self.app.root.update_idletasks()
                        abs_path = os.path.join(master_folder, doc["rel_path"])
                        return PDFHandler.contains_text(abs_path, terms[i], term_matchers[i])

                    if not all(begriff_trifft(i) for i in range(len(terms))):
                        continue

                for tag in splitted_tags:
                    global_tag_counts[tag] = global_tag_counts.get(tag, 0) + 1

                # Scan-Zeitpunkt (separate optionale Spalte, siehe scan_date.py) - unabhängig
                # vom KID_DokumentenDatum, betrifft wann die Datei gescannt statt worüber
                # das Dokument inhaltlich ist. creation_date/scan_zeit_embedded kommen
                # bereits aus dem Index bzw. der Live-Iteration mit, kein zusätzlicher
                # PDF-Zugriff nötig.
                scan_zeit = scan_date.format_scan_timestamp(
                    os.path.join(master_folder, doc["rel_path"]),
                    creation_date_raw=doc.get("creation_date", ""),
                    embedded=doc.get("scan_zeit_embedded", ""))

                if mails_aus and index_manager.ist_ausgeblendet(doc["rel_path"], doc.get("richtung")):
                    self.ausgeblendete_treffer += 1
                    continue

                # Wir geben jetzt unser formatiertes display_date (DD.MM.YYYY) in die Liste,
                # zusammen mit dem bereits bekannten Jahr (sort_date.year) für die Zeilenfarbe -
                # so muss es später nicht nochmal aus dem Text zurückgewonnen werden (siehe
                # FALLSTRICKE #18, dasselbe Problem gab es hier ursprünglich auch).
                file_data_list.append((display_date, titel, splitted_tags, entry_name, doc["rel_path"], sort_date.year, is_untouched, scan_zeit,
                                       scan_date.erfasst_anzeige(doc.get("erfasst", ""), scan_zeit)))

        # 2. Sortieren nach Datum (neueste zuerst)
        file_data_list.sort(key=lambda x: datetime.datetime.strptime(x[0], "%d.%m.%Y"), reverse=True)

        # 3. Für die GUI aufbereiten
        results = []
        for d_str, titel, splitted_tags, name, rel_path, jahr, is_untouched, scan_zeit, erfasst in file_data_list:
            if splitted_tags:
                splitted_tags.sort(key=lambda t: global_tag_counts.get(t, 0), reverse=True)
                sorted_tags_str = ", ".join(splitted_tags)
            else:
                sorted_tags_str = "---"
            results.append((d_str, titel, sorted_tags_str, name, rel_path, jahr, is_untouched, scan_zeit, erfasst))

        return results

    def is_local_result(self, rel_path):
        """
        Prüft, ob ein Suchergebnis 'lokal' ist (im aktuell links markierten Ordner oder
        darunter) — dann wird es in den Treffern stahlblau eingefärbt. Ohne markierten
        Unterordner (Master-Ordner selbst) gilt alles als lokal. Identische Logik wie in
        apply_filters, hier ausgelagert für die Live-Neufärbung nach dem Datum-Speichern.
        """
        selected_items = self.app.tree_folders.selection()
        if not selected_items:
            return True
        selected_folder_abs = self.app.tree_folders.item(selected_items[0], "values")[0]
        if selected_folder_abs == self.app.master_folder or app_paths.is_trash_path(selected_folder_abs, self.app.master_folder):
            return True
        selected_folder_rel = os.path.relpath(selected_folder_abs, self.app.master_folder)
        return rel_path.startswith(selected_folder_rel + os.sep) or os.path.dirname(rel_path) == selected_folder_rel

    def aktive_suchbegriffe(self):
        """
        Die Begriffe der angezeigten Suche (split_terms) für die Treffer-Markierung in der
        Vorschau - nicht des Feldinhalts: noch nicht mit Return abgeschickter Text markiert nichts.
        Leere Liste ohne angezeigte Suche.
        """
        text = self._angezeigt[0] if self._angezeigt else ""
        return self.split_terms(text) if isinstance(text, str) else []

    @staticmethod
    def anzeige_nach_suche(angezeigt_rel, treffer_rels, suchtext, ocr):
        """
        Was passiert nach einer Suche mit dem gerade angezeigten Dokument (Vorschau, Eigenschaften)?
        None = stehen lassen (es ist unter den Treffern), "" = leeren, sonst der Hinweistext für
        die leere Vorschau. Ohne das Leeren blieb ein Dokument sichtbar, das in der Trefferliste
        gar nicht mehr stand (Release-Check T0.18). Auch eine schon leere Anzeige wird geleert -
        sonst bliebe ein alter Hinweis stehen, wenn die nächste Suche (z.B. mit OCR) Treffer hat.
        """
        norm = lambda p: os.path.normcase(os.path.normpath(p))  # noqa: E731
        if angezeigt_rel and norm(angezeigt_rel) in {norm(t) for t in treffer_rels}:
            return None
        if not treffer_rels and suchtext.strip() and not ocr:
            return HINWEIS_OHNE_OCR
        return ""

    def is_search_active(self):
        """Zeigt die Dokumentenliste gerade Suchergebnisse? (Watchdog, Speichern, Verschieben und das
        Such-Schutzschild bauen dann die Treffer statt des Ordners neu auf.) Getippter, noch nicht mit
        Return abgeschickter Text zählt NICHT - siehe _angezeigt."""
        return self._angezeigt is not None

    def eingegebene_filter(self):
        """(Suchtext, Von, Bis, Filter-Tags) aus den Feldern - Platzhalter „TT.MM.JJJJ“ zählt als leer."""
        def feld(name):
            widget = getattr(self.app, name, None)
            wert = widget.get().strip() if widget is not None else ""
            return "" if wert == "TT.MM.JJJJ" else wert
        filter_tags = []
        if hasattr(self.app, 'tag_mode_var') and self.app.tag_mode_var.get() == "filter":
            for item in self.app.tree_tags.selection():
                tags = self.app.tree_tags.item(item, "tags")
                if "separator_tag" not in tags and "temp_tag" not in tags:
                    filter_tags.append(self.app.tree_tags.item(item, "text").lower())
        return feld('entry_search'), feld('entry_date_from'), feld('entry_date_to'), filter_tags

    def filter_eingegeben(self):
        """Steht in den Feldern eine Suche (Suchtext, Datumsbereich oder Filter-Tags)? Der Haken
        „Inhalt (OCR)“ allein ist KEINE Suche - er sagt nur, wie gesucht wird (FALLSTRICKE #74)."""
        return any(self.eingegebene_filter())

    def feld_geleert(self, event=None):
        """Loslassen einer Taste in Such- oder Datumsfeld: sucht NICHT (das macht Return, Peter
        01.11.2026 - sonst lief die Suche schon bei Pfeiltasten und beim Abtippen aus einem Dokument).
        Nur ein Feld, das in der angezeigten Suche gefüllt war und jetzt leer ist, setzt sofort neu auf."""
        if self._angezeigt is not None:
            aktuell = self.eingegebene_filter()
            if any(self._angezeigt[i] and not aktuell[i] for i in range(3)):
                self.apply_filters()
                return  # apply_filters färbt das Feld selbst
        self.faerbe_suchfeld()

    def faerbe_suchfeld(self):
        """Hintergrund des Suchfelds nach suchfeld_zustand: gelb = noch nicht gesucht, grün = gesucht."""
        feld = getattr(self.app, 'entry_search', None)
        if feld is None:
            return
        try:
            if not hasattr(self, '_suchfeld_grund'):
                self._suchfeld_grund = feld.cget("background")
            zustand = suchfeld_zustand(feld.get(), self._angezeigt[0] if self._angezeigt else None)
            farbe = {"ungesendet": SUCHFELD_UNGESENDET, "gesendet": SUCHFELD_GESENDET}.get(zustand,
                                                                                         self._suchfeld_grund)
            feld.configure(background=farbe)
        except tk.TclError:
            pass  # Fenster wird gerade geschlossen

    def trigger_search(self, event=None):
        """Sucht nach kurzer Pause - für Klicks (Haken „Inhalt (OCR)“, Filter-Tags, übernommener
        Tag-Vorschlag), damit mehrere Klicks kurz hintereinander nur EINE Suche auslösen. Tippen in
        Such- und Datumsfeldern sucht nicht mehr von selbst (feld_geleert, Return)."""
        if hasattr(self, '_search_timer'): 
            self.app.root.after_cancel(self._search_timer)
        self._search_timer = self.app.root.after(400, self.apply_filters)

    def reset_search(self):
        """Setzt alle Suchfelder und Filter zurück."""
        self.app.entry_search.delete(0, tk.END)
        
        self.app.entry_date_from.delete(0, tk.END)
        UIUtils.add_placeholder(self.app.entry_date_from, "TT.MM.JJJJ")
        
        self.app.entry_date_to.delete(0, tk.END)
        UIUtils.add_placeholder(self.app.entry_date_to, "TT.MM.JJJJ")
        
        if self.app.tag_mode_var.get() == "filter": 
            self.app.tree_tags.selection_remove(self.app.tree_tags.selection())
            
        self.apply_filters()

    def apply_filters(self):
        """Liest die UI aus, führt die Suche aus, färbt die Treffer und befüllt das Grid neu."""
        with aktivitaet.phase("Suche läuft…"):
            try:
                self._apply_filters()
            finally:
                self.faerbe_suchfeld()
        # Die Vorschau markiert die aktiven Suchbegriffe (11.09.2026): bleibt das angezeigte
        # Dokument stehen, folgen die Markierungen dem Suchtext - der Cache der Vorschau
        # rendert nur neu, wenn sich die Begriffe wirklich geändert haben.
        pm = getattr(self.app, 'preview_manager', None)
        if pm is not None and getattr(self.app, 'current_preview_path', None):
            pm.update_preview()

    def _apply_filters(self):
        search_text = self.app.entry_search.get()
        date_from_str = self.app.entry_date_from.get()
        date_to_str = self.app.entry_date_to.get()
        st, df, dt, filter_tags = self.eingegebene_filter()

        # Prüfen, ob überhaupt ein Filter aktiv ist - und ab jetzt als angezeigte Suche merken
        is_searching = bool(st or df or dt or filter_tags)
        self._angezeigt = (st, df, dt, tuple(filter_tags)) if is_searching else None
        self._zeige_trefferzahl(None)

        # Aktuelle Dokumentenauswahl merken, um sie über den Grid-Neuaufbau zu erhalten.
        # Sonst deselektiert jeder Neuaufbau (Tippen, Watchdog nach Auto-Save, ...) das
        # gerade angesehene Dokument - genau das ließ die Markierung "verschwinden".
        prev_selected_paths = {self.app.tree_files.item(i, "values")[4] for i in self.app.tree_files.selection()}

        if not is_searching:
            for row in self.app.tree_files.get_children():
                self.app.tree_files.delete(row)
            if self.app.tree_folders.selection():
                # Ein übrig gebliebenes Such-Schutzschild (FALLSTRICKE #14; gui.on_file_select
                # setzt es bei JEDEM Klick auf einen Treffer) darf diesen ausdrücklichen
                # Neuaufbau nicht schlucken - sonst bleibt die Liste nach „Reset" leer,
                # wenn der Treffer im schon markierten Ordner lag (FALLSTRICKE #70).
                self.app.folder_manager.ignore_next_select = False
                self.app.folder_manager.on_folder_select(None)
            else:
                # Kein Ordner markiert (z.B. direkt nach dem Start gesucht): die Liste bleibt
                # leer - dann darf auch kein Dokument mehr angezeigt werden (Peter 25.10.2026)
                self.app.leere_dokumentanzeige()
            return
            
        if not self.app.master_folder: 
            return
            
        # Eigentliche Suche ausführen
        results = self.execute_search(self.app.master_folder, search_text, date_from_str, date_to_str, filter_tags)
        self._zeige_trefferzahl(len(results))

        # --- NEU: Ermittle den aktuell links markierten Ordner ---
        selected_folder_rel = ""
        selected_items = self.app.tree_folders.selection()
        if selected_items:
            selected_folder_abs = self.app.tree_folders.item(selected_items[0], "values")[0]
            # Wenn nicht der Master-Ordner markiert ist, bilden wir den relativen Pfad
            if selected_folder_abs != self.app.master_folder and not app_paths.is_trash_path(selected_folder_abs, self.app.master_folder):
                selected_folder_rel = os.path.relpath(selected_folder_abs, self.app.master_folder)
        
        # Zeilen erst unsichtbar zusammenstellen, dann mit der angezeigten Liste vergleichen: sind sie
        # gleich, bleibt die Liste samt Markierung und Scrollposition stehen. Sonst flackerte jede
        # wiederholte Suche (Watchdog nach Auto-Save, Tipp-Timer nach Return) sichtbar (Peter 01.11.2026)
        zeilen = self._trefferzeilen(results, selected_folder_rel)
        if zeilen == self._angezeigte_zeilen():
            return

        # Standard-Sortierung der Suchergebnisse ist Datum absteigend — Spaltenkopf-Anzeige angleichen
        UIUtils.set_sort_indicator(self.app.tree_files, "datum", True)

        for row in self.app.tree_files.get_children():
            self.app.tree_files.delete(row)
        for werte, tags in zeilen:
            self.app.tree_files.insert("", "end", values=werte, tags=tags)

        # Vorherige Dokumentenauswahl wiederherstellen (falls die Treffer sie noch enthalten),
        # damit ein Neuaufbau das aktuell angesehene Dokument nicht aus der Auswahl wirft.
        if prev_selected_paths:
            wieder = [i for i in self.app.tree_files.get_children()
                      if self.app.tree_files.item(i, "values")[4] in prev_selected_paths]
            if wieder:
                self.app.tree_files.selection_set(wieder)

        # Liste und Anzeige müssen zusammenpassen: ein Dokument, das nicht unter den Treffern
        # ist, verschwindet aus Vorschau und Eigenschaften (wie bei einem leeren Ordner).
        angezeigt = getattr(self.app, 'current_preview_path', None)
        angezeigt_rel = os.path.relpath(angezeigt, self.app.master_folder) if angezeigt else ""
        use_ocr = bool(getattr(self.app, 'use_ocr_var', None) and self.app.use_ocr_var.get())
        hinweis = self.anzeige_nach_suche(angezeigt_rel, [r[4] for r in results], search_text, use_ocr)
        if hinweis is not None:
            self.app.leere_dokumentanzeige(hinweis)

    def _zeige_trefferzahl(self, anzahl):
        """Trefferzahl neben der Suchleiste (Peter 05.11.2026); None = keine Suche, die Anzeige bleibt leer."""
        anzeige = getattr(self.app, 'lbl_treffer', None)
        if anzeige is not None:
            text = "" if anzahl is None else f"{anzahl} Treffer"
            verborgen = getattr(self, "ausgeblendete_treffer", 0)
            if anzahl is not None and verborgen:      # Sonst wirkt eine gesuchte Mail wie verloren
                text += f" (+{verborgen} {'Mail' if verborgen == 1 else 'Mails'} ausgeblendet)"
            # Nur dieser längere Text darf die feste Breite sprengen, die Leiste springt nur bei ausgeblendeten Treffern
            anzeige.config(width=max(TREFFER_BREITE, len(text)))
            anzeige.config(text=text)

    def _angezeigte_zeilen(self):
        """Die Zeilen der Dokumentenliste im Format von _trefferzeilen (Werte als Text, Tags als Tupel) -
        Tk liefert Zahlen-Texte gern als int und ein einzelnes Tag als nackten String zurück."""
        zeilen = []
        for i in self.app.tree_files.get_children():
            tags = self.app.tree_files.item(i, "tags")
            if isinstance(tags, str):
                tags = (tags,) if tags else ()
            zeilen.append((tuple(str(w) for w in self.app.tree_files.item(i, "values")), tuple(tags)))
        return zeilen

    def _trefferzeilen(self, results, selected_folder_rel):
        """Zeilen (Werte, Tags) der Trefferliste für execute_search-Ergebnisse - ohne die Liste anzufassen."""
        zeilen = []
        for row_data in results:
            tags = []
            rel_path = row_data[4]
            jahr = row_data[5]
            is_untouched = row_data[6]

            # --- Hintergrundfarbe nach Jahres-Parität (konsistent mit folder_manager.py) ---
            tags.append("row_even" if jahr % 2 == 0 else "row_odd")
            # Orange Kennzeichnung noch unbearbeiteter Dokumente - wie in der Ordneransicht
            if is_untouched:
                tags.append("untouched")
            # ----------------------------------------

            if app_paths.is_trash_path(rel_path, self.app.master_folder):
                tags.append("trash_file")
            else:
                # (Hier folgt deine restliche search_local Logik)
                
                # --- NEU: Farb-Prüfung ---
                is_local = False
                
                if not selected_folder_rel:
                    is_local = True  # Im Master-Hauptordner ist logischerweise alles "lokal"
                else:
                    # Prüft ob die Datei exakt im Ordner oder einem Unterordner liegt.
                    # os.sep sorgt dafür, dass Ordner wie "2026" und "2026_Archiv" nicht fälschlich vermischt werden.
                    if rel_path.startswith(selected_folder_rel + os.sep) or os.path.dirname(rel_path) == selected_folder_rel:
                        is_local = True
                
                # Steelblue nur, wenn nicht schon orange (unberührt) - sonst würden sich
                # die beiden Schriftfarben überlagern; "unberührt" hat Vorrang.
                if is_local and not is_untouched:
                    tags.append("search_local")
                # Suchergebnisse außerhalb bekommen kein spezielles Tag und bleiben schwarz (bzw. im Standard-Theme)
                    
            # Überordner-Spalte: direkter Elternordner der Datei, im Root der Master-Ordnername
            parent_dir = os.path.dirname(rel_path)
            ordner = os.path.basename(parent_dir) if parent_dir else os.path.basename(self.app.master_folder)

            # Textqualität bleibt in Suchergebnissen leer - sie würde für jeden Treffer der ganzen
            # Sammlung einen PDF-Zugriff kosten
            werte = tuple(str(w) for w in row_data[:5] + (ordner, row_data[7], "", row_data[8]))
            zeilen.append((werte, tuple(tags)))
        return zeilen