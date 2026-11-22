import os
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

import auto_pilot
from tools.auto_filer import (AutoFilerInboxTool, AutoFilerPreviewWindow, AutoFilerTool, korrektur_menue,
                              zielordner_text)
from ui_utils import UIUtils


class TestZielordnerAuswahl(unittest.TestCase):
    """Peter 02.11.2026: ein eben angelegter Ordner fehlte in der Zielordner-Auswahl der Ablage-Vorschau."""

    def setUp(self):
        self.sammlung = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.sammlung, True)
        os.makedirs(os.path.join(self.sammlung, "Musterversicherung"))
        self.fenster = types.SimpleNamespace(app=types.SimpleNamespace(master_folder=self.sammlung),
                                             ordnerliste=auto_pilot.sammle_ordnerliste(self.sammlung),
                                             neue_ordner={"Stadtwerke Musterstadt", "Noch nicht da"})

    def test_neu_angelegter_ordner_kommt_dazu(self):
        liste = self.fenster.ordnerliste
        os.makedirs(os.path.join(self.sammlung, "Stadtwerke Musterstadt"))       # nach der Analyse angelegt
        AutoFilerPreviewWindow._ordnerliste_auffrischen(self.fenster)
        self.assertIs(self.fenster.ordnerliste, liste)                           # gleiche Liste (Analyse-Thread)
        self.assertEqual(sorted(liste), ["Musterversicherung", "Stadtwerke Musterstadt"])
        self.assertEqual(self.fenster.neue_ordner, {"Noch nicht da"})


class TestErgebnisKlick(unittest.TestCase):
    """Klick auf „Ergebnis“: grün -> gelb (Peter 02.11.2026), erneuter Klick zurück."""

    def test_gruen_wird_gelb_und_zurueck(self):
        e = {"sicher": True, "probleme": [], "datum": "2025-01-15", "titel": "Beitrag", "neuer_dateiname": "x.pdf"}
        gezeigt = []
        fenster = types.SimpleNamespace(_zeige_entscheidung=lambda iid, neu: gezeigt.append(neu))
        with patch("tools.auto_filer.bestaetigung.frage", return_value=True) as frage:
            AutoFilerPreviewWindow._frage_freigabe(fenster, "i1", e)
            self.assertFalse(gezeigt[-1]["sicher"])
            self.assertEqual(gezeigt[-1]["probleme"], [auto_pilot.PROBLEM_ZURUECKGESTELLT])
            AutoFilerPreviewWindow._frage_freigabe(fenster, "i1", gezeigt[-1])
            self.assertTrue(gezeigt[-1]["sicher"])
            self.assertEqual(frage.call_count, 1)                                # Zurücknehmen fragt nicht
        with patch("tools.auto_filer.bestaetigung.frage", return_value=False):
            AutoFilerPreviewWindow._frage_freigabe(fenster, "i1", e)
        self.assertEqual(len(gezeigt), 2)                                        # „Nein“ ändert nichts



class _OffeneVorschau:
    def __init__(self, pfade, einsortiert=False):
        self.pdf_paths, self.einsortiert, self.zerstoert, self.vorn = list(pfade), einsortiert, False, False

    def winfo_exists(self):
        return not self.zerstoert

    def destroy(self):
        self.zerstoert = True

    def deiconify(self):
        pass

    def lift(self):
        self.vorn = True

    def focus_set(self):
        pass

    def title(self):
        return "Vollautomatik — Ablage-Vorschau"

    ist_verwerfbar = AutoFilerPreviewWindow.ist_verwerfbar     # die echte Regel der Vorschau


