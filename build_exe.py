"""
Release-Build: baut `dist/DokumentenManager.exe` mit PyInstaller und PRÜFT das Ergebnis.

Warum ein Skript statt der langen Kommandozeile im README (Praxistest 31.08.2026,
FALLSTRICKE #39): In v0.9.3 fehlten in der EXE die Tools "Dubletten finden" und
"Tags ergänzen (KI)" - der ToolManager lädt die Plugins über den Dateipfad, PyInstaller
sieht diese Importe nicht und packte deshalb weder `dubletten.py` noch die Tool-Module
als importierbare Module ein. Im Quellcode-Betrieb fällt das nie auf.

Zwei Konsequenzen, beide hier verankert:
1. `--collect-submodules tools` sammelt alle Tool-Module MIT ihren Importen ein - neue
   Tools brauchen dadurch keine neuen Flags mehr.
2. Nach dem Build wird die fertige EXE geprüft: jedes Modul der App und jedes Tool muss
   wirklich drinstecken, ebenso die mitgelieferten Vorlagen und die OCR-Sprachdaten.
   Schlägt das fehl, endet das Skript mit Exit-Code 1 - dann bitte NICHT veröffentlichen.

Aufruf:  python build_exe.py            (baut und prüft)
         python build_exe.py --pruefen  (prüft eine vorhandene dist/DokumentenManager.exe)
"""

import os
import subprocess
import sys

PROJEKT = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(PROJEKT, "src")          # App-Module liegen seit dem Aufräumen (05.09.2026) in src/
EXE = os.path.join(PROJEKT, "dist", "DokumentenManager.exe")

# Module, die nur zur Laufzeit importiert werden (Tools, Plugins) oder die PyInstaller
# sonst nicht sieht. Die Tool-Module selbst kommen über --collect-submodules tools.
HIDDEN_IMPORTS = [
    "tkinter.simpledialog",
]

# Daten, die neben dem Code ins Paket müssen (Quelle;Ziel im EXE-Paket).
# Das Ziel-Layout in der EXE bleibt flach wie vor dem src/-Umbau - zur Laufzeit
# ändert sich für app_paths (sys._MEIPASS) und tool_manager dadurch nichts.
DATEN = [
    ("src/tools", "tools"),                # der ToolManager liest den Ordner zur Laufzeit
    ("tags_default.json", "."),            # ausgelieferte Vorlage für den Tag-Katalog
    ("folder_default.json", "."),          # ausgelieferte Vorlage für die Ordnerstruktur
    ("tessdata", "tessdata"),              # OCR-Sprachdaten (FALLSTRICKE #37)
    ("build_stempel.txt", "."),            # Build-Zeitpunkt für die Titelleiste (EXE-mtime = Download-Zeit!)
    ("icon/app.ico", "icon"),              # Fenstersymbol zur Laufzeit (gui.py iconbitmap)
]


def app_module():
    """Alle App-Module in src/ (main.py, build_exe.py und testzustand.py wohnen im Root)."""
    return sorted(
        name[:-3] for name in os.listdir(SRC)
        if name.endswith(".py")
    )


def tool_module():
    """Alle Tool-Plugins als Modulnamen (tools.pdf_inspector, ...)."""
    ordner = os.path.join(SRC, "tools")
    return sorted(
        "tools." + name[:-3] for name in os.listdir(ordner)
        if name.endswith(".py") and not name.startswith("__")
    )


