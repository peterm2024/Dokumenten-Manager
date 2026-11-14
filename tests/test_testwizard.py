"""Tests für den Test-Wizard (testwizard.py): Konfiguration, Parsen der Checkliste, Fragen-Zerlegung, Rückschreiben."""

import json
import os
import shutil
import tempfile
import unittest

import testwizard

BEISPIEL = """# Manuelle Test-Checkliste

Einleitung.

## 13. Einweg-Tags (09.09.2026)

* [x] **T13.1 Einstellung:** Reiter zeigt die Auswahl? Umstellen bleibt?
* [ ] **T13.2 Erstes Dokument:** Tag steht im Dokument, aber NICHT im Katalog? Log-Zeile „Tag-Warteliste … (1/2)"? (Hinweis in Klammern.) Zweiter Aufruf meldet „nichts zu tun"?
  * Vorbereitung: testzustand.py kaltstart, dann App starten
  * Datei: 0_Unsicher\\Grundriss.pdf
  * Klicks: Dokument markieren → Tools → Vollautomatik → Ablage-Vorschau…
  * ✗ 2026-09-10: Log-Zeile fehlte
* [ ] Punkt ohne Titel?
* [-] **Teilweise:** nur halb geprüft?
* [?] **Unklar:** Ergebnis unklar?

## 14. Eigenbelege (11.09.2026)

* [ ] **Wink:** Zeile gelb?
"""


class TestParseCheckliste(unittest.TestCase):
    def test_abschnitte_und_punkte(self):
        abschnitte = testwizard.parse_checkliste(BEISPIEL)
        self.assertEqual([a["titel"] for a in abschnitte], ["13. Einweg-Tags (09.09.2026)", "14. Eigenbelege (11.09.2026)"])
        punkte = abschnitte[0]["punkte"]
        self.assertEqual([p["titel"] for p in punkte], ["Einstellung", "Erstes Dokument", "", "Teilweise", "Unklar"])
        # feste Kennung wird vom Titel getrennt; Punkte ohne Kennung bekommen ""
        self.assertEqual([p["id"] for p in punkte], ["T13.1", "T13.2", "", "", ""])
        # [-] und [?] (teilweise/unklar) zählen als offen
        self.assertEqual([p["erledigt"] for p in punkte], [True, False, False, False, False])
        self.assertEqual(punkte[0]["zeile"], 6)
        self.assertEqual(punkte[2]["text"], "Punkt ohne Titel?")
        self.assertEqual(abschnitte[1]["punkte"][0]["titel"], "Wink")

    def test_unterpunkte_werden_feldern_zugeordnet(self):
        p = testwizard.parse_checkliste(BEISPIEL)[0]["punkte"][1]
        self.assertEqual(p["vorbereitung"], "testzustand.py kaltstart, dann App starten")
        self.assertEqual(p["datei"], "0_Unsicher\\Grundriss.pdf")
        self.assertEqual(p["klicks"], "Dokument markieren → Tools → Vollautomatik → Ablage-Vorschau…")
        self.assertEqual(p["fehlnotizen"], [("2026-09-10", "Log-Zeile fehlte")])
        self.assertEqual(p["letzte_zeile"], p["zeile"] + 4)
        self.assertTrue(p["text"].startswith("Tag steht im Dokument"))

    def test_heute_fehlgeschlagen(self):
        punkte = testwizard.parse_checkliste(BEISPIEL)[0]["punkte"]
        self.assertTrue(testwizard.heute_fehlgeschlagen(punkte[1], heute="2026-09-10"))
        self.assertFalse(testwizard.heute_fehlgeschlagen(punkte[1], heute="2026-09-11"))  # Notiz von gestern zählt nicht
        self.assertFalse(testwizard.heute_fehlgeschlagen(punkte[0], heute="2026-09-10"))

    def test_frage_liste(self):
        fragen = testwizard.frage_liste(testwizard.parse_checkliste(BEISPIEL)[0]["punkte"][1]["text"])
        self.assertEqual(fragen, ["Tag steht im Dokument, aber NICHT im Katalog?",
                                  "Log-Zeile „Tag-Warteliste … (1/2)\"?",
                                  "(Hinweis in Klammern.) Zweiter Aufruf meldet „nichts zu tun\"?"])
        self.assertEqual(testwizard.frage_liste("Nur ein Satz ohne Fragezeichen"), ["Nur ein Satz ohne Fragezeichen"])
        self.assertEqual(testwizard.frage_liste(""), [])


