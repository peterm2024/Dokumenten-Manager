"""
Wiki-Bereich „Ablageordner“ (KONZEPT_ORDNER_STECKBRIEF.md Schritt 3, 15.11.2026): zeigt je Ablageordner seinen
Steckbrief - die Nummern, IBANs und Adressen, die in mindestens zwei seiner Dokumente und fast nur dort stehen
(ordner_steckbrief.py). Trägt ein neues Dokument dieselben Merkmale, schlägt die Vollautomatik diesen Ordner vor.

Links die Ordner mit Merkmalen (Suchfeld), rechts die Merkmale des gewählten Ordners mit der Zahl seiner Dokumente,
darunter die Belege des gewählten Merkmals (Doppelklick zeigt das Dokument im Hauptfenster). „Ausschließen“ verwirft
ein Merkmal für diesen Ordner - gespeichert im Wiki (wissen.merkmal_ausschliessen), Vollautomatik und Ablage-Vorschau
beachten es ab ihrer nächsten Runde; „Wieder zulassen“ nimmt das zurück.

Der Steckbrief wird beim Öffnen aus dem Volltext-Index berechnet (Hintergrund-Thread: beim ersten Mal liest der
Abgleich den Text der ganzen Sammlung), gespeichert wird nur der Ausschluss. Geöffnet aus dem Wiki-Fenster
(„Ablageordner…“), nicht modal. Ins Protokoll nur Zahlen, nie Merkmale oder Ordner.
"""
import os
import threading
import tkinter as tk
import tkinter.messagebox as mb
from tkinter import ttk

import aktivitaet
import auto_pilot
import ordner_steckbrief
from ui_utils import Tooltip, UIUtils

ARTEN_TEXT = {"IBAN": "IBAN", "Nummer": "Nummer", "Kennung": "Kennung", "Adresse": "Adresse"}


def ordner_zeilen(steckbriefe, suche=""):
    """[(Ordner, geltende Merkmale, ausgeschlossene)] - nur Ordner mit Merkmalen, das Suchwort im Ordnernamen. Testbar
    ohne Tk."""
    suche = (suche or "").casefold().strip()
    zeilen = []
    for ordner in steckbriefe.ordner():
        if suche and suche not in ordner.casefold():
            continue
        merkmale = steckbriefe.von_ordner(ordner)
        aus = sum(1 for m in merkmale if m[3])
        zeilen.append((ordner, len(merkmale) - aus, aus))
    return zeilen


def merkmal_zeilen(steckbriefe, ordner):
    """[(Art-Text, Wert, Dokumente, Zustand-Text, ausgeschlossen)] für die rechte Liste."""
    return [(ARTEN_TEXT.get(art, art), wert, n, "ausgeschlossen" if aus else "zählt", aus)
            for art, wert, n, aus in steckbriefe.von_ordner(ordner)]


def lade_ansicht(app, wissen_db):
    """Steckbriefe samt Belegen der aktuellen Sammlung (aus jedem Thread). :return: (Steckbriefe, Dokumente)"""
    master = app.master_folder
    ziele = auto_pilot.ordner_fuer_zweitmeinung(auto_pilot.sammle_ordnerliste(master))
    index = getattr(app, "index_manager", None)
    ablagen = index.ablage_texte() if index is not None else []
    return ordner_steckbrief.ansicht(ablagen, ziele, ausgeschlossen=wissen_db.ausgeschlossene_merkmale())


