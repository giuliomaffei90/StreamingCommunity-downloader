---
name: build
description: Build the release .app of StreamingCommunity Downloader and put it in ~/Downloads. Use when the user asks to build, package, compile or release the app, produce a new .app, or says /build.
---

# Build the release app

Run the script. It does everything and stops at the first thing that is wrong:

```bash
./scripts/build-release.sh
```

It runs the tests, closes any running instance of the app, builds
`StreamingCommunity.spec`, checks the bundle actually contains what it needs,
and copies the result over whatever is in `~/Downloads`.

## Report back

- Where it landed, its version and its size — the script prints all three.
- That a running instance was closed, if the script said so — a download that
  was in flight did not survive it.
- That it is unsigned: on this Mac it opens normally, elsewhere it needs
  right-click → Open the first time.

## When it fails

**Tests red.** Nothing was built. Report the failures; do not build around them
by editing the script.

**A missing-file check failed.** The bundle built but something is not in it.
Almost always a data file or a dynamically imported module that PyInstaller's
analysis cannot see — the fix goes in `StreamingCommunity.spec`, in `datas` or
`hiddenimports`, not into the build script. `StreamingCommunity.spec` explains
the three that already exist and why.

**The app builds but the window is blank.** `webview` injects its own
JavaScript from files beside the module; that is why the spec collects it whole.
Check that `collect_all("webview")` is still there.

## The icon

`icon/AppIcon.icns` is committed and the build just reads it. It is regenerated
only when the icon itself changes:

```bash
python icon/make_icon.py
```

That needs Pillow, which is a development dependency — the build must never
require it.
