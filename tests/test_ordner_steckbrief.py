"""Tests für ordner_steckbrief.py und Regel D (auto_pilot.wende_steckbrief_an) - KONZEPT_ORDNER_STECKBRIEF.md.
Alle Nummern, IBANs und Adressen sind erfunden."""
import unittest
from unittest.mock import MagicMock, patch

import auto_pilot
import ordner_steckbrief as osb

STADTWERKE = "S - T\\Stadtwerke Musterstadt"
VERSICHERUNG = "V - W\\Musterversicherung"
ORDNER = [STADTWERKE, VERSICHERUNG, "A - B\\Finanzamt"]

BRIEF_STADTWERKE = """Stadtwerke Musterstadt GmbH, Werkstraße 7, 12345 Musterstadt
Kundennummer: 4711 0815   Vertragskonto 99887766
Rechnung vom 03.02.2024, Betrag 123,45 EUR. IBAN DE12 3456 7890 1234 5678 90
Max Mustermann, Musterweg 3, 12345 Musterstadt"""
BRIEF_VERSICHERUNG = """Musterversicherung AG, Policenallee 1
Versicherungsnummer: HV-2023-55512   Max Mustermann, Musterweg 3, 12345 Musterstadt"""


class TestMerkmale(unittest.TestCase):
    def test_nummern_iban_adressen(self):
        m = osb.merkmale(BRIEF_STADTWERKE)
        self.assertIn(("Nummer", "47110815"), m)              # Leerzeichen in Nummern fallen weg
        self.assertIn(("IBAN", "DE12345678901234567890"), m)
        self.assertIn(("Adresse", "werkstr. 7"), m)           # straße -> str., klein
        self.assertIn(("Adresse", "musterweg 3"), m)

    def test_adresse_am_zeilenende_gleich_wie_mit_komma(self):
        # KID-Test 15.11.2026: im Anschriftfeld folgt der Ort in der nächsten Zeile - „musterweg 3\n“ zählte als
        # anderes Merkmal als „musterweg 3“ und teilte die Stimmen
        self.assertIn(("Adresse", "musterweg 3"), osb.merkmale("Max Mustermann\nMusterweg 3\n12345 Musterstadt"))
        self.assertIn(("Adresse", "hauptstr. 5a"), osb.merkmale("Hauptstraße 5 a, 12345 Musterstadt"))

    def test_datum_jahr_und_betrag_sind_keine_kennung(self):
        werte = {w for _, w in osb.merkmale("Am 03.02.2024 im Jahr 2024 zahlten Sie 1234,56 EUR")}
        self.assertNotIn("03022024", werte)
        self.assertNotIn("2024", werte)
        self.assertFalse(any(w.startswith("1234") for w in werte), werte)

    def test_leerer_text(self):
        self.assertEqual(osb.merkmale(None), set())
        self.assertEqual(osb.merkmale(""), set())


