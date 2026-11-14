"""Der ausgelieferte Start-Katalog (tags_default.json) muss in sich stimmig sein - seit 27.10.2026
bringt er Synonyme ab Werk mit (Tag-Wildwuchs: 'Haftpflichtversicherung' neben 'Haftpflicht')."""
import json
import os
import unittest

import auto_pilot

PFAD = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tags_default.json")


def _lade():
    with open(PFAD, encoding="utf-8") as f:
        return json.load(f)


def _synonyme_und_tags(baum):
    """Wie tag_manager.get_synonyme/get_known_tags, nur auf der JSON-Struktur."""
    synonyme, tags = {}, []

    def walk(knoten, ziel):
        for k in knoten:
            if k.get("is_synonym"):
                synonyme[k["text"].lower()] = ziel
            elif not k.get("is_structural"):
                tags.append(k["text"])
            walk(k.get("children", []), k["text"] if not (k.get("is_structural") or k.get("is_synonym")) else ziel)

    walk(baum, None)
    return synonyme, tags


class TestTagsDefault(unittest.TestCase):

    def test_jedes_synonym_hat_ein_ziel_tag(self):
        synonyme, _tags = _synonyme_und_tags(_lade())
        self.assertGreater(len(synonyme), 20)
        ohne_ziel = [s for s, ziel in synonyme.items() if not ziel]
        self.assertEqual(ohne_ziel, [])

    def test_kein_synonym_ist_zugleich_ein_tag(self):
        synonyme, tags = _synonyme_und_tags(_lade())
        self.assertEqual(sorted(set(synonyme) & {t.lower() for t in tags}), [])

    def test_keine_doppelten_namen(self):
        synonyme, tags = _synonyme_und_tags(_lade())
        namen = [t.lower() for t in tags]
        self.assertEqual(len(namen), len(set(namen)))

    def test_langformen_der_ki_landen_beim_katalog_tag(self):
        synonyme, _tags = _synonyme_und_tags(_lade())
        tags, ersetzt = auto_pilot.ersetze_synonyme(
            ["Gebäudebrandversicherung", "Haftpflichtversicherung", "Betriebskosten", "Rechnung"], synonyme)
        self.assertEqual(tags, ["Gebäudeversicherung", "Haftpflicht", "Nebenkosten", "Rechnung"])
        self.assertEqual(len(ersetzt), 3)


if __name__ == "__main__":
    unittest.main()
