"""
Reine, Tk-/PyMuPDF-freie Textqualitäts-Heuristik ("sieht das nach OCR-Kauderwelsch
aus?"), ursprünglich in tools/title_cleanup.py entstanden. Liegt bewusst hier auf
Root-Ebene (nicht in tools/), weil sowohl pdf_handler.py (Kern, siehe
recapture_document) als auch mehrere tools/ diese Logik teilen - ein Tool dürfte
laut CLAUDE.md-Architektur nicht von einem anderen Tool abhängen bzw. der Kern
nicht von einem Tool, ohne die Abhängigkeitsrichtung zu verdrehen.
tools/title_cleanup.py importiert diese Symbole weiterhin (Re-Export), bestehender
Code/Tests dort bleiben unverändert lauffähig.
"""

import re

VOWELS = set("aeiouäöüAEIOUÄÖÜ")
# Ab dieser Länge einer Konsonantenkette gilt ein Wort als verdächtig - gezählt werden
# LAUTE, nicht Buchstaben (siehe KONSONANTEN_GRUPPEN): kalibriert an echten OCR-Trümmern
# wie "Rcinheiltgcbot" (Kette "ltgcb" = 5) - und so, dass ehrliche Komposita wie
# "Rechtsschutz" (ch-t-s-sch = 4), "Versicherungsschein", "Abschlagsplan" oder
# "Haftpflicht" NICHT mehr melden (T5.7-Befund 20.09.2026: zu viele Fehlalarme).
CONSONANT_RUN_THRESHOLD = 5
GARBLED_MIN_WORD_LEN = 5
# Buchstabengruppen, die im Deutschen EIN Laut sind und darum als ein Konsonant zählen
KONSONANTEN_GRUPPEN = ("sch", "ch", "ck", "pf", "tz", "st")
# OCR liest ein "e" gern als "c" (Courier-artige Schriften): ein "c" vor einem Konsonanten,
# der im Deutschen nicht auf "c" folgen kann, verrät den Fehler ("Vcnlehcrt", "Rcinheiltgcbot").
# Erlaubt bleiben ch/ck (deutsch) sowie cl/cr/ct/cc (Fremdwörter: Cloud, Crash, Direct, Account).
VERDAECHTIGES_C = re.compile(r"[cC](?=[bdfgjmnpqsvwxzBDFGJMNPQSVWXZß])")

WORD_PATTERN = re.compile(r"[^\W\d_]+", re.UNICODE)
INNERE_GROSSSCHREIBUNG = re.compile(r"[a-zäöüß][A-ZÄÖÜ]")


def longest_consonant_run(word):
    """
    Länge der längsten zusammenhängenden Konsonanten-Kette in einem Wort, in LAUTEN
    gezählt: „sch", „ch", „ck", „pf", „tz", „st" sind je ein Konsonant (reine Funktion).
    """
    best = current = i = 0
    klein = word.lower()
    while i < len(word):
        ch = word[i]
        if ch.isalpha() and ch not in VOWELS:
            current += 1
            best = max(best, current)
            gruppe = next((g for g in KONSONANTEN_GRUPPEN if klein.startswith(g, i)), None)
            i += len(gruppe) if gruppe else 1
        else:
            current = 0
            i += 1
    return best


def _wort_verdaechtig(word):
    return longest_consonant_run(word) >= CONSONANT_RUN_THRESHOLD or bool(VERDAECHTIGES_C.search(word))


def looks_garbled(text):
    """
    Heuristik: enthält der Text (Titel oder Dateiname) mindestens ein Wort, das
    nach OCR-Datenmüll aussieht (lange Konsonantenkette)? Kurze Wörter werden
    ignoriert (zu viele falsch-positive Treffer bei Abkürzungen/Initialen).

    Zwei Signale je Wort: Konsonantenkette in Lauten ab CONSONANT_RUN_THRESHOLD, oder ein
    "c" in unmöglicher Nachbarschaft (VERDAECHTIGES_C, das klassische e→c der Scanner-OCR).
    Einzelne echte Wörter mit seltenen Häufungen ("Zahnarztpraxis": r-z-t-p-r) melden
    weiterhin - ein paar unnötig gemeldete, saubere Dokumente sind das kleinere Übel
    gegenüber übersehenem echten Datenmüll.
    """
    if not text:
        return False
    woerter = WORD_PATTERN.findall(text)
    for word in woerter:
        if len(word) >= GARBLED_MIN_WORD_LEN and _wort_verdaechtig(word):
            return True
    # Drittes Signal: Großbuchstaben MITTEN in mehreren Wörtern ("6umaq3jSjaA-z;nq3S}eAUd" -> jSjaA, eAUd).
    # Eingestreute Ziffern/Sonderzeichen zerhacken solchen Müll in kurze Fragmente, die die beiden
    # Wort-Prüfungen oben nicht mehr fassen (FALLSTRICKE #21). Ein einzelnes Wort reicht nicht
    # (GmbH, iPhone, McDonald sind ehrlich), zwei sind es in einem Titel praktisch nie.
    return sum(1 for w in woerter if INNERE_GROSSSCHREIBUNG.search(w)) >= 2


def textqualitaet_prozent(text):
    """
    Grober Qualitäts-Indikator (0-100) für erkannten OCR-Text, z.B. um in
    tools/document_recapture.py sichtbar zu machen, ob sich ein Neu-Erfassen
    gelohnt hat: Anteil der bewertbaren Wörter, die NICHT nach Kauderwelsch
    aussehen (gleiche Konsonantenketten-Heuristik wie looks_garbled, hier aber
    als Prozentwert statt Ja/Nein). Liefert None, wenn zu wenige bewertbare
    Wörter vorhanden sind (z.B. leerer Text) - dann lässt sich keine sinnvolle
    Aussage treffen, statt eine irreführende Zahl vorzutäuschen.
    """
    if not text:
        return None
    bewertbare = [w for w in WORD_PATTERN.findall(text) if len(w) >= GARBLED_MIN_WORD_LEN]
    if not bewertbare:
        return None
    verdaechtig = sum(1 for w in bewertbare if _wort_verdaechtig(w))
    return round(100 * (1 - verdaechtig / len(bewertbare)))
