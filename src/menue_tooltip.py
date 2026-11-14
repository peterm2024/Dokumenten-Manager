"""
Erklärung beim Verweilen auf einem Menüeintrag (Menü-Hilfe Stufe 3, Vorbild Autodesk
Inventor, Nutzerwunsch 11.09.2026): bleibt der Mauszeiger etwas länger als eine Sekunde auf
einem Eintrag, erscheint rechts neben dem Menü ein Fensterchen mit „Was“ und „Wofür“ aus
menue_hilfe. Wechselt der Eintrag, wandert die Erklärung mit; schließt das Menü, verschwindet sie.

Technik (Machbarkeit am 11.09.2026 mit simulierter Maus geprüft, FALLSTRICKE #65):
- Tk feuert `<<MenuSelect>>`, sobald sich der markierte Eintrag ändert - auch bei den
  nativen Windows-Menüs, und `root.after`-Zeitgeber laufen währenddessen weiter.
- Für Menüleiste und Kaskaden legt Tk KLONE an (Namen wie `.#!menu.#!menu#!menu`), die
  tkinter nicht kennt: `event.widget` ist dann nur der Name als String. Der aktive Eintrag
  wird deshalb per Tcl direkt abgefragt (`index active`, `entrycget … -label`).
- Welches Menü das ist (Datei? Rechtsklick Dokument? Tools → Aufräumen?), erkennt die
  Anzeige an der Liste seiner Einträge: beim ersten Bedarf werden alle bekannten Menüs
  abgelaufen und ihre Label-Folgen den Menü-Pfaden zugeordnet (Klon und Original haben
  dieselben Einträge).
- Position: rechts neben dem offenen Menüfenster (Windows-Fensterklasse #32768 per
  ctypes), sonst rechts unter dem Mauszeiger.
"""
import ctypes
import sys
import tkinter as tk

import menue_hilfe

VERWEIL_MS = 1100          # so lange muss der Zeiger auf dem Eintrag bleiben
TEXT_BREITE = 380          # Umbruchbreite der Erklärung in Pixeln
ABSTAND = 6                # Luft zwischen Menü und Fensterchen
HINTERGRUND = "#fffbe6"
TITEL_FARBE = "#1f4e79"


def pfad_fuer_labels(menues, labels):
    """
    Menü-Pfad zu einer Label-Folge: `menues` ist ein Dict {Pfad: (Labels…)} aus dem Menü-Lauf,
    `labels` die Einträge des Menüs, in dem gerade gewählt wurde (ohne Trenner/Tearoff).
    Liefert None, wenn kein Menü diese Einträge hat.
    """
    gesucht = tuple(labels)
    for pfad, bekannt in menues.items():
        if tuple(bekannt) == gesucht:
            return pfad
    return None


def erklaerungs_text(eintrag):
    """Text des Fensterchens: erst „Was“, dann „Wofür“ (die Überschrift zeigt der Aufrufer separat)."""
    return f"Was: {eintrag.was}\n\nWofür: {eintrag.wofuer or '(keine Erklärung hinterlegt)'}"


