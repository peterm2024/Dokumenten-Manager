"""
Wiki von Hand, neuer Aufbau, Schritt N3 (KONZEPT_WIKI_VON_HAND.md, 12.11.2026): Die KI liest ausgesuchte Dokumente und
listet auf, wer und was darin vorkommt - der Mensch hakt an, was ins Wiki soll.

Fenster „Aus dem Dokument“ über dem Wiki-Fenster (höchstens eines). Ein Hintergrund-Lauf (`Lauf`, Meldungen über ein
Postfach, kein Tkinter im Thread) fragt je Dokument die KI (wissen_ki.baue_prompt / lies_json) und lässt den Code
prüfen (wissen_ki.pruefe_dinge). Die Vollautomatik pausiert solange. Höchstens `wissen_ki.HOECHSTENS` Dokumente je Lauf.

Die Liste zeigt je „Ding“ eine Zeile (Schublade: Bezeichnung) und darunter seine Angaben mit Zitat und Dokument:
- Was es im Wiki schon gibt, ist als „schon im Wiki“ markiert: Es bekommt nur die neuen Angaben und das Dokument als
  Beleg, kein zweiter Eintrag entsteht. Erkannt wird es an denselben Zitaten aus demselben Dokument (auch nach einer
  Umbenennung, `wissen_ki.finde_ueber_zitate`), sonst am Namen in beliebiger Schreibweise (`finde_eintrag`). Angaben,
  die dort schon stehen (gleiches Zitat oder sinngleich), erscheinen nicht noch einmal (`neue_angaben`).
- „Zuordnen…“ ändert das von Hand: ein anderer vorhandener Eintrag, oder ein neuer Eintrag in einer Schublade nach Wahl.
- Was der Mensch beim Übernehmen abgehakt lässt, merkt sich das Wiki je Dokument als abgelehnt (`wissen.ablehnen`,
  ebenso „Entfernen“ einer Angabe aus einem Dokument im Wiki-Fenster). Ein neuer Lauf über dasselbe Dokument zeigt es
  nicht wieder (`wissen_ki.ist_abgelehnt`); ein Eintrag, von dem nur Abgelehntes käme, fällt ganz weg. Schlecht
  erkannte Einträge, die der Mensch gar nicht angehakt hatte, gelten nicht als abgelehnt.
- Eine Schublade, die es noch nicht gibt, ist als „neue Schublade“ markiert und entsteht erst mit dem Übernehmen.
- Dinge aus schlecht erkanntem Text (`wissen_ki.text_guete`) sind markiert und nicht vorgehakt.
- Ein Klick in die erste Spalte hakt an oder ab; die Bezeichnung lässt sich vor dem Übernehmen ändern (Doppelklick
  auf den Eintrag). Ein Doppelklick auf eine Angabe zeigt ihr Dokument im Hauptfenster.
„Übernehmen“ legt die angehakten Dinge an bzw. ergänzt sie, trägt die Dokumente als Belege ein und verbindet auf Wunsch
die Einträge aus demselben Dokument. Vorher steht nichts im Wiki. Ins Protokoll nur Zahlen.
"""
import collections
import os
import queue
import threading
import time
import tkinter as tk
import tkinter.messagebox as mb
import tkinter.simpledialog as simpledialog
from tkinter import ttk

import ollama_client
import wissen
import wissen_ki
from pdf_handler import PDFHandler
from ui_utils import Tooltip, UIUtils

HAKEN, OHNE_HAKEN = "☑", "☐"


def dokumente_aus_belegen(app, belege):
    """Belege eines Eintrags → Dokumente für den Lauf ([{rel_path, titel}], Zahl nicht gefundener). Je Dokument einmal."""
    index = getattr(app, "index_manager", None)
    dokumente, fehlt, gesehen = [], 0, set()
    for b in belege:
        rel = index.pfad_zur_kid_id(b["kid_id"]) if index else None
        if not rel:
            fehlt += 1
        elif rel not in gesehen:
            gesehen.add(rel)
            dokumente.append({"rel_path": rel, "titel": b["titel"]})
    return dokumente, fehlt


