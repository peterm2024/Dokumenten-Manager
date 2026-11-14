"""
Stufe B der Dubletten-Erkennung (Nutzerwunsch 30.08.2026, ToDo „Vollautomatik").

Stufe A ist das Werkzeug „Dubletten finden": der Mensch sucht im Bestand nach doppelt
Gescanntem. Stufe B greift eine Ebene früher — BEVOR die Vollautomatik ein Dokument
ablegt, wird geprüft, ob im Zielordner schon dasselbe Dokument liegt. Ist das so, wird
die Entscheidung auf „unsicher" gesetzt: das Dokument wandert nach `0_Unsicher` und
der Mensch entscheidet. Grundregel des Seniorenmodus: bei Zweifel nie automatisch
ablegen — eine stille Verdopplung im Bestand fällt sonst erst Jahre später auf.

Warum ein eigenes Modul und nicht in `dubletten.py` oder `auto_pilot.py`:
`dubletten.py` bleibt bewusst PyMuPDF-frei (der Aufrufer liefert Text, Seitenzahl und
Fingerabdruck), und `auto_pilot.py` darf `dubletten.py` nicht importieren, weil
`dubletten.py` seinerseits `auto_pilot` braucht (Datum aus dem Dateinamen). Hier
laufen beide Seiten zusammen; zusätzlich wohnt hier `lese_info`, das vorher nur im
Werkzeug lag und jetzt von beiden benutzt wird.

Kosten: Für jedes abzulegende Dokument werden die PDFs des Zielordners eingelesen.
Der Seitenzahl-Vorfilter wirft die meisten sofort raus (`bewerte_paar` verlangt
gleiche Seitenzahl), ein Cache verhindert Mehrfach-Lesen innerhalb eines Laufs, und
MAX_VERGLEICHE deckelt ungewöhnlich volle Ordner.
"""

import os

import dubletten
from pdf_handler import PDFHandler

MAX_VERGLEICHE = 60   # so viele gleich lange Dokumente werden je Ablage höchstens verglichen

# Grauzone der KI-Zweitprüfung (Live-Fund 06.09.2026: dieselbe Kaminkehrer-Rechnung,
# zweimal verschieden gescannt, kam auf nur 0.628 Text-Ähnlichkeit und Bild-Hamming 19 -
# unter jeder Schwelle. Gleichzeitig ähneln sich VERSCHIEDENE Wohnungs-Abrechnungen
# desselben Tages zu 0.69-0.80 bei teils identischem Bild-Fingerabdruck: die Zonen
# überlappen, keine Schwelle trennt sie). Deshalb: Bei GLEICHEM Dokumentdatum und
# Ähnlichkeit ab dieser Untergrenze wird das Vision-Modell gefragt, obwohl die
# Deterministik "kein Treffer" sagt - nur ein klares "ja" mit Begründung stoppt dann.
GRAUZONE_TEXT = 0.5


def lese_info(pfad, mit_hash=True):
    """Fingerabdruck eines Dokuments (nur PyMuPDF/Dateisystem, aus einem Thread aufrufbar)."""
    return dubletten.sammle_info(
        pfad,
        text=PDFHandler.get_first_page_text(pfad),
        seiten=PDFHandler.get_page_count(pfad),
        bildhash=PDFHandler.get_page_fingerprint(pfad),
        meta=PDFHandler.get_metadata(pfad),
        mit_hash=mit_hash,
    )


def _info(pfad, cache):
    """lese_info mit optionalem Cache; None, wenn die Datei nicht lesbar ist."""
    if cache is not None and pfad in cache:
        return cache[pfad]
    try:
        info = lese_info(pfad)
    except Exception:
        info = None
    if cache is not None:
        cache[pfad] = info
    return info


def _pdfs_im_ordner(ordner, ausser=None):
    """PDFs direkt im Ordner (nicht rekursiv), ohne die übergebene Datei selbst."""
    try:
        with os.scandir(ordner) as eintraege:
            treffer = [e.path for e in eintraege
                       if e.is_file() and e.name.lower().endswith(".pdf") and not e.name.startswith(".")]
    except OSError:
        return []
    if ausser:
        treffer = [p for p in treffer if os.path.normcase(p) != os.path.normcase(ausser)]
    return sorted(treffer)


