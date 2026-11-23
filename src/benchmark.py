"""
Benchmark (Etappe 13 Schritt 3, KONZEPT_BENCHMARK.md): Wie schnell legt die Vollautomatik mit diesen Modellen auf
diesem KI-Server ab? Gemessen mit den 40 Prüfdokumenten (`pruefdokumente`) - überall dieselben Dokumente, die
Zahlen sind also zwischen Rechnern, Karten und Modellen vergleichbar.

Der Lauf geht denselben Weg wie der Vollautomatik-Dienst (auto_pilot_service._runde): Stapel zu STAPEL Dokumenten,
erst alle mit dem Lese-Modell lesen, dann die nötigen Zweitmeinungen mit dem Ordnerwahl-Modell, dann entscheiden.
Nur so zählen Modellwechsel mit, wenn beide Modelle nicht zugleich in den Grafikspeicher passen. Verschoben wird
nichts: Die Prüfdokumente liegen in einem Wegwerf-Ordner, die Ordnerliste ist die der Benchmark-Sammlung
(`pruefdokumente.ordner_der_sammlung`), ohne Ablage-Gedächtnis und mit dem ausgelieferten Tag-Katalog - die echte
Sammlung wird weder gelesen noch verändert.

Das Ergebnis enthält nur Zahlen, Modell- und Kartennamen (für „Ergebnis kopieren“ an Rückmeldungen). Ohne
Oberfläche; das Fenster ist tools/modell_benchmark.py.

Schritt 4 (Peter 22.11.2026): Gemessen wird ein FESTER Satz aus einem Zip - eingebaut der eingescannte Satz in
niedriger Auflösung (`pruefsatz/`, in der EXE per --add-data), wählbar die Download-Zips des Releases. Die Briefe
werden über den Dateinamen `Scan_0001.pdf` … ihrer Wahrheit zugeordnet; Satzname und Prüfsumme stehen im Ergebnis.
Dazu die Qualität gegen `pruefdokumente.wahrheit` (richtig sicher / zum Prüfen / still falsch, Datum, Absender),
eine Liste je Brief und die Ursache jedes Fehlers.
"""
import hashlib
import json
import os
import re
import shutil
import statistics
import tempfile
import time
import urllib.error
import zipfile
from datetime import datetime

import ablage_gedaechtnis
import app_paths
import auto_pilot
import ollama_client
import pruefdokumente
import sicher_speichern

STAPEL = 10              # wie auto_pilot_service.STAPEL_GROESSE - gleiche Modellwechsel wie im Dienst
MAX_FEHLER_IN_FOLGE = 3  # dann ist der Server weg - abbrechen statt 40 Mal zu scheitern
MAX_ERGEBNISSE = 30      # so viele Läufe bleiben in benchmark.json

# Fester Satz (Schritt 4): eingebaut der eingescannte Satz in niedriger Auflösung - Peter 20.11.2026: „die
# herausforderndste Version“, las nicht schlechter als die hohe Auflösung. Die Zips sind die unveränderten Anhänge
# der Releases (KID-Messungen/benchmark/download, einmal gebaut) - darum vergleichbar über Rechner hinweg.
SATZ_ORDNER = "pruefsatz"
SATZ_EINGEBAUT = "Pruefdokumente_Benchmark_gescannt_niedrig.zip"
# Prüfsumme des Release-Anhangs (seit v0.9.35) - test_benchmark hält den eingebauten Satz gleich dem Download
SATZ_EINGEBAUT_SUMME = "9aa3ab59d6fd29041baed02028f47de22f70b38ce70227b830a8857faccd871d"
SATZ_NAMEN = {"Pruefdokumente_Benchmark.zip": "digital",
              "Pruefdokumente_Benchmark_gescannt_hoch.zip": "gescannt hoch",
              SATZ_EINGEBAUT: "gescannt niedrig"}
MAX_BRIEF_BYTES = 50_000_000   # ein Prüfbrief hat wenige MB - größere Einträge im Zip werden übergangen
_SCAN = re.compile(r"^Scan_(\d{4})\.pdf$", re.IGNORECASE)
ERGEBNIS_TEXTE = {"richtig": "richtig sicher", "pruefen": "zum Prüfen", "falsch": "still falsch"}

