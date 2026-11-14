"""Die Testumgebung selbst (tests/__init__.py): Testfenster bleiben auf ihrem eigenen Desktop (FALLSTRICKE #124)."""
import ctypes
import sys
import unittest

import tests


@unittest.skipUnless(sys.platform == "win32", "nur unter Windows")
class TestEigenerDesktop(unittest.TestCase):
    def test_fenster_der_tests_entstehen_auf_dem_test_desktop(self):
        # Peter 09.11.2026: Testfenster poppten am Mauszeiger auf und nahmen den Fokus, während er woanders arbeitete
        self.assertTrue(tests.TEST_DESKTOP)
        user32 = ctypes.WinDLL("user32")
        user32.GetThreadDesktop.restype = ctypes.c_void_p
        faden = ctypes.windll.kernel32.GetCurrentThreadId()
        self.assertEqual(user32.GetThreadDesktop(faden), tests.TEST_DESKTOP)


if __name__ == "__main__":
    unittest.main()
