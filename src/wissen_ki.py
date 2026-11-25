"""
Wiki von Hand: Anbindung der KI (KONZEPT_WIKI_VON_HAND.md). Grundsatz „KI schlägt vor, Code prüft, Mensch entscheidet“.

Neuer Aufbau, Schritt N3 (12.11.2026): Die KI listet auf, wer und was in EINEM Dokument vorkommt („Dinge“: Schublade,
Bezeichnung, freie Angaben mit wörtlichem Zitat). Der Mensch hakt im Fenster an (tools/wiki_dinge.py), erst dann steht
etwas im Wiki.
1. `baue_prompt` gibt der KI den Text, die vorhandenen Schubladen und die Bezeichnungen vorhandener Einträge.
2. `lies_json` fragt die KI und liest ihre JSON-Antwort (abgeschnittenes reparieren, einmal wiederholen).
3. `pruefe_dinge` entscheidet im Code: Das Zitat steht im Dokument, die Zahlen der Angabe stehen im Zitat, keine
   Zugangsdaten, kein Impressum und keine Bankdaten (`IMPRESSUM`), keine Sätze über das Dokument; das Dokument selbst
   („Rechnung Nr. …“, `DOKUMENT`) ist kein Ding; die Bezeichnung braucht ein Wort aus dem Text. Was durchfällt, wird nur
   gezählt.
   Seit 19.11.2026 (Etappe 12, Schritt W3) ist eine Angabe Merkmal + Wert + Zitat statt eines Satzes: der Wert steht im
   Zitat (`wert_im_zitat`), ist kein Satz (`MAX_WERT_WOERTER`), wiederholt nicht die Bezeichnung und nennt kein anderes
   Ding desselben Dokuments (dafür gibt es „Verbinden“ beim Übernehmen); eine Dokumentart ist weder Ding noch Schublade
   (`DOKUMENTART`). Die KI bekommt die schon benutzten Merkmale (`baue_prompt(merkmale=)`), damit sie dieselben Namen
   wählt.
4. `finde_eintrag` und `finde_ueber_zitate` erkennen, welches Ding es im Wiki schon gibt (gleicher Name in anderer
   Schreibweise bzw. dieselben Zitate nach einer Umbenennung), `neue_angaben` lässt weg, was dort schon steht;
   `text_guete` erkennt schlecht erkannten Text.
Messung: `KID-Messungen/wiki_von_hand/dinge_messen.py` (Ergebnis im Konzept, „Messung N1“); seit W3
`merkmale_messen.py` (vorher/nachher, gespeicherte Antworten offline nachrechnen).

GUI-frei, nur Standardbibliothek (+ ollama_client, wissen). Datenschutz: ins Protokoll nur Zahlen.
"""
import collections
import json
import re
import time

import ollama_client
import wissen

MAX_TEXT = 16000                      # Zeichen je Dokument an die KI
MIN_TEXT = 30                         # darunter gilt ein Dokument als „ohne Text“ und wird nicht gefragt
NUM_CTX = 12288
NUM_PREDICT = 3000                    # bis zu 8 Dinge mit Angaben (Messung N1, Peters Test 13.11.2026)
TIMEOUT = 600
HOECHSTENS = 20                       # Dokumente je Lauf (Konzept F4)
SEKUNDEN_JE_DOKUMENT = 15             # erste Schätzung vor dem Lauf; danach zählt die gemessene Zeit


# Zugangsdaten gehören nicht ins Wiki (Datenschutz: es ist eine kompakte Akte) - der Code erkennt sie an Satz und Zitat.
ZUGANG = re.compile(r"passw|kennwort|\bpin\b|\btan\b|aktivierung|zugangs|schaltcode|benutzer|login|"
                    r"anmeldecode|sicherheitscode|puk\b", re.I)


class UnbrauchbareAntwort(ValueError):
    """Die KI hat geantwortet, aber auch nach Wiederholung kein verwertbares JSON. Betrifft nur dieses Dokument - der
    Server läuft, ein Lauf über mehrere Dokumente geht weiter (FALLSTRICKE #119)."""


def rette_json(roh):
    """
    Repariert eine abgeschnittene JSON-Antwort (die KI stößt bei langen Listen an NUM_PREDICT, mitten in einer
    Zeichenkette): schneidet hinter dem letzten vollständigen Wert ab und schließt die offenen Klammern. Verloren geht
    nur der angefangene Eintrag. Liefert ein dict oder None.
    """
    roh = str(roh or "")
    offen, in_text, escape, schnitte = [], False, False, []
    for i, z in enumerate(roh):
        if in_text:
            if escape:
                escape = False
            elif z == "\\":
                escape = True
            elif z == '"':
                in_text = False
        elif z == '"':
            in_text = True
        elif z in "{[":
            offen.append("}" if z == "{" else "]")
        elif z in "}]":
            if offen:
                offen.pop()
            schnitte.append((i + 1, "".join(reversed(offen))))
        elif z == ",":
            schnitte.append((i, "".join(reversed(offen))))
    for ende, zu in reversed(schnitte[-200:]):
        try:
            daten = json.loads(roh[:ende] + zu)
        except json.JSONDecodeError:
            continue
        if isinstance(daten, dict):
            return daten
    return None


