import unittest
from unittest.mock import patch

import spell_correct


class TestCleanOcrNoise(unittest.TestCase):
    def test_entfernt_isolierte_sonderzeichen(self):
        self.assertEqual(spell_correct.clean_ocr_noise("Text {mit} |Müll| ^und~ \\Backslash"),
                          "Text mit Müll und Backslash")

    def test_loest_null_und_eins_mitten_im_wort_auf(self):
        self.assertEqual(spell_correct.clean_ocr_noise("Vers1cherung fü0r Kunden"), "Verslcherung füOr Kunden")

    def test_laesst_isolierte_zahlen_unangetastet(self):
        self.assertEqual(spell_correct.clean_ocr_noise("Rechnung Nr. 12345 vom 2026"), "Rechnung Nr. 12345 vom 2026")

    def test_zeilenumbrueche_bleiben_erhalten_nur_leerzeichen_werden_zusammengezogen(self):
        self.assertEqual(spell_correct.clean_ocr_noise("Zeile1\n\nZeile2   mit    Luecken"),
                          "Zeile1\n\nZeile2 mit Luecken")


class TestBuildVocabulary(unittest.TestCase):
    def test_zaehlt_woerter_klein_geschrieben(self):
        vocab = spell_correct.build_vocabulary(["Versicherung versicherung VERSICHERUNG"])
        self.assertEqual(vocab["versicherung"], 3)

    def test_ignoriert_leere_und_none_eintraege(self):
        vocab = spell_correct.build_vocabulary(["Rechnung", "", None, "Rechnung"])
        self.assertEqual(vocab["rechnung"], 2)

    def test_mehrere_texte_werden_zusammengezaehlt(self):
        vocab = spell_correct.build_vocabulary(["Kunde Kunde", "Kunde"])
        self.assertEqual(vocab["kunde"], 3)


class TestCorrectWord(unittest.TestCase):
    def test_bereits_bekanntes_wort_bleibt_unveraendert(self):
        vocab = spell_correct.build_vocabulary(["Versicherung"])
        self.assertEqual(spell_correct.correct_word("Versicherung", vocab), "Versicherung")

    def test_korrigiert_zu_haeufigstem_kandidaten_in_editierdistanz_1(self):
        # "Versicherung" mit einem fehlenden Zeichen ("Versicherun") ist genau 1 Löschung entfernt
        vocab = spell_correct.build_vocabulary(["Versicherung " * 5 + "Versicherungen"])
        self.assertEqual(spell_correct.correct_word("Versicherun", vocab), "Versicherung")

    def test_ohne_nahen_kandidaten_bleibt_wort_unveraendert(self):
        vocab = spell_correct.build_vocabulary(["Rechnung"])
        self.assertEqual(spell_correct.correct_word("xqzpflwrmt", vocab), "xqzpflwrmt")

    def test_grossschreibung_am_wortanfang_bleibt_erhalten(self):
        vocab = spell_correct.build_vocabulary(["kunde " * 5])
        self.assertEqual(spell_correct.correct_word("Kunse", vocab), "Kunde")

    def test_vollstaendige_grossschreibung_bleibt_erhalten(self):
        vocab = spell_correct.build_vocabulary(["kunde " * 5])
        self.assertEqual(spell_correct.correct_word("KUNSE", vocab), "KUNDE")


class TestCorrectProperNoun(unittest.TestCase):
    """
    Eigennamen-Korrektur mit Distanz 2 unter strengen Bedingungen - Live-Fund 29.08.2026:
    das Vision-Modell las 'Musterbein' statt 'Musterheim' (zwei Zeichen daneben).
    """

    def setUp(self):
        self.vocab = spell_correct.build_vocabulary(["Musterheim Musterheim Musterheim Musterstadt Musterstadt Rechnung"])

    def test_zwei_zeichen_fehler_wird_ueber_haeufiges_wort_korrigiert(self):
        self.assertEqual(spell_correct.correct_proper_noun("Musterbein", self.vocab), "Musterheim")

    def test_bekanntes_wort_bleibt_unveraendert(self):
        self.assertEqual(spell_correct.correct_proper_noun("Musterstadt", self.vocab), "Musterstadt")

    def test_ohne_kandidaten_bleibt_das_wort_stehen(self):
        self.assertEqual(spell_correct.correct_proper_noun("Beispielfeld", self.vocab), "Beispielfeld")

    def test_zu_kurze_woerter_werden_nie_angefasst(self):
        vocab = spell_correct.build_vocabulary(["Mustermann Mustermann Mustermann"])
        self.assertEqual(spell_correct.correct_proper_noun("Merz", vocab), "Merz")

    def test_seltener_kandidat_reicht_nicht(self):
        """Ein Einzelfund im Wortschatz kann selbst ein OCR-Fehler sein - erst ab MIN_PROPER_NOUN_FREQ zählt er."""
        vocab = spell_correct.build_vocabulary(["Musterheim"])
        self.assertEqual(spell_correct.correct_proper_noun("Musterbein", vocab), "Musterbein")

    def test_distanz_eins_hat_vorrang_vor_distanz_zwei(self):
        vocab = spell_correct.build_vocabulary(["Maier Maier Maier Mayer Mayer Mayer Mayer Mayer"])
        # 'Maiar' liegt in Distanz 1 zu 'Maier', in Distanz 2 zum häufigeren 'Mayer' - Distanz 1 gewinnt
        self.assertEqual(spell_correct.correct_proper_noun("Maiar", vocab), "Maier")

    def test_leerer_wortschatz_aendert_nichts(self):
        self.assertEqual(spell_correct.correct_proper_noun("Musterbein", {}), "Musterbein")


class TestCorrectText(unittest.TestCase):
    def test_kurze_woerter_werden_nie_angefasst(self):
        vocab = spell_correct.build_vocabulary(["der die das"])
        # "de" ist zu kurz (< MIN_CORRECTABLE_LENGTH), bleibt trotz Nähe zu "der" unveraendert
        self.assertEqual(spell_correct.correct_text("de", vocab), "de")

    def test_laengeres_wort_wird_korrigiert(self):
        vocab = spell_correct.build_vocabulary(["Versicherung " * 5])
        result = spell_correct.correct_text("Ich habe eine Versicherun abgeschlossen", vocab)
        self.assertIn("Versicherung", result)

    def test_gleiches_wort_wird_nur_einmal_berechnet(self):
        vocab = spell_correct.build_vocabulary(["Versicherung " * 5])
        with patch("spell_correct.correct_word", wraps=spell_correct.correct_word) as spy:
            spell_correct.correct_text("Versicherun und Versicherun und Versicherun", vocab)
        self.assertEqual(spy.call_count, 1)


class TestSuggestCorrectedText(unittest.TestCase):
    def test_leerer_text_liefert_leeren_string(self):
        self.assertEqual(spell_correct.suggest_corrected_text("", {}), "")
        self.assertEqual(spell_correct.suggest_corrected_text("   ", {}), "")

    def test_kombiniert_cleanup_und_korrektur(self):
        # "Versicherun" braucht nur EINE Korrektur (fehlendes "g" am Ende) - kombiniert mit
        # dem Klammer-Cleanup, der unabhängig von der Wortschatz-Korrektur laufen muss.
        vocab = spell_correct.build_vocabulary(["Versicherung " * 5])
        result = spell_correct.suggest_corrected_text("Versicherun {kaputt}", vocab)
        self.assertIn("Versicherung", result)
        self.assertNotIn("{", result)
        self.assertNotIn("}", result)


if __name__ == "__main__":
    unittest.main()
