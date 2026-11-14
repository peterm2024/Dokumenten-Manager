"""
Rein lokale, KI-freie Rechtschreibkorrektur für die "Erweitert"-Stufe des Volltext-Index
(siehe index_manager.upgrade_to_erweitert_tier). Bewusst "dumm" gehalten - kein Ollama-
Server, kein Netzwerk, keine neue Abhängigkeit (nur `re`/`collections` aus der
Standardbibliothek), dafür deutlich schneller als die KI-Stufen ("Meister" braucht pro
Dokument einen Modellaufruf).

Zwei Schritte:
1. clean_ocr_noise: Regel-Cleanup offensichtlichen OCR-Mülls (kaputte Sonderzeichen,
   Ziffer/Buchstabe-Verwechslungen mitten im Wort).
2. correct_text: klassischer Editierdistanz-Spellchecker (nach Peter Norvig) - der
   Wortschatz ist dabei NICHT ein mitgeliefertes Wörterbuch, sondern wird aus den bereits
   gecachten Texten der eigenen Dokumentensammlung gebaut (siehe build_vocabulary): die
   meisten Wörter in den meisten Dokumenten sind intakt, das reicht als Häufigkeitstabelle.
   Findet sich für ein verdächtiges Wort kein Kandidat in Editierdistanz 1, bleibt es
   UNVERÄNDERT stehen (kein Rateverlust) - die Trefferquote ist dadurch bewusst
   unvollständig, aber nie schlechter als der Ausgangstext.
"""
import re
from collections import Counter

GERMAN_ALPHABET = "abcdefghijklmnopqrstuvwxyzäöüß"

# Wörter unter dieser Länge werden nie korrigiert - zu viele legitime kurze Wörter
# (Artikel, Präpositionen) liegen in Editierdistanz 1 zueinander, das Risiko einer
# falschen "Korrektur" wäre unverhältnismäßig hoch.
MIN_CORRECTABLE_LENGTH = 4

_WORD_RE = re.compile(r"[A-Za-zÄÖÜäöüß]+")
WORD_RE = _WORD_RE  # öffentlich für Aufrufer, die dieselbe Wortdefinition brauchen (auto_pilot)

# Eigennamen-Korrektur (correct_proper_noun): erst ab dieser Wortlänge, und ein Kandidat
# muss mindestens so oft in der Sammlung vorkommen - ein Einzelfund im Wortschatz kann
# selbst ein OCR-Fehler sein.
MIN_PROPER_NOUN_LENGTH = 5
MIN_PROPER_NOUN_FREQ = 2
_NOISE_CHARS_RE = re.compile(r"[{}|\\^~]")
_ZERO_IN_WORD_RE = re.compile(r"(?<=[A-Za-zÄÖÜäöüß])0(?=[A-Za-zÄÖÜäöüß])")
_ONE_IN_WORD_RE = re.compile(r"(?<=[A-Za-zÄÖÜäöüß])1(?=[A-Za-zÄÖÜäöüß])")
_INLINE_WHITESPACE_RE = re.compile(r"[ \t]+")


def clean_ocr_noise(text):
    """
    Regel-basierter Cleanup ohne Wortschatz: entfernt typische OCR-Sonderzeichen-Ausrutscher
    ({ } | \\ ^ ~ - in echtem deutschen Fließtext praktisch nie legitim) und löst "0"/"1"
    MITTEN IN EINEM WORT (zwischen zwei Buchstaben) zu "O"/"l" auf - der häufigste
    OCR-Verwechslungsfall. Bewusst NICHT auf isolierte Ziffern/Zahlen angewendet (Rechnungs-
    /Aktenzeichen bleiben unangetastet). Zeilenumbrüche bleiben erhalten (relevant für die
    zeilenübergreifende Suche), nur mehrfache Leerzeichen/Tabs werden zusammengezogen.
    """
    text = _NOISE_CHARS_RE.sub("", text)
    text = _ZERO_IN_WORD_RE.sub("O", text)
    text = _ONE_IN_WORD_RE.sub("l", text)
    text = _INLINE_WHITESPACE_RE.sub(" ", text)
    return text


def build_vocabulary(texts):
    """
    Baut eine Wort-Häufigkeitstabelle (klein geschrieben) aus einer Sammlung von Texten -
    typischerweise ALLE bereits gecachten Texte (text/text_ocr/text_ai) der gesamten
    Dokumentensammlung, nicht nur der gerade zu korrigierenden Dokumente: je mehr bereits
    sauberer Text vorhanden ist, desto besser die Trefferquote - der Wortschatz wächst so
    von selbst mit der Sammlung mit. None/leere Einträge werden übersprungen.
    """
    counter = Counter()
    for text in texts:
        if text:
            counter.update(w.lower() for w in _WORD_RE.findall(text))
    return counter