def _nur_zeichen(text):
    """Nur Buchstaben/Ziffern, klein - die Texterkennung setzt Satzzeichen und Leerzeichen anders als die KI zitiert."""
    return re.sub(r"[^0-9a-zäöüß]", "", str(text or "").lower())


def zitat_im_text(zitat, text):
    return bool(zitat) and _nur_zeichen(zitat) in _nur_zeichen(text)


def beleg_nahe(zitat, text, fenster=500):
    """Alle Wörter/Zahlen des Zitats stehen im Text dicht beieinander (±fenster Zeichen um das längste).
    Die KI setzt eine Tabellenzeile aus Spalten zusammen, die im erkannten Text weit auseinander stehen -
    „wörtlich“ allein verwürfe solche Zitate."""
    teile = [t for t in re.findall(r"[0-9a-zäöüß]+", str(zitat).lower()) if len(t) >= 2 or t.isdigit()]
    if not teile:
        return False
    flach = text.lower()
    anker = max(teile, key=len)
    for m in re.finditer(re.escape(anker), flach):
        ausschnitt = flach[max(0, m.start() - fenster):m.end() + fenster]
        if all(t in ausschnitt for t in teile):
            return True
    return False


def lies_json(prompt, base_url, model, timeout=TIMEOUT):
    """Fragt die KI. :return: (Antwort als dict, Sekunden). Kaputtes JSON: reparieren (`rette_json`), sonst
    einmal mit etwas Zufall wiederholen, danach `UnbrauchbareAntwort`. OSError (Server weg) geht an den
    Aufrufer."""
    for versuch in range(2):
        payload = {"model": model, "prompt": prompt, "stream": False, "format": "json",
                   "options": {"num_ctx": NUM_CTX, "temperature": 0.2 if versuch else 0, "num_predict": NUM_PREDICT}}
        start = time.time()
        roh = ollama_client._generate(payload, base_url, timeout).get("response", "")
        try:
            antwort = json.loads(roh)
        except json.JSONDecodeError as e:
            antwort = rette_json(roh)
            if antwort is None:
                if versuch:
                    raise UnbrauchbareAntwort(f"KI-Antwort ist kein gültiges JSON ({len(roh)} Zeichen)") from e
                continue
        return (antwort if isinstance(antwort, dict) else {}), round(time.time() - start, 1)


def dauer_text(sekunden):
    """„etwa 30 Sekunden“ / „etwa 2 Minuten“."""
    if sekunden < 50:
        return f"etwa {max(10, round(sekunden / 10) * 10)} Sekunden"
    minuten = max(1, round(sekunden / 60))
    return f"etwa {minuten} Minute{'' if minuten == 1 else 'n'}"


# ---------------------------------------------------------------- N3: Was kommt im Dokument vor?
MAX_DINGE = 8                         # Peter 13.11.2026: mit 5 fehlten Personen, die im Dokument stehen
GUETE_MIN = 0.65                      # darunter gilt der Text als schlecht erkannt (Eichung an KID-Test, 12.11.2026:
                                      # Zeichensalat 0,61 und darunter, brauchbare Dokumente ab 0,69)
MAX_BEKANNTE = 60                     # so viele vorhandene Einträge nennt der Prompt

