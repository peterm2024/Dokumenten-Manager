"""
Absender nachlesen (Ablage-Gedächtnis, KONZEPT_ABLAGE_GEDAECHTNIS.md E2, 27.10.2026): Das Gedächtnis
zählt nur Dokumente, die ihren gelesenen Absender als KID_ABSENDER im PDF tragen - neue Ablagen
schreiben ihn mit, der Bestand hat ihn nicht. Ohne diesen einmaligen Lauf begänne das Gedächtnis
leer und hülfe erst nach Monaten.

Die KI liest die erste Seite jedes abgelegten Dokuments ohne KID_ABSENDER mit DEMSELBEN Aufruf wie
die Vollautomatik (ollama_client.suggest_filing + auto_pilot.trenne_adresszeile) - nur so passt der
gespeicherte Absender später zu dem, was die Vollautomatik bei einem neuen Brief liest.
Geschrieben wird nur das subject-Feld; Titel, Tags und Datum bleiben unverändert. Dokumente im
Posteingang, in 0_Unsicher und im Papierkorb werden übersprungen (sie sind keine Stimme).
"""

import os
import threading
import tkinter.messagebox as mb

import app_paths
import auto_pilot
import ollama_client
from pdf_handler import PDFHandler
from tools.base_tool import BaseTool, ToolContext
from ui_utils import ProgressDialog

# Gemessene Lesezeit je Dokument mit qwen3.5:9b auf der 5060 Ti (Prüfstand 27.10.2026) - nur für die Vorab-Frage
SEKUNDEN_JE_DOKUMENT = 5
# So viele KI-Fehler hintereinander brechen den Lauf ab (Server weg) statt jedes Dokument einzeln scheitern zu lassen
MAX_FEHLER_IN_FOLGE = 3


def plane_nachlesen(dokumente, ablageziele):
    """
    Reine Planung, testbar ohne PDFs.
    :param dokumente: Liste von (rel_pfad, absender) - absender "" ohne KID_ABSENDER
    :param ablageziele: Ordner, deren Dokumente fürs Gedächtnis zählen (auto_pilot.ordner_fuer_zweitmeinung)
    :return: sortierte relative Pfade der Dokumente, deren Absender noch fehlt
    """
    ziele = {os.path.normcase(z) for z in ablageziele}
    return sorted(rel for rel, absender in dokumente
                  if not (absender or "").strip() and os.path.normcase(os.path.dirname(rel)) in ziele)


def absender_aus_antwort(ki_antwort):
    """Der Absender, wie ihn auch baue_entscheidung verwendet (Rücksendezeile auf den Namen gekürzt)."""
    absender, _ = auto_pilot.trenne_adresszeile((ki_antwort or {}).get("absender"))
    return absender


def sammle_dokumente(app):
    """(rel_pfad, absender) aller PDFs der Sammlung ohne Papierkorb - bevorzugt aus dem Suchindex."""
    master = app.master_folder
    try:
        doks = app.index_manager.iter_documents()
    except Exception:
        doks = app.search_manager._iter_documents_live(master)
    return [(d["rel_path"], d.get("absender") or "") for d in doks
            if not app_paths.is_trash_path(os.path.join(master, d["rel_path"]), master)]


def _dauer_text(sekunden):
    minuten = round(sekunden / 60)
    if minuten < 2:
        return "etwa eine Minute"
    if minuten < 90:
        return f"etwa {minuten} Minuten"
    return f"etwa {minuten / 60:.1f} Stunden".replace(".", ",")


