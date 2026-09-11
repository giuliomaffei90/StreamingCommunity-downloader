---
name: release
description: Publish a GitHub release of StreamingCommunity Downloader — version, notes, tag and DMG. Use when the user asks to release, publish or cut a version, or says /release.
---

# Release

The conventions are the ones the user keeps in their other projects.

## Versioning

- Check the latest tag (`git tag --sort=-v:refname | head -1`) and the fork's releases before
  choosing the next version.
- Not semantic versioning:
  - **Major (X)** — only when the user asks for it, however large the release.
  - **Minor (Y)** — real features, something a user would call "a feature".
  - **Patch (Z)** — fixes and small additions: scoped improvements, UI polish, doc-only changes.
- **Propose X.Y.Z and its bucket, and wait for the go-ahead before tagging.**
- The version lives in `VERSION` at the top of `scripts/build-release.sh`, which writes it into the
  bundle. Bump it in the commit that cuts the release, and tag `vX.Y.Z` to match.

## Notes

- Everything since the previous release (`git log vPREV..HEAD`), not just the last commit, grouped
  into user-facing bullets. A bug that came and went between two releases is not news.
- English, past tense: Added, Improved, Fixed, Refined, Updated, Removed. Concise and about the
  product; process detail only when it changes the app or how it is installed.
- No `## Verification` or `## Assets` section: GitHub already lists the assets.

```markdown
## Changes
- Added ...
- Improved ...
- Fixed ...

## Notes
- Needs macOS 15 or later on Apple silicon.
- The app is signed ad hoc and not notarized, so macOS blocks its first launch: open System
  Settings → Privacy & Security and choose *Open Anyway*.
- The source domain isn't shipped with the app, because it changes every few weeks: set it in
  Settings on first launch.

> [!IMPORTANT]
> Downloads need ffmpeg, which isn't bundled. Install it with Homebrew before the first download:
> `brew install ffmpeg`.
```

The `[!IMPORTANT]` block is a GitHub alert: its own block after a blank line, never inside a bullet,
and worded the same each release. Drop it once ffmpeg is bundled.

## Publishing

The repository is the fork, `giuliomaffei90/StreamingCommunity-downloader` (`origin`). `upstream` is
the original author's, and gh has no default repository here: **always pass `--repo`**. The fork
numbers its releases on its own, from v1.0.0. Upstream's tags (its own v1.0.0 to v2.2.0) were
deleted from the fork, and `remote.upstream.tagopt --no-tags` keeps a fetch from bringing them back.

It is built and uploaded from this Mac rather than in CI: the icon needs Xcode 26's `actool`, and the
DMG is a few megabytes.

1. Bump `VERSION`, commit, push `main`.
2. Write the notes to a file in the scratchpad.
3. `./scripts/build-release.sh` — the release is what was asked for, so it covers the build.
4. The DMG, with an Applications link to drag onto:
   ```bash
   STAGE="$(mktemp -d)"
   ditto "$HOME/Downloads/StreamingCommunity Downloader.app" "$STAGE/StreamingCommunity Downloader.app"
   ln -s /Applications "$STAGE/Applications"
   hdiutil create -volname "StreamingCommunity Downloader" -srcfolder "$STAGE" -ov -format UDZO \
     "<scratchpad>/StreamingCommunity Downloader-X.Y.Z.dmg"
   ```
5. Tag with the notes as its message, and push the tag. `--cleanup=verbatim` is required: without
   it git strips every `## ` line from the message as a comment.
   ```bash
   git tag -a vX.Y.Z -F <notes> --cleanup=verbatim
   git push origin vX.Y.Z
   ```
6. ```bash
   gh release create vX.Y.Z --repo giuliomaffei90/StreamingCommunity-downloader --verify-tag \
     --title "StreamingCommunity Downloader X.Y.Z" --notes-file <notes> "<dmg>"
   ```
7. Read it back with `gh release view vX.Y.Z --repo …`: headings, version, the DMG attached.