PROMPT = """Unten steht der Text EINES Dokuments einer privaten Dokumentensammlung (Titel: «TITEL»).

Der Besitzer der Sammlung führt ein Wiki über die Personen, Firmen, Behörden, Immobilien, Fahrzeuge, Verträge und
Versicherungen, mit denen er zu tun hat.«BEKANNT»

Nenne, wer und was in diesem Dokument eine Rolle spielt und ins Wiki gehört - höchstens 8 Dinge:
- die Gegenseite: Firma, Behörde, Arzt, Handwerker, Berater (auch mit Ansprechpartner, wenn er den Besitzer betreut),
- betroffene Gegenstände von Dauer: Immobilie (Gebäude, Wohnung, Grundstück), Fahrzeug, Gerät mit Garantie,
- laufende Verträge und Versicherungen (Strom, Versicherung, Abo, Wartung),
- ALLE Personen, die im Dokument mit Namen eine Rolle spielen: Empfänger, Mieter, Patient, Versicherter,
  Miteigentümer, Ansprechpartner, wer etwas ausgeführt hat - jede als eigenes Ding.
KEIN Ding ist: das Dokument selbst oder seine Art (eine Rechnung, ein Bescheid, ein Schreiben, eine
Datenschutzerklärung, ein Merkblatt), eine Bank nur wegen der Bankverbindung, ein Zähler, ein Artikel oder Betrag.

Je Ding:
- "schublade": eine aus «SCHUBLADEN»; passt wirklich keine, ein neues kurzes Wort (keine Dokumentart).
- "bezeichnung": kurzer Name mit Wörtern aus dem Text (z.B. "Musterversicherung AG", "Haus Musterstraße 1",
  "VW Golf M-XY 123", "Stromvertrag Musterwerke").
- "angaben": bis zu 6 Merkmale mit ihrem Wert, die auch in Jahren noch nützen, zu GENAU DIESEM Ding. Je Angabe:
  "merkmal": ein kurzer Name aus 1 bis 3 Wörtern, z.B. Telefon, E-Mail, Adresse, Kundennummer, Vertragsnummer,
  Versicherungsnummer, Kennzeichen, Beitrag, Zählernummer, Baujahr, Wohnfläche, geprüft am, zuständig für.«MERKMALE»
  "wert": NUR der Wert, so wie er im Text steht (z.B. "01234 56789", "V-4711", "19.02.2016", "140,86 €",
  "Feuerlöscher") - kein Satz.
  "zitat": die WÖRTLICHE Stelle aus dem Text, in der der Wert steht, höchstens eine Zeile.
  Die Bezeichnung selbst ist keine Angabe (bei einem Haus ist die Adresse schon die Bezeichnung). Nennt ein Wert eine
  andere Person oder Firma, ist das keine Angabe - nenne sie als eigenes Ding.
  Eine Kunden- oder Vertragsnummer gehört zur Firma bzw. zum Vertrag, nicht zur eigenen Person.
  NICHT: Geschäftsführer, Vorstand, Aufsichtsrat, Handelsregister, Steuer- oder USt-Nummer der Firma,
  Sachbearbeiter, Bankverbindung, Nummer, Datum, Beträge und Steuern einer einzelnen Rechnung, die Rolle in diesem
  Dokument („Empfänger der Rechnung“, „Ort der Leistung“).

Regeln: Nur was im Text steht. Nichts schätzen, rechnen oder ergänzen. Keine Passwörter, PINs oder Zugangscodes.

Antworte NUR mit JSON:
{"dinge": [{"schublade": "...", "bezeichnung": "...", "angaben": [{"merkmal": "...", "wert": "...", "zitat": "..."}]}]}

--- TEXT ---
«TEXT»"""
MAX_MERKMALE = 40                     # so viele schon benutzte Merkmale nennt der Prompt
MAX_WERT_WOERTER = 10                 # mehr Wörter: ein Satz, kein Wert

_WORT = re.compile(r"[\"„“‚‘'(\[]*[A-Za-zÄÖÜäöüßéèàç]+(?:-[A-Za-zÄÖÜäöüß]+)*[.,:;!?)\]\"“”‘']*")
_ZAHLWORT = re.compile(r"[\d.,:/\-–€%+()§*]+|[A-Z]{2}\d[\d ]+")
_VOKAL = re.compile(r"[aeiouyäöüAEIOUYÄÖÜ]")
_BINNENGROSS = re.compile(r"[a-zäöüß][A-ZÄÖÜ]")
_ZIFFERN = re.compile(r"\d+")
_NAMENSWORT = re.compile(r"[A-Za-zÄÖÜäöüß]{4,}")
# Die KI befolgt Verbote im Prompt nur teilweise (Messung N1) - diese Regeln entscheiden.
IMPRESSUM = re.compile(r"gesch[aä]ftsf|vorstand|aufsichtsrat|verwaltungsrat|\bHR[AB]\b|handelsregister|registergericht|"
                       r"amtsgericht|ust[.\- ]*(id|ld)|steuer[ -]?n(r|umm)|sachbearbeit|\bIBAN\b|\bBI[CG]\b|"
                       r"bankverbindung|sitz der gesellschaft|gl[aä]ubiger-id|"
                       # W3-Messung 19.11.2026: Bankdaten alter Art und „Bearbeiter“ kamen als Merkmal durch
                       r"konto-?n(r|ummer)|bankleitzahl|\bblz\b|\bbearbeiter", re.I)
