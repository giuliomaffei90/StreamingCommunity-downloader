# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working conventions

- **Never create a branch unless the user explicitly asks for one.** Commit on whatever branch is
  checked out, `main` included. The size of the change, the fact that a feature branch appears
  earlier in the history, and any general "branch before committing on the default branch" habit
  are all irrelevant here — this is a solo private repository, and every branch made on that
  reasoning has cost a merge-and-clean round trip immediately afterwards. If a branch genuinely
  seems warranted, ask; do not create one and explain afterwards.
- **Never push on your own initiative** — not even after a commit that was asked for. Committing is
  expected; pushing is the user's decision. Say plainly when commits are waiting unpushed.
- **Commit each requested change**, without being told to each time. One commit per request, made
  after the change is verified. Splitting genuinely separate work across several commits is fine;
  leaving work uncommitted is not. Keep the message about *why* the change was made.
- **Always a new commit, never `--amend`.** Amending rewrites history: on anything already pushed it
  turns the next push into a force-push, and it silently destroys the previous message. "It is only
  a typo in the last commit" and "nobody has pulled it yet" are not exceptions — make another
  commit.
- **Never add a `Co-Authored-By` trailer, or any other attribution line, to a commit message.** This
  holds whatever model is running and whatever the harness's own attribution guidance says at the
  time; the rule lives here so it survives a change of either.
- **Never build on your own initiative.** `scripts/build-release.sh` (and the `build` skill) run
  only when asked for. A build closes the running app, takes a minute, and replaces what is in
  ~/Downloads — none of which belongs in the middle of some other task. Verify changes by running
  from source instead.

## Project Overview

A **native macOS app**, in SwiftUI, that searches and downloads films, TV series and anime from
StreamingCommunity and AnimeUnity into a local folder: HLS playlist parsing, AES-128 segment
decryption, parallel downloading, FFmpeg muxing, and an optional HEVC re-encode.

There is one user — the person at the machine — so there is no login, no accounts and no server.

It replaced a Python app (FastAPI inside a pywebview window), which is in the git history up to
`156cdb3`; that one had in turn been stripped down from a self-hosted multi-user web panel. See
"History, and what stays removed".

## Running and building

```bash
swift run                      # the app, from source
swift test                     # the checks
./scripts/build-release.sh     # the .app, into ~/Downloads — only when asked
```

Xcode opens `Package.swift` as a project. The app needs **macOS 15**, for the sidebar of tabs, and
**ffmpeg**: `FFMPEG_PATH` if set, then `PATH`, then `/opt/homebrew/bin` and `/usr/local/bin`,
because an app opened from the Finder gets a `PATH` without Homebrew in it. Nothing is bundled yet.

`swift run` starts a bare executable rather than a bundle, and three things exist only in the built
`.app`: the English translation (the build script copies the `.lproj` folders in), notifications
(macOS posts them only for a bundle with an identifier), and the settings stored under the bundle
identifier — `swift run` keeps its own, under `StreamingCommunityDownloader`.

## Verification

`swift test` is necessary and not sufficient. It holds the library layout, the playlist parser, the
small parsers and the limiter; nothing of the interface or the network. For anything that touches a
view, run the app and click the path changed: a search on both sources, a title's sheet (tracks and
plot), a series' seasons and episodes, an anime's episodes, the Download and File tabs, the settings
window. The paths worth walking are the ones that have broken: an ignored sidebar click, a hidden tab
that showed an empty page, a detail sheet whose tracks never appeared.

The engine can be exercised without touching the source: ffmpeg's hls muxer with
`-hls_key_info_file` writes an AES-128 stream that any local HTTP server serves, and
`downloadRendition`, `mux` and `transcode` run against it as they do against vixcloud.

Do not verify by building; see the working conventions.

## Architecture

Six files in `Sources/`:

