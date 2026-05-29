import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "4")

from faster_whisper import WhisperModel
from opencc import OpenCC
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageStat


ROOT = Path(__file__).resolve().parent
MEMORY = ROOT / "reels_memory.json"
FONT_ZH = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_EN = "/System/Library/Fonts/HelveticaNeue.ttc"


def log(message):
    print(message, flush=True)


def write_progress(job_dir, stage, detail):
    progress_path = Path(job_dir) / "progress.json"
    previous = {}
    if progress_path.exists():
        try:
            previous = json.loads(progress_path.read_text())
        except json.JSONDecodeError:
            previous = {}
    now = time.time()
    if previous.get("stage") != stage:
        previous["stage_started_at"] = now
    previous.update({
        "stage": stage,
        "detail": detail,
        "updated_at": now,
    })
    progress_path.write_text(json.dumps(previous, ensure_ascii=False, indent=2))


def run(cmd, capture=False):
    if capture:
        return subprocess.run(cmd, check=True, text=True, capture_output=True)
    subprocess.run(cmd, check=True)
    return None


def load_memory(options_path=None):
    memory = json.loads(MEMORY.read_text())
    if options_path and Path(options_path).exists():
        memory["runtime_options"] = json.loads(Path(options_path).read_text())
    else:
        memory["runtime_options"] = {}
    return memory


def ffprobe_duration(video):
    result = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        str(video),
    ], capture=True)
    return float(result.stdout.strip())


def extract_audio(video, wav, job_dir=None):
    if job_dir:
        write_progress(job_dir, "validate", "正在抽出音訊，準備偵測停頓")
    log("1/7 Extracting audio")
    run([
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000",
        str(wav),
    ])


def detect_silence(video, log_path, memory, job_dir=None):
    if job_dir:
        write_progress(job_dir, "validate", "正在偵測停頓與不必要空白")
    log("2/7 Detecting pauses")
    edit = memory["editing"]
    result = run([
        "ffmpeg", "-hide_banner", "-i", str(video),
        "-af", f"silencedetect=noise={edit['silence_noise_db']}dB:d={edit['silence_min_duration']}",
        "-f", "null", "-",
    ], capture=True)
    log_path.write_text(result.stderr)


def parse_silences(log_path):
    text = log_path.read_text(errors="ignore")
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", text)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", text)]
    return list(zip(starts, ends))


def load_whisper(memory, job_dir=None):
    perf = memory.get("performance", {})
    model_name = perf.get("whisper_model", "small")
    compute_type = perf.get("compute_type", "int8")
    cpu_threads = int(perf.get("cpu_threads", 4))
    if job_dir:
        write_progress(job_dir, "transcribe", f"正在載入 Whisper {model_name} fast mode")
    log(f"Loading Whisper model: {model_name} ({compute_type}, {cpu_threads} threads)")
    return WhisperModel(
        model_name,
        device="cpu",
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        num_workers=1,
    )


def transcribe(model, memory, wav, out_json, task="transcribe", job_dir=None):
    label = "Chinese transcription" if task == "transcribe" else "English translation"
    if job_dir:
        detail = "正在產生繁體中文字幕" if task == "transcribe" else "正在翻譯英文字幕"
        write_progress(job_dir, "transcribe", detail)
    log(f"3/7 Running {label}")
    perf = memory.get("performance", {})
    # For the Chinese pass we ask Whisper for per-word timestamps. That lets us
    # snap each subtitle event to the actual speech onset/offset (instead of the
    # looser VAD-segment boundary) so the burnt-in subtitle stays glued to the
    # voice. The translation pass keeps the cheaper segment-level output.
    want_words = task == "transcribe" and perf.get("word_timestamps", True)
    segments, info = model.transcribe(
        str(wav),
        language="zh",
        task=task,
        vad_filter=True,
        beam_size=int(perf.get("beam_size", 3 if task == "transcribe" else 1)),
        best_of=1,
        word_timestamps=bool(want_words),
        condition_on_previous_text=False,
    )
    rows = []
    for seg in segments:
        text = seg.text.strip()
        if not text:
            continue
        start, end = seg.start, seg.end
        if want_words and seg.words:
            real_words = [w for w in seg.words if w.word.strip()]
            if real_words:
                start = real_words[0].start
                end = real_words[-1].end
        rows.append({"start": start, "end": end, "text": text})
    out_json.write_text(json.dumps({"language": info.language, "task": task, "segments": rows}, ensure_ascii=False, indent=2))
    return rows


def subtract_ranges(base, cuts):
    pieces = [base]
    for cs, ce in cuts:
        next_pieces = []
        for ps, pe in pieces:
            if ce <= ps or cs >= pe:
                next_pieces.append((ps, pe))
            else:
                if cs - ps >= 0.20:
                    next_pieces.append((ps, cs))
                if pe - ce >= 0.20:
                    next_pieces.append((ce, pe))
        pieces = next_pieces
    return pieces


def build_pieces(duration, silences, memory=None):
    edit = (memory or {}).get("editing", {})
    opening_trim = float(edit.get("opening_trim_seconds", 0))
    preserve_tail = float(edit.get("preserve_tail_seconds", 0))
    protected_tail_start = max(0, duration - preserve_tail)
    cuts = []
    for start, end in silences:
        if end >= protected_tail_start:
            continue
        cut_start = max(0, start + 0.06)
        cut_end = min(protected_tail_start, end - 0.10)
        if cut_end - cut_start >= 0.18:
            cuts.append((cut_start, cut_end))
    pieces = subtract_ranges((0.0, duration), cuts)
    merged = []
    for start, end in pieces:
        if not merged and opening_trim and end > opening_trim:
            start = max(start, opening_trim)
        if end - start < 0.22:
            continue
        if merged and start - merged[-1][1] < 0.12:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    if merged and merged[-1][1] < duration:
        merged[-1] = (merged[-1][0], duration)
    return merged


def make_timeline(pieces):
    timeline = []
    cursor = 0.0
    for start, end in pieces:
        timeline.append({
            "src_start": start,
            "src_end": end,
            "dst_start": cursor,
            "dst_end": cursor + end - start,
        })
        cursor += end - start
    return timeline


