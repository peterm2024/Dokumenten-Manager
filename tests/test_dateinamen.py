"""Tests für dateinamen.py (Tool 'Dateinamen aufräumen'): Vorschlag, Umbenennen mit Originalname, Wiederherstellen."""
import os
import shutil
import tempfile
import unittest

import dateinamen
from pdf_handler import PDFHandler

try:
    import fitz
    HAS_FITZ = True
except ImportError:  # pragma: no cover
    HAS_FITZ = False


class TestBereinigeDateiname(unittest.TestCase):
    def test_verbotene_zeichen_und_endung(self):
        self.assertEqual(dateinamen.bereinige_dateiname('Rech:nung/2024?'), "Rechnung2024.pdf")
        self.assertEqual(dateinamen.bereinige_dateiname("  Brief.PDF "), "Brief.PDF")
        self.assertEqual(dateinamen.bereinige_dateiname("Brief."), "Brief.pdf")

    def test_leer(self):
        self.assertEqual(dateinamen.bereinige_dateiname(""), "")
        self.assertEqual(dateinamen.bereinige_dateiname(':*?'), "")
        self.assertEqual(dateinamen.bereinige_dateiname(None), "")


class TestVorschlag(unittest.TestCase):
    def test_aus_datum_und_titel(self):
        meta = {"title": "Stromrechnung 2024", "KID_DokumentenDatum": "2024-02-20"}
        self.assertEqual(dateinamen.vorschlag_aus_metadaten(meta), "20240220_Stromrechnung 2024.pdf")

    def test_ohne_titel_oder_datum_kein_vorschlag(self):
        self.assertEqual(dateinamen.vorschlag_aus_metadaten({"title": "", "KID_DokumentenDatum": "2024-02-20"}), "")
        self.assertEqual(dateinamen.vorschlag_aus_metadaten({"title": "Brief", "KID_DokumentenDatum": ""}), "")
        self.assertEqual(dateinamen.vorschlag_aus_metadaten({"title": "Brief", "KID_DokumentenDatum": "2099-01-01"}), "")
        self.assertEqual(dateinamen.vorschlag_aus_metadaten({}), "")

    def test_datum_aus_dateiname_als_ersatz(self):
        """Ohne Dokumentdatum im PDF dient das Präfix des Dateinamens als Vorbelegung für den Vorschlag."""
        z = dateinamen.zeile_fuer(r"C:\x\20241215_scan.pdf", {"title": "Brief", "KID_DokumentenDatum": ""})
        self.assertEqual(z["datum"], "2024-12-15")
        self.assertEqual(z["vorschlag"], "20241215_Brief.pdf")
        z = dateinamen.zeile_fuer(r"C:\x\scan.pdf", {"title": "Brief", "KID_DokumentenDatum": ""})
        self.assertEqual((z["datum"], z["vorschlag"]), ("", ""))

    def test_titel_verdaechtig(self):
        """Peters Fall '20241215_l='n' =l': kaum Buchstaben -> Müll; OCR-Kauderwelsch -> Müll; normale Titel nicht."""
        self.assertTrue(dateinamen.titel_verdaechtig("20241215_l='n' =l"))
        self.assertTrue(dateinamen.titel_verdaechtig("463,8080"))
        self.assertTrue(dateinamen.titel_verdaechtig(""))
        self.assertTrue(dateinamen.titel_verdaechtig("y^ _nA_l -■' PSi _● _yylP±i£Jy"))
        self.assertTrue(dateinamen.titel_verdaechtig("Vcfsichctt Bcrtrgsrchnng"))
        self.assertFalse(dateinamen.titel_verdaechtig("Stromrechnung 2024"))
        self.assertFalse(dateinamen.titel_verdaechtig("Steuererklärung 2018 Zum Alten Fass 1 und 3"))
        self.assertFalse(dateinamen.titel_verdaechtig("20230627_Grundriss Hobbyraum"))

    def test_zeile_markiert_muell_titel(self):
        z = dateinamen.zeile_fuer(r"C:\x\20241215_l='n' =l.pdf", {"title": "20241215_l='n' =l", "KID_DokumentenDatum": "2024-12-01"})
        self.assertTrue(z["verdaechtig"])
        self.assertEqual(z["ki_titel"], "")
        self.assertEqual(dateinamen.baue_vorschlag(z["datum"], "Beitragsrechnung Kfz-Versicherung"),
                         "20241201_Beitragsrechnung Kfz-Versicherung.pdf")

    def test_zeile_mit_vorgegebenen_metadaten(self):
        z = dateinamen.zeile_fuer(r"C:\x\20240101_alt.pdf",
                                  {"title": "Brief", "KID_DokumentenDatum": "2024-02-20", "KID_Originalname": "scan.pdf"})
        self.assertEqual(z["name"], "20240101_alt.pdf")
        self.assertEqual(z["vorschlag"], "20240220_Brief.pdf")
        self.assertEqual(z["originalname"], "scan.pdf")


