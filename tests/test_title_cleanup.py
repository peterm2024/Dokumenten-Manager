import unittest

import fitz

from tools.title_cleanup import (
    longest_consonant_run,
    looks_garbled,
    _span_looks_corrupted,
    repair_mojibake,
    find_subject_line_rect,
    find_subject_candidates,
    find_top_line_rect,
)


class TestLongestConsonantRun(unittest.TestCase):
    def test_normal_word(self):
        self.assertEqual(longest_consonant_run("Versicherung"), 2)  # "rs" bzw. "ch"

    def test_garbled_word(self):
        # "ltgcb" -> 5 Konsonanten am Stück (echter OCR-Müll, FALLSTRICKE #21)
        self.assertGreaterEqual(longest_consonant_run("Rcinheiltgcbot"), 5)

    def test_lautgruppen_zaehlen_als_ein_konsonant(self):
        # sch/ch/ck/pf/tz/st sind EIN Laut: ehrliche Komposita bleiben unter der Schwelle (T5.7, 20.09.2026)
        self.assertEqual(longest_consonant_run("Rechtsschutz"), 4)        # ch-t-s-sch
        self.assertEqual(longest_consonant_run("Abschlagsplan"), 4)       # g-s-p-l
        self.assertEqual(longest_consonant_run("Privathaftpflicht"), 4)   # f-t-pf-l
        self.assertEqual(longest_consonant_run("Versicherungsschein"), 4)  # n-g-s-sch
        self.assertEqual(longest_consonant_run("Herbstmarkt"), 4)         # r-b-st-m

    def test_only_vowels(self):
        self.assertEqual(longest_consonant_run("aeiou"), 0)


class TestLooksGarbled(unittest.TestCase):
    def test_garbled_real_example(self):
        self.assertTrue(looks_garbled("die Bayerische Vcnlehcrt nach dem Rcinheiltgcbot"))

    def test_clean_title(self):
        self.assertFalse(looks_garbled("Beitragsrechnung Privatschutz-Versicherung"))
        for titel in ("Versicherungsschein Privathaftpflicht", "Abschlagsplan 2026", "Rechtsschutzversicherung",
                      "Deutschland Erbschaft Selbstständig", "Kundenservice Computer Account Direct Cloud"):
            self.assertFalse(looks_garbled(titel), titel)

    def test_zerhackter_muell_mit_ziffern(self):
        # Ziffern/Sonderzeichen zerhacken den Müll in kurze Fragmente - Großbuchstaben mittendrin verraten ihn
        self.assertTrue(looks_garbled("6umaq3jSjaA-z;nq3S}eAUd"))
        self.assertFalse(looks_garbled("Rechnung Muster GmbH 2024"))     # EIN Wort mit innerem Großbuchstaben ist ehrlich
        self.assertFalse(looks_garbled("Beitragsrechnung HKV Privatschutz; V-047-683-133-4"))

    def test_c_statt_e_verraet_ocr(self):
        # e→c ist die typische Scanner-Lesefehler; "Vcnlehcrt" hat nur eine 4er-Kette und fiel früher durch
        for wort in ("Vcnlehcrt", "Vcfsichctt", "Rcinheiltgcbot"):
            self.assertTrue(looks_garbled(wort), wort)

    def test_short_words_ignored(self):
        # Kurze Wörter (< GARBLED_MIN_WORD_LEN) sollen keine Fehlalarme auslösen
        self.assertFalse(looks_garbled("und mit tzscpfx"[:12]))

    def test_empty_text(self):
        self.assertFalse(looks_garbled(""))

    def test_user_semicolon_filenames_not_flagged(self):
        """
        Regressionstest: Der Nutzer verwendet ';' als Trennzeichen in AUTOMATISCH
        generierten Dateinamen (Scandatum + Titel) - das ist keine Kodierungs-Korruption
        und darf die Titel-/Dateinamen-Prüfung nicht triggern (siehe FALLSTRICKE #21,
        Nachtrag). Die striktere Rohtext-Prüfung (_span_looks_corrupted) bleibt strenger.
        """
        self.assertFalse(looks_garbled("Beitragsrechnung HKV Privatschutz; V-047-683-133-4"))
        self.assertFalse(looks_garbled("2. Erhebung und Speicherung personenbezogener Daten; A"))


class TestSpanLooksCorrupted(unittest.TestCase):
    def test_flags_implausible_punctuation_in_raw_span(self):
        # Echtes Beispiel aus einer kaputten Scanner-OCR-Ebene (siehe FALLSTRICKE #21) -
        # hier las das OCR die Zeile über Kopf ("6unuqoajs6ej..." = gedrehtes "...rechnung")
        self.assertTrue(_span_looks_corrupted("6umaq3jSjaA-z;nq3S}eAUd 6unuqoajs6ej;;ag"))

    def test_inherits_consonant_run_check(self):
        self.assertTrue(_span_looks_corrupted("Vcfsichctt"))

    def test_clean_text_not_flagged(self):
        self.assertFalse(_span_looks_corrupted("Beitragsrechnung Privatschutz-Versicherung"))


