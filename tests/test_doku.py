"""
Roter Faden der Doku als Test (Peter 05.11.2026): Die Projekt-Durchsicht fand 48 von 80 Modulen ohne Beschreibung in der
Projekt-Dokumentation und Konzepte, die kein Dokument nannte. Geprüft wird nur, ob etwas genannt und auffindbar ist -
ob der Text stimmt, kann kein Test sagen.
"""
import glob
import os
import re
import unittest

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _lies(*teile):
    with open(os.path.join(WURZEL, *teile), encoding="utf-8", errors="replace") as f:
        return f.read()


def _module():
    """Alle App-Module ohne __init__: {Name: Punkt-Name für die Referenz}."""
    dateien = glob.glob(os.path.join(WURZEL, "src", "*.py")) + glob.glob(os.path.join(WURZEL, "src", "tools", "*.py"))
    module = {}
    for pfad in dateien:
        name = os.path.basename(pfad)[:-3]
        if name != "__init__":
            module[name] = f"tools.{name}" if os.path.basename(os.path.dirname(pfad)) == "tools" else name
    return module


def _dokumente():
    return [os.path.basename(p) for p in glob.glob(os.path.join(WURZEL, "*.md"))]


class TestDoku(unittest.TestCase):
    def test_jedes_modul_steht_in_der_projekt_dokumentation(self):
        text = _lies("Projekt-Dokumentation.md")
        fehlt = sorted(m for m in _module() if not re.search(r"\b" + m + r"\b", text))
        self.assertEqual(fehlt, [], "Neues Modul: in Projekt-Dokumentation.md beschreiben")

    def test_jedes_modul_steht_in_der_referenz(self):
        text = _lies("docs", "reference.md")
        fehlt = sorted(p for p in _module().values() if f"::: {p}\n" not in text + "\n")
        self.assertEqual(fehlt, [], "Neues Modul: in docs/reference.md eintragen")

    def _nur_mit_arbeitsnotizen(self):
        # Der öffentliche Quellcode-Spiegel (veroeffentlichen.py) hat FAHRPLAN, CLAUDE.md und Konzepte nicht
        if not os.path.exists(os.path.join(WURZEL, "FAHRPLAN.md")):
            self.skipTest("öffentlicher Spiegel ohne private Arbeitsnotizen")

    def test_jedes_konzept_steht_im_fahrplan(self):
        self._nur_mit_arbeitsnotizen()
        text = _lies("FAHRPLAN.md")
        fehlt = sorted(d for d in _dokumente() if d.startswith("KONZEPT_") and d not in text)
        self.assertEqual(fehlt, [], "Neues Konzept: in die Konzept-Übersicht von FAHRPLAN.md eintragen")

    def test_hauptdokumente_verweisen_aufeinander(self):
        self._nur_mit_arbeitsnotizen()
        claude = _lies("CLAUDE.md")
        for name in ("FAHRPLAN.md", "Projekt-Dokumentation.md", "FALLSTRICKE_UND_WORKAROUNDS.md", "ToDo.txt"):
            self.assertIn(name, claude)
        fahrplan = _lies("FAHRPLAN.md")
        for name in ("Projekt-Dokumentation.md", "FALLSTRICKE_UND_WORKAROUNDS.md", "ToDo.txt", "MANUELLE_TESTS.md",
                     "CHANGELOG.md"):
            self.assertIn(name, fahrplan)
        self.assertIn("FAHRPLAN.md", _lies("Projekt-Dokumentation.md"))
        self.assertIn("FAHRPLAN.md", _lies("ToDo.txt"))

    def test_links_zeigen_auf_vorhandene_dateien(self):
        kaputt = []
        for dokument in _dokumente():
            for ziel in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", _lies(dokument)):
                # ../ zeigt aus dem Repo heraus (Projekte-Wiki), das gibt es nicht auf jedem Rechner
                if not ziel.startswith(("http", "mailto", "..")) and not os.path.exists(os.path.join(WURZEL, ziel)):
                    kaputt.append(f"{dokument}: {ziel}")
        self.assertEqual(kaputt, [])

    def test_fallstricke_nummern_lueckenlos_und_verweise_gueltig(self):
        kopf = [int(n) for n in re.findall(r"^#+\s*(?:Nr\.\s*)?#?(\d+)\b", _lies("FALLSTRICKE_UND_WORKAROUNDS.md"), re.M)]
        self.assertEqual(sorted(kopf), list(range(1, len(kopf) + 1)))
        dateien = [os.path.join(WURZEL, d) for d in _dokumente() if not d.startswith("FALLSTRICKE")]
        dateien += glob.glob(os.path.join(WURZEL, "src", "**", "*.py"), recursive=True)
        dateien += glob.glob(os.path.join(WURZEL, "tests", "*.py"))
        tot = []
        for pfad in dateien:
            with open(pfad, encoding="utf-8", errors="replace") as f:
                inhalt = f.read()
            for nummer in re.findall(r"FALLSTRICKE[^\n#]{0,30}#(\d+)", inhalt):
                if int(nummer) not in kopf and os.path.basename(pfad) != "test_doku.py":
                    tot.append(f"{os.path.basename(pfad)}: #{nummer}")
        self.assertEqual(tot, [])


if __name__ == "__main__":
    unittest.main()
