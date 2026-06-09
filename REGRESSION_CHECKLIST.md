# Regression Checklist

Run this before declaring any build "ready for the user to test".

Date last passed end-to-end: _(none)_

## Universal title / hook rules (apply to ALL uploads, no exceptions)

- [ ] Burnt-in title renders as 2 lines
- [ ] Line 1 and Line 2 are PAINTED IN DIFFERENT COLORS
- [ ] BOTH lines are complete content phrases (no "POV：" label-only line)
- [ ] Hook scorer NEVER picks a segment that ends with a dangling cue
      (能不能/可不可以/還是/然後/所以/因為/可是/不過/而且)
- [ ] Hook scorer NEVER picks a filler opener
      (好啦/嗯/啊/呃/OK/test/check)
- [ ] If top hook candidate can't be split into 2 concepts, the picker
      tries the NEXT best candidate, not "give up + use POV: label"
- [ ] Title fits within the cover band horizontally at base fontsize;
      auto-shrinks when too wide

## Cover styles

- [ ] Only `editorial` + `hook_caption` show in the GUI
- [ ] `magazine_pop` / `繽紛大字` is NOT in the radio group
- [ ] `magazine_pop` is NOT in STYLE_SWITCHER_ORDER
- [ ] `magazine_pop` is NOT in server ALLOWED_COVER_STYLES
- [ ] Hook Caption (全白爆點) title accent and EN subtitle are pure white,
      no neon green leaking through

## Subtitles (universal, every upload)

- [ ] ZH and EN subtitles NEVER overlap pixel-wise (hard assertion
      `_verify_subtitle_layout` raises a clear error if any pair would)
- [ ] EN can wrap to 2 lines without colliding with ZH 2-line case
- [ ] No mid-word ASCII split (e.g. "OK,CheckCheck" stays atomic
      across the comma — `_ZH_PUNCT_TOKENS` handling)
- [ ] Fullwidth ASCII (ＡＩ, ０-９) auto-converts to halfwidth via
      `fullwidth_to_halfwidth_ascii`
- [ ] No 1-3 char widow on line 2 of wrap_zh
- [ ] Silence cuts only fire on pauses > 0.74s with 280 ms padding on
      each side (Chinese-tuned)

## Editable cover text

- [ ] "✏️ 編輯封面文字" panel collapsed by default on result page
- [ ] Opening it shows all 6 ZH slots (POV / main 1 / main 2 / english /
      bottom 1 / bottom 2) OR all 5 EN slots (POV / main 1 / main 2 /
      bottom 1 / bottom 2) based on currentLang
- [ ] Editing a field highlights yellow (dirty state)
- [ ] "套用文案" POSTs to /jobs/<id>/cover with `cover_text` payload
      and ALL field values (not just dirty ones)
- [ ] Lines >60 chars rejected client-side AND server-side with a clear
      error message
- [ ] Unknown keys (font_family, font_size, anything not in
      EDITABLE_COVER_TEXT_KEYS) are silently dropped server-side
- [ ] Cover image refreshes in-place after apply (cache buster via `?t=`)
- [ ] Edited cover_copy persists into result.json
- [ ] Style flip (editorial ↔ hook_caption) preserves the user's edits
- [ ] Candidate flip preserves the user's edits
- [ ] Page reload restores the edited copy (read from result.json)
- [ ] "還原為原本的文字" restores the snapshot taken on first render
- [ ] Editor inputs + buttons disabled during caption re-burn
      (setResultPanelBusy lock)

## Editable transcript

- [ ] Transcript table loads after the job completes
- [ ] Each row: timestamp button + editable ZH cell + editable EN cell
- [ ] Click timestamp → video seeks to that moment
- [ ] Editing a cell marks it dirty (yellow highlight)
- [ ] "套用字幕修改" button posts to /jobs/<id>/captions
- [ ] During re-burn, ALL other result-panel buttons become disabled
- [ ] After re-burn, video src refreshes to new URL

## Language switching (the bug that keeps coming back)

- [ ] Upload a video on ZH → result shown → switch to EN
- [ ] On EN: result panel cleared (no leaked ZH state)
- [ ] No "找不到這個任務" flash
- [ ] No fake 8%/100% progress bars on the EN landing
- [ ] Switch back to ZH → ZH result RESTORES (video + cover + transcript)
- [ ] localStorage key `reels.session.zh` persists across switches
- [ ] localStorage key `reels.session.en` is independent
- [ ] If the ZH job's job_dir was wiped (15-min cleanup or rebuild),
      restoreSession silently falls back to empty UI (no error flash)
- [ ] activePollToken sentinel: cancelled polls never paint stale state

## UI safety

- [ ] Top dropzone clickable when result is showing → auto-resets first
- [ ] Drag-and-drop same file after completion still triggers upload
      (Safari quirk handled with `type` swap)
- [ ] Double-clicking the .app icon while it's running does NOT open a
      new browser tab (silent exit on port-already-in-use)
- [ ] Open Video / Open Cover buttons open in new tab (`target="_blank"`)
- [ ] "再剪一支影片" button resets the panel and scrolls to dropzone
- [ ] restoreActiveJob on page load: PROBES /jobs/<id> first, only
      paints "processing" UI if the job is genuinely still running
- [ ] Background colors / progress bars never appear without a real
      in-flight upload

## h264_videotoolbox encoder (ffmpeg 8.x)

- [ ] `render_video` passes `-b:v <bitrate>` for h264_videotoolbox,
      NEVER `-q:v <qscale>` (ffmpeg 8 removed qscale support → exit 187)
- [ ] Default: 8M average, 12M maxrate, 16M bufsize at 720x1280
- [ ] Render budget on M-chip: ≥3x realtime (137s clip → ≤45s render)
- [ ] First-second-grey-frame bug stays fixed
      (the original reason we switched from CBR to qscale)

## Speed budget (3-min input on M-chip Mac)

- [ ] Whisper-medium MLX translate: ~80s
- [ ] h264_videotoolbox encode: ~30s
- [ ] Total wall time: ~135-180s
- [ ] First-time model download: ~1.5 GB (warning shown to user)

## Build hygiene

- [ ] `node -e ...` JS template literal lint passes (no broken
      backticks inside HTML comments)
- [ ] Layout assertion `layout OK: NN ZH events, MM EN events,
      no pixel overlap` appears in every job's run.log
- [ ] `hook candidates (top 3):` lines appear in run.log for audit
- [ ] `hook title:` line shows the FINAL title actually rendered

## Smoke-test command

From the repo root:

```bash
PYTHON="$(pwd)/.venv-arm64/bin/python" bash scripts/smoke_test.sh
```

(See `scripts/smoke_test.sh` — runs synthetic clip through pipeline +
greps for required log lines + diffs served HTML vs source.)
