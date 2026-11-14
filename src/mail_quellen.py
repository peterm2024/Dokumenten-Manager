"""
Mail-Quellen-Assistent (KONZEPT_MAIL_IMPORT.md, Schritt 3a, Spike S5): findet die Mail-Programme des Rechners und
kopiert die gewählten Mail-Dateien in einen eigenen Ordner. Der Import arbeitet danach nur noch auf der Kopie.

Oberste Regel: Das Mail-Programm und seine Dateien werden unter keinen Umständen beeinflusst. Originale werden nur
lesend geöffnet, KID schreibt nichts in ihre Ordner, ändert nichts in der Registrierung und startet oder beendet kein
Mail-Programm. Kopiert wird nach Positivliste: nur Mail-Dateien, nie Dateien mit Zugangsdaten.

Die Suche liest nur Einstellungsdateien, Größen und die ersten Bytes, keine Mails. Sie prüft bekannte Orte und
durchsucht nicht die Platte; darum kann sie beim Öffnen des Fensters laufen (E14).

GUI-frei, nur Standardbibliothek und mail_lesen. Ins Protokoll gehören höchstens Zahlen und Programmnamen.
"""

import configparser
import ctypes
import hashlib
import json
import os
import re
import shutil
import sys

import mail_lesen

THUNDERBIRD, OUTLOOK = "Thunderbird", "Outlook"

MARKE = "KID-Mail-Kopie.json"              # nur ein Ordner mit dieser Datei wird je gelöscht
KOPIE_UNTERORDNER = "KID-Mail-Kopie"       # wenn der Nutzer selbst einen Ordner wählt
KOPIER_VERSUCHE = 3
STUECK = 1024 * 1024
PLATZ_RESERVE = 200 * 1024 * 1024          # die Platte soll nach dem Kopieren nicht randvoll sein

_MAIL_KONTOTYPEN = ("pop3", "imap", "none")           # rss und nntp sind keine Mails
# Zweite Sicherung neben der Positivliste: was so heißt, wird nie kopiert, auch nicht bei einem Fehler in der Suche
_NIE_KOPIEREN = {"logins.json", "key3.db", "key4.db", "cert8.db", "cert9.db", "signons.sqlite", "cookies.sqlite",
                 "prefs.js", "abook.sqlite", "pkcs11.txt"}
_BEIWERK = (".msf", ".dat", ".html", ".json", ".sqlite", ".db", ".js", ".txt", ".ini", ".log", ".wdseml")
_PREF = re.compile(r'^user_pref\("([^"]+)",\s*"(.*)"\);\s*$', re.M)
_NUR_ONLINE_MSF = 1000                     # ab dieser Größe hat der .msf-Index echte Einträge


class Gesperrt(OSError):
    """Eine Mail-Datei lässt sich nicht lesen, weil ihr Programm sie sperrt (E11)."""

    def __init__(self, programm):
        super().__init__(f"{programm} sperrt seine Mail-Datei.")
        self.programm = programm


class ZuWenigPlatz(OSError):
    def __init__(self, noetig, frei):
        super().__init__(f"Für die Kopie werden {groesse_text(noetig)} gebraucht, frei sind {groesse_text(frei)}.")
        self.noetig, self.frei = noetig, frei


class Quelle:
    """Ein Konto oder eine Datei: was der Nutzer ankreuzt. `dateien` = [(Pfad, Ordnername, Größe)]."""

    def __init__(self, programm, name, dateien, adressen=(), nur_online=0):
        self.programm, self.name, self.dateien = programm, name, list(dateien)
        self.adressen = list(adressen)
        self.nur_online = nur_online         # IMAP-Ordner, deren Text allein auf dem Server liegt

    @property
    def groesse(self):
        return sum(d[2] for d in self.dateien)


