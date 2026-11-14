"""
Tag-Hygiene (Nutzerwunsch 03.09.2026): Tags, die nur an 1-2 Dokumenten hängen,
sind meist Rauschen - "Ich will mehrere Dokumente unter einem Tag haben; ein Tag,
das nur ein- oder zweimal vorkommt, ist sinnlos, die Dokumente findet die
Textsuche genauso schnell." Im Kaltstart-Test hingen 99 von 162 Tags (61 %) an
höchstens zwei Dokumenten.

Das Tool zeigt diese Einzelgänger mit Kategorie, Anzahl und Dokumenten; der
Nutzer hakt ab, was wegkommt. Entfernen heißt: Tag aus den PDF-Metadaten der
betroffenen Dokumente löschen (Titel und übrige Tags bleiben), aus dem Katalog
nehmen und auf die Ignorierliste setzen, damit die Vollautomatik es nicht beim
nächsten Dokument wieder anlegt (Nutzer-Entscheidung 03.09.2026: automatisch).

Bewusst NICHT als Kandidat gelistet:
- Struktur-Knoten (graue Kategorien),
- Katalog-Tags mit Unter-Tags (kuratierte Hierarchie wie "Musterstadt" > "Weidenstraße 8"),
denn Einzelgänger sind nicht automatisch sinnlos - "Weidenstr. 8 Whg 3" mit einem
Dokument ist die Basis der Dubletten-Unterscheidung. Deshalb entscheidet der Mensch.

Zweiter Knopf (08.09.2026): "Synonyme im Bestand ersetzen" - Dokumente, die noch den
Text eines Synonym-Knotens tragen (Altbestand, oder das Tag wurde erst nachträglich
zum Synonym erklärt), bekommen stattdessen das Ziel-Tag samt Oberkategorien, genau
wie es die Vollautomatik für neue Dokumente tut (auto_pilot.ersetze_synonyme).

Dritter Knopf (28.10.2026): "Standard-Synonyme übernehmen" - tags_default.json wird nur beim
ersten Start kopiert, bestehende Kataloge bekommen die mitgelieferten Synonyme so nachträglich
(plane_standard_synonyme: nur unter vorhandene Ziel-Tags, nie über ein eigenes Tag hinweg).
Vierter Knopf (28.10.2026): "Sammel-Tags zerlegen" - Objekt-Tags aus der Zeit vor „ein Objekt
je Tag“ ('Zum Alten Fass 1 u. 3') werden in Dokumenten und Katalog zu Einzel-Tags
(plane_sammel_zerlegung, dieselbe Regel auto_pilot.teile_objekte wie bei neuen Dokumenten).
"""

import json
import os
import re
import tkinter as tk
import tkinter.messagebox as mb
import aktivitaet
import bestaetigung
from tkinter import ttk

import app_paths
import auto_pilot
import tag_ignorierliste
from pdf_handler import PDFHandler
from tools.base_tool import BaseTool, ToolContext
from ui_utils import UIUtils, ProgressDialog, Tooltip

SCHWELLE_STANDARD = 2


def sammle_tag_vorkommen(master_folder, ist_papierkorb=None):
    """
    {Tag-Text: [relative Pfade]} über alle PDFs der Sammlung (ohne Papierkorb).
    Reine Lesefunktion; Groß/Kleinschreibung: der zuerst gesehene Text gewinnt.
    """
    vorkommen = {}
    schluessel = {}  # lower -> kanonischer Text
    for wurzel, dirs, files in os.walk(master_folder):
        if ist_papierkorb is not None:
            dirs[:] = [d for d in dirs if not ist_papierkorb(os.path.join(wurzel, d))]
        for name in files:
            if not name.lower().endswith(".pdf"):
                continue
            pfad = os.path.join(wurzel, name)
            meta = PDFHandler.get_metadata(pfad) or {}
            rel = os.path.relpath(pfad, master_folder)
            for tag in (meta.get("keywords") or "").split(","):
                tag = tag.strip()
                if not tag:
                    continue
                kanon = schluessel.setdefault(tag.lower(), tag)
                vorkommen.setdefault(kanon, []).append(rel)
    return vorkommen


def finde_einzelgaenger(vorkommen, schwelle=SCHWELLE_STANDARD, katalog_info=None):
    """
    Die Aufräum-Kandidaten: Tags mit höchstens `schwelle` Dokumenten.
    :param katalog_info: {tag.lower(): (kategorie, hat_kinder, ist_struktur)} aus dem
                         Tag-Baum; Tags mit Kindern oder Struktur-Knoten fliegen raus.
    :return: Liste (tag, kategorie, [relative Pfade]), sortiert nach Kategorie und Tag
    """
    katalog_info = katalog_info or {}
    kandidaten = []
    for tag, pfade in vorkommen.items():
        if len(pfade) > schwelle:
            continue
        kategorie, hat_kinder, ist_struktur = katalog_info.get(tag.lower(), ("(nicht im Katalog)", False, False))
        if hat_kinder or ist_struktur:
            continue
        kandidaten.append((tag, kategorie, sorted(pfade)))
    return sorted(kandidaten, key=lambda k: (k[1].lower(), k[0].lower()))


