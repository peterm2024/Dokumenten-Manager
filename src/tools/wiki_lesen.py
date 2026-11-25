"""
Wiki: Was hat die KI schon gelesen? (Etappe 12 W7b, FAHRPLAN, 25.11.2026)

Die Ordner der Sammlung mit der Zahl der Dokumente, der schon gelesenen und der offenen; „Weiterlesen“ öffnet das
KI-Lesefenster (tools/wiki_dinge.py) mit den nächsten offenen Dokumenten des markierten Ordners samt Unterordnern, die
neuesten zuerst, höchstens `wissen_ki.HOECHSTENS` je Lauf.

- Gelesen ist, was das Wiki sich gemerkt hat (`wissen.gelesene`): nach „Übernehmen“ (auch „Nichts davon übernehmen“)
  oder wenn es nichts zu übernehmen gab. Ein geschlossener, abgebrochener oder gescheiterter Lauf zählt nicht.
- Dokumente ohne erkannten Text stehen in einer eigenen Spalte, die KI bekommt sie nicht.
- Posteingang und Unsicher fehlen; importierte Mails kommen nur mit dem Haken „Mails einbeziehen“ dazu
  (Anhänge zählen als Dokumente).
- Was in diesem Wiki-Fenster schon einmal nicht ging (KI-Antwort unbrauchbar, keine Dokument-ID möglich), kommt zuletzt.

Der Stand kommt aus dem Index (`index_manager.lesestand`, Hintergrund-Thread, Antwort über ein Postfach). Ins Protokoll nur
Zahlen, nie Ordnernamen oder Titel.
"""
import os
import queue
import threading
import tkinter as tk
from tkinter import ttk

import wissen_ki
from ordner_finden import UNSICHER_ORDNER
from ui_utils import Tooltip, UIUtils

ALLE = "Ganze Sammlung"


def ordner_gehoert_dazu(ordner):
    """Liest das Wiki in diesem Ordner (relativ)? Nicht in Posteingang und Unsicher. Reine Funktion."""
    teile = ordner.replace("\\", "/").casefold().split("/")
    return not any(t == UNSICHER_ORDNER.casefold() or "posteingang" in t for t in teile)


def gehoert_dazu(dokument, mails):
    """Zählt dieses Dokument überhaupt mit? Reine Funktion."""
    return ordner_gehoert_dazu(os.path.dirname(dokument["rel_path"])) and (mails or not dokument["mail"])


def zustand(dokument, gelesen):
    """„gelesen“, „ohne_text“ oder „offen“. Reine Funktion. :param gelesen: wissen.Wissen.gelesene()"""
    if dokument["kid_id"] and dokument["kid_id"] in gelesen:
        return "gelesen"
    return "ohne_text" if dokument["zeichen"] is not None and dokument["zeichen"] < wissen_ki.MIN_TEXT else "offen"


def ordner_stand(dokumente, gelesen, mails=False):
    """{Ordner ("" = die Sammlung): {dokumente, gelesen, offen, ohne_text}}, je Ordner samt seinen Unterordnern,
    alphabetisch, jeder Ordner vor seinen Unterordnern. Reine Funktion."""
    stand = {}
    for d in dokumente:
        if not gehoert_dazu(d, mails):
            continue
        was, ordner = zustand(d, gelesen), os.path.dirname(d["rel_path"])
        while True:
            zeile = stand.setdefault(ordner, {"dokumente": 0, "gelesen": 0, "offen": 0, "ohne_text": 0})
            zeile["dokumente"] += 1
            zeile[was] += 1
            if not ordner:
                break
            ordner = os.path.dirname(ordner)
    return dict(sorted(stand.items(), key=lambda z: [t.casefold() for t in z[0].split(os.sep)]))


def offene(dokumente, ordner, gelesen, mails=False, zuletzt=()):
    """Die offenen Dokumente eines Ordners samt Unterordnern, die neuesten zuerst (ohne Datum am Ende); was in `zuletzt`
    (rel_paths) steht, hinter allem anderen. Reine Funktion."""
    vorne = ordner + os.sep if ordner else ""
    liste = [d for d in dokumente if d["rel_path"].startswith(vorne) and gehoert_dazu(d, mails)
             and zustand(d, gelesen) == "offen"]
    liste.sort(key=lambda d: d["rel_path"].casefold())
    liste.sort(key=lambda d: d["datum"], reverse=True)
    return sorted(liste, key=lambda d: d["rel_path"] in zuletzt)


