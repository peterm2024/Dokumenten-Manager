"""
Ablage-Gedächtnis der Vollautomatik (KONZEPT_ABLAGE_GEDAECHTNIS.md, Peter 27.10.2026: E1-E5 wie
vorgeschlagen).

Kein von der KI geschriebenes Wissen, sondern eine Zählung bestätigter Fakten: „Dokumente vom
Absender X liegen in Ordner Y“. Jede Stimme ist ein PDF der Sammlung, das seinen gelesenen
Absender als KID_ABSENDER im subject-Feld trägt (geschrieben beim Ablegen und vom Werkzeug
„Absender nachlesen“). Der Ordner der Stimme ist der Ordner, in dem das PDF HEUTE liegt -
verschiebt der Nutzer ein Dokument, wandert seine Stimme mit. Das Gedächtnis ist damit keine
eigene Wahrheit neben der Sammlung und lässt sich jederzeit aus ihr neu aufbauen (Quelle:
Suchindex, IndexManager.ablage_absender).

Ein Fakt gilt erst ab MIN_STIMMEN Stimmen und MIN_ANTEIL der Stimmen dieses Absenders
(gemessen am Betatest-Korpus: qwen3.5 + Zweitmeinung 235/15 -> mit Gedächtnis 258/13
„richtig sicher / still falsch“). Rangfolge in auto_pilot.baue_entscheidung: Alias (vom
Menschen gelernt) vor Gedächtnis vor Namensregeln.

Verglichen wird über einen Schlüssel (schluessel): Kleinbuchstaben, ohne Satzzeichen und
Rechtsformen - „Stadtwerke Musterstadt GmbH“ und „Stadtwerke Musterstadt“ sind derselbe Absender.
Bewusst NUR exakt: die unscharfe Variante brachte in der Messung keine zusätzlichen
richtigen Treffer, aber Fehlgriffe.

Korrigieren: ein falsch abgelegtes Dokument in den richtigen Ordner verschieben - seine Stimme
wandert mit. Eine Sperrliste je Absender war gebaut und ist wieder weg (Peter 28.10.2026: die
Ordner stehen für Absender, nicht für Themen - ein Absender gehört also immer in EINEN Ordner).
"""

import collections
import os
import re

MIN_STIMMEN = 2
MIN_ANTEIL = 0.67

# Rechtsformen und Füllwörter, die zwei Schreibweisen desselben Absenders trennen würden
_FUELLWOERTER = {"ag", "gmbh", "mbh", "eg", "kg", "co", "ev", "e", "v", "aktiengesellschaft", "se", "ohg",
                 "gbr", "und", "der", "die", "das", "des", "für", "f", "von", "kundenservice"}


def schluessel(absender):
    """Vergleichsform eines Absenders: klein, ohne Satzzeichen und Rechtsformen ("" wenn nichts übrig bleibt)."""
    woerter = re.findall(r"[a-zäöüß0-9]+", (absender or "").lower())
    return " ".join(w for w in woerter if w not in _FUELLWOERTER)


class Gedaechtnis:
    """Stimmen „Absender-Schlüssel -> Ordner“; fragen liefert einen Ordner erst ab den Schwellen."""

    def __init__(self, mindest=MIN_STIMMEN, anteil=MIN_ANTEIL):
        self.mindest = mindest
        self.anteil = anteil
        self._stimmen = collections.defaultdict(collections.Counter)
        self._namen = {}  # Schlüssel -> eine lesbare Schreibweise (für die Anzeige)

    def stimme(self, absender, ordner):
        """Zählt eine Stimme (ein abgelegtes Dokument). Leerer Absender/Ordner zählt nicht."""
        k = schluessel(absender)
        if not k or not ordner:
            return
        self._stimmen[k][ordner] += 1
        self._namen.setdefault(k, " ".join(absender.split()))

    def frage(self, absender):
        """
        :return: (ordner, stimmen_fuer_ordner, stimmen_gesamt) oder None, wenn der Absender
                 unbekannt ist oder seine Stimmen die Schwellen nicht erreichen.
        """
        k = schluessel(absender)
        stimmen = self._stimmen.get(k)
        if not stimmen:
            return None
        ordner, n = stimmen.most_common(1)[0]
        gesamt = sum(stimmen.values())
        if n < self.mindest or n / gesamt < self.anteil:
            return None
        return ordner, n, gesamt

    def zustand(self, absender):
        """Kurztext für die Anzeige: 'gilt', 'erst 1 Dokument' oder 'uneinig'."""
        stimmen = self._stimmen.get(schluessel(absender))
        if not stimmen:
            return ""
        n = stimmen.most_common(1)[0][1]
        if n < self.mindest:
            return f"erst {n} Dokument" if n == 1 else f"erst {n} Dokumente"
        if n / sum(stimmen.values()) < self.anteil:
            return "uneinig"
        return "gilt"

    def eintraege(self):
        """Alle Absender mit ihren Stimmen, für die Anzeige: [(Name, Schlüssel, [(ordner, n), ...]), ...]."""
        return sorted(((self._namen[k], k, zaehler.most_common()) for k, zaehler in self._stimmen.items()),
                      key=lambda e: e[0].lower())

    def __len__(self):
        return len(self._stimmen)


def baue(ablagen, ablageziele):
    """
    Gedächtnis aus dem Bestand.
    :param ablagen: [(rel_pfad, absender), ...] (IndexManager.ablage_absender)
    :param ablageziele: Ordner, die als Ziel zählen (auto_pilot.ordner_fuer_zweitmeinung) - Dokumente
                        im Posteingang, in 0_Unsicher, im Papierkorb oder direkt in einer
                        Buchstabengruppe sind keine Stimme
    """
    ziele = {os.path.normcase(z): z for z in ablageziele}
    gedaechtnis = Gedaechtnis()
    for rel_pfad, absender in ablagen:
        ordner = ziele.get(os.path.normcase(os.path.dirname(rel_pfad)))
        if ordner:
            gedaechtnis.stimme(absender, ordner)
    return gedaechtnis


def lade(index_manager, ablageziele, logger=None):
    """
    Gedächtnis der aktuellen Sammlung aus dem Suchindex (aus jedem Thread aufrufbar, siehe
    IndexManager.ablage_absender). Ein Fehler liefert ein leeres Gedächtnis - dann entscheiden
    eben die Namensregeln wie bisher, die Ablage darf daran nie hängen bleiben.
    """
    try:
        ablagen = index_manager.ablage_absender() if index_manager is not None else []
    except Exception as e:
        if logger is not None:
            logger.warning(f"Ablage-Gedächtnis nicht lesbar: {e}")
        ablagen = []
    return baue(ablagen, ablageziele)
