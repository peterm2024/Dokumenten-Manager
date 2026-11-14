"""
Suchfeld der Volltextsuche (Nutzerwunsch 13.09.2026): dieselbe Tag-Autovervollständigung wie
im Tags-Feld und bekannte Tags im Suchtext blau-fett wie im Tag-Baum.

Ein ttk.Entry kann einzelne Wörter nicht einfärben, deshalb ist das Suchfeld seit dem
13.09.2026 ein einzeiliges tk.Text (wie das Tags-Feld). Damit der übrige Code (search_manager,
folder_manager, gui) weiter wie mit einem Entry arbeiten kann, bietet SuchFeld die
Entry-Aufrufe `get()` ohne Argumente und `delete(0, END)` an.

Reine Logik ohne Tk (testbar): `bekannte_tag_spannen(text, bekannte_tags)` liefert die
Zeichenbereiche der Wörter bzw. Anführungszeichen-Phrasen, die genau einem zuweisbaren Tag
entsprechen (Groß-/Kleinschreibung egal) - Phrasen wie "Musterstraße 12" werden samt
Anführungszeichen markiert.
"""

import re
import tkinter as tk
import tkinter.font as tkfont

TAG_FARBE = "#0055a4"          # wie "active_tag" im Tag-Baum (layout_builder)
_TOKEN = re.compile(r'"[^"]*"?|\S+')


def bekannte_tag_spannen(text, bekannte_tags):
    """
    Zeichenbereiche [(anfang, ende), ...] aller Suchbegriffe, die genau einem bekannten Tag
    entsprechen. Ein Begriff ist ein Wort ohne Leerzeichen oder eine Phrase in
    Anführungszeichen; verglichen wird ohne Anführungszeichen und ohne Groß-/Kleinschreibung.
    Ein Stern-Platzhalter macht den Begriff nie zu einem Tag ("Rech*" bleibt schwarz).
    """
    if not text or not bekannte_tags:
        return []
    bekannt = {t.strip().casefold() for t in bekannte_tags if t and t.strip()}
    spannen = []
    for treffer in _TOKEN.finditer(text):
        begriff = treffer.group().strip('"').strip().casefold()
        if begriff and "*" not in begriff and begriff in bekannt:
            spannen.append((treffer.start(), treffer.end()))
    return spannen


class SuchFeld(tk.Text):
    """Einzeiliges Suchfeld mit Entry-kompatiblem get()/delete() und Tag-Hervorhebung."""

    TAG_NAME = "bekanntes_tag"

    def __init__(self, master, bekannte_tags_fn, **kw):
        """
        :param bekannte_tags_fn: liefert die Liste der zuweisbaren Tags (TagManager.get_known_tags)
        """
        kw.setdefault("height", 1)
        kw.setdefault("wrap", "none")
        kw.setdefault("undo", False)
        basis = tkfont.nametofont("TkDefaultFont")
        kw.setdefault("font", basis)
        super().__init__(master, **kw)
        self._bekannte_tags_fn = bekannte_tags_fn
        fett = tkfont.Font(font=basis)
        fett.configure(weight="bold")
        self._fett = fett   # Referenz halten, sonst räumt Tk die Schrift weg
        self.tag_configure(self.TAG_NAME, foreground=TAG_FARBE, font=fett)
        # Kein Zeilenumbruch im einzeiligen Feld: Return wird in layout_builder für die
        # Suche gebunden; hier nur der Schutz gegen "\n" durch Einfügen (Strg+V).
        self.bind("<<Paste>>", self._nach_einfuegen, add="+")
        self.bind("<KeyRelease>", lambda e: self.markiere_tags(), add="+")

    # ---------------------------------------------------------------- Entry-Kompatibilität
    def get(self, *args):
        """Ohne Argumente wie ttk.Entry.get(): der ganze Text (ohne das abschließende Zeilenende)."""
        if not args:
            return super().get("1.0", "end-1c").replace("\n", " ")
        return super().get(*args)

    def delete(self, first, last=None):
        """Wie ttk.Entry.delete(0, END): alles löschen; sonst normales Text.delete."""
        if first == 0 or first == "0":
            super().delete("1.0", tk.END)
            return
        if last is None:
            super().delete(first)
        else:
            super().delete(first, last)

    def setze_text(self, text):
        """Inhalt komplett ersetzen (z.B. Tests, Wizard) und Markierung erneuern."""
        super().delete("1.0", tk.END)
        super().insert("1.0", text.replace("\n", " "))
        self.markiere_tags()

    # ---------------------------------------------------------------- Hervorhebung
    def markiere_tags(self):
        """Bekannte Tags im Suchtext blau-fett markieren (wie im Tag-Baum), alles andere normal."""
        self.tag_remove(self.TAG_NAME, "1.0", tk.END)
        text = self.get()
        try:
            bekannt = self._bekannte_tags_fn() or []
        except Exception:
            bekannt = []
        for anfang, ende in bekannte_tag_spannen(text, bekannt):
            self.tag_add(self.TAG_NAME, f"1.0 + {anfang} chars", f"1.0 + {ende} chars")

    def _nach_einfuegen(self, _event=None):
        # Nach dem Einfügen (Clipboard kann Zeilenumbrüche enthalten) in einer Zeile halten
        self.after_idle(self._einzeilig)

    def _einzeilig(self):
        text = super().get("1.0", "end-1c")
        if "\n" in text:
            self.setze_text(text.replace("\n", " "))
