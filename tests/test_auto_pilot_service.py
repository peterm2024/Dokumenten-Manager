"""
Tests für die Watchdog-Vollautomatik (auto_pilot_service.py, Seniorenmodus Schritt 4).
Der Dienst wird ohne Thread über eine_runde() geprüft; KI-Aufruf und Ausführung sind
gepatcht, das Dateisystem ist ein echter Temp-Ordner.
"""

import os
import shutil
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import app_paths
import auto_pilot_service
from auto_pilot_service import AutoPilotService


def _entscheidung(pfad, sicher=True):
    return {
        "pdf_path": pfad, "titel": "Rechnung", "titel_korrekturen": [], "tags": ["Rechnung"],
        "datum": "2026-06-18", "absender": "Gentilia", "ordnername": "Gentilia",
        "zielordner": "Gentilia", "ordner_neu": False, "ordner_per_alias": False, "ordner_hinweis": "",
        "neuer_dateiname": "20260618_Rechnung.pdf" if sicher else "", "sicher": sicher,
        "probleme": [] if sicher else ["kein plausibles Dokumentdatum erkannt"],
    }


class _analyse:
    """
    Ersetzt Lesen und Entscheiden der Vollautomatik (Stapelbetrieb je Modell: lies_dokument und
    entscheide_gelesen statt analysiere_dokument). side_effect wie früher bei analysiere_dokument:
    eine Exception scheitert beim Lesen, eine Funktion (pfad, known_tags, ordnerliste) liefert die
    Entscheidung. `with` liefert den Lese-Mock (ein Aufruf je gelesenem Dokument); mehrfach betretbar
    wie patch().
    """

    def __init__(self, side_effect=None):
        self.fehler = side_effect if isinstance(side_effect, BaseException) else None
        self.entscheide = (side_effect if callable(side_effect) and self.fehler is None
                           else (lambda pfad, *a: _entscheidung(pfad)))

    def _entscheide_gelesen(self, gelesen, ordnerliste, *a, **k):
        known_tags = a[3] if len(a) > 3 else k.get("known_tags")
        return self.entscheide(gelesen["pdf_path"], known_tags, ordnerliste)

    def __enter__(self):
        self._stapel = ExitStack()
        lesen = self._stapel.enter_context(patch(
            "auto_pilot.lies_dokument", side_effect=self.fehler or (lambda pfad, *a, **k: {
                "pdf_path": pfad, "png": b"png", "schreibschutz": None, "ki_antwort": {}})))
        self._stapel.enter_context(patch("auto_pilot.entscheide_gelesen", side_effect=self._entscheide_gelesen))
        return lesen

    def __exit__(self, *exc):
        return self._stapel.__exit__(*exc)


