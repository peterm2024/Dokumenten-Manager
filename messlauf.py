"""
Messlauf mit Leistungsbudgets (01.11.2026, Anregung aus storytold/photocraft `cargo xtask perf`).

Startet die echte Oberfläche mit der künstlichen Sammlung KID-S4 (Einstellungs-Kopie im Arbeitsordner,
Peters settings.json und KID-Test bleiben unberührt), misst die Szenarien aus messlauf_budgets.toml und
vergleicht mit messlauf_vergleich.json. Ein Rückschritt lässt den Lauf mit Code 1 enden.

    python messlauf.py                        # messen und vergleichen
    python messlauf.py --vergleich-speichern  # Ergebnis als neue Vergleichswerte (nur auf ruhigem Rechner)
    python messlauf.py --sammlung D:\\KID-S4   # andere Sammlung (muss KID-S4… heißen)

Die Oberfläche erscheint kurz auf dem Bildschirm; Maus und Tastatur werden nicht benutzt.
"""
import contextlib
import ctypes
import ctypes.wintypes
import datetime
import io
import json
import os
import shutil
import statistics
import sys
import time
import tomllib

PROJEKT = os.path.dirname(os.path.abspath(__file__))
BUDGETS = os.path.join(PROJEKT, "messlauf_budgets.toml")
VERGLEICH = os.path.join(PROJEKT, "messlauf_vergleich.json")
STANDARD_SAMMLUNG = os.path.join(os.path.expanduser("~"), "KID-S4")


# ---------------------------------------------------------------- reine Auswertung (getestet)

def bewerte(name, werte, szenario, vergleich, einstellungen):
    """
    Ein Szenario bewerten. :param werte: gemessene Sekunden (eine je Wiederholung)
    :return: dict median, budget, ueber_budget, pflicht, vergleich, rueckschritt
    """
    median = statistics.median(werte)
    budget = szenario.get("budget_s")
    alt = (vergleich or {}).get(name)
    rueckschritt = bool(
        alt is not None
        and median > alt * (1 + einstellungen["rueckschritt_prozent"] / 100)
        and median - alt > einstellungen["rueckschritt_min_s"])
    return {"median": median, "budget": budget, "ueber_budget": budget is not None and median > budget,
            "pflicht": bool(szenario.get("pflicht")), "vergleich": alt, "rueckschritt": rueckschritt}


def gescheitert(ergebnisse):
    """Namen der Szenarien, die den Lauf scheitern lassen: Rückschritt oder Pflicht-Budget gerissen."""
    return [n for n, e in ergebnisse.items() if e["rueckschritt"] or (e["pflicht"] and e["ueber_budget"])]


def zeile(name, szenario, e):
    alt = f"{e['vergleich']:6.2f}" if e["vergleich"] is not None else "     -"
    merk = []
    if e["rueckschritt"]:
        merk.append("RÜCKSCHRITT")
    if e["ueber_budget"]:
        merk.append("über Budget (Pflicht)" if e["pflicht"] else "über Budget")
    return f"{szenario.get('text', name):58} {e['median']:6.2f} s  Vergleich {alt}  Budget {e['budget']:5.2f}  {' '.join(merk)}"


# ---------------------------------------------------------------- Rechner-Last

class _FILETIME(ctypes.Structure):
    _fields_ = [("lo", ctypes.wintypes.DWORD), ("hi", ctypes.wintypes.DWORD)]


def cpu_last_prozent(dauer=1.0):
    """Mittlere CPU-Last über `dauer` Sekunden (GetSystemTimes), None außerhalb von Windows."""
    try:
        holen = ctypes.windll.kernel32.GetSystemTimes
    except AttributeError:
        return None

    def jetzt():
        leer, kern, nutzer = _FILETIME(), _FILETIME(), _FILETIME()
        holen(ctypes.byref(leer), ctypes.byref(kern), ctypes.byref(nutzer))
        return [(t.hi << 32) | t.lo for t in (leer, kern, nutzer)]

    a = jetzt()
    time.sleep(dauer)
    b = jetzt()
    leer, gesamt = b[0] - a[0], (b[1] - a[1]) + (b[2] - a[2])  # Kernzeit enthält die Leerlaufzeit
    return 100.0 * (1 - leer / gesamt) if gesamt else None


# ---------------------------------------------------------------- Messung in der echten Oberfläche

