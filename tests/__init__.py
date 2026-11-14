# Macht tests/ zum Paket, damit `python -m unittest discover -s tests -t .` die
# Testmodule als tests.test_xyz importiert - dieser Code läuft dabei VOR den Tests
# und legt src/ in den Suchpfad. Die Tests importieren die App-Module dadurch
# weiterhin flach (`import auto_pilot`), alle @patch("modul.name")-Strings bleiben gültig.
import atexit
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

# Jeder Lauf bekommt einen eigenen Temp-Ordner, der am Ende verschwindet: Bis 05.11.2026 blieben je Lauf 19 Ordner liegen
# (2.825 tmp* und 885 kid_tq_* in %TEMP%), weil nicht jeder Test hinter sich aufräumt.
tempfile.tempdir = tempfile.mkdtemp(prefix="kid_tests_")
atexit.register(shutil.rmtree, tempfile.tempdir, True)



# Testfenster auf einem eigenen, unsichtbaren Windows-Desktop (Peter 09.11.2026): Sie erschienen sonst bei jedem Testlauf
# kurz neben dem Mauszeiger und holten sich den Fokus (gemessen: gut 1 s je Lauf), auch wenn Peter in einem anderen
# Programm arbeitete - Tastendrücke wären im Testfenster gelandet. Fenster eines anderen Desktops sind nie zu sehen und
# können den Fokus nicht nehmen; für Tk sind sie ganz normal sichtbar. Muss laufen, bevor der Haupt-Thread ein Fenster
# hat (sonst lehnt Windows SetThreadDesktop ab) - also hier, vor dem ersten Testmodul. FALLSTRICKE #124.
if sys.platform == "win32":
    import ctypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.CreateDesktopW.restype = ctypes.c_void_p
    _user32.CreateDesktopW.argtypes = [ctypes.c_wchar_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.c_uint, ctypes.c_void_p]
    _user32.SetThreadDesktop.argtypes = [ctypes.c_void_p]
    TEST_DESKTOP = _user32.CreateDesktopW("KID-Tests", None, None, 0, 0x10000000, None)   # GENERIC_ALL
    if not (TEST_DESKTOP and _user32.SetThreadDesktop(TEST_DESKTOP)):
        TEST_DESKTOP = None
        sys.stderr.write("tests: eigener Desktop nicht möglich, Testfenster erscheinen auf dem Bildschirm\n")
