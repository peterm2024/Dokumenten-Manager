import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

import fitz

import ablage_gedaechtnis
import auto_pilot
import personen_namen
from pdf_handler import PDFHandler


def _ki_antwort(**overrides):
    """Vollständige, plausible KI-Antwort als Ausgangsbasis - Tests überschreiben gezielt einzelne Felder. KEIN Zielordner mehr (siehe finde_passenden_ordner)."""
    antwort = {
        "title": "Beitragsrechnung Haftpflichtversicherung",
        "tags": ["Versicherung", "Rechnung"],
        "absender": "Gentilia",
        "datum": "2026-06-18",
    }
    antwort.update(overrides)
    return antwort


VORHANDENE_ORDNER = ["A - B - C", "A - B - C\\Gentilia", "Stadtwerke"]


class TestFindePassendenOrdner(unittest.TestCase):
    """
    Tests für das deterministische Ordner-Matching - Ersatz für die frühere
    KI-Ordnerwahl. Live-Fund (13.07.2026, siehe FALLSTRICKE): bei >50 Ordner-
    Kandidaten wählte das Modell fast immer einen Auffangordner, SELBST bei
    korrekt erkanntem Absender ("Gentilia") und passendem, in der Liste
    stehendem Ordner.
    """

    def test_ordnername_ist_teilstring_des_vollen_firmennamens(self):
        self.assertEqual(
            auto_pilot.finde_passenden_ordner("Gentilia Deutschland Versicherung AG", VORHANDENE_ORDNER),
            "A - B - C\\Gentilia")

    def test_absender_ist_teilstring_des_laengeren_ordnernamens(self):
        ordner = ["Stadtwerke Musterstadt"]
        self.assertEqual(auto_pilot.finde_passenden_ordner("Stadtwerke", ordner), "Stadtwerke Musterstadt")

    def test_gross_kleinschreibung_ist_egal(self):
        self.assertEqual(auto_pilot.finde_passenden_ordner("gentilia deutschland", VORHANDENE_ORDNER),
                          "A - B - C\\Gentilia")

    def test_kein_treffer_liefert_none(self):
        self.assertIsNone(auto_pilot.finde_passenden_ordner("Volkswagen Insurance Brokers GmbH", VORHANDENE_ORDNER))

    def test_leerer_absender_liefert_none(self):
        self.assertIsNone(auto_pilot.finde_passenden_ordner("", VORHANDENE_ORDNER))

    def test_zu_kurzer_ordnername_wird_nicht_als_treffer_gewertet(self):
        """Fehlalarm-Schutz: ein sehr kurzer Ordnername würde sonst fast überall als Teilstring 'treffen'."""
        self.assertIsNone(auto_pilot.finde_passenden_ordner("Xy Versicherung AG", ["Xy"]))

    def test_teilstring_mitten_im_ordnernamen_ist_kein_treffer(self):
        """FALLSTRICKE #36: 'Musterstadt' (Kern von 'Musterstadt, Landratsamt') darf nicht den Radiologen treffen."""
        ordner = ["Radiologie und Nuklearmedizin Musterstadt (Dr. X)", "Landratsamt Musterstadt"]
        self.assertEqual(auto_pilot.finde_passenden_ordner("Landratsamt Musterstadt", ordner, "Musterstadt, Landratsamt"),
                          "Landratsamt Musterstadt")
        self.assertIsNone(auto_pilot.finde_passenden_ordner("Finanzamt Musterstadt", ordner, "Musterstadt, Finanzamt"))

    def test_ordnerkern_muss_als_ganzes_wort_im_absender_stehen(self):
        self.assertIsNone(auto_pilot.finde_passenden_ordner("Gentilianum GmbH", VORHANDENE_ORDNER))

    def test_absender_als_wortanfang_des_ordnerkerns(self):
        self.assertEqual(auto_pilot.finde_passenden_ordner("Volksbank", ["Volksbank Musterstadt"]), "Volksbank Musterstadt")
        self.assertIsNone(auto_pilot.finde_passenden_ordner("Volks", ["Volksbank Musterstadt"]))

    def test_bei_mehreren_treffern_gewinnt_der_spezifischere_laengere_ordner(self):
        ordner = ["Volksbank", "Volksbank Musterstadt"]
        self.assertEqual(auto_pilot.finde_passenden_ordner("Volksbank Musterstadt Raiffeisen", ordner),
                          "Volksbank Musterstadt")

    def test_vertauschte_wortreihenfolge_findet_den_ordner(self):
        """Kaltstart-Test 03.09.2026 (Ordner-Wildwuchs): 'Mustermann Hermann' neben 'Hermann Mustermann'."""
        self.assertEqual(auto_pilot.finde_passenden_ordner("Mustermann Hermann", ["Hermann Mustermann"]),
                         "Hermann Mustermann")
        self.assertEqual(
            auto_pilot.finde_passenden_ordner("Nikolaus Wolf Kaminkehrermeister",
                                              ["Wolf Nikolaus (Kaminkehrer)"]),
            "Wolf Nikolaus (Kaminkehrer)")

    def test_rechtsform_zusaetze_erzeugen_keinen_zweiten_ordner(self):
        self.assertEqual(auto_pilot.finde_passenden_ordner("Iqua Deutschland GmbH", ["Iqua SE"]), "Iqua SE")
        self.assertEqual(auto_pilot.finde_passenden_ordner("Bunt Data Service Team",
                                                           ["Bunt Data Service GmbH"]),
                         "Bunt Data Service GmbH")

    def test_wortmenge_nur_in_sicherer_richtung(self):
        """Gegenprobe #36: der Radiologe darf NICHT über die Wort-Menge gefunden werden."""
        self.assertIsNone(auto_pilot.finde_passenden_ordner(
            "Landratsamt Musterstadt", ["Radiologie und Nuklearmedizin Musterstadt (Dr. X)"], "Musterstadt, Landratsamt"))
        # verschiedene Personen mit gemeinsamem Wort bleiben getrennt
        self.assertIsNone(auto_pilot.finde_passenden_ordner(
            "Feuerlöscher Thomas Eis", ["Feuerlöscher Anton Tauber"]))


class TestKernnameUndBuchstabengruppe(unittest.TestCase):
    """Telefonbuch-Ordnernamen (Nutzer-Entscheidung 29.08.2026) und Einsortierung in Buchstabengruppen."""

    STANDARD_STRUKTUR = ["A - B - C - D - E - F", "A - B - C - D - E - F\\Dr. Maier",
                         "G - H - I - J - K - L", "S - T - U - V - W - X - Y - Z", "[0-9]"]

    def test_kernname_telefonbuchform_ist_teil_vor_dem_komma(self):
        self.assertEqual(auto_pilot.kernname("Carius, Dr. Emil (Zahnarzt)"), "Carius")

    def test_kernname_ueberspringt_anreden_und_titel(self):
        self.assertEqual(auto_pilot.kernname("Dr. Maier"), "Maier")
        self.assertEqual(auto_pilot.kernname("Dr. med. Rolf Bergmann"), "Rolf Bergmann")
        self.assertEqual(auto_pilot.kernname("Gentilia Deutschland"), "Gentilia Deutschland")

    def test_sortierbuchstabe_loest_umlaute_auf_und_erkennt_ziffern(self):
        self.assertEqual(auto_pilot.sortierbuchstabe("Carius, Dr. Emil"), "C")
        self.assertEqual(auto_pilot.sortierbuchstabe("Dr. Maier"), "M")
        self.assertEqual(auto_pilot.sortierbuchstabe("Ärztehaus"), "A")
        self.assertEqual(auto_pilot.sortierbuchstabe("1&1 Telecom"), "0-9")
        self.assertEqual(auto_pilot.sortierbuchstabe("(?)"), "")

    def test_buchstabengruppe_wird_nach_kernname_gewaehlt(self):
        self.assertEqual(auto_pilot.finde_buchstabengruppe("Carius, Dr. Emil (Zahnarzt)", self.STANDARD_STRUKTUR),
                         "A - B - C - D - E - F")
        self.assertEqual(auto_pilot.finde_buchstabengruppe("Gentilia", self.STANDARD_STRUKTUR), "G - H - I - J - K - L")
        self.assertEqual(auto_pilot.finde_buchstabengruppe("1&1", self.STANDARD_STRUKTUR), "[0-9]")

    def test_ohne_buchstabengruppen_bleibt_es_flach(self):
        self.assertIsNone(auto_pilot.finde_buchstabengruppe("Gentilia", ["Stadtwerke", "Gentilia Alt"]))

    def test_unterordner_werden_nie_als_buchstabengruppe_gewertet(self):
        # "A - B" als Unterordner irgendwo tief in der Sammlung darf nicht gewinnen
        self.assertIsNone(auto_pilot.finde_buchstabengruppe("Bank", ["Sonstiges\\A - B"]))

    def test_bereinige_ordnername_kuerzt_an_wortgrenze_und_schreibt_gross(self):
        self.assertEqual(auto_pilot.bereinige_ordnername("radiologie und nuklearmedizin"), "Radiologie und nuklearmedizin")
        lang = "Dr. Emil Carius Dr. Maximilian Carius Zahnarztpraxis Musterstadt Beispielfeld"
        gekuerzt = auto_pilot.bereinige_ordnername(lang)
        self.assertLessEqual(len(gekuerzt), auto_pilot.MAX_ORDNER_LAENGE)
        self.assertTrue(lang.startswith(gekuerzt))  # an einer Wortgrenze, kein halbes Wort
        self.assertEqual(auto_pilot.bereinige_ordnername('Ver/sicherung: "AG"'), "Versicherung AG")

    def test_gekuerzter_ordnername_endet_nicht_mit_bindewort(self):
        # Betatest 26.10.2026: die Kürzung ließ "... und" am Ende stehen
        self.assertEqual(auto_pilot.bereinige_ordnername("Haus- und Grundeigentümer Muster und Umgebung e.V."),
                         "Haus- und Grundeigentümer Muster")
        self.assertEqual(auto_pilot.bereinige_ordnername("Verband der Freunde des Musters für Umgebung"),
                         "Verband der Freunde des Musters")
        # ungekürzte Namen bleiben unangetastet
        self.assertEqual(auto_pilot.bereinige_ordnername("Max und Moritz"), "Max und Moritz")

    def test_gekuerzter_ordnername_ohne_offene_klammer(self):
        # Prüflauf 28.10.2026: "Wolf Nikolaus (Bevollmächtigter" im Ordnerbaum
        self.assertEqual(auto_pilot.bereinige_ordnername("Mustermann Max (Bevollmächtigter Bezirksschornsteinfeger)"),
                         "Mustermann Max")
        self.assertEqual(auto_pilot.bereinige_ordnername("Mustermann, Erbengemeinschaft (Musterstraße 1 und 3)"),
                         "Mustermann, Erbengemeinschaft")
        # geschlossene Klammer innerhalb der Länge bleibt
        self.assertEqual(auto_pilot.bereinige_ordnername("Mustermann, Max (Kaminkehrer) Musterstadt-Nord"),
                         "Mustermann, Max (Kaminkehrer)")

    def test_ordnername_passt_zum_absender(self):
        self.assertTrue(auto_pilot.ordnername_passt_zum_absender("Carius, Dr. Emil (Zahnarzt)", "Dr. Emil Carius Dr. Maximilian Carius"))
        self.assertTrue(auto_pilot.ordnername_passt_zum_absender("Gentilia", "Gentilia Deutschland Versicherung AG"))
        self.assertFalse(auto_pilot.ordnername_passt_zum_absender("Mustermann, Hermann", "Amsel BKK"))
        self.assertFalse(auto_pilot.ordnername_passt_zum_absender("Mustermann, Hermann", ""))


class TestBuchstabenbereich(unittest.TestCase):
    """Standard-Struktur aus folder_default.json ('[A-F]', '[G-L]', ...) - Praxistest 30.08.2026."""

    STRUKTUR = ["00_Posteingang", "[0-9]", "[A-F]", "[G-L]", "[M-R]", "[S-Z]", "[A-F]\\Finanzamt"]

    def test_bereichsform_wird_erkannt(self):
        self.assertEqual(auto_pilot.buchstaben_der_gruppe("[A-F]"), set("ABCDEF"))
        self.assertEqual(auto_pilot.buchstaben_der_gruppe("G-L"), set("GHIJKL"))
        self.assertEqual(auto_pilot.buchstaben_der_gruppe("A - B - C"), set("ABC"))
        self.assertEqual(auto_pilot.buchstaben_der_gruppe("Finanzamt"), set())
        self.assertEqual(auto_pilot.buchstaben_der_gruppe("[F-A]"), set())

    def test_neuer_ordner_landet_im_bereich(self):
        self.assertEqual(auto_pilot.finde_buchstabengruppe("Breitwies & Weber", self.STRUKTUR), "[A-F]")
        self.assertEqual(auto_pilot.finde_buchstabengruppe("Tauber, Anton (Feuerlöscher)", self.STRUKTUR), "[S-Z]")
        self.assertEqual(auto_pilot.finde_buchstabengruppe("Landratsamt Musterstadt", self.STRUKTUR), "[G-L]")
        self.assertEqual(auto_pilot.finde_buchstabengruppe("1&1", self.STRUKTUR), "[0-9]")

    def test_entscheidung_nutzt_bereichsordner(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Breitwies & Weber"), self.STRUKTUR)
        self.assertEqual(e["zielordner"], "[A-F]\\Breitwies & Weber")
        self.assertTrue(e["ordner_neu"])


class TestBaueEntscheidung(unittest.TestCase):
    """Tests für die deterministische Ablage-Prüfung (das 'Misstrauen' gegenüber der KI)."""

    def test_perfekte_antwort_mit_passendem_ordner_ist_sicher(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Gentilia Deutschland Versicherung AG"),
                                          VORHANDENE_ORDNER)
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], "A - B - C\\Gentilia")
        self.assertFalse(e["ordner_neu"])
        self.assertEqual(e["neuer_dateiname"], "20260618_Beitragsrechnung Haftpflichtversicherung.pdf")

    def test_ohne_absender_findet_tag_oder_dateiname_den_ordner(self):
        ordner = VORHANDENE_ORDNER + ["A - B - C\\HKV"]
        e = auto_pilot.baue_entscheidung("20220308_HKV.pdf", _ki_antwort(absender="", tags=["Versicherung", "HKV"]), ordner)
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], "A - B - C\\HKV")
        self.assertEqual(e["ordner_hinweis"], "Tag")
        self.assertFalse(e["ordner_neu"])

    def test_ohne_absender_und_ohne_hinweis_bleibt_unsicher(self):
        e = auto_pilot.baue_entscheidung("scan.pdf", _ki_antwort(absender="", tags=["Versicherung"]), VORHANDENE_ORDNER)
        self.assertFalse(e["sicher"])
        self.assertEqual(e["ordner_hinweis"], "")

    def test_hinweise_legen_nie_neue_ordner_an_und_greifen_nur_ohne_absender(self):
        # Absender vorhanden, aber unbekannt → wie bisher neuer Ordner, Tags spielen keine Rolle
        e = auto_pilot.baue_entscheidung("x.pdf", _ki_antwort(absender="Telenetz", tags=["Stadtwerke"]), VORHANDENE_ORDNER)
        self.assertEqual(e["zielordner"], "Telenetz")
        self.assertEqual(e["ordner_hinweis"], "")

    def test_unbekannter_absender_ergibt_neuen_ordner_bleibt_aber_sicher(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Telenetz"), VORHANDENE_ORDNER)
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], "Telenetz")
        self.assertTrue(e["ordner_neu"])

    def test_neuer_ordner_landet_unter_buchstabengruppe(self):
        struktur = ["A - B - C - D - E - F", "G - H - I - J - K - L"]
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(
            absender="Dr. Emil Carius Dr. Maximilian Carius", ordnername="Carius, Dr. Emil (Zahnarzt)"), struktur)
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], os.path.join("A - B - C - D - E - F", "Carius, Dr. Emil (Zahnarzt)"))
        self.assertTrue(e["ordner_neu"])

    def test_empfaenger_als_ordnername_wird_verworfen(self):
        """
        Regressionstest FALLSTRICKE #32 (Live-Fund 29.08.2026): die KI lieferte den
        Adressaten ('Mustermann, Hermann') als Ordnernamen - ohne Sperre entstünde ein
        Sammelordner unter dem Namen des Empfängers.
        """
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Amsel BKK", ordnername="Mustermann, Hermann"),
                                          VORHANDENE_ORDNER)
        self.assertEqual(e["ordnername"], "Amsel BKK")
        self.assertEqual(e["zielordner"], os.path.join("A - B - C", "Amsel BKK"))

    def test_zu_kurzer_absender_macht_unsicher_statt_ordner_anzulegen(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="KM"), VORHANDENE_ORDNER)
        self.assertFalse(e["sicher"])
        self.assertEqual(e["zielordner"], "")
        self.assertTrue(any("zu kurz" in p for p in e["probleme"]), e["probleme"])

    def test_telefonbuch_ordner_wird_ueber_kernname_wiedergefunden(self):
        ordner = ["A - B - C", "A - B - C\\Carius, Dr. Emil (Zahnarzt)"]
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Zahnarztpraxis Dr. Carius"), ordner)
        self.assertEqual(e["zielordner"], "A - B - C\\Carius, Dr. Emil (Zahnarzt)")
        self.assertFalse(e["ordner_neu"])

    def test_fehlender_absender_macht_unsicher(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender=""), VORHANDENE_ORDNER)
        self.assertFalse(e["sicher"])
        self.assertIn("kein Zielordner und kein Absender erkannt", e["probleme"])

    def test_fehlender_absender_liefert_leeren_string_nie_none(self):
        """
        Regressionstest: ohne Absender blieb 'zielordner' bisher None statt "" -
        tools/auto_filer.py stürzte beim Anhängen von '(neu)' mit TypeError ab
        ('NoneType' + 'str'), da der Rückgabewert immer als String erwartet wird.
        """
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender=""), VORHANDENE_ORDNER)
        self.assertEqual(e["zielordner"], "")
        self.assertIsInstance(e["zielordner"], str)

    def test_fehlender_titel_macht_unsicher_fehlende_tags_nicht(self):
        # Etappe 6 (FALLSTRICKE #120): Tags setzt der Mensch, ohne Tags ist ein Dokument nicht unsicher
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(title="", tags=[]), VORHANDENE_ORDNER)
        self.assertFalse(e["sicher"])
        self.assertEqual(e["probleme"], ["kein Titel erkannt"])
        self.assertEqual(e["neuer_dateiname"], "")  # ohne sichere Entscheidung kein Umbenennungs-Vorschlag

    def test_unplausible_daten_machen_unsicher(self):
        morgen = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        for datum in ("", "kein Datum", "40.13.2026", "2026-13-40", "1899-01-01", morgen, "18.06.20261"):
            e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(datum=datum), VORHANDENE_ORDNER)
            self.assertFalse(e["sicher"], f"Datum {datum!r} hätte unsicher sein müssen")
            self.assertIn("kein plausibles Dokumentdatum erkannt", e["probleme"])

    def test_geschuetztes_pdf_macht_unsicher(self):
        for schutz in ("verschlüsselt", "schreibgeschützt"):
            e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(), VORHANDENE_ORDNER, schreibschutz=schutz)
            self.assertFalse(e["sicher"])
            self.assertIn(f"PDF ist {schutz}", e["probleme"])

    def test_signiertes_pdf_bleibt_sicher(self):
        """Signierte PDFs können inkrementell beschrieben und gefahrlos verschoben werden - kein Ausschlussgrund."""
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(), VORHANDENE_ORDNER, schreibschutz="signiert")
        self.assertTrue(e["sicher"], e["probleme"])


