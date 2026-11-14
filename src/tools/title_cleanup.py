import os
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import bestaetigung

import app_paths
import ollama_client
from pdf_handler import PDFHandler
from tools.base_tool import BaseTool, ToolContext
from ui_utils import UIUtils
from text_quality import longest_consonant_run, looks_garbled  # noqa: F401 -- Re-Export, test_title_cleanup.py importiert beide weiterhin von hier

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

# ==========================================
# 1. REINE LOGIK (ohne Tk, einzeln testbar)
# ==========================================
# Die allgemeine Kauderwelsch-Heuristik (VOWELS/CONSONANT_RUN_THRESHOLD/
# GARBLED_MIN_WORD_LEN/WORD_PATTERN/longest_consonant_run/looks_garbled) lebt seit
# der "Text-Qualität"-Spalte im Neu-Erfassen-Tool in text_quality.py (siehe Import
# oben) - pdf_handler.py braucht sie ebenfalls, darf aber laut Architektur nicht von
# einem tools/-Modul abhängen.

# Satzzeichen, die in einem echten, sauber gelesenen Seitenausschnitt praktisch nie
# vorkommen, aber typisch für eine kaputte Scanner-OCR-Ebene (FALLSTRICKE #21) sind:
# eingestreute Ziffern/Sonderzeichen (z.B. "6umaq3jSjaA-z;nq3S}eAUd") zerstückeln
# zusammenhängende Buchstabenfolgen in kurze Fragmente, die die Konsonantenketten-
# Prüfung allein nicht mehr erkennt (siehe FALLSTRICKE #21). Bewusst NICHT Teil von
# looks_garbled(): ";" u.ä. kommen in vom Nutzer/Scanner AUTOMATISCH generierten
# Dateinamen legitim als Trennzeichen vor (z.B. "...Privatschutz; V-047-683-133-4") -
# dort wäre der Check ein Fehlalarm. Nur für die engere Rohtext-Prüfung in
# extract_candidate_text gedacht, siehe _span_looks_corrupted.
IMPLAUSIBLE_SPAN_CHARS_PATTERN = re.compile(r"[;{}|`^~]")


def _span_looks_corrupted(text):
    """
    Strengere Prüfung speziell für per get_text() gelesene Seitenausschnitte
    (extract_candidate_text): zusätzlich zu looks_garbled auch verdächtige
    Satzzeichen, die in echtem Fließtext praktisch nie vorkommen (siehe
    IMPLAUSIBLE_SPAN_CHARS_PATTERN) - dort ist das Risiko eines Fehlalarms
    durch legitime Nutzer-Dateinamen nicht gegeben, anders als bei looks_garbled.
    """
    return looks_garbled(text) or bool(IMPLAUSIBLE_SPAN_CHARS_PATTERN.search(text))


def repair_mojibake(text):
    """
    Repariert den klassischen Mojibake-Fall: UTF-8-Bytes, die fälschlich als
    cp1252/Latin-1 dekodiert wurden (z.B. 'Â«' statt '«'). Reine Bytes-Rückrechnung,
    kein Raten - liefert den Originaltext unverändert zurück, falls die Rückrechnung
    fehlschlägt oder das Ergebnis nicht eindeutig besser ist (weniger Ersatzzeichen).
    """
    if not text:
        return text
    try:
        repaired = text.encode("cp1252").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    # Nur übernehmen, wenn die Reparatur nicht selbst neue Fehlzeichen einführt
    if "�" in repaired and "�" not in text:
        return text
    return repaired


# Mindestbreite einer Zeile, damit sie überhaupt als Kandidat in Frage kommt - schließt
# nur echtes Rauschen aus (einzelne Satzzeichen-Fragmente), NICHT kurze einwortige
# Betreffzeilen ("Beitragsrechnung" kann schon bei ~80pt liegen, siehe FALLSTRICKE #21:
# ein zu hoher Wert schließt echte kurze Betreffzeilen versehentlich mit aus). Die
# Unschärfe wird stattdessen über mehrere Kandidaten statt eines Einzel-Vorschlags
# abgefangen (find_subject_candidates) - der Nutzer wählt bei Unklarheit selbst.
MIN_CANDIDATE_WIDTH_PT = 40

