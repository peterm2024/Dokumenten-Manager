"""
Ordner-Steckbrief (KONZEPT_ORDNER_STECKBRIEF.md, Idee Peter 14.11.2026).

Je Ablageordner die Merkmale, die in seinen Dokumenten wiederkehren und ihn von den anderen Ordnern unterscheiden:
IBAN, beschriftete Nummern (Kunden-, Vertrags-, Versicherungsnummer ...), sonstige Kennungen mit mindestens vier
Ziffern, Straßenadressen. Gezählt vom Code aus dem Volltext der abgelegten Dokumente - keine KI. Ein Merkmal gehört
zu einem Ordner, wenn es in mindestens MIN_DOKUMENTE seiner Dokumente und zu mindestens MIN_ANTEIL nur dort steht;
die eigene Adresse oder IBAN steht überall und fällt so von selbst heraus.

Der Steckbrief wird berechnet, nicht gespeichert (Grundsatz des Konzepts): wer ihn braucht, baut ihn aus dem Index
(`baue`). Gespeichert werden nur Korrekturen des Menschen - ausgeschlossene Merkmale (Wiki).

Nur Standardbibliothek (tests/test_modulgrenzen.py): kein Tkinter, kein PyMuPDF.
"""

import collections
import os
import re

MIN_DOKUMENTE = 2      # in so vielen Dokumenten des Ordners muss ein Merkmal stehen
MIN_ANTEIL = 0.8       # ... und so viele seiner Vorkommen müssen in diesem Ordner liegen

ARTEN = ("IBAN", "Nummer", "Kennung", "Adresse")

_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[0-9A-Z]{4}){3,7}(?:[ ]?[0-9A-Z]{1,3})?\b")
_BESCHRIFTET = re.compile(
    r"(?i)\b(?:kunden|vertrags|versicherungs|mitglieds|konto|steuer|policen|zähler|zaehler|objekt|mandats|"
    r"versicherten|personal|referenz|buchungs)[-\s]*(?:nummer|nr\.?|zeichen|id)\s*[:.]?\s*([A-Z0-9][A-Z0-9 ./\-]{3,24})")
_KENNUNG = re.compile(r"\b[A-Z0-9][A-Z0-9./\-]{4,}[A-Z0-9]\b")
_DATUM = re.compile(r"^\d{1,2}[./]\d{1,2}[./]\d{2,4}$")
_JAHR = re.compile(r"(19|20)\d{2}")
_STRASSE = re.compile(
    r"(?i)\b([A-ZÄÖÜ][a-zäöüß\-]+(?:straße|strasse|str\.|weg|gasse|platz|allee|ring|damm))\s*(\d{1,4}[ ]?[a-z]?)\b")   # [ ] statt \s: kein Zeilenumbruch in der Hausnummer


def _ziffern(text):
    return sum(c.isdigit() for c in text)


def _norm_kennung(text):
    return re.sub(r"[\s./\-]", "", text).upper()


def merkmale(text):
    """
    Merkmal-Kandidaten eines Dokuments. Ob ein Kandidat etwas taugt, entscheidet erst der Vergleich über die
    Ordner (`Steckbriefe`) - hier wird nur gesammelt und vereinheitlicht (Leerzeichen, Punkte, Bindestriche in
    Nummern fallen weg; Straßen klein, 'straße'/'strasse' -> 'str.').
    :return: Menge von (Art, Wert)
    """
    text = text or ""
    aus = set()
    for treffer in _IBAN.findall(text):
        wert = _norm_kennung(treffer)
        if 15 <= len(wert) <= 34 and _ziffern(wert) >= 10:
            aus.add(("IBAN", wert))
    for treffer in _BESCHRIFTET.findall(text):
        wert = _norm_kennung(treffer.split("  ")[0])
        if _ziffern(wert) >= 3:
            aus.add(("Nummer", wert))
    for treffer in _KENNUNG.findall(text):
        if _DATUM.match(treffer):
            continue
        wert = _norm_kennung(treffer)
        if _ziffern(wert) >= 4 and len(wert) >= 5 and not _JAHR.fullmatch(wert):
            aus.add(("Kennung", wert))
    for strasse, nummer in _STRASSE.findall(text):
        strasse = strasse.lower().replace("strasse", "str.").replace("straße", "str.")
        aus.add(("Adresse", f"{strasse} {nummer.replace(' ', '')}"))
    return aus


