"""
Dünner HTTP-Client für einen lokalen/im Netzwerk erreichbaren Ollama-Server
(https://ollama.com). Bewusst ohne zusätzliche Abhängigkeit (nur `urllib` aus
der Standardbibliothek) - passt zum KID-Grundprinzip "so unabhängig wie möglich":
funktioniert die App auch ganz ohne KI-Server, degradiert dieses Feature nur
(kein Vorschlag), der Rest der App bleibt unberührt.
"""
import json
import aktivitaet
import re
import base64
import urllib.request
import urllib.error

DEFAULT_URL = "http://localhost:11434"
# Standardmodell = das Modell, das auf dem gemeinsamen KI-Server tatsächlich liegt (Projekte-Wiki,
# ki-infrastruktur.md). Live-Fund 30.08.2026 beim Praxistest: eine frische Installation ohne
# "ollama_model" in der settings.json fragte nach dem alten Standard "llama3.2-vision", und der
# Server antwortete mit HTTP 500 "unknown model architecture: mllama" - siehe FALLSTRICKE #35.
# Seit v0.9.21 qwen3.5:9b (Modell-Prüfstand 27.10.2026, 403 Dokumente: still falsch abgelegt 36 statt
# 79 bei qwen2.5vl:7b unter Ollama 0.40.11, auf der Grafikkarte gleich schnell). Wer schon eine
# settings.json mit "ollama_model" hat, behält sein Modell.
DEFAULT_MODEL = "qwen3.5:9b"
DEFAULT_TIMEOUT = 90
# Bereinigung eines kompletten Dokument-Volltexts (Meister-Stufe) dauert länger als ein
# einzelner Titel-Vorschlag (deutlich mehr Eingabetext) - eigener, großzügigerer Timeout.
CLEAN_TEXT_TIMEOUT = 180

# KI ohne Grafikkarte (Einstellung ki_cpu_erlauben, Beta-Vorbereitung 13.09.2026): Ein
# Bild-Aufruf mit qwen2.5vl:7b dauert auf einem Prozessor je nach Rechner ein bis
# mehrere Minuten - mit den normalen 90 s liefe jede Anfrage in den Timeout. Im
# langsamen Modus wartet _generate das LANGSAM_FAKTOR-fache; die Aufrufer bleiben unverändert.
LANGSAM_FAKTOR = 6
_langsamer_modus = False


def setze_langsamen_modus(aktiv):
    """Schaltet die verlängerten Wartezeiten für KI ohne Grafikkarte ein/aus (gui.py beim Start, Einstellungen live)."""
    global _langsamer_modus
    _langsamer_modus = bool(aktiv)


def langsamer_modus():
    return _langsamer_modus


def wirksamer_timeout(timeout):
    """Timeout einer Anfrage unter Berücksichtigung des langsamen Modus."""
    return timeout * LANGSAM_FAKTOR if _langsamer_modus else timeout

# Live-Fund (13.07.2026, Vollautomatik/Seniorenmodus): Ollama lehnt Anfragen, die das
# Kontextfenster des Modells überschreiten, mit HTTP 400 "exceed_context_size_error" ab
# - passierte real, sobald die Ordnerliste der Sammlung wuchs (53 Ordner + Bild = 4254
# Tokens > Standard-num_ctx 4096). Ein Vision-Aufruf verbraucht für das Bild SELBST
# schon einen großen, bei fester Render-DPI (150) recht konstanten Batzen an Tokens
# (gemessen: ca. 3300) - dieser Puffer deckt das ab. Der Text-Anteil (wachsender
# Tag-Katalog/Ordnerliste) wird grob geschätzt (~3,5 Zeichen/Token für deutschen Text)
# und mit Sicherheitsfaktor aufgerundet: ein zu groß gewähltes num_ctx kostet nur etwas
# mehr VRAM, ein zu klein gewähltes bricht die Anfrage komplett ab.
BILD_TOKEN_PUFFER = 3500
ZEICHEN_PRO_TOKEN = 3.5
STANDARD_NUM_CTX = 4096


