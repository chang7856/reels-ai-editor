<p align="center">
  <img src="assets/icon-1024.png" width="160" alt="Reels AI Editor">
</p>

<h1 align="center">Release notes</h1>

## ⚡ How to install (read this first)

For first-time users — see [README.md](README.md#中文--安裝跟使用) for the full
bilingual one-pager (中文 + English).

**Mac TL;DR — no Terminal needed, even on macOS 15 (Sequoia):**

```
1) Open the .dmg → drag ReelsAIEditor into Applications
2) FIRST launch: double-click → "Apple could not verify" warning → click DONE
3) Open System Settings → Privacy & Security → scroll down
4) Find "ReelsAIEditor was blocked..." → click "Open Anyway" → confirm with password / Touch ID
5) Browser auto-opens. From now on, just click the icon like any other app.
```

> Why? Apple charges \$99/yr for a developer cert and I didn't pay it, so Gatekeeper blocks unsigned apps. **macOS 15 Sequoia removed the old "right-click → Open" button**, so the System Settings flow above is now the _only_ no-Terminal path. One-time, permanent whitelist for your user account.
>
> On older **macOS 13 / 14** you have a shorter path: right-click `/Applications/ReelsAIEditor` → Open → the warning gets an extra "Open" button. Sequoia stripped that button.
>
> If System Settings doesn't even show the blocked-app line (rare): `xattr -dr com.apple.quarantine /Applications/ReelsAIEditor.app` in Terminal is the nuclear option.

**Windows TL;DR:**

```
1) Unzip the .zip
2) Double-click ReelsAIEditor.exe
3) "More info" → "Run anyway" when SmartScreen pops the first time
```

---

## v1.1.0 — 2026-06-25

Three platform binaries attached. All three actively maintained from this
release forward (the Intel/Win freeze policy from v1.0 is rescinded).

| Download | Platform | Status |
|---|---|---|
| [`ReelsAIEditor-macOS-arm64.dmg`](https://github.com/chang7856/reels-ai-editor/releases/download/v1.1.0/ReelsAIEditor-macOS-arm64.dmg) | macOS · Apple Silicon (M1/M2/M3/M4) | **Actively maintained** |
| [`ReelsAIEditor-macOS-intel.dmg`](https://github.com/chang7856/reels-ai-editor/releases/download/v1.1.0/ReelsAIEditor-macOS-intel.dmg) | macOS · Intel CPU (pre-2020 Mac)   | Updated for v1.1 |
| [`ReelsAIEditor-Windows-x64.zip`](https://github.com/chang7856/reels-ai-editor/releases/download/v1.1.0/ReelsAIEditor-Windows-x64.zip) | Windows 10 / 11                    | Updated for v1.1 |

### What's new

**Look & feel**
- Y2K pixel-scissors app icon (粉 #FF6BB5 + 藍 #5BC2FF + 白) — Dock,
  Launchpad, Spotlight, the .dmg, and the README. Reproducible via
  `scripts/build_icon.sh` (pure PIL, no Adobe stack).

**Speed (Apple Silicon)**
- mlx-whisper-medium (Metal GPU + Neural Engine) replaces faster-whisper
  for both ZH transcription AND ZH→EN translation
- h264_videotoolbox hardware encoder replaces libx264 medium
- ~150 s end-to-end on a 3-min talking-head clip

**ffmpeg 8.x compatibility (critical)**
- `h264_videotoolbox` no longer takes `-q:v` in ffmpeg 8.x — every render
  died with exit 187 at frame 0. Switched to `-b:v 8M -maxrate 12M
  -bufsize 16M`.
- `-filter_complex_script` regression in ffmpeg 8.x — multi-line filter
  graphs error with `No option name near …`. Now reads the filter file
  and passes it inline via `-filter_complex` with newlines stripped.
  Without this, caption re-burn silently failed (subtitles.ass updated
  but the .mp4 was unchanged).

**Content-aware POV hook AND cover text**
- Burnt-in title and ALL cover text are derived from your transcript via
  the same hook scorer + 2-concept split.
- Hardcoded marketing templates removed ("AI 小編 / 真的能自動剪片",
  "廣告流程 / 可以自動跑嗎", "重點已經 / 幫你整理好了" — gone).
- Cover top band = #1 hook (2 concepts in 2 colors).
- Cover bottom band = a distinct secondary hook from the same
  transcript, OR left blank when no clean secondary exists.
- Hard completeness gate rejects "能不能夠…" / "然後" / lone modal /
  topic-shifter tails. Hard filler veto blocks 好啦/嗯/OK/test openers.
- Burnt-in title always 2 lines in 2 colors; both lines are independent
  complete concepts.

**✏️ Cover text editor (new)**
- Collapsible "編輯封面文字" panel: 6 editable slots in ZH mode
  (top label + 2-line main + English supporting line + 2-line bottom),
  5 in EN mode. "套用文案" re-renders the cover in ~1 s (no video
  re-encode). Edits stay sticky across style flips and candidate flips.
  Server-side whitelist + 60-char cap on each line.

**Editable subtitles + re-burn**
- Verification table under the output video: `[time]  ZH text  |  EN text`
  per row, click time to seek, click cell to edit.
- "套用字幕修改" re-burns the video in ~30 seconds.
- **Video loading overlay** during re-burn — translucent black + spinner
  + live elapsed-seconds counter covers the `<video>` so the user can't
  play the pre-edit burn underneath.
- **Job-expired banner** — if you press Apply after the 15-min retention
  sweep wiped your job, the error is now "這個任務已經過期" with a clear
  hint to re-upload (not the raw 404 string).
- Old video stays playable on re-burn failure (no more black-screen
  lockout).

**Per-language sessions**
- Chinese page and English page each remember their own finished result.
- ZH → EN → ZH round trip preserves the original ZH result.

**Cover styles**
- Removed `繽紛大字` / Color Pop (only Editorial Bold and All-White
  Hook remain).
- All-White Hook in-video title accent + EN subtitle are pure white now.

**Subtitle quality**
- Hard `_verify_subtitle_layout()` assertion in pipeline: ZH and EN
  subtitles never visually overlap.
- EN can wrap to 2 lines without colliding with ZH 2-line case.
- ASCII words containing punctuation (`OK,CheckCheck`) stay atomic.
- Fullwidth `ＡＩ` auto-converts to halfwidth `AI`.
- No 1-3 char orphans on the bottom line.
- Silence detection tuned for Chinese: only cuts pauses > 0.74 s with
  280 ms padding on each side.

**Whole flow in ONE browser window**
- "下載 Reels 影片" / "下載封面" use the `download=` attribute — same
  tab, native download dialog, no new windows during upload → process
  → download.
- Heartbeat-based Dock re-click: app touches a timestamp file on every
  page request; clicking the icon while a tab is alive (heartbeat
  ≤10s) silent-exits instead of stacking a new Chrome window. When
  the tab IS closed (heartbeat stale), the icon reopens it.
- Top dropzone clickable while a result is showing → auto-resets first.
- Re-uploading the same file works (Safari quirk handled).
- Stale jobs (15-min cleanup) no longer flash "找不到這個任務" on page
  load.

**macOS Sequoia 15 install (no Terminal)**
- Drag to Applications → double-click → "Apple could not verify"
  warning → click Done → System Settings → Privacy & Security → Open
  Anyway → confirm with password / Touch ID. One time, permanent
  whitelist. macOS 15 removed the older right-click → Open escape
  hatch, so System Settings is now the canonical no-Terminal path.
- `xattr -dr com.apple.quarantine` demoted to a collapsible "last
  resort" footnote.

**Build hygiene**
- `REGRESSION_CHECKLIST.md` and `scripts/smoke_test.sh` — **38
  automated gates** that must pass before shipping, including specific
  locks for:
  - ffmpeg 8.x `-filter_complex` inline vs `-filter_complex_script`
  - h264_videotoolbox uses `-b:v` not `-q:v`
  - No hardcoded "AI 小編 / 重點已經 / 廣告流程" cover templates
  - Download links use `download=` attribute, NOT `target="_blank"`
  - Heartbeat-based dock re-click (no duplicate tabs)
  - "能不能夠" incomplete-sentence regression
  - "OK,CheckCheck" atomic tokenization

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