def entferne_tag_aus_dokumenten(master_folder, tag, rel_pfade, logger=None, fehler=None):
    """
    Löscht EIN Tag aus den PDF-Metadaten der genannten Dokumente - Titel und alle
    übrigen Tags bleiben unangetastet (gleicher Lese-Ändere-Schreibe-Weg wie
    save_manager.ergaenze_tags_fuer_auswahl, nur pfad- statt auswahlbasiert).
    :param fehler: optionale Liste, in die nicht schreibbare Dokumente (relativer Pfad)
                   eingetragen werden - der Aufrufer meldet sie gesammelt statt mit einem
                   Popup pro Datei (Live-Fund 08.09.2026: PDF in der Anzeige offen).
    :return: Anzahl tatsächlich geänderter Dokumente
    """
    geaendert = 0
    for rel in rel_pfade:
        pfad = os.path.join(master_folder, rel)
        if not os.path.exists(pfad):
            continue
        meta = PDFHandler.get_metadata(pfad) or {}
        vorhanden = [t.strip() for t in (meta.get("keywords") or "").split(",") if t.strip()]
        neu = [t for t in vorhanden if t.lower() != tag.lower()]
        if neu == vorhanden:
            continue
        erfolg, msg = PDFHandler.save_metadata(pfad, meta.get("title", ""), ", ".join(neu), still=True)
        if erfolg:
            geaendert += 1
            if logger:
                logger.info(f"Tag-Hygiene: '{tag}' entfernt aus {pfad}")
        else:
            if fehler is not None:
                fehler.append(rel)
            if logger:
                logger.error(f"Tag-Hygiene: Schreiben fehlgeschlagen für {pfad}: {msg}")
    return geaendert


def plane_synonym_ersetzungen(vorkommen, synonyme):
    """
    Welche Dokumente tragen noch einen Synonym-Text? :param vorkommen: sammle_tag_vorkommen
    :param synonyme: {synonym (klein): Ziel-Tag} (tag_manager.get_synonyme)
    :return: Liste (Synonym-Text wie im Bestand, Ziel-Tag, [relative Pfade]), sortiert nach Ziel/Synonym
    """
    plan = []
    for tag, pfade in (vorkommen or {}).items():
        ziel = (synonyme or {}).get(tag.strip().lower())
        if ziel:
            plan.append((tag, ziel, sorted(pfade)))
    return sorted(plan, key=lambda p: (p[1].lower(), p[0].lower()))


def ersetze_synonyme_in_dokumenten(master_folder, rel_pfade, synonyme, tag_eltern=None, logger=None, fehler=None):
    """
    Tauscht in den PDF-Metadaten der genannten Dokumente jeden Synonym-Text gegen sein
    Ziel-Tag (plus dessen Oberkategorien, Auto-Hierarchie wie in der Vollautomatik);
    Titel und übrige Tags bleiben. Jedes Dokument wird nur einmal angefasst, auch wenn
    es mehrere Synonyme trägt.
    :return: Anzahl tatsächlich geänderter Dokumente
    """
    geaendert = 0
    for rel in dict.fromkeys(rel_pfade):
        pfad = os.path.join(master_folder, rel)
        if not os.path.exists(pfad):
            continue
        meta = PDFHandler.get_metadata(pfad) or {}
        vorhanden = [t.strip() for t in (meta.get("keywords") or "").split(",") if t.strip()]
        neu, ersetzungen = auto_pilot.ersetze_synonyme(vorhanden, synonyme)
        if not ersetzungen:
            continue
        neu = auto_pilot.ergaenze_oberkategorien(neu, tag_eltern)
        erfolg, msg = PDFHandler.save_metadata(pfad, meta.get("title", ""), ", ".join(neu), still=True)
        if erfolg:
            geaendert += 1
            if logger:
                logger.info(f"Tag-Hygiene: Synonyme ersetzt in {pfad}: "
                            + ", ".join(f"{a} -> {z}" for a, z in ersetzungen))
        else:
            if fehler is not None:
                fehler.append(rel)
            if logger:
                logger.error(f"Tag-Hygiene: Schreiben fehlgeschlagen für {pfad}: {msg}")
    return geaendert


def plane_sammel_zerlegung(vorkommen):
    """
    Sammel-Tags im Bestand: Objekt-Tags aus der Zeit vor der Regel „ein Objekt je Tag“
    (27.10.2026, FALLSTRICKE #82) wie 'Zum Alten Fass 1 u. 3'. Zerlegt wird mit derselben
    Regel wie bei neuen Dokumenten (auto_pilot.teile_objekte); nur Tags mit Ziffern kommen in
    Frage - Namen wie 'Müller und Söhne' bleiben, wie sie sind.
    :return: Liste (Tag, [Einzel-Tags], [relative Pfade]), sortiert nach Tag
    """
    plan = []
    for tag, pfade in (vorkommen or {}).items():
        if not re.search(r"\d", tag):
            continue
        teile = auto_pilot.teile_objekte(tag)
        if len(teile) > 1:
            plan.append((tag, teile, sorted(pfade)))
    return sorted(plan, key=lambda p: p[0].lower())


