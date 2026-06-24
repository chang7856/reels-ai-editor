#!/bin/bash
# Run the regression checklist in REGRESSION_CHECKLIST.md programmatically.
# Exit code 0 = all gates passed; non-zero = a gate failed and a build
# should NOT be shipped to the user.

set -eo pipefail
cd "$(dirname "$0")/.."

PASS=0
FAIL=0
FAILED_GATES=()

gate() {
    local name="$1"
    local cmd="$2"
    if eval "$cmd" >/dev/null 2>&1; then
        echo "  PASS  $name"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $name"
        FAIL=$((FAIL + 1))
        FAILED_GATES+=("$name")
    fi
}

echo "=== JS lint (no broken backticks in HTML comments) ==="
gate "templates/index.html JS parses" \
    'node -e "const fs = require(\"fs\"); const html = fs.readFileSync(\"templates/index.html\", \"utf-8\"); const matches = [...html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)]; matches.forEach(m => new Function(m[1]));"'

echo "=== Server-side: magazine_pop fully removed ==="
gate "magazine_pop NOT in ALLOWED_COVER_STYLES" \
    '! grep -q "magazine_pop" app.py'

echo "=== Frontend: magazine_pop removed from UI ==="
gate "magazine_pop NOT in radio inputs" \
    '! grep -q "magazine_pop" templates/index.html'

echo "=== Hook scorer: filler veto + completeness ==="
gate "_segment_looks_complete exists" \
    'grep -q "_segment_looks_complete" reels_gui_pipeline.py'
gate "filler_patterns covers 好啦/嗯/OK/test" \
    'grep -A 8 "filler_patterns" reels_gui_pipeline.py | grep -q "好啦" && grep -A 8 "filler_patterns" reels_gui_pipeline.py | grep -q "test"'

echo "=== Unit tests on the title pipeline ==="
.venv-arm64/bin/python <<'PY'
import sys; sys.path.insert(0, '.')
from reels_gui_pipeline import (
    _segment_looks_complete,
    _split_hook_into_two_concepts,
    segment_hook_score,
    derive_pov_title,
)

ok = True

# Completeness gate -- universal incompleteness signals.
# Locking THIS specific failing case from the user's screenshot so it can
# never regress: 剪接軟體的第二部影片能不能夠 → INCOMPLETE.
assert _segment_looks_complete("AI 小編真的能自動剪片嗎"), "complete sentence rejected"
assert not _segment_looks_complete("剪接軟體的第二部影片能不能夠"), "REGRESSION: 能不能夠 dangling sentence accepted"
assert not _segment_looks_complete("剪接軟體的第二部影片能不能"), "REGRESSION: 能不能 dangling sentence accepted"
assert not _segment_looks_complete("然後我們"), "dangling 然後 accepted"
assert not _segment_looks_complete("我們可以"), "lone modal 可以 accepted"
assert not _segment_looks_complete("但是"), "lone 但是 accepted"
assert not _segment_looks_complete("那個我覺得這個"), "trailing 這個 accepted"
print("  PASS  completeness gate (including 能不能夠 regression lock)")

# derive_pov_title must REFUSE to pick the dangling segment even if it
# scores high on topic keywords. Force a transcript where the only
# high-scoring segment is the dangling one + a wholesome complete one.
fake_segments = [
    {"start": 0.5, "end": 4.0, "text": "剪接軟體的第二部影片能不能夠"},
    {"start": 5.0, "end": 8.5, "text": "AI 小編真的能自動剪片嗎"},
]
zh_title, en_title = derive_pov_title(fake_segments, [], "STATIC ZH", "STATIC EN")
assert "能不能夠" not in zh_title, f"REGRESSION: picker chose 能不能夠 -> {zh_title!r}"
print(f"  PASS  derive_pov_title refuses dangling hook: {zh_title!r}")

# Filler veto in scoring
filler_score = segment_hook_score({"text": "好啦好啦,來快速測試一下", "start": 0.0}, 0)
real_score = segment_hook_score({"text": "我浪費了 3 年才發現這個秘密", "start": 2.0}, 0)
assert filler_score < real_score - 10, f"filler {filler_score} too close to real {real_score}"
print(f"  PASS  filler veto (filler={filler_score:.1f} < real={real_score:.1f})")

# 2-concept split
a, b = _split_hook_into_two_concepts("AI 小編真的能自動剪片嗎")
assert a == "AI 小編" and "真的" in b, f"split failed: {a!r} / {b!r}"
print(f"  PASS  pivot split: {a!r} / {b!r}")

