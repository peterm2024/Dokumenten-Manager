import logging
import os
import importlib.util
import inspect
import tkinter as tk
import tkinter.messagebox as mb

# Importiert unsere Schnittstellen-Vorlagen
from tools.base_tool import BaseTool, ToolContext

# Reihenfolge der Untermenüs im Tools-Menü (Tools nennen ihre Gruppe in menu_group)
GRUPPEN_REIHENFOLGE = ("Vollautomatik", "KI-Helfer", "Aufräumen", "PDF-Werkzeuge")


def gruppiere_tools(tools):
    """
    Ordnet Tools ihren Untermenü-Gruppen zu: Liste von (Gruppe, [Tools]) in Menü-
    Reihenfolge - erst GRUPPEN_REIHENFOLGE, dann unbekannte Gruppen in Auftrittsfolge,
    zuletzt ('', Tools ohne Gruppe). Innerhalb einer Gruppe bleibt die Ladereihenfolge.
    Reine Logik ohne Tkinter (testbar).
    """
    nach_gruppe = {}
    for tool in tools:
        gruppe = (getattr(tool, "menu_group", "") or "").strip()
        nach_gruppe.setdefault(gruppe, []).append(tool)
    reihenfolge = [g for g in GRUPPEN_REIHENFOLGE if g in nach_gruppe]
    reihenfolge += [g for g in nach_gruppe if g and g not in reihenfolge]
    ergebnis = [(g, nach_gruppe[g]) for g in reihenfolge]
    if "" in nach_gruppe:
        ergebnis.append(("", nach_gruppe[""]))
    return ergebnis


