"""Werkzeug „Mails importieren…“ (Mail-Import auf Abruf, KONZEPT_MAIL_AUF_ABRUF): Helfer und, mit Fenster, nur was
Dateien schützt - die Originale im Mail-Programm bleiben unverändert, gesperrte Dateien werden nicht erzwungen, aus der
Sammlung kommt nur Bestätigtes. Nur synthetische Mails."""
import datetime
import os
import shutil
import tempfile
import time
import tkinter as tk
import types
import unittest
from unittest.mock import patch

import mail_import
import mail_lesen
import mail_quellen
from tests import mail_testprofil
from tests.test_begleitet_erfassen import Einstellungen, threads_beenden
from tests.test_mail_import import baue, pdf_bytes
from tests.test_mail_quellen import fingerabdruck
from tools import mails_importieren as mi


ECHTE_SUCHE = mail_quellen.suche    # TestFenster ersetzt die Suche, damit nie die Programme des Rechners auftauchen


class TestHelfer(unittest.TestCase):
    def test_zeitraum_aus_feldern(self):
        self.assertEqual(mi.zeitraum_aus_feldern("2024", " "), (datetime.date(2024, 1, 1), None))
        self.assertEqual(mi.zeitraum_aus_feldern("03.2023", "15.04.2024"),
                         (datetime.date(2023, 3, 1), datetime.date(2024, 4, 15)))
        with self.assertRaises(ValueError):
            mi.zeitraum_aus_feldern("2024-03-05", "")

    def test_eigene(self):
        self.assertEqual(mi.eigene_aus_text("Max@Example.org; @musterstadt.example,\nkeine"),
                         ["max@example.org", "@musterstadt.example"])
        # aus „Name <adresse>“ nur die Adresse, Doppelte einmal (Peter 08.11.2026)
        self.assertEqual(mi.eigene_aus_text("max@example.org, Max Mustermann <MAX.ALT@example.org>, max@example.org"),
                         ["max@example.org", "max.alt@example.org"])

    def test_uebernahme_text(self):
        v = {"mails": 804, "anhaenge": 149, "einzelne": 40, "neue_ordner": 60}
        text = mi.uebernahme_text(v)
        self.assertIn("804 Mails und 149 PDF-Anhänge kommen als PDF in die Sammlung", text)
        self.assertIn("Dafür entstehen etwa 60 neue Ordner", text)
        self.assertIn("40 einzelne Mails kommen gemeinsam in den Ordner „Einzelne Mails“", text)
        self.assertIn("das dauert etwa 4 Stunden", text)
        einzeln = mi.uebernahme_text({"mails": 1, "anhaenge": 1, "einzelne": 1, "neue_ordner": 1})
        self.assertIn("1 Mail und 1 PDF-Anhang", einzeln)
        self.assertIn("etwa 1 neuer Ordner", einzeln)
        self.assertIn("Noch nichts angehakt", mi.uebernahme_text({"mails": 0, "anhaenge": 0, "einzelne": 0, "neue_ordner": 0}))
        # Konzept F6: direkt in einen Ordner - keine Ordner-Schätzung, keine Sammelablage, keine Wartezeit
        direkt = mi.uebernahme_text(v, "Vivafone")
        self.assertTrue(direkt.startswith("804 Mails und 149 PDF-Anhänge kommen direkt in den Ordner „Vivafone“, ohne KI"))
        self.assertNotIn("Einzelne Mails", direkt)
        self.assertNotIn("dauert", direkt)
        ohne = mi.uebernahme_text(v, anhaenge=False)
        self.assertIn("804 Mails kommen als PDF in die Sammlung. Die 149 PDF-Anhänge bleiben nur in der Original-Mail", ohne)
        self.assertIn("das dauert etwa 3 Stunden", ohne)                    # nur noch die Mails

    def test_treffer_text(self):
        e = types.SimpleNamespace(ergebnis="")
        drin = types.SimpleNamespace(ergebnis=mi.IMPORTIERT)
        r = mail_import.Suchergebnis()
        r.jahre = (2024, 2024)
        self.assertEqual(mi.treffer_text(r, 0), "Kein Treffer. Der Zeitraum 2024 kommt aus dem Suchtext.")
        r.treffer = [(e, False), (drin, True), (e, True)]
        r.varianten.update({"vivafon": 2})
        self.assertEqual(mi.treffer_text(r, 3), "3 Treffer (Zeitraum 2024 aus dem Suchtext), 1 schon in der Sammlung. "
                                                "Auch gefunden als: vivafon (2)")
        r.jahre, r.varianten = (2019, 2024), r.varianten.__class__()
        self.assertEqual(mi.treffer_text(r, 2), "3 Treffer (Zeitraum 2019-2024 aus dem Suchtext), 1 schon in der Sammlung, "
                                                "die neuesten 2 stehen in der Liste")
        r.newsletter = 12                                  # Peter 12.11.2026: Ausgeblendetes nennt die Zeile
        self.assertEqual(mi.treffer_text(r, 3, 20), "3 Treffer unter 20 Mails (Zeitraum 2019-2024 aus dem Suchtext), "
                                                    "1 schon in der Sammlung, 12 Newsletter ausgeblendet")
        r.treffer = []
        self.assertEqual(mi.treffer_text(r, 0), "Kein Treffer. Der Zeitraum 2019-2024 kommt aus dem Suchtext. "
                                                "12 Newsletter sind ausgeblendet.")

    def test_dauer_text(self):
        self.assertEqual(mi.dauer_text(10), "etwa eine Minute")
        self.assertEqual(mi.dauer_text(40 * 60), "etwa 40 Minuten")
        self.assertEqual(mi.dauer_text(4 * 3600), "etwa 4 Stunden")

    def test_abholen_laesst_das_fenster_wieder_zeichnen(self):
        # FALLSTRICKE #125: Phase 2 lieferte so schnell nach, wie das Fenster abholte - das Postfach wurde nie leer
        import queue
        postfach, geplant = queue.Queue(), []
        fenster = types.SimpleNamespace(winfo_exists=lambda: True, _postfach=postfach,
                                        after=lambda ms, fn: geplant.append(ms) or "id", _abholen=None)

        beginn = time.monotonic()

        def nachliefern():                                 # jede Nachricht bringt die nächste mit, eine Sekunde lang
            if time.monotonic() - beginn < 1:
                postfach.put((nachliefern, ()))
        postfach.put((nachliefern, ()))
        mi.MailImportFenster._abholen(fenster)             # kehrt bald zurück, statt abzuholen, solange etwas kommt
        self.assertLess(time.monotonic() - beginn, 0.5)
        self.assertEqual(geplant, [10])                    # und kommt bald wieder

    def test_phase_2_wartet_solange_das_fenster_vorrang_hat(self):
        # FALLSTRICKE #126: die Suche während Phase 2 dauerte 26 s statt 0,06 s
        import threading
        vorrang, halt, fertig = threading.Event(), threading.Event(), threading.Event()
        vorrang.set()
        ergebnis = []
        threading.Thread(target=lambda: (ergebnis.append(mi.warte_auf_vorrang(vorrang, halt.is_set)), fertig.set()),
                         daemon=True).start()
        self.assertFalse(fertig.wait(0.1))                 # wartet, solange das Fenster Vorrang hat
        vorrang.clear()
        self.assertTrue(fertig.wait(1))
        self.assertEqual(ergebnis, [False])                # und rechnet dann weiter
        vorrang.set()
        halt.set()                                         # Anhalten geht auch während des Wartens
        self.assertTrue(mi.warte_auf_vorrang(vorrang, halt.is_set))

        class Fenster:
            _vorrang, _vorrang_tiefe = vorrang, 0

            @mi.mit_vorrang
            def aussen(self):
                self.innen()
                return vorrang.is_set()                    # nach dem inneren Aufruf noch gesetzt

            @mi.mit_vorrang
            def innen(self):
                pass
        vorrang.clear()
        self.assertTrue(Fenster().aussen())
        self.assertFalse(vorrang.is_set())

    def test_stand_und_fehlende_dateien(self):
        # Peter 09.11.2026: was beim Einlesen gerade passiert, im Reiter „1. Woher?“
        self.assertEqual(mi.stand_text(400, 0.01, 1), "400 Mails")                      # zu früh für eine Restzeit
        self.assertEqual(mi.stand_text(12400, 0.25, 30, datei="Datei 2 von 5"), "12400 Mails, Datei 2 von 5, noch ca. 2 min")
        self.assertEqual(mi.stand_text(3000, 3000 / 36000, 30, gesamt=36000), "3000 von 36000, noch ca. 6 min")
        self.assertEqual(mi.stand_text(36000, 1.0, 300, gesamt=36000), "36000 von 36000")
        self.assertEqual(mi.text_hinweis(13000, 20000),
                         "Erst 65 % der Mailtexte sind durchsucht - weitere Treffer können dazukommen.")
        # F7: Ordner mit vielen Mail-Dateien
        text = mi.fehlende_text([f"{j}.pst" for j in range(2000, 2012)])
        self.assertTrue(text.startswith("12 Datei(en) ließen sich nicht lesen"))
        self.assertIn("• 2009.pst", text)
        self.assertNotIn("2010.pst", text)
        self.assertIn("… und 2 weitere", text)

    def test_fortschritt_text(self):
        # Peter 05.11. (T20.4): die KI-Einstufung von 1702 echten Mails zeigte nur einen Balken
        self.assertEqual(mi.fortschritt_text(1, 1702, 0), "1 von 1702")
        self.assertEqual(mi.fortschritt_text(5, 1702, 3), "5 von 1702")          # zu früh für eine Schätzung
        self.assertEqual(mi.fortschritt_text(101, 1702, 60), "101 von 1702, noch ca. 16 min")
        self.assertEqual(mi.fortschritt_text(1650, 1702, 990), "1650 von 1702, noch ca. 31 s")
        self.assertEqual(mi.fortschritt_text(1702, 1702, 1000), "1702 von 1702, noch ca. 1 s")

    def test_bekannt(self):
        class Gedaechtnis:
            def frage(self, absender):
                return ("Ordner", 3, 3) if absender == "Musterbank" else None
        bekannt = mi.bekannt_pruefer(["M - N - O\\Musterversicherung"], Gedaechtnis())
        self.assertTrue(bekannt("Musterversicherung", "service@muster-versicherung.example"))
        self.assertTrue(bekannt("Musterbank", "info@bank.example"))
        self.assertTrue(bekannt("", "info@musterversicherung.example"))      # ohne Namen: die Domain
        self.assertFalse(bekannt("", "musterversicherung@gmail.com"))        # nie die eines Mail-Anbieters
        self.assertFalse(bekannt("Erika Musterfrau", "erika@musterstadt.example"))
        with patch("tools.mails_importieren.auto_pilot.finde_passenden_ordner") as suche:
            bekannt("Erika Musterfrau", "erika@musterstadt.example")
            suche.assert_not_called()                                     # gemerkt, nicht neu gesucht


