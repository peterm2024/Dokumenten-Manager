import os
import shutil
import sys

# Zentrale Pfad-Logik für den Daten-Ordner (siehe KONZEPT_FILE_INDEX.md, Abschnitt 5.1):
# Alle sammlungs-gebundenen App-Dateien liegen in EINEM Ordner NEBEN dem Hauptordner —
# bewusst außerhalb der Watchdog-Überwachung (FALLSTRICKE #3: Rückkopplungsschleifen).
#
#   <Elternordner>/
#   ├── <Hauptordner>/        # die Dokumente (überwacht)
#   └── <Hauptordner>-Daten/  # App-Intern (nicht überwacht)
#       ├── Papierkorb/
#       ├── tags.json
#       ├── index.sqlite      # ab Phase 1
#       ├── aliase.json       # Absender-Aliase der Vollautomatik (ordner_aliase.py)
#       ├── tags_ignoriert.json  # Ignorierliste für KI-Tag-Vorschläge (tag_ignorierliste.py)
#       ├── Vollautomatik-Protokoll.txt  # eine Zeile pro automatisch abgelegtem Dokument
#       ├── wissen.sqlite     # Wiki von Hand (wissen.py)
#       └── dokumenten_manager.log
#
# Suffix bewusst OHNE App-Namen: Der Ordner steht direkt neben dem Hauptordner,
# der Kontext ist offensichtlich — und ein Hauptordner namens "KID" ergäbe sonst
# das alberne "KID-KID-Daten".
#
# Die settings.json bleibt bewusst bei der App: Sie enthält den Pfad zum Hauptordner
# und muss gefunden werden, BEVOR dieser bekannt ist (Henne-Ei).

DATA_DIR_SUFFIX = "-Daten"
TRASH_DIR_NAME = "Papierkorb"
LOG_FILE_NAME = "dokumenten_manager.log"
TAGS_FILE_NAME = "tags.json"
INDEX_FILE_NAME = "index.sqlite"
ALIASE_FILE_NAME = "aliase.json"
TAGS_IGNORIERT_FILE_NAME = "tags_ignoriert.json"
DUBLETTEN_GEPRUEFT_FILE_NAME = "dubletten_geprueft.json"
PAPIERKORB_HERKUNFT_FILE_NAME = "papierkorb_herkunft.json"
PROTOKOLL_FILE_NAME = "Vollautomatik-Protokoll.txt"
ZULETZT_BENUTZT_FILE_NAME = "zuletzt_benutzt.json"
WISSEN_FILE_NAME = "wissen.sqlite"
TESSDATA_DIR_NAME = "tessdata"


def _master_valid(master_folder):
    return bool(master_folder) and os.path.isdir(master_folder)


def data_dir(master_folder):
    """Pfad des KID-Daten-Ordners neben dem Hauptordner (ohne ihn anzulegen)."""
    master_folder = os.path.abspath(master_folder)
    parent = os.path.dirname(master_folder)
    return os.path.join(parent, os.path.basename(master_folder) + DATA_DIR_SUFFIX)


def trash_dir(master_folder):
    """Pfad des Papierkorbs innerhalb des KID-Daten-Ordners."""
    return os.path.join(data_dir(master_folder), TRASH_DIR_NAME)


def log_path(master_folder):
    """Pfad der Logdatei; ohne gültigen Hauptordner Fallback ins Arbeitsverzeichnis."""
    if not _master_valid(master_folder):
        return LOG_FILE_NAME
    return os.path.join(data_dir(master_folder), LOG_FILE_NAME)


def tags_path(master_folder):
    """Pfad der tags.json (Tag-Katalog gehört zur Sammlung); Fallback ins Arbeitsverzeichnis."""
    if not _master_valid(master_folder):
        return TAGS_FILE_NAME
    return os.path.join(data_dir(master_folder), TAGS_FILE_NAME)


def index_path(master_folder):
    """Pfad der Suchindex-Datenbank (Phase 1 des File-Index-Konzepts)."""
    return os.path.join(data_dir(master_folder), INDEX_FILE_NAME)