class Steckbriefe:
    """Merkmal -> in welchen Ordnern es wie oft steht. Lernt dazu (`hinzu`), fragt per `vorschlag`."""

    def __init__(self, mindest=MIN_DOKUMENTE, anteil=MIN_ANTEIL, ausgeschlossen=()):
        """:param ausgeschlossen: (Ordner, Art, Wert), die der Mensch verworfen hat (Wiki) - zählen nie"""
        self.mindest = mindest
        self.anteil = anteil
        self._ausgeschlossen = {(os.path.normcase(o), a, w) for o, a, w in ausgeschlossen}
        self._index = collections.defaultdict(collections.Counter)
        self._namen = {}          # normcase -> Ordnername wie in der Sammlung

    def hinzu(self, ordner, merkmal_menge):
        """Ein abgelegtes Dokument zählen (seine Merkmale stehen jetzt in `ordner`)."""
        if not ordner:
            return
        schluessel = os.path.normcase(ordner)
        self._namen.setdefault(schluessel, ordner)
        for merkmal in merkmal_menge:
            self._index[merkmal][schluessel] += 1

    def _besitzer(self, merkmal):
        """Ordner (normcase), zu dem das Merkmal gehört, oder None."""
        zaehler = self._index.get(merkmal)
        if not zaehler:
            return None
        ordner, n = zaehler.most_common(1)[0]
        if n < self.mindest or n / sum(zaehler.values()) < self.anteil:
            return None
        if (ordner, *merkmal) in self._ausgeschlossen:
            return None
        return ordner

    def vorschlag(self, merkmal_menge):
        """
        Ordner, auf den die Merkmale eines neuen Dokuments eindeutig zeigen, oder None. Eindeutig heißt: der
        bestbelegte Ordner hat mindestens doppelt so viele passende Merkmale wie der zweite (so gemessen).
        :return: (Ordnername oder None, Anzahl passender Merkmale)
        """
        stimmen = collections.Counter()
        for merkmal in merkmal_menge:
            ordner = self._besitzer(merkmal)
            if ordner:
                stimmen[ordner] += 1
        if not stimmen:
            return None, 0
        (bester, n1), *rest = stimmen.most_common()
        if rest and rest[0][1] * 2 > n1:
            return None, 0
        return self._namen[bester], n1

    def von_ordner(self, ordner):
        """Die Merkmale eines Ordners für die Anzeige: [(Art, Wert, Anzahl Dokumente, ausgeschlossen)], sortiert."""
        schluessel = os.path.normcase(ordner)
        aus = []
        for merkmal, zaehler in self._index.items():
            n = zaehler.get(schluessel, 0)
            if n >= self.mindest and n / sum(zaehler.values()) >= self.anteil:
                aus.append((*merkmal, n, (schluessel, *merkmal) in self._ausgeschlossen))
        return sorted(aus, key=lambda m: (ARTEN.index(m[0]) if m[0] in ARTEN else 9, -m[2], m[1]))

    def schliesse_aus(self, ordner, art, wert):
        """Merkmal für diesen Ordner verwerfen (das Wiki speichert es dauerhaft, hier nur für die offene Anzeige)."""
        self._ausgeschlossen.add((os.path.normcase(ordner), art, wert))

    def lasse_zu(self, ordner, art, wert):
        self._ausgeschlossen.discard((os.path.normcase(ordner), art, wert))

    def ordner(self):
        """Ordnernamen mit mindestens einem Merkmal."""
        return sorted({self._namen[o] for z in self._index.values() for o in z
                       if self._besitzer_ist(o, z)}, key=str.lower)

    def _besitzer_ist(self, ordner, zaehler):
        n = zaehler.get(ordner, 0)
        return n >= self.mindest and n / sum(zaehler.values()) >= self.anteil


def baue(ablagen, ablageziele, ausgeschlossen=()):
    """
    Steckbriefe aus dem Bestand.
    :param ablagen: [(rel_pfad, text), ...] - Volltext der Dokumente (Index)
    :param ablageziele: Ordner, die als Ziel zählen (auto_pilot.ordner_fuer_zweitmeinung) - wie beim Ablage-Gedächtnis
                        sind Dokumente im Posteingang, in 0_Unsicher, im Papierkorb oder direkt in einer
                        Buchstabengruppe keine Stimme
    """
    ziele = {os.path.normcase(z): z for z in ablageziele}
    steckbriefe = Steckbriefe(ausgeschlossen=ausgeschlossen)
    for rel_pfad, text in ablagen:
        ordner = ziele.get(os.path.normcase(os.path.dirname(rel_pfad)))
        if ordner:
            steckbriefe.hinzu(ordner, merkmale(text))
    return steckbriefe


def ansicht(ablagen, ablageziele, ausgeschlossen=()):
    """
    Für den Wiki-Bereich „Ablageordner“: wie `baue`, dazu je Ordner seine Dokumente mit ihren Merkmalen - daraus
    zeigt das Fenster die Belege eines Merkmals (`belege`).
    :return: (Steckbriefe, {Ordnername: [(rel_pfad, Merkmal-Menge), ...]})
    """
    ziele = {os.path.normcase(z): z for z in ablageziele}
    steckbriefe = Steckbriefe(ausgeschlossen=ausgeschlossen)
    dokumente = collections.defaultdict(list)
    for rel_pfad, text in ablagen:
        ordner = ziele.get(os.path.normcase(os.path.dirname(rel_pfad)))
        if ordner:
            menge = merkmale(text)
            steckbriefe.hinzu(ordner, menge)
            dokumente[ordner].append((rel_pfad, menge))
    return steckbriefe, dict(dokumente)


def belege(dokumente, ordner, art, wert):
    """Die Dokumente des Ordners, in denen das Merkmal steht (rel_pfade, sortiert). :param dokumente: aus `ansicht`"""
    return sorted((p for p, menge in dokumente.get(ordner, ()) if (art, wert) in menge), key=str.lower)


def lade(index_manager, ablageziele, ausgeschlossen=(), logger=None):
    """
    Steckbriefe der aktuellen Sammlung aus dem Volltext-Index (IndexManager.ablage_texte, aus jedem Thread). Ein
    Fehler liefert leere Steckbriefe - dann entscheiden Regeln und Zweitmeinung wie bisher, die Ablage darf daran
    nie hängen bleiben (wie ablage_gedaechtnis.lade).
    """
    try:
        ablagen = index_manager.ablage_texte() if index_manager is not None else []
    except Exception as e:
        if logger is not None:
            logger.warning(f"Ordner-Steckbriefe nicht lesbar: {e}")
        ablagen = []
    return baue(ablagen, ablageziele, ausgeschlossen=ausgeschlossen)
