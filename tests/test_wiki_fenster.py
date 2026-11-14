"""Fenster „Wiki…“ (Wiki von Hand, neuer Aufbau, Schritt N2): anlegen, Schubladen auf Zuruf, Angaben, Verbindungen,
Belege, ungespeicherte Änderungen, Löschen, Rechtsklick in der Dokumentenliste. Nur Musterdaten, Tk ohne sichtbares
Hauptfenster."""
import os
import shutil
import tempfile
import tkinter as tk
import types
import unittest
from tkinter import ttk
from unittest.mock import MagicMock, patch

import wissen
from pdf_handler import PDFHandler
from tests.test_begleitet_erfassen import Einstellungen, threads_beenden
from tests.test_mail_import import pdf_bytes
from tools import wiki as wf


class TestWikiFenster(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(threads_beenden)
        self.addCleanup(self.root.destroy)
        self.basis = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.basis, True)
        self.sammlung = os.path.join(self.basis, "Sammlung")
        os.makedirs(os.path.join(self.sammlung, "Fahrzeuge"))
        self.pdfs = []
        for name in ("Zulassung.pdf", "Kaufvertrag.pdf"):
            pfad = os.path.join(self.sammlung, "Fahrzeuge", name)
            with open(pfad, "wb") as d:
                d.write(pdf_bytes())
            self.pdfs.append(pfad)
        self.tree_files = ttk.Treeview(self.root, columns=("a", "b", "c", "d", "rel"))
        for pfad in self.pdfs:
            self.tree_files.insert("", tk.END, values=("", "", "", "", os.path.relpath(pfad, self.sammlung)))
        self.folder_manager = types.SimpleNamespace(zeige_dokument=MagicMock(return_value=True))
        self.index = types.SimpleNamespace(pfad_zur_kid_id=self.pfad_zur_kid_id)
        self.app = types.SimpleNamespace(root=self.root, master_folder=self.sammlung, config=Einstellungen(), logger=None,
                                         tree_files=self.tree_files, folder_manager=self.folder_manager,
                                         index_manager=self.index)
        p = patch("tools.wiki.UIUtils.werkzeugfenster")                 # sonst unsichtbar (FALLSTRICKE #95)
        p.start()
        self.addCleanup(p.stop)
        self.w = wissen.Wissen(self.sammlung)

    def pfad_zur_kid_id(self, kid_id):
        for pfad in self.pdfs:
            if PDFHandler.get_metadata(pfad).get("KID_ID") == kid_id:
                return os.path.relpath(pfad, self.sammlung)
        return None

    def fenster(self):
        f = wf.WikiFenster(self.app)
        self.addCleanup(lambda: f.winfo_exists() and f.destroy())
        self.root.update()
        return f

    def anlegen(self, f, bezeichnung, art, notiz=""):
        f._neu()
        f.var_bezeichnung.set(bezeichnung)
        f.var_art.set(art)
        f.txt_notiz.insert("1.0", notiz)
        self.assertTrue(f._speichern())
        self.root.update()
        return f.eintrag["id"]

    def test_leer_dann_anlegen_mit_neuer_schublade(self):
        f = self.fenster()
        self.assertEqual((str(f.btn_speichern.cget("state")), f.tree.get_children()), ("disabled", ()))
        self.assertFalse(os.path.exists(self.w.pfad))                              # Öffnen legt nichts an
        f._neu()
        self.assertEqual(list(f.cmb_art.cget("values")), list(wissen.START_ARTEN))
        self.assertEqual(str(f.btn_angabe.cget("state")), "disabled")              # erst nach dem Speichern
        with patch("tools.wiki.mb.showwarning") as warnung:                         # ohne Bezeichnung
            self.assertFalse(f._speichern())
        self.assertIn("Bezeichnung", warnung.call_args[0][1])
        max_ = self.anlegen(f, "Max Mustermann", "person", "Familie")              # Schreibweise der Schublade egal
        self.assertEqual((f.eintrag["art_name"], f.tree.item(f.tree.parent(f"e:{max_}"), "text")),
                         ("Person", "Person (1)"))
        self.assertEqual((f.txt_notiz.get("1.0", "end").strip(), str(f.btn_angabe.cget("state"))), ("Familie", "normal"))
        # neue Schublade auf Zuruf: erst nach Rückfrage
        f._neu()
        self.assertEqual(f.var_art.get(), "Person")                                # die zuletzt gezeigte ist vorgewählt
        f.var_bezeichnung.set("Geschirrspüler")
        f.var_art.set("  Gerät ")
        with patch("tools.wiki.mb.askyesno", return_value=False) as frage:
            self.assertFalse(f._speichern())
        self.assertIn("„Gerät“", frage.call_args[0][1])
        self.assertNotIn("Gerät", [a["name"] for a in self.w.arten()])
        with patch("tools.wiki.mb.askyesno", return_value=True):
            self.assertTrue(f._speichern())
        self.root.update()
        self.assertEqual([(e["art_name"], e["bezeichnung"]) for e in self.w.liste()],
                         [("Person", "Max Mustermann"), ("Gerät", "Geschirrspüler")])
        self.assertEqual([f.tree.item(g, "text") for g in f.tree.get_children()], ["Person (1)", "Gerät (1)"])
        # Schublade wechseln
        f.var_art.set("Sonstiges")
        self.assertTrue(f._speichern())
        self.assertEqual(self.w.lade(f.eintrag["id"])["art_name"], "Sonstiges")

    def test_angaben(self):
        f = self.fenster()
        haus = self.anlegen(f, "Haus Musterstraße 1", "Immobilie")
        with patch("tools.wiki.simpledialog.askstring", return_value="  Baujahr   1975 "):
            f._angabe_hinzu()
        with patch("tools.wiki.simpledialog.askstring", return_value="baujahr 1975"), \
                patch("tools.wiki.mb.showinfo") as info:
            f._angabe_hinzu()                                                      # steht schon da
        self.assertIn("steht schon da", info.call_args[0][1])
        with patch("tools.wiki.simpledialog.askstring", return_value=None):
            f._angabe_hinzu()                                                      # abgebrochen
        self.w.angabe_hinzu(haus, "Feuerlöscher geprüft am 19.02.2016", "AAAA-0001", "Rechnung Prüfdienst",
                            "Prüf-/Lieferdatum: 19.02.2016")
        f.var_bezeichnung.set("Haus Musterstraße 1a")                              # ungespeichert: bleibt stehen
        f._neu_laden()
        self.assertEqual(f.var_bezeichnung.get(), "Haus Musterstraße 1a")
        zeilen = [f.tree_angaben.item(i, "values") for i in f.tree_angaben.get_children()]
        self.assertEqual(zeilen, [("Baujahr 1975", ""), ("Feuerlöscher geprüft am 19.02.2016", "Rechnung Prüfdienst")])
        hand, ki = f.tree_angaben.get_children()
        f.tree_angaben.selection_set(ki)
        self.root.update()
        self.assertEqual(f.lbl_zitat.cget("text"), "Im Dokument: „Prüf-/Lieferdatum: 19.02.2016“")
        f.tree_angaben.selection_set(hand)
        self.root.update()
        self.assertEqual(f.lbl_zitat.cget("text"), "Von Hand eingetragen")
        with patch("tools.wiki.simpledialog.askstring", return_value="Baujahr 1976") as frage:
            f._angabe_aendern()
        self.assertEqual(frage.call_args[1]["initialvalue"], "Baujahr 1975")
        self.assertEqual(self.w.lade(haus)["angaben"][0]["text"], "Baujahr 1976")
        f.tree_angaben.selection_set(f.tree_angaben.get_children())
        f._angabe_weg()
        self.assertEqual((self.w.lade(haus)["angaben"], f.tree_angaben.get_children()), ([], ()))
        self.assertEqual(f.var_bezeichnung.get(), "Haus Musterstraße 1a")          # immer noch ungespeichert da

    def test_verbindungen(self):
        haus = self.w.speichere("Immobilie", "Haus Musterstraße 1", "Altbau")
        firma = self.w.speichere("Firma", "Muster Prüfdienst")
        max_ = self.w.speichere("Person", "Max Mustermann")
        f = self.fenster()
        f.tree.selection_set(f"e:{haus}")
        self.root.update()
        self.assertEqual(f.txt_notiz.get("1.0", "end").strip(), "Altbau")          # aus dem leeren, gesperrten Formular
        self.assertEqual(list(f.cmb_ziel.cget("values")), ["Max Mustermann (Person)", "Muster Prüfdienst (Firma)"])
        f.var_ziel.set("Muster Prüfdienst (Firma)")
        f._verbinden()
        self.assertEqual([f.tree_verbunden.item(i, "text") for i in f.tree_verbunden.get_children()],
                         ["Muster Prüfdienst (Firma)"])
        self.assertEqual(list(f.cmb_ziel.cget("values")), ["Max Mustermann (Person)"])   # schon Verbundene fehlen
        f.tree_verbunden.selection_set(f"v:{firma}")
        f._verbundenen_zeigen()                                                    # Doppelklick springt dorthin
        self.root.update()
        self.assertEqual((f.eintrag["id"], [v["id"] for v in f.eintrag["verbunden"]]), (firma, [haus]))
        f.tree_verbunden.selection_set(f"v:{haus}")
        f._trennen()
        self.assertEqual((self.w.lade(haus)["verbunden"], f.tree_verbunden.get_children()), ([], ()))
        self.assertEqual(self.w.anzahl(), 3)
        self.assertIsNotNone(self.w.lade(max_))

    def test_belege_aus_dem_hauptfenster_und_anzeigen(self):
        f = self.fenster()
        golf = self.anlegen(f, "VW Golf", "Fahrzeug")
        with patch("tools.wiki.mb.showinfo") as info:
            f._beleg_hinzu()                                                  # nichts markiert
        self.assertIn("markieren", info.call_args[0][1])
        self.tree_files.selection_set(self.tree_files.get_children())
        f.txt_notiz.insert("1.0", "Zweitwagen")                               # ungespeicherte Eingabe bleibt stehen
        f._beleg_hinzu()
        self.assertEqual([f.tree_belege.item(i, "text") for i in f.tree_belege.get_children()],
                         ["Kaufvertrag", "Zulassung"])
        self.assertEqual(f.txt_notiz.get("1.0", "end").strip(), "Zweitwagen")
        self.assertTrue(all(PDFHandler.get_metadata(p).get("KID_ID") for p in self.pdfs))   # Dokument-ID vergeben
        f.tree_belege.selection_set(f.tree_belege.get_children()[0])
        f._beleg_zeigen()
        self.assertEqual(self.folder_manager.zeige_dokument.call_args[0][0], self.pdfs[1])
        # Beleg entfernen: die Angabe aus dem Dokument bleibt, ohne Zitat
        kid = PDFHandler.get_metadata(self.pdfs[1]).get("KID_ID")
        self.w.angabe_hinzu(golf, "Gekauft 2019", kid, "Kaufvertrag", "Kaufvertrag vom 03.03.2019")
        f._neu_laden()
        f.tree_belege.selection_set(f.tree_belege.get_children()[0])
        f._beleg_weg()
        self.assertEqual([f.tree_belege.item(i, "text") for i in f.tree_belege.get_children()], ["Zulassung"])
        self.assertEqual(f.tree_angaben.item(f.tree_angaben.get_children()[0], "values"), ("Gekauft 2019", ""))

    def test_ungespeichert_fragt_und_abbrechen_bleibt(self):
        a = self.w.speichere("Person", "Max Mustermann")
        b = self.w.speichere("Person", "Erika Musterfrau")
        f = self.fenster()
        f.tree.selection_set(f"e:{a}")
        self.root.update()
        f.var_bezeichnung.set("Max M.")
        with patch("tools.wiki.mb.askyesnocancel", return_value=None) as frage:    # abbrechen: bleibt
            f.tree.selection_set(f"e:{b}")
            self.root.update()
        frage.assert_called_once()
        self.assertEqual((f.eintrag["id"], f.var_bezeichnung.get(), f.tree.selection()), (a, "Max M.", (f"e:{a}",)))
        with patch("tools.wiki.mb.askyesnocancel", return_value=None):
            f._schliessen()
        self.assertTrue(f.winfo_exists())
        with patch("tools.wiki.mb.askyesnocancel", return_value=True):             # speichern, dann wechseln
            f.tree.selection_set(f"e:{b}")
            self.root.update()
        self.assertEqual((f.eintrag["id"], self.w.lade(a)["bezeichnung"]), (b, "Max M."))
        f.txt_notiz.insert("1.0", "weg damit")
        with patch("tools.wiki.mb.askyesnocancel", return_value=False):            # verwerfen
            f._schliessen()
        self.assertFalse(f.winfo_exists())
        self.assertEqual(self.w.lade(b)["notiz"], "")

    def test_doppelt_und_loeschen(self):
        f = self.fenster()
        a = self.anlegen(f, "Max Mustermann", "Person")
        f._neu()
        f.var_bezeichnung.set("max  mustermann")
        with patch("tools.wiki.mb.askyesno", return_value=False) as frage:
            self.assertFalse(f._speichern())
        self.assertIn("schon einen Eintrag", frage.call_args[0][1])
        f.var_bezeichnung.set("Erika Musterfrau")
        self.assertTrue(f._speichern())
        self.root.update()
        b = f.eintrag["id"]
        self.w.verbinde(a, b)
        f._neu_laden()
        with patch("tools.wiki.mb.askyesno", return_value=False) as frage:
            f._loeschen()
        self.assertIn("mit 1 anderen Einträgen verbunden", frage.call_args[0][1])
        self.assertEqual(self.w.anzahl(), 2)
        with patch("tools.wiki.mb.askyesno", return_value=True):
            f._loeschen()
        self.assertEqual(([e["id"] for e in self.w.liste()], f.eintrag, str(f.btn_speichern.cget("state"))),
                         ([a], None, "disabled"))
        self.assertEqual(f.tree.item(f.tree.get_children()[0], "text"), "Person (1)")

    def test_suchen_anhaken_und_als_belege_uebernehmen(self):
        golf = self.w.speichere("Fahrzeug", "VW Golf")
        self.w.beleg_hinzu(golf, PDFHandler.ensure_kid_id(self.pdfs[0]), "Zulassung")
        f = self.fenster()
        f.tree.selection_set(f"e:{golf}")
        self.root.update()
        rels = [os.path.relpath(p, self.sammlung) for p in self.pdfs]
        treffer = [{"rel_path": r, "titel": os.path.splitext(os.path.basename(r))[0], "datum": "2019-03-12",
                    "ordner": "Fahrzeuge"} for r in rels]
        with patch("tools.wiki_suche.suche", return_value=treffer):
            f._suche_oeffnen()
            s = f.suche
            self.root.update()
            s._suche()
            self.assertFalse(hasattr(s, "btn_ki"))                                 # die KI kommt mit N3 zurück
            self.assertEqual(s._schon_belegt(), {rels[0]})
            s._schalte(rels[1], True)
            s._uebernehmen()
            self.root.update()
        self.assertEqual([b["titel"] for b in self.w.lade(golf)["belege"]], ["Kaufvertrag", "Zulassung"])
        self.assertEqual(len(f.tree_belege.get_children()), 2)
        anderer = self.w.speichere("Person", "Max Mustermann")
        f.zeige_eintrag(anderer)                                                   # anderer Eintrag: Suchfenster zu
        self.root.update()
        self.assertIsNone(f.suche)

    def test_rechtsklick_in_der_dokumentenliste(self):
        golf = self.w.speichere("Fahrzeug", "VW Golf")
        max_ = self.w.speichere("Person", "Max Mustermann")
        self.w.beleg_hinzu(golf, PDFHandler.ensure_kid_id(self.pdfs[0]), "Zulassung")
        werkzeug = wf.WikiTool()
        self.assertIn("context_menu", werkzeug.menu_hooks)
        menu = tk.Menu(self.root, tearoff=0)
        werkzeug.fuelle_kontextmenue(menu, types.SimpleNamespace(app=self.app, selected_files=[self.pdfs[0]]))
        self.assertEqual([menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) != "separator"],
                         ["Beleg in:", "Fahrzeug: VW Golf", "Von der KI lesen lassen…",
                          "Neuer Eintrag aus dem Dokument (von Hand)…", "Zu Eintrag hinzufügen"])
        vor_mtime = os.path.getmtime(self.pdfs[0])

        f = self.fenster()
        with patch("tools.wiki.UIUtils.einzelfenster", return_value=f):
            wf.WikiTool.aus_dem_menue(self.app, ("zeige", golf), [self.pdfs[0]])
            self.assertEqual(f.eintrag["id"], golf)
            wf.WikiTool.aus_dem_menue(self.app, ("hinzu", max_), [self.pdfs[1]])
            self.assertEqual((f.eintrag["id"], [b["titel"] for b in f.eintrag["belege"]]), (max_, ["Kaufvertrag"]))
            # neuer Eintrag aus zwei Dokumenten: erst „Speichern“ legt an und macht sie zu Belegen
            wf.WikiTool.aus_dem_menue(self.app, ("neu", None), self.pdfs)
            self.assertIn("2 Dokumente Belege", f.lbl_stand.cget("text"))
            self.assertEqual(self.w.anzahl(), 2)
            f.var_bezeichnung.set("Kfz-Versicherung")
            f.var_art.set("Versicherung")
            self.assertTrue(f._speichern())
            self.root.update()
            neu = f.eintrag["id"]
            self.assertEqual(sorted(b["titel"] for b in self.w.lade(neu)["belege"]), ["Kaufvertrag", "Zulassung"])
            self.assertEqual(len(f.tree_belege.get_children()), 2)
            self.assertIsNone(f._mitbringen)
            # nur die Dokument-ID kam dazu (die erste hatte schon eine): sonst bleibt die Datei, wie sie war
            self.assertEqual(os.path.getmtime(self.pdfs[0]), vor_mtime)
            # wer nach „Neuer Eintrag aus …“ einen anderen Eintrag wählt, nimmt nichts mit
            wf.WikiTool.aus_dem_menue(self.app, ("neu", None), [self.pdfs[0]])
            f.var_bezeichnung.set("Erika Musterfrau")
            with patch("tools.wiki.mb.askyesnocancel", return_value=False):        # verwerfen
                f.zeige_eintrag(max_)
            self.assertIsNone(f._mitbringen)
            f.var_bezeichnung.set("Max M.")
            self.assertTrue(f._speichern())
        self.assertEqual([b["titel"] for b in self.w.lade(max_)["belege"]], ["Kaufvertrag"])   # nichts dazugekommen
        self.assertEqual(self.w.anzahl(), 3)

    def test_schubladen_umbenennen_zusammenlegen_loeschen(self):
        # Schritt N4: kein Eintrag geht verloren, das Wiki-Fenster zeigt danach den neuen Stand
        f = self.fenster()
        s = f._schubladen()
        self.addCleanup(lambda: s.winfo_exists() and s.destroy())
        self.assertFalse(os.path.exists(self.w.pfad))                              # nur ansehen legt nichts an
        zeilen = lambda: [s.tree.item(i, "values") for i in s.tree.get_children()]   # noqa: E731
        self.assertEqual(zeilen()[0], ("Person", "0"))
        art = lambda name: next(a for a in s.arten if a["name"] == name)           # noqa: E731
        s.umbenennen(art("Fahrzeug"), "Autos")                                     # ohne Datei: sie entsteht jetzt
        self.assertIn("Autos", f.cmb_art.cget("values"))
        golf = self.w.speichere("Autos", "VW Golf")
        rad = self.w.speichere("Sonstiges", "Fahrrad")
        s._fuelle()
        f.schubladen_geaendert()
        f.zeige_eintrag(rad)
        with patch("tools.wiki_schubladen.mb.showwarning") as warnung:
            s.umbenennen(art("Sonstiges"), "autos")                                # gibt es schon
            s.loeschen(art("Autos"))                                               # nicht leer
            s.neu(" person ")                                                      # gibt es schon
        self.assertEqual(warnung.call_count, 3)
        self.assertEqual(self.w.anzahl(), 2)
        with patch("tools.wiki_schubladen.mb.askyesno", return_value=False) as frage:
            s.zusammenlegen(art("Sonstiges"), art("Autos"))
        self.assertIn("enthält einen Eintrag, er kommt nach „Autos“", frage.call_args[0][1])
        self.assertEqual(self.w.lade(rad)["art_name"], "Sonstiges")                # Nein: nichts geschieht
        with patch("tools.wiki_schubladen.mb.askyesno", return_value=True):
            self.assertEqual(s.zusammenlegen(art("Sonstiges"), art("Autos")), 1)
        self.assertEqual({self.w.lade(i)["art_name"] for i in (golf, rad)}, {"Autos"})
        self.assertNotIn("Sonstiges", [z[0] for z in zeilen()])
        self.assertEqual(s._gewaehlt()["name"], "Autos")
        self.assertEqual((f.eintrag["id"], f.var_art.get()), (rad, "Autos"))       # das Wiki-Fenster zeigt es
        self.assertNotIn("Sonstiges", f.cmb_art.cget("values"))
        s.neu("Geräte")
        self.assertEqual(zeilen()[-1], ("Geräte", "0"))
        s.loeschen(art("Geräte"))
        self.assertNotIn("Geräte", [z[0] for z in zeilen()])
        self.assertEqual(self.w.anzahl(), 2)

    def test_zusammenlegen(self):
        a = self.w.speichere("Versicherung", "Hausrat Musterversicherung")
        b = self.w.speichere("Vertrag", "Muster Privatschutz")
        self.w.angabe_hinzu(b, "Versicherungsnummer: 4711")
        f = self.fenster()
        f.zeige_eintrag(a)
        with patch("tools.wiki.mb.askyesno", return_value=False) as frage:
            self.assertFalse(f.zusammenlegen(b))
        self.assertIn("„Muster Privatschutz“ (Vertrag) mit diesem Eintrag zusammenlegen?", frage.call_args[0][1])
        self.assertEqual(self.w.anzahl(), 2)                                       # Nein: nichts geschieht
        with patch("tools.wiki.mb.askyesno", return_value=True):
            self.assertTrue(f.zusammenlegen(b))
        self.assertEqual([e["bezeichnung"] for e in self.w.liste()], ["Hausrat Musterversicherung"])
        self.assertEqual(f.eintrag["id"], a)
        self.assertEqual([f.tree_angaben.item(i, "values")[0] for i in f.tree_angaben.get_children()],
                         ["Versicherungsnummer: 4711", "Auch: Muster Privatschutz"])
        self.assertFalse(f.tree.exists(f"e:{b}"))

    def test_filter(self):
        self.w.speichere("Person", "Max Mustermann")
        erika = self.w.speichere("Person", "Erika Musterfrau")
        self.w.speichere("Firma", "Muster GmbH")
        f = self.fenster()
        f.var_filter.set("erika")
        self.assertEqual([(f.tree.item(g, "text"), f.tree.get_children(g)) for g in f.tree.get_children()],
                         [("Person (1)", (f"e:{erika}",))])
        # Peter 13.11.2026: auch in Angaben und Notiz suchen - eine Nummer findet ihren Eintrag
        self.w.angabe_hinzu(erika, "Geboren am 20.04.1935")
        telefon = self.w.angabe_hinzu(erika, "Telefon: 01234/5678")
        firma = self.w.speichere("Firma", "Prüfdienst", "Kommt jedes Jahr im Juni")
        def zeilen():
            return [i for g in f.tree.get_children() for i in f.tree.get_children(g)]
        f.var_filter.set("01234 5678")
        self.assertEqual(zeilen(), [f"e:{erika}"])
        f.var_filter.set("juni")
        self.assertEqual(zeilen(), [f"e:{firma}"])
        f.var_filter.set("erika juni")                                         # alle Wörter: keiner hat beide
        self.assertEqual(zeilen(), [])
        f.var_filter.set("telefon 5678")
        f.tree.selection_set(f"e:{erika}")
        self.root.update()
        self.assertEqual(f.tree_angaben.selection(), (f"a:{telefon}",))       # die passende Angabe ist markiert
        f.var_filter.set("")
        self.assertEqual(len(zeilen()), 4)


