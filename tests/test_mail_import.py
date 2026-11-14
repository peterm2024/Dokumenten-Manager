"""Mail-Import (KONZEPT_MAIL_IMPORT.md): mail_lesen, mail_pst, Mail-PDF im pdf_handler, mail_import, KI-Antwort.
Nur synthetische Mails mit Musterdaten - nie echte."""
import collections
import datetime
import json
import mailbox
import os
import shutil
import tempfile
import unittest
from email.message import EmailMessage
from email.utils import format_datetime
from unittest.mock import patch

import fitz

import app_paths
import mail_import
import mail_lesen
import mail_pst
from pdf_handler import PDFHandler

EIGENE = {"max@example.org"}
TESTDATEIEN = os.path.join(os.path.expanduser("~"), "KID-Messungen", "mail_testdateien")


def baue(von="Musterversicherung <service@muster-versicherung.example>", an="Max Mustermann <max@example.org>",
         betreff="Ihre Beitragsrechnung", text="Sehr geehrter Herr Mustermann,\nanbei die Rechnung.",
         datum=datetime.datetime(2024, 3, 5, 9, 30, tzinfo=datetime.timezone.utc), mid="<abc123@muster.example>",
         kopf=None, html=None, anhang=None):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = von, an, betreff
    if datum:
        m["Date"] = format_datetime(datum)
    if mid:
        m["Message-ID"] = mid
    for k, v in (kopf or {}).items():
        m[k] = v
    m.set_content(text)
    if html:
        m.add_alternative(html, subtype="html")
    if anhang:
        name, daten = anhang
        m.add_attachment(daten, maintype="application", subtype="pdf", filename=name)
    return m.as_bytes()


def pdf_bytes(text="Rechnung Nr. 4711"):
    doc = fitz.open()
    doc.new_page().insert_text((72, 72), text)
    daten = doc.tobytes()
    doc.close()
    return daten

def hake_an(bestand, absender=""):
    """Wie ein Häkchen im Fenster (mails_importieren._setze_ergebnisse): offene Mails, deren Absender `absender`
    enthält, auf „übernehmen“ setzen."""
    for e in bestand.eintraege:
        if not e.ergebnis and absender in (e.adresse or ""):
            e.ergebnis = mail_import.UEBERNEHMEN



class TestTabellenAufloesen(unittest.TestCase):
    def test_nur_die_aeussere_tabelle_kommt_weg(self):
        html = ('<table width="600"><tbody><tr bgcolor="#112233"><td style="height:3000px;color:#fff;padding:4px">'
                '<table><tr><td>Betrag</td><td>49,90</td></tr></table></td></tr></tbody></table>')
        neu = mail_lesen.loese_tabellen(html)
        self.assertEqual(neu.count("<table"), 1)
        self.assertIn("<td>Betrag</td>", neu)
        self.assertNotIn("height", neu)
        self.assertIn("color:#fff", neu)                  # weiße Schrift bleibt lesbar: mit ihrem Hintergrund
        self.assertIn("padding:4px", neu)                 # ohne eigene Farbe bleibt das Polster
        self.assertIn('style="background-color:#112233"', neu)
        self.assertNotIn("600", neu)

    def _farbige_seiten(self, html):
        """Je Seite die Zahl blauer Pixel einer Mail mit blauem Kopf und viel Text."""
        with tempfile.TemporaryDirectory() as t:
            pfad = os.path.join(t, "a.pdf")
            PDFHandler.schreibe_mail_pdf(pfad, html, "", {}, b"x", {})
            with fitz.open(pfad) as doc:
                ergebnis = []
                for seite in doc:
                    bild = seite.get_pixmap(dpi=40)
                    d, n = bild.samples, bild.n
                    ergebnis.append(sum(1 for i in range(0, len(d), n) if d[i] < 60 and d[i + 2] > 140))
                return ergebnis

    def test_farbiger_block_mit_polster_erscheint_nicht_auf_jeder_folgeseite(self):
        # MuPDF malt das obere Polster eines farbigen Blocks oben auf jede weitere Seite, über den Text
        text = "<p>Absatz mit etwas Text darin, damit die Seiten voll werden.</p>" * 120
        kopf = '<table><tr><td bgcolor="#1a5fb4" style="padding:20px">Kopf</td></tr><tr><td>'
        html, _, _ = mail_lesen.bereinige_html(f'<div style="background-color:#1a5fb4;padding:20px">Kopf</div>{text}')
        with self.subTest("Block aus der Mail"):
            farben = self._farbige_seiten(html)
            self.assertGreater(farben[0], 0)
            self.assertEqual(farben[1:], [0] * (len(farben) - 1))
        with self.subTest("aufgelöste Tabelle"):
            farben = self._farbige_seiten(mail_lesen.loese_tabellen(f"{kopf}{text}</td></tr></table>", alle=True))
            self.assertGreater(farben[0], 0)
            self.assertEqual(farben[1:], [0] * (len(farben) - 1))

    def test_alle_tabellen(self):
        neu = mail_lesen.loese_tabellen("<table><tr><td>A</td><th>B</th></tr></table>", alle=True)
        self.assertEqual(neu, "<div><div><div>A</div><div>B</div></div></div>")

    def test_einzelne_tabelle_bleibt_ohne_alle(self):
        html = "<table><tr><td>A</td></tr></table>"
        self.assertEqual(mail_lesen.loese_tabellen(html), html)

    def test_kaputte_verschachtelung_wirft_nichts_weg(self):
        for html in ("</td></tr></table>Text", "<td>Text", "<table><tr><td>Text"):
            self.assertIn("Text", mail_lesen.loese_tabellen(html, alle=True))

    def test_nur_text_trennt_tabellenzellen(self):
        self.assertIn("Betrag 49,90", mail_lesen.html_zu_text("<table><tr><td>Betrag</td><td>49,90</td></tr></table>"))


class TestMailLesen(unittest.TestCase):
    def test_html_zu_suchtext_wie_html_zu_text(self):
        # S3 (10.11.2026): siebenmal so schnell, aber derselbe Suchtext
        import suchsyntax
        proben = [
            "<html><head><title>Titel</title><style>.a { color: red }</style></head><body><p>Guten Tag</p></body></html>",
            "<table><tr><td>Betrag</td><td>49,90&nbsp;&euro;</td></tr></table>",
            "<p>Erste<br>Zweite<BR/>Dritte</p><div>Vierte</div><ul><li>Fünfte</li></ul>",
            "<!-- Kommentar > mit Klammer --><script type='x'>var a = '<p>';</script><b>Rechnung</b> &amp; Mahnung",
            "<STYLE type=text/css>p { margin: 0 }</STYLE><a href='https://x.example/?a=1&amp;b=2'>Link</a> &uuml;ber",
            "Kein HTML, nur Text mit < und > Zeichen",
        ]
        for roh in proben:
            self.assertEqual(suchsyntax.normalisiere(mail_lesen.html_zu_suchtext(roh)),
                             suchsyntax.normalisiere(mail_lesen.html_zu_text(roh)), roh)
        self.assertIn("Betrag 49,90", mail_lesen.html_zu_suchtext(proben[1]))

    def test_kopf_und_titel(self):
        m = mail_lesen.Mail(baue(betreff="AW: WG: Ihre Beitragsrechnung"))
        self.assertEqual(m.titel, "Ihre Beitragsrechnung")
        self.assertEqual(m.von_adressen, ["service@muster-versicherung.example"])
        self.assertEqual(m.message_id, "abc123@muster.example")
        self.assertEqual(m.schluessel(), "mid:abc123@muster.example")

    def test_datum_in_ortszeit(self):
        # S1: der Date-Kopf steht in der Zeitzone des Absenders - 23:30 in New York ist hier schon der nächste Tag
        ny = datetime.timezone(datetime.timedelta(hours=-5))
        m = mail_lesen.Mail(baue(datum=datetime.datetime(2024, 3, 5, 23, 30, tzinfo=ny)))
        erwartet = datetime.datetime(2024, 3, 6, 4, 30, tzinfo=datetime.timezone.utc).astimezone().replace(tzinfo=None)
        self.assertEqual(m.datum, erwartet)
        self.assertEqual(mail_lesen.datum_text(m), erwartet.strftime("%Y-%m-%d"))

    def test_8bit_kopf_als_cp1252(self):
        roh = (b"From: M\xfcller <m@example.org>\r\nTo: max@example.org\r\nSubject: Gr\xfc\xdfe\r\n"
               b"Content-Type: text/plain\r\n\r\nText\r\n")
        m = mail_lesen.Mail(roh)
        self.assertEqual(m.betreff, "Grüße")
        self.assertIn("Müller", m.von)

    def test_fingerabdruck_ohne_message_id(self):
        a = mail_lesen.Mail(baue(mid=None))
        b = mail_lesen.Mail(baue(mid=None))
        c = mail_lesen.Mail(baue(mid=None, text="ganz anderer Text"))
        self.assertTrue(a.schluessel().startswith("fp:"))
        self.assertEqual(a.schluessel(), b.schluessel())
        self.assertNotEqual(a.schluessel(), c.schluessel())

    def test_richtung_und_gegenueber(self):
        ein = mail_lesen.Mail(baue())
        self.assertEqual(mail_lesen.richtung(ein, EIGENE), "ein")
        self.assertEqual(mail_lesen.gegenueber(ein, EIGENE), ("Musterversicherung", "service@muster-versicherung.example"))
        aus = mail_lesen.Mail(baue(von="Max <max@example.org>",
                                   an="Max <max@example.org>, Erika Musterfrau <erika@musterstadt.example>"))
        self.assertEqual(mail_lesen.richtung(aus, EIGENE), "aus")
        self.assertEqual(mail_lesen.gegenueber(aus, EIGENE), ("Erika Musterfrau", "erika@musterstadt.example"))
        # eine ganze Domain als eigene Adresse
        self.assertEqual(mail_lesen.richtung(aus, {"@example.org"}), "aus")

    def test_vorfilter(self):
        self.assertEqual(mail_lesen.vorfilter(mail_lesen.Mail(baue()), "Posteingang"), "")
        self.assertEqual(mail_lesen.vorfilter(mail_lesen.Mail(baue()), "Postfach/Junk-E-Mail"), "Spam- oder Papierkorb-Ordner")
        self.assertEqual(mail_lesen.vorfilter(mail_lesen.Mail(baue()), "Gelöschte Elemente"), "Spam- oder Papierkorb-Ordner")
        # Peter 05.11.2026: Nie abgeschickte Mails gehören nicht in die Sammlung
        for ordner in ("Entwürfe", "Postfach/Entwürfe", "[Gmail]/Drafts", "Draft", "Vorlagen", "Konto\\Templates"):
            self.assertEqual(mail_lesen.vorfilter(mail_lesen.Mail(baue()), ordner), mail_lesen.GRUND_ENTWURF, ordner)
        # Nur der Ordner selbst: Eigene Ordner, die das Wort nur enthalten, bleiben drin
        for ordner in ("Entwürfe Haus", "Vorlagen/Kunden", "Gesendete Elemente", "Sent"):
            self.assertEqual(mail_lesen.vorfilter(mail_lesen.Mail(baue()), ordner), "", ordner)
        # Peter 05.11.2026 (T20.4): Bestellbestätigungen und AGB-Änderungen tragen auch einen Abmeldelink, Antworten
        # eines Ticket-Systems auf eine Kündigung die Kennung „automatisch“ - das entscheidet die KI, nicht der Kopf
        news = mail_lesen.Mail(baue(betreff="Deine Bestellbestätigung", kopf={"List-Unsubscribe": "<mailto:weg@example.org>"}))
        self.assertEqual(mail_lesen.vorfilter(news), "")
        auto = mail_lesen.Mail(baue(betreff="AW: Ihre Kündigung", kopf={"Auto-Submitted": "auto-replied"}))
        self.assertEqual(mail_lesen.vorfilter(auto), "")
        self.assertEqual(mail_lesen.vorfilter(mail_lesen.Mail(baue(betreff="Gelesen: Angebot"))), "Lesebestätigung")
        # Peter 30.10.2026: No-Reply-Absender schicken Rechnungen - nicht pauschal raus
        self.assertEqual(mail_lesen.vorfilter(mail_lesen.Mail(baue(von="Shop <noreply@shop.example>"))), "")

    def test_html_ohne_externe_inhalte(self):
        html = ('<html><head><style>p{color:red}</style><script>alert(1)</script></head><body>'
                '<p onclick="x()">Hallo</p><img src="https://tracker.example/p.gif" width="1" height="1">'
                '<img src="https://shop.example/bild.png"><iframe src="https://x.example"></iframe>'
                '<a href="javascript:x()">weg</a><a href="https://shop.example">Shop</a></body></html>')
        sicher, externe, stile = mail_lesen.bereinige_html(html)
        self.assertNotIn("script", sicher)
        self.assertNotIn("alert", sicher)
        self.assertNotIn("onclick", sicher)
        self.assertNotIn("tracker.example", sicher)
        self.assertNotIn("iframe", sicher)
        self.assertNotIn("javascript", sicher)
        self.assertIn('href="https://shop.example"', sicher)
        self.assertIn("[Bild nicht geladen]", sicher)     # das große Bild, das Zählpixel still
        self.assertEqual(externe, 2)
        self.assertIn("color:red", stile)

    def test_gegenueber_ohne_anfuehrungszeichen_und_ohne_adresse_als_name(self):
        # Aus dem Namen im Mailkopf wird ein Ordner: Betatest 06.11.2026 ergab Ordner wie 'M.Muster' und max@…
        for kopf, name in (("'M.Muster' <m@firma.example>", "M.Muster"),
                           ("\"'Customer Support'\" <c@firma.example>", "Customer Support"),
                           ("\"m@firma.example\" <m@firma.example>", ""),
                           ("Conan O'Brien <c@firma.example>", "Conan O'Brien")):
            with self.subTest(kopf=kopf):
                m = mail_lesen.Mail(baue(von=kopf, an="Max <max@example.org>"))
                self.assertEqual(mail_lesen.gegenueber(m, EIGENE)[0], name)

    def test_platzhalter_nur_ausserhalb_von_tabellen(self):
        # Langer Text in einer winzigen Layout-Zelle drückt die Spalten zusammen, die Zahl steht im Hinweis (FALLSTRICKE #110)
        bild = '<img src="https://shop.example/bild.png" width="20">'
        sicher, externe, _ = mail_lesen.bereinige_html(f"<table><tr><td>{bild}Text</td></tr></table>")
        self.assertNotIn("[Bild nicht geladen]", sicher)
        self.assertEqual(externe, 1)
        sicher, externe, _ = mail_lesen.bereinige_html(f"<table><tr><td>Text</td></tr></table><p>{bild}</p>")
        self.assertIn("[Bild nicht geladen]", sicher)
        self.assertEqual(externe, 1)

    def test_nur_ganze_regeln(self):
        f = mail_lesen._nur_ganze_regeln
        self.assertEqual(f("p{color:red}"), "p{color:red}")
        self.assertEqual(f("/* Kommentar */p{color:red}"), " p{color:red}")
        self.assertEqual(f("p{color:red}@keyframes x {from {top:0}"), "p{color:red}")      # offen bis zum Ende
        self.assertEqual(f("} p{color:red} rest"), " p{color:red}")
        self.assertEqual(f("p{color:red}/* offen"), "p{color:red}")
        self.assertIn("to {top:0}", f("@keyframes x {from {top:0} to {top:0}}"))

    def test_kaputte_stile_der_mail_lassen_unsere_regeln_stehen(self):
        # Der Parser schluckt sonst alles dahinter, auch den Kopfblock (FALLSTRICKE #110)
        for kaputt in ("@keyframes x { from { top:0 } to { top:0 }", "p{color:red} }}", "p{color:red} /* offen",
                       ".&.yahoo { display:none }"):
            with self.subTest(kaputt=kaputt):
                html = f"<html><head><style>{kaputt}</style></head><body><p>Text</p></body></html>"
                mail = mail_lesen.Mail(baue(text="Text", html=html))
                stile, seite, bilder = mail_lesen.seite_html(mail)
                ordner = tempfile.mkdtemp()
                self.addCleanup(shutil.rmtree, ordner, True)
                ziel = os.path.join(ordner, "m.pdf")
                PDFHandler.schreibe_mail_pdf(ziel, seite, stile, bilder, mail.daten, {})
                with fitz.open(ziel) as doc:
                    spans = [s for b in doc[0].get_text("dict")["blocks"] for z in b["lines"] for s in z["spans"]]
                self.assertEqual(round(spans[0]["size"]), 13)       # .betreff
                self.assertEqual(round(spans[-1]["size"]), 10)      # * { font-size: 10pt }

    def test_textanfang_aus_html(self):
        m = mail_lesen.Mail(baue(text="Text", html="<p>Bestellung <b>4711</b></p><script>x</script>"))
        self.assertEqual(m.textanfang(), "Bestellung 4711")

    def test_lange_woerter_umbrechbar(self):
        self.assertIn("\u200b", mail_lesen.brich_lange_woerter("x" * 100))
        self.assertEqual(mail_lesen.brich_lange_woerter("kurz"), "kurz")

    def test_kaputte_mail_wirft_nicht(self):
        m = mail_lesen.Mail(b"Subject: =?unbekannt?Q?x?=\r\nContent-Type: text/plain; charset=gibtsnicht\r\n\r\n\xe4\r\n")
        self.assertIsNone(m.datum)
        self.assertTrue(m.schluessel().startswith("fp:"))
        stile, seite, _ = mail_lesen.seite_html(m)
        self.assertIn("(ohne Datum)", seite)