def _geschaetzter_num_ctx(prompt_text, bilder=1):
    """Grobe, bewusst großzügig aufgerundete Schätzung des benötigten Kontextfensters für einen Bild-Prompt (siehe Konstanten oben)."""
    geschaetzt = int(len(prompt_text) / ZEICHEN_PRO_TOKEN) + bilder * BILD_TOKEN_PUFFER
    aufgerundet = ((geschaetzt * 2) // 1024 + 1) * 1024  # Sicherheitsfaktor ~2x, auf 1024 aufgerundet
    return max(STANDARD_NUM_CTX, aufgerundet)

TITLE_PROMPT = (
    "Du bekommst das Bild der ersten Seite eines deutschen Geschäftsbriefs "
    "(z.B. Rechnung, Versicherungsschreiben, Behördenschreiben). Gib NUR einen "
    "kurzen, prägnanten Titel für dieses Dokument zurück (z.B. 'Beitragsrechnung "
    "Kfz-Versicherung', 'Kündigungsbestätigung Mobilfunkvertrag'). Keine Erklärung, "
    "keine Anführungszeichen, keine Zeilenumbrüche, maximal 8 Wörter."
)

# Form neuer Tags (Tag-Wildwuchs, Betatest 27.10.2026): der Prompt verlangte bis dahin
# ausdrücklich 'Gebäudebrandversicherung'/'Hausratversicherung', der ausgelieferte Katalog hat aber
# 'Gebäudeversicherung'/'Hausrat' - die KI legte brav Doppelbegriffe an. Außerdem landeten Personen,
# Adressen, Absender und Satzfetzen im Tag-Feld, obwohl es dafür eigene Felder gibt. Die Literatur
# zu kontrolliertem Vokabular sagt dasselbe: ein Begriff je Sache, kurz, einheitliche Form.
# auto_pilot.grund_gegen_neues_tag prüft die Form trotzdem noch einmal im Code.
TAG_FORM_REGEL = (
    "Steht ein passender Tag in der Liste, übernimm ihn GENAU in deren Schreibweise. Ein neues Tag "
    "ist ein deutsches Hauptwort (möglichst Einzahl), höchstens drei Wörter. KEINE Namen von "
    "Personen, Firmen oder Behörden, KEINE Adressen, Nummern, Beträge oder Satzteile."
)

# {tag_catalog} wird durch die kommagetrennte Liste der im Tag-Baum bereits
# vorhandenen Tags ersetzt (siehe tag_manager.get_known_tags). Die Anweisung,
# bevorzugt einen vorhandenen Tag wiederzuverwenden, delegiert das eigentliche
# "Auto" <-> "Kfz"-Abgleichsproblem an das Sprachverständnis des Modells, statt
# dafür eine eigene Fuzzy-Matching-Logik zu bauen (die bei echten Synonymen wie
# diesem ohnehin nicht helfen würde, siehe FALLSTRICKE #21 zum Grenzfall reiner
# Zeichenketten-Ähnlichkeit).
TITLE_AND_TAGS_PROMPT_TEMPLATE = (
    "Du bekommst das Bild der ersten Seite eines deutschen Geschäftsbriefs "
    "(z.B. Rechnung, Versicherungsschreiben, Behördenschreiben).\n\n"
    "Aufgabe 1 - Titel: ein kurzer, prägnanter Titel für dieses Dokument (max. 8 Wörter).{style_block}\n\n"
    "Aufgabe 2 - Tags: bis zu 5 passende Schlagworte zur Einordnung. Bereits vorhandene "
    "Tags in der Sammlung:\n{tag_catalog}\n"
    "Verwende WENN MÖGLICH einen bereits vorhandenen Tag aus dieser Liste, auch wenn der "
    "Wortlaut leicht abweicht (z.B. 'Auto' statt 'Kfz' - dann den vorhandenen Tag wählen). "
    "Erstelle nur dann ein neues Tag, wenn wirklich keine passende vorhandene Kategorie existiert. "
    + TAG_FORM_REGEL + "\n\n"
    'Antworte AUSSCHLIESSLICH mit einem JSON-Objekt in genau diesem Format, ohne weiteren Text:\n'
    '{{"title": "...", "tags": ["...", "..."]}}'
)

# Wird nur eingefügt, wenn Stilbeispiele vorhanden sind (siehe suggest_title_and_tags) -
# hilft gegen uneinheitliche Titel bei thematisch gleichen Dokumenten im selben Ordner
# (z.B. "Beitragsrechnung Haftpflichtversicherung" vs. "Versicherungsrechnung Musterstadt" vs.
# "Versicherungsbeleg Hermann Mustermann" für denselben Versicherer/Zweck), ohne eine starre
# Titel-Vorlage zu erzwingen (manche Dokumente im Ordner weichen inhaltlich ab).
STYLE_BLOCK_TEMPLATE = (
    " Bereits vergebene Titel anderer Dokumente im selben Ordner (falls thematisch "
    "passend, im gleichen Stil benennen - keine Pflicht, wenn das Dokument inhaltlich "
    "abweicht):\n{examples}"
)


def _generate(payload, base_url, timeout):
    """
    Führt den eigentlichen POST an /api/generate aus und liefert den geparsten
    JSON-Body. Bei einem HTTPError wird der Response-BODY ausgelesen und an die
    Fehlermeldung angehängt (siehe FALLSTRICKE #29): Ollama liefert dort die
    eigentliche, sofort verwertbare Diagnose (z.B. "exceed_context_size_error"),
    die urllib sonst verschluckt (nur "HTTP Error 400: Bad Request" ohne Grund).

    Schickt immer "think": false mit (Modell-Prüfstand 27.10.2026): denkende Modelle wie
    qwen3.5/gemma4 schreiben sonst vor jeder Antwort seitenlange Überlegungen (Minuten statt
    Sekunden je Dokument); nicht denkende Modelle und ältere Ollama-Versionen ignorieren das Feld.
    """
    payload = dict(payload)
    payload.setdefault("think", False)
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # Aktivitätsanzeige: KI-Antworten dauern auf schwacher Hardware lange - die
    # Menüleiste zeigt "KI antwortet… (14 s)", auch aus Hintergrund-Threads (aktivitaet.py)
    with aktivitaet.phase(f"KI antwortet ({payload.get('model', '')})…", nebensache=True):
        try:
            with urllib.request.urlopen(req, timeout=wirksamer_timeout(timeout)) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise urllib.error.HTTPError(e.url, e.code, f"{e.reason} — {detail}", e.headers, None) from e


def is_reachable(base_url=DEFAULT_URL, timeout=1.5):
    """Schneller Erreichbarkeits-Check, z.B. für einen 'Verbindung testen'-Button."""
    try:
        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def list_models(base_url=DEFAULT_URL, timeout=3):
    """Namen aller auf dem Server geladenen (per 'ollama pull' gezogenen) Modelle."""
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return [m.get("name", "") for m in data.get("models", [])]


def geladene_modelle(base_url=DEFAULT_URL, timeout=5):
    """
    GET /api/ps: die gerade im Speicher liegenden Modelle als {name: {"size": Bytes, "size_vram": Bytes}}.
    size_vram == 0 heißt: das Modell rechnet auf der CPU (siehe gpu_status).
    """
    with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/ps", timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return {m.get("name", ""): {"size": int(m.get("size") or 0), "size_vram": int(m.get("size_vram") or 0)}
            for m in data.get("models", [])}