def aliase_path(master_folder):
    """Pfad der Absender-Alias-Datei der Vollautomatik (siehe ordner_aliase.py)."""
    return os.path.join(data_dir(master_folder), ALIASE_FILE_NAME)


def tags_ignoriert_path(master_folder):
    """Pfad der Ignorierliste für KI-Tag-Vorschläge (siehe tag_ignorierliste.py)."""
    return os.path.join(data_dir(master_folder), TAGS_IGNORIERT_FILE_NAME)


def dubletten_geprueft_path(master_folder):
    """Pfad des Dubletten-Gedächtnisses (geprüfte Paare, siehe dubletten_geprueft.py)."""
    return os.path.join(data_dir(master_folder), DUBLETTEN_GEPRUEFT_FILE_NAME)


def papierkorb_herkunft_path(master_folder):
    """Pfad des Papierkorb-Gedächtnisses (Herkunftsordner gelöschter Dateien, siehe papierkorb_herkunft.py)."""
    return os.path.join(data_dir(master_folder), PAPIERKORB_HERKUNFT_FILE_NAME)


def zuletzt_benutzt_path(master_folder):
    """Pfad der „Zuletzt benutzt“-Liste der Sammlung (siehe zuletzt_benutzt.py)."""
    return os.path.join(data_dir(master_folder), ZULETZT_BENUTZT_FILE_NAME)


def wissen_path(master_folder):
    """Pfad der Wissensbasis „Wiki von Hand“ (wissen.py, KONZEPT_WIKI_VON_HAND F3) - nicht im alten Wiki-Ordner."""
    return os.path.join(data_dir(master_folder), WISSEN_FILE_NAME)


def protokoll_path(master_folder):
    """Pfad des angehörigenfreundlichen Vollautomatik-Protokolls (siehe auto_pilot_service.py)."""
    return os.path.join(data_dir(master_folder), PROTOKOLL_FILE_NAME)


def bundled_default_path(filename):
    """
    Pfad einer mitgelieferten Vorlagen-Datei (tags_default.json, folder_default.json):
    neben dem Quellcode - bzw. in der gepackten EXE im PyInstaller-Entpackordner
    (sys._MEIPASS, per --add-data eingebettet, siehe README "Release bauen").
    Im Quellcode-Betrieb liegt der Code seit dem Aufräumen (05.09.2026) in src/,
    die Vorlagen bleiben aber im Projekt-Root - also eine Ebene über diesem Modul.
    """
    basis = getattr(sys, "_MEIPASS", None)
    if basis is None:
        basis = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(basis, filename)


def ensure_default_file(filename, logger=None):
    """
    Sorgt dafür, dass eine Vorlagen-Datei im Arbeitsverzeichnis liegt: fehlt sie dort,
    wird die mitgelieferte Kopie hingelegt (danach frei anpassbar). Praxistest 30.08.2026:
    die EXE brachte keine tags_default.json mit, also bekam der Beta-Tester nur den winzigen
    eingebauten Notfall-Katalog (Dokument -> Angebot, Rechnung) statt der ausgelieferten
    Kategorien - und die Vollautomatik hatte nichts, worin sie neue Tags einsortieren konnte.
    :return: True, wenn die Datei (jetzt) vorhanden ist
    """
    if os.path.exists(filename):
        return True
    quelle = bundled_default_path(filename)
    if not os.path.exists(quelle) or os.path.abspath(quelle) == os.path.abspath(filename):
        return False
    try:
        shutil.copyfile(quelle, filename)
        if logger:
            logger.info(f"Vorlage '{filename}' aus dem Programmpaket übernommen.")
        return True
    except OSError as e:
        if logger:
            logger.error(f"Vorlage '{filename}' konnte nicht kopiert werden: {e}")
        return False