class _Eintrag:
    def __init__(self, typ, wert):
        self.entry_type, self.data_as_string = typ, wert


class _Satz:
    def __init__(self, eintraege):
        self._e = eintraege
        self.number_of_entries = len(eintraege)

    def get_entry(self, i):
        return self._e[i]


class _Nachricht:
    """Nachbau eines pypff-Eintrags (nur die Attribute, die mail_pst benutzt)."""

    def __init__(self, klasse="IPM.Note", kopf="", eigenschaften=None, betreff="Angebot", text="Hallo",
                 html=None, anhaenge=()):
        e = {mail_pst.PR_MESSAGE_CLASS: klasse, **(eigenschaften or {})}
        self._saetze = [_Satz([_Eintrag(k, v) for k, v in e.items()])]
        self.number_of_record_sets = 1
        self.transport_headers = kopf
        self.sender_name = "Max Mustermann"
        self.subject = betreff
        self.client_submit_time = datetime.datetime(2009, 6, 1, 12, 0)
        self.delivery_time = self.creation_time = None
        self.plain_text_body = text.encode("utf-8") if text else b""
        self.html_body = html.encode("utf-8") if html else b""
        self.rtf_body = b""
        self._anhaenge = list(anhaenge)
        self.number_of_attachments = len(self._anhaenge)

    def get_record_set(self, i):
        return self._saetze[i]

    def get_attachment(self, i):
        name, daten = self._anhaenge[i]

        class _A:
            size = len(daten)
            long_filename = name

            def read_buffer(self, n):
                return daten[:n]
        return _A()


class _Ordner:
    def __init__(self, name, nachrichten=(), unter=()):
        self.name, self._n, self._u = name, list(nachrichten), list(unter)
        self.number_of_sub_messages, self.number_of_sub_folders = len(self._n), len(self._u)

    def get_sub_message(self, i):
        return self._n[i]

    def get_sub_folder(self, i):
        return self._u[i]


