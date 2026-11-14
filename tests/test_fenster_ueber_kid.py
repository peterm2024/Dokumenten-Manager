"""
Peter 04.11.2026: „Das Fenster sollte wieder TopMost sein, aber nicht modal. Das sollten wir generell bei allen
aufpoppenden Fenstern so machen, sonst kann es sein, dass ein Fenster aus Versehen im Hintergrund verschwindet und
doppelt geöffnet wird.“ - jede Fenster-Klasse (tk.Toplevel) in src/ bleibt über dem Hauptfenster (transient bzw.
UIUtils.werkzeugfenster). Geprüft per ast, ohne etwas auszuführen; wer bewusst abweicht, trägt es hier mit Grund ein.
"""
import ast
import glob
import os
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

AUSNAHMEN = {
    # Statusfenster des Seniorenmodus: bleibt stehen, während man in einem ANDEREN Programm arbeitet (T10g.63) -
    # transient verschwände es mit dem minimierten Hauptfenster
    "VollautomatikFenster",
}


def fensterklassen():
    for pfad in sorted(glob.glob(os.path.join(SRC, "**", "*.py"), recursive=True)):
        with open(pfad, encoding="utf-8") as f:
            quelle = f.read()
        for knoten in ast.walk(ast.parse(quelle)):
            if isinstance(knoten, ast.ClassDef) and any(
                    (isinstance(b, ast.Attribute) and b.attr == "Toplevel") or (isinstance(b, ast.Name) and b.id == "Toplevel")
                    for b in knoten.bases):
                yield os.path.relpath(pfad, SRC), knoten.name, ast.get_source_segment(quelle, knoten)


class TestFensterUeberKid(unittest.TestCase):
    def test_jedes_fenster_bleibt_ueber_dem_hauptfenster(self):
        gefunden = list(fensterklassen())
        self.assertGreater(len(gefunden), 20)
        fehlend = [f"{datei}: {name}" for datei, name, text in gefunden
                   if name not in AUSNAHMEN and "transient(" not in text and "werkzeugfenster(" not in text]
        self.assertEqual(fehlend, [], "Fenster ohne transient/UIUtils.werkzeugfenster - verschwinden hinter KID")


if __name__ == "__main__":
    unittest.main()
