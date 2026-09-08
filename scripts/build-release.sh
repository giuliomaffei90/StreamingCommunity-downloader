#!/usr/bin/env bash
#
# Build the release .app and put it in ~/Downloads.
#
#   ./scripts/build-release.sh
#
# The test run is not a formality: the bundle takes half a minute to build and
# several more to notice it is broken, and a failure inside a frozen app reports
# far worse than the same failure from source.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

APP_NAME="StreamingCommunity Downloader.app"
DEST_DIR="$HOME/Downloads"
DEST="$DEST_DIR/$APP_NAME"

PYTHON="${PYTHON:-$REPO/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

echo "==> Test"
"$PYTHON" -m pytest -q

# After the tests, so a red run does not close an app you were using for
# nothing. Before anything is deleted: this build wipes dist/ and replaces the
# copy in ~/Downloads, and replacing a bundle whose binary is still mapped
# leaves an app that is half one version and half the other.
echo "==> Chiusura istanze in esecuzione"
if pkill -f "$APP_NAME/Contents/MacOS/" 2>/dev/null; then
  echo "   chiusa, attendo che esca"
  # SIGTERM first, above. An in-flight download dies either way, but a process
  # given a moment to go is one that cannot still hold the bundle open when the
  # copy starts.
  for _ in $(seq 1 20); do
    pgrep -f "$APP_NAME/Contents/MacOS/" >/dev/null || break
    sleep 0.25
  done
  pkill -9 -f "$APP_NAME/Contents/MacOS/" 2>/dev/null || true
else
  echo "   nessuna in esecuzione"
fi

echo "==> Build"
rm -rf build dist
"$PYTHON" -m PyInstaller StreamingCommunity.spec --noconfirm --clean

BUILT="dist/$APP_NAME"

echo "==> Verifica del bundle"
# Each of these is something that has actually been missing from a bundle that
# built without complaint, and that only shows up when the app is opened.
for required in \
  "Contents/MacOS/StreamingCommunity" \
  "Contents/Resources/app/templates/index.html" \
  "Contents/Resources/app/static/app.js" \
  "Contents/Resources/AppIcon.icns"
do
  if [[ ! -e "$BUILT/$required" ]]; then
    echo "   MANCA: $required" >&2
    exit 1
  fi
done

if ! find "$BUILT" -name 'ffmpeg*' -type f | grep -q .; then
  echo "   MANCA: il binario ffmpeg statico — l'app non unirebbe nulla" >&2
  exit 1
fi

# Searched by name rather than by path: PyInstaller cross-links Frameworks and
# Resources, and the app resolved it through the other one than it is written to.
if ! find "$BUILT" -name 'user_agents.zip' -type f | grep -q .; then
  echo "   MANCA: user_agents.zip — ogni richiesta uscente costruisce il suo" >&2
  echo "          user-agent da lì, quindi non funzionerebbe niente in rete" >&2
  exit 1
fi

VERSION="$("$PYTHON" -c 'import app; print(app.__version__)')"

echo "==> Installazione in $DEST_DIR"
if [[ -e "$DEST" ]]; then
  # Only ever replace a previous build of this app. Anything else sharing the
  # name is somebody's file, and this script does not get to decide about it.
  if [[ ! -x "$DEST/Contents/MacOS/StreamingCommunity" ]]; then
    echo "   «$DEST» esiste e non è una build di quest'app. Rimuovilo a mano." >&2
    exit 1
  fi
  rm -rf "$DEST"
fi
mkdir -p "$DEST_DIR"
cp -R "$BUILT" "$DEST"

# The .icns in the bundle is correct and macOS still renders it colourless; see
# scripts/set_icon.py for what was ruled out. Stamping a custom icon resource
# after the copy is what actually shows the icon the user drew.
"$PYTHON" "$REPO/scripts/set_icon.py" "$DEST" || echo "   (icona non applicata)"

SIZE="$(du -sh "$DEST" | cut -f1)"
echo
echo "Pronta: $DEST"
echo "Versione $VERSION · $SIZE"
echo
echo "Non è firmata: sul tuo Mac si apre normalmente, altrove serve tasto destro > Apri."

# The counterpart to closing it at the start: the build exists to be run, and
# the copy just installed is the one to open — never the one left in dist/.
echo
echo "==> Avvio"
open "$DEST"
