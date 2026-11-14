"""
Testzustand-Skript (Entwickler-Werkzeug, kein Teil der App).

Stellt definierte, immer gleiche Testzustände her (Nutzerwunsch 04.09.2026:
"Manuell immer einrichten kann irgendwann daneben gehen"):

    python testzustand.py status      Zeigt, was gerade gilt (nur lesend)
    python testzustand.py erststart   App startet wie beim allerersten Mal:
                                      settings.json wird gesichert und entfernt
    python testzustand.py kaltstart   KID-Test frisch aufsetzen: Testordner leeren,
                                      Daten-Ordner löschen, alle PDFs aus dem
                                      Dokumenten-ZIP in den Posteingang, Hauptordner
                                      der App auf KID-Test stellen
    python testzustand.py zurueck     settings.json aus der Sicherung zurückspielen
                                      (die Sicherung bleibt erhalten)
    python testzustand.py posteingang NUR die PDFs aus dem Dokumenten-ZIP in den
                                      Posteingang entpacken - löscht nichts, lässt
                                      settings.json in Ruhe (für Von-Null-Tests:
                                      Ordner+Settings selbst löschen, App-Erst-
                                      einrichtung durchlaufen, dann dieses Kommando)

Sicherheit: Gelöscht wird AUSSCHLIESSLICH unterhalb von KID-Test/KID-Test-Daten
(harte Pfad-Prüfung); die erste Sicherung von settings.json wird nie überschrieben.
Die App sollte während eines Zustandswechsels geschlossen sein - sie schreibt
settings.json beim Beenden und würde den Testzustand wieder überschreiben.
"""

import json
import os
import shutil
import subprocess
import sys
import zipfile

PROJEKT = os.path.dirname(os.path.abspath(__file__))
SETTINGS = os.path.join(PROJEKT, "settings.json")
SICHERUNG = os.path.join(PROJEKT, "settings.json.original")

TESTORDNER = os.path.join(os.path.expanduser("~"), "KID-Test")
POSTEINGANG = os.path.join(TESTORDNER, "0_Posteingang")

# Das Archiv mit den echten Test-Dokumenten (Original der Sammlung eines Beta-Testers,
# Stand 04.09.2026: 403 PDFs in Ordnerstruktur). .7z braucht das installierte 7-Zip.
DOKUMENTE_ZIP = os.path.join(os.path.expanduser("~"), "Documents", "Digital.7z")
SIEBEN_ZIP = r"C:\Program Files\7-Zip\7z.exe"


def _daten_ordner():
    return TESTORDNER + "-Daten"


def _pruefe_testpfad(pfad):
    """Harte Sicherung: gelöscht wird nur, was eindeutig zum Testbestand gehört."""
    name = os.path.basename(pfad.rstrip("\\/"))
    if name not in ("KID-Test", "KID-Test-Daten"):
        sys.exit(f"ABBRUCH: '{pfad}' ist kein KID-Test-Pfad - hier wird nichts gelöscht.")


def _lies_settings(pfad):
    try:
        with open(pfad, encoding="utf-8") as f:
            daten = json.load(f)
        return daten if isinstance(daten, dict) else {}
    except (OSError, json.JSONDecodeError, ValueError):
        return {}


def _sichere_settings():
    """Erste Sicherung anlegen; eine vorhandene Sicherung ist das Original und bleibt."""
    if os.path.exists(SETTINGS) and not os.path.exists(SICHERUNG):
        shutil.copy2(SETTINGS, SICHERUNG)
        print(f"Sicherung angelegt: {SICHERUNG}")