class _FensterBasis(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(threads_beenden)
        self.addCleanup(self.root.destroy)
        self.addCleanup(threads_beenden)
        self.basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.basis, True)
        self.sammlung = os.path.join(self.basis, "Sammlung")
        for ordner in ("0_Posteingang", "M - N - O - P - Q - R\\Musterversicherung"):
            os.makedirs(os.path.join(self.sammlung, ordner))
        self.quelle = os.path.join(self.basis, "mails")
        os.makedirs(self.quelle)
        tz = datetime.timezone.utc
        mails = [baue(mid="<1@x>", anhang=("Rechnung.pdf", pdf_bytes())),                         # 05.03.2024
                 baue(mid="<2@x>", von="Shop <info@shop.example>", betreff="Bestellung", text="Ihre Bestellung 4711."),
                 baue(mid="<3@x>", von="Shop <info@shop.example>", betreff="Paket unterwegs", text="Ihr Paket kommt."),
                 baue(mid="<4@x>", von="Kabel Muster <info@kabel.example>", betreff="Vertrag",
                      text="Ihr Vivafon Vertrag wurde verlängert.", datum=datetime.datetime(2023, 6, 1, tzinfo=tz)),
                 baue(mid="<5@x>", von="Liste <l@liste.example>", kopf={"List-Unsubscribe": "<mailto:a@b>"},
                      betreff="Newsletter")]
        for i, daten in enumerate(mails):
            with open(os.path.join(self.quelle, f"{i}.eml"), "wb") as f:
                f.write(daten)
        self.dienst = types.SimpleNamespace(pausen=0)
        self.dienst.pausieren = lambda: setattr(self.dienst, "pausen", self.dienst.pausen + 1)
        self.dienst.fortsetzen = lambda: setattr(self.dienst, "pausen", self.dienst.pausen - 1)
        self.app = types.SimpleNamespace(root=self.root, master_folder=self.sammlung, config=Einstellungen(),
                                         auto_pilot_service=self.dienst, logger=None)
        for p in (patch("tools.mails_importieren.UIUtils.werkzeugfenster"),        # sonst unsichtbar (FALLSTRICKE #95)
                  patch("tools.mails_importieren.mb.askyesno", return_value=True),
                  patch("tools.mails_importieren.mb.showinfo"),
                  patch("tools.mails_importieren.ablage_gedaechtnis.lade", return_value=None),
                  patch("tools.mails_importieren.mail_quellen.suche", return_value=[])):   # nie die Programme des Rechners
            p.start()
            self.addCleanup(p.stop)

    def warte(self, bedingung, sekunden=10):
        ende = time.time() + sekunden
        while time.time() < ende:
            self.root.update()
            if bedingung():
                return
            time.sleep(0.02)
        self.fail("Zeitüberschreitung")


