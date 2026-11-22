"""Tests für die Aktivitätsanzeige (aktivitaet.py) - mit Attrappen statt echtem Tk."""
import threading
import unittest

import aktivitaet


class FakeMenubar:
    """Leiste wie in der App: Kaskaden + genau ein Kommando-Eintrag (die Anzeige) am Ende."""

    def __init__(self):
        self.eintraege = [("cascade", "Datei"), ("cascade", "Ansicht"), ("cascade", "Hilfe"), ("command", "Bereit")]

    def index(self, was):
        return len(self.eintraege) - 1 if was == "end" else was

    def type(self, index):
        return self.eintraege[index][0]

    def entryconfigure(self, index, label=None):
        self.eintraege[index] = (self.eintraege[index][0], label)

    def entrycget(self, index, option):
        return self.eintraege[index][1]

    def insert_cascade(self, index, label):
        self.eintraege.insert(index, ("cascade", label))


class FakeRoot:
    """after() sammelt Aufträge, statt sie zu planen; update_idletasks zählt Atemzüge."""

    def __init__(self):
        self.auftraege = []
        self.atemzuege = 0
        self._nr = 0

    def after(self, ms, fn=None, *args):
        self._nr += 1
        self.auftraege.append((ms, fn, args))
        return self._nr

    def after_cancel(self, job):
        self.auftraege = [a for a in self.auftraege if a is not job]

    def update_idletasks(self):
        self.atemzuege += 1


class TestOhneAnzeige(unittest.TestCase):
    def setUp(self):
        aktivitaet.registriere(None)

    def test_alles_wirkungslos(self):
        token = aktivitaet.beginne("x")
        aktivitaet.aktualisiere(token, "y")
        aktivitaet.beende(token)
        aktivitaet.atme()
        with aktivitaet.phase("p") as p:
            p.melde("q")
        with aktivitaet.warte_auf_antwort("Titel"):
            pass
        with self.assertLogs("DocManager", "INFO") as log:
            aktivitaet.erledigt("Ordnerstruktur angelegt")
        self.assertIn("Ordnerstruktur angelegt", log.output[0])


