import unittest
from unittest.mock import MagicMock, patch

import preview_manager
from preview_manager import PreviewManager

class TestPreviewManager(unittest.TestCase):
    def setUp(self):
        # Fake-App (GUI) erstellen
        self.mock_app = MagicMock()
        
        # Standardwerte simulieren
        self.mock_app.current_preview_path = "dummy_path.pdf"
        self.mock_app.custom_zoom = 1.0
        
        # --- FIX: Canvas-Mathematik simulieren ---
        self.mock_app.canvas_preview.winfo_width.return_value = 800
        self.mock_app.canvas_preview.winfo_height.return_value = 900
        self.mock_app.canvas_preview.bbox.return_value = (0, 0, 800, 1200) # x1, y1, x2, y2
        self.mock_app.canvas_preview.canvasx.return_value = 100.0
        self.mock_app.canvas_preview.canvasy.return_value = 100.0

        self.manager = PreviewManager(self.mock_app)

    @patch('pdf_handler.PDFHandler.get_preview_image')
    def test_performance_cache_prevents_re_render(self, mock_get_preview):
        """Testet, ob der Cache teure Doppel-Renders bei gleichen Parametern blockiert."""
        # Wir tun so, als würde das Rendern klappen. Das Fake-Bild braucht width()/height(),
        # weil die Vorschau die Seite inzwischen zentriert platziert.
        mock_photo = MagicMock()
        mock_photo.width.return_value = 752
        mock_photo.height.return_value = 1063
        mock_get_preview.return_value = (mock_photo, 100, 5, 0)
        
        # 1. Erster Aufruf: Das PDF muss zwingend gerendert werden
        self.manager.update_preview()
        self.assertEqual(mock_get_preview.call_count, 1)
        
        # 2. Zweiter Aufruf (mit exakt denselben Parametern!): 
        # Der Cache MUSS greifen, es darf kein neues Rendering angefordert werden
        self.manager.update_preview()
        self.assertEqual(mock_get_preview.call_count, 1) # Bleibt bei 1!

        # 3. Dritter Aufruf: Wir ändern den Zoom -> Jetzt muss neu gerendert werden
        self.mock_app.custom_zoom = 1.5
        self.manager.update_preview()
        self.assertEqual(mock_get_preview.call_count, 2) # Steigt auf 2!

    @patch('pdf_handler.PDFHandler.get_preview_image')
    def test_clears_canvas_when_switching_to_undisplayable_document(self, mock_get_preview):
        """
        Regressionstest: get_preview_image liefert None bei nicht darstellbaren PDFs
        (z.B. passwortgeschützt, siehe KONZEPT_PDF_ARTEN.md). Ohne expliziten
        Fehler-Zweig blieb der Canvas-Inhalt des VORHERIGEN Dokuments stehen, obwohl
        bereits ein anderes (nicht darstellbares) Dokument ausgewählt war.
        """
        mock_photo = MagicMock()
        mock_photo.width.return_value = 752
        mock_photo.height.return_value = 1063
        mock_get_preview.return_value = (mock_photo, 100, 5, 0)
        self.manager.update_preview()  # erstes, erfolgreich gerendertes Dokument

        self.mock_app.canvas_preview.delete.reset_mock()
        self.mock_app.root.title.reset_mock()
        self.mock_app.base_title = "KID v0.9.4"  # Vorschau-Info steht seit 31.08.2026 in der Titelleiste
        mock_get_preview.return_value = None
        self.mock_app.current_preview_path = "geschuetzt.pdf"

        self.manager.update_preview()

        self.mock_app.canvas_preview.delete.assert_called_once_with("all")
        self.assertIsNone(self.mock_app.photo_preview)
        titel = self.mock_app.root.title.call_args[0][0]
        self.assertIn("Keine Vorschau", titel)
        self.assertIn("KID v0.9.4", titel)

    @patch('pdf_handler.PDFHandler.get_preview_image')
    def test_leere_vorschau_erlaubt_erneutes_rendern_desselben_dokuments(self, mock_get_preview):
        """
        Regressionstest (FALLSTRICKE #43, Nutzerfund 31.08.2026): Ordner mit Dokument
        anklicken, dann einen LEEREN Ordner, dann wieder denselben — das Dokument wurde
        nicht mehr angezeigt. Ursache: der leere Ordner löschte nur den Canvas, der
        Performance-Cache hielt das Dokument weiter für "schon gezeichnet".
        """
        mock_photo = MagicMock()
        mock_photo.width.return_value = 752
        mock_photo.height.return_value = 1063
        mock_get_preview.return_value = (mock_photo, 100, 5, 0)

        self.manager.update_preview()                    # Dokument im Ordner "ADAC"
        self.assertEqual(mock_get_preview.call_count, 1)

        self.manager.leere_vorschau()                    # leerer Ordner dazwischen
        self.assertIsNone(self.mock_app.current_preview_path)
        self.mock_app.canvas_preview.delete.assert_called_with("all")

        self.mock_app.current_preview_path = "dummy_path.pdf"   # wieder dasselbe Dokument
        self.manager.update_preview()
        self.assertEqual(mock_get_preview.call_count, 2, "Dokument müsste erneut gerendert werden")

    @patch('pdf_handler.PDFHandler.get_preview_image')
    def test_verwerfe_cache_erzwingt_neuzeichnen(self, mock_get_preview):
        """Nach einer Inhaltsänderung (z.B. PDF-Editor) muss dasselbe Dokument neu gezeichnet werden."""
        mock_photo = MagicMock()
        mock_photo.width.return_value = 752
        mock_photo.height.return_value = 1063
        mock_get_preview.return_value = (mock_photo, 100, 5, 0)

        self.manager.update_preview()
        self.manager.update_preview()
        self.assertEqual(mock_get_preview.call_count, 1)

        self.manager.verwerfe_cache()
        self.manager.update_preview()
        self.assertEqual(mock_get_preview.call_count, 2)

    def test_zoom_limits(self):
        """Testet den Schutz vor dem 45GB-RAM-Overflow (Limit auf 500% bzw. 5.0)."""
        # Fake Mouse-Event (Delta > 0 bedeutet reinzoomen)
        mock_event = MagicMock()
        mock_event.delta = 120 
        mock_event.x = 100
        mock_event.y = 100
        
        # Wir erzwingen einen absurden Zoom-Wert vor dem Event
        self.mock_app.custom_zoom = 4.8 
        
        # Wir rufen das Mausrad-Event mehrmals auf, um über 5.0 zu kommen
        with patch.object(self.manager, 'update_preview'): # Rendern blockieren für den Test
            self.manager.on_zoom_mousewheel(mock_event) # 4.8 * 1.1 = 5.28 -> Gekappt auf 5.0
            self.manager.on_zoom_mousewheel(mock_event) # 5.0 * 1.1 = 5.5 -> Gekappt auf 5.0
            
        # Der Zoom darf 5.0 NIEMALS überschreiten!
        self.assertLessEqual(self.mock_app.custom_zoom, 5.0, "FATAL: Zoom-Limit durchbrochen!")

    def test_mausrad_blaettert_auch_mit_fokus_im_eingabefeld(self):
        """Release-Check 28.10.2026: die Datums-Automatik setzt den Fokus ins Datumsfeld - das
        Mausrad über der Vorschau muss trotzdem blättern (die Fokus-Sperre gilt nur für Pfeiltasten)."""
        self.mock_app.root.focus_get.return_value = preview_manager.ttk.Entry.__new__(preview_manager.ttk.Entry)
        self.mock_app.canvas_preview.yview.return_value = (0.0, 1.0)   # Seite passt ganz ins Fenster
        self.manager.total_pages = 2
        event = MagicMock(delta=-120, num=None)
        with patch.object(self.manager, '_blaettere_gleitend') as gleiten:
            self.manager.on_preview_mousewheel(event)
        gleiten.assert_called_once_with(1, ans_ende=False)

    def test_mausrad_nach_dem_blaettern_beginnt_oben_auf_der_neuen_seite(self):
        """FALLSTRICKE #116, Release-Check 07.11.2026: Bei Zoom scrollten die Rad-Rasten direkt nach dem
        Seitenwechsel schon in die neue Seite hinein (auch während sie noch hereinglitt) - man landete
        mitten auf der Seite statt an ihrem Anfang."""
        c = self.mock_app.canvas_preview
        self.manager.total_pages = 3
        runter = MagicMock(delta=-120, num=None)
        c.yview.return_value = (0.4, 1.0)                 # gezoomt, am Ende von Seite 1
        with patch.object(self.manager, '_blaettere_gleitend') as gleiten:
            self.manager.on_preview_mousewheel(runter)    # erste Raste am Rand: nur bewaffnen
            self.manager._end_cooldown()                  # 400 ms später
            self.manager.on_preview_mousewheel(runter)    # zweite Raste: blättert
            gleiten.assert_called_once_with(1, ans_ende=False)
            c.yview.return_value = (0.0, 0.6)             # neue Seite, oben
            self.manager.on_preview_mousewheel(runter)    # Rad dreht im Schwung weiter
            self.manager.on_preview_mousewheel(runter)
        c.yview_scroll.assert_not_called()
        self.manager._nachlauf_ende()                     # Sperre vorbei: Rad scrollt wieder
        self.manager.on_preview_mousewheel(runter)
        c.yview_scroll.assert_called_once_with(2, "units")

    def test_nachlauf_sperre_abschaltbar(self):
        """Peter 07.11.2026: „nicht jeder will diese Pause haben“ - Einstellung vorschau_nachlauf (Standard an)."""
        c = self.mock_app.canvas_preview
        self.mock_app.config.get.side_effect = lambda k, d=None: False if k == preview_manager.EINSTELLUNG_NACHLAUF else d
        self.manager.total_pages = 3
        runter = MagicMock(delta=-120, num=None)
        c.yview.return_value = (0.4, 1.0)
        with patch.object(self.manager, '_blaettere_gleitend'):
            self.manager.on_preview_mousewheel(runter)
            self.manager._end_cooldown()
            self.manager.on_preview_mousewheel(runter)    # blättert, ohne Sperre
            c.yview.return_value = (0.0, 0.6)
            self.manager.on_preview_mousewheel(runter)    # scrollt sofort weiter
        c.yview_scroll.assert_called_once_with(2, "units")

    def test_mausrad_rueckwaerts_beginnt_am_ende_der_vorigen_seite(self):
        """FALLSTRICKE #116, Peter 07.11.2026: Rückwärts geblättert muss die vorige Seite an ihrem Ende
        stehen, wie beim fortlaufenden Scrollen - nicht an ihrem Anfang."""
        c = self.mock_app.canvas_preview
        self.manager.total_pages = 3
        self.manager.current_page = 1
        hoch = MagicMock(delta=120, num=None)
        c.yview.return_value = (0.0, 0.6)                 # gezoomt, oben auf Seite 2
        with patch.object(self.manager, 'update_preview'):
            self.manager.on_preview_mousewheel(hoch)      # Rand: bewaffnen
            self.manager._end_cooldown()
            self.manager.on_preview_mousewheel(hoch)      # blättert zurück
        self.assertEqual(self.manager.current_page, 0)
        c.yview_moveto.assert_called_with(1.0)

    def test_zwischenbild_haelt_den_punkt_unter_der_maus(self):
        """FALLSTRICKE #117: Der Ausschnitt des Rohbilds, der beim Zoomen sofort gestreckt gezeigt wird, muss den Punkt
        unter dem Mauszeiger an derselben Bildschirmstelle lassen."""
        f = preview_manager.zwischenbild_ausschnitt
        gross = dict(bild_breite=2000, bild_hoehe=3000, rand=16)
        links, oben, rechts, unten = f(ix=400, iy=600, sx=100, sy=200, breite=800, hoehe=900, faktor=2.0, **gross)
        self.assertAlmostEqual(rechts - links, 400)                      # 800 Pixel Fenster / Faktor 2
        self.assertAlmostEqual(unten - oben, 450)
        # Punkt (400, 600) des Rohbilds landet nach dem Strecken bei (100, 200) im Fenster
        self.assertAlmostEqual((400 - links) * 2.0, 100)
        self.assertAlmostEqual((600 - oben) * 2.0, 200)
        self.assertEqual(f(10, 20, 10, 20, 800, 900, 1.0, **gross), (0, 0, 800, 900))   # Faktor 1: unverändert

    def test_zwischenbild_bleibt_in_den_bildlaufgrenzen(self):
        """FALLSTRICKE #117, Messung 07.11.2026: Stand die Maus unter der Vorschau, zeigte das Zwischenbild grauen Rand
        unter der Seite, das scharfe Bild darf aber nicht über das Seitenende scrollen - es saß 115 px tiefer."""
        f = preview_manager.zwischenbild_ausschnitt
        # Rohbild 1000 x 1400 bei Zoom 1, Ziel Zoom 2 (Bild 2000 x 2800), Fenster 800 x 700; Punkt kurz vor dem
        # Seitenende, Maus oben im Fenster: ungebremst reichte die Ansicht bis 3180, unter die Seite
        links, oben, rechts, unten = f(ix=500, iy=1390, sx=400, sy=300, breite=800, hoehe=700, faktor=2.0,
                                       bild_breite=1000, bild_hoehe=1400, rand=16)
        self.assertAlmostEqual(unten * 2.0, 2800 + 16)                   # unten endet die Ansicht am Rand unter der Seite
        self.assertAlmostEqual((unten - oben) * 2.0, 700)
        # Der Schatten steckt rechts und unten in der Scrollregion, das scharfe Bild reicht also 4 px weiter
        _l, _o, _r, unten = f(ix=500, iy=1390, sx=400, sy=300, breite=800, hoehe=700, faktor=2.0,
                              bild_breite=1000, bild_hoehe=1400, rand=16, schatten=4)
        self.assertAlmostEqual(unten * 2.0, 2800 + 4 + 16)
        # Seite schmaler als das Fenster: mittig wie in update_preview
        links, _o, rechts, _u = f(ix=100, iy=100, sx=0, sy=0, breite=800, hoehe=700, faktor=1.0,
                                  bild_breite=300, bild_hoehe=2000, rand=16)
        self.assertAlmostEqual(links + rechts, 300)                      # Mitte des Ausschnitts = Mitte der Seite

    def test_zoom_zeigt_sofort_ein_zwischenbild_und_zeichnet_spaeter_scharf(self):
        """FALLSTRICKE #117, Peter 07.11.2026: Zoomen „grenzwertig träge“ - jede Raste zeichnete nach 40 ms die ganze
        Seite neu. Jetzt kommt sofort ein gestreckter Ausschnitt, scharf erst, wenn das Rad ruht."""
        from PIL import Image
        c = self.mock_app.canvas_preview
        foto = MagicMock()
        foto.roh, foto.zoom = Image.new("RGB", (800, 1100), "white"), 1.0
        self.mock_app.photo_preview = foto
        c.coords.return_value = [416, 16]                 # Seite anchor "n": Mitte oben
        c.winfo_pointerx.return_value, c.winfo_rootx.return_value = 500, 100
        c.winfo_pointery.return_value, c.winfo_rooty.return_value = 400, 100
        c.winfo_rgb.return_value = (0x8f8f, 0x8f8f, 0x8f8f)
        with patch("preview_manager.ImageTk.PhotoImage") as tk_bild, patch.object(self.manager, "_apply_zoom") as scharf:
            self.manager.on_zoom_mousewheel(MagicMock(delta=120, x=400, y=300))
        scharf.assert_not_called()                        # nicht sofort neu rendern
        zwischen = tk_bild.call_args.args[0]
        self.assertEqual(zwischen.size, (800, 900))       # so groß wie die Vorschau
        self.assertTrue(any(k.kwargs.get("tags") == ("zwischen",) for k in c.create_image.call_args_list))
        verzoegerung = c.after.call_args.args[0]
        self.assertGreaterEqual(verzoegerung, 120)        # scharf erst, wenn das Rad ruht
        self.assertIs(c.after.call_args.args[1], scharf)

    def test_zwischenbild_zeigt_den_schatten_der_seite(self):
        """Peter 07.11.2026: Zoomen „flackert bzw. wackelt“ - das Zwischenbild hatte keinen Schatten, der dunkle Rand
        rechts und unter der Seite verschwand bei jeder Raste und kam beim Scharfwerden zurück."""
        from PIL import Image
        c = self.mock_app.canvas_preview
        foto = MagicMock()
        foto.roh, foto.zoom = Image.new("RGB", (300, 400), "white"), 1.0
        self.mock_app.photo_preview = foto
        c.coords.return_value = [400, 250]
        c.winfo_rgb.return_value = (0x8f8f, 0x8f8f, 0x8f8f)
        with patch("preview_manager.ImageTk.PhotoImage") as tk_bild:
            self.manager._zeige_zwischenbild(1.1)
        bild = tk_bild.call_args.args[0]
        # Seite 330 x 440 passt ins Fenster 800 x 900, steht also mittig: x 235..565, y 230..670
        schatten = (0x55, 0x55, 0x55)
        self.assertEqual(bild.getpixel((567, 450)), schatten)      # rechts neben der Seite
        self.assertEqual(bild.getpixel((450, 672)), schatten)      # unter der Seite
        self.assertEqual(bild.getpixel((567, 231)), (0x8f, 0x8f, 0x8f))   # oben rechts versetzt, wie beim scharfen Bild
        self.assertEqual(bild.getpixel((400, 450)), (255, 255, 255))

    @patch('pdf_handler.PDFHandler.get_preview_image')
    def test_zwischenbild_bleibt_bis_das_scharfe_bild_steht(self, mock_get_preview):
        """Peter 07.11.2026: Nach dem Zoomen erschien beim Scharfwerden kurz das alte Bild an alter Stelle - _apply_zoom
        entfernte das Zwischenbild, dann ließ update_preview beim Phasenstart einmal zeichnen (aktivitaet.phase)."""
        c = self.mock_app.canvas_preview
        geloescht_beim_zeichnen = []

        def zeichnet(*_a, **_k):
            geloescht_beim_zeichnen.extend(k.args for k in c.delete.call_args_list)
            foto = MagicMock()
            foto.width.return_value, foto.height.return_value = 900, 1300
            return (foto, 120, 5, 0)

        mock_get_preview.side_effect = zeichnet
        c.winfo_pointerx.return_value = c.winfo_rootx.return_value = 0
        c.winfo_pointery.return_value = c.winfo_rooty.return_value = 0
        c.cget.return_value = "0 0 900 1300"
        self.manager._target_zoom = 1.2
        c.delete.reset_mock()
        self.manager._apply_zoom()
        self.assertTrue(mock_get_preview.called)
        self.assertNotIn(("zwischen",), geloescht_beim_zeichnen)   # während des Zeichnens liegt es noch obenauf
        self.assertIn(("zwischen",), [k.args for k in c.delete.call_args_list])   # danach ist es weg

    @patch('pdf_handler.PDFHandler.get_preview_image')
    def test_zoom_zeichnet_kein_zwischenbild_an_der_alten_stelle(self, mock_get_preview):
        """FALLSTRICKE #116, Release-Check 07.11.2026: Strg+Mausrad flackerte - update_idletasks zwischen
        Neuzeichnen und Verschieben brachte das neue Bild einmal an der alten Stelle auf den Schirm."""
        mock_photo = MagicMock()
        mock_photo.width.return_value = 900
        mock_photo.height.return_value = 1300
        mock_get_preview.return_value = (mock_photo, 120, 5, 0)
        c = self.mock_app.canvas_preview
        c.winfo_pointerx.return_value = c.winfo_rootx.return_value = 0
        c.winfo_pointery.return_value = c.winfo_rooty.return_value = 0
        c.cget.return_value = "0 0 900 1300"
        self.manager._target_zoom = 1.2
        self.mock_app.root.reset_mock()
        c.reset_mock(return_value=False)
        self.manager._apply_zoom()
        aufrufe = [n for n, _a, _k in c.mock_calls + self.mock_app.root.mock_calls]
        self.assertIn("yview_moveto", aufrufe)
        self.assertFalse([n for n in aufrufe if n in ("update_idletasks", "update")], aufrufe)

