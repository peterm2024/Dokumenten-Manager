import os
import tkinter as tk
from tkinter import ttk, messagebox
from pdf_handler import PDFHandler
from tools.base_tool import BaseTool, ToolContext
from ui_utils import UIUtils

try:
    import fitz  # PyMuPDF
    from PIL import Image, ImageTk
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False


# ==========================================
# 1. DIE TOOL-SCHNITTSTELLE (Der Wrapper)
# ==========================================
class PDFEditorTool(BaseTool):
    def __init__(self):
        self.editor_window = None

    @property
    def name(self) -> str: return "Mini-PDF-Editor"

    @property
    def menu_group(self) -> str:
        return "PDF-Werkzeuge"

    @property
    def menu_label(self) -> str:
        return "Mini-PDF-Editor (Seiten drehen/löschen)…"

    @property
    def absicht(self) -> str:
        return ("Kleine Korrekturen ohne Fremdprogramm: die verkehrt herum gescannte Seite drehen, leere Rückseiten löschen, eine Trennseite einfügen.")

    @property
    def description(self) -> str: return "Seiten löschen, drehen und leere Seiten einfügen."

    @property
    def menu_hooks(self) -> list: return ["context_menu", "main_menu"]

    @property
    def required_input(self) -> str:
        return "single_file"  # ToolManager stellt sicher: exakt EINE Datei ausgewählt

    def execute(self, context: ToolContext) -> bool:
        if not HAS_FITZ:
            messagebox.showerror("Fehler", "PyMuPDF/Pillow ist nicht installiert.")
            return False

        pdf_path = context.selected_files[0]
        if not pdf_path.lower().endswith(".pdf"):
            messagebox.showinfo("Hinweis", "Der Mini-PDF-Editor kann nur PDF-Dateien bearbeiten.")
            return False

        # Nur EINE Editor-Instanz zulassen: bei ungespeicherten Änderungen wäre ein
        # stiller Dokumentwechsel gefährlich, daher wird das offene Fenster nur fokussiert.
        if self.editor_window and self.editor_window.winfo_exists():
            self.editor_window.lift()
            self.editor_window.focus()
            if self.editor_window.pdf_path != pdf_path:
                messagebox.showinfo("Hinweis", "Der Editor ist bereits geöffnet.\nBitte erst schließen, um eine andere Datei zu bearbeiten.",
                                    parent=self.editor_window)
        else:
            self.editor_window = PDFEditorWindow(context.app.root, context.app, pdf_path)
        return True

    # Bewusst KEIN on_selection_changed-Live-Update wie beim Inspektor:
    # ein Dokumentwechsel während ungespeicherter Bearbeitung würde Änderungen gefährden.

    def on_file_moved(self, old_path, new_path):
        """Zieht den Speicherpfad des offenen Editors nach, wenn die Datei in der Haupt-App verschoben/umbenannt wurde."""
        if self.editor_window and self.editor_window.winfo_exists():
            if self.editor_window.pdf_path == old_path:
                self.editor_window.update_path(new_path)


