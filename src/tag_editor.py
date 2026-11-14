import json
import logging
import os
import tkinter as tk
from tkinter import messagebox, ttk, font as tkfont
import bestaetigung

import app_paths
import sicher_speichern
import tag_ignorierliste
# --- NEU: Wir holen uns die Konstanten aus dem TagManager ---
from tag_manager import TagManager
from ui_utils import UIUtils

_log = logging.getLogger("DocManager")

# Bis 08.11.2026 hieß die Sammelkategorie für neue Tags „Neu (KI)“. Seit Etappe 6 vergibt die KI keine Tags mehr, neue
# kommen nur von Hand - der Name wird beim Laden umgestellt (migriere_neu_kategorie).
ALTER_NAME_NEU = "Neu (KI)"


def migriere_neu_kategorie(daten, neuer_name=TagManager.KATEGORIE_NEU):
    """
    Benennt die oberste Kategorie „Neu (KI)“ im geladenen Katalog in `neuer_name` um. Gibt es diese schon, wandern die
    Tags dorthin, ohne Doppelte (Groß/Klein egal). Reine Funktion auf der JSON-Struktur, liefert eine neue Liste.
    """
    if not isinstance(daten, list):
        return daten

    def name(knoten):
        return str(knoten.get("text", "")).strip().lower() if isinstance(knoten, dict) else ""

    if not any(name(k) == ALTER_NAME_NEU.lower() for k in daten):
        return daten
    ziel = next((dict(k, children=list(k.get("children") or [])) for k in daten if name(k) == neuer_name.lower()), None)
    ergebnis, ziel_eingefuegt = [], False
    for knoten in daten:
        if name(knoten) in (ALTER_NAME_NEU.lower(), neuer_name.lower()):
            if ziel is None:
                ziel = dict(knoten, text=neuer_name, children=[])
            vorhanden = {name(c) for c in ziel["children"]}
            if knoten is not ziel and name(knoten) == ALTER_NAME_NEU.lower():
                for kind in knoten.get("children") or []:
                    if name(kind) not in vorhanden:
                        ziel["children"].append(kind)
                        vorhanden.add(name(kind))
            if not ziel_eingefuegt:
                ergebnis.append(ziel)
                ziel_eingefuegt = True
            continue
        ergebnis.append(knoten)
    return ergebnis