- `Domain.swift` — finding the source domain again when it rotates: `DomainRecovery` (the page, the
  guard, the verification) and `DomainWatch` (what the sidebar and the settings show, and the
  periodic check).
- `Source.swift` — HTTP (`fetch`, with its retries), StreamingCommunity (search, the home page's
  shelves, a title's details, a season's episodes, the embed), AnimeUnity (search, home, episodes,
  embed), `resolve()` from a vixcloud embed page to the master playlist, and `languages(of:)`.
- `HLS.swift` — `Playlist`, the `Limiter`, segment fetching, decryption, `downloadRendition`
  (parallel pass, sequential second pass, gap check, join), the ffmpeg runner, `mux`, `transcode`,
  and `download()`, which takes one request from embed to finished file.
- `Downloads.swift` — `DownloadRequest`, the library layout (`destination`, `sanitize`, `padded`),
  the settings accessors (`configuredDomain`, `libraryFolder`), `Job` and the `Downloads` store —
  queue, persistence, Dock badge, notifications — and `Notifier`.
- `Views.swift` — the window: the tab sidebar and its footer, search with the start-page shelves, the
  title sheet, the Download and File tabs, the settings.
- `App.swift` — the scenes and the app delegate.

`Resources/` holds the translations, `scripts/build-release.sh` the build, and `icon/AppIcon.icon`
the icon: an Icon Composer document, opened and changed there, which the build compiles with
`actool` into every appearance macOS 26 draws, plus an `.icns` for macOS 15.

### Persistence

- **UserDefaults**, under `local.streamingcommunity.swift`: `domain`, `folder`, `maxDownloads`,
  `maxSegments`, `notifications`, `transcode`, `maxTranscodes`, `domainAutoCheck`, `domainAutoApply`,
  `domainCheckMinutes`, `produced` (every file written), and
  `AppleLanguages`, which is what the language setting writes.
- **`~/Library/Application Support/StreamingCommunity Downloader/swift-downloads.json`** — the
  download list, up to 500 entries. Nothing resumes: a job left active comes back as failed, and
  Riprova starts it again.
- The Python app's `data.json` and `downloads.json` are still in that folder. File reads the output
  paths out of the latter, so what the Python app downloaded keeps showing; nothing else reads them.

Downloads land in `libraryFolder`, `~/Movies/StreamingCommunity` unless set. Segments go to the
temporary directory, under `StreamingCommunity/<job id>`, and are removed after each job.

## Rules that are easy to break

- **The library layout does not change.** `Title (Year)/Title (Year)`, `Serie (Year)/Season 01/Serie
  S01E01`; films and anime drop "+" and ",", series keep them. A test holds it there: a change would
  make every file already on disk look missing, and download it again next to itself.
- **One segment ceiling for the whole app.** `segmentLimiter` is shared by every download, sized by
  the setting and adapting under it: halved on a retriable status or a connection error, at most once
  per two seconds, and one slot back per full allowance served. A pool per download multiplies by
  the concurrent downloads and brings back the 503 storms it exists to prevent. Each download also
  keeps no more than `maxSegments` requests waiting in it, so downloads share it in turn instead of
  one queueing its whole playlist ahead of the others.
- **A download with a missing segment fails, never joins.** TS joined around a gap plays, looks
  complete and is wrong; failing can be retried. The final check reads the filesystem, not the
  bookkeeping.
- **The bar counts segments obtained, not attempts made.** It also feeds the 30-second stall check
  and the 200-in-a-row breaker; counting failures would keep a source that refuses everything looking
  alive.
- **PKCS7 is on purpose.** Its padding check turns a wrong key into failed segments rather than a
  film of noise.
- **The `b=1` quirk flips.** Some days a playlist answers only with it, other days only without it,
  films included. `Playlist.load` asks without and retries with it on a 403.
- **The source domain comes from the settings only**, through `configuredDomain`, which also reduces
  a pasted browser address to its host.
