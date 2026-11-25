"""
Wiki: Übersicht je Schublade (Etappe 12 W5, KONZEPT_WIKI_VON_HAND.md „Umbau: Angaben als ‚Merkmal: Wert‘“, 23.11.2026).
Die Einträge einer Schublade als Zeilen, ihre Merkmale als Spalten, in jeder Zelle der jüngste Wert - etwa alle
Versicherungen mit Nummer und Beitrag auf einen Blick.

Gezeigt werden die häufigsten Merkmale (`SPALTEN_START`), „Spalten“ blendet weitere ein oder aus; die Wahl merkt sich
das Wiki je Schublade (`wissen.uebersicht_spalten`, Peter 23.11.2026). Doppelklick auf einen Wert zeigt das Dokument, aus dem er stammt, sonst
(Bezeichnung, leere Zelle, von Hand eingetragen) den Eintrag im Wiki-Fenster; Rechtsklick bietet beides und „Wert
kopieren“. Außer der Spaltenwahl liest das Fenster nur. Geöffnet aus dem Wiki-Fenster („Übersicht…“), nicht modal, höchstens eines; bekommt es
den Fokus, liest es neu - Änderungen im Wiki sind dann da. Ins Protokoll nur Zahlen, nie Bezeichnungen oder Werte.
"""
import collections
import os
import tkinter as tk
import tkinter.messagebox as mb
from tkinter import ttk

import wissen
from ui_utils import Tooltip, UIUtils

SPALTEN_START = 6                         # so viele Merkmale zeigt die Übersicht ohne eigene Wahl


def merkmale_der_schublade(eintraege):
    """[(Schlüssel, Schreibweise, Zahl der Einträge)] - die Merkmale der Einträge, die häufigsten zuerst, bei gleicher
    Zahl in der Reihenfolge ihres Auftretens. Freie Zeilen ohne Merkmal zählen nicht. Reine Funktion.
    :param eintraege: wissen.Wissen.eintraege_mit_angaben"""
    zahl, schreibweise = collections.Counter(), {}
    for e in eintraege:
        eigene = {}                                       # je Eintrag zählt ein Merkmal einmal
        for a in e["angaben"]:
            if wissen.merkmal_kern(a["merkmal"]):
                eigene.setdefault(wissen.merkmal_kern(a["merkmal"]), a["merkmal"])
        for schluessel, merkmal in eigene.items():
            zahl[schluessel] += 1
            schreibweise.setdefault(schluessel, merkmal)
    reihe = list(schreibweise)
    return [(s, schreibweise[s], zahl[s]) for s in sorted(reihe, key=lambda s: (-zahl[s], reihe.index(s)))]


def start_spalten(merkmale):
    """Schlüssel der Spalten ohne eigene Wahl: die häufigsten."""
    return [s for s, _name, _n in merkmale[:SPALTEN_START]]


def zeilen(eintraege):
    """[{id, bezeichnung, zellen: {Schlüssel: Angabe}}] - je Merkmal die Angabe mit dem jüngsten Wert (`aktuell`).
    Reine Funktion."""
    return [{"id": e["id"], "bezeichnung": e["bezeichnung"],
             "zellen": {wissen.merkmal_kern(a["merkmal"]): a for a in e["angaben"] if a["merkmal"] and a["aktuell"]}}
            for e in eintraege]


