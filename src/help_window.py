import os
import sys
import tkinter as tk
import webbrowser
from datetime import datetime
from tkinter import ttk
from ui_utils import UIUtils
import menue_hilfe

APP_NAME = "Dokumenten-Manager (KI Edition)"
# Release-Version (Git-Tag "v<Version>", GitHub-Release mit der gebauten EXE, siehe README "Release bauen")
APP_VERSION = "0.9.29"


def build_stempel():
    """
    Build-Kennung für Titelleiste und Hilfe (Nutzerwunsch 30.08.2026: auf einen Blick
    sehen, welche Version läuft - gerade beim Fernwarten über RustDesk). In der EXE
    der Erstellungszeitpunkt der Datei (PyInstaller schreibt sie beim Build neu),
    im Quellcode-Betrieb 'Entwicklung'.
    """
    if not getattr(sys, "frozen", False):
        return "Entwicklung"
    # Bevorzugt der beim Build eingebettete Stempel (build_stempel.txt, schreibt build_exe.py):
    # die Datei-Änderungszeit der EXE ist nach einem GitHub-Download die DOWNLOAD-Zeit,
    # nicht die Build-Zeit (Praxisfund 31.08.2026).
    try:
        import app_paths
        with open(app_paths.bundled_default_path("build_stempel.txt"), encoding="utf-8") as f:
            wert = f.read().strip()
        if wert:
            return wert
    except OSError:
        pass
    try:
        return datetime.fromtimestamp(os.path.getmtime(sys.executable)).strftime("%Y-%m-%d %H:%M")
    except OSError:
        return "?"


def fenstertitel():
    """Titel des Hauptfensters: Name, Version und Build."""
    return f"{APP_NAME} v{APP_VERSION} (Build {build_stempel()})"

# ==========================================
# HILFE-INHALTE
# ==========================================
# Struktur statt Fließtext: Jeder Tab ist eine Liste von Blöcken (stil, inhalt).
# Stile: "h1" = Hauptüberschrift, "h2" = Zwischenüberschrift, "p" = Absatz,
# "kbd" = Tastenkürzel-Tabelle (Liste von (Taste, Beschreibung)-Paaren).
# So bleibt der Text leicht pflegbar und die Darstellung übernimmt _render_blocks.

