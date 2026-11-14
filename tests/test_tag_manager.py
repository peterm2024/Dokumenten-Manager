import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import tkinter as tk

import zuletzt_benutzt
from tag_manager import TagManager

class TestTagManager(unittest.TestCase):
    def setUp(self):
        # 1. Eine "Fake GUI" (App) erstellen
        self.mock_app = MagicMock()
        
        # 2. Fake für das Textfeld und die Dateiliste
        self.mock_app.entry_tags.get.return_value = ""
        self.mock_app.tree_files.selection.return_value = ["dummy_pdf_item_1"]
        
        # ---> NEU: Mock für den neuen Tag-Modus (Zuweisen vs Filtern)
        self.mock_app.tag_mode_var = MagicMock()
        self.mock_app.tag_mode_var.get.return_value = "assign" # Standardmodus
        
        # ---> NEU: Tiefere Hierarchie für den Rekursions-Test (3 Ebenen)
        self.tree_data = {
            "node_hobbys": {"text": "Hobbys & Projekte", "parent": ""},
            "node_3d": {"text": "3D-Druck", "parent": "node_hobbys"},
            "node_ersatzteile": {"text": "Ersatzteile", "parent": "node_3d"},
            "node_labview": {"text": "LabVIEW", "parent": ""}
        }
        
        # Wir bringen der Fake-App bei, wie sie auf Baum-Abfragen antworten soll
        def mock_item(item_id, option=None, **kwargs):
            if option == "text":
                return self.tree_data.get(item_id, {}).get("text", "")
            if option == "tags":
                return ("bundle",) # Wir tun so, als wären es normale Tags, keine temp_tags
            return ""
            
        def mock_parent(item_id):
            return self.tree_data.get(item_id, {}).get("parent", "")
            
        self.mock_app.tree_tags.item.side_effect = mock_item
        self.mock_app.tree_tags.parent.side_effect = mock_parent
        
        self.manager = TagManager(self.mock_app)

    def test_toggle_remove_tag(self):
        # Ausgangslage: Tag existiert bereits im Textfeld
        self.mock_app.entry_tags.get.return_value = "Wichtig, LabVIEW, 2026"
        
        self.manager._toggle_tag("node_labview")
        
        # Erwartung: LabVIEW ist weg, der Rest bleibt
        self.mock_app.entry_tags.delete.assert_called_with("1.0", tk.END)
        self.mock_app.entry_tags.insert.assert_called_with("1.0", "Wichtig, 2026")

    def test_toggle_add_tag_deep_recursion(self):
        """ ---> NEU: Testet, ob Großeltern und Eltern korrekt gefunden werden """
        self.mock_app.entry_tags.get.return_value = ""
        
        # Aktion: Wir klicken tief im Baum auf "Ersatzteile"
        self.manager._toggle_tag("node_ersatzteile")
        
        # Erwartung: Opa, Papa und Kind werden logisch von oben nach unten eingefügt
        self.mock_app.entry_tags.insert.assert_called_with("1.0", "Hobbys & Projekte, 3D-Druck, Ersatzteile")

    def test_filter_mode_protection(self):
        """ ---> NEU: Testet, ob der Filtermodus das Zuweisen von Tags blockiert """
        # Wir simulieren, dass der User auf "🔍 Filtern" geschaltet hat
        self.mock_app.tag_mode_var.get.return_value = "filter"
        self.mock_app.entry_tags.get.return_value = ""
        
        self.manager._toggle_tag("node_labview")
        
        # Erwartung: Die GUI darf auf keinen Fall das Textfeld anfassen!
        self.mock_app.entry_tags.delete.assert_not_called()
        self.mock_app.entry_tags.insert.assert_not_called()

    @patch("tag_manager.messagebox")
    def test_toggle_without_file_selection(self, mock_msgbox):
        # Ausgangslage: KEIN PDF ist rechts ausgewählt!
        self.mock_app.tree_files.selection.return_value = []

        self.manager._toggle_tag("node_labview")

        # Erwartung: Synchronisation wird getriggert, aber kein Textfeld-Insert (kein Crash!)
        self.mock_app.entry_tags.insert.assert_not_called()

    def test_remove_recent_tag(self):
        """Entfernen eines Eintrags aus der Zuletzt-benutzt-Liste der Sammlung (Daten-Ordner)."""
        basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, basis, True)
        self.mock_app.master_folder = os.path.join(basis, "Sammlung")
        os.makedirs(self.mock_app.master_folder)
        zuletzt_benutzt.speichere(self.mock_app.master_folder, ["Rechnung", "Tippfehlr", "Steuern"])

        self.manager.remove_recent_tag("Tippfehlr")

        self.assertEqual(zuletzt_benutzt.lade(self.mock_app.master_folder), ["Rechnung", "Steuern"])
        self.mock_app.config.set.assert_not_called()

    def test_remove_recent_tag_unknown_entry(self):
        """Ein nicht (mehr) vorhandener Eintrag lässt die Liste unverändert."""
        basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, basis, True)
        self.mock_app.master_folder = os.path.join(basis, "Sammlung")
        os.makedirs(self.mock_app.master_folder)
        zuletzt_benutzt.speichere(self.mock_app.master_folder, ["Rechnung"])

        self.manager.remove_recent_tag("GibtEsNicht")

        self.assertEqual(zuletzt_benutzt.lade(self.mock_app.master_folder), ["Rechnung"])

    def test_add_recent_tags_je_sammlung(self):
        """Zwei Sammlungen haben getrennte Listen; neue Tags kommen vorne hin."""
        basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, basis, True)
        alt, neu = os.path.join(basis, "Alt"), os.path.join(basis, "Neu")
        os.makedirs(alt)
        os.makedirs(neu)
        self.mock_app.config.data = {}
        self.mock_app.master_folder = alt
        self.manager.add_recent_tags(["Steuer", "Rechnung"])
        self.manager.add_recent_tags(["Arzt", "Steuer"])
        self.assertEqual(zuletzt_benutzt.lade(alt), ["Arzt", "Steuer", "Rechnung"])

        self.mock_app.master_folder = neu
        self.assertEqual(zuletzt_benutzt.lade(neu, self.mock_app.config), [])

    def test_get_known_tags_filters_system_nodes(self):
        """---> NEU: Testet, ob nur zuweisbare Tags geliefert werden (ohne Struktur-/System-Einträge)."""
        # Baumstruktur: Zuletzt-benutzt-Ordner (mit Kind), Struktur-Knoten, normale Tags, Temp-Tag, Duplikat
        tree = {
            "": ["node_recent", "node_struct", "node_labview", "node_temp"],
            "node_recent": ["node_recent_child"],
            "node_struct": ["node_rechnung", "node_rechnung_dup"],
        }
        data = {
            "node_recent": {"text": "⏱️ Zuletzt benutzt", "tags": ("recent_root", "structural_tag")},
            "node_recent_child": {"text": "LabVIEW", "tags": ("bundle", "recent_item")},
            "node_struct": {"text": "Dokument", "tags": ("bundle", "structural_tag")},
            "node_rechnung": {"text": "Rechnung", "tags": ("bundle",)},
            # Tkinter kann ein einzelnes Tag als nackten String liefern (FALLSTRICKE #9)
            "node_rechnung_dup": {"text": "rechnung", "tags": "bundle"},
            "node_labview": {"text": "LabVIEW", "tags": ("bundle",)},
            "node_temp": {"text": "Tippfehler-Tag", "tags": ("temp_tag",)},
        }

        self.mock_app.tree_tags.get_children.side_effect = lambda parent="": tree.get(parent, [])
        self.mock_app.tree_tags.item.side_effect = lambda iid, option=None, **kw: data.get(iid, {}).get(option, "")

        result = self.manager.get_known_tags()

        # Erwartung: nur die echten Tags, Duplikat (case-insensitive) nur einmal,
        # Struktur-Knoten, Temp-Tag und der komplette Zuletzt-benutzt-Ast fehlen
        self.assertEqual(result, ["Rechnung", "LabVIEW"])


