"""
Entscheidungslogik der Vollautomatik (Seniorenmodus, siehe KONZEPT_SENIORENMODUS.md).

Grundprinzip: Die KI (ollama_client.suggest_filing) macht VORSCHLÄGE - ob ein
Dokument wirklich automatisch abgelegt werden darf ("sicher"), entscheidet
ausschließlich der deterministische, testbare Code hier. Bei jedem Zweifel wird
das Dokument als "unsicher" markiert und wandert später in den Unsicher-Ordner,
statt falsch einsortiert zu werden.

Schritt 1 (Analyse) ist reine Entscheidungslogik ohne Dateizugriffe. Schritt 2
(fuehre_entscheidung_aus) führt die geprüfte Entscheidung tatsächlich aus -
Metadaten/Umbenennen/Verschieben -, delegiert das eigentliche Verschieben aber
an einen von außen übergebenen Callable, um von Tkinter/der App unabhängig zu
bleiben (siehe dortige Docstring).

Seit Etappe 14 (23.11.2026) liegen vier Teile in eigenen Modulen: ordner_finden, titel_datum, tag_regeln und
ablage_ausfuehren. Hier stehen Entscheidung und Ablauf; die alten Namen werden weitergeleitet.
"""

import os

import eingangsstempel
import ollama_client
import ordner_aliase
import ordner_steckbrief
import ordnernamen
from pdf_handler import PDFHandler
from personen_namen import (ohne_eigene_namen, teile_empfaenger)
from titel_datum import (  # noqa: F401 - Weiterleitung, Aufrufer schreiben auto_pilot.<name>
    _VERBOTENE_ZEICHEN, _DATUM_FORMAT, _DATUM_DEUTSCH, _DATUM_ISO_LOCKER, MAX_TITEL_LAENGE, baue_titel_wortschatz,
    korrigiere_titel, _bereinige_titel_fuer_dateiname, baue_dateiname, _DATEINAME_DATUM, _DATEINAME_DATUM_DEUTSCH,
    datum_aus_dateiname, normalisiere_datum, WOCHENTAGE, datum_aus_eingabe, _datum_ist_plausibel)
from ordner_finden import (  # noqa: F401 - Weiterleitung, Aufrufer schreiben auto_pilot.<name>
    POSTEINGANG_ORDNER, UNSICHER_ORDNER, SAMMEL_ORDNER, _RESERVIERTE_NAMEN, MIN_ORDNER_MATCH_LAENGE,
    MAX_ORDNER_LAENGE, _ANREDEN, _UMLAUT_MAP, _BUCHSTABENGRUPPE, _BUCHSTABENBEREICH, _ZIFFERNGRUPPE, kernname,
    sortierbuchstabe, finde_buchstabengruppe, buchstaben_der_gruppe, _BINDEWOERTER_AM_ENDE, bereinige_ordnername,
    _ohne_geraetenamen, _ADRESSTEIL, _ABKUERZUNG, _BINNENVERSAL, trenne_adresszeile, absender_ist_kuerzel,
    ordnername_passt_zum_absender, _NAMENS_RAUSCHEN, _namenswoerter, _mehrdeutige_woerter, _ganzes_wort,
    _namen_passen, _KUERZEL_ORDNER, _kuerzel_im_absender, finde_passenden_ordner, MIN_AEHNLICHKEITS_WORT,
    _GATTUNGSWOERTER, _editierdistanz, _woerter_aehnlich, finde_aehnlichen_ordner, _NUR_ADRESSE,
    ordnername_aus_adresse, _vergleichsname, _HINWEIS_TRENNER, finde_ordner_ueber_hinweise, finde_posteingaenge,
    finde_posteingang, sammle_posteingang_dokumente, sammle_ordnerliste)
from tag_regeln import (  # noqa: F401 - Weiterleitung, Aufrufer schreiben auto_pilot.<name>
    KATEGORIE_PERSONEN, KATEGORIE_OBJEKTE, KATEGORIE_VARIANTEN, korrigiere_tag, tags_mit_empfaenger,
    ergaenze_oberkategorien, ersetze_synonyme, _OBJEKT_TRENNER, _NUR_PLZ, _PLZ_PRAEFIX, MIN_OBJEKTLAENGE,
    _NUR_HAUSNUMMER, _HAUSNUMMER_AM_ENDE, _HAUSNUMMER_MIT_ORT, _SAMMEL_HAUSNUMMERN, _OBJEKT_WORT,
    ist_objektbezeichnung, ohne_plz, _ORT_SUFFIX, trenne_ort, objekte_ohne_ort, titel_mit_objekt, normiere_objekt,
    finde_objekt_schreibweise, teile_objekte, ohne_zielordner_tags, _kategorie_name, ohne_kategorien, MIN_NEUES_TAG,
    MAX_WOERTER_NEUES_TAG, _ENGLISCHE_FUELLWOERTER, _DATEIFORMATE, _ANREDE_IM_TAG, grund_gegen_neues_tag,
    ohne_unbrauchbare_neue_tags, bestimme_neue_tags)
from ablage_ausfuehren import (  # noqa: F401 - Weiterleitung, Aufrufer schreiben auto_pilot.<name>
    _gleicher_pfad, _naechster_freier_pfad, protokolliere, protokolliere_ergebnis, fuehre_entscheidung_aus)

# Ab dieser Länge wird ein Name zum NEUEN Ordner (Peter 05.11.2026: kurze Firmennamen sind häufig). Der Vergleich mit
# vorhandenen Ordnern bleibt bei MIN_ORDNER_MATCH_LAENGE, sonst passte 'Eis' auch auf 'Eisenwaren'.
MIN_NEUER_ORDNER = 3


# Entfernt 14.11.2026 (Etappe 9, FALLSTRICKE #129): `_verschiedene_absender` - „teilen zwei Namen nur ein Wort, sind es
# verschiedene Absender, neuer Ordner ohne Rückfrage“. In einer frischen Sammlung 53 Rückfragen weniger, in einer
# bestehenden 20 still falsch abgelegte Dokumente mehr: Menschen benennen Ordner kürzer, als die KI den Absender liest,
# die Regel verwarf gerade den richtigen Ordner, und das Ablage-Gedächtnis schickte die weiteren Briefe hinterher.


def ortswoerter_des_dokuments(ki_antwort):
    """Die Wörter des KI-Orts ('12345 Musterstadt' -> {'musterstadt'}), wie finde_aehnlichen_ordner sie vergleicht."""
    return set(_namenswoerter(ohne_plz(str((ki_antwort or {}).get("ort") or ""))))


def merke_orte(orte, gelesen):
    """
    Ortswörter eines gelesenen Dokuments (lies_dokument) in die Menge `orte` des Laufs aufnehmen
    (Peter 29.10.2026, Rest von FALLSTRICKE #83): Ablage-Vorschau und Vollautomatik merken sich so
    die Orte, die die KI bisher gelesen hat, und wählen bei 'Stadtwerke Musterstadt' den Ordner
    'Landratsamt Musterstadt' nicht mehr vor - auch wenn der Ort im Dokument selbst fehlt.
    Nur Wörter, die für die Ähnlichkeit überhaupt zählen (MIN_AEHNLICHKEITS_WORT).
    """
    if gelesen:
        orte.update(w for w in ortswoerter_des_dokuments(gelesen.get("ki_antwort"))
                    if len(w) >= MIN_AEHNLICHKEITS_WORT)
    return orte