# Aufsichtsbehörden stehen in jedem Datenschutzhinweis und jeder Versicherungsinformation - kein Ding der Sammlung
# (Peter 19.11.2026)
AUFSICHT = re.compile(r"datenschutz\w*\s*aufsicht|aufsichtsbeh[öo]rde|beauftragte\w* f[üu]r (den )?datenschutz|"
                      r"\bBayLDA\b|\bBfDI\b|finanzdienstleistungsaufsicht|\bBaFin\b", re.I)
KUNDE_BEI = {"firma", "behörde", "versicherung"}     # Schubladen, bei denen eine Kundennummer stehen darf
AUFZAEHLUNG_AB = 3    # so viele Personen ohne eigene Kontaktangabe in einem Dokument = Aufzählung (Briefkopf)
# Ein einzelner Rechnungsbetrag oder ein Datum nur dieses Dokuments als Merkmal (W3-Messung: „Zu zahlender Betrag“) -
# gilt nur hier; „Beitrag“ (Versicherung, jedes Jahr) bleibt
EINMALIG = re.compile(r"^(zu zahlende[rn]?\s*|rechnungs|gesamt|end|zahl|brutto|netto)?(betrag|summe)$|^(mwst|"
                      r"umsatzsteuer|rechnungsdatum|zahlungsziel|zahlbar bis|f[aä]llig\w*)\b", re.I)
DOKUMENT = re.compile(r"^(beitrags|strom|gas|ab)?rechnung\b|\brechnung (nr|vom)\b|^(bescheid|schreiben|mahnung|"
                      r"angebot|lieferschein|quittung)\b", re.I)
# Eine Dokumentart ist weder ein Ding noch eine Schublade (Peters Bild 19.11.2026: eine Datenschutzerklärung unter
# „Versicherung“, eine Schublade „Rechnung“)
DOKUMENTART = re.compile(r"^(rechnungs?|rechnungen|schreiben|briefe?|bescheide?|mahnung(en)?|angebote?|lieferschein(e)?|"
                         r"quittung(en)?|dokumente?|belege?|kontoauszüge?|formulare?|anträge?|mitteilung(en)?)$|"
                         r"datenschutz(erklärung|hinweis|information)|merkblatt|informationsblatt|"
                         r"\bagb\b|allgemeine geschäftsbedingungen|widerrufsbelehrung", re.I)
UEBER_DAS_DOKUMENT = re.compile(r"^(es handelt sich|das dokument|dieses dokument|die rechnung wurde|das schreiben)", re.I)
# Sagt nur, welche Rolle das Ding in DIESEM Dokument spielt („Kunde der Rechnung“, „hat eine Rechnung erhalten“) -
# das Zitat stimmt, aber in zwei Jahren nützt der Satz nichts mehr (Peters Test 13.11.2026).
_PAPIER = r"(rechnung|schreibens?|bescheid(s|es)?|dokument(s|es)?|brief(s|es)?|mahnung|angebot(s|es)?|lieferschein(s|es)?)"
ROLLE = re.compile(r"\bdokument|\bim kopf (der|des) " + _PAPIER + r"\b|"
                   r"^(die |das )?(rechnungs(nummer|datum|betrag)|belegnummer|zahlungsziel)\b|"
                   r"\b(gesamt)?(betrag|summe) der rechnung\b|"
                   r"\b(kund(e|in)|empfänger(in)?|adressat(in)?|absender(in)?|aussteller(in)?|ersteller(in)?|"
                   r"rechnungs(empfänger|steller)(in)?)\b.{0,25}\b(der|des|dieser|dieses) " + _PAPIER + r"\b|"
                   r"\b(hat|haben|erhielt|erhält|bekam|bekommt)\b.{0,25}\b" + _PAPIER + r"\b.{0,25}\b"
                   r"(erhalten|bekommen|gestellt|ausgestellt|geschickt|geschrieben|verfasst|erstellt)\b", re.I)
# Als „Rolle“ oder „Funktion“ nur die Seite eines Vertrags oder Schreibens (KI-Lauf 23.11.2026: „Rolle:
# Versicherungsnehmer“) - „Funktion: Leiter Kundenservice“ bleibt, „Beruf: Verkäufer“ auch (anderes Merkmal).
NUR_ROLLE = re.compile(r"^(versicherungsnehmer|versicherungsgeber|versicherer|versicherte[rn]?|kund(e|in)|auftrag(geber|nehmer)|"
                       r"vertragspartner|käufer|verkäufer|empfänger|rechnungsempfänger|adressat|absender|"
                       r"unterzeichner|antragsteller|patient)(in)?$", re.I)
