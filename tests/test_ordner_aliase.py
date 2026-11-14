"""
Tests für die Absender-Aliase der Vollautomatik (ordner_aliase.py) und ihre
Anbindung in auto_pilot (Alias-Vorrang, Zielordner-Korrektur durch den Nutzer).
"""

import json
import os
import shutil
import tempfile
import unittest

import app_paths
import auto_pilot
import ordner_aliase

VKB = "V - W - X - Y - Z\\Versicherungskasse Musterland"
ORDNER = ["A - B - C", "G - H - I", "V - W - X - Y - Z", VKB, "G - H - I\\Gentilia"]


class TestFindeAlias(unittest.TestCase):
    """Reine Nachschlage-Logik ohne Dateisystem."""

    def setUp(self):
        self.aliase = {"Bayerische Landesbrandversicherung": VKB, "KM": "A - B - C\\Kehrmann, Fritz"}

    def test_exakter_treffer_gross_klein_egal(self):
        self.assertEqual(ordner_aliase.finde_alias("bayerische  landesbrandversicherung", self.aliase), VKB)

    def test_teilstring_in_beide_richtungen(self):
        self.assertEqual(ordner_aliase.finde_alias("Bayerische Landesbrandversicherung AG", self.aliase), VKB)
        self.assertEqual(ordner_aliase.finde_alias("Landesbrandversicherung", self.aliase), VKB)

    def test_kurze_schluessel_nur_exakt(self):
        # "KM" steckt in vielen Wörtern - als Teilstring wäre das ein Fehlalarm-Generator.
        self.assertEqual(ordner_aliase.finde_alias("KM", self.aliase), "A - B - C\\Kehrmann, Fritz")
        self.assertIsNone(ordner_aliase.finde_alias("Stadtwerke Musterstadt KM", self.aliase))

    def test_kein_treffer_und_leere_eingaben(self):
        self.assertIsNone(ordner_aliase.finde_alias("Gentilia", self.aliase))
        self.assertIsNone(ordner_aliase.finde_alias("", self.aliase))
        self.assertIsNone(ordner_aliase.finde_alias("Gentilia", {}))
        self.assertIsNone(ordner_aliase.finde_alias("Gentilia", None))

    def test_laengster_teilstring_gewinnt(self):
        aliase = {"Versicherung": "Allgemein", "Landesbrandversicherung": VKB}
        self.assertEqual(ordner_aliase.finde_alias("Bayerische Landesbrandversicherung", aliase), VKB)


class TestLoeseAliasOrdner(unittest.TestCase):
    def test_vorhandener_ordner_bleibt(self):
        self.assertEqual(ordner_aliase.loese_alias_ordner(VKB, ORDNER), VKB)

    def test_verschobener_ordner_wird_ueber_namen_gefunden(self):
        # Nutzer hat den Ordner in eine andere Buchstabengruppe geschoben
        self.assertEqual(ordner_aliase.loese_alias_ordner("A - B - C\\Versicherungskasse Musterland", ORDNER), VKB)

    def test_unbekannter_ordner_kommt_unveraendert_zurueck(self):
        self.assertEqual(ordner_aliase.loese_alias_ordner("Neu\\Ordner", ORDNER), "Neu\\Ordner")


