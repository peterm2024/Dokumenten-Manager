"""Tests für die GUI-freien Kerne der Tag-Hygiene (tools/tag_hygiene.py)."""

import os
import shutil
import tempfile
import unittest

import fitz

from pdf_handler import PDFHandler
from tools.tag_hygiene import (entferne_tag_aus_dokumenten, ersetze_synonyme_in_dokumenten, finde_einzelgaenger,
                               plane_sammel_zerlegung, plane_standard_synonyme, plane_synonym_ersetzungen,
                               sammle_tag_vorkommen, standard_synonyme, zerlege_sammel_tags_in_dokumenten,
                               zerlege_tags)


class TestFindeEinzelgaenger(unittest.TestCase):
    def setUp(self):
        self.vorkommen = {
            "Rechnung": ["a.pdf", "b.pdf", "c.pdf"],
            "Aktionspreis": ["a.pdf"],
            "Diagnose": ["a.pdf", "b.pdf"],
            "Weidenstr. 8 Whg 3": ["w.pdf"],
            "Musterstadt": ["a.pdf"],
            "Personen": ["x.pdf"],
        }
        self.katalog = {
            "rechnung": ("Dokumentart", False, False),
            "aktionspreis": ("Neu (KI)", False, False),
            "diagnose": ("Neu (KI)", False, False),
            "weidenstr. 8 whg 3": ("Objekte & Adressen", False, False),
            "musterstadt": ("Objekte & Adressen", True, False),   # kuratierter Eltern-Knoten
            "personen": ("Personen", True, True),             # Struktur-Knoten
        }

    def test_schwelle_und_schutzregeln(self):
        kandidaten = finde_einzelgaenger(self.vorkommen, 2, self.katalog)
        tags = [t for t, _, _ in kandidaten]
        self.assertIn("Aktionspreis", tags)
        self.assertIn("Diagnose", tags)
        self.assertIn("Weidenstr. 8 Whg 3", tags)  # Einzelgänger, aber der MENSCH entscheidet
        self.assertNotIn("Rechnung", tags)         # über der Schwelle
        self.assertNotIn("Musterstadt", tags)           # hat Unter-Tags -> nie anbieten
        self.assertNotIn("Personen", tags)         # Struktur-Knoten -> nie anbieten

    def test_schwelle_eins(self):
        tags = [t for t, _, _ in finde_einzelgaenger(self.vorkommen, 1, self.katalog)]
        self.assertNotIn("Diagnose", tags)
        self.assertIn("Aktionspreis", tags)

    def test_tag_ohne_katalog_eintrag_wird_angeboten(self):
        kandidaten = finde_einzelgaenger({"Verwaist": ["a.pdf"]}, 2, {})
        self.assertEqual(kandidaten, [("Verwaist", "(nicht im Katalog)", ["a.pdf"])])


