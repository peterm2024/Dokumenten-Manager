"""
Menü-Hilfe: EINE Quelle für die Erklärung jedes Menüeintrags (Nutzerwunsch 11.09.2026,
Vorbild Autodesk Inventor: beim Verweilen auf einem Eintrag erscheint eine kurze Hilfe).
Peter: „ich tue mir zwischenzeitlich schwer zu überblicken, welcher Eintrag im Menü
was genau macht und wofür er gut war, welche Intention dahinter stand.“

Je Eintrag zwei Sätze: WAS passiert beim Klick, und WOFÜR der Eintrag gedacht ist
(die Absicht, der typische Anlass). Die festen Menüs (Datei, Ansicht, Hilfe, Rechtsklick)
stehen hier; die Tools liefern ihre Texte selbst (`BaseTool.description` = was,
`BaseTool.absicht` = wofür), damit ein neues Tool seine Erklärung mitbringt.

Verwendet von:
- help_window: Reiter „Menü-Übersicht“ (`hilfe_bloecke`) - funktioniert immer.
- menue_tooltip (Stufe 3): Erklärung beim Verweilen auf einem Eintrag (`finde`).
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Eintrag:
    menue: str      # Menü-Pfad wie in der Oberfläche: "Datei", "Tools → Vollautomatik", "Rechtsklick Dokument"
    label: str      # Menütext wie angezeigt
    was: str        # Was passiert beim Klick
    wofuer: str     # Absicht: wofür gedacht, wann man es braucht
    bild: str = ""  # optional: Dateiname eines Bildes (Stufe 3, noch ungenutzt)


MENUE_REIHENFOLGE = ("Datei", "Ansicht", "Tools", "Hilfe", "Rechtsklick Ordner", "Rechtsklick Dokument",
                     "Rechtsklick Spaltenkopf")

FESTE_EINTRAEGE = [
    # ------------------------------------------------------------------ Datei
    Eintrag("Datei", "Sammlung öffnen (Hauptordner wählen)...",
            "Öffnet einen Ordner-Dialog; der gewählte Ordner wird zur Sammlung, die links im Ordnerbaum erscheint.",
            "Die Sammlung ist der Hauptordner mit allen Dokumenten. Nötig beim ersten Start, beim Wechsel auf eine "
            "andere Sammlung (z.B. Test-Sammlung) oder nach einem Umzug der Ordner."),
    Eintrag("Datei", "Standard-Ordnerstruktur in der Sammlung anlegen...",
            "Legt in der Sammlung die mitgelieferten Standardordner an (0_Posteingang, 0_Unsicher, Buchstabengruppen "
            "wie „A - B“); vorhandene Ordner bleiben unangetastet.",
            "Für einen schnellen, einheitlichen Start: Posteingang für den Scanner, Unsicher für die Vollautomatik, "
            "Buchstabengruppen für die Absender-Ordner. Ohne diese Struktur kann die Vollautomatik nicht ablegen."),
    Eintrag("Datei", "Einstellungen...",
            "Öffnet die Einstellungen als Reiter (Allgemein, Dokumentenliste, Eigenschaften, Vorschau, Suche & Volltext, "
            "KI-Server, Vollautomatik, Experten) mit einer Erklärzeile unter jeder Option; Änderungen wirken sofort.",
            "Alles, was das Programm an deine Arbeitsweise anpasst, an einem Ort: Auto-Save, Sicherheitsabfragen, "
            "sichtbare Spalten, Felder und Reihenfolge der Eigenschaften-Tabelle, Volltext-Stufen, Ollama-Adresse "
            "und Modell, Verhalten der Vollautomatik."),
    Eintrag("Datei", "Protokoll-Datei (Log) öffnen",
            "Öffnet dokumenten_manager.log aus dem Daten-Ordner der Sammlung im Standard-Editor.",
            "Wenn etwas nicht wie erwartet lief: das Protokoll nennt Fehler, geladene Tools, Index-Läufe und "
            "KI-Aufrufe mit Zeitstempel - die erste Anlaufstelle, bevor man rätselt."),
    Eintrag("Datei", "Beenden",
            "Speichert offene Änderungen (Titel/Tags per Auto-Save), merkt sich Fenstergröße und Spaltenbreiten "
            "und schließt das Programm.",
            "Sauberes Ende statt Fenster-X: beide Wege sind gleich, aber hier sieht man, dass nichts verloren geht."),

    # ------------------------------------------------------------------ Ansicht
    Eintrag("Ansicht", "Vorschau einpassen (Auto-Zoom, auch Doppelklick auf die Seite)",
            "Setzt einen von Hand gewählten Zoom (Strg+Mausrad) zurück, die Seite füllt wieder die Breite der Vorschau.",
            "Nach dem Hineinzoomen in ein Detail schnell zurück zur ganzen Seite - derselbe Effekt wie ein "
            "Doppelklick auf die Seite. Soll die KOMPLETTE Seite ohne Scrollen sichtbar sein: Doppelklick auf den "
            "Greifer zwischen Dokumentenliste und Vorschau - der rückt dann von selbst auf die passende Breite."),
    Eintrag("Ansicht", "Papierkorb im Ordnerbaum anzeigen",
            "Blendet den Papierkorb der Sammlung als Ordner im Baum ein oder aus.",
            "Gelöschte Dokumente landen zuerst im Papierkorb. Eingeblendet lässt sich dort per Rechtsklick "
            "„Wiederherstellen…“ ein Fehlgriff zurückholen; ausgeblendet bleibt der Baum übersichtlich."),
    Eintrag("Ansicht", "Mails ausblenden",
            "Zeigt in Ordnerbaum, Dokumentenliste und Suche keine importierten Mails. Ordner, in denen nur Mails liegen, "
            "verschwinden aus dem Baum. Gelöscht oder verschoben wird nichts.",
            "Wenn die vielen Mails die Scans überdecken. Scans und PDF-Anhänge bleiben sichtbar, ebenso alles in "
            "0_Posteingang und 0_Unsicher. Die Suche nennt, wie viele Mails sie außerdem gefunden hätte."),
    Eintrag("Ansicht", "Kurzbefehle anzeigen (F1)",
            "Blendet ein kleines Fenster ein, das die Tasten und Mausaktionen des Bereichs zeigt, in dem gerade "
            "der Cursor oder die Maus ist - darunter grau die überall gültigen. F1 schaltet es ein und aus.",
            "Zum Nachschauen, was in Liste, Ordnerbaum, Tag-Baum, Vorschau oder einem Eingabefeld gerade möglich "
            "ist, ohne die Hilfe zu öffnen. Das Fenster lässt sich verschieben und merkt sich seinen Platz."),
    Eintrag("Ansicht", "Fensteraufteilung zurücksetzen (Standard-Layout)",
            "Setzt die Breiten der drei Bereiche (Ordner, Liste, Vorschau) und die Spaltenaufteilung auf den "
            "Auslieferungszustand zurück.",
            "Wenn die Greifer so verschoben wurden, dass ein Bereich verschwunden ist oder die Liste unlesbar "
            "schmal wurde - ein Klick statt mühsamem Zurechtziehen."),

    # ------------------------------------------------------------------ Hilfe
    Eintrag("Hilfe", "Schnellstart",
            "Öffnet die Hilfe auf dem Reiter „Schnellstart“: in fünf Schritten startklar plus alle Tastenkürzel.",
            "Für den Einstieg und als Spickzettel für die Tasten (F2, Entf, Strg+I, Bild auf/ab …). Erscheint beim "
            "ersten Start automatisch; das Häkchen „Beim Start anzeigen“ steuert das."),
    Eintrag("Hilfe", "Funktionsumfang",
            "Öffnet die Hilfe auf dem Reiter „Funktionsumfang“: was das Programm kann, in Alltagssprache.",
            "Für die Frage „was hab ich davon?“ - Ordnung, Beschriften, Wiederfinden, Datenhoheit, Werkzeuge, "
            "KI-Server aus der Ferne."),
    Eintrag("Hilfe", "Tags: Sinn und Grenzen",
            "Öffnet die Hilfe auf dem Reiter „Tags“: was ein Tag ist, wofür es gedacht ist, "
            "Vorteile, Nachteile, bewährte Praxis und das Arbeiten ganz ohne Tags.",
            "Für die Entscheidung, ob und wie Tags genutzt werden. Das Programm verlangt nirgends ein "
            "Tag; wer sie weglässt, verzichtet nur auf das ordnerübergreifende Wiederfinden."),
    Eintrag("Hilfe", "Menü-Übersicht (jeder Eintrag erklärt)",
            "Öffnet die Hilfe auf dem Reiter „Menü-Übersicht“: zu jedem Menüeintrag „Was“ und „Wofür“.",
            "Genau diese Liste - wenn man nicht mehr weiß, was ein Eintrag tut oder warum es ihn gibt. "
            "Dieselbe Erklärung erscheint, wenn der Mauszeiger gut eine Sekunde auf einem Menüeintrag verweilt "
            "(abschaltbar unter Datei → Einstellungen). Neue Werkzeuge bringen ihre Texte selbst mit."),
    Eintrag("Hilfe", "KI auf dem eigenen PC (Ollama lokal)",
            "Springt im Funktionsumfang zum Abschnitt über Ollama auf diesem Rechner: Installation in drei "
            "Schritten und eine Tabelle, wie schnell die KI je nach Rechner antwortet.",
            "Wer keinen eigenen KI-Server hat, kann die KI-Funktionen trotzdem nutzen - auf dem Prozessor "
            "langsam, mit Grafikkarte flott. Die Tabelle nimmt die Enttäuschung vorweg."),
    Eintrag("Hilfe", "KI-Server aus der Ferne (Tailscale)",
            "Springt im Funktionsumfang zum Abschnitt über Tailscale (die Überschrift leuchtet kurz auf).",
            "Wenn der KI-Server in einem anderen Haus steht: Tailscale verbindet beide Rechner privat und "
            "verschlüsselt, ohne Portfreigabe am Router - die sichere Alternative zum offenen Internet."),
    Eintrag("Hilfe", "Auf neue Version prüfen...",
            "Fragt die Releases-Seite auf github.com nach der neuesten Version und vergleicht sie mit der laufenden; "
            "bei einer neueren kann die Download-Seite im Browser geöffnet werden.",
            "Das Programm aktualisiert sich nicht selbst. So sieht man mit einem Klick, ob eine neue EXE bereitliegt "
            "- dieselbe Prüfung läuft still beim Start (abschaltbar unter Datei → Einstellungen → Allgemein)."),
    Eintrag("Hilfe", "Über...",
            "Zeigt Programmname, Version und Build-Stempel sowie die verwendeten Bibliotheken.",
            "Bei Rückfragen oder Fehlermeldungen: welche Version läuft gerade? Der Build-Stempel unterscheidet "
            "eine Entwicklungs-Version von der ausgelieferten EXE."),

    # ------------------------------------------------------------------ Rechtsklick Ordnerbaum
    Eintrag("Rechtsklick Ordner", "Neuer Unterordner...",
            "Fragt nach einem Namen und legt den Ordner unter dem angeklickten Ordner an.",
            "Neue Absender oder Themen von Hand anlegen - die Vollautomatik legt Absender-Ordner sonst selbst an, "
            "sobald sie sicher ist."),
    Eintrag("Rechtsklick Ordner", "Umbenennen (F2)",
            "Benennt den angeklickten Ordner um; Dokumente darin bleiben, der Suchindex zieht nach.",
            "Tippfehler im Absender oder ein klarerer Name. Achtung: Aliase der Vollautomatik zeigen auf den "
            "Ordnernamen - nach dem Umbenennen ggf. den Zielordner in der Ablage-Vorschau neu anklicken."),
    Eintrag("Rechtsklick Ordner", "Zusammenführen mit…",
            "Verschiebt alle Dokumente des angeklickten Ordners in einen anderen Ordner und entfernt den leeren Ordner.",
            "Wenn zwei Ordner denselben Absender meinen („Stadtwerke“ und „Stadtwerke Musterstadt“) - aufräumen ohne "
            "Dokumente einzeln zu ziehen."),
    Eintrag("Rechtsklick Ordner", "Im Explorer / Finder öffnen",
            "Öffnet den Ordner im Windows-Explorer.",
            "Für alles, was das Programm nicht macht: Dateien von einem Stick hineinkopieren, ein Nicht-PDF ansehen."),
    Eintrag("Rechtsklick Ordner", "Alle Unterordner aufklappen",
            "Klappt den ganzen Ordnerbaum unter dem angeklickten Ordner auf.",
            "Überblick über eine Buchstabengruppe mit vielen Absendern, z.B. beim Suchen per Auge."),
    Eintrag("Rechtsklick Ordner", "Alle Unterordner zuklappen",
            "Klappt den Ordnerbaum unter dem angeklickten Ordner zu.",
            "Ordnung nach dem Aufklappen - der Baum wird wieder kurz."),
    Eintrag("Rechtsklick Ordner", "Aktualisieren",
            "Liest den Ordnerbaum und die Dokumentenliste neu von der Festplatte.",
            "Normalerweise merkt das Programm Änderungen selbst (Überwachung im Hintergrund). Nach Kopieren über "
            "das Netzwerk oder wenn eine Zahl im Baum nicht stimmt: hier einmal auffrischen."),

    # ------------------------------------------------------------------ Rechtsklick Dokumentenliste
    Eintrag("Rechtsklick Dokument", "Öffnen (Enter / Doppelklick)",
            "Öffnet das Dokument im Standard-PDF-Programm von Windows.",
            "Zum Drucken, Ausfüllen oder Weiterleiten - die eingebaute Vorschau ist nur zum Lesen."),
    Eintrag("Rechtsklick Dokument", "Im Ordner anzeigen (Explore...)",
            "Öffnet den Explorer mit dem markierten Dokument.",
            "Wenn man die Datei selbst braucht: als Anhang in eine E-Mail ziehen, auf einen Stick kopieren."),
    Eintrag("Rechtsklick Dokument", "Wiederherstellen...",
            "Holt ein Dokument aus dem Papierkorb zurück in seinen ursprünglichen Ordner (Menüpunkt nur im Papierkorb aktiv).",
            "Der Grund, warum „Löschen“ nie endgültig ist: ein Fehlgriff lässt sich zurücknehmen."),
    Eintrag("Rechtsklick Dokument", "Umbenennen (F2)",
            "Fragt nach einem neuen Dateinamen; Titel, Tags und Datum im PDF bleiben erhalten.",
            "Für einzelne Dateien. Für viele auf einmal: Tools → Aufräumen → „Dateinamen aufräumen“ mit "
            "Vorschlag JJJJMMTT_Titel.pdf."),
    Eintrag("Rechtsklick Dokument", "Löschen (Entf)",
            "Verschiebt das Dokument in den Papierkorb der Sammlung (nach Rückfrage, sofern Sicherheitsabfragen an sind).",
            "Nichts wird sofort gelöscht - im Papierkorb (Ansicht → Papierkorb anzeigen) lässt es sich wiederherstellen."),

    # ------------------------------------------------------------------ Kopfzeile der Dokumentenliste
    Eintrag("Rechtsklick Spaltenkopf", "Spalten ein-/ausblenden",
            "Rechtsklick auf die Kopfzeile der Dokumentenliste zeigt alle Spalten mit Häkchen: Datum, Titel, Tags, "
            "Name, Pfad, Ordner, Scan-Zeit, Textqualität.",
            "Die Liste zeigt nur, was man braucht. „Textqualität“ verrät kaputte Scanner-OCR auf einen Blick, "
            "„Scan-Zeit“ wann gescannt wurde - beides kostet beim Ordnerwechsel etwas Zeit, darum ausblendbar."),
]


def normalisiere_label(label):
    """Menütext für den Vergleich: Werkzeug-Symbol und Auslassungspunkte weg, Kleinschreibung, ein Leerzeichen."""
    text = (label or "").replace("🛠", "").replace("…", "").replace("...", "")
    return " ".join(text.split()).casefold()


def eintraege_fuer_tools(tools):
    """Erklärungen der Tools aus deren eigenen Feldern (description = was, absicht = wofür)."""
    eintraege = []
    for tool in tools or []:
        was = (getattr(tool, "description", "") or "").strip()
        wofuer = (getattr(tool, "absicht", "") or "").strip()
        hooks = getattr(tool, "menu_hooks", []) or []
        if "main_menu" in hooks:
            gruppe = getattr(tool, "menu_group", "") or ""
            menue = f"Tools → {gruppe}" if gruppe else "Tools"
            eintraege.append(Eintrag(menue, tool.menu_label, was, wofuer))
        if "context_menu" in hooks:
            eintraege.append(Eintrag("Rechtsklick Dokument", f"🛠 {tool.name}", was, wofuer))
    return eintraege


def _menue_rang(menue):
    """Sortierschlüssel nach MENUE_REIHENFOLGE; Tools-Untermenüs in der Reihenfolge des Tool-Managers."""
    kopf = menue.split(" → ")[0]
    rang = MENUE_REIHENFOLGE.index(kopf) if kopf in MENUE_REIHENFOLGE else len(MENUE_REIHENFOLGE)
    if kopf == "Tools":
        from tool_manager import GRUPPEN_REIHENFOLGE
        gruppe = menue.split(" → ")[1] if " → " in menue else ""
        unter = GRUPPEN_REIHENFOLGE.index(gruppe) if gruppe in GRUPPEN_REIHENFOLGE else len(GRUPPEN_REIHENFOLGE)
        return (rang, unter)
    return (rang, 0)


def alle_eintraege(tools=()):
    """Feste Einträge plus Tool-Einträge, nach Menü geordnet (stabil innerhalb eines Menüs)."""
    eintraege = list(FESTE_EINTRAEGE) + eintraege_fuer_tools(tools)
    return sorted(eintraege, key=lambda e: _menue_rang(e.menue))


def finde(eintraege, label, menue=None):
    """Eintrag zu einem Menütext (Vergleich normalisiert); menue schränkt auf einen Menü-Pfad ein. None, wenn unbekannt."""
    gesucht = normalisiere_label(label)
    if not gesucht:
        return None
    for eintrag in eintraege:
        if menue and eintrag.menue != menue:
            continue
        if normalisiere_label(eintrag.label) == gesucht:
            return eintrag
    return None


def fehlende_erklaerungen(eintraege):
    """Einträge ohne „was“ oder „wofür“ - für Tests und den Rauchtest (jedes Tool muss beides liefern)."""
    return [e for e in eintraege if not e.was.strip() or not e.wofuer.strip()]


MENUE_EMOJI = {"Datei": "📂", "Ansicht": "🖥️", "Tools": "🛠️", "Hilfe": "❓",
               "Rechtsklick Ordner": "🖱️", "Rechtsklick Dokument": "🖱️", "Rechtsklick Spaltenkopf": "🖱️"}


def hilfe_bloecke(tools=()):
    """
    Inhalt des Hilfe-Reiters „Menü-Übersicht“ im Block-Format von help_window
    (h1 je Menü, h2 je Eintrag - damit select_tab(abschnitt=<Menütext>) hinspringt -,
    darunter „Was:“ und „Wofür:“).
    """
    bloecke = [("h1", "🧭\tJeder Menüeintrag erklärt"),
               ("p", "Zu jedem Eintrag der Menüleiste und der Rechtsklick-Menüs: Was passiert beim Klick, "
                     "und wofür ist der Eintrag gedacht. Die Werkzeuge im Tools-Menü erklären sich selbst - "
                     "ein neues Werkzeug bringt seine Erklärung mit.")]
    letztes_menue = None
    for eintrag in alle_eintraege(tools):
        if eintrag.menue != letztes_menue:
            emoji = MENUE_EMOJI.get(eintrag.menue.split(" → ")[0], "•")
            bloecke.append(("h1", f"{emoji}\t{eintrag.menue}"))
            letztes_menue = eintrag.menue
        bloecke.append(("h2", eintrag.label))
        bloecke.append(("p", f"Was: {eintrag.was}"))
        bloecke.append(("p", f"Wofür: {eintrag.wofuer or '(keine Erklärung hinterlegt)'}"))
    return bloecke
