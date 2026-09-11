---
name: build
description: Build the release .app of StreamingCommunity Downloader and put it in ~/Downloads. Use when the user asks to build, package, compile or release the app, produce a new .app, or says /build.
---

# Build the release app

Run the script. It does everything and stops at the first thing that is wrong:

```bash
./scripts/build-release.sh
```

It runs the tests, builds the release binary, lists any interface string that has no English line,
closes any running instance of the app, assembles the bundle in `~/Downloads`, stamps the icon on
it and opens it.

Do not filter the script's output down to the last few lines: the "Chiusura istanze" line and any
"senza inglese" line are worth reporting, and get lost that way.

## Report back

- Where it landed and its size — the script prints both.
- That it is now running, since the script opens it.
- That a running instance was closed, if the script said so — a download that was in flight did not
  survive it.
- Any string listed "senza inglese": it shows in Italian on an English interface until it gets its
  line in `Resources/en.lproj/Localizable.strings`.
- That it is signed ad hoc: on this Mac it opens normally, elsewhere it needs right-click → Open the
  first time.

## When it fails

**Tests red.** Nothing was built. Report the failures; do not build around them by editing the
script.

**"esiste e non è una build di quest'app".** Something else sits at the app's path in `~/Downloads`
— an old build of the Python app, for instance. Tell the user; do not delete it yourself.

## The icon

`icon/AppIcon.icns` is committed and the build just reads it. It is regenerated only when the icon
itself changes, with `python icon/make_icon.py` — Python and Pillow as a development tool for that
one file; neither the app nor its build needs them.
