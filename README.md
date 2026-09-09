# StreamingCommunity Downloader

A macOS app that searches and downloads films, TV series and anime from StreamingCommunity and
AnimeUnity. Open it, download, close it: no browser, no terminal, no server to start by hand.

Fork of [EdoardoFiore/StreamingCommunity-downloader](https://github.com/EdoardoFiore/StreamingCommunity-downloader),
a self-hosted multi-user web panel. This fork keeps the download engine and rebuilds everything
around it as a single-user desktop app — see [What this fork changed](#what-this-fork-changed).

The interface is in Italian.

---

## What it does

- Search and download films, TV series and anime, with filters by kind and an Italian-dub-only
  filter for anime
- **Recovers the source domain on its own** when it rotates: finds it, verifies it, and proposes it
- Plot, genres, rating, artwork and trailer on the title page — read from the page's own payload,
  so no API key and no extra request
- Automatic quality selection (1080p → 720p → 480p → 360p)
- Parallel HLS segment download with AES-CBC decryption, backing off on its own when the source
  starts refusing
- Multiple audio tracks merged with FFmpeg, `.vtt` subtitles downloaded alongside
- Real-time progress, phase by phase (video → audio → merge), and on the Dock icon
- The download list survives a restart, and a failed download can be **retried from the list**
  without searching again
- Optional **HEVC re-encode after download**, on a queue counter of its own
- Built-in file manager, with video streaming and free space on the volume
- Notification Center notification when a download lands — one single summary for a whole season
- Configurable file and folder naming templates

---

## Installing

Download the `.app`, drag it into Applications, open it.

On first run, set the **source domain** in **Impostazioni → Sorgente**: it is not shipped with the
app, because it changes every few weeks.

The app is not signed with an Apple developer account, so the first launch of a downloaded copy
needs **right click → Open**. An `.app` you built yourself opens normally.

### Building it

Python ≥ 3.11.

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
./scripts/build-release.sh
```

The script runs the tests, builds, checks the bundle has everything it needs, and leaves the app in
`~/Downloads`. Around 110 MB, self-contained: it carries its own Python and a static FFmpeg, so the
Mac running it needs nothing installed.

To build without installing or testing: `pyinstaller StreamingCommunity.spec --noconfirm --clean`,
which leaves the result in `dist/`.

The icon lives in `icon/AppIcon.icns`, already compiled; regenerate it with `python icon/make_icon.py`.

### Running from source

```bash
pip install -r requirements.txt
python desktop.py
```

`python main.py` serves the panel at `http://127.0.0.1:8000` in an ordinary browser instead, with no
window — handy for development, where a browser's devtools beat a webview.

---

## Where things land

Downloads go where you tell them, in **Impostazioni → Download**: one destination folder, picked
with the native chooser or by pasting a path. It is also the folder the file manager shows, so what
you download is always where you are looking. Unconfigured, it is `~/Movies/StreamingCommunity`.

The app's own settings live in `~/Library/Application Support/StreamingCommunity Downloader/`.

The folder structure follows the layout recommended by the
[Jellyfin documentation](https://jellyfin.org/docs/general/server/media/movies/), which is also the
one Plex and Infuse recognise with no configuration:

```
<library>/
├── Movie (2020)/
│   ├── Movie (2020).mkv
│   └── Movie (2020).en.vtt
└── Series (2019)/
    └── Season 01/
        ├── Series S01E01.mkv
        └── Series S01E02.mkv
```

The extension is `.mp4` with a single audio track and `.mkv` once there is more than one, which is
what it takes to carry several in one file.

---

## When the source moves

The domain changes every few weeks, and until recently that stopped everything without explaining
why. Now the app notices, reads the current address off a public page, checks that it really serves
the source, and shows a banner proposing the change.

**Proposes, does not apply.** That page is written by people we do not control, and the domain
decides where every request ends up. Only second-level domains with a recognisable name are
considered, and only if they answer the way the source is expected to. **Impostazioni → Sorgente**
has a switch to apply without asking — off unless you turn it on — and a "check now" button.

---

## When the stream will not resolve

Video goes through the source's embed page, which sits behind Cloudflare and sometimes refuses. When
that happens the title page says so immediately, instead of leaving you a button that looks fine and
a download that fails ten minutes later.

---

## Re-encoding

Off by default. It follows the HandBrake "Plex" preset — x265, constant quality 26, capped at 1080p
without upscaling — and buys about a third of the file size for about a third of the running time in
CPU. The source arrives already compressed at roughly 1.5 Mbps, so re-encoding wins space and never
quality; if the result comes out larger than the original, the original is kept.

---

## What this fork changed

The original is a **self-hosted web panel**: a server several people reach over the network, running
in Docker, with a Jellyfin instance next to it. This fork is a **macOS app for one person**, and
most of what is gone was gone for the plainest of reasons — it was never used here. None of it is a
defect in the original: it is what a shared service needs and a local window does not.

**The whole Jellyfin integration is gone.** The original could log you in with Jellyfin credentials,
take a library path, refresh the library when a download landed, and fire a webhook telling it to
rescan. None of that was ever used, and unused code is not free: it has to be carried, frozen into
the bundle, and kept working.

Jellyfin *as a media server* is untouched. The output layout still follows its recommended
convention, so pointing Jellyfin, Plex or Infuse at the download folder works exactly as before.
What went away is the app talking to it.

**Accounts, permissions and the request queue went with the login.** An approval means something
only when the approver and the requester are different people; here they are the same person.
**Following a series** went too, because it worked by turning each new episode into a *request* —
without the queue it has nowhere to file what it finds.

**Docker, the compose templates and the ghcr workflow are gone.** The deliverable is a `.app`, and
the things this app does are the things a container cannot: open a window, put a progress bar on the
Dock icon, post to Notification Center, and open the native folder picker.

**Apprise notification channels became native notifications.** Discord, Telegram and ntfy exist to
reach someone who is not at the machine; the user of this app is at the machine, so `app/notify.py`
posts to Notification Center instead. Apprise also loads its plugins dynamically, which is the worst
possible shape for a PyInstaller bundle to freeze.

**`panel.db` and the database layer are gone.** Every table in it was `jf_*`. What is left is JSON
under Application Support: settings in `data.json`, the download ledger in `downloads.json`.

**Scheduling a download for later was removed**, also unused.

---

## Notes

One process, always: download state lives in memory. The server listens on `127.0.0.1` only and has
no login in front of it — it is a window onto a local process, not a service to expose on a network.

## Licence

MIT, as the original. See [LICENSE](LICENSE).
