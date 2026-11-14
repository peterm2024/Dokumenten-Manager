"""Wiki von Hand, neuer Aufbau, Schritt N3: „Was kommt im Dokument vor?“ - Prüfung im Code (wissen_ki), der Lauf und das
Fenster zum Anhaken (tools/wiki_dinge), ohne KI-Server. Nur Musterdaten."""
import collections
import os
import queue
import shutil
import tempfile
import time
import tkinter as tk
import types
import unittest
from unittest.mock import patch

import wissen
import wissen_ki
from pdf_handler import PDFHandler
from tests.test_begleitet_erfassen import Einstellungen, threads_beenden
from tests.test_mail_import import pdf_bytes
from tools import wiki as wf
from tools import wiki_dinge as wd

TEXT = """Muster Prüfdienst Feuerlöscher  Musterweg 17  12345 Musterstadt  Tel.: 01234/5678
Bankverbindung: Musterbank IBAN: DE00123456780000012345  Geschäftsführer: Erwin Muster
Herrn Max Mustermann  Musterstraße 8  12345 Musterstadt
Rechnung Nr. 20090006 vom 21.09.2020  Prüf-/Lieferdatum: 19.02.2016
für das Gebäude Altes Schloss in Musterdorf  Ihr Online-Passwort: geheim123
Prüfgebühr 16,90 EUR"""


def ding(schublade, bezeichnung, *angaben):
    return {"schublade": schublade, "bezeichnung": bezeichnung,
            "angaben": [{"text": t, "zitat": z} for t, z in angaben]}


ANTWORT = {"dinge": [
    ding("Firma", "Muster Prüfdienst",
         ("Anschrift: Musterweg 17, 12345 Musterstadt", "Musterweg 17 12345 Musterstadt"),
         ("Telefon: 01234/5678", "Tel.: 01234/5678"),
         ("Geschäftsführer ist Erwin Muster", "Geschäftsführer: Erwin Muster"),             # Impressum
         ("IBAN DE00123456780000012345", "IBAN: DE00123456780000012345"),                   # Bankdaten
         ("Telefon: 01234/9999", "Tel.: 01234/5678"),                                       # Zahl nicht im Zitat
         ("Das Dokument bezieht sich auf eine Prüfung", "Prüf-/Lieferdatum: 19.02.2016"),   # Satz über das Dokument
         ("Passwort geheim123", "Ihr Online-Passwort: geheim123"),                          # Zugangsdaten
         ("Sitz in Berlin", "Sitz der Firma ist Berlin"),                                   # erfunden
         ("Telefonnummer der Firma.", "Tel.: 01234/5678"),                                  # Beschriftung ohne Wert
         ("Rechnungsnummer: 20090006", "Rechnung Nr. 20090006")),                           # gilt nur für dieses Dokument
    ding("Immobilie", "Altes Schloss Musterdorf",
         ("Feuerlöscher geprüft am 19.02.2016", "Prüf-/Lieferdatum: 19.02.2016"),
         ("Ort der Prüfung und Empfänger der Rechnung", "Prüf-/Lieferdatum: 19.02.2016")),  # Rolle im Dokument
    ding("Vertrag", "Rechnung Nr. 20090006", ("Rechnung vom 21.09.2020", "vom 21.09.2020")),   # das Dokument selbst
    ding("Firma", "Hausverwaltung Sonnenschein", ("Telefon: 01234/5678", "Tel.: 01234/5678")),  # Name nicht im Text
    ding("Person", "Max Mustermann", ("Geschäftsführer Erwin Muster", "Geschäftsführer: Erwin Muster")),   # nichts bleibt
    ding("Gerät", "muster prüfdienst", ("Telefon: 01234/5678", "Tel.: 01234/5678"),         # derselbe noch einmal
         ("Prüfgebühr 16,90 EUR", "Prüfgebühr 16,90 EUR")),
    "Unsinn", {"bezeichnung": None}]}


