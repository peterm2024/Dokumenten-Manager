"""
Wiki von Hand, Schritt N4 (KONZEPT_WIKI_VON_HAND.md, „Neuer Aufbau“, 13.11.2026): Fenster „Schubladen“.

Schubladen entstehen auf Zuruf - beim Speichern eines Eintrags oder weil die KI ein neues Wort vorschlägt. Hier räumt
der Mensch auf:
- „Neu…“ legt eine leere Schublade an,
- „Umbenennen…“ ändert den Namen (alle Einträge bleiben darin),
- „Zusammenlegen mit…“ schiebt alle Einträge in eine andere Schublade, die eigene verschwindet (nach Rückfrage),
- „Löschen“ entfernt eine leere Schublade.

Kein Eintrag geht dabei verloren: Löschen geht nur leer, Zusammenlegen verschiebt (wissen.py, je eine Transaktion).
Das Fenster ist modal zum Wiki-Fenster; nach jeder Änderung zeigt dieses Liste und Auswahl neu
(`WikiFenster.schubladen_geaendert`). Ins Protokoll nur Zahlen.
"""
import tkinter as tk
import tkinter.messagebox as mb
import tkinter.simpledialog as simpledialog
from tkinter import ttk

import wissen
from ui_utils import Tooltip, UIUtils


