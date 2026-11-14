"""
Mails importieren - auf Abruf (KONZEPT_MAIL_AUF_ABRUF.md, Etappe 6 „Zurückrudern“, seit 08.11.2026; davor
KONZEPT_MAIL_IMPORT.md mit KI-Einstufung und Absender-Regeln).

Eine Seite in drei Schritten: 1. Woher? Ein gefundenes Mail-Programm oder von Hand .pst/.ost, mbox, .eml oder ein Ordner
mit beliebig vielen davon (F7, direkt gelesen), samt eigener Adressen, dann einlesen. 2. Suchen: Suchzeile wie im Hauptfenster (mehrere Wörter = UND, "…" genau,
leichte Unschärfe gegen Tippfehler, eine Jahreszahl gilt als Zeitraum), Filter, Trefferliste mit Häkchen und
Textvorschau; Häkchen bleiben über mehrere Suchen erhalten. 3. Übernehmen: nur die angehakten Mails, als Mail-PDFs in
den Posteingang (die Vollautomatik legt sie ab wie Scans) oder direkt in einen gewählten Ordner, ohne KI (F6).

Die Suche nach Mail-Programmen läuft beim Öffnen des Fensters (E14), kopiert wird erst mit „Einlesen“: Ein Mail-Programm
wird nie direkt gelesen, nur eine geprüfte Kopie (mail_quellen.py). Sie enthält private Mails und wird beim Schließen
des Fensters gelöscht, auf Rückfrage mit vorgewähltem Ja (E10). Reste eines abgebrochenen Laufs meldet das Fenster beim Öffnen.

Die Logik steckt in mail_import.py und mail_quellen.py (GUI-frei, getestet); hier nur Oberfläche und Threads. Die Quelle wird nie
verändert; Suchtext und Textanfang der Mails liegen nur im Arbeitsspeicher, ins Protokoll gehen nur Zahlen (Datenschutz).
Die Vollautomatik pausiert, solange der Import läuft.
"""

import functools
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import tkinter.messagebox as mb
from tkinter import filedialog, ttk

import ablage_gedaechtnis
import auto_pilot
import mail_import
import mail_lesen
import mail_pst
import mail_quellen
import suchsyntax
import vollautomatik_fenster
from tools.base_tool import BaseTool, ToolContext
from ui_utils import Tooltip, UIUtils

IMPORTIERT = "importiert"
VON_HAND = "Datei oder Ordner von Hand wählen"
KOPIE_MELDEN_ALLE = 16 * 1024 * 1024          # Bytes zwischen zwei Fortschrittsmeldungen beim Kopieren
MAX_ZEILEN = 5000                             # mehr Zeilen machen die Liste träge; die Zahl der Treffer stimmt trotzdem
HAKEN, OHNE_HAKEN = "☑", "☐"
RICHTUNGEN = ((None, "alle"), ("ein", "eingegangen"), ("aus", "gesendet"))
REITER = ("1. Woher?", "2. Suchen", "3. Übernehmen")
ABHOLEN_SEKUNDEN = 0.05        # je Abholung aus dem Postfach, dann ist der Tk-Ereignis-Loop wieder dran (FALLSTRICKE #125)
TEXT_BUENDEL_SEKUNDEN = 0.25   # Phase 2 schickt ihre Ergebnisse gebündelt, etwa viermal je Sekunde
BALKEN_STIL = "Mail.Horizontal.TProgressbar"


VORNE_RAND = 30               # Zeilen über und unter dem sichtbaren Teil, die Phase 2 auch zuerst liest (S2)
NACHZIEHEN_SEKUNDEN = 2        # so oft prüft eine laufende Textsuche, ob neu gelesene Texte Treffer bringen (S2)
TEXT_WECHSEL_SEKUNDEN = 0.001  # Wechseltakt der Rechenerlaubnis während Phase 2 (Python-Vorgabe 5 ms, FALLSTRICKE #126)


def text_hinweis(n, gesamt):
    """Hinweis hinter der Trefferzahl, solange Phase 2 läuft - wird zweimal je Sekunde neu geschrieben."""
    return f"Erst {100 * n // max(gesamt, 1)} % der Mailtexte sind durchsucht - weitere Treffer können dazukommen."


def warte_auf_vorrang(vorrang, halt):
    """Im Rechen-Thread je Mail: Solange das Fenster Vorrang hat, schlafen statt rechnen. :return: True = aufhören
    (FALLSTRICKE #126)"""
    while vorrang.is_set() and not halt():
        time.sleep(0.005)
    return halt()


def mit_vorrang(methode):
    """Viele Tk-Aufrufe am Stück (Trefferliste neu aufbauen, alle anhaken): Phase 2 wartet so lange. Jeder Tk-Aufruf
    gibt die Rechenerlaubnis (GIL) ab und bekommt sie gegen einen rechnenden Thread erst nach bis zu 5 ms zurück -
    5000 Zeilen dauerten so 26 s statt 0,06 s (FALLSTRICKE #126)."""
    @functools.wraps(methode)
    def huelle(self, *a, **k):
        self._vorrang_tiefe += 1
        self._vorrang.set()
        try:
            return methode(self, *a, **k)
        finally:
            self._vorrang_tiefe -= 1
            if not self._vorrang_tiefe:
                self._vorrang.clear()
    return huelle


def fortschritt_text(n, gesamt, sekunden):
    """„101 von 1702, noch ca. 16 min“; n = die Mail, die gerade dran ist. Die Restzeit erst nach einigen Mails."""
    text = f"{n} von {gesamt}"
    if n <= 10 or not sekunden:
        return text
    rest = sekunden / (n - 1) * (gesamt - n + 1)
    return f"{text}, noch ca. " + (f"{round(rest / 60)} min" if rest >= 60 else f"{max(1, int(rest))} s")


def zeit_kurz(sekunden):
    """„31 s“ oder „16 min“."""
    return f"{round(sekunden / 60)} min" if sekunden >= 60 else f"{max(1, int(sekunden))} s"


def stand_text(n, anteil, sekunden, gesamt=None, datei=""):
    """Fortschritt einer Phase des Einlesens (Peter 09.11.2026): „12400 Mails, Datei 2 von 5, noch ca. 40 s“ bzw.
    „3000 von 36000, noch ca. 5 min“. Die Restzeit erst, wenn sie sich schätzen lässt (ab 2 % und 2 s)."""
    teile = [f"{n} Mails" if gesamt is None else f"{n} von {gesamt}"]
    if datei:
        teile.append(datei)
    if 0.02 <= anteil < 1 and sekunden >= 2:
        teile.append("noch ca. " + zeit_kurz(sekunden * (1 - anteil) / anteil))
    return ", ".join(teile)


def fehlende_text(dateien):
    """Meldung, wenn Dateien eines Ordners nicht lesbar waren (F7): Die übrigen sind trotzdem eingelesen."""
    liste = "\n".join(f"• {d}" for d in dateien[:10]) + (f"\n… und {len(dateien) - 10} weitere" if len(dateien) > 10 else "")
    return (f"{len(dateien)} Datei(en) ließen sich nicht lesen und fehlen in der Liste:\n{liste}\n\nDie übrigen Mails "
            "sind eingelesen. Ist eine .pst noch in Outlook geöffnet, Outlook schließen und neu einlesen.")


def eigene_frage_text(funde, zeigen=12):
    """Rückfrage nach dem Einlesen: Absender aus den Ordnern „Gesendet“ als eigene Adressen übernehmen?"""
    zeilen = [f"• {a} ({n} Mails)" for a, n in funde[:zeigen]]
    if len(funde) > zeigen:
        zeilen.append(f"… und {len(funde) - zeigen} weitere")
    return ("In den gesendeten Mails stehen diese Absender, die noch nicht als eigene Adressen eingetragen sind:\n\n"
            + "\n".join(zeilen) + "\n\nAls eigene Adressen übernehmen? Mails von dort gelten dann als gesendet.\n"
            "(Nein: KID fragt nach diesen Adressen nicht wieder.)")


def unlesbar_text(pfad):
    """Eine einzeln gewählte Mail-Datei ließ sich nicht öffnen (T20.26): verständlich statt der Rohmeldung von libpff."""
    return (f"„{os.path.basename(pfad.rstrip(os.sep)) or pfad}“ ließ sich nicht lesen. Ist die Datei gerade in Outlook "
            "geöffnet, Outlook schließen und erneut einlesen. Sonst ist sie beschädigt oder keine Mail-Datei.")


def startordner(text):
    """Wo „Datei…“/„Ordner…“ beginnen: beim Pfad im Feld, auch wenn die Datei dort nicht mehr liegt; sonst None."""
    pfad = (text or "").strip()
    if os.path.isdir(pfad):
        return pfad
    ordner = os.path.dirname(pfad)
    return ordner if ordner and os.path.isdir(ordner) else None


_ADRESSE = re.compile(r"[^\s<>\"']*@[^\s<>\"']+")


def eigene_aus_text(text):
    """Adressen aus dem Feld, mit Komma, Semikolon oder Zeilenumbruch getrennt; aus „Name <a@b.de>“ nur die Adresse,
    „@domain.de“ bleibt (ganze Domain)."""
    funde = (_ADRESSE.search(t) for t in (text or "").replace(";", ",").replace("\n", ",").split(","))
    return list(dict.fromkeys(f.group(0).lower() for f in funde if f))


def zeitraum_aus_feldern(ab_text, bis_text):
    """(ab, bis) aus den Feldern, wie die Datumsfelder der Dokumentsuche: „2024“, „03.2024“, „15.03.2024“, leer = offen.
    ValueError, wenn ein ausgefülltes Feld nicht zu lesen ist."""
    ab, bis = suchsyntax.datum_grenze(ab_text), suchsyntax.datum_grenze(bis_text, ende=True)
    if (ab_text.strip() and ab is None) or (bis_text.strip() and bis is None):
        raise ValueError(ab_text if ab is None else bis_text)
    return ab, bis


def treffer_text(ergebnis, angezeigt, gesamt=None):
    """Die Zeile über der Trefferliste: Zahl, Zeitraum aus dem Suchtext, schon Importiertes, ähnliche Schreibweisen.
    `gesamt`: Zahl aller eingelesenen Mails - „18693 Treffer unter 20000 Mails“ zeigt, dass gesucht wurde, auch wenn
    sich die Liste kaum ändert (Peter 09.11.2026)."""
    n = len(ergebnis.treffer)
    newsletter = getattr(ergebnis, "newsletter", 0)
    if not n:
        text = "Kein Treffer."
        if ergebnis.jahre:
            text += f" Der Zeitraum {jahre_text(ergebnis.jahre)} kommt aus dem Suchtext."
        if newsletter:
            text += f" {newsletter} Newsletter sind ausgeblendet."
        return text
    text = "1 Treffer" if n == 1 else f"{n} Treffer"
    if gesamt:
        text += f" unter {gesamt} Mails"
    if ergebnis.jahre:
        text += f" (Zeitraum {jahre_text(ergebnis.jahre)} aus dem Suchtext)"
    if ergebnis.schon_drin:
        text += f", {ergebnis.schon_drin} schon in der Sammlung"
    if newsletter:
        text += f", {newsletter} Newsletter ausgeblendet"
    if angezeigt < n:
        text += f", die neuesten {angezeigt} stehen in der Liste"
    if ergebnis.varianten:
        text += ". Auch gefunden als: " + ", ".join(f"{v} ({z})" for v, z in ergebnis.varianten.most_common(6))
    return text


