"""Eigenschaften-Panel (dokument_eigenschaften.py): reine Sammel-/Formatierlogik ohne Tkinter."""
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

import dokument_eigenschaften as de


class TestFormatierer(unittest.TestCase):

    def test_pdf_datum(self):
        self.assertEqual(de.formatiere_pdf_datum("D:20240220143300+01'00'"), "20.02.2024 14:33")
        self.assertEqual(de.formatiere_pdf_datum("D:20240220"), "20.02.2024")
        self.assertEqual(de.formatiere_pdf_datum("irgendwas"), "irgendwas")
        self.assertEqual(de.formatiere_pdf_datum(None), "")

    def test_iso_datum_und_groesse(self):
        self.assertEqual(de.formatiere_iso_datum("2024-02-20"), "20.02.2024")
        self.assertEqual(de.formatiere_iso_datum("20.02.2024"), "20.02.2024")
        self.assertEqual(de.formatiere_groesse(845), "845 B")
        self.assertEqual(de.formatiere_groesse(250 * 1024), "250 KB")
        self.assertEqual(de.formatiere_groesse(int(1.25 * 1024 * 1024)), "1,2 MB")
        self.assertEqual(de.formatiere_groesse("x"), "")


class TestSammelnUndFormatieren(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pfad = os.path.join(self.tmp.name, "20240220_Stromrechnung.pdf")
        with open(self.pfad, "wb") as f:
            f.write(b"%PDF-1.4 fake" * 100)

    def test_alle_felder_landen_im_text(self):
        info = {"title": "Stromrechnung", "keywords": "Rechnung, Strom", "author": "E wie einfach",
                "subject": "KID_DATE:2024-02-20", "creator": "Scanner", "producer": "Scanner",
                "creationDate": "D:20240220143300", "modDate": "D:20240301090000",
                "KID_DokumentenDatum": "2024-02-20", "KID_ScanZeitpunkt": "2024-02-20 14:33",
                "seiten": 3, "schutz": "", "fehler": ""}
        e = de.sammle_eigenschaften(self.pfad, r"A - B\E wie einfach\20240220_Stromrechnung.pdf", lese_pdf=lambda p: info)
        self.assertEqual(e["dateiname"], "20240220_Stromrechnung.pdf")
        # Pfad einheitlich mit Systemtrennern, auch wenn der Hauptordner mit Schrägstrichen kam
        gemischt = de.sammle_eigenschaften(self.pfad.replace(os.sep, "/"), "", lese_pdf=lambda p: info)
        self.assertEqual(gemischt["pfad"], os.path.normpath(self.pfad))
        self.assertEqual(e["ordner"], r"A - B\E wie einfach")
        self.assertEqual(e["seiten"], "3")
        self.assertEqual(e["dokumentdatum"], "20.02.2024")
        self.assertEqual(e["erstellt_mit"], "Scanner")   # Creator == Producer nur einmal
        self.assertTrue(e["groesse"].endswith("KB"))
        text = de.formatiere_eigenschaften(e)
        for erwartet in ("Dateiname:", "20240220_Stromrechnung.pdf", "Ordner:", "Pfad:", self.pfad,
                         "Seiten: 3", "Dokumentdatum: 20.02.2024", "Scan-Zeitpunkt: 2024-02-20 14:33",
                         "Titel (PDF):", "Stromrechnung", "Tags (PDF):", "Rechnung, Strom",
                         "Autor: E wie einfach", "Betreff: KID_DATE:2024-02-20",
                         "Erstellt mit: Scanner", "PDF-Datum: 20.02.2024 14:33", "PDF geändert: 01.03.2024 09:00"):
            self.assertIn(erwartet, text)
        self.assertNotIn("Schutz:", text)
        self.assertNotIn("Hinweis:", text)

    def test_leere_felder_werden_ausgelassen_und_schutz_gezeigt(self):
        info = {"seiten": 1, "schutz": "signiert", "fehler": ""}
        e = de.sammle_eigenschaften(self.pfad, "x.pdf", lese_pdf=lambda p: info)
        text = de.formatiere_eigenschaften(e)
        self.assertIn("Ordner:         (Hauptordner)", text)
        self.assertIn("Schutz:         signiert", text)
        self.assertNotIn("Titel (PDF)", text)
        self.assertNotIn("Autor", text)

    def test_fehlende_datei_und_lesefehler_werfen_nicht(self):
        e = de.sammle_eigenschaften(os.path.join(self.tmp.name, "gibt-es-nicht.pdf"), "", lese_pdf=lambda p: {})
        self.assertTrue(e["fehler"].startswith("Datei nicht lesbar"))
        self.assertIn("Hinweis:", de.formatiere_eigenschaften(e))

        def kaputt(p):
            raise RuntimeError("PyMuPDF weg")
        e = de.sammle_eigenschaften(self.pfad, "", lese_pdf=kaputt)
        self.assertEqual(e["fehler"], "PyMuPDF weg")
        self.assertEqual(de.formatiere_eigenschaften({}), "")


class TestAufteilungUndPackregel(unittest.TestCase):
    """Feldaufteilung (Einstellung eigenschaften_felder) und die gierige Packregel der Tabelle."""

    def test_standard_ohne_einstellung_und_bei_muell(self):
        for wert in (None, "", 42, ["datum"]):
            a = de.feldaufteilung(wert)
            self.assertEqual(a["immer"], de.STANDARD_AUFTEILUNG["immer"])
            self.assertEqual(a["nie"], de.STANDARD_AUFTEILUNG["nie"])
        # Jedes Feld des Katalogs kommt im Standard genau einmal vor
        alle = sum((de.STANDARD_AUFTEILUNG[z] for z in de.ZONEN), [])
        self.assertEqual(sorted(alle), sorted(de.FELDER))

    def test_unbekannte_fliegen_raus_fehlende_kommen_nach_ausgeklappt(self):
        a = de.feldaufteilung({"immer": ["seiten", "gibt_es_nicht", "seiten"], "ausgeklappt": ["pfad"], "nie": ["titel"]})
        self.assertEqual(a["immer"], ["seiten", "datum"])          # datum erzwungen (hinten), Dublette weg
        self.assertEqual(a["ausgeklappt"][0], "pfad")
        self.assertIn("dateiname", a["ausgeklappt"])               # nicht genannt -> hinten in ausgeklappt
        self.assertEqual(a["nie"], ["titel"])
        self.assertNotIn("gibt_es_nicht", sum((a[z] for z in de.ZONEN), []))

    def test_datum_laesst_sich_nicht_verstecken_aber_im_block_verschieben(self):
        a = de.feldaufteilung({"immer": ["seiten"], "ausgeklappt": [], "nie": ["datum"]})
        self.assertEqual(a["immer"], ["seiten", "datum"])   # zurück ans Ende von „immer“
        self.assertNotIn("datum", a["nie"])
        a = de.feldaufteilung({"immer": ["seiten", "groesse", "datum"], "ausgeklappt": [], "nie": []})
        self.assertEqual(a["immer"], ["seiten", "groesse", "datum"])   # Position im Block bleibt

    def test_packregel_gierig(self):
        zeilen = de.packe_zeilen(["datum", "scan_zeitpunkt", "seiten", "groesse", "dateiname", "originalname",
                                  "ordner", "geaendert", "autor", "erstellt", "pfad"])
        self.assertEqual(zeilen, [
            [("datum", 2), ("scan_zeitpunkt", 2), ("seiten", 2), ("groesse", 2)],
            [("dateiname", 4), ("originalname", 4)],
            [("ordner", 8)],
            [("geaendert", 2), ("autor", 4), ("erstellt", 2)],
            [("pfad", 8)],
        ])
        self.assertEqual(de.packe_zeilen([]), [])
        # Zu breite Felder werden auf die Zeilenbreite gekappt
        self.assertEqual(de.packe_zeilen(["pfad"], paare_je_zeile=2), [[("pfad", 2)]])
        # Achtel: acht Felder nebeneinander
        acht = de.packe_zeilen(["seiten"] * 8, breiten={"seiten": 1})
        self.assertEqual(len(acht), 1)
        self.assertEqual(len(acht[0]), 8)

    def test_liste_mit_trennern_hin_und_zurueck(self):
        liste = de.aufteilung_als_liste(de.STANDARD_AUFTEILUNG)
        self.assertEqual(liste[0], "datum")
        self.assertEqual(liste.count("__ausgeklappt__"), 1)
        self.assertEqual(liste.count("__nie__"), 1)
        self.assertLess(liste.index("__ausgeklappt__"), liste.index("__nie__"))
        self.assertEqual(de.liste_als_aufteilung(liste), de.feldaufteilung(de.STANDARD_AUFTEILUNG))
        # Ein Feld unter den zweiten Trenner geschoben -> Zone „nie“; datum bleibt trotzdem oben
        liste.remove("seiten")
        liste.append("seiten")
        liste.remove("datum")
        liste.insert(liste.index("__nie__") + 1, "datum")
        a = de.liste_als_aufteilung(liste)
        self.assertIn("seiten", a["nie"])
        self.assertEqual(a["immer"][-1], "datum")
        self.assertEqual(de.anzeigetext("__nie__"), de.TRENNER_TEXTE["__nie__"])
        self.assertEqual(de.anzeigetext("groesse"), "Größe  ¼")
        self.assertEqual(de.anzeigetext("groesse", {"groesse": 8}), "Größe  1")
        self.assertEqual(de.anzeigetext("groesse", {"groesse": 1}), "Größe  ⅛")

    def test_breiten_einstellbar(self):
        a = de.feldaufteilung({"immer": ["datum"], "paare_je_zeile": 8,
                               "breiten": {"autor": 8, "pfad": 3, "unbekannt": 2, "seiten": True}})
        self.assertEqual(a["breiten"]["autor"], 8)        # gültige Stufe übernommen
        self.assertEqual(a["breiten"]["pfad"], 8)         # 3 ist keine Stufe -> Standard
        self.assertEqual(a["breiten"]["seiten"], 2)       # True ist kein Wert -> Standard
        self.assertEqual(a["breiten"]["groesse"], 2)      # nicht genannt -> Standard
        self.assertNotIn("unbekannt", a["breiten"])
        self.assertEqual(a["paare_je_zeile"], 8)
        # Altformat vom 15.09. (4 Paare je Zeile, ohne Marke): Werte werden verdoppelt
        alt = de.feldaufteilung({"immer": ["datum"], "breiten": {"autor": 4, "seiten": 1}})
        self.assertEqual((alt["breiten"]["autor"], alt["breiten"]["seiten"]), (8, 2))
        self.assertEqual(de.naechste_breite(1, 1), 2)
        self.assertEqual(de.naechste_breite(4, 1), 6)
        self.assertEqual(de.naechste_breite(6, 1), 8)
        self.assertEqual(de.naechste_breite(8, 1), 8)
        self.assertEqual(de.anzeigetext("autor", {"autor": 6}), "Autor  ¾")
        # ¾ + ¼ füllen eine Zeile genau
        self.assertEqual(de.packe_zeilen(["autor", "seiten"], breiten={"autor": 6}), [[("autor", 6), ("seiten", 2)]])
        self.assertEqual(de.naechste_breite(1, -1), 1)
        # Packregel mit eigenen Breiten: Autor auf ganze Zeile, Dateiname auf ⅛
        zeilen = de.packe_zeilen(["dateiname", "autor", "seiten"], breiten={"autor": 8, "dateiname": 1})
        self.assertEqual(zeilen, [[("dateiname", 1)], [("autor", 8)], [("seiten", 2)]])
        # Breiten überleben den Weg über die Liste (mit Marke, also keine Verdopplung)
        b = de.liste_als_aufteilung(de.aufteilung_als_liste(a), breiten=a["breiten"])
        self.assertEqual(b["breiten"]["autor"], 8)



class TestMailBezug(unittest.TestCase):
    """Peter 05.11.2026: der Bezug zwischen Mail und Anhang bleibt sichtbar, auch über Ordner hinweg."""
    MAIL = ("Musterbank\\20240412_Kontoauszug.pdf",
            {"title": "Ihr Kontoauszug", "KID_Richtung": "ein", "KID_DokumentenDatum": "2024-04-12"})
    ANHANG = ("Rechnungen\\20240412_Beleg.pdf", {"title": ""})

    def test_anhang_zeigt_seine_mail(self):
        self.assertEqual(de.mail_bezug(False, [self.MAIL]),
                         ("Anhang der Mail:", [("Ihr Kontoauszug, 12.04.2024", self.MAIL[0])]))
        # weitere Anhänge derselben Mail sind kein Link beim Anhang
        self.assertEqual(de.mail_bezug(False, [self.ANHANG, self.MAIL])[1], [("Ihr Kontoauszug, 12.04.2024", self.MAIL[0])])

    def test_mail_zeigt_ihre_anhaenge_titel_sonst_dateiname(self):
        benannt = ("A\\x.pdf", {"title": "Rechnung 42"})
        self.assertEqual(de.mail_bezug(True, [benannt, self.ANHANG]),
                         ("Anhänge:", [("Rechnung 42", "A\\x.pdf"), ("20240412_Beleg", self.ANHANG[0])]))

    def test_mail_ohne_anhaenge_hat_keinen_bezug(self):
        self.assertEqual(de.mail_bezug(True, []), ("", []))

    def test_anhang_ohne_mail_sagt_das(self):
        vorspann, links = de.mail_bezug(False, [])
        self.assertIn("nicht mehr in der Sammlung", vorspann)
        self.assertEqual(links, [])

    def test_sammeln_liefert_mail_id_und_art(self):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"x")
        try:
            e = de.sammle_eigenschaften(f.name, "x.pdf", lambda _p: {"KID_MailID": "mid:1@x", "KID_Richtung": "ein"})
            self.assertEqual((e["mail_id"], e["ist_mail"]), ("mid:1@x", True))
            e = de.sammle_eigenschaften(f.name, "x.pdf", lambda _p: {"title": "Scan"})
            self.assertEqual((e["mail_id"], e["ist_mail"]), ("", False))
        finally:
            os.remove(f.name)


