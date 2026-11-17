"""Dubletten-Finder-Fenster: Layout der beiden Vorschauen (FALLSTRICKE #66)."""
import tkinter as tk
import unittest

from tools.dubletten_finder import PARTNER_KLICKS, SeitenVorschau, lege_vorschauen_nebeneinander


class TestRechtesDokument(unittest.TestCase):
    def test_rechtsklick_und_shift_klick_waehlen_rechts(self):
        # Peter 17.11.2026: „LK = linkes Dokument, RK = rechtes Dokument“ - Shift+Klick bleibt zusätzlich
        self.assertIn("<Button-3>", PARTNER_KLICKS)
        self.assertIn("<Shift-Button-1>", PARTNER_KLICKS)


class TestVorschauenGleichBreit(unittest.TestCase):
    def test_teiler_bleibt_in_der_mitte_trotz_langem_dateinamen(self):
        root = tk.Tk()
        try:
            # nicht withdraw(): ein unsichtbares Fenster wird nicht layoutet (Breiten bleiben 1)
            root.geometry("1000x400+0+0")
            rahmen = tk.Frame(root)
            rahmen.pack(fill=tk.BOTH, expand=True)
            links, rechts = SeitenVorschau(rahmen), SeitenVorschau(rahmen)
            lege_vorschauen_nebeneinander(rahmen, [links, rechts])
            links.titel.config(text="Markiert: 20241003_HKV.pdf")
            rechts.titel.config(text="Vergleich: 20241003_Beitragsrechnung HKV Privatschutz Versicherung AG Hannover.pdf")
            root.update_idletasks()
            root.update()
            self.assertLessEqual(abs(links.winfo_width() - rechts.winfo_width()), 4,
                                 (links.winfo_width(), rechts.winfo_width()))
            self.assertGreater(links.winfo_width(), 300)
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
