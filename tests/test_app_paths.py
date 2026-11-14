import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import app_paths


class TestAppPaths(unittest.TestCase):
    """Tests für die zentrale KID-Daten-Ordner-Pfadlogik und die Alt-Migration."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.master = os.path.join(self.tmp, "KID")
        os.makedirs(self.master)
        # LEBENSWICHTIG: migrate_legacy_layout() migriert u.a. die tags.json aus dem
        # AKTUELLEN Arbeitsverzeichnis. Ohne diesen chdir liefe die Migration gegen
        # das echte Projektverzeichnis und würde die ECHTE tags.json wegziehen —
        # genau das ist am 06.07.2026 passiert (siehe FALLSTRICKE #20).
        self._old_cwd = os.getcwd()
        os.chdir(self.tmp)

    def tearDown(self):
        os.chdir(self._old_cwd)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_pfade_liegen_neben_dem_hauptordner(self):
        data = app_paths.data_dir(self.master)
        self.assertEqual(data, os.path.join(self.tmp, "KID-Daten"))
        self.assertEqual(app_paths.trash_dir(self.master), os.path.join(data, "Papierkorb"))
        self.assertEqual(app_paths.log_path(self.master), os.path.join(data, "dokumenten_manager.log"))
        self.assertEqual(app_paths.tags_path(self.master), os.path.join(data, "tags.json"))
        self.assertEqual(app_paths.index_path(self.master), os.path.join(data, "index.sqlite"))

    def test_fallback_ohne_hauptordner(self):
        """Ohne gültigen Hauptordner landen Log und Tags wie früher im Arbeitsverzeichnis."""
        self.assertEqual(app_paths.log_path(""), "dokumenten_manager.log")
        self.assertEqual(app_paths.tags_path(None), "tags.json")

    def test_is_trash_path(self):
        trash = app_paths.trash_dir(self.master)
        os.makedirs(trash)

        # Absoluter Pfad in den Papierkorb
        self.assertTrue(app_paths.is_trash_path(os.path.join(trash, "x.pdf"), self.master))
        # Relativer Pfad, wie er in den Treeview-values steht (relpath zum Hauptordner)
        rel = os.path.relpath(os.path.join(trash, "x.pdf"), self.master)
        self.assertTrue(app_paths.is_trash_path(rel, self.master))
        # Groß-/Kleinschreibung (Windows)
        self.assertTrue(app_paths.is_trash_path(os.path.join(trash, "x.pdf").upper(), self.master))
        # Normale Dokumente sind KEIN Papierkorb
        self.assertFalse(app_paths.is_trash_path(os.path.join(self.master, "A", "x.pdf"), self.master))
        # Ein normaler Unterordner, der zufällig "Papierkorb" heißt, auch nicht
        self.assertFalse(app_paths.is_trash_path(os.path.join(self.master, "Papierkorb", "x.pdf"), self.master))
        # Leere/ungültige Eingaben crashen nicht
        self.assertFalse(app_paths.is_trash_path("", self.master))
        self.assertFalse(app_paths.is_trash_path("x.pdf", ""))

    def test_migration_zieht_altbestaende_um(self):
        # Alt-Layout aufbauen: Papierkorb + Log neben dem Hauptordner
        old_trash = os.path.join(self.tmp, "KID-Papierkorb")
        os.makedirs(old_trash)
        with open(os.path.join(old_trash, "geloescht.pdf"), "w") as f:
            f.write("x")
        with open(os.path.join(self.tmp, "dokumenten_manager.log"), "w") as f:
            f.write("log")

        actions = app_paths.migrate_legacy_layout(self.master)

        self.assertEqual(len(actions), 2)  # Papierkorb + Log (keine tags.json im CWD-Test)
        self.assertTrue(os.path.exists(os.path.join(app_paths.trash_dir(self.master), "geloescht.pdf")))
        self.assertTrue(os.path.exists(os.path.join(app_paths.data_dir(self.master), "dokumenten_manager.log")))
        self.assertFalse(os.path.exists(old_trash))

    def test_migration_ueberschreibt_nie(self):
        """Existiert das Ziel bereits, bleibt der Altbestand unangetastet."""
        old_trash = os.path.join(self.tmp, "KID-Papierkorb")
        os.makedirs(old_trash)
        os.makedirs(app_paths.trash_dir(self.master))  # Ziel existiert schon

        actions = app_paths.migrate_legacy_layout(self.master)

        self.assertEqual(actions, [])
        self.assertTrue(os.path.exists(old_trash))  # Alt bleibt liegen

    def test_migration_ohne_altbestand_ist_leer(self):
        actions = app_paths.migrate_legacy_layout(self.master)
        self.assertEqual(actions, [])
        self.assertTrue(os.path.isdir(app_paths.data_dir(self.master)))  # Ordner wird trotzdem angelegt


if __name__ == "__main__":
    unittest.main()


class TestEnsureDefaultFile(unittest.TestCase):
    """Mitgelieferte Vorlagen (tags_default.json) landen beim ersten Start im Arbeitsverzeichnis - auch aus der EXE."""

    def setUp(self):
        import tempfile
        import shutil
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.alt = os.getcwd()
        os.chdir(self.tmp)
        self.addCleanup(os.chdir, self.alt)

    def test_vorlage_wird_aus_dem_paket_kopiert(self):
        import sys
        quelle_dir = os.path.join(self.tmp, "paket")
        os.makedirs(quelle_dir)
        with open(os.path.join(quelle_dir, "tags_default.json"), "w", encoding="utf-8") as f:
            f.write("[]")
        with patch.object(sys, "_MEIPASS", quelle_dir, create=True):
            self.assertEqual(app_paths.bundled_default_path("tags_default.json"), os.path.join(quelle_dir, "tags_default.json"))
            self.assertTrue(app_paths.ensure_default_file("tags_default.json"))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "tags_default.json")))

    def test_vorhandene_datei_bleibt_unangetastet(self):
        with open("tags_default.json", "w", encoding="utf-8") as f:
            f.write('[{"text": "Eigene"}]')
        self.assertTrue(app_paths.ensure_default_file("tags_default.json"))
        with open("tags_default.json", encoding="utf-8") as f:
            self.assertIn("Eigene", f.read())

    def test_ohne_paketkopie_false(self):
        self.assertFalse(app_paths.ensure_default_file("gibt_es_nicht.json"))

    def test_tessdata_neben_der_exe_hat_vorrang_vor_der_eingebetteten_kopie(self):
        import sys
        paket = os.path.join(self.tmp, "paket")
        os.makedirs(os.path.join(paket, "tessdata"))
        exe_dir = os.path.join(self.tmp, "exe")
        os.makedirs(exe_dir)
        with patch.object(sys, "_MEIPASS", paket, create=True), \
                patch.object(sys, "frozen", True, create=True), \
                patch.object(sys, "executable", os.path.join(exe_dir, "DokumentenManager.exe")):
            self.assertEqual(app_paths.app_dir(), exe_dir)
            # Nichts neben der EXE -> eingebettete Kopie
            self.assertEqual(app_paths.tessdata_dir(), os.path.join(paket, "tessdata"))
            # Eigener Ordner neben der EXE gewinnt
            os.makedirs(os.path.join(exe_dir, "tessdata"))
            self.assertEqual(app_paths.tessdata_dir(), os.path.join(exe_dir, "tessdata"))

    def test_ausgelieferte_vorlage_ist_gueltig_und_hat_kategorien(self):
        import json
        with open(app_paths.bundled_default_path("tags_default.json"), encoding="utf-8") as f:
            daten = json.load(f)
        kategorien = [n["text"] for n in daten if n.get("is_structural")]
        self.assertGreaterEqual(len(kategorien), 6)
        self.assertIn("Dokumentart", kategorien)
        texte = []

        def walk(nodes):
            for n in nodes:
                texte.append(n["text"].lower())
                walk(n.get("children", []))
        walk(daten)
        self.assertEqual(len(texte), len(set(texte)), "Tag-Namen in der Vorlage müssen eindeutig sein")