class TestMailPst(unittest.TestCase):
    def test_gesendete_mail_aus_eigenschaften(self):
        # S2: gesendete Mails haben keine gespeicherten Kopfzeilen - Absender, An und Message-ID aus den Eigenschaften
        n = _Nachricht(eigenschaften={mail_pst.PR_SENDER_SMTP: "max@example.org",
                                      mail_pst.PR_DISPLAY_TO: "erika@musterstadt.example",
                                      mail_pst.PR_INTERNET_MESSAGE_ID: "<s1@example.org>"},
                       anhaenge=[("Rechnung.pdf", pdf_bytes())])
        m = mail_lesen.Mail(mail_pst.baue_eml(n))
        self.assertEqual(m.von_adressen, ["max@example.org"])
        self.assertEqual(m.an, "erika@musterstadt.example")
        self.assertEqual(m.message_id, "s1@example.org")
        self.assertEqual(m.datum.year, 2009)
        self.assertEqual(m.textanfang(), "Hallo")
        self.assertEqual([a["name"] for a in m.koerper()[3]], ["Rechnung.pdf"])
        self.assertEqual(mail_lesen.richtung(m, EIGENE), "aus")

    def test_leerer_oder_mehrzeiliger_kopf_ist_nicht_unlesbar(self):
        # T20.4: 6 von 238 echten Mails fielen als „unlesbar“ durch - ValueError beim Setzen des Betreffs: Eine leere
        # Subject-Zeile in den Kopfzeilen zählt als „kein Betreff“, die zweite darf es aber nicht geben; Betreffe und
        # Empfänger aus den MAPI-Eigenschaften können Zeilenumbrüche enthalten
        leer = "From: Erika <erika@musterstadt.example>\r\nSubject: \r\nTo: \r\nMessage-ID: \r\n"
        m = mail_lesen.Mail(mail_pst.baue_eml(_Nachricht(
            kopf=leer, betreff="Grüße aus dem Urlaub",
            eigenschaften={mail_pst.PR_DISPLAY_TO: "max@example.org", mail_pst.PR_INTERNET_MESSAGE_ID: "<l1@x>"})))
        self.assertEqual((m.betreff, m.an, m.message_id), ("Grüße aus dem Urlaub", "max@example.org", "l1@x"))
        m = mail_lesen.Mail(mail_pst.baue_eml(_Nachricht(
            betreff="Zeile 1\r\nZeile 2", eigenschaften={mail_pst.PR_DISPLAY_TO: "Erika\nMusterfrau"})))
        self.assertEqual(m.betreff, "Zeile 1 Zeile 2")
        self.assertIn("Erika Musterfrau", m.an)                  # ohne Adresse setzt die Bibliothek Anführungszeichen

    def test_kopfmail_wie_mail(self):
        # S3b (12.11.2026): .pst direkt, ohne .eml - dieselben Felder wie über baue_eml und Mail
        import suchsyntax
        kodiert = ("From: =?iso-8859-1?q?M=FCller=2C_Erika?= <erika@musterstadt.example>\r\nTo: max@example.org,\r\n"
                   " Erika <erika@musterstadt.example>\r\nCc: \"Mustermann, Max\" <max@example.org>\r\n"
                   "Subject: =?utf-8?q?Gr=C3=BC=C3=9Fe_aus_dem_Urlaub?=\r\nMessage-ID: <k2@musterstadt.example>\r\n"
                   "Date: Tue, 2 Jun 2009 08:15:00 +0200\r\nList-Unsubscribe:\r\n <mailto:weg@musterstadt.example>\r\n"
                   "Auto-Submitted: auto-generated\r\nContent-Type: multipart/report; "
                   "report-type=disposition-notification\r\n")
        rtf = _Nachricht(kopf="Subject: Nur RTF\r\nMessage-ID: <r1@x>\r\n", text=None)
        rtf.rtf_body = b"{\\rtf1 Hallo}"
        faelle = {
            "kodiert": _Nachricht(kopf=kodiert, text="Hallo", html="<p>Hallo <b>Erika</b></p>",
                                  anhaenge=[("Beitrag.pdf", pdf_bytes()), ("Bild.jpg", b"x")]),
            "gesendet": _Nachricht(eigenschaften={mail_pst.PR_SENDER_SMTP: "max@example.org",
                                                  mail_pst.PR_DISPLAY_TO: "erika@musterstadt.example",
                                                  mail_pst.PR_DISPLAY_CC: "Erika\nMusterfrau",
                                                  mail_pst.PR_INTERNET_MESSAGE_ID: "<s1@example.org>"}),
            "leere Zeilen": _Nachricht(kopf="From: Erika <erika@musterstadt.example>\r\nSubject: \r\nTo: \r\n"
                                            "Message-ID: \r\n", betreff="Lesebestätigung: Angebot",
                                       eigenschaften={mail_pst.PR_DISPLAY_TO: "max@example.org",
                                                      mail_pst.PR_INTERNET_MESSAGE_ID: "<l1@x>"}),
            "nur RTF": rtf,
            "ohne alles": _Nachricht(text=None, betreff=""),
        }
        felder = ("von", "an", "cc", "betreff", "titel", "message_id", "datum_roh", "datum", "von_adressen",
                  "an_adressen", "liste", "automatisch", "lesebestaetigung")
        for name, n in faelle.items():
            alt = mail_lesen.Mail(mail_pst.baue_eml(n, anhaenge=False, ein_text=True))
            neu = mail_lesen.KopfMail(mail_pst.kopfzeilen(n), mail_pst.anhang_namen(n), mail_pst.text_teil(n))
            self.assertEqual([getattr(neu, f) for f in felder], [getattr(alt, f) for f in felder], name)
            self.assertEqual(neu.koerper()[0], alt.koerper()[0], name)
            self.assertEqual(suchsyntax.normalisiere(neu.koerper()[1]), suchsyntax.normalisiere(alt.koerper()[1]), name)
            self.assertEqual([(a["name"], a["typ"]) for a in neu.anhaenge_ohne_inhalt()],
                             [(a["name"], a["typ"]) for a in alt.anhaenge_ohne_inhalt()], name)
            if alt.message_id:
                self.assertEqual(neu.schluessel(), alt.schluessel(), name)
        self.assertTrue(mail_lesen.KopfMail(mail_pst.kopfzeilen(faelle["kodiert"]), []).liste)

    def test_ein_text_aendert_weder_kennung_noch_text(self):
        # S3 (10.11.2026): beim Einlesen nur der Textteil, den Mail.koerper liest. Mails ohne Message-ID erkennt KID am
        # Textanfang - der darf sich nicht ändern, sonst erschienen schon übernommene Mails als neu
        for html in ("<p>Guten <b>Tag</b>, anbei die Rechnung</p>", None):
            for text in ("Guten Tag, anbei die Rechnung", None):
                n = _Nachricht(text=text, html=html, anhaenge=[("R.pdf", pdf_bytes())])
                beide = mail_lesen.Mail(mail_pst.baue_eml(n, anhaenge=False))
                einer = mail_lesen.Mail(mail_pst.baue_eml(n, anhaenge=False, ein_text=True))
                self.assertFalse(einer.message_id)
                self.assertEqual(einer.schluessel(), beide.schluessel(), (html, text))
                self.assertEqual(einer.koerper()[:2], beide.koerper()[:2], (html, text))
                self.assertEqual([a["name"] for a in einer.koerper()[3]], ["R.pdf"])
                if html and text:
                    self.assertLess(len(einer.daten), len(beide.daten))

    def test_eingegangene_mail_aus_kopfzeilen(self):
        kopf = ("From: Musterbank <info@musterbank.example>\r\nTo: max@example.org\r\nSubject: Kontoauszug\r\n"
                "Message-ID: <k1@musterbank.example>\r\nDate: Mon, 1 Jun 2009 12:00:00 +0200\r\n"
                "List-Unsubscribe:\r\n <mailto:weg@musterbank.example>\r\nContent-Type: text/html\r\n")
        m = mail_lesen.Mail(mail_pst.baue_eml(_Nachricht(kopf=kopf)))
        self.assertEqual(m.betreff, "Kontoauszug")
        self.assertEqual(m.message_id, "k1@musterbank.example")
        self.assertTrue(m.liste)                       # umgebrochene Kopfzeile entfaltet
        self.assertEqual(m.koerper()[0], "text")       # Content-Type der Kopfzeilen gilt nicht - Inhalt neu gebaut

    def test_ordner_und_orte(self):
        kalender = _Nachricht(klasse="IPM.Appointment")
        baum = _Ordner("", unter=[_Ordner("Posteingang", [_Nachricht(betreff="A"), kalender],
                                          unter=[_Ordner("Versicherung", [_Nachricht(betreff="B")])]),
                                  _Ordner("Junk-E-Mail", [_Nachricht(betreff="C")])])

        class _Datei:
            root_folder = baum
        funde = list(mail_pst.mails(_Datei()))
        self.assertEqual([(o, p) for o, p, _ in funde],
                         [("0/0", "Posteingang"), ("0.0/0", "Posteingang/Versicherung"), ("1/0", "Junk-E-Mail")])
        self.assertEqual(mail_pst.hole(_Datei(), "0.0/0").subject, "B")

    @unittest.skipUnless(mail_pst.verfuegbar() and os.path.exists(os.path.join(TESTDATEIEN, "example-2013.ost")),
                         "pypff oder die öffentliche Testdatei fehlt")
    def test_echte_testdatei(self):
        # öffentliche Testdatei aus java-libpst (Spike S2)
        datei = mail_pst.oeffne(os.path.join(TESTDATEIEN, "example-2013.ost"))
        try:
            funde = [(ort, mail_lesen.Mail(mail_pst.baue_eml(m))) for ort, _, m in mail_pst.mails(datei)]
        finally:
            datei.close()
        self.assertEqual(len(funde), 3)
        self.assertTrue(all(m.message_id for _, m in funde))


class _Basis(unittest.TestCase):
    def setUp(self):
        self.basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.basis, True)
        self.sammlung = os.path.join(self.basis, "Sammlung")
        os.makedirs(os.path.join(self.sammlung, "0_Posteingang"))
        self.eingang = os.path.join(self.sammlung, "0_Posteingang")
        self.quelle = os.path.join(self.basis, "mails")
        os.makedirs(self.quelle)

    def eml(self, name, daten, unterordner=""):
        ordner = os.path.join(self.quelle, unterordner)
        os.makedirs(ordner, exist_ok=True)
        with open(os.path.join(ordner, name), "wb") as f:
            f.write(daten)


class TestMailPdf(_Basis):
    def test_mail_pdf_mit_eingebetteter_mail(self):
        daten = baue(text="Grüße aus Musterstadt, 12 m³ für 30 €")
        m = mail_lesen.Mail(daten)
        stile, seite, bilder = mail_lesen.seite_html(m)
        ziel = os.path.join(self.eingang, "x.pdf")
        kid_id = PDFHandler.schreibe_mail_pdf(ziel, seite, stile, bilder, daten, {
            "title": m.titel, "KID_DokumentenDatum": "2024-03-05", "KID_Absender": "Musterversicherung",
            "KID_MailID": m.schluessel(), "KID_Richtung": "ein"})
        meta = PDFHandler.get_metadata(ziel)
        self.assertEqual((meta["title"], meta["KID_DokumentenDatum"], meta["KID_Absender"], meta["KID_ID"]),
                         ("Ihre Beitragsrechnung", "2024-03-05", "Musterversicherung", kid_id))
        self.assertEqual((meta["KID_MailID"], meta["KID_Richtung"]), ("mid:abc123@muster.example", "ein"))
        self.assertTrue(meta["KID_ScanZeitpunkt"])
        self.assertEqual(PDFHandler.hole_eml(ziel), daten)
        with fitz.open(ziel) as doc:
            text = doc[0].get_text()
        self.assertIn("Von: Musterversicherung", text)
        self.assertIn("12 m³ für 30 €", text)
        # S1: die eingebettete Mail und die Mail-Felder überstehen KIDs normalen Speicherweg
        PDFHandler.save_metadata(ziel, "Neuer Titel", "Versicherung", still=True)
        meta = PDFHandler.get_metadata(ziel)
        self.assertEqual((meta["title"], meta["KID_MailID"], meta["KID_ID"]), ("Neuer Titel", "mid:abc123@muster.example", kid_id))
        self.assertEqual(PDFHandler.hole_eml(ziel), daten)
        with self.assertRaises(FileExistsError):
            PDFHandler.schreibe_mail_pdf(ziel, seite, stile, bilder, daten, {})

    def test_anhang_pdf(self):
        ziel = os.path.join(self.eingang, "a.pdf")
        self.assertTrue(PDFHandler.schreibe_anhang_pdf(ziel, pdf_bytes(), {"KID_MailID": "mid:x", "KID_Absender": "Shop"}))
        self.assertEqual(PDFHandler.get_metadata(ziel)["KID_MailID"], "mid:x")
        with self.assertRaises(ValueError):
            PDFHandler.schreibe_anhang_pdf(os.path.join(self.eingang, "b.pdf"), b"kein pdf", {})
        self.assertFalse(os.path.exists(os.path.join(self.eingang, "b.pdf")))


