"""
Dienstmodus (Etappe 10, KONZEPT_DIENSTMODUS, Peter 17.11.2026): KID startet ohne Hauptfenster direkt in die
Hintergrund-Automatik. Gedacht für einen Rechner, an dem niemand sitzt (Touch-Panel in der Firma): Auf dem Schirm steht
nur das Statusfenster der Hintergrund-Automatik, keine Dokumentenliste und keine Vorschau.

Start: `KID.exe --dienst` (bzw. `python main.py --dienst`), z.B. als Verknüpfung im Autostart-Ordner. Einstellungen,
Sammlung und Sammlungssperre (einzelstart) wie beim normalen Start; die Sammlung richtet man vorher einmal mit
Oberfläche ein (KI-Adresse, Modelle).

`DienstApp` ist der schlanke Stellvertreter des Hauptfensters (gui.DokumentenVerwaltung) für den
AutoPilotService: Einstellungen, Sammlung, Protokoll, Ordner-Wächter, Index, Verschieben. Den Tag-Katalog liest der
Dienst selbst aus tags.json (tag_katalog), Werkzeuge gibt es keine, und es wird nie etwas „gerade bearbeitet“.
Das unsichtbare Tk-Wurzelfenster bleibt, damit `root.after` (Statusfenster, Hauptthread) wie gewohnt trägt.

Die Hintergrund-Automatik ist hier immer an (`AutoPilotService(immer_an=True)`), die Einstellung
`auto_pilot_enabled` wird weder gelesen noch verändert. Beenden: Knopf „Dienst beenden“ im Statusfenster (mit
Rückfrage) - danach endet der ganze Prozess.

Sperre über Rechnergrenzen (Schritt 4, posteingang_sperre.py): Beim Start Hinweis in den Posteingang und Lebenszeichen
in den Daten-Ordner, jede Minute aufgefrischt; überwacht schon ein KID auf einem anderen Rechner, startet der Dienst
nicht. Beim Beenden verschwinden beide Dateien.
"""

import os
import threading
from tkinter import messagebox

import app_paths
import auto_pilot
import ollama_client
import posteingang_sperre
import ui_theme
from app_logger import AppLogger
from auto_pilot_service import AutoPilotService
from config import Config
from fehlerfaenger import Fehlerfaenger
from file_operations import FileOperations
from folder_monitor import FolderMonitor
from index_manager import IndexManager
from ui_utils import UIUtils

TITEL = "KID – Hintergrund-Automatik"
SCHALTER = "--dienst"


def ist_dienststart(argv):
    """True, wenn KID im Dienstmodus starten soll (Schalter `--dienst` irgendwo in der Kommandozeile)."""
    return SCHALTER in (argv or [])[1:]


class _KeineWerkzeuge:
    """Ersatz für den ToolManager: Im Dienstmodus gibt es keine offenen Werkzeuge, die von Verschiebungen hören."""

    def notify_file_moved(self, alt, neu):
        pass


