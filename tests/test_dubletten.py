"""Tests für die Dubletten-Erkennung (dubletten.py) und den Bild-Fingerabdruck in pdf_handler."""

import os
import shutil
import tempfile
import unittest

import fitz

import dubletten
from pdf_handler import PDFHandler

BRIEF = ("Stadtwerke Musterstadt Jahresabrechnung Strom Wasser Rechnungsdatum 12.03.2024 "
         "Verbrauch Strom 2370 kWh Wasser 85 Kubikmeter Herrn Hermann Mustermann Weidenstr 8 Musterstadt "
         "Zahlbar bis 26.03.2024 Kundennummer 1100378668 Vertragskonto 220100511903")


def _info(pfad, text=BRIEF, seiten=1, bildhash=0, meta=None, hash_="", datum="2024-03-12"):
    """Test-Info; Datum als Metadatum (leerer String = unbekannt)."""
    meta = dict(meta or {})
    if datum:
        meta.setdefault("KID_DokumentenDatum", datum)
    return {"pfad": pfad, "seiten": seiten, "text": text, "qualitaet": 90, "bildhash": bildhash,
            "hash": hash_, "meta": meta}


class TestAehnlichkeit(unittest.TestCase):
    def test_gleicher_text_mit_ocr_fehlern_ist_aehnlich(self):
        gestoert = BRIEF.replace("Rechnungsdatum", "Rechnungsdaturn").replace("Verbrauch", "Verbrauc h")
        self.assertGreaterEqual(dubletten.text_aehnlichkeit(BRIEF, gestoert), dubletten.TEXT_GLEICHES_DATUM)

    def test_verschiedene_briefe_sind_nicht_aehnlich(self):
        anderer = BRIEF.replace("2024", "2021").replace("Strom", "Gas").replace("2370", "1810").replace("Jahresabrechnung", "Mahnung")
        self.assertLess(dubletten.text_aehnlichkeit(BRIEF, anderer), dubletten.TEXT_DATUM_UNBEKANNT)

    def test_dokument_datum_aus_meta_sonst_dateiname(self):
        self.assertEqual(dubletten.dokument_datum(_info("x.pdf", datum="2020-02-03")), "2020-02-03")
        self.assertEqual(dubletten.dokument_datum(_info("20200203_x.pdf", datum="")), "2020-02-03")
        self.assertEqual(dubletten.dokument_datum(_info("x.pdf", datum="")), "")

    def test_zu_wenig_text_ist_nie_aehnlich(self):
        self.assertEqual(dubletten.text_aehnlichkeit("Seite 1", "Seite 1"), 0.0)

    def test_hamming(self):
        self.assertEqual(dubletten.hamming(0b1011, 0b0001), 2)


