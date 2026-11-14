"""
Wiki von Hand, Bauschritt 2 (KONZEPT_WIKI_VON_HAND.md, 09.11.2026): Belege für einen Wiki-Eintrag suchen und anhaken.

Fenster „Belege suchen: <Eintrag>“, geöffnet aus dem Wiki-Fenster. Die Suche ist dieselbe wie im Hauptfenster
(`SearchManager.execute_search`: mehrere Wörter = UND, Unschärfe, Platzhalter, Anführungszeichen, Dokument-ID), mit zwei
eigenen Schaltern: „auch im Inhalt“ gehört zu diesem Fenster (nicht zum Hauptfenster), und ausgeblendete Mails werden
immer mitgesucht - auch eine Mail kann etwas belegen. Der Papierkorb bleibt draußen.

Treffer bekommen ein Kästchen; die Häkchen bleiben über mehrere Suchen stehen (wie beim Mail-Import). Rechts zeigt die
Vorschau Titel, Datum, Ordner und die Textzeilen mit den Suchwörtern; ein Doppelklick zeigt das Dokument im Hauptfenster.
„Als Belege übernehmen“ trägt die angehakten Dokumente über ihre Dokument-ID beim Eintrag ein (WikiFenster.belege_eintragen).
Schon eingetragene Belege stehen grau mit „schon Beleg“ in der Liste und lassen sich nicht anhaken. Der Knopf „von der
KI lesen lassen“ (Bauschritt 3) ist mit den festen Feldern entfallen (12.11.2026); die KI kommt mit Schritt N3 des neuen
Aufbaus zurück. Ins Protokoll nur Zahlen.
"""
import os
import tkinter as tk
import tkinter.messagebox as mb
from tkinter import ttk

import app_paths
import suchsyntax
from search_manager import SearchManager
from ui_utils import Tooltip, UIUtils

HAKEN, OHNE_HAKEN = "☑", "☐"
FUNDSTELLEN = 6                                           # höchstens so viele Textzeilen in der Vorschau
ZEILE_MAX = 160


class _Schalter:
    """Fester Wert mit .get() - an Stelle einer Tk-Variablen des Hauptfensters."""
    def __init__(self, wert):
        self._wert = wert

    def get(self):
        return self._wert


class _SuchApp:
    """Das Hauptfenster aus Sicht der Suche, mit den Schaltern DIESES Fensters: „auch im Inhalt“ von hier, Mails nie
    ausgeblendet. Alles andere (Index, Einstellungen, Protokoll) kommt vom echten Hauptfenster."""
    def __init__(self, app, inhalt):
        self._app = app
        self.use_ocr_var = _Schalter(bool(inhalt))
        self.mails_ausblenden_var = None

    def __getattr__(self, name):
        return getattr(self._app, name)


def suche(app, text, inhalt=True):
    """Treffer wie in der Dokumentsuche des Hauptfensters, neueste zuerst, ohne Papierkorb:
    Liste von Dicts rel_path, datum (TT.MM.JJJJ), titel, ordner. Leerer Suchtext = keine Treffer."""
    if not (text or "").strip() or not getattr(app, "master_folder", None):
        return []
    zeilen = SearchManager(_SuchApp(app, inhalt)).execute_search(app.master_folder, text, "", "", [])
    treffer = []
    for z in zeilen:
        rel = z[4]
        if app_paths.is_trash_path(rel, app.master_folder):
            continue
        treffer.append({"rel_path": rel, "datum": z[0], "titel": z[1], "ordner": os.path.dirname(rel)})
    return treffer


def fundstellen(text, suchtext, hoechstens=FUNDSTELLEN):
    """Die ersten Textzeilen, in denen ein Suchwort wörtlich vorkommt (gekürzt). Platzhalter und Anführungszeichen
    fallen weg; Treffer über die Unschärfe tauchen hier nicht auf - dann bleibt die Liste leer."""
    begriffe = [b.strip('"').replace("*", "").replace("?", "") for b in suchsyntax.split_terms(suchtext)]
    begriffe = [b for b in begriffe if len(b) >= 2]
    if not begriffe or not text:
        return []
    gefunden = []
    for zeile in text.splitlines():
        zeile = " ".join(zeile.split())
        if zeile and any(b in zeile.lower() for b in begriffe):
            gefunden.append(zeile if len(zeile) <= ZEILE_MAX else zeile[:ZEILE_MAX - 1] + "…")
            if len(gefunden) >= hoechstens:
                break
    return gefunden


