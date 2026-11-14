"""
Ermittelt den Scan-Zeitpunkt eines Dokuments für die optionale "Scan-Zeitpunkt"-Spalte
in der Dokumentenliste (Reihenfolge der tatsächlichen Scans nachvollziehen).

Zwei verworfene Vorstufen (siehe FALLSTRICKE #22 für die volle Geschichte):
1. Ein im Dateinamen codiertes Datum auszuwerten - Sackgasse, die Ziffern im Namen sind
   selbst nur ein gescheiterter OCR-Versuch des DOKUMENTENDATUMS, kein Scan-Zeitpunkt.
2. Die Datei-Erstellungszeit (`os.path.getctime`) - bei einem Import von einem anderen
   Rechner/Datenträger ist das nur noch das Kopierdatum, nicht das Scan-Datum.

Verlässliche Quelle ist das PDF-Standardfeld `creationDate` (Format nach PDF-Spezifikation
'D:YYYYMMDDHHmmSS+HH'mm''): Scanner/Scan-Software brennen das beim Erzeugen des PDFs direkt
in die Datei ein - das übersteht Kopien, Backups und einen Rechnerwechsel, weil es Teil des
Dateiinhalts ist statt eines Dateisystem-Attributs. Die Datei-Erstellungszeit bleibt als
letzte, schwächere Rückfallebene, falls ein PDF gar kein creationDate trägt (z.B. manche
digital erzeugten Dokumente ganz ohne Scan-Ursprung).
"""
import os
import re
import datetime

STORAGE_FORMAT = "%Y-%m-%d %H:%M"
DISPLAY_FORMAT = "%d.%m.%Y %H:%M"
# Nur zum Lesen alter, vor dieser Vereinfachung gespeicherter Werte (damals ohne Uhrzeit).
_LEGACY_STORAGE_FORMAT_DATE_ONLY = "%Y-%m-%d"
_LEGACY_DISPLAY_FORMAT_DATE_ONLY = "%d.%m.%Y"

_PDF_DATE_PATTERN = re.compile(r"^D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?")


def parse_pdf_date(raw):
    """
    Parst das PDF-Standard-Metadatenfeld 'creationDate' (z.B. "D:20220505185907+01'00'").
    Zeitzone wird bewusst ignoriert (uns interessiert nur der Tag/die Uhrzeit vor Ort, kein
    exakter UTC-Zeitpunkt); Uhrzeit-Anteile sind laut Spezifikation optional und fehlende
    Teile werden auf 0 bzw. den 1. eines Monats/Jahres ergänzt. Liefert ein datetime oder
    None bei fehlendem/kaputtem Wert.
    """
    if not raw:
        return None
    match = _PDF_DATE_PATTERN.match(raw)
    if not match:
        return None
    year, month, day, hour, minute, second = match.groups()
    try:
        return datetime.datetime(int(year), int(month or 1), int(day or 1),
                                  int(hour or 0), int(minute or 0), int(second or 0))
    except ValueError:
        return None


def resolve_scan_timestamp(creation_date_raw, abs_path):
    """
    Bester verfügbarer Scan-Zeitpunkt: bevorzugt das im PDF eingebrannte creationDate-Feld
    (siehe parse_pdf_date), sonst die Datei-Erstellungszeit als letzte Rückfallebene.
    Liefert ein datetime oder None.
    """
    dt = parse_pdf_date(creation_date_raw)
    if dt:
        return dt
    try:
        return datetime.datetime.fromtimestamp(os.path.getctime(abs_path))
    except OSError:
        return None


def to_storage(dt):
    """Formatiert einen Scan-Zeitpunkt für die Ablage im PDF-subject-Feld (KID_SCAN:<wert>)."""
    return dt.strftime(STORAGE_FORMAT)


def erfasst_anzeige(erfasst, scan_anzeige):
    """Wert der Spalte „Erfasst“: der eingebrannte KID_ERFASST; ältere Dokumente haben keinen, dort steht der
    Scan-Zeitpunkt (Peter 04.11.2026). `scan_anzeige` ist schon in Anzeigeform (format_scan_timestamp)."""
    return format_storage_value(erfasst) or scan_anzeige or ""


def format_storage_value(value):
    """
    Wandelt einen gespeicherten KID_SCAN-Wert in die Anzeigeform (DD.MM.YYYY HH:MM) um.
    Erkennt zusätzlich das alte Nur-Datum-Format (aus der Zeit vor dieser Vereinfachung).
    Nicht parsebare Werte werden unverändert angezeigt statt verworfen - der gespeicherte
    Wert ist Ground Truth, lieber roh anzeigen als Information verschlucken.
    """
    if not value:
        return ""
    try:
        return datetime.datetime.strptime(value, STORAGE_FORMAT).strftime(DISPLAY_FORMAT)
    except ValueError:
        pass
    try:
        return datetime.datetime.strptime(value, _LEGACY_STORAGE_FORMAT_DATE_ONLY).strftime(_LEGACY_DISPLAY_FORMAT_DATE_ONLY)
    except ValueError:
        return value


def format_scan_timestamp(abs_path, creation_date_raw="", embedded=""):
    """
    Formatierte Anzeige (DD.MM.YYYY HH:MM) fürs Treeview: bevorzugt den bereits im PDF als
    KID_SCAN gespeicherten Wert (`embedded`, einmal fixiert - siehe pdf_handler.
    write_custom_metadata), sonst das PDF-eigene creationDate, sonst die Datei-
    Erstellungszeit (siehe resolve_scan_timestamp). Leerer String, wenn nichts ermittelbar ist.
    """
    if embedded:
        return format_storage_value(embedded)
    dt = resolve_scan_timestamp(creation_date_raw, abs_path)
    return dt.strftime(DISPLAY_FORMAT) if dt else ""