class Programm:
    """Ein gefundenes Mail-Programm: seine Quellen, oder `erklaerung`, wenn KID es nicht lesen kann."""

    def __init__(self, name, quellen=(), erklaerung=""):
        self.name, self.quellen, self.erklaerung = name, list(quellen), erklaerung

    def text(self):
        """Eintrag der ComboBox: „Thunderbird (2 Konten, 1,2 GB)“."""
        if not self.quellen:
            return f"{self.name} (nicht lesbar)"
        art = "Datei" if self.name == OUTLOOK else "Konto"
        mehrzahl = {"Datei": "Dateien", "Konto": "Konten"}[art]
        anzahl = len(self.quellen)
        return (f"{self.name} ({anzahl} {art if anzahl == 1 else mehrzahl}, "
                f"{groesse_text(sum(q.groesse for q in self.quellen))})")


def groesse_text(n):
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.1f} GB".replace(".", ",")
    return f"{max(n, 1) / 1024 ** 2:.0f} MB" if n >= 1024 * 1024 else f"{max(n, 1) // 1024 + 1} KB"


# ---------------------------------------------------------------- Suchen
def suche(umgebung=None, dokumente=None):
    """
    Alle gefundenen Mail-Programme, lesbare zuerst. Nie eine Ausnahme: Was sich nicht lesen lässt, wird übergangen.
    :param umgebung: Umgebungsvariablen (Tests), Standard os.environ
    :param dokumente: Ordner „Dokumente“ (Tests), Standard die Windows-Schnittstelle; er kann umgeleitet sein
    """
    env = os.environ if umgebung is None else umgebung
    programme = []
    for suchen in (lambda: _thunderbird(env), lambda: _outlook(env, dokumente), lambda: _nicht_lesbar(env)):
        try:
            programme.extend(suchen())
        except (OSError, ValueError, configparser.Error):
            continue
    return programme


def _thunderbird(env):
    wurzel = os.path.join(env.get("APPDATA", ""), "Thunderbird")
    if not env.get("APPDATA") or not os.path.isfile(os.path.join(wurzel, "profiles.ini")):
        return []
    profile = thunderbird_profile(wurzel)
    quellen, maildir, mit_mails = [], 0, set()
    for name, pfad, _standard in profile:
        for konto in _konten(pfad):
            if konto["maildir"]:
                maildir += 1
                continue
            dateien, nur_online = _mbox_dateien(konto["ordner"])
            if not dateien and not nur_online:
                continue
            mit_mails.add(name)
            quellen.append(Quelle(THUNDERBIRD, konto["name"], dateien, konto["adressen"], nur_online))
            quellen[-1].profil = name
    for q in quellen:                # der Profilname hilft nur, wenn wirklich zwei Profile Mails haben
        if len(mit_mails) > 1:
            q.name = f"{q.profil}: {q.name}"
    if quellen:
        return [Programm(THUNDERBIRD, quellen)]
    if maildir:
        return [Programm(THUNDERBIRD, erklaerung="Thunderbird speichert hier im Format Maildir, das KID nicht liest.")]
    return []


def thunderbird_profile(wurzel):
    """(Name, Pfad, Standard?) der vorhandenen Profile aus profiles.ini, das Standardprofil zuerst."""
    ini = configparser.RawConfigParser()
    ini.read(os.path.join(wurzel, "profiles.ini"), encoding="utf-8")
    standard = {ini.get(s, "Default", fallback="").replace("/", os.sep) for s in ini.sections() if s.startswith("Install")}
    standard |= {ini.get(s, "Path", fallback="").replace("/", os.sep) for s in ini.sections()
                 if s.startswith("Profile") and ini.get(s, "Default", fallback="") == "1"}
    funde = []
    for s in ini.sections():
        if not s.startswith("Profile"):
            continue
        pfad = ini.get(s, "Path", fallback="").replace("/", os.sep)
        ganz = os.path.join(wurzel, pfad) if ini.get(s, "IsRelative", fallback="1") == "1" else pfad
        if pfad and os.path.isdir(ganz):
            funde.append((ini.get(s, "Name", fallback=""), ganz, pfad in standard))
    return sorted(funde, key=lambda p: not p[2])