class TestFindeOrdnerUeberHinweise(unittest.TestCase):
    """Rückfall ohne Absender: Tags/Dateiname exakt gegen vorhandene Ordner (Live-Fund HKV, 30.08.2026)."""

    ORDNER = ["G - H - I", "G - H - I\\HKV", "G - H - I\\Gentilia", "Stadtwerke", "V\\Versicherungskasse Musterland"]

    def test_tag_trifft_ordner_exakt(self):
        self.assertEqual(auto_pilot.finde_ordner_ueber_hinweise(["2022", "Versicherung", "HKV"], "x.pdf", self.ORDNER),
                         ("G - H - I\\HKV", "Tag"))

    def test_dateiname_trifft_ordner_exakt(self):
        self.assertEqual(auto_pilot.finde_ordner_ueber_hinweise([], "D:\\KID\\00_Posteingang\\20220308_hkv.pdf", self.ORDNER),
                         ("G - H - I\\HKV", "Dateiname"))

    def test_kein_teilstring_treffer(self):
        # "Stadt" ist kein Ordner, "Stadtwerke Musterstadt" auch nicht - Teilstrings zählen bewusst nicht
        self.assertEqual(auto_pilot.finde_ordner_ueber_hinweise(["Stadt", "Stadtwerke Musterstadt"], "x.pdf", self.ORDNER),
                         (None, None))

    def test_mehrere_verschiedene_treffer_sind_kein_ergebnis(self):
        self.assertEqual(auto_pilot.finde_ordner_ueber_hinweise(["HKV", "Gentilia"], "x.pdf", self.ORDNER), (None, None))

    def test_telefonbuch_ordner_ueber_kernnamen(self):
        ordner = ["A - B - C\\Carius, Dr. Emil (Zahnarzt)"]
        self.assertEqual(auto_pilot.finde_ordner_ueber_hinweise(["Carius"], "x.pdf", ordner),
                         ("A - B - C\\Carius, Dr. Emil (Zahnarzt)", "Tag"))

    def test_buchstabengruppe_und_zahlen_werden_nicht_getroffen(self):
        self.assertEqual(auto_pilot.finde_ordner_ueber_hinweise(["2022"], "20220308.pdf", self.ORDNER), (None, None))


class TestNutzerKorrektur(unittest.TestCase):
    """Klick auf Titel/Tags/Datum in der Ablage-Vorschau (wende_korrektur_an) und Datums-Vorbelegung aus dem Dateinamen."""

    def test_tags_korrigieren(self):
        """Nutzerwunsch 01./03.09.2026: Tags direkt in der Vorschau bearbeiten ('Wgh.' -> 'Whg.')."""
        entscheidung = auto_pilot.baue_entscheidung(
            "C:/eingang/scan.pdf", _ki_antwort(tags=["Rechnung", "Wgh. 2"]), VORHANDENE_ORDNER)
        neu = auto_pilot.wende_korrektur_an(
            entscheidung, tags="Rechnung, Whg. 2, Ganzneu",
            known_tags=["Rechnung", "Whg. 2"], kategorien=["Dokumentart"])
        self.assertEqual(neu["tags"], ["Rechnung", "Whg. 2", "Ganzneu"])
        self.assertEqual(neu["neue_tags"], [("Ganzneu", "")])  # nur der hinzugetippte ist katalog-neu
        self.assertTrue(neu["sicher"])
        # Original bleibt unangetastet (Kopie-Semantik wie bei Titel/Datum) - und hat seit Etappe 6 keine KI-Tags
        self.assertEqual(entscheidung["tags"], [])

    def test_tags_leeren_ist_kein_problem(self):
        # Etappe 6 (FALLSTRICKE #120): früher machte ein leeres Tag-Feld die Zeile unsicher
        entscheidung = auto_pilot.baue_entscheidung(
            "C:/eingang/scan.pdf", _ki_antwort(), VORHANDENE_ORDNER)
        neu = auto_pilot.wende_korrektur_an(entscheidung, tags="  ,  ")
        self.assertEqual(neu["tags"], [])
        self.assertTrue(neu["sicher"], neu["probleme"])
        # ein alter Eintrag „keine Tags erkannt“ (Entscheidung von vorher) fällt bei der Korrektur weg
        alt = dict(entscheidung, probleme=["keine Tags erkannt"], sicher=False)
        self.assertTrue(auto_pilot.wende_korrektur_an(alt, tags="Rechnung")["sicher"])

    def test_tags_dubletten_und_leerraum_werden_bereinigt(self):
        entscheidung = auto_pilot.baue_entscheidung(
            "C:/eingang/scan.pdf", _ki_antwort(), VORHANDENE_ORDNER)
        neu = auto_pilot.wende_korrektur_an(entscheidung, tags=" Rechnung ,  rechnung,  Strom  Gas ")
        self.assertEqual(neu["tags"], ["Rechnung", "Strom Gas"])

    def test_datum_aus_dateiname(self):
        self.assertEqual(auto_pilot.datum_aus_dateiname("D:\\KID\\20200927_Sehr geehrter Herr.pdf"), "2020-09-27")
        self.assertEqual(auto_pilot.datum_aus_dateiname("2020-09-27 Brief.pdf"), "2020-09-27")
        self.assertEqual(auto_pilot.datum_aus_dateiname("Brief_20200927.pdf"), "")
        self.assertEqual(auto_pilot.datum_aus_dateiname("20201345_x.pdf"), "")   # kein Kalenderdatum
        self.assertEqual(auto_pilot.datum_aus_dateiname("202009271_x.pdf"), "")  # neunte Ziffer: keine Datumsform
        self.assertEqual(auto_pilot.datum_aus_dateiname(""), "")

    def test_datum_aus_dateiname_deutsche_reihenfolge(self):
        # Betatest 25.10.2026: Scanner-App vergab TTMMJJJJ ('01122024_HKV.pdf')
        self.assertEqual(auto_pilot.datum_aus_dateiname("01122024_HKV.pdf"), "2024-12-01")
        self.assertEqual(auto_pilot.datum_aus_dateiname("31052025_stadtwerke.pdf"), "2025-05-31")
        # Müll-Präfixe aus alter OCR bleiben in beiden Lesarten ungültig
        self.assertEqual(auto_pilot.datum_aus_dateiname("30020128_ewie einfach.pdf"), "")
        self.assertEqual(auto_pilot.datum_aus_dateiname("18531217_Anlage.pdf"), "")
        # JJJJMMTT hat Vorrang und bleibt unverändert
        self.assertEqual(auto_pilot.datum_aus_dateiname("20241201_x.pdf"), "2024-12-01")

    def test_datum_korrektur_macht_zeile_sicher(self):
        e = auto_pilot.baue_entscheidung("20200927_x.pdf", _ki_antwort(datum=""), VORHANDENE_ORDNER)
        self.assertFalse(e["sicher"])
        neu = auto_pilot.wende_korrektur_an(e, datum="2020-09-27")
        self.assertTrue(neu["sicher"], neu["probleme"])
        self.assertEqual(neu["neuer_dateiname"], "20200927_Beitragsrechnung Haftpflichtversicherung.pdf")
        self.assertEqual(e["datum"], "")  # Original unverändert

    def test_unplausibles_datum_bleibt_problem(self):
        e = auto_pilot.baue_entscheidung("x.pdf", _ki_antwort(), VORHANDENE_ORDNER)
        neu = auto_pilot.wende_korrektur_an(e, datum="Sept. 2020")
        self.assertFalse(neu["sicher"])
        self.assertEqual(neu["probleme"].count("kein plausibles Dokumentdatum erkannt"), 1)

    def test_deutsche_datumsform_wird_normalisiert(self):
        """Praxistest 30.08.2026: KI lieferte '20.07.2026' -> Zeile war unsicher, Nutzer-Korrektur lehnte dieselbe Form ab."""
        for eingabe, erwartet in (
            ("20.07.2026", "2026-07-20"), (" 20.7.2026 ", "2026-07-20"), ("20.07.26", "2026-07-20"),
            ("20.07.99", "1999-07-20"), ("2026.07.20", "2026-07-20"), ("20/07/2026", "2026-07-20"),
            ("2026-07-20", "2026-07-20"), ("20.07.2026.", "2026-07-20"), ("Juli 2026", "Juli 2026"), ("", ""),
        ):
            self.assertEqual(auto_pilot.normalisiere_datum(eingabe), erwartet, eingabe)
        e = auto_pilot.baue_entscheidung("x.pdf", _ki_antwort(datum="20.07.2026"), VORHANDENE_ORDNER)
        self.assertEqual(e["datum"], "2026-07-20")
        self.assertNotIn("kein plausibles Dokumentdatum erkannt", e["probleme"])
        self.assertTrue(e["neuer_dateiname"].startswith("20260720_"))
        neu = auto_pilot.wende_korrektur_an(e, datum="27.09.2020")
        self.assertEqual(neu["datum"], "2020-09-27")
        self.assertTrue(neu["sicher"], neu["probleme"])

    def test_tausche_namensform(self):
        """Kommalos tauschen (Nutzerkorrektur 30.08.2026: KI verwechselt Vor-/Nachname, Komma wäre dann falsch)."""
        self.assertEqual(personen_namen.tausche_namensform("Hermann Mustermann"), "Mustermann Hermann")
        self.assertEqual(personen_namen.tausche_namensform("Mustermann Hermann"), "Hermann Mustermann")
        self.assertEqual(personen_namen.tausche_namensform("Dr. Emil Carius"), "Carius Dr. Emil")
        self.assertEqual(personen_namen.tausche_namensform("Carius, Dr. Emil"), "Dr. Emil Carius")
        self.assertEqual(personen_namen.tausche_namensform("Rechnung"), "Rechnung")
        self.assertEqual(personen_namen.tausche_namensform(""), "")

    def test_teile_empfaenger(self):
        """Nutzerfund 30.08.2026: Klumpen-Tag 'Hermann Mustermann Werner Mustermann' -> einzelne Personen-Tags."""
        f = personen_namen.teile_empfaenger
        self.assertEqual(f("Hermann Mustermann und Werner Mustermann"), ["Hermann Mustermann", "Werner Mustermann"])
        self.assertEqual(f("Hermann und Werner Mustermann"), ["Hermann Mustermann", "Werner Mustermann"])  # geteilter Nachname
        self.assertEqual(f("Hermann Mustermann & Uta Huber"), ["Hermann Mustermann", "Uta Huber"])
        self.assertEqual(f("Hermann Mustermann Werner Mustermann"), ["Hermann Mustermann", "Werner Mustermann"])  # verklebt, gleicher Nachname
        self.assertEqual(f("Mustermann, Hermann"), ["Mustermann, Hermann"])  # Telefonbuch-Form bleibt EIN Tag
        self.assertEqual(f("Hermann Mustermann"), ["Hermann Mustermann"])
        self.assertEqual(f(""), [])
        # Katalog-Namen decken den Text ab -> Split auch bei verschiedenen Nachnamen
        self.assertEqual(f("Hermann Mustermann Uta Huber", ["Hermann Mustermann", "Uta Huber", "Peter Mustermann"]),
                         ["Hermann Mustermann", "Uta Huber"])
        # Katalog-Namen decken NICHT alles ab -> kein Raten
        self.assertEqual(f("Hermann Mustermann Uta Unbekannt", ["Hermann Mustermann"]), ["Hermann Mustermann Uta Unbekannt"])

    def test_teile_empfaenger_zustellvermerke(self):
        """Kaltstart-Test 03.09.2026: 'c/o' wurde am '/'-Trenner zerhackt -> Tags 'Erbengemeinschaft Mustermann c' + 'o Hermann Mustermann'."""
        f = personen_namen.teile_empfaenger
        self.assertEqual(f("Erbengemeinschaft Mustermann c/o Hermann Mustermann"),
                         ["Erbengemeinschaft Mustermann", "Hermann Mustermann"])
        self.assertEqual(f("Mustermann Erbengemeinschaft Z.Hd.Hermann Mustermann"),  # verklebt, ohne Leerzeichen
                         ["Mustermann Erbengemeinschaft", "Hermann Mustermann"])
        self.assertEqual(f("Mustermann Grundstücksgemeinschaft z. Hd. Werner Mustermann"),
                         ["Mustermann Grundstücksgemeinschaft", "Werner Mustermann"])
        self.assertEqual(f("Huber GmbH p.Adr. Hermann Mustermann"), ["Huber GmbH", "Hermann Mustermann"])
        # Anreden fallen weg, aber nur als eigenes Wort - nie mitten im Namen
        self.assertEqual(f("Herrn Hermann Mustermann"), ["Hermann Mustermann"])
        self.assertEqual(f("Frauenklinik Musterstadt"), ["Frauenklinik Musterstadt"])
        self.assertEqual(f("Padre Pio"), ["Padre Pio"])      # 'p.Adr.' braucht den Punkt
        self.assertEqual(f("Marco Polo"), ["Marco Polo"])    # 'c/o' braucht den Schrägstrich

    def test_teile_objekte_zustellvermerke(self):
        self.assertEqual(auto_pilot.teile_objekte("Weidenstr. 8 c/o Hausverwaltung"),
                         ["Weidenstr. 8", "Hausverwaltung"])

    def test_mehrere_empfaenger_werden_einzelne_personen_tags(self):
        tags, kategorien = auto_pilot.tags_mit_empfaenger(
            {"tags": ["Rechnung"], "empfaenger": "Hermann Mustermann und Werner Mustermann"})
        self.assertEqual(tags, ["Rechnung", "Hermann Mustermann", "Werner Mustermann"])
        self.assertEqual(kategorien, {"Hermann Mustermann": "Personen", "Werner Mustermann": "Personen"})

    def test_kommas_in_tags_werden_aufgeloest(self):
        """FALLSTRICKE #38: Komma ist das Trennzeichen des Schlagwortfelds - Live-Katalog hatte 'Mustermann, Uta'."""
        tags, kategorien = auto_pilot.tags_mit_empfaenger(
            {"tags": ["Steuern, Finanzen", "Rechnung"], "empfaenger": "Mustermann, Uta"})
        self.assertEqual(tags, ["Steuern", "Finanzen", "Rechnung", "Uta Mustermann"])
        self.assertEqual(kategorien, {"Uta Mustermann": "Personen"})

    def test_korrigiere_tag(self):
        """Nutzerfund 30.08.2026: 'Mustereheim' neben 'Musterheim' - Katalog-Schreibweise bzw. Wortschatz gewinnt."""
        from collections import Counter
        self.assertEqual(auto_pilot.korrigiere_tag("Mustereheim", ["Rechnung", "Musterheim"]), "Musterheim")
        self.assertEqual(auto_pilot.korrigiere_tag("musterheim", ["Musterheim"]), "Musterheim")  # Schreibweise des Katalogs
        self.assertEqual(auto_pilot.korrigiere_tag("Peter Mustermann", ["Petra Mustermann"]), "Peter Mustermann")  # Distanz 2: nie
        self.assertEqual(auto_pilot.korrigiere_tag("Auto", ["Aute"]), "Auto")  # zu kurz für unscharf
        self.assertEqual(auto_pilot.korrigiere_tag("Mustereheim", None, Counter({"musterheim": 5, "musterstadt": 9})), "Musterheim")
        self.assertEqual(auto_pilot.korrigiere_tag("Mustereheim", [], None), "Mustereheim")
        # Personen-Tags bleiben unangetastet (Maier/Meier sind zwei Menschen)
        tags, _ = auto_pilot.tags_mit_empfaenger({"tags": [], "empfaenger": "Hans Meier"}, known_tags=["Hans Maier"])
        self.assertEqual(tags, ["Hans Meier"])

    def test_titel_korrektur(self):
        e = auto_pilot.baue_entscheidung("x.pdf", _ki_antwort(title=""), VORHANDENE_ORDNER)
        self.assertIn("kein Titel erkannt", e["probleme"])
        neu = auto_pilot.wende_korrektur_an(e, titel="  Hausverwaltung  ")
        self.assertTrue(neu["sicher"], neu["probleme"])
        self.assertEqual(neu["titel"], "Hausverwaltung")
        self.assertEqual(neu["neuer_dateiname"], "20260618_Hausverwaltung.pdf")
        leer = auto_pilot.wende_korrektur_an(neu, titel="   ")
        self.assertIn("kein Titel erkannt", leer["probleme"])

    def test_andere_probleme_bleiben(self):
        e = auto_pilot.baue_entscheidung("x.pdf", _ki_antwort(title="", datum=""), VORHANDENE_ORDNER)
        neu = auto_pilot.wende_korrektur_an(e, datum="2026-06-18")
        self.assertEqual(neu["probleme"], ["kein Titel erkannt"])


