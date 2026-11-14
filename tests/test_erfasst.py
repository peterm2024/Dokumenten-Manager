"""Peter 04.11.2026 (T20.3): Spalte „Erfasst“ (welche Dokumente zuletzt erfasst wurden), KI-Titel auch in 0_Unsicher;
dazu aus demselben Test: Mails mit verschiedener Message-ID sind keine Dubletten, PDF-Anhänge bekommen das Mail-Datum
als Ersatz. Nur synthetische Daten."""
import datetime
import os
import shutil
import sqlite3
import tempfile
import tkinter as tk
import types
import unittest
from tkinter import ttk
from unittest.mock import patch

import fitz

import auto_pilot
import dubletten_pruefung
import index_manager
import mail_import
import scan_date
from pdf_handler import PDFHandler
from tests.test_mail_import import baue, pdf_bytes
from ui_utils import UIUtils

JETZT = "2026-11-04 19:30"
# genug verschiedene Wörter für den Textvergleich der Dublettenprüfung (MIN_WOERTER, 92 % bei anderem Datum)
LANG = " ".join(f"Position{i} Betrag{i}" for i in range(40))


def leeres_pdf(pfad, text="Beitragsrechnung Musterversicherung"):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    doc.save(pfad)
    doc.close()


def entscheidung(pfad, sicher=True):
    return {"pdf_path": pfad, "titel": "Beitragsrechnung 2025", "tags": ["Versicherung"], "datum": "2025-01-15",
            "absender": "Musterversicherung", "ordnername": "Musterversicherung", "zielordner": "Musterversicherung",
            "ordner_neu": True, "neuer_dateiname": "20250115_Beitragsrechnung.pdf", "sicher": sicher,
            "probleme": [] if sicher else ["kein plausibles Dokumentdatum erkannt"]}


class _Basis(unittest.TestCase):
    def setUp(self):
        self.master = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.master, True)
        self.pfad = os.path.join(self.master, "eingang.pdf")
        leeres_pdf(self.pfad)

    @staticmethod
    def verschieben(quelle, ziel):
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        shutil.move(quelle, ziel)


class TestFeld(_Basis):
    def test_einmal_gesetzt_nie_ueberschrieben(self):
        PDFHandler.write_custom_metadata(self.pfad, {"KID_Erfasst": JETZT}, still=True)
        self.assertEqual(PDFHandler.get_metadata(self.pfad)["KID_Erfasst"], JETZT)
        PDFHandler.write_custom_metadata(self.pfad, {"KID_Erfasst": "2030-01-01 00:00", "title": "X"}, still=True)
        self.assertEqual(PDFHandler.get_metadata(self.pfad)["KID_Erfasst"], JETZT)
        PDFHandler.save_metadata(self.pfad, "Neuer Titel", "Tag", still=True)         # normales Speichern ändert nichts
        self.assertEqual(PDFHandler.get_metadata(self.pfad)["KID_Erfasst"], JETZT)

    def test_anzeige_mit_ersatz_scan_zeitpunkt(self):
        self.assertEqual(scan_date.erfasst_anzeige(JETZT, "01.01.2020 10:00"), "04.11.2026 19:30")
        self.assertEqual(scan_date.erfasst_anzeige("", "01.01.2020 10:00"), "01.01.2020 10:00")    # alte Dokumente