class TestMailImport(_Basis):
    def journal(self, eigene=("max@example.org",)):
        j = mail_import.Journal(self.sammlung)
        j.eigene = list(eigene)
        return j

    def test_kaputtes_journal_wird_nicht_ueberschrieben(self):
        pfad = os.path.join(app_paths.data_dir(self.sammlung), mail_import.JOURNAL)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        with open(pfad, "w", encoding="utf-8") as f:
            f.write("{kaputt")
        with self.assertRaises(OSError):
            mail_import.Journal(self.sammlung)

    def test_quelle_arten(self):
        self.eml("a.eml", baue())
        box = mailbox.mbox(os.path.join(self.basis, "Inbox"))
        box.add(baue())
        box.close()
        self.assertEqual(mail_import.quelle_art(self.quelle), "ordner")
        self.assertEqual(mail_import.quelle_art(os.path.join(self.quelle, "a.eml")), "eml")
        self.assertEqual(mail_import.quelle_art(os.path.join(self.basis, "Inbox")), "mbox")
        self.assertEqual(mail_import.quelle_art(os.path.join(self.basis, "x.pst")), "pst")
        self.assertIsNone(mail_import.quelle_art(os.path.join(self.quelle, "nix.txt")))

    def test_einlesen_zaehlt_und_siebt(self):
        self.eml("1.eml", baue(mid="<1@x>"))
        self.eml("1kopie.eml", baue(mid="<1@x>"))                                  # doppelt
        self.eml("2.eml", baue(mid="<2@x>", kopf={"List-Unsubscribe": "<mailto:a@b>"}))
        self.eml("3.eml", baue(mid="<3@x>", datum=datetime.datetime(2001, 1, 1, tzinfo=datetime.timezone.utc)))
        self.eml("4.eml", baue(mid="<4@x>"), "Junk-E-Mail")
        self.eml("5.eml", baue(mid="<5@x>", von="Max <max@example.org>", an="Erika <erika@musterstadt.example>"))
        self.eml("kaputt.eml", b"")
        b = mail_import.lies_quelle(self.quelle, self.journal(), ab=datetime.date(2010, 1, 1))
        z = b.zahlen
        self.assertEqual((z["gesamt"], z["doppelt"], z["außerhalb des Zeitraums"]), (7, 1, 1))
        self.assertEqual(z["Vorfilter: Spam- oder Papierkorb-Ordner"], 1)
        self.assertEqual((z["aus"], z["unlesbar"]), (1, 1))

    def test_adresse_ganz_in_anfuehrungszeichen(self):
        # Kopf „"Name <adresse>"“ (echte .pst, 08.11.2026): getaddresses hielt das Ganze für die Adresse
        m = mail_lesen.Mail(baue(von='"Max Mustermann <max.alt@example.org>"',
                                 an='"Erika Musterfrau <erika@musterstadt.example>"'))
        self.assertEqual(m.von_adressen, ["max.alt@example.org"])
        eigene = {"max.alt@example.org"}
        self.assertEqual(mail_lesen.richtung(m, eigene), "aus")
        self.assertEqual(mail_lesen.gegenueber(m, eigene), ("Erika Musterfrau", "erika@musterstadt.example"))

    def test_gesendet_ordner(self):
        for ordner in ("Gesendete Elemente", "Oberste Ebene der Outlook-Datendatei/Gesendete Objekte", "[Gmail]/Gesendet",
                       "Thunderbird\\Sent", "Sent Items", " gesendet "):
            self.assertTrue(mail_lesen.ist_gesendet_ordner(ordner), ordner)
        for ordner in ("", "Posteingang", "Gesendet Haus", "Kunden/Gesendet alt", "Inbox"):
            self.assertFalse(mail_lesen.ist_gesendet_ordner(ordner), ordner)

    def test_domain_schluessel_nimmt_die_hauptdomain(self):
        self.assertEqual(mail_lesen.domain_schluessel("news@mail.firma.de"), "@firma.de")
        self.assertEqual(mail_lesen.domain_schluessel("NEWS@Firma.de"), "@firma.de")
        self.assertEqual(mail_lesen.domain_schluessel("a@mail.firma.co.uk"), "@firma.co.uk")
        # Unterdomain eines Mail-Anbieters: nie der ganze Anbieter, dort liegen auch Freunde
        self.assertEqual(mail_lesen.domain_schluessel("neu@mailings.web.de"), "@mailings.web.de")
        self.assertEqual(mail_lesen.domain_schluessel("erika@web.de"), "@web.de")   # ausdrücklich so gewählt

    def test_importieren_mit_anhang_und_nie_doppelt(self):
        self.eml("1.eml", baue(mid="<1@x>", anhang=("Rechnung 4711.pdf", pdf_bytes())))
        self.eml("2.eml", baue(mid="<2@x>"))                     # gleicher Tag, gleicher Betreff
        self.eml("3.eml", baue(mid="<3@x>", von="Spam <s@spam.example>"))
        j = self.journal()
        b = mail_import.lies_quelle(self.quelle, j)
        hake_an(b, "@muster-versicherung.example")                   # die Spam-Mail bleibt ohne Häkchen
        zahlen = mail_import.importiere(b, j, self.eingang)
        self.assertEqual((zahlen["mails"], zahlen["anhaenge"], zahlen["fehler"]), (2, 1, 0))
        dateien = sorted(os.listdir(self.eingang))
        self.assertEqual(dateien, ["20240305_Ihre Beitragsrechnung (2).pdf", "20240305_Ihre Beitragsrechnung.pdf",
                                   "20240305_Rechnung 4711.pdf"])
        anhang = PDFHandler.get_metadata(os.path.join(self.eingang, "20240305_Rechnung 4711.pdf"))
        self.assertEqual((anhang["KID_MailID"], anhang["KID_Absender"]), ("mid:1@x", "Musterversicherung"))
        # zweiter Lauf: nichts Neues
        j2 = mail_import.Journal(self.sammlung)
        b2 = mail_import.lies_quelle(self.quelle, j2)
        self.assertEqual(b2.zahlen["schon importiert"], 2)
        hake_an(b2, "@muster-versicherung.example")
        self.assertEqual(mail_import.importiere(b2, j2, self.eingang)["mails"], 0)
        self.assertEqual(len(os.listdir(self.eingang)), 3)

    def test_erneut_uebernehmen_nur_bewusst(self):
        # Peter 09.11.2026: von Hand gelöschte Mails bleiben ausgegraut; „Erneut übernehmen…“ gibt sie gezielt frei
        self.eml("1.eml", baue(mid="<1@x>"))
        self.eml("2.eml", baue(mid="<2@x>", betreff="Zweite"))
        j = self.journal()
        b = mail_import.lies_quelle(self.quelle, j)
        hake_an(b)
        mail_import.importiere(b, j, self.eingang)
        for name in os.listdir(self.eingang):                                     # von Hand gelöscht
            os.remove(os.path.join(self.eingang, name))
        j2 = mail_import.Journal(self.sammlung)
        b2 = mail_import.lies_quelle(self.quelle, j2)
        self.assertEqual(b2.zahlen["schon importiert"], 2)                         # bleibt ausgegraut
        hake_an(b2)
        self.assertEqual(mail_import.importiere(b2, j2, self.eingang)["mails"], 0)
        self.assertEqual(mail_import.erneut_freigeben(b2, {"mid:1@x", "mid:9@x"}), 1)
        e1 = next(e for e in b2.eintraege if e.schluessel == "mid:1@x")
        self.assertEqual((e1.ergebnis, e1.erneut), ("", True))
        self.assertIn("mid:1@x", j2.importiert)                                    # Journal erst beim Übernehmen
        e1.ergebnis = mail_import.UEBERNEHMEN
        self.assertEqual(mail_import.importiere(b2, j2, self.eingang)["mails"], 1)
        self.assertEqual(len(os.listdir(self.eingang)), 1)
        self.assertEqual((e1.ergebnis, e1.erneut), ("importiert", False))
        self.assertEqual(mail_import.lies_quelle(self.quelle, mail_import.Journal(self.sammlung)).zahlen["schon importiert"], 2)

    def test_direkt_in_einen_ordner_ohne_sammelablage(self):
        # KONZEPT_MAIL_AUF_ABRUF F6: ohne KI, Titel = Betreff, der Anhang trägt seinen Dateinamen als Titel, und eine
        # einzelne Mail bekommt kein KID_EINZELN (im Posteingang schickte es die Vollautomatik in die Sammelablage, E17)
        self.eml("1.eml", baue(mid="<1@x>", anhang=("Rechnung_4711.pdf", pdf_bytes())))
        self.eml("2.eml", baue(mid="<2@x>", von="Erika Musterfrau <erika@musterstadt.example>", betreff="Hallo"))
        j = self.journal()
        b = mail_import.lies_quelle(self.quelle, j)
        for e in b.eintraege:
            e.ergebnis = mail_import.UEBERNEHMEN
        self.assertEqual(mail_import.einzelne_mails(b), {"mid:2@x"})
        ordner = os.path.join(self.sammlung, "Versicherung")
        os.makedirs(ordner)
        zahlen = mail_import.importiere(b, j, ordner, direkt=True)
        self.assertEqual((zahlen["mails"], zahlen["anhaenge"], zahlen["fehler"]), (2, 1, 0))
        self.assertEqual(os.listdir(self.eingang), [])
        self.assertEqual(sorted(os.listdir(ordner)), ["20240305_Hallo.pdf", "20240305_Ihre Beitragsrechnung.pdf",
                                                      "20240305_Rechnung_4711.pdf"])
        mail = PDFHandler.get_metadata(os.path.join(ordner, "20240305_Ihre Beitragsrechnung.pdf"))
        self.assertEqual((mail["title"], mail["KID_Absender"], mail["KID_DokumentenDatum"][:10]),
                         ("Ihre Beitragsrechnung", "Musterversicherung", "2024-03-05"))
        self.assertFalse(PDFHandler.get_metadata(os.path.join(ordner, "20240305_Hallo.pdf")).get("KID_Einzeln"))
        anhang = PDFHandler.get_metadata(os.path.join(ordner, "20240305_Rechnung_4711.pdf"))
        self.assertEqual((anhang["title"], anhang["KID_MailID"]), ("Rechnung 4711", "mid:1@x"))

    def test_ohne_anhaenge_nur_das_mail_pdf(self):
        self.eml("1.eml", baue(mid="<1@x>", anhang=("Rechnung.pdf", pdf_bytes())))
        j = self.journal()
        b = mail_import.lies_quelle(self.quelle, j)
        b.eintraege[0].ergebnis = mail_import.UEBERNEHMEN
        zahlen = mail_import.importiere(b, j, self.eingang, anhaenge=False)
        self.assertEqual((zahlen["mails"], zahlen["anhaenge"]), (1, 0))
        self.assertEqual(os.listdir(self.eingang), ["20240305_Ihre Beitragsrechnung.pdf"])
        self.assertEqual(j.importiert["mid:1@x"]["dateien"], ["20240305_Ihre Beitragsrechnung.pdf"])

    def test_mail_die_nicht_auf_seiten_passt_kommt_als_text(self):
        # 05.11.2026 (FALLSTRICKE #103): passt ein Block auf keine Seite, verlangt die Story endlos neue Seiten -
        # der ganze Import stand, und „Abbrechen“ wirkt erst zwischen zwei Mails
        faelle = {"Polster": "<div style='padding:3000px'>Wichtiger Inhalt</div>",
                  "Schrift": "<p style='font-size:2000px'>Wichtiger Inhalt</p>"}
        for i, (name, inhalt) in enumerate(faelle.items()):
            self.eml(f"{i}.eml", baue(mid=f"<{i}@x>", betreff=name, html=f"<html><body>{inhalt}</body></html>"))
        j = self.journal()
        b = mail_import.lies_quelle(self.quelle, j)
        hake_an(b, "@muster-versicherung.example")
        zahlen = mail_import.importiere(b, j, self.eingang)
        self.assertEqual((zahlen["mails"], zahlen["fehler"], zahlen["vereinfacht"]), (2, 0, 2))
        for datei in os.listdir(self.eingang):
            with fitz.open(os.path.join(self.eingang, datei)) as doc:
                self.assertLess(doc.page_count, 5)
                text = "".join(s.get_text() for s in doc)
                self.assertIn("Wichtiger Inhalt", text)
                self.assertIn("Vereinfachte Darstellung", text)
                self.assertEqual(doc.embfile_names(), ["Original-Mail"])

    def test_lange_mail_in_layout_tabelle_behaelt_datentabelle(self):
        # FALLSTRICKE #103: nicht gleich reiner Text - die äußere Tabelle kommt weg, die Datentabelle innen bleibt
        absaetze = "".join(f"<p>Absatz {n} mit etwas Text darin.</p>" for n in range(80))
        daten = "<table><tr><td>Betrag</td><td>49,90</td></tr></table>"
        link = '<a href="https://shop.example/bestellung">Zur Bestellung</a>'
        self.eml("1.eml", baue(mid="<1@x>", betreff="Bestellung", html=(
            f"<html><body><table width='600'><tr><td>{absaetze}{link}{daten}</td></tr></table></body></html>")))
        j = self.journal()
        b = mail_import.lies_quelle(self.quelle, j)
        hake_an(b, "@muster-versicherung.example")
        zahlen = mail_import.importiere(b, j, self.eingang)
        self.assertEqual((zahlen["mails"], zahlen["fehler"], zahlen["vereinfacht"], zahlen["layout_aufgeloest"]),
                         (1, 0, 0, 1))
        with fitz.open(os.path.join(self.eingang, os.listdir(self.eingang)[0])) as doc:
            self.assertLess(doc.page_count, 10)
            text = "".join(s.get_text() for s in doc)
            self.assertIn("Absatz 79", text)
            self.assertIn("Vereinfachte Darstellung", text)
            self.assertIn("Zur Bestellung", text)
            # Die Datentabelle bleibt eine Tabelle: Betrag und Wert stehen auf derselben Höhe
            seite = next(s for s in doc if "49,90" in s.get_text())
            self.assertAlmostEqual(seite.search_for("Betrag")[0].y0, seite.search_for("49,90")[0].y0, delta=1)
            self.assertEqual(doc.embfile_names(), ["Original-Mail"])

    def test_layout_tabelle_mit_collapse_verliert_keinen_text(self):
        # FALLSTRICKE #108: Mit dieser alltäglichen Regel endet die Story nach 2 Seiten ohne Fehler, aber ohne den Text
        absaetze = "".join(f"<p>Absatz {n} mit etwas Text darin.</p>" for n in range(80))
        self.eml("1.eml", baue(mid="<1@x>", betreff="Newsletter", html=(
            "<html><head><style>table,td{border-collapse:collapse}</style></head><body>"
            f"<table width='100%' bgcolor='#111111'><tr><td><table width='600'><tr><td style='color:#ffffff'>{absaetze}"
            "</td></tr></table></td></tr></table></body></html>")))
        j = self.journal()
        b = mail_import.lies_quelle(self.quelle, j)
        hake_an(b, "@muster-versicherung.example")
        zahlen = mail_import.importiere(b, j, self.eingang)
        self.assertEqual((zahlen["mails"], zahlen["fehler"], zahlen["layout_aufgeloest"]), (1, 0, 1))
        with fitz.open(os.path.join(self.eingang, os.listdir(self.eingang)[0])) as doc:
            text = "".join(s.get_text() for s in doc)
            self.assertIn("Absatz 0 ", text)
            self.assertIn("Absatz 79", text)
            self.assertIn("Vereinfachte Darstellung", text)

    def test_kurze_mail_bleibt_in_voller_darstellung(self):
        # Die Prüfung darf gewöhnliche Mails nicht vereinfachen, auch wenn ein kleiner Vorspann versteckt ist
        self.eml("1.eml", baue(mid="<1@x>", betreff="Rechnung", html=(
            "<html><head><style>table,td{border-collapse:collapse}</style></head><body><div style='display:none'>Vorspann"
            "</div><table><tr><td>Betrag</td><td>49,90</td></tr></table><p>Vielen Dank für Ihren Einkauf.</p></body></html>")))
        j = self.journal()
        b = mail_import.lies_quelle(self.quelle, j)
        hake_an(b, "@muster-versicherung.example")
        zahlen = mail_import.importiere(b, j, self.eingang)
        self.assertEqual((zahlen["mails"], zahlen["layout_aufgeloest"], zahlen["vereinfacht"]), (1, 0, 0))

    def test_versteckter_text_vereinfacht_keine_mail(self):
        # Füllzeichen im Vorspann und versteckte Blöcke gehören nicht auf die Seiten: Echter Lauf 06.11.2026, mit einem
        # Vergleich nach Wörtern fielen 57 von 394 Mails auf reinen Text zurück (FALLSTRICKE #108)
        fuell = "&#847;&zwnj;&nbsp; " * 300
        versteckt = "Nur für Mobilgeräte gedacht. " * 40
        self.eml("1.eml", baue(mid="<1@x>", betreff="Angebot", html=(
            f"<html><body><div style='display:none;max-height:0'>{fuell}</div>"
            f"<div style='display: none'><div><p>{versteckt}</div></div>"
            "<table><tr><td>Betrag</td><td>49,90</td></tr></table>"
            "<p>Vielen Dank für Ihren Einkauf bei uns, wir melden uns bald wieder.</p></body></html>")))
        j = self.journal()
        b = mail_import.lies_quelle(self.quelle, j)
        hake_an(b, "@muster-versicherung.example")
        zahlen = mail_import.importiere(b, j, self.eingang)
        self.assertEqual((zahlen["mails"], zahlen["layout_aufgeloest"], zahlen["vereinfacht"]), (1, 0, 0))

    def test_nullzeichen_im_kopf_schneidet_die_mail_nicht_ab(self):
        # FALLSTRICKE #108: Die Story liest das HTML nur bis zum ersten Nullzeichen, kam im echten Lauf 1 von 394 vor
        from pdf_handler import PDFHandler
        daten = baue(mid="<1@x>", betreff="Vorher", text="Wichtiger Inhalt der Mail").replace(b"Vorher", b"Vor\x00her")
        self.assertIn(b"\x00", daten)
        mail = mail_lesen.Mail(daten)
        for stufe in (mail_lesen.VOLL, mail_lesen.NUR_TEXT):
            stile, seite, bilder = mail_lesen.seite_html(mail, "ein", stufe=stufe)
            self.assertNotIn("\x00", seite)
            ziel = os.path.join(self.basis, f"null{stufe}.pdf")
            PDFHandler.schreibe_mail_pdf(ziel, seite, stile, bilder, daten, {"title": "x"})
            with fitz.open(ziel) as doc:
                self.assertIn("Wichtiger Inhalt", "".join(s.get_text() for s in doc))

    def test_sichtbare_zeichen(self):
        f = mail_lesen.sichtbare_zeichen
        self.assertEqual(f("<p>Ab 12!</p>"), 4)
        self.assertEqual(f("<head><title>Titel</title><style>p{color:red}</style></head><p>Ab</p>"), 2)
        self.assertEqual(f("&#847;&zwnj;&nbsp; &nbsp;"), 0)
        self.assertEqual(f("<div style='display:none'><p>weg<div>auch weg</div></div><p>Ab</p>"), 2)
        self.assertEqual(f("<td style='mso-hide: all'>weg</td><td style='max-height:0;overflow:hidden'>weg</td>"), 0)
        # max-height:10px ist nicht versteckt, ein leerer Zeilenumbruch ändert nichts
        self.assertEqual(f("<div style='max-height:10px'>Ab</div><br><img src='x'>Cd"), 4)
        # Offene Absätze und Tags im Versteckten verschieben nichts
        self.assertEqual(f("<div style='display:none'><p>weg<br></div><p>Ab<p>Cd"), 4)

    def test_mbox_eingang(self):
        pfad = os.path.join(self.basis, "Inbox")
        box = mailbox.mbox(pfad)
        box.add(baue(mid="<m1@x>"))
        box.add(baue(mid="<m2@x>", betreff="Zweite"))
        box.close()
        j = self.journal()
        b = mail_import.lies_quelle(pfad, j)
        self.assertEqual(b.zahlen["gesamt"], 2)
        self.assertEqual(mail_import.lade_mail(pfad, b.eintraege[1].ort).titel, "Zweite")

    def _mbox(self, *mails):
        pfad = os.path.join(self.basis, "Inbox")
        with open(pfad, "wb") as f:
            for nr, kopf, text in mails:
                f.write(kopf + f"From: A <a@x.example>\nSubject: M{nr}\nMessage-ID: <{nr}@x>\n\n".encode() + text + b"\n\n")
        return pfad

    def test_from_im_text_zerlegt_die_mail_nicht(self):
        # FALLSTRICKE #105: mailbox.mbox nahm jede Zeile mit „From “ als neue Mail
        pfad = self._mbox(
            (1, b"From - Fri Mar 01 10:00:00 2024\n", b"Zeile eins\n\nFrom Hamburg nach Berlin\nZeile zwei"),
            (2, b"From a@x.example Fri Mar  1 10:00:00 +0100 2024\n", b"Text zwei\n\n>From maskiert"),
            (3, b"From ???@??? Fri, 1 Mar 2024 10:00:00\n", b"Text drei"))
        zahlen = collections.Counter()
        mails = list(mail_lesen.mbox_mails(pfad, zahlen))
        self.assertEqual(len(mails), 3)
        self.assertIn(b"From Hamburg nach Berlin\nZeile zwei", mails[0][1])
        self.assertIn(b">From maskiert", mails[1][1])
        self.assertEqual(zahlen[mail_lesen.ZAHL_FROM_IM_TEXT], 1)
        # Der Eingang über die Byte-Position liefert dieselbe Mail
        for ort, daten in mails:
            self.assertEqual(mail_lesen.mbox_mail(pfad, ort), daten)
        self.assertEqual(mails[0][1].splitlines()[0], b"From: A <a@x.example>")

    def test_gelesene_gezaehlte_und_uebergangene_thunderbird_mails(self):
        def status(s, s2="00000000"):
            return f"From - Fri Mar 01 10:00:00 2024\nX-Mozilla-Status: {s}\nX-Mozilla-Status2: {s2}\n".encode()
        pfad = self._mbox((1, status("0001"), b"Normal"), (2, status("0009"), b"Geloescht"),
                          (3, status("0081", "00200000"), b"Auf dem Server geloescht"), (4, status("0401"), b"Teilweise"))
        b = mail_import.lies_quelle(pfad, self.journal())
        self.assertEqual(sorted(e.betreff for e in b.eintraege), ["M1", "M4"])   # die gekürzte bleibt und wird gemeldet
        self.assertEqual(b.zahlen["gesamt"], 2)
        self.assertEqual(b.zahlen[mail_lesen.GELOESCHT], 2)
        self.assertEqual(b.zahlen[mail_lesen.TEILWEISE], 1)
        # Text im Mailtext zählt nicht als Zustand
        self.assertEqual(mail_lesen.mozilla_zustand(b"Subject: x\n\nX-Mozilla-Status: 0009\n"), "")

    def test_dateiname(self):
        self.assertEqual(mail_import.dateiname(datetime.datetime(2024, 3, 5), 'Re: "Angebot"/Teil 2?'),
                         "20240305_Re  Angebot Teil 2.pdf".replace("  ", " "))
        self.assertEqual(mail_import.dateiname(None, ""), "00000000_ohne Betreff.pdf")

    def test_eigene_adressen_aus_gesendeten_mails(self):
        # Peter 08.11.2026: „Ich möchte nicht jedes Mal alle möglichen eigenen Adressen eingeben“
        alt = "Max Mustermann <max.alt@example.org>"
        for i in range(3):
            self.eml(f"g{i}.eml", baue(mid=f"<g{i}@x>", von=alt, an="Erika Musterfrau <erika@musterstadt.example>"),
                     "Gesendete Elemente")
        # Peter 08.11.2026: dieselbe Adresse stand zweimal im Vorschlag, einmal als „Name <adresse>“
        self.eml("q.eml", baue(mid="<q@x>", von='"Max Mustermann <max.alt@example.org>"'), "Gesendete Elemente")
        self.eml("f.eml", baue(mid="<f@x>", von="Shop <info@shop.example>"), "Gesendete Elemente")   # nur einmal dort
        self.eml("e.eml", baue(mid="<e@x>"))                                                       # eingegangen
        j = self.journal()
        b = mail_import.lies_quelle(self.quelle, j)
        self.assertEqual(mail_import.eigene_vorschlaege(b, set(j.eigene)), [("max.alt@example.org", 4)])
        self.assertEqual(mail_import.eigene_vorschlaege(b, set(j.eigene), ["MAX.ALT@example.org"]), [])   # abgelehnt
        self.assertEqual(mail_import.eigene_vorschlaege(b, {"@example.org"}), [])         # Domain-Eintrag deckt sie
        g = next(e for e in b.eintraege if e.schluessel == "mid:g0@x")
        self.assertEqual((g.richtung, g.adresse, b.zahlen["aus"]), ("ein", "max.alt@example.org", 0))
        mail_import.setze_eigene(b, set(j.eigene) | {"max.alt@example.org"})
        self.assertEqual((g.richtung, g.name, g.adresse), ("aus", "Erika Musterfrau", "erika@musterstadt.example"))
        self.assertEqual((b.zahlen["aus"], b.zahlen["ein"]), (4, 2))

    def test_journal_behaelt_alte_eintraege(self):
        # Schritt 4 (KONZEPT_MAIL_AUF_ABRUF): KI-Einstufungen und Entscheidungen von Hand werden nicht mehr gelesen,
        # aber auch nicht gelöscht - im Daten-Ordner bleibt alles liegen
        j = self.journal()
        j.speichere()
        with open(j.pfad, encoding="utf-8") as f:
            alt = json.load(f)
        alt.update(ki_stand=2, ki={"mid:1@x": "beleg"}, hand={"mid:2@x": "verwerfen"})
        with open(j.pfad, "w", encoding="utf-8") as f:
            json.dump(alt, f)
        j2 = mail_import.Journal(self.sammlung)
        j2.importiert["mid:3@x"] = {"dateien": ["a.pdf"], "am": "2026-11-08"}
        j2.speichere()
        with open(j2.pfad, encoding="utf-8") as f:
            neu = json.load(f)
        self.assertEqual((neu["ki_stand"], neu["ki"], neu["hand"]), (2, {"mid:1@x": "beleg"}, {"mid:2@x": "verwerfen"}))
        self.assertEqual(list(neu["importiert"]), ["mid:3@x"])
        self.assertEqual(neu["eigene"], ["max@example.org"])

    def test_journal_ohne_inhalte(self):
        # Datenschutz: das Journal kennt Schlüssel und Dateinamen, aber keine Texte
        self.eml("1.eml", baue(mid="<1@x>", text="Geheimer Inhalt"))
        j = self.journal()
        b = mail_import.lies_quelle(self.quelle, j)
        hake_an(b, "@muster-versicherung.example")
        mail_import.importiere(b, j, self.eingang)
        with open(j.pfad, encoding="utf-8") as f:
            self.assertNotIn("Geheimer", f.read())


