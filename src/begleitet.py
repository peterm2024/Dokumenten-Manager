"""
Begleitetes Erfassen (KONZEPT_BEGLEITETES_ERFASSEN.md, Peter 04.11.2026: B1-B5 wie empfohlen) - die GUI-freien
Bausteine des Prüfplatzes `tools/begleitet_erfassen.py`.

Ein Prüfplatz, kein Lernbeschleuniger: die Simulation am Betatest-Korpus zeigte ~75 % richtige Vorschläge, flach
über 400 Dokumente - der Gewinn ist, dass der Nutzer jedes Dokument sieht (0 statt ~25 still falsch) und Titel,
Datum, Tags und Ordner in einem Durchgang korrigiert. Gelesen wird im Voraus (auto_pilot.lies_dokument), ENTSCHIEDEN
erst, wenn das Dokument dran ist - dann gelten die eben angelegten Ordner und das fortgeschriebene Gedächtnis schon.
Ohne Zweitmeinung (der Nutzer prüft ohnehin; ein Modellwechsel je Dokument kostete Sekunden).
"""

from collections import Counter

import ablage_gedaechtnis
import auto_pilot
import ordner_aliase

VORAUS = 20     # so viele Dokumente liest der Prüfplatz im Voraus (Prognose „von den nächsten …“)
OBJEKT_AB = 2   # B5: so oft dasselbe Objekt ohne Absender in denselben Ordner korrigiert, dann Objekt-Alias anbieten


def uebernimm(entscheidung, zielordner, titel, datum, tags, vorhandene_ordner, known_tags=None, kategorien=None):
    """
    „Ablegen“ auf dem Prüfplatz: die Felder des Nutzers anwenden und freigeben - er hat das Dokument gesehen, ein
    gelber Vorschlag mit seinem Ordner gilt damit als bestätigt (auch ein Dubletten-Verdacht, der im Status stand).
    Nur was keinen Dateinamen erlaubt (kein Titel, kein plausibles Datum, kein Ordner), bleibt offen - leere Tags
    sind erlaubt (reine Archivierung).
    :return: (Entscheidung, offene Probleme) - offene Probleme leer = ablegbar (sicher)
    """
    zielordner = " ".join(str(zielordner or "").split())
    e = auto_pilot.wende_korrektur_an(entscheidung, titel=titel, datum=datum, tags=tags, known_tags=known_tags,
                                      kategorien=kategorien)
    # Tags dürfen leer bleiben (Peter 04.11.2026: „Dokumente, da benötige ich keine Tags - reine Archivierung“)
    e["probleme"] = [p for p in e["probleme"] if p != auto_pilot._PROBLEM_KEINE_TAGS]
    vorher = {k: e.get(k) for k in ("ordner_per_alias", "ordner_gedaechtnis", "ordner_hinweis")}
    e = auto_pilot.wende_zielordner_an(e, zielordner, vorhandene_ordner)
    if zielordner == entscheidung.get("zielordner"):
        e.update(vorher)               # unverändert übernommen: kein „per Alias“ im Protokoll
    e = auto_pilot.wende_freigabe_an(e)
    return e, ([] if e["sicher"] else auto_pilot.korrigierbare_probleme(e))


def datum_vorschlag(entscheidung, scan_tag):
    """(Datum fürs Feld, ist Scandatum): ohne plausibles Datum aus dem Dokument das Scandatum (Peter 04.11.2026:
    „wenn kein Datum erkannt wird, sollte einfach das Scandatum benutzt werden“) - als Vorschlag im Feld, der Nutzer
    sieht den Hinweis und übernimmt mit Return."""
    datum = entscheidung.get("datum") or ""
    if auto_pilot._datum_ist_plausibel(datum):
        return datum, False
    if scan_tag and auto_pilot._datum_ist_plausibel(scan_tag):
        return scan_tag, True
    return datum, False