def _vorbereiten(sammlung, arbeit):
    os.makedirs(arbeit, exist_ok=True)
    quelle = os.path.join(PROJEKT, ".fernsteuerung", "settings.json")
    einstellungen = {}
    if os.path.exists(quelle):
        with open(quelle, encoding="utf-8") as f:
            einstellungen = json.load(f)
    einstellungen.update({"master_folder": sammlung.replace("\\", "/"), "show_help_on_start": False,
                          "versionspruefung_beim_start": False, "auto_pilot_enabled": False,
                          "kurzbefehle_anzeigen": False})
    with open(os.path.join(arbeit, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(einstellungen, f, ensure_ascii=False, indent=2)
    for vorlage in ("tags_default.json", "folder_default.json"):
        shutil.copyfile(os.path.join(PROJEKT, vorlage), os.path.join(arbeit, vorlage))
    os.chdir(arbeit)
    sys.path.insert(0, os.path.join(PROJEKT, "src"))


def messe(sammlung, wiederholungen):
    """{szenario: [Sekunden, …]} aus der echten Oberfläche."""
    import tkinter as tk
    leise = io.StringIO()
    werte = {}

    t0 = time.perf_counter()
    with contextlib.redirect_stdout(leise):
        import gui
        root = tk.Tk()
        app = gui.DokumentenVerwaltung(root)
        root.update()
    werte["start"] = [time.perf_counter() - t0]
    if os.path.normcase(os.path.abspath(app.master_folder)) != os.path.normcase(os.path.abspath(sammlung)):
        raise RuntimeError(f"falsche Sammlung geöffnet: {app.master_folder}")

    baum = app.tree_folders

    def alle(eltern=""):
        for k in baum.get_children(eltern):
            yield k
            yield from alle(k)

    def knoten(pfad):
        ziel = os.path.normcase(os.path.abspath(pfad))
        return next(k for k in alle() if baum.item(k, "values")
                    and os.path.normcase(os.path.abspath(baum.item(k, "values")[0])) == ziel)

    def oeffne(k):
        with contextlib.redirect_stdout(leise):
            baum.selection_remove(baum.selection())
            root.update()
            t = time.perf_counter()
            baum.selection_set(k)
            root.update()
            return time.perf_counter() - t

    absender = sorted(((len([f for f in fs if f.endswith(".pdf")]), w) for w, _, fs in os.walk(sammlung)
                       if os.path.dirname(w) != sammlung and w != sammlung), reverse=True)
    posteingang, groesster = knoten(os.path.join(sammlung, "0_Posteingang")), knoten(absender[0][1])
    for name, k in (("ordner_posteingang", posteingang), ("ordner_groesster", groesster)):
        werte[name] = [oeffne(k) for _ in range(wiederholungen)]

    def suche(text, volltext):
        with contextlib.redirect_stdout(leise):
            app.search_manager.reset_search()  # jede Messung baut die Trefferliste neu auf
            root.update()
            app.use_ocr_var.set(volltext)
            app.entry_search.delete(0, tk.END)
            app.entry_search.insert("end", text)  # SuchFeld ist ein tk.Text - Index "0" gibt es dort nicht
            t = time.perf_counter()
            app.search_manager.apply_filters()
            root.update()
            return time.perf_counter() - t

    werte["volltext_erste"] = [suche("Rechnung", True)]
    for name, text, volltext in (("suche_ohne_volltext", "Rechnung", False), ("volltext_haeufig", "Rechnung", True),
                                 ("volltext_tippfehler", "Rechnnug", True), ("volltext_selten", "VG-012345", True),
                                 ("volltext_nichts", "Xylophon", True)):
        werte[name] = [suche(text, volltext) for _ in range(wiederholungen)]

    with contextlib.redirect_stdout(leise):
        app.search_manager.reset_search()
        app.on_closing()
    return werte


def main(argv):
    with open(BUDGETS, "rb") as f:
        budgets = tomllib.load(f)
    einstellungen, szenarien = budgets["einstellungen"], budgets["szenario"]
    sammlung = STANDARD_SAMMLUNG
    if "--sammlung" in argv:
        sammlung = argv[argv.index("--sammlung") + 1]
    if not os.path.basename(os.path.normpath(sammlung)).startswith("KID-S4") or not os.path.isdir(sammlung):
        print(f"ABBRUCH: Messlauf nur mit einer künstlichen Sammlung KID-S4… ({sammlung})")
        return 2
    speichern = "--vergleich-speichern" in argv

    last = cpu_last_prozent()
    belastet = last is not None and last > einstellungen["max_cpu_last_prozent"]
    print(f"CPU-Last vor dem Lauf: {last:.0f} %" + ("  (belastet - Werte unsicher)" if belastet else ""))
    if speichern and belastet:
        print("ABBRUCH: Rechner zu beschäftigt, Vergleichswerte werden so nicht gespeichert.")
        return 2

    arbeit = os.path.join(os.environ.get("TEMP", PROJEKT), "kid_messlauf")
    _vorbereiten(sammlung, arbeit)
    werte = messe(sammlung, einstellungen["wiederholungen"])

    vergleich = {}
    if os.path.exists(VERGLEICH):
        with open(VERGLEICH, encoding="utf-8") as f:
            vergleich = json.load(f).get("werte", {})
    ergebnisse = {n: bewerte(n, werte[n], szenarien[n], vergleich, einstellungen) for n in szenarien if n in werte}
    print()
    for n, e in ergebnisse.items():
        print(zeile(n, szenarien[n], e))
    fehlend = sorted(set(szenarien) - set(werte))
    if fehlend:
        print("nicht gemessen:", ", ".join(fehlend))

    if speichern:
        with open(VERGLEICH, "w", encoding="utf-8") as f:
            json.dump({"stand": datetime.datetime.now().isoformat(timespec="minutes"), "sammlung": sammlung.replace(os.path.expanduser("~"), "~"),
                       "cpu_last_prozent": round(last or 0), "werte": {n: round(e["median"], 3)
                                                                       for n, e in ergebnisse.items()}},
                      f, ensure_ascii=False, indent=2)
        print(f"\nVergleichswerte gespeichert: {VERGLEICH}")
    schlecht = gescheitert(ergebnisse)
    print("\nERGEBNIS:", "gescheitert - " + ", ".join(schlecht) if schlecht else "ok")
    return 1 if schlecht else 0


if __name__ == "__main__":
    try:
        code = main(sys.argv[1:])
    except Exception:
        # nicht bis zu KIDs Fehlerfänger durchlassen - der zeigt sonst einen Dialog auf dem Bildschirm
        import traceback
        traceback.print_exc(file=sys.__stdout__)
        code = 3
    sys.stdout.flush()
    os._exit(code)  # Watchdog-/Status-Threads nicht abwarten
