"""
Wiki von Hand (KONZEPT_WIKI_VON_HAND.md, „Neuer Aufbau: freie Angaben statt fester Felder“, Schritt N2, 12.11.2026):
Fenster für die bestätigte Wissensbasis der Sammlung (wissen.py).

Links die Einträge in ihren Schubladen mit Suchfeld (leere Schubladen erscheinen nicht). Gesucht wird seit 13.11.2026
in Bezeichnung, Notiz und Angaben (`wissen.passt`, Nummern auch mit anderen Trennzeichen); die getroffenen Angaben
sind beim Öffnen des Eintrags markiert (`wissen.fundstellen`). Rechts der gewählte Eintrag:
- Bezeichnung, Schublade und Notiz - das Formular, gespeichert mit „Speichern“. Die Schublade ist ein Eingabefeld mit
  Auswahl: ein neuer Name legt nach Rückfrage eine neue Schublade an („auf Zuruf“). „Schubladen…“ daneben öffnet das
  Fenster zum Umbenennen, Zusammenlegen und Löschen (Schritt N4, tools/wiki_schubladen.py).
- „Zusammenlegen mit…“ unten: Ein anderer Eintrag meint dasselbe und geht im gezeigten auf
  (`wissen.eintraege_zusammenlegen`, nach Rückfrage).
- Angaben: kurze freie Zeilen. Aus einem Dokument tragen sie Titel und Zitat (unter der Liste zu lesen), von Hand
  eingetragene nicht. Hinzufügen, Ändern und Entfernen wirken sofort.
- Verbunden mit: andere Einträge; Doppelklick springt dorthin.
- Belege: Dokumente der Sammlung (über ihre Dokument-ID, sie bleiben nach Verschieben und Umbenennen gültig) - im
  Hauptfenster markierte oder über „Dokumente suchen…“ gefundene (tools/wiki_suche.py). Doppelklick zeigt das Dokument.

Rechtsklick in der Dokumentenliste (FAHRPLAN Etappe 6b): Untermenü „🛠 Wiki“ mit den Einträgen, in denen die markierten
Dokumente Beleg sind (öffnet sie hier), „Neuer Eintrag aus dem Dokument“ (beim Speichern werden sie Belege) und „Zu
Eintrag hinzufügen“. Inhalt als reine Liste in `wiki_menue`.

KI (Schritt N3): „Von der KI lesen lassen…“ - im Rechtsklick für die markierten Dokumente, bei den Belegen für die
Belege des Eintrags - öffnet das Fenster „Aus dem Dokument“ (tools/wiki_dinge.py): Die KI listet auf, wer und was in
den Dokumenten vorkommt, der Mensch hakt an. Ins Protokoll nur Zahlen.
"""
import collections
import os
import tkinter as tk
import tkinter.messagebox as mb
import tkinter.simpledialog as simpledialog
from tkinter import ttk

import app_paths
import wissen
from pdf_handler import PDFHandler
from tools.base_tool import BaseTool, ToolContext
from tools.wiki_dinge import DingeFenster, dokumente_aus_belegen
from tools.wiki_schubladen import SchubladenFenster
from tools.wiki_suche import BelegSuche
from ui_utils import Tooltip, UIUtils

KID_IDS_HOECHSTENS = 50                                   # so viele markierte Dokumente liest der Rechtsklick an


def markierte_pdfs(app):
    """Absolute Pfade der im Hauptfenster markierten PDFs (wie ToolManager beim Öffnen eines Werkzeugs)."""
    tree = getattr(app, "tree_files", None)
    if tree is None:
        return []
    pfade = []
    for iid in tree.selection():
        werte = tree.item(iid, "values")
        if len(werte) > 4 and str(werte[4]).lower().endswith(".pdf"):
            pfade.append(os.path.join(app.master_folder, werte[4]))
    return pfade


def dokument_titel(pfad):
    """Titel aus den PDF-Metadaten, sonst der Dateiname ohne Endung."""
    return (PDFHandler.get_metadata(pfad).get("title") or "").strip() or os.path.splitext(os.path.basename(pfad))[0]


def wiki_menue(eintraege, mit_beleg, n_dokumente, n_moeglich):
    """Inhalt des Rechtsklick-Untermenüs „🛠 Wiki“ als reine Liste (testbar ohne Tk).
    :param eintraege: Wissen.liste()
    :param mit_beleg: Ids der Einträge, in denen eines der markierten Dokumente Beleg ist
    :param n_dokumente: markierte PDFs; n_moeglich: davon außerhalb des Papierkorbs - nur sie können Beleg werden
    :return: [(Text, Aktion | [Untermenü], frei)], None = Trennlinie; Aktion = ("zeige" | "ki" | "neu" | "hinzu", Id)"""
    if not n_dokumente:
        return [("Kein Dokument markiert", None, False)]
    belegt = [e for e in eintraege if e["id"] in mit_beleg]
    zeilen = [("Beleg in:", None, False)] if belegt else [("In keinem Wiki-Eintrag Beleg", None, False)]
    zeilen += [(f"{e['art_name']}: {e['bezeichnung']}", ("zeige", e["id"]), True) for e in belegt]
    zeilen.append(None)
    wovon = "dem Dokument" if n_dokumente == 1 else f"den {n_dokumente} Dokumenten"
    zeilen.append(("Von der KI lesen lassen…", ("ki", None), n_moeglich > 0))
    zeilen.append((f"Neuer Eintrag aus {wovon} (von Hand)…", ("neu", None), n_moeglich > 0))
    hinzu = []
    for e in eintraege:                                   # schon nach Schublade geordnet
        if not hinzu or hinzu[-1][0] != e["art_name"]:
            hinzu.append((e["art_name"], [], True))
        hinzu[-1][1].append((e["bezeichnung"], ("hinzu", e["id"]), not (n_dokumente == 1 and e["id"] in mit_beleg)))
    zeilen.append(("Zu Eintrag hinzufügen", hinzu, n_moeglich > 0 and bool(hinzu)))
    return zeilen


