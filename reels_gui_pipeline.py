import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from faster_whisper import WhisperModel
from opencc import OpenCC
from PIL import Image, ImageDraw, ImageEnhance, ImageFont


ROOT = Path(__file__).resolve().parent
MEMORY = ROOT / "reels_memory.json"
FONT_ZH = "/System/Library/Fonts/STHeiti Medium.ttc"
FONT_EN = "/System/Library/Fonts/HelveticaNeue.ttc"


def log(message):
    print(message, flush=True)


def run(cmd, capture=False):
    if capture:
        return subprocess.run(cmd, check=True, text=True, capture_output=True)
    subprocess.run(cmd, check=True)
    return None


def load_memory():
    return json.loads(MEMORY.read_text())


def ffprobe_duration(video):
    result = run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        str(video),
    ], capture=True)
    return float(result.stdout.strip())


def extract_audio(video, wav):
    log("1/7 Extracting audio")
    run([
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(video),
        "-vn", "-ac", "1", "-ar", "16000",
        str(wav),
    ])


def detect_silence(video, log_path, memory):
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


def transcribe(wav, out_json, task="transcribe"):
    label = "Chinese transcription" if task == "transcribe" else "English translation"
    log(f"3/7 Running {label}")
    model = WhisperModel("large-v3-turbo", device="cpu", compute_type="int8")
    segments, info = model.transcribe(
        str(wav),
        language="zh",
        task=task,
        vad_filter=True,
        beam_size=5,
        word_timestamps=False,
        condition_on_previous_text=True,
    )
    rows = []
    for seg in segments:
        text = seg.text.strip()
        if text:
            rows.append({"start": seg.start, "end": seg.end, "text": text})
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


def build_pieces(duration, silences):
    cuts = []
    for start, end in silences:
        cut_start = max(0, start + 0.06)
        cut_end = min(duration, end - 0.10)
        if cut_end - cut_start >= 0.18:
            cuts.append((cut_start, cut_end))
    pieces = subtract_ranges((0.0, duration), cuts)
    merged = []
    for start, end in pieces:
        if end - start < 0.22:
            continue
        if merged and start - merged[-1][1] < 0.12:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
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


def clean_zh(text):
    text = OpenCC("s2t").convert(text)
    replacements = {
        "cloud": " Claude ",
        "Cloud": " Claude ",
        "Claude": " Claude ",
        "AI": " AI ",
        "IG": " IG ",
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
    text = re.sub(r"\b([A-Za-z][A-Za-z0-9/+\-.]*)\b", r" \1 ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(就是|然後|那|嗯|呃|啊)[，, ]*", "", text).strip()
    text = re.sub(r"(啊|嘛|呢|吧)$", "", text).strip()
    return text


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


def ass_escape(text):
    return text.replace("{", "").replace("}", "")


def build_ass(zh_segments, en_segments, timeline, ass_path, memory):
    sub = memory["subtitle"]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: ZH,STHeiti,{sub['chinese_font_size']},&H00FFFFFF,&H00FFFFFF,&HAA000000,&H70000000,1,0,0,0,100,100,{sub['chinese_letter_spacing']},0,1,5,1,2,80,80,{sub['chinese_bottom_margin']},1
Style: EN,Helvetica Neue,{sub['english_font_size']},&H00F2F2F2,&H00FFFFFF,&HA8000000,&H70000000,0,0,0,0,100,100,{sub['english_letter_spacing']},0,1,4,0,2,90,90,{sub['english_bottom_margin']},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for seg in zh_segments:
        for item in intersections(seg, timeline):
            start, end = item["start"], max(item["end"], item["start"] + 0.65)
            zh = ass_escape(wrap_zh(clean_zh(item["text"])))
            if zh:
                lines.append(f"Dialogue: 1,{ass_ts(start)},{ass_ts(end)},ZH,,0,0,0,,{zh}\n")
    if sub["bilingual"]:
        for seg in en_segments:
            for item in intersections(seg, timeline):
                start, end = item["start"], max(item["end"], item["start"] + 0.65)
                en = ass_escape(wrap_en(item["text"]))
                if en:
                    lines.append(f"Dialogue: 0,{ass_ts(start)},{ass_ts(end)},EN,,0,0,0,,{en}\n")
    ass_path.write_text("".join(lines))


def build_filter(video, pieces, ass_path, filter_path, memory):
    labels, parts = [], []
    for i, (start, end) in enumerate(pieces):
        parts.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS,"
            "scale=720:1280:force_original_aspect_ratio=increase,"
            "crop=720:1280,setsar=1[v{0}]".format(i)
        )
        parts.append(
            f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS,"
            "highpass=f=80,lowpass=f=12000,"
            "acompressor=threshold=-18dB:ratio=2.2:attack=8:release=120,"
            "volume=1.15[a{0}]".format(i)
        )
        labels.append(f"[v{i}][a{i}]")
    parts.append("".join(labels) + f"concat=n={len(pieces)}:v=1:a=1[cv][ca]")
    title = memory["title"]
    title_1 = title.replace(" 小編", "\\n小編") if " 小編" in title else title
    subs_path = str(ass_path).replace("\\", "\\\\").replace(":", "\\:")
    parts.append(
        "[cv]"
        f"drawtext=fontfile='{FONT_ZH}':text='{title_1}':x=(w-text_w)/2:y=145:"
        "fontsize=38:line_spacing=8:fontcolor=white:borderw=4:bordercolor=black@0.72:shadowx=2:shadowy=2,"
        f"subtitles='{subs_path}',format=yuv420p[vout]"
    )
    parts.append("[ca]alimiter=limit=0.95[aout]")
    filter_path.write_text(";\n".join(parts))


