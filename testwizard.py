"""
Test-Wizard: geht eine manuelle Test-Checkliste (Markdown) Punkt für Punkt mit dem
Tester durch und schreibt die Ergebnisse in dieselbe Datei zurück. Entwickler-Werkzeug,
unabhängig von dem Projekt, das getestet wird - nur Python-Standardbibliothek + Tkinter.

    python testwizard.py                      Wizard starten (Tkinter-Fenster)
    python testwizard.py --abschnitt 14       direkt mit Abschnitt 14 beginnen
    python testwizard.py --projekt ../App     Checkliste eines anderen Ordners führen
    python testwizard.py --checkliste X.md    genau diese Datei führen

Projekt-Einstellungen stehen in `testwizard.json` neben der Checkliste (alle Schlüssel
optional, siehe `testwizard.beispiel.json` und lade_konfiguration):

    {
      "checkliste": "MANUELLE_TESTS.md",
      "testordner": "C:/Testdaten/App",
      "app_start": ["python", "main.py"],
      "app_knopf": "App starten (main.py)",
      "titel": "Manuelle Tests - Wizard"
    }

Der Wizard liest die Checkliste, zeigt einen Prüfpunkt nach dem anderen und
schreibt das Ergebnis in dieselbe Datei zurück:

    * [x] **T14.1 Titel:** ...               bestanden (T14.1 = feste Kennung, frei wählbar)
    * [ ] **T14.2 Titel:** ...               offen / fehlgeschlagen
      * ✗ 2026-09-11: Notiz des Testers      Fehlnotiz (Unterpunkt, bleibt als Befund stehen)
      * 📝 2026-10-25: Beobachtung           Notiz, unabhängig vom Ergebnis (auch bei bestanden)
      * 💡 2026-10-25: Einfall                Idee zum Prüfpunkt oder zur getesteten Funktion

Jeder Prüfpunkt kann in MANUELLE_TESTS.md Unterpunkte tragen, die der Wizard als
eigene Felder zeigt (alle optional, Reihenfolge egal):

    * [ ] **Titel:** Fragen des Prüfpunkts ...
      * Vorbereitung: welcher Zustand vorher gelten muss (z.B. leere Datenbank)
      * Datei: Eingang\\Rechnung Muster GmbH.pdf   (relativ zum Testordner)
      * Klicks: Extras → Import → Vorschau …  (Klickfolge, "→" trennt)

Links ein Baum (seit 17.09.2026): Abschnitte als Knoten, darunter jeder Prüfpunkt mit
Status (✓ abgehakt grau, ✗ heute fehlgeschlagen rot, ○ offen) - ein Klick zeigt ihn rechts,
auch einen längst abgehakten. "Nur ungeprüfte zeigen" blendet Abgehaktes UND heute schon
als fehlgeschlagen Notiertes aus dem Baum aus - nach einem Neustart geht es beim nächsten
ungeprüften Punkt weiter; Haken weg = alles sehen (Fehlnotizen früherer Tage erscheinen
ohnehin rot unter den Fragen).
Die Fragen im Haupttext werden am "?" in nummerierte Einzelfragen zerlegt und als
Tabelle gezeigt: je Frage ein Haken „Bestanden" und eine Notiz-Spalte, darunter eine
allgemeine Notiz zum Prüfpunkt. „Fehlgeschlagen" schreibt daraus EINE Fehlnotiz-Zeile,
z.B. "1 ✓; 2 ✗ Tooltip fehlt; 3 ✓ — Fenster flackert". Notizen gehen nie verloren: bei
„Bestanden" werden sie als 📝-Notiz gespeichert, „Nur Notiz speichern" schreibt Notiz und
Idee (💡) ohne Ergebnis. "Ordner öffnen" zeigt die Datei
des Prüfpunkts im Explorer, "App starten" startet das konfigurierte Kommando als eigenen
Prozess (beide Knöpfe erscheinen nur, wenn `testordner` bzw. `app_start` konfiguriert sind).
Rechtsklick auf einen Abschnitt im Baum setzt alle Haken dieses Abschnitts zurück - für
Checklisten, die wiederholt durchlaufen werden (z.B. ein Release-Check); Befunde, Notizen
und Ideen bleiben dabei stehen.
"""

import datetime as _dt
import json
import os
import re
import subprocess
import sys

KONFIG_DATEI = "testwizard.json"
STANDARD_CHECKLISTE = "MANUELLE_TESTS.md"
STANDARD_TITEL = "Manuelle Tests - Wizard"

# Wird von _starte_gui aus der Konfiguration gefüllt; lade()/speichere() greifen darauf zu.
PROJEKT = os.path.abspath(".")
CHECKLISTE = os.path.join(PROJEKT, STANDARD_CHECKLISTE)
TESTORDNER = ""      # Wurzel für die "Datei:"-Angaben der Prüfpunkte (leer = keine)
APP_START = []       # Kommando für "App starten" (leer = Knopf ausblenden)
APP_KNOPF = "App starten"
TITEL = STANDARD_TITEL

_ABSCHNITT = re.compile(r"^##\s+(.*?)\s*$")
_PRUEFPUNKT = re.compile(r"^\* \[( |x|X|-|\?)\]\s*(.*)$")  # [-]/[?] = teilweise/unklar, zählt als offen
_TITEL = re.compile(r"^\*\*(.+?)\*\*\s*(.*)$", re.S)
_UNTERPUNKT = re.compile(r"^\s{2,}\* (.*)$")
_FEHLNOTIZ = re.compile(r"^✗\s*(\d{4}-\d{2}-\d{2}):\s*(.*)$")
# Notiz (📝) und Idee (💡): unabhängig vom Ergebnis, bleiben wie Fehlnotizen als Unterpunkt stehen
NOTIZ, IDEE = "📝", "💡"
_NOTIZ = re.compile(r"^(📝|💡)\s*(\d{4}-\d{2}-\d{2}):\s*(.*)$")
_KENNUNG = re.compile(r"^(T[0-9]+[a-z]?\.[0-9]+)\s+")
FELDER = ("Vorbereitung", "Datei", "Klicks")
KLICKS_ZEILEN = 8  # mehr Klick-Schritte scrollen im Feld, statt den Fragen-Bereich zu verdrängen
FARBE_LINIE = "#c8c8c8"   # Fragen-Tabelle: Rasterlinien (wie die Eigenschaften-Tabelle der App)
FARBE_KOPF = "#e6e6e6"
FARBE_OK = "#e9f7e9"      # Zeile mit Haken


