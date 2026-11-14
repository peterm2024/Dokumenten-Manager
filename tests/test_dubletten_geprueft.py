"""Dubletten-Gedächtnis (dubletten_geprueft.py): Paare merken, Gruppen trennen, Datei-Roundtrip."""
import os
import shutil
import tempfile
import unittest

import dubletten_geprueft


def _gruppe(*ids):
    return ([{"pfad": f"{i or 'ohne'}.pdf", "meta": {"KID_ID": i}} for i in ids], "Text zu 90% gleich", True)


class TestPaare(unittest.TestCase):
    def test_paare_aus_gruppe(self):
        self.assertEqual(dubletten_geprueft.paare_aus(["a", "b", "c"]),
                         {frozenset({"a", "b"}), frozenset({"a", "c"}), frozenset({"b", "c"})})
        self.assertEqual(dubletten_geprueft.paare_aus(["a", "", None]), set())
        self.assertEqual(dubletten_geprueft.paare_aus(["a", "a"]), set())

    def test_ist_geprueft_nur_wenn_alle_paare_gemerkt(self):
        paare = dubletten_geprueft.paare_aus(["a", "b"])
        self.assertTrue(dubletten_geprueft.ist_geprueft(paare, ["a", "b"]))
        self.assertFalse(dubletten_geprueft.ist_geprueft(paare, ["a", "b", "c"]))   # Neuling c
        self.assertFalse(dubletten_geprueft.ist_geprueft(paare, ["a"]))
        self.assertFalse(dubletten_geprueft.ist_geprueft(set(), ["a", "b"]))

    def test_trenne_gruppen(self):
        paare = dubletten_geprueft.paare_aus(["a", "b"])
        offene, geprueft = dubletten_geprueft.trenne_gruppen(
            [_gruppe("a", "b"), _gruppe("a", "b", "c"), _gruppe("x", "")], paare,
            lambda info: info["meta"]["KID_ID"])
        self.assertEqual(len(geprueft), 1)
        self.assertEqual([i["meta"]["KID_ID"] for i in geprueft[0][0]], ["a", "b"])
        self.assertEqual(len(offene), 2)   # Gruppe mit Neuling und Gruppe ohne IDs bleiben offen


class TestDatei(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.master = os.path.join(self.tmp, "Sammlung")
        os.makedirs(self.master)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_merken_laden_vergessen(self):
        self.assertEqual(dubletten_geprueft.lade(self.master), set())
        self.assertTrue(dubletten_geprueft.merke(self.master, ["a", "b", "c"]))
        self.assertTrue(dubletten_geprueft.ist_geprueft(dubletten_geprueft.lade(self.master), ["a", "b", "c"]))
        self.assertTrue(dubletten_geprueft.merke(self.master, ["x", "y"]))
        self.assertEqual(len(dubletten_geprueft.lade(self.master)), 4)
        self.assertTrue(dubletten_geprueft.vergiss(self.master, ["a", "b", "c"]))
        paare = dubletten_geprueft.lade(self.master)
        self.assertEqual(paare, {frozenset({"x", "y"})})
        self.assertFalse(dubletten_geprueft.merke(self.master, ["nur-eine"]))

    def test_kaputte_datei_ist_leer(self):
        import app_paths
        pfad = app_paths.dubletten_geprueft_path(self.master)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        open(pfad, "w", encoding="utf-8").write("{kaputt")
        self.assertEqual(dubletten_geprueft.lade(self.master), set())