class TestNurEineVorschau(unittest.TestCase):
    """Peter 21.11.2026 (Fenster-Durchsicht A3/A6): ein zweiter Aufruf der Ablage-Vorschau verwarf die offene samt
    aller Korrekturen; die beiden Tools öffneten außerdem je ein eigenes Fenster."""

    def setUp(self):
        UIUtils._einzelfenster.clear()
        self.addCleanup(UIUtils._einzelfenster.clear)
        hinweis = patch("tkinter.messagebox.showinfo")
        self.hinweis = hinweis.start()
        self.addCleanup(hinweis.stop)
        self.erzeugt = []

    def _oeffne(self, pfade, einsortiert=False, werkzeug=AutoFilerTool):
        def erzeugen():
            self.erzeugt.append(_OffeneVorschau(pfade, einsortiert))
            return self.erzeugt[-1]
        return werkzeug().oeffne_fenster(erzeugen, pfade)

    def test_zweiter_aufruf_holt_die_offene_nach_vorn(self):
        erste = self._oeffne(["a.pdf", "b.pdf"])
        zweite = self._oeffne(["b.pdf", "a.pdf"])
        self.assertIs(zweite, erste)
        self.assertTrue(erste.vorn)
        self.assertFalse(erste.zerstoert)
        self.hinweis.assert_not_called()

    def test_andere_auswahl_verwirft_nichts_und_sagt_warum(self):
        erste = self._oeffne(["a.pdf"])
        self.assertIs(self._oeffne(["c.pdf"]), erste)
        self.assertFalse(erste.zerstoert)
        self.assertEqual(len(self.erzeugt), 1)
        self.hinweis.assert_called_once()

    def test_eingeordnetes_protokoll_weicht_der_neuen_auswahl(self):
        erste = self._oeffne(["a.pdf"], einsortiert=True)
        neue = self._oeffne(["c.pdf"])
        self.assertTrue(erste.zerstoert)
        self.assertIsNot(neue, erste)
        self.hinweis.assert_not_called()

    def test_posteingang_und_auswahl_teilen_sich_ein_fenster(self):
        erste = self._oeffne(["a.pdf"])
        self.assertIs(self._oeffne(["a.pdf"], werkzeug=AutoFilerInboxTool), erste)
        self.assertEqual(len(self.erzeugt), 1)



class TestKorrekturPerDoppelklick(unittest.TestCase):
    """Fenster-Durchsicht A4 (Peter 21.11.2026): ein Einzelklick zum Auswählen öffnete schon einen Dialog - jetzt
    wählt er nur aus, korrigiert wird per Doppelklick oder Rechtsklick wie in allen anderen Tabellen."""

    def test_einzelklick_bearbeitet_nicht(self):
        """Seit B4c über die gemeinsame Hilfe (Doppelklick, Rechtsklick, F2) - kein eigener Klick-Handler mehr."""
        import inspect
        quelle = inspect.getsource(AutoFilerPreviewWindow._setup_ui)
        self.assertNotIn('"<Button-1>"', quelle)
        self.assertIn("UIUtils.tabelle_bearbeitbar(self.tree, self._bearbeite, menue=self._menue_eintraege", quelle)

    def test_menue_nur_fuer_analysierte_zeilen(self):
        fenster = types.SimpleNamespace(einsortiert=False, ergebnisse={"z1": {"probleme": [], "sicher": True}, "z2": None})
        self.assertEqual([s for s, _ in AutoFilerPreviewWindow._menue_eintraege(fenster, "z1")],
                         ["ziel", "titel", "tags", "datum", "status"])
        self.assertIsNone(AutoFilerPreviewWindow._menue_eintraege(fenster, "z2"))       # KI-Fehler / nicht analysiert
        fenster.einsortiert = True
        self.assertIsNone(AutoFilerPreviewWindow._menue_eintraege(fenster, "z1"))       # nach dem Einsortieren

    def test_menue_sagt_was_der_ergebnis_eintrag_tut(self):
        def letzter(**e):
            return korrektur_menue({"probleme": [], **e})[-1]
        self.assertEqual(letzter(sicher=True), ("status", "Auf gelb setzen (nicht automatisch ablegen)…"))
        self.assertEqual(letzter(sicher=False), ("status", "Auf grün setzen (trotzdem automatisch ablegen)…"))
        self.assertEqual(letzter(sicher=True, manuell_freigegeben=True), ("status", "Freigabe zurücknehmen (wieder gelb)"))
        self.assertEqual(letzter(probleme=[auto_pilot.PROBLEM_ZURUECKGESTELLT]),
                         ("status", "Wieder grün (Zurückstellung aufheben)"))
        self.assertEqual([s for s, _ in korrektur_menue({"probleme": []})], ["ziel", "titel", "tags", "datum", "status"])



class TestZusammenfassungNurBeiBedarf(unittest.TestCase):
    """A2 (Peter 21.11.2026): nach dem Einsortieren nur dann ein Fenster, wenn etwas nach 0_Unsicher ging oder
    scheiterte - sonst steht der Erfolg kurz in der Leiste und im Log."""

    def _melde(self, abgelegt, unsicher, fehlgeschlagen):
        with patch("tools.auto_filer.mb.showinfo") as fenster, patch("tools.auto_filer.aktivitaet.erledigt") as leiste:
            AutoFilerPreviewWindow._zeige_zusammenfassung(types.SimpleNamespace(), abgelegt, unsicher, fehlgeschlagen)
        return fenster, leiste

    def test_alles_abgelegt_ohne_fenster(self):
        fenster, leiste = self._melde(3, 0, 0)
        fenster.assert_not_called()
        self.assertIn("3 Dokument(e) automatisch abgelegt", leiste.call_args[0][0])

    def test_unsicher_oder_fehler_mit_fenster(self):
        for unsicher, fehler in ((1, 0), (0, 1)):
            fenster, leiste = self._melde(2, unsicher, fehler)
            fenster.assert_called_once()
            leiste.assert_not_called()