class LesenFenster(tk.Toplevel):
    def __init__(self, wiki):
        super().__init__(wiki)
        self.withdraw()                                   # erst aufbauen, dann zeigen (FALLSTRICKE #90)
        UIUtils.werkzeugfenster(self, wiki, maximierbar=True)
        self.wiki, self.app, self.wissen = wiki, wiki.app, wiki.wissen
        self.title("Wiki - Dokumente lesen")
        self.dokumente, self.gelesen, self.stand = None, set(), {}   # None: der Stand wird noch geholt
        self._vorwahl = ""                                # diesen Ordner markieren, sobald der Stand da ist
        self._postfach, self._after = queue.Queue(), None
        self._baue()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.update_idletasks()
        UIUtils.position_near_mouse(self, UIUtils.px(self, 760), UIUtils.px(self, 560))
        self.deiconify()
        self.aktualisiere()

    # ---------------------------------------------------------------- Aufbau
    def _baue(self):
        rand = UIUtils.px(self, 10)
        unten = ttk.Frame(self)                           # Knopfleiste VOR dem dehnbaren Inhalt mit side=BOTTOM
        unten.pack(side=tk.BOTTOM, fill=tk.X, padx=rand, pady=(4, rand))
        ttk.Button(unten, text="Schließen", command=self.destroy).pack(side=tk.RIGHT)
        self.btn_weiter = ttk.Button(unten, text="Weiterlesen", command=self.weiterlesen, state=tk.DISABLED)
        self.btn_weiter.pack(side=tk.RIGHT, padx=6)
        Tooltip(self.btn_weiter, f"Die nächsten offenen Dokumente des markierten Ordners von der KI lesen lassen, die "
                                 f"neuesten zuerst, höchstens {wissen_ki.HOECHSTENS} auf einmal.")
        self.var_mails = tk.BooleanVar(value=False)
        chk = ttk.Checkbutton(unten, text="Mails einbeziehen", variable=self.var_mails, command=self._fuelle)
        chk.pack(side=tk.LEFT)
        Tooltip(chk, "Auch importierte Mails mitzählen und lesen. Ihre Anhänge zählen immer als Dokumente.")
        self.lbl_stand = ttk.Label(self, foreground="gray40")
        self.lbl_stand.pack(fill=tk.X, padx=rand, pady=(rand, 4))
        rahmen = ttk.Frame(self)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=rand)
        self.tree = ttk.Treeview(rahmen, columns=("dokumente", "gelesen", "offen", "ohne_text"), selectmode="browse")
        self.tree.heading("#0", text="Ordner", anchor="w")
        self.tree.column("#0", width=UIUtils.px(self, 340), anchor="w")
        for spalte, text in (("dokumente", "Dokumente"), ("gelesen", "gelesen"), ("offen", "offen"),
                             ("ohne_text", "ohne Text")):
            self.tree.heading(spalte, text=text, anchor="e")
            self.tree.column(spalte, width=UIUtils.px(self, 85), anchor="e", stretch=False)
        self.tree.tag_configure("fertig", foreground="gray55")
        rolle = ttk.Scrollbar(rahmen, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=rolle.set)
        rolle.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._knopf())

    # ---------------------------------------------------------------- Stand holen
    def aktualisiere(self):
        """Den Stand im Hintergrund neu holen (die Sammlung wird dabei mit dem Index abgeglichen)."""
        self.lbl_stand.config(text="Die Dokumente der Sammlung werden gezählt…")
        index, postfach = getattr(self.app, "index_manager", None), self._postfach    # kein self im Thread: Schlösse der
        # Nutzer das Fenster vorher, stürben seine Tk-Objekte dort (FALLSTRICKE #95)

        def arbeite():
            try:
                postfach.put(("stand", index.lesestand()))
            except Exception as e:                        # noqa: BLE001 - Index gesperrt/kaputt: sagen statt hängen
                postfach.put(("fehler", type(e).__name__))
        threading.Thread(target=arbeite, daemon=True).start()
        if self._after is None:
            self._hole()

    def _hole(self):
        self._after = None
        if not self.winfo_exists():
            return
        try:
            was, inhalt = self._postfach.get_nowait()
        except queue.Empty:
            self._after = self.after(100, self._hole)
            return
        if was == "fehler":
            self.lbl_stand.config(text=f"Der Index der Sammlung ist gerade nicht lesbar ({inhalt}).")
            return
        self.dokumente = inhalt
        self._fuelle()
        gesamt = self.stand.get("", {})
        self._log(f"Wiki: Lesestand ({gesamt.get('dokumente', 0)} Dokumente, {gesamt.get('gelesen', 0)} gelesen, "
                  f"{gesamt.get('offen', 0)} offen, {gesamt.get('ohne_text', 0)} ohne Text)")

    def zeige_ordner(self, ordner):
        """Diesen Ordner markieren (vom Rechtsklick im Hauptfenster) - gleich oder sobald der Stand da ist."""
        self._vorwahl = ordner
        if self.dokumente is not None:
            self.tree.selection_set(())                   # die bisherige Markierung gilt nicht mehr
            self._fuelle()

    def gelesen_gemeldet(self, ids, ohne_text=()):
        """Nach einem Lauf (vom Lesefenster): die Zahlen gleich nachziehen, ohne die Sammlung neu zu zählen.
        :param ids: {rel_path: Dokument-ID} der gelesenen Dokumente; ohne_text: rel_paths ohne erkannten Text"""
        for d in self.dokumente or ():
            d["kid_id"] = ids.get(d["rel_path"]) or d["kid_id"]
            if d["rel_path"] in ohne_text:
                d["zeichen"] = 0
        if self.dokumente is not None:
            self._fuelle()

    # ---------------------------------------------------------------- Liste
    def _fuelle(self):
        markiert, offen = self.ordner(), self._aufgeklappt()
        if markiert is None:
            markiert = self._vorwahl
        self.gelesen = self.wissen.gelesene()
        self.stand = ordner_stand(self.dokumente or (), self.gelesen, self.var_mails.get())
        self.tree.delete(*self.tree.get_children())
        for ordner, z in self.stand.items():
            # iid „o:<Ordner>“: der Ordnername allein könnte leer sein (die Sammlung)
            parent = f"o:{os.path.dirname(ordner)}" if ordner else ""
            self.tree.insert(parent, tk.END, iid=f"o:{ordner}", text=os.path.basename(ordner) or ALLE,
                             open=not ordner or ordner in offen, tags=() if z["offen"] else ("fertig",),
                             values=[z[s] or "–" for s in ("dokumente", "gelesen", "offen", "ohne_text")])
        z = self.stand.get("")
        text = ("Hier gibt es noch keine Dokumente zum Lesen." if z is None else
                f"{z['gelesen']} von {z['dokumente']} Dokumenten gelesen, {z['offen']} offen"
                + (f", {z['ohne_text']} ohne erkannten Text" if z["ohne_text"] else "") + ".")
        if markiert in self.stand:
            self.tree.see(f"o:{markiert}")
            self.tree.selection_set(f"o:{markiert}")
        elif markiert:                                    # nichts anderes markieren: „Weiterlesen“ läse sonst woanders
            text += f" Im Ordner „{os.path.basename(markiert)}“ gibt es nichts zu lesen (Mails nur mit dem Haken unten)."
        self.lbl_stand.config(text=text)
        self._knopf()

    def ordner(self):
        """Der markierte Ordner ("" = die ganze Sammlung) oder None."""
        markiert = self.tree.selection()
        return markiert[0][2:] if markiert else None

    def _aufgeklappt(self):
        def sammle(iid):
            for kind in self.tree.get_children(iid):
                if self.tree.item(kind, "open"):
                    yield kind[2:]
                yield from sammle(kind)
        return set(sammle(""))

    def _knopf(self):
        n = self.stand[self.ordner()]["offen"] if self.ordner() in self.stand else 0
        lauf = min(n, wissen_ki.HOECHSTENS)
        self.btn_weiter.config(text="Weiterlesen" if not n else f"Weiterlesen ({n})" if n == lauf else
                               f"Weiterlesen ({lauf} von {n})", state=tk.NORMAL if n else tk.DISABLED,
                               style="Accent.TButton" if n else "TButton")

    def weiterlesen(self):
        """Das KI-Lesefenster mit den nächsten offenen Dokumenten. Ist schon eins offen, kommt es nur nach vorn - ein
        neuer Lauf würfe dessen Ergebnis weg."""
        dinge = self.wiki.dinge
        if dinge is not None and dinge.winfo_exists():
            dinge.lift()
            return
        if self.ordner() is None:
            return
        liste = offene(self.dokumente or (), self.ordner(), self.gelesen, self.var_mails.get(),
                       self.wiki.zuletzt_lesen)[:wissen_ki.HOECHSTENS]
        self.wiki.dinge_lesen([{"rel_path": d["rel_path"], "titel": d["titel"]} for d in liste])

    def destroy(self):
        if self._after is not None:                       # sonst feuert das Abholen nach dem Schließen ins Leere
            self.after_cancel(self._after)
            self._after = None
        super().destroy()

    def _log(self, text):
        logger = getattr(self.app, "logger", None)
        if logger is not None:
            logger.info(text)
