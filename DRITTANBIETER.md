# Drittanbieter-Komponenten und Lizenzen

Stand 03.11.2026 (Vorbereitung der Quellcode-Veröffentlichung). Der Dokumenten-Manager selbst steht unter der
**GNU Affero General Public License v3.0** (siehe [LICENSE](LICENSE)), weil seine wichtigste Abhängigkeit PyMuPDF
AGPL-lizenziert ist.

## In der ausgelieferten EXE enthalten

| Komponente | Version | Lizenz | Wofür |
|---|---|---|---|
| PyMuPDF (mit MuPDF) | 1.27.2.3 (MuPDF 1.27.2) | AGPL-3.0 (oder kommerziell bei Artifex) | PDF lesen, schreiben, darstellen |
| Pillow | 12.2.0 | MIT-CMU | Bilder (Vorschau, Fingerabdruck, Icon) |
| watchdog | 6.0.0 | Apache-2.0 | Ordnerüberwachung |
| libpff-python (pypff, libyal) | 20260926 | LGPL-3.0-or-later | Mail-Import: Outlook .pst/.ost lesen (seit 04.11.2026; mit der AGPL vereinbar) |
| Python (Laufzeit und Standardbibliothek) | 3.14.5 | PSF-2.0 | Laufzeit |
| Tcl/Tk (über tkinter) | 8.6.15 | Tcl/Tk-Lizenz (BSD-artig) | Oberfläche |
| Tesseract-Sprachdaten `deu.traineddata` | tessdata_fast | Apache-2.0 | OCR-Sprachdaten |
| PyInstaller-Bootloader | 6.22.2 | GPL-2.0-or-later mit Ausnahme für den Bootloader | Startprogramm der EXE (die Ausnahme erlaubt das Weitergeben gepackter Programme unter beliebiger Lizenz) |

Die OCR-Engine Tesseract selbst ist nicht in der EXE; sie wird über PyMuPDF angesprochen, die Sprachdaten liegen bei.

## Nur für die Entwicklung (nicht in der EXE)

| Komponente | Version | Lizenz |
|---|---|---|
| PyInstaller | 6.22.2 | GPL-2.0-or-later mit Ausnahme |
| ruff | 0.15.20 (installiert ist 0.16.6) | MIT |
| mkdocs | 1.6.1 | BSD-2-Clause |
| mkdocs-material | 9.7.6 | MIT |
| mkdocstrings | 1.0.4 | ISC |
| mkdocs-include-markdown-plugin | 7.3.0 | Apache-2.0 |

## Was daraus folgt

- **AGPL-3.0 verlangt den Quellcode für jeden, der das Programm bekommt** (Abschnitt 6: „Corresponding Source“), auch
  für die EXE der Beta-Tester. Solange der Quellcode privat ist, sollte das Angebot zumindest in README/Leitfaden
  stehen (Quellcode auf Anfrage) - besser ist die geplante Veröffentlichung des bereinigten Stands. Steht seit 04.11.2026 im
  öffentlichen README, im Leitfaden (Abschnitt 7) und im Hilfe-Reiter „Über“. Die EXE (onefile) bringt den Lizenztext nicht mit;
  deshalb legt `veroeffentlichen.py` ab v0.9.23 LICENSE.txt als zweite Datei in jedes Release.
- Mit der EXE sollten die Lizenztexte der enthaltenen Komponenten mitgeliefert werden (MIT-CMU, Apache-2.0, PSF, Tcl/Tk;
  Apache-2.0 verlangt bei Weitergabe den Lizenztext). Am einfachsten ein Ordner `Lizenzen/` neben der EXE bzw. im
  öffentlichen Repo.
- Keine Komponente ist mit der AGPL unverträglich (Apache-2.0, MIT, BSD, PSF und ISC sind mit GPLv3/AGPLv3 vereinbar).

Diese Übersicht ist eine technische Bestandsaufnahme, keine Rechtsberatung.