def app_dir():
    """
    Installationsordner der App: neben main.py - bzw. neben der gepackten EXE.
    Achtung: in der EXE zeigt __file__ in den PyInstaller-Entpackordner (Temp),
    nicht dorthin, wo der Nutzer die EXE abgelegt hat (FALLSTRICKE #37).
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    # Quellcode-Betrieb: main.py liegt im Projekt-Root, dieses Modul in src/ darunter.
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def tessdata_dir():
    """
    Ordner mit den Tesseract-OCR-Sprachdaten (deu.traineddata), sammlungsUNabhängig.
    Reihenfolge: eigener 'tessdata'-Ordner neben main.py/EXE (Nutzer kann bessere
    Sprachdaten hinlegen), sonst die in der EXE eingebettete Kopie (--add-data
    "tessdata;tessdata", siehe README "Release bauen"). Liefert immer einen Pfad;
    ob er existiert, prüfen die Aufrufer mit os.path.isdir.
    """
    eigener = os.path.join(app_dir(), TESSDATA_DIR_NAME)
    if os.path.isdir(eigener):
        return eigener
    eingebettet = bundled_default_path(TESSDATA_DIR_NAME)
    return eingebettet if os.path.isdir(eingebettet) else eigener


def is_trash_path(path, master_folder):
    """
    Prüft pfadbasiert, ob eine Datei/ein Ordner im Papierkorb liegt.
    Akzeptiert absolute Pfade und Pfade relativ zum Hauptordner (wie sie in den
    Treeview-values stehen, z.B. "..\\KID-KID-Daten\\Papierkorb\\x.pdf").
    Ersetzt die früheren '"-Papierkorb" in pfad'-Stringvergleiche.
    """
    if not path or not _master_valid(master_folder):
        return False
    abs_path = os.path.abspath(os.path.join(master_folder, path))
    trash = trash_dir(master_folder)
    return os.path.normcase(abs_path).startswith(os.path.normcase(trash))


def migrate_legacy_layout(master_folder):
    """
    Zieht Altbestände in den KID-Daten-Ordner um (einmalig, nur falls das Ziel
    noch nicht existiert): alten Papierkorb <Hauptordner>-Papierkorb, Logdatei
    aus dem Elternordner und die tags.json aus dem Arbeitsverzeichnis.
    :return: Liste von Beschreibungen der durchgeführten Aktionen (fürs Log).
    """
    if not _master_valid(master_folder):
        return []

    actions = []
    target_dir = data_dir(master_folder)
    master_folder = os.path.abspath(master_folder)
    parent = os.path.dirname(master_folder)

    # Kurzlebiger Zwischenstand der Entwicklung: Falls der Daten-Ordner schon
    # unter dem alten Suffix "-KID-Daten" angelegt wurde, komplett umbenennen.
    old_data_dir = os.path.join(parent, os.path.basename(master_folder) + "-KID-Daten")
    if os.path.isdir(old_data_dir) and not os.path.exists(target_dir):
        try:
            shutil.move(old_data_dir, target_dir)
            actions.append(f"Daten-Ordner umbenannt: {old_data_dir} -> {target_dir}")
        except OSError as e:
            actions.append(f"Daten-Ordner: Umbenennung fehlgeschlagen ({e})")

    os.makedirs(target_dir, exist_ok=True)

    migrations = [
        # (alter Pfad, neuer Pfad, Beschreibung)
        (os.path.join(parent, os.path.basename(master_folder) + "-Papierkorb"),
         trash_dir(master_folder), "Papierkorb"),
        (os.path.join(parent, LOG_FILE_NAME),
         os.path.join(target_dir, LOG_FILE_NAME), "Logdatei"),
        (os.path.abspath(TAGS_FILE_NAME),
         os.path.join(target_dir, TAGS_FILE_NAME), "Tag-Katalog (tags.json)"),
    ]

    for old_path, new_path, name in migrations:
        try:
            if os.path.exists(old_path) and not os.path.exists(new_path):
                shutil.move(old_path, new_path)
                actions.append(f"{name} migriert: {old_path} -> {new_path}")
        except OSError as e:
            actions.append(f"{name}: Migration fehlgeschlagen ({e}) — alter Ort bleibt bestehen")

    return actions