# Bekannte Grafikkarten zur Auswahl (F4: von Hand eintragen, Ollama nennt die Karte nicht) - Name mit Speicher
GRAFIKKARTEN = (
    "NVIDIA GeForce RTX 3060 (12 GB)", "NVIDIA GeForce RTX 3060 Ti (8 GB)", "NVIDIA GeForce RTX 3070 (8 GB)",
    "NVIDIA GeForce RTX 3080 (10 GB)", "NVIDIA GeForce RTX 3090 (24 GB)", "NVIDIA GeForce RTX 4060 (8 GB)",
    "NVIDIA GeForce RTX 4060 Ti (16 GB)", "NVIDIA GeForce RTX 4070 (12 GB)", "NVIDIA GeForce RTX 4080 (16 GB)",
    "NVIDIA GeForce RTX 4090 (24 GB)", "NVIDIA GeForce RTX 5060 Ti (16 GB)", "NVIDIA GeForce RTX 5070 (12 GB)",
    "NVIDIA GeForce RTX 5080 (16 GB)", "NVIDIA GeForce RTX 5090 (32 GB)", "NVIDIA Quadro RTX 8000 (48 GB)",
    "NVIDIA RTX A6000 (48 GB)", "ohne Grafikkarte (Prozessor)")


def katalog():
    """(Tags, Kategorien) aus dem ausgelieferten Tag-Katalog - fest, wie im ablage_messlauf."""
    with open(app_paths.bundled_default_path("tags_default.json"), encoding="utf-8") as f:
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


def start_ordner(wurzel):
    """Ordner der Benchmark-Sammlung in `wurzel` anlegen und so auflisten wie der Dienst (sammle_ordnerliste)."""
    for rel in pruefdokumente.ordner_der_sammlung():
        os.makedirs(os.path.join(wurzel, rel), exist_ok=True)
    return auto_pilot.sammle_ordnerliste(wurzel)


def speicher(base_url, modell, ps=ollama_client.geladene_modelle):
    """Wo liegt das geladene Modell? :return: {"status": gpu/teilweise/cpu/unbekannt, "gb": Grafikspeicher}"""
    try:
        info = next((i for n, i in ps(base_url).items() if ollama_client._passt_modellname(n, modell)), None)
    except Exception:
        info = None
    if not info or info["size"] <= 0:
        return {"status": "unbekannt", "gb": None}
    vram = info["size_vram"]
    status = "cpu" if vram <= 0 else "teilweise" if vram < info["size"] * 0.95 else "gpu"
    return {"status": status, "gb": round(vram / 1e9, 1)}


def geladen(base_url, modell, ps=ollama_client.geladene_modelle):
    try:
        return any(ollama_client._passt_modellname(n, modell) for n in ps(base_url))
    except Exception:
        return False


def nummer(pfad):
    """Prüfnummer aus dem Dateinamen `Scan_0017.pdf` (17), sonst None."""
    m = _SCAN.match(os.path.basename(pfad))
    return int(m.group(1)) if m else None


def fehler_ursache(e):
    """Warum ein KI-Aufruf scheiterte - in Worten für Anzeige und Protokoll, nie mit Inhalten (Befund aus dem
    Firmen-Lauf 20.11.2026: „3 Fehler“ allein sagte nicht, dass der VM der Arbeitsspeicher fehlte)."""
    grund = getattr(e, "reason", None)
    if isinstance(e, TimeoutError) or isinstance(grund, TimeoutError):
        return "Zeitüberschreitung"
    if isinstance(e, urllib.error.HTTPError):
        return f"Serverfehler (HTTP {e.code})"
    if isinstance(e, (urllib.error.URLError, ConnectionError)):
        return "Server nicht erreichbar"
    return type(e).__name__