TAB_QUICKSTART = [
    ("h1", "🚀	In fünf Schritten startklar"),

    ("h2", "1. Ablageort festlegen"),
    ("p", "Beim allerersten Start bietet das Programm an, den Ordner \"Dokumente\\KID\" "
          "anzulegen und fertig einzurichten — ein Klick auf Ja genügt. Alternativ wähle "
          "unter Datei → \"Sammlung öffnen...\" einen eigenen Ordner; Datei → "
          "\"Standard-Ordnerstruktur in der Sammlung anlegen...\" legt darin die fertige Registerstruktur an. "
          "Der Knopf \"🚀 Vollautomatik einschalten\" unten in diesem Fenster startet die "
          "automatische Ablage neuer Scans — sie bleibt auch nach einem Neustart an."),

    ("h2", "2. Dokumente hineinlegen"),
    ("p", "Lege deine PDF-Dateien einfach im Windows-Explorer in diese Ordner — das "
          "Programm bemerkt neue Dateien von selbst. Innerhalb des Programms kannst du "
          "Dateien mit der Maus von Ordner zu Ordner ziehen."),
    ("p", "Gut zu wissen: Titel, Tags und Datum werden direkt in die PDF-Dateien geschrieben "
          "(in deren Metadaten - der Inhalt bleibt unverändert, und die Angaben bleiben auch "
          "ohne dieses Programm erhalten). Wer das Programm erst kennenlernen möchte, arbeitet "
          "am besten mit Kopien seiner Dokumente. Gelöschte Dateien landen im Papierkorb der "
          "Sammlung, nicht im Nichts."),

    ("h2", "3. Dokument beschriften"),
    ("p", "Klicke ein Dokument an: Rechts erscheinen die Seitenansicht sowie Felder für "
          "Titel, Tags und Datum. Mit eingeschaltetem \"Auto-Save\" wird alles "
          "automatisch gespeichert — Tags, sobald du mit Enter bestätigst oder "
          "das Feld verlässt. Orange angezeigte Dokumente sind noch unbeschriftet."),

    ("h2", "4. Tags vergeben"),
    ("p", "Links unten findest du deinen Tag-Katalog als Baum: Oberbegriffe "
          "enthalten Unterbegriffe, etwa \"Nebenkosten\" mit \"Heizung\" darunter. "
          "Ein Doppelklick auf ein Tag weist es dem Dokument zu — Oberbegriffe "
          "kommen dabei automatisch mit: Wählst du \"Heizung\", steht am Dokument auch "
          "\"Nebenkosten\". Beim Tippen im Tag-Feld schlägt das Programm "
          "passende vorhandene Begriffe vor."),
    ("p", "Grau dargestellte Einträge sind reine Ordnungs-Kategorien: Sie gliedern nur "
          "den Katalog und werden selbst nie zugewiesen — z.B. eine Kategorie "
          "\"Dokument\" über den Tags \"Rechnung\" und \"Angebot\". Per "
          "Rechtsklick → \"Als Struktur/Kategorie umschalten\" bestimmst du selbst, "
          "welche Einträge nur der Ordnung dienen."),
    ("p", "Blau-kursiv dargestellte Einträge sind Synonyme: Sie stehen für das Tag "
          "direkt darüber. Liest die KI-Vollautomatik z.B. \"Haftpflichtversicherung\" und "
          "das steht im Katalog als Synonym unter \"Haftpflicht\", bekommt das Dokument "
          "\"Haftpflicht\" — das Synonym selbst wird nie vergeben und taucht auch nicht als "
          "neues Tag auf. Anlegen: Unter-Tag mit dem Synonym-Text anlegen, dann "
          "Rechtsklick → \"Als Synonym umschalten\"."),

    ("h2", "5. Wiederfinden"),
    ("p", "Das Suchfeld oben durchsucht Dateinamen, Titel und Tags im gesamten "
          "Bestand, sobald du Return drückst, und kleine Tippfehler verzeiht es dabei "
          "(\"Rechnnug\" findet trotzdem \"Rechnung\"). Mit * als Platzhalter geht auch "
          "\"Rechnung*2026\". Mehrere Wörter müssen alle vorkommen, egal in welcher "
          "Reihenfolge - soll ein Ausdruck genau so zusammenhängend dastehen, setze ihn in "
          "Anführungszeichen: \"Max Mustermann\". Auch ein einzelnes Wort in Anführungszeichen "
          "findet nur genau dieses Wort: \"Ramen\" findet dann weder \"Rahmen\" noch \"Ramensuppe\". Beim Tippen schlägt das Suchfeld passende Tags "
          "vor (wie das Tags-Feld), und ein Tag im Suchtext erscheint blau-fett wie im Tag-Baum. "
          "Zusätzlich kannst du nach Zeitraum eingrenzen oder den "
          "Tag-Baum als Filter benutzen (Umschalter \"Filtern\")."),

    ("h1", "⌨️	Tastenkürzel"),

    ("h2", "Ordnerbaum (links oben)"),
    ("kbd", [
        ("F2", "Ordner umbenennen"),
        ("Rechtsklick", "Neuer Unterordner, Zusammenführen, im Explorer öffnen, auf-/zuklappen"),
    ]),

    ("h2", "Dokumentenliste (Mitte)"),
    ("kbd", [
        ("F2", "Datei umbenennen"),
        ("Entf", "In den Papierkorb verschieben"),
        ("Enter", "Datei im Standardprogramm öffnen"),
        ("Strg + Klick", "Einzelne Dokumente zur Auswahl hinzufügen/entfernen"),
        ("Shift + Klick", "Bereich auswählen"),
        ("Ziehen auf Ordner", "Markierte Dokumente in diesen Ordner verschieben"),
        ("Alt + Ziehen", "Auf ein anderes Dokument fallen lassen: dessen Tags werden um die des gezogenen ergänzt "
                         "(ohne Alt passiert nichts)"),
        ("Klick auf Spaltenkopf", "Nach dieser Spalte sortieren, nochmal klicken: umgekehrt"),
    ]),

    ("h2", "Tag-Baum (links unten)"),
    ("kbd", [
        ("Doppelklick / Leertaste", "Tag zuweisen bzw. entfernen — sind mehrere Dokumente markiert, für alle auf einmal"),
        ("F2", "Tag umbenennen"),
        ("Entf", "Tag löschen"),
        ("Strg + I", "Tag wegräumen: aus Dokumenten, Katalog und künftigen KI-Vorschlägen"),
        ("Strg + X / Strg + V", "Tag ausschneiden / einfügen"),
        ("Alt + Hoch / Runter", "Tag in der Liste verschieben"),
        ("Esc", "Tag-Suchfeld leeren"),
    ]),

    ("h2", "Seitenansicht (rechts)"),
    ("kbd", [
        ("Mausrad", "Blättern und scrollen (am Seitenende: nächste Seite)"),
        ("Strg + Mausrad", "Vergrößern/verkleinern an der Mausposition"),
        ("Ziehen mit der Maus", "Ausschnitt verschieben"),
        ("Doppelklick", "Ansicht wieder einpassen (Seite füllt die Breite)"),
        ("Doppelklick auf Greifer", "Ganze Seite einpassen: der Greifer links neben der Ansicht rückt so, dass die "
                                    "komplette Seite ohne Scrollen zu sehen ist"),
        ("Pfeil links / rechts", "Eine Seite zurück / vor"),
        ("Bild auf / Bild ab", "Drei Seiten zurück / vor"),
    ]),
]