class TestFenster(_FensterBasis):
    """Nur, was Dateien schützt (Peter 09.11.2026): Die Bedienung des Fensters prüft Peter von Hand, die Logik dahinter
    prüfen die Kern-Tests in test_mail_import ohne Fenster."""

    def eingelesen(self):
        f = mi.MailImportFenster(self.app)
        self.addCleanup(lambda: f.winfo_exists() and f._schliessen())
        f.ent_quelle.insert(0, self.quelle)
        f.ent_eigene.insert(0, "max@example.org")
        f._einlesen()
        self.warte(lambda: f.bestand is not None and not f._laeuft)
        return f

    def test_abbrechen_sagt_was_es_tut_und_kein_zweiter_lauf(self):
        # Lauf 04.11.: Abbrechen wartet die laufende Mail ab - ohne Rückmeldung wirkte der Knopf tot,
        # und ein zweiter Start während des Laufs setzte den Abbruch zurück (zwei Threads an einem Journal)
        import threading
        f = self.eingelesen()
        f._alle_anhaken()
        frei, begonnen = threading.Event(), threading.Event()
        self.addCleanup(frei.set)

        def langsam(*a, **k):
            begonnen.set()
            frei.wait(5)
            return mail_import.collections.Counter()
        with patch("tools.mails_importieren.mail_import.importiere", side_effect=langsam):
            f._importieren()
            self.warte(begonnen.is_set)
            ja = mi.mb.askyesno
            ja.reset_mock()
            for start in (f._importieren, f._einlesen):
                start()                                    # alles gesperrt, keine Rückfrage, kein zweiter Thread
            ja.assert_not_called()
            self.assertEqual(str(f.btn_import.cget("state")), "disabled")
            f.btn_abbrechen.invoke()
            self.assertEqual(f.btn_abbrechen.cget("text"), "Bricht ab…")
            self.assertEqual(str(f.btn_abbrechen.cget("state")), "disabled")
            self.assertTrue(f._abbruch.is_set())
            frei.set()
            self.warte(lambda: not f._laeuft)
        self.assertEqual(f.btn_abbrechen.cget("text"), "Abbrechen")
        self.assertEqual(len(f.angehakt), 5)                 # nichts übernommen: die Häkchen bleiben
        self.assertEqual(str(f.btn_import.cget("state")), "normal")

    def _importiert_mit_papierkorb(self):
        """Fenster nach einem Import, abgelegt von der „Vollautomatik“ (anderer Ordner, anderer Name)."""
        f = self.eingelesen()
        for s in ("mid:1@x", "mid:2@x", "mid:3@x"):
            f._schalte(s)
        f._importieren()
        self.warte(lambda: not f._laeuft)
        eingang = os.path.join(self.sammlung, "0_Posteingang")
        abgelegt = os.path.join(self.sammlung, "A - B", "Abgelegt")
        os.makedirs(abgelegt)
        for i, name in enumerate(sorted(os.listdir(eingang))):
            shutil.move(os.path.join(eingang, name), os.path.join(abgelegt, f"umbenannt{i}.pdf"))
        self.geworfen = []

        def in_papierkorb(pfade):
            self.geworfen.extend(pfade)
            for p in pfade:
                os.remove(p)
            return len(pfade), 0
        self.app.file_ops = types.SimpleNamespace(in_papierkorb=in_papierkorb)
        return f, abgelegt

    def test_zuruecknehmen_nur_bestaetigt_und_nur_die_eigenen_dateien(self):
        # Nimmt nur die PDFs dieser Mail (samt Anhang) aus der Sammlung, auch wenn die Vollautomatik sie umbenannt hat,
        # und ohne Bestätigung gar nichts
        f, abgelegt = self._importiert_mit_papierkorb()
        self.assertEqual(len(os.listdir(abgelegt)), 4)                           # 3 Mails + 1 PDF-Anhang
        vorher = sorted(os.listdir(abgelegt))
        f.tree_m.selection_set("mid:2@x")
        with patch("tools.mails_importieren.mb.askyesno", return_value=False):
            f._zuruecknehmen()
            self.warte(lambda: not f._laeuft)
        self.assertEqual(sorted(os.listdir(abgelegt)), vorher)
        self.assertEqual(self.geworfen, [])
        self.assertEqual(f.tree_m.set("mid:2@x", "hinweis"), "in der Sammlung")
        f.tree_m.selection_set("mid:1@x")
        f._zuruecknehmen()
        self.warte(lambda: not f._laeuft)
        self.assertEqual(len(self.geworfen), 2)                                  # Mail-PDF und Anhang-PDF
        self.assertEqual(len(os.listdir(abgelegt)), 2)
        self.assertEqual(f.tree_m.set("mid:1@x", "hinweis"), "aus der Sammlung genommen")
        # Kommt beim nächsten Einlesen nicht als neu wieder
        b = mail_import.lies_quelle(self.quelle, mail_import.Journal(self.sammlung))
        e = next(x for x in b.eintraege if x.schluessel == "mid:1@x")
        self.assertEqual((e.ergebnis, e.grund), ("importiert", mail_import.GRUND_ZURUECKGENOMMEN))


