#!/usr/bin/env bash
#
# Build the release .app, put it in ~/Downloads and open it.
#
#   ./scripts/build-release.sh
#
# The tests go first: this closes the running app, and a red run should not close it for nothing.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXE="StreamingCommunityDownloader"
APP="$HOME/Downloads/StreamingCommunity Downloader.app"
cd "$REPO"

echo "==> Test"
if ! out="$(swift test 2>&1)"; then echo "$out"; exit 1; fi
echo "$out" | grep -E "Executed [0-9]+ tests" | tail -1

echo "==> Build"
LOC="$(mktemp -d)"
swift build -c release -Xswiftc -emit-localized-strings -Xswiftc -emit-localized-strings-path -Xswiftc "$LOC"
BIN="$(swift build -c release --show-bin-path)/$EXE"

# A string added without its English line shows up in Italian on an English interface, silently.
plutil -convert json -o "$LOC/en.json" "$REPO/Resources/en.lproj/Localizable.strings"
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
if pgrep -f "/$EXE( |$)" >/dev/null; then
  echo "   chiusa, attendo che esca"
  pkill -f "/$EXE( |$)" || true
  for _ in $(seq 1 25); do pgrep -f "/$EXE( |$)" >/dev/null || break; sleep 0.2; done
else
  echo "   nessuna in esecuzione"
fi

echo "==> Bundle"
# Only ever replace a previous build of this app. Anything else with the name — a build of the
# Python app this one replaced, say — is somebody's file, and this script does not get to decide.
if [[ -e "$APP" && ! -x "$APP/Contents/MacOS/$EXE" ]]; then
  echo "   «$APP» esiste e non è una build di quest'app. Rimuovilo a mano." >&2
  exit 1
fi
rm -rf "$APP"
# The name early builds had, which shares this one's identifier and would leave two of it around.
OLD="$HOME/Downloads/StreamingCommunity Swift.app"
if [[ -x "$OLD/Contents/MacOS/$EXE" ]]; then rm -rf "$OLD"; fi
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/"
cp "$REPO/icon/AppIcon.icns" "$APP/Contents/Resources/"
cp -R "$REPO/Resources/"*.lproj "$APP/Contents/Resources/"  # the interface's languages
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
  <key>LSMinimumSystemVersion</key><string>15.0</string>
</dict></plist>
EOF
codesign --force --deep -s - "$APP"
# The .icns alone comes out colourless on this system — the red plate turns black, for reasons
# chased a long way and never found. A custom icon resource, which is what the Finder's Get Info
# paste writes, is honoured without any of that. The paths travel as arguments, not as script.
osascript -l JavaScript -e 'function run(argv) {
  ObjC.import("AppKit");
  const image = $.NSImage.alloc.initWithContentsOfFile(argv[0]);
  return $.NSWorkspace.sharedWorkspace.setIconForFileOptions(image, argv[1], 0);
}' "$REPO/icon/icon.png" "$APP" >/dev/null || echo "   (icona non applicata)"

SIZE="$(du -sh "$APP" | cut -f1)"
echo
echo "Pronta: $APP · $SIZE"
echo "Firmata ad hoc: sul tuo Mac si apre normalmente, altrove serve tasto destro > Apri."

echo
echo "==> Avvio"
open "$APP"
