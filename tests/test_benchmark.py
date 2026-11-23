"""Benchmark (Etappe 13 Schritt 3): Messlauf wie im Dienst, ohne KI-Server - Lesen und Zweitmeinung sind Attrappen."""
import os
import tempfile
import unittest

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
        # Schritt 4: jeder Fehler mit Prüfnummer und Ursache (die Attrappe wirft ConnectionError)
        self.assertEqual(m["fehler_liste"], [(5, "Lesen", "Server nicht erreichbar"),
                                             (6, "Lesen", "Server nicht erreichbar"),
                                             (7, "Lesen", "Server nicht erreichbar")])

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

    def test_qualitaet_im_text_alte_laeufe_ohne(self):
        e = self.beispiel(qualitaet={"richtig": 31, "pruefen": 6, "falsch": 3, "datum": 36, "absender": 38},
                          pruefsumme="9aa3ab59d6fd", fehler=2, fehler_ursachen={"Zeitüberschreitung": 2})
        text = benchmark.als_text(e)
        self.assertIn("Still falsch abgelegt: 3 von 40", text)
        self.assertIn("Datum richtig: 36 von 40", text)
        self.assertIn("Satz: digital (9aa3ab59)", text)
        self.assertIn("2 Fehler (Zeitüberschreitung: 2)", text)
        # Läufe vor Schritt 4 (ohne Qualität) zeigen „-“ statt zu scheitern
        self.assertIn("Ordner richtig (sicher): -", benchmark.als_text(self.beispiel()))
        self.assertEqual(benchmark.wert(e, "Zum Prüfen (Rückfrage)"), "6 von 40")


def _zip(pfad, eintraege):
    import zipfile
    with zipfile.ZipFile(pfad, "w") as z:
        for name, inhalt in eintraege:
            z.writestr(name, inhalt)