def lauf(pfade, base_url, lesemodell, zweitmodell="", abbrechen=None, melde=None, lies=None, zweit=None,
         ps=ollama_client.geladene_modelle, uhr=time.monotonic):
    """
    Misst die Ablage der Dokumente `pfade` wie im Dienst (Stapel lesen → Zweitmeinungen → entscheiden).
    :param zweitmodell: Ordnerwahl-Modell, "" = ohne Zweitmeinung
    :param abbrechen: () -> True bricht nach dem laufenden Aufruf ab
    :param melde: (text, erledigt, gesamt) -> None, Fortschritt (aus dem Mess-Thread!)
    :param lies, zweit: für Tests statt auto_pilot.lies_dokument / auto_pilot.hole_zweitmeinung
    :return: Messung {"lesen": [s], "lesen_anfang": [s], "zweit": [s], "zweit_anfang": [s], "gesamt": s,
        "dokumente", "fehler", "fehler_liste", "abgebrochen", "kalt", "speicher_lesen", "speicher_zweit",
        "entscheidungen"}
        - *_anfang sind die ersten Aufrufe je Stapel (Laden bzw. Modellwechsel), die übrigen stehen in lesen/zweit
        - fehler_liste: [(Prüfnummer, "Lesen"/"Zweitmeinung", Ursache)] - Ursache aus fehler_ursache
    """
    abbrechen = abbrechen or (lambda: False)
    melde = melde or (lambda *_: None)
    lies = lies or auto_pilot.lies_dokument
    zweit = zweit or auto_pilot.hole_zweitmeinung
    tags, kategorien = katalog()
    m = {"lesen": [], "lesen_anfang": [], "zweit": [], "zweit_anfang": [], "gesamt": 0.0, "dokumente": 0,
         "fehler": 0, "fehler_liste": [], "abgebrochen": False, "kalt": not geladen(base_url, lesemodell, ps),
         "speicher_lesen": None, "speicher_zweit": None, "entscheidungen": []}
    with tempfile.TemporaryDirectory(prefix="kid_benchmark_") as wurzel:
        ordnerliste = start_ordner(wurzel)
        regeln = dict(known_tags=tags, kategorien=kategorien, gedaechtnis=ablage_gedaechtnis.Gedaechtnis(),
                      orte=set())
        start, fehler_in_folge, gesamt = uhr(), 0, len(pfade)
        for anfang in range(0, gesamt, STAPEL):
            stapel = []
            for i, pfad in enumerate(pfade[anfang:anfang + STAPEL]):
                if abbrechen() or fehler_in_folge >= MAX_FEHLER_IN_FOLGE:
                    break
                melde("Lesen", anfang + i, gesamt)
                t = uhr()
                try:
                    gelesen = lies(pfad, tags, base_url, lesemodell, kategorien)
                except Exception as e:
                    m["fehler"] += 1
                    m["fehler_liste"].append((nummer(pfad), "Lesen", fehler_ursache(e)))
                    fehler_in_folge += 1
                    continue
                fehler_in_folge = 0
                m["lesen_anfang" if i == 0 else "lesen"].append(uhr() - t)
                if m["speicher_lesen"] is None:
                    m["speicher_lesen"] = speicher(base_url, lesemodell, ps)
                auto_pilot.merke_orte(regeln["orte"], gelesen)
                stapel.append(gelesen)
            ranglisten = {}
            for i, gelesen in enumerate(g for g in stapel if zweitmodell and g.get("png") is not None
                                        and auto_pilot.braucht_zweitmeinung(
                                            auto_pilot.entscheide_gelesen(g, ordnerliste, base_url, **regeln))):
                if abbrechen():
                    break
                melde("Zweitmeinung", anfang + i, gesamt)
                t = uhr()
                try:
                    ranglisten[gelesen["pdf_path"]] = zweit(gelesen, ordnerliste, base_url, zweitmodell)
                except Exception as e:
                    ranglisten[gelesen["pdf_path"]] = e
                    m["fehler"] += 1
                    m["fehler_liste"].append((nummer(gelesen["pdf_path"]), "Zweitmeinung", fehler_ursache(e)))
                    continue
                m["zweit_anfang" if i == 0 else "zweit"].append(uhr() - t)
                if m["speicher_zweit"] is None:
                    m["speicher_zweit"] = speicher(base_url, zweitmodell, ps)
            for gelesen in stapel:
                e = auto_pilot.entscheide_gelesen(gelesen, ordnerliste, base_url, entscheidungsmodell=zweitmodell,
                                                  rangliste=ranglisten.get(gelesen["pdf_path"]), **regeln)
                m["dokumente"] += 1
                m["entscheidungen"].append((os.path.basename(gelesen["pdf_path"]), e))
                if e["sicher"] and not e.get("ordner_sammel"):
                    regeln["gedaechtnis"].stimme(e["absender"], e["zielordner"])
                    if e["ordner_neu"] and e["zielordner"] not in ordnerliste:
                        ordnerliste.append(e["zielordner"])
            if abbrechen() or fehler_in_folge >= MAX_FEHLER_IN_FOLGE:
                break
        m["gesamt"] = uhr() - start
    m["abgebrochen"] = m["dokumente"] < gesamt
    return m


