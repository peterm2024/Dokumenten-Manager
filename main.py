# Dokumenten-Manager (KI Edition) - KID
# Copyright (C) 2026 Peter Metz
#
# Freie Software unter der GNU Affero General Public License v3.0 —
# siehe die Datei LICENSE im Projektverzeichnis. Bereitgestellt ohne
# jede Gewährleistung.

import os
import sys

# Die App-Module liegen in src/ (Aufräumen 05.09.2026), behalten aber ihre flachen
# Namen (import gui, import auto_pilot, ...) - src/ kommt dafür in den Suchpfad.
# In der EXE ist das wirkungslos (PyInstaller packt die Module direkt ein).
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import tkinter as tk
import app_paths
import einzelstart
import fehlerfaenger
from config import Config
from gui import DokumentenVerwaltung
from help_window import APP_NAME

def main():
    """
    Startpunkt der Anwendung. 
    Initialisiert das Tkinter-Hauptfenster und startet die DokumentenVerwaltung.
    """
    root = tk.Tk()
    try:
        # settings.json, Vorlagen und das Protokoll ohne Sammlung werden relativ zum Arbeitsverzeichnis
        # gesucht. Das bestimmt aber der Startweg und kann auch C:\Windows\System32 sein (FALLSTRICKE #102).
        os.chdir(app_paths.app_dir())
        # Zwei KID auf derselben Sammlung kämen sich in die Quere (einzelstart.py): Der zweite Doppelklick holt nur das erste nach vorn.
        if not einzelstart.belege(Config().get("master_folder") or app_paths.app_dir()):
            einzelstart.hole_nach_vorn(APP_NAME)
            root.destroy()
            return
        fehlerfaenger.absturz_protokoll_starten(app_paths.app_dir())
        DokumentenVerwaltung(root)
    except Exception:
        # Absturz schon beim Aufbau des Hauptfensters: noch kein Logger, keine Konsole
        # (EXE) - Traceback neben die EXE schreiben und den Pfad anzeigen, damit ein
        # Beta-Tester etwas zum Mitschicken hat (fehlerfaenger.py, 13.09.2026).
        import traceback
        from tkinter import messagebox
        text = traceback.format_exc()
        pfad = fehlerfaenger.startfehler_sichern(text, app_paths.app_dir())
        root.withdraw()
        messagebox.showerror(
            "Start fehlgeschlagen",
            "Das Programm konnte nicht gestartet werden.\n\n"
            + text.strip().splitlines()[-1] + "\n\n"
            + (f"Die Einzelheiten stehen in:\n{pfad}" if pfad else text))
        raise
    root.mainloop()

if __name__ == "__main__":
    main()