def status():
    print(f"settings.json:  {'vorhanden' if os.path.exists(SETTINGS) else 'FEHLT (Erststart-Zustand)'}")
    if os.path.exists(SETTINGS):
        print(f"  master_folder: {_lies_settings(SETTINGS).get('master_folder', '(leer)')}")
    print(f"Sicherung:      {'vorhanden' if os.path.exists(SICHERUNG) else 'keine'}")
    if os.path.exists(SICHERUNG):
        print(f"  master_folder: {_lies_settings(SICHERUNG).get('master_folder', '(leer)')}")
    if os.path.isdir(TESTORDNER):
        pdfs = sum(len([f for f in files if f.lower().endswith('.pdf')])
                   for _, _, files in os.walk(TESTORDNER))
        eingang = len([f for f in os.listdir(POSTEINGANG) if f.lower().endswith('.pdf')]) \
            if os.path.isdir(POSTEINGANG) else 0
        print(f"KID-Test:       {pdfs} PDFs gesamt, davon {eingang} im Posteingang")
    else:
        print("KID-Test:       existiert nicht")
    print(f"Daten-Ordner:   {'vorhanden' if os.path.isdir(_daten_ordner()) else 'keiner'}")
    print(f"Dokumenten-ZIP: {DOKUMENTE_ZIP or '(noch nicht eingetragen - Konstante DOKUMENTE_ZIP)'}")


def erststart():
    _sichere_settings()
    if os.path.exists(SETTINGS):
        os.remove(SETTINGS)
        print("settings.json entfernt - die App startet jetzt wie beim allerersten Mal.")
    else:
        print("settings.json fehlt bereits - Erststart-Zustand steht schon.")
    kid = os.path.join(os.path.expanduser("~"), "Documents", "KID")
    print(f"ACHTUNG: Die Ersteinrichtung der App legt bei 'Ja' den Ordner '{kid}' an")
    print("und macht ihn zum Hauptordner (Live-Fund 04.09.2026: alter Inhalt dort")
    print("mischt sich sonst hinein - die App warnt inzwischen, wenn er nicht leer ist).")
    if os.path.isdir(kid) and os.listdir(kid):
        print(f"  -> '{kid}' existiert bereits und ist NICHT leer ({len(os.listdir(kid))} Einträge)!")


def zurueck():
    if not os.path.exists(SICHERUNG):
        sys.exit(f"Keine Sicherung gefunden ({SICHERUNG}) - nichts zurückzuspielen.")
    shutil.copy2(SICHERUNG, SETTINGS)
    print(f"settings.json aus der Sicherung zurückgespielt (master_folder: "
          f"{_lies_settings(SETTINGS).get('master_folder', '(leer)')}).")


def _entpacke_posteingang():
    """Alle PDFs aus dem Dokumenten-ZIP FLACH in den Posteingang (Ordnerstruktur im
    Archiv egal); Namenskollisionen werden umbenannt statt überschrieben."""
    if not DOKUMENTE_ZIP:
        sys.exit("Bitte zuerst den Pfad zum Dokumenten-ZIP in der Konstante DOKUMENTE_ZIP eintragen.")
    if not os.path.exists(DOKUMENTE_ZIP):
        sys.exit(f"Dokumenten-ZIP nicht gefunden: {DOKUMENTE_ZIP}")
    os.makedirs(POSTEINGANG, exist_ok=True)
    if DOKUMENTE_ZIP.lower().endswith(".7z"):
        if not os.path.exists(SIEBEN_ZIP):
            sys.exit(f"7-Zip nicht gefunden: {SIEBEN_ZIP}")
        # 'e' = flach entpacken, '-aou' = bei gleichem Namen automatisch umbenennen
        ergebnis = subprocess.run(
            [SIEBEN_ZIP, "e", DOKUMENTE_ZIP, f"-o{POSTEINGANG}", "*.pdf", "-r", "-aou", "-y"],
            capture_output=True, text=True)
        if ergebnis.returncode != 0:
            sys.exit(f"7-Zip-Fehler:\n{ergebnis.stdout}\n{ergebnis.stderr}")
    else:
        with zipfile.ZipFile(DOKUMENTE_ZIP) as archiv:
            for eintrag in archiv.namelist():
                if not eintrag.lower().endswith(".pdf"):
                    continue
                name = os.path.basename(eintrag)
                ziel = os.path.join(POSTEINGANG, name)
                zaehler = 0
                while os.path.exists(ziel):
                    zaehler += 1
                    stamm, endung = os.path.splitext(name)
                    ziel = os.path.join(POSTEINGANG, f"{stamm}_{zaehler:03d}{endung}")
                with archiv.open(eintrag) as quelle, open(ziel, "wb") as f:
                    shutil.copyfileobj(quelle, f)
    anzahl = len([f for f in os.listdir(POSTEINGANG) if f.lower().endswith(".pdf")])
    print(f"{anzahl} PDFs im Posteingang ({POSTEINGANG}).")


