"""
Ablage-Messlauf (Etappe 9, 14.11.2026): Wie gut legt die Vollautomatik ab?

Gegenstück zu messlauf.py (dort Geschwindigkeit, hier Qualität). Ein Korpus echter Dokumente mit einmal
aufgezeichneten KI-Antworten läuft durch die echte Entscheidung (auto_pilot.baue_entscheidung) - so wie im
Vollautomatik-Dienst: Dokumente in Scan-Reihenfolge, die Ordnerliste und das Ablage-Gedächtnis wachsen nur aus
sicheren Ablagen, gemerkte Orte zählen für die Vorauswahl nicht (FALLSTRICKE #83). Ohne KI-Server, in Sekunden.

Zwei Ausgangslagen:
  bestand  alte Ordnerstruktur der Dokumente (leer) - Wahrheit ist der Ordner, in dem das Dokument lag
  frisch   Sammlung aus folder_default.json - ohne Wahrheit über Namen, bewertet wird, ob ein entstandener
           Ordner Dokumente verschiedener Originalordner mischt (wie betatest/frisch_messen.py)

Der Korpus enthält echte Dokumente und liegt darum NICHT im Repo, sondern in
~/KID-Messungen/betatest (korpus.json: KI-Antworten, ../archiv_roh/Digital: Ordnerstruktur). Ausgegeben werden
nur Zahlen. `--details` schreibt jede Entscheidung in eine Datei neben den Korpus (enthält Namen, privat).

    python ablage_messlauf.py                        # messen, mit ablage_vergleich.json vergleichen
    python ablage_messlauf.py --vergleich-speichern  # heutigen Stand als Vergleich festhalten
    python ablage_messlauf.py --details              # zusätzlich Einzelfälle in die private Datei
    python ablage_messlauf.py --korpus=korpus.json      # andere Aufnahme (26.10.2026), ohne Vergleich
    python ablage_messlauf.py --zweitmeinung=zweitmeinung_clef-flash_9b.json   # zusätzlich mit Ordnerwahl-Modell
    python ablage_messlauf.py --volltext=volltext.json   # zusätzlich mit Ordner-Steckbrief (beides kombinierbar)

Rückschritt (Code 1): bestand - weniger richtig oder mehr still falsch; frisch - mehr still falsch,
Doppelordner, Phantom-Ordner oder falsche Vorauswahl. Die Entscheidung ist deterministisch, jede Abweichung
ist also eine echte Änderung.
"""
import collections
import json
import os
import sys
import tempfile

HIER = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HIER, "src"))

import ablage_gedaechtnis  # noqa: E402
import auto_pilot  # noqa: E402
import ordner_steckbrief  # noqa: E402

KORPUS = os.path.join(os.path.expanduser("~"), "KID-Messungen", "betatest")
KORPUS_DATEI = "korpus_20261114.json"   # die Aufnahme, gegen die ablage_vergleich.json gilt (Prompt und Modell vom 14.11.2026)
VERGLEICH = os.path.join(HIER, "ablage_vergleich.json")

# Je Ausgangslage: welche Zahlen bei Zunahme (+1) bzw. Abnahme (-1) ein Rückschritt sind
SCHLECHTER = {
    "bestand": {"richtig": -1, "still falsch (vorhandener Ordner)": +1, "still falsch (neuer Ordner)": +1},
    "gefüllt": {"richtig": -1, "still falsch (vorhandener Ordner)": +1, "still falsch (neuer Ordner)": +1},
    "frisch": {"still falsch": +1, "Doppelordner": +1, "Phantom-Ordner": +1, "unsicher, Vorwahl falsch": +1},
}


def _norm(pfad):
    return os.path.normcase(os.path.normpath(pfad)) if pfad else ""


def katalog(pfad=os.path.join(HIER, "tags_default.json")):
    """(Tags, Kategorien) aus dem ausgelieferten Tag-Katalog - fest, damit die Messung wiederholbar bleibt."""
    with open(pfad, encoding="utf-8") as f:
        baum = json.load(f)
    tags, kategorien = [], []

    def gehe(knoten):
        for k in knoten:
            if k.get("is_structural"):
                kategorien.append(k["text"])
            elif not k.get("is_synonym"):
                tags.append(k["text"])
            gehe(k.get("children", []))
    gehe(baum)
    return tags, kategorien