class TestAutoPilotService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.master = os.path.join(self.tmp, "KID")
        self.posteingang = os.path.join(self.master, "0_Posteingang")
        os.makedirs(self.posteingang)
        os.makedirs(os.path.join(self.master, "Gentilia"))

        self.app = MagicMock()
        self.app.master_folder = self.master
        self.config = {"auto_pilot_enabled": True}
        self.app.config.get.side_effect = lambda k, d=None: self.config.get(k, d)
        self.app.root.after.side_effect = lambda ms, fn: fn()  # Hauptthread-Aufrufe sofort ausführen
        self.app.tag_manager.get_known_tags.return_value = ["Rechnung"]
        self.app.tag_manager.tags_in_kategorie.return_value = []
        self.app.index_manager.wortschatz_der_sammlung.return_value = {}
        # Ohne explizite Vorgaben wären die MagicMock-Attribute "truthy" und jede
        # Datei gälte als "wird gerade bearbeitet" (Schutz vom 06.09.2026).
        self.app.current_preview_path = None
        self.app.save_manager.hat_offene_aenderung.return_value = False
        self.dienst = AutoPilotService(self.app)

        # Stabilitäts-Wartezeit im Test auf null, damit frisch angelegte Dateien sofort "fertig" sind
        patcher = patch.object(auto_pilot_service, "STABIL_MINDESTALTER", 0.0)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Grafikkarten-Pruefung (FALLSTRICKE #67) im Test: Modell liegt im Grafikspeicher
        self.gpu = patch("ollama_client.gpu_status", return_value=("gpu", "5,5 GB im Grafikspeicher"))
        self.gpu.start()
        self.addCleanup(self.gpu.stop)

    def _lege_pdf(self, name="scan.pdf"):
        pfad = os.path.join(self.posteingang, name)
        with open(pfad, "wb") as f:
            f.write(b"%PDF-1.4 test")
        return pfad

    def _patch_pipeline(self, sicher=True, erfolg=True):
        analyse = _analyse(lambda pfad, *a: _entscheidung(pfad, sicher))
        ausfuehren = patch("auto_pilot.fuehre_entscheidung_aus",
                           return_value={"erfolg": erfolg, "neuer_pfad": os.path.join(self.master, "Gentilia", "x.pdf"),
                                         "fehler": None if erfolg else "kaputt"})
        erreichbar = patch("ollama_client.is_reachable", return_value=True)
        return analyse, ausfuehren, erreichbar

    def test_ausgeschaltet_tut_nichts(self):
        self.config["auto_pilot_enabled"] = False
        self._lege_pdf()
        a, b, c = self._patch_pipeline()
        with a as analyse, b, c:
            self.assertEqual(self.dienst.eine_runde(), 0)
            analyse.assert_not_called()

    def test_verarbeitet_stabile_datei_und_protokolliert(self):
        pfad = self._lege_pdf()
        a, b, c = self._patch_pipeline()
        with a as analyse, b as ausfuehren, c:
            self.assertEqual(self.dienst.eine_runde(), 1)
        analyse.assert_called_once()
        self.assertEqual(analyse.call_args[0][0], pfad)
        # still=True: nie eine Messagebox aus dem Hintergrund-Thread
        self.assertTrue(ausfuehren.call_args.kwargs.get("still"))
        self.assertEqual(self.dienst.verarbeitet, 1)
        self.app.tool_manager.notify_file_moved.assert_called_once()
        with open(app_paths.protokoll_path(self.master), encoding="utf-8") as f:
            protokoll = f.read()
        self.assertIn("abgelegt  scan.pdf", protokoll)

    def test_datei_mit_offener_eingabe_wird_uebersprungen(self):
        """
        Live-Fund 06.09.2026: Der Dienst verschob die im Hauptfenster angezeigte
        Posteingang-Datei, während der Nutzer dort Titel/Tags tippte - das Auto-Save
        schrieb dann ins Leere. Bei offener, ungespeicherter Eingabe zu genau dieser
        Datei wird sie deshalb nicht angefasst.
        """
        pfad = self._lege_pdf()
        self.app.current_preview_path = pfad
        self.app.save_manager.hat_offene_aenderung.return_value = True
        a, b, c = self._patch_pipeline()
        with a as analyse, b, c:
            self.assertEqual(self.dienst.eine_runde(), 0)
            analyse.assert_not_called()
        # nach dem Speichern (bzw. Weiterklicken) holt die nächste Runde die Datei nach
        self.app.save_manager.hat_offene_aenderung.return_value = False
        with a as analyse, b, c:
            self.assertEqual(self.dienst.eine_runde(), 1)
            analyse.assert_called_once()

    def test_nur_angezeigte_datei_ohne_eingabe_wird_verarbeitet(self):
        """
        Nutzerfund 06.09.2026 direkt nach dem ersten Fix: Beim Öffnen des Posteingangs
        selektiert das Hauptfenster das erste Dokument automatisch - bloßes Anzeigen
        darf die Vollautomatik NICHT blockieren ("findet mein Dokument nicht").
        """
        pfad = self._lege_pdf()
        self.app.current_preview_path = pfad   # angezeigt, aber keine offene Eingabe
        a, b, c = self._patch_pipeline()
        with a as analyse, b, c:
            self.assertEqual(self.dienst.eine_runde(), 1)
            analyse.assert_called_once()

    def test_unsicher_wird_im_protokoll_begruendet(self):
        self._lege_pdf()
        a, b, c = self._patch_pipeline(sicher=False)
        with a, b, c:
            self.dienst.eine_runde()
        with open(app_paths.protokoll_path(self.master), encoding="utf-8") as f:
            self.assertIn("unsicher  scan.pdf", f.read())

    def _fertig_meldungen(self, sicher):
        """Führt eine Runde aus und liefert die 'fertig'-Meldungen ans Statusfenster."""
        self._lege_pdf()
        a, b, c = self._patch_pipeline(sicher=sicher)
        with a, b, c, patch.object(auto_pilot_service.vollautomatik_fenster, "melde") as melde:
            self.dienst.eine_runde()
        return [aufruf.kwargs for aufruf in melde.call_args_list if aufruf.args[1] == "fertig"]

    def test_statusfenster_bekommt_zielordner(self):
        """Das Fenster soll anzeigen, WOHIN einsortiert wurde (Nutzerwunsch 31.08.2026)."""
        fertig = self._fertig_meldungen(sicher=True)
        self.assertEqual(len(fertig), 1)
        self.assertEqual(fertig[0]["ziel"], os.path.join("Gentilia", "x.pdf"))
        self.assertEqual(fertig[0]["grund"], "")

    def test_statusfenster_bekommt_grund_bei_unsicher(self):
        fertig = self._fertig_meldungen(sicher=False)
        self.assertEqual(len(fertig), 1)
        self.assertIn("kein plausibles Dokumentdatum", fertig[0]["grund"])

    def test_dublette_im_zielordner_macht_die_ablage_unsicher(self):
        """
        Stufe B der Dubletten-Erkennung: Liegt im Zielordner schon dasselbe Dokument,
        wird NICHT abgelegt, sondern nach 0_Unsicher gereicht (Nutzerwunsch 30.08.2026:
        eine stille Verdopplung im Bestand faellt sonst erst Jahre spaeter auf).
        """
        self._lege_pdf()
        a, b, c = self._patch_pipeline(sicher=True)
        treffer = (os.path.join(self.master, "Gentilia", "alt.pdf"), "Text zu 97% gleich (gleiches Datum)")
        with a, b as ausfuehren, c, patch("dubletten_pruefung.finde_dublette", return_value=treffer):
            self.dienst.eine_runde()
        entscheidung = ausfuehren.call_args[0][0]
        self.assertFalse(entscheidung["sicher"])
        self.assertIn("Dublette", entscheidung["probleme"][0])
        self.assertEqual(entscheidung["dublette_zu"], treffer[0])
        with open(app_paths.protokoll_path(self.master), encoding="utf-8") as f:
            protokoll = f.read()
        self.assertIn("unsicher  scan.pdf", protokoll)
        self.assertIn("Dublette", protokoll)

    def test_dubletten_pruefung_faellt_nicht_auf_die_nase(self):
        """Ein Fehler in der Pruefung darf die Ablage nicht verhindern (nur Log-Eintrag)."""
        self._lege_pdf()
        a, b, c = self._patch_pipeline(sicher=True)
        with a, b, c, patch("dubletten_pruefung.finde_dublette", side_effect=OSError("Laufwerk weg")):
            self.assertEqual(self.dienst.eine_runde(), 1)

    def test_noch_wachsende_datei_wird_uebersprungen(self):
        pfad = self._lege_pdf()
        with patch.object(auto_pilot_service, "STABIL_MINDESTALTER", 3600.0):
            a, b, c = self._patch_pipeline()
            with a as analyse, b, c:
                self.assertEqual(self.dienst.eine_runde(), 0)
                analyse.assert_not_called()
        self.assertTrue(os.path.exists(pfad))

    def test_unfertige_datei_fuehrt_zu_kurzer_wartezeit(self):
        # Release-Check T0.13: ohne Nachprüfen wartete eine frisch gescannte Datei ~60 s
        self.assertEqual(self.dienst.naechste_wartezeit(), auto_pilot_service.PRUEF_INTERVALL)
        self._lege_pdf()
        with patch.object(auto_pilot_service, "STABIL_MINDESTALTER", 3600.0):
            a, b, c = self._patch_pipeline()
            with a, b, c:
                self.dienst.eine_runde()
        self.assertEqual(self.dienst.naechste_wartezeit(), auto_pilot_service.NACHPRUEFEN_NACH)
        self.assertLess(auto_pilot_service.NACHPRUEFEN_NACH, 10)
        a, b, c = self._patch_pipeline()
        with a, b, c:
            self.dienst.eine_runde()   # jetzt fertig -> wieder das normale Intervall
        self.assertEqual(self.dienst.naechste_wartezeit(), auto_pilot_service.PRUEF_INTERVALL)

    def test_leere_datei_gilt_nicht_als_fertig(self):
        open(os.path.join(self.posteingang, "leer.pdf"), "wb").close()
        a, b, c = self._patch_pipeline()
        with a as analyse, b, c:
            self.dienst.eine_runde()
            analyse.assert_not_called()

    def test_server_weg_nur_ein_logeintrag_und_dateien_bleiben(self):
        self._lege_pdf()
        with patch("ollama_client.is_reachable", return_value=False), \
                _analyse() as analyse:
            self.dienst.eine_runde()
            self.dienst.eine_runde()
            analyse.assert_not_called()
        self.assertEqual(self.app.logger.warning.call_count, 1)
        # Wieder erreichbar: Info-Eintrag und Verarbeitung
        a, b, c = self._patch_pipeline()
        with a, b, c:
            self.assertEqual(self.dienst.eine_runde(), 1)
        self.assertTrue(any("wieder erreichbar" in str(c) for c in self.app.logger.info.call_args_list))

    def test_server_weg_steht_einmal_im_protokoll_und_entwarnung(self):
        """Betatest 25.10.2026: Ausfall stand nur im technischen Log - Angehörige sahen nicht, warum Post lag."""
        self._lege_pdf()
        with patch("ollama_client.is_reachable", return_value=False):
            self.dienst.eine_runde()
            self.dienst.eine_runde()
        protokoll = app_paths.protokoll_path(self.master)
        with open(protokoll, encoding="utf-8") as f:
            self.assertEqual(f.read().count("WARNUNG   KI-Server nicht erreichbar"), 1)
        a, b, c = self._patch_pipeline()
        with a, b, c:
            self.dienst.eine_runde()
        with open(protokoll, encoding="utf-8") as f:
            self.assertEqual(f.read().count("OK        KI-Server wieder erreichbar"), 1)

    def test_cpu_betrieb_pausiert_und_meldet_einmal(self):
        """FALLSTRICKE #67: Server erreichbar, Modell aber nicht im Grafikspeicher -> nichts anfassen, einmal warnen."""
        self._lege_pdf()
        a, b, c = self._patch_pipeline()
        with a as analyse, b, c, patch("ollama_client.gpu_status", return_value=("cpu", "0 GB im Grafikspeicher")):
            self.assertEqual(self.dienst.eine_runde(), 0)
            self.assertEqual(self.dienst.eine_runde(), 0)
            analyse.assert_not_called()
        self.assertEqual(self.app.logger.warning.call_count, 1)
        self.assertIn("ohne Grafikkarte", str(self.app.logger.warning.call_args))
        protokoll = app_paths.protokoll_path(self.master)
        with open(protokoll, encoding="utf-8") as f:
            inhalt = f.read()
        self.assertEqual(inhalt.count("WARNUNG   KI-Server rechnet ohne Grafikkarte"), 1)
        # Grafikkarte wieder da: Verarbeitung laeuft, Entwarnung im Log und Protokoll
        with a, b, c:
            self.assertEqual(self.dienst.eine_runde(), 1)
        self.assertTrue(any("wieder auf der Grafikkarte" in str(k) for k in self.app.logger.info.call_args_list))
        with open(protokoll, encoding="utf-8") as f:
            self.assertIn("OK        KI-Server rechnet wieder auf der Grafikkarte", f.read())

    def test_cpu_betrieb_zugelassen_verarbeitet_mit_einem_hinweis(self):
        """Einstellung ki_cpu_erlauben (Beta-Vorbereitung 13.09.2026): kein Pausieren, ein HINWEIS statt WARNUNG."""
        self.config["ki_cpu_erlauben"] = True
        self._lege_pdf("a.pdf")
        a, b, c = self._patch_pipeline()
        with a as analyse, b, c, patch("ollama_client.gpu_status", return_value=("cpu", "0 GB im Grafikspeicher")):
            self.assertEqual(self.dienst.eine_runde(), 1)
            self._lege_pdf("b.pdf")
            # gepatchtes Verschieben laesst a.pdf liegen -> Runde 2 verarbeitet beide
            self.assertGreaterEqual(self.dienst.eine_runde(), 1)
            self.assertGreaterEqual(analyse.call_count, 2)
        self.app.logger.warning.assert_not_called()
        hinweise = [str(k) for k in self.app.logger.info.call_args_list if "zugelassen" in str(k)]
        self.assertEqual(len(hinweise), 1)
        with open(app_paths.protokoll_path(self.master), encoding="utf-8") as f:
            inhalt = f.read()
        self.assertEqual(inhalt.count("HINWEIS   KI-Server rechnet ohne Grafikkarte"), 1)
        self.assertNotIn("WARNUNG   KI-Server rechnet ohne Grafikkarte", inhalt)
        # Grafikkarte wieder da: Entwarnung genau einmal
        self._lege_pdf("c.pdf")
        with a, b, c:
            self.assertGreaterEqual(self.dienst.eine_runde(), 1)
        with open(app_paths.protokoll_path(self.master), encoding="utf-8") as f:
            self.assertEqual(f.read().count("OK        KI-Server rechnet wieder auf der Grafikkarte"), 1)

    def test_teilweise_und_unbekannt_bremsen_nicht(self):
        for status in ("teilweise", "unbekannt"):
            self._lege_pdf(f"scan_{status}.pdf")
            a, b, c = self._patch_pipeline()
            with a, b, c, patch("ollama_client.gpu_status", return_value=(status, "?")):
                self.assertGreaterEqual(self.dienst.eine_runde(), 1)   # gepatchtes Verschieben laesst die Datei liegen
        self.app.logger.warning.assert_not_called()

    def test_fehler_bei_analyse_wird_nicht_in_dauerschleife_wiederholt(self):
        pfad = self._lege_pdf()
        with patch("ollama_client.is_reachable", return_value=True), \
                _analyse(RuntimeError("Remote end closed")) as analyse, \
                patch("auto_pilot.fuehre_entscheidung_aus") as ausfuehren:
            self.assertEqual(self.dienst.eine_runde(), 0)
            self.assertEqual(self.dienst.eine_runde(), 0)
            self.assertEqual(analyse.call_count, 1)  # zweite Runde: Datei ist erst in 10 min wieder fällig
            ausfuehren.assert_not_called()
        self.assertTrue(os.path.exists(pfad))
        self.assertGreater(self.dienst._naechster_versuch[pfad], time.monotonic())

    def test_fehlgeschlagene_ablage_landet_im_protokoll(self):
        self._lege_pdf()
        a, b, c = self._patch_pipeline(erfolg=False)
        with a, b, c:
            self.assertEqual(self.dienst.eine_runde(), 0)
        with open(app_paths.protokoll_path(self.master), encoding="utf-8") as f:
            self.assertIn("FEHLER    scan.pdf", f.read())

    def test_pause_bei_offenem_vorschaufenster(self):
        self._lege_pdf()
        self.dienst.pausieren()
        a, b, c = self._patch_pipeline()
        with a as analyse, b, c:
            self.assertEqual(self.dienst.eine_runde(), 0)
            analyse.assert_not_called()
            self.dienst.fortsetzen()
            self.assertEqual(self.dienst.eine_runde(), 1)

    def test_neuer_ordner_zaehlt_in_derselben_runde_als_vorhanden(self):
        self._lege_pdf("a.pdf")
        self._lege_pdf("b.pdf")
        gesehene_listen = []

        def analyse(pfad, known_tags, ordnerliste, *a, **k):
            gesehene_listen.append(list(ordnerliste))
            e = _entscheidung(pfad)
            e.update(zielordner="Telenetz", ordner_neu=True)
            return e

        with patch("ollama_client.is_reachable", return_value=True), \
                _analyse(analyse), \
                patch("auto_pilot.fuehre_entscheidung_aus",
                      return_value={"erfolg": True, "neuer_pfad": os.path.join(self.master, "Telenetz", "x.pdf"), "fehler": None}):
            self.assertEqual(self.dienst.eine_runde(), 2)
        self.assertNotIn("Telenetz", gesehene_listen[0])
        self.assertIn("Telenetz", gesehene_listen[1])

    def test_unsicher_vorgeschlagener_ordner_zaehlt_nicht_als_vorhanden(self):
        # Nachtlauf 28.10.2026: der nie angelegte Ordner stand in der Liste -> 15x "existiert nicht mehr"
        self._lege_pdf("a.pdf")
        self._lege_pdf("b.pdf")
        gesehene_listen = []

        def analyse(pfad, known_tags, ordnerliste, *a, **k):
            gesehene_listen.append(list(ordnerliste))
            e = _entscheidung(pfad)
            e.update(zielordner="Telenetz", ordner_neu=True, sicher=False, probleme=["Ähnlicher Ordner vorhanden: x"])
            return e

        with patch("ollama_client.is_reachable", return_value=True), \
                _analyse(analyse), \
                patch("auto_pilot.fuehre_entscheidung_aus",
                      return_value={"erfolg": True, "neuer_pfad": os.path.join(self.master, "0_Unsicher", "x.pdf"),
                                    "fehler": None}):
            self.assertEqual(self.dienst.eine_runde(), 2)
        self.assertNotIn("Telenetz", gesehene_listen[1])

    def _protokolliere_phasen(self):
        """Patcht Lesen, Zweitmeinung und Ablage so, dass jeder Aufruf in self.phasen landet."""
        self.phasen = []
        self.config["ki_entscheidungsmodell"] = "clef-flash:9b"

        def lesen(pfad, *a, **k):
            self.phasen.append(("lesen", os.path.basename(pfad)))
            return {"pdf_path": pfad, "png": b"png", "schreibschutz": None, "ki_antwort": {}}

        def zweitmeinung(gelesen, *a, **k):
            name = os.path.basename(gelesen["pdf_path"])
            self.phasen.append(("zweit", name))
            return [("Rangliste " + name, 0.9)]

        def entscheide(gelesen, *a, **k):
            if "rangliste" in k:   # Phase 3 (Phase 2 fragt nur vorab, ob eine Zweitmeinung nötig ist)
                self.phasen.append(("ablage", os.path.basename(gelesen["pdf_path"]), k["rangliste"]))
            return _entscheidung(gelesen["pdf_path"])

        stapel = ExitStack()
        stapel.enter_context(patch("ollama_client.is_reachable", return_value=True))
        stapel.enter_context(patch("auto_pilot.lies_dokument", side_effect=lesen))
        stapel.enter_context(patch("auto_pilot.hole_zweitmeinung", side_effect=zweitmeinung))
        stapel.enter_context(patch("auto_pilot.entscheide_gelesen", side_effect=entscheide))
        stapel.enter_context(patch("auto_pilot.fuehre_entscheidung_aus", return_value={
            "erfolg": True, "neuer_pfad": os.path.join(self.master, "Gentilia", "x.pdf"), "fehler": None}))
        return stapel

    def test_stapel_erst_lesen_dann_zweitmeinungen_dann_ablegen(self):
        # Stapelbetrieb je Modell (28.10.2026): Lese- und Entscheidungsmodell wechseln nicht mehr je Dokument
        for name in ("a.pdf", "b.pdf", "c.pdf"):
            self._lege_pdf(name)
        with self._protokolliere_phasen():
            self.assertEqual(self.dienst.eine_runde(), 3)
        arten = [p[0] for p in self.phasen]
        self.assertEqual(arten, ["lesen"] * 3 + ["zweit"] * 3 + ["ablage"] * 3)
        # Phase 3 bekommt die vorab geholte Rangliste des jeweiligen Dokuments
        self.assertEqual([p[2] for p in self.phasen if p[0] == "ablage"],
                         [[("Rangliste " + n, 0.9)] for n in ("a.pdf", "b.pdf", "c.pdf")])

    def test_stapel_grenze(self):
        for name in ("a.pdf", "b.pdf", "c.pdf"):
            self._lege_pdf(name)
        with self._protokolliere_phasen(), patch.object(auto_pilot_service, "STAPEL_GROESSE", 2):
            self.assertEqual(self.dienst.eine_runde(), 3)
        self.assertEqual([p[0] for p in self.phasen],
                         ["lesen", "lesen", "zweit", "zweit", "ablage", "ablage", "lesen", "zweit", "ablage"])

    def test_stapel_veraltete_zweitmeinung_bei_neuem_ordner_neu_holen(self):
        # Messlauf 28.10.2026: Dokument 1 legt "Versicherungskasse Musterland" an, Dokument 3 sicher
        # "Bayerische Vers.kammer" - dessen Zweitmeinung stammte von vor dem ersten neuen Ordner
        for name in ("a.pdf", "b.pdf", "c.pdf"):
            self._lege_pdf(name)
        ziele = {"a.pdf": ("Versicherungskasse Musterland", True), "b.pdf": ("Bayerische Vers.kammer", True),
                 "c.pdf": ("Gentilia", False)}
        with self._protokolliere_phasen():
            def entscheide(gelesen, *a, **k):
                name = os.path.basename(gelesen["pdf_path"])
                if "rangliste" in k:
                    self.phasen.append(("ablage", name, k["rangliste"]))
                e = _entscheidung(gelesen["pdf_path"])
                e.update(zielordner=ziele[name][0], ordner_neu=ziele[name][1])
                return e
            with patch("auto_pilot.entscheide_gelesen", side_effect=entscheide):
                self.assertEqual(self.dienst.eine_runde(), 3)
        ablage = {p[1]: p[2] for p in self.phasen if p[0] == "ablage"}
        self.assertIsNotNone(ablage["a.pdf"])   # erster neuer Ordner: Zweitmeinung ist aktuell
        self.assertIsNone(ablage["b.pdf"])      # zweiter neuer Ordner: mit aktueller Liste neu fragen
        self.assertIsNotNone(ablage["c.pdf"])   # vorhandener Ordner: vorab geholte bleibt

    def test_stapel_ohne_entscheidungsmodell_keine_zweitmeinung(self):
        self._lege_pdf("a.pdf")
        with self._protokolliere_phasen():
            self.config["ki_entscheidungsmodell"] = ""
            self.assertEqual(self.dienst.eine_runde(), 1)
        self.assertEqual([p[0] for p in self.phasen], ["lesen", "ablage"])
        self.assertIsNone(self.phasen[1][2])

    def test_hauptthread_timeout_liefert_none_statt_zu_haengen(self):
        self.app.root.after.side_effect = lambda ms, fn: None  # Hauptthread antwortet nie
        with patch.object(auto_pilot_service, "HAUPTTHREAD_TIMEOUT", 0.01):
            self.assertIsNone(self.dienst._vom_hauptthread(lambda: 42))

    def test_start_meldet_sich_beim_waechter_an_und_stop_beendet_thread(self):
        self.config["auto_pilot_enabled"] = False
        self.dienst.start()
        self.app.monitor.add_listener.assert_called_once_with(self.dienst.on_filesystem_event)
        self.assertTrue(self.dienst._thread.is_alive())
        self.dienst.stop()
        self.assertFalse(self.dienst._thread.is_alive())

    def test_erste_runde_gleich_nach_dem_start(self):
        """Betatest 25.10.2026: vorher wartete der Dienst nach dem Start erst PRUEF_INTERVALL (60 s)."""
        gelaufen = threading.Event()
        with patch.object(auto_pilot_service, "RUHEZEIT_NACH_EREIGNIS", 0.01), \
                patch.object(auto_pilot_service, "PRUEF_INTERVALL", 3600.0), \
                patch.object(self.dienst, "eine_runde", side_effect=lambda: gelaufen.set()):
            self.dienst.start()
            try:
                self.assertTrue(gelaufen.wait(2.0))
            finally:
                self.dienst.stop()


class TestFolderMonitorListener(unittest.TestCase):
    def test_dispatch_ruft_callback_und_zuhoerer_auf_fehler_stoppen_nicht(self):
        from folder_monitor import FolderMonitor
        haupt = MagicMock()
        zuhoerer = MagicMock()
        monitor = FolderMonitor(haupt)
        monitor.add_listener(lambda: 1 / 0)
        monitor.add_listener(zuhoerer)
        monitor.add_listener(zuhoerer)  # doppelt anmelden -> einmal aufrufen
        monitor._dispatch()
        haupt.assert_called_once()
        zuhoerer.assert_called_once()
        monitor.remove_listener(zuhoerer)
        monitor._dispatch()
        zuhoerer.assert_called_once()


if __name__ == "__main__":
    unittest.main()
