"""Ein Abbruch beim Schreiben darf weder ein Original noch Einstellungen oder Katalog beschädigen (ARCHITEKTUR_REVIEW.md, R1, R2, R8).

Die Tests laufen über die öffentlichen Wege, damit sie auch gegen den Stand vor dem Fix scheitern konnten.
"""
import ast
import contextlib
import ctypes
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tkinter as tk
import unittest
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import fitz

import app_paths
import config
import dubletten_geprueft
import fehlerfaenger
import folder_manager
import gui
import ordner_aliase
import papierkorb_herkunft
import sicher_speichern
import tag_ignorierliste
import zuletzt_benutzt
from app_logger import AppLogger
from pdf_handler import PDFHandler
from tag_editor import TagEditor

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def _lies(pfad):
    with open(pfad, "rb") as f:
        return f.read()


def _schreibe(pfad, inhalt):
    os.makedirs(os.path.dirname(pfad) or ".", exist_ok=True)
    with open(pfad, "w", encoding="utf-8") as f:
        f.write(inhalt)


@contextlib.contextmanager
def _halte_offen(pfad, schreiben_erlaubt):
    """Hält die Datei wie ein fremdes Programm lesend offen, ohne das Löschen zu erlauben (echte Windows-Sperre)."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.restype = ctypes.c_void_p
    teilen = 0x1 | (0x2 if schreiben_erlaubt else 0)            # FILE_SHARE_READ (| FILE_SHARE_WRITE), nie DELETE
    griff = kernel32.CreateFileW(pfad, 0x80000000, teilen, None, 3, 0x80, None)   # GENERIC_READ, OPEN_EXISTING
    if griff in (None, ctypes.c_void_p(-1).value):
        raise OSError(ctypes.get_last_error(), "Datei ließ sich nicht öffnen")
    try:
        yield
    finally:
        kernel32.CloseHandle(ctypes.c_void_p(griff))


def _aufrufe(pfad):
    with open(pfad, encoding="utf-8") as f:
        baum = ast.parse(f.read())
    return [k for k in ast.walk(baum) if isinstance(k, ast.Call)]


def _quelldateien():
    for basis, _, namen in os.walk(SRC):
        if "__pycache__" not in basis:
            for n in namen:
                if n.endswith(".py"):
                    yield os.path.join(basis, n)


class TestPdfErsetzen(unittest.TestCase):
    """R1: Unter Windows kopiert shutil.move über ein vorhandenes Ziel. Ein Abbruch ließ ein halbes Original zurück."""

    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ordner, ignore_errors=True)
        self.pdf = os.path.join(self.ordner, "Musterrechnung.pdf")
        with fitz.open() as doc:
            for i in range(3):
                doc.new_page().insert_text((50, 50), f"Musterrechnung Seite {i}")
            doc.save(self.pdf)
        self.vorher = _lies(self.pdf)

    def test_kopiert_nicht_ueber_das_original(self):
        with patch("shutil.move", side_effect=AssertionError("shutil.move kopiert über das Original")):
            self.assertTrue(PDFHandler.write_custom_metadata(self.pdf, {"title": "Neu"}, still=True))
        self.assertEqual(PDFHandler.get_metadata(self.pdf)["title"], "Neu")

    def test_gescheitertes_ersetzen_laesst_das_original_unberuehrt(self):
        """Ein Programm hält das PDF offen und erlaubt weder Löschen noch Schreiben (wie manche PDF-Anzeige)."""
        with patch.object(PDFHandler, "SCHREIB_WARTEZEIT_S", 0), _halte_offen(self.pdf, schreiben_erlaubt=False):
            self.assertFalse(PDFHandler.write_custom_metadata(self.pdf, {"title": "Neu"}, still=True))
        self.assertEqual(_lies(self.pdf), self.vorher)
        self.assertEqual(os.listdir(self.ordner), ["Musterrechnung.pdf"])

    def test_offener_leser_verhindert_das_speichern_nicht(self):
        """Peter 07.11.2026, Speicher-Fehler WinError 32 beim Alt-Ziehen: Ein Leser, der Schreiben, aber kein Löschen erlaubt
        (so öffnet jedes Python-open), ließ os.replace scheitern; bis v0.9.25 kam das Speichern durch (FALLSTRICKE #118)."""
        with patch.object(PDFHandler, "SCHREIB_WARTEZEIT_S", 0), _halte_offen(self.pdf, schreiben_erlaubt=True):
            self.assertTrue(PDFHandler.write_custom_metadata(self.pdf, {"title": "Neu"}, still=True))
        self.assertEqual(PDFHandler.get_metadata(self.pdf)["title"], "Neu")
        self.assertEqual(os.listdir(self.ordner), ["Musterrechnung.pdf"])

    def test_fehler_beim_ueberschreiben_bringt_das_original_zurueck(self):
        echtes_fsync, aufrufe = os.fsync, []

        def fsync_scheitert_am_ziel(fd):
            aufrufe.append(fd)
            if len(aufrufe) > 1:                     # 1. Aufruf: Temp-Datei, 2.: Ziel beim Überschreiben
                raise OSError(28, "Platte voll")
            echtes_fsync(fd)

        with patch.object(PDFHandler, "SCHREIB_WARTEZEIT_S", 0), _halte_offen(self.pdf, schreiben_erlaubt=True), \
                patch("os.fsync", side_effect=fsync_scheitert_am_ziel):
            self.assertFalse(PDFHandler.write_custom_metadata(self.pdf, {"title": "Neu"}, still=True))
        self.assertEqual(_lies(self.pdf), self.vorher)
        self.assertEqual(os.listdir(self.ordner), ["Musterrechnung.pdf"])

    def test_defekte_neue_fassung_ersetzt_das_original_nicht(self):
        echtes_save = fitz.Document.save

        def speichert_defekt(doc, ziel, *a, **k):
            echtes_save(doc, ziel, *a, **k)
            with open(ziel, "r+b") as f:
                f.truncate(50)

        with patch.object(fitz.Document, "save", speichert_defekt):
            self.assertFalse(PDFHandler.write_custom_metadata(self.pdf, {"title": "Neu"}, still=True))
        self.assertEqual(_lies(self.pdf), self.vorher)
        self.assertEqual(os.listdir(self.ordner), ["Musterrechnung.pdf"])

    def test_fehlende_seiten_ersetzen_das_original_nicht(self):
        echtes_save = fitz.Document.save

        def speichert_weniger(doc, ziel, *a, **k):
            with fitz.open() as kurz:
                kurz.new_page()
                echtes_save(kurz, ziel)

        with patch.object(fitz.Document, "save", speichert_weniger):
            self.assertFalse(PDFHandler.write_custom_metadata(self.pdf, {"title": "Neu"}, still=True))
        self.assertEqual(_lies(self.pdf), self.vorher)

    def test_neue_fassung_liegt_vor_dem_ersetzen_auf_der_platte(self):
        reihenfolge = []
        echtes_fsync, echtes_replace = os.fsync, os.replace
        with patch("os.fsync", side_effect=lambda fd: (reihenfolge.append("fsync"), echtes_fsync(fd))[1]), \
                patch("os.replace", side_effect=lambda a, b: (reihenfolge.append("replace"), echtes_replace(a, b))[1]):
            self.assertTrue(PDFHandler.write_custom_metadata(self.pdf, {"title": "Neu"}, still=True))
        self.assertEqual(reihenfolge[-2:], ["fsync", "replace"])

    def test_kein_schreibweg_kopiert_ueber_ein_pdf(self):
        for pfad in (os.path.join(SRC, "pdf_handler.py"), os.path.join(SRC, "tools", "pdf_editor.py")):
            with self.subTest(pfad=os.path.basename(pfad)):
                treffer = [k.lineno for k in _aufrufe(pfad)
                           if isinstance(k.func, ast.Attribute) and k.func.attr == "move" and getattr(k.func.value, "id", "") == "shutil"]
                self.assertEqual(treffer, [])

    def test_rest_eines_abbruchs_steht_nicht_in_der_dokumentenliste(self):
        """Nach einem Abbruch liegt <Name>.pdf.tmp neben dem heilen Original (FALLSTRICKE #60, #115)."""
        self.assertTrue(folder_manager.ist_versteckte_systemdatei(SimpleNamespace(name="Muster.pdf.tmp")))

    def test_gescheiterte_signaturpruefung_nimmt_den_sicheren_weg(self):
        """Der Neuaufbau zerstört eine Signatur, der inkrementelle Weg nicht: im Zweifel gilt das PDF als signiert."""
        with patch.object(fitz.Document, "get_sigflags", side_effect=RuntimeError("kaputt")):
            self.assertEqual(PDFHandler.get_write_protection(self.pdf), "signiert")


class TestEinstellungen(unittest.TestCase):
    """R2: Eine halb geschriebene settings.json galt als nicht vorhanden und wurde überschrieben."""

    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ordner, ignore_errors=True)
        self.pfad = os.path.join(self.ordner, "settings.json")

    def test_kaputte_einstellungen_werden_nicht_ueberschrieben(self):
        kaputt = '{"master_folder": "D:/Samm'
        _schreibe(self.pfad, kaputt)
        c = config.Config(self.pfad)
        self.assertEqual(c.get("master_folder"), "")
        c.set("fenster", "1x1")
        self.assertEqual(_lies(self.pfad + ".kaputt").decode("utf-8"), kaputt)

    def test_gescheitertes_speichern_laesst_die_datei_ganz(self):
        c = config.Config(self.pfad)
        c.set("wert", 1)
        vorher = _lies(self.pfad)
        c.data["wert"] = 2
        with patch("os.replace", side_effect=OSError(5, "nachgestellt")):
            self.assertFalse(c.save())
        self.assertEqual(_lies(self.pfad), vorher)
        self.assertEqual(os.listdir(self.ordner), ["settings.json"])