class TestScrolleistenHysterese(unittest.TestCase):
    """FALLSTRICKE #49: eine einzelne Schwelle liess die Leiste an der Grenzbreite endlos flattern."""

    def test_zustand_bleibt_in_der_grauzone(self):
        f = preview_manager.scrolleiste_soll_sichtbar_sein
        # sichtbar + Seite passt knapp (Grauzone) -> bleibt sichtbar
        self.assertTrue(f(True, 970, 1000, auto_fit=True))
        # sichtbar + passt mit deutlichem Abstand -> darf weg
        self.assertFalse(f(True, 950, 1000, auto_fit=True))
        # ausgeblendet + kein Ueberstand -> bleibt weg (auch in der Grauzone)
        self.assertFalse(f(False, 990, 1000, auto_fit=True))
        # ausgeblendet + echter Ueberstand -> kommt wieder
        self.assertTrue(f(False, 1001, 1000, auto_fit=True))

    def test_keine_endlosschleife_im_breiten_autofit(self):
        """Simuliert die Rueckkopplung: Ausblenden verbreitert den Canvas, die Seite waechst mit."""
        f = preview_manager.scrolleiste_soll_sichtbar_sein
        hoehe, leiste, aspekt = 1000, 18, 1.414  # A4 hochkant
        for start_breite in range(500, 1200, 7):
            sichtbar = True
            wechsel = 0
            for _ in range(6):
                breite = start_breite - (leiste if sichtbar else 0)
                inhalt = int(breite * aspekt)
                neu = f(sichtbar, inhalt, hoehe, auto_fit=True)
                if neu != sichtbar:
                    wechsel += 1
                    sichtbar = neu
            self.assertLessEqual(wechsel, 1, f"Flattern bei Breite {start_breite}")

    def test_fester_zoom_reagiert_direkt(self):
        f = preview_manager.scrolleiste_soll_sichtbar_sein
        self.assertFalse(f(True, 995, 1000, auto_fit=False))   # passt -> weg, kleiner Puffer reicht
        self.assertTrue(f(False, 1001, 1000, auto_fit=False))


