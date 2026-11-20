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
Oberfläche; das Fenster ist tools/benchmark.py.
"""
import json
import os
import shutil
import statistics
import tempfile
import time
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


def lauf(pfade, base_url, lesemodell, zweitmodell="", abbrechen=None, melde=None, lies=None, zweit=None,
         ps=ollama_client.geladene_modelle, uhr=time.monotonic):
    """
    Misst die Ablage der Dokumente `pfade` wie im Dienst (Stapel lesen → Zweitmeinungen → entscheiden).
    :param zweitmodell: Ordnerwahl-Modell, "" = ohne Zweitmeinung
    :param abbrechen: () -> True bricht nach dem laufenden Aufruf ab
    :param melde: (text, erledigt, gesamt) -> None, Fortschritt (aus dem Mess-Thread!)
    :param lies, zweit: für Tests statt auto_pilot.lies_dokument / auto_pilot.hole_zweitmeinung
    :return: Messung {"lesen": [s], "lesen_anfang": [s], "zweit": [s], "zweit_anfang": [s], "gesamt": s,
        "dokumente", "fehler", "abgebrochen", "kalt", "speicher_lesen", "speicher_zweit", "entscheidungen"}
        - *_anfang sind die ersten Aufrufe je Stapel (Laden bzw. Modellwechsel), die übrigen stehen in lesen/zweit
    """
    abbrechen = abbrechen or (lambda: False)
    melde = melde or (lambda *_: None)
    lies = lies or auto_pilot.lies_dokument
    zweit = zweit or auto_pilot.hole_zweitmeinung
    tags, kategorien = katalog()
    m = {"lesen": [], "lesen_anfang": [], "zweit": [], "zweit_anfang": [], "gesamt": 0.0, "dokumente": 0,
         "fehler": 0, "abgebrochen": False, "kalt": not geladen(base_url, lesemodell, ps),
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
                except Exception:
                    m["fehler"] += 1
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


def zusammenfassen(m, lesemodell, zweitmodell, grafikkarte, version, satz="digital", jetzt=None):
    """Messung → Ergebnis (nur Zahlen und Namen, so wird es gespeichert und kopiert)."""
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
    }


def _zahl(wert, einheit="s"):
    return "-" if wert is None else f"{wert:.1f}".replace(".", ",") + (f" {einheit}" if einheit else "")


def _speicher_text(sp):
    if not sp:
        return "-"
    art = {"gpu": "Grafikkarte", "teilweise": "teilweise Prozessor", "cpu": "Prozessor"}.get(sp["status"], "unbekannt")
    return f"{art}, {_zahl(sp['gb'], 'GB')}" if sp.get("gb") else art


# Zeilen der Anzeige und des kopierten Textes: (Beschriftung, Ergebnis → Text)
ZEILEN = (
    ("Datum", lambda e: e["datum"]),
    ("Grafikkarte", lambda e: e["grafikkarte"] or "-"),
    ("Lese-Modell", lambda e: e["lesemodell"]),
    ("Zweitmeinung", lambda e: e["zweitmodell"] or "aus"),
    ("Dokumente", lambda e: f"{e['dokumente']}" + (" (abgebrochen)" if e["abgebrochen"] else "")
     + (f", {e['fehler']} Fehler" if e["fehler"] else "")),
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


def als_text(e):
    """Ein Ergebnis als Text für „Ergebnis kopieren“ - nur Zahlen, Modell- und Kartennamen."""
    return "KID-Benchmark (40 Prüfdokumente, " + e["satz"] + ")\n" + "\n".join(
        f"{titel}: {wert(e)}" for titel, wert in ZEILEN)


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


def bereite_satz():
    """Die Prüfdokumente frisch in einen Wegwerf-Ordner schreiben. :return: (ordner, [pfade]) - Ordner danach mit
    raeume_satz entfernen"""
    ordner = tempfile.mkdtemp(prefix="kid_pruefdokumente_")
    return ordner, pruefdokumente.schreibe_satz(ordner)


def raeume_satz(ordner):
    if ordner and os.path.basename(ordner).startswith("kid_pruefdokumente_"):
        shutil.rmtree(ordner, ignore_errors=True)
