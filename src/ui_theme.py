"""
Helles Design im Stil von Windows 11 (Etappe 11, Peter 17.11.2026: „Variante B hell“).

Eine Stelle für Farben, Schrift und Stile. `wende_an(root)` läuft einmal beim Start, NACH
`theme_use("clam")` und VOR dem Aufbau der Fenster:

- ttk-Elemente bekommen ihre Stile über `ttk.Style` (wirkt sofort auf alle, auch spätere).
- Klassische tk-Elemente (rund 450 in 25 Dateien) bekommen Hintergrund, Rahmen und Schrift über die
  Options-Datenbank (`root.option_add`). Sie gilt für alles, was DANACH erzeugt wird; eine Farbe, die
  der Code ausdrücklich setzt (Bedeutungsfarben: Zeilenstatus, Tag-Markierung, Suchfeld gelb/grün …),
  geht immer vor. Darum muss kein Fenster einzeln umgebaut werden (Design-Probe 17.11.2026,
  `KID-Messungen/rauchtests_archiv/design_probe.py`).
- Titelleisten von Hauptfenster und allen Toplevels nehmen die Fensterfarbe an und bekommen runde
  Ecken (Windows 11, `DwmSetWindowAttribute`; unter Windows 10 wirkungslos, nie ein Fehler).

Die Schriftgröße bleibt die von Windows (TkDefaultFont wächst mit der Textgröße, FALLSTRICKE #69) -
getauscht wird nur die Schriftfamilie.
"""
import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from ui_utils import UIUtils

# Palette (Windows-11-nah). Bedeutungsfarben der App stehen bewusst NICHT hier, sie bleiben in ihren Modulen.
# Fenstergrund WEISS wie die Windows-Menüleiste, die sich unter Windows 11 nicht färben lässt (Peter 17.11.2026:
# „die weiße Fassung sieht sehr schön und sauber aus“; vorher hellgrau #f3f3f3 mit weißem Balken darüber,
# FALLSTRICKE #132). Gegliedert wird über die feinen Kanten der Listen und Felder, die Bereiche haben keinen Rahmen.
FARBEN = {
    "fenster": "#ffffff",        # Fenster- und Leistengrund
    "flaeche": "#ffffff",        # Listen, Bäume, Eingabefelder
    "rand": "#e3e3e3",           # feine Kanten
    "text": "#1b1b1b",
    "leise": "#616161",          # Spaltenköpfe, Nebentexte
    "akzent": "#0067c0",         # Windows-11-Standardakzent
    "akzent_hover": "#1975c5",
    "knopf": "#f5f5f5",          # leicht grau, damit Knöpfe sich vom Weiß abheben
    "knopf_hover": "#ebebeb",
    "gesperrt": "#a0a0a0",       # Schrift gesperrter Knöpfe
    "kopf": "#ffffff",           # Spaltenköpfe
    "reiter": "#f0f0f0",         # nicht gewählte Reiter
    "balken": "#cdcdcd",         # Bildlaufleisten
    "auswahl": "#cce4f7",        # markierte Zeile
    "vorschau": "#eeeeee",       # Grund hinter der PDF-Seite
    "gefahr": "#d9534f",         # Reset-„✖“
    "gefahr_hover": "#c9302c",
}

# Windows-11-Schrift; fehlt sie (Windows 10), bleibt Segoe UI
SCHRIFT_FAMILIE = "Segoe UI Variable Text"
_SCHRIFTEN = ("TkDefaultFont", "TkTextFont", "TkHeadingFont", "TkMenuFont", "TkTooltipFont", "TkSmallCaptionFont",
              "TkCaptionFont", "TkIconFont")