def baue_entscheidung(pdf_path, ki_antwort, vorhandene_ordner, schreibschutz=None, vocabulary=None, aliase=None,
                      known_tags=None, kategorien=None, ignorierte_tags=None, tag_eltern=None,
                      synonyme=None, gedaechtnis=None, orte=None, textdaten=None, textwoerter=None, arzt=None):
    """
    Verwandelt den KI-Vorschlag (ollama_client.suggest_filing) in eine geprüfte
    Ablage-Entscheidung - reine Funktion, kein Dateisystem-/Netzwerkzugriff.

    :param vorhandene_ordner: relative Ordnerpfade der Sammlung (sammle_ordnerliste)
    :param schreibschutz: Ergebnis von PDFHandler.get_write_protection (oder None)
    :param vocabulary: Wortschatz (Counter) für die Titel-Korrektur, siehe korrigiere_titel; None = keine Korrektur
    :param aliase: Absender-Aliase {Absender: Zielordner} (ordner_aliase.lade_aliase); haben Vorrang
                   vor dem Namens-Matching. None/leer = keine Aliase
    :param known_tags: Tag-Katalog; KI-Tags, die dort fehlen, werden als neue_tags gemeldet
    :param kategorien: Kategorien des Katalogs (tag_manager.get_kategorien) für die Zuordnung neuer Tags
    :param ignorierte_tags: Ignorierliste (tag_ignorierliste.lade) - diese Tags schlägt die KI nie mehr vor
    :param tag_eltern: Oberkategorien-Zuordnung des Tag-Baums (tag_manager.get_tag_eltern)
                       für die Auto-Hierarchie, siehe ergaenze_oberkategorien; None = aus
    :param synonyme: Synonym-Zuordnung des Tag-Baums (tag_manager.get_synonyme), siehe ersetze_synonyme
    :param gedaechtnis: Ablage-Gedächtnis (ablage_gedaechtnis.Gedaechtnis) - nach den Aliasen, vor den
                        Namensregeln; None = aus
    :param orte: bisher gesehene Ortswörter des Laufs (merke_orte) - zählen wie der Ort des Dokuments
                 bei der Vorauswahl eines ähnlichen Ordners nicht mit (FALLSTRICKE #83); None = nur der eigene
    :param textdaten: Daten aus der Textebene (eingangsstempel.textdaten, von lies_dokument) - nahm die KI das
                      Datum eines Eingangsstempels, gilt das Briefdatum davor; None = KI-Datum unverändert
    :param textwoerter: Wörter der Textebene (ordnernamen.textwoerter, von lies_dokument) - ein Lesefehler der KI
                        im Ordnernamen bekommt die Schreibweise aus dem Text; None = Name wie von der KI
    :param arzt: Ärztin/Arzt aus der Textebene (ordnernamen.arzt_im_text, von lies_dokument) - ein Arztbrief bekommt
                 den Ordner „Dr. Nachname, Vorname (Fachrichtung)“ statt des Praxisnamens; None = KI-Name
    :return: Dict mit pdf_path, titel, titel_korrekturen, tags, tag_ersetzungen [(alt, neu)],
             neue_tags [(Tag, Kategorie)], tag_vorschlaege (Katalog-Tags der KI, nur zum Anklicken - B4a),
             datum, datum_stempel (das ersetzte Stempeldatum der KI oder ""),
             absender, ordnername, zielordner, ordner_neu, ordner_per_alias,
             ordner_gedaechtnis (Stimmen, 0 = Ordner nicht aus dem Gedächtnis),
             ordner_hinweis ('Tag'/'Dateiname'/''), neuer_dateiname, sicher, probleme (Liste von Gründen).
    """
    titel = (ki_antwort.get("title") or "").strip()
    titel, titel_korrekturen = korrigiere_titel(titel, vocabulary)
    # Objekt in den Titel (Nutzerwunsch 03.09.2026): macht Titel UND Dateinamen im
    # Ordner unterscheidbar - deterministisch aus dem Objekt-Feld, keine zweite KI nötig.
    objekte = objekte_ohne_ort(ki_antwort, known_tags, kategorien)
    titel = titel_mit_objekt(titel, objekte)
    tags, tag_kategorien = tags_mit_empfaenger(ki_antwort, ignorierte_tags, known_tags, vocabulary, kategorien)
    # Synonyme VOR der Katalog-Sperre und der Auto-Hierarchie: das Ziel-Tag ist ein Katalog-Tag
    # und bringt seine Oberkategorien selbst mit.
    tags, tag_ersetzungen = ersetze_synonyme(tags, synonyme)
    tags = ohne_kategorien(tags, kategorien)  # grau = nie vergeben, auch nicht automatisch
    tags = ergaenze_oberkategorien(tags, tag_eltern, ignorierte_tags)
    datum = normalisiere_datum(ki_antwort.get("datum"))
    datum_stempel, briefdatum = "", eingangsstempel.briefdatum_statt_stempel(datum, textdaten)
    if briefdatum:
        datum_stempel, datum = datum, briefdatum
    # Rücksendezeile statt Name ('Bay. LfSt, PF 0151 Straubing'): Adressteil weg, der Rest
    # ist der Alias-Schlüssel und Vergleichsname; ein reines Kürzel wird unten nie zum
    # neuen Ordner (siehe trenne_adresszeile / absender_ist_kuerzel).
    absender, war_adresszeile = trenne_adresszeile(ki_antwort.get("absender"))
    absender_kuerzel = absender_ist_kuerzel(absender)
    # Telefonbuch-Form von der KI ('Carius, Dr. Emil (Zahnarzt)') - aber nur, wenn sie
    # nachweislich aus dem Absender stammt (siehe ordnername_passt_zum_absender: die KI
    # lieferte sonst den Empfänger). Fehlt/verworfen: der Absender selbst ist der Ordnername.
    ordnername_ki, _ = trenne_adresszeile(ki_antwort.get("ordnername"))
    if ordnername_ki and (not ordnername_passt_zum_absender(ordnername_ki, absender)
                          or ordnernamen.ist_firma_in_telefonbuchform(ordnername_ki, absender)):
        ordnername_ki = ""
    roh = ordnername_ki or absender
    # Arztbrief: Ordner nach der Ärztin, nicht nach der Praxis - „Dr. Beispiel, Eva“ statt „Hausarztpraxis am Markt“
    # (Peter 22.11.2026, ordnernamen.arzt_ordner). Der Absender bleibt der Alias-Schlüssel; verglichen wird mit beidem.
    arzt_name = ordnernamen.arzt_ordner(ordnername_ki, absender, arzt, ki_antwort.get("empfaenger") or "")
    if arzt_name:
        roh = arzt_name
    # Namen neuer Ordner bleiben für Jahre (Frisch-Versuch 20./21.11.2026, ordnernamen.py): Schreibweise aus der
    # Textebene - „Haustchnik Mustergültig GmbH“ wird „Haustechnik Mustergültig GmbH“
    roh = ordnernamen.schreibweise_aus_text(roh, textwoerter)
    ordnername = bereinige_ordnername(ordnername_aus_adresse(roh))
    # Die Rechtsform fällt nur im Namen eines NEU angelegten Ordners weg. Verglichen wird weiter mit ihr: Ohne sie
    # traf 'Muster' den vorhandenen 'Muster Medizintechnik' sicher statt nachzufragen (so im Korpus 21.11.2026) - eine
    # Namensbereinigung soll keine Entscheidung ändern.
    ordnername_neu = bereinige_ordnername(ordnernamen.ohne_rechtsform(ordnername))
    # Mit vorhandenen Ordnern wird eine bloße Adresse nur über den Domainnamen verglichen (FALLSTRICKE #107)
    vergleichsnamen = [_vergleichsname(absender), ordnername if _vergleichsname(roh) == roh else _vergleichsname(roh)]
    tags, tags_verworfen = ohne_unbrauchbare_neue_tags(
        tags, tag_kategorien, known_tags, (absender, ordnername, ki_antwort.get("absender")))

    probleme = []
    if schreibschutz in ("verschlüsselt", "schreibgeschützt"):
        probleme.append(f"PDF ist {schreibschutz}")
    if not titel:
        probleme.append("kein Titel erkannt")
    if not _datum_ist_plausibel(datum):
        probleme.append("kein plausibles Dokumentdatum erkannt")

    # Zielordner-Wahl ist bewusst KEINE KI-Aufgabe (siehe finde_passenden_ordner) - findet
    # sich kein vorhandener Ordner, wird ein neuer vorgeschlagen: unter dem passenden
    # Buchstabengruppen-Ordner der Sammlung, falls sie welche hat, sonst flach.
    # Vorher: ein vom Nutzer hinterlegter Alias schlägt jeden Namensvergleich - das ist
    # der Weg für Weltwissen, das kein String-Vergleich haben kann ("Bayerische
    # Landesbrandversicherung" gehört zur "Versicherungskasse Musterland").
    ordner_neu = False
    ordner_per_alias = False
    ordner_sammel = False
    ordner_gedaechtnis = 0
    ordner_hinweis = ""
    zielordner = ordner_aliase.finde_alias(absender, aliase)
    treffer = gedaechtnis.frage(absender) if gedaechtnis is not None and absender and not zielordner else None
    if zielordner:
        ordner_per_alias = True
        zielordner = ordner_aliase.loese_alias_ordner(zielordner, vorhandene_ordner)
        ordner_neu = zielordner not in vorhandene_ordner
    elif treffer and treffer[0] in vorhandene_ordner:
        # Ablage-Gedächtnis (ablage_gedaechtnis.py): so viele Dokumente dieses Absenders liegen
        # schon dort - das löst auch, was kein Namensvergleich kann (Landesbrandversicherung ->
        # Versicherungskasse). Gilt wie ein Alias: keine Zweitmeinung, keine Ordner-Probleme.
        zielordner, ordner_gedaechtnis = treffer[0], treffer[1]
        ordner_hinweis = f"Gedächtnis, {ordner_gedaechtnis} Dokumente"
    else:
        zielordner = finde_passenden_ordner(vergleichsnamen[0], vorhandene_ordner, ordnername)
    if zielordner is None and not absender:
        # Eigenbelege (Notizen, Zählerstände, Mieterlisten) haben keinen Absender, aber
        # ein Objekt - ein per Klick gelernter Objekt-Alias ordnet sie dem Haus bzw. der
        # Wohnung zu (11.09.2026: 33 der 84 unsicheren Dokumente des Praxislaufs).
        zielordner, _objekt = ordner_aliase.finde_objekt_alias(objekte, aliase)
        if zielordner:
            ordner_per_alias = True
            ordner_hinweis = "Objekt"
            zielordner = ordner_aliase.loese_alias_ordner(zielordner, vorhandene_ordner)
            ordner_neu = zielordner not in vorhandene_ordner
    if zielordner is None and not absender:
        # Ohne Absender (Formulare, Mandate): Tags/Dateiname exakt gegen vorhandene Ordner
        zielordner, ordner_hinweis = finde_ordner_ueber_hinweise(tags, pdf_path, vorhandene_ordner)
        ordner_hinweis = ordner_hinweis or ""
    if zielordner is None and ordnername:
        aus_mailkopf = bool(ki_antwort.get("absender_aus_mailkopf"))
        kern_laenge = len(kernname(ordnername))
        mindestlaenge = 2 if aus_mailkopf else MIN_NEUER_ORDNER
        gleichnamig = next((o for o in vorhandene_ordner
                            if os.path.basename(o).casefold() == ordnername.casefold()), None)
        if gleichnamig and mindestlaenge <= kern_laenge < MIN_ORDNER_MATCH_LAENGE:
            zielordner = gleichnamig       # finde_passenden_ordner vergleicht so kurze Namen bewusst nicht
        elif kern_laenge < mindestlaenge:
            # Ein Kürzel wie 'KM' oder ein einzelner Buchstabe taugt nicht als Ordner -
            # lieber Unsicher als einen Ordner anlegen, den niemand wiederfindet.
            probleme.append(f"Absendername zu kurz für einen Ordner: '{ordnername}'")
        elif absender_kuerzel and not aus_mailkopf:
            # 'Bay. LfSt' (aus der Rücksendezeile) darf kein Ordner werden - Zielordner-Klick
            # legt den Alias 'Bay. LfSt' -> richtiger Ordner an, danach läuft es automatisch.
            probleme.append(
                f"Absender nur als Kürzel{' aus der Adresszeile' if war_adresszeile else ''} erkannt: "
                f"'{absender}' - Zielordner anklicken, dann merkt sich die Automatik den Ordner (Alias)")
            # Ein ähnlicher vorhandener Ordner ('ElsterOnline' -> 'ELSTER') ist schon vorgewählt,
            # dann reicht in der Ablage-Vorschau Enter (Betatest 25.10.2026).
            zielordner = finde_aehnlichen_ordner(vergleichsnamen, vorhandene_ordner)
        else:
            gruppe = finde_buchstabengruppe(ordnername_neu, vorhandene_ordner)
            neuer_ordner = os.path.join(gruppe, ordnername_neu) if gruppe else ordnername_neu
            aehnlich = finde_aehnlichen_ordner(vergleichsnamen, vorhandene_ordner)
            vorwahl = aehnlich and finde_aehnlichen_ordner(
                vergleichsnamen, vorhandene_ordner, ohne_gattungswoerter=True,
                ortswoerter=ortswoerter_des_dokuments(ki_antwort) | set(orte or ()))
            if ki_antwort.get("einzelne_mail"):
                # E17: Eine einzelne Mail ist weder einen eigenen Ordner noch eine Rückfrage wert, auch nicht bei einem ähnlichen
                # Ordner (Peter 06.11.2026). Nichts geht verloren, der Absender steht als Tag dabei.
                zielordner = os.path.join(gruppe, SAMMEL_ORDNER) if gruppe else SAMMEL_ORDNER
                ordner_neu = True
                ordner_sammel = True
                ordner_hinweis = SAMMEL_ORDNER
            elif vorwahl:
                # Kein stiller Doppelordner: der ähnliche Ordner ist vorgewählt, der Mensch
                # bestätigt ihn (oder tippt den neuen Namen) - Betatest 25.10.2026.
                zielordner = vorwahl
                probleme.append(f"{_PROBLEM_AEHNLICHER_ORDNER} '{vorwahl}' - passt er zu '{absender or ordnername}'? "
                                f"Zielordner anklicken (oder neuen Ordner '{ordnername_neu}' eintippen)")
            elif aehnlich:
                # Nur über ein Gattungswort ähnlich ('Versicherung'): trotzdem bremsen, aber der NEUE
                # Ordner ist vorgewählt - Enter in der Ablage-Vorschau legt ihn an. Bleibt das Dokument
                # unsicher, wandert der Ordner NICHT in die Ordnerliste der Runde (auto_pilot_service,
                # auto_filer) - sonst legte das nächste Dokument still in einen nie bestätigten Ordner ab.
                zielordner = neuer_ordner
                ordner_neu = True
                probleme.append(f"{_PROBLEM_AEHNLICHER_ORDNER} '{aehnlich}' - gehört '{absender or ordnername}' "
                                f"dorthin? Sonst wird der neue Ordner '{ordnername_neu}' angelegt - Zielordner "
                                "anklicken oder bestätigen")
            else:
                zielordner = neuer_ordner
                ordner_neu = True
    # Vertrag nach außen: zielordner ist IMMER ein String, nie None - ohne Absender
    # bleibt finde_passenden_ordner() bei None hängen (siehe oben, "and absender"
    # greift dann nicht) und würde sonst tools/auto_filer.py mit einem
    # TypeError beim String-Verketten abstürzen lassen.
    zielordner = zielordner or ""
    if not zielordner:
        # Mit Objekt bekommt der Nutzer den Wink, wie er es dauerhaft löst (Objekt-Alias).
        wink = (f" (Objekt '{objekte[0]}' - Zielordner anklicken und 'alle Dokumente zu diesem Objekt' wählen)"
                if objekte else "")
        probleme.append("kein Zielordner und kein Absender erkannt" + wink)

    # Etappe 6 (Peter 07.11.2026 nach der Prüfung beim Betatest: „fast alle von der KI generierten Tags nicht brauchbar“):
    # Die KI vergibt keine Tags mehr, auch keinen Absender-Tag beim Sammelordner. Ihre Tags dienten oben nur noch als Hinweis
    # für die Ordnerwahl ohne Absender (finde_ordner_ueber_hinweise). Tags setzt der Mensch, etwa in der Ablage-Vorschau;
    # ein Dokument ohne Tags ist darum auch kein Grund mehr für „unsicher“ (FALLSTRICKE #120).
    # B4a (21.11.2026): Was davon schon im Tag-Katalog steht, bleibt als Vorschlag zum Anklicken im Tag-Dialog der
    # Ablage-Vorschau - vergeben wird es weiterhin nur per Klick, wie beim Titelvorschlag.
    katalog = {t.lower() for t in (known_tags or [])}
    tag_vorschlaege = [t for t in tags if t.lower() in katalog]
    tags, tag_ersetzungen, tags_verworfen, neue_tags = [], [], [], []

    sicher = not probleme
    return {
        "pdf_path": pdf_path,
        "titel": titel,
        "titel_korrekturen": titel_korrekturen,
        "tags": tags,
        "tag_ersetzungen": tag_ersetzungen,
        "tags_verworfen": tags_verworfen,
        "tag_vorschlaege": tag_vorschlaege,
        "neue_tags": neue_tags,
        "datum": datum,
        "datum_stempel": datum_stempel,
        "absender": absender,
        "ordnername": ordnername,
        "zielordner": zielordner,
        "ordner_neu": ordner_neu,
        "ordner_per_alias": ordner_per_alias,
        "ordner_sammel": ordner_sammel,
        "ordner_gedaechtnis": ordner_gedaechtnis,
        "objekte": objekte,
        "ordner_hinweis": ordner_hinweis,
        "neuer_dateiname": baue_dateiname(datum, titel) if sicher else "",
        "sicher": sicher,
        "probleme": probleme,
    }


