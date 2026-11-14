"""
Eigenschaften-Panel unter der Dokumentenliste: Titel, Tags, Datum und ALLE Eigenschaften
des gewählten Dokuments als zweispaltige Tabelle mit Linien (Nutzerwunsch 14.09.2026,
vorher ein Textblock, 07.09.2026). Bearbeitbare Zellen sind weiß (Titel, Tags, Datum -
die Widgets liefert layout_builder), schreibgeschützte grau: markier- und kopierbar,
Rechtsklick „Kopieren“ / „Alles kopieren“, Tooltip mit dem vollen Wert nur, wenn die
Zelle ihn abschneidet.

Aufteilung der Felder: Jedes Feld hat eine feste Breite in „Paaren“ (Bezeichner+Wert;
PAARE_JE_ZEILE Paare je Zeile). `packe_zeilen` füllt die Zeilen von oben nach unten
gierig - passt ein Feld nicht mehr in die Restzeile, beginnt eine neue. Welche Felder
immer, nur ausgeklappt („Details“-Häkchen) oder nie erscheinen, steht in der Einstellung
`eigenschaften_felder` (drei geordnete Listen; Standard STANDARD_AUFTEILUNG). Leere Werte
bleiben als leere Zelle stehen, damit das Raster beim Dokumentwechsel nicht springt.

Aufteilung wie im übrigen Projekt: `sammle_eigenschaften`, `formatiere_eigenschaften`,
`feldaufteilung` und `packe_zeilen` sind reine Funktionen ohne Tkinter (Unit-Tests),
`EigenschaftenPanel` ist das Widget. Das PDF wird in einem Hintergrund-Thread gelesen
(große Scans dürfen den Klick nicht ausbremsen); ein Laufzähler verwirft veraltete
Ergebnisse, wenn der Nutzer schneller weiterklickt als gelesen wird - dasselbe Muster
wie in preview_manager.

Mail-Bezug (Peter 05.11.2026): PDF-Anhänge sind eigene Dokumente, sonst fehlt der Zusammenhang, und man kann sie schwer
von einem Scan unterscheiden. Die Leiste `leiste_mail` in der Knopfzeile zeigt beim Anhang seine Mail, bei der Mail ihre
Anhänge, jeweils zum Anklicken - auch wenn sie in verschiedenen Ordnern liegen. Bei allen anderen Dokumenten bleibt sie
leer und belegt keine Zeile.
"""
import atexit
import datetime
import os
import re
import shutil
import tempfile
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import messagebox, ttk

from pdf_handler import PDFHandler
from ui_utils import Tooltip, UIUtils

EINSTELLUNG_DETAILS = "eigenschaften_details"   # settings.json: Details ein-/ausgeklappt
EINSTELLUNG_FELDER = "eigenschaften_felder"     # settings.json: {"immer": [...], "ausgeklappt": [...], "nie": [...]}
PAARE_JE_ZEILE = 8   # 8 Paare je Zeile, damit ⅛ die kleinste Breite sein kann (Peter 15.09.2026)
_BREITE = 16                                    # Spaltenbreite der Bezeichner (Textfassung)
_TRENNER = "   ·   "

UNSICHER_ORDNER = "0_Unsicher"   # wie auto_pilot.UNSICHER_ORDNER (hier ohne den schweren Import)

FARBE_LINIE = "#c8c8c8"
FARBE_GRAU = "#f3f3f3"
FARBE_WEISS = "#ffffff"

# Feldkatalog: Schlüssel (wie in sammle_eigenschaften) -> (Bezeichner, Breite in Paaren).
# Die Breite folgt dem typischen Inhalt: Datum/Zahl ¼ (2 Paare), Name/Autor ½ (4), Ordner/Pfad die ganze Zeile (8).
FELDER = {
    "datum": ("Datum", 2),                  # bearbeitbar (date_entry aus layout_builder), immer sichtbar
    "scan_zeitpunkt": ("Scan-Zeitpunkt", 2),
    "seiten": ("Seiten", 2),
    "groesse": ("Größe", 2),
    "dateiname": ("Dateiname", 4),
    "originalname": ("Originalname", 4),
    "ordner": ("Ordner", 8),
    "pfad": ("Pfad", 8),
    "geaendert": ("Geändert", 2),
    "erstellt": ("Erstellt", 2),
    "dokument_id": ("Dokument-ID", 2),
    "schutz": ("Schutz", 2),
    "autor": ("Autor", 4),
    "betreff": ("Betreff", 4),
    "erstellt_mit": ("Erstellt mit", 2),
    "pdf_erstellt": ("PDF-Datum", 2),
    "pdf_geaendert": ("PDF geändert", 2),
    "fehler": ("Hinweis", 8),
    "status": ("Status", 8),                # warum orange / warum vorgelegt (Peter 28.10.2026)
    "dokumentdatum": ("Datum (PDF)", 2),    # steht schon bearbeitbar in „Datum“
    "titel": ("Titel (PDF)", 4),            # steht schon bearbeitbar im Titel-Feld
    "tags": ("Tags (PDF)", 4),              # steht schon bearbeitbar im Tags-Feld
}
ZONEN = ("immer", "ausgeklappt", "nie")
STANDARD_AUFTEILUNG = {
    "immer": ["datum", "scan_zeitpunkt", "seiten", "groesse", "dokument_id"],   # ID: Peter 25.10.2026
    "ausgeklappt": ["status", "dateiname", "originalname", "ordner", "pfad", "geaendert", "erstellt",
                    "schutz", "autor", "betreff", "erstellt_mit", "pdf_erstellt", "pdf_geaendert", "fehler"],
    "nie": ["dokumentdatum", "titel", "tags"],
}
IMMER_SICHTBAR = ("datum",)   # bearbeitbar - darf nie verschwinden
BREITEN_STUFEN = (1, 2, 4, 6, 8)                        # ⅛, ¼, ½, ¾, ganze Zeile (in Paaren)
BREITEN_TEXTE = {1: "⅛", 2: "¼", 4: "½", 6: "¾", 8: "1"}

