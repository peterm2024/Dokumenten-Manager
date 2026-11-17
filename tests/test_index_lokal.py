"""Index lokal je Rechner, wenn die Sammlung auf einem Netzlaufwerk liegt (Etappe 10 Schritt 6). Nur Musterdaten."""

import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import app_paths
import index_manager
from index_manager import IndexManager


class TestNetzlaufwerk(unittest.TestCase):
    def test_erkennung(self):
        self.assertTrue(app_paths.ist_netzlaufwerk(r"\\server\freigabe\Dokumente"))
        self.assertTrue(app_paths.ist_netzlaufwerk("//server/freigabe/Dokumente"))
        self.assertTrue(app_paths.ist_netzlaufwerk(r"\\?\UNC\server\freigabe\Dokumente"))
        self.assertFalse(app_paths.ist_netzlaufwerk(r"\\?\C:\Dokumente"))       # Langform eines lokalen Pfads
        self.assertFalse(app_paths.ist_netzlaufwerk(tempfile.gettempdir()))
        self.assertFalse(app_paths.ist_netzlaufwerk(""))

    def test_index_auf_dem_netzlaufwerk_liegt_lokal(self):
        with tempfile.TemporaryDirectory() as lokal, patch.dict(os.environ, {"LOCALAPPDATA": lokal}):
            pfad = app_paths.index_path(r"\\server\freigabe\Dokumente")
            self.assertTrue(pfad.startswith(os.path.join(lokal, "KID", "Index")))
            self.assertTrue(pfad.endswith("index.sqlite"))
            self.assertEqual(pfad, app_paths.index_path(r"\\SERVER\Freigabe\Dokumente\\"))   # gleiche Sammlung
            self.assertNotEqual(pfad, app_paths.index_path(r"\\server\andere\Dokumente"))     # gleicher Name, andere

    def test_eigene_platte_bleibt_beim_daten_ordner(self):
        with tempfile.TemporaryDirectory() as tmp:
            master = os.path.join(tmp, "Sammlung")
            os.makedirs(master)
            self.assertEqual(app_paths.index_path(master), os.path.join(tmp, "Sammlung-Daten", "index.sqlite"))


class TestUebernahme(unittest.TestCase):
    """Der erste lokale Index übernimmt den gemeinsamen, damit nicht jedes PDF neu gelesen werden muss."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.master = os.path.join(self.tmp, "Sammlung")
        os.makedirs(self.master)
        self.lokal = os.path.join(self.tmp, "lokal", "index.sqlite")
        self.app = MagicMock(master_folder=self.master)

    def _gemeinsamer_index(self):
        os.makedirs(app_paths.data_dir(self.master), exist_ok=True)
        con = sqlite3.connect(app_paths.geteilter_index_path(self.master))
        con.execute("CREATE TABLE probe (wert TEXT)")
        con.execute("INSERT INTO probe VALUES ('aus dem gemeinsamen Index')")
        con.commit()
        con.close()

    def test_erster_zugriff_kopiert_den_gemeinsamen(self):
        self._gemeinsamer_index()
        manager = IndexManager(self.app)
        with patch.object(index_manager.app_paths, "index_path", return_value=self.lokal):
            self.assertEqual(manager._index_pfad(self.master), self.lokal)
        con = sqlite3.connect(self.lokal)
        self.assertEqual(con.execute("SELECT wert FROM probe").fetchone()[0], "aus dem gemeinsamen Index")
        con.close()
        self.app.logger.info.assert_called_once()

    def test_kaputter_gemeinsamer_wird_nicht_uebernommen(self):
        os.makedirs(app_paths.data_dir(self.master))
        with open(app_paths.geteilter_index_path(self.master), "wb") as f:
            f.write(b"SQLite format 3\x00" + b"kaputt" * 200)
        self.assertFalse(index_manager.uebernimm_geteilten_index(self.master, self.lokal, self.app.logger))
        self.assertFalse(os.path.exists(self.lokal))
        self.assertFalse(os.path.exists(self.lokal + ".uebernahme"))
        self.app.logger.warning.assert_called_once()

    def test_ohne_gemeinsamen_oder_auf_eigener_platte_nichts_zu_tun(self):
        self.assertFalse(index_manager.uebernimm_geteilten_index(self.master, self.lokal))
        self._gemeinsamer_index()
        self.assertFalse(index_manager.uebernimm_geteilten_index(self.master, app_paths.geteilter_index_path(self.master)))


if __name__ == "__main__":
    unittest.main()