class TestAllerweltswoerter(unittest.TestCase):
    """FALLSTRICKE #50: Der Ordner 'Musterstadt, VB Musterbk' (Telefonbuch-Kern = Ortsname
    'Musterstadt') zog im Kaltstart-Lauf 3 jeden Absender mit 'Musterstadt' an - 25 Dokumente,
    die meisten falsch, sogar bei korrekt erkanntem Absender 'Finanzamt Musterstadt' (der
    längere Ordnername gewann). Wörter, die in mehreren Ordnernamen der Sammlung
    stehen, sind kein Alleinstellungsmerkmal und matchen nicht mehr."""

    ORDNER = ["A - B - C - D - E\\Musterstadt, VB Musterbk",
              "F - G - H - I - J\\Finanzamt",
              "K - L - M - N - O\\Landratsamt Musterstadt",
              "P - Q - R - S - T\\Radiologie und nuklearmedizin MUSTERSTADT",
              "A - B - C - D - E\\Gentilia"]

    def test_mehrdeutige_woerter(self):
        woerter = auto_pilot._mehrdeutige_woerter(self.ORDNER)
        self.assertIn("musterstadt", woerter)
        self.assertNotIn("gentilia", woerter)
        self.assertNotIn("finanzamt", woerter)

    def test_musterstadt_magnet_ist_entschaerft(self):
        # Vorher: 'Musterstadt, VB Musterbk' schlug als längerer Name sogar den exakten Treffer
        self.assertEqual(auto_pilot.finde_passenden_ordner("Finanzamt Musterstadt", self.ORDNER),
                         "F - G - H - I - J\\Finanzamt")

    def test_absender_mit_ortsnamen_matcht_keinen_orts_ordner(self):
        self.assertIsNone(auto_pilot.finde_passenden_ordner("Stadt Musterstadt", self.ORDNER))
        self.assertIsNone(auto_pilot.finde_passenden_ordner("Expert TechnoMarkt Musterstadt", self.ORDNER))

    def test_ordner_mit_eigenem_wort_matchen_weiter(self):
        self.assertEqual(auto_pilot.finde_passenden_ordner("Landratsamt Musterstadt", self.ORDNER),
                         "K - L - M - N - O\\Landratsamt Musterstadt")
        self.assertEqual(auto_pilot.finde_passenden_ordner("Gentilia Deutschland Versicherung AG", self.ORDNER),
                         "A - B - C - D - E\\Gentilia")

    def test_exakter_voller_ordnername_matcht_weiterhin(self):
        self.assertEqual(auto_pilot.finde_passenden_ordner("Musterstadt, VB Musterbk", self.ORDNER),
                         "A - B - C - D - E\\Musterstadt, VB Musterbk")

    def test_doppel_ordner_erzwingen_unsicher(self):
        # Vivafone/Vivafone Kabel: solange zwei ähnliche Ordner existieren, wird nicht
        # geraten - Zusammenführen (oder Alias) löst die Mehrdeutigkeit auf.
        ordner = ["U - V - W\\Vivafone Deutschland GmbH", "U - V - W\\Vivafone Kabel Deutschland"]
        self.assertIsNone(auto_pilot.finde_passenden_ordner("Vivafone GmbH", ordner))

    def test_hinweis_mit_allerweltswort_zaehlt_nicht(self):
        pfad, quelle = auto_pilot.finde_ordner_ueber_hinweise(
            ["Musterstadt"], "20230309_AW_Wohnung_Musterstadt.pdf", self.ORDNER)
        self.assertIsNone(pfad)
        self.assertIsNone(quelle)


class TestAutoHierarchie(unittest.TestCase):
    """Oberkategorien des Tag-Baums kommen in der Vollautomatik automatisch mit
    (Nutzerwunsch 04.09.2026: die Tag-Suche 'Versicherung' muss auch Dokumente
    finden, die nur die Sparte 'Gebäudebrandversicherung' tragen - wie beim
    manuellen Klick im Tag-Baum)."""

    ELTERN = {"gebäudebrandversicherung": ["Versicherung"],
              "feuer": ["Versicherung", "Gebäudebrandversicherung"]}

    def test_oberkategorie_kommt_vor_dem_untertag(self):
        tags = auto_pilot.ergaenze_oberkategorien(["Rechnung", "Gebäudebrandversicherung"], self.ELTERN)
        self.assertEqual(tags, ["Rechnung", "Versicherung", "Gebäudebrandversicherung"])

    def test_keine_duplikate_auch_bei_gross_klein(self):
        tags = auto_pilot.ergaenze_oberkategorien(["versicherung", "Gebäudebrandversicherung"], self.ELTERN)
        self.assertEqual(tags, ["versicherung", "Gebäudebrandversicherung"])

    def test_mehrstufige_hierarchie(self):
        tags = auto_pilot.ergaenze_oberkategorien(["Feuer"], self.ELTERN)
        self.assertEqual(tags, ["Versicherung", "Gebäudebrandversicherung", "Feuer"])

    def test_ignorierliste_gilt_auch_fuer_oberkategorien(self):
        tags = auto_pilot.ergaenze_oberkategorien(["Feuer"], self.ELTERN, {"versicherung"})
        self.assertEqual(tags, ["Gebäudebrandversicherung", "Feuer"])

    def test_ohne_zuordnung_unveraendert(self):
        self.assertEqual(auto_pilot.ergaenze_oberkategorien(["Rechnung"], None), ["Rechnung"])
        self.assertEqual(auto_pilot.ergaenze_oberkategorien(["Rechnung"], {}), ["Rechnung"])


class TestNeueTags(unittest.TestCase):
    """Automatisch wachsender Tag-Katalog (Nutzer-Entscheidung 30.08.2026)."""

    def test_unbekannte_tags_mit_gueltiger_kategorie(self):
        neue = auto_pilot.bestimme_neue_tags(
            ["Rechnung", "Stromverbrauch", "Energie"], {"Stromverbrauch": "thema", "Energie": "Quatsch"},
            known_tags=["rechnung"], kategorien=["Dokument", "Thema"])
        self.assertEqual(neue, [("Stromverbrauch", "Thema"), ("Energie", "")])

    def test_dubletten_und_leere_werden_ignoriert(self):
        neue = auto_pilot.bestimme_neue_tags(["Gas", "gas", " ", "Gas"], {}, [], [])
        self.assertEqual(neue, [("Gas", "")])

    def test_ohne_katalog_keine_neuen_tags_gemeldet(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(), VORHANDENE_ORDNER)
        self.assertEqual(e["neue_tags"], [])

    def test_struktur_kategorie_zaehlt_als_bekannt(self):
        # FALLSTRICKE #59: 'Gesundheit' ist im Katalog eine graue Kategorie (nicht in
        # known_tags) - darf NICHT als neuer Tag unter 'Neu (KI)' gemeldet werden
        neue = auto_pilot.bestimme_neue_tags(
            ["Gesundheit", "Arztrechnung", "gesundheit"], {"Arztrechnung": "Gesundheit"},
            known_tags=["Rechnung"], kategorien=["Dokument", "Gesundheit"])
        self.assertEqual(neue, [("Arztrechnung", "Gesundheit")])


class TestPersonenSchreibweise(unittest.TestCase):
    """Tag-Wildwuchs 06.09.2026: Personen-Tags schnappen auf die Katalog-Schreibweise."""

    KATALOG = ["Rechnung", "Hermann Mustermann", "Doris Richter", "Hans Maier", "Zippel"]

    def test_exakt_und_namensdreher(self):
        f = personen_namen.finde_personen_schreibweise
        self.assertEqual(f("hermann mustermann", self.KATALOG), "Hermann Mustermann")
        self.assertEqual(f("Mustermann Hermann", self.KATALOG), "Hermann Mustermann")
        self.assertEqual(f("zippel", self.KATALOG), "Zippel")

    def test_tippfehler_im_vornamen_bei_gleichem_nachnamen(self):
        f = personen_namen.finde_personen_schreibweise
        self.assertEqual(f("Hemann Mustermann", self.KATALOG), "Hermann Mustermann")
        self.assertEqual(f("Dorit Richter", self.KATALOG), "Doris Richter")
        self.assertEqual(f("Mustermann Hemann", self.KATALOG), "Hermann Mustermann")  # gedreht UND Tippfehler

    def test_unscharfer_nachname_und_einwortige_namen_bleiben_getrennt(self):
        f = personen_namen.finde_personen_schreibweise
        self.assertIsNone(f("Hans Meier", self.KATALOG))      # Maier/Meier: zwei Menschen
        self.assertIsNone(f("Zippl", self.KATALOG))           # einwortig: nur exakt
        self.assertIsNone(f("Petra Mustermann", self.KATALOG))      # Distanz 2 im Vornamen
        self.assertIsNone(f("Werner Mustermann", self.KATALOG))    # anderer Mensch
        self.assertIsNone(f("", self.KATALOG))
        self.assertIsNone(f("Hermann Mustermann", None))

    def test_empfaenger_nimmt_katalog_schreibweise_auch_aus_struktur_kategorien(self):
        # Peters Personen stehen oft als graue Knoten unter ihrer Adresse - die
        # Vollautomatik darf daneben keine zweite Schreibweise anlegen
        tags, kat = auto_pilot.tags_mit_empfaenger(
            _ki_antwort(empfaenger="Mustermann Hemann"), known_tags=["Rechnung", "Versicherung"],
            kategorien=["Weidenstr. 8", "Hermann Mustermann"])
        self.assertIn("Hermann Mustermann", tags)
        self.assertNotIn("Mustermann Hemann", tags)
        self.assertEqual(kat["Hermann Mustermann"], auto_pilot.KATEGORIE_PERSONEN)
        neue = auto_pilot.bestimme_neue_tags(tags, kat, ["Rechnung", "Versicherung"], ["Weidenstr. 8", "Hermann Mustermann"])
        self.assertEqual(neue, [])