class TestSuchtrefferInVorschau(unittest.TestCase):
    """Vorschau springt bei aktiver Suche zur Trefferseite und meldet Treffer in der Titelzeile (11.09.2026)."""

    def setUp(self):
        from search_manager import SearchManager
        self.mock_app = MagicMock()
        self.mock_app.current_preview_path = "dummy_path.pdf"
        self.mock_app.custom_zoom = 1.0
        self.mock_app.canvas_preview.winfo_width.return_value = 800
        self.mock_app.canvas_preview.winfo_height.return_value = 900
        self.mock_app.canvas_preview.bbox.return_value = (0, 0, 800, 1200)
        self.mock_app.entry_search.get.return_value = "plesche"
        self.mock_app.search_manager = SearchManager(self.mock_app)
        self.mock_app.search_manager._angezeigt = ("plesche", "", "", ())   # mit Return abgeschickte Suche
        self.manager = PreviewManager(self.mock_app)
        self.photo = MagicMock()
        self.photo.width.return_value = 752
        self.photo.height.return_value = 1063

    @patch('pdf_handler.PDFHandler.finde_treffer_seite', return_value=2)
    @patch('pdf_handler.PDFHandler.get_preview_image')
    def test_springt_zur_trefferseite_und_uebergibt_begriffe(self, mock_get_preview, mock_seite):
        mock_get_preview.return_value = (self.photo, 100, 5, 2)
        self.manager.update_preview()
        mock_seite.assert_called_once()
        self.assertEqual(mock_seite.call_args[0][1], ["plesche"])
        kwargs = mock_get_preview.call_args.kwargs
        self.assertEqual(kwargs["start_page"], 2)
        self.assertEqual(kwargs["highlight_terms"], ["plesche"])
        self.mock_app.base_title = "Dokumenten-Manager"
        self.manager.update_preview()   # Cache greift -> kein neuer Render, aber Titel bleibt gesetzt
        titel = self.mock_app.root.title.call_args[0][0]
        self.assertIn("Seite 3 von 5", titel)
        self.assertIn("plesche", titel)

    @patch('pdf_handler.PDFHandler.finde_treffer_seite', return_value=None)
    @patch('pdf_handler.PDFHandler.get_preview_image')
    def test_geaenderter_suchtext_rendert_neu(self, mock_get_preview, mock_seite):
        """Die Suchbegriffe gehören zum Cache-Zustand: neuer Text -> neue Markierung."""
        mock_get_preview.return_value = (self.photo, 100, 1, 0)
        self.manager.update_preview()
        self.manager.update_preview()
        self.assertEqual(mock_get_preview.call_count, 1)
        self.mock_app.search_manager._angezeigt = ("kfz", "", "", ())
        self.manager.update_preview()
        self.assertEqual(mock_get_preview.call_count, 2)
        self.assertEqual(mock_seite.call_count, 1)   # Seitensprung nur beim Dokumentwechsel

    def test_treffer_hinweis(self):
        self.assertEqual(PreviewManager.treffer_hinweis([], 0, None), "")
        self.assertIn("2 Treffer für „plesche kfz\"", PreviewManager.treffer_hinweis(["plesche", "kfz"], 2, 1))
        self.assertIn("auf Seite 3", PreviewManager.treffer_hinweis(["plesche"], 0, 2))
        self.assertIn("nicht im Seitentext", PreviewManager.treffer_hinweis(["plesche"], 0, None))