class TestLadenUndSpeichern(unittest.TestCase):
    """aliase.json im Daten-Ordner der Sammlung."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.master = os.path.join(self.tmp, "KID")
        os.makedirs(self.master)

    def test_ohne_datei_leeres_dict(self):
        self.assertEqual(ordner_aliase.lade_aliase(self.master), {})

    def test_speichern_legt_datei_im_daten_ordner_an_und_laedt_sie_wieder(self):
        ordner_aliase.speichere_alias(self.master, "Bayerische Landesbrandversicherung", VKB)
        pfad = app_paths.aliase_path(self.master)
        self.assertTrue(os.path.isfile(pfad))
        self.assertTrue(pfad.startswith(app_paths.data_dir(self.master)))
        self.assertEqual(ordner_aliase.lade_aliase(self.master), {"Bayerische Landesbrandversicherung": VKB})

    def test_gleicher_absender_wird_ueberschrieben_statt_verdoppelt(self):
        ordner_aliase.speichere_alias(self.master, "Gentilia", "Alt")
        aliase = ordner_aliase.speichere_alias(self.master, "gentilia", "Neu")
        self.assertEqual(aliase, {"gentilia": "Neu"})

    def test_leere_eingaben_werden_ignoriert(self):
        ordner_aliase.speichere_alias(self.master, "", VKB)
        ordner_aliase.speichere_alias(self.master, "Gentilia", "  ")
        self.assertFalse(os.path.exists(app_paths.aliase_path(self.master)))

    def test_loeschen_entfernt_eintrag_und_schreibt_datei(self):
        """Verwaltungsdialog (Nutzerfund 31.08.2026): falsch gelernte Aliase müssen wieder rausgehen."""
        ordner_aliase.speichere_alias(self.master, "Landratsamt Musterstadt", "Haus- und Grund Musterstadt")
        ordner_aliase.speichere_alias(self.master, "Gentilia", VKB)
        aliase = ordner_aliase.loesche_alias(self.master, "landratsamt   musterstadt")   # normalisiert
        self.assertEqual(aliase, {"Gentilia": VKB})
        self.assertEqual(ordner_aliase.lade_aliase(self.master), {"Gentilia": VKB})

    def test_loeschen_unbekannter_eintrag_aendert_nichts(self):
        ordner_aliase.speichere_alias(self.master, "Gentilia", VKB)
        aliase = ordner_aliase.loesche_alias(self.master, "Gibt es nicht")
        self.assertEqual(aliase, {"Gentilia": VKB})

    def test_kaputte_datei_haelt_nichts_an(self):
        pfad = app_paths.aliase_path(self.master)
        os.makedirs(os.path.dirname(pfad))
        with open(pfad, "w", encoding="utf-8") as f:
            f.write("{ kaputt")
        self.assertEqual(ordner_aliase.lade_aliase(self.master), {})
        with open(pfad, "w", encoding="utf-8") as f:
            json.dump(["keine", "tabelle"], f)
        self.assertEqual(ordner_aliase.lade_aliase(self.master), {})


def _ki_antwort(**overrides):
    antwort = {"title": "Beitragsrechnung", "tags": ["Versicherung"], "datum": "2026-06-18",
               "absender": "Bayerische Landesbrandversicherung"}
    antwort.update(overrides)
    return antwort


class TestAliasInBaueEntscheidung(unittest.TestCase):
    """Der Alias schlägt das Namens-Matching - genau der Fall, den kein String-Vergleich lösen kann."""

    def test_ohne_alias_entsteht_neuer_ordner(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(), ORDNER)
        self.assertTrue(e["ordner_neu"])
        self.assertFalse(e["ordner_per_alias"])
        self.assertEqual(e["zielordner"], "A - B - C\\Bayerische Landesbrandversicherung")

    def test_mit_alias_landet_es_im_vorhandenen_ordner(self):
        aliase = {"Bayerische Landesbrandversicherung": VKB}
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="Bayerische Landesbrandversicherung AG"),
                                          ORDNER, aliase=aliase)
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], VKB)
        self.assertFalse(e["ordner_neu"])
        self.assertTrue(e["ordner_per_alias"])

    def test_alias_auf_nicht_mehr_vorhandenen_ordner_wird_als_neu_markiert(self):
        aliase = {"Bayerische Landesbrandversicherung": "Weg\\Ordner"}
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(), ORDNER, aliase=aliase)
        self.assertEqual(e["zielordner"], "Weg\\Ordner")
        self.assertTrue(e["ordner_neu"])

    def test_alias_macht_zu_kurzen_absender_sicher(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="KM"), ORDNER,
                                          aliase={"KM": "A - B - C\\Kehrmann, Fritz"})
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], "A - B - C\\Kehrmann, Fritz")


class TestWendeZielordnerAn(unittest.TestCase):
    """Nutzer-Korrektur des Zielordners in der Ablage-Vorschau."""

    def test_ordner_wird_uebernommen_und_datei_bleibt_sicher(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(), ORDNER)
        neu = auto_pilot.wende_zielordner_an(e, VKB, ORDNER)
        self.assertEqual(neu["zielordner"], VKB)
        self.assertFalse(neu["ordner_neu"])
        self.assertTrue(neu["ordner_per_alias"])
        self.assertTrue(neu["sicher"])
        self.assertEqual(neu["neuer_dateiname"], "20260618_Beitragsrechnung.pdf")
        self.assertEqual(e["zielordner"], "A - B - C\\Bayerische Landesbrandversicherung")  # Original unverändert

    def test_zu_kurzer_absender_wird_durch_ordnerwahl_sicher(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(absender="KM"), ORDNER)
        self.assertFalse(e["sicher"])
        neu = auto_pilot.wende_zielordner_an(e, "A - B - C\\Kehrmann, Fritz", ORDNER)
        self.assertTrue(neu["sicher"], neu["probleme"])
        self.assertTrue(neu["ordner_neu"])

    def test_andere_probleme_bleiben_bestehen(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(datum="irgendwann"), ORDNER)
        neu = auto_pilot.wende_zielordner_an(e, VKB, ORDNER)
        self.assertFalse(neu["sicher"])
        self.assertIn("kein plausibles Dokumentdatum erkannt", neu["probleme"])
        self.assertEqual(neu["neuer_dateiname"], "")

    def test_leerer_ordner_bleibt_unsicher(self):
        e = auto_pilot.baue_entscheidung("dok.pdf", _ki_antwort(), ORDNER)
        neu = auto_pilot.wende_zielordner_an(e, "  ", ORDNER)
        self.assertFalse(neu["sicher"])


if __name__ == "__main__":
    unittest.main()


class TestObjektAlias(unittest.TestCase):
    """Eigenbelege ohne Absender (11.09.2026): Objekt-Aliase mit Präfix 'Objekt: ' in derselben Datei."""

    ALIASE = {"Gentilia": r"A - B\Gentilia", "Objekt: Weidenstr. 8": r"U - Z\Weidenstr. 8",
              "objekt: Zum Alten Fass 1 Musterheim": r"P - T\Musterheim"}

    def test_schluessel_helfer(self):
        self.assertEqual(ordner_aliase.objekt_schluessel(" Weidenstr. 8 "), "Objekt: Weidenstr. 8")
        self.assertTrue(ordner_aliase.ist_objekt_alias("objekt:  Weidenstr. 8"))
        self.assertFalse(ordner_aliase.ist_objekt_alias("Gentilia"))
        self.assertEqual(ordner_aliase.objekt_aus_schluessel("Objekt: Weidenstr. 8"), "Weidenstr. 8")
        self.assertEqual(ordner_aliase.objekt_aus_schluessel("Gentilia"), "Gentilia")

    def test_objekt_kern(self):
        for objekt, kern in (("Weidenstr. 8 Whg 4", "Weidenstr. 8"), ("Weidenstr. 8 Whg Nr. 2", "Weidenstr. 8"),
                             ("Weidenstr. 8, Wohnung 3", "Weidenstr. 8"), ("Zum Alten Fass 1 WE 12", "Zum Alten Fass 1"),
                             ("Hobbyraum", "Hobbyraum"), ("Weidenstr. 80", "Weidenstr. 80"), ("", "")):
            self.assertEqual(ordner_aliase.objekt_kern(objekt), kern, objekt)

    def test_objekt_alias_trifft_exakt_auf_haus_ebene(self):
        self.assertEqual(ordner_aliase.finde_objekt_alias(["Weidenstr. 8"], self.ALIASE),
                         (r"U - Z\Weidenstr. 8", "Weidenstr. 8"))
        # Wohnung im Haus: der Haus-Kern des Objekts trifft den Alias 'Weidenstr. 8'
        self.assertEqual(ordner_aliase.finde_objekt_alias(["Weidenstr. 8 Whg 4"], self.ALIASE)[0], r"U - Z\Weidenstr. 8")
        # aber NICHT als Teilstring: anderes Haus
        self.assertEqual(ordner_aliase.finde_objekt_alias(["Weidenstr. 80"], self.ALIASE), (None, None))
        # Eintrag MIT Wohnung (von Hand) gewinnt für genau diese Wohnung
        aliase = dict(self.ALIASE, **{"Objekt: Weidenstr. 8 Whg 4": "Mieter Whg 4"})
        self.assertEqual(ordner_aliase.finde_objekt_alias(["Weidenstr. 8 Whg 4"], aliase)[0], "Mieter Whg 4")
        self.assertEqual(ordner_aliase.finde_objekt_alias(["Weidenstr. 8 Whg 2"], aliase)[0], r"U - Z\Weidenstr. 8")
        # erstes Objekt mit Treffer zählt; Groß/Klein im Präfix egal
        self.assertEqual(ordner_aliase.finde_objekt_alias(["Hobbyraum", "Zum Alten Fass 1 Musterheim"], self.ALIASE),
                         (r"P - T\Musterheim", "Zum Alten Fass 1 Musterheim"))
        self.assertEqual(ordner_aliase.finde_objekt_alias(["Hobbyraum"], self.ALIASE), (None, None))
        self.assertEqual(ordner_aliase.finde_objekt_alias([], self.ALIASE), (None, None))
        self.assertEqual(ordner_aliase.finde_objekt_alias(["Weidenstr. 8"], {"Gentilia": "x"}), (None, None))

    def test_absender_suche_ueberspringt_objekt_aliase(self):
        # Ein Absender 'Weidenstr. 8' (Hausverwaltung o.ä.) darf NICHT auf den Objekt-Alias fallen
        self.assertIsNone(ordner_aliase.finde_alias("Weidenstr. 8", self.ALIASE))
        self.assertEqual(ordner_aliase.finde_alias("Gentilia AG", self.ALIASE), r"A - B\Gentilia")
        # und ein Objekt trifft keinen Absender-Alias
        self.assertEqual(ordner_aliase.finde_objekt_alias(["Gentilia"], self.ALIASE), (None, None))