class TestAblage(_Basis):
    def test_sichere_ablage_setzt_erfasst(self):
        e = auto_pilot.fuehre_entscheidung_aus(entscheidung(self.pfad), self.master, self.verschieben)
        wert = PDFHandler.get_metadata(e["neuer_pfad"])["KID_Erfasst"]
        self.assertTrue(datetime.datetime.strptime(wert, "%Y-%m-%d %H:%M"))

    def test_unsicher_bekommt_titel_und_erfasst_sonst_nichts(self):
        PDFHandler.write_custom_metadata(self.pfad, {"keywords": "Alt", "KID_DokumentenDatum": "2001-02-03"}, still=True)
        e = auto_pilot.fuehre_entscheidung_aus(entscheidung(self.pfad, sicher=False), self.master, self.verschieben)
        self.assertEqual(os.path.basename(e["neuer_pfad"]), "eingang.pdf")             # Dateiname bleibt
        meta = PDFHandler.get_metadata(e["neuer_pfad"])
        self.assertEqual(meta["title"], "Beitragsrechnung 2025")
        self.assertTrue(meta["KID_Erfasst"])
        self.assertEqual(meta["KID_Grund"], "kein plausibles Dokumentdatum erkannt")
        self.assertEqual((meta["keywords"], meta["KID_DokumentenDatum"]), ("Alt", "2001-02-03"))   # Peter: nur der Titel

    def test_unsicher_ohne_ki_titel_laesst_vorhandenen_stehen(self):
        PDFHandler.write_custom_metadata(self.pfad, {"title": "Mein Betreff"}, still=True)
        auftrag = dict(entscheidung(self.pfad, sicher=False), titel="")
        e = auto_pilot.fuehre_entscheidung_aus(auftrag, self.master, self.verschieben)
        self.assertEqual(PDFHandler.get_metadata(e["neuer_pfad"])["title"], "Mein Betreff")


class TestIndex(_Basis):
    def app(self):
        return types.SimpleNamespace(master_folder=self.master, config=None, logger=None)

    def test_alter_index_bekommt_die_spalte_ohne_alles_neu_zu_lesen(self):
        im = index_manager.IndexManager(self.app())
        im.metadaten([self.pfad])                                 # Index anlegen, Datei hat noch kein KID_Erfasst
        pfad_db = index_manager.app_paths.index_path(self.master)
        con = sqlite3.connect(pfad_db)
        spalten = [z[1] for z in con.execute("PRAGMA table_info(files)")]
        self.assertIn("erfasst", spalten)
        con.close()
        with patch("index_manager.PDFHandler.get_metadata") as lesen:
            neu = index_manager.IndexManager(self.app())
            self.assertEqual(neu.metadaten([self.pfad])[self.pfad]["KID_Erfasst"], "")
            lesen.assert_not_called()

    def test_neuer_wert_kommt_ueber_den_index(self):
        PDFHandler.write_custom_metadata(self.pfad, {"KID_Erfasst": JETZT}, still=True)
        im = index_manager.IndexManager(self.app())
        self.assertEqual(im.metadaten([self.pfad])[self.pfad]["KID_Erfasst"], JETZT)
        with patch("index_manager.PDFHandler.get_metadata") as lesen:     # zweites Mal aus dem Index
            self.assertEqual(im.metadaten([self.pfad])[self.pfad]["KID_Erfasst"], JETZT)
            lesen.assert_not_called()