class TestEntferneTagAusDokumenten(unittest.TestCase):
    def setUp(self):
        self.master = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.master, ignore_errors=True)

    def _erzeuge_pdf(self, rel, titel="Titel", keywords=""):
        pfad = os.path.join(self.master, rel)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        doc = fitz.open()
        doc.new_page()
        doc.set_metadata({"title": titel, "keywords": keywords})
        doc.save(pfad)
        doc.close()
        return pfad

    def test_entfernt_nur_das_eine_tag_und_behaelt_titel(self):
        pfad = self._erzeuge_pdf("Ordner/a.pdf", titel="Mein Titel", keywords="Rechnung, Aktionspreis, Strom")
        geaendert = entferne_tag_aus_dokumenten(self.master, "Aktionspreis", ["Ordner/a.pdf"])
        self.assertEqual(geaendert, 1)
        meta = PDFHandler.get_metadata(pfad)
        self.assertEqual(meta["title"], "Mein Titel")
        self.assertEqual(meta["keywords"], "Rechnung, Strom")

    def test_fehlende_datei_und_fremdes_tag_sind_kein_fehler(self):
        self._erzeuge_pdf("b.pdf", keywords="Rechnung")
        geaendert = entferne_tag_aus_dokumenten(self.master, "Aktionspreis", ["b.pdf", "gibtsnicht.pdf"])
        self.assertEqual(geaendert, 0)

    def test_sammle_tag_vorkommen(self):
        self._erzeuge_pdf("Ordner/a.pdf", keywords="Rechnung, Strom")
        self._erzeuge_pdf("b.pdf", keywords="rechnung")
        vorkommen = sammle_tag_vorkommen(self.master)
        # Groß/Klein fällt zusammen, der zuerst gesehene Text gewinnt
        treffer = {t.lower(): pfade for t, pfade in vorkommen.items()}
        self.assertEqual(len(treffer["rechnung"]), 2)
        self.assertEqual(len(treffer["strom"]), 1)

    # ---- Synonyme im Bestand (08.09.2026) ----
    SYNONYME = {"haftpflichtversicherung": "Haftpflicht", "einkommensteuer": "Steuererklärung"}
    ELTERN = {"haftpflicht": ["Versicherung"], "steuererklärung": ["Finanzen"]}

    def test_plane_synonym_ersetzungen(self):
        vorkommen = {"Haftpflichtversicherung": ["b.pdf", "a.pdf"], "Rechnung": ["a.pdf"], "einkommensteuer": ["c.pdf"]}
        self.assertEqual(plane_synonym_ersetzungen(vorkommen, self.SYNONYME),
                         [("Haftpflichtversicherung", "Haftpflicht", ["a.pdf", "b.pdf"]),
                          ("einkommensteuer", "Steuererklärung", ["c.pdf"])])
        self.assertEqual(plane_synonym_ersetzungen(vorkommen, {}), [])

    def test_ersetze_synonyme_in_dokumenten(self):
        a = self._erzeuge_pdf("Ordner/a.pdf", titel="Beitrag", keywords="Versicherung, Hermann Mustermann, Haftpflichtversicherung")
        b = self._erzeuge_pdf("b.pdf", keywords="Haftpflichtversicherung, Einkommensteuer, Haftpflicht")
        c = self._erzeuge_pdf("c.pdf", keywords="Rechnung")
        geaendert = ersetze_synonyme_in_dokumenten(self.master, ["Ordner/a.pdf", "b.pdf", "b.pdf", "c.pdf", "fehlt.pdf"],
                                                   self.SYNONYME, self.ELTERN)
        self.assertEqual(geaendert, 2)
        self.assertEqual(PDFHandler.get_metadata(a)["title"], "Beitrag")
        self.assertEqual(PDFHandler.get_metadata(a)["keywords"], "Versicherung, Hermann Mustermann, Haftpflicht")
        # Ziel schon vorhanden -> nur einmal; Oberkategorien kommen dazu
        self.assertEqual(PDFHandler.get_metadata(b)["keywords"], "Versicherung, Haftpflicht, Finanzen, Steuererklärung")
        self.assertEqual(PDFHandler.get_metadata(c)["keywords"], "Rechnung")

    def test_gesperrte_datei_wird_gesammelt_gemeldet(self):
        from unittest.mock import patch
        self._erzeuge_pdf("a.pdf", keywords="Haftpflichtversicherung")
        self._erzeuge_pdf("b.pdf", keywords="Aktionspreis")
        fehler = []
        with patch.object(PDFHandler, "save_metadata", return_value=(False, "WinError 32")) as sm:
            n = ersetze_synonyme_in_dokumenten(self.master, ["a.pdf"], self.SYNONYME, fehler=fehler)
            m = entferne_tag_aus_dokumenten(self.master, "Aktionspreis", ["b.pdf"], fehler=fehler)
        self.assertEqual((n, m), (0, 0))
        self.assertEqual(fehler, ["a.pdf", "b.pdf"])
        # nie ein Popup aus der Schleife: immer still
        for aufruf in sm.call_args_list:
            self.assertTrue(aufruf.kwargs.get("still"))