class AblageordnerFenster(tk.Toplevel):
    def __init__(self, wiki):
        super().__init__(wiki)
        self.withdraw()                                   # erst aufbauen, dann zeigen (FALLSTRICKE #90)
        UIUtils.werkzeugfenster(self, wiki)
        self.app = wiki.app
        self.wissen = wiki.wissen
        self.title("Ablageordner")
        self.steckbriefe = None
        self.dokumente = {}
        self._ordner = []                                 # Zeile i links = _ordner[i]
        self._merkmale = []                               # Zeile i rechts = _merkmale[i]
        self._belege = []                                 # Zeile i unten = _belege[i] (rel_pfad)
        self._baue()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        UIUtils.position_near_mouse(self, UIUtils.px(self, 900), UIUtils.px(self, 620))
        self.deiconify()
        self._lade()

    # ---------------------------------------------------------------- Aufbau
    def _baue(self):
        rand = UIUtils.px(self, 10)
        ttk.Label(self, wraplength=UIUtils.px(self, 860), justify=tk.LEFT, text=(
            "Der Steckbrief eines Ordners: Nummern, IBANs und Adressen, die in mindestens zwei seiner Dokumente und "
            "fast nur dort stehen. Trägt ein neues Dokument dieselben, schlägt die Vollautomatik diesen Ordner vor. "
            "Gehört ein Merkmal nicht zum Ordner, etwa weil es auch in anderen Ordnern gilt: ausschließen.")
        ).pack(fill=tk.X, padx=rand, pady=(rand, 4))

        unten = ttk.Frame(self)                           # Knopfleiste VOR dem dehnbaren Inhalt mit side=BOTTOM
        unten.pack(side=tk.BOTTOM, fill=tk.X, padx=rand, pady=(4, rand))
        ttk.Button(unten, text="Schließen", command=self.destroy).pack(side=tk.RIGHT)
        self.status = ttk.Label(unten, foreground="gray40")
        self.status.pack(side=tk.LEFT)

        teiler = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        teiler.pack(fill=tk.BOTH, expand=True, padx=rand, pady=(4, 0))
        links = ttk.Frame(teiler)
        rechts = ttk.Frame(teiler)
        teiler.add(links, weight=2)
        teiler.add(rechts, weight=3)

        self.var_suche = tk.StringVar()
        suche = ttk.Entry(links, textvariable=self.var_suche)
        suche.pack(fill=tk.X, pady=(0, 4))
        Tooltip(suche, "Ordner nach ihrem Namen filtern")
        self.var_suche.trace_add("write", lambda *_: self._fuelle_ordner())
        self.tree_ordner = ttk.Treeview(links, columns=("ordner", "anzahl"), show="headings", selectmode="browse")
        self.tree_ordner.heading("ordner", text="Ordner", anchor="w")
        self.tree_ordner.heading("anzahl", text="Merkmale", anchor="e")
        self.tree_ordner.column("ordner", width=UIUtils.px(self, 260), anchor="w")
        self.tree_ordner.column("anzahl", width=UIUtils.px(self, 80), anchor="e", stretch=False)
        self.tree_ordner.pack(fill=tk.BOTH, expand=True)
        self.tree_ordner.bind("<<TreeviewSelect>>", lambda _e: self._ordner_gewaehlt())

        innen = ttk.Frame(rechts)
        innen.pack(fill=tk.BOTH, expand=True, padx=(rand, 0))
        rahmen_belege = ttk.Frame(innen)                  # Belege unten, die Merkmale bekommen den Rest
        rahmen_belege.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        ttk.Label(rahmen_belege, text="Belege (Dokumente des Ordners mit diesem Merkmal)").pack(anchor="w")
        self.tree_belege = ttk.Treeview(rahmen_belege, show="tree", height=6, selectmode="browse")
        self.tree_belege.pack(fill=tk.X, pady=(4, 0))
        self.tree_belege.bind("<Double-1>", lambda _e: self._beleg_zeigen())
        Tooltip(self.tree_belege, "Doppelklick zeigt das Dokument im Hauptfenster")

        kopf = ttk.Frame(innen)
        kopf.pack(fill=tk.X)
        self.lbl_ordner = ttk.Label(kopf, font=("", UIUtils.schriftgroesse(self, 1), "bold"))
        self.lbl_ordner.pack(side=tk.LEFT)
        self.btn_umschalten = ttk.Button(kopf, text="Ausschließen", command=self._umschalten, state=tk.DISABLED)
        self.btn_umschalten.pack(side=tk.RIGHT)
        Tooltip(self.btn_umschalten, "Das Merkmal zählt für diesen Ordner nicht mehr - Vollautomatik und "
                                     "Ablage-Vorschau beachten das ab ihrer nächsten Runde. Rückgängig mit "
                                     "„Wieder zulassen“.")
        spalten = (("art", "Art", 90), ("wert", "Merkmal", 220), ("n", "Dokumente", 80), ("zustand", "", 110))
        self.tree_merkmale = ttk.Treeview(innen, columns=[s[0] for s in spalten], show="headings", selectmode="browse")
        for spalte, text, breite in spalten:
            self.tree_merkmale.heading(spalte, text=text, anchor="e" if spalte == "n" else "w")
            self.tree_merkmale.column(spalte, width=UIUtils.px(self, breite), anchor="e" if spalte == "n" else "w",
                                      stretch=spalte == "wert")
        self.tree_merkmale.tag_configure("aus", foreground="gray50")
        self.tree_merkmale.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.tree_merkmale.bind("<<TreeviewSelect>>", lambda _e: self._merkmal_gewaehlt())

    # ---------------------------------------------------------------- Laden (Hintergrund)
    def _lade(self):
        self.status.config(text="Lese den Volltext der Sammlung…")

        def arbeit():
            try:
                with aktivitaet.phase("Wiki: Steckbriefe der Ablageordner…"):
                    ergebnis = lade_ansicht(self.app, self.wissen)
                fehler = None
            except Exception as e:                        # noqa: BLE001 - im Fenster sagen statt still leer
                ergebnis, fehler = None, type(e).__name__
            try:
                self.after(0, self._geladen, ergebnis, fehler)
            except (tk.TclError, RuntimeError):           # Fenster schon zu
                pass
        threading.Thread(target=arbeit, daemon=True).start()

    def _geladen(self, ergebnis, fehler):
        if not self.winfo_exists():
            return
        if fehler:
            self.status.config(text=f"Steckbriefe nicht lesbar ({fehler}).")
            self._log(f"Wiki: Steckbriefe nicht lesbar ({fehler})", "warning")
            return
        self.steckbriefe, self.dokumente = ergebnis
        self._fuelle_ordner()
        n_dokumente = sum(len(d) for d in self.dokumente.values())
        self.status.config(text=f"{len(self._ordner)} Ordner mit Merkmalen, gezählt aus {n_dokumente} Dokumenten "
                                "mit Text.")
        self._log(f"Wiki: Ablageordner geöffnet ({len(self._ordner)} Ordner mit Merkmalen)")

    # ---------------------------------------------------------------- Listen
    def _fuelle_ordner(self):
        if self.steckbriefe is None:
            return
        zeilen = ordner_zeilen(self.steckbriefe, self.var_suche.get())
        self._ordner = [z[0] for z in zeilen]
        self.tree_ordner.delete(*self.tree_ordner.get_children())
        for i, (ordner, gilt, aus) in enumerate(zeilen):
            self.tree_ordner.insert("", tk.END, iid=str(i), values=(ordner, f"{gilt} (+{aus} aus)" if aus else str(gilt)))
        self._zeige_ordner(None)

    def _gewaehlter_ordner(self):
        auswahl = self.tree_ordner.selection()
        return self._ordner[int(auswahl[0])] if auswahl else None

    def _ordner_gewaehlt(self):
        self._zeige_ordner(self._gewaehlter_ordner())

    def _zeige_ordner(self, ordner, waehle_merkmal=None):
        self.lbl_ordner.config(text=ordner or "")
        self.tree_merkmale.delete(*self.tree_merkmale.get_children())
        self._merkmale = []
        if ordner:
            for i, (art_text, wert, n, zustand, aus) in enumerate(merkmal_zeilen(self.steckbriefe, ordner)):
                self._merkmale.append((art_text, wert, aus))
                self.tree_merkmale.insert("", tk.END, iid=str(i), values=(art_text, wert, n, zustand),
                                          tags=("aus",) if aus else ())
                if waehle_merkmal == (art_text, wert):
                    self.tree_merkmale.selection_set(str(i))
        self._merkmal_gewaehlt()

    def _gewaehltes_merkmal(self):
        """(Art, Wert, ausgeschlossen) mit der Art wie in ordner_steckbrief, oder None."""
        auswahl = self.tree_merkmale.selection()
        if not auswahl:
            return None
        art_text, wert, aus = self._merkmale[int(auswahl[0])]
        art = next((a for a, t in ARTEN_TEXT.items() if t == art_text), art_text)
        return art, wert, aus

    def _merkmal_gewaehlt(self):
        merkmal = self._gewaehltes_merkmal()
        ordner = self._gewaehlter_ordner()
        self.tree_belege.delete(*self.tree_belege.get_children())
        self._belege = []
        if not merkmal or not ordner:
            self.btn_umschalten.config(state=tk.DISABLED, text="Ausschließen")
            return
        art, wert, aus = merkmal
        self.btn_umschalten.config(state=tk.NORMAL, text="Wieder zulassen" if aus else "Ausschließen")
        self._belege = ordner_steckbrief.belege(self.dokumente, ordner, art, wert)
        for i, rel in enumerate(self._belege):
            self.tree_belege.insert("", tk.END, iid=str(i), text=os.path.basename(rel))

    # ---------------------------------------------------------------- Aktionen
    def _umschalten(self):
        merkmal, ordner = self._gewaehltes_merkmal(), self._gewaehlter_ordner()
        if not merkmal or not ordner:
            return
        art, wert, aus = merkmal
        try:
            if aus:
                self.wissen.merkmal_zulassen(ordner, art, wert)
                self.steckbriefe.lasse_zu(ordner, art, wert)
            else:
                self.wissen.merkmal_ausschliessen(ordner, art, wert)
                self.steckbriefe.schliesse_aus(ordner, art, wert)
        except Exception as e:                            # noqa: BLE001 - Datei gesperrt o.ä.: sagen, nichts ändern
            mb.showerror("Ablageordner", f"Konnte das Wiki nicht speichern ({type(e).__name__}).", parent=self)
            return
        self._log("Wiki: Steckbrief-Merkmal " + ("wieder zugelassen" if aus else "ausgeschlossen"))
        # Nur die Zahl links nachziehen: die Liste neu zu füllen löste ein spätes <<TreeviewSelect>> aus, das die
        # Auswahl rechts wieder verwürfe
        zeile = next((z for z in ordner_zeilen(self.steckbriefe) if z[0] == ordner), None)
        auswahl = self.tree_ordner.selection()
        if zeile and auswahl:
            self.tree_ordner.set(auswahl[0], "anzahl", f"{zeile[1]} (+{zeile[2]} aus)" if zeile[2] else str(zeile[1]))
        self._zeige_ordner(ordner, waehle_merkmal=(ARTEN_TEXT.get(art, art), wert))

    def _beleg_zeigen(self):
        auswahl = self.tree_belege.selection()
        if not auswahl:
            return
        pfad = os.path.join(self.app.master_folder, self._belege[int(auswahl[0])])
        folder_manager = getattr(self.app, "folder_manager", None)
        if folder_manager is None or not folder_manager.zeige_dokument(pfad):
            mb.showinfo("Ablageordner", "Das Dokument ist in der Sammlung nicht (mehr) zu finden.", parent=self)

    def _log(self, text, stufe="info"):
        """Nur Zahlen, nie Merkmale oder Ordner (Datenschutz)."""
        logger = getattr(self.app, "logger", None)
        if logger is not None:
            getattr(logger, stufe)(text)
