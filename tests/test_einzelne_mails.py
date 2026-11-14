"""Entscheidung E17 (Peter 06.11.2026): Eine einzelne Mail bekommt keinen eigenen Ordner, sondern kommt in die
Sammelablage ihrer Buchstabengruppe - auch beim Mail-Import auf Abruf, wenn das Ziel der Posteingang ist
(KONZEPT_MAIL_AUF_ABRUF F6). E16 (bekannte Absender und die KI-Einstufung) ist mit Bauschritt 4 entfallen."""
import datetime
import os
import shutil
import tempfile
import unittest

import app_paths
import auto_pilot
import mail_import
from pdf_handler import PDFHandler


class _E:
    """Eintrag, wie ihn lies_quelle liefert, ohne Mail."""

    def __init__(self, schluessel, adresse, name="", ergebnis=mail_import.UEBERNEHMEN, anhaenge=0):
        self.schluessel, self.adresse, self.name = schluessel, adresse, name
        self.ergebnis, self.grund, self.pdf_anhaenge = ergebnis, "", anhaenge
        self.vorfilter = ""
        self.richtung = "ein"
        self.datum = datetime.datetime(2024, 3, 5)


class TestEinzelneMailsErkennen(unittest.TestCase):
    def bestand(self, *eintraege):
        b = mail_import.Bestand("x")
        b.eintraege = list(eintraege)
        return b

    def test_einzelne_mail_ohne_anhang(self):
        b = self.bestand(_E("a", "a@eins.example", "Eins"), _E("b", "b@zwei.example", "Zwei"),
                         _E("c", "b@zwei.example", "Zwei"), _E("d", "d@anhang.example", "Anhang", anhaenge=1))
        self.assertEqual(mail_import.einzelne_mails(b), {"a"})

    def test_frueher_importierte_mail_zaehlt_mit(self):
        b = self.bestand(_E("a", "a@eins.example", "Eins"), _E("b", "a@eins.example", "Eins", ergebnis="importiert"))
        self.assertEqual(mail_import.einzelne_mails(b), set())

    def test_mail_ohne_haekchen_zaehlt_nicht(self):
        b = self.bestand(_E("a", "a@eins.example", "Eins"), _E("b", "a@eins.example", "Eins", ergebnis=""))
        self.assertEqual(mail_import.einzelne_mails(b), {"a"})

    def test_zwei_adressen_einer_firma_ohne_namen_zaehlen_zusammen(self):
        b = self.bestand(_E("a", "news@firma.example"), _E("b", "info@firma.example"))
        self.assertEqual(mail_import.einzelne_mails(b), set())

    def test_zwei_personen_beim_selben_mail_anbieter_bleiben_getrennt(self):
        b = self.bestand(_E("a", "erika@gmail.com"), _E("b", "max@gmail.com"))
        self.assertEqual(mail_import.einzelne_mails(b), {"a", "b"})

    def test_vorschau(self):
        b = self.bestand(_E("a", "a@eins.example", "Eins"), _E("b", "b@zwei.example", "Zwei"),
                         _E("c", "b@zwei.example", "Zwei", anhaenge=2), _E("d", "d@bekannt.example", "Bekannt"),
                         _E("e", "e@bekannt.example", "Bekannt"), _E("f", "f@weg.example", "Weg", ergebnis=""))
        v = mail_import.vorschau(b, lambda name, adresse: name == "Bekannt")
        self.assertEqual(v, {"mails": 5, "anhaenge": 2, "einzelne": 1, "neue_ordner": 1})