class TestTagsZelle(unittest.TestCase):
    """A5 (Peter 21.11.2026): die Tags-Spalte war fast immer leer - ohne Tags zeigt sie, wie viele Katalog-Vorschläge
    der KI im Knopf-Dialog warten."""

    def test_ohne_tags_die_zahl_der_vorschlaege(self):
        from tools.auto_filer import tags_zelle
        self.assertEqual(tags_zelle([], [], ["Strom", "Rechnung", "Stadtwerke"], "Neu"), "+ 3 Vorschläge")
        self.assertEqual(tags_zelle([], [], ["Strom"], "Neu"), "+ 1 Vorschlag")
        self.assertEqual(tags_zelle([], [], [], "Neu"), "")

    def test_gesetzte_tags_wie_bisher(self):
        from tools.auto_filer import tags_zelle
        self.assertEqual(tags_zelle(["Strom", "Zähler"], [("Zähler", "")], ["Strom", "Rechnung"], "Neu"),
                         "Strom, Zähler (neu→Neu)")

    def test_die_vorschau_nutzt_es(self):
        import inspect
        quelle = inspect.getsource(AutoFilerPreviewWindow._zeige_entscheidung)
        self.assertIn("tags_zelle(", quelle)
        self.assertIn("self.ki_tags.get(iid", quelle)


class TestTagDialogInDerVorschau(unittest.TestCase):
    """B4a (Peter 21.11.2026): Tags in der Ablage-Vorschau über den Knopf-Dialog mit Vervollständigung statt
    freiem Text; die Tags der KI-Analyse bleiben als Knöpfe, auch wenn man sie abwählt."""

    def test_ki_tags_der_analyse_bleiben_gemerkt(self):
        fenster = types.SimpleNamespace(ergebnisse={}, ki_tags={}, ki_titel={}, winfo_exists=lambda: False)
        AutoFilerPreviewWindow._zeige_entscheidung(
            fenster, "z1", {"tags": ["Strom"], "tag_vorschlaege": ["Rechnung", "Strom"]})
        AutoFilerPreviewWindow._zeige_entscheidung(fenster, "z1", {"tags": []})   # Nutzer wählt ab
        self.assertEqual(fenster.ki_tags["z1"], ["Strom", "Rechnung"])

    def test_dialog_bekommt_ki_tags_und_vervollstaendigung(self):
        tm = types.SimpleNamespace(get_known_tags=lambda: ["Strom", "Rechnung"], get_kategorien=lambda: {})
        app = types.SimpleNamespace(tag_manager=tm)
        fenster = types.SimpleNamespace(app=app, einsortiert=False, ergebnisse={"z1": {"tags": ["Strom"]}},
                                        ki_tags={"z1": ["Strom", "Rechnung"]})
        with patch("tools.auto_filer.TagSuggestionDialog.ask", return_value=None) as ask:
            AutoFilerPreviewWindow._bearbeite(fenster, "z1", "tags")
        args, kwargs = ask.call_args
        self.assertEqual(args[2], "Strom")
        self.assertEqual(args[3], ["Strom", "Rechnung"])
        self.assertEqual(args[4], {"strom", "rechnung"})
        self.assertIs(kwargs.get("app"), app)


class TestDatumMitPruefung(unittest.TestCase):
    """B4b (21.11.2026): die Datum-Zelle öffnet den Datumsdialog mit auto_pilot.datum_aus_eingabe als Prüfung."""

    def _frage(self, antwort):
        gezeigt = {}
        fenster = types.SimpleNamespace(_zeige_entscheidung=lambda iid, e: gezeigt.__setitem__(iid, e))
        entscheidung = {"datum": "2026-01-02", "pdf_path": "scan.pdf", "titel": "Rechnung", "probleme": [],
                        "sicher": True, "neuer_dateiname": "x"}
        with patch("tools.auto_filer.UIUtils.ask_datum", return_value=antwort) as ask:
            AutoFilerPreviewWindow._frage_datum(fenster, "z1", entscheidung)
        return ask, gezeigt

    def test_pruefung_und_vorgabe(self):
        ask, _ = self._frage(None)
        self.assertIs(ask.call_args.kwargs["pruefe"], auto_pilot.datum_aus_eingabe)
        self.assertEqual(ask.call_args.kwargs["initialvalue"], "2026-01-02")

    def test_abbrechen_aendert_nichts_ok_uebernimmt(self):
        self.assertEqual(self._frage(None)[1], {})
        self.assertEqual(self._frage("2026-07-20")[1]["z1"]["datum"], "2026-07-20")


