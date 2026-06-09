# Release notes

## ⚡ How to install (read this first)

For first-time users — see [README.md](README.md#中文--安裝跟使用) for the full
bilingual one-pager (中文 + English) with screenshots-worth of detail.

**Mac TL;DR:**

```bash
# 1) Drag ReelsAIEditor.app into /Applications, then open Terminal and run:
xattr -dr com.apple.quarantine /Applications/ReelsAIEditor.app
# 2) Done. Open the app from Launchpad like any other. Browser auto-opens.
```

**Windows TL;DR:**

```
1) Unzip the .zip
2) Double-click ReelsAIEditor.exe
3) "More info" → "Run anyway" when SmartScreen pops the first time
```

---

## v1.1.0 — 2026-06-10

Three platform binaries attached. All three actively maintained from this
release forward (the Intel/Win freeze policy from v1.0 is rescinded).

| Download | Platform | Status |
|---|---|---|
| `ReelsAIEditor-macOS-arm64.dmg` | macOS · Apple Silicon (M1/M2/M3/M4) | **Actively maintained** |
| `ReelsAIEditor-macOS-intel.dmg`  | macOS · Intel CPU (pre-2020 Mac)   | Updated for v1.1 |
| `ReelsAIEditor-Windows-x64.zip`  | Windows 10 / 11                    | Updated for v1.1 |

### What's new

**Speed (Apple Silicon)**
- mlx-whisper-medium (Metal GPU + Neural Engine) replaces faster-whisper for
  both ZH transcription AND ZH→EN translation
- h264_videotoolbox hardware encoder replaces libx264 medium
- ~150 s end-to-end on a 3-min talking-head clip

**Content-aware POV hook**
- Burnt-in title is picked from your actual transcript using 10 hook
  patterns (numbered list, question, contrarian, mistake, secret,
  time-promise, authority, emotion, urgency, topic anchor)
- Hard completeness gate: incomplete fragments ("能不能夠…") are rejected
- Hard filler veto: 好啦/嗯/OK/test openers can't become the hook
- Title is always 2 lines in 2 colors; both lines are independent
  complete concepts

**Editable subtitles**
- Verification table under the output video: `[time]  ZH text  |  EN text`
  per row, click time to seek, click cell to edit
- "套用字幕修改" re-burns the video in ~30 seconds
- All other buttons greyed out during the re-burn

**Per-language sessions**
- Chinese page and English page each remember their own finished result
- ZH → EN → ZH round trip preserves the original ZH result

**Cover styles**
- Removed `繽紛大字` / Color Pop (only Editorial Bold and All-White Hook remain)
- All-White Hook in-video title accent + EN subtitle are pure white now

**Subtitle quality**
- Hard `_verify_subtitle_layout()` assertion in pipeline: ZH and EN
  subtitles never visually overlap
- EN can wrap to 2 lines without colliding with ZH 2-line case
- ASCII words containing punctuation (`OK,CheckCheck`) stay atomic
- Fullwidth `ＡＩ` auto-converts to halfwidth `AI`
- No 1-3 char orphans on the bottom line
- Silence detection tuned for Chinese: only cuts pauses > 0.74 s with
  280 ms padding on each side

**UX**
- Top dropzone clickable while a result is showing → auto-resets first
- Re-uploading the same file works (Safari quirk handled)
- Open Video / Open Cover open in new tab for preview
- Double-clicking the .app icon while running no longer opens new tabs
- Stale jobs (15-min cleanup) no longer flash "找不到這個任務" on page load

**Build hygiene**
- `REGRESSION_CHECKLIST.md` and `scripts/smoke_test.sh` (12 automated
  gates including a lock for the "能不能夠" incomplete-sentence regression
  so it can never come back)

---

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