class TestBlaetternOhneGrau(unittest.TestCase):
    """Seitenwechsel: neue Seite direkt unter/über der alten, gleitet ohne Leerlauf ein (25.10.2026)."""

    def test_vorwaerts_liegt_neue_seite_unter_der_alten(self):
        # alte Seite oben 24, 1000 hoch; neue wurde bei 24 gezeichnet -> nach unten unter die alte
        self.assertEqual(PreviewManager.blaetter_versatz(24, 1000, 24, 1000, 1, 24), 1024)

    def test_rueckwaerts_liegt_neue_seite_ueber_der_alten(self):
        self.assertEqual(PreviewManager.blaetter_versatz(24, 1000, 24, 900, -1, 24), -924)

    def test_gleitschritte_summe_und_auslauf(self):
        for strecke in (-1024, 924, 7, 0):
            schritte = PreviewManager.gleit_schritte(strecke, 14)
            self.assertEqual(len(schritte), 14)
            self.assertEqual(sum(schritte), strecke)
        schritte = [abs(x) for x in PreviewManager.gleit_schritte(-1024, 14)]
        self.assertGreater(schritte[0], schritte[-1])   # schnell an, weich aus
        self.assertEqual(schritte, sorted(schritte, reverse=True))


class TestDokumentLeiste(unittest.TestCase):
    """Bildlaufleiste der Vorschau über das ganze Dokument (Nutzerwunsch 25.10.2026)."""

    def test_anteil_im_dokument(self):
        self.assertEqual(preview_manager.dokument_anteil(2, 6, 0.0, 1.0), (2 / 6, 3 / 6))
        oben, unten = preview_manager.dokument_anteil(0, 4, 0.5, 0.75)   # in Seite 1 hineingezoomt
        self.assertAlmostEqual(oben, 0.125)
        self.assertAlmostEqual(unten, 0.1875)
        self.assertEqual(preview_manager.dokument_anteil(0, 0, 0.2, 0.6), (0.2, 0.6))   # ohne Seitenzahl wie bisher

    def test_ziel_aus_anteil(self):
        self.assertEqual(preview_manager.ziel_aus_anteil(0.0, 6), (0, 0.0))
        seite, innen = preview_manager.ziel_aus_anteil(0.5, 6)
        self.assertEqual(seite, 3)
        self.assertAlmostEqual(innen, 0.0)
        seite, innen = preview_manager.ziel_aus_anteil(0.45, 4)
        self.assertEqual(seite, 1)
        self.assertAlmostEqual(innen, 0.8)
        self.assertEqual(preview_manager.ziel_aus_anteil(1.0, 6)[0], 5)    # ganz unten = letzte Seite
        self.assertEqual(preview_manager.ziel_aus_anteil(-0.2, 6), (0, 0.0))

    def test_leiste_bei_mehreren_seiten_immer_sichtbar(self):
        f = preview_manager.scrolleiste_soll_sichtbar_sein
        self.assertTrue(f(False, 500, 900, auto_fit=True, seiten=3))   # Seite passt, trotzdem sichtbar
        self.assertFalse(f(False, 500, 900, auto_fit=True, seiten=1))  # Einzelseite wie bisher

    def _manager(self, seite=0, seiten=6, yview=(0.0, 1.0)):
        app = MagicMock()
        app.current_preview_path = "dummy.pdf"
        app.canvas_preview.yview.return_value = yview
        pm = PreviewManager(app)
        pm.current_page, pm.total_pages = seite, seiten
        pm._blaettern = MagicMock()
        return pm, app

    def test_schieber_auf_derselben_seite_scrollt_sofort(self):
        pm, app = self._manager(seite=1, seiten=4, yview=(0.0, 0.25))
        pm.on_scrollbar("moveto", "0.3")          # 0.3 * 4 = 1.2 -> Seite 2 (Index 1), 20 % hinein
        args = app.canvas_preview.yview_moveto.call_args[0]
        self.assertAlmostEqual(args[0], 0.2)
        app.root.after.assert_any_call(900, pm._verstecke_seitenschild)
        self.assertIsNone(pm._leisten_ziel)

    def test_schieber_auf_andere_seite_springt_entprellt(self):
        pm, app = self._manager(seite=0, seiten=6)
        pm.on_scrollbar("moveto", "0.7")
        self.assertEqual(pm._leisten_ziel[0], 4)
        app.root.after.assert_any_call(60, pm._leisten_sprung)
        pm.update_preview = MagicMock()
        pm._leisten_sprung()
        self.assertEqual(pm.current_page, 4)
        pm.update_preview.assert_called_once()

    def test_sprung_ueber_das_ende_landet_auf_der_letzten_seite(self):
        """Peter 28.10.2026: Bild↓ (3 Seiten) tat bei kurzen Dokumenten nichts."""
        app = MagicMock()
        pm = PreviewManager(app)
        pm.current_page, pm.total_pages = 0, 2
        pm._animation_abschliessen = MagicMock()
        pm._blaettere_gleitend = MagicMock()
        pm._blaettern(3)
        pm._blaettere_gleitend.assert_called_once_with(1, ans_ende=False)
        pm.current_page = 1
        pm._blaettere_gleitend.reset_mock()
        pm._blaettern(3)                          # schon auf der letzten Seite
        pm._blaettere_gleitend.assert_not_called()
        pm._blaettern(-3)                         # Bild↑ seitenweise: an den Anfang
        pm._blaettere_gleitend.assert_called_once_with(-1, ans_ende=False)

    def test_klick_neben_den_schieber_blaettert(self):
        pm, _ = self._manager(seite=2)
        pm.on_scrollbar("scroll", "1", "pages")
        pm._blaettern.assert_called_once_with(1)
        pm._blaettern.reset_mock()
        pm.on_scrollbar("scroll", "-1", "units")   # Seite ganz sichtbar -> Pfeil blättert
        pm._blaettern.assert_called_once_with(-1, fortlaufend=True)

    def test_canvas_meldet_dokumentanteil_an_die_leiste(self):
        pm, app = self._manager(seite=2, seiten=6)
        pm.on_canvas_yview("0.0", "1.0")
        app.scroll_preview.set.assert_called_once_with(2 / 6, 3 / 6)

    def test_schieber_ueber_das_ende_hinaus_behaelt_seine_groesse(self):
        # Seite ganz sichtbar (sichtbar = 1.0): ganz unten ziehen bleibt Seite 6 OBEN, Schieber 1/6 hoch
        self.assertEqual(preview_manager.ziel_aus_anteil(1.0, 6, 1.0), (5, 0.0))
        seite, innen = preview_manager.ziel_aus_anteil(0.99, 4, 0.25)
        self.assertEqual(seite, 3)
        self.assertAlmostEqual(innen, 0.75)
        pm, app = self._manager(seite=0, seiten=6, yview=(0.0, 1.0))
        pm.on_scrollbar("moveto", "1.0")
        oben, unten = app.scroll_preview.set.call_args[0]
        self.assertAlmostEqual(unten - oben, 1 / 6)   # Schieber nicht gestaucht

    def test_waagerechte_leiste_nur_bei_bedarf(self):
        self.assertFalse(preview_manager.waagerechte_leiste_noetig("0.0", "1.0", 2000))
        self.assertFalse(preview_manager.waagerechte_leiste_noetig(0.0, 0.995, 2000))   # 10 px Schatten/Rand
        self.assertTrue(preview_manager.waagerechte_leiste_noetig(0.1, 0.8, 2000))
        app = MagicMock()
        app.canvas_preview.cget.return_value = "-24 -24 1976 1300"
        app.scroll_preview_x.winfo_manager.return_value = ""
        pm = PreviewManager(app)
        pm.on_canvas_xview("0.1", "0.8")
        app.scroll_preview_x.pack.assert_called_once()
        app.scroll_preview_x.winfo_manager.return_value = "pack"
        pm.on_canvas_xview("0.0", "1.0")
        app.scroll_preview_x.pack_forget.assert_called_once()

