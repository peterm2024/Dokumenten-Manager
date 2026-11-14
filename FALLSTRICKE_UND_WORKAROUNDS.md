# Entwicklungs-Logbuch: Gelöste Fallstricke & Workarounds

Dieses Dokument dokumentiert die technischen Hürden, die während der Entwicklung des Dokumenten-Managers aufgetreten sind, sowie die erarbeiteten Lösungen und Best Practices.

---

## 1. Das Windows-Datei-Lock-Problem (File-Locking)

**Problem:** Abstürze (`PermissionError`) beim Speichern der Metadaten, da die App das PDF für die Vorschau noch blockierte.
**Lösung:** Architektur-Umstellung in `pdf_handler.py`. Dateien werden geöffnet, verarbeitet und in derselben Millisekunde wieder geschlossen (`doc.close()`). Inkrementelles Speichern (`incremental=True`) wurde aktiviert, um Änderungen konfliktfrei anzuhängen.

---

## 2. Der Panning-Jitter (Maus-Ziehen in der Vorschau)

**Problem:** Das Ziehen des PDFs stotterte massiv, wenn die Render-Auflösung (durch DPI/Zoom) sehr hoch war.
**Lösung:** Ein starker Throttle-Mechanismus (`self._drag_timer`). Die GUI aktualisiert die Bildposition nur alle 15ms und bricht überschüssige Events ab.

---

## 3. Die Watchdog-Kollision (Thread-Deadlocks)

**Problem:** Endlosschleifen beim Verschieben (Drag & Drop) von Dateien. GUI und Hintergrund-Watchdog versuchten zeitgleich, die Treeviews zu aktualisieren.
**Lösung:** Einführung einer Watchdog-Stummschaltung (`self.is_moving = True`). Der Watchdog bekommt während Datei-Operationen einen Maulkorb verpasst.

---

## 4. Der Metadaten-Überschreib-Bug (PyMuPDF Dicts)

**Problem:** Beim Speichern neuer Tags wurden bestehende Metadaten (Titel, Ersteller) versehentlich gelöscht, da PyMuPDF ein unvollständiges Dictionary erwartete.
**Lösung:** Zuerst müssen zwingend alle bestehenden Metadaten per `doc.metadata` ausgelesen werden. Dann werden gezielt nur die gewünschten Keys manipuliert und das gesamte Objekt zurückgeschrieben.

---

## 5. Löschen von Ordnern mit versteckten Systemdateien

**Problem:** Windows blockiert das Löschen von Ordnern (Papierkorb-Logik), wenn sich darin noch versteckte Dateien wie `thumbs.db` befinden.
**Lösung:** Ein manueller Datei-Sweep über `os.scandir` zum Erzwingen des Datei-Löschens (`os.unlink`), bevor der eigentliche Ordner entfernt wird.

---

## 6. Tkinter Fokus-Verlust beim Auto-Save

**Problem:** Klickte der User schnell durch die Tags, verlor Tkinter nach 1 Sekunde (Auto-Save-Timer) die Auswahl in der mittleren Spalte.
**Ursache:** Das Speichern änderte den "Zuletzt geändert"-Zeitstempel. Der Watchdog bemerkte dies, löschte die Liste und baute sie neu auf.
**Lösung:** Ein Selection-Lock. Die ID der ausgewählten Datei wird gemerkt, das UI heimlich aktualisiert (`item(sel_id, values=...)`), und die Auswahl hart wiederhergestellt.

---

## 7. Der PyMuPDF RAM-Overflow (Der 45GB-Fehler)

**Problem:** Das Programm fror beim Klick auf ein Dokument komplett ein, die Konsole warf den Fehler: `not enough free memory for image buffer`. Python versuchte 45 GB RAM zu belegen.
**Ursache:** PyMuPDF rendert Zoom-Level über Multiplikatoren (`1.0` = 100%). Ein versehentlich via UI/Config übergebener Wert von `125` bedeutete 12.500% Zoom, was zu einem gigantischen Bild-Canvas führte.
**Lösung:** Implementierung eines Hard-Limits beim Laden der `settings.json`. Jeder Zoomwert `> 5.0` (500%) wird als invalid betrachtet und auf Auto-Fit (`None`) zurückgesetzt.

---

## 8. Der Tkinter Selection-Deadlock (Doppeltes Rendering)

**Problem:** GUI fror ein, da PyMuPDF versuchte, dieselbe PDF-Datei auf denselben Canvas zweimal in derselben Millisekunde zu rendern.
**Ursache:** Das manuelle Setzen von `tree_files.selection_set()` im Code feuerte intern bereits das Event `<<TreeviewSelect>>`. Ein darauffolgender manueller Aufruf von `on_file_select()` erzeugte einen Race Condition / File Lock.
**Lösung:** 1. Entfernen des manuellen Aufrufs (Tkinter das Eventing überlassen).
2. Entkopplung von UI-Klick und Rendering durch einen `after(200)` Timer (Debounce). Dies erlaubt der GUI, sich aufzubauen und Klick-Folgen auszuwerten, bevor das arbeitsintensive PDF-Rendern beginnt.

---

## 9. Tkinter Treeview Tags-Typisierung

**Problem:** Der Tag-Manager crashte willkürlich mit der Meldung, dass Strings gesplittet werden (`['b', 'u', 'n', ...]`).
**Ursache:** Tkinter gibt über `item(iid, "tags")` oft ein Tuple zurück (z.B. `("bundle",)`). Wenn ein Item jedoch nur ein einziges Tag besitzt, gibt Tkinter es in manchen Versionen als simplen String (`"bundle"`) zurück. Die Iteration über den String zerteilt das Wort.
**Lösung:** Ein Type-Check (`isinstance(tags_data, str)`) direkt nach dem Auslesen zwingt einzelne Strings zurück in eine Liste.

---

## 10. Das "Nackte PDF" Metadaten-Problem (PyMuPDF Incremental Save)

**Problem:** Das automatische Speichern (Auto-Save) von neu generierten Dateinamen als PDF-Titel verpuffte wirkungslos, wenn das PDF direkt von einem Scanner kam.
**Ursache:** PyMuPDFs `incremental=True`-Methode speichert zwar extrem schnell, weigert sich jedoch, das `/Info`-Dictionary anzulegen, falls das PDF komplett ohne Metadatenstruktur erzeugt wurde.
**Lösung:** Umleitung der GUI-Speicherfunktion auf die sichere `write_custom_metadata`-Methode des `PDFHandler`. Diese schreibt über eine temporäre Datei die komplette PDF-Struktur neu und erzwingt das Vorhandensein der Metadaten-Felder.

---

## 11. Versteckte Fehler im PDF-Inspektor

**Problem:** Bei der Fehlersuche half der PDF-Inspektor nicht weiter, da leere Metadatenfelder (wie "title" oder "keywords") einfach unsichtbar waren.
**Ursache:** Die Abfrage `if value:` übersprang alle Keys, deren Value `""` oder `None` war.
**Lösung:** Die Iteration in `pdf_inspector.py` wurde angepasst, um gnadenlos über alle `doc.metadata.items()` zu iterieren. Fehlt ein Wert, wird nun explizit `(leer)` ausgegeben. Zusätzlich wurde eine Sonderbehandlung für das KI-generierte Datum (`KID_DokumentenDatum`) eingebaut, um es sofort visuell hervorzuheben.

---

## 12. Render-Thrashing beim Fenster-Skalieren

**Problem:** Zog man das App-Fenster oder den mittleren Trennbalken in der Größe zurecht, fror die UI extrem ein und die CPU-Last stieg massiv an.
**Ursache:** Tkinters `<Configure>`-Event feuerte pro Pixel-Veränderung hunderte Male, was in der `preview_manager.py` bei jedem Aufruf ein komplettes, extrem rechenintensives Neurendern des PDFs durch PyMuPDF auslöste.
**Lösung:** Ein UI-Debouncing-Timer. Das Event setzt nur noch eine Variable und startet einen 150ms Timer. Erst wenn der User aufhört, das Fenster zu skalieren, läuft der Timer ab und das Rendern wird exakt einmal ausgeführt.

---

## 13. Der Zitter-Klick ("Sloppy Click") & MockEvents

**Problem:** Beim simplen Anklicken einer PDF-Datei ploppte manchmal die Meldung auf: "Die gezogene Quelldatei hat keine Tags". Tkinter interpretierte ein minimales Verwackeln der Maus (1 Pixel) sofort als Beginn eines Drag & Drop Vorgangs. Zudem stürzten Code-Aufrufe ohne Maus mit einem `MockEvent`-Attributfehler ab.
**Lösung:** Einführung einer Deadzone/Toleranz in `file_operations.py`. Das Programm merkt sich `_drag_start_x/y` und wertet in `on_file_drop` jede Bewegung unter 2 Pixeln als lautlosen Klick. Zudem schützt `hasattr(event, 'x_root')` vor Abstürzen durch MockEvents.

---

## 14. Die Auto-Sync Ordner-Falle bei der Suche

**Problem:** Suchte man nach einem Begriff und klickte auf ein Ergebnis in der Liste, sprang die Ansicht plötzlich zurück in den Root-Ordner.
**Ursache:** Der Klick löste eine Komfortfunktion aus, die den zugehörigen Ordner im Dateibaum markiert. Diese Markierung triggerte wiederum das Tree-Event `on_folder_select`, welches die Suchergebnisse sofort überschrieb.
**Lösung:** Ein "Such-Schutzschild". Wenn Text im Suchfeld steht, setzt die `gui.py` temporär die Variable `self.folder_manager.ignore_next_select = True`. Der FolderManager fängt dies ab und ignoriert das nächste Update.

---

## 15. Cache blockiert dynamische Vorschau-Marker

**Problem:** Der "Virtuelle Textmarker" in der PDF-Vorschau (der das gesetzte Datum gelb markiert) aktualisierte sich nach einer manuellen Datumseingabe im Textfeld und anschließendem Druck auf "Return" nicht.
**Ursache:** Der `PreviewManager` besitzt aus Performance-Gründen ein Gedächtnis (`_last_rendered_state`). Da sich Pfad, Zoom und Seite nicht geändert hatten, ignorierte er den Neu-Zeichnen-Befehl und lieferte das alte Bild.
**Lösung:** Bei der manuellen Bestätigung (`save_manual_date`) wird der Cache vor dem Update-Call explizit gelöscht (`self.preview_manager._last_rendered_state = None`), um ein hartes Neu-Rendern (inklusive frischem Textmarker) zu erzwingen.

---

## 16. Plugin-Architektur: Zirkelbezüge beim Import

**Problem:** Beim Auslagern des PDF-Inspektors in das neue Modulsystem stürzte die Anwendung beim Start mit einem `ImportError` (circular import) ab.
**Ursache:** Die abstrakte Klassenvorlage und die konkrete Umsetzung des Inspektors lagen in der gleichen Datei oder hatten überschneidende Dateinamen (`base_tool.py`), wodurch sich das Modul beim Start selbst importieren wollte.
**Lösung:** Strikte Trennung von Interface und Implementierung. Die Schnittstelle liegt nun völlig isoliert in `tools/base_tool.py`. Neue Werkzeuge wie `tools/pdf_inspector.py` importieren diese Datei lediglich.

---

## 17. Unsichtbare Treeview-Schriftfarben (Tk-8.6.9-Regression)

**Problem:** Per `tag_configure(..., foreground=...)` gesetzte Schriftfarben für einzelne Zeilen in `tree_files` (z.B. "orange" für unbearbeitete Dokumente, "steelblue" für lokale Suchtreffer) wurden nie angezeigt — die Zeilen blieben schwarz. Hintergrundfarben (z.B. die Pastell-Zeilenfarben) funktionierten dagegen einwandfrei.
**Ursache:** Seit Tk 8.6.9 definiert die "clam"-Theme (und andere) eine eigene Zustands-Map für den Style `"Treeview"`, die die per Tag gesetzte `foreground` überschreibt. Betrifft nur `foreground`, nicht `background` — deshalb fiel es bei den Zeilen-Hintergrundfarben nie auf.
**Lösung:** Direkt nach `style.theme_use("clam")` in `gui.py` die Zustands-Map von `"Treeview"` für `foreground`/`background` bereinigen (Standard-Workaround für diesen bekannten Tk-Bug):
```python
def _fixed_style_map(option):
    return [elm for elm in style.map("Treeview", query_opt=option) if elm[:2] != ("!disabled", "!selected")]
style.map("Treeview", foreground=_fixed_style_map("foreground"), background=_fixed_style_map("background"))
```

---

## 18. Inkonsistente Zeilenfarbe nach Jahres-Parität

**Problem:** Manche Dokumente mit ungeradem Jahr wurden blau statt grün hinterlegt (Blau = gerades Jahr, Grün = ungerades Jahr), obwohl die Zuordnung im Code korrekt war.
**Ursache:** `on_folder_select` ermittelte das Jahr für die Hintergrundfarbe erst ganz am Ende erneut per Regex aus dem bereits formatierten `file_date`-String (`PATTERN_YEAR_END`), statt die beim Datums-Parsing weiter oben ohnehin schon bekannte Jahreszahl direkt weiterzugeben. Schlug dieses Nach-Parsen fehl (z.B. bei unüblich formatierten Datums-Strings), griff ein stummer `except Exception: bg_tag = "row_even"`-Fallback — das Dokument erschien dann fälschlich blau statt grün.
**Lösung:** Das Jahr wird jetzt direkt an der Stelle gemerkt, an der `file_date`/`sortable_date` berechnet werden (aus `KID_DokumentenDatum` bzw. dem Datei-Änderungsdatum), und ohne erneutes Parsen für die Hintergrundfarbe wiederverwendet.

**Nachtrag:** In `search_manager.py` (Suchergebnis-Ansicht) gab es dieselbe Zeilenfarben-Logik, aber mit einem eigenständigen Bug: Dort wurde statt des Jahres versehentlich der **Tag des Monats** aus dem Anzeigetext geparst (`row_data[0].split('.')[0]` liefert den Tag, nicht das Jahr). Gleiche Lösung angewendet: `execute_search()` gibt jetzt das bereits bekannte `sort_date.year` mit zurück, statt es später aus dem Text zu raten.

---

## 19. Stilles Überschreiben von Event-Bindings (`bind()` ohne `add="+"`)

**Problem:** Zweimal aufgetreten: (a) Der Doppelklick-Zoom-Reset auf der Vorschau rief nie die `preview_manager`-Variante auf, (b) das Rechtsklick-Menü zum Ein-/Ausblenden von Spalten auf der Kopfzeile reagierte gar nicht — jeweils ohne Fehlermeldung.
**Ursache:** Tkinters `widget.bind(event, handler)` **ersetzt** kommentarlos alle zuvor registrierten Bindings desselben Events auf diesem Widget. Nur `bind(event, handler, add="+")` hängt zusätzlich an. Wird irgendwo später im Aufbau dasselbe Event erneut ohne `add` gebunden, verschwindet das frühere Binding still.
**Lösung:** (a) Duplikat entfernt und auf eine Implementierung konsolidiert. (b) Registrierungs-Reihenfolge beachtet: Zusatz-Bindings (mit `add="+"`) erst NACH dem "Haupt"-Binding registrieren. **Regel:** Vor jedem neuen `bind()` auf ein bereits verwendetes Widget prüfen, ob das Event dort schon gebunden ist — dann entweder `add="+"` verwenden (und auf die Reihenfolge achten) oder einen gemeinsamen Dispatcher bauen.
---

## 20. Datenverlust durch Tests: Migrations-Funktion lief im echten Arbeitsverzeichnis

**Problem:** Beim Entwickeln des KID-Daten-Ordners (Phase 0 des File-Index-Konzepts) hat der Unit-Test-Lauf die ECHTE tags.json des Nutzers gelöscht. Der Tag-Katalog musste aus einem Screenshot und den in den PDFs gespeicherten Tags rekonstruiert werden.
**Ursache:** Verkettung zweier Fehler: (1) `migrate_legacy_layout()` migriert designgemäß die tags.json aus dem AKTUELLEN Arbeitsverzeichnis — die Tests riefen die Funktion auf, ohne das Arbeitsverzeichnis zu wechseln, also fand sie die echte Datei des Projektordners und verschob sie in den Temp-Testordner. (2) Das `tearDown` löschte den Temp-Ordner per `shutil.rmtree` — vorbei am Windows-Papierkorb, unwiederbringlich.
**Lösung/Regeln:**
1. **Tests, die Funktionen mit Dateisystem-Seiteneffekten aufrufen (verschieben/löschen/umbenennen), MÜSSEN vorher per `os.chdir()` in ein eigenes Temp-Verzeichnis wechseln** (und es in tearDown zurücksetzen) — niemals implizit im Projektverzeichnis laufen lassen.
2. `save_tags()` legt seither vor jedem Überschreiben eine `tags.json.bak` an — der Tag-Katalog ist die einzige Datei, deren Inhalt nirgendwo sonst rekonstruierbar vorliegt (die Tags in den PDFs retten nur die zugewiesenen, nicht die Baumstruktur).
3. Generell bei Funktionen, die relative Pfade/CWD nutzen: im Docstring explizit machen, dass sie CWD-abhängig sind.

---

## 21. Kauderwelsch-Titel: unsichtbare Scanner-OCR-Ebene ist Müll, das sichtbare Dokument aber einwandfrei

**Problem:** Etliche PDFs (z.B. Versicherungs-Schreiben) hatten Dateinamen/Titel wie `"die Bayerische Vcnlehcrt nach dem Rcinheiltgcbot"` — sichtbar reiner Kauderwelsch, obwohl das Dokument beim Ansehen völlig normal aussieht. Ein Fuzzy-Wortabgleich gegen einen Wortschatz als "Rechtschreibkorrektur" erwies sich als Sackgasse (bei echten Beispielen nur ~0,45 Ähnlichkeit — weit unter jeder brauchbaren Schwelle, hätte also plausible, aber FALSCHE Wörter eingesetzt).
**Ursache:** Die Dokumente sind ScanSnap-Scans: ein Vollseiten-JPEG plus eine davon unabhängige, **unsichtbare** OCR-Textebene (Render-Modus unsichtbar, typische Ebenen-Fonts Courier/ArialMT). Das ScanSnap-OCR hat teils miserabel gelesen und teils sogar die Seiten-Orientierung falsch erkannt (extrahierter Text wie `"seop isn6nv"` = über Kopf gelesenes "August"). Da beim Ansehen nur das Scan-*Bild* gerendert wird, fällt die kaputte Textebene visuell nie auf — nur `page.get_text()`, Index und abgeleitete Titel/Dateinamen bekommen den Müll.
**Fehldiagnose als eigene Lehre:** Ursprünglich wurde hier eine "defekte `ToUnicode`-Font-Kodierung digital erzeugter PDFs" diagnostiziert — widerlegt durch den Nutzer, dem Falt-Artefakte im Dokument auffielen (Papier wird für Fensterumschläge zweimal gefaltet → ein digital erzeugtes PDF hätte keine Faltkanten!), plus `CreatorTool: PFU ScanSnap Home` in den Metadaten. Verifikation per Seiten-Inspektion: genau ein Bild mit 100% Seitenabdeckung + unsichtbare Textebene = Scan. Die Fehldiagnose war folgenlos für den Fix (Re-OCR des Seitenbilds funktioniert in beiden Fällen), hätte aber Folgeentscheidungen verfälscht: eine kaputte Font-Kodierung wäre im Dokument unreparierbar, eine kaputte OCR-**Ebene** dagegen lässt sich austauschen, ohne das Scan-Bild anzufassen.
**Lösung:** Statt die kaputten Zeichen zu "reparieren" (unmöglich ohne Raten), wird das Bild der Seite per **echtem OCR neu gelesen** (`page.get_pixmap()` + `pix.pdfocr_tobytes(language="deu", tessdata=...)`, eingebaut in PyMuPDF/`fitz`, keine neue pip-Abhängigkeit — nur die Sprachdaten `deu.traineddata` müssen einmalig manuell in `tessdata/` liegen, siehe `app_paths.tessdata_dir()`). Da OCR die ganze Seite liest, aber nur die Betreffzeile als Titel gebraucht wird: Die Position der Betreffzeile lässt sich trotz kaputter Zeichen **über Schriftgröße/Position** finden (`page.get_text("dict")` liefert Bounding-Boxen/Font-Größen korrekt, nur der Text-Inhalt ist kaputt) — dann wird gezielt nur dieser kleine Ausschnitt gecroppt und per OCR gelesen (~30ms statt ganze Seite). Wichtige Detail-Falle dabei: Die naive "größte Schriftgröße pro Zeile" (`max()` über alle Text-Fragmente/Spans einer Zeile) wird leicht durch einzelne, fälschlich übergroß vermessene Mini-Glyphen verfälscht (ein einzelnes Satzzeichen-Fragment kann zufällig eine absurd hohe `size` haben) — robuster ist die Schriftgröße des **längsten** Fragments einer Zeile. Siehe `tools/title_cleanup.py`.

## 22. Dateinamen-Ziffern sind kein Scan-Datum, sondern ein gescheiterter OCR-Versuch des Dokumentdatums

**Problem:** Für eine "Scan-Zeitpunkt"-Spalte lag die Annahme nahe, die automatisch generierten Dateinamen (z.B. `20260413_...pdf`) beginnen mit dem tatsächlichen Scan-Datum — ein erster Entwurf parste dieses Präfix entsprechend (inkl. Erkennung von `YYYYMMDD` vs. `DDMMYYYY` per Jahres-Plausibilität).
**Ursache:** Ein Blick auf echte Problemfälle widerlegte die Annahme: `"60180227_GENTILIA_001.pdf"` ergibt gar kein gültiges Kalenderdatum, und `"50030122_20. APR, 2021.pdf"` enthält offensichtlich zwei nebeneinanderstehende Extraktionsversuche (Ziffern-Rohform *und* Text-Fallback) für **dasselbe** Datum. Das Namens-Präfix ist also selbst nur ein automatischer (oft fehlgeschlagener) Versuch, das inhaltliche **Dokumentdatum** auszulesen — es hat nichts mit dem Zeitpunkt zu tun, an dem die Datei gescannt wurde.
**Lösung:** Jeglisches Parsen des Dateinamens für den Scan-Zeitpunkt verworfen. Einzige Quelle ist jetzt die Datei-Erstellungszeit (`os.path.getctime`, unter Windows ein echtes Erstelldatum). Bekannte Einschränkung bewusst in Kauf genommen: die Erstellungszeit verschiebt sich bei einer Wiederherstellung aus einem Backup auf das Wiederherstellungsdatum — abgefedert dadurch, dass der Wert beim ersten Metadaten-Speichern dauerhaft als `KID_SCAN:` im subject-Feld verankert wird (siehe `pdf_handler.write_custom_metadata`) und ab dann unabhängig vom Dateisystem ist. Siehe `scan_date.py`.
**Lehre:** Bei Annahmen über automatisch generierte Namenskonventionen lohnt sich ein Blick auf mehrere echte Grenzfälle aus der Sammlung, bevor eine Parsing-Heuristik gebaut wird — nicht nur auf die sauberen Standardfälle.

## 23. "Zuletzt benutzt"-Tags verloren ihre Markierung ~1s nach der Zuweisung (Auto-Save)

**Problem:** Ein gerade zugewiesenes Tag wurde unter "Zuletzt benutzt" korrekt blau markiert, verlor diese Markierung aber nach etwa einer Sekunde wieder — nur dort, die reguläre Baum-Position desselben Tags blieb markiert.
**Ursache:** Der stille Auto-Save (`save_manager._perform_autosave`, 1s-Debounce — daher das Timing) ruft `add_recent_tags` auf, das die Kinder des "Zuletzt benutzt"-Knotens **löscht und neu einfügt** (`refresh_recent_tags_ui`) — der Neuaufbau verwirft deren `TAG_ACTIVE`-Markierung. Der manuelle Speicherweg (`_finish_save`) ruft danach `sync_tag_tree_selection()` auf und heilt das; der Auto-Save-Pfad tat das nicht. Regression aus der Umstellung "stiller Auto-Save aktualisiert nur die betroffene Zeile statt Grid-Vollneuaufbau" — dabei ging der Sync-Aufruf am Ende des alten Pfads verloren. Dasselbe Muster gab es schon einmal in `remove_recent_tag` (dort seither mit explizitem Sync gelöst).
**Lösung:** `sync_tag_tree_selection()` auch in `_perform_autosave` direkt nach `add_recent_tags` aufrufen (idempotent, Regressionstest in `test_save_manager.py`).
**Lehre:** Jeder Codepfad, der Teile des Tag-Baums neu aufbaut, muss anschließend die Markierungen re-synchronisieren — beim Aufspalten eines gemeinsamen Ablaufs in Varianten prüfen, welche Abschluss-Schritte des Originals ALLE Varianten brauchen.

## 24. Auto-Save-Fehlschlag: Oberfläche zeigte einen nie gespeicherten Zustand als gespeichert an

