"""Der eigene Name ist kein Tag (FALLSTRICKE #114): In der Abnahme vom 06.11.2026 trug die KI den Empfänger an fast jede Mail."""
import os
import shutil
import tempfile
import unittest

import app_paths
import auto_pilot
import personen_namen
import mail_import
import mail_lesen
from pdf_handler import PDFHandler
from tests.test_mail_import import baue


class TestEigeneNamen(unittest.TestCase):
    def namen(self, an, von="Firma <info@firma.example>", eigene=("max@example.org",)):
        return mail_lesen.eigene_namen(mail_lesen.Mail(baue(von=von, an=an)), set(eigene))

    def test_name_des_eigenen_empfaengers(self):
        self.assertEqual(self.namen("Max Mustermann <max@example.org>"), "Max Mustermann")

    def test_fremde_empfaenger_zaehlen_nicht(self):
        self.assertEqual(self.namen("Erika Beispiel <erika@example.org>, Max Mustermann <max@example.org>"), "Max Mustermann")

    def test_gesendete_mail_hat_den_eigenen_namen_im_absender(self):
        self.assertEqual(self.namen("Firma <info@firma.example>", von="Max Mustermann <max@example.org>"), "Max Mustermann")

    def test_vorname_nachname_aus_der_adresse(self):
        self.assertEqual(self.namen("max.mustermann@example.org", eigene=("max.mustermann@example.org",)), "max.mustermann")

    def test_ein_allgemeines_postfach_ist_kein_name(self):
        # sonst verlöre jede Mail an info@… ihr Tag „Info“
        self.assertEqual(self.namen("info@example.org", eigene=("info@example.org",)), "")

    def test_eigene_domain_gilt(self):
        self.assertEqual(self.namen("Max Mustermann <max@example.org>", eigene=("@example.org",)), "Max Mustermann")


class TestTags(unittest.TestCase):
    META = {"KID_MailID": "mid:1@x", "KID_Richtung": "ein", "KID_Absender": "Firma", "KID_Eigen": "Max Mustermann;max.mustermann"}

    def tags(self, *tags, meta=None):
        return auto_pilot.mit_mailkopf({"absender": "x", "tags": list(tags)}, meta or self.META)["tags"]

    def test_eigener_name_faellt_heraus(self):
        self.assertEqual(self.tags("Rechnung", "Max Mustermann", "Strom"), ["Rechnung", "Strom"])

    def test_schreibweise_und_reihenfolge_egal(self):
        self.assertEqual(self.tags("Rechnung", "MUSTERMANN, Max", "max.mustermann"), ["Rechnung"])

    def test_teile_des_namens_bleiben(self):
        # „Familie“ aus „Familie Mustermann“ oder „Info“ dürfen nicht verschwinden
        meta = dict(self.META, KID_Eigen="Familie Mustermann")
        self.assertEqual(self.tags("Familie", "Mustermann", meta=meta), ["Familie", "Mustermann"])

    def test_andere_personen_bleiben(self):
        self.assertEqual(self.tags("Erika Beispiel"), ["Erika Beispiel"])

    def test_empfaenger_feld_der_ki(self):
        # Der eigentliche Weg: Aus dem KI-Feld „empfaenger“ werden gewollt Personen-Tags (Nutzerwunsch 30.08.2026)
        def empfaenger(text):
            return auto_pilot.mit_mailkopf({"absender": "x", "empfaenger": text}, self.META)["empfaenger"]
        self.assertEqual(empfaenger("Max Mustermann"), "")
        self.assertEqual(empfaenger("Herrn Max Mustermann"), "")
        self.assertEqual(empfaenger("Erika Beispiel"), "Erika Beispiel")
        self.assertEqual(personen_namen.teile_empfaenger(empfaenger("Max Mustermann und Erika Beispiel")), ["Erika Beispiel"])

    def test_ohne_feld_und_bei_anhaengen_unveraendert(self):
        self.assertEqual(self.tags("Max Mustermann", meta={"KID_MailID": "mid:1@x", "KID_Richtung": "ein"}), ["Max Mustermann"])
        self.assertEqual(self.tags("Max Mustermann", meta={"KID_MailID": "mid:1@x", "KID_Eigen": "Max Mustermann"}),
                         ["Max Mustermann"])


class TestDurchlauf(unittest.TestCase):
    def test_vom_import_bis_zur_entscheidung(self):
        basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, basis, True)
        master = os.path.join(basis, "Sammlung")
        eingang, quelle = os.path.join(master, "0_Posteingang"), os.path.join(basis, "q")
        os.makedirs(eingang), os.makedirs(quelle), os.makedirs(os.path.join(master, "M - N - O"))
        os.makedirs(app_paths.data_dir(master), exist_ok=True)
        with open(os.path.join(quelle, "1.eml"), "wb") as f:
            f.write(baue(mid="<1@x>", von="Musterfirma <info@musterfirma.example>", an="Max Mustermann <max@example.org>"))
        j = mail_import.Journal(master)
        j.eigene = ["max@example.org"]
        b = mail_import.lies_quelle(quelle, j)
        b.eintraege[0].ergebnis = mail_import.UEBERNEHMEN
        mail_import.importiere(b, j, eingang)
        pdf = os.path.join(eingang, os.listdir(eingang)[0])

        ki = {"title": "Rechnung", "tags": ["Rechnung", "Max Mustermann"], "datum": "2024-03-05", "absender": "x",
              "empfaenger": "Max Mustermann"}
        e = auto_pilot.baue_entscheidung(pdf, auto_pilot.mit_mailkopf(ki, PDFHandler.get_metadata(pdf)),
                                         auto_pilot.sammle_ordnerliste(master))
        self.assertEqual(e["tags"], [])      # seit Etappe 6 gar keine KI-Tags, der eigene Name also erst recht nicht


if __name__ == "__main__":
    unittest.main()