_PDF_DATUM = re.compile(r"^D:(\d{4})(\d{2})(\d{2})(?:(\d{2})(\d{2}))?")
_ISO_DATUM = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")

MAX_MAIL_LINKS = 4            # mehr Anhänge passen nicht in die Knopfzeile, der Rest steht als „+ n weitere“ da
MAX_LINK_ZEICHEN = 40         # der volle Text steht im Tooltip
FARBE_LINK = "#0055a4"
ORDNER_ORIGINAL_MAILS = "KID-Original-Mails"
_aufraeumen_vorgemerkt = False


def formatiere_pdf_datum(text):
    """PDF-Datumsform 'D:20240220143300+01'00'' -> '20.02.2024 14:33'; alles andere unverändert."""
    text = (text or "").strip()
    m = _PDF_DATUM.match(text)
    if not m:
        return text
    jahr, monat, tag, stunde, minute = m.groups()
    ergebnis = f"{tag}.{monat}.{jahr}"
    if stunde is not None:
        ergebnis += f" {stunde}:{minute}"
    return ergebnis


def formatiere_iso_datum(text):
    """'2024-02-20' -> '20.02.2024' (KID-Dokumentdatum); alles andere unverändert."""
    text = (text or "").strip()
    m = _ISO_DATUM.match(text)
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}" if m else text


def formatiere_groesse(anzahl_bytes):
    """Dateigröße lesbar: 845 B, 245 KB, 1,2 MB."""
    try:
        groesse = float(anzahl_bytes)
    except (TypeError, ValueError):
        return ""
    if groesse < 1024:
        return f"{int(groesse)} B"
    if groesse < 1024 * 1024:
        return f"{groesse / 1024:.0f} KB"
    return f"{groesse / (1024 * 1024):.1f} MB".replace(".", ",")


def formatiere_zeit(zeitstempel):
    """Unix-Zeit -> '06.09.2026 23:10'."""
    try:
        return datetime.datetime.fromtimestamp(zeitstempel).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def sammle_eigenschaften(abs_path, rel_path="", lese_pdf=None):
    """
    Alle Eigenschaften eines Dokuments als Dict - Dateisystem (os.stat) plus PDF-Inhalt
    (Standard: PDFHandler.get_document_info; Tests reichen eine eigene Funktion herein).
    Liefert auch bei fehlender/unlesbarer Datei ein Dict (mit 'fehler'), nie eine Ausnahme.
    """
    lese_pdf = lese_pdf or PDFHandler.get_document_info
    e = {
        "dateiname": os.path.basename(abs_path or ""),
        "ordner": os.path.dirname(rel_path or "") if rel_path else "",
        # normpath: der Hauptordner kommt aus dem Tk-Ordnerdialog mit Schrägstrichen
        # ("C:/Users/..."), os.path.join hängt mit Backslash an - sonst steht beides gemischt da
        "pfad": os.path.normpath(abs_path) if abs_path else "",
        "groesse": "", "geaendert": "", "erstellt": "",
        "seiten": "", "schutz": "", "fehler": "",
        "dokumentdatum": "", "scan_zeitpunkt": "",
        "titel": "", "tags": "", "autor": "", "betreff": "",
        "erstellt_mit": "", "pdf_erstellt": "", "pdf_geaendert": "", "status": "",
    }
    try:
        st = os.stat(abs_path)
        e["groesse"] = formatiere_groesse(st.st_size)
        e["geaendert"] = formatiere_zeit(st.st_mtime)
        e["erstellt"] = formatiere_zeit(st.st_ctime)
    except OSError as fehler:
        e["fehler"] = f"Datei nicht lesbar: {fehler}"
        return e
    try:
        info = lese_pdf(abs_path) or {}
    except Exception as fehler:
        e["fehler"] = str(fehler)
        return e
    e["seiten"] = str(info.get("seiten") or "") if info.get("seiten") else ""
    e["schutz"] = info.get("schutz", "") or ""
    e["fehler"] = info.get("fehler", "") or ""
    e["dokumentdatum"] = formatiere_iso_datum(info.get("KID_DokumentenDatum", ""))
    e["scan_zeitpunkt"] = (info.get("KID_ScanZeitpunkt") or "").strip()
    e["originalname"] = (info.get("KID_Originalname") or "").strip()
    e["dokument_id"] = (info.get("KID_ID") or "").strip()
    e["titel"] = (info.get("title") or "").strip()
    e["tags"] = (info.get("keywords") or "").strip()
    e["autor"] = (info.get("author") or "").strip()
    e["betreff"] = (info.get("subject") or "").strip()
    erzeuger = [t for t in ((info.get("creator") or "").strip(), (info.get("producer") or "").strip()) if t]
    e["erstellt_mit"] = " / ".join(dict.fromkeys(erzeuger))
    e["pdf_erstellt"] = formatiere_pdf_datum(info.get("creationDate", ""))
    e["pdf_geaendert"] = formatiere_pdf_datum(info.get("modDate", ""))
    e["status"] = dokument_status(info, rel_path)
    e["mail_id"] = (info.get("KID_MailID") or "").strip()
    e["ist_mail"] = bool(info.get("KID_Richtung"))
    return e