a, b = _split_hook_into_two_concepts("我浪費了 3 年才發現這個秘密")
assert a and b, f"balanced split failed: {a!r} / {b!r}"
print(f"  PASS  balanced split: {a!r} / {b!r}")
PY

echo "=== Subtitle pipeline: layout assertion exists ==="
gate "_verify_subtitle_layout in code" \
    'grep -q "_verify_subtitle_layout" reels_gui_pipeline.py'

echo "=== h264_videotoolbox uses -b:v not -q:v (ffmpeg 8 compat) ==="
# ffmpeg 8.x dropped -q:v / qscale for h264_videotoolbox. Any build that
# still passes -q:v dies with exit 187 at frame 0. Locking this fix.
gate "videotoolbox path does NOT pass -q:v" \
    'grep -B 1 -A 6 "encoder == \"h264_videotoolbox\"" reels_gui_pipeline.py | grep -q -- "-b:v"  && ! grep -B 1 -A 12 "encoder == \"h264_videotoolbox\"" reels_gui_pipeline.py | grep -q -- "\"-q:v\""'
gate "videotoolbox_bitrate default in reels_memory.json" \
    'grep -q "videotoolbox_bitrate" reels_memory.json'

echo "=== wrap_zh tokenizer keeps OK,CheckCheck atomic ==="
.venv-arm64/bin/python <<'PY'
import sys; sys.path.insert(0, '.')
from reels_gui_pipeline import wrap_zh, fullwidth_to_halfwidth_ascii
out = wrap_zh("OK,CheckCheck")
assert "CheckCheck" in out and "Chec\\NkCheck" not in out, f"mid-word split: {out!r}"
print(f"  PASS  wrap_zh('OK,CheckCheck') = {out!r}")
assert fullwidth_to_halfwidth_ascii("ＡＩ") == "AI"
print("  PASS  fullwidth -> halfwidth conversion")
PY

echo "=== Frontend: per-language session keys ==="
gate "snapshotSession does NOT removeItem (only set)" \
    '! grep -B 2 -A 6 "function snapshotSession" templates/index.html | grep -q "removeItem"'
gate "restoreSession accepts both done and complete" \
    'grep -q "data.status !== \"done\" && data.status !== \"complete\"" templates/index.html'
gate "activePollToken sentinel in place" \
    'grep -q "activePollToken" templates/index.html'
gate "upload submit pins activeJob.lang" \
    'grep -q "reels.activeJob.lang" templates/index.html'

echo "=== Result download links open in SAME tab (no target=_blank) ==="
# User asked for the entire upload→download flow to live in one window.
# Open Video / Open Cover must use the download attribute, not _blank.
gate 'Open Video link uses download attribute, not target=_blank' \
    'grep -E "class=\"download\" href=.*videoUrl" templates/index.html | grep -q "download=" && ! grep -E "class=\"download\" href=.*videoUrl" templates/index.html | grep -q "target=\""'
gate 'Open Cover link uses download attribute, not target=_blank' \
    'grep -E "class=\"download\" id=\"openCoverLink\"" templates/index.html | grep -q "download=" && ! grep -E "class=\"download\" id=\"openCoverLink\"" templates/index.html | grep -q "target=\""'
gate 'i18n label is 下載/Download (not 開啟/Open)' \
    'grep -q "下載 Reels 影片" templates/index.html && grep -q "Download Reels Video" templates/index.html'

echo "=== Dock re-click uses heartbeat to avoid duplicate tabs ==="
gate "app.py defines HEARTBEAT_FILE + _touch_heartbeat" \
    'grep -q "HEARTBEAT_FILE" app.py && grep -q "_touch_heartbeat" app.py'
gate "/ route touches heartbeat" \
    'grep -B 1 -A 6 "def index" app.py | grep -q "_touch_heartbeat"'
gate "/jobs/<id> polling also touches heartbeat" \
    'grep -B 1 -A 6 "def job_status" app.py | grep -q "_touch_heartbeat"'
gate "launch.py reads heartbeat before opening browser" \
    'grep -q "_browser_tab_looks_alive" launch.py'
gate "launch.py HEARTBEAT_FILE matches app.py path" \
    'grep -q "reels-ai-editor-heartbeat" launch.py && grep -q "reels-ai-editor-heartbeat" app.py'

echo "=== Frontend: result-panel busy lock ==="
gate "setResultPanelBusy helper exists" \
    'grep -q "setResultPanelBusy" templates/index.html'
