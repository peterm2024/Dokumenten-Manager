"""
Prüfdokumente für den Benchmark (Etappe 13, KONZEPT_BENCHMARK.md Schritt 2): 40 erfundene Briefe mit bekannter
Wahrheit - welcher Ablageordner, welches Belegdatum, welcher Absender.

Nur Musterdaten (Max Mustermann, Musterstadt, „Musterversicherung AG“ …), damit Ergebnisse geteilt werden dürfen.
Die Briefe sind fest: Jeder Rechner erzeugt dieselben Dokumente, die Zahlen bleiben vergleichbar.

Aufteilung (Peter 19.11.2026, F2): 35 Briefe für 11 vorhandene Ablageordner, davon 10 schwer (zwei Firmen im
Brief, Marke statt Firmenname, viele Datumsangaben, Brief über einen Makler …), und 5 Briefe von Absendern ohne
passenden Ordner - richtig ist dort ein neuer Ordner oder die Rückfrage, falsch die stille Ablage in einen
vorhandenen. Unten auf jeder Seite steht „Prüfdokument 017“: Nach dem Ausdrucken und Einscannen ordnet
`nummer_aus_text` die Scans darüber ihrer Wahrheit zu.

Gestaltung nach echter, geschwärzter Post (Peter 19.11.2026): Logo, Rücksendezeile mit Frankiervermerk und
Matrixcode, Infoblock rechts (Ansprechpartner, Zeichen, Datum), Betreffblock, Tabellen mit Fußnoten, Unterschrift,
dichtes Kleingedrucktes in drei Spalten, Falz- und Lochmarke, Druckcode am Rand, Eingangsstempel mit späterem
Datum, Hinweisseite 2. Das Datum steht je Absender anders (im Infoblock mit und ohne „Datum:“, als „Ort, Datum“,
ausgeschrieben).

Ohne Oberfläche; PDFs schreibt nur `pdf_handler` (die Zeichnungen sind einfache Dicts, siehe
`PDFHandler._zeichne`).
"""
import hashlib
import html
import math
import os
import random
import re

from pdf_handler import PDFHandler

# Der Satz ist eingefroren (Peter 20.11.2026): Er liegt gedruckt und eingescannt als fester Download bei jedem Release
# (Pruefdokumente_Benchmark.zip / …_gescannt.zip, KID-Messungen/benchmark/download_zips.py). Ändert sich ein Brief,
# passen Benchmark, Download und Scans nicht mehr zusammen und alte Messungen sind nicht mehr vergleichbar -
# tests/test_pruefdokumente.py prüft darum diesen Fingerabdruck. Ein neuer Satz bräuchte einen neuen Namen.
FINGERABDRUCK = "5e87d7d0fef880eb287cef143a4a2a7eb33ffb4de85ecd68a1f0b8f5200ab6fe"   # Satz vom 19.11.2026

EMPFAENGER = ("Herrn", "Max Mustermann", "Musterstraße 1", "12345 Musterstadt")
FUSS = "Prüfdokument {nr:03d} · KID-Benchmark · nur Musterdaten"
DATEINAME = "Scan_{nr:04d}.pdf"
SAMMEL_PDF = "Pruefdokumente_zum_Drucken.pdf"

# Ordnervorlage der Benchmark-Sammlung: die Gruppen aus folder_default.json und je Absender ein Ordner
GRUPPEN = ("[0-9]", "A - B - C - D - E", "F - G - H - I - J", "K - L - M - N - O", "P - Q - R - S - T",
           "U - V - W - X - Y - Z")

MONATE = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember")
STEMPEL_MONATE = ("JAN", "FEB", "MÄR", "APR", "MAI", "JUN", "JUL", "AUG", "SEP", "OKT", "NOV", "DEZ")
TINTE = (0.15, 0.22, 0.62)
GRAU = (0.45, 0.45, 0.45)
WEISS = (1, 1, 1)
RAND = (60, 45, -50, -112)   # Textbereich: unten Platz für Kleingedrucktes, Seitenzahl und Prüfnummer


def _absender(name, adresse, kontakt, zeile, recht, ordner, kennwort, logo, datum="info", rahmen=False,
              post=True, signierer=(), nachsatz="", block=False, ort=None):
    """name/adresse: Kopf; kontakt: Zeilen des Infoblocks; zeile: Rücksendezeile; recht: Kleingedrucktes in drei
    Spalten; ordner: Ablageordner (None = keiner vorhanden); kennwort: muss im gelesenen Absender vorkommen;
    datum: info („Datum: …“), nackt (nur das Datum), ort („Ort, Datum“), lang („Ort, 12. Januar 2026“);
    signierer: (Name, Funktion) - leer = maschinell erstellt; block: Angaben als Block unter dem Betreff."""
    return dict(name=name, adresse=adresse, kontakt=kontakt, zeile=zeile, recht=recht, ordner=ordner,
                kennwort=kennwort, logo=logo, datum=datum, rahmen=rahmen, post=post, signierer=signierer,
                nachsatz=nachsatz, block=block, ort=ort)


