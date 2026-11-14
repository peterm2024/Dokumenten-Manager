import os
import tkinter as tk
from tkinter import ttk
from tools.base_tool import BaseTool, ToolContext
from ui_utils import UIUtils

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

# ==========================================
# 1. DIE TOOL-SCHNITTSTELLE (Der Wrapper)
# ==========================================
class PDFInspectorTool(BaseTool):
    def __init__(self):
        self.inspector_window = None 

    @property
    def name(self) -> str: return "PDF-Inspektor"

    @property
    def menu_group(self) -> str:
        return "PDF-Werkzeuge"

    @property
    def menu_label(self) -> str:
        return "PDF-Inspektor (Metadaten, Struktur, Text)…"

    @property
    def absicht(self) -> str:
        return ("Nachsehen, was WIRKLICH in der Datei steht: Metadaten, KID-Felder (Datum, Scan-Zeit, Originalname), Textebene je Seite. Die erste Anlaufstelle, wenn die Suche etwas nicht findet oder ein Titel merkwürdig ist.")

    @property
    def description(self) -> str: return "Analysiert Metadaten, Struktur und OCR-Texte."

    @property
    def menu_hooks(self) -> list: return ["context_menu", "main_menu"]

    @property
    def required_input(self) -> str: 
        return "none" # <-- NEU: Das Tool darf jetzt OHNE Datei gestartet werden!

    def execute(self, context: ToolContext) -> bool:
        pdf_path = context.selected_files[0] if context.selected_files else ""
        
        if self.inspector_window and self.inspector_window.winfo_exists():
            self.inspector_window.lift()
            if pdf_path: self.inspector_window.update_data(pdf_path)
        else:
            self.inspector_window = PDFInspectorWindow(context.app.root, pdf_path)
        return True

    # --- NEU: Das Live-Update-Radio ---
    def on_selection_changed(self, context: ToolContext) -> None:
        if self.inspector_window and self.inspector_window.winfo_exists():
            if len(context.selected_files) == 1:
                self.inspector_window.update_data(context.selected_files[0])
            elif len(context.selected_files) > 1:
                self.inspector_window.update_data("MULTI")
            else:
                self.inspector_window.update_data("")