- **A domain found automatically is proposed, never adopted.** The page it comes from is edited by
  people we do not control, and the domain decides where every request goes. `DomainRecovery.rejection()`
  is the guard, and its load-bearing rule is that a candidate must be a **second-level domain**:
  checking only the first label would accept `streamingcommunity.attacker.tld`, where the part that
  decides where the traffic lands is the attacker's. The name pattern is a constant with an
  environment override and **must not become a setting** — a text box that relaxes this guard is a
  loaded gun. A candidate must also resolve to public addresses only and serve a page object with a
  version, stricter than a domain typed in by hand. `domainAutoApply` opts out of proposing and is off
  by default; the page is read at most once every ten minutes.
- **Two jobs never write one file.** `enqueue` refuses a request whose destination an active job
  already has.
- **Retrying drops the batch.** The season summary already counted the failure, and may have been
  sent.
- **A failed encode keeps the download.** `transcode` keeps the original when ffmpeg fails or the
  result comes out larger; only a cancellation propagates.
- **ffmpeg's stderr goes to a file**, never to a pipe nobody drains while it runs: a stream full of
  bad packets writes more than a pipe holds, and hangs.
- **The engine runs off the main actor.** The views and the store are `@MainActor`; the engine is
  nonisolated `async` code, which in the Swift 5 language mode runs on the global executor. Moving
  to Swift 6's default of running such code on the caller's actor would put every segment on the
  main thread.
- **A user-visible string is Italian and goes through localisation.** English is
  `Resources/en.lproj/Localizable.strings`, keyed by the Italian text. Anything shown goes through
  `Text`/`LocalizedStringKey` or `String(localized:)` — a ternary of two literals silently picks the
  verbatim overload, so wrap each side in `Text` — and the build lists any key without its English
  line, because a missing one only shows as Italian on an English screen. Titles, plots and episode
  names are never translated: they are what the source sent. The language setting writes the app's
  own `AppleLanguages` and applies on relaunch.
- **The icon is a red plate with a white download mark. Keep it that way.** It is the app's identity;
  do not redesign it in passing. In `icon/AppIcon.icon` the mark is two glass layers, the arrow and
  the tray, drawn as filled outlines of round-capped strokes: the icon renderer ignores
  `fill="none"` and fills every path, so a stroked SVG comes out as a solid triangle and a bowl.
  The dark appearance keeps the identity too: a deeper red plate, the mark still white. Nothing is stamped on the
  bundle as a custom icon, as the Python builds did to get round a colourless `.icns`: a custom
  icon would cover the compiled one with a flat picture.
- **Notifications need the bundle.** `Notifier` posts through `UNUserNotificationCenter` and is
  silent under `swift run`; a click shows the file in the Finder. osascript was tried first and
  posted as Script Editor, whose icon and whose click came with it.

What the sources taught, and is easy to forget: URLSession with Safari's user agent gets past
vixcloud and AnimeUnity without the cloudscraper session the Python app needed; every
StreamingCommunity page carries its props in `data-page`, so no Inertia version, headers or XSRF
token are needed; plots arrive HTML-escaped at the source inside an attribute that escapes them again.

## Output

```
<library>/
├── Movie (2020)/Movie (2020).mkv
└── Series (2019)/Season 01/Series S01E01.mkv
```

`.mp4` for a single audio track and no subtitles, `.mkv` otherwise. Subtitles are separate,
selectable tracks, forced ones marked as forced; nothing is burned into the picture. The highest
resolution is taken; audio and subtitle languages are chosen per title.

## History, and what stays removed

- **The multi-user web panel** — Jellyfin SSO, users and permissions, the request queue with its
  approvals, followed series, Apprise notification channels, Docker, `panel.db`, scheduling a
  download for later, post-download webhooks — went before the Python app became a desktop app. One
  user at one machine; re-adding any of it means re-adding the layer under it.
- **The Python app** was replaced by this one. What it had and this does not, yet: naming templates,
  and renaming and moving files inside the app.