gate "busy lock covers cover-editor inputs + buttons" \
    'grep -q "coverEditorApply" templates/index.html && grep -q "cover-editor-field input" templates/index.html'

echo "=== Cover-text editor: backend whitelist + GUI fields ==="
gate "EDITABLE_COVER_TEXT_KEYS whitelist defined" \
    'grep -q "EDITABLE_COVER_TEXT_KEYS" app.py'
gate "cover_text payload accepted by /jobs/<id>/cover" \
    'grep -q "cover_text_payload" app.py'
gate "cover_copy persisted back to result.json" \
    'grep -q "result\\[\"cover_copy\"\\] = cover_copy" app.py'
gate "60-char per-line cap enforced" \
    'grep -q "MAX_COVER_TEXT_LINE_CHARS" app.py'
gate "GUI editor section in renderResult" \
    'grep -q "cover-editor" templates/index.html && grep -q "coverEditorFieldsFor" templates/index.html'
gate "GUI ZH editor covers all 6 cover slots" \
    'grep -q "coverEditorPov" templates/index.html && grep -q "coverEditorMain1" templates/index.html && grep -q "coverEditorEnglish" templates/index.html && grep -q "coverEditorBottom1" templates/index.html'
gate "GUI EN editor covers 4 EN slots + POV" \
    'grep -q "coverEditorEnMain1" templates/index.html && grep -q "coverEditorEnBottom1" templates/index.html'

echo "=== Cover copy must be content-aware (no hardcoded marketing templates) ==="
# Check the demo / hardcoded strings only appear in COMMENTS (lines starting
# with whitespace + #) -- never as quoted string literals or JSON values.
# A python comment-only mention is fine ("we removed this because ..."); a
# string literal would mean the template is still being shipped.
gate "no 'AI 小編' string literal in pipeline" \
    '! grep -E "[\"'\'']AI 小編" reels_gui_pipeline.py'
gate "no 'AI 小編' value in reels_memory.json" \
    '! grep -q "AI 小編" reels_memory.json'
