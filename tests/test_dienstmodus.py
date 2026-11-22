"""Dienstmodus (dienstmodus.py, Etappe 10 Schritt 3): KID ohne Hauptfenster direkt in der Hintergrund-Automatik.
Schnelle Kern-Tests ohne echtes Tk-Fenster; Bedienung und Aussehen prüft Peter (T10g.67)."""

import unittest
from unittest.mock import MagicMock, patch

import dienstmodus
import vollautomatik_fenster
from auto_pilot_service import AutoPilotService


class TestStartschalter(unittest.TestCase):
    def test_nur_mit_schalter(self):
        self.assertTrue(dienstmodus.ist_dienststart(["KID.exe", "--dienst"]))
        self.assertFalse(dienstmodus.ist_dienststart(["KID.exe"]))
        self.assertFalse(dienstmodus.ist_dienststart(["--dienst"]))    # argv[0] ist das Programm selbst
        self.assertFalse(dienstmodus.ist_dienststart(None))


class TestImmerAn(unittest.TestCase):
    def test_dienstmodus_laeuft_auch_bei_ausgeschalteter_einstellung(self):
        app = MagicMock()
        app.config.get.side_effect = lambda k, d=None: False       # auto_pilot_enabled aus
        self.assertFalse(AutoPilotService(app).ist_aktiv())
        self.assertTrue(AutoPilotService(app, immer_an=True).ist_aktiv())


class TestStatusfenster(unittest.TestCase):
    def test_oeffnet_im_dienstmodus_ohne_einstellung_und_ohne_sichtbares_hauptfenster(self):
        app = MagicMock(dienstmodus=True, vollautomatik_fenster=None)
        app.config.get.side_effect = lambda k, d=None: False
        app.root.winfo_viewable.return_value = False                 # Wurzelfenster bleibt unsichtbar
        with patch.object(vollautomatik_fenster, "VollautomatikFenster") as fenster:
            vollautomatik_fenster.synchronisiere(app, beim_start=True)
        fenster.assert_called_once()
        app.root.after.assert_not_called()                           # wartet nicht auf ein Hauptfenster

    def test_ohne_dienstmodus_bleibt_es_bei_der_einstellung(self):
        app = MagicMock(spec=["config", "root", "vollautomatik_fenster"], vollautomatik_fenster=None)
        app.config.get.side_effect = lambda k, d=None: False
        with patch.object(vollautomatik_fenster, "VollautomatikFenster") as fenster:
            vollautomatik_fenster.synchronisiere(app)
        fenster.assert_not_called()


class TestStatusfensterNurImDienstUeberAllem(unittest.TestCase):
    """B1 (Peter 21.11.2026): „Vollautomatik läuft“ lag über ALLEN Programmen. Jetzt nur im Dienstmodus; mit
    Hauptfenster kommt es nach vorn, sobald KID den Fokus bekommt - nicht, solange das Mail-Fenster offen ist."""

    def _app(self):
        app = MagicMock(spec=["root", "vollautomatik_fenster"])
        app.vollautomatik_fenster.winfo_exists.return_value = True
        app.vollautomatik_fenster.winfo_viewable.return_value = True
        return app

    def test_topmost_nur_im_dienstmodus(self):
        import inspect
        quelle = inspect.getsource(vollautomatik_fenster.VollautomatikFenster.__init__)
        teil = quelle.split("if self._dienst:")[1].split("else:")[0]
        self.assertIn('self.attributes("-topmost", True)', teil)
        self.assertNotIn('-topmost', quelle.split("if self._dienst:")[0])
        self.assertIn("vorn_halten(app)", quelle)

    def test_kid_im_fokus_holt_es_ueber_das_hauptfenster(self):
        app = self._app()
        vollautomatik_fenster.vorn_halten(app)
        vollautomatik_fenster.vorn_halten(app)               # zweites Fenster: nicht doppelt binden
        self.assertEqual(app.root.bind.call_count, 1)
        ereignis, rueckruf = app.root.bind.call_args.args
        self.assertEqual((ereignis, app.root.bind.call_args.kwargs.get("add")), ("<FocusIn>", "+"))
        rueckruf(None)
        app.vollautomatik_fenster.lift.assert_called_once_with(app.root)

    def test_mail_fenster_offen_haelt_es_zurueck(self):
        app = self._app()
        app.vollautomatik_fenster._dienst = False
        vollautomatik_fenster.zuruecktreten(app, True)
        vollautomatik_fenster.nach_vorn(app)
        app.vollautomatik_fenster.lift.assert_not_called()
        app.vollautomatik_fenster.attributes.assert_not_called()   # mit Hauptfenster nie -topmost
        vollautomatik_fenster.zuruecktreten(app, False)
        vollautomatik_fenster.nach_vorn(app)
        app.vollautomatik_fenster.lift.assert_called_once_with(app.root)

    def test_im_dienstmodus_weiter_ueber_topmost(self):
        app = self._app()
        app.vollautomatik_fenster._dienst = True
        vollautomatik_fenster.zuruecktreten(app, True)
        app.vollautomatik_fenster.attributes.assert_called_with("-topmost", False)
        vollautomatik_fenster.zuruecktreten(app, False)
        app.vollautomatik_fenster.attributes.assert_called_with("-topmost", True)