class TestBewerteUndGruppiere(unittest.TestCase):
    def test_identische_datei_gewinnt_vor_text(self):
        a, b = _info("a.pdf", hash_="x"), _info("b.pdf", hash_="x")
        self.assertEqual(dubletten.bewerte_paar(a, b), "identische Datei")

    def test_verschiedene_seitenzahl_ist_keine_dublette(self):
        self.assertIsNone(dubletten.bewerte_paar(_info("a.pdf", seiten=1), _info("b.pdf", seiten=2)))

    def test_bildhash_faengt_ocr_muell_ab_nur_bei_gleichem_datum(self):
        # Beide ohne brauchbare Textebene: nur ein SEHR naher Fingerabdruck UND gleiches Datum zählt
        a = _info("a.pdf", text="x y z", bildhash=0b1111_0000)
        b = _info("b.pdf", text="q r s", bildhash=0b1111_0001)
        self.assertIn("keine Textebene", dubletten.bewerte_paar(a, b))
        self.assertIsNone(dubletten.bewerte_paar(a, _info("b2.pdf", text="q r s", bildhash=0b1111_0001, datum="")))
        c = _info("c.pdf", text="q r s", bildhash=0xFFFF_FFFF_0000_0000)
        self.assertIsNone(dubletten.bewerte_paar(a, c))
        weit = _info("w.pdf", text="q r s", bildhash=0b1111_0000 ^ 0b111)  # 3 Bit: zu unsicher ohne Text
        self.assertIsNone(dubletten.bewerte_paar(a, weit))

    def test_gleiche_vorlage_anderes_datum_ist_keine_dublette(self):
        """Live-Fund: Jahresrechnungen derselben Vorlage - Bild gleich, Text zu ~70 % gleich, Datum anders."""
        a = _info("20240312_r.pdf", text=BRIEF, bildhash=0b1, datum="2024-03-12")
        anderer = BRIEF.replace("2024", "2023").replace("2370", "1810").replace("85", "91")
        b = _info("20230314_r.pdf", text=anderer, bildhash=0b11, datum="2023-03-14")
        self.assertGreater(dubletten.text_aehnlichkeit(BRIEF, anderer), 0.6)
        self.assertIsNone(dubletten.bewerte_paar(a, b))
        # Dieselben Texte mit GLEICHEM Datum (zweiter Scan mit OCR-Abweichungen) -> Dublette
        c = _info("20240312_r_1.pdf", text=anderer, bildhash=0b11, datum="2024-03-12")
        self.assertIn("gleiches Datum", dubletten.bewerte_paar(a, c))

    def test_ohne_datum_nur_sehr_aehnlicher_text(self):
        a = _info("a.pdf", text=BRIEF, bildhash=0b1, datum="")
        leicht = _info("b.pdf", text=BRIEF.replace("Rechnungsdatum", "Rechnungsdaturn"), bildhash=0b11, datum="")
        self.assertIn("Datum unbekannt", dubletten.bewerte_paar(a, leicht))
        # Ohne Bild-Bestätigung reicht ein Text von ~80 % nicht (Fingerabdruck weit weg)
        staerker = _info("c.pdf", text=BRIEF.replace("Rechnungsdatum", "X").replace("Verbrauch", "Y").replace("Kubikmeter", "Z").replace("Zahlbar", "W"), bildhash=0xFFFF_FFFF_0000_0000, datum="")
        self.assertIsNone(dubletten.bewerte_paar(a, staerker))
        # Mit gleichem Bild darf der Text schlechter sein - aber nicht beliebig
        mit_bild = dict(staerker, bildhash=0b11)
        self.assertIn("Seite 1 sieht gleich aus", dubletten.bewerte_paar(a, mit_bild))

    def test_gruppen_werden_transitiv_zusammengefasst(self):
        infos = [_info("a.pdf", hash_="1"), _info("b.pdf", hash_="1"),
                 _info("c.pdf", text="ganz anderer Text " * 5, hash_="2", bildhash=0xFFFF_FFFF_0000_0000),
                 _info("d.pdf", text=BRIEF.replace("Strom", "Strorn"), hash_="3", bildhash=0)]
        gruppen = dubletten.finde_dubletten(infos)
        self.assertEqual(len(gruppen), 1)
        mitglieder, grund, sicher = gruppen[0]
        self.assertEqual(sorted(i["pfad"] for i in mitglieder), ["a.pdf", "b.pdf", "d.pdf"])
        self.assertEqual(grund, "identische Datei")
        self.assertTrue(sicher)

    def test_unterschiede_zeigen_nur_abweichende_woerter_ziffern_zuerst(self):
        """Zwei Rechnungen derselben Vorlage: Rechnungsnummer/Betrag/Anrede stehen vorn, Gemeinsames fehlt."""
        a = "Sehr geehrter Herr Huber Rechnung Nr 4711 Betrag 120 Euro Stadtwerke Musterstadt"
        b = "Sehr geehrte Frau Maier Rechnung Nr 4712 Betrag 120 Euro Stadtwerke Musterstadt"
        nur_a, nur_b = dubletten.unterschiede(a, b)
        self.assertEqual(nur_a, ["4711", "geehrter", "herr", "huber"])
        self.assertEqual(nur_b, ["4712", "frau", "geehrte", "maier"])
        self.assertEqual(dubletten.unterschiede(a, a), ([], []))
        self.assertEqual(len(dubletten.unterschiede(" ".join(f"wort{i}" for i in range(50)), "", max_woerter=5)[0]), 5)

    def test_verschiedene_personen_tags_machen_pruefen(self):
        """Gleicher Serienbrief an beide Ehepartner: fast wortgleich, aber verschiedene Personen-Tags -> nie Papierkorb-Vorschlag."""
        merkmale = {"Personen": ["Hermann Mustermann", "Maria Mustermann"]}
        a = _info("brief_vater.pdf", meta={"keywords": "Rechnung, Hermann Mustermann"})
        b = _info("brief_mutter.pdf", text=BRIEF.replace("Hermann", "Maria"),
                  meta={"keywords": "Rechnung, Maria Mustermann"})
        grund = dubletten.bewerte_paar(a, b, merkmale)
        self.assertTrue(grund and grund.startswith("Prüfen:"), grund)
        self.assertIn("verschiedene Tags aus 'Personen' (hermann mustermann / maria mustermann)", grund)
        self.assertFalse(dubletten.finde_dubletten([a, b], merkmale)[0][2])
        # gleiche Person bzw. ohne Personen-Katalog: weiterhin sicherer Treffer
        c = _info("brief_vater_2.pdf", meta={"keywords": "Rechnung, Hermann Mustermann"})
        self.assertFalse(dubletten.bewerte_paar(a, c, merkmale).startswith("Prüfen:"))
        self.assertFalse(dubletten.bewerte_paar(a, b, None).startswith("Prüfen:"))
        # nur ein Dokument getaggt: das ungetaggte wird über den Seitentext zugeordnet
        # ('Maria Mustermann' steht im Anschriftenfeld) -> ebenfalls Prüfen
        d = _info("brief_ohne_tags.pdf", text=BRIEF.replace("Hermann", "Maria"), meta={"keywords": ""})
        self.assertTrue(dubletten.bewerte_paar(a, d, merkmale).startswith("Prüfen:"))

    def test_personen_erkennung_faellt_auf_seitentext_zurueck(self):
        """Praxistest 30.08.2026: Zensus-Briefe an Hermann und Uta trugen nur '2022, Zensus' als Tags -
        die Namen aus dem Katalog werden dann im Anschriftenfeld (Seitentext) gefunden."""
        merkmale = {"Personen": ["Hermann Mustermann", "Uta Mustermann", "Eis"]}
        a = _info("zensus_hermann.pdf", meta={"keywords": "2022, Zensus"})  # BRIEF enthält 'Hermann Mustermann'
        b = _info("zensus_uta.pdf", text=BRIEF.replace("Hermann", "Uta"), meta={"keywords": "2022, Zensus"})
        grund = dubletten.bewerte_paar(a, b, merkmale)
        self.assertTrue(grund and grund.startswith("Prüfen:"), grund)
        self.assertIn("hermann mustermann / uta mustermann", grund)
        self.assertFalse(dubletten.finde_dubletten([a, b], merkmale)[0][2])
        # zweiter Scan desselben Briefs: gleicher Name im Text -> weiterhin sicherer Treffer
        c = _info("zensus_hermann_2.pdf", text=BRIEF.replace("Kubikmeter", "Kubikrneter"), meta={"keywords": ""})
        self.assertFalse(dubletten.bewerte_paar(a, c, merkmale).startswith("Prüfen:"))
        # Wortgrenzen und Mindestlänge: 'Eis' (3 Zeichen) wird nicht im Text gesucht
        self.assertEqual(dubletten.namen_im_text(_info("x.pdf", text="Eisenbahn und Eis am Stiel"), ["Eis"]), set())
        self.assertEqual(dubletten.namen_im_text(_info("x.pdf", text="Die Prellung von Herrn Prell"), ["Prell"]), {"prell"})
        # Dokument-Tags haben Vorrang vor dem Text (getaggt zählt nur das Tag)
        d = _info("zensus_hermann_3.pdf", meta={"keywords": "2022, Uta Mustermann"})
        self.assertIn("uta mustermann", dubletten.tags_aus(d, merkmale["Personen"]))

    def test_verschiedene_objekt_tags_machen_pruefen_trotz_gleicher_person(self):
        """Gleicher Bescheid für zwei Häuser ('Zum Alten Fass 1' und '3'), beide an denselben Empfänger:
        der gemeinsame Personen-Tag darf den Objekt-Unterschied nicht überdecken."""
        merkmale = {"Personen": ["Hermann Mustermann"],
                    "Objekte & Adressen": ["Zum Alten Fass 1", "Zum Alten Fass 3"]}
        a = _info("bescheid_1.pdf", meta={"keywords": "Grundsteuer, Hermann Mustermann, Zum Alten Fass 1"})
        b = _info("bescheid_3.pdf", meta={"keywords": "Grundsteuer, Hermann Mustermann, Zum Alten Fass 3"})
        grund = dubletten.bewerte_paar(a, b, merkmale)
        self.assertTrue(grund and grund.startswith("Prüfen:"), grund)
        self.assertIn("Objekte & Adressen", grund)
        self.assertIn("zum alten fass 1 / zum alten fass 3", grund)
        # gleiches Objekt -> normale Bewertung (sicherer Treffer)
        c = _info("bescheid_1_kopie.pdf", meta={"keywords": "Grundsteuer, Hermann Mustermann, Zum Alten Fass 1"})
        self.assertFalse(dubletten.bewerte_paar(a, c, merkmale).startswith("Prüfen:"))

    def test_unterschiede_zeigen_hausnummern(self):
        """1-2-stellige Zahlen (Hausnummern) erscheinen in der Unterschiede-Zeile, obwohl die Ähnlichkeit sie ignoriert."""
        self.assertEqual(dubletten.unterschiede("Zum Alten Fass 1", "Zum Alten Fass 3"), (["1"], ["3"]))

    def test_schwache_treffer_sind_pruefen_faelle(self):
        """Gas- und Abwasser-Rechnung vom selben Tag: gleiches Papier, ~65 % Text -> 'Prüfen:', Gruppe unsicher."""
        a = _info("20230115_Gas.pdf", text=BRIEF, bildhash=0b1)
        anderer = BRIEF.replace("Strom", "Abwasser").replace("2370", "410").replace("kWh", "Kubik").replace("Jahresabrechnung", "Gebuehrenbescheid").replace("Wasser", "Kanal")
        b = _info("20230115_Abwasser.pdf", text=anderer, bildhash=0b11)
        grund = dubletten.bewerte_paar(a, b)
        self.assertTrue(grund and grund.startswith("Prüfen:"), grund)
        gruppen = dubletten.finde_dubletten([a, b])
        self.assertEqual(len(gruppen), 1)
        self.assertFalse(gruppen[0][2])
        # Starker Text-Treffer bleibt ohne 'Prüfen:'
        c = _info("20230115_Gas_1.pdf", text=BRIEF.replace("Rechnungsdatum", "Rechnungsdaturn"), bildhash=0b11)
        self.assertFalse(dubletten.bewerte_paar(a, c).startswith("Prüfen:"))
        self.assertTrue(dubletten.finde_dubletten([a, c])[0][2])

    def test_empfehlung_bevorzugt_textqualitaet_dann_metadaten_dann_kurzen_namen(self):
        schlecht = dict(_info("scan_1.pdf"), qualitaet=60)
        gut = dict(_info("scan_1.pdf"), qualitaet=95)
        self.assertIs(dubletten.empfehlung([schlecht, gut]), gut)
        ohne_meta = dict(_info("scan.pdf"), qualitaet=95)
        mit_meta = dict(_info("scan_1.pdf"), qualitaet=94, meta={"title": "Rechnung", "keywords": "", "KID_DokumentenDatum": "2024-03-12"})
        self.assertIs(dubletten.empfehlung([ohne_meta, mit_meta]), mit_meta)
        kurz, lang = _info("scan.pdf"), _info("scan_1.pdf")
        self.assertIs(dubletten.empfehlung([lang, kurz]), kurz)


