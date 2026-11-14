import os
import datetime
import logging
import tkinter as tk
import aktivitaet
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk

from pdf_handler import PDFHandler
from search_manager import SearchManager
from ui_utils import UIUtils

# Hintergrund des Datumsfelds, solange dort nur ein vermutetes Datum steht (noch nicht im PDF):
# orange wie „unberührt“ in der Liste, weiße Schrift - wirkt wie vorausgewählt (Peter 28.10.2026)
_log = logging.getLogger("DocManager")

DATUM_VORSCHLAG_FARBE = "#E07800"
# Kurze Sperre nach dem Blättern per Mausrad (FALLSTRICKE #116), abschaltbar unter Einstellungen → Vorschau
EINSTELLUNG_NACHLAUF = "vorschau_nachlauf"
# Zoomen: sofort ein gestreckter Ausschnitt, scharf neu gezeichnet erst, wenn das Rad so lange ruht (FALLSTRICKE #117)
SCHARF_NACH_MS = 150
# Schatten rechts unter der Seite; das Zoom-Zwischenbild malt ihn mit, sonst flackert der Seitenrand (FALLSTRICKE #117)
SCHATTEN_PX = 4
SCHATTEN_FARBE = "#555555"


def _in_bildlaufgrenzen(start, bild, fenster, rand, schatten=0):
    """Wo die Ansicht nach dem scharfen Bild tatsächlich beginnt (Pixel des gezoomten Bildes): Passt die Seite samt Rand
    ins Fenster, steht sie mittig (update_preview), sonst begrenzt die Bildlaufleiste auf Seite plus Rand - rechts und
    unten zusätzlich um den Schatten, der in der Scrollregion steckt."""
    if bild + 2 * rand <= fenster:
        return (bild - fenster) / 2
    return min(max(start, -rand), bild + schatten + rand - fenster)


def zwischenbild_ausschnitt(ix, iy, sx, sy, breite, hoehe, faktor, bild_breite, bild_hoehe, rand, schatten=0):
    """
    Ausschnitt (links, oben, rechts, unten) des Rohbilds (`bild_breite` × `bild_hoehe`), der auf `breite` × `hoehe`
    gestreckt das Zwischenbild beim Zoomen ergibt: Der Rohbild-Punkt (ix, iy) unter dem Mauszeiger bleibt an der
    Fensterstelle (sx, sy), soweit die Bildlaufgrenzen das zulassen - genau wie danach beim scharfen Bild, sonst
    springt es (Messung 07.11.2026: Maus unter der Vorschau, 115 px Versatz). `faktor` = neuer Zoom / Zoom des Rohbilds.
    """
    links = _in_bildlaufgrenzen(ix * faktor - sx, bild_breite * faktor, breite, rand, schatten) / faktor
    oben = _in_bildlaufgrenzen(iy * faktor - sy, bild_hoehe * faktor, hoehe, rand, schatten) / faktor
    return links, oben, links + breite / faktor, oben + hoehe / faktor


def dokument_anteil(seite, seiten, oben, unten):
    """
    Bildlauf der aktuellen Seite (yview oben/unten, je 0..1) als Anteil am GANZEN Dokument -
    das zeigt die Bildlaufleiste der Vorschau seit 25.10.2026 (Nutzerwunsch: sehen, wo die
    Seite im Dokument steht). Seite 3 von 6, ganz sichtbar -> (2/6, 3/6).
    """
    seiten = max(1, int(seiten or 1))
    return (seite + oben) / seiten, (seite + unten) / seiten


def ziel_aus_anteil(anteil, seiten, sichtbar=0.0):
    """
    Position des Leisten-Schiebers (0..1 über das ganze Dokument) -> (Seite, Anteil innerhalb
    der Seite). ``sichtbar`` = sichtbarer Anteil einer Seite (yview unten - oben): weiter als
    1 - sichtbar kann eine Seite nicht gescrollt werden - ohne diese Grenze rechnete das
    Ziehen über das Dokumentende hinaus, und Tk stauchte den Schieber (Nutzerfund 25.10.2026).
    """
    seiten = max(1, int(seiten or 1))
    pos = min(max(float(anteil), 0.0), 1.0) * seiten
    seite = min(int(pos), seiten - 1)
    return seite, min(pos - seite, max(0.0, 1.0 - sichtbar))


def waagerechte_leiste_noetig(links, rechts, gesamt_breite, toleranz=24):
    """
    Braucht die Vorschau eine waagerechte Bildlaufleiste? Erst, wenn mehr als ``toleranz``
    Pixel verdeckt sind - sonst stünde sie schon beim normalen Zoom da, weil Schatten und
    grauer Rand die Seite ein paar Pixel breiter machen als die Vorschau.
    """
    return (1.0 - (float(rechts) - float(links))) * gesamt_breite > toleranz


def scrolleiste_soll_sichtbar_sein(sichtbar, inhalt_hoehe, canvas_hoehe, auto_fit,
                                   ausblende_puffer=40, seiten=1):
    """
    Soll die senkrechte Bildlaufleiste der Vorschau (noch/wieder) sichtbar sein?

    ECHTE Hysterese (FALLSTRICKE #49, Nutzerfund 03.09.2026 "Zoom-Flattern"):
    Ausblenden erst, wenn die Seite MIT DEUTLICHEM Abstand hineinpasst; Einblenden
    erst bei echtem Überstand. Dazwischen bleibt der Zustand, wie er ist. Nötig, weil
    im Breiten-Autofit das Ausblenden der Leiste den Canvas verbreitert und die Seite
    damit höher macht (~Seitenverhältnis x Leistenbreite, A4 hochkant ≈ 25 px) - eine
    EINZELNE Schwelle kippte an der Grenzbreite endlos hin und her. Der Abstand (40)
    muss diesen Zuwachs sicher übersteigen. Bei festem Zoom ändert die Breite die
    Seitenhöhe nicht - dort reicht ein kleiner Abstand.
    Bei mehrseitigen Dokumenten bleibt die Leiste immer stehen: sie zeigt seit 25.10.2026
    die Position im ganzen Dokument (dokument_anteil) - und ohne Wechsel kein Flattern.
    """
    if seiten > 1:
        return True
    if not auto_fit:
        ausblende_puffer = 2
    if sichtbar:
        return inhalt_hoehe > canvas_hoehe - ausblende_puffer
    return inhalt_hoehe > canvas_hoehe


