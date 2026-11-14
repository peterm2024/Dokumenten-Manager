import logging
import os

import sicher_speichern

_log = logging.getLogger("DocManager")


class Config:
    def __init__(self, filename="settings.json"):
        """
        Initialisiert den Konfigurations-Manager mit einer Zieldatei und Standardwerten.
        :param filename: Der Name oder Pfad der Konfigurations-JSON-Datei.
        """
        self.filename = filename
        # Hier definieren wir alle Standardwerte unserer App
        self.data = {
            "master_folder": ""
        }
        self.load()

    def load(self):
        """
        Lädt die Einstellungen aus der JSON-Datei und überschreibt die internen Standardwerte.
        """
        if os.path.exists(self.filename):
            try:
                # Überschreibe die Standardwerte mit den geladenen Werten. Eine beschädigte Datei legt
                # lade_json beiseite (FALLSTRICKE #115), gui meldet das beim Start.
                self.data.update(sicher_speichern.lade_json(self.filename))
            except Exception as e:
                _log.error(f"Fehler beim Laden der Einstellungen: {e}")

    def save(self):
        """
        Speichert das aktuelle Konfigurations-Dictionary in die JSON-Datei.
        :return: True bei Erfolg, False bei einem Fehler.
        """
        try:
            sicher_speichern.schreibe_json(self.filename, self.data, indent=4)
            return True
        except Exception as e:
            _log.error(f"Fehler beim Speichern der Einstellungen: {e}")
            return False

    def get(self, key, default=""):
        """
        Holt einen Wert aus den Einstellungen.
        :param key: Der abzufragende Schlüssel (z.B. "window_geometry").
        :param default: Der Rückgabewert, falls der Schlüssel nicht existiert.
        :return: Der gefundene Wert oder der Standardwert.
        """
        return self.data.get(key, default)

    def set(self, key, value):
        """
        Setzt einen neuen Wert für den angegebenen Schlüssel und speichert die Konfiguration.
        :param key: Der zu setzende Schlüssel.
        :param value: Der zugehörige Wert.
        """
        self.data[key] = value
        self.save()