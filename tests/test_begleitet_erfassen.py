import os
import shutil
import tempfile
import time
import tkinter as tk
import types
import unittest
from unittest.mock import patch

from tools import begleitet_erfassen as be


def threads_beenden():
    """Hintergrund-Threads der Fenster abwarten und alle Verweise aufs Test-Tk im HAUPT-Thread abräumen: stirbt ein
    Tk-Objekt später in einem fremden Thread (Thread-Ende oder Garbage Collector, z.B. im Fehlerfänger-Test), bricht
    „Tcl_AsyncDelete: async handler deleted by the wrong thread“ die ganze Suite ab."""
    import gc
    import threading
    from ui_utils import UIUtils
    for faden in threading.enumerate():
        if faden is not threading.main_thread() and faden.daemon:
            faden.join(5)
    UIUtils._einzelfenster.clear()
    gc.collect()


class Einstellungen(dict):
    def get(self, schluessel, vorgabe=None):
        return super().get(schluessel, vorgabe)

    def set(self, schluessel, wert):
        self[schluessel] = wert


def vorschlag(pfad, sicher=True, ziel="M - N - O - P - Q - R\\Musterversicherung"):
    return {"pdf_path": pfad, "titel": "Beitragsrechnung", "titel_korrekturen": [], "tags": ["Versicherung"],
            "neue_tags": [], "tag_ersetzungen": [], "datum": "2025-01-15" if sicher else "",
            "absender": "Musterversicherung AG",
            "ordnername": "Musterversicherung", "zielordner": ziel, "ordner_neu": False, "ordner_per_alias": False,
            "ordner_gedaechtnis": 0, "ordner_hinweis": "", "objekte": [], "sicher": sicher,
            "neuer_dateiname": "20250115_Beitragsrechnung.pdf" if sicher else "",
            "probleme": [] if sicher else ["kein plausibles Dokumentdatum erkannt"]}


