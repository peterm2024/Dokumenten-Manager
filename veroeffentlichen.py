"""
Release ins öffentliche Repo bringen (14.09.2026), seit 14.11.2026 mit Quellcode-Spiegel (Etappe 8).

Der Quellcode entsteht im privaten Repo peterm2024/Dokumenten-Manager-dev, die Nutzer sehen
das öffentliche Repo peterm2024/Dokumenten-Manager (lokaler Klon: ../Dokumenten-Manager-public).
Dieses Skript hält beide zusammen:

    python veroeffentlichen.py v0.9.18 release_notes.md "v0.9.18 - Kurztitel"
    python veroeffentlichen.py --spiegel        # nur den Quellcode-Spiegel füllen, kein Release
    python veroeffentlichen.py --probe          # nur prüfen und zählen, nichts schreiben

1. Spiegel: nimmt den COMMITTETEN Stand (HEAD) des privaten Repos, lässt die privaten Arbeitsnotizen
   weg (PRIVAT) und prüft jede Datei gegen die private Begriffsliste (BEGRIFFE, liegt bewusst nicht im
   Repo). Eine einzige Fundstelle bricht ab, bevor irgendetwas geschrieben wird. Danach ersetzt der Stand
   den Inhalt des öffentlichen Klons; dessen README.md (Nutzer-Startseite) bleibt, die Entwickler-README
   heißt dort ENTWICKLER.md.
2. committet und pusht dort,
3. legt das GitHub-Release mit dist/DokumentenManager.exe, dem Lizenztext (LICENSE.txt - die AGPL verlangt ihn
   bei jeder Weitergabe, die EXE selbst bringt ihn nicht mit) und den Notizen an. Das „Source code“-Zip,
   das GitHub jedem Release anhängt, enthält damit genau den Quellcode der EXE.

Voraussetzungen: `python build_exe.py` ist gelaufen (dist/DokumentenManager.exe frisch),
Version und CHANGELOG sind im privaten Repo committet und der Tag ist gesetzt.
"""

import io
import os
import re
import shutil
import subprocess
import sys
import tarfile

HIER = os.path.dirname(os.path.abspath(__file__))
OEFFENTLICH = os.path.join(os.path.dirname(HIER), "Dokumenten-Manager-public")
REPO = "peterm2024/Dokumenten-Manager"
EXE = os.path.join(HIER, "dist", "DokumentenManager.exe")
# Private Liste echter Namen/Orte/Firmen (ein Regex je Zeile) - dieselbe liest tests/test_help_window.py
BEGRIFFE = os.path.join(os.path.expanduser("~"), "KID-Messungen", "release_check", "begriffe.txt")

# Arbeitsnotizen bleiben privat (Entscheidung E2, FAHRPLAN Etappe 8). Vergleich über den Pfadanfang.
PRIVAT = ("FAHRPLAN.md", "MANUELLE_TESTS", "ARCHITEKTUR_REVIEW.md", "ToDo.txt", "CLAUDE.md", "KONZEPT_",
          "Modellradar", "spikes/", "docs/tests.md")
UMBENENNEN = {"README.md": "ENTWICKLER.md"}     # die README.md des öffentlichen Repos ist die Nutzer-Startseite
NUR_OEFFENTLICH = ("README.md",)                # gehört dem öffentlichen Klon, der Spiegel fasst sie nicht an


def ist_oeffentlich(pfad):
    """True, wenn eine Datei des privaten Repos in den Spiegel gehört."""
    return not pfad.startswith(PRIVAT)


def zielpfad(pfad):
    return UMBENENNEN.get(pfad, pfad)


def _link_auf_privates(treffer):
    ziel = treffer.group(2)
    return treffer.group(1) if ziel.startswith(PRIVAT) else treffer.group(0)


def anpassen(pfad, text):
    """Die wenigen Stellen, die auf weggelassene oder umbenannte Dateien zeigen, für den Spiegel richten.
    Markdown-Links auf private Dateien werden zu schlichtem Text (sonst tote Links auf GitHub)."""
    if pfad.endswith(".md"):
        text = re.sub(r"\[([^\]]+)\]\(([^)#\s]+)(?:#[^)]*)?\)", _link_auf_privates, text)
    if pfad == "docs/index.md":
        text = text.replace('"../README.md"', '"../ENTWICKLER.md"')
    elif pfad == "mkdocs.yml":
        text = "".join(z for z in text.splitlines(keepends=True) if not z.strip().endswith(": tests.md"))
    return text


