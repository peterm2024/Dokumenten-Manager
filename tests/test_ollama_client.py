import json
import unittest
from unittest.mock import patch, MagicMock

import ollama_client


def _fake_response(status=200, body=b""):
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


class TestIsReachable(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_reachable_on_status_200(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(status=200)
        self.assertTrue(ollama_client.is_reachable("http://localhost:11434"))

    @patch("urllib.request.urlopen", side_effect=OSError("connection refused"))
    def test_not_reachable_on_connection_error(self, mock_urlopen):
        self.assertFalse(ollama_client.is_reachable("http://localhost:11434"))


class TestListModels(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_parses_model_names(self, mock_urlopen):
        body = json.dumps({"models": [{"name": "llama3.2-vision"}, {"name": "qwen2.5vl"}]}).encode("utf-8")
        mock_urlopen.return_value = _fake_response(body=body)
        self.assertEqual(ollama_client.list_models(), ["llama3.2-vision", "qwen2.5vl"])

    @patch("urllib.request.urlopen")
    def test_empty_when_no_models(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(body=json.dumps({"models": []}).encode("utf-8"))
        self.assertEqual(ollama_client.list_models(), [])


class TestSuggestTitle(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_returns_cleaned_response_text(self, mock_urlopen):
        body = json.dumps({"response": '  "Beitragsrechnung Kfz-Versicherung"\n'}).encode("utf-8")
        mock_urlopen.return_value = _fake_response(body=body)
        result = ollama_client.suggest_title(b"fake-png-bytes")
        self.assertEqual(result, "Beitragsrechnung Kfz-Versicherung")

    @patch("urllib.request.urlopen")
    def test_sends_base64_image_and_model(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(body=json.dumps({"response": "Titel"}).encode("utf-8"))
        ollama_client.suggest_title(b"\x89PNG..", base_url="http://server:11434", model="qwen2.5vl")

        sent_request = mock_urlopen.call_args[0][0]
        payload = json.loads(sent_request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "qwen2.5vl")
        self.assertEqual(payload["stream"], False)
        self.assertIn("images", payload)
        self.assertEqual(sent_request.full_url, "http://server:11434/api/generate")

    @patch("urllib.request.urlopen", side_effect=OSError("timed out"))
    def test_propagates_connection_errors(self, mock_urlopen):
        with self.assertRaises(OSError):
            ollama_client.suggest_title(b"fake-png-bytes")

    @patch("urllib.request.urlopen")
    def test_schaltet_das_nachdenken_ab(self, mock_urlopen):
        # Denkende Modelle (qwen3.5, gemma4) grübeln sonst vor jeder Antwort minutenlang
        mock_urlopen.return_value = _fake_response(body=json.dumps({"response": "Titel"}).encode("utf-8"))
        ollama_client.suggest_title(b"bild", "http://localhost:11434", model="qwen3.5:9b")
        payload = json.loads(mock_urlopen.call_args[0][0].data.decode("utf-8"))
        self.assertIs(payload["think"], False)


class TestLangsamerModus(unittest.TestCase):
    """KI ohne Grafikkarte (ki_cpu_erlauben): _generate wartet das LANGSAM_FAKTOR-fache."""

    def tearDown(self):
        ollama_client.setze_langsamen_modus(False)

    def test_wirksamer_timeout(self):
        self.assertEqual(ollama_client.wirksamer_timeout(90), 90)
        ollama_client.setze_langsamen_modus(True)
        self.assertTrue(ollama_client.langsamer_modus())
        self.assertEqual(ollama_client.wirksamer_timeout(90), 90 * ollama_client.LANGSAM_FAKTOR)

    @patch("urllib.request.urlopen")
    def test_generate_reicht_verlaengerten_timeout_durch(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(body=json.dumps({"response": "Titel"}).encode("utf-8"))
        ollama_client.suggest_title(b"bild", "http://localhost:11434", timeout=30)
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 30)
        ollama_client.setze_langsamen_modus(True)
        ollama_client.suggest_title(b"bild", "http://localhost:11434", timeout=30)
        self.assertEqual(mock_urlopen.call_args.kwargs["timeout"], 30 * ollama_client.LANGSAM_FAKTOR)


class TestCleanTitle(unittest.TestCase):
    def test_strips_quotes_and_collapses_whitespace(self):
        self.assertEqual(ollama_client._clean_title('  "Titel  mit   Leerzeichen"\n'), "Titel mit Leerzeichen")

    def test_empty_text(self):
        self.assertEqual(ollama_client._clean_title(""), "")


class TestParseTitleAndTags(unittest.TestCase):
    def test_parses_clean_json(self):
        text = '{"title": "Beitragsrechnung Kfz-Versicherung", "tags": ["Versicherung", "Kfz"]}'
        result = ollama_client._parse_title_and_tags(text)
        self.assertEqual(result, {"title": "Beitragsrechnung Kfz-Versicherung", "tags": ["Versicherung", "Kfz"]})

    def test_extracts_json_wrapped_in_markdown_fence(self):
        text = '```json\n{"title": "Kuendigung", "tags": ["Vertrag"]}\n```'
        result = ollama_client._parse_title_and_tags(text)
        self.assertEqual(result, {"title": "Kuendigung", "tags": ["Vertrag"]})

    def test_extracts_json_with_leading_explanation_text(self):
        text = 'Hier ist das Ergebnis:\n{"title": "Rechnung", "tags": []}\nEnde.'
        result = ollama_client._parse_title_and_tags(text)
        self.assertEqual(result, {"title": "Rechnung", "tags": []})

    def test_returns_empty_on_unparseable_response(self):
        self.assertEqual(ollama_client._parse_title_and_tags("Kauderwelsch ohne JSON"), {"title": "", "tags": []})

    def test_missing_tags_key_defaults_to_empty_list(self):
        result = ollama_client._parse_title_and_tags('{"title": "Nur Titel"}')
        self.assertEqual(result, {"title": "Nur Titel", "tags": []})

    def test_non_list_tags_are_ignored(self):
        result = ollama_client._parse_title_and_tags('{"title": "X", "tags": "Versicherung"}')
        self.assertEqual(result, {"title": "X", "tags": []})


class TestGenerateHttpErrorDetail(unittest.TestCase):
    """Regressionstest FALLSTRICKE #29: der Response-BODY eines HTTPError enthält bei Ollama die eigentliche Diagnose und darf nicht verschluckt werden."""

    @patch("urllib.request.urlopen")
    def test_haengt_response_body_an_die_fehlermeldung_an(self, mock_urlopen):
        import urllib.error
        body = b'{"error":"request (4254 tokens) exceeds the available context size (4096 tokens)"}'
        mock_urlopen.side_effect = urllib.error.HTTPError(
            "http://server/api/generate", 400, "Bad Request", {}, MagicMock(read=lambda: body))

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            ollama_client.suggest_title(b"fake-png")

        self.assertIn("exceeds the available context size", str(ctx.exception))


class TestGeschaetzterNumCtx(unittest.TestCase):
    """
    Regressionstest nach echtem Live-Fund (13.07.2026): Ollama lehnte einen
    Vollautomatik-Aufruf mit HTTP 400 'exceed_context_size_error' ab, sobald die
    Ordnerliste der Sammlung (53 Ordner) zusammen mit dem Bild das Standard-
    Kontextfenster (4096 Tokens) überschritt. Gemessen: 4254 Tokens gebraucht.
    """

    def test_liegt_nie_unter_dem_standardwert(self):
        self.assertGreaterEqual(ollama_client._geschaetzter_num_ctx(""), ollama_client.STANDARD_NUM_CTX)

    def test_waechst_mit_der_prompt_laenge(self):
        kurz = ollama_client._geschaetzter_num_ctx("kurzer Prompt")
        lang = ollama_client._geschaetzter_num_ctx("Ordner\n" * 500)
        self.assertGreater(lang, kurz)

    def test_deckt_den_real_gemessenen_bedarf(self):
        """Ein 3662-Zeichen-Prompt (53 Ordner) brauchte real 4254 Tokens - die Schätzung muss darüber liegen."""
        prompt = "x" * 3662
        self.assertGreater(ollama_client._geschaetzter_num_ctx(prompt), 4254)


class TestParseFiling(unittest.TestCase):
    """
    Tests für das Parsen der Vollautomatik-Antwort (Seniorenmodus,
    KONZEPT_SENIORENMODUS.md). KEIN 'zielordner'-Feld mehr - die Ordnerwahl
    übernimmt seit dem Live-Fund (13.07.2026, siehe FALLSTRICKE) deterministischer
    Code (auto_pilot.finde_passenden_ordner), nicht mehr die KI-Antwort.
    """

    def test_parses_vollstaendige_antwort(self):
        text = '{"title": "Beitragsrechnung", "tags": ["Versicherung"], "absender": "Gentilia", "datum": "2026-06-18"}'
        result = ollama_client._parse_filing(text)
        self.assertEqual(result, {
            "title": "Beitragsrechnung", "tags": ["Versicherung"],
            "absender": "Gentilia", "datum": "2026-06-18", "ordnername": "", "empfaenger": "", "objekt": "", "ort": "", "tag_kategorien": {}})

    def test_ordnername_wird_uebernommen(self):
        text = '{"title": "T", "tags": [], "absender": "Dr. Emil Carius", "datum": "2026-06-18", "ordnername": "Carius, Dr. Emil (Zahnarzt)"}'
        self.assertEqual(ollama_client._parse_filing(text)["ordnername"], "Carius, Dr. Emil (Zahnarzt)")

    def test_fehlende_felder_werden_leer(self):
        result = ollama_client._parse_filing('{"title": "Nur Titel"}')
        self.assertEqual(result, {"title": "Nur Titel", "tags": [], "absender": "", "datum": "", "ordnername": "", "empfaenger": "", "objekt": "", "ort": "", "tag_kategorien": {}})

    def test_kauderwelsch_liefert_leere_felder(self):
        result = ollama_client._parse_filing("keine JSON-Antwort")
        self.assertEqual(result, {"title": "", "tags": [], "absender": "", "datum": "", "ordnername": "", "empfaenger": "", "objekt": "", "ort": "", "tag_kategorien": {}})

    def test_empfaenger_wird_uebernommen(self):
        text = '{"title": "T", "tags": [], "absender": "Gentilia", "datum": "", "empfaenger": "Hermann Mustermann"}'
        self.assertEqual(ollama_client._parse_filing(text)["empfaenger"], "Hermann Mustermann")

    def test_null_werte_werden_leere_strings(self):
        result = ollama_client._parse_filing('{"title": "T", "absender": null, "datum": null}')
        self.assertEqual(result["absender"], "")
        self.assertEqual(result["datum"], "")


class TestSuggestFiling(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_prompt_enthaelt_tag_katalog_aber_keine_ordnerliste(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(
            body=json.dumps({"response": '{"title": "T", "tags": ["Kfz"], "absender": "A", '
                                          '"datum": "2026-01-02"}'}).encode("utf-8"))
        result = ollama_client.suggest_filing(b"fake-png", known_tags=["Kfz"])

        sent_request = mock_urlopen.call_args[0][0]
        payload = json.loads(sent_request.data.decode("utf-8"))
        self.assertEqual(payload["format"], "json")
        self.assertIn("num_ctx", payload["options"])
        self.assertIn("Kfz", payload["prompt"])
        self.assertNotIn("Zielordner", payload["prompt"])
        self.assertEqual(result["absender"], "A")

    @patch("urllib.request.urlopen", side_effect=OSError("timed out"))
    def test_verbindungsfehler_wird_weitergereicht(self, mock_urlopen):
        with self.assertRaises(OSError):
            ollama_client.suggest_filing(b"fake-png")


class TestPruefeDublette(unittest.TestCase):
    """KI-Zweitprüfung eines Dubletten-Verdachts (Nutzer-Entscheidung 06.09.2026)."""

    @staticmethod
    def _antworten(*bodies):
        """urlopen-Mock, der nacheinander die übergebenen response-Strings liefert."""
        return [
            _fake_response(body=json.dumps({"response": b}).encode("utf-8")) for b in bodies]

    @patch("urllib.request.urlopen")
    def test_liest_jede_seite_einzeln_und_vergleicht_im_code(self, mock_urlopen):
        """Live-Fund 06.09.2026: Bei zwei Bildern in EINEM Aufruf vermischt das Modell die Dokumente."""
        mock_urlopen.side_effect = self._antworten(
            '{"kennnummer": "RE-4711", "datum": "02.08.2019", "betrag": "58,52"}',
            '{"kennnummer": "RE-4712", "datum": "02.08.2019", "betrag": "58,52"}')
        ergebnis = ollama_client.pruefe_dublette(b"png-neu", b"png-alt")

        self.assertEqual(ergebnis["gleiches_dokument"], "nein")
        self.assertIn("verschiedene Rechnungs-/Kennnummern", ergebnis["begruendung"])
        self.assertEqual(mock_urlopen.call_count, 2)   # kein Zwei-Bilder-Rückfall nötig
        for aufruf in mock_urlopen.call_args_list:
            payload = json.loads(aufruf[0][0].data.decode("utf-8"))
            self.assertEqual(len(payload["images"]), 1)
            self.assertEqual(payload["format"], "json")

    @patch("urllib.request.urlopen")
    def test_rueckfall_auf_zwei_bilder_urteil_ohne_belastbare_felder(self, mock_urlopen):
        mock_urlopen.side_effect = self._antworten(
            '{"kennnummer": "", "datum": "", "betrag": ""}',
            '{"kennnummer": "", "datum": "", "betrag": ""}',
            '{"gleiches_dokument": "nein", "begruendung": "andere Anschrift"}')
        ergebnis = ollama_client.pruefe_dublette(b"png-neu", b"png-alt")

        self.assertEqual(ergebnis, {"gleiches_dokument": "nein", "begruendung": "andere Anschrift"})
        self.assertEqual(mock_urlopen.call_count, 3)
        payload = json.loads(mock_urlopen.call_args_list[2][0][0].data.decode("utf-8"))
        self.assertEqual(len(payload["images"]), 2)
        # num_ctx muss den Token-Batzen BEIDER Bilder abdecken (je ~3300 gemessen)
        self.assertGreaterEqual(payload["options"]["num_ctx"], 2 * 3300)

    def test_parse_normalisiert_antworten(self):
        # Groß-/Kleinschreibung und Zusatz-Leerraum werden vereinheitlicht
        self.assertEqual(
            ollama_client._parse_dubletten_antwort('{"gleiches_dokument": " Ja ", "begruendung": "gleiche\\nNummer"}'),
            {"gleiches_dokument": "ja", "begruendung": "gleiche Nummer"})
        # alles außer klarem ja/nein wird 'unsicher' (fail-safe)
        for kaputt in ('{"gleiches_dokument": "vielleicht"}', "Kauderwelsch ohne JSON", "", None):
            self.assertEqual(ollama_client._parse_dubletten_antwort(kaputt)["gleiches_dokument"],
                             "unsicher", kaputt)

    def test_vergleich_gleiche_kennnummer_und_betrag_ist_dublette(self):
        """Live-Fund 06.09.2026 (Kaminkehrer): dieselbe Rechnung, zweimal gescannt."""
        antwort = ollama_client._vergleiche_dublettenmerkmale(
            {"kennnummer": "2019 00 01886", "betrag": "58,52 €"},
            {"kennnummer": "2019-00-01886", "betrag": "EUR 58,52"})
        self.assertEqual(antwort["gleiches_dokument"], "ja")
        self.assertIn("dieselbe Rechnungs-/Kennnummer", antwort["begruendung"])
        self.assertIn("2019 00 01886", antwort["begruendung"])

    def test_vergleich_gleiche_objektnummer_mit_verschiedenen_betraegen_ist_keine(self):
        """
        Live-Fund 06.09.2026 (Iqua): Alle vier Wohnungs-Abrechnungen tragen dieselbe
        Liegenschaftsnummer - erst der unterschiedliche Betrag entlarvt sie als
        verschiedene Dokumente. Gleiche Nummer allein darf NICHT 'ja' ergeben.
        """
        antwort = ollama_client._vergleiche_dublettenmerkmale(
            {"kennnummer": "5112/5734/2099", "betrag": "1.234,56"},
            {"kennnummer": "5112/5734/2099", "betrag": "987,65"})
        self.assertEqual(antwort["gleiches_dokument"], "nein")
        self.assertIn("verschiedene Beträge", antwort["begruendung"])

    def test_vergleich_verschiedene_kennnummern_sind_keine_dublette(self):
        antwort = ollama_client._vergleiche_dublettenmerkmale(
            {"kennnummer": "RE-4711"}, {"kennnummer": "RE-4712"})
        self.assertEqual(antwort["gleiches_dokument"], "nein")
        self.assertIn("verschiedene Rechnungs-/Kennnummern", antwort["begruendung"])

    def test_vergleich_ohne_belastbare_felder_entscheidet_nicht(self):
        # Kennnummer zu kurz (bloßes Jahr) -> keine Entscheidung
        self.assertIsNone(ollama_client._vergleiche_dublettenmerkmale(
            {"kennnummer": "2019"}, {"kennnummer": "2019"}))
        # gleiche Nummer, aber Beträge nicht lesbar -> ebenfalls keine Entscheidung
        self.assertIsNone(ollama_client._vergleiche_dublettenmerkmale(
            {"kennnummer": "RE-4711", "betrag": ""}, {"kennnummer": "RE 4711", "betrag": ""}))
        self.assertIsNone(ollama_client._vergleiche_dublettenmerkmale({}, None))

    @patch("urllib.request.urlopen", side_effect=OSError("timed out"))
    def test_verbindungsfehler_wird_weitergereicht(self, mock_urlopen):
        with self.assertRaises(OSError):
            ollama_client.pruefe_dublette(b"a", b"b")


class TestSuggestTitleAndTags(unittest.TestCase):
    @patch("urllib.request.urlopen")
    def test_includes_tag_catalog_in_prompt_and_json_format(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(
            body=json.dumps({"response": '{"title": "Titel", "tags": ["Kfz"]}'}).encode("utf-8")
        )
        result = ollama_client.suggest_title_and_tags(b"fake-png", known_tags=["Kfz", "Rechnung"])

        sent_request = mock_urlopen.call_args[0][0]
        payload = json.loads(sent_request.data.decode("utf-8"))
        self.assertEqual(payload["format"], "json")
        self.assertIn("num_ctx", payload["options"])
        self.assertIn("Kfz, Rechnung", payload["prompt"])
        self.assertEqual(result, {"title": "Titel", "tags": ["Kfz"]})

    @patch("urllib.request.urlopen")
    def test_works_without_known_tags(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(
            body=json.dumps({"response": '{"title": "Titel", "tags": []}'}).encode("utf-8")
        )
        result = ollama_client.suggest_title_and_tags(b"fake-png", known_tags=None)
        self.assertEqual(result, {"title": "Titel", "tags": []})

    @patch("urllib.request.urlopen")
    def test_includes_style_examples_in_prompt(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(
            body=json.dumps({"response": '{"title": "Titel", "tags": []}'}).encode("utf-8")
        )
        ollama_client.suggest_title_and_tags(
            b"fake-png", style_examples=["Beitragsrechnung Gentilia", "Versicherungsmahnung Mustermann"]
        )
        sent_request = mock_urlopen.call_args[0][0]
        prompt = json.loads(sent_request.data.decode("utf-8"))["prompt"]
        self.assertIn("Beitragsrechnung Gentilia", prompt)
        self.assertIn("Versicherungsmahnung Mustermann", prompt)

    @patch("urllib.request.urlopen")
    def test_no_style_block_without_examples(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(
            body=json.dumps({"response": '{"title": "Titel", "tags": []}'}).encode("utf-8")
        )
        ollama_client.suggest_title_and_tags(b"fake-png", style_examples=None)
        sent_request = mock_urlopen.call_args[0][0]
        prompt = json.loads(sent_request.data.decode("utf-8"))["prompt"]
        self.assertNotIn("Bereits vergebene Titel anderer Dokumente", prompt)


class TestSuggestCleanedText(unittest.TestCase):
    def test_empty_input_returns_empty_without_request(self):
        with patch("urllib.request.urlopen") as mock_urlopen:
            self.assertEqual(ollama_client.suggest_cleaned_text(""), "")
            self.assertEqual(ollama_client.suggest_cleaned_text("   "), "")
            mock_urlopen.assert_not_called()

    @patch("urllib.request.urlopen")
    def test_returns_stripped_response_text(self, mock_urlopen):
        body = json.dumps({"response": "  Bereinigter Text.\n"}).encode("utf-8")
        mock_urlopen.return_value = _fake_response(body=body)
        result = ollama_client.suggest_cleaned_text("Rohr Text mit Feheler")
        self.assertEqual(result, "Bereinigter Text.")

    @patch("urllib.request.urlopen")
    def test_sends_raw_text_in_prompt_no_json_format(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(body=json.dumps({"response": "X"}).encode("utf-8"))
        ollama_client.suggest_cleaned_text("Roher OCR-Text", base_url="http://server:11434", model="qwen2.5vl")

        sent_request = mock_urlopen.call_args[0][0]
        payload = json.loads(sent_request.data.decode("utf-8"))
        self.assertEqual(payload["model"], "qwen2.5vl")
        self.assertIn("Roher OCR-Text", payload["prompt"])
        self.assertNotIn("format", payload)  # Freitext-Antwort, kein JSON-Modus
        self.assertNotIn("images", payload)  # reiner Textaufruf, kein Bild
        self.assertEqual(sent_request.full_url, "http://server:11434/api/generate")

    @patch("urllib.request.urlopen", side_effect=OSError("timed out"))
    def test_propagates_connection_errors(self, mock_urlopen):
        with self.assertRaises(OSError):
            ollama_client.suggest_cleaned_text("Text")


class TestGpuStatus(unittest.TestCase):
    """gpu_status (12.09.2026): stiller CPU-Betrieb nach Treiber-Mismatch wird erkannt."""

    def _ps(self, name, size, vram):
        return {name: {"size": size, "size_vram": vram}}

    @patch("ollama_client._generate")
    @patch("ollama_client.geladene_modelle")
    def test_cpu_wenn_kein_vram(self, mock_ps, mock_gen):
        mock_ps.return_value = self._ps("qwen2.5vl:7b", 10_800_000_000, 0)
        status, details = ollama_client.gpu_status("http://x", "qwen2.5vl:7b")
        self.assertEqual(status, "cpu")
        self.assertIn("0 GB im Grafikspeicher", details)
        mock_gen.assert_not_called()   # Modell war schon geladen

    @patch("ollama_client._generate")
    @patch("ollama_client.geladene_modelle")
    def test_gpu_und_teilweise(self, mock_ps, mock_gen):
        mock_ps.return_value = self._ps("qwen2.5vl:7b", 5_500_000_000, 5_500_000_000)
        self.assertEqual(ollama_client.gpu_status("http://x", "qwen2.5vl:7b")[0], "gpu")
        mock_ps.return_value = self._ps("qwen2.5vl:7b", 10_000_000_000, 4_000_000_000)
        self.assertEqual(ollama_client.gpu_status("http://x", "qwen2.5vl:7b")[0], "teilweise")

    @patch("ollama_client._generate")
    @patch("ollama_client.geladene_modelle")
    def test_laedt_modell_bei_bedarf_und_matcht_tag(self, mock_ps, mock_gen):
        mock_ps.side_effect = [{}, self._ps("qwen2.5vl:latest", 5_000_000_000, 5_000_000_000)]
        status, _ = ollama_client.gpu_status("http://x", "qwen2.5vl")
        self.assertEqual(status, "gpu")
        mock_gen.assert_called_once()
        self.assertEqual(mock_gen.call_args[0][0]["model"], "qwen2.5vl")

    @patch("ollama_client.geladene_modelle", side_effect=OSError("kaputt"))
    def test_unbekannt_bei_fehler(self, _mock_ps):
        status, details = ollama_client.gpu_status("http://x", "m")
        self.assertEqual(status, "unbekannt")
        self.assertIn("kaputt", details)

    @patch("ollama_client.urllib.request.urlopen")
    def test_geladene_modelle_parst_ps(self, mock_urlopen):
        body = json.dumps({"models": [{"name": "qwen2.5vl:7b", "size": 10, "size_vram": 0}]}).encode()
        mock_urlopen.return_value = _fake_response(200, body)
        self.assertEqual(ollama_client.geladene_modelle("http://x"), {"qwen2.5vl:7b": {"size": 10, "size_vram": 0}})


if __name__ == "__main__":
    unittest.main()


class TestTagKategorien(unittest.TestCase):
    """Aufgabe 8 (Kategorie neuer Tags) - nur mit Kategorien im Prompt, robust geparst."""

    def test_parse_tag_kategorien(self):
        r = ollama_client._parse_filing('{"title": "T", "tags": ["Strom"], "tag_kategorien": {"Strom": "Thema", "": "x", "Leer": null}}')
        self.assertEqual(r["tag_kategorien"], {"Strom": "Thema"})

    def test_parse_ohne_oder_kaputte_kategorien(self):
        self.assertEqual(ollama_client._parse_filing('{"title": "T"}')["tag_kategorien"], {})
        self.assertEqual(ollama_client._parse_filing('{"title": "T", "tag_kategorien": ["Liste"]}')["tag_kategorien"], {})

    def test_prompt_enthaelt_kategorien_nur_wenn_vorhanden(self):
        with patch("ollama_client._generate", return_value={"response": "{}"}) as gen:
            ollama_client.suggest_filing(b"png", known_tags=["Kfz"], kategorien=["Dokument", "Thema"])
            prompt = gen.call_args[0][0]["prompt"]
            self.assertIn("Aufgabe 8", prompt)
            self.assertIn("Aufgabe 6 - Empfänger", prompt)
            self.assertIn("Dokument, Thema", prompt)
        with patch("ollama_client._generate", return_value={"response": "{}"}) as gen:
            ollama_client.suggest_filing(b"png", known_tags=["Kfz"])
            self.assertNotIn("Aufgabe 8", gen.call_args[0][0]["prompt"])


class TestWaehleOrdner(unittest.TestCase):
    """Zweitmeinung zur Ordnerwahl über /v1/systemone (Modell-Prüfstand 27.10.2026)."""

    @patch("urllib.request.urlopen")
    def test_fragt_jeden_ordner_einzeln_und_liefert_rangliste(self, mock_urlopen):
        antwort = {"answers": {"o000": {"noul": 0.12}, "o001": {"noul": 0.97}, "o002": {"noul": 0.4}}}
        mock_urlopen.return_value = _fake_response(body=json.dumps(antwort).encode("utf-8"))
        ordner = ["A - B - C/Gentilia", "S - T - U/Stadtwerke", "_Anderes"]
        rangliste = ollama_client.waehle_ordner(b"bild", ordner, "http://server:11434", model="clef-flash:9b")

        self.assertEqual(rangliste, [("S - T - U/Stadtwerke", 0.97), ("_Anderes", 0.4), ("A - B - C/Gentilia", 0.12)])
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "http://server:11434/v1/systemone")
        payload = json.loads(req.data.decode("utf-8"))
        self.assertEqual(payload["model"], "clef-flash:9b")
        self.assertEqual(len(payload["images"]), 1)
        # Gefragt wird mit dem letzten Pfadteil, nicht mit der Buchstabengruppe
        self.assertIn("„Stadtwerke“", payload["questions"]["o001"]["instructions"])
        self.assertEqual(payload["questions"]["o001"]["type"], "noul")

    @patch("urllib.request.urlopen")
    def test_fehlende_antworten_zaehlen_als_null(self, mock_urlopen):
        mock_urlopen.return_value = _fake_response(body=json.dumps({"answers": {}}).encode("utf-8"))
        self.assertEqual(ollama_client.waehle_ordner(b"bild", ["X"]), [("X", 0.0)])

    def test_ohne_ordner_keine_anfrage(self):
        self.assertEqual(ollama_client.waehle_ordner(b"bild", []), [])


class TestTagRegelImPrompt(unittest.TestCase):
    """Tag-Wildwuchs 27.10.2026: der Prompt darf keine eigenen Wortformen vorgeben, die der Katalog nicht hat."""

    def test_keine_langformen_als_beispiel(self):
        for vorlage in (ollama_client.FILING_PROMPT_TEMPLATE, ollama_client.TITLE_AND_TAGS_PROMPT_TEMPLATE):
            tag_aufgabe = vorlage[vorlage.index("Aufgabe 2"):]
            tag_aufgabe = tag_aufgabe[:tag_aufgabe.find("Aufgabe 3")]  # Titel-Beispiele dürfen Langformen haben
            self.assertNotIn("Gebäudebrandversicherung", tag_aufgabe)
            self.assertNotIn("Hausratversicherung", tag_aufgabe)
            self.assertIn(ollama_client.TAG_FORM_REGEL, tag_aufgabe)

    def test_personen_und_objekte_haben_eigene_felder(self):
        self.assertIn("gehören NICHT in die Tags", ollama_client.FILING_PROMPT_TEMPLATE)
