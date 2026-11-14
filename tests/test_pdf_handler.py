import unittest
import os
import tempfile
from unittest.mock import patch

from pdf_handler import PDFHandler

class TestPDFHandler(unittest.TestCase):
    
    def setUp(self):
        """Wird VOR jedem einzelnen Test ausgeführt. Bereitet die Umgebung vor."""
        self.test_pdf = "test_dummy_dokument.pdf"
        
        if PDFHandler.is_supported():
            import fitz
            doc = fitz.open()
            doc.new_page() # Eine leere Seite hinzufügen
            doc.save(self.test_pdf)
            doc.close()

    def tearDown(self):
        """Wird NACH jedem Test ausgeführt. Räumt auf."""
        if os.path.exists(self.test_pdf):
            try:
                os.remove(self.test_pdf)
            except Exception as e:
                print(f"Konnte Test-Datei nicht löschen: {e}")

    def test_is_supported(self):
        self.assertIsInstance(PDFHandler.is_supported(), bool)

    def test_non_existent_file(self):
        # Sollte leere Werte zurückgeben und nicht abstürzen
        meta = PDFHandler.get_metadata("existiert_garantiert_nicht.pdf")
        self.assertEqual(meta, {"title": "", "keywords": "", "KID_DokumentenDatum": "", "KID_ScanZeitpunkt": ""})
        
        # Vorschau sollte None sein, ohne zu crashen
        img = PDFHandler.get_preview_image("existiert_garantiert_nicht.pdf", 800, 600)
        self.assertIsNone(img)
        
    def test_metadata_read_write(self):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert, überspringe Test.")

        test_titel = "Mein Geheimer Test-Titel"
        test_tags = "Wichtig, Steuern, 2026"

        erfolg, nachricht = PDFHandler.save_metadata(self.test_pdf, test_titel, test_tags)
        self.assertTrue(erfolg, f"Speichern ist fehlgeschlagen: {nachricht}")

        meta = PDFHandler.get_metadata(self.test_pdf)
        self.assertEqual(meta.get("title"), test_titel)
        self.assertEqual(meta.get("keywords"), test_tags)

    def test_file_lock_release(self):
        """ ---> NEU: Überprüft, ob das Dokument korrekt geschlossen wird (kein File-Lock) """
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
            
        # Wir lesen und schreiben fröhlich Metadaten...
        PDFHandler.get_metadata(self.test_pdf)
        PDFHandler.save_metadata(self.test_pdf, "Test-Lock", "Tag")
        
        # Wenn ein File-Lock besteht, wirft os.rename unter Windows sofort einen PermissionError
        new_name = "test_dummy_dokument_renamed.pdf"
        try:
            os.rename(self.test_pdf, new_name)
            os.rename(new_name, self.test_pdf) # direkt wieder zurücksetzen für den tearDown
            lock_released = True
        except PermissionError:
            lock_released = False
            
        self.assertTrue(lock_released, "Die Datei ist nach dem Metadaten-Zugriff noch blockiert! File-Lock detektiert!")

    def test_get_fulltext(self):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        import fitz
        text_pdf = "test_fulltext_dokument.pdf"
        doc = fitz.open()
        doc.new_page().insert_text((50, 100), "Beispieltext fuer den Volltext-Cache")
        doc.save(text_pdf)
        doc.close()
        self.addCleanup(lambda: os.path.exists(text_pdf) and os.remove(text_pdf))

        self.assertIn("Beispieltext", PDFHandler.get_fulltext(text_pdf))

    def test_get_fulltext_missing_file(self):
        self.assertEqual(PDFHandler.get_fulltext("existiert_garantiert_nicht.pdf"), "")

    def test_get_fulltext_ocr_missing_file(self):
        self.assertEqual(PDFHandler.get_fulltext_ocr("existiert_garantiert_nicht.pdf", "irgendein/pfad"), "")

    def test_kid_subject_roundtrip(self):
        """parse_kid_subject/build_kid_subject: neues Mehr-Feld-Format und Alt-Format (nur KID_DATE)."""
        # Alt-Format bleibt lesbar (abwärtskompatibel)
        self.assertEqual(PDFHandler.parse_kid_subject("KID_DATE:2026-05-12"), ("2026-05-12", ""))
        # Neues kombiniertes Format
        self.assertEqual(PDFHandler.parse_kid_subject("KID_DATE:2026-05-12|KID_SCAN:2026-04-13 14:32"),
                          ("2026-05-12", "2026-04-13 14:32"))
        # Nur Scan-Zeitpunkt (Dokument-Datum noch nicht gesetzt)
        self.assertEqual(PDFHandler.parse_kid_subject("KID_SCAN:2026-04-13"), ("", "2026-04-13"))
        # Fremder/leerer subject-Inhalt liefert leere Felder
        self.assertEqual(PDFHandler.parse_kid_subject("Irgendein echter Betreff"), ("", ""))
        self.assertEqual(PDFHandler.parse_kid_subject(""), ("", ""))
        # build ist das exakte Gegenstück
        self.assertEqual(PDFHandler.build_kid_subject("2026-05-12", "2026-04-13 14:32"),
                          "KID_DATE:2026-05-12|KID_SCAN:2026-04-13 14:32")
        self.assertEqual(PDFHandler.build_kid_subject("2026-05-12", ""), "KID_DATE:2026-05-12")
        self.assertEqual(PDFHandler.build_kid_subject("", ""), "")
        # Ursprünglicher Dateiname (11.09.2026): eigenes Feld, alte Aufrufer sehen weiter ein 2er-Tuple
        subject = PDFHandler.build_kid_subject("2026-05-12", "2026-04-13 14:32", "Scan_0001.pdf")
        self.assertEqual(subject, "KID_DATE:2026-05-12|KID_SCAN:2026-04-13 14:32|KID_NAME:Scan_0001.pdf")
        self.assertEqual(PDFHandler.parse_kid_subject(subject), ("2026-05-12", "2026-04-13 14:32"))
        self.assertEqual(PDFHandler.parse_kid_original_name(subject), "Scan_0001.pdf")
        self.assertEqual(PDFHandler.parse_kid_original_name("KID_DATE:2026-05-12"), "")
        self.assertEqual(PDFHandler.parse_kid_original_name(""), "")

    def test_scan_timestamp_written_on_save_and_preserved(self):
        """Beim ersten Speichern wird KID_SCAN automatisch eingebrannt und von späteren Saves nicht überschrieben."""
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")

        PDFHandler.save_metadata(self.test_pdf, "Titel", "Tag1")
        scan_first = PDFHandler.get_metadata(self.test_pdf).get("KID_ScanZeitpunkt")
        self.assertTrue(scan_first, "KID_SCAN wurde beim Speichern nicht eingebrannt")

        # Zweiter Save (auch mit Datums-Update) darf den einmal gespeicherten Wert nicht verändern
        PDFHandler.write_custom_metadata(self.test_pdf, {"KID_DokumentenDatum": "2026-05-12"})
        meta = PDFHandler.get_metadata(self.test_pdf)
        self.assertEqual(meta.get("KID_ScanZeitpunkt"), scan_first)
        self.assertEqual(meta.get("KID_DokumentenDatum"), "2026-05-12")

    def test_grund_der_vollautomatik_im_subject(self):
        """KID_GRUND (28.10.2026): setzen, beim weiteren Speichern behalten, mit '' löschen."""
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        PDFHandler.write_custom_metadata(self.test_pdf, {"KID_Grund": "kein Datum | kein Absender"}, still=True)
        self.assertEqual(PDFHandler.get_metadata(self.test_pdf)["KID_Grund"], "kein Datum kein Absender")
        PDFHandler.save_metadata(self.test_pdf, "Titel", "Tag")
        self.assertEqual(PDFHandler.get_metadata(self.test_pdf)["KID_Grund"], "kein Datum kein Absender")
        PDFHandler.write_custom_metadata(self.test_pdf, {"KID_Grund": ""}, still=True)
        self.assertEqual(PDFHandler.get_metadata(self.test_pdf)["KID_Grund"], "")
        self.assertEqual(PDFHandler.parse_kid_grund("KID_ID:ABCD-EFGH|KID_GRUND:x: y"), "x: y")

    def test_save_metadata_schreibt_datum_mit(self):
        """FALLSTRICKE #86: Titel, Tags und Dokumentdatum in einem Schreibvorgang; ohne datum bleibt es unverändert."""
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        PDFHandler.save_metadata(self.test_pdf, "Kontoauszug Januar 2025", "Kontoauszug", datum="2025-01-31")
        meta = PDFHandler.get_metadata(self.test_pdf)
        self.assertEqual((meta.get("title"), meta.get("KID_DokumentenDatum")), ("Kontoauszug Januar 2025", "2025-01-31"))
        PDFHandler.save_metadata(self.test_pdf, "Neuer Titel", "Kontoauszug")
        self.assertEqual(PDFHandler.get_metadata(self.test_pdf).get("KID_DokumentenDatum"), "2025-01-31")

    # ==========================================
    # SCHREIBSCHUTZ-ERKENNUNG (KONZEPT_PDF_ARTEN.md 1.5/1.6)
    # ==========================================
    def _erzeuge_verschluesseltes_pdf(self, path):
        import fitz
        doc = fitz.open()
        doc.new_page()
        doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="geheim")
        doc.close()

    def _erzeuge_schreibgeschuetztes_pdf(self, path):
        """Nur Besitzer-Passwort: öffnet ohne Passwort, verbietet aber Änderungen."""
        import fitz
        doc = fitz.open()
        doc.new_page()
        perm = fitz.PDF_PERM_ACCESSIBILITY | fitz.PDF_PERM_PRINT | fitz.PDF_PERM_COPY
        doc.save(path, encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="chef", permissions=perm)
        doc.close()

    def _erzeuge_signiertes_pdf(self, path):
        """Setzt die SigFlags im AcroForm per XREF - simuliert ein digital signiertes PDF (echtes Krypto-Signieren braucht Zertifikate, für die Erkennung zählen nur die SigFlags)."""
        import fitz
        doc = fitz.open()
        doc.new_page()
        doc.save(path)
        doc.close()
        # Neu vom Pfad öffnen: saveIncr() braucht ein Dokument MIT Dateinamen
        # (ein im RAM erzeugtes kennt keinen).
        doc = fitz.open(path)
        doc.xref_set_key(doc.pdf_catalog(), "AcroForm", "<< /SigFlags 3 /Fields [] >>")
        doc.saveIncr()
        doc.close()

    def test_get_write_protection_normales_pdf(self):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        self.assertIsNone(PDFHandler.get_write_protection(self.test_pdf))

    def test_get_write_protection_fehlende_datei(self):
        self.assertIsNone(PDFHandler.get_write_protection("existiert_garantiert_nicht.pdf"))

    def test_get_write_protection_verschluesselt(self):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        path = "test_verschluesselt.pdf"
        self._erzeuge_verschluesseltes_pdf(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

        self.assertEqual(PDFHandler.get_write_protection(path), "verschlüsselt")

    def test_get_write_protection_schreibgeschuetzt(self):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        path = "test_schreibgeschuetzt.pdf"
        self._erzeuge_schreibgeschuetztes_pdf(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

        self.assertEqual(PDFHandler.get_write_protection(path), "schreibgeschützt")

    def test_get_write_protection_signiert(self):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        path = "test_signiert.pdf"
        self._erzeuge_signiertes_pdf(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

        self.assertEqual(PDFHandler.get_write_protection(path), "signiert")

    @patch("pdf_handler.mb")
    def test_write_custom_metadata_verweigert_verschluesselte(self, mock_mb):
        """Verschlüsselte PDFs dürfen NIE verändert werden - Rückgabe False + Fehlerdialog, Datei bleibt byte-identisch."""
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        path = "test_verschluesselt_schreiben.pdf"
        self._erzeuge_verschluesseltes_pdf(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with open(path, "rb") as f:
            bytes_vorher = f.read()

        erfolg = PDFHandler.write_custom_metadata(path, {"title": "Darf nicht ankommen"})

        self.assertFalse(erfolg)
        mock_mb.showerror.assert_called_once()
        with open(path, "rb") as f:
            self.assertEqual(f.read(), bytes_vorher)

    @patch("pdf_handler.mb")
    def test_write_custom_metadata_signiert_schreibt_inkrementell(self, mock_mb):
        """Signierte PDFs: Metadaten kommen an, aber per Anhängen (SigFlags/Signatur-Struktur bleibt erhalten, Datei wächst statt neu aufgebaut zu werden)."""
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        path = "test_signiert_schreiben.pdf"
        self._erzeuge_signiertes_pdf(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        groesse_vorher = os.path.getsize(path)

        erfolg = PDFHandler.write_custom_metadata(path, {"title": "Titel trotz Signatur", "KID_DokumentenDatum": "2026-05-12"})

        self.assertTrue(erfolg)
        mock_mb.showerror.assert_not_called()
        meta = PDFHandler.get_metadata(path)
        self.assertEqual(meta.get("title"), "Titel trotz Signatur")
        self.assertEqual(meta.get("KID_DokumentenDatum"), "2026-05-12")
        # Signatur-Kennzeichen überlebt UND die Datei ist gewachsen (inkrementell angehängt statt neu aufgebaut)
        self.assertEqual(PDFHandler.get_write_protection(path), "signiert")
        self.assertGreater(os.path.getsize(path), groesse_vorher)

    # ==========================================
    # SEITEN-KLASSIFIZIERUNG fürs Neu-Erfassen-Tool (KONZEPT_PDF_ARTEN.md 1.1-1.3)
    # ==========================================
    def _erzeuge_klassifizierungs_pdf(self, path):
        """
        Baut ein synthetisches 5-Seiten-PDF mit allen Seitentypen:
        1 Scan (Vollbild + unsichtbarer OCR-Text, Render-Modus 3), 2 digital
        (sichtbarer Text), 3 Misch (Vollbild + sichtbarer Text), 4 leer,
        5 Misch (Teilbild ohne Text).
        """
        import fitz
        doc = fitz.open()
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20))
        pix.clear_with(200)

        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, pixmap=pix)
        page.insert_text(fitz.Point(72, 72), "Unsichtbarer OCR Text", render_mode=3)

        page = doc.new_page(width=595, height=842)
        page.insert_text(fitz.Point(72, 72), "Sichtbarer Text")

        page = doc.new_page(width=595, height=842)
        page.insert_image(page.rect, pixmap=pix)
        page.insert_text(fitz.Point(72, 72), "Sichtbarer Stempel")

        doc.new_page(width=595, height=842)

        page = doc.new_page(width=595, height=842)
        page.insert_image(fitz.Rect(0, 0, 100, 100), pixmap=pix)

        doc.save(path)
        doc.close()

    def test_classify_pages_alle_seitentypen(self):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        path = "test_klassifizierung.pdf"
        self._erzeuge_klassifizierungs_pdf(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

        pages = PDFHandler.classify_pages(path)

        self.assertEqual([p["typ"] for p in pages], ["scan", "digital", "misch", "leer", "misch"])
        self.assertEqual([p["seite"] for p in pages], [1, 2, 3, 4, 5])
        # Scan-Seite: nur unsichtbare OCR-Ebene, Bild deckt die ganze Seite ab
        self.assertTrue(pages[0]["unsichtbarer_text"])
        self.assertFalse(pages[0]["sichtbarer_text"])
        self.assertGreaterEqual(pages[0]["bild_abdeckung"], 0.9)
        # Digital-Seite: sichtbarer Text, kein Bild
        self.assertTrue(pages[1]["sichtbarer_text"])
        self.assertEqual(pages[1]["bild_abdeckung"], 0.0)
        # Teilbild-Seite: kleines Bild reicht NICHT für "scan"
        self.assertLess(pages[4]["bild_abdeckung"], 0.9)

    def test_classify_pages_scan_ohne_textebene_ist_trotzdem_scan(self):
        """Frisch gescannt ohne OCR-Lauf: Vollbild ganz ohne Text muss ebenfalls als Scan gelten."""
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        import fitz
        path = "test_scan_ohne_text.pdf"
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 20, 20))
        pix.clear_with(200)
        page.insert_image(page.rect, pixmap=pix)
        doc.save(path)
        doc.close()
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

        pages = PDFHandler.classify_pages(path)

        self.assertEqual(pages[0]["typ"], "scan")
        self.assertFalse(pages[0]["unsichtbarer_text"])

    def test_classify_pages_fehlende_datei(self):
        self.assertEqual(PDFHandler.classify_pages("existiert_garantiert_nicht.pdf"), [])

    def test_classify_pages_verschluesseltes_pdf(self):
        """Verschlüsselte PDFs sind nicht analysierbar - leere Liste, kein Crash (Aufrufer verweigert dann)."""
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        path = "test_klassifizierung_verschluesselt.pdf"
        self._erzeuge_verschluesseltes_pdf(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

        self.assertEqual(PDFHandler.classify_pages(path), [])

    # ==========================================
    # NEU-ERFASSEN: OCR-Textebene zurückschreiben
    # ==========================================
    def _tessdata_verfuegbar(self):
        import app_paths
        return os.path.exists(os.path.join(app_paths.tessdata_dir(), "deu.traineddata"))

    def _erzeuge_scan_pdf_mit_kaputter_ocr_ebene(self, path, zweite_digitale_seite=False):
        """
        Baut ein Scan-artiges PDF: Seite 1 = Vollbild mit sichtbarem Text "Versichert
        nach dem Reinheitsgebot" (als Bild eingebettet, simuliert einen Scan) + eine
        GARBLED unsichtbare OCR-Ebene (wie ein kaputt lesender Scanner, siehe
        FALLSTRICKE #21). Optional eine zweite, echte digitale Seite zur Kontrolle,
        dass das Neu-Erfassen sie nicht anfasst.
        """
        import fitz
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        render_doc = fitz.open()
        render_page = render_doc.new_page(width=595, height=842)
        render_page.insert_text(fitz.Point(72, 100), "Versichert nach dem Reinheitsgebot", fontsize=18)
        pix = render_page.get_pixmap(dpi=150)
        page.insert_image(page.rect, stream=pix.tobytes("png"))
        page.insert_text(fitz.Point(72, 100), "kaputter garble text", fontsize=18, render_mode=3)
        if zweite_digitale_seite:
            seite2 = doc.new_page(width=595, height=842)
            seite2.insert_text(fitz.Point(72, 100), "Digitaler Text bleibt unangetastet", fontsize=14)
        doc.save(path)
        doc.close()

    def _wort(self, text):
        """Minimales Wort-Tupel im Format von page.get_text('words', ...): (x0,y0,x1,y1,text,block,line,wort)."""
        return (0, 0, 10, 10, text, 0, 0, 0)

    def test_waehle_bessere_textebene_bevorzugt_neue_bei_gleicher_oder_besserer_qualitaet(self):
        alte = [self._wort("Vcfsichctt")]  # kaputt
        neue = [self._wort("Versicherung")]  # sauber
        gewaehlt, alte_behalten = PDFHandler._waehle_bessere_textebene(alte, neue)
        self.assertEqual(gewaehlt, neue)
        self.assertFalse(alte_behalten)

    def test_waehle_bessere_textebene_behaelt_alte_wenn_neue_schlechter_ist(self):
        alte = [self._wort("Versicherung"), self._wort("Rechnung")]  # sauber
        neue = [self._wort("Vcfsichctt")]  # kaputt
        gewaehlt, alte_behalten = PDFHandler._waehle_bessere_textebene(alte, neue)
        self.assertEqual(gewaehlt, alte)
        self.assertTrue(alte_behalten)

    def test_waehle_bessere_textebene_nimmt_neue_wenn_alte_leer_war(self):
        """Kein Downside: eine leere alte Ebene (z.B. Scan ohne je gelaufenes OCR) darf die neue nie blockieren."""
        gewaehlt, alte_behalten = PDFHandler._waehle_bessere_textebene([], [self._wort("Vcfsichctt")])
        self.assertEqual(gewaehlt, [self._wort("Vcfsichctt")])
        self.assertFalse(alte_behalten)

    def test_waehle_bessere_textebene_beide_leer(self):
        gewaehlt, alte_behalten = PDFHandler._waehle_bessere_textebene([], [])
        self.assertEqual(gewaehlt, [])
        self.assertFalse(alte_behalten)

    def _erzeuge_scan_pdf_mit_sauberer_ocr_ebene(self, path):
        """Gegenstück zu _erzeuge_scan_pdf_mit_kaputter_ocr_ebene: die vorhandene unsichtbare OCR-Ebene ist bereits sauber (identisch zum sichtbaren Bildinhalt) - für Tests, in denen eine simulierte SCHLECHTERE neue OCR sie nicht überschreiben darf."""
        import fitz
        doc = fitz.open()
        page = doc.new_page(width=595, height=842)
        render_doc = fitz.open()
        render_page = render_doc.new_page(width=595, height=842)
        render_page.insert_text(fitz.Point(72, 100), "Versichert nach dem Reinheitsgebot", fontsize=18)
        pix = render_page.get_pixmap(dpi=150)
        page.insert_image(page.rect, stream=pix.tobytes("png"))
        page.insert_text(fitz.Point(72, 100), "Versichert nach dem Reinheitsgebot", fontsize=18, render_mode=3)
        doc.save(path)
        doc.close()

    def test_recapture_document_behaelt_alte_ebene_wenn_neue_ocr_schlechter_ist(self):
        """
        Regressionstest nach echtem Nutzer-Fund: ein erneutes OCR kann bei stark
        degradierten Scans auch mal SCHLECHTER ausfallen als die ursprüngliche
        Textebene. get_textpage_ocr wird hier durch ein leeres Ergebnis simuliert
        (deterministisch, unabhängig von der tatsächlichen Tesseract-Trefferquote,
        braucht daher auch keine lokale tessdata) - die neue, schlechtere ("leere")
        Ebene darf die bessere alte NICHT überschreiben.
        """
        import fitz
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        path = "test_recapture_alte_ebene_besser.pdf"
        self._erzeuge_scan_pdf_mit_sauberer_ocr_ebene(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

        with patch.object(fitz.Page, "get_textpage_ocr", lambda self, **kwargs: self.get_textpage()):
            erfolg, meldung, seiten = PDFHandler.recapture_document(path, "irrelevanter/pfad")

        self.assertTrue(erfolg, meldung)
        self.assertEqual(seiten, 1)
        self.assertIn("beibehalten", meldung)
        with fitz.open(path) as d:
            text = d[0].get_text()
        self.assertIn("Reinheitsgebot", text)

    def test_recapture_document_ersetzt_kaputte_ocr_ebene(self):
        import app_paths
        import fitz
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        if not self._tessdata_verfuegbar():
            self.skipTest("Tesseract-Sprachdaten (tessdata/deu.traineddata) nicht vorhanden.")
        path = "test_recapture_scan.pdf"
        self._erzeuge_scan_pdf_mit_kaputter_ocr_ebene(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with fitz.open(path) as d:
            bild_vorher = d.extract_image(d[0].get_images(full=True)[0][0])["image"]

        erfolg, meldung, seiten = PDFHandler.recapture_document(path, app_paths.tessdata_dir())

        self.assertTrue(erfolg, meldung)
        self.assertEqual(seiten, 1)
        with fitz.open(path) as d:
            neuer_text = d[0].get_text()
            bild_nachher = d.extract_image(d[0].get_images(full=True)[0][0])["image"]
        self.assertIn("Reinheitsgebot", neuer_text)
        self.assertNotIn("garble", neuer_text)
        # Bild-Objekt bleibt byteidentisch - keine Neukompression (KONZEPT_PDF_ARTEN.md 2.2)
        self.assertEqual(bild_vorher, bild_nachher)

    def test_recapture_document_laesst_digitale_seite_unangetastet(self):
        import app_paths
        import fitz
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        if not self._tessdata_verfuegbar():
            self.skipTest("Tesseract-Sprachdaten (tessdata/deu.traineddata) nicht vorhanden.")
        path = "test_recapture_hybrid.pdf"
        self._erzeuge_scan_pdf_mit_kaputter_ocr_ebene(path, zweite_digitale_seite=True)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

        erfolg, meldung, seiten = PDFHandler.recapture_document(path, app_paths.tessdata_dir())

        self.assertTrue(erfolg, meldung)
        self.assertEqual(seiten, 1)  # nur die Scan-Seite zählt, nicht die digitale
        with fitz.open(path) as d:
            self.assertEqual(d[1].get_text().strip(), "Digitaler Text bleibt unangetastet")
            for span in d[1].get_texttrace():
                self.assertEqual(span["type"], 0)  # weiterhin normal sichtbar, kein render_mode=3

    def test_recapture_document_ohne_scan_seiten(self):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        path = "test_recapture_nur_digital.pdf"
        import fitz
        doc = fitz.open()
        doc.new_page().insert_text(fitz.Point(72, 100), "Nur digitaler Text")
        doc.save(path)
        doc.close()
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with open(path, "rb") as f:
            bytes_vorher = f.read()

        erfolg, meldung, seiten = PDFHandler.recapture_document(path, "irgendein/pfad")

        self.assertFalse(erfolg)
        self.assertEqual(seiten, 0)
        self.assertIn("Keine Scan-Seiten", meldung)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), bytes_vorher)

    def test_recapture_document_fehlende_datei(self):
        self.assertEqual(
            PDFHandler.recapture_document("existiert_garantiert_nicht.pdf", "irgendein/pfad"),
            (False, "Datei nicht gefunden.", 0))

    def test_recapture_document_verweigert_geschuetzte_pdfs(self):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        path = "test_recapture_verschluesselt.pdf"
        self._erzeuge_verschluesseltes_pdf(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))

        erfolg, meldung, seiten = PDFHandler.recapture_document(path, "irgendein/pfad")

        self.assertFalse(erfolg)
        self.assertEqual(seiten, 0)
        self.assertIn("verschlüsselt", meldung)

    def test_recapture_document_groessenlimit_verweigert_und_laesst_datei_unveraendert(self):
        """Sicherheitsnetz gegen eine fehlgelaufene OCR-Explosion (KONZEPT_PDF_ARTEN.md 2.2) - Faktor künstlich auf 0 gesetzt, damit JEDES Ergebnis das Limit reißt."""
        import app_paths
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        if not self._tessdata_verfuegbar():
            self.skipTest("Tesseract-Sprachdaten (tessdata/deu.traineddata) nicht vorhanden.")
        path = "test_recapture_groessenlimit.pdf"
        self._erzeuge_scan_pdf_mit_kaputter_ocr_ebene(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with open(path, "rb") as f:
            bytes_vorher = f.read()

        with patch.object(PDFHandler, "RECAPTURE_MAX_SIZE_FACTOR", 0):
            erfolg, meldung, seiten = PDFHandler.recapture_document(path, app_paths.tessdata_dir())

        self.assertFalse(erfolg)
        self.assertEqual(seiten, 0)
        self.assertIn("groß", meldung)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), bytes_vorher)

    def test_recapture_document_ruft_on_progress_pro_seite_auf(self):
        import app_paths
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        if not self._tessdata_verfuegbar():
            self.skipTest("Tesseract-Sprachdaten (tessdata/deu.traineddata) nicht vorhanden.")
        path = "test_recapture_progress.pdf"
        self._erzeuge_scan_pdf_mit_kaputter_ocr_ebene(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        aufrufe = []

        PDFHandler.recapture_document(path, app_paths.tessdata_dir(),
                                       on_progress=lambda d, t: aufrufe.append((d, t)))

        self.assertEqual(aufrufe, [(1, 1)])

    def test_recapture_document_should_stop_bricht_ab_ohne_datei_zu_aendern(self):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        path = "test_recapture_abbruch.pdf"
        self._erzeuge_scan_pdf_mit_kaputter_ocr_ebene(path)
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))
        with open(path, "rb") as f:
            bytes_vorher = f.read()

        erfolg, meldung, seiten = PDFHandler.recapture_document(
            path, "irgendein/pfad", should_stop=lambda: True)

        self.assertFalse(erfolg)
        self.assertEqual(seiten, 0)
        self.assertIn("Abgebrochen", meldung)
        with open(path, "rb") as f:
            self.assertEqual(f.read(), bytes_vorher)

    @patch('PIL.ImageTk.PhotoImage')
    def test_get_preview_image(self, mock_photo_image):
        """ ---> NEU: Testet die Vorschau-Erstellung, ohne ein echtes GUI-Fenster zu benötigen """
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
            
        # Wir mocken Tkinter.PhotoImage, weil der Test sonst crasht (es existiert ja keine GUI hier)
        mock_photo_image.return_value = "MockedImageTk"
        
        # Die Methode gibt ein Tuple zurück: (photo, zoom_pct, total_pages, start_page)
        result = PDFHandler.get_preview_image(self.test_pdf, 800, 600)
        
        # Sicherstellen, dass überhaupt etwas zurückkam
        self.assertIsNotNone(result)
        
        # Das Tuple entpacken
        img, zoom, total, start = result
        
        # Jetzt testen wir nur das entpackte Bild-Objekt
        self.assertEqual(img, "MockedImageTk", "Die Vorschaugenerierung lieferte nicht das erwartete Bild-Objekt zurück.")