class TestTitelDialogInDerVorschau(unittest.TestCase):
    """B4d (21.11.2026): Titel in der Ablage-Vorschau über den Kandidaten-Dialog - KI-Titel der Analyse als Knopf
    (auch nach einer Korrektur) und der bisherige Titel im PDF (Peters Fund beim Titelvorschlag)."""

    def test_ki_titel_bleibt_gemerkt(self):
        fenster = types.SimpleNamespace(ergebnisse={}, ki_tags={}, ki_titel={}, winfo_exists=lambda: False)
        AutoFilerPreviewWindow._zeige_entscheidung(fenster, "z1", {"tags": [], "titel": "Rechnung Strom"})
        AutoFilerPreviewWindow._zeige_entscheidung(fenster, "z1", {"tags": [], "titel": "Von Hand"})
        self.assertEqual(fenster.ki_titel["z1"], "Rechnung Strom")

    def test_dialog_bekommt_ki_titel_aktuellen_und_bisherigen(self):
        fenster = types.SimpleNamespace(einsortiert=False, ki_titel={"z1": "Rechnung Strom"},
                                        ergebnisse={"z1": {"titel": "Von Hand"}},
                                        _bisheriger_titel=lambda iid: "Jahresabrechnung Strom")
        with patch("tools.auto_filer.CandidatePickerDialog.ask", return_value=None) as ask:
            AutoFilerPreviewWindow._bearbeite(fenster, "z1", "titel")
        args, kwargs = ask.call_args
        self.assertEqual(args[2], ["Rechnung Strom", "Von Hand"])
        self.assertEqual(args[3], "Von Hand")
        self.assertEqual(kwargs["bisher"], "Jahresabrechnung Strom")

    def test_bisheriger_titel_aus_dem_pdf(self):
        fenster = types.SimpleNamespace(rows={"z1": "C:/x/a.pdf"})
        with patch("tools.auto_filer.PDFHandler.get_metadata", return_value={"title": " Alt "}):
            self.assertEqual(AutoFilerPreviewWindow._bisheriger_titel(fenster, "z1"), "Alt")
        with patch("tools.auto_filer.PDFHandler.get_metadata", side_effect=OSError("weg")):
            self.assertEqual(AutoFilerPreviewWindow._bisheriger_titel(fenster, "z1"), "")


class TestZielordnerVonHand(unittest.TestCase):
    """Peter 21.11.2026: nach einer Zielordner-Korrektur ohne „für alle des Absenders“ stand [Alias] in der Zelle,
    obwohl kein Alias gespeichert wurde - wende_zielordner_an setzt ordner_per_alias auch für die Handwahl."""

    def _entscheidung(self, **extra):
        e = {"zielordner": "Strom", "ordner_neu": False, "ordner_per_alias": False, "ordner_hinweis": "",
             "probleme": [], "sicher": True, "datum": "2026-01-01", "titel": "Rechnung", "neuer_dateiname": "x",
             "absender": "Musterwerke GmbH", "objekte": []}
        e.update(extra)
        return e

    def test_zellentext(self):
        self.assertEqual(zielordner_text(self._entscheidung(ordner_von_hand=True, ordner_per_alias=True)),
                         "Strom [von Hand]")
        self.assertEqual(zielordner_text(self._entscheidung(ordner_per_alias=True)), "Strom [Alias]")
        self.assertEqual(zielordner_text(self._entscheidung(ordner_per_alias=True, ordner_hinweis="Objekt")),
                         "Strom [Objekt-Alias]")
        self.assertEqual(zielordner_text(self._entscheidung(), {"Strom"}), "Strom (neu)")

    def _waehle(self, fuer_alle):
        gezeigt = {}
        fenster = types.SimpleNamespace(
            ergebnisse={"z1": self._entscheidung()}, aliase={}, ordnerliste=["Strom", "Gas"], neue_ordner=set(),
            app=types.SimpleNamespace(master_folder="C:/Sammlung"),
            _zeige_entscheidung=lambda iid, e: gezeigt.__setitem__(iid, e))
        with patch("tools.auto_filer.ordner_aliase.speichere_alias", return_value={"Musterwerke GmbH": "Gas"}):
            AutoFilerPreviewWindow._setze_zielordner(fenster, "z1", "Gas", fuer_alle=fuer_alle)
        return zielordner_text(gezeigt["z1"])

    def test_handwahl_zeigt_von_hand(self):
        self.assertEqual(self._waehle(fuer_alle=False), "Gas [von Hand]")

    def test_fuer_alle_des_absenders_zeigt_alias(self):
        self.assertEqual(self._waehle(fuer_alle=True), "Gas [Alias]")

if __name__ == "__main__":
    unittest.main()