# Wie viele Kandidatenzeilen dem Nutzer maximal zur Auswahl angeboten werden.
MAX_CANDIDATES = 3

# Standard-Polsterung um eine erkannte Zeile für den OCR-Ausschnitt (in PDF-Punkten).
LINE_PADDING_PT = 4


def find_subject_candidates(page, limit=MAX_CANDIDATES):
    """
    Positions-Heuristik für die Betreffzeile eines Geschäftsbriefs (DIN-5008-artiges
    Layout: Logo oben, Adressfeld links, Absenderdaten rechts, danach abgesetzt die
    Betreffzeile, dann die Anrede). Funktioniert auch bei kaputter OCR-Ebene, da nur
    Position/Schriftgröße ausgewertet werden (die Bounding-Boxen der OCR-Ebene stimmen,
    nur die gelesenen Zeichen sind Müll - FALLSTRICKE #21), nicht der Textinhalt selbst.

    Liefert bis zu `limit` Kandidaten-Rects (bereits gegen Nachbarzeilen gepolstert,
    siehe _pad_line_avoiding_neighbors), nach Schriftgröße absteigend sortiert - eine
    einzelne Positions-/Größen-Heuristik trifft nicht bei jedem Brief-Layout (siehe
    FALLSTRICKE #21), mehrere Kandidaten lassen den Nutzer bei Unklarheit selbst wählen.
    Ist das Mittelband leer, fällt die Funktion auf eine einzelne Top-Zeile zurück
    (find_top_line_rect). Liefert eine leere Liste, wenn gar nichts gefunden wurde.
    """
    page_w, page_h = page.rect.width, page.rect.height
    lines = _extract_lines(page)

    band_top, band_bottom = page_h * 0.25, page_h * 0.65
    candidates = [l for l in lines
                  if band_top <= l["y0"] <= band_bottom and l["x0"] < page_w * 0.55
                  and (l["x1"] - l["x0"]) >= MIN_CANDIDATE_WIDTH_PT]
    if candidates:
        candidates.sort(key=lambda l: -l["size"])
        chosen = candidates[:limit]
        return [_pad_line_avoiding_neighbors(l, lines, page.rect) for l in chosen]

    top_rect = find_top_line_rect(page)
    return [top_rect] if top_rect is not None else []


def find_subject_line_rect(page):
    """Bequemlichkeits-Wrapper um find_subject_candidates: liefert nur den besten Treffer (oder None)."""
    candidates = find_subject_candidates(page, limit=1)
    return candidates[0] if candidates else None


def find_top_line_rect(page):
    """
    Fallback-Heuristik, falls im Mittelband nichts gefunden wurde: die oberste
    ausreichend breite Textzeile unterhalb der typischen Logo-Zone (erste 8% der
    Seitenhöhe) - kurze Fragmente (Seitenzahl, Datum) werden ausgeschlossen.
    """
    page_h = page.rect.height
    lines = _extract_lines(page)
    candidates = [l for l in lines if l["y0"] > page_h * 0.08 and (l["x1"] - l["x0"]) >= MIN_CANDIDATE_WIDTH_PT]
    if not candidates:
        return None
    best = min(candidates, key=lambda l: l["y0"])
    return _pad_line_avoiding_neighbors(best, lines, page.rect)