class TestSuche(_Basis):
    """Mail-Import auf Abruf (KONZEPT_MAIL_AUF_ABRUF): suchen in den eingelesenen Mails, ohne die Quelle neu zu lesen."""

    def setUp(self):
        super().setUp()
        tz = datetime.timezone.utc
        vivafone = "Vivafone Kundenservice <rechnung@vivafone.example>"
        self.eml("1.eml", baue(mid="<1@x>", von=vivafone, betreff="Ihre Rechnung Januar", text="Ihre Rechnung steht bereit.",
                               datum=datetime.datetime(2024, 1, 3, tzinfo=tz), anhang=("Rechnung_01.pdf", pdf_bytes())))
        self.eml("2.eml", baue(mid="<2@x>", von=vivafone, betreff="Angebot", text="Jetzt upgraden.",
                               datum=datetime.datetime(2023, 5, 1, tzinfo=tz)))
        self.eml("3.eml", baue(mid="<3@x>", von="Kabel Muster <info@kabel.example>", betreff="Vertrag",
                               text="Ihr Vivafon Vertrag wurde verlängert.", datum=datetime.datetime(2024, 6, 1, tzinfo=tz)))
        self.eml("4.eml", baue(mid="<4@x>", von="Telenetz <info@telenetz.example>", betreff="Rechnung",
                               datum=datetime.datetime(2024, 2, 1, tzinfo=tz)))
        self.eml("5.eml", baue(mid="<5@x>", von="Max <max@example.org>", an=vivafone, betreff="Kuendigung Festnetz",
                               text="Hiermit kündige ich.", datum=datetime.datetime(2024, 3, 1, tzinfo=tz)))
        self.eml("6.eml", baue(mid="<6@x>", von=vivafone, betreff="Ohne Datum", datum=None))
        self.eml("7.eml", baue(mid="<7@x>", von=vivafone, betreff="Gewinnspiel", datum=datetime.datetime(2024, 4, 1, tzinfo=tz)),
                 "Junk-E-Mail")
        self.journal = mail_import.Journal(self.sammlung)
        self.journal.eigene = ["max@example.org"]
        self.bestand = mail_import.lies_quelle(self.quelle, self.journal)

    def nummern(self, ergebnis):
        return [e.schluessel[4:-2] for e, _ in ergebnis.treffer]

    def test_peters_beispiel_mit_jahr_und_tippfehler(self):
        """„Vivafone 2024“: Jahr als Zeitraum, „Vivafon“ über die Unschärfe, ohne Datum bleibt drin, Spam nicht."""
        r = mail_import.suche(self.bestand, "Vivafone 2024")
        self.assertEqual(r.jahre, (2024, 2024))
        self.assertEqual(self.nummern(r), ["3", "5", "1", "6"])          # neueste zuerst, ohne Datum am Ende
        self.assertEqual({e.schluessel[4:-2]: unscharf for e, unscharf in r.treffer},
                         {"3": True, "5": False, "1": False, "6": False})
        self.assertEqual(r.varianten, {"vivafon": 1})

    def test_anfuehrungszeichen_schalten_die_unschaerfe_ab(self):
        self.assertEqual(self.nummern(mail_import.suche(self.bestand, '"Vivafone" 2024')), ["5", "1", "6"])

    def test_jahr_ist_text_wenn_der_zeitraum_gesetzt_ist(self):
        r = mail_import.suche(self.bestand, "2024", ab=datetime.date(2020, 1, 1))
        self.assertIsNone(r.jahre)
        self.assertEqual(self.nummern(r), [])            # „2024“ steht in keinem Text

    def test_umlaute_richtung_anhang_und_absender(self):
        # wörtlich, nicht über die Unschärfe: „Kündigung“ = „Kuendigung“
        self.assertEqual([(e.schluessel, u) for e, u in mail_import.suche(self.bestand, "Kündigung").treffer],
                         [("mid:5@x", False)])
        self.assertEqual(self.nummern(mail_import.suche(self.bestand, "vivafone", richtung="aus")), ["5"])
        self.assertEqual(self.nummern(mail_import.suche(self.bestand, nur_anhang=True)), ["1"])
        self.assertEqual(self.nummern(mail_import.suche(self.bestand, von_an="telenetz")), ["4"])

    def test_spam_nur_auf_wunsch(self):
        self.assertNotIn("7", self.nummern(mail_import.suche(self.bestand, "gewinnspiel")))
        self.assertEqual(self.nummern(mail_import.suche(self.bestand, "gewinnspiel", auch_vorfilter=True)), ["7"])

    def test_anhangsname_wird_durchsucht(self):
        self.assertEqual(self.nummern(mail_import.suche(self.bestand, "rechnung_01")), ["1"])

    def test_schon_importierte_zaehlen_mit(self):
        self.journal.importiert["mid:1@x"] = {"dateien": ["a.pdf"], "am": "2026-11-08"}
        r = mail_import.suche(mail_import.lies_quelle(self.quelle, self.journal), "januar")
        self.assertEqual((self.nummern(r), r.schon_drin), (["1"], 1))

    def test_suchtext_ist_begrenzt(self):
        self.eml("lang.eml", baue(mid="<8@x>", text="wort " * 10000))
        e = next(e for e in mail_import.lies_quelle(self.quelle, self.journal).eintraege if e.schluessel == "mid:8@x")
        self.assertLess(len(e.suchtext), mail_import.SUCHTEXT_ZEICHEN + 500)


