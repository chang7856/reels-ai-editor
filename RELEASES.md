# Release notes

## v1.0.0 — 2026-05-30

First public release. Three platform binaries are attached to the GitHub Release.

| Download                              | Platform                          | Status                                  |
|---------------------------------------|-----------------------------------|-----------------------------------------|
| `ReelsAIEditor-macOS-arm64.dmg`       | macOS · Apple Silicon (M1/M2/M3/M4)| **Actively maintained** — future updates ship here |
| `ReelsAIEditor-macOS-intel.dmg`       | macOS · Intel CPU (pre-2020 Mac)  | **Final at v1.0** — will not be updated again |
| `ReelsAIEditor-Windows-x64.zip`       | Windows 10 / 11                   | **Final at v1.0** — will not be updated again |

### Why only Apple Silicon gets updates

The author runs an Apple Silicon Mac. Cross-platform builds for Intel Mac
and Windows are published once at v1.0 as a one-shot courtesy snapshot.
Future updates target Apple Silicon only.

### What's in v1.0.0

- Talking-head video → auto-edited vertical IG Reel (720×1280)
- Whisper-based transcription with sentence-by-sentence subtitles
- Three cover styles: Editorial Bold / All-White Hook / Color Pop
- Bilingual (ZH + EN) mode on the Chinese page, English-only on the English page
- IG Reels safe-area aware text positioning
- 15-minute auto-deletion of uploads + outputs
- Cloudflare Tunnel one-click sharing (`share-tunnel.command`)
- ZH ↔ EN UI toggle
- PM-style flow: Cover Style locks once a Reel is generated, only the bottom
  switcher can change it until the user starts a new upload

### Known caveats

- macOS will show "developer cannot be verified" on first launch — right-click
  the .app and choose "Open" to bypass once.
- First run downloads the Whisper `small` model (~470 MB).
- `ffmpeg` and `ffprobe` are bundled inside the .app — no separate install
  required. (This was a fix released the same day after the original v1.0
  shipped without them and required `brew install ffmpeg`.)
- Intel Mac builds run noticeably slower than Apple Silicon for transcription
  (3–5×).

### License

MIT. See [LICENSE](LICENSE).
