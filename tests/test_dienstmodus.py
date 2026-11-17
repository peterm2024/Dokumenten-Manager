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