class DienstApp:
    """Stellvertreter des Hauptfensters für die Hintergrund-Automatik. `gestartet` ist False, wenn es nichts zu tun gab
    (keine gültige Sammlung) - dann ist das Wurzelfenster schon zerstört."""

    dienstmodus = True

    def __init__(self, root):
        self.root = root
        root.withdraw()
        root.title(TITEL)
        self.config = Config()
        self.master_folder = self.config.get("master_folder")
        # Was der AutoPilotService beim Hauptfenster abfragt - hier gibt es nichts zu bearbeiten
        self.is_moving = False
        self.is_saving = False
        self.current_preview_path = None
        self.save_manager = None
        self.tag_manager = None
        self.tool_manager = _KeineWerkzeuge()
        self.vollautomatik_fenster = None
        self.posteingang = None
        self.gestartet = False

        if not self.master_folder or not os.path.isdir(self.master_folder):
            messagebox.showerror(TITEL, "Es ist keine Dokumenten-Sammlung eingerichtet (oder sie ist nicht erreichbar).\n\n"
                                        "Bitte KID einmal normal starten und die Sammlung wählen, dann erneut im "
                                        "Dienstmodus starten.")
            root.destroy()
            return

        app_paths.migrate_legacy_layout(self.master_folder)
        self.logger = AppLogger()
        self.logger.set_log_file(app_paths.log_path(self.master_folder))
        self.logger.info("Dienstmodus gestartet (ohne Hauptfenster, Hintergrund-Automatik).")
        self.fehlerfaenger = Fehlerfaenger(root, self.logger, self._oeffne_log).installieren()
        ollama_client.setze_langsamen_modus(bool(self.config.get("ki_cpu_erlauben", False)))

        # Sperre über Rechnergrenzen (Schritt 4, posteingang_sperre.py): überwacht schon ein KID auf einem anderen
        # Rechner diesen Posteingang (Sammlung auf dem Netzlaufwerk), startet der Dienst hier nicht
        fremd = posteingang_sperre.fremd_aktiv(self.master_folder)
        if fremd:
            wer = posteingang_sperre.beschreibung(fremd)
            self.logger.warning(f"Dienstmodus nicht gestartet: Posteingang wird schon von KID auf {wer} überwacht.")
            messagebox.showinfo(TITEL, f"Diesen Posteingang überwacht schon KID auf {wer}.\n\n"
                                       "Der Dienstmodus startet deshalb hier nicht.")
            root.destroy()
            return
        self.posteingang = auto_pilot.finde_posteingang(self.master_folder)
        try:
            posteingang_sperre.belege(self.master_folder, self.posteingang)
        except OSError as e:
            self.logger.warning(f"Dienstmodus: Sperre des Posteingangs nicht möglich ({e}) - läuft ohne.")
        self._lebenszeichen_stopp = threading.Event()
        self._sperre_verloren = False

        self.file_ops = FileOperations(self)          # nur _verschiebe_ohne_duplikat wird gebraucht
        self.index_manager = IndexManager(self)
        self.monitor = FolderMonitor(lambda: None)    # kein Ordnerbaum zu aktualisieren; der Dienst hört als Zuhörer
        self.monitor.start_watching(self.master_folder)

        auto_pilot.protokolliere(self.master_folder, "DIENST    gestartet - Hintergrund-Automatik ohne Hauptfenster",
                                 self.logger)
        ui_theme.wende_an(root)      # dasselbe helle Design wie mit Oberfläche (Etappe 11) - vor dem Statusfenster
        UIUtils.mindestgroesse_ueberall(root)        # B5: Mindestgröße wie mit Oberfläche
        self.auto_pilot_service = AutoPilotService(self, immer_an=True)
        self.auto_pilot_service.start()               # öffnet auch das Statusfenster (vollautomatik_fenster)
        threading.Thread(target=self._lebenszeichen, name="Posteingang-Sperre", daemon=True).start()
        self.gestartet = True

    def _lebenszeichen(self):
        """Hintergrund-Thread: Sperre jede Minute auffrischen. Hat sie inzwischen ein anderes KID (zwei Dienste fast
        gleichzeitig gestartet), pausiert dieser Dienst, bis sie wieder frei ist - eine Zeile im Protokoll."""
        while not self._lebenszeichen_stopp.wait(posteingang_sperre.LEBENSZEICHEN_S):
            self.pruefe_sperre()

    def pruefe_sperre(self):
        try:
            frei = posteingang_sperre.erneuere(self.master_folder)
        except OSError as e:
            self.logger.warning(f"Dienstmodus: Lebenszeichen nicht geschrieben ({e}).")
            return
        if not frei and not self._sperre_verloren:
            wer = posteingang_sperre.beschreibung(posteingang_sperre.lies(self.master_folder) or {})
            auto_pilot.protokolliere(self.master_folder, f"WARNUNG   Posteingang wird inzwischen von KID auf {wer} "
                                                         "überwacht - dieser Dienst pausiert", self.logger)
            self._sperre_verloren = True
            self.auto_pilot_service.pausieren()
            self.auto_pilot_service._status("fremd", text=f"Diesen Posteingang überwacht inzwischen KID auf {wer} - "
                                                          "hier pausiert die Hintergrund-Automatik.")
        elif frei and self._sperre_verloren:
            auto_pilot.protokolliere(self.master_folder, "OK        Posteingang wieder frei - Dienst läuft weiter",
                                     self.logger)
            self._sperre_verloren = False
            self.auto_pilot_service.fortsetzen()

    def _oeffne_log(self):
        if os.path.exists(self.logger.log_file):
            os.startfile(self.logger.log_file)

    def beenden(self):
        """Hintergrund-Automatik anhalten, Protokollzeile, Prozess beenden."""
        try:
            self._lebenszeichen_stopp.set()
            self.auto_pilot_service.stop()
            posteingang_sperre.gib_frei(self.master_folder, self.posteingang)
            self.monitor.stop_watching()
            self.index_manager.close()
            auto_pilot.protokolliere(self.master_folder, "DIENST    beendet", self.logger)
            self.logger.info("Dienstmodus beendet.\n" + "-" * 40)
        finally:
            self.root.quit()