class TestDatumsSuchformen(unittest.TestCase):
    """Datums-Marker: Suchformen inkl. der OCR-typischen Varianten ohne Leerzeichen (30.08.2026)."""

    def test_numerische_und_ausgeschriebene_formen(self):
        formen = PDFHandler.datums_suchformen("2020-02-03")
        for erwartet in ("03.02.2020", "3.2.2020", "03.02.20", "3. Februar 2020", "Februar 2020"):
            self.assertIn(erwartet, formen)

    def test_zusammengeklebte_ocr_formen(self):
        formen = PDFHandler.datums_suchformen("2020-02-03")
        self.assertIn("Februar2020", formen)
        self.assertIn("3.Februar2020", formen)

    def test_ungueltiges_datum_liefert_leere_liste(self):
        self.assertEqual(PDFHandler.datums_suchformen("kein Datum"), [])
        self.assertEqual(PDFHandler.datums_suchformen(None), [])

    def test_treffer_in_echter_ocr_textebene(self):
        """Nachstellung des Live-Falls: PyMuPDF findet die geklebte Form, wenn sie in der Suchliste steht."""
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Seite 1 3:*Februar2020 Ihre Stromrechnung")
        treffer = [f for f in PDFHandler.datums_suchformen("2020-02-03") if page.search_for(f)]
        doc.close()
        self.assertEqual(treffer, ["Februar2020"])


