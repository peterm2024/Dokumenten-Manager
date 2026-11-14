import os
import shutil
import tempfile
import unittest
from datetime import datetime
from unittest.mock import MagicMock, patch

from tools.document_recapture import (
    DocumentRecaptureTool,
    baue_zusammenfassung,
    sicherungskopie_pfad,
    textqualitaet_prozent,
)


def _seite(typ):
    """Minimaler Seiten-Eintrag im Format von PDFHandler.classify_pages."""
    return {"seite": 1, "typ": typ, "bild_abdeckung": 1.0,
            "sichtbarer_text": False, "unsichtbarer_text": False}


class TestBaueZusammenfassung(unittest.TestCase):
    """Tests für die (Tkinter-freie) Zusammenfassungslogik des Neu-Erfassen-Tools."""

    def test_geschuetztes_pdf_wird_verweigert(self):
        for schutz in ("verschlüsselt", "schreibgeschützt", "signiert"):
            text = baue_zusammenfassung([_seite("scan")], schutz)
            self.assertIn(schutz, text)
            self.assertIn("verweigert", text)

    def test_signiert_sperrt_auch_bei_scan_seiten(self):
        """Signierte PDFs verweigert das Tool KOMPLETT (KONZEPT_PDF_ARTEN.md 1.5) - auch wenn alle Seiten Scans sind."""
        text = baue_zusammenfassung([_seite("scan"), _seite("scan")], "signiert")
        self.assertNotIn("würden neu erfasst", text)

    def test_nicht_analysierbar(self):
        text = baue_zusammenfassung([], None)
        self.assertIn("nicht analysiert", text)

    def test_keine_scan_seiten(self):
        text = baue_zusammenfassung([_seite("digital"), _seite("misch")], None)
        self.assertIn("Keine der 2 Seiten", text)

    def test_zaehlt_nur_scan_seiten(self):
        pages = [_seite("scan"), _seite("digital"), _seite("scan"), _seite("leer")]
        text = baue_zusammenfassung(pages, None)
        self.assertIn("2 von 4 Seiten", text)


class TestTextqualitaetProzent(unittest.TestCase):
    """Tests für den Kauderwelsch-Qualitätsindikator (gleiche Heuristik/Kalibrierung wie tools.title_cleanup.looks_garbled)."""

    def test_sauberer_text_liefert_100(self):
        wert = textqualitaet_prozent("Beitragsrechnung Privatschutz-Versicherung für das laufende Jahr")
        self.assertEqual(wert, 100)

    def test_kauderwelsch_liefert_wert_unter_100(self):
        wert = textqualitaet_prozent("die Bayerische Vcnlehcrt nach dem Rcinheiltgcbot")
        self.assertIsNotNone(wert)
        self.assertLess(wert, 100)

    def test_leerer_text_liefert_none(self):
        self.assertIsNone(textqualitaet_prozent(""))

    def test_nur_kurze_woerter_liefert_none(self):
        """Kurze Wörter (< GARBLED_MIN_WORD_LEN) sind nicht bewertbar - keine falsche 100%-Sicherheit vortäuschen."""
        self.assertIsNone(textqualitaet_prozent("und mit da"))

    def test_gemischter_text_liegt_zwischen_0_und_100(self):
        text = "Versicherung Rechnung Betrag " + "Vcfsichctt"
        wert = textqualitaet_prozent(text)
        self.assertTrue(0 < wert < 100, wert)


class TestOnSelectionChanged(unittest.TestCase):
    """Tests für das Live-Update des offenen Analyse-Fensters bei Dateiwechsel in der Hauptliste (wie beim PDF-Inspektor)."""

    def setUp(self):
        self.tool = DocumentRecaptureTool()
        self.tool.window = MagicMock()
        self.tool.window.winfo_exists.return_value = True
        self.context = MagicMock()

    def test_wechselt_bei_genau_einer_pdf_auswahl(self):
        self.context.selected_files = ["C:/KID/a.pdf"]
        self.tool.on_selection_changed(self.context)
        self.tool.window.wechsle_dokument.assert_called_once_with("C:/KID/a.pdf")

    def test_ignoriert_mehrfachauswahl(self):
        self.context.selected_files = ["C:/KID/a.pdf", "C:/KID/b.pdf"]
        self.tool.on_selection_changed(self.context)
        self.tool.window.wechsle_dokument.assert_not_called()

    def test_ignoriert_leere_auswahl(self):
        self.context.selected_files = []
        self.tool.on_selection_changed(self.context)
        self.tool.window.wechsle_dokument.assert_not_called()

    def test_ignoriert_nicht_pdf_datei(self):
        self.context.selected_files = ["C:/KID/notiz.txt"]
        self.tool.on_selection_changed(self.context)
        self.tool.window.wechsle_dokument.assert_not_called()

    def test_ohne_offenes_fenster_kein_crash(self):
        self.tool.window = None
        self.context.selected_files = ["C:/KID/a.pdf"]
        self.tool.on_selection_changed(self.context)  # darf nicht crashen


class TestSicherungskopiePfad(unittest.TestCase):
    """Tests für den Sicherungskopie-Zielpfad im Papierkorb vor dem Neu-Erfassen."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_baut_pfad_mit_zeitstempel_suffix_im_papierkorb(self):
        with patch("tools.document_recapture.app_paths.trash_dir", return_value=self.tmp):
            pfad = sicherungskopie_pfad(r"C:\KID\Ordner\dok.pdf", r"C:\KID")

        self.assertEqual(os.path.dirname(pfad), self.tmp)
        self.assertTrue(os.path.basename(pfad).startswith("dok_vor_neuerfassung_"))
        self.assertTrue(pfad.endswith(".pdf"))

    def test_haengt_zaehler_bei_kollision_an(self):
        """Zwei Läufe innerhalb derselben Sekunde dürfen sich nicht gegenseitig überschreiben."""
        fester_zeitpunkt = datetime(2026, 7, 13, 10, 30, 0)
        with patch("tools.document_recapture.app_paths.trash_dir", return_value=self.tmp), \
             patch("tools.document_recapture.datetime") as mock_dt:
            mock_dt.now.return_value = fester_zeitpunkt
            erster = sicherungskopie_pfad(r"C:\KID\dok.pdf", r"C:\KID")
            open(erster, "wb").close()
            zweiter = sicherungskopie_pfad(r"C:\KID\dok.pdf", r"C:\KID")

        self.assertNotEqual(erster, zweiter)
        self.assertTrue(zweiter.endswith("_1.pdf"))


if __name__ == "__main__":
    unittest.main()