def intersections(seg, timeline):
    rows = []
    for item in timeline:
        start = max(seg["start"], item["src_start"])
        end = min(seg["end"], item["src_end"])
        if end - start >= 0.20:
            rows.append({
                "start": item["dst_start"] + start - item["src_start"],
                "end": item["dst_start"] + end - item["src_start"],
                "text": seg["text"].strip(),
            })
    return rows


def ass_ts(seconds):
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# Ideographs only — deliberately excludes CJK punctuation like "：、。！？"
# so we do not inject a space between a Latin word and a full-width punctuation
# mark (e.g. "POV：" must stay tight).
_CJK_BLOCKS = r"㐀-䶿一-鿿豈-﫿"
_CJK_RANGE = f"[{_CJK_BLOCKS}]"
_ASCII_WORD = r"[A-Za-z0-9][A-Za-z0-9/+\-.]*"


def normalize_cjk_ascii_spacing(text):
    """Make sure there is always a single space between Chinese and English /
    digit tokens. Punctuation is left untouched.

    The rule is documented in reels_memory.json (subtitle.mixed_language_spacing)
    so future edits stay consistent.
    """
    if not text:
        return text
    # ASCII word followed by CJK -> add space.
    text = re.sub(rf"({_ASCII_WORD})({_CJK_RANGE})", r"\1 \2", text)
    # CJK followed by ASCII word -> add space.
    text = re.sub(rf"({_CJK_RANGE})({_ASCII_WORD})", r"\1 \2", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def clean_zh(text):
    text = OpenCC("s2t").convert(text)
    replacements = {
        "cloud": " Claude ",
        "Cloud": " Claude ",
        "Claude": " Claude ",
        "AI": " AI ",
        "IG": " IG ",
        "APP": "App",
        "App": "App",
        "app": "App",
        "po文": "貼文",
        "user": "使用者",
        "account": "帳號",
        "google ads": " Google Ads ",
        "Google Ads": " Google Ads ",
        "ABI test": " A/B test ",
        "A B test": " A/B test ",
        "menu cpc": " manual CPC ",
        "kpi": " KPI ",
        "repo": " repo ",
        "pipeline": " pipeline ",
        "campaign": " campaign ",
        "感謝觀優優獨播劇場——": "掰掰",
        "感谢观优优独播剧场——": "掰掰",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\bA\s+p\s+p\b", "App", text, flags=re.IGNORECASE)
    text = re.sub(r"\bA\s+I\b", "AI", text)
    text = re.sub(r"\bI\s+G\b", "IG", text)
    text = re.sub(r"^(就是|然後|那|嗯|呃|啊)[，, ]*", "", text).strip()
    text = re.sub(r"(啊|嘛|呢|吧)$", "", text).strip()
    text = normalize_cjk_ascii_spacing(text)
    return text


def clean_en(text):
    return normalize_cjk_ascii_spacing(re.sub(r"\s+", " ", text).strip())


def wrap_zh(text, max_width=26):
    tokens = []
    for part in text.split():
        if re.fullmatch(r"[A-Za-z0-9/+\-.]+", part):
            tokens.append(part)
        else:
            tokens.extend(list(part))

    def token_width(token):
        return len(token) + 2 if re.fullmatch(r"[A-Za-z0-9/+\-.]+", token) else 2

    def append_token(line, token):
        is_ascii = bool(re.fullmatch(r"[A-Za-z0-9/+\-.]+", token))
        if is_ascii:
            return (line + " " + token).strip()
        if line and re.search(r"[A-Za-z0-9/+\-.]$", line):
            return line + " " + token
        return line + token

    lines, line, width = [], "", 0
    for token in tokens:
        next_width = token_width(token)
        if line and width + next_width > max_width:
            lines.append(line.strip())
            line, width = "", 0
        line = append_token(line, token)
        width += next_width
    if line:
        lines.append(line.strip())
    return r"\N".join(lines[:2])


def wrap_en(text, width=38):
    words = text.split()
    lines, line = [], ""
    for word in words:
        candidate = word if not line else f"{line} {word}"
        if len(candidate) > width:
            if line:
                lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return r"\N".join(lines[:2])


def plain_wrap_zh(text, max_chars=9):
    compact = re.sub(r"\s+", " ", clean_zh(text)).strip(" ，,。.!！?")
    if not compact:
        return []
    lines = wrap_zh(compact, max_width=max_chars * 2).split(r"\N")
    return [line.strip() for line in lines[:2] if line.strip()]


def segment_hook_score(segment, index=0):
    text = clean_zh(segment.get("text", ""))
    keywords = [
        "AI", "自動", "廣告", "小編", "Google", "成本", "省", "免費",
        "問題", "方法", "怎麼", "為什麼", "其實", "最", "不需要", "可以",
    ]
    score = max(0, 60 - segment.get("start", 0)) * 0.12
    score += max(0, 26 - len(text)) * 0.12
    score += sum(4 for word in keywords if word in text)
    score += 6 if re.search(r"[？?！!]", text) else 0
    score += 2 if index < 6 else 0
    return score


def best_hook_segment(zh_segments):
    if not zh_segments:
        return None
    candidates = [(segment_hook_score(seg, index), seg) for index, seg in enumerate(zh_segments[:24])]
    return max(candidates, key=lambda item: item[0])[1]


def nearest_english_segment(en_segments, target):
    if not en_segments:
        return ""
    match = min(en_segments, key=lambda seg: abs(((seg["start"] + seg["end"]) / 2) - target))
    return clean_en(match.get("text", ""))


def _split_en_headline(text, max_chars=18):
    """Return [line1, line2] for an English hero headline.

    We balance the two lines by length so neither feels stranded — IG covers
    look amateurish when one line has 2 words and the other has 8.
    """
    words = text.strip().split()
    if not words:
        return ["", ""]
    if len(text) <= max_chars:
        return [text, ""]
    best_diff = float("inf")
    best_split = 1
    for split in range(1, len(words)):
        left = " ".join(words[:split])
        right = " ".join(words[split:])
        if len(left) > max_chars + 4 or len(right) > max_chars + 4:
            continue
        diff = abs(len(left) - len(right))
        if diff < best_diff:
            best_diff = diff
            best_split = split
    return [" ".join(words[:best_split]), " ".join(words[best_split:])]


def build_cover_copy(memory, zh_segments, en_segments):
    cover = dict(memory["cover"])
    hook = best_hook_segment(zh_segments)
    if not hook:
        return cover, None
    hook_time = max(0.2, (hook["start"] + hook["end"]) / 2)
    transcript = clean_zh(" ".join(seg.get("text", "") for seg in zh_segments[:16]))
    hook_text = clean_zh(hook["text"])
    if any(word in transcript for word in ["AI", "自動", "剪輯", "小編"]):
        cover["main_line_1"] = "AI 小編"
        cover["main_line_2"] = "真的能自動剪片？"
        cover["english_line"] = "Can AI really edit Reels for you?"
        cover["en_main_line_1"] = "Can AI really"
        cover["en_main_line_2"] = "edit Reels for you?"
        cover["bottom_line_1"] = "我把流程"
        cover["bottom_line_2"] = "直接做成 App"
        cover["en_bottom_line_1"] = "I shipped"
        cover["en_bottom_line_2"] = "the whole pipeline"
    elif any(word in transcript for word in ["廣告", "Google", "投放", "成本"]):
        cover["main_line_1"] = "廣告流程"
        cover["main_line_2"] = "可以自動跑嗎？"
        cover["english_line"] = "Can ads run on autopilot?"
        cover["en_main_line_1"] = "Can ads"
        cover["en_main_line_2"] = "run on autopilot?"
        cover["bottom_line_1"] = "小團隊也能"
        cover["bottom_line_2"] = "省下重複工作"
        cover["en_bottom_line_1"] = "A small team"
        cover["en_bottom_line_2"] = "saves the repeat work"
    else:
        lines = plain_wrap_zh(hook_text, 9)
        if lines:
            cover["main_line_1"] = lines[0]
            cover["main_line_2"] = lines[1] if len(lines) > 1 else "這段值得看完"
        english = nearest_english_segment(en_segments, hook_time)
        en_main = _split_en_headline(english or "This is worth watching")
        cover["en_main_line_1"], cover["en_main_line_2"] = en_main[0], en_main[1] or "This is worth watching"
        if english:
            cover["english_line"] = wrap_en(english, 32).replace(r"\N", " ")
        cover["bottom_line_1"] = "重點已經"
        cover["bottom_line_2"] = "幫你整理好了"
        cover["en_bottom_line_1"] = "Key takeaways"
        cover["en_bottom_line_2"] = "saved for you"
    cover["top_label"] = "POV"
    return cover, hook


def ass_escape(text):
    return text.replace("{", "").replace("}", "")


def _build_en_assignments(zh_segments, en_segments):
    """Distribute each EN segment's text across the ZH segments it spans.

    Whisper's translate pass tends to merge several spoken phrases into one
    longer EN segment, so a single EN line often covers two or three ZH
    segments. Picking a single "best" EN per ZH (and marking it used) leaves
    later ZH lines without any English, which is what the user noticed in
    screenshot #2. Instead we walk the EN segments in order and split each
    one across the ZH segments it overlaps with, proportional to overlap
    duration — so every ZH whose audio came from that EN gets a fragment of
    the translation, and no two consecutive ZH lines are forced to show the
    exact same English string.
    """
    assignments = [""] * len(zh_segments)
    if not zh_segments or not en_segments:
        return assignments

    for en in en_segments:
        words = clean_en(en.get("text", "")).split()
        if not words:
            continue
        en_start, en_end = en["start"], en["end"]
        overlaps = []
        for index, zh in enumerate(zh_segments):
            overlap = min(zh["end"], en_end) - max(zh["start"], en_start)
            if overlap >= 0.12:
                overlaps.append((index, overlap))
        if not overlaps:
            # Fall back to the closest ZH by centre — keeps short interjections
            # from being dropped entirely.
            center = (en_start + en_end) / 2
            nearest = min(
                range(len(zh_segments)),
                key=lambda i: abs((zh_segments[i]["start"] + zh_segments[i]["end"]) / 2 - center),
            )
            overlaps = [(nearest, 0.0)]

        if len(overlaps) == 1:
            zh_idx = overlaps[0][0]
            assignments[zh_idx] = (
                (assignments[zh_idx] + " " + " ".join(words)).strip()
                if assignments[zh_idx]
                else " ".join(words)
            )
            continue

        total = sum(max(0.001, ov) for _, ov in overlaps)
        cursor = 0
        for slot_index, (zh_idx, ov) in enumerate(overlaps):
            if slot_index == len(overlaps) - 1:
                portion = words[cursor:]
            else:
                share = max(1, int(round(len(words) * (max(0.001, ov) / total))))
                portion = words[cursor:cursor + share]
                cursor += share
            if not portion:
                continue
            chunk = " ".join(portion)
            assignments[zh_idx] = (
                (assignments[zh_idx] + " " + chunk).strip() if assignments[zh_idx] else chunk
            )

    return assignments


def _split_wrapped(text):
    """Return the dialogue text split into at most two lines (top, bottom).

    `wrap_zh` / `wrap_en` already emit at most two lines joined by `\\N`. The
    caller passes the already-escaped string, so this is a pure split.
    """
    if not text:
        return []
    parts = [chunk.strip() for chunk in text.split(r"\N")]
    parts = [chunk for chunk in parts if chunk]
    return parts[:2]


def _dialogue_lines(style_name, layer, start, end, text, base_margin_v, font_size, gap_px):
    """Emit one or two Dialogue rows so wrapped subtitles get a visible gap."""
    parts = _split_wrapped(text)
    if not parts:
        return []
    if len(parts) == 1:
        return [(layer, start, end, style_name, base_margin_v, parts[0])]
    line_height = int(round(font_size * 1.22))
    top_margin = base_margin_v + line_height + gap_px
    return [
        (layer, start, end, style_name, top_margin, parts[0]),
        (layer, start, end, style_name, base_margin_v, parts[1]),
    ]


def build_ass(zh_segments, en_segments, timeline, ass_path, memory, cover_style="editorial", language="zh"):
    sub = memory["subtitle"]
    language = (language or "zh").lower()
    en_only = language == "en"
    lead_seconds = float(sub.get("lead_seconds", 0.18))
    hold_seconds = float(sub.get("hold_seconds", 0.20))
    zh_size = int(sub["chinese_font_size"])
    en_size = int(sub.get("english_font_size_solo", 72)) if en_only else int(sub["english_font_size"])
    zh_base_margin = int(sub["chinese_bottom_margin"])
    # In English-only mode the EN line is the hero, so put it where the ZH line
    # normally lives (and the ZH style is skipped).
    en_base_margin = zh_base_margin if en_only else int(sub["english_bottom_margin"])
    line_gap = int(sub.get("line_gap_px", 22))
    palette = _subtitle_spec(cover_style)
    en_primary = palette.get("en_primary_solo", palette["en_primary"]) if en_only else palette["en_primary"]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ZH,STHeiti,{zh_size},{palette['zh_primary']},&H00FFFFFF,{palette['zh_outline']},&H70000000,1,0,0,0,100,100,{sub['chinese_letter_spacing']},0,1,2,1,2,80,80,{zh_base_margin},1
Style: EN,Helvetica Neue,{en_size},{en_primary},&H00FFFFFF,{palette['en_outline']},&H70000000,1,0,0,0,100,100,{sub['english_letter_spacing']},0,1,2,1,2,80,80,{en_base_margin},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    rows = []
    last_zh_norm, last_en_norm, last_end = None, None, -99
    timeline_end = timeline[-1]["dst_end"] if timeline else 0
    bilingual = bool(sub.get("bilingual")) and not en_only
    en_assignments = _build_en_assignments(zh_segments, en_segments) if (bilingual or en_only) else [""] * len(zh_segments)
    for zh_index, zh in enumerate(zh_segments):
        en_text = en_assignments[zh_index] if zh_index < len(en_assignments) else ""
        for item in intersections(zh, timeline):
            start = max(0.0, item["start"] - lead_seconds)
            end = min(timeline_end, max(item["end"], item["start"] + 0.65) + hold_seconds)
            if en_only:
                # English-only: skip the Chinese line entirely.
                if not en_text:
                    continue
                en_clean_raw = clean_en(en_text)
                en_text_wrapped = ass_escape(wrap_en(en_clean_raw, width=22))
                if not en_text_wrapped:
                    continue
                normalized = re.sub(r"\s+", "", en_text_wrapped.replace(r"\N", "").lower())
                if normalized == last_en_norm and start - last_end < 1.25:
                    rows[-1]["end"] = max(rows[-1]["end"], end)
                    last_end = max(last_end, end)
                    continue
                rows.append({"start": start, "end": end, "zh": "", "en": en_text_wrapped})
                last_en_norm, last_end = normalized, end
            else:
                zh_clean = clean_zh(item["text"])
                zh_text = ass_escape(wrap_zh(zh_clean))
                if not zh_text:
                    continue
                normalized = re.sub(r"\s+", "", zh_text.replace(r"\N", ""))
                if normalized == last_zh_norm and start - last_end < 1.25:
                    rows[-1]["end"] = max(rows[-1]["end"], end)
                    last_end = max(last_end, end)
                    continue
                en_clean = ass_escape(wrap_en(en_text)) if (bilingual and en_text) else ""
                rows.append({"start": start, "end": end, "zh": zh_text, "en": en_clean})
                last_zh_norm, last_end = normalized, end

    # No-overlap rule: clip each row's end so the next row's lead-in never
    # collides with it.
    rows.sort(key=lambda r: r["start"])
    min_gap = float(sub.get("min_gap_seconds", 0.04))
    for index in range(len(rows) - 1):
        next_start = rows[index + 1]["start"]
        latest_end = next_start - min_gap
        if rows[index]["end"] > latest_end:
            rows[index]["end"] = max(rows[index]["start"] + 0.35, latest_end)

    lines = [header]
    for row in sorted(rows, key=lambda r: r["start"]):
        dialogue_rows = []
        if row.get("zh"):
            dialogue_rows.extend(_dialogue_lines(
                "ZH", 1, row["start"], row["end"], row["zh"], zh_base_margin, zh_size, line_gap,
            ))
        if row.get("en"):
            dialogue_rows.extend(_dialogue_lines(
                "EN", 1 if en_only else 0, row["start"], row["end"], row["en"], en_base_margin, en_size, max(10, line_gap - 4),
            ))
        for layer, start, end, style_name, margin_v, text in dialogue_rows:
            lines.append(
                f"Dialogue: {layer},{ass_ts(start)},{ass_ts(end)},{style_name},,0,0,{margin_v},,{text}\n"
            )
    ass_path.write_text("".join(lines))


def _ffmpeg_text_escape(text):
    # drawtext text= uses single-quote framing, plus colon/backslash escaping.
    return (
        text.replace("\\", "\\\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
    )


def _title_lines(title):
    # Render the title as up to two cleanly-spaced lines. Drawing line breaks
    # via "\n" inside drawtext text= is unreliable across ffmpeg versions and
    # was previously rendering the literal letter "n".
    normalized = normalize_cjk_ascii_spacing(title)
    if " 小編" in normalized:
        head, tail = normalized.split(" 小編", 1)
        return [head.strip(), ("小編" + tail).strip()]
    if "：" in normalized:
        head, tail = normalized.split("：", 1)
        return [(head + "：").strip(), tail.strip()]
    if ":" in normalized:
        head, tail = normalized.split(":", 1)
        return [(head + ":").strip(), tail.strip()]
    return [normalized.strip()]


def _en_title_lines(title):
    """Split an English title into one or two visually balanced lines."""
    if not title:
        return [""]
    if ":" in title:
        head, tail = title.split(":", 1)
        return [(head + ":").strip(), tail.strip()]
    parts = _split_en_headline(title.strip(), max_chars=22)
    return [p for p in parts if p]


def build_filter(video, pieces, ass_path, filter_path, memory):
    labels, parts = [], []
    export = memory.get("export", {})
    target_w = int(export.get("width", 720))
    target_h = int(export.get("height", 1280))
    for i, (start, end) in enumerate(pieces):
        parts.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,"
            f"scale={target_w}:{target_h}:force_original_aspect_ratio=increase:flags=lanczos+accurate_rnd,"
            f"crop={target_w}:{target_h},setsar=1[v{i}]"
        )
        parts.append(
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,"
            "highpass=f=80,lowpass=f=12000,"
            "acompressor=threshold=-18dB:ratio=2.2:attack=8:release=120,"
            f"volume=1.15[a{i}]"
        )
        labels.append(f"[v{i}][a{i}]")
    parts.append("".join(labels) + f"concat=n={len(pieces)}:v=1:a=1[cv][ca]")

    style = memory.get("runtime_options", {}).get("cover_style", "editorial")
    language = (memory.get("runtime_options", {}).get("language") or "zh").lower()
    in_video_title = _in_video_title_overlay(style)
    if language == "en":
        en_title = memory.get("title_en") or memory.get("title", "")
        title_lines = _en_title_lines(en_title)
    else:
        title_lines = _title_lines(memory["title"])
    title_draws = []
    # Top translucent band keeps the burnt-in title readable on any background.
    title_draws.append(
        f"drawbox=x=0:y=0:w=iw:h={in_video_title['band_h']}:"
        f"color={in_video_title['band_color']}:t=fill"
    )
    for index, line in enumerate(title_lines):
        if not line:
            continue
        y = in_video_title["title_y_top"] + index * in_video_title["line_height"]
        color = in_video_title["main_color"] if index == 0 else in_video_title["accent_color"]
        title_draws.append(
            f"drawtext=fontfile='{FONT_ZH}':text='{_ffmpeg_text_escape(line)}':"
            f"x=(w-text_w)/2:y={y}:fontsize={in_video_title['fontsize']}:"
            f"fontcolor={color}:borderw={in_video_title['borderw']}:"
            f"bordercolor=black@{in_video_title['border_alpha']}:shadowx=2:shadowy=2"
        )

    subs_path = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")
    parts.append(
        "[cv]"
        + ",".join(title_draws + [f"subtitles='{subs_path}'", "format=yuv420p"])
        + "[vout]"
    )
    parts.append("[ca]alimiter=limit=0.95[aout]")
    filter_path.write_text(";\n".join(parts))


def _in_video_title_overlay(style):
    return _video_title_spec(style)


def render_video(video, filter_path, output, memory):
    write_progress(output.parent, "render", "正在輸出壓縮後的 IG Reels 影片")
    log("5/7 Rendering compressed IG Reels MP4")
    export = memory["export"]
    preset = export.get("x264_preset", "medium")
    crf = str(int(export.get("crf", 22)))
    # NOTE: we encode in CRF mode rather than CBR/VBV. The previous CBR config
    # (`-b:v ... -maxrate ... -bufsize ...`) starved the encoder on the very
    # short first trim+concat piece (<1s) and produced a flat grey first
    # ~30 frames. CRF gives consistent per-frame quality and keeps frame 0
    # painted from the start, which matters more than hitting an exact bitrate.
    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(video),
        "-filter_complex_script", str(filter_path),
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", preset,
        "-profile:v", "high",
        "-level", "4.1",
        "-crf", crf,
        "-maxrate", export.get("maxrate", "4000k"),
        "-bufsize", export.get("bufsize", "8000k"),
        "-pix_fmt", export["pix_fmt"],
        "-c:a", "aac",
        "-b:a", export["audio_bitrate"],
        "-movflags", "+faststart",
        str(output),
    ]
    run(cmd)


def text_width(draw, text, font, stroke_width=0):
    box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    return box[2] - box[0]


def draw_centered(draw, text, y, font, fill, stroke_width=4):
    x = (720 - text_width(draw, text, font, stroke_width)) / 2
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=(0, 0, 0))


