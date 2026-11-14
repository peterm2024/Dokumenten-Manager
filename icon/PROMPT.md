# Prompt für ein Programmsymbol (Bild-KI)

Das mitgelieferte `app.ico` ist mit Pillow gezeichnet (`icon_erzeugen.py`). Wer ein aufwendigeres Symbol möchte, kann diesen Prompt in eine Bild-KI (z.B. Midjourney, DALL·E, Stable Diffusion, Ideogram) geben und das Ergebnis als 1024×1024-PNG mit transparentem Hintergrund speichern; `icon_erzeugen.py` lässt sich dann leicht so ändern, dass es das PNG statt der eigenen Zeichnung in die ICO-Größen herunterrechnet.

## Prompt (englisch, für die meisten Bild-KIs)

> Flat, modern app icon for a Windows desktop application that organizes PDF documents. A single white document sheet with a folded top-right corner, showing three or four short grey text lines, with an orange price-tag / label hanging over its lower right corner (the tag has a small round hole and a string). Background: a rounded square in deep blue (#1F4E79). Minimal, clean vector style, no text, no letters, no gradients heavier than a subtle one, high contrast, centered composition, generous margins so the motif stays readable at 16×16 pixels. Transparent background outside the rounded square. 1024×1024.

## Varianten

- **Mit KI-Andeutung:** `… and a small four-pointed sparkle in light blue at the top-left of the sheet, hinting at AI assistance …`
- **Mit Ordner statt Blatt:** `… a white folder tab behind the document sheet …`
- **Anderer Grundton:** `deep blue (#1F4E79)` durch `dark teal (#1F6F78)` oder `graphite (#2B2F36)` ersetzen.

## Negativ-Prompt (falls das Werkzeug einen kennt)

> text, letters, watermark, photo, 3D render, drop shadow outside the square, blurry, multiple icons, frame, border

## Anforderungen an das Ergebnis

- Motiv bei 16 px noch erkennbar (Blatt + farbiger Anhänger genügen, Details fallen weg).
- Keine Schrift im Bild - Buchstaben werden bei kleinen Größen zu Matsch.
- Ecken des Grundquadrats abgerundet (Radius etwa 20 % der Kantenlänge), außerhalb transparent.
- Farben: Blau #1F4E79 (Überschriften der Hilfe), Orange #F08C14 (Anhänger), Weiß.