class TestKleineDateien(unittest.TestCase):
    """R2: Dieselbe Regel für alle JSON-Dateien im Daten-Ordner."""

    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ordner, ignore_errors=True)
        self.master = os.path.join(self.ordner, "Sammlung")
        os.makedirs(self.master)

    def test_kaputte_datei_bleibt_erhalten(self):
        faelle = [
            ("aliase", app_paths.aliase_path, lambda: ordner_aliase.lade_aliase(self.master), {}),
            ("ignorierliste", app_paths.tags_ignoriert_path, lambda: tag_ignorierliste.lade(self.master), set()),
            ("dubletten", app_paths.dubletten_geprueft_path, lambda: dubletten_geprueft.lade(self.master), set()),
            ("papierkorb", app_paths.papierkorb_herkunft_path, lambda: papierkorb_herkunft.lade(self.master), {}),
            ("zuletzt", app_paths.zuletzt_benutzt_path, lambda: zuletzt_benutzt.lade(self.master), []),
        ]
        for name, pfad_von, lade, leer in faelle:
            with self.subTest(name):
                pfad = pfad_von(self.master)
                _schreibe(pfad, '{"halb')
                self.assertEqual(lade(), leer)
                self.assertEqual(_lies(pfad + ".kaputt"), b'{"halb')
                self.assertFalse(os.path.exists(pfad), "die kaputte Datei liegt noch am alten Platz und würde überschrieben")

    def test_kein_modul_schreibt_json_direkt(self):
        """Neue Speicher sollen den sicheren Weg nicht vergessen können. mail_quellen bleibt reine Standardbibliothek und schreibt seine Marke selbst atomar."""
        erlaubt = {"sicher_speichern.py", "mail_quellen.py"}
        for pfad in _quelldateien():
            if os.path.basename(pfad) in erlaubt:
                continue
            treffer = [k.lineno for k in _aufrufe(pfad)
                       if isinstance(k.func, ast.Attribute) and k.func.attr == "dump" and getattr(k.func.value, "id", "") == "json"]
            with self.subTest(pfad=os.path.relpath(pfad, SRC)):
                self.assertEqual(treffer, [], "bitte sicher_speichern.schreibe_json nehmen")


