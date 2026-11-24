"""Build docs/images/hero.png (the README banner) from the example pictures.

Three rows – a line plot, a bar chart and a micrograph – each shown as
published figure → extraction checked on the original → journal-style replot.
Run after tools/build_examples.py (which calls it at the end).
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

IMG = Path(__file__).resolve().parent.parent / "docs" / "images"
W, CELL_H, GAP, TOP = 1300, 300, 20, 60


def _font(size, bold=False):
    names = (["DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf"] if bold else ["DejaVuSans.ttf", "LiberationSans-Regular.ttf"])
    for n in names:
        for d in ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/truetype/liberation"):
            p = Path(d) / n
            if p.exists():
                return ImageFont.truetype(str(p), size)
    return ImageFont.load_default()


def _fit(im: Image.Image, w: int, h: int) -> Image.Image:
    f = min(w / im.width, h / im.height)
    return im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.LANCZOS)


def main():
    rows = [["line_input", "line_overlay", "line_replot"],
            ["bar_input", "bar_overlay", "bar_replot"],
            ["micro_input", "micro_overlay", "micro_combined"]]
    H = TOP + len(rows) * (CELL_H + GAP)
    canvas = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(canvas)
    d.text((20, 16), "published figure  →  extracted data, verified on the original  →  journal-ready replot",
           fill=(30, 41, 59), font=_font(22, bold=True))
    cw = (W - 4 * GAP) // 3
    for r, row in enumerate(rows):
        y = TOP + r * (CELL_H + GAP)
        names = row if (IMG / f"{row[0]}.png").exists() else row[1:]
        cells = [Image.open(IMG / f"{n}.png").convert("RGB") for n in names if (IMG / f"{n}.png").exists()]
        if len(cells) == 2:            # micrograph row: the combined figure takes two cells
            widths = [cw, 2 * cw + GAP]
        else:
            widths = [cw] * len(cells)
        x = GAP
        for im, w in zip(cells, widths):
            im = _fit(im, w, CELL_H)
            canvas.paste(im, (x + (w - im.width) // 2, y + (CELL_H - im.height) // 2))
            x += w + GAP
    canvas.save(IMG / "hero.png", optimize=True)
    print("written", IMG / "hero.png")


if __name__ == "__main__":
    main()