TAB_FEATURES = [
    ("h1", "✨	Was kann das Programm?"),
    ("p", "Kurz gesagt: Es hilft dir, PDF-Dokumente abzulegen, zu beschriften und in "
          "Sekunden wiederzufinden — ohne dass deine Dateien in einem fremden System "
          "verschwinden. Alles bleibt in ganz normalen Windows-Ordnern auf deinem Rechner."),

    ("h2", "🗂️\tOrdnung halten"),
    ("p", "Deine Dokumente liegen in gewöhnlichen Ordnern, die du links im Programm wie "
          "im Explorer siehst — samt Anzahl der Dokumente pro Ordner. Dateien lassen sich "
          "per Maus verschieben; Gelöschtes landet zuerst in einem Papierkorb und kann "
          "wiederhergestellt werden."),

    ("h2", "🏷️\tBeschriften statt suchen"),
    ("p", "Jedes Dokument bekommt Titel, Tags und ein Dokumentdatum (z.B. das "
          "Rechnungsdatum). Das Datum liest das Programm meist selbst aus dem Dokument — "
          "du musst nur noch bestätigen oder korrigieren. Deine Tags organisierst "
          "du in einem eigenen Katalog mit Ober- und Unterbegriffen; die zuletzt "
          "benutzten sind immer griffbereit."),

    ("h2", "🔍\tBlitzschnell wiederfinden"),
    ("p", "Ein Suchfeld durchsucht den kompletten Bestand über alle Ordner hinweg — nach "
          "Namen, Titeln und Tags, auf Wunsch auch im Text der Dokumente selbst "
          "(Texterkennung). Kleine Tippfehler verzeiht die Suche von selbst — auch solche, "
          "die beim Einscannen im Dokumenttext entstehen. Ergebnisse lassen sich nach "
          "Zeitraum und Tags eingrenzen. Ein Wort in Anführungszeichen findet nur genau "
          "dieses Wort. Treffer im gerade geöffneten Ordner werden blau hervorgehoben."),

    ("h2", "📄\tBequem lesen"),
    ("p", "Die eingebaute Seitenansicht zeigt das Dokument groß und gestochen scharf, "
          "mit sanftem Umblättern, stufenlosem Vergrößern und einer gelben Markierung "
          "auf dem erkannten Datum. Zum Bearbeiten in einem anderen Programm genügt ein "
          "Doppelklick auf die Datei."),

    ("h2", "🔒\tDeine Daten gehören dir"),
    ("p", "Titel, Tags und Datum werden unsichtbar in der PDF-Datei selbst "
          "gespeichert — nicht in einer Datenbank des Programms. Kopierst du eine Datei "
          "auf einen Stick oder schickst sie per E-Mail, bleibt alles erhalten. Und "
          "solltest du das Programm eines Tages nicht mehr benutzen: Deine Dokumente "
          "und Ordner bleiben vollständig nutzbar. Nichts verlässt deinen Rechner."),

    ("h2", "✉️\tMails übernehmen"),
    ("p", "Tools → Vollautomatik → „Mails importieren…“ holt gezielt Mails aus Thunderbird, "
          "klassischem Outlook oder .pst-, .ost-, mbox- und .eml-Dateien in die Sammlung, auch aus "
          "einem Ordner mit vielen solchen Dateien. Das Programm sucht die Mail-Programme beim Öffnen "
          "des Fensters selbst, arbeitet dort nur auf einer Kopie und verändert an den Mail-Dateien "
          "nichts. Nach dem Einlesen sucht man wie im Hauptfenster, etwa „Stadtwerke 2024“, und hakt "
          "die gewünschten Mails an; kleine Tippfehler werden verziehen. Übernommen werden nur die "
          "angehakten Mails, wahlweise in den Posteingang (die Vollautomatik legt sie ab) oder direkt "
          "in einen gewählten Ordner. Sie werden zu PDFs mit der Original-Mail darin: "
          "„Original-Mail öffnen“ neben „Details“ zeigt sie samt Links und Anhängen. PDF-Anhänge "
          "werden eigene Dokumente und bleiben mit ihrer Mail verbunden. Einzelne Mails ohne Anhang "
          "kommen in „Einzelne Mails“ statt in einen eigenen Ordner. Ansicht → „Mails ausblenden“ "
          "zeigt bei Bedarf nur Scans und Anhänge."),

    ("h2", "🧭\tBegleitet erfassen"),
    ("p", "Für eine neue oder große Sammlung: Tools → Vollautomatik → „Begleitet erfassen "
          "(Posteingang)…“ geht den Posteingang Dokument für Dokument durch. Das Programm schlägt "
          "Zielordner, Titel, Datum und Tags vor, du bestätigst oder korrigierst. Sobald die "
          "Vorschläge meist stimmen, übernimmt die Vollautomatik den Rest."),

    ("h2", "📖\tWiki: Nachschlagen, wer und was zur Sammlung gehört"),
    ("p", "Unter Tools → KI-Helfer → „Wiki…“ führst du ein Nachschlagewerk zu deiner Sammlung: "
          "Einträge für Personen, Firmen, Behörden, Immobilien, Fahrzeuge, Verträge und "
          "Versicherungen. Sie liegen in Schubladen, die du selbst erweitern, umbenennen und "
          "zusammenlegen kannst. Jeder Eintrag hat kurze Angaben, Verbindungen zu anderen Einträgen "
          "und Dokumente als Belege. Mit Rechtsklick auf ein Dokument → „Wiki“ → „Von der KI lesen "
          "lassen…“ listet die KI auf, wer und was darin vorkommt; ins Wiki kommt nur, was du "
          "anhakst. Die KI kann sich irren, deshalb steht bei jeder Angabe das Zitat aus dem "
          "Dokument. Die PDF-Dateien bleiben dabei unverändert."),

    ("h2", "🛠️\tPraktische Werkzeuge"),
    ("p", "Im Tools-Menü findest du Helfer für besondere Fälle, nach Themen sortiert: "
          "„Vollautomatik“ (Posteingang verarbeiten, Begleitet erfassen, Mails importieren, "
          "Ablage-Vorschau, Hintergrund-Automatik, Protokoll), „KI-Helfer“ (Titel vorschlagen, "
          "Dokument neu erfassen, Wiki), "
          "„Aufräumen“ (Dubletten finden, Tag-Hygiene, Titel aufräumen) und „PDF-Werkzeuge“ "
          "(Inspektor, der alle gespeicherten Informationen einer PDF-Datei offenlegt; "
          "Mini-Editor, der Seiten dreht, löscht oder leere Seiten einfügt). Die Einstellungen, "
          "in denen du das Programm an deine Arbeitsweise anpasst, liegen unter Datei → "
          "Einstellungen. Diese Werkzeugliste ist erweiterbar — neue Helfer kommen dazu, ohne "
          "das Programm selbst zu ändern."),

    ("h2", "💻\tKI auf dem eigenen PC"),
    ("p", "Wer keinen eigenen KI-Server hat, kann Ollama direkt auf diesem Rechner laufen lassen. "
          "Das Programm merkt keinen Unterschied - nur die Geschwindigkeit hängt vom Rechner ab."),
    ("p", "1. Ollama für Windows von ollama.com installieren; es läuft danach als Hintergrunddienst "
          "und hört nur auf diesem PC (nichts geht ins Internet).\n"
          "2. In der Eingabeaufforderung das Bild-Modell laden (rund 7 GB Download, einmalig):  "
          "ollama pull qwen3.5:9b\n"
          "3. Im Programm unter Datei → Einstellungen → KI-Server bleibt die Adresse "
          "http://localhost:11434; \"Verbindung testen\" klicken - der Punkt rechts in der "
          "Suchleiste wird grün."),
    ("p", "Womit man rechnen muss (Richtwerte für ein Dokument mit einer Seite, Modell qwen3.5:9b):"),
    ("tabelle", [('Rechner', 'Dauer je Dokument', 'Bemerkung'), ('nur Prozessor (ohne Grafikkarte)', '2 bis 10 Minuten', 'mind. 16 GB Arbeitsspeicher; Häkchen "KI ohne Grafikkarte zulassen" setzen'), ('Grafik im Prozessor (integriert)', 'wie nur Prozessor', 'Ollama nutzt integrierte Grafik unter Windows in der Regel nicht'), ('eigene Grafikkarte mit 8 GB', '20 bis 60 Sekunden', 'Modell passt gerade; bei viel Text teils im Arbeitsspeicher'), ('eigene Grafikkarte mit 16 GB', '5 bis 20 Sekunden', 'alles im Grafikspeicher - der gedachte Normalfall')]),
    ("p", "Ohne Grafikkarte ist die KI also kein Werkzeug zum Zuschauen, aber die Vollautomatik "
          "arbeitet unbeaufsichtigt im Hintergrund - ein Stapel Scans ist dann eben über Nacht "
          "abgelegt statt in einer Viertelstunde. Dafür in den Einstellungen \"KI ohne Grafikkarte "
          "zulassen\" ankreuzen, sonst pausiert die Vollautomatik (bei einem Server mit Grafikkarte "
          "ist Prozessor-Betrieb nämlich ein Defekt). Wer es schneller braucht, kann als Modell "
          "qwen3.5:4b eintragen: halb so groß und schneller; wie gut es Dokumente liest, ist nicht gemessen."),
    ("p", "Für alles außer der KI (Ordner, Tags, Suche, Vorschau, Dubletten, Aufräumen) braucht es "
          "weder Ollama noch eine Grafikkarte."),

    ("h2", "🌐\tKI-Server aus der Ferne (Tailscale)"),
    ("p", "Ob der KI-Server gerade antwortet, zeigt der Farbpunkt rechts in der Suchleiste: "
          "grün = verbunden, rot = nicht erreichbar (der Mauszeiger darauf zeigt den Text). Bei Rot sind die Werkzeuge, die "
          "den Server brauchen (Titel vorschlagen, Ablage-Vorschau, Posteingang "
          "verarbeiten), im Menü ausgegraut; sobald der Server wieder antwortet, werden sie von "
          "selbst frei. Alles andere arbeitet ohne Server weiter."),
    ("p", "Die KI-Funktionen (Titelvorschlag, Vollautomatik) sprechen mit einem Ollama-Server "
          "im eigenen Netz. Steht der Server in einem anderen Haus, verbindet Tailscale "
          "beide Rechner zu einem privaten Netz — verschlüsselt, ohne "
          "Portfreigabe am Router und kostenlos für den Privatgebrauch."),
    ("link", "https://tailscale.com/"),
    ("p", "So geht's: Tailscale auf dem Server-Rechner und auf diesem Rechner installieren und "
          "beide mit DEMSELBEN Konto anmelden (z.B. GitHub oder Apple). Danach unter Datei → "
          "Einstellungen → KI-Server als Server-Adresse den Tailscale-Namen des Servers eintragen, z.B. "
          "http://ki-server:11434 — das Programm merkt keinen Unterschied zum Heimnetz."),
    ("p", "Wichtig: Den KI-Server niemals über eine Portfreigabe am Router ins Internet stellen "
          "— Ollama hat keine Anmeldung, jeder könnte ihn benutzen. Tailscale ist der sichere Weg."),
]