class TestMailProgramm(_FensterBasis):
    """Mail-Quellen-Assistent im Fenster: Testprofil ohne echte Mails, kein echtes Mail-Programm beteiligt."""

    def setUp(self):
        super().setUp()
        self.rechner = os.path.join(self.basis, "rechner")
        mail_testprofil.baue(self.rechner)
        env = {"APPDATA": os.path.join(self.rechner, "AppData", "Roaming"),
               "LOCALAPPDATA": os.path.join(self.rechner, "AppData", "Local")}
        self.gefunden = ECHTE_SUCHE(env, dokumente="")
        self.kopie = os.path.join(self.basis, "lokal", "Mail-Kopie")
        p = patch("tools.mails_importieren.mail_quellen.kopie_ordner", return_value=self.kopie)
        p.start()
        self.addCleanup(p.stop)
        # Ein echtes Meldungsfenster bliebe stehen und hielte den Test an: Fehler kommen als Test-Fehler
        for name in ("showerror", "showwarning"):
            p = patch(f"tools.mails_importieren.mb.{name}", side_effect=lambda titel, text, **k: self.meldungen.append(text))
            p.start()
            self.addCleanup(p.stop)
        self.meldungen = []

    def fenster(self, programme=None):
        with patch("tools.mails_importieren.mail_quellen.suche", return_value=self.gefunden if programme is None else programme):
            f = mi.MailImportFenster(self.app)
            self.addCleanup(lambda: f.winfo_exists() and f._schliessen())
            self.warte(lambda: f.programme or f.lbl_programm.cget("text"))
        return f

    def einlesen(self, f):
        f._einlesen()
        self.warte(lambda: not f._laeuft)

    def test_einmal_durch_und_die_originale_bleiben_unveraendert(self):
        vorher = fingerabdruck(self.rechner)
        f = self.fenster()
        self.einlesen(f)
        self.assertEqual(mail_import.quelle_art(f.bestand.quelle), "kopie")
        self.assertIn(f"2 {mail_lesen.GELOESCHT}", f.lbl_zahlen.cget("text"))
        self.assertIn("1 nur teilweise geladen", f.lbl_zahlen.cget("text"))
        self.assertEqual(mail_import.Journal(self.sammlung).zuletzt["programm"], mail_quellen.THUNDERBIRD)
        f._alle_anhaken()
        f._importieren()
        self.warte(lambda: not f._laeuft)
        eingang = os.listdir(os.path.join(self.sammlung, "0_Posteingang"))
        self.assertGreaterEqual(len(eingang), 1)
        # Auf Abruf (08.11.2026): Nach dem Import wird weitergesucht, die Kopie bleibt dafür liegen. E10 gilt beim
        # Schließen: gefragt, mit Ja ist sie weg
        self.assertTrue(mail_quellen.ist_kopie(self.kopie))
        self.assertEqual(str(f.btn_import.cget("state")), tk.DISABLED)
        f._schliessen()
        self.assertFalse(os.path.exists(self.kopie))
        self.assertEqual(fingerabdruck(self.rechner), vorher)

    def test_schliessen_waehrend_der_text_nachgelesen_wird(self):
        # Phase 2 (09.11.2026) hat eine Datei der Kopie offen. Schließen hält sie an und wartet, bis die Datei zu ist -
        # sonst bliebe die Kopie mit privaten Mails liegen (E10)
        import threading
        original, begonnen = mail_import.text_felder, threading.Event()

        def langsam(*a, **k):
            if threading.current_thread().name == "Mail-Import Text":
                begonnen.set()
                time.sleep(0.3)
            return original(*a, **k)
        with patch("mail_import.text_felder", side_effect=langsam):
            f = self.fenster()
            self.einlesen(f)
            self.warte(begonnen.is_set)
            thread = f._phase2["thread"]
            f._schliessen()
            self.assertFalse(thread.is_alive())           # keine Datei der Kopie mehr offen
        self.assertFalse(os.path.exists(self.kopie))

    def test_gesperrte_datei_fragt_und_erzwingt_nichts(self):
        f = self.fenster()
        fehler = mail_quellen.Gesperrt(mail_quellen.OUTLOOK)
        with patch("tools.mails_importieren.mail_quellen.kopiere", side_effect=fehler) as kopiere, \
                patch("tools.mails_importieren.mb.askretrycancel", side_effect=[True, False]) as frage:
            self.einlesen(f)
            self.warte(lambda: frage.call_count == 2 and not f._laeuft)
        self.assertEqual(kopiere.call_count, 2)
        self.assertIn("Outlook schließen", frage.call_args[0][1])
        self.assertIsNone(f.bestand)


if __name__ == "__main__":
    unittest.main()
