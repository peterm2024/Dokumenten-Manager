"""Ansicht → „Mails ausblenden“ (Peter 06.11.2026) und der leere Ordner, der unten noch ein Dokument zeigte (FALLSTRICKE #111)."""
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import app_paths
import index_manager
from folder_manager import FolderManager
from index_manager import IndexManager
from search_manager import SearchManager
from tests.test_folder_manager import _FakeTreeview


def _meta(pfad):
    """Attrappe für PDFHandler.get_metadata: Dateien namens mail* sind Mail-PDFs."""
    return {"title": "T", "keywords": "", "KID_Richtung": "ein" if os.path.basename(pfad).startswith("mail") else ""}


class _Sammlung(unittest.TestCase):
    DATEIEN = (("A", "NurMail", "mail1.pdf"), ("A", "Gemischt", "mail2.pdf"), ("A", "Gemischt", "scan1.pdf"),
               ("0_Unsicher", "mail3.pdf"), ("B", "C", "mail4.pdf"))

    def setUp(self):
        self.master = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.master, ignore_errors=True)
        os.makedirs(os.path.join(self.master, "A", "Leer"))
        for teile in self.DATEIEN:
            pfad = os.path.join(self.master, *teile)
            os.makedirs(os.path.dirname(pfad), exist_ok=True)
            open(pfad, "wb").close()
        self.app = MagicMock()
        self.app.master_folder = self.master
        self.app.show_trash_var.get.return_value = False
        self.app.index_manager = None
        self.app.tree_folders = _FakeTreeview()
        self.manager = FolderManager(self.app)
        patcher = patch("folder_manager.PDFHandler.get_metadata", side_effect=_meta)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _baum(self):
        """{Ordnername: Zahl} des aufgebauten Baums."""
        self.manager.refresh_folder_tree()
        return {n["text"]: n["values"][1] for n in self.app.tree_folders.nodes.values()}


class TestOrdnerbaum(_Sammlung):
    def test_ausgeschaltet_bleibt_alles(self):
        self.app.mails_ausblenden_var.get.return_value = False
        baum = self._baum()
        self.assertEqual(baum["NurMail"], "1")
        self.assertEqual(baum["Gemischt"], "2")
        self.assertEqual(baum["C"], "1")

    def test_eingeschaltet_verschwinden_reine_mail_ordner(self):
        self.app.mails_ausblenden_var.get.return_value = True
        baum = self._baum()
        self.assertNotIn("NurMail", baum)
        self.assertNotIn("C", baum)
        self.assertNotIn("B", baum)                 # auch der Ordner darüber, wenn darunter nur Mails liegen
        self.assertEqual(baum["Gemischt"], "1")     # die Mail zählt nicht mehr, der Scan bleibt

    def test_leere_ordner_und_systemordner_bleiben(self):
        self.app.mails_ausblenden_var.get.return_value = True
        baum = self._baum()
        self.assertIn("Leer", baum)                 # kein Mail-Ordner, sondern leer: bleibt wie bisher
        self.assertEqual(baum["0_Unsicher"], "1")   # was noch auf eine Entscheidung wartet, bleibt sichtbar
        self.assertEqual(baum[os.path.basename(self.master)], "2")

    def test_ein_blosses_magicmock_schaltet_nichts_aus(self):
        # Viele Tests arbeiten mit MagicMock-App: Der Schalter gilt nur bei echtem True
        self.assertFalse(index_manager.mails_ausgeblendet(MagicMock()))


class TestSprungZuEinerMail(_Sammlung):
    def test_sprung_zu_einer_ausgeblendeten_mail_blendet_ein(self):
        # „Anhang der Mail: …“ zeigt auf eine Mail in einem ausgeblendeten Ordner
        var = self.app.mails_ausblenden_var
        var.get.return_value = True
        var.set.side_effect = lambda w: setattr(var.get, "return_value", w)
        self.app.search_manager.is_search_active.return_value = False
        self.manager.refresh_folder_tree()
        self.manager.on_folder_select = MagicMock()
        ziel = os.path.join(self.master, "A", "NurMail", "mail1.pdf")
        self.assertTrue(self.manager.zeige_dokument(ziel))
        var.set.assert_called_with(False)
        self.app.config.set.assert_called_with("mails_ausblenden", False)
        self.assertIn("NurMail", {n["text"] for n in self.app.tree_folders.nodes.values()})


