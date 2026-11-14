import datetime
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import search_manager
from search_manager import SearchManager


class TestSucheAktiv(unittest.TestCase):
    """OCR-Haken allein ist keine Suche (FALLSTRICKE #74: Ordner-Klick wurde verschluckt)."""

    def _manager(self, text="", von="TT.MM.JJJJ", bis="TT.MM.JJJJ", modus="assign", tags=()):
        app = MagicMock()
        app.entry_search.get.return_value = text
        app.entry_date_from.get.return_value = von
        app.entry_date_to.get.return_value = bis
        app.tag_mode_var.get.return_value = modus
        app.tree_tags.selection.return_value = tags
        app.use_ocr_var.get.return_value = True
        return SearchManager(app)

    def test_nur_ocr_haken_ist_keine_suche(self):
        self.assertFalse(self._manager().is_search_active())

    def test_text_datum_oder_filtertags(self):
        self.assertTrue(self._manager(text="Rechnung").filter_eingegeben())
        self.assertTrue(self._manager(von="2020").filter_eingegeben())
        self.assertTrue(self._manager(bis="2022").filter_eingegeben())
        self.assertTrue(self._manager(modus="filter", tags=("I001",)).filter_eingegeben())
        self.assertFalse(self._manager(modus="assign", tags=("I001",)).filter_eingegeben())
        self.assertFalse(self._manager().filter_eingegeben())   # Platzhalter TT.MM.JJJJ zählt als leer

    def test_suche_aktiv_erst_nach_dem_abschicken(self):
        """Peter 01.11.2026: Tippen sucht nicht mehr - nur die angezeigte Suche zählt."""
        manager = self._manager(text="Rechnung")
        self.assertFalse(manager.is_search_active())   # nur getippt
        manager.execute_search = lambda *a: []
        manager.app.tree_folders.selection.return_value = ()
        manager.app.tree_files.selection.return_value = ()
        manager.app.tree_files.get_children.return_value = ()
        manager.app.master_folder = "C:/Sammlung"
        manager.app.current_preview_path = None
        manager._apply_filters()                         # Return
        self.assertTrue(manager.is_search_active())
        self.assertEqual(manager.aktive_suchbegriffe(), ["rechnung"])

    def test_geleertes_feld_setzt_sofort_zurueck(self):
        manager = self._manager(text="")
        manager.apply_filters = MagicMock()
        manager.feld_geleert()                           # keine Suche angezeigt -> nichts
        manager.apply_filters.assert_not_called()
        manager._angezeigt = ("rechnung", "", "", ())
        manager.app.entry_search.get.return_value = "rechnun"
        manager.feld_geleert()                           # nur verändert (z.B. Pfeiltaste, Rücktaste) -> nichts
        manager.apply_filters.assert_not_called()
        manager.app.entry_search.get.return_value = ""
        manager.feld_geleert()                           # geleert -> zurücksetzen
        manager.apply_filters.assert_called_once_with()

    def test_reset_ohne_markierten_ordner_leert_anzeige(self):
        # Peter 25.10.2026: Suche zurückgesetzt, kein Ordner markiert -> Liste leer, Dokument stand noch da
        manager = self._manager()
        manager.app.tree_folders.selection.return_value = ()
        manager.app.tree_files.selection.return_value = ()
        manager.app.tree_files.get_children.return_value = ()
        manager._apply_filters()
        manager.app.leere_dokumentanzeige.assert_called_once_with()
        manager.app.folder_manager.on_folder_select.assert_not_called()

    def test_reset_mit_markiertem_ordner_zeigt_ordner(self):
        manager = self._manager()
        manager.app.tree_folders.selection.return_value = ("I001",)
        manager.app.tree_files.selection.return_value = ()
        manager.app.tree_files.get_children.return_value = ()
        manager._apply_filters()
        manager.app.folder_manager.on_folder_select.assert_called_once_with(None)
        manager.app.leere_dokumentanzeige.assert_not_called()