ABSENDER = {
    "vers": _absender(
        "Musterversicherung AG", "Versicherungsallee 10 · 45678 Musterhausen",
        ("Kundenservice", "Telefon 04567 8900-0", "service@musterversicherung.example",
         "www.musterversicherung.example"),
        "Musterversicherung AG · 45678 Musterhausen",
        ("Musterversicherung AG\nVersicherungsallee 10\n45678 Musterhausen\nTelefon 04567 8900-0",
         "Vorstand: Dr. Anna Probe (Vorsitzende),\nJens Muster, Karin Probst\nVorsitzender des Aufsichtsrats: "
         "Paul Probst\nSitz Musterhausen, Amtsgericht Musterhausen HRB 1234",
         "IBAN DE00 4567 0000 1234 5678 90\nBIC MUSTDEXXXXX\nVersicherungsteuer-Nr. 000/V00000000\n"
         "Ein Unternehmen der Probata Gruppe"),
        "K - L - M - N - O/Musterversicherung", "Musterversicherung",
        dict(art="kasten", farbe=(0.12, 0.30, 0.55), teile=("MUSTER", "VERSICHERUNG"),
             slogan="Gut versichert seit 1898."),
        datum="nackt", rahmen=True, block=True,
        signierer=(("Dr. Anna Probe", "Vorstand"), ("Jens Muster", "Leiter Kundenservice")),
        nachsatz="Haben Sie Fragen zu Ihrem Vertrag? Unser Kundenservice ist Montag bis Freitag von 8 bis 20 Uhr "
                 "für Sie da. Ihre Daten ändern Sie jederzeit im Kundenportal."),
    "bank": _absender(
        "Beispielbank eG", "Bankplatz 2 · 23456 Beispielhausen",
        ("Ihre Beraterin", "Lena Probe", "Telefon 02345 6789-112", "lena.probe@beispielbank.example"),
        "Beispielbank eG · Bankplatz 2 · 23456 Beispielhausen",
        ("Beispielbank eG\nBankplatz 2, 23456 Beispielhausen\nTelefon 02345 6789-0\nwww.beispielbank.example",
         "Vorstand: Tom Muster, Ute Probst\nVorsitzende des Aufsichtsrats: Rita Exempel\n"
         "Genossenschaftsregister Beispielhausen GnR 99",
         "BIC BSPLDEXX\nGläubiger-ID DE00ZZZ00000012345\nUSt-IdNr. DE000000099\n"
         "Angeschlossen an die Sicherungseinrichtung"),
        "A - B - C - D - E/Beispielbank", "Beispielbank",
        dict(art="rund", farbe=(0.0, 0.45, 0.30), zeichen="B", slogan="Ihre Bank vor Ort"),
        datum="nackt", signierer=(("Lena Probe", "Kundenberaterin"), ("Tom Muster", "Vorstand")),
        nachsatz="Unsere Allgemeinen Geschäftsbedingungen sowie das Preis- und Leistungsverzeichnis erhalten Sie "
                 "in jeder Geschäftsstelle und unter www.beispielbank.example."),
    "swerke": _absender(
        "Stadtwerke Musterstadt GmbH", "Werkstraße 5 · 12345 Musterstadt",
        ("Kundenzentrum am Marktplatz", "Telefon 01234 5678-100", "Mo-Fr 8-18 Uhr",
         "kundenservice@stadtwerke-musterstadt.example"),
        "Stadtwerke Musterstadt GmbH · Werkstraße 5 · 12345 Musterstadt",
        ("Stadtwerke Musterstadt GmbH\nWerkstraße 5, 12345 Musterstadt\nwww.stadtwerke-musterstadt.example",
         "Geschäftsführer: Dipl.-Ing. Frank Probst\nAufsichtsratsvorsitz: Oberbürgermeisterin Maria Muster\n"
         "Sitz Musterstadt, Amtsgericht Musterstadt HRB 2222",
         "IBAN DE00 1234 0000 0000 1111 22\nGläubiger-ID DE00ZZZ00000022222\nUSt-IdNr. DE000002222"),
        "P - Q - R - S - T/Stadtwerke", "Stadtwerke",
        dict(art="balken", farbe=(0.0, 0.42, 0.70), slogan="Energie und Wasser für Musterstadt"),
        rahmen=True,
        nachsatz="Fragen zu Ihrer Rechnung beantworten wir gern im Kundenzentrum am Marktplatz."),
    "fa": _absender(
        "Finanzamt Musterstadt", "Steuerplatz 1 · 12345 Musterstadt",
        ("Steuerplatz 1", "12345 Musterstadt", "Telefon 01234 5678-0", "Zimmer 214, Sachgebiet 3"),
        "Finanzamt Musterstadt · Postfach 10 00 · 12345 Musterstadt",
        ("Finanzamt Musterstadt\nSteuerplatz 1, 12345 Musterstadt\nTelefon 01234 5678-0",
         "Öffnungszeiten Servicezentrum:\nMo-Do 8-15 Uhr, Fr 8-12 Uhr\nTermine nach Vereinbarung",
         "Bankverbindung: Landeskasse Musterstadt\nIBAN DE00 1234 0000 0000 0001 00\nBIC MUSTDEXX100"),
        "F - G - H - I - J/Finanzamt", "Finanzamt",
        dict(art="amt", farbe=GRAU, zusatz="Steuerverwaltung des Landes"),
        rahmen=True, nachsatz="Bitte geben Sie bei allen Rückfragen Ihre Steuernummer an."),
    "bkk": _absender(
        "Muster BKK", "Gesundheitsweg 3 · 45678 Musterhausen",
        ("Die Betriebskrankenkasse für Musterhausen", "Ihr Kundenberater: Ole Probst", "Telefon 04567 1234-0",
         "service@muster-bkk.example"),
        "Muster BKK · Gesundheitsweg 3 · 45678 Musterhausen",
        ("Muster BKK\nKörperschaft des öffentlichen Rechts\nGesundheitsweg 3, 45678 Musterhausen",
         "Vorstand: Sabine Exempel\nVorsitzender des Verwaltungsrats: Uwe Probe",
         "IBAN DE00 4567 0000 0000 1234 00\nInstitutionskennzeichen 100000000"),
        "K - L - M - N - O/Krankenkasse", "BKK",
        dict(art="schrift", farbe=(0.70, 0.10, 0.25), slogan="Gesund in Musterhausen"),
        datum="ort", signierer=(("Ole Probst", "Kundenberater"),),
        nachsatz="Ihre Muster BKK erreichen Sie auch rund um die Uhr in unserer Service-App."),
    "arzt": _absender(
        "Hausarztpraxis am Markt", "Marktplatz 4 · 12345 Musterstadt",
        ("Dr. med. Eva Beispiel", "Fachärztin für Allgemeinmedizin", "Telefon 01234 9876",
         "Sprechzeiten Mo-Fr 8-12 Uhr"),
        "Dr. med. Eva Beispiel · Marktplatz 4 · 12345 Musterstadt",
        ("Hausarztpraxis am Markt\nDr. med. Eva Beispiel\nMarktplatz 4, 12345 Musterstadt",
         "Telefon 01234 9876\nTelefax 01234 9877", "IBAN DE00 2345 0000 0000 9876 54\nBIC BSPLDEXX"),
        "A - B - C - D - E/Dr. Beispiel", "Beispiel",
        dict(art="schrift", farbe=(0.20, 0.45, 0.35), slogan="Allgemeinmedizin · Reisemedizin"),
        datum="lang", post=False, signierer=(("Dr. med. Eva Beispiel", "Fachärztin für Allgemeinmedizin"),)),
    "tel": _absender(
        "Telemuster GmbH", "Funkturmstraße 8 · 23456 Beispielhausen",
        ("Kundenservice", "Hotline 0800 123 456 (kostenfrei)", "www.telemuster.example"),
        "Telemuster GmbH · Postfach 5 00 · 23456 Beispielhausen",
        ("Telemuster GmbH\nFunkturmstraße 8, 23456 Beispielhausen\nAmtsgericht Beispielhausen HRB 5678",
         "Geschäftsführung: Nina Probe, Lars Muster\nVorsitzender des Aufsichtsrats: Georg Probst",
         "IBAN DE00 2345 0000 0000 5678 00\nGläubiger-ID DE00ZZZ00000056789\nUSt-IdNr. DE000005678"),
        "P - Q - R - S - T/Telemuster", "Telemuster",
        dict(art="kachel", farbe=(0.42, 0.20, 0.60), zeichen="TM"),
        rahmen=True,
        nachsatz="Ihre Rechnungen finden Sie auch im Kundencenter unter www.telemuster.example. Bitte geben Sie "
                 "bei Fragen immer Ihre Kundennummer an."),
    "auto": _absender(
        "Autohaus Musterdorf GmbH", "Gewerbering 12 · 34567 Musterdorf",
        ("Ihr Serviceberater", "Klaus Probe", "Werkstatt 03456 7788", "Verkauf 03456 7789"),
        "Autohaus Musterdorf GmbH · Gewerbering 12 · 34567 Musterdorf",
        ("Autohaus Musterdorf GmbH\nGewerbering 12, 34567 Musterdorf\nAmtsgericht Musterdorf HRB 345",
         "Geschäftsführer: Dirk Muster\nWerkstatt: Mo-Fr 7-18 Uhr, Sa 8-12 Uhr",
         "IBAN DE00 3456 0000 0000 7788 00\nUSt-IdNr. DE000000345"),
        "A - B - C - D - E/Autohaus Musterdorf", "Autohaus",
        dict(art="balken", farbe=(0.65, 0.10, 0.10), slogan="Verkauf · Service · Teile"),
        datum="nackt", signierer=(("Klaus Probe", "Serviceberater"),)),
    "haus": _absender(
        "Haustechnik Mustergültig GmbH", "Rohrweg 7 · 12345 Musterstadt",
        ("Heizung · Sanitär · Klima", "Meisterbetrieb seit 1985", "Telefon 01234 4455",
         "info@mustergueltig.example"),
        "Haustechnik Mustergültig GmbH · Rohrweg 7 · 12345 Musterstadt",
        ("Haustechnik Mustergültig GmbH\nRohrweg 7, 12345 Musterstadt",
         "Geschäftsführer: Bernd Probst,\nInstallateur- und Heizungsbauermeister\nAmtsgericht Musterstadt HRB 4455",
         "IBAN DE00 1234 0000 0000 4455 00\nUSt-IdNr. DE000004455"),
        "F - G - H - I - J/Haustechnik Mustergültig", "Mustergültig",
        dict(art="rund", farbe=(0.85, 0.45, 0.05), zeichen="H", slogan="Heizung · Sanitär · Klima"),
        datum="ort", post=False, signierer=(("Bernd Probst", "Meister"),)),
    "werk": _absender(
        "Musterwerk Maschinenbau GmbH", "Industriestraße 20 · 34567 Musterdorf",
        ("Personalabteilung", "Sabine Probe", "Telefon 03456 9000-212", "personal@musterwerk.example"),
        "Musterwerk Maschinenbau GmbH · Industriestraße 20 · 34567 Musterdorf",
        ("Musterwerk Maschinenbau GmbH\nIndustriestraße 20, 34567 Musterdorf\nTelefon 03456 9000-0",
         "Geschäftsführung: Dr. Herbert Muster\nAmtsgericht Musterdorf HRB 900",
         "IBAN DE00 3456 0000 0000 9000 00\nUSt-IdNr. DE000000900"),
        "K - L - M - N - O/Musterwerk", "Musterwerk",
        dict(art="schrift", farbe=(0.25, 0.33, 0.42), slogan="Präzision aus Musterdorf"),
        post=False, signierer=(("Sabine Probe", "Personalabteilung"),)),
    "hv": _absender(
        "Hausverwaltung Exemplar GmbH", "Verwalterweg 9 · 23456 Beispielhausen",
        ("Ihre Objektbetreuerin", "Petra Probe", "Telefon 02345 3344", "Sprechzeiten Di und Do 9-12 Uhr"),
        "Hausverwaltung Exemplar GmbH · Verwalterweg 9 · 23456 Beispielhausen",
        ("Hausverwaltung Exemplar GmbH\nVerwalterweg 9, 23456 Beispielhausen",
         "Geschäftsführerin: Petra Probe\nAmtsgericht Beispielhausen HRB 3344\nErlaubnis nach § 34c GewO",
         "IBAN DE00 2345 0000 0000 3344 00\nUSt-IdNr. DE000003344"),
        "F - G - H - I - J/Hausverwaltung Exemplar", "Exemplar",
        dict(art="kasten", farbe=(0.15, 0.40, 0.25), teile=("EXEMPLAR",), slogan="Hausverwaltung GmbH"),
        datum="lang", signierer=(("i. A. Petra Probe", "Objektbetreuung"),)),
    # Absender ohne passenden Ordner
    "tier": _absender(
        "Tierarztpraxis am Musterbach", "Bachweg 2 · 34567 Musterdorf",
        ("Dr. med. vet. Jana Probst", "Telefon 03456 2211", "Notdienst 03456 2212"),
        "Tierarztpraxis am Musterbach · Bachweg 2 · 34567 Musterdorf",
        ("Tierarztpraxis am Musterbach\nDr. med. vet. Jana Probst\nBachweg 2, 34567 Musterdorf",
         "Sprechzeiten: Mo-Fr 9-12 und 15-18 Uhr", "IBAN DE00 3456 0000 0000 2211 00"),
        None, "Tierarzt",
        dict(art="rund", farbe=(0.45, 0.30, 0.15), zeichen="T", slogan="Kleintiere · Pferde"),
        datum="ort", post=False, signierer=(("Dr. med. vet. Jana Probst", "Tierärztin"),)),
    "tsv": _absender(
        "TSV Musterstadt 1890 e.V.", "Sportplatzweg 1 · 12345 Musterstadt",
        ("Geschäftsstelle", "Sportplatzweg 1", "Telefon 01234 1890", "Di 17-19 Uhr"),
        "TSV Musterstadt 1890 e.V. · Sportplatzweg 1 · 12345 Musterstadt",
        ("TSV Musterstadt 1890 e.V.\nSportplatzweg 1, 12345 Musterstadt\nVereinsregister Musterstadt VR 77",
         "1. Vorsitzender: Rolf Muster\nKassenwartin: Heike Probe",
         "IBAN DE00 1234 0000 0000 1890 00\nGläubiger-ID DE00ZZZ00000000001"),
        None, "TSV",
        dict(art="rund", farbe=(0.10, 0.25, 0.65), zeichen="TSV", slogan="Sport für alle seit 1890"),
        datum="ort", post=False, signierer=(("Rolf Muster", "1. Vorsitzender"), ("Heike Probe", "Kassenwartin"))),
    "bib": _absender(
        "Stadtbibliothek Musterstadt", "Bücherplatz 3 · 12345 Musterstadt",
        ("Ausleihe und Leserservice", "Telefon 01234 5678-300", "Di-Fr 10-18 Uhr, Sa 10-14 Uhr"),
        "Stadt Musterstadt · Stadtbibliothek · Bücherplatz 3 · 12345 Musterstadt",
        ("Stadt Musterstadt\nStadtbibliothek\nBücherplatz 3, 12345 Musterstadt",
         "Öffnungszeiten:\nDi-Fr 10-18 Uhr, Sa 10-14 Uhr",
         "Stadtkasse Musterstadt\nIBAN DE00 1234 0000 0000 0300 00"),
        None, "Stadtbibliothek",
        dict(art="amt", farbe=(0.20, 0.35, 0.60), zusatz="Stadt Musterstadt")),
    "kamin": _absender(
        "Kai Beispielmann", "Rußweg 5 · 12345 Musterstadt",
        ("Bezirksschornsteinfegermeister", "Kehrbezirk Musterstadt 7", "Telefon 01234 7007"),
        "Kai Beispielmann · Rußweg 5 · 12345 Musterstadt",
        ("Kai Beispielmann\nBezirksschornsteinfegermeister\nRußweg 5, 12345 Musterstadt",
         "Kehrbezirk Musterstadt 7\nbestellt durch den Landkreis Musterkreis", "IBAN DE00 1234 0000 0000 0007 00"),
        None, "Beispielmann",
        dict(art="schrift", farbe=(0.10, 0.10, 0.10), slogan="Bezirksschornsteinfegermeister"),
        datum="ort", post=False, signierer=(("Kai Beispielmann", "Bezirksschornsteinfegermeister"),)),
    "rs": _absender(
        "Musterrechtsschutz Versicherung AG", "Rechtsweg 11 · 45678 Musterhausen",
        ("Vertragsservice", "Telefon 04567 4321-0", "vertrag@musterrechtsschutz.example"),
        "Musterrechtsschutz Versicherung AG · Rechtsweg 11 · 45678 Musterhausen",
        ("Musterrechtsschutz Versicherung AG\nRechtsweg 11, 45678 Musterhausen",
         "Vorstand: Dr. Felix Probe (Vors.), Mia Muster\nSitz Musterhausen, Amtsgericht Musterhausen HRB 4321",
         "IBAN DE00 4567 0000 0000 4321 00\nVersicherungsteuer-Nr. 000/V00004321"),
        None, "Musterrechtsschutz",
        dict(art="kasten", farbe=(0.55, 0.08, 0.12), teile=("MUSTER", "RECHTSSCHUTZ"),
             slogan="Recht haben. Recht bekommen."),
        datum="nackt", rahmen=True, block=True,
        signierer=(("Dr. Felix Probe", "Vorstand"), ("Mia Muster", "Vorstand"))),
}