class TestPruefung(unittest.TestCase):
    def test_der_code_sortiert_aus(self):
        dinge, weg = wissen_ki.pruefe_dinge(ANTWORT, TEXT)
        self.assertEqual([(d["schublade"], d["bezeichnung"], [a["text"] for a in d["angaben"]]) for d in dinge], [
            ("Firma", "Muster Prüfdienst", ["Anschrift: Musterweg 17, 12345 Musterstadt", "Telefon: 01234/5678",
                                           "Prüfgebühr 16,90 EUR"]),
            ("Immobilie", "Altes Schloss Musterdorf", ["Feuerlöscher geprüft am 19.02.2016"])])
        self.assertEqual(weg, collections.Counter(impressum=3, zahl=1, ueber=1, zugang=1, zitat=1, dokument=1, name=2,
                                                  ohne=1, rolle=2, etikett=1))
        self.assertEqual(set(weg) - set(wissen_ki.GRUENDE), set())
        for kaputt in (None, [], {"dinge": "x"}, {"dinge": [{"bezeichnung": "Muster", "angaben": "x"}]}):
            self.assertEqual(wissen_ki.pruefe_dinge(kaputt, TEXT)[0], [])
        viele = {"dinge": [ding("Firma", f"Muster {wort}", ("Telefon: 01234/5678", "Tel.: 01234/5678"))
                           for wort in ("Prüfdienst", "Feuerlöscher", "Musterweg", "Musterstadt", "Musterbank", "Schloss",
                                        "Gebäude", "Rechnung", "Musterdorf", "Prüfgebühr")]}
        self.assertEqual(len(wissen_ki.pruefe_dinge(viele, TEXT)[0]), wissen_ki.MAX_DINGE)

    def test_prompt(self):
        p = wissen_ki.baue_prompt("x" * 20000, "Rechnung", ["Person", "Firma"], ["Max  Mustermann", "VW Golf"])
        self.assertIn("eine aus Person, Firma;", p)
        self.assertIn("Im Wiki stehen schon: Max Mustermann; VW Golf.", p)
        self.assertIn("x" * wissen_ki.MAX_TEXT, p)
        self.assertNotIn("x" * (wissen_ki.MAX_TEXT + 1), p)
        self.assertNotIn("Im Wiki stehen schon", wissen_ki.baue_prompt("Text", "", ["Person"]))

    def test_schon_im_wiki(self):
        liste = [{"id": 1, "bezeichnung": "Max Mustermann"}, {"id": 2, "bezeichnung": "Muster Prüfdienst"},
                 {"id": 3, "bezeichnung": "Prüfdienst Muster GmbH"}]
        self.assertEqual(wissen_ki.finde_eintrag("Herrn Max Mustermann", liste)["id"], 1)    # Anrede egal
        self.assertEqual(wissen_ki.finde_eintrag("Mustermann, Max", liste)["id"], 1)
        self.assertIsNone(wissen_ki.finde_eintrag("Max", liste))
        self.assertEqual(wissen_ki.finde_eintrag("Prüfdienst Muster", liste)["id"], 2)       # die GmbH hat ein Wort mehr
        self.assertIsNone(wissen_ki.finde_eintrag("Muster", liste + [{"id": 4, "bezeichnung": "Muster"},
                                                                    {"id": 5, "bezeichnung": "MUSTER"}]))   # mehrdeutig

    def test_angaben_ohne_wert(self):
        # Peters Test 13.11.2026: Sätze mit richtigem Zitat, die in zwei Jahren nichts mehr sagen
        def grund(satz):
            return wissen_ki._pruefe_angabe({"text": satz, "zitat": "Tel.: 01234/5678"}, TEXT)[2]
        for satz in ("Kunde der Rechnung mit Wohnadresse in Musterstadt", "Patientin und Empfängerin der Rechnung",
                     "Er wohnt in Musterstadt und hat eine Rechnung erhalten", "Hat das Schreiben verfasst",
                     "Verbrauchsdaten sind im Dokument nicht ausgefüllt", "Zahnarzt, Name im Kopf der Rechnung",
                     "Rechnungsdatum: heute", "Gesamtbetrag der Rechnung: hoch", "Belegnummer ist unbekannt"):
            self.assertEqual(grund(satz), "rolle", satz)
        for satz in ("Telefonnummer der Praxis.", "Anschrift des Kunden Max Mustermann.", "Webseite der Praxis",
                     "Zählernummer für den Brunnenwasserverbrauch.", "Die Wohnadresse befindet sich in Musterstadt"):
            self.assertEqual(grund(satz), "etikett", satz)
        for satz in ("Zuständig für Abfallgebühren und Erlass des Bescheides", "Stellt jedes Jahr die Rechnung für die Wartung",
                     "E-Mail: info@muster.example", "Webseite: www.muster.example", "Internet: muster.de",
                     "Kundennummer bei der Firma lautet 5678", "Kontakt: Telefon 01234/5678", "Zahnarzt in Musterstadt",
                     "Kontaktansprechpartner Max Mustermann ist Leiter der Abteilung",
                     "Hat die Prüfung des Feuerlöschers durchgeführt", "Vertragsnummer (Rechnungsnummer): 5678"):
            self.assertEqual(grund(satz), "", satz)

    def test_schreibweisen_derselben_sache(self):
        # Peter 13.11.2026: verschiedene Schreibweisen derselben Adresse führten zu neuen Einträgen
        gleich = wissen_ki.gleicher_name
        self.assertTrue(gleich("Musterstr. 8", "Musterstraße 8"))
        self.assertTrue(gleich("Musterstrasse 8, 12345 Musterstadt", "Musterstr.8"))        # die eine steckt in der anderen
        self.assertTrue(gleich("Liegenschaft Musterstraße 8", "Musterstr. 8"))
        self.assertTrue(gleich("Zum Alten Faß 1", "zum alten Fass 1"))
        self.assertFalse(gleich("Zum Alten Faß 1", "Zum Alten Faß 3"))                 # andere Hausnummer
        self.assertFalse(gleich("Max Mustermann", "Max"))                                    # ohne Hausnummer: genau
        self.assertFalse(gleich("Muster GmbH", "Muster GmbH Stromvertrieb"))
        self.assertFalse(gleich("", "8"))
        liste = [{"id": 1, "bezeichnung": "Musterstraße 8, 12345 Musterstadt"}, {"id": 2, "bezeichnung": "Max Mustermann"}]
        self.assertEqual(wissen_ki.finde_eintrag("Musterstr. 8", liste)["id"], 1)
        angabe = wissen_ki.gleiche_angabe
        self.assertTrue(angabe("Anschrift: Musterstr. 8, 12345 Musterstadt", "Anschrift ist Musterstraße 8, 12345 Musterstadt"))
        self.assertTrue(angabe("Telefon: 01234/5678", "Telefonnummer der Firma ist 01234 5678"))   # dieselbe Nummer
        self.assertFalse(angabe("Baujahr 1975", "Baujahr 1976"))
        self.assertFalse(angabe("Zuständig für Reinigung", "Zuständig für Heizung"))
        self.assertFalse(angabe("Einheiten: 3", "Stockwerke: 3"))                            # kurze Zahl sagt nichts

    def test_wiedererkennen_nach_umbenennung(self):
        # Peter 13.11.2026: gefundene und danach geänderte Einträge wurden beim nächsten Lauf neu genannt
        schloss = {"id": 1, "bezeichnung": "Schlossgut", "angaben": [
            {"text": "Löscher zuletzt geprüft 2016", "zitat": "Prüf-/Lieferdatum: 19.02.2016"},
            {"text": "Baujahr 1750", "zitat": ""}]}
        firma = {"id": 2, "bezeichnung": "Prüfdienst", "angaben": [{"text": "Telefon 01234/5678", "zitat": "Tel.: 01234/5678"}]}
        zitate = ["Prüf-/Lieferdatum:  19.02.2016", "für das Gebäude Altes Schloss"]
        self.assertEqual(wissen_ki.finde_ueber_zitate(zitate, [firma, schloss])["id"], 1)
        self.assertIsNone(wissen_ki.finde_ueber_zitate(["anderes Zitat", ""], [firma, schloss]))
        self.assertIsNone(wissen_ki.finde_ueber_zitate(zitate + ["Tel.: 01234/5678"], [firma, schloss]))   # Gleichstand
        vorschlag = [{"text": "Feuerlöscher geprüft am 19.02.2016", "zitat": "Prüf-/Lieferdatum: 19.02.2016"},   # gleiches Zitat
                     {"text": "Baujahr: 1750", "zitat": "erbaut 1750"},                                          # sinngleich
                     {"text": "Liegt in Musterdorf", "zitat": "Altes Schloss in Musterdorf"}]
        self.assertEqual([a["text"] for a in wissen_ki.neue_angaben(vorschlag, schloss)], ["Liegt in Musterdorf"])

    def test_abgelehnt(self):
        abgelehnte = [{"text": "Telefon: 01234/5678", "zitat": "Tel.: 01234/5678"},
                      {"text": "Kunde seit vielen Jahren", "zitat": "Ihr Kunde seit 2001"}]
        ja = wissen_ki.ist_abgelehnt
        self.assertTrue(ja({"text": "Telefonnummer ist 01234 5678", "zitat": "Tel.: 01234/5678"}, abgelehnte))
        self.assertTrue(ja({"text": "Rufnummer: 01234/5678", "zitat": "Telefon 01234/5678"}, abgelehnte))   # Nummer
        self.assertTrue(ja({"text": "Stammkunde", "zitat": "Ihr  Kunde seit 2001"}, abgelehnte))           # Zitat
        self.assertFalse(ja({"text": "Kunde seit 2001", "zitat": "seit 2001 Kunde"}, abgelehnte))
        self.assertFalse(ja({"text": "Telefon: 01234/9999", "zitat": ""}, abgelehnte))
        self.assertFalse(ja({"text": "Telefon: 01234/5678", "zitat": "Tel.: 01234/5678"}, []))

    def test_schlecht_erkannter_text(self):
        self.assertGreater(wissen_ki.text_guete(TEXT), 0.85)
        salat = "VWrrterBlr' 6 8^21 Dchx Tö^jf: OSiffiiS(55^.3 CommeoetankAG «BAN OratlOMOC B«C GOÖAOEFBCX3 l^rauHom y} i*H"
        self.assertLess(wissen_ki.text_guete(salat), wissen_ki.GUETE_MIN)
        self.assertEqual(wissen_ki.text_guete(""), 0.0)
        self.assertEqual(wissen_ki.text_guete("BeritnerVcftjarA Deutsche Bank"), 2 / 3)   # Großbuchstabe mitten im Wort