def frame_quality(path):
    im = Image.open(path).convert("RGB")
    gray = im.convert("L")
    sharpness = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).var[0]
    brightness = ImageStat.Stat(gray).mean[0]
    contrast = ImageStat.Stat(gray).stddev[0]
    w, h = gray.size

    eye_box = (int(w * 0.18), int(h * 0.26), int(w * 0.82), int(h * 0.46))
    eye_crop = gray.crop(eye_box)
    eye_pixels = list(eye_crop.getdata())
    eye_dark_ratio = sum(1 for value in eye_pixels if value < 90) / max(1, len(eye_pixels))
    eye_edges = eye_crop.filter(ImageFilter.FIND_EDGES)
    eye_edge_var = ImageStat.Stat(eye_edges).var[0]
    eye_edge_mean = ImageStat.Stat(eye_edges).mean[0]

    face_box = (int(w * 0.14), int(h * 0.20), int(w * 0.86), int(h * 0.66))
    face_gray = gray.crop(face_box)
    face_color = im.crop(face_box)
    face_edge_var = ImageStat.Stat(face_gray.filter(ImageFilter.FIND_EDGES)).var[0]
    face_color_stddev = sum(ImageStat.Stat(face_color).stddev) / 3

    brightness_penalty = abs(brightness - 132) * 0.35

    # Closed eyes: no dark pupils against skin, and almost no horizontal edges in the eye band.
    blink_penalty = 0
    if eye_dark_ratio < 0.012:
        blink_penalty += 220
    if eye_edge_mean < 16:
        blink_penalty += 160

    # Back of head / facing away: face crop is featureless (low edges) and color is too uniform.
    back_head_penalty = 0
    if face_edge_var < 320 and face_color_stddev < 30:
        back_head_penalty += 320
    elif face_edge_var < 220:
        back_head_penalty += 160

    eye_open_bonus = max(0, eye_edge_mean - 20) * 4
    face_feature_bonus = min(140, max(0, face_edge_var - 400) * 0.25)

    return (
        sharpness
        + contrast
        + eye_dark_ratio * 1800
        + eye_open_bonus
        + face_feature_bonus
        - brightness_penalty
        - blink_penalty
        - back_head_penalty
    )