gate "no '我把流程' / '直接做成 App' string literal" \
    '! grep -E "[\"'\'']我把流程" reels_gui_pipeline.py && ! grep -E "[\"'\'']直接做成 App" reels_gui_pipeline.py'
gate "no '重點已經' / '幫你整理好了' string literal" \
    '! grep -E "[\"'\'']重點已經" reels_gui_pipeline.py && ! grep -E "[\"'\'']幫你整理好了" reels_gui_pipeline.py'
gate "no '廣告流程' / '可以自動跑嗎' string literal" \
    '! grep -E "[\"'\'']廣告流程" reels_gui_pipeline.py && ! grep -E "[\"'\'']可以自動跑嗎" reels_gui_pipeline.py'
gate "build_cover_copy uses _pick_secondary_hook for bottom band" \
    'grep -q "_pick_secondary_hook" reels_gui_pipeline.py'
gate "reels_memory.json cover text fields start empty" \
    'grep -q "\"main_line_1\": \"\"" reels_memory.json && grep -q "\"bottom_line_1\": \"\"" reels_memory.json'

.venv-arm64/bin/python <<'PY'
# Live cover copy: synthetic transcripts must not produce the old
# "AI 小編" / "重點已經" hardcoded outputs.
import sys, json
sys.path.insert(0, '.')
from reels_gui_pipeline import build_cover_copy

memory = json.loads(open("reels_memory.json").read())

# Used to false-trigger the AI template because "AI" appeared in transcript
zh = [
    {"start": 0.5, "end": 3.0, "text": "今天我們來聊聊 AI 工具"},
    {"start": 3.0, "end": 7.0, "text": "其實大部分人都用錯方向"},
    {"start": 7.0, "end": 11.0, "text": "你應該先問清楚目標再來挑工具"},
]
en = [
    {"start": 0.5, "end": 3.0, "text": "Let's talk about AI tools today"},
    {"start": 3.0, "end": 7.0, "text": "Most people approach this wrong"},
    {"start": 7.0, "end": 11.0, "text": "Define your goal first, then pick a tool"},
]
cover, _ = build_cover_copy(memory, zh, en)
assert "AI 小編" not in cover.get("main_line_1", ""), "REGRESSION: AI 小編 template fired"
assert "真的能自動剪片" not in cover.get("main_line_2", ""), "REGRESSION: 真的能自動剪片 template fired"
assert "我把流程" not in cover.get("bottom_line_1", ""), "REGRESSION: 我把流程 stock bottom fired"
assert "重點已經" not in cover.get("bottom_line_1", ""), "REGRESSION: 重點已經 stock bottom fired"
assert cover.get("main_line_1"), "main_line_1 empty"
print(f"  PASS  content-aware cover for AI-mentioning video: {cover['main_line_1']!r} / {cover['main_line_2']!r}")

# Short clip without a clean secondary hook -> bottom band MUST stay empty,
# not silently fall back to stock filler.
zh = [{"start": 0.5, "end": 3.0, "text": "我浪費了 3 年才發現這個秘密"}]
en = [{"start": 0.5, "end": 3.0, "text": "I wasted 3 years before I found this secret"}]
cover, _ = build_cover_copy(memory, zh, en)
assert cover.get("bottom_line_1", "") == "", f"bottom should be empty, got {cover.get('bottom_line_1')!r}"
assert cover.get("bottom_line_2", "") == "", f"bottom_2 should be empty"
print(f"  PASS  short clip: bottom band empty (no stock filler)")
PY

.venv-arm64/bin/python <<'PY'
# Backend live round-trip: send a cover_text override against a synthetic
# result.json so we catch any drift between app.py's whitelist and what
# the cover_copy dict actually carries.
import json, sys, tempfile, shutil
from pathlib import Path

sys.path.insert(0, '.')
from app import app, OUTPUTS, EDITABLE_COVER_TEXT_KEYS

job_id = "_smoke_cover_text"
job_dir = OUTPUTS / job_id
if job_dir.exists():
    shutil.rmtree(job_dir)
job_dir.mkdir(parents=True)
# Minimal result.json + a candidate frame the endpoint can copy over.
cover_base = job_dir / "reels_cover.jpg"
candidate = job_dir / "cover_candidate_0.jpg"
from PIL import Image
Image.new("RGB", (720, 1280), (180, 200, 220)).save(candidate)
Image.new("RGB", (720, 1280), (180, 200, 220)).save(cover_base)
result = {
    "video": "reels_ig_compressed.mp4",
    "cover": "reels_cover.jpg",
    "cover_style": "editorial",
    "language": "zh",
    "cover_copy": {
        "top_label": "POV",
        "main_line_1": "原本的標題",
        "main_line_2": "原本的副標",
        "english_line": "Old english line",
        "bottom_line_1": "原本下面",
        "bottom_line_2": "原本下面 2",
    },
    "cover_candidates": [{"filename": "cover_candidate_0.jpg", "selected": True}],
    "selected_cover_candidate": "cover_candidate_0.jpg",
    "memory": json.loads(Path("reels_memory.json").read_text()),
}
(job_dir / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2))

with app.test_client() as c:
    rsp = c.post(f"/jobs/{job_id}/cover", json={
        "cover_text": {
            "main_line_1": "我寫了 App",
            "main_line_2": "可以改文字了",
            "english_line": "I built my own editor",
        },
    })
    assert rsp.status_code == 200, f"cover_text edit failed: {rsp.status_code} {rsp.get_data(as_text=True)}"
    body = rsp.get_json()
    cc = body.get("cover_copy") or {}
    assert cc.get("main_line_1") == "我寫了 App", f"edit not applied: {cc}"
    assert cc.get("main_line_2") == "可以改文字了"
    assert cc.get("english_line") == "I built my own editor"
    # Untouched fields stay as originals
    assert cc.get("top_label") == "POV"
    assert cc.get("bottom_line_1") == "原本下面"

    # Reject too-long line
    rsp2 = c.post(f"/jobs/{job_id}/cover", json={
        "cover_text": {"main_line_1": "長" * 70},
    })
    assert rsp2.status_code == 400, f"too-long line not rejected: {rsp2.status_code}"

    # Unknown key silently dropped
    rsp3 = c.post(f"/jobs/{job_id}/cover", json={
        "cover_text": {"font_family": "Comic Sans"},
    })
    assert rsp3.status_code == 200
    assert "font_family" not in (rsp3.get_json().get("cover_copy") or {})

# Cleanup
shutil.rmtree(job_dir)
print("  PASS  cover_text round-trip (apply + length cap + key whitelist)")
PY

echo ""
echo "==============================================="
echo "  PASS: $PASS"
echo "  FAIL: $FAIL"
if [ "$FAIL" -gt 0 ]; then
    echo ""
    echo "Failing gates:"
    for g in "${FAILED_GATES[@]}"; do
        echo "  - $g"
    done
    exit 1
fi
echo "  All gates green. Safe to build."