class TestBenenneUmMitAttrappen(unittest.TestCase):
    """Regeln ohne echte PDFs: Metadaten-Schreiber und Umbenennen werden mitprotokolliert."""

    def setUp(self):
        self.geschrieben = []
        self.umbenannt = []
        self.vorhanden = set()

    def _schreibe(self, pfad, daten):
        self.geschrieben.append((pfad, daten))
        return True

    def _umbenenne(self, alt, neu):
        self.umbenannt.append((alt, neu))

    def _existiert(self, pfad):
        return os.path.normcase(pfad) in {os.path.normcase(p) for p in self.vorhanden}

    def test_umbenennen_brennt_alten_namen_ein(self):
        neu, fehler = dateinamen.benenne_um(r"C:\s\scan_001.pdf", "20240220_Brief", self._schreibe, self._umbenenne, self._existiert)
        self.assertEqual(fehler, "")
        self.assertEqual(neu, r"C:\s\20240220_Brief.pdf")
        self.assertEqual(self.geschrieben, [(r"C:\s\scan_001.pdf", {"KID_Originalname": "scan_001.pdf"})])
        self.assertEqual(self.umbenannt, [(r"C:\s\scan_001.pdf", r"C:\s\20240220_Brief.pdf")])

    def test_zusatz_metadaten_kommen_mit(self):
        """KI-Titel wird im selben Schreibvorgang wie der Originalname ins PDF geschrieben."""
        dateinamen.benenne_um(r"C:\s\scan.pdf", "20241201_Brief.pdf", self._schreibe, self._umbenenne, self._existiert,
                              zusatz_metadaten={"title": "Brief"})
        self.assertEqual(self.geschrieben, [(r"C:\s\scan.pdf", {"title": "Brief", "KID_Originalname": "scan.pdf"})])

    def test_gleicher_name_tut_nichts(self):
        neu, fehler = dateinamen.benenne_um(r"C:\s\a.pdf", "a.pdf", self._schreibe, self._umbenenne, self._existiert)
        self.assertEqual((neu, fehler), (r"C:\s\a.pdf", ""))
        self.assertEqual(self.geschrieben, [])
        self.assertEqual(self.umbenannt, [])

    def test_konflikt_wird_gemeldet_nicht_umgangen(self):
        self.vorhanden.add(r"C:\s\b.pdf")
        neu, fehler = dateinamen.benenne_um(r"C:\s\a.pdf", "b.pdf", self._schreibe, self._umbenenne, self._existiert)
        self.assertEqual(neu, r"C:\s\a.pdf")
        self.assertIn("existiert bereits", fehler)
        self.assertEqual(self.geschrieben, [])   # nichts angefasst

    def test_nur_grossschreibung_anders_ist_erlaubt(self):
        self.vorhanden.add(r"C:\s\brief.pdf")   # Windows: exists() wäre True für die Datei selbst
        neu, fehler = dateinamen.benenne_um(r"C:\s\brief.pdf", "Brief.pdf", self._schreibe, self._umbenenne, self._existiert)
        self.assertEqual((neu, fehler), (r"C:\s\Brief.pdf", ""))

    def test_metadaten_fehler_verhindert_umbenennen(self):
        neu, fehler = dateinamen.benenne_um(r"C:\s\a.pdf", "b.pdf", lambda p, d: False, self._umbenenne, self._existiert)
        self.assertEqual(neu, r"C:\s\a.pdf")
        self.assertIn("nicht umbenannt", fehler)
        self.assertEqual(self.umbenannt, [])

    def test_leerer_name(self):
        neu, fehler = dateinamen.benenne_um(r"C:\s\a.pdf", "  ", self._schreibe, self._umbenenne, self._existiert)
        self.assertEqual(fehler, "Leerer Dateiname.")

    def test_wiederherstellen_mit_vorgabe(self):
        neu, fehler = dateinamen.stelle_wieder_her(r"C:\s\20240220_Brief.pdf", "scan_001.pdf", self._umbenenne, self._existiert)
        self.assertEqual((neu, fehler), (r"C:\s\scan_001.pdf", ""))

    def test_wiederherstellen_ohne_originalname(self):
        neu, fehler = dateinamen.stelle_wieder_her(r"C:\s\a.pdf", "", self._umbenenne, self._existiert)
        self.assertIn("Kein Originalname", fehler)
        self.assertEqual(self.umbenannt, [])

    def test_wiederherstellen_konflikt(self):
        self.vorhanden.add(r"C:\s\scan.pdf")
        neu, fehler = dateinamen.stelle_wieder_her(r"C:\s\a.pdf", "scan.pdf", self._umbenenne, self._existiert)
        self.assertIn("existiert bereits", fehler)