class MenueTooltip:
    """
    Hängt sich an alle Menüs der Anwendung (bind_all auf <<MenuSelect>>) und zeigt die
    Erklärung aus menue_hilfe. `eintraege_fn` liefert bei Bedarf die aktuelle Liste der
    Einträge (damit Tools, die später geladen werden, dabei sind); `zusatz_menues` sind
    Menüs außerhalb der Menüleiste mit ihrem Pfad, z.B. {"Rechtsklick Ordner": menu}.
    `aktiv_fn` (optional) kann die Anzeige abschalten (Einstellung).
    """

    def __init__(self, root, eintraege_fn, zusatz_menues=None, aktiv_fn=None):
        self.root = root
        self.eintraege_fn = eintraege_fn
        self.zusatz_menues = dict(zusatz_menues or {})
        self.aktiv_fn = aktiv_fn or (lambda: True)
        self._menues = None          # {Pfad: (Labels…)}, lazy
        self._job = None
        self._fenster = None
        self._eintraege = None
        self.letzter_eintrag = None  # zuletzt gezeigter Eintrag (Tests/Rauchtest)
        root.bind_all("<<MenuSelect>>", self._on_menu_select, add="+")

    # ------------------------------------------------------------ Menü-Registrierung
    def registriere_menue(self, pfad, menu):
        self.zusatz_menues[pfad] = menu
        self._menues = None

    @staticmethod
    def _labels(tk_call, menu_name):
        """Label-Folge eines Menüs (per Tcl, funktioniert für Originale und Klone)."""
        labels = []
        try:
            ende = tk_call(menu_name, "index", "end")
        except tk.TclError:
            return labels
        if ende in ("none", None, ""):
            return labels
        for i in range(int(ende) + 1):
            typ = tk_call(menu_name, "type", i)
            if typ in ("separator", "tearoff"):
                continue
            labels.append(str(tk_call(menu_name, "entrycget", i, "-label")))
        return labels

    def _baue_menue_karte(self):
        """Alle bekannten Menüs ablaufen: Menüleiste samt Kaskaden plus zusatz_menues."""
        karte = {}
        call = self.root.tk.call

        def lauf(menu_name, pfad):
            karte[pfad] = tuple(self._labels(call, menu_name))
            try:
                ende = call(menu_name, "index", "end")
                for i in range(int(ende) + 1):
                    if call(menu_name, "type", i) == "cascade":
                        unter = str(call(menu_name, "entrycget", i, "-menu"))
                        label = str(call(menu_name, "entrycget", i, "-label"))
                        if unter:
                            lauf(unter, f"{pfad} → {label}" if pfad else label)
            except (tk.TclError, ValueError):
                pass

        try:
            leiste = str(self.root.cget("menu"))
            if leiste:
                lauf(leiste, "")
        except tk.TclError:
            pass
        for pfad, menu in self.zusatz_menues.items():
            lauf(str(menu), pfad)
        return karte

    def _pfad_fuer(self, menu_name):
        labels = self._labels(self.root.tk.call, menu_name)
        if self._menues is None:
            self._menues = self._baue_menue_karte()
        pfad = pfad_fuer_labels(self._menues, labels)
        if pfad is None:
            # Menü seit dem letzten Lauf verändert (z.B. Tools nachgeladen): einmal neu aufbauen
            self._menues = self._baue_menue_karte()
            pfad = pfad_fuer_labels(self._menues, labels)
        return pfad

    # ------------------------------------------------------------ Ereignis
    def _on_menu_select(self, event):
        menu_name = str(event.widget)
        self._abbrechen()
        try:
            idx = self.root.tk.call(menu_name, "index", "active")
            if idx in ("none", None, ""):
                self._verstecke()
                return
            label = str(self.root.tk.call(menu_name, "entrycget", idx, "-label"))
        except tk.TclError:
            self._verstecke()
            return
        if not self.aktiv_fn():
            return
        self._job = self.root.after(VERWEIL_MS, lambda: self._zeige_fuer(menu_name, label))

    def _abbrechen(self):
        if self._job is not None:
            try:
                self.root.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _zeige_fuer(self, menu_name, label):
        self._job = None
        pfad = self._pfad_fuer(menu_name)
        if pfad == "":
            self._verstecke()      # Menüleiste selbst (Datei/Ansicht/…): keine Erklärung
            return
        if self._eintraege is None:
            self._eintraege = self.eintraege_fn()
        eintrag = menue_hilfe.finde(self._eintraege, label, menue=pfad)
        if eintrag is None and pfad and " → " in pfad:
            eintrag = menue_hilfe.finde(self._eintraege, label)   # Notnagel ohne Pfad
        if eintrag is None:
            self._verstecke()
            return
        self.letzter_eintrag = eintrag
        self._zeige(eintrag)

    def eintraege_neu_laden(self):
        """Nach dem Laden weiterer Tools aufrufen (oder einfach beim nächsten Fenster-Öffnen)."""
        self._eintraege = None
        self._menues = None

    # ------------------------------------------------------------ Fenster
    def _zeige(self, eintrag):
        self._verstecke()
        w = tk.Toplevel(self.root)
        w.overrideredirect(True)
        try:
            w.attributes("-topmost", True)
        except tk.TclError:
            pass
        rahmen = tk.Frame(w, bg=HINTERGRUND, bd=1, relief="solid")
        rahmen.pack()
        tk.Label(rahmen, text=eintrag.label.replace("🛠 ", ""),
                 bg=HINTERGRUND, fg=TITEL_FARBE, font=("Segoe UI", 10, "bold"), justify="left",
                 wraplength=TEXT_BREITE, anchor="w").pack(fill="x", padx=10, pady=(8, 2))
        tk.Label(rahmen, text=erklaerungs_text(eintrag), bg=HINTERGRUND, fg="#222222",
                 font=("Segoe UI", 10), justify="left", wraplength=TEXT_BREITE, anchor="w").pack(padx=10, pady=(0, 8))
        w.update_idletasks()
        x, y = self._position(w.winfo_reqwidth(), w.winfo_reqheight())
        w.geometry(f"+{x}+{y}")
        self._fenster = w

    def _verstecke(self):
        if self._fenster is not None:
            try:
                self._fenster.destroy()
            except tk.TclError:
                pass
            self._fenster = None

    def sichtbar(self):
        return self._fenster is not None and bool(self._fenster.winfo_exists())

    def _position(self, breite, hoehe):
        """Rechts neben dem offenen Menüfenster auf Höhe des Zeigers; sonst rechts unter dem Zeiger."""
        px, py = self.root.winfo_pointerxy()
        x, y = px + 24, py + 12
        rechts = _menuefenster_rechte_kante()
        if rechts is not None:
            x, y = rechts + ABSTAND, py - 10
        sw, sh = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        if x + breite > sw:
            x = max(0, px - breite - 24)
        if y + hoehe > sh:
            y = max(0, sh - hoehe - 4)
        return x, y


def _menuefenster_rechte_kante():
    """Rechte Kante des gerade offenen Windows-Popup-Menüs (Fensterklasse #32768) oder None."""
    if not sys.platform.startswith("win"):
        return None
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW("#32768", None)
        if not hwnd or not user32.IsWindowVisible(hwnd):
            return None

        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        r = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return None
        return int(r.right)
    except Exception:
        return None