class PreviewManager:
    # Sichtbarer Hintergrund-Rand um die gerenderte Seite (Pixel)
    PAGE_MARGIN = 24

    def __init__(self, app):
        """
        Initialisiert den Controller für die PDF-Vorschau und Panning/Zoom-Events.
        :param app: Referenz auf die Hauptinstanz.
        """
        self.app = app
        self.last_rendered_path = None
        self.current_page = 0 
        self.total_pages = 1
        
        # Performance-Cache
        self._last_rendered_state = None  

        # Für Smart-Scroll und Animationen
        self._edge_reached = False
        self._scroll_cooldown = False
        self._cooldown_timer = None
        self._nachlauf = False         # kurz nach dem Blättern per Mausrad: weitere Rasten verwerfen
        self._nachlauf_timer = None
        self._anim_timer = None
        self._anim_rest = 0       # noch ausstehende Gleitstrecke (für sofortiges Abschließen)
        self._leisten_ziel = None  # (Seite, Anteil) beim Ziehen am Schieber der Bildlaufleiste
        self._leisten_timer = None
        self._schild_timer = None
        self._seitenschild = None
        self._alt_bild = None     # Referenz auf das Bild der alten Seite während der Animation

    def verwerfe_cache(self):
        """
        Vergisst, was zuletzt gezeichnet wurde — der nächste update_preview() zeichnet
        garantiert neu. Nötig, sobald sich der Inhalt eines Dokuments oder der Canvas
        selbst geändert hat, ohne dass sich Pfad/Seite/Zoom unterscheiden (FALLSTRICKE #43).
        """
        self._last_rendered_state = None

    def leere_vorschau(self, hinweis=""):
        """
        Leert die Vorschau vollständig (leerer Ordner, keine Auswahl); ein `hinweis` erscheint
        als grauer Text oben in der leeren Fläche (Suche ohne Treffer, search_manager).

        Wichtig: NICHT nur den Canvas löschen — ohne verwerfen des Caches hielte der
        Manager dasselbe Dokument weiterhin für „bereits gezeichnet" und würde es beim
        nächsten Anklicken gar nicht mehr rendern (FALLSTRICKE #43).
        """
        self.app.current_preview_path = None
        self.last_rendered_path = None
        self.verwerfe_cache()
        self.current_page = 0
        if hasattr(self.app, "canvas_preview"):
            c = self.app.canvas_preview
            c.delete("all")
            if hinweis:
                c.config(scrollregion=(0, 0, 0, 0))
                c.xview_moveto(0)
                c.yview_moveto(0)
                breite = max(c.winfo_width(), UIUtils.px(c, 300))
                c.create_text(breite // 2, UIUtils.px(c, 40), text=hinweis, anchor="n", justify="center",
                              width=breite - UIUtils.px(c, 40), fill="#555555")
        self.setze_vorschau_info("")

    def setze_vorschau_info(self, text):
        """
        Dateiname/Seite/Zoom in die Fenster-Titelleiste schreiben (31.08.2026): die frühere
        Kopfzeile über der Vorschau kostete bei 125-%-Schrift Vorschau-Höhe - die Titelleiste
        ist ohnehin da. Leerer Text stellt den Basis-Titel (App-Name + Version) wieder her.
        """
        basis = getattr(self.app, "base_title", None)
        if basis:
            self.app.root.title(f"{basis}  —  {text}" if text else basis)

    def update_preview(self):
        """
        Fordert ein neues Bild vom PDFHandler an und zeichnet es.
        Nutzt einen intelligenten Cache, um unnötige Renders zu vermeiden.
        """
        current_path = getattr(self.app, 'current_preview_path', None)
        if not current_path:
            self.setze_vorschau_info("")
            return
        
        c_width = self.app.canvas_preview.winfo_width()
        if c_width < 10: return

        # Rand um die Seite, damit der graue Canvas-Hintergrund sichtbar bleibt
        # und die Seite sich vom Hintergrund abhebt
        display_width = c_width - 2 * self.PAGE_MARGIN
        display_height = 10000
        
        is_new_doc = getattr(self, 'last_rendered_path', None) != current_path
        self.last_rendered_path = current_path

        # Aktive Suchbegriffe: werden auf der Seite hellblau markiert, und bei einem neuen
        # Dokument springt die Vorschau auf die erste Seite mit Fundstelle (Nutzerwunsch
        # 11.09.2026: „da hätte ich gerne gewusst, wo das im Dokument steht").
        suchbegriffe = self._aktive_suchbegriffe()

        if is_new_doc:
            self.current_page = 0
            self._treffer_seite = None
            if suchbegriffe:
                self._treffer_seite = PDFHandler.finde_treffer_seite(
                    current_path, suchbegriffe, SearchManager.begriff_matcher)
                if self._treffer_seite is not None:
                    self.current_page = self._treffer_seite

            # --- Datums-Logik (KID_DokumentenDatum & OCR) ---
            if hasattr(self.app, 'date_entry'):
                self.app.date_entry.delete(0, tk.END)
                
                meta = PDFHandler.get_metadata(current_path)
                saved_date = meta.get("KID_DokumentenDatum", "") if meta else ""
                # Wem das Datumsfeld gehört und was davon schon im PDF steht: Speichern von
                # Titel/Tags schreibt ein abweichendes Feld-Datum mit (FALLSTRICKE #86)
                self.app.datum_feld = {"pfad": current_path, "gespeichert": saved_date, "notbehelf": None}

                if saved_date:
                    self.app.date_entry.insert(0, saved_date)
                    self.app.setze_datum_stil(vermutet=False)
                else:
                    suggested_date = PDFHandler.suggest_document_date(current_path)
                    if not suggested_date:
                        try:
                            stat = os.stat(current_path)
                            file_mtime = datetime.datetime.fromtimestamp(stat.st_mtime)
                            file_ctime = datetime.datetime.fromtimestamp(stat.st_ctime)
                            fallback_date = min(file_mtime, file_ctime)
                            suggested_date = fallback_date.strftime("%Y-%m-%d")
                            # Datei-Datum ist nur ein Notbehelf (Download-/Kopiertag) - nie mitspeichern
                            self.app.datum_feld["notbehelf"] = suggested_date
                        except Exception:
                            pass

                    if suggested_date:
                        # Datum nur VORSCHLAGEN (ins Feld schreiben, hilfreich, nicht
                        # destruktiv). Automatisch SPEICHERN nur, wenn der Nutzer das
                        # ausdrücklich aktiviert hat - sonst würde ein bloßer Klick das
                        # Dokument verändern (und ihm den "unberührt/orange"-Status nehmen).
                        # Orange hinterlegt = noch nicht im PDF (Peter 28.10.2026: sah aus wie gespeichert)
                        self.app.date_entry.insert(0, suggested_date)
                        self.app.datum_feld["angezeigt"] = suggested_date
                        self.app.setze_datum_stil(vermutet=True)
                        if self.app.config.get("auto_fill_on_click", False) and hasattr(self.app, 'save_manual_date'):
                            self.app.root.after(100, self.app.save_manual_date)
                            def focus_and_select():
                                if hasattr(self.app, 'date_entry'):
                                    self.app.date_entry.focus_set()
                                    self.app.date_entry.selection_range(0, tk.END)
                                    self.app.date_entry.icursor(tk.END)
                            self.app.root.after(250, focus_and_select)

        # --- Cache-Check für massiven Performance-Boost ---
        current_zoom = getattr(self.app, 'custom_zoom', None)
        current_state = (current_path, self.current_page, current_zoom, display_width, tuple(suchbegriffe))
        
        if getattr(self, '_last_rendered_state', None) == current_state:
            return  
            
        self._last_rendered_state = current_state
