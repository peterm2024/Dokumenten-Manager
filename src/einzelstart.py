"""
Eine Sammlung, ein KID (ARCHITEKTUR_REVIEW.md, R3).

Zwei laufende KID auf derselben Sammlung hießen zwei Vollautomatiken im selben Posteingang mit denselben Temp-Dateien, und
die Einstellungen schreibt zuletzt, wer zuletzt schließt. Bis das Fenster der EXE steht, vergeht eine Weile (gemessen rund 1 s,
auf langsameren Rechnern vermutlich länger), ein zweiter Doppelklick liegt also nahe.

Die Sperre ist ein benannter Windows-Mutex mit dem Pfad der Sammlung im Namen. Sie liegt nicht als Datei auf der Platte und
wird darum auch nach einem Absturz von selbst frei. Sie gilt je Sammlung: Zwei verschiedene Sammlungen dürfen parallel laufen.
Lässt sich gar kein Mutex anlegen, startet KID trotzdem: Die Sperre soll schützen, nie den Start verhindern.
"""
import ctypes
import hashlib
import logging
import os
import sys
from ctypes import wintypes

FEHLER_SCHON_VORHANDEN = 183
SW_RESTORE = 9

_log = logging.getLogger("DocManager")
_griff = None
_name_belegt = None


def _kernel32():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CreateMutexW.restype = wintypes.HANDLE
    k.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    return k


def _mutex_name(sammlung):
    """Gleicher Ordner, gleicher Name, egal in welcher Schreibweise."""
    kanonisch = os.path.normcase(os.path.abspath(sammlung))
    return "Local\\KID-Sammlung-" + hashlib.sha1(kanonisch.encode("utf-8")).hexdigest()


def belege(sammlung):
    """True, wenn diese Sammlung jetzt diesem Prozess gehört; False, wenn ein anderes KID sie offen hat. Eine vorher belegte
    Sammlung wird erst frei, wenn die neue sicher ist: Ein gescheiterter Wechsel ändert nichts."""
    global _griff, _name_belegt
    if sys.platform != "win32":
        return True
    name = _mutex_name(sammlung)
    if name == _name_belegt:
        return True
    k = _kernel32()
    griff = k.CreateMutexW(None, False, name)
    fehler = ctypes.get_last_error()
    if not griff:
        _log.warning(f"Sperre für die Sammlung nicht möglich (Windows-Fehler {fehler}), KID startet trotzdem.")
        return True
    if fehler == FEHLER_SCHON_VORHANDEN:
        k.CloseHandle(griff)
        return False
    freigeben()
    _griff, _name_belegt = griff, name
    return True


def freigeben():
    """Gibt die Sammlung frei. Beim Ende des Prozesses erledigt das Windows von selbst."""
    global _griff, _name_belegt
    if _griff:
        _kernel32().CloseHandle(_griff)
    _griff, _name_belegt = None, None


def _finde_fenster(titel_anfang):
    """Griff des ersten sichtbaren Fensters, dessen Titel so beginnt, sonst None."""
    u = ctypes.WinDLL("user32")
    gefunden = []
    Rueckruf = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def pruefe(hwnd, _):
        if not u.IsWindowVisible(hwnd):
            return True
        puffer = ctypes.create_unicode_buffer(512)
        u.GetWindowTextW(hwnd, puffer, 512)
        if puffer.value.startswith(titel_anfang):
            gefunden.append(hwnd)
            return False
        return True

    u.EnumWindows(Rueckruf(pruefe), 0)
    return gefunden[0] if gefunden else None


def hole_nach_vorn(titel_anfang):
    """Holt das laufende KID nach vorn, damit der zweite Doppelklick nicht wirkungslos aussieht. Startet es noch und hat kein
    Fenster, passiert nichts: Es erscheint dann ohnehin gleich."""
    if sys.platform != "win32":
        return False
    hwnd = _finde_fenster(titel_anfang)
    if not hwnd:
        return False
    u = ctypes.WinDLL("user32")
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, SW_RESTORE)
    u.SetForegroundWindow(hwnd)
    return True