def _edits1(word):
    """Alle Zeichenketten in Editierdistanz 1 zu `word` (Löschen/Vertauschen/Ersetzen/Einfügen je einer Position)."""
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    deletes = (L + R[1:] for L, R in splits if R)
    transposes = (L + R[1] + R[0] + R[2:] for L, R in splits if len(R) > 1)
    replaces = (L + c + R[1:] for L, R in splits if R for c in GERMAN_ALPHABET)
    inserts = (L + c + R for L, R in splits for c in GERMAN_ALPHABET)
    return set(deletes) | set(transposes) | set(replaces) | set(inserts)


def _edits2(word):
    """Alle Zeichenketten in Editierdistanz 2 (zwei verkettete _edits1-Schritte) - nur für einzelne Wörter gedacht, nicht für Fließtext."""
    return {e2 for e1 in _edits1(word) for e2 in _edits1(e1)}


def _match_case(original, corrected_lower):
    """Überträgt das Groß-/Kleinschreibungsmuster von `original` auf den (kleingeschriebenen) Korrekturvorschlag."""
    if original.isupper():
        return corrected_lower.upper()
    if original[:1].isupper():
        return corrected_lower[:1].upper() + corrected_lower[1:]
    return corrected_lower


def correct_word(word, vocabulary):
    """
    Rät für ein einzelnes Wort: bereits im Wortschatz bekannt -> unverändert. Sonst wird
    unter allen Kandidaten in Editierdistanz 1, die selbst im Wortschatz vorkommen, der
    HÄUFIGSTE gewählt (klassischer Norvig-Spellchecker). Kein Kandidat gefunden -> Wort
    bleibt unverändert (kein Rateverlust). Bewusst nur Editierdistanz 1 (nicht 2) - schnell
    und konservativer, ein zwei Zeichen entferntes Wort ist oft ein anderes echtes Wort.
    """
    lower = word.lower()
    if lower in vocabulary:
        return word
    candidates = [w for w in _edits1(lower) if w in vocabulary]
    if not candidates:
        return word
    best = max(candidates, key=vocabulary.get)
    return _match_case(word, best)


def correct_text(text, vocabulary, min_length=MIN_CORRECTABLE_LENGTH):
    """Wendet correct_word auf jedes ausreichend lange Wort in `text` an (pro eindeutigem Wort nur einmal berechnet, da OCR-Text häufig Wiederholungen enthält)."""
    cache = {}

    def repl(match):
        word = match.group(0)
        if len(word) < min_length:
            return word
        if word not in cache:
            cache[word] = correct_word(word, vocabulary)
        return cache[word]

    return _WORD_RE.sub(repl, text)


def suggest_corrected_text(text, vocabulary):
    """
    Einstiegspunkt für die "Erweitert"-Stufe (siehe index_manager.upgrade_to_erweitert_tier):
    kombiniert clean_ocr_noise + correct_text. Liefert bei leerem Eingabetext sofort ""
    zurück, analog zu ollama_client.suggest_cleaned_text (gleiche Rolle, nur lokal statt KI).
    """
    if not text or not text.strip():
        return ""
    return correct_text(clean_ocr_noise(text), vocabulary)



def correct_proper_noun(word, vocabulary, min_freq=MIN_PROPER_NOUN_FREQ):
    """
    Korrektur für EINZELNE, exponierte Wörter wie KI-Titelwörter (Live-Fund 29.08.2026:
    das Vision-Modell las 'Musterbein' statt 'Musterheim' - zwei Zeichen daneben, also für
    correct_word mit Distanz 1 unerreichbar). Erlaubt Distanz 2, aber nur unter strengen
    Bedingungen, die im Fließtext zu riskant wären: das Wort ist mindestens
    MIN_PROPER_NOUN_LENGTH lang, im Wortschatz UNBEKANNT, und der Kandidat kommt in der
    Sammlung mindestens `min_freq`-mal vor. Distanz 1 hat Vorrang vor Distanz 2; unter
    mehreren Kandidaten gewinnt der häufigste. Kein Kandidat -> Wort bleibt unverändert.
    """
    lower = word.lower()
    if len(lower) < MIN_PROPER_NOUN_LENGTH or not vocabulary or lower in vocabulary:
        return word
    for kandidaten in (_edits1(lower), _edits2(lower)):
        treffer = [w for w in kandidaten if vocabulary.get(w, 0) >= min_freq]
        if treffer:
            return _match_case(word, max(treffer, key=vocabulary.get))
    return word