class TestTagSearchEntry(unittest.TestCase):
    """Suchfeld über dem Tag-Baum: reine Match-Helfer + on_tag_search_changed/reset_tag_search."""

    def setUp(self):
        self.mock_app = MagicMock()
        self.mock_app.tag_mode_var.get.return_value = "assign"
        self.manager = TagManager(self.mock_app)

        # Testbestand in Anzeige-Reihenfolge (wie ihn _collect_searchable_nodes liefert)
        self.nodes = [
            ("i_dok", "dokument"),
            ("i_rech", "rechnung"),
            ("i_rech_nk", "rechnung nebenkosten"),
            ("i_vers", "versicherung"),
        ]

    # --- reine Funktionen (ohne Tk) -----------------------------------------
    def test_first_prefix_match(self):
        self.assertEqual(TagManager._first_prefix_match(self.nodes, "versi"), "i_vers")
        self.assertEqual(TagManager._first_prefix_match(self.nodes, "rech"), "i_rech")
        self.assertIsNone(TagManager._first_prefix_match(self.nodes, "xyz"))

    def test_first_substring_match(self):
        # "nebenkosten" kommt nur mitten im Text vor -> nur per Enthält-Suche findbar
        self.assertEqual(TagManager._first_substring_match(self.nodes, "nebenkosten"), "i_rech_nk")
        self.assertIsNone(TagManager._first_substring_match(self.nodes, "zzz"))

    def test_collect_searchable_nodes_filters_system_nodes(self):
        """Struktur-Kategorien bleiben drin, System-Knoten (Verlauf, Trennlinie, Temp) fliegen raus."""
        tree = {
            "": ["recent", "struct", "labview", "temp", "sep"],
            "recent": ["recent_child"],
            "struct": ["rechnung"],
        }
        data = {
            "recent": {"text": "⏱️ Zuletzt benutzt", "tags": ("recent_root", "structural_tag")},
            "recent_child": {"text": "LabVIEW", "tags": ("bundle", "recent_item")},
            "struct": {"text": "Dokument", "tags": ("bundle", "structural_tag")},
            "rechnung": {"text": "Rechnung", "tags": ("bundle",)},
            # Tkinter kann ein einzelnes Tag als nackten String liefern (FALLSTRICKE #9)
            "labview": {"text": "LabVIEW", "tags": "bundle"},
            "temp": {"text": "Tippfehler", "tags": ("temp_tag",)},
            "sep": {"text": "---", "tags": ("separator_tag",)},
        }
        self.mock_app.tree_tags.get_children.side_effect = lambda parent="": tree.get(parent, [])
        self.mock_app.tree_tags.item.side_effect = lambda iid, option=None, **kw: data.get(iid, {}).get(option, "")

        result = self.manager._collect_searchable_nodes()

        # Struktur-Knoten "Dokument" bleibt, Verlaufs-Ast/Temp/Trennlinie fehlen, Reihenfolge = Tiefensuche
        self.assertEqual(result, [("struct", "dokument"), ("rechnung", "rechnung"), ("labview", "labview")])

    # --- on_tag_search_changed / reset_tag_search (mit Mocks) --------------
    def _install_nodes(self, nodes):
        """Verdrahtet _collect_searchable_nodes fest auf die gegebene Knotenliste."""
        self.manager._collect_searchable_nodes = lambda: nodes

    def test_search_changed_prefix_selects_and_scrolls(self):
        self._install_nodes(self.nodes)
        self.mock_app.entry_tag_search.get.return_value = "versi"

        self.manager.on_tag_search_changed()

        self.mock_app.tree_tags.selection_set.assert_called_with("i_vers")
        self.mock_app.tree_tags.focus.assert_called_with("i_vers")
        self.mock_app.tree_tags.see.assert_called_with("i_vers")

    def test_search_changed_substring_fallback(self):
        self._install_nodes(self.nodes)
        # "nebenkosten" gibt es nur als Substring -> Präfix scheitert, Enthält greift
        self.mock_app.entry_tag_search.get.return_value = "nebenkosten"

        self.manager.on_tag_search_changed()

        self.mock_app.tree_tags.selection_set.assert_called_with("i_rech_nk")

    def test_search_changed_ignores_empty_and_placeholder(self):
        self._install_nodes(self.nodes)
        for value in ("", "   ", TagManager.TAG_SEARCH_PLACEHOLDER):
            self.mock_app.entry_tag_search.get.return_value = value
            self.manager.on_tag_search_changed()
        self.mock_app.tree_tags.selection_set.assert_not_called()

    def test_search_changed_no_match_leaves_selection_untouched(self):
        self._install_nodes(self.nodes)
        self.mock_app.entry_tag_search.get.return_value = "xyz123"

        self.manager.on_tag_search_changed()

        self.mock_app.tree_tags.selection_set.assert_not_called()

    def test_reset_tag_search_clears_entry_and_restores_placeholder(self):
        self.mock_app.entry_tag_search.get.return_value = ""
        result = self.manager.reset_tag_search(event=MagicMock())

        self.mock_app.entry_tag_search.delete.assert_called_with(0, tk.END)
        self.mock_app.entry_tag_search.insert.assert_called_with(0, TagManager.TAG_SEARCH_PLACEHOLDER)
        # Fokus wandert in den Baum: sonst tippt man hinter den Platzhalter weiter (T2.8)
        self.mock_app.tree_tags.focus_set.assert_called_once()
        self.assertEqual(result, "break")

    def test_search_shortcut_acts_on_found_tag(self):
        """F2/Strg+I im Suchfeld: Aktion läuft auf der Baum-Auswahl, Ereignis wird geschluckt."""
        self.mock_app.tree_tags.selection.return_value = ("i_vers",)
        aktion = MagicMock()
        self.assertEqual(self.manager.on_tag_search_shortcut(MagicMock(), aktion), "break")
        aktion.assert_called_once()

    def test_search_shortcut_without_selection_does_nothing(self):
        self.mock_app.tree_tags.selection.return_value = ()
        aktion = MagicMock()
        self.assertIsNone(self.manager.on_tag_search_shortcut(MagicMock(), aktion))
        aktion.assert_not_called()

    def test_search_return_moves_focus_to_tree(self):
        """Enter im Suchfeld übergibt den Tastatur-Fokus an den Baum, damit Leertaste den gefundenen Tag toggeln kann."""
        result = self.manager.on_tag_search_return(event=MagicMock())

        self.mock_app.tree_tags.focus_set.assert_called_once()
        self.assertEqual(result, "break")

    def _key(self, char):
        ev = MagicMock()
        ev.char = char
        return ev

    def test_tree_typed_redirects_focus_and_first_char_to_search(self):
        """Lostippen im Baum schickt Fokus + erstes Zeichen ins Suchfeld und löst sofort die Suche aus."""
        self.manager.on_tag_search_changed = MagicMock()

        result = self.manager.on_tag_tree_typed(self._key("v"))

        self.mock_app.entry_tag_search.focus_set.assert_called_once()
        self.mock_app.entry_tag_search.delete.assert_called_with(0, tk.END)
        self.mock_app.entry_tag_search.insert.assert_called_with(0, "v")
        self.manager.on_tag_search_changed.assert_called_once()
        self.assertEqual(result, "break")

    def test_tree_typed_ignores_space_and_nonprintable(self):
        self.manager.on_tag_search_changed = MagicMock()

        self.assertIsNone(self.manager.on_tag_tree_typed(self._key(" ")))
        self.assertIsNone(self.manager.on_tag_tree_typed(self._key("")))
        self.mock_app.entry_tag_search.focus_set.assert_not_called()
        self.manager.on_tag_search_changed.assert_not_called()


