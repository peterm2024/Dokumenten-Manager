"""Tests für die Versionsprüfung gegen die GitHub-Releases (versionspruefung.py, 14.09.2026)."""

import json
import unittest
from unittest.mock import MagicMock, patch

import versionspruefung
from versionspruefung import parse_version, vergleiche, hole_neueste, pruefe


def _antwort(body):
    resp = MagicMock()
    resp.read.return_value = json.dumps(body).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestVersionen(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_version("v0.9.17"), (0, 9, 17))
        self.assertEqual(parse_version("0.9.17 (Build 2026-09-13)"), (0, 9, 17))
        self.assertEqual(parse_version("1.0"), (1, 0, 0))
        self.assertIsNone(parse_version("Beta"))

    def test_vergleiche(self):
        self.assertEqual(vergleiche("0.9.17", "v0.9.18"), "neuer")
        self.assertEqual(vergleiche("0.9.17", "v0.10.0"), "neuer")
        self.assertEqual(vergleiche("0.9.17", "v0.9.17"), "aktuell")
        self.assertEqual(vergleiche("0.9.18", "v0.9.17"), "voraus")
        with self.assertRaises(ValueError):
            vergleiche("0.9.17", "kaputt")


class TestHoleNeueste(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_liest_tag_url_und_notizen(self, urlopen):
        urlopen.return_value = _antwort({"tag_name": "v0.9.18", "html_url": "https://x/rel", "body": " Neu \n"})
        n = hole_neueste()
        self.assertEqual(n, {"version": "0.9.18", "url": "https://x/rel", "notizen": "Neu"})
        req = urlopen.call_args[0][0]
        self.assertEqual(req.full_url, versionspruefung.API_URL)
        self.assertIn("User-agent", req.headers)

    def test_404_und_limit_in_klartext(self):
        import urllib.error
        for code, wort in ((404, "nicht erreichbar"), (403, "Anfragelimit")):
            fehler = urllib.error.HTTPError(versionspruefung.API_URL, code, "x", {}, None)
            with patch("urllib.request.urlopen", side_effect=fehler):
                with self.assertRaises(OSError) as cm:
                    hole_neueste()
            self.assertIn(wort, str(cm.exception))

    @patch("urllib.request.urlopen")
    def test_ohne_versionsnummer_fehler(self, urlopen):
        urlopen.return_value = _antwort({"message": "rate limit"})
        with self.assertRaises(ValueError):
            hole_neueste()


class TestPruefe(unittest.TestCase):
    def setUp(self):
        self.app = MagicMock()
        self.app.root.after.side_effect = lambda ms, fn: fn()
        self.oeffne = MagicMock()

    def _lauf(self, still, hole, **dialoge):
        with patch("versionspruefung.messagebox.askyesno", return_value=dialoge.get("ja", False)) as frage, \
                patch("versionspruefung.messagebox.showinfo") as info, \
                patch("versionspruefung.messagebox.showwarning") as warnung, \
                patch("versionspruefung.threading.Thread", side_effect=lambda target, **k: MagicMock(start=target)):
            pruefe(self.app, still=still, aktuell="0.9.17", hole=hole, oeffne=self.oeffne)
        return frage, info, warnung

    def test_neuere_version_fragt_und_oeffnet_browser(self):
        hole = lambda: {"version": "0.9.18", "url": "https://x/rel", "notizen": "Fehlerfänger"}
        frage, info, warnung = self._lauf(True, hole, ja=True)
        frage.assert_called_once()
        self.assertIn("0.9.18", frage.call_args[0][1])
        self.assertIn("installiert: 0.9.17", frage.call_args[0][1])
        self.assertIn("Fehlerfänger", frage.call_args[0][1])
        self.oeffne.assert_called_once_with("https://x/rel")
        info.assert_not_called()
        self.assertIn("neuer", str(self.app.logger.info.call_args))

    def test_nein_oeffnet_nichts(self):
        frage, _i, _w = self._lauf(False, lambda: {"version": "0.9.18", "url": "u", "notizen": ""}, ja=False)
        frage.assert_called_once()
        self.oeffne.assert_not_called()

    def test_aktuell_still_ohne_fenster_laut_mit_info(self):
        hole = lambda: {"version": "0.9.17", "url": "u", "notizen": ""}
        frage, info, warnung = self._lauf(True, hole)
        frage.assert_not_called(); info.assert_not_called(); warnung.assert_not_called()
        frage, info, warnung = self._lauf(False, hole)
        info.assert_called_once()
        self.assertIn("ist die neueste", info.call_args[0][1])

    def test_entwicklungsversion(self):
        _f, info, _w = self._lauf(False, lambda: {"version": "0.9.16", "url": "u", "notizen": ""})
        self.assertIn("Entwicklungsversion", info.call_args[0][1])

    def test_netzfehler_still_nur_log_laut_warnung(self):
        def kaputt():
            raise OSError("kein Netz")
        frage, info, warnung = self._lauf(True, kaputt)
        warnung.assert_not_called()
        self.assertIn("nicht möglich", str(self.app.logger.info.call_args))
        frage, info, warnung = self._lauf(False, kaputt)
        warnung.assert_called_once()
        self.assertIn("kein Netz", warnung.call_args[0][1])
        self.assertIn(versionspruefung.RELEASES_URL, warnung.call_args[0][1])

    def test_notizen_ohne_markdown(self):
        self.assertEqual(versionspruefung.ohne_markdown("## Neu\n\n**Fett** und `code`\n"), "Neu\n\nFett und code")
        frage, _i, _w = self._lauf(False, lambda: {"version": "0.9.18", "url": "u", "notizen": "## Neu in v0.9.18\n**Fehler**"})
        self.assertNotIn("##", frage.call_args[0][1])
        self.assertNotIn("**", frage.call_args[0][1])
        self.assertIn("Neu in v0.9.18", frage.call_args[0][1])

    def test_lange_notizen_gekuerzt(self):
        notizen = "\n".join(f"Zeile {i} " + "x" * 40 for i in range(40))
        frage, _i, _w = self._lauf(False, lambda: {"version": "0.9.18", "url": "u", "notizen": notizen})
        text = frage.call_args[0][1]
        self.assertLess(len(text), 800)
        self.assertIn("…", text)


if __name__ == "__main__":
    unittest.main()