class TestFehlnotizText(unittest.TestCase):
    """Die Fragen-Tabelle des Wizards (Haken + Notiz je Frage) wird zu EINER Fehlnotiz-Zeile."""

    def test_mehrere_fragen_mit_haken_und_notizen(self):
        zeilen = [(True, ""), (False, "Tooltip  fehlt\nganz"), (True, "")]
        self.assertEqual(testwizard.fehlnotiz_text(zeilen, "Fenster flackert"),
                         "1 ✓; 2 ✗ Tooltip fehlt ganz; 3 ✓ — Fenster flackert")
        self.assertEqual(testwizard.fehlnotiz_text(zeilen), "1 ✓; 2 ✗ Tooltip fehlt ganz; 3 ✓")

    def test_eine_frage_ohne_nummerierung(self):
        self.assertEqual(testwizard.fehlnotiz_text([(False, "kaputt")], ""), "kaputt")
        self.assertEqual(testwizard.fehlnotiz_text([(False, "kaputt")], "allgemein"), "kaputt — allgemein")
        self.assertEqual(testwizard.fehlnotiz_text([(False, "")], "nur allgemein"), "nur allgemein")
        self.assertEqual(testwizard.fehlnotiz_text([], "nur allgemein"), "nur allgemein")

    def test_ergebnis_landet_als_fehlnotiz_in_der_checkliste(self):
        p = testwizard.parse_checkliste(BEISPIEL)[0]["punkte"][0]
        notiz = testwizard.fehlnotiz_text([(True, ""), (False, "sprang zurück")], "")
        neu = testwizard.markiere(BEISPIEL, p["zeile"], False, notiz, datum="2026-09-17")
        punkt = testwizard.parse_checkliste(neu)[0]["punkte"][0]
        self.assertEqual(punkt["fehlnotizen"], [("2026-09-17", "1 ✓; 2 ✗ sprang zurück")])

    def test_parsen_ist_umkehrung(self):
        zeilen = [(True, ""), (False, "Tooltip fehlt; wirklich"), (False, "")]
        text = testwizard.fehlnotiz_text(zeilen, "Fenster — flackert")
        self.assertEqual(testwizard.fehlnotiz_parsen(text, 3), (zeilen, "Fenster — flackert"))
        self.assertEqual(testwizard.fehlnotiz_parsen("1 ✓; 2 ✗ kaputt", 2), ([(True, ""), (False, "kaputt")], ""))
        self.assertEqual(testwizard.fehlnotiz_parsen("kaputt — allgemein", 1), ([(False, "kaputt")], "allgemein"))

    def test_parsen_lehnt_fremdes_format_ab(self):
        self.assertIsNone(testwizard.fehlnotiz_parsen("1. Teilweise 2. Ja Scrollleiste fehlt", 2))
        self.assertIsNone(testwizard.fehlnotiz_parsen("1 ✓; 2 ✗ kaputt", 3))   # Fragenzahl passt nicht
        self.assertIsNone(testwizard.fehlnotiz_parsen("1 ✓; 3 ✗ kaputt", 2))   # Lücke in der Nummerierung
        self.assertIsNone(testwizard.fehlnotiz_parsen("1 ✓; 2 ✗ kaputt", 1))   # eine Frage, aber nummeriert


