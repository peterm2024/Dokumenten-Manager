"""Menü-Hilfe (menue_hilfe.py): jede Erklärung vorhanden, Suche nach Menütext, Hilfe-Blöcke."""
import unittest
from unittest.mock import MagicMock

import menue_hilfe
import tool_manager


class _Tool:
    def __init__(self, name, gruppe="", hooks=("main_menu",), description="was", absicht="wofür"):
        self.name = name
        self.menu_label = name + "…"
        self.menu_group = gruppe
        self.menu_hooks = list(hooks)
        self.description = description
        self.absicht = absicht


class TestFesteEintraege(unittest.TestCase):
    def test_alle_festen_eintraege_haben_was_und_wofuer(self):
        self.assertEqual(menue_hilfe.fehlende_erklaerungen(menue_hilfe.FESTE_EINTRAEGE), [])

    def test_keine_doppelten_labels_je_menue(self):
        gesehen = set()
        for e in menue_hilfe.FESTE_EINTRAEGE:
            schluessel = (e.menue, menue_hilfe.normalisiere_label(e.label))
            self.assertNotIn(schluessel, gesehen)
            gesehen.add(schluessel)


class TestNormalisierenUndFinden(unittest.TestCase):
    def test_normalisiere_label(self):
        self.assertEqual(menue_hilfe.normalisiere_label("Einstellungen..."), "einstellungen")
        self.assertEqual(menue_hilfe.normalisiere_label("🛠 PDF-Inspektor"), "pdf-inspektor")
        self.assertEqual(menue_hilfe.normalisiere_label("Dubletten  finden…"), "dubletten finden")

    def test_finde_ueber_label_und_menue(self):
        e = menue_hilfe.finde(menue_hilfe.FESTE_EINTRAEGE, "Einstellungen...")
        self.assertEqual(e.menue, "Datei")
        self.assertIn("Reiter", e.was)
        # gleicher Text in zwei Menüs: Menü-Pfad entscheidet
        ordner = menue_hilfe.finde(menue_hilfe.FESTE_EINTRAEGE, "Umbenennen (F2)", menue="Rechtsklick Ordner")
        datei = menue_hilfe.finde(menue_hilfe.FESTE_EINTRAEGE, "Umbenennen (F2)", menue="Rechtsklick Dokument")
        self.assertIn("Ordner", ordner.was)
        self.assertIn("Dateinamen", datei.was)
        self.assertIsNone(menue_hilfe.finde(menue_hilfe.FESTE_EINTRAEGE, "Gibt es nicht"))
        self.assertIsNone(menue_hilfe.finde(menue_hilfe.FESTE_EINTRAEGE, ""))


class TestToolEintraege(unittest.TestCase):
    def test_tool_liefert_menue_und_kontextmenue_eintrag(self):
        t = _Tool("PDF-Inspektor", "PDF-Werkzeuge", hooks=("main_menu", "context_menu"))
        eintraege = menue_hilfe.eintraege_fuer_tools([t])
        self.assertEqual([(e.menue, e.label) for e in eintraege],
                         [("Tools → PDF-Werkzeuge", "PDF-Inspektor…"), ("Rechtsklick Dokument", "🛠 PDF-Inspektor")])
        self.assertTrue(menue_hilfe.finde(eintraege, "🛠 PDF-Inspektor", menue="Rechtsklick Dokument"))

    def test_reihenfolge_der_menues(self):
        tools = [_Tool("Z", "PDF-Werkzeuge"), _Tool("A", "Vollautomatik"), _Tool("Ohne")]
        menues = []
        for e in menue_hilfe.alle_eintraege(tools):
            if e.menue not in menues:
                menues.append(e.menue)
        self.assertEqual(menues[:2], ["Datei", "Ansicht"])
        self.assertLess(menues.index("Tools → Vollautomatik"), menues.index("Tools → PDF-Werkzeuge"))
        self.assertLess(menues.index("Tools → PDF-Werkzeuge"), menues.index("Hilfe"))
        self.assertLess(menues.index("Hilfe"), menues.index("Rechtsklick Ordner"))
        self.assertIn("Tools", menues)

    def test_echte_tools_haben_beschreibung_und_absicht(self):
        """Jedes ausgelieferte Tool bringt beide Erklärungen mit (BaseTool.absicht ist sonst leer)."""
        manager = tool_manager.ToolManager(MagicMock())
        self.assertGreaterEqual(len(manager.tools), 12)
        eintraege = menue_hilfe.eintraege_fuer_tools(manager.tools)
        fehlt = [(e.menue, e.label) for e in menue_hilfe.fehlende_erklaerungen(eintraege)]
        self.assertEqual(fehlt, [])


class TestHilfeBloecke(unittest.TestCase):
    def test_bloecke_je_menue_und_eintrag(self):
        bloecke = menue_hilfe.hilfe_bloecke([_Tool("Dubletten finden", "Aufräumen")])
        h1 = [c for s, c in bloecke if s == "h1"]
        self.assertTrue(any(c.endswith("\tDatei") for c in h1))
        self.assertTrue(any(c.endswith("\tTools → Aufräumen") for c in h1))
        h2 = [c for s, c in bloecke if s == "h2"]
        self.assertIn("Dubletten finden…", h2)
        self.assertIn("Sammlung öffnen (Hauptordner wählen)...", h2)
        p = [c for s, c in bloecke if s == "p"]
        self.assertTrue(any(c.startswith("Was: was") for c in p))
        self.assertTrue(any(c.startswith("Wofür: wofür") for c in p))

    def test_fehlende_absicht_wird_benannt(self):
        bloecke = menue_hilfe.hilfe_bloecke([_Tool("X", "Aufräumen", absicht="")])
        self.assertTrue(any(c == "Wofür: (keine Erklärung hinterlegt)" for s, c in bloecke if s == "p"))


if __name__ == "__main__":
    unittest.main()
