import os
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox
import bestaetigung

import ollama_client
from pdf_handler import PDFHandler
from tag_manager import TagManager
from tools.base_tool import BaseTool, ToolContext
from tools.title_cleanup import CandidatePickerDialog
from ui_utils import UIUtils

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

# Reicht für ein multimodales Modell zur Layout-/Text-Erkennung, hält den
# base64-Payload zum Ollama-Server aber noch in vertretbarer Größe.
RENDER_DPI = 150


def current_title_or_filename(path, meta):
    """Der Titel, wie er dem Nutzer heute angezeigt wird: echter Metadaten-Titel oder ersatzweise der Dateiname."""
    title = (meta or {}).get("title", "")
    return title if title else os.path.splitext(os.path.basename(path))[0]


def katalog_vorschlaege(vorschlaege, known_tags, vorhandene_csv=""):
    """
    Etappe 6 (Peter 07.11.2026, FALLSTRICKE #120): Die KI schlägt nur Tags aus dem Katalog vor, in dessen Schreibweise, und
    nichts, was das Dokument schon trägt. Früher kamen ihre Tags samt neuer Begriffe gleich ins Tag-Feld (merge_tags) und
    wurden mit dem Titel geschrieben; jetzt schreibt nur, was der Nutzer im Tag-Dialog anklickt. Reine Funktion.
    """
    katalog = {str(t).lower(): t for t in known_tags or []}
    schon = {t.strip().lower() for t in str(vorhandene_csv or "").split(",") if t.strip()}
    ergebnis = []
    for tag in vorschlaege or []:
        treffer = katalog.get(str(tag).strip().lower())
        if treffer and treffer.lower() not in schon and treffer not in ergebnis:
            ergebnis.append(treffer)
    return ergebnis


def vorschlag_hinweis(anzahl):
    """Text hinter den Tags in der Liste, solange KI-Vorschläge zum Anklicken bereitliegen."""
    if not anzahl:
        return ""
    return f"  [+{anzahl} {'Vorschlag' if anzahl == 1 else 'Vorschläge'}: Doppelklick]"


def sibling_title_examples(path, limit=5):
    """
    Sammelt bis zu `limit` bereits vergebene Titel anderer PDFs im selben Ordner (nicht
    nur aus dem Dateinamen übernommene, siehe current_title_or_filename) - dient der KI
    als Stilbeispiel, damit thematisch gleiche Dokumente (z.B. alle Rechnungen desselben
    Versicherers) tendenziell ähnlich benannt werden statt bei jedem Aufruf unabhängig
    neu formuliert zu werden.
    """
    folder = os.path.dirname(path)
    examples = []
    try:
        entries = os.listdir(folder)
    except OSError:
        return examples
    for name in entries:
        if len(examples) >= limit:
            break
        if not name.lower().endswith(".pdf"):
            continue
        sibling_path = os.path.join(folder, name)
        if os.path.normcase(sibling_path) == os.path.normcase(path):
            continue
        title = (PDFHandler.get_metadata(sibling_path) or {}).get("title", "").strip()
        if title and title != os.path.splitext(name)[0]:
            examples.append(title)
    return examples


def exclude_folder_name_tag(tags, folder_path):
    """
    Entfernt Tag-Vorschläge, die dem aktuellen Ordnernamen entsprechen (z.B. den
    Firmennamen "Gentilia", wenn das Dokument bereits im Ordner "Gentilia" liegt) - diese
    Information steckt schon in der Ordnerstruktur und ist als Tag überflüssig.

    Neben dem exakten Treffer werden auch die typischen KI-Lesevarianten des Namens
    gefiltert: abgeschnitten ("Gentili" statt "Gentilia" - Tag ist Präfix des
    Ordnernamens) und erweitert ("Gentilia Deutschland Versicherung AG" - Tag enthält
    den Ordnernamen). Mindestlänge 4 verhindert Zufallstreffer durch Kurz-Tags; ein
    Tag wie "2023" bei einem Ordner "Rechnungen 2023" bleibt bewusst erhalten
    (Jahres-Tags sind gewollt, nur Präfix-/Enthält-Beziehungen zum vollen
    Ordnernamen werden geprüft, keine beliebigen Teilstrings).
    """
    folder_name = os.path.basename(os.path.normpath(folder_path)).lower()
    result = []
    for tag in tags:
        tag_l = tag.lower()
        if tag_l == folder_name:
            continue
        if len(tag_l) >= 4 and folder_name.startswith(tag_l) and len(tag_l) >= 0.75 * len(folder_name):
            # Abgeschnittene Variante des Ordnernamens ("Gentili" ~ "Gentilia"): das Tag
            # muss fast den ganzen Namen abdecken - sonst würde z.B. das Katalog-Tag
            # "Rechnung" bei einem Ordner "Rechnungen 2023" fälschlich mitgefiltert.
            continue
        if len(folder_name) >= 4 and folder_name in tag_l:
            continue  # Tag enthält den Ordnernamen (z.B. mit Rechtsform-Zusatz)
        result.append(tag)
    return result