class TestOrdnerMitMailDateien(_Basis):
    """KONZEPT_MAIL_AUF_ABRUF F7: Ein Ordner mit vielen .pst/mbox/.eml (Peters Archiv: 25 .pst, 12,6 GB) wird in einem
    Durchgang zu einem Bestand, direkt gelesen. Vor dem Übernehmen prüft KID, dass sich keine Datei verändert hat."""

    def journal(self):
        j = mail_import.Journal(self.sammlung)
        j.eigene = ["max@example.org"]
        return j

    def mbox(self, relativ, *mails):
        pfad = os.path.join(self.quelle, relativ)
        os.makedirs(os.path.dirname(pfad), exist_ok=True)
        box = mailbox.mbox(pfad)
        for m in mails:
            box.add(m)
        box.close()
        return pfad

    def test_alle_dateien_ein_bestand(self):
        self.eml("a.eml", baue(mid="<e1@x>"), unterordner="Export")
        self.mbox(os.path.join("Profil", "Inbox"), baue(mid="<m1@x>"), baue(mid="<e1@x>"))   # e1 doppelt, andere Datei
        self.mbox(os.path.join("Profil", "Inbox.sbd", "Junk"), baue(mid="<j1@x>"))
        with open(os.path.join(self.quelle, "Profil", "Inbox.msf"), "wb") as f:
            f.write(b"// <!-- <mdb:mork:z")
        with open(os.path.join(self.quelle, "notiz.txt"), "w", encoding="utf-8") as f:
            f.write("keine Mail")
        self.assertEqual(mail_import.quelle_art(self.quelle), "ordner")
        j = self.journal()
        b = mail_import.lies_quelle(self.quelle, j)
        self.assertEqual((b.zahlen["gesamt"], b.zahlen["doppelt"], b.fehlende_dateien), (4, 1, []))
        nach_mid = {e.schluessel: e for e in b.eintraege}
        self.assertEqual(set(nach_mid), {"mid:e1@x", "mid:m1@x", "mid:j1@x"})
        self.assertEqual(nach_mid["mid:j1@x"].vorfilter, "Spam- oder Papierkorb-Ordner")   # Thunderbird-Unterordner
        self.assertEqual(nach_mid["mid:m1@x"].vorfilter, "")
        for e in b.eintraege:
            e.ergebnis = mail_import.UEBERNEHMEN
        zahlen = mail_import.importiere(b, j, self.eingang)                  # liest jede Mail aus ihrer Datei
        self.assertEqual((zahlen["mails"], zahlen["fehler"]), (3, 0))
        self.assertEqual(set(j.importiert), set(nach_mid))

    @unittest.skipUnless(mail_pst.verfuegbar() and os.path.exists(os.path.join(TESTDATEIEN, "example-2013.ost")),
                         "pypff oder Testdatei fehlt")
    def test_pst_im_ordner_und_kaputte_datei_fehlt_allein(self):
        shutil.copy(os.path.join(TESTDATEIEN, "example-2013.ost"), os.path.join(self.quelle, "2013.ost"))
        with open(os.path.join(self.quelle, "2018.pst"), "wb") as f:
            f.write(b"keine pst")                  # wie eine kaputte oder von Outlook gesperrte Datei
        self.eml("x.eml", baue(mid="<x1@x>"))
        b = mail_import.lies_quelle(self.quelle, self.journal())
        self.assertEqual(b.fehlende_dateien, ["2018.pst"])
        self.assertEqual(b.zahlen[mail_import.DATEI_NICHT_LESBAR], 1)
        self.assertEqual(len(b.eintraege), 4)                                # 3 aus der .ost, 1 .eml
        e = next(e for e in b.eintraege if e.ort[0] == "2013.ost")
        with mail_import.geoeffnet(self.quelle):
            self.assertTrue(mail_import.lade_mail(self.quelle, e.ort).message_id)

    def test_veraenderte_datei_verhindert_uebernehmen(self):
        pfad = self.mbox("Inbox", baue(mid="<m1@x>"), baue(mid="<m2@x>"))
        for i, quelle in enumerate((pfad, self.quelle)):                    # einzelne mbox und Ordner
            j = self.journal()
            b = mail_import.lies_quelle(quelle, j)
            for e in b.eintraege:
                e.ergebnis = mail_import.UEBERNEHMEN
            self.assertEqual(mail_import.veraenderte_dateien(b), [])
            box = mailbox.mbox(pfad)                                         # Thunderbird schreibt weiter
            box.add(baue(mid=f"<neu{i}@x>"))
            box.close()
            with self.assertRaises(mail_import.QuelleVeraendert) as fehler:
                mail_import.importiere(b, j, self.eingang)
            self.assertEqual(fehler.exception.dateien, ["Inbox"])
            self.assertIn("neu einlesen", str(fehler.exception))
            self.assertEqual((os.listdir(self.eingang), j.importiert), ([], {}))

    def test_ordner_ohne_mails_sagt_warum(self):
        # T20.4: sonst stand nur „0 Mails gelesen“ da
        with open(os.path.join(self.quelle, "notiz.txt"), "w", encoding="utf-8") as f:
            f.write("x")
        self.assertIn("keine Mail-Dateien", mail_import.ordner_hinweis(self.quelle))
        self.mbox("Inbox", baue())
        self.assertIn("keine lesbaren Mails", mail_import.ordner_hinweis(self.quelle))


if __name__ == "__main__":
    unittest.main()


