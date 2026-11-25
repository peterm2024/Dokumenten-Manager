"""Wiki: was die KI schon gelesen hat (tools/wiki_lesen.py, Etappe 12 W7b). Nur Musterdaten."""
import os
import shutil
import tempfile
import threading
import time
import tkinter as tk
import types
import unittest
from unittest.mock import patch

import app_paths
import wissen
import wissen_ki
from tests.test_begleitet_erfassen import Einstellungen, threads_beenden
from tools import wiki as wf
from tools import wiki_lesen as wl


def dok(pfad, kid_id="", datum="", mail=False, zeichen=500):
    return {"rel_path": pfad.replace("/", os.sep), "titel": os.path.basename(pfad)[:-4], "kid_id": kid_id, "datum": datum,
            "mail": mail, "zeichen": zeichen}


DOKUMENTE = [dok("S/Stadtwerke/Alt.pdf", "A", "2020-01-01"), dok("S/Stadtwerke/Neu.pdf", "B", "2026-01-01"),
             dok("S/Stadtwerke/Ohne Datum.pdf"), dok("S/Bild.pdf", zeichen=29), dok("S/Knapp.pdf", "K", "2021-01-01", zeichen=30),
             dok("S/Unbekannt.pdf", datum="2022-01-01", zeichen=None), dok("Mails/Mail.pdf", mail=True),
             dok("Mails/Anhang.pdf", datum="2023-01-01"), dok("0_Posteingang/Scan.pdf"), dok("00_posteingang/Scan.pdf"),
             dok("0_Unsicher/Rest.pdf"), dok("Lose.pdf", "L"), dok("Stadt/Brief.pdf", "X")]


class TestZaehlung(unittest.TestCase):
    def test_je_ordner_samt_unterordnern(self):
        stand = wl.ordner_stand(DOKUMENTE, {"A", "L", "", "fremd"})
        self.assertEqual({o: tuple(z.values()) for o, z in stand.items()}, {       # Dokumente, gelesen, offen, ohne Text
            "": (9, 2, 6, 1), "Mails": (1, 0, 1, 0), "S": (6, 1, 4, 1), os.path.join("S", "Stadtwerke"): (3, 1, 2, 0),
            "Stadt": (1, 0, 1, 0)})
        self.assertEqual(list(stand), ["", "Mails", "S", os.path.join("S", "Stadtwerke"), "Stadt"])
        self.assertEqual(wl.ordner_stand(DOKUMENTE, set(), mails=True)["Mails"]["dokumente"], 2)
        self.assertEqual(wl.ordner_stand([], set()), {})
        # ein Unterordner kommt direkt nach seinem Ordner, auch wenn ein Name mit Leerzeichen dazwischen passte
        reihe = wl.ordner_stand([dok("A B/x.pdf"), dok("A/Z/x.pdf"), dok("A/x.pdf")], set())
        self.assertEqual(list(reihe), ["", "A", os.path.join("A", "Z"), "A B"])

    def test_gelesen_geht_vor_ohne_text(self):
        self.assertEqual(wl.zustand(dok("x.pdf", "A", zeichen=0), {"A"}), "gelesen")
        self.assertEqual(wl.zustand(dok("x.pdf", "A", zeichen=0), {"B"}), "ohne_text")
        self.assertEqual(wl.zustand(dok("x.pdf", ""), {""}), "offen")             # ohne Dokument-ID nie gelesen

    def test_offene_die_neuesten_zuerst(self):
        def namen(*args, **kw):
            return [d["titel"] for d in wl.offene(DOKUMENTE, *args, **kw)]
        self.assertEqual(namen("S", {"A"}), ["Neu", "Unbekannt", "Knapp", "Ohne Datum"])
        self.assertEqual(namen("S", {"A"}, zuletzt={os.path.join("S", "Stadtwerke", "Neu.pdf")}),
                         ["Unbekannt", "Knapp", "Ohne Datum", "Neu"])
        self.assertEqual(namen("Stadt", set()), ["Brief"])                        # nicht „Stadtwerke“
        self.assertEqual(namen("", {"A", "B", "L", "K", "X"}), ["Anhang", "Unbekannt", "Ohne Datum"])
        self.assertIn("Mail", namen("", set(), mails=True))