def baue():
    # Build-Zeitpunkt einbetten (help_window.build_stempel liest ihn aus dem Paket)
    from datetime import datetime
    with open(os.path.join(PROJEKT, "build_stempel.txt"), "w", encoding="utf-8") as f:
        f.write(datetime.now().strftime("%Y-%m-%d %H:%M"))
    befehl = [
        sys.executable, "-m", "PyInstaller",
        "--noconsole", "--onefile", "--name", "DokumentenManager", "--clean", "--noconfirm",
        "--icon", "icon/app.ico",          # Symbol der EXE-Datei im Explorer (icon/icon_erzeugen.py)
        "--paths", "src",                  # flache Modulnamen (import gui) aus src/ auflösen
        "--collect-submodules", "tools",   # Tool-Plugins samt ihrer Importe (z.B. dubletten.py)
    ]
    for quelle, ziel in DATEN:
        befehl += ["--add-data", f"{quelle};{ziel}"]
    for modul in HIDDEN_IMPORTS:
        befehl += ["--hidden-import", modul]
    befehl.append("main.py")
    print("Build:", " ".join(befehl), "\n")
    # PYTHONPATH: --paths wirkt nur auf die Import-Analyse der App; --collect-submodules
    # importiert das tools-Paket dagegen im PyInstaller-Prozess selbst - ohne src/ im
    # Suchpfad sammelt es STILL nichts ein (die Prüfung unten fängt das ab, Praxisfund
    # beim src/-Umbau 05.09.2026: 8 dynamisch geladene Tools fehlten in der EXE).
    umgebung = os.environ.copy()
    umgebung["PYTHONPATH"] = SRC + os.pathsep + umgebung.get("PYTHONPATH", "")
    ergebnis = subprocess.run(befehl, cwd=PROJEKT, env=umgebung)
    if ergebnis.returncode != 0:
        print("\nFEHLER: PyInstaller ist fehlgeschlagen.")
        sys.exit(ergebnis.returncode)


# Binär-Erweiterungen, die in der EXE stecken müssen (Mail-Import: Outlook .pst lesen, 04.11.2026)
ERWEITERUNGEN = ("pypff",)


def pruefe():
    """Liest die gebaute EXE und vergleicht ihren Inhalt mit dem Projekt."""
    from PyInstaller.archive.readers import CArchiveReader, ZlibArchiveReader

    if not os.path.exists(EXE):
        print(f"FEHLER: {EXE} nicht gefunden.")
        sys.exit(1)

    archiv = CArchiveReader(EXE)
    dateien = set(archiv.toc)
    pyz_name = next(n for n in dateien if n.lower().endswith(".pyz"))
    rohdaten = archiv.extract(pyz_name)
    if not isinstance(rohdaten, (bytes, bytearray)):   # ältere PyInstaller-Versionen: (typ, daten)
        rohdaten = rohdaten[1]
    pyz_datei = os.path.join(PROJEKT, "dist", "_pruef.pyz")
    with open(pyz_datei, "wb") as f:
        f.write(rohdaten)
    try:
        module = set(ZlibArchiveReader(pyz_datei).toc)
    finally:
        os.remove(pyz_datei)

    fehlt = []
    fehlt += [f"Modul '{m}'" for m in app_module() + tool_module() if m not in module]
    # Erweiterungen, die nur ein optionaler Import einbindet (mail_pst: try/except) - fehlen sie, merkt es sonst keiner
    fehlt += [f"Erweiterung '{e}'" for e in ERWEITERUNGEN if not any(n.lower().startswith(e) for n in dateien)]
    for quelle, ziel in DATEN:
        if os.path.isdir(os.path.join(PROJEKT, quelle)):
            # Ordner landen im Archiv unter ihrem ZIEL-Namen (z.B. src/tools -> tools\...)
            treffer = any(n.replace("/", "\\").startswith(ziel + "\\") for n in dateien)
        else:
            treffer = quelle in dateien or quelle.replace("/", "\\") in dateien
        if not treffer:
            fehlt.append(f"Daten '{quelle}'")

    groesse = os.path.getsize(EXE) / (1024 * 1024)
    if fehlt:
        print(f"\nPRÜFUNG FEHLGESCHLAGEN ({len(fehlt)} Punkt(e)) - EXE NICHT veröffentlichen:")
        for eintrag in fehlt:
            print("  fehlt:", eintrag)
        sys.exit(1)
    print(f"\nPrüfung OK: {len(app_module())} App-Module, {len(tool_module())} Tools, "
          f"alle Vorlagen und Sprachdaten enthalten ({groesse:.1f} MB).")


if __name__ == "__main__":
    if "--pruefen" not in sys.argv:
        baue()
    pruefe()
