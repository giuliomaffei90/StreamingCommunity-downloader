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

A **macOS desktop app** that searches and downloads films, TV series and anime from
StreamingCommunity and AnimeUnity into a local folder. It handles M3U8 parsing, AES-CBC segment
decryption, parallel downloading and FFmpeg merging.

It is a FastAPI application inside a window: `desktop.py` starts uvicorn on a background thread and
opens a `pywebview` window pointing at it. There is one user — the person at the machine — so there
is **no login, no permissions layer and no accounts**. Anything that reaches the panel is that
person.

This shape is the result of a deliberate strip. The project used to be a self-hosted multi-user web
panel with Jellyfin SSO, a request queue with approvals, followed series, Apprise notification
channels and a Docker image. All of that is gone; see "What was removed, and why it stays removed".

## Running and building

```bash
pip install -r requirements.txt
python desktop.py          # the app: window + server, one process

pip install -r requirements-dev.txt   # tests and PyInstaller
pytest -q
pyinstaller StreamingCommunity.spec --noconfirm --clean
# -> dist/StreamingCommunity Downloader.app
```

`python main.py` still exists and serves the panel at `http://127.0.0.1:8000` in a browser, without
a window. It is for development, where a browser's devtools beat a webview.

**Prerequisites when running from source:** none beyond the requirements. FFmpeg resolves through
`app.core.ffmpeg_path.get_ffmpeg_exe()` — never call `ffmpeg`/`ffmpeg-python` directly. Order:
`FFMPEG_PATH` env override, then system PATH, then the static binary bundled by `imageio-ffmpeg`.
That last step is what makes the built `.app` work on a Mac with no Homebrew, and it is why
`imageio_ffmpeg` is collected whole in the spec.

`ffprobe` is optional and resolves separately; `imageio-ffmpeg` ships ffmpeg alone, so a bundled app
usually has no ffprobe. Everything that reads it treats `None` as "unknown" rather than failing.

## Verification

```bash
.venv/bin/python -m pytest -q          # the suite
node --check app/static/app.js         # after any change to app.js
```

**A green suite is necessary and not sufficient, and this is not a platitude here.** The tests cover
Python; the two most expensive failures this app has had were invisible to them:

- The episode browser hung on its spinner forever with every test passing, because a call into a
  removed feature threw a `ReferenceError` outside the `try` in `app.js` — no Python involved.
- `GET /api/files` answered 500 with every test passing, because a constant was removed along with
  the block it happened to sit inside.

So for anything touching `app/static/app.js`, `app/templates/index.html` or a router, run the app
and click the path you changed:

```bash
.venv/bin/python main.py               # http://127.0.0.1:8000, a normal browser, devtools work
```

Read the browser console after clicking, not just the page — both failures above were silent on
screen and loud in the console. The paths worth walking, because they are the ones that have broken:
a search, a title's detail modal, **Episodi** on a series and on an anime, the settings modal's
tabs, and the file manager.

Do not verify by building. A build takes a minute, closes the running app and replaces what is in
~/Downloads; running from source shows the same code. See the working conventions above.

## Architecture

### Entry flow

`desktop.py` → uvicorn thread → `app.main:app`, and the main thread goes to `webview.start()`. The
lifespan registers the two job listeners, rebuilds the download list from the ledger and starts
the domain watch loop.

### Layout

**`app/core/`** — source interaction and the download engine
- `page.py` — domain check, search
- `domain_recovery.py` — finds the source domain again when it rotates: scrapes a
  third-party page, guards the candidate, verifies it, and *proposes* it
- `metadata.py` — plot/genres/rating/artwork/trailer, all from the title page's own props,
  behind an in-process TTL cache
- `naming.py` — the file/folder naming templates and their validation
- `film.py` — movie resolve + download; also owns `_collect_audio_tracks` /
  `_collect_subtitle_tracks`, which `tv.py` and `animeunity.py` import
- `tv.py` — seasons, episodes, per-episode languages, episode download
- `animeunity.py` — AnimeUnity search, episodes, download
- `m3u8.py` — `M3U8_Parser`, `M3U8_Segments`, `M3U8_Downloader`, `Decryption`, `download_m3u8()`
- `paths.py` — destination paths (`film_path`, `episode_path`, `anime_path`) and the
  Windows-path guard. Names come from `naming.py`