class TestTagKatalog(unittest.TestCase):
    """R2: Beim Laden einer kaputten tags.json überschrieb save_tags die gute .bak mit der kaputten Datei."""

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ordner, ignore_errors=True)
        self.master = os.path.join(self.ordner, "Sammlung")
        os.makedirs(self.master)
        alt = os.getcwd()
        self.addCleanup(os.chdir, alt)
        os.chdir(self.ordner)   # die Vorlage tags_default.json wird relativ zum Arbeitsverzeichnis gesucht
        self.baum = ttk.Treeview(self.root)
        self.addCleanup(self.baum.destroy)
        self.pfad = app_paths.tags_path(self.master)
        self.app = SimpleNamespace(master_folder=self.master, tree_tags=self.baum, root=self.root, logger=logging.getLogger("test"))

    def _lade(self):
        for kind in self.baum.get_children():
            self.baum.delete(kind)
        editor = TagEditor(self.app)
        editor.load_tags()
        return editor

    def _tags(self):
        return [self.baum.item(k, "text") for k in self.baum.get_children()]

    def test_kaputter_katalog_kommt_aus_der_sicherung_zurueck(self):
        _schreibe(self.pfad, json.dumps([{"text": "Mein Katalog", "children": []}]))
        self._lade()
        self.baum.insert("", "end", text="Mein zweiter Tag", tags=("bundle",))
        TagEditor(self.app).save_tags()
        self.assertIn("Mein Katalog", _lies(self.pfad + ".bak").decode("utf-8"))
        kaputt = _lies(self.pfad)[:40]
        with open(self.pfad, "wb") as f:
            f.write(kaputt)

        self._lade()

        self.assertIn("Mein Katalog", self._tags())
        self.assertEqual(_lies(self.pfad + ".kaputt"), kaputt)
        self.assertIn("Mein Katalog", _lies(self.pfad).decode("utf-8"))

    def test_kaputter_katalog_ohne_sicherung_bleibt_beiseitegelegt(self):
        _schreibe(self.pfad, '[{"text": "Mein Kat')
        self._lade()
        self.assertEqual(_lies(self.pfad + ".kaputt"), b'[{"text": "Mein Kat')

    def test_start_ohne_aenderung_schreibt_nichts(self):
        """Jeder Start schrieb den Katalog neu, und die .bak war danach nur noch dieselbe Fassung."""
        _schreibe(self.pfad, json.dumps([{"text": "Mein Katalog", "children": []}]))
        self._lade()
        vorher = (_lies(self.pfad), _lies(self.pfad + ".bak") if os.path.exists(self.pfad + ".bak") else None)
        self._lade()
        self.assertEqual((_lies(self.pfad), _lies(self.pfad + ".bak") if os.path.exists(self.pfad + ".bak") else None), vorher)