class TestWikiWerkzeug(unittest.TestCase):
    def test_rechtsklick_menue(self):
        eintraege = [{"id": 1, "art": 1, "art_name": "Person", "bezeichnung": "Max Mustermann"},
                     {"id": 3, "art": 1, "art_name": "Person", "bezeichnung": "Erika Musterfrau"},
                     {"id": 2, "art": 5, "art_name": "Fahrzeug", "bezeichnung": "VW Golf"}]
        self.assertEqual(wf.wiki_menue(eintraege, set(), 0, 0), [("Kein Dokument markiert", None, False)])
        z = wf.wiki_menue(eintraege, {2}, 1, 1)
        self.assertEqual(z[:5], [("Beleg in:", None, False), ("Fahrzeug: VW Golf", ("zeige", 2), True), None,
                                 ("Von der KI lesen lassen…", ("ki", None), True),
                                 ("Neuer Eintrag aus dem Dokument (von Hand)…", ("neu", None), True)])
        self.assertEqual(z[5], ("Zu Eintrag hinzufügen", [
            ("Person", [("Max Mustermann", ("hinzu", 1), True), ("Erika Musterfrau", ("hinzu", 3), True)], True),
            ("Fahrzeug", [("VW Golf", ("hinzu", 2), False)], True)], True))        # schon Beleg: grau
        z = wf.wiki_menue(eintraege, {2}, 3, 3)                         # mehrere: „schon Beleg“ gilt nicht für alle
        self.assertEqual((z[4][0], z[5][1][1][1][0][2]), ("Neuer Eintrag aus den 3 Dokumenten (von Hand)…", True))
        self.assertEqual(wf.wiki_menue([], set(), 1, 0),                # im Papierkorb, Wiki leer
                         [("In keinem Wiki-Eintrag Beleg", None, False), None,
                          ("Von der KI lesen lassen…", ("ki", None), False),
                          ("Neuer Eintrag aus dem Dokument (von Hand)…", ("neu", None), False),
                          ("Zu Eintrag hinzufügen", [], False)])

    def test_beschreibung(self):
        t = wf.WikiTool()
        self.assertEqual((t.menu_label, t.menu_group, t.required_input), ("Wiki…", "KI-Helfer", "none"))
        self.assertTrue(t.absicht and t.description)
        self.assertFalse(getattr(t, "braucht_ki", False))


if __name__ == "__main__":
    unittest.main()