class TestKorrigiereTitel(unittest.TestCase):
    """Titel-Wortschatz-Abgleich (Hebel gegen KI-Lesefehler, 29.08.2026: 'Musterbein' statt 'Musterheim')."""

    def setUp(self):
        import spell_correct
        self.vocab = spell_correct.build_vocabulary(["Musterheim Musterheim Stromverbrauch Stromverbrauch Prüfung Prüfung"])

    def test_lesefehler_im_titel_wird_korrigiert_und_gemeldet(self):
        titel, korrekturen = auto_pilot.korrigiere_titel("Stromverbrauch Prüfung Musterbein", self.vocab)
        self.assertEqual(titel, "Stromverbrauch Prüfung Musterheim")
        self.assertEqual(korrekturen, [("Musterbein", "Musterheim")])

    def test_ohne_wortschatz_bleibt_der_titel_unveraendert(self):
        self.assertEqual(auto_pilot.korrigiere_titel("Stromverbrauch Musterbein", None), ("Stromverbrauch Musterbein", []))

    def test_baue_entscheidung_nutzt_wortschatz_und_dateiname_folgt(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(title="Prüfung Musterbein"), VORHANDENE_ORDNER,
                                          vocabulary=self.vocab)
        self.assertEqual(e["titel"], "Prüfung Musterheim")
        self.assertEqual(e["titel_korrekturen"], [("Musterbein", "Musterheim")])
        self.assertEqual(e["neuer_dateiname"], "20260618_Prüfung Musterheim.pdf")

    def test_baue_titel_wortschatz_nimmt_erste_seiten_des_stapels_auf(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        pfad = os.path.join(tmp, "a.pdf")
        doc = fitz.open()
        doc.new_page().insert_text((50, 100), "Zaehlerstand Musterheim Musterheim")
        doc.save(pfad)
        doc.close()
        vocab = auto_pilot.baue_titel_wortschatz([pfad], basis={"musterstadt": 5})
        self.assertEqual(vocab["musterheim"], 2)
        self.assertEqual(vocab["musterstadt"], 5)


class TestBaueDateiname(unittest.TestCase):
    def test_schema_jjjjmmtt_titel(self):
        self.assertEqual(auto_pilot.baue_dateiname("2026-06-18", "Rechnung Strom"),
                          "20260618_Rechnung Strom.pdf")

    def test_verbotene_zeichen_werden_entfernt(self):
        self.assertEqual(auto_pilot.baue_dateiname("2026-01-02", 'Titel: mit\\bösen/Zeichen?*"<>|'),
                          "20260102_Titel mitbösenZeichen.pdf")

    def test_ueberlanger_titel_wird_gekuerzt(self):
        name = auto_pilot.baue_dateiname("2026-01-02", "Wort " * 50)
        self.assertLessEqual(len(name), len("20260102_") + auto_pilot.MAX_TITEL_LAENGE + len(".pdf"))


class TestWendeFreigabeAn(unittest.TestCase):
    """Manuelle Freigabe unsicherer Zeilen in der Ablage-Vorschau (Nutzerwunsch 06.09.2026)."""

    def _entscheidung_mit_dublettenverdacht(self):
        """Vollständige Entscheidung, die nur wegen eines nicht-korrigierbaren Grundes unsicher ist."""
        e = auto_pilot.baue_entscheidung(
            "C:\\eingang.pdf", _ki_antwort(absender="Gentilia Deutschland Versicherung AG"), VORHANDENE_ORDNER)
        self.assertTrue(e["sicher"])  # Ausgangslage: eigentlich sicher
        e["probleme"] = ["vermutlich Dublette zu '20260421_x.pdf'"]
        e["sicher"] = False
        e["neuer_dateiname"] = ""
        return e

    def test_freigabe_macht_sicher_und_baut_dateinamen(self):
        e = self._entscheidung_mit_dublettenverdacht()
        self.assertEqual(auto_pilot.korrigierbare_probleme(e), [])
        neu = auto_pilot.wende_freigabe_an(e)
        self.assertTrue(neu["sicher"])
        self.assertTrue(neu["manuell_freigegeben"])
        self.assertTrue(neu["neuer_dateiname"].endswith(".pdf"))
        # Die Gründe bleiben stehen - Anzeige und Protokoll sollen sie weiter nennen
        self.assertEqual(neu["probleme"], ["vermutlich Dublette zu '20260421_x.pdf'"])
        self.assertFalse(e.get("manuell_freigegeben"))  # Original unverändert (Kopie)

    def test_freigabe_ueberstimmt_keine_korrigierbaren_probleme(self):
        e = self._entscheidung_mit_dublettenverdacht()
        e["probleme"].append("kein plausibles Dokumentdatum erkannt")
        self.assertEqual(auto_pilot.korrigierbare_probleme(e), ["kein plausibles Dokumentdatum erkannt"])
        neu = auto_pilot.wende_freigabe_an(e)
        self.assertFalse(neu["sicher"])  # erst das Datum per Zelle korrigieren
        self.assertEqual(neu["neuer_dateiname"], "")

    def test_freigabe_laesst_sich_zuruecknehmen(self):
        e = auto_pilot.wende_freigabe_an(self._entscheidung_mit_dublettenverdacht())
        zurueck = auto_pilot.wende_freigabe_an(e, freigeben=False)
        self.assertFalse(zurueck["sicher"])
        self.assertFalse(zurueck["manuell_freigegeben"])
        self.assertEqual(zurueck["neuer_dateiname"], "")

    def test_korrektur_hebt_freigabe_auf(self):
        """Nach Titel- oder Zielordner-Korrektur muss die Freigabe neu erteilt werden."""
        e = auto_pilot.wende_freigabe_an(self._entscheidung_mit_dublettenverdacht())
        nach_titel = auto_pilot.wende_korrektur_an(e, titel="Neuer Titel")
        self.assertNotIn("manuell_freigegeben", nach_titel)
        self.assertFalse(nach_titel["sicher"])  # Dubletten-Verdacht zählt wieder
        nach_ordner = auto_pilot.wende_zielordner_an(e, "Stadtwerke", VORHANDENE_ORDNER)
        self.assertNotIn("manuell_freigegeben", nach_ordner)
        self.assertFalse(nach_ordner["sicher"])

    def test_freigabe_ohne_probleme_bleibt_sicher(self):
        e = auto_pilot.baue_entscheidung(
            "C:\\eingang.pdf", _ki_antwort(absender="Gentilia Deutschland Versicherung AG"), VORHANDENE_ORDNER)
        neu = auto_pilot.wende_freigabe_an(e, freigeben=False)
        self.assertTrue(neu["sicher"])  # keine Probleme -> Rücknahme ändert nichts


class TestWendeZurueckstellungAn(unittest.TestCase):
    """Grüne Zeile von Hand wieder gelb (Peter 02.11.2026)."""

    def _sicher(self):
        e = auto_pilot.baue_entscheidung(
            "C:\\eingang.pdf", _ki_antwort(absender="Gentilia Deutschland Versicherung AG"), VORHANDENE_ORDNER)
        self.assertTrue(e["sicher"])
        return e

    def test_zurueckstellen_macht_unsicher_mit_grund(self):
        neu = auto_pilot.wende_zurueckstellung_an(self._sicher())
        self.assertFalse(neu["sicher"])
        self.assertEqual(neu["probleme"], [auto_pilot.PROBLEM_ZURUECKGESTELLT])
        self.assertEqual(neu["neuer_dateiname"], "")
        self.assertEqual(auto_pilot.korrigierbare_probleme(neu), [])

    def test_bleibt_gelb_nach_korrekturen(self):
        neu = auto_pilot.wende_zurueckstellung_an(self._sicher())
        self.assertFalse(auto_pilot.wende_korrektur_an(neu, titel="Anderer Titel")["sicher"])
        self.assertFalse(auto_pilot.wende_zielordner_an(neu, "Stadtwerke", VORHANDENE_ORDNER)["sicher"])

    def test_laesst_sich_zuruecknehmen(self):
        zurueck = auto_pilot.wende_zurueckstellung_an(auto_pilot.wende_zurueckstellung_an(self._sicher()), False)
        self.assertTrue(zurueck["sicher"])
        self.assertEqual(zurueck["probleme"], [])
        self.assertTrue(zurueck["neuer_dateiname"].endswith(".pdf"))


class TestFuehreEntscheidungAus(unittest.TestCase):
    """Tests für Schritt 2 (Ausführung) - baue_entscheidung ist bereits als 'sicher'/'unsicher' geprüft."""

    def setUp(self):
        self.master = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.master, ignore_errors=True)
        self.pdf_path = os.path.join(self.master, "eingang.pdf")
        self._erzeuge_pdf(self.pdf_path)
        # Die "vorhandenen" Ordner liegen wie im echten Betrieb auch auf der Platte -
        # fuehre_entscheidung_aus prüft seit 06.09.2026, ob ein bei der Analyse
        # gefundener Zielordner noch existiert (Umbenennen-Randfall).
        for ordner in VORHANDENE_ORDNER:
            os.makedirs(os.path.join(self.master, ordner), exist_ok=True)

    def _erzeuge_pdf(self, path):
        doc = fitz.open()
        doc.new_page()
        doc.save(path)
        doc.close()

    def _verschieben(self, quelle, ziel):
        """Test-Double für file_operations._verschiebe_ohne_duplikat - legt den Zielordner selbst an, wie shutil.move es nicht täte."""
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        shutil.move(quelle, ziel)

    def test_sichere_entscheidung_schreibt_metadaten_benennt_um_und_verschiebt(self):
        entscheidung = auto_pilot.baue_entscheidung(
            self.pdf_path, _ki_antwort(absender="Gentilia Deutschland Versicherung AG"), VORHANDENE_ORDNER)
        ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, self._verschieben)

        self.assertTrue(ergebnis["erfolg"], ergebnis["fehler"])
        erwartet = os.path.join(self.master, "A - B - C", "Gentilia",
                                 "20260618_Beitragsrechnung Haftpflichtversicherung.pdf")
        self.assertEqual(ergebnis["neuer_pfad"], erwartet)
        self.assertTrue(os.path.exists(erwartet))
        self.assertFalse(os.path.exists(self.pdf_path))
        meta = PDFHandler.get_metadata(erwartet)
        self.assertEqual(meta["title"], "Beitragsrechnung Haftpflichtversicherung")
        self.assertEqual(meta["KID_DokumentenDatum"], "2026-06-18")

    def test_unsichere_entscheidung_verschiebt_unveraendert_nach_unsicher_ordner(self):
        entscheidung = auto_pilot.baue_entscheidung(self.pdf_path, _ki_antwort(absender=""), VORHANDENE_ORDNER)
        ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, self._verschieben)

        self.assertTrue(ergebnis["erfolg"], ergebnis["fehler"])
        erwartet = os.path.join(self.master, auto_pilot.UNSICHER_ORDNER, "eingang.pdf")
        self.assertEqual(ergebnis["neuer_pfad"], erwartet)
        self.assertTrue(os.path.exists(erwartet))
        meta = PDFHandler.get_metadata(erwartet)
        # Peter 04.11.2026: der KI-Titel kommt mit (man sieht, worum es geht), Tags und Datum warten auf die Prüfung
        self.assertEqual((meta["title"], meta["keywords"], meta["KID_DokumentenDatum"]), (entscheidung["titel"], "", ""))

    def test_ki_tags_kommen_nicht_ins_pdf_vorhandene_bleiben(self):
        """Etappe 6 (Peter 07.11.2026 beim Betatest: „fast alle von der KI generierten Tags nicht brauchbar“, FALLSTRICKE
        #120): Die KI vergibt keine Tags mehr, und ohne Eintrag eines Menschen überschreibt die Ablage keine Tags im PDF."""
        PDFHandler.write_custom_metadata(self.pdf_path, {"keywords": "Von Hand"}, still=True)
        entscheidung = auto_pilot.baue_entscheidung(
            self.pdf_path, _ki_antwort(absender="Gentilia Deutschland Versicherung AG", tags=["Rechnung", "Unsinn"]),
            VORHANDENE_ORDNER, known_tags=["Rechnung"])
        self.assertEqual((entscheidung["tags"], entscheidung["neue_tags"]), ([], []))
        self.assertTrue(entscheidung["sicher"], entscheidung["probleme"])
        ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, self._verschieben)
        self.assertEqual(PDFHandler.get_metadata(ergebnis["neuer_pfad"])["keywords"], "Von Hand")

    def test_tags_aus_der_ablage_vorschau_werden_geschrieben(self):
        entscheidung = auto_pilot.wende_korrektur_an(auto_pilot.baue_entscheidung(
            self.pdf_path, _ki_antwort(absender="Gentilia Deutschland Versicherung AG"), VORHANDENE_ORDNER),
            tags="Haftpflicht, Versicherung")
        ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, self._verschieben)
        self.assertEqual(PDFHandler.get_metadata(ergebnis["neuer_pfad"])["keywords"], "Haftpflicht, Versicherung")

    def test_unsicher_merkt_den_grund_im_pdf_sicher_loescht_ihn(self):
        """Status-Zeile der Eigenschaften (Peter 28.10.2026): warum vorgelegt - Grund und KI-Titel, keine Tags/Datum."""
        entscheidung = auto_pilot.baue_entscheidung(self.pdf_path, _ki_antwort(absender=""), VORHANDENE_ORDNER)
        ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, self._verschieben)
        meta = PDFHandler.get_metadata(ergebnis["neuer_pfad"])
        self.assertEqual(meta["KID_Grund"], "; ".join(entscheidung["probleme"]))
        self.assertEqual((meta["keywords"], meta["KID_DokumentenDatum"]), ("", ""))

        sicher = auto_pilot.baue_entscheidung(ergebnis["neuer_pfad"], _ki_antwort(absender="Gentilia Deutschland Versicherung AG"),
                                              VORHANDENE_ORDNER)
        ergebnis = auto_pilot.fuehre_entscheidung_aus(sicher, self.master, self._verschieben)
        self.assertEqual(PDFHandler.get_metadata(ergebnis["neuer_pfad"])["KID_Grund"], "")

    def test_unsicher_verschiebt_auch_wenn_der_grund_nicht_schreibbar_ist(self):
        entscheidung = auto_pilot.baue_entscheidung(self.pdf_path, _ki_antwort(absender=""), VORHANDENE_ORDNER)
        with patch("auto_pilot.PDFHandler.write_custom_metadata", return_value=False):
            ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, self._verschieben)
        self.assertTrue(ergebnis["erfolg"], ergebnis["fehler"])
        self.assertTrue(os.path.exists(ergebnis["neuer_pfad"]))

    def test_verschwundener_zielordner_stuft_auf_unsicher_zurueck(self):
        """Randfall 05.09.2026: Ordner wird ZWISCHEN Analyse und 'Jetzt einsortieren' umbenannt -
        makedirs würde sonst den alten Namen still wieder anlegen."""
        entscheidung = auto_pilot.baue_entscheidung(
            self.pdf_path, _ki_antwort(absender="Gentilia Deutschland Versicherung AG"), VORHANDENE_ORDNER)
        self.assertTrue(entscheidung["sicher"])
        self.assertFalse(entscheidung["ordner_neu"])
        shutil.rmtree(os.path.join(self.master, "A - B - C", "Gentilia"))  # Nutzer hat umbenannt/gelöscht

        ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, self._verschieben)

        self.assertTrue(ergebnis["erfolg"], ergebnis["fehler"])
        # Dokument landet in 0_Unsicher (ohne Tags/Datum), der alte Ordnername entsteht NICHT neu
        self.assertEqual(ergebnis["neuer_pfad"],
                         os.path.join(self.master, auto_pilot.UNSICHER_ORDNER, "eingang.pdf"))
        self.assertFalse(os.path.isdir(os.path.join(self.master, "A - B - C", "Gentilia")))
        meta = PDFHandler.get_metadata(ergebnis["neuer_pfad"])
        self.assertEqual(meta["keywords"], "")  # bei der Rückstufung wie jedes Unsichere: keine Tags
        # Die Rückstufung steht im Entscheidungs-Dict, damit Protokoll und Anzeige sie sehen
        self.assertFalse(entscheidung["sicher"])
        self.assertTrue(any("existiert nicht mehr" in p for p in entscheidung["probleme"]),
                        entscheidung["probleme"])

    def test_bewusst_neuer_zielordner_wird_weiterhin_angelegt(self):
        """ordner_neu=True heißt: Anlegen ist gewollt - die Existenz-Prüfung greift hier nicht."""
        entscheidung = auto_pilot.baue_entscheidung(self.pdf_path, _ki_antwort(absender="Telenetz"), VORHANDENE_ORDNER)
        self.assertTrue(entscheidung["ordner_neu"])
        ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, self._verschieben)
        self.assertTrue(ergebnis["erfolg"], ergebnis["fehler"])
        self.assertTrue(entscheidung["sicher"])
        self.assertTrue(os.path.isdir(os.path.join(self.master, "Telenetz")))

    def test_datei_am_eigenen_platz_wird_nicht_umbenannt(self):
        """
        Nutzerfund 06.09.2026: Ablage-Vorschau über den Unsicher-Ordner - eine weiter
        unsichere Datei liegt schon in 0_Unsicher und wurde trotzdem 'verschoben':
        _naechster_freier_pfad sah die Datei SELBST als Konflikt und machte 'X_1.pdf'
        daraus (jede Runde ein weiteres '_1'). Quelle == Ziel muss ein No-Op sein.
        """
        unsicher = os.path.join(self.master, auto_pilot.UNSICHER_ORDNER)
        pfad = os.path.join(unsicher, "eingang.pdf")
        os.makedirs(unsicher)
        shutil.move(self.pdf_path, pfad)
        entscheidung = auto_pilot.baue_entscheidung(pfad, _ki_antwort(absender=""), VORHANDENE_ORDNER)
        self.assertFalse(entscheidung["sicher"])

        verschoben = []
        ergebnis = auto_pilot.fuehre_entscheidung_aus(
            entscheidung, self.master, lambda q, z: verschoben.append((q, z)))
        self.assertTrue(ergebnis["erfolg"], ergebnis["fehler"])
        self.assertEqual(ergebnis["neuer_pfad"], pfad)
        self.assertEqual(verschoben, [])           # nichts verschoben ...
        self.assertTrue(os.path.exists(pfad))      # ... Datei unverändert am Platz, kein '_1'

    def test_richtig_benannte_datei_im_zielordner_bekommt_nur_metadaten(self):
        """Gleicher Schutz im Grün-Fall: schon korrekt abgelegte Datei wird nicht in 'X_1' umbenannt."""
        ziel_ordner = os.path.join(self.master, "A - B - C", "Gentilia")
        pfad = os.path.join(ziel_ordner, "20260618_Beitragsrechnung Haftpflichtversicherung.pdf")
        shutil.move(self.pdf_path, pfad)
        entscheidung = auto_pilot.baue_entscheidung(
            pfad, _ki_antwort(absender="Gentilia Deutschland Versicherung AG"), VORHANDENE_ORDNER)
        self.assertTrue(entscheidung["sicher"])
        self.assertEqual(entscheidung["neuer_dateiname"], os.path.basename(pfad))

        verschoben = []
        ergebnis = auto_pilot.fuehre_entscheidung_aus(
            entscheidung, self.master, lambda q, z: verschoben.append((q, z)))
        self.assertTrue(ergebnis["erfolg"], ergebnis["fehler"])
        self.assertEqual(ergebnis["neuer_pfad"], pfad)
        self.assertEqual(verschoben, [])
        meta = PDFHandler.get_metadata(pfad)       # Metadaten wurden trotzdem geschrieben
        self.assertEqual(meta["title"], "Beitragsrechnung Haftpflichtversicherung")

    def test_namenskonflikt_im_zielordner_wird_aufgeloest(self):
        ziel_ordner = os.path.join(self.master, "Telenetz")
        os.makedirs(ziel_ordner)
        self._erzeuge_pdf(os.path.join(ziel_ordner, "20260618_Beitragsrechnung Haftpflichtversicherung.pdf"))

        entscheidung = auto_pilot.baue_entscheidung(self.pdf_path, _ki_antwort(absender="Telenetz"), VORHANDENE_ORDNER)
        ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, self._verschieben)

        self.assertTrue(ergebnis["erfolg"], ergebnis["fehler"])
        self.assertNotEqual(os.path.basename(ergebnis["neuer_pfad"]), "20260618_Beitragsrechnung Haftpflichtversicherung.pdf")
        self.assertTrue(os.path.exists(ergebnis["neuer_pfad"]))

    def test_fehler_beim_verschieben_wird_als_erfolglos_gemeldet(self):
        entscheidung = auto_pilot.baue_entscheidung(self.pdf_path, _ki_antwort(absender="Telenetz"), VORHANDENE_ORDNER)

        def kaputtes_verschieben(quelle, ziel):
            raise OSError("Datei ist gesperrt")

        ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, kaputtes_verschieben)
        self.assertFalse(ergebnis["erfolg"])
        self.assertIn("gesperrt", ergebnis["fehler"])
        self.assertIsNone(ergebnis["neuer_pfad"])

    def _lies_protokoll(self):
        import app_paths
        with open(app_paths.protokoll_path(self.master), encoding="utf-8") as f:
            return f.read()

    def test_protokolliere_ergebnis_schreibt_alle_drei_formen(self):
        """Kaltstart-Test 03.09.2026: die Vorschau-Ablage protokollierte nicht - Unsicher-Gründe waren weg."""
        # sicher -> "abgelegt"
        entscheidung = auto_pilot.baue_entscheidung(
            self.pdf_path, _ki_antwort(absender="Gentilia Deutschland Versicherung AG"), VORHANDENE_ORDNER)
        ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, self._verschieben)
        auto_pilot.protokolliere_ergebnis(entscheidung, ergebnis, self.master)
        self.assertIn("abgelegt  eingang.pdf  ->", self._lies_protokoll())

        # unsicher -> Grund steht dabei
        self._erzeuge_pdf(self.pdf_path)
        entscheidung = auto_pilot.baue_entscheidung(self.pdf_path, _ki_antwort(absender=""), VORHANDENE_ORDNER)
        ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, self._verschieben)
        auto_pilot.protokolliere_ergebnis(entscheidung, ergebnis, self.master)
        protokoll = self._lies_protokoll()
        self.assertIn("unsicher  eingang.pdf  ->", protokoll)
        self.assertIn("(Grund: ", protokoll)

        # Fehler -> "FEHLER" mit Meldung
        auto_pilot.protokolliere_ergebnis(
            entscheidung, {"erfolg": False, "neuer_pfad": None, "fehler": "Datei ist gesperrt"}, self.master)
        self.assertIn("FEHLER    eingang.pdf  -  Datei ist gesperrt", self._lies_protokoll())

    def test_protokoll_vermerkt_manuelle_freigabe(self):
        """Das Angehörigen-Protokoll soll zeigen, worüber der Nutzer bewusst hinweggegangen ist."""
        entscheidung = auto_pilot.baue_entscheidung(
            self.pdf_path, _ki_antwort(absender="Gentilia Deutschland Versicherung AG"), VORHANDENE_ORDNER)
        entscheidung["probleme"] = ["vermutlich Dublette zu 'x.pdf'"]
        entscheidung["sicher"] = False
        entscheidung = auto_pilot.wende_freigabe_an(entscheidung)

        ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, self._verschieben)
        self.assertTrue(ergebnis["erfolg"], ergebnis["fehler"])
        auto_pilot.protokolliere_ergebnis(entscheidung, ergebnis, self.master)
        protokoll = self._lies_protokoll()
        self.assertIn("abgelegt  eingang.pdf  ->", protokoll)
        self.assertIn("(manuell freigegeben trotz: vermutlich Dublette zu 'x.pdf')", protokoll)


class TestOrdnerlisteUndPosteingang(unittest.TestCase):
    def setUp(self):
        self.master = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.master, ignore_errors=True)
        for pfad in ("0_Posteingang", "0_Unsicher", ".versteckt",
                      os.path.join("A - B - C", "Gentilia"), "Stadtwerke"):
            os.makedirs(os.path.join(self.master, pfad))

    def test_sammle_ordnerliste_schliesst_systemordner_aus(self):
        ordner = auto_pilot.sammle_ordnerliste(self.master)
        self.assertEqual(ordner, ["A - B - C", os.path.join("A - B - C", "Gentilia"), "Stadtwerke"])

    def test_zwei_posteingaenge_werden_beide_verarbeitet(self):
        """FALLSTRICKE #40 (Praxistest 31.08.2026): '00_Posteingang' UND '0_Posteingang' - der Scanner
        schrieb in den einen, verarbeitet wurde nur der andere; jetzt werden ALLE geleert."""
        os.makedirs(os.path.join(self.master, "00_Posteingang"))
        open(os.path.join(self.master, "00_Posteingang", "b.pdf"), "w").close()
        open(os.path.join(self.master, "0_Posteingang", "a.pdf"), "w").close()
        alle = auto_pilot.finde_posteingaenge(self.master)
        self.assertEqual([os.path.basename(pfad) for pfad in alle], ["0_Posteingang", "00_Posteingang"])
        self.assertEqual(os.path.basename(auto_pilot.finde_posteingang(self.master)), "0_Posteingang")
        dokumente = auto_pilot.sammle_posteingang_dokumente(self.master)
        self.assertEqual(sorted(os.path.basename(pfad) for pfad in dokumente), ["a.pdf", "b.pdf"])

    def test_finde_posteingang_erkennt_varianten(self):
        self.assertEqual(os.path.basename(auto_pilot.finde_posteingang(self.master)), "0_Posteingang")
        os.rename(os.path.join(self.master, "0_Posteingang"), os.path.join(self.master, "00_Posteingang"))
        self.assertEqual(os.path.basename(auto_pilot.finde_posteingang(self.master)), "00_Posteingang")

    def test_finde_posteingang_ohne_treffer(self):
        shutil.rmtree(os.path.join(self.master, "0_Posteingang"))
        self.assertIsNone(auto_pilot.finde_posteingang(self.master))

    def _lege_datei_an(self, *teile):
        pfad = os.path.join(self.master, *teile)
        with open(pfad, "wb") as f:
            f.write(b"x")
        return pfad

    def test_sammle_posteingang_dokumente_liefert_nur_pdfs_sortiert(self):
        self._lege_datei_an("0_Posteingang", "b_zweite.pdf")
        self._lege_datei_an("0_Posteingang", "a_erste.pdf")
        self._lege_datei_an("0_Posteingang", "notiz.txt")       # kein PDF
        self._lege_datei_an("0_Posteingang", ".versteckt.pdf")  # Systemdatei

        dokumente = auto_pilot.sammle_posteingang_dokumente(self.master)

        self.assertEqual([os.path.basename(d) for d in dokumente], ["a_erste.pdf", "b_zweite.pdf"])
        self.assertTrue(all(os.path.isabs(d) for d in dokumente))

    def test_sammle_posteingang_dokumente_ignoriert_unterordner(self):
        """Bewusst nicht rekursiv: ein Unterordner im Posteingang ist eine Nutzer-Absicht, die die Automatik nicht überfahren darf."""
        os.makedirs(os.path.join(self.master, "0_Posteingang", "spaeter"))
        self._lege_datei_an("0_Posteingang", "spaeter", "nicht_anfassen.pdf")
        self._lege_datei_an("0_Posteingang", "direkt.pdf")

        dokumente = auto_pilot.sammle_posteingang_dokumente(self.master)

        self.assertEqual([os.path.basename(d) for d in dokumente], ["direkt.pdf"])

    def test_sammle_posteingang_dokumente_ohne_posteingang_liefert_leere_liste(self):
        shutil.rmtree(os.path.join(self.master, "0_Posteingang"))
        self.assertEqual(auto_pilot.sammle_posteingang_dokumente(self.master), [])

    def test_sammle_posteingang_dokumente_bei_leerem_posteingang(self):
        self.assertEqual(auto_pilot.sammle_posteingang_dokumente(self.master), [])


if __name__ == "__main__":
    unittest.main()


