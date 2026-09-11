#!/usr/bin/env bash
#
# Build the Swift port as a release .app, put it in ~/Downloads and open it. It carries the Python
# app's name and so its path there too: each build script refuses to replace the other's build.
#
#   swift/build-app.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"
EXE="StreamingCommunityDownloader"
APP="$HOME/Downloads/StreamingCommunity Downloader.app"
cd "$HERE"

echo "==> Build"
LOC="$(mktemp -d)"
swift build -c release -Xswiftc -emit-localized-strings -Xswiftc -emit-localized-strings-path -Xswiftc "$LOC"
BIN="$(swift build -c release --show-bin-path)/$EXE"

# A string added without its English line shows up in Italian on an English interface, silently.
plutil -convert json -o "$LOC/en.json" "$HERE/Resources/en.lproj/Localizable.strings"
python3 - "$LOC" <<'PY'
import glob, json, os, sys
used = {e["key"] for f in glob.glob(os.path.join(sys.argv[1], "*.stringsdata"))
        for table in json.load(open(f))["tables"].values() for e in table}
missing = sorted(used - set(json.load(open(os.path.join(sys.argv[1], "en.json")))))
for key in missing:
    print(f"   senza inglese: {key}")
PY
rm -rf "$LOC"

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
# The name builds had before, which shares this one's identifier and would leave two of it around.
OLD="$HOME/Downloads/StreamingCommunity Swift.app"
if [[ -x "$OLD/Contents/MacOS/$EXE" ]]; then rm -rf "$OLD"; fi
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/"
cp "$REPO/icon/AppIcon.icns" "$APP/Contents/Resources/"
cp -R "$HERE/Resources/"*.lproj "$APP/Contents/Resources/"  # the interface's languages
cat > "$APP/Contents/Info.plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>local.streamingcommunity.swift</string>
  <key>CFBundleDevelopmentRegion</key><string>it</string>
  <key>CFBundleName</key><string>StreamingCommunity Downloader</string>
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