def _zwei_verschiedene_mails(a, b):
    """Zwei Mail-PDFs mit verschiedener Message-ID sind zwei Mails, auch bei gleichem Text - monatliche Rechnungen
    aus derselben Vorlage (T20.3: 12 von 28 landeten in 0_Unsicher). Doppelte Mails fängt schon der Import ab.
    Anhänge (ohne KID_RICHTUNG) und Scans werden weiter verglichen: dieselbe Rechnung zweimal IST eine Dublette."""
    ma, mb = a.get("meta") or {}, b.get("meta") or {}
    return bool(ma.get("KID_Richtung") and mb.get("KID_Richtung") and ma.get("KID_MailID") != mb.get("KID_MailID"))


def finde_dublette(pdf_path, zielordner, merkmale=None, cache=None, max_vergleiche=MAX_VERGLEICHE, datum=None,
                   grauzone=None):
    """
    Liegt im Zielordner bereits dasselbe Dokument? Liefert (pfad, grund) oder None.

    Es zählt JEDER Treffer von `dubletten.bewerte_paar` — auch die schwachen mit dem
    Vorsatz „Prüfen:". Im Werkzeug bedeutet „Prüfen:" nur „kein Papierkorb-Vorschlag";
    hier ist schon der Verdacht Grund genug, die Automatik anhalten zu lassen.

    :param datum: Dokumentdatum des NEUEN Dokuments („JJJJ-MM-TT"). Wichtig: zum Zeit-
        punkt dieser Prüfung stehen Datum und neuer Dateiname noch NICHT in der Datei
        (beides schreibt erst `fuehre_entscheidung_aus`) — ohne diesen Wert fiele jeder
        Vergleich in den unscharfen Zweig „Datum unbekannt" (Textschwelle 0.85 statt
        0.92), und Serienbriefe derselben Vorlage aus verschiedenen Jahren landeten
        reihenweise in `0_Unsicher`. Das Datum ist laut `dubletten.py` das entscheidende
        Unterscheidungsmerkmal — es muss also mitgegeben werden.
    :param grauzone: optionales Dict, das bei „kein Treffer" mit dem besten Grauzonen-
        Kandidaten gefüllt wird (Keys pfad/aehnlichkeit): gleiches Dokumentdatum und
        Text-Ähnlichkeit >= GRAUZONE_TEXT, aber unterhalb der harten Schwellen — Futter
        für die KI-Zweitprüfung in pruefe_entscheidung (siehe GRAUZONE_TEXT oben).
    """
    if not zielordner or not os.path.isdir(zielordner):
        return None
    neu = _info(pdf_path, cache)
    if neu is None:
        return None
    if datum:
        # Kopie, damit der Cache-Eintrag des Dokuments unverändert bleibt
        neu = dict(neu, meta={**(neu.get("meta") or {}), "KID_DokumentenDatum": datum})
    datum_neu = dubletten.dokument_datum(neu)
    verglichen = 0
    for kandidat in _pdfs_im_ordner(zielordner, ausser=pdf_path):
        if verglichen >= max_vergleiche:
            break
        try:
            if PDFHandler.get_page_count(kandidat) != neu["seiten"]:
                continue    # billiger Vorfilter: bewerte_paar verlangt gleiche Seitenzahl
        except Exception:
            continue
        info = _info(kandidat, cache)
        if info is None:
            continue
        verglichen += 1
        if _zwei_verschiedene_mails(neu, info):
            continue
        grund = dubletten.bewerte_paar(neu, info, merkmale)
        if grund:
            return kandidat, grund
        if grauzone is not None and datum_neu and datum_neu == dubletten.dokument_datum(info):
            aehnlich = dubletten.text_aehnlichkeit(neu.get("text", ""), info.get("text", ""))
            if aehnlich >= GRAUZONE_TEXT and aehnlich > grauzone.get("aehnlichkeit", 0.0):
                grauzone["pfad"] = kandidat
                grauzone["aehnlichkeit"] = aehnlich
    return None


