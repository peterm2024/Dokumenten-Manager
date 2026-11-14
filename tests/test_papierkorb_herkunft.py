"""Tests für das Papierkorb-Gedächtnis (Herkunftsordner gelöschter Dateien)."""

import os
import tempfile
import unittest

import app_paths
import papierkorb_herkunft as ph


class TestPapierkorbHerkunft(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.master = os.path.join(self._tmp.name, "Sammlung")
        os.makedirs(os.path.join(self.master, "K", "Kehrmann"))
        self.korb = app_paths.trash_dir(self.master)
        os.makedirs(self.korb)

    def tearDown(self):
        self._tmp.cleanup()

    def test_merken_und_zurueck_in_den_herkunftsordner(self):
        quelle = os.path.join(self.master, "K", "Kehrmann", "a.pdf")
        im_korb = os.path.join(self.korb, "a.pdf")
        ph.merke(self.master, im_korb, quelle)
        self.assertEqual(ph.lade(self.master), {"a.pdf": os.path.join("K", "Kehrmann")})
        self.assertEqual(ph.zielordner(self.master, im_korb), os.path.join(os.path.abspath(self.master), "K", "Kehrmann"))
        ph.vergiss(self.master, im_korb)
        self.assertEqual(ph.lade(self.master), {})

    def test_ohne_eintrag_oder_ordner_weg_in_den_hauptordner(self):
        im_korb = os.path.join(self.korb, "b.pdf")
        self.assertEqual(ph.zielordner(self.master, im_korb), self.master)
        ph.merke(self.master, im_korb, os.path.join(self.master, "Weg", "b.pdf"))
        self.assertEqual(ph.zielordner(self.master, im_korb), self.master)

    def test_hauptordner_selbst_und_kaputte_datei(self):
        im_korb = os.path.join(self.korb, "c.pdf")
        ph.merke(self.master, im_korb, os.path.join(self.master, "c.pdf"))
        self.assertEqual(ph.lade(self.master)["c.pdf"], "")
        self.assertEqual(ph.zielordner(self.master, im_korb), self.master)
        with open(app_paths.papierkorb_herkunft_path(self.master), "w", encoding="utf-8") as f:
            f.write("{kaputt")
        self.assertEqual(ph.lade(self.master), {})

    def test_kein_ausbruch_aus_der_sammlung(self):
        im_korb = os.path.join(self.korb, "d.pdf")
        ph.merke(self.master, im_korb, os.path.join(self._tmp.name, "d.pdf"))   # außerhalb
        self.assertEqual(ph.zielordner(self.master, im_korb), self.master)


if __name__ == "__main__":
    unittest.main()
