"""
Programm-Icon erzeugen (14.09.2026): python icon/icon_erzeugen.py

Zeichnet mit Pillow ein einfaches, auch bei 16 px lesbares Motiv - weißes Dokumentblatt mit
Eselsohr auf dunkelblauem, abgerundetem Grund, darauf ein orangefarbener Tag-Anhänger -
und schreibt icon/app.ico (16 bis 256 px) sowie icon/app_256.png (Vorschau, README).
Kein Text im Icon: Schrift ist bei kleinen Größen nur Matsch.
Verwendung: build_exe.py (--icon, EXE-Symbol), gui.py (Fenstersymbol über app_paths).
"""

import os
from PIL import Image, ImageDraw

HIER = os.path.dirname(os.path.abspath(__file__))
BLAU = (31, 78, 121)        # help_window.HEADING_COLOR
BLAU_HELL = (0, 120, 215)   # Accent.TButton
ORANGE = (240, 140, 20)
WEISS = (255, 255, 255)
GRAU = (170, 180, 195)


def zeichne(groesse=256):
    """Motiv in 4-facher Größe zeichnen und herunterrechnen (glatte Kanten)."""
    s = groesse * 4
    bild = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    z = ImageDraw.Draw(bild)
    e = s / 256  # Einheit: 1 px im 256er-Icon

    # Grund: abgerundetes Quadrat in einer Farbe (ein Verlauf bringt bei 16-32 px nichts)
    z.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(52 * e), fill=BLAU)

    # Dokumentblatt mit Eselsohr oben rechts
    l, t, r, b = 56 * e, 34 * e, 200 * e, 222 * e
    ohr = 40 * e
    blatt = [(l, t), (r - ohr, t), (r, t + ohr), (r, b), (l, b)]
    z.polygon(blatt, fill=WEISS)
    z.polygon([(r - ohr, t), (r - ohr, t + ohr), (r, t + ohr)], fill=(215, 225, 238))
    # Textzeilen
    for i, breite in enumerate((70, 100, 100, 84, 100, 60)):
        y = t + 66 * e + i * 20 * e
        z.rounded_rectangle((l + 22 * e, y, l + (22 + breite) * e, y + 9 * e), radius=int(4 * e), fill=GRAU)

    # Tag-Anhänger unten rechts (Schild mit Loch), leicht gedreht
    tag = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    zt = ImageDraw.Draw(tag)
    tl, tt, tr, tb = 118 * e, 150 * e, 236 * e, 208 * e
    spitze = 30 * e
    zt.polygon([(tl + spitze, tt), (tr, tt), (tr, tb), (tl + spitze, tb), (tl, (tt + tb) / 2)], fill=ORANGE)
    zt.ellipse((tl + spitze - 2 * e, (tt + tb) / 2 - 8 * e, tl + spitze + 14 * e, (tt + tb) / 2 + 8 * e), fill=WEISS)
    tag = tag.rotate(-18, resample=Image.BICUBIC, center=(int(177 * e), int(179 * e)))
    # Schatten unter dem Anhänger
    schatten = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    schatten.paste((0, 0, 0, 70), (0, 0, s, s), tag.split()[3])
    bild.alpha_composite(schatten, (int(3 * e), int(5 * e)))
    bild.alpha_composite(tag)

    return bild.resize((groesse, groesse), Image.LANCZOS)


def main():
    gross = zeichne(256)
    gross.save(os.path.join(HIER, "app_256.png"))
    bilder = [gross.resize((n, n), Image.LANCZOS) for n in (16, 24, 32, 48, 64, 128, 256)]
    bilder[-1].save(os.path.join(HIER, "app.ico"), format="ICO", sizes=[b.size for b in bilder],
                    append_images=bilder[:-1])
    # Vorschau in kleinen Größen zum Prüfen
    vorschau = Image.new("RGBA", (16 + 24 + 32 + 48 + 64 + 5 * 12, 70), (240, 240, 240, 255))
    x = 6
    for b in bilder[:5]:
        vorschau.alpha_composite(b, (x, 3))
        x += b.width + 12
    vorschau.save(os.path.join(HIER, "vorschau_klein.png"))
    print("app.ico, app_256.png, vorschau_klein.png geschrieben")


if __name__ == "__main__":
    main()
