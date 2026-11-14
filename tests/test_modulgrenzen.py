"""
Modulgrenzen, die CLAUDE.md beschreibt, als Test (01.11.2026, Vorbild: `cargo xtask layers` bei
storytold/pdfcraft): ohne Prüfung hält sich der Code nur so lange daran, wie jemand daran denkt.
Geprüft werden die DIREKTEN Importe jedes Moduls in src/ (per ast, ohne etwas auszuführen).
Wer eine Grenze bewusst verschiebt, ändert die Liste hier UND die Beschreibung in CLAUDE.md.
"""
import ast
import os
import sys
import unittest

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

# Module ohne Oberfläche: testbar ohne Tk, aus Hintergrund-Threads nutzbar (Vollautomatik, Index)
GUI_FREI = {
    "sicher_speichern", "einzelstart", "personen_namen",
    "ablage_gedaechtnis", "aktivitaet", "begleitet", "app_logger", "app_paths", "auto_pilot", "auto_pilot_service",
    "config", "dateinamen", "dubletten", "dubletten_geprueft", "dubletten_pruefung", "folder_monitor",
    "index_manager", "mail_import", "mail_lesen", "mail_pst", "mail_quellen", "menue_hilfe", "ollama_client", "ordner_aliase", "papierkorb_herkunft", "scan_date", "server_wecken",
    "spell_correct", "suchsyntax", "tag_ignorierliste", "text_quality",
    "wissen", "wissen_ki", "zuletzt_benutzt",
}

# PyMuPDF nur über pdf_handler; file_operations prüft nur, ob es installiert ist (CLAUDE.md, ruff-Abschnitt).
# Tools (src/tools/) dürfen es direkt - sie sind Erweiterungen, nicht der Kern.
FITZ_ERLAUBT = {"pdf_handler", "file_operations"}

# Nur Standardbibliothek + eigene Module (dünner HTTP-Client, läuft auch ohne Zusatzpakete)
NUR_STANDARD = {"ollama_client", "app_paths", "config", "spell_correct", "scan_date", "aktivitaet", "server_wecken",
                "mail_lesen", "mail_quellen", "sicher_speichern", "einzelstart", "personen_namen",
                "suchsyntax", "wissen", "wissen_ki"}

# Einzelne verbotene Kanten: (Modul, darf nicht importieren, Grund)
VERBOTEN = [
    ("personen_namen", "auto_pilot", "kein Ring: auto_pilot nutzt die Namenslogik, nicht umgekehrt"),
    ("dubletten", "pdf_handler", "dubletten.py bleibt PyMuPDF-frei, der Aufrufer liefert die PDF-Werte"),
    ("dubletten", "fitz", "dubletten.py bleibt PyMuPDF-frei"),
    ("auto_pilot", "dubletten", "Ringschluss: dubletten importiert auto_pilot"),
    ("auto_pilot", "dubletten_pruefung", "Ringschluss über dubletten"),
    ("auto_pilot", "auto_pilot_service", "die Logik kennt den Dienst nicht, nur umgekehrt"),
    ("index_manager", "search_manager", "search_manager benutzt den Index, nicht umgekehrt"),
]


def _importe(modul):
    """Namen der direkt importierten Module (oberste Ebene, `from tools.x` -> 'tools')."""
    with open(os.path.join(SRC, modul + ".py"), encoding="utf-8") as f:
        baum = ast.parse(f.read())
    namen = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Import):
            namen |= {a.name.split(".")[0] for a in knoten.names}
        elif isinstance(knoten, ast.ImportFrom) and knoten.module and knoten.level == 0:
            namen.add(knoten.module.split(".")[0])
    return namen


def _module():
    return sorted(f[:-3] for f in os.listdir(SRC) if f.endswith(".py"))


class TestModulgrenzen(unittest.TestCase):

    def test_listen_nennen_nur_vorhandene_module(self):
        vorhanden = set(_module())
        genannt = GUI_FREI | FITZ_ERLAUBT | NUR_STANDARD | {m for m, _, _ in VERBOTEN}
        self.assertEqual(genannt - vorhanden, set(), "Modul umbenannt/entfernt? Liste anpassen")

    def test_gui_freie_module_importieren_kein_tkinter(self):
        for modul in sorted(GUI_FREI):
            with self.subTest(modul=modul):
                self.assertNotIn("tkinter", _importe(modul))

    def test_pymupdf_im_kern_nur_ueber_pdf_handler(self):
        for modul in _module():
            if modul in FITZ_ERLAUBT:
                continue
            with self.subTest(modul=modul):
                self.assertNotIn("fitz", _importe(modul))

    def test_nur_standardbibliothek(self):
        eigene = set(_module()) | {"tools"}
        for modul in sorted(NUR_STANDARD):
            with self.subTest(modul=modul):
                fremd = {n for n in _importe(modul) if n not in sys.stdlib_module_names and n not in eigene}
                self.assertEqual(fremd, set())

    def test_verbotene_kanten(self):
        for modul, ziel, grund in VERBOTEN:
            with self.subTest(modul=modul, ziel=ziel):
                self.assertNotIn(ziel, _importe(modul), grund)


if __name__ == "__main__":
    unittest.main()
