import os
import unittest
from unittest.mock import MagicMock

from tools.pdf_inspector import PDFInspectorWindow


class TestLoadDataReleasesFileHandle(unittest.TestCase):
    """
    Regressionstest: _load_data() muss die geöffnete PDF-Datei IMMER wieder
    freigeben, auch wenn mitten im Lesen (Metadaten/XMP/Fonts/Text) eine Exception
    auftritt - sonst blockiert ein offen gebliebenes OS-Dateihandle spätere
    Verschieben/Löschen/Wiederherstellen-Operationen mit "[WinError 32] wird von
    einem anderen Prozess verwendet", solange der Inspektor offen bleibt.
    """

    def setUp(self):
        import fitz
        self.path = "test_inspector_leak.pdf"
        doc = fitz.open()
        doc.new_page()
        doc.save(self.path)
        doc.close()
        self.addCleanup(lambda: os.path.exists(self.path) and os.remove(self.path))

    def _fake_window(self):
        fake = MagicMock()
        fake.pdf_path = self.path
        return fake

    def test_datei_ist_nach_erfolgreichem_laden_sofort_wieder_entsperrt(self):
        fake = self._fake_window()

        PDFInspectorWindow._load_data(fake)

        os.remove(self.path)  # wirft PermissionError/WinError 32, falls noch ein Handle offen wäre
        self.assertFalse(os.path.exists(self.path))

    def test_datei_ist_auch_nach_exception_waehrend_der_verarbeitung_wieder_entsperrt(self):
        fake = self._fake_window()
        # Simuliert einen Fehler mitten in der Verarbeitung (z.B. ein kaputtes
        # Metadatenfeld) - der EXAKTE Auslöseort ist für den Handle-Leak egal,
        # entscheidend ist nur: bleibt "doc" trotzdem offen?
        # 3. Aufruf ist der insert() der except-Klausel selbst (Fehlermeldung anzeigen) - muss glatt durchlaufen
        fake.txt_meta.insert.side_effect = [None, RuntimeError("simulierter Fehler mitten im Lesen"), None]

        PDFInspectorWindow._load_data(fake)

        os.remove(self.path)
        self.assertFalse(os.path.exists(self.path))


if __name__ == "__main__":
    unittest.main()