# Zeilenhöhe von Listen/Bäumen relativ zum Zeilenabstand der Schrift. Früher 4/3 (FALLSTRICKE #69: darunter
# schnitt Tk bei 125 % die Unterlängen ab), jetzt etwas luftiger.
ZEILEN_FAKTOR = 1.45
SASH_PX = 4             # Breite der Trennbalken (vorher 6)
# Innenabstand JEDES Bereichs des Hauptfensters (Ordnerbaum, Tags, Suchleiste, Liste, Eigenschaften, Vorschau) -
# zwischen zwei Bereichen liegen damit überall BEREICH_PX + SASH_PX + BEREICH_PX (Peter 17.11.2026: „die
# Trennräume vereinheitlichen“; vorher Eigenschaften 4 px, Vorschau 0 px)
BEREICH_PX = 5

# DwmSetWindowAttribute-Kennungen (Windows 11)
_DWM_DUNKEL = 20
_DWM_ECKEN = 33
_DWM_ECKEN_RUND = 2
_DWM_TITELFARBE = 35
_DWM_TITELTEXT = 36


def colorref(farbe):
    """'#rrggbb' -> Windows-COLORREF (0x00BBGGRR)."""
    r, g, b = int(farbe[1:3], 16), int(farbe[3:5], 16), int(farbe[5:7], 16)
    return r | (g << 8) | (b << 16)


def wende_an(root):
    """Design einmal anwenden: Schrift, ttk-Stile, Options-Datenbank, Titelleisten."""
    _schrift(root)
    _ttk_stile(root)
    _optionen(root)
    # Das Wurzelfenster entsteht VOR der Options-Datenbank und behielte sonst das Windows-Grau (#f0f0f0) als
    # Rand ums Fenster
    root.configure(bg=FARBEN["fenster"])
    _titelleisten(root)


def _schrift(root):
    try:
        probe = tkfont.Font(root=root, family=SCHRIFT_FAMILIE)
        vorhanden = probe.actual("family") == SCHRIFT_FAMILIE
    except tk.TclError:
        vorhanden = False
    if not vorhanden:
        return
    for name in _SCHRIFTEN:
        try:
            tkfont.nametofont(name, root=root).configure(family=SCHRIFT_FAMILIE)
        except tk.TclError:
            pass