# Lesefehler der Texterkennung in E-Mail und Webseite („servtce@musterversicheru ng.example“): mit Leerzeichen oder ohne
# Endung ist es keine Adresse und stünde neben der richtigen als zweiter Wert. Mehrere durch Komma oder Strichpunkt gehen.
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[a-zäöü]{2,}$", re.I)
_WEB = re.compile(r"^(https?://)?[^\s/@]+\.[a-zäöü]{2,}(/\S*)?$", re.I)
_ADRESSFORM = {"e-mail": _EMAIL, "webseite": _WEB}
# Beschriftung ohne den Wert („Telefon: Zentrale“, „Adresse: <ein Name>“): Wer so heißt, muss eine Ziffer, eine E-Mail-
# oder eine Internetadresse nennen.
ETIKETT = re.compile(r"^(die |der |das |seine |ihre )?(\w*anschrift|\w*adresse|telefon\w*|fax\w*|\w+nummer|e-mail\S*|"
                     r"webseite|website|internet\w*)\b", re.I)
_WERT = re.compile(r"\d|@|www\.|\.(de|com|net|org|eu|ch|at)\b", re.I)
GRUENDE = {"leer": "ohne Text oder Zitat", "zugang": "Zugangsdaten", "zitat": "Zitat nicht im Dokument",
           "zahl": "Zahl nicht im Zitat", "impressum": "Impressum oder Bankdaten", "lang": "zu lang",
           "dokument": "das Dokument selbst", "name": "Name nicht im Dokument", "ohne": "ohne brauchbare Angabe",
           "ueber": "Satz über das Dokument", "rolle": "gilt nur für dieses Dokument",
           "etikett": "Beschriftung ohne Wert", "schreibweise": "E-Mail oder Webseite unlesbar", "merkmal": "Merkmal fehlt oder ist zu lang",
           "satz": "Satz statt Wert", "wert": "Wert nicht im Zitat", "bezeichnung": "wiederholt die Bezeichnung",
           "verbindung": "nennt ein anderes Ding (Verbinden)", "aufsicht": "Aufsichtsbehörde",
           "kunde": "Kundennummer ohne eindeutige Firma"}


def text_guete(text):
    """Anteil der Wörter, die wie Wörter oder Zahlen aussehen (0-1). Zeichensalat aus schlechter Texterkennung liegt
    deutlich unter sauberem Text; die KI macht daraus sonst „Dinge“, deren Zitate wörtlich im kaputten Text stehen."""
    tokens = str(text or "")[:MAX_TEXT].split()
    gut = 0
    for t in tokens:
        if _ZAHLWORT.fullmatch(t):
            gut += 1
        elif _WORT.fullmatch(t):
            kern = t.strip("\"„“‚‘'()[].,:;!?”")
            gut += len(kern) == 1 or bool(_VOKAL.search(kern) and not _BINNENGROSS.search(kern))
    return gut / len(tokens) if tokens else 0.0


def baue_prompt(text, titel="", schubladen=(), bekannte=(), merkmale=()):
    """:param bekannte: Bezeichnungen vorhandener Einträge - die KI soll sie in derselben Schreibweise nennen
    :param merkmale: im Wiki schon benutzte Merkmale (wissen.Wissen.merkmale) - die KI soll dieselben Namen nehmen"""
    bekannt = ""
    if bekannte:
        namen = "; ".join(" ".join(str(b).split()) for b in list(bekannte)[:MAX_BEKANNTE])
        bekannt = f"\nIm Wiki stehen schon: {namen}. Kommt eines davon vor, nenne es mit GENAU dieser Bezeichnung."
    schon = ""
    if merkmale:
        schon = ("\n  Im Wiki schon benutzte Merkmale - für dasselbe GENAU diesen Namen nehmen: "
                 + ", ".join(" ".join(str(m).split()) for m in list(merkmale)[:MAX_MERKMALE]) + ".")
    return (PROMPT.replace("«TITEL»", titel or "-").replace("«BEKANNT»", bekannt).replace("«MERKMALE»", schon)
            .replace("«SCHUBLADEN»", ", ".join(schubladen)).replace("«TEXT»", str(text or "")[:MAX_TEXT]))


def wert_im_zitat(wert, zitat):
    """Steht der Wert im Zitat? Die Ziffernfolgen des Werts stehen in denen des Zitats, und jedes Wort (ab 3 Buchstaben)
    kommt im Zitat vor - Schreibweise, Leer- und Satzzeichen egal („140,86 €“ in „140,86 EUR“)."""
    flach = _nur_zeichen(zitat)
    ziffern = "".join(_ZIFFERN.findall(str(zitat)))
    if any(z not in ziffern for z in _ZIFFERN.findall(str(wert))):
        return False
    woerter = [w for w in re.findall(r"[a-zäöüß]+", str(wert).lower()) if len(w) >= 3]
    return all(w in flach for w in woerter) and bool(_nur_zeichen(wert))


