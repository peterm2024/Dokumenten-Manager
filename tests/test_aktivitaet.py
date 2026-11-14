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


if __name__ == "__main__":
    unittest.main()