def _ttk_stile(root):
    f = FARBEN
    s = ttk.Style(root)
    # Die Farben greifen nur im Theme „clam“ (die Windows-Themes zeichnen Knöpfe & Co. selbst). gui.py setzt es
    # schon; der Dienstmodus nicht.
    if s.theme_use() != "clam" and "clam" in s.theme_names():
        s.theme_use("clam")
    basis =tkfont.nametofont("TkDefaultFont", root=root)
    fett = (basis.actual("family"), basis.actual("size"), "bold")
    s.configure(".", background=f["fenster"], foreground=f["text"], bordercolor=f["rand"], lightcolor=f["fenster"],
                darkcolor=f["fenster"], troughcolor=f["fenster"], focuscolor=f["akzent"],
                selectbackground=f["akzent"], selectforeground="#ffffff", fieldbackground=f["flaeche"],
                insertcolor=f["text"])
    s.configure("TFrame", background=f["fenster"], bordercolor=f["rand"], lightcolor=f["rand"], darkcolor=f["rand"])
    s.configure("TLabel", background=f["fenster"], foreground=f["text"])
    s.configure("TButton", background=f["knopf"], foreground=f["text"], bordercolor=f["rand"],
                lightcolor=f["knopf"], darkcolor=f["knopf"], padding=(10, 4), relief="flat")
    s.map("TButton", background=[("pressed", f["rand"]), ("active", f["knopf_hover"])],
          lightcolor=[("active", f["knopf_hover"])], darkcolor=[("active", f["knopf_hover"])],
          bordercolor=[("focus", f["akzent"])])
    # Speichern & Co.: gefüllter Akzentknopf
    s.configure("Accent.TButton", background=f["akzent"], foreground="#ffffff", font=fett,
                lightcolor=f["akzent"], darkcolor=f["akzent"], bordercolor=f["akzent"])
    # Gesperrt grau wie jeder andere Knopf: vorher blieb er blau mit hellblauer Schrift und sah fast bedienbar
    # aus (Peter 22.11.2026, „Übernehmen und schließen“ gesperrt, solange nichts ansteht)
    s.map("Accent.TButton", background=[("disabled", f["knopf"]), ("active", f["akzent_hover"])],
          foreground=[("disabled", f["gesperrt"])], bordercolor=[("disabled", f["rand"])],
          lightcolor=[("disabled", f["knopf"])], darkcolor=[("disabled", f["knopf"])])
    # Reset-„✖“ neben dem Suchfeld: flacher Symbol-Knopf auf Leistenfarbe, nur beim Darüberfahren hinterlegt
    # (Peter 17.11.2026: vorher ein eigenes Grau, weder Feld noch Leiste)
    s.configure("Danger.TButton", foreground=f["gefahr"], font=fett, padding=(UIUtils.px(root, 1), 0),
                background=f["fenster"],
                bordercolor=f["fenster"], lightcolor=f["fenster"], darkcolor=f["fenster"])
    s.map("Danger.TButton", background=[("pressed", f["rand"]), ("active", f["knopf_hover"])],
          bordercolor=[("active", f["rand"])], lightcolor=[("active", f["knopf_hover"])],
          darkcolor=[("active", f["knopf_hover"])], foreground=[("active", f["gefahr_hover"])])

    # Monatskalender im Datumsdialog (B4e): flache Tagesknöpfe, heute in Akzentschrift, gewählter Tag gefüllt
    klein = (UIUtils.px(root, 2), UIUtils.px(root, 1))
    for stil, grund, schrift, extra in (("Kalender.TButton", f["flaeche"], f["text"], {}),
                                        ("KalenderHeute.TButton", f["flaeche"], f["akzent"], {"font": fett}),
                                        ("KalenderGewaehlt.TButton", f["akzent"], "#ffffff", {"font": fett})):
        s.configure(stil, padding=klein, background=grund, foreground=schrift, bordercolor=grund,
                    lightcolor=grund, darkcolor=grund, **extra)
        aktiv = f["akzent_hover"] if grund == f["akzent"] else f["knopf_hover"]
        s.map(stil, background=[("disabled", f["flaeche"]), ("pressed", f["rand"]), ("active", aktiv)],
              foreground=[("disabled", f["balken"])], lightcolor=[("active", aktiv)],
              darkcolor=[("active", aktiv)])
    s.configure("KalenderKopf.TLabel", foreground=f["leise"])
    # Aufklapp-Kalender unter dem Datumsfeld: weißer Grund mit feiner Kante
    s.configure("Klappe.TFrame", background=f["flaeche"], borderwidth=1, relief="solid", bordercolor=f["balken"],
                lightcolor=f["balken"], darkcolor=f["balken"])

    zeilenabstand = basis.metrics("linespace")
    s.configure("Treeview", background=f["flaeche"], fieldbackground=f["flaeche"], foreground=f["text"],
                bordercolor=f["rand"], lightcolor=f["flaeche"], darkcolor=f["flaeche"], borderwidth=0,
                rowheight=max(20, int(round(zeilenabstand * ZEILEN_FAKTOR))))
    # Nur Zustand "selected" - keine "!selected"-Einträge, sonst überdeckt die Map wieder die Schriftfarben der
    # Zeilen-Tags (Tk-8.6.9-Fehler, Fix in gui.py, FALLSTRICKE: Treeview-Tag-Schriftfarben)
    s.map("Treeview", background=[("selected", f["auswahl"])], foreground=[("selected", f["text"])])
    s.configure("Tags.Treeview", background=f["flaeche"], fieldbackground=f["flaeche"])
    # Spaltenköpfe: je eine 1-px-Linie unten und rechts (Peter 17.11.2026: auf Weiß brauchen sie einen Rahmen).
    # clam zeichnet „raised“ mit äußerer bordercolor + innerer light-/darkcolor; Außenlinie und helle Seite in
    # Kopffarbe unsichtbar, nur die dunkle Seite (unten/rechts) in `rand` - gemessen 1 px, „solid“ ergäbe 2-4 px.
    s.configure("Treeview.Heading", background=f["kopf"], foreground=f["leise"], relief="raised",
                bordercolor=f["kopf"], lightcolor=f["kopf"], darkcolor=f["rand"], padding=(6, 4))
    s.map("Treeview.Heading", background=[("active", f["knopf_hover"])],
          bordercolor=[("active", f["knopf_hover"])], lightcolor=[("active", f["knopf_hover"])])
    for w in ("TEntry", "TCombobox", "TSpinbox"):
        s.configure(w, fieldbackground=f["flaeche"], foreground=f["text"], bordercolor=f["rand"],
                    lightcolor=f["flaeche"], darkcolor=f["flaeche"], padding=4, arrowcolor=f["leise"],
                    background=f["knopf"])
        s.map(w, bordercolor=[("focus", f["akzent"])], lightcolor=[("focus", f["akzent"])])
    # Auswahlfeld zum Nur-Auswählen (readonly): clam füllt es mit Fokus dunkelblau, ohne grau (Peter 18.11.2026,
    # „Mails importieren“ → Mail-Programm). Hell wie ein Eingabefeld, den Fokus zeigt der blaue Rand.
    s.map("TCombobox", fieldbackground=[("readonly", "focus", f["flaeche"]), ("readonly", f["flaeche"])],
          foreground=[("readonly", "focus", f["text"])],
          selectbackground=[("readonly", "focus", f["flaeche"])], selectforeground=[("readonly", "focus", f["text"])],
          bordercolor=[("focus", f["akzent"])], lightcolor=[("focus", f["akzent"])])
    s.configure("TScrollbar", background=f["balken"], troughcolor=f["fenster"], bordercolor=f["fenster"],
                lightcolor=f["balken"], darkcolor=f["balken"], arrowcolor=f["leise"], gripcount=0, arrowsize=12,
                relief="flat")
    s.configure("TCheckbutton", background=f["fenster"], foreground=f["text"], indicatorbackground=f["flaeche"])
    s.configure("TRadiobutton", background=f["fenster"], foreground=f["text"], indicatorbackground=f["flaeche"])
    s.configure("TPanedwindow", background=f["fenster"])
    # Trennbalken zwischen den Bereichen 4 px (Peter 17.11.2026: Trennbereich 2-3 px schmaler; 3 px wären mit der
    # Maus schwer zu greifen)
    s.configure("Sash", sashthickness=SASH_PX, gripcount=0, background=f["fenster"], lightcolor=f["fenster"],
                darkcolor=f["fenster"])
    s.configure("TNotebook", background=f["fenster"], bordercolor=f["rand"], lightcolor=f["fenster"],
                darkcolor=f["fenster"])
    # Reiter: der gewählte verschmilzt mit der Seite, die anderen leicht abgesetzt mit leiser Schrift. Polster 8 px:
    # mit 12 px brauchten die 8 Reiter der Einstellungen 711 px bei rund 700 px Platz - Tk schnitt die Titel ab
    # (Peter 17.11.2026). Gewählt und nicht gewählt gleich groß (clam macht den gewählten sonst schmaler).
    s.configure("TNotebook.Tab", background=f["reiter"], foreground=f["leise"], bordercolor=f["rand"],
                lightcolor=f["reiter"], darkcolor=f["reiter"], padding=(8, 4))
    s.map("TNotebook.Tab", padding=[("selected", (8, 4))],
          background=[("selected", f["fenster"]), ("active", f["knopf_hover"])],
          lightcolor=[("selected", f["fenster"]), ("active", f["knopf_hover"])],
          darkcolor=[("selected", f["fenster"]), ("active", f["knopf_hover"])],
          foreground=[("selected", f["text"])])
    s.configure("TProgressbar", background=f["akzent"], troughcolor=f["rand"])