def lade_begriffe(pfad=BEGRIFFE):
    """Die private Begriffsliste. Fehlt sie, gibt es keinen Spiegel (lieber gar nicht als ungeprüft)."""
    if not os.path.isfile(pfad):
        sys.exit(f"Begriffsliste fehlt: {pfad} - ohne Prüfung wird nichts veröffentlicht.")
    with open(pfad, encoding="utf-8") as f:
        return [re.compile(z.strip()) for z in f if z.strip() and not z.startswith("#")]


def fundstellen(pfad, text, regeln):
    """[(Zeile, Begriffsnummer)] - nie den Text selbst, damit keine Ausgabe die echten Namen zeigt.
    Zeilen mit „Copyright“ sind ausgenommen: der Urheber-Vermerk nennt bewusst den vollen Namen (E5)."""
    treffer = [(0, i) for i, rx in enumerate(regeln, 1) if rx.search(pfad)]
    for nr, zeile in enumerate(text.splitlines(), 1):
        if "Copyright" in zeile:
            continue
        treffer += [(nr, i) for i, rx in enumerate(regeln, 1) if rx.search(zeile)]
    return treffer


def tote_einbindungen(dateien):
    """mkdocs-Einbindungen und Nav-Einträge, die im Spiegel ins Leere zeigen würden."""
    tot = []
    for pfad, inhalt in dateien.items():
        if pfad.startswith("docs/") and pfad.endswith(".md"):
            for ziel in re.findall(r'include-markdown\s+"([^"]+)"', inhalt.decode("utf-8")):
                if os.path.normpath(os.path.join("docs", ziel)).replace("\\", "/") not in dateien:
                    tot.append(f"{pfad} -> {ziel}")
    nav = dateien.get("mkdocs.yml", b"").decode("utf-8")
    for ziel in re.findall(r":\s*(\S+\.md)\s*$", nav, re.M):
        if "docs/" + ziel not in dateien:
            tot.append(f"mkdocs.yml -> {ziel}")
    return tot


def spiegel_stand(stand="HEAD"):
    """{Zielpfad: bytes} aus dem committeten Stand (HEAD) des privaten Repos, schon angepasst.
    ``stand`` darf jeder Commit sein - Probeläufe nehmen `git stash create` (Arbeitsstand, nichts committet)."""
    tar = subprocess.run(["git", "archive", "--format=tar", stand], cwd=HIER, capture_output=True, check=True).stdout
    dateien = {}
    with tarfile.open(fileobj=io.BytesIO(tar)) as archiv:
        for eintrag in archiv:
            if not eintrag.isfile() or not ist_oeffentlich(eintrag.name):
                continue
            inhalt = archiv.extractfile(eintrag).read()
            if eintrag.name.endswith(".md") or eintrag.name == "mkdocs.yml":
                inhalt = anpassen(eintrag.name, inhalt.decode("utf-8")).encode("utf-8")
            dateien[zielpfad(eintrag.name)] = inhalt
    return dateien


def als_text(inhalt):
    """Jede lesbare Datei als Text, egal welche Endung (UTF-16 mit BOM eingeschlossen). Bilder/Icons: ""
    - bei ihnen wird nur der Dateiname geprüft."""
    if inhalt.startswith((b"\xff\xfe", b"\xfe\xff")):
        return inhalt.decode("utf-16", errors="replace")
    try:
        return inhalt.decode("utf-8")
    except UnicodeDecodeError:
        return ""


def pruefe_stand(dateien, regeln):
    """Gesamtzahl der Fundstellen; je betroffener Datei eine Zeile mit Zeilen- und Begriffsnummern."""
    summe = 0
    for pfad in sorted(dateien):
        text = als_text(dateien[pfad])
        treffer = fundstellen(pfad, text, regeln)
        if treffer:
            summe += len(treffer)
            print(f"   {pfad}: " + " ".join(f"{z}:B{b}" for z, b in treffer)[:200])
    return summe


