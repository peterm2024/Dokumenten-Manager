"""Tag-Katalog ohne Oberfläche (tag_katalog.py, Etappe 10 Schritt 1): Regeln wie im Tag-Baum, Lesen aus tags.json.
Nur Musterdaten."""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock

import auto_pilot
import tag_katalog
from tag_manager import TagManager
from tests.test_tag_manager import _FakeTagTree

KATALOG = [
    {"text": "Dokumentart", "is_structural": True, "children": [
        {"text": "Rechnung", "children": []},
        {"text": "rechnung", "children": [{"text": "Verschluckt", "children": []}]},   # Doppelt auf derselben Ebene
        {"text": "Vertrag", "children": []}]},
    {"text": "Thema", "is_structural": True, "children": [
        {"text": "Versicherung", "children": [
            {"text": "Haftpflicht", "children": [
                {"text": "Haftpflichtversicherung", "is_synonym": True, "children": []}]}]},
        {"text": "Sonstiges", "is_synonym": True, "children": []}]},           # Synonym ohne Ziel: wirkungslos
    {"text": "Personen", "is_structural": True, "children": [{"text": "Max Mustermann", "children": []}]},
    {"text": "Wohnen & Immobilien", "is_structural": True, "children": [
        {"text": "Adressen", "is_structural": True, "children": [{"text": "Musterstraße 1", "children": []}]}]},
    {"text": "Beides", "is_structural": True, "is_synonym": True, "children": []},  # Synonym hat Vorrang
]


class TestRegeln(unittest.TestCase):
    def setUp(self):
        self.knoten = tag_katalog.bereinige(KATALOG)

    def test_bekannte_tags_ohne_kategorien_synonyme_und_doppelte(self):
        self.assertEqual(tag_katalog.bekannte_tags(self.knoten),
                         ["Rechnung", "Vertrag", "Versicherung", "Haftpflicht", "Max Mustermann", "Musterstraße 1"])

    def test_kategorien(self):
        self.assertEqual(tag_katalog.kategorien(self.knoten),
                         ["Dokumentart", "Thema", "Personen", "Wohnen & Immobilien", "Adressen"])

    def test_parents_nur_zuweisbare(self):
        self.assertEqual(tag_katalog.tag_parents(self.knoten), {"haftpflicht": ["Versicherung"]})

    def test_synonyme_zeigen_auf_das_tag_darueber(self):
        self.assertEqual(tag_katalog.synonyme(self.knoten), {"haftpflichtversicherung": "Haftpflicht"})

    def test_merkmale_unter_variantennamen(self):
        merkmale = tag_katalog.merkmale_fuer_dubletten(self.knoten, auto_pilot.KATEGORIE_VARIANTEN)
        self.assertEqual(merkmale["Personen"], ["Max Mustermann"])
        self.assertEqual(merkmale["Objekte & Adressen"], ["Musterstraße 1"])


class TestLaden(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.pfad = os.path.join(self.tmp, "tags.json")

    def _schreibe(self, pfad, inhalt):
        with open(pfad, "w", encoding="utf-8") as f:
            f.write(inhalt)

    def test_liest_die_datei(self):
        self._schreibe(self.pfad, json.dumps(KATALOG))
        self.assertIn("Haftpflicht", tag_katalog.bekannte_tags(tag_katalog.lade(self.pfad)))

    def test_beschaedigt_nimmt_die_sicherung_und_laesst_die_datei_liegen(self):
        self._schreibe(self.pfad, "{kaputt")
        self._schreibe(self.pfad + ".bak", json.dumps([{"text": "Aus der Sicherung", "children": []}]))
        self.assertEqual(tag_katalog.bekannte_tags(tag_katalog.lade(self.pfad)), ["Aus der Sicherung"])
        with open(self.pfad, encoding="utf-8") as f:
            self.assertEqual(f.read(), "{kaputt")

    def test_ohne_datei_none(self):
        self.assertIsNone(tag_katalog.lade(self.pfad))


class TestGleichWieImBaum(unittest.TestCase):
    """Der TagManager rechnet auf seinem Baum dasselbe wie der Dienst auf der Datei - System-Einträge zählen nicht."""

    def test_ausgelieferte_vorlage(self):
        wurzel = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(wurzel, "tags_default.json"), encoding="utf-8") as f:
            vorlage = json.load(f) + KATALOG
        app = MagicMock()
        baum = app.tree_tags = _FakeTagTree()
        zuletzt = baum.insert("", "end", text="⏱️ Zuletzt benutzt",
                              tags=(TagManager.TAG_RECENT_ROOT, TagManager.TAG_STRUCTURAL))
        baum.insert(zuletzt, "end", text="Rechnung", tags=(TagManager.TAG_RECENT_ITEM,))
        baum.insert("", "end", text="Nur am Dokument", tags=(TagManager.TAG_TEMP,))
        baum.insert("", "end", text="────", tags=(TagManager.TAG_SEP,))

        def einfuegen(parent, knoten):          # wie tag_editor._insert_nodes
            vorhanden = set()
            for k in knoten:
                if k["text"].lower() in vorhanden:
                    continue
                vorhanden.add(k["text"].lower())
                tags = (TagManager.TAG_BUNDLE,)
                if k.get("is_synonym"):
                    tags += (TagManager.TAG_SYNONYM,)
                elif k.get("is_structural"):
                    tags += (TagManager.TAG_STRUCTURAL,)
                einfuegen(baum.insert(parent, "end", text=k["text"], tags=tags), k.get("children") or [])

        einfuegen("", vorlage)
        manager = TagManager(app)
        knoten = tag_katalog.bereinige(vorlage)
        datei = tag_katalog.katalog_fuer_dienst(knoten)
        self.assertEqual(manager.get_known_tags(), datei["known_tags"])
        self.assertNotIn("Nur am Dokument", datei["known_tags"])
        self.assertEqual(manager.get_kategorien(), datei["kategorien"])
        self.assertEqual(manager.get_tag_eltern(), datei["tag_eltern"])
        self.assertEqual(manager.get_synonyme(), datei["synonyme"])
        self.assertEqual(manager.merkmale_fuer_dubletten(),
                         tag_katalog.merkmale_fuer_dubletten(knoten, auto_pilot.KATEGORIE_VARIANTEN))
        self.assertGreater(len(datei["known_tags"]), 20)


if __name__ == "__main__":
    unittest.main()