class TestSammelablage(unittest.TestCase):
    ORDNER = ["A - B - C", "A - B - C\\Altbekannt", "M - N - O"]

    def entscheide(self, absender, einzeln=True, ordner=None, tags=("Rechnung",)):
        ki = {"title": "Titel", "tags": list(tags), "datum": "2024-03-05", "absender": absender,
              "absender_aus_mailkopf": True, "einzelne_mail": einzeln}
        return auto_pilot.baue_entscheidung("x.pdf", ki, self.ORDNER if ordner is None else ordner)

    def test_einzelne_mail_kommt_in_die_sammelablage_ihrer_gruppe(self):
        e = self.entscheide("Musterfirma")
        self.assertEqual(e["zielordner"], os.path.join("M - N - O", auto_pilot.SAMMEL_ORDNER))
        self.assertTrue(e["ordner_neu"])        # angelegt wird sie wie jeder neue Ordner
        self.assertTrue(e["ordner_sammel"])
        self.assertTrue(e["sicher"])

    def test_ohne_buchstabengruppen_liegt_sie_flach(self):
        self.assertEqual(self.entscheide("Musterfirma", ordner=[])["zielordner"], auto_pilot.SAMMEL_ORDNER)

    def test_vorhandener_ordner_geht_vor(self):
        e = self.entscheide("Altbekannt")
        self.assertEqual(e["zielordner"], "A - B - C\\Altbekannt")
        self.assertFalse(e.get("ordner_sammel"))

    def test_ohne_markierung_entsteht_der_eigene_ordner(self):
        e = self.entscheide("Musterfirma", einzeln=False)
        self.assertEqual(e["zielordner"], os.path.join("M - N - O", "Musterfirma"))
        self.assertFalse(e["ordner_sammel"])

    def test_kein_absender_tag_mehr(self):
        # Etappe 6 (FALLSTRICKE #120): auch in der Sammelablage keine Tags von selbst. Gefunden wird die Mail über den
        # Absender trotzdem: Er steht im Mailkopf des PDFs, die Volltextsuche findet ihn
        for einzeln in (True, False):
            self.assertEqual(self.entscheide("Musterfirma", einzeln=einzeln, tags=("Rechnung",))["tags"], [])

    def test_aehnlicher_ordner_loest_bei_einzelner_mail_keine_rueckfrage_aus(self):
        # Peter 06.11.2026: In der Abnahme landeten 2 von 4 einzelnen Mails deswegen in 0_Unsicher. Klare Treffer bleiben, siehe oben
        ordner = ["K - L - M", "K - L - M\\Mustermarkt"]
        e = self.entscheide("Muster-GmbH", einzeln=True, ordner=ordner)
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], os.path.join("K - L - M", auto_pilot.SAMMEL_ORDNER))
        # Ohne Markierung fragt die Vollautomatik weiter nach
        e = self.entscheide("Muster-GmbH", einzeln=False, ordner=ordner)
        self.assertFalse(e["sicher"])
        self.assertIn("Mustermarkt", e["probleme"][0])

    def test_keine_zweitmeinung_zur_sammelablage(self):
        e = self.entscheide("Musterfirma")
        self.assertFalse(auto_pilot.braucht_zweitmeinung(e))
        self.assertEqual(auto_pilot.wende_zweitmeinung_an(e, [("A - B - C\\Altbekannt", 0.99)], self.ORDNER)["zielordner"],
                         e["zielordner"])

    def test_sammelablage_ist_kein_ablageziel_fuer_andere(self):
        # Sonst schickten Gedächtnis und Namensvergleich auch Rechnungen desselben Absenders dorthin
        master = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, master, True)
        os.makedirs(os.path.join(master, "M - N - O", auto_pilot.SAMMEL_ORDNER))
        os.makedirs(os.path.join(master, "M - N - O", "Musterbank"))
        self.assertEqual(auto_pilot.sammle_ordnerliste(master), ["M - N - O", os.path.join("M - N - O", "Musterbank")])

    def test_hand_korrektur_hebt_die_sammelablage_auf(self):
        e = auto_pilot.wende_zielordner_an(self.entscheide("Musterfirma"), "A - B - C\\Altbekannt", self.ORDNER)
        self.assertFalse(e["ordner_sammel"])