# ==========================================
# 2. DEINE ORIGINAL-GUI (komplett entkoppelt)
# ==========================================
class PDFInspectorWindow(tk.Toplevel):
    def __init__(self, parent, pdf_path):
        super().__init__(parent)
        UIUtils.position_near_mouse(self, UIUtils.px(self, 700), UIUtils.px(self, 550))
        self.transient(parent)  # Bleibt über dem Hauptfenster, aber nicht modal
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        
        self._setup_ui()
        self.update_data(pdf_path)

    def on_close(self):
        self.destroy()

    def _setup_ui(self):
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        self.tab_meta = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_meta, text="Metadaten (Header & XMP)")
        self.txt_meta = tk.Text(self.tab_meta, wrap="word", font=("Consolas", 10), bg="#f8f9fa")
        self._add_scrollbar(self.tab_meta, self.txt_meta)

        self.tab_struct = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_struct, text="Struktur & Eingebettetes")
        self.txt_struct = tk.Text(self.tab_struct, wrap="word", font=("Consolas", 10), bg="#f8f9fa")
        self._add_scrollbar(self.tab_struct, self.txt_struct)

        self.tab_text = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_text, text="Text (OCR-Check)")
        self.txt_text = tk.Text(self.tab_text, wrap="word", font=("Consolas", 10), bg="#f8f9fa")
        self._add_scrollbar(self.tab_text, self.txt_text)

    def _add_scrollbar(self, parent, text_widget):
        scroll = ttk.Scrollbar(parent, command=text_widget.yview)
        text_widget.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        text_widget.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

    def update_data(self, new_pdf_path):
        self.pdf_path = new_pdf_path
        
        # Felder leeren und zum Beschreiben freischalten
        for txt_widget in (self.txt_meta, self.txt_struct, self.txt_text):
            txt_widget.config(state=tk.NORMAL)
            txt_widget.delete("1.0", tk.END)
            
        if not new_pdf_path:
            self.title("🔍 PDF-Inspektor - Bereit")
            msg = "Keine Datei ausgewählt.\nBitte klicke auf ein PDF in der Hauptliste."
            self.txt_meta.insert(tk.END, msg); self.txt_struct.insert(tk.END, msg); self.txt_text.insert(tk.END, msg)
        elif new_pdf_path == "MULTI":
            self.title("🔍 PDF-Inspektor - Mehrfachauswahl")
            msg = "Mehrere Dateien ausgewählt.\nDer Inspektor kann immer nur EINE Datei gleichzeitig scannen."
            self.txt_meta.insert(tk.END, msg); self.txt_struct.insert(tk.END, msg); self.txt_text.insert(tk.END, msg)
        elif not new_pdf_path.lower().endswith(".pdf"):
            dateiname = os.path.basename(new_pdf_path)
            self.title(f"🔍 PDF-Inspektor - {dateiname}")
            msg = f"'{dateiname}' ist kein PDF. Inspektion nicht möglich."
            self.txt_meta.insert(tk.END, msg); self.txt_struct.insert(tk.END, msg); self.txt_text.insert(tk.END, msg)
        else:
            dateiname = os.path.basename(new_pdf_path)
            self.title(f"🔍 PDF-Inspektor - {dateiname}")
            self._load_data()
            
        # Felder wieder sperren
        for txt_widget in (self.txt_meta, self.txt_struct, self.txt_text):
            txt_widget.config(state=tk.DISABLED)

    def _load_data(self):
        if not HAS_FITZ:
            self.txt_meta.insert(tk.END, "Fehler: PyMuPDF ist nicht installiert.\nBitte mit 'pip install PyMuPDF' installieren.")
            return

        try:
            # WICHTIG: als Kontextmanager öffnen, nicht doc.close() als letzte Zeile im
            # try-Block - sonst bleibt bei JEDER Exception zwischen dem Öffnen und dem
            # Ende (z.B. beim Lesen von Metadaten/XMP/Text eines beschädigten PDFs) ein
            # OS-Dateihandle offen, das dann spätere Verschieben/Löschen/Wiederherstellen
            # dieser Datei mit "[WinError 32] wird von einem anderen Prozess verwendet"
            # blockiert, solange der Inspektor offen bleibt.
            with fitz.open(self.pdf_path) as doc:
                # --- 1. Tab: Metadaten ---
                self.txt_meta.insert(tk.END, f"Dateipfad: {self.pdf_path}\nSeitenanzahl: {doc.page_count}\n")
                self.txt_meta.insert(tk.END, "-"*50 + "\n[Standard Dictionary Metadaten]\n")

                for key, value in doc.metadata.items():
                    display_val = value if value else "(leer)"
                    self.txt_meta.insert(tk.END, f"{key}: {display_val}\n")

                    if key == "subject" and value and value.startswith("KID_DATE:"):
                        kid_date = value.replace("KID_DATE:", "").strip()
                        self.txt_meta.insert(tk.END, f"  -> [KI-Extrakt] KID_DokumentenDatum: {kid_date}\n")

                xmp = doc.get_xml_metadata()
                if xmp:
                    self.txt_meta.insert(tk.END, "\n" + "-"*50 + "\n[Erweiterte XMP Metadaten]\n" + xmp)
                else:
                    self.txt_meta.insert(tk.END, "\n[Keine erweiterten XMP Metadaten gefunden]\n")

                # --- 2. Tab: Struktur & Fonts ---
                if doc.page_count > 0:
                    page = doc[0]
                    fonts = page.get_fonts()
                    self.txt_struct.insert(tk.END, f"Eingebettete Fonts auf Seite 1 ({len(fonts)} gefunden):\n")
                    for f in fonts: self.txt_struct.insert(tk.END, f" - {f[3]} (Typ: {f[2]})\n")

                    images = page.get_images()
                    self.txt_struct.insert(tk.END, f"\nEingebettete Bilder auf Seite 1 ({len(images)} gefunden):\n")
                    for img in images: self.txt_struct.insert(tk.END, f" - Bild-ID {img[0]}: {img[2]}x{img[3]} Pixel\n")

                # --- 3. Tab: Text / OCR ---
                if doc.page_count > 0:
                    text = doc[0].get_text()
                    if text.strip():
                        self.txt_text.insert(tk.END, "STATUS: Text gefunden! Das Dokument enthält eine auslesbare Textebene.\n")
                        self.txt_text.insert(tk.END, "-"*50 + "\n\n" + text[:1500] + ("\n\n... [Text abgeschnitten]" if len(text) > 1500 else ""))
                    else:
                        self.txt_text.insert(tk.END, "STATUS: KEIN Text gefunden!\n\nDas Dokument besteht scheinbar nur aus flachen Bildern.")
        except Exception as e:
            self.txt_meta.insert(tk.END, f"Fehler beim Analysieren des PDFs:\n{e}")