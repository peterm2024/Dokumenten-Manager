"""
KI-Server per Wake-on-LAN wecken (Peters Wunsch 01.11.2026: „per Doppelklick auf die LED aufwecken“).

Der Server schläft nachts (Nachtruhe auf dem Host, siehe Projekte-Wiki ki-infrastruktur.md); bisher ging
Wecken nur über die FRITZ!Box-Oberfläche. Ein „Magic Packet“ ist ein UDP-Broadcast: 6 × 0xFF, dann
16 × die MAC-Adresse der Netzwerkkarte. Nur Standardbibliothek, ohne Tkinter - die Oberfläche sitzt in
ki_status.py.

Grenzen:
- Broadcasts kommen nur im selben Heimnetz an, nicht über Tailscale oder einen Router hinweg.
- Es muss die MAC der ECHTEN Netzwerkkarte des Server-PCs sein. Die einer virtuellen Maschine (Proxmox
  vergibt BC:24:11:…) lässt sich nicht wecken (Fund 14.09.2026); `ist_virtuelle_mac` warnt davor.
"""

import re
import socket

PORT = 9
# Hersteller-Präfixe virtueller Netzwerkkarten: Proxmox, QEMU/KVM, Hyper-V, VirtualBox, VMware
VIRTUELLE_PRAEFIXE = ("BC:24:11", "52:54:00", "00:15:5D", "08:00:27", "00:0C:29", "00:50:56", "00:05:69")


def mac_normalisieren(text):
    """„aa-bb-cc-11-22-33“, „AABB.CC11.2233“, „aabbcc112233“ → „AA:BB:CC:11:22:33“; Ungültiges → None.
    Die Gruppen müssen passen (6 × 2, 3 × 4 oder 1 × 12 Zeichen) - sonst ginge eine versehentlich eingetippte
    IP-Adresse wie 192.168.100.194 (zwölf Ziffern) als MAC durch."""
    gruppen = [g for g in re.split(r"[\s:.\-]+", str(text or "").strip().upper()) if g]
    if [len(g) for g in gruppen] not in ([2] * 6, [4] * 3, [12]):
        return None
    ziffern = "".join(gruppen)
    if not re.fullmatch(r"[0-9A-F]{12}", ziffern):
        return None
    return ":".join(ziffern[i:i + 2] for i in range(0, 12, 2))


def ist_virtuelle_mac(mac):
    mac = mac_normalisieren(mac)
    return bool(mac) and mac[:8] in VIRTUELLE_PRAEFIXE


def magic_packet(mac):
    mac = mac_normalisieren(mac)
    if not mac:
        raise ValueError("keine gültige MAC-Adresse")
    return b"\xff" * 6 + bytes.fromhex(mac.replace(":", "")) * 16


def broadcast_ziele():
    """255.255.255.255 plus die /24-Broadcasts aller eigenen IPv4-Adressen - Windows schickt den allgemeinen
    Broadcast sonst womöglich nur über eine Karte hinaus (z.B. Tailscale statt LAN)."""
    ziele = ["255.255.255.255"]
    try:
        adressen = {a[4][0] for a in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)}
    except OSError:
        adressen = set()
    for ip in sorted(adressen):
        teile = ip.split(".")
        if len(teile) == 4 and not ip.startswith(("127.", "169.254.", "100.")):  # 100.x = Tailscale
            ziele.append(".".join(teile[:3] + ["255"]))
    return list(dict.fromkeys(ziele))


def sende(mac, ziele=None, port=PORT):
    """Magic Packet an alle Ziele schicken. Liefert die Zahl der Ziele, an die es ging; OSError, wenn keines."""
    paket = magic_packet(mac)
    gesendet, fehler = 0, None
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for ziel in (ziele or broadcast_ziele()):
            try:
                s.sendto(paket, (ziel, port))
                gesendet += 1
            except OSError as e:
                fehler = e
    if not gesendet:
        raise fehler or OSError("kein Broadcast-Ziel")
    return gesendet