def _konten(profil):
    """Mail-Konten eines Profils aus prefs.js. Die Ordner stehen dort: Ein Konto kann woanders liegen als unter Mail\\."""
    pfad = os.path.join(profil, "prefs.js")
    if not os.path.isfile(pfad):
        return []
    with open(pfad, encoding="utf-8", errors="replace") as f:
        werte = {k: v.replace("\\\\", "\\").replace('\\"', '"') for k, v in _PREF.findall(f.read())}
    konten = []
    for konto in werte.get("mail.accountmanager.accounts", "").split(","):
        server = werte.get(f"mail.account.{konto}.server")
        if werte.get(f"mail.server.{server}.type") not in _MAIL_KONTOTYPEN:
            continue
        relativ = werte.get(f"mail.server.{server}.directory-rel", "")
        ordner = (os.path.join(profil, relativ[len("[ProfD]"):].replace("/", os.sep)) if relativ.startswith("[ProfD]")
                  else werte.get(f"mail.server.{server}.directory", ""))
        if not ordner or not os.path.isdir(ordner):
            continue
        kennungen = [i for i in werte.get(f"mail.account.{konto}.identities", "").split(",") if i]
        konten.append({"name": werte.get(f"mail.server.{server}.name", "") or os.path.basename(ordner), "ordner": ordner,
                       "adressen": [werte[f"mail.identity.{i}.useremail"].lower() for i in kennungen
                                    if f"mail.identity.{i}.useremail" in werte],
                       "maildir": "maildirstore" in werte.get(f"mail.server.{server}.storeContractID", "")})
    return konten


def _mbox_dateien(ordner):
    """
    ([(Pfad, Ordnername, Größe)], Zahl der IMAP-Ordner ohne Text) eines Kontos, nach Positivliste: Eine Mail-Datei
    beginnt mit „From “, Unterordner enden auf .sbd. Eine leere Datei mit großem .msf heißt: Die Mails liegen nur auf
    dem Server, das meldet die Oberfläche, statt leere Mails zu übernehmen.
    """
    dateien, nur_online = [], 0
    for wurzel, unter, namen in os.walk(ordner):
        unter[:] = [u for u in unter if u.endswith(".sbd")]
        for name in sorted(namen):
            pfad = os.path.join(wurzel, name)
            if name.lower().endswith(_BEIWERK) or name.lower() in _NIE_KOPIEREN:
                continue
            try:
                groesse = os.path.getsize(pfad)
                if groesse == 0:
                    msf = pfad + ".msf"
                    if os.path.exists(msf) and os.path.getsize(msf) >= _NUR_ONLINE_MSF:
                        nur_online += 1
                elif mail_lesen.ist_mbox(pfad):
                    dateien.append((pfad, os.path.relpath(pfad, ordner).replace(".sbd" + os.sep, "/"), groesse))
            except OSError:
                continue
    return dateien, nur_online


def _outlook(env, dokumente):
    orte = []
    if env.get("LOCALAPPDATA"):
        orte.append(os.path.join(env["LOCALAPPDATA"], "Microsoft", "Outlook"))
    dokumente = dokumente_ordner(env) if dokumente is None else dokumente
    if dokumente:
        orte += [os.path.join(dokumente, n) for n in ("Outlook-Dateien", "Outlook Files")]
    quellen = []
    for ort in orte:
        if not os.path.isdir(ort):
            continue
        for name in sorted(os.listdir(ort)):
            pfad = os.path.join(ort, name)
            if name.lower().endswith((".pst", ".ost")) and os.path.isfile(pfad):
                quellen.append(Quelle(OUTLOOK, name, [(pfad, "", os.path.getsize(pfad))]))
    return [Programm(OUTLOOK, quellen)] if quellen else []


def dokumente_ordner(env=None):
    """Der echte Ordner „Dokumente“: Er kann in OneDrive oder auf ein anderes Laufwerk umgeleitet sein."""
    env = os.environ if env is None else env
    if sys.platform == "win32":
        puffer = ctypes.create_unicode_buffer(32768)
        if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, puffer) == 0 and puffer.value:   # CSIDL_PERSONAL
            return puffer.value
    return os.path.join(env.get("USERPROFILE", ""), "Documents") if env.get("USERPROFILE") else ""


