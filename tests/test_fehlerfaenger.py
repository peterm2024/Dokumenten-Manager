"""Tests für den zentralen Fehlerfänger (fehlerfaenger.py, Beta-Vorbereitung 13.09.2026)."""

import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

import fehlerfaenger
from fehlerfaenger import Fehlerfaenger, kurztext, startfehler_sichern


def _ausnahme():
    try:
        raise ValueError("kaputt")
    except ValueError:
        return sys.exc_info()


class TestKurztext(unittest.TestCase):
    def test_typ_und_meldung(self):
        self.assertEqual(kurztext(ValueError, ValueError("x")), "ValueError: x")

    def test_ohne_meldung_nur_typ(self):
        self.assertEqual(kurztext(RuntimeError, RuntimeError()), "RuntimeError")


class TestFehlerfaenger(unittest.TestCase):
    def setUp(self):
        self.root = MagicMock()
        self.root.after.side_effect = lambda ms, fn: fn()
        self.logger = MagicMock()
        self.dialog = MagicMock()
        self.f = Fehlerfaenger(self.root, self.logger, dialog=self.dialog)

    def test_tk_fehler_protokolliert_traceback_und_zeigt_dialog(self):
        typ, wert, tb = _ausnahme()
        self.f.tk_fehler(typ, wert, tb)
        self.logger.error.assert_called_once()
        text = self.logger.error.call_args[0][0]
        self.assertIn("ValueError: kaputt", text)
        self.assertIn("Traceback", text)
        self.assertIn("Bedienung", text)
        self.dialog.assert_called_once_with("ValueError: kaputt", "Bedienung/Oberfläche")

    def test_gleiche_meldung_nur_einmal_pro_sperrzeit(self):
        typ, wert, tb = _ausnahme()
        self.assertTrue(self.f.melde(typ, wert, tb, "Test"))
        self.assertFalse(self.f.melde(typ, wert, tb, "Test"))
        self.assertEqual(self.logger.error.call_count, 2)   # protokolliert wird trotzdem
        self.assertEqual(self.dialog.call_count, 1)
        self.assertEqual(self.f.anzahl, 2)
        # Andere Meldung: eigener Dialog
        self.assertTrue(self.f.melde(KeyError, KeyError("k"), tb, "Test"))
        self.assertEqual(self.dialog.call_count, 2)

    def test_nach_sperrzeit_wieder_dialog(self):
        typ, wert, tb = _ausnahme()
        with patch.object(fehlerfaenger, "SPERRE_SEKUNDEN", 0):
            self.assertTrue(self.f.melde(typ, wert, tb, "Test"))
            self.assertTrue(self.f.melde(typ, wert, tb, "Test"))

    def test_thread_fehler_dialog_ueber_root_after(self):
        typ, wert, tb = _ausnahme()
        args = MagicMock(exc_type=typ, exc_value=wert, exc_traceback=tb)
        args.thread.name = "Vollautomatik"
        ergebnis = {}

        def im_thread():
            ergebnis["dialog_direkt"] = self.f.thread_fehler(args)
        t = threading.Thread(target=im_thread)
        t.start()
        t.join()
        self.root.after.assert_called_once()
        self.dialog.assert_called_once_with("ValueError: kaputt", "Hintergrund (Vollautomatik)")
        self.assertIn("Vollautomatik", self.logger.error.call_args[0][0])

    def test_system_exit_im_thread_ignoriert(self):
        args = MagicMock(exc_type=SystemExit, exc_value=SystemExit(), exc_traceback=None)
        self.f.thread_fehler(args)
        self.logger.error.assert_not_called()
        self.dialog.assert_not_called()

    def test_logger_fehler_bricht_nicht(self):
        self.logger.error.side_effect = OSError("Platte voll")
        typ, wert, tb = _ausnahme()
        self.assertTrue(self.f.melde(typ, wert, tb, "Test"))
        self.dialog.assert_called_once()

    def test_installieren_und_deinstallieren(self):
        alt = (sys.excepthook, threading.excepthook)
        self.f.installieren()
        try:
            # gebundene Methoden sind bei jedem Zugriff neue Objekte -> Gleichheit statt Identität
            self.assertEqual(sys.excepthook, self.f.sys_fehler)
            self.assertEqual(threading.excepthook, self.f.thread_fehler)
            self.assertEqual(self.root.report_callback_exception, self.f.tk_fehler)
        finally:
            self.f.deinstallieren()
        self.assertEqual((sys.excepthook, threading.excepthook), alt)

    def test_standard_dialog_oeffnet_protokoll_bei_ja(self):
        oeffnen = MagicMock()
        f = Fehlerfaenger(self.root, self.logger, log_oeffnen=oeffnen)
        with patch("fehlerfaenger.messagebox.askyesno", return_value=True) as frage:
            f._standard_dialog("ValueError: kaputt", "Test")
        self.assertIn("ValueError: kaputt", frage.call_args[0][1])
        self.assertIn("Protokoll", frage.call_args[0][1])
        oeffnen.assert_called_once()
        with patch("fehlerfaenger.messagebox.askyesno", return_value=False):
            f._standard_dialog("x", "Test")
        oeffnen.assert_called_once()


class TestStartfehler(unittest.TestCase):
    def test_schreibt_datei_und_haengt_an(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = startfehler_sichern("Traceback ... Fehler 1", tmp)
            self.assertEqual(os.path.basename(pfad), fehlerfaenger.STARTFEHLER_DATEI)
            startfehler_sichern("Fehler 2", tmp)
            with open(pfad, encoding="utf-8") as f:
                inhalt = f.read()
            self.assertIn("Fehler 1", inhalt)
            self.assertIn("Fehler 2", inhalt)
            self.assertEqual(inhalt.count("====="), 4)

    def test_unschreibbares_verzeichnis_liefert_none(self):
        self.assertIsNone(startfehler_sichern("x", os.path.join(tempfile.gettempdir(), "gibt", "es", "nicht")))


if __name__ == "__main__":
    unittest.main()


class TestAusgabeAbsichern(unittest.TestCase):
    """FALLSTRICKE #78: Debug-print mit „□“ ließ das Speichern bei umgeleiteter cp1252-Ausgabe scheitern."""

    def test_cp1252_ausgabe_wirft_nicht_mehr(self):
        import io
        puffer = io.BytesIO()
        strom = io.TextIOWrapper(puffer, encoding="cp1252")
        with self.assertRaises(UnicodeEncodeError):
            print("Speichere 20190101_□vmc.pdf", file=strom)
        fehlerfaenger.ausgabe_absichern([strom])
        print("Speichere 20190101_□vmc.pdf", file=strom)
        strom.flush()
        self.assertIn(b"\\u25a1vmc.pdf", puffer.getvalue())

    def test_ohne_konsole_kein_fehler(self):
        fehlerfaenger.ausgabe_absichern([None, object()])   # EXE: sys.stdout ist None