# Probleme, die allein an der Ordnerwahl hängen - sie erledigen sich, sobald der Nutzer
# den Zielordner selbst bestimmt (wende_zielordner_an).
# "Absender nur als Kürzel" fehlte hier bis zum Betatest 25.10.2026: der Hinweis verlangte
# den Zielordner-Klick, der Klick räumte ihn aber nicht weg - die Zeile blieb gelb.
_PROBLEM_AEHNLICHER_ORDNER = "Ähnlicher Ordner vorhanden:"
_PROBLEM_ZWEITMEINUNG = "Zweitmeinung zum Ordner:"
_PROBLEM_STECKBRIEF = "Ordner-Steckbrief:"
_ORDNER_PROBLEM_PRAEFIXE = ("Absendername zu kurz für einen Ordner", "kein Zielordner und kein Absender erkannt",
                            "Absender nur als Kürzel", _PROBLEM_AEHNLICHER_ORDNER, _PROBLEM_ZWEITMEINUNG,
                            _PROBLEM_STECKBRIEF)
STECKBRIEF_HINWEIS = "Ordner-Steckbrief"

# Zweitmeinung eines Entscheidungsmodells zur Ordnerwahl (ollama_client.waehle_ordner,
# Modell-Prüfstand 27.10.2026 am Bestand von 403 Dokumenten). Grundregel bleibt: die KI
# schlägt vor, dieser Code entscheidet.
# - Sperre: legt die Regel-Logik sicher ab, das Modell hält aber mit p >= SPERRE einen
#   ANDEREN Ordner für richtig -> unsicher (still falsch 36 -> 14; bei solchen Widersprüchen
#   hatte die Logik 14x, das Modell 11x recht, 11x beide falsch - deshalb bleibt der Ordner
#   der Logik vorgewählt und der des Modells steht nur im Hinweis).
# - Bestätigung: ist die Logik nur wegen der Ordnerwahl unsicher und das Modell sehr sicher
#   (p >= ERSATZ und Abstand zum Zweitplatzierten >= ABSTAND), gilt dessen Ordner (16 von 17 richtig).
ZWEITMEINUNG_SPERRE_AB = 0.8
ZWEITMEINUNG_ERSATZ_AB = 0.95
ZWEITMEINUNG_ABSTAND = 0.2
ZWEITMEINUNG_HINWEIS = "KI-Ordnerwahl"


