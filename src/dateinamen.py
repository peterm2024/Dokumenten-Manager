"""
Dateinamen aufräumen (Stufe 2 der Dateinamen-Entschärfung, Nutzerwunsch 11.09.2026).

Reine Logik für das Tool `tools/dateinamen_aufraeumen.py`: Vorschlag aus Dokumentdatum +
Titel ('JJJJMMTT_Titel.pdf', dasselbe Schema wie die Vollautomatik), Umbenennen einer
Datei mit Einbrennen des bisherigen Namens als KID_NAME (siehe
`PDFHandler.parse_kid_original_name`) und Rückbenennen auf diesen Originalnamen.

Grundregel des Nutzers: Umbenennen passiert NUR für ausdrücklich angehakte Dateien,
Vorschläge sind bearbeitbar, und der allererste Name geht nie verloren.
Die Dateisystem-/PDF-Zugriffe sind als Parameter austauschbar, damit die Regeln ohne
echte PDFs testbar bleiben.
"""
import os
import re

import auto_pilot
from pdf_handler import PDFHandler
from text_quality import looks_garbled

# Zeichen, die Windows in Dateinamen nicht erlaubt (gleiche Liste wie FileOperations.rename_file)
_VERBOTEN = r'\/:*?"<>|'
_DATUM = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bereinige_dateiname(name):
    """
    Macht aus einer Nutzereingabe einen gültigen PDF-Dateinamen: verbotene Zeichen weg,
    Leerraum an den Rändern weg, Endung '.pdf' sicherstellen. Leer, wenn nichts übrig bleibt.
    """
    name = "".join(c for c in (name or "") if c not in _VERBOTEN).strip().rstrip(".")
    if not name:
        return ""
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


def baue_vorschlag(datum, titel):
    """'JJJJMMTT_Titel.pdf' aus plausiblem Datum und nicht-leerem Titel, sonst ""."""
    datum = (datum or "").strip()
    titel = (titel or "").strip()
    if not titel or not _DATUM.match(datum) or not auto_pilot._datum_ist_plausibel(datum):
        return ""
    return auto_pilot.baue_dateiname(datum, titel)


def vorschlag_aus_metadaten(meta):
    """
    Dateinamen-Vorschlag 'JJJJMMTT_Titel.pdf' aus den PDF-Metadaten (Dokumentdatum +
    Titel). "" wenn Datum oder Titel fehlen - dann gibt es nichts Sinnvolles vorzuschlagen
    und die Zeile bleibt im Tool ohne Haken.
    """
    return baue_vorschlag(meta.get("KID_DokumentenDatum"), meta.get("title"))


def titel_verdaechtig(titel):
    """
    Sieht der Titel nach Datenmüll aus, so dass ein KI-Titel nötig ist? Drei Muster
    (Nutzerfund 11.09.2026, "20241215_l='n' =l"), geprüft nach Abzug eines Datums-Präfixes
    'JJJJMMTT_': OCR-Kauderwelsch mit langen Konsonantenketten (`text_quality.looks_garbled`);
    überwiegend Ziffern/Sonderzeichen (weniger als 40 % der Nicht-Leerzeichen sind
    Buchstaben, z.B. "463,8080"); oder weniger als die Hälfte der Wörter sind "wortartig"
    (mindestens zwei Buchstaben, nur Buchstaben/Ziffern und übliche Satzzeichen - "l='n'",
    "_nA_l", "y^" fallen durch). Leer zählt auch als Müll.
    """
    titel = (titel or "").strip()
    if not titel:
        return True
    if looks_garbled(titel):
        return True
    kern = re.sub(r"^\d{8}[_ -]*", "", titel)
    zeichen = [c for c in kern if not c.isspace()]
    if not zeichen:
        return True
    buchstaben = sum(1 for c in zeichen if c.isalpha())
    # 0,4 statt 0,5: Titel mit Aktenzeichen und Datum ("Str.Nr. 107_250_90485 Ihr Schreiben
    # vom 18.1.2017") haben legitim viele Ziffern und sollen nicht orange werden
    if buchstaben / len(zeichen) < 0.4:
        return True
    woerter = kern.split()
    wortartig = sum(1 for w in woerter if _WORTARTIG.fullmatch(w) and sum(c.isalpha() for c in w) >= 2)
    return wortartig / len(woerter) < 0.5


# Ein "wortartiges" Token: Buchstaben/Ziffern (kein Unterstrich) plus übliche Satzzeichen
_WORTARTIG = re.compile(r"[^\W_](?:[^\W_]|[\-.,/&()':;+§])*", re.UNICODE)


