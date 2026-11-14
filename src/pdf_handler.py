import io
import logging
import os
import re
import secrets
from datetime import datetime
import tkinter.messagebox as mb

import mail_lesen
import scan_date
import sicher_speichern
import text_quality

try:
    import fitz

    # Schaltet die gesprächigen C-Level Warnungen im Terminal stumm
    fitz.TOOLS.mupdf_display_errors(False)

    from PIL import Image, ImageTk
    HAS_PREVIEW = True
except ImportError:
    HAS_PREVIEW = False

_log = logging.getLogger("DocManager")

MAX_MAIL_SEITEN = 300


class MailZuLang(ValueError):
    """Das HTML einer Mail lässt sich nicht auf MAX_MAIL_SEITEN Seiten verteilen."""


class PDFHandler:
    # --- Vorkompilierte Konstanten für massiven Performance-Boost ---
    GERMAN_MONTHS = {
        'januar': 1, 'jan': 1, 'jänner': 1, 'februar': 2, 'feb': 2,
        'märz': 3, 'marz': 3, 'mär': 3, 'april': 4, 'apr': 4,
        'mai': 5, 'juni': 6, 'jun': 6, 'juli': 7, 'jul': 7,
        'august': 8, 'aug': 8, 'september': 9, 'sep': 9, 'sept': 9,
        'oktober': 10, 'okt': 10, 'november': 11, 'nov': 11, 'dezember': 12, 'dez': 12
    }

    PRIORITY_KEYWORDS = ['rechnungsdatum', 'datum', 'belegdatum', 'erstelltam', 'date']
    PATTERN_DATE_SPLIT = re.compile(r'[-.,/]')

    # Regex vorkompilieren (beschleunigt die Suche bei vielen Texten enorm)
    PATTERNS_NUMERIC = [
        re.compile(r'\b(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{4})\b'),
        re.compile(r'\b(\d{1,2})\s*\.\s*(\d{1,2})\s*\.\s*(\d{2})\b')
    ]
    PATTERN_TEXT_MONTH = re.compile(r'\b(\d{1,2})\.?\s+([A-Za-zÄÖÜäöüß]+)\s+(\d{4})\b')
    PATTERN_PARTIAL_TEXT = re.compile(r'\b([A-Za-zÄÖÜäöüß]+)\s+(\d{4})\b')
    PATTERN_PARTIAL_NUM = re.compile(r'\b(\d{1,2})\s*[\./-]\s*(\d{4})\b')

    @staticmethod
    def is_supported():
        return HAS_PREVIEW

    @staticmethod
    def parse_kid_subject(subject_text):
        """
        Zerlegt das subject-Feld in seine KID-Bestandteile. Historisch stand dort nur
        'KID_DATE:<datum>'; inzwischen können mehrere Felder mit '|' getrennt stehen,
        z.B. 'KID_DATE:2026-05-12|KID_SCAN:2026-04-13 14:32'. Alte Ein-Feld-Dateien
        werden weiterhin korrekt gelesen (abwärtskompatibel).
        :return: Tuple (dokument_datum, scan_zeitpunkt), fehlende Teile als "".
        """
        doc_date, scan_ts = "", ""
        if subject_text:
            for part in subject_text.split("|"):
                part = part.strip()
                if part.startswith("KID_DATE:"):
                    doc_date = part[len("KID_DATE:"):].strip()
                elif part.startswith("KID_SCAN:"):
                    scan_ts = part[len("KID_SCAN:"):].strip()
        return doc_date, scan_ts

    @staticmethod
    def parse_kid_original_name(subject_text):
        """
        Ursprünglicher Dateiname aus dem subject-Feld ('KID_NAME:<name>'), "" wenn keiner
        gespeichert ist. Eigenes Feld statt drittem Tuple-Element von parse_kid_subject,
        damit die bestehenden Aufrufer unverändert bleiben. Windows-Dateinamen enthalten
        weder '|' noch ':', die Trennzeichen sind also sicher.
        """
        for part in (subject_text or "").split("|"):
            part = part.strip()
            if part.startswith("KID_NAME:"):
                return part[len("KID_NAME:"):].strip()
        return ""

    @staticmethod
    def parse_kid_id(subject_text):
        """Eindeutige Dokument-ID aus dem subject-Feld ('KID_ID:<id>'), "" wenn keine vergeben ist."""
        for part in (subject_text or "").split("|"):
            part = part.strip()
            if part.startswith("KID_ID:"):
                return part[len("KID_ID:"):].strip()
        return ""

    @staticmethod
    def parse_kid_absender(subject_text):
        """Absender, wie ihn die Ablage gelesen hat ('KID_ABSENDER:<text>'), "" wenn keiner gespeichert ist."""
        for part in (subject_text or "").split("|"):
            part = part.strip()
            if part.startswith("KID_ABSENDER:"):
                return part[len("KID_ABSENDER:"):].strip()
        return ""

    @staticmethod
    def parse_kid_grund(subject_text):
        """Warum die Vollautomatik das Dokument vorgelegt hat ('KID_GRUND:<text>'), "" wenn keiner gespeichert ist."""
        for part in (subject_text or "").split("|"):
            part = part.strip()
            if part.startswith("KID_GRUND:"):
                return part[len("KID_GRUND:"):].strip()
        return ""

    @staticmethod
    def parse_kid_feld(subject_text, name):
        """Ein beliebiges KID-Feld ('KID_<NAME>:<wert>') aus dem subject-Feld, "" wenn es fehlt - für die Felder des
        Mail-Imports (KID_MAILID, KID_RICHTUNG, KONZEPT_MAIL_IMPORT.md)."""
        for part in (subject_text or "").split("|"):
            part = part.strip()
            if part.startswith(f"KID_{name}:"):
                return part[len(f"KID_{name}:"):].strip()
        return ""

    @staticmethod
    def bereinige_absender(text):
        """Absender als ein subject-Feld: '|' ist das Trennzeichen, Zeilenumbrüche/Mehrfach-Leerraum raus."""
        return " ".join((text or "").replace("|", " ").split())

    @staticmethod
    def build_kid_subject(doc_date, scan_ts, original_name="", kid_id="", absender="", grund="", mail_id="",
                          richtung="", erfasst="", einzeln="", eigen=""):
        """Gegenstück zu parse_kid_subject: baut den subject-String aus den KID-Feldern (leere Teile werden weggelassen)."""
        parts = []
        if doc_date:
            parts.append(f"KID_DATE:{doc_date}")
        if scan_ts:
            parts.append(f"KID_SCAN:{scan_ts}")
        if original_name:
            parts.append(f"KID_NAME:{original_name}")
        if kid_id:
            parts.append(f"KID_ID:{kid_id}")
        if absender:
            parts.append(f"KID_ABSENDER:{absender}")
        if grund:
            parts.append(f"KID_GRUND:{grund}")
        if mail_id:
            parts.append(f"KID_MAILID:{mail_id}")
        if richtung:
            parts.append(f"KID_RICHTUNG:{richtung}")
        if erfasst:
            parts.append(f"KID_ERFASST:{erfasst}")
        if einzeln:
            parts.append(f"KID_EINZELN:{einzeln}")      # nur bis zur Ablage nötig, ein späteres Speichern darf es verlieren
        if eigen:
            parts.append(f"KID_EIGEN:{eigen}")          # ebenso (mail_lesen.eigene_namen)
        return "|".join(parts)

    # Zeichen der Dokument-ID: Großbuchstaben und Ziffern OHNE Verwechsler (0/O, 1/I/L) - die ID
    # wird in Notizen und Rückmeldungen abgetippt oder vorgelesen (Peter 25.10.2026). 31 Zeichen,
    # 8 Stellen: rund 850 Milliarden Möglichkeiten.
    KID_ID_ZEICHEN = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"

    @staticmethod
    def neue_kid_id():
        """Neue zufällige Dokument-ID im Format 'XXXX-XXXX' (z.B. 'K7M4-Q2XP')."""
        zeichen = "".join(secrets.choice(PDFHandler.KID_ID_ZEICHEN) for _ in range(8))
        return f"{zeichen[:4]}-{zeichen[4:]}"

    @staticmethod
    def ensure_kid_id(pdf_path):
        """
        Eindeutige Dokument-ID lesen oder EINMALIG vergeben (`neue_kid_id`; ältere Dokumente
        tragen noch 12 Hex-Zeichen - bleiben gültig) und als 'KID_ID:<id>' ins subject-Feld
        einbrennen. Gedacht für Gedächtnisse, die ein Dokument über Umbenennen/Verschieben/
        Metadaten-Änderungen hinweg wiedererkennen müssen (dubletten_geprueft.py) - der
        Datei-Hash ändert sich bei jedem Speichern, die ID nie. Seit 25.10.2026 vergibt auch
        jedes Speichern die ID mit (_merge_kid_metadata); hier für Dokumente, die nie
        gespeichert wurden.
        :return: die ID oder "" (Datei nicht schreibbar - still, keine Messagebox)
        """
        meta = PDFHandler.get_metadata(pdf_path)
        kid_id = (meta.get("KID_ID") or "").strip()
        if kid_id:
            return kid_id
        kid_id = PDFHandler.neue_kid_id()
        return kid_id if PDFHandler.write_custom_metadata(pdf_path, {"KID_ID": kid_id}, still=True) else ""

    @staticmethod
    def ersetze_kid_id(pdf_path):
        """
        Vergibt eine NEUE Dokument-ID, auch wenn schon eine da ist - nur für Kopien, die die ID
        ihres Originals mitgebracht haben (Werkzeug „Dokument-IDs vergeben“, 25.10.2026).
        :return: die neue ID oder "" (Datei nicht schreibbar - still)
        """
        kid_id = PDFHandler.neue_kid_id()
        return kid_id if PDFHandler.write_custom_metadata(pdf_path, {"KID_ID_ERSETZEN": kid_id}, still=True) else ""

    @staticmethod
    def schreibe_mail_pdf(ziel, seite_html, stile, bilder, eml, felder, mindest_zeichen=0):
        """
        Mail-PDF des Mail-Imports (KONZEPT_MAIL_IMPORT.md, E1): die Seiten aus dem entschärften HTML
        (mail_lesen.seite_html, PyMuPDF Story), Schriften gekürzt (S4: 70 → 28 KB je kurzer Mail), die Original-.eml
        als eingebettete Datei „Original-Mail“ und die KID-Felder gleich mit (`felder`: title, author, keywords,
        KID_DokumentenDatum, KID_Absender, KID_MailID, KID_Richtung). Schreibt über eine Temp-Datei und überschreibt
        nie eine vorhandene Datei (FileExistsError). `bilder` = {cid: (Archivname, Bytes)}.
        :param mindest_zeichen: Stehen weniger Buchstaben und Ziffern auf den Seiten, gilt die Darstellung als
            gescheitert (MailZuLang): Die Story verliert Text mancher Layout-Tabellen ohne Fehler (FALLSTRICKE #108)
        :return: die vergebene Dokument-ID
        """
        if os.path.exists(ziel):
            raise FileExistsError(ziel)
        archiv = fitz.Archive()
        for name, daten in (bilder or {}).values():
            archiv.add(daten, name)
        # Mail-Stile zuerst, unsere danach - der Kopfblock sieht so immer gleich aus
        story = fitz.Story(html=seite_html, user_css=(stile or "") + "\n" + mail_lesen.CSS, archive=archiv)
        puffer = io.BytesIO()
        schreiber = fitz.DocumentWriter(puffer)
        seite = fitz.paper_rect("a4")
        weiter, seiten = True, 0
        while weiter:
            # Passt ein Block auf keine Seite (riesiges Polster, riesige Schrift), verlangt die Story endlos neue
            # Seiten (FALLSTRICKE #103)
            if seiten >= MAX_MAIL_SEITEN:
                raise MailZuLang(f"Mail passt nicht auf {MAX_MAIL_SEITEN} Seiten")
            geraet = schreiber.begin_page(seite)
            weiter, _ = story.place(seite + (50, 50, -50, -50))
            story.draw(geraet)
            schreiber.end_page()
            seiten += 1
        schreiber.close()
        kid_id = PDFHandler.neue_kid_id()
        jetzt = scan_date.to_storage(datetime.now())
        with fitz.open("pdf", puffer.getvalue()) as doc:
            if sum(mail_lesen.zeichenzahl(s.get_text()) for s in doc) < mindest_zeichen:
                raise MailZuLang(f"Weniger als {mindest_zeichen} Zeichen auf den Seiten")
            doc.subset_fonts()
            doc.embfile_add("Original-Mail", eml, filename="original.eml", desc="Original-Mail (.eml)")
            b = PDFHandler.bereinige_absender
            doc.set_metadata({
                "title": felder.get("title") or "", "author": felder.get("author") or "",
                "keywords": felder.get("keywords") or "", "creator": "KID Mail-Import", "producer": "PyMuPDF",
                "subject": PDFHandler.build_kid_subject(
                    felder.get("KID_DokumentenDatum") or "", jetzt, "", kid_id,
                    b(felder.get("KID_Absender") or ""), "", b(felder.get("KID_MailID") or ""),
                    b(felder.get("KID_Richtung") or ""), jetzt, b(felder.get("KID_Einzeln") or ""),
                    b(felder.get("KID_Eigen") or "")),
            })
            tmp = ziel + ".tmp"
            try:
                doc.save(tmp, garbage=3, deflate=True)
            except Exception:
                if os.path.exists(tmp):
                    os.remove(tmp)                  # keine halbe Temp-Datei im Posteingang zurücklassen
                raise
        os.replace(tmp, ziel)
        return kid_id

    @staticmethod
    def schreibe_anhang_pdf(ziel, daten, felder):
        """
        PDF-Anhang einer Mail als eigenes Dokument (E2: eine Rechnung per Mail soll wie eine gescannte auffindbar
        sein), verknüpft über dieselbe KID_MAILID. Nur echte, lesbare PDFs (sonst ValueError); verschlüsselte bleiben
        unverändert (ohne KID-Felder - lieber das Original als gar nichts). Überschreibt nie (FileExistsError).
        :return: True, wenn die KID-Felder geschrieben werden konnten
        """
        if os.path.exists(ziel):
            raise FileExistsError(ziel)
        try:
            with fitz.open("pdf", daten) as doc:
                if doc.page_count < 1:
                    raise ValueError("PDF ohne Seiten")
                geschuetzt = doc.needs_pass or doc.is_encrypted
        except (RuntimeError, fitz.FileDataError) as e:
            raise ValueError(f"kein lesbares PDF: {e}") from e
        tmp = ziel + ".tmp"
        with open(tmp, "wb") as f:
            f.write(daten)
        os.replace(tmp, ziel)
        if geschuetzt:
            return False
        return PDFHandler.write_custom_metadata(ziel, {k: v for k, v in felder.items() if v}, still=True)

    @staticmethod
    def hole_eml(filepath):
        """Die eingebettete Original-Mail eines Mail-PDFs (Bytes) oder None."""
        try:
            with fitz.open(filepath) as doc:
                return doc.embfile_get("Original-Mail") if "Original-Mail" in doc.embfile_names() else None
        except Exception:
            return None

    @staticmethod
    def scan_tag(filepath):
        """
        Scan-Tag als 'JJJJ-MM-TT' (Peter 04.11.2026: „wenn kein Datum erkannt wird, einfach das Scandatum“, Prüfplatz
        begleitet_erfassen): der eingebrannte KID_SCAN, sonst das creationDate des Scanners, sonst die Datei-
        Erstellungszeit (scan_date.resolve_scan_timestamp). Leer, wenn nichts ermittelbar ist.
        """
        if not HAS_PREVIEW or not os.path.exists(filepath):
            return ""
        try:
            with open(filepath, "rb") as f:
                pdf_bytes = f.read()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                meta = doc.metadata or {}
        except Exception:
            meta = {}
        _datum, scan = PDFHandler.parse_kid_subject(meta.get("subject") or "")
        if scan:
            return scan[:10]
        dt = scan_date.resolve_scan_timestamp(meta.get("creationDate") or "", filepath)
        return dt.strftime("%Y-%m-%d") if dt else ""

    @staticmethod
    def get_metadata(filepath):
        """
        Liest Titel, Keywords/Tags und das KI-erkannte Dokumentdatum aus einer PDF-Datei.
        Das Datum ist nicht als eigenes PDF-Metadatenfeld gespeichert, sondern wird aus dem
        'subject'-Feld zurückgewonnen, das den Präfix 'KID_DATE:' trägt (siehe write_custom_metadata).
        Gibt bei fehlender Datei/Bibliothek oder Lesefehler leere Strings zurück statt zu crashen.
        """
        if not HAS_PREVIEW or not os.path.exists(filepath):
            return {"title": "", "keywords": "", "KID_DokumentenDatum": "", "KID_ScanZeitpunkt": ""}

        try:
            # --- FIX: Memory-Stream ---
            with open(filepath, "rb") as f:
                pdf_bytes = f.read()

            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                meta = doc.metadata.copy()

                # Alle None-Werte in leere Strings umwandeln
                for key in meta:
                    if meta[key] is None:
                        meta[key] = ""

                # KID-Felder aus dem 'subject'-Feld rückübersetzen (siehe parse_kid_subject)
                doc_date, scan_ts = PDFHandler.parse_kid_subject(meta.get("subject", ""))
                meta["KID_DokumentenDatum"] = doc_date
                meta["KID_ScanZeitpunkt"] = scan_ts
                meta["KID_Originalname"] = PDFHandler.parse_kid_original_name(meta.get("subject", ""))
                meta["KID_ID"] = PDFHandler.parse_kid_id(meta.get("subject", ""))
                meta["KID_Absender"] = PDFHandler.parse_kid_absender(meta.get("subject", ""))
                meta["KID_Grund"] = PDFHandler.parse_kid_grund(meta.get("subject", ""))
                meta["KID_MailID"] = PDFHandler.parse_kid_feld(meta.get("subject", ""), "MAILID")
                meta["KID_Richtung"] = PDFHandler.parse_kid_feld(meta.get("subject", ""), "RICHTUNG")
                meta["KID_Einzeln"] = PDFHandler.parse_kid_feld(meta.get("subject", ""), "EINZELN")
                meta["KID_Eigen"] = PDFHandler.parse_kid_feld(meta.get("subject", ""), "EIGEN")
                meta["KID_Erfasst"] = PDFHandler.parse_kid_feld(meta.get("subject", ""), "ERFASST")

                return meta
        except Exception as e:
            _log.warning(f"Fehler beim Lesen der Metadaten: {e}")
            return {"title": "", "keywords": "", "KID_DokumentenDatum": "", "KID_ScanZeitpunkt": ""}

    @staticmethod
    def get_document_info(filepath):
        """
        Alles, was das Eigenschaften-Panel (dokument_eigenschaften.py) über ein PDF wissen
        will, in EINEM Lesevorgang: die kompletten PDF-Metadaten (wie get_metadata, inkl.
        der KID-Felder), Seitenzahl und Schutz-Flags. Liefert bei Fehlern ein Dict mit
        gefülltem 'fehler' statt zu werfen - das Panel zeigt den Text dann einfach an.
        """
        info = {"title": "", "keywords": "", "KID_DokumentenDatum": "", "KID_ScanZeitpunkt": "",
                "seiten": 0, "schutz": "", "fehler": ""}
        if not HAS_PREVIEW:
            info["fehler"] = "PyMuPDF ist nicht installiert."
            return info
        if not os.path.exists(filepath):
            info["fehler"] = "Datei nicht gefunden."
            return info
        try:
            with open(filepath, "rb") as f:
                pdf_bytes = f.read()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                meta = {k: (v if v is not None else "") for k, v in doc.metadata.items()}
                doc_date, scan_ts = PDFHandler.parse_kid_subject(meta.get("subject", ""))
                info.update(meta)
                info["KID_DokumentenDatum"] = doc_date
                info["KID_ScanZeitpunkt"] = scan_ts
                info["KID_Originalname"] = PDFHandler.parse_kid_original_name(meta.get("subject", ""))
                info["KID_ID"] = PDFHandler.parse_kid_id(meta.get("subject", ""))
                info["KID_Absender"] = PDFHandler.parse_kid_absender(meta.get("subject", ""))
                info["KID_Grund"] = PDFHandler.parse_kid_grund(meta.get("subject", ""))
                info["KID_MailID"] = PDFHandler.parse_kid_feld(meta.get("subject", ""), "MAILID")
                info["KID_Richtung"] = PDFHandler.parse_kid_feld(meta.get("subject", ""), "RICHTUNG")
                info["KID_Erfasst"] = PDFHandler.parse_kid_feld(meta.get("subject", ""), "ERFASST")
                info["seiten"] = doc.page_count
                schutz = []
                if doc.needs_pass or doc.is_encrypted:
                    schutz.append("verschlüsselt")
                elif not doc.permissions & fitz.PDF_PERM_MODIFY:
                    schutz.append("schreibgeschützt")
                try:
                    if doc.get_sigflags() > 0:
                        schutz.append("signiert")
                except Exception:
                    pass
                info["schutz"] = ", ".join(schutz)
        except Exception as e:
            info["fehler"] = str(e)
        return info

    @staticmethod
    def get_write_protection(pdf_path):
        """
        Prüft VOR einem Schreibzugriff, ob das PDF besonders geschützt ist (siehe
        KONZEPT_PDF_ARTEN.md, Abschnitte 1.5/1.6). Liefert:
        - "verschlüsselt":   Nutzer-Passwort nötig - wir können nicht einmal lesen.
        - "schreibgeschützt": Besitzer-Passwort verbietet Änderungen. PyMuPDF KÖNNTE
                              das oft ignorieren, wir respektieren aber bewusst die
                              Absicht des Erstellers.
        - "signiert":        digitale Signatur vorhanden (SigFlags im AcroForm) - ein
                              Datei-Neuaufbau würde sie unwiderruflich zerstören, nur
                              inkrementelles Anhängen ist erlaubt.
        - None:              normal beschreibbar (auch bei Lesefehlern - die behandeln
                              die Schreibwege selbst mit ihren bestehenden Fehlerpfaden).
        """
        if not HAS_PREVIEW or not os.path.exists(pdf_path):
            return None
        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                if doc.needs_pass or doc.is_encrypted:
                    return "verschlüsselt"
                if not doc.permissions & fitz.PDF_PERM_MODIFY:
                    return "schreibgeschützt"
                # SigFlags >= 1 heißt konservativ "Signatur(-Feld) vorhanden" - auch ein
                # noch unsigniertes Signaturfeld landet damit auf dem (funktionierenden)
                # inkrementellen Schreibweg, das ist der sichere Fehler. Das gilt auch, wenn die Prüfung selbst
                # scheitert: Der Neuaufbau zerstört eine Signatur unwiderruflich.
                try:
                    if doc.get_sigflags() > 0:
                        return "signiert"
                except Exception:
                    return "signiert"
        except Exception:
            return None
        return None

    @staticmethod
    def save_metadata(filepath, title, keywords, still=False, datum=None):
        """
        Speichert Titel und Tags im PDF. Nutzt die sichere Temp-File-Methode,
        damit auch bei PDFs ohne vorherige Metadaten-Struktur die Felder erzwungen werden.
        :param still: True = keine Messagebox bei Fehlern (siehe write_custom_metadata) -
                      fürs debouncte Auto-Save, das nicht mit einem modalen Fehler-Popup
                      in die laufende Eingabe platzen soll (Live-Fund 06.09.2026).
        :param datum: optional 'JJJJ-MM-TT' - wird im selben Schreibvorgang als
                      KID_DokumentenDatum mitgespeichert (FALLSTRICKE #86).
        """
        if not HAS_PREVIEW:
            return False, "PyMuPDF ist nicht installiert."

        try:
            felder = {"title": title, "keywords": keywords}
            if datum:
                felder["KID_DokumentenDatum"] = datum
            # Wir leiten den Speichern-Befehl direkt auf unsere kugelsichere Methode um!
            erfolg = PDFHandler.write_custom_metadata(filepath, felder, still=still)
            
            if erfolg:
                return True, "Metadaten erfolgreich gespeichert!"
            else:
                return False, "Fehler beim Überschreiben der PDF-Datei."
        except Exception as e:
            return False, str(e)

    # Monatsnamen für die ausgeschriebenen Datumsformen des Markers ("12. Dezember 2025")
    _MONATSNAMEN = {
        "01": ["Januar", "Jan", "Jan."], "02": ["Februar", "Feb", "Feb."],
        "03": ["März", "Mär"], "04": ["April", "Apr", "Apr."],
        "05": ["Mai", "Mai."], "06": ["Juni", "Jun", "Jun."],
        "07": ["Juli", "Jul", "Jul."], "08": ["August", "Aug", "Aug."],
        "09": ["September", "Sep", "Sept.", "Sep."], "10": ["Oktober", "Okt", "Okt."],
        "11": ["November", "Nov", "Nov."], "12": ["Dezember", "Dez", "Dez."],
    }

    @staticmethod
    def datums_suchformen(kid_date):
        """
        Alle Schreibweisen, unter denen der Datums-Marker ein gespeichertes Datum
        ('JJJJ-MM-TT') in der Textebene sucht: numerisch (12.05.2026, 12.5.26, ...) und
        ausgeschrieben (12. Mai 2026, Mai 2026). Seit 30.08.2026 zusätzlich die
        "zusammengeklebten" Formen ohne Leerzeichen (Mai2026, 12.Mai2026) - schlechte
        OCR-Textebenen verschlucken das Leerzeichen gern ('3:*Februar2020'), und die
        Suche von PyMuPDF ist zwar groß/klein-unempfindlich, aber nicht leerzeichen-tolerant.
        Ungültiges Datum -> leere Liste.
        """
        try:
            y, m, d = kid_date.split("-")
        except (AttributeError, ValueError):
            return []
        m_str = m.zfill(2)
        formen = [
            f"{d}.{m}.{y}",                  # 12.05.2026
            f"{d}.{m}.{y[-2:]}",             # 12.05.26
            f"{int(d)}.{int(m)}.{y}",        # 12.5.2026
            f"{int(d)}.{int(m)}.{y[-2:]}",   # 12.5.26
        ]
        for name in PDFHandler._MONATSNAMEN.get(m_str, []):
            formen.append(f"{int(d)}. {name} {y}")   # 12. Dezember 2025
            formen.append(f"{name} {y}")             # Dezember 2025
            formen.append(f"{int(d)}.{name}{y}")     # 12.Dezember2025 (OCR ohne Leerzeichen)
            formen.append(f"{name}{y}")              # Dezember2025
        # Reihenfolge behalten, Dubletten (z.B. bei einstelligem Tag) entfernen
        return list(dict.fromkeys(formen))

    @staticmethod
    def marker_boxen_bereinigen(boxen, mindest_ueberlappung=0.5):
        """
        Entfernt aus einer Liste von Treffer-Rechtecken (fitz.Rect) alle, die zum großen
        Teil in einem größeren Rechteck liegen: Schnittfläche / eigene Fläche >=
        mindest_ueberlappung. Größte Boxen zuerst, damit "12. Mai 2026" gewinnt und das
        darin enthaltene "Mai 2026" wegfällt; Reihenfolge der behaltenen Boxen ist die
        Größenreihenfolge. Leere/entartete Rechtecke werden übersprungen.
        """
        behalten = []
        for box in sorted(boxen, key=lambda r: r.get_area(), reverse=True):
            flaeche = box.get_area()
            if flaeche <= 0:
                continue
            doppelt = False
            for gross in behalten:
                schnitt = (gross & box).get_area()
                if schnitt / flaeche >= mindest_ueberlappung:
                    doppelt = True
                    break
            if not doppelt:
                behalten.append(box)
        return behalten

    # Suchtreffer-Marker: hellblau statt gelb, blauer statt roter Rahmen - auf einen Blick
    # vom Datums-Marker unterscheidbar (Nutzerwunsch 11.09.2026: „wo steht das im Dokument?").
    TREFFER_FUELLUNG = (0.55, 0.85, 1.0)
    TREFFER_RAHMEN = (0.0, 0.2, 0.9)
    TREFFER_MAX_SEITEN = 300   # Seitensuche nach dem ersten Treffer: Obergrenze für Riesen-PDFs

    @staticmethod
    def suchtreffer_boxen(page, terms, matcher_fuer=None):
        """
        Liefert die Rechtecke (fitz.Rect) aller Fundstellen der Suchbegriffe auf einer Seite.
        Je Begriff zuerst die exakte Suche der Textebene (page.search_for, unabhängig von
        Groß-/Kleinschreibung, auch über Wortgrenzen wie „Kfz-Versicherung"); ohne exakten
        Fund die unscharfe Suche über die Wörter der Seite (und benachbarte Wortpaare, weil
        die Texterkennung Wörter gern zerreißt) mit demselben Matcher wie die Dokumentsuche
        (matcher_fuer(term) -> Prüf-Funktion, z.B. SearchManager.begriff_matcher) - so wird
        „Rechnnug" auch auf der Seite gefunden. Überlappende Boxen werden eingedampft.
        """
        boxen = []
        woerter = None
        for term in terms or []:
            term = (term or "").strip()
            if not term:
                continue
            exakt = [] if ("*" in term or "?" in term) else list(page.search_for(term))
            if exakt:
                boxen.extend(exakt)
                continue
            if matcher_fuer is None:
                continue
            matcher = matcher_fuer(term)
            if woerter is None:
                woerter = [(fitz.Rect(w[:4]), w[4]) for w in page.get_text("words")]
            for rect, wort in woerter:
                if matcher(wort):
                    boxen.append(rect)
            for (r1, w1), (r2, w2) in zip(woerter, woerter[1:]):
                if matcher(w1) or matcher(w2):
                    continue
                # zerrissenes Wort: nur Paare auf derselben Zeile zusammenkleben;
                # Phrase ("max mustermann"): auch über den Zeilenumbruch hinweg
                gleiche_zeile = r1.y0 < r2.y1 and r2.y0 < r1.y1
                if (gleiche_zeile and matcher(w1 + w2)) or matcher(w1 + " " + w2):
                    boxen.append(r1 | r2)
        return PDFHandler.marker_boxen_bereinigen(boxen)

    @staticmethod
    def finde_treffer_seite(pdf_path, terms, matcher_fuer=None, max_seiten=None):
        """
        Erste Seite (0-basiert), auf der einer der Suchbegriffe steht, sonst None - damit die
        Vorschau bei einem Suchtreffer gleich auf die Fundstelle springt. Durchsucht höchstens
        max_seiten (Standard TREFFER_MAX_SEITEN) Seiten. Treffer, die nur im verbesserten
        Text des Suchindex stehen (Stufen Fortgeschritten/Meister), sind hier nicht auffindbar.
        """
        if not HAS_PREVIEW or not terms or not os.path.exists(pdf_path):
            return None
        grenze = max_seiten or PDFHandler.TREFFER_MAX_SEITEN
        try:
            with fitz.open(pdf_path) as doc:
                for nr in range(min(len(doc), grenze)):
                    if PDFHandler.suchtreffer_boxen(doc.load_page(nr), terms, matcher_fuer):
                        return nr
        except Exception as e:
            _log.warning(f"Trefferseite nicht ermittelbar: {e}")
        return None

    @staticmethod
    def get_preview_image(pdf_path, display_width, display_height, fixed_zoom=None, start_page=0,
                          highlight_date=None, highlight_terms=None, matcher_fuer=None, treffer_boxen=None):
        """
        Rendert eine PDF-Seite als Tkinter-kompatibles Bild (öffnet die Datei per Memory-Stream,
        rührt die Originaldatei also nicht an). Wenn ein KID_DokumentenDatum gesetzt ist, wird
        zusätzlich versucht, dessen Textform (numerisch oder mit ausgeschriebenem Monatsnamen) auf
        der Seite zu finden und als gelber Marker einzuzeichnen ("virtueller Textmarker").
        highlight_terms (Liste der aktiven Suchbegriffe) werden zusätzlich hellblau markiert
        (siehe suchtreffer_boxen); wird eine Liste treffer_boxen übergeben, landen die
        gefundenen Rechtecke darin (der Aufrufer zählt sie für die Titelzeile).
        :return: Tuple (PhotoImage, zoom_pct, total_pages, gerenderte_seite) oder None bei Fehler.
        """
        if not HAS_PREVIEW or not os.path.exists(pdf_path):
            return None
            
        try:
            # --- Memory-Stream: Schützt die Originaldatei! ---
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
                
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            total_pages = len(doc)
            
            if total_pages == 0:
                doc.close()
                return None
                
            start_page = max(0, min(start_page, total_pages - 1))
            page0 = doc.load_page(0)
            
            if fixed_zoom:
                zoom = fixed_zoom
            else:
                rect = page0.rect
                zoom = display_width / rect.width
                
            zoom_pct = int(zoom * 100)
            mat = fitz.Matrix(zoom, zoom)
            
            page = doc.load_page(start_page)
            
            # --- Virtueller Textmarker für das KID_Datum ---
            # Bevorzugt das (evtl. nur vorgeschlagene, noch nicht gespeicherte) highlight_date,
            # damit auch der Datums-Vorschlag bei unbearbeiteten Dokumenten markiert wird;
            # sonst das gespeicherte Datum aus dem subject-Feld.
            kid_date = highlight_date
            if not kid_date:
                # parse_kid_subject statt rohem replace(): das subject-Feld kann inzwischen
                # mehrere KID-Felder enthalten (KID_DATE|KID_SCAN), siehe parse_kid_subject.
                kid_date, _ = PDFHandler.parse_kid_subject(doc.metadata.get("subject", ""))
            if kid_date:
                try:
                    search_terms = PDFHandler.datums_suchformen(kid_date)
                    # Auf der aktuellen Seite nach allen Begriffen suchen; überlappende
                    # Treffer (z.B. "Mai 2026" innerhalb von "12. Mai 2026") werden auf
                    # die größte Box eingedampft - sonst liegen zwei Marker samt zwei
                    # roten Rahmen übereinander (T4.9, 11.09.2026).
                    boxen = [rect_box for term in search_terms for rect_box in page.search_for(term)]
                    for rect_box in PDFHandler.marker_boxen_bereinigen(boxen):
                        marker = page.add_highlight_annot(rect_box)
                        marker.update() # Zeichnet das Gelb in den RAM
                        # Roter Rahmen zusätzlich zur gelben Füllung: macht auf einen Blick
                        # erkennbar, dass diese Markierung vom Programm stammt und nicht
                        # Teil des Original-Dokuments ist (z.B. ein echtes gelbes Textmarker-
                        # Feld im gescannten Original könnte sonst verwechselt werden).
                        # 2pt nach außen versetzt (überdeckt sonst Teile der Ziffern) und
                        # als Haarlinie: 1/zoom Punkte entsprechen nach dem Rendern exakt
                        # einem Bildschirm-Pixel, unabhängig von der Zoomstufe.
                        frame = fitz.Rect(rect_box.x0 - 2, rect_box.y0 - 2, rect_box.x1 + 2, rect_box.y1 + 2)
                        page.draw_rect(frame, color=(1, 0, 0), width=1.0 / zoom)

                except Exception as e:
                    _log.warning(f"Marker-Fehler ignoriert: {e}")

            # --- Suchtreffer-Marker (hellblau, blauer Rahmen) ---
            if highlight_terms:
                try:
                    for rect_box in PDFHandler.suchtreffer_boxen(page, highlight_terms, matcher_fuer):
                        marker = page.add_highlight_annot(rect_box)
                        marker.set_colors(stroke=PDFHandler.TREFFER_FUELLUNG)
                        marker.update()
                        frame = fitz.Rect(rect_box.x0 - 2, rect_box.y0 - 2, rect_box.x1 + 2, rect_box.y1 + 2)
                        page.draw_rect(frame, color=PDFHandler.TREFFER_RAHMEN, width=1.0 / zoom)
                        if treffer_boxen is not None:
                            treffer_boxen.append(rect_box)
                except Exception as e:
                    _log.warning(f"Treffer-Marker-Fehler ignoriert: {e}")
            # ----------------------------------------------------
            
            # Jetzt wird das Bild gerendert (inklusive der neuen Marker!)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            doc.close() 
            
            photo = ImageTk.PhotoImage(img)
            # Für das schnelle Zwischenbild beim Zoomen (preview_manager, FALLSTRICKE #117): Rohbild und genauer Zoom.
            # Nimmt das Bild-Objekt keine Attribute an, fehlt nur das Zwischenbild - die Vorschau selbst nie.
            try:
                photo.roh, photo.zoom = img, zoom
            except AttributeError:
                pass
            return photo, zoom_pct, total_pages, start_page
            
        except Exception as e:
            _log.warning(f"Fehler bei der PDF-Vorschau: {e}")
            return None

    @classmethod
    def normalize_date_input(cls, raw_input):
        """Wandelt Tastatureingaben (z.B. '150426' oder '15.4.26') und ISO-Daten in das Format YYYY-MM-DD um; gibt None bei ungültiger Eingabe zurück."""
        raw = raw_input.strip()
        if not raw:
            return None

        if raw.isdigit():
            if len(raw) == 6:
                day, month, year = int(raw[0:2]), int(raw[2:4]), int(raw[4:6])
                year += 2000 if year < 80 else 1900
            elif len(raw) == 8:
                day, month, year = int(raw[0:2]), int(raw[2:4]), int(raw[4:8])
            else:
                return None
        else:
            # --- Performanter Split über vorkompiliertes Regex-Muster ---
            parts = cls.PATTERN_DATE_SPLIT.split(raw)
            if len(parts) == 3:
                if len(parts[0]) == 4:
                    year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
                else:
                    day, month, year = int(parts[0]), int(parts[1]), int(parts[2])
                    if year < 100:
                        year += 2000 if year < 80 else 1900
            else:
                return None

        try:
            return datetime(year, month, day).strftime("%Y-%m-%d")
        except ValueError:
            return None

    @staticmethod
    def get_page_count(pdf_path):
        try:
            # --- FIX: Memory-Stream ---
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                return doc.page_count
        except Exception:
            return 1 

    @classmethod
    def _find_valid_date_in_text(cls, text_chunk, upper_bound_date):
        """Hilfsmethode für suggest_document_date: Durchsucht einen Textblock nach gültigen Daten."""
        priority_dates = []
        normal_dates = []
        text_for_partials = text_chunk
        
        def is_priority(match_obj):
            """Prüft, ob eines der PRIORITY_KEYWORDS (z.B. 'Rechnungsdatum') in den 100 Zeichen vor dem Treffer steht."""
            start_pos = match_obj.start()
            prefix = text_chunk[max(0, start_pos - 100):start_pos].lower()
            clean_prefix = re.sub(r'\s+', '', prefix)
            return any(kw in clean_prefix for kw in cls.PRIORITY_KEYWORDS)

        # --- SCHRITT A: Vollständige Daten suchen ---
        for pattern in cls.PATTERNS_NUMERIC:
            for m in pattern.finditer(text_chunk):
                try:
                    day, month = int(m.group(1)), int(m.group(2))
                    year_str = m.group(3).strip()
                    year = int(year_str) + (2000 if int(year_str) < 80 else 1900) if len(year_str) == 2 else int(year_str)
                    parsed_date = datetime(year, month, day)
                    
                    if is_priority(m): priority_dates.append(parsed_date)
                    else: normal_dates.append(parsed_date)
                    
                    text_for_partials = text_for_partials.replace(m.group(0), '---')
                except ValueError: continue 

        for m in cls.PATTERN_TEXT_MONTH.finditer(text_chunk):
            try:
                day, month_str, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
                if month_str in cls.GERMAN_MONTHS:
                    parsed_date = datetime(year, cls.GERMAN_MONTHS[month_str], day)
                    if is_priority(m): priority_dates.append(parsed_date)
                    else: normal_dates.append(parsed_date)
                    text_for_partials = text_for_partials.replace(m.group(0), '---')
            except ValueError: continue
                
        # --- SCHRITT B: Unvollständige Daten suchen (im geschwärzten Text) ---
        for m in cls.PATTERN_PARTIAL_TEXT.finditer(text_for_partials):
            try:
                month_str, year = m.group(1).lower(), int(m.group(2))
                if month_str in cls.GERMAN_MONTHS:
                    parsed_date = datetime(year, cls.GERMAN_MONTHS[month_str], 1)
                    if is_priority(m): priority_dates.append(parsed_date)
                    else: normal_dates.append(parsed_date)
            except ValueError: continue
                
        for m in cls.PATTERN_PARTIAL_NUM.finditer(text_for_partials):
            try:
                month, year = int(m.group(1)), int(m.group(2))
                if 1 <= month <= 12 and year > 1900:
                    parsed_date = datetime(year, month, 1)
                    if is_priority(m): priority_dates.append(parsed_date)
                    else: normal_dates.append(parsed_date)
            except ValueError: continue

        # --- SCHRITT C: Filtern und Auswerten ---
        def filter_dates(date_list):
            """Verwirft unplausible Treffer: Datum in der Zukunft (nach dem Datei-Zeitstempel) oder älter als 15 Jahre."""
            valid = []
            for d in date_list:
                if d > upper_bound_date or (upper_bound_date - d).days > 15 * 365: continue
                valid.append(d)
            return valid

        valid_priority = filter_dates(priority_dates)
        valid_normal = filter_dates(normal_dates)

        if valid_priority:
            _log.debug("Signalwort gefunden! Priorisiere VIP-Datum.")
            return max(valid_priority)
        elif valid_normal:
            return min(valid_normal)
        return None

    @classmethod
    def suggest_document_date(cls, pdf_path):
        if not os.path.exists(pdf_path) or not HAS_PREVIEW:
            return None

        try:
            stat = os.stat(pdf_path)
            file_mtime = datetime.fromtimestamp(stat.st_mtime)
            file_ctime = datetime.fromtimestamp(stat.st_ctime)
            upper_bound_date = min(file_mtime, file_ctime)

            # --- FIX: Memory-Stream ---
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                if doc.page_count == 0:
                    return None
                
                first_page = doc[0]
                page_rect = first_page.rect
                
                rect_top = fitz.Rect(0, 0, page_rect.width, page_rect.height * 0.50)
                text_top = first_page.get_text("text", clip=rect_top, sort=True)
                
                _log.debug(f"OCR (obere Hälfte) {os.path.basename(pdf_path)}")
                best_date = cls._find_valid_date_in_text(text_top, upper_bound_date)

                if not best_date:
                    _log.debug("Kein Datum in oberer Hälfte. Scanne untere Hälfte...")
                    rect_bottom = fitz.Rect(0, page_rect.height * 0.50, page_rect.width, page_rect.height)
                    text_bottom = first_page.get_text("text", clip=rect_bottom, sort=True)
                    best_date = cls._find_valid_date_in_text(text_bottom, upper_bound_date)

                if best_date:
                    _log.debug(f"Finales Datum gewählt -> {best_date.strftime('%Y-%m-%d')}")
                    return best_date.strftime("%Y-%m-%d")
                else:
                    _log.debug("Auf der gesamten ersten Seite kein passendes Datum gefunden.")
                    return None

        except Exception as e:
            _log.warning(f"Fehler bei der Datumsextraktion: {e}")
            return None

    @staticmethod
    def _merge_kid_metadata(meta, custom_data_dict, pdf_path):
        """
        Gemeinsame Metadaten-Zusammenführung beider Schreibwege (Neuaufbau und inkrementell):
        None-Werte bereinigen, KID-Felder im subject zusammenführen (bestehende Werte bleiben
        erhalten, ein übergebenes Dokumentdatum überschreibt gezielt nur seinen Teil), beim
        ersten Speichern den Scan-Zeitpunkt einbrennen (siehe scan_date.py - muss VOR einem
        Temp-Datei-Neuaufbau gelesen werden, der die Datei-Erstellungszeit auf "jetzt" setzen
        würde), und die Standard-Felder aus custom_data_dict übernehmen.
        """
        for key in meta:
            if meta[key] is None:
                meta[key] = ""

        existing_date, existing_scan = PDFHandler.parse_kid_subject(meta.get("subject", ""))
        new_date = custom_data_dict.get("KID_DokumentenDatum", existing_date)
        new_scan = existing_scan
        if not new_scan:
            dt = scan_date.resolve_scan_timestamp(meta.get("creationDate", ""), pdf_path)
            if dt:
                new_scan = scan_date.to_storage(dt)
        # Ursprünglicher Dateiname (Nutzerwunsch 11.09.2026, nachdem die Vollautomatik einen
        # guten Namen durch einen falschen KI-Titel ersetzt hatte): wird beim ERSTEN
        # Umbenennen eingebrannt und danach nie mehr überschrieben - der allererste Name
        # geht so nie verloren, egal wie oft später umbenannt wird.
        original_name = PDFHandler.parse_kid_original_name(meta.get("subject", ""))
        if not original_name:
            original_name = (custom_data_dict.get("KID_Originalname") or "").strip()
        # Dokument-ID (12.09.2026, Dubletten-Gedächtnis): einmal vergeben, nie überschrieben.
        # Seit 25.10.2026 bekommt jedes Dokument sie beim ersten Speichern - ohne eigenen
        # Schreibvorgang, bloßes Anklicken ändert also weiterhin nichts (Peter: Dokumente in
        # Notizen über eine kurze ID statt über den ganzen Dateinamen nennen).
        kid_id = PDFHandler.parse_kid_id(meta.get("subject", ""))
        if not kid_id:
            kid_id = (custom_data_dict.get("KID_ID") or "").strip() or PDFHandler.neue_kid_id()
        # Einzige Ausnahme vom „nie überschreiben“: eine Explorer-Kopie trägt dieselbe ID wie ihr
        # Original - das Werkzeug „Dokument-IDs vergeben“ gibt ihr gezielt eine neue (ersetze_kid_id)
        if (custom_data_dict.get("KID_ID_ERSETZEN") or "").strip():
            kid_id = custom_data_dict["KID_ID_ERSETZEN"].strip()
        # Absender für das Ablage-Gedächtnis (KONZEPT_ABLAGE_GEDAECHTNIS.md, 27.10.2026): anders als
        # KID_NAME überschreibbar - ein neuer Ablage-Lauf oder „Absender nachlesen“ liest genauer.
        absender = PDFHandler.parse_kid_absender(meta.get("subject", ""))
        if "KID_Absender" in custom_data_dict:
            absender = PDFHandler.bereinige_absender(custom_data_dict["KID_Absender"]) or absender
        # Grund, warum die Vollautomatik das Dokument vorgelegt hat (28.10.2026): wird bei jeder
        # Ablage-Entscheidung neu gesetzt bzw. geleert ("KID_Grund": "" bei sicherer Ablage)
        grund = PDFHandler.parse_kid_grund(meta.get("subject", ""))
        if "KID_Grund" in custom_data_dict:
            grund = PDFHandler.bereinige_absender(custom_data_dict["KID_Grund"])
        # Mail-Import (04.11.2026): Message-ID bzw. Fingerabdruck und Richtung - einmal gesetzt, nie überschrieben
        mail_id = (PDFHandler.parse_kid_feld(meta.get("subject", ""), "MAILID")
                   or PDFHandler.bereinige_absender(custom_data_dict.get("KID_MailID") or ""))
        richtung = (PDFHandler.parse_kid_feld(meta.get("subject", ""), "RICHTUNG")
                    or PDFHandler.bereinige_absender(custom_data_dict.get("KID_Richtung") or ""))
        # Wann KID das Dokument erfasst hat (Peter 04.11.2026, Spalte „Erfasst“): einmal gesetzt, nie überschrieben -
        # sonst schöbe jedes spätere Speichern von Tags das Dokument wieder nach oben
        erfasst = (PDFHandler.parse_kid_feld(meta.get("subject", ""), "ERFASST")
                   or (custom_data_dict.get("KID_Erfasst") or "").strip())
        kid_subject = PDFHandler.build_kid_subject(new_date, new_scan, original_name, kid_id, absender, grund,
                                                   mail_id, richtung, erfasst)
        if kid_subject:
            meta["subject"] = kid_subject

        for key, value in custom_data_dict.items():
            if key in ["title", "author", "keywords", "creator", "producer"]:
                meta[key] = value if value is not None else ""

        return meta

    @staticmethod
    def _write_metadata_incremental(pdf_path, custom_data_dict, still=False):
        """
        Schreibweg für signierte PDFs: hängt die Änderung inkrementell an (doc.saveIncr()),
        statt die Datei neu aufzubauen - ein Neuaufbau würde die digitale Signatur
        unwiderruflich zerstören (KONZEPT_PDF_ARTEN.md 1.5). Viewer zeigen danach korrekt
        "signiert, aber nachträglich geändert"; die signierte Ursprungsversion bleibt prüfbar.
        Öffnet bewusst per Pfad statt Memory-Stream: saveIncr() muss in die Originaldatei
        schreiben (der kurze File-Lock während des Speicherns ist hier unvermeidbar).
        """
        try:
            doc = fitz.open(pdf_path)
            try:
                meta = PDFHandler._merge_kid_metadata(doc.metadata.copy(), custom_data_dict, pdf_path)
                doc.set_metadata(meta)
                doc.saveIncr()
            finally:
                doc.close()
            _log.debug("Signiertes PDF - Metadaten inkrementell angehängt (Signatur bleibt erhalten).")
            return True
        except Exception as e:
            _log.error(f"Inkrementelles Speichern von {os.path.basename(pdf_path)} fehlgeschlagen: {e}")
            if not still:
                mb.showerror("Speicher-Fehler",
                             f"Das signierte PDF konnte nicht (inkrementell) gespeichert werden:\n{e}")
            return False

    @staticmethod
    def write_custom_metadata(pdf_path, custom_data_dict, still=False):
        """
        Schreibt Metadaten robust über eine komplette Neuerstellung (Temp-Datei + doc.save + move),
        statt incremental=True zu nutzen — das ist bei "nackten" Scanner-PDFs ohne /Info-Dictionary
        nötig, siehe FALLSTRICKE #10. Liest zuerst immer das komplette bestehende Metadaten-Dict aus
        und ändert nur gezielt die übergebenen Keys, damit nichts verloren geht (FALLSTRICKE #4).
        Das Dokumentdatum wird nicht direkt gespeichert, sondern kodiert im 'subject'-Feld als
        'KID_DATE:<datum>' (siehe get_metadata zum Zurücklesen). Beim ersten Speichern wird
        zusätzlich der ermittelte Scan-Zeitpunkt als 'KID_SCAN:<zeit>' mit eingebrannt
        (siehe scan_date.py) - danach ist er sicher im Dokument verankert und übersteht
        auch Kopien/Backups, die die Datei-Erstellungszeit verfälschen würden.

        Geschützte PDFs (siehe get_write_protection / KONZEPT_PDF_ARTEN.md): verschlüsselte
        und schreibgeschützte werden mit klarer Meldung abgelehnt; signierte werden auf den
        inkrementellen Schreibweg umgeleitet, weil der Neuaufbau hier die Signatur
        unwiderruflich zerstören würde.

        :param still: True = keine Messagebox bei Fehlern, nur Rückgabewert False - für
                      Aufrufer aus Hintergrund-Threads (Vollautomatik, auto_pilot_service.py):
                      Tkinter ist nicht thread-sicher, eine Messagebox von dort wäre ein
                      Absturzrisiko.
        """
        if not os.path.exists(pdf_path) or not HAS_PREVIEW:
            return False

        protection = PDFHandler.get_write_protection(pdf_path)
        if protection in ("verschlüsselt", "schreibgeschützt"):
            if not still:
                mb.showerror("PDF ist geschützt",
                             f"Dieses PDF ist {protection} und wird nicht verändert:\n{os.path.basename(pdf_path)}")
            return False
        if protection == "signiert":
            return PDFHandler._write_metadata_incremental(pdf_path, custom_data_dict, still)

        try:
            _log.debug(f"Speichere Metadaten für {os.path.basename(pdf_path)}")
            temp_path = pdf_path + ".tmp"

            # --- FIX: Memory-Stream auch hier, um Schreibblockaden zu vermeiden ---
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                meta = PDFHandler._merge_kid_metadata(doc.metadata.copy(), custom_data_dict, pdf_path)
                doc.set_metadata(meta)
                doc.save(temp_path)
                seiten = doc.page_count

            PDFHandler.ersetze_datei(temp_path, pdf_path, seiten)
            return True

        except Exception as e:
            _log.error(f"Speichern von {os.path.basename(pdf_path)} fehlgeschlagen: {e}")
            # Die halbfertige Temp-Datei darf nie liegen bleiben (FALLSTRICKE #60: sie tauchte
            # als '...pdf.tmp' in der Dokumentenliste auf).
            PDFHandler._entferne_leise(pdf_path + ".tmp")
            if not still:
                mb.showerror("Speicher-Fehler",
                             f"Das PDF konnte nicht überschrieben werden:\n{os.path.basename(pdf_path)}\n\n{e}\n\n"
                             "Ist die Datei gerade in einem anderen Programm (PDF-Anzeige, Explorer-Vorschau) "
                             "geöffnet? Dann dort schließen und erneut speichern.")
            return False

    # Überschreiben des Originals: unter Windows sperren PDF-Anzeigeprogramme, Explorer-Vorschau,
    # Virenscanner und Indexdienst die Datei gern für Sekundenbruchteile bis dauerhaft
    # (WinError 32). Kurze Sperren überbrückt die Wiederholung (Lehre aus FALLSTRICKE #27).
    SCHREIB_VERSUCHE = 3
    SCHREIB_WARTEZEIT_S = 0.3

    @staticmethod
    def ersetze_datei(temp_path, pdf_path, seiten):
        """
        Die einzige Stelle, die ein vorhandenes PDF ersetzt. Prüft zuerst die neue Fassung: Ein defektes Ergebnis oder fehlende
        Seiten erreichen das Original nie. Das Ersetzen selbst geschieht in einem Schritt (sicher_speichern.ersetze_datei,
        FALLSTRICKE #115), hält ein anderes Programm das PDF offen, an Ort und Stelle (#118); bei einem Fehler ist das
        Original unberührt, der Aufrufer darf die Temp-Datei löschen.
        :param seiten: Seitenzahl, die die neue Fassung haben muss
        :raises ValueError: neue Fassung unbrauchbar
        :raises OSError: Ersetzen gescheitert, etwa weil ein anderes Programm die Datei offen hält
        """
        try:
            with fitz.open(temp_path) as neu:
                gefunden = neu.page_count
        except (RuntimeError, ValueError) as e:     # fitz.FileDataError ist ein RuntimeError
            raise ValueError(f"Die neue Fassung ist nicht lesbar: {e}") from e
        if gefunden != seiten:
            raise ValueError(f"Die neue Fassung hat {gefunden} statt {seiten} Seiten.")
        sicher_speichern.ersetze_datei(temp_path, pdf_path, PDFHandler.SCHREIB_VERSUCHE, PDFHandler.SCHREIB_WARTEZEIT_S)

    @staticmethod
    def _entferne_leise(pfad):
        try:
            if os.path.exists(pfad):
                os.remove(pfad)
        except OSError:
            pass
    
    # --- HIER MUSS UNSERE NEUE METHODE SITZEN (Exakt gleich eingerückt!) ---
    @staticmethod
    def contains_text(pdf_path, search_term, matcher=None):
        """
        Durchsucht den unsichtbaren OCR-Text eines PDFs nach einem Suchbegriff.
        :param matcher: Optionale Prüf-Funktion (String -> bool), z.B. für
                        Wildcard-Suche (siehe SearchManager.build_matcher).
                        Ohne matcher wird die klassische Enthält-Suche verwendet.
        """
        if not HAS_PREVIEW or not os.path.exists(pdf_path):
            return False

        if matcher is None:
            search_term = search_term.lower()
            matcher = lambda text: search_term in text  # noqa: E731 -- bewusst kompakter Default

        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()

            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                for page in doc:
                    text = page.get_text("text").lower()
                    if matcher(text):
                        return True  # Treffer! Sofort abbrechen

            return False

        except Exception as e:
            _log.warning(f"Fehler bei OCR-Suche in {os.path.basename(pdf_path)}: {e}")
            return False

    @staticmethod
    def get_page_fingerprint(pdf_path, page_number=0):
        """
        Wahrnehmungs-Fingerabdruck (dHash, 64 Bit) einer Seite für die Dubletten-Erkennung
        (dubletten.py): Seite winzig in Graustufen rendern (9x8 Pixel), jedes Pixel mit
        seinem rechten Nachbarn vergleichen -> 64 Bits. Zwei Scans desselben Blatts
        unterscheiden sich darin nur in wenigen Bits, verschiedene Briefe in vielen.
        Unempfindlich gegen OCR-Fehler, Helligkeit und leichte Verschiebung.
        :return: int (0..2^64-1) oder None bei Fehler/ohne Vorschau-Bibliothek
        """
        if not HAS_PREVIEW:
            return None
        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                if page_number >= doc.page_count:
                    return None
                page = doc.load_page(page_number)
                pix = page.get_pixmap(matrix=fitz.Matrix(0.1, 0.1), colorspace=fitz.csGRAY)
                img = Image.frombytes("L", [pix.width, pix.height], pix.samples).resize((9, 8))
            pixel = list(img.getdata())
            wert = 0
            for zeile in range(8):
                for spalte in range(8):
                    links = pixel[zeile * 9 + spalte]
                    rechts = pixel[zeile * 9 + spalte + 1]
                    wert = (wert << 1) | (1 if links > rechts else 0)
            return wert
        except Exception as e:
            _log.warning(f"Fingerabdruck-Fehler bei {os.path.basename(pdf_path)}: {e}")
            return None

    @staticmethod
    def get_first_page_text(pdf_path):
        """Textebene NUR der ersten Seite (Memory-Stream, Datei bleibt frei) - für den Titel-Wortschatz der Vollautomatik; '' bei Fehler."""
        if not HAS_PREVIEW or not os.path.exists(pdf_path):
            return ""
        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                return doc[0].get_text() if len(doc) else ""
        except Exception:
            return ""

    @staticmethod
    def get_fulltext(pdf_path):
        """
        Extrahiert den kompletten Text aller Seiten (vorhandene Textebene, KEIN neues OCR) -
        Grundlage für den Volltext-Cache im Suchindex ("Standard"-Stufe, siehe
        index_manager.search_fulltext). Liefert bei Fehlern/fehlender Bibliothek einen
        leeren String statt zu crashen (das Dokument ist dann über die Volltextsuche
        schlicht nicht auffindbar, alles andere funktioniert weiter).
        """
        if not HAS_PREVIEW or not os.path.exists(pdf_path):
            return ""
        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                return "\n".join(page.get_text("text") for page in doc)
        except Exception as e:
            _log.warning(f"Fehler bei Volltext-Extraktion aus {os.path.basename(pdf_path)}: {e}")
            return ""

    @staticmethod
    def render_page_png(pdf_path, page_number=0, dpi=150):
        """
        Rendert EINE Seite als PNG-Bytes - Grundlage für KI-Bildanalysen (z.B.
        auto_pilot.analysiere_dokument; tools/ai_title_suggest.py hat historisch
        eine eigene Variante). Öffnet per Memory-Stream, rührt die Originaldatei
        also nicht an. Liefert None bei Fehlern/fehlender Seite/fehlender Bibliothek.
        """
        if not HAS_PREVIEW or not os.path.exists(pdf_path):
            return None
        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                if page_number >= doc.page_count:
                    return None
                return doc[page_number].get_pixmap(dpi=dpi).tobytes("png")
        except Exception as e:
            _log.warning(f"Fehler beim Seiten-Rendering von {os.path.basename(pdf_path)}: {e}")
            return None

    @staticmethod
    def get_fulltext_ocr(pdf_path, tessdata_path, language="deu", dpi=200):
        """
        Erzwingt echtes Bild-OCR aller Seiten (page.get_textpage_ocr(..., full=True) -
        liest das Seitenbild neu statt die vorhandene Textebene zu übernehmen) - für die
        "Fortgeschritten"-Stufe des Volltext-Cache. Nötig, weil auch eine bereits
        vorhandene Textebene selbst kaputtes OCR sein kann (siehe FALLSTRICKE #21: der
        ScanSnap las dort teils über Kopf) - `full=False` würde eine solche Ebene fälschlich
        als "schon lesbar" akzeptieren und gar nicht neu lesen. Braucht die Tesseract-
        Sprachdaten (siehe app_paths.tessdata_dir()); ~0,4s pro Seite, siehe
        KONZEPT_FILE_INDEX.md - Aufrufer ist ein expliziter Batch-Lauf, keine Live-Suche.
        Liefert bei Fehlern/fehlender Bibliothek einen leeren String statt zu crashen.
        """
        if not HAS_PREVIEW or not os.path.exists(pdf_path):
            return ""
        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                parts = []
                for page in doc:
                    tp = page.get_textpage_ocr(flags=3, language=language, dpi=dpi, full=True, tessdata=tessdata_path)
                    parts.append(page.get_text("text", textpage=tp))
                return "\n".join(parts)
        except Exception as e:
            _log.warning(f"Fehler bei Fortgeschritten-OCR aus {os.path.basename(pdf_path)}: {e}")
            return ""

    # Ab dieser Bild-Abdeckung gilt eine Seite als vollflächiger Scan (siehe
    # KONZEPT_PDF_ARTEN.md 1.1/1.3 - Misch-Seiten mit Teilbildern bleiben darunter).
    SCAN_BILD_ABDECKUNG_MIN = 0.9

    @staticmethod
    def classify_pages(pdf_path):
        """
        Stuft jede Seite für das Neu-Erfassen-Tool ein (siehe KONZEPT_PDF_ARTEN.md 1.1-1.3):

        - "scan":    vollseitiges Bild, höchstens UNSICHTBARE OCR-Textebene (Render-Modus 3)
                     - NUR solche Seiten darf das Neu-Erfassen-Tool bearbeiten.
        - "digital": sichtbarer Text ohne vollflächiges Seitenbild - wird NIE angefasst
                     (es gibt kein "besseres OCR" für echten Text).
        - "misch":   Bild + sichtbarer Text, Teilbilder oder sonstige Zwitter - im
                     Zweifel überspringen.
        - "leer":    weder Bild noch Text.

        Die Entscheidung fällt bewusst PRO SEITE, nicht pro Dokument - hybride PDFs
        (digitaler Brief + eingescannter Anhang) sind real. Liefert eine Liste von Dicts
        (seite, typ, bild_abdeckung, sichtbarer_text, unsichtbarer_text, text - der
        rohe `get_text()`-Inhalt der Seite, z.B. für eine Textqualitäts-Einschätzung
        in tools/document_recapture.py); bei Fehlern oder fehlender Bibliothek eine
        leere Liste (Aufrufer behandelt das als "nicht analysierbar", nie als "alles Scan").
        """
        if not HAS_PREVIEW or not os.path.exists(pdf_path):
            return []
        try:
            with open(pdf_path, "rb") as f:
                pdf_bytes = f.read()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                return [PDFHandler._classify_single_page(page) for page in doc]
        except Exception as e:
            _log.warning(f"Fehler bei Seiten-Klassifizierung von {os.path.basename(pdf_path)}: {e}")
            return []

    @staticmethod
    def _classify_single_page(page):
        """Klassifiziert EINE bereits geöffnete PyMuPDF-Seite (Herzstück von classify_pages)."""
        page_area = page.rect.get_area()
        # Größte Abdeckung eines EINZELNEN Bildes - ein echter Scan ist genau ein
        # vollseitiges Bild, mehrere Teilbilder sollen sich nicht zu "Scan" addieren.
        max_abdeckung = 0.0
        if page_area > 0:
            for img in page.get_images(full=True):
                for rect in page.get_image_rects(img[0]):
                    schnitt = fitz.Rect(rect)
                    schnitt.intersect(page.rect)
                    if not schnitt.is_empty:
                        max_abdeckung = max(max_abdeckung, schnitt.get_area() / page_area)

        # get_texttrace liefert (anders als get_text) den Text-Render-Modus mit:
        # type == 3 ist unsichtbarer Text - genau so legen Scanner ihre OCR-Ebene ab.
        sichtbar = False
        unsichtbar = False
        for span in page.get_texttrace():
            if not any(not chr(c[0]).isspace() for c in span["chars"]):
                continue  # reine Leerzeichen-Spans zählen nicht als Text
            if span["type"] == 3:
                unsichtbar = True
            else:
                sichtbar = True

        if sichtbar:
            typ = "misch" if max_abdeckung >= PDFHandler.SCAN_BILD_ABDECKUNG_MIN else "digital"
        elif max_abdeckung >= PDFHandler.SCAN_BILD_ABDECKUNG_MIN:
            typ = "scan"
        elif max_abdeckung > 0 or unsichtbar:
            # Teilbild ohne sichtbaren Text bzw. unsichtbarer Text ohne Seitenbild -
            # beides kein sauberer Scan, im Zweifel überspringen.
            typ = "misch"
        else:
            typ = "leer"

        return {
            "seite": page.number + 1,
            "typ": typ,
            "bild_abdeckung": round(max_abdeckung, 3),
            "sichtbarer_text": sichtbar,
            "unsichtbarer_text": unsichtbar,
            "text": page.get_text(),
        }

    # Ergebnis darf höchstens so viel größer als das Original werden - schützt vor
    # einer fehlgelaufenen OCR-Explosion (siehe KONZEPT_PDF_ARTEN.md 2.2).
    RECAPTURE_MAX_SIZE_FACTOR = 1.5

    @staticmethod
    def _textebene_wort_einfuegen(page, x0, y0, x1, y1, word, fontname="helv"):
        """
        Setzt EIN unsichtbares OCR-Wort (render_mode=3) so in die Seite, dass es das
        Wort-Rechteck aus der Erkennung in Höhe UND Breite ausfüllt: Schriftgröße aus der
        Höhe, dazu eine horizontale Streckung/Stauchung (morph-Matrix um den Einfügepunkt),
        damit die Helvetica-Breite der Bildbreite entspricht. Ohne die Streckung war der
        unsichtbare Text meist schmaler als das gedruckte Wort, und der Datums-Marker
        (search_for) endete mitten im Wort - "18.11.20|19" (Nutzerfund 11.09.2026).
        Liefert die x-Streckung (1.0 = keine).
        """
        hoehe = max(y1 - y0, 1.0)
        fontsize = max(1.0, hoehe * 0.8)
        punkt = fitz.Point(x0, y1 - hoehe * 0.15)
        breite_text = fitz.get_text_length(word, fontname=fontname, fontsize=fontsize)
        streckung = (x1 - x0) / breite_text if breite_text > 0 and x1 > x0 else 1.0
        page.insert_text(punkt, word, fontsize=fontsize, fontname=fontname, render_mode=3,
                         morph=(punkt, fitz.Matrix(streckung, 1.0)))
        return streckung

    @staticmethod
    def get_textqualitaet(filepath, max_seiten=1):
        """
        Textqualität (0-100, siehe text_quality.textqualitaet_prozent) der ersten Seite(n)
        für die optionale Spalte "Textqualität" der Dokumentenliste (Nutzerwunsch
        11.09.2026): eine kaputte Scanner-OCR-Ebene fällt so schon in der Liste auf, ohne
        das Neu-Erfassen-Tool zu öffnen. None bei fehlendem/zu kurzem Text oder Fehlern.
        """
        if not HAS_PREVIEW or not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "rb") as f:
                pdf_bytes = f.read()
            with fitz.open(stream=pdf_bytes, filetype="pdf") as doc:
                text = "\n".join(doc[i].get_text("text") for i in range(min(max_seiten, doc.page_count)))
            return text_quality.textqualitaet_prozent(text)
        except Exception as e:
            _log.warning(f"Fehler bei der Textqualität von {os.path.basename(filepath)}: {e}")
            return None

    @staticmethod
    def _waehle_bessere_textebene(alte_worte, neue_worte):
        """
        Vergleicht die Textqualität (siehe text_quality.textqualitaet_prozent) der
        alten gegen die frisch per OCR erkannte Wortliste einer Scan-Seite und
        entscheidet, welche im PDF landet - reine Funktion (nur die von
        page.get_text("words", ...) gelieferten Tupel nötig, kein PyMuPDF-Objekt),
        einzeln testbar. Die alte Ebene gewinnt nur, wenn sie nachweisbar (nicht
        None) UND mindestens so gut wie die neue ist - im Zweifel (z.B. leere alte
        Ebene) gewinnt die neue, frisch erkannte Version.
        :return: (gewählte Wortliste, alte_ebene_behalten: bool)
        """
        alte_qualitaet = text_quality.textqualitaet_prozent(" ".join(w[4] for w in alte_worte))
        neue_qualitaet = text_quality.textqualitaet_prozent(" ".join(w[4] for w in neue_worte))
        alte_ist_besser = (alte_qualitaet is not None
                            and (neue_qualitaet is None or neue_qualitaet < alte_qualitaet))
        return (alte_worte, True) if alte_ist_besser else (neue_worte, False)

    @staticmethod
    def recapture_document(pdf_path, tessdata_path, language="deu", dpi=200,
                            on_progress=None, should_stop=None):
        """
        Schreibt die OCR-Textebene echter Scan-Seiten (siehe classify_pages) neu:
        entfernt die alte, ggf. kaputte unsichtbare Textebene per Redaktion und fügt
        frisch erkannten Text an den richtigen Positionen unsichtbar wieder ein.
        Digital-/Misch-/Leer-Seiten werden NIE angefasst.

        Bild-Objekte bleiben dank `images=PDF_REDACT_IMAGE_NONE` byte- UND
        pixelidentisch (keine Neukompression, geprüft per Pixmap-Vergleich) - die
        Redaktion entfernt ausschließlich Textobjekte, zeichnet keine Füllfläche
        (die alte Textebene war ohnehin unsichtbar, es gibt nichts zu überdecken).

        Verweigert geschützte PDFs (siehe get_write_protection) sowie ein Ergebnis,
        das um mehr als RECAPTURE_MAX_SIZE_FACTOR gewachsen wäre - in beiden Fällen
        bleibt die Datei unverändert auf der Platte. Kein eigenes Backup/Papierkorb-
        Handling hier (bewusst Aufgabe des Aufrufers, siehe tools/document_recapture.py) -
        pdf_handler bleibt reine PyMuPDF-Schnittstelle ohne app_paths-Abhängigkeit.

        Pro Seite wird die neue OCR-Qualität (siehe text_quality.textqualitaet_prozent)
        gegen die der alten Textebene verglichen (KONZEPT_PDF_ARTEN.md / Nutzer-Fund:
        ein erneutes OCR kann bei stark degradierten Scans auch mal SCHLECHTER
        ausfallen als das, was der Scanner ursprünglich gelesen hat) - schneidet die
        alte Ebene nachweislich besser ab, wird sie nach der Redaktion unverändert
        wieder eingesetzt statt der neuen (schlechteren) Version. Kein echtes Wort-
        für-Wort-Mergen zweier OCR-Ergebnisse (das wäre fehleranfällig), sondern die
        konservativere "behalte die insgesamt bessere Version" pro Seite.

        `on_progress(fertig, gesamt)` wird nach jeder Scan-Seite gerufen (für große
        Dokumente, siehe KONZEPT_PDF_ARTEN.md 1.9); `should_stop()` wird davor geprüft
        und bricht bei True vor dem Speichern ab - die Datei bleibt dann unverändert,
        da bis dahin nur die IM RAM geöffnete Kopie verändert wurde.

        :return: (erfolg: bool, meldung: str, bearbeitete_seiten: int)
        """
        if not HAS_PREVIEW or not os.path.exists(pdf_path):
            return False, "Datei nicht gefunden.", 0

        protection = PDFHandler.get_write_protection(pdf_path)
        if protection:
            return False, f"PDF ist {protection} — Neu-Erfassen wird verweigert.", 0

        groesse_vorher = os.path.getsize(pdf_path)
        try:
            with fitz.open(pdf_path) as doc:
                scan_seiten_gesamt = sum(
                    1 for page in doc if PDFHandler._classify_single_page(page)["typ"] == "scan")
                bearbeitete_seiten = 0
                alte_ebene_behalten = 0
                for page in doc:
                    if PDFHandler._classify_single_page(page)["typ"] != "scan":
                        continue
                    if should_stop and should_stop():
                        return False, "Abgebrochen — Datei unverändert.", bearbeitete_seiten

                    alte_worte = page.get_text("words")

                    page.add_redact_annot(page.rect)
                    page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                                           graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                                           text=fitz.PDF_REDACT_TEXT_REMOVE)
                    tp = page.get_textpage_ocr(flags=3, language=language, dpi=dpi,
                                                full=True, tessdata=tessdata_path)
                    neue_worte = page.get_text("words", textpage=tp)

                    einzusetzende_worte, alte_behalten = PDFHandler._waehle_bessere_textebene(
                        alte_worte, neue_worte)
                    if alte_behalten:
                        alte_ebene_behalten += 1

                    for x0, y0, x1, y1, word, *_rest in einzusetzende_worte:
                        PDFHandler._textebene_wort_einfuegen(page, x0, y0, x1, y1, word)
                    bearbeitete_seiten += 1
                    if on_progress:
                        on_progress(bearbeitete_seiten, scan_seiten_gesamt)

                if bearbeitete_seiten == 0:
                    return False, "Keine Scan-Seiten gefunden — nichts zu tun.", 0

                neue_bytes = doc.write(garbage=4, deflate=True)
                seiten = doc.page_count
        except Exception as e:
            _log.warning(f"Fehler beim Neu-Erfassen von {os.path.basename(pdf_path)}: {e}")
            return False, f"Fehler beim Neu-Erfassen: {e}", 0

        if groesse_vorher > 0 and len(neue_bytes) > groesse_vorher * PDFHandler.RECAPTURE_MAX_SIZE_FACTOR:
            faktor = len(neue_bytes) / groesse_vorher
            return False, (f"Ergebnis wäre {faktor:.1f}x so groß wie das Original — "
                            "abgebrochen, Datei unverändert."), 0

        # Atomar über Temp-Datei ersetzen - ein Absturz mitten im Schreiben darf die Originaldatei
        # nie halbfertig zurücklassen.
        temp_path = pdf_path + ".recapture_tmp"
        try:
            with open(temp_path, "wb") as f:
                f.write(neue_bytes)
            PDFHandler.ersetze_datei(temp_path, pdf_path, seiten)
        except (OSError, ValueError) as e:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            return False, f"Schreiben fehlgeschlagen: {e}", 0

        meldung = f"{bearbeitete_seiten} Scan-Seite(n) neu erfasst."
        if alte_ebene_behalten:
            meldung += (f" Bei {alte_ebene_behalten} davon war die alte Textebene "
                        "besser und wurde beibehalten.")
        return True, meldung, bearbeitete_seiten