class _FakeTagTree:
    """Minimaler Treeview-Ersatz für den Tag-Katalog (insert/get_children/item)."""

    def __init__(self):
        self.nodes = {}
        self.roots = []
        self._n = 0

    def insert(self, parent, index, text="", tags=(), open=False):
        self._n += 1
        iid = f"T{self._n}"
        self.nodes[iid] = {"parent": parent, "text": text, "tags": tuple(tags), "open": open, "children": []}
        (self.roots if parent == "" else self.nodes[parent]["children"]).append(iid)
        return iid

    def get_children(self, parent=""):
        return tuple(self.roots if parent == "" else self.nodes[parent]["children"])

    def parent(self, iid):
        return self.nodes[iid]["parent"]

    def item(self, iid, option=None, **kw):
        if kw:
            self.nodes[iid].update(kw)
            return None
        return self.nodes[iid][option]


class TestAddTagsToCatalog(unittest.TestCase):
    """Automatisch wachsender Tag-Katalog (30.08.2026): Kategorie-Zuordnung, Sammelknoten, Dubletten."""

    def setUp(self):
        from tag_manager import TagManager
        self.app = MagicMock()
        self.tree = self.app.tree_tags = _FakeTagTree()
        self.tree.insert("", "end", text="⏱️ Zuletzt benutzt", tags=(TagManager.TAG_RECENT_ROOT, TagManager.TAG_STRUCTURAL))
        self.dokument = self.tree.insert("", "end", text="Dokument", tags=(TagManager.TAG_BUNDLE, TagManager.TAG_STRUCTURAL))
        self.tree.insert(self.dokument, "end", text="Rechnung", tags=(TagManager.TAG_BUNDLE,))
        self.thema = self.tree.insert("", "end", text="Thema", tags=(TagManager.TAG_BUNDLE, TagManager.TAG_STRUCTURAL))
        self.manager = TagManager(self.app)

    def _texte(self, parent):
        return [self.tree.item(c, "text") for c in self.tree.get_children(parent)]

    def test_komma_wird_aus_neuen_tags_entfernt(self):
        self.manager.add_tags_to_catalog([("Steuern, Finanzen", "Thema")])
        self.assertEqual(self._texte(self.thema), ["Steuern Finanzen"])

    def test_tags_in_kategorie(self):
        self.assertEqual(self.manager.tags_in_kategorie("dokument"), ["Rechnung"])
        self.assertEqual(self.manager.tags_in_kategorie("Thema"), [])
        self.assertEqual(self.manager.tags_in_kategorie("Gibt es nicht"), [])

    def test_get_kategorien_ohne_zuletzt_benutzt(self):
        self.assertEqual(self.manager.get_kategorien(), ["Dokument", "Thema"])

    def test_neue_tags_landen_in_kategorie_und_werden_gespeichert(self):
        aufgenommen = self.manager.add_tags_to_catalog([("Stromverbrauch", "thema"), ("Angebot", "Dokument")])
        self.assertEqual(aufgenommen, ["Stromverbrauch", "Angebot"])
        self.assertEqual(self._texte(self.thema), ["Stromverbrauch"])
        self.assertEqual(self._texte(self.dokument), ["Rechnung", "Angebot"])
        self.app.tag_editor.save_tags.assert_called_once()

    def test_unbekannte_kategorie_landet_unter_neu_ki(self):
        self.manager.add_tags_to_catalog([("Gas", ""), ("Wasser", "Gibt es nicht")])
        neu = [c for c in self.tree.get_children("") if self.tree.item(c, "text") == self.manager.KATEGORIE_NEU]
        self.assertEqual(len(neu), 1)
        self.assertIn("structural_tag", self.tree.item(neu[0], "tags"))
        self.assertEqual(self._texte(neu[0]), ["Gas", "Wasser"])

    def test_bekannte_tags_werden_uebersprungen(self):
        self.assertEqual(self.manager.add_tags_to_catalog([("rechnung", "Thema"), ("", "Thema")]), [])
        self.app.tag_editor.save_tags.assert_not_called()

    def test_struktur_kategorie_wird_nicht_als_tag_dupliziert(self):
        # FALLSTRICKE #59: 'Thema' ist eine graue Kategorie - kein zweites 'Thema' unter 'Neu (KI)'
        self.assertEqual(self.manager.add_tags_to_catalog([("thema", ""), ("Dokument", "Thema")]), [])
        self.assertEqual(self._texte(""), ["⏱️ Zuletzt benutzt", "Dokument", "Thema"])
        self.app.tag_editor.save_tags.assert_not_called()


