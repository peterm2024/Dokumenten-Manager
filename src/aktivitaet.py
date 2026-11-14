"""
Aktivitätsanzeige in der Menüleiste (Nutzerwunsch 11.09.2026 nach dem Besuch beim Betatest:
auf dem alten Rechner reagiert das Programm träge, und ohne Rückmeldung weiß man nicht, ob
noch etwas passiert oder auf eine "unsichtbare" Eingabe gewartet wird).

Rechts neben „Hilfe" steht ein ausgegrauter Menüeintrag ohne Funktion, dessen Text die
laufende Phase in Klartext zeigt: „Lese Ordner „A - B" 12/80…", „Vorschau wird
gezeichnet…", „KI antwortet… (14 s)", „Wartet auf deine Antwort: „Datei umbenennen"".
Im Ruhezustand „Bereit". Läuft eine Phase länger als ein paar Sekunden, dreht sich ein
Zeichen und die Dauer wird angezeigt - man sieht, dass es weitergeht.

Benutzung aus jedem Modul, ohne die GUI zu kennen:

    with aktivitaet.phase("Lese Ordner…") as p:
        for i, datei in enumerate(dateien, 1):
            p.melde(f"Lese Ordner {i}/{len(dateien)}…")   # optional
            aktivitaet.atme()                             # in langen Schleifen im Tk-Thread

    with aktivitaet.warte_auf_antwort("Datei umbenennen"):
        antwort = messagebox.askyesno(...)

Ohne registrierte Anzeige (Tests, Skripte) sind alle Funktionen wirkungslos. Aufrufe aus
Hintergrund-Threads sind erlaubt - die Anzeige leitet sie per root.after in den
Tk-Thread; `atme()` wirkt nur im Tk-Thread (update_idletasks aus einem Thread wäre ein
Absturzrisiko).
"""
import itertools
import threading
import time

_anzeige = None          # die registrierte Anzeige (Anzeige-Instanz) oder None
_zaehler = itertools.count(1)

RUHE_TEXT = "Bereit"
SPINNER = "|/-\\"
TICK_MS = 250
DAUER_AB_SEKUNDEN = 3    # ab hier wird "(12 s)" angehängt
ATEM_ABSTAND = 0.1       # update_idletasks höchstens alle 100 ms


def registriere(anzeige):
    """Meldet die GUI-Anzeige an (layout_builder); None meldet sie ab."""
    global _anzeige
    _anzeige = anzeige


def beginne(text, nebensache=False):
    """Startet eine Phase, liefert ein Token für aktualisiere/beende. `nebensache`: Hilfsschritt einer Aufgabe, zum
    Beispiel die KI-Anfrage: Er verdeckt deren Text nicht, sondern steht nur als Dauer dahinter."""
    token = next(_zaehler)
    if _anzeige is not None:
        _anzeige.beginne(token, text, nebensache)
    return token


def aktualisiere(token, text):
    if _anzeige is not None:
        _anzeige.aktualisiere(token, text)


def beende(token):
    if _anzeige is not None:
        _anzeige.beende(token)


def atme():
    """Lässt die Oberfläche in einer langen synchronen Schleife kurz zeichnen (gedrosselt)."""
    if _anzeige is not None:
        _anzeige.atme()


def kurz(name, laenge=40):
    """Ein Dateiname für die Menüleiste, deren Platz knapp ist. Die Auslassungspunkte setzt der Aufrufer ans Ende der Phase."""
    return name[:laenge]


class phase:
    """Kontextmanager für eine Phase; p.melde(text) aktualisiert den Text."""

    def __init__(self, text, nebensache=False):
        self.text = text
        self.nebensache = nebensache
        self.token = None

    def __enter__(self):
        self.token = beginne(self.text, self.nebensache)
        return self

    def melde(self, text):
        self.text = text
        aktualisiere(self.token, text)

    def __exit__(self, *_exc):
        beende(self.token)
        return False


def warte_auf_antwort(titel):
    """Phase „Wartet auf deine Antwort: „<Dialogtitel>"" um einen modalen Dialog herum."""
    return phase(f"Wartet auf deine Antwort: „{titel}\"")