def baue_menue(menu, zeilen, ausfuehren):
    """`wiki_menue` in ein tk.Menu eintragen; Untermenüs werden Kinder von `menu` (der ToolManager räumt sie ab)."""
    for zeile in zeilen:
        if zeile is None:
            menu.add_separator()
            continue
        text, was, frei = zeile
        zustand = tk.NORMAL if frei else tk.DISABLED
        if isinstance(was, list):
            unter = tk.Menu(menu, tearoff=0)
            baue_menue(unter, was, ausfuehren)
            menu.add_cascade(label=text, menu=unter, state=zustand)
        else:
            menu.add_command(label=text, state=zustand, command=(lambda w=was: ausfuehren(w)) if was else None)


class WikiFenster(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.withdraw()                                   # erst aufbauen, dann zeigen (FALLSTRICKE #90)
        UIUtils.werkzeugfenster(self, app.root)           # über KID, nicht modal
        self.app = app
        self.title("Wiki")
        self.wissen = wissen.Wissen(app.master_folder)
        try:
            self.wissen.sichere()
        except Exception as e:                            # noqa: BLE001 - ohne Sicherung trotzdem öffnen, aber sagen
            self._log(f"Wiki: Sicherung nicht möglich ({type(e).__name__})", "warning")
        self.eintrag = None                               # geladener Eintrag (dict) oder None
        self.neu = False                                  # Formular für einen noch nicht gespeicherten Eintrag
        self._stand = None                                # Formularinhalt beim Laden (ungespeichert?)
        self.suche = None                                 # offenes Fenster „Belege suchen“ (BelegSuche) oder None
        self.dinge = None                                 # offenes Fenster „Aus dem Dokument“ (DingeFenster) oder None
        self._mitbringen = None                           # Rechtsklick „Neuer Eintrag aus …“: Pfade, die beim Speichern
                                                          # Belege werden
        self._ziele = {}                                  # Auswahl „Verbinden“: Text → Eintrags-Id
        self._baue()
        self.protocol("WM_DELETE_WINDOW", self._schliessen)
        self.update_idletasks()
        UIUtils.position_near_mouse(self, UIUtils.px(self, 980), UIUtils.px(self, 760))
        self._fuelle_liste()
        self._zeige_leer()
        self.deiconify()
        self._log(f"Wiki geöffnet ({self.wissen.anzahl()} Einträge)")

    # ---------------------------------------------------------------- Aufbau
    def _baue(self):
        rand = UIUtils.px(self, 10)
        unten = ttk.Frame(self)                           # Knopfleiste VOR dem dehnbaren Inhalt mit side=BOTTOM
        unten.pack(side=tk.BOTTOM, fill=tk.X, padx=rand, pady=(4, rand))
        ttk.Button(unten, text="Schließen", command=self._schliessen).pack(side=tk.RIGHT)
        self.btn_loeschen = ttk.Button(unten, text="Löschen", command=self._loeschen)
        self.btn_loeschen.pack(side=tk.RIGHT, padx=6)
        self.btn_legen = ttk.Button(unten, text="Zusammenlegen mit…", command=self._zusammenlegen_menue)
        self.btn_legen.pack(side=tk.RIGHT)
        Tooltip(self.btn_legen, "Ein anderer Eintrag meint dasselbe: Seine Angaben, Belege und Verbindungen kommen zu "
                                "diesem Eintrag, der andere verschwindet.")
        self.menue_legen = tk.Menu(self, tearoff=0)
        self.btn_speichern = ttk.Button(unten, text="Speichern", command=self._speichern, style="Accent.TButton")
        self.btn_speichern.pack(side=tk.RIGHT)

        teiler = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        teiler.pack(fill=tk.BOTH, expand=True, padx=rand, pady=(rand, 0))
        links = ttk.Frame(teiler)
        rechts = ttk.Frame(teiler)
        teiler.add(links, weight=1)
        teiler.add(rechts, weight=3)

        self.btn_neu = ttk.Button(links, text="Neuer Eintrag…", command=self._neu)
        self.btn_neu.pack(side=tk.BOTTOM, fill=tk.X, pady=(6, 0))
        self.var_filter = tk.StringVar()
        filt = ttk.Entry(links, textvariable=self.var_filter)
        filt.pack(fill=tk.X, pady=(0, 4))
        Tooltip(filt, "Sucht in Bezeichnung, Notiz und Angaben, etwa nach einer Telefon- oder Kundennummer. Mehrere "
                      "Wörter müssen alle vorkommen. Die passenden Angaben sind rechts markiert.")
        self.var_filter.trace_add("write", lambda *_: self._fuelle_liste())
        self.tree = ttk.Treeview(links, show="tree", selectmode="browse")
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._gewaehlt())

        innen = ttk.Frame(rechts)
        innen.pack(fill=tk.BOTH, expand=True, padx=(10, 0))
        self.lbl_kopf = ttk.Label(innen, font=("", UIUtils.schriftgroesse(self, 2), "bold"))
        self.lbl_kopf.pack(anchor="w")
        self.lbl_stand = ttk.Label(innen, foreground="gray40", wraplength=UIUtils.px(self, 680), justify=tk.LEFT)
        self.lbl_stand.pack(anchor="w", pady=(0, 6))

        # Belege und Verbindungen von unten nach oben, die Angaben bekommen den Rest
        self.rahmen_belege = ttk.Frame(innen)
        self.rahmen_belege.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        kopf = ttk.Frame(self.rahmen_belege)
        kopf.pack(fill=tk.X)
        ttk.Label(kopf, text="Belege").pack(side=tk.LEFT)
        self.btn_beleg_weg = ttk.Button(kopf, text="Entfernen", command=self._beleg_weg)
        self.btn_beleg_weg.pack(side=tk.RIGHT)
        Tooltip(self.btn_beleg_weg, "Das Dokument ist dann kein Beleg mehr. Angaben aus ihm bleiben stehen, verlieren "
                                    "aber Dokument und Zitat.")
        self.btn_beleg = ttk.Button(kopf, text="Markierte Dokumente hinzufügen", command=self._beleg_hinzu)
        self.btn_beleg.pack(side=tk.RIGHT, padx=6)
        Tooltip(self.btn_beleg, "Die im Hauptfenster markierten Dokumente werden Belege dieses Eintrags. "
                                "Doppelklick auf einen Beleg zeigt ihn im Hauptfenster.")
        self.btn_suchen = ttk.Button(kopf, text="Dokumente suchen…", command=self._suche_oeffnen)
        self.btn_suchen.pack(side=tk.RIGHT)
        Tooltip(self.btn_suchen, "Passende Dokumente in der Sammlung suchen, anhaken und als Belege übernehmen")
        self.btn_ki = ttk.Button(kopf, text="Von der KI lesen lassen…", command=self._belege_lesen)
        self.btn_ki.pack(side=tk.RIGHT, padx=(0, 6))
        Tooltip(self.btn_ki, "Die KI liest die markierten Belege (ohne Markierung alle) und listet auf, wer und was "
                             "darin vorkommt. Ins Wiki kommt nur, was du anhakst.")
        self.tree_belege = ttk.Treeview(self.rahmen_belege, show="tree", height=4, selectmode="extended")
        self.tree_belege.pack(fill=tk.X, pady=(4, 0))
        self.tree_belege.bind("<Double-1>", lambda _e: self._beleg_zeigen())

        self.rahmen_verbunden = ttk.Frame(innen)
        self.rahmen_verbunden.pack(side=tk.BOTTOM, fill=tk.X, pady=(8, 0))
        kopf = ttk.Frame(self.rahmen_verbunden)
        kopf.pack(fill=tk.X)
        ttk.Label(kopf, text="Verbunden mit").pack(side=tk.LEFT)
        self.btn_trennen = ttk.Button(kopf, text="Trennen", command=self._trennen)
        self.btn_trennen.pack(side=tk.RIGHT)
        self.btn_verbinden = ttk.Button(kopf, text="Verbinden", command=self._verbinden)
        self.btn_verbinden.pack(side=tk.RIGHT, padx=6)
        self.var_ziel = tk.StringVar()
        self.cmb_ziel = ttk.Combobox(kopf, textvariable=self.var_ziel, state="readonly", width=40)
        self.cmb_ziel.pack(side=tk.RIGHT)
        Tooltip(self.cmb_ziel, "Einen anderen Eintrag wählen, der mit diesem zu tun hat - etwa die Firma, die ein Haus "
                               "betreut. Doppelklick auf eine Verbindung springt dorthin.")
        self.tree_verbunden = ttk.Treeview(self.rahmen_verbunden, show="tree", height=3, selectmode="browse")
        self.tree_verbunden.pack(fill=tk.X, pady=(4, 0))
        self.tree_verbunden.bind("<Double-1>", lambda _e: self._verbundenen_zeigen())

        formular = ttk.Frame(innen)
        formular.pack(fill=tk.X)
        formular.columnconfigure(1, weight=1)
        ttk.Label(formular, text="Bezeichnung:").grid(row=0, column=0, sticky="w", pady=2, padx=(0, 6))
        self.var_bezeichnung = tk.StringVar()
        self.ent_bezeichnung = ttk.Entry(formular, textvariable=self.var_bezeichnung)
        self.ent_bezeichnung.grid(row=0, column=1, sticky="ew", pady=2)
        ttk.Label(formular, text="Schublade:").grid(row=1, column=0, sticky="w", pady=2, padx=(0, 6))
        self.var_art = tk.StringVar()
        zeile = ttk.Frame(formular)
        zeile.grid(row=1, column=1, sticky="w", pady=2)
        self.cmb_art = ttk.Combobox(zeile, textvariable=self.var_art, width=30)
        self.cmb_art.pack(side=tk.LEFT)
        self.btn_schubladen = ttk.Button(zeile, text="Schubladen…", command=self._schubladen)
        self.btn_schubladen.pack(side=tk.LEFT, padx=(6, 0))
        Tooltip(self.btn_schubladen, "Schubladen umbenennen, zusammenlegen, neu anlegen oder leere löschen.")
        Tooltip(self.cmb_art, "Unter welcher Überschrift der Eintrag links steht. Eine vorhandene wählen oder einen "
                              "neuen Namen eintippen - dann entsteht beim Speichern eine neue Schublade.")
        ttk.Label(formular, text="Notiz:").grid(row=2, column=0, sticky="nw", pady=2, padx=(0, 6))
        self.txt_notiz = tk.Text(formular, height=3, wrap="word")
        self.txt_notiz.grid(row=2, column=1, sticky="ew", pady=2)

        self.rahmen_angaben = ttk.Frame(innen)
        self.rahmen_angaben.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        kopf = ttk.Frame(self.rahmen_angaben)
        kopf.pack(fill=tk.X)
        ttk.Label(kopf, text="Angaben").pack(side=tk.LEFT)
        self.btn_angabe_weg = ttk.Button(kopf, text="Entfernen", command=self._angabe_weg)
        self.btn_angabe_weg.pack(side=tk.RIGHT)
        self.btn_angabe_aendern = ttk.Button(kopf, text="Ändern…", command=self._angabe_aendern)
        self.btn_angabe_aendern.pack(side=tk.RIGHT, padx=6)
        self.btn_angabe = ttk.Button(kopf, text="Hinzufügen…", command=self._angabe_hinzu)
        self.btn_angabe.pack(side=tk.RIGHT)
        Tooltip(self.btn_angabe, "Eine kurze Zeile, etwa „Telefon: 01234 56789“ oder „Heizung erneuert 2019“")
        self.lbl_zitat = ttk.Label(self.rahmen_angaben, foreground="gray40", wraplength=UIUtils.px(self, 680),
                                   justify=tk.LEFT)
        self.lbl_zitat.pack(side=tk.BOTTOM, anchor="w", pady=(2, 0))
        self.tree_angaben = ttk.Treeview(self.rahmen_angaben, columns=("text", "quelle"), show="headings", height=5,
                                         selectmode="extended")
        self.tree_angaben.heading("text", text="Angabe", anchor="w")
        self.tree_angaben.heading("quelle", text="aus Dokument", anchor="w")
        self.tree_angaben.column("text", width=UIUtils.px(self, 430), anchor="w")
        self.tree_angaben.column("quelle", width=UIUtils.px(self, 220), anchor="w")
        self.tree_angaben.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        self.tree_angaben.bind("<<TreeviewSelect>>", lambda _e: self._zeige_zitat())
        self.tree_angaben.bind("<Double-1>", lambda _e: self._angabe_aendern())

    # ---------------------------------------------------------------- Liste
    def _fuelle_liste(self, waehle=None):
        filt = self.var_filter.get().strip()
        offen = {iid for iid in self.tree.get_children() if self.tree.item(iid, "open")}
        hatte = bool(self.tree.get_children())
        self.tree.delete(*self.tree.get_children())
        gruppen = {}
        texte = self.wissen.suchtexte() if filt else {}
        for e in self.wissen.liste():                     # schon nach Schublade und Bezeichnung geordnet
            if filt and not wissen.passt(filt, texte.get(e["id"], [e["bezeichnung"]])):
                continue
            gruppe = f"art:{e['art']}"
            if gruppe not in gruppen:
                gruppen[gruppe] = [e["art_name"], 0]
                self.tree.insert("", tk.END, iid=gruppe, open=bool(filt) or gruppe in offen or not hatte)
            gruppen[gruppe][1] += 1
            self.tree.insert(gruppe, tk.END, iid=f"e:{e['id']}", text=e["bezeichnung"])
        for gruppe, (name, n) in gruppen.items():
            self.tree.item(gruppe, text=f"{name} ({n})")
        if waehle and self.tree.exists(f"e:{waehle}"):
            self.tree.item(self.tree.parent(f"e:{waehle}"), open=True)
            self.tree.selection_set(f"e:{waehle}")        # lädt über <<TreeviewSelect>> (FALLSTRICKE #8)
            self.tree.see(f"e:{waehle}")

    def _gewaehlt(self):
        auswahl = self.tree.selection()
        if not auswahl or not auswahl[0].startswith("e:"):
            return
        eintrag_id = int(auswahl[0][2:])
        if self.eintrag and self.eintrag["id"] == eintrag_id:
            return
        if not self._weiter_trotz_aenderung():
            # Abbrechen: die Liste zeigt wieder, was im Formular steht - sonst fragte jedes weitere <<TreeviewSelect>>
            # mit der fremden Zeile noch einmal
            if self.eintrag:
                self.tree.selection_set(f"e:{self.eintrag['id']}")
            else:
                self.tree.selection_remove(self.tree.selection())
            return
        if self.tree.selection() != (f"e:{eintrag_id}",) and self.tree.exists(f"e:{eintrag_id}"):
            self.tree.selection_set(f"e:{eintrag_id}")    # „Speichern“ hat die Liste neu gebaut und den alten gewählt
        self._zeige(self.wissen.lade(eintrag_id))

    # ---------------------------------------------------------------- Formular
    def _leere_formular(self):
        self.txt_notiz.config(state=tk.NORMAL)            # gesperrt nähme das Textfeld nichts an
        self.var_bezeichnung.set("")
        self.var_art.set("")
        self.cmb_art.config(values=[a["name"] for a in self.wissen.arten()])
        self.txt_notiz.delete("1.0", "end")
        for tree in (self.tree_angaben, self.tree_verbunden, self.tree_belege):
            tree.delete(*tree.get_children())
        self.lbl_zitat.config(text="")
        self.cmb_ziel.config(values=[])
        self.var_ziel.set("")
        self._ziele = {}

    def _zeige_leer(self):
        self._mitbringen = None
        self._suche_schliessen()
        self.eintrag, self.neu = None, False
        self._leere_formular()
        self._stand = None
        self.lbl_kopf.config(text="Wiki")
        self.lbl_stand.config(text="Links einen Eintrag wählen oder unten einen neuen anlegen. Es steht nur drin, was "
                                   "du selbst einträgst oder bestätigst.")
        self._schalte(False)

    def _neu(self):
        """Formular für einen neuen Eintrag; die Schublade des zuletzt gezeigten Eintrags ist vorgewählt.
        :return: False, wenn der Nutzer wegen ungespeicherter Änderungen abbricht"""
        if not self._weiter_trotz_aenderung():
            return False
        vorwahl = self.eintrag["art_name"] if self.eintrag else ""
        self._mitbringen = None
        self._suche_schliessen()
        self.tree.selection_remove(self.tree.selection())
        self.eintrag, self.neu = None, True
        self._leere_formular()
        self.var_art.set(vorwahl or (self.cmb_art.cget("values") or [""])[0])
        self._stand = self._formular()
        self.lbl_kopf.config(text="Neuer Eintrag")
        self.lbl_stand.config(text="Angaben, Verbindungen und Belege lassen sich nach dem Speichern hinzufügen.")
        self._schalte(True, teile=False)
        self.ent_bezeichnung.focus_set()
        return True

    def neu_aus_dokumenten(self, pfade):
        """Rechtsklick „Neuer Eintrag aus dem Dokument“: Formular für einen neuen Eintrag; beim Speichern werden `pfade`
        seine Belege. :return: False bei Abbruch"""
        if not pfade or not self._neu():
            return False
        self._mitbringen = list(pfade)
        n = len(pfade)
        self.lbl_stand.config(text="Beim Speichern wird das Dokument Beleg dieses Eintrags." if n == 1 else
                              f"Beim Speichern werden die {n} Dokumente Belege dieses Eintrags.")
        return True

    def zeige_eintrag(self, eintrag_id):
        """Von außen (Rechtsklick in der Dokumentenliste, Doppelklick auf eine Verbindung) diesen Eintrag zeigen;
        Ungespeichertes fragt wie ein Klick in die Liste. :return: True, wenn er jetzt gezeigt wird"""
        if self.eintrag and self.eintrag["id"] == eintrag_id:
            return True
        if self.wissen.lade(eintrag_id) is None or not self._weiter_trotz_aenderung():
            return False
        self.nach_aenderung(eintrag_id)
        return True

    def _zeige(self, eintrag):
        self._mitbringen = None
        if eintrag is None:
            self._fuelle_liste()
            self._zeige_leer()
            return
        self._suche_schliessen(ausser=eintrag["id"])
        self.eintrag, self.neu = eintrag, False
        self._leere_formular()
        self.var_bezeichnung.set(eintrag["bezeichnung"])
        self.var_art.set(eintrag["art_name"])
        self.txt_notiz.insert("1.0", eintrag["notiz"])
        self._stand = self._formular()
        self.lbl_kopf.config(text=f"{eintrag['art_name']}: {eintrag['bezeichnung']}")
        self.lbl_stand.config(text=f"geändert {eintrag['geaendert'][:16].replace('T', ' ')}")
        for a in eintrag["angaben"]:
            self.tree_angaben.insert("", tk.END, iid=f"a:{a['id']}", values=(a["text"], a["titel"] or a["kid_id"]))
        for v in eintrag["verbunden"]:
            self.tree_verbunden.insert("", tk.END, iid=f"v:{v['id']}", text=f"{v['bezeichnung']} ({v['art_name']})")
        for b in eintrag["belege"]:
            self.tree_belege.insert("", tk.END, iid=f"b:{b['id']}", text=b["titel"] or b["kid_id"])
        schon = {v["id"] for v in eintrag["verbunden"]} | {eintrag["id"]}
        for e in self.wissen.liste():
            if e["id"] not in schon:
                text = f"{e['bezeichnung']} ({e['art_name']})"
                self._ziele[text if text not in self._ziele else f"{text} [{e['id']}]"] = e["id"]
        self.cmb_ziel.config(values=list(self._ziele))
        self._schalte(True)
        filt = self.var_filter.get().strip()
        if filt:                                          # die Angaben, die die Suche getroffen hat
            treffer = [f"a:{eintrag['angaben'][i - 2]['id']}"
                       for i in wissen.fundstellen(filt, [eintrag["bezeichnung"], eintrag["notiz"]]
                                                   + [a["text"] for a in eintrag["angaben"]]) if i >= 2]
            if treffer:
                self.tree_angaben.selection_set(treffer)
                self.tree_angaben.see(treffer[0])

    def _neu_laden(self):
        """Nach einer Sofort-Änderung (Angabe, Verbindung, Beleg): den Eintrag frisch zeigen, ungespeicherte Eingaben
        im Formular bleiben stehen."""
        stand = self._formular()
        self._zeige(self.wissen.lade(self.eintrag["id"]))
        if stand and self.eintrag:
            self.var_bezeichnung.set(stand["bezeichnung"])
            self.var_art.set(stand["art"])
            self.txt_notiz.delete("1.0", "end")
            self.txt_notiz.insert("1.0", stand["notiz"])

    def _formular(self):
        """Formularinhalt als Dict (zum Speichern und für „ungespeichert?“), None ohne Formular."""
        if not (self.eintrag or self.neu):
            return None
        return {"bezeichnung": self.var_bezeichnung.get(), "art": self.var_art.get(),
                "notiz": self.txt_notiz.get("1.0", "end").strip()}

    def _geaendert(self):
        return self._stand is not None and self._formular() != self._stand

    def _weiter_trotz_aenderung(self):
        """Ungespeicherte Änderungen: speichern, verwerfen oder bleiben (bewusst nicht über bestaetigung.frage)."""
        if not self._geaendert():
            return True
        antwort = mb.askyesnocancel("Wiki", "Die Änderungen an diesem Eintrag sind noch nicht gespeichert.\n\n"
                                            "Jetzt speichern?", parent=self)
        if antwort is None:
            return False
        return self._speichern() if antwort else True

    def _schalte(self, an, teile=True):
        """`an`: es gibt ein Formular. `teile`: der Eintrag ist gespeichert - Angaben, Verbindungen, Belege gehen."""
        self.btn_speichern.config(state=tk.NORMAL if an else tk.DISABLED)
        self.btn_loeschen.config(state=tk.NORMAL if an and self.eintrag else tk.DISABLED)
        for feld in (self.ent_bezeichnung, self.cmb_art, self.txt_notiz):
            feld.config(state=tk.NORMAL if an else tk.DISABLED)
        frei = tk.NORMAL if an and teile else tk.DISABLED
        for knopf in (self.btn_angabe, self.btn_angabe_aendern, self.btn_angabe_weg, self.btn_verbinden,
                      self.btn_trennen, self.btn_beleg, self.btn_beleg_weg, self.btn_suchen, self.btn_ki,
                      self.btn_legen):
            knopf.config(state=frei)
        self.cmb_ziel.config(state="readonly" if an and teile else tk.DISABLED)

    # ---------------------------------------------------------------- Speichern, Löschen
    def _schublade(self, name):
        """Name aus dem Formular → Id der Schublade bzw. der Name (neu, oder die Datei gibt es noch nicht).
        :return: (art, neu) - art None, wenn der Nutzer eine neue Schublade nicht will"""
        name = " ".join(name.split())
        for a in self.wissen.arten():
            if a["name"].casefold() == name.casefold():
                return (a["id"] if a["id"] is not None else a["name"]), False
        if name and not mb.askyesno("Wiki", f"Eine Schublade „{name}“ gibt es noch nicht.\n\nNeu anlegen?", parent=self):
            return None, False
        return name, True

    def _speichern(self):
        stand = self._formular()
        if stand is None:
            return False
        eigen = self.eintrag["id"] if self.eintrag else None
        art, neue_schublade = self._schublade(stand["art"])
        if art is None:
            return False
        if not neue_schublade and not isinstance(art, str) and self.wissen.gleichnamige(
                art, stand["bezeichnung"], ausser=eigen) and not mb.askyesno(
                "Wiki", f"In dieser Schublade gibt es schon einen Eintrag „{stand['bezeichnung'].strip()}“.\n\n"
                        "Trotzdem speichern?", parent=self):
            return False
        try:
            eintrag_id = self.wissen.speichere(art, stand["bezeichnung"], stand["notiz"], eintrag_id=eigen)
        except wissen.Eingabefehler as e:
            mb.showwarning("Wiki", str(e), parent=self)
            return False
        except Exception as e:                            # noqa: BLE001 - Datei gesperrt o. ä.: sagen, nichts verlieren
            mb.showerror("Wiki", f"Der Eintrag ließ sich nicht speichern:\n{e}", parent=self)
            return False
        self._log(f"Wiki: Eintrag {'angelegt' if eigen is None else 'geändert'}"
                  + (", neue Schublade" if neue_schublade else ""))
        mitbringen = self._mitbringen                     # nur ein neuer Eintrag hat etwas dabei (_zeige vergisst es)
        self.nach_aenderung(eintrag_id)                   # vergisst das Mitgebrachte
        if mitbringen:
            pfade = [p for p in mitbringen if os.path.isfile(p)]   # inzwischen verschoben oder gelöscht: fällt weg
            if pfade:
                self.belege_eintragen(eintrag_id, pfade)
        return True

    def _schubladen(self):
        """„Schubladen…“: erst Ungespeichertes klären, dann das Fenster (modal, wiki_schubladen.py)."""
        if not self._weiter_trotz_aenderung():
            return None
        self.schubladen = SchubladenFenster(self)
        return self.schubladen

    def schubladen_geaendert(self):
        """Eine Schublade wurde umbenannt, zusammengelegt, angelegt oder gelöscht: Liste und Eintrag neu zeigen. Ein
        noch nicht gespeicherter neuer Eintrag behält seine Eingaben und bekommt nur die neue Auswahl."""
        if self.eintrag:
            self.nach_aenderung(self.eintrag["id"])
        else:
            self._fuelle_liste()
        self.cmb_art.config(values=[a["name"] for a in self.wissen.arten()])

    def nach_aenderung(self, eintrag_id):
        """Nach dem Speichern: Liste neu, den Eintrag zeigen, im offenen Suchfenster die neuen Belege als „schon
        Beleg“."""
        self.eintrag, self.neu = None, False              # damit _gewaehlt neu lädt
        self._stand = None
        self._fuelle_liste(waehle=eintrag_id)
        if self.eintrag is None:                          # Filter blendet ihn aus: trotzdem zeigen
            self._zeige(self.wissen.lade(eintrag_id))
        if self.suche is not None and self.suche.winfo_exists() and self.suche.suchtext:
            self.suche.aktualisiere()

    def _loeschen(self):
        if not self.eintrag:
            return
        e = self.eintrag
        text = f"„{e['bezeichnung']}“ samt seinen Angaben und Belegen aus dem Wiki löschen?"
        if e["verbunden"]:
            text += f"\n\nEr ist mit {len(e['verbunden'])} anderen Einträgen verbunden; die Verbindungen entfallen."
        text += "\n\nDie Dokumente selbst bleiben unverändert."
        if not mb.askyesno("Wiki", text, parent=self, icon="warning"):
            return
        self.wissen.loesche(e["id"])
        self._log("Wiki: Eintrag gelöscht")
        self._stand = None
        self._fuelle_liste()
        self._zeige_leer()

    def _zusammenlegen_menue(self):
        """„Zusammenlegen mit…“: Menü der anderen Einträge, nach Schubladen."""
        if not self.eintrag or not self._weiter_trotz_aenderung() or not self.eintrag:
            return
        menue = self.menue_legen
        for kind in menue.winfo_children():
            kind.destroy()
        menue.delete(0, "end")
        gruppen = collections.OrderedDict()
        for e in self.wissen.liste():
            if e["id"] != self.eintrag["id"]:
                gruppen.setdefault(e["art_name"], []).append(e)
        for name, eintraege in gruppen.items():
            unter = tk.Menu(menue, tearoff=0)
            for e in eintraege:
                unter.add_command(label=e["bezeichnung"], command=lambda z=e: self.zusammenlegen(z["id"]))
            menue.add_cascade(label=f"{name} ({len(eintraege)})", menu=unter)
        if not gruppen:
            menue.add_command(label="(kein anderer Eintrag)", state=tk.DISABLED)
        try:
            menue.tk_popup(self.btn_legen.winfo_rootx(), self.btn_legen.winfo_rooty() - UIUtils.px(self, 30))
        finally:
            menue.grab_release()

    def zusammenlegen(self, anderer_id):
        """Der Eintrag `anderer_id` geht im gezeigten auf - nach Rückfrage (unumkehrbar, bewusst nicht abschaltbar)."""
        anderer = self.wissen.lade(anderer_id)
        if not self.eintrag or anderer is None:
            return False
        e = self.eintrag
        if not mb.askyesno("Wiki", f"„{anderer['bezeichnung']}“ ({anderer['art_name']}) mit diesem Eintrag zusammenlegen?\n\n"
                           f"Seine {len(anderer['angaben'])} Angaben, {len(anderer['belege'])} Belege und "
                           f"{len(anderer['verbunden'])} Verbindungen kommen zu „{e['bezeichnung']}“ ({e['art_name']}). "
                           f"„{anderer['bezeichnung']}“ verschwindet, sein Name bleibt als Angabe „Auch: …“ stehen.\n\n"
                           "Das lässt sich nicht rückgängig machen.", parent=self):
            return False
        try:
            zahlen = self.wissen.eintraege_zusammenlegen(e["id"], anderer_id)
        except wissen.Eingabefehler as fehler:
            mb.showwarning("Wiki", str(fehler), parent=self)
            return False
        self._log(f"Wiki: Einträge zusammengelegt ({zahlen['angaben']} Angaben, {zahlen['belege']} Belege, "
                  f"{zahlen['verbunden']} Verbindungen dazu)")
        self.nach_aenderung(e["id"])
        return True

    # ---------------------------------------------------------------- Angaben
    def _markierte_angaben(self):
        return [int(iid[2:]) for iid in self.tree_angaben.selection() if iid.startswith("a:")]

    def _zeige_zitat(self):
        ids = self._markierte_angaben()
        angabe = next((a for a in self.eintrag["angaben"] if a["id"] == ids[0]), None) if self.eintrag and ids else None
        if angabe is None:
            self.lbl_zitat.config(text="")
        elif angabe["zitat"]:
            self.lbl_zitat.config(text=f"Im Dokument: „{angabe['zitat']}“")
        else:
            self.lbl_zitat.config(text="Von Hand eingetragen" if not angabe["kid_id"] else "")

    def _frage_angabe(self, titel, vorgabe=""):
        return simpledialog.askstring(titel, "Angabe (eine kurze Zeile):", initialvalue=vorgabe, parent=self)

    def _angabe_hinzu(self):
        if not self.eintrag:
            return
        text = self._frage_angabe("Angabe hinzufügen")
        if text is None:
            return
        try:
            neu = self.wissen.angabe_hinzu(self.eintrag["id"], text)
        except wissen.Eingabefehler as e:
            mb.showwarning("Wiki", str(e), parent=self)
            return
        if neu is None:
            mb.showinfo("Wiki", "Diese Angabe steht schon da.", parent=self)
            return
        self._neu_laden()

    def _angabe_aendern(self):
        ids = self._markierte_angaben()
        if not self.eintrag or len(ids) != 1:
            return
        alt = next(a for a in self.eintrag["angaben"] if a["id"] == ids[0])
        text = self._frage_angabe("Angabe ändern", alt["text"])
        if text is None or " ".join(text.split()) == alt["text"]:
            return
        try:
            self.wissen.angabe_aendern(ids[0], text)
        except wissen.Eingabefehler as e:
            mb.showwarning("Wiki", str(e), parent=self)
            return
        self._neu_laden()

    def _angabe_weg(self):
        ids = self._markierte_angaben()
        if not self.eintrag or not ids:
            return
        for angabe_id in ids:
            self.wissen.angabe_weg(angabe_id)
        self._neu_laden()

    # ---------------------------------------------------------------- Verbindungen
    def _verbinden(self):
        ziel = self._ziele.get(self.var_ziel.get())
        if not self.eintrag or ziel is None:
            return
        try:
            self.wissen.verbinde(self.eintrag["id"], ziel)
        except wissen.Eingabefehler as e:                 # das Ziel wurde inzwischen gelöscht
            mb.showwarning("Wiki", str(e), parent=self)
        self._neu_laden()

    def _trennen(self):
        auswahl = self.tree_verbunden.selection()
        if not self.eintrag or not auswahl:
            return
        self.wissen.trenne(self.eintrag["id"], int(auswahl[0][2:]))
        self._neu_laden()

    def _verbundenen_zeigen(self):
        auswahl = self.tree_verbunden.selection()
        if auswahl:
            self.zeige_eintrag(int(auswahl[0][2:]))

    # ---------------------------------------------------------------- Belege
    def _beleg_hinzu(self):
        if not self.eintrag:
            return
        pfade = markierte_pdfs(self.app)
        if not pfade:
            mb.showinfo("Wiki", "Bitte im Hauptfenster ein oder mehrere Dokumente markieren.", parent=self)
            return
        self.belege_eintragen(self.eintrag["id"], pfade)

    def belege_eintragen(self, eintrag_id, pfade, parent=None):
        """PDFs (absolute Pfade) als Belege des Eintrags eintragen, über ihre Dokument-ID (wird nötigenfalls vergeben).
        Zeigt das Fenster gerade diesen Eintrag, erscheinen sie sofort; ungespeicherte Eingaben bleiben stehen.
        Gemeinsam für „Markierte Dokumente hinzufügen“, das Suchfenster und den Rechtsklick. :return: Zahl neuer
        Belege, None wenn es den Eintrag nicht mehr gibt"""
        if self.wissen.lade(eintrag_id) is None:
            return None
        neu = ohne_id = 0
        for pfad in pfade:
            kid_id = PDFHandler.ensure_kid_id(pfad)
            if not kid_id:
                ohne_id += 1
                continue
            neu += self.wissen.beleg_hinzu(eintrag_id, kid_id, dokument_titel(pfad))
        self._log(f"Wiki: {neu} Beleg(e) hinzugefügt")
        if ohne_id:
            mb.showwarning("Wiki", f"{ohne_id} Dokument(e) ließen sich nicht als Beleg eintragen: Sie bekommen keine "
                                   "Dokument-ID (schreibgeschützt oder gerade geöffnet?).", parent=parent or self)
        if self.eintrag and self.eintrag["id"] == eintrag_id:
            self._neu_laden()
        return neu

    def _suche_oeffnen(self):
        """Fenster „Belege suchen“ zum gewählten Eintrag; höchstens eines, für einen anderen Eintrag ein neues."""
        if not self.eintrag:
            return
        if self.suche is not None and self.suche.winfo_exists() and self.suche.eintrag_id == self.eintrag["id"]:
            self.suche.deiconify()
            self.suche.lift()
            self.suche.ent_suche.focus_set()
            return
        self._suche_schliessen()
        self.suche = BelegSuche(self, self.eintrag)

    def _suche_schliessen(self, ausser=None):
        """Das Suchfenster gehört zu einem Eintrag: wechselt das Wiki-Fenster zu einem anderen, geht es zu."""
        if self.suche is not None and self.suche.winfo_exists() and self.suche.eintrag_id != ausser:
            self.suche.destroy()
        if self.suche is not None and not self.suche.winfo_exists():
            self.suche = None

    def _belege_lesen(self):
        """„Von der KI lesen lassen…“ bei den Belegen: die markierten, ohne Markierung alle."""
        if not self.eintrag:
            return
        markiert = {iid for iid in self.tree_belege.selection() if iid.startswith("b:")}
        belege = [b for b in self.eintrag["belege"] if not markiert or f"b:{b['id']}" in markiert]
        dokumente, fehlt = dokumente_aus_belegen(self.app, belege)
        if not dokumente:
            mb.showinfo("Wiki", f"{fehlt} Beleg(e) sind in der Sammlung nicht (mehr) zu finden." if fehlt else
                        "Dieser Eintrag hat noch keine Belege.", parent=self)
            return
        self.dinge_lesen(dokumente)

    def dinge_lesen(self, dokumente):
        """Fenster „Aus dem Dokument“ öffnen (höchstens eines): die KI liest `dokumente` ([{rel_path, titel}])."""
        if not dokumente:
            return
        if self.dinge is not None and self.dinge.winfo_exists():
            self.dinge.destroy()                          # ein laufender Lauf bricht ab
        self.dinge = DingeFenster(self, dokumente)

    def _beleg_weg(self):
        auswahl = [iid for iid in self.tree_belege.selection() if iid.startswith("b:")]
        if not self.eintrag or not auswahl:
            return
        for iid in auswahl:
            self.wissen.beleg_weg(int(iid[2:]))
        self._neu_laden()

    def _beleg_zeigen(self):
        auswahl = self.tree_belege.selection()
        if not self.eintrag or not auswahl:
            return
        beleg = next((b for b in self.eintrag["belege"] if f"b:{b['id']}" == auswahl[0]), None)
        index = getattr(self.app, "index_manager", None)
        rel = index.pfad_zur_kid_id(beleg["kid_id"]) if beleg and index else None
        folder_manager = getattr(self.app, "folder_manager", None)
        if not rel or folder_manager is None or not folder_manager.zeige_dokument(os.path.join(self.app.master_folder, rel)):
            mb.showinfo("Wiki", "Das Dokument ist in der Sammlung nicht (mehr) zu finden. Liegt es im Papierkorb?",
                        parent=self)

    # ---------------------------------------------------------------- Schließen, Protokoll
    def _schliessen(self):
        if not self._weiter_trotz_aenderung():
            return
        self.destroy()

    def _log(self, text, stufe="info"):
        """Nur Zahlen, nie Namen oder Werte (Datenschutz)."""
        logger = getattr(self.app, "logger", None)
        if logger is not None:
            getattr(logger, stufe)(text)


