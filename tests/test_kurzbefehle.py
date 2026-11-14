import os
import re
import unittest
from types import SimpleNamespace

import kurzbefehle as kb

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


def _quelltext(*namen):
    return "\n".join(open(os.path.join(SRC, n), encoding="utf-8").read() for n in namen)


class TestKatalog(unittest.TestCase):
    """Kurzbefehl-Fenster (Peter 28.10.2026): EINE Quelle, und sie muss zum Code passen."""

    def test_jeder_widget_bereich_hat_eintraege(self):
        for bereich in kb.WIDGETS.values():
            self.assertIn(bereich, kb.BEREICHE)
            self.assertTrue(kb.BEREICHE[bereich][1], bereich)
        self.assertTrue(kb.UEBERALL)

    def test_jede_genannte_bindung_gibt_es_im_code(self):
        """Steht eine Taste im Fenster, muss sie auch gebunden sein - sonst erzählt das Fenster Unsinn."""
        quelle = _quelltext("layout_builder.py", "kurzbefehle.py")
        eintraege = list(kb.UEBERALL) + [e for _, liste in kb.BEREICHE.values() for e in liste]
        geprueft = 0
        for eintrag in eintraege:
            if not eintrag["bindung"]:
                continue
            attr, sequenz = eintrag["bindung"]
            if attr == "root":
                muster = r"root\.bind\(\s*\"" + re.escape(sequenz) + '"'
            else:
                muster = r"self\.app\." + re.escape(attr) + r"\.bind\(\s*\"" + re.escape(sequenz) + '"'
            self.assertRegex(quelle, muster, f"{eintrag['taste']}: keine Bindung {attr} {sequenz}")
            geprueft += 1
        self.assertGreater(geprueft, 30)


class TestPosition(unittest.TestCase):
    def test_position_auf_dem_bildschirm(self):
        self.assertTrue(kb.position_sichtbar("+1990+970", 2560, 1440))
        self.assertFalse(kb.position_sichtbar("+3000+200", 2560, 1440))   # zweiter Monitor weg
        self.assertFalse(kb.position_sichtbar("+-5+10", 2560, 1440))
        self.assertFalse(kb.position_sichtbar("", 2560, 1440))


class TestBereichFuer(unittest.TestCase):
    def setUp(self):
        self.app = SimpleNamespace(
            tree_files=".!panedwindow.!frame2.!treeview",
            tree_folders=".!panedwindow.!frame.!treeview",
            canvas_preview=".!panedwindow.!frame3.!canvas",
            date_entry=".!panedwindow.!frame2.!frame.!entry3",
            eigenschaften_panel=SimpleNamespace(tabelle=".!panedwindow.!frame2.!frame"),
        )

    def test_widget_selbst_und_kinder(self):
        self.assertEqual(kb.bereich_fuer(self.app, ".!panedwindow.!frame2.!treeview"), "dokumentenliste")
        self.assertEqual(kb.bereich_fuer(self.app, ".!panedwindow.!frame3.!canvas.!label"), "vorschau")

    def test_eingabefeld_in_der_tabelle_vor_der_tabelle(self):
        self.assertEqual(kb.bereich_fuer(self.app, ".!panedwindow.!frame2.!frame.!entry3"), "datum")
        self.assertEqual(kb.bereich_fuer(self.app, ".!panedwindow.!frame2.!frame.!entry5"), "eigenschaften")

    def test_unbekannt_oder_fehlend(self):
        self.assertIsNone(kb.bereich_fuer(self.app, ".!toplevel.!label"))
        self.assertIsNone(kb.bereich_fuer(self.app, None))
        self.assertIsNone(kb.bereich_fuer(SimpleNamespace(), ".!panedwindow"))


if __name__ == "__main__":
    unittest.main()