def _brief(nr, wer, datum, betreff, absaetze, art="eindeutig", info=(), gruss="Ihr Kundenservice",
           tabelle=None, anlage=None, grund="", stempel=None, seite2=None, fussnoten=(), anders=None,
           auch_neu=()):
    """stempel: Datum des Eingangsstempels; seite2: {titel, absaetze, tabelle?}; anders: Abweichungen vom Absender
    (z. B. Marke statt Firmenname, Brief über einen Makler); auch_neu: ebenfalls richtig ist ein NEUER Ordner mit
    einem dieser Namen (nur Wahrheit, nicht im Brief - der Fingerabdruck bleibt)."""
    return dict(nr=nr, wer=wer, datum=datum, betreff=betreff, absaetze=absaetze, art=art, info=info, gruss=gruss,
                tabelle=tabelle, anlage=anlage, grund=grund, stempel=stempel, seite2=seite2, fussnoten=fussnoten,
                anders=anders or {}, auch_neu=tuple(auch_neu))


# Anlage zu Brief 12: eine Rechnung eines ANDEREN vorhandenen Absenders - abgelegt wird beim Versicherer
_ANLAGE_12 = dict(wer="auto", titel="Rechnung Nr. W-2026-0412",
                  text="Reparatur Stoßfänger hinten, Lackierung, Kleinteile. Fahrzeug: Kombi, Kennzeichen MU-ST 123.",
                  tabelle=(("Position", "Betrag"), ("Stoßfänger hinten erneuert", "612,40 €"),
                           ("Lackierung", "398,00 €"), ("Kleinteile", "54,20 €"), ("Summe brutto", "1.064,60 €")))

_HINWEISE_VERS = (
    "Beitragsanpassung: Ändert sich der Beitrag aufgrund einer Anpassungsklausel, ohne dass sich der Umfang des "
    "Versicherungsschutzes ändert, können Sie den Vertrag innerhalb eines Monats nach Zugang der Mitteilung "
    "kündigen, frühestens jedoch zum Zeitpunkt des Wirksamwerdens der Erhöhung.",
    "Bitte teilen Sie uns innerhalb eines Monats mit, wenn sich das versicherte Risiko gegenüber Ihren Angaben "
    "geändert hat oder neue Risiken entstanden sind. Andernfalls kann der Versicherungsschutz gefährdet sein.",
    "Zahlen Sie den Beitrag nicht rechtzeitig, richten sich die Rechtsfolgen nach den Allgemeinen "
    "Versicherungsbedingungen. Gebündelte Verträge gelten jeweils gesondert für die aufgeführten Beiträge.",
    "Datenschutz: Informationen zur Verarbeitung Ihrer Daten finden Sie im Merkblatt zur Datenverarbeitung, "
    "Stand 07.2025, das wir Ihnen auf Wunsch gern zusenden.")

