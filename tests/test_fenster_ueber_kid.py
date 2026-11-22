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
    # transient verschwände es mit dem minimierten Hauptfenster; über KID hält es vollautomatik_fenster.vorn_halten
    # (B1, 21.11.2026), über allen Programmen nur im Dienstmodus
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
                yield os.path.relpath(pfad, SRC), knoten.name, knoten


def ruft_ueber_kid(klasse):
    """Ruft die Klasse transient(...) oder UIUtils.werkzeugfenster(...) auf? Nur echte Aufrufe zählen: Bis 21.11.2026
    ließ der Test die Ablage-Vorschau durch, weil ihr KOMMENTAR „Bewusst KEIN transient(app.root)“ lautete."""
    return any(isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute)
               and k.func.attr in ("transient", "werkzeugfenster") for k in ast.walk(klasse))


class TestFensterUeberKid(unittest.TestCase):
    def test_jedes_fenster_bleibt_ueber_dem_hauptfenster(self):
        gefunden = list(fensterklassen())
        self.assertGreater(len(gefunden), 20)
        fehlend = [f"{datei}: {name}" for datei, name, klasse in gefunden
                   if name not in AUSNAHMEN and not ruft_ueber_kid(klasse)]
        self.assertEqual(fehlend, [], "Fenster ohne transient/UIUtils.werkzeugfenster - verschwinden hinter KID")


# Fenster, die ein Werkzeug bewusst NICHT über oeffne_fenster öffnet: modaler Fortschritt eines Laufs
NICHT_WERKZEUGFENSTER = {"ProgressDialog"}


def _execute_methoden():
    for pfad in sorted(glob.glob(os.path.join(SRC, "tools", "*.py"))):
        with open(pfad, encoding="utf-8") as f:
            baum = ast.parse(f.read())
        for klasse in ast.walk(baum):
            if isinstance(klasse, ast.ClassDef):
                for m in klasse.body:
                    if isinstance(m, ast.FunctionDef) and m.name == "execute":
                        yield f"{os.path.basename(pfad)}: {klasse.name}", m


def _ist_self_attribut(knoten):
    return (isinstance(knoten, ast.Attribute) and isinstance(knoten.value, ast.Name)
            and knoten.value.id == "self")


def werkzeug_verstoesse(execute, fensternamen):
    """Was in execute() am einen Weg vorbei ein Fenster öffnet oder verwirft (leere Liste = in Ordnung)."""
    verstoesse, verschachtelt = [], set()
    for knoten in ast.walk(execute):
        if isinstance(knoten, (ast.Lambda, ast.FunctionDef)) and knoten is not execute:
            verschachtelt.update(id(k) for k in ast.walk(knoten))
    ruft_oeffne = False
    for knoten in ast.walk(execute):
        if not isinstance(knoten, ast.Call):
            continue
        f = knoten.func
        name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
        if name == "oeffne_fenster":
            ruft_oeffne = True
        elif name == "einzelfenster" or (name == "destroy" and _ist_self_attribut(f.value)):
            verstoesse.append(f"ruft {name}() selbst auf")   # destroy: nur self.<fenster>, ein Fortschritt darf
        elif name in fensternamen and id(knoten) not in verschachtelt:
            verstoesse.append(f"baut {name} direkt")
    if any(isinstance(k, ast.Call) and isinstance(k.func, ast.Name) and k.func.id in fensternamen
           for k in ast.walk(execute)) and not ruft_oeffne:
        verstoesse.append("öffnet ein Fenster ohne oeffne_fenster")
    return verstoesse


class TestWerkzeugeOeffnenUeberBaseTool(unittest.TestCase):
    """Fenster-Durchsicht B3 (Peter 21.11.2026): jedes Werkzeug öffnet sein Fenster über BaseTool.oeffne_fenster -
    höchstens eins, ein zweiter Aufruf holt das offene samt Änderungen nach vorn. Vorher regelte das jedes Werkzeug
    selbst: vier verwarfen das offene Fenster, eins öffnete beliebig viele, eins überging eine neue Auswahl still."""

    def test_jedes_werkzeug_nimmt_den_einen_weg(self):
        fensternamen = {name for _, name, _ in fensterklassen()} - NICHT_WERKZEUGFENSTER
        gefunden = list(_execute_methoden())
        self.assertGreater(len(gefunden), 20)
        fehler = [f"{wo}: {v}" for wo, m in gefunden for v in werkzeug_verstoesse(m, fensternamen)]
        self.assertEqual(fehler, [])

if __name__ == "__main__":
    unittest.main()
