"""Dubletten-Finder-Fenster: Layout der beiden Vorschauen (FALLSTRICKE #66)."""
import tkinter as tk
import unittest

from tools.dubletten_finder import SeitenVorschau, lege_vorschauen_nebeneinander


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