def _nicht_lesbar(env):
    """Programme, die KID erkennt, aber nicht liest: lieber erklären, als den Nutzer suchen lassen."""
    lokal, roaming = env.get("LOCALAPPDATA", ""), env.get("APPDATA", "")
    erkannt = []
    if lokal and os.path.isdir(os.path.join(lokal, "Microsoft", "Olk")):
        erkannt.append(Programm("Neues Outlook", erklaerung="Das neue Outlook hält die Mails im Postfach beim Anbieter "
                                                            "und hat keine lokale Mail-Datei, die KID lesen könnte."))
    if lokal and os.path.isdir(os.path.join(lokal, "Packages", "microsoft.windowscommunicationsapps_8wekyb3d8bbwe")):
        erkannt.append(Programm("Windows Mail", erklaerung="Windows Mail speichert in einem eigenen Format ohne "
                                                           "lesbare Mail-Datei."))
    if roaming and os.path.isdir(os.path.join(roaming, "eM Client")):
        erkannt.append(Programm("eM Client", erklaerung="eM Client speichert in einem eigenen Format. Über Export als "
                                                        ".eml lässt sich der Ordner von Hand wählen."))
    return erkannt


# ---------------------------------------------------------------- Kopieren
def kopie_ordner(umgebung=None):
    """E9: unter %LOCALAPPDATA%, weil der Daten-Ordner der Sammlung im Netz oder in einer Cloud liegen kann (private
    Mails wanderten dann mit) und Windows %TEMP% unter Umständen mitten im Lauf aufräumt."""
    env = os.environ if umgebung is None else umgebung
    return os.path.join(env.get("LOCALAPPDATA") or os.path.expanduser("~"), "Dokumenten-Manager", "Mail-Kopie")


def ist_kopie(ordner):
    return os.path.isfile(os.path.join(ordner, MARKE))