def _optionen(root):
    """
    Klassische tk-Elemente über die Options-Datenbank (Priorität widgetDefault: alles Ausdrückliche geht vor).

    Muster nur mit Options-NAMEN (klein: `background`), nie mit Options-KLASSEN (groß: `Background`): zur Klasse
    „Foreground“ gehören in Tk auch `activeBackground` der Menüs und `selectBackground` von Listen und Textfeldern,
    zur Klasse „Background“ `activeForeground` und `selectColor` der Häkchen. `*Foreground` machte so die
    Menü-Hervorhebung und jede Listenauswahl fast schwarz (Peter 17.11.2026, FALLSTRICKE #132). Menüs bleiben ganz
    bei den Windows-Farben.
    """
    f = FARBEN
    o = root.option_add
    for klasse in ("Frame", "Label", "Checkbutton", "Radiobutton", "Menubutton", "Toplevel", "Canvas", "Scale",
                   "LabelFrame", "PanedWindow", "Message"):
        o(f"*{klasse}.background", f["fenster"])
    for klasse in ("Entry", "Text", "Listbox", "Spinbox"):
        o(f"*{klasse}.background", f["flaeche"])
        o(f"*{klasse}.relief", "flat")
        o(f"*{klasse}.borderWidth", 0)
        o(f"*{klasse}.highlightThickness", 1)
        o(f"*{klasse}.highlightBackground", f["rand"])
        o(f"*{klasse}.highlightColor", f["akzent"])
    for klasse in ("Label", "Button", "Checkbutton", "Radiobutton", "Menubutton", "Entry", "Text", "Listbox",
                   "Spinbox", "Scale", "LabelFrame", "Message"):
        o(f"*{klasse}.foreground", f["text"])
    o("*Button.background", f["knopf"])
    o("*Button.relief", "flat")
    o("*Button.borderWidth", 0)
    o("*Button.highlightThickness", 1)
    o("*Button.highlightBackground", f["rand"])
    o("*Button.activeBackground", f["knopf_hover"])
    o("*Checkbutton.activeBackground", f["fenster"])
    o("*Radiobutton.activeBackground", f["fenster"])
    o("*Frame.highlightBackground", f["fenster"])
    o("*Label.highlightBackground", f["fenster"])