TAB_TAGS = [
    ("h1", "🏷️\tTags: Sinn, Vorteile, Grenzen"),
    ("p", "Ein Tag (deutsch: Schlagwort) ist ein kurzer Begriff, der einem Dokument zusätzlich zu Ordner, "
          "Titel und Datum mitgegeben wird - zum Beispiel \"Rechnung\", \"Gebäudeversicherung\" "
          "oder \"Ferienwohnung\". Ein Dokument kann mehrere Tags tragen. Sie werden im "
          "Feld \"Stichwörter\" der PDF-Datei selbst gespeichert, nicht in einer Datenbank des "
          "Programms, und sind deshalb auch in anderen PDF-Programmen und in den "
          "Windows-Dateieigenschaften sichtbar. Der Katalog links unten (Baum mit Ober- und "
          "Unterbegriffen) ist nur die Vorschlagsliste; verbindlich ist, was am Dokument steht."),

    ("h2", "Wofür Tags gedacht sind"),
    ("p", "Ein Ordner beantwortet genau eine Frage: Wo liegt das Dokument? Ein Dokument "
          "gehört aber oft zu mehreren Themen zugleich - die Gasrechnung für die vermietete "
          "Wohnung ist eine Rechnung, betrifft die Nebenkosten und das Objekt Musterstraße 12. "
          "Im Ordner kann sie nur an einer Stelle liegen; mit Tags ist sie über jeden "
          "dieser Wege auffindbar. Der typische Nutzen zeigt sich in der Suche mit zwei oder "
          "drei Begriffen: \"Versicherung Musterstraße 2021\" oder \"Nebenkosten Ferienwohnung 2022\" "
          "liefert in Sekunden die passenden Dokumente, unabhängig davon, in welchem Ordner "
          "sie abgelegt sind."),

    ("h2", "Warum Tags, wenn es die Suche gibt?"),
    ("p", "Die Suche findet, was auf dem Papier steht: Dateinamen, Titel, Tags und "
          "auf Wunsch den erkannten Text der Seiten. Tags halten fest, was NICHT "
          "auf dem Papier steht, aber zum Wiederfinden gebraucht wird: die Einordnung. Auf "
          "einer Beitragsrechnung der Versicherung steht selten das Wort \"Versicherung\", "
          "auf einem Bescheid nicht \"Nebenkosten\", und das betroffene Objekt erscheint oft "
          "nur als Vertragsnummer oder gar nicht. Ein Tag ist außerdem ein festgelegter "
          "Begriff: \"Gebäudeversicherung\" bleibt \"Gebäudeversicherung\", während auf dem "
          "Papier mal \"Wohngebäude-Police\", mal \"Beitragsrechnung\", mal \"Prämie\" steht. "
          "Umgekehrt trifft die Volltextsuche nach \"Versicherung\" jeden Brief, der das Wort "
          "beiläufig erwähnt. Dazu kommt die Technik: Die Volltextsuche braucht eine "
          "Texterkennung, die bei schlechten Scans Wörter verfehlt; Tags stehen als "
          "Klartext in den Dateieigenschaften und werden immer gefunden. Beides ergänzt sich: "
          "Der Text beantwortet \"wo steht dieses Wort\", das Tag \"welche Dokumente "
          "gehören zu diesem Thema\"."),

    ("h2", "Vorteile"),
    ("kbd", [
        ("Mehrere Zugänge", "Ein Dokument ist über Art, Objekt und Ort auffindbar, nicht nur über seinen Ordner."),
        ("Ordnerübergreifend", "Die Suche und der Filter-Modus des Katalogs wirken über die gesamte Sammlung."),
        ("Kombinierbar", "Mehrere Tags grenzen gemeinsam ein; Oberbegriffe kommen automatisch mit."),
        ("Bleibt am Dokument", "Kopieren, Verschieben, Weitergeben per Stick oder E-Mail - die Tags reisen mit."),
        ("In deiner Hand", "Tags vergibst du selbst; die Vollautomatik legt ab, ohne Tags zu setzen. Synonyme lenken Varianten auf einen Begriff."),
    ]),

    ("h2", "Nachteile und Grenzen"),
    ("kbd", [
        ("Pflegeaufwand", "Tags müssen vergeben und der Katalog gelegentlich aufgeräumt werden (Tools → Aufräumen → Tag-Hygiene)."),
        ("Wildwuchs", "Ohne Disziplin entstehen Varianten desselben Begriffs (\"Rechnung\", \"Rechnungen\", \"Re.\"), die sich gegenseitig verdecken."),
        ("Flächendeckend = wertlos", "Ein Tag, das auf der halben Sammlung steht, grenzt nichts mehr ein."),
        ("Kein Ersatz für Ordner", "Tags ergänzen die Ordnerstruktur, sie ersetzen sie nicht."),
    ]),

    ("h2", "Bewährte Praxis"),
    ("p", "Wenige, aussagekräftige Tags je Dokument (drei bis fünf) sind besser als "
          "viele. Bewährt hat sich die Kombination aus Art des Dokuments, Objekt und Ort: "
          "die konkrete Sparte als Tag (\"Gebäudeversicherung\" statt nur "
          "\"Versicherung\" - der Oberbegriff kommt über den Katalog automatisch dazu), das "
          "Objekt (z.B. \"Musterstraße 12\") im Titel und als Tag, der Ort als eigenes "
          "Tag. Namen von Familienmitgliedern taugen meist nicht als Tag, weil "
          "sie auf zu vielen Dokumenten stehen; mit Strg+I lassen sie sich aus Dokumenten, "
          "Katalog und künftigen KI-Vorschlägen entfernen. Schreibvarianten werden als "
          "Synonym unter dem gewünschten Begriff eingetragen; die Tag-Hygiene (Tools → "
          "Aufräumen) vereinheitlicht sie dann in den Dokumenten."),

    ("h2", "Arbeiten ohne Tags"),
    ("p", "Das Programm verlangt an keiner Stelle ein Tag. Ordner, Titel, "
          "Dokumentdatum und die Volltextsuche (Häkchen \"Inhalt (OCR)\") funktionieren "
          "vollständig ohne. Auch die Vollautomatik legt Dokumente nach Absender und Datum "
          "ab und setzt dabei keine Tags. Wer den Katalog nicht braucht, kann den Bereich "
          "links unten mit dem Greifer zwischen Ordnerbaum und Katalog klein ziehen. Der "
          "Verzicht kostet nichts außer dem ordnerübergreifenden Wiederfinden - und lässt "
          "sich später jederzeit nachholen."),
]

