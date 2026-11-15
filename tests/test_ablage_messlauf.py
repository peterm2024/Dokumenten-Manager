"""Tests für ablage_messlauf.py (Etappe 9, 14.11.2026) - mit erfundenen Dokumenten, ohne den privaten Korpus.

Der Messlauf soll die Vollautomatik so nachbilden, wie der Dienst entscheidet; geprüft werden hier die Teile, an
denen eine Abweichung still falsche Zahlen ergäbe: Ordnerliste wie im Betrieb, Lernen nur aus sicheren Ablagen,
Bewertung und Rückschritt-Erkennung.
"""
import os
import unittest

import ablage_messlauf as m

# Tupel: ein Test, der die Startliste verändert, darf die anderen nicht beeinflussen
ORDNER = ("A - B - C - D - E", "F - G - H - I - J", "F - G - H - I - J\\Finanzamt", "K - L - M - N - O",
          "P - Q - R - S - T", "P - Q - R - S - T\\Stadtwerke", "U - V - W - X - Y - Z")


def ki(absender, ordnername=None, ort="", title="Schreiben", datum="2024-03-01"):
    return {"absender": absender, "ordnername": ordnername or absender, "ort": ort, "title": title,
            "datum": datum, "tags": [], "tag_kategorien": {}, "empfaenger": "", "objekt": ""}


def dok(nr, absender, original, **kw):
    return {"nr": nr, "name": f"scan_{nr}.pdf", "original": original, "ki": ki(absender, **kw)}


class TestOrdnerliste(unittest.TestCase):
    def test_wie_im_betrieb_ohne_posteingang_und_unsicher(self):
        liste = m.ordnerliste(m.vorlage_ordner())
        self.assertNotIn("0_Posteingang", liste)
        self.assertNotIn("0_Unsicher", liste)
        self.assertIn(os.path.join("P - Q - R - S - T", "Stadtwerke"), liste)


class TestLauf(unittest.TestCase):
    def setUp(self):
        self.tags, self.kategorien = m.katalog()

    def test_ki_fehler_wird_gezaehlt_nicht_entschieden(self):
        d = {"nr": 1, "name": "x.pdf", "original": "", "ki": {"fehler": "Zeitüberschreitung"}}
        z, _ = m.bewerte_bestand(m.lauf([d], ORDNER, self.tags, self.kategorien))
        self.assertEqual(z, {"KI-Fehler": 1})

    def test_neuer_ordner_zaehlt_erst_nach_sicherer_ablage(self):
        # Wie im Dienst (FALLSTRICKE #83): ein sicher angelegter Ordner steht danach in der Liste, das zweite
        # Dokument desselben Absenders landet im selben Ordner
        neu = "K - L - M - N - O\\Musterwerke Beispiel GmbH"   # die Rechtsform bleibt im Ordnernamen
        dokumente = [dok(1, "Musterwerke Beispiel GmbH", neu), dok(2, "Musterwerke Beispiel GmbH", neu)]
        ergebnis = m.lauf(dokumente, ORDNER, self.tags, self.kategorien)
        (_, e1), (_, e2) = ergebnis
        self.assertTrue(e1["sicher"] and e1["ordner_neu"], e1["probleme"])
        self.assertEqual(e1["zielordner"], neu)
        self.assertFalse(e2["ordner_neu"], e2["probleme"])
        self.assertEqual(e2["zielordner"], e1["zielordner"])
        self.assertEqual(m.bewerte_bestand(ergebnis)[0]["richtig"], 2)

    def test_startliste_bleibt_unveraendert(self):
        liste = list(ORDNER)
        m.lauf([dok(1, "Musterwerke Beispiel GmbH", "")], liste, self.tags, self.kategorien)
        self.assertEqual(liste, list(ORDNER))

    def test_zweitmeinung_sperrt_sichere_ablage(self):
        # Aufgezeichnete Rangliste: das Entscheidungsmodell hält einen anderen Ordner für passender (p >= Sperre)
        d = dok(7, "Musterwerke Beispiel GmbH", "P - Q - R - S - T\\Stadtwerke")
        ohne = m.lauf([d], ORDNER, self.tags, self.kategorien)[0][1]
        self.assertTrue(ohne["sicher"])
        rang = {"7": [["P - Q - R - S - T\\Stadtwerke", 0.97], ["F - G - H - I - J\\Finanzamt", 0.01]]}
        mit = m.lauf([d], ORDNER, self.tags, self.kategorien, ranglisten=rang)[0][1]
        self.assertFalse(mit["sicher"], mit["probleme"])
        # Ordner, die nicht in der Liste stehen, zählen nicht (aufgenommen über eine andere Ordnerliste)
        fremd = {"7": [["Gibt es nicht", 0.99]]}
        self.assertTrue(m.lauf([d], ORDNER, self.tags, self.kategorien, ranglisten=fremd)[0][1]["sicher"])

    def test_unsichere_ablage_lehrt_nichts(self):
        # Ohne Datum unsicher: Der vorgeschlagene neue Ordner existiert nicht und darf beim nächsten Dokument
        # nicht als vorhanden gelten (Nachtlauf 28.10.2026: 15x „Zielordner existiert nicht mehr“)
        dokumente = [dok(1, "Musterwerke Beispiel GmbH", "", datum=""), dok(2, "Musterwerke Beispiel GmbH", "")]
        (_, e1), (_, e2) = m.lauf(dokumente, ORDNER, self.tags, self.kategorien)
        self.assertFalse(e1["sicher"])
        self.assertTrue(e2["sicher"] and e2["ordner_neu"], e2["probleme"])