def extract_cover_candidate(video, candidate_path, seek):
    run([
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-ss", f"{seek:.2f}",
        "-i", str(video),
        "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
        "-frames:v", "1",
        "-update", "1",
        str(candidate_path),
    ])


def pick_cover_candidates(video, frame, hook_time, duration, top_n=5):
    base = hook_time if hook_time is not None else duration * 0.18
    raw_seeks = [
        base - 1.0, base - 0.55, base, base + 0.45, base + 0.9,
        duration * 0.22, duration * 0.38, duration * 0.55,
        duration * 0.70,
    ]
    candidates = []
    for index, raw_seek in enumerate(raw_seeks):
        seek = min(max(raw_seek, 0.7), max(duration - 0.7, 0.7))
        candidate = frame.with_name(f"cover_candidate_{index}.jpg")
        try:
            extract_cover_candidate(video, candidate, seek)
            score = frame_quality(candidate)
        except Exception:
            continue
        candidates.append({"path": candidate, "seek": seek, "score": score})

    if not candidates:
        fallback_seek = min(max(base, 0.7), max(duration - 0.7, 0.7))
        extract_cover_candidate(video, frame, fallback_seek)
        return fallback_seek, []

    candidates.sort(key=lambda item: item["score"], reverse=True)
    top = candidates[:top_n]
    shutil.copy2(top[0]["path"], frame)
    # Discard the unused candidate files so the output directory stays small.
    kept_paths = {item["path"] for item in top}
    for item in candidates[top_n:]:
        try:
            item["path"].unlink()
        except FileNotFoundError:
            pass
    return top[0]["seek"], top



