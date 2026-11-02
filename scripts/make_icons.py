"""Render the logo PNGs in web/public from the N4b tile (same shapes as design/logo.svg and Logo.svelte).

    uv run python scripts/make_icons.py [SCRATCH_DIR]

Writes icon-192.png, icon-512.png and apple-touch-icon.png (180x180, full square: iOS rounds it itself) to
web/public. Each is drawn at 4x and downsampled with LANCZOS. With SCRATCH_DIR it also writes a 16x16 favicon
preview (roof stroke 5, as favicon.svg) and an 8x nearest-neighbour enlargement of it, to eyeball legibility.
"""

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROBIN = (0xB4, 0x49, 0x1A)
WHITE = (255, 255, 255)
SS = 4  # supersampling factor
PUBLIC = Path(__file__).resolve().parent.parent / "web" / "public"


def draw_tile(size: int, *, roof: float = 3.4, full_square: bool = False) -> Image.Image:
    """The 64x64 logo tile at `size` px. Transparent rounded corners unless `full_square`."""
    big = size * SS
    k = big / 64
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    def pt(x: float, y: float) -> tuple[float, float]:
        return x * k, y * k

    if full_square:
        d.rectangle((0, 0, big, big), fill=ROBIN)
    else:
        d.rounded_rectangle((0, 0, big - 1, big - 1), radius=15 * k, fill=ROBIN)
    # Roof: a polyline with round caps and joins.
    roof_pts = [pt(11, 29), pt(32, 15), pt(53, 29)]
    w = roof * k
    d.line(roof_pts, fill=WHITE, width=round(w), joint="curve")
    for x, y in roof_pts:
        d.ellipse((x - w / 2, y - w / 2, x + w / 2, y + w / 2), fill=WHITE)
    cx, cy = pt(32, 37.5)
    d.ellipse((cx - 13.5 * k, cy - 13.5 * k, cx + 13.5 * k, cy + 13.5 * k), fill=WHITE)
    for ex in (27, 37):
        x, y = pt(ex, 35.3)
        d.ellipse((x - 2.6 * k, y - 2.6 * k, x + 2.6 * k, y + 2.6 * k), fill=ROBIN)
    beak = [pt(29.3, 39.4), pt(34.7, 39.4), pt(32, 43.8)]
    d.polygon(beak, fill=ROBIN)
    d.line(beak + [beak[0]], fill=ROBIN, width=round(1.5 * k), joint="curve")
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    draw_tile(192).save(PUBLIC / "icon-192.png")
    draw_tile(512).save(PUBLIC / "icon-512.png")
    draw_tile(180, full_square=True).convert("RGB").save(PUBLIC / "apple-touch-icon.png")
    if len(sys.argv) > 1:
        out = Path(sys.argv[1])
        out.mkdir(parents=True, exist_ok=True)
        small = draw_tile(16, roof=5)
        small.save(out / "favicon-16.png")
        small.resize((128, 128), Image.NEAREST).save(out / "favicon-16-zoom.png")


if __name__ == "__main__":
    main()