class TestLauf(unittest.TestCase):
    def test_schlecht_nur_wenn_alle_quellen_schlecht_sind(self):
        a, b = {"rel_path": "a.pdf", "titel": "a"}, {"rel_path": "b.pdf", "titel": "b"}
        eins = [ding("Firma", "Muster GmbH", ("Telefon: 1", "Tel. 1"))]
        zwei = [ding("Firma", "Muster GmbH", ("Telefon: 1", "Tel. 1")), ding("Person", "Max", ("x", "x"))]
        g = wd.lege_zusammen([(a, eins, False), (b, zwei, True)])
        self.assertEqual([(x["bezeichnung"], x["schlecht"], len(x["doks"]), len(x["angaben"])) for x in g],
                         [("Muster GmbH", False, 2, 1), ("Max", True, 1, 1)])
        self.assertTrue(wd.lege_zusammen([(b, eins, True), (a, eins, True)])[0]["schlecht"])

    def lauf(self, texte, dokumente=None):
        index = types.SimpleNamespace(wiki_text=lambda rel: (texte[rel], ""))
        app = types.SimpleNamespace(index_manager=index, master_folder="x")
        dokumente = dokumente or [{"rel_path": rel, "titel": rel[:-4]} for rel in texte]
        return wd.Lauf(app, dokumente, "u", "m", ["Person", "Firma"], ["Max Mustermann"])

    def meldungen(self, lauf):
        lauf.arbeite()                                   # direkt im Test-Thread
        m = []
        while not lauf.postfach.empty():
            m.append(lauf.postfach.get())
        return m

    def test_liest_prueft_und_legt_zusammen(self):
        lauf = self.lauf({"a.pdf": TEXT, "b.pdf": TEXT, "leer.pdf": "  ", "salat.pdf": "X^y} i*H «BAN O^r Qz{ " * 20})
        antworten = [({"dinge": ANTWORT["dinge"][:2]}, 1.0),
                     ({"dinge": [ding("Firma", "MUSTER PRÜFDIENST", ("Telefon: 01234/5678", "Tel.: 01234/5678"),
                                      ("Prüft Feuerlöscher", "Muster Prüfdienst Feuerlöscher"))]}, 1.0),
                     ({"dinge": []}, 1.0)]
        with patch("tools.wiki_dinge.wissen_ki.lies_json", side_effect=antworten) as ki:
            m = self.meldungen(lauf)
        self.assertEqual([x[0] for x in m], ["stand"] * 4 + ["fertig"])
        self.assertIn("Im Wiki stehen schon: Max Mustermann.", ki.call_args_list[0][0][0])
        e = m[-1][1]
        z = e["zahlen"]
        self.assertEqual((z["gelesen"], z["ohne_text"], z["schlecht"]), (3, 1, 1))
        firma, schloss = e["dinge"]
        self.assertEqual((firma["bezeichnung"], [d["rel_path"] for d in firma["doks"]], firma["schlecht"]),
                         ("Muster Prüfdienst", ["a.pdf", "b.pdf"], False))
        self.assertEqual([(a["text"], a["dok"]["rel_path"]) for a in firma["angaben"]],
                         [("Anschrift: Musterweg 17, 12345 Musterstadt", "a.pdf"), ("Telefon: 01234/5678", "a.pdf"),
                          ("Prüft Feuerlöscher", "b.pdf")])
        self.assertEqual([d["rel_path"] for d in schloss["doks"]], ["a.pdf"])
        self.assertEqual(e["verworfen"]["impressum"], 2)

    def test_server_weg_unbrauchbar_abbrechen_und_hoechstens_zwanzig(self):
        with patch("tools.wiki_dinge.wissen_ki.lies_json", side_effect=OSError("weg")):
            m = self.meldungen(self.lauf({"a.pdf": TEXT, "b.pdf": TEXT}))
        self.assertEqual([x[0] for x in m], ["stand", "fehler"])
        with patch("tools.wiki_dinge.wissen_ki.lies_json", side_effect=[wissen_ki.UnbrauchbareAntwort("x"),
                                                                       RuntimeError("y")]):
            m = self.meldungen(self.lauf({"a.pdf": TEXT, "b.pdf": TEXT}))
        self.assertEqual((m[-1][1]["zahlen"]["unbrauchbar"], m[-1][1]["zahlen"]["fehler"], m[-1][1]["dinge"]), (1, 1, []))
        lauf = self.lauf({"a.pdf": TEXT})
        lauf.abbrechen.set()
        with patch("tools.wiki_dinge.wissen_ki.lies_json") as ki:
            m = self.meldungen(lauf)
        ki.assert_not_called()
        self.assertEqual(m[-1][1]["zahlen"]["abgebrochen"], 1)
        viele = [{"rel_path": f"{n}.pdf", "titel": str(n)} for n in range(25)]
        self.assertEqual(len(self.lauf({}, viele).dokumente), wissen_ki.HOECHSTENS)