def _median(werte):
    return round(statistics.median(werte), 1) if werte else None


def bewerte(entscheidungen):
    """
    Qualität gegen die Wahrheit der Prüfbriefe (wie die Zählung im ablage_messlauf):
    - richtig: sicher abgelegt, und zwar richtig - im Ordner der Wahrheit, bei `auch_neu` auch in einem neuen Ordner
      dieses Namens; bei Briefen ohne passenden Ordner (Wahrheit None) ist ein NEUER Ordner richtig
    - pruefen: Rückfrage (nicht sicher) - kostet Arbeit, aber nichts geht verloren
    - falsch: sicher, aber im falschen Ordner - das Teure, niemand sieht es
    Dazu Datum (Belegdatum) und Absender (Kennwort der Wahrheit im Absender) richtig.
    :param entscheidungen: [(Dateiname, Entscheidung)] wie aus lauf()
    :return: (Zähler {richtig, pruefen, falsch, datum, absender}, Liste je Brief [{nr, erwartet, gewaehlt,
        ergebnis, datum, absender}] nach Prüfnummer)
    """
    z = {"richtig": 0, "pruefen": 0, "falsch": 0, "datum": 0, "absender": 0}
    faelle = []
    for name, e in entscheidungen:
        nr = nummer(name)
        if nr is None or not 1 <= nr <= len(pruefdokumente.BRIEFE):
            continue
        w = pruefdokumente.wahrheit(nr)
        tag, monat, jahr = w["datum"].split(".")
        datum_ok = auto_pilot.normalisiere_datum(e.get("datum") or "") == f"{jahr}-{monat}-{tag}"
        absender_ok = bool(re.search(r"\b" + re.escape(w["kennwort"]), e.get("absender") or "", re.IGNORECASE))
        ziel = (e.get("zielordner") or "").replace("\\", "/")
        if not e.get("sicher"):
            art = "pruefen"
        elif w["ordner"] is None:
            art = "richtig" if e.get("ordner_neu") else "falsch"
        else:
            art = "richtig" if pruefdokumente.ordner_richtig(nr, ziel) else "falsch"
        z[art] += 1
        z["datum"] += datum_ok
        z["absender"] += absender_ok
        erwartet = w["ordner"] or "neuer Ordner"
        if w["auch_neu"]:
            erwartet += " (oder neu: " + ", ".join(w["auch_neu"]) + ")"
        faelle.append({"nr": nr, "erwartet": erwartet, "gewaehlt": ziel or "-", "ergebnis": art,
                       "datum": datum_ok, "absender": absender_ok})
    faelle.sort(key=lambda f: f["nr"])
    return z, faelle


def zaehle_ursachen(fehler_liste):
    """{Ursache: Anzahl} aus [(Prüfnummer, Phase, Ursache)], in der Reihenfolge des ersten Auftretens."""
    ursachen = {}
    for _nr, _phase, ursache in fehler_liste:
        ursachen[ursache] = ursachen.get(ursache, 0) + 1
    return ursachen


def ursachen_text(fehler_liste):
    """„Zeitüberschreitung: 3, Server nicht erreichbar: 1“ - leer ohne Fehler."""
    return ", ".join(f"{u}: {n}" for u, n in zaehle_ursachen(fehler_liste).items())


