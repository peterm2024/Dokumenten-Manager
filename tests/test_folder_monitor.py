"""
Tests für folder_monitor.py: Welche Watchdog-Ereignisse lösen den GUI-Abgleich aus?
Ein bloßes „Ordner geändert" (DirModifiedEvent) darf es NICHT (FALLSTRICKE #68: doppeltes
Neulesen des Posteingangs nach jeder Vollautomatik-Ablage).
"""

import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock

from watchdog.events import (DirCreatedEvent, DirDeletedEvent, DirModifiedEvent, FileCreatedEvent,
                             FileDeletedEvent, FileModifiedEvent, FileMovedEvent)

import folder_monitor


class TestSyncHandler(unittest.TestCase):
    def setUp(self):
        self.callback = MagicMock()
        self.handler = folder_monitor.SyncHandler(self.callback)

    def test_datei_ereignisse_loesen_abgleich_aus(self):
        for ereignis in (FileCreatedEvent("C:/x/a.pdf"), FileModifiedEvent("C:/x/a.pdf"),
                         FileDeletedEvent("C:/x/a.pdf"), FileMovedEvent("C:/x/a.pdf", "C:/y/a.pdf")):
            self.callback.reset_mock()
            self.handler.on_any_event(ereignis)
            self.assertEqual(self.callback.call_count, 1, ereignis)

    def test_ordner_anlegen_und_loeschen_loesen_abgleich_aus(self):
        for ereignis in (DirCreatedEvent("C:/x/neu"), DirDeletedEvent("C:/x/alt")):
            self.callback.reset_mock()
            self.handler.on_any_event(ereignis)
            self.assertEqual(self.callback.call_count, 1, ereignis)

    def test_bloss_ordner_geaendert_wird_ignoriert(self):
        self.handler.on_any_event(DirModifiedEvent("C:/x/0_Posteingang"))
        self.callback.assert_not_called()

    def test_bloss_gelesene_datei_wird_ignoriert(self):
        # FALLSTRICKE #106: Windows meldet die neue Zugriffszeit als „geändert“, jeder erste Klick baute die Liste neu auf
        with tempfile.TemporaryDirectory() as ordner:
            pfad = os.path.join(ordner, "a.pdf")
            with open(pfad, "wb") as f:
                f.write(b"x")
            os.utime(pfad, (time.time(), time.time() - 3600))
            self.handler.on_any_event(FileModifiedEvent(pfad))
            self.callback.assert_not_called()
            # Eine echte Änderung setzt die Änderungszeit auf jetzt
            os.utime(pfad, None)
            self.handler.on_any_event(FileModifiedEvent(pfad))
            self.assertEqual(self.callback.call_count, 1)
            # Neu, verschoben und gelöscht zählen immer, auch mit alter Änderungszeit (etwa kopiert)
            os.utime(pfad, (time.time(), time.time() - 3600))
            for ereignis in (FileCreatedEvent(pfad), FileMovedEvent(pfad, pfad + "2"), FileDeletedEvent(pfad)):
                self.callback.reset_mock()
                self.handler.on_any_event(ereignis)
                self.assertEqual(self.callback.call_count, 1, ereignis)

    def test_ist_nur_zugriff_grenze(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = os.path.join(ordner, "a.pdf")
            with open(pfad, "wb") as f:
                f.write(b"x")
            jetzt = os.path.getmtime(pfad)
            grenze = folder_monitor.MAX_ALTER_GEAENDERT
            self.assertFalse(folder_monitor.ist_nur_zugriff(FileModifiedEvent(pfad), jetzt=jetzt + grenze))
            self.assertTrue(folder_monitor.ist_nur_zugriff(FileModifiedEvent(pfad), jetzt=jetzt + grenze + 1))
        # Nicht prüfbar: Das Ereignis gilt, lieber einmal zu oft neu lesen als eine Änderung verpassen
        self.assertFalse(folder_monitor.ist_nur_zugriff(FileModifiedEvent(pfad)))
        self.assertFalse(folder_monitor.ist_nur_zugriff(DirModifiedEvent(ordner)))

    def test_ist_reines_ordner_ereignis(self):
        self.assertTrue(folder_monitor.ist_reines_ordner_ereignis(DirModifiedEvent("C:/x")))
        self.assertFalse(folder_monitor.ist_reines_ordner_ereignis(FileModifiedEvent("C:/x/a.pdf")))
        self.assertFalse(folder_monitor.ist_reines_ordner_ereignis(DirCreatedEvent("C:/x/neu")))


if __name__ == "__main__":
    unittest.main()