class Anzeige:
    """
    GUI-Teil: pflegt den Menüeintrag `index` der `menubar`. Alle öffentlichen Methoden
    sind thread-sicher (Umleitung per root.after, wenn nicht im Tk-Thread).
    """

    def __init__(self, root, menubar, index, ruhe_text=RUHE_TEXT):
        self.root = root
        self.menubar = menubar
        self.index = index
        self.ruhe_text = ruhe_text
        self._phasen = []        # Liste von [token, text, startzeit] - die letzte ist sichtbar
        self._spinner = itertools.cycle(SPINNER)
        self._tick_job = None
        self._letzter_atem = 0.0
        self._tk_thread = threading.current_thread()
        self._letzter_text = ruhe_text   # der Eintrag wurde mit diesem Text angelegt
        self._zeige(ruhe_text)

    # ------------------------------------------------------------ Thread-Umleitung
    def _im_tk_thread(self):
        return threading.current_thread() is self._tk_thread

    def _ausfuehren(self, fn, *args):
        if self._im_tk_thread():
            fn(*args)
        else:
            try:
                self.root.after(0, fn, *args)
            except Exception:
                pass   # Fenster schon weg - Anzeige ist dann egal

    # ------------------------------------------------------------ öffentlich
    def beginne(self, token, text, nebensache=False):
        self._ausfuehren(self._beginne, token, text, nebensache)

    def aktualisiere(self, token, text):
        self._ausfuehren(self._aktualisiere, token, text)

    def beende(self, token):
        self._ausfuehren(self._beende, token)

    def atme(self):
        if not self._im_tk_thread():
            return
        jetzt = time.monotonic()
        if jetzt - self._letzter_atem < ATEM_ABSTAND:
            return
        self._letzter_atem = jetzt
        try:
            self.root.update_idletasks()
        except Exception:
            pass

    def aktueller_text(self):
        """Sichtbarer Text (für Tests/Smoke)."""
        try:
            return self.menubar.entrycget(self._finde_index(), "label")
        except Exception:
            return ""

    def _finde_index(self):
        """
        Aktueller Index des Anzeige-Eintrags. Der bei der Anlage gemerkte Index stimmt
        nicht mehr, sobald davor etwas eingefügt wird (der ToolManager schiebt „Tools"
        vor „Hilfe") - Live-Fund im Rauchtest: der Text landete auf dem „Hilfe"-Eintrag.
        Deshalb wird der einzige Kommando-Eintrag der Leiste mit dem zuletzt
        geschriebenen Text gesucht; Rückfall: der gemerkte Index.
        """
        try:
            ende = self.menubar.index("end")
            for i in range((ende if ende is not None else -1) + 1):
                if self.menubar.type(i) == "command" and self.menubar.entrycget(i, "label") == self._letzter_text:
                    return i
        except Exception:
            pass
        return self.index

    def laeuft(self):
        return bool(self._phasen)

    # ------------------------------------------------------------ intern (Tk-Thread)
    def _beginne(self, token, text, nebensache=False):
        self._phasen.append([token, text, time.monotonic(), nebensache])
        self._zeichne(sofort=True)
        if self._tick_job is None:
            self._tick_job = self.root.after(TICK_MS, self._tick)

    def _aktualisiere(self, token, text):
        for eintrag in self._phasen:
            if eintrag[0] == token:
                eintrag[1] = text
        self._zeichne(sofort=True)

    def _beende(self, token):
        self._phasen = [e for e in self._phasen if e[0] != token]
        self._zeichne(sofort=False)
        if not self._phasen and self._tick_job is not None:
            try:
                self.root.after_cancel(self._tick_job)
            except Exception:
                pass
            self._tick_job = None

    def _tick(self):
        self._tick_job = None
        if self._phasen:
            self._zeichne(sofort=False)
            self._tick_job = self.root.after(TICK_MS, self._tick)

    def _zeichne(self, sofort):
        if not self._phasen:
            self._zeige(self.ruhe_text)
            return
        _token, text, start, nebensache = self._phasen[-1]
        dauer = time.monotonic() - start
        aufgabe = next((p[1] for p in reversed(self._phasen) if not p[3]), None) if nebensache else None
        if aufgabe:             # Die Menüleiste sagt, woran die KI arbeitet, nicht nur dass sie es tut (FALLSTRICKE #112)
            text = aufgabe
            zusatz = f" (KI {int(dauer)} s)" if dauer >= DAUER_AB_SEKUNDEN else ""
        else:
            zusatz = f" ({int(dauer)} s)" if dauer >= DAUER_AB_SEKUNDEN else ""
        self._zeige(f"{next(self._spinner)} {text}{zusatz}")
        if sofort:
            # Vor einer synchronen Phase muss der Text noch auf den Schirm - danach
            # kommt die Oberfläche erst wieder zum Zeichnen, wenn die Phase vorbei ist.
            # Ungedrosselt: ein Phasenstart darf nie im Drossel-Fenster untergehen.
            self._letzter_atem = 0.0
            self.atme()

    def _zeige(self, text):
        try:
            self.menubar.entryconfigure(self._finde_index(), label=text)
            self._letzter_text = text
        except Exception:
            pass