class TestMarkerBoxenBereinigen(unittest.TestCase):
    """T4.9: 'Mai 2026' liegt in '12. Mai 2026' - nur ein Marker, nicht zwei übereinander."""

    def test_enthaltene_box_faellt_weg(self):
        import fitz
        gross = fitz.Rect(100, 100, 220, 112)   # "12. Mai 2026"
        klein = fitz.Rect(130, 100, 220, 112)   # "Mai 2026" darin
        self.assertEqual(PDFHandler.marker_boxen_bereinigen([klein, gross]), [gross])

    def test_getrennte_boxen_bleiben(self):
        import fitz
        a = fitz.Rect(100, 100, 160, 112)
        b = fitz.Rect(100, 300, 160, 312)   # gleiches Datum weiter unten (z.B. Kopf + Fußzeile)
        self.assertEqual(PDFHandler.marker_boxen_bereinigen([a, b]), [a, b])

    def test_leichte_ueberlappung_bleibt(self):
        import fitz
        a = fitz.Rect(100, 100, 160, 112)
        b = fitz.Rect(150, 100, 210, 112)   # nur 10 von 60 Punkten überdeckt
        self.assertEqual(len(PDFHandler.marker_boxen_bereinigen([a, b])), 2)

    def test_leere_und_entartete_boxen(self):
        import fitz
        self.assertEqual(PDFHandler.marker_boxen_bereinigen([]), [])
        self.assertEqual(PDFHandler.marker_boxen_bereinigen([fitz.Rect(1, 1, 1, 1)]), [])

    def test_echte_seite_liefert_einen_marker(self):
        """Live-Nachstellung: ausgeschriebenes Datum ergibt nach der Bereinigung genau eine Box."""
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Musterstadt, den 12. Mai 2026")
        boxen = [r for f in PDFHandler.datums_suchformen("2026-05-12") for r in page.search_for(f)]
        doc.close()
        self.assertGreaterEqual(len(boxen), 2)   # "12. Mai 2026" und "Mai 2026"
        self.assertEqual(len(PDFHandler.marker_boxen_bereinigen(boxen)), 1)