BRIEFE = (
    _brief(1, "vers", "12.01.2026", "Beitragsrechnung Hausratversicherung 2026",
           ("für Ihre Hausratversicherung wird zum 01.02.2026 der Jahresbeitrag fällig.",
            "Wir buchen den Betrag wie vereinbart von Ihrem Konto ab. Sie müssen nichts weiter tun."),
           info=(("Versicherungsschein", "HR-123456"), ("Zahlungsweise", "jährlich")), stempel="16.01.2026",
           tabelle=(("Leistung", "Nettobeitrag", "Versicherungsteuer", "Bruttobeitrag"),
                    ("Hausrat, Versicherungssumme 65.000 €", "124,54 €", "23,66 € 1)", "148,20 €"),
                    ("Glasversicherung", "20,17 €", "3,83 € 1)", "24,00 €"),
                    ("Gesamt", "", "", "172,20 € 2)")),
           fussnoten=("1) Die Versicherungsteuer beträgt 19 % des Nettobeitrags.",
                      "2) Vorangegangene Beitragsforderungen und Gutschriften sind nicht berücksichtigt."),
           seite2=dict(titel="Hinweise zu Ihrer Beitragsrechnung", absaetze=_HINWEISE_VERS)),
    _brief(2, "bank", "05.01.2026", "Rechnungsabschluss Girokonto 4. Quartal 2025",
           ("zum 31.12.2025 haben wir Ihr Girokonto 1234 5678 abgeschlossen. Der Saldo des Rechnungsabschlusses gilt "
            "als genehmigt, wenn Sie nicht innerhalb von sechs Wochen widersprechen.",),
           info=(("Kontonummer", "1234 5678"),),
           tabelle=(("Posten", "Betrag"), ("Kontoführung Oktober bis Dezember", "13,50 €"),
                    ("Zinsen für Guthaben", "0,00 €"), ("Saldo zum 31.12.2025", "2.418,77 € H")),
           gruss="Ihre Beispielbank eG"),
    _brief(3, "swerke", "14.02.2026", "Jahresabrechnung Strom 2025",
           ("anbei erhalten Sie Ihre Jahresabrechnung für den Abrechnungszeitraum 01.01.2025 bis 31.12.2025. "
            "Den Zählerstand haben wir am 31.12.2025 abgelesen (Zählernummer 1ESY 1234 5678).",
            "Das Guthaben von 86,40 € überweisen wir bis zum 03.03.2026 auf Ihr Konto. Ihr neuer monatlicher "
            "Abschlag ab 15.03.2026 beträgt 74,00 €. Diese Abrechnung ersetzt die vorläufige Mitteilung vom 08.01.2026."),
           art="schwer", grund="viele Datumsangaben und ein Eingangsstempel - Belegdatum ist das Briefdatum",
           info=(("Kundennummer", "200 345 678"), ("Rechnungsnummer", "2026-0214-0815")), stempel="19.02.2026",
           tabelle=(("Posten", "Betrag"), ("Verbrauch 2.410 kWh × 0,3120 €", "751,92 €"),
                    ("Grundpreis 12 Monate", "142,80 €"), ("Summe brutto", "894,72 €"),
                    ("geleistete Abschläge", "981,12 €"), ("Guthaben", "86,40 €")),
           seite2=dict(titel="Erläuterungen zu Ihrer Jahresabrechnung", absaetze=(
               "Ihr Strompreis setzt sich zusammen aus Energiebeschaffung und Vertrieb, Netzentgelten, "
               "Messstellenbetrieb, Konzessionsabgabe, Umlagen sowie Stromsteuer und Umsatzsteuer.",
               "Die Preise gelten seit dem 01.04.2025. Preisänderungen teilen wir Ihnen mindestens einen Monat vorher "
               "schriftlich mit.",
               "Verbraucherschlichtung: Bei Beschwerden wenden Sie sich bitte zuerst an unser Kundenzentrum. Wird "
               "Ihrer Beschwerde nicht abgeholfen, können Sie die Schlichtungsstelle Energie anrufen.",
               "Ihr Verbrauch im Vergleich: 2.410 kWh im Jahr 2025, 2.530 kWh im Jahr 2024. Ein vergleichbarer "
               "Zwei-Personen-Haushalt verbraucht etwa 2.500 kWh im Jahr."))),
    _brief(4, "fa", "18.03.2026", "Bescheid für 2024 über Einkommensteuer und Solidaritätszuschlag",
           ("Die Steuer wird festgesetzt wie folgt. Dieser Bescheid ergeht unter dem Vorbehalt der Nachprüfung "
            "(§ 164 AO).",
            "Der Erstattungsbetrag wird auf das Konto DE00 1234 5678 9012 3456 78 überwiesen."),
           art="schwer", grund="Formular mit Tabellen und Rechtstext auf zwei Seiten",
           info=(("Steuernummer", "123/456/78901"), ("Bei Rückfragen", "Frau Probst")), gruss="Finanzamt Musterstadt",
           tabelle=(("", "Einkommensteuer", "Solidaritätszuschlag"), ("festgesetzt", "6.214,00 €", "0,00 €"),
                    ("abzüglich Steuerabzug vom Lohn", "6.902,00 €", "0,00 €"), ("Erstattung", "688,00 €", "0,00 €")),
           seite2=dict(titel="Erläuterungen und Rechtsbehelfsbelehrung", absaetze=(
               "Die Aufwendungen für Arbeitsmittel wurden nur in Höhe von 110 € anerkannt, weil Belege fehlten.",
               "Der Bescheid ist nach § 165 Abs. 1 Satz 2 AO teilweise vorläufig. Die Vorläufigkeit umfasst die "
               "Abziehbarkeit der Beiträge zu Rentenversicherungen als Sonderausgaben.",
               "Rechtsbehelfsbelehrung: Der Bescheid kann mit dem Einspruch angefochten werden. Der Einspruch ist "
               "beim Finanzamt Musterstadt schriftlich einzureichen, diesem elektronisch zu übermitteln oder dort "
               "zur Niederschrift zu erklären. Die Frist für die Einlegung beträgt einen Monat. Sie beginnt mit "
               "Ablauf des Tages, an dem Ihnen dieser Bescheid bekannt gegeben worden ist.",
               "Bei Übermittlung durch die Post gilt der Bescheid am vierten Tag nach Aufgabe zur Post als bekannt "
               "gegeben."))),
    _brief(5, "bkk", "02.02.2026", "Ihr Beitrag ab 1. Januar 2026",
           ("der Zusatzbeitrag der Muster BKK beträgt ab dem 01.01.2026 1,9 Prozent. Ihr Arbeitgeber führt den "
            "Beitrag weiterhin direkt ab.",
            "Wegen der Änderung haben Sie ein Sonderkündigungsrecht bis zum 31.03.2026. Wir würden uns freuen, wenn "
            "Sie uns treu bleiben."),
           art="schwer", grund="Krankenkasse liegt im Ordner „Krankenkasse“, nicht unter ihrem Namen",
           info=(("Versichertennummer", "A123456789"),), gruss="Ihre Muster BKK"),
    _brief(6, "arzt", "23.02.2026", "Privatrechnung Reiseimpfung",
           ("für die Beratung und Impfung am 16.02.2026 berechnen wir nach der Gebührenordnung für Ärzte (GOÄ):",
            "Bitte überweisen Sie den Betrag innerhalb von 30 Tagen. Viele Krankenkassen erstatten Reiseimpfungen."),
           art="schwer", grund="Praxisname im Kopf, Ärztin erst im Infoblock; Datum ausgeschrieben",
           info=(("Rechnungsnummer", "P-2026-0231"),), gruss="Ihre Hausarztpraxis am Markt",
           tabelle=(("GOÄ", "Leistung", "Faktor", "Betrag"), ("1", "Beratung", "2,3", "10,72 €"),
                    ("375", "Impfung", "2,3", "10,72 €"), ("", "Impfstoff", "", "68,90 €"),
                    ("", "Summe", "", "90,34 €"))),
    _brief(7, "tel", "03.03.2026", "Ihre Rechnung Februar 2026",
           ("hier ist Ihre Rechnung für den Monat Februar 2026. Der Betrag wird am 10.03.2026 von Ihrem Konto "
            "abgebucht.",),
           info=(("Kundennummer", "TM-778899"), ("Rechnungsnummer", "R-2026-02-778899")),
           tabelle=(("Leistung", "Zeitraum", "Betrag"), ("Tarif Zuhause 100", "01.02.-28.02.", "39,95 €"),
                    ("Mobil S", "01.02.-28.02.", "9,99 €"), ("Summe brutto", "", "49,94 €")),
           fussnoten=("Alle Beträge enthalten 19 % Umsatzsteuer.",), gruss="Ihr Telemuster-Team"),
    _brief(8, "auto", "10.03.2026", "Rechnung Inspektion",
           ("vielen Dank für Ihren Auftrag. Für die Inspektion Ihres Fahrzeugs (Kennzeichen MU-ST 123, "
            "Kilometerstand 84.250) berechnen wir:",
            "Zahlbar sofort ohne Abzug. Wir wünschen Ihnen allzeit gute Fahrt."),
           info=(("Rechnungsnummer", "W-2026-0310"), ("Auftrag", "A-55812")), gruss="Ihr Werkstatt-Team",
           stempel="13.03.2026",
           tabelle=(("Position", "Betrag"), ("Inspektion nach Herstellervorgabe", "289,00 €"),
                    ("Motoröl 5 l", "64,50 €"), ("Ölfilter", "18,90 €"), ("Summe brutto", "372,40 €"))),
    _brief(9, "haus", "25.02.2026", "Angebot Austausch Heizungspumpe",
           ("wie besprochen bieten wir Ihnen den Austausch der Umwälzpumpe Ihrer Heizungsanlage an. Das Angebot gilt "
            "vier Wochen.",),
           info=(("Angebotsnummer", "A-2026-044"),), gruss="Haustechnik Mustergültig GmbH",
           tabelle=(("Position", "Betrag"), ("Hocheffizienzpumpe", "312,00 €"), ("Montage 2 Std.", "138,00 €"),
                    ("Summe brutto", "535,50 €"))),
    _brief(10, "werk", "31.01.2026", "Entgeltabrechnung Januar 2026",
           ("Personalnummer 004711, Steuerklasse I, Abrechnungsmonat 01/2026.",),
           anders=dict(signierer=(), kontakt=("Personalabteilung", "Entgeltabrechnung für MAX MUSTERMANN",
                                              "Personalnummer 004711")),
           gruss="Personalabteilung",
           tabelle=(("Bezeichnung", "Betrag"), ("Grundgehalt", "3.850,00 €"), ("Lohnsteuer", "-498,25 €"),
                    ("Sozialversicherung", "-806,10 €"), ("Auszahlung", "2.545,65 €"))),
    _brief(11, "hv", "30.04.2026", "Betriebskostenabrechnung 2025",
           ("für Ihre Wohnung Musterstraße 1, 2. OG links, erhalten Sie die Abrechnung der Betriebskosten für das "
            "Jahr 2025. Es ergibt sich eine Nachzahlung von 112,36 €, fällig zum 31.05.2026.",),
           art="schwer", grund="Kopf nennt „EXEMPLAR Immobilien“, der Ordner heißt „Hausverwaltung Exemplar“",
           anders=dict(name="EXEMPLAR Immobilien", adresse="Verwalterweg 9 · 23456 Beispielhausen",
                       zeile="EXEMPLAR Immobilien · Verwalterweg 9 · 23456 Beispielhausen",
                       logo=dict(art="kasten", farbe=(0.15, 0.40, 0.25), teile=("EXEMPLAR", "IMMOBILIEN"),
                                 slogan="Verwaltung · Vermietung"),
                       recht=("EXEMPLAR Immobilien\nVerwalterweg 9, 23456 Beispielhausen",
                              "Geschäftsführerin: Petra Probe\nAmtsgericht Beispielhausen HRB 3344",
                              "IBAN DE00 2345 0000 0000 3344 00")),
           gruss="EXEMPLAR Immobilien",
           tabelle=(("Kostenart", "Ihr Anteil"), ("Heizung und Warmwasser", "684,10 €"), ("Wasser", "212,40 €"),
                    ("Müllabfuhr", "96,00 €"), ("Hausreinigung", "119,86 €"), ("Vorauszahlungen", "-1.000,00 €"),
                    ("Nachzahlung", "112,36 €"))),
    _brief(12, "vers", "20.04.2026", "Ihre Schadenmeldung vom 14.04.2026 - Kfz-Haftpflicht",
           ("wir haben Ihre Schadenmeldung erhalten und die Rechnung des Autohauses Musterdorf geprüft. Den Betrag "
            "von 1.064,60 € überweisen wir direkt an die Werkstatt.",
            "Eine Kopie der Rechnung liegt diesem Schreiben bei."),
           art="schwer", grund="Anlage ist eine Rechnung eines anderen vorhandenen Absenders",
           info=(("Schadennummer", "KH-2026-5544"),), anlage=_ANLAGE_12, stempel="24.04.2026"),
    _brief(13, "bank", "15.03.2026", "Information zur Anpassung der Entgelte",
           ("ab dem 01.06.2026 ändern sich einzelne Entgelte für Ihr Girokonto. Die Kontoführung kostet dann "
            "5,50 € im Monat. Die Übersicht der Änderungen finden Sie auf der Rückseite.",
            "Wenn Sie nicht bis zum 31.05.2026 widersprechen, gilt Ihre Zustimmung als erteilt."),
           gruss="Ihre Beispielbank eG",
           seite2=dict(titel="Auszug aus dem Preis- und Leistungsverzeichnis, gültig ab 01.06.2026",
                       absaetze=("Die Änderungen betreffen nur die unten aufgeführten Posten. Alle anderen Entgelte "
                                 "bleiben unverändert.",
                                 "Sie können den Kontovertrag vor dem Wirksamwerden der Änderungen fristlos und "
                                 "kostenfrei kündigen."),
                       tabelle=(("Posten", "bisher", "neu"), ("Kontoführung monatlich", "4,50 €", "5,50 €"),
                                ("Girocard jährlich", "10,00 €", "12,00 €"),
                                ("Beleghafte Überweisung", "1,50 €", "2,00 €")))),
    _brief(14, "tier", "09.03.2026", "Rechnung Impfung",
           ("für die Behandlung Ihres Hundes „Bello“ am 06.03.2026 berechnen wir nach der Gebührenordnung für "
            "Tierärzte:",),
           art="neu", grund="kein Ordner vorhanden", gruss="Tierarztpraxis am Musterbach",
           tabelle=(("Leistung", "Betrag"), ("Allgemeine Untersuchung", "23,62 €"), ("Impfung", "31,50 €"),
                    ("Summe brutto", "89,05 €"))),
    _brief(15, "swerke", "20.02.2026", "Neue Abschlagszahlung ab März 2026",
           ("aufgrund Ihres Verbrauchs passen wir den monatlichen Abschlag für Strom an. Ab dem 15.03.2026 buchen "
            "wir 74,00 € ab.",),
           info=(("Kundennummer", "200 345 678"),)),
    _brief(16, "fa", "10.02.2026", "Festsetzung von Vorauszahlungen zur Einkommensteuer",
           ("Die Vorauszahlungen werden ab dem 1. Kalendervierteljahr 2026 auf je 150,00 € festgesetzt. "
            "Fälligkeiten: 10.03., 10.06., 10.09. und 10.12.2026.",),
           info=(("Steuernummer", "123/456/78901"),), gruss="Finanzamt Musterstadt"),
    _brief(17, "bkk", "16.04.2026", "Bonusprogramm: Ihre Prämie",
           ("Sie haben im Jahr 2025 an unserem Bonusprogramm teilgenommen und vier Maßnahmen nachgewiesen. "
            "Wir überweisen Ihnen eine Prämie von 60,00 €.",),
           info=(("Versichertennummer", "A123456789"),), gruss="Ihre Muster BKK"),
    _brief(18, "tel", "22.01.2026", "Bestätigung Ihres Tarifwechsels",
           ("vielen Dank für Ihren Auftrag. Ab dem 01.02.2026 telefonieren und surfen Sie im Tarif „Musterfunk "
            "Allnet M“ für 19,99 € im Monat. Ihre Rufnummer bleibt erhalten.",
            "Musterfunk ist eine Marke der Telemuster GmbH."),
           art="schwer", grund="Marke „Musterfunk“ statt Firmenname im Kopf",
           anders=dict(name="MUSTERFUNK", logo=dict(art="schrift", farbe=(0.85, 0.35, 0.0), slogan="Mobil telefonieren"),
                       zeile="Musterfunk · Postfach 5 00 · 23456 Beispielhausen",
                       kontakt=("Musterfunk Kundenservice", "Hotline 0800 123 457", "www.musterfunk.example")),
           info=(("Kundennummer", "TM-778899"),), gruss="Ihr Musterfunk-Team",
           # Peter 21.11.2026: „Ich bin bei Congstar, Congstar ist eine Tochter der Telekom, aber mir würde es nie
           # einfallen, Congstar unter Telekom einzuordnen“ - die Marke als eigener Ordner ist genauso richtig
           auch_neu=("Musterfunk",)),
    _brief(19, "auto", "01.04.2026", "Erinnerung: Hauptuntersuchung fällig",
           ("die Hauptuntersuchung Ihres Fahrzeugs mit dem Kennzeichen MU-ST 123 ist im Mai 2026 fällig. Gern "
            "übernehmen wir den Termin für Sie. Rufen Sie uns einfach an.",),
           gruss="Ihr Werkstatt-Team"),
    _brief(20, "haus", "18.03.2026", "Rechnung Nr. 2026-0315",
           ("für den Austausch der Heizungspumpe am 12.03.2026 laut Angebot A-2026-044 berechnen wir:",
            "Bitte überweisen Sie den Betrag innerhalb von 14 Tagen ohne Abzug."),
           info=(("Rechnungsnummer", "2026-0315"),), gruss="Haustechnik Mustergültig GmbH", stempel="21.03.2026",
           tabelle=(("Position", "Betrag"), ("Hocheffizienzpumpe", "312,00 €"), ("Montage 2,5 Std.", "172,50 €"),
                    ("Summe brutto", "576,56 €")),
           fussnoten=("Im Rechnungsbetrag sind 92,06 € Umsatzsteuer (19 %) enthalten. Lohnanteil nach § 35a EStG: "
                      "172,50 €.",)),
    _brief(21, "tsv", "15.01.2026", "Mitgliedsbeitrag 2026",
           ("der Jahresbeitrag für 2026 beträgt 96,00 €. Wir ziehen ihn am 01.02.2026 mit dem SEPA-Lastschrift-"
            "mandat ab (Mandatsreferenz TSV-0815).",),
           art="neu", grund="kein Ordner vorhanden", gruss="Der Vorstand"),
    _brief(22, "werk", "12.05.2026", "Bestätigung Ihres Urlaubsantrags",
           ("Ihr Urlaub vom 03.08.2026 bis 21.08.2026 (15 Arbeitstage) ist genehmigt. Ihr Resturlaub für 2026 "
            "beträgt danach 12 Tage.",), gruss="Personalabteilung"),
    _brief(23, "hv", "15.05.2026", "Ankündigung: Wartung der Rauchwarnmelder",
           ("am 10.06.2026 zwischen 8 und 12 Uhr prüft ein Fachbetrieb die Rauchwarnmelder in Ihrer Wohnung. Bitte "
            "ermöglichen Sie den Zutritt oder hinterlegen Sie einen Schlüssel.",), gruss="Hausverwaltung Exemplar GmbH"),
    _brief(24, "bank", "28.04.2026", "Jetzt Zinsen sichern: Ihre Baufinanzierung",
           ("träumen Sie vom eigenen Zuhause? Mit der Beispielbank-Baufinanzierung sichern Sie sich die Zinsen von "
            "heute für bis zu 15 Jahre. Vereinbaren Sie jetzt einen Beratungstermin in Ihrer Geschäftsstelle!",
            "Dieses Angebot ist freibleibend. Werbung."),
           art="schwer", grund="Werbebrief statt Kontobrief", gruss="Ihr Beratungsteam"),
    _brief(25, "vers", "07.05.2026", "Änderung Ihrer Bankverbindung",
           ("wir haben Ihre neue Bankverbindung für alle Verträge gespeichert. Ab der nächsten Fälligkeit buchen "
            "wir die Beiträge von diesem Konto ab.",), info=(("Kundennummer", "K-900123"),), stempel="11.05.2026"),
    _brief(26, "arzt", "11.05.2026", "Erinnerung Auffrischungsimpfung",
           ("Ihre Tetanus-Impfung liegt zehn Jahre zurück. Wir empfehlen eine Auffrischung. Bitte vereinbaren Sie "
            "einen Termin in unserer Sprechstunde.",), gruss="Ihr Praxisteam"),
    _brief(27, "bib", "06.05.2026", "Mahnung: Leihfrist überschritten",
           ("die Leihfrist für zwei Medien ist am 30.04.2026 abgelaufen. Bitte geben Sie die Medien zurück. Die "
            "Mahngebühr beträgt bisher 2,00 €.",),
           art="neu", grund="kein Ordner vorhanden; teilt den Ort mit den Stadtwerken", gruss="Stadtbibliothek Musterstadt",
           info=(("Lesernummer", "0001234"),)),
    _brief(28, "swerke", "12.06.2026", "Ankündigung Zählerwechsel",
           ("am 24.06.2026 tauschen wir Ihren Stromzähler gegen einen modernen digitalen Zähler. Der Wechsel dauert "
            "etwa 30 Minuten, der Strom ist kurz unterbrochen.",), info=(("Kundennummer", "200 345 678"),)),
    _brief(29, "fa", "02.06.2026", "Einkommensteuererklärung 2025 - Anforderung von Belegen",
           ("Für die Bearbeitung Ihrer Erklärung benötige ich noch die Belege zu den Handwerkerleistungen. Bitte "
            "reichen Sie diese bis zum 30.06.2026 ein.",),
           info=(("Steuernummer", "123/456/78901"),), gruss="Im Auftrag",
           anders=dict(signierer=(("Mustermitarbeiterin", "Sachbearbeitung"),))),
    _brief(30, "bkk", "20.06.2026", "Bescheinigung über Ihre Mitgliedschaft",
           ("hiermit bestätigen wir, dass Sie seit dem 01.04.2011 bei der Muster BKK versichert sind. Diese "
            "Bescheinigung gilt zur Vorlage beim Arbeitgeber.",), gruss="Ihre Muster BKK"),
    _brief(31, "tel", "04.06.2026", "Ihre Rechnung Mai 2026",
           ("hier ist Ihre Rechnung für den Monat Mai 2026. Der Betrag wird am 10.06.2026 von Ihrem Konto "
            "abgebucht.",),
           info=(("Kundennummer", "TM-778899"), ("Rechnungsnummer", "R-2026-05-778899")),
           tabelle=(("Leistung", "Zeitraum", "Betrag"), ("Tarif Zuhause 100", "01.05.-31.05.", "39,95 €"),
                    ("Musterfunk Allnet M", "01.05.-31.05.", "19,99 €"), ("Summe brutto", "", "59,94 €")),
           fussnoten=("Alle Beträge enthalten 19 % Umsatzsteuer.",), gruss="Ihr Telemuster-Team"),
    _brief(32, "auto", "15.10.2025", "Einlagerung Ihrer Sommerreifen",
           ("Ihre Sommerreifen lagern bis zum Frühjahr bei uns (Lagerplatz 14-B). Die Einlagerung kostet 39,00 € "
            "pro Saison.",), gruss="Ihr Werkstatt-Team"),
    _brief(33, "kamin", "22.05.2026", "Feuerstättenschau und Gebührenbescheid",
           ("bei der Feuerstättenschau am 19.05.2026 habe ich keine Mängel festgestellt. Für die Überprüfung Ihrer "
            "Gasheizung setze ich nach der Kehr- und Überprüfungsordnung folgende Gebühren fest:",),
           art="neu", grund="kein Ordner vorhanden", gruss="Kai Beispielmann", stempel="27.05.2026",
           tabelle=(("Leistung", "Betrag"), ("Feuerstättenschau", "38,40 €"), ("Abgaswegeüberprüfung", "27,60 €"),
                    ("Summe brutto", "78,54 €"))),
    _brief(34, "haus", "09.10.2025", "Wartung Gasheizung - Terminvorschlag",
           ("die jährliche Wartung Ihrer Gasheizung steht an. Wir schlagen Ihnen den 28.10.2025 um 9 Uhr vor. Bitte "
            "bestätigen Sie den Termin telefonisch.",), gruss="Haustechnik Mustergültig GmbH"),
    _brief(35, "werk", "01.12.2025", "Mitteilung über die Sonderzahlung 2025",
           ("mit der Abrechnung für November erhalten Sie eine Sonderzahlung von 1.925,00 € brutto. Wir danken "
            "Ihnen für Ihren Einsatz im Jahr 2025.",), gruss="Geschäftsführung",
           anders=dict(signierer=(("Dr. Herbert Muster", "Geschäftsführer"),))),
    _brief(36, "bank", "13.02.2026", "Wir ziehen um: Ihre Geschäftsstelle Beispielhausen-Nord",
           ("ab dem 02.03.2026 finden Sie uns in der Lindenallee 30. Ihre Kontoverbindung und Ihre Ansprechpartner "
            "bleiben gleich.",),
           art="schwer", grund="Geschäftsstelle mit anderer Adresse im Kopf",
           anders=dict(adresse="Geschäftsstelle Beispielhausen-Nord · Lindenallee 30 · 23456 Beispielhausen",
                       kontakt=("Geschäftsstelle Beispielhausen-Nord", "Lindenallee 30", "23456 Beispielhausen",
                                "Telefon 02345 6789-400"),
                       zeile="Beispielbank eG · Geschäftsstelle Nord · Lindenallee 30 · 23456 Beispielhausen"),
           gruss="Ihr Team der Geschäftsstelle"),
    _brief(37, "vers", "15.11.2025", "Ihre Jahresmitteilung zur Unfallversicherung",
           ("Ihre Unfallversicherung läuft unverändert weiter. Die Leistungen wurden zum 01.01.2026 ohne "
            "Mehrbeitrag verbessert.",
            "Die frühzeitige Übersendung dieser Mitteilung erfolgt aus technischen Gründen. Der Zeitpunkt, zu dem "
            "Ihr Beitrag fällig wird, bleibt hiervon unberührt."),
           art="schwer", grund="Brief über einen Makler: Rücksendezeile, Ansprechpartner und Ort nennen den Makler, "
                               "der Versicherer steht im Logo und im Kleingedruckten",
           info=(("Versicherungsschein", "UV-654321"),), gruss="Ihr Versicherungsmakler",
           anders=dict(zeile="Muster Assekuranz-Makler GmbH · Maklerweg 4 · 56789 Probstadt",
                       info_kopf=("Muster Assekuranz-Makler GmbH", "Maklerweg 4 · 56789 Probstadt"),
                       kontakt=("Ihr Ansprechpartner:", "Herr Tim Probe", "Telefon 05678 4321",
                                "probe@assekuranz-makler.example", "Steuer-Nr. 000/000/00000"),
                       datum="ort", ort="Probstadt", signierer=(),
                       recht=("Versicherer: Musterversicherung AG\nVersicherungsallee 10, 45678 Musterhausen\n"
                              "Amtsgericht Musterhausen HRB 1234",
                              "Muster Assekuranz-Makler GmbH, Sitz Probstadt\nAmtsgericht Probstadt HRB 4321\n"
                              "Geschäftsführer: Tim Probe",
                              "Vermittlerregister D-0000-ABCDE-00\nwww.vermittlerregister.example")),
           seite2=dict(titel="Hinweise", absaetze=_HINWEISE_VERS[:3])),
    _brief(38, "rs", "03.02.2026", "Ihr neuer Rechtsschutzvertrag",
           ("willkommen bei der Musterrechtsschutz! Ihr Vertrag beginnt am 01.03.2026. Der Beitrag beträgt "
            "21,40 € im Monat. Bitte prüfen Sie die Angaben in Ihrem Versicherungsschein auf Seite 2.",),
           art="neu", grund="kein Ordner vorhanden; ähnlicher Name und Logo wie die Musterversicherung",
           info=(("Versicherungsschein", "RS-2026-1001"),), stempel="06.02.2026",
           seite2=dict(titel="Versicherungsschein RS-2026-1001",
                       absaetze=("Versicherungsbeginn: 01.03.2026, 0 Uhr. Ablauf: 01.03.2027, 0 Uhr. Der Vertrag "
                                 "verlängert sich um jeweils ein Jahr, wenn er nicht drei Monate vor Ablauf "
                                 "gekündigt wird.",
                                 "Versicherte Bereiche: Privat-, Berufs- und Verkehrsrechtsschutz für Sie und Ihre "
                                 "Familie. Selbstbeteiligung je Rechtsschutzfall 150 €.",
                                 "Es gelten die Allgemeinen Bedingungen für die Rechtsschutzversicherung, Stand "
                                 "01.2026."),
                       tabelle=(("Baustein", "Monatsbeitrag"), ("Privat und Beruf", "15,10 €"),
                                ("Verkehr", "6,30 €"), ("Gesamt", "21,40 €")))),
    _brief(39, "arzt", "17.12.2025", "Rechnung für eine ärztliche Bescheinigung",
           ("für die am 10.12.2025 ausgestellte Bescheinigung berechnen wir nach GOÄ 15,00 €. Bitte überweisen Sie "
            "den Betrag innerhalb von 30 Tagen.",), info=(("Rechnungsnummer", "P-2025-1217"),),
           gruss="Ihre Hausarztpraxis am Markt"),
    _brief(40, "hv", "10.12.2025", "Information zum Winterdienst",
           ("ab sofort räumt ein Dienstleister die Gehwege an Werktagen ab 7 Uhr. Die Kosten werden über die "
            "Betriebskosten abgerechnet.",), gruss="Hausverwaltung Exemplar GmbH"),
)