def zerlege_tags(tags, zerlegung):
    """
    Ersetzt in einer Tag-Liste jedes Sammel-Tag an seiner Stelle durch die Einzel-Tags
    (doppelte fallen weg, Reihenfolge bleibt). :param zerlegung: {sammel-tag (klein): [Einzel-Tags]}
    :return: (neue Liste, geändert?)
    """
    neu, gesehen, geaendert = [], set(), False
    for tag in tags:
        teile = zerlegung.get(tag.strip().lower())
        if teile:
            geaendert = True
        for t in teile or [tag]:
            if t.lower() not in gesehen:
                gesehen.add(t.lower())
                neu.append(t)
    return neu, geaendert


def zerlege_sammel_tags_in_dokumenten(master_folder, rel_pfade, zerlegung, logger=None, fehler=None):
    """Schreibt zerlege_tags in die PDF-Metadaten (Titel und übrige Tags bleiben). :return: Anzahl geänderter Dokumente"""
    geaendert = 0
    for rel in dict.fromkeys(rel_pfade):
        pfad = os.path.join(master_folder, rel)
        if not os.path.exists(pfad):
            continue
        meta = PDFHandler.get_metadata(pfad) or {}
        vorhanden = [t.strip() for t in (meta.get("keywords") or "").split(",") if t.strip()]
        neu, anders = zerlege_tags(vorhanden, zerlegung)
        if not anders:
            continue
        erfolg, msg = PDFHandler.save_metadata(pfad, meta.get("title", ""), ", ".join(neu), still=True)
        if erfolg:
            geaendert += 1
            if logger:
                logger.info(f"Tag-Hygiene: Sammel-Tags zerlegt in {pfad}: {', '.join(vorhanden)} -> {', '.join(neu)}")
        else:
            if fehler is not None:
                fehler.append(rel)
            if logger:
                logger.error(f"Tag-Hygiene: Schreiben fehlgeschlagen für {pfad}: {msg}")
    return geaendert


def standard_synonyme(vorlage):
    """
    [(Ziel-Tag, Synonym-Text)] aus der Vorlage (tags_default.json-Struktur): jeder Synonym-Knoten
    mit dem nächsten zuweisbaren Tag darüber - dieselbe Regel wie tag_manager.get_synonyme,
    ein Synonym ohne solches Tag (nur graue Kategorien darüber) fällt weg.
    """
    paare = []

    def walk(knoten, ziel):
        for k in knoten or []:
            text = (k.get("text") or "").strip()
            if not text:
                continue
            if k.get("is_synonym"):
                if ziel:
                    paare.append((ziel, text))
                continue
            walk(k.get("children"), ziel if k.get("is_structural") else text)

    walk(vorlage, "")
    return paare


def plane_standard_synonyme(vorlage, katalog):
    """
    Welche Synonyme der mitgelieferten Vorlage fehlen im Katalog der Sammlung? Die Vorlage wird
    nur beim allerersten Start kopiert - bestehende Kataloge bekämen neue Standard-Synonyme
    sonst nie (ToDo 27.10.2026). Übernommen wird nur, was sicher passt:
    - das Ziel-Tag steht im Katalog als zuweisbares Tag (nicht grau, kein Synonym),
    - der Synonym-Text kommt im Katalog noch nirgends vor (auch nicht als eigenes Tag - das
      wäre eine Entscheidung des Nutzers, kein Nachtrag).
    :param katalog: Knotenliste wie tags.json (tag_editor._get_nodes)
    :return: Liste (Ziel-Tag in Katalog-Schreibweise, Synonym-Text), sortiert nach Ziel/Synonym
    """
    alle, zuweisbar = set(), {}

    def walk(knoten):
        for k in knoten or []:
            text = (k.get("text") or "").strip()
            if not text:
                continue
            alle.add(text.lower())
            if not k.get("is_synonym") and not k.get("is_structural"):
                zuweisbar.setdefault(text.lower(), text)
            walk(k.get("children"))

    walk(katalog)
    plan, gesehen = [], set()
    for ziel, synonym in standard_synonyme(vorlage):
        ziel_im_katalog = zuweisbar.get(ziel.lower())
        if not ziel_im_katalog or synonym.lower() in alle or synonym.lower() in gesehen:
            continue
        gesehen.add(synonym.lower())
        plan.append((ziel_im_katalog, synonym))
    return sorted(plan, key=lambda p: (p[0].lower(), p[1].lower()))


def _fehlerhinweis(fehler):
    """Gesammelte Meldung für nicht schreibbare Dokumente (leer, wenn alles klappte)."""
    if not fehler:
        return ""
    namen = "\n".join("  " + os.path.basename(p) for p in fehler[:10])
    if len(fehler) > 10:
        namen += f"\n  … und {len(fehler) - 10} weitere"
    return (f"\n\n{len(fehler)} Dokument(e) konnten NICHT geschrieben werden:\n{namen}\n\n"
            "Meist ist die Datei gerade in einem anderen Programm (PDF-Anzeige, Explorer-Vorschau) "
            "geöffnet - dort schließen und den Vorgang wiederholen.")