- `probe.py` — reads which audio and subtitle tracks a file already carries, via ffprobe
- `headers.py` — user-agent rotation, `sanitize_filename`
- `_shared.py` — embed parsing, M3U8 URL/key, `MissingAudioTrackError`, and stream
  resolution (`resolve_stream`, `fetch_key_from_playlist`, `_FALLBACK_PROVIDERS`)

**`app/`**
- `jobs.py` — `JobManager`: thread pool, semaphore, SSE broadcast, retry
- `notify.py` — macOS notifications through osascript
- `downloads_notify.py` — what to say about a finished download, and the batch bookkeeping that
  turns a whole season into one summary
- `config.py` — paths and settings
- `progress.py`, `routers/`, `templates/`, `static/`

**`desktop.py`** — the window. **`StreamingCommunity.spec`** — the bundle.

### Persistence

There is no database. Everything is JSON under
`~/Library/Application Support/StreamingCommunity Downloader/`:

- `data.json` — source domain, download folder, performance settings, domain-recovery switches,
  naming templates. Written only through `config.update_data()`, which holds the
  file lock: a background thread writes `domain` while the user may be saving something else.
- `downloads.json` — the download ledger: what was downloaded, what failed, what was cut short.
  See `app/history.py`.

Downloads land in `config.download_dir()`, defaulting to `~/Movies/StreamingCommunity`. Temp
segments go to `tmp/<job_id>/` under Application Support and are cleaned up afterwards.

`DATA_FILE`, `SCHEDULE_FILE`, `TMP_DIR` and `VIDEOS_DIR` can be overridden by environment variables,
which is how the tests point them at a temporary directory.

## Rules that are easy to break

- **Single process only.** Download job state lives in memory in `JobManager`. `desktop.py` runs
  uvicorn on a thread rather than a subprocess for exactly this reason, and `--workers > 1` would
  leave each worker blind to the others' downloads.
- **The webview owns the main thread.** On macOS the Cocoa event loop must be there, so uvicorn goes
  to the background thread — never the other way round. Its `install_signal_handlers` is overridden
  to a no-op because signal handlers can only be installed from the main thread.
- **The source domain never comes from the client.** Use `app.config.configured_domain()`. The
  window is a browser like any other, and a page it loads must not be able to point the downloader
  at a host of its choosing.
- **Paths are absolute and under Application Support.** A bundled `.app` starts with its working
  directory at `/`, so a relative `data.json` is unwritable. Anything new that persists goes through
  `app.config`, never through a bare relative path.
- **Frozen resources come from `sys._MEIPASS`.** `app/main.py` resolves `BASE_DIR` that way when
  `sys.frozen` is set; `__file__` points inside an archive there and the templates it names do not
  exist as paths.
- **osascript takes arguments, never interpolated strings.** Both `app/notify.py` and the folder
  picker in `app/routers/files.py` pass their text as `argv`. Titles come from the source — someone
  else's database — and a film called `Ocean"s Eleven` interpolated into a quoted AppleScript string
  stops being data and starts being syntax.
- **A batch's expected total is fixed before its first job is submitted**, and every job created
  must reach a terminal listener exactly once — otherwise the batch never closes and its summary
  never fires. That is why `jobs.py` notifies listeners on *every* path out of `_run_download`,
  including the job cancelled before it started.
- **Retrying a job drops its batch link.** `JobManager.retry()` clears `batch_id`: the season
  summary that job belonged to already counted the failure and has been sent, and reporting into it
  a second time would close it early on episodes somebody is still waiting for. The call to repeat
  is recorded in `_run_download`, which every path into the executor goes through.
- **`max_segment_workers` is a process-wide ceiling, not a per-download target.**
  `m3u8.segment_budget()` returns one `AdaptiveLimiter` for the whole app, held around each segment
  request. Sizing a pool per download instead multiplies it by `max_concurrent_downloads` and
  reproduces the 503 storms it exists to prevent. The limiter halves its allowance on pushback
  (`penalise()` on a retriable status or a connection error, once per `PENALTY_INTERVAL`) and climbs
  back one slot per allowance served (`reward()` on a 200) — a non-retriable status teaches it
  nothing, because a verdict is not congestion. `Retry-After` wins over the computed backoff.
  Segments go through the download's pooled `requests.Session`, never a bare `requests.get`.
