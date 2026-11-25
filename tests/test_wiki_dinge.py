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
Herrn Max Mustermann  geb. 01.02.1950  Musterstraße 8  12345 Musterstadt  Kunden-Nr. 4711
Rechnung Nr. 20090006 vom 21.09.2020  Prüf-/Lieferdatum: 19.02.2016
für das Gebäude Altes Schloss in Musterdorf, Standort Keller  Ihr Online-Passwort: geheim123
Prüfgebühr 16,90 EUR"""

KANZLEI_TEXT = """Datenschutzhinweise  Kanzlei Muster & Partner  Musterweg 1  12345 Musterstadt  Tel. 01234/1111
Anna Muster Rechtsanwalt  Fachanwältin für Familienrecht  Bernd Beispiel Rechtsanwalt  Carla Probe Rechtsanwalt
Fachanwältin für Erbrecht  Herrn Max Mustermann  Musterstraße 8, D-12345 Musterstadt  Musterstraße 8, 12345 Musterstadt
Zuständig ist das Landesamt für Datenschutzaufsicht, Musterallee 1, 12345 Musterstadt"""


def ding(schublade, bezeichnung, *angaben):
    """Ein Ding, wie die KI es liefert; je Angabe (Merkmal, Wert, Zitat) - seit Etappe 12 W3 kein Satz mehr."""
    return {"schublade": schublade, "bezeichnung": bezeichnung,
            "angaben": [{"merkmal": m, "wert": w, "zitat": z} for m, w, z in angaben]}


ANTWORT = {"dinge": [
    ding("Firma", "Muster Prüfdienst",
         ("Adresse", "Musterweg 17, 12345 Musterstadt", "Musterweg 17 12345 Musterstadt"),
         ("Telefon", "01234/5678", "Tel.: 01234/5678"),
         ("Geschäftsführer", "Erwin Muster", "Geschäftsführer: Erwin Muster"),                # Impressum
         ("IBAN", "DE00123456780000012345", "IBAN: DE00123456780000012345"),                  # Bankdaten
         ("Telefon", "01234/9999", "Tel.: 01234/5678"),                                      # Wert nicht im Zitat
         ("Prüfung", "Das Dokument bezieht sich auf eine Prüfung", "Prüf-/Lieferdatum: 19.02.2016"),   # über das Dokument
         ("Passwort", "geheim123", "Ihr Online-Passwort: geheim123"),                         # Zugangsdaten
         ("Sitz", "Berlin", "Sitz der Firma ist Berlin"),                                     # erfunden
         ("Telefon", "", "Tel.: 01234/5678"),                                                 # Merkmal ohne Wert
         ("Rechnungsnummer", "20090006", "Rechnung Nr. 20090006"),                            # gilt nur für dieses Dokument
         ("", "01234/5678", "Tel.: 01234/5678"),                                              # ohne Merkmal
         ("Leistung", "prüft jedes Jahr alle Feuerlöscher im Gebäude Altes Schloss in Musterdorf und schickt die "
                      "Rechnung", "Muster Prüfdienst Feuerlöscher")),                         # ein Satz
    ding("Immobilie", "Altes Schloss Musterdorf",
         ("Feuerlöscher geprüft am", "19.02.2016", "Prüf-/Lieferdatum: 19.02.2016"),
         ("Rolle", "Empfänger der Rechnung", "Prüf-/Lieferdatum: 19.02.2016"),               # Rolle im Dokument
         ("Lage", "Altes Schloss in Musterdorf", "für das Gebäude Altes Schloss in Musterdorf")),   # = Bezeichnung
    ding("Vertrag", "Rechnung Nr. 20090006", ("Datum", "21.09.2020", "vom 21.09.2020")),    # das Dokument selbst
    ding("Versicherung", "Datenschutzhinweise Muster Prüfdienst",
         ("Stand", "2020", "vom 21.09.2020")),                                                # eine Dokumentart
    ding("Rechnungen", "Musterbank Musterstadt", ("Postleitzahl", "12345", "12345 Musterstadt")),   # Schublade = Dokumentart
    ding("Firma", "Hausverwaltung Sonnenschein", ("Telefon", "01234/5678", "Tel.: 01234/5678")),   # Name nicht im Text
    ding("Person", "Max Mustermann",
         ("Adresse", "Musterstraße 8, 12345 Musterstadt", "Musterstraße 8  12345 Musterstadt"),
         ("Kunde bei", "Muster Prüfdienst", "Muster Prüfdienst Feuerlöscher")),               # ein anderes Ding: Verbinden
    ding("Gerät", "muster prüfdienst", ("Telefon", "01234/5678", "Tel.: 01234/5678"),       # derselbe noch einmal
         ("Prüfgebühr", "16,90 EUR", "Prüfgebühr 16,90 EUR")),
    "Unsinn", {"bezeichnung": None}]}


class TestPruefung(unittest.TestCase):
    def test_der_code_sortiert_aus(self):
        dinge, weg = wissen_ki.pruefe_dinge(ANTWORT, TEXT)
        self.assertEqual([(d["schublade"], d["bezeichnung"], [a["text"] for a in d["angaben"]]) for d in dinge], [
            ("Firma", "Muster Prüfdienst", ["Adresse: Musterweg 17, 12345 Musterstadt", "Telefon: 01234 5678",
                                           "Prüfgebühr: 16,90 EUR"]),
            ("Immobilie", "Altes Schloss Musterdorf", ["Feuerlöscher geprüft am: 19.02.2016"]),
            ("Sonstiges", "Musterbank Musterstadt", ["Postleitzahl: 12345"]),
            ("Person", "Max Mustermann", ["Adresse: Musterstraße 8, 12345 Musterstadt"])])
        self.assertEqual(dinge[0]["angaben"][0], {"merkmal": "Adresse", "wert": "Musterweg 17, 12345 Musterstadt",
                                                  "zitat": "Musterweg 17 12345 Musterstadt",
                                                  "text": "Adresse: Musterweg 17, 12345 Musterstadt"})
        self.assertEqual(weg, collections.Counter(impressum=2, wert=1, rolle=3, zugang=1, zitat=1, leer=1, merkmal=1,
                                                  satz=1, bezeichnung=1, dokument=2, name=2, verbindung=1))
        self.assertEqual(set(weg) - set(wissen_ki.GRUENDE), set())
        for kaputt in (None, [], {"dinge": "x"}, {"dinge": [{"bezeichnung": "Muster", "angaben": "x"}]}):
            self.assertEqual(wissen_ki.pruefe_dinge(kaputt, TEXT)[0], [])
        viele = {"dinge": [ding("Firma", f"Muster {wort}", ("Telefon", "01234/5678", "Tel.: 01234/5678"))
                           for wort in ("Prüfdienst", "Feuerlöscher", "Musterweg", "Musterstadt", "Musterbank", "Schloss",
                                        "Gebäude", "Keller", "Musterdorf", "Prüfgebühr")]}
        self.assertEqual(len(wissen_ki.pruefe_dinge(viele, TEXT)[0]), wissen_ki.MAX_DINGE)

    def test_prompt(self):
        p = wissen_ki.baue_prompt("x" * 20000, "Rechnung", ["Person", "Firma"], ["Max  Mustermann", "VW Golf"])
        self.assertIn("eine aus Person, Firma;", p)
        self.assertIn("Im Wiki stehen schon: Max Mustermann; VW Golf.", p)
        self.assertIn("x" * wissen_ki.MAX_TEXT, p)
        self.assertNotIn("x" * (wissen_ki.MAX_TEXT + 1), p)
        self.assertNotIn("Im Wiki stehen schon", wissen_ki.baue_prompt("Text", "", ["Person"]))
        # Etappe 12 W3: die schon benutzten Merkmale, damit die KI dieselben Namen nimmt
        p = wissen_ki.baue_prompt("Text", "", ["Person"], [], ["Telefon", " Kunden  nummer"])
        self.assertIn("Im Wiki schon benutzte Merkmale - für dasselbe GENAU diesen Namen nehmen: Telefon, Kunden nummer.", p)
        self.assertNotIn("schon benutzte Merkmale", wissen_ki.baue_prompt("Text", "", ["Person"]))
        self.assertNotIn("«", p)

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
        # Peters Test 13.11.2026: Sätze mit richtigem Zitat, die in zwei Jahren nichts mehr sagen - seit W3 (19.11.2026)
        # ist eine Angabe Merkmal + Wert, der Wert muss im Zitat stehen
        def grund(merkmal, wert, zitat="Tel.: 01234/5678", bezeichnung="Muster Prüfdienst"):
            return wissen_ki._pruefe_angabe({"merkmal": merkmal, "wert": wert, "zitat": zitat}, TEXT, bezeichnung)[3]
        for merkmal, wert in (("Rolle", "Kunde der Rechnung mit Wohnadresse in Musterstadt"),
                              ("Rolle", "Patientin und Empfängerin der Rechnung"), ("Info", "Hat das Schreiben verfasst"),
                              ("Rechnungsdatum", "heute"), ("Gesamtbetrag der Rechnung", "hoch")):
            self.assertEqual(grund(merkmal, wert), "rolle", wert)
        for merkmal in ("Zu zahlender Betrag", "Betrag", "Rechnungsdatum", "fällig am", "MwSt"):   # W3-Messung
            self.assertEqual(grund(merkmal, "01234/5678"), "rolle", merkmal)
        for merkmal in ("Kontonummer", "Konto-Nr", "BLZ", "Bankleitzahl", "Bearbeiter"):
            self.assertEqual(grund(merkmal, "01234/5678"), "impressum", merkmal)
        self.assertEqual(grund("Beitrag", "01234/5678"), "")                    # Versicherungsbeitrag: jedes Jahr
        for merkmal, wert in (("Telefon", "Telefonnummer der Praxis."), ("Adresse", "Anschrift des Kunden"),
                              ("Webseite", "Webseite der Praxis")):
            self.assertEqual(grund(merkmal, wert), "wert", wert)                 # Beschriftung statt Wert
        self.assertEqual(grund("Telefon", "1 2 3 4 5 6 7 8 9 10 11"), "satz")
        self.assertEqual(grund("Wie man die Firma telefonisch erreicht", "01234/5678"), "merkmal")   # zu viele Wörter
        self.assertEqual(grund("x" * (wissen.MAX_MERKMAL + 1), "01234/5678"), "merkmal")
        self.assertEqual(grund("Name", "Muster Prüfdienst", "Muster Prüfdienst Feuerlöscher"), "bezeichnung")
        for merkmal, wert, zitat in (("Telefon", "01234 5678", "Tel.: 01234/5678"),
                                     ("Prüfgebühr", "16,90 €", "Prüfgebühr 16,90 EUR"),            # Zeichen egal
                                     ("geprüft am", "19.02.2016", "Prüf-/Lieferdatum: 19.02.2016"),
                                     ("Kundennummer", "4711", "Kunden-Nr. 4711"),
                                     ("zuständig für", "Feuerlöscher", "Muster Prüfdienst Feuerlöscher")):
            self.assertEqual(grund(merkmal, wert, zitat), "", wert)
        # KI-Lauf auf Prüfbriefen 23.11.2026 (Peter: „Ja“): Lesefehler und Vertragsrollen als Angaben
        text = ("servtce@musterversicheru ng.example www.musterversicheru ng.examplo service@muster.example "
                "www.muster.example Jens Muster Leiter Kundenservice Versicherungsnehmer Verkäufer Zentrale "
                "a@muster.example, b@muster.example Eigentümer")

        def g(merkmal, wert):
            return wissen_ki._pruefe_angabe({"merkmal": merkmal, "wert": wert, "zitat": wert}, text, "Musterfirma")[3]
        for merkmal, wert, erwartet in (
                ("E-Mail", "servtce@musterversicheru ng.example", "schreibweise"), ("E-Mail", "service@muster.example", ""),
                ("Webseite", "www.musterversicheru ng.examplo", "schreibweise"), ("Homepage", "www.muster.example", ""),
                ("E-Mail", "a@muster.example, b@muster.example", ""), ("Webseite", "www.muster.example.", ""),
                ("Adresse", "Jens Muster", "etikett"), ("Telefon", "Zentrale", "etikett"),
                ("Rolle", "Versicherungsnehmer", "rolle"), ("Funktion", "Versicherungsnehmer", "rolle"),
                ("Funktion", "Leiter Kundenservice", ""), ("Rolle", "Eigentümer", ""), ("Beruf", "Verkäufer", "")):
            self.assertEqual(g(merkmal, wert), erwartet, f"{merkmal}: {wert}")
        self.assertIn("schreibweise", wissen_ki.GRUENDE)
        self.assertEqual(wissen.merkmal_kern("Rolle"), wissen.merkmal_kern("Funktion"))      # eine Angabe, nicht zwei
        self.assertTrue(wissen_ki.wert_im_zitat("16,90 €", "Prüfgebühr 16,90 EUR"))
        self.assertFalse(wissen_ki.wert_im_zitat("16,90 Euro", "Prüfgebühr 16,90 EUR"))    # „Euro“ steht nicht da
        self.assertFalse(wissen_ki.wert_im_zitat("1690", "Gebühr 16,90 und 1690"[:10]))
        self.assertFalse(wissen_ki.wert_im_zitat("€", "16,90 €"))                          # ohne Buchstaben/Ziffern

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

    def test_telefon_einheitlich_und_kundennummer_bei_der_firma(self):
        # Peters Abnahme W3 (19.11.2026): Telefon- und Faxnummern einheitlich (DIN 5008), Kundennummer nie bei der Person
        tel = wissen.telefon_einheitlich
        for roh, soll in (("01234/567 89", "01234 56789"), ("0987-65 43 21", "0987 654321"), ("04321 765432", "04321 765432"),
                          ("(01234) 56789", "01234 56789"), ("+49 (0)1234-56789", "+49 1234 56789"),
                          ("0049 1234 / 56789", "+49 1234 56789"), ("0 43 21 / 76 54 32", "04321 765432"),
                          ("01234 56789 (Zentrale)", "01234 56789 (Zentrale)"), ("1234", "1234")):
            self.assertEqual(tel(roh), soll, roh)
        self.assertEqual(wissen.wert_einheitlich("Telefax", "01234/567 99"), "01234 56799")
        self.assertEqual(wissen.wert_einheitlich("Kundennummer", "081/31"), "081/31")      # nur Telefonisches
        for roh in ("Musterstr. 8, D-12345 Musterstadt", "Musterstr. 8 12345 Musterstadt", "Musterstr. 8 ,  12345 Musterstadt",
                    "Musterstr. 8 DE-12345 Musterstadt"):
            self.assertEqual(wissen.wert_einheitlich("Anschrift", roh), "Musterstr. 8, 12345 Musterstadt", roh)
        self.assertEqual(wissen.wert_einheitlich("Adresse", "12345 Musterstadt"), "12345 Musterstadt")
        self.assertEqual(wissen.wert_einheitlich("Vertragsnummer", "D-12345 X"), "D-12345 X")    # nur bei Anschriften
        # Daten nach DIN 5008 mit vierstelliger Jahreszahl (Peter 19.11.2026)
        import datetime
        heute = datetime.date(2026, 11, 19)
        for roh, soll in (("17.03.19 bis 16.03.20", "17.03.2019 bis 16.03.2020"), ("1.2.2019", "01.02.2019"),
                          ("31.12.31", "31.12.2031"), ("01.02.32", "01.02.1932"), ("geprüft am 5.6.16.", "geprüft am 05.06.2016."),
                          ("32.01.2019", "32.01.2019"), ("1.2.3.4", "1.2.3.4"), ("12.345.67", "12.345.67"),
                          ("Version 1.13.2019", "Version 1.13.2019")):
            self.assertEqual(wissen.datum_einheitlich(roh, heute), soll, roh)
        self.assertEqual(wissen.wert_einheitlich("Leistungszeitraum", "17.03.19 bis 16.03.20")[:10], "17.03.2019")
        text = TEXT + "  Fax: 01234/56 79"
        firma = ding("Firma", "Muster Prüfdienst", ("Telefon", "01234/5678", "Tel.: 01234/5678"),
                     ("Telefon", "01234 5678", "Tel.: 01234/5678"), ("Fax", "01234/56 79", "Fax: 01234/56 79"))
        person = ding("Person", "Max Mustermann", ("Kunden-Nr.", "4711", "Kunden-Nr. 4711"),
                      ("Geburtsdatum", "01.02.1950", "geb. 01.02.1950"))
        dinge, weg = wissen_ki.pruefe_dinge({"dinge": [person, firma]}, text)
        self.assertEqual([(d["bezeichnung"], [a["text"] for a in d["angaben"]]) for d in dinge], [
            ("Max Mustermann", ["Geburtsdatum: 01.02.1950"]),
            ("Muster Prüfdienst", ["Telefon: 01234 5678", "Fax: 01234 5679", "Kunden-Nr.: 4711"])])
        # mehrere oder keine Firma: welche wäre es? Dann lieber gar nicht
        zweite = ding("Versicherung", "Musterbank Musterstadt", ("Telefon", "01234/5678", "Tel.: 01234/5678"))
        dinge, weg = wissen_ki.pruefe_dinge({"dinge": [person, firma, zweite]}, text)
        self.assertEqual(weg["kunde"], 1)
        self.assertNotIn("4711", str(dinge))
        dinge, weg = wissen_ki.pruefe_dinge({"dinge": [person]}, text)
        self.assertEqual(weg["kunde"], 1)
        ohne_nummer = ding("Person", "Max Mustermann", ("Geburtsdatum", "01.02.1950", "geb. 01.02.1950"))
        _, weg = wissen_ki.pruefe_dinge({"dinge": [ohne_nummer, firma, zweite]}, text)
        self.assertNotIn("kunde", weg)                      # sonst stand „0× Kundennummer …“ in der Statuszeile

    def test_datenschutzhinweis_einer_kanzlei(self):
        # Peters Abnahme W3 (19.11.2026): dieselbe Adresse mit und ohne „D-“ kam zweimal, die Aufsichtsbehörde aus dem
        # Datenschutzhinweis als Eintrag, die Anwälte aus dem Briefkopf vorgehakt, „Spezialgebiet“ neben „Fachgebiet“
        self.assertEqual(wissen_ki.kern("Musterstr. 8, D-12345 Musterstadt"), wissen_ki.kern("Musterstraße 8 12345 Musterstadt"))
        self.assertNotEqual(wissen_ki.kern("Haus D-12"), wissen_ki.kern("Haus 12"))          # nur vor einer Postleitzahl
        text = KANZLEI_TEXT

        def anwalt(name, *fach):
            return ding("Person", name, ("Beruf", "Rechtsanwalt", f"{name} Rechtsanwalt"),
                        *[("Spezialgebiet", f, f) for f in fach])
        antwort = {"dinge": [
            ding("Person", "Max Mustermann",
                 ("Adresse", "Musterstraße 8, D-12345 Musterstadt", "Musterstraße 8, D-12345 Musterstadt"),
                 ("Adresse", "Musterstraße 8, 12345 Musterstadt", "Musterstraße 8, 12345 Musterstadt")),
            ding("Firma", "Kanzlei Muster & Partner", ("Telefon", "01234/1111", "Tel. 01234/1111")),
            anwalt("Anna Muster", "Fachanwältin für Familienrecht"), anwalt("Bernd Beispiel"),
            ding("Behörde", "Landesamt für Datenschutzaufsicht", ("Adresse", "Musterallee 1, 12345 Musterstadt",
                                                                  "Musterallee 1, 12345 Musterstadt"))]}
        dinge, weg = wissen_ki.pruefe_dinge(antwort, text)
        self.assertEqual(weg["aufsicht"], 1)
        self.assertEqual([(d["bezeichnung"], len(d["angaben"]), d["aufgezaehlt"]) for d in dinge],
                         [("Max Mustermann", 1, False), ("Kanzlei Muster & Partner", 1, False),
                          ("Anna Muster", 2, False), ("Bernd Beispiel", 1, False)])      # zwei sind noch keine Aufzählung
        antwort["dinge"].append(anwalt("Carla Probe", "Fachanwältin für Erbrecht"))
        dinge, _ = wissen_ki.pruefe_dinge(antwort, text)
        self.assertEqual([d["aufgezaehlt"] for d in dinge], [False, False, True, True, True])
        # Merkmale auf eine Schreibweise: die im Wiki schon benutzte, sonst die zuerst genannte
        self.assertEqual(wissen.merkmal_kern("Spezialgebiet"), wissen.merkmal_kern("Fachgebiet"))
        wissen_ki.einheitliche_merkmale(dinge, ["Fachgebiet", "Tel."])
        self.assertEqual([a["text"] for d in dinge for a in d["angaben"]][:3],
                         ["Adresse: Musterstraße 8, 12345 Musterstadt", "Tel.: 01234 1111", "Beruf: Rechtsanwalt"])
        self.assertEqual(dinge[2]["angaben"][1]["text"], "Fachgebiet: Fachanwältin für Familienrecht")
        self.assertEqual(wissen_ki.einheitliche_merkmale(
            [ding("Person", "x", ("Spezialgebiet", "a", "a"), ("Fachgebiet", "b", "b"))])[0]["angaben"][1]["merkmal"],
            "Spezialgebiet")

    def test_bekannte_angabe_nur_bei_gleichem_merkmal_und_wert(self):
        # W4: nur dann wird das Dokument eine weitere Quelle - dieselben vier Ziffern reichen nicht
        eintrag = {"angaben": [{"merkmal": "Baujahr", "wert": "1998", "text": "Baujahr: 1998", "zitat": ""},
                               {"merkmal": "Telefon", "wert": "01234 5678", "text": "Telefon: 01234 5678", "zitat": ""}]}

        def a(merkmal, wert):
            return {"merkmal": merkmal, "wert": wert, "text": wissen.angabe_text(merkmal, wert), "zitat": "z"}
        self.assertEqual(wissen_ki.bekannte_angabe(a("Telefonnummer", "01234 5678"), eintrag)["merkmal"], "Telefon")
        self.assertIsNone(wissen_ki.bekannte_angabe(a("Einzug", "1998"), eintrag))
        self.assertIsNone(wissen_ki.bekannte_angabe(a("Baujahr", "1999"), eintrag))
        self.assertIsNone(wissen_ki.bekannte_angabe({"text": "Baujahr: 1998", "zitat": ""}, eintrag))

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
        eins = [{"schublade": "Firma", "bezeichnung": "Muster GmbH", "angaben": [{"text": "Telefon: 1", "zitat": "Tel. 1"}]}]
        zwei = eins + [{"schublade": "Person", "bezeichnung": "Max", "angaben": [{"text": "x", "zitat": "x"}]}]
        g = wd.lege_zusammen([(a, eins, False), (b, zwei, True)])
        self.assertEqual([(x["bezeichnung"], x["schlecht"], len(x["doks"]), len(x["angaben"])) for x in g],
                         [("Muster GmbH", False, 2, 1), ("Max", True, 1, 1)])
        self.assertTrue(wd.lege_zusammen([(b, eins, True), (a, eins, True)])[0]["schlecht"])
        # Peters Abnahme W3: dieselbe Adresse aus zwei Dokumenten, verschieden geschrieben, ist eine Angabe
        def person(merkmal, wert):
            return [{"schublade": "Person", "bezeichnung": "Max", "angaben": [
                {"merkmal": merkmal, "wert": wert, "zitat": wert, "text": wissen.angabe_text(merkmal, wert)}]}]
        g = wd.lege_zusammen([(a, person("Adresse", "Musterstraße 8, D-12345 Musterstadt"), False),
                              (b, person("Anschrift", "Musterstr. 8 12345 Musterstadt"), False),
                              (b, person("Adresse", "Musterstraße 18, 12345 Musterstadt"), False)])
        self.assertEqual([(x["wert"], x["dok"]["rel_path"]) for x in g[0]["angaben"]],
                         [("Musterstraße 8, D-12345 Musterstadt", "a.pdf"), ("Musterstraße 18, 12345 Musterstadt", "b.pdf")])
        # W4: das zweite Dokument geht nicht verloren, es ist eine weitere Quelle mit seinem eigenen Zitat
        self.assertEqual([[(d["rel_path"], z) for d, z in wd.quellen(x)] for x in g[0]["angaben"]],
                         [[("a.pdf", "Musterstraße 8, D-12345 Musterstadt"), ("b.pdf", "Musterstr. 8 12345 Musterstadt")],
                          [("b.pdf", "Musterstraße 18, 12345 Musterstadt")]])
        g = wd.lege_zusammen([(a, person("Adresse", "Musterstraße 8") + person("Anschrift", "Musterstr. 8"), False)])
        self.assertEqual(len(wd.quellen(g[0]["angaben"][0])), 1)               # dasselbe Dokument zählt einmal

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
                     ({"dinge": [ding("Firma", "MUSTER PRÜFDIENST", ("Telefon", "01234/5678", "Tel.: 01234/5678"),
                                      ("zuständig für", "Feuerlöscher", "Muster Prüfdienst Feuerlöscher"))]}, 1.0),
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
                         [("Adresse: Musterweg 17, 12345 Musterstadt", "a.pdf"), ("Telefon: 01234 5678", "a.pdf"),
                          ("zuständig für: Feuerlöscher", "b.pdf")])
        self.assertEqual((firma["angaben"][2]["merkmal"], firma["angaben"][2]["wert"]), ("zuständig für", "Feuerlöscher"))
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
            ding("Person", "Herrn Max Mustermann",
                 ("Adresse", "Musterstraße 8, 12345 Musterstadt", "Musterstraße 8 12345 Musterstadt"),
                 ("Geburtsdatum", "01.02.1950", "geb. 01.02.1950"),
                 ("Kundennummer", "4711", "Kunden-Nr. 4711")),                                  # gehört zur Firma
            ding("Gerät", "Feuerlöscher", ("Prüfgebühr", "16,90 EUR", "Prüfgebühr 16,90 EUR"))]}
        with patch("tools.wiki_dinge.wissen_ki.lies_json", return_value=(antwort, 1.0)):
            f.dinge_lesen([{"rel_path": "Rechnung.pdf", "titel": "Rechnung Prüfdienst"}])
            d = f.dinge
            self.warte(d)
        self.assertEqual((self.dienst.pausen, self.dienst.stand), (1, 0))          # Vollautomatik wartete solange
        self.assertIn("1 Dokument gelesen", d.lbl_status.cget("text"))
        self.assertIn("2× Impressum oder Bankdaten", d.lbl_status.cget("text"))
        zeilen = [d.tree.item(i, "text") for i in d.tree.get_children()]
        self.assertEqual(zeilen, ["☑ Firma: Muster Prüfdienst", "☑ Immobilie: Altes Schloss Musterdorf",
                                  "☑ Person: Herrn Max Mustermann", "☑ Gerät: Feuerlöscher"])
        self.assertEqual([d.tree.set(i, "wert") for i in d.tree.get_children()],
                         ["", "", "schon im Wiki, wird ergänzt", "neue Schublade"])
        # schon im Wiki: anhaken lässt sich nur, was dort noch nicht steht; die Anschrift bekommt eine weitere Quelle (W4)
        self.assertEqual([(d.tree.item(i, "text"), d.tree.set(i, "wert")) for i in d.tree.get_children("d:2")],
                         [("☑ Geburtsdatum", "01.02.1950"),
                          ("✓ Anschrift (schon im Wiki)", "Musterstraße 8, 12345 Musterstadt")])
        self.assertIn("1 Angabe schon im Wiki (nur weiterer Beleg)", d.lbl_status.cget("text"))
        d._schalte("b:2:0")                                                        # hat keinen Haken
        self.assertEqual(d.tree.item("b:2:0", "text"), "✓ Anschrift (schon im Wiki)")
        # Spalte „Dokument“: die Dokument-ID beim Eintrag (hier noch keine), bei der Angabe nur, wenn er mehrere hat
        self.assertEqual(d.tree.item("d:0", "values"), ("", "", "(noch ohne ID)"))
        self.assertEqual((d.tree.item("a:0:1", "text"), d.tree.item("a:0:1", "values")),
                         ("☑ Telefon", ("01234 5678", "„Tel.: 01234/5678“", "")))
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
                         [("Anschrift: Musterweg 17, 12345 Musterstadt", kid, "Musterweg 17 12345 Musterstadt"),
                          ("Kundennummer: 4711", kid, "Kunden-Nr. 4711")])
        # „Adresse“ der KI heißt wie das schon benutzte Merkmal „Anschrift“ (einheitliche_merkmale); die Kundennummer,
        # die die KI bei der Person nannte, steht bei der Firma (Peter 19.11.2026)
        self.assertEqual(([b["titel"] for b in firma["belege"]], sorted(v["bezeichnung"] for v in firma["verbunden"])),
                         (["Rechnung Prüfdienst"], ["Altes Schloss", "Max Mustermann"]))
        person = self.w.lade(max_)
        self.assertEqual([a["text"] for a in person["angaben"]],
                         ["Anschrift: Musterstraße 8, 12345 Musterstadt", "Geburtsdatum: 01.02.1950"])
        self.assertEqual([[(q["kid_id"], q["zitat"]) for q in a["quellen"]] for a in person["angaben"]],
                         [[(kid, "Musterstraße 8 12345 Musterstadt")], [(kid, "geb. 01.02.1950")]])
        self.assertEqual(len(person["belege"]), 1)
        self.assertEqual(f.eintrag["bezeichnung"], "Muster Prüfdienst")            # das Wiki zeigt den ersten

        # Was abgehakt blieb (Telefon, das Gerät mit seiner Prüfgebühr), ist je Dokument als abgelehnt gemerkt
        self.assertEqual(self.w.abgelehnte([kid]), {kid: [{"text": "Telefon: 01234 5678", "zitat": "Tel.: 01234/5678"},
                                                          {"text": "Prüfgebühr: 16,90 EUR", "zitat": "Prüfgebühr 16,90 EUR"}]})

        # Zweiter Lauf über dasselbe Dokument (Peter 13.11.2026): Die umbenannte Immobilie und der umformulierte
        # Firmeneintrag werden wiedererkannt, nichts entsteht doppelt; nur wirklich Neues wird angeboten - Abgelehntes
        # nicht, auch anders formuliert nicht
        self.w.speichere("Firma", "Prüfdienst Muster & Söhne", eintrag_id=firma["id"])
        self.w.angabe_aendern(firma["angaben"][0]["id"], "Sitz im Musterweg 17 in Musterstadt")
        antwort2 = {"dinge": antwort["dinge"][:3] + [
            ding("Gerät", "Feuerlöscher", ("Gebühr", "16,90 EUR", "Prüfgebühr 16,90 EUR"),   # anders benannt, gleiches Zitat
                 ("Standort", "Keller", "Standort Keller"))]}
        antwort2["dinge"][0] = dict(antwort2["dinge"][0], angaben=antwort2["dinge"][0]["angaben"] + [
            {"merkmal": "Telefonnummer", "wert": "01234 5678", "zitat": "Tel.: 01234/5678"}])
        with patch("tools.wiki_dinge.wissen_ki.lies_json", return_value=(antwort2, 1.0)):
            f.dinge_lesen([{"rel_path": "Rechnung.pdf", "titel": "Rechnung Prüfdienst"}])
            d = f.dinge
            self.warte(d)
        self.assertIn("2 früher abgelehnte Angaben ausgeblendet", d.lbl_status.cget("text"))
        # Firma, Schloss und Person samt Angaben und Beleg stehen schon da: ausgeblendet, nicht noch einmal (24.11.2026)
        self.assertIn("3 Einträge ohne Neues ausgeblendet", d.lbl_status.cget("text"))
        self.assertEqual([(d.tree.item(i, "text"), d.tree.set(i, "wert")) for i in d.tree.get_children()],
                         [("☑ Gerät: Feuerlöscher", "neue Schublade")])
        self.assertEqual([(d.tree.item(a, "text"), d.tree.set(a, "wert")) for a in d.tree.get_children("d:0")],
                         [("☑ Standort", "Keller")])
        # von Hand zuordnen: das Gerät gehört zum Schloss - oder wird neu in einer vorhandenen Schublade angelegt
        schloss = next(e for e in self.w.liste() if e["bezeichnung"] == "Altes Schloss")
        d.zuordnen(0, ziel=schloss)
        self.assertEqual((d.tree.item("d:0", "text"), d.tree.set("d:0", "wert")),
                         ("☑ Gerät: Feuerlöscher", "schon im Wiki als „Altes Schloss“, wird ergänzt"))
        d.zuordnen(0, schublade="Sonstiges")
        self.assertEqual((d.tree.item("d:0", "text"), d.tree.set("d:0", "wert")), ("☑ Sonstiges: Feuerlöscher", ""))
        d.zuordnen(0, ziel=schloss)
        d.tree.selection_set("a:0:0")
        d._doppelklick()                                                           # Angabe: ihr Dokument zeigen
        self.assertEqual(self.gezeigt, [self.pdf])
        d._uebernehmen()
        self.assertEqual(self.w.anzahl(), 3)                                       # kein neuer Eintrag
        self.assertEqual([a["text"] for a in self.w.lade(schloss["id"])["angaben"]],
                         ["Feuerlöscher geprüft am: 19.02.2016", "Standort: Keller"])
        self.assertEqual([a["text"] for a in self.w.lade(firma["id"])["angaben"]],
                         ["Kundennummer: 4711", "Sitz im Musterweg 17 in Musterstadt"])   # freie Zeilen zuletzt
        self.assertEqual(len(self.w.abgelehnte([kid])[kid]), 2)                   # nichts abgehakt: nichts dazu

        # Ein Ding, von dem nur Abgelehntes käme, erscheint gar nicht
        with patch("tools.wiki_dinge.wissen_ki.lies_json", return_value=(antwort, 1.0)):
            f.dinge_lesen([{"rel_path": "Rechnung.pdf", "titel": "Rechnung Prüfdienst"}])
            d = f.dinge
            self.warte(d)
        self.assertEqual(d.tree.get_children(), ())
        self.assertIn("Alles davon steht schon im Wiki.", d.lbl_status.cget("text"))
        self.assertEqual(d.ziel, {})
        self.assertEqual(str(d.btn_uebernehmen.cget("state")), "disabled")
        d.destroy()

    def test_ohne_neues_wird_ausgeblendet_und_trotzdem_verbunden(self):
        kid = PDFHandler.ensure_kid_id(self.pdf)
        telefon = ("Telefon", "01234/5678", "Tel.: 01234/5678")
        firma, schloss = self.w.speichere("Firma", "Muster Prüfdienst"), self.w.speichere("Immobilie", "Altes Schloss")
        for e in (firma, schloss):
            self.w.beleg_hinzu(e, kid, "Rechnung")
        self.w.angabe_hinzu(firma, telefon[:2], kid, "Rechnung", telefon[2])
        self.w.angabe_hinzu(schloss, "Feuerlöscher geprüft am 19.02.2016")          # von Hand, sinngleich: kein Neues
        f = wf.WikiFenster(self.app)
        self.addCleanup(lambda: f.winfo_exists() and f.destroy())

        def lies(*dinge):
            with patch("tools.wiki_dinge.wissen_ki.lies_json", return_value=({"dinge": list(dinge)}, 1.0)):
                f.dinge_lesen([{"rel_path": "Rechnung.pdf", "titel": "Rechnung"}])
                self.warte(f.dinge)
            return f.dinge
        alt = [ding("Firma", "Muster Prüfdienst", telefon),
               ding("Immobilie", "Altes Schloss", ("Feuerlöscher geprüft am", "19.02.2016", "Prüf-/Lieferdatum: 19.02.2016"))]
        d = lies(*alt, ding("Gerät", "Feuerlöscher", ("Standort", "Keller", "Standort Keller")))
        self.assertEqual([d.tree.item(i, "text") for i in d.tree.get_children()], ["☑ Gerät: Feuerlöscher"])
        d._uebernehmen()
        geraet = next(e["id"] for e in self.w.liste() if e["bezeichnung"] == "Feuerlöscher")
        self.assertEqual(sorted(v["bezeichnung"] for v in self.w.lade(geraet)["verbunden"]),
                         ["Altes Schloss", "Muster Prüfdienst"])
        self.assertEqual([v["bezeichnung"] for v in self.w.lade(firma)["verbunden"]], ["Feuerlöscher"])   # nicht mit dem Schloss

        # Ist das Dokument noch kein Beleg, bleibt der Eintrag stehen: Übernehmen trägt es ein
        self.w.beleg_weg(self.w.lade(schloss)["belege"][0]["id"])
        d = lies(*alt)
        self.assertEqual([(d.tree.item(i, "text"), d.tree.set(i, "wert")) for i in d.tree.get_children()],
                         [("☑ Immobilie: Altes Schloss", "schon im Wiki, nur weiterer Beleg")])
        self.assertIn("1 Eintrag ohne Neues ausgeblendet", d.lbl_status.cget("text"))
        d.var_verbinden.set(False)
        d._uebernehmen()
        self.assertEqual([b["kid_id"] for b in self.w.lade(schloss)["belege"]], [kid])

        # Ein Dokument ohne Dokument-ID kann noch kein Beleg sein: nichts ausblenden
        with patch.object(wd.DingeFenster, "_kid_id", return_value=""):
            d = lies(*alt)
        self.assertEqual(len(d.tree.get_children()), 2)
        d.destroy()

        # Nicht verbunden wird, was sonst auch keinen Haken hätte (Text schlecht erkannt) - und was inzwischen gelöscht ist
        heft = ding("Heft", "Musterstraße 8", ("Ort", "Musterstadt", "Musterstraße 8 12345 Musterstadt"))
        with patch("tools.wiki_dinge.wissen_ki.text_guete", return_value=0):
            d = lies(*alt, heft)
        self.assertEqual([d.tree.item(i, "text") for i in d.tree.get_children()], ["☐ Heft: Musterstraße 8"])
        d._schalte("d:0")
        d._uebernehmen()
        neu = next(e["id"] for e in self.w.liste() if e["bezeichnung"] == "Musterstraße 8")
        self.assertEqual(self.w.lade(neu)["verbunden"], [])
        self.w.loesche(neu)
        d = lies(*alt, heft)
        self.w.loesche(schloss)
        d._uebernehmen()
        neu = next(e["id"] for e in self.w.liste() if e["bezeichnung"] == "Musterstraße 8")
        self.assertEqual([v["bezeichnung"] for v in self.w.lade(neu)["verbunden"]], ["Muster Prüfdienst"])

    def test_gelesen_nach_der_entscheidung_und_nie_ohne_sie(self):
        """W7b: gelesen ist, worüber entschieden wurde - nicht ein geschlossenes Fenster, nicht was nicht ging."""
        namen = ("Rechnung.pdf", "Zwei.pdf", "Drei.pdf", "Vier.pdf", "Fuenf.pdf")
        for n in namen[1:]:
            with open(os.path.join(self.sammlung, n), "wb") as datei:
                datei.write(pdf_bytes())
        self.app.index_manager.wiki_text = lambda rel: ("" if rel == "Vier.pdf" else TEXT, "")
        self.app.index_manager.text_gilt_weiter = lambda rel, vorher: weiter.append((rel, vorher.st_size))
        weiter, groesse = [], os.path.getsize(self.pdf)
        f = wf.WikiFenster(self.app)
        self.addCleanup(lambda: f.winfo_exists() and f.destroy())
        firma = {"dinge": [ding("Firma", "Muster Prüfdienst", ("Telefon", "01234/5678", "Tel.: 01234/5678"))]}

        def id_von(name):
            return PDFHandler.get_metadata(os.path.join(self.sammlung, name)).get("KID_ID") or ""

        def lies(antworten, dokumente):
            with patch("tools.wiki_dinge.wissen_ki.lies_json", side_effect=antworten):
                f.dinge_lesen([{"rel_path": n, "titel": n} for n in dokumente])
                self.warte(f.dinge)
            return f.dinge
        lies([(firma, 1.0)], namen[:1]).destroy()                                  # geschlossen: nicht gelesen, keine ID
        self.assertEqual((self.w.gelesene(), id_von("Rechnung.pdf")), (set(), ""))
        # Rechnung gibt etwas her, Zwei nichts, Drei scheitert, Vier hat keinen Text - Fuenf kam nicht dran (Abbruch)
        unbrauchbar = wd.wissen_ki.UnbrauchbareAntwort("x")
        d = lies([(firma, 1.0), ({"dinge": []}, 1.0), unbrauchbar], namen[:4])
        self.assertEqual(self.w.gelesene(), set())                                 # erst mit der Entscheidung
        self.assertEqual(f.zuletzt_lesen, {"Drei.pdf"})
        d._schalte("d:0")
        d._uebernehmen()                                                           # „Nichts davon übernehmen“
        self.root.update()
        self.assertFalse(d.winfo_exists())
        self.assertEqual(self.w.anzahl(), 0)
        self.assertEqual(self.w.gelesene(), {id_von("Rechnung.pdf"), id_von("Zwei.pdf")})
        self.assertNotIn("", self.w.gelesene())
        self.assertEqual((id_von("Drei.pdf"), id_von("Vier.pdf")), ("", ""))
        self.assertEqual(weiter, [("Rechnung.pdf", groesse), ("Zwei.pdf", groesse)])   # der erkannte Text gilt weiter
        self.assertEqual(len(self.w.abgelehnte([id_von("Rechnung.pdf")])[id_von("Rechnung.pdf")]), 1)   # trotz neuer ID
        # nichts zu entscheiden: gleich gelesen, Drei ist kein Sorgenkind mehr
        d = lies([({"dinge": []}, 1.0)], ("Drei.pdf",))
        self.assertIn(id_von("Drei.pdf"), self.w.gelesene() - {""})
        self.assertEqual(f.zuletzt_lesen, set())
        self.assertEqual(str(d.btn_uebernehmen.cget("state")), "disabled")
        # ohne Dokument-ID (Datei nicht schreibbar) lässt es sich nicht merken: kommt zuletzt dran
        with patch("tools.wiki_dinge.PDFHandler.ensure_kid_id", return_value=""):
            lies([({"dinge": []}, 1.0)], ("Fuenf.pdf",))
        self.assertEqual((f.zuletzt_lesen, len(self.w.gelesene())), ({"Fuenf.pdf"}, 3))

    def test_aufzaehlung_nicht_vorgehakt_und_spalte_mit_ids(self):
        f = wf.WikiFenster(self.app)
        self.addCleanup(lambda: f.winfo_exists() and f.destroy())
        self.app.index_manager.wiki_text = lambda rel: (KANZLEI_TEXT, "")
        kid = PDFHandler.ensure_kid_id(self.pdf)
        zweites = os.path.join(self.sammlung, "Zweites.pdf")
        shutil.copy(self.pdf, zweites)
        PDFHandler.ensure_kid_id(zweites)                                  # Kopie trägt dieselbe ID - egal hier
        antwort = {"dinge": [ding("Firma", "Kanzlei Muster & Partner", ("Telefon", "01234/1111", "Tel. 01234/1111"))] + [
            ding("Person", name, ("Beruf", "Rechtsanwalt", f"{name} Rechtsanwalt"))
            for name in ("Anna Muster", "Bernd Beispiel", "Carla Probe")]}
        with patch("tools.wiki_dinge.wissen_ki.lies_json", return_value=(antwort, 1.0)):
            f.dinge_lesen([{"rel_path": "Rechnung.pdf", "titel": "Rechnung"}, {"rel_path": "Zweites.pdf", "titel": "Z"}])
            d = f.dinge
            self.warte(d)
        self.assertEqual([d.tree.item(i, "text") for i in d.tree.get_children()],
                         ["☑ Firma: Kanzlei Muster & Partner"] +
                         [f"☐ Person: {n}" for n in ("Anna Muster", "Bernd Beispiel", "Carla Probe")])
        self.assertEqual([d.tree.set(f"d:{n}", "wert") for n in range(4)], [""] + ["aus einer Aufzählung (z.B. Briefkopf)"] * 3)
        self.assertEqual(d.tree.set("d:0", "quelle"), f"{kid} +1")
        self.assertEqual(d.tree.set("a:0:0", "quelle"), f"{kid} +1")             # W4: beide Dokumente sind Quelle
        # Rechtsklick (Peter 19.11.2026): Dokument zeigen, Dokument-ID kopieren - bei mehreren Dokumenten Untermenüs
        d.dinge[0]["angaben"][0]["weitere"] = []                                    # eine Angabe aus einem Dokument
        menue = d.baue_menue("a:0:0")
        self.assertEqual([menue.entrycget(n, "label") for n in range(menue.index("end") + 1)],
                         ["Dokument zeigen", f"Dokument-ID kopieren ({kid})"])
        menue.invoke(1)
        self.assertEqual(d.clipboard_get(), kid)
        menue.invoke(0)
        self.assertEqual(self.gezeigt, [self.pdf])
        menue = d.baue_menue("d:0")
        self.assertEqual([menue.type(n) for n in range(2)], ["cascade", "cascade"])
        unten = d.nametowidget(menue.entrycget(0, "menu"))
        unten.invoke(1)
        self.assertEqual(self.gezeigt, [self.pdf, zweites])
        d._schalte("d:1")                                                          # eine Anwältin doch
        d._uebernehmen()
        self.assertEqual([e["bezeichnung"] for e in self.w.liste()], ["Anna Muster", "Kanzlei Muster & Partner"])
        self.assertEqual(self.w.abgelehnte([kid]), {})                             # nicht vorgehakt: nicht abgelehnt

    def test_mehrere_dokumente_werden_quellen_einer_angabe(self):
        # W4: zwei Dokumente eines Laufs und später ein drittes nennen dieselbe Telefonnummer - eine Angabe, drei Quellen
        pfade = [self.pdf] + [os.path.join(self.sammlung, n) for n in ("Zwei.pdf", "Drei.pdf")]
        for p in pfade[1:]:
            with open(p, "wb") as f:
                f.write(pdf_bytes())
        kids = [PDFHandler.ensure_kid_id(p) for p in pfade]
        self.assertEqual(len(set(kids)), 3)
        doks = [{"rel_path": os.path.basename(p), "titel": os.path.basename(p)[:-4]} for p in pfade]
        f = wf.WikiFenster(self.app)
        self.addCleanup(lambda: f.winfo_exists() and f.destroy())

        def lies(dokumente, *angaben):
            antwort = {"dinge": [ding("Firma", "Muster Prüfdienst", *angaben)]}
            with patch("tools.wiki_dinge.wissen_ki.lies_json", return_value=(antwort, 1.0)):
                f.dinge_lesen(dokumente)
                self.warte(f.dinge)
            return f.dinge
        telefon = ("Telefon", "01234/5678", "Tel.: 01234/5678")
        d = lies(doks[:2], telefon, ("Prüfgebühr", "16,90 EUR", "Prüfgebühr 16,90 EUR"))
        self.assertEqual(d.tree.set("a:0:0", "quelle"), f"{kids[0]} +1")
        self.assertEqual([x["rel_path"] for x in d._doks_der_zeile("a:0:0")], ["Rechnung.pdf", "Zwei.pdf"])
        d._schalte("a:0:1")                                                        # die Gebühr nicht: aus beiden abgelehnt
        d._uebernehmen()
        firma = self.w.liste()[0]["id"]
        self.assertEqual([(a["text"], sorted(q["kid_id"] for q in a["quellen"])) for a in self.w.lade(firma)["angaben"]],
                         [("Telefon: 01234 5678", sorted(kids[:2]))])
        self.assertEqual({k: len(v) for k, v in self.w.abgelehnte(kids).items()}, {kids[0]: 1, kids[1]: 1})

        # Aus zwei Dokumenten abgelehnt, im dritten neu: dort wird es angeboten, mit nur diesem Dokument als Quelle
        d = lies(doks, ("Prüfgebühr", "16,90 EUR", "Prüfgebühr 16,90 EUR"))
        self.assertEqual([(d.tree.item(i, "text"), d.tree.set(i, "quelle")) for i in d.tree.get_children("d:0")],
                         [("☑ Prüfgebühr", kids[2])])
        self.assertEqual(d.dinge[0]["angaben"][0]["dok"]["rel_path"], "Drei.pdf")
        d.destroy()

        d = lies(doks[2:], ("Telefonnummer", "01234/5678", "Tel.: 01234/5678"))    # nur Bekanntes, anders benannt
        self.assertEqual([d.tree.item(i, "text") for i in d.tree.get_children("d:0")], ["✓ Telefon (schon im Wiki)"])
        self.assertEqual(d.baue_menue("b:0:0").entrycget(0, "label"), "Dokument zeigen")
        d._schalte("d:0")                                                          # Eintrag abgewählt
        self.assertEqual((d.btn_uebernehmen.cget("text"), str(d.btn_uebernehmen.cget("state"))),
                         ("Nichts davon übernehmen", "normal"))
        d._schalte("d:0")
        d._uebernehmen()
        eintrag = self.w.lade(firma)
        self.assertEqual([sorted(q["kid_id"] for q in a["quellen"]) for a in eintrag["angaben"]], [sorted(kids)])
        self.assertEqual(sorted(b["kid_id"] for b in eintrag["belege"]), sorted(kids))
        self.assertEqual(self.w.abgelehnte([kids[2]]), {})

        # ab MAX_BELEG_QUELLEN nur noch Quelle, nicht mehr Beleg - auch beim Übernehmen aus dem Dokument
        for n in range(wissen.MAX_BELEG_QUELLEN):
            self.w.angabe_hinzu(firma, ("Telefon", "01234 5678"), f"AAAA-{n:04d}", "x", "y")
        vorher = {b["kid_id"] for b in self.w.lade(firma)["belege"]}
        viertes = os.path.join(self.sammlung, "Vier.pdf")
        with open(viertes, "wb") as datei:
            datei.write(pdf_bytes())
        kid4 = PDFHandler.ensure_kid_id(viertes)
        lies([{"rel_path": "Vier.pdf", "titel": "Vier"}], telefon)._uebernehmen()
        eintrag = self.w.lade(firma)
        self.assertIn(kid4, [q["kid_id"] for q in eintrag["angaben"][0]["quellen"]])
        self.assertEqual({b["kid_id"] for b in eintrag["belege"]}, vorher)
        # noch einmal gelesen: schon Quelle, und Beleg wird es nie - bringt nichts Neues
        d = lies([{"rel_path": "Vier.pdf", "titel": "Vier"}], telefon)
        self.assertIn("1 Eintrag ohne Neues ausgeblendet", d.lbl_status.cget("text"))
        d.destroy()

    def test_schlecht_erkannt_nicht_vorgehakt_ohne_verbinden_und_schliessen_bricht_ab(self):
        f = wf.WikiFenster(self.app)
        self.addCleanup(lambda: f.winfo_exists() and f.destroy())
        self.app.index_manager.wiki_text = lambda rel: (TEXT + " X^y} i*H «BAN O^r Qz{" * 60, "")
        with patch("tools.wiki_dinge.wissen_ki.lies_json", return_value=({"dinge": ANTWORT["dinge"][:2]}, 1.0)):
            f.dinge_lesen([{"rel_path": "Rechnung.pdf", "titel": "Rechnung"}])
            d = f.dinge
            self.warte(d)
        self.assertEqual((d.tree.item("d:0", "text"), d.tree.set("d:0", "wert")),
                         ("☐ Firma: Muster Prüfdienst", "Text schlecht erkannt"))
        self.assertEqual(d.btn_uebernehmen.cget("text"), "Nichts davon übernehmen")
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
