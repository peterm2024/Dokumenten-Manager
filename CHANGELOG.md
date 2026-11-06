# Changelog

Kurzfassung je Version, neueste zuerst. Die vollständigen Release-Texte (samt EXE-Download) stehen bei den [GitHub-Releases](https://github.com/peterm2024/Dokumenten-Manager/releases); Angaben wie „FALLSTRICKE #69“ verweisen auf die interne Entwickler-Dokumentation.

## v0.9.24 — 2026-11-06

- Mails importieren: Newsletter mit vielen externen Bildern sehen als PDF deutlich besser aus. In Tabellen steht kein „[Bild nicht geladen]“ mehr, das drückte die Spalten zusammen und ließ Texte überlappen; die Zahl der Bilder steht weiterhin oben im Kopf. Fehler in den Stilen einer Mail setzen die Darstellung von Betreff und Kopfzeilen nicht mehr außer Kraft.
- Fensteraufteilung: Nach „Fensteraufteilung zurücksetzen“ sind „Reset“ und die Trefferzahl wieder sichtbar. Bei sehr großer Schrift bleibt der Vorschau beim ersten Start genug Platz.
- Mails importieren: Manche Newsletter erschienen als PDF nur mit Kopfzeilen und einer leeren Fläche, ihr Text fehlte auch für die Suche. KID prüft jetzt, ob der Text auf den Seiten steht, und nimmt sonst die vereinfachte Darstellung. Schon importierte PDFs bleiben unverändert, die Original-Mail ist dort vollständig eingebettet.
- Hilfe: Die Seite „Was kann das Programm?“ erklärt jetzt auch Mail-Import, Begleitet erfassen, Sammlungs-Wiki und „Frag deine Dokumente“.
- Mails importieren: Entwürfe und Vorlagen werden aussortiert, sie wurden nie abgeschickt.
- Ablage von Mails ohne Absendernamen: Der vordere Teil der Adresse („service@“, „online@“) macht keinen Ordner mehr „ähnlich“. Die Domain findet den Ordner des Absenders jetzt direkt.
- Dokumentenliste: Beim Durchklicken baut sich die Liste nicht mehr nach jedem Klick neu auf. Windows meldete schon das Lesen einer Datei als Änderung.
- Mails importieren: KID findet Thunderbird und klassisches Outlook selbst und bietet sie beim Öffnen des Fensters zur Auswahl an, die eigenen Adressen stehen schon zum Bestätigen da. KID arbeitet dabei nur auf einer Kopie der Mail-Dateien und verändert am Mail-Programm nichts. Die Kopie wird nach dem Import auf Rückfrage gelöscht. Datei oder Ordner lassen sich weiterhin von Hand wählen.
- Mails importieren: mbox-Dateien: Eine Zeile, die im Mailtext mit „From“ beginnt, zerlegt die Mail nicht mehr. In Thunderbird gelöschte Mails, die noch in der Datei stehen, kommen nicht wieder.
- Mails importieren: Bei einer importierten Mail öffnet „Original-Mail öffnen“ (neben „Details“) die eingebettete Mail im Standard-Mailprogramm, mit allen Links und Anhängen. Das Postfach bleibt dabei unberührt.
- Mails importieren: PDF-Anhänge behalten den Bezug zu ihrer Mail. Unter den Eigenschaften steht beim Anhang „Anhang der Mail: Betreff, Datum“, bei der Mail stehen ihre Anhänge, jeweils anklickbar, auch wenn sie in verschiedenen Ordnern liegen. Das gilt auch für schon importierte Mails. Beim ersten Start nach dem Update liest KID dafür einmal die Angaben aller Dokumente neu ein.
- Suche: Ein einzelnes Wort in Anführungszeichen findet nur genau dieses Wort, ohne die Unschärfe: `"Ramen"` findet weder „Rahmen“ noch „Ramensuppe“. Die Zahl der Treffer steht jetzt neben „Reset“.
- Vollautomatik: Weniger Rückfragen bei neuen Ordnern. Namen mit drei Buchstaben reichen jetzt auch bei Scans. Teilen zwei Namen nur ein Wort, etwa den Ort, entsteht ein eigener Ordner statt einer Rückfrage; dafür kann gelegentlich ein Doppelordner entstehen. Steht im Mailkopf nur eine Adresse, heißt der Ordner wie die Domain, außer bei großen Mail-Anbietern.
- Mails importieren: Der Import bleibt nicht mehr an Mails hängen, die sich nicht auf Seiten verteilen lassen, etwa längere Newsletter im Tabellen-Layout. Solche Mails behalten Farben und innere Tabellen, nur das äußere Layout fällt weg; reiner Text ist der letzte Ausweg. Die vollständige Mail ist immer eingebettet.
- Mails importieren: Schon importierte Mails lassen sich nachträglich verwerfen, einzeln oder mit allen Mails ihres Absenders (Zeigen: „importiert“). Die PDFs samt Anhängen kommen in den Papierkorb, die Mails kommen beim nächsten Einlesen nicht wieder.
- Vollautomatik: Weniger Mails in `0_Unsicher`: Firmen mit kurzen Namen aus dem Mailkopf (drei Buchstaben) bekommen ihren Ordner, und PDF-Anhänge ohne brauchbaren Absender gehen zum Absender der Mail.
- Papierkorb: Zwei gleichnamige Dateien aus verschiedenen Ordnern überschreiben sich dort nicht mehr. Bisher ging die zuerst gelöschte verloren. Beim Wiederherstellen kehrt jede unter ihrem alten Namen in ihren Ordner zurück.
- Start: Das Programm startet jetzt auch dann, wenn es nicht per Doppelklick im Explorer, sondern zum Beispiel über die Windows-Suche aufgerufen wird. Vorher suchte es seine Einstellungen je nach Startweg im falschen Ordner und brach mit „Start fehlgeschlagen“ ab.
- Mails importieren: Neue Spalte „Beziehung“ in der Absender-Liste. Ob jemand ein Freund, Kollege oder Geschäftspartner ist, steht in keiner Mail - sagt man es einmal je Absender (aus der Liste wählen oder frei tippen), trennt die KI persönliche Mails viel besser von echter Korrespondenz, auch wenn es zwischen Freunden um eine Sache geht. Nur die Mails dieses Absenders werden danach neu eingestuft. Die Beziehung gilt sofort auch für weitere Adressen derselben Person (gleicher Name oder gleiches „vorname.nachname“), auch in später eingelesenen Mail-Dateien; schon Gesetztes bleibt unverändert.
- Mails importieren: „für die ganze Domain“ gilt jetzt für die Hauptdomain samt Unterdomains (`mail.firma.de` zählt zu `firma.de`), außer bei Mail-Anbietern. Unter „Zeigen“ lässt sich die Prüfliste nach KI-Einstufung filtern, zum Beispiel nur „KI: benachrichtigung“.
- Mails importieren: Mails mit Abmeldelink oder der Kennung „automatische Antwort“ werden nicht mehr ungelesen aussortiert, denn auch Bestellbestätigungen, AGB-Änderungen und Antworten auf eine Kündigung tragen sie. Die KI liest sie jetzt mit und behält außerdem Änderungen an Verträgen und Abonnements, bestätigte An- und Abmeldungen und dem Konto zugeteilte Inhalte. Die KI-Einstufung dauert dadurch länger. Vorhandene KI-Einstufungen werden einmal neu erstellt, Entscheidungen von Hand bleiben.
- Mails importieren: Persönliche Mails von Freunden und Familie stuft die KI jetzt als „privat“ ein. Sie landen weder still im Archiv noch im Müll, sondern in der Prüfliste: unten steht ihre Anzahl, „Zeigen: privat“ filtert sie, „Alle markieren“ (oder Strg+A) und „Übernehmen“/„Verwerfen“ entscheiden alle auf einmal.
- Mails importieren: Mails aus .pst/.ost-Dateien mit leerem oder mehrzeiligem Betreff oder Empfänger zählen nicht mehr als „unlesbar“. Wählt man einen Ordner, in dem keine .eml-Dateien liegen, sagt KID, was dort liegt und wie es weitergeht, statt nur „0 Mails gelesen“ zu melden. „Datei…“ und „Ordner…“ beginnen beim Pfad, der im Feld steht. KI-Einstufung und Import zeigen neben dem Balken, wie weit sie sind und wie lange es noch dauert („101 von 1702, noch ca. 16 min“).

## v0.9.23 — 2026-11-04

- Hinweis: veröffentlicht mit den automatischen Prüfungen, aber ohne den vollständigen manuellen Abschlusstest. Der Mail-Import ist bisher nur mit Test-Postfächern erprobt, noch nicht mit einem großen echten Outlook-Archiv.
- Neue Spalte „Erfasst“ in der Dokumentenliste (einblendbar unter Datei → Einstellungen → Dokumentenliste): wann KID ein Dokument abgelegt oder importiert hat, mit Uhrzeit - so sieht man, was zuletzt dazugekommen ist. Der Wert bleibt auch nach späterem Bearbeiten stehen; ältere Dokumente zeigen den Scan-Zeitpunkt. Dokumente in 0_Unsicher bekommen jetzt schon den KI-Titel, damit man dort sieht, worum es geht (Tags, Datum und Dateiname warten weiter auf die Prüfung).
- Mails importieren (Tools → Vollautomatik → „Mails importieren…“): alte Mail-Archive - Outlook (.pst/.ost), Thunderbird (mbox) oder .eml-Dateien - einmal in die Sammlung übernehmen. KID liest die Quelle nur, sortiert Doppeltes, Newsletter, automatische Antworten und Spam-Ordner aus und zeigt die Absender nach Anzahl: je Absender einmal „immer“, „nie“, „nur Belege und Korrespondenz“ oder „einzeln prüfen“ (gilt auch für spätere Läufe). Den Rest stuft auf Wunsch die KI ein (nur der Text; Unsicheres wird nie verworfen, sondern kommt in die Prüfliste). Übernommene Mails landen als PDF im Posteingang - mit Kopf, Text und der Original-Mail darin -, PDF-Anhänge zusätzlich als eigene Dokumente; die Vollautomatik legt sie ab wie Briefe, mit dem Datum aus der Mail, gesendete Mails beim Empfänger. Ein weitergeleiteter PDF-Anhang wird wie ein Scan beim Aussteller abgelegt. Abbrechen ist jederzeit möglich, ein neuer Lauf macht beim Rest weiter und legt nichts doppelt an.
- Werkzeugfenster bleiben über dem KID-Hauptfenster, ohne es zu sperren - sie verschwinden nicht mehr aus Versehen dahinter. Ein zweiter Aufruf desselben Werkzeugs holt das offene Fenster nach vorn, statt ein zweites zu öffnen (zwei Fenster auf denselben Daten konnten sich gegenseitig alte Stände zurückschreiben).
- Begleitet erfassen (Tools → Vollautomatik → „Begleitet erfassen (Posteingang)…“): der Posteingang Dokument für Dokument - das Hauptfenster zeigt das Dokument, ein schlankes Fenster den Vorschlag (Zielordner, Titel, Datum, Tags; grün = KID wäre sicher, gelb mit Grund). Korrigieren, Return legt ab; das nächste Dokument ist meist schon gelesen. Gedacht für eine neue oder große Sammlung: nichts landet unbemerkt im falschen Ordner. Wer einen Absender in einen Ordner legt, in dem schon ein anders geschriebener Absender liegt, wird gefragt, ob es derselbe ist (dann merkt KID es sich). Unten steht, wie viele der nächsten Dokumente jetzt grün wären - „Rest der Vollautomatik geben“ übergibt den Rest.
- Wiki: Was die KI gelesen hat (Rechtsklick auf ein Dokument → KI-Helfer): zeigt, welche Fakten das Wiki aus dem Dokument gelesen hat, mit Zitat - und lässt sie korrigieren: „Stimmt nicht“, richtiger Wert, „Diese Fläche gilt“, „Person ist dieselbe wie…“ (z.B. ein falsch erkannter Name). Die Korrektur gilt im Wiki und bei „Frag deine Dokumente“; das PDF bleibt unverändert.
- Sammlungs-Wiki: Rückfragen beantworten (Tools → KI-Helfer → „Wiki: Rückfragen beantworten…“). Was die Dokumente nicht verraten - wer „wir“ sind, ob zwei Schreibweisen dasselbe Haus meinen, welche von zwei Flächen gilt -, fragt KID der Reihe nach ab, die wichtigsten zuerst. Jede Antwort wird gemerkt (Datei „eigenes_wissen.json“ im Wiki-Ordner, von Hand änderbar), nie wieder gefragt und bei Wiki-Seiten und Fragen berücksichtigt. Statt der vorgegebenen Knöpfe lässt sich auch mit eigenen Worten antworten (z.B. „Insgesamt 400 m², davon Wohnung 1: 142 m²“); der Text steht dann auf der Seite des Objekts. Flächen werden nur noch mit Flächen derselben Art verglichen (Wohnfläche, Nutzfläche, Grundstück), viele Antwortknöpfe brechen in Reihen um. „Beantwortete…“ zeigt alle Antworten; jede lässt sich ändern oder löschen (dann wird wieder gefragt). Gleiche Flächen stehen auf der Objektseite nur noch einmal, mit allen Dokumenten, und einheitlich geschrieben („142 m²“). Beträge und Längen, die die KI für eine Fläche hielt (z.B. weil die Texterkennung das „m²“ verschluckt hatte), zählen nicht mehr als Fläche. Zwei ähnlich geschriebene Straßen (z.B. „Bergstr. 3“ und „Burgstr. 3“) legt das Wiki nicht mehr still zusammen, sondern fragt nach; nur ein einzelner Lesefehler wird ohne Frage zugeordnet. KID fragt nie ungefragt; die Wiki-Hauptseite zeigt, wie viele Rückfragen offen sind.
- Frag deine Dokumente (Tools → KI-Helfer, braucht das eingeschaltete Sammlungs-Wiki): eine Frage in Alltagssprache, z.B. „Was hat der Kaminkehrer 2024 gekostet?“. KID sucht die passenden Dokumente und antwortet in etwa 20 Sekunden aus deren schon gelesenen Fakten; jede Angabe nennt ihr Dokument (ein Klick zeigt es), Zahlen, die in keinem gefundenen Dokument stehen, sind markiert. Die Antwort kennt auch das Objekt eines Dokuments (z.B. die Verbrauchsstelle einer Gasrechnung). Passende Dokumente, die noch nicht gelesen sind, lassen sich per Knopf nachlesen. Fragen und Antworten werden nicht gespeichert.
- Ablage-Vorschau: Ein Dokument, das automatisch abgelegt würde (grün), lässt sich per Klick auf „Ergebnis“ zurückstellen - es wird gelb und kommt beim Einsortieren in den Unsicher-Ordner, mit dem Grund „von Hand zurückgestellt“; ein erneuter Klick nimmt das zurück. Die Zielordner-Auswahl zeigt jetzt auch Ordner, die erst nach dem Start der Analyse angelegt wurden.
- Fenster-Platzierung: Das Statusfenster der Vollautomatik bleibt an seinem Platz, während man in einem anderen Programm arbeitet (es sprang beim Wachsen auf den Monitor mit dem Mauszeiger). Neue KID-Fenster öffnen sich nur noch am Mauszeiger, wenn man gerade in KID arbeitet - sonst mittig über dem KID-Hauptfenster.
- Sammlungs-Wiki (ausdrücklich einzuschalten unter Datei → Einstellungen → „Wiki“, je Sammlung): KID merkt sich je Dokument geprüfte Fakten - Beträge, Verträge, Verbräuche, Personen mit Rolle, Flächen -, jeweils mit dem Zitat aus dem Dokument; Zugangsdaten werden nie übernommen. Tools → KI-Helfer → „Wiki: Bestand nachlesen…“ liest die vorhandenen Dokumente (etwa 15 Sekunden je Dokument, abbrechen und später fortsetzen möglich). Neu abgelegte Dokumente (Vollautomatik, Ablage-Vorschau, Posteingang verarbeiten) liest das Wiki von selbst, sobald die Vollautomatik nichts zu tun hat - die Ablage selbst wird dadurch nicht langsamer. Die PDF-Dateien bleiben unverändert; ausschalten pausiert nur, gesammelt wird im Ordner „Wiki“ neben der Sammlung. Tools → KI-Helfer → „Wiki öffnen“ zeigt die Wiki-Seiten im Browser: Objekte mit Flächen und Personen, Verträge mit Beitragsreihe und Status, Zähler, Personen mit Rollen, je Ordner Kennungen und Beträge je Jahr, dazu wenige Rückfragen - jeweils mit den Dokumenten, aus denen es stammt.

## v0.9.22 — 2026-11-02

- Hinweis: veröffentlicht mit den automatischen Prüfungen, aber ohne den vollständigen manuellen Abschlusstest.
- KI-Server per Doppelklick wecken: Ist der Server aus (roter Punkt rechts in der Suchleiste), schickt ein Doppelklick ein Wake-on-LAN-Signal; der Punkt leuchtet orange, bis der Server antwortet. Dafür einmal die MAC-Adresse des Server-PCs eintragen (Einstellungen → KI-Server → „Wecken (MAC)“). Geht nur im selben Heimnetz. Die MAC wird schon beim Eintippen oder Einfügen geprüft; die MAC einer virtuellen Maschine (lässt sich nicht wecken) wird sofort rot gewarnt.
- Einstellungsfenster: lässt sich nicht mehr kleiner ziehen, als sein Inhalt braucht.
- Große Ordner öffnen sich schneller: Titel, Tags und Daten kommen aus dem Suchindex, solange ein PDF unverändert ist - nur neue oder geänderte PDFs werden noch geöffnet. Ein Ordner mit 5.000 Dokumenten braucht etwa 0,3 statt 2,3 Sekunden. Direkt nach dem Rechnerstart, wenn die PDFs noch nicht im Speicher liegen, dauerte allein das Lesen der PDFs bisher über eine halbe Minute; diese Zugriffe entfallen jetzt.
- Suchfeld zeigt den Stand: dezent gelb, solange der getippte Text noch nicht mit Return gesucht wurde, dezent grün, wenn die Liste genau diese Suche zeigt.
- Suche startet erst mit Return: Tippen, Pfeiltasten oder das Abtippen aus einem offenen Dokument lösen keine Suche mehr aus (vorher lief sie bei jeder Taste und nach Return sogar zweimal). Ein geleertes Suchfeld setzt die Suche sofort zurück; Klicks auf „Inhalt (OCR)“, Filter-Tags und Tag-Vorschläge suchen wie bisher sofort. Die Trefferliste wird nur noch neu gezeichnet, wenn sich die Treffer wirklich ändern - kein Flackern mehr beim Weiterklicken.
- Suche mit „Inhalt (OCR)“ in großen Sammlungen deutlich schneller: Tippfehler, seltene Wörter und Wörter ohne Treffer brauchen bei 20.000 Dokumenten etwa 1 bis 1,8 statt 3,5 bis 4,3 Sekunden - bei unveränderten Treffern. Die unscharfe Suche vergleicht dafür jedes verschiedene Wort der Sammlung nur noch einmal statt jedes Wort jedes Dokuments.
- Vollautomatik mit Zweitmeinung zur Ordnerwahl rund 40 % schneller: Die beiden KI-Modelle passen nicht gleichzeitig in den Grafikspeicher, deshalb liest die Vollautomatik jetzt 10 Dokumente am Stück, holt danach alle Zweitmeinungen und legt dann ab - statt je Dokument zweimal das Modell zu wechseln (403 Dokumente: 67 statt 109 Minuten). Das Statusfenster zeigt die Phase („Zweitmeinung zur Ordnerwahl…“, „Wird geprüft und einsortiert…“). Ablage-Vorschau und „Posteingang verarbeiten“ arbeiten ebenso stapelweise.
- Dokumentdatum: Dokumente ohne gespeichertes Datum zeigen in der Liste (und im Von/Bis-Filter der Suche) das aus dem Dokument gelesene Datum statt des Datei-Datums; im Datumsfeld steht es orange, solange es nur vermutet ist. Mit Auto-Save wird es gespeichert, sobald man zum nächsten Dokument wechselt. Ein vermutetes Datum ist orange hinterlegt; zum Korrigieren tippt man in der Dokumentenliste einfach das richtige Datum (landet im Datumsfeld, Return speichert, Esc holt den Vorschlag zurück). Speichern von Titel/Tags (auch automatisch) und der Titel-Vorschlag (KI) schreiben es mit - vorher zeigte die Dokumentenliste z.B. bei heruntergeladenen Kontoauszügen den Download-Tag, obwohl unten das richtige Datum stand.
- Eigenschaften: neue Zeile „Status“ unter Details erklärt, warum ein Dokument auffällt - von der Vollautomatik zur Prüfung vorgelegt (mit Grund; die Vollautomatik merkt ihn dafür im PDF), unbearbeitet (orange in der Liste) oder Datum nur vermutet. Mit Auto-Save bekommt ein Dokument seine Dokument-ID schon beim Anklicken, nicht erst beim ersten Speichern. Neues Werkzeug Tools → Aufräumen → „Gründe in 0_Unsicher nachtragen“ holt den Grund für Dokumente, die schon vorher dort lagen, einmalig aus dem Vollautomatik-Protokoll.
- Kurzbefehl-Fenster: Ansicht → „Kurzbefehle anzeigen (F1)“ (oder F1) blendet ein kleines Fenster ein, das die Tasten und Mausaktionen des Bereichs zeigt, in dem Cursor oder Maus gerade sind (Liste, Ordnerbaum, Tag-Baum, Vorschau, Eingabefelder …), darunter die überall gültigen. Es lässt sich verschieben und merkt sich Platz und Zustand. In der Dokumentenliste blättern ←/→ und Bild↑/↓ die Vorschau, ohne dass die Liste mitscrollt; im Ordner- und Tag-Baum gehören die Tasten dem Baum (Auf-/Zuklappen). Ein Sprung über das Ende landet auf der ersten bzw. letzten Seite (Bild↓ tat bei kurzen Dokumenten nichts). Pos1/Ende springen in der Dokumentenliste auf das erste/letzte Dokument, im Ordner- und Tag-Baum auf den ersten/letzten Eintrag, in der Vorschau auf die erste/letzte Seite.
- Tags mit Alt auf ein anderes Dokument übertragen: Die Menüleiste nennt die übertragenen Tags; hat das Ziel schon alle, sagt ein Hinweis das (vorher geschah scheinbar nichts). In einer Trefferliste zeigt das Ziel die neuen Tags sofort, und Titel/Tags-Feld werden beim Anklicken aus dem PDF gefüllt statt aus der Listenzeile (eine veraltete Zeile konnte per Auto-Save alte Tags zurückschreiben, FALLSTRICKE #87).
- Titel-Vorschlag (KI): Schließen des Fensters, während die Vorschläge noch laden, führt nicht mehr zu „Interner Fehler“; die KI hört dann auch auf.
- Vollautomatik in einer neuen Sammlung: Ein Ortsname im Absender („Landratsamt Musterstadt“) führt nicht mehr dazu, dass der erste Ordner mit diesem Ort („Bürgerbüro Musterstadt“) vorgewählt wird - das Dokument wird weiter zur Prüfung vorgelegt, vorgewählt ist dann der neue Ordner. Dafür merken sich Vollautomatik und Ablage-Vorschau bis zum Programmende die Orte der bisher gelesenen Dokumente (in unserer Messung sanken die falschen Vorwahlen von 31 auf 4).
- „⏱️ Zuletzt benutzt“ gehört jetzt zur Sammlung (liegt im Daten-Ordner wie der Tag-Katalog): eine neue Sammlung beginnt mit einer leeren Liste statt mit den Tags der alten. Die bisherige Liste übernimmt die Sammlung, die nach dem Update als erste geöffnet wird.
- Tag-Hygiene: neuer Knopf „Standard-Synonyme übernehmen…“ trägt die mitgelieferten Synonyme (z.B. „Müllabfuhr“ → „Müll“) auch in Sammlungen nach, die vor v0.9.21 angelegt wurden - nur unter vorhandenen Tags, eigene Tags gleichen Namens bleiben unberührt. Tragen Dokumente schon einen der Texte, wird das Ersetzen gleich angeboten. Ebenfalls neu: „Sammel-Tags zerlegen…“ macht aus älteren Tags wie „Musterstraße 1 u. 3“ ein Tag je Objekt - in den Dokumenten und im Katalog, nach derselben Regel wie bei neuen Dokumenten. Das Fenster ist dafür in zwei beschriftete Bereiche geteilt („Katalog aufräumen“ und „Selten benutzte Tags“); Werkzeuge, die in viele Dokumente schreiben, fragen immer vorher, und zu entfernende Tags werden per Kästchen ☐/☒ angekreuzt.

## v0.9.21 — 2026-10-28

- Neues Standardmodell `qwen3.5:9b` (rund 7 GB): legt in unseren Messungen mit 403 Dokumenten deutlich seltener in den falschen Ordner ab als `qwen2.5vl:7b` und ist auf der Grafikkarte gleich schnell. Bestehende Installationen behalten ihr eingetragenes Modell; Umstieg: `ollama pull qwen3.5:9b` und unter Datei → Einstellungen → KI-Server eintragen. Neuere Modelle, die vor der Antwort „nachdenken“, werden dabei abgeschaltet (sonst minutenlange Antworten).
- Ablage-Gedächtnis: Die Vollautomatik lernt aus dem Bestand, in welchem Ordner die Dokumente eines Absenders liegen (ab 2 Dokumenten, mindestens zwei Drittel im selben Ordner) - auch dort, wo kein Namensvergleich hilft („Landesbrandversicherung“ liegt bei „Versicherungskammer“). Dafür merkt sich jedes abgelegte Dokument seinen Absender im PDF; neues Werkzeug Tools → Aufräumen → „Absender nachlesen“ holt das für den Bestand einmalig nach, Tools → Vollautomatik → „Ablage-Gedächtnis ansehen“ zeigt, was gelernt wurde. Verschiebt man ein Dokument, zieht das Gedächtnis mit.
- Keine Doppelordner mehr: Bevor die Vollautomatik einen neuen Ordner anlegt, prüft sie, ob ein ähnlicher schon existiert - dann wird das Dokument zur Prüfung vorgelegt, der ähnliche Ordner ist vorgewählt. Kürzel-Ordner wie „HDI“ oder „WGV“ werden im Absender erkannt; ein Absender, der nur als Kürzel aus der Adresszeile kommt, wird nie zum neuen Ordner. Ähnelt der Name nur über ein allgemeines Wort („Versicherung“), ist der neue Ordner vorgewählt statt eines fremden. Gekürzte Ordnernamen enden nicht mehr mit einer offenen Klammer.
- Optionale Zweitmeinung zur Ordnerwahl (Datei → Einstellungen → KI-Server → „Ordnerwahl“, Standard aus): ein zweites KI-Modell prüft jeden Zielordner; widerspricht es deutlich, wird das Dokument zur Prüfung vorgelegt statt still abgelegt.
- Weniger Tag-Wildwuchs: Betrifft ein Dokument mehrere Hausnummern („1 u. 3“), gibt es je Objekt ein eigenes Tag; neue Tags mit Ziffern, Satzfetzen, englischen Wörtern oder dem Absendernamen werden verworfen (mit Grund im Protokoll); Schreibvarianten derselben Adresse oder Person warten nicht mehr getrennt. Neue Sammlungen bringen 38 Synonyme mit (z.B. „Haftpflichtversicherung“ → „Haftpflicht“).
- Vollautomatik: Liegt beim Start schon Post im Posteingang, beginnt sie sofort statt nach einer Minute. Ist der KI-Server nicht erreichbar, steht das einmal im Protokoll, ebenso seine Rückkehr.
- Dateinamen wie `15012024_Rechnung.pdf` (TTMMJJJJ) liefern jetzt auch ein Datum; gekürzte Ordnernamen enden nicht mehr auf „und“. Das Mausrad blättert in der Vorschau auch dann, wenn der Cursor gerade im Datumsfeld steht.

## v0.9.20 — 2026-10-25

- Titel-Aufräumen (OCR): Spalte „Datei“, senkrechte Scrollleiste, Klick auf eine Zeile zeigt das Dokument im Hauptfenster (FALLSTRICKE #73), Knopf „KI-Titel vorschlagen“ (erste Seite per KI wie im Dateinamen-Tool), Vorschläge werden nicht mehr automatisch angehakt. Kauderwelsch-Erkennung zählt Laute statt Buchstaben (sch/ch/ck/pf/tz/st) und erkennt den e→c-Lesefehler - ehrliche Titel wie „Rechtsschutz“ oder „Abschlagsplan“ melden nicht mehr.
- Vorschau: Seitenwechsel ohne graue Pause - die neue Seite ist sofort da und gleitet mit der alten zusammen ein. Die Bildlaufleiste zeigt jetzt die Position im ganzen Dokument (Ziehen springt zur Seite, kurz „Seite x von N“), beim Zoomen erscheint bei Bedarf eine waagerechte Leiste.
- Nach dem Umbenennen (F2) bleibt die umbenannte Datei markiert, statt auf die erste Zeile zu springen.
- Tags mit Alt auf ein anderes Dokument übertragen behält die Reihenfolge: dessen Tags bleiben vorne, die neuen kommen dahinter (vorher durcheinandergewürfelt).
- Tags-Feld und Suchfeld: Return übernimmt einen Vorschlag der Liste nur noch, wenn er mit Pfeil runter/hoch angewählt ist - ein neu getipptes Tag wie „Test“ wird nicht mehr ungefragt zu „Testament“. Die Tags im PDF enden nicht mehr mit einem Komma.
- Ordner reagieren wieder beim ersten Klick: mit Haken „Inhalt (OCR)“ oder nach dem Anklicken eines Suchtreffers wurde der nächste Ordnerklick verschluckt (FALLSTRICKE #74).
- Ein Dokument aus der Trefferliste auf einen Ordner ziehen lässt die Suche stehen; das Dokument bleibt markiert und zeigt seinen neuen Ordner (vorher wechselte die Ansicht in den Ordner und die Suche war weg).
- Papierkorb: „Wiederherstellen“ legt ein Dokument zurück in den Ordner, aus dem es gelöscht wurde (vorher immer in den Hauptordner), die Meldung nennt den Ordner. Wird der Papierkorb ausgeblendet, während man ihn ansieht, wechselt die Ansicht in den Hauptordner.
- Dokumentenliste: Die Spalte „Tags“ gehört zur Standard-Ansicht (erster Start und „Fensteraufteilung zurücksetzen“); die Meldung nach dem Zurücksetzen verlangt keinen Neustart mehr - alles wirkt sofort.
- Ablage-Vorschau: Im Dialog „Zielordner wählen“ bricht die Option „Alle Dokumente von … — auch künftige“ um, statt bei langen Absendernamen rechts abgeschnitten zu werden.
- Dokument-ID: Jedes Dokument bekommt beim ersten Speichern eine kurze, gut lesbare ID (z.B. K7M4-Q2XP), um es in Notizen und Rückmeldungen eindeutig zu nennen. Sie steht in den Eigenschaften, bleibt beim Umbenennen und Verschieben gleich, und die Suche findet das Dokument über die ID (auch nur deren Anfang, Groß-/Kleinschreibung und Bindestrich egal). Neues Werkzeug Tools → Aufräumen → „Dokument-IDs vergeben…“ holt den Bestand nach und gibt Kopien, die die ID ihres Originals mitgebracht haben, eine eigene.
- Speichern: Dateien mit Sonderzeichen wie ● oder □ im Namen ließen sich bei umgeleiteter Programmausgabe nicht speichern (FALLSTRICKE #78).
- Große Schrift (125 %): Fenster, die nahe am unteren Bildschirmrand aufgehen, ragen nicht mehr mit der Fußzeile über den Rand; Datum in der Dokumentenliste und Dokumentenzahl im Ordnerbaum werden nicht mehr abgeschnitten (Spaltenbreiten wachsen mit).
- Suche: Ein Dokument, das nicht unter den Treffern steht, verschwindet aus Vorschau und Eigenschaften. Findet eine Textsuche ohne „Inhalt (OCR)“ nichts, erklärt ein Hinweis in der Vorschau, wie man im Dokumenttext sucht.
- Vollautomatik: Ein frisch gescanntes Dokument wird nach gut 10 Sekunden abgelegt statt erst nach rund einer Minute (FALLSTRICKE #75).

## v0.9.19 — 2026-09-15

- Eigenschaften-Bereich als Tabelle mit Linien: Titel, Tags und Datum als weiße bearbeitbare Zellen, alle übrigen Angaben als graue schreibgeschützte Zellen (markieren/kopieren, Rechtsklick „Kopieren“ / „Alles kopieren“, Tooltip bei abgeschnittenem Wert). Kurze Angaben teilen sich eine Zeile; ausgeklappt braucht die Tabelle weniger Höhe als der alte Textblock, und der Bereich entfaltet sich nach oben (FALLSTRICKE #72).
- Einstellungen → neuer Reiter „Eigenschaften“: eine Liste mit zwei Trennern bestimmt Reihenfolge und Sichtbarkeit der Felder (immer / nur mit „Details“ / nie; ▲▼ oder Alt+Hoch/Runter), + und − die Breite je Feld (⅛, ¼, ½, ¾, 1). Die Tabelle folgt sofort, „Standard“ stellt die Auslieferung her.
- Tags per Drag & Drop auf ein anderes Dokument übertragen geht nur noch mit gedrückter Alt-Taste (Fehlgriff-Schutz); das Drag-Fensterchen zeigt „Tags übertragen →“, ohne Alt erscheint ein kurzer Hinweis in der Menüleiste.
- Hilfe → Schnellstart: fehlende Tastenkürzel ergänzt (Greifer-Doppelklick, Tag für mehrere Dokumente, Spaltensortierung, Esc im Tag-Suchfeld, Ordnerbaum); Pfad in den Eigenschaften einheitlich mit Backslashes.

## v0.9.18 — 2026-09-14

- Hilfe → „Auf neue Version prüfen…“: fragt die Releases-Seite ab, vergleicht die Versionsnummer und bietet bei einer neueren die Download-Seite im Browser an. Dieselbe Prüfung läuft still beim Programmstart und meldet sich nur, wenn es etwas Neueres gibt (abschaltbar unter Einstellungen → Allgemein; es werden keine Angaben über dich übertragen).
- Programmsymbol: eigenes Icon (Dokumentblatt mit Tag-Anhänger) in Titelleiste, Taskleiste und für die EXE-Datei.
- Downloads und Beta-Test laufen ab jetzt über das öffentliche Repository peterm2024/Dokumenten-Manager (README mit Screenshot, Beta-Leitfaden, Changelog, Releases); der Quellcode bleibt vorerst privat.

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

- Windows-Textgröße 125 % (Barrierefreiheit): Fenstergrößen, Umbrüche und Spaltenbreiten wachsen jetzt auch mit der Textgröße, nicht nur mit der Bildschirm-Skalierung; Zeilen in Bäumen und Tabellen sind so hoch wie die Schrift (keine abgeschnittenen Unterlängen); in den Einstellungen bleiben Fußzeile mit „Schließen“, „Ändern…“ und „Altbestand nachziehen“ immer sichtbar; Reset-/Speichern-Knopf und Statusfenster nutzen die Standardschriftgröße (FALLSTRICKE #69).
- Vollautomatik: nach jedem abgelegten Dokument wird der angezeigte Posteingang nur noch einmal neu gelesen statt zweimal (#68).
- KI-Server → „Verbindung testen“ meldet, ob das Modell auf der Grafikkarte oder still auf der CPU rechnet, und warnt bei CPU-Betrieb (häufige Ursache für Zeitüberschreitungen, #67).

## v0.9.13 — 2026-09-12

- Menü-Hilfe: zu jedem Menüeintrag „Was“ und „Wofür“ — als Fensterchen, das erscheint, wenn der Mauszeiger gut eine Sekunde auf einem Eintrag verweilt (auch in Untermenüs und Rechtsklick-Menüs, abschaltbar unter Datei → Einstellungen), und als neuer Hilfe-Reiter „Menü-Übersicht“; Werkzeuge bringen ihre Erklärung selbst mit (FALLSTRICKE #65: Tk-Menü-Klone).
- Dubletten finden: Spalte „Vorschau“ zeigt, welche Zeile links und welche rechts verglichen wird, Kopfzeilen „Markiert:“/„Vergleich:“, Shift+Klick wählt das rechte Dokument; beide Vorschauen bleiben gleich breit (#66).
- Dubletten-Gedächtnis: Doppelklick auf die Gruppenzeile (oder „Gruppe als geprüft merken“) merkt eine geprüfte Gruppe als „keine Dublette“ und blendet sie aus — dauerhaft über Dokument-IDs (`KID_ID`, einmalig ins PDF eingebrannt, im Details-Block sichtbar); Häkchen „Geprüfte Gruppen anzeigen“ und „Prüfung aufheben“ machen es rückgängig, ein neu hinzukommendes Dokument lässt die Gruppe wieder erscheinen.

## v0.9.12 — 2026-09-11

- Aktivitätsanzeige rechts neben „Hilfe" in der Menüleiste: zeigt in Klartext, was gerade läuft („Lese Ordner … (12 Dateien)…", „Suche läuft…", „Vorschau wird gezeichnet…", „Speichere …", „KI antwortet … (14 s)", „Wartet auf deine Antwort: „…""), im Ruhezustand „Bereit" — auf langsamen Rechnern sieht man so, dass es weitergeht.
- Suchtreffer im Dokument: bei aktiver Suche markiert die Vorschau die Suchbegriffe hellblau mit blauem Rahmen (Datum bleibt gelb/rot), springt beim Anklicken eines Treffers auf die erste Fundstelle und nennt in der Titelleiste Trefferzahl bzw. Trefferseite; Treffer nur in Name/Titel/Tags oder im verbesserten Index-Text werden als „nicht im Seitentext" ausgewiesen.
- Phrasensuche: `"Max Mustermann"` in Anführungszeichen findet nur den zusammenhängenden Text (nicht „Mustermann, Max"), Zeilenumbruch zählt als Leerzeichen; ohne Anführungszeichen wie bisher jedes Wort für sich. Hilfe-Absatz „Wiederfinden" ergänzt.
- Behoben: unscharfe Suche traf Bruchstücke von OCR-Müll („Kostal" fand „Sta(l^'tc^ke" = Stadtwerke) — kürzere Wörter brauchen jetzt eine höhere Ähnlichkeit (#64).

## v0.9.11 — 2026-09-11

- Dateinamen unter Kontrolle: der bisherige Name wird beim ersten Umbenennen als „Originalname" ins PDF eingebrannt (Details-Block); Umbenennen beim Ablegen abschaltbar; neues Tool „Dateinamen aufräumen" (Vorschlag `JJJJMMTT_Titel.pdf`, nur Angehaktes wird umbenannt, Originalnamen wiederherstellen, Müll-Titel orange, „KI-Titel vorschlagen").
- Vollautomatik: Objekt-Alias ordnet absenderlose Eigenbelege (Notizen, Zählerstände) per Zielordner-Klick ihrem Haus zu; Rücksendezeilen wie „Finanzamt Musterstadt, Postfach 1234" werden gekürzt und reine Kürzel nie zum neuen Ordner.
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
- Objekt im Titel („… Gebäudeversicherung Musterstraße 1"); Ort und Objekt als getrennte Schlagwörter.
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
