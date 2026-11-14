from abc import ABC, abstractmethod
from typing import Any, List

class ToolContext:
    """Liefert dem Tool alle relevanten Daten der App, ohne die GUI fest zu koppeln."""
    def __init__(self, selected_files: List[str], current_folder: str, logger: Any, app_reference: Any):
        self.selected_files = selected_files  # Absolute Pfade der markierten PDFs
        self.current_folder = current_folder  # Aktuell geöffnetes Verzeichnis
        self.logger = logger                  # Zugriff auf das zentrale Logging-System
        self.app = app_reference              # Optionale Brücke für GUI-Updates

class BaseTool(ABC):
    """Abstrakte Basisklasse für Plugins in tools/. Der ToolManager lädt beim Start alle Klassen, die hiervon erben, und hängt sie über menu_hooks in die GUI ein.

    Optional (12.11.2026): Wer `fuelle_kontextmenue(self, menu, context)` definiert, bekommt im Rechtsklick der
    Dokumentenliste statt eines Eintrags ein Untermenü „🛠 name“, das der ToolManager vor jedem Öffnen leert und von
    dieser Methode füllen lässt (tk.Menu; Unter-Untermenüs als Kinder von `menu`). Vorbild: tools/wiki.py."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Anzeigename des Tools im Menü, z.B. 'PDF-Inspektor'."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """Kurzbeschreibung, z.B. für Tooltips."""
        pass

    @property
    @abstractmethod
    def menu_hooks(self) -> List[str]:
        """Legt fest, wo das Tool auftaucht: Teilmenge von ["context_menu", "main_menu"]."""
        pass

    @property
    @abstractmethod
    def required_input(self) -> str:
        """Ob eine Dateiauswahl nötig ist, bevor execute() aufgerufen werden darf, z.B. "none" oder "single_file"."""
        pass

    @abstractmethod
    def execute(self, context: ToolContext) -> bool:
        """Startet das Tool (z.B. öffnet ein Toplevel-Fenster); der ToolManager stellt vorher required_input sicher."""
        pass

    @property
    def menu_group(self) -> str:
        """
        Untermenü im Tools-Menü, z.B. "Vollautomatik" oder "Aufräumen" (Nutzerwunsch
        07.09.2026: das flache Tools-Menü war unübersichtlich). Leer = oberste Ebene.
        Die Reihenfolge der Gruppen legt tool_manager.GRUPPEN_REIHENFOLGE fest.
        """
        return ""

    @property
    def braucht_ki(self) -> bool:
        """
        True, wenn das Tool ohne erreichbaren KI-Server nicht sinnvoll läuft (Titel-Vorschlag,
        Ablage-Vorschau, Posteingang verarbeiten). Der ToolManager sperrt
        seine Menüeinträge dann, solange ki_status den Server als nicht erreichbar meldet
        (Nutzerfund 13.09.2026: Werkzeug lief ohne Server los und blieb stumm stehen).
        Tools, bei denen die KI nur ein optionaler Knopf ist (Dateinamen aufräumen,
        Dubletten-Zweitprüfung), bleiben erreichbar.
        """
        return False

    @property
    def absicht(self) -> str:
        """
        WOFÜR das Tool gedacht ist - die Absicht, der typische Anlass (1-2 Sätze). Ergänzt
        `description` (WAS passiert) in der Menü-Hilfe (menue_hilfe.py: Reiter
        „Menü-Übersicht" und Erklärung beim Verweilen auf dem Eintrag). Leer = keine
        Erklärung hinterlegt; ein ausgeliefertes Tool sollte sie liefern (Test).
        """
        return ""

    @property
    def menu_label(self) -> str:
        """
        Kurzer Text im (Unter-)Menü - darf die Gruppe weglassen ("Protokoll anzeigen"
        statt "Vollautomatik: Protokoll anzeigen"). Das Rechtsklick-Menü und alle
        Meldungen benutzen weiterhin den vollen `name`.
        """
        return self.name

    def on_selection_changed(self, context: ToolContext) -> None:
        """Wird aufgerufen, wenn sich die Dateiauswahl in der Haupt-App ändert."""
        pass

    def on_file_moved(self, old_path: str, new_path: str) -> None:
        """Wird aufgerufen, wenn die Haupt-App eine Datei verschiebt oder umbenennt — damit offene Tool-Fenster ihren Datei-Pfad nachziehen können."""
        pass