class TestSchreibenBeiDateisperre(unittest.TestCase):
    """
    Live-Fund 08.09.2026 (FALLSTRICKE #60): PDF in der Anzeige offen, Tag-Hygiene schreibt -
    WinError 32, und die halbfertige '...pdf.tmp' blieb liegen und tauchte in der Dokumentenliste auf.
    """

    def setUp(self):
        import tempfile
        import shutil
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        self.ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ordner, ignore_errors=True)
        self.pdf = os.path.join(self.ordner, "gesperrt.pdf")
        import fitz
        doc = fitz.open()
        doc.new_page()
        doc.set_metadata({"title": "Alt", "keywords": "A"})
        doc.save(self.pdf)
        doc.close()

    def test_temp_datei_bleibt_bei_sperre_nicht_liegen(self):
        with patch.object(PDFHandler, "SCHREIB_WARTEZEIT_S", 0.01), \
                patch.object(PDFHandler, "ersetze_datei", side_effect=PermissionError(32, "gesperrt")):
            erfolg, _msg = PDFHandler.save_metadata(self.pdf, "Neu", "B", still=True)
        self.assertFalse(erfolg)
        self.assertFalse(os.path.exists(self.pdf + ".tmp"), "Temp-Datei blieb liegen")
        self.assertEqual(PDFHandler.get_metadata(self.pdf)["title"], "Alt")   # Original unversehrt

    def test_kurze_sperre_wird_ueberbrueckt(self):
        echtes_replace = os.replace   # vor dem Patch sichern - der Patch trifft das geteilte os-Modul
        versuche = []

        def replace_mit_einer_sperre(src, dst):
            versuche.append(1)
            if len(versuche) == 1:
                raise PermissionError(32, "gesperrt")
            echtes_replace(src, dst)

        with patch.object(PDFHandler, "SCHREIB_WARTEZEIT_S", 0.01), \
                patch("os.replace", side_effect=replace_mit_einer_sperre):
            erfolg, _msg = PDFHandler.save_metadata(self.pdf, "Neu", "B", still=True)
        self.assertTrue(erfolg)
        self.assertEqual(len(versuche), 2)
        self.assertEqual(PDFHandler.get_metadata(self.pdf)["title"], "Neu")