class TestObjektTag(unittest.TestCase):
    """
    Objekt/Ort als eigenes Tag unter "Objekte & Adressen" (Nutzerfund 01.09.2026:
    Ortsangaben wie "Musterheim" wurden praktisch nie vergeben, weil sie im 5er-Budget
    der allgemeinen Schlagworte untergingen - genau diese Kategorie braucht aber die
    Dubletten-Erkennung, um denselben Bescheid fuer zwei Grundstuecke zu unterscheiden).
    """

    def test_normiere_objekt_laesst_schreibvarianten_zusammenfallen(self):
        """Kaltstart-Test 03.09.2026: dieselbe Adresse stand in einem Dutzend Formen im Katalog."""
        n = auto_pilot.normiere_objekt
        # alle echten Varianten aus dem Testlauf fallen auf dieselbe Normalform
        for variante in ("Zum Alten Fass 1 u. 3 Musterheim", "Zum alten Fass 1 u. 3 Musterheim",
                         "Zum-Alten-Fass 1 u. 3 Musterheim", "Zum Alten Faß 1 u. 3 Musterheim",
                         "Zum Alten Fass 1 + 3 Musterheim", "Zum Alten Fass 1+3 Musterheim",
                         "Zum Alten Fass 1 u.3 Musterheim", "Zum alten Faß 1+3 Musterheim"):
            self.assertEqual(n(variante), n("Zum Alten Fass 1 u. 3 Musterheim"), variante)
        for variante in ("Weidenstr. 8 Whg Nr. 1 in Musterstadt", "Weidenstraße 8 Whg 1 Musterstadt",
                         "Weidenstrasse 8 Wohnung 1 Musterstadt", "Weidenstr.8 Wgh.Nr.1 in Musterstadt"):
            self.assertEqual(n(variante), n("Weidenstr. 8 Whg 1 Musterstadt"), variante)
        self.assertEqual(n("MUS-HM 738"), n("MUS HM 738"))
        # Haus- und Wohnungsnummern bleiben unterscheidend - dafür gibt es das Feature
        self.assertNotEqual(n("Zum Alten Fass 1"), n("Zum Alten Fass 3"))
        self.assertNotEqual(n("Weidenstr. 8 Whg 1"), n("Weidenstr. 8 Whg 2"))
        self.assertNotEqual(n("Zum Alten Fass 1"), n("Zum Alten Fass 1 u. 3"))

    def test_objekt_schnappt_auf_katalog_schreibweise(self):
        """Neue Varianten erzeugen KEIN neues Tag mehr, sondern übernehmen die Katalog-Form.
        Seit 27.10.2026 wird die Sammelangabe vorher in Einzel-Objekte zerlegt (ein Objekt je Tag)."""
        tags, kategorien = auto_pilot.tags_mit_empfaenger(
            {"tags": ["Grundsteuer"], "objekt": "Zum-Alten-Faß 1 u.3 Musterheim"},
            known_tags=["Rechnung", "Zum Alten Fass 1", "Zum Alten Fass 3", "Musterheim"],
            kategorien=["Personen", "Objekte & Adressen"])
        self.assertEqual(tags, ["Grundsteuer", "Zum Alten Fass 1", "Zum Alten Fass 3", "Musterheim"])

    def test_gleiche_objekte_im_dokument_werden_einmal_getaggt(self):
        tags, _ = auto_pilot.tags_mit_empfaenger(
            {"tags": [], "objekt": "Weidenstr. 8; Weidenstraße 8"},
            kategorien=["Objekte & Adressen"])
        self.assertEqual(tags, ["Weidenstr. 8"])

    def test_titel_mit_objekt(self):
        """Nutzerwunsch 03.09.2026: 6x 'Beitragsrechnung Gebäudeversicherung' ist ohne Objekt nicht unterscheidbar."""
        f = auto_pilot.titel_mit_objekt
        self.assertEqual(f("Beitragsrechnung Gebäudeversicherung", ["Weidenstr. 8"]),
                         "Beitragsrechnung Gebäudeversicherung Weidenstr. 8")
        # steht das Objekt schon (auch als Schreibvariante) im Titel, wird nichts angehängt
        self.assertEqual(f("Jahresabrechnung Weidenstraße 8", ["Weidenstr. 8"]),
                         "Jahresabrechnung Weidenstraße 8")
        self.assertEqual(f("", ["Weidenstr. 8"]), "")   # leerer Titel bleibt leer -> unsicher
        self.assertEqual(f("Kontoauszug", []), "Kontoauszug")

    def test_objekt_landet_im_titel_und_dateinamen(self):
        entscheidung = auto_pilot.baue_entscheidung(
            "C:/eingang/scan.pdf",
            _ki_antwort(title="Beitragsrechnung Gebäudeversicherung",
                        objekt="Weidenstr. 8 in Musterstadt", ort="Musterstadt"),
            VORHANDENE_ORDNER)
        self.assertEqual(entscheidung["titel"], "Beitragsrechnung Gebäudeversicherung Weidenstr. 8")
        self.assertIn("Weidenstr. 8", entscheidung["neuer_dateiname"])
        self.assertNotIn("Musterstadt", entscheidung["titel"])  # der Ort bleibt draußen

    def test_trenne_ort(self):
        """Nutzer-Entscheidung 03.09.2026: Ort und Objekt sind getrennte Tags."""
        f = auto_pilot.trenne_ort
        self.assertEqual(f("Weidenstr. 8 in Musterstadt"), ("Weidenstr. 8", "Musterstadt"))          # Ort klebt per " in "
        self.assertEqual(f("Weidenstr. 8 Musterstadt", "Musterstadt"), ("Weidenstr. 8", "Musterstadt"))   # Ort klebt ohne "in"
        self.assertEqual(f("Weidenstr. 8", "Musterstadt"), ("Weidenstr. 8", "Musterstadt"))          # KI liefert Ort getrennt
        self.assertEqual(f("Weidenstr. 8", ""), ("Weidenstr. 8", ""))
        self.assertEqual(f("Musterheim", "Musterheim"), ("Musterheim", "Musterheim"))              # reiner Ort bleibt stehen
        self.assertEqual(f("Zum Alten Fass 1 in Musterheim"), ("Zum Alten Fass 1", "Musterheim"))

    def test_ort_wird_eigenes_tag_neben_dem_objekt(self):
        tags, kategorien = auto_pilot.tags_mit_empfaenger(
            {"tags": ["Grundsteuer"], "objekt": "Weidenstr. 8 in Musterstadt", "ort": "Musterstadt"},
            kategorien=["Objekte & Adressen"])
        self.assertIn("Weidenstr. 8", tags)
        self.assertIn("Musterstadt", tags)
        self.assertNotIn("Weidenstr. 8 in Musterstadt", tags)
        self.assertEqual(kategorien["Musterstadt"], "Objekte & Adressen")

    def test_ort_ohne_objekt_wird_ignoriert(self):
        """Eine Ortsangabe ohne Objekt ist meist die Stadt aus dem Anschriftenfeld - kein Tag."""
        tags, _ = auto_pilot.tags_mit_empfaenger(
            {"tags": ["Rechnung"], "objekt": "", "ort": "Musterstadt"},
            kategorien=["Objekte & Adressen"])
        self.assertEqual(tags, ["Rechnung"])

    def test_ort_schnappt_auf_katalog_schreibweise(self):
        tags, _ = auto_pilot.tags_mit_empfaenger(
            {"tags": [], "objekt": "Zum Alten Fass 1", "ort": "musterheim"},
            known_tags=["Musterheim"], kategorien=["Objekte & Adressen"])
        self.assertEqual(tags, ["Zum Alten Fass 1", "Musterheim"])

    def test_objekt_wird_eigenes_tag_mit_kategorie(self):
        tags, kategorien = auto_pilot.tags_mit_empfaenger(
            {"tags": ["Grundsteuer"], "objekt": "Zum Alten Fass 1"},
            kategorien=["Personen", "Objekte & Adressen"])
        self.assertIn("Zum Alten Fass 1", tags)
        self.assertEqual(kategorien["Zum Alten Fass 1"], "Objekte & Adressen")

    def test_mehrere_objekte_werden_getrennt(self):
        tags, _ = auto_pilot.tags_mit_empfaenger(
            {"tags": [], "objekt": "Zum Alten Fass 1 und Zum Alten Fass 3"})
        self.assertIn("Zum Alten Fass 1", tags)
        self.assertIn("Zum Alten Fass 3", tags)

    def test_kategoriename_folgt_dem_katalog(self):
        """Gewachsener Katalog nennt den Zweig nur 'Adressen' - dorthin muss das Tag."""
        _, kategorien = auto_pilot.tags_mit_empfaenger(
            {"tags": [], "objekt": "Musterheim"}, kategorien=["Zeitraum", "Adressen", "Personen"])
        self.assertEqual(kategorien["Musterheim"], "Adressen")

    def test_ohne_passende_kategorie_bleibt_der_kanonische_name(self):
        _, kategorien = auto_pilot.tags_mit_empfaenger(
            {"tags": [], "objekt": "Musterheim"}, kategorien=["Zeitraum"])
        self.assertEqual(kategorien["Musterheim"], auto_pilot.KATEGORIE_OBJEKTE)

    def test_leeres_objekt_ist_kein_fehler(self):
        tags, kategorien = auto_pilot.tags_mit_empfaenger({"tags": ["Rechnung"], "objekt": ""})
        self.assertEqual(tags, ["Rechnung"])
        self.assertEqual(kategorien, {})

    def test_objekt_auf_der_ignorierliste_faellt_weg(self):
        tags, _ = auto_pilot.tags_mit_empfaenger(
            {"tags": [], "objekt": "Musterheim"}, ignorierte=["musterheim"])
        self.assertEqual(tags, [])


class TestOhneZielordnerTags(unittest.TestCase):
    """
    Der Zielordner steht schon am Dokument - ihn zusaetzlich als Tag zu fuehren ist
    Doppelung (Nutzerwunsch 01.09.2026).
    """

    def test_ordnername_faellt_als_tag_weg(self):
        tags = auto_pilot.ohne_zielordner_tags(
            ["Grundsteuer", "Finanzamt Musterstadt", "2023"], r"A - B - C\Finanzamt Musterstadt")
        self.assertEqual(tags, ["Grundsteuer", "2023"])

    def test_ort_bleibt_erhalten(self):
        """Nur Gleichheit zaehlt, nie Teilstring - 'Musterstadt' ist eine eigene Information."""
        tags = auto_pilot.ohne_zielordner_tags(
            ["Musterstadt", "Grundsteuer"], r"A - B - C\Finanzamt Musterstadt")
        self.assertEqual(tags, ["Musterstadt", "Grundsteuer"])

    def test_gross_klein_und_leerraum_egal(self):
        tags = auto_pilot.ohne_zielordner_tags(["  finanzamt musterstadt "], "Finanzamt Musterstadt")
        self.assertEqual(tags, [])

    def test_telefonbuch_ordner_auch_ueber_den_kernnamen(self):
        tags = auto_pilot.ohne_zielordner_tags(
            ["Carius", "Zahnarzt"], r"A - B - C\Carius, Dr. Emil (Zahnarzt)")
        self.assertEqual(tags, ["Zahnarzt"])

    def test_ohne_zielordner_bleibt_alles(self):
        self.assertEqual(auto_pilot.ohne_zielordner_tags(["A", "B"], ""), ["A", "B"])

    def test_in_der_entscheidung_stehen_keine_tags_und_sie_bleibt_sicher(self):
        entscheidung = auto_pilot.baue_entscheidung(
            "scan.pdf",
            {"title": "Grundsteuerbescheid", "tags": ["Grundsteuer", "Finanzamt Musterstadt"],
             "datum": "2023-07-18", "absender": "Finanzamt Musterstadt", "ordnername": "Finanzamt Musterstadt"},
            ["A - B - C - D - E - F", r"A - B - C - D - E - F\Finanzamt Musterstadt"])
        self.assertEqual(entscheidung["zielordner"], r"A - B - C - D - E - F\Finanzamt Musterstadt")
        self.assertEqual(entscheidung["tags"], [])           # Etappe 6: die KI vergibt keine Tags mehr
        self.assertTrue(entscheidung["sicher"])

    def test_ohne_tags_bleibt_die_ablage_sicher(self):
        entscheidung = auto_pilot.baue_entscheidung(
            "scan.pdf",
            {"title": "Schreiben", "tags": ["Gentilia"], "datum": "2023-07-18",
             "absender": "Gentilia", "ordnername": "Gentilia"},
            ["Gentilia"])
        self.assertEqual(entscheidung["tags"], [])
        self.assertTrue(entscheidung["sicher"], entscheidung["probleme"])


class TestTeileObjekte(unittest.TestCase):
    """
    Objekt-Angaben der KI muessen zu garantiert KOMMAFREIEN Tags zerfallen -
    ein Tag mit Komma ueberlebt den Rundlauf durchs PDF-Schlagwortfeld nicht
    (FALLSTRICKE #38). Live-Fund 01.09.2026: 'Weidenstr. 8, Wgh.Nr.5'.
    """

    def test_komma_trennt(self):
        self.assertEqual(auto_pilot.teile_objekte("Weidenstr. 8, Wgh.Nr.5"),
                         ["Weidenstr. 8", "Wgh.Nr.5"])

    def test_kein_ergebnis_enthaelt_je_ein_komma(self):
        for roh in ("Zum Alten Fass 1, Weidenstr. 8 Wgh.Nr. 2", "A, B; C / D und E"):
            for tag in auto_pilot.teile_objekte(roh):
                self.assertNotIn(",", tag)

    def test_und_trennt(self):
        self.assertEqual(auto_pilot.teile_objekte("Zum Alten Fass 1 und Zum Alten Fass 3"),
                         ["Zum Alten Fass 1", "Zum Alten Fass 3"])

    def test_reine_postleitzahl_faellt_weg(self):
        self.assertEqual(auto_pilot.teile_objekte("Zum Alten Fass 1, 12345"), ["Zum Alten Fass 1"])

    def test_leer_und_zu_kurz(self):
        self.assertEqual(auto_pilot.teile_objekte(""), [])
        self.assertEqual(auto_pilot.teile_objekte(None), [])
        self.assertEqual(auto_pilot.teile_objekte("  ,  ; a "), [])

    def test_doppelte_nennung_nur_einmal(self):
        self.assertEqual(auto_pilot.teile_objekte("Musterheim und musterheim"), ["Musterheim"])

    def test_einzelnes_objekt_bleibt_unveraendert(self):
        self.assertEqual(auto_pilot.teile_objekte("Zum Alten Fass 1"), ["Zum Alten Fass 1"])


class TestOrdnernameAlsTagFilter(unittest.TestCase):
    """
    Live-Fund 01.09.2026: der reale Ordner heisst kurz ("Finanzamt"), der Absender-Tag
    lang ("Finanzamt Musterstadt") - ohne Vergleich gegen den Ordnernamen blieb er stehen.
    """

    def test_absendername_faellt_auch_bei_kuerzerem_ordner_weg(self):
        tags = auto_pilot.ohne_zielordner_tags(
            ["Grundsteuer", "Finanzamt Musterstadt"], r"A - B - C\Finanzamt", "Finanzamt Musterstadt")
        self.assertEqual(tags, ["Grundsteuer"])

    def test_ort_bleibt_auch_dann_erhalten(self):
        tags = auto_pilot.ohne_zielordner_tags(
            ["Musterstadt", "Grundsteuer"], r"A - B - C\Finanzamt", "Finanzamt Musterstadt")
        self.assertEqual(tags, ["Musterstadt", "Grundsteuer"])


class TestTagWildwuchsTeil2(unittest.TestCase):
    """
    Neu-Einlese-Lauf 07.09.2026 (Snapshots 2239 vs 2347): 17 Objekt-Varianten neben
    grauen Katalog-Adressen, fünf Erbengemeinschaft-Schreibweisen, bloße Nachnamen,
    PLZ als Objekt, angeklebte Anschrift am Empfänger.
    """

    KATALOG = ["Rechnung", "Christian Lehmann", "Egon Zieger", "Hermann Mustermann", "Peter Mustermann",
               "Mustermann Hermann und Werner", "Erbengemeinschaft Mustermann Hermann Mustermann Werner Mustermann"]

    def test_personen_wortmenge_und_verbinder(self):
        f = personen_namen.finde_personen_schreibweise
        self.assertEqual(f("Mustermann Hermann & Werner", self.KATALOG), "Mustermann Hermann und Werner")
        self.assertEqual(f("Werner und Hermann Mustermann", self.KATALOG), "Mustermann Hermann und Werner")
        self.assertEqual(f("Mustermann Erbengemeinschaft Hermann und Werner", self.KATALOG),
                         "Erbengemeinschaft Mustermann Hermann Mustermann Werner Mustermann")
        self.assertIsNone(f("Erbengemeinschaft Hermann", self.KATALOG))   # Teilmenge reicht nicht

    def test_blosser_nachname_nur_wenn_eindeutig(self):
        f = personen_namen.finde_personen_schreibweise
        self.assertEqual(f("Lehmann", self.KATALOG), "Christian Lehmann")
        self.assertEqual(f("zieger", self.KATALOG), "Egon Zieger")
        self.assertIsNone(f("Mustermann", self.KATALOG))      # Hermann, Peter, ... - mehrdeutig
        self.assertIsNone(f("Roth", self.KATALOG))      # unbekannt

    def test_ohne_anschrift(self):
        self.assertEqual(personen_namen.ohne_anschrift("Hermann Mustermann Weidenstr. 8"), "Hermann Mustermann")
        self.assertEqual(personen_namen.ohne_anschrift("Werner Mustermann, Dorfstraße 38"), "Werner Mustermann")
        self.assertEqual(personen_namen.ohne_anschrift("Weidenstraße 8"), "")
        self.assertEqual(personen_namen.ohne_anschrift("Hermann Mustermann"), "Hermann Mustermann")

    def test_empfaenger_ohne_anschrift_und_adresse_ist_keine_person(self):
        tags, kat = auto_pilot.tags_mit_empfaenger(
            _ki_antwort(tags=["Rechnung"], empfaenger="Hermann Mustermann Weidenstr. 8"),
            known_tags=["Rechnung"], kategorien=["Weidenstr. 8", "Hermann Mustermann"])
        self.assertEqual(tags, ["Rechnung", "Hermann Mustermann"])
        tags, _ = auto_pilot.tags_mit_empfaenger(_ki_antwort(tags=["Rechnung"], empfaenger="Weidenstraße 8"))
        self.assertEqual(tags, ["Rechnung"])

    def test_objekt_schnappt_auch_auf_graue_katalog_adresse(self):
        # 'Weidenstr. 8 Whg 2' ist bei Peter ein grauer Struktur-Knoten (nicht in known_tags)
        tags, _ = auto_pilot.tags_mit_empfaenger(
            {"tags": ["Grundsteuer"], "objekt": "Weidenstr. 8 Whg Nr. 2"},
            known_tags=["Grundsteuer"], kategorien=["Musterstadt", "Weidenstr. 8 Whg 2", "Objekte & Adressen"])
        self.assertIn("Weidenstr. 8 Whg 2", tags)
        self.assertNotIn("Weidenstr. 8 Whg Nr. 2", tags)
        self.assertEqual(auto_pilot.objekte_ohne_ort(
            {"objekt": "Zum-Alten-Fass 3"}, ["Rechnung"], ["Zum Alten Fass 3"]), ["Zum Alten Fass 3"])

    def test_plz_ist_kein_objekt(self):
        self.assertEqual(auto_pilot.ohne_plz("12345 Musterstadt"), "Musterstadt")
        self.assertEqual(auto_pilot.ohne_plz("Weidenstr. 8"), "Weidenstr. 8")
        self.assertEqual(auto_pilot.ohne_plz("12345"), "12345")
        tags, _ = auto_pilot.tags_mit_empfaenger(
            {"tags": ["Bescheid"], "objekt": "12345 Musterstadt", "ort": "Musterstadt"}, kategorien=["Objekte & Adressen"])
        self.assertEqual(tags, ["Bescheid", "Musterstadt"])
        tags, _ = auto_pilot.tags_mit_empfaenger(
            {"tags": ["Bescheid"], "objekt": "Weidenstr. 8", "ort": "12345 Musterstadt"}, kategorien=["Objekte & Adressen"])
        self.assertEqual(tags, ["Bescheid", "Weidenstr. 8", "Musterstadt"])