def ordner_fuer_zweitmeinung(vorhandene_ordner):
    """Die Ordner, die als Ablageziel infrage kommen: ohne die Buchstabengruppen der obersten Ebene."""
    ziele = []
    for ordner in vorhandene_ordner:
        oben = os.sep not in ordner and "/" not in ordner
        if oben and (buchstaben_der_gruppe(ordner) or _ZIFFERNGRUPPE.match(ordner)):
            continue
        ziele.append(ordner)
    return ziele


def wende_zweitmeinung_an(entscheidung, rangliste, vorhandene_ordner):
    """
    Verrechnet die Rangliste des Entscheidungsmodells ([(ordner, p), ...], beste zuerst)
    mit der Entscheidung der Regel-Logik (siehe ZWEITMEINUNG_*). Liefert eine Kopie.
    Per Alias festgelegte Ordner bleiben unberührt - die hat der Mensch selbst beigebracht -,
    ebenso Ordner aus dem Ablage-Gedächtnis (dort liegen schon mehrere Dokumente des Absenders).
    """
    if not rangliste or entscheidung.get("ordner_per_alias") or entscheidung.get("ordner_gedaechtnis") or entscheidung.get("ordner_sammel"):
        return entscheidung
    bester, p1 = rangliste[0]
    p2 = rangliste[1][1] if len(rangliste) > 1 else 0.0
    ziel = entscheidung.get("zielordner") or ""
    if entscheidung["sicher"]:
        if bester == ziel or p1 < ZWEITMEINUNG_SPERRE_AB:
            return entscheidung
        neu = dict(entscheidung)
        neu["probleme"] = list(entscheidung["probleme"]) + [
            f"{_PROBLEM_ZWEITMEINUNG} die KI hält '{bester}' für passender ({p1:.0%}) - "
            f"Zielordner anklicken und bestätigen oder ändern"]
        neu["sicher"] = False
        neu["neuer_dateiname"] = ""
        return neu
    ordner_probleme = [p for p in entscheidung["probleme"] if p.startswith(_ORDNER_PROBLEM_PRAEFIXE)]
    if not ordner_probleme or p1 < ZWEITMEINUNG_ERSATZ_AB or p1 - p2 < ZWEITMEINUNG_ABSTAND:
        return entscheidung
    neu = wende_zielordner_an(entscheidung, bester, vorhandene_ordner)
    neu["ordner_per_alias"] = False
    neu["ordner_hinweis"] = ZWEITMEINUNG_HINWEIS
    return neu