TAB_ABOUT = [
    ("h1", f"ℹ️	{APP_NAME}"),
    ("p", f"Version {APP_VERSION} (Build {build_stempel()})"),
    ("p", "Ein lokales, datenschutzfreundliches Werkzeug zur Verwaltung, Verschlagwortung "
          "und Organisation von PDF-Dokumenten."),
    ("p", "Alle Daten bleiben auf deinem Rechner. Titel, Tags und Dokumentdatum "
          "werden direkt in die PDF-Dateien geschrieben — die Dokumente bleiben auch ohne "
          "dieses Programm vollständig nutzbar."),

    ("h2", "Technik"),
    ("kbd", [
        ("Python / Tkinter", "Programm und Oberfläche"),
        ("PyMuPDF", "PDF-Anzeige und Beschriftung"),
        ("Pillow", "Bildverarbeitung"),
        ("watchdog", "Überwachung der Ordner auf Änderungen"),
    ]),

    ("h2", "Lizenz & Rechtliches"),
    ("p", "Copyright © 2026 Peter Metz. Freie Software unter der GNU Affero General "
          "Public License v3.0 (AGPL-3.0): kostenlose Nutzung, Weitergabe und Veränderung "
          "erlaubt — Veränderungen müssen bei Weitergabe wieder quelloffen unter derselben "
          "Lizenz erscheinen, der Copyright-Vermerk muss erhalten bleiben. Der vollständige "
          "Lizenztext liegt jedem Release bei (LICENSE.txt) und steht auf der Projektseite. Der Quellcode wird in einem "
          "eigenen Schritt veröffentlicht; bis dahin gibt es ihn auf Anfrage (GitHub-Issue "
          "oder direkt beim Entwickler)."),
    ("p", "Dieses Programm wird ohne jede Gewährleistung bereitgestellt (Details in der "
          "Lizenz, Abschnitte 15 und 16). Es verarbeitet keine Daten außerhalb deines "
          "Rechners und sendet nichts ins Internet — keine Telemetrie, keine Konten, "
          "keine Cloud."),
    ("p", "Verwendete Bibliotheken: PyMuPDF (AGPL-3.0), Pillow (MIT-CMU), "
          "watchdog (Apache-2.0), Python/Tkinter (PSF-Lizenz)."),

    ("h2", "Projekt"),
    ("link", "https://github.com/peterm2024/Dokumenten-Manager"),
    ("p", "Entwickelt als Einzelprojekt mit KI-Unterstützung."),
]