class TestKiTagsMitKategorie(unittest.TestCase):
    """
    Wiederholungslauf 08.09.2026: KI-Tags, die die KI selbst als 'Personen' oder
    'Objekte & Adressen' einstuft, laufen über dieselben Regeln wie Empfänger- und
    Objekt-Feld - vorher kamen '12345 Musterstadt', 'Hermann Mustermann Peter Mustermann' und
    'Kunden der iqua Deutschland GmbH' ungefiltert in den Katalog.
    """

    def test_ist_personenname(self):
        f = personen_namen.ist_personenname
        for ja in ("Dr. Emil Carius", "Uta Berta Mustermann", "Bichler/Prem", "Zippel"):
            self.assertTrue(f(ja), ja)
        for nein in ("12345 Musterstadt", "Kunden der iqua Deutschland GmbH", "An alle Haushalte der Wasserversorgung",
                     "Iqua Deutschland GmbH", "Sehr geehrte Damen und Herren", "", "a b c d e f"):
            self.assertFalse(f(nein), nein)

    def test_personen_tags_der_ki_laufen_durch_die_personenregeln(self):
        tags, kat = auto_pilot.tags_mit_empfaenger(
            {"tags": ["Rechnung", "Hermann Mustermann Peter Mustermann", "12345 Musterstadt", "Kunden der iqua Deutschland GmbH",
                      "Mustermann Hermann"],
             "tag_kategorien": {"Hermann Mustermann Peter Mustermann": "Personen", "12345 Musterstadt": "Personen",
                                "Kunden der iqua Deutschland GmbH": "Personen", "Mustermann Hermann": "Personen"}},
            known_tags=["Rechnung"], kategorien=["Personen", "Hermann Mustermann", "Peter Mustermann"])
        self.assertEqual(tags, ["Rechnung", "Hermann Mustermann", "Peter Mustermann"])
        self.assertEqual(kat["Peter Mustermann"], auto_pilot.KATEGORIE_PERSONEN)

    def test_objekt_tags_der_ki_laufen_durch_die_objektregeln(self):
        tags, kat = auto_pilot.tags_mit_empfaenger(
            {"tags": ["Grundsteuer", "Weidenstr. 8 Whg Nr. 2", "12345"],
             "tag_kategorien": {"Weidenstr. 8 Whg Nr. 2": "Objekte & Adressen", "12345": "Adressen"},
             "objekt": "Weidenstraße 8 Whg 2"},
            known_tags=["Grundsteuer"], kategorien=["Objekte & Adressen", "Weidenstr. 8 Whg 2"])
        self.assertEqual(tags, ["Grundsteuer", "Weidenstr. 8 Whg 2"])
        self.assertEqual(kat["Weidenstr. 8 Whg 2"], "Objekte & Adressen")

    def test_empfaenger_sammelanrede_ist_keine_person(self):
        tags, _ = auto_pilot.tags_mit_empfaenger(
            _ki_antwort(tags=["Info"], empfaenger="An alle Haushalte der Wasserversorgung des Wasserzweckverbandes"))
        self.assertEqual(tags, ["Info"])


class TestPersonenTitel(unittest.TestCase):
    """Wiederholungslauf 08.09.2026: 'Johann Schuff' stand neben 'Dr. Johann Schuff' im Katalog."""

    def test_ohne_titel(self):
        self.assertEqual(personen_namen.ohne_titel("Dr. med. Emil Carius"), "Emil Carius")
        self.assertEqual(personen_namen.ohne_titel("Prof. Dr. h.c. Maier"), "Maier")
        self.assertEqual(personen_namen.ohne_titel("Hermann Mustermann"), "Hermann Mustermann")
        self.assertEqual(personen_namen.ohne_titel("Dipl.-Ing. Peter Mustermann"), "Peter Mustermann")

    def test_titel_variante_schnappt_auf_katalog_form(self):
        f = personen_namen.finde_personen_schreibweise
        katalog = ["Dr. Johann Schuff", "Dr. Emil Carius", "Hermann Mustermann"]
        self.assertEqual(f("Johann Schuff", katalog), "Dr. Johann Schuff")
        self.assertEqual(f("Schuff Johann", katalog), "Dr. Johann Schuff")     # gedreht + ohne Titel
        self.assertEqual(f("Carius, Dr. Emil", ["Emil Carius"]), "Emil Carius")   # Titel nur beim Vorschlag
        self.assertEqual(f("Dr. Hermann Mustermann", katalog), "Hermann Mustermann")
        self.assertIsNone(f("Johann Schmidt", katalog))


class TestSynonymKnoten(unittest.TestCase):
    """Synonym-Knoten des Katalogs (08.09.2026): KI-Text -> Tag darüber, der Synonym-Text selbst nie."""

    SYNONYME = {"haftpflichtversicherung": "Haftpflicht", "privathaftpflicht": "Haftpflicht",
                "einkommensteuer": "Steuererklärung"}
    KATALOG = ["Rechnung", "Versicherung", "Haftpflicht", "Steuererklärung"]

    def test_ersetze_synonyme(self):
        tags, ersetzt = auto_pilot.ersetze_synonyme(
            ["Rechnung", "Haftpflichtversicherung", "Privathaftpflicht", "Haftpflicht", "EINKOMMENSTEUER"], self.SYNONYME)
        self.assertEqual(tags, ["Rechnung", "Haftpflicht", "Steuererklärung"])
        self.assertEqual(ersetzt, [("Haftpflichtversicherung", "Haftpflicht"), ("Privathaftpflicht", "Haftpflicht"),
                                   ("EINKOMMENSTEUER", "Steuererklärung")])
        self.assertEqual(auto_pilot.ersetze_synonyme(["Rechnung"], None), (["Rechnung"], []))
        self.assertEqual(auto_pilot.ersetze_synonyme(["Rechnung"], {}), (["Rechnung"], []))

class TestGraueKategorieNieVergeben(unittest.TestCase):
    """Nutzerfund 08.09.2026: grauer Personen-Knoten 'Hermann Mustermann' kam als Empfänger-Tag ins Dokument."""

    def test_graue_adresse_bleibt_im_titel_aber_nicht_als_tag(self):
        antwort = _ki_antwort(tags=["Grundsteuer"], objekt="Weidenstr. 8 Whg Nr. 2")
        e = auto_pilot.baue_entscheidung("dok.pdf", antwort, VORHANDENE_ORDNER, known_tags=["Grundsteuer"],
                                         kategorien=["Objekte & Adressen", "Weidenstr. 8 Whg 2"])
        self.assertEqual(e["tags"], [])
        self.assertIn("Weidenstr. 8 Whg 2", e["titel"])
        self.assertEqual(e["neue_tags"], [])

class TestEigenbelegeUeberObjekt(unittest.TestCase):
    """Eigenbelege ohne Absender (11.09.2026): Zielordner über einen gelernten Objekt-Alias."""

    ORDNER = VORHANDENE_ORDNER + ["U - Z", "U - Z\\Weidenstr. 8"]
    ALIASE = {"Objekt: Weidenstr. 8": "U - Z\\Weidenstr. 8", "Stadtwerke Musterstadt": "Stadtwerke"}

    def _eigenbeleg(self, **kw):
        antwort = _ki_antwort(title="Zählerstand Gas", tags=["Zählerstand"], absender="",
                              objekt="Weidenstr. 8 Whg 4", datum="2026-03-01")
        antwort.update(kw)
        return antwort

    def test_objekt_alias_ordnet_absenderlosen_beleg_zu(self):
        e = auto_pilot.baue_entscheidung("Zaehlerstand.pdf", self._eigenbeleg(), self.ORDNER, aliase=self.ALIASE)
        self.assertEqual(e["zielordner"], "U - Z\\Weidenstr. 8")
        self.assertTrue(e["ordner_per_alias"])
        self.assertEqual(e["ordner_hinweis"], "Objekt")
        self.assertFalse(e["ordner_neu"])
        self.assertEqual(e["objekte"], ["Weidenstr. 8 Whg 4"])
        self.assertTrue(e["sicher"], e["probleme"])

    def test_mit_absender_gewinnt_der_absender(self):
        # Brief der Stadtwerke über dasselbe Haus gehört weiter zu den Stadtwerken
        e = auto_pilot.baue_entscheidung("Rechnung.pdf", self._eigenbeleg(absender="Stadtwerke Musterstadt"),
                                         self.ORDNER, aliase=self.ALIASE)
        self.assertEqual(e["zielordner"], "Stadtwerke")
        self.assertEqual(e["ordner_hinweis"], "")

    def test_ohne_alias_bleibt_unsicher_mit_wink(self):
        e = auto_pilot.baue_entscheidung("Zaehlerstand.pdf", self._eigenbeleg(), self.ORDNER, aliase={})
        self.assertFalse(e["sicher"])
        self.assertEqual(e["zielordner"], "")
        self.assertTrue(any(p.startswith("kein Zielordner und kein Absender erkannt")
                            and "Objekt 'Weidenstr. 8 Whg 4'" in p for p in e["probleme"]), e["probleme"])
        # Korrektur per Klick räumt genau dieses Problem weg
        korrigiert = auto_pilot.wende_zielordner_an(e, "U - Z\\Weidenstr. 8", self.ORDNER)
        self.assertTrue(korrigiert["sicher"], korrigiert["probleme"])

    def test_ohne_objekt_kein_wink(self):
        e = auto_pilot.baue_entscheidung("Notiz.pdf", self._eigenbeleg(objekt=""), self.ORDNER, aliase=self.ALIASE)
        self.assertIn("kein Zielordner und kein Absender erkannt", e["probleme"])
        self.assertEqual(e["objekte"], [])

    def test_alias_schluessel_und_trifft(self):
        mit_absender = {"absender": "Gentilia AG", "objekte": ["Weidenstr. 8"]}
        ohne_absender = {"absender": "", "objekte": ["Weidenstr. 8 Whg 2"]}
        anderes_objekt = {"absender": "", "objekte": ["Hobbyraum"]}
        self.assertEqual(auto_pilot.alias_schluessel(mit_absender), ("Gentilia AG", "Absender"))
        # gelernt wird auf Haus-Ebene (alle Wohnungen des Hauses in denselben Ordner)
        self.assertEqual(auto_pilot.alias_schluessel(ohne_absender), ("Objekt: Weidenstr. 8", "Objekt"))
        self.assertEqual(auto_pilot.alias_schluessel({"absender": "", "objekte": []}), ("", ""))
        # Objekt-Alias gilt nur für absenderlose Zeilen mit passendem Objekt
        self.assertTrue(auto_pilot.alias_trifft(ohne_absender, "Objekt: Weidenstr. 8", "U - Z\\Weidenstr. 8"))
        self.assertFalse(auto_pilot.alias_trifft(mit_absender, "Objekt: Weidenstr. 8", "U - Z\\Weidenstr. 8"))
        self.assertFalse(auto_pilot.alias_trifft(anderes_objekt, "Objekt: Weidenstr. 8", "U - Z\\Weidenstr. 8"))
        # Absender-Alias wie bisher nur über den Absender
        self.assertTrue(auto_pilot.alias_trifft(mit_absender, "Gentilia", "A - B - C\\Gentilia"))
        self.assertFalse(auto_pilot.alias_trifft(ohne_absender, "Gentilia", "A - B - C\\Gentilia"))


class TestUmbenennenUndOriginalname(TestFuehreEntscheidungAus):
    """Dateinamen (Peter 11.09.2026): Originalname einbrennen, Umbenennen abschaltbar."""

    def _sicher(self):
        return auto_pilot.baue_entscheidung(
            self.pdf_path, _ki_antwort(absender="Gentilia Deutschland Versicherung AG"), VORHANDENE_ORDNER)

    def test_originalname_wird_beim_umbenennen_eingebrannt_und_nie_ueberschrieben(self):
        ergebnis = auto_pilot.fuehre_entscheidung_aus(self._sicher(), self.master, self._verschieben)
        self.assertTrue(ergebnis["erfolg"], ergebnis["fehler"])
        self.assertEqual(PDFHandler.get_metadata(ergebnis["neuer_pfad"])["KID_Originalname"], "eingang.pdf")
        # zweite Ablage mit anderem Titel: neuer Dateiname, aber der ALLERERSTE Name bleibt
        zweite = auto_pilot.baue_entscheidung(
            ergebnis["neuer_pfad"], _ki_antwort(title="Ganz anderer Titel", absender="Stadtwerke"), VORHANDENE_ORDNER)
        ergebnis2 = auto_pilot.fuehre_entscheidung_aus(zweite, self.master, self._verschieben)
        self.assertTrue(ergebnis2["erfolg"], ergebnis2["fehler"])
        self.assertTrue(ergebnis2["neuer_pfad"].endswith("20260618_Ganz anderer Titel.pdf"))
        meta = PDFHandler.get_metadata(ergebnis2["neuer_pfad"])
        self.assertEqual(meta["KID_Originalname"], "eingang.pdf")
        self.assertEqual(meta["title"], "Ganz anderer Titel")
        self.assertEqual(meta["KID_DokumentenDatum"], "2026-06-18")

    def test_ohne_umbenennen_bleibt_der_dateiname(self):
        ergebnis = auto_pilot.fuehre_entscheidung_aus(self._sicher(), self.master, self._verschieben, umbenennen=False)
        self.assertTrue(ergebnis["erfolg"], ergebnis["fehler"])
        self.assertEqual(ergebnis["neuer_pfad"], os.path.join(self.master, "A - B - C", "Gentilia", "eingang.pdf"))
        meta = PDFHandler.get_metadata(ergebnis["neuer_pfad"])
        self.assertEqual(meta["title"], "Beitragsrechnung Haftpflichtversicherung")  # Metadaten kommen trotzdem
        self.assertEqual(meta["KID_DokumentenDatum"], "2026-06-18")
        self.assertEqual(meta["KID_Originalname"], "")  # nichts umbenannt -> nichts zu merken

    def test_unsicher_bleibt_auch_mit_umbenennen_unveraendert(self):
        entscheidung = auto_pilot.baue_entscheidung(self.pdf_path, _ki_antwort(absender=""), VORHANDENE_ORDNER)
        ergebnis = auto_pilot.fuehre_entscheidung_aus(entscheidung, self.master, self._verschieben, umbenennen=True)
        self.assertEqual(os.path.basename(ergebnis["neuer_pfad"]), "eingang.pdf")
        self.assertEqual(PDFHandler.get_metadata(ergebnis["neuer_pfad"])["KID_Originalname"], "")


class TestAdresszeileAlsAbsender(unittest.TestCase):
    """Live-Fund 07.09.2026: 'Bay. LfSt, PF 0151 Straubing' wurde als Ordner angelegt."""

    def test_trenne_adresszeile(self):
        self.assertEqual(auto_pilot.trenne_adresszeile("Bay. LfSt, PF 0151 Straubing"), ("Bay. LfSt", True))
        self.assertEqual(auto_pilot.trenne_adresszeile("Bay. LfSt Postfach 0151, 94301 Straubing"), ("Bay. LfSt", True))
        self.assertEqual(auto_pilot.trenne_adresszeile("Stadtwerke Musterstadt, 12345 Musterstadt"), ("Stadtwerke Musterstadt", True))
        self.assertEqual(auto_pilot.trenne_adresszeile("Gentilia Versicherung Weidenstr. 8"), ("Gentilia Versicherung", True))
        self.assertEqual(auto_pilot.trenne_adresszeile("Stadtwerke Musterstadt"), ("Stadtwerke Musterstadt", False))
        self.assertEqual(auto_pilot.trenne_adresszeile("Finanzamt Musterstadt"), ("Finanzamt Musterstadt", False))
        self.assertEqual(auto_pilot.trenne_adresszeile(""), ("", False))
        self.assertEqual(auto_pilot.trenne_adresszeile(None), ("", False))

    def test_absender_ist_kuerzel(self):
        for ja in ("Bay. LfSt", "Bay. LfSt.", "BayLfSt"):
            self.assertTrue(auto_pilot.absender_ist_kuerzel(ja), ja)
        for nein in ("ADAC", "HKV", "Stadtwerke Musterstadt", "St. Josef Krankenhaus", "Dr. Emil Carius",
                     "Bayerisches Landesamt für Steuern", "Finanzamt Musterstadt", ""):
            self.assertFalse(auto_pilot.absender_ist_kuerzel(nein), nein)

    def test_kuerzel_aus_adresszeile_wird_kein_neuer_ordner(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Bay. LfSt, PF 0151 Straubing"), VORHANDENE_ORDNER)
        self.assertFalse(e["sicher"])
        self.assertEqual(e["absender"], "Bay. LfSt")
        self.assertEqual(e["zielordner"], "")
        self.assertFalse(e["ordner_neu"])
        self.assertTrue(any("Kürzel aus der Adresszeile" in p and "Bay. LfSt" in p for p in e["probleme"]), e["probleme"])

    def test_zielordner_klick_raeumt_kuerzel_hinweis_weg(self):
        """Betatest 25.10.2026: Der Hinweis verlangte den Klick, der Klick ließ ihn aber stehen."""
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Bay. LfSt, PF 0151 Straubing"), VORHANDENE_ORDNER)
        self.assertIn(next(p for p in e["probleme"] if "Kürzel" in p), auto_pilot.korrigierbare_probleme(e))
        neu = auto_pilot.wende_zielordner_an(e, "Stadtwerke", VORHANDENE_ORDNER)
        self.assertTrue(neu["sicher"], neu["probleme"])

    def test_ki_ordnername_mit_adresse_wird_bereinigt(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Bay. LfSt, PF 0151 Straubing",
                                                                 ordnername="Bay. LfSt, PF 0151 Straubing"), VORHANDENE_ORDNER)
        self.assertEqual(e["ordnername"], "Bay. LfSt")
        self.assertFalse(e["sicher"])

    def test_alias_auf_den_kern_macht_es_sicher(self):
        """Nach dem Zielordner-Klick: Alias-Schlüssel ist der Kern ohne Adresse - beim nächsten Brief greift er."""
        ordner = VORHANDENE_ORDNER + ["A - B - C\\Bayerisches Landesamt für Steuern"]
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Bay. LfSt, PF 0151 Straubing"), ordner)
        self.assertEqual(auto_pilot.alias_schluessel(e), ("Bay. LfSt", "Absender"))
        aliase = {"Bay. LfSt": "A - B - C\\Bayerisches Landesamt für Steuern"}
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Bay. LfSt, PF 0152 Straubing"), ordner, aliase=aliase)
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], "A - B - C\\Bayerisches Landesamt für Steuern")
        self.assertTrue(e["ordner_per_alias"])

    def test_adresse_ohne_kuerzel_bleibt_normaler_absender(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Stadtwerke Musterstadt, 12345 Musterstadt"), VORHANDENE_ORDNER)
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], "Stadtwerke")
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Telenetz Deutschland, Postfach 2000 Bonn"), VORHANDENE_ORDNER)
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], "Telenetz Deutschland")
        self.assertTrue(e["ordner_neu"])