class TestSteckbriefe(unittest.TestCase):
    def _bestand(self, ausgeschlossen=()):
        ablagen = [(STADTWERKE + "\\r1.pdf", BRIEF_STADTWERKE), (STADTWERKE + "\\r2.pdf", BRIEF_STADTWERKE),
                   (VERSICHERUNG + "\\v1.pdf", BRIEF_VERSICHERUNG), (VERSICHERUNG + "\\v2.pdf", BRIEF_VERSICHERUNG),
                   ("0_Unsicher\\x.pdf", BRIEF_STADTWERKE), ("S - T\\lose.pdf", BRIEF_STADTWERKE)]
        return osb.baue(ablagen, ORDNER, ausgeschlossen=ausgeschlossen)

    def test_vorschlag_ueber_wiederkehrende_merkmale(self):
        ordner, n = self._bestand().vorschlag(osb.merkmale("Ihre Kundennummer 4711-0815, neue Abschlagszahlung"))
        self.assertEqual(ordner, STADTWERKE)
        self.assertEqual(n, 1)

    def test_eigene_adresse_unterscheidet_nicht(self):
        # Musterweg 3 steht in beiden Ordnern - nur 50 % in einem, also kein Merkmal
        self.assertEqual(self._bestand().vorschlag({("Adresse", "musterweg 3")}), (None, 0))
        self.assertNotIn("musterweg 3", [w for _, w, _, _ in self._bestand().von_ordner(STADTWERKE)])

    def test_ein_dokument_reicht_nicht(self):
        s = osb.Steckbriefe()
        s.hinzu(STADTWERKE, osb.merkmale(BRIEF_STADTWERKE))
        self.assertEqual(s.vorschlag(osb.merkmale(BRIEF_STADTWERKE)), (None, 0))
        s.hinzu(STADTWERKE, osb.merkmale(BRIEF_STADTWERKE))
        self.assertEqual(s.vorschlag(osb.merkmale(BRIEF_STADTWERKE))[0], STADTWERKE)

    def test_nur_ablageziele_zaehlen(self):
        # 0_Unsicher und ein Dokument direkt in der Buchstabengruppe sind keine Stimme: Werkstraße liegt 2x im Ordner
        merkmale = dict(((w, n) for _, w, n, _ in self._bestand().von_ordner(STADTWERKE)))
        self.assertEqual(merkmale["werkstr. 7"], 2)

    def test_mehrdeutig_gibt_keinen_vorschlag(self):
        s = osb.Steckbriefe()
        for _ in range(2):
            s.hinzu(STADTWERKE, {("Nummer", "111111"), ("Nummer", "222222"), ("Nummer", "333333")})
            s.hinzu(VERSICHERUNG, {("Nummer", "999999")})
        self.assertEqual(s.vorschlag({("Nummer", "111111"), ("Nummer", "999999")}), (None, 0))      # 1 : 1
        self.assertEqual(s.vorschlag({("Nummer", "111111"), ("Nummer", "222222"), ("Nummer", "999999")}),
                         (STADTWERKE, 2))                                                            # 2 : 1
        for _ in range(2):
            s.hinzu(VERSICHERUNG, {("Nummer", "888888")})
        self.assertEqual(s.vorschlag({("Nummer", "111111"), ("Nummer", "222222"), ("Nummer", "333333"),
                                      ("Nummer", "999999"), ("Nummer", "888888")}), (None, 0))       # 3 : 2

    def test_ausgeschlossenes_merkmal_zaehlt_nicht(self):
        s = self._bestand(ausgeschlossen=[(STADTWERKE, "Nummer", "47110815")])
        self.assertEqual(s.vorschlag({("Nummer", "47110815")}), (None, 0))
        angezeigt = [m for m in s.von_ordner(STADTWERKE) if m[1] == "47110815"]
        self.assertEqual(angezeigt[0][3], True)               # das Wiki zeigt es als ausgeschlossen

    def test_ordnernamen_wie_in_der_sammlung(self):
        s = osb.Steckbriefe()
        for _ in range(2):
            s.hinzu("S - T\\Stadtwerke Musterstadt", {("Nummer", "123456")})
        self.assertEqual(s.vorschlag({("Nummer", "123456")})[0], "S - T\\Stadtwerke Musterstadt")
        self.assertEqual(s.ordner(), ["S - T\\Stadtwerke Musterstadt"])


def _e(ziel, sicher=True, probleme=None, **mehr):
    e = {"pdf_path": "x.pdf", "titel": "Rechnung", "datum": "2024-02-03", "zielordner": ziel, "ordner_neu": False,
         "sicher": sicher, "probleme": probleme if probleme is not None else ([] if sicher else ["?"]),
         "neuer_dateiname": "20240203_Rechnung.pdf" if sicher else "", "ordner_per_alias": False}
    e.update(mehr)
    return e