def _pruefe_angabe(angabe, text, bezeichnung=""):
    """:return: (Merkmal, Wert, Zitat, Grund) - Grund "" = gültig"""
    merkmal, wert, zitat = (" ".join(str(angabe.get(k) or "").split()) for k in ("merkmal", "wert", "zitat"))
    merkmal = merkmal.rstrip(":").strip()
    satz = f"{merkmal} {wert}"
    if not wert or not zitat:
        return merkmal, wert, zitat, "leer"
    if not merkmal or len(merkmal) > wissen.MAX_MERKMAL or len(merkmal.split()) > 4:
        return merkmal, wert, zitat, "merkmal"
    if len(wissen.angabe_text(merkmal, wert)) > wissen.MAX_ANGABE:
        return merkmal, wert, zitat, "lang"
    if len(wert.split()) > MAX_WERT_WOERTER:
        return merkmal, wert, zitat, "satz"
    if ZUGANG.search(zitat) or ZUGANG.search(satz):
        return merkmal, wert, zitat, "zugang"
    if IMPRESSUM.search(zitat) or IMPRESSUM.search(satz):
        return merkmal, wert, zitat, "impressum"
    if UEBER_DAS_DOKUMENT.search(wert) or ROLLE.search(satz) or ROLLE.search(wert) or EINMALIG.search(merkmal):
        return merkmal, wert, zitat, "rolle"
    if wissen.merkmal_kern(merkmal) == "funktion" and NUR_ROLLE.match(wert):
        return merkmal, wert, zitat, "rolle"
    if not (zitat_im_text(zitat, text) or beleg_nahe(zitat, text)):
        return merkmal, wert, zitat, "zitat"
    if not wert_im_zitat(wert, zitat):
        return merkmal, wert, zitat, "wert"
    if ETIKETT.search(merkmal) and not _WERT.search(wert):
        return merkmal, wert, zitat, "etikett"
    form = _ADRESSFORM.get(wissen.merkmal_kern(merkmal))
    if form and not all(form.match(t.strip(" .")) for t in re.split(r"[,;]", wert)):
        return merkmal, wert, zitat, "schreibweise"
    k = kern(wert)
    if k and k <= kern(bezeichnung):
        return merkmal, wert, zitat, "bezeichnung"
    return merkmal, wert, zitat, ""