def _passt_modellname(name, model):
    return name == model or (":" not in model and name.startswith(model + ":"))


def gpu_status(base_url=DEFAULT_URL, model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT):
    """
    Läuft das Modell auf der Grafikkarte? Liefert (status, details) mit status
    'gpu' | 'cpu' | 'teilweise' | 'unbekannt'. Ist das Modell noch nicht geladen, wird es
    mit einem Mini-Prompt geladen (dauert beim ersten Mal einige Sekunden).

    Anlass 12.09.2026: Nach einem NVIDIA-Treiber-Update (Kernel-Modul und Bibliothek passten
    nicht mehr zusammen) rechnete der Server STILL auf der CPU - Textaufrufe klappten in
    Sekunden, Bild-Aufrufe brauchten Minuten und liefen in Musterstadt in den Timeout. Weder
    Erreichbarkeit noch Modellliste zeigen das; nur /api/ps mit size_vram 0 (Wiki: KI-Infrastruktur).
    """
    try:
        ps = geladene_modelle(base_url)
        if not any(_passt_modellname(n, model) for n in ps):
            _generate({"model": model, "prompt": "OK", "stream": False, "options": {"num_predict": 1}},
                      base_url, timeout)
            ps = geladene_modelle(base_url)
        info = next((i for n, i in ps.items() if _passt_modellname(n, model)), None)
        if not info:
            return "unbekannt", "Modell nach dem Laden nicht in /api/ps gefunden."
        size, vram = info["size"], info["size_vram"]
        if size <= 0:
            return "unbekannt", "Keine Größenangabe vom Server."
        if vram <= 0:
            return "cpu", f"{size / 1e9:.1f} GB im Arbeitsspeicher, 0 GB im Grafikspeicher"
        if vram < size * 0.95:
            return "teilweise", f"nur {vram / 1e9:.1f} von {size / 1e9:.1f} GB im Grafikspeicher"
        return "gpu", f"{vram / 1e9:.1f} GB im Grafikspeicher"
    except Exception as e:
        return "unbekannt", str(e)