CSS = """
body { font-family: sans-serif; font-size: 9.5pt; }
p { margin-top: 0; margin-bottom: 7pt; }
.zeile { font-size: 6pt; text-decoration: underline; margin-bottom: 2pt; }
.porto { font-size: 7pt; font-weight: bold; margin: 0; }
.code { font-size: 6pt; margin-bottom: 6pt; }
.an { font-size: 10pt; }
.info { font-size: 7.5pt; }
.ortdatum { text-align: right; margin-top: 4pt; }
.betreff { font-weight: bold; margin-top: 14pt; }
table.block td { font-size: 9pt; padding-right: 14pt; }
table.posten td { padding-right: 18pt; }
table.posten tr.kopf td { font-weight: bold; border-bottom: 1px solid black; }
table.rahmen { border-collapse: collapse; }
table.rahmen td { border: 1px solid #333333; padding: 2pt 5pt; font-size: 8.5pt; }
table.rahmen tr.kopf td { font-weight: bold; background-color: #e6e6e6; }
.fussnote { font-size: 7pt; margin: 0; }
.maschinell { font-size: 7.5pt; font-style: italic; }
.unterschrift td { font-size: 8.5pt; }
.hinweis td { font-size: 7.5pt; padding-right: 12pt; }
.seitenkopf { font-size: 8.5pt; margin-bottom: 14pt; }
"""