class IgnorierlisteDialog(tk.Toplevel):
    """
    Die KI-Ignorierliste ansehen und Einträge wieder freigeben (Nutzerfrage 03.09.2026:
    "Kann ich die Hygiene-Ignore-Liste auch bearbeiten?"). Gefüllt wird die Liste von
    der Tag-Hygiene und vom Rechtsklick im Tag-Baum (das Werkzeug "Tags ergänzen (KI)" gibt es seit 08.11.2026 nicht mehr).
    """

    def __init__(self, parent, master_folder):
        super().__init__(parent)
        self.master_folder = master_folder
        self.title("Ignorierliste der KI")
        UIUtils.position_near_mouse(self, UIUtils.px(self, 420), UIUtils.px(self, 420))
        self.transient(parent)

        ttk.Label(self, anchor="w", wraplength=UIUtils.px(self, 390),
                  text="Diese Tags schlägt die KI nicht mehr vor. Entfernen gibt ein Tag wieder frei."
                  ).pack(fill=tk.X, padx=10, pady=(10, 5))
        rahmen = ttk.Frame(self)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        self.liste = tk.Listbox(rahmen, selectmode=tk.EXTENDED)
        scroll = ttk.Scrollbar(rahmen, command=self.liste.yview)
        self.liste.configure(yscrollcommand=scroll.set)
        self.liste.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.liste.bind("<Delete>", self._entfernen)

        knoepfe = ttk.Frame(self)
        knoepfe.pack(pady=(5, 10))
        ttk.Button(knoepfe, text="Von der Liste entfernen (Entf)",
                   command=self._entfernen).pack(side=tk.LEFT, padx=5)
        ttk.Button(knoepfe, text="Schließen", command=self.destroy).pack(side=tk.LEFT, padx=5)
        self._fuellen()
        self.grab_set()

    def _fuellen(self):
        self.liste.delete(0, tk.END)
        for tag in tag_ignorierliste.lade_liste(self.master_folder):
            self.liste.insert(tk.END, tag)

    def _entfernen(self, event=None):
        auswahl = [self.liste.get(i) for i in self.liste.curselection()]
        if not auswahl:
            return
        for tag in auswahl:
            tag_ignorierliste.entferne(self.master_folder, tag)
        self._fuellen()


# Kästchen statt nacktem Kreuz in der 'Weg?'-Spalte (Peter 31.10.2026): ein leeres Kästchen zeigt
# sofort, dass man hier ankreuzt - „markiert“ ließ sich mit der blauen Zeilenauswahl verwechseln
KAESTCHEN_AUS = "☐"
KAESTCHEN_AN = "☒"


def _frage_vor_dem_schreiben(titel, text, parent):
    """
    Rückfrage vor Werkzeugen, die in viele PDFs schreiben: kommt IMMER, auch wenn die
    Sicherheitsabfragen abgeschaltet sind (wie „Dokument-IDs vergeben“; Peter 31.10.2026, T12.8:
    ohne Rückfrage war nicht zu erkennen, was gleich passiert).
    """
    with aktivitaet.warte_auf_antwort(titel):
        return bool(mb.askyesno(titel, text, parent=parent))