def lege_zusammen(je_dokument):
    """Dinge aus mehreren Dokumenten zusammenlegen: gleiche Bezeichnung (Schreibweise egal) = ein Ding.
    :param je_dokument: [(dokument, [Dinge aus wissen_ki.pruefe_dinge], schlecht_erkannt)]
    :return: [{schublade, bezeichnung, angaben: [{text, zitat, dok}], doks: [dokument], schlecht}] - `schlecht`, wenn
             alle Quellen schlecht erkannt sind. Reine Funktion."""
    gruppen = collections.OrderedDict()
    for dok, dinge, schlecht in je_dokument:
        for d in dinge:
            g = gruppen.setdefault(d["bezeichnung"].casefold(), {"schublade": d["schublade"], "bezeichnung": d["bezeichnung"],
                                                                 "angaben": [], "doks": [], "schlecht": True})
            g["schlecht"] = g["schlecht"] and schlecht
            if dok not in g["doks"]:
                g["doks"].append(dok)
            schon = {a["text"].casefold() for a in g["angaben"]}
            g["angaben"] += [{"text": a["text"], "zitat": a["zitat"], "dok": dok} for a in d["angaben"]
                             if a["text"].casefold() not in schon]
    return list(gruppen.values())


class Lauf:
    """Liest die Dokumente nacheinander (Hintergrund-Thread) und legt Meldungen ins Postfach:
    ("stand", n, gesamt, sekunden_bisher), ("fertig", ergebnis) oder ("fehler", text)."""

    def __init__(self, app, dokumente, base_url, model, schubladen, bekannte):
        self.app, self.dokumente = app, dokumente[:wissen_ki.HOECHSTENS]
        self.base_url, self.model = base_url, model
        self.schubladen, self.bekannte = list(schubladen), list(bekannte)
        self.postfach = queue.Queue()
        self.abbrechen = threading.Event()

    def starte(self):
        threading.Thread(target=self.arbeite, daemon=True).start()

    def arbeite(self):
        index = getattr(self.app, "index_manager", None)
        je_dokument, verworfen, zahlen = [], collections.Counter(), collections.Counter()
        start = time.time()
        for n, dok in enumerate(self.dokumente):
            if self.abbrechen.is_set():
                zahlen["abgebrochen"] = 1
                break
            self.postfach.put(("stand", n, len(self.dokumente), time.time() - start))
            try:
                text = index.wiki_text(dok["rel_path"])[0] if index else ""
            except Exception:                                 # noqa: BLE001 - Index gesperrt: Dokument zählt als ohne Text
                text = ""
            if len(text.strip()) < wissen_ki.MIN_TEXT:
                zahlen["ohne_text"] += 1
                continue
            schlecht = wissen_ki.text_guete(text) < wissen_ki.GUETE_MIN
            prompt = wissen_ki.baue_prompt(text, dok["titel"], self.schubladen, self.bekannte)
            try:
                antwort, _sek = wissen_ki.lies_json(prompt, self.base_url, self.model)
            except OSError as fehler:                          # Server weg: der ganze Lauf endet hier
                self.postfach.put(("fehler", f"Der KI-Server antwortet nicht ({type(fehler).__name__})."))
                return
            except wissen_ki.UnbrauchbareAntwort:
                zahlen["unbrauchbar"] += 1
                continue
            except Exception:                                 # noqa: BLE001 - ein Dokument darf den Lauf nicht beenden
                zahlen["fehler"] += 1
                continue
            dinge, weg = wissen_ki.pruefe_dinge(antwort, text)
            verworfen.update(weg)
            zahlen["gelesen"] += 1
            zahlen["schlecht"] += schlecht
            je_dokument.append((dok, dinge, schlecht))
        zahlen["sekunden"] = round(time.time() - start)
        self.postfach.put(("fertig", {"dinge": lege_zusammen(je_dokument), "verworfen": verworfen, "zahlen": zahlen}))