def ordnerliste(relpfade):
    """Ordnerliste wie im Dienst: die Ordner in einem Wegwerf-Ordner anlegen und sammle_ordnerliste fragen
    (schließt Posteingang, 0_Unsicher, Sammelordner und Papierkorb genauso aus wie im Betrieb)."""
    with tempfile.TemporaryDirectory() as wurzel:
        for rel in relpfade:
            os.makedirs(os.path.join(wurzel, rel), exist_ok=True)
        return auto_pilot.sammle_ordnerliste(wurzel)


def vorlage_ordner(pfad=os.path.join(HIER, "folder_default.json")):
    with open(pfad, encoding="utf-8") as f:
        baum = json.load(f)
    rel = []

    def gehe(knoten, vorne):
        for name, kinder in knoten.items():
            rel.append(os.path.join(vorne, name))
            gehe(kinder or {}, os.path.join(vorne, name))
    gehe(baum, "")
    return rel


def bestand_ordner(roh):
    return [os.path.relpath(w, roh) for w, _, _ in os.walk(roh) if w != roh]


def lade_korpus(ordner=KORPUS, datei=KORPUS_DATEI):
    """Dokumente in Scan-Reihenfolge: [{"nr", "name", "original", "ki"}]."""
    with open(os.path.join(ordner, datei), encoding="utf-8") as f:
        return sorted(json.load(f).values(), key=lambda d: d["nr"])


def lauf(dokumente, start_ordner, tags, kategorien, ranglisten=None, texte=None, vorbelegt=()):
    """Entscheidet jedes Dokument wie der Vollautomatik-Dienst. :return: [(dokument, entscheidung oder None)]
    :param ranglisten: aufgezeichnete Zweitmeinungen {nr: [(ordner, p), ...]} (Einstellung „Ordnerwahl“,
        ki_entscheidungsmodell); aufgenommen über die Startordner - Ordner, die erst der Lauf anlegt, kennt sie
        nicht, sie kann aber eine sichere Ablage dorthin sperren. None = aus (Standard der Vollautomatik).
    :param texte: Volltext je Dokument {nr: text} - dann gilt der Ordner-Steckbrief (Regel D), gebaut wie im Dienst
        nur aus den sicher abgelegten Dokumenten des Laufs. None = aus.
    :param vorbelegt: Dokumente, die schon in ihren Originalordnern liegen (Ausgangslage „gefüllt“): Gedächtnis
        (als hätte „Absender nachlesen“ den Absender gespeichert) und Steckbrief kennen sie von Anfang an."""
    liste = list(start_ordner)
    gedaechtnis = ablage_gedaechtnis.Gedaechtnis()
    steckbriefe = ordner_steckbrief.Steckbriefe() if texte is not None else None
    namen = {_norm(o): o for o in liste}
    for d in vorbelegt:
        ordner = namen.get(_norm(d["original"]))
        if not ordner:
            continue
        if isinstance(d["ki"], dict) and "fehler" not in d["ki"]:
            gedaechtnis.stimme(d["ki"].get("absender") or "", ordner)
        if steckbriefe is not None:
            steckbriefe.hinzu(ordner, ordner_steckbrief.merkmale(texte.get(str(d["nr"]), "")))
    orte = set()
    ergebnis = []
    for d in dokumente:
        ki = d["ki"]
        if not isinstance(ki, dict) or "fehler" in ki:
            ergebnis.append((d, None))
            continue
        auto_pilot.merke_orte(orte, {"ki_antwort": ki})
        e = auto_pilot.baue_entscheidung(d["name"], dict(ki), liste, known_tags=tags, kategorien=kategorien,
                                         gedaechtnis=gedaechtnis, orte=orte)
        rang = (ranglisten or {}).get(str(d["nr"]))
        if isinstance(rang, list) and auto_pilot.braucht_zweitmeinung(e):
            e = auto_pilot.wende_zweitmeinung_an(e, [(o, p) for o, p in rang if o in liste], liste)
        merkmale = None
        if steckbriefe is not None:
            merkmale = ordner_steckbrief.merkmale(texte.get(str(d["nr"]), ""))
            vorschlag, anzahl = steckbriefe.vorschlag(merkmale)
            e = auto_pilot.wende_steckbrief_an(e, vorschlag, [(o, p) for o, p in rang if o in liste]
                                               if isinstance(rang, list) else None, liste, anzahl)
        if e["sicher"] and not e.get("ordner_sammel"):
            gedaechtnis.stimme(e["absender"], e["zielordner"])
            if e["ordner_neu"] and e["zielordner"] not in liste:
                liste.append(e["zielordner"])
            if steckbriefe is not None:
                steckbriefe.hinzu(e["zielordner"], merkmale)
        ergebnis.append((d, e))
    return ergebnis


