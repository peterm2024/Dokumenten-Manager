"""
Versionsprüfung gegen die GitHub-Releases (Beta-Vorbereitung 14.09.2026).

Das Programm hat keine automatische Aktualisierung; Beta-Tester sollen aber merken, wenn
eine neue EXE bereitliegt. „Hilfe → Auf neue Version prüfen…“ fragt die GitHub-API nach
dem neuesten Release (nur Standardbibliothek, ohne Anmeldung) und vergleicht die
Versionsnummer mit `help_window.APP_VERSION`. Optional läuft dieselbe Prüfung still beim
Start (Einstellung `versionspruefung_beim_start`, Standard an) und meldet sich NUR, wenn
es etwas Neueres gibt - kein Fenster bei „aktuell“ oder ohne Internet.

Die Anfrage läuft in einem Hintergrund-Thread; Dialoge kommen per `root.after` in den
Tk-Thread. Es wird nichts über den Nutzer übertragen (kein Name, keine Kennung); GitHub
sieht nur, dass jemand die Release-Liste abruft.
"""

import json
import re
import threading
import urllib.error
import urllib.request
import webbrowser
from tkinter import messagebox

REPO = "peterm2024/Dokumenten-Manager"
RELEASES_URL = f"https://github.com/{REPO}/releases"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
TIMEOUT = 6
EINSTELLUNG = "versionspruefung_beim_start"


def parse_version(text):
    """'v0.9.17' oder '0.9.17 (Build …)' -> (0, 9, 17); None, wenn keine Nummer erkennbar."""
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", str(text or ""))
    if not m:
        return None
    return tuple(int(g) if g is not None else 0 for g in m.groups())


def vergleiche(aktuell, neueste):
    """'neuer' (Release ist neuer), 'aktuell' (gleich) oder 'voraus' (lokale Version ist neuer - Entwicklung)."""
    a, n = parse_version(aktuell), parse_version(neueste)
    if a is None or n is None:
        raise ValueError(f"Versionsnummer nicht lesbar: {aktuell!r} / {neueste!r}")
    if n > a:
        return "neuer"
    if n < a:
        return "voraus"
    return "aktuell"


def hole_neueste(timeout=TIMEOUT):
    """Fragt die GitHub-API nach dem neuesten Release: {'version', 'url', 'notizen'}. Wirft bei Netz-/Formatfehlern."""
    req = urllib.request.Request(API_URL, headers={"User-Agent": "Dokumenten-Manager", "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            daten = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # 404 heißt bei GitHub auch: Repository privat oder noch kein Release - ohne
        # Anmeldung nicht unterscheidbar. Klartext statt "HTTP Error 404: Not Found".
        if e.code == 404:
            raise OSError("Die Releases-Seite ist ohne Anmeldung nicht erreichbar "
                          "(Repository privat oder noch kein Release).") from e
        if e.code in (403, 429):
            raise OSError("GitHub lehnt die Anfrage vorübergehend ab (Anfragelimit) - später erneut versuchen.") from e
        raise
    version = daten.get("tag_name") or daten.get("name") or ""
    if parse_version(version) is None:
        raise ValueError("Antwort ohne Versionsnummer")
    return {"version": version.lstrip("v"), "url": daten.get("html_url") or RELEASES_URL,
            "notizen": (daten.get("body") or "").strip()}


def ohne_markdown(text):
    """Release-Notizen für einen Tk-Dialog: Überschriften-Rauten, Fett-Sterne und Backticks entfernen."""
    zeilen = []
    for zeile in str(text or "").splitlines():
        zeile = re.sub(r"^\s*#+\s*", "", zeile)
        zeile = zeile.replace("**", "").replace("`", "")
        zeilen.append(zeile)
    return "\n".join(zeilen).strip()


def pruefe(app, still=False, aktuell=None, hole=hole_neueste, oeffne=webbrowser.open):
    """
    Startet die Prüfung im Hintergrund. still=True (Start): nur bei einer neueren Version melden.
    aktuell/hole/oeffne sind für Tests austauschbar.
    """
    if aktuell is None:
        from help_window import APP_VERSION
        aktuell = APP_VERSION

    def lauf():
        try:
            neueste = hole()
            befund = vergleiche(aktuell, neueste["version"])
            ergebnis = (befund, neueste, None)
        except Exception as e:  # Netz weg, Rate-Limit, Formatänderung - nie den Aufrufer stören
            ergebnis = (None, None, e)
        try:
            app.root.after(0, lambda: _zeige(app, still, aktuell, ergebnis, oeffne))
        except Exception:
            pass

    threading.Thread(target=lauf, name="Versionsprüfung", daemon=True).start()


def _zeige(app, still, aktuell, ergebnis, oeffne):
    befund, neueste, fehler = ergebnis
    logger = getattr(app, "logger", None)
    if fehler is not None:
        if logger:
            logger.info(f"Versionsprüfung nicht möglich: {fehler}")
        if not still:
            messagebox.showwarning("Versionsprüfung",
                                   f"Die Releases-Seite konnte nicht abgefragt werden:\n{fehler}\n\n"
                                   f"Von Hand nachsehen: {RELEASES_URL}", parent=app.root)
        return
    if logger:
        logger.info(f"Versionsprüfung: installiert {aktuell}, neuestes Release {neueste['version']} ({befund}).")
    if befund == "neuer":
        kurz = ohne_markdown(neueste["notizen"])
        if len(kurz) > 600:
            kurz = kurz[:600].rsplit("\n", 1)[0] + "\n…"
        text = (f"Es gibt eine neue Version: {neueste['version']} (installiert: {aktuell}).\n\n"
                + (kurz + "\n\n" if kurz else "")
                + "Die Releases-Seite mit dem Download im Browser öffnen?")
        if messagebox.askyesno("Neue Version verfügbar", text, parent=app.root):
            oeffne(neueste["url"])
    elif not still:
        if befund == "aktuell":
            messagebox.showinfo("Versionsprüfung", f"Version {aktuell} ist die neueste.", parent=app.root)
        else:
            messagebox.showinfo("Versionsprüfung",
                                f"Version {aktuell} ist neuer als das letzte Release ({neueste['version']}) - "
                                "eine Entwicklungsversion.", parent=app.root)