class TestSearchMatcher(unittest.TestCase):
    """Tests für die Wildcard-Suche (SearchManager.build_matcher)."""

    def test_enthaelt_suche_ohne_wildcards(self):
        matcher = SearchManager.build_matcher("rechnung")
        self.assertTrue(matcher("stadtwerke_rechnung_2026.pdf"))
        self.assertTrue(matcher("Meine RECHNUNG"))  # case-insensitive
        self.assertFalse(matcher("angebot_2026.pdf"))

    def test_stern_wildcard(self):
        matcher = SearchManager.build_matcher("rechnung*2026")
        self.assertTrue(matcher("rechnung_stadtwerke_2026"))
        self.assertTrue(matcher("prefix rechnung x 2026 suffix"))  # Muster muss nur irgendwo passen
        self.assertFalse(matcher("2026_rechnung"))  # falsche Reihenfolge

    def test_fragezeichen_wildcard(self):
        matcher = SearchManager.build_matcher("me?er")
        self.assertTrue(matcher("herr meier"))
        self.assertTrue(matcher("frau meyer"))
        self.assertFalse(matcher("herr mller"))

    def test_leerer_suchtext_trifft_alles(self):
        matcher = SearchManager.build_matcher("   ")
        self.assertTrue(matcher("irgendwas"))

    def test_wildcard_ueber_zeilengrenzen(self):
        # OCR-Seitentext enthält Zeilenumbrüche — * muss darüber hinweg matchen
        matcher = SearchManager.build_matcher("stadtwerke*gesamtbetrag")
        self.assertTrue(matcher("stadtwerke münchen\nrechnung nr. 4711\ngesamtbetrag: 128,50 eur"))

    def test_fuzzy_tippfehler(self):
        """Unscharfe Suche: Buchstabendreher und fehlende Buchstaben werden verziehen."""
        self.assertTrue(SearchManager.build_matcher("Rechnnug")("stadtwerke_rechnung_2026.pdf"))
        self.assertTrue(SearchManager.build_matcher("Heizng")("nebenkosten heizung 2025"))

    def test_fuzzy_ocr_fehler(self):
        """Unscharfe Suche: typische Texterkennungs-Fehler (w -> vv, o -> a)."""
        self.assertTrue(SearchManager.build_matcher("stadtvverke")("rechnung der stadtwerke"))
        self.assertTrue(SearchManager.build_matcher("nebenkasten")("abrechnung nebenkosten 2026"))

    def test_fuzzy_keine_falschtreffer(self):
        """Verschiedene Wörter dürfen trotz Ähnlichkeit NICHT matchen."""
        self.assertFalse(SearchManager.build_matcher("steuer")("feuer im haus"))
        self.assertFalse(SearchManager.build_matcher("miete")("einkaufsliste"))

    def test_fuzzy_nicht_bei_kurzen_begriffen(self):
        """Unter 4 Zeichen bleibt es bei der exakten Enthält-Suche ('Bank' darf nicht 'Dank' treffen)."""
        self.assertFalse(SearchManager.build_matcher("kfz")("kfe unterlagen"))

    def test_fuzzy_zerrissene_woerter(self):
        """Von der Texterkennung zerrissene Wörter werden als zusammengeklebtes Token-Paar geheilt (echte OCR-Beispiele)."""
        self.assertTrue(SearchManager.build_matcher("Schornsteinfeger")("siehe schornsteinl'eger unterlagen"))
        self.assertTrue(SearchManager.build_matcher("Steuerzwecken")("rechnungen zu Steiier-zwecken aufbewahren"))

    def test_mehrwort_suche_ist_und_verknuepft(self):
        """Nutzerfund 30.08.2026: 'steuer 2023' fand nichts - die Wortfolge musste zusammenhängend vorkommen."""
        m = SearchManager.build_matcher("steuer 2023")
        self.assertTrue(m("grundsteuerbescheid.pdf grundsteuerbescheid 2023, steuern, musterstadt"))
        self.assertTrue(m("2023 kommt zuerst, dann steuern"))  # Reihenfolge egal
        self.assertFalse(m("grundsteuerbescheid 2022, steuern"))  # ein Wort fehlt
        self.assertFalse(m("2023 ohne das andere wort"))
        # jedes Wort für sich unscharf (ab 4 Zeichen), Wildcards bleiben ein Ausdruck
        self.assertTrue(SearchManager.build_matcher("stadtwerke rechnnug")("meine stadtwerke rechnung 2026"))
        self.assertEqual(SearchManager.split_terms("  Steuer 2023 "), ["steuer", "2023"])
        self.assertEqual(SearchManager.split_terms("rechnung*2026"), ["rechnung*2026"])
        self.assertEqual(SearchManager.split_terms(""), [])

    def test_mehrwort_kurze_woerter_bleiben_exakt(self):
        """Kurze Begriffe (< 4 Zeichen) auch in der Mehrwort-Suche nur als Enthaelt-Suche, nie unscharf."""
        self.assertTrue(SearchManager.build_matcher("kfz 2026")("kfz-versicherung 2026"))
        self.assertFalse(SearchManager.build_matcher("kfe 2026")("kfz-versicherung 2026"))