class TestDoppelordnerBremse(unittest.TestCase):
    """
    Betatest 25.10.2026: 28 neue Ordner neben bestehenden (11 % der Ablagen) - Kürzel-Ordner
    waren für den Vergleich zu kurz, abgekürzte Ordnernamen passten nie, und ähnliche Namen
    erzeugten still einen zweiten Ordner. Stufe A ordnet die eindeutigen Fälle zu, Stufe B
    lässt bei bloßer Ähnlichkeit den Menschen entscheiden.
    """

    ORDNER = ["G - H - I", "G - H - I\\HKV", "S - T - U", "S - T - U\\WMV", "A - B - C",
              "A - B - C\\Bayr. Landesamt f. Statistik", "A - B - C\\ELSTER",
              "S - T - U\\Vivafone Kabel Deutschland", "S - T - U\\WZV Musterdorf",
              "J - K - L", "J - K - L\\Kornmeier Landtechnik"]

    def _entscheidung(self, absender, ordnername=None):
        return auto_pilot.baue_entscheidung(
            "dok.pdf", _ki_antwort(absender=absender, ordnername=ordnername or absender), self.ORDNER)

    # --- Stufe A: sicher zuordnen
    def test_kuerzel_ordner_trifft_gross_geschriebenes_wort(self):
        self.assertEqual(auto_pilot.finde_passenden_ordner("HKV Versicherung AG", self.ORDNER), "G - H - I\\HKV")
        self.assertEqual(auto_pilot.finde_passenden_ordner("WMV-Versicherung AG", self.ORDNER), "S - T - U\\WMV")

    def test_kuerzel_klein_geschrieben_oder_im_wort_trifft_nicht(self):
        self.assertIsNone(auto_pilot.finde_passenden_ordner("Hkv-Fanclub Musterstadt", self.ORDNER))
        self.assertIsNone(auto_pilot.finde_passenden_ordner("SHKVX Handel", self.ORDNER))

    def test_rechtsform_ist_kein_kuerzel_ordner(self):
        self.assertIsNone(auto_pilot.finde_passenden_ordner("Muster AG", ["AG"]))

    def test_exakter_kurzer_name_trifft(self):
        self.assertEqual(auto_pilot.finde_passenden_ordner("WMV", self.ORDNER), "S - T - U\\WMV")
        e = self._entscheidung("WMV")
        self.assertEqual(e["zielordner"], "S - T - U\\WMV")
        self.assertFalse(e["ordner_neu"])

    def test_abgekuerzter_ordnername_trifft_ausgeschriebenen_absender(self):
        self.assertEqual(auto_pilot.finde_passenden_ordner("Bayerisches Landesamt für Statistik", self.ORDNER),
                         "A - B - C\\Bayr. Landesamt f. Statistik")

    def test_abgekuerzter_ordnername_braucht_alle_vollen_woerter(self):
        # 'Landesamt' allein reicht nicht - sonst landete die Steuer-Post bei der Statistik
        self.assertIsNone(auto_pilot.finde_passenden_ordner("Bayerisches Landesamt für Steuern",
                                                            ["A - B - C\\Bayr. Landesamt f. Statistik"]))

    # --- Stufe B: ähnlich -> Mensch entscheidet
    def test_aehnlicher_ordner_statt_doppelordner(self):
        for absender, erwartet in (("Vivafone Deutschland GmbH", "S - T - U\\Vivafone Kabel Deutschland"),
                                   ("ElsterOnline", "A - B - C\\ELSTER"),
                                   ("Kornmair Landtechnik", "J - K - L\\Kornmeier Landtechnik")):
            e = self._entscheidung(absender)
            self.assertFalse(e["sicher"], absender)
            self.assertFalse(e["ordner_neu"], absender)
            self.assertEqual(e["zielordner"], erwartet, absender)
            # 'ElsterOnline' gilt als Kürzel (Binnen-Großbuchstabe) - dann steht dieser Grund da
            self.assertTrue(any(p.startswith(("Ähnlicher Ordner vorhanden", "Absender nur als Kürzel"))
                                for p in e["probleme"]), e["probleme"])

    def test_ein_gemeinsames_wort_und_beide_mit_eigenen_woertern_gibt_neuen_ordner(self):
        # Mail-Lauf 05.11.2026: 11 von 17 PDFs in 0_Unsicher. Der Preis ist ein gelegentlicher Doppelordner
        for absender, erwartet in (("Wasserversorgungsgruppe Musterdorf", "Wasserversorgungsgruppe Musterdorf"),
                                   ("Zweckverband Musterdorf", "Zweckverband Musterdorf")):
            e = self._entscheidung(absender)
            self.assertTrue(e["sicher"], e["probleme"])
            self.assertTrue(e["ordner_neu"], absender)
            self.assertTrue(e["zielordner"].endswith(erwartet), e["zielordner"])

    def test_name_steckt_ganz_im_ordner_bleibt_aehnlich(self):
        for name, ordner in (("Musterstadt", "Bürgerbüro Musterstadt"), ("Kabel Vivafone", "Vivafone Kabel Deutschland"),
                             ("Beispiel Musterwerke Nord", "Musterwerke")):
            self.assertFalse(auto_pilot._verschiedene_absender(name, ordner), (name, ordner))
        self.assertTrue(auto_pilot._verschiedene_absender("Landratsamt Musterstadt", "Bürgerbüro Musterstadt"))
        self.assertTrue(auto_pilot._verschiedene_absender("Kaminkehrer Abcdef", "Abcdef (Bezirk) Nord"))
        # zwei gemeinsame Wörter sind nicht mehr „nur ein Wort“
        self.assertFalse(auto_pilot._verschiedene_absender("Stadtwerke Musterstadt Süd", "Stadtwerke Musterstadt Nord"))

    def test_bester_kandidat_nach_anteil(self):
        # ELSTER (1 von 1 Wort) schlägt 'Bayr. Landesamt f. Statistik' (1 von 2)
        self.assertEqual(auto_pilot.finde_aehnlichen_ordner(
            ["Bayerisches Landesamt für Steuern Zentralstelle ElsterOnline"], self.ORDNER), "A - B - C\\ELSTER")

    def test_ohne_aehnlichkeit_entsteht_der_neue_ordner_wie_bisher(self):
        e = self._entscheidung("Musterfirma Beispiel GmbH")
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertTrue(e["ordner_neu"])

    def test_kurze_und_allerweltswoerter_zaehlen_nicht(self):
        ordner = ["Haus Abc", "Stadtwerke Musterstadt", "Landratsamt Musterstadt"]
        # 'Haus' ist zu kurz, 'Musterstadt' steht in zwei Ordnern (Allerweltswort)
        self.assertIsNone(auto_pilot.finde_aehnlichen_ordner(["Haus Beispiel", "Musterstadt Bürgerbüro"], ordner))

    def test_buchstabengruppen_sind_keine_kandidaten(self):
        self.assertIsNone(auto_pilot.finde_aehnlichen_ordner(["Abcde Fghij"], ["A - B - C - D - E - F"]))

    def test_zielordner_klick_bestaetigt_aehnlichen_ordner(self):
        e = self._entscheidung("Vivafone Deutschland GmbH")
        neu = auto_pilot.wende_zielordner_an(e, e["zielordner"], self.ORDNER)
        self.assertTrue(neu["sicher"], neu["probleme"])

    def test_tippfehler_allein_reicht_nicht(self):
        # Betatest-Korpus: 'Bayerische Landesbrandversicherung' bekam 'die Bayrische' vorgeschlagen
        self.assertIsNone(auto_pilot.finde_aehnlichen_ordner(
            ["Bayerische Landesbrandversicherung AG"], ["A - B - C\\die Bayrische"]))

    def test_gattungswort_bremst_aber_waehlt_den_neuen_ordner_vor(self):
        # Release-Check v0.9.21: in einer frischen Sammlung bekam 'Versicherungskasse Musterland'
        # 'HKV Versicherung AG' vorgewählt - 'Versicherung' ist nur ein Gattungswort
        ordner = ["F - G - H", "F - G - H\\HKV Versicherung AG", "U - V - W"]
        self.assertEqual(auto_pilot.finde_aehnlichen_ordner(["Versicherungskasse Musterland"], ordner),
                         "F - G - H\\HKV Versicherung AG")
        self.assertIsNone(auto_pilot.finde_aehnlichen_ordner(["Versicherungskasse Musterland"], ordner,
                                                             ohne_gattungswoerter=True))
        # Steckt der Name ganz im Ordner, bremst es weiter, aber der neue Ordner ist vorgewählt
        ordner = ["F - G - H", "F - G - H\\HKV Versicherung AG", "U - V - W"]
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Versicherung", ordnername="Versicherung"),
                                         ordner)
        self.assertFalse(e["sicher"])
        self.assertTrue(e["ordner_neu"])
        self.assertEqual(e["zielordner"], "U - V - W\\Versicherung")
        self.assertTrue(any(p.startswith("Ähnlicher Ordner vorhanden: 'F - G - H\\HKV Versicherung AG'")
                            for p in e["probleme"]), e["probleme"])
        # Zwei verschiedene Namen mit nur dem Gattungswort gemeinsam: neuer Ordner ohne Rückfrage
        e = auto_pilot.baue_entscheidung(
            "dok.pdf", _ki_antwort(absender="Versicherungskasse Musterland", ordnername="Versicherungskasse Musterland"),
            ordner)
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], "U - V - W\\Versicherungskasse Musterland")

    def test_herkunftswort_waehlt_nicht_vor(self):
        # Nachtlauf 28.10.2026: Zensus-Briefe bekamen die Landesbrandversicherung vorgewählt
        ordner = ["A - B - C", "A - B - C\\Bayerische Landesbrandversicherung"]
        self.assertIsNone(auto_pilot.finde_aehnlichen_ordner(["Bayerisches Landesamt für Statistik"], ordner,
                                                             ohne_gattungswoerter=True))
        # Klammerzusatz ist Beschreibung, kein Name
        kaminkehrer = ["K - L - M", "K - L - M\\Kehrmann, Fritz (Kaminkehrer)"]
        self.assertEqual(auto_pilot.finde_aehnlichen_ordner(["Max Mustermann, Kaminkehrermeister"], kaminkehrer),
                         "K - L - M\\Kehrmann, Fritz (Kaminkehrer)")
        self.assertIsNone(auto_pilot.finde_aehnlichen_ordner(["Max Mustermann, Kaminkehrermeister"], kaminkehrer,
                                                             ohne_gattungswoerter=True))
        # ... ein echtes Unterscheidungswort wählt weiter vor
        self.assertEqual(auto_pilot.finde_aehnlichen_ordner(["Landesbrandversicherung Bayern"], ordner,
                                                            ohne_gattungswoerter=True),
                         "A - B - C\\Bayerische Landesbrandversicherung")

    def test_ort_des_dokuments_waehlt_nicht_vor(self):
        # Rest von FALLSTRICKE #83: in einer frischen Sammlung bekam jeder '… Musterstadt' den
        # ersten Musterstadt-Ordner vorgewählt, solange der Ort erst in EINEM Ordner stand
        ordner = ["A - B - C", "A - B - C\\Bürgerbüro Musterstadt", "L - M - N"]
        e = auto_pilot.baue_entscheidung(
            "dok.pdf", _ki_antwort(absender="Musterstadt", ordnername="Musterstadt", ort="12345 Musterstadt"), ordner)
        self.assertFalse(e["sicher"])   # die Bremse bleibt
        self.assertTrue(e["ordner_neu"])
        self.assertEqual(e["zielordner"], "L - M - N\\Musterstadt")
        # ohne Ortsangabe der KI bleibt es bei der Vorwahl, ein echtes Namenswort wählt weiter vor
        e = auto_pilot.baue_entscheidung(
            "dok.pdf", _ki_antwort(absender="Musterstadt", ordnername="Musterstadt"), ordner)
        self.assertEqual(e["zielordner"], "A - B - C\\Bürgerbüro Musterstadt")
        self.assertEqual(auto_pilot.finde_aehnlichen_ordner(
            ["Bürgerbüro der Stadt"], ordner, ohne_gattungswoerter=True, ortswoerter={"musterstadt"}),
            "A - B - C\\Bürgerbüro Musterstadt")

    def test_gemerkte_orte_waehlen_nicht_vor(self):
        # Peter 29.10.2026: Orte, die die KI in früheren Dokumenten des Laufs gelesen hat, zählen
        # ebenfalls nicht - auch wenn dieses Dokument selbst keinen Ort nennt
        ordner = ["A - B - C", "A - B - C\\Bürgerbüro Musterstadt", "L - M - N"]
        orte = set()
        auto_pilot.merke_orte(orte, {"ki_antwort": _ki_antwort(ort="12345 Musterstadt")})
        auto_pilot.merke_orte(orte, {"ki_antwort": _ki_antwort(ort="Au")})   # zu kurz, zählt nie
        auto_pilot.merke_orte(orte, None)                                    # Lesefehler
        self.assertEqual(orte, {"musterstadt"})
        e = auto_pilot.baue_entscheidung(
            "dok.pdf", _ki_antwort(absender="Musterstadt", ordnername="Musterstadt"), ordner, orte=orte)
        self.assertFalse(e["sicher"])
        self.assertEqual(e["zielordner"], "L - M - N\\Musterstadt")
        # über die Stapel-Bausteine gereicht
        gelesen = {"pdf_path": "dok.pdf", "schreibschutz": None, "png": b"x",
                   "ki_antwort": _ki_antwort(absender="Musterstadt", ordnername="Musterstadt")}
        e = auto_pilot.entscheide_im_stapel(gelesen, ordner, "http://x", orte=orte)
        self.assertEqual(e["zielordner"], "L - M - N\\Musterstadt")