def suggest_title(image_bytes, base_url=DEFAULT_URL, model=DEFAULT_MODEL,
                   prompt=TITLE_PROMPT, timeout=DEFAULT_TIMEOUT):
    """
    Schickt ein Seitenbild an ein multimodales Ollama-Modell und liefert den
    vorgeschlagenen Titel als String. Wirft bei Verbindungs-/Server-Fehlern eine
    Exception weiter - der Aufrufer entscheidet über Fallback/Anzeige (siehe
    tools/ai_title_suggest.py: einzelne fehlgeschlagene Dokumente stoppen nicht
    die ganze Stapelverarbeitung).
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [base64.b64encode(image_bytes).decode("ascii")],
        "stream": False,
    }
    data = _generate(payload, base_url, timeout)
    return _clean_title(data.get("response", ""))


def _clean_title(text):
    """Räumt typische Modell-Ausgaben auf: Anführungszeichen, Zeilenumbrüche, Mehrfach-Leerzeichen."""
    text = text.strip().strip('"').strip("'")
    return " ".join(text.split())


def suggest_title_and_tags(image_bytes, known_tags=None, style_examples=None, base_url=DEFAULT_URL,
                            model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT):
    """
    Wie suggest_title, liefert aber zusätzlich passende Tag-Vorschläge in einem einzigen
    Modellaufruf zurück (spart eine zweite Anfrage). `known_tags` sollte der komplette
    zuweisbare Tag-Katalog der Sammlung sein (siehe tag_manager.get_known_tags) - das
    Modell wird angewiesen, daraus bevorzugt wiederzuverwenden statt Duplikate zu erfinden.
    `style_examples` sind optionale bereits vergebene Titel anderer Dokumente im selben
    Ordner (siehe tools/ai_title_suggest.sibling_title_examples) - dienen als Stilvorbild,
    damit thematisch gleiche Dokumente tendenziell ähnlich benannt werden.
    "format": "json" nutzt Ollamas eingebauten JSON-Modus für zuverlässigere Antworten;
    _parse_title_and_tags federt trotzdem ab, falls das Modell sich nicht daran hält.
    Gibt {"title": str, "tags": [str, ...]} zurück (leer bei nicht auswertbarer Antwort).
    """
    catalog = ", ".join(known_tags) if known_tags else "(noch keine)"
    style_block = ""
    if style_examples:
        style_block = STYLE_BLOCK_TEMPLATE.format(examples="\n".join(f"- {t}" for t in style_examples))
    prompt = TITLE_AND_TAGS_PROMPT_TEMPLATE.format(tag_catalog=catalog, style_block=style_block)
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [base64.b64encode(image_bytes).decode("ascii")],
        "stream": False,
        "format": "json",
        "options": {"num_ctx": _geschaetzter_num_ctx(prompt)},
    }
    data = _generate(payload, base_url, timeout)
    return _parse_title_and_tags(data.get("response", ""))


# Prompt der Vollautomatik (Seniorenmodus, siehe KONZEPT_SENIORENMODUS.md):
# EIN Aufruf liefert Titel, Tags, Absender, Dokumentdatum und einen Ordnernamen
# in Telefonbuch-Form ('Carius, Dr. Emil (Zahnarzt)' - unter C auffindbar, aber
# Titel und Beruf bleiben lesbar; Nutzer-Entscheidung 29.08.2026). BEWUSST KEINE
# Zielordner-WAHL aus einer Liste (siehe suggest_filing-Docstring: bei vielen
# Ordner-Kandidaten unzuverlässig) - den Abgleich gegen vorhandene Ordner und die
# Einsortierung in Buchstabengruppen übernimmt deterministischer Code in auto_pilot.
# Der Ordnername ist reine FORMATIERUNG des Absenders, kein Suchen - das kann das
# Modell; auto_pilot prüft ihn trotzdem nach (Mindestlänge, verbotene Zeichen).
FILING_PROMPT_TEMPLATE = (
    "Du bekommst das Bild der ersten Seite eines deutschen Geschäftsbriefs "
    "(z.B. Rechnung, Versicherungsschreiben, Behördenschreiben).\n\n"
    "Aufgabe 1 - Titel: ein kurzer, prägnanter Titel für dieses Dokument (max. 8 Wörter). "
    "Bei Verträgen, Policen, Kündigungen, Vollmachten und ähnlichen Vereinbarungen gehört "
    "der Vertragspartner bzw. die Gegenseite in den Titel (z.B. 'Mietvertrag mit Familie Huber', "
    "'Hausratversicherung Gentilia', 'Kündigung Stromvertrag E wie einfach'), damit der Titel "
    "auch ohne den Ordner verständlich ist.\n\n"
    "Aufgabe 2 - Tags: bis zu 5 Schlagworte, die sagen, worum es im Dokument geht (Art und "
    "Thema). Bereits vorhandene Tags in der Sammlung:\n{tag_catalog}\n"
    "Verwende WENN MÖGLICH einen bereits vorhandenen Tag aus dieser Liste, auch wenn der "
    "Wortlaut leicht abweicht (z.B. 'Auto' statt 'Kfz' - dann den vorhandenen Tag wählen). "
    "Erstelle nur dann ein neues Tag, wenn wirklich keine passende vorhandene Kategorie existiert. "
    "Nenne die KONKRETE Art des Dokuments, wenn es eine hat: bei Versicherungen die Sparte "
    "(nicht nur 'Versicherung'), bei Steuern und Abgaben die genaue Art (z.B. 'Grundsteuer' - "
    "nicht nur 'Steuer'). " + TAG_FORM_REGEL + " Absender, Empfänger und Objekt haben eigene "
    "Felder (Aufgaben 3, 6 und 7) und gehören NICHT in die Tags.\n\n"
    "Aufgabe 3 - Absender: der Name der Firma, Behörde oder Organisation, die das Dokument "
    "verschickt hat - kurz und ohne Rechtsform-Zusatz (z.B. 'Gentilia', 'Stadtwerke Musterstadt', "
    "'Finanzamt Musterstadt'). Nimm den ausgeschriebenen Namen aus dem Briefkopf oder der "
    "Unterschriftenzeile (z.B. 'Bayerisches Landesamt für Steuern'), NICHT die abgekürzte "
    "Rücksendezeile über dem Anschriftenfeld (wie 'Bay. LfSt, PF 0151 Straubing') und keine "
    "Postfach-, Postleitzahl- oder Straßenangaben. Wenn nicht erkennbar, leer lassen.\n\n"
    "Aufgabe 4 - Datum: das Datum des Dokuments (Briefdatum/Rechnungsdatum, NICHT ein "
    "Fälligkeits- oder Vertragsbeginn-Datum) im Format JJJJ-MM-TT. Wenn nicht sicher "
    "erkennbar, leer lassen - NICHT raten.\n\n"
    "Aufgabe 5 - Ordnername: ein Ablage-Ordnername für diesen Absender wie in einem "
    "Telefonbuch. Bei einer Firma, Behörde oder Organisation: der Firmenname ohne "
    "Rechtsform, ggf. mit Ort (z.B. 'Gentilia', 'Stadtwerke Musterstadt', 'Finanzamt Musterstadt'). "
    "Bei einer Person (Arzt, Anwalt, Handwerker, Privatperson): 'Nachname, Titel Vorname "
    "(Beruf)' - z.B. 'Carius, Dr. Emil (Zahnarzt)' oder 'Kehrmann, Fritz (Kaminkehrer)'. "
    "Der Ordnername bezeichnet IMMER den Absender aus Aufgabe 3 - NIEMALS den Empfänger "
    "oder Adressaten des Briefs (die Person im Anschriftenfeld). Verwende nur Wörter, die "
    "tatsächlich im Dokument stehen. Wenn der Absender nicht erkennbar ist, leer lassen.\n\n"
    "Aufgabe 6 - Empfänger: die Person, an die der Brief adressiert ist (der Name im "
    "Anschriftenfeld), als 'Vorname Nachname' ohne Anrede, Titel und Adresse (z.B. "
    "'Hermann Mustermann'). Sind mehrere Personen angesprochen, alle nennen und mit ' und ' "
    "trennen (z.B. 'Hermann Mustermann und Werner Mustermann'). Steht dort keine Person oder ist "
    "der Name nicht sicher lesbar, leer lassen - NICHT raten.\n\n"
    "Aufgabe 7 - Objekt und Ort: Bezieht sich das Dokument auf ein bestimmtes Objekt - "
    "ein Grundstück, ein Haus, eine Wohnung oder ein Fahrzeug? Dann in 'objekt' dessen "
    "Bezeichnung: Straße mit Hausnummer (ggf. Wohnungsnummer) oder amtliches Kennzeichen "
    "(z.B. 'Zum Alten Fass 1', 'Weidenstr. 8 Whg 2', 'MUS-XY 123') - OHNE Postleitzahl "
    "und OHNE Ortsnamen. Die Ortschaft bzw. der Ortsteil dazu gehört stattdessen in 'ort' "
    "(z.B. 'Musterstadt', 'Musterheim'). Betrifft das Dokument mehrere Objekte, alle nennen und "
    "mit ' und ' trennen. Bei Versicherungs- und Abrechnungsdokumenten steht das Objekt "
    "oft als beschriftete Angabe direkt auf dem Dokument - achte auf Felder wie "
    "'Versicherungsort', 'Risikoanschrift', 'versichertes Objekt', 'Abrechnungsobjekt', "
    "'Objekt' oder 'Liegenschaft' und übernimm genau diese Adresse (wieder ohne "
    "Postleitzahl und Ortsname). Geht es um kein bestimmtes Objekt (normale Rechnung, "
    "Arztbrief, Kontoauszug) oder ist die Bezeichnung nicht sicher lesbar: beide leer lassen. "
    "NIEMALS die Anschrift des Empfängers einsetzen, NICHT den bloßen Sitz des Absenders "
    "oder einer Firma/Gemeinschaft (es zählt das Objekt, um das es inhaltlich geht) und "
    "NICHT raten.\n\n"
    "{kategorien_block}"
    'Antworte AUSSCHLIESSLICH mit einem JSON-Objekt in genau diesem Format, ohne weiteren Text:\n'
    '{{"title": "...", "tags": ["...", "..."], "absender": "...", "datum": "JJJJ-MM-TT", '
    '"ordnername": "...", "empfaenger": "...", "objekt": "...", "ort": "...", '
    '"tag_kategorien": {{"neues Tag": "Kategorie"}}}}'
)

# Aufgabe 8 nur, wenn der Tag-Katalog Kategorien (graue Struktur-Knoten) hat: neue Tags
# sollen dort einsortiert werden, wo ein Mensch sie suchen würde (Nutzer-Entscheidung
# 30.08.2026: der Katalog wächst automatisch, "einen falschen Tag löschen ist leichter als
# einen von Hand anlegen"). Die Kategorie ist reine Zuordnung aus einer kurzen Liste - das
# kann das Modell; auto_pilot prüft nach, dass die Antwort wirklich in der Liste steht.
KATEGORIEN_BLOCK_TEMPLATE = (
    "Aufgabe 8 - Kategorie neuer Tags: Der Tag-Katalog ist in diese Kategorien gegliedert:\n"
    "{kategorien}\n"
    "Ordne jedes Tag aus Aufgabe 2, das NICHT in der Liste vorhandener Tags steht, genau "
    "einer dieser Kategorien zu (nur Namen aus dieser Liste verwenden). Die Schlüssel in "
    "tag_kategorien sind EXAKT die Tag-Texte aus Aufgabe 2 - nicht der Titel, nicht der "
    "Absender. Vorhandene Tags nicht aufführen; gibt es keine neuen Tags, ein leeres Objekt {{}}.\n\n"
)


def suggest_filing(image_bytes, known_tags=None, base_url=DEFAULT_URL,
                    model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT, kategorien=None):
    """
    Der eine KI-Aufruf der Vollautomatik (Seniorenmodus): liefert Titel, Tags,
    Absender und Dokumentdatum in einem einzigen Vision-Aufruf (ein Roundtrip
    pro Dokument - die Netzwerklatenz ist der Flaschenhals, siehe die
    Erweitert-Stufen-Erfahrung). Der Zielordner wird bewusst NICHT von der KI
    gewählt - Live-Fund (13.07.2026, siehe FALLSTRICKE): bei >50 Ordner-
    Kandidaten wählte das Modell fast immer einen Auffangordner, selbst bei
    korrekt erkanntem Absender. Die Ordnerwahl übernimmt stattdessen
    deterministischer Code (auto_pilot.finde_passenden_ordner) anhand des
    hier gelieferten Absenders. Gibt ein Dict mit den Keys title/tags/
    absender/datum/ordnername/empfaenger/objekt/tag_kategorien zurück (fehlende Felder leer); wirft bei
    Verbindungs-/Server-Fehlern eine Exception weiter - der Aufrufer entscheidet (Batch
    läuft weiter bzw. Dokument bleibt im Posteingang liegen).

    :param kategorien: Kategorien des Tag-Katalogs (tag_manager.get_kategorien); nur dann
                       wird das Modell gebeten, NEUE Tags einer Kategorie zuzuordnen.
    """
    catalog = ", ".join(known_tags) if known_tags else "(noch keine)"
    kategorien_block = KATEGORIEN_BLOCK_TEMPLATE.format(kategorien=", ".join(kategorien)) if kategorien else ""
    prompt = FILING_PROMPT_TEMPLATE.format(tag_catalog=catalog, kategorien_block=kategorien_block)
    payload = {
        "model": model,
        "prompt": prompt,
        "images": [base64.b64encode(image_bytes).decode("ascii")],
        "stream": False,
        "format": "json",
        "options": {"num_ctx": _geschaetzter_num_ctx(prompt)},
    }
    data = _generate(payload, base_url, timeout)
    return _parse_filing(data.get("response", ""))


# Zweitmeinung zur Ordnerwahl (Modell-Prüfstand 27.10.2026): Entscheidungsmodelle wie
# clef-flash beantworten über Ollamas /v1/systemone Ja/Nein-Fragen mit einer Wahrscheinlichkeit
# ("noul") - hier je Ordner "gehört das Dokument hierher?". Anders als die frühere Bitte an ein
# Sprachmodell, sich EINEN Ordner aus einer langen Liste auszusuchen (FALLSTRICKE #30/#32),
# wird jeder Ordner einzeln bewertet; am KID-Bestand stimmte Platz 1 in 77 %, bei p >= 0.95
# mit klarem Abstand in 98 % der Fälle. Was daraus folgt, entscheidet auto_pilot.wende_zweitmeinung_an.
ORDNERWAHL_ZUSTAND = (
    "Eingescannter Brief (erste Seite) aus einer privaten Dokumentenablage in Deutschland. "
    "Die Ablage ist nach Absendern (Firmen, Behörden, Personen) bzw. nach Objekten geordnet. "
    "Das Dokument soll in genau einen der vorhandenen Ordner einsortiert werden.")
_PFADTRENNER = re.compile(r"[\\/]")


def waehle_ordner(image_bytes, ordner, base_url=DEFAULT_URL, model="clef-flash:9b", timeout=DEFAULT_TIMEOUT):
    """
    Lässt ein Entscheidungsmodell jeden Ordner bewerten und liefert die Rangliste
    [(ordner, wahrscheinlichkeit), ...], beste zuerst. Gefragt wird mit dem letzten
    Pfadteil ('A - B - C\\Stadtwerke' -> 'Stadtwerke'), zurück kommt der volle Pfad.
    Wirft Verbindungs-/Server-Fehler weiter (auch HTTP 404, wenn der Server zu alt ist
    oder das Modell kein Entscheidungsmodell ist).
    """
    ordner = list(ordner)
    if not ordner:
        return []
    fragen = {f"o{i:03d}": {"type": "noul",
                            "instructions": f"Gehört dieses Dokument in den Ordner „{_PFADTRENNER.split(o)[-1]}“?"}
              for i, o in enumerate(ordner)}
    payload = {"model": model, "state": ORDNERWAHL_ZUSTAND, "questions": fragen,
               "images": [base64.b64encode(image_bytes).decode("ascii")]}
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/v1/systemone",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with aktivitaet.phase(f"KI wählt den Ordner ({model})…", nebensache=True):
        try:
            with urllib.request.urlopen(req, timeout=wirksamer_timeout(timeout)) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise urllib.error.HTTPError(e.url, e.code, f"{e.reason} — {detail}", e.headers, None) from e
    antworten = data.get("answers") or {}
    rangliste = []
    for schluessel, o in zip(fragen, ordner):
        try:
            p = float((antworten.get(schluessel) or {}).get("noul") or 0.0)
        except (TypeError, ValueError):
            p = 0.0
        rangliste.append((o, p))
    return sorted(rangliste, key=lambda op: -op[1])


def _parse_filing(text):
    """Parst die Vollautomatik-Antwort robust (gleiche Strategie wie _parse_title_and_tags), fehlende/kaputte Felder werden leer."""
    basis = _parse_title_and_tags(text)  # title + tags inkl. Bereinigung
    parsed = None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\{.*\}", text, re.DOTALL) if isinstance(text, str) else None
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = None
    if not isinstance(parsed, dict):
        parsed = {}
    return {
        "title": basis["title"],
        "tags": basis["tags"],
        "absender": str(parsed.get("absender", "") or "").strip(),
        "datum": str(parsed.get("datum", "") or "").strip(),
        "ordnername": str(parsed.get("ordnername", "") or "").strip(),
        "empfaenger": str(parsed.get("empfaenger", "") or "").strip(),
        "objekt": str(parsed.get("objekt", "") or "").strip(),
        "ort": str(parsed.get("ort", "") or "").strip(),
        "tag_kategorien": _parse_tag_kategorien(parsed.get("tag_kategorien")),
    }


def _parse_tag_kategorien(roh):
    """{Tag: Kategorie} aus der Antwort - nur ein echtes Objekt mit nicht-leeren Strings zählt."""
    if not isinstance(roh, dict):
        return {}
    return {str(k).strip(): str(v).strip() for k, v in roh.items()
            if str(k).strip() and v is not None and str(v).strip()}


# KI-Zweitprüfung eines Dubletten-Verdachts (Nutzer-Entscheidung 06.09.2026): Die
# deterministische Stufe B (dubletten_pruefung.py) meldet bei unscharfen Text-/Bild-
# Treffern auch Fehlalarme (Serienbriefe, Monatsrechnungen gleicher Absender). Das
# Vision-Modell bekommt BEIDE erste Seiten und soll die konkreten Angaben vergleichen -
# genau das, was Jaccard/dHash nicht können. Die Entscheidung, was mit der Antwort
# passiert, trifft wie immer deterministischer Code (dubletten_pruefung).
DUBLETTEN_PROMPT = (
    "Du bekommst die Bilder der ersten Seiten von ZWEI eingescannten deutschen "
    "Geschäftsdokumenten, die sich ähnlich sehen. Entscheide, ob es sich um DASSELBE "
    "Dokument handelt (z.B. doppelt gescannt oder kopiert) oder um ZWEI VERSCHIEDENE "
    "Dokumente (z.B. zwei Monatsrechnungen desselben Absenders mit gleichem Layout).\n\n"
    "Vergleiche dazu die konkreten Angaben beider Seiten: Rechnungs-/Kundennummer, "
    "Aktenzeichen, Datum, Beträge, Abrechnungszeiträume, Zählerstände. Unterscheiden "
    "sich solche Angaben, sind es VERSCHIEDENE Dokumente ('nein'). Gleiches Layout und "
    "gleicher Absender allein bedeuten NICHT dasselbe Dokument. Kannst du die "
    "entscheidenden Angaben nicht sicher lesen, antworte 'unsicher' - NICHT raten.\n\n"
    'Antworte AUSSCHLIESSLICH mit einem JSON-Objekt in genau diesem Format, ohne weiteren Text:\n'
    '{"gleiches_dokument": "ja oder nein oder unsicher", '
    '"begruendung": "ein kurzer Satz mit dem entscheidenden Unterschied bzw. der Übereinstimmung"}'
)

# Einzelbild-Ablesung für die Dubletten-Zweitprüfung (Live-Fund 06.09.2026: Bei ZWEI
# Bildern in einem Aufruf vermischt qwen2.5vl:7b die Dokumente - es las die Felder von
# Bild 1 und wiederholte sie für Bild 2, wodurch verschiedene Wohnungs-Abrechnungen als
# "dieselbe Nummer, derselbe Betrag" galten. Einzelbild-Lesung ist dagegen erprobt
# zuverlässig - die gesamte Vollautomatik basiert darauf.)
DUBLETTEN_MERKMAL_PROMPT = (
    "Du bekommst das Bild der ersten Seite eines eingescannten deutschen "
    "Geschäftsdokuments. Lies folgende Angaben ab, exakt wie gedruckt "
    "(nicht raten - was nicht sicher lesbar ist, leer lassen):\n"
    "- kennnummer: die Rechnungs-, Beleg- oder Kundennummer bzw. das Aktenzeichen\n"
    "- datum: das Dokumentdatum\n"
    "- betrag: der End- bzw. Rechnungsbetrag\n\n"
    'Antworte AUSSCHLIESSLICH mit einem JSON-Objekt in genau diesem Format, ohne weiteren Text:\n'
    '{"kennnummer": "...", "datum": "...", "betrag": "..."}'
)


def _lies_dublettenmerkmale(bild, base_url, model, timeout):
    """Liest kennnummer/datum/betrag EINER Seite ab (Einzelbild, siehe DUBLETTEN_MERKMAL_PROMPT)."""
    payload = {
        "model": model,
        "prompt": DUBLETTEN_MERKMAL_PROMPT,
        "images": [base64.b64encode(bild).decode("ascii")],
        "stream": False,
        "format": "json",
        "options": {"num_ctx": _geschaetzter_num_ctx(DUBLETTEN_MERKMAL_PROMPT)},
    }
    data = _generate(payload, base_url, timeout)
    try:
        parsed = json.loads(data.get("response", ""))
    except (json.JSONDecodeError, TypeError):
        parsed = None
    return parsed if isinstance(parsed, dict) else {}


def pruefe_dublette(bild_neu, bild_alt, base_url=DEFAULT_URL, model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT):
    """
    Fragt das Vision-Modell, ob zwei Seitenbilder dasselbe Dokument zeigen
    (KI-Zweitprüfung der Stufe-B-Dubletten-Erkennung). Liefert
    {"gleiches_dokument": "ja"|"nein"|"unsicher", "begruendung": str} - bei nicht
    auswertbarer Antwort "unsicher" (fail-safe: der Verdacht bleibt dann bestehen).
    Wirft Verbindungs-/Server-Fehler weiter, der Aufrufer entscheidet.

    Arbeitsteilung (Live-Funde 06.09.2026): Das Modell LIEST nur - jede Seite in einem
    EIGENEN Aufruf (bei zwei Bildern auf einmal vermischt es die Dokumente); den
    Vergleich der abgelesenen Felder übernimmt _vergleiche_dublettenmerkmale
    deterministisch. Nur wenn die Felder nicht belastbar lesbar sind, fällt die
    Prüfung auf das (wackligere) Zwei-Bilder-Urteil des Modells zurück.
    """
    merkmale_neu = _lies_dublettenmerkmale(bild_neu, base_url, model, timeout)
    merkmale_alt = _lies_dublettenmerkmale(bild_alt, base_url, model, timeout)
    entschieden = _vergleiche_dublettenmerkmale(merkmale_neu, merkmale_alt)
    if entschieden is not None:
        return entschieden

    payload = {
        "model": model,
        "prompt": DUBLETTEN_PROMPT,
        "images": [base64.b64encode(bild_neu).decode("ascii"),
                   base64.b64encode(bild_alt).decode("ascii")],
        "stream": False,
        "format": "json",
        "options": {"num_ctx": _geschaetzter_num_ctx(DUBLETTEN_PROMPT, bilder=2)},
    }
    data = _generate(payload, base_url, timeout)
    return _parse_dubletten_antwort(data.get("response", ""))


def _norm_kennnummer(wert):
    """Kennnummer für den Vergleich normalisieren: nur Buchstaben/Ziffern, Kleinschreibung."""
    return re.sub(r"[^0-9a-zäöüß]", "", str(wert or "").lower())


def _norm_betrag(wert):
    """Betrag für den Vergleich normalisieren: nur die Ziffern (Währung, Punkte, Kommas egal)."""
    return re.sub(r"[^0-9]", "", str(wert or ""))


def _vergleiche_dublettenmerkmale(neu, alt):
    """
    Deterministischer Vergleich der pro Seite abgelesenen Felder (kennnummer/betrag) -
    "das Modell liest ab, der Code vergleicht" (Live-Funde 06.09.2026: das Modell-Urteil
    selbst war unzuverlässig - identisch abgelesene Nummern galten als "unterschiedlich").
    Eine gleiche Kennnummer allein beweist dabei KEINE Dublette: Abrechnungen
    verschiedener Wohnungen derselben Liegenschaft teilen sich die Objektnummer
    (real: Iqua '5112/5734/2099' auf allen vier Wohnungs-Abrechnungen). Regeln:
    - verschiedene Kennnummern (je >= 5 Zeichen normalisiert; ein bloßes Jahr wie
      '2019' zählt nicht) -> "nein"
    - gleiche Kennnummer UND gleicher Betrag -> "ja" (doppelter Scan)
    - gleiche Kennnummer, aber verschiedene Beträge -> "nein" (geteilte Objektnummer)
    :return: Antwort-Dict wie pruefe_dublette, oder None wenn die Felder nicht reichen
             (dann entscheidet das Zwei-Bilder-Urteil des Modells).
    """
    kenn_neu = " ".join(str((neu or {}).get("kennnummer", "")).split())
    kenn_alt = " ".join(str((alt or {}).get("kennnummer", "")).split())
    k1, k2 = _norm_kennnummer(kenn_neu), _norm_kennnummer(kenn_alt)
    b1, b2 = _norm_betrag((neu or {}).get("betrag")), _norm_betrag((alt or {}).get("betrag"))
    if len(k1) < 5 or len(k2) < 5:
        return None
    if k1 != k2:
        return {"gleiches_dokument": "nein",
                "begruendung": f"verschiedene Rechnungs-/Kennnummern ('{kenn_neu}' gegenüber '{kenn_alt}')"}
    if len(b1) >= 3 and len(b2) >= 3:
        if b1 == b2:
            return {"gleiches_dokument": "ja",
                    "begruendung": f"beide Seiten tragen dieselbe Rechnungs-/Kennnummer "
                                   f"'{kenn_neu}' und denselben Betrag"}
        return {"gleiches_dokument": "nein",
                "begruendung": f"gleiche Kenn-/Objektnummer '{kenn_neu}', aber verschiedene "
                               f"Beträge - vermutlich verschiedene Dokumente derselben Sache"}
    return None


def _parse_dubletten_antwort(text):
    """Parst das Zwei-Bilder-Urteil robust; alles außer einem klaren ja/nein wird 'unsicher'."""
    parsed = None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\{.*\}", text, re.DOTALL) if isinstance(text, str) else None
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = None
    if not isinstance(parsed, dict):
        parsed = {}
    antwort = str(parsed.get("gleiches_dokument", "") or "").strip().lower()
    if antwort not in ("ja", "nein"):
        antwort = "unsicher"
    return {"gleiches_dokument": antwort,
            "begruendung": " ".join(str(parsed.get("begruendung", "") or "").split())}


# {text} wird durch den rohen Re-OCR-Text (siehe index_manager.upgrade_to_meister_tier)
# ersetzt. Ausdrücklich NUR Erkennungsfehler korrigieren lassen, keine Inhalte ergänzen -
# das Modell soll den vorhandenen (ggf. noch immer unvollständigen) Text plausibilisieren,
# nicht neue Fakten erfinden (Risiko bei generativen Modellen sonst besonders hoch).
CLEAN_TEXT_PROMPT_TEMPLATE = (
    "Der folgende Text stammt aus einer automatischen Texterkennung (OCR) eines "
    "eingescannten deutschen Geschäftsbriefs und enthält typische OCR-Fehler "
    "(vertauschte/fehlende Zeichen, falsch erkannte Wörter, gelegentlich falsche "
    "Zeilenreihenfolge). Korrigiere AUSSCHLIESSLICH offensichtliche Erkennungsfehler "
    "(Rechtschreibung, Wortgrenzen, Zeichenfehler). Erfinde KEINE neuen Inhalte, Zahlen, "
    "Namen oder Beträge hinzu und lasse den Sinn unverändert. Ist eine Stelle nicht "
    "sicher zu entziffern, lasse sie wie im Original stehen statt zu raten. Antworte "
    "AUSSCHLIESSLICH mit dem korrigierten Text, ohne Einleitung, Erklärung oder Kommentar."
    "\n\n--- OCR-TEXT ---\n{text}"
)


def suggest_cleaned_text(raw_text, base_url=DEFAULT_URL, model=DEFAULT_MODEL, timeout=CLEAN_TEXT_TIMEOUT):
    """
    Schickt rohen (Re-)OCR-Text an ein Ollama-Textmodell zur KI-Prüfung/Bereinigung
    (Meister-Stufe, siehe index_manager.upgrade_to_meister_tier). Reiner Textaufruf ohne
    Bild - anders als suggest_title_and_tags kein "format": "json", da eine freie
    Textantwort erwartet wird. Liefert bei leerem Eingabetext sofort "" zurück (kein
    sinnloser Modellaufruf für Dokumente ohne Re-OCR-Text). Wirft bei Verbindungs-/
    Server-Fehlern eine Exception weiter - der Aufrufer (Batch-Lauf) entscheidet, ob ein
    einzelnes fehlgeschlagenes Dokument die restliche Verarbeitung stoppt.
    """
    if not raw_text or not raw_text.strip():
        return ""
    prompt = CLEAN_TEXT_PROMPT_TEMPLATE.format(text=raw_text)
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    data = _generate(payload, base_url, timeout)
    return data.get("response", "").strip()


def _parse_title_and_tags(text):
    """Parst die Modell-Antwort robust: direktes JSON, sonst das erste {...}-Objekt im Text."""
    parsed = None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\{.*\}", text, re.DOTALL) if isinstance(text, str) else None
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = None

    if not isinstance(parsed, dict):
        return {"title": "", "tags": []}

    title = _clean_title(str(parsed.get("title", "")))
    tags_raw = parsed.get("tags", [])
    tags = [str(t).strip() for t in tags_raw if str(t).strip()] if isinstance(tags_raw, list) else []
    return {"title": title, "tags": tags}

