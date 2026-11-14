"""Tests für den Quellcode-Spiegel in veroeffentlichen.py (Etappe 8, 14.11.2026).

Der Spiegel ist die einzige Stelle, an der Code aus dem privaten Repo öffentlich wird. Wichtig ist darum vor allem:
eine Fundstelle aus der privaten Begriffsliste bricht ab, BEVOR etwas geschrieben wird, und private Arbeitsnotizen
kommen nie mit. Die Beispiel-Begriffe hier sind erfunden.
"""
import os
import re
import tempfile
import unittest
from unittest.mock import patch

import veroeffentlichen as v

REGELN = [re.compile(r"Musterhausen"), re.compile(r"\bErika\b")]


class TestAuswahl(unittest.TestCase):
    def test_arbeitsnotizen_bleiben_privat(self):
        for privat in ("FAHRPLAN.md", "MANUELLE_TESTS.md", "MANUELLE_TESTS_ARCHIV.md", "CLAUDE.md", "ToDo.txt",
                       "KONZEPT_MAIL_IMPORT.md", "ARCHITEKTUR_REVIEW.md", "spikes/x.py", "docs/tests.md"):
            self.assertFalse(v.ist_oeffentlich(privat), privat)
        for oeffentlich in ("src/gui.py", "tests/test_gui.py", "README.md", "FALLSTRICKE_UND_WORKAROUNDS.md",
                            "docs/index.md", "main.py", "icon/app.ico"):
            self.assertTrue(v.ist_oeffentlich(oeffentlich), oeffentlich)

    def test_entwickler_readme_wird_umbenannt(self):
        self.assertEqual(v.zielpfad("README.md"), "ENTWICKLER.md")
        self.assertEqual(v.zielpfad("src/README.md"), "src/README.md")


class TestAnpassen(unittest.TestCase):
    def test_links_auf_private_dateien_werden_text(self):
        text = "Siehe [FAHRPLAN.md](FAHRPLAN.md#etappe-8), [Doku](Projekt-Dokumentation.md) und [x](https://a.b)."
        self.assertEqual(v.anpassen("Projekt-Dokumentation.md", text),
                         "Siehe FAHRPLAN.md, [Doku](Projekt-Dokumentation.md) und [x](https://a.b).")

    def test_python_dateien_bleiben_unveraendert(self):
        text = 'hilfe = "[FAHRPLAN](FAHRPLAN.md)"\n'
        self.assertEqual(v.anpassen("src/x.py", text), text)

    def test_mkdocs_ohne_private_seiten(self):
        index = '{% include-markdown "../README.md" %}\n'
        self.assertEqual(v.anpassen("docs/index.md", index), '{% include-markdown "../ENTWICKLER.md" %}\n')
        nav = "nav:\n  - Start: index.md\n  - Manuelle Tests: tests.md\n  - Changelog: changelog.md\n"
        self.assertEqual(v.anpassen("mkdocs.yml", nav), "nav:\n  - Start: index.md\n  - Changelog: changelog.md\n")

    def test_tote_einbindungen_werden_gefunden(self):
        dateien = {"docs/a.md": b'{% include-markdown "../FAHRPLAN.md" %}', "docs/b.md": b'{% include-markdown "../X.md" %}',
                   "X.md": b"", "mkdocs.yml": b"nav:\n  - A: a.md\n  - C: c.md\n"}
        self.assertEqual(v.tote_einbindungen(dateien), ["docs/a.md -> ../FAHRPLAN.md", "mkdocs.yml -> c.md"])


class TestPruefung(unittest.TestCase):
    def test_fundstellen_nur_als_nummern(self):
        text = "Zeile eins\nIn Musterhausen bei Erika\nCopyright (c) Erika Muster\n"
        self.assertEqual(v.fundstellen("src/a.py", text, REGELN), [(2, 1), (2, 2)])   # Copyright-Zeile ausgenommen (E5)

    def test_auch_der_dateiname_zaehlt(self):
        self.assertEqual(v.fundstellen("tests/test_musterhausen_Musterhausen.py", "", REGELN), [(0, 1)])

    def test_ohne_begriffsliste_kein_spiegel(self):
        with self.assertRaises(SystemExit):
            v.lade_begriffe(os.path.join(tempfile.gettempdir(), "gibt_es_nicht_4711.txt"))

    def test_fundstelle_bricht_ab_bevor_etwas_geschrieben_wird(self):
        stand = {"src/a.py": b"ok\n", "src/b.py": "x = 'Musterhausen'\n".encode("utf-8")}
        stopp = AssertionError("Spiegel hat trotz Fundstelle geschrieben")
        with patch.object(v, "spiegel_stand", return_value=stand), patch.object(v, "lade_begriffe", return_value=REGELN), \
                patch("veroeffentlichen.subprocess.run", side_effect=stopp), \
                patch("veroeffentlichen.os.remove", side_effect=stopp), \
                patch("veroeffentlichen.os.makedirs", side_effect=stopp), \
                patch("builtins.print"):
            with self.assertRaises(SystemExit) as abbruch:
                v.spiegel_fuellen()
        self.assertIn("abgebrochen", str(abbruch.exception))

    def test_nutzer_readme_des_klons_wird_mitgeprueft(self):
        with tempfile.TemporaryDirectory() as klon:
            with open(os.path.join(klon, "README.md"), "w", encoding="utf-8") as f:
                f.write("Grüße aus Musterhausen\n")
            with patch.object(v, "OEFFENTLICH", klon), patch.object(v, "spiegel_stand", return_value={"a.py": b""}), \
                    patch.object(v, "lade_begriffe", return_value=REGELN), patch("builtins.print"):
                with self.assertRaises(SystemExit):
                    v.spiegel_fuellen(nur_pruefen=True)

    def test_binaerdatei_wird_nur_am_namen_geprueft(self):
        with patch("builtins.print"):
            self.assertEqual(v.pruefe_stand({"bilder/a.png": b"\x89PNG\r\n\x00Musterhausen\x81"}, REGELN), 0)
            self.assertEqual(v.pruefe_stand({"Musterhausen.png": b"\x89PNG\x81"}, REGELN), 1)

    def test_release_notizen_werden_geprueft(self):
        with tempfile.TemporaryDirectory() as ordner:
            datei = os.path.join(ordner, "notizen.md")
            with open(datei, "w", encoding="utf-8") as f:
                f.write("Neu: schneller.\n")
            v.pruefe_notizen(datei, "v1.0 - Schneller", REGELN)          # sauber: kein Abbruch
            with patch("builtins.print"):
                with self.assertRaises(SystemExit):
                    v.pruefe_notizen(datei, "v1.0 - Gruß nach Musterhausen", REGELN)
                with open(datei, "a", encoding="utf-8") as f:
                    f.write("Danke an Erika.\n")
                with self.assertRaises(SystemExit):
                    v.pruefe_notizen(datei, "v1.0", REGELN)

    def test_utf16_text_wird_geprueft(self):
        with patch("builtins.print"):
            self.assertEqual(v.pruefe_stand({"notiz.txt": "Gruß aus Musterhausen".encode("utf-16")}, REGELN), 1)


if __name__ == "__main__":
    unittest.main()