def lies_kopie(ordner):
    """Der Inhalt der Markierungsdatei, ohne vollständige Kopie None."""
    try:
        with open(os.path.join(ordner, MARKE), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("fertig") else None
    except (OSError, ValueError):
        return None


def kopie_passt(ordner, quellen):
    """Ist die vorhandene Kopie noch genau der Stand dieser Quellen? Dann muss nichts neu kopiert werden, etwa wenn
    der Nutzer nach einem abgebrochenen Lauf weitermacht."""
    d = lies_kopie(ordner)
    if d is None:
        return False
    vorhanden = {e["quelle"]: e for e in d.get("dateien", [])}
    gesucht = [datei[0] for q in quellen for datei in q.dateien]
    if set(vorhanden) != set(gesucht):
        return False
    try:
        return all(os.stat(p).st_size == vorhanden[p]["groesse"] and os.stat(p).st_mtime_ns == vorhanden[p]["zeit"]
                   and os.path.exists(os.path.join(ordner, vorhanden[p]["datei"])) for p in gesucht)
    except OSError:
        return False


def loesche_kopie(ordner):
    """Nur ein Ordner mit Markierungsdatei wird gelöscht, nie anhand eines Pfads allein. :return: True = weg oder leer"""
    if not os.path.isdir(ordner):
        return True
    if not ist_kopie(ordner):
        return False
    shutil.rmtree(ordner, ignore_errors=True)
    return not os.path.exists(ordner)


def _sha256(pfad):
    h = hashlib.sha256()
    with open(pfad, "rb") as f:
        while stueck := f.read(STUECK):
            h.update(stueck)
    return h.hexdigest()


def _kopiere_datei(quelle, ziel, programm, abbrechen, weiter):
    """Eine Datei kopieren und prüfen. Original nur lesend. :return: (Größe, Zeit) des kopierten Stands, oder None,
    wenn sie sich während des Kopierens geändert hat."""
    vorher = os.stat(quelle)
    h = hashlib.sha256()
    try:
        with open(quelle, "rb") as ein, open(ziel, "wb") as aus:
            while stueck := ein.read(STUECK):
                if abbrechen and abbrechen():
                    return False
                h.update(stueck)
                aus.write(stueck)
                weiter(len(stueck))
    except PermissionError as e:
        raise Gesperrt(programm) from e
    nachher = os.stat(quelle)
    if (vorher.st_size, vorher.st_mtime_ns) != (nachher.st_size, nachher.st_mtime_ns) or _sha256(ziel) != h.hexdigest():
        return None
    return nachher.st_size, nachher.st_mtime_ns


def kopiere(quellen, ordner, abbrechen=None, fortschritt=None, frei=None):
    """
    Kopiert die Mail-Dateien der Quellen nach `ordner` und schreibt die Markierungsdatei. Eine vorhandene Kopie wird
    ersetzt. Abbruch oder Fehler hinterlassen keine halbe Kopie.
    :param abbrechen: Callable → True bricht ab
    :param fortschritt: Callable(kopierte Bytes, Bytes gesamt)
    :param frei: freier Platz in Bytes (Tests), Standard: gemessen
    :return: True, False = abgebrochen
    :raises Gesperrt, ZuWenigPlatz, OSError: Der Aufrufer meldet es, nichts wird erzwungen.
    """
    if os.path.isdir(ordner) and os.listdir(ordner) and not ist_kopie(ordner):
        raise OSError("Der Ordner für die Kopie enthält fremde Dateien.")
    gesamt = sum(q.groesse for q in quellen)
    os.makedirs(os.path.dirname(os.path.abspath(ordner)), exist_ok=True)
    verfuegbar = shutil.disk_usage(os.path.dirname(os.path.abspath(ordner))).free if frei is None else frei
    if gesamt + PLATZ_RESERVE > verfuegbar:
        raise ZuWenigPlatz(gesamt + PLATZ_RESERVE, verfuegbar)
    loesche_kopie(ordner)
    os.makedirs(ordner, exist_ok=True)
    marke = os.path.join(ordner, MARKE)
    with open(marke, "w", encoding="utf-8") as f:     # zuerst: auch eine halbe Kopie ist als eigene erkennbar
        json.dump({"fertig": False}, f)
    fertig = False
    try:
        erledigt = [0]

        def weiter(n):
            erledigt[0] += n
            if fortschritt:
                fortschritt(erledigt[0], gesamt)

        eintraege = []
        for q in quellen:
            for pfad, ordnername, _groesse in q.dateien:
                if os.path.basename(pfad).lower() in _NIE_KOPIEREN:
                    continue
                name = f"{len(eintraege):05d}" + (os.path.splitext(pfad)[1].lower() if q.programm == OUTLOOK else "")
                ziel = os.path.join(ordner, name)
                for _versuch in range(KOPIER_VERSUCHE):
                    stand_vorher = erledigt[0]
                    stand = _kopiere_datei(pfad, ziel, q.programm, abbrechen, weiter)
                    if stand is False:
                        return False
                    if stand is not None:
                        break
                    erledigt[0] = stand_vorher              # geändert, während kopiert wurde: noch einmal
                else:
                    raise OSError(f"{q.programm} ändert eine Mail-Datei fortlaufend. Bitte das Programm schließen.")
                eintraege.append({"datei": name, "quelle": pfad, "konto": q.name, "ordner": ordnername,
                                  "groesse": stand[0], "zeit": stand[1]})
        tmp = marke + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"fertig": True, "hinweis": "Kopie für den Mail-Import von KID. Wird nach dem Import gelöscht.",
                       "dateien": eintraege}, f, ensure_ascii=False, indent=1)
        os.replace(tmp, marke)
        fertig = True
        return True
    finally:
        if not fertig:
            loesche_kopie(ordner)


def kopie_groesse(ordner):
    """Bytes aller Dateien einer Kopie."""
    return sum(e.stat().st_size for e in os.scandir(ordner) if e.is_file()) if os.path.isdir(ordner) else 0


def kopie_dateien(ordner):
    """[(Pfad in der Kopie, Ordnername)] einer vollständigen Kopie."""
    d = lies_kopie(ordner)
    return [(os.path.join(ordner, e["datei"]), e["ordner"]) for e in d["dateien"]] if d else []