class TestDatumsGrenzen(unittest.TestCase):
    """
    Von-/Bis-Felder nehmen auch groebere Angaben (Nutzerwunsch 01.09.2026):
    "Von 2020 - Bis 2022" muss alle Dokumente aus 2020, 2021 und 2022 finden.
    """

    def setUp(self):
        self.manager = SearchManager(MagicMock())

    def test_volles_datum_wie_bisher(self):
        self.assertEqual(self.manager.parse_date("15.03.2021"), datetime.date(2021, 3, 15))
        self.assertEqual(self.manager.parse_date("15.03.2021", ende=True), datetime.date(2021, 3, 15))

    def test_jahr_wird_zum_jahresanfang_bzw_jahresende(self):
        self.assertEqual(self.manager.parse_date("2020"), datetime.date(2020, 1, 1))
        self.assertEqual(self.manager.parse_date("2022", ende=True), datetime.date(2022, 12, 31))

    def test_monat_und_jahr(self):
        self.assertEqual(self.manager.parse_date("07.2020"), datetime.date(2020, 7, 1))
        self.assertEqual(self.manager.parse_date("07.2020", ende=True), datetime.date(2020, 7, 31))

    def test_monatsende_beachtet_schaltjahr(self):
        self.assertEqual(self.manager.parse_date("02.2024", ende=True), datetime.date(2024, 2, 29))
        self.assertEqual(self.manager.parse_date("02.2023", ende=True), datetime.date(2023, 2, 28))

    def test_platzhalter_und_unsinn_filtern_nicht(self):
        for wert in ("", "   ", "TT.MM.JJJJ", "Unsinn", "13.2020", "20", "202"):
            with self.subTest(wert=wert):
                self.assertIsNone(self.manager.parse_date(wert))
                self.assertIsNone(self.manager.parse_date(wert, ende=True))

    def test_jahresbereich_schliesst_ganze_jahre_ein(self):
        """Die eigentliche Nutzer-Erwartung: 2020-2022 enthaelt den 31.12.2022."""
        von = self.manager.parse_date("2020")
        bis = self.manager.parse_date("2022", ende=True)
        for tag in (datetime.date(2020, 1, 1), datetime.date(2021, 6, 15), datetime.date(2022, 12, 31)):
            self.assertTrue(von <= tag <= bis, tag)
        for tag in (datetime.date(2019, 12, 31), datetime.date(2023, 1, 1)):
            self.assertFalse(von <= tag <= bis, tag)