class TestFingerabdruckEchtePdf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _pdf(self, name, text, versatz=0):
        pfad = os.path.join(self.tmp, name)
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72 + versatz, 100), text, fontsize=14)
        page.draw_rect(fitz.Rect(72, 200, 400, 400), color=(0, 0, 0), fill=(0.3, 0.3, 0.3))
        doc.save(pfad)
        doc.close()
        return pfad

    def test_fingerabdruck_zweier_scans_nah_beieinander_andere_seite_weit_weg(self):
        a = self._pdf("a.pdf", "Stadtwerke Musterstadt Rechnung")
        b = self._pdf("b.pdf", "Stadtwerke Musterstadt Rechnung", versatz=2)  # leicht verschoben wie ein zweiter Scan
        leer = os.path.join(self.tmp, "leer.pdf")
        doc = fitz.open()
        doc.new_page()
        doc.save(leer)
        doc.close()
        ha, hb, hl = (PDFHandler.get_page_fingerprint(p) for p in (a, b, leer))
        self.assertIsNotNone(ha)
        self.assertLessEqual(dubletten.hamming(ha, hb), dubletten.BILD_SCHWELLE)
        self.assertGreater(dubletten.hamming(ha, hl), dubletten.BILD_SCHWELLE)

    def test_sammle_info_liest_hash_und_qualitaet(self):
        a = self._pdf("a.pdf", BRIEF)
        info = dubletten.sammle_info(a, BRIEF, 1, 5, {"title": "T"})
        self.assertEqual(len(info["hash"]), 64)
        self.assertGreater(info["qualitaet"], 0)
        self.assertEqual(info["meta"]["title"], "T")

    def test_kaputte_datei_liefert_none_fingerabdruck(self):
        pfad = os.path.join(self.tmp, "kaputt.pdf")
        with open(pfad, "wb") as f:
            f.write(b"kein pdf")
        self.assertIsNone(PDFHandler.get_page_fingerprint(pfad))