class UebersichtFenster(tk.Toplevel):
    def __init__(self, wiki):
        super().__init__(wiki)
        self.withdraw()                                   # erst aufbauen, dann zeigen (FALLSTRICKE #90)
        UIUtils.werkzeugfenster(self, wiki, maximierbar=True)
        self.wiki, self.app, self.wissen = wiki, wiki.app, wiki.wissen
        self.title("Wiki - Übersicht")
        self.arten, self.zeilen, self.merkmale = [], [], []
        self._haken = {}                                  # Schlüssel → BooleanVar des Spaltenmenüs
        self._baue()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<FocusIn>", lambda e: self.aktualisiere() if e.widget is self else None)
        self.update_idletasks()
        UIUtils.position_near_mouse(self, UIUtils.px(self, 1120), UIUtils.px(self, 520))
        self.aktualisiere(self._start_schublade())
        self.deiconify()
        self._log(f"Wiki: Übersicht geöffnet ({len(self.zeilen)} Einträge, {len(self.merkmale)} Merkmale)")

    # ---------------------------------------------------------------- Aufbau
    def _baue(self):
        rand = UIUtils.px(self, 10)
        unten = ttk.Frame(self)                           # Knopfleiste VOR dem dehnbaren Inhalt mit side=BOTTOM
        unten.pack(side=tk.BOTTOM, fill=tk.X, padx=rand, pady=(4, rand))
        ttk.Button(unten, text="Schließen", command=self.destroy).pack(side=tk.RIGHT)
        self.lbl_stand = ttk.Label(unten, foreground="gray40")
        self.lbl_stand.pack(side=tk.LEFT)

        oben = ttk.Frame(self)
        oben.pack(fill=tk.X, padx=rand, pady=(rand, 4))
        ttk.Label(oben, text="Schublade:").pack(side=tk.LEFT)
        self.cmb_art = ttk.Combobox(oben, state="readonly", width=34)
        self.cmb_art.pack(side=tk.LEFT, padx=6)
        self.cmb_art.bind("<<ComboboxSelected>>", lambda _e: self._fuelle())
        self.cmb_art.bind("<MouseWheel>", lambda _e: "break")          # das Rad stellt nichts um (FALLSTRICKE #133)
        self.btn_spalten = ttk.Menubutton(oben, text="Spalten")
        self.btn_spalten.pack(side=tk.LEFT)
        self.menue_spalten = tk.Menu(self.btn_spalten, tearoff=0)
        self.btn_spalten.configure(menu=self.menue_spalten)
        Tooltip(self.btn_spalten, "Welche Merkmale als Spalten gezeigt werden. Ohne Auswahl sind es die häufigsten; die "
                                  "Zahl dahinter sagt, bei wie vielen Einträgen es das Merkmal gibt.")

        rahmen = ttk.Frame(self)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=rand)
        self.tree = ttk.Treeview(rahmen, show="headings", selectmode="browse")
        rolle = ttk.Scrollbar(rahmen, orient=tk.VERTICAL, command=self.tree.yview)
        quer = ttk.Scrollbar(rahmen, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=rolle.set, xscrollcommand=quer.set)
        rolle.pack(side=tk.RIGHT, fill=tk.Y)
        quer.pack(side=tk.BOTTOM, fill=tk.X)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self._doppelklick)
        self.tree.bind("<Button-3>", self._menue)
        Tooltip(self.tree, "Doppelklick auf einen Wert zeigt das Dokument, auf eine Bezeichnung den Eintrag")

    def _start_schublade(self):
        """Die Schublade des im Wiki gezeigten Eintrags, sonst die mit den meisten Einträgen (Id oder None)."""
        if self.wiki.eintrag:
            return self.wiki.eintrag["art"]
        arten = [a for a in self.wissen.arten() if a["anzahl"]]
        return max(arten, key=lambda a: a["anzahl"])["id"] if arten else None

    # ---------------------------------------------------------------- Inhalt
    def schublade(self):
        """Id der gewählten Schublade oder None."""
        i = self.cmb_art.current()
        return self.arten[i]["id"] if 0 <= i < len(self.arten) else None

    def aktualisiere(self, art=None):
        """Schubladen mit Einträgen und ihren Inhalt neu lesen; die gewählte (oder `art`) bleibt gewählt."""
        art = art if art is not None else self.schublade()
        self.arten = [a for a in self.wissen.arten() if a["anzahl"]]
        self.cmb_art.configure(values=[f"{a['name']} ({a['anzahl']})" for a in self.arten])
        ids = [a["id"] for a in self.arten]
        if self.arten:
            self.cmb_art.current(ids.index(art) if art in ids else 0)
        else:
            self.cmb_art.set("")
        self._fuelle()

    def spalten(self):
        """Schlüssel der gezeigten Merkmale: die Wahl für diese Schublade (was es noch gibt), sonst die häufigsten."""
        wahl = self.wissen.uebersicht_spalten(self.schublade()) if self.schublade() is not None else None
        if wahl is None:
            return start_spalten(self.merkmale)
        return [s for s, _name, _n in self.merkmale if s in wahl]

    def _fuelle(self):
        art = self.schublade()
        eintraege = self.wissen.eintraege_mit_angaben(art) if art is not None else []
        self.merkmale, self.zeilen = merkmale_der_schublade(eintraege), zeilen(eintraege)
        self._fuelle_menue()
        self._zeichne()

    def _fuelle_menue(self):
        self.menue_spalten.delete(0, "end")
        gezeigt = set(self.spalten())
        self._haken = {}
        for schluessel, name, n in self.merkmale:
            var = self._haken[schluessel] = tk.BooleanVar(self, value=schluessel in gezeigt)
            self.menue_spalten.add_checkbutton(label=f"{name} ({n})", variable=var, command=self._spalten_gewaehlt)
        if self.merkmale:
            self.menue_spalten.add_separator()
            self.menue_spalten.add_command(label="Die häufigsten zeigen", command=self._spalten_zurueck)
        self.btn_spalten.configure(state=tk.NORMAL if self.merkmale else tk.DISABLED)

    def _spalten_gewaehlt(self):
        self.wissen.setze_uebersicht_spalten(self.schublade(), [s for s, var in self._haken.items() if var.get()])
        self._zeichne()

    def _spalten_zurueck(self):
        self.wissen.setze_uebersicht_spalten(self.schublade(), None)
        self._fuelle_menue()
        self._zeichne()

    def _zeichne(self):
        markiert = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        namen = {s: name for s, name, _n in self.merkmale}
        gezeigt = self.spalten()
        self.tree.configure(columns=["bezeichnung"] + [f"m:{s}" for s in gezeigt])
        for spalte, titel, breite in [("bezeichnung", "Eintrag", 230)] + [(f"m:{s}", namen[s], 140) for s in gezeigt]:
            self.tree.heading(spalte, text=titel, anchor="w")
            self.tree.column(spalte, width=UIUtils.px(self, breite), minwidth=UIUtils.px(self, 60), anchor="w",
                             stretch=True)
        for z in self.zeilen:
            self.tree.insert("", tk.END, iid=f"e:{z['id']}", values=[z["bezeichnung"]] + [
                z["zellen"][s]["wert"] if s in z["zellen"] else "" for s in gezeigt])
        if markiert and self.tree.exists(markiert[0]):
            self.tree.selection_set(markiert[0])
        n, m = len(self.zeilen), len(self.merkmale)
        self.lbl_stand.config(text=f"{n} Eintr{'ag' if n == 1 else 'äge'}, {len(gezeigt)} von {m} Merkmalen gezeigt" if n
                              else "Noch keine Einträge im Wiki.")

    # ---------------------------------------------------------------- Zellen
    def _zelle(self, event):
        """(Eintrags-Id, Schlüssel des Merkmals oder None) unter der Maus, None daneben."""
        zeile, spalte = self.tree.identify_row(event.y), self.tree.identify_column(event.x)
        if not zeile or not spalte:
            return None
        name = str(self.tree.column(spalte, "id"))
        return int(zeile[2:]), (name[2:] if name.startswith("m:") else None)

    def angabe(self, eintrag_id, schluessel):
        """Die Angabe in dieser Zelle oder None."""
        z = next((z for z in self.zeilen if z["id"] == eintrag_id), None)
        return z["zellen"].get(schluessel) if z and schluessel else None

    def oeffne(self, eintrag_id, schluessel=None):
        """Doppelklick: das Dokument des Werts, sonst den Eintrag."""
        angabe = self.angabe(eintrag_id, schluessel)
        if angabe and angabe["kid_id"]:
            self._zeige_dokument(angabe)
        else:
            self.wiki.zeige_eintrag(eintrag_id)

    def _doppelklick(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":       # Spaltenkopf oder Trennlinie
            return
        zelle = self._zelle(event)
        if zelle:
            self.oeffne(*zelle)

    def _zeige_dokument(self, angabe):
        index, ordner = getattr(self.app, "index_manager", None), getattr(self.app, "folder_manager", None)
        rel = index.pfad_zur_kid_id(angabe["kid_id"]) if index else None
        if not rel or ordner is None or not ordner.zeige_dokument(os.path.join(self.app.master_folder, rel)):
            mb.showinfo("Wiki", "Das Dokument ist in der Sammlung nicht (mehr) zu finden. Liegt es im Papierkorb?",
                        parent=self)

    def _kopiere(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    def baue_menue(self, eintrag_id, schluessel):
        """Rechtsklick-Menü einer Zelle (zum Testen getrennt vom Aufklappen)."""
        angabe = self.angabe(eintrag_id, schluessel)
        menue = tk.Menu(self, tearoff=0)
        menue.add_command(label="Eintrag zeigen", command=lambda: self.wiki.zeige_eintrag(eintrag_id))
        menue.add_command(label="Dokument zeigen", command=lambda: self._zeige_dokument(angabe),
                          state=tk.NORMAL if angabe and angabe["kid_id"] else tk.DISABLED)
        menue.add_command(label="Wert kopieren", command=lambda: self._kopiere(angabe["wert"]),
                          state=tk.NORMAL if angabe else tk.DISABLED)
        return menue

    def _menue(self, event):
        zelle = self._zelle(event)
        if zelle:
            self.tree.selection_set(f"e:{zelle[0]}")
            self.baue_menue(*zelle).tk_popup(event.x_root, event.y_root)

    def _log(self, text):
        """Nur Zahlen, nie Bezeichnungen oder Werte (Datenschutz)."""
        logger = getattr(self.app, "logger", None)
        if logger is not None:
            logger.info(text)