# ==========================================
# DAS HILFE-FENSTER
# ==========================================
class HelpWindow(tk.Toplevel):
    """
    Hilfe-Fenster mit den Tabs Schnellstart, Funktionsumfang, Tags, Menü-Übersicht und Über.
    Beim automatischen Aufruf am Programmstart modal (blockiert das Hauptfenster,
    bis es geschlossen wird); über das Hilfe-Menü geöffnet nicht-modal.
    """

    # Der Reiter „Menü-Übersicht" (Index 3) wird zur Laufzeit aus menue_hilfe gebaut (None),
    # weil die Tool-Erklärungen aus den geladenen Tools kommen. „Tags" (Index 2,
    # Nutzerwunsch 13.09.2026): Sinn, Vorteile und Grenzen der Tags ausdrücklich erklärt,
    # weil manche Anwender sie für überflüssig halten - inklusive „Arbeiten ohne Tags".
    TABS = (("Schnellstart", TAB_QUICKSTART), ("Funktionsumfang", TAB_FEATURES),
            ("Tags", TAB_TAGS), ("Menü-Übersicht", None), ("Über", TAB_ABOUT))

    HEADING_COLOR = "#1f4e79"   # Dunkles Blau für Überschriften
    KEY_COLOR = "#1f4e79"       # Tasten-Spalte in derselben Akzentfarbe

    def __init__(self, parent, app, start_tab=0, modal=False):
        super().__init__(parent)
        self.app = app
        self.title(f"Hilfe - {APP_NAME}")
        breite, hoehe = UIUtils.px(self, 680), UIUtils.px(self, 720)
        if modal:
            self._center_on_parent(parent, breite, hoehe)
        else:
            UIUtils.position_near_mouse(self, breite, hoehe)
        self.transient(parent)

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 4))

        # Sprungmarken: je Tab die h2-Überschriften -> (Text-Widget, Text-Marke), damit
        # select_tab(..., abschnitt=) direkt zu einem Abschnitt scrollen kann (T1.10).
        self._abschnitte = {}
        for tab_index, (tab_title, blocks) in enumerate(self.TABS):
            if blocks is None:
                blocks = menue_hilfe.hilfe_bloecke(self._tools())
            frame = ttk.Frame(self.notebook)
            self.notebook.add(frame, text=tab_title)
            text = tk.Text(frame, wrap="word", bg="#fdfdfd", padx=16, pady=12,
                           relief="flat", cursor="arrow")
            scroll = ttk.Scrollbar(frame, command=text.yview)
            text.configure(yscrollcommand=scroll.set)
            scroll.pack(side=tk.RIGHT, fill=tk.Y)
            text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
            self._render_blocks(text, blocks, tab_index)
            text.config(state=tk.DISABLED)  # Nur lesen

        # Fußleiste: Startverhalten steuerbar; im Modal-Fall zusätzlich ein Schließen-Button
        bottom = ttk.Frame(self)
        bottom.pack(fill=tk.X, padx=10, pady=(0, 10))
        self.var_show_on_start = tk.BooleanVar(value=bool(self.app.config.get("show_help_on_start", True)))
        ttk.Checkbutton(bottom, text="Beim Start anzeigen", variable=self.var_show_on_start,
                        command=self._apply_show_on_start).pack(side=tk.LEFT)
        # Seniorenmodus Schritt 5: die Vollautomatik direkt aus dem Start-Fenster schalten -
        # dieselbe Mechanik wie das Tool "Vollautomatik: automatisch ein/aus" (das
        # Statusfenster selbst IST die Ein-Rückmeldung, deshalb keine Messagebox).
        self.btn_vollautomatik = ttk.Button(bottom, command=self._toggle_vollautomatik)
        self._aktualisiere_vollautomatik_knopf()
        self.btn_vollautomatik.pack(side=tk.LEFT, padx=(15, 0))
        if modal:
            ttk.Button(bottom, text="Los geht's!", command=self.destroy, style="Accent.TButton").pack(side=tk.RIGHT)

        self.select_tab(start_tab)

        if modal:
            self.grab_set()  # Blockiert das Hauptfenster, bis dieses Fenster geschlossen wird

    def _tools(self):
        """Geladene Tools der App (für die Menü-Übersicht); ohne ToolManager leer."""
        manager = getattr(self.app, "tool_manager", None)
        return list(getattr(manager, "tools", []) or [])

    def _apply_show_on_start(self):
        """Speichert, ob der Schnellstart beim nächsten Programmstart automatisch erscheinen soll."""
        self.app.config.set("show_help_on_start", self.var_show_on_start.get())

    def _toggle_vollautomatik(self):
        """Vollautomatik ein/aus - überlebt den Neustart (auto_pilot_enabled in der Config)."""
        neu = not bool(self.app.config.get("auto_pilot_enabled", False))
        self.app.config.set("auto_pilot_enabled", neu)
        dienst = getattr(self.app, "auto_pilot_service", None)
        if dienst is not None:
            dienst.anstossen()
        self._aktualisiere_vollautomatik_knopf()

    def _aktualisiere_vollautomatik_knopf(self):
        an = bool(self.app.config.get("auto_pilot_enabled", False))
        self.btn_vollautomatik.config(
            text="Vollautomatik ausschalten" if an else "🚀 Vollautomatik einschalten")

    def _center_on_parent(self, parent, width, height):
        """Zentriert das Fenster über dem Hauptfenster (für den modalen Start-Aufruf)."""
        parent.update_idletasks()
        x = parent.winfo_rootx() + (parent.winfo_width() - width) // 2
        y = parent.winfo_rooty() + (parent.winfo_height() - height) // 2
        # Auf dem Monitor des Hauptfensters halten (max(0, ...) würde bei einem Monitor LINKS
        # vom Hauptmonitor - negative Koordinaten - das Fenster nach rechts verschieben).
        links, oben, rechts, unten = UIUtils.monitor_bounds_at(
            self, parent.winfo_rootx() + parent.winfo_width() // 2, parent.winfo_rooty() + parent.winfo_height() // 2)
        x = max(links, min(x, rechts - width))
        y = max(oben, min(y, unten - height))
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _render_blocks(self, text, blocks, tab_index=0):
        """Rendert die Inhalts-Blöcke mit echter Formatierung (Schriftgrößen, Farben, Tab-Spalten)."""
        # Tab-Stopp nach dem Emoji: Emojis sind unterschiedlich breit, mit "Emoji\tText"
        # beginnt der Überschriften-Text trotzdem immer an derselben Position.
        text.tag_configure("h1", font=("Segoe UI", 15, "bold"), foreground=self.HEADING_COLOR,
                           spacing1=14, spacing3=6, tabs=("40",))
        # 40px wie bei h1: auch die breiten Emojis (mit Variationsselektor, z.B. 🗂️)
        # passen damit VOR den ersten Tab-Stopp — kein Ausweichen auf den nächsten Stopp
        text.tag_configure("h2", font=("Segoe UI", 11, "bold"), foreground="#333333",
                           spacing1=10, spacing3=3, tabs=("40",))
        text.tag_configure("p", font=("Segoe UI", 10), foreground="#222222",
                           spacing3=6, lmargin1=4, lmargin2=4)
        # Tastenkürzel: Tab-Stopp bei 190px richtet die Beschreibungs-Spalte sauber aus,
        # unabhängig von der (proportionalen) Schriftart. lmargin2 lässt umbrochene
        # Beschreibungen in der zweiten Spalte weiterlaufen.
        text.tag_configure("kbd", font=("Segoe UI", 10), foreground="#222222",
                           tabs=("190",), lmargin1=16, lmargin2=190, spacing3=2)
        text.tag_configure("kbd_key", font=("Segoe UI", 10, "bold"), foreground=self.KEY_COLOR)
        # Klickbare Links: blau + unterstrichen, Handcursor beim Überfahren, Klick öffnet
        # den Standardbrowser. Jeder Link bekommt einen eigenen Tag-Namen, damit die
        # Klick-Bindung genau seine URL trifft.
        text.tag_configure("link", font=("Segoe UI", 10, "underline"), foreground="#0563c1",
                           spacing3=6, lmargin1=4, lmargin2=4)
        # Tabellen (13.09.2026): drei Spalten über Tab-Stopps, Kopfzeile fett, Zeilen mit
        # feinem Abstand; umbrochene Zellen laufen in der letzten Spalte weiter (lmargin2).
        text.tag_configure("tabelle", font=("Segoe UI", 10), foreground="#222222",
                           tabs=("235", "360"), lmargin1=8, lmargin2=360, spacing3=3)
        text.tag_configure("tabelle_kopf", font=("Segoe UI", 10, "bold"), foreground=self.HEADING_COLOR)

        for block_nr, (style, content) in enumerate(blocks):
            if style == "kbd":
                for key, desc in content:
                    text.insert(tk.END, key, ("kbd", "kbd_key"))
                    text.insert(tk.END, f"\t{desc}\n", ("kbd",))
            elif style == "tabelle":
                for zeile_nr, zeile in enumerate(content):
                    tags = ("tabelle", "tabelle_kopf") if zeile_nr == 0 else ("tabelle",)
                    text.insert(tk.END, "\t".join(zeile) + "\n", tags)
                text.insert(tk.END, "\n", ("p",))
            elif style == "link":
                marke = f"link_{block_nr}"
                text.insert(tk.END, f"{content}\n", ("link", marke))
                text.tag_bind(marke, "<Button-1>", lambda _e, url=content: webbrowser.open(url))
                text.tag_bind(marke, "<Enter>", lambda _e, t=text: t.config(cursor="hand2"))
                text.tag_bind(marke, "<Leave>", lambda _e, t=text: t.config(cursor="arrow"))
            else:
                if style == "h2":
                    # Marke VOR dem Einfügen setzen (gravity left: sie bleibt am Zeilenanfang
                    # der Überschrift, statt mit dem Text nach unten zu wandern)
                    marke = f"abschnitt_{block_nr}"
                    text.mark_set(marke, tk.END + "-1c")
                    text.mark_gravity(marke, tk.LEFT)
                    self._abschnitte[(tab_index, abschnitts_titel(content))] = (text, marke)
                text.insert(tk.END, f"{content}\n", (style,))

    def select_tab(self, index, abschnitt=None):
        """Wechselt auf den gewünschten Tab (0=Schnellstart, 1=Funktionsumfang, 2=Tags, 3=Menü-Übersicht, 4=Über).

        abschnitt: Anfang einer h2-Überschrift dieses Tabs (ohne Emoji, z.B. "KI-Server aus
        der Ferne") - der Text wird so gescrollt, dass die Überschrift oben steht (bzw. so
        weit wie möglich, wenn der Abschnitt nahe am Textende liegt), und die Überschrift
        leuchtet kurz gelb auf, damit das Auge sie sofort findet.
        """
        self.notebook.select(index)
        if abschnitt:
            ziel = self.finde_abschnitt(index, abschnitt)
            if ziel is not None:
                text, marke = ziel
                # Beim frischen Fenster kennt das Text-Widget seine Höhe noch nicht -
                # erst nach dem Layout scrollen, sonst landet die Marke irgendwo.
                text.after_idle(lambda: self._springe_zu(text, marke))

    BLITZ_FARBE = "#fff3b0"
    BLITZ_DAUER_MS = 1500

    def _springe_zu(self, text, marke):
        """Scrollt die Überschrift an der Marke nach oben und hebt ihre Zeile kurz hervor."""
        text.yview(marke)
        text.tag_configure("sprung", background=self.BLITZ_FARBE)
        text.tag_remove("sprung", "1.0", tk.END)
        text.tag_add("sprung", f"{marke} linestart", f"{marke} lineend")
        text.after(self.BLITZ_DAUER_MS, lambda: text.winfo_exists() and text.tag_remove("sprung", "1.0", tk.END))

    def finde_abschnitt(self, tab_index, abschnitt):
        """Liefert (Text-Widget, Marke) der ersten h2-Überschrift des Tabs, die mit `abschnitt` beginnt."""
        gesucht = abschnitts_titel(abschnitt)
        for (tab, titel), ziel in self._abschnitte.items():
            if tab == tab_index and titel.startswith(gesucht):
                return ziel
        return None


def abschnitts_titel(ueberschrift):
    """Normalisiert eine h2-Überschrift für den Vergleich: Emoji-Präfix vor dem Tab weg, Kleinschreibung."""
    titel = ueberschrift.split("\t")[-1] if "\t" in ueberschrift else ueberschrift
    return titel.strip().casefold()


def open_help(app, tab=0, modal=False, abschnitt=None):
    """Öffnet das Hilfe-Fenster (Singleton) auf dem gewünschten Tab; modal=True für den automatischen Start-Aufruf.

    abschnitt: optional der Anfang einer Abschnitts-Überschrift, zu der gescrollt wird (siehe HelpWindow.select_tab).
    """
    window = getattr(app, 'help_window', None)
    if window and window.winfo_exists():
        window.select_tab(tab, abschnitt)
        window.lift()
        window.focus()
    else:
        app.help_window = HelpWindow(app.root, app, start_tab=tab, modal=modal)
        if abschnitt:
            app.help_window.select_tab(tab, abschnitt)