- **A download with a missing segment must fail, never join.** TS concatenated with gaps produces a
  file that opens, plays, and is wrong — and lands in the library looking like a good one. Failing
  is recoverable because the download can be run again; a silently truncated film is not, because
  nobody knows to. `_require_every_segment()` reads the *filesystem*, not `_failed_segments`: a run
  cut short by the watchdog never attempts the rest, so the bookkeeping is emptiest exactly when
  most of the download is absent.
- **The progress bar counts segments obtained, not attempts made.** It is also the input to the
  stall watchdog (`timer()`), so counting failures as progress does not just misreport — it stops a
  source failing every single request from ever tripping the timeout.
- **A domain found automatically is proposed, never adopted.** The page it comes from is edited by
  people we do not control, and the domain decides where every search, image fetch and download
  referer goes. `domain_recovery.is_plausible()` is the guard, and its load-bearing rule is that a
  candidate must be a **second-level domain**: checking only the first label would accept
  `streamingcommunity.attacker.tld`, where the part that decides where the traffic lands is the
  attacker's. The name pattern is a module constant with an env override and **must not become a
  settings field** — a text box that relaxes an SSRF guard is a loaded gun. `verify()` is
  deliberately stricter than `PUT /api/domain`, which accepts an empty version string: a person
  typing a host in is making a decision, a web page is not. `domain_auto_apply` opts out of all of
  this and is off by default.
- **Title metadata has one provider and needs no credential.** It comes from the title page's own
  props — the payload already fetched to find `tmdb_id` — so it costs no request of its own. Two
  other providers were tried and removed after being measured: the site's `/api/titles/preview`
  answers 419 (Laravel CSRF) to every request and never once worked, while TMDB turned out not to be
  an upgrade — the site copies its synopses from TMDB, so the text was usually identical, and the
  round trip *lost* a trailer on one title, a logo on another and 1100 characters of plot on a
  third. Do not re-add a provider without measuring it against the props on real titles first.
- **`metadata.cached_tmdb_id()` never does I/O.** A stream fallback would read it at download time,
  and a download that is about to succeed must not pay a round trip to discover a fallback it will
  not use.
- **When stream resolution has nothing to fall back to, the primary error must survive.**
  `_FALLBACK_PROVIDERS` is empty: a second road through vixsrc was built and removed, because that
  site is now a client-rendered app whose HTML carries no playlist, token or `.m3u8` at all.
  `resolve_stream()` is the seam a replacement plugs into, and the resolution context (`tmdb_id`,
  media type, season, episode) is already threaded from every caller. A user told "no alternative
  source" when the real failure was Cloudflare has been sent to debug the wrong thing, so the
  original exception is re-raised unchanged. AnimeUnity is excluded on purpose: no TMDB id,
  different embed host.
- **Changing a naming template must not hide files already in the library.** `naming.render()` never
  raises — it runs inside a download, after the bytes are fetched — so everything it would paper
  over is refused by `naming.validate()` at save time. Never `str.format` a user template:
  `{title.__class__}` leaks attributes and a stray `{` raises mid-download.
- **A user-visible string is Italian, and goes through the translation.** The interface has two
  languages (`app/static/i18n.js`), keyed by the Italian source string: text in `index.html` is
  translated by a DOM walk at load, and anything `app.js` builds has to be wrapped in `t()` — a
  string added without it simply stays Italian on an English page, silently, with every test still
  green. Counted strings take a `{n}` placeholder rather than being glued together, because English
  does not always put the number in the same place, and two Italian words that are spelled the same
  but translate differently are told apart with a `|context` suffix on the key. Titles, plots and
  episode names are never translated: they are what the source sent, not interface.
- **Never `confirm()`, `alert()` or `prompt()` in the frontend.** Confirmations go through
  `scConfirm()` and text entry through `scPrompt()` in `app/static/app.js`, which resolve a Promise
  from a Tabler modal. A browser dialog ignores the theme and cannot be styled — and inside a
  webview it looks like the app itself has crashed into a system alert.