class BelegSuche(tk.Toplevel):
    """Suchfenster zu EINEM gespeicherten Eintrag des Wiki-Fensters `wiki` (WikiFenster)."""

    def __init__(self, wiki, eintrag):
        super().__init__(wiki)
        self.withdraw()                                   # erst aufbauen, dann zeigen (FALLSTRICKE #90)
        UIUtils.werkzeugfenster(self, wiki)               # über dem Wiki-Fenster, nicht modal
        self.wiki = wiki
        self.app = wiki.app
        self.eintrag_id = eintrag["id"]
        self.title(f"Belege suchen: {eintrag['bezeichnung']}")
        self.angehakt = set()                             # rel_paths, über mehrere Suchen
        self.titel = {}                                   # rel_path → Titel, auch für Häkchen aus früheren Suchen
        self.treffer = {}                                 # rel_path → Treffer-Dict der letzten Suche
        self.suchtext = ""
        self._baue()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.update_idletasks()
        UIUtils.position_near_mouse(self, UIUtils.px(self, 940), UIUtils.px(self, 600))
        self.ent_suche.insert(0, eintrag["bezeichnung"])
        self.deiconify()
        self.ent_suche.focus_set()
        self.ent_suche.select_range(0, tk.END)

    # ---------------------------------------------------------------- Aufbau
    def _baue(self):
        rand = UIUtils.px(self, 10)
        unten = ttk.Frame(self)                           # Knopfleiste VOR dem dehnbaren Inhalt mit side=BOTTOM
        unten.pack(side=tk.BOTTOM, fill=tk.X, padx=rand, pady=(4, rand))
        ttk.Button(unten, text="Schließen", command=self.destroy).pack(side=tk.RIGHT)
        self.btn_uebernehmen = ttk.Button(unten, command=self._uebernehmen)
        self.btn_uebernehmen.pack(side=tk.RIGHT, padx=6)
        self.btn_keine = ttk.Button(unten, text="Keine", command=self._keine)
        self.btn_keine.pack(side=tk.LEFT)
        Tooltip(self.btn_keine, "Alle Häkchen entfernen, auch die aus früheren Suchen")
        self.lbl_status = ttk.Label(unten, foreground="gray40")
        self.lbl_status.pack(side=tk.LEFT, padx=8)

        oben = ttk.Frame(self)
        oben.pack(fill=tk.X, padx=rand, pady=(rand, 4))
        ttk.Label(oben, text="Suchen:").pack(side=tk.LEFT)
        self.ent_suche = ttk.Entry(oben)
        self.ent_suche.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.ent_suche.bind("<Return>", lambda _e: self._suche())
        Tooltip(self.ent_suche, "Wie die Suche im Hauptfenster: mehrere Wörter müssen alle vorkommen, kleine Tippfehler "
                                "werden toleriert, \"in Anführungszeichen\" genau, * und ? als Platzhalter.")
        self.var_inhalt = tk.BooleanVar(value=True)
        ttk.Checkbutton(oben, text="auch im Inhalt", variable=self.var_inhalt).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(oben, text="Suchen", command=self._suche).pack(side=tk.LEFT)
        self.lbl_treffer = ttk.Label(self, foreground="gray40")
        self.lbl_treffer.pack(fill=tk.X, padx=rand)

        teiler = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        teiler.pack(fill=tk.BOTH, expand=True, padx=rand, pady=(4, 0))
        links = ttk.Frame(teiler)
        rechts = ttk.Frame(teiler)
        teiler.add(links, weight=3)
        teiler.add(rechts, weight=2)
        self.tree = ttk.Treeview(links, columns=("haken", "datum", "titel", "ordner"), show="headings",
                                 selectmode="extended")
        for spalte, titel, breite, dehnen in (("haken", "", 30, False), ("datum", "Datum", 90, False),
                                              ("titel", "Titel", 260, True), ("ordner", "Ordner", 180, True)):
            self.tree.heading(spalte, text=titel)
            self.tree.column(spalte, width=UIUtils.px(self, breite), stretch=dehnen,
                             anchor="center" if spalte == "haken" else "w")
        self.tree.tag_configure("beleg", foreground="gray50")
        rollen = ttk.Scrollbar(links, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=rollen.set)
        rollen.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Button-1>", self._klick)
        self.tree.bind("<space>", lambda _e: (self._schalte_markierte(), "break")[1])
        self.tree.bind("<Double-1>", lambda _e: self._zeigen())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._vorschau())
        self.txt_vorschau = tk.Text(rechts, wrap="word", height=10, state=tk.DISABLED, relief=tk.FLAT,
                                    padx=UIUtils.px(self, 6), pady=UIUtils.px(self, 4))
        self.txt_vorschau.pack(fill=tk.BOTH, expand=True, padx=(6, 0))
        self._summe()
        self._zeige_text("Suchwörter eingeben und Enter drücken. Ein Klick ins Kästchen hakt ein Dokument an, ein "
                         "Doppelklick zeigt es im Hauptfenster.")

    # ---------------------------------------------------------------- Suche
    def _schon_belegt(self):
        """rel_paths der Dokumente, die schon Beleg dieses Eintrags sind (über die Dokument-ID)."""
        e = self.wiki.wissen.lade(self.eintrag_id)
        index = getattr(self.app, "index_manager", None)
        if e is None or index is None:
            return set()
        return {rel for rel in (index.pfad_zur_kid_id(b["kid_id"]) for b in e["belege"]) if rel}

    def _suche(self):
        self.suchtext = self.ent_suche.get().strip()
        if not self.suchtext:
            return
        self.config(cursor="watch")
        self.update_idletasks()
        try:
            treffer = suche(self.app, self.suchtext, self.var_inhalt.get())
        except Exception as e:                            # noqa: BLE001 - Index gesperrt o. ä.: sagen, Fenster bleibt
            self._log(f"Wiki-Suche: Fehler ({type(e).__name__})", "warning")
            mb.showwarning("Belege suchen", f"Die Suche ist fehlgeschlagen:\n{e}", parent=self)
            return
        finally:
            self.config(cursor="")
        belegt = self._schon_belegt()
        self.treffer = {t["rel_path"]: t for t in treffer}
        self.tree.delete(*self.tree.get_children())
        for t in treffer:
            schon = t["rel_path"] in belegt
            haken = "" if schon else (HAKEN if t["rel_path"] in self.angehakt else OHNE_HAKEN)
            self.tree.insert("", tk.END, iid=t["rel_path"], tags=("beleg",) if schon else (),
                             values=(haken, t["datum"], t["titel"] + ("  (schon Beleg)" if schon else ""), t["ordner"]))
        anzahl = len(treffer)
        text = "Kein Treffer." if not anzahl else f"{anzahl} Treffer" + (f", davon {len(belegt & set(self.treffer))} "
                                                                           "schon Beleg" if belegt & set(self.treffer)
                                                                           else "")
        if not self.var_inhalt.get():
            text += " (nur Titel, Tags und Dateiname)"
        self.lbl_treffer.config(text=text)
        self._log(f"Wiki-Suche: {anzahl} Treffer")
        self._zeige_text("Eine Zeile anklicken: hier stehen dann die Stellen mit den Suchwörtern." if anzahl else
                         "Andere Wörter versuchen - oder „auch im Inhalt“ einschalten.")

    # ---------------------------------------------------------------- Häkchen
    def _schalte(self, rel, an=None):
        if not self.tree.exists(rel) or "beleg" in self.tree.item(rel, "tags"):
            return
        an = (rel not in self.angehakt) if an is None else an
        (self.angehakt.add if an else self.angehakt.discard)(rel)
        if an and rel in self.treffer:
            self.titel[rel] = self.treffer[rel]["titel"]
        self.tree.set(rel, "haken", HAKEN if an else OHNE_HAKEN)

    def _klick(self, event):
        """Klick ins Kästchen hakt an, ohne die Markierung zu ändern; sonst markiert der Klick wie gewohnt."""
        zeile = self.tree.identify_row(event.y)
        if zeile and self.tree.identify_column(event.x) == "#1":
            self._schalte(zeile)
            self._summe()
            return "break"
        return None

    def _schalte_markierte(self):
        """Leertaste: fehlt einer markierten Zeile das Häkchen, bekommen alle eins, sonst gehen alle weg."""
        zeilen = [z for z in self.tree.selection() if "beleg" not in self.tree.item(z, "tags")]
        an = any(z not in self.angehakt for z in zeilen)
        for z in zeilen:
            self._schalte(z, an)
        self._summe()

    def _keine(self):
        for rel in list(self.angehakt):
            self._schalte(rel, False)
        self.angehakt.clear()
        self._summe()

    def _summe(self):
        n = len(self.angehakt)
        self.btn_uebernehmen.config(text=f"{n} Dokument{'' if n == 1 else 'e'} als Belege übernehmen",
                                    state=tk.NORMAL if n else tk.DISABLED, style="Accent.TButton" if n else "TButton")
        sichtbar = sum(1 for rel in self.angehakt if self.tree.exists(rel))
        self.lbl_status.config(text=f"{n - sichtbar} angehakt aus früheren Suchen" if n > sichtbar else "")

    # ---------------------------------------------------------------- Vorschau
    def _zeige_text(self, text):
        self.txt_vorschau.config(state=tk.NORMAL)
        self.txt_vorschau.delete("1.0", tk.END)
        self.txt_vorschau.insert("1.0", text)
        self.txt_vorschau.config(state=tk.DISABLED)

    def _vorschau(self):
        auswahl = self.tree.selection()
        t = self.treffer.get(auswahl[0]) if auswahl else None
        if t is None:
            return
        index = getattr(self.app, "index_manager", None)
        try:
            text = index.wiki_text(t["rel_path"])[0] if index else ""
        except Exception:                                 # noqa: BLE001 - ohne Text trotzdem Titel und Ordner zeigen
            text = ""
        zeilen = fundstellen(text, self.suchtext)
        teile = [t["titel"], f"{t['datum']} · {t['ordner'] or 'Hauptordner'}", ""]
        if zeilen:
            teile += ["Stellen mit den Suchwörtern:"] + [f"• {z}" for z in zeilen]
        elif text:
            teile.append("Die Suchwörter stehen im Titel, in den Tags oder in ähnlicher Schreibweise im Text.")
        else:
            teile.append("Für dieses Dokument ist noch kein Text erkannt.")
        teile += ["", "Doppelklick zeigt das Dokument im Hauptfenster."]
        self._zeige_text("\n".join(teile))

    def _zeigen(self):
        auswahl = self.tree.selection()
        folder_manager = getattr(self.app, "folder_manager", None)
        if auswahl and folder_manager is not None:
            folder_manager.zeige_dokument(os.path.join(self.app.master_folder, auswahl[0]))

    # ---------------------------------------------------------------- Übernehmen
    def _uebernehmen(self):
        if not self.angehakt:
            return
        pfade = [os.path.join(self.app.master_folder, rel) for rel in sorted(self.angehakt)]
        neu = self.wiki.belege_eintragen(self.eintrag_id, pfade, parent=self)
        if neu is None:                                   # Eintrag inzwischen weg
            self.destroy()
            return
        self.angehakt.clear()
        self.aktualisiere()                               # zeigt die neuen Belege als „schon Beleg“
        self._summe()
        self.lbl_status.config(text=f"{neu} Beleg{'' if neu == 1 else 'e'} hinzugefügt")

    def aktualisiere(self):
        """Die letzte Suche noch einmal (nach neuen Belegen: zeigt sie als „schon Beleg“)."""
        if self.suchtext:
            self.ent_suche.delete(0, tk.END)
            self.ent_suche.insert(0, self.suchtext)
            self._suche()
            self._summe()

    def _log(self, text, stufe="info"):
        """Nur Zahlen, nie Suchwörter oder Titel (Datenschutz)."""
        logger = getattr(self.app, "logger", None)
        if logger is not None:
            getattr(logger, stufe)(text)
