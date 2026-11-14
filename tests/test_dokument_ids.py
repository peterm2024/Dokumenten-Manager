"""Tests für das Werkzeug „Dokument-IDs vergeben“ (tools/dokument_ids.py, 25.10.2026)."""

import unittest

from tools.dokument_ids import plane_id_vergabe


class TestPlaneIdVergabe(unittest.TestCase):

    def test_ohne_id_wird_vergeben(self):
        ohne, ersetzen = plane_id_vergabe([("b.pdf", ""), ("a.pdf", None), ("c.pdf", "K7M4-Q2XP")], {})
        self.assertEqual(ohne, ["a.pdf", "b.pdf"])
        self.assertEqual(ersetzen, [])

    def test_kopie_mit_doppelter_id_bekommt_neue_aelteste_behaelt(self):
        doks = [("Kopie.pdf", "K7M4-Q2XP"), ("Original.pdf", "K7M4-Q2XP"), ("Andere.pdf", "B53U-RNDX")]
        ohne, ersetzen = plane_id_vergabe(doks, {"Original.pdf": 100.0, "Kopie.pdf": 200.0, "Andere.pdf": 50.0})
        self.assertEqual(ohne, [])
        self.assertEqual(ersetzen, ["Kopie.pdf"])

    def test_drei_gleiche_und_gross_klein_egal(self):
        doks = [("a.pdf", "3f2a9c1b7d5e"), ("b.pdf", "3F2A9C1B7D5E"), ("c.pdf", "3f2a9c1b7d5e")]
        _, ersetzen = plane_id_vergabe(doks, {"a.pdf": 3.0, "b.pdf": 1.0, "c.pdf": 2.0})
        self.assertEqual(ersetzen, ["a.pdf", "c.pdf"])          # b.pdf ist die älteste

    def test_alles_eindeutig_nichts_zu_tun(self):
        self.assertEqual(plane_id_vergabe([("a.pdf", "K7M4-Q2XP"), ("b.pdf", "B53U-RNDX")], {}), ([], []))


if __name__ == "__main__":
    unittest.main()