class TestRegelD(unittest.TestCase):
    AEHNLICH = auto_pilot._PROBLEM_AEHNLICHER_ORDNER + " 'x'"

    def test_bestaetigt_sichere_ablage(self):
        e = _e(STADTWERKE)
        self.assertIs(auto_pilot.wende_steckbrief_an(e, STADTWERKE, None, ORDNER, 3), e)

    def test_sperrt_widersprechende_sichere_ablage(self):
        neu = auto_pilot.wende_steckbrief_an(_e(VERSICHERUNG), STADTWERKE, None, ORDNER, 2)
        self.assertFalse(neu["sicher"])
        self.assertEqual(neu["zielordner"], STADTWERKE)        # Steckbrief-Ordner vorgewählt
        self.assertEqual(neu["neuer_dateiname"], "")
        self.assertTrue(neu["probleme"][-1].startswith(auto_pilot._PROBLEM_STECKBRIEF), neu["probleme"])
        self.assertIn(VERSICHERUNG, neu["probleme"][-1])         # was KID wollte, steht dabei

    def test_rueckfrage_mit_zustimmender_vorwahl_wird_sicher(self):
        neu = auto_pilot.wende_steckbrief_an(_e(STADTWERKE, False, [self.AEHNLICH]), STADTWERKE, None, ORDNER, 2)
        self.assertTrue(neu["sicher"], neu["probleme"])
        self.assertEqual(neu["ordner_hinweis"], auto_pilot.STECKBRIEF_HINWEIS)
        self.assertFalse(neu["ordner_per_alias"])

    def test_rueckfrage_mit_zustimmender_zweitmeinung_wird_sicher(self):
        neu = auto_pilot.wende_steckbrief_an(_e("", False, ["kein Zielordner und kein Absender erkannt"]),
                                             STADTWERKE, [(STADTWERKE, 0.6), (VERSICHERUNG, 0.3)], ORDNER, 2)
        self.assertTrue(neu["sicher"], neu["probleme"])
        self.assertEqual(neu["zielordner"], STADTWERKE)

    def test_ohne_zweites_signal_nur_vorwahl(self):
        neu = auto_pilot.wende_steckbrief_an(_e(VERSICHERUNG, False, [self.AEHNLICH]), STADTWERKE,
                                             [(VERSICHERUNG, 0.7)], ORDNER, 2)
        self.assertFalse(neu["sicher"])
        self.assertEqual(neu["zielordner"], STADTWERKE)

    def test_anderer_grund_bleibt_rueckfrage(self):
        # Ein fehlendes Datum macht ein richtiger Ordner nicht besser
        e = _e(STADTWERKE, False, ["kein plausibles Dokumentdatum erkannt"])
        self.assertIs(auto_pilot.wende_steckbrief_an(e, STADTWERKE, None, ORDNER, 2), e)   # unverändert

    def test_alias_sammelordner_und_unbekannter_ordner_bleiben(self):
        for e in (_e(VERSICHERUNG, ordner_per_alias=True), _e(VERSICHERUNG, ordner_sammel=True)):
            self.assertIs(auto_pilot.wende_steckbrief_an(e, STADTWERKE, None, ORDNER, 2), e)
        e = _e(VERSICHERUNG)
        self.assertIs(auto_pilot.wende_steckbrief_an(e, "Gibt es nicht", None, ORDNER, 2), e)
        self.assertIs(auto_pilot.wende_steckbrief_an(e, None, None, ORDNER, 0), e)

    def test_zielordner_klick_raeumt_den_hinweis_weg(self):
        neu = auto_pilot.wende_steckbrief_an(_e(VERSICHERUNG), STADTWERKE, None, ORDNER, 2)
        bestaetigt = auto_pilot.wende_zielordner_an(neu, STADTWERKE, ORDNER)
        self.assertTrue(bestaetigt["sicher"], bestaetigt["probleme"])


class TestAnsicht(unittest.TestCase):
    """Schritt 3: Wiki-Bereich „Ablageordner“ - Belege je Merkmal, Ausschließen in der offenen Anzeige."""

    def setUp(self):
        self.s, self.dokumente = osb.ansicht(
            [(STADTWERKE + "\\r1.pdf", BRIEF_STADTWERKE), (STADTWERKE + "\\r2.pdf", BRIEF_STADTWERKE),
             (STADTWERKE + "\\anders.pdf", "Kundennummer: 1234 5678"), (VERSICHERUNG + "\\v1.pdf", BRIEF_VERSICHERUNG),
             ("0_Unsicher\\x.pdf", BRIEF_STADTWERKE)], ORDNER)

    def test_belege_eines_merkmals(self):
        self.assertEqual(osb.belege(self.dokumente, STADTWERKE, "Nummer", "47110815"),
                         [STADTWERKE + "\\r1.pdf", STADTWERKE + "\\r2.pdf"])
        self.assertEqual(osb.belege(self.dokumente, "0_Unsicher", "Nummer", "47110815"), [])   # kein Ablageziel
        self.assertEqual(self.s.vorschlag({("Nummer", "47110815")}), (STADTWERKE, 1))       # zählt wie baue()

    def test_ausschliessen_und_zulassen(self):
        self.s.schliesse_aus(STADTWERKE.upper(), "Nummer", "47110815")
        self.assertEqual(self.s.vorschlag({("Nummer", "47110815")}), (None, 0))
        self.s.lasse_zu(STADTWERKE, "Nummer", "47110815")
        self.assertEqual(self.s.vorschlag({("Nummer", "47110815")}), (STADTWERKE, 1))

    def test_anzeigezeilen(self):
        from tools import wiki_ablageordner as fenster
        self.s.schliesse_aus(STADTWERKE, "Nummer", "47110815")
        zeilen = fenster.ordner_zeilen(self.s)
        self.assertEqual([z[0] for z in zeilen], [STADTWERKE])      # Versicherung: nur 1 Dokument, keine Merkmale
        gilt, aus = zeilen[0][1:]
        self.assertEqual(aus, 1)
        self.assertEqual(gilt, len(self.s.von_ordner(STADTWERKE)) - 1)
        self.assertEqual(fenster.ordner_zeilen(self.s, "versich"), [])
        merkmal = next(z for z in fenster.merkmal_zeilen(self.s, STADTWERKE) if z[1] == "47110815")
        self.assertEqual(merkmal, ("Nummer", "47110815", 2, "ausgeschlossen", True))