class TestDokumentenliste(_Sammlung):
    def _liste(self, *ordner):
        pfad = os.path.join(self.master, *ordner)
        self.app.tree_folders.insert("", "end", text="x", values=(pfad, ""))
        self.app.tree_folders.selection_set(self.app.tree_folders.get_children("")[-1])
        self.app.folder_manager = self.manager
        self.app.tree_files = MagicMock()
        self.app.tree_files.selection.return_value = ()
        self.app.tree_files.get_children.return_value = ()
        self.app.current_preview_path = None
        with patch("folder_manager.UIUtils.set_sort_indicator"):
            self.manager.on_folder_select(None)
        return [a.kwargs["values"][3] for a in self.app.tree_files.insert.call_args_list]

    def test_liste_zeigt_keine_mails_wenn_ausgeblendet(self):
        self.app.mails_ausblenden_var.get.return_value = True
        self.assertEqual(self._liste("A", "Gemischt"), ["scan1.pdf"])

    def test_liste_zeigt_mails_sonst(self):
        self.app.mails_ausblenden_var.get.return_value = False
        self.assertEqual(sorted(self._liste("A", "Gemischt")), ["mail2.pdf", "scan1.pdf"])

    def test_systemordner_zeigt_mails_immer(self):
        self.app.mails_ausblenden_var.get.return_value = True
        self.assertEqual(self._liste("0_Unsicher"), ["mail3.pdf"])

    def test_leerer_ordner_leert_auch_die_eigenschaften(self):
        # Screenshot Peter 06.11.2026: Liste leer, unten standen noch Dateiname, Ordner und „Original-Mail öffnen“
        self.app.mails_ausblenden_var.get.return_value = False
        self.assertEqual(self._liste("A", "Leer"), [])
        self.app.leere_dokumentanzeige.assert_called_once()


class TestLeereAnzeige(unittest.TestCase):
    def test_auch_das_datum_verschwindet(self):
        # Im leeren Ordner blieb das vermutete Datum des letzten Dokuments orange stehen
        import gui
        app = MagicMock()
        gui.DokumentenVerwaltung.leere_dokumentanzeige(app)
        app.date_entry.delete.assert_called_once()
        app.setze_datum_stil.assert_called_once_with()
        app.eigenschaften_panel.leeren.assert_called_once_with()


class TestSuche(unittest.TestCase):
    def _suche(self, an):
        app = MagicMock()
        app.mails_ausblenden_var.get.return_value = an
        app.use_ocr_var.get.return_value = False
        docs = [dict(rel_path=r, name=os.path.basename(r), title="Rechnung", keywords="", kid_date="2024-01-02",
                     creation_date="", scan_zeit_embedded="", erfasst="", kid_id="", mtime=0.0, richtung=ri)
                for r, ri in ((os.path.join("A", "mail.pdf"), "ein"), (os.path.join("A", "scan.pdf"), ""),
                              (os.path.join("0_Unsicher", "mail2.pdf"), "ein"))]
        sm = SearchManager(app)
        sm._iter_documents = lambda _m: docs
        with tempfile.TemporaryDirectory() as master, patch("search_manager.index_manager.vermutete_daten_sicher", return_value={}):
            treffer = sm.execute_search(master, "rechnung", "", "", [])
        return sm, sorted(os.path.basename(t[4]) for t in treffer)

    def test_ausgeblendet_findet_keine_mails_und_sagt_es(self):
        sm, treffer = self._suche(True)
        self.assertEqual(treffer, ["mail2.pdf", "scan.pdf"])
        self.assertEqual(sm.ausgeblendete_treffer, 1)
        sm._zeige_trefferzahl(2)
        text = sm.app.lbl_treffer.config.call_args.kwargs["text"]
        self.assertEqual(text, "2 Treffer (+1 Mail ausgeblendet)")
        breite = sm.app.lbl_treffer.config.call_args_list[-2].kwargs["width"]
        self.assertGreaterEqual(breite, len(text))                  # das Feld schnitte den Hinweis sonst ab

    def test_sonst_findet_sie_alles(self):
        sm, treffer = self._suche(False)
        self.assertEqual(treffer, ["mail.pdf", "mail2.pdf", "scan.pdf"])
        self.assertEqual(sm.ausgeblendete_treffer, 0)
        sm._zeige_trefferzahl(3)
        self.assertEqual(sm.app.lbl_treffer.config.call_args.kwargs["text"], "3 Treffer")