def spiegel_fuellen(nur_pruefen=False):
    """Schritt 1. Bricht bei Fundstellen oder toten Einbindungen ab, bevor etwas geschrieben wird."""
    dateien = spiegel_stand()
    regeln = lade_begriffe()
    funde = pruefe_stand(dateien, regeln)
    for name in NUR_OEFFENTLICH:          # die Nutzer-README geht mit dem Commit ebenfalls hinaus
        pfad = os.path.join(OEFFENTLICH, name)
        if os.path.isfile(pfad):
            with open(pfad, "rb") as f:
                funde += pruefe_stand({name + " (öffentlicher Klon)": f.read()}, regeln)
    tot = tote_einbindungen(dateien)
    for t in tot:
        print("   tote Einbindung:", t)
    print(f"   {len(dateien)} Dateien, {funde} Fundstellen, {len(tot)} tote Einbindungen")
    if funde or tot:
        sys.exit("Spiegel abgebrochen - erst im privaten Repo bereinigen und committen.")
    if nur_pruefen:
        return
    alt = subprocess.run(["git", "ls-files"], cwd=OEFFENTLICH, capture_output=True, text=True,
                         encoding="utf-8", check=True).stdout.splitlines()
    for pfad in alt:
        if pfad not in dateien and pfad not in NUR_OEFFENTLICH:
            os.remove(os.path.join(OEFFENTLICH, pfad))
    for pfad, inhalt in dateien.items():
        ziel = os.path.join(OEFFENTLICH, pfad)
        os.makedirs(os.path.dirname(ziel), exist_ok=True)
        with open(ziel, "wb") as f:
            f.write(inhalt)


def pruefe_notizen(notizen, titel, regeln=None):
    """Release-Text und -Titel landen direkt auf GitHub - dieselbe Prüfung wie der Spiegel (FALLSTRICKE #128)."""
    with open(notizen, encoding="utf-8") as f:
        text = titel + "\n" + f.read()
    treffer = fundstellen("", text, regeln if regeln is not None else lade_begriffe())
    if treffer:
        print("   Release-Notizen: " + " ".join(f"{z}:B{b}" for z, b in treffer)[:200])
        sys.exit("Release abgebrochen - die Notizen enthalten einen Begriff aus der privaten Liste.")


def lauf(befehl, cwd):
    print("  >", " ".join(befehl))
    subprocess.run(befehl, cwd=cwd, check=True)


def commit_und_push(nachricht):
    lauf(["git", "add", "-A"], OEFFENTLICH)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=OEFFENTLICH, capture_output=True, text=True).stdout
    if status.strip():
        lauf(["git", "commit", "-q", "-m", nachricht], OEFFENTLICH)
    else:
        print("   nichts zu committen")
    lauf(["git", "push", "-q", "origin", "HEAD"], OEFFENTLICH)


def main():
    if not os.path.isdir(os.path.join(OEFFENTLICH, ".git")):
        sys.exit(f"Öffentlicher Klon fehlt: {OEFFENTLICH}  (git clone https://github.com/{REPO}.git)")
    stand = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HIER, capture_output=True, text=True,
                           check=True).stdout.strip()
    if len(sys.argv) == 2 and sys.argv[1] in ("--probe", "--spiegel"):
        print(f"1. Quellcode-Spiegel (Stand {stand}) {'prüfen' if sys.argv[1] == '--probe' else 'füllen'}")
        spiegel_fuellen(nur_pruefen=sys.argv[1] == "--probe")
        if sys.argv[1] == "--spiegel":
            print("2. Commit und Push im öffentlichen Repo")
            commit_und_push(f"Quellcode-Stand {stand}")
        return
    if len(sys.argv) not in (3, 4) or not sys.argv[1].startswith("v"):
        sys.exit("Aufruf: python veroeffentlichen.py v<Version> <Notizen.md> [\"Titel\"]  |  --spiegel  |  --probe")
    version, notizen = sys.argv[1], os.path.abspath(sys.argv[2])
    titel = sys.argv[3] if len(sys.argv) == 4 else version
    if not os.path.isfile(EXE):
        sys.exit(f"EXE fehlt: {EXE}  (erst python build_exe.py)")
    if not os.path.isfile(notizen):
        sys.exit(f"Notizen fehlen: {notizen}")
    pruefe_notizen(notizen, titel)

    print(f"1. Quellcode-Spiegel (Stand {stand}) nach {OEFFENTLICH}")
    spiegel_fuellen()

    print("2. Commit und Push im öffentlichen Repo")
    commit_und_push(f"Release {version}: Quellcode, Leitfaden, Changelog")

    print(f"3. GitHub-Release {version} in {REPO}")
    lizenz = os.path.join(os.path.dirname(EXE), "LICENSE.txt")    # .txt: unter Windows per Doppelklick lesbar
    shutil.copyfile(os.path.join(HIER, "LICENSE"), lizenz)
    lauf(["gh", "release", "create", version, EXE, lizenz, "-R", REPO, "--title", titel, "--notes-file", notizen], HIER)
    print("fertig:", f"https://github.com/{REPO}/releases/tag/{version}")


if __name__ == "__main__":
    main()
