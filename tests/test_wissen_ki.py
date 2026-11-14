"""Wiki von Hand: Anbindung der KI (wissen_ki), ohne KI-Server. Nur Musterdaten."""
import json
import unittest
from unittest.mock import patch

import wissen_ki


class TestKiAufruf(unittest.TestCase):
    def test_dauer(self):
        self.assertEqual(wissen_ki.dauer_text(3), "etwa 10 Sekunden")
        self.assertEqual(wissen_ki.dauer_text(45), "etwa 40 Sekunden")
        self.assertEqual(wissen_ki.dauer_text(61), "etwa 1 Minute")
        self.assertEqual(wissen_ki.dauer_text(300), "etwa 5 Minuten")

    def test_json_repariert_wiederholt_oder_unbrauchbar(self):
        ok = json.dumps({"vorschlaege": [{"feld": "modell", "wert": "VW Golf", "zitat": "VW Golf"}]})
        with patch("wissen_ki.ollama_client._generate", return_value={"response": ok}) as gen:
            self.assertEqual(wissen_ki.lies_json("p", "u", "m")[0]["vorschlaege"][0]["wert"], "VW Golf")
        payload = gen.call_args[0][0]
        self.assertEqual((payload["format"], payload["options"]["temperature"]), ("json", 0))
        with patch("wissen_ki.ollama_client._generate", return_value={"response": ok[:-12]}) as gen:  # abgeschnitten
            self.assertEqual(wissen_ki.lies_json("p", "u", "m")[0]["vorschlaege"][0]["wert"], "VW Golf")
        gen.assert_called_once()                                                # gerettet, nicht wiederholt
        with patch("wissen_ki.ollama_client._generate", side_effect=[{"response": "Unsinn"}, {"response": ok}]) as gen:
            self.assertIn("vorschlaege", wissen_ki.lies_json("p", "u", "m")[0])
        self.assertEqual(gen.call_args[0][0]["options"]["temperature"], 0.2)
        with patch("wissen_ki.ollama_client._generate", return_value={"response": "Unsinn"}):
            with self.assertRaises(wissen_ki.UnbrauchbareAntwort):
                wissen_ki.lies_json("p", "u", "m")

    def test_rette_json(self):
        self.assertIsNone(wissen_ki.rette_json('{"art": "Rech'))
        self.assertIsNone(wissen_ki.rette_json(""))
        self.assertEqual(wissen_ki.rette_json('{"art": "Brief", "worum": "Sch'), {"art": "Brief"})
        self.assertEqual(wissen_ki.rette_json('{"dinge": [{"a": 1}, {"a": 2}, {"a": "abgeschn'), {"dinge": [{"a": 1}, {"a": 2}]})

    def test_zitat_und_zugangsdaten(self):
        text = "Prüf-/Lieferdatum:  19.02.2016\nMenge   Bezeichnung   Preis\n1   Feuerlöscher prüfen   16,90"
        self.assertTrue(wissen_ki.zitat_im_text("Prüf- / Lieferdatum: 19.02.2016", text))      # Satzzeichen egal
        self.assertFalse(wissen_ki.zitat_im_text("Lieferdatum 20.02.2016", text))
        self.assertFalse(wissen_ki.zitat_im_text("", text))
        self.assertTrue(wissen_ki.beleg_nahe("Feuerlöscher prüfen Preis 16,90", text))          # aus Spalten zusammengesetzt
        self.assertFalse(wissen_ki.beleg_nahe("Feuerlöscher prüfen 17,90", text))
        self.assertFalse(wissen_ki.beleg_nahe("Feuerlöscher prüfen 16,90", text + " " * 600, fenster=5))
        self.assertFalse(wissen_ki.beleg_nahe("", text))
        for wort in ("Ihr Passwort: geheim", "PIN 1234", "Aktivierungscode", "Benutzername max", "PUK 99"):
            self.assertTrue(wissen_ki.ZUGANG.search(wort), wort)
        self.assertIsNone(wissen_ki.ZUGANG.search("Pinsel und Spinat, Tante Erna"))


if __name__ == "__main__":
    unittest.main()