class TestBewertung(unittest.TestCase):
    @staticmethod
    def e(ziel, sicher=True, neu=False):
        return {"zielordner": ziel, "sicher": sicher, "ordner_neu": neu}

    def test_bestand(self):
        ergebnis = [({"nr": 1, "original": "A\\X"}, self.e("A\\X")),
                    ({"nr": 2, "original": "A\\X"}, self.e("A\\Y")),
                    ({"nr": 3, "original": "A\\X"}, self.e("A\\Z", neu=True)),
                    ({"nr": 4, "original": "A\\X"}, self.e("a\\x", sicher=False)),   # Groß/klein egal (Windows)
                    ({"nr": 5, "original": "A\\X"}, self.e("A\\Y", sicher=False)),
                    ({"nr": 6, "original": "A\\X"}, None)]
        z, faelle = m.bewerte_bestand(ergebnis)
        self.assertEqual(dict(z), {"richtig": 1, "still falsch (vorhandener Ordner)": 1,
                                   "still falsch (neuer Ordner)": 1, "unsicher, Vorwahl richtig": 1,
                                   "unsicher, Vorwahl anders": 1, "KI-Fehler": 1})
        self.assertEqual([nr for nr, _ in faelle], [1, 2, 3, 4, 5, 6])

    def test_frisch_mischt_originale(self):
        ergebnis = [({"nr": 1, "original": "Alt\\Stadtwerke"}, self.e("S\\Stadtwerke", neu=True)),
                    ({"nr": 2, "original": "Alt\\Stadtwerke"}, self.e("S\\Stadtwerke")),
                    ({"nr": 3, "original": "Alt\\Steuer"}, self.e("S\\Stadtwerke")),          # mischt
                    ({"nr": 4, "original": "Alt\\Stadtwerke"}, self.e("S\\Stadtwerke 2", neu=True)),   # Doppel
                    ({"nr": 5, "original": "Alt\\Bank"}, self.e("B\\Nie angelegt")),           # Phantom
                    ({"nr": 6, "original": "Alt\\Bank"}, self.e("S\\Stadtwerke", sicher=False))]
        z, _ = m.bewerte_frisch(ergebnis, ["S", "B"])
        self.assertEqual(dict(z), {"sicher ok": 2, "still falsch": 1, "Doppelordner": 1, "Phantom-Ordner": 1,
                                   "unsicher, Vorwahl falsch": 1})


class TestRueckschritt(unittest.TestCase):
    def test_richtung_je_zahl(self):
        vorher = {"richtig": 200, "still falsch (vorhandener Ordner)": 50, "unsicher, Vorwahl anders": 60}
        self.assertEqual(m.rueckschritte("bestand", dict(vorher, **{"unsicher, Vorwahl anders": 90}), vorher), [])
        self.assertEqual(len(m.rueckschritte("bestand", dict(vorher, richtig=199), vorher)), 1)
        schlechter = dict(vorher, **{"still falsch (vorhandener Ordner)": 51})
        self.assertEqual(m.rueckschritte("bestand", schlechter, vorher),
                         ["bestand: still falsch (vorhandener Ordner) 50 -> 51"])
        self.assertEqual(m.rueckschritte("bestand", dict(vorher, richtig=230), vorher), [])   # besser ist kein Rückschritt

    def test_frisch_neue_art_zaehlt_ab_null(self):
        self.assertEqual(m.rueckschritte("frisch", {"Phantom-Ordner": 1}, {"sicher ok": 5}),
                         ["frisch: Phantom-Ordner 0 -> 1"])


if __name__ == "__main__":
    unittest.main()