class TestAktiveSuchbegriffe(unittest.TestCase):
    """Suchbegriffe für die Treffer-Markierung in der Vorschau (11.09.2026)."""

    def _manager(self, text):
        manager = SearchManager(MagicMock())
        manager._angezeigt = (text.strip().lower(), "", "", ()) if text.strip() else None
        return manager

    def test_begriffe_der_angezeigten_suche(self):
        self.assertEqual(self._manager("Plesche Kfz").aktive_suchbegriffe(), ["plesche", "kfz"])
        self.assertEqual(self._manager("rechnung*2026").aktive_suchbegriffe(), ["rechnung*2026"])

    def test_leer_ohne_angezeigte_suche(self):
        self.assertEqual(self._manager("   ").aktive_suchbegriffe(), [])
        app = MagicMock()
        app.entry_search.get.return_value = "nur getippt"   # nicht abgeschickt -> keine Markierung
        self.assertEqual(SearchManager(app).aktive_suchbegriffe(), [])


class TestPhrasenSuche(unittest.TestCase):
    """Anführungszeichen = nur zusammenhängender Text (Peter 11.09.2026: "Peter Mustermann")."""

    def test_split_terms_mit_anfuehrungszeichen(self):
        self.assertEqual(SearchManager.split_terms('"Peter Mustermann"'), ["peter mustermann"])
        self.assertEqual(SearchManager.split_terms('rechnung "Peter  Mustermann" 2026'), ["rechnung", "peter mustermann", "2026"])
        self.assertEqual(SearchManager.split_terms('"Peter Mustermann'), ["peter mustermann"])   # noch nicht geschlossen
        self.assertEqual(SearchManager.split_terms('""'), [])

    def test_phrase_nur_zusammenhaengend(self):
        m = SearchManager.build_matcher('"Peter Mustermann"')
        self.assertTrue(m("Herr Peter Mustermann, Musterstraße"))
        self.assertTrue(m("versicherungsnehmer:\npeter\nmustermann"))     # Zeilenumbruch im OCR-Text
        self.assertFalse(m("Mustermann, Peter"))
        self.assertFalse(m("Peter Müller und Klaus Mustermann"))
        self.assertFalse(m("Petra Mustermann"))                              # nicht unscharf

    def test_phrase_kombiniert_mit_woertern(self):
        m = SearchManager.build_matcher('rechnnug "Peter Mustermann"')
        self.assertTrue(m("rechnung peter mustermann 2026"))
        self.assertFalse(m("rechnung mustermann peter 2026"))

    def test_nur_unscharfe_einzelwoerter_bieten_den_schnellen_weg(self):
        """index_manager.search_fulltext erkennt den schnellen Weg an begriff/aehnliche_woerter (Spike S4)."""
        unscharf = SearchManager.begriff_matcher("Rechnung")
        self.assertEqual(unscharf.begriff, "rechnung")
        self.assertEqual(unscharf.aehnliche_woerter(["rechnnug", "mahnung", "rechnungen"]), {"rechnnug", "rechnungen"})
        for begriff in ("peter mustermann", "rech*", "abc", '"rechnung"'):  # Phrase, Platzhalter, zu kurz, genau
            with self.subTest(begriff=begriff):
                self.assertFalse(hasattr(SearchManager.begriff_matcher(begriff), "aehnliche_woerter"))

    def test_ein_wort_in_anfuehrungszeichen_gilt_genau(self):
        # Peter 05.11.2026: "Ramen" fand auch Raten, Namen, Damen und Rahmen
        m = SearchManager.build_matcher('"Ramen"')
        for treffer in ("Ramen", "eine ramen-suppe", "(RAMEN)", "ramen_2024.pdf", "suppe ramen\nnudeln"):
            self.assertTrue(m(treffer), treffer)
        for kein_treffer in ("Raten", "Namen", "Damen", "Rahmen", "Ramensuppe", "Xramen"):
            self.assertFalse(m(kein_treffer), kein_treffer)
        # ohne Anführungszeichen bleibt es unscharf, und mit anderen Begriffen verknüpft es sich wie jeder Begriff
        self.assertTrue(SearchManager.build_matcher("Ramen")("Rahmen"))
        beide = SearchManager.build_matcher('"Ramen" rechnnug')
        self.assertTrue(beide("rechnung ramen"))
        self.assertFalse(beide("rechnung rahmen"))
        self.assertEqual(SearchManager.split_terms('"Ramen"'), ['"ramen"'])
        self.assertEqual(SearchManager.split_terms('"Ram*"'), ["ram*"])              # Platzhalter bleibt ein Muster

    def test_genaues_wort_markiert_in_der_vorschau_nur_dieses_wort(self):
        import fitz
        from pdf_handler import PDFHandler
        with fitz.open() as doc:
            seite = doc.new_page()
            seite.insert_text((72, 72), "Ramen Rahmen Namen Ramensuppe (Ramen)")
            self.assertEqual(len(PDFHandler.suchtreffer_boxen(seite, ['"ramen"'], SearchManager.begriff_matcher)), 2)

    def test_trefferzahl_erscheint_nur_bei_einer_suche(self):
        from unittest.mock import MagicMock
        app = MagicMock()
        sm = SearchManager(app)
        sm._zeige_trefferzahl(3)
        app.lbl_treffer.config.assert_called_with(text="3 Treffer")
        sm._zeige_trefferzahl(0)
        app.lbl_treffer.config.assert_called_with(text="0 Treffer")
        sm._zeige_trefferzahl(None)
        app.lbl_treffer.config.assert_called_with(text="")

    def test_begriff_matcher_einzelwort_wie_bisher(self):
        self.assertTrue(SearchManager.begriff_matcher("rechnung")("meine rechnnug"))
        self.assertTrue(SearchManager.begriff_matcher("me?er")("herr meyer"))
        self.assertFalse(SearchManager.begriff_matcher("kfe")("kfz"))