**Problem:** Beim Testen der neuen Schreibschutz-Erkennung (siehe #25 und KONZEPT_PDF_ARTEN.md) am echten verschlüsselten PDF: Tag im Baum angeklickt → Fehlermeldung "PDF ist geschützt", aber das Tag blieb trotzdem im Tag-Baum blau markiert, im Eigenschaften-Feld sichtbar UND in der Dokumentenliste-Zeile eingetragen — obwohl auf der Platte nichts geschrieben wurde.
**Ursache:** `save_manager._perform_autosave` aktualisierte Dokumentenliste-Zeile, "Zuletzt benutzt"-Verlauf und Tag-Baum-Markierung **unconditional**, unabhängig vom Rückgabewert `erfolg` von `PDFHandler.save_metadata` — der Erfolgsfall-Code lief also auch nach einem Fehlschlag durch. Zusätzlich blieben Titel-/Tags-Eingabefeld unangetastet (sie enthielten weiterhin den nie gespeicherten, nur eingegebenen Wert), da niemand sie zurücksetzte.
**Lösung:** Der komplette "optimistische" Block (Zeile aktualisieren, Verlauf ergänzen, Baum synchronisieren) läuft jetzt nur noch im `if erfolg:`-Zweig. Im `else`-Zweig ein neues `_revert_fields_to_disk(path)`: liest die Datei per `PDFHandler.get_metadata` frisch aus (unverändert, da der Schreibversuch ja fehlschlug) und setzt Titel-/Tags-Feld darauf zurück, dann `sync_tag_tree_selection()` — das Tag verliert seine blaue Markierung wieder. `_dirty` wird dabei auf `False` gesetzt (nicht mehr `True` wie vorher): nach dem Revert gibt es nichts mehr offen zu speichern, da die Eingabe verworfen wurde (ein automatischer Retry würde bei dauerhaft geschützten Dateien ohnehin nie klappen).
**Lehre:** Bei "optimistischen" UI-Updates (Oberfläche vorgreifend aktualisieren, bevor der eigentliche Speichervorgang bestätigt ist) IMMER einen expliziten Rückweg für den Fehlerfall einbauen — sonst kann die Oberfläche dauerhaft einen Zustand zeigen, der nie auf der Platte existiert hat.

## 25. Vorschau zeigte weiter das vorherige Dokument, wenn das neu ausgewählte nicht darstellbar war

**Problem:** Nach dem Wechsel von einem normalen zu einem passwortgeschützten Dokument blieb im Vorschau-Bereich weiterhin die Seite des VORHERIGEN Dokuments sichtbar, obwohl in der Liste bereits das geschützte Dokument markiert war.
**Ursache:** `preview_manager.update_preview()` ruft `PDFHandler.get_preview_image()` auf und zeichnet das Ergebnis nur im `if result:`-Zweig (bei Erfolg). `get_preview_image` liefert bei nicht öffenbaren PDFs (verschlüsselt, beschädigt) `None` zurück — dafür gab es aber keinen `else`-Zweig: Der Canvas wurde nie geleert (`canvas.delete("all")` steht nur im Erfolgspfad), das alte gerenderte Bild blieb also stehen.
**Lösung:** `else`-Zweig ergänzt: Canvas leeren, Scrollregion zurücksetzen, `photo_preview` auf `None`, Titelzeile auf "Keine Vorschau verfügbar" setzen.
**Lehre:** Jede Funktion mit `if result: ...` und leisem `None`-Rückgabewert braucht einen expliziten `else` — sonst bleibt bei Fehlschlag stillschweigend der ALTE UI-Zustand stehen, statt ihn erkennbar zurückzusetzen.

## 26. Alte OCR-Textebene zurückschreiben: Redaktion darf keine Füllfläche über das Scan-Bild zeichnen

**Kontext:** Für das "Dokument neu erfassen"-Tool (`PDFHandler.recapture_document`) muss die alte, ggf. kaputte unsichtbare OCR-Textebene einer Scan-Seite entfernt und durch frisch erkannten Text ersetzt werden, OHNE das Scan-Bild neu zu komprimieren.
**Falle:** PyMuPDFs `page.apply_redactions()` markiert normalerweise geschwärzte Bereiche standardmäßig mit einer sichtbaren Füllfläche (das ist bei "echten" Schwärzungen ja der Sinn) — ungeprüft übernommen hätte das den kompletten Scan optisch mit einem weißen Rechteck überdeckt, obwohl nur unsichtbarer Text entfernt werden sollte.
**Lösung:** `apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE, graphics=fitz.PDF_REDACT_LINE_ART_NONE, text=fitz.PDF_REDACT_TEXT_REMOVE)` — Bilder/Vektorgrafik werden komplett ignoriert, nur Textobjekte verschwinden. Da die zu entfernende Textebene selbst unsichtbar war (Render-Modus 3), gibt es ohnehin nichts sichtbar zu überdecken. Vor dem Einbau per Pixmap-Vergleich (`page.get_pixmap().tobytes()` vor/nach Redaktion) verifiziert: Ergebnis war byteidentisch.
**Lehre:** Bei jeder Redaktion/Content-Manipulation, die NICHT das sichtbare Bild verändern soll, explizit `images=PDF_REDACT_IMAGE_NONE` setzen und das Ergebnis per Pixmap-Rendering (nicht nur per extrahierten Bild-Bytes!) gegenprüfen — extrahierte Bild-Bytes allein hätten eine zusätzlich darübergezeichnete Füllfläche nicht aufgedeckt, nur der gerenderte Seiteninhalt zeigt die tatsächliche Optik.

## 27. PDF-Inspektor blockierte spätere Verschieben/Löschen-Operationen mit "[WinError 32]"

**Problem:** Nutzer öffnete den PDF-Inspektor auf einer Datei, versuchte diese Datei später aus dem Papierkorb wiederherzustellen — Fehlermeldung "[WinError 32] Der Prozess kann nicht auf die Datei zugreifen, da sie von einem anderen Prozess verwendet wird". Die Datei war dabei bereits an den Zielort KOPIERT, nur die Quelle (im Papierkorb) blieb zusätzlich liegen — ein stilles Duplikat statt eines sauberen Verschiebens.
**Ursache 1 (Handle-Leak):** `PDFInspectorWindow._load_data()` rief `doc.close()` als LETZTE Zeile im `try`-Block auf statt in einem `finally`/Kontextmanager. Jede Exception zwischen `fitz.open()` und dieser letzten Zeile (z.B. beim Lesen von Metadaten/XMP/Fonts/Text eines ungewöhnlichen PDFs) übersprang das Schließen — das Dateihandle blieb für die gesamte Lebensdauer des Inspektor-Fensters offen.
**Ursache 2 (stilles Duplikat bei Teilfehler):** `shutil.move()` fällt bei einem `os.rename()`-Fehler (z.B. weil die Datei noch offen ist) intern auf Kopieren+Löschen zurück. Schlägt dabei NUR das Löschen der (noch gesperrten) Quelle fehl, bleibt die bereits erstellte Kopie am Ziel liegen — der Nutzer sieht nur eine Fehlermeldung, merkt aber nicht, dass die Datei jetzt doppelt existiert.
**Lösung:** (1) `PDFInspectorWindow._load_data()` nutzt jetzt `with fitz.open(...) as doc:` statt eines manuellen `doc.close()` am Ende des try-Blocks — das Handle wird IMMER freigegeben, auch bei einer Exception. (2) Neuer Helfer `file_operations.FileOperations._verschiebe_ohne_duplikat()`: bei einem fehlgeschlagenen `shutil.move()` wird geprüft, ob sowohl Quelle als auch Ziel existieren (= Kopie gelungen, Löschen gescheitert) — dann wird die überzählige Zielkopie wieder entfernt, bevor der Fehler weitergereicht wird. Beide Stellen (Papierkorb-Verschieben in `delete_file`, Wiederherstellen in `restore_file`) nutzen jetzt diesen Helfer statt `shutil.move()` direkt.
**Lehre:** `fitz.open()` (und generell jede Ressource mit explizitem `.close()`) IMMER per Kontextmanager oder `try/finally` öffnen, nie mit `.close()` als letzter Zeile in einem `try`-Block ohne `finally` — sonst hängt die Freigabe von einem fehlerfreien Durchlauf ab. Zusätzlich: `shutil.move()` ist NICHT atomar (Kopieren+Löschen als Fallback) — wer robust gegen "Zieldatei bereits offen"-artige Fehler sein will, muss den Teilerfolg selbst erkennen und aufräumen.

**Nachtrag (zweiter Live-Fund, gleiche Fehlermeldung, andere Ursache):** Der WinError 32 trat auch NACH dem Inspektor-Fix wieder auf. Diagnose zur Laufzeit ergab: es liefen unbemerkt ZWEI Instanzen des Dokumenten-Managers parallel (zweimal aus VS Code per Debugger gestartet, 2 Sekunden auseinander). Die zweite Instanz beobachtet mit ihrem eigenen Watchdog denselben Hauptordner und liest bei jeder Dateiänderung dieselben Dateien für ihren Suchindex nach — solche Lesefenster dauern nur Sekundenbruchteile, aber Python-Datei-Handles erlauben unter Windows kein gleichzeitiges Verschieben (kein `FILE_SHARE_DELETE`). Trifft ein Wiederherstellen/Löschen genau in so ein Fenster, schlägt es fehl, obwohl Sekundenbruchteile später alles frei wäre. Dieselbe Fehlerklasse verursachen auch Virenscanner und der Windows-Indexdienst. **Lösung:** `_verschiebe_ohne_duplikat` versucht den Move jetzt bis zu 3× mit 0,3s Pause (`MOVE_VERSUCHE`/`MOVE_WARTEZEIT_S`), bevor es aufgibt; die Fehlermeldung fragt zusätzlich explizit nach einem anderen offenen Programm bzw. einer doppelt gestarteten Instanz. **Lehre:** Transiente Datei-Sperren sind unter Windows Normalzustand, kein Ausnahmefall — Datei-Operationen, die direkt nach einer beobachtbaren Änderung laufen (Watchdog!), brauchen grundsätzlich eine kleine Retry-Schleife. Und: bei "unerklärlichen" Sperren zuerst prüfen, ob das eigene Programm mehrfach läuft.

## 28. Neu-Erfassen konnte eine bereits gute alte OCR-Ebene durch eine schlechtere neue ersetzen

**Problem:** Nutzer testete "Dokument neu erfassen" an einem stark degradierten Scan aus der Sammlung — die neu erkannte OCR-Textebene war teilweise SCHLECHTER als die ursprüngliche (der Scanner hatte an der Stelle offenbar zufällig besser gelesen als der erneute Tesseract-Lauf). Bis dahin überschrieb `recapture_document` jede Scan-Seite bedingungslos.
**Ursache:** Kein Qualitätsvergleich vor dem Ersetzen — die Annahme "ein erneutes OCR ist immer mindestens so gut wie das vorhandene" stimmt bei stark beschädigten Vorlagen nicht zuverlässig.
**Lösung:** `PDFHandler._waehle_bessere_textebene(alte_worte, neue_worte)` (reine, einzeln testbare Funktion) vergleicht pro Seite die Textqualität (`text_quality.textqualitaet_prozent`, gleiche Kauderwelsch-Heuristik wie `tools/title_cleanup.py`) von alter und neuer Wortliste; die alte gewinnt nur, wenn sie nachweisbar (nicht `None`) UND mindestens so gut ist. Kein echtes Wort-für-Wort-Mergen zweier OCR-Ergebnisse (fehleranfällig), sondern die konservativere "behalte pro Seite die insgesamt bessere Version". Die Erfolgsmeldung nennt jetzt explizit, bei wie vielen Seiten die alte Ebene beibehalten wurde.
**Lehre:** Bei "verbessere automatisch"-Features nie blind annehmen, dass der neue, aufwändigere Weg immer besser ist als der Status quo — ein Vorher/Nachher-Vergleich mit einer (auch groben) Qualitätsmetrik ist die einzige Absicherung gegen echte Regressionen, gerade bei probabilistischen Schritten wie OCR.

## 29. Vollautomatik-Analyse schlug mit "HTTP Error 400: Bad Request" fehl, sobald die Ordnerliste wuchs

**Problem:** Beim ersten Live-Test von "Vollautomatik: Ablage-Vorschau" (Seniorenmodus) schlug die KI-Analyse für ein echtes Dokument mit `HTTP Error 400: Bad Request` fehl — der Log-Eintrag zeigte nur den nichtssagenden `str(e)`, keine Details.
**Ursache:** Die eigentliche Fehlermeldung steckte im Response-BODY des `HTTPError`, den `ollama_client.suggest_filing` nicht auslas (`urllib.error.HTTPError` propagiert einfach weiter). Ein read-only-Reproduktionsskript gegen den echten Ollama-Server (`e.read().decode()`) zeigte den wahren Grund: `"request (4254 tokens) exceeds the available context size (4096 tokens)"`. Die Sammlung hat inzwischen 53 Ablage-Ordner — Ordnerliste + Tag-Katalog + das Bild (Vision-Modelle verbrauchen dafür selbst schon ~3300 Tokens) sprengten das Standard-Kontextfenster des Modells. Mit einer kleinen Test-Ordnerliste (3 Einträge) war der Fehler nicht reproduzierbar — das Problem skaliert mit der Sammlungsgröße, nicht mit einem bestimmten Dokument.
**Lösung:** `ollama_client._geschaetzter_num_ctx(prompt)` schätzt den Tokenbedarf grob (~3,5 Zeichen/Token für deutschen Text + fester Bild-Puffer) und rundet großzügig (Faktor ~2) auf; das Ergebnis wird als `options.num_ctx` im Ollama-Request mitgeschickt (`suggest_filing` UND `suggest_title_and_tags`, da auch dort der Tag-Katalog wachsen kann). Ollama lädt das Modell bei Bedarf mit dem größeren Kontext neu.
**Lehre:** Bei `urllib.error.HTTPError` IMMER `e.read()` auslesen, bevor man den Fehler nur als String weiterreicht — der Response-Body enthält bei APIs wie Ollama oft die eigentliche, sofort verwertbare Diagnose. Und: Features, deren Prompt-Länge mit der Sammlungsgröße wächst (hier: die komplette Ordnerliste), brauchen von Anfang an ein mitwachsendes Kontextfenster statt eines festen Standardwerts — sonst funktioniert ein Feature nur so lange, wie die Sammlung klein bleibt, und bricht erst beim Nutzer mit realen Daten.

## 30. Vollautomatik wählte fast immer den Auffangordner "_Anderes", obwohl der Absender korrekt erkannt wurde

**Problem:** Nach dem num_ctx-Fix lief die Vollautomatik-Analyse zwar durch, aber der Zielordner war praktisch immer `_Anderes` (ein echter Auffang-/Sonstiges-Ordner der Sammlung) — auch wenn `absender` in derselben KI-Antwort korrekt "Gentilia Deutschland Versicherung AG" lautete und ein passender Ordner (`G - H - I - J - K - L\Gentilia`) in der mitgeschickten Liste stand.
**Ursache:** Die KI sollte bislang selbst aus einer Liste von 53 vorhandenen Ordnern den passenden auswählen (Aufgabe 5 im Prompt). Ein Vision-Modell ist beim zuverlässigen "Durchsuchen" einer langen Liste im eigenen Kontext offenbar deutlich schwächer als beim reinen Erkennen von Dokumentinhalten (klassisches "lost in the middle"/Listen-Problem bei LLMs) — es griff wiederholt zum naheliegenden, kurzen "Sicheren" Namen `_Anderes`, statt den eigenen (korrekten!) Absender-Vorschlag gegen die Liste abzugleichen. Ein Diagnoseskript gegen den echten Server (mit den echten 53 Ordnern der Sammlung) reproduzierte das zuverlässig; mit einer kurzen 3-Ordner-Testliste trat der Fehler dagegen NICHT auf — auch hier skaliert das Problem mit der Sammlungsgröße.
**Lösung:** Die Zielordner-Aufgabe wurde komplett aus dem KI-Prompt entfernt (`FILING_PROMPT_TEMPLATE`/`suggest_filing` liefern nur noch Titel/Tags/Absender/Datum). Ein neuer, rein deterministischer Matcher `auto_pilot.finde_passenden_ordner(absender, vorhandene_ordner)` vergleicht den von der KI gelieferten Absender case-insensitiv als Teilstring gegen den letzten Pfadbestandteil jedes vorhandenen Ordners (in beide Richtungen, da mal der Ordner kürzer ist als der volle Firmenname und umgekehrt). Kein Treffer → neuer Ordner nach dem Absendernamen (bisheriges Verhalten). Am echten Server verifiziert: derselbe "Gentilia"-Fall matcht jetzt korrekt, ein unbekannter Absender ("Volkswagen Insurance Brokers GmbH") erzeugt korrekt einen neuen Ordner statt `_Anderes`.
**Lehre:** Eine KI zuverlässig gegen eine WACHSENDE Liste (hier: alle Ordner der Sammlung) "suchen" zu lassen, ist ein Skalierungsrisiko, das mit wenigen Testfällen unentdeckt bleibt — Suchen/Matchen in einer bekannten, endlichen Liste ist eine Aufgabe für deterministischen Code, nicht für ein generatives Modell. Die KI sollte nur das liefern, was NICHT anders zu ermitteln ist (hier: den Absender aus dem Dokumentbild lesen); alles, was sich danach als reiner String-/Datenabgleich gegen bekannte, lokale Daten formulieren lässt, gehört in testbaren Python-Code.

**Nachtrag (Folgebug beim Live-Test des Fixes):** `baue_entscheidung` ließ `zielordner` als `None` (statt `""`) stehen, wenn WEDER ein passender Ordner gefunden noch ein Absender erkannt wurde (`finde_passenden_ordner` liefert `None`, und der `elif absender`-Zweig griff mangels Absender nicht) — `tools/auto_filer.py`s `entscheidung["zielordner"] + " (neu)"` stürzte dann mit `TypeError: unsupported operand type(s) for +: 'NoneType' and 'str'` ab, obwohl die Zeile korrekt als "unsicher" erkannt worden wäre. Fix: `zielordner = zielordner or ""` direkt vor der Rückgabe - der Vertrag nach außen ist jetzt "immer ein String". **Lehre:** Wenn eine Funktion `None` als "kein Ergebnis"-Signal INTERN nutzt (hier: `finde_passenden_ordner`), muss die aufrufende Funktion das VOR der Rückgabe an die Außenwelt in den vereinbarten Typ normalisieren (hier: leerer String) - sonst leckt die interne Sentinel-Semantik in Code, der sie nicht erwartet.

## 31. Dokumentenliste zeigte nach einer Datei-Operation weiter den alten Stand (verschobene/gelöschte Dateien blieben sichtbar)

**Problem:** Beim Live-Test von "Jetzt einsortieren" (Vollautomatik Schritt 2) blieben Dokumente, die gerade nach `0_Unsicher` verschoben wurden, weiterhin in der Dokumentenliste (`tree_files`) des Hauptfensters stehen — obwohl die Datei auf der Festplatte bereits am neuen Ort lag.
**Ursache:** `refresh_folder_tree()` baut den Ordnerbaum (`tree_folders`) komplett neu auf und verwirft dabei dessen Selektion. Ein direkt danach aufgerufenes `on_folder_select(None)` bricht in diesem Zustand sofort mit `if not items: return` ab (keine Selektion mehr vorhanden) — das Dokumenten-Grid wird also gar nicht neu geladen. `tools/auto_filer.py`s `_starte_einsortierung` rief genau diese Reihenfolge (`refresh_folder_tree()` gefolgt von `on_folder_select(None)`) direkt hintereinander auf.
**Lösung:** Denselben Ablauf wie in `file_operations.delete_file`/`restore_file` übernommen: den aktuell selektierten Ordnerpfad VOR `refresh_folder_tree()` merken, danach mit `folder_manager._select_and_open_path(pfad)` gezielt wieder aufklappen/selektieren (das löst intern `on_folder_select` MIT gültiger Selektion aus) statt blind `on_folder_select(None)` zu rufen.
**Lehre:** Dieses Muster (Ordnerbaum-Neuaufbau verwirft die Selektion, ein nachfolgendes `on_folder_select(None)` ist dadurch ein stiller No-Op) ist bereits zweimal unabhängig aufgetreten (`delete_file`/`restore_file`, jetzt `auto_filer.py`) — jede NEUE Stelle, die nach einer Datei-Operation `refresh_folder_tree()` aufruft, muss den Selektions-Pfad vorher sichern und über `_select_and_open_path()` wiederherstellen, niemals nur `on_folder_select(None)` blind hinterherschicken.

## 32. Vollautomatik: KI lieferte den EMPFÄNGER als Ordnernamen ("Mustermann, Hermann" bei Absender "Amsel BKK")

**Problem:** Nach Einführung der Telefonbuch-Ordnernamen (29.08.2026: 'Carius, Dr. Emil (Zahnarzt)' statt des vollen Praxisnamens) lieferte die KI in einer read-only-Diagnose gegen den echten Server bei zwei von sechs Dokumenten den Namen des Adressaten als Ordnernamen — bei einer Versicherungsrechnung von "Amsel BKK" und einer von "HKV" jeweils "Mustermann, Hermann" (den Empfänger). Der Absender selbst war in derselben Antwort korrekt erkannt. Ohne Gegenprüfung wäre ein Sammelordner unter dem Namen des Nutzers entstanden, in dem sich Post beliebiger Firmen gestapelt hätte.
**Ursache:** Der Prompt verlangte für Personen die Form "Nachname, Vorname" — auf einer Firmenrechnung ist der einzige Personenname aber der Adressat im Anschriftenfeld. Das Modell folgte der Formvorgabe und griff zum nächstbesten Personennamen. Klassischer Fall von "Formatvorgabe schlägt Semantik" bei generativen Modellen.
**Lösung:** Zweigleisig, nach dem Grundprinzip des Seniorenmodus (KI schlägt vor, Code entscheidet): (1) Prompt schärfen ("bezeichnet IMMER den Absender aus Aufgabe 3 — NIEMALS den Empfänger") — das hilft, reicht aber allein nicht. (2) Deterministische Sperre `auto_pilot.ordnername_passt_zum_absender()`: ein Ordnername wird nur übernommen, wenn jedes Wort seines Kerns (ab 3 Zeichen) im Absender-String vorkommt; sonst wird er verworfen und der Absender selbst ist der Ordnername. Zweiter Live-Lauf nach dem Fix: "Mustermann, Hermann" → verworfen → "Amsel BKK"; ebenso ein vermutlich mitunterzeichnender Arzt ("Bergmann, Dr. med. Rolf") bei einer Radiologie-Praxis → "Radiologie und nuklearmedizin MUSTERSTADT". Regressionstest `test_empfaenger_als_ordnername_wird_verworfen`.
**Lehre:** Jedes neue Feld, das die KI "formatieren" soll, braucht eine deterministische Plausibilitätsprüfung gegen ein Feld, dem man schon vertraut — hier: Ordnername gegen Absender. Und wie bei #29/#30: mit echten Dokumenten testen, BEVOR es in den Nutzer-Lauf geht — sechs Dokumente reichten, um den Fehler zu sehen.

## 33. Vollautomatik: Vision-Modell las "Musterbein" statt "Musterheim" — dpi war NICHT der Hebel, der Sammlungs-Wortschatz schon

**Problem:** Im 411-Dokumente-Testlauf erzeugte die KI den Titel "Stromverbrauch Prüfung Musterbein" — gemeint war der Ortsteil Musterheim. Zwei Zeichen daneben (b↔h, n↔m). Folge über den Titel hinaus: die unscharfe Suche toleriert nur ~1 Fehler pro Wort (Ähnlichkeit ≥ 0,8; hier 0,75) — eine Suche nach "Musterheim" hätte das Dokument über den Titel NICHT gefunden.
**Erste Hypothese (widerlegt):** Render-Auflösung. `render_page_png` rendert mit 150 dpi, ein 300-dpi-Scan verliert dabei die Hälfte der Pixel. Read-only-Experiment an drei Musterheim-Dokumenten mit 150/200/300 dpi: alle neun Aufrufe lasen "Musterheim" korrekt — der Fehler ist sporadisch (Modell-Nichtdeterminismus), nicht auflösungsbedingt; 300 dpi verdreifacht nur die Bildgröße. dpi blieb bei 150.
**Lösung:** Deterministischer Abgleich der KI-Titelwörter gegen den Wortschatz der eigenen Sammlung (`auto_pilot.korrigiere_titel` → `spell_correct.correct_proper_noun`): ein Titelwort, das im Wortschatz UNBEKANNT ist, wird durch ein bekanntes Wort in Editierdistanz ≤ 2 ersetzt — aber nur, wenn es mindestens 5 Zeichen lang ist und der Kandidat mindestens 2-mal in der Sammlung vorkommt (ein Einzelfund kann selbst ein OCR-Fehler sein); Distanz 1 hat Vorrang. Der bestehende Fließtext-Korrektor bleibt bewusst bei Distanz 1 — die Zusatzbedingungen machen Distanz 2 nur für einzelne, exponierte Wörter vertretbar. Der Wortschatz ist der persistierte Sammlungs-Wortschatz (Index) PLUS die ersten Seiten des aktuellen Stapels (`baue_titel_wortschatz`) — so wirkt es auch in einer frischen Sammlung ohne Index-Historie, denn "Musterheim" steht in den Adresszeilen des Stapels selbst. Jede Korrektur wird in der Ergebnis-Spalte angezeigt ("[Titel korrigiert: Musterbein→Musterheim]"), damit eine Fehlkorrektur sofort auffällt.
**Lehre:** Bei Lesefehlern eines Vision-Modells zuerst prüfen, ob der Fehler reproduzierbar ist, bevor man an der Eingabe (Auflösung) dreht — ein sporadischer Fehler braucht ein Korrektiv, keine bessere Eingabe. Und: was das Programm über die Sammlung schon weiß (hier der Wortschatz), ist die stärkste Gegenprüfung für das, was ein Modell erzeugt — gleiche Philosophie wie #30/#32.

## 34. Ordnerbaum klappte bei jedem Dateiklick und bei jeder Explorer-Änderung komplett zu

**Problem:** Nutzer klappt alle Ordner auf, klickt eine Datei an — der ganze Baum fällt zusammen. Dasselbe beim Anlegen/Löschen eines Ordners im Windows-Explorer. Aufgefallen erst mit der neuen Sammlung auf Laufwerk D: (30.08.2026).
**Ursache:** `refresh_folder_tree()` löscht alle Knoten und baut den Baum neu — nur die Wurzel offen. Aufgerufen wird es nicht nur nach eigenen Aktionen, sondern über `on_filesystem_event → sync_ui` bei JEDEM Watchdog-Ereignis. Der Watchdog meldet unter Windows auch Änderungen der **Zugriffszeit** (`FILE_NOTIFY_CHANGE_LAST_ACCESS` gehört zu seinen Standard-Flags) — und die setzt Windows beim Rendern der Vorschau, sobald NTFS-Last-Access-Updates auf dem Laufwerk aktiv sind (auf Laufwerk D: offenbar, auf C: nicht). Ein bloßer Klick wurde so zum „Dateisystem-Ereignis" und riss den Baum ein. Nur `file_operations.on_file_drop` hatte sich lokal mit einem eigenen save/restore-Zustand geschützt; alle anderen Aufrufer (Watchdog, Löschen, Wiederherstellen, Ordner anlegen/umbenennen, Vollautomatik) nicht.
**Lösung:** Der Aufklapp-Zustand wird **zentral in `refresh_folder_tree()`** gerettet und wiederhergestellt (`_offene_ordner` / `_klappe_auf`, pfadbasiert) — unabhängig davon, wer den Neuaufbau auslöst. Der lokale save/restore-Block in `on_file_drop` ist damit entfallen. Die **Selektion** stellt weiterhin der Aufrufer per `_select_and_open_path` her (siehe #31): `selection_set()` löst `<<TreeviewSelect>>` und damit einen Grid-Neuaufbau aus — das soll nicht jeder Baum-Neuaufbau implizit tun.
**Lehre:** Zustand, den ein Neuaufbau zerstört (Aufklappen, Scrollposition, Auswahl), gehört in die Neuaufbau-Funktion selbst, nicht in einzelne Aufrufer — sonst schützt sich genau ein Aufrufer, und jeder neue vergisst es (hier: fünf von sechs). Und: Watchdog-Ereignisse sind unter Windows gesprächiger als erwartet (Zugriffszeit!) — jeder Sync-Pfad muss davon ausgehen, dass er auch ohne echte Änderung läuft.

## 35. Frische Installation: KI-Analyse scheitert mit HTTP 500 „unknown model architecture: 'mllama'"

**Problem:** Erster Praxistest der EXE auf einem fremden PC (30.08.2026): Server über Tailscale erreichbar, aber jede Analyse endet mit `HTTP Error 500 … error loading model: unknown model architecture: 'mllama'`.
**Ursache:** In der neuen `settings.json` fehlte `ollama_model`, also griff `ollama_client.DEFAULT_MODEL` — und das stand noch auf dem Modell aus den ersten Experimenten (`llama3.2-vision`, Architektur „mllama"), das der Server in seiner heutigen Ollama-Version nicht mehr laden kann. Auf dem Entwickler-PC fiel das nie auf, weil dort `qwen2.5vl:7b` seit Monaten in der `settings.json` steht.
**Lösung:** `DEFAULT_MODEL = "qwen2.5vl:7b"` (das Modell, das laut Projekte-Wiki tatsächlich auf dem Server liegt). Sofort-Workaround auf dem betroffenen PC: Tools → Einstellungen → Modell `qwen2.5vl:7b` eintragen, „Verbindung testen" zeigt die geladenen Modelle.
**Lehre:** Standardwerte, die nur auf dem Entwickler-Rechner nie greifen, sind unsichtbar falsch — jeder Praxistest auf einem frischen PC ist auch ein Test der Defaults. Sinnvoll wäre außerdem, dass „Verbindung testen" warnt, wenn das eingestellte Modell nicht in der Liste des Servers auftaucht.

## 36. Praxistest bei einem Beta-Tester: neue Ordner flach statt in `[A-F]`, und Landratsamt-Post beim Radiologen

**Problem:** Erster Lauf der Vollautomatik auf einer frisch generierten Standard-Struktur (30.08.2026, 411 Dokumente): (a) alle neuen Ordner landeten flach im Hauptordner statt unter `[A-F]`, `[G-L]` …; (b) mehrere Dokumente von Finanzamt/Landratsamt bekamen den Zielordner „Radiologie und Nuklearmedizin MUSTERSTADT".
**Ursache:** (a) `finde_buchstabengruppe` kannte nur die aufgezählte Form `A - B - C - D - E - F` (Entwickler-Sammlung), nicht die **Bereichsform `[A-F]`**, die `folder_default.json` als Standard erzeugt — der Default der eigenen App war für die Automatik unsichtbar (gleiche Lehre wie #35: Defaults, die der Entwickler nie nutzt). (b) `finde_passenden_ordner` erlaubte Teilstring-Treffer in beide Richtungen. Die KI lieferte als Telefonbuch-Ordnernamen `Musterstadt, Landratsamt`, dessen Kern `Musterstadt` als Teilstring in „Radiologie und Nuklearmedizin Musterstadt" steckt — und da der längere Ordnerkern gewinnt, schlug der Radiologe den gerade angelegten Ordner „Landratsamt Musterstadt".
**Lösung:** (a) `buchstaben_der_gruppe()` versteht beide Formen (`[A-F]`, `A-F`, `A - B - C`). (b) `_namen_passen()`: Ordnerkern muss als **ganze Wortfolge** im Absender stehen ODER der Absender muss der **Wortanfang** des Ordnerkerns sein (`Stadtwerke` → `Stadtwerke Musterstadt`); ein Treffer mitten im Ordnernamen zählt nicht mehr.
**Lehre:** Ortsnamen sind Gift für Teilstring-Vergleiche — jeder zweite Absender in einer Sammlung trägt denselben Ort. Und: was die KI als „Kernname" liefert, kann eine Stadt sein; der deterministische Abgleich muss das aushalten.

## 37. Release-EXE: „Tesseract-Sprachdaten fehlen" trotz `tessdata`-Ordner neben der EXE

**Problem:** Beim Praxistest (30.08.2026) meldete „Dokument neu erfassen" in der gepackten EXE fehlende Sprachdaten — auch ein `tessdata`-Ordner neben der EXE hätte nicht geholfen.

**Ursache:** `app_paths.tessdata_dir()` leitete den Pfad aus `__file__` ab. In einer PyInstaller-Onefile-EXE liegt `__file__` im temporären Entpackordner (`sys._MEIPASS`, bei jedem Start neu), nicht neben der EXE. Die Sprachdaten waren zudem nie Teil des Pakets (`.gitignore`, „einmalig manuell herunterladen") — für einen Senioren-PC keine Option.

**Lösung:** `app_paths.app_dir()` liefert den echten Installationsordner (`sys.executable` bei `sys.frozen`, sonst Quellordner); `tessdata_dir()` nimmt zuerst einen `tessdata`-Ordner dort, sonst die per `--add-data "tessdata;tessdata"` eingebettete Kopie (`deu.traineddata` aus tessdata_fast, 1,5 MB, Apache-2.0). Merksatz: in der EXE nie `__file__` für „neben dem Programm" verwenden — `__file__`/`_MEIPASS` = mitgelieferte Dateien, `sys.executable` = Ort der Installation.

## 38. Tags mit Komma im Katalog („Mustermann, Uta", „Hermann Mustermann, Werner Mustermann")

**Problem:** Nach den ersten Vollautomatik-Läufen (30.08.2026) standen im Tag-Katalog Einträge wie `Mustermann, Uta` und `Hermann Mustermann, Uta Mustermann, Peter Mustermann`. Beim Zuweisen an ein Dokument zerfielen sie still in ihre Teile, beim nächsten Lesen entstanden daraus scheinbar neue Tags.

**Ursache:** Das PDF-Schlagwortfeld (`keywords`) ist ein kommagetrennter String — die App splittet überall an `,` (`tag_manager`, `save_manager`) und joint mit `", "`. Ein Tag, der selbst ein Komma enthält, kann diesen Rundlauf nie überleben. Die Kommas kamen von der KI: mehrere Empfänger im Anschriftenfeld wurden als EIN String mit Kommas geliefert, einmal in Telefonbuch-Form.

**Lösung:** Kommas sind in Tags grundsätzlich unmöglich. (1) `auto_pilot.tags_mit_empfaenger` trennt KI-Tags an Kommas in einzelne Tags, mehrere Empfänger zerlegt `teile_empfaenger`, eine einzelne Person in Telefonbuch-Form wird kommalos (`Mustermann, Uta` → `Uta Mustermann`). (2) `tag_manager.add_tags_to_catalog` ersetzt Kommas durch Leerzeichen als letzte Sperre. (3) Der Prüf-Dialog des Ergänzen-Tools nimmt keine Kommas an — der kurzzeitig vorhandene Knopf „Komma setzen/entfernen" wurde deshalb wieder entfernt. Merksatz: Ein Tag darf kein Zeichen enthalten, das irgendwo als Trennzeichen dient. Gleichzeitig eingeführt: `korrigiere_tag` — Rechtschreib-Schutz gegen Katalog-Varianten wie `Mustereheim` neben `Musterheim` (Editierdistanz 1 ab 6 Zeichen, sonst Wortschatz; nie für Personen-Tags).

## 39. Release-EXE v0.9.3: zwei Tools fehlten im Menü („Dubletten finden", „Tags ergänzen (KI)")

**Problem:** Aus dem Quellcode lief alles, in der von GitHub geladenen EXE fehlten beim Praxistest (31.08.2026) genau die beiden neuen Tools — ohne Fehlermeldung.

**Ursache:** Der `ToolManager` lädt die Plugins über den Dateipfad (`importlib.util.spec_from_file_location`). PyInstaller sieht diese Importe nicht: `--add-data "tools;tools"` legt die `.py`-Dateien nur als DATEN ins Paket, die darin importierten Module fehlten aber im Code-Archiv — `dubletten.py` (von `tools/dubletten_finder.py` importiert) und die Tool-Module selbst, die `tools/tag_ergaenzer.py` per `from tools.dubletten_finder import …` braucht. Beide Importe scheiterten zur Laufzeit, der Ladefehler ging per `print()` auf die bei `--noconsole` unsichtbare Konsole.

**Lösung:** (1) `tools/__init__.py` macht `tools` zu einem echten Paket, (2) der Build läuft über `build_exe.py` mit `--collect-submodules tools` — damit landen alle Tool-Module MIT ihren Importen im Paket, neue Tools brauchen keine neuen Flags mehr, (3) `build_exe.py` prüft die fertige EXE gegen das Projekt (jedes App-Modul, jedes Tool, Vorlagen, `tessdata`) und bricht bei Lücken ab, (4) `ToolManager._load_tools` schreibt Ladefehler ins Log. Merksatz: Was der Code erst zur Laufzeit importiert, muss beim Packen ausdrücklich eingesammelt UND danach nachgewiesen werden — „läuft aus dem Quellcode" sagt nichts über die EXE.

## 40. Vollautomatik startete nicht: „00_Posteingang" UND „0_Posteingang" nebeneinander

**Problem:** Praxistest 31.08.2026: Der ScanSnap legte ein Dokument in den Posteingang, die eingeschaltete Vollautomatik rührte es nicht an. In der Sammlung existierten ZWEI Posteingang-Ordner („00_Posteingang" aus der Anfangszeit, „0_Posteingang" aus der ausgelieferten Vorlage).

**Ursache:** `finde_posteingang()` lieferte den ERSTEN Treffer der Verzeichnis-Reihenfolge — der Scanner schrieb aber in den anderen Ordner. Der Wächter weckte den Dienst zwar (er reagiert auf jedes Dateisystem-Ereignis), doch dessen Arbeitsliste (`sammle_posteingang_dokumente`) las nur den einen Ordner: nichts zu tun, Dokument bleibt liegen.

**Lösung:** `finde_posteingaenge()` liefert ALLE Posteingang-Ordner (Standardname `0_Posteingang` zuerst), `sammle_posteingang_dokumente` leert jeden davon — Vollautomatik und „Posteingang verarbeiten" arbeiten damit automatisch beide Ordner ab. Empfehlung an den Nutzer bleibt trotzdem: auf EINEN Posteingang zusammenführen (der Standard ist `0_Posteingang`). Merksatz: Wo ein Name „flexibel erkannt" wird, muss die Verarbeitung mit MEHREREN Treffern rechnen — sonst gewinnt still der falsche.

## 41. Leeres Fenster nach dem Start: nur Menü und graue Vorschau, linke Spalten zugeklappt

**Problem:** Am Tester-PC (per RustDesk gestartet, 31.08.2026) kam v0.9.4 mit leerem Fenster hoch: Menüleiste, darunter nur die graue Vorschaufläche, Ordnerbaum und Dateiliste waren auf Breite 0 zusammengeschoben. Reproduzierbar bei JEDEM Start, aus dem Quellcode am Entwickler-PC nie.

**Ursache:** `apply_saved_layout` setzte die gespeicherten Trennlinien 200 ms nach dem Start per `main_pane.sashpos(...)`. `ttk.PanedWindow` kürzt diese Werte aber immer auf die AKTUELL vorhandene Breite — und hatte Tk das Fenster zu diesem Zeitpunkt noch nicht vermessen (`winfo_width() == 1`, möglich bei langsamem EXE-Start, Fernwartung, Virenscanner), wurden aus `[260, 700]` die Werte `[-10, -5]`, nach dem Layout `[0, 5]`. Beim Beenden schrieb `on_closing` genau diese kaputten Werte in die `settings.json` — ab da startete die App jedes Mal falsch, ohne je wieder herauszufinden. Lokal nachgestellt: `sashpos()` vor dem ersten Layout liefert exakt diese Werte.

**Lösung:** Drei Sperren in `gui.py`: (1) `apply_saved_layout` setzt erst, wenn `sashes_passen(...)` bestätigt, dass das Fenster wirklich breit genug ist, und sieht sonst bis zu 20-mal im 100-ms-Takt nach; (2) `on_closing` speichert Trennlinien nur noch, wenn `sashes_gueltig(...)` zustimmt (sonst bleibt die letzte gute Aufteilung stehen und es gibt einen Log-Eintrag); (3) „Ansicht → Standard-Layout wiederherstellen" schiebt die Trennlinien jetzt auch sichtbar auf `standard_sashes(...)` zurück — die Rettung, wenn doch einmal nichts mehr zu greifen ist. Sofort-Hilfe an einem betroffenen Rechner ohne neue EXE: Trennlinie am linken Rand mit der Maus nach rechts ziehen und die App normal schließen (dann wird die gute Aufteilung gespeichert), oder in der `settings.json` neben der EXE den Eintrag `sash_positions` löschen. Merksatz: Geometrie-Werte nie setzen, bevor das Fenster vermessen ist — und einen aus der Oberfläche gelesenen Wert vor dem Speichern auf Plausibilität prüfen, sonst frisst sich ein Anzeigefehler dauerhaft in die Einstellungen.

## 42. 125-%-Skalierung: Texte laufen aus Fenstern heraus, Tabellenspalten werden abgeschnitten

**Problem:** Am Tester-PC (125 % Skalierung UND 125 % Schriftgröße) war im Statusfenster der Vollautomatik die Ergebniszeile unten abgeschnitten („als: 20080630 Datenschutzhinweise von…", die Zeile „Grund: …" fehlte ganz). In der Ablage-Vorschau standen in der Tabelle nur Fragmente („UNSICHER: kein plausib", „A - B - C - D - E\Breit").

**Ursache:** Zwei verschiedene, aber verwandte Fehler. (1) Windows skaliert die Schrift, feste Pixelmaße im Code aber nicht: `position_near_mouse(self, 330, 500)`, `wraplength=300`, Thumbnail-Maße — bei 125 % braucht derselbe Text rund ein Viertel mehr Platz, das Fenster blieb gleich groß. (2) `ttk.Treeview` quetscht seine Spalten standardmäßig (`stretch=True`, `minwidth=20`) auf die Fensterbreite zusammen, statt waagerecht scrollbar zu werden — der Text wird dann einfach abgeschnitten.

**Lösung:** (1) `UIUtils.skalierung(widget)` (= `winfo_fpixels("1i") / 96`) und `UIUtils.px(widget, wert)` als gemeinsame Helfer; alle festen Maße von `vollautomatik_fenster.py` und `tools/auto_filer.py` laufen jetzt durch `px()`. (2) Das Statusfenster setzt keine feste Höhe mehr, sondern zieht sich nach jedem Zustandswechsel auf `winfo_reqheight()` nach (`_passe_groesse_an`, nur wachsen, auf den Monitor begrenzt) — der Ausschalt-Knopf ist zusätzlich als erstes mit `side=BOTTOM` verankert. (3) Die Tabelle der Ablage-Vorschau bekommt `stretch=False` plus `minwidth=Spaltenbreite` und eine waagerechte Bildlaufleiste (Gitter-Layout, damit die senkrechte Leiste nicht darüber hinwegreicht); nur die letzte Spalte dehnt sich in den Restplatz. Merksatz: Jeder fest kodierte Pixelwert ist eine Annahme über die Skalierung — entweder durch `UIUtils.px()` schicken oder das Fenster sich selbst bemessen lassen; und eine Tabelle mit vielen Spalten braucht eine waagerechte Bildlaufleiste, sonst „verschwindet" Inhalt lautlos.

**Nachtrag (31.08.2026):** Danach wurden ALLE übrigen Fenster mit festen Maßen umgestellt — Hilfe, Texteingabe-Dialog, PDF-Inspektor, Mini-PDF-Editor, Einstellungen, Dokument neu erfassen, Titel-Aufräumen, Titel-Vorschlag, Tags ergänzen, Dubletten-Finder (Fenstergrößen, `minsize`, `wraplength`, Treeview-Spaltenbreiten); der Dubletten-Finder bekam dieselbe waagerechte Bildlaufleiste wie die Ablage-Vorschau. Zusätzlich begrenzt `UIUtils.position_near_mouse` die Fenstergröße jetzt auf den Arbeitsbereich des Monitors — hochskalierte Maße (1400 × 900 werden bei 125 % zu 1750 × 1125) sind sonst größer als ein Full-HD-Bildschirm und die Knopfleiste läge unter der Taskleiste. **Wichtig:** `width=` bei `Button`, `Entry`, `Label`, `Listbox` und `Text` zählt ZEICHEN, nicht Pixel — das skaliert Tk über die Schrift bereits selbst und darf NICHT durch `px()` geschickt werden; nur `Treeview.column(width=…)` und Fenstermaße sind Pixel.

## 43. Dokument wird beim zweiten Anklicken nicht mehr angezeigt (leerer Ordner dazwischen)

**Problem:** Nutzerfund 31.08.2026: Ordner „A - B - C - D - E" anklicken, dann den Unterordner „ADAC" — das erste Dokument erscheint. Wieder „A - B - C - D - E", dann wieder „ADAC" — die Vorschau bleibt leer. Alles andere (Titel, Tags, Auswahl in der Liste) stimmte.

**Ursache:** `PreviewManager.update_preview` bricht früh ab, wenn `(Pfad, Seite, Zoom, Breite)` unverändert sind — ein wichtiger Performance-Schutz, weil `<Configure>` und Auswahl-Events sehr oft feuern. Der Zweig „Ordner enthält keine Dokumente" in `folder_manager.on_folder_select` löschte aber nur den Canvas (`canvas_preview.delete("all")`) und setzte `current_preview_path = None`, ohne diesen Cache zu verwerfen. Beim erneuten Anklicken desselben Dokuments war der Zustand also identisch zum letzten *gerenderten* — der Manager hielt das Bild für „schon gezeichnet" und zeichnete nichts, obwohl der Canvas inzwischen leer war. Reproduziert: nach dem alten Ablauf blieb der Render-Zähler bei 1, mit dem Fix steigt er auf 2.

**Lösung:** Zwei öffentliche Methoden statt Fremdzugriff auf das private Cache-Feld: `PreviewManager.verwerfe_cache()` (nächstes Zeichnen erzwingen) und `PreviewManager.leere_vorschau()` (Canvas leeren, Pfad/Seite zurücksetzen, Titelzeile leeren UND Cache verwerfen). `folder_manager` benutzt jetzt `leere_vorschau()`; die drei Stellen, die bisher `preview_manager._last_rendered_state = None` von außen setzten (`gui.save_manual_date`, `tools/pdf_editor.py`, `tools/document_recapture.py`), rufen `verwerfe_cache()`. Merksatz: Wer die Anzeige von außen leert, muss auch das Gedächtnis der Anzeige leeren — sonst hält ein Cache einen Zustand für aktuell, den es auf dem Schirm längst nicht mehr gibt.

## 44. Vergiftete Absender-Aliase: EIN Klick lenkte ganze Absender dauerhaft in den falschen Ordner

**Problem:** Praxisfund 31.08.2026: Dutzende Finanzamts-, Landratsamts- und Steuer-Dokumente lagen alle in „Haus- und Grund Musterstadt". Beim Korrigieren in der Ablage-Vorschau das nächste Problem: Ein Klick auf den Zielordner einer Zeile änderte auch andere Zeilen mit — darunter richtige.

**Ursache:** Die Zielordner-Korrektur speicherte JEDE Wahl sofort als Absender-Alias (`aliase.json`) und wandte sie auf alle Zeilen desselben Absenders an — ohne Rückfrage und ohne Anzeige. In der echten Sammlung standen dadurch Einträge wie `„Landratsamt Musterstadt" → „Haus- und Grund Musterstadt"` und `„Finanzamt Musterstadt" → „Stadt Musterstadt"`: vermutlich einmal für ein einzelnes Dokument so gewollt, ab da aber ein dauerhafter Wegweiser mit Vorrang vor dem Namensvergleich — jedes künftige Landratsamt-Dokument wanderte still in den falschen Ordner. Es gab weder eine Möglichkeit, die gelernten Aliase zu sehen, noch sie loszuwerden.

**Lösung:** (1) Der Zielordner-Dialog fragt jetzt nach der Reichweite — Vorgabe ist „Nur dieses eine Dokument" (kein Alias, keine anderen Zeilen); „Alle Dokumente von ‚Absender' — auch künftige" ist eine bewusste, ausdrückliche Wahl. (2) Neuer Dialog „Gemerkte Zuordnungen…" in der Ablage-Vorschau: zeigt `aliase.json` als Tabelle und löscht Einträge (`ordner_aliase.loesche_alias`); Löschen ist folgenarm, weil nur der Wegweiser wegfällt und der Namensvergleich wieder übernimmt. Merksatz: Was aus einer einzelnen Nutzeraktion DAUERHAFTE Regeln lernt, braucht eine ausdrückliche Zustimmung und eine sichtbare, editierbare Liste des Gelernten — sonst vergiftet ein einziger Sonderfall-Klick das Verhalten für immer.

## 45. Kategorie „Objekte & Adressen" nur in der Vorlage — die Objekt-Unterscheidung lief still ins Leere

**Problem:** Nutzerfrage 01.09.2026: „Warum werden Orte wie Musterstadt oder Musterheim nicht mehr vertaggt?" Die Prüfung der echten Sammlung förderte zwei Fehler zutage. (a) Von 399 Dokumenten trugen nur 26 einen Ortsbezug — und die stammten aus der Zeit vor der Automatik. (b) Schwerwiegender: `dubletten.UNTERSCHEIDUNGS_KATEGORIEN` suchte eine Kategorie namens „Objekte & Adressen"; die gewachsene Sammlung hatte den Zweig aber als „Wohnen & Immobilien / **Adressen**". Der exakte Namensvergleich lieferte damit stumm eine leere Liste — die Unterscheidung „Zum Alten Fass 1" vs. „Zum Alten Fass 3", für die das Ganze gebaut wurde, konnte NIE greifen. Bei „Personen" stimmte der Name zufällig, deshalb fiel nichts auf.

**Ursache:** (a) Der Vollautomatik-Prompt kannte gar keine Objekt-Aufgabe. Orte hätten sich unter „bis zu 5 passende Schlagworte" gegen Dokumentart, Thema, Jahr und Empfänger durchsetzen müssen — chancenlos. (b) Ein Konstanten-Name aus der ausgelieferten `tags_default.json` wurde als Tatsache über jeden Katalog behandelt. Kataloge wachsen aber beim Nutzer, nicht in der Vorlage.

**Lösung:** (1) `auto_pilot.KATEGORIE_VARIANTEN` listet die möglichen Namen je Kategorie („Objekte & Adressen", „Adressen", „Objekte", …); `tag_manager.merkmale_fuer_dubletten()` löst sie auf und ist ab jetzt die EINE Stelle, die die Unterscheidungs-Tags liefert (vorher in drei Aufrufern kopiert). `auto_pilot._kategorie_name` macht dasselbe beim Einsortieren neuer Tags, sonst landeten sie in „Neu (KI)" und blieben unsichtbar. (2) Neue Prompt-Aufgabe 7 „Objekt": Grundstück, Wohnung, Haus oder Fahrzeug als eigenes Feld — analog zum Empfänger, der schon so ein Tag unter „Personen" erzeugt. (3) `teile_objekte()` zerlegt die Antwort in garantiert kommafreie Tags — `teile_empfaenger` ist auf Personennamen zugeschnitten und ließ im Live-Test „Weidenstr. 8, Wgh.Nr.5" als EIN Tag mit Komma stehen (FALLSTRICKE #38). Live gegengeprüft: drei Grundsteuererklärungen desselben Absenders bekommen jetzt „Zum Alten Fass 1" bzw. „Weidenstr. 8 Whg.Nr. 2" bzw. „Weidenstr. 8 Wg.Nr. 4" — genau das Signal, das die Dubletten-Erkennung braucht. Merksatz: Ein Name aus einer mitgelieferten Vorlage ist keine Zusicherung über gewachsene Nutzerdaten — wer per Name sucht, muss Varianten kennen ODER scheitern laut, nie still mit einer leeren Liste.

## 46. Zielordner doppelt: der Absender stand nochmal als Tag am Dokument

**Problem:** Nutzerhinweis 01.09.2026: Ein Dokument im Ordner „Finanzamt" trug zusätzlich das Tag „Finanzamt Musterstadt" — Information, die die Ablage schon zeigt, und bei jeder Suche ein Treffer mehr ohne Erkenntnisgewinn.

**Ursache:** Die KI liefert den Absender sowohl als eigenes Feld (daraus wird der Ordner) als auch regelmäßig unter den Schlagworten. Niemand hat die beiden je gegeneinander gehalten.

**Lösung:** `auto_pilot.ohne_zielordner_tags(tags, zielordner, ordnername)` — läuft in `baue_entscheidung` erst NACH der Ordnerwahl (vorher steht der Ordner nicht fest, und `finde_ordner_ueber_hinweise` braucht die Tags sogar noch). Drei Vergleichswerte: der letzte Pfadbestandteil des Zielordners, dessen Kernname (Telefonbuch-Ordner „Carius, Dr. Emil (Zahnarzt)" → auch „Carius") und der aus dem Absender abgeleitete `ordnername` — Letzteres nötig, weil der reale Ordner oft kürzer heißt als der Absender (Ordner „Finanzamt", Tag „Finanzamt Musterstadt"). Verglichen wird ausschließlich auf **Gleichheit**, nie als Teilstring: Das Orts-Tag „Musterstadt" überlebt neben dem Ordner „Finanzamt Musterstadt". Bei einer **Alias-Ablage** in einen fremden Ordner wird der `ordnername` bewusst NICHT geprüft — dort verrät der Ordner den Absender gerade nicht („Landratsamt Musterstadt" liegt unter „Haus- und Grund Musterstadt"), der Tag ist dann die einzige Spur. Fällt dadurch das letzte Tag weg, wird die Entscheidung „unsicher" („keine Tags erkannt").

## 47. „c/o" wurde am Schrägstrich zerhackt: Tags „Erbengemeinschaft Mustermann c" und „o Hermann Mustermann"

**Problem:** Kaltstart-Test 03.09.2026 (423 echte Dokumente in eine leere Sammlung): im Katalog standen die wertlosen Personen-Tags „Erbengemeinschaft Mustermann c" und „o Hermann Mustermann" — je 16 Dokumente. Ebenso Klumpen wie „Mustermann Erbengemeinschaft Z.Hd.Hermann Mustermann" als EIN Tag.

**Ursache:** `_EMPFAENGER_TRENNER` und `_OBJEKT_TRENNER` behandeln `/` als Trennzeichen zwischen zwei Namen („Hermann/Werner Mustermann"). Der Zustellvermerk „c/o" enthält denselben Schrägstrich mitten im Wort — der Split zerlegte ihn in „…c" und „o…". „Z.Hd." wiederum ist gar kein Trennzeichen und blieb einfach im Namen kleben.

**Lösung:** `auto_pilot._ZUSTELLVERMERKE` ersetzt „c/o", „z.Hd." (auch verklebt: „Z.Hd.Hermann"), „zu Händen (von)" und „p.Adr." VOR dem Zerlegen durch ein echtes Trennzeichen — beide verbundenen Namen bleiben so als eigene Tags erhalten. Dazu entfernt `_ANREDE_VOR_NAME` die Anreden Herr(n)/Frau/Firma (nur als eigenes Wort — „Frauenklinik" bleibt unangetastet; bewusst NICHT das vorhandene `_ANREDEN`, das ist auf Ordner-Kernnamen zugeschnitten und würde auch „Dr./Praxis" wegwerfen, die im Personen-Tag bleiben sollen). Merksatz: Wer an Sonderzeichen splittet, muss vorher die Wörter neutralisieren, die dieses Zeichen IN sich tragen — sonst zerlegt der Split nicht zwischen den Werten, sondern mitten durch einen.

## 48. Adress-Schreibvarianten-Explosion: dieselbe Adresse stand in einem Dutzend Formen im Katalog

**Problem:** Gleicher Kaltstart-Test: von 43 Objekt-Tags waren ~30 Schreibvarianten von genau ZWEI echten Objekten. „Zum Alten Fass 1 u. 3 Musterheim" existierte u.a. mit Bindestrichen, als „1+3", „1 u.3", mit „Schloß", mit/ohne „Nr."; „Weidenstr. 8" auch als „Weidenstraße 8", „Weidenstrasse 8", mit „Whg.Nr."/„Whg Nr."/„Wgh."-Tippfehler. Damit war die Dubletten-Unterscheidung nach Objekt wieder wertlos: gleiche Adresse ≠ gleiches Tag.

**Ursache:** Die KI transkribiert wörtlich, was auf dem jeweiligen Brief steht — und jeder Absender schreibt die Adresse anders. Der Katalog-Abgleich verglich aber nur exakt (bzw. case-insensitiv): jede neue Schreibform wurde ein neues Tag.

**Lösung:** `auto_pilot.normiere_objekt()` bildet eine Vergleichs-Normalform (klein, ß→ss, ä→ae, Bindestriche/Punkte→Leerraum, „…str"→„…strasse", wohnung/whg/wgh→whg, „nr"/„in" entfallen, „u."/„und"/„+"→„+"), `finde_objekt_schreibweise()` schnappt neue Objekt-Angaben in `tags_mit_empfaenger` auf die vorhandene Katalog-Schreibweise. Haus- und Wohnungsnummern bleiben unterscheidend — „Schloss 1" vs. „Schloss 3" vs. „Schloss 1+3" bleiben drei Tags, dafür ist das Feature da. Gegenprobe mit den echten 43 Kaltstart-Tags: 18 Varianten wären zusammengefallen, alles Unterschiedliche blieb getrennt. Bewusst NICHT zusammengelegt: Formen mit/ohne Ortszusatz („Weidenstr. 8" vs. „Weidenstr. 8 Musterstadt") — welche die kanonische wäre, kann nur der Nutzer entscheiden. Merksatz: Wo eine KI freien Text liefert, der als IDENTITÄT dient (Adresse, Kennzeichen, Name), braucht es eine Normalform für den Vergleich — sonst erzeugt jede Transkriptions-Laune eine neue Identität.

## 49. Bildlaufleisten-Flattern in der Vorschau: eine Schwelle ist keine Hysterese

**Problem:** Nutzerfund 03.09.2026, kurz nach Einbau des automatischen Leisten-Ausblendens („Seite einpassen"): An einer ganz bestimmten Fensterbreite flatterte die Vorschau dauerhaft — Bildlaufleiste raus, rein, raus, rein, das Bild zoomte sichtbar mit.

**Ursache:** Das Ein-/Ausblenden benutzte EINE Schwelle („passt die Seite in die Höhe minus Puffer?") für beide Richtungen. Im Breiten-Autofit koppelt die Leiste aber auf die Seitenhöhe zurück: Ausblenden → Canvas ~18 px breiter → Seite wächst mit (Seitenverhältnis × Leistenbreite, A4 hochkant ≈ 25 px) → wieder über der Schwelle → Einblenden → schmaler → unter der Schwelle → … Ein verschobener Puffer verschiebt nur die Grenzbreite, an der es kippt — er beseitigt sie nicht.

**Lösung:** `preview_manager.scrolleiste_soll_sichtbar_sein` mit ECHTER Hysterese: Ausblenden erst, wenn die Seite mit deutlichem Abstand (40 px > maximaler Rückkopplungs-Zuwachs) hineinpasst; Einblenden erst bei echtem Überstand; in der Grauzone dazwischen bleibt der Zustand stehen. Der Unit-Test simuliert die Rückkopplung über viele Fensterbreiten und zählt die Zustandswechsel (höchstens einer erlaubt). Merksatz: Wenn eine automatische UI-Reaktion die Messgröße verändert, auf der sie selbst beruht (Leiste ↔ Breite ↔ Seitenhöhe), braucht der Umschalter zwei getrennte Schwellen mit einem Abstand größer als die Rückkopplung — sonst entsteht ein Oszillator.

## 50. Der „Musterstadt, VB Musterbk"-Magnet: ein Ordner mit Ortsnamen-Kern zog jeden Orts-Absender an

**Problem:** Kaltstart-Lauf 3 (04.09.2026): 25 Dokumente im Ordner „Musterstadt, VB Musterbk", die meisten falsch — Grundsteuerbescheide, Mietverträge, Laborrechnungen, sogar ein Dokument mit korrekt erkanntem Absender „Finanzamt Musterstadt" (Tag am Dokument bewies es) landete bei der Bank statt im vorhandenen Ordner „Finanzamt".

**Ursache:** Drei Zahnräder griffen ineinander. (1) Der Beta-Tester benannte den Ordner in der Form „Ort, Institution" — `kernname()` unterstellt aber Telefonbuch-Form („Nachname, Vorname") und machte „Musterstadt" zum Ordnerkern. (2) `_namen_passen` matcht den Kern als ganzes Wort im Absender — und „Musterstadt" steht in Dutzenden Absendern der Gegend („Stadt Musterstadt", „Expert TechnoMarkt Musterstadt", …). (3) Bei mehreren Treffern gewinnt der LÄNGERE Ordnername — „Musterstadt, VB Musterbk" (17 Zeichen) schlug sogar den exakten Treffer „Finanzamt" (9 Zeichen).

**Lösung:** `auto_pilot._mehrdeutige_woerter()` sammelt die „Allerweltswörter" der Sammlung — Wörter, die in MEHREREN Ordnernamen vorkommen („Musterstadt" stand in dreien). Ein Ordnerkern, der kein einziges nur ihm gehörendes Wort enthält, matcht gar nicht mehr (weder in `_namen_passen` noch als Tag-/Dateinamen-Hinweis in `finde_ordner_ueber_hinweise`); erreichbar bleibt so ein Ordner über den exakten vollen Namen oder — der gedachte Weg — über einen Absender-Alias. Nützlicher Nebeneffekt: Bei Doppel-Ordnern („Vivafone …"/„Vivafone Kabel …", „LKM Versicherung"/„…en") ist das gemeinsame Wort automatisch mehrdeutig — statt zu raten wird das Dokument „unsicher", bis der Nutzer die Ordner zusammenführt. Merksatz: Ob ein Wort einen Ordner IDENTIFIZIERT, weiß die Sammlung selbst — ein Wort, das in mehreren Ordnernamen steht, identifiziert keinen davon; der Code muss dafür keine Ortsnamen kennen.

## 51. Hilfe-Fenster legte sich über die Ersteinrichtungs-Frage: Tk-Timer feuern auch während modaler Dialoge

**Problem:** Nutzerfund 04.09.2026 beim Von-Null-Test: Beim allerersten Start erschien die Ersteinrichtungs-Frage („Dokumente\KID anlegen?") — und eine Zehntelsekunde später schob sich das Schnellstart-Hilfefenster mitten darüber. Die Frage war nur noch als abgeschnittener Streifen am Rand sichtbar.

**Ursache:** Beide Start-Dialoge hingen an getrennten Timern (`after(300)` Ersteinrichtung, `after(400)` Hilfe) — im Vertrauen darauf, dass der modale Messagebox-Dialog den zweiten Timer aufhält. Tut er nicht: Ein modaler Dialog blockiert nur die EINGABE ins Hauptfenster, die Tk-Ereignisschleife (und damit alle `after`-Timer) läuft währenddessen normal weiter. Der 400ms-Timer feuerte also mitten in die offene Frage hinein und öffnete das Hilfe-Toplevel obendrauf.

**Lösung:** EIN `after`-Callback, der beide Schritte nacheinander ausführt: erst `ersteinrichtung_anbieten()` (blockiert synchron, bis alle Dialoge beantwortet sind), dann `open_help(...)`. Merksatz: „Modal" heißt in Tkinter nicht „die Welt steht still" — wer eine Reihenfolge zwischen Dialogen braucht, muss sie im Code verketten statt über gestaffelte Timer zu hoffen.

## 52. Ordner-Sprung schlug still fehl: Schrägstrich-Mix zwischen settings.json und os.path

**Problem:** Nutzerfund 05.09.2026 nach dem Von-Null-Test: In der Ablage-Vorschau zeigte das Anklicken einer Zeile das Dokument nicht mehr im Hauptfenster an — der Hintergrund-Sync (Ordnerwechsel + Dateiauswahl) tat kommentarlos nichts. Am 03.09. hatte genau das noch funktioniert.

**Ursache:** `_select_and_open_path` verglich Pfade mit rohem `startswith`. Der Hauptordner steht aber mit VORWÄRTS-Schrägstrichen in settings.json (`C:/Users/max/KID-Test` — so liefern ihn Tk-Dateidialoge, und so schreibt ihn testzustand.py), während `os.path.abspath`/`dirname` Backslashes erzeugen. `"C:\…".startswith("C:/…")` ist immer False → die Wurzel matchte nie, der Sprung unterblieb ohne jede Meldung. Tückisch: Solange der Hauptordner (wie vor dem 04.09.) mit Backslashes gespeichert war, funktionierte alles — der Bug schlief, bis der Kaltstart-/Ersteinrichtungs-Weg den Pfad mit Vorwärts-Schrägstrichen schrieb. Obendrein fehlte eine Trennzeichen-Prüfung: `KID-Test-Daten` galt als „liegt unter" `KID-Test`.

**Lösung:** Vergleich in `_select_and_open_path` über `os.path.normcase(os.path.normpath(...))` auf beiden Seiten, Vorfahren-Test als `ziel == item_path or ziel.startswith(item_path + os.sep)`. Merksatz: Windows-Pfade NIE roh mit String-Operationen vergleichen — zwischen Tk (Vorwärts-Schrägstriche), json-Konfig und os.path (Backslashes) ist der Mix garantiert; `normpath`+`normcase` vor jedem Vergleich, und ein „liegt unter"-Test braucht das Trennzeichen.

## 53. src/-Umbau: `--collect-submodules tools` sammelte STILL nichts mehr ein

**Problem:** Beim Struktur-Aufräumen (05.09.2026, Module von der Projektwurzel nach `src/`) baute PyInstaller die EXE ohne Fehlermeldung — aber die eingebaute Prüfung von `build_exe.py` schlug an: 8 der 11 Tool-Module fehlten im Paket. Exakt das v0.9.3-Szenario (FALLSTRICKE #39), das die Prüfung einst motiviert hat.

**Ursache:** Zwei verschiedene Suchpfade. `--paths src` wirkt nur auf die Import-ANALYSE der App (deshalb kamen die 3 direkt importierten Tools wie `tools.base_tool` noch mit). `--collect-submodules tools` dagegen importiert das Paket im PyInstaller-Prozess selbst — und dessen `sys.path` kannte `src/` nicht. Vorher lag `tools/` im Arbeitsverzeichnis und war zufällig importierbar. Findet `collect_submodules` das Paket nicht, sammelt es kommentarlos NICHTS ein.

**Lösung:** `build_exe.baue()` startet PyInstaller mit `PYTHONPATH=src` (zusätzlich zu `--paths src`). Merksatz: `--paths` und `--collect-submodules` benutzen NICHT denselben Suchpfad — und die Selbstprüfung der EXE nach dem Build ist genau für solche stillen Ausfälle da, niemals weglassen.

## 54. Watchdog-Vollautomatik verschob die Datei unter dem laufenden Auto-Save weg

**Problem:** Nutzerfund 06.09.2026: Beim Bearbeiten einer Posteingang-Datei erschien plötzlich ein Fehler-Popup „Speicher-Fehler: Das PDF konnte nicht überschrieben werden: Failed to open stream", im Log zweimal „Fehler beim automatischen Speichern" — und die Datei lag auf einmal in `0_Unsicher` statt im Posteingang.

**Ursache:** Race zwischen zwei legitimen Akteuren: Der Nutzer hatte die Posteingang-Datei im Hauptfenster ausgewählt und Titel/Tags getippt (debounctes Auto-Save, 1 s). Gleichzeitig hielt die eingeschaltete Watchdog-Vollautomatik die Datei für ein fertiges, stabiles Posteingang-Dokument und verschob sie (hier: als „unsicher" nach `0_Unsicher`). Das Auto-Save feuerte danach auf den gemerkten ALTEN Pfad — je nach Mikro-Timing „Datei fehlt" (stiller Fehlschlag) oder mitten in die Verschiebung hinein (MuPDF: „Failed to open stream", modales Popup aus `write_custom_metadata(still=False)`). Die `pausieren()`-Sperre griff nicht: sie gilt nur, solange ein Vollautomatik-FENSTER offen ist, nicht fürs normale Arbeiten im Hauptfenster.

**Lösung:** Doppelt abgesichert. (1) Wurzel: `auto_pilot_service` überspringt eine Datei, wenn sie gerade im Hauptfenster angezeigt wird UND dort eine ungespeicherte Eingabe offen ist (`_wird_gerade_bearbeitet`: `current_preview_path` + `save_manager.hat_offene_aenderung`, beides über den Hauptthread gelesen; zweite Prüfung nochmal NACH der sekundenlangen KI-Analyse). Die 60-Sekunden-Fallback-Runde holt die Datei nach dem Speichern nach. (2) Symptom: `_perform_autosave` prüft vor dem Schreiben die Existenz (verschwundene Datei → Log-Warnung statt Popup, Änderung verworfen) und speichert grundsätzlich mit `still=True` — Fehler laufen über Rückgabewert + Revert, nie als modale Box in die laufende Eingabe.

Wichtige Verfeinerung (Nutzerfund direkt nach dem ersten Fix, „Vollautomatik findet mein Dokument nicht"): Bloßes ANZEIGEN darf NICHT reichen — beim Öffnen des Posteingangs selektiert das Hauptfenster das erste Dokument automatisch, ein „angezeigt = tabu" blockierte die Verarbeitung also dauerhaft. Merksatz: Der Dienst darf nichts anfassen, WORAN der Nutzer gerade arbeitet (offene Eingabe) — aber „ansehen" ist kein „bearbeiten", sonst legt die Auto-Selektion die Automatik still.

## 55. desktop.ini stand als „Dokument" in der Liste — und bekam einen PDF-Schreibversuch

**Problem:** Nutzerfund 06.09.2026, gleiches Popup wie #54 („Speicher-Fehler: Failed to open stream"), aber andere Ursache: Im leeren Posteingang stand plötzlich `desktop.ini` als Dokument-Zeile, wurde beim Ordnerwechsel auto-selektiert — und das Popup erschien ohne jeden Log-Eintrag.

**Ursache:** Verkettung dreier Einzelteile. (a) `on_folder_select` listet alle Dateien außer Punkt-Dateien — die von Windows selbst angelegte, im Explorer unsichtbare `desktop.ini` (Versteckt+System-Attribut) fiel durch diesen Filter. (b) Die Datums-Logik der Vorschau schlägt auch für Nicht-PDFs ein Datum vor (der Datei-Änderungszeit-Fallback funktioniert für jede Datei). (c) Bei aktivem `auto_fill_on_click` ruft `preview_manager` dann `save_manual_date` auf, und der schrieb via `write_custom_metadata` OHNE PDF-Prüfung — MuPDF quittiert die ini-Datei mit „Failed to open stream" als Messagebox; geloggt wird auf diesem Weg nichts, deshalb war das Log leer.

**Lösung:** `folder_manager.ist_versteckte_systemdatei` (Name `desktop.ini`/`Thumbs.db` oder Versteckt-/System-Attribut via `st_file_attributes`) filtert die Dokumentenliste — was der Explorer versteckt, zeigt auch KID nicht. Zusätzlich schreibt `save_manual_date` nur noch bei `.pdf`-Pfaden. Merksatz: Jeder Schreibweg in PDF-Metadaten braucht seine eigene `.pdf`-Prüfung — die Dokumentenliste enthält bewusst auch andere Dateitypen, und „der Aufrufer prüft schon" gilt spätestens bei Automatik-Ketten (Klick → Vorschau → Timer → Schreiben) nicht mehr.

## 56. Doppelt gescannte Rechnung rutschte durch — und drei Lehren über die KI-Zweitprüfung

**Problem:** Nutzerfund 06.09.2026 nach dem großen Vollautomatik-Lauf: Dieselbe Kaminkehrer-Rechnung landete zweimal im Zielordner (zwei verschiedene Scans), ohne dass Stufe B ansprang. Beim Nachstellen zeigte sich eine Kaskade: (a) Die zwei Scans derselben Rechnung ähnelten sich nur zu 0.628 (Schwelle 0.7) bei Bild-Hamming 19 (Schwelle 6) — während sich VERSCHIEDENE Iqua-Wohnungsabrechnungen desselben Tages zu 0.69–0.80 bei teils identischem Bild-Fingerabdruck ähneln. Die Zonen überlappen, keine Schwelle trennt sie. (b) Das Zwei-Bilder-Urteil des Vision-Modells war unbrauchbar: Es las auf beiden Seiten DIESELBE Rechnungsnummer ab und schloss trotzdem „unterschiedlich". (c) Beim Versuch, stattdessen die Felder beider Seiten in EINEM Aufruf abzulesen, vermischte qwen2.5vl:7b die Dokumente — Bild 2 bekam die Werte von Bild 1, verschiedene Wohnungsabrechnungen galten plötzlich als „gleiche Nummer, gleicher Betrag". (d) Und eine gleiche Kennnummer allein beweist ohnehin nichts: Alle vier Wohnungsabrechnungen tragen dieselbe Liegenschaftsnummer.

**Lösung:** Dreiteilig. (1) GRAUZONE in `dubletten_pruefung` (`GRAUZONE_TEXT` 0.5): Bei gleichem Dokumentdatum und Ähnlichkeit knapp unter den Schwellen wird die KI-Zweitprüfung gefragt, obwohl die Deterministik „kein Treffer" sagt — nur ein klares „ja" mit Begründung stoppt dann. (2) „Das Modell liest ab, der Code vergleicht": `pruefe_dublette` ruft das Modell pro Seite EINZELN (Einzelbild-Lesung ist erprobt zuverlässig, die ganze Vollautomatik basiert darauf) und `_vergleiche_dublettenmerkmale` entscheidet deterministisch: verschiedene Kennnummern → nein; gleiche Kennnummer + gleicher Betrag → ja; gleiche Kennnummer + verschiedene Beträge → nein (geteilte Objektnummer). Nur ohne belastbare Felder zählt das Zwei-Bilder-Urteil als Rückfall. (3) Alle drei Praxisfälle end-zu-end gegen den echten Server verifiziert. Merksatz: Einem Vision-Modell nie zwei Dokumente in einem Aufruf zum VERGLEICHEN geben — einzeln ablesen lassen und im Code vergleichen; und Kennnummern können geteilt sein (Liegenschaft!), erst Nummer+Betrag zusammen beweisen die Dublette.

## 57. „_1"-Kaskade: Datei wurde an ihrem eigenen Namen vorbei umbenannt

**Problem:** Nutzerfund 06.09.2026 („Wieso wird eigentlich ein _1 an den Dateinamen gehängt?"): Nach einer Ablage-Vorschau ÜBER den Unsicher-Ordner hießen alle weiterhin unsicheren Dateien plötzlich `X_1.pdf`, nach dem nächsten Durchlauf `X_1_1.pdf` — obwohl sie den Ordner nie verlassen haben.

**Ursache:** Bleibt eine Entscheidung „unsicher", verschiebt `fuehre_entscheidung_aus` die Datei nach `0_Unsicher`. Liegt sie dort aber SCHON, sind Quelle und Ziel identisch — und `_naechster_freier_pfad` prüft nur „existiert die Zieldatei?": ja, es ist die Datei selbst. Also wich er auf `_1` aus und benannte die Datei an ihrem eigenen Namen vorbei um. Derselbe Effekt drohte im Grün-Fall, wenn ein bereits korrekt benanntes Dokument seines Zielordners erneut durch die Vorschau läuft.

**Lösung:** Vor der Konflikt-Auflösung prüfen, ob Quelle == Ziel (`_gleicher_pfad`, normcase+abspath wegen des Schrägstrich-Mixes aus #52): dann ist nichts zu verschieben — Metadaten werden im Grün-Fall trotzdem geschrieben, der `verschieben`-Callable wird gar nicht erst aufgerufen (dessen Duplikat-Aufräumen auf sich selbst wäre riskant). Merksatz: Jede „nächster freier Name"-Logik braucht die Vorab-Frage „bin ich das selbst?" — sonst erzeugt Wiederholung Endlos-Suffixe.

## 58. App startete unsichtbar im Nirgendwo: Fenstergeometrie blind wiederhergestellt

**Problem:** Nutzerfund 06.09.2026: Beim Start lag das Hauptfenster komplett außerhalb aller Bildschirme („ich kann die Titelleiste zum Verschieben nicht greifen"). In der settings.json stand `window_geometry = 1440x1237+-4028+-921` — eine Position von einer Monitor-Anordnung, die es so nicht (mehr) gab.

**Ursache:** `gui.py` stellte die gespeicherte Geometrie ungeprüft wieder her. Tk merkt nicht, ob die Koordinaten auf einem angeschlossenen Monitor liegen — nach Docking-/Monitorwechsel oder RDP-Sitzungen zeigen sie gern ins Leere. (Erste Hilfe für Betroffene: Fenster über die Taskleiste fokussieren, dann Win+Umschalt+Pfeil bzw. Alt+Leertaste → „Verschieben" → Pfeiltasten.)

**Lösung:** `UIUtils.sichere_fenstergeometrie` prüft vor dem Anwenden drei Titelleisten-Punkte (links/Mitte/rechts, knapp unter der Oberkante) per Win32 `MonitorFromPoint(MONITOR_DEFAULTTONULL)` gegen ALLE Monitore (`punkt_auf_einem_monitor`; Nicht-Windows/Fehler: nichts verwerfen). Liegt keiner auf einem Monitor, wird nur die Position verworfen — die Größe bleibt, Tk platziert selbst. Merksatz: Gespeicherte Fensterpositionen sind Momentaufnahmen einer Monitor-Landschaft — vor dem Wiederherstellen IMMER gegen die aktuelle prüfen, und zwar gegen alle Monitore, nicht nur den Hauptmonitor (sonst FALLSTRICKE #42 rückwärts).

## 59. Tag-Katalog wuchs mit exakten Doppelgängern: Struktur-Kategorien galten als „unbekannt"

**Problem:** Nach dem Praxislauf 06.09.2026 (Von-Null-Struktur, ~68 Dokumente) standen 38 Tags doppelt im Katalog — z.B. „Gesundheit" als graue Wurzel-Kategorie UND als zuweisbarer Tag unter „Neu (KI)", „Hermann Mustermann" als grauer Knoten unter „Weidenstr. 8" UND unter „Personen". Kein Whitespace, keine Schreibvariante: buchstabengleich.

**Ursache:** `get_known_tags()` liefert bewusst nur zuweisbare Tags (ohne graue Struktur-Knoten). Genau diese Liste war für `bestimme_neue_tags` und `add_tags_to_catalog` das Kriterium „schon im Katalog?". Schlägt die KI einen Tag vor, der im Katalog als Struktur-Kategorie existiert, ist er in dieser Liste nicht enthalten → gilt als neu → wird ein zweites Mal angelegt. Peters Katalog hat viele solche Knoten (Personen als graue Unterknoten ihrer Adresse), daher die hohe Zahl.

**Lösung:** Als „bekannt" zählen jetzt zuweisbare Tags UND Kategorie-Namen (`get_kategorien()` bzw. der ohnehin übergebene `kategorien`-Parameter) — an beiden Stellen, damit auch die Ablage-Vorschau und das Tag-Ergänzen-Tool profitieren. Der Tag steht weiterhin am Dokument (so wie die Auto-Hierarchie Kategorie-Namen an Dokumente schreibt), nur der Katalog bekommt keinen Zwilling. Dazu schnappen Personen-Tags aus dem Empfänger jetzt auf die Katalog-Schreibweise (`finde_personen_schreibweise`: Namensdreher „Mustermann Hermann" → „Hermann Mustermann", Tippfehler im Vornamen bei exakt gleichem Nachnamen „Hemann Mustermann", „Dorit Richter"; Nachname bleibt scharf — Maier/Meier sind zwei Menschen). Merksatz: Wer „ist das schon im Katalog?" fragt, muss gegen ALLE Katalog-Namen prüfen, nicht nur gegen die anklickbaren — die Sicht „zuweisbar" und die Sicht „existiert" sind zwei verschiedene Fragen.

## 60. Speichern bei geöffnetem PDF: „…pdf.tmp" blieb liegen und stand in der Dokumentenliste

**Problem:** Peter hatte ein PDF in der Anzeige offen und klickte in der Tag-Hygiene auf „Synonyme im Bestand ersetzen". Ergebnis: modale Meldung „[WinError 32] Der Prozess kann nicht auf die Datei zugreifen", und danach lag neben dem Original eine Datei „20241003_…pdf.tmp", die in der Dokumentenliste auftauchte (ohne Tags, Titel = Dateiname).

**Ursache:** `write_custom_metadata` baut das PDF sicher über eine Temp-Datei neu und schiebt sie mit `shutil.move` über das Original. Ist das Original von einem anderen Programm geöffnet, scheitert das Überschreiben — die fertige Temp-Datei blieb aber stehen, weil der `except`-Zweig nur die Meldung zeigte. Zusätzlich lief die Hygiene-Schleife mit `still=False`, also ein Popup pro gesperrter Datei, mitten im Fortschrittsdialog.

**Lösung:** (1) Der Schreibweg entfernt die Temp-Datei bei jedem Fehler. (2) Das Überschreiben wird bis zu dreimal mit 0,3 s Pause versucht (`SCHREIB_VERSUCHE`/`SCHREIB_WARTEZEIT_S`, gleiche Lehre wie #27: kurze Sperren durch Explorer-Vorschau, Virenscanner, Indexdienst sind unter Windows Normalzustand). (3) Die Fehlermeldung nennt die Datei und fragt nach dem anderen Programm. (4) Tag-Hygiene (Entfernen und Synonyme) schreibt `still=True`, sammelt gescheiterte Dokumente und meldet sie einmal am Ende als Warnung mit Dateinamen. **Lehre:** Jeder Temp-Datei-Schreibweg braucht ein `finally`/`except`-Aufräumen — und Stapel-Operationen dürfen nie den modalen Fehlerdialog des Einzel-Schreibwegs benutzen.

## 61. Spaltenbreite ziehen endete als Drag & Drop (Tag-Transfer mit der alten Auswahl)

**Problem:** Peter zog in der Dokumentenliste eine Spaltenbreite an der Trennlinie der Kopfzeile und ließ die Maus versehentlich außerhalb des Spaltenbereichs los (über einer anderen Zeile bzw. dem Ordnerbaum). Die App versuchte daraufhin, Tags zu übertragen bzw. die Datei zu verschieben — als hätte er das zuvor markierte Dokument gezogen (Nutzerfund 11.09.2026 beim Durchgehen der manuellen Tests).

**Ursache:** `on_drag_start` (ButtonPress-1 auf `tree_files`) merkte sich nur die Startkoordinaten und stieg bei Kopfzeile/Trennlinie still aus (kein `item`, Region ≠ „nothing"). `on_drag_stop` (ButtonRelease-1) wusste davon nichts: Es prüfte lediglich die Totzone (≤ 2 px) und das Widget unter der Maus — beim Spaltenziehen ist die Bewegung groß und die Maus meist über der Liste oder dem Ordnerbaum. `on_file_drop` nahm dann `tree_files.selection()[0]` als Quelle, also das Dokument, das vorher markiert war.

**Lösung:** Ein explizites Flag `_drag_aktiv`, das NUR gesetzt wird, wenn der Druck auf einer Zeile lag (`identify_row` liefert ein Item); STRG-/SHIFT-Klicks, Kopfzeile, Trennlinie und Klick ins Leere setzen es nicht. `on_drag_motion` und `on_drag_stop` tun ohne Flag nichts (außer Hervorhebungen löschen); der Drop setzt es wieder zurück. Test `TestDragNurVonZeile`. **Lehre:** Bei Press/Motion/Release-Tripeln auf demselben Widget muss der Release wissen, ob der Press überhaupt ein Drag war — ein Bewegungs-Schwellwert allein unterscheidet „Datei ziehen" nicht von „Spalte ziehen".

## 62. Hilfe-Sprung zum Abschnitt „landete daneben": Tk scrollt nicht über das Textende hinaus

**Problem:** Der Menüpunkt Hilfe → „KI-Server aus der Ferne (Tailscale)" öffnete zwar den Funktionsumfang, aber man musste selbst zum Abschnitt scrollen (Fehlnotiz T1.10, 11.09.2026). Nach dem Einbau von Sprungmarken (`HelpWindow.select_tab(..., abschnitt=)`) schien der Sprung im echten Fenster weiter falsch zu landen: `yview(marke)` ergab 0,40 statt 0,70 wie im Unit-Test, und die oberste Zeile war ein anderer Absatz.

**Ursache:** Kein Fehler im Sprung — der Abschnitt liegt so nah am Textende, dass das Text-Widget die Überschrift gar nicht bis nach oben schieben KANN (Tk lässt hinter der letzten Zeile keinen Leerraum). Im Unit-Test war das Fenster `withdraw()`n, ohne Umbruch war der Text „länger" und die Überschrift kam nach oben; im sichtbaren Fenster mit Zeilenumbruch nicht. Der Screenshot zeigte den Abschnitt korrekt sichtbar in der unteren Hälfte.

**Lösung:** Sprung so lassen (so weit wie möglich scrollen), zusätzlich die Überschrift-Zeile 1,5 s gelb hinterlegen (`_springe_zu`, Tag `sprung`), damit das Auge sie sofort findet. Tests prüfen `dlineinfo(marke) is not None` (sichtbar) statt „oberste Zeile". **Lehre:** Bei „scrolle Element X nach oben"-Erwartungen immer mit einem Screenshot im echten Fenster gegenprüfen — Zahlen von `yview()` sagen nicht, ob das Ziel sichtbar ist; und ein Withdrawn-Fenster im Test hat andere Umbrüche als das sichtbare.

## 63. Datums-Marker endete nach dem Neu-Erfassen mitten im Wort („18.11.20|19")

**Problem:** Nach „Dokument neu erfassen" fand der virtuelle Textmarker das Datum zwar, der gelbe Balken samt rotem Rahmen deckte aber nur „18.11.20" ab, die letzten Ziffern standen außerhalb (Nutzerfund 11.09.2026 am Privatschutz-Brief).

**Ursache:** `recapture_document` setzte jedes OCR-Wort per `insert_text` mit einer Schriftgröße aus der Wort-HÖHE (0,8 × Höhe) in Helvetica ein. Die Breite ergab sich dann aus der Helvetica-Laufweite - bei breit gedruckten Ziffern schmaler als das gedruckte Wort. `search_for` liefert die Box des unsichtbaren Textes, nicht die des Bildes, also endete der Marker zu früh.

**Lösung:** `_textebene_wort_einfuegen`: Schriftgröße weiter aus der Höhe, zusätzlich eine horizontale Streckung/Stauchung per `morph`-Matrix um den Einfügepunkt, so dass `fitz.get_text_length` × Faktor exakt der Box-Breite entspricht. Tests `TestTextebeneWortbreite` prüfen, dass `search_for` die Box in x0/x1 auf 1,5pt genau trifft. **Lehre:** Wer eine unsichtbare Textebene schreibt, muss BEIDE Achsen an das Bild anpassen - alles, was später Boxen aus dem Text ableitet (Marker, Kopieren, Markieren im Viewer), erbt sonst den Versatz.

## 64. Suche nach „Kostal" markierte in der Vorschau „Stadtwerke"

**Problem:** Die OCR-Suche nach „Kostal" fand „20250131_Jahresabrechnung und Gebührenbescheid.pdf" (Stadtwerke Musterstadt), und die neue Treffer-Markierung legte den hellblauen Marker über das Wort „Stadtwerke". Das Wort „Kostal" kommt im Dokument nirgends vor.

**Ursache:** Kein Marker-Fehler, sondern ein Falschtreffer der unscharfen Suche, den der Marker nur sichtbar gemacht hat. Die Textebene des Scans enthält für „Stadtwerke" das Müll-Token `Sta(l^'tc^ke`. Der Matcher zerlegt es an den Sonderzeichen in `Sta`, `l`, `tc`, `ke` und prüft auch benachbarte Paare (die Heilung zerrissener Wörter wie „schornsteinl'eger"). Das Paar `Stal` hat zu „kostal" eine Ähnlichkeit von exakt 2·4/(6+4) = 0.8 - genau die Schwelle. Ein Bruchstück, das vollständig im Suchbegriff enthalten ist, liegt bei zwei fehlenden Buchstaben immer auf oder knapp unter der Schwelle.

**Lösung:** Ist das geprüfte Wort kürzer als der Suchbegriff, gilt die höhere Schwelle `FUZZY_THRESHOLD_KUERZER = 0.85`. Ein einzelner fehlender Buchstabe („Rechnug", 0.93) und die OCR-Klassiker („stadtvverke" ~ „stadtwerke", 0.857) bleiben erlaubt, gleich lange Wörter („Meier"/„Meyer", 0.8) unverändert. Merksatz: Ein Treffer-Marker, der auf ein anderes Wort zeigt, ist ein Hinweis auf die Textebene - erst dort nachsehen (`page.get_text("words")`), bevor man am Marker schraubt.

## 65. Erklärung beim Verweilen auf einem Menüeintrag: Tk-Menü-Klone liefern nur Namen

**Problem:** Für die Menü-Hilfe (Stufe 3, Vorbild Inventor) soll beim Verweilen auf einem Menüeintrag ein Fensterchen mit „Was/Wofür“ erscheinen. Offene Fragen vorab: Feuert Tk unter Windows überhaupt ein Ereignis, während ein natives Menü offen ist? Laufen `after`-Zeitgeber weiter? Kann ein Toplevel neben dem Menü erscheinen? Und im Versuch: der `<<MenuSelect>>`-Handler stürzte mit „substring not found“ ab.

**Ursache:** Die ersten drei Fragen beantwortet ein Versuch mit simulierter Maus (ctypes `SetCursorPos`/`mouse_event`) mit Ja: `<<MenuSelect>>` kommt bei jedem Wechsel des markierten Eintrags, Zeitgeber ticken weiter, ein `overrideredirect`-Toplevel wird sichtbar. Der Absturz: Für Menüleiste und Kaskaden legt Tk **Klone** an (`.#!menu.#!menu#!menu`), die tkinter nicht als Widgets kennt - `event.widget` ist dann ein **String**, und `"…".index("active")` ist die String-Methode. Zusätzlich ist der Klon-Name nicht auf das Original-Menü zurückführbar (welches Menü ist das: Datei? Rechtsklick Dokument? Tools → Aufräumen?).

**Lösung:** Alles per Tcl direkt auf dem Namen (`root.tk.call(name, "index", "active")`, `entrycget … -label`). Das Menü wird an seiner **Label-Folge** erkannt: beim ersten Bedarf werden Menüleiste, Kaskaden und die registrierten Kontextmenüs abgelaufen und ihre Einträge den Menü-Pfaden zugeordnet (Klon und Original haben dieselben Einträge); ein Fehlschlag (Menü nachträglich verändert) baut die Karte einmal neu. Position: rechte Kante des offenen Windows-Popup-Menüs (Fensterklasse `#32768` per `FindWindowW`), sonst rechts unter dem Zeiger. Merksatz: Bei Menü-Ereignissen nie auf `event.widget` als Objekt vertrauen - erst `str()`, dann Tcl.

## 66. Dubletten finden: der Teiler zwischen den Vorschauen wanderte mit dem Dateinamen

**Problem:** Die beiden Vorschauen unter der Tabelle sollen gleich breit sein. Je nach markierter Zeile war die linke aber mal schmaler, mal breiter - der „Teiler“ sprang beim Klick auf eine andere Zeile derselben Gruppe.

**Ursache:** `pack(side=LEFT, fill=BOTH, expand=True)` teilt nur den **Rest** gleich auf: jedes Widget bekommt zuerst seine Wunschbreite, und die hängt beim Vorschau-Kopf vom Text des Dateinamen-Labels ab („Markiert: 20241003_HKV.pdf“ gegen „Vergleich: 20241003_Beitragsrechnung HKV Privatschutz.pdf“). Längerer Name = breitere Vorschau.

**Lösung:** `grid` mit zwei Spalten in derselben `uniform`-Gruppe und gleichem `weight` (`lege_vorschauen_nebeneinander`) - die Breite wird unabhängig vom Inhalt halbiert. Zusätzlich bekommt das Titel-Label `width=10`, damit ein langer Dateiname keine Mindestbreite mehr erzwingt (er wird gestreckt bzw. abgeschnitten). Merksatz: Sollen zwei Bereiche exakt gleich breit sein, nie über pack/expand, sondern grid + uniform - und Labels mit variablem Text ohne eigene Wunschbreite.

## 67. KI-Aufrufe laufen in Musterstadt in den Timeout, obwohl Server, Tailscale und Upload in Ordnung sind

**Problem:** „Posteingang verarbeiten" bei einem Beta-Tester: jeder KI-Aufruf endete nach 90 s als Timeout. Von Hand geprüft: Server antwortet, Modell vorhanden, Tailscale-Ping 25 ms, 700 KB Upload in 0,2 s, ein Text-Aufruf per PowerShell in 0,8 s. Alles „gesund" - und trotzdem Timeout.

**Ursache:** Der Ollama-Server rechnete **still auf der CPU**. Ein `apt upgrade` in der VM hatte den NVIDIA-Userspace-Treiber auf 580.178 gehoben, das Kernel-Modul blieb 580.159 (`nvidia-smi`: „Driver/library version mismatch"). Ollama startet dann ohne GPU: `GET /api/ps` zeigte `size_vram: 0`, 14 Token/s statt 86. Ein Textaufruf schafft das noch in Sekunden (deshalb sahen alle Tests gut aus), ein Vision-Aufruf mit ~0,5 MB Seitenbild braucht auf der CPU Minuten. Hörbares Symptom am Server: Lüfter drehen hoch, weil die CPU statt der GPU arbeitet.

**Lösung:** VM neu starten (Kernel-Modul passt wieder), Treiberpaket festnageln (`apt-mark hold nvidia-driver-580`). In der App meldet „Verbindung testen" seitdem, ob das Modell im Grafikspeicher liegt (`ollama_client.gpu_status` über `/api/ps`), mit deutlicher Warnung bei CPU-Betrieb. Merksatz: Bei „Timeout trotz gesundem Server" zuerst `/api/ps` ansehen - Erreichbarkeit und Modellliste sagen nichts darüber, WO gerechnet wird. Details: Wiki „KI-Infrastruktur".

## 68. Vollautomatik: der Posteingang wurde nach jedem Dokument ZWEIMAL neu gelesen

**Problem:** Nutzerfund 12.09.2026 beim Durchlauf des Posteingangs mit der Vollautomatik: nach jedem abgelegten Dokument las die App den angezeigten Posteingang zweimal komplett neu (Aktivitätsanzeige „Lese Ordner …“ zweimal hintereinander, bei großen Ordnern spürbar).

**Ursache:** Im instrumentierten Rauchtest sichtbar: Metadaten schreiben, umbenennen und verschieben lösen einen Schub Watchdog-Ereignisse aus → nach 500 ms Debounce `sync_ui` → Ordnerbaum + Dokumentenliste neu lesen (erstes Lesen, gewollt). Genau während dieses Lesens meldete Windows ein einzelnes, verspätetes **`DirModifiedEvent` für den Posteingang-Ordner selbst** (Ordner-Zeitstempel nach der Änderung) - keine Datei-Ereignisse dazu. Der Debouncer nahm es als neue Änderung und las 500 ms später ein zweites Mal. Der Effekt kettet sich nicht weiter, weil das zweite Lesen keinen Nachzügler mehr erzeugt.

**Lösung:** `folder_monitor.SyncHandler` ignoriert reine „Ordner geändert“-Ereignisse (`ist_reines_ordner_ereignis`: `is_directory` und `event_type == "modified"`). Das kostet keine Information: Jedes Anlegen, Löschen, Umbenennen und Verschieben kommt als eigenes Datei- bzw. Ordner-Ereignis (created/deleted/moved) ohnehin an, und ein Ordner-„modified“ ohne solches Ereignis bedeutet nie einen Inhaltswechsel. Rauchtest danach: ein `sync_ui` pro Dokument statt zwei. Merksatz: Wer auf Dateisystem-Ereignisse mit eigenem Lesen reagiert, muss die Ereignisse herausfiltern, die das eigene Lesen erzeugt - sonst füttert sich der Debouncer selbst.

## 69. Windows-Textgröße 125 % (Barrierefreiheit): Knöpfe abgeschnitten, Unterlängen fehlen, Fußzeile weg

**Problem:** Am Tester-PC ist zusätzlich zur Skalierung 125 % auch die Windows-**Textgröße** (Einstellungen → Barrierefreiheit) auf 125 % gestellt. Ergebnis (12.09.2026, in der Simulation reproduziert): Knöpfe mit abgeschnittenem Text („Altbestand na…“, „Wartende KI-Ta…“), in den Bäumen/Tabellen fehlen die Unterlängen („Fahrzeua & Verkehr“, „Sammluna“), in den Einstellungen war die Fußzeile mit „Schließen“ gar nicht mehr da und „Ändern…“ hinter dem langen Sammlungs-Pfad aus dem Fenster gedrängt.

**Ursache:** Drei Dinge. (1) Die Textgröße vergrößert NUR die Systemschriften - Tk übernimmt sie in `TkDefaultFont` (9 pt → 11 pt) -, die Auflösung bleibt: `winfo_fpixels("1i")` liefert weiter 120 dpi. `UIUtils.skalierung` (FALLSTRICKE #42) sah also 1,25, obwohl der Platzbedarf bei 1,25 × 1,22 ≈ 1,53 lag. (2) `ttk.Treeview` hat eine feste Zeilenhöhe von 20 px - bei 11 pt auf 120 dpi ist die Schrift aber ~24 px hoch. (3) Pack-Reihenfolge: Ein `fill=BOTH, expand=True`-Inhalt, der höher/breiter als das Fenster ist, schiebt alles, was NACH ihm gepackt wurde, einfach hinaus (Fußzeile, Knopf rechts neben einem langen Label).

**Lösung:** (1) `UIUtils.schriftfaktor` = Punktgröße von `TkDefaultFont` / 9 (nur Windows, nie < 1); `skalierung` multipliziert DPI-Faktor und Schriftfaktor, alle `px()`-Maße wachsen mit. `UIUtils.schriftgroesse(widget, delta)` ersetzt feste 9/10-pt-Angaben (Reset-/Speichern-Knopf, Statusfenster). (2) `gui.py` setzt `Treeview rowheight = max(20, Zeilenabstand × 4/3)` - bei 100 % bleibt es bei 20 px. (3) Fußzeilen und Knöpfe neben langen Texten werden ZUERST und mit `side=BOTTOM`/`side=RIGHT` gepackt (Einstellungen: Fußzeile, „Ändern…“, „Altbestand nachziehen“). Prüfwerkzeug: Rauchtest `smoke_schrift_check.py` stellt `tk scaling` auf 120/72 und alle Tk-Schriften auf 11 pt, öffnet jedes Fenster und meldet Knöpfe, die nicht sichtbar, abgeschnitten oder kleiner als ihr Platzbedarf sind. Merksatz: Skalierung und Textgröße sind zwei unabhängige Windows-Regler - messen, was Tk wirklich als Schrift benutzt, statt nur die dpi zu fragen; und was nach dem dehnbaren Inhalt gepackt wird, ist das Erste, das verschwindet.

## 70. Nach „Reset“ der Suche bleibt die Dokumentenliste leer

**Problem:** Beim Rauchtest des neuen Suchfelds (13.09.2026) aufgefallen, im alten Stand reproduziert: Suchen, ein Treffer wird angezeigt, dann „✖ Reset“ - die Liste ist leer, obwohl links weiter der Ordner markiert ist. Erst ein erneuter Klick auf den Ordner füllt sie.

**Ursache:** `gui.on_file_select` setzt bei aktiver Suche bei JEDEM Klick auf einen Treffer das Such-Schutzschild `ignore_next_select = True` (FALLSTRICKE #14). Gedacht ist es für das Tree-Event, das die automatische Ordner-Markierung des Treffers auslöst. Liegt der Treffer aber im ohnehin markierten Ordner (oder wird der Treffer automatisch als erste Zeile ausgewählt), feuert kein solches Event, und das Schild bleibt scharf. Der nächste `on_folder_select(None)` - genau der ausdrückliche Neuaufbau, den `search_manager._apply_filters` nach dem Reset anstößt - wird dann verschluckt.

**Lösung:** `_apply_filters` löscht das Schild, bevor es den Neuaufbau ohne Suche aufruft. Merksatz: Ein „ignoriere das nächste Event“-Schild muss von dem gelöscht werden, der das Event bewusst auslöst - sonst trifft es irgendwann den Falschen.

## 71. LabelFrame ohne Text reserviert die Titelzeile trotzdem

**Problem:** Um Platz zu sparen, bekamen die fünf Bereichs-Rahmen des Hauptfensters (Ordnerbaum, Tag-Baum, Suchleiste, Dokumentenliste, Eigenschaften) am 13.09.2026 `text=""`. Die Titel waren weg, der Platz aber nicht: Über jedem Inhalt blieb ein leerer Streifen in Höhe der alten Beschriftung (Peters Screenshot).

**Ursache:** `ttk.LabelFrame` legt die Rahmenlinie immer in die Mitte der Beschriftungszeile und rückt den Inhalt entsprechend nach unten - auch wenn die Beschriftung leer ist. Der Platzbedarf hängt am Widget-Typ, nicht am Text.

**Lösung:** Die fünf Rahmen sind jetzt `ttk.Frame(relief="groove", borderwidth=1)` - sieht wie der LabelFrame-Rand aus, der Inhalt beginnt aber direkt unter der Oberkante (Rauchtest `smoke_rahmen.py`: erstes Kind-Widget 6 px unter der Rahmen-Oberkante, vorher ~28 px). Merksatz: Wer bei einem LabelFrame nur den Text leert, spart keinen Platz - der Rahmen-Typ muss gewechselt werden.

## 72. ttk.PanedWindow rückt den Greifer nicht nach, wenn ein Bereich höher werden will

**Problem:** Der Eigenschaften-Bereich (unterster Teil des senkrechten PanedWindows in der Mitte, `weight=0`) wurde am 14.09.2026 zur Tabelle. Beim Anhaken von „Details“ wuchs die Tabelle - und schob Speichern, Auto-Save und das Details-Häkchen selbst aus dem sichtbaren Bereich (Peter 15.09.2026). Beim Programmstart passte alles, weil das PanedWindow die Bereiche EINMAL nach ihrem Platzbedarf verteilt.

**Ursache:** `ttk.PanedWindow` behandelt die Greifer nach dem ersten Layout als vom Nutzer gesetzt. Ändert ein Bereich später seine Wunschhöhe (`winfo_reqheight`), bleibt der Greifer, wo er ist; der Inhalt wird abgeschnitten. Dazu kam die Pack-Reihenfolge: Die Knopfzeile war NACH der Tabelle gepackt und flog als Erstes hinaus.

**Lösung:** Zweiteilig. (1) Knopfzeile ZUERST mit `side=BOTTOM` packen, Tabelle danach mit `side=TOP` - dieselbe Regel wie für die Fußzeile der Einstellungen (#69): Knopfleisten vor dem dehnbaren Inhalt verankern. (2) `EigenschaftenPanel._platz_anfordern` setzt nach jedem Neuaufbau (per `after_idle`, also nach dem Zeichnen) den Greifer über dem Bereich auf `Pane-Höhe − Wunschhöhe − Greifer-Dicke`, so dass sich der Bereich nach oben entfaltet und beim Einklappen wieder Platz an die Dokumentenliste abgibt. Merksatz: Ein PanedWindow ist keine Pack-Geometrie - wer nach dem Start die Höhe eines Bereichs ändert, muss den Greifer selbst nachziehen.

## 73. Zeile in der Dokumentenliste nach Ordnerwechsel „springt zurück“ (doppeltes on_folder_select)

**Problem:** Ein Werkzeug-Fenster (Titel-Aufräumen, Ablage-Vorschau) will zur Kontrolle das Dokument einer Zeile im Hauptfenster zeigen: links in den Ordner wechseln, dann die Zeile in der Dokumentenliste wählen. Die Zeile war korrekt gewählt - und eine Viertelsekunde später stand die Auswahl wieder auf der ERSTEN Zeile des Ordners, die Vorschau zeigte das falsche Dokument.

**Ursache:** `_select_and_open_path` setzt `tree_folders.selection_set(item)` und ruft `on_folder_select(None)` direkt auf (füllt die Liste, wählt die erste Zeile). Der `selection_set` erzeugt aber zusätzlich ein `<<TreeviewSelect>>`, das Tk erst NACH dem laufenden Aufruf zustellt - dann läuft `on_folder_select` ein zweites Mal, baut die Liste neu auf und wählt wieder die erste Zeile, weil `current_preview_path` inzwischen auf sie zeigt. Die eigene Zeilenauswahl lag dazwischen und wurde überschrieben.

**Lösung:** `FolderManager.zeige_dokument(pfad)` (20.09.2026) ist der gemeinsame Helfer für alle Werkzeug-Fenster und wählt die Zeile nach einem Ordnerwechsel erst per `root.after_idle` - also nachdem das nachgereichte Ereignis abgearbeitet ist - und schaut, falls die Zeile noch fehlt, bis zu zehnmal alle 50 ms erneut nach: der Idle-Aufruf kann mitten im zweiten Listenaufbau landen (ein `update_idletasks` beim Zeichnen der Vorschau der ersten Zeile), wenn die alten Zeilen schon gelöscht, die neuen noch nicht eingefügt sind. Ohne Ordnerwechsel wird sofort gewählt. Allgemein: nach `selection_set` auf einem Treeview mit gebundenem `<<TreeviewSelect>>` nie davon ausgehen, dass der Handler schon gelaufen ist.

## 74. Ordner-Klick erst beim zweiten Mal angenommen (Haken „Inhalt (OCR)“)

**Problem:** Nach einer Suche mit Haken „Inhalt (OCR)“ und ✖ Reset reagierte ein Klick auf einen Ordner erst beim zweiten Mal (Peter, Release-Check T0.6, 25.10.2026).

**Ursache:** `gui.on_file_select` zählte für das Such-Schutzschild (#14) schon den OCR-Haken allein als laufende Suche. Reset leert Suchtext und Datum, lässt den Haken aber stehen - danach schärfte JEDER Klick auf ein Dokument `ignore_next_select`, und weil kein automatisches Ordner-Ereignis folgte, traf das Schild den nächsten echten Ordner-Klick (dieselbe Falle wie #70, nur aus einer anderen Ecke).

Bei der Nachprüfung zeigte sich derselbe Effekt auch bei echter Suche: Treffer anklicken schärft das Schild, aber die frühere Komfortfunktion „Treffer markiert seinen Ordner“ (für die #14 das Schild erfand) gibt es nicht mehr - also traf es wieder den nächsten Ordner-Klick.

**Lösung:** `on_file_select` nutzt `SearchManager.is_search_active()` (Text, Datum von/bis, Filter-Tags - nicht der OCR-Haken), und `FolderManager.on_tree_click` - ein echter Mausklick in den Ordnerbaum - entschärft ein liegengebliebenes Schild, bevor `<<TreeviewSelect>>` feuert. Programmgesteuerte `on_folder_select(None)`-Aufrufe während einer Suche bleiben geschützt wie bisher. Merksatz: Ein Schalter, der nur das WIE einer Suche festlegt, ist kein Zeichen dafür, DASS gesucht wird - und ein ausdrücklicher Nutzerklick ist nie das „nächste automatische Ereignis“.

## 75. Vollautomatik holte neue Scans erst nach einer Minute ab

**Problem:** Eine in den Posteingang kopierte PDF wurde erst nach rund 65 Sekunden abgelegt, die Checkliste verspricht etwa 10 Sekunden (Release-Check T0.13, 25.10.2026).

**Ursache:** Zwei Wartezeiten passten nicht zusammen. Nach dem Dateisystem-Ereignis wartet der Dienst `RUHEZEIT_NACH_EREIGNIS` = 3 s auf Ruhe und startet dann eine Runde - eine Datei gilt aber erst als fertig, wenn sie `STABIL_MINDESTALTER` = 5 s unverändert ist. Die neue Datei war also in genau dieser Runde noch „unfertig“, wurde übersprungen, und weil danach kein weiteres Ereignis kam, griff erst die Fallback-Runde nach `PRUEF_INTERVALL` = 60 s. Ein Scanner schreibt ebenfalls frische Dateien - derselbe Effekt.

**Lösung:** `eine_runde` zählt die noch unfertigen Dateien (`_unfertige`), und `naechste_wartezeit()` liefert dann `NACHPRUEFEN_NACH` (Mindestalter + 1 s) statt des Fallback-Intervalls. Gemessen: 12 s vom Kopieren bis zur Protokollzeile. Merksatz: Wer „erst warten, dann prüfen“ macht, muss auch den Fall „geprüft, war noch zu früh“ mit einem eigenen Wecker abdecken. Nachtrag (Betatest 25.10.2026): Derselbe Effekt nach jedem Programmstart - `_schleife` wartete zuerst `PRUEF_INTERVALL`, bevor sie das erste Mal nachsah; Post, die bei geschlossener App eingelegt worden war, lag eine Minute ohne jede Anzeige herum. `start()` setzt jetzt das Weck-Ereignis, die erste Runde läuft nach der Ruhezeit (3 s).

## 76. Suche ohne OCR: Wort in der Vorschau markiert, Dokument aber nicht in der Liste

**Problem:** Dokument angezeigt, dann ein Wort aus seinem Text gesucht (Häkchen „Inhalt (OCR)“ aus): Die Trefferliste enthielt das Dokument nicht, Vorschau und Eigenschaften zeigten es aber weiter - samt blau markiertem Treffer (Release-Check T0.18, 25.10.2026).

**Ursache:** Zwei Wahrheiten. Ohne OCR durchsucht die Suche nur Name, Titel und Tags; die Treffer-Markierung der Vorschau (`PDFHandler.suchtreffer_boxen`) liest den Seitentext dagegen immer. Und `_apply_filters` baute nur die Liste neu - das angezeigte Dokument blieb stehen, auch wenn es nicht mehr dazugehörte.

**Lösung:** Nach dem Neuaufbau entscheidet `SearchManager.anzeige_nach_suche` (rein, getestet): angezeigtes Dokument unter den Treffern → stehen lassen; sonst `gui.leere_dokumentanzeige` (erst `flush_pending`, dann Vorschau/Titel/Tags/Eigenschaften leer). Hat eine Textsuche ohne OCR gar keine Treffer, steht `HINWEIS_OHNE_OCR` grau in der leeren Vorschau. Auch eine schon leere Anzeige wird geleert, sonst bliebe der alte Hinweis stehen, wenn die nächste Suche (mit OCR) Treffer hat. Nachtrag (Peters Fund am selben Abend): Auch ohne Suche kann die Liste leer bleiben - Reset, während links kein Ordner markiert ist (z.B. direkt nach dem Start gesucht). Dort leert `_apply_filters` die Anzeige jetzt ebenfalls. Merksatz: Was angezeigt wird, muss in der Liste stehen.

## 77. Große Schrift: Fenster ragen unten über den Bildschirm, Datum in der Liste abgeschnitten

**Problem:** Release-Check T0.16 (25.10.2026) mit simulierter 125-%-Skalierung + 125-%-Textgröße: Das Einstellungsfenster ragte unten über den Bildschirmrand, „Schließen“ war nur halb zu sehen. In der Dokumentenliste stand „27.04.202“, im Ordnerbaum war die Dokumentenzahl angeschnitten.

**Ursache:** (1) Tk zählt bei `geometry("BxH+X+Y")` B×H als INNENmaß, X/Y aber als Außenkante. `UIUtils._begrenzt_auf_monitor`/`position_near_mouse` rechneten ohne Titelleiste und Rahmen - jedes nahe am unteren Rand geöffnete Fenster lag um gut 30 px zu tief (unabhängig von der Schriftgröße, bei großen Fenstern fällt es nur eher auf). (2) Die Spaltenbreiten der Dokumentenliste und des Ordnerbaums waren feste Pixel, nicht über `UIUtils.px()` (FALLSTRICKE #42), und wurden auch als echte Pixel gespeichert. (3) Warum die echte Windows-Einstellung nichts zeigte: Python und die EXE sind nicht DPI-fähig - Windows meldet 96 dpi und vergrößert das Fenster nur als Bild, die Textgröße kam bei der Systemschrift (`SPI_GETNONCLIENTMETRICS`: -12 px) nicht an; bei Peter steht außerdem nur der Hauptmonitor auf 125 %.

**Lösung:** (1) `UIUtils.fensterrahmen()` (Titelleiste + Rahmen über `GetSystemMetrics`, Rückfall 16×39) geht in Begrenzung und Größenkappung ein. (2) `layout_builder.STANDARD_BREITEN`/`MINDEST_BREITEN` in 100-%-Pixeln, `breiten_fuer_bildschirm` multipliziert mit `UIUtils.skalierung`, `gui.on_closing` speichert über `breiten_zum_speichern` wieder in 100-%-Einheiten (alte gespeicherte Werte waren praktisch die unskalierten Standards, passen also). (3) Für den Test: `python fernsteuerung.py start schrift125` simuliert 120 dpi + 11 pt in der App (`simuliere_grosse_schrift`), Windows bleibt unverändert.

## 78. Speichern scheitert an Dateinamen mit ●/■/□ - wegen einer Debug-Zeile

**Problem:** Das neue Werkzeug „Dokument-IDs vergeben“ meldete 7 von 403 Dateien als „nicht beschreibbar“ - alle mit Zeichen wie ●, ■ oder □ im Namen (OCR-Müll aus Scanner-Dateinamen, 25.10.2026). Dieselben Dateien ließen sich in einem eigenen Python-Prozess problemlos beschreiben.

**Ursache:** `PDFHandler.write_custom_metadata` gibt vor dem Schreiben `print(f"--- DEBUG: Speichere Metadaten für {name} ---")` aus. Unter der Fernsteuerung (und bei jeder Umleitung der Ausgabe in eine Datei) gilt für `sys.stdout` der Windows-Zeichensatz cp1252 - ●/■/□ sind dort nicht darstellbar, `print` wirft `UnicodeEncodeError`, der landet im `except` des Schreibwegs, und das Speichern gilt als gescheitert. Betroffen war also JEDES Speichern solcher Dateien, nicht nur die ID. Die EXE hat keine Konsole (`sys.stdout` ist None), dort trat es nicht auf; im VS-Code-Terminal auch nicht (echte Konsole, Unicode).

**Lösung:** `fehlerfaenger.ausgabe_absichern()` stellt stdout/stderr beim App-Start (gui.py, direkt nach dem Fehlerfänger) auf `errors="backslashreplace"` um - nicht darstellbare Zeichen erscheinen als `\u25a1`, statt einen Fehler zu werfen. Merksatz: Diagnose-Ausgaben dürfen nie Teil des Erfolgswegs sein - ein `print` innerhalb eines `try`, dessen `except` „fehlgeschlagen“ meldet, macht aus einem Anzeigeproblem einen Datenfehler.

## 79. Ablage-Vorschau: Zielordner-Klick lässt „Absender nur als Kürzel“ stehen

**Problem:** Betatest 25.10.2026: Drei Dokumente der VR-Bank blieben nach dem Zielordner-Klick gelb - der Grund „Absender nur als Kürzel erkannt: 'VR-NetWorld' - Zielordner anklicken, dann merkt sich die Automatik den Ordner“ stand weiter da, obwohl genau dieser Klick gemacht war.

**Ursache:** `wende_zielordner_an` räumt nur die Probleme weg, die mit einem Eintrag aus `_ORDNER_PROBLEM_PRAEFIXE` beginnen. Der Kürzel-Hinweis kam später dazu (Rücksendezeilen, 07.09.2026) und wurde dort nicht nachgetragen. Damit war er auch kein „korrigierbares“ Problem (`korrigierbare_probleme`) - die Freigabe-Logik behandelte ihn wie eine Dublette.

**Lösung:** Präfix „Absender nur als Kürzel“ in `_ORDNER_PROBLEM_PRAEFIXE`, Test `test_zielordner_klick_raeumt_kuerzel_hinweis_weg`. Merksatz: Ein Problemtext, der eine Handlung verlangt, braucht einen Test, dass genau diese Handlung ihn auflöst.

## 80. Vollautomatik legt still Doppelordner an (HKV neben „HKV Versicherung AG“)

**Problem:** Betatest 25.10.2026 (alte Ordnerstruktur, 403 Dokumente einzeln eingescannt): 28 neue Ordner neben bestehenden, 11 % der Ablagen gingen dorthin - „HKV Versicherung AG“ neben „HKV“, „WMV-Versicherung AG“ neben „WMV“, „ElsterOnline“ neben „ELSTER“, „Vivafone Deutschland GmbH“ neben „Vivafone Kabel Deutschland“. Alles als „sicher“, also ohne dass jemand gefragt wurde.

**Ursache:** (1) `MIN_ORDNER_MATCH_LAENGE` = 4 übersprang Ordnerkerne unter 4 Zeichen komplett - auch den exakten Vergleich, sodass selbst der Absender „WMV“ den Ordner „WMV“ nicht fand. (2) Der Wort-Mengen-Vergleich verlangt ALLE Ordnerwörter im Absender; „Bayr.“ und „f.“ stehen nie wörtlich in „Bayerisches Landesamt für Statistik“. (3) Fand sich nichts, entstand ohne weitere Prüfung ein neuer Ordner - „ähnlich“ gab es nicht, nur „gleich“ oder „neu“.

**Lösung:** Stufe A (sicher zuordnen): exakter Name auch für kurze Ordner; Kürzel-Ordner (`_KUERZEL_ORDNER`, 2-3 Großbuchstaben) treffen, wenn sie GROSS als ganzes Wort im Absender stehen (`_kuerzel_im_absender`); abgekürzte Ordnerwörter (mit Punkt) zählen nicht mit, wenn mindestens zwei ausgeschriebene Wörter übrig bleiben und alle passen. Stufe B (Mensch fragen): bevor ein neuer Ordner entsteht, sucht `finde_aehnlichen_ordner` einen vorhandenen mit gemeinsamem unverwechselbarem Wort (≥ 5 Zeichen, kein Allerweltswort der Sammlung, auch als Wortanfang ab 6 Zeichen oder mit Tippfehler - aber ein Tippfehler allein reicht nicht, sonst ähnelte „Bayerische Landesbrandversicherung“ dem Ordner „die Bayrische“). Dann bleibt die Ablage unsicher, der ähnliche Ordner ist vorgewählt (Problem „Ähnlicher Ordner vorhanden:“, per Zielordner-Klick korrigierbar). Nachgemessen am gesammelten KI-Korpus der 403 Dokumente (`KID-Messungen/betatest/abgleich_messen.py`): richtiger Ordner 223 → 271, still in einen Doppel-/Fremdordner 115 → 61 (der Rest ist Weltwissen wie Landesbrand → Versicherungskasse, also Alias-Sache), kein einziges Dokument landet neu still falsch. Merksatz: Zwischen „gleich“ und „neu“ braucht eine Zuordnung die Stufe „ähnlich“ - und die gehört dem Menschen.


## 81. Neues KI-Modell rechnet Minuten statt Sekunden - es „denkt“ vor jeder Antwort

**Problem:** Modell-Prüfstand 27.10.2026 (403 Dokumente, Ollama 0.40.11): `qwen3.5:9b`, `gemma4:12b` und `nemotron-3.5-bolt` brauchten für dieselbe Ablage-Anfrage ein Vielfaches der Zeit von `qwen2.5vl:7b`; `qwen3-vl:8b` lag bei 60-90 s je Dokument. Beim Wechsel zwischen zwei Modellen kam einmal noch ein zweiter Effekt dazu: über 200 s je Dokument bei nur 11 % Grafikkarten-Last.

**Ursache:** (1) Neuere Modelle sind „denkende“ Modelle (`/api/show` meldet die Fähigkeit `thinking`) und schreiben vor der eigentlichen Antwort seitenlange Überlegungen - bei KIDs Ablage-Prompt rund 6000 Tokens. (2) `qwen3-vl:8b` denkt unter Ollama 0.40.11 sogar trotz `"think": false`; eine `num_predict`-Grenze schneidet dann nur die eigentliche Antwort ab (leere Felder). (3) Lag beim Modellwechsel das vorige Modell noch im Grafikspeicher (`OLLAMA_MAX_LOADED_MODELS=2`), lud Ollama das neue nur zu 30 von 37 Schichten auf die Karte - der Rest rechnete auf dem Prozessor.

**Lösung:** `ollama_client._generate` schickt immer `"think": false` mit (Test `test_schaltet_das_nachdenken_ab`); nicht denkende Modelle und ältere Ollama-Versionen ignorieren das Feld (geprüft mit `qwen2.5vl:7b`). `qwen3-vl` ist damit für KID ungeeignet. Der Wechsel zwischen Lese- und Entscheidungsmodell (Zweitmeinung zur Ordnerwahl, `ollama_client.waehle_ordner`) lief im Test sauber ganz auf der Karte (~22 s je Dokument für beide zusammen); hängt ein Wechsel, zeigt „Verbindung testen“ das als „teilweise“ (`gpu_status`). Merksatz: Ein neues Modell erst am eigenen Bestand messen - Geschwindigkeit UND Ergebnis; das alte `qwen2.5vl:7b` legte unter dem neuen Ollama zwar doppelt so schnell, aber 79 statt 56 Dokumente still falsch ab.


## 82. Tag-Wildwuchs: Varianten warten getrennt, und der Prompt bestellt Doppelbegriffe

**Problem:** Betatest 25./26.10.2026 (403 Dokumente, Vollautomatik): 124 verschiedene Tags in den PDFs, davon 61 nicht im Katalog und 66 an genau einem Dokument. Dieselbe Adresse stand in fünf Schreibweisen da („Zum Alten Faß 1“, „Zum-Alten-Faß 1“, „Zum Alten Fass Nr1“ …), dazu Doppelbegriffe wie „Haftpflicht“ neben „Haftpflichtversicherung“ und Müll wie „AFP LPD PDF TIFF“, „3 TAN: 309876“, „Sehr geehrter Kunde“. Sammelangaben („Zum alten Fass 1 u. 3“, „Musterstadt / Musterheim“, „Weidenstr. 8 Whg 2 and 4“) waren je EIN Tag - die Suche nach Hausnummer 3 fand diese Dokumente nicht.

**Ursache:** (1) Personen und Objekte schnappten nur auf die Schreibweise des KATALOGS. Neue Tags kommen aber erst nach dem zweiten Dokument in den Katalog (Warteliste, `tag_kandidaten`) - und die Warteliste vergleicht wörtlich. Jede Variante wartete also für sich, keine erreichte je zwei Dokumente, alle blieben als Einzelgänger in den PDFs. (2) Der Ablage-Prompt nannte als Beispiel ausdrücklich „Gebäudebrandversicherung“ und „Hausratversicherung“, der ausgelieferte Katalog hat „Gebäudeversicherung“ und „Hausrat“ - die KI tat, was man ihr sagte. (3) Nichts prüfte die FORM eines neuen Tags; Personen, Adressen und Absender kamen auch über das Tag-Feld, obwohl es dafür eigene Felder gibt. (4) Hausnummern-Sammelangaben trennte `teile_objekte` nicht („u.“, „+“, „and“ fehlten), und die Sammelform im Katalog zog Varianten sogar an.

**Lösung:** (1) `tags_mit_empfaenger(…, wartende=)`: Personen/Objekte schnappen zusätzlich auf die Schreibweisen der Warteliste (`tag_kandidaten.texte`, Katalog geht vor). (2) Prompt verlangt „steht ein passender Tag in der Liste, genau dessen Schreibweise“, deutsches Hauptwort, höchstens drei Wörter, keine Namen/Adressen/Nummern (`ollama_client.TAG_FORM_REGEL`); `tags_default.json` bringt Synonyme ab Werk mit (Langformen → Katalog-Tag). (3) `grund_gegen_neues_tag` verwirft neue Sach-Tags mit Ziffern, über drei Wörtern, klein geschrieben, Anrede, englischen Füllwörtern, Dateiformaten oder gleich dem Absender (Grund im Log: „Tags verworfen für …“). (4) Ein Objekt je Tag: `teile_objekte` zerlegt „1 u. 3“, „1+3“, „Whg 2 and 4“ und gibt der nackten Nummer die Straße davor; auch ohne Kategorie und für den Ort. Gemessen am Korpus (`KID-Messungen/betatest/tag_messen.py`, echte Pipeline, Warteliste simuliert), siehe ToDo. Merksatz: Eine Warteliste, die wörtlich vergleicht, lässt genau die Varianten nie durch, gegen die sie schützen soll - und ein Prompt-Beispiel ist für die KI eine Bestellung.


## 83. Vollautomatik hält einen nie angelegten Ordner für vorhanden („Zielordner existiert nicht mehr“)

**Problem:** Nachtlauf 28.10.2026 (frische Sammlung, 403 Dokumente): 15 Briefe der Versicherungskasse landeten in `0_Unsicher` mit „Zielordner 'A - B - C - D - E\Bayerische Landesbrandversicherung' existiert nicht mehr (seit der Analyse umbenannt oder gelöscht?)“ - den Ordner hatte es nie gegeben. Weitere Briefe (Zensus vom Landesamt für Statistik) bekamen ihn als „ähnlichen Ordner“ vorgewählt. Außerdem wählte die Ähnlichkeits-Bremse in einer frischen Sammlung oft Unpassendes vor: „Versicherungskasse Musterland“ → „HKV Versicherung AG“, jeder Kaminkehrer → „Kehrmann, Fritz (Kaminkehrer)“.

**Ursache:** (1) Die Varianten-Zusammenführung (`auto_pilot_service._verarbeite`, Worker in `tools/auto_filer.py`) nahm JEDEN neu vorgeschlagenen Ordner sofort in die Ordnerliste der Runde auf - auch den eines UNSICHEREN Dokuments, das in `0_Unsicher` landet. Der Ordner existierte nur in der Liste; das nächste Dokument desselben Absenders fand ihn per Namensvergleich als „vorhanden“ (`ordner_neu=False`), und `fuehre_entscheidung_aus` stellte dann zu Recht fest, dass er fehlt. (2) `finde_aehnlichen_ordner` erkennt Allerweltswörter nur, wenn sie in mindestens zwei Ordnern stehen (`_mehrdeutige_woerter`) - in einer frischen Sammlung steht „Versicherung“ erst in einem.

**Lösung:** (1) Die Ordnerliste wächst nur noch durch SICHERE Ablagen (im Dienst nach der erfolgreichen Ablage). (2) Zweistufig: die Bremse bleibt wie sie ist (gleiche Bedingung „ähnlich“, gleiches „unsicher“), die VORAUSWAHL prüft aber ohne Gattungs- und Herkunftswörter (`_GATTUNGSWOERTER`: Versicherung, Bayerische, Deutsche, Service …) und ohne Klammerzusatz im Ordnernamen (`finde_aehnlichen_ordner(…, ohne_gattungswoerter=True)`). Bleibt dann nichts Ähnliches übrig, ist der NEUE Ordner vorgewählt (`ordner_neu=True`, unsicher) - Enter in der Ablage-Vorschau legt ihn an. Gemessen am Korpus (`KID-Messungen/betatest/frisch_messen.py` und `abgleich_messen.py`): frische Sammlung falsche Vorauswahl 78 → 31, Phantom-Ordner 7 → 0, still falsch unverändert 8; gewachsene Sammlung: keine sichere Ablage ändert sich. Die Gattungswörter ganz aus der Ähnlichkeit zu nehmen (Versuch 1) machte drei Briefe still falsch - dort war die „falsche“ Ähnlichkeit die Bremse. Grenze: Ortsnamen („… Musterstadt“ → „Bürgerbüro Musterstadt“) wählten in einer frischen Sammlung weiter falsch vor, bis ein zweiter Ordner den Ort enthält - nachgezogen 28.10.2026 nachts: auch der Ort des Dokuments laut KI (`ki_antwort["ort"]`, Parameter `ortswoerter`) zählt für die Vorauswahl nicht; falsche Vorauswahl 31 → 17, richtige 12 = 12 (`betatest/ort_messen.py`). Stufe 2 (29.10.2026, Peters OK): auch die bisher gelesenen KI-Orte zählen nicht (`auto_pilot.merke_orte` nach jedem `lies_dokument`, Parameter `orte=` durch `entscheide_gelesen`/`entscheide_im_stapel`; die Menge `AutoPilotService.orte` lebt bis zum Programmende, die Ablage-Vorschau teilt sie) - falsch 17 → 4, richtig 12 → 11 (`betatest/orte_echt_messen.py`). Merksatz: Was nur vorgeschlagen ist, darf für die nächste Entscheidung nicht als Tatsache gelten - und Bremse und Vorauswahl sind zwei verschiedene Fragen.

## 84. Mausrad blättert nicht, wenn der Cursor im Datumsfeld steht

**Problem:** Release-Check 28.10.2026: Ein Dokument angeklickt, Mausrad über der Vorschau - es scrollt bis zum Seitenende, blättert aber nie auf Seite 2. Beim nächsten Dokument ging es wieder.

**Ursache:** Die Datums-Automatik („Datum beim Anklicken eintragen“, `auto_fill_on_click`) setzt bei Dokumenten ohne Datum 250 ms nach dem Klick den Fokus ins Datumsfeld, damit man den Vorschlag gleich korrigieren kann. `PreviewManager.flip_page` bricht ab, solange ein Eingabefeld den Fokus hat - das ist richtig für die Pfeiltasten (die gehören dann dem Feld), das Mausrad lief aber über dieselbe Funktion.

**Lösung:** `on_preview_mousewheel` ruft direkt `_blaettern` (ohne Fokus-Prüfung). Das Mausrad über der Vorschau meint immer die Vorschau. Test: `test_mausrad_blaettert_auch_mit_fokus_im_eingabefeld`.

**Merksatz:** Eine Fokus-Sperre gehört an die Tastatur-Bindung, nicht an die gemeinsame Aktion, die auch Maus-Ereignisse auslösen.

## 85. Titel-Vorschlag (KI): „Interner Fehler“ nach dem Schließen des Fensters

**Problem:** Beta-Test 28.10.2026: Fenster „Titel-Vorschlag (KI)“ geschlossen, während die Vorschläge noch geladen wurden - kurz danach „Interner Fehler“ mit `TclError: invalid command name ".!aititlesuggestwindow3.!treeview"` in `_on_suggestion_ready`.

**Ursache:** Der Hintergrund-Thread arbeitet alle Dokumente ab und meldet jedes Ergebnis per `self.after` an das Fenster. Nach dem Schließen ist die Treeview zerstört, die nächste Antwort fragt trotzdem `self.tree.exists(iid)` - Tk kennt das Widget nicht mehr. Außerdem lief die KI für die restlichen Dokumente umsonst weiter.

**Lösung:** Schließen geht über `_schliessen` (Stopp-Flag `_stop`, der Worker hört nach dem laufenden Dokument auf), `_on_suggestion_ready` prüft zuerst `self.winfo_exists()` - dasselbe Muster wie Tag-Ergänzer und Ablage-Vorschau. Test: `test_spaete_ki_antwort_nach_schliessen_ohne_fehler`.

**Merksatz:** Jeder Rückruf aus einem Hintergrund-Thread muss damit rechnen, dass sein Fenster inzwischen weg ist - und jedes Fenster mit Worker braucht ein Stopp-Flag beim Schließen.

## 86. Liste zeigt den Download-Tag statt des Dokumentdatums, obwohl unten das richtige Datum steht

**Problem:** Beta-Test 28.10.2026: Kontoauszüge heruntergeladen, Titel per „Titel-Vorschlag (KI)“ gesetzt - in der Dokumentenliste steht bei allen der 28.10.2026, unten in den Eigenschaften aber das richtige Datum (z.B. 2025-01-31).

**Ursache:** Das Datum in den Eigenschaften war nur ein VORSCHLAG (`PDFHandler.suggest_document_date`, aus dem Seitentext gelesen), stand aber schwarz da wie ein gespeichertes. Ins PDF kam es nur per Return im Datumsfeld (oder mit „Datum beim Anklicken eintragen“). Weder Speichern/Auto-Save von Titel/Tags noch der Titel-Vorschlag schrieben es mit; die Liste zeigt ohne `KID_DokumentenDatum` das Datei-Änderungsdatum.

**Lösung:** (1) Ein nur vorgeschlagenes Datum steht orange im Feld (`preview_manager.DATUM_VORSCHLAG_FARBE`, dieselbe Farbe wie „unberührt“ in der Liste; Grau war Peter zu schwach - „nur erkennbar, wenn man sich erinnert, was es bedeutet“), Tooltip erklärt es, Tippen macht es schwarz. (2) Die Vorschau merkt sich in `app.datum_feld` = {pfad, gespeichert, notbehelf}, wem das Feld gehört; `save_manager.datum_zum_mitspeichern` entscheidet, ob beim Speichern von Titel/Tags das Feld-Datum mitgeht (gleiches Dokument, gültig, weicht vom gespeicherten ab, ist nicht das Datei-Datum als Notbehelf) - `PDFHandler.save_metadata(…, datum=)` schreibt es im selben Vorgang, der Auto-Save zieht die Listenzeile mit. Bei Mehrfachauswahl bekommt nur das angezeigte Dokument das Datum. (3) Der Titel-Vorschlag schreibt bei Dokumenten ohne Datum das aus dem Text gelesene mit (ohne Notbehelf). (4) Ordner- und Trefferliste zeigen bei PDFs ohne gespeichertes Datum das vermutete statt des Datei-Datums (auch der Von/Bis-Filter rechnet damit): `IndexManager.vermutete_daten` merkt es in der Index-Tabelle `datum_vermutet` (frisch über mtime+Größe, '' = nichts gefunden, wird auch gemerkt), `index_manager.vermutete_daten_sicher` liefert ohne/bei defektem Index `{}` → Datei-Datum wie früher. Gemessen: 158 undatierte Dokumente 0,88 s beim ersten Öffnen, danach 0,12 s (~14 ms je Dokument fürs Lesen). (5) Mit Auto-Save genügt Anklicken und Weiterklicken (Peters Wunsch): `SaveManager.datum_beim_verlassen(neuer_pfad)` läuft in `gui.on_file_select`, bevor die Felder neu befüllt werden, und schreibt das Feld-Datum des bisherigen Dokuments (gleiche Regeln wie `datum_zum_mitspeichern`); wählt ein Listen-Neuaufbau dasselbe Dokument wieder aus, zählt das nicht als Verlassen. Die Zeile verliert dabei „unberührt“ (`gui.aktualisiere_datumszeile`, ausgelagert aus `save_manual_date`). (6) Vorauswahl ohne Fokus-Raub (Peters Idee): ein vermutetes Datum ist orange HINTERLEGT mit weißer Schrift (`gui.setze_datum_stil`) und wirkt wie markiert; eine Ziffer in der Dokumentenliste (`datum_aus_liste_tippen`, nur bei vermutetem Datum) springt ins Feld und ersetzt den Vorschlag, Return speichert und gibt den Fokus an die Liste zurück, Esc stellt den Vorschlag wieder her. Echte Vorauswahl per `focus_set` hätte die Pfeiltasten der Liste gestohlen - und genau dieser Fokus im Datumsfeld war die Ursache von #84.

**Merksatz:** Was nur vorgeschlagen ist, muss anders aussehen als das Gespeicherte - und wer einen Datensatz speichert, darf das sichtbare Feld daneben nicht stillschweigend liegen lassen.

## 87. Alt-Tag-Übertragung in einer Trefferliste: Ziel zeigt die alten Tags - und Auto-Save schreibt sie zurück

**Problem:** Beta-Test 28.10.2026: In einer Trefferliste Tag „Musterheim“ bei Dokument B gelöscht, dann A (mit „Musterheim“) per Alt auf B gezogen - B zeigt „Musterheim“ nicht, obwohl das Log „Tags übertragen“ meldet. Vorher schon: Übertragung „geht nicht“, wenn B alle Tags von A schon hatte (es kam keinerlei Rückmeldung).

**Ursache:** Nach dem Drop baute `on_folder_select(None)` die Liste neu - in einer Trefferliste passiert dabei nichts (Such-Schutzschild), die Zielzeile behielt die alten Tags. Schlimmer: `gui.on_file_select` füllte Titel- und Tags-Feld AUS DER LISTENZEILE, nicht aus dem PDF. Mit einer veralteten Zeile hätte die nächste Titel-Änderung per Auto-Save die alten Tags ins PDF zurückgeschrieben - die Übertragung wäre still verloren.

**Lösung:** (1) Der Drop zieht die Zielzeile direkt nach (`werte[2]`), `on_folder_select` nur noch außerhalb einer Suche. (2) `on_file_select` liest Titel/Tags aus dem PDF (`get_metadata`, ~0,2 ms; nur wenn das Lesen gelang - das Fehler-Dict hat kein „format“ - sonst wie bisher aus der Zeile). Nebenwirkung: das Tags-Feld zeigt die Reihenfolge im PDF statt der Häufigkeits-Sortierung der Liste. (3) Rückmeldung: Menüleiste nennt die neuen Tags (`file_operations.neue_tags`), hat das Ziel schon alle, kommt ein Hinweis und es wird nichts geschrieben.

**Merksatz:** Eine Listenzeile ist ein Anzeige-Cache - wer daraus ein Eingabefeld füllt, das per Auto-Save zurückgeschrieben wird, macht den Cache zur Quelle der Wahrheit.

## 88. Suche lief bei Pfeiltasten und nach Return doppelt - die Trefferliste flackerte beim Weiterklicken

**Problem:** Peter 01.11.2026 (Abnahme T7.28): Schon eine Cursortaste im Suchfeld startete die Suche; ein Klick auf ein Dokument kurz nach Return baute die Trefferliste sichtbar neu auf (Flackern, mit „Inhalt (OCR)“ besonders lästig). Beim Abtippen aus einem offenen Dokument lief die Suche ständig mit.

**Ursache:** Das Suchfeld hatte `<KeyRelease>` → `trigger_search` (Suche nach 0,4 s) - für JEDE losgelassene Taste, auch Pfeile, Pos1, Umschalt. Return suchte zusätzlich sofort (`suche_sofort`), und das Loslassen derselben Return-Taste stieß 0,4 s später die zweite, vollständige Suche an (gemessen: Suchen bei 0,0 und 0,66 s). Jeder Neuaufbau löschte alle Zeilen und legte sie neu an, auch bei identischen Treffern.

**Lösung:** (1) Gesucht wird nur noch mit Return/Enter in Such-, Von- und Bis-Feld (Peters Wahl); `<KeyRelease>` ruft `search_manager.feld_geleert` - ein Feld, das in der angezeigten Suche gefüllt war und jetzt leer ist, setzt sofort zurück. Klicks (Haken „Inhalt (OCR)“, Filter-Tags, übernommener Tag-Vorschlag) suchen weiter über `trigger_search`. (2) Weil im Feld jetzt Text stehen kann, der nicht gesucht wurde, fragt `is_search_active()` nach der ANGEZEIGTEN Suche (`_angezeigt`, gesetzt in `_apply_filters`), nicht mehr nach dem Feldinhalt (`filter_eingegeben()`) - sonst hätte der Watchdog beim nächsten Speichern die halbfertige Eingabe ungefragt gesucht, und ein Ordner-Klick hätte sie gelöscht; auch die Vorschau markiert nur abgeschickte Begriffe. (3) `_apply_filters` stellt die Zeilen erst unsichtbar zusammen (`_trefferzeilen`) und zeichnet nur neu, wenn sie sich von den angezeigten unterscheiden (`_angezeigte_zeilen`: Tk liefert Zahlen-Texte als int und ein einzelnes Tag als String zurück - vor dem Vergleich normalisieren).

**Merksatz:** Ein Tasten-Ereignis ist kein Text-Ereignis - und wer neben „sofort“ noch „verzögert“ auslöst, sucht doppelt. Ändert sich, WANN etwas ausgelöst wird, müssen alle Stellen, die „läuft es gerade?“ fragen, auf den ausgeführten Zustand umgestellt werden, nicht auf den eingegebenen.

## 89. Großer Ordner öffnet langsam - die Fortschrittsanzeige kostete mehr als das Lesen

**Problem:** Spike S4 (01.11.2026): Der Posteingang mit 5.000 Mail-PDFs brauchte 2,3 s zum Öffnen, direkt nach dem Rechnerstart (Dateien nicht im Cache) über eine halbe Minute.

**Ursache:** (1) `on_folder_select` öffnete jedes PDF für Titel/Tags/Daten (`PDFHandler.get_metadata`, warm 0,6 s, kalt 35 s) - obwohl der Suchindex genau diese Werte schon frisch hatte. (2) Gemessen mit cProfile: die Aktivitätsanzeige meldete alle 5 Dateien den Zähler und rief `aktivitaet.atme()` (= `update_idletasks`, zeichnet das ganze Fenster) - 1.000 Mal, zusammen 0,8 s, also mehr als das Lesen selbst.

**Lösung:** `IndexManager.metadaten(pfade, melde)` liefert die Werte aus der `files`-Tabelle, solange Änderungsdatum und Größe passen (`_zeile_frisch`, dieselbe Regel wie der Abgleich der Suche); nur neue/veränderte PDFs werden gelesen und gleich vollständig nachgetragen (`_werte_aus_pdf` + `_UPSERT_FILES`, gemeinsam mit `_abgleich` - die Suche liest sie danach nicht noch einmal). `index_manager.metadaten_sicher` fällt ohne Index (Einstellung `use_index` aus, Fehler) auf `{}` zurück, die Ordnerliste liest dann wie früher selbst. Gemeldet wird nur noch beim tatsächlichen Nachlesen. Ergebnis 0,32 s statt 2,32 s; alt gegen neu auf KID-Test: 50 Ordner, 405 Zeilen, keine Abweichung.

**Merksatz:** Fortschritt nur melden, wo wirklich gewartet wird - jede Meldung zeichnet das Fenster neu. Und was der Index schon frisch weiß, nicht noch einmal aus der Datei lesen.

## 90. Vollautomatik-Statusfenster springt zur Maus, während man in einem anderen Programm arbeitet

**Problem:** Peter 02.11.2026: Läuft die Vollautomatik im Hintergrund und arbeitet man in einem anderen Fenster (anderer Monitor), wandert das Statusfenster immer wieder in die Nähe des Mauszeigers - also mitten in das andere Programm.

**Ursache:** Das Fenster wird NICHT neu angelegt (gleiche Objekt-ID, per Fernsteuerung gemessen), sondern wächst: beim ersten Dokument kommen Vorschaubild und Ergebniszeile dazu (`_passe_groesse_an`, Höhe 426 -> 456 -> 499). Beim Wachsen hält `UIUtils._begrenzt_auf_monitor` das Fenster auf dem Bildschirm - und zwar auf dem Monitor UNTER DEM MAUSZEIGER (`monitor_bounds_at(window.winfo_pointerx(), …)`). Steht die Maus auf dem anderen Monitor, „begrenzt“ die Funktion das Fenster dorthin: von +238+156 nach -2986-89.

**Lösung:** (1) `_begrenzt_auf_monitor(…, bezug=(x, y))`: Wer ein schon offenes Fenster nur vergrößert, gibt dessen eigenen Ort als Bezug - das Vollautomatik-Fenster bleibt so auf seinem Monitor (gemessen: bleibt bei +316+234, Maus bei -3096). (2) Peters allgemeiner Wunsch: `position_near_mouse(_auto)` fragt über `UIUtils._anker`, ob KID gerade das aktive Programm ist (`app_hat_fokus`: Vordergrundfenster gehört zu diesem Prozess); wenn nicht, öffnet ein neues Fenster mittig über dem KID-Hauptfenster statt am Mauszeiger (minimiertes Hauptfenster: weiter am Mauszeiger). Tests: `TestAnkerNachFokus`, `test_bezug_bestimmt_den_monitor_nicht_die_maus` (beide ohne die Regel rot gesehen).

**Nachtrag aus der Abnahme mit Peter (gleicher Abend):** (3) Das Statusfenster stand beim Öffnen NIE dort, wo es sollte: es war schon während des Aufbaus sichtbar (`update_idletasks` in `_passe_groesse_an`), Windows setzte es auf seine treppenartige Standardposition (+238+156, +264+182, …) und die anschließende Platzierung ging unter - jetzt `withdraw()` am Anfang, `deiconify()` nach dem Platzieren. (4) Vor dem ersten Zeichnen meldet Tk das Hauptfenster als „1x1“ (auch `geometry()`), seine „Mitte“ ist die obere linke Ecke - `synchronisiere` öffnet das Statusfenster erst, wenn das Hauptfenster sichtbar ist, `_anker` nimmt bei 1 Pixel Breite den Mauszeiger. (5) Bei MAXIMIERTEM Fenster liefert `geometry()` die Lage vor dem Maximieren (+358+260 statt +82+43) - Peter: „nicht mittig, aber ungefähr“; `_anker` nimmt `winfo_rootx/rooty/width/height`. (6) Beim Programmstart hat KID selbst den Fokus, die Maus ist aber noch im Programm, aus dem man gestartet hat - Fenster, die KID von sich aus öffnet (Statusfenster beim Start), gehen mit `ueber_kid=True` immer über das Hauptfenster.

**Merksatz:** „Am Mauszeiger“ heißt „da, wo der Nutzer hinschaut“ - das gilt nur, solange er in KID arbeitet. Ein Fenster, das schon steht, wird nie nach der Maus ausgerichtet. Ein neues Fenster erst unsichtbar aufbauen, dann platzieren, dann zeigen - und Fenstermaße erst glauben, wenn das Fenster gezeichnet ist (nicht `geometry()` bei maximiert).


## 91. Sammlungs-Wiki: Verbräuche zehnfach - und der Fix kam nicht auf den Seiten an

**Problem:** Peter 02.11.2026 beim Ansehen des KID-Test-Wikis: „Einige Werte stimmen offensichtlich nicht.“ Der Strom stand mit 14560 kWh statt 1456,0 kWh in der Zählertabelle, ohne Zeitraum als „?–?“. In den Fakten: 9 Zahlen vom Prüfer „korrigiert“, 7 davon falsch (1456,0 → 14560, 399,3000 → 3993000, 8.8 → 88).

**Ursache:** (1) `wiki_fakten.wert_wie_im_text` (aus dem Spike übernommen) liest eine KI-Zahl so, wie sie im Text steht - und behandelte jede Fundstelle, die nicht auf zwei oder drei Nachkommastellen endet, als ganze Zahl (Trenner raus). Gedacht für „KI schrieb 6830, im Text 68,30“; aber eine oder vier Nachkommastellen (Zählerstände, Arbeitspreise) sind genauso Nachkommastellen. Der Spike hat das nie gezeigt: verglichen wurde nur, ob er an 402 Dokumenten dieselben Fakten liefert, nicht ob die Zahlen stimmen. (2) Eine Regeländerung soll über `REGELN` alle gespeicherten Fakten ohne KI neu prüfen - das passierte aber nur in `FaktenSpeicher.fakten(kid_id, text)`, und das braucht den Text. Der Seitenbau nahm `alle()` = die gespeicherten Fakten, wie sie waren. Ein Fix in den Prüfregeln wäre also nie auf den Wiki-Seiten angekommen.

**Lösung:** (1) Die Fundstelle gilt, wie sie dasteht (`als_zahl(fund)`), REGELN = 2. (2) `alle()` meldet je Zeile, ob sie aus den aktuellen Regeln stammt; `seiten_aktualisieren(…, text_von=IndexManager.wiki_text)` prüft veraltete Zeilen vor dem Seitenbau neu (einmal, danach stimmt `regeln`). Nebenbei zeigt die Zählertabelle ohne belegten Zeitraum den Monat des Belegs statt „?–?“. Tests: `test_eine_oder_vier_nachkommastellen_bleiben_nachkommastellen`, `test_fakten_aus_alten_regeln_werden_vor_dem_seitenbau_neu_geprueft` (beide ohne Fix rot gesehen); an einer Kopie der KID-Test-Fakten: 12 von 12 neu geprüft, Strom 1456,0 kWh.

**Merksatz:** Ein „Korrigieren“ des KI-Werts braucht einen Test mit dem Fall, den es NICHT korrigieren darf. Und ein Mechanismus „bei neuer Regelversion neu prüfen“ muss an der Stelle sitzen, an der gelesen wird - sonst greift er nur, wo zufällig der Text vorliegt.

**Nachtrag (gleicher Abend, Peters Prüfung der Seiten):** (3) Ein Betrag „29.391,69 €“ stand in keinem Dokument - die Ordnerseite addierte alle Gesamt-/Beitragsbeträge je Jahr, und eine Mehrjahres-Übersicht hatte sieben davon (eine Rechnung hat genauso Netto, MwSt und Brutto als „gesamt“). Erster Versuch „je Dokument nur der höchste“ - Peter: „Der Wert ergibt keinen Sinn“, eine Summe über verschiedene Leistungen sagt nichts. Jetzt zeigt die Ordnerseite eine Belegtabelle (Datum, Wofür, Betrag, Dokument-ID; Positionen eingerückt, Rechnungsbetrag zuerst). Außerdem bleiben Dokumente in 0_Posteingang und 0_Unsicher draußen (`UNGEPRUEFTE_ORDNER`, Peter: „noch nicht geprüfte Dateien“) - ihre Fakten bleiben gemerkt und erscheinen nach dem Ablegen. (4) Gezählt wurde auf 2012, weil `Dok._datum` das von der KI gelesene Datum nahm, obwohl die Prüfung es als „datum nicht im Text“ markiert hatte - und weil das KI-Datum vor dem Datum aus KID ging, kam auch Peters Korrektur eines Belegdatums in KID nie im Wiki an. Jetzt: Datum aus KID (KID_DokumentenDatum) zuerst, das KI-Datum nur belegt. (5) Peter: „unbedingt die Dokument-ID unterbringen“ - jeder Wert trägt seine ID in eckigen Klammern (`Dok.id_ref`, ohne ID der Dateiname), in der HTML-Fassung kopiert ein Klick sie (`HTML_SKRIPT` getrennt von `HTML_KOPF`, weil der durch `.format()` läuft und die Klammern des Skripts zerlegen würde). (6) Eine Handwerkerrechnung schrieb Beträge mit Dezimalpunkt und teils drei Nachkommastellen (127.01, „27.000“) - `als_zahl` las „27.000“ deutsch als 27 Tausend. `punkt_ist_dezimal(text)`: mindestens zwei Zahlen mit Punkt und zwei Nachkommastellen (keine Datumsteile) und keine einzige deutsche Komma-Zahl - dann gilt im ganzen Dokument der Punkt als Dezimaltrenner (REGELN 3). Prozentwerte („19.00%“) erscheinen nicht als Betrag.

## 92. Wiki-Rückfrage „welche Fläche gilt?“ mit sieben Werten zwischen 13 und 413 m²

**Problem (KID-Test, 03.11.2026, Selbstprüfung vor T19.8):** Die Rückfrage zu „gesamt“ eines Hauses bot 13 / 50 / 194 / 220 / 400 / 411 / 413 m² zur Auswahl - und der siebte Knopf ragte aus dem Fenster.

**Ursache:** `_flaechen_je_teil` gruppierte nur nach dem Teil („gesamt“). Die KI liefert aber unter „gesamt“ Wohnfläche, Nutzfläche und „Fläche des Grund und Bodens“ - verschiedene Größen, die sich nie widersprechen -, dazu Einträge, die gar keine Flächen sind („13 m“ mit Einheit „m“, „5“ mit Einheit „Anzahl Wohnungen“). Die Knöpfe standen in einer einzigen `pack`-Reihe.

**Lösung:** Verglichen wird je Teil UND Art (`_flaechen_art`: Wohn-/Nutzfläche/Grundstück, sonst ohne Art), der Schlüssel trägt die Art mit („flaeche:objekt|gesamt, wohnfläche“; ohne Art wie bisher, gespeicherte Antworten bleiben gültig), und nur echte Flächenangaben zählen (`_ist_flaeche`: Einheit m²/m2/qm, ohne Einheit muss der Wert sie tragen oder die Art eine Fläche sein). Nebenbei: die Objektseite schrieb „413,00 m² m²“ (`_flaeche_text`). Die Antwortknöpfe brechen nach ihrer gemessenen Breite in Reihen um. KID-Test: aus der einen Frage mit 7 Werten wurden drei mit 4, 3 und 2 Werten. Tests: `test_flaeche_nur_gleiche_art_und_nur_m2`, `tests/test_wiki_rueckfragen.py` (beide vorher rot).

## 93. Wiki: Euro-Betrag und Abgasleitung als „Fläche“ - die Texterkennung hatte das m² verschluckt

**Problem (Peter, T19.10, 03.11.2026):** Auf der Objektseite standen „Wohnfläche 200,00 m2“ (Grundsteuer-Bescheid) und „13 m m²“ (Kaminkehrer-Rechnung); Flächen erschienen mal als „142,00“, mal als „142 m2“.

**Ursache:** Im Bescheid hatte die Texterkennung „400 m2“ zu „^00 m2“ gemacht - die KI nahm den Äquivalenzbetrag „200,00 €“ daneben und hängte „m2“ an. „13 m“ ist die Länge der Abgasleitung, die KI erfand die Einheit m². Die Prüfung ließ beides durch: Zahl und Zitatwörter stehen im Text (Beleg „verstreut“). Eine einfache Regel „Zahl muss vor m² stehen“ hätte aber echte Flächen verworfen: die Texterkennung schreibt das hochgestellte ² als „m^“, „m"“ oder lässt es weg („(411,00 m)“), und Mieterlisten haben die Einheit nur in der Spaltenüberschrift.

**Lösung:** `wiki_fakten.keine_flaeche` (REGELN 4): eine Fläche gilt nicht, wenn ihre Zahl im Text überall als Betrag steht (€/EUR); als Länge/Volumen (nacktes „m“, m³, auch im Zitat selbst: „65m“) nur, wenn das Zitat nicht von einer Fläche spricht; ganz ohne Flächenwort in Zitat und Dokument ebenfalls nicht. „m^“/„m"“/„m'“/„m*“ zählen als m². Gemessen auf KID-Test (55 belegte Flächen): erste Fassung verwarf 14, davon 6 echte Wohnflächen mit OCR-² - verfeinert: 7 verworfen, alle richtig (6 Längen, 1 Betrag). Die Seiten schreiben Flächen einheitlich („142 m²“, „107,5 m²“, `_flaeche_text`), zeigen die Art als Wohnfläche/Nutzfläche/Grundstück und den Prompt-Platzhalter „Wohnung/Raum/Haus oder gesamt“ als „(ohne Angabe)“. Falsch gelesene Art (194 m² Grund und Boden als „Nutzfläche“) bleibt - das kann nur eine Korrektur am Dokument beheben. **Messfalle:** Ein Vergleich „mit/ohne Regel“ über `_zuordnen` SPEICHERT die Neuprüfung mit der neuen REGELN-Nummer - der zweite Lauf sieht dann „aktuell“ und prüft nicht mehr; vorher die Spalte `regeln` zurücksetzen.

## 94. „Stimmt nicht“ und „Korrektur zurücknehmen“ reagierten nicht - der Korrektur-Schlüssel hatte sich geändert

**Problem (Peter, T19.12, 04.11.2026):** Im Werkzeug „Wiki: Was die KI gelesen hat“ änderte Peter bei einer „Betrag position“ (Zitat „Gasanschluss seit 1.2.2015“) den Wert auf „1.2.2015“ - danach taten „Stimmt nicht“ und „Korrektur zurücknehmen“ scheinbar nichts. Außerdem ließ sich bei Verträgen nichts korrigieren („Schreibfehler lassen sich nicht beheben“).

**Ursache:** Der Schlüssel einer Korrektur ist `fakt:<ID>|<Liste>|<Wert, wie die KI ihn las>` - gelesen aus `<feld>_ki`, sonst aus dem Feld. Die KI hatte den Betrag LEER geliefert; `korrigiere` merkte den leeren KI-Wert als `betrag_ki = ""`, und `fakt_schluessel` nahm `e.get("betrag_ki") or e.get("betrag")` - der leere String ist falsy, also galt der NEUE Wert: anderer Schlüssel, die Buttons griffen ins Leere. Verträge haben in `wiki_fakten.HAUPTFELD` keinen Hauptwert; „Wert ändern“ schrieb in ein Feld `was`, das nirgends angezeigt wird.

**Lösung:** `fakt_schluessel` fragt, ob `<feld>_ki` VORHANDEN ist (nicht, ob es wahr ist); ohne Wert steht das Zitat für den Eintrag (`~gasanschluss seit 1.2.2015`). `wiki_wissen.korrekturfeld`: Verträge korrigieren die Vertragsnummer. Test `TestKorrekturOhneWert` (vorher rot). Merksatz: bei „schon da?“-Fragen an Dicts `in` statt Wahrheitswert - leer ist auch ein Wert.

## 95. Tk und Threads in Tests: root.after aus dem Thread verpufft, Tk-Objekte sterben im falschen Thread

**Problem (04.11.2026, Prüfplatz `tools/begleitet_erfassen.py`):** (1) Der Fenstertest wartete endlos auf den ersten Vorschlag, obwohl der Leser-Thread längst gelesen hatte. (2) Nach weiteren Fenstertests brach die ganze Suite in einem ALTEN Test (`test_fehlerfaenger`, Fehler im Thread) mit „Tcl_AsyncDelete: async handler deleted by the wrong thread“ ab.

**Ursache:** (1) `root.after(...)` aus einem fremden Thread funktioniert nur, solange Tk in der `mainloop` steht - der Test ruft nur `update()`, dann wirft es RuntimeError, und mein `except` schluckte das still. (2) Ein Tk-Hauptfenster aus einem früheren Test hing noch in einem Referenzzyklus (Fenster-Registrierung `UIUtils.einzelfenster`, Thread-Closures); der Garbage Collector lief zufällig im Thread des Fehlerfänger-Tests und gab den Tcl-Interpreter dort frei.

**Lösung:** (1) Threads melden über ein Postfach (`queue.Queue`), das das Fenster alle 100 ms im Tk-Thread leert (`_nach_tk`/`_abholen`; beim Schließen `after_cancel`, sonst „invalid command name …_abholen“) - kein Tk-Aufruf aus dem Thread, gleich in App und Test. (2) Fenstertests räumen im Haupt-Thread auf (`threads_beenden`: Daemon-Threads abwarten, `UIUtils._einzelfenster` leeren, `gc.collect()` - vor UND nach `root.destroy`). Werkzeugfenster sind jetzt `transient` zum Hauptfenster (`UIUtils.werkzeugfenster`) - in Tests mit verstecktem Hauptfenster bleiben sie damit unsichtbar (Layout-Tests patchen das weg).

## 96. Wiki: zwei ähnlich geschriebene Straßen wurden still ein Objekt

**Problem (Befund 03.11.2026, behoben 04.11.2026):** „Bergstr 3“ und „Burgstr 3“ landeten im Wiki ohne Rückfrage auf EINER Objektseite - Flächen, Verträge und Personen zweier Häuser mischten sich.

**Ursache:** `wiki_seiten.objekt_kanon` führt Schreibweisen über `_passt` zusammen, und `_passt` lässt je Straßenwort eine Lesefehler-Toleranz von 0,8 zu (nötig für „weilenstr“ ~ „weidenstr“, Lauf 02.11.). „bergstr“/„burgstr“ liegen mit 0,86 darüber - ein Lesefehler und eine zweite Straße sehen für einen Ähnlichkeitswert gleich aus. Die Rückfrage „dasselbe Objekt?“ (`rueckfragen` Punkt 2) kam nie dran, weil es nach dem Zusammenführen nur noch ein Objekt gab.

**Lösung:** `_still_zuordnen`: mit gleichen Wörtern wie bisher; NUR über die Toleranz bloß, wenn die Schreibweise ein seltener Ausreißer ist - kein eigener Objekt-Tag und höchstens 2 Nennungen bzw. ein Fünftel der Zielschreibweise. Sonst bleiben beide stehen und die Rückfrage entscheidet. Gegenprobe: KID-Test und Betatest-Korpus (402 Dokumente) unverändert 8 Objekte, keine zusätzliche Rückfrage. Tests `test_aehnliche_strassen_nur_mit_rueckfrage`, `test_aehnliche_objekt_tags_nie_still_zusammen` (ohne Fix rot), `test_seltener_ocr_fehler_wird_still_zugeordnet`.

## 97. Mail-Import: „Grüße“ wurde „Gr??e“ - decode_header bekam einen String statt des Header-Objekts

**Problem (04.11.2026, `mail_lesen._kopf`):** Alte Mails mit ungeschützten 8-Bit-Umlauten im Kopf (Outlook der 2000er) zeigten „Gr??e“ statt „Grüße“, obwohl die Reparatur aus Spike S1 übernommen war.

**Ursache:** `policy.default` macht aus den Bytes U+FFFD; deshalb liest `_kopf` die Zeile ein zweites Mal aus einem `compat32`-Parser. Der liefert dafür ein `email.header.Header`-OBJEKT. `str(header)` wirft die Bytes ebenfalls schon weg (wieder U+FFFD) - nur `decode_header(header)` gibt sie als `(bytes, "unknown-8bit")` heraus, die dann als cp1252 gedeutet werden. Beim Übernehmen aus dem Spike war ein harmlos aussehendes `str(...)` dazugekommen.

**Lösung:** `decode_header(roh)` mit dem Objekt selbst (Kommentar an der Stelle). Test `test_8bit_kopf_als_cp1252` (war mit `str(roh)` rot).

## 98. Ordnersuche wurde ab ~500 Ordnern zehnmal langsamer - re vergisst seine Muster

**Problem (04.11.2026, Messung Mail-Import mit 20.000 Mails):** Das erste Entscheiden über 2.000 Gegenüber brauchte 46 s; fast alles davon in `auto_pilot.finde_passenden_ordner` (72 ms je Aufruf bei 600 Ordnern).

**Ursache:** `_namen_passen` baute je Ordner ein Muster `re.search(r"(?<![\w])" + re.escape(kern) + …)`. `re` merkt sich übersetzte Muster, aber nur 512 Stück - bei 600 Ordnern fliegt jedes Muster wieder heraus, bevor es noch einmal gebraucht wird, und wird bei jedem Aufruf neu übersetzt. Mit KID-Test (wenige Dutzend Ordner) fällt das nie auf.

**Lösung:** `_ganzes_wort(kern)` mit eigenem `functools.lru_cache(8192)`: 7 ms je Aufruf, Ergebnis identisch (alle Vollautomatik-Tests unverändert). Gilt für jede Stelle, die Muster aus Ordner- oder Absendernamen zusammensetzt.

## 99. Monatliche Mails als „vermutlich Dublette“ in 0_Unsicher - zwei Dublettenprüfungen wussten nichts voneinander

**Problem (04.11.2026, T20.3):** 12 von 28 importierten Mails landeten in 0_Unsicher: „Text zu 95 % gleich (anderes Datum); KI-Zweitprüfung sagt ‚ja‘“ - obwohl sie verschiedene Message-IDs und Daten hatten (dieselbe Rechnungsvorlage in verschiedenen Monaten).

**Ursache:** Die Dublettenprüfung vor der Ablage (`dubletten_pruefung`) ist für Scans gebaut: dort ist fast gleicher Text mit anderem Datum oft eine falsch datierte Kopie. Bei Mails hat aber schon der Import über Message-ID bzw. Fingerabdruck entschieden, und das Datum aus dem Mailkopf ist sicher. Auch die KI-Zweitprüfung half nicht: Sie sieht dieselbe Vertragsnummer und denselben Betrag und sagt „ja“.

**Lösung:** `_zwei_verschiedene_mails`: zwei Mail-PDFs (beide mit `KID_RICHTUNG`) mit verschiedener `KID_MAILID` werden nicht verglichen. Mail gegen Scan und Anhänge (ohne `KID_RICHTUNG`) schon: dieselbe Rechnung zweimal IST eine Dublette. Danach 27 von 27 abgelegt. Testtexte müssen lang genug sein (`MIN_WOERTER`, 92 % bei anderem Datum) - mit kurzem Text war der Test auch ohne Fix grün.

## 100. Mail-Import: echte .pst-Mails „unlesbar“ - EmailMessage nimmt keinen zweiten Betreff und keine Zeilenumbrüche

**Problem (04.11.2026, T20.4):** Von 238 Mails einer echten .pst zählte der Import 6 als „unlesbar“, 2 von 2618 in einer zweiten. Die Mails waren in Ordnung, tauchten aber in keiner Liste auf und ließen sich nicht retten. Mit den synthetischen Mails und den öffentlichen Testdateien kam das nie vor. Peters Zählskript (`KID-Messungen/mail_testdateien/unlesbar_zaehlen.py`, nur Fehlerart und Code-Stelle) zeigte: alle 6 `ValueError` in `baue_eml` beim Setzen des Betreffs.

**Ursache:** `if not msg["Subject"]: msg["Subject"] = …` - eine LEERE Zeile aus den gespeicherten Kopfzeilen gilt als „kein Betreff“, sie existiert aber, und `EmailMessage` erlaubt von Subject, To, From, Date und Message-ID nur eine (`There may be at most 1 …`). Dazu lehnt es Zeilenumbrüche im Wert ab, die Werte aus den MAPI-Eigenschaften enthalten können. Welcher der beiden Fälle die echten Mails traf, ist offen, der Test deckt beide ab.

**Lösung:** `mail_pst._setze_kopf`: vorhandene Zeile entfernen, Steuerzeichen durch Leerzeichen ersetzen, setzen. `baue_eml` fängt den Fehler weiter außen ab und zählt ihn nur - eine Zahl „unlesbar“ an echten Daten lohnt sich also immer nachzusehen.

## 101. Mail-Import: Bestellbestätigungen und Kündigungs-Antworten fielen ohne KI heraus - ein Kopf sagt nichts über den Inhalt

**Problem (05.11.2026, T20.4):** In einer echten Jahres-.pst sortierte der Vorfilter 34 % aller Mails ohne KI aus. Dabei waren Bestellbestätigungen und AGB-Änderungen (Grund „Newsletter (List-Unsubscribe)“) und die Antwort eines Ticket-Systems auf eine Kündigung („automatische Antwort“). Die Stichprobe „von der KI verworfen“ konnte das nicht zeigen, sie sah nur die Zeilen mit „KI:“. Daneben nannte die KI Vertragsänderungen, zugeteilte Inhalte und bestätigte An-/Abmeldungen „werbung“.

**Ursache:** Der Vorfilter schloss aus einem Kopf auf den Inhalt. Versanddienste setzen `List-Unsubscribe` und Ticket-Systeme `Auto-Submitted` auf alles, was sie verschicken. Für No-Reply-Absender stand dieselbe Regel schon im Konzept, für diese beiden Köpfe nicht. Die Klassen im Prompt kannten nur Rechnung und Vertrag, nicht deren Änderung.

**Lösung:** Der Vorfilter nimmt nur noch Spam-/Papierkorb-Ordner und Lesebestätigungen, alles andere urteilt die KI am Text (bei höchstens 0,6 s je Mail tragbar: rund 6.500 Mails mehr im Gesamtbestand = etwa eine Stunde). Prompt erweitert; `mail_import.KI_STAND` macht gespeicherte Urteile nach einer Prompt-Änderung ungültig, Entscheidungen von Hand bleiben. Erfundene Mails derselben Arten: vorher 19, nachher 22 von 22 mit richtigem Ergebnis - das misst nur, ob die Regel greift; ob sie an echten Mails trägt, zeigt erst Peters Stichprobe.

**Nachtrag 08.11.2026:** Die KI-Einstufung der Mails ist mit dem Mail-Import auf Abruf entfallen (KONZEPT_MAIL_AUF_ABRUF, Bauschritt 4): Der Mensch sucht und hakt an. Die Lehre bleibt: Der Vorfilter (`mail_lesen.vorfilter`) nimmt nur Spam-/Papierkorb-Ordner, Entwürfe und Lesebestätigungen und blendet sie seitdem nur aus (Haken „auch Spam, Papierkorb und Entwürfe“).

## 102. Start fehlgeschlagen: „Permission denied“ auf `C:\Windows\System32\dokumenten_manager.log`

**Problem (05.11.2026):** Die Test-EXE startete nicht und meldete einen `PermissionError` auf das Protokoll in `System32`. Sie lag dabei ordentlich in ihrem Ordner, neben ihrer `settings.json`.

**Ursache:** `settings.json`, die Vorlagen und das Protokoll ohne Sammlung werden relativ zum Arbeitsverzeichnis gesucht. Das legt aber der Startweg fest, nicht der Ort der EXE: Der Doppelklick im Explorer nimmt den Ordner der Datei, der Start über die Windows-Suche lief hier mit `System32`. Dort fand die App keine Einstellungen, hielt sich für unkonfiguriert, und das Protokoll landete im Rückfall auf `System32`. Erst dieser Schreibversuch fiel auf. Mit Administratorrechten wäre er gelungen, und die App hätte ihre Dateien still in `System32` abgelegt.

**Lösung:** `main.main()` wechselt vor dem Aufbau des Hauptfensters per `os.chdir(app_paths.app_dir())` in den Programmordner. `fernsteuerung.py` und `messlauf.py` rufen `main()` nicht auf und behalten ihren eigenen Arbeitsordner. Nachgestellt mit Wegwerf-Sammlung und `Start-Process -WorkingDirectory C:\Windows\System32`: neu7 scheitert, neu8 startet und schreibt ins Protokoll der Sammlung.

**Grenze:** Ein schreibgeschützter Programmordner (etwa `C:\Program Files`) bleibt ungelöst. Ohne Sammlung scheitert dort weiter das Protokoll, und `Config.save` schluckt den Fehler beim Speichern der Einstellungen. Siehe FAHRPLAN, Zurückgestellt.

## 103. Mail-Import stand bei „1 von 74“: Eine Tabellenzeile, die höher als eine Seite ist, verlangt endlos neue Seiten

**Problem (05.11.2026, echter Durchlauf):** Der Import echter Mails kam über die erste Mail nicht hinaus, bei voller Last auf einem CPU-Kern. „Abbrechen“ half nicht, es wirkt erst zwischen zwei Mails.

**Ursache:** `fitz.Story` kann eine Tabellenzeile nicht über Seiten teilen. Passt sie auf keine Seite, liefert `place()` immer wieder „es kommt noch mehr“, und die Schleife in `schreibe_mail_pdf` hatte keine Obergrenze. Das ist kein Sonderfall: Newsletter und Bestellbestätigungen stecken ihren ganzen Inhalt oft in eine äußere Layout-Tabelle, jede solche Mail über eine Seite Länge läuft hinein. Mit erfundenem HTML reichen dafür schon rund zwei Seiten Text in einer Zelle. Dasselbe passiert bei riesiger Schrift oder riesigem Polster. Die Unit-Tests sahen das nicht, weil ihre Testmails kurz waren.

**Lösung:** Nach `MAX_MAIL_SEITEN` (300) wirft `schreibe_mail_pdf` die Ausnahme `MailZuLang`, und `_importiere` legt die Mail über `seite_html(…, nur_text=True)` als reinen Text ab, mit Hinweis im PDF und eingebetteter Original-Mail. Das Fenster nennt die Zahl („vereinfacht“). Echter Lauf danach: 74 Mails in wenigen Sekunden, 26 davon als Text.

**Nachtrag (Darstellungsstufen):** 26 von 74 als reiner Text waren zu viele. `_schreibe_in_passender_stufe` versucht jetzt der Reihe nach `VOLL`, `OHNE_LAYOUT` (Tabellen mit einer Tabelle darin werden zu Blöcken, innere Datentabellen bleiben), `OHNE_TABELLEN` und erst zuletzt `NUR_TEXT`. Ab der zweiten Stufe steht ein Hinweis im PDF. Beim Auflösen fallen feste Größen weg, Farben bleiben, weil weiße Schrift sonst unlesbar würde. Das Ergebnis mit echten Mails steht noch aus.

**Daneben gefunden:** Ein Block mit Hintergrundfarbe UND Polster wird von MuPDF oben auf jede Folgeseite gemalt, als farbiger Balken über dem Text. Echte Tabellenzellen betrifft das nicht. `_ohne_polster_bei_farbe` nimmt bei solchen Blöcken das Polster weg, für Stile am Element. Über Klassen gesetzte Stile aus dem `<style>`-Block der Mail bleiben davon unberührt.

**Lehre:** Bei Schleifen um Bibliotheksaufrufe, die „mach weiter“ melden, immer eine Grenze setzen. Und ein Testlauf mit echten Daten findet, was kurze erfundene Mails nie zeigen: Diese Stelle lief seit dem 04.11. fehlerfrei durch alle Tests.

## 104. Papierkorb: Die zweite gleichnamige Datei überschrieb die erste still

**Problem (05.11.2026, beim Bau des nachträglichen Verwerfens gefunden):** Wer nacheinander zwei Dateien gleichen Namens aus verschiedenen Ordnern löschte, hatte danach nur noch die zweite im Papierkorb. Die erste war ohne Meldung verloren, obwohl der Papierkorb genau davor schützen soll.

**Ursache:** `delete_file` zielte auf `Papierkorb/<Dateiname>`. `shutil.move` ersetzt eine vorhandene Zieldatei: Unter Windows scheitert zwar `os.rename`, der eingebaute Rückfall aufs Kopieren überschreibt dann aber. Auch `papierkorb_herkunft` kennt nur den Dateinamen, die alte Herkunft ging also mit verloren.

**Lösung:** `_freier_papierkorb_pfad` hängt „ (2)“ an, solange der Name belegt ist. Der Weg gilt für `delete_file` und das neue `in_papierkorb`. Test mit zwei gleichnamigen Dateien, vor dem Fix rot.

**Lehre:** `shutil.move` auf eine vorhandene Datei ist kein Fehlerfall, sondern ein Überschreiben. Wer verschiebt, prüft das Ziel selbst.

## 105. mbox: Eine Zeile „From …“ im Mailtext zerlegte die Mail

**Problem:** Beim Einlesen einer mbox wurde aus einer Mail mit der Zeile „From Hamburg nach Berlin“ im Text zwei Mails, die zweite ohne Kopf (Spike S5: 6 statt 5).

**Ursache:** `mailbox.mbox` der Standardbibliothek nimmt jede Zeile, die mit `From ` beginnt, als Trennzeile. Eigentlich maskieren Programme solche Zeilen im Text (`>From`), ob Thunderbird das immer tut, ist nicht geklärt. Thunderbird selbst prüft die Form der Zeile.

**Lösung:** `mail_lesen.mbox_mails` liest zeilenweise (Thunderbird-Dateien können viele GB groß sein) und trennt nur an Zeilen mit Wochentag, Tag und Monat und Uhrzeit. Die Regel ist bewusst großzügig: Eine zu strenge würde Mails verschmelzen, was schlimmer wäre als eine zerlegte. Deshalb zählt der Lauf „From“-Zeilen im Text und zeigt die Zahl an: Viele davon bei wenigen Mails hießen, dass die Datei eine unbekannte Trennzeile benutzt.

**Grenze:** Gegen einen echten Thunderbird ist das noch nicht geprüft, das Testprofil ist nach der Dokumentation gebaut.

## 106. Dokumentenliste wurde beim Durchklicken nach jedem Klick neu aufgebaut

**Problem:** Peter 05.11.2026: Beim Durchklicken der Dokumente baute sich die Liste nach jedem Klick neu auf, 0,5 s später. Beim zweiten Durchgang durch dieselben Dokumente passierte nichts.

**Ursache:** Windows aktualisiert beim Lesen einer Datei die Zugriffszeit (bei `DisableLastAccess = 2` höchstens einmal je Stunde), und der Watchdog meldet das als „Datei geändert“. Gemessen in KID-Test: 8 von 8 ersten Klicks ergaben ein `modified` auf ein PDF, dessen Änderungszeit 8 Tage zurücklag, danach `sync_ui` mit Neuaufbau von Ordnerbaum und Liste. Das war seit #34 bekannt („nach jedem Klick auf eine Datei“), dort wurde aber nur der Aufklapp-Zustand gerettet; #68 filterte nur das Ordner-Ereignis, #88 betraf die Suche. Geschrieben hat KID dabei nichts, die Vermutung `kennung_beim_anklicken` traf nicht zu, denn die Dokumente hatten ihre ID schon.

**Lösung:** `folder_monitor.ist_nur_zugriff`: Ein `modified` auf eine Datei, deren Änderungszeit älter als 60 s ist, wird nicht weitergegeben. Eine echte Änderung setzt die Änderungszeit auf jetzt; neu, verschoben und gelöscht sind andere Ereignisarten und zählen immer. 60 s lassen Spielraum für die Uhr eines Netzlaufwerks. Lässt sich die Datei nicht prüfen, gilt das Ereignis. Gegenprobe im echten Programm: 8 Klicks mit erneuerter Zugriffszeit, kein Neuaufbau, eine echte Änderung löst ihn weiter aus.

**Grenze:** Geht eine Uhr eines Netzlaufwerks mehr als 60 s nach, bemerkt KID eine dortige Änderung erst beim nächsten Neulesen.

## 107. Mails ohne Absendernamen: Das Funktionswort der Adresse machte fremde Ordner „ähnlich“

**Problem:** Peter 06.11.2026, nach erneutem Ablegen aller Dokumente aus `0_Unsicher`: Die zwei verbliebenen unsicheren Mails hatten nur eine Adresse im Kopf. Nachgestellt: `service@beispielware.info` fragte nach dem Ordner „MUSTERMARKT Service“, `online@mustermarkt.de` nach „DISKONT ONLINESHOP“, obwohl „MUSTERMARKT Service“ daneben lag.

**Ursache:** `baue_entscheidung` verglich die ganze Adresse als Namen. `_namenswoerter` zerlegt sie in Wörter, also zählten auch „service“ und „online“. „online“ ist der Wortanfang von „onlineshop“ (Güte 2), und weil „DISKONT“ fehlte, passte dort 1 von 1 Wort, beim richtigen Ordner nur 1 von 2. Der Domainname allein kam gar nicht vor: „mustermarkt.de“ passt nicht auf den Anfang von „mustermarkt service“. Die Endung wirkte genauso (`.online`).

**Lösung:** `_vergleichsname`: Eine bloße Adresse wird mit vorhandenen Ordnern nur über den Domainnamen verglichen (`online@mail.firma.de` -> `firma`). Damit findet die Domain den Ordner des Absenders auch ohne Rückfrage. Ordnername, Alias und Ablage-Gedächtnis bleiben wie gehabt. Bei Mail-Anbietern bleibt die ganze Adresse, dort steht vorn oft der Name der Person. Betatest-Korpus: Keiner der 403 Absender ist eine bloße Adresse, dort ändert sich nichts.

**Grenze:** Eine Domain, deren Name zugleich ein vorhandener Ordnername ist, wird ohne Rückfrage dort abgelegt, auch wenn es eine andere Firma gleichen Namens ist. Das gilt für Absendernamen schon immer.

## 108. Mail-PDF verlor den ganzen Text, ohne dass ein Fehler kam

**Problem:** Peter 06.11.2026: Ein Newsletter erschien als PDF nur mit Kopfzeilen und einer dunklen Fläche. Rund 370 Wörter Text fehlten auf den Seiten, im PDF standen nur die 21 Wörter des Kopfes. Die eingebettete Original-Mail war vollständig. Damit fehlte der Text auch für Suche, Wiki und das Lesen durch die KI. Gezählt mit `KID-Messungen/mail_textverlust_zaehlen.py` (nur Zahlen): 117 von 394 echten Mail-PDFs zeigten in voller Darstellung weniger als die Hälfte ihres sichtbaren Textes, 72 davon unter 25 %.

**Ursache:** Zwei getrennte Fälle.
1. Eine Tabellenzeile, die höher ist als eine Seite (siehe #103), kombiniert mit `table,td{border-collapse:collapse}` in den Stilen der Mail. Mit dieser Regel verlangt die Story nicht endlos neue Seiten, sondern endet nach 2 Seiten ohne Fehler, zeichnet aber nur den Hintergrund. Die Regel ist in Newslettern alltäglich. Der Schutz aus #103 erkannte nur die endlose Variante. Eingegrenzt per Weglassen aller 41 Stilregeln der Mail; nachgestellt mit erfundenem HTML in `test_layout_tabelle_mit_collapse_verliert_keinen_text`.
2. Ein Nullzeichen im Mailkopf (1 von 394): Die Story liest das HTML nur bis dorthin, in jeder Stufe, auch als reiner Text.

**Lösung:**
- `schreibe_mail_pdf(mindest_zeichen=…)`: Stehen weniger Buchstaben und Ziffern auf den Seiten als verlangt, gilt die Darstellung als gescheitert und `_schreibe_in_passender_stufe` nimmt die nächste. Verlangt werden 70 % von `mail_lesen.sichtbare_zeichen`.
- Der erste Versuch verglich Wörter und verlangte die Hälfte. Das schickte 57 Mails bis zum reinen Text, weil Füllzeichen im Vorspann und versteckte Blöcke als Text zählten. Darum zählen jetzt nur Buchstaben und Ziffern, ohne `display:none`, `max-height:0` und `mso-hide:all`.
- `seite_html` entfernt Steuerzeichen.
- Ergebnis an den 394 Mails, nachgerechnet im Temp-Ordner: 375 ab 90 % ihres Textes, 18 bei 75-90 %, 1 bei 50-75 %, keine darunter. Darstellung: 179 voll, 199 vereinfacht, 16 reiner Text. Mit 50 % statt 70 % blieben 51 Mails unter 75 %.

**Grenze:** Vor dem Fix erzeugte PDFs bleiben, wie sie sind; das Journal führt die Mails als importiert. Wer mit Klassen versteckt (`.mobil{display:none}`), zählt weiter als sichtbar, solche Mails werden im Zweifel unnötig vereinfacht. Vereinfachte Mails verlieren ihr Layout: Die Hälfte der Mails trägt jetzt den Hinweis „Vereinfachte Darstellung“. Ein besseres Layout wäre nur mit einem anderen Erzeuger möglich, siehe FAHRPLAN, Edge.

## 109. Standardaufteilung schnitt die Suchleiste ab, bei großer Schrift verschwand die Vorschau fast

**Problem:** Release-Check v0.9.24, T0.16 und T0.10. Nach „Fensteraufteilung zurücksetzen“ ragten bei normaler Schrift im Fenster 1400×900 „Reset“ 98 Pixel und die Trefferzahl 181 Pixel über den Rand, auch maximiert. Beim Erststart mit simulierten 125 % blieben der Vorschau 23 Pixel.

**Ursache:** Es gibt zwei Wege zur Aufteilung. `standard_sashes` rechnete die Mitte fest mit 440 Pixeln, die Suchleiste braucht aber 698 (bei großer Schrift 979), und das „Maximieren“ gibt nur der Vorschau mehr Platz (`weight=1`). Ohne gespeicherte Werte ergibt sich die Aufteilung dagegen aus den Wunschbreiten: bei normaler Schrift passend, bei großer Schrift nimmt die Mitte fast alles. Die Trefferzahl (v0.9.24) hat das um rund 150 Pixel verschärft. Der Prüfhelfer aus T0.16 sah nichts, weil er Knöpfe mit ihrer eigenen Breite vergleicht: Was die Trennlinie abdeckt, gilt als sichtbar. Peter fiel es nicht auf, weil seine gespeicherte Aufteilung breit ist.

**Lösung:** `standard_sashes(breite, mitte)` nimmt den Platzbedarf der Suchleiste, höchstens so viel, dass der Vorschau 30 % bleiben. `_vorschau_freihalten` korrigiert beim Erststart ohne gespeicherte Werte eine Vorschau unter 10 % der Breite (`vorschau_zu_schmal`). Gemessen: 100 % nach Zurücksetzen alles sichtbar, Vorschau 408 Pixel; simuliert 125 % beim Erststart Vorschau 408 statt 23 Pixel.

**Grenze:** Bei simulierten 125 % im 1400er-Fenster ragen Reset und Trefferzahl weiter über den Rand, bis man die Spalte aufzieht; die Vorschau ging vor. Gespeicherte Aufteilungen bleiben unverändert. Beim Prüfen der Oberfläche auch messen, ob die Bedienelemente innerhalb ihrer Spalte liegen, nicht nur, ob sie ihre Wunschbreite haben.

## 110. Mail-PDF: Newsletter mit überlappenden Texten, schmalen Spalten und Kopf in Standardschrift

**Problem:** Peter 06.11.2026: Ein Newsletter „sieht komisch aus“. Der Text war vollständig, aber 5 Seiten lang, die Spalten nur wenige Wörter breit, Texte überlagert, große dunkle Flächen, 55-mal „[Bild nicht geladen]“. Betreff und Kopfzeilen standen in Serifenschrift und nicht fett.

**Ursache:**
1. Ein nie geschlossener Block in den Stilen der Mail (`@keyframes x { from {…} to {…}` ohne letzte Klammer). `user_css` ist ein einziger Text, die Regeln von `mail_lesen.CSS` stehen dahinter und landen in diesem Block. Ein offener Kommentar wirkt genauso. Einzelne ungültige Regeln wie `.&.yahoo_hide {…}` überspringt der Parser dagegen sauber. Ein `mupdf_warnings()`-Hinweis ist das einzige Zeichen, die Story arbeitet ohne Fehler weiter.
2. Der Platzhalter „[Bild nicht geladen]“ ersetzte auch 20 Pixel kleine Abstandsbilder. In einer Layout-Zelle mit fester Breite und Höhe sprengt der lange Text die Spalte und läuft über die Nachbarn. Zugleich zählte er für `sichtbare_zeichen`: 880 von 2142 Zeichen waren Platzhalter, die Prüfung auf Textverlust (#108) maß also auch sie.

**Lösung:**
- `_nur_ganze_regeln` in `bereinige_html` lässt nur vollständige Regeln durch, ohne Kommentare und fremde Klammern. Was nach einem offenen Block kommt, fällt weg; das ging auch vorher verloren.
- `_Bereiniger` zählt die offenen Tabellen, in Tabellen gibt es keinen Platzhalter mehr. Die Zahl der Bilder steht im Hinweis oben. Außerhalb von Tabellen bleibt er, dort zeigt er, wo in einer normalen Mail ein Bild stand.
- Ergebnis an dieser Mail: voll 3 statt 5 Seiten, 1258 von 1262 Zeichen; vereinfacht 2 statt 3 Seiten, 1314 von 1318 Zeichen (vorher 1970 von 2198).

**Grenze:** Vor dem Fix erzeugte PDFs bleiben, wie sie sind. In voller Darstellung bleiben einzelne Spalten dieser Mail zu schmal, die vereinfachte Darstellung wäre hier schöner; ob eine Mail, die vereinfacht weniger Seiten braucht, so erscheinen soll, ist offen (FAHRPLAN, Zurückgestellt) und müsste an echten Mails gezählt werden. Der Fix selbst ist an erfundenem HTML getestet und an dieser einen Mail nachgerechnet, noch nicht an den 394 aus #108.

## 111. Dokumentenliste leer, unten standen noch Dateiname, Ordner und „Original-Mail öffnen“

**Problem:** Peter 06.11.2026, Screenshot aus dem Betatest: Die Vollautomatik hatte den Posteingang geleert. Liste und Vorschau waren leer, Titel und Tags auch, die Eigenschaften zeigten weiter das zuletzt gewählte Dokument samt Link zur Mail.

**Ursache:** `on_folder_select` räumte im Zweig „Ordner ohne Dokumente“ Vorschau, Titel und Tags einzeln ab. Die Eigenschaften-Tabelle kam später dazu (14.09.2026), und dieser Zweig wurde nicht ergänzt. `gui.leere_dokumentanzeige` kann alles, wird dort aber nicht benutzt.

**Lösung:** Der Zweig ruft `leere_dokumentanzeige`. Wer etwas zur Anzeige eines Dokuments ergänzt, trägt es dort ein, es gibt nur diese eine Stelle zum Leeren.

## 112. Menüleiste sagte nur „KI antwortet“, nicht woran

**Problem:** Peter 06.11.2026: „Außerdem arbeitet die KI im Hintergrund, ohne dass ich weiß, was sie macht.“ Bei leerem Posteingang stand „KI antwortet“ in der Leiste, ohne Hinweis worauf.

**Ursache:** Zwei Dinge. Die Anzeige zeigt immer die zuletzt begonnene Phase, und `_generate` beginnt seine eigene: Der genaue Text der Vollautomatik („liest: Name“) war darum fast nie zu sehen. Und der Wiki-Leser arbeitet ohne Fenster und meldete gar keine Phase, nach einem Massenimport hat er über Stunden zu tun.

**Lösung:** `aktivitaet.phase(text, nebensache=True)`: Die KI-Anfrage ist ein Hilfsschritt und steht nur noch als Dauer hinter der Aufgabe, „Vollautomatik liest 3 von 120: Name… (KI 4 s)“. Der Wiki-Leser meldet „Wiki liest Fakten, noch 812: Name…“, der Mail-Import seine KI-Einstufung. Allein ohne Aufgabe steht weiter „KI antwortet“.

**Grenze:** Die Leiste zeigt nur den Stand. Abbrechen oder Pausieren lässt sich der Wiki-Leser dort nicht.

## 113. Ordner hießen mit Anführungszeichen oder wie eine Adresse

**Problem:** Betatest 06.11.2026: 4 von 192 Ordnern mit Anführungszeichen im Namen (`'M.Muster'`), 2 mit `@`.

**Ursache:** Manche Mail-Programme setzen den Anzeigenamen in eigene Anführungszeichen oder tragen dort die Adresse ein: `"'M.Muster'" <m@firma.example>`, `"m@firma.example" <m@firma.example>`. `getaddresses` nimmt nur die äußeren weg, der Rest wurde über KID_ABSENDER zum Ordnernamen.

**Lösung:** `_name_aus_kopf` entfernt umschließende Anführungszeichen, eine Adresse gilt nicht als Name; dann zählt wie bei Mails ohne Namen die Domain (#107). Anführungszeichen im Namen selbst (O'Brien) bleiben. Schon angelegte Ordner bleiben, wie sie sind.

## 114. Die KI trug den Empfänger als Tag an fast jede Mail

**Problem:** Abnahme 06.11.2026 mit echter KI und erfundenen Mails: Alle 7 sicher abgelegten Mail-PDFs bekamen den Empfänger als Tag, die PDF-Anhänge nicht. In einer echten Sammlung wäre das der eigene Name an jeder Mail, wertlos für die Suche.

**Ursache:** Die Vollautomatik macht aus dem KI-Feld „empfaenger“ gewollt Personen-Tags (`tags_mit_empfaenger`, Nutzerwunsch 30.08.2026). Bei Scans unterscheidet das Personen, bei einer Mail steht im Kopf „An:“ aber fast immer der Nutzer selbst. Der erste Fix filterte nur das Feld „tags“: Die Unit-Tests waren grün, im Lauf mit echter KI stand der Name weiter da.

**Lösung:** Der Import kennt die eigenen Adressen. `mail_lesen.eigene_namen` schreibt ihre Anzeigenamen als `KID_EIGEN` ins PDF, `auto_pilot.mit_mailkopf` entfernt ihn aus `tags` und `empfaenger`, in beliebiger Schreibweise und Reihenfolge; andere Personen bleiben. Nur der ganze Name: „Familie“ aus „Familie Mustermann“ bleibt, und ein Postfach wie `info@` zählt nicht als Name, sonst verlöre jede Mail ihr Tag „Info“. Scans, Anhänge und schon abgelegte Mails bleiben, wie sie sind.

## 115. Speichern kopierte über das Original, kaputte Einstellungen wurden still überschrieben

**Problem:** Architektur-Review 07.11.2026, kein Schadensfall bekannt. Ein hart beendeter Prozess hinterließ beim Ersetzen eines PDFs eine halbe Datei am Platz des Originals. Eine halb geschriebene `settings.json` galt beim nächsten Start als nicht vorhanden: KID startete ohne Sammlung, die nächste Einstellung überschrieb sie. Bei `tags.json` wurde der eigene Katalog durch die Vorlage ersetzt, und die `.bak` bekam die kaputte Datei. Ein zweites KID auf derselben Sammlung ließ sich jederzeit starten.

**Ursache:** `shutil.move` auf ein vorhandenes Ziel ersetzt es unter Windows nicht in einem Schritt: `os.rename` scheitert, dann kopiert es über das Ziel (dasselbe Verhalten wie #104, dort nur am Papierkorb behoben). Python 3.14 kopiert dabei über das native `CopyFile2`, ein Patch auf `shutil.copyfile` greift also nicht; Abbruch-Tests brauchen einen echten Prozess. Der `python.exe` der `.venv` ist nur ein Starter: Wer ihn beendet, trifft den Kindprozess nicht sofort, darum im Test `sys._base_executable`. Die JSON-Dateien wurden direkt mit `open(..., "w")` geschrieben, `tags.json` zudem bei jedem Start. Fehler beim Laden der Einstellungen gingen nur an `print`, also in der EXE ins Leere.

**Lösung:** `sicher_speichern.py` schreibt über Temp-Datei, `fsync` und `os.replace`; `lade_json` legt Unlesbares als `<Name>.kaputt` beiseite, bevor jemand darüber schreiben kann, `gui.melde_beschaedigte` zeigt das an. `PDFHandler.ersetze_datei` ist die einzige Stelle, die ein vorhandenes PDF ersetzt, und prüft vorher Lesbarkeit und Seitenzahl. Der Tag-Katalog kommt aus der `.bak` zurück und wird nur noch bei einer Änderung geschrieben. `einzelstart.py` sperrt je Sammlung über einen benannten Mutex, der auch nach einem Absturz frei wird. `tests/test_datensicherheit.py` prüft den Quelltext: kein `json.dump` außerhalb von `sicher_speichern` (Ausnahme `mail_quellen`), kein `shutil.move` in den PDF-Schreibwegen, kein `print` in `src/`.

**Beleg:** Dauertest 07.11.2026 mit erfundenen PDFs von 2 MB: Ein echter Prozess schreibt fortlaufend Metadaten und wird nach zufälliger Zeit hart beendet, je 150-mal. Über `shutil.move` 3 Abbrüche mit beschädigtem PDF, über `sicher_speichern.ersetze_datei` keiner.

**Preis:** `os.replace` scheitert, wenn ein anderes Programm die Datei offen hält und das Löschen nicht erlaubt, das Überkopieren kam dort durch. Das zeigte sich noch am selben Tag als Speicher-Fehler, seither gibt es dafür einen Notweg (#118).

**Grenze:** Nach einem Abbruch bleibt `<Name>.pdf.tmp` neben dem heilen Original liegen, bis dasselbe Dokument wieder gespeichert wird; die Dokumentenliste blendet das aus. Nur Schutz vor dem Abbruch beim Schreiben. Das Anhängen beim signierten PDF (`saveIncr`) schreibt weiter in die Originaldatei. Kein Schutz vor einer defekten Platte, dafür braucht es ein Backup. `messlauf.py` startet `gui` direkt und umgeht die Sperre aus `main.py` (nur KID-S4). `fernsteuerung.py` sperrt seit 2026-11-07 selbst: Beim Release-Check v0.9.26 liefen kurz Peters EXE und das ferngesteuerte KID zugleich auf KID-Test; Test `test_kein_start_wenn_die_testsammlung_schon_offen_ist`.

## 116. Vorschau: nach dem Blättern mitten auf der Seite, Flackern beim Zoomen

**Problem:** Release-Check v0.9.26, 07.11.2026, Peter: Gezoomt mit dem Mausrad vorwärts geblättert, die neue Seite stand nicht an ihrem Anfang. Rückwärts stand die vorige Seite an ihrem Anfang statt an ihrem Ende. Beim Zoomen mit Strg+Mausrad flackerte es manchmal leicht. Beides gab es schon in v0.9.25.

**Ursache:** Das Mausrad hatte nur VOR dem Blättern eine Sperre (am Seitenende 400 ms warten, dann blättert die nächste Raste). Nach dem Seitenwechsel scrollten die Rasten, die das Rad im Schwung noch liefert, sofort in die neue Seite hinein, auch während sie noch hereinglitt. Programmgesteuert (`_blaettern`) landete die Ansicht korrekt oben, nur das echte Rad nicht. Rückwärts sprang `_blaettere_gleitend` ebenfalls nach oben, beim fortlaufenden Scrollen erwartet man dort das Seitenende. Beim Zoomen rief `_apply_zoom` zwischen Neuzeichnen und Verschieben `update_idletasks` auf: Tk zeichnete das größere Bild einmal an der alten Stelle, dann sprang die Ansicht unter den Mauszeiger.

**Lösung:** `_blaettern_per_rad` setzt nach dem Seitenwechsel 300 ms Nachlauf-Sperre (`NACHLAUF_MS`, länger als die Gleit-Animation; 400 ms waren Peter zu lang), in der `on_preview_mousewheel` Rasten verwirft; danach scrollt das Rad wieder normal. Mausrad und Leisten-Pfeile blättern `fortlaufend`: rückwärts steht die vorige Seite an ihrem Ende. Bild↑ und Pfeiltasten blättern weiter seitenweise an den Anfang. Die Sperre ist abschaltbar (Einstellungen → Vorschau, `vorschau_nachlauf`, Standard an; Peter: „nicht jeder will diese Pause haben“). `_apply_zoom` verschiebt ohne `update_idletasks`, `bbox` kennt die neuen Maße auch so. Tests: `test_mausrad_nach_dem_blaettern_beginnt_oben_auf_der_neuen_seite`, `test_mausrad_rueckwaerts_beginnt_am_ende_der_vorigen_seite`, `test_zoom_zeichnet_kein_zwischenbild_an_der_alten_stelle`.

**Merksatz:** Eine Sperre gegen das Durchrattern gehört auf beide Seiten des Ereignisses. Und wer zeichnen lässt, bevor die Ansicht stimmt, zeigt ein Zwischenbild.

## 117. Zoomen mit Strg+Mausrad träge: jede Raste zeichnete die ganze Seite neu

**Problem:** Release-Check v0.9.26, 07.11.2026, Peter: Zoomen fühlt sich „grenzwertig träge“ an, auf einem langsameren Rechner wohl zu träge.

**Ursache:** `on_zoom_mousewheel` startete nach 40 ms Ruhe `_apply_zoom`, also das komplette Rendern der Seite mit Markierungen. Rasten kommen beim Drehen etwa alle 30 bis 100 ms, darum renderte fast jede Raste die ganze Seite, und bei starkem Zoom ist das ein großes Bild. Gemessen an fünf Scans aus KID-Test auf Peters Rechner: 9 bis 19 ms bei 130 %, 93 bis 145 ms bei 500 %, dazu kommt die übrige Arbeit von `update_preview`.

**Lösung:** Jede Raste zeigt sofort ein Zwischenbild: `_zeige_zwischenbild` streckt nur den sichtbaren Ausschnitt des Rohbilds (`zwischenbild_ausschnitt`, Punkt unter dem Mauszeiger bleibt stehen) auf Fenstergröße, etwa 15 ms unabhängig vom Zoom. Scharf neu gezeichnet wird erst nach `SCHARF_NACH_MS` (150 ms) Ruhe. `PDFHandler.get_preview_image` hängt dem `PhotoImage` dafür `roh` (das PIL-Bild) und `zoom` an. `_apply_zoom` rechnet mit `bbox("blatt")` (Seite und Schatten), nicht mit `bbox("all")`, in dem das Zwischenbild läge. Das Zwischenbild hält sich an dieselben Bildlaufgrenzen wie danach das scharfe Bild (`_in_bildlaufgrenzen`: Seite plus Rand, mittig, wenn sie ins Fenster passt). Ohne das sprang es: Stand die Maus unter der Vorschau, zeigte das Zwischenbild grauen Rand unter der Seite und saß 115 px neben dem scharfen Bild; mit der Grenze 0 px (Aufnahme der Vorschaufläche in KID, `rc_zoom_versatz`). Peter danach: „flackert bzw. wackelt, fühlt sich aber flüssig an“. Das Zwischenbild deckte die ganze Fläche ab, ohne den dunklen Schatten (4 px rechts und unter der Seite): Der Rand verschwand bei jeder Raste und kam beim Scharfwerden zurück. Jetzt malt `_zeige_zwischenbild` ihn mit (`SCHATTEN_PX`, `SCHATTEN_FARBE`, dieselben Werte wie `update_preview`), und die Bildlaufgrenzen rechnen ihn rechts und unten mit ein wie die Scrollregion. Tests: `test_zwischenbild_haelt_den_punkt_unter_der_maus`, `test_zwischenbild_bleibt_in_den_bildlaufgrenzen`, `test_zoom_zeigt_sofort_ein_zwischenbild_und_zeichnet_spaeter_scharf`, `test_zwischenbild_zeigt_den_schatten_der_seite`. Danach Peter: „Stillstand Mausrad -> Bild wird an der alten Position mit alter Zoomstufe nochmal gezeichnet … es flackert“. `_apply_zoom` nahm das Zwischenbild weg, bevor es `update_preview` aufrief, und das lässt beim Start der Phase „Vorschau wird gezeichnet“ einmal zeichnen (`aktivitaet.phase` → `update_idletasks`, damit der Text in der Menüleiste erscheint). In diesem Moment lag nur das alte scharfe Bild auf der Fläche. Jetzt bleibt das Zwischenbild bis nach `update_preview` liegen (`_weg_mit_zwischenbild`, auch wenn `update_preview` den Cache trifft und nichts löscht); im echten KID protokolliert: beim Zwischen-Zeichnen 1 Zwischenbild obenauf, danach 0 (`rc_zoom_scharf_zeichnen`). Test: `test_zwischenbild_bleibt_bis_das_scharfe_bild_steht`.

**Preis:** Bis das Rad ruht, ist das Bild kurz unscharf. Das Rohbild bleibt im Speicher, bei 500 % rund 38 MB zusätzlich.

**Merksatz:** Für die Rückmeldung genügt, was schon da ist. Teuer gerechnet wird erst, wenn der Nutzer aufhört. Und ein Vorab-Bild muss denselben Regeln folgen wie das endgültige, sonst springt es. Weggenommen wird es erst, wenn das endgültige steht: Irgendwer zeichnet zwischendurch immer.

## 118. Speicher-Fehler WinError 32: ein anderes Programm hielt das PDF nur lesend offen

**Problem:** 07.11.2026, Peter, nach Release v0.9.26: Beim Ziehen mit Alt (Tags übertragen) kam zweimal hintereinander „Speicher-Fehler: Das PDF konnte nicht überschrieben werden … [WinError 32] … '….pdf.tmp' -> '….pdf'“. Kurz danach hielt niemand mehr die Datei offen. Nachgestellt per Fernsteuerung, ein Wächter über den Windows Restart Manager lief mit: KID selbst hielt die Datei nie offen. Wer sie bei Peter hielt, ist unbekannt (Indexdienst, Virenscanner, Anzeigeprogramm).

**Ursache:** Seit #115 ersetzt `os.replace` das PDF in einem Schritt. Windows erlaubt das nur, wenn jeder, der die Datei gerade offen hat, das Löschen mitgestattet. Viele Leser gestatten Lesen und Schreiben, aber nicht das Löschen, darunter jedes Python-`open`. Bis v0.9.25 lief `shutil.move`: Umbenennen auf das vorhandene Ziel scheiterte immer, dann kopierte es über das Ziel, und das gestattet ein solcher Leser. Mit Wegwerf-Dateien nachgeprüft: Bei offenem Leser scheitert `os.replace`, `shutil.move` kommt durch. Der „Preis“ von #115 war also im Alltag sichtbar.

**Lösung:** `sicher_speichern.ersetze_datei` versucht weiter zuerst `os.replace` mit Wiederholungen. Bleibt es bei `PermissionError`, überschreibt `_ueberschreibe` das Ziel an Ort und Stelle: Neue Fassung lesen, Ziel mit `r+b` öffnen (scheitert sofort und ohne Schaden, wenn der Halter auch das Schreiben verbietet), Original im Speicher behalten, schreiben, kürzen, `fsync`. Scheitert das Schreiben, kommt das Original zurück. Die Temp-Datei wird erst danach entfernt, ins Protokoll kommt eine Warnung. Verbietet der Halter auch das Schreiben, meldet KID wie bisher den ursprünglichen WinError 32. Tests mit echter Windows-Sperre per `CreateFileW` statt Patch: `test_offener_leser_verhindert_das_speichern_nicht`, `test_gescheitertes_ersetzen_laesst_das_original_unberuehrt`, `test_fehler_beim_ueberschreiben_bringt_das_original_zurueck`. Ohne den Notweg bzw. ohne das Zurückholen sind die Tests rot.

**Grenze:** Nur der Notweg ist nicht in einem Schritt. Wird der Prozess genau während des Überschreibens hart beendet, kann das Original halb geschrieben sein, die neue Fassung liegt dann aber vollständig als `<Name>.pdf.tmp` daneben. Das gilt auch für die JSON-Dateien.

**Merksatz:** Wer „in einem Schritt ersetzen“ einführt, braucht einen Plan für die Leser, die das Löschen nicht erlauben. Ein Test mit gepatchtem `os.replace` beweist das nicht, eine echte Sperre schon.

## 119. Wiki nachlesen brach ab: „KI-Server antwortet nicht: JSONDecodeError: Unterminated string“

**Problem:** 07.11.2026, Peter, Betatest: „Wiki: Bestand nachlesen“ endete mit „1008 von 1073 Dokument(en) gelesen … Abgebrochen, der KI-Server antwortet nicht: JSONDecodeError: Unterminated string starting at: line 1 column 10792“, beim nächsten Start nach „2 von 62“ wieder, diesmal „line 404 column 7 (char 11019)“. Der Server lief.

**Ursache:** `wiki_fakten.lies_fakten` begrenzt die Antwort mit `NUM_PREDICT = 5000` Tokens. Dokumente mit vielen Einträgen (Kontoauszug mit bis zu 30 Buchungen, Mieterlisten) brauchen mehr, die JSON-Antwort endet mitten in einer Zeichenkette; eingerücktes JSON (Zeile 404) verbraucht zusätzlich Tokens für Leerzeichen. Die Wiederholung mit etwas Zufall stößt an dieselbe Grenze, dann ging der `JSONDecodeError` an `lies_bestand`. Das zählte ihn wie einen Verbindungsfehler: drei in Folge = „KI-Server antwortet nicht“, Abbruch. Solche Dokumente stehen oft im selben Ordner hintereinander. Da sie offen blieben, kamen sie beim nächsten Start wieder zuerst dran.

**Lösung:** `rette_json` repariert eine abgeschnittene Antwort: hinter dem letzten vollständigen Wert abschneiden, offene Klammern schließen; verloren geht nur der angefangene Eintrag (bleibt er halb stehen, fehlt ihm der Beleg, und `pruefe_fakten` lässt ihn nicht als Fakt gelten). Gerettet wird ohne Wiederholung. Ist nichts zu retten, wirft `lies_fakten` nach der Wiederholung `UnbrauchbareAntwort`; `lies_bestand` zählt das als „unbrauchbar“, nicht als Fehler in Folge, und läuft weiter. Die Meldung nennt diese Dokumente, sie bleiben offen und kommen beim nächsten Start wieder dran. Der Hintergrund-Leser (`wiki_leser`) überspringt schon bisher alles außer `OSError`. Prompt und Prüfregeln unverändert, darum kein neuer `REGELN`-Stand. Tests: `test_abgeschnittene_antwort_wird_gerettet`, `test_unrettbare_antwort_meldet_sich_als_solche`, `test_rette_json_ohne_vollstaendigen_wert`, `test_unbrauchbare_ki_antwort_bricht_den_lauf_nicht_ab`; ohne `rette_json` bzw. ohne den eigenen Zweig rot.

**Grenze:** Die Ursache selbst, die Token-Grenze, bleibt: Bei sehr langen Dokumenten fehlen die Einträge hinter dem Schnitt. Mehr `NUM_PREDICT` braucht mehr `NUM_CTX` (Text bis 16.000 Zeichen plus Antwort) und damit Zeit und Speicher auf dem Server; erst messen. Nicht an den Dokumenten des Beta-Testers nachgeprüft (Datenschutz: nur Peter startet echte Läufe).

**Merksatz:** Eine Antwort, die kommt, ist kein Serverausfall. Wer Fehler zählt, um aufzugeben, zählt nur die, bei denen Weitermachen sinnlos ist.

## 120. Die KI-Tags waren fast alle unbrauchbar: die Vollautomatik vergibt keine Tags mehr

**Problem:** 07.11.2026, Peter prüfte die Sammlung eines Beta-Testers: „fast alle von der KI generierten Tags nicht brauchbar“, er entfernte die meisten von Hand. Bis dahin hatten Bewährungs-Warteliste, Wildwuchs-Regeln und die Prüfung neuer Tags (`grund_gegen_neues_tag`, #82), Ignorierliste und Katalog-Sperre das nur eingedämmt.

**Ursache:** Kein einzelner Bug, sondern die Aufgabe: Welches Tag ein Dokument wiederfindbar macht, ist Geschmack und Zusammenhang der Sammlung. Das lässt sich nicht gegen das Dokument prüfen wie Datum oder Absender, die KI ist dabei oft sicher und trotzdem daneben.

**Lösung (Etappe 6, Peter: „Zukünftig werden keine Tags mehr von der KI generiert“):** `auto_pilot.baue_entscheidung` liefert immer `tags = []` und `neue_tags = []`, auch keinen Absender-Tag beim Sammelordner „Einzelne Mails“ (der Absender steht im Mailkopf des PDFs, die Volltextsuche findet ihn). Die KI-Tags laufen intern weiter durch die bisherigen Regeln, weil `finde_ordner_ueber_hinweise` sie bei Dokumenten ohne Absender als Hinweis auf den Ordner braucht; die Ordnerwahl war beim Betatest meist in Ordnung und bleibt gleich. „keine Tags erkannt“ macht ein Dokument nicht mehr unsicher (vorher wäre ohne KI-Tags fast alles in `0_Unsicher` gelandet), auch nicht ein leeres Tag-Feld in der Ablage-Vorschau. `fuehre_entscheidung_aus` schreibt `keywords` nur noch, wenn ein Mensch in der Ablage-Vorschau Tags eingetragen hat; sonst bleiben Tags im PDF stehen (vorher überschrieb ein leeres Feld sie). Die Dubletten-Prüfung liest die Tags aus dem PDF und ist nicht betroffen. Tests: `test_ki_tags_kommen_nicht_ins_pdf_vorhandene_bleiben`, `test_tags_aus_der_ablage_vorschau_werden_geschrieben`, `test_tags_leeren_ist_kein_problem`, `test_fehlender_titel_macht_unsicher_fehlende_tags_nicht`, `test_kein_absender_tag_mehr`; mit der alten `auto_pilot.py` rot. 14 Tests, die nur die Tag-Ausgabe der Entscheidung prüften, sind entfallen.

**Schritt 2 (08.11.2026):** Das Werkzeug „Tags ergänzen (KI)“ ist entfernt, samt `auto_pilot.ergaenzungs_tags`. Der Titel-Vorschlag filtert die KI-Tags auf den Katalog (`katalog_vorschlaege`, Katalog-Schreibweise, ohne was das Dokument schon trägt) und schreibt sie nicht mehr von selbst ins Tag-Feld (vorher `merge_tags`); die Liste zeigt „[+N Vorschläge: Doppelklick]“, der Tag-Dialog bietet sie als Knöpfe zum Anklicken. Test: `test_ki_tags_kommen_nicht_von_selbst_ins_tag_feld`, mit der alten `_on_suggestion_ready` rot.

**Schritt 3 (08.11.2026):** Die Bewährungs-Warteliste (`tag_kandidaten.py`, `tag_kandidaten.json`) und die Einstellung „Nur Tags aus dem Katalog vergeben“ (`auto_pilot_nur_bekannte_tags`, samt `auto_pilot.nur_katalog_tags`) sind entfernt, ebenso die Einstellung „Neue Tags der KI in den Katalog aufnehmen“ und der Knopf „Wartende KI-Tags…“ der Tag-Hygiene. Von Hand eingetragene neue Tags kommen sofort in den Katalog (`TagManager.add_tags_to_catalog(neue_tags)`). Die Parameter `wartende` und `nur_bekannte_tags` sind aus der ganzen Kette `auto_pilot` → Dienst/Ablage-Vorschau/Begleitet erfassen verschwunden; die beiden Aufrufe, die Argumente nach Position weiterreichten, sind auf Namen umgestellt. Die alten Einstellungswerte bleiben in `settings.json` stehen und sind im Experten-Reiter ausgeblendet; eine vorhandene `tag_kandidaten.json` im Daten-Ordner bleibt liegen und wird nicht mehr gelesen. Folge für die Ordnerwahl: War die Katalog-Sperre an (Tester-PC), standen als Ordner-Hinweis ohne Absender nur Katalog-Tags zur Verfügung, jetzt alle KI-Tags; wirkt nur bei Dokumenten ohne erkannten Absender und exakter Gleichheit mit einem Ordnernamen. Die Sammelkategorie für neue Tags heißt jetzt „Neu“ statt „Neu (KI)“ (Peter: „Ja bitte“); `tag_editor.migriere_neu_kategorie` stellt vorhandene Kataloge beim Laden um, eine schon vorhandene Kategorie „Neu“ nimmt die Tags ohne Doppelte auf. Im Katalog von KID-Test geprüft: 15 Tags, danach unter „Neu“, alles andere gleich.

**Grenze:** Der KI-Prompt fragt weiter nach Tags, weil die Ordnerwahl sie als Hinweis nutzt. Feste Regeln wie „Versicherung“ oder „Nebenkosten“ ergeben sich laut Peter erst aus dem interaktiv aufgebauten Wiki.

**Merksatz:** Die KI arbeitet nur dort selbstständig, wo man ihr Ergebnis gegen das Dokument prüfen kann. Was eine Sammlung wiederfindbar macht, entscheidet der Mensch.

## 121. Fernsteuerung: KID nahm beim Start den Fokus, danach öffneten sich Fenster am Mauszeiger im anderen Programm

**Problem:** 08.11.2026, Peter: „sorge dafür, dass sich keine Fenster mehr an meinem Mauscursor öffnen, wenn ich in einem anderen Programm bin, und klau mir dort auch nicht den Fokus.“ Während Claude per Fernsteuerung testete, arbeitete Peter in einem anderen Programm; das Fenster „Mails importieren“ erschien an seinem Mauszeiger.

**Ursache:** Zwei Dinge zusammen. (1) `fernsteuerung.py start` startet KID aus dem Vordergrund-Programm heraus (Claudes Shell im Editor), Windows gibt dem ersten Fenster des neuen Prozesses darum den Fokus. (2) Damit galt KID für `UIUtils.app_hat_fokus` als aktiv, und `_anker` setzte das nächste Fenster an den Mauszeiger statt über KID (Regel aus #90). Dazu rief Claudes Vorbereitungsskript `f.lift(); f.focus_force()` auf - `focus_force` holt das Fenster ausdrücklich nach vorn.

**Lösung:** `fernsteuerung._starte` merkt sich vor `tk.Tk()` das Vordergrundfenster (`_vordergrund`) und gibt ihm den Fokus einmal zurück, wenn das erste Zeigen des Hauptfensters ihn genommen hat (`_fokus_nicht_klauen`, `fokus_zurueckgeben`; geprüft nur kurz nach dem Erscheinen, damit ein späterer Klick in KID nicht zurückgedreht wird). Danach hält sich KID korrekt für „nicht aktiv“, neue Fenster kommen über KID. Gegenprobe: nach dem Neustart Vordergrund = das andere Programm, `app_hat_fokus` = False. Claudes Skripte rufen weder `lift`, `focus_force` noch `-topmost` auf, außer nach `hinweis` und Peters „Los“. Test: `test_start_klaut_keinen_fokus`, ohne den Rückgabe-Aufruf rot.

**Merksatz:** Ein Programm, das ein anderer gerade nicht benutzt, nimmt sich weder Fokus noch Mausposition. Wer „ist die App aktiv?“ fragt, muss damit rechnen, dass sie sich den Fokus selbst genommen hat.

## 122. Rotprobe: nach dem Zurücksetzen lief weiter der kaputte Code

**Problem:** 08.11.2026, eigene Adressen aus gesendeten Mails: Nach der Rotprobe (`EIGENE_MINDESTENS = 3` testweise auf `1`, Test rot, zurück auf `3`) schlug ein Gegencheck mit dem echten Code eine Adresse mit nur einer Mail vor - obwohl im Quelltext wieder `3` stand.

**Ursache:** Python hält eine `.pyc` in `__pycache__` für gültig, solange Änderungszeit (in ganzen Sekunden) und Größe der Quelldatei zu ihr passen. Die Rotprobe schrieb den kaputten und den richtigen Text gleich lang und in derselben Sekunde; der Testlauf dazwischen hatte den kaputten Bytecode gespeichert, und der galt danach weiter. Ein Testlauf nach der Rotprobe hätte also die falsche Fassung geprüft.

**Lösung:** Nach jedem Zurücksetzen den Cache des Moduls löschen (Claudes Ersetz-Hilfe tut das seitdem selbst), Regel in CLAUDE.md bei der Rotprobe. Wer zweifelt: `__pycache__` unter `src/` und `tests/` löschen.

**Merksatz:** Nicht nur der Quelltext muss zurück, auch was Python daraus gemacht hat.

## 123. Dieselbe eigene Adresse zweimal im Vorschlag, einmal als „Name <adresse>“

**Problem:** 08.11.2026, Peters erster Lauf der Erkennung eigener Adressen an echten Mails: Die Rückfrage nannte seine Hauptadresse zweimal, einmal rein und einmal in der Form „Name <adresse>“.

**Ursache:** Manche Mails tragen den Absender ganz in Anführungszeichen (`From: "Name <a@b.de>"`). Für `email.utils.getaddresses` ist das ein Anzeigename ohne Adresse - es liefert den ganzen Text als Adresse. Folge nicht nur im Vorschlag: `ist_eigene` erkannte solche Mails nie, sie galten als eingegangen, mit dem Nutzer selbst als Gegenüber.

**Lösung:** `mail_lesen._bereinigt` holt die Adresse aus „Name <a@b.de>“ (und den Namen, falls keiner da ist); `_adressen` und `_namen_und_adressen` gehen beide darüber. Das Feld „Eigene Adressen“ (`mails_importieren.eigene_aus_text`) nimmt aus solchen Einträgen nur die Adresse und streicht Doppelte - ein schon übernommener kaputter Eintrag heilt beim nächsten Einlesen. Tests: `test_adresse_ganz_in_anfuehrungszeichen`, `test_eigene_adressen_aus_gesendeten_mails`, `test_eigene`; ohne den Fix rot.

**Merksatz:** Ein Mailkopf ist Eingabe von irgendwem - auch die Absenderzeile kann eine Form haben, die die Standardbibliothek anders liest als ein Mensch.

## 124. Testfenster poppten am Mauszeiger auf und nahmen den Fokus

**Problem:** 08./09.11.2026: Bei jedem Testlauf (Claudes Läufe, pre-push-Hook) erschien das Mail-Import-Fenster mehrmals kurz neben dem Mauszeiger, während Peter in einem anderen Programm arbeitete. Peter fragte, ob das ein Test von Claude sei.

**Ursache:** Fenster-Tests bauen echte Tk-Fenster und lassen sie absichtlich sichtbar (FALLSTRICKE #95), und `UIUtils.position_near_mouse` setzt sie wie im Programm an die Maus. Fenster nur aus dem Bildschirm zu schieben reichte nicht: Ein Wächter, der alle 5 ms das Vordergrundfenster prüfte, sah danach immer noch rund 270 Proben (gut 1 s je Lauf) mit einem Testfenster im Vordergrund - Tastendrücke wären unsichtbar dort gelandet. Windows gibt einem Prozess den Vordergrund, wenn ihn das gerade aktive Programm gestartet hat (hier VS Code über Claude Code).

**Lösung:** `tests/__init__.py` legt vor dem ersten Testmodul einen eigenen Windows-Desktop „KID-Tests“ an (`CreateDesktopW`) und hängt den Haupt-Thread daran (`SetThreadDesktop`, geht nur, solange der Thread noch kein Fenster hat). Fenster eines anderen Desktops sind nie zu sehen und können den Fokus nicht nehmen; für Tk sind sie ganz normal sichtbar, alle Tests laufen unverändert. Der Wächter sah danach 0 Proben. Test `test_testumgebung`; ohne `SetThreadDesktop` rot. Geht der Desktop nicht, meldet `tests` das und die Fenster erscheinen wie früher.

**Merksatz:** Ein Fenster außerhalb des Bildschirms ist unsichtbar, aber nicht harmlos - den Fokus nimmt es trotzdem.

## 125. Mail-Import: Fenster „Keine Rückmeldung“, solange der Text im Hintergrund nachgelesen wurde

**Problem:** 09.11.2026, Peters Test von „Schneller einlesen“, Bauschritt S1, mit 20.000 künstlichen Mails: Nach Phase 1 zeigte Windows „Keine Rückmeldung“, bis Phase 2 fertig war. Ein Messlauf in der App fand eine einzige Lücke von 35 s im Tk-Ereignis-Loop - genau die Dauer von Phase 2 -, aber keine einzelne langsame Aktion (die längste 0,2 s).

**Ursache:** `_abholen` leerte das Postfach in einer Schleife „bis es leer ist“. Phase 2 schickte jede Mail einzeln, etwa so schnell, wie das Fenster sie verarbeitete - das Postfach wurde nie leer, `_abholen` kehrte nicht zurück, und Tk kam weder zum Zeichnen noch zu den Fenster-Nachrichten von Windows.

**Lösung:** `_abholen` holt höchstens `ABHOLEN_SEKUNDEN` (50 ms) lang ab und kommt nach 10 ms wieder, wenn noch etwas wartet. Phase 2 bündelt ihre Ergebnisse (`TEXT_BUENDEL_SEKUNDEN`, etwa viermal je Sekunde, `_texte_da`). Test `test_abholen_laesst_das_fenster_wieder_zeichnen` (ein Postfach, das sich selbst nachfüllt); ohne die Zeitgrenze kehrt er nicht zurück.

**Merksatz:** „Abholen, bis nichts mehr da ist“ endet nie, wenn jemand schneller nachlegt - jede Abholschleife im Tk-Thread braucht eine Zeitgrenze.

## 126. Mail-Import: Suchen während Phase 2 dauerte 26 Sekunden

**Problem:** 09.11.2026, nach dem Fix #125 hing das Fenster weiter, aber nur, wenn Peter während Phase 2 suchte. Nachgestellt in der App: „rechnung“ in 20.000 künstlichen Mails dauerte während Phase 2 26,5 s, danach 0,06 s. Ohne Bedienung lief das Fenster flüssig, keine Pause über 0,33 s.

**Ursache:** Konvoi-Effekt der Python-Rechenerlaubnis (GIL). Jeder Tk-Aufruf gibt sie ab, solange Tcl arbeitet; zurück bekommt der Tk-Thread sie gegen einen ununterbrochen rechnenden Thread erst nach dem Wechselintervall von 5 ms. Die Trefferliste füllt bis zu 5.000 Zeilen (`MAX_ZEILEN`) - 5.000 × 5 ms. Einzelne Tk-Aufrufe (Klicken, Blättern) merkt man nicht, viele am Stück schon.

**Lösung:** `mit_vorrang` an den Methoden mit vielen Tk-Aufrufen (`_suche`, `_setze_bestand`, Anhaken) setzt ein Ereignis, Phase 2 schläft je Mail, solange es gesetzt ist (`warte_auf_vorrang` steckt im `abbrechen` von `lies_texte`, der Kern bleibt unberührt). Test `test_phase_2_wartet_solange_das_fenster_vorrang_hat`; gemessen in der App vorher 26,5 s.

**Merksatz:** Ein rechnender Hintergrund-Thread bremst nicht die Rechnung im Tk-Thread, sondern jeden einzelnen Tk-Aufruf - viele davon am Stück brauchen Vorrang.

## 127. Wiki: frisch abgelegtes Dokument galt als „ohne erkannten Text“

**Problem:** 13.11.2026, Peter ließ im Wiki ein Dokument von der KI lesen: „0 Dokumente gelesen · 1 ohne erkannten Text“, obwohl die Rechnung eine saubere Textebene hat.

**Ursache:** `index_manager.wiki_text` las nur den Volltext-Cache. Den füllt erst eine Volltextsuche (oder früher der Abgleich des alten Sammlungs-Wikis); ein Dokument, das seit der Ablage in keiner Suche vorkam, hat dort keine Zeile. Keine Zeile und leerer Text sahen gleich aus.

**Lösung:** Fehlt die Zeile und gibt es die Datei, gleicht `wiki_text` den Cache erst ab (`_abgleich`, `_ensure_fulltext_baseline`) und liest dann noch einmal. Test: `test_wiki_text` beginnt mit leerem Cache.

**Merksatz:** Ein Cache, der nebenbei von einer anderen Funktion gefüllt wird, ist keine Quelle - wer daraus liest, muss „nicht da“ von „leer“ unterscheiden und selbst nachfüllen.

## 128. Öffentliches Repo enthielt persönliche Angaben, obwohl dort „nur Doku“ lag

**Problem:** 14.11.2026, Etappe 8 (Quellcode veröffentlichen): Das private Repo war bereinigt, die Prüfung meldete 0 Fundstellen. Im öffentlichen Repo standen trotzdem ein echter Raumname und ein Bankkürzel im CHANGELOG, ein echter Ortsname in der Historie (in allen 13 Release-Tags) und dieselben Angaben in einem Release-Text auf GitHub.

**Ursache:** Das Release-Skript hatte CHANGELOG und Leitfaden bei jedem Release ungeprüft kopiert, und die Release-Texte entstehen außerhalb beider Repos. Die Bereinigung des privaten Repos erreicht nichts, was schon draußen ist.

**Lösung:** Öffentliche Historie einmalig mit der Ersetzungsliste umgeschrieben (`git filter-branch --tree-filter … --tag-name-filter cat -- --all`, Tags per Force-Push mitgezogen - Releases hängen am Tag-Namen und bleiben samt EXE erhalten), Release-Text per `gh release edit` korrigiert. Seitdem prüft `veroeffentlichen.py` JEDE Datei vor dem Kopieren gegen die private Begriffsliste und bricht bei einer Fundstelle ab, bevor es etwas schreibt (`tests/test_veroeffentlichen.py`). Release-Notizen gehen durch dieselbe Prüfung, bevor sie veröffentlicht werden. Nebenbefund: `filter-branch -- --all` schreibt auch `refs/remotes/origin/*` um, ein Vergleich gegen `origin/main` zeigt danach nichts - gegen `refs/original/…` vergleichen.

**Merksatz:** „Nichts Privates veröffentlichen“ heißt: alles prüfen, was schon draußen ist (Dateien, Historie, Tags, Release-Texte), und den Weg nach draußen selbst zur Prüfstelle machen.