def pruefe_dinge(antwort, text):
    """Der Code entscheidet, was von der Antwort der KI gezeigt wird.
    :return: (Dinge [{schublade, bezeichnung, angaben: [{merkmal, wert, zitat, text}]}], Counter verworfener Gründe) -
             `text` = „Merkmal: Wert“ (wissen.angabe_text), zum Vergleichen mit Vorhandenem und Abgelehntem
    Ein Ding braucht eine Bezeichnung mit einem Wort aus dem Dokument und mindestens eine gültige Angabe; das Dokument
    selbst („Rechnung Nr. …“) oder eine Dokumentart ist kein Ding, eine Dokumentart auch keine Schublade (dann
    „Sonstiges“). Eine Angabe, deren Wert ein anderes Ding desselben Dokuments nennt, fällt weg (`verbindung`) - das
    verbindet „Verbinden“ beim Übernehmen. Gleiche Bezeichnungen werden zusammengelegt, höchstens `MAX_DINGE`."""
    roh = antwort.get("dinge") if isinstance(antwort, dict) else None
    dinge, verworfen = collections.OrderedDict(), collections.Counter()
    klein = str(text or "").casefold()
    for d in roh if isinstance(roh, list) else []:
        if not isinstance(d, dict):
            continue
        bezeichnung = " ".join(str(d.get("bezeichnung") or "").split())
        schublade = " ".join(str(d.get("schublade") or "").split())
        if not schublade or DOKUMENTART.search(schublade):
            schublade = "Sonstiges"
        if not any(w.casefold() in klein for w in _NAMENSWORT.findall(bezeichnung)):
            verworfen["name"] += 1
            continue
        if DOKUMENT.search(bezeichnung) or DOKUMENTART.search(bezeichnung):
            verworfen["dokument"] += 1
            continue
        if AUFSICHT.search(bezeichnung):
            verworfen["aufsicht"] += 1
            continue
        angaben, gesehen = [], set()
        for a in d.get("angaben") if isinstance(d.get("angaben"), list) else []:
            if not isinstance(a, dict):
                continue
            merkmal, wert, zitat, grund = _pruefe_angabe(a, text, bezeichnung)
            wert = wissen.wert_einheitlich(merkmal, wert)    # erst nach der Prüfung: die prüft gegen das Zitat
            schluessel = (wissen.merkmal_kern(merkmal), kern(wert))
            if grund:
                verworfen[grund] += 1
            elif schluessel not in gesehen:
                gesehen.add(schluessel)
                angaben.append({"merkmal": merkmal, "wert": wert, "zitat": zitat,
                                "text": wissen.angabe_text(merkmal, wert)})
        ziel = dinge.setdefault(bezeichnung.casefold(), {"schublade": schublade, "bezeichnung": bezeichnung, "angaben": []})
        schon = {x["text"].casefold() for x in ziel["angaben"]}
        ziel["angaben"] += [a for a in angaben if a["text"].casefold() not in schon]
    # Eine Kundennummer gehört zur Firma, nie zur Person (Peter 19.11.2026: sonst sammeln sich bei einer Person die
    # Kundennummern vieler Firmen) - die KI hält sich nicht immer an den Prompt. Ohne eindeutige Firma: weg.
    firmen = [d for d in dinge.values() if d["schublade"].casefold() in KUNDE_BEI]
    for d in dinge.values():
        if not d["schublade"].casefold().startswith("person"):
            continue
        nummern = [a for a in d["angaben"] if wissen.merkmal_kern(a["merkmal"]) == "kundennummer"]
        if not nummern:
            continue
        d["angaben"] = [a for a in d["angaben"] if not any(a is n for n in nummern)]
        if len(firmen) != 1:
            verworfen["kunde"] += len(nummern)
            continue
        for a in nummern:
            if all((wissen.merkmal_kern(x["merkmal"]), kern(x["wert"])) != (wissen.merkmal_kern(a["merkmal"]), kern(a["wert"]))
                   for x in firmen[0]["angaben"]):
                firmen[0]["angaben"].append(a)
    # Zweiter Durchgang: nennt ein Wert ein anderes Ding dieses Dokuments, ist das eine Verbindung, keine Angabe
    for schl, d in dinge.items():
        andere = [kern(x["bezeichnung"]) for s, x in dinge.items() if s != schl]
        bleiben = [a for a in d["angaben"] if not any(len(o) >= 2 and o <= kern(a["wert"]) for o in andere)]
        if len(bleiben) < len(d["angaben"]):
            verworfen["verbindung"] += len(d["angaben"]) - len(bleiben)
        d["angaben"] = bleiben
    ergebnis = [d for d in dinge.values() if d["angaben"]]
    if len(ergebnis) < len(dinge):
        verworfen["ohne"] += len(dinge) - len(ergebnis)
    # Personen ohne eigene Kontaktangabe (kein Wert mit Ziffer oder @), mehrere in einem Dokument: eine Aufzählung wie
    # die Anwälte im Briefkopf - gezeigt, aber nicht vorgehakt (Peter 19.11.2026: „manchmal ganz sinnvoll“)
    nebenbei = [d for d in ergebnis if d["schublade"].casefold().startswith("person")
                and not any(re.search(r"[\d@]", a["wert"]) for a in d["angaben"])]
    for d in ergebnis:
        d["aufgezaehlt"] = len(nebenbei) >= AUFZAEHLUNG_AB and any(d is x for x in nebenbei)
    return ergebnis[:MAX_DINGE], verworfen


def einheitliche_merkmale(dinge, bekannte=()):
    """Gleichbedeutende Merkmale (`wissen.merkmal_kern`) auf eine Schreibweise bringen: die im Wiki schon benutzte
    (`bekannte`), sonst die zuerst genannte. Ändert die Angaben der Dinge (auch `text`) und gibt `dinge` zurück."""
    schreibweise = {}
    for m in bekannte:
        schreibweise.setdefault(wissen.merkmal_kern(m), m)
    for d in dinge:
        for a in d["angaben"]:
            a["merkmal"] = schreibweise.setdefault(wissen.merkmal_kern(a["merkmal"]), a["merkmal"])
            a["text"] = wissen.angabe_text(a["merkmal"], a["wert"])
    return dinge


_STRASSE = re.compile(r"str(\.|asse)?(?=[^a-z]|$)")
_FUELLWORT = {"herr", "herrn", "frau", "familie", "firma", "und", "ist", "lautet", "der", "die", "das", "des", "in", "im"}


def kern(text):
    """Wörter und Zahlen eines Namens oder einer Angabe, auf eine Schreibweise gebracht: klein, ß = ss, „Str.“ =
    „Straße“, ohne Satzzeichen und Füllwörter. Peter 13.11.2026: verschiedene Schreibweisen derselben Adresse ergaben
    neue Einträge."""
    t = _STRASSE.sub("strasse ", wissen.LAND_VOR_PLZ.sub("", str(text or "").casefold().replace("ß", "ss")))
    return frozenset(re.findall(r"[0-9a-zäöü]+", t)) - _FUELLWORT