class TestNotizenUndIdeen(unittest.TestCase):
    """📝-Notizen und 💡-Ideen: unabhängig vom Ergebnis, als Unterpunkte unter dem Prüfpunkt."""

    def test_notiz_text_nur_fragen_mit_notiz(self):
        self.assertEqual(testwizard.notiz_text(["", "Tooltip  verzögert", ""], "später\nansehen"),
                         "2: Tooltip verzögert — später ansehen")
        self.assertEqual(testwizard.notiz_text(["nur eine Frage"], ""), "nur eine Frage")
        self.assertEqual(testwizard.notiz_text(["", ""], ""), "")
        self.assertEqual(testwizard.notiz_text([], "allgemein"), "allgemein")

    def test_einfuegen_und_parsen(self):
        p = testwizard.parse_checkliste(BEISPIEL)[0]["punkte"][0]   # T13.1, abgehakt
        neu = testwizard.fuege_notiz_ein(BEISPIEL, p["zeile"], "Knopf  sitzt tief", datum="2026-10-24")
        neu = testwizard.fuege_notiz_ein(neu, p["zeile"], "Auswahl merken", testwizard.IDEE, datum="2026-10-25")
        punkt = testwizard.parse_checkliste(neu)[0]["punkte"][0]
        self.assertTrue(punkt["erledigt"])                 # Ergebnis bleibt unberührt
        self.assertEqual(punkt["notizen"], [("💡", "2026-10-25", "Auswahl merken"),
                                            ("📝", "2026-10-24", "Knopf sitzt tief")])  # neueste zuerst
        self.assertEqual(punkt["fehlnotizen"], [])
        self.assertFalse(testwizard.heute_fehlgeschlagen(punkt, heute="2026-10-25"))  # Notiz ist kein Befund

    def test_leere_notiz_aendert_nichts(self):
        self.assertEqual(testwizard.fuege_notiz_ein(BEISPIEL, 6, "  "), BEISPIEL)

    def test_einfuegen_findet_verschobenen_punkt_und_lehnt_fremde_art_ab(self):
        p = testwizard.parse_checkliste(BEISPIEL)[0]["punkte"][1]  # T13.2
        verschoben = BEISPIEL.replace("## 13.", "Neue Zeile\n\n## 13.")
        neu = testwizard.fuege_notiz_ein(verschoben, p["zeile"], "Idee", testwizard.IDEE, datum="2026-10-25",
                                         kennung="T13.2")
        self.assertIn("**T13.2 Erstes Dokument:**", neu.split("  * 💡 2026-10-25: Idee")[0].splitlines()[-1])
        with self.assertRaises(ValueError):
            testwizard.fuege_notiz_ein(BEISPIEL, p["zeile"], "x", "✗")

    def test_notizen_und_fehlnotizen_nebeneinander(self):
        p = testwizard.parse_checkliste(BEISPIEL)[0]["punkte"][1]  # T13.2 hat schon eine Fehlnotiz
        neu = testwizard.fuege_notiz_ein(BEISPIEL, p["zeile"], "Log liegt woanders", datum="2026-10-25")
        punkt = testwizard.parse_checkliste(neu)[0]["punkte"][1]
        self.assertEqual(punkt["fehlnotizen"], [("2026-09-10", "Log-Zeile fehlte")])
        self.assertEqual(punkt["notizen"], [("📝", "2026-10-25", "Log liegt woanders")])
        self.assertEqual(punkt["klicks"], "Dokument markieren → Tools → Vollautomatik → Ablage-Vorschau…")