class SchubladenFenster(tk.Toplevel):
    def __init__(self, wiki):
        super().__init__(wiki)
        self.withdraw()                                   # erst aufbauen, dann zeigen (FALLSTRICKE #90)
        UIUtils.werkzeugfenster(self, wiki)
        self.wiki = wiki
        self.wissen = wiki.wissen
        self.title("Schubladen")
        self.arten = []                                   # wie wissen.arten(); Zeile i der Liste = arten[i]
        self._baue()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        UIUtils.position_near_mouse(self, UIUtils.px(self, 430), UIUtils.px(self, 380))
        self._fuelle()
        self.deiconify()
        try:
            self.grab_set()                               # das Wiki-Fenster wartet, bis hier geschlossen ist
        except tk.TclError:
            pass

    # ---------------------------------------------------------------- Aufbau
    def _baue(self):
        rand = UIUtils.px(self, 10)
        unten = ttk.Frame(self)                           # Knopfleiste VOR dem dehnbaren Inhalt mit side=BOTTOM
        unten.pack(side=tk.BOTTOM, fill=tk.X, padx=rand, pady=(4, rand))
        ttk.Button(unten, text="Schließen", command=self.destroy).pack(side=tk.RIGHT)
        rechts = ttk.Frame(self)
        rechts.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, rand), pady=(rand, 0))
        ttk.Button(rechts, text="Neu…", command=self._neu).pack(fill=tk.X)
        self.btn_name = ttk.Button(rechts, text="Umbenennen…", command=self._umbenennen)
        self.btn_name.pack(fill=tk.X, pady=(6, 0))
        self.btn_legen = ttk.Button(rechts, text="Zusammenlegen mit…", command=self._zusammenlegen_menue)
        self.btn_legen.pack(fill=tk.X, pady=(6, 0))
        Tooltip(self.btn_legen, "Alle Einträge dieser Schublade kommen in eine andere, diese Schublade verschwindet.")
        self.btn_weg = ttk.Button(rechts, text="Löschen", command=self._loeschen)
        self.btn_weg.pack(fill=tk.X, pady=(6, 0))
        Tooltip(self.btn_weg, "Nur eine leere Schublade lässt sich löschen. Einträge vorher verschieben: Zusammenlegen.")
        self.menue = tk.Menu(self, tearoff=0)
        self.tree = ttk.Treeview(self, columns=("name", "anzahl"), show="headings", selectmode="browse")
        self.tree.heading("name", text="Schublade", anchor="w")
        self.tree.heading("anzahl", text="Einträge", anchor="e")
        self.tree.column("name", width=UIUtils.px(self, 190), anchor="w")
        self.tree.column("anzahl", width=UIUtils.px(self, 70), anchor="e", stretch=False)
        self.tree.pack(fill=tk.BOTH, expand=True, padx=rand, pady=(rand, 0))
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._schalte())
        self.tree.bind("<Double-1>", lambda _e: self._umbenennen())

    def _fuelle(self, waehle=None):
        """:param waehle: Name der Schublade, die danach markiert ist"""
        self.arten = self.wissen.arten()
        self.tree.delete(*self.tree.get_children())
        for i, a in enumerate(self.arten):
            self.tree.insert("", tk.END, iid=str(i), values=(a["name"], a["anzahl"]))
            if waehle is not None and a["name"].casefold() == waehle.casefold():
                self.tree.selection_set(str(i))
        self._schalte()

    def _gewaehlt(self):
        markiert = self.tree.selection()
        return self.arten[int(markiert[0])] if markiert else None

    def _schalte(self):
        a = self._gewaehlt()
        self.btn_name.config(state=tk.NORMAL if a else tk.DISABLED)
        self.btn_legen.config(state=tk.NORMAL if a and len(self.arten) > 1 else tk.DISABLED)
        self.btn_weg.config(state=tk.NORMAL if a and not a["anzahl"] and len(self.arten) > 1 else tk.DISABLED)

    # ---------------------------------------------------------------- Änderungen
    def _id(self, art):
        """Id der Schublade; solange es die Datei noch nicht gibt (Id None), entsteht sie jetzt mit den
        Start-Schubladen."""
        return art["id"] if art["id"] is not None else self.wissen.art_neu(art["name"])

    def _aendere(self, arbeit, waehle, protokoll):
        """Eine Änderung ausführen; ein Eingabefehler wird gemeldet. :return: Ergebnis von `arbeit`, None bei Fehler"""
        try:
            ergebnis = arbeit()
        except wissen.Eingabefehler as e:
            mb.showwarning("Schubladen", str(e), parent=self)
            return None
        self._fuelle(waehle)
        self.wiki.schubladen_geaendert()
        self.wiki._log("Wiki: " + protokoll(ergebnis))
        return ergebnis

    def neu(self, name):
        if any(a["name"].casefold() == " ".join(name.split()).casefold() for a in self.arten):
            mb.showwarning("Schubladen", f"Eine Schublade „{' '.join(name.split())}“ gibt es schon.", parent=self)
            return None
        return self._aendere(lambda: self.wissen.art_neu(name), " ".join(name.split()), lambda _e: "Schublade angelegt")

    def umbenennen(self, art, name):
        return self._aendere(lambda: self.wissen.art_umbenennen(self._id(art), name) or True, " ".join(name.split()),
                             lambda _e: "Schublade umbenannt")

    def zusammenlegen(self, von, nach):
        """Alle Einträge von `von` nach `nach`, `von` verschwindet - nach Rückfrage (bewusst nicht abschaltbar)."""
        n = von["anzahl"]
        was = "ist leer" if not n else ("enthält einen Eintrag, er kommt" if n == 1 else f"enthält {n} Einträge, sie kommen")
        if not mb.askyesno("Schubladen", f"Die Schublade „{von['name']}“ {was}"
                           + ("." if not n else f" nach „{nach['name']}“.")
                           + f"\n\n„{von['name']}“ verschwindet. Zusammenlegen?", parent=self):
            return None
        return self._aendere(lambda: self.wissen.arten_zusammenlegen(self._id(von), self._id(nach)), nach["name"],
                             lambda zahl: f"Schubladen zusammengelegt ({zahl} Einträge verschoben)")

    def loeschen(self, art):
        return self._aendere(lambda: self.wissen.art_loeschen(self._id(art)) or True, None,
                             lambda _e: "leere Schublade gelöscht")

    # ---------------------------------------------------------------- Knöpfe
    def _neu(self):
        name = simpledialog.askstring("Neue Schublade", "Name der Schublade:", parent=self)
        if name and name.strip():
            self.neu(name)

    def _umbenennen(self):
        a = self._gewaehlt()
        if a is None:
            return
        name = simpledialog.askstring("Schublade umbenennen", "Neuer Name:", initialvalue=a["name"], parent=self)
        if name and name.strip() and " ".join(name.split()) != a["name"]:
            self.umbenennen(a, name)

    def _zusammenlegen_menue(self):
        von = self._gewaehlt()
        if von is None:
            return
        self.menue.delete(0, "end")
        for a in self.arten:
            if a is not von:
                self.menue.add_command(label=f"{a['name']}  ({a['anzahl']})", command=lambda z=a: self.zusammenlegen(von, z))
        try:
            self.menue.tk_popup(self.btn_legen.winfo_rootx(), self.btn_legen.winfo_rooty() + self.btn_legen.winfo_height())
        finally:
            self.menue.grab_release()

    def _loeschen(self):
        a = self._gewaehlt()
        if a is not None:
            self.loeschen(a)
