"""Benchmark (Etappe 13 Schritt 3): Messlauf wie im Dienst, ohne KI-Server - Lesen und Zweitmeinung sind Attrappen."""
import os
import tempfile
import unittest
from unittest.mock import patch

import benchmark
import pruefdokumente as p


class Uhr:
    """Falsche Uhr: jeder Aufruf der Attrappen lässt so viele Sekunden vergehen, wie sie vorgeben."""
    def __init__(self):
        self.jetzt = 0.0

    def __call__(self):
        return self.jetzt


def attrappen(uhr, lesen_s=5.0, zweit_s=3.0, laden_s=20.0, wechsel_s=8.0, fehler_bei=()):
    """Lesen/Zweitmeinung wie ein Server mit 16 GB: das erste Laden dauert, je Stapel kostet der Wechsel extra."""
    zustand = {"geladen": None}

    def kosten(modell, normal):
        if zustand["geladen"] is None:
            extra = laden_s
        elif zustand["geladen"] != modell:
            extra = wechsel_s
        else:
            extra = 0.0
        zustand["geladen"] = modell
        uhr.jetzt += normal + extra

    def lies(pfad, tags, base_url, modell, kategorien):
        nr = p.nummer_aus_text(os.path.basename(pfad).replace("Scan_0", "Prüfdokument "))
        if nr in fehler_bei:
            raise ConnectionError("Server weg")
        kosten(modell, lesen_s)
        w = p.wahrheit(nr)
        absender = p.ABSENDER[p.BRIEFE[nr - 1]["wer"]]["name"]
        return {"pdf_path": pfad, "schreibschutz": None, "png": b"bild", "merkmale": (),
                "ki_antwort": {"title": "Brief", "tags": [], "absender": absender, "datum": w["datum"],
                               "ordnername": "", "empfaenger": "", "objekt": "", "ort": "", "tag_kategorien": {}}}

    def zweit(gelesen, ordnerliste, base_url, modell):
        kosten(modell, zweit_s)
        return [(ordnerliste[0], 0.9)]

    def ps(base_url):
        return {zustand["geladen"]: {"size": 7_000_000_000, "size_vram": 7_000_000_000}} if zustand["geladen"] else {}
    return lies, zweit, ps


class TestLauf(unittest.TestCase):
    def setUp(self):
        self.pfade = [f"C:/x/Scan_{n:04d}.pdf" for n in range(1, 41)]

    def test_stapel_wie_im_dienst_mit_laden_und_modellwechsel(self):
        uhr = Uhr()
        lies, zweit, ps = attrappen(uhr)
        m = benchmark.lauf(self.pfade, "http://srv", "lese:9b", "wahl:9b", lies=lies, zweit=zweit, ps=ps, uhr=uhr)
        self.assertEqual(m["dokumente"], 40)
        self.assertFalse(m["abgebrochen"])
        self.assertTrue(m["kalt"])
        # vier Stapel zu zehn: der erste Aufruf je Stapel trägt Laden bzw. Wechsel
        self.assertEqual(m["lesen_anfang"], [25.0, 13.0, 13.0, 13.0])
        self.assertTrue(all(s == 5.0 for s in m["lesen"]))
        self.assertEqual(len(m["lesen"]), 36)
        self.assertEqual(m["speicher_lesen"], {"status": "gpu", "gb": 7.0})
        e = benchmark.zusammenfassen(m, "lese:9b", "wahl:9b", "RTX Test (16 GB)", "0.9.35")
        self.assertEqual(e["lesen_median"], 5.0)
        self.assertEqual(e["lesen_erster"], 25.0)
        self.assertEqual(e["zweit_median"], 3.0)
        self.assertEqual(e["wechsel_sekunden"], 8.0)
        self.assertGreater(e["zweit_anzahl"], 30)
        self.assertEqual(e["sekunden_je_dokument"], round(uhr.jetzt / 40, 1))

    def test_ohne_zweitmeinung_kein_modellwechsel(self):
        uhr = Uhr()
        lies, zweit, ps = attrappen(uhr)
        m = benchmark.lauf(self.pfade, "http://srv", "lese:9b", "", lies=lies, zweit=zweit, ps=ps, uhr=uhr)
        self.assertEqual(m["zweit"] + m["zweit_anfang"], [])
        self.assertEqual(m["lesen_anfang"], [25.0, 5.0, 5.0, 5.0])
        e = benchmark.zusammenfassen(m, "lese:9b", "", "", "0.9.35")
        self.assertEqual(e["wechsel_sekunden"], 0.0)
        self.assertEqual(e["zweitmodell"], "")

    def test_server_weg_bricht_nach_drei_fehlern_ab(self):
        uhr = Uhr()
        lies, zweit, ps = attrappen(uhr, fehler_bei=range(5, 41))
        m = benchmark.lauf(self.pfade, "http://srv", "lese:9b", "wahl:9b", lies=lies, zweit=zweit, ps=ps, uhr=uhr)
        self.assertEqual(m["fehler"], benchmark.MAX_FEHLER_IN_FOLGE)
        self.assertEqual(m["dokumente"], 4)
        self.assertTrue(m["abgebrochen"])

    def test_abbrechen(self):
        uhr = Uhr()
        lies, zweit, ps = attrappen(uhr)
        gelesen = []

        def lies_mit_zaehler(*a):
            gelesen.append(1)
            return lies(*a)
        m = benchmark.lauf(self.pfade, "http://srv", "lese:9b", "wahl:9b", lies=lies_mit_zaehler, zweit=zweit, ps=ps,
                           uhr=uhr, abbrechen=lambda: len(gelesen) >= 12)
        self.assertEqual(len(gelesen), 12)
        self.assertTrue(m["abgebrochen"])

    def test_nichts_wird_in_der_echten_sammlung_angelegt(self):
        # Der Lauf legt die Ordner der Benchmark-Sammlung nur in einem Wegwerf-Ordner an
        uhr = Uhr()
        lies, zweit, ps = attrappen(uhr)
        vorher = set(os.listdir(tempfile.gettempdir()))
        benchmark.lauf(self.pfade[:3], "http://srv", "lese:9b", "", lies=lies, zweit=zweit, ps=ps, uhr=uhr)
        self.assertFalse({n for n in set(os.listdir(tempfile.gettempdir())) - vorher if n.startswith("kid_benchmark_")})