class TestPruefplatz(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(threads_beenden)                 # nach root.destroy
        self.addCleanup(self.root.destroy)
        self.addCleanup(threads_beenden)   # vor root.destroy: kein Tk-Objekt stirbt in einem Thread
        self.sammlung = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.sammlung, True)
        for ordner in ("0_Posteingang", "0_Unsicher", "M - N - O - P - Q - R\\Musterversicherung"):
            os.makedirs(os.path.join(self.sammlung, ordner))
        self.pfade = []
        for name in ("20250101_a.pdf", "20250102_b.pdf", "20250103_c.pdf"):
            pfad = os.path.join(self.sammlung, "0_Posteingang", name)
            open(pfad, "wb").close()
            self.pfade.append(pfad)
        self.ausgefuehrt = []
        self.vorschlaege = {}                        # Dateiname -> abweichender Vorschlag
        self.dienst = types.SimpleNamespace(pausen=0, angestossen=0)
        self.dienst.pausieren = lambda: setattr(self.dienst, "pausen", self.dienst.pausen + 1)
        self.dienst.fortsetzen = lambda: setattr(self.dienst, "pausen", self.dienst.pausen - 1)
        self.dienst.anstossen = lambda: setattr(self.dienst, "angestossen", self.dienst.angestossen + 1)
        self.gezeigt = []
        self.app = types.SimpleNamespace(
            root=self.root, master_folder=self.sammlung, config=Einstellungen(), auto_pilot_service=self.dienst,
            file_ops=types.SimpleNamespace(_verschiebe_ohne_duplikat=None), is_moving=False,
            folder_manager=types.SimpleNamespace(zeige_dokument=self.gezeigt.append, refresh_folder_tree=lambda: None))
        patcher = [
            patch("tools.begleitet_erfassen.auto_pilot.lies_dokument",
                  side_effect=lambda pfad, *a, **k: {"pdf_path": pfad, "png": b"x", "ki_antwort": {}, "schreibschutz": None}),
            patch("tools.begleitet_erfassen.auto_pilot.entscheide_gelesen",
                  side_effect=lambda gelesen, *a, **k: self.vorschlaege.get(
                      os.path.basename(gelesen["pdf_path"]),
                      vorschlag(gelesen["pdf_path"], sicher=not gelesen["pdf_path"].endswith("b.pdf")))),
            patch("tools.begleitet_erfassen.dubletten_pruefung.pruefe_entscheidung"),
            patch("tools.begleitet_erfassen.auto_pilot.fuehre_entscheidung_aus", side_effect=self._ausfuehren),
            patch("tools.begleitet_erfassen.auto_pilot.protokolliere_ergebnis"),
            patch("tools.begleitet_erfassen.mb.askyesno", return_value=True),
            patch("tools.begleitet_erfassen.mb.showinfo"),
            patch("tools.begleitet_erfassen.PDFHandler.scan_tag", return_value="2025-02-01"),
        ]
        # transient zu einem versteckten Hauptfenster = unsichtbar (nur im Test, in KID ist es sichtbar)
        aus = patch("ui_utils.UIUtils.werkzeugfenster")
        aus.start()
        self.addCleanup(aus.stop)
        for p in patcher:
            p.start()
            self.addCleanup(p.stop)

    def _ausfuehren(self, e, *args, **kwargs):
        self.ausgefuehrt.append((os.path.basename(e["pdf_path"]), e["sicher"], e["zielordner"], e["datum"]))
        return {"erfolg": True, "neuer_pfad": os.path.join(self.sammlung, e["zielordner"], "x.pdf"), "fehler": None}

    def warte(self, bedingung, sekunden=5):
        ende = time.time() + sekunden
        while time.time() < ende:
            self.root.update()
            if bedingung():
                return
            time.sleep(0.02)
        self.fail("Zeitüberschreitung")

    def test_ablauf_ablegen_korrigieren_zurueckstellen(self):
        f = be.BegleitetFenster(self.app, self.pfade)
        self.addCleanup(f._schliessen)
        self.assertEqual(self.dienst.pausen, 1)                               # Vollautomatik pausiert
        self.warte(lambda: f.entscheidung is not None)
        self.assertEqual(self.gezeigt[-1], self.pfade[0])                     # Hauptfenster zeigt das Dokument
        self.assertEqual(f.lbl_status.cget("bg"), be.GRUEN)
        f._ablegen()                                                          # 1: grün, so übernommen
        self.warte(lambda: f.entscheidung is not None and f.nr == 1)
        self.assertEqual(f.lbl_status.cget("bg"), be.GELB)                    # 2: gelb, Datum fehlt
        self.assertEqual(f.eingaben["datum"].get(), "2025-02-01")             # Scandatum vorgeschlagen
        self.assertIn("Scandatum", f.lbl_datum_hinweis.cget("text"))
        self.assertEqual(str(f.focus_get()), str(f.eingaben["datum"]))
        f.eingaben["datum"].delete(0, tk.END)
        f.eingaben["datum"].insert(0, "03.02.2025")
        f._ablegen()
        self.warte(lambda: f.entscheidung is not None and f.nr == 2)
        f._zurueckstellen()                                                   # 3: nach 0_Unsicher
        self.assertEqual(self.ausgefuehrt, [
            ("20250101_a.pdf", True, "M - N - O - P - Q - R\\Musterversicherung", "2025-01-15"),
            ("20250102_b.pdf", True, "M - N - O - P - Q - R\\Musterversicherung", "2025-02-03"),
            ("20250103_c.pdf", False, "M - N - O - P - Q - R\\Musterversicherung", "2025-01-15")])
        self.assertEqual((f.abgelegt, f.zurueckgestellt, f.nr), (2, 1, 3))
        self.assertEqual(f.gedaechtnis.frage("Musterversicherung AG")[0], "M - N - O - P - Q - R\\Musterversicherung")
        self.assertIn("Fertig: 2 abgelegt", f.lbl_status.cget("text"))
        f._schliessen()
        self.assertEqual(self.dienst.pausen, 0)                               # Vollautomatik läuft weiter

    def test_b4_rueckfrage_legt_alias_an(self):
        ziel = "M - N - O - P - Q - R\\Musterversicherung"
        b = os.path.join(self.sammlung, "0_Posteingang", "20250102_b.pdf")
        self.vorschlaege["20250102_b.pdf"] = dict(vorschlag(b), absender="Landesbrand Musterland",
                                                   zielordner="K - L\\Landesbrand Musterland", ordner_neu=True)
        f = be.BegleitetFenster(self.app, self.pfade)
        self.addCleanup(f._schliessen)
        self.warte(lambda: f.entscheidung is not None)
        f._ablegen()                                                          # a: Musterversicherung AG -> ziel
        self.warte(lambda: f.entscheidung is not None and f.nr == 1)
        f.eingaben["ziel"].delete(0, tk.END)
        f.eingaben["ziel"].insert(0, ziel)                                    # b: korrigiert in denselben Ordner
        f.eingaben["datum"].delete(0, tk.END)
        f.eingaben["datum"].insert(0, "02.01.2025")
        with patch("tools.begleitet_erfassen.mb.askyesno", return_value=True) as frage:
            f._ablegen()
        self.assertIn("derselbe Absender wie „Musterversicherung AG“", frage.call_args[0][1])
        self.assertEqual(f.aliase, {"Landesbrand Musterland": ziel})
        import ordner_aliase
        self.assertEqual(ordner_aliase.lade_aliase(self.sammlung), {"Landesbrand Musterland": ziel})

    def test_rest_der_vollautomatik_geben(self):
        f = be.BegleitetFenster(self.app, self.pfade)
        self.warte(lambda: f.entscheidung is not None)
        f._rest_abgeben()
        self.assertFalse(f.winfo_exists())
        self.assertEqual((self.app.config.get("auto_pilot_enabled"), self.dienst.angestossen, self.dienst.pausen),
                         (True, 1, 0))


if __name__ == "__main__":
    unittest.main()