def zusammenfassen(m, lesemodell, zweitmodell, grafikkarte, version, satz="digital", jetzt=None, pruefsumme=""):
    """Messung → Ergebnis (nur Zahlen und Namen, so wird es gespeichert und kopiert). Die Liste je Brief enthält
    nur Prüfnummern und die Ordnernamen der Benchmark-Sammlung (Musterdaten)."""
    qualitaet, faelle = bewerte(m.get("entscheidungen", []))
    ursachen = zaehle_ursachen(m.get("fehler_liste", []))
    lesen, zweit = m["lesen"] or m["lesen_anfang"], m["zweit"] or m["zweit_anfang"]
    # Modellwechsel: ab dem zweiten Stapel kostet der erste Aufruf je Modell mehr, wenn das andere Modell es aus
    # dem Speicher verdrängt hat - der erste Aufruf überhaupt ist das Laden und zählt hier nicht
    wechsel = None
    if len(m["lesen_anfang"]) > 1 and lesen:
        mehr = [a - _median(lesen) for a in m["lesen_anfang"][1:]]
        mehr += [a - _median(zweit) for a in m["zweit_anfang"][1:]] if zweit else []
        wechsel = max(0.0, round(statistics.median(mehr), 1))
    return {
        "datum": (jetzt or datetime.now()).strftime("%Y-%m-%d %H:%M"), "version": version, "satz": satz,
        "grafikkarte": grafikkarte, "lesemodell": lesemodell, "zweitmodell": zweitmodell or "",
        "dokumente": m["dokumente"], "fehler": m["fehler"], "abgebrochen": m["abgebrochen"], "kalt": m["kalt"],
        "sekunden_je_dokument": round(m["gesamt"] / m["dokumente"], 1) if m["dokumente"] else None,
        "minuten_gesamt": round(m["gesamt"] / 60, 1),
        "lesen_median": _median(lesen), "lesen_erster": round(m["lesen_anfang"][0], 1) if m["lesen_anfang"] else None,
        "zweit_median": _median(zweit), "zweit_erster": round(m["zweit_anfang"][0], 1) if m["zweit_anfang"] else None,
        "zweit_anzahl": len(m["zweit"]) + len(m["zweit_anfang"]), "wechsel_sekunden": wechsel,
        "speicher_lesen": m["speicher_lesen"], "speicher_zweit": m["speicher_zweit"],
        "pruefsumme": pruefsumme, "qualitaet": qualitaet, "faelle": faelle, "fehler_ursachen": ursachen,
        "fehler_liste": [list(f) for f in m.get("fehler_liste", [])],
    }


def _zahl(wert, einheit="s"):
    return "-" if wert is None else f"{wert:.1f}".replace(".", ",") + (f" {einheit}" if einheit else "")


def _speicher_text(sp):
    if not sp:
        return "-"
    art = {"gpu": "Grafikkarte", "teilweise": "teilweise Prozessor", "cpu": "Prozessor"}.get(sp["status"], "unbekannt")
    return f"{art}, {_zahl(sp['gb'], 'GB')}" if sp.get("gb") else art


def _fehler_text(e):
    if not e["fehler"]:
        return ""
    ursachen = ", ".join(f"{u}: {n}" for u, n in (e.get("fehler_ursachen") or {}).items())
    return f", {e['fehler']} Fehler" + (f" ({ursachen})" if ursachen else "")


def _qualitaet(schluessel):
    """Zeile „n von Dokumente“ - Läufe vor Schritt 4 haben keine Qualität („-“)."""
    def text(e):
        q = e.get("qualitaet")
        return "-" if not q else f"{q[schluessel]} von {e['dokumente']}"
    return text


def _satz_text(e):
    return e["satz"] + (f" ({e['pruefsumme'][:8]})" if e.get("pruefsumme") else "")


# Zeilen der Anzeige und des kopierten Textes: (Beschriftung, Ergebnis → Text)
ZEILEN = (
    ("Datum", lambda e: e["datum"]),
    ("Satz", _satz_text),
    ("Grafikkarte", lambda e: e["grafikkarte"] or "-"),
    ("Lese-Modell", lambda e: e["lesemodell"]),
    ("Zweitmeinung", lambda e: e["zweitmodell"] or "aus"),
    ("Dokumente", lambda e: f"{e['dokumente']}" + (" (abgebrochen)" if e["abgebrochen"] else "") + _fehler_text(e)),
    ("Ordner richtig (sicher)", _qualitaet("richtig")),
    ("Zum Prüfen (Rückfrage)", _qualitaet("pruefen")),
    ("Still falsch abgelegt", _qualitaet("falsch")),
    ("Datum richtig", _qualitaet("datum")),
    ("Absender richtig", _qualitaet("absender")),
    ("Sekunden je Dokument", lambda e: _zahl(e["sekunden_je_dokument"])),
    ("Dauer gesamt", lambda e: _zahl(e["minuten_gesamt"], "min")),
    ("Lesen (Median)", lambda e: _zahl(e["lesen_median"])),
    ("Zweitmeinung (Median)", lambda e: _zahl(e["zweit_median"]) + (f", {e['zweit_anzahl']} Abfragen"
                                                                  if e["zweit_anzahl"] else "")),
    ("Erster Aufruf (Laden)", lambda e: _zahl(e["lesen_erster"]) + ("" if e["kalt"] else " (war geladen)")),
    ("Modellwechsel je Stapel", lambda e: _zahl(e["wechsel_sekunden"])),
    ("Lese-Modell liegt auf", lambda e: _speicher_text(e["speicher_lesen"])),
    ("Zweitmeinung liegt auf", lambda e: _speicher_text(e["speicher_zweit"])),
    ("KID-Version", lambda e: e["version"]),
)