# IG Reels cover styles — each entry now defines a *complete* palette that
# carries through the cover, the burnt-in title, AND the subtitles. Picking a
# different cover therefore changes every typographic accent in the export, so
# the deliverable always feels like one piece.
#
# Band height notes: keep the top band under ~33 % of the cover so the face
# stays unmistakably the focal point — the reference image the user shared has
# a noticeably *small* top band, not a half-screen letterbox.
COVER_STYLES = {
    # ── Editorial Bold ──────────────────────────────────────────────────────
    # Knowledge-Reels look — black band at the top + bottom, white headline
    # with marigold yellow accent. This is the user's approved baseline; do
    # NOT change the positions, band sizes, or fonts here.
    "editorial": {
        "cover": {
            "top_band": {"y0": 0, "y1": 420, "rgb": (0, 0, 0), "alpha": 92},
            "bottom_band": {"y0": 1054, "y1": 1280, "rgb": (0, 0, 0), "alpha": 110},
            "fonts": {"pov": 36, "big": 62, "mid": 50, "en": 30},
            "colors": {
                "pov": (255, 255, 255, 255),
                "main_1": (255, 255, 255, 255),
                "main_2": (247, 218, 83, 255),
                "english": (255, 255, 255, 240),
                "bottom_1": (255, 255, 255, 255),
                "bottom_2": (247, 218, 83, 255),
            },
            "ys": {"pov": 76, "main_1": 130, "main_2": 214, "english": 308, "bottom_1": 1108, "bottom_2": 1188},
            "stroke": {"pov": 3, "main": 5, "english": 3, "bottom": 5},
        },
        "video_title": {
            # Band big enough to wrap both title lines with safe padding on
            # top and bottom. Line 1 top = title_y_top; line 2 top =
            # title_y_top + line_height; each line is fontsize tall, so the
            # last pixel is roughly title_y_top + line_height + fontsize.
            "band_h": 290,
            "band_color": "black@0.48",
            "title_y_top": 80,
            "line_height": 72,
            "fontsize": 46,
            "main_color": "white",
            "accent_color": "0xF7DA53",
            "borderw": 4,
            "border_alpha": 0.78,
        },
        "subtitle": {
            # ASS uses &HAABBGGRR (alpha-blue-green-red).
            # User asked for unified white ZH + hairline border for legibility.
            "zh_primary": "&H00FFFFFF",
            "zh_outline": "&H50000000",
            "en_primary": "&H0053DAF7",  # marigold yellow #F7DA53
            "en_outline": "&H80000000",
        },
    },

    # ── All-White Hook / 全白爆點 ──────────────────────────────────────────
    # SAME typographic positions + fonts as Editorial Bold, but every accent
    # is white and the bands are removed. The text floats on the photo with
    # a slightly thicker black stroke for legibility.
    "hook_caption": {
        "layout": "editorial",
        "cover": {
            "top_band": {"y0": 0, "y1": 0, "rgb": (0, 0, 0), "alpha": 0},
            "bottom_band": {"y0": 0, "y1": 0, "rgb": (0, 0, 0), "alpha": 0},
            "fonts": {"pov": 36, "big": 62, "mid": 50, "en": 30},
            "colors": {
                "pov": (255, 255, 255, 255),
                "main_1": (255, 255, 255, 255),
                "main_2": (255, 255, 255, 255),
                "english": (255, 255, 255, 240),
                "bottom_1": (255, 255, 255, 255),
                "bottom_2": (255, 255, 255, 255),
            },
            "ys": {"pov": 76, "main_1": 130, "main_2": 214, "english": 308, "bottom_1": 1108, "bottom_2": 1188},
            "stroke": {"pov": 4, "main": 7, "english": 4, "bottom": 6},
        },
        "video_title": {
            "band_h": 290,
            "band_color": "black@0.34",
            "title_y_top": 80,
            "line_height": 72,
            "fontsize": 46,
            "main_color": "white",
            "accent_color": "0x3CE65A",       # auto-caption neon green
            "borderw": 5,
            "border_alpha": 0.85,
        },
        "subtitle": {
            # Pure white ZH with a near-invisible black outline — the user's
            # explicit request: white captions, very thin border for legibility.
            "zh_primary": "&H00FFFFFF",
            "zh_outline": "&H50000000",
            "en_primary": "&H003CE65A",       # auto-caption green
            "en_outline": "&H80000000",
        },
    },

    # ── Color Pop / 繽紛大字 ────────────────────────────────────────────────
    # Canva-style centered hero: a very faint black scrim across the whole
    # cover (so the headline reads on any background) + a single big bold
    # statement split across two lines, each in a different bright colour.
    # No POV label, no bottom hook line — just the hero.
    "magazine_pop": {
        "layout": "centered_hero",
        "cover": {
            "scrim": {"y0": 0, "y1": 1280, "rgb": (0, 0, 0), "alpha": 48},
            # English glyphs are visually wider than CJK at the same em size,
            # so we use a slightly smaller `big_en` to keep the headline
            # comfortably inside the 720 px canvas.
            "fonts": {"big": 84, "big_en": 64, "en": 38},
            "colors": {
                # Orange + lime — straight off the Canva reference the user
                # shared. Both have ~85 % luminance so neither line "wins".
                "main_1": (245, 138, 56, 255),    # warm orange
                "main_2": (150, 222, 78, 255),    # lime green
                "english": (255, 255, 255, 255),
            },
            # Centered around the vertical middle of the cover so the face stays
            # visible above and below.
            "ys": {"main_1": 526, "main_2": 626, "english": 760},
            "stroke": {"main": 6, "english": 3},
        },
        "video_title": {
            "band_h": 290,
            "band_color": "black@0.36",
            "title_y_top": 80,
            "line_height": 72,
            "fontsize": 46,
            "main_color": "0xF58A38",         # orange
            "accent_color": "0x96DE4E",       # lime
            "borderw": 4,
            "border_alpha": 0.78,
        },
        "subtitle": {
            "zh_primary": "&H00FFFFFF",
            "zh_outline": "&H50000000",
            "en_primary": "&H004EDE96",       # lime (#96DE4E) in BGR
            "en_outline": "&H80000000",
        },
    },
}