class ToolManager:
    def __init__(self, app):
        """Verwaltet alle externen Plugins und bindet sie in die GUI ein."""
        self.app = app
        self.tools = []
        # Menüeinträge je Tool [(menu, index), ...] - damit ki_status die Einträge der
        # KI-Werkzeuge sperren kann, solange der Server nicht erreichbar ist (13.09.2026)
        self._eintraege = {}
        self.ki_erreichbar = None   # None = noch nicht geprüft, sonst True/False
        self._load_tools()

    def _load_tools(self):
        """
        Scannt den 'tools'-Ordner und lädt alle Klassen, die von BaseTool erben.
        Ein Tool, das sich nicht laden lässt, fehlt einfach im Menü - der Grund gehört
        deshalb ins LOG und nicht auf die (bei --noconsole unsichtbare) Konsole:
        genau so blieben in der Release-EXE v0.9.3 zwei Tools unbemerkt weg (FALLSTRICKE #39).
        """
        tools_dir = os.path.join(os.path.dirname(__file__), "tools")
        if not os.path.exists(tools_dir):
            os.makedirs(tools_dir)
            return

        for filename in os.listdir(tools_dir):
            if filename.endswith(".py") and filename != "base_tool.py" and not filename.startswith("__"):
                module_name = filename[:-3]
                file_path = os.path.join(tools_dir, filename)
                
                try:
                    # Dynamischer Import der Python-Datei
                    spec = importlib.util.spec_from_file_location(module_name, file_path)
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    # Suche nach Tool-Klassen im geladenen Modul
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if issubclass(obj, BaseTool) and obj is not BaseTool:
                            tool_instance = obj()
                            self.tools.append(tool_instance)
                            if hasattr(self.app, 'logger'):
                                self.app.logger.info(f"Tool geladen: {tool_instance.name}")
                except Exception as e:
                    meldung = f"Tool '{filename}' konnte nicht geladen werden: {e}"
                    logging.getLogger("DocManager").error(meldung)

    def execute_tool(self, tool):
        """Sammelt die GUI-Daten (Context) und startet das ausgewählte Tool."""
        if getattr(tool, "braucht_ki", False) and self.ki_erreichbar is False:
            # Zweite Sperre neben dem ausgegrauten Menü (Tastatur, Kontextmenü, Skripte)
            url = self.app.config.get("ollama_url", "") if hasattr(self.app, "config") else ""
            mb.showwarning(
                "KI-Server nicht erreichbar",
                f"„{tool.name}“ braucht den KI-Server, der unter {url} zurzeit nicht antwortet.\n\n"
                "Server einschalten oder die Adresse unter Datei → Einstellungen → KI-Server prüfen. "
                "Sobald er antwortet, wird die LED in der Suchleiste grün und die KI-Werkzeuge sind wieder frei.")
            return False
        context = self.kontext()
        selected_files = context.selected_files
                
        # --- SICHERHEITS-VALIDIERUNG ---
        if tool.required_input == "single_file" and len(selected_files) != 1:
            mb.showinfo("Hinweis", f"Das Tool '{tool.name}' erfordert exakt EINE ausgewählte Datei.")
            return
        elif tool.required_input == "multiple_files" and len(selected_files) < 1:
            mb.showinfo("Hinweis", f"Das Tool '{tool.name}' erfordert mindestens eine ausgewählte Datei.")
            return
            
        # Tool ausführen!
        try:
            tool.execute(context)
        except Exception as e:
            mb.showerror("Tool-Fehler", f"Das Tool '{tool.name}' hat einen Fehler verursacht:\n{e}")

    def kontext(self):
        """Der „Koffer“ für ein Tool: die in der Dateiliste markierten Dateien (absolute Pfade) und die App."""
        selected_files = []
        if hasattr(self.app, 'tree_files'):
            for item in self.app.tree_files.selection():
                rel_path = self.app.tree_files.item(item, "values")[4]
                selected_files.append(os.path.join(self.app.master_folder, rel_path))
        return ToolContext(
            selected_files=selected_files,
            current_folder=getattr(self.app, 'master_folder', ""),
            logger=getattr(self.app, 'logger', None),
            app_reference=self.app
        )

    # ==========================================
    # GUI EINBINDUNG
    # ==========================================
    def populate_context_menu(self, context_menu):
        """Fügt alle Tools ins Rechtsklick-Menü ein, die das angefordert haben. Ein Tool mit der Methode
        `fuelle_kontextmenue(menu, context)` bekommt statt eines Eintrags ein Untermenü, das es bei jedem Öffnen frisch
        füllt (Wiki, Peter 12.11.2026) - Tk ruft `postcommand` der Kaskaden, bevor das Rechtsklick-Menü erscheint."""
        relevant_tools = [t for t in self.tools if "context_menu" in t.menu_hooks]
        if not relevant_tools: return

        context_menu.add_separator()
        for tool in relevant_tools:
            if callable(getattr(tool, "fuelle_kontextmenue", None)):
                unter = tk.Menu(context_menu, tearoff=0)
                unter.configure(postcommand=lambda t=tool, m=unter: self.fuelle_untermenue(t, m))
                context_menu.add_cascade(label=f"🛠 {tool.name}", menu=unter)
            else:
                # Lambda-Trickserei für Tkinter, damit der Button weiß, welches Tool er ist
                context_menu.add_command(
                    label=f"🛠 {tool.name}",
                    command=lambda t=tool: self.execute_tool(t)
                )
            self._merke_eintrag(tool, context_menu)

    def fuelle_untermenue(self, tool, menu):
        """Das Untermenü eines Tools leeren (samt seinen Unter-Untermenüs) und vom Tool neu füllen lassen. Ein Fehler
        darin kostet nur das Untermenü; ins Protokoll nur die Art des Fehlers (keine Pfade oder Namen)."""
        for kind in menu.winfo_children():
            kind.destroy()
        menu.delete(0, "end")
        try:
            tool.fuelle_kontextmenue(menu, self.kontext())
        except Exception as e:  # noqa: BLE001 - ein Tool darf das Rechtsklick-Menü nicht kaputtmachen
            logging.getLogger("DocManager").error(f"Tool '{tool.name}': Untermenü nicht gefüllt ({type(e).__name__})")
            for kind in menu.winfo_children():
                kind.destroy()
            menu.delete(0, "end")
            menu.add_command(label="(gerade nicht verfügbar, siehe Protokoll)", state=tk.DISABLED)

    def _merke_eintrag(self, tool, menu):
        """Den zuletzt in `menu` angefügten Eintrag diesem Tool zuordnen (für setze_ki_verfuegbar)."""
        try:
            self._eintraege.setdefault(tool, []).append((menu, menu.index("end")))
        except tk.TclError:
            pass

    def setze_ki_verfuegbar(self, erreichbar):
        """
        Menüeinträge aller Tools mit `braucht_ki` sperren (erreichbar False) bzw. freigeben
        (True oder None = noch ungeprüft). Abonnent von ki_status.KiStatus; läuft im Tk-Thread.
        """
        self.ki_erreichbar = erreichbar
        zustand = "disabled" if erreichbar is False else "normal"
        for tool, eintraege in self._eintraege.items():
            if not getattr(tool, "braucht_ki", False):
                continue
            for menu, index in eintraege:
                try:
                    menu.entryconfig(index, state=zustand)
                except tk.TclError:
                    pass

    def ki_tools(self):
        """Namen der Tools, die den KI-Server brauchen (Tests, Doku)."""
        return [t.name for t in self.tools if getattr(t, "braucht_ki", False)]

    def finde_tool(self, name):
        """Tool über seinen `name` oder Klassennamen - z.B. damit das Datei-Menü die Einstellungen öffnen kann."""
        for tool in self.tools:
            if tool.name == name or type(tool).__name__ == name:
                return tool
        return None

    def populate_main_menu(self, menubar):
        """
        Baut das 'Tools'-Menü in der Fensterleiste auf — vor dem Hilfe-Menü, falls vorhanden
        (Konvention: Hilfe ganz rechts). Tools mit `menu_group` landen in Untermenüs
        (Reihenfolge: GRUPPEN_REIHENFOLGE, unbekannte Gruppen danach), Tools ohne Gruppe
        darunter auf der obersten Ebene.
        """
        relevant_tools = [t for t in self.tools if "main_menu" in t.menu_hooks]
        if not relevant_tools: return

        tools_menu = tk.Menu(menubar, tearoff=0)
        gruppen = gruppiere_tools(relevant_tools)
        for gruppe, tools in gruppen:
            if not gruppe:
                continue
            untermenu = tk.Menu(tools_menu, tearoff=0)
            for tool in tools:
                untermenu.add_command(label=tool.menu_label, command=lambda t=tool: self.execute_tool(t))
                self._merke_eintrag(tool, untermenu)
            tools_menu.add_cascade(label=gruppe, menu=untermenu)
        ohne_gruppe = next((tools for gruppe, tools in gruppen if not gruppe), [])
        if ohne_gruppe and any(gruppe for gruppe, _ in gruppen):
            tools_menu.add_separator()
        for tool in ohne_gruppe:
            tools_menu.add_command(label=tool.menu_label, command=lambda t=tool: self.execute_tool(t))
            self._merke_eintrag(tool, tools_menu)

        # VOR "Hilfe" einfügen - "Hilfe" ist seit der Aktivitätsanzeige (aktivitaet.py)
        # nicht mehr der letzte Eintrag, daher die Leiste nach dem Label absuchen.
        try:
            last_index = menubar.index("end")
            for i in range((last_index or -1) + 1):
                if menubar.type(i) == "cascade" and menubar.entrycget(i, "label") == "Hilfe":
                    menubar.insert_cascade(i, label="Tools", menu=tools_menu)
                    return
        except tk.TclError:
            pass
        menubar.add_cascade(label="Tools", menu=tools_menu)

    def notify_file_moved(self, old_path, new_path):
        """Informiert alle Tools, dass eine Datei verschoben/umbenannt wurde (z.B. damit ein offener Editor seinen Speicherpfad nachzieht)."""
        for tool in self.tools:
            try:
                tool.on_file_moved(old_path, new_path)
            except Exception as e:
                logging.getLogger("DocManager").warning(f"Fehler im Tool {tool.name} bei Pfad-Update: {e}")

    def notify_selection_change(self):
        """Informiert alle aktiven Tools darüber, dass sich die Dateiauswahl geändert hat."""
        selected_files = []
        if hasattr(self.app, 'tree_files'):
            for item in self.app.tree_files.selection():
                rel_path = self.app.tree_files.item(item, "values")[4]
                abs_path = os.path.join(self.app.master_folder, rel_path)
                selected_files.append(abs_path)
                
        context = ToolContext(
            selected_files=selected_files,
            current_folder=getattr(self.app, 'master_folder', ""),
            logger=getattr(self.app, 'logger', None),
            app_reference=self.app
        )
        
        # Ruft die Update-Funktion bei jedem Tool auf, das gerade aktiv ist
        for tool in self.tools:
            if hasattr(tool, "on_selection_changed"):
                try:
                    tool.on_selection_changed(context)
                except Exception as e:
                    logging.getLogger("DocManager").warning(f"Fehler im Tool {tool.name} beim Live-Update: {e}")