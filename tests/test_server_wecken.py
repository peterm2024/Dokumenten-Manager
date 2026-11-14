"""
Tests für server_wecken.py (01.11.2026): MAC-Schreibweisen, Warnung vor virtuellen Karten, Aufbau des
Magic Packets, Broadcast-Ziele und Senden (Socket gepatcht - im Test geht nichts ins Netz).
"""

import unittest
from unittest.mock import MagicMock, patch

import server_wecken as sw


class TestMac(unittest.TestCase):
    def test_schreibweisen(self):
        for roh in ("aa:bb:cc:11:22:33", "AA-BB-CC-11-22-33", "aabb.cc11.2233", " aabbcc112233 ", "AA BB CC 11 22 33"):
            with self.subTest(roh=roh):
                self.assertEqual(sw.mac_normalisieren(roh), "AA:BB:CC:11:22:33")

    def test_ungueltig(self):
        for roh in ("", None, "aa:bb:cc:11:22", "aa:bb:cc:11:22:33:00", "zz:bb:cc:11:22:33", "192.168.100.194"):
            with self.subTest(roh=roh):
                self.assertIsNone(sw.mac_normalisieren(roh))

    def test_virtuelle_karte_erkannt(self):
        """Fund 14.09.2026: in der FRITZ!Box stand unter dem Servernamen die Proxmox-Karte BC:24:11:… der VM."""
        self.assertTrue(sw.ist_virtuelle_mac("bc:24:11:aa:bb:cc"))
        self.assertTrue(sw.ist_virtuelle_mac("52-54-00-12-34-56"))
        self.assertFalse(sw.ist_virtuelle_mac("AA:BB:CC:11:22:33"))
        self.assertFalse(sw.ist_virtuelle_mac("kaputt"))


class TestPaket(unittest.TestCase):
    def test_aufbau(self):
        p = sw.magic_packet("01:02:03:04:05:06")
        self.assertEqual(len(p), 102)
        self.assertEqual(p[:6], b"\xff" * 6)
        self.assertEqual(p[6:], bytes([1, 2, 3, 4, 5, 6]) * 16)

    def test_ungueltige_mac(self):
        with self.assertRaises(ValueError):
            sw.magic_packet("nix")

    def test_ziele_ohne_tailscale_und_doppelte(self):
        adressen = [(None, None, None, None, (ip, 0)) for ip in
                    ("192.168.100.181", "100.64.0.7", "127.0.0.1", "192.168.100.181", "10.0.0.5")]
        with patch("socket.getaddrinfo", return_value=adressen):
            self.assertEqual(sw.broadcast_ziele(), ["255.255.255.255", "10.0.0.255", "192.168.100.255"])
        with patch("socket.getaddrinfo", side_effect=OSError):
            self.assertEqual(sw.broadcast_ziele(), ["255.255.255.255"])

    def test_senden(self):
        sock = MagicMock()
        with patch("socket.socket") as fabrik:
            fabrik.return_value.__enter__.return_value = sock
            self.assertEqual(sw.sende("01:02:03:04:05:06", ziele=["1.2.3.255", "255.255.255.255"]), 2)
        sock.setsockopt.assert_called_once()
        self.assertEqual(sock.sendto.call_args_list[0].args, (sw.magic_packet("010203040506"), ("1.2.3.255", 9)))

    def test_senden_scheitert_ueberall(self):
        sock = MagicMock()
        sock.sendto.side_effect = OSError("Netz weg")
        with patch("socket.socket") as fabrik:
            fabrik.return_value.__enter__.return_value = sock
            with self.assertRaises(OSError):
                sw.sende("01:02:03:04:05:06", ziele=["1.2.3.255"])


if __name__ == "__main__":
    unittest.main()