# Backwards-compat aliases for old slugs so saved jobs / cached requests don't
# break after the redesign.
COVER_STYLES["creator"] = COVER_STYLES["hook_caption"]
COVER_STYLES["high_contrast"] = COVER_STYLES["magazine_pop"]


def _video_title_spec(style):
    return (COVER_STYLES.get(style) or COVER_STYLES["editorial"])["video_title"]


def _subtitle_spec(style):
    return (COVER_STYLES.get(style) or COVER_STYLES["editorial"])["subtitle"]


def _paint_band(overlay, band):
    if not band or band.get("y1", 0) <= band.get("y0", 0) or band.get("alpha", 0) <= 0:
        return
    od = ImageDraw.Draw(overlay)
    color = (*band["rgb"], band["alpha"])
    od.rectangle([0, band["y0"], overlay.size[0], band["y1"]], fill=color)


def _resolve_cover_lines(cover, language):
    if language == "en":
        # Never fall back to Chinese strings in English mode — the EN fonts
        # we load don't carry CJK glyphs and would render as tofu boxes.
        main_1 = cover.get("en_main_line_1") or ""
        main_2 = cover.get("en_main_line_2") or ""
        if not main_1:
            split = _split_en_headline(cover.get("english_line") or cover.get("main_line_1", ""))
            main_1, main_2 = split[0], split[1] if len(split) > 1 else main_2
        return {
            "pov":     cover.get("top_label", "POV"),
            "main_1":  main_1,
            "main_2":  main_2,
            "english": "",
            "bottom_1": cover.get("en_bottom_line_1") or "",
            "bottom_2": cover.get("en_bottom_line_2") or "",
        }
    return {
        "pov":      cover.get("top_label", "POV"),
        "main_1":   cover.get("main_line_1", ""),
        "main_2":   cover.get("main_line_2", ""),
        "english":  cover.get("english_line", ""),
        "bottom_1": cover.get("bottom_line_1", ""),
        "bottom_2": cover.get("bottom_line_2", ""),
    }