class TestMehrfachZuweisung(unittest.TestCase):
    """
    Doppelklick auf ein Tag bei MEHREREN markierten Dokumenten (Nutzerwunsch 01.09.2026):
    additiv pro Dokument, nicht ueber das Tags-Eingabefeld (das zeigt nur das primaer
    markierte Dokument und wuerde die individuellen Tags der anderen platt machen).
    """

    ZEILEN = {
        "f1": ("", "A", "Grundsteuer, Werner Mustermann", "a.pdf", "a.pdf"),
        "f2": ("", "B", "---", "b.pdf", "b.pdf"),
        "f3": ("", "C", "Steuer, Grundsteuer", "c.pdf", "c.pdf"),
    }
    BAUM = {
        "n_finanzen": {"text": "Finanzen & Steuern", "parent": ""},
        "n_steuer": {"text": "Steuer", "parent": "n_finanzen"},
        "n_grund": {"text": "Grundsteuer", "parent": "n_steuer"},
    }

    def setUp(self):
        self.mock_app = MagicMock()
        self.mock_app.tag_mode_var = MagicMock()
        self.mock_app.tag_mode_var.get.return_value = "assign"
        self.mock_app.entry_tags.get.return_value = ""
        self.mock_app.tree_tags.item.side_effect = lambda iid, option=None, **k: (
            self.BAUM.get(iid, {}).get("text", "") if option == "text" else ("bundle",))
        self.mock_app.tree_tags.parent.side_effect = lambda iid: self.BAUM.get(iid, {}).get("parent", "")
        self.mock_app.tree_files.item.side_effect = lambda iid, option=None: self.ZEILEN[iid]
        self.manager = TagManager(self.mock_app)

    def test_ein_dokument_geht_weiter_ueber_das_eingabefeld(self):
        """Der bisherige Weg bleibt unveraendert, solange nur ein Dokument markiert ist."""
        self.mock_app.tree_files.selection.return_value = ["f1"]
        self.manager._toggle_tag("n_steuer")
        self.mock_app.entry_tags.insert.assert_called_once()
        self.mock_app.save_manager.ergaenze_tags_fuer_auswahl.assert_not_called()

    def test_mehrere_dokumente_ergaenzen_mit_oberkategorien(self):
        self.mock_app.tree_files.selection.return_value = ["f1", "f2"]
        self.manager._toggle_tag("n_grund")
        self.mock_app.save_manager.ergaenze_tags_fuer_auswahl.assert_called_once_with(
            ["Finanzen & Steuern", "Steuer", "Grundsteuer"])
        self.mock_app.entry_tags.insert.assert_not_called()

    def test_haben_alle_das_tag_schon_wird_es_entfernt(self):
        """Wie ein Kontrollkaestchen: alle markiert -> abwaehlen; gemischt -> ueberall setzen."""
        self.mock_app.tree_files.selection.return_value = ["f1", "f3"]   # beide haben "Grundsteuer"
        self.manager._toggle_tag("n_grund")
        self.mock_app.save_manager.ergaenze_tags_fuer_auswahl.assert_called_once_with(
            ["Grundsteuer"], entfernen=True)

    def test_gemischter_zustand_ergaenzt_ueberall(self):
        self.mock_app.tree_files.selection.return_value = ["f1", "f3"]   # nur f3 hat "Steuer"
        self.manager._toggle_tag("n_steuer")
        self.mock_app.save_manager.ergaenze_tags_fuer_auswahl.assert_called_once_with(
            ["Finanzen & Steuern", "Steuer"])

    def test_leere_tagspalte_zaehlt_als_fehlend(self):
        self.mock_app.tree_files.selection.return_value = ["f2", "f3"]   # f2 hat "---"
        self.manager._toggle_tag("n_steuer")
        self.assertFalse(self.mock_app.save_manager.ergaenze_tags_fuer_auswahl.call_args.kwargs.get("entfernen"))