def _pad_line_avoiding_neighbors(target, lines, page_rect, pad=LINE_PADDING_PT):
    """
    Polstert eine erkannte Zeile für den OCR-Ausschnitt, begrenzt die Polsterung
    oben/unten aber auf höchstens die halbe Lücke zur nächsten Nachbarzeile - sonst
    reicht der Ausschnitt bei engem Zeilenabstand in die Nachbarzeile hinein und die
    OCR liest deren Anfang als Kauderwelsch mit (siehe FALLSTRICKE #21).
    """
    above_gaps = [target["y0"] - l["y1"] for l in lines if l is not target and l["y1"] <= target["y0"]]
    below_gaps = [l["y0"] - target["y1"] for l in lines if l is not target and l["y0"] >= target["y1"]]
    above_gap = min(above_gaps) if above_gaps else None
    below_gap = min(below_gaps) if below_gaps else None

    top_pad = min(pad, above_gap / 2) if above_gap is not None and above_gap > 0 else pad
    bottom_pad = min(pad, below_gap / 2) if below_gap is not None and below_gap > 0 else pad

    return fitz.Rect(
        max(page_rect.x0, target["x0"] - pad),
        max(page_rect.y0, target["y0"] - top_pad),
        min(page_rect.x1, target["x1"] + pad),
        min(page_rect.y1, target["y1"] + bottom_pad),
    )


def _extract_lines(page):
    """
    Sammelt Textzeilen mit Position und einer robusten repräsentativen Schriftgröße
    (Größe des LÄNGSTEN Fragments einer Zeile statt max() über alle Fragmente -
    einzelne, fälschlich übergroß vermessene Mini-Glyphen verzerren sonst die Auswahl).
    """
    result = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            y0 = min(s["bbox"][1] for s in spans)
            y1 = max(s["bbox"][3] for s in spans)
            x0 = min(s["bbox"][0] for s in spans)
            x1 = max(s["bbox"][2] for s in spans)
            rep_size = max(spans, key=lambda s: len(s["text"]))["size"]
            result.append({"y0": y0, "y1": y1, "x0": x0, "x1": x1, "size": rep_size})
    return result


def ocr_region(page, rect, tessdata_path, language="deu", dpi=300):
    """
    Rendert genau den übergebenen Seitenausschnitt als Bild und lässt Tesseract
    (über PyMuPDF eingebaut) nur diesen kleinen Bereich lesen - schneller und
    präziser als die ganze Seite zu scannen. `rect` muss bereits die gewünschte
    Polsterung enthalten (siehe _pad_line_avoiding_neighbors) - hier wird NICHT
    nochmal gepolstert, um kein erneutes Hineinreichen in Nachbarzeilen zu riskieren.
    Wirft bei fehlenden Sprachdaten eine aussagekräftige Exception (Aufrufer fängt das ab).
    """
    pix = page.get_pixmap(dpi=dpi, clip=rect)
    ocr_bytes = pix.pdfocr_tobytes(compress=False, language=language, tessdata=tessdata_path)
    with fitz.open(stream=ocr_bytes, filetype="pdf") as ocr_doc:
        return ocr_doc[0].get_text("text").strip()


def extract_candidate_text(page, rect, tessdata_path, language="deu"):
    """
    Liest den Text eines Kandidaten-Rects: bevorzugt die eingebettete (echte) Textebene
    (schnell, zuverlässig - Ground Truth), wenn sie an dieser Stelle nicht kaputt
    aussieht. Nur bei Verdacht auf kaputte Kodierung (_span_looks_corrupted) wird
    gezielt per OCR nachgelesen - nicht jedes Dokument hat die Kauderwelsch-OCR-Ebene
    aus FALLSTRICKE #21, manche PDFs sind schlicht korrekt und brauchen gar kein OCR.
    """
    real_text = " ".join(page.get_text("text", clip=rect).split())
    if real_text and not _span_looks_corrupted(real_text):
        return real_text
    try:
        ocr_text = ocr_region(page, rect, tessdata_path, language=language)
        ocr_text = repair_mojibake(ocr_text)
        return " ".join(ocr_text.split()) or None
    except Exception:
        return real_text or None


