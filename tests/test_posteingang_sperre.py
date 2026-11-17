"""Sperre des Posteingangs über Rechnergrenzen (posteingang_sperre.py, Etappe 10 Schritt 4). Nur Musterdaten."""

import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import app_paths
import auto_pilot_service
import dienstmodus
import posteingang_sperre as ps
from auto_pilot_service import AutoPilotService

ICH = {"rechner": "BUERO-PC", "pid": 111}
PANEL = {"rechner": "PANEL-01", "pid": 222}
JETZT = datetime(2026, 11, 17, 8, 0, 0)


class _Sammlung(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.master = os.path.join(self.tmp, "Sammlung")
        self.posteingang = os.path.join(self.master, "0_Posteingang")
        os.makedirs(self.posteingang)

    def hinweis(self):
        return os.path.join(self.posteingang, ps.HINWEIS_NAME)


class TestSperre(_Sammlung):
    def test_eigene_sperre_ist_nicht_fremd(self):
        ps.belege(self.master, self.posteingang, JETZT, PANEL)
        self.assertIsNone(ps.fremd_aktiv(self.master, JETZT, PANEL))
        self.assertTrue(os.path.isfile(self.hinweis()))
        with open(self.hinweis(), encoding="utf-8") as f:
            self.assertIn("PANEL-01", f.read())

    def test_frische_fremde_sperre_wird_erkannt(self):
        ps.belege(self.master, self.posteingang, JETZT, PANEL)
        fremd = ps.fremd_aktiv(self.master, JETZT + timedelta(minutes=5), ICH)
        self.assertEqual(fremd["rechner"], "PANEL-01")
        self.assertEqual(ps.beschreibung(fremd), "Rechner PANEL-01 (seit 17.11.2026 08:00)")

    def test_verwaiste_sperre_zaehlt_nicht(self):
        ps.belege(self.master, self.posteingang, JETZT, PANEL)
        self.assertIsNone(ps.fremd_aktiv(self.master, JETZT + timedelta(seconds=ps.VERWAIST_NACH_S + 1), ICH))

    def test_lebenszeichen_aus_der_zukunft_gilt_als_frisch(self):
        ps.belege(self.master, self.posteingang, JETZT, PANEL)
        self.assertIsNotNone(ps.fremd_aktiv(self.master, JETZT - timedelta(minutes=3), ICH))   # Uhren weichen ab

    def test_erneuern_haelt_den_start_und_weicht_fremden(self):
        ps.belege(self.master, self.posteingang, JETZT, PANEL)
        self.assertTrue(ps.erneuere(self.master, JETZT + timedelta(minutes=1), PANEL))
        sperre = ps.lies(self.master)
        self.assertEqual((sperre["seit"], sperre["lebenszeichen"]), ("2026-11-17 08:00:00", "2026-11-17 08:01:00"))
        self.assertFalse(ps.erneuere(self.master, JETZT + timedelta(minutes=2), ICH))         # Panel lebt noch
        self.assertEqual(ps.lies(self.master)["rechner"], "PANEL-01")
        self.assertTrue(ps.erneuere(self.master, JETZT + timedelta(hours=1), ICH))            # Panel verwaist

    def test_freigeben_nur_die_eigene(self):
        ps.belege(self.master, self.posteingang, JETZT, PANEL)
        ps.gib_frei(self.master, self.posteingang, ICH)
        self.assertIsNotNone(ps.lies(self.master))
        ps.gib_frei(self.master, self.posteingang, PANEL)
        self.assertIsNone(ps.lies(self.master))
        self.assertFalse(os.path.exists(self.hinweis()))

    def test_lebenszeichen_liegt_im_daten_ordner_nicht_im_posteingang(self):
        ps.belege(self.master, self.posteingang, JETZT, PANEL)
        self.assertEqual(os.listdir(self.posteingang), [ps.HINWEIS_NAME])
        self.assertTrue(os.path.isfile(app_paths.posteingang_sperre_path(self.master)))

    def test_kaputtes_lebenszeichen_sperrt_nicht(self):
        os.makedirs(os.path.dirname(app_paths.posteingang_sperre_path(self.master)), exist_ok=True)
        with open(app_paths.posteingang_sperre_path(self.master), "w", encoding="utf-8") as f:
            f.write("{kaputt")
        self.assertIsNone(ps.fremd_aktiv(self.master, JETZT, ICH))


class TestHintergrundAutomatik(_Sammlung):
    """Ein KID mit Oberfläche auf einem anderen PC lässt den Posteingang in Ruhe, solange der Dienst lebt."""

    def _dienst(self, immer_an=False):
        app = MagicMock()
        app.master_folder = self.master
        app.config.get.side_effect = lambda k, d=None: {"auto_pilot_enabled": True}.get(k, d)
        app.root.after.side_effect = lambda ms, fn: fn()
        return AutoPilotService(app, immer_an=immer_an)

    def _fremde_sperre(self):
        os.makedirs(os.path.dirname(app_paths.posteingang_sperre_path(self.master)), exist_ok=True)
        zeit = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(app_paths.posteingang_sperre_path(self.master), "w", encoding="utf-8") as f:
            json.dump({"rechner": "PANEL-01", "pid": 1, "seit": zeit, "lebenszeichen": zeit}, f)
        with open(os.path.join(self.posteingang, "scan.pdf"), "wb") as f:
            f.write(b"%PDF-1.4 test")

    def test_pausiert_bei_fremder_ueberwachung(self):
        self._fremde_sperre()
        dienst = self._dienst()
        with patch.object(auto_pilot_service, "STABIL_MINDESTALTER", 0.0), \
                patch("auto_pilot.lies_dokument") as lesen, patch("vollautomatik_fenster.melde") as melde:
            self.assertEqual(dienst.eine_runde(), 0)
        lesen.assert_not_called()
        self.assertIn("fremd", [c.args[1] for c in melde.call_args_list])
        dienst.app.logger.warning.assert_called_once()

    def test_der_dienst_selbst_laesst_sich_nicht_aufhalten(self):
        self._fremde_sperre()
        dienst = self._dienst(immer_an=True)
        with patch.object(dienst, "_fremd_ueberwacht") as gefragt, \
                patch("ollama_client.is_reachable", return_value=False), patch("vollautomatik_fenster.melde"):
            dienst.eine_runde()
        gefragt.assert_not_called()


class TestDienstStart(_Sammlung):
    def test_startet_nicht_wenn_ein_anderer_rechner_ueberwacht(self):
        root = MagicMock()
        einstellungen = MagicMock()
        einstellungen.get.side_effect = lambda k, d=None: self.master if k == "master_folder" else d
        with patch.object(dienstmodus, "Config", return_value=einstellungen), \
                patch.object(dienstmodus, "AppLogger"), patch.object(dienstmodus, "Fehlerfaenger"), \
                patch.object(dienstmodus.posteingang_sperre, "fremd_aktiv", return_value=dict(PANEL, seit="")), \
                patch.object(dienstmodus.messagebox, "showinfo") as meldung, \
                patch.object(dienstmodus, "AutoPilotService") as dienst:
            app = dienstmodus.DienstApp(root)
        self.assertFalse(app.gestartet)
        self.assertIn("PANEL-01", meldung.call_args.args[1])
        dienst.assert_not_called()
        root.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