def _titelleisten(root):
    """Titelleiste in Fensterfarbe und runde Ecken - fürs Hauptfenster und jedes Toplevel beim ersten Anzeigen."""
    if sys.platform != "win32":
        return
    erledigt = set()

    def faerbe(widget):
        try:
            if widget.winfo_toplevel() is not widget or widget.wm_overrideredirect():
                return            # Tooltips & Co. haben keine Titelleiste
            hwnd = int(widget.wm_frame(), 16)
        except (tk.TclError, ValueError):
            return
        if hwnd in erledigt:
            return
        erledigt.add(hwnd)
        titelleiste(hwnd)

    root.bind("<Map>", lambda e: faerbe(e.widget) if e.widget is root else None, add="+")
    root.bind_class("Toplevel", "<Map>", lambda e: faerbe(e.widget), add="+")


def titelleiste(hwnd, farben=FARBEN):
    """DWM-Attribute eines Fensters setzen; jeder Fehler (Windows 10, kein DWM) bleibt folgenlos."""
    try:
        import ctypes
        dwm = ctypes.windll.dwmapi
        for attr, wert in ((_DWM_DUNKEL, 0), (_DWM_ECKEN, _DWM_ECKEN_RUND),
                           (_DWM_TITELFARBE, colorref(farben["fenster"])), (_DWM_TITELTEXT, colorref(farben["text"]))):
            v = ctypes.c_int(wert)
            dwm.DwmSetWindowAttribute(ctypes.c_void_p(hwnd), attr, ctypes.byref(v), ctypes.sizeof(v))
    except (AttributeError, OSError):
        pass