class TagEditor:
    def __init__(self, app):
        self.app = app
        # Der Tag-Katalog gehört zur Dokumentensammlung und liegt im KID-Daten-Ordner;
        # ohne gewählten Hauptordner Fallback ins Arbeitsverzeichnis (wie früher).
        # Bei einem Hauptordner-Wechsel setzt folder_manager.choose_master_folder
        # diesen Pfad neu und lädt den Katalog der neuen Sammlung.
        self.tags_file = app_paths.tags_path(app.master_folder)
        self.setup_context_menu()
        self.clipboard_tag = None

    def _is_protected_node(self, tags):
        """
        Hilfsmethode: Prüft, ob es sich um einen System-Eintrag handelt, der nicht editiert werden darf.
        (z.B. Temp-Tags, Trennlinien oder der 'Zuletzt benutzt' Ordner).
        """
        if not tags: return False
        protected = {TagManager.TAG_TEMP, TagManager.TAG_SEP, TagManager.TAG_RECENT_ROOT, TagManager.TAG_RECENT_ITEM}
        # Prüft superschnell (via Mengen-Schnittmenge), ob eines der geschützten Tags vorhanden ist
        return bool(protected.intersection(tags))

    def _item_tags(self, iid):
        """Item-Tags immer als Liste - Tkinter liefert ein einzelnes Tag als nackten String (FALLSTRICKE #9)."""
        tags = self.app.tree_tags.item(iid, "tags")
        return [tags] if isinstance(tags, str) else list(tags)

    def setup_context_menu(self):
        self.menu = tk.Menu(self.app.root, tearoff=0)
        self.menu.add_command(label="Neues Tag...", command=self.add_tag)
        self.menu.add_command(label="Umbenennen (F2)", command=self.rename_tag)
        self.menu.add_command(label="Duplizieren", command=self.duplicate_tag)
        self.menu.add_separator()
        self.menu.add_command(label="Als Struktur/Kategorie umschalten", command=self.toggle_structural)
        self.menu.add_command(label="Als Synonym umschalten (steht für das Tag darüber)", command=self.toggle_synonym)
        self.menu.add_separator()
        self.menu.add_command(label="Ausschneiden (Strg+X)", command=self.cut_tag)
        self.menu.add_command(label="Einfügen (Strg+V)", command=self.paste_tag)
        self.menu.add_separator()
        self.menu.add_command(label="Nach oben verschieben (Alt+Hoch)", command=self.move_tag_up)
        self.menu.add_command(label="Nach unten verschieben (Alt+Runter)", command=self.move_tag_down)
        self.menu.add_command(label="Unter-Tags alphabetisch sortieren", command=self.sortiere_kinder)
        self.menu.add_separator()
        self.menu.add_command(label="Alle aufklappen", command=self.expand_all)
        self.menu.add_command(label="Alle zuklappen", command=self.collapse_all)
        self.menu.add_separator()
        self.menu.add_command(label="Wegräumen && für KI ignorieren (Strg+I)", command=self.ignoriere_tag)
        self.menu.add_command(label="Löschen (Entf)", command=self.delete_tag)

        self.temp_menu = tk.Menu(self.app.root, tearoff=0)
        self.temp_menu.add_command(label="Als feste Vorlage speichern", command=self.save_temp_tag)

        self.recent_menu = tk.Menu(self.app.root, tearoff=0)
        self.recent_menu.add_command(label="Aus Verlauf entfernen", command=self.remove_recent_entry)

    def show_menu(self, event):
        """Zeigt je nach angeklicktem Knoten das passende Kontextmenü: Vollmenü für reguläre Tags, Kurzmenü für Temp-Tags und Verlaufs-Einträge, gar keins für Trennlinie und den Verlaufs-Ordner selbst."""
        iid = self.app.tree_tags.identify_row(event.y)
        if not iid:
            self.app.tree_tags.selection_remove(self.app.tree_tags.selection())
            state = tk.NORMAL if self.clipboard_tag and self.app.tree_tags.exists(self.clipboard_tag) else tk.DISABLED
            self.menu.entryconfig("Einfügen (Strg+V)", state=state)
            self.menu.tk_popup(event.x_root, event.y_root)
            return

        tags = self.app.tree_tags.item(iid, "tags")

        # Trennlinie und der Verlaufs-Ordner selbst bekommen kein Kontextmenü
        if TagManager.TAG_SEP in tags or TagManager.TAG_RECENT_ROOT in tags:
            return

        # Verlaufs-Einträge bekommen ein eigenes Kurzmenü (nur "Aus Verlauf entfernen")
        if TagManager.TAG_RECENT_ITEM in tags:
            self.app.tree_tags.selection_set(iid)
            self.recent_menu.tk_popup(event.x_root, event.y_root)
            return

        self.app.tree_tags.selection_set(iid)

        if TagManager.TAG_TEMP in tags:
            self.temp_menu.tk_popup(event.x_root, event.y_root)
        else:
            state = tk.NORMAL if self.clipboard_tag and self.app.tree_tags.exists(self.clipboard_tag) else tk.DISABLED
            self.menu.entryconfig("Einfügen (Strg+V)", state=state)
            self.menu.tk_popup(event.x_root, event.y_root)

    def toggle_structural(self):
        """Schaltet das ausgewählte Tag zwischen normalem (zuweisbarem) Tag und reiner Struktur-Kategorie (grau, nicht zuweisbar) um."""
        auswahl = self.app.tree_tags.selection()
        if not auswahl: return
        iid = auswahl[0]
        
        tags = self._item_tags(iid)
        if self._is_protected_node(tags): return

        if TagManager.TAG_STRUCTURAL in tags:
            tags.remove(TagManager.TAG_STRUCTURAL)
        else:
            tags.append(TagManager.TAG_STRUCTURAL)
            if TagManager.TAG_SYNONYM in tags:
                tags.remove(TagManager.TAG_SYNONYM)  # entweder Kategorie oder Synonym

        self.app.tree_tags.item(iid, tags=tags)
        self.save_tags()

    def toggle_synonym(self):
        """
        Schaltet das ausgewählte Tag zwischen normalem Tag und Synonym-Knoten um (Nutzeridee
        08.09.2026, Gegenstück zu den Ordner-Aliasen): Ein Synonym steht für das Tag darüber -
        liest die KI 'Haftpflichtversicherung', bekommt das Dokument 'Haftpflicht', der
        Synonym-Text selbst wird nie zugewiesen (tag_manager.get_synonyme). Braucht deshalb
        einen Elternknoten und darf selbst keine Unter-Tags haben.
        """
        auswahl = self.app.tree_tags.selection()
        if not auswahl: return
        iid = auswahl[0]
        tags = self._item_tags(iid)
        if self._is_protected_node(tags): return

        if TagManager.TAG_SYNONYM in tags:
            tags.remove(TagManager.TAG_SYNONYM)
        else:
            if not self.app.tree_tags.parent(iid):
                messagebox.showinfo("Synonym", "Ein Synonym braucht ein Tag darüber, für das es steht -\n"
                                    "auf der obersten Ebene geht das nicht.")
                return
            if self.app.tree_tags.get_children(iid):
                messagebox.showinfo("Synonym", "Ein Synonym kann keine Unter-Tags haben.\n"
                                    "Bitte zuerst die Unter-Tags verschieben oder löschen.")
                return
            tags.append(TagManager.TAG_SYNONYM)
            if TagManager.TAG_STRUCTURAL in tags:
                tags.remove(TagManager.TAG_STRUCTURAL)

        self.app.tree_tags.item(iid, tags=tags)
        self.save_tags()
        self.app.tag_manager.sync_tag_tree_selection()

    def expand_all(self):
        self._set_tree_state("", True)

    def collapse_all(self):
        self._set_tree_state("", False)

    def _set_tree_state(self, parent, is_open):
        for child in self.app.tree_tags.get_children(parent):
            self.app.tree_tags.item(child, open=is_open)
            self._set_tree_state(child, is_open) 

    def remove_recent_entry(self):
        """Entfernt den ausgewählten Eintrag aus dem 'Zuletzt benutzt'-Verlauf (Logik liegt im TagManager)."""
        auswahl = self.app.tree_tags.selection()
        if not auswahl: return
        tag_text = self.app.tree_tags.item(auswahl[0], "text")
        self.app.tag_manager.remove_recent_tag(tag_text)

    def save_temp_tag(self, item_id=None):
        """Übernimmt ein nur im Textfeld existierendes Freitext-Tag als feste Vorlage in den Baum und speichert die Struktur."""
        if not item_id:
            auswahl = self.app.tree_tags.selection()
            if not auswahl: return
            item_id = auswahl[0]
            
        text = self.app.tree_tags.item(item_id, "text")
        self.app.tree_tags.insert("", "end", text=text, tags=(TagManager.TAG_BUNDLE,))
        
        self.save_tags()
        self.app.tag_manager.sync_tag_tree_selection()

    def add_tag(self):
        """Fragt einen Namen ab und fügt ein neues Tag ein (als Unter-Tag der Auswahl, sonst als Haupt-Tag); verhindert Duplikate auf derselben Ebene."""
        auswahl = self.app.tree_tags.selection()
        if auswahl:
            parent = auswahl[0]
            if TagManager.TAG_SYNONYM in self._item_tags(parent):
                messagebox.showwarning("Hinweis", "Unter einem Synonym kann kein Tag liegen - "
                                       "bitte das Tag darüber auswählen.")
                return
            prompt = f"Name für das Unter-Tag in '{self.app.tree_tags.item(parent, 'text')}':"
        else:
            parent = ""  
            prompt = "Name für das neue Haupt-Tag:"
            
        name = UIUtils.ask_string("Neues Tag", prompt)
        if name and name.strip():
            existing = [self.app.tree_tags.item(c, "text").lower() for c in self.app.tree_tags.get_children(parent)]
            if name.lower() in existing:
                messagebox.showwarning("Hinweis", "Ein Tag mit diesem Namen existiert hier bereits!")
                return
                
            self.app.tree_tags.insert(parent, "end", text=name, tags=(TagManager.TAG_BUNDLE,), open=True)
            self.save_tags()

    def rename_tag(self, event=None):
        """Benennt das ausgewählte Tag um (System-Knoten sind über _is_protected_node geschützt)."""
        auswahl = self.app.tree_tags.selection()
        if not auswahl: return

        iid = auswahl[0]
        tags = self.app.tree_tags.item(iid, "tags")
        if self._is_protected_node(tags): return

        alter_text = self.app.tree_tags.item(iid, "text")
        neuer_text = UIUtils.ask_string("Umbenennen", "Neuer Name für das Tag:", initialvalue=alter_text)
        
        if neuer_text and neuer_text.strip() and neuer_text != alter_text:
            self.app.tree_tags.item(iid, text=neuer_text.strip())
            self.save_tags()
            self.app.tag_manager.sync_tag_tree_selection()

    def duplicate_tag(self):
        """Legt auf derselben Ebene eine Kopie des ausgewählten Tags an (Vorschlagsname '<Original> (Kopie)')."""
        auswahl = self.app.tree_tags.selection()
        if not auswahl: return
        
        iid = auswahl[0]
        tags = self.app.tree_tags.item(iid, "tags")
        if self._is_protected_node(tags): return
        
        text = self.app.tree_tags.item(iid, "text")
        parent = self.app.tree_tags.parent(iid)
        
        new_name = UIUtils.ask_string("Duplizieren", "Neuer Name für die Kopie:", initialvalue=f"{text} (Kopie)")
        if new_name:
            self.app.tree_tags.insert(parent, "end", text=new_name, tags=(TagManager.TAG_BUNDLE,))
            self.save_tags()

    def ignoriere_tag(self, event=None):
        """
        Rechtsklick/Strg+I im Tag-Baum (Nutzerwunsch 03.09.2026): das Tag KOMPLETT
        wegräumen - derselbe Weg wie im Tag-Hygiene-Tool, nur für ein einzelnes Tag:
        aus den PDF-Metadaten aller betroffenen Dokumente löschen (Titel und übrige
        Tags bleiben), aus dem Katalog nehmen und auf die KI-Ignorierliste setzen
        (Nutzer-Klarstellung 03.09.2026: nur ignorieren, aber im Katalog stehen
        lassen, verwirrt - halbe Sachen macht das hier bewusst nicht).
        Rückgängig: Ignorierliste über Tag-Hygiene → 'Ignorierliste…' bearbeiten.
        """
        # Bewusster Griff ins Tool-Modul: die Entfernen-Logik wohnt bei der Tag-Hygiene
        # und soll nur EINMAL existieren (kein Import-Ringschluss: tag_hygiene kennt
        # tag_editor nicht).
        from tools import tag_hygiene

        auswahl = self.app.tree_tags.selection()
        if not auswahl:
            return
        iid = auswahl[0]
        # Einzelnes Item-Tag kommt als nackter String statt Tuple (FALLSTRICKE) -
        # sonst prüfte _is_protected_node Buchstaben statt Tag-Namen.
        item_tags = self.app.tree_tags.item(iid, "tags")
        if self._is_protected_node((item_tags,) if isinstance(item_tags, str) else item_tags):
            return
        text = self.app.tree_tags.item(iid, "text").strip()
        if not text:
            return
        if self.app.tree_tags.get_children(iid):
            messagebox.showwarning(
                "Tag ignorieren",
                f"'{text}' hat Unter-Tags und wird deshalb nicht angefasst.\n"
                "Bitte zuerst die Unter-Tags verschieben oder einzeln aufräumen.")
            return

        vorkommen = tag_hygiene.sammle_tag_vorkommen(
            self.app.master_folder,
            lambda pfad: app_paths.is_trash_path(pfad, self.app.master_folder))
        pfade = next((p for t, p in vorkommen.items() if t.lower() == text.lower()), [])
        if not bestaetigung.frage(
                "Tag ignorieren",
                f"'{text}' komplett entfernen?\n\n"
                f"- wird aus {len(pfade)} Dokument(en) gelöscht (Titel und übrige Tags bleiben)\n"
                "- verschwindet aus dem Tag-Katalog\n"
                "- die KI schlägt es nie mehr vor (Ignorierliste)"):
            return

        self.app.is_saving = True
        try:
            geaendert = tag_hygiene.entferne_tag_aus_dokumenten(
                self.app.master_folder, text, pfade, getattr(self.app, "logger", None))
        finally:
            self.app.is_saving = False
        tag_ignorierliste.ergaenze(self.app.master_folder, text)
        self.app.tree_tags.delete(iid)
        self.save_tags()
        self.app.tag_manager.sync_tag_tree_selection()
        if hasattr(self.app, "folder_manager"):
            self.app.folder_manager.on_folder_select(None)
        messagebox.showinfo(
            "Tag ignorieren",
            f"'{text}' entfernt ({geaendert} Dokument(e) geändert) und auf die Ignorierliste gesetzt.\n"
            "Rückgängig machen: Tools → Tag-Hygiene → 'Ignorierliste…'.")

    def delete_tag(self, event=None):
        """Löscht das ausgewählte Tag samt aller Unter-Tags nach Sicherheitsabfrage (System-Knoten geschützt)."""
        auswahl = self.app.tree_tags.selection()
        if not auswahl: return
        
        iid = auswahl[0]
        tags = self.app.tree_tags.item(iid, "tags")
        if self._is_protected_node(tags): return
        
        text = self.app.tree_tags.item(iid, "text")
        # Kategorien (graue Struktur-Knoten) und Tags MIT Unter-Tags fragen IMMER nach - auch
        # bei abgeschalteten Sicherheitsabfragen (Nutzerentscheidung 07.09.2026): ein Fehlgriff
        # auf "Versicherung" risse den ganzen Ast mit. Nur ein Blatt-Tag geht ohne Rückfrage.
        if TagManager.TAG_STRUCTURAL in tags or self.app.tree_tags.get_children(iid):
            frage = lambda titel, text_: messagebox.askyesno(titel, text_)  # noqa: E731
        else:
            frage = bestaetigung.frage
        if frage("Löschen", f"Soll das Tag '{text}' und alle darin enthaltenen Unter-Tags wirklich gelöscht werden?"):
            self.app.tree_tags.delete(iid)
            self.save_tags()
            self.app.tag_manager.sync_tag_tree_selection()

    def load_tags(self):
        """Baut den Tag-Baum aus tags.json neu auf (mit 'Zuletzt benutzt'-Systemknoten als erstem Eintrag); fällt bei fehlender oder beschädigter Datei auf _create_default_tags zurück."""
        self.app.tree_tags.tag_configure(TagManager.TAG_STRUCTURAL, foreground="#a0a0a0")
        # Synonyme blau-grau und kursiv: "steht für das Tag darüber", nie selbst zuweisbar.
        # Schrift aus dem Baum-Style ableiten, damit die Größe bei Skalierung stimmt.
        try:
            self._synonym_font = tkfont.Font(font=ttk.Style().lookup("Tags.Treeview", "font") or "TkDefaultFont")
            self._synonym_font.configure(slant="italic")
            self.app.tree_tags.tag_configure(TagManager.TAG_SYNONYM, foreground="#5b7fa6", font=self._synonym_font)
        except Exception:
            self.app.tree_tags.tag_configure(TagManager.TAG_SYNONYM, foreground="#5b7fa6")
        
        for child in self.app.tree_tags.get_children(""):
            self.app.tree_tags.delete(child)

        # Zuletzt benutzt Knoten immer als Erstes generieren
        self.app.recent_tags_node = self.app.tree_tags.insert("", "end", text="⏱️ Zuletzt benutzt", tags=(TagManager.TAG_RECENT_ROOT, TagManager.TAG_STRUCTURAL), open=True)

        data = self._lade_katalog()
        if data is None:
            self._create_default_tags()
        else:
            try:
                self._insert_nodes("", migriere_neu_kategorie(data))
                self.save_tags()
            except Exception as e:
                _log.error(f"Fehler beim Laden der {self.tags_file}: {e}")
                self._create_default_tags()
            
        # Nach dem Aufbau des Baums die Historie laden
        if hasattr(self.app, 'tag_manager'):
            self.app.tag_manager.refresh_recent_tags_ui()

    def _lade_katalog(self):
        """Der gespeicherte Katalog, sonst seine Sicherung, sonst None. Eine beschädigte Datei legt lade_json beiseite: Sie wird
        also nicht mehr über die gute .bak kopiert, was den Katalog früher endgültig zerstörte (FALLSTRICKE #115)."""
        for pfad in (self.tags_file, self.tags_file + ".bak"):
            try:
                data = sicher_speichern.lade_json(pfad)
            except FileNotFoundError:
                continue
            except (OSError, ValueError) as e:
                _log.error(f"Tag-Katalog {os.path.basename(pfad)} nicht lesbar: {e}")
                continue
            if isinstance(data, list):
                return data
        return None

    def _create_default_tags(self):
        """
        Legt die Start-Tag-Struktur an, falls noch keine tags.json existiert.
        Quelle ist die konfigurierbare tags_default.json (gleiches Muster wie
        folder_default.json); fehlt auch diese oder ist sie beschädigt, wird
        eine kleine eingebaute Beispiel-Struktur verwendet und als
        tags_default.json abgelegt, damit sie ab dann anpassbar ist.
        """
        fallback_tags = [
            {
                "text": "Dokument",
                "is_structural": True,
                "children": [{"text": "Angebot", "children": []}, {"text": "Rechnung", "children": []}]
            }
        ]

        defaults_file = "tags_default.json"
        default_tags = fallback_tags
        # Mitgelieferte Vorlage (auch aus der gepackten EXE) hat Vorrang vor dem Notfall-Katalog
        app_paths.ensure_default_file(defaults_file, getattr(self.app, "logger", None))
        if os.path.exists(defaults_file):
            try:
                with open(defaults_file, "r", encoding="utf-8") as f:
                    default_tags = json.load(f)
            except Exception as e:
                if hasattr(self.app, 'logger'):
                    self.app.logger.error(f"Fehler beim Laden der {defaults_file}: {e} — verwende eingebaute Standard-Tags.")
        else:
            try:
                sicher_speichern.schreibe_json(defaults_file, fallback_tags, indent=4, ensure_ascii=False)
                if hasattr(self.app, 'logger'):
                    self.app.logger.info(f"Standard-Konfiguration '{defaults_file}' wurde neu erstellt.")
            except Exception as e:
                if hasattr(self.app, 'logger'):
                    self.app.logger.error(f"Konnte '{defaults_file}' nicht erstellen: {e}")

        self._insert_nodes("", default_tags)
        self.save_tags()
        
    def _insert_nodes(self, parent, nodes):
        """Fügt rekursiv Tag-Dictionaries (aus der JSON-Struktur) in den Baum ein, überspringt dabei Namensduplikate auf derselben Ebene."""
        existing_texts = [self.app.tree_tags.item(c, "text").lower() for c in self.app.tree_tags.get_children(parent)]
        for node in nodes:
            node_text = node["text"]
            if node_text.lower() not in existing_texts:
                tags = (TagManager.TAG_BUNDLE,)
                if node.get("is_synonym", False):
                    tags += (TagManager.TAG_SYNONYM,)
                elif node.get("is_structural", False):
                    tags += (TagManager.TAG_STRUCTURAL,)
                
                new_item = self.app.tree_tags.insert(parent, "end", text=node_text, tags=tags, open=False)
                existing_texts.append(node_text.lower())
                if "children" in node and node["children"]:
                    self._insert_nodes(new_item, node["children"])

    def save_tags(self):
        """
        Liest den aktuellen Baum aus (ohne System-Knoten) und schreibt ihn nach tags.json.
        Sicherheitsgurt: Die vorherige Fassung wird vor dem Überschreiben als
        tags.json.bak aufgehoben — der Tag-Katalog ist die einzige Datei, die
        nirgendwo sonst rekonstruierbar gespeichert ist (Lehre aus FALLSTRICKE #20).
        Ohne Änderung wird nichts geschrieben: Sonst wäre die .bak nach jedem Start nur dieselbe Fassung.
        """
        data = self._get_nodes("")
        try:
            if self._katalog_unveraendert(data):
                return
            if os.path.exists(self.tags_file):
                sicher_speichern.sichere_kopie(self.tags_file, self.tags_file + ".bak")
            sicher_speichern.schreibe_json(self.tags_file, data, indent=4, ensure_ascii=False)
        except Exception as e:
            _log.error(f"Fehler beim Speichern der {self.tags_file}: {e}")

    def _katalog_unveraendert(self, data):
        """Steht genau dieser Katalog schon in der Datei?"""
        try:
            with open(self.tags_file, encoding="utf-8") as f:
                return json.load(f) == data
        except (OSError, ValueError):
            return False

    def _get_nodes(self, parent):
        """Wandelt den Treeview rekursiv in eine JSON-taugliche Liste von Dictionaries um; System-Knoten (z.B. 'Zuletzt benutzt') werden dabei ausgeschlossen."""
        nodes = []
        for child in self.app.tree_tags.get_children(parent):
            tags = self.app.tree_tags.item(child, "tags")
            
            # System-Ordner ausblenden, damit sie nicht versehentlich in tags.json landen
            if self._is_protected_node(tags):
                continue
                
            text = self.app.tree_tags.item(child, "text")
            children = self._get_nodes(child)
            
            node_data = {"text": text, "children": children}
            if TagManager.TAG_STRUCTURAL in tags:
                node_data["is_structural"] = True
            if TagManager.TAG_SYNONYM in tags:
                node_data["is_synonym"] = True
                
            nodes.append(node_data)
        return nodes
    
    def cut_tag(self, event=None):
        """Merkt sich das ausgewählte Tag für einen nachfolgenden paste_tag-Aufruf (kein sofortiges Verschieben)."""
        auswahl = self.app.tree_tags.selection()
        if not auswahl: return
        tags = self.app.tree_tags.item(auswahl[0], "tags")
        if self._is_protected_node(tags): return

        self.clipboard_tag = auswahl[0]
        if hasattr(self.app, 'logger'):
            self.app.logger.info(f"Tag in Zwischenablage: {self.app.tree_tags.item(self.clipboard_tag, 'text')}")

    def paste_tag(self, event=None):
        """Verschiebt das mit cut_tag gemerkte Tag an die aktuelle Position; verhindert das Einfügen in System-Ordner sowie in sich selbst/eigene Kinder (Zyklus-Check)."""
        if not self.clipboard_tag or not self.app.tree_tags.exists(self.clipboard_tag): return
            
        auswahl = self.app.tree_tags.selection()
        target_parent = auswahl[0] if auswahl else ""
        
        # Verbietet das Einfügen in die Historie
        if target_parent:
            t_tags = self.app.tree_tags.item(target_parent, "tags")
            if self._is_protected_node(t_tags):
                messagebox.showwarning("Hinweis", "In diesen System-Ordner kann nichts eingefügt werden.")
                return
            if TagManager.TAG_SYNONYM in t_tags:
                messagebox.showwarning("Hinweis", "Unter einem Synonym kann nichts liegen - "
                                       "bitte das Tag darüber auswählen.")
                return

        curr = target_parent
        while curr:
            if curr == self.clipboard_tag:
                messagebox.showwarning("Fehler", "Ein Tag kann nicht in sich selbst eingefügt werden!")
                return
            curr = self.app.tree_tags.parent(curr)

        self.app.tree_tags.move(self.clipboard_tag, target_parent, "end")
        if target_parent:
            self.app.tree_tags.item(target_parent, open=True) 
            
        self.save_tags()
        self.clipboard_tag = None 

    # Für die Sortierung: Umlaute einreihen wie ihre Grundbuchstaben ('Ärzte' bei A,
    # 'Österreich' bei O), sonst landeten sie hinter Z.
    _SORTIER_MAP = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "ß": "s"})

    def sortiere_kinder(self, event=None):
        """
        Sortiert die direkten Unter-Tags des ausgewählten Knotens alphabetisch
        (Nutzerwunsch 03.09.2026); ohne Auswahl die oberste Ebene. Systemknoten
        ('Zuletzt benutzt', Trennlinie, Temp-Tags) bleiben unangetastet vorn stehen.
        Bewusst nur EINE Ebene - tiefer sortiert man gezielt den jeweiligen Knoten.
        Mit Rückfrage, weil die handverschobene Reihenfolge (Alt+Hoch/Runter) verloren geht.
        """
        def item_tags(iid):
            # Einzelnes Item-Tag kommt als nackter String statt Tuple (FALLSTRICKE)
            tags = self.app.tree_tags.item(iid, "tags")
            return (tags,) if isinstance(tags, str) else tags

        auswahl = self.app.tree_tags.selection()
        parent = auswahl[0] if auswahl else ""
        if parent and self._is_protected_node(item_tags(parent)):
            return
        kinder = [c for c in self.app.tree_tags.get_children(parent)
                  if not self._is_protected_node(item_tags(c))]
        if len(kinder) < 2:
            return
        wo = f"in '{self.app.tree_tags.item(parent, 'text')}'" if parent else "auf der obersten Ebene"
        if not bestaetigung.frage(
                "Sortieren", f"Die {len(kinder)} Tags {wo} alphabetisch sortieren?\n"
                "Die bisherige Reihenfolge geht dabei verloren."):
            return
        sortiert = sorted(kinder, key=lambda c: self.app.tree_tags.item(c, "text").lower()
                          .translate(self._SORTIER_MAP))
        # Systemknoten (oben) behalten ihre Plätze: die sortierbaren wandern dahinter ans Ende
        for kind in sortiert:
            self.app.tree_tags.move(kind, parent, "end")
        self.save_tags()

    def move_tag_up(self, event=None):
        """Verschiebt das ausgewählte Tag eine Position nach oben; auf oberster Ebene darf nichts über den 'Zuletzt benutzt'-Knoten (Index 0) hinweg verschoben werden."""
        auswahl = self.app.tree_tags.selection()
        if not auswahl: return
        item = auswahl[0]
        tags = self.app.tree_tags.item(item, "tags")
        if self._is_protected_node(tags): return "break"

        parent = self.app.tree_tags.parent(item)
        idx = self.app.tree_tags.index(item) 
        
        # --- FIX: Verhindern, dass Tags über "Zuletzt benutzt" verschoben werden ---
        min_idx = 1 if not parent else 0
        
        if idx > min_idx:
            self.app.tree_tags.move(item, parent, idx - 1)
            self.save_tags()
        return "break"

    def move_tag_down(self, event=None):
        """Verschiebt das ausgewählte Tag eine Position nach unten (innerhalb derselben Ebene/Elternknoten)."""
        auswahl = self.app.tree_tags.selection()
        if not auswahl: return
        item = auswahl[0]
        tags = self.app.tree_tags.item(item, "tags")
        if self._is_protected_node(tags): return "break"
        
        parent = self.app.tree_tags.parent(item)
        idx = self.app.tree_tags.index(item)
        children = self.app.tree_tags.get_children(parent)
        
        if idx < len(children) - 1:
            self.app.tree_tags.move(item, parent, idx + 1)
            self.save_tags()
        return "break"