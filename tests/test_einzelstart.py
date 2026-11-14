"""Zwei KID auf derselben Sammlung: zwei Vollautomatiken im selben Posteingang (ARCHITEKTUR_REVIEW.md, R3).

Die Sperre gilt zwischen Prozessen, darum prüfen echte Prozesse sie.
"""
import os
import subprocess
import sys
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock, patch

import einzelstart
import main

SRC = os.path.dirname(os.path.abspath(einzelstart.__file__))
PROBE = "import sys; sys.path.insert(0, sys.argv[1]); import einzelstart; print(einzelstart.belege(sys.argv[2]), flush=True)"
HALTE = PROBE + "; sys.stdin.read()"
# Der python.exe der .venv ist nur ein Starter: Ihn zu beenden träfe nicht sofort den Prozess, der die Sperre hält
PYTHON = getattr(sys, "_base_executable", sys.executable)


def _frag_anderen_prozess(sammlung):
    return subprocess.run([PYTHON, "-c", PROBE, SRC, sammlung], capture_output=True, text=True, timeout=60).stdout.strip()


class _Halter:
    """Ein zweiter Prozess, der die Sperre hält, bis er endet."""

    def __init__(self, sammlung):
        self.p = subprocess.Popen([PYTHON, "-c", HALTE, SRC, sammlung], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.antwort = self.p.stdout.readline().strip()

    def beende(self):
        self.p.stdin.close()
        self.p.stdout.close()
        self.p.wait(timeout=30)

    def toete(self):
        self.p.kill()
        self.p.stdin.close()
        self.p.stdout.close()
        self.p.wait(timeout=30)


class TestSperre(unittest.TestCase):
    def setUp(self):
        self.sammlung = os.path.join(tempfile.gettempdir(), f"KID-Test-Sperre-{os.getpid()}-{self.id()}")
        self.addCleanup(einzelstart.freigeben)

    def test_zweiter_prozess_bekommt_die_sammlung_nicht(self):
        self.assertTrue(einzelstart.belege(self.sammlung))
        self.assertEqual(_frag_anderen_prozess(self.sammlung), "False")

    def test_andere_sammlung_bleibt_frei(self):
        self.assertTrue(einzelstart.belege(self.sammlung))
        self.assertEqual(_frag_anderen_prozess(self.sammlung + "-andere"), "True")

    def test_schreibweise_des_pfads_zaehlt_nicht(self):
        self.assertTrue(einzelstart.belege(self.sammlung))
        self.assertEqual(_frag_anderen_prozess(self.sammlung.upper() + os.sep), "False")

    def test_wird_frei_wenn_der_halter_abstuerzt(self):
        h = _Halter(self.sammlung)
        self.assertEqual(h.antwort, "True")
        self.assertFalse(einzelstart.belege(self.sammlung))
        h.toete()
        self.assertTrue(einzelstart.belege(self.sammlung))

    def test_wird_frei_wenn_der_halter_endet(self):
        h = _Halter(self.sammlung)
        h.beende()
        self.assertTrue(einzelstart.belege(self.sammlung))

    def test_eigene_sammlung_erneut_belegen_geht(self):
        self.assertTrue(einzelstart.belege(self.sammlung))
        self.assertTrue(einzelstart.belege(self.sammlung))

    def test_wechsel_gibt_die_alte_sammlung_frei(self):
        self.assertTrue(einzelstart.belege(self.sammlung))
        self.assertTrue(einzelstart.belege(self.sammlung + "-neu"))
        self.assertEqual(_frag_anderen_prozess(self.sammlung), "True")
        self.assertEqual(_frag_anderen_prozess(self.sammlung + "-neu"), "False")

    def test_gescheiterter_wechsel_behaelt_die_alte_sammlung(self):
        ziel = self.sammlung + "-belegt"
        h = _Halter(ziel)
        self.addCleanup(h.beende)
        self.assertTrue(einzelstart.belege(self.sammlung))
        self.assertFalse(einzelstart.belege(ziel))
        self.assertEqual(_frag_anderen_prozess(self.sammlung), "False")


class TestFenster(unittest.TestCase):
    def test_findet_das_laufende_fenster_am_titelanfang(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        root.title(f"KID-Fenstertest {os.getpid()} v1.2.3 - dokument.pdf")
        root.update()
        self.assertTrue(einzelstart._finde_fenster(f"KID-Fenstertest {os.getpid()}"))
        self.assertIsNone(einzelstart._finde_fenster("KID-Fenster, das es nicht gibt"))


class TestStart(unittest.TestCase):
    def test_zweiter_start_baut_kein_fenster_auf(self):
        alt = os.getcwd()
        self.addCleanup(os.chdir, alt)
        with tempfile.TemporaryDirectory() as ordner:
            with patch("main.tk.Tk") as tk_fenster, patch("main.DokumentenVerwaltung") as gui, \
                    patch("app_paths.app_dir", return_value=ordner), \
                    patch("einzelstart.belege", return_value=False), \
                    patch("einzelstart.hole_nach_vorn") as nach_vorn:
                main.main()
            os.chdir(alt)
        gui.assert_not_called()
        nach_vorn.assert_called_once()
        tk_fenster.return_value.mainloop.assert_not_called()

    def test_erster_start_laeuft_normal(self):
        alt = os.getcwd()
        self.addCleanup(os.chdir, alt)
        with tempfile.TemporaryDirectory() as ordner:
            with patch("main.tk.Tk") as tk_fenster, patch("main.DokumentenVerwaltung") as gui, \
                    patch("app_paths.app_dir", return_value=ordner), \
                    patch("einzelstart.belege", return_value=True), \
                    patch("fehlerfaenger.absturz_protokoll_starten"):
                main.main()
            os.chdir(alt)
        gui.assert_called_once()
        tk_fenster.return_value.mainloop.assert_called_once()


class TestSammlungWechseln(unittest.TestCase):
    def test_belegte_sammlung_wird_nicht_geoeffnet(self):
        from folder_manager import FolderManager
        app = MagicMock()
        app.master_folder = "D:/Alt"
        fm = FolderManager(app)
        with patch("einzelstart.belege", return_value=False), patch("folder_manager.messagebox") as mb, \
                tempfile.TemporaryDirectory() as ziel:
            self.assertFalse(fm._sammlung_belegen(ziel))
            mb.showwarning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