def ordner_der_sammlung():
    """Relative Ordnerpfade der Benchmark-Sammlung: Gruppen, Posteingang, Unsicher und die 11 Absender-Ordner."""
    absender = sorted({a["ordner"] for a in ABSENDER.values() if a["ordner"]})
    return ["0_Posteingang", "0_Unsicher", *GRUPPEN, *absender]


def wahrheit(nr):
    """{ordner (None = neuer Ordner oder Rückfrage richtig), auch_neu (Namen, unter denen ein NEUER Ordner ebenso
    richtig ist - Marke statt Konzern, Brief 18), datum (TT.MM.JJJJ), kennwort, art}."""
    b = BRIEFE[nr - 1]
    a = ABSENDER[b["wer"]]
    return {"ordner": a["ordner"], "auch_neu": b["auch_neu"], "datum": b["datum"], "kennwort": a["kennwort"],
            "art": b["art"]}


def ordner_richtig(nr, ordner_rel):
    """Liegt Brief `nr` im richtigen Ordner? `ordner_rel` relativ zur Sammlung mit „/“ (z. B. „P - Q - R - S - T/Telemuster“).
    Richtig ist der Ordner der Wahrheit oder - bei `auch_neu` - ein Ordner mit einem dieser Namen."""
    w = wahrheit(nr)
    return ordner_rel == w["ordner"] or ordner_rel.rsplit("/", 1)[-1] in w["auch_neu"]


