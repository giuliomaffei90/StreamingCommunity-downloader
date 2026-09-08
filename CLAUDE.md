# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working conventions

- **Work directly on `main`.** Do not create a branch unless explicitly asked for one. This is a
  solo private repository with no collaborators, so a branch buys nothing and costs a
  merge-and-clean round trip afterwards.
- **Never push on your own initiative** — not even after a commit that was asked for. Committing is
  expected; pushing is the user's decision. Say plainly when commits are waiting unpushed.
- **Commit each requested change**, without being told to each time. One commit per request, made
  after the change is verified. Splitting genuinely separate work across several commits is fine;
  leaving work uncommitted is not.
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

## Architecture

### Entry flow

`desktop.py` → uvicorn thread → `app.main:app`, and the main thread goes to `webview.start()`. The
lifespan registers the two job listeners, loads the schedule store and starts the domain watch loop.

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
- `schedule.py`, `progress.py`, `routers/`, `templates/`, `static/`

**`desktop.py`** — the window. **`StreamingCommunity.spec`** — the bundle.

### Persistence

There is no database. Everything is JSON under
`~/Library/Application Support/StreamingCommunity Downloader/`:

- `data.json` — source domain, download folder, performance settings, domain-recovery switches,
  naming templates. Written only through `config.update_data()`, which holds the
  file lock: a background thread writes `domain` while the user may be saving something else.
- `schedule.json` — scheduled downloads

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
  including the job cancelled before it started, and why `cancel()` notifies for a job still
  `scheduled` that the executor never saw.
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