def gleicher_name(a, b):
    """Dieselbe Sache gemeint? Gleiche Wörter (Reihenfolge, Anrede, Schreibweise egal). Bei Anschriften (mit
    Hausnummer) genügt es, wenn die eine Bezeichnung ganz in der anderen steckt („Musterstr. 8“ und „Musterstraße 8,
    12345 Musterstadt“)."""
    ka, kb = kern(a), kern(b)
    if not ka or not kb:
        return False
    if ka == kb:
        return True
    klein, gross = sorted((ka, kb), key=len)
    return len(klein) >= 2 and klein < gross and any(w.isdigit() for w in klein)


def gleiche_angabe(a, b):
    """Zwei Angaben sagen dasselbe: gleiche Wörter, oder dieselbe Nummer (ab 4 Ziffern: Telefon, Kunden-, Vertragsnummer,
    Datum) - auch wenn die Beschriftung anders lautet („Telefon: …“ und „Telefonnummer ist …“)."""
    if kern(a) == kern(b):
        return True
    za, zb = ("".join(_ZIFFERN.findall(str(t))) for t in (a, b))
    return len(za) >= 4 and za == zb


def finde_eintrag(bezeichnung, liste):
    """Der vorhandene Eintrag, der mit dieser Bezeichnung gemeint ist (`gleicher_name`), oder None - auch None, wenn
    mehrere passen. :param liste: wissen.Wissen.liste()"""
    treffer = [e for e in liste if gleicher_name(e["bezeichnung"], bezeichnung)]
    return treffer[0] if len(treffer) == 1 else None


def finde_ueber_zitate(zitate, eintraege):
    """Der Eintrag, der schon Angaben mit denselben Zitaten trägt - so wird ein Eintrag wiedererkannt, den der Mensch
    umbenannt oder umformuliert hat (das Zitat bleibt beim Ändern stehen). Der mit den meisten gemeinsamen Zitaten,
    None ohne Treffer oder bei Gleichstand. :param eintraege: geladene Einträge (wissen.Wissen.lade)"""
    gesucht = {" ".join(str(z).split()).casefold() for z in zitate if z}
    zahl = [(len(gesucht & {a["zitat"].casefold() for a in e["angaben"] if a["zitat"]}), e) for e in eintraege]
    zahl = sorted((z for z in zahl if z[0]), key=lambda z: -z[0])
    if not zahl or (len(zahl) > 1 and zahl[0][0] == zahl[1][0]):
        return None
    return zahl[0][1]


def ist_abgelehnt(angabe, abgelehnte):
    """Hat der Mensch diese Angabe schon einmal abgelehnt? Gleiches Zitat oder sinngleicher Text (`gleiche_angabe`) -
    die KI formuliert bei jedem Lauf etwas anders. :param abgelehnte: wissen.Wissen.abgelehnte(...)[kid_id] des
    Dokuments, aus dem die Angabe stammt"""
    zitat = " ".join(str(angabe.get("zitat") or "").split()).casefold()
    return any((zitat and zitat == " ".join(a["zitat"].split()).casefold()) or gleiche_angabe(angabe["text"], a["text"])
               for a in abgelehnte)


def bekannte_angabe(angabe, eintrag):
    """Die Angabe des Eintrags mit demselben Merkmal und Wert (`wissen.angabe_schluessel`) oder None. Nur dann ist ein
    weiteres Dokument eine weitere Quelle - „sinngleich“ (`gleiche_angabe`) reicht nicht: Zwei Merkmale mit denselben
    vier Ziffern (Baujahr 1998, Einzug 1998) sind verschiedene Angaben."""
    if "wert" not in angabe:
        return None
    schluessel = wissen.angabe_schluessel(angabe["merkmal"], angabe["wert"])
    return next((x for x in eintrag["angaben"] if wissen.angabe_schluessel(x["merkmal"], x["wert"]) == schluessel), None)


def neue_angaben(angaben, eintrag):
    """Von den vorgeschlagenen Angaben die, die im Eintrag noch nicht stehen - weder mit demselben Zitat noch
    sinngleich (`gleiche_angabe`)."""
    zitate = {a["zitat"].casefold() for a in eintrag["angaben"] if a["zitat"]}
    return [a for a in angaben if " ".join(a["zitat"].split()).casefold() not in zitate
            and not any(gleiche_angabe(a["text"], x["text"]) for x in eintrag["angaben"])]
