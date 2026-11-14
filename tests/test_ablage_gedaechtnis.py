import os
import unittest
from unittest.mock import MagicMock

import ablage_gedaechtnis
from ablage_gedaechtnis import Gedaechtnis

VKB = os.path.join("S - Z", "Versicherungskasse Musterland")
STADT = os.path.join("S - Z", "Stadt Musterstadt")


class TestSchluessel(unittest.TestCase):
    def test_rechtsformen_und_satzzeichen_fallen_weg(self):
        self.assertEqual(ablage_gedaechtnis.schluessel("Stadtwerke Musterstadt GmbH"), "stadtwerke musterstadt")
        self.assertEqual(ablage_gedaechtnis.schluessel("Bayerische Landesbrandversicherung AG"),
                         ablage_gedaechtnis.schluessel("Bayerische  Landesbrandversicherung Aktiengesellschaft"))
        self.assertEqual(ablage_gedaechtnis.schluessel("Dr. Müller & Co. KG"), "dr müller")
        self.assertEqual(ablage_gedaechtnis.schluessel(""), "")
        self.assertEqual(ablage_gedaechtnis.schluessel(None), "")


class TestGedaechtnis(unittest.TestCase):
    def test_eine_stimme_reicht_nicht(self):
        g = Gedaechtnis()
        g.stimme("Bayerische Landesbrandversicherung AG", VKB)
        self.assertIsNone(g.frage("Bayerische Landesbrandversicherung"))

    def test_zwei_stimmen_einig(self):
        g = Gedaechtnis()
        g.stimme("Bayerische Landesbrandversicherung AG", VKB)
        g.stimme("Bayerische Landesbrandversicherung", VKB)
        self.assertEqual(g.frage("Bayerische Landesbrandversicherung Aktiengesellschaft"), (VKB, 2, 2))

    def test_uneinig_unter_zwei_dritteln_gilt_nicht(self):
        g = Gedaechtnis()
        for ordner in (VKB, VKB, STADT, STADT):
            g.stimme("Landratsamt Musterstadt", ordner)
        self.assertIsNone(g.frage("Landratsamt Musterstadt"))        # 2 von 4 = 50 %
        g.stimme("Landratsamt Musterstadt", VKB)
        self.assertIsNone(g.frage("Landratsamt Musterstadt"))        # 3 von 5 = 60 %
        g.stimme("Landratsamt Musterstadt", VKB)
        self.assertIsNone(g.frage("Landratsamt Musterstadt"))        # 4 von 6 = 66,7 % - knapp unter 67 % (so gemessen)
        g.stimme("Landratsamt Musterstadt", VKB)
        self.assertEqual(g.frage("Landratsamt Musterstadt"), (VKB, 5, 7))  # 71 %

    def test_nur_exakter_schluessel(self):
        g = Gedaechtnis()
        g.stimme("Stadtwerke Musterstadt", STADT)
        g.stimme("Stadtwerke Musterstadt", STADT)
        self.assertIsNone(g.frage("Stadtwerke München"))
        self.assertIsNone(g.frage(""))

    def test_leeres_zaehlt_nicht(self):
        g = Gedaechtnis()
        g.stimme("", VKB)
        g.stimme("GmbH", VKB)      # bleibt nach dem Schlüssel nichts übrig
        g.stimme("Gentilia", "")
        self.assertEqual(len(g), 0)

    def test_eintraege_fuer_die_anzeige(self):
        g = Gedaechtnis()
        g.stimme("Stadtwerke Musterstadt GmbH", STADT)
        g.stimme("Stadtwerke Musterstadt", STADT)
        g.stimme("ADAC", VKB)
        self.assertEqual(g.eintraege(), [("ADAC", "adac", [(VKB, 1)]),
                                         ("Stadtwerke Musterstadt GmbH", "stadtwerke musterstadt", [(STADT, 2)])])


class TestBaue(unittest.TestCase):
    def test_nur_ablageziele_zaehlen(self):
        ablagen = [
            (os.path.join(VKB, "a.pdf"), "LBV"),
            (os.path.join(VKB, "b.pdf"), "LBV"),
            (os.path.join("0_Unsicher", "c.pdf"), "LBV"),
            (os.path.join("0_Posteingang", "d.pdf"), "LBV"),
            ("e.pdf", "LBV"),                                   # direkt im Hauptordner
        ]
        g = ablage_gedaechtnis.baue(ablagen, [VKB, STADT])
        self.assertEqual(g.frage("LBV"), (VKB, 2, 2))

    def test_gross_klein_des_ordners_egal(self):
        g = ablage_gedaechtnis.baue([(os.path.join(VKB.upper(), "a.pdf"), "LBV"),
                                     (os.path.join(VKB, "b.pdf"), "LBV")], [VKB])
        self.assertEqual(g.frage("LBV"), (VKB, 2, 2))

    def test_lade_faellt_bei_fehler_auf_leer_zurueck(self):
        index = MagicMock()
        index.ablage_absender.side_effect = RuntimeError("kaputt")
        logger = MagicMock()
        g = ablage_gedaechtnis.lade(index, [VKB], logger)
        self.assertEqual(len(g), 0)
        logger.warning.assert_called_once()
        self.assertEqual(len(ablage_gedaechtnis.lade(None, [VKB])), 0)


class TestZustand(unittest.TestCase):
    def test_zustand(self):
        g = Gedaechtnis()
        g.stimme("ADAC", VKB)
        self.assertEqual(g.zustand("ADAC"), "erst 1 Dokument")
        g.stimme("ADAC", STADT)
        self.assertEqual(g.zustand("ADAC"), "erst 1 Dokument")
        g.stimme("ADAC", STADT)
        self.assertEqual(g.zustand("ADAC"), "uneinig")     # 2 von 3
        self.assertEqual(g.zustand("Unbekannt"), "")


class TestAnsichtZeilen(unittest.TestCase):
    def test_geltende_zuerst_mehrere_ordner_mit_anzahl(self):
        from tools.gedaechtnis_ansicht import zeilen
        g = Gedaechtnis()
        g.stimme("ADAC", VKB)
        for ordner in (STADT, STADT, VKB):
            g.stimme("Stadt Musterstadt", ordner)
        g.stimme("Gentilia", VKB)
        g.stimme("Gentilia", VKB)
        self.assertEqual(zeilen(g), [
            ("Gentilia", VKB, "2", "gilt", "gentilia", []),
            ("ADAC", VKB, "1", "erst 1 Dokument", "adac", []),
            ("Stadt Musterstadt", STADT, "2 von 3", "uneinig", "stadt musterstadt", [(VKB, 1)]),   # 2 von 3 < 67 %
        ])


if __name__ == "__main__":
    unittest.main()