def feld_fuer_problem(entscheidung):
    """In welches Feld der Fokus springt: dorthin, wo ein korrigierbares Problem steht (Datum vor Titel vor Ordner);
    None = nichts zu korrigieren, Return legt ab."""
    probleme = auto_pilot.korrigierbare_probleme(entscheidung)
    for feld, problem in (("datum", auto_pilot._PROBLEM_KEIN_DATUM), ("titel", auto_pilot._PROBLEM_KEIN_TITEL)):
        if problem in probleme:
            return feld
    # fehlende Tags halten nicht auf (reine Archivierung), nur der Ordner
    return "ziel" if any(p != auto_pilot._PROBLEM_KEINE_TAGS for p in probleme) else None


def zurueckstellen(entscheidung):
    """„Nach 0_Unsicher“: der Nutzer kann (noch) nicht entscheiden - Grund „von Hand zurückgestellt“."""
    return auto_pilot.wende_zurueckstellung_an(entscheidung)


class Rueckfragen:
    """
    Die zwei Rückfragen beim Ablegen (B4/B5) - nur nach einer KORREKTUR des Zielordners, nie bei übernommenem
    Vorschlag. Messung: ein Alias aus JEDER Korrektur machte es schlechter (Themenordner ziehen dann alle Dokumente
    eines Absenders an sich), deshalb fragt KID und merkt sich ein Nein für den Rest des Durchgangs.

    B4 Absender-Schreibweise: im gewählten Ordner liegt laut Gedächtnis schon ein ANDERER Absender - „Ist X
       derselbe wie Y?“; ja = Alias X -> Ordner (gilt ab dem nächsten Dokument, auch in der Vollautomatik).
    B5 Themenordner: dasselbe Objekt ohne Absender zum OBJEKT_AB-ten Mal in denselben Ordner - Objekt-Alias anbieten.
    """

    def __init__(self):
        self.objekt_korrekturen = Counter()
        self.abgelehnt = set()

    def nach_ablage(self, vorschlag, abgelegt, gedaechtnis, aliase):
        """Rückfrage nach einer Ablage oder None. Vor dem Fortschreiben des Gedächtnisses mit dieser Ablage aufrufen.
        :return: {"art": "Absender"|"Objekt", "schluessel", "ordner", "text"}"""
        ordner = (abgelegt.get("zielordner") or "").strip()
        if not ordner or ordner == (vorschlag.get("zielordner") or "").strip():
            return None
        schluessel, art = auto_pilot.alias_schluessel(abgelegt)
        if not schluessel or (schluessel, ordner) in self.abgelehnt:
            return None
        if art == "Absender":
            if ordner_aliase.finde_alias(schluessel, aliase) or gedaechtnis is None:
                return None
            eigener = ablage_gedaechtnis.schluessel(schluessel)
            andere = [name for name, k, stimmen in gedaechtnis.eintraege()
                      if k != eigener and any(o == ordner for o, _n in stimmen)]
            if not andere:
                return None
            return {"art": art, "schluessel": schluessel, "ordner": ordner,
                    "text": f"Ist „{schluessel}“ derselbe Absender wie „{andere[0]}“?\n\nDann legt KID Dokumente von "
                            f"„{schluessel}“ künftig immer nach „{ordner}“ (auch die Vollautomatik)."}
        self.objekt_korrekturen[(schluessel, ordner)] += 1
        if self.objekt_korrekturen[(schluessel, ordner)] < OBJEKT_AB or ordner_aliase.finde_objekt_alias(
                [ordner_aliase.objekt_aus_schluessel(schluessel)], aliase)[0]:
            return None
        return {"art": art, "schluessel": schluessel, "ordner": ordner,
                "text": f"Schon {self.objekt_korrekturen[(schluessel, ordner)]} Dokumente ohne Absender zu "
                        f"„{ordner_aliase.objekt_aus_schluessel(schluessel)}“ nach „{ordner}“ gelegt.\n\n"
                        "Solche Dokumente künftig immer dort ablegen?"}

    def abgelehnt_merken(self, frage):
        self.abgelehnt.add((frage["schluessel"], frage["ordner"]))


def prognose(entscheidungen):
    """(grün, gesamt) über die schon gelesenen nächsten Dokumente - „von den nächsten 12 wären jetzt 9 grün“."""
    gelesen = [e for e in entscheidungen if e is not None]
    return sum(1 for e in gelesen if e["sicher"]), len(gelesen)
