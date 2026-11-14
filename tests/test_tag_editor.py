import unittest
from unittest.mock import MagicMock, patch
from tag_manager import TagManager
from tag_editor import TagEditor, migriere_neu_kategorie

class TestTagEditor(unittest.TestCase):
    def setUp(self):
        self.mock_app = MagicMock()
        self.editor = TagEditor(self.mock_app)

    def test_is_protected_node(self):
        """Testet die Kern-Schutzfunktion vor System-Ordnern."""
        # Das darf editiert werden
        self.assertFalse(self.editor._is_protected_node(["bundle", "structural_tag"]))
        
        # Das darf NICHT editiert werden (System-Tags)
        self.assertTrue(self.editor._is_protected_node([TagManager.TAG_RECENT_ROOT]))
        self.assertTrue(self.editor._is_protected_node([TagManager.TAG_TEMP]))
        self.assertTrue(self.editor._is_protected_node([TagManager.TAG_SEP]))

    @patch('json.dump')
    def test_save_excludes_system_nodes(self, mock_json_dump):
        """Testet, ob System-Tags heimlich beim Speichern in die tags.json rutschen."""
        
        # Wir simulieren drei Nodes in unserem Treeview:
        # 1. Ein echtes Tag, 2. Der "Zuletzt benutzt" Ordner, 3. Eine Trennlinie
        fake_children = ["node1", "node2", "node3"]
        self.mock_app.tree_tags.get_children.side_effect = lambda parent: fake_children if parent == "" else []
        
        # Wir gaukeln vor, welche Tags diese Nodes besitzen
        def mock_item(iid, option):
            if option == "tags":
                if iid == "node1": return ("bundle",)
                if iid == "node2": return (TagManager.TAG_RECENT_ROOT,)
                if iid == "node3": return (TagManager.TAG_SEP,)
            if option == "text":
                if iid == "node1": return "Rechnung"
                return "DarfNichtGemerktWerden"
        
        self.mock_app.tree_tags.item.side_effect = mock_item

        # Wir rufen die Lese-Methode auf
        nodes_to_save = self.editor._get_nodes("")
        
        # Erwartung: Die Liste darf NUR "Rechnung" enthalten. 
        # node2 und node3 müssen gnadenlos ignoriert worden sein!
        self.assertEqual(len(nodes_to_save), 1)
        self.assertEqual(nodes_to_save[0]["text"], "Rechnung")

class TestDeleteTagRueckfrage(unittest.TestCase):
    """
    Nutzerentscheidung 07.09.2026: Bei abgeschalteten Sicherheitsabfragen darf ein BLATT-Tag
    ohne Rückfrage weg - Kategorien (graue Struktur-Knoten) und Tags mit Unter-Tags fragen immer.
    """

    def setUp(self):
        import bestaetigung
        from tests.test_tag_manager import _FakeTagTree
        self.app = MagicMock()
        self.tree = self.app.tree_tags = _FakeTagTree()
        self.kategorie = self.tree.insert("", "end", text="Versicherung", tags=(TagManager.TAG_BUNDLE, TagManager.TAG_STRUCTURAL))
        self.eltern = self.tree.insert("", "end", text="Kfz", tags=(TagManager.TAG_BUNDLE,))
        self.tree.insert(self.eltern, "end", text="Haftpflicht", tags=(TagManager.TAG_BUNDLE,))
        self.blatt = self.tree.insert("", "end", text="Rechnung", tags=(TagManager.TAG_BUNDLE,))
        self.tree.selection = lambda: self._auswahl
        self.tree.delete = MagicMock()
        self.editor = TagEditor(self.app)
        self.editor.save_tags = MagicMock()
        # Sicherheitsabfragen AUS
        aus = MagicMock()
        aus.get.return_value = False
        bestaetigung.konfigurieren(aus)
        self.addCleanup(bestaetigung.konfigurieren, None)

    def _loeschen(self, iid):
        self._auswahl = (iid,)
        with patch("tag_editor.messagebox.askyesno", return_value=False) as frage:
            self.editor.delete_tag()
        return frage

    def test_blatt_tag_geht_ohne_rueckfrage(self):
        frage = self._loeschen(self.blatt)
        frage.assert_not_called()
        self.tree.delete.assert_called_once_with(self.blatt)

    def test_kategorie_fragt_immer(self):
        frage = self._loeschen(self.kategorie)
        frage.assert_called_once()
        self.tree.delete.assert_not_called()

    def test_tag_mit_unter_tags_fragt_immer(self):
        frage = self._loeschen(self.eltern)
        frage.assert_called_once()
        self.tree.delete.assert_not_called()