class TestVollautomatikMitMailkopf(unittest.TestCase):
    def test_mailkopf_geht_vor(self):
        import auto_pilot
        ki = {"title": "Rechnung", "datum": "2023-01-01", "absender": "Max Mustermann", "ordnername": "", "tags": []}
        meta = {"KID_MailID": "mid:1@x", "KID_Richtung": "aus", "KID_DokumentenDatum": "2024-03-05",
                "KID_Absender": "Musterversicherung"}
        neu = auto_pilot.mit_mailkopf(ki, meta)
        self.assertEqual((neu["datum"], neu["absender"], neu["title"]), ("2024-03-05", "Musterversicherung", "Rechnung"))
        self.assertIs(auto_pilot.mit_mailkopf(ki, {"KID_DokumentenDatum": "2024-03-05"}), ki)   # kein Mail-PDF
        self.assertIsNone(auto_pilot.mit_mailkopf(None, meta))

    def test_anhang_wie_ein_scan(self):
        # Erika leitet eine Rechnung der Musterbank weiter: der Anhang gehört zur Musterbank (E2: wie ein Scan);
        # das Gegenüber der Mail gilt nur, wenn auf dem Dokument kein Absender zu lesen ist
        import auto_pilot
        anhang = {"KID_MailID": "mid:1@x", "KID_Absender": "Erika Musterfrau"}       # ohne KID_Richtung = Anhang
        ki = {"datum": "2023-01-01", "absender": "Musterbank"}
        self.assertEqual(auto_pilot.mit_mailkopf(ki, anhang)["absender"], "Musterbank")
        self.assertEqual(auto_pilot.mit_mailkopf(dict(ki, absender=""), anhang)["absender"], "Erika Musterfrau")
        mail = dict(anhang, KID_Richtung="ein")                                      # die Mail selbst bleibt beim Kopf
        self.assertEqual(auto_pilot.mit_mailkopf(ki, mail)["absender"], "Erika Musterfrau")

    def test_kurzer_name_aus_dem_mailkopf_bekommt_einen_ordner(self):
        # Echter Lauf 05.11.2026: Firmen mit drei Buchstaben landeten in 0_Unsicher. Im Mailkopf steht der Name fest,
        # dort reichen sogar zwei Buchstaben
        import auto_pilot
        for name in ("XYZ", "XY"):
            ki = auto_pilot.mit_mailkopf({"title": "Paket", "tags": ["Versand"], "datum": "2024-03-05",
                                          "absender": "Falsch"},
                                         {"KID_MailID": "mid:1@x", "KID_Richtung": "ein", "KID_Absender": name,
                                          "KID_DokumentenDatum": "2024-03-05"})
            e = auto_pilot.baue_entscheidung("dok.pdf", ki, ["Musterbank"])
            self.assertEqual((e["sicher"], e["zielordner"], e["probleme"]), (True, name, []))
            self.assertEqual(auto_pilot.baue_entscheidung("dok.pdf", ki, ["Musterbank", name])["zielordner"], name)
        # Auch aus dem Mailkopf: ein einzelner Buchstabe ist kein Ordner
        ki_kurz = dict(ki, absender="X")
        self.assertFalse(auto_pilot.baue_entscheidung("dok.pdf", ki_kurz, ["Musterbank"])["sicher"])

    def test_drei_buchstaben_reichen_auch_beim_scan(self):
        # Peter 05.11.2026: kurze Firmennamen sind häufig. Zwei Buchstaben bleiben beim Scan ein Lesefehler-Verdacht
        import auto_pilot
        scan = {"title": "Paket", "tags": ["Versand"], "datum": "2024-03-05", "absender": "Xyz"}
        e = auto_pilot.baue_entscheidung("dok.pdf", scan, ["Musterbank"])
        self.assertEqual((e["sicher"], e["zielordner"], e["ordner_neu"]), (True, "Xyz", True))
        # Der vorhandene gleichnamige Ordner gewinnt, auch unter einer Buchstabengruppe und in anderer Schreibweise
        e = auto_pilot.baue_entscheidung("dok.pdf", scan, ["Musterbank", "U - Z\\XYZ"])
        self.assertEqual((e["sicher"], e["zielordner"], e["ordner_neu"]), (True, "U - Z\\XYZ", False))
        # Der Vergleich bleibt streng: 'Eis' ist nicht 'Eisenwaren'
        e = auto_pilot.baue_entscheidung("dok.pdf", dict(scan, absender="Eis"), ["Eisenwaren Beispiel"])
        self.assertEqual(e["zielordner"], "Eis")
        self.assertFalse(auto_pilot.baue_entscheidung("dok.pdf", dict(scan, absender="Xy"), ["Musterbank"])["sicher"])

    def test_nur_adresse_im_mailkopf_gibt_die_domain_als_ordner(self):
        import auto_pilot
        self.assertEqual(auto_pilot.ordnername_aus_adresse("info@mail.firma.de"), "firma.de")
        self.assertEqual(auto_pilot.ordnername_aus_adresse("A@Firma.co.uk"), "firma.co.uk")
        # Bei Mail-Anbietern sagt die Domain nichts über das Gegenüber
        self.assertEqual(auto_pilot.ordnername_aus_adresse("max@web.de"), "max@web.de")
        self.assertEqual(auto_pilot.ordnername_aus_adresse("max@mailings.web.de"), "max@mailings.web.de")
        # Alles andere bleibt, auch mit @ im Namen
        self.assertEqual(auto_pilot.ordnername_aus_adresse("Muster GmbH"), "Muster GmbH")
        self.assertEqual(auto_pilot.ordnername_aus_adresse("Firma @ Musterstadt"), "Firma @ Musterstadt")
        ki = auto_pilot.mit_mailkopf({"title": "Paket", "tags": ["Versand"], "datum": "2024-03-05", "absender": "Falsch"},
                                     {"KID_MailID": "mid:1@x", "KID_Richtung": "ein", "KID_Absender": "info@firma.de",
                                      "KID_DokumentenDatum": "2024-03-05"})
        e = auto_pilot.baue_entscheidung("dok.pdf", ki, ["Musterbank"])
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"].casefold(), "firma.de")

    def _ablage_nur_adresse(self, adresse, ordner):
        import auto_pilot
        ki = auto_pilot.mit_mailkopf({"title": "Paket", "tags": ["Versand"], "datum": "2024-03-05", "absender": "Falsch"},
                                     {"KID_MailID": "mid:1@x", "KID_Richtung": "ein", "KID_Absender": adresse,
                                      "KID_DokumentenDatum": "2024-03-05"})
        return auto_pilot.baue_entscheidung("dok.pdf", ki, ordner)

    def test_vorderer_teil_der_adresse_macht_keinen_ordner_aehnlich(self):
        # FALLSTRICKE #107: „service@“ und „online@“ sagen nichts über das Gegenüber
        e = self._ablage_nur_adresse("service@beispielware.info", ["MUSTERMARKT Service"])
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], "Beispielware.info")
        e = self._ablage_nur_adresse("online@beispielware.de", ["DISKONT ONLINESHOP"])
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], "Beispielware.de")
        # Die Endung auch nicht
        e = self._ablage_nur_adresse("info@beispielware.online", ["DISKONT ONLINESHOP"])
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], "Beispielware.online")

    def test_domain_findet_den_vorhandenen_ordner(self):
        e = self._ablage_nur_adresse("online@mustermarkt.de", ["DISKONT ONLINESHOP", "MUSTERMARKT Service"])
        self.assertTrue(e["sicher"], e["probleme"])
        self.assertEqual(e["zielordner"], "MUSTERMARKT Service")
        # Ein schon angelegter Domain-Ordner wird wiedergefunden
        e = self._ablage_nur_adresse("kontakt@mustermarkt.de", ["Mustermarkt.de"])
        self.assertEqual(e["zielordner"], "Mustermarkt.de")

    def test_vergleichsname(self):
        import auto_pilot
        self.assertEqual(auto_pilot._vergleichsname("online@mail.firma.co.uk"), "firma")
        # Bei Mail-Anbietern ist der vordere Teil oft der Name der Person, hier bleibt alles
        self.assertEqual(auto_pilot._vergleichsname("erika.musterfrau@web.de"), "erika.musterfrau@web.de")
        self.assertEqual(auto_pilot._vergleichsname("Muster GmbH"), "Muster GmbH")
        self.assertEqual(auto_pilot._vergleichsname(""), "")

    def test_anhang_mit_unbrauchbarem_absender_nimmt_das_gegenueber(self):
        # Die KI las auf dem Anhang nichts Brauchbares: dann zählt das Gegenüber der Mail
        import auto_pilot
        anhang = {"KID_MailID": "mid:1@x", "KID_Absender": "Musterversand GmbH", "KID_DokumentenDatum": "2024-03-05"}
        for gelesen in ("", "XY", "Bay. LfSt"):
            ki = auto_pilot.mit_mailkopf({"title": "Rechnung", "tags": ["Rechnung"], "datum": "2024-03-05",
                                          "absender": gelesen}, anhang)
            self.assertEqual(ki["absender"], "Musterversand GmbH", gelesen)
            self.assertTrue(auto_pilot.baue_entscheidung("dok.pdf", ki, ["Musterbank"])["sicher"], gelesen)
        # Drei Buchstaben gelten als Name des Ausstellers (Peter 05.11.2026)
        ki = auto_pilot.mit_mailkopf({"title": "Rechnung", "tags": ["Rechnung"], "datum": "2024-03-05",
                                      "absender": "XYZ"}, anhang)
        self.assertEqual(ki["absender"], "XYZ")