class TestRepairMojibake(unittest.TestCase):
    def test_repairs_double_encoded_guillemet(self):
        # 'Â«' (U+00C2 U+00AB) ist die klassische Mojibake-Form von '«'
        broken = "_JÂ«m"
        fixed = repair_mojibake(broken)
        self.assertEqual(fixed, "_J«m")

    def test_returns_original_on_undecodable_input(self):
        # Enthält ein Zeichen außerhalb von cp1252 -> encode() schlägt fehl -> Original zurück
        text = "Test \U0001F600"
        self.assertEqual(repair_mojibake(text), text)

    def test_empty_text(self):
        self.assertEqual(repair_mojibake(""), "")


class TestSubjectLineHeuristic(unittest.TestCase):
    def _build_page(self, width=600, height=800):
        doc = fitz.open()
        page = doc.new_page(width=width, height=height)
        self.addCleanup(doc.close)
        return doc, page

    def test_finds_largest_font_line_in_band_left_column(self):
        doc, page = self._build_page()
        # Header/Logo-Zone (wird nicht betrachtet, liegt vor dem Band)
        page.insert_text((50, 30), "LOGO", fontsize=20)
        # Normale Zeile im Band, kleine Schrift
        page.insert_text((50, 250), "kleiner nebensaetzlicher Text hier", fontsize=9)
        # Die "Betreffzeile": groessere Schrift, im Band, linke Spalte
        page.insert_text((50, 300), "WICHTIGER BETREFF TEXT HIER", fontsize=16)
        # Rechte Spalte im Band, noch groessere Schrift - soll durch die x0-Grenze ausgeschlossen werden
        page.insert_text((420, 280), "Rechte Spalte Adresse Zeile", fontsize=18)

        rect = find_subject_line_rect(page)
        self.assertIsNotNone(rect)
        # Erwartung: die Betreffzeile bei y ~ 300 (nicht die rechte Spalte bei y ~ 280, nicht der kleine Text bei y ~ 250).
        # Toleranz groesser als bei den anderen Faellen: insert_text() positioniert per Grundlinie
        # (bbox.y0 ist der Oberrand der Glyphen, bei fontsize=16 sichtbarer Versatz), plus die
        # neue Polsterung (_pad_line_avoiding_neighbors) verschiebt y0 zusaetzlich um bis zu 4pt.
        self.assertLess(abs(rect.y0 - 300), 26)
        self.assertLess(rect.x0, 300)  # linke Spalte, nicht die rechte bei x=420

    def test_returns_none_without_band_candidates(self):
        doc, page = self._build_page()
        # Nur Text ganz oben (Header-Zone) und ganz unten (nach dem Band) - kein Kandidat im Mittelband
        page.insert_text((50, 20), "Kopfzeile", fontsize=12)
        page.insert_text((50, 780), "Fusszeile", fontsize=8)

        self.assertIsNone(find_subject_line_rect(page))

    def test_top_line_fallback(self):
        doc, page = self._build_page()
        page.insert_text((50, 20), "Im Logo-Bereich, wird uebersprungen", fontsize=10)
        page.insert_text((50, 100), "Erste richtige Zeile", fontsize=12)
        page.insert_text((50, 150), "Zweite Zeile", fontsize=12)

        rect = find_top_line_rect(page)
        self.assertIsNotNone(rect)
        # +4pt Toleranz fuer die neue Polsterung (_pad_line_avoiding_neighbors)
        self.assertLess(abs(rect.y0 - 100), 20)

    def test_short_stamp_and_real_subject_both_reach_candidate_list(self):
        """
        Regressionstest fuer den echten Fall: ein schmaler Datumsstempel ('21. APR. 2026')
        gewinnt bei reiner Groessen-Sortierung leicht gegen eine kurze, aber echte
        Betreffzeile ('Beitragsrechnung') - ein zu strenger Mindestbreiten-Filter hatte das
        vorher "geloest", aber dabei auch echte kurze Betreffzeilen ausgeschlossen (siehe
        FALLSTRICKE #21). Die aktuelle Strategie: beide landen in der Kandidatenliste,
        der Nutzer waehlt bei Unklarheit selbst - die echte Zeile muss nur IRGENDWO in
        den Top-Kandidaten auftauchen, nicht zwingend an Position 1.
        """
        doc, page = self._build_page()
        page.insert_text((280, 220), "21. APR.", fontsize=14)  # schmaler Stempel, hohe Schriftgroesse
        page.insert_text((50, 320), "Beitragsrechnung Haftpflichtversicherung", fontsize=11)  # echte, kurze Betreffzeile

        candidates = find_subject_candidates(page, limit=3)
        self.assertTrue(any(abs(r.y0 - 320) < 20 for r in candidates),
                         "Die echte Betreffzeile muss unter den Kandidaten sein")

    def test_padding_does_not_bleed_into_next_line(self):
        """
        Regressionstest: bei engem Zeilenabstand darf der Ausschnitt nicht bis in die
        Nachbarzeile hineinreichen (produzierte sonst Kauderwelsch aus deren Anfang).
        """
        doc, page = self._build_page()
        page.insert_text((50, 300), "Beitragsrechnung Privatschutz-Versicherung", fontsize=12)
        # Naechste Zeile nur 6pt unterhalb des Textendes - enger als die Standard-Polsterung (4pt x2)
        page.insert_text((50, 309), "Ihre Versicherungsschein-Nr.: 12345", fontsize=9)

        rect = find_subject_line_rect(page)
        self.assertIsNotNone(rect)
        # Der Ausschnitt darf nicht bis zur Grundlinie der zweiten Zeile (y=309) reichen
        self.assertLess(rect.y1, 309)


if __name__ == "__main__":
    unittest.main()