class TestFuzzyBruchstueck(unittest.TestCase):
    """FALLSTRICKE #64: ein kürzeres Bruchstück darf den Suchbegriff nicht bei genau 0.8 treffen."""

    def test_muell_token_der_texterkennung_trifft_nicht(self):
        m = SearchManager.build_matcher("kostal")
        self.assertFalse(m("Sta(l^'tc^ke Musterstadt Brunngartenstraße 3"))   # echter OCR-Text, "Stadtwerke"
        self.assertFalse(m("stal"))

    def test_einzelner_fehlender_buchstabe_bleibt_erlaubt(self):
        self.assertTrue(SearchManager.build_matcher("rechnung")("ihre rechnug vom 3.5."))
        self.assertTrue(SearchManager.build_matcher("stadtvverke")("rechnung der stadtwerke"))
        self.assertTrue(SearchManager.build_matcher("kostal")("wechselrichter kosta1 plenticore"))   # gleich lang: 0.8 reicht


class TestAnzeigeNachSuche(unittest.TestCase):
    """Release-Check T0.18: Dokument stand in Vorschau/Eigenschaften, aber nicht in der Trefferliste."""

    def test_angezeigtes_dokument_unter_treffern_bleibt(self):
        self.assertIsNone(SearchManager.anzeige_nach_suche(
            "A\\Brief.pdf", ["A/Brief.pdf", "B/x.pdf"], "brief", False))

    def test_nicht_unter_treffern_wird_geleert(self):
        self.assertEqual(SearchManager.anzeige_nach_suche("A\\Brief.pdf", ["B/x.pdf"], "brief", False), "")

    def test_ohne_treffer_und_ohne_ocr_kommt_hinweis(self):
        self.assertEqual(SearchManager.anzeige_nach_suche("A\\Brief.pdf", [], "Zahlung", False),
                         search_manager.HINWEIS_OHNE_OCR)
        # auch wenn gerade nichts angezeigt war - die leere Liste braucht die Erklärung
        self.assertEqual(SearchManager.anzeige_nach_suche("", [], "Zahlung", False),
                         search_manager.HINWEIS_OHNE_OCR)

    def test_mit_ocr_oder_ohne_suchtext_kein_hinweis(self):
        self.assertEqual(SearchManager.anzeige_nach_suche("A\\Brief.pdf", [], "Zahlung", True), "")
        self.assertEqual(SearchManager.anzeige_nach_suche("A\\Brief.pdf", [], "  ", False), "")
        self.assertEqual(SearchManager.anzeige_nach_suche("", [], "Zahlung", True), "")

    def test_alter_hinweis_verschwindet_bei_treffern(self):
        # nichts angezeigt (Hinweis steht), nächste Suche mit OCR findet etwas -> leeren
        self.assertEqual(SearchManager.anzeige_nach_suche("", ["B/x.pdf"], "Zahlung", True), "")