class TestMerkmaleFuerDubletten(unittest.TestCase):
    """
    Praxisfund 01.09.2026: Die reale Sammlung nennt den Adressen-Zweig
    "Wohnen & Immobilien / Adressen", die ausgelieferte Vorlage "Objekte & Adressen".
    Der frueher exakte Namensvergleich lieferte still eine leere Liste - die
    Objekt-Unterscheidung der Dubletten-Erkennung konnte damit NIE greifen.
    """

    def _manager(self, kategorien_mit_tags):
        app = MagicMock()
        manager = TagManager(app)
        manager.tags_in_kategorie = lambda name: kategorien_mit_tags.get(name, [])
        return manager

    def test_findet_die_kategorie_unter_ihrem_variantennamen(self):
        manager = self._manager({"Personen": ["Hermann Mustermann"],
                                 "Adressen": ["Musterheim", "Zum Alten Fass 1"]})
        merkmale = manager.merkmale_fuer_dubletten()
        self.assertEqual(merkmale["Personen"], ["Hermann Mustermann"])
        self.assertEqual(merkmale["Objekte & Adressen"], ["Musterheim", "Zum Alten Fass 1"])

    def test_vorlagen_name_funktioniert_weiterhin(self):
        manager = self._manager({"Personen": ["A"], "Objekte & Adressen": ["B"]})
        self.assertEqual(manager.merkmale_fuer_dubletten()["Objekte & Adressen"], ["B"])

    def test_ohne_passende_kategorie_leere_liste(self):
        manager = self._manager({"Personen": ["A"]})
        merkmale = manager.merkmale_fuer_dubletten()
        self.assertEqual(merkmale["Objekte & Adressen"], [])
        self.assertEqual(set(merkmale), {"Personen", "Objekte & Adressen"})