class TestHakenZuruecksetzen(unittest.TestCase):
    """Rechtsklick auf einen Abschnitt: alle Haken nur dieses Abschnitts zurück auf offen."""

    def test_nur_der_eigene_abschnitt(self):
        text = BEISPIEL.replace("* [ ] **Wink:**", "* [x] **Wink:**")
        abschnitte = testwizard.parse_checkliste(text)
        neu, anzahl = testwizard.haken_zuruecksetzen(text, abschnitte[0]["zeile"])
        self.assertEqual(anzahl, 1)                       # nur T13.1 war in Abschnitt 13 abgehakt
        neue = testwizard.parse_checkliste(neu)
        self.assertFalse(any(p["erledigt"] for p in neue[0]["punkte"]))
        self.assertTrue(neue[1]["punkte"][0]["erledigt"])  # Abschnitt 14 unberührt
        self.assertEqual(neue[0]["punkte"][1]["fehlnotizen"], [("2026-09-10", "Log-Zeile fehlte")])  # Befund bleibt
        self.assertEqual(neue[0]["punkte"][3]["titel"], "Teilweise")  # [-] bleibt, wie es ist
        self.assertIn("* [-] **Teilweise:**", neu)

    def test_zeilenenden_und_fehler(self):
        crlf = BEISPIEL.replace("\n", "\r\n")
        neu, anzahl = testwizard.haken_zuruecksetzen(crlf, testwizard.parse_checkliste(crlf)[0]["zeile"])
        self.assertEqual(anzahl, 1)
        self.assertNotIn("\n", neu.replace("\r\n", ""))
        with self.assertRaises(ValueError):
            testwizard.haken_zuruecksetzen(BEISPIEL, 0)   # Zeile 0 ist keine Abschnitts-Überschrift


class TestMarkiere(unittest.TestCase):
    def test_bestanden_setzt_haken(self):
        abschnitte = testwizard.parse_checkliste(BEISPIEL)
        p = abschnitte[0]["punkte"][1]
        neu = testwizard.markiere(BEISPIEL, p["zeile"], True)
        self.assertIn("* [x] **T13.2 Erstes Dokument:**", neu)
        self.assertEqual(len(neu.splitlines()), len(BEISPIEL.splitlines()))
        self.assertTrue(testwizard.parse_checkliste(neu)[0]["punkte"][1]["erledigt"])

    def test_fehlgeschlagen_schreibt_notiz_und_nimmt_haken_weg(self):
        abschnitte = testwizard.parse_checkliste(BEISPIEL)
        p = abschnitte[0]["punkte"][0]  # war [x]
        neu = testwizard.markiere(BEISPIEL, p["zeile"], False, "Auswahl  sprang\nzurück", datum="2026-09-11")
        zeilen = neu.splitlines()
        self.assertTrue(zeilen[p["zeile"]].startswith("* [ ] **T13.1 Einstellung:**"))
        self.assertEqual(zeilen[p["zeile"] + 1], "  * ✗ 2026-09-11: Auswahl sprang zurück")
        punkt = testwizard.parse_checkliste(neu)[0]["punkte"][0]
        self.assertFalse(punkt["erledigt"])
        self.assertEqual(punkt["fehlnotizen"], [("2026-09-11", "Auswahl sprang zurück")])

    def test_zeilenenden_bleiben(self):
        crlf = BEISPIEL.replace("\n", "\r\n")
        p = testwizard.parse_checkliste(crlf)[1]["punkte"][0]
        neu = testwizard.markiere(crlf, p["zeile"], False, "kaputt", datum="2026-09-11")
        self.assertNotIn("\n", neu.replace("\r\n", ""))
        self.assertIn("* [ ] **Wink:** Zeile gelb?\r\n  * ✗ 2026-09-11: kaputt\r\n", neu)

    def test_falsche_zeile_wird_abgelehnt(self):
        with self.assertRaises(ValueError):
            testwizard.markiere(BEISPIEL, 0, True)

    def test_kennung_findet_verschobenen_punkt(self):
        # Zwischen Einlesen und Abhaken wurden oben Zeilen eingefügt (Editor/Claude) -
        # die alte Zeilennummer zeigt jetzt auf einen anderen Punkt bzw. ins Leere
        p = testwizard.parse_checkliste(BEISPIEL)[0]["punkte"][1]  # T13.2
        verschoben = BEISPIEL.replace("## 13.", "Neue Zeile\nNoch eine\n\n## 13.")
        neu = testwizard.markiere(verschoben, p["zeile"], True, kennung="T13.2")
        self.assertIn("* [x] **T13.2 Erstes Dokument:**", neu)
        self.assertIn("* [x] **T13.1 Einstellung:**", neu)  # der Nachbar blieb unberührt
        with self.assertRaises(ValueError):
            testwizard.markiere(verschoben, p["zeile"], True, kennung="T99.9")