def dokument_status(info, rel_path=""):
    """
    Klartext, warum ein Dokument auffällt (Peter 28.10.2026): von der Vollautomatik vorgelegt (Grund
    aus KID_GRUND, nur solange es in 0_Unsicher liegt), unbearbeitet (orange in der Liste) oder
    Datum nur vermutet (orange hinterlegt). "" wenn alles erledigt ist.
    """
    teile = []
    grund = (info.get("KID_Grund") or "").strip()
    ordner = os.path.dirname(rel_path or "")
    if grund and os.path.normcase(ordner) == os.path.normcase(UNSICHER_ORDNER):
        # Die Gründe sprechen die Ablage-Vorschau an („Zielordner anklicken“ = deren Spalte) -
        # darum der Wegweiser dorthin (Peter 28.10.2026: „was meinst du mit Zielordner anklicken?“)
        teile.append("Von der Vollautomatik zur Prüfung vorgelegt (erledigen: Rechtsklick → Vollautomatik: "
                     f"Ablage-Vorschau, dort Spalte „Zielordner“): {grund}")
    titel = (info.get("title") or "").strip()
    tags = (info.get("keywords") or "").strip()
    datum = (info.get("KID_DokumentenDatum") or "").strip()
    if not titel and not tags and not datum:
        teile.append("Unbearbeitet (orange in der Liste): noch kein Titel, keine Tags, kein Datum gespeichert")
    elif not datum:
        teile.append("Datum nur vermutet (orange hinterlegt) - noch nicht gespeichert")
    return _TRENNER.join(teile)


def mail_bezug(ist_mail, verwandte):
    """
    Was die Leiste zum Mail-Bezug anzeigt: (Vorspann, [(Linktext, rel_path), ...]).
    :param ist_mail: True = das Dokument ist die Mail selbst, False = ein Anhang
    :param verwandte: [(rel_path, Metadaten)] der übrigen Dokumente mit derselben KID_MAILID
    Eine Mail ohne Anhänge hat keinen Bezug (leerer Vorspann). Ein Anhang, dessen Mail nicht mehr in der Sammlung
    liegt, sagt das, damit er nicht wie ein Scan aussieht.
    """
    def name(rel_path, meta):
        return (meta.get("title") or "").strip() or os.path.splitext(os.path.basename(rel_path))[0]

    if ist_mail:
        anhaenge = [(name(r, m), r) for r, m in verwandte if not m.get("KID_Richtung")]
        return ("Anhänge:", anhaenge) if anhaenge else ("", [])
    for r, m in verwandte:
        if m.get("KID_Richtung"):
            datum = formatiere_iso_datum(m.get("KID_DokumentenDatum", ""))
            return "Anhang der Mail:", [(f"{name(r, m)}, {datum}" if datum else name(r, m), r)]
    return "Anhang einer Mail, die nicht mehr in der Sammlung liegt", []


def original_mail_ordner():
    """Hier liegen die zum Öffnen entpackten Mails. Fest, damit Reste nach einem Absturz wiedergefunden werden."""
    return os.path.join(tempfile.gettempdir(), ORDNER_ORIGINAL_MAILS)


def raeume_original_mails_auf():
    """Entpackte Mails entfernen. Eine Datei, die das Mailprogramm noch offen hält, bleibt bis zum nächsten Mal liegen."""
    shutil.rmtree(original_mail_ordner(), ignore_errors=True)


