import tkinter as tk
from tkinter import ttk, messagebox  # noqa: F401 -- messagebox von test_tag_manager.py gepatcht (tag_manager.messagebox)
from ui_utils import UIUtils
import dubletten
import zuletzt_benutzt

class TagManager:
    # --- Konstanten für die Tag-Zustände (verhindert Tippfehler) ---
    TAG_TEMP = "temp_tag"
    TAG_SEP = "separator_tag"
    TAG_ACTIVE = "active_tag"
    TAG_RECENT_ROOT = "recent_root"
    TAG_RECENT_ITEM = "recent_item"
    TAG_STRUCTURAL = "structural_tag"
    # Synonym-Knoten (08.09.2026): steht für das zuweisbare Tag darüber, wird nie selbst
    # vergeben - siehe get_synonyme / auto_pilot.ersetze_synonyme
    TAG_SYNONYM = "synonym_tag"
    TAG_BUNDLE = "bundle"

    # Platzhaltertext des Suchfelds über dem Tag-Baum (siehe layout_builder.py) -
    # ein echtes ttk.Entry statt eines gebastelten Headers, damit der Fokus-Rahmen
    # automatisch vom Theme kommt (wie bei entry_search der Volltextsuche).
    TAG_SEARCH_PLACEHOLDER = "🔎 Tag suchen…"

    def __init__(self, app):
        """Initialisiert den Manager für die Verschlagwortung und den Tag-Baum."""
        self.app = app

    def on_tag_mode_change(self):
        """Schaltet den Tag-Baum zwischen Zuweisungs- und Filter-Modus um (inkl. Hintergrundfarbe) und triggert die Suche neu."""
        style = ttk.Style()
        if self.app.tag_mode_var.get() == "filter":
            style.configure("Tags.Treeview", background="#e6f2ff", fieldbackground="#e6f2ff")
        else:
            style.configure("Tags.Treeview", background="white", fieldbackground="white")
            self.app.tree_tags.selection_remove(self.app.tree_tags.selection())
        self.app.search_manager.trigger_search()

    def on_tag_select(self, event):
        """Löst im Filter-Modus bei Tag-Auswahl eine neue Suche aus."""
        if self.app.tag_mode_var.get() == "filter":
            self.app.search_manager.trigger_search()

    def _get_current_tags(self):
        """Hilfsmethode: Liest das Textfeld aus und liefert eine saubere Liste zurück."""
        raw = self.app.entry_tags.get("1.0", tk.END).strip()
        if raw in ("", "---"):
            return []
        return [t.strip() for t in raw.split(",") if t.strip()]

    def get_known_tags(self):
        """
        Sammelt alle zuweisbaren Tag-Namen aus dem Vorlagen-Baum — ohne Struktur-Kategorien
        (grau, nicht zuweisbar) und ohne System-Einträge (Temp-Tags, Trennlinie,
        'Zuletzt benutzt'-Ordner samt Inhalt, da dessen Einträge nur Kopien echter Tags sind).
        :return: Liste der Tag-Texte in Baum-Reihenfolge, ohne Duplikate.
        """
        known = []
        seen = set()

        def walk(parent=""):
            for child in self.app.tree_tags.get_children(parent):
                item_tags = self.app.tree_tags.item(child, "tags")
                # Tkinter kann ein einzelnes Tag als nackten String liefern (FALLSTRICKE #9)
                if isinstance(item_tags, str):
                    item_tags = (item_tags,)

                if self.TAG_RECENT_ROOT in item_tags:
                    continue  # inkl. Kinder überspringen

                if (self.TAG_TEMP not in item_tags and self.TAG_SEP not in item_tags
                        and self.TAG_RECENT_ITEM not in item_tags
                        and self.TAG_STRUCTURAL not in item_tags
                        and self.TAG_SYNONYM not in item_tags):
                    text = self.app.tree_tags.item(child, "text")
                    if text.lower() not in seen:
                        seen.add(text.lower())
                        known.append(text)
                walk(child)

        walk()
        return known

    def _item_tags(self, item):
        item_tags = self.app.tree_tags.item(item, "tags")
        return (item_tags,) if isinstance(item_tags, str) else tuple(item_tags)

    def get_kategorien(self):
        """
        Namen aller Struktur-Kategorien des Katalogs (graue, nicht zuweisbare Knoten wie
        'Dokument', 'Absender') in Baum-Reihenfolge - die Liste, aus der die Vollautomatik
        neue Tags einsortieren lässt. Ohne 'Zuletzt benutzt' und ohne Duplikate.
        """
        kategorien = []
        seen = set()

        def walk(parent=""):
            for child in self.app.tree_tags.get_children(parent):
                item_tags = self._item_tags(child)
                if self.TAG_RECENT_ROOT in item_tags:
                    continue
                if self.TAG_STRUCTURAL in item_tags and self.TAG_SYNONYM not in item_tags:
                    text = self.app.tree_tags.item(child, "text")
                    if text.lower() not in seen:
                        seen.add(text.lower())
                        kategorien.append(text)
                walk(child)

        walk()
        return kategorien

    def get_tag_eltern(self):
        """
        Oberkategorien-Zuordnung für die Auto-Hierarchie der Vollautomatik:
        {tag (klein): [zuweisbare Eltern-Tags von oben nach unten]}. Vergibt die KI
        'Gebäudebrandversicherung', bekommt das Dokument auch 'Versicherung' - genau
        wie beim manuellen Klick im Tag-Baum (toggle_tag). Struktur-Kategorien (grau,
        nicht zuweisbar) zählen wie dort NICHT als Eltern. Nur Tags MIT zuweisbaren
        Eltern stehen in der Zuordnung. NUR vom Hauptthread aufrufen (Tkinter).
        """
        zuordnung = {}

        def walk(parent, eltern):
            for child in self.app.tree_tags.get_children(parent):
                item_tags = self._item_tags(child)
                if self.TAG_RECENT_ROOT in item_tags:
                    continue  # 'Zuletzt benutzt' samt Kindern: nur Kopien echter Tags
                text = self.app.tree_tags.item(child, "text")
                zuweisbar = (self.TAG_TEMP not in item_tags and self.TAG_SEP not in item_tags
                             and self.TAG_RECENT_ITEM not in item_tags
                             and self.TAG_STRUCTURAL not in item_tags
                             and self.TAG_SYNONYM not in item_tags)
                if zuweisbar and eltern and text.lower() not in zuordnung:
                    zuordnung[text.lower()] = list(eltern)
                walk(child, eltern + [text] if zuweisbar else eltern)

        walk("", [])
        return zuordnung

    def get_synonyme(self):
        """
        Synonym-Zuordnung des Katalogs für die Vollautomatik: {synonym (klein): Ziel-Tag}.
        Ein Synonym-Knoten (Rechtsklick "Als Synonym umschalten") unter einem Tag bedeutet:
        schlägt die KI DIESEN Text vor, bekommt das Dokument stattdessen das Tag darüber -
        der Synonym-Text selbst wird nie vergeben ('Haftpflichtversicherung' -> 'Haftpflicht',
        'Einkommensteuer' -> 'Steuererklärung'). Ziel ist das nächste zuweisbare Tag über
        dem Knoten; ein Synonym ohne solches (oberste Ebene, nur graue Kategorien darüber)
        bleibt wirkungslos. Bewusst kein "grau = Synonym" (Nutzerentscheidung 08.09.2026):
        graue Knoten sind bei Peter auch Struktur (Bewohner unter der Adresse).
        NUR vom Hauptthread aufrufen (Tkinter).
        """
        zuordnung = {}

        def walk(parent, ziel):
            for child in self.app.tree_tags.get_children(parent):
                item_tags = self._item_tags(child)
                if self.TAG_RECENT_ROOT in item_tags:
                    continue
                text = self.app.tree_tags.item(child, "text")
                if self.TAG_SYNONYM in item_tags:
                    if ziel and text.strip().lower() not in zuordnung:
                        zuordnung[text.strip().lower()] = ziel
                    continue  # unter einem Synonym liegt nichts Zuweisbares
                zuweisbar = (self.TAG_TEMP not in item_tags and self.TAG_SEP not in item_tags
                             and self.TAG_RECENT_ITEM not in item_tags
                             and self.TAG_STRUCTURAL not in item_tags)
                walk(child, text if zuweisbar else ziel)

        walk("", "")
        return zuordnung

    def tags_in_kategorie(self, kategorie):
        """
        Alle zuweisbaren Tags unterhalb einer Struktur-Kategorie (z.B. 'Personen' -
        die Namens-Tags für die Dubletten-Unterscheidung). Leere Liste, wenn es die
        Kategorie nicht gibt. NUR vom Hauptthread aufrufen (Tkinter).
        """
        knoten = self._finde_kategorie_knoten(kategorie)
        if knoten is None:
            return []
        ergebnis = []

        def walk(parent):
            for child in self.app.tree_tags.get_children(parent):
                item_tags = self._item_tags(child)
                if self.TAG_STRUCTURAL not in item_tags and self.TAG_SYNONYM not in item_tags:
                    ergebnis.append(self.app.tree_tags.item(child, "text"))
                walk(child)

        walk(knoten)
        return ergebnis

    def merkmale_fuer_dubletten(self):
        """
        Unterscheidungs-Tags für die Dubletten-Erkennung: {kanonische Kategorie: [Tags]}.

        Sucht jede Kategorie unter mehreren möglichen Namen (dubletten.KATEGORIE_VARIANTEN) —
        ein gewachsener Katalog nennt den Adressen-Zweig z.B. „Wohnen & Immobilien /
        Adressen" statt „Objekte & Adressen" wie die ausgelieferte Vorlage. Der frühere
        exakte Namensvergleich lieferte dort still eine leere Liste, womit die Unterscheidung
        zweier Objekte („Zum Alten Fass 1" vs. „... 3") nie greifen konnte.
        NUR vom Hauptthread aufrufen (liest den Tag-Baum).
        """
        merkmale = {}
        for kanonisch, varianten in dubletten.KATEGORIE_VARIANTEN.items():
            gefunden = []
            for name in varianten:
                gefunden = self.tags_in_kategorie(name)
                if gefunden:
                    break
            merkmale[kanonisch] = gefunden
        return merkmale

    KATEGORIE_NEU = "Neu"     # bis 08.11.2026 „Neu (KI)“, tag_editor.migriere_neu_kategorie stellt um

    def _finde_kategorie_knoten(self, name):
        """Struktur-Knoten mit diesem Namen (Groß/Klein egal) oder None."""
        gesucht = (name or "").strip().lower()
        if not gesucht:
            return None

        def walk(parent=""):
            for child in self.app.tree_tags.get_children(parent):
                item_tags = self._item_tags(child)
                if self.TAG_RECENT_ROOT in item_tags:
                    continue
                if self.TAG_STRUCTURAL in item_tags and self.app.tree_tags.item(child, "text").lower() == gesucht:
                    return child
                treffer = walk(child)
                if treffer:
                    return treffer
            return None

        return walk()

    def add_tags_to_catalog(self, neue_tags):
        """
        Nimmt von der Vollautomatik vergebene, noch unbekannte Tags in den Katalog auf
        (Nutzer-Entscheidung 30.08.2026: der Katalog wächst automatisch, ein falscher Tag ist
        schneller gelöscht als ein fehlender angelegt). Jedes Tag landet unter der
        angegebenen Kategorie; ist keine oder eine unbekannte angegeben, unter der
        Sammelkategorie 'Neu' (wird bei Bedarf als Struktur-Knoten angelegt), damit der
        Nutzer die Neuzugänge auf einen Blick findet. Bereits bekannte Tags werden übersprungen -
        auch solche, die als graue Struktur-Kategorie im Katalog stehen (FALLSTRICKE #59:
        sonst entsteht 'Gesundheit' ein zweites Mal als zuweisbarer Tag unter 'Neu').

        Seit Etappe 6 (08.11.2026, FALLSTRICKE #120) kommen hier nur noch Tags an, die ein Mensch in der
        Ablage-Vorschau oder in „Begleitet erfassen“ eingetragen hat; die Bewährungs-Warteliste für KI-Tags
        (tag_kandidaten) ist entfallen.
        NUR vom Hauptthread aufrufen (Tkinter). :param neue_tags: Liste von (Tag, Kategorie)
        :return: Liste der tatsächlich aufgenommenen Tag-Namen
        """
        # Synonym-Texte zählen ebenfalls als bekannt: sie sind bewusst KEIN Tag, dürfen also
        # auch nicht als solches neu entstehen (ersetze_synonyme hat sie normalerweise schon
        # vorher durch ihr Ziel-Tag ersetzt - das hier ist der zweite Gurt).
        bekannt = ({t.lower() for t in self.get_known_tags()} | {k.lower() for k in self.get_kategorien()}
                   | set(self.get_synonyme()))
        # Komma ist das Trennzeichen des Schlagwortfelds - darf nie Teil eines Tags sein (FALLSTRICKE #38)
        paare = [(" ".join((tag or "").replace(",", " ").split()), kategorie) for tag, kategorie in neue_tags or ()]
        paare = [(tag, kategorie) for tag, kategorie in paare if tag and tag.lower() not in bekannt]
        aufgenommen = []
        for tag, kategorie in paare:
            if tag.lower() in bekannt:
                continue
            knoten = self._finde_kategorie_knoten(kategorie)
            if knoten is None:
                knoten = self._finde_kategorie_knoten(self.KATEGORIE_NEU)
                if knoten is None:
                    knoten = self.app.tree_tags.insert(
                        "", "end", text=self.KATEGORIE_NEU, tags=(self.TAG_BUNDLE, self.TAG_STRUCTURAL), open=True)
            self.app.tree_tags.insert(knoten, "end", text=tag, tags=(self.TAG_BUNDLE,))
            self.app.tree_tags.item(knoten, open=True)
            bekannt.add(tag.lower())
            aufgenommen.append(tag)
        if aufgenommen and hasattr(self.app, "tag_editor"):
            self.app.tag_editor.save_tags()
        return aufgenommen

    # ==========================================
    # SUCHFELD ÜBER DEM TAG-BAUM (Live-Synchronisation)
    # ==========================================
    def on_tag_search_changed(self, event=None):
        """
        Live-Suche im Tag-Baum: bei jedem Tastendruck im Suchfeld über dem Baum
        (entry_tag_search) springt die Markierung auf den passenden Tag - zuerst
        Präfix-Suche ("versi" findet "Versicherung"), sonst Enthält-Suche. Leeres
        Feld oder unveränderter Platzhalter lassen die Baum-Auswahl unangetastet.
        """
        text = self.app.entry_tag_search.get().strip().lower()
        if not text or text == self.TAG_SEARCH_PLACEHOLDER.lower():
            return

        nodes = self._collect_searchable_nodes()
        if not nodes:
            return

        match = self._first_prefix_match(nodes, text) or self._first_substring_match(nodes, text)
        if match is not None:
            self.app.tree_tags.selection_set(match)
            self.app.tree_tags.focus(match)
            self.app.tree_tags.see(match)  # klappt bei Bedarf die Elternknoten auf

    def reset_tag_search(self, event=None):
        """
        Leert das Tag-Suchfeld (z.B. per Esc), stellt den Platzhalter wieder her und gibt
        den Tastatur-Fokus an den Baum. Ohne den Fokuswechsel stünde der Cursor hinter dem
        frisch eingesetzten Platzhalter und das nächste Zeichen würde an "🔎 Tag suchen…"
        angehängt (T2.8, 11.09.2026); im Baum wirken außerdem F2/Entf/Strg-Kürzel sofort.
        """
        self.app.entry_tag_search.delete(0, tk.END)
        UIUtils.add_placeholder(self.app.entry_tag_search, self.TAG_SEARCH_PLACEHOLDER)
        self.app.tree_tags.focus_set()
        return "break" if event is not None else None

    def on_tag_search_shortcut(self, event, aktion):
        """
        F2 / Strg+I im Suchfeld wirken auf den gerade gefundenen (im Baum markierten) Tag,
        als stünde der Fokus im Baum - man muss nach dem Suchen nicht erst Enter drücken.
        Entf, Strg+X und Strg+V bleiben bewusst Textbearbeitung im Feld.
        """
        if not self.app.tree_tags.selection():
            return None
        aktion()
        return "break"

    def on_tag_search_return(self, event=None):
        """
        Enter im Suchfeld: Tastatur-Fokus springt auf den Baum, die Auswahl (der
        zuletzt gefundene Tag) bleibt bestehen - Leertaste schaltet ihn direkt zu/ab,
        ohne den Baum extra anklicken zu müssen.
        """
        self.app.tree_tags.focus_set()
        return "break"

    def on_tag_tree_typed(self, event):
        """
        Tippt man los, während der Baum den Fokus hat (z.B. direkt nach Enter aus dem
        Suchfeld heraus), springt der Fokus automatisch zurück ins Suchfeld und
        übernimmt das erste Zeichen - man kann nahtlos weitersuchen, ohne das Feld
        extra anzuklicken. Leertaste (Zuweisungs-Toggle) und alle anderen nicht
        druckbaren Tasten (Navigation, F2/Entf/Strg-Kürzel) bleiben unberührt.
        """
        if not event.char or not event.char.isprintable() or event.char == " ":
            return None
        self.app.entry_tag_search.focus_set()
        self.app.entry_tag_search.delete(0, tk.END)
        self.app.entry_tag_search.insert(0, event.char)
        self.app.entry_tag_search.icursor(tk.END)
        self.on_tag_search_changed()
        return "break"

    def _collect_searchable_nodes(self):
        """
        Sammelt alle durchsuchbaren Baum-Knoten in Anzeige-Reihenfolge (Tiefensuche)
        als Liste von (iid, kleingeschriebener_text). Struktur-Kategorien bleiben drin
        (man will auch dorthin springen können), System-Knoten (Trennlinie, der komplette
        'Zuletzt benutzt'-Ast, Temp-Tags) werden übersprungen.
        """
        result = []

        def walk(parent=""):
            for child in self.app.tree_tags.get_children(parent):
                item_tags = self.app.tree_tags.item(child, "tags")
                # Tkinter kann ein einzelnes Tag als nackten String liefern (FALLSTRICKE #9)
                if isinstance(item_tags, str):
                    item_tags = (item_tags,)

                if self.TAG_RECENT_ROOT in item_tags:
                    continue  # Verlaufs-Ordner samt Kindern überspringen

                if (self.TAG_SEP not in item_tags
                        and self.TAG_RECENT_ITEM not in item_tags
                        and self.TAG_TEMP not in item_tags):
                    text = self.app.tree_tags.item(child, "text")
                    result.append((child, text.lower()))
                walk(child)

        walk()
        return result

    @staticmethod
    def _first_prefix_match(nodes, needle):
        """Erster Knoten (iid), dessen Text mit `needle` beginnt — sonst None. Reine Funktion (testbar ohne Tk)."""
        for iid, text in nodes:
            if text.startswith(needle):
                return iid
        return None

    @staticmethod
    def _first_substring_match(nodes, needle):
        """Erster Knoten (iid), dessen Text `needle` enthält — sonst None. Reine Funktion (testbar ohne Tk)."""
        for iid, text in nodes:
            if needle in text:
                return iid
        return None

    # ==========================================
    # ZULETZT BENUTZTE TAGS
    # ==========================================
    def _lade_recent(self):
        """'Zuletzt benutzt' der offenen Sammlung (Daten-Ordner, siehe zuletzt_benutzt.py)."""
        return zuletzt_benutzt.lade(getattr(self.app, "master_folder", None), self.app.config)

    def add_recent_tags(self, tags_list):
        """Fügt neue Tags zur 'Zuletzt benutzt' Liste hinzu und speichert sie im Daten-Ordner der Sammlung."""
        if not tags_list: return
        recent = zuletzt_benutzt.vorne_einreihen(self._lade_recent(), tags_list)
        zuletzt_benutzt.speichere(getattr(self.app, "master_folder", None), recent)
        self.refresh_recent_tags_ui()

    def refresh_recent_tags_ui(self):
        """Aktualisiert den 'Zuletzt benutzt' Ordner im Treeview."""
        recent_node = getattr(self.app, 'recent_tags_node', None)
        if not recent_node or not self.app.tree_tags.exists(recent_node): return

        for child in self.app.tree_tags.get_children(recent_node):
            self.app.tree_tags.delete(child)

        for t in self._lade_recent():
            self.app.tree_tags.insert(recent_node, "end", text=t, tags=(self.TAG_BUNDLE, self.TAG_RECENT_ITEM))

    def remove_recent_tag(self, tag_text):
        """
        Entfernt einen einzelnen Eintrag aus der 'Zuletzt benutzt'-Historie (z.B. einen
        versehentlich gespeicherten Tippfehler-Tag) und aktualisiert Datei und UI.
        Betrifft nur den Verlauf — feste Tag-Vorlagen im Baum bleiben unberührt.
        :param tag_text: Der exakte Text des zu entfernenden Verlaufs-Eintrags.
        """
        recent = self._lade_recent()
        if tag_text in recent:
            recent.remove(tag_text)
            zuletzt_benutzt.speichere(getattr(self.app, "master_folder", None), recent)
            self.refresh_recent_tags_ui()
            # Der Neuaufbau der Verlaufs-Einträge verwirft deren active_tag-Markierung —
            # Hervorhebung für das aktuell angezeigte Dokument wiederherstellen.
            self.sync_tag_tree_selection()

    # ==========================================
    # SYNCHRONISATION & BAUM-UPDATE
    # ==========================================
    def sync_tag_tree_selection(self, event=None):
        """Synchronisiert die visuelle Hervorhebung im Tag-Baum mit dem Textfeld."""
        
        # 1. Temporäre Tags (und den Trennstrich) oben entfernen
        for child in self.app.tree_tags.get_children(""):
            item_tags = self.app.tree_tags.item(child, "tags")
            if self.TAG_TEMP in item_tags or self.TAG_SEP in item_tags:
                self.app.tree_tags.delete(child)

        # 2. Aktuelle Tags auslesen und als Set speichern (O(1) Performance-Boost)
        current_tags = self._get_current_tags()
        current_tags_lower = {t.lower() for t in current_tags}

        # 3. Alle existierenden Tags im Baum sammeln
        predefined_tags_lower = set()
        def collect_predefined(parent=""):
            """Sammelt rekursiv die Texte aller regulären (nicht 'Zuletzt benutzt') Baum-Einträge in ein Set, für den O(1)-Abgleich mit Freitext-Tags."""
            for child in self.app.tree_tags.get_children(parent):
                tags = self.app.tree_tags.item(child, "tags")
                if self.TAG_RECENT_ROOT not in tags and self.TAG_RECENT_ITEM not in tags:
                    predefined_tags_lower.add(self.app.tree_tags.item(child, "text").lower())
                collect_predefined(child)
        collect_predefined()

        # 4. Freitext-Tags (die nicht im Baum existieren) oben anpinnen
        unknown_tags = [t for t in current_tags if t.lower() not in predefined_tags_lower]
        if unknown_tags:
            for idx, t in enumerate(unknown_tags):
                self.app.tree_tags.insert("", idx, text=t, tags=(self.TAG_TEMP,))
            self.app.tree_tags.insert("", len(unknown_tags), text="──────────", tags=(self.TAG_SEP,))

        # 5. Rekursives Update der Markierungen (Blau hinterlegen)
        def update_nodes(parent=""):
            """Setzt/entfernt rekursiv das TAG_ACTIVE-Flag (blaue Hervorhebung) je nachdem, ob der Knotentext in den aktuell zugewiesenen Tags steckt."""
            for child in self.app.tree_tags.get_children(parent):
                item_tags = list(self.app.tree_tags.item(child, "tags"))

                if self.TAG_TEMP in item_tags or self.TAG_SEP in item_tags:
                    continue
                    
                if self.TAG_RECENT_ROOT in item_tags:
                    update_nodes(child)
                    continue

                # Schneller Check dank Set-Abfrage
                text_lower = self.app.tree_tags.item(child, "text").lower()
                is_active = text_lower in current_tags_lower

                if is_active and self.TAG_ACTIVE not in item_tags:
                    item_tags.append(self.TAG_ACTIVE)
                    self.app.tree_tags.item(child, tags=item_tags)
                elif not is_active and self.TAG_ACTIVE in item_tags:
                    item_tags.remove(self.TAG_ACTIVE)
                    self.app.tree_tags.item(child, tags=item_tags)

                update_nodes(child)

        update_nodes()

    # ==========================================
    # EVENTS (KLICK & LEERTASTE)
    # ==========================================
    def on_tag_double_click(self, event):
        """Wandelt im Zuweisungs-Modus einen Temp-Tag in ein festes Tag um oder schaltet ein reguläres Tag um; im Filter-Modus komplett blockiert."""
        if getattr(self.app, 'tag_mode_var', None) and self.app.tag_mode_var.get() == "filter":
            return "break" 

        if self.app.tree_tags.identify_element(event.x, event.y) == "indicator":
            return
            
        item_id = self.app.tree_tags.identify_row(event.y)
        if not item_id: return

        item_tags = self.app.tree_tags.item(item_id, "tags")
        if self.TAG_SEP in item_tags or self.TAG_RECENT_ROOT in item_tags:
            return "break"

        if self.TAG_TEMP in item_tags:
            self.app.root.after(10, lambda: self.app.tag_editor.save_temp_tag(item_id))
            return "break"

        self.app.root.after(10, lambda: self._toggle_tag(item_id))
        return "break"

    def on_space_toggle(self, event):
        """Schaltet das im Baum markierte Tag per Leertaste zu/ab (Tastatur-Äquivalent zum Doppelklick), im Filter-Modus deaktiviert."""
        if getattr(self.app, 'tag_mode_var', None) and self.app.tag_mode_var.get() == "filter":
            return "break"
            
        auswahl = self.app.tree_tags.selection()
        if auswahl:
            item_tags = self.app.tree_tags.item(auswahl[0], "tags")
            if self.TAG_SEP not in item_tags and self.TAG_RECENT_ROOT not in item_tags:
                self._toggle_tag(auswahl[0])
        return "break"

    # ==========================================
    # KERN-LOGIK: TAG HINZUFÜGEN / ENTFERNEN
    # ==========================================
    def _toggle_tag(self, item_id):
        """Schaltet einen Tag ein oder aus und zieht automatisch alle übergeordneten Kategorien nach."""
        if getattr(self.app, 'tag_mode_var', None) and self.app.tag_mode_var.get() == "filter":
            return 

        item_tags = self.app.tree_tags.item(item_id, "tags")
        nicht_zuweisbar = self.TAG_STRUCTURAL in item_tags or self.TAG_SYNONYM in item_tags

        auswahl = self.app.tree_files.selection()
        if not auswahl:
            if not nicht_zuweisbar:
                self.sync_tag_tree_selection()
            return

        tag_text = self.app.tree_tags.item(item_id, "text")
        if nicht_zuweisbar:
            # Kategorien und Synonyme werden nie zugewiesen. Trägt das Dokument den Text aber
            # noch (Altbestand, oder das Tag wurde erst nachträglich zum Synonym erklärt), darf
            # der Doppelklick ihn ENTFERNEN (Nutzerfund 08.09.2026: "Haftpflichtversicherung"
            # ließ sich nach dem Umschalten nicht mehr vom Dokument nehmen). Nur bei EINEM
            # markierten Dokument - die Mehrfach-Logik würde es sonst überall hinzufügen.
            if len(auswahl) > 1 or tag_text not in self._get_current_tags():
                return
        elif len(auswahl) > 1:
            self._toggle_tag_mehrfach(item_id, auswahl)
            return

        current_tags = self._get_current_tags()
            
        if tag_text in current_tags:
            current_tags.remove(tag_text)
        else:
            # Auto-Hierarchie: Wenn Unterkategorie markiert wird, Hauptkategorien mitnehmen
            ancestors = []
            parent_id = self.app.tree_tags.parent(item_id)
            while parent_id:
                parent_tags = self.app.tree_tags.item(parent_id, "tags")
                if self.TAG_STRUCTURAL not in parent_tags and self.TAG_SYNONYM not in parent_tags:
                    parent_text = self.app.tree_tags.item(parent_id, "text")
                    if parent_text not in current_tags:
                        ancestors.insert(0, parent_text) 
                parent_id = self.app.tree_tags.parent(parent_id)
            
            current_tags.extend(ancestors)
            current_tags.append(tag_text)
            
        # Textfeld überschreiben
        self.app.entry_tags.delete("1.0", tk.END)
        if current_tags:
            self.app.entry_tags.insert("1.0", ", ".join(current_tags))
            
        self.sync_tag_tree_selection()
        self.app.save_manager.trigger_autosave()

    def _oberkategorien(self, item_id):
        """Zuweisbare Elternknoten eines Tags, von oben nach unten (Auto-Hierarchie)."""
        ancestors = []
        parent_id = self.app.tree_tags.parent(item_id)
        while parent_id:
            eltern_tags = self.app.tree_tags.item(parent_id, "tags")
            if self.TAG_STRUCTURAL not in eltern_tags and self.TAG_SYNONYM not in eltern_tags:
                ancestors.insert(0, self.app.tree_tags.item(parent_id, "text"))
            parent_id = self.app.tree_tags.parent(parent_id)
        return ancestors

    def _toggle_tag_mehrfach(self, item_id, auswahl):
        """
        Ein Tag für MEHRERE markierte Dokumente auf einmal (Nutzerwunsch 01.09.2026:
        Dokumente markieren, Tag doppelklicken). Jedes Dokument behält dabei seine
        eigenen übrigen Tags — deshalb läuft das NICHT über das Tags-Eingabefeld
        (das zeigt nur das primär markierte Dokument), sondern pro Datei über die
        Metadaten (save_manager.ergaenze_tags_fuer_auswahl).

        Richtung wie bei einem Kontrollkästchen mit gemischtem Zustand: Tragen ALLE
        markierten Dokumente das Tag bereits, wird es entfernt; sonst wird es überall
        ergänzt (Oberkategorien kommen beim Ergänzen automatisch mit, beim Entfernen
        bewusst nicht — die gelten meist auch für andere Tags des Dokuments).
        """
        tag_text = self.app.tree_tags.item(item_id, "text")
        alle_haben_es = True
        for item in auswahl:
            werte = self.app.tree_files.item(item, "values")
            vorhandene = {t.strip().lower() for t in str(werte[2]).split(",") if t.strip() and t.strip() != "---"}
            if tag_text.lower() not in vorhandene:
                alle_haben_es = False
                break

        if alle_haben_es:
            anzahl = self.app.save_manager.ergaenze_tags_fuer_auswahl([tag_text], entfernen=True)
            aktion = "entfernt von"
        else:
            anzahl = self.app.save_manager.ergaenze_tags_fuer_auswahl(
                self._oberkategorien(item_id) + [tag_text])
            aktion = "vergeben für"
        self.app.logger.info(f"Tag '{tag_text}' {aktion} {anzahl} Dokument(e) (Mehrfachauswahl).")