class TestAnzeige(unittest.TestCase):
    def setUp(self):
        self.root = FakeRoot()
        self.menu = FakeMenubar()
        self.anzeige = aktivitaet.Anzeige(self.root, self.menu, 3)
        aktivitaet.registriere(self.anzeige)

    def tearDown(self):
        aktivitaet.registriere(None)

    def test_eintrag_wird_nach_einfuegen_davor_wiedergefunden(self):
        """Der ToolManager schiebt „Tools" vor „Hilfe" - die Anzeige darf danach nicht auf „Hilfe" schreiben."""
        self.menu.insert_cascade(2, "Tools")
        with aktivitaet.phase("Lese Ordner…"):
            self.assertEqual(self.menu.eintraege[3], ("cascade", "Hilfe"))
            self.assertIn("Lese Ordner", self.menu.eintraege[4][1])
            self.assertEqual(self.menu.eintraege[4][0], "command")
        self.assertEqual(self.menu.eintraege[4], ("command", "Bereit"))
        self.assertEqual(self.menu.eintraege[3], ("cascade", "Hilfe"))

    def test_ruhe_text_am_anfang(self):
        self.assertEqual(self.anzeige.aktueller_text(), "Bereit")
        self.assertFalse(self.anzeige.laeuft())

    def test_phase_zeigt_text_und_kehrt_zu_bereit_zurueck(self):
        with aktivitaet.phase("Lese Ordner…") as p:
            self.assertIn("Lese Ordner…", self.anzeige.aktueller_text())
            self.assertTrue(self.anzeige.laeuft())
            p.melde("Lese Ordner 5/80…")
            self.assertIn("5/80", self.anzeige.aktueller_text())
        self.assertEqual(self.anzeige.aktueller_text(), "Bereit")
        self.assertFalse(self.anzeige.laeuft())

    def test_verschachtelt_zeigt_die_innerste(self):
        aussen = aktivitaet.beginne("Suche läuft…")
        innen = aktivitaet.beginne("Suche: neue Dokumente einlesen 1/3…")
        self.assertIn("1/3", self.anzeige.aktueller_text())
        aktivitaet.beende(innen)
        self.assertIn("Suche läuft", self.anzeige.aktueller_text())
        aktivitaet.beende(aussen)
        self.assertEqual(self.anzeige.aktueller_text(), "Bereit")

    def test_ki_verdeckt_nicht_die_aufgabe(self):
        # Peter 06.11.2026: Die Menüleiste sagte nur „KI antwortet“, nicht wofür
        with aktivitaet.phase("Vollautomatik liest 3 von 120: a.pdf…"):
            with aktivitaet.phase("KI antwortet (m)…", nebensache=True):
                text = self.anzeige.aktueller_text()
                self.assertIn("Vollautomatik liest 3 von 120: a.pdf", text)
                self.assertNotIn("KI antwortet", text)

    def test_ki_allein_steht_fuer_sich(self):
        with aktivitaet.phase("KI antwortet (m)…", nebensache=True):
            self.assertIn("KI antwortet (m)", self.anzeige.aktueller_text())

    def test_neue_aufgabe_nach_der_ki_bleibt_sichtbar(self):
        ki = aktivitaet.beginne("KI antwortet (m)…", nebensache=True)
        with aktivitaet.phase("Lese Ordner…"):
            self.assertIn("Lese Ordner", self.anzeige.aktueller_text())
        aktivitaet.beende(ki)

    def test_kurz(self):
        self.assertEqual(aktivitaet.kurz("kurz.pdf"), "kurz.pdf")
        lang = aktivitaet.kurz("x" * 100)
        self.assertEqual(len(lang), 40)
        # Die Auslassungspunkte setzt der Aufrufer ans Ende der Phase, sonst stand „Stromvertr……“ in der Menüleiste
        self.assertFalse(lang.endswith("…"))

    def test_warte_auf_antwort(self):
        with aktivitaet.warte_auf_antwort("Datei umbenennen"):
            self.assertIn("Wartet auf deine Antwort", self.anzeige.aktueller_text())
            self.assertIn("Datei umbenennen", self.anzeige.aktueller_text())

    def test_phasenstart_zeichnet_sofort(self):
        """Vor einer synchronen Phase muss der Text auf den Schirm: update_idletasks ungedrosselt."""
        vorher = self.root.atemzuege
        aktivitaet.beginne("a")
        aktivitaet.beginne("b")
        self.assertEqual(self.root.atemzuege, vorher + 2)

    def test_atme_ist_gedrosselt(self):
        vorher = self.root.atemzuege
        aktivitaet.atme()
        aktivitaet.atme()
        aktivitaet.atme()
        self.assertEqual(self.root.atemzuege, vorher + 1)

    def test_tick_zeigt_dauer_nach_schwelle(self):
        token = aktivitaet.beginne("KI antwortet…")
        self.anzeige._phasen[0][2] -= 10   # Startzeit 10 s zurückdrehen
        self.anzeige._tick()
        self.assertRegex(self.anzeige.aktueller_text(), r"\(1\d s\)")
        aktivitaet.beende(token)

    def test_aus_fremdem_thread_geht_ueber_after(self):
        ergebnis = {}

        def im_thread():
            ergebnis["token"] = aktivitaet.beginne("aus Thread")

        t = threading.Thread(target=im_thread)
        t.start()
        t.join()
        # Noch nicht sichtbar (nur geplant) ...
        self.assertEqual(self.anzeige.aktueller_text(), "Bereit")
        geplant = [a for a in self.root.auftraege if a[0] == 0]
        self.assertTrue(geplant)
        # ... bis der Tk-Thread den Auftrag ausführt
        for _ms, fn, args in geplant:
            fn(*args)
        self.assertIn("aus Thread", self.anzeige.aktueller_text())
        aktivitaet.beende(ergebnis["token"])


