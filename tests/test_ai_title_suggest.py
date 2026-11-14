import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import MagicMock

import fitz

from tools.ai_title_suggest import (
    current_title_or_filename,
    katalog_vorschlaege,
    format_tags_preview,
    sibling_title_examples,
    exclude_folder_name_tag,
    AiTitleSuggestWindow,
)


def _make_pdf(path, title=""):
    doc = fitz.open()
    doc.new_page()
    if title:
        doc.set_metadata({"title": title})
    doc.save(path)
    doc.close()


class TestCurrentTitleOrFilename(unittest.TestCase):
    def test_uses_existing_title(self):
        meta = {"title": "Beitragsrechnung Kfz-Versicherung"}
        self.assertEqual(current_title_or_filename(r"C:\docs\20260413_foo.pdf", meta), "Beitragsrechnung Kfz-Versicherung")

    def test_falls_back_to_filename_without_extension(self):
        meta = {"title": ""}
        self.assertEqual(current_title_or_filename(r"C:\docs\20260413_foo.pdf", meta), "20260413_foo")

    def test_none_metadata_falls_back_to_filename(self):
        self.assertEqual(current_title_or_filename(r"C:\docs\bar.pdf", None), "bar")


class TestKatalogVorschlaege(unittest.TestCase):
    """Etappe 6 (Peter 07.11.2026, FALLSTRICKE #120): KI-Tags nur aus dem Katalog, nur zum Anklicken."""

    def test_nur_katalog_tags_in_katalog_schreibweise(self):
        self.assertEqual(katalog_vorschlaege(["kfz", "Erfunden", "Rechnung"], ["Kfz", "Rechnung", "Versicherung"]),
                         ["Kfz", "Rechnung"])

    def test_ohne_was_das_dokument_schon_traegt_und_ohne_doppelte(self):
        self.assertEqual(katalog_vorschlaege(["Kfz", "KFZ", "Rechnung"], ["Kfz", "Rechnung"], "rechnung, Alt"), ["Kfz"])

    def test_leer(self):
        self.assertEqual(katalog_vorschlaege(None, ["Kfz"]), [])
        self.assertEqual(katalog_vorschlaege(["Kfz"], None), [])


class TestFormatTagsPreview(unittest.TestCase):
    def test_marks_unknown_tags_as_new(self):
        result = format_tags_preview(["Kfz", "Neuerfindung"], {"kfz", "rechnung"})
        self.assertEqual(result, "Kfz, (neu) Neuerfindung")

    def test_no_markers_when_all_known(self):
        result = format_tags_preview(["Kfz", "Rechnung"], {"kfz", "rechnung"})
        self.assertEqual(result, "Kfz, Rechnung")

    def test_case_insensitive_known_check(self):
        result = format_tags_preview(["KFZ"], {"kfz"})
        self.assertEqual(result, "KFZ")


class TestExcludeFolderNameTag(unittest.TestCase):
    def test_removes_tag_matching_folder_name(self):
        result = exclude_folder_name_tag(["Gentilia", "Rechnung"], r"C:\KID\G - H - I\Gentilia")
        self.assertEqual(result, ["Rechnung"])

    def test_case_insensitive(self):
        result = exclude_folder_name_tag(["gentilia", "Rechnung"], r"C:\KID\G - H - I\Gentilia")
        self.assertEqual(result, ["Rechnung"])

    def test_no_match_leaves_list_unchanged(self):
        result = exclude_folder_name_tag(["Rechnung", "Haftpflicht"], r"C:\KID\G - H - I\Gentilia")
        self.assertEqual(result, ["Rechnung", "Haftpflicht"])

    def test_trailing_slash_folder_path(self):
        result = exclude_folder_name_tag(["Gentilia"], r"C:\KID\G - H - I\Gentilia\ ".rstrip())
        self.assertEqual(result, [])

    def test_removes_truncated_variant_of_folder_name(self):
        # KI liest den Firmennamen manchmal abgeschnitten ("Gentili" statt "Gentilia")
        result = exclude_folder_name_tag(["Gentili", "Rechnung"], r"C:\KID\G - H - I\Gentilia")
        self.assertEqual(result, ["Rechnung"])

    def test_removes_extended_variant_containing_folder_name(self):
        # ... oder erweitert um die Rechtsform ("Gentilia Deutschland Versicherung AG")
        result = exclude_folder_name_tag(["Gentilia Deutschland Versicherung AG", "Rechnung"], r"C:\KID\G - H - I\Gentilia")
        self.assertEqual(result, ["Rechnung"])

    def test_keeps_year_tag_when_folder_contains_year(self):
        # Jahres-Tags sind gewollt und dürfen NICHT gefiltert werden, nur weil die
        # Jahreszahl zufällig im Ordnernamen vorkommt
        result = exclude_folder_name_tag(["2023", "Rechnung"], r"C:\KID\Rechnungen 2023")
        self.assertEqual(result, ["2023", "Rechnung"])

    def test_keeps_short_prefix_tags(self):
        # Kurz-Tags unter 4 Zeichen lösen den Präfix-Check nicht aus (zu viele Zufallstreffer)
        result = exclude_folder_name_tag(["Gen"], r"C:\KID\G - H - I\Gentilia")
        self.assertEqual(result, ["Gen"])


