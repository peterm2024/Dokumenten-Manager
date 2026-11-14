"""
Gründe nachtragen (28.10.2026): Seit diesem Stand schreibt die Vollautomatik beim Ablegen in 0_Unsicher
den Grund als KID_GRUND ins PDF - die Eigenschaften-Zeile „Status“ zeigt ihn dann an. Dokumente, die
schon vorher dort lagen, tragen keinen. Ihr Grund steht aber im Vollautomatik-Protokoll; dieses
Werkzeug holt ihn einmalig von dort (ohne KI, nur das subject-Feld wird geschrieben - Titel, Tags und
Datum bleiben unverändert, die orange Markierung „unbearbeitet“ also auch).
"""

import os
import re
import threading
import tkinter.messagebox as mb

import app_paths
import auto_pilot
from pdf_handler import PDFHandler
from tools.base_tool import BaseTool, ToolContext
from ui_utils import ProgressDialog

# Protokollzeile der Vollautomatik (auto_pilot_service._verarbeite):
# "2026-10-28 15:34  unsicher  name.pdf  ->  0_Unsicher\name.pdf  (Grund: ...)"
_UNSICHER_ZEILE = re.compile(r"^\S+ \S+  unsicher  .+?  ->  (.+?)  \(Grund: (.*)\)\s*$")


def gruende_aus_protokoll(text):
    """
    Grund je Ziel aus dem Protokolltext, die jüngste Zeile gewinnt (ein Dokument kann mehrmals
    vorgelegt worden sein). :return: {normcase(relativer Zielpfad): grund}
    """
    gruende = {}
    for zeile in (text or "").splitlines():
        treffer = _UNSICHER_ZEILE.match(zeile)
        if treffer and treffer.group(2).strip():
            gruende[os.path.normcase(os.path.normpath(treffer.group(1).strip()))] = treffer.group(2).strip()
    return gruende


def plane_gruende(dokumente, gruende):
    """
    Reine Planung, testbar ohne PDFs.
    :param dokumente: Liste von (rel_pfad, gespeicherter_grund) der PDFs in 0_Unsicher
    :param gruende: Ergebnis von gruende_aus_protokoll
    :return: sortierte Liste (rel_pfad, grund) der Dokumente ohne gespeicherten Grund, für die das Protokoll einen kennt
    """
    plan = []
    for rel, gespeichert in dokumente:
        grund = gruende.get(os.path.normcase(os.path.normpath(rel)))
        if grund and not (gespeichert or "").strip():
            plan.append((rel, grund))
    return sorted(plan)


def sammle_unsicher(master):
    """(rel_pfad, gespeicherter_grund) aller PDFs direkt in 0_Unsicher."""
    ordner = os.path.join(master, auto_pilot.UNSICHER_ORDNER)
    if not os.path.isdir(ordner):
        return []
    return [(os.path.join(auto_pilot.UNSICHER_ORDNER, name),
             PDFHandler.get_metadata(os.path.join(ordner, name)).get("KID_Grund", ""))
            for name in sorted(os.listdir(ordner)) if name.lower().endswith(".pdf")]


class GruendeNachtragenTool(BaseTool):
    """Menü-Einstieg: trägt den Vollautomatik-Grund aus dem Protokoll in die PDFs in 0_Unsicher nach."""

    @property
    def name(self) -> str:
        return "Gründe nachtragen"

    @property
    def menu_group(self) -> str:
        return "Aufräumen"

    @property
    def menu_label(self) -> str:
        return "Gründe in 0_Unsicher nachtragen (aus dem Protokoll)…"

    @property
    def absicht(self) -> str:
        return ("Die Zeile „Status“ in den Eigenschaften zeigt, warum die Vollautomatik ein Dokument zur Prüfung "
                "vorgelegt hat. Neue Ablagen merken sich das selbst; dieses Werkzeug holt es für Dokumente nach, "
                "die schon vorher in 0_Unsicher lagen.")

    @property
    def description(self) -> str:
        return ("Liest das Vollautomatik-Protokoll und schreibt bei Dokumenten in 0_Unsicher ohne gespeicherten "
                "Grund den protokollierten Grund ins PDF. Titel, Tags und Datum bleiben unverändert.")

    @property
    def menu_hooks(self) -> list:
        return ["main_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        app = context.app
        master = app.master_folder
        titel = "Gründe nachtragen"
        try:
            with open(app_paths.protokoll_path(master), encoding="utf-8") as f:
                gruende = gruende_aus_protokoll(f.read())
        except OSError:
            gruende = {}
        plan = plane_gruende(sammle_unsicher(master), gruende)
        if not plan:
            mb.showinfo(titel, "In 0_Unsicher gibt es kein Dokument ohne gespeicherten Grund, zu dem das "
                               "Vollautomatik-Protokoll einen Grund kennt.", parent=app.root)
            return True
        # Bewusst immer fragen (nicht über bestaetigung.frage abschaltbar): schreibt in viele PDFs
        if not mb.askyesno(titel, f"{len(plan)} Dokument(e) in 0_Unsicher ohne gespeicherten Grund - das "
                                  "Protokoll kennt ihn.\n\nDer Grund wird in die PDF-Datei geschrieben (Titel, Tags "
                                  "und Datum bleiben unverändert).\n\nFortfahren?", parent=app.root):
            return True

        dienst = getattr(app, "auto_pilot_service", None)
        if dienst is not None:
            dienst.pausieren()
        app.is_saving = True
        dialog = ProgressDialog(app.root, titel, "Gründe werden eingetragen...")
        stand = {"geschrieben": 0, "fehler": []}

        def worker():
            for i, (rel, grund) in enumerate(plan):
                if dialog.should_stop():
                    break
                if PDFHandler.write_custom_metadata(os.path.join(master, rel), {"KID_Grund": grund}, still=True):
                    stand["geschrieben"] += 1
                else:
                    stand["fehler"].append(rel)
                app.root.after(0, dialog.update_progress, i + 1, len(plan))
            app.root.after(0, fertig)

        def fertig():
            app.is_saving = False
            if dienst is not None:
                dienst.fortsetzen()
            if dialog.winfo_exists():
                dialog.destroy()
            if getattr(app, "logger", None):
                app.logger.info(f"Gründe nachtragen: {stand['geschrieben']} geschrieben, "
                                f"{len(stand['fehler'])} Fehler")
            text = f"{stand['geschrieben']} von {len(plan)} Dokument(en) zeigen jetzt ihren Grund unter Details → Status."
            if stand["fehler"]:
                text += (f"\n\n{len(stand['fehler'])} Datei(en) ließen sich nicht beschreiben, z.B.:\n"
                         + "\n".join(stand["fehler"][:5]))
            (mb.showwarning if stand["fehler"] else mb.showinfo)(titel, text, parent=app.root)

        threading.Thread(target=worker, daemon=True).start()
        return True