class TestErgebnis(unittest.TestCase):
    def beispiel(self, **anders):
        e = {"datum": "2026-11-20 00:30", "version": "0.9.35", "satz": "digital", "grafikkarte": "RTX Test (16 GB)",
             "lesemodell": "lese:9b", "zweitmodell": "wahl:9b", "dokumente": 40, "fehler": 0, "abgebrochen": False,
             "kalt": True, "sekunden_je_dokument": 9.25, "minuten_gesamt": 6.2, "lesen_median": 5.0,
             "lesen_erster": 25.0, "zweit_median": 3.0, "zweit_erster": 11.0, "zweit_anzahl": 33,
             "wechsel_sekunden": 8.0, "speicher_lesen": {"status": "gpu", "gb": 7.0},
             "speicher_zweit": {"status": "teilweise", "gb": 5.5}}
        e.update(anders)
        return e

    def test_text_nur_zahlen_und_namen(self):
        text = benchmark.als_text(self.beispiel())
        self.assertIn("Sekunden je Dokument: 9,2 s", text)
        self.assertIn("Zweitmeinung liegt auf: teilweise Prozessor, 5,5 GB", text)
        self.assertIn("Grafikkarte: RTX Test (16 GB)", text)
        self.assertNotIn("http", text)

    def test_speichern_und_laden_begrenzt(self):
        with tempfile.TemporaryDirectory() as ordner:
            pfad = os.path.join(ordner, "daten", "benchmark.json")
            self.assertEqual(benchmark.lade_ergebnisse(pfad), [])
            for i in range(benchmark.MAX_ERGEBNISSE + 2):
                benchmark.speichere_ergebnis(pfad, self.beispiel(dokumente=i))
            alle = benchmark.lade_ergebnisse(pfad)
            self.assertEqual(len(alle), benchmark.MAX_ERGEBNISSE)
            self.assertEqual(alle[-1]["dokumente"], benchmark.MAX_ERGEBNISSE + 1)

    def test_satz_im_wegwerf_ordner(self):
        # Den Satz selbst prüft test_pruefdokumente - hier nur: eigener Wegwerf-Ordner, danach wieder weg
        def schreibe(ordner):
            pfad = os.path.join(ordner, "Scan_0001.pdf")
            open(pfad, "wb").close()
            return [pfad]
        with patch("pruefdokumente.schreibe_satz", side_effect=schreibe):
            ordner, pfade = benchmark.bereite_satz()
        try:
            self.assertTrue(os.path.basename(ordner).startswith("kid_pruefdokumente_"))
            self.assertTrue(all(os.path.isfile(x) for x in pfade))
        finally:
            benchmark.raeume_satz(ordner)
        self.assertFalse(os.path.exists(ordner))


if __name__ == "__main__":
    unittest.main()