class TestFenster(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(threads_beenden)
        self.addCleanup(self.root.destroy)
        basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, basis, True)
        sammlung = os.path.join(basis, "Sammlung")
        os.makedirs(sammlung)
        self.dokumente = [dict(d) for d in DOKUMENTE] + [dok(f"Viele/{n:02d}.pdf", f"V{n}") for n in range(25)]
        self.index = types.SimpleNamespace(lesestand=lambda: self.dokumente)
        app = types.SimpleNamespace(root=self.root, master_folder=sammlung, config=Einstellungen(), logger=None,
                                    index_manager=self.index)
        for ziel in ("tools.wiki.UIUtils.werkzeugfenster", "tools.wiki_lesen.UIUtils.werkzeugfenster"):
            p = patch(ziel)                                            # sonst unsichtbar (FALLSTRICKE #95)
            p.start()
            self.addCleanup(p.stop)
        self.w = wissen.Wissen(sammlung)
        self.w.merke_gelesen(["A", "L"])
        self.f = wf.WikiFenster(app)
        self.addCleanup(lambda: self.f.winfo_exists() and self.f.destroy())

    def oeffne(self):
        d = self.f._dokumente_lesen()
        ende = time.time() + 10
        while d._after is not None and time.time() < ende:
            self.root.update()
            time.sleep(0.02)
        return d

    def test_zahlen_weiterlesen_und_nachziehen(self):
        d = self.oeffne()
        self.assertIs(self.f._dokumente_lesen(), d)                                # höchstens eins
        self.assertEqual(d.lbl_stand.cget("text"), "2 von 34 Dokumenten gelesen, 31 offen, 1 ohne erkannten Text.")
        self.assertEqual([str(x) for x in d.tree.item("o:S", "values")], ["6", "1", "4", "1"])
        self.assertEqual([str(x) for x in d.tree.item("o:Stadt", "values")], ["1", "–", "1", "–"])
        self.assertEqual((d.ordner(), d.btn_weiter.cget("text")), ("", "Weiterlesen (20 von 31)"))
        d.var_mails.set(True)
        d._fuelle()
        self.assertEqual(d.btn_weiter.cget("text"), "Weiterlesen (20 von 32)")
        d.var_mails.set(False)
        d.tree.selection_set("o:S")
        self.root.update()
        self.assertEqual(d.btn_weiter.cget("text"), "Weiterlesen (4)")
        self.f.zuletzt_lesen = {os.path.join("S", "Stadtwerke", "Neu.pdf")}
        with patch.object(self.f, "dinge_lesen") as lesen:
            d.weiterlesen()
            self.assertEqual([x["titel"] for x in lesen.call_args[0][0]], ["Unbekannt", "Knapp", "Ohne Datum", "Neu"])
            d.tree.selection_set("o:")
            self.root.update()
            d.weiterlesen()
            self.assertEqual(len(lesen.call_args[0][0]), wissen_ki.HOECHSTENS)
            self.f.dinge = types.SimpleNamespace(winfo_exists=lambda: True, lift=lambda: None)   # schon ein Lauf offen
            d.weiterlesen()
            self.assertEqual(lesen.call_count, 2)
            self.f.dinge = None
        # nach einem Lauf: drei gelesen (eins bekam seine Dokument-ID erst jetzt), eins ohne Text
        d.tree.selection_set("o:S")
        d.tree.item("o:S", open=True)
        s = os.path.join("S", "Stadtwerke")
        ids = {os.path.join(s, "Neu.pdf"): "B", os.path.join("S", "Knapp.pdf"): "K", os.path.join(s, "Ohne Datum.pdf"): "N"}
        self.w.merke_gelesen(ids.values())
        self.f.nach_lesen(ids, [os.path.join("S", "Unbekannt.pdf")], [])
        self.root.update()
        self.assertEqual([str(x) for x in d.tree.item("o:S", "values")], ["6", "4", "–", "2"])
        self.assertEqual((d.ordner(), bool(d.tree.item("o:S", "open"))), ("S", True))   # Markierung und Aufgeklapptes bleiben
        self.assertEqual((str(d.btn_weiter.cget("state")), d.tree.item("o:S", "tags")), ("disabled", ("fertig",)))
        self.assertEqual(self.f.zuletzt_lesen, set())

    def test_vom_rechtsklick_im_ordnerbaum(self):
        werkzeug, app = wf.WikiTool(), self.f.app
        self.assertIn("folder_menu", werkzeug.menu_hooks)

        def pfad(*teile):
            return os.path.join(app.master_folder, *teile)
        self.assertEqual([werkzeug.ordner_moeglich(app, p) for p in (
            pfad(), pfad("S"), pfad("0_Posteingang"), pfad("S", "00_Posteingang"), pfad("0_Unsicher"),
            os.path.join(app_paths.trash_dir(app.master_folder), "Alt"))], [True, True, False, False, False, False])
        weiter = threading.Event()
        self.addCleanup(weiter.set)
        self.index.lesestand = lambda: weiter.wait(5) and self.dokumente
        with patch("tools.wiki.WikiFenster", return_value=self.f), patch.object(
                wf.UIUtils, "einzelfenster", side_effect=lambda schluessel, erzeugen: erzeugen()):
            werkzeug.oeffne_ordner(app, pfad("S", "Stadtwerke"))
            d = self.f.lesen
            self.assertIsNone(d.ordner())                                          # der Stand wird noch geholt
            d.weiterlesen()                                                        # tut noch nichts
            weiter.set()
            ende = time.time() + 10
            while d._after is not None and time.time() < ende:
                self.root.update()
            self.assertEqual((d.ordner(), d.btn_weiter.cget("text")), (os.path.join("S", "Stadtwerke"), "Weiterlesen (2)"))
            self.assertTrue(d.tree.item("o:S", "open"))                            # aufgeklappt bis dorthin
            d.zeige_ordner("Stadt")                                                # schon offen: umspringen
            self.root.update()
            self.assertEqual((d.ordner(), d.btn_weiter.cget("text")), ("Stadt", "Weiterlesen (1)"))
            d.zeige_ordner("")
            self.assertEqual(d.ordner(), "")
            # ein Ordner ohne Dokumente: nichts anderes markieren, sonst läse „Weiterlesen“ die ganze Sammlung
            d.zeige_ordner(os.path.join("S", "Leer"))
            self.assertIsNone(d.ordner())
            self.assertIn("Im Ordner „Leer“ gibt es nichts zu lesen", d.lbl_stand.cget("text"))
            self.assertEqual(str(d.btn_weiter.cget("state")), "disabled")
            with patch.object(self.f, "dinge_lesen") as lesen:
                d.weiterlesen()
            lesen.assert_not_called()
            d.destroy()

    def test_index_nicht_lesbar_und_leere_sammlung(self):
        self.dokumente = []
        d = self.oeffne()
        self.assertEqual(d.lbl_stand.cget("text"), "Hier gibt es noch keine Dokumente zum Lesen.")
        self.assertEqual(str(d.btn_weiter.cget("state")), "disabled")
        self.index.lesestand = lambda: 1 / 0
        d.aktualisiere()
        while d._after is not None:
            self.root.update()
        self.assertIn("nicht lesbar (ZeroDivisionError)", d.lbl_stand.cget("text"))
        d.destroy()


if __name__ == "__main__":
    unittest.main()