def wende_steckbrief_an(entscheidung, vorschlag, rangliste, vorhandene_ordner, merkmale=0):
    """
    Regel D des Ordner-Steckbriefs (KONZEPT_ORDNER_STECKBRIEF.md; Korpus mit Zweitmeinung: 243 richtig / 24 still
    falsch / 136 unsicher -> 276 / 20 / 107). Der Steckbrief allein lag nur zu 81 % richtig (er lernt auch aus
    Fehlablagen), deshalb entscheidet er nie allein:
    - Sperre: Eine sichere Ablage in einen anderen Ordner wird zur Rückfrage, der Steckbrief-Ordner ist vorgewählt.
    - Bestätigung: Ist die Entscheidung nur wegen der Ordnerwahl unsicher und stimmt ein zweites Signal zu - die
      Vorwahl der Regeln oder der erste Platz der Zweitmeinung -, gilt der Steckbrief-Ordner.
    - Sonst: Der Steckbrief-Ordner ist vorgewählt, der Mensch bestätigt.
    Alias- und Sammelordner bleiben unberührt (die hat der Mensch bzw. E17 festgelegt). Liefert eine Kopie.
    :param vorschlag: Ordner aus ordner_steckbrief.Steckbriefe.vorschlag (muss in vorhandene_ordner stehen)
    :param rangliste: Zweitmeinung [(ordner, p), ...] oder None
    :param merkmale: Anzahl passender Merkmale (nur für den Hinweis)
    """
    if (not vorschlag or vorschlag not in vorhandene_ordner or entscheidung.get("ordner_per_alias")
            or entscheidung.get("ordner_sammel")):
        return entscheidung
    ziel = entscheidung.get("zielordner") or ""
    if _gleicher_ordner(ziel, vorschlag):
        if entscheidung["sicher"]:
            return entscheidung
        zustimmung = True
    else:
        zustimmung = bool(rangliste) and _gleicher_ordner(rangliste[0][0], vorschlag)
    hinweis = (f"{_PROBLEM_STECKBRIEF} {merkmale} Merkmal{'e' if merkmale != 1 else ''} (Nummern, Adressen) wie "
               f"in '{vorschlag}'")
    ordner_probleme = [p for p in entscheidung["probleme"] if p.startswith(_ORDNER_PROBLEM_PRAEFIXE)]
    if not entscheidung["sicher"] and zustimmung and ordner_probleme:
        neu = wende_zielordner_an(entscheidung, vorschlag, vorhandene_ordner)
        neu["ordner_per_alias"] = False
        neu["ordner_hinweis"] = STECKBRIEF_HINWEIS
        return neu
    if _gleicher_ordner(ziel, vorschlag):
        return entscheidung          # schon vorgewählt, aus anderem Grund unsicher (z.B. kein Datum)
    neu = dict(entscheidung)
    neu["zielordner"] = vorschlag
    neu["ordner_neu"] = False
    neu["ordner_gedaechtnis"] = 0
    neu["sicher"] = False
    neu["neuer_dateiname"] = ""
    neu["probleme"] = list(entscheidung["probleme"]) + [
        f"{hinweis}" + (f" - KID wollte nach '{ziel}'" if ziel else "") + " - Zielordner anklicken und bestätigen"]
    return neu


def _gleicher_ordner(a, b):
    return bool(a) and bool(b) and os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


_PROBLEM_KEIN_TITEL = "kein Titel erkannt"
_PROBLEM_KEINE_TAGS = "keine Tags erkannt"
_PROBLEM_KEIN_DATUM = "kein plausibles Dokumentdatum erkannt"


def wende_korrektur_an(entscheidung, titel=None, datum=None, tags=None, known_tags=None, kategorien=None):
    """
    Liefert eine Kopie der Entscheidung mit vom Nutzer korrigiertem Titel, Datum und/oder
    Tags (Doppelklick auf die Zelle in der Ablage-Vorschau). Das jeweilige KI-Problem entfällt
    bzw. kommt zurück, wenn die Eingabe leer/unplausibel ist; 'sicher' und der Dateiname
    werden neu bestimmt. None = Feld unverändert lassen.
    :param tags: kommagetrennter Eingabetext des Nutzers (Nutzerwunsch 01./03.09.2026);
                 Komma ist das Trennzeichen des Schlagwortfelds (FALLSTRICKE #38).
                 known_tags/kategorien dienen dazu, die "(neu→Kategorie)"-Kennzeichnung
                 für hinzugetippte Tags neu zu bestimmen.
    """
    neu = dict(entscheidung)
    # Eine Korrektur ändert die Faktenlage - eine früher erteilte manuelle Freigabe
    # (wende_freigabe_an) gilt dann nicht mehr und muss neu erteilt werden.
    neu.pop("manuell_freigegeben", None)
    probleme = list(entscheidung["probleme"])
    if titel is not None:
        neu["titel"] = titel.strip()
        neu["titel_korrekturen"] = []  # Nutzer-Titel wird nicht mehr "korrigiert"
        probleme = [p for p in probleme if p != _PROBLEM_KEIN_TITEL]
        if not neu["titel"]:
            probleme.append(_PROBLEM_KEIN_TITEL)
    if datum is not None:
        neu["datum"] = normalisiere_datum(datum)
        probleme = [p for p in probleme if p != _PROBLEM_KEIN_DATUM]
        if not _datum_ist_plausibel(neu["datum"]):
            probleme.append(_PROBLEM_KEIN_DATUM)
    if tags is not None:
        liste = []
        for teil in str(tags).split(","):
            teil = " ".join(teil.split())
            if teil and teil.lower() not in {t.lower() for t in liste}:
                liste.append(teil)
        neu["tags"] = liste
        neu["neue_tags"] = bestimme_neue_tags(liste, None, known_tags, kategorien)
        # Leere Tags sind kein Problem mehr (Etappe 6, FALLSTRICKE #120); ein alter Eintrag fällt weg
        probleme = [p for p in probleme if p != _PROBLEM_KEINE_TAGS]
    neu["probleme"] = probleme
    neu["sicher"] = not probleme
    neu["neuer_dateiname"] = baue_dateiname(neu["datum"], neu["titel"]) if neu["sicher"] else ""
    return neu