class TestDurchlauf(unittest.TestCase):
    def test_import_bis_zur_ablage(self):
        """Die echte Kette ohne KI-Server: Import schreibt das PDF, die Ablage liest die Markierung und verschiebt."""
        from tests.test_mail_import import baue
        basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, basis, True)
        master = os.path.join(basis, "Sammlung")
        for ordner in ("0_Posteingang", "0_Unsicher", "M - N - O"):
            os.makedirs(os.path.join(master, ordner))
        os.makedirs(app_paths.data_dir(master), exist_ok=True)
        quelle = os.path.join(basis, "q")
        os.makedirs(quelle)
        with open(os.path.join(quelle, "1.eml"), "wb") as f:
            f.write(baue(mid="<1@x>", von="Musterfirma <info@musterfirma.example>", betreff="Allein"))
        j = mail_import.Journal(master)
        b = mail_import.lies_quelle(quelle, j)
        b.eintraege[0].ergebnis = mail_import.UEBERNEHMEN
        eingang = os.path.join(master, "0_Posteingang")
        mail_import.importiere(b, j, eingang)
        pdf = os.path.join(eingang, os.listdir(eingang)[0])

        ki = {"title": "Allein", "tags": ["Rechnung"], "datum": "2024-03-05", "absender": "falsch gelesen"}
        ki = auto_pilot.mit_mailkopf(ki, PDFHandler.get_metadata(pdf))
        e = auto_pilot.baue_entscheidung(pdf, ki, auto_pilot.sammle_ordnerliste(master))
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], os.path.join("M - N - O", auto_pilot.SAMMEL_ORDNER))

        def verschieben(von, nach):
            os.makedirs(os.path.dirname(nach), exist_ok=True)
            os.replace(von, nach)
            return True
        ergebnis = auto_pilot.fuehre_entscheidung_aus(e, master, verschieben, still=True)
        self.assertTrue(ergebnis["erfolg"], ergebnis.get("fehler"))
        self.assertEqual(os.path.dirname(ergebnis["neuer_pfad"]), os.path.join(master, "M - N - O", auto_pilot.SAMMEL_ORDNER))
        meta = PDFHandler.get_metadata(ergebnis["neuer_pfad"])
        self.assertEqual(meta["KID_Richtung"], "ein")           # bleibt als Mail erkennbar, auch für „Mails ausblenden“
        self.assertEqual(meta["KID_Absender"], "Musterfirma")
        self.assertTrue(meta["KID_MailID"])
        # Der nächste Durchlauf sieht die Sammelablage nicht als Ziel, auch nicht, wenn sie jetzt existiert
        self.assertNotIn(os.path.join("M - N - O", auto_pilot.SAMMEL_ORDNER), auto_pilot.sammle_ordnerliste(master))


class TestMarkierungImPdf(unittest.TestCase):
    def test_bleibt_im_pdf_lesbar(self):
        subject = PDFHandler.build_kid_subject("2024-03-05", "s", "", "A", "Firma", "", "mid:1@x", "ein", "e", einzeln="1")
        self.assertEqual(PDFHandler.parse_kid_feld(subject, "EINZELN"), "1")
        self.assertEqual(PDFHandler.parse_kid_feld(subject, "RICHTUNG"), "ein")
        self.assertNotIn("EINZELN", PDFHandler.build_kid_subject("2024-03-05", "s"))

    def test_mailkopf_gibt_sie_an_die_entscheidung_weiter(self):
        meta = {"KID_MailID": "mid:1@x", "KID_Richtung": "ein", "KID_Absender": "Firma", "KID_Einzeln": "1"}
        self.assertTrue(auto_pilot.mit_mailkopf({"absender": "x"}, meta)["einzelne_mail"])
        del meta["KID_Einzeln"]
        self.assertFalse(auto_pilot.mit_mailkopf({"absender": "x"}, meta).get("einzelne_mail"))

    def test_import_schreibt_die_markierung(self):
        from tests.test_mail_import import baue
        basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, basis, True)
        quelle, ziel = os.path.join(basis, "q"), os.path.join(basis, "0_Posteingang")
        os.makedirs(quelle), os.makedirs(os.path.join(basis, "Sammlung"))
        for i, (von, betreff) in enumerate((("Eins <a@eins.example>", "Allein"), ("Zwei <b@zwei.example>", "Erste"),
                                            ("Zwei <b@zwei.example>", "Zweite"))):
            with open(os.path.join(quelle, f"{i}.eml"), "wb") as f:
                f.write(baue(mid=f"<{i}@x>", von=von, betreff=betreff))
        master = os.path.join(basis, "Sammlung")
        os.makedirs(app_paths.data_dir(master), exist_ok=True)
        j = mail_import.Journal(master)
        b = mail_import.lies_quelle(quelle, j)
        for e in b.eintraege:
            e.ergebnis = mail_import.UEBERNEHMEN
        mail_import.importiere(b, j, ziel)
        gelesen = {PDFHandler.get_metadata(os.path.join(ziel, n))["title"]: PDFHandler.get_metadata(os.path.join(ziel, n)).get("KID_Einzeln")
                   for n in os.listdir(ziel)}
        self.assertEqual(gelesen, {"Allein": "1", "Erste": "", "Zweite": ""})


if __name__ == "__main__":
    unittest.main()