class WikiTool(BaseTool):
    @property
    def name(self) -> str:
        return "Wiki"

    @property
    def menu_group(self) -> str:
        return "KI-Helfer"

    @property
    def menu_label(self) -> str:
        return "Wiki…"

    @property
    def absicht(self) -> str:
        return ("Was KID über die Sammlung weiß - Familie, Firmen, Immobilien, Fahrzeuge, Verträge -, von Hand angelegt "
                "und bestätigt, jede Angabe mit dem Dokument, aus dem sie stammt. Später nutzt KID dieses Wissen beim "
                "Ablegen und Beantworten von Fragen.")

    @property
    def description(self) -> str:
        return ("Einträge in frei erweiterbaren Schubladen, jeder mit kurzen Angaben (etwa Anschrift, Telefon, "
                "Kundennummer), Verbindungen zu anderen Einträgen, einer Notiz und Belegen: im Fenster gesuchte und "
                "angehakte oder im Hauptfenster markierte Dokumente. Es steht nur drin, was du selbst einträgst oder "
                "bestätigst. Auf Wunsch liest die KI ausgesuchte Dokumente und listet auf, wer und was darin "
                "vorkommt, je mit Zitat - du hakst an, was ins Wiki soll. Rechtsklick auf ein Dokument: Einträge, in "
                "denen es Beleg ist, von der KI lesen lassen, ein neuer Eintrag von Hand oder zu einem vorhandenen "
                "hinzufügen.")

    @property
    def menu_hooks(self) -> list:
        return ["main_menu", "context_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        app = context.app
        UIUtils.einzelfenster("wiki_von_hand", lambda: WikiFenster(app))
        return True

    def fuelle_kontextmenue(self, menu, context):
        """Untermenü „🛠 Wiki“ im Rechtsklick der Dokumentenliste; der ToolManager ruft es vor jedem Öffnen. Liest nur
        (Wiki und die Dokument-IDs der markierten PDFs), geschrieben wird erst beim Klick auf eine Aktion."""
        app = context.app
        pdfs = [p for p in context.selected_files if p.lower().endswith(".pdf")]
        moeglich = [p for p in pdfs if not app_paths.is_trash_path(p, app.master_folder)]
        w = wissen.Wissen(app.master_folder)
        eintraege = w.liste()
        mit_beleg = set()
        if eintraege:
            kid_ids = [(PDFHandler.get_metadata(p).get("KID_ID") or "").strip() for p in pdfs[:KID_IDS_HOECHSTENS]]
            mit_beleg = {e["id"] for e in w.eintraege_mit_beleg(kid_ids)}
        baue_menue(menu, wiki_menue(eintraege, mit_beleg, len(pdfs), len(moeglich)),
                   lambda aktion: self.aus_dem_menue(app, aktion, moeglich))

    @staticmethod
    def aus_dem_menue(app, aktion, pfade):
        """Eine Aktion aus dem Rechtsklick: Wiki-Fenster öffnen (höchstens eins) und dort zeigen, anlegen, hinzufügen."""
        was, wert = aktion
        fenster = UIUtils.einzelfenster("wiki_von_hand", lambda: WikiFenster(app))
        if was == "zeige":
            fenster.zeige_eintrag(wert)
        elif was == "ki":
            fenster.dinge_lesen([{"rel_path": os.path.relpath(p, app.master_folder), "titel": dokument_titel(p)}
                                 for p in pfade])
        elif was == "neu":
            fenster.neu_aus_dokumenten(pfade)
        elif was == "hinzu" and pfade:
            fenster.zeige_eintrag(wert)
            fenster.belege_eintragen(wert, pfade)
