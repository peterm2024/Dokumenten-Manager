"""Auswertung des Messlaufs (messlauf.py): wann ein Szenario als Rückschritt gilt bzw. den Lauf scheitern lässt."""
import os
import tomllib
import unittest

import messlauf

EINST = {"rueckschritt_prozent": 15.0, "rueckschritt_min_s": 0.05}


class TestBewerte(unittest.TestCase):

    def test_median_der_wiederholungen(self):
        e = messlauf.bewerte("a", [0.9, 0.3, 0.32], {"budget_s": 1.0}, {}, EINST)
        self.assertAlmostEqual(e["median"], 0.32)
        self.assertFalse(e["ueber_budget"])

    def test_rueckschritt_braucht_prozent_und_mindestabstand(self):
        szen = {"budget_s": 5.0}
        # +20 %, aber nur 0,02 s: Timer-Rauschen, kein Rückschritt
        self.assertFalse(messlauf.bewerte("a", [0.12], szen, {"a": 0.10}, EINST)["rueckschritt"])
        # +10 % bei 1 s: unter der Prozent-Schwelle
        self.assertFalse(messlauf.bewerte("a", [1.10], szen, {"a": 1.00}, EINST)["rueckschritt"])
        # +20 % und 0,2 s: Rückschritt
        self.assertTrue(messlauf.bewerte("a", [1.20], szen, {"a": 1.00}, EINST)["rueckschritt"])

    def test_ohne_vergleichswert_kein_rueckschritt(self):
        self.assertFalse(messlauf.bewerte("a", [9.0], {"budget_s": 1.0}, {}, EINST)["rueckschritt"])

    def test_nur_pflicht_budget_laesst_scheitern(self):
        ergebnisse = {
            "hinweis": messlauf.bewerte("hinweis", [3.0], {"budget_s": 1.0}, {}, EINST),
            "pflicht": messlauf.bewerte("pflicht", [3.0], {"budget_s": 1.0, "pflicht": True}, {}, EINST),
            "langsamer": messlauf.bewerte("langsamer", [2.0], {"budget_s": 5.0}, {"langsamer": 1.0}, EINST),
        }
        self.assertEqual(sorted(messlauf.gescheitert(ergebnisse)), ["langsamer", "pflicht"])


class TestBudgetDatei(unittest.TestCase):

    def test_jedes_szenario_hat_text_und_budget(self):
        with open(os.path.join(messlauf.PROJEKT, "messlauf_budgets.toml"), "rb") as f:
            budgets = tomllib.load(f)
        for name, szen in budgets["szenario"].items():
            with self.subTest(szenario=name):
                self.assertIn("text", szen)
                self.assertGreater(szen["budget_s"], 0)


if __name__ == "__main__":
    unittest.main()