class TestDingeFenster(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(threads_beenden)
        self.addCleanup(self.root.destroy)
        self.basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.basis, True)
        self.sammlung = os.path.join(self.basis, "Sammlung")
        os.makedirs(self.sammlung)
        self.pdf = os.path.join(self.sammlung, "Rechnung.pdf")
        with open(self.pdf, "wb") as d:
            d.write(pdf_bytes())
        self.dienst = types.SimpleNamespace(stand=0, pausen=0)
        self.dienst.pausieren = lambda: (setattr(self.dienst, "stand", self.dienst.stand + 1),
                                         setattr(self.dienst, "pausen", self.dienst.pausen + 1))
        self.dienst.fortsetzen = lambda: setattr(self.dienst, "stand", self.dienst.stand - 1)
        index = types.SimpleNamespace(wiki_text=lambda rel: (TEXT, ""), pfad_zur_kid_id=lambda kid: "Rechnung.pdf")
        self.gezeigt = []
        zeiger = types.SimpleNamespace(zeige_dokument=lambda pfad: self.gezeigt.append(pfad) or True)
        self.app = types.SimpleNamespace(root=self.root, master_folder=self.sammlung, config=Einstellungen(), logger=None,
                                         index_manager=index, auto_pilot_service=self.dienst, folder_manager=zeiger)
        for ziel in ("tools.wiki.UIUtils.werkzeugfenster", "tools.wiki_dinge.UIUtils.werkzeugfenster"):
            p = patch(ziel)                                            # sonst unsichtbar (FALLSTRICKE #95)
            p.start()
            self.addCleanup(p.stop)
        self.w = wissen.Wissen(self.sammlung)

    def warte(self, d):
        ende = time.time() + 10
        while d._laeuft and time.time() < ende:
            self.root.update()
            time.sleep(0.02)
        self.assertFalse(d._laeuft)

    def test_auflisten_anhaken_uebernehmen(self):
        max_ = self.w.speichere("Person", "Max Mustermann")
        self.w.angabe_hinzu(max_, "Anschrift: Musterstraße 8, 12345 Musterstadt")
        f = wf.WikiFenster(self.app)
        self.addCleanup(lambda: f.winfo_exists() and f.destroy())
        antwort = {"dinge": ANTWORT["dinge"][:2] + [
            ding("Person", "Herrn Max Mustermann", ("Anschrift: Musterstraße 8, 12345 Musterstadt", "Musterstraße 8 12345 Musterstadt"),
                 ("Kunde beim Muster Prüfdienst", "Herrn Max Mustermann")),
            ding("Gerät", "Feuerlöscher", ("Prüfgebühr 16,90 EUR", "Prüfgebühr 16,90 EUR"))]}
        with patch("tools.wiki_dinge.wissen_ki.lies_json", return_value=(antwort, 1.0)):
            f.dinge_lesen([{"rel_path": "Rechnung.pdf", "titel": "Rechnung Prüfdienst"}])
            d = f.dinge
            self.warte(d)
        self.assertEqual((self.dienst.pausen, self.dienst.stand), (1, 0))          # Vollautomatik wartete solange
        self.assertIn("1 Dokument gelesen", d.lbl_status.cget("text"))
        self.assertIn("2× Impressum oder Bankdaten", d.lbl_status.cget("text"))
        zeilen = [d.tree.item(i, "text") for i in d.tree.get_children()]
        self.assertEqual(zeilen, ["☑ Firma: Muster Prüfdienst", "☑ Immobilie: Altes Schloss Musterdorf",
                                  "☑ Person: Herrn Max Mustermann   - schon im Wiki, wird ergänzt",
                                  "☑ Gerät: Feuerlöscher   - neue Schublade"])
        # schon im Wiki: nur die Angabe, die dort noch nicht steht
        self.assertEqual([d.tree.item(i, "text") for i in d.tree.get_children("d:2")], ["☑ Kunde beim Muster Prüfdienst"])
        self.assertEqual(d.tree.item("a:0:1", "values"), ("„Tel.: 01234/5678“", "Rechnung Prüfdienst"))
        self.assertEqual(self.w.anzahl(), 1)                                       # noch nichts im Wiki
        d._schalte("d:3")                                                          # das Gerät nicht
        d._schalte("a:0:1")                                                        # die Telefonnummer nicht
        self.assertEqual(d.btn_uebernehmen.cget("text"), "3 Einträge übernehmen")
        d.tree.selection_set("d:1")
        with patch("tools.wiki_dinge.simpledialog.askstring", return_value="Altes Schloss"):
            d._umbenennen()
        d._uebernehmen()
        self.root.update()
        self.assertFalse(d.winfo_exists())
        self.assertEqual([(e["art_name"], e["bezeichnung"]) for e in self.w.liste()],
                         [("Person", "Max Mustermann"), ("Firma", "Muster Prüfdienst"), ("Immobilie", "Altes Schloss")])
        self.assertNotIn("Gerät", [a["name"] for a in self.w.arten()])
        firma = self.w.lade(self.w.liste()[1]["id"])
        kid = PDFHandler.get_metadata(self.pdf).get("KID_ID")
        self.assertTrue(kid)
        self.assertEqual([(a["text"], a["kid_id"], a["zitat"]) for a in firma["angaben"]],
                         [("Anschrift: Musterweg 17, 12345 Musterstadt", kid, "Musterweg 17 12345 Musterstadt")])
        self.assertEqual(([b["titel"] for b in firma["belege"]], sorted(v["bezeichnung"] for v in firma["verbunden"])),
                         (["Rechnung Prüfdienst"], ["Altes Schloss", "Max Mustermann"]))
        person = self.w.lade(max_)
        self.assertEqual([a["text"] for a in person["angaben"]],
                         ["Anschrift: Musterstraße 8, 12345 Musterstadt", "Kunde beim Muster Prüfdienst"])
        self.assertEqual(len(person["belege"]), 1)
        self.assertEqual(f.eintrag["bezeichnung"], "Muster Prüfdienst")            # das Wiki zeigt den ersten

        # Was abgehakt blieb (Telefon, das Gerät mit seiner Prüfgebühr), ist je Dokument als abgelehnt gemerkt
        self.assertEqual(self.w.abgelehnte([kid]), {kid: [{"text": "Telefon: 01234/5678", "zitat": "Tel.: 01234/5678"},
                                                          {"text": "Prüfgebühr 16,90 EUR", "zitat": "Prüfgebühr 16,90 EUR"}]})

        # Zweiter Lauf über dasselbe Dokument (Peter 13.11.2026): Die umbenannte Immobilie und der umformulierte
        # Firmeneintrag werden wiedererkannt, nichts entsteht doppelt; nur wirklich Neues wird angeboten - Abgelehntes
        # nicht, auch anders formuliert nicht
        self.w.speichere("Firma", "Prüfdienst Muster & Söhne", eintrag_id=firma["id"])
        self.w.angabe_aendern(firma["angaben"][0]["id"], "Sitz im Musterweg 17 in Musterstadt")
        antwort2 = {"dinge": antwort["dinge"][:3] + [
            ding("Gerät", "Feuerlöscher", ("Prüfgebühr: 16,90 Euro", "Prüfgebühr 16,90 EUR"),
                 ("Gerät steht im Alten Fass", "für das Gebäude Altes Schloss in Musterdorf"))]}
        antwort2["dinge"][0] = dict(antwort2["dinge"][0], angaben=antwort2["dinge"][0]["angaben"] + [
            {"text": "Telefonnummer ist 01234 5678", "zitat": "Tel.: 01234/5678"}])
        with patch("tools.wiki_dinge.wissen_ki.lies_json", return_value=(antwort2, 1.0)):
            f.dinge_lesen([{"rel_path": "Rechnung.pdf", "titel": "Rechnung Prüfdienst"}])
            d = f.dinge
            self.warte(d)
        self.assertIn("3 früher abgelehnte Angaben ausgeblendet", d.lbl_status.cget("text"))
        self.assertEqual([d.tree.item(i, "text") for i in d.tree.get_children()], [
            "☑ Firma: Muster Prüfdienst   - schon im Wiki als „Prüfdienst Muster & Söhne“, wird ergänzt",
            "☑ Immobilie: Altes Schloss Musterdorf   - schon im Wiki als „Altes Schloss“, wird ergänzt",
            "☑ Person: Herrn Max Mustermann   - schon im Wiki, wird ergänzt",
            "☑ Gerät: Feuerlöscher   - neue Schublade"])
        self.assertEqual([[d.tree.item(a, "text") for a in d.tree.get_children(i)] for i in d.tree.get_children()],
                         [[], [], [], ["☑ Gerät steht im Alten Fass"]])
        # von Hand zuordnen: das Gerät gehört zum Schloss - oder wird neu in einer vorhandenen Schublade angelegt
        schloss = next(e for e in self.w.liste() if e["bezeichnung"] == "Altes Schloss")
        d.zuordnen(3, ziel=schloss)
        self.assertEqual(d.tree.item("d:3", "text"), "☑ Gerät: Feuerlöscher   - schon im Wiki als „Altes Schloss“, wird ergänzt")
        d.zuordnen(3, schublade="Sonstiges")
        self.assertEqual(d.tree.item("d:3", "text"), "☑ Sonstiges: Feuerlöscher")
        d.zuordnen(3, ziel=schloss)
        d.tree.selection_set("a:3:0")
        d._doppelklick()                                                           # Angabe: ihr Dokument zeigen
        self.assertEqual(self.gezeigt, [self.pdf])
        d._uebernehmen()
        self.assertEqual(self.w.anzahl(), 3)                                       # kein neuer Eintrag
        self.assertEqual([a["text"] for a in self.w.lade(schloss["id"])["angaben"]],
                         ["Feuerlöscher geprüft am 19.02.2016", "Gerät steht im Alten Fass"])
        self.assertEqual([a["text"] for a in self.w.lade(firma["id"])["angaben"]], ["Sitz im Musterweg 17 in Musterstadt"])
        self.assertEqual(len(self.w.abgelehnte([kid])[kid]), 2)                   # nichts abgehakt: nichts dazu

        # Ein Ding, von dem nur Abgelehntes käme, erscheint gar nicht
        with patch("tools.wiki_dinge.wissen_ki.lies_json", return_value=(antwort, 1.0)):
            f.dinge_lesen([{"rel_path": "Rechnung.pdf", "titel": "Rechnung Prüfdienst"}])
            d = f.dinge
            self.warte(d)
        self.assertNotIn("Gerät", " ".join(d.tree.item(i, "text") for i in d.tree.get_children()))
        d.destroy()

    def test_schlecht_erkannt_nicht_vorgehakt_ohne_verbinden_und_schliessen_bricht_ab(self):
        f = wf.WikiFenster(self.app)
        self.addCleanup(lambda: f.winfo_exists() and f.destroy())
        self.app.index_manager.wiki_text = lambda rel: (TEXT + " X^y} i*H «BAN O^r Qz{" * 60, "")
        with patch("tools.wiki_dinge.wissen_ki.lies_json", return_value=({"dinge": ANTWORT["dinge"][:2]}, 1.0)):
            f.dinge_lesen([{"rel_path": "Rechnung.pdf", "titel": "Rechnung"}])
            d = f.dinge
            self.warte(d)
        self.assertEqual(d.tree.item("d:0", "text"), "☐ Firma: Muster Prüfdienst   - Text schlecht erkannt")
        self.assertEqual(str(d.btn_uebernehmen.cget("state")), "disabled")
        d._schalte("d:0")
        d.var_verbinden.set(False)
        d._uebernehmen()
        self.assertEqual([(e["bezeichnung"], self.w.lade(e["id"])["verbunden"]) for e in self.w.liste()],
                         [("Muster Prüfdienst", [])])
        kid = PDFHandler.get_metadata(self.pdf).get("KID_ID")
        self.assertEqual(self.w.abgelehnte([kid]), {})                             # nie angehakt: nicht abgelehnt
        # ein neuer Lauf ersetzt den alten; Schließen mitten im Lesen gibt die Vollautomatik frei
        import threading
        weiter = threading.Event()
        self.addCleanup(weiter.set)
        with patch("tools.wiki_dinge.wissen_ki.lies_json", side_effect=lambda *a, **k: (weiter.wait(5), ({}, 1.0))[1]):
            f.dinge_lesen([{"rel_path": "Rechnung.pdf", "titel": "Rechnung"}])
            d = f.dinge
            self.assertEqual(self.dienst.stand, 1)
            f.destroy()                                                            # das Wiki-Fenster geht zu
            self.assertTrue(d.lauf.abbrechen.is_set())
            self.assertEqual(self.dienst.stand, 0)
            weiter.set()
            ende = time.time() + 5
            fertig = False
            while not fertig and time.time() < ende:                               # der Thread läuft noch aus
                try:
                    fertig = d.lauf.postfach.get(timeout=0.1)[0] == "fertig"
                except queue.Empty:
                    pass


if __name__ == "__main__":
    unittest.main()
