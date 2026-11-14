"""
Zentrale Ja/Nein-Sicherheitsabfragen (Nutzerwunsch 07.09.2026: "Bestätigungsdialoge in
den Einstellungen deaktivieren können").

Alle ROUTINE-Rückfragen der App ("3 Dateien in den Papierkorb?", "Jetzt einsortieren?",
"Tag löschen?") laufen über `frage`. Steht in den Einstellungen `bestaetigungen_anzeigen`
auf False, gilt die Antwort als "Ja" - ohne Dialog.

Bewusst NICHT hier durchgeleitet (fragen immer, weil unumkehrbar oder keine reine
Bestätigung): endgültiges Löschen aus dem Papierkorb, Überschreiben einer vorhandenen
Datei, die Ersteinrichtungs-Dialoge und "Änderungen speichern?" im PDF-Editor.

Die Config wird einmal beim Start eingehängt (`konfigurieren`); ohne Config wird immer
gefragt - so verhalten sich Tests und Tool-Fenster ohne App-Kontext wie bisher.
"""
from tkinter import messagebox
import aktivitaet

EINSTELLUNG = "bestaetigungen_anzeigen"

_config = None


def konfigurieren(config):
    """Hängt die App-Config ein (gui.py beim Start). None = immer fragen."""
    global _config
    _config = config


def aktiv():
    """True, wenn Routine-Rückfragen angezeigt werden sollen (Standard: ja)."""
    if _config is None:
        return True
    try:
        return bool(_config.get(EINSTELLUNG, True))
    except Exception:
        return True


def frage(titel, text, parent=None):
    """
    Ja/Nein-Rückfrage wie messagebox.askyesno - liefert ohne Dialog True, wenn der
    Nutzer die Sicherheitsabfragen abgeschaltet hat.
    """
    if not aktiv():
        return True
    # Aktivitätsanzeige: ein Dialog kann hinter einem anderen Fenster liegen - in der
    # Menüleiste steht dann, dass auf eine Antwort gewartet wird (aktivitaet.py)
    with aktivitaet.warte_auf_antwort(titel):
        if parent is not None:
            return bool(messagebox.askyesno(titel, text, parent=parent))
        return bool(messagebox.askyesno(titel, text))