def original_mail_bereitstellen(pdf_pfad):
    """
    Legt die eingebettete Original-Mail als .eml in den Temp-Ordner und liefert den Pfad, ohne Original-Mail None.
    Die erste Mail einer Sitzung räumt Reste früherer Sitzungen weg, beim Beenden räumt atexit auf: Mailinhalte
    sollen nicht im Temp-Ordner liegen bleiben.
    """
    global _aufraeumen_vorgemerkt
    daten = PDFHandler.hole_eml(pdf_pfad)
    if daten is None:
        return None
    if not _aufraeumen_vorgemerkt:
        raeume_original_mails_auf()
        atexit.register(raeume_original_mails_auf)
        _aufraeumen_vorgemerkt = True
    ordner = original_mail_ordner()
    os.makedirs(ordner, exist_ok=True)
    stamm = os.path.splitext(os.path.basename(pdf_pfad))[0]
    pfad = os.path.join(ordner, stamm + ".eml")
    with open(pfad, "wb") as f:
        f.write(daten)
    return pfad


def _zeile(bezeichner, wert):
    return f"{bezeichner + ':':<{_BREITE}}{wert}"


def _paare(*paare):
    """Kurze Angaben in EINER Zeile: 'Seiten: 3   ·   Größe: 245 KB' (leere werden übersprungen)."""
    return _TRENNER.join(f"{k}: {v}" for k, v in paare if v)


def formatiere_eigenschaften(e):
    """
    Dict aus sammle_eigenschaften -> kompakter, kopierbarer Text (eine Eigenschaft pro
    Zeile, kurze Angaben zu Sammelzeilen gebündelt) - das Ergebnis von „Alles kopieren“.
    Leere Werte werden ausgelassen, damit der Text nicht mit '-' vollsteht; die Reihenfolge ist fest.
    """
    if not e:
        return ""
    zeilen = [
        _zeile("Status", e.get("status")) if e.get("status") else "",
        _zeile("Dateiname", e.get("dateiname", "")),
        _zeile("Originalname", e.get("originalname")) if e.get("originalname") else "",
        _zeile("Dokument-ID", e.get("dokument_id")) if e.get("dokument_id") else "",
        _zeile("Ordner", e.get("ordner") or "(Hauptordner)"),
        _zeile("Pfad", e.get("pfad", "")),
        _paare(("Seiten", e.get("seiten")), ("Größe", e.get("groesse")),
               ("Geändert", e.get("geaendert")), ("Erstellt", e.get("erstellt"))),
        _paare(("Dokumentdatum", e.get("dokumentdatum")), ("Scan-Zeitpunkt", e.get("scan_zeitpunkt"))),
        _zeile("Titel (PDF)", e.get("titel")) if e.get("titel") else "",
        _zeile("Tags (PDF)", e.get("tags")) if e.get("tags") else "",
        _paare(("Autor", e.get("autor")), ("Betreff", e.get("betreff"))),
        _paare(("Erstellt mit", e.get("erstellt_mit")), ("PDF-Datum", e.get("pdf_erstellt")),
               ("PDF geändert", e.get("pdf_geaendert"))),
        _zeile("Schutz", e.get("schutz")) if e.get("schutz") else "",
        _zeile("Hinweis", e.get("fehler")) if e.get("fehler") else "",
    ]
    return "\n".join(z for z in zeilen if z)


# ---------------------------------------------------------------- Aufteilung & Packregel (Tk-frei)

def feldaufteilung(wert):
    """
    Einstellung `eigenschaften_felder` in eine saubere Aufteilung {"immer", "ausgeklappt", "nie"}
    bringen: unbekannte Schlüssel fliegen raus, doppelte zählen beim ersten Auftreten, Felder aus
    IMMER_SICHTBAR bleiben in „immer“ (an ihrer Position; aus einer anderen Zone kommen sie ans
    Ende von „immer“ - so lässt sich „Datum“ innerhalb des Blocks verschieben, aber nicht
    darunter, Peter 15.09.2026), und Felder, die in keiner Zone stehen (z.B. neu
    dazugekommen), landen hinten in „ausgeklappt“ - so geht bei einem Update nichts still verloren.
    Ohne oder mit unbrauchbarem Wert gilt STANDARD_AUFTEILUNG. Vierter Teil „breiten“
    ({Schlüssel: Paare}, seit 15.09.2026 per +/- einstellbar): nur Werte aus BREITEN_STUFEN,
    sonst der Standard aus FELDER.
    """
    if not isinstance(wert, dict):
        wert = STANDARD_AUFTEILUNG
    ergebnis = {zone: [] for zone in ZONEN}
    breiten_alt = wert.get("breiten") if isinstance(wert.get("breiten"), dict) else {}
    # Kurzlebiges Altformat (nur 15.09.2026, 4 Paare je Zeile): Werte ohne "paare_je_zeile"-Marke verdoppeln
    faktor = 1 if wert.get("paare_je_zeile") == PAARE_JE_ZEILE else 2
    ergebnis["breiten"] = {}
    for s in FELDER:
        b = breiten_alt.get(s)
        b = b * faktor if isinstance(b, int) and not isinstance(b, bool) else None
        ergebnis["breiten"][s] = b if b in BREITEN_STUFEN else FELDER[s][1]
    ergebnis["paare_je_zeile"] = PAARE_JE_ZEILE
    gesehen = set()
    for zone in ZONEN:
        for schluessel in wert.get(zone) or []:
            if schluessel in FELDER and schluessel not in gesehen:
                ergebnis[zone].append(schluessel)
                gesehen.add(schluessel)
    for schluessel in IMMER_SICHTBAR:
        if schluessel not in ergebnis["immer"]:
            for zone in ZONEN:
                if schluessel in ergebnis[zone]:
                    ergebnis[zone].remove(schluessel)
            ergebnis["immer"].append(schluessel)
            gesehen.add(schluessel)
    for schluessel in FELDER:
        if schluessel not in gesehen:
            ergebnis["ausgeklappt"].append(schluessel)
    return ergebnis


