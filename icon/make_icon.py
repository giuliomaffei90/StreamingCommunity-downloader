"""Generate the app icon: icon.png (1024) and AppIcon.icns.

    python icon/make_icon.py

**The icon is a red plate with a white glyph. Keep it that way.** Whatever else
changes here, that pair is the app's identity — a red tile in the Dock with a
white download mark on it — and it is the one thing not to redesign in passing.

Drawn rather than designed in a graphics app so the icon is regenerable. The
mark is the plain download arrow: a stem, a chevron and the tray it lands in,
all stroked with round caps, which is what makes it legible at 16px where a
filled triangle turns into a smudge.

The plate is treated the way macOS treats glass: light collects along the top
edge, falls off over the upper third, and bounces back faintly off the bottom.
The glyph sits above that on a soft shadow. All of it is cheap compositing —
gradients, masks and one blur — because the alternative is an SVG renderer and
a new dependency for one file that is regenerated a few times a year.

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

from PIL import Image, ImageChops, ImageDraw, ImageFilter

HERE = Path(__file__).parent

SIZE = 1024
SCALE = 4  # drawn this many times larger, then downsampled

# macOS icons do not fill their canvas. Big Sur onwards the rounded plate is
# 824 of 1024 with the rest transparent, which is what makes an icon sit at the
# same visual size as its neighbours in the Dock.
PLATE = 824
PLATE_RADIUS = 185

# A red plate, lighter at the top and darker at the bottom so it reads as one
# colour with light falling on it. Deliberately redder than the interface's
# --accent (#e02444), which leans crimson: at 32 pixels in the Dock that lean
# reads as pink rather than as red.
ACCENT_TOP = (240, 58, 48)
ACCENT_BOTTOM = (163, 16, 16)
GLYPH = (255, 255, 255)

# The download mark, in its own 512-unit square. Stroke centres, so every
# coordinate is the middle of a 42-wide stroke with a round cap on each end.
GLYPH_BOX = 512
STROKE = 42
STEM = ((256, 88), (256, 312))
CHEVRON = ((152, 230), (256, 334), (360, 230))
TRAY = (97, 300, 415, 438)  # a rounded rectangle with its top half cut away
TRAY_RADIUS = 52
TRAY_TOP = 352  # where the two open ends of the tray stop

# What the mark measures once its stroke is included, and where the middle of
# that is: the glyph is centred by its ink, not by its coordinate box, or it
# hangs low on the plate.
GLYPH_TOP = STEM[0][1] - STROKE / 2
GLYPH_BOTTOM = TRAY[3] + STROKE / 2
# Of the plate. Chosen at 16px, not at 1024: at 0.52 the mark was still
# balanced large but had gone to a smudge in the menu bar.
GLYPH_HEIGHT = 0.64


def _fade(size: int, alpha) -> Image.Image:
    """A vertical alpha ramp, built one row at a time and stretched sideways.

    ``alpha`` takes a position from 0 (top) to 1 (bottom) and returns 0-255.
    """
    column = Image.new("L", (1, size))
    pixels = column.load()
    for y in range(size):
        pixels[0, y] = max(0, min(255, round(alpha(y / (size - 1)))))
    return column.resize((size, size), Image.Resampling.BILINEAR)


def _gradient(size: int) -> Image.Image:
    column = Image.new("RGB", (1, size))
    pixels = column.load()
    for y in range(size):
        t = y / (size - 1)
        pixels[0, y] = tuple(
            round(top + (bottom - top) * t)
            for top, bottom in zip(ACCENT_TOP, ACCENT_BOTTOM)
        )
    return column.resize((size, size), Image.Resampling.BILINEAR)


def _plate_mask(size: int) -> Image.Image:
    scale = size / SIZE
    plate, radius = PLATE * scale, PLATE_RADIUS * scale
    inset = (size - plate) / 2
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (inset, inset, inset + plate, inset + plate), radius=radius, fill=255
    )
    return mask


def _glass(canvas: Image.Image, size: int, plate: Image.Image):
    """Light on the plate: a rim along the top, a sheen under it, a bottom bounce.

    Every layer is multiplied by the plate mask before it lands, so nothing
    spills past the rounded corners into the transparent margin.
    """
    scale = size / SIZE
    inset = (size - PLATE * scale) / 2
    radius = PLATE_RADIUS * scale

    # The sheen: brightest at the very top, gone by a little under halfway.
    # Blurred so it has no edge of its own — an edge here reads as a second
    # shape sitting on the plate rather than as light.
    sheen = _fade(size, lambda t: 150 * max(0.0, 1 - t / 0.46) ** 1.7)
    sheen = sheen.filter(ImageFilter.GaussianBlur(28 * scale))
    canvas.paste(Image.new("RGB", (size, size), (255, 255, 255)),
                 (0, 0), ImageChops.multiply(sheen, plate))

    # The rim: a hairline of near-white just inside the top edge, following the
    # corners round and fading out before it reaches the sides. This is the one
    # detail that makes the plate read as glass rather than as flat paint.
    rim_width = 7 * scale
    rim = Image.new("L", (size, size), 0)
    ImageDraw.Draw(rim).rounded_rectangle(
        (inset + rim_width / 2, inset + rim_width / 2,
         inset + PLATE * scale - rim_width / 2, inset + PLATE * scale - rim_width / 2),
        radius=radius, outline=255, width=round(rim_width),
    )
    rim = rim.filter(ImageFilter.GaussianBlur(2.5 * scale))
    rim = ImageChops.multiply(rim, _fade(size, lambda t: 235 * max(0.0, 1 - t / 0.34) ** 1.1))
    canvas.paste(Image.new("RGB", (size, size), (255, 255, 255)),
                 (0, 0), ImageChops.multiply(rim, plate))

    # Light bouncing back off whatever the icon is sitting on. Faint on purpose:
    # visible at 512, and at 16px it is doing nothing but keeping the bottom
    # edge from going dead flat.
    bounce = ImageChops.multiply(
        rim, _fade(size, lambda t: 150 * max(0.0, (t - 0.72) / 0.28) ** 1.4)
    )
    canvas.paste(Image.new("RGB", (size, size), (255, 214, 208)),
                 (0, 0), ImageChops.multiply(bounce, plate))


def _glyph_mask(size: int) -> Image.Image:
    """The download mark, drawn in its own square and placed on the plate.

    Strokes are lines plus a disc at every vertex: PIL draws neither round caps
    nor round joins, and without the discs the chevron comes to a chiselled
    point and the stem ends in a flat edge.
    """
    scale = size / SIZE
    span = PLATE * scale * GLYPH_HEIGHT / (GLYPH_BOTTOM - GLYPH_TOP)
    mid_x, mid_y = GLYPH_BOX / 2, (GLYPH_TOP + GLYPH_BOTTOM) / 2

    def at(x, y):
        return (size / 2 + (x - mid_x) * span, size / 2 + (y - mid_y) * span)

    width = STROKE * span
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)

    def stroke(points):
        radius = width / 2
        placed = [at(*p) for p in points]
        for start, end in zip(placed, placed[1:]):
            draw.line((*start, *end), fill=255, width=round(width))
        for x, y in placed:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=255)

    stroke(STEM)
    stroke(CHEVRON)

    # The tray is a rounded rectangle with its top half taken off, which is what
    # gives the two bottom corners a proper radius. Drawn on its own layer so
    # the cut does not take the arrow with it.
    tray = Image.new("L", (size, size), 0)
    tray_draw = ImageDraw.Draw(tray)
    # Grown by half a stroke on every side: PIL puts an outline's *outer* edge
    # on the rectangle and thickens inward, so without this the stroke centre
    # lands half a width in from TRAY and the round caps below, placed on TRAY
    # itself, stick out of the corners as two knobs.
    half = width / 2
    left, top = at(TRAY[0], TRAY[1])
    right, bottom = at(TRAY[2], TRAY[3])
    tray_draw.rounded_rectangle(
        (left - half, top - half, right + half, bottom + half),
        radius=TRAY_RADIUS * span + half, outline=255, width=round(width),
    )
    cut = at(0, TRAY_TOP)[1]
    tray_draw.rectangle((0, 0, size, cut), fill=0)
    # Round caps for the two ends the cut just left square.
    for x in (TRAY[0], TRAY[2]):
        cx, cy = at(x, TRAY_TOP)
        radius = width / 2
        tray_draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=255)

    return ImageChops.lighter(mask, tray)


def render(size: int = SIZE) -> Image.Image:
    big = size * SCALE
    plate = _plate_mask(big)

    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    canvas.paste(_gradient(big), (0, 0), plate)
    _glass(canvas, big, plate)

    # The glyph floats: a blurred dark copy dropped below it separates the white
    # from the red, which at small sizes is the difference between a mark and a
    # hole in the plate.
    glyph = _glyph_mask(big)
    shadow = glyph.filter(ImageFilter.GaussianBlur(11 * big / SIZE))
    shadow = shadow.point(lambda v: round(v * 0.42))
    canvas.paste(Image.new("RGB", (big, big), (86, 6, 6)),
                 (0, round(9 * big / SIZE)), ImageChops.multiply(shadow, plate))
    canvas.paste(Image.new("RGB", (big, big), GLYPH), (0, 0), glyph)

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