class TestSiblingTitleExamples(unittest.TestCase):
    def test_collects_titled_siblings_excludes_self_and_untitled(self):
        with tempfile.TemporaryDirectory() as tmp:
            _make_pdf(os.path.join(tmp, "a.pdf"), title="Beitragsrechnung Gentilia")
            _make_pdf(os.path.join(tmp, "b.pdf"))  # kein Titel -> fällt auf Dateinamen zurück, wird ausgeschlossen
            target = os.path.join(tmp, "c.pdf")
            _make_pdf(target, title="Wird ignoriert, da es das Ziel-Dokument selbst ist")

            examples = sibling_title_examples(target)
            self.assertEqual(examples, ["Beitragsrechnung Gentilia"])

    def test_respects_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                _make_pdf(os.path.join(tmp, f"doc{i}.pdf"), title=f"Titel {i}")
            target = os.path.join(tmp, "target.pdf")
            _make_pdf(target)

            self.assertEqual(len(sibling_title_examples(target, limit=2)), 2)

    def test_ignores_non_pdf_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "notes.txt"), "w") as f:
                f.write("kein PDF")
            target = os.path.join(tmp, "target.pdf")
            _make_pdf(target)

            self.assertEqual(sibling_title_examples(target), [])

    def test_missing_folder_returns_empty_list(self):
        self.assertEqual(sibling_title_examples(r"C:\this\folder\does\not\exist\file.pdf"), [])



class TestFensterGeschlossen(unittest.TestCase):
    def test_spaete_ki_antwort_nach_schliessen_ohne_fehler(self):
        """Peter 28.10.2026: Fenster während der Analyse geschlossen -> TclError ".!aititlesuggestwindow3.!treeview"."""
        root = tk.Tk()
        root.withdraw()
        try:
            fenster = AiTitleSuggestWindow(root, MagicMock(), [])
            iid = fenster.tree.insert("", "end", values=("☐", "alt", "", ""))
            fenster.rows[iid] = {"path": "x.pdf", "old_title": "alt", "keywords": ""}
            fenster._schliessen()
            self.assertTrue(fenster._stop)
            fenster._on_suggestion_ready(iid, {"title": "Neu", "tags": []}, set(), 1, 1)   # darf nicht werfen
        finally:
            root.destroy()


class TestVorschlaegeNurZumAnklicken(unittest.TestCase):
    def test_ki_tags_kommen_nicht_von_selbst_ins_tag_feld(self):
        """Etappe 6 (FALLSTRICKE #120): Früher landeten die KI-Tags gleich im Tag-Feld und wurden mit dem Titel geschrieben."""
        root = tk.Tk()
        root.withdraw()
        try:
            fenster = AiTitleSuggestWindow(root, MagicMock(), [])
            iid = fenster.tree.insert("", "end", values=("☐", "alt", "", ""))
            fenster.rows[iid] = {"path": "x.pdf", "old_title": "alt", "keywords": "Versicherung"}
            fenster._on_suggestion_ready(iid, {"title": "Neu", "tags": ["Kfz", "Rechnung"]}, {"versicherung"}, 1, 1)
            self.assertEqual(fenster.rows[iid]["tags_csv"], "Versicherung")
            self.assertEqual(fenster.rows[iid]["suggested_tags"], ["Kfz", "Rechnung"])   # bereit für den Tag-Dialog
            self.assertEqual(fenster.tree.set(iid, "tags"), "Versicherung  [+2 Vorschläge: Doppelklick]")
            fenster._stop = True
            fenster.destroy()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