class _Einstellungen(dict):
    def get(self, k, d=None):
        return super().get(k, d)


class TestNurKurzZeigen(unittest.TestCase):
    """Schritt 2: Dokumente im Statusfenster nur kurz zeigen (KONZEPT_DIENSTMODUS F1-F3)."""

    def test_standard_mit_oberflaeche_nie_ausblenden_im_dienst_30_s(self):
        leer = _Einstellungen()
        self.assertIsNone(vollautomatik_fenster.anzeigedauer(leer, dienst=False))
        self.assertEqual(vollautomatik_fenster.anzeigedauer(leer, dienst=True), 30)

    def test_eingestellte_werte_und_unbrauchbares(self):
        e = _Einstellungen(vollautomatik_anzeigedauer=60, dienst_anzeigedauer=0)
        self.assertEqual(vollautomatik_fenster.anzeigedauer(e, dienst=False), 60)
        self.assertEqual(vollautomatik_fenster.anzeigedauer(e, dienst=True), 0)       # 0 = gar nicht zeigen
        kaputt = _Einstellungen(vollautomatik_anzeigedauer="viel", dienst_anzeigedauer=-5)
        self.assertIsNone(vollautomatik_fenster.anzeigedauer(kaputt, dienst=False))
        self.assertEqual(vollautomatik_fenster.anzeigedauer(kaputt, dienst=True), 30)
        nie = _Einstellungen(dienst_anzeigedauer=None)
        self.assertIsNone(vollautomatik_fenster.anzeigedauer(nie, dienst=True))

    def test_restzeit_ab_dem_ersten_erscheinen(self):
        self.assertIsNone(vollautomatik_fenster.restzeit(None, 100.0, 500.0))
        self.assertEqual(vollautomatik_fenster.restzeit(30, 100.0, 110.0), 20.0)
        self.assertEqual(vollautomatik_fenster.restzeit(30, 100.0, 140.0), 0.0)
        self.assertEqual(vollautomatik_fenster.restzeit(0, 100.0, 100.0), 0.0)

    def test_fensterfaktor_begrenzt(self):
        self.assertEqual(vollautomatik_fenster.fenster_faktor(_Einstellungen()), 1.5)
        self.assertEqual(vollautomatik_fenster.fenster_faktor(_Einstellungen(dienst_fenster_faktor=9)), 3.0)
        self.assertEqual(vollautomatik_fenster.fenster_faktor(_Einstellungen(dienst_fenster_faktor="x")), 1.5)

    def test_auswahl_der_einstellungen_passt_zu_den_regeln(self):
        for _text, wert in vollautomatik_fenster.DAUER_WAHL:
            self.assertEqual(vollautomatik_fenster.anzeigedauer(_Einstellungen(dienst_anzeigedauer=wert), True), wert)


class TestTageszaehler(unittest.TestCase):
    def test_zaehlt_und_beginnt_um_mitternacht_neu(self):
        import datetime
        dienst = AutoPilotService(MagicMock())
        montag, dienstag = datetime.date(2026, 11, 16), datetime.date(2026, 11, 17)
        dienst.zaehle(True, montag)
        dienst.zaehle(False, montag)
        dienst.zaehle(True, montag)
        self.assertEqual(dienst.zaehler_heute(montag), (2, 1))
        self.assertEqual(dienst.zaehler_heute(dienstag), (0, 0))
        dienst.zaehle(False, dienstag)
        self.assertEqual(dienst.zaehler_heute(dienstag), (0, 1))

    def test_zeile_ohne_inhalte(self):
        import datetime
        self.assertEqual(vollautomatik_fenster.zaehler_text(3, 1, datetime.datetime(2026, 11, 17, 14, 32)),
                         "Heute: 3 abgelegt, 1 unsicher · zuletzt nachgesehen 14:32")


class TestOhneSammlung(unittest.TestCase):
    def test_meldet_und_startet_nicht(self):
        root = MagicMock()
        einstellungen = MagicMock()
        einstellungen.get.side_effect = lambda k, d=None: None
        with patch.object(dienstmodus, "Config", return_value=einstellungen), \
                patch.object(dienstmodus.messagebox, "showerror") as meldung, \
                patch.object(dienstmodus, "AutoPilotService") as dienst:
            app = dienstmodus.DienstApp(root)
        self.assertFalse(app.gestartet)
        meldung.assert_called_once()
        root.destroy.assert_called_once()
        dienst.assert_not_called()


if __name__ == "__main__":
    unittest.main()
