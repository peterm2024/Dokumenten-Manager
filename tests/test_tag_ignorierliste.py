"""Tests für die Ignorierliste der KI-Tag-Vorschläge (tag_ignorierliste.py)."""

import json
import os
import shutil
import tempfile
import unittest

import app_paths
import tag_ignorierliste


class TestTagIgnorierliste(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.master = os.path.join(self.tmp, "KID")
        os.makedirs(app_paths.data_dir(self.master))  # Daten-Ordner existiert im Betrieb immer
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_leer_ohne_datei(self):
        self.assertEqual(tag_ignorierliste.lade(self.master), set())

    def test_ergaenzen_und_laden(self):
        self.assertTrue(tag_ignorierliste.ergaenze(self.master, "Gebäudezählnung"))
        self.assertTrue(tag_ignorierliste.ergaenze(self.master, "Dokument"))
        self.assertEqual(tag_ignorierliste.lade(self.master), {"gebäudezählnung", "dokument"})
        # Groß/Klein zählt als Dublette - Datei behält einen Eintrag in Original-Schreibweise
        self.assertTrue(tag_ignorierliste.ergaenze(self.master, "DOKUMENT"))
        with open(app_paths.tags_ignoriert_path(self.master), encoding="utf-8") as f:
            liste = json.load(f)
        self.assertEqual(sorted(liste), ["Dokument", "Gebäudezählnung"])

    def test_leere_und_kaputte_eingaben(self):
        self.assertFalse(tag_ignorierliste.ergaenze(self.master, "  "))
        with open(app_paths.tags_ignoriert_path(self.master), "w", encoding="utf-8") as f:
            f.write("{kaputt")
        self.assertEqual(tag_ignorierliste.lade(self.master), set())
        self.assertTrue(tag_ignorierliste.ergaenze(self.master, "Neu"))
        self.assertEqual(tag_ignorierliste.lade(self.master), {"neu"})


    def test_entferne_und_lade_liste(self):
        """Nutzerwunsch 03.09.2026: Ignorierliste bearbeitbar - Einträge wieder freigeben."""
        tag_ignorierliste.ergaenze(self.master, "Zebra")
        tag_ignorierliste.ergaenze(self.master, "affe")
        self.assertEqual(tag_ignorierliste.lade_liste(self.master), ["affe", "Zebra"])
        self.assertTrue(tag_ignorierliste.entferne(self.master, "ZEBRA"))  # Groß/Klein egal
        self.assertEqual(tag_ignorierliste.lade_liste(self.master), ["affe"])
        self.assertEqual(tag_ignorierliste.lade(self.master), {"affe"})
        # nicht vorhandenes Tag zu entfernen ist kein Fehler
        self.assertTrue(tag_ignorierliste.entferne(self.master, "gibtsnicht"))


if __name__ == "__main__":
    unittest.main()
