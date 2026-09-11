# StreamingCommunity Downloader

A native macOS app that searches and downloads films, TV series and anime from StreamingCommunity and
AnimeUnity. Open it, download, close it.

Fork of [EdoardoFiore/StreamingCommunity-downloader](https://github.com/EdoardoFiore/StreamingCommunity-downloader),
a self-hosted multi-user web panel. This fork is a single-user Mac app written in SwiftUI — see
[What this fork changed](#what-this-fork-changed).

The interface is in Italian or English, chosen in **Impostazioni** / **Settings**.

---

## What it does

- Search films, TV series and anime, filtered by kind, with an Italian-dub-only filter for anime, a
  page of results at a time
- **Finds the source domain again when it rotates**: reads the current one off a public page, checks
  it really serves the source, and proposes it
- A start page with what each source puts on its front page: trending, recently added, today's top
  ten, the latest anime episodes
- Plot, genres, rating and trailer for each title, and its audio and subtitle languages to choose
  from
- Whole seasons, whole series or every episode of an anime in one go
- Highest available quality, parallel segment download with AES-128 decryption, backing off on its
  own when the source starts refusing
- Several audio tracks and the subtitles muxed into one file as selectable tracks
- Progress step by step, in the list and on the Dock icon; a failed download can be retried from the
  list
- An optional HEVC re-encode after each download
- A File tab with what was downloaded, the free space on the volume, open, show in Finder, move to
  Trash
- A notification when a download lands — one summary for a whole season — that shows the file when
  clicked

---

## Installing

It needs **macOS 15** and **ffmpeg**:

```bash
brew install ffmpeg
```

Then download the DMG from [Releases](https://github.com/giuliomaffei90/StreamingCommunity-downloader/releases)
and drag the app into Applications. It is signed ad hoc and not notarized, so macOS blocks its first
launch: open **System Settings → Privacy & Security** and choose **Open Anyway**.

Or build it:

```bash
./scripts/build-release.sh
```

The script runs the tests, builds, and leaves the app in `~/Downloads` and opens it. On the Mac that
built it, it opens normally.

On first run, set the **source domain** in the settings: it is not shipped with the app, because it
changes every few weeks. The footer of the sidebar shows it in green while it answers and in red once
it stops; when it moves, the app looks the new one up, and proposes it there once it has checked it
really serves the source. It never adopts one on its own unless told to in the settings, since the
page it reads is edited by people nobody here controls. macOS also asks, once, whether the app may
post notifications.

### From source

```bash
swift run
swift test
```

Xcode opens `Package.swift` as a project. Run this way it speaks Italian only and posts no
notifications: both need the built bundle.

---

## Where things land

In the folder chosen in the settings, `~/Movies/StreamingCommunity` unless changed, laid out the way
the [Jellyfin documentation](https://jellyfin.org/docs/general/server/media/movies/) recommends and
Plex and Infuse recognise with no configuration:

```
<library>/
├── Movie (2020)/
│   └── Movie (2020).mkv
└── Series (2019)/
    └── Season 01/
        ├── Series S01E01.mkv
        └── Series S01E02.mkv
```

The file is `.mp4` with a single audio track and no subtitles, and `.mkv` otherwise.

---

## Re-encoding

Off by default. It follows HandBrake's "Plex" preset — x265, constant quality 26, capped at 1080p
without upscaling — and buys about a third of the file size for about a third of the running time in
CPU. If the result comes out larger than the original, the original is kept.

---

## What this fork changed

The original is a **self-hosted web panel** for several people, run in Docker next to a Jellyfin
instance. This fork first became a Python desktop app for one person — the accounts, the request
queue, the Jellyfin integration and Docker went, unused — and was then rewritten as a **native macOS
app**: SwiftUI instead of a web page in a window, URLSession instead of a Python HTTP stack, the
system's own notifications, settings window, folder picker and Finder.

---

## Licence

MIT, as the original. See [LICENSE](LICENSE).
