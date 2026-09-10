#!/usr/bin/env bash
#
# Build the Swift port as a release .app, put it in ~/Downloads beside the Python app rather than
# over it, and open it.
#
#   swift/build-app.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
EXE="StreamingCommunityDownloader"
APP="$HOME/Downloads/StreamingCommunity Swift.app"
cd "$HERE"

echo "==> Build"
swift build -c release
BIN="$(swift build -c release --show-bin-path)/$EXE"

# Every instance, however it was started — swift run, Xcode, a previous build — because two of them
# would each write the download list over the other's. Matched on the executable path alone, so
# the compiler working on the module of the same name is left alone.
echo "==> Chiusura istanze in esecuzione"
pkill -f "/$EXE( |$)" || true
for _ in $(seq 1 25); do pgrep -f "/$EXE( |$)" >/dev/null || break; sleep 0.2; done

echo "==> Bundle"
# Only ever replace a previous build of this app: anything else with the name is somebody's file.
if [[ -e "$APP" && ! -x "$APP/Contents/MacOS/$EXE" ]]; then
  echo "   «$APP» esiste e non è una build di quest'app. Rimuovilo a mano." >&2
  exit 1
fi
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/"
cp "$REPO/icon/AppIcon.icns" "$APP/Contents/Resources/"
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>local.streamingcommunity.swift</string>
  <key>CFBundleName</key><string>StreamingCommunity Swift</string>
  <key>CFBundleExecutable</key><string>$EXE</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
</dict></plist>
EOF
codesign --force --deep -s - "$APP"
# The .icns alone comes out colourless on this system; scripts/set_icon.py says why.
"$REPO/.venv/bin/python" "$REPO/scripts/set_icon.py" "$APP" || echo "   (icona non applicata)"

echo "==> Avvio"
open "$APP"
echo "Pronta: $APP"