class TestErledigt(unittest.TestCase):
    """A2 (Peter 21.11.2026): reine Erfolgsmeldungen ohne Fenster - kurz in der Leiste, dazu im Log."""

    def setUp(self):
        self.root = FakeRoot()
        self.anzeige = aktivitaet.Anzeige(self.root, FakeMenubar(), 3)
        aktivitaet.registriere(self.anzeige)
        self.addCleanup(aktivitaet.registriere, None)

    def _ablaufen(self):
        """Führt die geplanten Abräum-Aufträge aus (FakeRoot plant nur)."""
        auftraege, self.root.auftraege = self.root.auftraege, []
        for _ms, fn, args in auftraege:
            if fn is not None and getattr(fn, "__name__", "") == "_erledigt_weg":
                fn(*args)

    def test_zeigt_haken_ohne_spinner_und_verschwindet(self):
        with self.assertLogs("DocManager", "INFO") as log:
            aktivitaet.erledigt("3 Titel geschrieben")
        self.assertEqual(self.anzeige.aktueller_text(), "✓ 3 Titel geschrieben")
        self.assertIn("3 Titel geschrieben", log.output[0])
        self.assertFalse(self.anzeige.laeuft())
        self._ablaufen()
        self.assertEqual(self.anzeige.aktueller_text(), "Bereit")

    def test_laufende_phase_hat_vorrang(self):
        aktivitaet.erledigt("gespeichert")
        with aktivitaet.phase("Lese Ordner…"):
            self.assertIn("Lese Ordner…", self.anzeige.aktueller_text())
        self.assertEqual(self.anzeige.aktueller_text(), "✓ gespeichert")

    def test_auffaelliges_feld_bekommt_text_und_dauer(self):
        gezeigt = []
        self.anzeige.erfolg_feld = lambda text, ms: gezeigt.append((text, ms))
        aktivitaet.erledigt("Ordnerstruktur angelegt")
        self.assertEqual(gezeigt, [("Ordnerstruktur angelegt", aktivitaet.ERLEDIGT_MS)])

    def test_fehler_im_feld_stoert_nicht(self):
        def kaputt(text, ms):
            raise RuntimeError("Fenster schon weg")
        self.anzeige.erfolg_feld = kaputt
        aktivitaet.erledigt("gespeichert")
        self.assertEqual(self.anzeige.aktueller_text(), "✓ gespeichert")

    def test_neuere_meldung_behaelt_ihre_zeit(self):
        aktivitaet.erledigt("erste")
        erster = list(self.root.auftraege)
        aktivitaet.erledigt("zweite")
        for _ms, fn, args in erster:
            fn(*args)                 # die Zeit der ersten läuft ab ...
        self.assertEqual(self.anzeige.aktueller_text(), "✓ zweite")   # ... die zweite bleibt stehen


class TestKeineErfolgsfenster(unittest.TestCase):
    """Wächter zu A2: kein Meldungsfenster, das nur Erfolg bestätigt - dafür gibt es aktivitaet.erledigt."""

    ERFOLGSTITEL = {"Erfolg", "Erledigt", "Fertig", "Übernommen", "Zurückgesetzt", "Gespeichert"}

    def test_kein_showinfo_mit_erfolgstitel(self):
        import ast
        import os
        src = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
        funde = []
        for ordner, _unter, dateien in os.walk(src):
            for name in dateien:
                if not name.endswith(".py"):
                    continue
                pfad = os.path.join(ordner, name)
                with open(pfad, encoding="utf-8") as f:
                    baum = ast.parse(f.read())
                for knoten in ast.walk(baum):
                    if (isinstance(knoten, ast.Call) and isinstance(knoten.func, ast.Attribute)
                            and knoten.func.attr == "showinfo" and knoten.args
                            and isinstance(knoten.args[0], ast.Constant)
                            and knoten.args[0].value in self.ERFOLGSTITEL):
                        funde.append(f"{os.path.relpath(pfad, src)}:{knoten.lineno} „{knoten.args[0].value}“")
        self.assertEqual(funde, [], "Erfolg ohne Fenster melden: aktivitaet.erledigt(text)")


if __name__ == "__main__":
    unittest.main()