@unittest.skipUnless(HAS_FITZ, "PyMuPDF fehlt")
class TestEchtePdfs(unittest.TestCase):
    """Rundlauf mit echten Dateien: Originalname wird beim ERSTEN Umbenennen eingebrannt und überlebt das zweite."""

    def setUp(self):
        self.ordner = tempfile.mkdtemp(prefix="kid_dateinamen_")
        self.pfad = os.path.join(self.ordner, "scan_001.pdf")
        doc = fitz.open()
        doc.new_page().insert_text((72, 72), "Brief")
        doc.set_metadata({"title": "Brief an Peter", "subject": "KID_DATE:2024-02-20"})
        doc.save(self.pfad)
        doc.close()

    def tearDown(self):
        shutil.rmtree(self.ordner, ignore_errors=True)

    def test_rundlauf_umbenennen_und_wiederherstellen(self):
        zeile = dateinamen.zeile_fuer(self.pfad)
        self.assertEqual(zeile["vorschlag"], "20240220_Brief an Peter.pdf")
        self.assertEqual(zeile["originalname"], "")

        p1, fehler = dateinamen.benenne_um(self.pfad, zeile["vorschlag"])
        self.assertEqual(fehler, "")
        self.assertTrue(os.path.exists(p1))
        self.assertFalse(os.path.exists(self.pfad))
        self.assertEqual(PDFHandler.get_metadata(p1)["KID_Originalname"], "scan_001.pdf")

        # Zweites Umbenennen: Originalname bleibt der allererste
        p2, fehler = dateinamen.benenne_um(p1, "20240220_Ganz anders.pdf")
        self.assertEqual(fehler, "")
        self.assertEqual(PDFHandler.get_metadata(p2)["KID_Originalname"], "scan_001.pdf")
        self.assertEqual(PDFHandler.get_metadata(p2)["title"], "Brief an Peter")   # Titel unangetastet

        p3, fehler = dateinamen.stelle_wieder_her(p2)
        self.assertEqual(fehler, "")
        self.assertEqual(os.path.basename(p3), "scan_001.pdf")
        self.assertTrue(os.path.exists(p3))

    def test_sammle_pdfs(self):
        unter = os.path.join(self.ordner, "Unter")
        os.makedirs(unter)
        shutil.copy(self.pfad, os.path.join(unter, "tief.pdf"))
        open(os.path.join(self.ordner, "notiz.txt"), "w").close()
        flach = dateinamen.sammle_pdfs(self.ordner)
        self.assertEqual([os.path.basename(p) for p in flach], ["scan_001.pdf"])
        tief = dateinamen.sammle_pdfs(self.ordner, rekursiv=True)
        self.assertEqual(sorted(os.path.basename(p) for p in tief), ["scan_001.pdf", "tief.pdf"])
        ohne = dateinamen.sammle_pdfs(self.ordner, rekursiv=True, ist_papierkorb=lambda p: p.endswith("Unter"))
        self.assertEqual([os.path.basename(p) for p in ohne], ["scan_001.pdf"])
        self.assertEqual(dateinamen.sammle_pdfs(os.path.join(self.ordner, "gibtsnicht")), [])


if __name__ == "__main__":
    unittest.main()