class AbsenderNachlesenTool(BaseTool):
    """Menü-Einstieg: lässt die KI den Absender aller abgelegten Dokumente einmal nachlesen."""

    @property
    def name(self) -> str:
        return "Absender nachlesen"

    @property
    def menu_group(self) -> str:
        return "Aufräumen"

    @property
    def menu_label(self) -> str:
        return "Absender nachlesen (Ablage-Gedächtnis)…"

    @property
    def absicht(self) -> str:
        return ("Die Vollautomatik lernt aus dem Bestand, in welchem Ordner die Dokumente eines Absenders liegen. "
                "Dafür muss sie wissen, von wem jedes abgelegte Dokument stammt; neue Ablagen merken sich das "
                "selbst, dieses Werkzeug holt es für den Bestand einmalig nach.")

    @property
    def description(self) -> str:
        return ("Lässt die KI bei allen abgelegten Dokumenten ohne gespeicherten Absender die erste Seite lesen und "
                "schreibt den Absender ins PDF. Titel, Tags und Datum bleiben unverändert.")

    @property
    def braucht_ki(self) -> bool:
        return True

    @property
    def menu_hooks(self) -> list:
        return ["main_menu"]

    @property
    def required_input(self) -> str:
        return "none"

    def execute(self, context: ToolContext) -> bool:
        app = context.app
        master = app.master_folder
        titel = "Absender nachlesen"
        ziele = auto_pilot.ordner_fuer_zweitmeinung(auto_pilot.sammle_ordnerliste(master))
        dokumente = sammle_dokumente(app)
        offen = plane_nachlesen(dokumente, ziele)
        if not offen:
            mb.showinfo(titel, "Alle abgelegten Dokumente haben bereits einen gespeicherten Absender.", parent=app.root)
            return True
        # Bewusst immer fragen (nicht über bestaetigung.frage abschaltbar): schreibt in viele PDFs
        if not mb.askyesno(titel, f"{len(offen)} abgelegte(s) Dokument(e) ohne gespeicherten Absender.\n\n"
                           "Die KI liest bei jedem die erste Seite, das dauert "
                           f"{_dauer_text(len(offen) * SEKUNDEN_JE_DOKUMENT)}. Der Absender wird in die PDF-Datei "
                           "geschrieben (Titel, Tags und Datum bleiben unverändert); die Vollautomatik "
                           "pausiert solange.\n\nFortfahren?", parent=app.root):
            return True

        base_url = app.config.get("ollama_url", ollama_client.DEFAULT_URL)
        model = app.config.get("ollama_model", ollama_client.DEFAULT_MODEL)
        known_tags = app.tag_manager.get_known_tags() if hasattr(app, "tag_manager") else []
        kategorien = app.tag_manager.get_kategorien() if hasattr(app, "tag_manager") else []
        dienst = getattr(app, "auto_pilot_service", None)
        if dienst is not None:
            dienst.pausieren()
        app.is_saving = True
        dialog = ProgressDialog(app.root, titel, "Absender werden gelesen...")
        stand = {"geschrieben": 0, "ohne": [], "fehler": [], "abbruch": ""}

        def worker():
            fehler_in_folge = 0
            for i, rel in enumerate(offen):
                if dialog.should_stop():
                    break
                pfad = os.path.join(master, rel)
                try:
                    png = PDFHandler.render_page_png(pfad)
                    if png is None:
                        stand["fehler"].append(rel)
                    else:
                        absender = absender_aus_antwort(ollama_client.suggest_filing(
                            png, known_tags=known_tags, base_url=base_url, model=model, kategorien=kategorien))
                        if not absender:
                            stand["ohne"].append(rel)
                        elif PDFHandler.write_custom_metadata(pfad, {"KID_Absender": absender}, still=True):
                            stand["geschrieben"] += 1
                        else:
                            stand["fehler"].append(rel)
                    fehler_in_folge = 0
                except Exception as e:
                    stand["fehler"].append(rel)
                    fehler_in_folge += 1
                    if fehler_in_folge >= MAX_FEHLER_IN_FOLGE:
                        stand["abbruch"] = str(e)
                        break
                app.root.after(0, dialog.update_progress, i + 1, len(offen))
            app.root.after(0, fertig)

        def fertig():
            app.is_saving = False
            if dienst is not None:
                dienst.fortsetzen()
            if dialog.winfo_exists():
                dialog.destroy()
            if getattr(app, "logger", None):
                app.logger.info(f"Absender nachlesen: {stand['geschrieben']} geschrieben, {len(stand['ohne'])} ohne "
                                f"erkennbaren Absender, {len(stand['fehler'])} Fehler {stand['abbruch']}".rstrip())
            text = f"{stand['geschrieben']} von {len(offen)} Dokument(en) haben jetzt einen gespeicherten Absender."
            if stand["ohne"]:
                text += f"\n\nBei {len(stand['ohne'])} Dokument(en) hat die KI keinen Absender erkannt."
            if stand["abbruch"]:
                text += f"\n\nAbgebrochen, der KI-Server antwortet nicht:\n{stand['abbruch']}"
            if stand["fehler"]:
                text += (f"\n\n{len(stand['fehler'])} Datei(en) ließen sich nicht lesen oder beschreiben, z.B.:\n"
                         + "\n".join(stand["fehler"][:5]))
            (mb.showwarning if stand["fehler"] else mb.showinfo)(titel, text, parent=app.root)

        threading.Thread(target=worker, daemon=True).start()
        return True