class TestOriginalMail(unittest.TestCase):
    """Peter 05.11.2026: die eingebettete Original-Mail lässt sich aus KID heraus öffnen."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patcher = patch("dokument_eigenschaften.tempfile.gettempdir", return_value=self.tmp)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_mail_kommt_unveraendert_in_den_temp_ordner(self):
        with patch("dokument_eigenschaften.PDFHandler.hole_eml", return_value=b"Subject: Test\r\n\r\nText"):
            pfad = de.original_mail_bereitstellen(os.path.join("Ablage", "20240412_Rechnung.pdf"))
        self.assertEqual(pfad, os.path.join(self.tmp, de.ORDNER_ORIGINAL_MAILS, "20240412_Rechnung.eml"))
        with open(pfad, "rb") as f:
            self.assertEqual(f.read(), b"Subject: Test\r\n\r\nText")
        de.raeume_original_mails_auf()
        self.assertFalse(os.path.exists(pfad))

    def test_ohne_original_mail_entsteht_nichts(self):
        with patch("dokument_eigenschaften.PDFHandler.hole_eml", return_value=None):
            self.assertIsNone(de.original_mail_bereitstellen("scan.pdf"))
        self.assertEqual(os.listdir(self.tmp), [])

    def test_reste_frueherer_sitzungen_verschwinden_und_beenden_raeumt_auf(self):
        rest = os.path.join(self.tmp, de.ORDNER_ORIGINAL_MAILS, "alt.eml")
        os.makedirs(os.path.dirname(rest))
        with open(rest, "w") as f:
            f.write("alt")
        with (patch("dokument_eigenschaften.PDFHandler.hole_eml", return_value=b"neu"),
              patch("dokument_eigenschaften._aufraeumen_vorgemerkt", False),
              patch("dokument_eigenschaften.atexit.register") as beim_beenden):
            pfad = de.original_mail_bereitstellen("neu.pdf")
            de.original_mail_bereitstellen("zweite.pdf")
        self.assertFalse(os.path.exists(rest))
        self.assertTrue(os.path.exists(pfad))
        self.assertTrue(os.path.exists(os.path.join(os.path.dirname(pfad), "zweite.eml")))   # die erste bleibt offen
        beim_beenden.assert_called_once_with(de.raeume_original_mails_auf)

    def test_echtes_mail_pdf_gibt_die_mail_zurueck(self):
        import mail_lesen
        from pdf_handler import PDFHandler
        eml = (b"From: Muster <a@firma.example>\r\nTo: b@beispiel.example\r\nSubject: Test\r\n"
               b"Date: Fri, 12 Apr 2024 10:00:00 +0200\r\nMessage-ID: <1@firma.example>\r\n"
               b"Content-Type: text/plain; charset=utf-8\r\n\r\nHallo\r\n")
        mail = mail_lesen.Mail(eml)
        stile, seite, bilder = mail_lesen.seite_html(mail, "ein")
        pdf = os.path.join(self.tmp, "mail.pdf")
        PDFHandler.schreibe_mail_pdf(pdf, seite, stile, bilder, mail.daten, {"title": "Test"})
        with open(de.original_mail_bereitstellen(pdf), "rb") as f:
            self.assertEqual(f.read(), eml)


class TestDokumentStatus(unittest.TestCase):
    """Peter 28.10.2026: in den Details vermerken, warum ein Dokument unsicher bzw. orange ist."""

    def test_vorgelegt_nur_in_0_unsicher(self):
        info = {"title": "", "keywords": "", "KID_DokumentenDatum": "", "KID_Grund": "kein Zielordner erkannt"}
        status = de.dokument_status(info, os.path.join("0_Unsicher", "brief.pdf"))
        self.assertIn("Von der Vollautomatik zur Prüfung vorgelegt", status)
        self.assertIn("Ablage-Vorschau", status)
        self.assertTrue(status.split(de._TRENNER)[0].endswith(": kein Zielordner erkannt"))
        self.assertIn("Unbearbeitet", status)
        self.assertNotIn("Vollautomatik", de.dokument_status(info, os.path.join("Versicherung", "brief.pdf")))

    def test_datum_nur_vermutet(self):
        info = {"title": "Kontoauszug Januar 2025", "keywords": "", "KID_DokumentenDatum": ""}
        self.assertEqual(de.dokument_status(info, "konto.pdf"), "Datum nur vermutet (orange hinterlegt) - noch nicht gespeichert")

    def test_erledigt_leer(self):
        info = {"title": "Kontoauszug", "keywords": "Bank", "KID_DokumentenDatum": "2025-01-31"}
        self.assertEqual(de.dokument_status(info, "konto.pdf"), "")

    def test_unsicher_ordner_wie_in_der_vollautomatik(self):
        import auto_pilot
        self.assertEqual(de.UNSICHER_ORDNER, auto_pilot.UNSICHER_ORDNER)


if __name__ == "__main__":
    unittest.main()