class TestIndex(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.master = os.path.join(self.tmp, "Sammlung")
        os.makedirs(self.master)
        for name in ("mail.pdf", "scan.pdf"):
            open(os.path.join(self.master, name), "wb").close()
        app = MagicMock()
        app.master_folder = self.master
        self.index = IndexManager(app)
        self.addCleanup(self.index.close)
        self.werte = {"mail.pdf": {"title": "M", "KID_MailID": "mid:1@x", "KID_Richtung": "ein"},
                      "scan.pdf": {"title": "S", "KID_MailID": ""}}

    def _meta(self, pfad):
        return self.werte[os.path.basename(pfad)]

    def test_metadaten_liefern_die_richtung(self):
        with patch("index_manager.PDFHandler.get_metadata", side_effect=self._meta):
            pfade = [os.path.join(self.master, n) for n in ("mail.pdf", "scan.pdf")]
            self.index.metadaten(pfade)                                  # erst lesen, dann aus dem Index
            aus_index = self.index.metadaten(pfade)
        self.assertEqual(aus_index[pfade[0]]["KID_Richtung"], "ein")
        self.assertEqual(aus_index[pfade[1]]["KID_Richtung"], "")

    def test_abgleich_liefert_die_richtung(self):
        with patch("index_manager.PDFHandler.get_metadata", side_effect=self._meta):
            docs = {d["name"]: d for d in self.index.iter_documents()}
        self.assertEqual(docs["mail.pdf"]["richtung"], "ein")
        self.assertEqual(docs["scan.pdf"]["richtung"], "")

    def test_alter_index_liest_nur_mails_einmal_nach(self):
        # Eine ganze große Sammlung neu zu lesen wäre teuer; nur PDFs mit KID_MailID können Mails sein
        with patch("index_manager.PDFHandler.get_metadata", side_effect=self._meta) as lies:
            self.index.iter_documents()
            con = self.index._connect()
            with con:
                con.execute("UPDATE files SET richtung = NULL")
            lies.reset_mock()
            self.index.iter_documents()
            self.assertEqual(lies.call_count, 1)
            self.assertEqual(os.path.basename(lies.call_args.args[0]), "mail.pdf")
            lies.reset_mock()
            self.index.iter_documents()
            lies.assert_not_called()

    def test_datenpfad_bleibt_getrennt(self):
        self.assertFalse(os.path.commonpath([self.master, app_paths.index_path(self.master)]) == self.master)


class TestAusgeblendeteMail(unittest.TestCase):
    def test_regel(self):
        f = index_manager.ist_ausgeblendet
        self.assertTrue(f(os.path.join("A", "m.pdf"), "ein"))
        self.assertFalse(f(os.path.join("A", "s.pdf"), ""))
        self.assertFalse(f(os.path.join("0_Unsicher", "m.pdf"), "ein"))
        self.assertFalse(f(os.path.join("0_Posteingang", "m.pdf"), "aus"))


if __name__ == "__main__":
    unittest.main()
