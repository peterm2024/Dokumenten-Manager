import tkinter as tk


class TagAutocomplete:
    """
    Autovervollständigung mit bekannten Tags für ein tk.Text-Eingabefeld.

    Zeigt beim Tippen ein Dropdown mit passenden, bereits existierenden Tags
    aus dem Vorlagen-Baum an (Quelle: TagManager.get_known_tags). Bedienung:
    Pfeil hoch/runter wählt, Return/Tab übernimmt, Escape schließt, Mausklick
    übernimmt direkt. Vervollständigt wird immer nur der aktuelle Teil-Begriff
    am Cursor.

    Zwei Einsatzorte (13.09.2026):
    - Tags-Feld (Standard): Begriffe sind kommagetrennt, schon vergebene Tags werden nicht
      vorgeschlagen, nach der Übernahme laufen Baum-Sync und Auto-Save.
    - Suchfeld (`trenner=None`): Begriffe sind leerzeichengetrennt, ein Tag mit Leerzeichen
      wird in Anführungszeichen übernommen (Phrasensuche, search_manager.split_terms),
      danach ruft `nach_uebernahme` die Suche an.
    """

    MAX_SUGGESTIONS = 8

    def __init__(self, app, text=None, trenner=",", ausschluss_fn=None, nach_uebernahme=None):
        """
        :param app: Referenz auf die Hauptinstanz (DokumentenVerwaltung).
        :param text: das tk.Text-Feld; ohne Angabe app.entry_tags (Tags-Feld).
        :param trenner: Zeichen zwischen den Begriffen; None = Leerzeichen (Suchfeld).
        :param ausschluss_fn: liefert Begriffe, die nicht vorgeschlagen werden (Tags-Feld: schon vergebene).
        :param nach_uebernahme: wird nach dem Einsetzen eines Vorschlags aufgerufen.
        """
        self.app = app
        self.text = text if text is not None else self.app.entry_tags
        self.trenner = trenner
        self._ausschluss_fn = ausschluss_fn
        self._nach_uebernahme = nach_uebernahme
        if text is None and trenner == ",":
            # Standardverhalten des Tags-Felds (wie vor dem 13.09.2026)
            if self._ausschluss_fn is None:
                self._ausschluss_fn = lambda: self.app.tag_manager._get_current_tags()
            if self._nach_uebernahme is None:
                self._nach_uebernahme = self._tags_feld_nachlauf
        self.popup = None
        self.listbox = None
        self._matches = []
        self._index = 0

        widget = self.text
        # add="+": bestehende KeyRelease-Bindungen (Baum-Sync, Suche, Markierung) bleiben aktiv
        widget.bind("<KeyRelease>", self._on_keyrelease, add="+")
        widget.bind("<Down>", self._on_down)
        widget.bind("<Up>", self._on_up)
        widget.bind("<Return>", self._on_accept)
        widget.bind("<Tab>", self._on_accept)
        widget.bind("<Escape>", self._on_escape)
        widget.bind("<FocusOut>", lambda e: self._hide(), add="+")

    def _tags_feld_nachlauf(self):
        # Programmatischer Insert feuert kein KeyRelease -> Sync und Autosave manuell anstoßen
        self.app.tag_manager.sync_tag_tree_selection()
        self.app.save_manager.trigger_autosave()

    # ==========================================
    # EVENT-HANDLER
    # ==========================================
    def _on_keyrelease(self, event):
        # Navigations-/Bestätigungstasten aktualisieren die Vorschläge nicht
        if event.keysym in ("Down", "Up", "Return", "Tab", "Escape", "Shift_L", "Shift_R", "Control_L", "Control_R"):
            return

        token = self._current_token()
        if not token:
            self._hide()
            return

        try:
            ausgeschlossen = {t.lower() for t in (self._ausschluss_fn() if self._ausschluss_fn else [])}
        except Exception:
            ausgeschlossen = set()
        known = self.app.tag_manager.get_known_tags()
        token_lower = token.lower()

        # Präfix-Treffer zuerst, danach Enthalten-Treffer — ausgeschlossene Tags ausblenden
        starts = [t for t in known if t.lower().startswith(token_lower) and t.lower() not in ausgeschlossen]
        contains = [t for t in known if token_lower in t.lower() and not t.lower().startswith(token_lower) and t.lower() not in ausgeschlossen]
        self._matches = (starts + contains)[:self.MAX_SUGGESTIONS]

        # Exakter (einziger) Treffer ist bereits fertig getippt -> kein Popup nötig
        if not self._matches or (len(self._matches) == 1 and self._matches[0].lower() == token_lower):
            self._hide()
            return

        self._show()

    def _on_down(self, event):
        if not self._visible():
            return None
        self._index = (self._index + 1) % len(self._matches)   # von -1 (nichts gewählt) auf den ersten
        self._highlight()
        return "break"

    def _on_up(self, event):
        if not self._visible():
            return None
        self._index = (len(self._matches) - 1) if self._index < 0 else (self._index - 1) % len(self._matches)
        self._highlight()
        return "break"

    def _on_accept(self, event):
        """
        Return übernimmt einen Vorschlag nur, wenn er per Pfeiltaste angewählt ist; sonst gilt das
        Getippte und Return läuft zum nächsten Handler weiter (Speichern bzw. Suchen). Vorher nahm
        Return immer den ersten Vorschlag - aus einem neuen Tag „Test“ wurde ungefragt „Testament“
        (Fund T0.4, 25.10.2026).
        """
        if not self._visible():
            return None
        if self._index < 0:
            self._hide()
            return None
        self._insert_choice(self._matches[self._index])
        return "break"

    def _on_click(self, event):
        selection = self.listbox.curselection()
        if selection:
            self._insert_choice(self._matches[selection[0]])

    def _on_escape(self, event):
        if not self._visible():
            return None
        self._hide()
        return "break"

    # ==========================================
    # KERNLOGIK
    # ==========================================
    def _token_start(self, before):
        """Zeichen-Offset (ab Textanfang), an dem der aktuelle Teil-Begriff beginnt."""
        if self.trenner is not None:
            last = before.rfind(self.trenner)
            return last + 1 if last >= 0 else 0
        # Suchfeld: eine offene Anführungszeichen-Phrase zählt als EIN Begriff
        offen = before.rfind('"')
        if offen >= 0 and before.count('"') % 2 == 1:
            return offen
        last = max(before.rfind(" "), before.rfind("\t"))
        return last + 1 if last >= 0 else 0

    def _current_token(self):
        """Liefert den Teil-Begriff zwischen letztem Trenner und Cursor (gestrippt, ohne Anführungszeichen)."""
        before = self.text.get("1.0", "insert")
        return before[self._token_start(before):].strip().strip('"').strip()

    def _insert_choice(self, choice):
        """Ersetzt den aktuellen Teil-Begriff durch den gewählten Vorschlag."""
        text = self.text
        before = text.get("1.0", "insert")
        start_chars = self._token_start(before)
        text.delete(f"1.0 + {start_chars} chars", "insert")
        if self.trenner is not None:
            prefix = " " if start_chars > 0 else ""
            text.insert("insert", f"{prefix}{choice}{self.trenner} ")
        else:
            wert = f'"{choice}"' if " " in choice else choice
            text.insert("insert", f"{wert} ")

        self._hide()
        if self._nach_uebernahme is not None:
            self._nach_uebernahme()

    # ==========================================
    # POPUP-DARSTELLUNG
    # ==========================================
    def _visible(self):
        return self.popup is not None and self.popup.winfo_exists() and self.popup.winfo_viewable()

    def _show(self):
        text = self.text
        bbox = text.bbox("insert")
        if not bbox:
            self._hide()
            return

        if self.popup is None or not self.popup.winfo_exists():
            self.popup = tk.Toplevel(self.app.root)
            self.popup.overrideredirect(True)  # Kein Fensterrahmen
            self.popup.attributes("-topmost", True)
            self.listbox = tk.Listbox(self.popup, activestyle="none",
                                      highlightthickness=1, highlightbackground="#999999",
                                      selectbackground="#0078D7", selectforeground="white")
            self.listbox.pack(fill=tk.BOTH, expand=True)
            self.listbox.bind("<ButtonRelease-1>", self._on_click)

        self.listbox.delete(0, tk.END)
        for match in self._matches:
            self.listbox.insert(tk.END, f" {match}")
        self.listbox.config(height=len(self._matches))
        self._index = -1   # nichts vorgewählt - erst eine Pfeiltaste wählt (siehe _on_accept)
        self._highlight()

        # Direkt unter dem Cursor im Textfeld positionieren
        x = text.winfo_rootx() + bbox[0]
        y = text.winfo_rooty() + bbox[1] + bbox[3]
        width = max(180, min(400, self.listbox.winfo_reqwidth() + 20))
        self.popup.geometry(f"{width}x{self.listbox.winfo_reqheight()}+{x}+{y}")
        self.popup.deiconify()

    def _highlight(self):
        self.listbox.selection_clear(0, tk.END)
        if self._index >= 0:
            self.listbox.selection_set(self._index)
            self.listbox.see(self._index)

    def _hide(self):
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.withdraw()