# ---------------------------------------------------------------- Parsen / Schreiben
def parse_checkliste(text):
    """
    Zerlegt MANUELLE_TESTS.md in Abschnitte mit Prüfpunkten.
    :return: Liste von {"titel", "zeile", "punkte": [ {...} ]}; Prüfpunkt = {"zeile" (0-basiert),
             "erledigt", "titel", "text", "vorbereitung", "datei", "klicks", "fehlnotizen": [(datum, notiz)],
             "notizen": [(art, datum, text)] mit art NOTIZ/IDEE, "letzte_zeile" (letzte zum Punkt gehörende Zeile)}
             Fehlnotizen und Notizen stehen neueste zuerst (der Wizard fügt direkt unter dem Punkt ein).
    """
    abschnitte = []
    aktuell = None
    punkt = None
    for nr, zeile in enumerate(text.splitlines()):
        m = _ABSCHNITT.match(zeile)
        if m:
            aktuell = {"titel": m.group(1), "zeile": nr, "punkte": []}
            abschnitte.append(aktuell)
            punkt = None
            continue
        m = _PRUEFPUNKT.match(zeile)
        if m and aktuell is not None:
            rest = m.group(2).strip()
            t = _TITEL.match(rest)
            titel, body = (t.group(1).rstrip(":").strip(), t.group(2).strip()) if t else ("", rest)
            # feste Kennung 'T14.3' am Titelanfang (siehe Kopf von MANUELLE_TESTS.md)
            kennung = _KENNUNG.match(titel)
            test_id, titel = (kennung.group(1), titel[kennung.end():].strip()) if kennung else ("", titel)
            punkt = {"zeile": nr, "letzte_zeile": nr, "erledigt": m.group(1).lower() == "x",
                     "id": test_id, "titel": titel, "text": body, "vorbereitung": "", "datei": "", "klicks": "",
                     "fehlnotizen": [], "notizen": []}
            aktuell["punkte"].append(punkt)
            continue
        m = _UNTERPUNKT.match(zeile)
        if m and punkt is not None:
            inhalt = m.group(1).strip()
            punkt["letzte_zeile"] = nr
            f = _FEHLNOTIZ.match(inhalt)
            if f:
                punkt["fehlnotizen"].append((f.group(1), f.group(2).strip()))
                continue
            n = _NOTIZ.match(inhalt)
            if n:
                punkt["notizen"].append((n.group(1), n.group(2), n.group(3).strip()))
                continue
            for feld in FELDER:
                if inhalt.lower().startswith(feld.lower() + ":"):
                    punkt[feld.lower()] = inhalt[len(feld) + 1:].strip()
                    break
            continue
        if zeile.strip() == "" or zeile.startswith("#"):
            punkt = None  # Leerzeile/Überschrift beendet den Prüfpunkt-Block
    return abschnitte


def frage_liste(text):
    """Zerlegt den Prüftext am '?' in Einzelfragen (Klammer-Nachsätze bleiben beim Satz)."""
    teile = re.split(r"(?<=\?)\s+(?=[A-ZÄÖÜ„(\"'])", text.strip())
    return [t.strip() for t in teile if t.strip()]


def fehlnotiz_text(zeilen, allgemein=""):
    """
    Baut aus der Fragen-Tabelle des Wizards EINE Fehlnotiz-Zeile: je Frage Nummer + ✓/✗ + Notiz,
    dahinter die allgemeine Notiz. ``zeilen`` = [(bestanden, notiz)] in Fragenreihenfolge; bei nur
    einer Frage entfällt die Nummerierung. Beispiel: '1 ✓; 2 ✗ Tooltip fehlt; 3 ✓ — Fenster flackert'
    """
    allgemein = " ".join(allgemein.split())
    teile = []
    if len(zeilen) == 1:
        notiz = " ".join(zeilen[0][1].split())
        if notiz:
            teile.append(notiz)
    else:
        for nr, (ok, notiz) in enumerate(zeilen, 1):
            notiz = " ".join(notiz.split())
            teile.append(f"{nr} {'✓' if ok else '✗'}" + (f" {notiz}" if notiz else ""))
    text = "; ".join(teile)
    if allgemein:
        text = f"{text} — {allgemein}" if text else allgemein
    return text


def notiz_text(notizen, allgemein=""):
    """
    Notiz-Zeile für bestandene Punkte bzw. „Nur Notiz speichern": nur die Fragen, die eine Notiz
    tragen, mit Nummer; dahinter die allgemeine Notiz. ``notizen`` = Notiz je Frage in Reihenfolge
    (leere Strings erlaubt). Bei nur einer Frage entfällt die Nummer.
    Beispiel: '2: Tooltip erscheint verzögert — Idee für später'.
    """
    allgemein = " ".join(allgemein.split())
    teile = []
    for nr, notiz in enumerate(notizen, 1):
        notiz = " ".join(notiz.split())
        if notiz:
            teile.append(notiz if len(notizen) == 1 else f"{nr}: {notiz}")
    text = "; ".join(teile)
    if allgemein:
        text = f"{text} — {allgemein}" if text else allgemein
    return text


def fehlnotiz_parsen(text, anzahl):
    """
    Umkehrung von fehlnotiz_text: liest '1 ✓; 2 ✗ Tooltip fehlt; 3 ✓ — Fenster flackert' zurück in
    ([(bestanden, notiz)], allgemein), damit der Wizard Haken und Notizen eines schon geprüften
    Punkts wieder zeigt. None, wenn der Text nicht in diesem Format ist (ältere, freie Notizen)
    oder die Fragenzahl nicht passt. Bei genau einer Frage ist die Notiz unnummeriert - dann
    zählt der ganze Text (vor ' — ') als Zeilen-Notiz.
    """
    kopf, _, allgemein = text.partition(" — ")
    if anzahl == 1:
        m = re.match(r"^\d+ [✓✗]", kopf)
        if m:
            return None
        return [(False, kopf.strip())], allgemein.strip()
    zeilen = []
    for teil in re.split(r"; (?=\d+ [✓✗])", kopf):
        m = re.match(r"^(\d+) ([✓✗])(?: (.*))?$", teil, re.S)
        if not m or int(m.group(1)) != len(zeilen) + 1:
            return None
        zeilen.append((m.group(2) == "✓", (m.group(3) or "").strip()))
    if len(zeilen) != anzahl:
        return None
    return zeilen, allgemein.strip()


def heute_fehlgeschlagen(punkt, heute=None):
    """True, wenn der Prüfpunkt eine Fehlnotiz mit dem heutigen Datum trägt (in dieser Sitzung schon geprüft)."""
    heute = heute or _dt.date.today().isoformat()
    return any(datum == heute for datum, _ in punkt.get("fehlnotizen", ()))


def _zeilen(text):
    nl = "\r\n" if "\r\n" in text else "\n"
    return text.split(nl), nl