class TestWaehlePartner(unittest.TestCase):
    """Vorschau rechts bei Gruppen mit 3+ Dokumenten (Nutzerfund 12.09.2026)."""

    def setUp(self):
        self.a, self.b, self.c = ({"pfad": "a.pdf"}, {"pfad": "b.pdf"}, {"pfad": "c.pdf"})
        self.gruppe = [self.a, self.b, self.c]

    def test_standard_ist_das_erste_andere(self):
        self.assertIs(dubletten.waehle_partner(self.gruppe, self.a), self.b)
        self.assertIs(dubletten.waehle_partner(self.gruppe, self.b), self.a)
        self.assertIs(dubletten.waehle_partner(self.gruppe, self.c), self.a)

    def test_gewuenschter_partner_gewinnt(self):
        self.assertIs(dubletten.waehle_partner(self.gruppe, self.a, "c.pdf"), self.c)
        # Wunsch = linkes Dokument selbst oder fremd -> Rückfall auf das erste andere
        self.assertIs(dubletten.waehle_partner(self.gruppe, self.c, "c.pdf"), self.a)
        self.assertIs(dubletten.waehle_partner(self.gruppe, self.a, "x.pdf"), self.b)

    def test_ohne_zweites_dokument(self):
        self.assertIsNone(dubletten.waehle_partner([self.a], self.a))


if __name__ == "__main__":
    unittest.main()