def suggest_titles(pdf_path, tessdata_path, language="deu", limit=MAX_CANDIDATES):
    """
    Kompletter Vorschlags-Pipeline für ein einzelnes PDF: bis zu `limit`
    Betreffzeilen-Kandidaten per Layout-Heuristik finden, pro Kandidat Text lesen
    (echte Textebene bevorzugt, sonst gezielt per OCR). Gibt eine Liste eindeutiger,
    nicht-leerer Vorschläge zurück (leere Liste, wenn nichts gefunden wurde bzw. ein
    Fehler auftrat, z.B. fehlende Tesseract-Sprachdaten).
    """
    if not HAS_FITZ:
        return []
    try:
        with fitz.open(pdf_path) as doc:
            if doc.page_count == 0:
                return []
            page = doc[0]
            rects = find_subject_candidates(page, limit=limit)
            results = []
            for rect in rects:
                text = extract_candidate_text(page, rect, tessdata_path, language=language)
                if text and text not in results:
                    results.append(text)
            return results
    except Exception:
        return []


# ==========================================
# 2. TOOL-SCHNITTSTELLE
# ==========================================
class TitleCleanupTool(BaseTool):
    def __init__(self):
        self.window = None

    @property
    def name(self) -> str:
        return "Titel-Aufräumen (OCR)"

    @property
    def menu_group(self) -> str:
        return "Aufräumen"

    @property
    def menu_label(self) -> str:
        return "Titel aufräumen (kaputte OCR-Titel)…"

    @property
    def absicht(self) -> str:
        return ("Titel aus kaputter OCR oder Fonts („l='n' =l“) sind unbrauchbar. Das Tool findet sie und bietet Kandidaten aus dem Dokumenttext zur Auswahl - für den ganzen Bestand auf einmal.")

    @property
    def description(self) -> str:
        return "Findet Dokumente mit kaputtem OCR-/Font-Titel und schlägt passende Titel-Kandidaten zur Auswahl vor."

    @property
    def menu_hooks(self) -> list:
        return ["main_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        if self.window and self.window.winfo_exists():
            self.window.lift()
        else:
            self.window = TitleCleanupWindow(context.app.root, context.app)
        return True


# ==========================================
# 3. GUI
# ==========================================
class TitleCleanupWindow(tk.Toplevel):
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("🧹 Titel-Aufräumen (OCR)")
        UIUtils.position_near_mouse(self, UIUtils.px(self, 900), UIUtils.px(self, 550))
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        self.rows = {}  # iid -> {"path": ..., "old_title": ..., "keywords": ...}
        self._ki_laeuft = False
        self._setup_ui()
        self._scan()

    def _setup_ui(self):
        top = tk.Frame(self)
        top.pack(fill=tk.X, padx=10, pady=(10, 5))
        self.status_var = tk.StringVar(value="Durchsuche Sammlung...")
        tk.Label(top, textvariable=self.status_var, anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)

        # KI-Titel wie im Dateinamen-Tool (T5.7-Befund 17.09.2026: OCR-Vorschläge teils schlechter als
        # der alte Titel - die KI liest die erste Seite als Bild und trifft den Betreff meist besser)
        self.btn_ki = ttk.Button(top, text="KI-Titel vorschlagen", command=self._ki_titel, state=tk.DISABLED)
        self.btn_ki.pack(side=tk.RIGHT, padx=(5, 0))
        self.btn_suggest = ttk.Button(top, text="Vorschläge laden (OCR)", command=self._load_suggestions, state=tk.DISABLED)
        self.btn_suggest.pack(side=tk.RIGHT, padx=(5, 0))

        # Knopfzeile ZUERST und unten packen, damit sie bei kleinem Fenster sichtbar bleibt
        bottom = tk.Frame(self)
        bottom.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 10))
        tk.Label(bottom, text="Klick auf eine Zeile zeigt das Dokument im Hauptfenster. Doppelklick auf Vorschlag = "
                              "bearbeiten, Leertaste = an/abwählen.", fg="#666").pack(side=tk.LEFT)
        ttk.Button(bottom, text="Markierte übernehmen", command=self._apply_checked, style="Accent.TButton").pack(side=tk.RIGHT)

        rahmen = tk.Frame(self)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        columns = ("check", "datei", "old_title", "suggestion")
        self.tree = ttk.Treeview(rahmen, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("check", text="✓")
        self.tree.heading("datei", text="Datei")
        self.tree.heading("old_title", text="Aktueller Titel")
        self.tree.heading("suggestion", text="Vorschlag")
        self.tree.column("check", width=UIUtils.px(self, 30), anchor="center", stretch=False)
        self.tree.column("datei", width=UIUtils.px(self, 220))
        self.tree.column("old_title", width=UIUtils.px(self, 280))
        self.tree.column("suggestion", width=UIUtils.px(self, 320))
        rollen = ttk.Scrollbar(rahmen, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=rollen.set)
        rollen.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self._edit_suggestion)
        self.tree.bind("<space>", self._toggle_check)
        self.tree.bind("<<TreeviewSelect>>", self._sync_hauptfenster)

    # --- Schritt 1: verdächtige Dokumente finden (schnell, kein OCR) ---
    def _scan(self):
        master = getattr(self.app, "master_folder", None)
        if not master or not os.path.isdir(master):
            self.status_var.set("Kein Hauptordner gewählt.")
            return

        found = []
        for root_dir, _, files in os.walk(master):
            if app_paths.is_trash_path(root_dir, master):
                continue
            for name in files:
                if not name.lower().endswith(".pdf"):
                    continue
                abs_path = os.path.join(root_dir, name)
                meta = PDFHandler.get_metadata(abs_path)
                title = meta.get("title", "") or os.path.splitext(name)[0]
                if looks_garbled(title):
                    found.append((abs_path, title, meta.get("keywords", "")))

        for abs_path, title, keywords in found:
            iid = self.tree.insert("", "end", values=("☐", os.path.relpath(abs_path, master), title, ""))
            self.rows[iid] = {"path": abs_path, "old_title": title, "keywords": keywords}

        if not found:
            self.status_var.set("Keine verdächtigen Titel gefunden. 🎉")
        else:
            self.status_var.set(f"{len(found)} verdächtige Titel gefunden.")
            if not HAS_FITZ or not os.path.isdir(app_paths.tessdata_dir()):
                self.status_var.set(self.status_var.get() + " (OCR-Sprachdaten fehlen - siehe tessdata/-Ordner)")
            else:
                self.btn_suggest.config(state=tk.NORMAL)
            self.btn_ki.config(state=tk.NORMAL if HAS_FITZ else tk.DISABLED)

    def _sync_hauptfenster(self, event=None):
        """Klick auf eine Zeile zeigt das Dokument im Hauptfenster (T5.7-Befund 17.09.2026: Vorschau fehlte)."""
        auswahl = self.tree.selection()
        folder_manager = getattr(self.app, "folder_manager", None)
        if len(auswahl) == 1 and auswahl[0] in self.rows and folder_manager is not None:
            folder_manager.zeige_dokument(self.rows[auswahl[0]]["path"])

    # --- Schritt 2: OCR-Vorschläge nachladen (im Hintergrund-Thread) ---
    def _load_suggestions(self):
        self.btn_suggest.config(state=tk.DISABLED)
        tessdata_path = app_paths.tessdata_dir()
        items = list(self.rows.items())

        def worker():
            for i, (iid, row) in enumerate(items):
                candidates = suggest_titles(row["path"], tessdata_path)
                self.after(0, self._on_suggestion_ready, iid, candidates, i + 1, len(items))

        threading.Thread(target=worker, daemon=True).start()

    def _on_suggestion_ready(self, iid, candidates, done, total):
        if not self.tree.exists(iid):
            return
        # OCR-Kandidaten hinter einen evtl. schon vorhandenen KI-Titel einreihen
        vorhandene = self.rows[iid].get("candidates", [])
        self.rows[iid]["candidates"] = vorhandene + [c for c in candidates if c not in vorhandene]
        if not self.rows[iid].get("suggestion"):
            self.rows[iid]["suggestion"] = candidates[0] if candidates else ""
        # Bewusst KEIN Haken: der Nutzer sieht den Vorschlag erst an (T5.7-Befund 17.09.2026:
        # OCR-Vorschläge waren teils schlechter als der alte Titel)
        self._zeichne_zeile(iid)
        self.status_var.set(f"OCR: {done}/{total} verarbeitet...")
        if done == total:
            self.status_var.set(f"Fertig: {total} Vorschläge geladen - bitte ansehen und anhaken.")

    def _zeichne_zeile(self, iid, check=None):
        row = self.rows[iid]
        if check is None:
            check = self.tree.set(iid, "check")
        vorschlag = row.get("suggestion") or ("(KI liest…)" if row.get("ki_laeuft") else "")
        if not vorschlag and "candidates" in row:
            vorschlag = "(kein Vorschlag gefunden)"
        if not row.get("suggestion"):
            check = "☐"
        self.tree.item(iid, values=(check, os.path.relpath(row["path"], self.app.master_folder),
                                    row["old_title"], vorschlag))

    # --- Schritt 2b: KI-Titel (erste Seite als Bild, wie im Dateinamen-Tool) ---
    def _ki_titel(self):
        """Lässt die KI für die markierten Zeilen (ohne Markierung: alle ohne KI-Titel) einen Titel ablesen.
        Der KI-Titel wird zum Vorschlag (vor die OCR-Kandidaten), die Zeile bleibt OHNE Haken."""
        if self._ki_laeuft:
            return
        ziele = [iid for iid in self.tree.selection() if iid in self.rows]
        if not ziele:
            ziele = [iid for iid, row in self.rows.items() if not row.get("ki_titel")]
        if not ziele:
            messagebox.showinfo("KI-Titel vorschlagen", "Keine Zeilen markiert und alle haben schon einen KI-Titel.", parent=self)
            return
        base_url = self.app.config.get("ollama_url", ollama_client.DEFAULT_URL)
        model = self.app.config.get("ollama_model", ollama_client.DEFAULT_MODEL)
        if not ollama_client.is_reachable(base_url):
            messagebox.showwarning("Ollama nicht erreichbar",
                                   f"Der KI-Server unter {base_url} antwortet nicht.\n"
                                   "Server-Adresse in den Einstellungen prüfen, oder Ollama lokal/im Netzwerk starten.",
                                   parent=self)
            return
        from tools.ai_title_suggest import render_first_page_png
        self._ki_laeuft = True
        self.btn_ki.config(state=tk.DISABLED)
        for iid in ziele:
            self.rows[iid]["ki_laeuft"] = True
            self._zeichne_zeile(iid)
        self.status_var.set(f"KI liest {len(ziele)} Dokument(e)…")
        auftraege = [(iid, self.rows[iid]["path"]) for iid in ziele]

        def worker():
            for nr, (iid, pfad) in enumerate(auftraege, start=1):
                titel = ""
                try:
                    bild = render_first_page_png(pfad)
                    if bild:
                        titel = ollama_client.suggest_title(bild, base_url=base_url, model=model)
                except Exception as e:
                    if getattr(self.app, "logger", None):
                        self.app.logger.warning(f"KI-Titel fehlgeschlagen für {pfad}: {e}")
                self.after(0, self._ki_fertig, iid, titel, nr, len(auftraege))

        threading.Thread(target=worker, daemon=True).start()

    def _ki_fertig(self, iid, titel, nr, gesamt):
        if not self.winfo_exists():
            return
        row = self.rows.get(iid)
        if row is not None:
            row["ki_laeuft"] = False
            if titel:
                row["ki_titel"] = titel
                row["suggestion"] = titel
                row["candidates"] = [titel] + [c for c in row.get("candidates", []) if c != titel]
            if self.tree.exists(iid):
                self._zeichne_zeile(iid)
        self.status_var.set(f"KI: {nr}/{gesamt} gelesen…")
        if nr >= gesamt:
            self._ki_laeuft = False
            self.btn_ki.config(state=tk.NORMAL)
            self.status_var.set(f"Fertig: {gesamt} KI-Titel gelesen - bitte ansehen und anhaken.")

    # --- Interaktion ---
    def _toggle_check(self, event=None):
        for iid in self.tree.selection():
            if not self.rows[iid].get("suggestion"):
                continue
            self._zeichne_zeile(iid, "☐" if self.tree.set(iid, "check") == "☑" else "☑")

    def _edit_suggestion(self, event):
        iid = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not iid or col != "#4":
            return
        candidates = self.rows[iid].get("candidates", [])
        new_value = CandidatePickerDialog.ask(self, "Titel wählen", candidates, self.rows[iid].get("suggestion", ""))
        if new_value and new_value.strip():
            self.rows[iid]["suggestion"] = new_value.strip()
            self._zeichne_zeile(iid, "☑")

    def _apply_checked(self):
        to_apply = [iid for iid in self.rows if self.tree.exists(iid) and self.tree.set(iid, "check") == "☑"]
        if not to_apply:
            messagebox.showinfo("Hinweis", "Keine Vorschläge zum Übernehmen markiert.")
            return
        if not bestaetigung.frage("Übernehmen", f"{len(to_apply)} Titel jetzt in die PDFs schreiben?"):
            return

        errors = []
        for iid in to_apply:
            row = self.rows[iid]
            new_title = row.get("suggestion") or self.tree.set(iid, "suggestion")
            ok, msg = PDFHandler.save_metadata(row["path"], new_title, row["keywords"])
            if not ok:
                errors.append(f"{os.path.basename(row['path'])}: {msg}")
            else:
                self.tree.delete(iid)
                del self.rows[iid]

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


