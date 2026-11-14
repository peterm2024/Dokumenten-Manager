"""
Dokument-IDs vergeben (Peter 25.10.2026): Jedes Dokument soll eine kurze, eindeutige ID haben,
um es in Notizen und Rückmeldungen zu nennen (Format und Erzeugung: PDFHandler.neue_kid_id).
Neue Dokumente bekommen sie beim ersten Speichern; dieses Werkzeug holt den Bestand nach.

Zweite Aufgabe: doppelte IDs. Wer eine PDF im Explorer kopiert, kopiert ihre ID mit. Von
mehreren Dateien mit derselben ID behält die mit dem ältesten Erstellungszeitpunkt ihre ID
(Windows gibt einer Kopie einen neuen Erstellungszeitpunkt), die übrigen bekommen eine neue.

Titel, Tags und Datum bleiben unverändert; geschrieben wird nur das subject-Feld (KID_ID).
"""

import os
import tkinter.messagebox as mb

import app_paths
from pdf_handler import PDFHandler
from tools.base_tool import BaseTool, ToolContext
from ui_utils import ProgressDialog


def plane_id_vergabe(dokumente, erstellt):
    """
    Reine Planung, testbar ohne PDFs.
    :param dokumente: Liste von (rel_pfad, kid_id) - kid_id "" ohne ID
    :param erstellt: {rel_pfad: Erstellungszeitpunkt} - ältester behält eine doppelte ID
    :return: (ohne_id, zu_ersetzen) - zwei sortierte Listen relativer Pfade
    """
    ohne_id = sorted(rel for rel, kid in dokumente if not (kid or "").strip())
    gruppen = {}
    for rel, kid in dokumente:
        kid = (kid or "").strip()
        if kid:
            gruppen.setdefault(kid.upper(), []).append(rel)
    zu_ersetzen = []
    for pfade in gruppen.values():
        if len(pfade) > 1:
            pfade = sorted(pfade, key=lambda r: (erstellt.get(r, float("inf")), r))
            zu_ersetzen.extend(pfade[1:])
    return ohne_id, sorted(zu_ersetzen)


def sammle_dokumente(app):
    """(rel_pfad, kid_id) aller PDFs der Sammlung ohne Papierkorb - bevorzugt aus dem Suchindex."""
    master = app.master_folder
    try:
        doks = app.index_manager.iter_documents()
    except Exception:
        doks = app.search_manager._iter_documents_live(master)
    return [(d["rel_path"], d.get("kid_id") or "") for d in doks
            if not app_paths.is_trash_path(os.path.join(master, d["rel_path"]), master)]


def _erstellt(master, rel_pfade):
    zeiten = {}
    for rel in rel_pfade:
        try:
            zeiten[rel] = os.stat(os.path.join(master, rel)).st_ctime
        except OSError:
            pass
    return zeiten


class DokumentIdsTool(BaseTool):
    """Menü-Einstieg: vergibt fehlende und doppelte Dokument-IDs im ganzen Bestand."""

    @property
    def name(self) -> str:
        return "Dokument-IDs vergeben"

    @property
    def menu_group(self) -> str:
        return "Aufräumen"

    @property
    def menu_label(self) -> str:
        return "Dokument-IDs vergeben…"

    @property
    def absicht(self) -> str:
        return ("Jedes Dokument eindeutig benennen können, etwa in Notizen oder Rückmeldungen. Neue Dokumente "
                "bekommen die ID beim ersten Speichern; dieses Werkzeug holt den Bestand nach und trennt Kopien, "
                "die die ID ihres Originals mitgebracht haben.")

    @property
    def description(self) -> str:
        return ("Gibt allen Dokumenten ohne Dokument-ID eine (z.B. K7M4-Q2XP) und Kopien mit doppelter ID eine "
                "neue. Titel, Tags und Datum bleiben unverändert.")

    @property
    def menu_hooks(self) -> list:
        return ["main_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        app = context.app
        master = app.master_folder
        dokumente = sammle_dokumente(app)
        ohne_id, zu_ersetzen = plane_id_vergabe(dokumente, _erstellt(master, [r for r, k in dokumente if k]))
        titel = "Dokument-IDs vergeben"
        if not ohne_id and not zu_ersetzen:
            mb.showinfo(titel, f"Alle {len(dokumente)} Dokumente haben bereits eine eindeutige Dokument-ID.",
                        parent=app.root)
            return True
        teile = []
        if ohne_id:
            teile.append(f"{len(ohne_id)} Dokument(e) ohne Dokument-ID bekommen eine")
        if zu_ersetzen:
            teile.append(f"{len(zu_ersetzen)} Kopie(n) mit doppelter ID bekommen eine neue "
                         "(die älteste Datei behält ihre ID)")
        # Bewusst immer fragen (nicht über bestaetigung.frage abschaltbar): schreibt in viele PDFs
        if not mb.askyesno(titel, f"{len(dokumente)} Dokumente in der Sammlung.\n\n" + ";\n".join(teile) + ".\n\n"
                           "Dabei wird in jede dieser PDF-Dateien geschrieben (Titel, Tags und Datum bleiben "
                           "unverändert). Fortfahren?", parent=app.root):
            return True

        auftraege = [(rel, PDFHandler.ensure_kid_id) for rel in ohne_id] + \
                    [(rel, PDFHandler.ersetze_kid_id) for rel in zu_ersetzen]
        dialog = ProgressDialog(app.root, titel, "Dokument-IDs werden vergeben...")
        app.is_saving = True
        erledigt, fehler = 0, []
        try:
            for i, (rel, schreibe) in enumerate(auftraege):
                if dialog.should_stop():
                    break
                if schreibe(os.path.join(master, rel)):
                    erledigt += 1
                else:
                    fehler.append(rel)
                if dialog.winfo_exists():
                    dialog.update_progress(i + 1, len(auftraege))
                app.root.update()
        finally:
            app.is_saving = False
            if dialog.winfo_exists():
                dialog.destroy()

        if hasattr(app, "folder_manager"):
            app.folder_manager.on_folder_select(None)
        text = f"{erledigt} von {len(auftraege)} Dokument(en) haben eine Dokument-ID bekommen."
        if fehler:
            text += (f"\n\n{len(fehler)} Datei(en) ließen sich nicht beschreiben (gesperrt oder schreibgeschützt), "
                     "z.B.:\n" + "\n".join(fehler[:5]))
        (mb.showwarning if fehler else mb.showinfo)(titel, text, parent=app.root)
        return True