class TestEinbau(unittest.TestCase):
    """Schritt 2: Steckbriefe aus dem Index, Regel D in entscheide_gelesen / entscheide_im_stapel."""

    def _steckbriefe(self):
        index = MagicMock()
        index.ablage_texte.return_value = [(STADTWERKE + "\\r1.pdf", BRIEF_STADTWERKE),
                                           (STADTWERKE + "\\r2.pdf", BRIEF_STADTWERKE)]
        return osb.lade(index, ORDNER)

    def _gelesen(self):
        return {"pdf_path": "neu.pdf", "png": b"png", "schreibschutz": None, "ki_antwort": {},
                "merkmale": osb.merkmale("Kundennummer: 4711 0815")}

    def test_lade_aus_dem_index(self):
        self.assertEqual(self._steckbriefe().vorschlag({("Nummer", "47110815")}), (STADTWERKE, 1))

    def test_lade_fehler_gibt_leere_steckbriefe(self):
        index, logger = MagicMock(), MagicMock()
        index.ablage_texte.side_effect = OSError("Index gesperrt")
        self.assertEqual(osb.lade(index, ORDNER, logger=logger).vorschlag({("Nummer", "47110815")}), (None, 0))
        logger.warning.assert_called_once()
        self.assertEqual(osb.lade(None, ORDNER).ordner(), [])

    def test_lies_dokument_sammelt_die_merkmale_aus_der_textebene(self):
        with patch("auto_pilot.PDFHandler.get_write_protection", return_value=None), \
                patch("auto_pilot.PDFHandler.render_page_png", return_value=None), \
                patch("auto_pilot.PDFHandler.get_fulltext", return_value=BRIEF_STADTWERKE):
            gelesen = auto_pilot.lies_dokument("neu.pdf", [], "http://x", "m")
        self.assertIn(("Nummer", "47110815"), gelesen["merkmale"])

    def test_entscheide_gelesen_sperrt_per_steckbrief(self):
        with patch("auto_pilot.baue_entscheidung", return_value=_e(VERSICHERUNG)):
            ohne = auto_pilot.entscheide_gelesen(self._gelesen(), ORDNER, "http://x")
            mit = auto_pilot.entscheide_gelesen(self._gelesen(), ORDNER, "http://x", steckbriefe=self._steckbriefe())
        self.assertTrue(ohne["sicher"])
        self.assertFalse(mit["sicher"])
        self.assertEqual(mit["zielordner"], STADTWERKE)

    def test_zweitmeinung_ist_das_zweite_signal(self):
        # Die Zweitmeinung allein ist zu schwach (60 %), mit dem Steckbrief zusammen gilt ihr erster Platz
        unsicher = _e("", False, ["kein Zielordner und kein Absender erkannt"])
        with patch("auto_pilot.baue_entscheidung", return_value=unsicher):
            e = auto_pilot.entscheide_gelesen(self._gelesen(), ORDNER, "http://x", entscheidungsmodell="clef",
                                              rangliste=[(STADTWERKE, 0.6), (VERSICHERUNG, 0.3)],
                                              steckbriefe=self._steckbriefe())
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["ordner_hinweis"], auto_pilot.STECKBRIEF_HINWEIS)

    def test_im_stapel_nur_fuer_die_endgueltige_entscheidung(self):
        aufrufe = []

        def entscheide(g, ordner, url, **k):
            aufrufe.append(k.get("steckbriefe"))
            return {"ordner_neu": True, "sicher": True}
        steckbriefe = self._steckbriefe()
        with patch("auto_pilot.entscheide_gelesen", side_effect=entscheide):
            auto_pilot.entscheide_im_stapel(self._gelesen(), ORDNER, "http://x", "clef", rangliste=["alt"],
                                            ordner_stand=1, steckbriefe=steckbriefe)
        self.assertEqual(aufrufe, [None, steckbriefe])   # die Vorab-Prüfung „neuer Ordner?“ ohne Steckbrief


if __name__ == "__main__":
    unittest.main()
