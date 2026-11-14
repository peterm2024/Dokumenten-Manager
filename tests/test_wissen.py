"""Wiki von Hand, neuer Aufbau (KONZEPT_WIKI_VON_HAND.md, Schritt N2): Speicher mit Schubladen, freien Angaben, Belegen
und Verbindungen. Nur Musterdaten."""
import os
import shutil
import sqlite3
import tempfile
import threading
import unittest

import app_paths
import wissen


class TestWissen(unittest.TestCase):
    def setUp(self):
        self.basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.basis, True)
        self.sammlung = os.path.join(self.basis, "Sammlung")
        os.makedirs(self.sammlung)
        self.w = wissen.Wissen(self.sammlung)

    def art(self, name):
        return next(a["id"] or a["name"] for a in self.w.arten() if a["name"] == name)   # ohne Datei: der Name

    def test_lesen_legt_keine_datei_an(self):
        self.assertEqual(self.w.pfad, os.path.join(app_paths.data_dir(self.sammlung), "wissen.sqlite"))
        self.assertEqual((self.w.liste(), self.w.anzahl(), self.w.lade(1), self.w.eintraege_mit_beleg(["AAAA-0001"])),
                         ([], 0, None, []))
        self.assertEqual([(a["id"], a["name"]) for a in self.w.arten()], [(None, n) for n in wissen.START_ARTEN])
        self.assertFalse(self.w.sichere())
        self.assertFalse(os.path.exists(self.w.pfad))

    def test_anlegen_laden_aendern_loeschen(self):
        firma = self.w.art_neu("firma")                                      # gibt es schon: dieselbe Schublade
        self.assertEqual(firma, self.art("Firma"))
        with self.assertRaises(wissen.Eingabefehler):
            self.w.speichere(firma, "   ")
        with self.assertRaises(wissen.Eingabefehler):
            self.w.speichere(9999, "Muster GmbH")
        with self.assertRaises(wissen.Eingabefehler):
            self.w.speichere("  ", "Muster GmbH")
        e = self.w.speichere(firma, "  Muster   GmbH ", " Hausverwaltung\n")
        d = self.w.lade(e)
        self.assertEqual((d["bezeichnung"], d["notiz"], d["art_name"], d["geprueft"]),
                         ("Muster GmbH", "Hausverwaltung", "Firma", ""))
        self.assertEqual((d["angaben"], d["belege"], d["verbunden"]), ([], [], []))
        self.assertEqual(self.w.gleichnamige(firma, "muster  gmbh"), [e])
        self.assertEqual(self.w.gleichnamige(firma, "muster gmbh", ausser=e), [])
        self.assertEqual(self.w.gleichnamige(self.art("Person"), "Muster GmbH"), [])
        # ändern: auch die Schublade; Angaben und Belege bleiben
        self.w.angabe_hinzu(e, "Telefon: 01234 56789")
        self.w.beleg_hinzu(e, "AAAA-0001", "Rechnung")
        self.assertEqual(self.w.speichere(self.art("Behörde"), "Musteramt", eintrag_id=e), e)
        d = self.w.lade(e)
        self.assertEqual((d["bezeichnung"], d["art_name"], d["notiz"], len(d["angaben"]), len(d["belege"])),
                         ("Musteramt", "Behörde", "", 1, 1))
        with self.assertRaises(wissen.Eingabefehler):
            self.w.speichere(firma, "Weg", eintrag_id=777)
        self.w.loesche(e)
        self.assertEqual((self.w.lade(e), self.w.anzahl()), (None, 0))
        con = sqlite3.connect(self.w.pfad)
        self.addCleanup(con.close)
        self.assertEqual([con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("angabe", "beleg")], [0, 0])

    def test_liste_in_reihenfolge_der_schubladen(self):
        self.w.speichere(self.art("Fahrzeug"), "VW Golf")
        self.w.speichere(self.art("Person"), "Max Mustermann")
        self.w.speichere(self.art("Person"), "erika Musterfrau")
        neu = self.w.art_neu("  Gerät ")
        self.w.speichere(neu, "Geschirrspüler")
        self.assertEqual([(e["art_name"], e["bezeichnung"]) for e in self.w.liste()],
                         [("Person", "erika Musterfrau"), ("Person", "Max Mustermann"), ("Fahrzeug", "VW Golf"),
                          ("Gerät", "Geschirrspüler")])
        self.assertEqual([(a["name"], a["anzahl"]) for a in self.w.arten() if a["anzahl"]],
                         [("Person", 2), ("Fahrzeug", 1), ("Gerät", 1)])
        self.assertEqual(self.w.arten()[-1]["name"], "Gerät")                # neue Schublade am Ende
        self.assertEqual(self.w.anzahl(), 4)

    def test_schubladen_umbenennen_und_zusammenlegen(self):
        handwerker, dienst = self.w.art_neu("Handwerker"), self.w.art_neu("Dienstleister")
        a = self.w.speichere(handwerker, "Muster Sanitär")
        b = self.w.speichere(dienst, "Muster Reinigung")
        with self.assertRaises(wissen.Eingabefehler):
            self.w.art_neu(" ")
        with self.assertRaises(wissen.Eingabefehler):
            self.w.art_umbenennen(dienst, "handwerker")                      # gibt es schon: zusammenlegen
        self.w.art_umbenennen(handwerker, "HANDWERKER")                      # nur die Schreibweise: erlaubt
        self.w.art_umbenennen(dienst, "Dienste")
        self.assertEqual(self.w.lade(b)["art_name"], "Dienste")
        self.assertEqual(self.w.arten_zusammenlegen(dienst, handwerker), 1)
        self.assertEqual({self.w.lade(i)["art_name"] for i in (a, b)}, {"HANDWERKER"})
        self.assertNotIn("Dienste", [x["name"] for x in self.w.arten()])
        self.assertEqual(self.w.arten_zusammenlegen(handwerker, handwerker), 0)
        with self.assertRaises(wissen.Eingabefehler):
            self.w.arten_zusammenlegen(dienst, handwerker)                   # die Quelle gibt es nicht mehr
        self.assertEqual(self.w.anzahl(), 2)                                 # nichts verloren
        with self.assertRaises(wissen.Eingabefehler):
            self.w.art_loeschen(handwerker)                                  # nicht leer: bleibt
        self.assertEqual(self.w.anzahl(), 2)
        leer = self.w.art_neu("Leer")
        self.w.art_loeschen(leer)
        self.assertNotIn("Leer", [x["name"] for x in self.w.arten()])
        for x in self.w.arten():                                             # alle leeren weg - die letzte bleibt
            if not x["anzahl"]:
                self.w.art_loeschen(x["id"])
        self.w.loesche(a)
        self.w.loesche(b)
        with self.assertRaises(wissen.Eingabefehler):
            self.w.art_loeschen(handwerker)
        self.assertEqual([x["name"] for x in self.w.arten()], ["HANDWERKER"])

    def test_angaben_mit_und_ohne_dokument(self):
        e = self.w.speichere(self.art("Immobilie"), "Haus Musterstraße 1")
        hand = self.w.angabe_hinzu(e, "  Baujahr   1975 ")
        ki = self.w.angabe_hinzu(e, "Feuerlöscher geprüft am 19.02.2016", "AAAA-0001", "Rechnung Prüfdienst",
                                 "Prüf-/Lieferdatum:  19.02.2016")
        self.assertIsNone(self.w.angabe_hinzu(e, "baujahr 1975"))            # steht schon da
        with self.assertRaises(wissen.Eingabefehler):
            self.w.angabe_hinzu(e, "  ")
        with self.assertRaises(wissen.Eingabefehler):
            self.w.angabe_hinzu(e, "x" * (wissen.MAX_ANGABE + 1))
        with self.assertRaises(wissen.Eingabefehler):
            self.w.angabe_hinzu(e, "Zitat ohne Dokument", zitat="irgendwo")
        with self.assertRaises(wissen.Eingabefehler):
            self.w.angabe_hinzu(999, "Eintrag fehlt")
        d = self.w.lade(e)
        self.assertEqual([(a["id"], a["text"], a["kid_id"], a["zitat"]) for a in d["angaben"]],
                         [(hand, "Baujahr 1975", "", ""),
                          (ki, "Feuerlöscher geprüft am 19.02.2016", "AAAA-0001", "Prüf-/Lieferdatum: 19.02.2016")])
        self.assertEqual([(b["kid_id"], b["titel"]) for b in d["belege"]], [("AAAA-0001", "Rechnung Prüfdienst")])
        # dieselbe Angabe später aus einem Dokument: die von Hand bekommt das Dokument, keine zweite Zeile
        self.assertIsNone(self.w.angabe_hinzu(e, "Baujahr 1975", "BBBB-0002", "Kaufvertrag", "Baujahr 1975"))
        d = self.w.lade(e)
        self.assertEqual((len(d["angaben"]), d["angaben"][0]["kid_id"], len(d["belege"])), (2, "BBBB-0002", 2))
        self.w.angabe_aendern(ki, "Feuerlöscher zuletzt geprüft am 19.02.2016")
        with self.assertRaises(wissen.Eingabefehler):
            self.w.angabe_aendern(ki, "")
        with self.assertRaises(wissen.Eingabefehler):
            self.w.angabe_aendern(12345, "weg")
        a = self.w.lade(e)["angaben"][1]
        self.assertEqual((a["text"], a["zitat"]), ("Feuerlöscher zuletzt geprüft am 19.02.2016",
                                                   "Prüf-/Lieferdatum: 19.02.2016"))   # Zitat bleibt
        self.w.angabe_weg(hand)
        self.w.angabe_weg(hand)                                              # zweimal schadet nicht
        self.assertEqual([x["id"] for x in self.w.lade(e)["angaben"]], [ki])

    def test_belege(self):
        e = self.w.speichere(self.art("Person"), "Max Mustermann")
        f = self.w.speichere(self.art("Fahrzeug"), "VW Golf")
        self.w.speichere(self.art("Person"), "Erika Musterfrau")
        with self.assertRaises(wissen.Eingabefehler):
            self.w.beleg_hinzu(e, "", "ohne ID")
        self.assertTrue(self.w.beleg_hinzu(e, "ZZZZ-0001", "  Zeugnis   2001 "))
        self.assertFalse(self.w.beleg_hinzu(e, "ZZZZ-0001", "Zeugnis"))      # nie doppelt
        self.w.angabe_hinzu(e, "Abschluss 2001", "ZZZZ-0001", "Zeugnis 2001", "Abschluss im Jahr 2001")
        self.w.angabe_hinzu(f, "Halter: Max Mustermann", "AAAA-0001", "Zulassung", "Halter Max Mustermann")
        self.w.beleg_hinzu(e, "AAAA-0001", "Zulassung")
        self.assertEqual([b["titel"] for b in self.w.lade(e)["belege"]], ["Zeugnis 2001", "Zulassung"])
        self.assertEqual([x["bezeichnung"] for x in self.w.eintraege_mit_beleg(["AAAA-0001"])],
                         ["Max Mustermann", "VW Golf"])                      # Reihenfolge wie liste()
        self.assertEqual([x["id"] for x in self.w.eintraege_mit_beleg(["ZZZZ-0001", "", "CCCC-0003"])], [e])
        self.assertEqual(self.w.eintraege_mit_beleg(["", "CCCC-0003"]), [])
        # Beleg weg: die Angabe bleibt, gilt aber wie von Hand
        zeugnis = next(b["id"] for b in self.w.lade(e)["belege"] if b["kid_id"] == "ZZZZ-0001")
        self.w.beleg_weg(zeugnis)
        self.w.beleg_weg(zeugnis)
        d = self.w.lade(e)
        self.assertEqual(([b["kid_id"] for b in d["belege"]], [(a["text"], a["kid_id"], a["zitat"]) for a in d["angaben"]]),
                         (["AAAA-0001"], [("Abschluss 2001", "", "")]))
        self.assertEqual(self.w.lade(f)["angaben"][0]["kid_id"], "AAAA-0001")   # der andere Eintrag bleibt, wie er war

    def test_verbindungen(self):
        haus = self.w.speichere(self.art("Immobilie"), "Haus Musterstraße 1")
        firma = self.w.speichere(self.art("Firma"), "Muster Prüfdienst")
        max_ = self.w.speichere(self.art("Person"), "Max Mustermann")
        self.assertTrue(self.w.verbinde(haus, firma))
        self.assertFalse(self.w.verbinde(firma, haus))                       # ohne Richtung, nie doppelt
        self.assertTrue(self.w.verbinde(max_, haus))
        with self.assertRaises(wissen.Eingabefehler):
            self.w.verbinde(haus, haus)
        with self.assertRaises(wissen.Eingabefehler):
            self.w.verbinde(haus, 999)
        self.assertEqual([(v["bezeichnung"], v["art_name"]) for v in self.w.lade(haus)["verbunden"]],
                         [("Max Mustermann", "Person"), ("Muster Prüfdienst", "Firma")])
        self.assertEqual([v["id"] for v in self.w.lade(firma)["verbunden"]], [haus])
        self.w.trenne(firma, haus)
        self.assertEqual([v["id"] for v in self.w.lade(haus)["verbunden"]], [max_])
        self.w.loesche(max_)                                                 # Löschen nimmt die Verbindung mit
        self.assertEqual(self.w.lade(haus)["verbunden"], [])

    def test_geprueft_gilt_nur_bis_zur_naechsten_aenderung(self):
        e = self.w.speichere(self.art("Person"), "Max Mustermann")
        angabe = self.w.angabe_hinzu(e, "Rolle: Familie")

        def geprueft(wert="2026-11-12T10:00:00"):
            con = sqlite3.connect(self.w.pfad)
            con.execute("UPDATE eintrag SET geprueft = ? WHERE id = ?", (wert, e))
            con.commit()
            con.close()

        for aendern in (lambda: self.w.speichere(self.art("Person"), "Max Mustermann", "Notiz", eintrag_id=e),
                        lambda: self.w.angabe_hinzu(e, "Telefon: 01234 56789"),
                        lambda: self.w.angabe_aendern(angabe, "Rolle: Familie, Eigentümer"),
                        lambda: self.w.angabe_weg(angabe)):
            geprueft()
            self.assertTrue(self.w.lade(e)["geprueft"])
            aendern()
            self.assertEqual(self.w.lade(e)["geprueft"], "")
        geprueft()
        self.w.beleg_hinzu(e, "AAAA-0001", "Ausweis")                        # ein Beleg ändert keinen Text
        self.assertTrue(self.w.lade(e)["geprueft"])

    def test_eintraege_zusammenlegen(self):
        # Peter 13.11.2026: zwei Einträge meinen dasselbe - nichts darf dabei verloren gehen
        a = self.w.speichere(self.art("Versicherung"), "Hausrat Musterversicherung", "Seit 2019.")
        b = self.w.speichere(self.art("Vertrag"), "Muster Privatschutz", "Läuft über Max.")
        c = self.w.speichere(self.art("Firma"), "Musterversicherung AG")
        d = self.w.speichere(self.art("Person"), "Max Mustermann")
        self.w.angabe_hinzu(a, "Versicherungsnummer: 4711")
        self.w.angabe_hinzu(a, "Beitrag jährlich zum 01.12.")
        self.w.angabe_hinzu(b, "versicherungsnummer:  4711", "AAAA-0001", "Police", "Vers.-Nr. 4711")   # derselbe Text
        self.w.angabe_hinzu(b, "Versicherungsort: Musterstraße 8", "AAAA-0001", "Police", "Musterstraße 8")
        self.w.beleg_hinzu(a, "BBBB-0002", "Rechnung")
        self.w.beleg_hinzu(b, "BBBB-0002", "Rechnung")
        for x, y in ((a, b), (a, c), (b, c), (b, d)):
            self.w.verbinde(x, y)
        self.assertEqual(self.w.eintraege_zusammenlegen(a, b), {"angaben": 1, "belege": 1, "verbunden": 1})
        e = self.w.lade(a)
        self.assertIsNone(self.w.lade(b))
        self.assertEqual([(x["text"], x["kid_id"], x["zitat"]) for x in e["angaben"]], [
            ("Versicherungsnummer: 4711", "AAAA-0001", "Vers.-Nr. 4711"),          # bekam Dokument und Zitat
            ("Beitrag jährlich zum 01.12.", "", ""),
            ("Versicherungsort: Musterstraße 8", "AAAA-0001", "Musterstraße 8"),
            ("Auch: Muster Privatschutz", "", "")])
        self.assertEqual(sorted(x["kid_id"] for x in e["belege"]), ["AAAA-0001", "BBBB-0002"])
        self.assertEqual(sorted(v["id"] for v in e["verbunden"]), [c, d])
        self.assertEqual((e["notiz"], e["art_name"], e["bezeichnung"]),
                         ("Seit 2019.\nLäuft über Max.", "Versicherung", "Hausrat Musterversicherung"))
        self.assertEqual(self.w.anzahl(), 3)
        for x, y in ((a, a), (a, b), (99999, c)):
            with self.assertRaises(wissen.Eingabefehler):
                self.w.eintraege_zusammenlegen(x, y)
        self.assertEqual(self.w.anzahl(), 3)
        gleich = self.w.speichere(self.art("Firma"), "musterversicherung  ag")
        self.w.eintraege_zusammenlegen(c, gleich)                                  # gleicher Name: kein „Auch: …“
        self.assertEqual(self.w.lade(c)["angaben"], [])

    def test_suche_in_angaben_und_notiz(self):
        e = self.w.speichere(self.art("Firma"), "Muster Prüfdienst", "Kommt jedes Jahr im Juni")
        self.w.angabe_hinzu(e, "Telefon: 01234/5678")
        self.w.angabe_hinzu(e, "Anschrift: Musterstraße 8")
        texte = self.w.suchtexte()[e]
        self.assertEqual(texte, ["Muster Prüfdienst", "Kommt jedes Jahr im Juni", "Telefon: 01234/5678",
                                 "Anschrift: Musterstraße 8"])
        for suche in ("prüfdienst", "JUNI", "01234/5678", "01234 5678", "012345678", "5678", "musterstrasse",
                      "telefon 5678", "  "):
            self.assertTrue(wissen.passt(suche, texte), suche)
        for suche in ("prüfdienst juli", "56789", "13", "Telefon 9999"):
            self.assertFalse(wissen.passt(suche, texte), suche)
        self.assertEqual(wissen.fundstellen("telefon juni", texte), [1, 2])
        self.assertEqual(wissen.fundstellen("", texte), [])
        self.assertEqual(wissen.Wissen(os.path.join(self.basis, "leer")).suchtexte(), {})

    def test_abgelehntes_wird_gemerkt(self):
        e = self.w.speichere(self.art("Firma"), "Muster Prüfdienst")
        aus_dok = self.w.angabe_hinzu(e, "Telefon: 01234/5678", "AAAA-0001", "Rechnung", "Tel.: 01234/5678")
        von_hand = self.w.angabe_hinzu(e, "Zuständig für Feuerlöscher")
        self.assertEqual(self.w.abgelehnte(["AAAA-0001"]), {})
        self.w.angabe_weg(aus_dok)                                           # aus einem Dokument: gemerkt
        self.w.angabe_weg(von_hand)                                          # von Hand: nichts zu merken
        self.assertEqual(self.w.abgelehnte(["AAAA-0001", "", "BBBB-0002"]),
                         {"AAAA-0001": [{"text": "Telefon: 01234/5678", "zitat": "Tel.: 01234/5678"}]})
        con = sqlite3.connect(self.w.pfad)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM abgelehnt").fetchone()[0], 1)   # keine Zeile ohne Dokument
        con.close()
        self.assertEqual(self.w.ablehnen("AAAA-0001", [{"text": " Telefon:  01234/5678", "zitat": "Tel.: 01234/5678"},
                                                       {"text": "Prüfgebühr 16,90 EUR", "zitat": ""},
                                                       {"text": " ", "zitat": "x"}]), 1)      # doppelt und leer: nicht
        self.assertEqual(self.w.ablehnen("", [{"text": "x", "zitat": "y"}]), 0)              # ohne Dokument-ID nichts
        self.assertEqual(len(self.w.abgelehnte(["AAAA-0001"])["AAAA-0001"]), 2)
        self.assertEqual(wissen.Wissen(os.path.join(self.basis, "leer")).abgelehnte(["AAAA-0001"]), {})

    def test_datei_vom_12_11_wird_nachgeruestet(self):
        # Aufbau vom 12.11.2026 (user_version 2) bekommt nur die neue Tabelle - kein Eintrag geht verloren
        e = self.w.speichere(self.art("Person"), "Max Mustermann")
        self.w.angabe_hinzu(e, "Telefon: 01234/5678", "AAAA-0001", "Rechnung", "Tel.: 01234/5678")
        con = sqlite3.connect(self.w.pfad)
        con.executescript("DROP TABLE abgelehnt; PRAGMA user_version = 2;")
        con.close()
        with self.assertNoLogs("DocManager", "INFO"):                        # nichts beiseitegelegt
            self.assertEqual([a["text"] for a in self.w.lade(e)["angaben"]], ["Telefon: 01234/5678"])
        self.assertFalse(os.path.exists(self.w.pfad_alt))
        self.w.angabe_weg(self.w.lade(e)["angaben"][0]["id"])
        self.assertEqual(len(self.w.abgelehnte(["AAAA-0001"])["AAAA-0001"]), 1)
        con = sqlite3.connect(self.w.pfad)
        self.addCleanup(con.close)
        self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], wissen.SCHEMA)

    def test_alte_datei_wird_beiseitegelegt(self):
        # Aufbau bis 12.11.2026 (feste Felder, user_version 1): beiseite als wissen_alt.sqlite, leer neu beginnen
        os.makedirs(os.path.dirname(self.w.pfad))
        con = sqlite3.connect(self.w.pfad)
        con.executescript("CREATE TABLE eintrag (id INTEGER PRIMARY KEY, art TEXT, bezeichnung TEXT);"
                          "INSERT INTO eintrag (art, bezeichnung) VALUES ('fahrzeug', 'VW Golf');"
                          "CREATE TABLE wert (eintrag INTEGER, feld TEXT, wert TEXT); PRAGMA user_version = 1;")
        con.close()
        with self.assertLogs("DocManager", "INFO") as log:
            self.assertEqual(self.w.liste(), [])
        self.assertNotIn("Golf", " ".join(log.output))                       # ins Protokoll keine Inhalte
        self.assertTrue(os.path.exists(self.w.pfad_alt))
        alt = sqlite3.connect(self.w.pfad_alt)
        self.addCleanup(alt.close)
        self.assertEqual(alt.execute("SELECT bezeichnung FROM eintrag").fetchall(), [("VW Golf",)])
        e = self.w.speichere(self.art("Fahrzeug"), "VW Golf")                # das neue Wiki arbeitet
        self.assertEqual(self.w.lade(e)["art_name"], "Fahrzeug")
        with self.assertNoLogs("DocManager", "INFO"):                        # nur einmal
            self.assertEqual(self.w.anzahl(), 1)

    def test_sicherung_und_transaktion(self):
        e = self.w.speichere(self.art("Person"), "Max Mustermann")
        self.assertTrue(self.w.sichere())
        self.w.loesche(e)
        bak = wissen.Wissen(pfad=self.w.pfad + ".bak")
        self.assertEqual([x["bezeichnung"] for x in bak.liste()], ["Max Mustermann"])
        # alles oder nichts: scheitert die Angabe, wird auch das Dokument nicht Beleg
        e = self.w.speichere(self.art("Person"), "Erika Musterfrau")

        def kaputt(con):
            con.execute("INSERT INTO beleg (eintrag, kid_id) VALUES (?, 'AAAA-0001')", (e,))
            raise RuntimeError("mittendrin")
        with self.assertRaises(RuntimeError):
            self.w._mit(kaputt)
        self.assertEqual(self.w.lade(e)["belege"], [])

    def test_aus_einem_anderen_thread(self):
        e = self.w.speichere(self.art("Person"), "Max Mustermann")
        ergebnis = []
        t = threading.Thread(target=lambda: ergebnis.append(self.w.angabe_hinzu(e, "Rolle: Familie")))
        t.start()
        t.join(10)
        self.assertEqual([a["id"] for a in self.w.lade(e)["angaben"]], ergebnis)


if __name__ == "__main__":
    unittest.main()
