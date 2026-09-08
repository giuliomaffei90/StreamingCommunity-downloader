"""Stamp the app's icon onto a built bundle.

    python scripts/set_icon.py "<path to .app>"

Why this exists rather than just `icon=` in the spec, which is already set:
the .icns lands in the bundle correctly and `NSImage` renders it in full colour,
but whatever LaunchServices does with it comes back with the colour stripped and
the system's own shading applied — a red plate becomes a black one. That was
chased a long way and never explained. Ruled out along the way: the icns itself,
its chunk structure, the raw ARGB entries, its `info` chunk, Pillow versus sips
as the encoder, the PNG colour mode and profile, PyInstaller's bundle (a
hand-written four-line bundle behaves the same), the icon caches by path and by
bundle identifier, lsregister, quarantine, the code signature, and dark mode.

`NSWorkspace.setIcon:forFile:` writes a custom icon resource instead, which is
the same thing Finder's Get Info paste does, and macOS honours it without
consulting any of the above. It is applied after the bundle is in place, so it
survives the copy.
"""

import os
import sys


def main(app_path: str) -> int:
    if not os.path.isdir(app_path):
        print(f"Nessun bundle in {app_path}", file=sys.stderr)
        return 1

    try:
        from AppKit import NSImage, NSWorkspace
    except ImportError:
        # pyobjc rides in with pywebview, so this is only reachable if the build
        # environment is missing its own dependencies.
        print("pyobjc non disponibile: icona non applicata", file=sys.stderr)
        return 1

    source = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "icon", "icon.png")
    image = NSImage.alloc().initWithContentsOfFile_(source)
    if image is None:
        print(f"Non riesco a leggere {source}", file=sys.stderr)
        return 1

    if not NSWorkspace.sharedWorkspace().setIcon_forFile_options_(image, app_path, 0):
        print("setIcon rifiutato dal sistema", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
