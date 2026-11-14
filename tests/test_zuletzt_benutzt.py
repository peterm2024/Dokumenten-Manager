import json
import os
import shutil
import tempfile
import unittest

import app_paths
import zuletzt_benutzt
from config import Config


class TestZuletztBenutzt(unittest.TestCase):
    def setUp(self):
        self.basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.basis, True)
        self.sammlung = os.path.join(self.basis, "Sammlung")
        os.makedirs(self.sammlung)
        self.config = Config(os.path.join(self.basis, "settings.json"))

    def test_ohne_hauptordner_leer_und_nichts_gespeichert(self):
        self.assertEqual(zuletzt_benutzt.lade("", self.config), [])
        self.assertFalse(zuletzt_benutzt.speichere(os.path.join(self.basis, "fehlt"), ["Steuer"]))

    def test_speichern_und_laden(self):
        self.assertTrue(zuletzt_benutzt.speichere(self.sammlung, ["Steuer", "Arzt"]))
        self.assertTrue(os.path.exists(app_paths.zuletzt_benutzt_path(self.sammlung)))
        self.assertEqual(zuletzt_benutzt.lade(self.sammlung, self.config), ["Steuer", "Arzt"])

    def test_alte_liste_wird_einmal_uebernommen(self):
        """Die offene Sammlung übernimmt die alte Liste; danach ist sie aus der settings.json weg."""
        self.config.set("recent_tags", ["Steuer", "Arzt"])
        self.assertEqual(zuletzt_benutzt.lade(self.sammlung, self.config), ["Steuer", "Arzt"])
        self.assertNotIn("recent_tags", self.config.data)
        with open(self.config.filename, encoding="utf-8") as f:
            self.assertNotIn("recent_tags", json.load(f))
        # Eine zweite (neue) Sammlung beginnt leer
        zweite = os.path.join(self.basis, "Zweite")
        os.makedirs(zweite)
        self.assertEqual(zuletzt_benutzt.lade(zweite, self.config), [])
        self.assertEqual(zuletzt_benutzt.lade(self.sammlung, self.config), ["Steuer", "Arzt"])

    def test_vorhandene_datei_geht_vor_alter_liste(self):
        zuletzt_benutzt.speichere(self.sammlung, ["Arzt"])
        self.config.set("recent_tags", ["Steuer"])
        self.assertEqual(zuletzt_benutzt.lade(self.sammlung, self.config), ["Arzt"])

    def test_kaputte_datei_ergibt_leere_liste(self):
        pfad = app_paths.zuletzt_benutzt_path(self.sammlung)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, "w", encoding="utf-8") as f:
            f.write("{kaputt")
        self.assertEqual(zuletzt_benutzt.lade(self.sammlung), [])

    def test_vorne_einreihen(self):
        liste = ["A", "B", "C"]
        self.assertEqual(zuletzt_benutzt.vorne_einreihen(liste, ["C", "X"]), ["C", "X", "A", "B"])
        lang = [str(i) for i in range(10)]
        self.assertEqual(len(zuletzt_benutzt.vorne_einreihen(lang, ["neu"])), zuletzt_benutzt.MAX_EINTRAEGE)
        self.assertEqual(zuletzt_benutzt.vorne_einreihen(lang, ["neu"])[0], "neu")


if __name__ == "__main__":
    unittest.main()