def render_cover(frame_path, output, memory, cover_copy=None, style=None, language=None):
    cover = cover_copy or memory["cover"]
    style = style or memory.get("runtime_options", {}).get("cover_style", cover.get("default_style", "editorial"))
    language = (language or memory.get("runtime_options", {}).get("language", "zh")).lower()
    style_entry = COVER_STYLES.get(style) or COVER_STYLES["editorial"]
    spec = style_entry["cover"]
    layout = style_entry.get("layout", "default")

    im = Image.open(frame_path).convert("RGB")
    target_size = (720, 1280)
    if im.size != target_size:
        im = im.resize(target_size, Image.LANCZOS)
    im = ImageEnhance.Contrast(im).enhance(1.06)
    im = ImageEnhance.Color(im).enhance(1.04).convert("RGBA")

    if layout == "centered_hero":
        _render_centered_hero(im, spec, cover, language)
    else:
        _render_editorial(im, spec, cover, language)

    im.convert("RGB").save(output, quality=92)


def _render_editorial(im, spec, cover, language):
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    _paint_band(overlay, spec.get("top_band"))
    _paint_band(overlay, spec.get("bottom_band"))
    composited = Image.alpha_composite(im, overlay)
    im.paste(composited, (0, 0))
    draw = ImageDraw.Draw(im)
    lines = _resolve_cover_lines(cover, language)
    ys = spec["ys"]
    colors = spec["colors"]
    stroke = spec["stroke"]
    if language == "en":
        big_font = ImageFont.truetype(FONT_EN, spec["fonts"]["big"])
        bottom_font = ImageFont.truetype(FONT_EN, spec["fonts"]["mid"])
        pov_font = ImageFont.truetype(FONT_EN, spec["fonts"]["pov"])
        draw_centered(draw, lines["pov"], ys["pov"], pov_font, colors["pov"], stroke["pov"])
        draw_centered(draw, lines["main_1"], ys["main_1"], big_font, colors["main_1"], stroke["main"])
        if lines["main_2"]:
            draw_centered(draw, lines["main_2"], ys["main_2"], big_font, colors["main_2"], stroke["main"])
        draw_centered(draw, lines["bottom_1"], ys["bottom_1"], bottom_font, colors["bottom_1"], stroke["bottom"])
        if lines["bottom_2"]:
            draw_centered(draw, lines["bottom_2"], ys["bottom_2"], bottom_font, colors["bottom_2"], stroke["bottom"])
        return
    fonts_pov = ImageFont.truetype(FONT_EN, spec["fonts"]["pov"])
    fonts_big = ImageFont.truetype(FONT_ZH, spec["fonts"]["big"])
    fonts_mid = ImageFont.truetype(FONT_ZH, spec["fonts"]["mid"])
    fonts_en = ImageFont.truetype(FONT_EN, spec["fonts"]["en"])
    draw_centered(draw, lines["pov"], ys["pov"], fonts_pov, colors["pov"], stroke["pov"])
    draw_centered(draw, lines["main_1"], ys["main_1"], fonts_big, colors["main_1"], stroke["main"])
    draw_centered(draw, lines["main_2"], ys["main_2"], fonts_big, colors["main_2"], stroke["main"])
    draw_centered(draw, lines["english"], ys["english"], fonts_en, colors["english"], stroke["english"])
    draw_centered(draw, lines["bottom_1"], ys["bottom_1"], fonts_mid, colors["bottom_1"], stroke["bottom"])
    draw_centered(draw, lines["bottom_2"], ys["bottom_2"], fonts_mid, colors["bottom_2"], stroke["bottom"])