def _absender_des_briefs(b):
    return {**ABSENDER[b["wer"]], **b["anders"]}


def _ort(a):
    return a["ort"] or a["adresse"].split("·")[-1].strip().split(" ", 1)[1]


def datum_im_brief(nr):
    """Das Belegdatum so, wie es im Brief steht („12.01.2026“ oder ausgeschrieben „12. Januar 2026“)."""
    b = BRIEFE[nr - 1]
    if _absender_des_briefs(b)["datum"] != "lang":
        return b["datum"]
    tag, monat, jahr = (int(t) for t in b["datum"].split("."))
    return f"{tag}. {MONATE[monat - 1]} {jahr}"


def _e(text):
    # „12,40 €“ nie vor dem Euro-Zeichen umbrechen
    return html.escape(text, quote=False).replace(" €", " €")


def _mindestbreite(pt):
    # Story ignoriert Spaltenbreiten (width=…) - ein unsichtbarer Platzhalter erzwingt die Mindestbreite einer Zelle
    return f"<p style='margin:0; padding-left:{pt}pt; font-size:1pt'>&nbsp;</p>"


def _tabelle(zeilen, rahmen):
    kopf, *rest = zeilen
    t = f"<table class='{'rahmen' if rahmen else 'posten'}'><tr class='kopf'>"
    t += "".join(f"<td>{_e(z)}</td>" for z in kopf) + "</tr>"
    for zeile in rest:
        t += "<tr>" + "".join(f"<td>{_e(z)}</td>" for z in zeile) + "</tr>"
    return t + "</table>"


def _infoblock(b, a):
    name, adresse = a.get("info_kopf") or (a["name"], a["adresse"])
    zeilen = [f"<b>{_e(name)}</b>", _e(adresse), ""] + [_e(z) for z in a["kontakt"]]
    if not a["block"] and b["info"]:
        zeilen += [""] + [f"{_e(k)}: {_e(v)}" for k, v in b["info"]]
    if a["datum"] == "info":
        zeilen += ["", f"Datum: {b['datum']}"]
    elif a["datum"] == "nackt":
        zeilen += ["", b["datum"]]
    return "<br>".join(zeilen)


def _seite1(b, a):
    nr = b["nr"]
    links = f"<p class='zeile'>{_e(a['zeile'])}</p>"
    if a["post"]:
        monat = b["datum"][3:5] + "." + b["datum"][8:]
        links += (f"<p class='porto'>DV {monat}&nbsp;&nbsp;&nbsp;0,95 Musterpost</p>"
                  f"<p class='code'>*{4567000 + nr * 13}*{nr:04d}{len(b['betreff']):03d}*</p>")
    else:
        links += "<p class='code'>&nbsp;</p>"
    links += "<p class='an'>" + "<br>".join(_e(z) for z in EMPFAENGER) + "</p>"
    teile = ["<div style='height:44pt'></div>",
             f"<table><tr><td>{_mindestbreite(270)}{links}</td>"
             f"<td class='info'>{_infoblock(b, a)}</td></tr></table>"]
    if a["datum"] in ("ort", "lang"):
        teile.append(f"<p class='ortdatum'>{_e(_ort(a))}, {_e(datum_im_brief(nr))}</p>")
    if a["block"]:
        zeilen = [("Versicherungsnehmer", "Max Mustermann"), *b["info"]]
        teile.append(f"<p class='betreff'>{_e(b['betreff'])}</p><table class='block'>"
                     + "".join(f"<tr><td>{_mindestbreite(115) if i == 0 else ''}<b>{_e(k)}</b></td><td>{_e(v)}</td></tr>"
                             for i, (k, v) in enumerate(zeilen))
                     + "</table><p></p>")
    else:
        teile.append(f"<p class='betreff'>{_e(b['betreff'])}</p>")
    teile.append("<p>Sehr geehrter Herr Mustermann,</p>")
    absaetze = list(b["absaetze"])
    teile.append(f"<p>{_e(absaetze.pop(0))}</p>")
    if b["tabelle"]:
        teile.append(_tabelle(b["tabelle"], a["rahmen"]))
        teile += [f"<p class='fussnote'>{_e(f)}</p>" for f in b["fussnoten"]]
        teile.append("<p></p>")
    teile += [f"<p>{_e(t)}</p>" for t in absaetze]
    if a["nachsatz"]:
        teile.append(f"<p>{_e(a['nachsatz'])}</p>")
    teile.append("<p>Mit freundlichen Grüßen</p>")
    signierer = a["signierer"]
    if not signierer or b["gruss"] != signierer[0][0]:
        teile.append(f"<p>{_e(b['gruss'])}</p>")
    if signierer:
        teile.append("<div style='height:30pt'></div><table class='unterschrift'><tr>"
                     + "".join(f"<td>{_mindestbreite(190)}{_e(n)}<br>{_e(f)}</td>" for n, f in signierer)
                     + "</tr></table>")
    else:
        teile.append("<p class='maschinell'>Dieses Schreiben wurde maschinell erstellt und ist ohne Unterschrift "
                     "gültig.</p>")
    if b["anlage"]:
        teile.append("<p>Anlage: Kopie der Rechnung</p>")
    return "".join(teile)


def _seite2(b, a):
    s2 = b["seite2"]
    bezug = f", {b['info'][0][0]} {b['info'][0][1]}" if b["info"] else ""
    absaetze = [f"<p>{_e(t)}</p>" for t in s2["absaetze"]]
    mitte = (len(absaetze) + 1) // 2
    teile = [f"<p class='seitenkopf'>Seite 2 zum Schreiben vom {_e(datum_im_brief(b['nr']))}{_e(bezug)}</p>",
             f"<p class='betreff'>{_e(s2['titel'])}</p>"]
    if s2.get("tabelle"):
        teile += [_tabelle(s2["tabelle"], True), "<p></p>"]
    teile.append(f"<table class='hinweis' width='100%'><tr><td width='50%'>{''.join(absaetze[:mitte])}</td>"
                 f"<td width='50%'>{''.join(absaetze[mitte:])}</td></tr></table>")
    return "".join(teile)


def _anlage(an):
    a = ABSENDER[an["wer"]]
    return (f"<p style='font-size:15pt; font-weight:bold'>{_e(a['name'])}</p><p class='info'>{_e(a['adresse'])}"
            f"</p><p class='betreff'>{_e(an['titel'])}</p><p>{_e(an['text'])}</p>" + _tabelle(an["tabelle"], False))


def html_abschnitte(nr):
    """Brief Nr. `nr` als HTML: [Brief, (Seite 2), (Anlage)] - jeder Abschnitt beginnt auf einer neuen Seite."""
    b = BRIEFE[nr - 1]
    a = _absender_des_briefs(b)
    abschnitte = [_seite1(b, a)]
    if b["seite2"]:
        abschnitte.append(_seite2(b, a))
    if b["anlage"]:
        abschnitte.append(_anlage(b["anlage"]))
    return abschnitte


# --- Zeichnungen (Dicts für PDFHandler._zeichne) --------------------------------------------------------------

def _breite(text, groesse, fett=True):
    # grobe Textbreite in Punkt für Helvetica - genug, um Logos zu bemessen
    return len(text) * groesse * (0.62 if fett else 0.5) + (len(text) * groesse * 0.1 if text.isupper() else 0)


