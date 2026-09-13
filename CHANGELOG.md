# Changelog

Kurzfassung je Version, neueste zuerst. Die vollständigen Release-Texte (samt EXE-Download) stehen bei den [GitHub-Releases](https://github.com/peterm2024/Dokumenten-Manager/releases); Hintergründe zu einzelnen Fixes in [FALLSTRICKE_UND_WORKAROUNDS.md](FALLSTRICKE_UND_WORKAROUNDS.md).

## v0.9.17 — 2026-09-13

- Beta-Vorbereitung: Interne Fehler werden nicht mehr verschluckt. Jeder unbehandelte Fehler (Bedienung, Hintergrund-Threads, Hauptprogramm) landet mit vollständigem Traceback im Protokoll und in einem Dialog „Interner Fehler“ mit „Protokoll jetzt öffnen?“ (dieselbe Meldung höchstens alle 30 s). Ein Absturz schon beim Start wird als `startfehler.txt` neben die EXE geschrieben und angezeigt.
- Einstellungen → KI-Server: neues Häkchen „KI ohne Grafikkarte zulassen“ für Ollama auf einem PC ohne passende Grafikkarte. Die Wartezeit je Anfrage wird auf das Sechsfache verlängert, die Vollautomatik pausiert bei Prozessor-Betrieb nicht mehr (nur ein „HINWEIS“ im Protokoll), „Posteingang verarbeiten“ fragt nicht mehr nach, „Verbindung testen“ meldet eine Info statt der Warnung. Ohne Häkchen bleibt Prozessor-Betrieb ein Defekt-Signal wie bisher.
- Sicherungshinweis: Der Willkommens-Dialog, das erste Öffnen eines Ordners mit vorhandenen PDFs und der Schnellstart weisen darauf hin, dass Titel, Tags und Datum in die PDF-Dateien geschrieben werden, und raten zum Kennenlernen zu Kopien.
- Hilfe: neuer Abschnitt „KI auf dem eigenen PC“ (auch im Hilfe-Menü) mit Ollama-Installation in drei Schritten und einer Tabelle, wie lange ein Dokument je nach Rechner dauert (nur Prozessor / integrierte Grafik / Grafikkarte 8 GB / 16 GB). Dieselbe Tabelle steht in der README.
- Neu im Projekt: `BETA_LEITFADEN.md`, eine Seite für Tester (Einrichtung, KI mit oder ohne, was testen, bekannte Grenzen, Rückmeldung).

## v0.9.16 — 2026-09-13

- KI-Server-Anzeige: Ein Farbpunkt rechts in der Suchleiste zeigt, ob der KI-Server antwortet (grün verbunden, rot nicht erreichbar, grau beim Prüfen; der Text erscheint als Tooltip). Alle Werkzeuge, die den Server brauchen (Titel vorschlagen, Tags ergänzen, Ablage-Vorschau, Posteingang verarbeiten), sind im Menü und im Rechtsklick-Menü ausgegraut, solange er fehlt, und werden von selbst wieder frei; „Verbindung testen“ zieht die Anzeige sofort nach. Anlass: ein Werkzeug lief ohne Server los und blieb stumm stehen.
- Platz in der Oberfläche: Der Hinweis „(auch 2020 oder 07.2020)“ steht nicht mehr in der Suchleiste, sondern erscheint als Tooltip auf den Von-/Bis-Feldern; die fünf Bereiche (Ordnerbaum, Tag-Baum, Suchleiste, Dokumentenliste, Eigenschaften) tragen keine Titelzeile mehr, der Inhalt beginnt direkt am Rahmen (FALLSTRICKE #71).

## v0.9.15 — 2026-09-13

- Suche: Das Suchfeld schlägt beim Tippen Tags vor (dieselbe Autovervollständigung wie im Tags-Feld; ein Tag mit Leerzeichen wird als Phrase in Anführungszeichen übernommen) und zeigt Tags im Suchtext blau-fett wie im Tag-Baum; Return sucht sofort. Nach „Reset“ bleibt die Liste nicht mehr leer, wenn der angeklickte Treffer im markierten Ordner lag (FALLSTRICKE #70).
- Hilfe: neuer Reiter „Tags“ (Hilfe → „Tags: Sinn und Grenzen“): was ein Tag ist, wofür Tags gedacht sind, warum Tags trotz Suche, Vorteile, Nachteile und Grenzen, bewährte Praxis, Arbeiten ohne Tags. In der ganzen Hilfe heißt es jetzt „Tags“ statt „Schlagwörter“; Beispiele ohne persönliche Angaben.
- Vollautomatik: pausiert, wenn der KI-Server ohne Grafikkarte rechnet (Meldung im Statusfenster, im Angehörigen-Protokoll und im Log; läuft von selbst weiter, sobald die Grafikkarte zurück ist); „Posteingang verarbeiten“ fragt in dem Fall nach.

## v0.9.14 — 2026-09-12

- Windows-Textgröße 125 % (Barrierefreiheit, Eltern-PC): Fenstergrößen, Umbrüche und Spaltenbreiten wachsen jetzt auch mit der Textgröße, nicht nur mit der Bildschirm-Skalierung; Zeilen in Bäumen und Tabellen sind so hoch wie die Schrift (keine abgeschnittenen Unterlängen); in den Einstellungen bleiben Fußzeile mit „Schließen“, „Ändern…“ und „Altbestand nachziehen“ immer sichtbar; Reset-/Speichern-Knopf und Statusfenster nutzen die Standardschriftgröße (FALLSTRICKE #69).
- Vollautomatik: nach jedem abgelegten Dokument wird der angezeigte Posteingang nur noch einmal neu gelesen statt zweimal (#68).
- KI-Server → „Verbindung testen“ meldet, ob das Modell auf der Grafikkarte oder still auf der CPU rechnet, und warnt bei CPU-Betrieb (Ursache des Timeouts in Dachau, #67).

## v0.9.13 — 2026-09-12

- Menü-Hilfe: zu jedem Menüeintrag „Was“ und „Wofür“ — als Fensterchen, das erscheint, wenn der Mauszeiger gut eine Sekunde auf einem Eintrag verweilt (auch in Untermenüs und Rechtsklick-Menüs, abschaltbar unter Datei → Einstellungen), und als neuer Hilfe-Reiter „Menü-Übersicht“; Werkzeuge bringen ihre Erklärung selbst mit (FALLSTRICKE #65: Tk-Menü-Klone).
- Dubletten finden: Spalte „Vorschau“ zeigt, welche Zeile links und welche rechts verglichen wird, Kopfzeilen „Markiert:“/„Vergleich:“, Shift+Klick wählt das rechte Dokument; beide Vorschauen bleiben gleich breit (#66).
- Dubletten-Gedächtnis: Doppelklick auf die Gruppenzeile (oder „Gruppe als geprüft merken“) merkt eine geprüfte Gruppe als „keine Dublette“ und blendet sie aus — dauerhaft über Dokument-IDs (`KID_ID`, einmalig ins PDF eingebrannt, im Details-Block sichtbar); Häkchen „Geprüfte Gruppen anzeigen“ und „Prüfung aufheben“ machen es rückgängig, ein neu hinzukommendes Dokument lässt die Gruppe wieder erscheinen.

## v0.9.12 — 2026-09-11

- Aktivitätsanzeige rechts neben „Hilfe" in der Menüleiste: zeigt in Klartext, was gerade läuft („Lese Ordner … (12 Dateien)…", „Suche läuft…", „Vorschau wird gezeichnet…", „Speichere …", „KI antwortet … (14 s)", „Wartet auf deine Antwort: „…""), im Ruhezustand „Bereit" — auf langsamen Rechnern sieht man so, dass es weitergeht.
- Suchtreffer im Dokument: bei aktiver Suche markiert die Vorschau die Suchbegriffe hellblau mit blauem Rahmen (Datum bleibt gelb/rot), springt beim Anklicken eines Treffers auf die erste Fundstelle und nennt in der Titelleiste Trefferzahl bzw. Trefferseite; Treffer nur in Name/Titel/Tags oder im verbesserten Index-Text werden als „nicht im Seitentext" ausgewiesen.
- Phrasensuche: `"Peter Metz"` in Anführungszeichen findet nur den zusammenhängenden Text (nicht „Metz, Peter"), Zeilenumbruch zählt als Leerzeichen; ohne Anführungszeichen wie bisher jedes Wort für sich. Hilfe-Absatz „Wiederfinden" ergänzt.
- Behoben: unscharfe Suche traf Bruchstücke von OCR-Müll („Kostal" fand „Sta(l^'tc^ke" = Stadtwerke) — kürzere Wörter brauchen jetzt eine höhere Ähnlichkeit (#64).

## v0.9.11 — 2026-09-11

- Dateinamen unter Kontrolle: der bisherige Name wird beim ersten Umbenennen als „Originalname" ins PDF eingebrannt (Details-Block); Umbenennen beim Ablegen abschaltbar; neues Tool „Dateinamen aufräumen" (Vorschlag `JJJJMMTT_Titel.pdf`, nur Angehaktes wird umbenannt, Originalnamen wiederherstellen, Müll-Titel orange, „KI-Titel vorschlagen").
- Vollautomatik: Objekt-Alias ordnet absenderlose Eigenbelege (Notizen, Zählerstände) per Zielordner-Klick ihrem Haus zu; Rücksendezeilen wie „Bay. LfSt, PF 0151 Straubing" werden gekürzt und reine Kürzel nie zum neuen Ordner.
- Dokumentenliste: optionale Spalte „Textqualität" (kaputte Scanner-OCR sofort sichtbar, aktualisiert sich nach „Dokument neu erfassen"); Datums-Marker ohne Doppel-Treffer und nach dem Neu-Erfassen bündig (#63); Hilfe springt zum Tailscale-Abschnitt (#62); Tag-Suchfeld: Esc gibt Fokus an den Baum, F2/Strg+I aus dem Suchfeld.
- Behoben: Spaltenbreite ziehen endete als Drag & Drop (#61).
- Entwicklung: Test-Wizard `python testwizard.py` führt durch MANUELLE_TESTS.md (feste IDs, Vorbereitung/Datei/Klicks).

## v0.9.10 — 2026-09-09

- Tag-Katalog mit drei Knoten-Arten: zuweisbares Tag, graue Struktur-Kategorie (wird jetzt auch von der Vollautomatik nie vergeben) und neu das blau-kursive **Synonym** („Haftpflichtversicherung" steht für „Haftpflicht"; Personen als Synonym unter ihrem Ort = „wohnt in"). Tag-Hygiene ersetzt Synonyme im Bestand auf Knopfdruck.
- Tag-Wildwuchs gebremst: Struktur-Kategorien zählen als bekannt (keine Doppelgänger unter „Neu (KI)", #59); Objekte und Personen schnappen auf die Katalog-Schreibweise (Namensdreher, &/und, akademische Titel, angeklebte Anschrift, PLZ ist kein Objekt); neue KI-Tags kommen erst beim zweiten Dokument in den Katalog („Bewährung", Warteliste in der Tag-Hygiene); Einstellung „Nur Tags aus dem Katalog vergeben" für fertige Kataloge.
- Dubletten: KI-Zweitprüfung räumt unscharfe Verdachte aus (jede Seite einzeln abgelesen, Kennnummer/Betrag vergleicht der Code); Grauzone bei gleichem Datum stoppt doppelt gescannte Rechnungen (#56). Ablage-Vorschau: Zielordner-Revalidierung, manuelle Freigabe gelber Zeilen, Volltext der Ergebnis-Zeile.
- Oberfläche in Klartext: Einstellungen als Reiter mit Erklärzeilen unter „Datei", Tools-Menü mit Untermenüs, schreibgeschützter Detail-Block „Details" zu jedem Dokument, Routine-Rückfragen abschaltbar (Unumkehrbares fragt immer).
- Behoben: Watchdog verschob die Datei unter dem laufenden Auto-Save weg (#54), desktop.ini als Dokument (#55), „_1"-Kaskade beim Umbenennen (#57), unsichtbares Fenster nach Monitorwechsel plus Maximiert-Merken (#58), liegengebliebene „…pdf.tmp" bei geöffnetem PDF (#60).

## v0.9.9 — 2026-09-05

- Seniorenmodus Schritt 5 (Roadmap abgeschlossen): Ersteinrichtung beim ersten Start (Standardordner anlegen / eigenen wählen / später), Vollautomatik-Schalter im Schnellstart-Fenster.
- Auto-Hierarchie auch in der Vollautomatik: konkrete Sparten-Tags („Gebäudebrandversicherung") tragen ihre Oberkategorien („Versicherung") automatisch mit ein; Prompt liefert Sparte und versichertes Objekt.
- „Allerweltswörter"-Regel beendet den Ortsnamen-Magneten: ein Ordnerkern ohne eigenes, eindeutiges Wort matcht nicht mehr (FALLSTRICKE #50).
- Statusfenster zweispaltig: links das zuletzt abgelegte Dokument mit Ergebnis, rechts das gerade verarbeitete.
- Behoben: Hilfe-Fenster überlappte die Ersteinrichtungs-Frage (#51); Hintergrund-Sync der Ablage-Vorschau scheiterte am Schrägstrich-Mix im Pfadvergleich (#52).

## v0.9.8 — 2026-09-03

- Tag-Hygiene-Tool: selten benutzte Tags sammeln, entfernen und dauerhaft ignorieren; Ignorierliste bearbeitbar.
- Objekt im Titel („… Gebäudeversicherung Winterstr. 8"); Ort und Objekt als getrennte Schlagwörter.
- „Ordner zusammenführen" per Rechtsklick, inklusive gemerkter Zuordnung.
- Ablage-Vorschau: maximierbar, Zeile zeigt das Dokument im Hauptfenster, Tags in der Zelle korrigierbar, vollständiges Protokoll.
- Behoben: c/o-Zustellvermerke zerhackten Namen (#47), Adress-Schreibvarianten (#48), Ordner-Wildwuchs durch Wortreihenfolge/Rechtsform, flatternde Bildlaufleiste (#49).

## v0.9.7 — 2026-08-31

- Dubletten-Prüfung vor dem automatischen Ablegen: liegt das Dokument schon im Zielordner, geht es begründet nach `0_Unsicher`.
- Mehrfach-Verschlagwortung (mehrere Dokumente markieren, Doppelklick im Tag-Baum); Orte/Objekte als eigene Schlagwörter; Datumssuche mit Jahres- und Monatsangaben.
- Gemerkte Absender-Zuordnungen einsehbar und löschbar; Zielordner-Korrektur gilt nur noch auf Wunsch für den ganzen Absender (#44).
- Diverse Anzeige-Fixes bei 125-%-Skalierung in allen Fenstern (#42).

## v0.9.6 — 2026-08-31

- Skalierungs-Fixes im Statusfenster, waagerechte Bildlaufleiste in der Ablage-Vorschau, sauberes Timer-Abmelden beim Schließen (#42).

## v0.9.5 — 2026-08-31

- Startfehler „leeres Fenster" behoben: Fensteraufteilung wird erst nach der Vermessung gesetzt, unplausible Werte werden nicht mehr gespeichert (#41).
- Statusfenster bleibt im Vordergrund (nicht modal) und zeigt nach dem Einsortieren Zielordner bzw. Unsicher-Grund an.

## v0.9.4 — 2026-08-31

- Reparatur der v0.9.3-EXE: zwei Tools fehlten, weil PyInstaller die zur Laufzeit geladenen Plugins nicht sah — seitdem baut und prüft `build_exe.py` jede Release-EXE (#39).
- Statusfenster der Vollautomatik (Aktivitätsring, Zustand, Vorschaubild); alle Posteingang-Ordner werden geleert (#40); Build-Zeitstempel wird eingebettet.

## v0.9.3 — 2026-08-30

- Tools „Dubletten finden" (Hash, Textvergleich, Bild-Fingerabdruck, synchrone Vergleichs-Vorschau) und „Tags ergänzen (KI)" (prüfen → ergänzen, nie ersetzen).
- Personen-Tags aus dem Anschriftenfeld, Vertragspartner im Titel, UND-verknüpfte Suche, OCR-Sprachdaten in der EXE eingebettet (#37).

## v0.9.2 — 2026-08-30

- Vorlagen (`tags_default.json`, `folder_default.json`) werden mit der EXE ausgeliefert; generischer Start-Katalog mit 9 Kategorien.

## v0.9.1 — 2026-08-30

- Praxistest-Fixes: Standardmodell `qwen2.5vl:7b`, neue Ordner landen in den Buchstabengruppen, strengerer Ordner-Abgleich, Datums-OCR-Formen.
- Tag-Katalog wächst automatisch um neue KI-Tags (einsortiert in vorhandene Kategorien).

## v0.9.0 — 2026-08-30

- Erste fertige Windows-EXE (ohne Python-Installation): Vollautomatik/Seniorenmodus bis Schritt 4 — Ablage-Vorschau, Stapelverarbeitung, Watchdog-Vollautomatik mit Angehörigen-Protokoll.
- Telefonbuch-Ordnernamen, Absender-Aliase, Titel-Korrektur über den Sammlungs-Wortschatz, Hilfe-Abschnitt „KI-Server aus der Ferne (Tailscale)".