def bewerte_bestand(ergebnis):
    """Wahrheit = Originalordner. :return: (Zähler, [(nr, Art)])"""
    z, faelle = collections.Counter(), []
    for d, e in ergebnis:
        if e is None:
            art = "KI-Fehler"
        elif e["sicher"]:
            if _norm(e["zielordner"]) == _norm(d["original"]):
                art = "richtig"
            else:
                art = "still falsch (neuer Ordner)" if e["ordner_neu"] else "still falsch (vorhandener Ordner)"
        else:
            richtig = _norm(e["zielordner"]) == _norm(d["original"])
            art = "unsicher, Vorwahl richtig" if richtig else "unsicher, Vorwahl anders"
        z[art] += 1
        faelle.append((d["nr"], art))
    return z, faelle


def bewerte_frisch(ergebnis, start_ordner):
    """Ohne Namens-Wahrheit: jeder entstandene Ordner merkt sich die Originalordner seiner Dokumente."""
    z, faelle = collections.Counter(), []
    angelegt = set(start_ordner)
    inhalt = collections.defaultdict(collections.Counter)
    heimat = {}
    for d, e in ergebnis:
        if e is None:
            art = "KI-Fehler"
        else:
            ziel, orig = e["zielordner"], _norm(d["original"])
            if e["sicher"]:
                if ziel and not e["ordner_neu"] and ziel not in angelegt:
                    art = "Phantom-Ordner"
                elif e["ordner_neu"] and orig in heimat and heimat[orig] != ziel:
                    art = "Doppelordner"
                elif inhalt[ziel] and orig not in inhalt[ziel]:
                    art = "still falsch"
                else:
                    art = "sicher ok"
                angelegt.add(ziel)
                inhalt[ziel][orig] += 1
                heimat.setdefault(orig, ziel)
            elif not e["ordner_neu"] and inhalt[ziel] and orig not in inhalt[ziel]:
                art = "unsicher, Vorwahl falsch"
            else:
                art = "unsicher"
        z[art] += 1
        faelle.append((d["nr"], art))
    return z, faelle


def rueckschritte(lage, jetzt, vorher):
    """Liste lesbarer Rückschritte gegenüber dem gespeicherten Stand."""
    aus = []
    for art, richtung in SCHLECHTER[lage.split()[0]].items():    # „bestand mit Zweitmeinung“ wie „bestand“
        diff = jetzt.get(art, 0) - vorher.get(art, 0)
        if diff * richtung > 0:
            aus.append(f"{lage}: {art} {vorher.get(art, 0)} -> {jetzt.get(art, 0)}")
    return aus