def _render_centered_hero(im, spec, cover, language):
    """User-requested Style 3.

    Whole-cover faint black scrim + two big bold lines in contrasting colours.
    No POV, no bottom hook — just a clean centred headline."""
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    scrim = spec.get("scrim")
    if scrim:
        _paint_band(overlay, scrim)
    composited = Image.alpha_composite(im, overlay)
    im.paste(composited, (0, 0))
    draw = ImageDraw.Draw(im)

    lines = _resolve_cover_lines(cover, language)
    main_1 = lines.get("main_1") or ""
    main_2 = lines.get("main_2") or ""
    # Sentence-case English (no UPPER) — reads as editorial and stops the
    # headline from going wider than the cover.

    if language == "en":
        size = spec["fonts"].get("big_en") or spec["fonts"]["big"]
        big_font = ImageFont.truetype(FONT_EN, size)
    else:
        big_font = ImageFont.truetype(FONT_ZH, spec["fonts"]["big"])
    ys = spec["ys"]
    colors = spec["colors"]
    stroke = spec["stroke"]

    if main_1:
        draw_centered(draw, main_1, ys["main_1"], big_font, colors["main_1"], stroke["main"])
    if main_2:
        draw_centered(draw, main_2, ys["main_2"], big_font, colors["main_2"], stroke["main"])

    # Style 3 deliberately drops the POV label and the bottom hook line —
    # the user asked for "just the special hero, nothing else above or below".


def make_cover(video, output, memory, cover_copy=None, hook_time=None, job_dir=None, language=None):
    if job_dir:
        write_progress(job_dir, "render", "正在挑選最適合當 hook 的封面畫面")
    log("6/7 Creating cover")
    frame = output.with_name("cover_base.jpg")
    duration = ffprobe_duration(video)
    selected_seek, candidates = pick_cover_candidates(video, frame, hook_time, duration)
    log(f"Selected cover frame at {selected_seek:.2f}s")
    render_cover(frame, output, memory, cover_copy, language=language)
    return selected_seek, candidates


def process_video(source, job_dir, options_path=None):
    memory = load_memory(options_path)
    job_dir.mkdir(parents=True, exist_ok=True)
    write_progress(job_dir, "validate", "正在檢查影片並準備處理")
    input_video = job_dir / ("input" + Path(source).suffix.lower())
    if Path(source).resolve() != input_video.resolve():
        shutil.copy2(source, input_video)
    wav = job_dir / "audio_16k.wav"
    silence_log = job_dir / "silence.log"
    zh_json = job_dir / "transcript_zh.json"
    en_json = job_dir / "transcript_en.json"
    ass_path = job_dir / "subtitles.ass"
    filter_path = job_dir / "filter.txt"
    output = job_dir / "reels_ig_compressed.mp4"
    cover = job_dir / "reels_cover.jpg"

    extract_audio(input_video, wav, job_dir)
    detect_silence(input_video, silence_log, memory, job_dir)
    model = load_whisper(memory, job_dir)
    zh_segments = transcribe(model, memory, wav, zh_json, "transcribe", job_dir)
    en_segments = transcribe(model, memory, wav, en_json, "translate", job_dir) if memory["subtitle"]["bilingual"] else []
    write_progress(job_dir, "render", "正在 digest 內容，挑選 hook 與封面文案")
    cover_copy, hook_segment = build_cover_copy(memory, zh_segments, en_segments)
    log("4/7 Building edit timeline and subtitles")
    duration = ffprobe_duration(input_video)
    pieces = build_pieces(duration, parse_silences(silence_log), memory)
    timeline = make_timeline(pieces)
    write_progress(job_dir, "render", "正在建立剪輯時間軸與雙語字幕")
    runtime_style = memory.get("runtime_options", {}).get("cover_style", memory["cover"].get("default_style", "editorial"))
    runtime_lang = memory.get("runtime_options", {}).get("language", "zh")
    build_ass(zh_segments, en_segments, timeline, ass_path, memory, cover_style=runtime_style, language=runtime_lang)
    build_filter(input_video, pieces, ass_path, filter_path, memory)
    render_video(input_video, filter_path, output, memory)
    hook_time = ((hook_segment["start"] + hook_segment["end"]) / 2) if hook_segment else None
    selected_seek, candidates = make_cover(input_video, cover, memory, cover_copy, hook_time, job_dir, language=runtime_lang)
    cover_candidates = [
        {
            "filename": item["path"].name,
            "seek_seconds": round(item["seek"], 2),
            "score": round(float(item["score"]), 2),
            "selected": item["path"].name == "cover_candidate_0.jpg" or item["seek"] == selected_seek,
        }
        for item in candidates
    ]
    # Mark exactly one as selected — the highest-scoring one we copied to cover_base.
    if cover_candidates:
        for item in cover_candidates:
            item["selected"] = False
        cover_candidates[0]["selected"] = True
    metadata = {
        "video": output.name,
        "cover": cover.name,
        "duration_seconds": round(timeline[-1]["dst_end"] if timeline else 0, 2),
        "pieces": len(pieces),
        "cover_style": memory.get("runtime_options", {}).get("cover_style", memory["cover"].get("default_style")),
        "language": runtime_lang,
        "cover_copy": cover_copy,
        "hook_time_seconds": round(hook_time, 2) if hook_time is not None else None,
        "hook_text": clean_zh(hook_segment["text"]) if hook_segment else None,
        "cover_candidates": cover_candidates,
        "selected_cover_candidate": cover_candidates[0]["filename"] if cover_candidates else None,
        "memory": memory,
    }
    (job_dir / "result.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    write_progress(job_dir, "done", "影片與封面都完成了")
    log("7/7 Done")
    return metadata


def main():
    if len(sys.argv) not in {3, 4}:
        print("Usage: python3 reels_gui_pipeline.py INPUT_VIDEO OUTPUT_DIR [OPTIONS_JSON]", file=sys.stderr)
        raise SystemExit(2)
    options_path = Path(sys.argv[3]) if len(sys.argv) == 4 else None
    result = process_video(Path(sys.argv[1]), Path(sys.argv[2]), options_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