class TestSynonyme(unittest.TestCase):
    """Synonym-Knoten (Nutzeridee 08.09.2026): stehen für das zuweisbare Tag darüber, werden nie selbst vergeben."""

    def setUp(self):
        from tag_manager import TagManager
        self.app = MagicMock()
        self.tree = self.app.tree_tags = _FakeTagTree()
        self.tree.insert("", "end", text="⏱️ Zuletzt benutzt", tags=(TagManager.TAG_RECENT_ROOT, TagManager.TAG_STRUCTURAL))
        thema = self.tree.insert("", "end", text="Thema", tags=(TagManager.TAG_BUNDLE, TagManager.TAG_STRUCTURAL))
        vers = self.tree.insert(thema, "end", text="Versicherung", tags=(TagManager.TAG_BUNDLE,))
        haft = self.tree.insert(vers, "end", text="Haftpflicht", tags=(TagManager.TAG_BUNDLE,))
        self.tree.insert(haft, "end", text="Haftpflichtversicherung", tags=(TagManager.TAG_BUNDLE, TagManager.TAG_SYNONYM))
        self.synonym = self.tree.insert(haft, "end", text="Privathaftpflicht", tags=(TagManager.TAG_BUNDLE, TagManager.TAG_SYNONYM))
        # Synonym direkt unter einer grauen Kategorie: kein zuweisbares Ziel -> wirkungslos
        self.tree.insert(thema, "end", text="Sonstiges", tags=(TagManager.TAG_BUNDLE, TagManager.TAG_SYNONYM))
        # Synonym auf oberster Ebene: ebenfalls wirkungslos
        self.tree.insert("", "end", text="Verwaist", tags=(TagManager.TAG_BUNDLE, TagManager.TAG_SYNONYM))
        self.manager = TagManager(self.app)

    def test_get_synonyme_zeigt_auf_das_naechste_zuweisbare_tag(self):
        self.assertEqual(self.manager.get_synonyme(),
                         {"haftpflichtversicherung": "Haftpflicht", "privathaftpflicht": "Haftpflicht"})

    def test_synonyme_sind_weder_tags_noch_kategorien_noch_eltern(self):
        self.assertEqual(self.manager.get_known_tags(), ["Versicherung", "Haftpflicht"])
        self.assertEqual(self.manager.get_kategorien(), ["Thema"])
        self.assertEqual(self.manager.get_tag_eltern(), {"haftpflicht": ["Versicherung"]})
        self.assertEqual(self.manager.tags_in_kategorie("Thema"), ["Versicherung", "Haftpflicht"])

    def test_synonym_text_wird_nie_als_neues_tag_aufgenommen(self):
        self.assertEqual(self.manager.add_tags_to_catalog([("Haftpflichtversicherung", "Thema"), ("Hausrat", "Thema")]),
                         ["Hausrat"])

    def test_doppelklick_fuegt_synonym_nie_hinzu(self):
        self.app.tag_mode_var.get.return_value = "assign"
        self.app.tree_files.selection.return_value = ("f1",)
        self.app.entry_tags.get.return_value = "Versicherung"
        self.manager._toggle_tag(self.synonym)
        self.app.entry_tags.delete.assert_not_called()
        self.app.entry_tags.insert.assert_not_called()

    def test_doppelklick_entfernt_synonym_text_aus_dem_dokument(self):
        # Nutzerfund 08.09.2026: Altbestand trägt den Text noch - Doppelklick muss ihn wegnehmen können
        self.app.tag_mode_var.get.return_value = "assign"
        self.app.tree_files.selection.return_value = ("f1",)
        self.app.entry_tags.get.return_value = "Versicherung, Privathaftpflicht, Rechnung"
        self.manager._toggle_tag(self.synonym)
        self.app.entry_tags.insert.assert_called_with("1.0", "Versicherung, Rechnung")
        # bei mehreren markierten Dokumenten passiert nichts
        self.app.entry_tags.insert.reset_mock()
        self.app.tree_files.selection.return_value = ("f1", "f2")
        self.manager._toggle_tag(self.synonym)
        self.app.entry_tags.insert.assert_not_called()


