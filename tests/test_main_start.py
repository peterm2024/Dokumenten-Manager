"""Startpunkt main.py: Die App arbeitet immer im Programmordner (FALLSTRICKE #102)."""
import os
import tempfile
import unittest
from unittest.mock import patch

import main


class TestStartordner(unittest.TestCase):
    def test_start_wechselt_vor_dem_aufbau_in_den_programmordner(self):
        """Wird die EXE mit fremdem Arbeitsverzeichnis gestartet (z. B. C:\\Windows\\System32), muss
        sie trotzdem ihre settings.json finden und darf das Protokoll nicht dorthin schreiben wollen."""
        alt = os.getcwd()
        self.addCleanup(os.chdir, alt)
        with tempfile.TemporaryDirectory() as programmordner, tempfile.TemporaryDirectory() as fremd:
            self.addCleanup(os.chdir, alt)
            os.chdir(fremd)
            beim_aufbau = []
            with patch("main.tk.Tk"), \
                    patch("main.DokumentenVerwaltung", side_effect=lambda root: beim_aufbau.append(os.getcwd())), \
                    patch("app_paths.app_dir", return_value=programmordner), \
                    patch("fehlerfaenger.absturz_protokoll_starten"), \
                    patch("einzelstart.belege", return_value=True):
                main.main()
            os.chdir(alt)   # sonst lässt Windows den Temp-Ordner nicht löschen
            self.assertEqual([os.path.realpath(programmordner)], [os.path.realpath(p) for p in beim_aufbau])


if __name__ == "__main__":
    unittest.main()
