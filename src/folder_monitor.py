import logging
import os
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

MAX_ALTER_GEAENDERT = 60   # Sekunden: Wer länger nicht geschrieben wurde, wurde nur gelesen (ist_nur_zugriff)

class SyncHandler(FileSystemEventHandler):
    def __init__(self, callback):
        super().__init__()
        # Diese Funktion wird aufgerufen, sobald das Betriebssystem eine Änderung meldet
        self.callback = callback
        
    def on_any_event(self, event):
        # Wir ignorieren temporäre Dateien oder ganz spezifische Events nicht,
        # sondern leiten einfach das "Es hat sich was getan"-Signal an die GUI weiter.
        # EINE Ausnahme: ein bloßes „Ordner geändert" (DirModifiedEvent). Es begleitet
        # ohnehin jedes Anlegen/Löschen/Umbenennen einer Datei (deren Ereignisse kommen
        # sowieso) - und Windows meldet es zusätzlich verspätet, sobald der Ordner nach
        # einer Änderung das nächste Mal gelesen wird. Genau dieser Nachzügler löste
        # nach jedem eigenen Neulesen (sync_ui) ein zweites Neulesen aus: die
        # Vollautomatik las den Posteingang pro Dokument zweimal (FALLSTRICKE #68).
        if ist_reines_ordner_ereignis(event) or ist_nur_zugriff(event):
            return
        self.callback()


def ist_reines_ordner_ereignis(event):
    """True für ein „Ordner geändert"-Ereignis ohne eigenen Informationswert (siehe SyncHandler.on_any_event)."""
    return bool(getattr(event, "is_directory", False)) and getattr(event, "event_type", "") == "modified"


def ist_nur_zugriff(event, jetzt=None):
    """
    True, wenn eine Datei als „geändert“ gemeldet wird, ihr Inhalt aber längst nicht mehr geändert wurde. Windows
    meldet so die neue Zugriffszeit, also schon das bloße Lesen: Jeder erste Klick auf ein Dokument baute darum Ordnerbaum
    und Liste neu auf (Peter 05.11.2026, FALLSTRICKE #106). Neue, umbenannte und gelöschte Dateien melden eine andere
    Ereignisart, und eine echte Änderung setzt die Änderungszeit auf jetzt. MAX_ALTER_GEAENDERT lässt Spielraum für die
    abweichende Uhr eines Netzlaufwerks. Lässt sich die Datei nicht prüfen, gilt das Ereignis.
    """
    if getattr(event, "is_directory", False) or getattr(event, "event_type", "") != "modified":
        return False
    try:
        return (time.time() if jetzt is None else jetzt) - os.path.getmtime(event.src_path) > MAX_ALTER_GEAENDERT
    except (OSError, TypeError, ValueError):
        return False

class FolderMonitor:
    def __init__(self, callback):
        self.observer = None
        self.callback = callback
        # Weitere Zuhörer (z.B. die Vollautomatik, auto_pilot_service.py) - werden nach dem
        # Haupt-Callback aufgerufen; ein Fehler in einem Zuhörer darf die GUI-Synchronisation
        # nicht abwürgen. Achtung: alles hier läuft auf dem Watchdog-Thread.
        self._listeners = []

    def add_listener(self, listener):
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener):
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _dispatch(self):
        self.callback()
        for listener in list(self._listeners):
            try:
                listener()
            except Exception as e:
                logging.getLogger("DocManager").warning(f"Fehler in Watchdog-Zuhörer: {e}")

    def start_watching(self, path):
        self.stop_watching() # Alten Watcher stoppen, falls ein neuer Ordner gewählt wird
        
        if not path or not os.path.exists(path):
            return
            
        event_handler = SyncHandler(self._dispatch)
        self.observer = Observer()
        # recursive=True bedeutet: Er überwacht auch alle Unterordner!
        self.observer.schedule(event_handler, path, recursive=True)
        self.observer.start()

    def stop_watching(self):
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None