class TestNeueTagsInDenKatalog(unittest.TestCase):
    """Etappe 6 (FALLSTRICKE #120): Neue Tags kommen nur noch von Hand (Ablage-Vorschau, Begleitet erfassen) und gleich in
    den Katalog - die Bewährungs-Warteliste für KI-Tags (09.09.2026) ist entfallen."""

    def setUp(self):
        self.app = MagicMock()
        self.tree = self.app.tree_tags = _FakeTagTree()
        self.thema = self.tree.insert("", "end", text="Thema", tags=(TagManager.TAG_BUNDLE, TagManager.TAG_STRUCTURAL))
        self.tree.insert(self.thema, "end", text="Rechnung", tags=(TagManager.TAG_BUNDLE,))
        self.manager = TagManager(self.app)

    def _texte(self, parent):
        return [self.tree.item(c, "text") for c in self.tree.get_children(parent)]

    def test_neues_tag_kommt_sofort_in_den_katalog(self):
        self.assertEqual(self.manager.add_tags_to_catalog([("Thorax", "Thema")]), ["Thorax"])
        self.assertEqual(self._texte(self.thema), ["Rechnung", "Thorax"])
        self.app.tag_editor.save_tags.assert_called_once()

    def test_bekanntes_tag_nicht_doppelt(self):
        self.assertEqual(self.manager.add_tags_to_catalog([("rechnung", "Thema"), ("Thema", "")]), [])
        self.assertEqual(self._texte(self.thema), ["Rechnung"])
