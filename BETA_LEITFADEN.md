# Beta-Test: Leitfaden für Tester

Danke fürs Mitmachen. Diese Seite ist alles, was du zum Loslegen brauchst.

## 1. Was das Programm tut

Der Dokumenten-Manager verwaltet PDF-Dokumente (Rechnungen, Verträge, Bescheide, Scans) in einer normalen Ordnerstruktur auf deinem Rechner. Titel, Tags und Datum schreibt er **direkt in die PDF-Dateien** (in deren Metadaten - der Inhalt bleibt unverändert). Es gibt keine Datenbank, keinen Online-Dienst, keine Anmeldung: Deine Dokumente bleiben, wo sie sind, und alles läuft auf deinem PC. Optional hilft eine lokale KI beim Beschriften und Einsortieren.

## 2. Einrichtung (5 Minuten)

1. `DokumentenManager.exe` von der [Releases-Seite](https://github.com/peterm2024/Dokumenten-Manager/releases) herunterladen und in einen **eigenen Ordner** legen (z.B. `C:\Programme-Portabel\DokumentenManager\`). Das Programm legt seine Einstellungen daneben ab; es braucht keine Installation.
2. Beim ersten Start fragt Windows SmartScreen nach („Weitere Informationen" → „Trotzdem ausführen"). Die Datei ist nicht signiert, das ist bei einem Einzelentwickler-Programm normal.
3. Das Programm bietet an, einen Dokumentenordner unter `Dokumente\KID` anzulegen. „Ja" ist für den Test der einfachste Weg.
4. **Wichtig:** Zum Kennenlernen bitte mit **Kopien** deiner Dokumente arbeiten - das Programm schreibt in die Dateien. Gelöschte Dateien landen im Papierkorb der Sammlung, nicht im Nichts.
5. Hilfe → Schnellstart lesen (2 Minuten), dann ein paar PDFs in den Ordner `0_Posteingang` legen.

## 3. KI - mit oder ohne

Alles außer den KI-Funktionen läuft ohne weitere Software. Für Titelvorschlag, Tags ergänzen, Ablage-Vorschau und Vollautomatik braucht es ein [Ollama](https://ollama.com) auf diesem PC oder einem Rechner im Heimnetz. Steht der Server woanders, etwa bei Angehörigen, verbindet [Tailscale](https://tailscale.com) beide Rechner privat und verschlüsselt, ohne Portfreigabe am Router - im Programm erklärt unter Hilfe → „KI-Server aus der Ferne (Tailscale)".

Einrichtung auf dem eigenen PC:

1. Ollama für Windows installieren (läuft als Hintergrunddienst, hört nur auf diesem PC).
2. In der Eingabeaufforderung das Modell laden (einmalig, rund 6 GB): `ollama pull qwen2.5vl:7b`
3. Im Programm unter Datei → Einstellungen → KI-Server „Verbindung testen" klicken. Der Punkt rechts in der Suchleiste wird grün.

Wie schnell die KI antwortet, hängt fast nur von der Grafikkarte ab. Richtwerte je Dokument:

| Rechner | Dauer je Dokument | Bemerkung |
|---|---|---|
| nur Prozessor (ohne Grafikkarte) | 2 bis 10 Minuten | mind. 16 GB Arbeitsspeicher; in den Einstellungen „KI ohne Grafikkarte zulassen" ankreuzen |
| Grafik im Prozessor (integriert) | wie nur Prozessor | Ollama nutzt integrierte Grafik unter Windows in der Regel nicht |
| eigene Grafikkarte mit 8 GB | 20 bis 60 Sekunden | Modell passt gerade |
| eigene Grafikkarte mit 16 GB | 5 bis 20 Sekunden | alles im Grafikspeicher - der gedachte Normalfall |

Ohne Grafikkarte ist die KI nichts zum Zuschauen, aber die Vollautomatik läuft unbeaufsichtigt - ein Stapel Scans ist dann über Nacht abgelegt. Ohne KI ist das Programm trotzdem vollständig nutzbar; die KI-Einträge im Menü sind dann ausgegraut.

## 4. Was wir gerne getestet hätten

- **Ersteinrichtung und erster Eindruck:** Kommst du ohne Erklärung zurecht? Wo hast du gestutzt?
- **Beschriften:** Titel, Tags, Datum vergeben; Tags aus dem Katalog links unten zuweisen; Auto-Save.
- **Suchen:** Text, Tags (im Suchfeld werden bekannte Tags blau), Datum („2021" oder „07.2021" reicht), Inhalt (OCR).
- **Ordnen:** Dateien per Maus verschieben, umbenennen, löschen (Papierkorb), Standard-Ordnerstruktur.
- **Werkzeuge:** Dubletten finden, Dateinamen aufräumen, PDF-Inspektor.
- **Mit KI:** Titel vorschlagen, Tags ergänzen, Ablage-Vorschau (zeigt nur an, ändert nichts), dann die Vollautomatik mit dem Posteingang.
- **Auf deinem Bildschirm:** Skalierung 125 % oder größere Windows-Textgröße - ist alles lesbar, wird etwas abgeschnitten?

## 5. Bekannte Grenzen

- Nur PDF-Dateien. Andere Dateitypen werden nicht angezeigt.
- Windows. Andere Systeme sind nicht getestet.
- Die KI liest manche Scans falsch (Ziffern, kleine Schrift); Neues im Tag-Katalog landet unter „Neu (KI)" und will gelegentlich aufgeräumt werden.
- Die Hilfetexte sind noch nicht in der Endfassung.
- Es gibt keine automatische Aktualisierung. Das Programm sagt aber beim Start Bescheid, wenn auf der Releases-Seite eine neuere Version liegt (auch von Hand: Hilfe → „Auf neue Version prüfen…"); die neue EXE einfach über die alte kopieren, die Einstellungen bleiben erhalten.

## 6. Rückmeldung

Am hilfreichsten ist eine Rückmeldung mit diesen drei Dingen:

1. **Versionsnummer** aus der Titelleiste (z.B. „v0.9.17").
2. **Was du getan hast und was stattdessen passiert ist** - gerne mit Bildschirmfoto.
3. Die **Protokolldatei**: Datei → „Protokoll-Datei (Log) öffnen", Inhalt kopieren oder Datei anhängen. Erscheint ein Fenster „Interner Fehler", bitte dort „Ja" wählen, dann ist das Protokoll schon offen. Startet das Programm gar nicht erst, liegt neben der EXE eine Datei `startfehler.txt`.

Rückmeldungen als [GitHub-Issue](https://github.com/peterm2024/Dokumenten-Manager/issues) oder direkt an den Entwickler. Auch „hat alles funktioniert" ist eine wertvolle Rückmeldung.