class TestSpalte(unittest.TestCase):
    def test_spalte_sortiert_mit_uhrzeit(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        baum = ttk.Treeview(root, columns=("erfasst",))
        for wert in ("04.11.2026 09:00", "04.11.2026 19:30", "03.11.2026 23:00"):
            baum.insert("", "end", values=(wert,))
        UIUtils.sort_treeview(baum, "erfasst", True)
        self.assertEqual([baum.set(i, "erfasst") for i in baum.get_children()],
                         ["04.11.2026 19:30", "04.11.2026 09:00", "03.11.2026 23:00"])

    def test_spalte_ist_angelegt(self):
        import layout_builder
        from tools.settings_editor import SettingsEditorWindow
        self.assertIn("erfasst", layout_builder.STANDARD_BREITEN)
        self.assertIn("erfasst", layout_builder.MINDEST_BREITEN)
        self.assertEqual(SettingsEditorWindow.COLUMN_LABELS["erfasst"], "Erfasst")


class TestMailsKeineDubletten(unittest.TestCase):
    def setUp(self):
        self.master = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.master, True)
        self.ziel = os.path.join(self.master, "Ordner")
        self.eingang = os.path.join(self.master, "0_Posteingang")
        os.makedirs(self.ziel)
        os.makedirs(self.eingang)
        self.journal = mail_import.Journal(self.master)
        self.journal.eigene = ["max@example.org"]

    def mail_pdf(self, ordner, mid, datum):
        quelle = os.path.join(self.master, f"{mid}.eml")
        with open(quelle, "wb") as f:
            f.write(baue(mid=f"<{mid}@x>", datum=datetime.datetime(datum, 1, 15, 9, tzinfo=datetime.timezone.utc),
                         text=LANG))
        b = mail_import.lies_quelle(quelle, self.journal)
        b.eintraege[0].ergebnis = mail_import.UEBERNEHMEN
        mail_import.importiere(b, self.journal, ordner)
        return os.path.join(ordner, self.journal.importiert[b.eintraege[0].schluessel]["dateien"][0])

    def test_zwei_mails_gleichen_textes_sind_keine_dublette(self):
        # T20.3: 12 von 28 Mails landeten als „vermutlich Dublette“ in 0_Unsicher, trotz eigener Message-ID
        self.mail_pdf(self.ziel, "a", 2023)
        neu = self.mail_pdf(self.eingang, "b", 2024)
        self.assertIsNone(dubletten_pruefung.finde_dublette(neu, self.ziel, datum="2024-01-15"))

    def test_mail_und_scan_werden_weiter_verglichen(self):
        alt = self.mail_pdf(self.ziel, "a", 2024)
        kopie = os.path.join(self.eingang, "scan.pdf")
        with fitz.open(alt) as doc:
            doc.set_metadata({"title": "Scan"})
            doc.save(kopie)
        self.assertIsNotNone(dubletten_pruefung.finde_dublette(kopie, self.ziel))

    def test_anhaenge_werden_weiter_verglichen(self):
        # dieselbe Rechnung als Anhang zweier Mails IST eine Dublette
        daten = pdf_bytes(LANG)
        a, b = os.path.join(self.ziel, "a.pdf"), os.path.join(self.eingang, "b.pdf")
        PDFHandler.schreibe_anhang_pdf(a, daten, {"KID_MailID": "mid:1@x"})
        PDFHandler.schreibe_anhang_pdf(b, daten, {"KID_MailID": "mid:2@x"})
        self.assertIsNotNone(dubletten_pruefung.finde_dublette(b, self.ziel))


class TestAnhangDatum(unittest.TestCase):
    def test_ki_datum_vor_maildatum(self):
        anhang = {"KID_MailID": "mid:1@x", "KID_DokumentenDatum": "2024-03-05"}
        self.assertEqual(auto_pilot.mit_mailkopf({"datum": "2024-02-28"}, anhang)["datum"], "2024-02-28")
        self.assertEqual(auto_pilot.mit_mailkopf({"datum": ""}, anhang)["datum"], "2024-03-05")
        self.assertEqual(auto_pilot.mit_mailkopf({"datum": "Quatsch"}, anhang)["datum"], "2024-03-05")

    def test_import_schreibt_maildatum_und_erfasst_in_den_anhang(self):
        basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, basis, True)
        quelle = os.path.join(basis, "m.eml")
        with open(quelle, "wb") as f:
            f.write(baue(anhang=("R.pdf", pdf_bytes())))
        j = mail_import.Journal(basis)
        j.eigene = ["max@example.org"]
        b = mail_import.lies_quelle(quelle, j)
        b.eintraege[0].ergebnis = mail_import.UEBERNEHMEN
        ziel = os.path.join(basis, "ein")
        mail_import.importiere(b, j, ziel)
        anhang = PDFHandler.get_metadata(os.path.join(ziel, "20240305_R.pdf"))
        self.assertEqual(anhang["KID_DokumentenDatum"], "2024-03-05")
        self.assertTrue(anhang["KID_Erfasst"])
        mail = PDFHandler.get_metadata(os.path.join(ziel, "20240305_Ihre Beitragsrechnung.pdf"))
        self.assertTrue(mail["KID_Erfasst"])


if __name__ == "__main__":
    unittest.main()