def messen(korpus_ordner=KORPUS, datei=KORPUS_DATEI, zweitmeinung=None, volltext=None):
    """:param zweitmeinung: Dateiname aufgezeichneter Ranglisten neben dem Korpus - misst dann zusätzlich
        „bestand mit Zweitmeinung“ (nur dort: aufgenommen über die Ordner der alten Struktur).
    :param volltext: Dateiname {nr: text} neben dem Korpus - misst dann zusätzlich mit Ordner-Steckbrief."""
    dokumente = lade_korpus(korpus_ordner, datei)
    tags, kategorien = katalog()
    roh = os.path.join(os.path.dirname(korpus_ordner), "archiv_roh", "Digital")
    ranglisten = texte = None
    if zweitmeinung:
        with open(os.path.join(korpus_ordner, zweitmeinung), encoding="utf-8") as f:
            ranglisten = json.load(f)
    if volltext:
        with open(os.path.join(korpus_ordner, volltext), encoding="utf-8") as f:
            texte = json.load(f)
    ergebnisse = {}
    start = ordnerliste(bestand_ordner(roh))
    for titel, r, t in (("bestand", None, None), ("bestand mit Zweitmeinung", ranglisten, None),
                        ("bestand mit Steckbrief", None, texte),
                        ("bestand mit Zweitmeinung und Steckbrief", ranglisten, texte)):
        if titel == "bestand" or (r is not None or "Zweitmeinung" not in titel) and (t is not None or "Steckbrief" not in titel):
            ergebnisse[titel] = bewerte_bestand(lauf(dokumente, start, tags, kategorien, r, t))
    # „gefüllt“: die erste Hälfte (Scan-Reihenfolge) liegt schon richtig, gemessen wird die zweite - wie in einer
    # gewachsenen Sammlung (Peter, Eltern). Steckbrief und Gedächtnis kennen den Bestand von Anfang an.
    haelfte = len(dokumente) // 2
    vor, rest = dokumente[:haelfte], dokumente[haelfte:]
    for titel, r, t in (("gefüllt", None, None), ("gefüllt mit Zweitmeinung", ranglisten, None),
                        ("gefüllt mit Steckbrief", None, texte),
                        ("gefüllt mit Zweitmeinung und Steckbrief", ranglisten, texte)):
        if titel == "gefüllt" or (r is not None or "Zweitmeinung" not in titel) and (t is not None or "Steckbrief" not in titel):
            ergebnisse[titel] = bewerte_bestand(lauf(rest, start, tags, kategorien, r, t, vorbelegt=vor))
    start = ordnerliste(vorlage_ordner())
    ergebnisse["frisch"] = bewerte_frisch(lauf(dokumente, start, tags, kategorien), start)
    if texte is not None:
        ergebnisse["frisch mit Steckbrief"] = bewerte_frisch(lauf(dokumente, start, tags, kategorien, None, texte),
                                                             start)
    return len(dokumente), ergebnisse


def ausgabe(_anzahl, ergebnisse, vergleich):
    for lage, (z, _) in ergebnisse.items():
        vorher = vergleich.get(lage, {})
        anzahl = sum(z.values()) or 1     # „gefüllt“ misst nur die zweite Hälfte
        print(f"\n{lage} ({anzahl} Dokumente)" + ("" if vorher else "  - noch kein Vergleichsstand"))
        for art in sorted(set(z) | set(vorher)):
            n, alt = z.get(art, 0), vorher.get(art)
            diff = "" if alt is None or alt == n else f"  ({'+' if n > alt else ''}{n - alt})"
            print(f"  {art:36s} {n:4d}  {100 * n / anzahl:5.1f} %{diff}")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    datei = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--korpus=")), KORPUS_DATEI)
    if not os.path.isfile(os.path.join(KORPUS, datei)):
        print(f"Kein Korpus {datei} unter {KORPUS} - der Ablage-Messlauf braucht die privaten Messdaten.")
        return 2
    zweitmeinung = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--zweitmeinung=")), None)
    volltext = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--volltext=")), None)
    anzahl, ergebnisse = messen(KORPUS, datei, zweitmeinung, volltext)
    vergleich = {}
    if datei != KORPUS_DATEI:
        print(f"Andere Aufnahme ({datei}): ohne Vergleich gegen {os.path.basename(VERGLEICH)}")
    elif os.path.isfile(VERGLEICH):
        with open(VERGLEICH, encoding="utf-8") as f:
            vergleich = json.load(f)
    ausgabe(anzahl, ergebnisse, vergleich)
    if "--details" in sys.argv:
        ziel = os.path.join(KORPUS, "ablage_details.txt")
        with open(ziel, "w", encoding="utf-8") as f:
            for lage, (_, faelle) in ergebnisse.items():
                for nr, art in faelle:
                    f.write(f"{lage}\t{nr}\t{art}\n")
        print(f"\nEinzelfälle (privat): {ziel}")
    stand = {lage: dict(z) for lage, (z, _) in ergebnisse.items()}
    if "--vergleich-speichern" in sys.argv and datei == KORPUS_DATEI:
        import sicher_speichern
        sicher_speichern.schreibe_json(VERGLEICH, stand, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"\nVergleichsstand gespeichert: {VERGLEICH}")
        return 0
    schlechter = [r for lage in stand for r in rueckschritte(lage, stand[lage], vergleich.get(lage, {}))
                  if vergleich.get(lage)]
    if schlechter:
        print("\nRÜCKSCHRITT:\n  " + "\n  ".join(schlechter))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