def wert(e, titel):
    """Text einer Zeile aus ZEILEN über ihre Beschriftung (nicht über die Position - die Liste wächst)."""
    return next(f(e) for t, f in ZEILEN if t == titel)


def als_text(e):
    """Ein Ergebnis als Text für „Ergebnis kopieren“ - nur Zahlen, Modell- und Kartennamen."""
    return "KID-Benchmark (40 Prüfdokumente)\n" + "\n".join(f"{titel}: {f(e)}" for titel, f in ZEILEN)


def gewaehlt_text(fall):
    """
    Gewählter Ordner für Liste und Protokoll. Gehört er nicht zur Prüfsammlung, hat die KI ihn angelegt - bei diesem
    oder einem früheren Brief desselben Laufs (die Ordnerliste wächst wie im Betrieb): Vermerk „(neu angelegt)“.
    Beim Absender mit vorhandenem Ordner ist das ein zweiter Ordner daneben (T21.4: „Hausarztpraxis am Markt“ wirkt
    richtiger als „Dr. Beispiel“, bis man sieht, dass es ihn in der Sammlung nicht gab). Bei einer Rückfrage wird
    nichts angelegt, also kein Vermerk. Aus dem Ordner abgeleitet, damit auch gespeicherte Läufe ihn zeigen.
    """
    ordner = fall["gewaehlt"]
    neu = fall["ergebnis"] != "pruefen" and ordner != "-" and ordner not in pruefdokumente.ordner_der_sammlung()
    return ordner + (" (neu angelegt)" if neu else "")


def protokoll_text(e):
    """Für das Protokoll: welche Briefe still falsch lagen und warum Aufrufe scheiterten - nur Prüfnummern,
    Ordner der Benchmark-Sammlung und Ursachen (Musterdaten, keine echten Inhalte)."""
    teile = []
    falsch = [f for f in e.get("faelle", []) if f["ergebnis"] == "falsch"]
    if falsch:
        teile.append("still falsch: " + ", ".join(f"Nr. {f['nr']} → {gewaehlt_text(f)} (richtig: {f['erwartet']})"
                                                 for f in falsch))
    if e.get("fehler_liste"):
        teile.append("Fehler: " + ", ".join(f"Nr. {nr} {phase}: {ursache}" for nr, phase, ursache in e["fehler_liste"]))
    return "; ".join(teile)


def lade_ergebnisse(pfad):
    """Gespeicherte Läufe, neuester zuletzt. Fehlt oder klemmt die Datei: leere Liste."""
    try:
        daten = sicher_speichern.lade_json(pfad)
    except (OSError, ValueError):
        return []
    return [e for e in daten if isinstance(e, dict)] if isinstance(daten, list) else []


def speichere_ergebnis(pfad, ergebnis):
    alle = (lade_ergebnisse(pfad) + [ergebnis])[-MAX_ERGEBNISSE:]
    os.makedirs(os.path.dirname(pfad), exist_ok=True)
    sicher_speichern.schreibe_json(pfad, alle, ensure_ascii=False, indent=1)
    return alle


def eingebauter_satz():
    """Pfad des eingebauten Satzes (im Quellcode-Betrieb `pruefsatz/` im Projekt-Root, in der EXE eingebettet)."""
    return app_paths.bundled_default_path(os.path.join(SATZ_ORDNER, SATZ_EINGEBAUT))


def satz_name(zip_pfad):
    """„gescannt niedrig“ für die bekannten Release-Zips, sonst der Dateiname ohne Endung."""
    name = os.path.basename(zip_pfad)
    return SATZ_NAMEN.get(name, os.path.splitext(name)[0])