class TestTextebeneWortbreite(unittest.TestCase):
    """Neu-Erfassen: das unsichtbare Wort muss das erkannte Wort-Rechteck in der Breite füllen (Marker-Rahmen)."""

    def test_wort_fuellt_rechteck_in_der_breite(self):
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        # Wort-Box, wie sie Tesseract für ein breit gedrucktes "18.11.2019" liefern könnte
        x0, y0, x1, y1 = 100.0, 100.0, 190.0, 112.0
        streckung = PDFHandler._textebene_wort_einfuegen(page, x0, y0, x1, y1, "18.11.2019")
        self.assertGreater(streckung, 1.0)   # Helvetica wäre schmaler als 90pt -> gestreckt
        treffer = page.search_for("18.11.2019")
        doc.close()
        self.assertEqual(len(treffer), 1)
        self.assertAlmostEqual(treffer[0].x0, x0, delta=1.5)
        self.assertAlmostEqual(treffer[0].x1, x1, delta=1.5)

    def test_schmales_rechteck_wird_gestaucht(self):
        import fitz
        doc = fitz.open()
        page = doc.new_page()
        streckung = PDFHandler._textebene_wort_einfuegen(page, 100, 100, 130, 112, "Beitragsrechnung")
        treffer = page.search_for("Beitragsrechnung")
        doc.close()
        self.assertLess(streckung, 1.0)
        self.assertEqual(len(treffer), 1)
        self.assertAlmostEqual(treffer[0].x1, 130, delta=1.5)


