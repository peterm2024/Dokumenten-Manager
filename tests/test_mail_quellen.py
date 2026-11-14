"""Mail-Quellen-Assistent (mail_quellen.py): finden, kopieren, Originale bleiben unverändert. Testprofil ohne echte Mails."""
import ctypes
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

import mail_import
import mail_lesen
import mail_quellen
from tests import mail_testprofil


def fingerabdruck(wurzel):
    """Inhalt, Größe und Änderungszeit jeder Datei: Beweis, dass ein Durchlauf nichts verändert hat (Konzept „Absicherung“)."""
    stand = {}
    for w, _, dateien in os.walk(wurzel):
        for name in dateien:
            pfad = os.path.join(w, name)
            st = os.stat(pfad)
            with open(pfad, "rb") as f:
                stand[pfad] = (hashlib.sha256(f.read()).hexdigest(), st.st_size, st.st_mtime_ns)
    return stand


class _Basis(unittest.TestCase):
    def setUp(self):
        self.basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.basis, True)
        self.ziel = os.path.join(self.basis, "rechner")
        mail_testprofil.baue(self.ziel)
        self.env = {"APPDATA": os.path.join(self.ziel, "AppData", "Roaming"),
                    "LOCALAPPDATA": os.path.join(self.ziel, "AppData", "Local")}
        self.kopie = os.path.join(self.basis, "lokal", "Mail-Kopie")

    def programme(self):
        return mail_quellen.suche(self.env, dokumente=os.path.join(self.ziel, "Dokumente"))

    def thunderbird(self):
        return next(p for p in self.programme() if p.name == mail_quellen.THUNDERBIRD)

    def konto(self, teil):
        return next(q for q in self.thunderbird().quellen if teil in q.name)


class TestSuche(_Basis):
    def test_findet_konten_nicht_feeds_und_auch_verschobene(self):
        namen = [q.name for q in self.thunderbird().quellen]
        self.assertEqual(len(namen), 4, namen)
        self.assertFalse(any("Blogs" in n for n in namen))
        self.assertTrue(any("verschoben" in n for n in namen))
        self.assertEqual(namen[0], "Konto Beispiel")                # das zweite Profil hat keine lesbaren Mails

    def test_zwei_profile_mit_mails_tragen_den_profilnamen(self):
        zweites = os.path.join(self.ziel, "AndererOrt", "zweites-profil")
        konto = os.path.join(zweites, "Mail", "pop.zwei.example")
        mail_testprofil.mbox(konto, "Inbox", mail_testprofil.mail(20, "Zweites Profil"))
        with open(os.path.join(zweites, "prefs.js"), "w", encoding="utf-8") as f:
            f.write('user_pref("mail.accountmanager.accounts", "account1");\n'
                    'user_pref("mail.account.account1.server", "server1");\n'
                    'user_pref("mail.server.server1.type", "pop3");\n'
                    'user_pref("mail.server.server1.name", "Zweites Konto");\n'
                    'user_pref("mail.server.server1.directory-rel", "[ProfD]Mail/pop.zwei.example");\n')
        namen = [q.name for q in self.thunderbird().quellen]
        self.assertEqual(namen[0], "default-release: Konto Beispiel")     # das Standardprofil zuerst
        self.assertEqual(namen[-1], "zweites: Zweites Konto")

    def test_nicht_vorhandenes_profil_und_fehlendes_programm_sind_kein_fehler(self):
        self.assertEqual([p[0] for p in mail_quellen.thunderbird_profile(os.path.join(self.env["APPDATA"], "Thunderbird"))],
                         ["default-release", "zweites"])
        self.assertEqual(mail_quellen.suche({"APPDATA": os.path.join(self.basis, "nichts"), "LOCALAPPDATA": ""}, dokumente=""), [])
        self.assertEqual(mail_quellen.suche({}, dokumente=""), [])

    def test_kaputte_einstellungen_halten_die_suche_nicht_auf(self):
        with open(os.path.join(self.env["APPDATA"], "Thunderbird", "profiles.ini"), "w", encoding="utf-8") as f:
            f.write("kein ini")
        self.assertEqual(self.programme(), [])

    def test_positivliste_nur_mail_dateien(self):
        dateien = [d for q in self.thunderbird().quellen for d in q.dateien]
        namen = {os.path.basename(d[0]) for d in dateien}
        self.assertEqual(namen, {"Inbox", "Sent", "Trash", "Junk", "Drafts", "Templates", "2023", "2024", "März.Belege", "INBOX"})
        self.assertFalse(any(n.endswith((".msf", ".dat", ".html", ".json", ".db", ".sqlite", ".js")) for n in namen))

    def test_ordnernamen_aus_dem_pfad(self):
        ordner = {d[1] for d in self.konto("Beispiel").dateien}
        self.assertIn("Archives/2024/März.Belege", ordner)
        self.assertIn("Archives/2024", ordner)

    def test_eigene_adressen_klein_und_je_konto(self):
        self.assertEqual(self.konto("Firma").adressen, ["max.mustermann@firma.example", "max@firma.example"])

    def test_imap_ordner_ohne_text_wird_gezaehlt(self):
        self.assertEqual(self.konto("Firma").nur_online, 1)
        self.assertEqual(self.konto("Beispiel").nur_online, 0)

    def test_maildir_wird_erklaert_nicht_gelesen(self):
        self.assertFalse(any("Maildir" in q.name or "maildir" in d[0] for q in self.thunderbird().quellen for d in q.dateien))
        ordner = os.path.join(self.env["APPDATA"], "Thunderbird")
        shutil.rmtree(os.path.join(ordner, "Profiles"))
        p = self.programme()
        self.assertEqual([x.name for x in p], [mail_quellen.THUNDERBIRD])
        self.assertIn("Maildir", p[0].erklaerung)
        self.assertEqual(p[0].quellen, [])

    def test_outlook_dateien_an_beiden_orten(self):
        for ordner, name in ((os.path.join(self.env["LOCALAPPDATA"], "Microsoft", "Outlook"), "konto.ost"),
                             (os.path.join(self.ziel, "Dokumente", "Outlook-Dateien"), "archiv.pst"),
                             (os.path.join(self.ziel, "Dokumente", "Outlook-Dateien"), "notiz.txt")):
            os.makedirs(ordner, exist_ok=True)
            with open(os.path.join(ordner, name), "wb") as f:
                f.write(b"x" * 2048)
        outlook = next(p for p in self.programme() if p.name == mail_quellen.OUTLOOK)
        self.assertEqual(sorted(q.name for q in outlook.quellen), ["archiv.pst", "konto.ost"])
        self.assertEqual(outlook.text(), "Outlook (2 Dateien, 5 KB)")

    def test_nicht_lesbare_programme_werden_erklaert(self):
        os.makedirs(os.path.join(self.env["LOCALAPPDATA"], "Microsoft", "Olk"))
        neu = next(p for p in self.programme() if p.name == "Neues Outlook")
        self.assertEqual(neu.quellen, [])
        self.assertTrue(neu.erklaerung)
        self.assertEqual(neu.text(), "Neues Outlook (nicht lesbar)")