def naechste_breite(paare, richtung):
    """Breite eine Stufe breiter (+1) oder schmaler (-1): 1 → 2 → 4 → 6 → 8 (⅛, ¼, ½, ¾, 1), an den Enden bleibt sie."""
    stufen = list(BREITEN_STUFEN)
    i = stufen.index(paare) if paare in stufen else 0
    return stufen[max(0, min(len(stufen) - 1, i + richtung))]


def packe_zeilen(schluessel, paare_je_zeile=PAARE_JE_ZEILE, breiten=None):
    """
    Feld-Schlüssel der Reihe nach in Zeilen zu `paare_je_zeile` Paaren packen (gierig):
    [[("datum", 2), ("scan_zeitpunkt", 2), ("seiten", 2), ("groesse", 2)], [("dateiname", 4), ...], ...].
    Ein Feld, das nicht mehr in die Restzeile passt, beginnt eine neue; breitere Felder als
    eine Zeile werden auf die Zeilenbreite gekappt. `breiten` überschreibt die Standardbreiten aus FELDER.
    """
    breiten = breiten or {}
    zeilen, aktuell, belegt = [], [], 0
    for s in schluessel:
        breite = min(breiten.get(s, FELDER[s][1]), paare_je_zeile)
        if aktuell and belegt + breite > paare_je_zeile:
            zeilen.append(aktuell)
            aktuell, belegt = [], 0
        aktuell.append((s, breite))
        belegt += breite
    if aktuell:
        zeilen.append(aktuell)
    return zeilen


TRENNER_MARKEN = {"ausgeklappt": "__ausgeklappt__", "nie": "__nie__"}
TRENNER_TEXTE = {"__ausgeklappt__": "────────  nur mit „Details“  ────────",
                 "__nie__": "────────  nicht anzeigen  ────────"}


def aufteilung_als_liste(aufteilung):
    """Aufteilung -> EINE Liste für die Einstellungs-Oberfläche: Felder der Zone „immer“, dann die
    Trenner-Marke, Zone „ausgeklappt“, Marke, Zone „nie“ (Marken siehe TRENNER_MARKEN)."""
    a = feldaufteilung(aufteilung)
    return a["immer"] + [TRENNER_MARKEN["ausgeklappt"]] + a["ausgeklappt"] + [TRENNER_MARKEN["nie"]] + a["nie"]


def liste_als_aufteilung(liste, breiten=None):
    """Umkehrung von aufteilung_als_liste: an den Trenner-Marken in die drei Zonen schneiden
    (fehlt eine Marke, gilt alles Folgende als „ausgeklappt“ bzw. „nie“ leer); Ergebnis normalisiert,
    `breiten` wird mitgenommen."""
    zonen = {zone: [] for zone in ZONEN}
    zonen["breiten"] = dict(breiten or {})
    zonen["paare_je_zeile"] = PAARE_JE_ZEILE
    aktuell = "immer"
    for eintrag in liste:
        if eintrag == TRENNER_MARKEN["ausgeklappt"]:
            aktuell = "ausgeklappt"
        elif eintrag == TRENNER_MARKEN["nie"]:
            aktuell = "nie"
        else:
            zonen[aktuell].append(eintrag)
    return feldaufteilung(zonen)


def anzeigetext(eintrag, breiten=None):
    """Listeneintrag (Feld-Schlüssel oder Trenner-Marke) -> Text für die Listbox, mit Breite: „Pfad  1“, „Seiten  ¼“."""
    if eintrag in TRENNER_TEXTE:
        return TRENNER_TEXTE[eintrag]
    if eintrag not in FELDER:
        return eintrag
    breite = (breiten or {}).get(eintrag, FELDER[eintrag][1])
    return f"{FELDER[eintrag][0]}  {BREITEN_TEXTE.get(breite, breite)}"


