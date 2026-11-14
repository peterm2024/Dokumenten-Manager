import unittest

import ablage_gedaechtnis
import auto_pilot
import begleitet

ORDNER = ["0_Posteingang", "0_Unsicher", "M - N - O - P - Q - R", "M - N - O - P - Q - R\\Musterversicherung"]


def entscheidung(**aenderungen):
    e = {"pdf_path": "C:/Sammlung/0_Posteingang/scan.pdf", "titel": "Beitragsrechnung 2025", "titel_korrekturen": [],
         "tags": ["Versicherung"], "neue_tags": [], "tag_ersetzungen": [], "datum": "2025-01-15",
         "absender": "Musterversicherung AG", "ordnername": "Musterversicherung",
         "zielordner": "M - N - O - P - Q - R\\Musterversicherung", "ordner_neu": False, "ordner_per_alias": False,
         "ordner_gedaechtnis": 3, "ordner_hinweis": "Gedächtnis", "objekte": [], "neuer_dateiname": "",
         "sicher": False, "probleme": ["Ähnlicher Ordner vorhanden: Musterversicherung"]}
    e.update(aenderungen)
    return e


class TestUebernehmen(unittest.TestCase):
    def test_gelber_vorschlag_wird_mit_dem_ordner_des_nutzers_sicher(self):
        e, offen = begleitet.uebernimm(entscheidung(), "M - N - O - P - Q - R\\Musterversicherung",
                                       "Beitragsrechnung 2025", "2025-01-15", "Versicherung", ORDNER)
        self.assertEqual(offen, [])
        self.assertTrue(e["sicher"])
        self.assertEqual(e["neuer_dateiname"], "20250115_Beitragsrechnung 2025.pdf")
        self.assertEqual((e["ordner_per_alias"], e["ordner_gedaechtnis"]), (False, 3))    # unverändert übernommen

    def test_korrekturen_und_neuer_ordner(self):
        e, offen = begleitet.uebernimm(entscheidung(), "  S - T - U\\Stadtwerke   Musterstadt ", "Jahresabrechnung",
                                       "15.03.2025", "Strom, Musterweg 3", ORDNER)
        self.assertEqual(offen, [])
        self.assertEqual((e["zielordner"], e["ordner_neu"]), ("S - T - U\\Stadtwerke Musterstadt", True))
        self.assertEqual((e["titel"], e["datum"], e["tags"]), ("Jahresabrechnung", "2025-03-15", ["Strom", "Musterweg 3"]))

    def test_ohne_datum_bleibt_offen(self):
        e, offen = begleitet.uebernimm(entscheidung(), "M - N - O - P - Q - R\\Musterversicherung", "Brief", "",
                                       "Versicherung", ORDNER)
        self.assertFalse(e["sicher"])
        self.assertEqual(offen, [auto_pilot._PROBLEM_KEIN_DATUM])

    def test_dubletten_verdacht_gilt_als_gesehen(self):
        e, offen = begleitet.uebernimm(entscheidung(probleme=["vermutlich Dublette zu „x.pdf“"]),
                                       "M - N - O - P - Q - R\\Musterversicherung", "Brief", "2025-01-15",
                                       "Versicherung", ORDNER)
        self.assertEqual((e["sicher"], offen), (True, []))
        self.assertIn("vermutlich Dublette zu „x.pdf“", e["probleme"])          # bleibt fürs Protokoll stehen

    def test_fokus_dorthin_wo_etwas_fehlt(self):
        # KID-Test 04.11.: „2024-09-XX“ war unplausibel, markiert war aber der Zielordner
        self.assertEqual(begleitet.feld_fuer_problem(entscheidung(probleme=[auto_pilot._PROBLEM_KEIN_DATUM,
                                                                             "Ähnlicher Ordner vorhanden: x"])), "datum")
        self.assertEqual(begleitet.feld_fuer_problem(entscheidung()), "ziel")
        self.assertIsNone(begleitet.feld_fuer_problem(entscheidung(probleme=["vermutlich Dublette zu „x.pdf“"])))
        self.assertIsNone(begleitet.feld_fuer_problem(entscheidung(sicher=True, probleme=[])))

    def test_leere_tags_halten_nicht_auf(self):
        # Peter 04.11.2026: „Dokumente, da benötige ich keine Tags - reine Archivierung“
        e, offen = begleitet.uebernimm(entscheidung(), "M - N - O - P - Q - R\Musterversicherung", "Kontoauszug",
                                       "2025-01-15", "  ", ORDNER)
        self.assertEqual((e["sicher"], e["tags"], offen), (True, [], []))
        self.assertIsNone(begleitet.feld_fuer_problem(entscheidung(probleme=[auto_pilot._PROBLEM_KEINE_TAGS])))

    def test_scandatum_wenn_kein_datum(self):
        # Peter 04.11.2026: „wenn kein Datum erkannt wird, sollte einfach das Scandatum benutzt werden“
        self.assertEqual(begleitet.datum_vorschlag(entscheidung(datum="2024-09-XX"), "2025-03-02"), ("2025-03-02", True))
        self.assertEqual(begleitet.datum_vorschlag(entscheidung(), "2025-03-02"), ("2025-01-15", False))
        self.assertEqual(begleitet.datum_vorschlag(entscheidung(datum=""), ""), ("", False))

    def test_zurueckstellen_und_prognose(self):
        e = begleitet.zurueckstellen(entscheidung(sicher=True, probleme=[]))
        self.assertFalse(e["sicher"])
        self.assertIn(auto_pilot.PROBLEM_ZURUECKGESTELLT, e["probleme"])
        self.assertEqual(begleitet.prognose([entscheidung(sicher=True), None, entscheidung(), entscheidung(sicher=True)]),
                         (2, 3))