def jahre_text(jahre):
    return str(jahre[0]) if jahre[0] == jahre[1] else f"{jahre[0]}-{jahre[1]}"


def kennzahlen(bestand):
    """Kurzer Text mit den Zahlen des Einlesens (nur Zahlen)."""
    z = bestand.zahlen
    teile = [f"{z['gesamt']} Mails gelesen"]
    for schluessel, text in (("ein", "eingegangen"), ("aus", "gesendet"), ("doppelt", "doppelt"),
                             ("schon importiert", "schon in der Sammlung"), ("unlesbar", "unlesbar"),
                             (mail_import.DATEI_NICHT_LESBAR, "Datei(en) nicht lesbar"),
                             (mail_lesen.GELOESCHT, mail_lesen.GELOESCHT + " (übergangen)"),
                             (mail_lesen.TEILWEISE, mail_lesen.TEILWEISE),
                             (mail_lesen.ZAHL_FROM_IM_TEXT, "„From“-Zeilen im Mailtext (keine neue Mail)")):
        if z[schluessel]:
            teile.append(f"{z[schluessel]} {text}")
    vorfilter = sum(v for k, v in z.items() if k.startswith("Vorfilter: "))
    if vorfilter:
        teile.append(f"{vorfilter} ausgeblendet ("
                     + ", ".join(f"{k[len('Vorfilter: '):]} {v}" for k, v in sorted(z.items()) if k.startswith("Vorfilter: "))
                     + ")")
    return ", ".join(teile) + ("  - ABGEBROCHEN" if z["abgebrochen"] else "")


SEKUNDEN_JE_DOKUMENT = 15      # Vollautomatik, grobe Angabe wie im Fenster „Begleitet erfassen“


def dauer_text(sekunden):
    """„etwa 40 Minuten“, ab anderthalb Stunden in Stunden."""
    minuten = sekunden / 60
    if minuten < 1.5:
        return "etwa eine Minute"
    return f"etwa {round(minuten)} Minuten" if minuten < 90 else f"etwa {round(minuten / 60)} Stunden"


def uebernahme_text(v, ordner=None, anhaenge=True):
    """Was „Übernehmen“ bewirkt (mail_import.vorschau): Im Vortest wusste niemand, wo die Mails landen. Und erst nach dem
    Import zu sehen, wie viele Ordner entstehen, hat Peter beim Betatest erschlagen.
    :param ordner: gewähltes Ziel (relativ zur Sammlung) oder None = Posteingang mit Vollautomatik (Konzept F6)
    :param anhaenge: Haken „PDF-Anhänge als eigene Dokumente“"""
    if not v["mails"]:
        return "Noch nichts angehakt. Suchen, dann die gewünschten Mails anhaken."
    n_anh = v["anhaenge"] if anhaenge else 0
    mails = "1 Mail" if v["mails"] == 1 else f"{v['mails']} Mails"
    anh = "" if not n_anh else " und 1 PDF-Anhang" if n_anh == 1 else f" und {n_anh} PDF-Anhänge"
    kommen = "kommt" if v["mails"] == 1 and not n_anh else "kommen"
    rest = ""
    if v["anhaenge"] and not anhaenge:
        rest = (" Der PDF-Anhang bleibt" if v["anhaenge"] == 1 else f" Die {v['anhaenge']} PDF-Anhänge bleiben") + \
            " nur in der Original-Mail im PDF."
    if ordner:
        return (f"{mails}{anh} {kommen} direkt in den Ordner „{ordner}“, ohne KI: Titel ist der Betreff, Datum und "
                f"Absender stammen aus der Mail.{rest}")
    # Worte aus der Gegenprobe: „Sammelablage“, „Vollautomatik legt ab“ und „Posteingang“ hielt jeder für etwas anderes
    teile = [f"{mails}{anh} {kommen} als PDF in die Sammlung.{rest}"]
    if v["neue_ordner"]:
        teile.append("Dafür entsteht etwa 1 neuer Ordner." if v["neue_ordner"] == 1
                     else f"Dafür entstehen etwa {v['neue_ordner']} neue Ordner.")
    if v["einzelne"]:
        teile.append("1 einzelne Mail kommt in den Ordner „Einzelne Mails“." if v["einzelne"] == 1
                     else f"{v['einzelne']} einzelne Mails kommen gemeinsam in den Ordner „Einzelne Mails“.")
    dauer = dauer_text((v["mails"] + n_anh) * SEKUNDEN_JE_DOKUMENT)
    teile.append(f"KID sortiert sie danach im Hintergrund ein, das dauert {dauer}. Den Stand siehst du oben rechts neben „Hilfe“.")
    return " ".join(teile)


def bekannt_pruefer(ordnerliste, gedaechtnis):
    """bekannt(name, adresse): hat das Gegenüber schon einen Ordner (Namensregeln der Vollautomatik) oder steht es im
    Ablage-Gedächtnis? Ohne Namen zählt die Domain („musterbank“ aus info@musterbank.example), nie die eines
    Mail-Anbieters. Je Gegenüber nur einmal gerechnet. Dient der Schätzung „etwa N neue Ordner“."""
    gemerkt = {}

    def bekannt(name, adresse):
        if (name, adresse) not in gemerkt:
            gemerkt[(name, adresse)] = _bekannt(name, adresse)
        return gemerkt[(name, adresse)]

    def _bekannt(name, adresse):
        kandidaten = [name] if name else []
        domain = (adresse or "").rpartition("@")[2].split(".")
        if not name and len(domain) >= 2 and domain[-2] not in mail_import.ANBIETER:
            kandidaten.append(domain[-2])
        for k in kandidaten:
            if gedaechtnis is not None and gedaechtnis.frage(k):
                return True
            if len(k) >= 4 and auto_pilot.finde_passenden_ordner(k, ordnerliste):
                return True
        return False
    return bekannt