- Blocking work goes through `asyncio.to_thread` (routers) or the job pool. The folder picker is the
  starkest case: it blocks until a human answers a dialog.

## What was removed, and why it stays removed

Re-adding any of these means re-adding the layer under it, which is the actual cost:

- **Jellyfin SSO, sessions, users, permissions.** One user at one machine. Every `/api` route is
  reachable by whoever has the window; there is no `require(...)` to add a decision to.
- **The request queue.** Approvals only mean something when the approver and the requester are
  different people.
- **Followed series.** It worked by turning a new episode into a *request*, so it went with the
  queue. Re-adding it means giving the poller its own path to submit jobs, plus the "already in the
  library" check that used to live in the request resolver.
- **Apprise notification channels.** Replaced by `app/notify.py`. Apprise also loads its plugins
  dynamically, which is the single worst thing to hand PyInstaller.
- **Docker, the compose templates, the ghcr workflow.** The deliverable is a `.app`.
- **`panel.db` and `app/db.py`.** Every table was `jf_*`, and the one that outlived the strip — the
  download hooks — has since gone too.
- **Scheduling a download for later.** A `datetime-local` next to the action button, a
  `schedule.json` store, a 30-second scheduler loop, `POST /api/download/schedule/{film,episode,
  anime}`, a `scheduled` job status with its own badge and a "run it now" button. Removed on
  request: it was not used. Note that `history.py` and `jobs.restore_from_history()` still accept
  `scheduled` as an incoming status — ledgers written before the removal carry it, and those rows
  still have to be closed. That is the only place the word should appear.
- **Post-download webhooks.** They existed to tell Jellyfin to rescan. With Jellyfin gone the
  remaining use was "say when a download finished", which `app/notify.py` already does natively.

## Output layout

```
<library>/
├── Movie (2020)/Movie (2020).mp4
└── Series (2019)/Season 01/Series S01E01.mp4
```

Subtitles land beside the video as `{stem}.{lang}.vtt`. The extension is `.mp4` for a single audio
track and `.mkv` once there is more than one.

## Quality and languages

Highest available resolution is chosen automatically (1080p → 720p → 480p → 360p). Audio and
subtitle languages are chosen per download.

## vixcloud.co quirk

TV episode M3U8 URLs sometimes return 403; appending `?b=1` (or `&b=1`) resolves it. Handled in
`_fetch_text_with_b1_fallback` and `_collect_audio_tracks`.

## The Swift port (`swift/`)

An experiment: the same app rewritten as a native SwiftUI program, beside the Python one rather
than in place of it. `cd swift && swift run` opens it, `swift test` runs its checks, and Xcode opens
`swift/Package.swift` as a project. `swift/build-app.sh` builds a release `.app` into ~/Downloads and
opens it — a build, so only when asked, like the Python one. It has the Python app's name, and so
its path: each build script refuses to replace the other's build. It needs
macOS 15, for the sidebar of tabs, and ffmpeg installed (Homebrew): nothing is bundled yet.

It shares only the library layout with the Python app: `destination()` reproduces the default naming
templates exactly, and a test holds it there, so both apps fill one library. Settings live in
UserDefaults, the download list in `swift-downloads.json` in the same Application Support folder.

Not ported, on purpose: naming templates, domain recovery and the English translation — every `Text`
is a `LocalizedStringKey`, so that one is a String Catalog away. The File tab lists what either app
downloaded, with open, reveal and trash; renaming and moving are left to the Finder.

Learnt while porting, and true of the Python app as well:
- URLSession with Safari's user agent gets past vixcloud and AnimeUnity without cloudscraper.
- Every StreamingCommunity page carries its props in `data-page`, so search results, a title and a
  season read without the Inertia version, the X-Inertia headers or the XSRF token.
- The `b=1` quirk flips: some days a playlist answers only with it, other days only without it,
  films included. `Playlist.load` asks without and retries with it on a 403, as `_fetch_m3u8` does.
- Plots are HTML-escaped at the source, inside a page attribute that escapes them a second time.
