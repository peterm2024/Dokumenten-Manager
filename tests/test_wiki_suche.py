"""Wiki von Hand, Bauschritt 2: Suche nach Belegen (tools/wiki_suche.py) ohne Fenster. Nur Musterdaten."""
import os
import shutil
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

import fitz

from pdf_handler import PDFHandler
from tools import wiki_suche as ws


def pdf(pfad, text):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(pfad)
    doc.close()


class TestSuche(unittest.TestCase):
    def setUp(self):
        self.sammlung = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.sammlung, True)
        os.makedirs(os.path.join(self.sammlung, "Fahrzeuge"))
        pdf(os.path.join(self.sammlung, "Fahrzeuge", "Zulassung.pdf"), "Amtl. Kennzeichen M-XY 123 VW Golf")
        pdf(os.path.join(self.sammlung, "Fahrzeuge", "Werkstatt.pdf"), "Inspektion Golf")
        pdf(os.path.join(self.sammlung, "Brief.pdf"), "Sehr geehrter Herr Mustermann")
        # ohne Index: die Live-Suche des Hauptfensters; die Ansicht „Mails ausblenden“ ist an
        self.app = types.SimpleNamespace(master_folder=self.sammlung, config={"use_index": False}, logger=MagicMock(),
                                         root=MagicMock(), use_ocr_var=types.SimpleNamespace(get=lambda: False),
                                         mails_ausblenden_var=types.SimpleNamespace(get=lambda: True))

    def rels(self, *a, **k):
        return sorted(t["rel_path"] for t in ws.suche(self.app, *a, **k))

    def test_wie_die_hauptsuche_mit_eigenem_inhalt_schalter(self):
        golf = [os.path.join("Fahrzeuge", "Werkstatt.pdf"), os.path.join("Fahrzeuge", "Zulassung.pdf")]
        self.assertEqual(self.rels("golf"), golf)                          # im Inhalt, obwohl das Hauptfenster aus hat
        self.assertEqual(self.rels("golf", inhalt=False), [])               # nur Titel, Tags, Dateiname
        self.assertEqual(self.rels("Zulassung", inhalt=False), [golf[1]])
        self.assertEqual(self.rels("golf m-xy"), [golf[1]])                 # mehrere Wörter = UND
        self.assertEqual(self.rels("Mustermnn"), ["Brief.pdf"])             # Tippfehler wie im Hauptfenster
        self.assertEqual(self.rels("  "), [])
        t = ws.suche(self.app, "brief", inhalt=False)[0]
        self.assertEqual((t["titel"], t["ordner"]), ("Brief.pdf", ""))
        self.assertRegex(t["datum"], r"^\d\d\.\d\d\.\d{4}$")

    def test_mails_werden_immer_mitgesucht(self):
        # Auch eine Mail kann etwas belegen - die Ansicht „Mails ausblenden“ im Hauptfenster gilt hier nicht
        echt = PDFHandler.get_metadata

        def als_mail(pfad):
            meta = dict(echt(pfad))
            if os.path.basename(pfad) == "Brief.pdf":
                meta["KID_Richtung"] = "ein"
            return meta
        with patch("search_manager.PDFHandler.get_metadata", side_effect=als_mail):
            self.assertEqual(self.rels("mustermann"), ["Brief.pdf"])

    def test_schalter_des_hauptfensters_bleiben_unberuehrt(self):
        ws.suche(self.app, "golf")
        self.assertFalse(self.app.use_ocr_var.get())
        self.assertTrue(self.app.mails_ausblenden_var.get())


class TestFundstellen(unittest.TestCase):
    def test_zeilen_mit_suchwoertern(self):
        text = "Kopf\nAmtl. Kennzeichen   M-XY 123\n\nFahrzeug: VW GOLF\n" + "x" * 300 + " golf\nEnde"
        z = ws.fundstellen(text, 'golf "m-xy 123"')
        self.assertEqual(z[:2], ["Amtl. Kennzeichen M-XY 123", "Fahrzeug: VW GOLF"])
        self.assertTrue(z[2].endswith("…") and len(z[2]) == ws.ZEILE_MAX)
        self.assertEqual(len(ws.fundstellen("golf\n" * 20, "golf")), ws.FUNDSTELLEN)
        self.assertEqual(ws.fundstellen(text, "gol*"), ["Fahrzeug: VW GOLF", z[2]])   # Platzhalter fällt weg
        self.assertEqual(ws.fundstellen(text, "audi"), [])
        self.assertEqual(ws.fundstellen("", "golf"), [])


if __name__ == "__main__":
    unittest.main()