# ==========================================
# 2. DAS EDITOR-FENSTER
# ==========================================
class PDFEditorWindow(tk.Toplevel):
    """
    Nicht-modales Editor-Fenster. Das PDF wird komplett im RAM bearbeitet
    (Memory-Stream, kein File-Lock auf dem Original — siehe FALLSTRICKE #1);
    erst der explizite "Speichern"-Klick ersetzt die Originaldatei über eine
    Temp-Datei (gleiches Muster wie PDFHandler.write_custom_metadata).
    """

    def __init__(self, parent, app, pdf_path):
        super().__init__(parent)
        self.app = app
        self.pdf_path = pdf_path
        self.doc = None
        self.dirty = False
        self.current_page = 0
        self._photo = None       # Referenz halten, sonst sammelt Tkinter das Bild weg
        self._resize_timer = None

        # Hochformat-freundliche Startgröße, nahe der Maus geöffnet;
        # bleibt über dem Hauptfenster, aber nicht modal
        UIUtils.position_near_mouse(self, UIUtils.px(self, 820), UIUtils.px(self, 900))
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            self.doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            messagebox.showerror("Fehler", f"PDF konnte nicht geladen werden:\n{e}", parent=parent)
            self.destroy()
            return

        self._setup_ui()
        self._refresh_page_list(select=0)
        self._update_title()

    # ==========================================
    # UI-AUFBAU
    # ==========================================
    def _setup_ui(self):
        main = ttk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Links: Seitenliste oben, alle Buttons darunter — die Vorschau rechts
        # bekommt so die komplette Fensterhöhe für ein A4-Hochformat.
        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        ttk.Label(left, text="Seiten:").pack(anchor="w")
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.page_list = tk.Listbox(list_frame, width=16, exportselection=False)
        self.page_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll = ttk.Scrollbar(list_frame, command=self.page_list.yview)
        self.page_list.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.page_list.bind("<<ListboxSelect>>", self._on_page_select)

        btns = ttk.Frame(left)
        btns.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btns, text="↺ Links drehen", command=lambda: self._rotate(-90)).pack(fill=tk.X, pady=2)
        ttk.Button(btns, text="↻ Rechts drehen", command=lambda: self._rotate(90)).pack(fill=tk.X, pady=2)
        ttk.Button(btns, text="Leere Seite danach", command=self._insert_blank).pack(fill=tk.X, pady=2)
        ttk.Button(btns, text="Seite löschen", command=self._delete_page).pack(fill=tk.X, pady=2)
        self.btn_save = ttk.Button(btns, text="💾 Speichern", command=self._save, state=tk.DISABLED, style="Accent.TButton")
        self.btn_save.pack(fill=tk.X, pady=(10, 2))

        # Rechts: Vorschau über die volle Höhe, Seite wird eingepasst (Fit-to-Window)
        self.preview = tk.Canvas(main, bg="#e0e0e0", highlightthickness=1, highlightbackground="#999999")
        self.preview.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Debounce statt Direkt-Rendern bei jedem Resize-Pixel (siehe FALLSTRICKE #12)
        self.preview.bind("<Configure>", self._on_preview_resize)

    # ==========================================
    # ANZEIGE
    # ==========================================
    def _update_title(self):
        marker = " *" if self.dirty else ""
        self.title(f"✂️ Mini-PDF-Editor - {os.path.basename(self.pdf_path)}{marker}")
        self.btn_save.config(state=tk.NORMAL if self.dirty else tk.DISABLED)

    def update_path(self, new_path):
        """Wird vom Tool-Wrapper aufgerufen, wenn die Datei in der Haupt-App verschoben/umbenannt wurde."""
        self.pdf_path = new_path
        self._update_title()

    def _refresh_page_list(self, select=None):
        """Baut die Seitenliste neu auf und wählt (falls angegeben) eine Seite aus."""
        self.page_list.delete(0, tk.END)
        for i in range(self.doc.page_count):
            rotation = self.doc[i].rotation
            suffix = f"  ({rotation}°)" if rotation else ""
            self.page_list.insert(tk.END, f" Seite {i + 1}{suffix}")

        if select is not None:
            select = max(0, min(select, self.doc.page_count - 1))
            self.page_list.selection_clear(0, tk.END)
            self.page_list.selection_set(select)
            self.page_list.see(select)
            self.current_page = select
            self._render_page()

    def _on_page_select(self, event=None):
        selection = self.page_list.curselection()
        if selection:
            self.current_page = selection[0]
            self._render_page()

    def _on_preview_resize(self, event):
        if self._resize_timer:
            self.after_cancel(self._resize_timer)
        self._resize_timer = self.after(150, self._render_page)

    def _render_page(self):
        """Rendert die aktuelle Seite komplett eingepasst in die Vorschau (Fit-to-Window, A4-Hochformat-optimiert)."""
        self._resize_timer = None
        try:
            page = self.doc[self.current_page]
            cw = self.preview.winfo_width()
            ch = self.preview.winfo_height()
            if cw < 50 or ch < 50:
                # Canvas hat noch keine echte Größe (Fenster baut sich gerade auf) -> gleich nochmal
                self.after(100, self._render_page)
                return

            # Rotation beachten: bei 90°/270° sind Breite und Höhe vertauscht
            rect = page.rect if page.rotation % 180 == 0 else fitz.Rect(0, 0, page.rect.height, page.rect.width)
            zoom = min((cw - 20) / rect.width, (ch - 20) / rect.height) if rect.width and rect.height else 1.0
            zoom = max(0.05, min(zoom, 3.0))  # Schutz vor Extremwerten

            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            self._photo = ImageTk.PhotoImage(img)

            self.preview.delete("all")
            self.preview.create_image(cw // 2, ch // 2, anchor="center", image=self._photo)
        except Exception as e:
            self.preview.delete("all")
            self.preview.create_text(20, 20, anchor="nw", text=f"Vorschau-Fehler: {e}")

    # ==========================================
    # SEITEN-OPERATIONEN (nur im RAM)
    # ==========================================
    def _rotate(self, delta):
        page = self.doc[self.current_page]
        page.set_rotation((page.rotation + delta) % 360)
        self.dirty = True
        self._update_title()
        self._refresh_page_list(select=self.current_page)

    def _insert_blank(self):
        # Neue Seite übernimmt das Format der aktuellen Seite
        rect = self.doc[self.current_page].rect
        self.doc.new_page(pno=self.current_page + 1, width=rect.width, height=rect.height)
        self.dirty = True
        self._update_title()
        self._refresh_page_list(select=self.current_page + 1)

    def _delete_page(self):
        if self.doc.page_count <= 1:
            messagebox.showinfo("Hinweis", "Die letzte verbleibende Seite kann nicht gelöscht werden.", parent=self)
            return
        self.doc.delete_page(self.current_page)
        self.dirty = True
        self._update_title()
        self._refresh_page_list(select=self.current_page)

    # ==========================================
    # SPEICHERN & SCHLIESSEN
    # ==========================================
    def _save(self):
        """
        Ersetzt die Originaldatei über eine Temp-Datei; Watchdog wird währenddessen stummgeschaltet.
        :return: True bei Erfolg (wichtig für den Speichern-und-Schließen-Ablauf in on_close).
        """
        temp_path = self.pdf_path + ".tmp"
        self.app.is_moving = True
        try:
            # garbage/deflate räumt gelöschte Seiten wirklich aus der Datei
            self.doc.save(temp_path, garbage=3, deflate=True)
            PDFHandler.ersetze_datei(temp_path, self.pdf_path, self.doc.page_count)

            self.dirty = False
            self._update_title()
            if hasattr(self.app, 'logger') and self.app.logger:
                self.app.logger.info(f"Mini-PDF-Editor: Datei gespeichert: {self.pdf_path}")

            # Haupt-Vorschau zwingen, das geänderte Dokument neu zu rendern (Cache-Reset,
            # gleiche Technik wie bei save_manual_date - siehe FALLSTRICKE #15)
            if getattr(self.app, 'current_preview_path', None) == self.pdf_path and hasattr(self.app, 'preview_manager'):
                self.app.preview_manager.verwerfe_cache()
                self.app.preview_manager.update_preview()
            return True
        except Exception as e:
            messagebox.showerror("Fehler", f"Speichern fehlgeschlagen:\n{e}", parent=self)
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            return False
        finally:
            # Watchdog erst nach der Windows-Datei-Freigabe wieder aufwecken
            self.app.root.after(1500, lambda: setattr(self.app, 'is_moving', False))

    def on_close(self):
        if self.dirty:
            antwort = messagebox.askyesnocancel(
                "Änderungen speichern?",
                "Soll ich die Änderungen speichern?\n\nJa = Speichern und schließen\nNein = Änderungen verwerfen\nAbbrechen = Zurück zum Editor",
                parent=self)
            if antwort is None:
                return  # Abbrechen: Fenster bleibt offen
            if antwort:
                if not self._save():
                    return  # Speichern fehlgeschlagen: Fenster offen lassen, nichts verwerfen
        if self.doc:
            self.doc.close()
        self.destroy()