class TestSucheNachDokumentId(unittest.TestCase):
    """Dokument-ID Schritt 2 (25.10.2026): Suche findet ein Dokument über seine ID."""

    def _suche(self, text):
        app = MagicMock()
        app.use_ocr_var.get.return_value = False
        app.config.get.side_effect = lambda key, default=None: False if key == "use_index" else default
        manager = SearchManager(app)
        doks = [{"rel_path": "A/brief.pdf", "name": "brief.pdf", "title": "Brief", "keywords": "",
                 "kid_date": "2026-01-02", "creation_date": "", "scan_zeit_embedded": "",
                 "kid_id": "K7M4-Q2XP", "mtime": 0},
                {"rel_path": "B/rechnung.pdf", "name": "rechnung.pdf", "title": "Rechnung", "keywords": "",
                 "kid_date": "2026-01-03", "creation_date": "", "scan_zeit_embedded": "",
                 "kid_id": "B53U-RNDX", "mtime": 0}]
        manager._iter_documents = lambda master: doks
        with tempfile.TemporaryDirectory() as master:     # execute_search verlangt einen echten Ordner
            return [r[4] for r in manager.execute_search(master, text, "", "", [])]

    def test_volle_id_anfang_und_ohne_bindestrich(self):
        for text in ("K7M4-Q2XP", "k7m4", "K7M4Q2XP", "q2xp"):
            self.assertEqual(self._suche(text), ["A/brief.pdf"], text)

    def test_andere_begriffe_unveraendert(self):
        self.assertEqual(self._suche("rechnung"), ["B/rechnung.pdf"])


class TestVermutetesDatumInTreffern(unittest.TestCase):
    """FALLSTRICKE #86: ohne gespeichertes Datum zeigt und filtert die Trefferliste das vermutete."""

    def _suche(self, von="", bis=""):
        app = MagicMock()
        app.use_ocr_var.get.return_value = False
        manager = SearchManager(app)
        doks = [{"rel_path": "A/konto.pdf", "name": "konto.pdf", "title": "Kontoauszug", "keywords": "",
                 "kid_date": "", "creation_date": "", "scan_zeit_embedded": "", "kid_id": "",
                 "mtime": 1_790_000_000}]   # Datei-Datum Sept. 2026 (Download-Tag)
        manager._iter_documents = lambda master: doks
        with tempfile.TemporaryDirectory() as master:
            vermutet = {os.path.join(master, "A/konto.pdf"): "2025-01-31"}
            with patch("search_manager.index_manager.vermutete_daten_sicher", return_value=vermutet):
                return [(r[0], r[5]) for r in manager.execute_search(master, "", von, bis, [])]

    def test_vermutetes_datum_statt_datei_datum(self):
        self.assertEqual(self._suche(), [("31.01.2025", 2025)])

    def test_von_bis_nutzt_das_vermutete_datum(self):
        self.assertEqual(self._suche("2025", "2025"), [("31.01.2025", 2025)])
        self.assertEqual(self._suche("2026", ""), [])



