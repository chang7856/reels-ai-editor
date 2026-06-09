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

echo "=== Frontend: open links in new tab ==="
gate 'target="_blank" on Open Video' \
    'grep -q "target=\"_blank\"" templates/index.html'

echo "=== Frontend: result-panel busy lock ==="
gate "setResultPanelBusy helper exists" \
    'grep -q "setResultPanelBusy" templates/index.html'

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