def render_video(video, filter_path, output, memory):
    log("5/7 Rendering compressed IG Reels MP4")
    export = memory["export"]
    run([
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(video),
        "-filter_complex_script", str(filter_path),
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-profile:v", "high",
        "-level", "4.1",
        "-b:v", export["video_bitrate"],
        "-maxrate", export["maxrate"],
        "-bufsize", export["bufsize"],
        "-pix_fmt", export["pix_fmt"],
        "-c:a", "aac",
        "-b:a", export["audio_bitrate"],
        "-movflags", "+faststart",
        str(output),
    ])


def text_width(draw, text, font, stroke_width=0):
    box = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    return box[2] - box[0]


def draw_centered(draw, text, y, font, fill, stroke_width=4):
    x = (720 - text_width(draw, text, font, stroke_width)) / 2
    draw.text((x, y), text, font=font, fill=fill, stroke_width=stroke_width, stroke_fill=(0, 0, 0))


def make_cover(video, output, memory):
    log("6/7 Creating cover")
    frame = output.with_name("cover_base.jpg")
    duration = ffprobe_duration(video)
    seek = min(max(duration * 0.12, 1.0), max(duration - 1.0, 1.0))
    run([
        "ffmpeg", "-hide_banner", "-y",
        "-ss", f"{seek:.2f}",
        "-i", str(video),
        "-vf", "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280",
        "-frames:v", "1",
        str(frame),
    ])
    cover = memory["cover"]
    im = Image.open(frame).convert("RGB")
    im = ImageEnhance.Contrast(im).enhance(1.08)
    im = ImageEnhance.Color(im).enhance(1.05).convert("RGBA")
    overlay = Image.new("RGBA", im.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rectangle([0, 0, 720, 360], fill=(0, 0, 0, 92))
    od.rectangle([0, 840, 720, 1280], fill=(0, 0, 0, 122))
    im = Image.alpha_composite(im, overlay)
    draw = ImageDraw.Draw(im)
    font_pov = ImageFont.truetype(FONT_EN, 36)
    font_big = ImageFont.truetype(FONT_ZH, 54)
    font_mid = ImageFont.truetype(FONT_ZH, 43)
    font_en = ImageFont.truetype(FONT_EN, 28)
    white = (255, 255, 255, 255)
    yellow = (247, 218, 83, 255)
    draw_centered(draw, cover["top_label"], 118, font_pov, white, 3)
    draw_centered(draw, cover["main_line_1"], 165, font_big, white, 4)
    draw_centered(draw, cover["main_line_2"], 235, font_big, yellow, 4)
    draw_centered(draw, cover["english_line"], 315, font_en, white, 2)
    draw_centered(draw, cover["bottom_line_1"], 895, font_mid, white, 4)
    draw_centered(draw, cover["bottom_line_2"], 955, font_mid, yellow, 4)
    im.convert("RGB").save(output, quality=92)


def process_video(source, job_dir):
    memory = load_memory()
    job_dir.mkdir(parents=True, exist_ok=True)
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

    extract_audio(input_video, wav)
    detect_silence(input_video, silence_log, memory)
    zh_segments = transcribe(wav, zh_json, "transcribe")
    en_segments = transcribe(wav, en_json, "translate") if memory["subtitle"]["bilingual"] else []
    log("4/7 Building edit timeline and subtitles")
    duration = ffprobe_duration(input_video)
    pieces = build_pieces(duration, parse_silences(silence_log))
    timeline = make_timeline(pieces)
    build_ass(zh_segments, en_segments, timeline, ass_path, memory)
    build_filter(input_video, pieces, ass_path, filter_path, memory)
    render_video(input_video, filter_path, output, memory)
    make_cover(input_video, cover, memory)
    metadata = {
        "video": output.name,
        "cover": cover.name,
        "duration_seconds": round(timeline[-1]["dst_end"] if timeline else 0, 2),
        "pieces": len(pieces),
        "memory": memory,
    }
    (job_dir / "result.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2))
    log("7/7 Done")
    return metadata


def main():
    if len(sys.argv) != 3:
        print("Usage: python3 reels_gui_pipeline.py INPUT_VIDEO OUTPUT_DIR", file=sys.stderr)
        raise SystemExit(2)
    result = process_video(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