class TestTextqualitaetSpalte(unittest.TestCase):
    def _pdf(self, text):
        import fitz
        pfad = os.path.join(tempfile.mkdtemp(prefix="kid_tq_"), "t.pdf")
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), text)
        doc.save(pfad)
        doc.close()
        return pfad

    def test_sauberer_text_hohe_qualitaet(self):
        pfad = self._pdf("Beitragsrechnung Privatschutz-Versicherung für das laufende Jahr")
        self.assertEqual(PDFHandler.get_textqualitaet(pfad), 100)

    def test_kauderwelsch_niedrige_qualitaet(self):
        pfad = self._pdf("Vcnlehcrt Rcinheiltgcbot 6umaq3jSjaA znq3S}eAUd Vcfsichctt Bcrtrgsrchnng")
        wert = PDFHandler.get_textqualitaet(pfad)
        self.assertIsNotNone(wert)
        self.assertLess(wert, 50)

    def test_ohne_text_none(self):
        pfad = self._pdf("")
        self.assertIsNone(PDFHandler.get_textqualitaet(pfad))
        self.assertIsNone(PDFHandler.get_textqualitaet(pfad + ".fehlt.pdf"))


class TestSuchtrefferMarker(unittest.TestCase):
    """Suchtreffer im Dokument markieren (11.09.2026): Boxen je Seite, erste Trefferseite, Zählung."""

    @classmethod
    def setUpClass(cls):
        if not PDFHandler.is_supported():
            raise unittest.SkipTest("PyMuPDF nicht installiert.")
        import fitz
        from search_manager import SearchManager
        cls.matcher_fuer = staticmethod(SearchManager.build_matcher)
        cls.tmp = tempfile.mkdtemp()
        cls.pfad = os.path.join(cls.tmp, "kfz.pdf")
        doc = fitz.open()
        doc.new_page().insert_text((72, 100), "Vertragsunterlagen zu Ihrer Kfz-Versicherung")
        seite2 = doc.new_page()
        seite2.insert_text((72, 100), "Versicherungsnehmer: Peter Plesche")
        seite2.insert_text((72, 130), "Ihre Rechnnug vom 12.05.2026")
        seite2.insert_text((72, 160), "Beitrag Kfz-Versi cherung")
        doc.save(cls.pfad)
        doc.close()

    @classmethod
    def tearDownClass(cls):
        import shutil
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def _seite(self, nr):
        import fitz
        doc = fitz.open(self.pfad)
        self.addCleanup(doc.close)
        return doc.load_page(nr)

    def test_exakter_treffer_liefert_eine_box_um_das_wort(self):
        boxen = PDFHandler.suchtreffer_boxen(self._seite(1), ["plesche"], self.matcher_fuer)
        self.assertEqual(len(boxen), 1)
        wort = self._seite(1).search_for("Plesche")[0]
        self.assertAlmostEqual(boxen[0].x0, wort.x0, places=1)
        self.assertAlmostEqual(boxen[0].x1, wort.x1, places=1)

    def test_unscharfer_treffer_ueber_die_woerter_der_seite(self):
        """„rechnung" steht nicht auf der Seite, „Rechnnug" schon - derselbe Matcher wie in der Suche."""
        boxen = PDFHandler.suchtreffer_boxen(self._seite(1), ["rechnung"], self.matcher_fuer)
        self.assertEqual(len(boxen), 1)
        self.assertTrue(boxen[0].y0 > 100)   # zweite Textzeile (y=130), nicht der Name (y=100)

    def test_zerrissenes_wort_wird_als_paar_gefunden(self):
        """Ohne exakten Fund („Kfz-Versi cherung" ist zerrissen) werden benachbarte Wörter zusammen geprüft."""
        boxen = PDFHandler.suchtreffer_boxen(self._seite(1), ["kfz-versicherung"], self.matcher_fuer)
        self.assertEqual(len(boxen), 1, boxen)
        self.assertTrue(boxen[0].y0 > 140, boxen)   # y=160, nicht "Versicherungsnehmer" auf y=100

    def test_mehrere_begriffe_und_kein_treffer(self):
        boxen = PDFHandler.suchtreffer_boxen(self._seite(0), ["kfz", "vertragsunterlagen"], self.matcher_fuer)
        self.assertEqual(len(boxen), 2)
        self.assertEqual(PDFHandler.suchtreffer_boxen(self._seite(0), ["plesche"], self.matcher_fuer), [])
        self.assertEqual(PDFHandler.suchtreffer_boxen(self._seite(0), [], self.matcher_fuer), [])

    def test_ohne_matcher_nur_exakte_suche(self):
        self.assertEqual(PDFHandler.suchtreffer_boxen(self._seite(1), ["rechnung"]), [])
        self.assertEqual(len(PDFHandler.suchtreffer_boxen(self._seite(1), ["plesche"])), 1)

    def test_finde_treffer_seite(self):
        self.assertEqual(PDFHandler.finde_treffer_seite(self.pfad, ["plesche"], self.matcher_fuer), 1)
        self.assertEqual(PDFHandler.finde_treffer_seite(self.pfad, ["kfz"], self.matcher_fuer), 0)
        self.assertIsNone(PDFHandler.finde_treffer_seite(self.pfad, ["stadtwerke"], self.matcher_fuer))
        self.assertIsNone(PDFHandler.finde_treffer_seite(self.pfad, [], self.matcher_fuer))
        self.assertIsNone(PDFHandler.finde_treffer_seite(self.pfad, ["plesche"], self.matcher_fuer, max_seiten=1))
        self.assertIsNone(PDFHandler.finde_treffer_seite(os.path.join(self.tmp, "fehlt.pdf"), ["x"]))

    @patch('PIL.ImageTk.PhotoImage')
    def test_get_preview_image_zaehlt_treffer_und_bleibt_kompatibel(self, mock_photo):
        mock_photo.return_value = "Bild"
        boxen = []
        result = PDFHandler.get_preview_image(self.pfad, 800, 600, start_page=1,
                                              highlight_terms=["plesche", "rechnung"],
                                              matcher_fuer=self.matcher_fuer, treffer_boxen=boxen)
        self.assertEqual((result[0], result[2], result[3]), ("Bild", 2, 1))
        self.assertEqual(len(boxen), 2)
        # ohne Suchbegriffe: unverändertes Verhalten, Liste bleibt leer
        boxen = []
        PDFHandler.get_preview_image(self.pfad, 800, 600, treffer_boxen=boxen)
        self.assertEqual(boxen, [])