NEW_TAG_MARKER = "(neu) "


def format_tags_preview(tags_list, known_tags_lower):
    """
    Zeigt neue (noch nicht im Tag-Katalog vorhandene) Tags mit Textmarker an, zur
    schnellen Kontrolle. Bewusst Klartext statt Emoji (z.B. 🆕) - die Windows-Standard-
    schrift von Tkinter stellt nicht jedes Emoji dar (zeigt sonst ein leeres Kästchen).
    """
    return ", ".join(f"{NEW_TAG_MARKER}{t}" if t.lower() not in known_tags_lower else t for t in tags_list)


def render_first_page_png(pdf_path, dpi=RENDER_DPI):
    """Rendert die erste Seite als PNG-Bytes - Grundlage für die KI-Bildanalyse."""
    with fitz.open(pdf_path) as doc:
        if doc.page_count == 0:
            return None
        return doc[0].get_pixmap(dpi=dpi).tobytes("png")


# ==========================================
# TOOL-SCHNITTSTELLE
# ==========================================
class AiTitleSuggestTool(BaseTool):
    def __init__(self):
        self.window = None

    @property
    def name(self) -> str:
        return "Titel-Vorschlag (KI)"

    @property
    def menu_group(self) -> str:
        return "KI-Helfer"

    @property
    def menu_label(self) -> str:
        return "Titel vorschlagen (markierte Dokumente)…"

    @property
    def absicht(self) -> str:
        return ("Gescannte Dokumente haben oft keinen oder einen Müll-Titel aus der Texterkennung. Statt selbst zu tippen liest die KI die erste Seite und schlägt vor; du prüfst und übernimmst mit einem Klick.")

    @property
    def description(self) -> str:
        return "Schlägt per lokalem KI-Server (Ollama) einen Titel für die ausgewählten Dokumente vor (Seitenbild wird analysiert)."

    @property
    def braucht_ki(self) -> bool:
        return True   # ohne KI-Server sinnlos - Menüeintrag wird dann gesperrt (ki_status)

    @property
    def menu_hooks(self) -> list:
        return ["context_menu", "main_menu"]

    @property
    def required_input(self) -> str:
        return "multiple_files"

    def execute(self, context: ToolContext) -> bool:
        if self.window and self.window.winfo_exists():
            self.window.lift()
        else:
            self.window = AiTitleSuggestWindow(context.app.root, context.app, context.selected_files)
        return True