def _logo(lg, name):
    f, art = lg["farbe"], lg["art"]
    slogan = lg.get("slogan", "")
    el = []
    if art == "kasten":
        teile = lg.get("teile") or (name,)
        breite = max(_breite(t, 13) for t in teile) + 16
        x0, y0, h = 545 - breite, 36, len(teile) * 15 + 8
        el.append({"rechteck": (x0, y0, 545, y0 + h), "farbe": f, "breite": 1.3})
        el += [{"text": t, "pos": (x0 + 8, y0 + 18 + i * 15), "groesse": 13, "schrift": "hebo", "farbe": f}
               for i, t in enumerate(teile)]
        if slogan:
            el.append({"text": slogan, "pos": (x0, y0 + h + 13), "groesse": 9, "schrift": "hebo", "farbe": f})
        # Firmenname klein links - so steht er auf echten Briefen neben dem Logo
        el.append({"text": name, "pos": (60, 50), "groesse": 11, "farbe": (0.2, 0.2, 0.2)})
    elif art == "balken":
        el.append({"rechteck": (60, 36, 60 + _breite(name, 15) + 20, 64), "fuellung": f, "farbe": None})
        el.append({"text": name, "pos": (70, 55), "groesse": 15, "schrift": "hebo", "farbe": WEISS})
        el.append({"text": slogan, "pos": (60, 76), "groesse": 8, "farbe": f})
    elif art in ("rund", "kachel"):
        z = lg["zeichen"]
        gr = 18 if len(z) == 1 else 13 if len(z) == 2 else 10
        if art == "rund":
            el.append({"kreis": (78, 54, 18), "fuellung": f, "farbe": None})
        else:
            el.append({"rechteck": (60, 36, 96, 72), "fuellung": f, "farbe": None})
        el.append({"text": z, "pos": (78 - _breite(z, gr) / 2, 54 + gr * 0.36), "groesse": gr, "schrift": "hebo",
                   "farbe": WEISS})
        el.append({"text": name, "pos": (104, 57), "groesse": 16, "schrift": "hebo", "farbe": f})
        if slogan:
            el.append({"text": slogan, "pos": (104, 70), "groesse": 8, "farbe": GRAU})
    elif art == "schrift":
        el.append({"text": name, "pos": (60, 60), "groesse": 20, "schrift": "hebo", "farbe": f})
        el.append({"linie": [(60, 68), (545, 68)], "farbe": f, "breite": 1.5})
        el.append({"text": slogan, "pos": (545 - _breite(slogan, 8, False), 80), "groesse": 8, "farbe": f})
    elif art == "amt":
        el.append({"linie": [(60, 36), (84, 36), (84, 56), (72, 68), (60, 56)], "geschlossen": True,
                   "fuellung": (0.88, 0.88, 0.88), "farbe": f, "breite": 1})
        el.append({"linie": [(66, 44), (78, 44), (78, 54), (72, 60), (66, 54)], "geschlossen": True,
                   "fuellung": f, "farbe": None})
        el.append({"text": name, "pos": (94, 52), "groesse": 13, "schrift": "hebo", "farbe": (0.1, 0.1, 0.1)})
        el.append({"text": lg["zusatz"], "pos": (94, 64), "groesse": 8, "farbe": GRAU})
    return el


def _unterschrift(saat, dx, dy):
    """Ein Namenszug als Linienzug: großer Anfangsbuchstabe, danach eine auslaufende Schreiblinie."""
    r = random.Random(saat)
    el = []
    h = r.uniform(12, 18)
    anfang = [(dx + 6 + 7 * math.sin(t / 20 * 2 * math.pi) * (1 - t / 40), dy + 26 - h * t / 20)
              for t in range(21)]
    anfang += [(dx + 6 + (t - 20) * 0.8 + 5 * math.cos((t - 20) / 6), dy + 26 - h + (t - 20) * h / 22)
               for t in range(20, 43)]
    el.append({"linie": anfang, "farbe": TINTE, "breite": 1.1})
    a = [r.uniform(2.5, 5.5) for _ in range(3)]
    f = [r.uniform(0.25, 0.7) for _ in range(3)]
    p = [r.uniform(0, 6.3) for _ in range(3)]
    laenge = r.uniform(70, 110)
    zug = []
    for i in range(140):
        t = i / 139 * laenge
        y = sum(a[k] * math.sin(f[k] * t + p[k]) for k in range(3)) * (1 - 0.6 * t / laenge)
        zug.append((dx + 24 + t + 2.5 * math.sin(t * 1.3 + p[0]), dy + 20 + y))
    el.append({"linie": zug, "farbe": TINTE, "breite": 0.9})
    return el


def _matrixcode(saat, x, y, zellen=12, g=1.4):
    r = random.Random(saat)
    el = []
    for i in range(zellen):
        for j in range(zellen):
            rand_ = i == 0 or j == zellen - 1
            takt = (j == 0 and i % 2 == 0) or (i == zellen - 1 and j % 2 == 1)
            if rand_ or takt or r.random() < 0.45:
                el.append({"rechteck": (x + i * g, y + j * g, x + (i + 1) * g, y + (j + 1) * g),
                           "fuellung": (0, 0, 0), "farbe": None})
    return el


def _stempel(datum):
    tag, monat, jahr = (int(t) for t in datum.split("."))
    return f"{tag}. {STEMPEL_MONATE[monat - 1]}. {jahr}"


def _recht(spalten):
    el = [{"linie": [(60, 738), (545, 738)], "farbe": GRAU, "breite": 0.4}]
    el += [{"text": s, "pos": (60 + i * 165, 747), "groesse": 5.6, "farbe": (0.2, 0.2, 0.2)}
           for i, s in enumerate(spalten)]
    return el


def _zeichnung(b, a):
    nr = b["nr"]
    brief_seiten = 2 if b["seite2"] else 1
    anlage_abschnitt = brief_seiten if b["anlage"] else None

    def zeichne(seite, seitenzahl, abschnitt):
        el = []
        if abschnitt == anlage_abschnitt:
            return [{"text": "KOPIE", "pos": (300, 330), "groesse": 46, "schrift": "hebo",
                     "farbe": (0.78, 0.78, 0.78), "drehung": -20}]
        if abschnitt == 0:
            el += _logo(a["logo"], a["name"])
            # Falzmarken (105 mm, 210 mm) und Lochmarke (148,5 mm) nach DIN 5008
            el += [{"linie": [(12, y), (22 + 6 * (y == 421), y)], "farbe": GRAU, "breite": 0.5}
                   for y in (297.6, 421, 595.3)]
            if a["post"]:
                el += [dict(e, anker="Musterpost") for e in _matrixcode(nr, 112, -2, zellen=14, g=1.6)]
                el += _matrixcode(nr * 7, 24, 470, zellen=11, g=1.3)
            if b["stempel"]:
                el.append({"text": _stempel(b["stempel"]), "pos": (128, 4), "groesse": 14, "schrift": "cobo",
                           "farbe": TINTE, "drehung": -4, "anker": "Musterstraße 1"})
            for i, _ in enumerate(a["signierer"]):
                el += [dict(e, anker="Mit freundlichen Grüßen") for e in _unterschrift(nr * 10 + i, i * 200, 20)]
            el += _recht(a["recht"])
        else:
            el.append({"text": a["name"], "pos": (545 - _breite(a["name"], 10), 40), "groesse": 10,
                       "schrift": "hebo", "farbe": a["logo"]["farbe"]})
        if abschnitt < brief_seiten:
            el.append({"text": f"{b['wer'].upper()} {nr:03d}-{b['datum'][3:5]}{b['datum'][8:]}  "
                               f"{1000 + nr * 37:05d}", "pos": (40, 720), "groesse": 5, "drehung": -90,
                       "farbe": GRAU})
            el.append({"text": f"F {b['wer'].upper()} {nr:02d}.{b['datum'][8:]}", "pos": (60, 800), "groesse": 6})
            if brief_seiten > 1:
                el.append({"text": f"Seite {seite + 1} von {brief_seiten}", "pos": (490, 800), "groesse": 7})
        return el
    return zeichne


def schreibe_satz(ziel):
    """Alle Prüfdokumente als einzelne PDFs (`Scan_0001.pdf` …) in `ziel` und dazu eine Sammel-PDF zum Ausdrucken.
    Vorhandene Dateien werden nie überschrieben (FileExistsError). :return: Liste der geschriebenen Einzel-PDFs"""
    os.makedirs(ziel, exist_ok=True)
    pfade = []
    for b in BRIEFE:
        pfad = os.path.join(ziel, DATEINAME.format(nr=b["nr"]))
        PDFHandler.schreibe_html_pdf(pfad, html_abschnitte(b["nr"]), CSS, FUSS.format(nr=b["nr"]),
                                     zeichnung=_zeichnung(b, _absender_des_briefs(b)), rand=RAND)
        pfade.append(pfad)
    PDFHandler.fuege_pdfs_zusammen(os.path.join(ziel, SAMMEL_PDF), pfade)
    return pfade


def fingerabdruck():
    """SHA-256 über alles, was die PDFs bestimmt (Seitentext als HTML, Zeichnungen je Seite, CSS, Fuß, Rand) - ohne
    PDFs zu schreiben und unabhängig von der PyMuPDF-Version. Muss FINGERABDRUCK gleichen."""
    teile = [CSS, FUSS, repr(RAND), DATEINAME]
    for b in BRIEFE:
        zeichne = _zeichnung(b, _absender_des_briefs(b))
        teile.append(repr(html_abschnitte(b["nr"])))
        n = seitenzahl(b["nr"])
        teile += [repr(zeichne(i, n, i)) for i in range(n)]
    return hashlib.sha256("\n".join(teile).encode("utf-8")).hexdigest()


def seitenzahl(nr):
    """Seiten des Prüfdokuments: Brief, ggf. Hinweisseite, ggf. Anlage."""
    b = BRIEFE[nr - 1]
    return 1 + bool(b["seite2"]) + bool(b["anlage"])


# „Prüfdokument 017“ - auch nach Texterkennung eines Scans („Prufdokument 017“, „Prüfdokument O17“)
_NUMMER = re.compile(r"pr\S{0,2}f\s*-?\s*dokument\s*([0-9oOIl]{3})", re.IGNORECASE)


def nummer_aus_text(text):
    """Nummer des Prüfdokuments aus dem (erkannten) Text einer Seite, oder None."""
    m = _NUMMER.search(text or "")
    if not m:
        return None
    ziffern = m.group(1).translate(str.maketrans("oOIl", "0011"))
    nr = int(ziffern)
    return nr if 1 <= nr <= len(BRIEFE) else None