class TestPhraseAufSeite(unittest.TestCase):
    """Phrase in der Vorschau markieren, auch wenn die Texterkennung sie über den Zeilenumbruch zieht."""

    def test_phrase_ueber_zeilenumbruch(self):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        import fitz
        from search_manager import SearchManager
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 100), "Versicherungsnehmer: Peter")
        page.insert_text((72, 120), "Mustermann, Musterweg 1")
        page.insert_text((72, 160), "Mustermann, Peter")
        boxen = PDFHandler.suchtreffer_boxen(page, ["peter mustermann"], SearchManager.begriff_matcher)
        doc.close()
        self.assertTrue(boxen)
        self.assertTrue(all(b.y1 < 150 for b in boxen), boxen)   # "Mustermann, Peter" (y=160) NICHT markiert


class TestDokumentId(unittest.TestCase):
    """KID_ID (12.09.2026): eindeutige Dokument-ID im subject-Feld, einmal vergeben, nie überschrieben."""

    def test_subject_roundtrip_mit_id(self):
        subject = PDFHandler.build_kid_subject("2026-05-12", "", "Scan_0001.pdf", "3f2a9c1b7d5e")
        self.assertEqual(subject, "KID_DATE:2026-05-12|KID_NAME:Scan_0001.pdf|KID_ID:3f2a9c1b7d5e")
        self.assertEqual(PDFHandler.parse_kid_id(subject), "3f2a9c1b7d5e")
        self.assertEqual(PDFHandler.parse_kid_subject(subject), ("2026-05-12", ""))
        self.assertEqual(PDFHandler.parse_kid_id("KID_DATE:2026-05-12"), "")
        self.assertEqual(PDFHandler.parse_kid_id(""), "")

    def test_ensure_kid_id_vergibt_einmal_und_ueberlebt_speichern(self):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        import fitz
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        pfad = os.path.join(tmp, "doc.pdf")
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "Test")
        doc.save(pfad)
        doc.close()
        self.assertEqual(PDFHandler.get_metadata(pfad).get("KID_ID"), "")
        kid = PDFHandler.ensure_kid_id(pfad)
        self.assertRegex(kid, r"^[2-9A-HJKMNP-Z]{4}-[2-9A-HJKMNP-Z]{4}$")
        self.assertEqual(PDFHandler.ensure_kid_id(pfad), kid)             # zweiter Aufruf: dieselbe
        self.assertTrue(PDFHandler.write_custom_metadata(pfad, {"title": "Neu", "KID_DokumentenDatum": "2026-01-02"}, still=True))
        meta = PDFHandler.get_metadata(pfad)
        self.assertEqual(meta.get("KID_ID"), kid)                          # Speichern überschreibt nicht
        self.assertEqual(meta.get("KID_DokumentenDatum"), "2026-01-02")
        self.assertEqual(PDFHandler.get_document_info(pfad).get("KID_ID"), kid)
        self.assertEqual(PDFHandler.ensure_kid_id(os.path.join(tmp, "fehlt.pdf")), "")

    def _leeres_pdf(self, name="doc.pdf"):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        import fitz
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        pfad = os.path.join(tmp, name)
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "Test")
        doc.save(pfad)
        doc.close()
        return pfad

    def test_neue_id_ohne_verwechsler(self):
        ids = {PDFHandler.neue_kid_id() for _ in range(500)}
        self.assertGreater(len(ids), 495)                                  # zufällig, praktisch nie doppelt
        for kid in ids:
            self.assertRegex(kid, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
            self.assertFalse(set(kid) & set("01OIL"), kid)

    def test_speichern_vergibt_id_einmalig(self):
        # 25.10.2026: jedes Dokument bekommt seine ID beim ersten Speichern mit
        pfad = self._leeres_pdf()
        self.assertTrue(PDFHandler.write_custom_metadata(pfad, {"title": "Erster"}, still=True))
        kid = PDFHandler.get_metadata(pfad).get("KID_ID")
        self.assertRegex(kid, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.assertTrue(PDFHandler.write_custom_metadata(pfad, {"title": "Zweiter"}, still=True))
        self.assertEqual(PDFHandler.get_metadata(pfad).get("KID_ID"), kid)    # bleibt beim nächsten Speichern

    def test_ersetze_kid_id_gibt_kopie_neue_id(self):
        pfad = self._leeres_pdf()
        alt = PDFHandler.ensure_kid_id(pfad)
        self.assertTrue(PDFHandler.write_custom_metadata(pfad, {"title": "Bleibt", "KID_DokumentenDatum": "2026-03-04"}, still=True))
        neu = PDFHandler.ersetze_kid_id(pfad)
        self.assertRegex(neu, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")
        self.assertNotEqual(neu, alt)
        meta = PDFHandler.get_metadata(pfad)
        self.assertEqual(meta.get("KID_ID"), neu)
        self.assertEqual(meta.get("title"), "Bleibt")                       # Titel und Datum unverändert
        self.assertEqual(meta.get("KID_DokumentenDatum"), "2026-03-04")

    def test_alte_hex_id_bleibt_gueltig(self):
        pfad = self._leeres_pdf()
        self.assertTrue(PDFHandler.write_custom_metadata(pfad, {"KID_ID": "3f2a9c1b7d5e"}, still=True))
        self.assertTrue(PDFHandler.write_custom_metadata(pfad, {"title": "Neu"}, still=True))
        self.assertEqual(PDFHandler.get_metadata(pfad).get("KID_ID"), "3f2a9c1b7d5e")
        self.assertEqual(PDFHandler.ensure_kid_id(pfad), "3f2a9c1b7d5e")


class TestKidAbsender(unittest.TestCase):
    """KID_ABSENDER (27.10.2026, Ablage-Gedächtnis): gelesener Absender im subject-Feld, überschreibbar."""

    def test_subject_roundtrip(self):
        subject = PDFHandler.build_kid_subject("2026-05-12", "", "", "K7M4-Q2XP", "Stadtwerke Musterstadt: Kundenservice")
        self.assertEqual(subject, "KID_DATE:2026-05-12|KID_ID:K7M4-Q2XP|KID_ABSENDER:Stadtwerke Musterstadt: Kundenservice")
        self.assertEqual(PDFHandler.parse_kid_absender(subject), "Stadtwerke Musterstadt: Kundenservice")
        self.assertEqual(PDFHandler.parse_kid_id(subject), "K7M4-Q2XP")
        self.assertEqual(PDFHandler.parse_kid_absender("KID_DATE:2026-05-12"), "")
        self.assertEqual(PDFHandler.bereinige_absender(" A |B\nC "), "A B C")

    def test_bleibt_beim_speichern_und_wird_ueberschrieben(self):
        if not PDFHandler.is_supported():
            self.skipTest("PyMuPDF nicht installiert.")
        import fitz
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp, ignore_errors=True))
        pfad = os.path.join(tmp, "doc.pdf")
        doc = fitz.open()
        doc.new_page()
        doc.save(pfad)
        doc.close()
        self.assertTrue(PDFHandler.write_custom_metadata(pfad, {"KID_Absender": "Gentilia | AG"}, still=True))
        self.assertEqual(PDFHandler.get_metadata(pfad)["KID_Absender"], "Gentilia AG")
        self.assertTrue(PDFHandler.write_custom_metadata(pfad, {"title": "Neu"}, still=True))
        self.assertEqual(PDFHandler.get_metadata(pfad)["KID_Absender"], "Gentilia AG")   # normales Speichern
        self.assertTrue(PDFHandler.write_custom_metadata(pfad, {"KID_Absender": ""}, still=True))
        self.assertEqual(PDFHandler.get_metadata(pfad)["KID_Absender"], "Gentilia AG")   # leer löscht nicht
        self.assertTrue(PDFHandler.write_custom_metadata(pfad, {"KID_Absender": "Stadtwerke"}, still=True))
        self.assertEqual(PDFHandler.get_document_info(pfad)["KID_Absender"], "Stadtwerke")