def pruefe_entscheidung(entscheidung, master_folder, merkmale=None, cache=None, ki_pruefung=None):
    """
    Hängt Stufe B an eine fertige Ablage-Entscheidung: Findet sich im Zielordner eine
    Dublette, wird die Entscheidung auf „unsicher" gesetzt und die Begründung ergänzt.

    :param ki_pruefung: optionale KI-Zweitprüfung `f(pfad_neu, pfad_alt) -> Dict|None`
        (in der Praxis auto_pilot.pruefe_dublette_per_ki; Nutzer-Entscheidung 06.09.2026).
        Sie wird NUR bei unscharfen Treffern gefragt - eine „identische Datei" ist
        mathematisch sicher eine Kopie, da gibt es nichts zu prüfen. Nur ein klares
        „nein" MIT Begründung räumt den Verdacht aus (die Entscheidung bleibt dann
        sicher, der Vermerk steht in entscheidung["dubletten_zweitpruefung"] für
        Anzeige und Protokoll); „ja"/„unsicher"/Fehler lassen den Verdacht bestehen,
        die KI-Begründung wird dann an den Hinweis angehängt (Entscheidungshilfe für
        die manuelle Freigabe). Ein Fehler der Zweitprüfung darf die Stufe-B-Sperre
        nie aufheben. Zusätzlich prüft die KI die GRAUZONE (siehe GRAUZONE_TEXT):
        meldet die Deterministik keinen Treffer, liegt aber ein gleich datierter
        Kandidat knapp unter den Schwellen, entscheidet ein klares „ja" mit
        Begründung doch noch auf „unsicher" — die KI verfeinert den Befund also in
        beide Richtungen, ersetzt ihn aber nie.
    :return: Der Hinweistext (auch für Protokoll/Anzeige) oder None, wenn nichts gefunden
             wurde bzw. die Entscheidung ohnehin schon unsicher ist.
    """
    if not entscheidung.get("sicher") or not entscheidung.get("zielordner"):
        return None
    ziel = os.path.join(master_folder, entscheidung["zielordner"])
    grauzone = {} if ki_pruefung is not None else None
    treffer = finde_dublette(entscheidung["pdf_path"], ziel, merkmale, cache,
                             datum=entscheidung.get("datum"), grauzone=grauzone)
    if not treffer:
        # Grauzone (Live-Fund 06.09.2026, Kaminkehrer-Rechnung doppelt gescannt): Die
        # Deterministik sagt "kein Treffer", aber ein gleich datierter Kandidat liegt
        # knapp darunter - das Vision-Modell schaut auf die konkreten Angaben. NUR ein
        # klares "ja" MIT Begründung stoppt die Ablage; "nein"/"unsicher"/Fehler folgen
        # dem deterministischen Befund (sonst würde jede Serien-Abrechnung hängen).
        if grauzone and grauzone.get("pfad"):
            try:
                antwort = ki_pruefung(entscheidung["pdf_path"], grauzone["pfad"])
            except Exception:
                antwort = None
            if antwort and antwort.get("gleiches_dokument") == "ja" and antwort.get("begruendung"):
                hinweis = (f"vermutlich Dublette zu '{os.path.basename(grauzone['pfad'])}' im Zielordner "
                           f"(KI-Zweitprüfung bei gleichem Datum, Text zu {grauzone['aehnlichkeit']:.0%} "
                           f"ähnlich: {antwort['begruendung']})")
                entscheidung["sicher"] = False
                entscheidung.setdefault("probleme", []).append(hinweis)
                entscheidung["dublette_zu"] = grauzone["pfad"]
                return hinweis
        return None
    pfad, grund = treffer
    if ki_pruefung is not None and not grund.startswith("identische"):
        try:
            antwort = ki_pruefung(entscheidung["pdf_path"], pfad)
        except Exception:
            antwort = None
        if antwort and antwort.get("gleiches_dokument") == "nein" and antwort.get("begruendung"):
            entscheidung["dubletten_zweitpruefung"] = (
                f"Dubletten-Verdacht zu '{os.path.basename(pfad)}' ({grund}) "
                f"per KI-Zweitprüfung ausgeräumt: {antwort['begruendung']}")
            return None
        if antwort and antwort.get("begruendung"):
            grund += f"; KI-Zweitprüfung sagt '{antwort['gleiches_dokument']}': {antwort['begruendung']}"
    hinweis = f"vermutlich Dublette zu '{os.path.basename(pfad)}' im Zielordner ({grund})"
    entscheidung["sicher"] = False
    entscheidung.setdefault("probleme", []).append(hinweis)
    entscheidung["dublette_zu"] = pfad
    return hinweis
