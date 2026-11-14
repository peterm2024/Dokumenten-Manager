import os
import unittest

from tools.gruende_nachtragen import gruende_aus_protokoll, plane_gruende

PROTOKOLL = """\
2026-10-28 14:38  abgelegt  01012024_VER.pdf  ->  U - V\\Versicherungskasse Musterland\\20240528_Beitrag.pdf
2026-10-28 14:38  unsicher  01102024_VER.pdf  ->  0_Unsicher\\01102024_VER.pdf  (Grund: kein plausibles Dokumentdatum erkannt)
2026-10-28 15:34  unsicher  rechnung.pdf  ->  0_Unsicher\\rechnung.pdf  (Grund: Ähnlicher Ordner vorhanden: 'K\\Kehrmann, Fritz (Kaminkehrermeister)' - gehört 'Werner' dorthin?)
2026-10-28 16:00  WARNUNG   KI-Server nicht erreichbar
2026-10-29 09:00  unsicher  01102024_VER.pdf  ->  0_Unsicher\\01102024_VER.pdf  (Grund: kein Zielordner und kein Absender erkannt)
"""


class TestGruendeNachtragen(unittest.TestCase):
    """Gründe der Vollautomatik für Dokumente, die schon vor KID_GRUND in 0_Unsicher lagen (28.10.2026)."""

    def test_protokoll_lesen_juengste_zeile_gewinnt(self):
        gruende = gruende_aus_protokoll(PROTOKOLL)
        self.assertEqual(len(gruende), 2)
        self.assertEqual(gruende[os.path.normcase(os.path.join("0_Unsicher", "01102024_VER.pdf"))],
                         "kein Zielordner und kein Absender erkannt")
        # Klammern IM Grund stören nicht
        self.assertTrue(gruende[os.path.normcase(os.path.join("0_Unsicher", "rechnung.pdf"))].endswith("dorthin?"))

    def test_plan_nur_ohne_gespeicherten_grund(self):
        gruende = gruende_aus_protokoll(PROTOKOLL)
        dokumente = [(os.path.join("0_Unsicher", "01102024_VER.pdf"), ""),
                     (os.path.join("0_Unsicher", "rechnung.pdf"), "schon gespeichert"),
                     (os.path.join("0_Unsicher", "unbekannt.pdf"), "")]
        self.assertEqual(plane_gruende(dokumente, gruende),
                         [(os.path.join("0_Unsicher", "01102024_VER.pdf"), "kein Zielordner und kein Absender erkannt")])

    def test_leeres_protokoll(self):
        self.assertEqual(gruende_aus_protokoll(""), {})
        self.assertEqual(plane_gruende([("0_Unsicher/x.pdf", "")], {}), [])


if __name__ == "__main__":
    unittest.main()
