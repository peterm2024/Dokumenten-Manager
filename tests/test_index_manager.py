import os
import shutil
import tempfile
import threading
import unittest
from collections import Counter
from unittest.mock import MagicMock, patch

import index_manager
from index_manager import IndexManager


class TestIndexManager(unittest.TestCase):
    """Tests für den Suchindex: Frische-Prüfung, Lazy-Nachindizierung, Entfernen verschwundener Dateien."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.master = os.path.join(self.tmp, "KID")
        os.makedirs(self.master)

        self.mock_app = MagicMock()
        self.mock_app.master_folder = self.master
        # Verhält sich wie das echte Config.get(key, default) - liefert den übergebenen
        # Default zurück statt eines undefinierten MagicMock-Objekts. Wichtig, weil
        # _ensure_fulltext_baseline seit der automatischen Erweitert-Anwendung
        # config.get("index_text_mode", "standard") abfragt - ohne dieses Mock würde
        # JEDER bestehende Test (auch für Standard/Fortgeschritten/Meister) plötzlich
        # ungewollt die automatische Korrektur mit auslösen.
        self.mock_app.config.get.side_effect = lambda key, default=None: default
        self.manager = IndexManager(self.mock_app)

        # Zwei Fake-PDFs anlegen (Inhalt egal, get_metadata wird gemockt)
        self._schreibe_pdf("a.pdf", "Inhalt A")
        os.makedirs(os.path.join(self.master, "Ordner"))
        self._schreibe_pdf(os.path.join("Ordner", "b.pdf"), "Inhalt B")

    def tearDown(self):
        self.manager.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _volltext_einlesen(self):
        """Dateiliste und Volltext-Cache mit der Platte abgleichen (eigene Verbindung, wie die Lese-Funktionen)."""
        import app_paths
        con = self.manager._open_connection(app_paths.index_path(self.master))
        try:
            self.manager._abgleich(con, os.path.abspath(self.master))
            self.manager._ensure_fulltext_baseline(con, os.path.abspath(self.master))
        finally:
            con.close()

    def _schreibe_pdf(self, rel, inhalt):
        with open(os.path.join(self.master, rel), "w") as f:
            f.write(inhalt)

    @patch("index_manager.PDFHandler.get_metadata")
    def test_erstaufbau_liest_jede_pdf_genau_einmal(self, mock_meta):
        mock_meta.return_value = {"title": "T", "keywords": "K", "KID_DokumentenDatum": "2026-01-01"}

        docs = self.manager.iter_documents()

        self.assertEqual(len(docs), 2)
        self.assertEqual(mock_meta.call_count, 2)
        self.assertEqual({d["name"] for d in docs}, {"a.pdf", "b.pdf"})
        self.assertEqual(docs[0]["title"], "T")

    @patch("index_manager.PDFHandler.get_metadata")
    def test_zweiter_lauf_oeffnet_keine_pdf(self, mock_meta):
        """Der Kern des Konzepts: Bei unveränderten Dateien wird KEINE PDF mehr geöffnet."""
        mock_meta.return_value = {"title": "T", "keywords": "", "KID_DokumentenDatum": ""}
        self.manager.iter_documents()
        mock_meta.reset_mock()

        docs = self.manager.iter_documents()

        self.assertEqual(len(docs), 2)
        mock_meta.assert_not_called()

    @patch("index_manager.PDFHandler.get_metadata")
    def test_geaenderte_datei_wird_nachindiziert(self, mock_meta):
        mock_meta.return_value = {"title": "Alt", "keywords": "", "KID_DokumentenDatum": ""}
        self.manager.iter_documents()

        # Datei verändern (anderer Inhalt -> andere Größe, neue mtime)
        self._schreibe_pdf("a.pdf", "Neuer, längerer Inhalt")
        mock_meta.reset_mock()
        mock_meta.return_value = {"title": "Neu", "keywords": "", "KID_DokumentenDatum": ""}

        docs = self.manager.iter_documents()

        self.assertEqual(mock_meta.call_count, 1)  # NUR die geänderte Datei
        titel = {d["name"]: d["title"] for d in docs}
        self.assertEqual(titel["a.pdf"], "Neu")
        self.assertEqual(titel["b.pdf"], "Alt")  # aus dem Index, unangetastet

    @patch("index_manager.PDFHandler.get_metadata")
    def test_geloeschte_datei_verschwindet_aus_dem_index(self, mock_meta):
        mock_meta.return_value = {"title": "T", "keywords": "", "KID_DokumentenDatum": ""}
        self.manager.iter_documents()

        os.remove(os.path.join(self.master, "a.pdf"))
        docs = self.manager.iter_documents()

        self.assertEqual({d["name"] for d in docs}, {"b.pdf"})
        # Auch in der Datenbank selbst ist der Eintrag weg
        con = self.manager._connect()
        rows = list(con.execute("SELECT rel_path FROM files"))
        self.assertEqual(len(rows), 1)

    @patch("index_manager.PDFHandler.get_metadata")
    def test_rebuild_verwirft_und_baut_neu(self, mock_meta):
        mock_meta.return_value = {"title": "T", "keywords": "", "KID_DokumentenDatum": ""}
        self.manager.iter_documents()
        mock_meta.reset_mock()

        anzahl = self.manager.rebuild()

        self.assertEqual(anzahl, 2)
        self.assertEqual(mock_meta.call_count, 2)  # alles neu gelesen

    def test_ohne_hauptordner_fliegt_exception(self):
        """Ohne gültigen Hauptordner muss iter_documents scheitern, damit der Aufrufer auf die Live-Suche zurückfällt."""
        self.mock_app.master_folder = ""
        with self.assertRaises(RuntimeError):
            self.manager.iter_documents()

    @patch("index_manager.PDFHandler.get_metadata")
    def test_indexdatei_liegt_im_daten_ordner(self, mock_meta):
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        self.manager.iter_documents()
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "KID-Daten", "index.sqlite")))

    @patch("index_manager.PDFHandler.get_metadata")
    def test_dokument_id_wird_durchgereicht(self, mock_meta):
        mock_meta.return_value = {"title": "T", "keywords": "", "KID_DokumentenDatum": "", "KID_ID": "K7M4-Q2XP"}
        self.assertTrue(all(d["kid_id"] == "K7M4-Q2XP" for d in self.manager.iter_documents()))
        mock_meta.reset_mock()
        self.assertTrue(all(d["kid_id"] == "K7M4-Q2XP" for d in self.manager.iter_documents()))
        mock_meta.assert_not_called()                     # aus dem Index, ohne PDF zu öffnen

    @patch("index_manager.PDFHandler.get_metadata")
    def test_absender_fuers_ablage_gedaechtnis(self, mock_meta):
        mock_meta.side_effect = lambda pfad: {"title": "", "keywords": "", "KID_DokumentenDatum": "", "KID_ID": "X",
                                              "KID_Absender": "Gentilia" if pfad.endswith("b.pdf") else ""}
        self.assertEqual(self.manager.ablage_absender(), [(os.path.join("Ordner", "b.pdf"), "Gentilia")])
        mock_meta.reset_mock()
        docs = self.manager.iter_documents()                  # derselbe Index, ohne PDF zu öffnen
        mock_meta.assert_not_called()
        self.assertEqual({d["name"]: d["absender"] for d in docs}, {"a.pdf": "", "b.pdf": "Gentilia"})

    @patch("index_manager.PDFHandler.get_fulltext", side_effect=lambda pfad: "Text " + os.path.basename(pfad))
    @patch("index_manager.PDFHandler.get_metadata")
    def test_wiki_text(self, mock_meta, _text):
        mock_meta.side_effect = lambda pfad: {"title": "T", "keywords": "", "KID_DokumentenDatum": "2025-01-15",
                                              "KID_ID": "AAAA-BBBB" if pfad.endswith("a.pdf") else ""}
        # Noch nie gesucht, der Cache ist leer: Das Dokument wird trotzdem gelesen (Peter 13.11.2026: ein frisch
        # abgelegtes Dokument galt im Wiki als „ohne erkannten Text“)
        self.assertEqual(self.manager.wiki_text(os.path.join("Ordner", "b.pdf"))[0], "Text b.pdf")
        self.assertEqual(self.manager.wiki_text("a.pdf"), ("Text a.pdf", "Text a.pdf"))
        self.assertEqual(self.manager.wiki_text("fehlt.pdf"), ("", ""))

    @patch("index_manager.PDFHandler.get_fulltext", return_value="")
    @patch("index_manager.PDFHandler.get_metadata", return_value={"title": "", "keywords": "", "KID_DokumentenDatum": ""})
    def test_wiki_text_ohne_textebene_nimmt_ocr(self, _meta, _text):
        """Scan: Kenntext ist der OCR-Text; der korrigierte Text (text_erweitert) geht nicht mit an die KI."""
        self._volltext_einlesen()
        con = self.manager._connect()
        with con:
            con.execute("UPDATE fulltext SET text_ocr = 'OCR a', text_erweitert = 'korrigiert' WHERE rel_path = 'a.pdf'")
        self.assertEqual(self.manager.wiki_text("a.pdf"), ("OCR a", "OCR a"))

    @patch("index_manager.PDFHandler.get_metadata")
    def test_mail_verwandte_finden_sich_ueber_ordner_hinweg(self, mock_meta):
        # Peter 05.11.2026: Mail und Anhang liegen oft in verschiedenen Ordnern, nur KID_MAILID verbindet sie
        mock_meta.return_value = {"title": "T", "keywords": "", "KID_DokumentenDatum": "", "KID_ID": "",
                                  "KID_Absender": "", "KID_MailID": "mid:1@x"}
        self.manager.iter_documents()
        b = os.path.join("Ordner", "b.pdf")
        self.assertEqual(self.manager.mail_verwandte("mid:1@x", "a.pdf"), [b])
        self.assertEqual(self.manager.mail_verwandte("mid:1@x", b), ["a.pdf"])
        self.assertEqual(self.manager.mail_verwandte("mid:anders@x", "a.pdf"), [])
        self.assertEqual(self.manager.mail_verwandte("", "a.pdf"), [])

    @patch("index_manager.PDFHandler.get_metadata")
    def test_mail_verwandte_gleichen_nur_bei_veraltetem_index_ab(self, mock_meta):
        mock_meta.return_value = {"title": "T", "keywords": "", "KID_DokumentenDatum": "", "KID_ID": "",
                                  "KID_Absender": "", "KID_MailID": "mid:1@x"}
        self.manager.iter_documents()
        with patch.object(self.manager, "_abgleich", wraps=self.manager._abgleich) as abgleich:
            self.manager.mail_verwandte("mid:1@x", "a.pdf")
            abgleich.assert_not_called()                    # frisch: kein Lauf durch die ganze Sammlung
            # Die Vollautomatik hat den Anhang verschoben und umbenannt
            neu = os.path.join("Ordner", "umbenannt.pdf")
            os.replace(os.path.join(self.master, "Ordner", "b.pdf"), os.path.join(self.master, neu))
            self.assertEqual(self.manager.mail_verwandte("mid:1@x", "a.pdf"), [neu])
            abgleich.assert_called_once()
            # Im Papierkorb außerhalb der Sammlung ist das Dokument nie im Index, das darf nicht jedes Mal abgleichen
            abgleich.reset_mock()
            self.assertEqual(self.manager.mail_verwandte("mid:1@x", os.path.join("..", "Papierkorb", "c.pdf")),
                             sorted(["a.pdf", neu]))
            abgleich.assert_not_called()

    @patch("index_manager.PDFHandler.get_metadata")
    def test_alter_index_ohne_mail_id_liest_einmal_nach(self, mock_meta):
        mock_meta.return_value = {"title": "T", "keywords": "", "KID_DokumentenDatum": "", "KID_ID": "X",
                                  "KID_Absender": "", "KID_MailID": ""}
        self.manager.iter_documents()
        con = self.manager._connect()
        with con:
            con.execute("UPDATE files SET mail_id = NULL")
        mock_meta.reset_mock()
        self.manager.iter_documents()
        self.assertEqual(mock_meta.call_count, 2)
        mock_meta.reset_mock()
        self.manager.iter_documents()
        mock_meta.assert_not_called()

    @patch("index_manager.PDFHandler.get_metadata")
    def test_alter_index_ohne_absender_liest_einmal_nach(self, mock_meta):
        mock_meta.return_value = {"title": "T", "keywords": "", "KID_DokumentenDatum": "", "KID_ID": "X",
                                  "KID_Absender": "ADAC"}
        self.manager.iter_documents()
        con = self.manager._connect()
        with con:
            con.execute("UPDATE files SET absender = NULL")
        mock_meta.reset_mock()
        self.assertEqual(len(self.manager.ablage_absender()), 2)
        self.assertEqual(mock_meta.call_count, 2)

    @patch("index_manager.PDFHandler.get_metadata")
    def test_alter_index_ohne_id_liest_einmal_nach(self, mock_meta):
        # Index aus der Zeit vor der ID-Spalte: Zeilen haben kid_id NULL -> genau EIN Nachlesen
        mock_meta.return_value = {"title": "T", "keywords": "", "KID_DokumentenDatum": "", "KID_ID": "K7M4-Q2XP"}
        self.manager.iter_documents()
        con = self.manager._connect()
        with con:
            con.execute("UPDATE files SET kid_id = NULL")
        mock_meta.reset_mock()
        docs = self.manager.iter_documents()
        self.assertEqual(mock_meta.call_count, 2)
        self.assertTrue(all(d["kid_id"] == "K7M4-Q2XP" for d in docs))
        mock_meta.reset_mock()
        self.manager.iter_documents()
        mock_meta.assert_not_called()

    @patch("index_manager.PDFHandler.get_metadata")
    def test_creation_date_und_scan_zeit_werden_durchgereicht(self, mock_meta):
        mock_meta.return_value = {
            "title": "T", "keywords": "", "KID_DokumentenDatum": "",
            "creationDate": "D:20220505185907+01'00'", "KID_ScanZeitpunkt": "",
        }
        docs = self.manager.iter_documents()
        self.assertTrue(all(d["creation_date"] == "D:20220505185907+01'00'" for d in docs))

    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_fulltext_erstaufbau_und_treffer(self, mock_meta, mock_text):
        """Volltext-Cache: Erstaufbau liest jede PDF genau einmal, Matcher findet die richtigen Dokumente."""
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.side_effect = lambda path: "Rechnung Stadtwerke" if path.endswith("a.pdf") else "Kuendigung Vertrag"
        self.manager.iter_documents()  # files-Tabelle befüllen (Voraussetzung)

        hits = self.manager.search_fulltext(lambda text: "stadtwerke" in text)

        self.assertEqual(hits, {"a.pdf"})
        self.assertEqual(mock_text.call_count, 2)

    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_fulltext_zweiter_lauf_oeffnet_keine_pdf(self, mock_meta, mock_text):
        """Frische-Prüfung: bei unveränderten Dateien wird für die Volltextsuche KEINE PDF mehr geöffnet."""
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Inhalt"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)
        mock_text.reset_mock()

        hits = self.manager.search_fulltext(lambda text: "inhalt" in text)

        mock_text.assert_not_called()
        self.assertEqual(hits, {"a.pdf", os.path.join("Ordner", "b.pdf")})

    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_fulltext_geaenderte_datei_wird_nachgelesen(self, mock_meta, mock_text):
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Alter Text"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)

        self._schreibe_pdf("a.pdf", "Neuer, laengerer Inhalt")
        self.manager.iter_documents()  # files-Tabelle auffrischen (wie in execute_search)
        mock_text.reset_mock()
        mock_text.return_value = "Neuer Text"

        hits = self.manager.search_fulltext(lambda text: "neuer" in text)

        self.assertEqual(mock_text.call_count, 1)  # NUR die geänderte Datei
        self.assertEqual(hits, {"a.pdf"})

    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_fulltext_geloeschte_datei_verschwindet(self, mock_meta, mock_text):
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Inhalt"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)

        os.remove(os.path.join(self.master, "a.pdf"))
        self.manager.iter_documents()

        hits = self.manager.search_fulltext(lambda text: True)
        self.assertEqual(hits, {os.path.join("Ordner", "b.pdf")})

    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_rebuild_leert_auch_den_volltext_cache(self, mock_meta, mock_text):
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Inhalt"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)

        self.manager.rebuild()

        con = self.manager._connect()
        self.assertEqual(list(con.execute("SELECT COUNT(*) FROM fulltext"))[0][0], 0)

    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_ocr_tier_nutzt_keine_geteilte_verbindung(self, mock_meta, mock_text, mock_ocr):
        """
        Regressionstest: upgrade_to_ocr_tier darf self._con nicht anfassen. Die Methode
        läuft in einem Hintergrund-Thread (siehe tools/settings_editor.py) - eine
        geteilte, dort erstmals gebundene Connection hätte spätere Haupt-Thread-Zugriffe
        (search_fulltext) mit einer ProgrammingError scheitern lassen, die dort abgefangen
        wird und still auf die Live-Suche zurückfällt (sichtbarer Bug: "Cache hat den
        Text, Suche findet ihn trotzdem nicht", ohne Fehlermeldung).
        """
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Text"
        mock_ocr.return_value = "OCR"

        self.manager.upgrade_to_ocr_tier("pfad")

        self.assertIsNone(self.manager._con)

    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_ocr_tier_aus_echtem_hintergrund_thread(self, mock_meta, mock_ocr):
        """
        Reproduziert den echten Bug end-to-end: search_fulltext bindet self._con zuerst
        an den Test-("Haupt")-Thread, DANACH läuft upgrade_to_ocr_tier in einem echten
        threading.Thread (wie im echten Einstellungen-Fluss) - die anschließende Suche im
        ursprünglichen Thread muss den frisch ergänzten OCR-Text trotzdem finden.
        """
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        with patch("index_manager.PDFHandler.get_fulltext", return_value="Kauderwelsch"):
            self.manager.iter_documents()
            self.manager.search_fulltext(lambda text: False)  # self._con jetzt an DIESEN Thread gebunden

        mock_ocr.return_value = "Stadtwerke Rechnung"
        thread = threading.Thread(target=self.manager.upgrade_to_ocr_tier, args=("pfad",))
        thread.start()
        thread.join()

        hits = self.manager.search_fulltext(lambda text: "stadtwerke" in text)
        self.assertEqual(hits, {"a.pdf", os.path.join("Ordner", "b.pdf")})

    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_ocr_tier_ergaenzt_text_ocr_ohne_original_zu_verlieren(self, mock_meta, mock_text, mock_ocr):
        """"Ergänzen statt ersetzen": text_ocr kommt dazu, der Original-Text (text) bleibt unangetastet."""
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Originaltext (evtl. Kauderwelsch)"
        mock_ocr.return_value = "Neu gelesener OCR-Text"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)  # Standard-Cache befuellen

        done = self.manager.upgrade_to_ocr_tier("irgendein/tessdata/pfad")

        self.assertEqual(done, 2)
        self.assertEqual(mock_ocr.call_count, 2)
        rows = {r[0]: r for r in self.manager._connect().execute(
            "SELECT rel_path, text, text_ocr, tier FROM fulltext")}
        for rel_path, (_, text, text_ocr, tier) in rows.items():
            self.assertEqual(text, "Originaltext (evtl. Kauderwelsch)")
            self.assertEqual(text_ocr, "Neu gelesener OCR-Text")
            self.assertEqual(tier, "fortgeschritten")

    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_ocr_tier_ueberspringt_bereits_hochgestufte(self, mock_meta, mock_text, mock_ocr):
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Text"
        mock_ocr.return_value = "OCR"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)
        self.manager.upgrade_to_ocr_tier("pfad")
        mock_ocr.reset_mock()

        done = self.manager.upgrade_to_ocr_tier("pfad")

        self.assertEqual(done, 0)
        mock_ocr.assert_not_called()

    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_ocr_tier_respektiert_should_stop(self, mock_meta, mock_text, mock_ocr):
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Text"
        mock_ocr.return_value = "OCR"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)

        done = self.manager.upgrade_to_ocr_tier("pfad", should_stop=lambda: True)

        self.assertEqual(done, 0)  # bricht VOR dem ersten Dokument ab
        mock_ocr.assert_not_called()

    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_ocr_tier_ruft_progress_callback(self, mock_meta, mock_text, mock_ocr):
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Text"
        mock_ocr.return_value = "OCR"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)

        calls = []
        self.manager.upgrade_to_ocr_tier("pfad", on_progress=lambda d, t: calls.append((d, t)))

        self.assertEqual(calls, [(1, 2), (2, 2)])

    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    def test_search_fulltext_matched_auch_ueber_text_ocr(self, mock_ocr):
        """Ein Treffer, der nur im Re-OCR-Text steckt (nicht im Original), muss trotzdem gefunden werden."""
        mock_ocr.return_value = "Stadtwerke Rechnung"
        with patch("index_manager.PDFHandler.get_metadata",
                   return_value={"title": "", "keywords": "", "KID_DokumentenDatum": ""}), \
             patch("index_manager.PDFHandler.get_fulltext", return_value="Kauderwelsch ohne Treffer"):
            self.manager.iter_documents()
            self.manager.search_fulltext(lambda text: False)
            self.manager.upgrade_to_ocr_tier("pfad")

        hits = self.manager.search_fulltext(lambda text: "stadtwerke" in text)
        self.assertEqual(hits, {"a.pdf", os.path.join("Ordner", "b.pdf")})

    # ==========================================
    # ERWEITERT-STUFE (lokale, KI-freie Korrektur des bestehenden Texts, ohne Re-OCR)
    # ==========================================
    @patch("index_manager.spell_correct.suggest_corrected_text")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_erweitert_tier_ergaenzt_text_erweitert_ohne_original_zu_verlieren(self, mock_meta, mock_text, mock_correct):
        """"Ergänzen statt ersetzen": text_erweitert kommt dazu, der Original-Text (text) bleibt unangetastet - und es wird KEIN Bild-OCR aufgerufen."""
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Originaltext (evtl. Kauderwelsch)"
        mock_correct.return_value = "Lokal korrigierter Text"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)

        done = self.manager.upgrade_to_erweitert_tier()

        self.assertEqual(done, 2)
        self.assertEqual(mock_correct.call_count, 2)
        rows = {r[0]: r for r in self.manager._connect().execute(
            "SELECT rel_path, text, text_erweitert, tier FROM fulltext")}
        for rel_path, (_, text, text_erweitert, tier) in rows.items():
            self.assertEqual(text, "Originaltext (evtl. Kauderwelsch)")
            self.assertEqual(text_erweitert, "Lokal korrigierter Text")
            self.assertEqual(tier, "erweitert")

    @patch("index_manager.spell_correct.suggest_corrected_text")
    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_erweitert_tier_ueberspringt_bereits_hoeher_hochgestufte(self, mock_meta, mock_text, mock_ocr, mock_correct):
        """Dokumente mit bereits gleichwertiger/besserer Textquelle (hier: schon re-OCR't) werden nicht nochmal per Erweitert angefasst."""
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Text"
        mock_ocr.return_value = "OCR"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)
        self.manager.upgrade_to_ocr_tier("pfad")  # a.pdf/b.pdf sind jetzt 'fortgeschritten'

        done = self.manager.upgrade_to_erweitert_tier()

        self.assertEqual(done, 0)
        mock_correct.assert_not_called()

    @patch("index_manager.spell_correct.suggest_corrected_text")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_erweitert_tier_ueberspringt_bereits_erweiterte(self, mock_meta, mock_text, mock_correct):
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Text"
        mock_correct.return_value = "Korrigiert"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)
        self.manager.upgrade_to_erweitert_tier()
        mock_correct.reset_mock()

        done = self.manager.upgrade_to_erweitert_tier()

        self.assertEqual(done, 0)
        mock_correct.assert_not_called()

    @patch("index_manager.spell_correct.suggest_corrected_text")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_erweitert_tier_respektiert_should_stop(self, mock_meta, mock_text, mock_correct):
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Text"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)

        done = self.manager.upgrade_to_erweitert_tier(should_stop=lambda: True)

        self.assertEqual(done, 0)  # bricht VOR dem ersten Dokument ab
        mock_correct.assert_not_called()

    @patch("index_manager.spell_correct.suggest_corrected_text")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_erweitert_tier_ruft_progress_callback(self, mock_meta, mock_text, mock_correct):
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Text"
        mock_correct.return_value = "Korrigiert"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)

        calls = []
        self.manager.upgrade_to_erweitert_tier(on_progress=lambda d, t: calls.append((d, t)))

        self.assertEqual(calls, [(1, 2), (2, 2)])

    @patch("index_manager.spell_correct.suggest_corrected_text")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_erweitert_tier_baut_wortschatz_aus_gesamtem_cache(self, mock_meta, mock_text, mock_correct):
        """Der Wortschatz wird aus text/text_ocr/text_ai ALLER Zeilen gebaut, nicht nur der gerade zu korrigierenden - suggest_corrected_text bekommt daher dasselbe Vokabular für beide Dokumente übergeben."""
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.side_effect = lambda path: "Text A" if path.endswith("a.pdf") else "Text B"
        mock_correct.return_value = "Korrigiert"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)

        self.manager.upgrade_to_erweitert_tier()

        vocab_a = mock_correct.call_args_list[0].args[1]
        vocab_b = mock_correct.call_args_list[1].args[1]
        self.assertEqual(vocab_a, vocab_b)
        self.assertIn("text", vocab_a)  # aus "Text A" UND "Text B" gemeinsam gebaut

    @patch("index_manager.spell_correct.suggest_corrected_text")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_search_fulltext_matched_auch_ueber_text_erweitert(self, mock_meta, mock_text, mock_correct):
        """Ein Treffer, der nur im lokal korrigierten Text steckt (nicht im Original), muss trotzdem gefunden werden."""
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Kauderwelsch ohne Treffer"
        mock_correct.return_value = "Stadtwerke Rechnung"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)
        self.manager.upgrade_to_erweitert_tier()

        hits = self.manager.search_fulltext(lambda text: "stadtwerke" in text)
        self.assertEqual(hits, {"a.pdf", os.path.join("Ordner", "b.pdf")})

    @patch("index_manager.spell_correct.suggest_corrected_text")
    def test_upgrade_to_erweitert_tier_nutzt_keine_geteilte_verbindung(self, mock_correct):
        """
        Regressionstest wie bei upgrade_to_ocr_tier: läuft in einem Hintergrund-Thread,
        darf self._con nicht anfassen.
        """
        import sqlite3
        import app_paths
        mock_correct.return_value = "Korrigiert"

        path = app_paths.index_path(self.master)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        con = sqlite3.connect(path)
        con.execute(IndexManager.SCHEMA)
        con.execute(IndexManager.SCHEMA_FULLTEXT)
        for rel_path in ("a.pdf", os.path.join("Ordner", "b.pdf")):
            con.execute("INSERT INTO files (rel_path, mtime, size) VALUES (?, 1.0, 1)", (rel_path,))
            con.execute(
                "INSERT INTO fulltext (rel_path, mtime, size, text, tier) "
                "VALUES (?, 1.0, 1, 'Originaltext', 'standard')", (rel_path,))
        con.commit()
        con.close()

        self.manager.upgrade_to_erweitert_tier()

        self.assertIsNone(self.manager._con)

    # ==========================================
    # PERSISTENTER WORTSCHATZ + AUTOMATISCHE ANWENDUNG BEIM SCANNEN
    # ==========================================
    def test_persist_vocabulary_delta_addiert_zu_bestehender_haeufigkeit(self):
        con = self.manager._connect()
        self.manager._persist_vocabulary_delta(con, Counter({"kunde": 2, "rechnung": 1}))
        self.manager._persist_vocabulary_delta(con, Counter({"kunde": 3}))

        vocab = self.manager._load_vocabulary(con)

        self.assertEqual(vocab["kunde"], 5)
        self.assertEqual(vocab["rechnung"], 1)

    def test_persist_vocabulary_delta_mit_leerem_delta_tut_nichts(self):
        con = self.manager._connect()
        self.manager._persist_vocabulary_delta(con, Counter())  # darf nicht crashen
        self.assertEqual(self.manager._load_vocabulary(con), {})

    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_standard_modus_wendet_keine_automatische_korrektur_an(self, mock_meta, mock_text):
        """Ohne Stufen-Auswahl (index_text_mode='standard', der setUp-Default) bleibt alles wie vor der Automatisierung: Tier 'standard', kein Wortschatz-Aufbau."""
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Kunde"

        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)

        con = self.manager._connect()
        for tier, text_erweitert in con.execute("SELECT tier, text_erweitert FROM fulltext"):
            self.assertEqual(tier, "standard")
            self.assertEqual(text_erweitert, "")
        self.assertEqual(list(con.execute("SELECT COUNT(*) FROM vocabulary"))[0][0], 0)

    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_neue_dokumente_landen_beim_scannen_automatisch_auf_erweitert(self, mock_meta, mock_text):
        """Sobald index_text_mode != 'standard' ist, springen neu gecachte Dokumente direkt auf Tier 'erweitert' - kein Klick auf 'Jetzt ausführen' nötig."""
        self.mock_app.config.get.side_effect = lambda key, default=None: "erweitert" if key == "index_text_mode" else default
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Kunde"

        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)

        con = self.manager._connect()
        tiers = [row[0] for row in con.execute("SELECT tier FROM fulltext")]
        self.assertEqual(tiers, ["erweitert", "erweitert"])

    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_automatische_korrektur_nutzt_nur_vorher_bekannten_wortschatz(self, mock_meta, mock_text):
        """
        Regressionstest gegen Selbstvergiftung: würde die automatische Korrektur die frisch
        eingelesenen (kaputten) Wörter DIESES Batches selbst mit einmischen, würde
        "Versicherun" durch seine bloße Anwesenheit im Rohtext sofort als "bekannt" gelten
        und NIE zu "Versicherung" korrigiert werden - obwohl "Versicherung" bereits VORHER
        im persistierten Wortschatz stand.
        """
        self.mock_app.config.get.side_effect = lambda key, default=None: "erweitert" if key == "index_text_mode" else default
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Versicherun"

        con = self.manager._connect()
        with con:
            con.execute("INSERT INTO vocabulary (word, freq) VALUES ('versicherung', 10)")

        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)

        for (text_erweitert,) in con.execute("SELECT text_erweitert FROM fulltext"):
            self.assertIn("Versicherung", text_erweitert)

    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_wortschatz_wird_beim_automatischen_scannen_additiv_persistiert(self, mock_meta, mock_text):
        self.mock_app.config.get.side_effect = lambda key, default=None: "erweitert" if key == "index_text_mode" else default
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Kunde Kunde"

        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)  # a.pdf + b.pdf, je 2x "Kunde"

        con = self.manager._connect()
        freq = dict(con.execute("SELECT word, freq FROM vocabulary"))
        self.assertEqual(freq.get("kunde"), 4)

    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_wortschatz_waechst_ueber_mehrere_scans_additiv(self, mock_meta, mock_text):
        self.mock_app.config.get.side_effect = lambda key, default=None: "erweitert" if key == "index_text_mode" else default
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Kunde"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)  # a.pdf + b.pdf -> "kunde" freq 2

        self._schreibe_pdf("c.pdf", "Inhalt C")  # neue Datei -> beim naechsten Scan stale
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)  # c.pdf -> +1

        con = self.manager._connect()
        freq = dict(con.execute("SELECT word, freq FROM vocabulary"))
        self.assertEqual(freq.get("kunde"), 3)

    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_erweitert_tier_persistiert_wortschatz_fuer_kuenftige_laeufe(self, mock_meta, mock_text):
        """Der manuelle Nachzieh-Lauf (Altbestand, Tier 'standard' bei mode='standard' gescannt) speist den persistenten Wortschatz genauso wie die automatische Anwendung."""
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Kunde Kunde"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)  # mode='standard' -> Tier bleibt 'standard', Wortschatz noch leer

        self.manager.upgrade_to_erweitert_tier()

        con = self.manager._connect()
        freq = dict(con.execute("SELECT word, freq FROM vocabulary"))
        self.assertEqual(freq.get("kunde"), 4)

    # ==========================================
    # MEISTER-STUFE (KI-Prüfung des Re-OCR-Texts)
    # ==========================================
    @patch("index_manager.ollama_client.suggest_cleaned_text")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_meister_tier_ueberspringt_noch_nicht_fortgeschrittene(self, mock_meta, mock_text, mock_clean):
        """Ohne vorheriges Re-OCR (Tier 'standard') gibt es nichts zu prüfen - Dokumente werden übersprungen, nicht bearbeitet."""
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Text"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)  # Standard-Cache befuellen, tier bleibt 'standard'

        done, skipped = self.manager.upgrade_to_meister_tier("http://server", "modell")

        self.assertEqual(done, 0)
        self.assertEqual(skipped, 2)
        mock_clean.assert_not_called()

    @patch("index_manager.ollama_client.suggest_cleaned_text")
    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_meister_tier_ergaenzt_text_ai_ohne_andere_zu_verlieren(self, mock_meta, mock_text, mock_ocr, mock_clean):
        """"Ergänzen statt ersetzen": text_ai kommt dazu, text/text_ocr bleiben unangetastet."""
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Originaltext"
        mock_ocr.return_value = "Re-OCR-Text"
        mock_clean.return_value = "KI-geprüfter Text"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)
        self.manager.upgrade_to_ocr_tier("pfad")  # Voraussetzung: erst 'Fortgeschritten'

        done, skipped = self.manager.upgrade_to_meister_tier("http://server", "modell")

        self.assertEqual(done, 2)
        self.assertEqual(skipped, 0)
        self.assertEqual(mock_clean.call_count, 2)
        rows = {r[0]: r for r in self.manager._connect().execute(
            "SELECT rel_path, text, text_ocr, text_ai, tier FROM fulltext")}
        for rel_path, (_, text, text_ocr, text_ai, tier) in rows.items():
            self.assertEqual(text, "Originaltext")
            self.assertEqual(text_ocr, "Re-OCR-Text")
            self.assertEqual(text_ai, "KI-geprüfter Text")
            self.assertEqual(tier, "meister")

    @patch("index_manager.ollama_client.suggest_cleaned_text")
    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_meister_tier_ueberspringt_bereits_hochgestufte(self, mock_meta, mock_text, mock_ocr, mock_clean):
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Text"
        mock_ocr.return_value = "OCR"
        mock_clean.return_value = "KI-Text"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)
        self.manager.upgrade_to_ocr_tier("pfad")
        self.manager.upgrade_to_meister_tier("http://server", "modell")
        mock_clean.reset_mock()

        done, skipped = self.manager.upgrade_to_meister_tier("http://server", "modell")

        # 'skipped' zählt nur Dokumente, denen das Re-OCR fehlt (siehe Docstring) - bereits
        # auf 'meister' hochgestufte sind schlicht fertig, nicht "übersprungen".
        self.assertEqual(done, 0)
        self.assertEqual(skipped, 0)
        mock_clean.assert_not_called()

    @patch("index_manager.ollama_client.suggest_cleaned_text")
    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_meister_tier_respektiert_should_stop(self, mock_meta, mock_text, mock_ocr, mock_clean):
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Text"
        mock_ocr.return_value = "OCR"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)
        self.manager.upgrade_to_ocr_tier("pfad")

        done, skipped = self.manager.upgrade_to_meister_tier("http://server", "modell", should_stop=lambda: True)

        self.assertEqual(done, 0)  # bricht VOR dem ersten Dokument ab
        mock_clean.assert_not_called()

    @patch("index_manager.ollama_client.suggest_cleaned_text")
    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_meister_tier_ruft_progress_callback(self, mock_meta, mock_text, mock_ocr, mock_clean):
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Text"
        mock_ocr.return_value = "OCR"
        mock_clean.return_value = "KI-Text"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)
        self.manager.upgrade_to_ocr_tier("pfad")

        calls = []
        self.manager.upgrade_to_meister_tier("http://server", "modell", on_progress=lambda d, t: calls.append((d, t)))

        self.assertEqual(calls, [(1, 2), (2, 2)])

    @patch("index_manager.ollama_client.suggest_cleaned_text")
    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_search_fulltext_matched_auch_ueber_text_ai(self, mock_meta, mock_text, mock_ocr, mock_clean):
        """Ein Treffer, der nur im KI-geprüften Text steckt (nicht in Original oder Re-OCR), muss trotzdem gefunden werden."""
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Kauderwelsch ohne Treffer"
        mock_ocr.return_value = "Auch hier kein Treffer"
        mock_clean.return_value = "Stadtwerke Rechnung"
        self.manager.iter_documents()
        self.manager.search_fulltext(lambda text: False)
        self.manager.upgrade_to_ocr_tier("pfad")
        self.manager.upgrade_to_meister_tier("http://server", "modell")

        hits = self.manager.search_fulltext(lambda text: "stadtwerke" in text)
        self.assertEqual(hits, {"a.pdf", os.path.join("Ordner", "b.pdf")})

    @patch("index_manager.ollama_client.suggest_cleaned_text")
    @patch("index_manager.PDFHandler.get_fulltext_ocr")
    @patch("index_manager.PDFHandler.get_fulltext")
    @patch("index_manager.PDFHandler.get_metadata")
    def test_upgrade_to_meister_tier_nutzt_keine_geteilte_verbindung(self, mock_meta, mock_text, mock_ocr, mock_clean):
        """
        Regressionstest wie bei upgrade_to_ocr_tier: läuft in einem Hintergrund-Thread,
        darf self._con nicht anfassen. Die Fortgeschritten-Vorbedingung wird bewusst über
        eine eigene, rohe Verbindung vorbereitet statt über self.manager.iter_documents()/
        search_fulltext() - genau diese Aufrufe würden self._con sonst an DIESEN
        (Test-)Thread binden und den eigentlichen Regressionsfall verdecken.
        """
        import sqlite3
        import app_paths
        mock_meta.return_value = {"title": "", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Text"
        mock_ocr.return_value = "OCR"
        mock_clean.return_value = "KI-Text"

        path = app_paths.index_path(self.master)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        con = sqlite3.connect(path)
        con.execute(IndexManager.SCHEMA)
        con.execute(IndexManager.SCHEMA_FULLTEXT)
        for rel_path in ("a.pdf", os.path.join("Ordner", "b.pdf")):
            con.execute("INSERT INTO files (rel_path, mtime, size) VALUES (?, 1.0, 1)", (rel_path,))
            con.execute(
                "INSERT INTO fulltext (rel_path, mtime, size, text, text_ocr, tier) "
                "VALUES (?, 1.0, 1, 'Original', 'ReOCR', 'fortgeschritten')", (rel_path,))
        con.commit()
        con.close()

        self.manager.upgrade_to_meister_tier("http://server", "modell")

        self.assertIsNone(self.manager._con)

    @patch("index_manager.PDFHandler.get_metadata")
    def test_migration_ergaenzt_spalten_einer_aelteren_index_datei(self, mock_meta):
        """Eine index.sqlite aus einer älteren App-Version (nur die ursprünglichen 6 Spalten) darf nicht crashen, sondern wird migriert."""
        import sqlite3
        data_dir = os.path.join(self.tmp, "KID-Daten")
        os.makedirs(data_dir, exist_ok=True)
        con = sqlite3.connect(os.path.join(data_dir, "index.sqlite"))
        con.execute("""
            CREATE TABLE files (
                rel_path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '', keywords TEXT NOT NULL DEFAULT '',
                kid_date TEXT NOT NULL DEFAULT ''
            )
        """)
        con.close()

        mock_meta.return_value = {
            "title": "T", "keywords": "", "KID_DokumentenDatum": "",
            "creationDate": "D:20220505185907+01'00'", "KID_ScanZeitpunkt": "",
        }
        docs = self.manager.iter_documents()

        self.assertEqual(len(docs), 2)
        self.assertTrue(all(d["creation_date"] == "D:20220505185907+01'00'" for d in docs))

    @patch("index_manager.PDFHandler.get_metadata")
    @patch("index_manager.PDFHandler.get_fulltext")
    def test_migration_ergaenzt_text_ai_spalte_bei_altem_volltext_cache(self, mock_text, mock_meta):
        """Ein Volltext-Cache aus der Fortgeschritten-Session (ohne text_ai-Spalte) darf nicht crashen, sondern wird migriert."""
        import sqlite3
        data_dir = os.path.join(self.tmp, "KID-Daten")
        os.makedirs(data_dir, exist_ok=True)
        con = sqlite3.connect(os.path.join(data_dir, "index.sqlite"))
        con.execute("""
            CREATE TABLE files (
                rel_path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '', keywords TEXT NOT NULL DEFAULT '',
                kid_date TEXT NOT NULL DEFAULT '', creation_date TEXT NOT NULL DEFAULT '',
                scan_zeit TEXT NOT NULL DEFAULT ''
            )
        """)
        con.execute("""
            CREATE TABLE fulltext (
                rel_path TEXT PRIMARY KEY, mtime REAL NOT NULL, size INTEGER NOT NULL,
                text TEXT NOT NULL DEFAULT '', text_ocr TEXT NOT NULL DEFAULT '',
                tier TEXT NOT NULL DEFAULT 'standard'
            )
        """)
        con.close()

        mock_meta.return_value = {"title": "T", "keywords": "", "KID_DokumentenDatum": ""}
        mock_text.return_value = "Inhalt"
        self.manager.iter_documents()

        hits = self.manager.search_fulltext(lambda text: "inhalt" in text)
        self.assertEqual(hits, {"a.pdf", os.path.join("Ordner", "b.pdf")})



class TestVermuteteDaten(unittest.TestCase):
    """FALLSTRICKE #86: vermutetes Dokumentdatum für die Listen, gemerkt im Index."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.master = os.path.join(self.tmp, "KID")
        os.makedirs(self.master)
        self.mock_app = MagicMock()
        self.mock_app.master_folder = self.master
        self.mock_app.config.get.side_effect = lambda key, default=None: default
        self.manager = IndexManager(self.mock_app)
        self.mock_app.index_manager = self.manager
        self.pfad = os.path.join(self.master, "konto.pdf")
        with open(self.pfad, "w") as f:
            f.write("x")

    def tearDown(self):
        self.manager.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch("index_manager.PDFHandler.suggest_document_date", return_value="2025-01-31")
    def test_liest_einmal_und_merkt_sich_das_datum(self, mock_datum):
        self.assertEqual(self.manager.vermutete_daten([self.pfad]), {self.pfad: "2025-01-31"})
        self.assertEqual(self.manager.vermutete_daten([self.pfad]), {self.pfad: "2025-01-31"})
        self.assertEqual(mock_datum.call_count, 1)

    @patch("index_manager.PDFHandler.suggest_document_date", return_value=None)
    def test_nichts_gefunden_wird_auch_gemerkt(self, mock_datum):
        self.assertEqual(self.manager.vermutete_daten([self.pfad]), {self.pfad: ""})
        self.manager.vermutete_daten([self.pfad])
        self.assertEqual(mock_datum.call_count, 1)

    @patch("index_manager.PDFHandler.suggest_document_date", side_effect=["2025-01-31", "2025-02-28"])
    def test_veraenderte_datei_wird_neu_gelesen(self, mock_datum):
        self.manager.vermutete_daten([self.pfad])
        with open(self.pfad, "w") as f:
            f.write("verändert, andere Größe")
        self.assertEqual(self.manager.vermutete_daten([self.pfad]), {self.pfad: "2025-02-28"})

    def test_verschwundene_datei_fehlt_im_ergebnis(self):
        self.assertEqual(self.manager.vermutete_daten([os.path.join(self.master, "weg.pdf")]), {})

    def test_sicher_ohne_index_oder_bei_fehler_leer(self):
        app = MagicMock()
        app.config.get.side_effect = lambda key, default=None: False if key == "use_index" else default
        self.assertEqual(index_manager.vermutete_daten_sicher(app, [self.pfad]), {})
        app.config.get.side_effect = lambda key, default=None: default
        app.index_manager.vermutete_daten.side_effect = RuntimeError("defekt")
        self.assertEqual(index_manager.vermutete_daten_sicher(app, [self.pfad]), {})
        app.logger.error.assert_called_once()

    def test_als_listendatum(self):
        self.assertEqual(index_manager.als_listendatum("2025-01-31"), ("31.01.2025", "20250131", 2025))
        self.assertIsNone(index_manager.als_listendatum(""))
        self.assertIsNone(index_manager.als_listendatum(None))


class TestMetadatenFuerOrdnerliste(unittest.TestCase):
    """Ordnerliste aus dem Index (01.11.2026): unveränderte PDFs werden nicht mehr geöffnet."""

    META = {"title": "Kontoauszug", "keywords": "Bank, Konto", "KID_DokumentenDatum": "2025-01-31",
            "creationDate": "D:20250131", "KID_ScanZeitpunkt": "", "KID_ID": "ABCD-EFGH", "KID_Absender": "Bank"}

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.master = os.path.join(self.tmp, "KID")
        os.makedirs(self.master)
        self.mock_app = MagicMock()
        self.mock_app.master_folder = self.master
        self.mock_app.config.get.side_effect = lambda key, default=None: default
        self.manager = IndexManager(self.mock_app)
        self.mock_app.index_manager = self.manager
        self.pfad = os.path.join(self.master, "konto.pdf")
        with open(self.pfad, "w") as f:
            f.write("x")

    def tearDown(self):
        self.manager.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _erwartet(self, meta):
        return dict({k: meta[k] for k in ("title", "keywords", "KID_DokumentenDatum", "creationDate", "KID_ScanZeitpunkt")},
                    KID_Erfasst=meta.get("KID_Erfasst", ""), KID_Richtung=meta.get("KID_Richtung", ""))

    def test_liest_einmal_und_liefert_danach_aus_dem_index(self):
        with patch("index_manager.PDFHandler.get_metadata", return_value=self.META) as lesen:
            self.assertEqual(self.manager.metadaten([self.pfad]), {self.pfad: self._erwartet(self.META)})
            self.assertEqual(self.manager.metadaten([self.pfad]), {self.pfad: self._erwartet(self.META)})
        self.assertEqual(lesen.call_count, 1)

    def test_nachgetragene_zeile_nutzt_auch_die_suche(self):
        """Die Ordnerliste trägt vollständige Zeilen ein - der Abgleich der Suche muss sie nicht neu lesen."""
        with patch("index_manager.PDFHandler.get_metadata", return_value=self.META) as lesen:
            self.manager.metadaten([self.pfad])
            dokumente = self.manager.iter_documents()
        self.assertEqual(lesen.call_count, 1)
        self.assertEqual(dokumente[0]["kid_id"], "ABCD-EFGH")
        self.assertEqual(dokumente[0]["absender"], "Bank")

    def test_veraenderte_datei_wird_neu_gelesen(self):
        neu = dict(self.META, title="Kontoauszug Februar")
        with patch("index_manager.PDFHandler.get_metadata", side_effect=[self.META, neu]):
            self.manager.metadaten([self.pfad])
            with open(self.pfad, "w") as f:
                f.write("verändert, andere Größe")
            self.assertEqual(self.manager.metadaten([self.pfad])[self.pfad]["title"], "Kontoauszug Februar")

    def test_verschwundene_und_fremde_dateien_fehlen(self):
        fremd = os.path.join(self.tmp, "fremd.pdf")
        with open(fremd, "w") as f:
            f.write("x")
        with patch("index_manager.PDFHandler.get_metadata", return_value=self.META) as lesen:
            self.assertEqual(self.manager.metadaten([os.path.join(self.master, "weg.pdf"), fremd]), {})
        lesen.assert_not_called()

    def test_sicher_ohne_index_oder_bei_fehler_leer(self):
        app = MagicMock()
        app.config.get.side_effect = lambda key, default=None: False if key == "use_index" else default
        self.assertEqual(index_manager.metadaten_sicher(app, [self.pfad]), {})
        app.config.get.side_effect = lambda key, default=None: default
        app.index_manager.metadaten.side_effect = RuntimeError("defekt")
        self.assertEqual(index_manager.metadaten_sicher(app, [self.pfad]), {})
        app.logger.error.assert_called_once()


class TestSchnelleUnscharfeSuche(unittest.TestCase):
    """Unscharfe Volltextsuche über den Wortschatz (Spike S4, 01.11.2026): MUSS exakt dieselben Treffer
    liefern wie der Matcher je Dokument - nur schneller."""

    TEXTE = {
        "a.pdf": "Schornsteinl'eger Rechnung 2023",              # von der Texterkennung zerrissen
        "b.pdf": "Datei stadtwerke_rechnung_2026 im Anhang",      # Unterstriche trennen Wörter
        "c.pdf": "Ihre Rechnnug vom Amt",                         # Tippfehler im Dokument
        "d.pdf": "Grundsteuerbescheid für das Jahr",              # Teilwort
        "e.pdf": "für Steiier-\nzwecken absetzbar",               # Trennstrich über den Zeilenumbruch
        "f.pdf": "Versicherungskasse Musterland",
        "g.pdf": "Müllabfuhr Gebühr Musterstadt",                 # Umlaute
        "h.pdf": "Kauderwelsch xqz ohne Bezug",
        "i.pdf": "Vorgang VG 012345 erledigt",                    # Kennung ohne Bindestrich
        "j.pdf": "Rechnungen und Mahnungen",
        "k.pdf": "Versicherunq Beitrag",                          # Texterkennung: q statt g
        "l.pdf": "Schorn steinfeger kam",                         # Leerzeichen mitten im Wort
    }
    BEGRIFFE = ["rechnung", "rechnnug", "schornsteinfeger", "steuerzwecken", "grundsteuer", "versicherung",
                "müllabfuhr", "xylophon", "stadtwerke", "vg-012345", "mahnung", "bayern", "beitrag"]

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.master = os.path.join(self.tmp, "KID")
        os.makedirs(self.master)
        for name, text in self.TEXTE.items():
            with open(os.path.join(self.master, name), "w", encoding="utf-8") as f:
                f.write(text)  # Größe unterscheidet die Dateien, Inhalt liest der Mock
        app = MagicMock()
        app.master_folder = self.master
        app.config.get.side_effect = lambda key, default=None: default
        self.manager = IndexManager(app)
        self.patches = [
            patch("index_manager.PDFHandler.get_metadata",
                  return_value={"title": "", "keywords": "", "KID_DokumentenDatum": ""}),
            patch("index_manager.PDFHandler.get_fulltext",
                  side_effect=lambda pfad: self.TEXTE[os.path.basename(pfad)]),
        ]
        for p in self.patches:
            p.start()
        self.manager.iter_documents()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.manager.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_gleiche_treffer_wie_matcher_je_dokument(self):
        from search_manager import SearchManager
        for begriff in self.BEGRIFFE:
            matcher = SearchManager.begriff_matcher(begriff)
            erwartet = {n for n, t in self.TEXTE.items() if matcher(t.lower())}
            with self.subTest(begriff=begriff):
                self.assertTrue(hasattr(matcher, "aehnliche_woerter"))  # nimmt wirklich den schnellen Weg
                self.assertEqual(self.manager.search_fulltext(matcher), erwartet)

    def test_zerrissene_woerter_werden_gefunden(self):
        from search_manager import SearchManager
        self.assertEqual(self.manager.search_fulltext(SearchManager.begriff_matcher("schornsteinfeger")),
                         {"a.pdf", "l.pdf"})
        self.assertEqual(self.manager.search_fulltext(SearchManager.begriff_matcher("steuerzwecken")), {"e.pdf"})
        self.assertEqual(self.manager.search_fulltext(SearchManager.begriff_matcher("vg-012345")), {"i.pdf"})

    def test_wortschatz_bleibt_gemerkt_solange_sich_nichts_aendert(self):
        from search_manager import SearchManager
        self.manager.search_fulltext(SearchManager.begriff_matcher("rechnung"))
        gemerkt = self.manager._suchwortschatz
        self.manager.search_fulltext(SearchManager.begriff_matcher("bayern"))
        self.assertIs(self.manager._suchwortschatz, gemerkt)

    def test_geaenderte_datei_erneuert_den_wortschatz(self):
        from search_manager import SearchManager
        self.manager.search_fulltext(SearchManager.begriff_matcher("rechnung"))
        self.TEXTE = dict(self.TEXTE, **{"h.pdf": "Jetzt mit Zahnarztrechnunq"})
        with open(os.path.join(self.master, "h.pdf"), "w", encoding="utf-8") as f:
            f.write("geändert, andere Größe")
        self.manager.iter_documents()
        treffer = self.manager.search_fulltext(SearchManager.begriff_matcher("zahnarztrechnung"))
        self.assertEqual(treffer, {"h.pdf"})

    def test_hochstufung_erneuert_den_wortschatz(self):
        """Ein nur im verbesserten Text stehendes Wort muss nach upgrade_to_erweitert_tier gefunden werden."""
        from search_manager import SearchManager
        self.manager.search_fulltext(SearchManager.begriff_matcher("rechnung"))
        with patch("index_manager.spell_correct.suggest_corrected_text",
                   side_effect=lambda text, voc: "Heizkostenabrechnung" if "Kauderwelsch" in text else ""):
            self.manager.upgrade_to_erweitert_tier()
        treffer = self.manager.search_fulltext(SearchManager.begriff_matcher("heizkostenabrechnunq"))
        self.assertEqual(treffer, {"h.pdf"})

    def test_muster_ohne_aehnliche_woerter_ist_none(self):
        self.assertIsNone(index_manager.muster_fuer_aehnliche(set(), {"a"}, set()))


if __name__ == "__main__":
    unittest.main()