class CandidatePickerDialog(tk.Toplevel):
    """
    Kleiner modaler Dialog: zeigt bis zu MAX_CANDIDATES gefundene Titel-Kandidaten
    zur Auswahl (Klick übernimmt sofort in das Textfeld) plus ein frei editierbares
    Textfeld darunter für Handkorrekturen. Eine einzelne Positions-Heuristik trifft
    nicht immer die richtige Zeile (siehe FALLSTRICKE #21) - hier entscheidet der
    Nutzer bei Unklarheit selbst, ohne alles neu tippen zu müssen.
    """
    def __init__(self, parent, title, candidates, initial_value):
        super().__init__(parent)
        self.title(title)
        self.transient(parent)
        self.grab_set()
        self.result = None

        if candidates:
            tk.Label(self, text="Gefundene Kandidaten (Klick übernimmt):", anchor="w").pack(fill=tk.X, padx=10, pady=(10, 2))
            for cand in candidates:
                ttk.Button(self, text=cand, command=lambda c=cand: self._use(c)).pack(fill=tk.X, padx=10, pady=2)

        tk.Label(self, text="Titel (frei editierbar):", anchor="w").pack(fill=tk.X, padx=10, pady=(10, 2))
        self.entry = ttk.Entry(self, width=60)
        self.entry.insert(0, initial_value or "")
        self.entry.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.entry.bind("<Return>", lambda e: self._confirm())

        btns = tk.Frame(self)
        btns.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Button(btns, text="Übernehmen", command=self._confirm, style="Accent.TButton").pack(side=tk.RIGHT)
        ttk.Button(btns, text="Abbrechen", command=self.destroy).pack(side=tk.RIGHT, padx=(0, 5))

        UIUtils.position_near_mouse_auto(self)
        self.entry.focus_set()
        self.entry.icursor(tk.END)

    def _use(self, text):
        self.entry.delete(0, tk.END)
        self.entry.insert(0, text)

    def _confirm(self):
        self.result = self.entry.get()
        self.destroy()

    @staticmethod
    def ask(parent, title, candidates, initial_value):
        dialog = CandidatePickerDialog(parent, title, candidates, initial_value)
        parent.wait_window(dialog)
        return dialog.result