def posteingang():
    """Von-Null-Test (Nutzerwunsch 04.09.2026): Peter löscht KID-Test und settings.json
    selbst, lässt die App-Ersteinrichtung die Struktur anlegen - dieses Kommando füllt
    danach NUR den Posteingang. Es löscht nichts und fasst settings.json nicht an."""
    _entpacke_posteingang()
    print("Nichts gelöscht, settings.json unangetastet.")


def kaltstart():
    if not DOKUMENTE_ZIP:
        sys.exit("Bitte zuerst den Pfad zum Dokumenten-ZIP in der Konstante DOKUMENTE_ZIP eintragen.")
    if not os.path.exists(DOKUMENTE_ZIP):
        sys.exit(f"Dokumenten-ZIP nicht gefunden: {DOKUMENTE_ZIP}")

    _pruefe_testpfad(TESTORDNER)
    _pruefe_testpfad(_daten_ordner())
    _sichere_settings()

    for pfad in (TESTORDNER, _daten_ordner()):
        if os.path.isdir(pfad):
            shutil.rmtree(pfad)
            print(f"geleert: {pfad}")
    os.makedirs(POSTEINGANG)

    # Standard-Registerstruktur wie in der App (folder_default.json) - ohne sie hatte
    # Lauf 3 am 04.09.2026 KEINE vorhandenen Ordner und schlug alles als "(neu)" vor;
    # damit war der Lauf nicht mit Lauf 1/2 vergleichbar.
    struktur_datei = os.path.join(PROJEKT, "folder_default.json")
    try:
        struktur = _lies_settings(struktur_datei)  # liest beliebiges JSON-Dict
    except Exception:
        struktur = {}
    if not struktur:
        struktur = {"0_Unsicher": {}, "[0-9]": {}, "A - B - C - D - E": {},
                    "F - G - H - I - J": {"Finanzamt": {}}, "K - L - M - N - O": {"Krankenkasse": {}},
                    "P - Q - R - S - T": {"Stadtwerke": {}}, "U - V - W - X - Y - Z": {}}

    def _baue(basis, knoten):
        if isinstance(knoten, dict):
            for name, unter in knoten.items():
                if "posteingang" in name.lower():
                    continue  # Posteingang existiert schon
                os.makedirs(os.path.join(basis, name), exist_ok=True)
                _baue(os.path.join(basis, name), unter)
        elif isinstance(knoten, list):
            for name in knoten:
                os.makedirs(os.path.join(basis, name), exist_ok=True)
    _baue(TESTORDNER, struktur)
    print("Standard-Registerstruktur angelegt.")

    _entpacke_posteingang()

    # Hauptordner auf KID-Test stellen; alle übrigen Einstellungen (Ollama-Server,
    # Fensterlage ...) bleiben, wie sie sind - Basis ist die Sicherung bzw. der Ist-Stand.
    basis = _lies_settings(SETTINGS) or _lies_settings(SICHERUNG)
    basis["master_folder"] = TESTORDNER.replace("\\", "/")
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(basis, f, indent=4, ensure_ascii=False)
    print(f"Hauptordner der App: {basis['master_folder']}")
    print("Kaltstart-Zustand steht - App starten und 'Posteingang verarbeiten' ausführen.")


if __name__ == "__main__":
    befehle = {"status": status, "erststart": erststart, "kaltstart": kaltstart, "zurueck": zurueck,
               "posteingang": posteingang}
    wahl = sys.argv[1] if len(sys.argv) > 1 else ""
    if wahl not in befehle:
        print(__doc__)
        sys.exit(1)
    befehle[wahl]()