class TestSammelTagsZerlegen(unittest.TestCase):
    """Sammel-Tags im Bestand: ein Objekt je Tag (28.10.2026)."""

    setUp = TestEntferneTagAusDokumenten.setUp
    _erzeuge_pdf = TestEntferneTagAusDokumenten._erzeuge_pdf

    def test_plan_nur_fuer_zerlegbare_tags_mit_ziffern(self):
        vorkommen = {"Zum Alten Fass 1 u. 3": ["a.pdf", "b.pdf"], "Müller und Söhne": ["c.pdf"],
                     "Weidenstr. 8": ["a.pdf"], "Rechnung": ["a.pdf"]}
        self.assertEqual(plane_sammel_zerlegung(vorkommen), [
            ("Zum Alten Fass 1 u. 3", ["Zum Alten Fass 1", "Zum Alten Fass 3"], ["a.pdf", "b.pdf"])])

    def test_zerlege_tags_an_ort_und_stelle_ohne_doppelte(self):
        zerlegung = {"zum alten fass 1 u. 3": ["Zum Alten Fass 1", "Zum Alten Fass 3"]}
        self.assertEqual(
            zerlege_tags(["Strom", "Zum Alten Fass 1 u. 3", "Zum Alten Fass 3", "Musterheim"], zerlegung),
            (["Strom", "Zum Alten Fass 1", "Zum Alten Fass 3", "Musterheim"], True))
        self.assertEqual(zerlege_tags(["Strom"], zerlegung), (["Strom"], False))

    def test_schreibt_ins_pdf_und_behaelt_titel(self):
        pfad = self._erzeuge_pdf("a.pdf", titel="Grundsteuer", keywords="Grundsteuer, Zum Alten Fass 1 u. 3")
        self._erzeuge_pdf("b.pdf", keywords="Strom")
        zerlegung = {"zum alten fass 1 u. 3": ["Zum Alten Fass 1", "Zum Alten Fass 3"]}
        self.assertEqual(zerlege_sammel_tags_in_dokumenten(self.master, ["a.pdf", "b.pdf", "fehlt.pdf"], zerlegung), 1)
        meta = PDFHandler.get_metadata(pfad)
        self.assertEqual(meta["title"], "Grundsteuer")
        self.assertEqual(meta["keywords"], "Grundsteuer, Zum Alten Fass 1, Zum Alten Fass 3")


class TestStandardSynonyme(unittest.TestCase):
    """Synonyme der mitgelieferten Vorlage in bestehende Kataloge nachtragen (28.10.2026)."""

    VORLAGE = [
        {"text": "Wohnen & Haus", "is_structural": True, "children": [
            {"text": "Nebenkosten", "children": [
                {"text": "Gas", "children": [{"text": "Erdgas", "is_synonym": True}]},
                {"text": "Müll", "children": [{"text": "Müllabfuhr", "is_synonym": True},
                                              {"text": "Abfallgebühr", "is_synonym": True}]},
                {"text": "Betriebskosten", "is_synonym": True},
            ]},
            {"text": "Wirkungslos", "is_synonym": True},   # nur graue Kategorie darüber
        ]},
    ]

    def test_ziel_ist_naechstes_zuweisbares_tag(self):
        self.assertEqual(standard_synonyme(self.VORLAGE), [
            ("Gas", "Erdgas"), ("Müll", "Müllabfuhr"), ("Müll", "Abfallgebühr"),
            ("Nebenkosten", "Betriebskosten")])

    def test_nur_unter_vorhandenen_ziel_tags_in_katalog_schreibweise(self):
        katalog = [{"text": "Haus", "is_structural": True, "children": [
            {"text": "gas", "children": []}, {"text": "Müll", "children": []}]}]
        self.assertEqual(plane_standard_synonyme(self.VORLAGE, katalog), [
            ("gas", "Erdgas"), ("Müll", "Abfallgebühr"), ("Müll", "Müllabfuhr")])

    def test_vorhandene_texte_bleiben_unangetastet(self):
        katalog = [
            {"text": "Müll", "children": [{"text": "müllabfuhr", "is_synonym": True}]},
            {"text": "Abfallgebühr", "children": []},           # eigenes Tag des Nutzers
            {"text": "Gas", "is_structural": True, "children": []},  # grau = kein Ziel
            {"text": "Nebenkosten", "is_synonym": True, "children": []},  # Synonym = kein Ziel
        ]
        self.assertEqual(plane_standard_synonyme(self.VORLAGE, katalog), [])

    def test_mitgelieferte_vorlage_ist_lesbar_und_liefert_synonyme(self):
        import json
        import app_paths
        with open(app_paths.bundled_default_path("tags_default.json"), encoding="utf-8") as f:
            vorlage = json.load(f)
        paare = standard_synonyme(vorlage)
        self.assertGreater(len(paare), 20)
        # gegen einen leeren Katalog gibt es nichts zu tun, gegen die Vorlage selbst auch nicht
        self.assertEqual(plane_standard_synonyme(vorlage, []), [])
        self.assertEqual(plane_standard_synonyme(vorlage, vorlage), [])


if __name__ == "__main__":
    unittest.main()