def korrigierbare_probleme(entscheidung):
    """
    Die Teilmenge der Probleme, für die die Ablage-Vorschau eine eigene Korrektur-Zelle
    hat (Titel/Tags/Datum/Zielordner). Alles andere ("vermutlich Dublette zu ...",
    Schreibschutz, Seite nicht darstellbar) besitzt keine Zelle - dafür gibt es die
    manuelle Freigabe (wende_freigabe_an).
    """
    praefixe = (_PROBLEM_KEIN_TITEL, _PROBLEM_KEINE_TAGS, _PROBLEM_KEIN_DATUM) + _ORDNER_PROBLEM_PRAEFIXE
    return [p for p in entscheidung["probleme"] if p.startswith(praefixe)]


def wende_freigabe_an(entscheidung, freigeben=True):
    """
    Manuelle Freigabe einer 'unsicheren' Zeile (Nutzerwunsch 06.09.2026): Der Nutzer hat
    die verbliebenen Gründe (z.B. "vermutlich Dublette zu ...") selbst geprüft und will
    trotzdem automatisch ablegen. Liefert eine Kopie; die Probleme BLEIBEN im Dict
    stehen, damit Anzeige und Protokoll ehrlich sagen, worüber hinweggegangen wurde.
    Korrigierbare Probleme (korrigierbare_probleme) werden bewusst NICHT überstimmt -
    ohne Titel/Datum gäbe es keinen Dateinamen; sind welche offen, bleibt die
    Entscheidung unsicher. freigeben=False nimmt die Freigabe zurück.
    """
    neu = dict(entscheidung)
    neu["manuell_freigegeben"] = bool(freigeben)
    neu["sicher"] = not neu["probleme"] or (bool(freigeben) and not korrigierbare_probleme(neu))
    neu["neuer_dateiname"] = baue_dateiname(neu["datum"], neu["titel"]) if neu["sicher"] else ""
    return neu


PROBLEM_ZURUECKGESTELLT = "von Hand zurückgestellt"


def wende_zurueckstellung_an(entscheidung, zurueckstellen=True):
    """
    Gegenstück zur Freigabe (Peter 02.11.2026: „Dokumente manuell wieder gelb machen, wenn sie fälschlicherweise
    grün wurden“): eine sichere Zeile wird unsicher und wandert beim Einsortieren nach 0_Unsicher. Als Problem
    vermerkt, damit es Korrekturen an Titel/Datum/Zielordner überlebt (die bestimmen `sicher` aus den Problemen
    neu) und als Grund (KID_GRUND, Protokoll) dasteht. zurueckstellen=False nimmt es zurück.
    """
    neu = dict(entscheidung)
    neu.pop("manuell_freigegeben", None)
    neu["probleme"] = [p for p in entscheidung["probleme"] if p != PROBLEM_ZURUECKGESTELLT]
    if zurueckstellen:
        neu["probleme"].append(PROBLEM_ZURUECKGESTELLT)
    neu["sicher"] = not neu["probleme"]
    neu["neuer_dateiname"] = baue_dateiname(neu["datum"], neu["titel"]) if neu["sicher"] else ""
    return neu


def alias_schluessel(entscheidung):
    """
    Unter welchem Schlüssel ein Zielordner-Klick "für alle" gemerkt wird: der Absender -
    oder, bei Dokumenten ohne Absender (Eigenbelege), das erste Objekt auf Haus-Ebene
    ("Weidenstr. 8 Whg 4" -> "Objekt: Weidenstr. 8", ordner_aliase.objekt_kern), damit
    alle Wohnungen des Hauses denselben Ordner bekommen.
    :return: (Schlüssel, Art 'Absender'/'Objekt') oder ('', '') wenn nichts lernbar ist
    """
    absender = (entscheidung.get("absender") or "").strip()
    if absender:
        return absender, "Absender"
    objekte = entscheidung.get("objekte") or []
    if objekte:
        return ordner_aliase.objekt_schluessel(ordner_aliase.objekt_kern(objekte[0])), "Objekt"
    return "", ""


def alias_trifft(entscheidung, schluessel, zielordner):
    """
    Gilt der frisch gelernte Alias {schluessel: zielordner} auch für diese (andere) Zeile
    des Stapels? Absender-Alias nur über den Absender, Objekt-Alias nur für absenderlose
    Dokumente über deren Objekte - genau wie in baue_entscheidung.
    """
    absender = (entscheidung.get("absender") or "").strip()
    if ordner_aliase.ist_objekt_alias(schluessel):
        if absender:
            return False
        return ordner_aliase.finde_objekt_alias(entscheidung.get("objekte"), {schluessel: zielordner})[0] is not None
    return bool(absender) and ordner_aliase.finde_alias(absender, {schluessel: zielordner}) is not None


def wende_zielordner_an(entscheidung, zielordner, vorhandene_ordner):
    """
    Liefert eine Kopie der Entscheidung mit vom Nutzer festgelegtem Zielordner (Klick auf
    die Zielordner-Zelle in der Ablage-Vorschau). Ordner-bezogene Probleme entfallen,
    'sicher' und der neue Dateiname werden neu bestimmt; Titel/Tags/Datum-Probleme
    bleiben - ein fehlendes Datum wird durch einen richtigen Ordner nicht besser.
    """
    zielordner = (zielordner or "").strip()
    neu = dict(entscheidung)
    # Eine Korrektur ändert die Faktenlage - eine früher erteilte Freigabe gilt dann
    # nicht mehr (der Dubletten-Verdacht bezog sich z.B. auf den ALTEN Zielordner).
    neu.pop("manuell_freigegeben", None)
    neu["zielordner"] = zielordner
    neu["ordner_neu"] = bool(zielordner) and zielordner not in vorhandene_ordner
    neu["ordner_per_alias"] = True
    neu["ordner_sammel"] = False
    neu["ordner_gedaechtnis"] = 0
    neu["ordner_hinweis"] = ""
    neu["probleme"] = [p for p in entscheidung["probleme"] if not p.startswith(_ORDNER_PROBLEM_PRAEFIXE)]
    if not zielordner:
        neu["probleme"].append("kein Zielordner und kein Absender erkannt")
    neu["sicher"] = not neu["probleme"]
    neu["neuer_dateiname"] = baue_dateiname(neu["datum"], neu["titel"]) if neu["sicher"] else ""
    return neu


def analysiere_dokument(pdf_path, known_tags, vorhandene_ordner, base_url, model, vocabulary=None, aliase=None,
                        kategorien=None, ignorierte_tags=None, tag_eltern=None,
                        synonyme=None, entscheidungsmodell="", gedaechtnis=None, orte=None):
    """
    Komplette Analyse EINES Dokuments: Schreibschutz prüfen, Seite 1 rendern,
    KI befragen, Entscheidung bauen. Wirft Verbindungs-/Serverfehler des
    KI-Aufrufs weiter (Aufrufer entscheidet - im Batch läuft der Rest weiter,
    in der Vollautomatik bleibt das Dokument im Posteingang liegen).

    Mit entscheidungsmodell holt sie zusätzlich die Zweitmeinung zur Ordnerwahl
    (wende_zweitmeinung_an). Scheitert nur diese, bleibt es bei der Entscheidung der
    Regel-Logik (wie ohne Zweitmeinung); der Grund steht dann in "zweitmeinung_fehler".
    """
    gelesen = lies_dokument(pdf_path, known_tags, base_url, model, kategorien)
    return entscheide_gelesen(gelesen, vorhandene_ordner, base_url, vocabulary=vocabulary, aliase=aliase,
                              known_tags=known_tags, kategorien=kategorien, ignorierte_tags=ignorierte_tags,
                              tag_eltern=tag_eltern, synonyme=synonyme, entscheidungsmodell=entscheidungsmodell,
                              gedaechtnis=gedaechtnis, orte=orte)