class MailImportFenster(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.withdraw()                              # erst aufbauen, dann zeigen (FALLSTRICKE #90)
        UIUtils.werkzeugfenster(self, app.root)      # über KID, nicht modal
        self.app = app
        self.master_folder = app.master_folder
        self.title("Mails importieren")
        self.journal = mail_import.Journal(self.master_folder)
        self.bestand = None
        self.bekannt = None
        self.ergebnis = None                         # letztes mail_import.Suchergebnis
        self.angehakt = set()                        # Schlüssel; bleiben über mehrere Suchen erhalten (Konzept F9)
        self._eintrag = {}                           # Schlüssel → Eintrag des Bestands
        self.programme = []
        self.haken = []                              # [(mail_quellen.Quelle, BooleanVar)] des gewählten Programms
        self.kopie_ziel = self.journal.zuletzt.get("kopie") or mail_quellen.kopie_ordner()
        self._kopie_gemeldet = 0
        self._stopp = threading.Event()              # Fenster zu
        self._abbruch = threading.Event()            # laufende Arbeit abbrechen
        self._laeuft = False
        self._postfach = queue.Queue()
        self._abhol_id = None
        self._dienst = None
        self._vorrang = threading.Event()            # gesetzt = das Fenster arbeitet viel, Phase 2 wartet (mit_vorrang)
        self._vorrang_tiefe = 0
        self._treffer_basis = ""
        self._vorne = []                             # Einträge, die Phase 2 zuerst liest (die sichtbaren, S2)
        self._vormerken_id = None
        self._nachgezogen = 0.0                      # wann die Textsuche zuletzt nachgezogen wurde
        self._phase1 = None                          # Einlesen in zwei Phasen: {"lage", "beginn", "ende"}
        self._phase2 = None                          # dazu "halt" (Event) und "thread"
        self._stand_id = None
        self._ordner = auto_pilot.sammle_ordnerliste(self.master_folder)   # Ziele für „direkt in den Ordner“ (F6)
        self._baue()
        self.protocol("WM_DELETE_WINDOW", self._schliessen)
        self.update_idletasks()
        UIUtils.position_near_mouse(self, UIUtils.px(self, 1000), UIUtils.px(self, 720))
        self._summe()
        vollautomatik_fenster.zuruecktreten(app, True)
        self.deiconify()
        self._abholen()
        self._zeige_stand()
        self._suche_programme()

    # ---------------------------------------------------------------- Aufbau
    def _baue(self):
        """Drei Schritte als Reiter (Peter 09.11.2026 nach dem Betatest: zu viel Platz für die Einstellungen,
        seine Wahl statt Einklappen), je Schritt ein Hauptknopf (E15). Der jeweils nächste ist blau. „Suchen“ und
        „Übernehmen“ gehen erst nach dem Einlesen auf. Kennzahlen und Fortschritt stehen unter den Reitern, damit
        Meldungen in jedem Schritt zu sehen sind."""
        rand = UIUtils.px(self, 10)
        # Im Stil „clam“ sind Balken und Rinne fast gleich grau: ein voller Balken sah leer aus (Peter 09.11.2026)
        ttk.Style(self).configure(BALKEN_STIL, background="#0078D7", lightcolor="#0078D7", darkcolor="#0078D7")
        inhalt = ttk.Frame(self)
        inhalt.pack(fill=tk.BOTH, expand=True)

        unten = ttk.Frame(inhalt)                    # Knopfleisten VOR dem dehnbaren Inhalt mit side=BOTTOM
        unten.pack(side=tk.BOTTOM, fill=tk.X, padx=rand, pady=(6, rand))
        ttk.Button(unten, text="Schließen", command=self._schliessen).pack(side=tk.RIGHT)
        self.btn_abbrechen = ttk.Button(unten, text="Abbrechen", command=self._abbrechen, state=tk.DISABLED)
        self.btn_abbrechen.pack(side=tk.RIGHT, padx=6)
        self.fortschritt = ttk.Progressbar(unten, length=UIUtils.px(self, 220), mode="determinate", style=BALKEN_STIL)
        self.fortschritt.pack(side=tk.LEFT)
        self.lbl_fortschritt = ttk.Label(unten)
        self.lbl_fortschritt.pack(side=tk.LEFT, padx=6)
        self.lbl_zahlen = ttk.Label(inhalt, wraplength=UIUtils.px(self, 940), justify=tk.LEFT)
        self.lbl_zahlen.pack(side=tk.BOTTOM, fill=tk.X, padx=rand + UIUtils.px(self, 4), pady=(4, 0))

        self.reiter = ttk.Notebook(inhalt)
        self.reiter.pack(fill=tk.BOTH, expand=True, padx=rand, pady=(rand, 0))
        seiten = []
        for titel in REITER:
            seite = ttk.Frame(self.reiter, padding=UIUtils.px(self, 6))
            self.reiter.add(seite, text=titel)
            seiten.append(seite)
        self._baue_schritt1(seiten[0])
        self._baue_schritt2(seiten[1])
        self._baue_schritt3(seiten[2])

    def _baue_schritt1(self, quelle):
        quelle.columnconfigure(1, weight=1)
        # Größte Sorge im Vortest: Sind die Mails danach weg? Darum oben und in normaler Schrift, nicht grau (E15)
        ttk.Label(quelle, text="Deine Mails bleiben unberührt: KID liest nur und arbeitet aus einem Mail-Programm auf einer "
                               "Kopie.", wraplength=UIUtils.px(self, 900), justify=tk.LEFT).grid(
            row=0, column=0, columnspan=4, sticky="w", padx=6, pady=(2, 4))
        ttk.Label(quelle, text="Mail-Programm:").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        self.var_programm = tk.StringVar(value=VON_HAND)
        self.cb_programm = ttk.Combobox(quelle, textvariable=self.var_programm, values=(VON_HAND,), state="readonly")
        self.cb_programm.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(0, 6), pady=3)
        self.cb_programm.bind("<<ComboboxSelected>>", lambda _e: self._programm_gewaehlt())
        self.lbl_programm = ttk.Label(quelle, foreground="gray40", wraplength=UIUtils.px(self, 900), justify=tk.LEFT)
        self.lbl_programm.grid(row=2, column=0, columnspan=4, sticky="w", padx=6)
        self.lbl_programm.grid_remove()
        self.rahmen_quellen = ttk.Frame(quelle)      # Häkchen, nur bei mehr als einem Konto oder einer Datei
        self.rahmen_quellen.grid(row=3, column=1, columnspan=3, sticky="ew", pady=(0, 3))
        self.rahmen_quellen.grid_remove()
        lbl_hand = ttk.Label(quelle, text="Datei/Ordner:")
        lbl_hand.grid(row=4, column=0, sticky="w", padx=6, pady=3)
        self.ent_quelle = ttk.Entry(quelle)
        self.ent_quelle.grid(row=4, column=1, sticky="ew", pady=3)
        btn_datei = ttk.Button(quelle, text="Datei…", command=self._datei_waehlen)
        btn_datei.grid(row=4, column=2, padx=(6, 0))
        btn_ordner = ttk.Button(quelle, text="Ordner…", command=self._ordner_waehlen)
        btn_ordner.grid(row=4, column=3, padx=6)
        self._zeile_von_hand = (lbl_hand, self.ent_quelle, btn_datei, btn_ordner)
        lbl_eigene = ttk.Label(quelle, text="Eigene Adressen:")
        lbl_eigene.grid(row=5, column=0, sticky="w", padx=6, pady=3)
        self.ent_eigene = ttk.Entry(quelle)
        self.ent_eigene.grid(row=5, column=1, columnspan=2, sticky="ew", pady=3)
        self.ent_eigene.insert(0, ", ".join(self.journal.eigene))
        erklaerung = ("Mit Komma getrennt, auch alte; „@beispiel.de“ steht für eine ganze Domain. Mails von dort gelten als "
                      "gesendet, abgelegt werden sie beim Empfänger.")
        Tooltip(lbl_eigene, erklaerung)
        Tooltip(self.ent_eigene, erklaerung)
        self.btn_einlesen = ttk.Button(quelle, text="Mails einlesen", command=self._einlesen)
        self.btn_einlesen.grid(row=5, column=3, padx=6)
        # Peter 04.11. (T20.1): Quelle des letzten Laufs steht wieder da
        self.ent_quelle.insert(0, self.journal.zuletzt.get("quelle", ""))
        self.rahmen_reste = ttk.Frame(quelle)
        self.rahmen_reste.grid(row=6, column=0, columnspan=4, sticky="ew", padx=6, pady=(0, 4))
        self.lbl_reste = ttk.Label(self.rahmen_reste)
        self.lbl_reste.pack(side=tk.LEFT)
        ttk.Button(self.rahmen_reste, text="Kopie löschen", command=self._kopie_loeschen).pack(side=tk.LEFT, padx=8)
        self.rahmen_reste.grid_remove()
        # Peter 09.11.2026: der freie Platz zeigt, was beim Einlesen gerade passiert, zweimal je Sekunde
        self.rahmen_stand = ttk.Frame(quelle)
        self.rahmen_stand.grid(row=7, column=0, columnspan=4, sticky="ew", padx=6, pady=(10, 4))
        self.rahmen_stand.columnconfigure(2, weight=1)
        self.stand = {}
        for zeile, (art, text) in enumerate((("liste", "Liste:"), ("text", "Text für die Suche:"))):
            ttk.Label(self.rahmen_stand, text=text).grid(row=zeile, column=0, sticky="w", pady=2)
            balken = ttk.Progressbar(self.rahmen_stand, length=UIUtils.px(self, 220), mode="determinate", maximum=100,
                                     style=BALKEN_STIL)
            balken.grid(row=zeile, column=1, sticky="w", padx=8, pady=2)
            schrift = ttk.Label(self.rahmen_stand)
            schrift.grid(row=zeile, column=2, sticky="w", pady=2)
            self.stand[art] = (balken, schrift)
        Tooltip(self.rahmen_stand, "Erst kommt die Liste aus Absender, Empfängern, Betreff und Datum - danach lässt sich "
                                   "schon suchen. Den Text der Mails liest KID im Hintergrund nach; bis dahin findet "
                                   "die Suche Wörter aus dem Text noch nicht überall.")
        self.rahmen_stand.grid_remove()

    def _baue_schritt2(self, schritt):
        zeile = ttk.Frame(schritt)
        zeile.pack(fill=tk.X, padx=6, pady=(2, 3))
        ttk.Label(zeile, text="Suche:").pack(side=tk.LEFT)
        self.ent_suche = ttk.Entry(zeile)
        self.ent_suche.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.btn_suchen = ttk.Button(zeile, text="Suchen", command=self._suche)
        self.btn_suchen.pack(side=tk.LEFT)
        Tooltip(self.ent_suche, "Sucht in Betreff, Absender, Empfängern, Text und Namen der Anhänge. Mehrere Wörter: alle "
                                "müssen vorkommen. Ein Tippfehler je Wort wird verziehen, ab 9 Buchstaben zwei; "
                                "\"in Anführungszeichen\" gilt genau. Eine Jahreszahl wie 2024 gilt als Zeitraum, "
                                "solange die Felder „ab“ und „bis“ leer sind.")
        filter_ = ttk.Frame(schritt)
        filter_.pack(fill=tk.X, padx=6, pady=3)
        ttk.Label(filter_, text="Zeitraum ab").pack(side=tk.LEFT)
        self.ent_ab = ttk.Entry(filter_, width=11)
        self.ent_ab.pack(side=tk.LEFT, padx=4)
        ttk.Label(filter_, text="bis").pack(side=tk.LEFT)
        self.ent_bis = ttk.Entry(filter_, width=11)
        self.ent_bis.pack(side=tk.LEFT, padx=4)
        Tooltip(self.ent_ab, "TT.MM.JJJJ, auch nur Jahr (2024) oder Monat (03.2024); leer = offen")
        Tooltip(self.ent_bis, "TT.MM.JJJJ, auch nur Jahr (2024) oder Monat (03.2024); leer = offen")
        ttk.Label(filter_, text="Von/An:").pack(side=tk.LEFT, padx=(12, 0))
        self.ent_von_an = ttk.Entry(filter_, width=22)
        self.ent_von_an.pack(side=tk.LEFT, padx=4)
        Tooltip(self.ent_von_an, "Name oder Adresse von Absender oder Empfänger, zum Beispiel „vivafone“")
        self.var_richtung = tk.StringVar(value="")
        for wert, text in RICHTUNGEN:
            ttk.Radiobutton(filter_, text=text, value=wert or "", variable=self.var_richtung,
                            command=self._suche).pack(side=tk.LEFT, padx=(8 if wert is None else 0, 4))
        # Peter 04.11. (T20.1): der Zeitraum des letzten Laufs steht wieder da; den Suchtext merkt sich KID nicht (F10)
        self.ent_ab.insert(0, self.journal.zuletzt.get("ab", ""))
        self.ent_bis.insert(0, self.journal.zuletzt.get("bis", ""))
        haken = ttk.Frame(schritt)
        haken.pack(fill=tk.X, padx=6, pady=(0, 3))
        self.var_anhang = tk.BooleanVar(value=False)
        ttk.Checkbutton(haken, text="nur mit Anhang", variable=self.var_anhang, command=self._suche).pack(side=tk.LEFT)
        self.var_vorfilter = tk.BooleanVar(value=False)
        chk = ttk.Checkbutton(haken, text="auch Spam, Papierkorb und Entwürfe", variable=self.var_vorfilter,
                              command=self._suche)
        chk.pack(side=tk.LEFT, padx=12)
        Tooltip(chk, "Diese Mails sind sonst ausgeblendet, ebenso Lesebestätigungen.")
        self.var_newsletter = tk.BooleanVar(value=False)       # Peter 12.11.2026: standardmäßig eingeblendet
        chk = ttk.Checkbutton(haken, text="Newsletter ausblenden", variable=self.var_newsletter, command=self._suche)
        chk.pack(side=tk.LEFT)
        Tooltip(chk, "Erkannt am Abmeldelink im Mailkopf, an Absendern wie newsletter@… oder …@news… und am Wort "
                     "„Newsletter“ im Betreff; dazu, was per Rechtsklick als Newsletter gilt. Achtung: Auch Shops "
                     "schicken Rechnungen mit Abmeldelink.")
        for feld in (self.ent_suche, self.ent_ab, self.ent_bis, self.ent_von_an):
            feld.bind("<Return>", lambda _e: self._suche())

        kopf = ttk.Frame(schritt)
        kopf.pack(fill=tk.X, padx=6, pady=(4, 2))
        ttk.Button(kopf, text="Keine", command=self._keine).pack(side=tk.RIGHT)
        ttk.Button(kopf, text="Alle anhaken", command=self._alle_anhaken).pack(side=tk.RIGHT, padx=6)
        self.lbl_treffer = ttk.Label(kopf, wraplength=UIUtils.px(self, 720), justify=tk.LEFT)
        self.lbl_treffer.pack(side=tk.LEFT, fill=tk.X, expand=True)

        weiter = ttk.Frame(schritt)
        weiter.pack(side=tk.BOTTOM, fill=tk.X, padx=6)
        self.btn_weiter = ttk.Button(weiter, text=f"Weiter zu „{REITER[2]}“", command=lambda: self.reiter.select(2))
        self.btn_weiter.pack(side=tk.RIGHT)
        self.txt_vorschau = tk.Text(schritt, height=6, wrap="word", relief=tk.FLAT, padx=6, pady=4,
                                    background=self.cget("background"))
        self.txt_vorschau.pack(side=tk.BOTTOM, fill=tk.X, padx=6, pady=(2, 6))
        self.txt_vorschau.tag_configure("kopf", foreground="gray30")
        self.txt_vorschau.config(state=tk.DISABLED)
        ttk.Label(schritt, foreground="gray40",
                  text="Klick auf das Kästchen oder Leertaste: anhaken. Graue Zeilen sind schon in der Sammlung, "
                       "Rechtsklick nimmt sie wieder heraus. ≈ = nur über eine ähnliche Schreibweise gefunden.").pack(
            side=tk.BOTTOM, anchor="w", padx=6, pady=(4, 0))
        liste = ttk.Frame(schritt)
        liste.pack(fill=tk.BOTH, expand=True, padx=6)
        spalten = ("haken", "datum", "richtung", "gegenueber", "betreff", "anhaenge", "hinweis")
        self.tree_m = ttk.Treeview(liste, columns=spalten, show="headings", selectmode="extended")
        for s, text, breite in (("haken", "", 34), ("datum", "Datum", 90), ("richtung", "", 30),
                                ("gegenueber", "Von/An", 200), ("betreff", "Betreff", 300), ("anhaenge", "Anh.", 45),
                                ("hinweis", "", 150)):
            self.tree_m.heading(s, text=text)
            self.tree_m.column(s, width=UIUtils.px(self, breite), stretch=s in ("betreff", "gegenueber"),
                               anchor="center" if s in ("haken", "richtung", "anhaenge") else "w")
        self.tree_m.tag_configure("drin", foreground="gray50")
        self.tree_m.bind("<Button-1>", self._klick)
        self.tree_m.bind("<space>", lambda _e: (self._schalte_markierte(), "break")[1])
        self.tree_m.bind("<Control-a>", lambda _e: (self.tree_m.selection_set(self.tree_m.get_children()), "break")[1])
        self.tree_m.bind("<Button-3>", self._rechtsklick)
        self.tree_m.bind("<<TreeviewSelect>>", lambda _e: (self._zeige_vorschau(), self._vormerken_bald()))
        self.menue_m = tk.Menu(self, tearoff=0)
        rollen = ttk.Scrollbar(liste, orient=tk.VERTICAL, command=self.tree_m.yview)
        self.tree_m.configure(yscrollcommand=lambda *a: (rollen.set(*a), self._vormerken_bald()))
        rollen.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_m.pack(fill=tk.BOTH, expand=True)

    def _baue_schritt3(self, schritt):
        """Ziel nach Konzept F6: Posteingang mit Vollautomatik (Vorgabe) oder direkt in einen Ordner, ohne KI."""
        schritt.columnconfigure(2, weight=1)
        self.var_ziel = tk.StringVar(value="posteingang")
        ttk.Label(schritt, text="Ziel:").grid(row=0, column=0, sticky="w", padx=6, pady=(2, 0))
        ttk.Radiobutton(schritt, text="Posteingang, die Vollautomatik legt ab", value="posteingang",
                        variable=self.var_ziel, command=self._summe).grid(row=0, column=1, columnspan=2, sticky="w")
        ttk.Radiobutton(schritt, text="direkt in den Ordner", value="ordner", variable=self.var_ziel,
                        command=self._ziel_ordner_gewaehlt).grid(row=1, column=1, sticky="w")
        self.var_ordner = tk.StringVar()
        self.cb_ordner = ttk.Combobox(schritt, textvariable=self.var_ordner, values=self._ordner, height=20)
        self.cb_ordner.grid(row=1, column=2, sticky="ew", padx=(4, 6), pady=2)
        self.cb_ordner.bind("<<ComboboxSelected>>", lambda _e: self._ziel_ordner_gewaehlt())
        self.cb_ordner.bind("<KeyRelease>", self._ordner_getippt)
        Tooltip(self.cb_ordner, "Tippen filtert die Liste. Ohne KI: Titel ist der Betreff, Datum und Absender stammen "
                                "aus der Mail, der Dateiname wird „Datum_Betreff.pdf“.")
        self.var_anhaenge = tk.BooleanVar(value=True)
        chk = ttk.Checkbutton(schritt, text="PDF-Anhänge als eigene Dokumente", variable=self.var_anhaenge,
                              command=self._summe)
        chk.grid(row=0, column=2, sticky="e", padx=6, pady=(2, 0))  # neben dem Ziel: spart eine Zeile
        Tooltip(chk, "Dann findet die Dokumentsuche auch den Text einer Rechnung im Anhang. Ohne Haken steckt der "
                     "Anhang nur in der Original-Mail, die jedes Mail-PDF eingebettet trägt.")
        unten = ttk.Frame(schritt)
        unten.grid(row=2, column=0, columnspan=3, sticky="ew")
        self.btn_import = ttk.Button(unten, text="Übernehmen", command=self._importieren, state=tk.DISABLED)
        self.btn_import.pack(side=tk.RIGHT, padx=6, pady=(2, 6))
        self.lbl_summe = ttk.Label(unten, wraplength=UIUtils.px(self, 720), justify=tk.LEFT)
        self.lbl_summe.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6, pady=(2, 6))

    def _ziel_ordner(self):
        """(gewählt, Ordner): gewählt = „direkt in den Ordner“ ist an; Ordner = der eingetragene, sofern es ihn in
        der Sammlung gibt, sonst None. Getippt genügt auch der letzte Teil („Musterversicherung“), wenn er eindeutig ist."""
        if self.var_ziel.get() != "ordner":
            return False, None
        text = self.var_ordner.get().strip().strip("\\/").casefold()
        treffer = [o for o in self._ordner if o.casefold() == text]
        if not treffer and text:
            treffer = [o for o in self._ordner if os.path.basename(o).casefold() == text]
        return True, treffer[0] if len(treffer) == 1 else None

    def _ziel_ordner_gewaehlt(self):
        self.var_ziel.set("ordner")
        self._summe()

    def _ordner_getippt(self, event):
        """Tippen filtert die Auswahl (bei Hunderten Ordnern), und wer tippt, meint „direkt in den Ordner“."""
        if event.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
            return
        text = self.var_ordner.get().strip().casefold()
        self.cb_ordner.config(values=[o for o in self._ordner if text in o.casefold()] if text else self._ordner)
        self._ziel_ordner_gewaehlt()

    # ---------------------------------------------------------------- Mail-Programme
    def _suche_programme(self):
        """Im Hintergrund, auch wenn es meist Millisekunden sind: ein Profil kann auf einem schlafenden Laufwerk liegen."""
        threading.Thread(target=lambda: self._nach_tk(self._programme_gefunden, mail_quellen.suche()),
                         name="Mail-Programme suchen", daemon=True).start()

    def _programme_gefunden(self, programme):
        self.programme = programme
        self.cb_programm.config(values=[p.text() for p in programme] + [VON_HAND])
        zuletzt = self.journal.zuletzt.get("programm")
        wahl = next((p for p in programme if p.name == zuletzt), None)
        if wahl is None and not self.ent_quelle.get().strip():         # ein Pfad im Feld hat Vorrang vor dem Vorschlag
            wahl = next((p for p in programme if p.quellen), None)
        self.var_programm.set(wahl.text() if wahl else VON_HAND)
        self._programm_gewaehlt()
        self._zeige_reste()

    def _programm(self):
        """Das gewählte Mail-Programm, bei „von Hand“ None."""
        return next((p for p in self.programme if p.text() == self.var_programm.get()), None)

    def _programm_gewaehlt(self):
        programm = self._programm()
        for w in self._zeile_von_hand:
            w.grid() if programm is None else w.grid_remove()
        for w in self.rahmen_quellen.winfo_children():
            w.destroy()
        self.haken = []
        for q in programm.quellen if programm else ():
            self.haken.append((q, tk.BooleanVar(value=True)))
        if len(self.haken) > 1:
            for i, (q, var) in enumerate(self.haken):
                ttk.Checkbutton(self.rahmen_quellen, text=f"{q.name} ({mail_quellen.groesse_text(q.groesse)})",
                                variable=var, command=self._adressen_vorschlagen).grid(row=i // 3, column=i % 3, sticky="w",
                                                                                      padx=(0, 16))
            self.rahmen_quellen.grid()
        else:
            self.rahmen_quellen.grid_remove()
        hinweis = ""
        if programm is None and not self.programme:
            hinweis = "Kein Mail-Programm gefunden. Eine Mail-Datei oder einen Ordner lässt sich von Hand wählen."
        elif programm is not None and programm.erklaerung:
            hinweis = programm.erklaerung
        elif programm is not None:
            nur_online = sum(q.nur_online for q in programm.quellen)
            if nur_online:
                hinweis = (f"{nur_online} Ordner {'liegt' if nur_online == 1 else 'liegen'} nur auf dem Server und "
                           f"{'wird' if nur_online == 1 else 'werden'} nicht gelesen. In Thunderbird lässt "
                           "sich das je Konto unter „Synchronisation & Speicherplatz“ ändern.")
        self.lbl_programm.config(text=hinweis)
        self.lbl_programm.grid() if hinweis else self.lbl_programm.grid_remove()
        self._adressen_vorschlagen()

    def _adressen_vorschlagen(self):
        """E12: die Adressen der angekreuzten Konten stehen zum Bestätigen im Feld, Eingetragenes bleibt."""
        vorhanden = eigene_aus_text(self.ent_eigene.get())
        neu = [a for q, var in self.haken if var.get() for a in q.adressen if a not in vorhanden]
        if neu:
            self.ent_eigene.delete(0, tk.END)
            self.ent_eigene.insert(0, ", ".join(vorhanden + list(dict.fromkeys(neu))))

    def _zeige_reste(self):
        """Reste eines abgebrochenen Laufs melden: Die Kopie enthält private Mails und soll nicht vergessen liegen."""
        if mail_quellen.ist_kopie(self.kopie_ziel):
            self.lbl_reste.config(text="Von einem früheren Lauf liegt noch eine Kopie der Mail-Dateien "
                                       f"({mail_quellen.groesse_text(mail_quellen.kopie_groesse(self.kopie_ziel))}).")
            self.rahmen_reste.grid()
        else:
            self.rahmen_reste.grid_remove()

    def _kopie_loeschen(self):
        if self._laeuft:
            return
        self._texte_stoppen(warten=True)             # sonst ist eine Datei der Kopie noch offen
        if self.bestand is not None and mail_import.quelle_art(self.bestand.quelle) == "kopie":
            self._setze_bestand(None)
            self.lbl_zahlen.config(text="Die Kopie ist gelöscht. Zum Weiterarbeiten wieder „Mails einlesen“.")
        if not mail_quellen.loesche_kopie(self.kopie_ziel):
            mb.showwarning("Mails importieren", f"Die Kopie ließ sich nicht ganz löschen:\n{self.kopie_ziel}", parent=self)
        self._zeige_reste()

    def _frage_kopie_loeschen(self, anlass):
        """E10: nach Rückfrage mit vorgewähltem Ja. :return: True, wenn sie weg ist oder gar nicht da war"""
        if not mail_quellen.ist_kopie(self.kopie_ziel):
            return True
        if not mb.askyesno("Mails importieren", f"{anlass}\n\nDie Kopie der Mail-Dateien enthält private Mails. Jetzt "
                           "löschen? Beim nächsten Einlesen wird neu aus dem Mail-Programm kopiert.", parent=self):
            self._zeige_reste()
            return False
        self._kopie_loeschen()
        return True

    def _melde_kopie(self, n, gesamt):
        if abs(n - self._kopie_gemeldet) >= KOPIE_MELDEN_ALLE or n == gesamt:
            self._kopie_gemeldet = n
            self._nach_tk(self._zeige_kopie, n, gesamt)

    def _zeige_kopie(self, n, gesamt):
        self.fortschritt.config(maximum=max(gesamt, 1), value=n)
        self.lbl_fortschritt.config(text=f"Kopie: {mail_quellen.groesse_text(n)} von {mail_quellen.groesse_text(gesamt)}")

    def _kopie_problem(self, fehler):
        """Gesperrt oder zu wenig Platz: Nichts wird erzwungen, der Nutzer entscheidet (E9, E11)."""
        self.lbl_zahlen.config(text="")
        if isinstance(fehler, mail_quellen.Gesperrt):
            if mb.askretrycancel("Mails importieren", f"{fehler.programm} sperrt seine Mail-Datei, solange es läuft.\n\n"
                                 f"Bitte {fehler.programm} schließen und noch einmal versuchen.", parent=self):
                self._einlesen()
            return
        if mb.askokcancel("Mails importieren", f"{fehler}\n\nBitte einen Ordner mit genug Platz wählen, zum Beispiel auf "
                          "einem anderen Laufwerk. Die Kopie wird dort nach dem Import wieder gelöscht.", parent=self):
            ordner = filedialog.askdirectory(parent=self, title="Ordner für die Kopie der Mail-Dateien wählen")
            if ordner:
                self.kopie_ziel = os.path.join(os.path.normpath(ordner), mail_quellen.KOPIE_UNTERORDNER)
                self._einlesen()

    # ---------------------------------------------------------------- Quelle
    def _datei_waehlen(self):
        pfad = filedialog.askopenfilename(parent=self, title="Mail-Datei wählen",
                                          initialdir=startordner(self.ent_quelle.get()), filetypes=[
            ("Mail-Dateien", "*.pst *.ost *.eml *.mbox *.mbx"), ("Alle Dateien (z.B. mbox ohne Endung)", "*.*")])
        if pfad:
            self.ent_quelle.delete(0, tk.END)
            self.ent_quelle.insert(0, os.path.normpath(pfad))

    def _ordner_waehlen(self):
        pfad = filedialog.askdirectory(parent=self, title="Ordner mit Mail-Dateien wählen",
                                       initialdir=startordner(self.ent_quelle.get()))
        if pfad:
            self.ent_quelle.delete(0, tk.END)
            self.ent_quelle.insert(0, os.path.normpath(pfad))

    def _abbrechen(self):
        """Die laufende Mail wird noch fertig - der Knopf sagt das, sonst wirkt er tot."""
        self._abbruch.set()
        self.btn_abbrechen.config(text="Bricht ab…", state=tk.DISABLED)

    def _merke_zuletzt(self, **werte):
        """Quelle und Zeitraum für das nächste Öffnen (T20.1, Konzept F10); den Suchtext nicht."""
        self.journal.zuletzt.update(werte, ab=self.ent_ab.get().strip(), bis=self.ent_bis.get().strip())

    def _einlesen(self):
        if self._laeuft:
            return
        programm = self._programm()
        quellen = None
        if programm is None:
            quelle = self.ent_quelle.get().strip()
            if not quelle or not os.path.exists(quelle):
                mb.showwarning("Mails importieren", "Bitte eine vorhandene Datei oder einen Ordner wählen.", parent=self)
                return
            art = mail_import.quelle_art(quelle)
            if art is None:
                mb.showwarning("Mails importieren", "Das ist keine bekannte Mail-Datei (.pst, .ost, mbox, .eml) und kein "
                                                    "Ordner.", parent=self)
                return
        else:
            if not programm.quellen:
                mb.showinfo("Mails importieren", programm.erklaerung, parent=self)
                return
            quellen = [q for q, var in self.haken if var.get()]
            if not quellen:
                mb.showwarning("Mails importieren", "Bitte mindestens ein Konto oder eine Datei ankreuzen.", parent=self)
                return
            quelle = self.kopie_ziel
            art = "pst" if programm.name == mail_quellen.OUTLOOK else "kopie"
        if art == "pst" and not mail_pst.verfuegbar():
            mb.showerror("Mails importieren", "Zum Lesen von .pst/.ost-Dateien fehlt in dieser Version das Paket "
                                              "libpff-python.", parent=self)
            return
        eigene = eigene_aus_text(self.ent_eigene.get())
        if not eigene and not mb.askyesno("Mails importieren", "Noch keine eigenen Adressen eingetragen. KID schlägt "
                                          "nach dem Einlesen die Absender aus den gesendeten Mails vor. Ohne eigene "
                                          "Adressen gelten alle Mails als eingegangen.\n\nEinlesen?", parent=self):
            return
        self.journal.eigene = eigene
        self.journal.zuletzt = {}
        if programm is None:
            self._merke_zuletzt(quelle=quelle)
        else:
            self._merke_zuletzt(programm=programm.name, kopie=self.kopie_ziel)
        try:
            self.journal.speichere()
        except OSError as e:
            mb.showerror("Mails importieren", f"Das Journal ließ sich nicht speichern:\n{e}", parent=self)
            return
        ordnerliste = auto_pilot.sammle_ordnerliste(self.master_folder)
        self._ordner = ordnerliste                   # seit dem Öffnen angelegte Ordner stehen so auch zur Wahl
        self.cb_ordner.config(values=ordnerliste)
        self._texte_stoppen(warten=True)             # die Kopie wird gleich neu geschrieben
        p1 = self._phase1 = {"lage": {}, "beginn": time.monotonic(), "ende": None}
        self._phase2 = None
        self.rahmen_stand.grid()
        self.lbl_zahlen.config(text="Lese die Liste…")
        self.rahmen_reste.grid_remove()
        self._kopie_gemeldet = 0

        def arbeit():
            if quellen is not None and not mail_quellen.kopie_passt(quelle, quellen):
                self._nach_tk(self._zeige_text, "Kopiere die Mail-Dateien, die Originale bleiben unberührt…")
                try:
                    if not mail_quellen.kopiere(quellen, quelle, abbrechen=self._abbruch.is_set,
                                                fortschritt=self._melde_kopie):
                        return None
                except (mail_quellen.Gesperrt, mail_quellen.ZuWenigPlatz) as fehler:
                    return fehler
                self._nach_tk(self._zeige_text, "Lese die Liste…")
                p1["beginn"] = time.monotonic()      # die Restzeit gilt fürs Lesen, nicht fürs Kopieren
            gedaechtnis = ablage_gedaechtnis.lade(getattr(self.app, "index_manager", None),
                                                  auto_pilot.ordner_fuer_zweitmeinung(ordnerliste),
                                                  getattr(self.app, "logger", None))
            try:
                bestand = mail_import.lies_quelle(quelle, self.journal, abbrechen=self._abbruch.is_set,
                                                  nur_kopf=True, lage=p1["lage"])
            except OSError:                # eine einzelne Datei, kaputt oder gesperrt (T20.26: sonst libpff-Rohtext)
                return unlesbar_text(quelle)
            leer = (quellen is None and os.path.isdir(quelle) and not bestand.zahlen["gesamt"]
                    and not bestand.zahlen["abgebrochen"] and not bestand.fehlende_dateien)
            return bestand, bekannt_pruefer(ordnerliste, gedaechtnis), mail_import.ordner_hinweis(quelle) if leer else None

        def fertig(ergebnis):
            p1["ende"] = time.monotonic()
            if ergebnis is None:
                self.lbl_zahlen.config(text="Kopieren abgebrochen. Es bleibt keine halbe Kopie zurück.")
                return
            if isinstance(ergebnis, OSError):
                self._kopie_problem(ergebnis)
                return
            if isinstance(ergebnis, str):
                self._log("Mail-Import: Quelle nicht lesbar", "warning")
                self.lbl_zahlen.config(text="")
                mb.showwarning("Mails importieren", ergebnis, parent=self)
                return
            bestand, self.bekannt, hinweis = ergebnis
            self._setze_bestand(bestand)
            self._summe()                            # gibt die Reiter frei, auch wenn die Suche am Zeitraum scheitert
            self.reiter.select(1)                    # weiter mit „2. Suchen“
            self._texte_starten()
            self._vormerken_bald()
            self._log(f"Mail-Import: eingelesen ({mail_import.protokoll_zeile(bestand.zahlen)})")
            self.lbl_zahlen.config(text=kennzahlen(bestand))
            self.ent_suche.focus_set()
            self._eigene_vorschlagen()
            if hinweis:
                mb.showwarning("Mails importieren", hinweis, parent=self)
            elif bestand.fehlende_dateien:
                mb.showwarning("Mails importieren", fehlende_text(bestand.fehlende_dateien), parent=self)

        self._im_hintergrund(arbeit, fertig, pausieren=False)

    def _texte_starten(self):
        """Phase 2: den Text im Hintergrund nachlesen (KONZEPT_MAIL_AUF_ABRUF „Schneller einlesen“). Der Thread ändert
        nichts selbst, jede Mail kommt über das Postfach in den Tk-Thread (`_text_da`)."""
        bestand = self.bestand
        if bestand is None or not bestand.ohne_text():
            return
        halt = threading.Event()
        lage = {"n": 0, "gesamt": bestand.ohne_text()}
        p2 = self._phase2 = {"lage": lage, "beginn": time.monotonic(), "ende": None, "halt": halt}

        buendel, zuletzt = [], [time.monotonic()]

        def melde(e, felder):                  # gebündelt: einzeln kamen bis zu tausend Nachrichten je Sekunde
            buendel.append((e, felder))
            if time.monotonic() - zuletzt[0] >= TEXT_BUENDEL_SEKUNDEN:
                self._nach_tk(self._texte_da, bestand, buendel[:])
                buendel.clear()
                zuletzt[0] = time.monotonic()

        wechsel = sys.getswitchinterval()        # Klicks warten sonst bis zu 5 ms je Tk-Aufruf (FALLSTRICKE #126)
        sys.setswitchinterval(min(wechsel, TEXT_WECHSEL_SEKUNDEN))

        def lauf():
            fehler = None
            try:
                mail_import.lies_texte(bestand, melde, lage=lage, vorne=lambda: self._vorne,
                                       abbrechen=lambda: warte_auf_vorrang(
                                           self._vorrang, lambda: halt.is_set() or self._stopp.is_set()))
            except Exception as e:             # noqa: BLE001 - die Liste bleibt, nur der Text fehlt
                fehler = type(e).__name__
            if buendel:
                self._nach_tk(self._texte_da, bestand, buendel[:])
            sys.setswitchinterval(wechsel)
            self._nach_tk(self._texte_fertig, bestand, p2, fehler)

        p2["thread"] = threading.Thread(target=lauf, name="Mail-Import Text", daemon=True)
        p2["thread"].start()

    def _vormerken_bald(self):
        if self._vormerken_id is None and self._text_laeuft():
            self._vormerken_id = self.after(150, self._sichtbare_vormerken)

    def _sichtbare_vormerken(self):
        """S2 (Peter 09.11.2026): Die Zeilen, die man gerade sieht, samt Rand und Markierten, liest Phase 2 zuerst -
        nach jeder Suche, beim Blättern und Anklicken. Eine neue Liste ersetzt die alte (`lies_texte(vorne=…)`)."""
        self._vormerken_id = None
        zeilen = self.tree_m.get_children()
        if not self._text_laeuft() or not zeilen:
            return
        oben, unten = self.tree_m.yview()
        von, bis = int(oben * len(zeilen)), int(unten * len(zeilen)) + 1
        wahl = ((self.tree_m.focus(),) + self.tree_m.selection()[:50]
                + zeilen[max(0, von - VORNE_RAND):bis + VORNE_RAND])
        eintraege, gesehen = [], set()
        for s in wahl:
            e = self._eintrag.get(s)
            if e is not None and not e.voll and s not in gesehen:
                gesehen.add(s)
                eintraege.append(e)
        if eintraege:
            self._vorne = eintraege

    def _texte_da(self, bestand, buendel):
        if bestand is not self.bestand:
            return
        fokus = self.tree_m.focus()
        for e, felder in buendel:
            anhaenge = e.anhaenge
            bestand.setze_text(e, felder)
            if e.anhaenge != anhaenge and self.tree_m.exists(e.schluessel):
                self.tree_m.set(e.schluessel, "anhaenge", e.anhaenge or "")
            if e.schluessel == fokus:
                self._zeige_vorschau()

    def _texte_fertig(self, bestand, p2, fehler):
        p2["ende"] = time.monotonic()
        if bestand is not self.bestand:
            return
        if fehler:
            self._log(f"Mail-Import: Text nachlesen abgebrochen mit {fehler}", "warning")
        else:
            self._log(f"Mail-Import: Text nachgelesen ({p2['lage']['n']} Mails, {p2['ende'] - p2['beginn']:.0f} s)")
        if self.ent_suche.get().strip():              # Treffer im Text, die beim Suchen noch fehlten
            ergebnis = self._suche_rechnen(warnen=False)
            if ergebnis is not None:
                self._suche_zeigen(ergebnis, stelle_behalten=True)

    def _texte_stoppen(self, warten=False):
        """Phase 2 anhalten; `warten`: bis die Quelle zu ist (die Kopie wird gleich gelöscht oder neu geschrieben)."""
        p2 = self._phase2
        if p2 is None:
            return
        p2["halt"].set()
        if warten and p2["thread"].is_alive():
            p2["thread"].join(timeout=10)

    def _text_laeuft(self):
        return self._phase2 is not None and self._phase2["ende"] is None and not self._phase2["halt"].is_set()

    def _zeige_stand(self):
        """Zweimal je Sekunde: Stand beider Phasen im Reiter „1. Woher?“, die zweite kurz auch unten."""
        if not self.winfo_exists():
            return
        jetzt = time.monotonic()
        p1, p2 = self._phase1, self._phase2
        if p1 is not None:
            lage, balken, schrift = p1["lage"], *self.stand["liste"]
            sekunden = (p1["ende"] or jetzt) - p1["beginn"]
            n, teil = lage.get("n", 0), lage.get("teil", 0.0)
            if p1["ende"] is None and self._laeuft:
                datei = f"Datei {lage['nr']} von {lage['gesamt']}" if lage.get("gesamt", 0) > 1 else ""
                text = stand_text(n, teil, sekunden, datei=datei) if lage else ("kopiert erst die Mail-Dateien…" if self._programm() is not None else "beginnt…")
            elif self.bestand is not None and p1["ende"] is not None:
                text = f"{n} Mails, " + ("abgebrochen" if self.bestand.zahlen["abgebrochen"] else "fertig") + \
                    f" nach {zeit_kurz(sekunden)}"           # „fertig in 32 s“ las sich wie eine Vorhersage (Peter)
            else:
                text = "nicht gelesen"
            balken.config(value=100 * teil)
            schrift.config(text=text)
            balken, schrift = self.stand["text"]
            if p2 is not None:
                lage = p2["lage"]
                n, gesamt = lage["n"], lage["gesamt"]
                sekunden = (p2["ende"] or jetzt) - p2["beginn"]
                if self._text_laeuft():
                    text = stand_text(n, n / gesamt, sekunden, gesamt=gesamt)
                else:
                    text = f"fertig nach {zeit_kurz(sekunden)}" if p2["ende"] and n >= gesamt else "angehalten"
                balken.config(value=100 * n / gesamt)
            elif self.bestand is not None and p1["ende"] is not None:
                text = "fertig"                       # nichts nachzulesen
                balken.config(value=100)
            else:
                text = ""
                balken.config(value=0)
            schrift.config(text=text)
            self._zeige_unten(p1, p2, jetzt)
            if self._text_laeuft() and not self._laeuft:
                self._suche_nachziehen()
            self._zeige_treffer()
        self._stand_id = self.after(500, self._zeige_stand)

    def _zeige_unten(self, p1, p2, jetzt):
        """Der Bereich unten zeigt jeden Vorgang, damit er in jedem Reiter zu sehen ist (Peter 09.11.2026). Kopieren und
        Übernehmen melden sich selbst (`_zeige_kopie`, `_zeige_fortschritt`), hier die beiden Phasen des Einlesens."""
        lage = p1["lage"]
        if p1["ende"] is None and self._laeuft and lage:
            datei = f"Datei {lage['nr']} von {lage['gesamt']}" if lage.get("gesamt", 0) > 1 else ""
            self.fortschritt.config(maximum=100, value=100 * lage.get("teil", 0.0))
            self.lbl_fortschritt.config(text="Liste: " + stand_text(lage.get("n", 0), lage.get("teil", 0.0),
                                                                    jetzt - p1["beginn"], datei=datei))
        elif not self._laeuft and self._text_laeuft():
            n, gesamt = p2["lage"]["n"], p2["lage"]["gesamt"]
            self.fortschritt.config(maximum=100, value=100 * n / gesamt)
            self.lbl_fortschritt.config(text="Text für die Suche: " + stand_text(n, n / gesamt, jetzt - p2["beginn"],
                                                                                 gesamt=gesamt))
        elif not self._laeuft:
            self.fortschritt.config(value=0)
            self.lbl_fortschritt.config(text="")

    def _zeige_treffer(self):
        """Trefferzeile samt Hinweis, wie weit Phase 2 ist - laufend, nicht nur beim Suchen (Peter 09.11.2026)."""
        text = self._treffer_basis
        if text and self._text_laeuft() and self.ent_suche.get().strip():
            text += ". " + text_hinweis(self._phase2["lage"]["n"], self._phase2["lage"]["gesamt"])
        if self.lbl_treffer.cget("text") != text:
            self.lbl_treffer.config(text=text)

    def _eigene_vorschlagen(self):
        """Eigene Adressen aus den Ordnern „Gesendet“ (Peter 08.11.2026: „Ich möchte nicht jedes Mal alle möglichen
        eigenen Adressen eingeben“). Ja: ins Feld und ins Journal, Richtung und Gegenüber sofort neu; Nein: diese
        Adressen nicht wieder vorschlagen. Ins Protokoll nur die Zahl."""
        eigene = eigene_aus_text(self.ent_eigene.get())
        funde = mail_import.eigene_vorschlaege(self.bestand, set(eigene), self.journal.nicht_eigene)
        if not funde:
            return
        if mb.askyesno("Mails importieren", eigene_frage_text(funde), parent=self):
            eigene += [a for a, _ in funde]
            self.ent_eigene.delete(0, tk.END)
            self.ent_eigene.insert(0, ", ".join(eigene))
            self.journal.eigene = eigene
            mail_import.setze_eigene(self.bestand, set(eigene))
            self.lbl_zahlen.config(text=kennzahlen(self.bestand))
            self._suche()
            self._log(f"Mail-Import: {len(funde)} eigene Adresse(n) aus gesendeten Mails übernommen")
        else:
            self.journal.nicht_eigene += [a for a, _ in funde]
        try:
            self.journal.speichere()
        except OSError as e:
            mb.showerror("Mails importieren", f"Das Journal ließ sich nicht speichern:\n{e}", parent=self)

    @mit_vorrang
    def _setze_bestand(self, bestand):
        """Neuer Bestand: Häkchen, die es darin noch gibt, bleiben (erneutes Einlesen derselben Quelle)."""
        self.bestand = bestand
        self._eintrag = {e.schluessel: e for e in bestand.eintraege} if bestand else {}
        self.angehakt &= set(self._eintrag)
        self._suche()

    # ---------------------------------------------------------------- Suchen und anhaken
    @mit_vorrang
    def _suche(self):
        if self.bestand is None:
            self.ergebnis = None
            self.tree_m.delete(*self.tree_m.get_children())
            self._treffer_basis = ""
            self.lbl_treffer.config(text="")
            self._zeige_vorschau()
            self._summe()
            return
        ergebnis = self._suche_rechnen(warnen=True)
        if ergebnis is not None:
            self._suche_zeigen(ergebnis)

    def _suche_rechnen(self, warnen):
        """Das Suchergebnis zu den Feldern, None bei falschem Zeitraum (`warnen`: dann mit Meldung)."""
        try:
            ab, bis = zeitraum_aus_feldern(self.ent_ab.get(), self.ent_bis.get())
        except ValueError as e:
            if warnen:
                mb.showwarning("Mails importieren", f"„{e}“ ist kein Datum. Zeitraum bitte als TT.MM.JJJJ, als Jahr "
                                                    "(2024) oder Monat (03.2024), oder leer lassen.", parent=self)
            return None
        self._nachgezogen = time.monotonic()
        return mail_import.suche(self.bestand, self.ent_suche.get(), ab, bis, von_an=self.ent_von_an.get(),
                                 richtung=self.var_richtung.get() or None, nur_anhang=self.var_anhang.get(),
                                 auch_vorfilter=self.var_vorfilter.get(), ohne_newsletter=self.var_newsletter.get(),
                                 newsletter_regeln=set(self.journal.newsletter))

    @mit_vorrang
    def _suche_nachziehen(self):
        """S2: Läuft Phase 2 und steht etwas im Suchfeld, kommen Treffer im Text von selbst dazu - ohne neues „Suchen“,
        an derselben Stelle der Liste. Neu aufgebaut wird nur, wenn sich die Zahl der Treffer geändert hat."""
        if (self.bestand is None or self.ergebnis is None or not self.ent_suche.get().strip()
                or time.monotonic() - self._nachgezogen < NACHZIEHEN_SEKUNDEN):
            return
        ergebnis = self._suche_rechnen(warnen=False)
        if ergebnis is None or len(ergebnis.treffer) == len(self.ergebnis.treffer):
            return
        if len(self.tree_m.get_children()) >= MAX_ZEILEN:
            # Die Liste ist voll: Neue, neuere Treffer schöben die markierte Zeile hinten hinaus (Peter 10.11.2026).
            # Bis zum Ende von Phase 2 nur die Zahl nachziehen
            self._treffer_basis = treffer_text(ergebnis, MAX_ZEILEN, len(self.bestand.eintraege))
            return
        self._suche_zeigen(ergebnis, stelle_behalten=True)

    def _anker(self, markiert):
        """(Zeile, Abstand von oben) für `stelle_behalten`: die markierte, wenn man sie sieht, sonst die oberste
        sichtbare. Peter 10.11.2026: Mit nur der Blätterposition rutschte beim Nachziehen alles weg - neue Treffer
        schieben sich nach Datum dazwischen."""
        zeilen = self.tree_m.get_children()
        if not zeilen:
            return None, 0
        oben, unten = self.tree_m.yview()
        erste = min(round(oben * len(zeilen)), len(zeilen) - 1)
        sichtbar = zeilen[erste:erste + max(1, round((unten - oben) * len(zeilen)))]
        anker = markiert if markiert in sichtbar else zeilen[erste]
        return anker, sichtbar.index(anker) if anker in sichtbar else 0

    @mit_vorrang
    def _suche_zeigen(self, ergebnis, stelle_behalten=False):
        self.ergebnis = ergebnis
        vorher = self.tree_m.focus()                 # die Zeile in der Vorschau bleibt, wenn sie wieder dabei ist
        oben = self.tree_m.yview()[0]
        anker, abstand = self._anker(vorher) if stelle_behalten else (None, 0)
        self.tree_m.delete(*self.tree_m.get_children())
        for e, unscharf in self.ergebnis.treffer[:MAX_ZEILEN]:
            self.tree_m.insert("", tk.END, iid=e.schluessel, values=self._zeile(e, unscharf),
                               tags=("drin",) if e.ergebnis == IMPORTIERT else ())
        if vorher and self.tree_m.exists(vorher):
            self.tree_m.selection_set(vorher)
            self.tree_m.focus(vorher)
            if not stelle_behalten:
                self.tree_m.see(vorher)
        if anker and self.tree_m.exists(anker):
            self.tree_m.yview_moveto(max(0, self.tree_m.index(anker) - abstand) / len(self.tree_m.get_children()))
        elif stelle_behalten:
            self.tree_m.yview_moveto(oben)
        self._treffer_basis = treffer_text(self.ergebnis, min(len(self.ergebnis.treffer), MAX_ZEILEN),
                                           len(self.bestand.eintraege))
        self._zeige_treffer()
        self._zeige_vorschau()
        self._summe()
        self._vormerken_bald()

    def _zeile(self, e, unscharf):
        if e.ergebnis == IMPORTIERT:
            haken, hinweis = "", "aus der Sammlung genommen" if e.grund == mail_import.GRUND_ZURUECKGENOMMEN else "in der Sammlung"
        else:
            haken = HAKEN if e.schluessel in self.angehakt else OHNE_HAKEN
            hinweis = "schon einmal übernommen" if e.erneut else ""
        if not hinweis and mail_import.ist_newsletter(e, self._newsletter_regeln):
            hinweis = "Newsletter"
        if unscharf:
            hinweis = ("≈ ähnlich, " + hinweis) if hinweis else "≈ ähnlich"
        return (haken, e.datum.strftime("%d.%m.%Y") if e.datum else "ohne Datum", "→" if e.richtung == "aus" else "←",
                e.name or e.adresse, e.betreff, e.anhaenge or "", hinweis)

    def _schalte(self, schluessel, an=None):
        """Häkchen einer Zeile umschalten (an=None) oder setzen; schon Importiertes lässt sich nicht anhaken."""
        e = self._eintrag.get(schluessel)
        if e is None or e.ergebnis == IMPORTIERT:
            return
        if an is None:
            an = schluessel not in self.angehakt
        if an:
            self.angehakt.add(schluessel)
        else:
            self.angehakt.discard(schluessel)
        if self.tree_m.exists(schluessel):
            self.tree_m.set(schluessel, "haken", HAKEN if an else OHNE_HAKEN)

    def _klick(self, event):
        """Klick ins Kästchen hakt an, ohne die Markierung zu ändern; sonst markiert der Klick wie gewohnt."""
        zeile = self.tree_m.identify_row(event.y)
        if zeile and self.tree_m.identify_column(event.x) == "#1":
            self._schalte(zeile)
            self._summe()
            return "break"
        return None

    @mit_vorrang
    def _schalte_markierte(self, an=None):
        """Leertaste: Ist eine markierte Zeile noch ohne Häkchen, bekommen alle eins, sonst verlieren alle ihres."""
        markiert = [s for s in self.tree_m.selection() if self._eintrag[s].ergebnis != IMPORTIERT]
        if an is None:
            an = any(s not in self.angehakt for s in markiert)
        for s in markiert:
            self._schalte(s, an)
        self._summe()

    @mit_vorrang
    def _alle_anhaken(self):
        """Nur die angezeigten Treffer."""
        for s in self.tree_m.get_children():
            self._schalte(s, True)
        self._summe()

    @mit_vorrang
    def _keine(self):
        """Leert die ganze Auswahl, auch die aus früheren Suchen (Konzept F9)."""
        for s in list(self.angehakt):
            self._schalte(s, False)
        self._summe()

    def _zeige_vorschau(self):
        """Nur Text, nichts nachgeladen (Konzept F8): Kopf und Textanfang der Zeile mit dem Fokus."""
        zeile = self.tree_m.focus() or next(iter(self.tree_m.selection()), "")
        e = self._eintrag.get(zeile) if zeile and self.tree_m.exists(zeile) else None
        self.txt_vorschau.config(state=tk.NORMAL)
        self.txt_vorschau.delete("1.0", tk.END)
        if e is not None:
            wer = f"{e.name} <{e.adresse}>" if e.name and e.adresse else e.name or e.adresse
            kopf = [("An " if e.richtung == "aus" else "Von ") + wer,
                    e.datum.strftime("%d.%m.%Y %H:%M") if e.datum else "ohne Datum", e.betreff]
            if e.anhang_namen:
                kopf.append("Anhang: " + e.anhang_namen)
            self.txt_vorschau.insert(tk.END, " · ".join(kopf) + "\n", "kopf")
            self.txt_vorschau.insert(tk.END, e.anfang or ("(kein Text)" if e.voll else "(Der Text wird noch gelesen…)"))
        elif self.tree_m.get_children():
            self.txt_vorschau.insert(tk.END, "Eine Zeile anklicken, dann steht hier der Anfang der Mail.", "kopf")
        self.txt_vorschau.config(state=tk.DISABLED)

    def _menue_aktionen(self):
        """Rechtsklick: (Text, Befehl, aktiv), None = Trennstrich."""
        markiert = self.tree_m.selection()
        offen = any(self._eintrag[s].ergebnis != IMPORTIERT for s in markiert)
        drin = any(self._eintrag[s].ergebnis == IMPORTIERT and self._eintrag[s].grund != mail_import.GRUND_ZURUECKGENOMMEN
                   for s in markiert)
        frueher = any(self._eintrag[s].ergebnis == IMPORTIERT for s in markiert)
        adressen = sorted({a for s in markiert for a in self._eintrag[s].kopf.von_adressen})
        regeln = self._newsletter_regeln
        domaenen = sorted({mail_lesen.domain_schluessel(a) for a in adressen})
        domaene_text = (f"Domäne {domaenen[0]} als Newsletter behandeln" if len(domaenen) == 1
                        else "Domänen der Absender als Newsletter behandeln")
        return [("Anhaken", lambda: self._schalte_markierte(True), offen),
                ("Haken entfernen", lambda: self._schalte_markierte(False), offen), None,
                ("Aus der Sammlung nehmen…", self._zuruecknehmen, drin and not self._laeuft),
                ("Erneut übernehmen…", self._erneut, frueher and not self._laeuft), None,
                ("Absender als Newsletter behandeln", lambda: self._newsletter(adressen, False, True),
                 any(a not in regeln for a in adressen)),
                (domaene_text, lambda: self._newsletter(adressen, True, True),
                 any(d not in regeln for d in domaenen)),
                ("Nicht mehr als Newsletter behandeln", lambda: self._newsletter(adressen, False, False),
                 any(a in regeln or mail_lesen.domain_schluessel(a) in regeln for a in adressen))]

    @property
    def _newsletter_regeln(self):
        return set(self.journal.newsletter)

    def _newsletter(self, adressen, domaene, an):
        """Rechtsklick (Peter 12.11.2026): Absender oder ihre Domäne als Newsletter behandeln - oder nicht mehr. Gilt
        auch beim nächsten Einlesen (Journal). Am Kopf erkannte Newsletter bleiben, was sie sind."""
        n = mail_import.newsletter_regel(self.journal.newsletter, adressen, domaene, an)
        if not n:
            return
        try:
            self.journal.speichere()
        except OSError as e:
            mb.showerror("Mails importieren", f"Das Journal ließ sich nicht speichern:\n{e}", parent=self)
        self._log(f"Mail-Import: {n} Newsletter-Regel(n) {'dazu' if an else 'entfernt'}")
        ergebnis = self._suche_rechnen(warnen=False)
        if ergebnis is not None:
            self._suche_zeigen(ergebnis, stelle_behalten=True)

    def _erneut(self):
        """Schon übernommene Mails bewusst noch einmal übernehmen (Peter 09.11.2026): etwa nach Löschen von Hand im
        Hauptfenster - davon erfährt der Import nichts, die Mail bleibt sonst ausgegraut."""
        schluessel = {s for s in self.tree_m.selection() if self._eintrag[s].ergebnis == IMPORTIERT}
        if self._laeuft or not schluessel:
            return
        if not mb.askyesno("Mails importieren", f"{len(schluessel)} Mail(s) wurden schon einmal übernommen. Liegen sie "
                           "noch in der Sammlung, gibt es sie danach doppelt.\n\nWieder anhaken, um sie noch einmal zu "
                           "übernehmen?", parent=self):
            return
        mail_import.erneut_freigeben(self.bestand, schluessel)
        for s in schluessel:
            self._schalte(s, True)
        self._suche()
        self._log(f"Mail-Import: {len(schluessel)} Mail(s) zum erneuten Übernehmen freigegeben")

    def _rechtsklick(self, event):
        """Wie im Explorer: Eine nicht markierte Zeile wird markiert, eine markierte Gruppe bleibt."""
        zeile = self.tree_m.identify_row(event.y)
        if not zeile:
            return
        if zeile not in self.tree_m.selection():
            self.tree_m.selection_set(zeile)
            self.tree_m.focus(zeile)
        self.menue_m.delete(0, tk.END)
        for aktion in self._menue_aktionen():
            if aktion is None:
                self.menue_m.add_separator()
            else:
                text, befehl, aktiv = aktion
                self.menue_m.add_command(label=text, command=befehl, state=tk.NORMAL if aktiv else tk.DISABLED)
        try:
            self.menue_m.tk_popup(event.x_root, event.y_root)
        finally:
            self.menue_m.grab_release()

    def _offen_angehakt(self):
        return [self._eintrag[s] for s in self.angehakt if self._eintrag[s].ergebnis != IMPORTIERT]

    def _summe(self):
        if self.bestand is None:
            self.lbl_summe.config(text="")
            self.btn_import.config(text="Übernehmen", state=tk.DISABLED, style="TButton")
            self.btn_einlesen.config(style="Accent.TButton")
            self.btn_suchen.config(state=tk.DISABLED)
            self._reiter_freigeben(False)
            return
        self.btn_einlesen.config(style="TButton")
        self.btn_suchen.config(state=tk.NORMAL)
        offen = self._offen_angehakt()
        self._reiter_freigeben(True, len(offen))
        self._setze_ergebnisse()
        direkt, ordner = self._ziel_ordner()
        text = uebernahme_text(mail_import.vorschau(self.bestand, self.bekannt), ordner, self.var_anhaenge.get())
        n = len(offen)
        if direkt and not ordner and n:
            text = "Bitte einen vorhandenen Ordner der Sammlung wählen (Tippen filtert die Liste)."
            n_frei = 0
        else:
            n_frei = n
        self.lbl_summe.config(text=text)
        self.btn_import.config(text="1 markierte Mail übernehmen" if n == 1 else f"{n} markierte Mails übernehmen",
                               state=tk.DISABLED if self._laeuft or not n_frei else tk.NORMAL,
                               style="Accent.TButton" if n_frei else "TButton")

    def _reiter_freigeben(self, frei, n=0):
        """„Suchen“ und „Übernehmen“ nur mit eingelesenen Mails; am dritten Reiter steht die Zahl der angehakten."""
        if not frei and self.reiter.index("current") != 0:
            self.reiter.select(0)
        for i in (1, 2):
            self.reiter.tab(i, state=tk.NORMAL if frei else tk.DISABLED)
        self.reiter.tab(2, text=f"{REITER[2]} ({n})" if n else REITER[2])
        self.btn_weiter.config(state=tk.NORMAL if frei else tk.DISABLED, style="Accent.TButton" if n else "TButton")

    def _setze_ergebnisse(self):
        """Brücke zum Import (mail_import.importiere, vorschau): Angehakt heißt „übernehmen“, alles andere bleibt offen."""
        for e in self.bestand.eintraege:
            if e.ergebnis != IMPORTIERT:
                e.ergebnis = mail_import.UEBERNEHMEN if e.schluessel in self.angehakt else ""

    # ---------------------------------------------------------------- Import und Zurücknehmen
    def _importieren(self):
        if self._laeuft or self.bestand is None:
            return
        direkt, ordner = self._ziel_ordner()
        if direkt:
            ziel = os.path.join(self.master_folder, ordner) if ordner else None
            if ziel is None or not os.path.isdir(ziel):       # auch: seit dem Öffnen umbenannt oder gelöscht
                mb.showwarning("Mails importieren", "Bitte einen vorhandenen Ordner der Sammlung wählen.", parent=self)
                return
        else:
            ziel = auto_pilot.finde_posteingang(self.master_folder)
            if ziel is None:
                mb.showerror("Mails importieren", f"In dieser Sammlung gibt es keinen Ordner "
                                                  f"„{auto_pilot.POSTEINGANG_ORDNER}“.", parent=self)
                return
        anhaenge = self.var_anhaenge.get()
        anzahl = len(self._offen_angehakt())
        frage = (f"{anzahl} Mail(s) kommen als PDF direkt in den Ordner „{ordner}“, ohne KI." if direkt else
                 f"{anzahl} Mail(s) kommen als PDF in die Sammlung. KID sortiert sie danach im Hintergrund ein wie Scans.")
        frage += (" PDF-Anhänge kommen als eigene Dokumente dazu." if anhaenge else
                  " PDF-Anhänge bleiben nur in der Original-Mail im PDF.")
        if not anzahl or not mb.askyesno("Mails importieren", f"{frage}\n\nJetzt übernehmen?", parent=self):
            return
        self._setze_ergebnisse()

        def arbeit():
            return mail_import.importiere(self.bestand, self.journal, ziel, abbrechen=self._abbruch.is_set,
                                          fortschritt=self._melde, anhaenge=anhaenge, direkt=direkt)

        def fertig(zahlen):
            self._log(f"Mail-Import: importiert ({mail_import.protokoll_zeile(zahlen)}, "
                      f"{'direkt in einen Ordner' if direkt else 'Posteingang'})")
            self.angehakt = {s for s in self.angehakt if self._eintrag[s].ergebnis != IMPORTIERT}
            self._suche()
            if direkt:
                text = f"{zahlen['mails']} Mail(s) und {zahlen['anhaenge']} PDF-Anhang/-Anhänge liegen im Ordner „{ordner}“."
            else:
                text = (f"{zahlen['mails']} Mail(s) und {zahlen['anhaenge']} PDF-Anhang/-Anhänge liegen im Posteingang "
                        "der Sammlung. KID sortiert sie jetzt im Hintergrund ein, den Stand siehst du oben rechts neben "
                        "„Hilfe“.")
            if zahlen["layout_aufgeloest"] or zahlen["vereinfacht"]:
                text += (f"\n\nVereinfacht dargestellt, weil sie sonst nicht auf Seiten passen: {zahlen['layout_aufgeloest']} "
                         f"ohne Tabellen-Layout, {zahlen['vereinfacht']} als reiner Text. Die vollständige Mail ist jeweils "
                         "eingebettet.")
            if zahlen["fehler"] or zahlen["anhang_fehler"]:
                text += (f"\n\n{zahlen['fehler']} Mail(s) und {zahlen['anhang_fehler']} Anhang/Anhänge ließen sich "
                         "nicht umwandeln (die Mails bleiben angehakt für den nächsten Versuch).")
            mb.showinfo("Mails importieren", text, parent=self)

        self._im_hintergrund(arbeit, fertig)

    def _zuruecknehmen(self):
        """Schon importierte Mails nachträglich aus der Sammlung nehmen (Peter 05.11.2026): Ihre PDFs samt Anhängen
        kommen in den Papierkorb der Sammlung, wiederherstellbar; das Journal behält sie als importiert, damit sie
        beim nächsten Einlesen nicht als neu erscheinen."""
        if self._laeuft or self.bestand is None:
            return
        schluessel = {s for s in self.tree_m.selection() if self._eintrag[s].ergebnis == IMPORTIERT
                      and self._eintrag[s].grund != mail_import.GRUND_ZURUECKGENOMMEN}
        if not schluessel:
            return
        self.lbl_zahlen.config(text="Suche die PDFs in der Sammlung…")

        def arbeit():
            return mail_import.finde_importierte(self.master_folder, schluessel, abbrechen=self._abbruch.is_set)

        def fertig(gefunden):
            self.lbl_zahlen.config(text=kennzahlen(self.bestand))
            pfade = [p for liste in gefunden.values() for p in liste]
            if not mb.askyesno("Mails importieren", f"{len(schluessel)} Mail(s) werden aus der Sammlung genommen. "
                               f"{len(pfade)} PDF(s), auch PDF-Anhänge, kommen in den Papierkorb der Sammlung und lassen "
                               "sich dort wiederherstellen.\n\nJetzt herausnehmen?", parent=self):
                return
            verschoben, fehler = self.app.file_ops.in_papierkorb(pfade)
            if fehler:                       # eine Datei ist noch offen: die Mail bleibt, wie sie war
                mb.showwarning("Mails importieren", f"{fehler} PDF(s) ließen sich nicht verschieben. Sind sie gerade "
                               "geöffnet? Bitte noch einmal versuchen.", parent=self)
                schluessel_ok = {s for s, liste in gefunden.items() if all(not os.path.exists(p) for p in liste)}
                schluessel_ok |= schluessel - set(gefunden)
            else:
                schluessel_ok = schluessel
            mail_import.merke_zurueckgenommen(self.bestand, self.journal, schluessel_ok)
            try:
                self.journal.speichere()
            except OSError as e:
                mb.showerror("Mails importieren", f"Das ließ sich nicht speichern:\n{e}", parent=self)
            self._log(f"Mail-Import: aus der Sammlung genommen (mails {len(schluessel_ok)}, pdfs {verschoben}, "
                      f"fehler {fehler})")
            self._suche()

        self._im_hintergrund(arbeit, fertig)

    # ---------------------------------------------------------------- Threads
    def _zeige_text(self, text):
        self.lbl_zahlen.config(text=text)

    def _melde(self, n, gesamt):
        self._nach_tk(self._zeige_fortschritt, n, gesamt)

    def _zeige_fortschritt(self, n, gesamt):
        self.fortschritt.config(maximum=max(gesamt, 1), value=n)
        self.lbl_fortschritt.config(text="Übernehmen: " + fortschritt_text(n, gesamt, time.monotonic() - self._beginn))

    def _im_hintergrund(self, arbeit, fertig, pausieren=True):
        """`arbeit` im Thread, `fertig(ergebnis)` danach im Tk-Thread; solange sind die Knöpfe gesperrt, die
        Vollautomatik pausiert (Posteingang)."""
        self._laeuft = True
        self._beginn = time.monotonic()
        self._abbruch.clear()
        for knopf in (self.btn_einlesen, self.btn_import):
            knopf.config(state=tk.DISABLED)
        self.btn_abbrechen.config(state=tk.NORMAL)
        if pausieren:
            self._dienst = getattr(self.app, "auto_pilot_service", None)
            if self._dienst is not None:
                self._dienst.pausieren()

        def lauf():
            try:
                ergebnis, fehler = arbeit(), None
            except Exception as e:             # noqa: BLE001 - jeder Fehler kommt als Meldung zurück
                ergebnis, fehler = None, e
            self._nach_tk(self._fertig, fertig, ergebnis, fehler)

        threading.Thread(target=lauf, name="Mail-Import", daemon=True).start()

    def _fertig(self, fertig, ergebnis, fehler):
        self._laeuft = False
        if self._dienst is not None:
            self._dienst.fortsetzen()
            self._dienst = None
        self.btn_abbrechen.config(text="Abbrechen", state=tk.DISABLED)
        self.btn_einlesen.config(state=tk.NORMAL)
        self.fortschritt.config(value=0)
        self.lbl_fortschritt.config(text="")
        if isinstance(fehler, mail_import.QuelleVeraendert):
            self._log("Mail-Import: Quelle seit dem Einlesen verändert, nichts übernommen", "warning")
            self.lbl_zahlen.config(text="")
            mb.showwarning("Mails importieren", str(fehler), parent=self)
            self._summe()
            return
        if fehler is not None:
            self._log(f"Mail-Import: Fehler {type(fehler).__name__}", "warning")
            self.lbl_zahlen.config(text="")
            mb.showerror("Mails importieren", f"{type(fehler).__name__}: {fehler}", parent=self)
            self._summe()
            return
        fertig(ergebnis)
        self._summe()

    def _nach_tk(self, fn, *args):
        if not self._stopp.is_set():
            self._postfach.put((fn, args))

    def _abholen(self):
        """Postfach leeren, aber höchstens ABHOLEN_SEKUNDEN lang: Liefert ein Thread so schnell nach, wie hier abgeholt
        wird, würde das Postfach nie leer - das Fenster stand so in Phase 2 eine halbe Minute (FALLSTRICKE #125)."""
        if not self.winfo_exists():
            return
        ende = time.monotonic() + ABHOLEN_SEKUNDEN
        while time.monotonic() < ende:
            try:
                fn, args = self._postfach.get_nowait()
            except queue.Empty:
                break
            fn(*args)
            if not self.winfo_exists():
                return
        self._abhol_id = self.after(10 if not self._postfach.empty() else 100, self._abholen)

    def _schliessen(self):
        if not self.winfo_exists():
            return
        if self._laeuft and not mb.askyesno("Mails importieren", "Es läuft noch etwas. Abbrechen und schließen? "
                                            "Das Erledigte bleibt gemerkt.", parent=self):
            return
        self._texte_stoppen(warten=True)
        if not self._laeuft:
            self._frage_kopie_loeschen("Das Fenster wird geschlossen.")
        if self.journal.zuletzt:                     # der Zeitraum gilt fürs nächste Mal (T20.1)
            self._merke_zuletzt()
            try:
                self.journal.speichere()
            except OSError:
                pass                                 # nur eine Bequemlichkeit, kein Grund, das Schließen aufzuhalten
        self._abbruch.set()
        self._stopp.set()
        if self._abhol_id is not None:
            self.after_cancel(self._abhol_id)
            self._abhol_id = None
        for name in ("_stand_id", "_vormerken_id"):
            if getattr(self, name) is not None:
                self.after_cancel(getattr(self, name))
                setattr(self, name, None)
        if self._dienst is not None:
            self._dienst.fortsetzen()
            self._dienst = None
        vollautomatik_fenster.zuruecktreten(self.app, False)
        self.destroy()

    def _log(self, text, stufe="info"):
        logger = getattr(self.app, "logger", None)
        if logger is not None:
            getattr(logger, stufe)(text)