class TestZweitmeinungOrdnerwahl(unittest.TestCase):
    """
    Modell-Prüfstand 27.10.2026: ein Entscheidungsmodell (clef-flash) bewertet jeden Ordner;
    deutlicher Widerspruch sperrt eine sichere Ablage, große Sicherheit klärt einen Fall,
    der nur an der Ordnerwahl hing. Die KI schlägt vor, der Code entscheidet.
    """

    ORDNER = ["A - B - C", "A - B - C\\Gentilia", "S - T - U", "S - T - U\\Stadtwerke", "[0-9]", "_Anderes"]

    def _sicher(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(), self.ORDNER)
        self.assertTrue(e["sicher"])
        self.assertEqual(e["zielordner"], "A - B - C\\Gentilia")
        return e

    def _nur_ordner_unsicher(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="", ordnername="KM"), self.ORDNER)
        self.assertFalse(e["sicher"])
        self.assertTrue(all(p.startswith(auto_pilot._ORDNER_PROBLEM_PRAEFIXE) for p in e["probleme"]))
        return e

    def test_buchstabengruppen_sind_keine_kandidaten(self):
        self.assertEqual(auto_pilot.ordner_fuer_zweitmeinung(self.ORDNER),
                         ["A - B - C\\Gentilia", "S - T - U\\Stadtwerke", "_Anderes"])

    def test_deutlicher_widerspruch_sperrt_die_sichere_ablage(self):
        neu = auto_pilot.wende_zweitmeinung_an(
            self._sicher(), [("S - T - U\\Stadtwerke", 0.91), ("A - B - C\\Gentilia", 0.3)], self.ORDNER)
        self.assertFalse(neu["sicher"])
        self.assertEqual(neu["neuer_dateiname"], "")
        # Der Ordner der Logik bleibt vorgewählt, der Vorschlag der KI steht im Hinweis
        self.assertEqual(neu["zielordner"], "A - B - C\\Gentilia")
        self.assertIn("S - T - U\\Stadtwerke", neu["probleme"][-1])

    def test_zustimmung_oder_schwacher_widerspruch_aendert_nichts(self):
        e = self._sicher()
        self.assertIs(auto_pilot.wende_zweitmeinung_an(e, [("A - B - C\\Gentilia", 0.99)], self.ORDNER), e)
        self.assertIs(auto_pilot.wende_zweitmeinung_an(e, [("S - T - U\\Stadtwerke", 0.7)], self.ORDNER), e)
        self.assertIs(auto_pilot.wende_zweitmeinung_an(e, [], self.ORDNER), e)

    def test_zielordner_klick_raeumt_den_widerspruch_weg(self):
        gesperrt = auto_pilot.wende_zweitmeinung_an(
            self._sicher(), [("S - T - U\\Stadtwerke", 0.95), ("A - B - C\\Gentilia", 0.1)], self.ORDNER)
        bestaetigt = auto_pilot.wende_zielordner_an(gesperrt, gesperrt["zielordner"], self.ORDNER)
        self.assertTrue(bestaetigt["sicher"])

    def test_sehr_sichere_ki_klaert_einen_reinen_ordnerfall(self):
        neu = auto_pilot.wende_zweitmeinung_an(
            self._nur_ordner_unsicher(), [("S - T - U\\Stadtwerke", 0.97), ("_Anderes", 0.5)], self.ORDNER)
        self.assertTrue(neu["sicher"])
        self.assertEqual(neu["zielordner"], "S - T - U\\Stadtwerke")
        self.assertFalse(neu["ordner_neu"])
        self.assertEqual(neu["ordner_hinweis"], auto_pilot.ZWEITMEINUNG_HINWEIS)
        self.assertFalse(neu["ordner_per_alias"])
        self.assertTrue(neu["neuer_dateiname"])

    def test_ohne_klaren_abstand_oder_unter_der_schwelle_bleibt_es_unsicher(self):
        e = self._nur_ordner_unsicher()
        self.assertIs(auto_pilot.wende_zweitmeinung_an(
            e, [("S - T - U\\Stadtwerke", 0.97), ("_Anderes", 0.9)], self.ORDNER), e)
        self.assertIs(auto_pilot.wende_zweitmeinung_an(
            e, [("S - T - U\\Stadtwerke", 0.9), ("_Anderes", 0.1)], self.ORDNER), e)

    def test_andere_probleme_bleiben_bestehen(self):
        # Ohne Datum gibt es keinen Dateinamen - daran ändert auch der richtige Ordner nichts
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="", ordnername="KM", datum=""), self.ORDNER)
        neu = auto_pilot.wende_zweitmeinung_an(e, [("S - T - U\\Stadtwerke", 0.99), ("_Anderes", 0.1)], self.ORDNER)
        self.assertEqual(neu["zielordner"], "S - T - U\\Stadtwerke")
        self.assertFalse(neu["sicher"])
        e_nur_datum = dict(self._sicher(), sicher=False, probleme=[auto_pilot._PROBLEM_KEIN_DATUM])
        self.assertIs(auto_pilot.wende_zweitmeinung_an(
            e_nur_datum, [("S - T - U\\Stadtwerke", 0.99), ("_Anderes", 0.1)], self.ORDNER), e_nur_datum)

    def test_alias_ordner_bleibt_unberuehrt(self):
        e = dict(self._sicher(), ordner_per_alias=True)
        self.assertIs(auto_pilot.wende_zweitmeinung_an(e, [("S - T - U\\Stadtwerke", 0.99)], self.ORDNER), e)

    def test_analysiere_dokument_holt_die_zweitmeinung_nur_mit_modell(self):
        from unittest.mock import patch
        with patch("auto_pilot.PDFHandler.get_write_protection", return_value=None), \
                patch("auto_pilot.PDFHandler.render_page_png", return_value=b"png"), \
                patch("ollama_client.suggest_filing", return_value=_ki_antwort()), \
                patch("ollama_client.waehle_ordner",
                      return_value=[("S - T - U\\Stadtwerke", 0.9), ("A - B - C\\Gentilia", 0.1)]) as wahl:
            ohne = auto_pilot.analysiere_dokument("dok.pdf", [], self.ORDNER, "http://x", "m")
            mit = auto_pilot.analysiere_dokument("dok.pdf", [], self.ORDNER, "http://x", "m",
                                                 entscheidungsmodell="clef-flash:9b")
        self.assertTrue(ohne["sicher"])
        self.assertFalse(mit["sicher"])
        wahl.assert_called_once()
        self.assertEqual(wahl.call_args.args[1], auto_pilot.ordner_fuer_zweitmeinung(self.ORDNER))
        self.assertEqual(wahl.call_args.kwargs["model"], "clef-flash:9b")

    def test_fehler_der_zweitmeinung_laesst_die_entscheidung_stehen(self):
        from unittest.mock import patch
        with patch("auto_pilot.PDFHandler.get_write_protection", return_value=None), \
                patch("auto_pilot.PDFHandler.render_page_png", return_value=b"png"), \
                patch("ollama_client.suggest_filing", return_value=_ki_antwort()), \
                patch("ollama_client.waehle_ordner", side_effect=OSError("HTTP 404")):
            e = auto_pilot.analysiere_dokument("dok.pdf", [], self.ORDNER, "http://x", "m",
                                               entscheidungsmodell="clef-flash:9b")
        self.assertTrue(e["sicher"])
        self.assertIn("404", e["zweitmeinung_fehler"])

    def test_ohne_ordnerproblem_wird_nicht_gefragt(self):
        # Unsicher nur wegen des Datums: weder Sperre noch Klärung möglich - Modellwechsel sparen
        from unittest.mock import patch
        with patch("auto_pilot.PDFHandler.get_write_protection", return_value=None), \
                patch("auto_pilot.PDFHandler.render_page_png", return_value=b"png"), \
                patch("ollama_client.suggest_filing", return_value=_ki_antwort(datum="")), \
                patch("ollama_client.waehle_ordner") as wahl:
            auto_pilot.analysiere_dokument("dok.pdf", [], self.ORDNER, "http://x", "m",
                                           entscheidungsmodell="clef-flash:9b")
        wahl.assert_not_called()

    def test_stapel_bausteine_nutzen_die_vorab_geholte_rangliste(self):
        # Stapelbetrieb je Modell: lies_dokument (Lesemodell) und hole_zweitmeinung (Entscheidungsmodell)
        # laufen getrennt; entscheide_gelesen fragt dann nicht noch einmal
        from unittest.mock import patch
        with patch("auto_pilot.PDFHandler.get_write_protection", return_value=None), \
                patch("auto_pilot.PDFHandler.render_page_png", return_value=b"png"), \
                patch("ollama_client.suggest_filing", return_value=_ki_antwort()), \
                patch("ollama_client.waehle_ordner",
                      return_value=[("S - T - U\\Stadtwerke", 0.9), ("A - B - C\\Gentilia", 0.1)]) as wahl:
            gelesen = auto_pilot.lies_dokument("dok.pdf", [], "http://x", "m")
            rangliste = auto_pilot.hole_zweitmeinung(gelesen, self.ORDNER, "http://x", "clef-flash:9b")
            e = auto_pilot.entscheide_gelesen(gelesen, self.ORDNER, "http://x",
                                              entscheidungsmodell="clef-flash:9b", rangliste=rangliste)
        self.assertEqual(wahl.call_count, 1)
        self.assertFalse(e["sicher"])   # wie analysiere_dokument mit Zweitmeinung (Test oben)

    def test_stapel_fehler_der_zweitmeinung_kommt_als_exception(self):
        from unittest.mock import patch
        with patch("auto_pilot.PDFHandler.get_write_protection", return_value=None), \
                patch("auto_pilot.PDFHandler.render_page_png", return_value=b"png"), \
                patch("ollama_client.suggest_filing", return_value=_ki_antwort()), \
                patch("ollama_client.waehle_ordner") as wahl:
            gelesen = auto_pilot.lies_dokument("dok.pdf", [], "http://x", "m")
            e = auto_pilot.entscheide_gelesen(gelesen, self.ORDNER, "http://x", entscheidungsmodell="clef-flash:9b",
                                              rangliste=OSError("HTTP 404"))
        wahl.assert_not_called()
        self.assertTrue(e["sicher"])
        self.assertIn("404", e["zweitmeinung_fehler"])

    def test_zweitmeinungen_fuer_stapel_am_stueck(self):
        """Phase 2 als gemeinsamer Baustein (Vollautomatik + Ablage-Vorschau, 28.10.2026)."""
        with patch("auto_pilot.PDFHandler.get_write_protection", return_value=None), \
                patch("auto_pilot.PDFHandler.render_page_png", return_value=b"png"), \
                patch("ollama_client.suggest_filing", return_value=_ki_antwort()), \
                patch("ollama_client.waehle_ordner",
                      side_effect=[[("A - B - C\\Gentilia", 0.9)], OSError("weg")]) as wahl:
            stapel = [auto_pilot.lies_dokument(f"dok{i}.pdf", [], "http://x", "m") for i in range(2)]
            abgerufen = []
            ranglisten = auto_pilot.zweitmeinungen_fuer_stapel(stapel, self.ORDNER, "http://x", "clef-flash:9b",
                                                               vor_abruf=lambda g: abgerufen.append(g["pdf_path"]))
        self.assertEqual(wahl.call_count, 2)
        self.assertEqual(abgerufen, ["dok0.pdf", "dok1.pdf"])
        self.assertEqual(ranglisten["dok0.pdf"], [("A - B - C\\Gentilia", 0.9)])
        self.assertIsInstance(ranglisten["dok1.pdf"], OSError)
        self.assertEqual(auto_pilot.zweitmeinungen_fuer_stapel(stapel, self.ORDNER, "http://x", ""), {})
        self.assertEqual(auto_pilot.zweitmeinungen_fuer_stapel(stapel, self.ORDNER, "http://x", "clef",
                                                               abbrechen=lambda: True), {})

    def test_entscheide_im_stapel_holt_veraltete_zweitmeinung_neu(self):
        """Neuer Ordner seit Phase 2 und das Dokument will wieder einen neuen: mit aktueller Liste neu fragen."""
        gelesen = {"pdf_path": "dok.pdf", "png": b"png", "schreibschutz": None, "ki_antwort": {}}
        aufrufe = []

        def entscheide(g, ordner, url, **k):
            aufrufe.append(k.get("rangliste", "ohne"))
            return {"ordner_neu": True, "sicher": True}
        with patch("auto_pilot.entscheide_gelesen", side_effect=entscheide):
            auto_pilot.entscheide_im_stapel(gelesen, ["A", "B"], "http://x", "clef", rangliste=["alt"], ordner_stand=1)
            self.assertEqual(aufrufe, ["ohne", None])      # Vorab-Prüfung, dann ohne alte Rangliste
            aufrufe.clear()
            auto_pilot.entscheide_im_stapel(gelesen, ["A", "B"], "http://x", "clef", rangliste=["alt"], ordner_stand=2)
            self.assertEqual(aufrufe, [["alt"]])           # keine neuen Ordner -> Rangliste bleibt

    def test_braucht_zweitmeinung(self):
        self.assertTrue(auto_pilot.braucht_zweitmeinung(self._sicher()))
        self.assertFalse(auto_pilot.braucht_zweitmeinung(dict(self._sicher(), ordner_gedaechtnis=3)))
        self.assertFalse(auto_pilot.braucht_zweitmeinung(dict(self._sicher(), ordner_per_alias=True)))
        self.assertFalse(auto_pilot.braucht_zweitmeinung(
            dict(self._sicher(), sicher=False, probleme=["kein plausibles Dokumentdatum erkannt"])))

    def test_nicht_darstellbare_seite_ohne_ki_aufruf(self):
        from unittest.mock import patch
        with patch("auto_pilot.PDFHandler.get_write_protection", return_value=None), \
                patch("auto_pilot.PDFHandler.render_page_png", return_value=None), \
                patch("ollama_client.suggest_filing") as lesen:
            gelesen = auto_pilot.lies_dokument("dok.pdf", [], "http://x", "m")
            e = auto_pilot.entscheide_gelesen(gelesen, self.ORDNER, "http://x")
        lesen.assert_not_called()
        self.assertFalse(e["sicher"])
        self.assertIn("nicht darstellbar", e["probleme"][0])


class TestTagWildwuchsTeil3(unittest.TestCase):
    """Betatest 27.10.2026: ein Objekt je Tag, Prüfung neuer Sach-Tags, Warteliste als Schreibweise."""

    OBJ = ["Personen", "Objekte & Adressen"]

    def test_sammelangabe_wird_zu_einzelobjekten(self):
        self.assertEqual(auto_pilot.teile_objekte("Zum alten Fass 1 u. 3"),
                         ["Zum alten Fass 1", "Zum alten Fass 3"])
        self.assertEqual(auto_pilot.teile_objekte("Zum Alten Fass 1+3"),
                         ["Zum Alten Fass 1", "Zum Alten Fass 3"])
        self.assertEqual(auto_pilot.teile_objekte("Weidenstr. 8 Whg 2 and 4"),
                         ["Weidenstr. 8 Whg 2", "Weidenstr. 8 Whg 4"])
        self.assertEqual(auto_pilot.teile_objekte("Zum alten Fass 1 und 3"),
                         ["Zum alten Fass 1", "Zum alten Fass 3"])
        self.assertEqual(auto_pilot.teile_objekte("Musterstadt / Musterheim"), ["Musterstadt", "Musterheim"])
        # eine einzelne Adresse bleibt, wie sie ist
        self.assertEqual(auto_pilot.teile_objekte("Weidenstr. 8 Whg 2"), ["Weidenstr. 8 Whg 2"])

    def test_nr_ohne_leerzeichen_ist_dieselbe_adresse(self):
        self.assertEqual(auto_pilot.normiere_objekt("Zum Alten Fass Nr1"),
                         auto_pilot.normiere_objekt("Zum alten Faß 1"))

    def test_bruchstuecke_sind_keine_objekte(self):
        for text in ("Nr. 3", "75m", "14m x 1", "R. R."):
            self.assertFalse(auto_pilot.ist_objektbezeichnung(text), text)
        for text in ("Weidenstr. 8", "MUS-HM 738", "Musterheim"):
            self.assertTrue(auto_pilot.ist_objektbezeichnung(text), text)
        tags, _ = auto_pilot.tags_mit_empfaenger({"tags": ["Rechnung"], "objekt": "Nr. 3"}, kategorien=self.OBJ)
        self.assertEqual(tags, ["Rechnung"])

    def test_sammeltag_aus_dem_katalog_wird_zerlegt(self):
        """Steht die Sammelform im Katalog, schlägt die KI sie ohne Kategorie vor - trotzdem zerlegen."""
        katalog = ["Rechnung", "Zum alten Fass 1 u. 3", "Zum alten Fass 1", "Musterstadt / Musterheim", "Musterstadt",
                   "Musterheim"]
        tags, _ = auto_pilot.tags_mit_empfaenger(
            {"tags": ["Rechnung", "Zum alten Fass 1 u. 3", "Musterstadt / Musterheim"]},
            known_tags=katalog, kategorien=self.OBJ)
        self.assertEqual(tags, ["Rechnung", "Musterstadt", "Musterheim", "Zum alten Fass 1", "Zum alten Fass 3"])

    def test_bekannte_adresse_ohne_kategorie_rastet_als_objekt_ein(self):
        """Test T13.9: 'Zum Alten Fass Nr.1' kam als Sach-Tag und fiel der Ziffern-Regel zum Opfer."""
        katalog = ["Mietvertrag", "Zum alten Fass 1"]
        tags, _ = auto_pilot.tags_mit_empfaenger({"tags": ["Mietvertrag", "Zum Alten Fass Nr.1"]},
                                                 known_tags=katalog, kategorien=self.OBJ)
        self.assertIn("Zum alten Fass 1", tags)
        # unbekannte Ziffern-Tags ohne Kategorie bleiben ein Fall für die Prüfung neuer Tags
        tags, _ = auto_pilot.tags_mit_empfaenger({"tags": ["PLG7"]}, known_tags=katalog, kategorien=self.OBJ)
        self.assertEqual(tags, ["PLG7"])

    def test_ort_mit_schraegstrich_wird_zerlegt(self):
        tags, _ = auto_pilot.tags_mit_empfaenger(
            {"tags": [], "objekt": "Weidenstr. 8", "ort": "Musterstadt / Musterheim"}, kategorien=self.OBJ)
        self.assertEqual(tags, ["Weidenstr. 8", "Musterstadt", "Musterheim"])

    def test_gruende_gegen_neue_tags(self):
        faelle = {
            "TV": "zu kurz",
            "3 TAN: 309876": "enthält Ziffern",
            "abzubuchender Gesamtbeitrag in Euro": "zu lang",
            "abzubuchender Gesamtbeitrag": "kein Substantiv",
            "Sehr geehrter Kunde": "Anrede",
            "Heating and Water": "englisch",
            "AFP LPD PDF": "Dateiformat",
        }
        for tag, grund in faelle.items():
            self.assertEqual(auto_pilot.grund_gegen_neues_tag(tag), grund, tag)
        self.assertEqual(auto_pilot.grund_gegen_neues_tag("Finanzamt Musterstadt", ("Finanzamt Musterstadt",)), "Absender")
        for tag in ("Gebührenbescheid", "Gebäude- und Wohnungszählung", "Abfallentsorgung"):
            self.assertEqual(auto_pilot.grund_gegen_neues_tag(tag), "", tag)

    def test_pruefung_nur_fuer_neue_sachtags(self):
        tags = ["Rechnung", "TV", "Weidenstr. 8", "Max Mustermann", "Sehr geehrter Kunde"]
        kategorien = {"Weidenstr. 8": "Objekte & Adressen", "Max Mustermann": "Personen"}
        behalten, verworfen = auto_pilot.ohne_unbrauchbare_neue_tags(tags, kategorien, ["Rechnung", "TV"])
        self.assertEqual(behalten, ["Rechnung", "TV", "Weidenstr. 8", "Max Mustermann"])
        self.assertEqual(verworfen, [("Sehr geehrter Kunde", "Anrede")])
        # ohne Katalog-Information bleibt alles
        self.assertEqual(auto_pilot.ohne_unbrauchbare_neue_tags(tags, kategorien, None), (tags, []))


class TestAblageGedaechtnis(unittest.TestCase):
    """Ablage-Gedächtnis (27.10.2026): Rangfolge Alias > Gedächtnis > Namensregeln, keine Zweitmeinung."""

    LBV = "Bayerische Landesbrandversicherung AG"
    VKB = "S - Z\\Versicherungskasse Musterland"
    ORDNER = VORHANDENE_ORDNER + ["S - Z", VKB]

    def _gedaechtnis(self, ordner=None, stimmen=2):
        g = ablage_gedaechtnis.Gedaechtnis()
        for _ in range(stimmen):
            g.stimme(self.LBV, ordner or self.VKB)
        return g

    def test_gedaechtnis_schlaegt_namensregel(self):
        e = auto_pilot.baue_entscheidung("x.pdf", _ki_antwort(absender=self.LBV), self.ORDNER,
                                         gedaechtnis=self._gedaechtnis())
        self.assertEqual(e["zielordner"], self.VKB)
        self.assertEqual(e["ordner_gedaechtnis"], 2)
        self.assertEqual(e["ordner_hinweis"], "Gedächtnis, 2 Dokumente")
        self.assertFalse(e["ordner_neu"])
        self.assertFalse(e["ordner_per_alias"])
        self.assertTrue(e["sicher"], e["probleme"])

    def test_ohne_gedaechtnis_wie_bisher(self):
        e = auto_pilot.baue_entscheidung("x.pdf", _ki_antwort(absender=self.LBV), self.ORDNER,
                                         gedaechtnis=self._gedaechtnis(stimmen=1))
        self.assertEqual(e["ordner_gedaechtnis"], 0)
        self.assertNotEqual(e["zielordner"], self.VKB)

    def test_alias_geht_vor(self):
        e = auto_pilot.baue_entscheidung("x.pdf", _ki_antwort(absender=self.LBV), self.ORDNER,
                                         aliase={"Landesbrandversicherung": "Stadtwerke"},
                                         gedaechtnis=self._gedaechtnis())
        self.assertEqual(e["zielordner"], "Stadtwerke")
        self.assertTrue(e["ordner_per_alias"])
        self.assertEqual(e["ordner_gedaechtnis"], 0)

    def test_verschwundener_ordner_zaehlt_nicht(self):
        e = auto_pilot.baue_entscheidung("x.pdf", _ki_antwort(absender=self.LBV), self.ORDNER,
                                         gedaechtnis=self._gedaechtnis(ordner="S - Z\\Weg"))
        self.assertEqual(e["ordner_gedaechtnis"], 0)

    def test_zweitmeinung_laesst_gedaechtnis_stehen(self):
        e = auto_pilot.baue_entscheidung("x.pdf", _ki_antwort(absender=self.LBV), self.ORDNER,
                                         gedaechtnis=self._gedaechtnis())
        self.assertIs(auto_pilot.wende_zweitmeinung_an(e, [("Stadtwerke", 0.99)], self.ORDNER), e)

    def test_zielordner_klick_hebt_gedaechtnis_auf(self):
        e = auto_pilot.baue_entscheidung("x.pdf", _ki_antwort(absender=self.LBV), self.ORDNER,
                                         gedaechtnis=self._gedaechtnis())
        neu = auto_pilot.wende_zielordner_an(e, "Stadtwerke", self.ORDNER)
        self.assertEqual(neu["ordner_gedaechtnis"], 0)
        self.assertTrue(neu["ordner_per_alias"])


class TestAbsenderWirdEingebrannt(TestFuehreEntscheidungAus):
    """Die Ablage schreibt den gelesenen Absender als KID_ABSENDER ins PDF - die Stimme fürs Gedächtnis."""

    def test_sicher_schreibt_absender(self):
        e = auto_pilot.baue_entscheidung(self.pdf_path, _ki_antwort(absender="Gentilia Deutschland Versicherung AG"),
                                         VORHANDENE_ORDNER)
        ergebnis = auto_pilot.fuehre_entscheidung_aus(e, self.master, self._verschieben)
        self.assertTrue(ergebnis["erfolg"], ergebnis["fehler"])
        self.assertEqual(PDFHandler.get_metadata(ergebnis["neuer_pfad"])["KID_Absender"],
                         "Gentilia Deutschland Versicherung AG")

    def test_unsicher_schreibt_nichts(self):
        e = auto_pilot.baue_entscheidung(self.pdf_path, _ki_antwort(absender="Gentilia", title=""), VORHANDENE_ORDNER)
        ergebnis = auto_pilot.fuehre_entscheidung_aus(e, self.master, self._verschieben)
        self.assertEqual(PDFHandler.get_metadata(ergebnis["neuer_pfad"])["KID_Absender"], "")