class TestKonfiguration(unittest.TestCase):
    """testwizard.json neben der Checkliste steuert Checkliste, Testordner, App-Knopf und Fenstertitel."""

    def setUp(self):
        self.ordner = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.ordner, ignore_errors=True)
        # Modul-Einstellungen nach jedem Test auf den Ausgangszustand zurücksetzen
        merker = {n: getattr(testwizard, n) for n in ("PROJEKT", "CHECKLISTE", "TESTORDNER", "APP_START", "APP_KNOPF", "TITEL")}
        self.addCleanup(lambda: [setattr(testwizard, n, w) for n, w in merker.items()])

    def _schreibe(self, konfig):
        with open(os.path.join(self.ordner, testwizard.KONFIG_DATEI), "w", encoding="utf-8") as f:
            json.dump(konfig, f)

    def test_ohne_datei_gelten_die_standardwerte(self):
        self.assertEqual(testwizard.lade_konfiguration(self.ordner), {})
        self.assertEqual(testwizard.CHECKLISTE, os.path.join(self.ordner, testwizard.STANDARD_CHECKLISTE))
        self.assertEqual(testwizard.TESTORDNER, "")   # kein Knopf "Testordner im Explorer"
        self.assertEqual(testwizard.APP_START, [])    # kein Knopf "App starten"
        self.assertEqual(testwizard.TITEL, testwizard.STANDARD_TITEL)

    def test_werte_aus_der_datei(self):
        self._schreibe({"checkliste": "UI-Tests.md", "testordner": "C:/Testdaten/App",
                        "app_start": ["python", "main.py"], "app_knopf": "Start", "titel": "MeinApp"})
        testwizard.lade_konfiguration(self.ordner)
        self.assertEqual(testwizard.CHECKLISTE, os.path.join(self.ordner, "UI-Tests.md"))
        self.assertEqual(testwizard.TESTORDNER, "C:/Testdaten/App")   # absoluter Pfad bleibt, wie er ist
        self.assertEqual(testwizard.APP_START, ["python", "main.py"])
        self.assertEqual(testwizard.APP_KNOPF, "Start")
        self.assertEqual(testwizard.TITEL, "MeinApp")

    def test_relativer_testordner_gilt_ab_projektordner(self):
        self._schreibe({"testordner": "testdaten", "app_start": "meinapp.exe"})
        testwizard.lade_konfiguration(self.ordner)
        self.assertEqual(testwizard.TESTORDNER, os.path.join(self.ordner, "testdaten"))
        self.assertEqual(testwizard.APP_START, ["meinapp.exe"])  # String wird zur Ein-Element-Liste

    def test_kommandozeile_schlaegt_konfiguration(self):
        self._schreibe({"checkliste": "UI-Tests.md"})
        testwizard.lade_konfiguration(self.ordner, checkliste="Regression.md")
        self.assertEqual(testwizard.CHECKLISTE, os.path.join(self.ordner, "Regression.md"))

    def test_lesen_und_schreiben_folgen_der_konfiguration(self):
        ziel = os.path.join(self.ordner, "UI-Tests.md")
        with open(ziel, "w", encoding="utf-8", newline="") as f:
            f.write(BEISPIEL)
        self._schreibe({"checkliste": "UI-Tests.md"})
        testwizard.lade_konfiguration(self.ordner)
        p = testwizard.parse_checkliste(testwizard.lade())[0]["punkte"][1]
        testwizard.speichere(testwizard.markiere(testwizard.lade(), p["zeile"], True, kennung="T13.2"))
        with open(ziel, encoding="utf-8", newline="") as f:
            self.assertIn("* [x] **T13.2 Erstes Dokument:**", f.read())


if __name__ == "__main__":
    unittest.main()
