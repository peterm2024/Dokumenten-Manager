"""
Tag-Katalog ohne Oberfläche (Etappe 10, KONZEPT_DIENSTMODUS Befund 2, 17.11.2026). Nur Standardbibliothek.

Der Katalog liegt als Baum in tags.json: eine Liste von Knoten {"text", "children", "is_structural", "is_synonym"}.
Diese Funktionen beantworten darauf dieselben Fragen wie bisher der Tag-Baum im Hauptfenster (TagManager), damit
die Vollautomatik sie ohne Hauptfenster und aus ihrem eigenen Thread beantworten kann (die Dubletten-Merkmale
braucht nur noch das Hauptfenster):
- `bekannte_tags`: zuweisbare Tags (ohne graue Kategorien und Synonyme), ohne Doppelte
- `kategorien`: graue Struktur-Kategorien
- `tag_parents`: Oberkategorien-Zuordnung der Auto-Hierarchie {tag (klein): [zuweisbare Parent-Tags von oben]}
- `synonyme`: {synonym (klein): Ziel-Tag darüber}
- `tags_in_kategorie` / `merkmale_fuer_dubletten`: Unterscheidungs-Tags der Dubletten-Prüfung

Der TagManager wandelt seinen Baum in dieselben Knoten um und ruft dieselben Funktionen auf - es gibt also nur
eine Fassung der Regeln. Bisher holte der Dienst den Katalog über den Hauptthread und wartete darauf höchstens
5 s; war das Hauptfenster beschäftigt, lief die Runde still mit leerem Katalog weiter (FALLSTRICKE #131).

Regeln wie beim Aufbau des Baums (tag_editor._insert_nodes): Ein Knoten, dessen Name auf derselben Ebene schon
vorkam (Groß/Klein egal), fällt samt Inhalt weg; „Synonym“ hat Vorrang vor „Kategorie“.
"""

import json


def lade(pfad):
    """
    Katalog aus tags.json, sonst aus ihrer Sicherung tags.json.bak, sonst None. Nur lesend: Anders als der Tag-Editor
    legt diese Funktion eine beschädigte Datei NICHT beiseite - das bleibt dem Hauptfenster vorbehalten.
    """
    for datei in (pfad, pfad + ".bak"):
        try:
            with open(datei, encoding="utf-8") as f:
                daten = json.load(f)
        except (OSError, ValueError):
            continue
        if isinstance(daten, list):
            return bereinige(daten)
    return None


def bereinige(knoten):
    """Knoten wie im Baum: ohne Doppelte je Ebene, Synonym vor Kategorie, ohne leere Namen."""
    ergebnis, gesehen = [], set()
    for k in knoten or []:
        if not isinstance(k, dict):
            continue
        text = str(k.get("text", ""))
        if not text.strip() or text.lower() in gesehen:
            continue
        gesehen.add(text.lower())
        synonym = bool(k.get("is_synonym"))
        ergebnis.append({"text": text, "is_synonym": synonym,
                         "is_structural": bool(k.get("is_structural")) and not synonym,
                         "children": bereinige(k.get("children"))})
    return ergebnis


def _zuweisbar(k):
    return not k.get("is_structural") and not k.get("is_synonym")


def bekannte_tags(knoten):
    """Zuweisbare Tags in Baum-Reihenfolge, ohne Doppelte (Groß/Klein egal)."""
    tags, gesehen = [], set()

    def gehe(liste):
        for k in liste:
            if _zuweisbar(k) and k["text"].lower() not in gesehen:
                gesehen.add(k["text"].lower())
                tags.append(k["text"])
            gehe(k["children"])

    gehe(knoten)
    return tags


def kategorien(knoten):
    """Namen der grauen Struktur-Kategorien in Baum-Reihenfolge, ohne Doppelte."""
    namen, gesehen = [], set()

    def gehe(liste):
        for k in liste:
            if k.get("is_structural") and k["text"].lower() not in gesehen:
                gesehen.add(k["text"].lower())
                namen.append(k["text"])
            gehe(k["children"])

    gehe(knoten)
    return namen


def tag_parents(knoten):
    """{tag (klein): [zuweisbare Parent-Tags von oben nach unten]} - nur Tags MIT zuweisbarem Parent; graue Kategorien
    zählen nicht als Parent. Bei Doppelten gilt das erste Vorkommen."""
    zuordnung = {}

    def gehe(liste, parents):
        for k in liste:
            zuweisbar = _zuweisbar(k)
            if zuweisbar and parents and k["text"].lower() not in zuordnung:
                zuordnung[k["text"].lower()] = list(parents)
            gehe(k["children"], parents + [k["text"]] if zuweisbar else parents)

    gehe(knoten, [])
    return zuordnung


def synonyme(knoten):
    """{synonym (klein): Ziel-Tag} - Ziel ist das nächste zuweisbare Tag über dem Synonym; ohne ein solches bleibt das
    Synonym wirkungslos. Unter einem Synonym liegt nichts Zuweisbares."""
    zuordnung = {}

    def gehe(liste, ziel):
        for k in liste:
            if k.get("is_synonym"):
                if ziel and k["text"].strip().lower() not in zuordnung:
                    zuordnung[k["text"].strip().lower()] = ziel
                continue
            gehe(k["children"], k["text"] if _zuweisbar(k) else ziel)

    gehe(knoten, "")
    return zuordnung


def tags_in_kategorie(knoten, kategorie):
    """Alle zuweisbaren Tags unter der ersten grauen Kategorie dieses Namens (Groß/Klein egal), [] ohne sie."""
    gesucht = (kategorie or "").strip().lower()

    def finde(liste):
        for k in liste:
            if k.get("is_structural") and k["text"].lower() == gesucht:
                return k
            treffer = finde(k["children"])
            if treffer:
                return treffer
        return None

    start = finde(knoten) if gesucht else None
    if start is None:
        return []
    tags = []

    def gehe(liste):
        for k in liste:
            if _zuweisbar(k):
                tags.append(k["text"])
            gehe(k["children"])

    gehe(start["children"])
    return tags


def merkmale_fuer_dubletten(knoten, varianten):
    """{kanonische Kategorie: [Tags]} - je Kategorie die erste Namensvariante, unter der es Tags gibt
    (`varianten` = auto_pilot.KATEGORIE_VARIANTEN)."""
    merkmale = {}
    for kanonisch, namen in varianten.items():
        gefunden = []
        for name in namen:
            gefunden = tags_in_kategorie(knoten, name)
            if gefunden:
                break
        merkmale[kanonisch] = gefunden
    return merkmale


def katalog_fuer_dienst(knoten):
    """Alles, was die Vollautomatik je Runde braucht, in einem Zug (seit 17.11.2026 ohne Dubletten-Merkmale: der
    Dienst prüft nicht mehr auf Dubletten)."""
    return {"known_tags": bekannte_tags(knoten), "kategorien": kategorien(knoten), "tag_eltern": tag_parents(knoten),
            "synonyme": synonyme(knoten)}