def markiere(text, zeile, bestanden, notiz="", datum=None, kennung=""):
    """
    Schreibt das Ergebnis eines Prüfpunkts (0-basierte Zeilennummer aus parse_checkliste)
    in den Text zurück: bestanden -> '[x]'; fehlgeschlagen -> '[ ]' plus Fehlnotiz als
    Unterpunkt direkt unter dem Punkt (vor evtl. vorhandenen Unterpunkten, damit die
    Notiz sofort ins Auge fällt). Zeilenenden bleiben, wie sie sind.
    Mit ``kennung`` (z.B. 'T14.3') wird der Punkt über seine ID wiedergefunden, falls sich
    die Datei seit dem Einlesen verschoben hat (Editor oder Claude haben Zeilen eingefügt).
    """
    zeilen, nl = _zeilen(text)
    zeile = _finde_punktzeile(zeilen, zeile, kennung)
    m = _PRUEFPUNKT.match(zeilen[zeile])
    zeilen[zeile] = "* [" + ("x" if bestanden else " ") + "] " + m.group(2)
    if not bestanden and notiz.strip():
        datum = datum or _dt.date.today().isoformat()
        zeilen.insert(zeile + 1, f"  * ✗ {datum}: {' '.join(notiz.split())}")
    return nl.join(zeilen)


def haken_zuruecksetzen(text, abschnitt_zeile):
    """
    Setzt alle abgehakten Prüfpunkte (`* [x]`) des Abschnitts, dessen Überschrift in Zeile
    ``abschnitt_zeile`` (0-basiert, aus parse_checkliste) steht, wieder auf offen (`* [ ]`) -
    bis zur nächsten `## `-Überschrift. Unterpunkte (Befunde, Notizen, Ideen) bleiben stehen.
    :return: (neuer Text, Anzahl zurückgesetzter Punkte)
    """
    zeilen, nl = _zeilen(text)
    if not (abschnitt_zeile < len(zeilen) and _ABSCHNITT.match(zeilen[abschnitt_zeile])):
        raise ValueError(f"Zeile {abschnitt_zeile + 1} ist keine Abschnitts-Überschrift")
    anzahl = 0
    for i in range(abschnitt_zeile + 1, len(zeilen)):
        if _ABSCHNITT.match(zeilen[i]):
            break
        m = _PRUEFPUNKT.match(zeilen[i])
        if m and m.group(1).lower() == "x":
            zeilen[i] = "* [ ] " + m.group(2)
            anzahl += 1
    return nl.join(zeilen), anzahl


def fuege_notiz_ein(text, zeile, notiz, art=NOTIZ, datum=None, kennung=""):
    """
    Schreibt eine Notiz (📝) oder Idee (💡) als Unterpunkt direkt unter den Prüfpunkt, ohne
    das Ergebnis anzufassen. Leere Notiz = Text unverändert. Wiederfinden über ``kennung``
    wie bei markiere; Zeilenenden bleiben, wie sie sind.
    """
    if art not in (NOTIZ, IDEE):
        raise ValueError(f"Unbekannte Notiz-Art {art!r}")
    if not notiz.strip():
        return text
    zeilen, nl = _zeilen(text)
    zeile = _finde_punktzeile(zeilen, zeile, kennung)
    datum = datum or _dt.date.today().isoformat()
    zeilen.insert(zeile + 1, f"  * {art} {datum}: {' '.join(notiz.split())}")
    return nl.join(zeilen)


def _finde_punktzeile(zeilen, zeile, kennung=""):
    """Zeilenindex des Prüfpunkts; mit ``kennung`` auch nach Verschiebungen. ValueError, wenn keiner da ist."""
    if kennung:
        marke = f"**{kennung} "
        if not (zeile < len(zeilen) and _PRUEFPUNKT.match(zeilen[zeile]) and marke in zeilen[zeile]):
            treffer = [i for i, z in enumerate(zeilen) if _PRUEFPUNKT.match(z) and marke in z]
            if len(treffer) != 1:
                raise ValueError(f"Prüfpunkt {kennung} nicht eindeutig in der Checkliste gefunden ({len(treffer)}x)")
            zeile = treffer[0]
    if not (zeile < len(zeilen) and _PRUEFPUNKT.match(zeilen[zeile])):
        raise ValueError(f"Zeile {zeile + 1} ist kein Prüfpunkt: {zeilen[zeile][:60] if zeile < len(zeilen) else ''!r}")
    return zeile


def lade_konfiguration(projekt=None, checkliste=None):
    """
    Liest `testwizard.json` (falls vorhanden) aus dem Projektordner und setzt daraus die
    Modul-Einstellungen. ``projekt`` ist der Ordner mit Checkliste und Konfiguration
    (Standard: aktuelles Verzeichnis), ``checkliste`` übersteuert den Dateinamen aus der
    Konfiguration. Relative Pfade in der Konfiguration gelten relativ zum Projektordner, ``~`` = Benutzerordner.
    Liefert die gelesene Konfiguration als dict (leer, wenn es keine Datei gibt).
    """
    global PROJEKT, CHECKLISTE, TESTORDNER, APP_START, APP_KNOPF, TITEL
    PROJEKT = os.path.abspath(projekt or ".")
    konfig = {}
    pfad = os.path.join(PROJEKT, KONFIG_DATEI)
    if os.path.isfile(pfad):
        with open(pfad, encoding="utf-8") as f:
            konfig = json.load(f)

    def im_projekt(wert):
        wert = os.path.expanduser(wert)          # "~/Testdaten" = im Benutzerordner
        return wert if os.path.isabs(wert) else os.path.join(PROJEKT, wert)

    CHECKLISTE = im_projekt(checkliste or konfig.get("checkliste") or STANDARD_CHECKLISTE)
    testordner = konfig.get("testordner") or ""
    TESTORDNER = im_projekt(testordner) if testordner else ""
    start = konfig.get("app_start") or []
    APP_START = [start] if isinstance(start, str) else list(start)
    APP_KNOPF = konfig.get("app_knopf") or "App starten"
    TITEL = konfig.get("titel") or STANDARD_TITEL
    return konfig


def lade():
    with open(CHECKLISTE, encoding="utf-8", newline="") as f:
        return f.read()


