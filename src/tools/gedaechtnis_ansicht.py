"""
Ablage-Gedächtnis ansehen (KONZEPT_ABLAGE_GEDAECHTNIS.md Schritt 5, 27.10.2026): listet, was die
Vollautomatik aus dem Bestand gelernt hat - je Absender die Ordner mit der Zahl der Dokumente und
ob die Zuordnung gilt. Ein falscher Fakt wird korrigiert, indem man die falsch liegenden Dokumente
verschiebt (ihre Stimmen wandern mit). Liest nur, schreibt nichts.
"""

import tkinter as tk
from tkinter import ttk

import ablage_gedaechtnis
import auto_pilot
from tools.base_tool import BaseTool, ToolContext
from ui_utils import UIUtils


def zeilen(gedaechtnis):
    """
    Anzeigezeilen, geltende zuerst - testbar ohne Tk:
    [(Absender, Hauptordner, Dokumente-Text, Zustand, Schlüssel, [(weiterer Ordner, n), ...]), ...]
    Dokumente-Text ist "5" oder bei verstreuten Dokumenten "23 von 24" (Peter 28.10.2026: die
    kommagetrennte Ordnerliste war unklar - die übrigen Ordner stehen jetzt als eigene Zeilen darunter).
    """
    ergebnis = []
    for name, schluessel, stimmen in gedaechtnis.eintraege():
        (haupt, n), weitere = stimmen[0], stimmen[1:]
        gesamt = sum(z for _, z in stimmen)
        anzahl = f"{n} von {gesamt}" if weitere else str(n)
        ergebnis.append((name, haupt, anzahl, gedaechtnis.zustand(name), schluessel, weitere))
    ergebnis.sort(key=lambda z: (z[3] != "gilt", z[0].lower()))
    return ergebnis


class GedaechtnisAnsichtTool(BaseTool):
    def __init__(self):
        self.window = None

    @property
    def name(self) -> str:
        return "Ablage-Gedächtnis ansehen"

    @property
    def menu_group(self) -> str:
        return "Vollautomatik"

    @property
    def menu_label(self) -> str:
        return "Ablage-Gedächtnis ansehen…"

    @property
    def absicht(self) -> str:
        return ("Nachvollziehen, was die Vollautomatik aus dem Bestand gelernt hat, und eine falsch gelernte "
                "Zuordnung abstellen.")

    @property
    def description(self) -> str:
        return ("Zeigt je Absender, in welchem Ordner seine Dokumente liegen und ob die Vollautomatik das als "
                "Regel nutzt (ab 2 Dokumenten, mindestens zwei Drittel im selben Ordner).")

    @property
    def menu_hooks(self) -> list:
        return ["main_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        if self.window and self.window.winfo_exists():
            self.window.destroy()
        self.window = GedaechtnisFenster(context.app)
        return True


class GedaechtnisFenster(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Ablage-Gedächtnis")
        # Über dem Hauptfenster bleiben, aber nicht modal (Peter 28.10.2026) - wie die Alias-Verwaltung
        self.transient(app.root)
        UIUtils.position_near_mouse(self, UIUtils.px(self, 900), UIUtils.px(self, 520))
        ttk.Label(self, wraplength=UIUtils.px(self, 870), anchor="w", justify=tk.LEFT, text=(
            "Die Vollautomatik zählt, in welchem Ordner die Dokumente eines Absenders liegen. Ab 2 Dokumenten, "
            "von denen mindestens zwei Drittel im selben Ordner liegen, legt sie neue Dokumente dieses Absenders "
            "dort ab. Liegen Dokumente eines Absenders in verschiedenen Ordnern, zeigt die Zeile den Ordner mit "
            "den meisten („23 von 24“) und grau darunter, wo die übrigen liegen - oft ein falsch abgelegtes "
            "Dokument. Liegt etwas falsch: das Dokument in den richtigen Ordner verschieben, die Zählung zieht "
            "mit.")).pack(fill=tk.X, padx=10, pady=(10, 5))

        # Knopfleiste VOR dem dehnbaren Inhalt packen (side=BOTTOM), sonst verschwindet sie bei 125 %
        knoepfe = ttk.Frame(self)
        knoepfe.pack(side=tk.BOTTOM, pady=(0, 10))
        ttk.Button(knoepfe, text="Schließen", command=self.destroy).pack(side=tk.LEFT, padx=5)
        self.status = ttk.Label(self, anchor="w", foreground="gray40")
        self.status.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 5))

        rahmen = ttk.Frame(self)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        spalten = (("absender", "Absender (wie von der KI gelesen)", 260), ("ordner", "Ordner", 420),
                   ("anzahl", "Dokumente", 90), ("zustand", "Zustand", 110))
        self.tree = ttk.Treeview(rahmen, columns=[s[0] for s in spalten], show="headings", selectmode="browse")
        for spalte, text, breite in spalten:
            self.tree.heading(spalte, text=text)
            self.tree.column(spalte, width=UIUtils.px(self, breite), anchor="w", stretch=spalte == "ordner")
        self.tree.tag_configure("aus", foreground="gray50")
        self.tree.tag_configure("neben", foreground="gray50")
        scroll = ttk.Scrollbar(rahmen, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.bind("<Escape>", lambda e: self.destroy())
        self._fuelle()

    def _fuelle(self):
        master = self.app.master_folder
        ziele = auto_pilot.ordner_fuer_zweitmeinung(auto_pilot.sammle_ordnerliste(master))
        gedaechtnis = ablage_gedaechtnis.lade(getattr(self.app, "index_manager", None), ziele,
                                              getattr(self.app, "logger", None))
        self.tree.delete(*self.tree.get_children())
        alle = zeilen(gedaechtnis)
        dokumente = 0
        for name, ordner, anzahl, zustand, _schluessel, weitere in alle:
            self.tree.insert("", tk.END, values=(name, ordner, anzahl, zustand),
                             tags=() if zustand == "gilt" else ("aus",))
            for anderer, n in weitere:
                # Eingerückt und grau: hier liegen die übrigen Dokumente dieses Absenders - meist falsch
                # abgelegte (Peter 28.10.2026: „auch in …“ sagte ihm nichts)
                text = "1 Dokument liegt abweichend in" if n == 1 else f"{n} Dokumente liegen abweichend in"
                self.tree.insert("", tk.END, values=("", f"    ↳ {text}: {anderer}", "", ""), tags=("neben",))
                dokumente += n
            dokumente += int(anzahl.split()[0])
        gilt = sum(1 for z in alle if z[3] == "gilt")
        self.status.config(text=f"{len(alle)} Absender aus {dokumente} Dokumenten, davon gelten {gilt}. "
                                "Dokumente ohne gespeicherten Absender zählen nicht (Tools → Aufräumen → "
                                "Absender nachlesen).")