class TestMeldung(unittest.TestCase):
    """R2: Was beiseitegelegt wurde, muss der Nutzer erfahren, sonst sähe es nach verlorenen Einstellungen aus."""

    def setUp(self):
        sicher_speichern.nimm_beiseite_gelegte()
        self.addCleanup(sicher_speichern.nimm_beiseite_gelegte)

    def test_beschaedigte_dateien_werden_einmal_gemeldet(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = os.path.join(ordner, "settings.json")
            _schreibe(pfad, "{kaputt")
            config.Config(pfad)
            fenster = SimpleNamespace(logger=MagicMock())
            with patch("gui.messagebox") as mb:
                gui.DokumentenVerwaltung.melde_beschaedigte(fenster)
                gui.DokumentenVerwaltung.melde_beschaedigte(fenster)
            mb.showwarning.assert_called_once()
            self.assertIn("settings.json.kaputt", mb.showwarning.call_args.args[1])

    def test_ohne_schaden_keine_meldung(self):
        with patch("gui.messagebox") as mb:
            gui.DokumentenVerwaltung.melde_beschaedigte(SimpleNamespace(logger=MagicMock()))
        mb.showwarning.assert_not_called()


class TestProtokoll(unittest.TestCase):
    """R8: Fehler müssen auch in der EXE ohne Konsole eine Spur hinterlassen."""

    def test_kein_print_in_der_app(self):
        for pfad in _quelldateien():
            treffer = [k.lineno for k in _aufrufe(pfad) if getattr(k.func, "id", "") == "print"]
            with self.subTest(pfad=os.path.relpath(pfad, SRC)):
                self.assertEqual(treffer, [], "print geht in der EXE ins Leere, bitte ins Protokoll")

    def test_protokoll_waechst_nicht_ohne_grenze(self):
        with tempfile.TemporaryDirectory() as ordner:
            logger = AppLogger()
            pfad = os.path.join(ordner, "protokoll.log")
            logger.set_log_file(pfad)
            self.addCleanup(logger.logger.removeHandler, logger.fh)
            try:
                for _ in range(3000):
                    logger.info("x" * 4000)
                self.assertLess(os.path.getsize(pfad), 8 * 1024 * 1024)
                self.assertTrue(os.path.exists(pfad + ".1"), "die ältere Fassung bleibt erhalten")
            finally:
                logger.fh.close()

    def test_native_absturz_hinterlaesst_eine_spur(self):
        """Ein Absturz im nativen Code (MuPDF, libpff) umgeht jedes except, darum ein echter Absturz im eigenen Prozess."""
        with tempfile.TemporaryDirectory() as ordner:
            code = ("import sys; sys.path.insert(0, sys.argv[1]); import fehlerfaenger, ctypes; "
                    "fehlerfaenger.absturz_protokoll_starten(sys.argv[2]); ctypes.string_at(0)")
            subprocess.run([sys.executable, "-c", code, SRC, ordner], capture_output=True, timeout=60)
            text = fehlerfaenger.letzter_absturz(ordner)
            self.assertIn("fatal", text.lower())
            self.assertEqual(fehlerfaenger.letzter_absturz(ordner), "", "jeder Absturz wird nur einmal gemeldet")

    def test_normales_ende_hinterlaesst_nichts(self):
        with tempfile.TemporaryDirectory() as ordner:
            code = ("import sys; sys.path.insert(0, sys.argv[1]); import fehlerfaenger; "
                    "fehlerfaenger.absturz_protokoll_starten(sys.argv[2])")
            subprocess.run([sys.executable, "-c", code, SRC, ordner], capture_output=True, timeout=60)
            time.sleep(0.05)
            self.assertEqual(os.listdir(ordner), [])


if __name__ == "__main__":
    unittest.main()