class TestKopie(_Basis):
    def test_originale_bleiben_unveraendert(self):
        # Peters Vorgabe 05.11.2026: Die Mail-Funktion darf unter keinen Umständen beeinflusst werden
        vorher = fingerabdruck(self.ziel)
        p = self.thunderbird()
        self.assertTrue(mail_quellen.kopiere(p.quellen, self.kopie, frei=10 ** 12))
        journal = mail_import.Journal(os.path.join(self.basis, "Sammlung"))
        bestand = mail_import.lies_quelle(self.kopie, journal)
        for e in bestand.eintraege:
            mail_import.lade_mail(self.kopie, e.ort)
        self.assertEqual(fingerabdruck(self.ziel), vorher)

    def test_nur_mail_dateien_keine_zugangsdaten_in_der_kopie(self):
        mail_quellen.kopiere(self.thunderbird().quellen, self.kopie, frei=10 ** 12)
        for name in os.listdir(self.kopie):
            with open(os.path.join(self.kopie, name), "rb") as f:
                self.assertNotIn(b"GEHEIM", f.read(), name)
        # Selbst wenn die Suche einen Fehler hätte: was so heißt, wird nie kopiert
        fremd = os.path.join(self.basis, "logins.json")
        with open(fremd, "w") as f:
            f.write("From GEHEIM")
        q = mail_quellen.Quelle(mail_quellen.THUNDERBIRD, "x", [(fremd, "", 11)])
        mail_quellen.kopiere([q], self.kopie, frei=10 ** 12)
        self.assertEqual(mail_quellen.kopie_dateien(self.kopie), [])

    def test_einlesen_der_kopie_ordner_filter_und_geloeschte(self):
        mail_quellen.kopiere(self.thunderbird().quellen, self.kopie, frei=10 ** 12)
        self.assertEqual(mail_import.quelle_art(self.kopie), "kopie")
        journal = mail_import.Journal(os.path.join(self.basis, "Sammlung"))
        b = mail_import.lies_quelle(self.kopie, journal)
        self.assertEqual(b.zahlen[mail_lesen.GELOESCHT], 2)
        self.assertEqual(b.zahlen[mail_lesen.TEILWEISE], 1)
        self.assertEqual(b.zahlen[mail_lesen.ZAHL_FROM_IM_TEXT], 1)
        betreffe = {e.betreff: e for e in b.eintraege}
        self.assertNotIn("Gelöscht, noch nicht komprimiert", betreffe)
        self.assertNotIn("Auf dem Server gelöscht", betreffe)
        self.assertTrue(betreffe["Im Papierkorb"].vorfilter)
        self.assertTrue(betreffe["Spam"].vorfilter)
        self.assertEqual(betreffe["Nie abgeschickter Entwurf"].vorfilter, mail_lesen.GRUND_ENTWURF)
        self.assertEqual(betreffe["Vorlage Kündigung"].vorfilter, mail_lesen.GRUND_ENTWURF)
        self.assertEqual(betreffe["Gesendete Mail"].vorfilter, "")
        self.assertEqual(betreffe["Unterordner mit Punkt im Namen"].ordner, "Archives/2024/März.Belege")
        self.assertNotIn("Feed, keine Mail", betreffe)
        self.assertEqual(mail_import.lade_mail(self.kopie, betreffe["Lokaler Ordner"].ort).titel, "Lokaler Ordner")
        self.assertIn(b"From Hamburg nach Berlin",
                      mail_import.lade_mail(self.kopie, betreffe["Text mit unmaskiertem From"].ort).daten)

    def test_kopie_wird_wiederverwendet_bis_sich_das_original_aendert(self):
        q = [self.konto("Beispiel")]
        mail_quellen.kopiere(q, self.kopie, frei=10 ** 12)
        self.assertTrue(mail_quellen.kopie_passt(self.kopie, q))
        self.assertFalse(mail_quellen.kopie_passt(self.kopie, [self.konto("Firma")]))    # andere Auswahl
        with open(q[0].dateien[0][0], "ab") as f:
            f.write(b"From - Fri Mar 01 11:00:00 2024\nSubject: neu\n\nneu\n")
        self.assertFalse(mail_quellen.kopie_passt(self.kopie, q))

    def test_abbruch_hinterlaesst_nichts(self):
        q = [self.konto("Beispiel")]
        self.assertFalse(mail_quellen.kopiere(q, self.kopie, abbrechen=lambda: True, frei=10 ** 12))
        self.assertFalse(os.path.exists(self.kopie))

    def test_fehler_mitten_im_kopieren_hinterlaesst_nichts(self):
        q = self.konto("Beispiel")
        q.dateien.append((os.path.join(self.basis, "fehlt"), "", 5))
        with self.assertRaises(OSError):
            mail_quellen.kopiere([q], self.kopie, frei=10 ** 12)
        self.assertFalse(os.path.exists(self.kopie))

    def test_zu_wenig_platz_kopiert_nichts(self):
        with self.assertRaises(mail_quellen.ZuWenigPlatz) as fehler:
            mail_quellen.kopiere([self.konto("Beispiel")], self.kopie, frei=1000)
        self.assertIn("frei sind", str(fehler.exception))
        self.assertFalse(os.path.exists(self.kopie))

    def test_gesperrte_datei_meldet_das_programm_und_der_neue_versuch_klappt(self):
        # So sperrt klassisches Outlook seine .pst: ohne Teilen geöffnet
        pst = os.path.join(self.basis, "archiv.pst")
        with open(pst, "wb") as f:
            f.write(b"x" * 1000)
        q = mail_quellen.Quelle(mail_quellen.OUTLOOK, "archiv.pst", [(pst, "", 1000)])
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = ctypes.c_void_p
        griff = kernel32.CreateFileW(pst, 0x80000000, 0, None, 3, 0, None)
        try:
            with self.assertRaises(mail_quellen.Gesperrt) as fehler:
                mail_quellen.kopiere([q], self.kopie, frei=10 ** 12)
            self.assertEqual(fehler.exception.programm, mail_quellen.OUTLOOK)
            self.assertFalse(os.path.exists(self.kopie))
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(griff))
        self.assertTrue(mail_quellen.kopiere([q], self.kopie, frei=10 ** 12))
        self.assertTrue(os.path.exists(os.path.join(self.kopie, "00000.pst")))

    def test_aenderung_waehrend_des_kopierens_kopiert_neu_oder_gibt_auf(self):
        q = self.konto("Beispiel")
        pfad = q.dateien[0][0]
        neue_zeit = 10 ** 18
        echte_stat = os.stat
        staende = []

        def stat_mit_aenderung(p, *a, **k):
            if p == pfad:
                staende.append(1)
                if len(staende) == 2:      # nach dem ersten Kopieren, vor dem Vergleich: Thunderbird schreibt
                    os.utime(pfad, ns=(neue_zeit, neue_zeit))
            return echte_stat(p, *a, **k)

        with patch("mail_quellen.os.stat", stat_mit_aenderung):
            self.assertTrue(mail_quellen.kopiere([q], self.kopie, frei=10 ** 12))
        self.assertEqual(len(staende), 4)               # ein zweiter Durchgang fand statt
        self.assertEqual(mail_quellen.lies_kopie(self.kopie)["dateien"][0]["zeit"], neue_zeit)

        # Ändert sich die Datei bei jedem Versuch, gibt KID auf, statt mit einem halben Stand zu arbeiten
        zeiten = iter(range(1, 100))

        def stat_immer_neu(p, *a, **k):
            if p == pfad:
                n = next(zeiten) * 10 ** 18
                os.utime(pfad, ns=(n, n))
            return echte_stat(p, *a, **k)

        ziel = os.path.join(self.basis, "lokal", "zweite")
        with patch("mail_quellen.os.stat", stat_immer_neu), self.assertRaises(OSError) as fehler:
            mail_quellen.kopiere([q], ziel, frei=10 ** 12)
        self.assertIn("schließen", str(fehler.exception))
        self.assertFalse(os.path.exists(ziel))

    def test_loeschen_nur_mit_markierung(self):
        fremd = os.path.join(self.basis, "fremd")
        os.makedirs(fremd)
        with open(os.path.join(fremd, "wichtig.txt"), "w") as f:
            f.write("x")
        self.assertFalse(mail_quellen.loesche_kopie(fremd))
        self.assertTrue(os.path.exists(os.path.join(fremd, "wichtig.txt")))
        # ... und ein Ordner mit fremden Dateien wird nicht als Ziel überschrieben
        with self.assertRaises(OSError):
            mail_quellen.kopiere([self.konto("Beispiel")], fremd, frei=10 ** 12)
        self.assertTrue(os.path.exists(os.path.join(fremd, "wichtig.txt")))
        mail_quellen.kopiere([self.konto("Beispiel")], self.kopie, frei=10 ** 12)
        self.assertTrue(mail_quellen.loesche_kopie(self.kopie))
        self.assertFalse(os.path.exists(self.kopie))
        self.assertTrue(mail_quellen.loesche_kopie(self.kopie))           # schon weg

    def test_halbe_kopie_gilt_nicht_als_vollstaendig(self):
        os.makedirs(self.kopie)
        with open(os.path.join(self.kopie, mail_quellen.MARKE), "w") as f:
            json.dump({"fertig": False}, f)
        self.assertIsNone(mail_quellen.lies_kopie(self.kopie))
        self.assertFalse(mail_quellen.kopie_passt(self.kopie, [self.konto("Beispiel")]))
        self.assertEqual(mail_quellen.kopie_dateien(self.kopie), [])
        self.assertTrue(mail_quellen.loesche_kopie(self.kopie))

    def test_mehrere_pst_in_einer_kopie_oeffnen_einzeln_und_wechselnd(self):
        for name in ("00000.pst", "00001.pst"):
            os.makedirs(self.kopie, exist_ok=True)
            with open(os.path.join(self.kopie, name), "wb") as f:
                f.write(b"x")
        with open(os.path.join(self.kopie, mail_quellen.MARKE), "w") as f:
            json.dump({"fertig": True, "dateien": [
                {"datei": "00000.pst", "quelle": "a", "konto": "a", "ordner": "", "groesse": 1, "zeit": 1},
                {"datei": "00001.pst", "quelle": "b", "konto": "b", "ordner": "", "groesse": 1, "zeit": 1}]}, f)
        offen = []

        def oeffne(pfad):
            d = MagicMock()
            offen.append((os.path.basename(pfad), d))
            return d

        eml = b"From: A <a@x.example>\nSubject: T\nMessage-ID: <1@x>\n\nText\n"
        with patch("mail_import.mail_pst.oeffne", side_effect=oeffne), patch("mail_import.mail_pst.hole"), \
                patch("mail_import.mail_pst.baue_eml", return_value=eml):
            with mail_import.geoeffnet(self.kopie):
                for ort in (("00000.pst", 1), ("00000.pst", 2), ("00001.pst", 1), ("00001.pst", 2)):
                    mail_import.lade_mail(self.kopie, ort)
        self.assertEqual([n for n, _ in offen], ["00000.pst", "00001.pst"])   # je Datei einmal
        for _, d in offen:
            d.close.assert_called_once()                                       # am Ende alle wieder zu


if __name__ == "__main__":
    unittest.main()