# ---------------------------------------------------------------- Widgets

class _Zelle:
    """Schreibgeschützte Wert-Zelle: Entry im Zustand readonly (markier-/kopierbar), Rechtsklick-Menü
    „Kopieren“ (Markierung, sonst ganzer Wert) / „Alles kopieren“, Tooltip nur bei abgeschnittenem Wert."""

    def __init__(self, tabelle, schrift, alles_text):
        self.wert = ""
        self.schrift = schrift
        self.w = tk.Entry(tabelle, relief="flat", bd=0, highlightthickness=0, font=schrift,
                          readonlybackground=FARBE_GRAU, fg="#333333", state="readonly")
        Tooltip(self.w, self._tooltip_text)
        self.menu = tk.Menu(self.w, tearoff=0)
        self.menu.add_command(label="Kopieren", command=self.kopieren)
        self.menu.add_command(label="Alles kopieren", command=lambda: self._in_zwischenablage(alles_text()))
        self.w.bind("<Button-3>", self._menu_zeigen)

    def setze(self, wert):
        self.wert = wert or ""
        try:
            self.w.configure(state=tk.NORMAL)
            self.w.delete(0, tk.END)
            self.w.insert(0, self.wert)
            self.w.configure(state="readonly")
        except tk.TclError:
            pass

    def _tooltip_text(self):
        # Nur wenn der Wert breiter ist als die Zelle (abgeschnitten) - sonst kein Hinweis
        try:
            if self.wert and self.schrift.measure(self.wert) + 8 > self.w.winfo_width():
                return self.wert
        except tk.TclError:
            pass
        return ""

    def _menu_zeigen(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def kopieren(self):
        try:
            text = self.w.selection_get() if self.w.selection_present() else self.wert
        except tk.TclError:
            text = self.wert
        self._in_zwischenablage(text)

    def _in_zwischenablage(self, text):
        try:
            self.w.clipboard_clear()
            self.w.clipboard_append(text or "")
        except tk.TclError:
            pass


class EigenschaftenPanel:
    """
    Die Eigenschaften-Tabelle des Hauptfensters. `tabelle` ist der Raster-Frame (Hintergrund =
    Linienfarbe, 1 px Abstand zwischen den Zellen ergibt das Gitter); layout_builder legt die
    bearbeitbaren Widgets (Titel, Tags, Datum) MIT `tabelle` als Master an und übergibt sie per
    `setze_eingabefelder`. Das Häkchen `chk` („Details“) klappt die Zone „ausgeklappt“ ein/aus
    (persistiert in settings.json); `setze_aufteilung` übernimmt eine neue Feldaufteilung
    (Einstellungs-Oberfläche).
    """

    def __init__(self, app, parent, chk_parent=None):
        self.app = app
        self._lauf = 0
        self._aktueller_pfad = None
        self._aktueller_rel = ""
        self._eigenschaften = {}
        self._feste = []          # [(Bezeichner, Widget)] - volle Zeilen oben (Titel, Tags)
        self._eingabe = {}        # Schlüssel -> bearbeitbares Widget im Fluss (datum)
        self._labels = {}         # Bezeichner-Text -> Label
        self._fueller = []
        self._aufteilung = feldaufteilung(app.config.get(EINSTELLUNG_FELDER, None))

        self.var_sichtbar = tk.BooleanVar(value=bool(app.config.get(EINSTELLUNG_DETAILS, True)))
        # Die Checkbox darf in einem anderen Container sitzen (Knopfzeile unter der Tabelle)
        self.chk = ttk.Checkbutton(chk_parent or parent, text="Details", variable=self.var_sichtbar,
                                   command=self._umschalten)

        self.tabelle = tk.Frame(parent, bg=FARBE_LINIE)
        for paar in range(PAARE_JE_ZEILE):
            self.tabelle.grid_columnconfigure(2 * paar + 1, weight=1, uniform="wert")
        self.schrift = tkfont.nametofont("TkDefaultFont")
        self._innen = UIUtils.px(self.tabelle, 3)
        # Für jedes Feld eine graue Zelle; bearbeitbare Widgets aus setze_eingabefelder haben Vorrang
        self.zellen = {s: _Zelle(self.tabelle, self.schrift, self._alles_text) for s in FELDER}
        # Bezug zwischen Mail und Anhang; layout_builder setzt die Leiste hinter „Details“
        self.leiste_mail = ttk.Frame(chk_parent or parent)
        self._mail_bezug = ("", [])
        self._ist_mail = False
        self._link_schrift = tkfont.Font(font=self.schrift, underline=True)

    # ---------- Aufbau ----------
    def setze_eingabefelder(self, feste, fluss):
        """feste: [(Bezeichner, Widget)] als volle Zeilen oben; fluss: {Schlüssel: Widget} im Raster."""
        self._feste = list(feste)
        self._eingabe = dict(fluss)
        self._anordnen()

    def setze_aufteilung(self, aufteilung, speichern=True):
        self._aufteilung = feldaufteilung(aufteilung)
        if speichern:
            self.app.config.set(EINSTELLUNG_FELDER, self.aufteilung())
        self._anordnen()

    def aufteilung(self):
        return {z: (dict(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v))
                for z, v in self._aufteilung.items()}

    def sichtbare_schluessel(self):
        keys = list(self._aufteilung["immer"])
        if self.var_sichtbar.get():
            keys += self._aufteilung["ausgeklappt"]
        return keys

    def _label(self, text):
        if text not in self._labels:
            self._labels[text] = tk.Label(self.tabelle, text=text, anchor="w", bg=FARBE_WEISS,
                                          padx=UIUtils.px(self.tabelle, 5))
        return self._labels[text]

    def _platz_anfordern(self):
        """
        Der Eigenschaften-Bereich sitzt als unterster Teil im senkrechten PanedWindow (weight 0).
        Ändert sich die Höhe der Tabelle (Details auf/zu, andere Aufteilung), rückt ttk den
        Greifer nicht von selbst nach - der Bereich blieb gleich hoch und schnitt unten ab.
        Deshalb den Greifer über dem Bereich so setzen, dass der ganze Inhalt (Tabelle +
        Knopfzeile) sichtbar ist: der Bereich entfaltet sich nach oben (Peter 15.09.2026).
        """
        bereich = self.tabelle.master
        pane = bereich.master
        try:
            panes = [str(p) for p in pane.panes()]
            idx = panes.index(str(bereich)) - 1
            if idx < 0:
                return
            bereich.update_idletasks()
            noetig = bereich.winfo_reqheight() + UIUtils.px(bereich, 8)   # + Greifer-Dicke
            pane.sashpos(idx, max(0, pane.winfo_height() - noetig))
        except (tk.TclError, ValueError, AttributeError):
            pass  # kein PanedWindow (Tests/Attrappen) oder noch nicht gezeichnet

    def _anordnen(self):
        """Raster komplett neu legen: feste Zeilen, dann die sichtbaren Felder nach packe_zeilen."""
        for w in self.tabelle.grid_slaves():
            w.grid_forget()
        for f in self._fueller:
            f.destroy()
        self._fueller = []
        pad = {"padx": (0, 1), "pady": (0, 1)}
        r = 0
        for bez, widget in self._feste:
            self._label(bez).grid(row=r, column=0, sticky="nsew", **pad)
            widget.grid(row=r, column=1, columnspan=2 * PAARE_JE_ZEILE - 1, sticky="ew",
                        ipady=0 if isinstance(widget, tk.Text) else self._innen, **pad)
            r += 1
        for zeile in packe_zeilen(self.sichtbare_schluessel(), breiten=self._aufteilung["breiten"]):
            spalte = 0
            for schluessel, paare in zeile:
                self._label(FELDER[schluessel][0]).grid(row=r, column=spalte, sticky="nsew", **pad)
                widget = self._eingabe.get(schluessel) or self.zellen[schluessel].w
                widget.grid(row=r, column=spalte + 1, columnspan=2 * paare - 1, sticky="ew",
                            ipady=self._innen, **pad)
                spalte += 2 * paare
            if spalte < 2 * PAARE_JE_ZEILE:
                # Restzeile grau auffüllen, damit das Gitter geschlossen aussieht
                f = tk.Frame(self.tabelle, bg=FARBE_GRAU)
                f.grid(row=r, column=spalte, columnspan=2 * PAARE_JE_ZEILE - spalte, sticky="nsew", **pad)
                self._fueller.append(f)
            r += 1
        try:
            self.app.root.after_idle(self._platz_anfordern)
        except (tk.TclError, AttributeError):
            pass

    # ---------- Sichtbarkeit ----------
    def _umschalten(self, speichern=True):
        self._anordnen()
        if speichern:
            self.app.config.set(EINSTELLUNG_DETAILS, bool(self.var_sichtbar.get()))

    # ---------- Inhalt ----------
    def _alles_text(self):
        return formatiere_eigenschaften(self._eigenschaften)

    def _setze_werte(self, e):
        self._eigenschaften = e or {}
        for schluessel, zelle in self.zellen.items():
            wert = self._eigenschaften.get(schluessel, "")
            if schluessel == "ordner" and self._eigenschaften and not wert:
                wert = "(Hauptordner)"
            zelle.setze(wert)

    def _link(self, text, befehl):
        link = ttk.Label(self.leiste_mail, text=text, foreground=FARBE_LINK, cursor="hand2", font=self._link_schrift)
        link.bind("<Button-1>", lambda _e: befehl())
        return link

    def _zeige_mail_bezug(self, bezug, ist_mail=False):
        if (bezug, ist_mail) == (self._mail_bezug, self._ist_mail):
            return
        self._mail_bezug, self._ist_mail = bezug, ist_mail
        for w in self.leiste_mail.winfo_children():
            w.destroy()
        if ist_mail:
            self._link("Original-Mail öffnen", self._oeffne_original_mail).pack(
                side=tk.LEFT, padx=(0, UIUtils.px(self.leiste_mail, 16)))
        vorspann, links = bezug
        if not vorspann:
            return
        ttk.Label(self.leiste_mail, text=vorspann).pack(side=tk.LEFT)
        for text, rel_path in links[:MAX_MAIL_LINKS]:
            kurz = text if len(text) <= MAX_LINK_ZEICHEN else text[:MAX_LINK_ZEICHEN - 1] + "…"
            link = self._link(kurz, lambda r=rel_path: self._oeffne_verwandtes(r))
            link.pack(side=tk.LEFT, padx=(UIUtils.px(self.leiste_mail, 6), 0))
            Tooltip(link, text)
        rest = len(links) - MAX_MAIL_LINKS
        if rest > 0:
            ttk.Label(self.leiste_mail, text=f"+ {rest} weitere").pack(side=tk.LEFT, padx=(UIUtils.px(self.leiste_mail, 6), 0))

    def _oeffne_original_mail(self):
        """Öffnet die eingebettete Original-Mail im Standard-Mailprogramm, das Postfach bleibt unberührt."""
        pdf = self._aktueller_pfad
        fenster = self.leiste_mail.winfo_toplevel()
        try:
            pfad = original_mail_bereitstellen(pdf)
        except OSError as fehler:
            messagebox.showerror("Original-Mail", f"Die Mail ließ sich nicht bereitstellen: {fehler}", parent=fenster)
            return
        if pfad is None:
            messagebox.showinfo("Original-Mail", "In diesem PDF steckt keine Original-Mail.", parent=fenster)
            return
        try:
            os.startfile(pfad)
        except OSError:
            messagebox.showinfo("Original-Mail", "Auf diesem Rechner ist kein Programm für Mail-Dateien (.eml) "
                                f"eingerichtet.\n\nDie Mail liegt bis zum Beenden von KID hier:\n{pfad}", parent=fenster)

    def _oeffne_verwandtes(self, rel_path):
        self.app.folder_manager.zeige_dokument(os.path.join(self.app.master_folder, rel_path))

    def _lies_mail_bezug(self, e, rel_path):
        """Im Hintergrund-Thread: der Bezug des Dokuments für mail_bezug; ohne Index keiner (die Liste bleibt leer)."""
        index = getattr(self.app, "index_manager", None)
        if not e.get("mail_id") or index is None:
            return "", []
        try:
            verwandte = index.mail_verwandte(e["mail_id"], rel_path)
            master = self.app.master_folder
            return mail_bezug(e["ist_mail"], [(r, PDFHandler.get_metadata(os.path.join(master, r))) for r in verwandte])
        except Exception as fehler:      # noqa: BLE001 - der Bezug ist eine Zugabe, die Eigenschaften gelten trotzdem
            logger = getattr(self.app, "logger", None)
            if logger:
                logger.error(f"Mail-Bezug nicht lesbar: {fehler}")
            return "", []

    def leeren(self):
        self._lauf += 1
        self._aktueller_pfad = None
        self._aktueller_rel = ""
        self._setze_werte({})
        self._zeige_mail_bezug(("", []))

    def zeige(self, abs_path, rel_path=""):
        """Liest die Eigenschaften im Hintergrund und trägt sie über root.after ein."""
        self._aktueller_pfad = abs_path
        self._aktueller_rel = rel_path
        self._lauf += 1
        lauf = self._lauf
        self._setze_werte({"dateiname": os.path.basename(abs_path), "fehler": "(wird gelesen …)"})
        self._zeige_mail_bezug(("", []))

        def worker():
            try:
                e = sammle_eigenschaften(abs_path, rel_path)
            except Exception as fehler:
                e = {"dateiname": os.path.basename(abs_path), "fehler": f"Eigenschaften nicht lesbar: {fehler}"}
            try:
                self.app.root.after(0, self._eintragen, lauf, e)
                # Danach, nicht davor: ein veralteter Index braucht einen Abgleich, das darf die Tabelle nicht aufhalten
                bezug = self._lies_mail_bezug(e, rel_path)
                self.app.root.after(0, self._eintragen_bezug, lauf, bezug)
            except (tk.TclError, RuntimeError):
                pass  # Fenster wird gerade geschlossen

        threading.Thread(target=worker, daemon=True).start()

    def _eintragen(self, lauf, e):
        if lauf != self._lauf:
            return  # inzwischen ein anderes Dokument gewählt
        self._setze_werte(e)
        self._zeige_mail_bezug(("", []), bool(e.get("ist_mail")))

    def _eintragen_bezug(self, lauf, bezug):
        if lauf == self._lauf:
            self._zeige_mail_bezug(bezug, self._ist_mail)