class TagHygieneFenster(tk.Toplevel):
    """Kandidaten-Tabelle mit Abhak-Spalte; 'Prüfen' füllt sie, 'Entfernen' räumt auf."""

    def __init__(self, app):
        super().__init__(app.root)
        UIUtils.werkzeugfenster(self, app.root)   # über KID, nicht modal (Peter 04.11.2026)
        self.app = app
        self.title("Tag-Hygiene")
        UIUtils.position_near_mouse(self, UIUtils.px(self, 900), UIUtils.px(self, 560))
        self.zeilen = {}  # iid -> {"tag":, "kategorie":, "pfade":, "markiert": bool}
        self._geprueft = False  # erst nach „Prüfen“ frischen die Werkzeuge die Liste auf

        # Zwei beschriftete Bereiche (Peter 31.10.2026, T12.7: „Oberfläche nicht verständlich genug“ -
        # die Werkzeug-Knöpfe sahen aus, als gehörten sie zur Liste darunter)
        werkzeuge = ttk.LabelFrame(self, text="Katalog aufräumen (wirkt auf alle Dokumente)")
        werkzeuge.pack(fill=tk.X, padx=10, pady=(10, 5))
        for text, befehl, erklaerung in (
                ("Standard-Synonyme übernehmen…", self._standard_synonyme_uebernehmen,
                 "Trägt die mitgelieferten Synonyme (z.B. „Müllabfuhr“ → „Müll“) unter vorhandenen Tags "
                 "nach - für Sammlungen, die ohne sie angelegt wurden."),
                ("Synonyme im Bestand ersetzen…", self._synonyme_ersetzen,
                 "Dokumente, die einen Synonym-Text als Tag tragen, bekommen stattdessen das Tag, "
                 "für das das Synonym steht."),
                ("Sammel-Tags zerlegen…", self._sammel_tags_zerlegen,
                 "Macht aus Tags wie „Musterweg 1 u. 3“ ein Tag je Objekt - in den Dokumenten und im Katalog."),
                ("Ignorierliste…", lambda: IgnorierlisteDialog(self, self.app.master_folder),
                 "Tags, die die KI nie mehr vorschlagen soll.")):
            knopf = ttk.Button(werkzeuge, text=text, command=befehl)
            knopf.pack(side=tk.LEFT, padx=5, pady=5)
            Tooltip(knopf, erklaerung)

        einzel = ttk.LabelFrame(self, text="Selten benutzte Tags")
        einzel.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        kopf = ttk.Frame(einzel)
        kopf.pack(fill=tk.X, padx=5, pady=(5, 0))
        ttk.Label(kopf, text="Tags mit höchstens").pack(side=tk.LEFT)
        self.schwelle = tk.IntVar(value=SCHWELLE_STANDARD)
        ttk.Spinbox(kopf, from_=1, to=10, width=3, textvariable=self.schwelle).pack(side=tk.LEFT, padx=5)
        ttk.Label(kopf, text="Dokument(en) suchen:").pack(side=tk.LEFT)
        ttk.Button(kopf, text="Prüfen", command=self._pruefen).pack(side=tk.LEFT, padx=10)

        rahmen = ttk.Frame(einzel)
        rahmen.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        spalten = ("weg", "tag", "kategorie", "anzahl", "dokumente")
        self.tree = ttk.Treeview(rahmen, columns=spalten, show="headings", selectmode="browse")
        for spalte, text, breite, stretch in (
                ("weg", "Weg?", 50, False), ("tag", "Tag", 200, False),
                ("kategorie", "Kategorie", 150, False), ("anzahl", "Anz.", 45, False),
                ("dokumente", "Dokumente", 380, True)):
            px = UIUtils.px(self, breite)
            self.tree.heading(spalte, text=text)
            self.tree.column(spalte, width=px, minwidth=px, stretch=stretch,
                             anchor="center" if spalte in ("weg", "anzahl") else "w")
        scroll = ttk.Scrollbar(rahmen, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<Button-1>", self._klick)
        # Bis zum ersten „Prüfen“ sagt die leere Liste, was sie zeigen wird (Prüfen liest alle PDFs,
        # das kann dauern - deshalb nicht automatisch beim Öffnen)
        self.tree.insert("", tk.END, values=("", "", "", "", "Noch leer - „Prüfen“ startet die Suche."))

        hinweis = ttk.Label(
            einzel, anchor="w", foreground="gray40", wraplength=UIUtils.px(self, 840),
            text=("Klick auf das Kästchen in der 'Weg?'-Spalte kreuzt ein Tag zum Entfernen an. Entfernen löscht das Tag "
                  "aus den Dokumenten (Titel und übrige Tags bleiben), nimmt es aus dem Katalog und setzt "
                  "es auf die Ignorierliste der KI. Tags mit Unter-Tags und Struktur-Knoten werden nicht "
                  "angeboten. Die Dokumente selbst bleiben unverändert auffindbar (Volltextsuche)."))
        hinweis.pack(fill=tk.X, padx=5, pady=(0, 5))

        knoepfe = ttk.Frame(self)
        knoepfe.pack(pady=(0, 10))
        self.btn_entfernen = ttk.Button(knoepfe, text="Angekreuzte entfernen",
                                        command=self._entfernen, state=tk.DISABLED)
        self.btn_entfernen.pack(side=tk.LEFT, padx=5)
        ttk.Button(knoepfe, text="Schließen", command=self.destroy).pack(side=tk.LEFT, padx=5)

    # ------------------------------------------------------------------ Prüfen
    def _katalog_info(self):
        """{tag.lower(): (Oberkategorie, hat_kinder, ist_struktur)} aus dem Tag-Baum des Hauptfensters."""
        info = {}
        baum = self.app.tree_tags
        struktur_marker = self.app.tag_manager.TAG_STRUCTURAL

        def walk(parent, kategorie):
            for child in baum.get_children(parent):
                text = baum.item(child, "text")
                item_tags = baum.item(child, "tags")
                item_tags = (item_tags,) if isinstance(item_tags, str) else tuple(item_tags)
                kinder = baum.get_children(child)
                info.setdefault(text.strip().lower(),
                                (kategorie or text, bool(kinder), struktur_marker in item_tags))
                walk(child, kategorie or text)

        walk("", None)
        return info

    def _pruefen(self):
        self._geprueft = True
        vorkommen = sammle_tag_vorkommen(
            self.app.master_folder,
            lambda pfad: app_paths.is_trash_path(pfad, self.app.master_folder))
        kandidaten = finde_einzelgaenger(vorkommen, max(1, int(self.schwelle.get())), self._katalog_info())
        self.tree.delete(*self.tree.get_children())
        self.zeilen = {}
        for tag, kategorie, pfade in kandidaten:
            namen = ", ".join(os.path.basename(p) for p in pfade)
            iid = self.tree.insert("", tk.END, values=(KAESTCHEN_AUS, tag, kategorie, len(pfade), namen))
            self.zeilen[iid] = {"tag": tag, "kategorie": kategorie, "pfade": pfade, "markiert": False}
        self.btn_entfernen.config(state=tk.NORMAL if kandidaten else tk.DISABLED)
        if not kandidaten:
            mb.showinfo("Tag-Hygiene", "Keine Einzelgänger-Tags gefunden.", parent=self)

    def _klick(self, event):
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        if self.tree.column(self.tree.identify_column(event.x), "id") != "weg":
            return
        iid = self.tree.identify_row(event.y)
        zeile = self.zeilen.get(iid)
        if zeile is None:
            return
        zeile["markiert"] = not zeile["markiert"]
        self.tree.set(iid, "weg", KAESTCHEN_AN if zeile["markiert"] else KAESTCHEN_AUS)

    # ------------------------------------------------------------------ Entfernen
    def _entfernen(self):
        markierte = [(iid, z) for iid, z in self.zeilen.items() if z["markiert"]]
        if not markierte:
            mb.showinfo("Tag-Hygiene", "Bitte zuerst Tags in der 'Weg?'-Spalte ankreuzen.", parent=self)
            return
        dokumente = sum(len(z["pfade"]) for _, z in markierte)
        if not bestaetigung.frage("Tag-Hygiene",
                           f"{len(markierte)} Tag(s) aus {dokumente} Dokument(en) entfernen?\n\n"
                           "Die Tags kommen zusätzlich auf die Ignorierliste der KI und werden "
                           "aus dem Tag-Katalog gelöscht.", parent=self):
            return

        dialog = ProgressDialog(self, "Tag-Hygiene", "Tags werden entfernt...")
        self.app.is_saving = True
        geaendert = 0
        fehler = []
        try:
            for i, (iid, zeile) in enumerate(markierte):
                if dialog.should_stop():
                    break
                geaendert += entferne_tag_aus_dokumenten(
                    self.app.master_folder, zeile["tag"], zeile["pfade"], getattr(self.app, "logger", None), fehler)
                tag_ignorierliste.ergaenze(self.app.master_folder, zeile["tag"])
                self._loesche_aus_katalog(zeile["tag"])
                if self.tree.exists(iid):
                    self.tree.delete(iid)
                self.zeilen.pop(iid, None)
                if dialog.winfo_exists():
                    dialog.update_progress(i + 1, len(markierte))
                self.update()
        finally:
            self.app.is_saving = False
            if dialog.winfo_exists():
                dialog.destroy()

        # Katalog einmal speichern und die Ansichten des Hauptfensters auffrischen
        self.app.tag_editor.save_tags()
        if hasattr(self.app, "folder_manager"):
            self.app.folder_manager.on_folder_select(None)
        (mb.showwarning if fehler else mb.showinfo)(
            "Tag-Hygiene",
            f"{len(markierte)} Tag(s) entfernt, {geaendert} Dokument(e) geändert." + _fehlerhinweis(fehler),
            parent=self)

    # ------------------------------------------------------------------ Synonyme
    def _synonyme_ersetzen(self, vorkommen=None, vorspann=""):
        """
        Altbestand an die Synonym-Knoten des Katalogs anpassen (Nutzerwunsch 08.09.2026,
        direkt nach dem ersten Synonym: 17 Dokumente trugen noch 'Haftpflichtversicherung').
        :param vorkommen: schon gesammelte Tag-Vorkommen (spart das zweite Lesen aller PDFs)
        :param vorspann: Text vor der Rückfrage (z.B. „12 Synonyme eingetragen.“)
        """
        synonyme = self.app.tag_manager.get_synonyme()
        if not synonyme:
            mb.showinfo("Synonyme", "Der Tag-Katalog enthält keine Synonym-Knoten\n"
                        "(Rechtsklick im Tag-Baum → \"Als Synonym umschalten\").", parent=self)
            return
        if vorkommen is None:
            vorkommen = sammle_tag_vorkommen(
                self.app.master_folder,
                lambda pfad: app_paths.is_trash_path(pfad, self.app.master_folder))
        plan = plane_synonym_ersetzungen(vorkommen, synonyme)
        if not plan:
            mb.showinfo("Synonyme", "Kein Dokument trägt noch einen Synonym-Text - nichts zu tun.", parent=self)
            return
        pfade = sorted({p for _, _, liste in plan for p in liste})
        zeilen = "\n".join(f"  {alt} → {ziel}: {len(liste)} Dokument(e)" for alt, ziel, liste in plan)
        if not _frage_vor_dem_schreiben(
                "Synonyme im Bestand ersetzen",
                f"{vorspann}In {len(pfade)} Dokument(en) den Synonym-Text durch das Ziel-Tag ersetzen?\n\n{zeilen}\n\n"
                "Oberkategorien des Ziel-Tags kommen dazu, Titel und übrige Tags bleiben.", parent=self):
            return

        dialog = ProgressDialog(self, "Synonyme", "Tags werden ersetzt...")
        self.app.is_saving = True
        geaendert = 0
        fehler = []
        try:
            tag_eltern = self.app.tag_manager.get_tag_eltern()
            logger = getattr(self.app, "logger", None)
            for i, rel in enumerate(pfade):
                if dialog.should_stop():
                    break
                geaendert += ersetze_synonyme_in_dokumenten(
                    self.app.master_folder, [rel], synonyme, tag_eltern, logger, fehler)
                if dialog.winfo_exists():
                    dialog.update_progress(i + 1, len(pfade))
                self.update()
        finally:
            self.app.is_saving = False
            if dialog.winfo_exists():
                dialog.destroy()
        if hasattr(self.app, "folder_manager"):
            self.app.folder_manager.on_folder_select(None)
        (mb.showwarning if fehler else mb.showinfo)(
            "Synonyme", f"{geaendert} Dokument(e) geändert." + _fehlerhinweis(fehler), parent=self)
        if self._geprueft:
            self._pruefen()

    def _standard_synonyme_uebernehmen(self):
        """Fehlende Synonyme der mitgelieferten Vorlage in den Katalog dieser Sammlung eintragen."""
        try:
            with open(app_paths.bundled_default_path("tags_default.json"), encoding="utf-8") as f:
                vorlage = json.load(f)
        except (OSError, ValueError) as e:
            mb.showerror("Standard-Synonyme", f"Die mitgelieferte Tag-Vorlage ist nicht lesbar:\n{e}", parent=self)
            return
        plan = plane_standard_synonyme(vorlage, self.app.tag_editor._get_nodes(""))
        if not plan:
            mb.showinfo("Standard-Synonyme", "Der Katalog enthält schon alle passenden Standard-Synonyme.",
                        parent=self)
            return
        zeilen = "\n".join(f"  {syn} → {ziel}" for ziel, syn in plan[:30])
        if len(plan) > 30:
            zeilen += f"\n  … und {len(plan) - 30} weitere"
        if not bestaetigung.frage(
                "Standard-Synonyme übernehmen",
                f"{len(plan)} Synonym(e) aus der mitgelieferten Vorlage in den Tag-Katalog eintragen?\n\n{zeilen}\n\n"
                "Schlägt die KI später einen dieser Texte vor, bekommt das Dokument das Tag rechts davon. "
                "Im Tag-Baum lässt sich jedes Synonym wieder löschen.", parent=self):
            return

        baum, tm = self.app.tree_tags, self.app.tag_manager
        ziele = {}

        def suche(parent):
            for child in baum.get_children(parent):
                item_tags = baum.item(child, "tags")
                item_tags = (item_tags,) if isinstance(item_tags, str) else tuple(item_tags)
                if self.app.tag_editor._is_protected_node(item_tags):
                    continue
                if tm.TAG_SYNONYM not in item_tags and tm.TAG_STRUCTURAL not in item_tags:
                    ziele.setdefault(baum.item(child, "text").strip().lower(), child)
                suche(child)

        suche("")
        for ziel, syn in plan:
            iid = ziele.get(ziel.lower())
            if iid:
                baum.insert(iid, "end", text=syn, tags=(tm.TAG_BUNDLE, tm.TAG_SYNONYM), open=False)
        self.app.tag_editor.save_tags()
        logger = getattr(self.app, "logger", None)
        if logger:
            logger.info("Tag-Hygiene: Standard-Synonyme übernommen: " + ", ".join(f"{s} -> {z}" for z, s in plan))

        # Tragen Dokumente schon einen der neuen Synonym-Texte, gleich das Ersetzen anbieten
        vorkommen = sammle_tag_vorkommen(
            self.app.master_folder, lambda pfad: app_paths.is_trash_path(pfad, self.app.master_folder))
        if plane_synonym_ersetzungen(vorkommen, tm.get_synonyme()):
            self._synonyme_ersetzen(vorkommen, f"{len(plan)} Synonym(e) eingetragen.\n\n")
        else:
            mb.showinfo("Standard-Synonyme", f"{len(plan)} Synonym(e) eingetragen.", parent=self)

    def _sammel_tags_zerlegen(self):
        """Altbestand an die Regel „ein Objekt je Tag“ anpassen (ToDo 27.10.2026, Betatest: 22 Dokumente
        trugen 'Zum Alten Fass 1 u. 3')."""
        vorkommen = sammle_tag_vorkommen(
            self.app.master_folder, lambda pfad: app_paths.is_trash_path(pfad, self.app.master_folder))
        plan = plane_sammel_zerlegung(vorkommen)
        if not plan:
            mb.showinfo("Sammel-Tags", "Kein Dokument trägt ein Sammel-Tag wie „Musterstraße 1 u. 3“ - nichts zu tun.",
                        parent=self)
            return
        pfade = sorted({p for _, _, liste in plan for p in liste})
        zeilen = "\n".join(f"  {tag} → {' + '.join(teile)}: {len(liste)} Dokument(e)" for tag, teile, liste in plan)
        if not _frage_vor_dem_schreiben(
                "Sammel-Tags zerlegen",
                f"In {len(pfade)} Dokument(en) jedes Sammel-Tag durch ein Tag je Objekt ersetzen?\n\n{zeilen}\n\n"
                "Titel und übrige Tags bleiben; im Tag-Katalog treten die Einzel-Tags an die Stelle des Sammel-Tags.",
                parent=self):
            return

        zerlegung = {tag.lower(): teile for tag, teile, _ in plan}
        dialog = ProgressDialog(self, "Sammel-Tags", "Tags werden zerlegt...")
        self.app.is_saving = True
        geaendert = 0
        fehler = []
        try:
            logger = getattr(self.app, "logger", None)
            for i, rel in enumerate(pfade):
                if dialog.should_stop():
                    break
                geaendert += zerlege_sammel_tags_in_dokumenten(self.app.master_folder, [rel], zerlegung, logger, fehler)
                if dialog.winfo_exists():
                    dialog.update_progress(i + 1, len(pfade))
                self.update()
        finally:
            self.app.is_saving = False
            if dialog.winfo_exists():
                dialog.destroy()
        self._zerlege_im_katalog(zerlegung)
        if hasattr(self.app, "folder_manager"):
            self.app.folder_manager.on_folder_select(None)
        (mb.showwarning if fehler else mb.showinfo)(
            "Sammel-Tags", f"{geaendert} Dokument(e) geändert." + _fehlerhinweis(fehler), parent=self)
        if self._geprueft:
            self._pruefen()

    def _zerlege_im_katalog(self, zerlegung):
        """Sammel-Tags im Tag-Baum durch ihre Einzel-Tags ersetzen (als Geschwister, nur was noch fehlt)."""
        baum, tm = self.app.tree_tags, self.app.tag_manager
        vorhanden, sammel = set(), []

        def walk(parent):
            for child in baum.get_children(parent):
                item_tags = baum.item(child, "tags")
                item_tags = (item_tags,) if isinstance(item_tags, str) else tuple(item_tags)
                if self.app.tag_editor._is_protected_node(item_tags):
                    continue
                text = baum.item(child, "text").strip()
                vorhanden.add(text.lower())
                if (text.lower() in zerlegung and not baum.get_children(child)
                        and tm.TAG_STRUCTURAL not in item_tags and tm.TAG_SYNONYM not in item_tags):
                    sammel.append(child)
                walk(child)

        walk("")
        for knoten in sammel:
            eltern, index = baum.parent(knoten), baum.index(knoten)
            for teil in zerlegung[baum.item(knoten, "text").strip().lower()]:
                if teil.lower() not in vorhanden:
                    index += 1
                    baum.insert(eltern, index, text=teil, tags=(tm.TAG_BUNDLE,), open=False)
                    vorhanden.add(teil.lower())
            baum.delete(knoten)
        if sammel:
            self.app.tag_editor.save_tags()

    def _loesche_aus_katalog(self, tag):
        """Blatt-Knoten mit diesem Text aus dem Tag-Baum löschen (nur ohne Kinder, nie Struktur-Knoten)."""
        baum = self.app.tree_tags
        struktur_marker = self.app.tag_manager.TAG_STRUCTURAL

        def suche(parent):
            for child in baum.get_children(parent):
                if baum.item(child, "text").strip().lower() == tag.strip().lower():
                    item_tags = baum.item(child, "tags")
                    item_tags = (item_tags,) if isinstance(item_tags, str) else tuple(item_tags)
                    if not baum.get_children(child) and struktur_marker not in item_tags:
                        baum.delete(child)
                        return True
                if suche(child):
                    return True
            return False

        suche("")


class TagHygieneTool(BaseTool):
    """Menü-Einstieg: öffnet das Tag-Hygiene-Fenster."""

    @property
    def name(self) -> str:
        return "Tag-Hygiene (Einzelgänger aufräumen)"

    @property
    def menu_group(self) -> str:
        return "Aufräumen"

    @property
    def menu_label(self) -> str:
        return "Tag-Hygiene: selten benutzte Tags…"

    @property
    def absicht(self) -> str:
        return ("Gegen Tag-Wildwuchs: Einzelgänger-Tags aufräumen, Synonyme im Bestand ersetzen, mitgelieferte Standard-Synonyme nachtragen, Sammel-Tags („Musterstraße 1 u. 3“) zerlegen, die Warteliste neuer KI-Tags prüfen. Ein kleiner Katalog hält die Suche nach Kategorie + Ort + Jahr treffsicher.")

    @property
    def description(self) -> str:
        return "Findet Tags, die nur an wenigen Dokumenten hängen, und räumt sie auf Wunsch weg."

    @property
    def menu_hooks(self) -> list:
        return ["main_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        def neu():
            fenster = TagHygieneFenster(context.app)
            fenster.after(100, fenster._pruefen)  # direkt mit der Standard-Schwelle füllen
            return fenster
        # höchstens ein Fenster (Peter 04.11.2026: doppelt geöffnet = falsche Daten) - ein offenes kommt nach vorn
        UIUtils.einzelfenster("tag_hygiene", neu)
        return True