class TestTrefferlisteOhneFlackern(unittest.TestCase):
    """Wiederholte Suche mit gleichen Treffern baut die Liste nicht neu auf (Peter 01.11.2026: Flackern)."""

    def setUp(self):
        import tkinter as tk
        from tkinter import ttk
        self.root = tk.Tk()
        self.root.withdraw()
        self.tmp = tempfile.mkdtemp()
        app = MagicMock()
        app.master_folder = self.tmp
        app.tree_files = ttk.Treeview(self.root, columns=("datum", "titel", "tags", "name", "path", "ordner",
                                                          "scan_zeit", "qualitaet", "erfasst"))
        app.tree_folders = ttk.Treeview(self.root)
        app.entry_search.get.return_value = "rechnung"
        app.entry_date_from.get.return_value = ""
        app.entry_date_to.get.return_value = ""
        app.tag_mode_var.get.return_value = "assign"
        app.current_preview_path = None
        self.app = app
        self.sm = SearchManager(app)
        self.treffer = [("01.02.2024", "Rechnung", "Strom", "a.pdf", "a.pdf", 2024, False, "", ""),
                        ("05.03.2023", "2023", "---", "b.pdf", os.path.join("Ordner", "b.pdf"), 2023, True, "", "")]
        self.sm.execute_search = lambda *a: list(self.treffer)

    def tearDown(self):
        self.root.destroy()
        os.rmdir(self.tmp)

    def test_gleiche_treffer_lassen_die_zeilen_stehen(self):
        self.sm._apply_filters()
        vorher = self.app.tree_files.get_children()
        self.app.tree_files.selection_set(vorher[1])
        self.sm._apply_filters()
        self.assertEqual(self.app.tree_files.get_children(), vorher)  # dieselben Zeilen, nicht neu angelegt
        self.assertEqual(self.app.tree_files.selection(), (vorher[1],))

    def test_trefferzahl_stimmt_auch_wenn_die_zeilen_stehen_bleiben(self):
        self.sm._apply_filters()
        self.app.lbl_treffer.config.assert_called_with(text="2 Treffer")
        self.app.lbl_treffer.config.reset_mock()
        self.sm._apply_filters()      # gleiche Zeilen: die Liste bleibt, die Zahl muss trotzdem stehen
        self.app.lbl_treffer.config.assert_called_with(text="2 Treffer")
        self.app.entry_search.get.return_value = ""
        self.app.tree_folders.selection = lambda: ()
        self.sm._apply_filters()      # keine Suche mehr: keine Zahl
        self.app.lbl_treffer.config.assert_called_with(text="")

    def test_geaenderte_treffer_bauen_neu_auf(self):
        self.sm._apply_filters()
        vorher = self.app.tree_files.get_children()
        self.treffer[0] = ("01.02.2024", "Rechnung neu", "Strom", "a.pdf", "a.pdf", 2024, False, "", "")
        self.sm._apply_filters()
        nachher = self.app.tree_files.get_children()
        self.assertNotEqual(nachher, vorher)
        self.assertEqual(self.app.tree_files.item(nachher[0], "values")[1], "Rechnung neu")


class TestSuchfeldFarbe(unittest.TestCase):
    """Peter 01.11.2026: gelb = getippt, noch nicht gesucht; grün = die Liste zeigt genau diese Suche."""

    def test_zustand(self):
        self.assertEqual(search_manager.suchfeld_zustand("", None), "leer")
        self.assertEqual(search_manager.suchfeld_zustand("   ", "rechnung"), "leer")
        self.assertEqual(search_manager.suchfeld_zustand("Rechnung", None), "ungesendet")
        self.assertEqual(search_manager.suchfeld_zustand("Rechnung", "Rechnung"), "gesendet")
        self.assertEqual(search_manager.suchfeld_zustand("Rechnung 2023", "Rechnung"), "ungesendet")
        self.assertEqual(search_manager.suchfeld_zustand(" Rechnung ", "Rechnung"), "gesendet")

    def test_feld_wird_gefaerbt(self):
        app = MagicMock()
        app.entry_search.cget.return_value = "white"
        app.entry_search.get.return_value = "Rechnung"
        manager = SearchManager(app)
        manager.faerbe_suchfeld()
        app.entry_search.configure.assert_called_with(background=search_manager.SUCHFELD_UNGESENDET)
        manager._angezeigt = ("Rechnung", "", "", ())
        manager.faerbe_suchfeld()
        app.entry_search.configure.assert_called_with(background=search_manager.SUCHFELD_GESENDET)
        app.entry_search.get.return_value = ""
        manager._angezeigt = None
        manager.faerbe_suchfeld()
        app.entry_search.configure.assert_called_with(background="white")