class DingeFenster(tk.Toplevel):
    """Was kommt in den Dokumenten vor? Startet den Lauf sofort; `wiki` ist das Wiki-Fenster."""

    def __init__(self, wiki, dokumente):
        super().__init__(wiki)
        self.withdraw()                                   # erst aufbauen, dann zeigen (FALLSTRICKE #90)
        UIUtils.werkzeugfenster(self, wiki)
        self.wiki, self.app = wiki, wiki.app
        self.title("Aus dem Dokument" if len(dokumente) == 1 else f"Aus {len(dokumente)} Dokumenten")
        self.dinge, self.ziel = [], {}                    # Dinge des Laufs; Nr. → vorhandener Eintrag (schon im Wiki)
        self.dinge_an, self.angaben_an = set(), set()     # angehakt: Nr. des Dings bzw. (Nr., Nr. der Angabe)
        self._dienst = getattr(self.app, "auto_pilot_service", None)
        self._pausiert = False
        self._baue()
        self.protocol("WM_DELETE_WINDOW", self._schliessen)
        self.update_idletasks()
        UIUtils.position_near_mouse(self, UIUtils.px(self, 1000), UIUtils.px(self, 560))
        self.deiconify()
        config = self.app.config
        self.lauf = Lauf(self.app, dokumente, config.get("ollama_url", ollama_client.DEFAULT_URL),
                         config.get("ollama_model", ollama_client.DEFAULT_MODEL),
                         [a["name"] for a in wiki.wissen.arten()], [e["bezeichnung"] for e in wiki.wissen.liste()])
        weg = len(dokumente) - len(self.lauf.dokumente)
        self._hinweis_menge = (f" (die ersten {wissen_ki.HOECHSTENS}; {weg} weitere bitte in einem zweiten Lauf)"
                               if weg > 0 else "")
        if self._dienst is not None:
            self._dienst.pausieren()
            self._pausiert = True
        self._laeuft = True
        self.lauf.starte()
        self._melde_stand(0, len(self.lauf.dokumente), 0)
        self._hole()

    # ---------------------------------------------------------------- Aufbau
    def _baue(self):
        rand = UIUtils.px(self, 10)
        unten = ttk.Frame(self)                           # Knopfleiste VOR dem dehnbaren Inhalt mit side=BOTTOM
        unten.pack(side=tk.BOTTOM, fill=tk.X, padx=rand, pady=(4, rand))
        self.btn_abbrechen = ttk.Button(unten, text="Abbrechen", command=self._schliessen)
        self.btn_abbrechen.pack(side=tk.RIGHT)
        self.btn_uebernehmen = ttk.Button(unten, text="Übernehmen", command=self._uebernehmen, state=tk.DISABLED)
        self.btn_uebernehmen.pack(side=tk.RIGHT, padx=6)
        self.btn_name = ttk.Button(unten, text="Bezeichnung ändern…", command=self._umbenennen, state=tk.DISABLED)
        self.btn_name.pack(side=tk.LEFT)
        self.btn_ziel = ttk.Button(unten, text="Zuordnen…", command=self._zuordnen_menue, state=tk.DISABLED)
        self.btn_ziel.pack(side=tk.LEFT, padx=(6, 0))
        Tooltip(self.btn_ziel, "Den markierten Eintrag einem vorhandenen Wiki-Eintrag zuordnen (er wird dann ergänzt) "
                               "oder als neuen Eintrag in eine andere Schublade legen.")
        self.menue_ziel = tk.Menu(self, tearoff=0)
        Tooltip(self.btn_name, "Den Namen des markierten Eintrags vor dem Übernehmen ändern (auch per Doppelklick). "
                               "Heißt er dann wie ein vorhandener Eintrag, wird dieser ergänzt.")
        self.var_verbinden = tk.BooleanVar(value=True)
        chk = ttk.Checkbutton(unten, text="Einträge aus demselben Dokument verbinden", variable=self.var_verbinden)
        chk.pack(side=tk.LEFT, padx=12)
        Tooltip(chk, "Die übernommenen Einträge stehen danach gegenseitig unter „Verbunden mit“ - etwa das Haus und "
                     "die Firma, die dort etwas geprüft hat.")
        self.lbl_status = ttk.Label(self, foreground="gray40", wraplength=UIUtils.px(self, 960), justify=tk.LEFT)
        self.lbl_status.pack(fill=tk.X, padx=rand, pady=(rand, 2))
        self.balken = ttk.Progressbar(self, mode="determinate")
        self.balken.pack(fill=tk.X, padx=rand, pady=(0, 4))
        rahmen = ttk.Frame(self)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=rand)
        self.tree = ttk.Treeview(rahmen, columns=("zitat", "quelle"), selectmode="browse")
        self.tree.heading("#0", text="Eintrag und Angaben", anchor="w")
        self.tree.heading("zitat", text="im Dokument", anchor="w")
        self.tree.heading("quelle", text="Dokument", anchor="w")
        self.tree.column("#0", width=UIUtils.px(self, 470), anchor="w")
        self.tree.column("zitat", width=UIUtils.px(self, 300), anchor="w")
        self.tree.column("quelle", width=UIUtils.px(self, 180), anchor="w")
        self.tree.tag_configure("ding", font=("", UIUtils.schriftgroesse(self, 0), "bold"))
        self.tree.tag_configure("aus", foreground="gray55")
        rolle = ttk.Scrollbar(rahmen, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=rolle.set)
        rolle.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<Button-1>", self._klick)
        self.tree.bind("<Double-1>", lambda _e: self._doppelklick())
        self.tree.bind("<space>", lambda _e: self._schalte_markierte())
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._summe())

    # ---------------------------------------------------------------- Lauf
    def _hole(self):
        """Postfach des Laufs abholen (Haupt-Thread)."""
        if not self.winfo_exists():
            return
        try:
            while True:
                meldung = self.lauf.postfach.get_nowait()
                if meldung[0] == "stand":
                    self._melde_stand(*meldung[1:])
                elif meldung[0] == "fertig":
                    self._fertig(meldung[1])
                    return
                elif meldung[0] == "fehler":
                    self._lauf_ende()
                    self.lbl_status.config(text=meldung[1] + " Bitte prüfen, ob der KI-Server läuft, und es noch einmal "
                                                             "versuchen.")
                    self._log("Wiki-KI: Lauf abgebrochen, KI-Server antwortet nicht", "warning")
                    return
        except queue.Empty:
            pass
        self._after = self.after(100, self._hole)

    def _melde_stand(self, n, gesamt, sekunden):
        self.balken.config(maximum=max(1, gesamt), value=n)
        je = sekunden / n if n else wissen_ki.SEKUNDEN_JE_DOKUMENT
        was = "das Dokument" if gesamt == 1 else f"Dokument {n + 1} von {gesamt}"
        self.lbl_status.config(text=f"Die KI liest {was}, noch {wissen_ki.dauer_text(je * (gesamt - n))}…"
                                    f"{self._hinweis_menge}" + ("  - wird abgebrochen…" if self.lauf.abbrechen.is_set() else ""))

    def _lauf_ende(self):
        self._laeuft = False
        if self._pausiert:
            self._pausiert = False
            self._dienst.fortsetzen()
        self.btn_abbrechen.config(text="Schließen")
        self.balken.pack_forget()

    def _fertig(self, ergebnis):
        self._lauf_ende()
        z, verworfen = ergebnis["zahlen"], ergebnis["verworfen"]
        self.dinge, n_abgelehnt = self._ohne_abgelehnte(ergebnis["dinge"])
        for i, d in enumerate(self.dinge):
            d["alle"] = list(d["angaben"])                # wie die KI sie nannte; „angaben“ = was davon neu ist
            self._ordne_zu(i, self._finde_ziel(d))
            if not d["schlecht"]:
                self.dinge_an.add(i)
        n_angaben = sum(len(d["angaben"]) for d in self.dinge)
        teile = [f"{z['gelesen']} Dokument{'' if z['gelesen'] == 1 else 'e'} gelesen in {z['sekunden']} s",
                 f"{len(self.dinge)} Eintr{'ag' if len(self.dinge) == 1 else 'äge'} mit {n_angaben} Angaben"]
        if n_abgelehnt:
            teile.append(f"{n_abgelehnt} früher abgelehnte Angabe{'' if n_abgelehnt == 1 else 'n'} ausgeblendet")
        if sum(verworfen.values()):
            teile.append(f"{sum(verworfen.values())} aussortiert (" + ", ".join(
                f"{n}× {wissen_ki.GRUENDE[g]}" for g, n in verworfen.most_common()) + ")")
        for schluessel, text in (("ohne_text", "ohne erkannten Text"), ("schlecht", "mit schlecht erkanntem Text"),
                                 ("unbrauchbar", "KI-Antwort unbrauchbar"), ("fehler", "Fehler")):
            if z.get(schluessel):
                teile.append(f"{z[schluessel]} {text}")
        if z.get("abgebrochen"):
            teile.append("abgebrochen")
        self.lbl_status.config(text=" · ".join(teile) + (". Bitte prüfen und abwählen, was nicht ins Wiki soll."
                                                         if self.dinge else ". Nichts gefunden, das sich belegen lässt."))
        self._log(f"Wiki-KI: {z['gelesen']} gelesen in {z['sekunden']} s, {len(self.dinge)} Dinge, {n_angaben} Angaben, "
                  f"{len(self.ziel)} schon im Wiki, {n_abgelehnt} früher abgelehnt, "
                  f"{sum(verworfen.values())} aussortiert ({dict(verworfen)}), "
                  f"{z.get('ohne_text', 0)} ohne Text, {z.get('schlecht', 0)} schlecht erkannt, "
                  f"{z.get('unbrauchbar', 0)} unbrauchbar, {z.get('fehler', 0)} Fehler")
        self._fuelle()

    def _kid_id(self, dok):
        """Dokument-ID eines Dokuments des Laufs, nur gelesen (vergibt keine). "" ohne ID."""
        merk = self.__dict__.setdefault("_kids", {})
        if dok["rel_path"] not in merk:
            merk[dok["rel_path"]] = (PDFHandler.get_metadata(os.path.join(self.app.master_folder, dok["rel_path"]))
                                     .get("KID_ID") or "").strip()
        return merk[dok["rel_path"]]

    def _ohne_abgelehnte(self, dinge):
        """Früher Abgelehntes herausnehmen. :return: (Dinge, Zahl ausgeblendeter Angaben) - ein Ding, von dem nur
        Abgelehntes käme, fällt ganz weg."""
        abgelehnte = self.wiki.wissen.abgelehnte([self._kid_id(dok) for d in dinge for dok in d["doks"]])
        if not abgelehnte:
            return dinge, 0
        bleiben, weg = [], 0
        for d in dinge:
            rest = [a for a in d["angaben"]
                    if not wissen_ki.ist_abgelehnt(a, abgelehnte.get(self._kid_id(a["dok"]), []))]
            weg += len(d["angaben"]) - len(rest)
            if rest or not d["angaben"]:
                bleiben.append(dict(d, angaben=rest))
        return bleiben, weg

    # ---------------------------------------------------------------- Zuordnung
    def _finde_ziel(self, d):
        """Der vorhandene Eintrag zu einem Ding: erst über gemeinsame Zitate aus demselben Dokument (auch umbenannte
        Einträge), sonst über den Namen. Liest nur."""
        w = self.wiki.wissen
        kid_ids = [self._kid_id(dok) for dok in d["doks"]]
        kandidaten = [w.lade(e["id"]) for e in w.eintraege_mit_beleg(kid_ids)]
        ziel = wissen_ki.finde_ueber_zitate([a["zitat"] for a in d["alle"]], [k for k in kandidaten if k])
        return ziel or wissen_ki.finde_eintrag(d["bezeichnung"], w.liste())

    def _ordne_zu(self, i, ziel):
        """Ding `i` gehört zu diesem vorhandenen Eintrag (oder None = neuer Eintrag): nur noch Angaben zeigen, die dort
        fehlen; alle gezeigten sind angehakt."""
        d = self.dinge[i]
        self.ziel.pop(i, None)
        geladen = self.wiki.wissen.lade(ziel["id"]) if ziel else None
        if geladen is not None:
            self.ziel[i] = geladen
            d["angaben"] = wissen_ki.neue_angaben(d["alle"], geladen)
        else:
            d["angaben"] = list(d["alle"])
        self.angaben_an = {(a, b) for a, b in self.angaben_an if a != i} | {(i, j) for j in range(len(d["angaben"]))}

    def _zuordnen_menue(self):
        """„Zuordnen…“: Menü am Knopf - neuer Eintrag in einer Schublade oder ein vorhandener Eintrag."""
        markiert = self.tree.selection()
        if not markiert or not markiert[0].startswith("d:"):
            return
        i = int(markiert[0][2:])
        menue = self.menue_ziel
        for kind in menue.winfo_children():
            kind.destroy()
        menue.delete(0, "end")
        neu = tk.Menu(menue, tearoff=0)
        for a in self.wiki.wissen.arten():
            neu.add_command(label=a["name"], command=lambda n=a["name"]: self.zuordnen(i, schublade=n))
        menue.add_cascade(label="Neuer Eintrag in", menu=neu)
        vorhanden = tk.Menu(menue, tearoff=0)
        gruppen = collections.OrderedDict()
        for e in self.wiki.wissen.liste():
            gruppen.setdefault(e["art_name"], []).append(e)
        for name, eintraege in gruppen.items():
            unter = tk.Menu(vorhanden, tearoff=0)
            for e in eintraege:
                unter.add_command(label=e["bezeichnung"], command=lambda z=e: self.zuordnen(i, ziel=z))
            vorhanden.add_cascade(label=name, menu=unter)
        menue.add_cascade(label="Vorhandenen Eintrag ergänzen", menu=vorhanden,
                          state=tk.NORMAL if gruppen else tk.DISABLED)
        try:
            menue.tk_popup(self.btn_ziel.winfo_rootx(), self.btn_ziel.winfo_rooty() - UIUtils.px(self, 50))
        finally:
            menue.grab_release()

    def zuordnen(self, i, ziel=None, schublade=None):
        """Ding `i` von Hand zuordnen: `ziel` = vorhandener Eintrag (wird ergänzt), sonst neuer Eintrag in `schublade`."""
        if schublade:
            self.dinge[i]["schublade"] = schublade
        self._ordne_zu(i, ziel)
        self._fuelle()
        self.tree.selection_set(f"d:{i}")

    # ---------------------------------------------------------------- Liste
    def _ding_text(self, i):
        d = self.dinge[i]
        vorhanden = {a["name"].casefold() for a in self.wiki.wissen.arten()}
        text = f"{HAKEN if i in self.dinge_an else OHNE_HAKEN} {d['schublade']}: {d['bezeichnung']}"
        if i in self.ziel:
            z = self.ziel[i]
            anders = "" if wissen_ki.kern(z["bezeichnung"]) == wissen_ki.kern(d["bezeichnung"]) else f" als „{z['bezeichnung']}“"
            text += f"   - schon im Wiki{anders}, wird ergänzt"
        elif d["schublade"].casefold() not in vorhanden:
            text += "   - neue Schublade"
        if d["schlecht"]:
            text += "   - Text schlecht erkannt"
        return text

    def _fuelle(self):
        self.tree.delete(*self.tree.get_children())
        for i, d in enumerate(self.dinge):
            an = i in self.dinge_an
            self.tree.insert("", tk.END, iid=f"d:{i}", text=self._ding_text(i), open=True,
                             tags=("ding",) if an else ("ding", "aus"),
                             values=("", ", ".join(dok["titel"] for dok in d["doks"])))
            for j, a in enumerate(d["angaben"]):
                hakt = (i, j) in self.angaben_an
                self.tree.insert(f"d:{i}", tk.END, iid=f"a:{i}:{j}", tags=() if an and hakt else ("aus",),
                                 text=f"{HAKEN if hakt else OHNE_HAKEN} {a['text']}",
                                 values=(f"„{a['zitat']}“", a["dok"]["titel"]))
        self._summe()

    def _schalte(self, iid):
        teile = iid.split(":")
        if teile[0] == "d":
            self.dinge_an ^= {int(teile[1])}
        else:
            self.angaben_an ^= {(int(teile[1]), int(teile[2]))}
        markiert = self.tree.selection()
        self._fuelle()
        if markiert and self.tree.exists(markiert[0]):
            self.tree.selection_set(markiert[0])

    def _klick(self, event):
        """Ein Klick in die erste Spalte hakt die Zeile an oder ab (und markiert sie); ein Klick in die anderen
        Spalten markiert nur. Das Dreieck zum Auf- und Zuklappen bleibt, was es ist."""
        zeile = self.tree.identify_row(event.y)
        if zeile and self.tree.identify_column(event.x) == "#0" and "indicator" not in str(
                self.tree.identify_element(event.x, event.y)):
            self.tree.selection_set(zeile)
            self._schalte(zeile)
            return "break"
        return None

    def _schalte_markierte(self):
        for zeile in self.tree.selection():
            self._schalte(zeile)

    def _summe(self):
        n = len(self.dinge_an)
        self.btn_uebernehmen.config(text=f"{n} Eintr{'ag' if n == 1 else 'äge'} übernehmen" if n else "Übernehmen",
                                    state=tk.NORMAL if n and not self._laeuft else tk.DISABLED,
                                    style="Accent.TButton" if n else "TButton")
        markiert = self.tree.selection()
        for knopf in (self.btn_name, self.btn_ziel):
            knopf.config(state=tk.NORMAL if markiert and markiert[0].startswith("d:") else tk.DISABLED)

    def _doppelklick(self):
        """Auf einen Eintrag: Bezeichnung ändern. Auf eine Angabe: ihr Dokument im Hauptfenster zeigen (Peter
        13.11.2026), zum Vergleichen mit dem Zitat."""
        markiert = self.tree.selection()
        if not markiert:
            return
        if markiert[0].startswith("d:"):
            self._umbenennen()
            return
        _, i, j = markiert[0].split(":")
        dok = self.dinge[int(i)]["angaben"][int(j)]["dok"]
        folder_manager = getattr(self.app, "folder_manager", None)
        if folder_manager is None or not folder_manager.zeige_dokument(os.path.join(self.app.master_folder, dok["rel_path"])):
            mb.showinfo("Aus dem Dokument", "Das Dokument ist in der Sammlung nicht (mehr) zu finden.", parent=self)

    def _umbenennen(self):
        markiert = self.tree.selection()
        if not markiert or not markiert[0].startswith("d:"):
            return
        i = int(markiert[0][2:])
        name = simpledialog.askstring("Bezeichnung ändern", "Wie soll der Eintrag heißen?",
                                      initialvalue=self.dinge[i]["bezeichnung"], parent=self)
        name = " ".join((name or "").split())
        if not name or name == self.dinge[i]["bezeichnung"]:
            return
        self.dinge[i]["bezeichnung"] = name
        if i not in self.ziel:                            # heißt er jetzt wie ein vorhandener, wird der ergänzt
            self._ordne_zu(i, wissen_ki.finde_eintrag(name, self.wiki.wissen.liste()))
        self._fuelle()
        self.tree.selection_set(f"d:{i}")

    # ---------------------------------------------------------------- Übernehmen
    def _uebernehmen(self):
        if not self.dinge_an or self._laeuft:
            return
        w = self.wiki
        if not w._weiter_trotz_aenderung():               # ungespeicherte Eingaben im Wiki: Nutzer hat abgebrochen
            return
        kid_ids, je_dok, erster = {}, collections.defaultdict(list), None
        zahlen = collections.Counter()

        def kid_id(dok):
            if dok["rel_path"] not in kid_ids:
                kid_ids[dok["rel_path"]] = PDFHandler.ensure_kid_id(os.path.join(self.app.master_folder, dok["rel_path"]))
                zahlen["ohne_id"] += not kid_ids[dok["rel_path"]]
            return kid_ids[dok["rel_path"]]

        for i in sorted(self.dinge_an):
            d = self.dinge[i]
            try:
                ziel = self.ziel.get(i)
                if ziel is not None and w.wissen.lade(ziel["id"]) is not None:
                    eintrag_id = ziel["id"]
                    zahlen["ergaenzt"] += 1
                else:
                    eintrag_id = w.wissen.speichere(d["schublade"], d["bezeichnung"])
                    zahlen["neu"] += 1
                for dok in d["doks"]:
                    if kid_id(dok):
                        zahlen["belege"] += w.wissen.beleg_hinzu(eintrag_id, kid_id(dok), dok["titel"])
                    je_dok[dok["rel_path"]].append(eintrag_id)
                for j, a in enumerate(d["angaben"]):
                    if (i, j) in self.angaben_an:
                        kid = kid_id(a["dok"])
                        neu = w.wissen.angabe_hinzu(eintrag_id, a["text"], kid, a["dok"]["titel"] if kid else "",
                                                    a["zitat"] if kid else "")
                        zahlen["angaben"] += neu is not None
            except wissen.Eingabefehler as fehler:
                mb.showwarning("Aus dem Dokument", f"„{d['bezeichnung']}“ ließ sich nicht übernehmen:\n{fehler}", parent=self)
                continue
            erster = erster or eintrag_id
        # Was abgehakt blieb, ist abgelehnt - je Dokument gemerkt (schlecht erkannte, nie angehakte zählen nicht)
        abgelehnt = collections.defaultdict(list)
        for i, d in enumerate(self.dinge):
            if i not in self.dinge_an and d["schlecht"]:
                continue
            for j, a in enumerate(d["angaben"]):
                if i not in self.dinge_an or (i, j) not in self.angaben_an:
                    abgelehnt[kid_ids.get(a["dok"]["rel_path"]) or self._kid_id(a["dok"])].append(a)
        for kid, angaben in abgelehnt.items():
            zahlen["abgelehnt"] += w.wissen.ablehnen(kid, angaben)
        if self.var_verbinden.get():
            for ids in je_dok.values():
                for n, a in enumerate(ids):
                    for b in ids[n + 1:]:
                        if a != b:
                            zahlen["verbunden"] += w.wissen.verbinde(a, b)
        self._log(f"Wiki-KI: {zahlen['neu']} Einträge neu, {zahlen['ergaenzt']} ergänzt, {zahlen['angaben']} Angaben, "
                  f"{zahlen['belege']} Belege, {zahlen['verbunden']} Verbindungen, {zahlen['abgelehnt']} abgelehnt gemerkt")
        if zahlen["ohne_id"]:
            mb.showwarning("Aus dem Dokument", f"{zahlen['ohne_id']} Dokument(e) ließen sich nicht als Beleg eintragen: "
                                               "Sie bekommen keine Dokument-ID (schreibgeschützt oder gerade geöffnet?). "
                                               "Die Angaben stehen ohne Zitat im Wiki.", parent=self)
        if erster and w.winfo_exists():
            w.nach_aenderung(erster)
        self._schliessen()

    # ---------------------------------------------------------------- Schließen, Protokoll
    def _schliessen(self):
        if self._laeuft:
            self.lauf.abbrechen.set()                     # das laufende Dokument liest die KI noch zu Ende
        self.destroy()

    def destroy(self):
        if getattr(self, "_after", None) is not None:     # sonst feuert das Abholen nach dem Schließen ins Leere
            self.after_cancel(self._after)
            self._after = None
        if getattr(self, "_laeuft", False):
            self.lauf.abbrechen.set()
        if getattr(self, "_pausiert", False):             # Vollautomatik nie angehalten zurücklassen
            self._pausiert = False
            self._dienst.fortsetzen()
        super().destroy()

    def _log(self, text, stufe="info"):
        """Nur Zahlen, nie Namen oder Werte (Datenschutz)."""
        logger = getattr(self.app, "logger", None)
        if logger is not None:
            getattr(logger, stufe)(text)