class TestSynonymUmschalten(unittest.TestCase):
    """Rechtsklick 'Als Synonym umschalten' (08.09.2026) und is_synonym in tags.json."""

    def setUp(self):
        from tests.test_tag_manager import _FakeTagTree
        self._FakeTagTree = _FakeTagTree
        self.app = MagicMock()
        self.tree = self.app.tree_tags = _FakeTagTree()
        self.eltern = self.tree.insert("", "end", text="Haftpflicht", tags=(TagManager.TAG_BUNDLE,))
        self.kind = self.tree.insert(self.eltern, "end", text="Haftpflichtversicherung",
                                     tags=(TagManager.TAG_BUNDLE, TagManager.TAG_STRUCTURAL))
        self.tree.selection = lambda: self._auswahl
        self.editor = TagEditor(self.app)
        self.editor.save_tags = MagicMock()

    def test_umschalten_setzt_synonym_und_entfernt_struktur(self):
        self._auswahl = (self.kind,)
        self.editor.toggle_synonym()
        tags = self.tree.item(self.kind, "tags")
        self.assertIn(TagManager.TAG_SYNONYM, tags)
        self.assertNotIn(TagManager.TAG_STRUCTURAL, tags)
        self.editor.save_tags.assert_called_once()
        self.editor.toggle_synonym()   # und zurück
        self.assertNotIn(TagManager.TAG_SYNONYM, self.tree.item(self.kind, "tags"))

    def test_oberste_ebene_geht_nicht(self):
        self._auswahl = (self.eltern,)
        with patch("tag_editor.messagebox.showinfo") as info:
            self.editor.toggle_synonym()
        self.assertNotIn(TagManager.TAG_SYNONYM, self.tree.item(self.eltern, "tags"))
        info.assert_called_once()
        self.editor.save_tags.assert_not_called()

    def test_knoten_mit_unter_tags_geht_nicht(self):
        blatt = self.tree.insert(self.kind, "end", text="Unter", tags=(TagManager.TAG_BUNDLE,))
        self._auswahl = (self.kind,)
        with patch("tag_editor.messagebox.showinfo") as info:
            self.editor.toggle_synonym()
        self.assertNotIn(TagManager.TAG_SYNONYM, self.tree.item(self.kind, "tags"))
        info.assert_called_once()
        self._auswahl = (blatt,)
        self.editor.toggle_synonym()   # das Blatt darunter darf
        self.assertIn(TagManager.TAG_SYNONYM, self.tree.item(blatt, "tags"))

    def test_struktur_umschalten_entfernt_synonym(self):
        self._auswahl = (self.kind,)
        self.editor.toggle_synonym()
        self.editor.toggle_structural()
        tags = self.tree.item(self.kind, "tags")
        self.assertIn(TagManager.TAG_STRUCTURAL, tags)
        self.assertNotIn(TagManager.TAG_SYNONYM, tags)

    def test_is_synonym_ueberlebt_speichern_und_laden(self):
        self._auswahl = (self.kind,)
        self.editor.toggle_synonym()
        daten = self.editor._get_nodes("")
        self.assertEqual(daten, [{"text": "Haftpflicht", "children": [
            {"text": "Haftpflichtversicherung", "children": [], "is_synonym": True}]}])
        neu = self.app.tree_tags = self._FakeTagTree()
        self.editor._insert_nodes("", daten)
        kind = neu.get_children(neu.get_children("")[0])[0]
        self.assertEqual(neu.item(kind, "tags"), (TagManager.TAG_BUNDLE, TagManager.TAG_SYNONYM))


class TestNeuKategorieUmbenennen(unittest.TestCase):
    """Etappe 6 (Peter 08.11.2026): „Neu (KI)“ heißt jetzt „Neu“, die neuen Tags kommen nur noch von Hand."""

    def test_alte_kategorie_wird_umbenannt(self):
        daten = [{"text": "Thema", "is_structural": True, "children": []},
                 {"text": "Neu (KI)", "is_structural": True, "children": [{"text": "Thorax", "children": []}]}]
        neu = migriere_neu_kategorie(daten)
        self.assertEqual([k["text"] for k in neu], ["Thema", "Neu"])
        self.assertEqual(neu[1]["children"], [{"text": "Thorax", "children": []}])
        self.assertTrue(neu[1]["is_structural"])
        self.assertEqual(daten[1]["text"], "Neu (KI)")      # Eingabe bleibt unverändert

    def test_vorhandene_neu_kategorie_nimmt_die_tags_auf(self):
        daten = [{"text": "Neu", "is_structural": True, "children": [{"text": "Gas", "children": []}]},
                 {"text": "Neu (KI)", "is_structural": True,
                  "children": [{"text": "gas", "children": []}, {"text": "Strom", "children": []}]}]
        neu = migriere_neu_kategorie(daten)
        self.assertEqual([k["text"] for k in neu], ["Neu"])
        self.assertEqual([c["text"] for c in neu[0]["children"]], ["Gas", "Strom"])

    def test_ohne_alte_kategorie_unveraendert(self):
        daten = [{"text": "Thema", "children": []}]
        self.assertIs(migriere_neu_kategorie(daten), daten)
        self.assertIsNone(migriere_neu_kategorie(None))