# Die drei Bausteine von analysiere_dokument einzeln - für den Stapelbetrieb je Modell
# (auto_pilot_service): erst alle Dokumente eines Stapels mit dem Lesemodell lesen, dann alle
# Zweitmeinungen mit dem Entscheidungsmodell holen, dann der Reihe nach entscheiden und ablegen.
# Beide Modelle passen nicht gleichzeitig in 16 GB - je Dokument gewechselt, lud Ollama jedes
# Mal neu (~22 s statt ~9 s je Dokument, Modell-Prüfstand 27.10.2026).

def lies_dokument(pdf_path, known_tags, base_url, model, kategorien=None):
    """
    Lesemodell-Teil: Schreibschutz prüfen, Seite 1 rendern, KI befragen. Wirft Verbindungs-/
    Serverfehler des KI-Aufrufs weiter. :return: {"pdf_path", "schreibschutz", "png", "ki_antwort", "merkmale",
    "daten", "woerter", "arzt"} (png None = Seite nicht darstellbar, dann ohne KI-Aufruf; merkmale = Nummern/Adressen aus der
    Textebene für den Ordner-Steckbrief, daten = Brief- und Stempeldaten der Textebene (eingangsstempel.textdaten),
    woerter = Schreibweisen für den Ordnernamen (ordnernamen.textwoerter), arzt = Ärztin eines Arztbriefs
    (ordnernamen.arzt_im_text); alles leer ohne Textebene - kein OCR, das
    kostete je Dokument Sekunden)
    """
    schreibschutz = PDFHandler.get_write_protection(pdf_path)
    png = PDFHandler.render_page_png(pdf_path)
    ki_antwort = None
    if png is not None:
        ki_antwort = ollama_client.suggest_filing(
            png, known_tags=known_tags, base_url=base_url, model=model, kategorien=kategorien)
        ki_antwort = mit_mailkopf(ki_antwort, PDFHandler.get_metadata(pdf_path))
    volltext = PDFHandler.get_fulltext(pdf_path)
    return {"pdf_path": pdf_path, "schreibschutz": schreibschutz, "png": png, "ki_antwort": ki_antwort,
            "merkmale": ordner_steckbrief.merkmale(volltext), "daten": eingangsstempel.textdaten(volltext),
            "woerter": ordnernamen.textwoerter(volltext), "arzt": ordnernamen.arzt_im_text(volltext)}


def mit_mailkopf(ki_antwort, meta):
    """Mail-PDF (KID_MAILID, Mail-Import 04.11.2026): Datum und Gegenüber stehen im Mailkopf fest - sie gehen dem
    KI-Lesewert vor (Konzept „Ablage“: sicherer als bei Scans; die KI las sonst auch ein Datum aus dem Text oder
    bei gesendeten Mails den eigenen Namen als Absender). Ein PDF-Anhang (KID_MAILID ohne KID_RICHTUNG) gilt wie ein
    Scan: eine weitergeleitete Rechnung gehört zu ihrem Aussteller - das Gegenüber der Mail nur, wenn auf dem Dokument
    kein brauchbarer Absender zu lesen ist (leer, nur ein Kürzel, unter drei Buchstaben). `absender_aus_mailkopf` lockert in baue_entscheidung die Sperre für kurze Namen: Im Kopf
    steht der Name fest, er ist kein Lesefehler. Andere PDFs unverändert."""
    if not isinstance(ki_antwort, dict) or not (meta or {}).get("KID_MailID"):
        return ki_antwort
    neu = dict(ki_antwort)
    if not meta.get("KID_Richtung"):
        if meta.get("KID_Absender") and _absender_unbrauchbar(neu.get("absender")):
            neu["absender"] = meta["KID_Absender"]
            neu["absender_aus_mailkopf"] = True
        # das Mail-Datum nur als Ersatz: das Dokumentdatum einer Rechnung steht auf der Rechnung
        if meta.get("KID_DokumentenDatum") and not _datum_ist_plausibel(normalisiere_datum(neu.get("datum"))):
            neu["datum"] = meta["KID_DokumentenDatum"]
        return neu
    if meta.get("KID_DokumentenDatum"):
        neu["datum"] = meta["KID_DokumentenDatum"]
    if meta.get("KID_Absender"):
        neu["absender"] = meta["KID_Absender"]   # der KI-Ordnername gilt nur, wenn er dazu passt (baue_entscheidung)
        neu["absender_aus_mailkopf"] = True
    if meta.get("KID_Einzeln"):
        neu["einzelne_mail"] = True              # vom Import gesetzt, er kennt alle Mails des Laufs (E17)
    if meta.get("KID_Eigen"):
        if isinstance(neu.get("tags"), list):
            neu["tags"] = ohne_eigene_namen(neu["tags"], meta["KID_Eigen"])
        if neu.get("empfaenger"):                # der Hauptweg: Daraus macht tags_mit_empfaenger Personen-Tags
            neu["empfaenger"] = "; ".join(ohne_eigene_namen(teile_empfaenger(neu["empfaenger"]), meta["KID_Eigen"]))
    return neu


def _absender_unbrauchbar(absender):
    """Taugt der gelesene Absender nicht für einen Ordner? Leer, reines Kürzel oder zu kurz (wie in baue_entscheidung)."""
    name, _ = trenne_adresszeile(absender)
    return (not name or absender_ist_kuerzel(name)
            or len(kernname(bereinige_ordnername(name))) < MIN_NEUER_ORDNER)


def braucht_zweitmeinung(entscheidung):
    """Bekommt diese Entscheidung eine Zweitmeinung zur Ordnerwahl? (sicher oder nur wegen des Ordners
    unsicher - aber nie bei Alias- oder Gedächtnis-Ordnern, die gelten ohnehin)"""
    if entscheidung.get("ordner_per_alias") or entscheidung.get("ordner_gedaechtnis") or entscheidung.get("ordner_sammel"):
        return False
    return entscheidung["sicher"] or any(p.startswith(_ORDNER_PROBLEM_PRAEFIXE) for p in entscheidung["probleme"])


STANDARD_ENTSCHEIDUNGSMODELL = "clef-flash:9b"


