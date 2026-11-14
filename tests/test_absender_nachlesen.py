import os
import unittest

from tools.absender_nachlesen import absender_aus_antwort, plane_nachlesen

VKB = os.path.join("S - Z", "Versicherungskasse Musterland")


class TestAbsenderNachlesen(unittest.TestCase):
    def test_plant_nur_abgelegte_ohne_absender(self):
        dokumente = [
            (os.path.join(VKB, "b.pdf"), ""),
            (os.path.join(VKB, "a.pdf"), "  "),
            (os.path.join(VKB, "c.pdf"), "Versicherungskasse"),     # hat schon einen
            (os.path.join("0_Unsicher", "d.pdf"), ""),               # keine Stimme
            (os.path.join("0_Posteingang", "e.pdf"), ""),
            ("f.pdf", ""),                                           # direkt im Hauptordner
        ]
        self.assertEqual(plane_nachlesen(dokumente, [VKB]), [os.path.join(VKB, "a.pdf"), os.path.join(VKB, "b.pdf")])

    def test_absender_wie_in_der_ablage(self):
        self.assertEqual(absender_aus_antwort({"absender": "Bay. LfSt, PF 0151 Straubing"}), "Bay. LfSt")
        self.assertEqual(absender_aus_antwort({"absender": ""}), "")
        self.assertEqual(absender_aus_antwort(None), "")


if __name__ == "__main__":
    unittest.main()