class MailsImportierenTool(BaseTool):
    """Menü-Einstieg: Mails aus .pst, mbox oder .eml suchen und gezielt als PDFs in den Posteingang übernehmen."""

    @property
    def name(self) -> str:
        return "Vollautomatik: Mails importieren"

    @property
    def menu_group(self) -> str:
        return "Vollautomatik"

    @property
    def menu_label(self) -> str:
        return "Mails importieren…"

    @property
    def absicht(self) -> str:
        return ("Mails gehören zur Korrespondenz wie Briefe: aus alten Mail-Archiven (Outlook .pst, Thunderbird mbox, "
                ".eml) gezielt die Mails holen, die man braucht - etwa „Vivafone 2024“ -, und sie neben den Briefen "
                "desselben Absenders ablegen.")

    @property
    def description(self) -> str:
        return ("Findet Thunderbird und Outlook selbst und arbeitet nur auf einer Kopie, das Mail-Programm bleibt "
                "unberührt; Mail-Dateien und Ordner gehen auch von Hand. Eine Suche wie im Hauptfenster filtert die "
                "Mails nach Text, Zeitraum, Absender und Anhang, kleine Tippfehler werden verziehen. Nur angehakte Mails "
                "kommen als PDF (mit der Original-Mail darin) in den Posteingang, PDF-Anhänge zusätzlich als eigene "
                "Dokumente. Die Quelle bleibt unverändert.")

    @property
    def menu_hooks(self) -> list:
        return ["main_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        app = context.app
        try:
            UIUtils.einzelfenster("mails_importieren", lambda: MailImportFenster(app))
        except OSError as e:                   # kaputtes Journal: nie still überschreiben
            mb.showerror("Mails importieren", str(e), parent=app.root)
            return False
        return True