def speichere(text):
    with open(CHECKLISTE, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ---------------------------------------------------------------- Oberfläche
def _starte_gui(start_abschnitt=None, screenshot=None, nach_start=None):
    import tkinter as tk
    from tkinter import ttk, messagebox

    class Wizard(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(TITEL)
            self.geometry("1000x800+80+40")
            # Mindestgröße so, dass Vorbereitung, Datei, 8 Klick-Zeilen, Fragen, Notiz und
            # Knöpfe zusammen Platz haben - kleiner ließ sich der Fragen-Bereich wegdrücken
            self.minsize(840, 720)
            # Immer im Vordergrund (Nutzerwunsch 11.09.2026): beim Testen wandert der Wizard
            # sonst hinter das App-Fenster und wird vergessen.
            self.attributes("-topmost", True)
            self.nur_offene = tk.BooleanVar(value=True)
            self.abschnitte = []
            self.position = 0     # Index in self.punkte
            self.punkte = []      # (abschnitt, punkt) der aktuellen Auswahl
            self.ergebnisse = []  # (abschnittstitel, punkttitel, bestanden, notiz)
            self._bau()
            self._lade_liste()
            if start_abschnitt:
                self._waehle_abschnitt(start_abschnitt)

        # ---------- Aufbau
        def _bau(self):
            # tk.PanedWindow statt ttk: kennt 'minsize' je Seite - der Trenner lässt sich sonst
            # so weit schieben, dass Liste oder Prüfpunkt verschwinden (Nutzerfund 11.09.2026)
            haupt = tk.PanedWindow(self, orient=tk.HORIZONTAL, sashwidth=6, sashrelief=tk.RAISED, bd=0)
            haupt.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

            links = ttk.Frame(haupt, padding=4)
            haupt.add(links, minsize=280, stretch="never")  # Liste behält ihre Breite, der Prüfpunkt rechts wächst
            ttk.Label(links, text="Abschnitte (ungeprüft / gesamt) und Prüfpunkte").pack(anchor="w")
            # Baum statt Listbox (Nutzerwunsch 17.09.2026): Prüfpunkte als Kinder, jeder direkt anklickbar -
            # auch abgehakte lassen sich so noch einmal ansehen (Filter aus)
            baumrahmen = ttk.Frame(links)
            baumrahmen.pack(fill=tk.BOTH, expand=True)
            self.baum = ttk.Treeview(baumrahmen, show="tree", selectmode="browse")
            rollen = ttk.Scrollbar(baumrahmen, command=self.baum.yview)
            self.baum.configure(yscrollcommand=rollen.set)
            rollen.pack(side=tk.RIGHT, fill=tk.Y)
            self.baum.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.baum.column("#0", width=320, stretch=True)
            self.baum.tag_configure("fertig", foreground="#888")
            self.baum.tag_configure("fehl", foreground="#a33")
            self.baum.bind("<<TreeviewSelect>>", lambda e: self._baum_gewaehlt())
            self.baum.bind("<Button-3>", self._baum_kontextmenue)
            self._angezeigt_iid = None  # Baum-Knoten des rechts gezeigten Punkts (verhindert Echo der eigenen Auswahl)
            self._klick_im_baum = False  # während _baum_gewaehlt: Auswahl/Aufklappen NICHT nachführen
            ttk.Checkbutton(links, text="nur ungeprüfte zeigen (ohne heutige ✗)", variable=self.nur_offene,
                            command=self._filter_geaendert).pack(anchor="w", pady=(4, 0))
            # App- und Ordner-Knopf nur, wenn das Projekt sie konfiguriert hat (testwizard.json)
            if APP_START:
                ttk.Button(links, text=APP_KNOPF, command=self._app_starten).pack(fill=tk.X, pady=(8, 2))
            if TESTORDNER:
                ttk.Button(links, text="Testordner im Explorer",
                           command=lambda: self._oeffne(TESTORDNER)).pack(fill=tk.X, pady=2)
            ttk.Button(links, text="Sitzungs-Zusammenfassung", command=self._zusammenfassung).pack(fill=tk.X, pady=(8, 2))

            rechts = ttk.Frame(haupt, padding=4)
            haupt.add(rechts, minsize=520, stretch="always")

            # Bedienleiste und Notiz ZUERST und von unten packen: sie bleiben immer sichtbar,
            # auch wenn Vorbereitung/Klicks lang sind (Nutzerfund 11.09.2026: Knöpfe lagen
            # außerhalb des Fensters). Der Fragen-Bereich bekommt den Rest und scrollt.
            knoepfe = ttk.Frame(rechts)
            knoepfe.pack(side=tk.BOTTOM, fill=tk.X)
            ttk.Button(knoepfe, text="◀ Zurück", command=lambda: self._springe(-1)).pack(side=tk.LEFT)
            ttk.Button(knoepfe, text="Überspringen ▶", command=lambda: self._springe(+1)).pack(side=tk.LEFT, padx=6)
            ttk.Button(knoepfe, text="Fehlgeschlagen ✗", command=lambda: self._ergebnis(False)).pack(side=tk.RIGHT)
            ttk.Button(knoepfe, text="Bestanden ✓", command=lambda: self._ergebnis(True)).pack(side=tk.RIGHT, padx=6)
            # Notizen/Ideen ohne Ergebnis festhalten (Nutzerwunsch 25.10.2026) - der Punkt bleibt, wie er ist
            ttk.Button(knoepfe, text="Nur Notiz speichern 📝", command=self._nur_notiz).pack(side=tk.RIGHT, padx=(0, 12))
            self.bind("<Control-Return>", lambda e: self._ergebnis(True))
            ideenzeile = ttk.Frame(rechts)
            ideenzeile.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 6))
            ttk.Label(ideenzeile, text="💡 Idee:").pack(side=tk.LEFT)
            self.ent_idee = ttk.Entry(ideenzeile, font=("Segoe UI", 10))
            self.ent_idee.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(6, 0))
            self.txt_notiz = tk.Text(rechts, height=3, font=("Segoe UI", 10))
            self.txt_notiz.pack(side=tk.BOTTOM, fill=tk.X, pady=(0, 6))
            ttk.Label(rechts, text="Notiz zum Prüfpunkt (wird immer gespeichert: bei Bestanden als 📝-Notiz, "
                                   "bei Fehlgeschlagen im ✗-Befund):").pack(side=tk.BOTTOM, anchor="w")

            self.lbl_kopf = ttk.Label(rechts, text="Links einen Abschnitt wählen.", font=("Segoe UI", 10, "bold"),
                                      wraplength=640, justify=tk.LEFT)
            self.lbl_kopf.pack(anchor="w")
            self.lbl_titel = ttk.Label(rechts, text="", font=("Segoe UI", 14, "bold"), wraplength=640)
            self.lbl_titel.pack(anchor="w", pady=(6, 8))

            self.felder = {}
            for feld, farbe in (("Vorbereitung", "#fff4d6"), ("Datei", "#e8f1ff"), ("Klicks", "#e9f7e9")):
                rahmen = ttk.LabelFrame(rechts, text=feld, padding=6)
                if feld == "Klicks":
                    # Klickfolgen können 15+ Schritte haben: begrenzte Höhe (max. KLICKS_ZEILEN),
                    # darüber hinaus scrollen - sonst drückt die Liste den Fragen-Bereich weg
                    inhalt = tk.Text(rahmen, wrap="word", height=4, font=("Segoe UI", 9), relief="flat",
                                     bg=farbe, cursor="arrow")
                    rollen = ttk.Scrollbar(rahmen, command=inhalt.yview)
                    inhalt.configure(yscrollcommand=rollen.set, state="disabled")
                    rollen.pack(side=tk.RIGHT, fill=tk.Y)
                    inhalt.pack(fill=tk.X, side=tk.LEFT, expand=True)
                    self.felder[feld] = (rahmen, inhalt)
                    continue
                # Datei-Feld: schmaler umbrechen, rechts daneben die beiden Knöpfe übereinander
                inhalt = tk.Label(rahmen, text="", justify=tk.LEFT, anchor="w",
                                  wraplength=480 if feld == "Datei" else 600, bg=farbe)
                inhalt.pack(fill=tk.X, side=tk.LEFT, expand=True)
                if feld == "Datei":
                    knopfspalte = ttk.Frame(rahmen)
                    knopfspalte.pack(side=tk.RIGHT, padx=(6, 0))
                    ttk.Button(knopfspalte, text="Ordner öffnen", command=self._datei_ordner_oeffnen).pack(fill=tk.X)
                    ttk.Button(knopfspalte, text="Pfad kopieren", command=self._datei_pfad_kopieren).pack(fill=tk.X, pady=(3, 0))
                self.felder[feld] = (rahmen, inhalt)

            # Fragen-Tabelle (Nutzerwunsch 17.09.2026): je Einzelfrage eine Zeile mit Haken „Bestanden"
            # und eigener Notiz-Spalte, statt alles in EINE Notiz zu tippen ("1. Ja 2. Teilweise 3. …").
            # Raster mit Linien wie in der Eigenschaften-Tabelle der App: Rahmen in Linienfarbe,
            # Zellen mit 1 px Abstand; das Ganze liegt in einem Canvas, damit es scrollen kann.
            self.fragen_rahmen = ttk.LabelFrame(rechts, text="Prüfen - Haken je Frage, Notiz nach Bedarf", padding=6)
            self.fragen_rahmen.pack(fill=tk.BOTH, expand=True, pady=(4, 4))
            self.canvas_fragen = tk.Canvas(self.fragen_rahmen, highlightthickness=0, bg="white")
            scroll = ttk.Scrollbar(self.fragen_rahmen, command=self.canvas_fragen.yview)
            self.canvas_fragen.configure(yscrollcommand=scroll.set)
            scroll.pack(side=tk.RIGHT, fill=tk.Y)
            self.canvas_fragen.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self.tabelle = tk.Frame(self.canvas_fragen, bg=FARBE_LINIE)
            self._tabelle_fenster = self.canvas_fragen.create_window((0, 0), window=self.tabelle, anchor="nw")
            self.tabelle.columnconfigure(1, weight=1)  # die Frage bekommt die restliche Breite
            self.canvas_fragen.bind("<Configure>", self._tabelle_breite)
            self.tabelle.bind("<Configure>", lambda e: self.canvas_fragen.configure(
                scrollregion=self.canvas_fragen.bbox("all")))
            self.bind_all("<MouseWheel>", self._rad)
            self.fragen_zeilen = []  # je Frage {"var", "notiz", "frage", "zellen"}
            # Frühere Fehlnotizen (rot) unter der Tabelle, nur gepackt, wenn es welche gibt
            self.lbl_befunde = tk.Label(rechts, text="", fg="#a33", justify=tk.LEFT, anchor="w",
                                        wraplength=640, font=("Segoe UI", 9, "italic"))
            # Frühere Notizen (📝) und Ideen (💡) darunter, ruhiger gefärbt als die Befunde
            self.lbl_notizen = tk.Label(rechts, text="", fg="#3a5a80", justify=tk.LEFT, anchor="w",
                                        wraplength=640, font=("Segoe UI", 9))
            # Umbruchbreite der Textzeilen der rechten Seite folgt der Breite des Bereichs (Trenner, Fenster)
            rechts.bind("<Configure>", lambda e: [w.configure(wraplength=max(200, e.width - 12))
                                                  for w in (self.lbl_kopf, self.lbl_titel, self.lbl_befunde,
                                                            self.lbl_notizen)])

        # ---------- Fragen-Tabelle
        def _fragen_fuellen(self, fragen):
            """Baut das Raster neu: Kopfzeile plus je Frage Nr. | Frage | Haken | Notiz-Eingabe."""
            for w in self.tabelle.winfo_children():
                w.destroy()
            self.fragen_zeilen = []
            for c, text in enumerate(("Nr.", "Frage", "Bestanden", "Notiz")):
                tk.Label(self.tabelle, text=text, bg=FARBE_KOPF, anchor="w", padx=4, pady=2,
                         font=("Segoe UI", 9, "bold")).grid(row=0, column=c, sticky="nsew", padx=(0, 1), pady=(0, 1))
            for i, frage in enumerate(fragen, 1):
                var = tk.BooleanVar(value=False)
                nr = tk.Label(self.tabelle, text=f"{i}.", bg="white", anchor="n", padx=4, pady=3,
                              font=("Segoe UI", 10, "bold"), fg="#5b7fa6")
                lbl = tk.Label(self.tabelle, text=frage, bg="white", anchor="nw", justify=tk.LEFT,
                               padx=4, pady=3, font=("Segoe UI", 10), wraplength=400)
                zelle = tk.Frame(self.tabelle, bg="white", cursor="hand2")
                chk = tk.Checkbutton(zelle, variable=var, bg="white", activebackground="white",
                                     highlightthickness=0, cursor="hand2",
                                     command=lambda i=i: self._zeile_faerben(i - 1))
                chk.pack(padx=14, pady=2)
                notiz = tk.Entry(self.tabelle, relief="flat", bd=0, width=30, font=("Segoe UI", 10), bg="white")
                nr.grid(row=i, column=0, sticky="nsew", padx=(0, 1), pady=(0, 1))
                lbl.grid(row=i, column=1, sticky="nsew", padx=(0, 1), pady=(0, 1))
                zelle.grid(row=i, column=2, sticky="nsew", padx=(0, 1), pady=(0, 1))
                notiz.grid(row=i, column=3, sticky="nsew", padx=(0, 1), pady=(0, 1), ipady=3)
                # Klick irgendwo in der „Bestanden"-Zelle (nicht nur aufs Kästchen) setzt den Haken
                zelle.bind("<Button-1>", lambda e, i=i: self._zeile_umschalten(i - 1))
                self.fragen_zeilen.append({"var": var, "notiz": notiz, "frage": lbl, "zellen": (nr, lbl, zelle)})
            self._tabelle_breite()
            self.canvas_fragen.yview_moveto(0)

        def _zeile_umschalten(self, i):
            z = self.fragen_zeilen[i]
            z["var"].set(not z["var"].get())
            self._zeile_faerben(i)

        def _zeile_faerben(self, i):
            z = self.fragen_zeilen[i]
            farbe = FARBE_OK if z["var"].get() else "white"
            for w in z["zellen"]:
                w.configure(bg=farbe)
            for w in z["zellen"][2].winfo_children():
                w.configure(bg=farbe, activebackground=farbe)

        def _tabelle_breite(self, event=None):
            """Tabelle so breit wie der Canvas; die Frage-Spalte bricht auf die verbleibende Breite um."""
            breite = self.canvas_fragen.winfo_width()
            if breite < 50:
                return
            self.canvas_fragen.itemconfigure(self._tabelle_fenster, width=breite)
            if not self.fragen_zeilen:
                return
            # Was der Frage-Spalte bleibt: Canvas minus die festen Spalten (deren Breite bestimmt die breiteste
            # Zelle, oft die Kopfzeile „Bestanden" - deshalb über grid_bbox messen, nicht über die Zellen der
            # ersten Zeile), minus Rasterlinie und Innenabstände des Labels; zu viel wird rechts abgeschnitten
            self.tabelle.update_idletasks()
            fest = sum(self.tabelle.grid_bbox(c, 0)[2] for c in (0, 2, 3))
            rest = breite - fest - 1 - 2 * 4 - 8
            for z in self.fragen_zeilen:
                z["frage"].configure(wraplength=max(120, rest))

        def _rad(self, event):
            """Mausrad über der Fragen-Tabelle scrollt den Canvas (die Kinder fangen es sonst nicht)."""
            w = self.winfo_containing(event.x_root, event.y_root)
            if w is not None and str(w).startswith(str(self.canvas_fragen)):
                self.canvas_fragen.yview_scroll(-1 if event.delta > 0 else 1, "units")

        # ---------- Daten
        def _ungeprueft(self, p):
            """Zählt/zeigt der Filter diesen Punkt? (nicht abgehakt und - bei aktivem Filter - heute nicht ✗)"""
            return not p["erledigt"] and not (self.nur_offene.get() and heute_fehlgeschlagen(p))

        def _lade_liste(self):
            """Baum neu aufbauen (Abschnitte mit Zahlen ungeprüft / gesamt, ✗ heute; Prüfpunkte als Kinder
            mit Status-Symbol); aufgeklappte Abschnitte und die Auswahl bleiben erhalten."""
            self.text = lade()
            self.abschnitte = parse_checkliste(self.text)
            offen_iids = {iid for iid in self.baum.get_children() if self.baum.item(iid, "open")}
            auswahl = self.baum.selection()
            self.baum.delete(*self.baum.get_children())
            for i, a in enumerate(self.abschnitte):
                offen = sum(1 for p in a["punkte"] if self._ungeprueft(p))
                heute = sum(1 for p in a["punkte"] if not p["erledigt"] and heute_fehlgeschlagen(p))
                zusatz = f" ✗{heute}" if heute else ""
                # Zahlen vorn, damit sie bei langen Abschnittstiteln nicht abgeschnitten werden
                iid = f"a{i}"
                self.baum.insert("", tk.END, iid=iid, text=f"[{offen}/{len(a['punkte'])}{zusatz}]  {a['titel']}",
                                 open=iid in offen_iids)
                for j, p in enumerate(a["punkte"]):
                    if self.nur_offene.get() and not self._ungeprueft(p):
                        continue
                    if p["erledigt"]:
                        symbol, tag = "✓", "fertig"
                    elif heute_fehlgeschlagen(p):
                        symbol, tag = "✗", "fehl"
                    else:
                        symbol, tag = "○", ""
                    arten = {art for art, _, _ in p["notizen"]}
                    zusatz = "".join(f" {art}" for art in (NOTIZ, IDEE) if art in arten)
                    self.baum.insert(iid, tk.END, iid=f"a{i}p{j}", tags=(tag,),
                                     text=f"{symbol} {p['id']} {p['titel'] or '(ohne Titel)'}{zusatz}".replace("  ", " "))
            if auswahl:
                # Punkt vom Filter ausgeblendet -> Auswahl fällt auf seinen Abschnitt zurück
                iid = auswahl[0] if self.baum.exists(auswahl[0]) else auswahl[0].split("p")[0]
                if self.baum.exists(iid):
                    self.baum.selection_set(iid)

        def _filter_geaendert(self):
            self._lade_liste()
            self._baum_gewaehlt(erzwinge=True)

        def _waehle_abschnitt(self, nummer):
            for i, a in enumerate(self.abschnitte):
                if a["titel"].split(".")[0].strip() == str(nummer):
                    self.baum.item(f"a{i}", open=True)
                    self.baum.selection_set(f"a{i}")
                    self.baum.see(f"a{i}")
                    self._baum_gewaehlt(erzwinge=True)
                    return

        def _baum_gewaehlt(self, erzwinge=False):
            """Klick im Baum: Abschnitt -> erster (ungeprüfter) Punkt, Prüfpunkt -> genau dieser.
            Die Auswahl, die _zeige selbst setzt, löst nichts aus (gleicher Knoten wie angezeigt)."""
            auswahl = self.baum.selection()
            if not auswahl or (auswahl[0] == self._angezeigt_iid and not erzwinge):
                return
            m = re.match(r"a(\d+)(?:p(\d+))?$", auswahl[0])
            if not m:
                return
            a = self.abschnitte[int(m.group(1))]
            # "nur offene": weder abgehakt noch HEUTE schon als fehlgeschlagen notiert - nach
            # einem Neustart des Wizards geht es so direkt beim nächsten ungeprüften Punkt weiter
            self.punkte = [(a, p) for p in a["punkte"] if not self.nur_offene.get() or self._ungeprueft(p)]
            self.position = 0
            if m.group(2):
                ziel = a["punkte"][int(m.group(2))]
                self.position = next((k for k, (_, q) in enumerate(self.punkte) if q is ziel), 0)
            # Nutzerfund 17.09.2026: ein Klick aufs [-] wählt in ttk ERST den Abschnitt aus und klappt ihn
            # DANN zu - führte _zeige hier die Auswahl nach (Kind wählen, Abschnitt öffnen), war er sofort
            # wieder offen. Bei einem Klick im Baum bleibt der Baum deshalb, wie der Nutzer ihn gesetzt hat.
            self._klick_im_baum = True
            try:
                self._zeige()
            finally:
                self._klick_im_baum = False

        def _baum_kontextmenue(self, event):
            """Rechtsklick auf einen Abschnitt: Haken zurücksetzen (Release-Check erneut durchlaufen)."""
            iid = self.baum.identify_row(event.y)
            m = re.match(r"a(\d+)$", iid or "")
            if not m:
                return
            a = self.abschnitte[int(m.group(1))]
            menue = tk.Menu(self, tearoff=0)
            menue.add_command(label=f"Alle Haken in „{a['titel']}“ zurücksetzen…",
                              command=lambda: self._haken_zuruecksetzen(a))
            menue.tk_popup(event.x_root, event.y_root)

        def _haken_zuruecksetzen(self, a):
            abgehakt = sum(1 for p in a["punkte"] if p["erledigt"])
            if not abgehakt:
                messagebox.showinfo("Haken zurücksetzen", "In diesem Abschnitt ist nichts abgehakt.", parent=self)
                return
            if not messagebox.askyesno("Haken zurücksetzen",
                                       f"{abgehakt} abgehakte Prüfpunkte in „{a['titel']}“ wieder auf offen setzen?\n\n"
                                       "Befunde, Notizen und Ideen bleiben stehen.", parent=self):
                return
            try:
                text, _ = haken_zuruecksetzen(lade(), a["zeile"])
            except ValueError as e:
                messagebox.showerror("Checkliste verändert", f"{e}\n\nBitte Wizard neu starten.", parent=self)
                return
            speichere(text)
            i = self.abschnitte.index(a)
            self._lade_liste()
            self.baum.item(f"a{i}", open=True)
            self.baum.selection_set(f"a{i}")
            self._baum_gewaehlt(erzwinge=True)

        def _baum_markieren(self, a, p):
            """Baum-Auswahl dem rechts gezeigten Punkt nachführen (Pfeile, Überspringen, nach Ergebnis)."""
            self._angezeigt_iid = None
            if self._klick_im_baum:
                auswahl = self.baum.selection()
                self._angezeigt_iid = auswahl[0] if auswahl else None
                return
            if a is None or p is None or a not in self.abschnitte:
                return
            iid = f"a{self.abschnitte.index(a)}p{a['punkte'].index(p)}"
            if self.baum.exists(iid):
                self._angezeigt_iid = iid
                self.baum.item(f"a{self.abschnitte.index(a)}", open=True)
                self.baum.selection_set(iid)
                self.baum.see(iid)

        def _aktuell(self):
            """(Abschnitt, Prüfpunkt) an der aktuellen Position; hinter dem Ende (Abschnitt, None)."""
            if 0 <= self.position < len(self.punkte):
                return self.punkte[self.position]
            # Nutzerfund 11.09.2026: "Überspringen" hinter dem letzten Punkt lieferte (None, None)
            # und _zeige griff auf a["titel"] zu -> TypeError. Der Abschnitt bleibt bekannt.
            return (self.punkte[0][0] if self.punkte else None), None

        def _zeige(self):
            a, p = self._aktuell()
            self.txt_notiz.delete("1.0", tk.END)
            self.ent_idee.delete(0, tk.END)
            self.lbl_befunde.pack_forget()
            self.lbl_notizen.pack_forget()
            self._baum_markieren(a, p)
            if p is None:
                self.lbl_kopf.configure(text=(f"{a['titel']}: alle Prüfpunkte durch." if self.punkte
                                              else "Alle Prüfpunkte dieses Abschnitts sind abgehakt oder heute als ✗ "
                                                   "notiert - Haken bei 'nur ungeprüfte zeigen' weg, um sie zu sehen."))
                self.lbl_titel.configure(text="")
                for feld, (rahmen, inhalt) in self.felder.items():
                    rahmen.pack_forget()
                self._fragen_fuellen([])
                return
            self.lbl_kopf.configure(text=f"{a['titel']}  —  Prüfpunkt {self.position + 1} von {len(self.punkte)}"
                                         + ("   [bereits abgehakt]" if p["erledigt"] else ""))
            self.lbl_titel.configure(text=(f"{p['id']}  " if p["id"] else "") + (p["titel"] or "(ohne Titel)"))
            for feld, (rahmen, inhalt) in self.felder.items():
                wert = p[feld.lower()]
                if feld == "Klicks":
                    schritte = [s.strip() for s in wert.split("→") if s.strip()] if wert else []
                    inhalt.configure(state="normal", height=max(1, min(len(schritte), KLICKS_ZEILEN)))
                    inhalt.delete("1.0", tk.END)
                    inhalt.insert(tk.END, "\n".join(f"{i + 1}. {s}" for i, s in enumerate(schritte)))
                    inhalt.configure(state="disabled")
                else:
                    if feld == "Datei" and wert and TESTORDNER:
                        wert = wert + "\n(relativ zum Testordner " + TESTORDNER + ")"
                    inhalt.configure(text=wert)
                rahmen.pack_forget()
                if wert:
                    rahmen.pack(fill=tk.X, pady=2, before=self.fragen_rahmen)
            self._fragen_fuellen(frage_liste(p["text"]))
            # Ergebnis widerspiegeln (Nutzerwunsch 17.09.2026): abgehakt = alle Haken; sonst Haken und
            # Notizen aus der neuesten Fehlnotiz, wenn sie im Tabellen-Format geschrieben wurde
            if p["erledigt"]:
                for i in range(len(self.fragen_zeilen)):
                    self.fragen_zeilen[i]["var"].set(True)
                    self._zeile_faerben(i)
            elif p["fehlnotizen"]:
                gelesen = fehlnotiz_parsen(p["fehlnotizen"][0][1], len(self.fragen_zeilen))  # [0] = neueste
                if gelesen:
                    for i, (ok, notiz) in enumerate(gelesen[0]):
                        self.fragen_zeilen[i]["var"].set(ok)
                        self.fragen_zeilen[i]["notiz"].insert(0, notiz)
                        self._zeile_faerben(i)
                    self.txt_notiz.insert("1.0", gelesen[1])
            if p["fehlnotizen"]:
                self.lbl_befunde.configure(text="\n".join(f"Früherer Befund {d}: {n}" for d, n in p["fehlnotizen"]))
                self.lbl_befunde.pack(fill=tk.X, after=self.fragen_rahmen)
            if p["notizen"]:
                self.lbl_notizen.configure(text="\n".join(f"{art} {d}: {n}" for art, d, n in p["notizen"]))
                self.lbl_notizen.pack(fill=tk.X, after=self.lbl_befunde if p["fehlnotizen"] else self.fragen_rahmen)

        # ---------- Aktionen
        def _springe(self, schritt):
            if not self.punkte:
                return
            self.position = max(0, min(len(self.punkte), self.position + schritt))
            self._zeige()

        def _ergebnis(self, bestanden):
            a, p = self._aktuell()
            if p is None:
                return
            allgemein = self.txt_notiz.get("1.0", tk.END).strip()
            zeilen = [(z["var"].get(), z["notiz"].get()) for z in self.fragen_zeilen]
            idee = self.ent_idee.get().strip()
            if bestanden:
                # Notizen gehen nicht mehr verloren (Nutzerwunsch 25.10.2026): sie werden als 📝 gespeichert
                notiz = notiz_text([n for _, n in zeilen], allgemein)
            else:
                if not allgemein and not any(n.strip() for _, n in zeilen):
                    messagebox.showwarning("Notiz fehlt", "Bitte kurz notieren, was nicht geklappt hat - in der "
                                           "Notiz-Spalte der betroffenen Frage oder unten allgemein.", parent=self)
                    return
                notiz = fehlnotiz_text(zeilen, allgemein)
            text = lade()  # frisch lesen - der Nutzer könnte die Datei nebenbei im Editor geändert haben
            try:
                text = markiere(text, p["zeile"], bestanden, "" if bestanden else notiz, kennung=p["id"])
                if bestanden:
                    text = fuege_notiz_ein(text, p["zeile"], notiz, NOTIZ, kennung=p["id"])
                text = fuege_notiz_ein(text, p["zeile"], idee, IDEE, kennung=p["id"])
            except ValueError as e:
                messagebox.showerror("Checkliste verändert", f"{e}\n\nBitte Wizard neu starten.", parent=self)
                return
            speichere(text)
            self.ergebnisse.append((a["titel"], f"{p['id']} {p['titel']}".strip(), bestanden, notiz, idee))
            self._neu_einlesen(a)
            self.position += 1
            self._zeige()

        def _nur_notiz(self):
            """Notiz und/oder Idee speichern, ohne das Ergebnis zu ändern; der Punkt bleibt angezeigt,
            gesetzte Haken bleiben stehen (Nutzerwunsch 25.10.2026)."""
            a, p = self._aktuell()
            if p is None:
                return
            haken = [z["var"].get() for z in self.fragen_zeilen]
            notiz = notiz_text([z["notiz"].get() for z in self.fragen_zeilen], self.txt_notiz.get("1.0", tk.END))
            idee = self.ent_idee.get().strip()
            if not notiz and not idee:
                messagebox.showinfo("Nichts zu speichern", "Notiz-Spalte, Notizfeld und Ideenfeld sind leer.", parent=self)
                return
            text = lade()
            try:
                text = fuege_notiz_ein(text, p["zeile"], notiz, NOTIZ, kennung=p["id"])
                text = fuege_notiz_ein(text, p["zeile"], idee, IDEE, kennung=p["id"])
            except ValueError as e:
                messagebox.showerror("Checkliste verändert", f"{e}\n\nBitte Wizard neu starten.", parent=self)
                return
            speichere(text)
            self.ergebnisse.append((a["titel"], f"{p['id']} {p['titel']}".strip(), None, notiz, idee))
            self._neu_einlesen(a)
            self._zeige()
            for i, ok in enumerate(haken[:len(self.fragen_zeilen)]):
                self.fragen_zeilen[i]["var"].set(ok)
                self._zeile_faerben(i)

        def _neu_einlesen(self, a):
            """Nach dem Schreiben neu parsen (Zeilennummern haben sich verschoben), Punktauswahl halten."""
            aktuelle_titel = [q["id"] or q["titel"] for _, q in self.punkte]
            i_abschnitt = self.abschnitte.index(a)
            self._lade_liste()
            a_neu = self.abschnitte[i_abschnitt] if i_abschnitt < len(self.abschnitte) else None
            self.punkte = [(a_neu, q) for q in (a_neu["punkte"] if a_neu else [])
                           if (q["id"] or q["titel"]) in aktuelle_titel]

        def _oeffne(self, pfad):
            try:
                os.startfile(pfad)
            except OSError as e:
                messagebox.showerror("Öffnen", str(e), parent=self)

        def _datei_pfad(self):
            _, p = self._aktuell()
            if p is None or not p["datei"]:
                return None
            return os.path.join(TESTORDNER or PROJEKT, p["datei"].split("(")[0].strip())

        def _datei_ordner_oeffnen(self):
            pfad = self._datei_pfad()
            if not pfad:
                return
            if os.path.exists(pfad):
                subprocess.Popen(["explorer", "/select,", pfad])
            else:
                ordner = os.path.dirname(pfad)
                self._oeffne(ordner if os.path.isdir(ordner) else (TESTORDNER or PROJEKT))

        def _datei_pfad_kopieren(self):
            pfad = self._datei_pfad()
            if pfad:
                self.clipboard_clear()
                self.clipboard_append(pfad)

        def _app_starten(self):
            """Startet das konfigurierte Kommando (app_start) im Projektordner als eigenen Prozess.
            'python' bzw. 'py' wird durch den laufenden Interpreter ersetzt - im Zweifel die venv."""
            befehl = list(APP_START)
            if befehl and befehl[0] in ("python", "python3", "py"):
                befehl[0] = sys.executable
            try:
                subprocess.Popen(befehl, cwd=PROJEKT)
            except OSError as e:
                messagebox.showerror("App starten", f"{' '.join(befehl)}\n\n{e}", parent=self)

        def _zusammenfassung(self):
            if not self.ergebnisse:
                messagebox.showinfo("Zusammenfassung", "In dieser Sitzung noch nichts geprüft.", parent=self)
                return
            zeilen = []
            for a, t, ok, n, idee in self.ergebnisse:
                symbol = NOTIZ if ok is None else ("✓" if ok else "✗")
                zeilen.append(f"{symbol} {a} / {t}" + (f" — {n}" if n else ""))
                if idee:
                    zeilen.append(f"    {IDEE} {idee}")
            geprueft = sum(1 for e in self.ergebnisse if e[2] is not None)
            fehl = sum(1 for e in self.ergebnisse if e[2] is False)
            ideen = sum(1 for e in self.ergebnisse if e[4])
            text = (f"{geprueft} geprüft, {fehl} fehlgeschlagen, {ideen} Idee(n):\n\n" + "\n".join(zeilen))
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo("Zusammenfassung (in der Zwischenablage)", text, parent=self)

    wizard = Wizard()
    if nach_start:
        wizard.after(300, lambda: nach_start(wizard))  # Rauchtest-Haken: Bedienung per Skript
    if screenshot:
        # Entwickler-Hilfe: Fenster nach dem Aufbau abfotografieren und beenden (Rauchtest)
        def knipsen():
            try:
                from PIL import ImageGrab
                x, y = wizard.winfo_rootx(), wizard.winfo_rooty()
                ImageGrab.grab(bbox=(x - 8, y - 32, x + wizard.winfo_width() + 8,
                                     y + wizard.winfo_height() + 8)).save(screenshot)
            finally:
                wizard.destroy()
        wizard.after(900, knipsen)
    wizard.mainloop()


def _argument(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else None


if __name__ == "__main__":
    lade_konfiguration(_argument("--projekt"), _argument("--checkliste"))
    if not os.path.isfile(CHECKLISTE):
        sys.exit(f"Checkliste nicht gefunden: {CHECKLISTE}\n"
                 f"Mit --projekt <Ordner> oder --checkliste <Datei> den richtigen Ort angeben,\n"
                 f"oder eine {KONFIG_DATEI} neben der Checkliste anlegen (siehe README).")
    _starte_gui(_argument("--abschnitt"), screenshot=_argument("--screenshot"))