def zeile_fuer(pdf_path, meta=None):
    """
    Eine Tabellenzeile für das Tool: aktueller Name, Originalname (aus dem PDF), Vorschlag,
    Titel, Datum (aus dem PDF, ersatzweise aus dem Dateinamen-Präfix - nur als Vorbelegung
    für den Vorschlag, nie ins PDF geschrieben), Verdacht auf Müll-Titel.
    `meta` kann vorgegeben werden (Tests); sonst wird das PDF gelesen.
    """
    if meta is None:
        meta = PDFHandler.get_metadata(pdf_path) or {}
    titel = (meta.get("title") or "").strip()
    datum = (meta.get("KID_DokumentenDatum") or "").strip() or auto_pilot.datum_aus_dateiname(pdf_path)
    return {
        "pfad": pdf_path,
        "name": os.path.basename(pdf_path),
        "originalname": (meta.get("KID_Originalname") or "").strip(),
        "vorschlag": baue_vorschlag(datum, titel),
        "titel": titel,
        "datum": datum,
        "verdaechtig": titel_verdaechtig(titel),
        "ki_titel": "",
    }


def sammle_pdfs(ordner, rekursiv=False, ist_papierkorb=None):
    """PDF-Pfade eines Ordners (optional mit Unterordnern), Papierkorb ausgenommen, sortiert."""
    pdfs = []
    if not ordner or not os.path.isdir(ordner):
        return pdfs
    if rekursiv:
        for wurzel, dirs, files in os.walk(ordner):
            if ist_papierkorb and ist_papierkorb(wurzel):
                dirs[:] = []
                continue
            pdfs.extend(os.path.join(wurzel, f) for f in files if f.lower().endswith(".pdf"))
    else:
        try:
            pdfs = [os.path.join(ordner, f) for f in os.listdir(ordner)
                    if f.lower().endswith(".pdf") and os.path.isfile(os.path.join(ordner, f))]
        except OSError:
            return []
    return sorted(pdfs, key=lambda p: os.path.normcase(p))


def benenne_um(pfad, neuer_name, schreibe_metadaten=None, umbenennen=os.rename, existiert=os.path.exists,
               zusatz_metadaten=None):
    """
    Benennt EINE Datei im selben Ordner um und brennt vorher den bisherigen Namen als
    KID_NAME ins PDF (nur beim ersten Mal - `_merge_kid_metadata` lässt einen vorhandenen
    Originalnamen unangetastet). Liefert (neuer_pfad, fehler): bei Erfolg ist fehler "",
    bei "nichts zu tun" (gleicher Name) kommt der alte Pfad zurück.

    zusatz_metadaten: weitere Felder, die im selben Schreibvorgang ins PDF kommen - z.B.
    {"title": KI-Titel}, damit Dateiname und Titel nach einem KI-Vorschlag zusammenpassen.

    Kein automatisches '_1'-Anhängen: Ein Konflikt ist hier ein Nutzer-Fehler in einer
    Tabelle, die er gerade vor sich hat - er soll den Namen selbst anpassen.
    """
    schreibe_metadaten = schreibe_metadaten or (lambda p, d: PDFHandler.write_custom_metadata(p, d, still=True))
    neuer_name = bereinige_dateiname(neuer_name)
    if not neuer_name:
        return pfad, "Leerer Dateiname."
    alter_name = os.path.basename(pfad)
    if neuer_name == alter_name:
        return pfad, ""
    ziel = os.path.join(os.path.dirname(pfad), neuer_name)
    # Nur Groß-/Kleinschreibung anders: Windows erlaubt das Umbenennen, exists() wäre True
    if os.path.normcase(neuer_name) != os.path.normcase(alter_name) and existiert(ziel):
        return pfad, f"'{neuer_name}' existiert bereits."
    daten = dict(zusatz_metadaten or {})
    daten["KID_Originalname"] = alter_name
    if not schreibe_metadaten(pfad, daten):
        return pfad, "Originalname konnte nicht ins PDF geschrieben werden (Datei geöffnet oder geschützt?) - nicht umbenannt."
    try:
        umbenennen(pfad, ziel)
    except OSError as e:
        return pfad, f"Umbenennen fehlgeschlagen: {e}"
    return ziel, ""


def stelle_wieder_her(pfad, originalname=None, umbenennen=os.rename, existiert=os.path.exists):
    """
    Benennt eine Datei auf ihren im PDF gespeicherten Originalnamen zurück. `originalname`
    kann vorgegeben werden (aus der Tabelle); sonst wird er aus dem PDF gelesen. Kein
    Metadaten-Schreiben nötig: der Originalname steht ja schon drin.
    Liefert (neuer_pfad, fehler).
    """
    if originalname is None:
        originalname = (PDFHandler.get_metadata(pfad) or {}).get("KID_Originalname", "")
    originalname = bereinige_dateiname(originalname)
    if not originalname:
        return pfad, "Kein Originalname im PDF gespeichert."
    alter_name = os.path.basename(pfad)
    if originalname == alter_name:
        return pfad, ""
    ziel = os.path.join(os.path.dirname(pfad), originalname)
    if os.path.normcase(originalname) != os.path.normcase(alter_name) and existiert(ziel):
        return pfad, f"'{originalname}' existiert bereits."
    try:
        umbenennen(pfad, ziel)
    except OSError as e:
        return pfad, f"Umbenennen fehlgeschlagen: {e}"
    return ziel, ""