def briefe_im_zip(pfad):
    """Wie viele Prüfbriefe (`Scan_0001.pdf` … mit gültiger Nummer) liegen im Zip? 0 bei kaputter Datei."""
    try:
        with zipfile.ZipFile(pfad) as z:
            return len({nr for n in z.namelist()
                        for nr in [nummer(n.replace("\\", "/").rsplit("/", 1)[-1])]
                        if nr is not None and 1 <= nr <= len(pruefdokumente.BRIEFE)})
    except (OSError, zipfile.BadZipFile):
        return 0


def pruefsumme(pfad):
    """SHA-256 der Zip-Datei - zwei Läufe sind nur mit derselben Summe vergleichbar."""
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        for stueck in iter(lambda: f.read(1 << 20), b""):
            h.update(stueck)
    return h.hexdigest()


def bereite_satz(zip_pfad=None):
    """
    Die Prüfbriefe aus dem Zip (Standard: der eingebaute Satz) in einen Wegwerf-Ordner entpacken. Nur Einträge
    `Scan_0001.pdf` … mit gültiger Prüfnummer; geschrieben wird unter einem aus der Nummer gebildeten Namen, nie
    unter dem Pfad aus dem Zip (kein Schreiben außerhalb des Ordners).
    :return: (ordner, [pfade] nach Prüfnummer) - Ordner danach mit raeume_satz entfernen
    :raises ValueError: keine Prüfbriefe im Zip; zipfile.BadZipFile/OSError: Datei kaputt oder fehlt
    """
    zip_pfad = zip_pfad or eingebauter_satz()
    ordner = tempfile.mkdtemp(prefix="kid_pruefdokumente_")
    try:
        pfade = {}
        with zipfile.ZipFile(zip_pfad) as z:
            for info in z.infolist():
                nr = nummer(info.filename.replace("\\", "/").rsplit("/", 1)[-1])
                if (nr is None or not 1 <= nr <= len(pruefdokumente.BRIEFE) or nr in pfade
                        or info.file_size > MAX_BRIEF_BYTES):
                    continue
                ziel = os.path.join(ordner, pruefdokumente.DATEINAME.format(nr=nr))
                with z.open(info) as quelle, open(ziel, "wb") as f:
                    shutil.copyfileobj(quelle, f)
                pfade[nr] = ziel
        if not pfade:
            raise ValueError("Im Zip liegen keine Prüfbriefe (Scan_0001.pdf …).")
    except Exception:
        raeume_satz(ordner)
        raise
    return ordner, [pfade[n] for n in sorted(pfade)]


def brief_auspacken(zip_pfad, nr):
    """
    Einen Prüfbrief zum Ansehen in einen Wegwerf-Ordner entpacken (Doppelklick in der Liste je Brief). Geschrieben
    wird wie bei bereite_satz unter einem aus der Nummer gebildeten Namen.
    :return: (ordner, pfad) - Ordner danach mit raeume_satz entfernen; (None, None), wenn der Brief im Zip fehlt
    """
    ordner = tempfile.mkdtemp(prefix="kid_pruefdokumente_")
    try:
        with zipfile.ZipFile(zip_pfad) as z:
            for info in z.infolist():
                name = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
                if nummer(name) == nr and info.file_size <= MAX_BRIEF_BYTES:
                    ziel = os.path.join(ordner, pruefdokumente.DATEINAME.format(nr=nr))
                    with z.open(info) as quelle, open(ziel, "wb") as f:
                        shutil.copyfileobj(quelle, f)
                    return ordner, ziel
    except Exception:
        raeume_satz(ordner)
        raise
    raeume_satz(ordner)
    return None, None


def satz_des_laufs(ergebnis, kandidaten):
    """Welcher Zip gehört zu diesem Lauf? Der erste vorhandene Kandidat mit derselben Prüfsumme, sonst None."""
    summe = ergebnis.get("pruefsumme")
    for pfad in kandidaten:
        if summe and pfad and os.path.isfile(pfad) and pruefsumme(pfad) == summe:
            return pfad
    return None


def raeume_satz(ordner):
    if ordner and os.path.basename(ordner).startswith("kid_pruefdokumente_"):
        shutil.rmtree(ordner, ignore_errors=True)
