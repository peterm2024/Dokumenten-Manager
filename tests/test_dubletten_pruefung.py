"""
Tests für Stufe B der Dubletten-Erkennung (dubletten_pruefung.py): Bevor die
Vollautomatik ablegt, wird der Zielordner geprüft. PyMuPDF ist gepatcht — die
Testdateien sind echte, aber inhaltlich beliebige Dateien im Temp-Ordner.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import dubletten_pruefung

TEXT_A = ("Rechnung Nr 4711 vom 30 Juni 2008 Gentilia Versicherung Beitrag Jahresbeitrag "
          "Kraftfahrzeug Haftpflicht Zahlung bis 15 Juli fällig Bankverbindung Sparkasse")
TEXT_ANDERS = ("Kündigung Mietvertrag Wohnung Erdgeschoss zum Monatsende Widerspruch "
               "Betriebskosten Abrechnung Heizung Warmwasser Nachzahlung Kaution Übergabe")


class TestDublettenPruefung(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.master = os.path.join(self.tmp, "KID")
        self.ziel = os.path.join(self.master, "Gentilia")
        os.makedirs(self.ziel)
        self.neu = self._datei(os.path.join(self.master, "0_Posteingang"), "scan.pdf", b"neu")
        self.alt = self._datei(self.ziel, "20080630_Rechnung.pdf", b"alt")

        # Standard: beide Dokumente sind derselbe Brief (gleicher Text, gleiches Datum)
        self.daten = {
            self.neu: {"text": TEXT_A, "seiten": 1, "hash": 1234, "datum": "2008-06-30", "tags": ""},
            self.alt: {"text": TEXT_A, "seiten": 1, "hash": 1234, "datum": "2008-06-30", "tags": ""},
        }
        self._patche_pdf()

    def _datei(self, ordner, name, inhalt):
        os.makedirs(ordner, exist_ok=True)
        pfad = os.path.join(ordner, name)
        with open(pfad, "wb") as f:
            f.write(inhalt)
        return pfad

    def _patche_pdf(self):
        """PyMuPDF-Zugriffe durch die Werte aus self.daten ersetzen."""
        self.seitenzahl_aufrufe = []

        def seiten(pfad):
            self.seitenzahl_aufrufe.append(pfad)
            return self.daten[pfad]["seiten"]

        def text(pfad):
            return self.daten[pfad]["text"]

        for name, funktion in (("get_page_count", seiten), ("get_first_page_text", text),
                               ("get_page_fingerprint", lambda p: self.daten[p]["hash"]),
                               ("get_metadata", lambda p: {"KID_DokumentenDatum": self.daten[p]["datum"],
                                                           "keywords": self.daten[p]["tags"]})):
            patcher = patch.object(dubletten_pruefung.PDFHandler, name, staticmethod(funktion))
            patcher.start()
            self.addCleanup(patcher.stop)

    def _entscheidung(self, sicher=True):
        return {"pdf_path": self.neu, "zielordner": "Gentilia", "sicher": sicher, "probleme": []}

    # ------------------------------------------------------------------ finde_dublette
    def test_findet_gleichen_brief_im_zielordner(self):
        treffer = dubletten_pruefung.finde_dublette(self.neu, self.ziel)
        self.assertIsNotNone(treffer)
        pfad, grund = treffer
        self.assertEqual(pfad, self.alt)
        self.assertIn("gleich", grund)

    def test_anderer_inhalt_ist_keine_dublette(self):
        self.daten[self.alt]["text"] = TEXT_ANDERS
        self.daten[self.alt]["hash"] = 0xF0F0F0F0F0F0F0F0
        self.daten[self.alt]["datum"] = "2019-01-02"
        self.assertIsNone(dubletten_pruefung.finde_dublette(self.neu, self.ziel))

    def test_andere_seitenzahl_wird_gar_nicht_erst_gelesen(self):
        """Der Vorfilter spart das teure Einlesen — bewerte_paar würde ohnehin None liefern."""
        self.daten[self.alt]["seiten"] = 3
        with patch.object(dubletten_pruefung, "lese_info", side_effect=dubletten_pruefung.lese_info) as gelesen:
            self.assertIsNone(dubletten_pruefung.finde_dublette(self.neu, self.ziel))
        # nur das neue Dokument selbst wurde eingelesen, nicht der Kandidat
        gelesene = [aufruf.args[0] for aufruf in gelesen.call_args_list]
        self.assertEqual(gelesene, [self.neu])

    def test_leerer_oder_fehlender_zielordner(self):
        self.assertIsNone(dubletten_pruefung.finde_dublette(self.neu, ""))
        self.assertIsNone(dubletten_pruefung.finde_dublette(self.neu, os.path.join(self.master, "GibtsNicht")))

    def test_datei_vergleicht_sich_nicht_mit_sich_selbst(self):
        """Liegt das Dokument schon im Zielordner (Ablage-Vorschau auf abgelegte Dateien), kein Selbsttreffer."""
        self.assertIsNone(dubletten_pruefung.finde_dublette(self.alt, self.ziel))

    def test_deckel_begrenzt_die_vergleiche(self):
        for i in range(5):
            pfad = self._datei(self.ziel, f"kopie{i}.pdf", f"k{i}".encode())
            self.daten[pfad] = {"text": TEXT_ANDERS, "seiten": 1, "hash": 0xF0F0F0F0F0F0F0F0,
                                "datum": "2019-01-02", "tags": ""}
        with patch.object(dubletten_pruefung, "lese_info", side_effect=dubletten_pruefung.lese_info) as gelesen:
            dubletten_pruefung.finde_dublette(self.neu, self.ziel, max_vergleiche=2)
        # 1x das neue Dokument + höchstens 2 Kandidaten
        self.assertLessEqual(len(gelesen.call_args_list), 3)

    # ------------------------------------------------------------------ pruefe_entscheidung
    def test_entscheidung_wird_unsicher_mit_begruendung(self):
        entscheidung = self._entscheidung()
        hinweis = dubletten_pruefung.pruefe_entscheidung(entscheidung, self.master)
        self.assertIsNotNone(hinweis)
        self.assertFalse(entscheidung["sicher"])
        self.assertIn("Dublette", entscheidung["probleme"][0])
        self.assertIn("20080630_Rechnung.pdf", entscheidung["probleme"][0])
        self.assertEqual(entscheidung["dublette_zu"], self.alt)

    def test_ohne_dublette_bleibt_die_entscheidung_sicher(self):
        self.daten[self.alt]["text"] = TEXT_ANDERS
        self.daten[self.alt]["hash"] = 0xF0F0F0F0F0F0F0F0
        self.daten[self.alt]["datum"] = "2019-01-02"
        entscheidung = self._entscheidung()
        self.assertIsNone(dubletten_pruefung.pruefe_entscheidung(entscheidung, self.master))
        self.assertTrue(entscheidung["sicher"])
        self.assertEqual(entscheidung["probleme"], [])

    def test_bereits_unsichere_entscheidung_wird_nicht_geprueft(self):
        entscheidung = self._entscheidung(sicher=False)
        with patch.object(dubletten_pruefung, "finde_dublette") as suche:
            self.assertIsNone(dubletten_pruefung.pruefe_entscheidung(entscheidung, self.master))
        suche.assert_not_called()

    def test_schwacher_treffer_reicht_fuer_unsicher(self):
        """
        Verschiedene Personen-Tags ergeben im Werkzeug nur 'Prüfen:' (kein Papierkorb-
        Vorschlag). Für die Automatik ist schon dieser Verdacht Grund genug anzuhalten.
        """
        self.daten[self.neu]["tags"] = "Uta Mustermann"
        self.daten[self.alt]["tags"] = "Hermann Mustermann"
        merkmale = {"Personen": ["Uta Mustermann", "Hermann Mustermann"]}
        entscheidung = self._entscheidung()
        hinweis = dubletten_pruefung.pruefe_entscheidung(entscheidung, self.master, merkmale)
        self.assertIsNotNone(hinweis)
        self.assertIn("Prüfen", hinweis)
        self.assertFalse(entscheidung["sicher"])

    def test_datum_der_entscheidung_zaehlt_beim_vergleich(self):
        """
        Das Dokumentdatum steht zum Prüfzeitpunkt noch NICHT in der Datei (es schreibt erst
        fuehre_entscheidung_aus). Ohne die Übergabe fiele jeder Vergleich in den unscharfen
        Zweig „Datum unbekannt" (0.85) statt „anderes Datum" (0.92) — Serienbriefe derselben
        Vorlage aus verschiedenen Jahren landeten dann reihenweise in 0_Unsicher.
        """
        import dubletten
        # Text zwischen den beiden Schwellen: unbekanntes Datum → Treffer, anderes Datum → keiner
        woerter = TEXT_A.split()
        aehnlicher_text = " ".join(woerter[:-1] + ["Nachtrag"])   # Ähnlichkeit ~0.89
        self.daten[self.alt]["text"] = aehnlicher_text
        self.daten[self.alt]["datum"] = "2019-01-02"
        self.daten[self.neu]["datum"] = ""          # in der Datei steht noch nichts
        aehnlichkeit = dubletten.text_aehnlichkeit(TEXT_A, aehnlicher_text)
        self.assertTrue(dubletten.TEXT_DATUM_UNBEKANNT <= aehnlichkeit < dubletten.TEXT_ANDERES_DATUM,
                        f"Testdaten passen nicht: {aehnlichkeit:.2f}")

        # ohne Datum: beide Daten unbekannt → schwächere Schwelle greift
        self.assertIsNotNone(dubletten_pruefung.finde_dublette(self.neu, self.ziel))
        # mit dem Datum aus der Entscheidung: verschiedene Daten → strengere Schwelle
        entscheidung = self._entscheidung()
        entscheidung["datum"] = "2008-06-30"
        self.assertIsNone(dubletten_pruefung.pruefe_entscheidung(entscheidung, self.master))
        self.assertTrue(entscheidung["sicher"])

    # ------------------------------------------------------------ KI-Zweitprüfung (06.09.2026)
    def test_ki_zweitpruefung_raeumt_unscharfen_treffer_aus(self):
        """Ein klares 'nein' mit Begründung hebt die Sperre auf - die Entscheidung bleibt sicher."""
        entscheidung = self._entscheidung()
        aufrufe = []

        def ki(neu, alt):
            aufrufe.append((neu, alt))
            return {"gleiches_dokument": "nein", "begruendung": "verschiedene Rechnungsnummern"}

        hinweis = dubletten_pruefung.pruefe_entscheidung(entscheidung, self.master, ki_pruefung=ki)
        self.assertIsNone(hinweis)
        self.assertTrue(entscheidung["sicher"])
        self.assertEqual(entscheidung["probleme"], [])
        self.assertEqual(aufrufe, [(self.neu, self.alt)])
        self.assertIn("ausgeräumt", entscheidung["dubletten_zweitpruefung"])
        self.assertIn("verschiedene Rechnungsnummern", entscheidung["dubletten_zweitpruefung"])
        self.assertIn("20080630_Rechnung.pdf", entscheidung["dubletten_zweitpruefung"])

    def test_ki_ja_oder_unsicher_laesst_verdacht_bestehen(self):
        for antwort in ("ja", "unsicher"):
            entscheidung = self._entscheidung()
            hinweis = dubletten_pruefung.pruefe_entscheidung(
                entscheidung, self.master,
                ki_pruefung=lambda n, a, antwort=antwort: {
                    "gleiches_dokument": antwort, "begruendung": "gleiche Rechnungsnummer"})
            self.assertIsNotNone(hinweis, antwort)
            self.assertFalse(entscheidung["sicher"])
            # Die KI-Begründung wird als Entscheidungshilfe an den Hinweis gehängt
            self.assertIn("KI-Zweitprüfung", hinweis)
            self.assertIn("gleiche Rechnungsnummer", hinweis)

    def test_ki_nein_ohne_begruendung_zaehlt_nicht(self):
        """Ein 'nein' ohne nachvollziehbaren Grund reicht nicht - Grundregel: bei Zweifel anhalten."""
        entscheidung = self._entscheidung()
        hinweis = dubletten_pruefung.pruefe_entscheidung(
            entscheidung, self.master,
            ki_pruefung=lambda n, a: {"gleiches_dokument": "nein", "begruendung": ""})
        self.assertIsNotNone(hinweis)
        self.assertFalse(entscheidung["sicher"])

    def test_identische_datei_wird_nicht_ki_geprueft(self):
        """Hash-Treffer sind mathematisch sicher - die KI wird gar nicht erst gefragt."""
        with open(self.alt, "wb") as f:
            f.write(b"neu")   # gleicher Datei-Inhalt wie self.neu -> identischer Hash
        aufrufe = []
        entscheidung = self._entscheidung()
        hinweis = dubletten_pruefung.pruefe_entscheidung(
            entscheidung, self.master,
            ki_pruefung=lambda n, a: aufrufe.append(1) or {"gleiches_dokument": "nein", "begruendung": "x"})
        self.assertIsNotNone(hinweis)
        self.assertIn("identische Datei", hinweis)
        self.assertFalse(entscheidung["sicher"])
        self.assertEqual(aufrufe, [])

    # -------------------------------------------------- Grauzone (Kaminkehrer-Fund 06.09.2026)
    def _grauzonen_paar(self):
        """
        Beide Dokumente gleich datiert, Text-Ähnlichkeit ZWISCHEN Grauzone (0.5) und
        harter Schwelle (0.7), Bild-Fingerabdruck weit auseinander - wie die real
        doppelt gescannte Kaminkehrer-Rechnung (0.628, Hamming 19).
        """
        import dubletten
        woerter = TEXT_A.split()
        anders = ("Kehrgebühr Feuerstätte Abgasweg Messung Emissionsmessung "
                  "Schornstein Immissionsschutz Betriebssicherheit").split()
        self.daten[self.alt]["text"] = " ".join(woerter[:16] + anders)
        self.daten[self.alt]["hash"] = 0xF0F0F0F0F0F0F0F0   # Bild-Weg scheidet aus (großer Abstand)
        aehnlich = dubletten.text_aehnlichkeit(self.daten[self.neu]["text"], self.daten[self.alt]["text"])
        self.assertTrue(dubletten_pruefung.GRAUZONE_TEXT <= aehnlich < dubletten.TEXT_GLEICHES_DATUM,
                        f"Testdaten passen nicht: {aehnlich:.2f}")

    def test_grauzone_ki_ja_stoppt_die_ablage(self):
        """Doppelt gescannte Rechnung: Deterministik sieht nichts, die KI erkennt dieselben Angaben."""
        self._grauzonen_paar()
        entscheidung = self._entscheidung()
        aufrufe = []

        def ki(neu, alt):
            aufrufe.append((neu, alt))
            return {"gleiches_dokument": "ja", "begruendung": "gleiche Rechnungsnummer und Beträge"}

        hinweis = dubletten_pruefung.pruefe_entscheidung(entscheidung, self.master, ki_pruefung=ki)
        self.assertIsNotNone(hinweis)
        self.assertFalse(entscheidung["sicher"])
        self.assertEqual(entscheidung["dublette_zu"], self.alt)
        self.assertIn("KI-Zweitprüfung bei gleichem Datum", hinweis)
        self.assertIn("gleiche Rechnungsnummer", hinweis)
        self.assertEqual(aufrufe, [(self.neu, self.alt)])

    def test_grauzone_ki_nein_oder_unsicher_folgt_der_deterministik(self):
        """Serien-Abrechnungen gleichen Datums dürfen NICHT hängenbleiben, wenn die KI nicht klar 'ja' sagt."""
        self._grauzonen_paar()
        for antwort in ({"gleiches_dokument": "nein", "begruendung": "andere Wohnung"},
                        {"gleiches_dokument": "unsicher", "begruendung": "nicht lesbar"},
                        {"gleiches_dokument": "ja", "begruendung": ""},   # ja ohne Begründung zählt nicht
                        None):
            entscheidung = self._entscheidung()
            hinweis = dubletten_pruefung.pruefe_entscheidung(
                entscheidung, self.master, ki_pruefung=lambda n, a, antwort=antwort: antwort)
            self.assertIsNone(hinweis, antwort)
            self.assertTrue(entscheidung["sicher"], antwort)

    def test_grauzone_fragt_nicht_bei_geringer_aehnlichkeit_oder_ohne_ki(self):
        self.daten[self.alt]["text"] = TEXT_ANDERS
        self.daten[self.alt]["hash"] = 0xF0F0F0F0F0F0F0F0
        aufrufe = []
        entscheidung = self._entscheidung()
        self.assertIsNone(dubletten_pruefung.pruefe_entscheidung(
            entscheidung, self.master,
            ki_pruefung=lambda n, a: aufrufe.append(1) or {"gleiches_dokument": "ja", "begruendung": "x"}))
        self.assertEqual(aufrufe, [])   # unter der Grauzonen-Schwelle wird die KI nicht bemüht
        self.assertTrue(entscheidung["sicher"])

    def test_fehler_der_ki_zweitpruefung_haelt_die_sperre(self):
        """Server weg / Renderfehler: der Verdacht bleibt bestehen (fail-safe)."""
        def kaputt(n, a):
            raise OSError("Server weg")

        entscheidung = self._entscheidung()
        hinweis = dubletten_pruefung.pruefe_entscheidung(entscheidung, self.master, ki_pruefung=kaputt)
        self.assertIsNotNone(hinweis)
        self.assertFalse(entscheidung["sicher"])

    def test_cache_liest_jede_datei_nur_einmal(self):
        cache = {}
        with patch.object(dubletten_pruefung, "lese_info", side_effect=dubletten_pruefung.lese_info) as gelesen:
            dubletten_pruefung.finde_dublette(self.neu, self.ziel, cache=cache)
            dubletten_pruefung.finde_dublette(self.neu, self.ziel, cache=cache)
        self.assertEqual(len(gelesen.call_args_list), 2)   # neu + alt, beim zweiten Lauf nichts mehr


if __name__ == "__main__":
    unittest.main()