# ==========================================
# GUI
# ==========================================
class AiTitleSuggestWindow(tk.Toplevel):
    def __init__(self, parent, app, paths):
        super().__init__(parent)
        self.app = app
        self.title("🤖 Titel-Vorschlag (KI)")
        UIUtils.position_near_mouse(self, UIUtils.px(self, 900), UIUtils.px(self, 500))
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._schliessen)
        self._stop = False  # Schließen während der Analyse: Worker hört nach dem laufenden Dokument auf

        self.rows = {}  # iid -> {"path", "old_title", "keywords", "suggestion"}
        self._setup_ui()
        self._populate(paths)

    def _setup_ui(self):
        top = tk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=(10, 5))
        self.status_var = tk.StringVar(value="")
        tk.Label(top, textvariable=self.status_var, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.btn_suggest = ttk.Button(top, text="Vorschläge laden (KI)", command=self._load_suggestions)
        self.btn_suggest.pack(side=tk.RIGHT, padx=(5, 0))

        columns = ("check", "old_title", "suggestion", "tags")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("check", text="✓")
        self.tree.heading("old_title", text="Aktueller Titel")
        self.tree.heading("suggestion", text="KI-Vorschlag (Titel)")
        self.tree.heading("tags", text="Tags")
        # Nur die letzte Spalte (Tags) soll beim Vergrößern des Fensters mitwachsen -
        # die anderen sind meist schon ausreichend breit, und Tags braucht am meisten Platz.
        self.tree.column("check", width=UIUtils.px(self, 30), anchor="center", stretch=False)
        self.tree.column("old_title", width=UIUtils.px(self, 280), stretch=False)
        self.tree.column("suggestion", width=UIUtils.px(self, 280), stretch=False)
        self.tree.column("tags", width=UIUtils.px(self, 280), stretch=True)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.tree.bind("<Double-1>", self._edit_suggestion)
        self.tree.bind("<space>", self._toggle_check)
        self.tree.bind("<<TreeviewSelect>>", self._sync_main_selection)

        bottom = tk.Frame(self)
        bottom.pack(fill=tk.X, padx=10, pady=(0, 10))
        tk.Label(bottom, text="Doppelklick auf Titel/Tags = bearbeiten, Leertaste = an/abwählen. Tag-Vorschläge kommen nur aus dem Katalog und erst per Klick ins Dokument.", fg="#666").pack(side=tk.LEFT)
        ttk.Button(bottom, text="Markierte übernehmen", command=self._apply_checked, style="Accent.TButton").pack(side=tk.RIGHT)

    def _populate(self, paths):
        if not HAS_FITZ:
            self.status_var.set("PyMuPDF (fitz) nicht verfügbar.")
            self.btn_suggest.config(state=tk.DISABLED)
            return
        for path in paths:
            if not path.lower().endswith(".pdf"):
                continue
            meta = PDFHandler.get_metadata(path)
            old_title = current_title_or_filename(path, meta)
            iid = self.tree.insert("", "end", values=("☐", old_title, "", ""))
            self.rows[iid] = {"path": path, "old_title": old_title, "keywords": meta.get("keywords", ""),
                              "datum": meta.get("KID_DokumentenDatum", "")}
        self.status_var.set(f"{len(self.rows)} Dokument(e) bereit.")
        self._autosize_columns(("old_title", "suggestion"))

    def _autosize_columns(self, cols, max_width=None):
        """Passt die Breite der übergebenen Spalten einmalig an ihren Inhalt an (gedeckelt durch max_width, damit ein einzelner sehr langer Dateiname nicht das ganze Fenster sprengt)."""
        if max_width is None:
            max_width = UIUtils.px(self, 420)   # Deckel wächst mit der Skalierung (FALLSTRICKE #42)
        font = tkfont.nametofont("TkDefaultFont")
        for col in cols:
            width = font.measure(self.tree.heading(col)["text"])
            for item in self.tree.get_children(""):
                width = max(width, font.measure(str(self.tree.set(item, col))))
            self.tree.column(col, width=min(width + UIUtils.px(self, 20), max_width))

    # --- KI-Vorschläge im Hintergrund-Thread laden ---
    def _load_suggestions(self):
        base_url = self.app.config.get("ollama_url", ollama_client.DEFAULT_URL)
        model = self.app.config.get("ollama_model", ollama_client.DEFAULT_MODEL)
        if not ollama_client.is_reachable(base_url):
            messagebox.showwarning(
                "Ollama nicht erreichbar",
                f"Der KI-Server unter {base_url} antwortet nicht.\n"
                "Server-Adresse in den Einstellungen prüfen, oder Ollama lokal/im Netzwerk starten.",
                parent=self,
            )
            return

        known_tags = self.app.tag_manager.get_known_tags() if hasattr(self.app, "tag_manager") else []
        known_tags_lower = {t.lower() for t in known_tags}

        self.btn_suggest.config(state=tk.DISABLED)
        items = list(self.rows.items())

        def worker():
            # Pro Ordner gesammelte Stilbeispiele: zu Beginn aus bereits auf der Platte
            # vorhandenen (kuratierten) Titeln der Geschwister-PDFs, danach ergänzt um
            # die in diesem Lauf selbst erzeugten Titel - so werden mehrere thematisch
            # gleiche Dokumente im selben Batch zunehmend konsistent benannt.
            style_examples_by_folder = {}
            for i, (iid, row) in enumerate(items):
                if self._stop:
                    return
                folder = os.path.dirname(row["path"])
                style_examples = style_examples_by_folder.setdefault(folder, sibling_title_examples(row["path"]))

                result = None
                try:
                    image = render_first_page_png(row["path"])
                    if image:
                        result = ollama_client.suggest_title_and_tags(
                            image, known_tags=known_tags, style_examples=style_examples,
                            base_url=base_url, model=model)
                except Exception as e:
                    if hasattr(self.app, "logger"):
                        self.app.logger.warning(f"KI-Titelvorschlag fehlgeschlagen für {row['path']}: {e}")

                if result and result.get("tags"):
                    result["tags"] = katalog_vorschlaege(exclude_folder_name_tag(result["tags"], folder), known_tags,
                                                         row["keywords"])

                if result and result.get("title") and result["title"] not in style_examples:
                    style_examples_by_folder[folder] = (style_examples + [result["title"]])[-5:]

                self.after(0, self._on_suggestion_ready, iid, result, known_tags_lower, i + 1, len(items))

        threading.Thread(target=worker, daemon=True).start()

    def _schliessen(self):
        self._stop = True
        self.destroy()

    def _on_suggestion_ready(self, iid, result, known_tags_lower, done, total):
        # Fenster während der Analyse geschlossen: die Antwort kommt trotzdem noch an (FALLSTRICKE #85)
        if not (self.winfo_exists() and self.tree.exists(iid)):
            return
        title = (result or {}).get("title", "")
        suggested_tags = (result or {}).get("tags", [])
        self.rows[iid]["suggestion"] = title
        self.rows[iid]["suggested_tags"] = suggested_tags

        # Die Tags bleiben, wie sie im PDF stehen; die KI-Vorschläge liegen nur zum Anklicken bereit (Etappe 6, #120)
        vorhanden = [t.strip() for t in self.rows[iid]["keywords"].split(",") if t.strip()]
        self.rows[iid]["tags_csv"] = ", ".join(vorhanden)

        old_title = self.tree.set(iid, "old_title")
        check = "☑" if title else "☐"
        self.tree.item(iid, values=(check, old_title, title or "(kein Vorschlag)",
                                    format_tags_preview(vorhanden, known_tags_lower) + vorschlag_hinweis(len(suggested_tags))))
        self.status_var.set(f"KI: {done}/{total} verarbeitet...")
        if done == total:
            self.status_var.set(f"Fertig: {total} Dokument(e) verarbeitet.")
            self.btn_suggest.config(state=tk.NORMAL)

    # --- Interaktion ---
    def _sync_main_selection(self, event=None):
        """
        Klick auf eine Zeile im Tool wählt dasselbe Dokument auch in der Dateiliste des
        Hauptfensters aus (inkl. Vorschau). Bewusst NUR selection_set/see - Tkinter feuert
        das on_file_select-Event dann selbst, ein zusätzlicher manueller Aufruf würde
        doppelt rendern (siehe FALLSTRICKE: Render-Deadlock-Regel). Ist das Dokument in
        der aktuellen Ordneransicht nicht (mehr) sichtbar, passiert einfach nichts.
        """
        selection = self.tree.selection()
        if len(selection) != 1:
            return
        path = self.rows.get(selection[0], {}).get("path")
        tree_files = getattr(self.app, "tree_files", None)
        master = getattr(self.app, "master_folder", "")
        if not path or tree_files is None or not master:
            return
        target = os.path.normcase(os.path.abspath(path))
        for item in tree_files.get_children(""):
            values = tree_files.item(item, "values")
            if len(values) > 4 and os.path.normcase(os.path.abspath(os.path.join(master, values[4]))) == target:
                # Auf EXAKTE Einzelauswahl prüfen, nicht nur "ist enthalten" - sonst
                # passiert bei einer bestehenden Mehrfachauswahl (z.B. die ursprünglich
                # markierten Dokumente, mit denen dieses Tool geöffnet wurde) nichts,
                # weil das Ziel-Element ja schon Teil dieser größeren Auswahl ist.
                if tree_files.selection() != (item,):
                    tree_files.selection_set(item)
                    tree_files.see(item)
                break

    def _toggle_check(self, event=None):
        for iid in self.tree.selection():
            check, old_title, suggestion, tags = self.tree.item(iid, "values")
            if not suggestion or suggestion == "(kein Vorschlag)":
                continue
            new_check = "☐" if check == "☑" else "☑"
            self.tree.item(iid, values=(new_check, old_title, suggestion, tags))

    def _edit_suggestion(self, event):
        iid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not iid:
            return
        if col == "#3":
            self._edit_title(iid)
        elif col == "#4":
            self._edit_tags(iid)

    def _edit_title(self, iid):
        check, old_title, suggestion, tags = self.tree.item(iid, "values")
        current = suggestion if suggestion != "(kein Vorschlag)" else ""
        new_value = CandidatePickerDialog.ask(self, "Titel bearbeiten", [current] if current else [], current)
        if new_value and new_value.strip():
            self.rows[iid]["suggestion"] = new_value.strip()
            self.tree.item(iid, values=("☑", old_title, new_value.strip(), tags))

    def _edit_tags(self, iid):
        known_tags = self.app.tag_manager.get_known_tags() if hasattr(self.app, "tag_manager") else []
        known_tags_lower = {t.lower() for t in known_tags}
        row = self.rows[iid]
        current_csv = row.get("tags_csv", row["keywords"])
        suggested = row.get("suggested_tags", [])
        new_value = TagSuggestionDialog.ask(self, "Tags bearbeiten", current_csv, suggested, known_tags_lower)
        if new_value is not None:
            tags_list = [t.strip() for t in new_value.split(",") if t.strip()]
            row["tags_csv"] = ", ".join(tags_list)
            check, old_title, suggestion, _old_tags = self.tree.item(iid, "values")
            self.tree.item(iid, values=(check, old_title, suggestion, format_tags_preview(tags_list, known_tags_lower)))

    def _apply_checked(self):
        to_apply = [iid for iid in self.rows if self.tree.exists(iid) and self.tree.set(iid, "check") == "☑"]
        if not to_apply:
            messagebox.showinfo("Hinweis", "Keine Vorschläge zum Übernehmen markiert.")
            return
        if not bestaetigung.frage("Übernehmen", f"{len(to_apply)} Titel/Tags jetzt in die PDFs schreiben?"):
            return

        known_tags_lower = {t.lower() for t in (self.app.tag_manager.get_known_tags() if hasattr(self.app, "tag_manager") else [])}
        new_tags_added = set()

        errors = []
        for iid in to_apply:
            row = self.rows[iid]
            new_title = self.tree.set(iid, "suggestion")
            new_keywords = row.get("tags_csv", row["keywords"])
            # Noch kein Dokumentdatum im PDF: das aus dem Text gelesene mitspeichern - sonst zeigt die
            # Liste weiter den Download-Tag (Peter 28.10.2026, Kontoauszüge; FALLSTRICKE #86)
            datum = None if row.get("datum") else PDFHandler.suggest_document_date(row["path"])
            ok, msg = PDFHandler.save_metadata(row["path"], new_title, new_keywords, datum=datum)
            if not ok:
                errors.append(f"{os.path.basename(row['path'])}: {msg}")
            else:
                if hasattr(self.app, "tree_tags"):
                    for tag in (t.strip() for t in new_keywords.split(",") if t.strip()):
                        if tag.lower() not in known_tags_lower and tag.lower() not in new_tags_added:
                            self.app.tree_tags.insert("", "end", text=tag, tags=(TagManager.TAG_BUNDLE,))
                            new_tags_added.add(tag.lower())
                self.tree.delete(iid)
                del self.rows[iid]

        if new_tags_added and hasattr(self.app, "tag_editor"):
            self.app.tag_editor.save_tags()
            if hasattr(self.app, "tag_manager"):
                self.app.tag_manager.sync_tag_tree_selection()

        if hasattr(self.app, "index_manager") and self.app.index_manager:
            try:
                self.app.index_manager.iter_documents()
            except Exception:
                pass
        if hasattr(self.app, "folder_manager"):
            self.app.folder_manager.on_folder_select(None)

        if errors:
            messagebox.showerror("Teilweise fehlgeschlagen", "\n".join(errors))
        else:
            messagebox.showinfo("Erledigt", "Alle markierten Titel wurden aktualisiert.")


class TagSuggestionDialog(tk.Toplevel):
    """
    Analog zu CandidatePickerDialog (title_cleanup.py), aber für Mehrfachauswahl:
    die Vorschläge sind an-/abwählbare Buttons, die sich in beide Richtungen mit dem
    Textfeld synchron halten - Klick ändert den Text, manuelles Tippen im Text zieht die
    Button-Zustände nach. Ausgewählte Tags werden steelblue eingefärbt (wie aktive Tags
    im Tag-Baum) statt auf den ttk-"Toolbutton"-Stil zu setzen, dessen an/aus-Zustand
    unter dem Windows-Theme kaum erkennbar ist (siehe FALLSTRICKE zum Tag-Baum-Fokusrahmen -
    dasselbe Rendering-Problem). Noch nicht im Tag-Katalog vorhandene Vorschläge tragen den
    Text-Marker "(neu)" auf dem Button - im Textfeld selbst steht immer der reine,
    speicherbare Tag-Text ohne Marker.
    """
    CHECKED_BG = "steelblue"
    CHECKED_FG = "white"
    UNCHECKED_BG = "SystemButtonFace"
    UNCHECKED_FG = "black"

    def __init__(self, parent, title, current_tags_csv, suggested_tags, known_tags_lower):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.result = None

        current = [t.strip() for t in current_tags_csv.split(",") if t.strip()]
        # Buttons für ALLE Tags anbieten, nicht nur die KI-Vorschläge - sonst lassen sich
        # bereits zugewiesene Tags nur über das Textfeld abwählen, nicht per Klick.
        all_tags = list(dict.fromkeys(current + list(suggested_tags or [])))
        self.check_vars = {}
        self.check_buttons = {}
        if all_tags:
            tk.Label(self, text="Tags (Klick = an/abwählen):", anchor="w").pack(fill=tk.X, padx=10, pady=(10, 2))
            box = tk.Frame(self)
            box.pack(fill=tk.X, padx=10, pady=2)
            for i, tag in enumerate(all_tags):
                label = f"{NEW_TAG_MARKER}{tag}" if tag.lower() not in known_tags_lower else tag
                var = tk.BooleanVar(value=(tag in current))
                self.check_vars[tag] = var
                btn = tk.Checkbutton(box, text=label, variable=var, indicatoron=False,
                                      relief="raised", bd=1, padx=8, pady=4,
                                      command=lambda t=tag: self._apply_check(t))
                btn.grid(row=i // 3, column=i % 3, sticky="w", padx=2, pady=2)
                self.check_buttons[tag] = btn
                self._refresh_button_look(tag)

        tk.Label(self, text="Tags (frei editierbar, Komma-getrennt):", anchor="w").pack(fill=tk.X, padx=10, pady=(10, 2))
        self.text = tk.Text(self, height=3, width=60, wrap="word")
        self.text.insert("1.0", current_tags_csv)
        self.text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        # Return bestätigt wie vorher beim Entry (Zeilenumbrüche ergeben in einer
        # Komma-Liste keinen Sinn); "break" verhindert das Einfügen des Umbruchs.
        self.text.bind("<Return>", lambda e: self._confirm() or "break")
        self.text.bind("<KeyRelease>", self._sync_checks_from_text)

        btns = tk.Frame(self)
        btns.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(btns, text="Übernehmen", command=self._confirm, style="Accent.TButton").pack(side=tk.RIGHT)
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side=tk.RIGHT, padx=(0, 5))

        UIUtils.position_near_mouse_auto(self)
        self.text.focus_set()
        self.text.mark_set("insert", "end")

    def _current_list(self):
        return [t.strip() for t in self.text.get("1.0", tk.END).split(",") if t.strip()]

    def _set_list(self, tags_list):
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", ", ".join(tags_list))

    def _apply_check(self, tag):
        """Checkbutton geklickt: Tag entsprechend dem neuen Button-Zustand im Textfeld ergänzen/entfernen."""
        current = self._current_list()
        if self.check_vars[tag].get():
            if tag not in current:
                current.append(tag)
        else:
            current = [t for t in current if t != tag]
        self._set_list(current)
        self._refresh_button_look(tag)

    def _sync_checks_from_text(self, event=None):
        """Manuell im Textfeld editiert: Button-Zustände (inkl. Einfärbung) an den aktuellen Text angleichen."""
        current = self._current_list()
        for tag, var in self.check_vars.items():
            var.set(tag in current)
            self._refresh_button_look(tag)

    def _refresh_button_look(self, tag):
        """Färbt den Button je nach Zustand deutlich sichtbar ein (steelblue = ausgewählt)."""
        checked = self.check_vars[tag].get()
        bg = self.CHECKED_BG if checked else self.UNCHECKED_BG
        fg = self.CHECKED_FG if checked else self.UNCHECKED_FG
        self.check_buttons[tag].config(bg=bg, fg=fg, activebackground=bg, activeforeground=fg,
                                        selectcolor=bg, relief="sunken" if checked else "raised")

    def _confirm(self):
        self.result = ", ".join(self._current_list())
        self.destroy()

    @staticmethod
    def ask(parent, title, current_tags_csv, suggested_tags, known_tags_lower):
        dialog = TagSuggestionDialog(parent, title, current_tags_csv, suggested_tags, known_tags_lower)
        parent.wait_window(dialog)
        return dialog.result