def wirksames_entscheidungsmodell(config, base_url):
    """
    Modell der Zweitmeinung zur Ordnerwahl, "" = aus. Seit 15.11.2026 (Peter, vor v0.9.30) standardmäßig an: Steht
    `ki_entscheidungsmodell` nicht in settings.json, gilt STANDARD_ENTSCHEIDUNGSMODELL - aber nur, wenn der KI-Server es
    hat; sonst aus, statt bei jedem Dokument an einem fehlenden Modell zu scheitern (Beta-Tester mit eigenem Server).
    Ein eingetragener Wert gilt, wie er ist: ein bewusst geleertes Feld bleibt aus. Gemessen (Etappe 9): mit
    Zweitmeinung still falsch 45 -> 24 im Bestand, in Themenordnern 25 -> 15.
    :param config: hat get(key, default) wie config.Config
    """
    wert = config.get("ki_entscheidungsmodell", None)
    if wert is not None:
        return str(wert).strip()
    try:
        namen = ollama_client.list_models(base_url)
    except Exception:                                     # Server weg: dann gibt es ohnehin keine Ablage
        return ""
    return (STANDARD_ENTSCHEIDUNGSMODELL
            if any(ollama_client._passt_modellname(n, STANDARD_ENTSCHEIDUNGSMODELL) for n in namen) else "")


def hole_zweitmeinung(gelesen, vorhandene_ordner, base_url, entscheidungsmodell):
    """Entscheidungsmodell-Teil: Rangliste [(ordner, p), ...] zur Seite 1 des gelesenen Dokuments.
    Wirft Fehler weiter."""
    return ollama_client.waehle_ordner(gelesen["png"], ordner_fuer_zweitmeinung(vorhandene_ordner),
                                       base_url=base_url, model=entscheidungsmodell)


def entscheide_gelesen(gelesen, vorhandene_ordner, base_url, vocabulary=None, aliase=None, known_tags=None,
                       kategorien=None, ignorierte_tags=None, tag_eltern=None,
                       synonyme=None, entscheidungsmodell="", gedaechtnis=None, rangliste=None,
                       orte=None, steckbriefe=None):
    """
    Entscheidung aus einem gelesenen Dokument (lies_dokument) bauen und - mit entscheidungsmodell -
    die Zweitmeinung verrechnen. Eine im Stapel schon geholte Zweitmeinung kommt als rangliste
    (Liste oder Exception); fehlt sie, wird sie hier geholt. Scheitert nur die Zweitmeinung, bleibt
    es bei der Regel-Logik, der Grund steht in "zweitmeinung_fehler".
    :param steckbriefe: ordner_steckbrief.Steckbriefe - danach Regel D (wende_steckbrief_an), so gemessen im
        ablage_messlauf: nach der Zweitmeinung, deren erster Platz als zweites Signal zählt
    """
    if gelesen["png"] is None:
        return {
            "pdf_path": gelesen["pdf_path"], "titel": "", "titel_korrekturen": [], "tags": [], "tag_ersetzungen": [],
            "neue_tags": [], "datum": "",
            "absender": "", "ordnername": "", "zielordner": "", "ordner_neu": False,
            "ordner_per_alias": False, "ordner_gedaechtnis": 0, "objekte": [], "ordner_hinweis": "", "neuer_dateiname": "", "sicher": False,
            "probleme": ["Seite 1 nicht darstellbar (beschädigt oder geschützt?)"],
        }
    entscheidung = baue_entscheidung(gelesen["pdf_path"], gelesen["ki_antwort"], vorhandene_ordner,
                                     schreibschutz=gelesen["schreibschutz"], vocabulary=vocabulary, aliase=aliase,
                                     known_tags=known_tags, kategorien=kategorien, ignorierte_tags=ignorierte_tags,
                                     tag_eltern=tag_eltern, synonyme=synonyme, gedaechtnis=gedaechtnis, orte=orte,
                                     textdaten=gelesen.get("daten"), textwoerter=gelesen.get("woerter"),
                                     arzt=gelesen.get("arzt"))
    if entscheidungsmodell and braucht_zweitmeinung(entscheidung):
        try:
            if rangliste is None:
                rangliste = hole_zweitmeinung(gelesen, vorhandene_ordner, base_url, entscheidungsmodell)
            if isinstance(rangliste, Exception):
                raise rangliste
            entscheidung = wende_zweitmeinung_an(entscheidung, rangliste, vorhandene_ordner)
        except Exception as e:
            entscheidung = dict(entscheidung, zweitmeinung_fehler=str(e))
    if steckbriefe is not None and gelesen.get("merkmale"):
        vorschlag, anzahl = steckbriefe.vorschlag(gelesen["merkmale"])
        entscheidung = wende_steckbrief_an(entscheidung, vorschlag, rangliste if isinstance(rangliste, list) else None,
                                           vorhandene_ordner, anzahl)
    return entscheidung


def zweitmeinungen_fuer_stapel(stapel, vorhandene_ordner, base_url, entscheidungsmodell, abbrechen=None,
                               vor_abruf=None, **regeln):
    """
    Phase 2 des Stapelbetriebs je Modell (28.10.2026, Vollautomatik und Ablage-Vorschau): für jedes
    gelesene Dokument (lies_dokument), das nach dem jetzigen Stand eine Zweitmeinung braucht, das
    Entscheidungsmodell fragen - alle am Stück, damit Ollama nicht je Dokument das Modell wechselt.
    :param stapel: Liste gelesener Dokumente
    :param abbrechen: optional () -> True bricht ab
    :param vor_abruf: optional (gelesen) -> None, vor jeder Abfrage (Statusanzeige)
    :param regeln: übrige Argumente von entscheide_gelesen (known_tags, aliase, gedaechtnis, ...)
    :return: {pdf_path: rangliste oder Exception}
    """
    ranglisten = {}
    if not entscheidungsmodell:
        return ranglisten
    for gelesen in stapel:
        if abbrechen and abbrechen():
            break
        if gelesen.get("png") is None:
            continue
        if not braucht_zweitmeinung(entscheide_gelesen(gelesen, vorhandene_ordner, base_url, **regeln)):
            continue
        if vor_abruf:
            vor_abruf(gelesen)
        try:
            ranglisten[gelesen["pdf_path"]] = hole_zweitmeinung(gelesen, vorhandene_ordner, base_url,
                                                                entscheidungsmodell)
        except Exception as e:
            ranglisten[gelesen["pdf_path"]] = e
    return ranglisten


def entscheide_im_stapel(gelesen, vorhandene_ordner, base_url, entscheidungsmodell="", rangliste=None,
                         ordner_stand=None, steckbriefe=None, **regeln):
    """
    Phase 3 des Stapelbetriebs: wie entscheide_gelesen mit der in Phase 2 geholten Rangliste.
    :param steckbriefe: nur für die endgültige Entscheidung - ob eine Zweitmeinung nötig ist, entscheidet wie in
        Phase 2 die Regel-Logik allein
    :param ordner_stand: Länge der Ordnerliste, als die Rangliste geholt wurde. Sind seitdem im selben
        Stapel neue Ordner entstanden und will dieses Dokument wieder einen NEUEN Ordner anlegen, wird
        die Zweitmeinung mit der aktuellen Liste neu geholt - sonst kann das Entscheidungsmodell den
        gerade angelegten Zwilling nicht nennen (Messlauf 28.10.2026: sicher „Bayerische Vers.kammer“
        neben dem zwei Dokumente älteren „Versicherungskasse Musterland“).
    """
    if rangliste is not None and ordner_stand is not None and len(vorhandene_ordner) > ordner_stand:
        if entscheide_gelesen(gelesen, vorhandene_ordner, base_url, **regeln)["ordner_neu"]:
            rangliste = None
    return entscheide_gelesen(gelesen, vorhandene_ordner, base_url, entscheidungsmodell=entscheidungsmodell,
                              rangliste=rangliste, steckbriefe=steckbriefe, **regeln)