class TestRueckfragen(unittest.TestCase):
    ZIEL = "U - V - W - X - Y - Z\\Versicherungskasse Musterland"

    def setUp(self):
        self.gedaechtnis = ablage_gedaechtnis.Gedaechtnis()
        for _ in range(3):
            self.gedaechtnis.stimme("Versicherungskasse Musterland", self.ZIEL)
        self.r = begleitet.Rueckfragen()

    def test_b4_andere_schreibweise_im_gewaehlten_ordner(self):
        vorschlag = entscheidung(absender="Landesbrandversicherung Musterland AG", zielordner="L\\Landesbrand (neu)")
        abgelegt = dict(vorschlag, zielordner=self.ZIEL)
        frage = self.r.nach_ablage(vorschlag, abgelegt, self.gedaechtnis, {})
        self.assertEqual((frage["art"], frage["schluessel"], frage["ordner"]),
                         ("Absender", "Landesbrandversicherung Musterland AG", self.ZIEL))
        self.assertIn("derselbe Absender wie „Versicherungskasse Musterland“", frage["text"])
        self.r.abgelehnt_merken(frage)                                           # Nein: im Durchgang nie wieder
        self.assertIsNone(self.r.nach_ablage(vorschlag, abgelegt, self.gedaechtnis, {}))

    def test_b4_nicht_ohne_korrektur_ohne_fremden_absender_oder_mit_alias(self):
        vorschlag = entscheidung(absender="Landesbrandversicherung Musterland AG", zielordner=self.ZIEL)
        self.assertIsNone(self.r.nach_ablage(vorschlag, dict(vorschlag), self.gedaechtnis, {}))   # übernommen
        anders = dict(vorschlag, zielordner="A\\Anderer Ordner")
        self.assertIsNone(self.r.nach_ablage(vorschlag, anders, self.gedaechtnis, {}))          # dort kein anderer
        abgelegt = dict(vorschlag, zielordner=self.ZIEL)
        vorschlag_neu = dict(vorschlag, zielordner="L\\Landesbrand")
        self.assertIsNone(self.r.nach_ablage(vorschlag_neu, abgelegt, self.gedaechtnis,
                                             {"Landesbrandversicherung Musterland": self.ZIEL}))  # Alias schon da
        selbst = dict(vorschlag_neu, absender="Versicherungskasse Musterland")
        self.assertIsNone(self.r.nach_ablage(selbst, dict(selbst, zielordner=self.ZIEL), self.gedaechtnis, {}))

    def test_b5_objekt_alias_beim_zweiten_mal(self):
        vorschlag = entscheidung(absender="", objekte=["Musterweg 3"], zielordner="")
        abgelegt = dict(vorschlag, zielordner="M\\Mustermann Musterweg")
        self.assertIsNone(self.r.nach_ablage(vorschlag, abgelegt, self.gedaechtnis, {}))       # erstes Mal
        frage = self.r.nach_ablage(vorschlag, abgelegt, self.gedaechtnis, {})
        self.assertEqual((frage["art"], frage["schluessel"]), ("Objekt", "Objekt: Musterweg 3"))
        self.assertIn("Schon 2 Dokumente ohne Absender zu „Musterweg 3“", frage["text"])
        self.assertIsNone(self.r.nach_ablage(vorschlag, abgelegt, self.gedaechtnis,
                                             {"Objekt: Musterweg 3": "M\\Mustermann Musterweg"}))   # Alias schon da


if __name__ == "__main__":
    unittest.main()