#        self.app.last_rendered_zoom = zoom_pct # zoom_pct ist der Wert den PyMuPDF errechnet hat

        # Das im Datumsfeld stehende Datum gelb markieren - auch wenn es nur vorgeschlagen
        # und noch nicht gespeichert ist (normalize_date_input liefert None bei ungültig).
        highlight_date = None
        if hasattr(self.app, 'date_entry'):
            highlight_date = PDFHandler.normalize_date_input(self.app.date_entry.get())

        treffer_boxen = []
        with aktivitaet.phase(f"Vorschau wird gezeichnet: {os.path.basename(current_path)}…"):
            result = PDFHandler.get_preview_image(
                current_path,
                display_width,
                display_height,
                fixed_zoom=current_zoom,
                start_page=self.current_page,
                highlight_date=highlight_date,
                highlight_terms=suchbegriffe,
                matcher_fuer=SearchManager.begriff_matcher,
                treffer_boxen=treffer_boxen
            )

        if result:
            photo, zoom_pct, self.total_pages, self.current_page = result
            self.app.photo_preview = photo 
            self.app.last_zoom_pct = zoom_pct
            
            c = self.app.canvas_preview
            c.delete("all")

            # Seite horizontal mittig platzieren; vertikal zentrieren, falls sie
            # niedriger als der Canvas ist (sonst mit Rand oben beginnen)
            img_w = photo.width()
            img_h = photo.height()
            c_height = c.winfo_height()
            x_center = max(c_width // 2, self.PAGE_MARGIN + img_w // 2)
            y_top = max(self.PAGE_MARGIN, (c_height - img_h) // 2)

            # Dezenter Schatten hinter der Seite, damit sie sich vom Hintergrund abhebt
            # (deutlich dunkler als der mittelgraue Canvas-Hintergrund #8f8f8f)
            shadow = SCHATTEN_PX
            c.create_rectangle(x_center - img_w // 2 + shadow, y_top + shadow,
                               x_center + img_w // 2 + shadow, y_top + img_h + shadow,
                               fill=SCHATTEN_FARBE, outline="", tags=("blatt",))
            c.create_image(x_center, y_top, anchor="n", image=self.app.photo_preview, tags=("seite", "blatt"))

            # Scrollregion um den Rand erweitern, damit auch beim Scrollen/Pannen
            # rundum Hintergrund sichtbar bleibt
            bbox = c.bbox("all")
            c.config(scrollregion=(bbox[0] - self.PAGE_MARGIN, bbox[1] - self.PAGE_MARGIN,
                                   bbox[2] + self.PAGE_MARGIN, bbox[3] + self.PAGE_MARGIN))
            self._passe_scrollleiste_an(img_h + 2 * self.PAGE_MARGIN + shadow)

            if is_new_doc:
                c.yview_moveto(0)
                c.xview_moveto(0)
            
            filename = os.path.basename(current_path)
            title_text = f"{filename} (Seite {self.current_page + 1} von {self.total_pages}) - {zoom_pct}%"
            title_text += self.treffer_hinweis(suchbegriffe, len(treffer_boxen),
                                               getattr(self, '_treffer_seite', None))
            self.setze_vorschau_info(title_text)
        else:
            # get_preview_image liefert None z.B. bei passwortgeschützten oder
            # beschädigten PDFs (siehe KONZEPT_PDF_ARTEN.md) - ohne diesen Zweig
            # blieb der Canvas-Inhalt des VORHERIGEN Dokuments stehen, obwohl schon
            # ein anderes ausgewählt war (Bug: Vorschau "hinkt" beim Wechsel hinterher).
            self.total_pages = 1
            self.app.photo_preview = None
            c = self.app.canvas_preview
            c.delete("all")
            c.config(scrollregion=(0, 0, 0, 0))
            self.setze_vorschau_info(f"{os.path.basename(current_path)} - Keine Vorschau verfügbar")

    def _aktive_suchbegriffe(self):
        sm = getattr(self.app, 'search_manager', None)
        if not isinstance(sm, SearchManager):
            return []
        return sm.aktive_suchbegriffe()

    @staticmethod
    def treffer_hinweis(suchbegriffe, anzahl_auf_seite, treffer_seite):
        """
        Zusatz für die Titelzeile der Vorschau bei aktiver Suche: Zahl der Markierungen auf
        der Seite, sonst der Hinweis, wo der Treffer stattdessen liegt (andere Seite bzw.
        gar nicht im Seitentext - dann stammt er aus Name/Titel/Tags/Dokument-ID oder aus dem
        verbesserten Text des Suchindex, den das PDF selbst nicht enthält).
        """
        if not suchbegriffe:
            return ""
        begriffe = " ".join(b.strip('"') for b in suchbegriffe)
        if anzahl_auf_seite:
            return f" - {anzahl_auf_seite} Treffer für „{begriffe}\" markiert"
        if treffer_seite is not None:
            return f" - Treffer für „{begriffe}\" auf Seite {treffer_seite + 1}"
        return f" - „{begriffe}\" nicht im Seitentext (Treffer in Name/Titel/Tags/Dokument-ID oder nur im Suchindex)"

    # ==========================================
    # SEITENBLÄTTERN & ANIMATION
    # ==========================================
    def flip_page(self, delta, event=None):
        """Startet den Seitenwechsel mit Animation."""
        if not getattr(self.app, 'current_preview_path', None):
            return
            
        focused = self.app.root.focus_get()
        if isinstance(focused, (tk.Entry, tk.Text, ttk.Entry)):
            return
        # Ordner- und Tag-Baum: Pfeile und Bild-Tasten gehören dem Baum (auf-/zuklappen, scrollen) -
        # die Root-Bindung feuert nach der Treeview-Klasse, darum hier abfangen (Peter 28.10.2026)
        if focused is not None and focused in (getattr(self.app, 'tree_folders', None),
                                               getattr(self.app, 'tree_tags', None)):
            return
        self._blaettern(delta)

    def _blaettern(self, delta, fortlaufend=False):
        """
        Seitenwechsel ohne Fokus-Prüfung (auch für die Bildlaufleiste, die keinen Fokus nimmt).
        `fortlaufend`: Mausrad und Leisten-Pfeile scrollen über die Seitengrenze - rückwärts steht die vorige
        Seite dann an ihrem Ende, nicht am Anfang (Peter 07.11.2026, FALLSTRICKE #116). Bild↑ blättert seitenweise.
        """
        # Ein Sprung über das Ende landet auf der ersten/letzten Seite (Bild↓ bei 2 Seiten tat sonst nichts)
        ziel = max(0, self.current_page + delta)
        if hasattr(self, 'total_pages'):
            ziel = min(ziel, self.total_pages - 1)
        delta = ziel - self.current_page
        if delta == 0:
            return

        # Eine noch laufende Animation sofort zu Ende bringen, sonst liegen alte Seite und
        # Versatz beim schnellen Weiterdrehen falsch
        self._animation_abschliessen()
        self._blaettere_gleitend(delta, ans_ende=fortlaufend and delta < 0)

    @staticmethod
    def blaetter_versatz(alt_oben, alt_hoehe, neu_oben, neu_hoehe, delta, abstand):
        """
        Um wie viel die frisch gezeichnete Seite (Oberkante ``neu_oben``) zunächst verschoben
        werden muss, damit sie direkt unter (vorwärts, delta > 0) bzw. über (rückwärts) der
        alten Seite liegt - mit ``abstand`` grauem Rand dazwischen, wie in einem PDF-Betrachter.
        """
        if delta > 0:
            return alt_oben + alt_hoehe + abstand - neu_oben
        return alt_oben - abstand - neu_hoehe - neu_oben

    @staticmethod
    def gleit_schritte(strecke, schritte=14):
        """Ganzzahlige Einzelschritte (Summe = strecke), die schnell anlaufen und weich auslaufen."""
        positionen = [round(strecke * (1 - (1 - i / schritte) ** 3)) for i in range(schritte + 1)]
        return [b - a for a, b in zip(positionen, positionen[1:])]

    def _blaettere_gleitend(self, delta, ans_ende=False):
        """
        Seitenwechsel ohne „Blättern ins Leere" (Nutzerfund 25.10.2026): Früher glitt die alte
        Seite erst ganz aus dem Bild, DANN wurde die neue gerendert (bei großem Zoom spürbar) und
        glitt herein - dazwischen war nur grauer Hintergrund zu sehen. Jetzt wird die neue Seite
        zuerst gezeichnet, während die alte stehen bleibt; dann gleiten beide zusammen weiter,
        die neue direkt unter bzw. über der alten.
        """
        c = self.app.canvas_preview
        alt_bild = getattr(self.app, "photo_preview", None)
        alt_pos = c.coords("seite") if alt_bild is not None else []
        alt_sicht = c.canvasy(0)

        self.current_page += delta
        self.update_preview()
        c.yview_moveto(1.0 if ans_ende else 0)

        neu_bild = getattr(self.app, "photo_preview", None)
        neu_pos = c.coords("seite")
        if len(alt_pos) < 2 or len(neu_pos) < 2 or neu_bild is None or neu_bild is alt_bild:
            return   # nichts Neues gezeichnet (Fehler, gleiche Seite) - nichts zu animieren

        # Alles Gezeichnete gehört zur neuen Seite; die alte kommt als Kopie dorthin zurück,
        # wo sie eben auf dem Bildschirm stand
        c.addtag_all("neu")
        neu_sicht = c.canvasy(0)
        ax, ay = alt_pos[0], alt_pos[1] - alt_sicht + neu_sicht
        b, h, schatten = alt_bild.width(), alt_bild.height(), SCHATTEN_PX
        c.create_rectangle(ax - b // 2 + schatten, ay + schatten, ax + b // 2 + schatten, ay + h + schatten,
                           fill=SCHATTEN_FARBE, outline="", tags=("alt",))
        c.create_image(ax, ay, anchor="n", image=alt_bild, tags=("alt",))
        self._alt_bild = alt_bild

        versatz = self.blaetter_versatz(ay, h, neu_pos[1], neu_bild.height(), delta, self.PAGE_MARGIN)
        c.move("neu", 0, versatz)
        self._anim_rest = -versatz
        schritte = self.gleit_schritte(-versatz)

        def worker(i):
            if i < len(schritte):
                c.move("all", 0, schritte[i])
                self._anim_rest -= schritte[i]
                self._anim_timer = c.after(15, worker, i + 1)
            else:
                self._anim_timer = None
                self._animation_abschliessen()

        worker(0)

    def _animation_abschliessen(self):
        """Laufende Blätter-Animation sofort beenden: Restweg gehen, alte Seite entfernen."""
        if self._anim_timer:
            self.app.root.after_cancel(self._anim_timer)
            self._anim_timer = None
        c = self.app.canvas_preview
        if self._anim_rest:
            c.move("all", 0, self._anim_rest)
            self._anim_rest = 0
        c.delete("alt")
        c.dtag("all", "neu")
        self._alt_bild = None

    # ==========================================
    # MAUS- & ZOOM-EVENTS
    # ==========================================
    def _end_cooldown(self):
        self._scroll_cooldown = False

    NACHLAUF_MS = 300   # länger als die Gleit-Animation (14 × 15 ms); 400 ms waren Peter zu lang (07.11.2026)

    def _blaettern_per_rad(self, richtung):
        """
        Blättern am Seitenrand per Mausrad, danach eine kurze Nachlauf-Sperre (FALLSTRICKE #116): Ohne sie
        scrollten die Rasten, die das Rad im Schwung noch liefert, sofort in die neue Seite hinein - bei Zoom
        landete man mitten auf ihr statt an ihrem Anfang. Danach scrollt das Rad wieder normal weiter.
        """
        self._blaettern(richtung, fortlaufend=True)
        self._edge_reached = False
        if not self.app.config.get(EINSTELLUNG_NACHLAUF, True):
            return   # abgeschaltet (Einstellungen → Vorschau): Rad scrollt sofort weiter
        self._nachlauf = True
        if self._nachlauf_timer:
            self.app.root.after_cancel(self._nachlauf_timer)
        self._nachlauf_timer = self.app.root.after(self.NACHLAUF_MS, self._nachlauf_ende)

    def _nachlauf_ende(self):
        self._nachlauf = False
        self._nachlauf_timer = None

    def on_preview_mousewheel(self, event):
        """Scrollt das Canvas vertikal und blättert am Rand animiert zur nächsten Seite (mit Cooldown)."""
        # Blättert über _blaettern, NICHT flip_page: dessen Fokus-Sperre (Cursor in einem Eingabefeld)
        # ist für die Pfeiltasten gedacht - das Mausrad über der Vorschau meint immer die Vorschau
        # (Release-Check 28.10.2026: die Datums-Automatik setzt den Fokus ins Datumsfeld)
        if not getattr(self.app, 'current_preview_path', None): return
        if self._nachlauf:
            return   # gerade geblättert: die neue Seite beginnt oben (FALLSTRICKE #116)

        if hasattr(event, 'num') and event.num in (4, 5):
            direction = -1 if event.num == 4 else 1
        else:
            direction = -1 if event.delta > 0 else 1
            
        c = self.app.canvas_preview
        y_scroll = c.yview()
        
        if y_scroll[0] <= 0.0 and y_scroll[1] >= 1.0:
            # Seite passt komplett ins Fenster: Es gibt keinen "Rand", an dem man erst
            # ankommen könnte - die zweistufige Logik unten (erster Tick bewaffnet, zweiter
            # blättert) fühlte sich hier wie ein Blindgänger an (ToDo 30.08.2026). Sofort
            # blättern, nur eine kurze Sperre gegen das Durchrattern beim schnellen Drehen.
            if not self._scroll_cooldown:
                self._scroll_cooldown = True
                if self._cooldown_timer: self.app.root.after_cancel(self._cooldown_timer)
                self._cooldown_timer = self.app.root.after(250, self._end_cooldown)
                self._blaettern(direction)
            self._edge_reached = False
            return

        if direction < 0 and y_scroll[0] <= 0.0:
            if not self._edge_reached:
                self._edge_reached = True
                self._scroll_cooldown = True
                if self._cooldown_timer: self.app.root.after_cancel(self._cooldown_timer)
                self._cooldown_timer = self.app.root.after(400, self._end_cooldown)
            elif not self._scroll_cooldown:
                self._blaettern_per_rad(-1)
        elif direction > 0 and y_scroll[1] >= 1.0:
            if not self._edge_reached:
                self._edge_reached = True
                self._scroll_cooldown = True
                if self._cooldown_timer: self.app.root.after_cancel(self._cooldown_timer)
                self._cooldown_timer = self.app.root.after(400, self._end_cooldown)
            elif not self._scroll_cooldown:
                self._blaettern_per_rad(1)
        else:
            self._edge_reached = False
            self._scroll_cooldown = False
            if self._cooldown_timer: self.app.root.after_cancel(self._cooldown_timer)
            c.yview_scroll(direction * 2, "units")

    def on_zoom_mousewheel(self, event):
        """
        Berechnet bei Strg+Mausrad den neuen Ziel-Zoom (gedeckelt auf 10-500% als RAM-Schutz), zeigt sofort ein gestrecktes
        Zwischenbild und rendert scharf erst, wenn das Rad SCHARF_NACH_MS ruht (_apply_zoom, FALLSTRICKE #117).
        """
        # 1. Ziel-Zoom berechnen (1.0 / 1.1 verhindert mathematischen Drift)
        zoom_factor = 1.1 if event.delta > 0 else (1.0 / 1.1)

        current_zoom = getattr(self, '_target_zoom', None)
        if current_zoom is None:
            current_zoom = self.app.custom_zoom
            if current_zoom is None:
                current_zoom = getattr(self.app, 'last_zoom_pct', 100) / 100.0

        new_zoom = current_zoom * zoom_factor

        # RAM-Schutz Limitierungen
        if new_zoom > 5.0: new_zoom = 5.0
        if new_zoom < 0.1: new_zoom = 0.1
        if abs(new_zoom - current_zoom) < 0.001:
            return

        self._target_zoom = new_zoom

        # 2. Sofort sichtbar: gestreckter Ausschnitt des vorhandenen Bildes. Früher renderte jede Raste nach 40 ms die
        # ganze Seite neu, bei starkem Zoom stauten sich die Rasten (Peter 07.11.2026: „grenzwertig träge“).
        self._zeige_zwischenbild(new_zoom)

        # 3. Scharf neu zeichnen erst, wenn das Rad ruht (Debouncing)
        if getattr(self, '_zoom_timer', None):
            self.app.canvas_preview.after_cancel(self._zoom_timer)
        self._zoom_timer = self.app.canvas_preview.after(SCHARF_NACH_MS, self._apply_zoom)

    def _zeige_zwischenbild(self, ziel_zoom):
        """
        Legt über die Vorschau einen auf `ziel_zoom` gestreckten Ausschnitt des Rohbilds der aktuellen Seite (nur so groß
        wie das Fenster, darum schnell), der Punkt unter dem Mauszeiger bleibt stehen. Das scharfe Bild aus _apply_zoom
        ersetzt es. Ohne Rohbild (Fehler, Test-Attrappe) geschieht nichts - dann kommt nur das scharfe Bild.
        """
        c = self.app.canvas_preview
        foto = getattr(self.app, "photo_preview", None)
        roh, roh_zoom = getattr(foto, "roh", None), getattr(foto, "zoom", None)
        pos = c.coords("seite")
        if not isinstance(roh, Image.Image) or not isinstance(roh_zoom, (int, float)) or roh_zoom <= 0 or len(pos) < 2:
            return
        try:
            breite, hoehe = c.winfo_width(), c.winfo_height()
            try:
                sx = c.winfo_pointerx() - c.winfo_rootx()
                sy = c.winfo_pointery() - c.winfo_rooty()
            except Exception:
                sx, sy = breite / 2, hoehe / 2
            # Seite liegt mit anchor "n": pos = (Mitte, Oberkante) in Canvas-Koordinaten
            ix = c.canvasx(sx) - (pos[0] - roh.width / 2)
            iy = c.canvasy(sy) - pos[1]
            box = zwischenbild_ausschnitt(ix, iy, sx, sy, breite, hoehe, ziel_zoom / roh_zoom,
                                          roh.width, roh.height, self.PAGE_MARGIN, SCHATTEN_PX)
            grau = tuple(v // 257 for v in c.winfo_rgb(c.cget("bg")))
            bild = roh.transform((breite, hoehe), Image.EXTENT, box, Image.BILINEAR, fillcolor=grau)
            # Schatten wie beim scharfen Bild rechts und unter der Seite (Peter 07.11.2026: „flackert bzw. wackelt“ -
            # ohne ihn verschwand der dunkle Rand bei jeder Raste und kam beim Scharfwerden zurück)
            f = breite / (box[2] - box[0])
            links, oben = -box[0] * f, -box[1] * f
            rechts, unten = (roh.width - box[0]) * f, (roh.height - box[1]) * f
            s = SCHATTEN_PX
            malen = ImageDraw.Draw(bild)
            malen.rectangle((rechts, oben + s, rechts + s - 1, unten + s - 1), fill=SCHATTEN_FARBE)
            malen.rectangle((links + s, unten, rechts + s - 1, unten + s - 1), fill=SCHATTEN_FARBE)
            self._zwischen_foto = ImageTk.PhotoImage(bild)
            c.delete("zwischen")
            c.create_image(c.canvasx(0), c.canvasy(0), anchor="nw", image=self._zwischen_foto, tags=("zwischen",))
        except Exception as e:   # das Zwischenbild ist nur Komfort, das scharfe Bild kommt trotzdem
            _log.debug(f"Zwischenbild beim Zoomen übersprungen: {e}")

    def _weg_mit_zwischenbild(self):
        self.app.canvas_preview.delete("zwischen")
        self._zwischen_foto = None

    def _apply_zoom(self):
        """
        Rendert die Vorschau mit dem gedebounceten Ziel-Zoom neu und hält dabei den Punkt unter dem
        Mauszeiger fix (Maus-zentrierter Zoom): merkt sich die Position relativ zur alten Bildgröße,
        rendert, und verschiebt die Scrollregion anhand des tatsächlichen neuen/alten Pixelverhältnisses
        wieder auf denselben Punkt.
        """
        self._zoom_timer = None
        # Das Zwischenbild bleibt liegen, bis das scharfe Bild steht: update_preview lässt beim Phasenstart einmal zeichnen
        # (aktivitaet.phase), ohne Zwischenbild erschien dort das alte Bild an alter Stelle (Peter 07.11.2026, FALLSTRICKE #117).
        # Gerechnet wird darum mit der Seite samt Schatten (Tag "blatt"), nicht mit bbox("all").
        target = getattr(self, '_target_zoom', None)
        if not target:
            self._weg_mit_zwischenbild()
            return

        # --- FIX 1: Live-Hardware-Koordinaten der Maus abrufen ---
        # Verhindert, dass das Bild an alte Koordinaten "springt", falls die Maus bewegt wurde.
        try:
            x_screen = self.app.canvas_preview.winfo_pointerx() - self.app.canvas_preview.winfo_rootx()
            y_screen = self.app.canvas_preview.winfo_pointery() - self.app.canvas_preview.winfo_rooty()
        except Exception:
            # Fallback, falls die Maus gerade den Monitor verlässt
            x_screen = self.app.canvas_preview.winfo_width() / 2
            y_screen = self.app.canvas_preview.winfo_height() / 2

        # Wo ist dieser Live-Punkt auf dem alten Papier?
        x_canvas = self.app.canvas_preview.canvasx(x_screen)
        y_canvas = self.app.canvas_preview.canvasy(y_screen)

        bbox_old = self.app.canvas_preview.bbox("blatt")
        if not bbox_old:
            self.app.custom_zoom = target
            self.update_preview()
            self._weg_mit_zwischenbild()
            return

        old_width = bbox_old[2] - bbox_old[0]
        old_height = bbox_old[3] - bbox_old[1]

        if old_width <= 0 or old_height <= 0:
            self.app.custom_zoom = target
            self.update_preview()
            self._weg_mit_zwischenbild()
            return

        # --- FIX 2: Jetzt erst Rendern! ---
        self.app.custom_zoom = target
        self._target_zoom = None
        self.update_preview()
        self._weg_mit_zwischenbild()     # meist schon mit delete("all") weg; nicht, wenn update_preview den Cache traf

        # KEIN update_idletasks hier: Es brachte das neue Bild einmal an der ALTEN Stelle auf den Schirm,
        # erst danach sprang die Ansicht unter den Mauszeiger - das Flackern beim Zoomen (FALLSTRICKE #116).
        # bbox kennt die neuen Maße auch so, Tk berechnet sie beim Anlegen des Bildes.
        bbox_new = self.app.canvas_preview.bbox("all")
        if not bbox_new: return

        new_width = bbox_new[2] - bbox_new[0]
        new_height = bbox_new[3] - bbox_new[1]
        if new_width <= 0 or new_height <= 0: return

        # 3. Perfekte Mathematik anhand des ECHTEN Pixelverhältnisses
        actual_ratio_x = new_width / old_width
        actual_ratio_y = new_height / old_height

        distance_x_new = (x_canvas - bbox_old[0]) * actual_ratio_x
        distance_y_new = (y_canvas - bbox_old[1]) * actual_ratio_y

        new_canvas_x = bbox_new[0] + distance_x_new
        new_canvas_y = bbox_new[1] + distance_y_new

        view_x = new_canvas_x - x_screen
        view_y = new_canvas_y - y_screen

        # 4. Saubere Zuweisung der Scrollregion (Schützt vor dem Rand-Kleben)
        sr = self.app.canvas_preview.cget("scrollregion")
        if sr:
            try:
                # float() schützt vor eventuellen Skalierungsfehlern bei 4K Monitoren
                sr_list = [int(float(i)) for i in sr.split()]
                sr_w = sr_list[2] - sr_list[0]
                sr_h = sr_list[3] - sr_list[1]
                sr_offset_x = sr_list[0]
                sr_offset_y = sr_list[1]
            except Exception:
                sr_w, sr_h = new_width, new_height
                sr_offset_x, sr_offset_y = bbox_new[0], bbox_new[1]
        else:
            sr_w, sr_h = new_width, new_height
            sr_offset_x, sr_offset_y = bbox_new[0], bbox_new[1]

        frac_x = (view_x - sr_offset_x) / sr_w if sr_w > 0 else 0
        frac_y = (view_y - sr_offset_y) / sr_h if sr_h > 0 else 0

        self.app.canvas_preview.xview_moveto(frac_x)
        self.app.canvas_preview.yview_moveto(frac_y)

    # ==========================================
    # BILDLAUFLEISTE ÜBER DAS GANZE DOKUMENT
    # ==========================================
    def on_canvas_yview(self, oben, unten):
        """yscrollcommand des Canvas: Bildlauf der Seite auf das ganze Dokument umrechnen."""
        leiste = getattr(self.app, "scroll_preview", None)
        if leiste is None:
            return
        leiste.set(*dokument_anteil(self.current_page, getattr(self, "total_pages", 1),
                                    float(oben), float(unten)))

    def on_canvas_xview(self, links, rechts):
        """
        xscrollcommand des Canvas: waagerechte Leiste nur zeigen, solange die Seite breiter als
        die Vorschau ist (Nutzerfund 25.10.2026: beim Zoomen fehlte sie). Ihr Ein-/Ausblenden
        ändert nur die HÖHE des Canvas - im Breiten-Autofit also keine Rückkopplung wie bei #49.
        """
        leiste = getattr(self.app, "scroll_preview_x", None)
        if leiste is None:
            return
        leiste.set(links, rechts)
        region = str(self.app.canvas_preview.cget("scrollregion")).split()
        gesamt = float(region[2]) - float(region[0]) if len(region) == 4 else 0
        noetig = waagerechte_leiste_noetig(links, rechts, gesamt, self.PAGE_MARGIN)
        sichtbar = bool(leiste.winfo_manager())
        if noetig and not sichtbar:
            leiste.pack(side=tk.BOTTOM, fill=tk.X, before=self.app.canvas_preview)
        elif sichtbar and not noetig:
            leiste.pack_forget()

    def on_scrollbar(self, aktion, *args):
        """
        Befehle der Bildlaufleiste: Schieber ziehen ("moveto") springt zur passenden Seite und
        Stelle - innerhalb der Seite sofort, auf eine andere Seite entprellt (Rendern dauert);
        Klick neben den Schieber ("scroll … pages") blättert eine Seite, die Pfeile scrollen
        und blättern am Seitenrand weiter wie das Mausrad.
        """
        if not getattr(self.app, "current_preview_path", None):
            return
        seiten = getattr(self, "total_pages", 1) or 1
        c = self.app.canvas_preview
        if aktion == "moveto":
            oben, unten = c.yview()
            seite, innen = ziel_aus_anteil(args[0], seiten, unten - oben)
            self.app.scroll_preview.set(*dokument_anteil(seite, seiten, innen, innen + (unten - oben)))
            self._zeige_seitenschild(seite, seiten, float(args[0]))
            if seite == self.current_page:
                c.yview_moveto(innen)
                return
            self._leisten_ziel = (seite, innen)
            if self._leisten_timer:
                self.app.root.after_cancel(self._leisten_timer)
            self._leisten_timer = self.app.root.after(60, self._leisten_sprung)
        elif aktion == "scroll":
            schritte, einheit = int(args[0]), args[1]
            richtung = 1 if schritte > 0 else -1
            oben, unten = c.yview()
            if einheit == "pages":
                self._blaettern(richtung)
            elif (richtung > 0 and unten >= 1.0) or (richtung < 0 and oben <= 0.0):
                self._blaettern(richtung, fortlaufend=True)   # Pfeil am Rand: weiter wie das Mausrad
            else:
                c.yview_scroll(schritte * 2, "units")

    def _leisten_sprung(self):
        """Ziel vom Schieber anspringen (ohne Gleit-Animation - beim Ziehen will man direkt dorthin)."""
        self._leisten_timer = None
        if not self._leisten_ziel:
            return
        seite, innen = self._leisten_ziel
        self._leisten_ziel = None
        self._animation_abschliessen()
        if seite != self.current_page:
            self.current_page = seite
            self.update_preview()
        self.app.canvas_preview.yview_moveto(innen)

    def _zeige_seitenschild(self, seite, seiten, anteil):
        """Kleines Schild „Seite x von N" neben dem Schieber, solange gezogen wird."""
        if seiten < 2:
            return
        c = self.app.canvas_preview
        if self._seitenschild is None or not self._seitenschild.winfo_exists():
            self._seitenschild = tk.Label(c, bg="#fffbe6", fg="#333333", relief="solid", bd=1, padx=6, pady=2)
        self._seitenschild.configure(text=f"Seite {seite + 1} von {seiten}")
        self._seitenschild.place(in_=c, relx=1.0, x=-8, rely=min(max(anteil, 0.03), 0.97), anchor="e")
        if self._schild_timer:
            self.app.root.after_cancel(self._schild_timer)
        self._schild_timer = self.app.root.after(900, self._verstecke_seitenschild)

    def _verstecke_seitenschild(self):
        self._schild_timer = None
        if self._seitenschild is not None and self._seitenschild.winfo_exists():
            self._seitenschild.place_forget()

    def _passe_scrollleiste_an(self, inhalt_hoehe):
        """
        Senkrechte Bildlaufleiste nur zeigen, wenn sie gebraucht wird (Nutzerwunsch
        03.09.2026: nach 'Seite einpassen' soll sie verschwinden). Zustandswechsel über
        scrolleiste_soll_sichtbar_sein - mit ECHTER Hysterese, siehe FALLSTRICKE #49.
        """
        leiste = getattr(self.app, "scroll_preview", None)
        c = getattr(self.app, "canvas_preview", None)
        if leiste is None or c is None:
            return
        sichtbar = bool(leiste.winfo_manager())
        soll = scrolleiste_soll_sichtbar_sein(
            sichtbar, inhalt_hoehe, c.winfo_height(),
            auto_fit=getattr(self.app, "custom_zoom", None) is None,
            seiten=getattr(self, "total_pages", 1) or 1)
        if sichtbar and not soll:
            leiste.pack_forget()
        elif soll and not sichtbar:
            leiste.pack(side=tk.RIGHT, fill=tk.Y, before=c)

    def reset_zoom(self, event=None):
        """Setzt den manuellen Zoom zurück auf Auto-Fit, persistiert das in der Config und rendert neu."""
        self.app.custom_zoom = None
        self.app.config.set("custom_zoom", None)
        self.update_preview()

    def on_sash_doppelklick(self, event):
        """
        Doppelklick auf einen Greifer des Haupt-PanedWindows: nur der RECHTE Greifer
        (zwischen Dokumentenliste und Seitenansicht, Sash-Index 1) passt die Seite ein
        (Nutzerwunsch 03.09.2026) - der linke behält sein normales Verhalten.
        """
        pane = self.app.main_pane
        try:
            sash = pane.tk.call(pane._w, "identify", "sash", event.x, event.y)
        except tk.TclError:
            return
        if str(sash) == "1":
            self.passe_seite_ein()

    def passe_seite_ein(self):
        """
        'Seite einpassen' (Nutzerwunsch 03.09.2026): Zoom so wählen, dass die GANZE Seite
        in die Höhe der Ansicht passt, und den rechten Greifer exakt auf die dafür nötige
        Breite ziehen - ganze Seite bei minimalem grauen Rand, die Bildlaufleiste
        verschwindet dann von selbst (siehe _passe_scrollleiste_an).
        Rechnet über das zuletzt gerenderte Bild (Bildgröße / letzter Zoom = Seitengröße
        in Punkten) und hält die RAM-Schutzgrenzen des Zooms ein (custom_zoom nie > 5.0).
        """
        photo = getattr(self.app, "photo_preview", None)
        zoom_pct = getattr(self.app, "last_zoom_pct", 0)
        if photo is None or not zoom_pct:
            return
        alt = zoom_pct / 100.0
        seite_breite = photo.width() / alt
        seite_hoehe = photo.height() / alt
        hoehe = self.app.canvas_preview.winfo_height()
        if seite_hoehe <= 0 or hoehe < 50:
            return
        schatten = 6
        ziel = (hoehe - 2 * self.PAGE_MARGIN - schatten) / seite_hoehe
        ziel = max(0.1, min(5.0, ziel))
        self.app.custom_zoom = ziel
        self.app.config.set("custom_zoom", round(ziel, 3))

        # Greifer auf die benötigte Breite ziehen: Seitenansicht = Seite + Rand links/rechts
        pane = self.app.main_pane
        benoetigt = int(seite_breite * ziel) + 2 * self.PAGE_MARGIN + schatten
        gesamt = pane.winfo_width()
        neuer_sash = max(pane.sashpos(0) + 60, gesamt - benoetigt - 5)
        if neuer_sash < gesamt - 50:
            pane.sashpos(1, neuer_sash)
        self.update_preview()

    def on_canvas_click(self, event):
        # Klick in die Vorschau gibt ihr die Tastatur: Pfeile, Bild↑/↓, Pos1/Ende blättern dann die Seiten
        # (in der Liste wählen Pos1/Ende Dokumente, Peter 28.10.2026)
        self.app.canvas_preview.focus_set()
        if getattr(self.app, 'current_preview_path', None):
            self.app.canvas_preview.scan_mark(event.x, event.y)

    def on_canvas_drag(self, event):
        if getattr(self.app, 'current_preview_path', None):
            self.app.canvas_preview.scan_dragto(event.x, event.y, gain=1)
            
    def on_canvas_resize(self, event):
        """Debounced Neu-Rendern bei Fenster-/Spalten-Resize um 150ms, statt bei jedem <Configure>-Event zu rendern (siehe FALLSTRICKE #12)."""
        if not getattr(self.app, 'current_preview_path', None):
            return
        if hasattr(self, '_resize_timer'):
            self.app.root.after_cancel(self._resize_timer)
        self._resize_timer = self.app.root.after(150, self.update_preview)