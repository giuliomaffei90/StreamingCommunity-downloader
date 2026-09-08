"""Generate the app icon: icon.png (1024) and AppIcon.icns.

    python icon/make_icon.py

Drawn rather than designed in a graphics app so the icon is regenerable and its
colours stay tied to the interface's own: ``--accent`` and ``--bg-base`` from
app/templates/index.html. Change them there and here together, or the app and
its icon drift apart.

Everything is drawn at 4x and downsampled with LANCZOS at the end. PIL's
ImageDraw does not anti-alias, so shapes drawn at final size come out with
stepped edges — at 16px in the menu bar that is the whole icon.

The output is committed: the build reads AppIcon.icns and must not depend on
Pillow, which is a development dependency and is deliberately excluded from the
bundle.
"""

import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).parent

SIZE = 1024
SCALE = 4  # drawn this many times larger, then downsampled

# macOS icons do not fill their canvas. Big Sur onwards the rounded plate is
# 824 of 1024 with the rest transparent, which is what makes an icon sit at the
# same visual size as its neighbours in the Dock.
PLATE = 824
PLATE_RADIUS = 185

# From the interface's palette. ACCENT is --accent; the other two are it lifted
# and dropped, so the plate reads as one colour with light falling on it.
ACCENT_TOP = (240, 60, 96)
ACCENT_BOTTOM = (166, 20, 55)
GLYPH = (255, 255, 255)


def _gradient(size: int) -> Image.Image:
    """A vertical gradient, built one row at a time and stretched sideways."""
    column = Image.new("RGB", (1, size))
    pixels = column.load()
    for y in range(size):
        t = y / (size - 1)
        pixels[0, y] = tuple(
            round(top + (bottom - top) * t)
            for top, bottom in zip(ACCENT_TOP, ACCENT_BOTTOM)
        )
    return column.resize((size, size), Image.Resampling.BILINEAR)


def _plate(size: int) -> Image.Image:
    """The rounded square, gradient-filled, on a transparent canvas."""
    scale = size / SIZE
    plate, radius = PLATE * scale, PLATE_RADIUS * scale
    inset = (size - plate) / 2

    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset, inset, inset + plate, inset + plate), radius=radius, fill=255
    )

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(_gradient(size), (0, 0), mask)
    return canvas


def _arrow(canvas: Image.Image, size: int):
    """A download arrow: stem, head, and the line it lands on.

    Sized generously. An icon is read at 16px far more often than at 1024, and
    a glyph that looks balanced large turns to mush small.
    """
    scale = size / SIZE
    draw = ImageDraw.Draw(canvas)

    def at(*values):
        return [v * scale for v in values]

    # Stem
    draw.rounded_rectangle(at(468, 268, 556, 590), radius=44 * scale, fill=GLYPH)
    # Head
    draw.polygon(at(346, 536, 678, 536, 512, 736), fill=GLYPH)
    # The line it lands on
    draw.rounded_rectangle(at(330, 772, 694, 838), radius=33 * scale, fill=GLYPH)


def render(size: int = SIZE) -> Image.Image:
    big = size * SCALE
    canvas = _plate(big)
    _arrow(canvas, big)
    return canvas.resize((size, size), Image.Resampling.LANCZOS)


# (filename, pixel size) for every entry .icns expects. The @2x files are the
# same square at twice the pixels, not a different drawing.
ICONSET = [
    ("icon_16x16.png", 16), ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32), ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128), ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256), ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512), ("icon_512x512@2x.png", 1024),
]


def main():
    master = render()
    master.save(HERE / "icon.png")

    iconset = HERE / "AppIcon.iconset"
    iconset.mkdir(exist_ok=True)
    for name, size in ICONSET:
        # Downsampled from the 1024 master rather than re-rendered: the glyph
        # keeps the same proportions at every size.
        master.resize((size, size), Image.Resampling.LANCZOS).save(iconset / name)

    result = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(HERE / "AppIcon.icns")],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(1)

    for png in iconset.iterdir():
        png.unlink()
    iconset.rmdir()

    print(f"icon.png and AppIcon.icns written to {HERE}")


if __name__ == "__main__":
    main()