class TestSatz(unittest.TestCase):
    """Schritt 4 (Peter 22.11.2026): fester Satz aus einem Zip statt erzeugt."""

    def test_eingebauter_satz_ist_der_release_anhang(self):
        # Der eingebaute Satz muss Byte für Byte der Download-Zip sein - sonst wären Läufe mit dem eingebauten und dem
        # heruntergeladenen Satz nicht vergleichbar
        satz = benchmark.eingebauter_satz()
        self.assertTrue(os.path.isfile(satz), satz)
        self.assertEqual(benchmark.pruefsumme(satz), benchmark.SATZ_EINGEBAUT_SUMME)
        self.assertEqual(benchmark.satz_name(satz), "gescannt niedrig")
        ordner, pfade = benchmark.bereite_satz()
        try:
            self.assertEqual([benchmark.nummer(x) for x in pfade], list(range(1, 41)))
        finally:
            benchmark.raeume_satz(ordner)
        self.assertFalse(os.path.exists(ordner))

    def test_zuordnung_ueber_dateinamen_und_nichts_ausserhalb(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = os.path.join(tmp, "eigener.zip")
            _zip(pfad, [("Pruefdokumente/Scan_0002.pdf", b"zwei"), ("Pruefdokumente/LIESMICH.txt", b"x"),
                        ("../../Scan_0001.pdf", b"eins"), ("Scan_0099.pdf", b"zu gross"),
                        ("Pruefdokumente/Pruefdokumente_zum_Drucken.pdf", b"sammel")])
            ordner, pfade = benchmark.bereite_satz(pfad)
            try:
                self.assertEqual([os.path.basename(x) for x in pfade], ["Scan_0001.pdf", "Scan_0002.pdf"])
                self.assertTrue(all(os.path.dirname(x) == ordner for x in pfade))
                with open(pfade[0], "rb") as f:
                    self.assertEqual(f.read(), b"eins")
                self.assertFalse(os.path.exists(os.path.join(tmp, "..", "Scan_0001.pdf")))
            finally:
                benchmark.raeume_satz(ordner)
            self.assertEqual(benchmark.satz_name(pfad), "eigener")
            # Anzeige im Fenster: nur gültige Prüfbriefe zählen (Nr. 99 und die Sammel-PDF nicht)
            self.assertEqual(benchmark.briefe_im_zip(pfad), 2)
            kaputt = os.path.join(tmp, "kaputt.zip")
            with open(kaputt, "wb") as f:
                f.write(b"kein zip")
            self.assertEqual(benchmark.briefe_im_zip(kaputt), 0)
            self.assertEqual(benchmark.briefe_im_zip(os.path.join(tmp, "fehlt.zip")), 0)

    def test_einzelnen_brief_ansehen(self):
        # T21.4 (Peter): Doppelklick in der Liste je Brief öffnet den Brief - aus dem Zip des letzten Laufs
        with tempfile.TemporaryDirectory() as tmp:
            pfad = os.path.join(tmp, "eigener.zip")
            _zip(pfad, [("Pruefdokumente/Scan_0002.pdf", b"zwei"), ("../../Scan_0001.pdf", b"eins")])
            ordner, brief = benchmark.brief_auspacken(pfad, 1)
            try:
                self.assertEqual(os.path.dirname(brief), ordner)
                self.assertEqual(os.path.basename(brief), "Scan_0001.pdf")
                with open(brief, "rb") as f:
                    self.assertEqual(f.read(), b"eins")
            finally:
                benchmark.raeume_satz(ordner)
            self.assertFalse(os.path.exists(ordner))
            self.assertEqual(benchmark.brief_auspacken(pfad, 3), (None, None))
            # welcher Zip gehört zum Lauf: der mit derselben Prüfsumme, fehlende Kandidaten zählen nicht
            lauf = {"pruefsumme": benchmark.pruefsumme(pfad)}
            eingebaut = benchmark.eingebauter_satz()
            self.assertEqual(benchmark.satz_des_laufs(lauf, [eingebaut, os.path.join(tmp, "fehlt.zip"), pfad]), pfad)
            self.assertIsNone(benchmark.satz_des_laufs(lauf, [eingebaut]))
            self.assertIsNone(benchmark.satz_des_laufs({}, [pfad]))   # alter Lauf ohne Prüfsumme

    def test_zip_ohne_pruefbriefe_raeumt_auf(self):
        with tempfile.TemporaryDirectory() as tmp:
            pfad = os.path.join(tmp, "leer.zip")
            _zip(pfad, [("LIESMICH.txt", b"x")])
            vorher = {n for n in os.listdir(tempfile.gettempdir()) if n.startswith("kid_pruefdokumente_")}
            with self.assertRaises(ValueError):
                benchmark.bereite_satz(pfad)
            nachher = {n for n in os.listdir(tempfile.gettempdir()) if n.startswith("kid_pruefdokumente_")}
            self.assertEqual(nachher, vorher)


def _e(ziel, sicher=True, neu=False, datum="", absender=""):
    return {"zielordner": ziel, "sicher": sicher, "ordner_neu": neu, "datum": datum, "absender": absender}


class TestBewerte(unittest.TestCase):
    def test_zaehlung_gegen_die_wahrheit(self):
        w1 = p.wahrheit(1)
        entscheidungen = [
            ("Scan_0001.pdf", _e(w1["ordner"], datum="12.01.2026", absender="Musterversicherung AG")),   # richtig
            ("Scan_0002.pdf", _e("A - B - C - D - E/Autohaus Musterdorf")),                                           # still falsch
            ("Scan_0003.pdf", _e(p.wahrheit(3)["ordner"], sicher=False)),                                 # Rückfrage
            ("Scan_0014.pdf", _e("[0-9]/Neu GmbH", neu=True)),                       # ohne Ordner: neuer richtig
            ("Scan_0021.pdf", _e(w1["ordner"])),                                     # ohne Ordner: vorhandener falsch
            ("Scan_0018.pdf", _e("M - N/Musterfunk", neu=True)),                     # Marke als eigener Ordner
        ]
        z, faelle = benchmark.bewerte(entscheidungen)
        self.assertEqual((z["richtig"], z["pruefen"], z["falsch"]), (3, 1, 2))
        self.assertEqual((z["datum"], z["absender"]), (1, 1))
        self.assertEqual([f["nr"] for f in faelle], [1, 2, 3, 14, 18, 21])
        nr18 = next(f for f in faelle if f["nr"] == 18)
        self.assertEqual(nr18["ergebnis"], "richtig")
        self.assertIn("oder neu: Musterfunk", nr18["erwartet"])
        self.assertEqual(next(f for f in faelle if f["nr"] == 14)["erwartet"], "neuer Ordner")
        # T21.4: ein neu angelegter Ordner ist als solcher zu erkennen - sonst wirkt der falsche Ordner richtiger
        self.assertEqual(benchmark.gewaehlt_text(nr18), "M - N/Musterfunk (neu angelegt)")
        self.assertEqual(benchmark.gewaehlt_text(next(f for f in faelle if f["nr"] == 2)), "A - B - C - D - E/Autohaus Musterdorf")
        self.assertEqual(benchmark.gewaehlt_text(next(f for f in faelle if f["nr"] == 3)), p.wahrheit(3)["ordner"])
        self.assertEqual(benchmark.gewaehlt_text({"gewaehlt": "X/Neu", "ergebnis": "pruefen"}), "X/Neu")  # Rückfrage
        # Brief 26 landet im Ordner, den Brief 6 im selben Lauf angelegt hat: die KI meldet ihn als vorhanden
        # (ordner_neu False), zur Prüfsammlung gehört er trotzdem nicht
        _, faelle = benchmark.bewerte([("Scan_0026.pdf", _e("F - G - H - I - J/Hausarztpraxis am Markt")),
                                       ("Scan_0039.pdf", _e(p.wahrheit(39)["ordner"]))])
        self.assertEqual([benchmark.gewaehlt_text(f) for f in faelle],
                         ["F - G - H - I - J/Hausarztpraxis am Markt (neu angelegt)", p.wahrheit(39)["ordner"]])

    def test_protokoll_nur_nummern_ordner_und_ursachen(self):
        m = {"lesen": [5.0], "lesen_anfang": [20.0], "zweit": [], "zweit_anfang": [], "gesamt": 30.0, "dokumente": 2,
             "fehler": 1, "fehler_liste": [(7, "Lesen", "Zeitüberschreitung")], "abgebrochen": False, "kalt": True,
             "speicher_lesen": None, "speicher_zweit": None,
             "entscheidungen": [("Scan_0002.pdf", _e("A - B - C - D - E/Autohaus Musterdorf"))]}
        e = benchmark.zusammenfassen(m, "lese:9b", "", "Karte", "0.9.37", satz="gescannt niedrig", pruefsumme="ab")
        text = benchmark.protokoll_text(e)
        self.assertIn("Nr. 2 → A - B - C - D - E/Autohaus Musterdorf (richtig: ", text)
        m["entscheidungen"] = [("Scan_0006.pdf", _e("F - G - H - I - J/Hausarztpraxis am Markt", neu=True))]
        e = benchmark.zusammenfassen(m, "lese:9b", "", "Karte", "0.9.37", satz="gescannt niedrig", pruefsumme="ab")
        self.assertIn("Nr. 6 → F - G - H - I - J/Hausarztpraxis am Markt (neu angelegt) (richtig: ",
                      benchmark.protokoll_text(e))
        self.assertIn("Nr. 7 Lesen: Zeitüberschreitung", text)
        self.assertEqual(e["fehler_ursachen"], {"Zeitüberschreitung": 1})


class TestFehlerUrsache(unittest.TestCase):
    def test_ursachen_in_worten(self):
        import urllib.error
        self.assertEqual(benchmark.fehler_ursache(TimeoutError()), "Zeitüberschreitung")
        self.assertEqual(benchmark.fehler_ursache(urllib.error.URLError(TimeoutError())), "Zeitüberschreitung")
        http = urllib.error.HTTPError("u", 500, "x", None, None)
        self.assertEqual(benchmark.fehler_ursache(http), "Serverfehler (HTTP 500)")
        http.close()
        self.assertEqual(benchmark.fehler_ursache(urllib.error.URLError("verweigert")), "Server nicht erreichbar")
        self.assertEqual(benchmark.fehler_ursache(ConnectionError("weg")), "Server nicht erreichbar")
        self.assertEqual(benchmark.fehler_ursache(KeyError("geheim")), "KeyError")   # nie der Text der Ausnahme

    def test_ursachen_text_auch_ohne_ergebnis(self):
        # Scheitern alle Aufrufe, gibt es kein Ergebnis - die Ursache zeigt das Fenster trotzdem (Firmen-Lauf)
        liste = [(1, "Lesen", "Zeitüberschreitung"), (2, "Lesen", "Zeitüberschreitung"),
                 (3, "Zweitmeinung", "Server nicht erreichbar")]
        self.assertEqual(benchmark.ursachen_text(liste), "Zeitüberschreitung: 2, Server nicht erreichbar: 1")
        self.assertEqual(benchmark.ursachen_text([]), "")


if __name__ == "__main__":
    unittest.main()
