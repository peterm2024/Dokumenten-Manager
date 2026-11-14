import os
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

import auto_pilot
from tools.auto_filer import AutoFilerPreviewWindow


class TestZielordnerAuswahl(unittest.TestCase):
    """Peter 02.11.2026: ein eben angelegter Ordner fehlte in der Zielordner-Auswahl der Ablage-Vorschau."""

    def setUp(self):
        self.sammlung = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.sammlung, True)
        os.makedirs(os.path.join(self.sammlung, "Musterversicherung"))
        self.fenster = types.SimpleNamespace(app=types.SimpleNamespace(master_folder=self.sammlung),
                                             ordnerliste=auto_pilot.sammle_ordnerliste(self.sammlung),
                                             neue_ordner={"Stadtwerke Musterstadt", "Noch nicht da"})

    def test_neu_angelegter_ordner_kommt_dazu(self):
        liste = self.fenster.ordnerliste
        os.makedirs(os.path.join(self.sammlung, "Stadtwerke Musterstadt"))       # nach der Analyse angelegt
        AutoFilerPreviewWindow._ordnerliste_auffrischen(self.fenster)
        self.assertIs(self.fenster.ordnerliste, liste)                           # gleiche Liste (Analyse-Thread)
        self.assertEqual(sorted(liste), ["Musterversicherung", "Stadtwerke Musterstadt"])
        self.assertEqual(self.fenster.neue_ordner, {"Noch nicht da"})


class TestErgebnisKlick(unittest.TestCase):
    """Klick auf „Ergebnis“: grün -> gelb (Peter 02.11.2026), erneuter Klick zurück."""

    def test_gruen_wird_gelb_und_zurueck(self):
        e = {"sicher": True, "probleme": [], "datum": "2025-01-15", "titel": "Beitrag", "neuer_dateiname": "x.pdf"}
        gezeigt = []
        fenster = types.SimpleNamespace(_zeige_entscheidung=lambda iid, neu: gezeigt.append(neu))
        with patch("tools.auto_filer.bestaetigung.frage", return_value=True) as frage:
            AutoFilerPreviewWindow._frage_freigabe(fenster, "i1", e)
            self.assertFalse(gezeigt[-1]["sicher"])
            self.assertEqual(gezeigt[-1]["probleme"], [auto_pilot.PROBLEM_ZURUECKGESTELLT])
            AutoFilerPreviewWindow._frage_freigabe(fenster, "i1", gezeigt[-1])
            self.assertTrue(gezeigt[-1]["sicher"])
            self.assertEqual(frage.call_count, 1)                                # Zurücknehmen fragt nicht
        with patch("tools.auto_filer.bestaetigung.frage", return_value=False):
            AutoFilerPreviewWindow._frage_freigabe(fenster, "i1", e)
        self.assertEqual(len(gezeigt), 2)                                        # „Nein“ ändert nichts


if __name__ == "__main__":
    unittest.main()