class TestZweiPhasen(_Basis):
    """KONZEPT_MAIL_AUF_ABRUF „Schneller einlesen“ (Peter 09.11.2026): Phase 1 nur der Kopf, Phase 2 der Text im
    Hintergrund. Beide zusammen müssen genau das ergeben, was das Einlesen in einem Zug ergibt - vor allem dieselben
    Kennungen, sonst erschienen schon übernommene Mails als neu."""

    FELDER = ("ort", "ordner", "schluessel", "richtung", "name", "adresse", "datum", "betreff", "vorfilter",
              "pdf_anhaenge", "anhaenge", "anhang_namen", "personen", "suchtext", "anfang", "ergebnis", "grund", "voll")

    def journal(self):
        j = mail_import.Journal(self.sammlung)
        j.eigene = sorted(EIGENE)
        return j

    def zwei_phasen(self, quelle, j, vorne=None):
        lage = {}
        b = mail_import.lies_quelle(quelle, j, nur_kopf=True, lage=lage)
        vorher = [(e.schluessel, e.voll, e.anfang) for e in b.eintraege]
        gemeldet = []
        liste = vorne(b) if vorne else None
        mail_import.lies_texte(b, lambda e, f: gemeldet.append((e, f)), vorne=liste and (lambda: liste))
        self.reihenfolge = [e.schluessel for e, _ in gemeldet]
        for e, f in gemeldet:
            b.setze_text(e, f)
        return b, vorher, lage, len(gemeldet)

    def gleich(self, quelle, vorne=None):
        ganz = mail_import.lies_quelle(quelle, self.journal())
        b, vorher, lage, gemeldet = self.zwei_phasen(quelle, self.journal(), vorne)
        self.assertEqual([[getattr(e, f) for f in self.FELDER] for e in b.eintraege],
                         [[getattr(e, f) for f in self.FELDER] for e in ganz.eintraege])
        self.assertEqual(b.wortschatz, ganz.wortschatz)
        self.assertEqual(b.zahlen, ganz.zahlen)
        self.assertEqual(lage["teil"], 1.0)
        self.assertEqual(lage["n"], ganz.zahlen["gesamt"])
        return vorher, gemeldet

    def test_ordner_mit_eml_und_mbox(self):
        self.eml("1.eml", baue(mid="<1@x>", html="<p>Guten Tag, <b>anbei</b> die Rechnung</p>"))
        self.eml("2.eml", baue(mid=None, betreff="Ohne Kennung", text="Alter Brief ohne Message-ID"))
        self.eml("3.eml", baue(mid="<3@x>", anhang=("Beitrag.pdf", pdf_bytes())), "Archiv")
        box = mailbox.mbox(os.path.join(self.quelle, "Inbox"))
        box.add(baue(mid="<m1@x>", betreff="Aus Thunderbird"))
        box.add(baue(mid=None, betreff="Auch ohne Kennung", text="Noch ein alter Text"))
        box.close()
        vorher, gemeldet = self.gleich(self.quelle)
        # Phase 1: Mails mit Message-ID ohne Text, die ohne Kennung schon ganz
        self.assertEqual(sorted((s.startswith("mid:"), voll, bool(anfang)) for s, voll, anfang in vorher),
                         [(False, True, True)] * 2 + [(True, False, False)] * 3)
        self.assertEqual(gemeldet, 3)

    def test_sichtbare_zuerst(self):
        # S2 (Peter 09.11.2026): was in der Liste steht, liest Phase 2 zuerst - gezielt, mit genau demselben Ergebnis
        for i in range(4):
            self.eml(f"{i}.eml", baue(mid=f"<{i}@x>", text=f"Text Nummer {i}"))
        box = mailbox.mbox(os.path.join(self.quelle, "Inbox"))
        for i in range(4, 7):
            box.add(baue(mid=f"<{i}@x>", text=f"Text Nummer {i}", html=f"<p>Nummer <b>{i}</b></p>"))
        box.close()
        vorne = ["mid:6@x", "mid:2@x", "mid:5@x"]
        self.gleich(self.quelle, lambda b: [e for s in vorne for e in b.eintraege if e.schluessel == s])
        self.assertEqual(self.reihenfolge[:3], vorne)
        self.assertEqual(len(self.reihenfolge), 7)                      # jede genau einmal

    def test_pst_liest_den_text_erst_in_phase_2(self):
        mit = ("From: Musterversicherung <service@muster-versicherung.example>\r\nTo: max@example.org\r\n"
               "Subject: Rechnung\r\nMessage-ID: <p1@x>\r\nDate: Mon, 1 Jun 2009 12:00:00 +0200\r\n")
        ohne = mit.replace("Message-ID: <p1@x>\r\n", "").replace("Rechnung", "Alter Brief")
        baum = _Ordner("", unter=[_Ordner("Posteingang", [
            _Nachricht(kopf=mit, text="Guten Tag", html="<p>Guten <i>Tag</i>, die Rechnung</p>",
                       anhaenge=[("R.pdf", pdf_bytes())]),
            _Nachricht(kopf=ohne, text="Ein alter Brief ohne Kennung"),
            _Nachricht(eigenschaften={mail_pst.PR_SENDER_SMTP: "max@example.org",
                                      mail_pst.PR_DISPLAY_TO: "erika@musterstadt.example",
                                      mail_pst.PR_INTERNET_MESSAGE_ID: "<s1@example.org>"}, text="Gesendet")])])

        class _Datei:
            root_folder = baum

            def close(self):
                pass
        quelle = os.path.join(self.basis, "archiv.pst")
        open(quelle, "wb").close()
        mit_text = []
        original = mail_pst.baue_eml

        def gezaehlt(m, anhaenge=True, text=True, **k):
            mit_text.append(text)
            return original(m, anhaenge, text, **k)
        with patch("mail_import.mail_pst.oeffne", return_value=_Datei()):
            ganz = mail_import.lies_quelle(quelle, self.journal())
            b, _, _, _ = self.zwei_phasen(quelle, self.journal(), lambda b: b.eintraege[::-1])      # S2: gezielt geholt
            self.assertEqual(self.reihenfolge, ["mid:s1@example.org", "mid:p1@x"])
            self.assertEqual([[getattr(e, f) for f in self.FELDER] for e in b.eintraege],
                             [[getattr(e, f) for f in self.FELDER] for e in ganz.eintraege])
            with patch("mail_import.mail_pst.baue_eml", side_effect=gezaehlt):
                b = mail_import.lies_quelle(quelle, self.journal(), nur_kopf=True)
                self.assertEqual([e.schluessel for e in b.eintraege], [e.schluessel for e in ganz.eintraege])
                gemeldet = []
                mail_import.lies_texte(b, lambda e, f: gemeldet.append((e, f)))
            # S3b: der Umweg über eine .eml nur noch für die Mail ohne Kennung, in beiden Phasen zusammen
            self.assertEqual(mit_text, [True])
        for e, f in gemeldet:
            b.setze_text(e, f)
        self.assertEqual(len(gemeldet), 2)
        self.assertEqual([[getattr(e, f) for f in self.FELDER] for e in b.eintraege],
                         [[getattr(e, f) for f in self.FELDER] for e in ganz.eintraege])

    def test_veraenderte_datei_bringt_keinen_fremden_text(self):
        # Zwischen Phase 1 und 2 steht an derselben Stelle eine andere Mail: kein fremder Text, die Mail bleibt ohne
        self.eml("1.eml", baue(mid="<1@x>", text="Der richtige Text"))
        self.eml("2.eml", baue(mid="<2@x>", text="Auch richtig"))
        b = mail_import.lies_quelle(self.quelle, self.journal(), nur_kopf=True)
        self.eml("1.eml", baue(mid="<9@x>", text="Ein ganz anderer Text"))
        gemeldet = []
        self.assertEqual(mail_import.lies_texte(b, lambda e, f: gemeldet.append((e, f))), 1)
        self.assertEqual([e.schluessel for e, _ in gemeldet], ["mid:2@x"])

    def test_mbox_und_eml_in_phase_1_nur_der_kopf(self):
        # S3 (10.11.2026): mbox und .eml zerlegen in Phase 1 nur die Kopfzeilen, die Anhänge kommen mit Phase 2
        self.eml("1.eml", baue(mid="<1@x>", anhang=("R.pdf", pdf_bytes())))
        box = mailbox.mbox(os.path.join(self.quelle, "Inbox"))
        box.add(baue(mid="<2@x>", anhang=("B.pdf", pdf_bytes())))
        box.close()
        b = mail_import.lies_quelle(self.quelle, self.journal(), nur_kopf=True)
        self.assertEqual([(e.voll, e.anhaenge, e.pdf_anhaenge) for e in b.eintraege], [(False, 0, 0)] * 2)
        gemeldet = []
        mail_import.lies_texte(b, lambda e, f: gemeldet.append((e, f)))
        for e, f in gemeldet:
            b.setze_text(e, f)
        self.assertEqual([(e.voll, e.anhaenge, e.pdf_anhaenge) for e in b.eintraege], [(True, 1, 1)] * 2)

    def test_abbrechen(self):
        for i in range(3):
            self.eml(f"{i}.eml", baue(mid=f"<{i}@x>"))
        b = mail_import.lies_quelle(self.quelle, self.journal(), nur_kopf=True)
        gemeldet = []
        mail_import.lies_texte(b, lambda e, f: gemeldet.append(e), abbrechen=lambda: len(gemeldet) >= 1)
        self.assertEqual(len(gemeldet), 1)
        self.assertEqual(b.ohne_text(), 3)                 # übernommen wird erst im Tk-Thread (setze_text)


class TestNewsletter(_Basis):
    """Peter 12.11.2026: Newsletter ausblenden können - nur auf Wunsch, mit Zahl (FALLSTRICKE #101)."""

    def test_erkennen(self):
        ja = [baue(kopf={"List-Unsubscribe": "<mailto:weg@shop.example>"}),
              baue(von="Shop <newsletter@shop.example>"), baue(von="Shop <newsletter-de@shop.example>"),
              baue(von="Info <info@news.firma.example>"), baue(von="Info <info@newsletter.firma.example>"),
              baue(betreff="Unser Newsletter im März"), baue(betreff="NEWSLETTER: Neuheiten")]
        nein = [baue(), baue(von="Info <info@firma.news>"), baue(von="Max <max.newsletter@example.org>"),
                baue(betreff="Newsletterabmeldung bestätigt"), baue(von="Info <info@renews.example>")]
        self.assertEqual([mail_lesen.ist_newsletter(mail_lesen.Mail(d)) for d in ja], [True] * len(ja))
        self.assertEqual([mail_lesen.ist_newsletter(mail_lesen.Mail(d)) for d in nein], [False] * len(nein))

    def test_ausblenden_nur_auf_wunsch_und_gezaehlt(self):
        self.eml("1.eml", baue(mid="<1@x>", kopf={"List-Unsubscribe": "<mailto:weg@shop.example>"}))
        self.eml("2.eml", baue(mid="<2@x>", von="Shop <newsletter@shop.example>"))
        self.eml("3.eml", baue(mid="<3@x>", von="Verein <info@verein.example>"))
        self.eml("4.eml", baue(mid="<4@x>", von="Erika <erika@musterstadt.example>"))
        self.eml("5.eml", baue(mid="<5@x>", von="Bank <post@mail.musterbank.example>"))
        j = mail_import.Journal(self.sammlung)
        b = mail_import.lies_quelle(self.quelle, j)
        self.assertEqual(len(mail_import.suche(b).treffer), 5)                    # standardmäßig eingeblendet
        r = mail_import.suche(b, ohne_newsletter=True)
        self.assertEqual(([e.schluessel for e, _ in r.treffer], r.newsletter),
                         (["mid:3@x", "mid:4@x", "mid:5@x"], 2))
        # Rechtsklick: ein Absender, eine Domäne (auch Unterdomänen)
        self.assertEqual(mail_import.newsletter_regel(j.newsletter, ["info@verein.example"]), 1)
        self.assertEqual(mail_import.newsletter_regel(j.newsletter, ["post@mail.musterbank.example"], domaene=True), 1)
        self.assertEqual(mail_import.newsletter_regel(j.newsletter, ["post@mail.musterbank.example"], domaene=True), 0)
        j.speichere()
        j = mail_import.Journal(self.sammlung)
        self.assertEqual(j.newsletter, ["info@verein.example", "@musterbank.example"])
        r = mail_import.suche(b, ohne_newsletter=True, newsletter_regeln=set(j.newsletter))
        self.assertEqual(([e.schluessel for e, _ in r.treffer], r.newsletter), (["mid:4@x"], 4))
        # nicht mehr: Adresse und Domäne gehen beide heraus
        self.assertEqual(mail_import.newsletter_regel(j.newsletter, ["post@mail.musterbank.example"], an=False), 1)
        self.assertEqual(j.newsletter, ["info@verein.example"])


class TestPstImport(_Basis):
    def test_einlesen_ohne_anhaenge_import_mit_und_einmal_geoeffnet(self):
        gelesen = []

        class _Gezaehlt(_Nachricht):
            def get_attachment(self, i):
                a = super().get_attachment(i)
                original = a.read_buffer

                def read_buffer(n, _o=original):
                    gelesen.append(n)
                    return _o(n)
                a.read_buffer = read_buffer
                return a
        kopf = ("From: Musterversicherung <service@muster-versicherung.example>\r\nTo: max@example.org\r\n"
                "Subject: Rechnung\r\nMessage-ID: <p1@x>\r\nDate: Mon, 1 Jun 2009 12:00:00 +0200\r\n")
        baum = _Ordner("", unter=[_Ordner("Posteingang", [_Gezaehlt(kopf=kopf, anhaenge=[("R.pdf", pdf_bytes())]),
                                                          _Gezaehlt(kopf=kopf.replace("p1@", "p2@"))])])
        geoeffnet = []

        class _Datei:
            root_folder = baum

            def close(self):
                pass
        quelle = os.path.join(self.basis, "archiv.pst")
        open(quelle, "wb").close()
        with patch("mail_import.mail_pst.oeffne", side_effect=lambda p: geoeffnet.append(p) or _Datei()):
            j = mail_import.Journal(self.sammlung)
            b = mail_import.lies_quelle(quelle, j)
            self.assertEqual((b.zahlen["gesamt"], gelesen), (2, []))          # Anhänge nicht gelesen
            self.assertEqual(b.eintraege[0].pdf_anhaenge, 1)                  # aber gezählt (über den Namen)
            hake_an(b, "@muster-versicherung.example")
            geoeffnet.clear()
            zahlen = mail_import.importiere(b, j, self.eingang)
        self.assertEqual((zahlen["mails"], zahlen["anhaenge"]), (2, 1))
        self.assertEqual(len(geoeffnet), 1)                                   # eine .pst, einmal geöffnet
        self.assertTrue(gelesen)
        self.assertIn("20090601_R.pdf", os.listdir(self.eingang))
