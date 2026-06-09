import json
import os
import platform
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


def _can_use_mlx():
    """Return True iff we're on Apple Silicon arm64 macOS AND mlx-whisper +
    Metal are usable. Anywhere else we fall back to faster-whisper CPU.

    mlx-whisper transcribes 20-60x realtime by running the encoder on the
    GPU (Metal) and the decoder on the ANE. faster-whisper CPU int8 is only
    ~2-4x realtime even with the turbo model -- nowhere near the 3min->1min
    budget. So this branch is the whole speed story on Apple Silicon.
    """
    if platform.system() != "Darwin":
        log(f"  MLX: skip ({platform.system()} != Darwin)")
        return False
    if platform.machine() != "arm64":
        log(f"  MLX: skip (arch={platform.machine()})")
        return False
    try:
        import mlx_whisper  # noqa: F401
        import mlx.core as mx
        ok = bool(mx.metal.is_available())
        log(f"  MLX import OK from {mlx_whisper.__file__}; metal available = {ok}")
        return ok
    except Exception as exc:
        import traceback
        log(f"  MLX detection FAILED: {type(exc).__name__}: {exc}")
        for line in traceback.format_exc().splitlines():
            log(f"    {line}")
        return False


def load_whisper(memory, job_dir=None):
    """Return a backend handle. Two shapes:
        ("mlx",  {"repo": "mlx-community/whisper-large-v3-turbo"})
        ("ctr",  WhisperModel(...))   # faster-whisper / ctranslate2
    The transcribe() function dispatches on the leading tag.
    """
    perf = memory.get("performance", {})
    if _can_use_mlx():
        repo = perf.get("mlx_whisper_repo", "mlx-community/whisper-large-v3-turbo")
        if job_dir:
            write_progress(job_dir, "transcribe", f"正在載入 Whisper {repo.split('/')[-1]} (MLX)")
        log(f"Loading Whisper (MLX backend): {repo}")
        return ("mlx", {"repo": repo})

    # Fallback: faster-whisper CPU (Intel macOS / Windows / Linux)
    model_name = perf.get("whisper_model", "Systran/faster-whisper-large-v3-turbo")
    compute_type = perf.get("compute_type", "int8")
    cpu_threads = int(perf.get("cpu_threads", 4))
    if job_dir:
        write_progress(job_dir, "transcribe", f"正在載入 Whisper {model_name}")
    log(f"Loading Whisper (faster-whisper CPU): {model_name} ({compute_type}, {cpu_threads} threads)")
    return ("ctr", WhisperModel(
        model_name,
        device="cpu",
        compute_type=compute_type,
        cpu_threads=cpu_threads,
        num_workers=1,
    ))


def load_translator(memory, job_dir=None):
    """Load the bundled CT2-converted opus-mt-zh-en model plus its
    SentencePiece tokenizers.

    The model is staged into models/opus-mt-zh-en/ at build time by
    scripts/fetch_translator.sh (which runs ct2-transformers-converter
    against Helsinki-NLP/opus-mt-zh-en with int8 quantisation). At runtime
    we only need ctranslate2 (already a dep via faster-whisper) and
    sentencepiece (~3 MB).

    Returns (translator, sp_src, sp_tgt) on success, or None if the bundle
    isn't present. Callers fall back to an empty EN list when None.
    """
    model_dir = ROOT / "models" / "opus-mt-zh-en"
    if not model_dir.is_dir() or not (model_dir / "model.bin").exists():
        log(f"  WARNING: translator model not found at {model_dir}")
        log("  EN subtitles will be empty. Run scripts/fetch_translator.sh.")
        return None
    if job_dir:
        write_progress(job_dir, "transcribe", "正在載入翻譯模型")
    log(f"Loading ZH->EN translator from {model_dir}")
    try:
        import ctranslate2
        import sentencepiece as spm
    except ImportError as exc:
        log(f"  WARNING: translator runtime deps missing: {exc}")
        return None
    perf = memory.get("performance", {})
    threads = int(perf.get("cpu_threads", 4))
    translator = ctranslate2.Translator(
        str(model_dir),
        device="cpu",
        compute_type="int8",
        intra_threads=threads,
    )
    sp_src = spm.SentencePieceProcessor()
    sp_src.Load(str(model_dir / "source.spm"))
    sp_tgt = spm.SentencePieceProcessor()
    sp_tgt.Load(str(model_dir / "target.spm"))
    return (translator, sp_src, sp_tgt)


_SENTENCE_TERMINATORS = ("。", "！", "？", "!", "?", ".")


def _group_zh_into_sentences(zh_segments, max_chars=80, max_gap=0.8):
    """Group consecutive ZH segments into sentence-like batches so Marian
    sees enough context to produce coherent English instead of fragments.

    A new batch starts when ANY of the following is true for the current
    segment:
      * Its text ends with terminal punctuation (Chinese or ASCII)
      * The gap to the next segment exceeds `max_gap` seconds (long pause)
      * The cumulative character count for the current batch exceeds
        `max_chars` (defensive cap so Marian context never explodes)

    Returns: list of (start_index, end_index) half-open ranges.
    """
    groups = []
    if not zh_segments:
        return groups
    cur_start = 0
    cur_chars = 0
    for i, zh in enumerate(zh_segments):
        cur_chars += len(zh.get("text", ""))
        text_clean = (zh.get("text") or "").rstrip(" 、,，；;\t\n")
        terminal = text_clean.endswith(_SENTENCE_TERMINATORS)
        next_gap = (
            (zh_segments[i + 1]["start"] - zh["end"])
            if i + 1 < len(zh_segments) else 0.0
        )
        if terminal or next_gap > max_gap or cur_chars > max_chars:
            groups.append((cur_start, i + 1))
            cur_start = i + 1
            cur_chars = 0
    if cur_start < len(zh_segments):
        groups.append((cur_start, len(zh_segments)))
    return groups


def produce_en_segments(memory, wav, zh_segments, out_json, job_dir=None):
    """Top-level dispatch for ZH -> EN subtitle production.

    On Apple Silicon arm64 with MLX available: runs mlx-whisper-medium with
    task='translate' against the source audio. Quality on talking-head
    Chinese is dramatically better than dedicated NMT models (tested Marian
    opus-mt-zh-en, NLLB-200-distilled-600M) because Whisper was pre-trained
    on subtitled video data exactly like the user's content. Cost: ~98s on
    3-min audio (one-time model download ~1.5 GB on first run).

    Elsewhere (Intel macOS, Windows, Linux): falls back to the bundled
    Marian opus-mt-zh-en CT2 model. Faster (~1s) but lower quality.

    Returns a list of {"start", "end", "text"} segments. Whisper translate
    decides its own segment boundaries, so downstream build_ass uses
    _build_en_assignments to distribute these across the (separately
    produced) ZH segments by time-overlap.
    """
    if _can_use_mlx():
        return _translate_with_mlx_whisper(memory, wav, out_json, job_dir)
    translator = load_translator(memory, job_dir)
    return translate_zh_to_en(translator, zh_segments, out_json, job_dir)


def _translate_with_mlx_whisper(memory, wav, out_json, job_dir=None):
    """ZH -> EN translation via mlx-whisper task='translate'.

    Uses a SEPARATE Whisper model from the ZH-transcribe pass (the turbo
    model used for transcribe does not support translate well -- it was
    trained without translation data). We default to whisper-medium-mlx
    which balances quality (much better than Marian / NLLB-600M) against
    speed (~98s on 3-min audio, vs whisper-large-v3's ~400s).
    """
    perf = memory.get("performance", {})
    repo = perf.get("mlx_translate_repo", "mlx-community/whisper-medium-mlx")
    if job_dir:
        write_progress(job_dir, "transcribe", f"正在翻譯英文字幕（Whisper translate）")
    log(f"3b/7 ZH -> EN translation via mlx-whisper {repo}")
    import mlx_whisper
    result = mlx_whisper.transcribe(
        str(wav),
        path_or_hf_repo=repo,
        task="translate",
        language="zh",
        temperature=0.0,
        condition_on_previous_text=False,  # off: faster, fewer hallucinations
        word_timestamps=False,
    )
    rows = []
    for seg in result.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        rows.append({
            "start": float(seg.get("start", 0.0)),
            "end": float(seg.get("end", 0.0)),
            "text": text,
        })
    log(f"  Whisper translate: {len(rows)} EN segments")
    if out_json:
        out_json.write_text(json.dumps(
            {"language": "en", "task": "mlx-whisper-translate", "backend": repo, "segments": rows},
            ensure_ascii=False, indent=2,
        ))
    return rows


def translate_zh_to_en(translator_bundle, zh_segments, out_json, job_dir=None):
    """Translate ZH segments to EN using Marian opus-mt-zh-en (CT2 int8).

    Strategy: merge consecutive ZH segments into sentence-level batches
    (`_group_zh_into_sentences`), translate each batch as ONE input so
    Marian has enough context to produce a coherent English sentence,
    then split the English words back to constituent ZH segments by
    char-count proportion. This avoids the per-segment-translation
    fragmentation that produces repeated words and untranslated mid-clause
    fragments leaking source CJK characters.

    Returns rows aligned 1:1 with zh_segments using the
    {"start", "end", "text"} shape downstream code expects.
    """
    if not zh_segments or translator_bundle is None:
        if out_json:
            out_json.write_text(
                json.dumps({"language": "en", "task": "translate-marian", "segments": []}, ensure_ascii=False, indent=2)
            )
        return []
    if job_dir:
        write_progress(job_dir, "transcribe", "正在翻譯英文字幕")
    translator, sp_src, sp_tgt = translator_bundle

    groups = _group_zh_into_sentences(zh_segments)
    log(f"3b/7 ZH -> EN translation ({len(zh_segments)} segments grouped into {len(groups)} sentences via Marian)")

    # Build one source string per sentence group. We strip per-segment text
    # to avoid double-spacing, and Marian's SentencePiece tokenizer handles
    # the joined Chinese fine without needing explicit word boundaries.
    batch_sources = []
    for start_idx, end_idx in groups:
        merged_zh = "".join(zh_segments[i].get("text", "").strip() for i in range(start_idx, end_idx))
        batch_sources.append(merged_zh)
    src_tokens = [sp_src.EncodeAsPieces(text) if text else [] for text in batch_sources]

    results = translator.translate_batch(
        src_tokens,
        beam_size=2,             # slight quality bump vs greedy, still cheap
        max_decoding_length=384,
        replace_unknowns=True,
        no_repeat_ngram_size=2,  # blocks "Today today" / "First of first" / "design designs"
        repetition_penalty=1.2,  # extra nudge against Marian's loop pathology
    )

    # Per-group: decode EN, then proportionally split EN words back to
    # constituent ZH segments by ZH char count so each subtitle frame still
    # gets its own EN line aligned to its audio window.
    rows = [None] * len(zh_segments)
    for (start_idx, end_idx), result in zip(groups, results):
        if result.hypotheses:
            full_en = sp_tgt.DecodePieces(result.hypotheses[0]).strip()
        else:
            full_en = ""
        en_words = full_en.split()
        constituent = list(range(start_idx, end_idx))

        if len(constituent) == 1:
            rows[constituent[0]] = {
                "start": zh_segments[constituent[0]]["start"],
                "end": zh_segments[constituent[0]]["end"],
                "text": full_en,
            }
            continue

        # Multi-segment group: divide EN words across ZH segments by ZH char
        # count (longer ZH chunk = bigger EN slice). Edge case: very short
        # EN with many ZH segments -- give each at least 1 word until we run
        # out, then leave the rest empty rather than padding nonsense.
        char_weights = [max(1, len(zh_segments[i].get("text", ""))) for i in constituent]
        total_weight = sum(char_weights)
        cursor = 0
        for slot_idx, zh_idx in enumerate(constituent):
            if slot_idx == len(constituent) - 1:
                portion = en_words[cursor:]
            else:
                share = max(1, int(round(len(en_words) * char_weights[slot_idx] / total_weight)))
                share = min(share, max(0, len(en_words) - cursor - (len(constituent) - slot_idx - 1)))
                portion = en_words[cursor:cursor + share]
                cursor += share
            rows[zh_idx] = {
                "start": zh_segments[zh_idx]["start"],
                "end": zh_segments[zh_idx]["end"],
                "text": " ".join(portion).strip(),
            }

    # Backfill any slot the loop missed with an empty placeholder so
    # downstream code can rely on 1:1 alignment.
    for i, zh in enumerate(zh_segments):
        if rows[i] is None:
            rows[i] = {"start": zh["start"], "end": zh["end"], "text": ""}

    if out_json:
        out_json.write_text(
            json.dumps({"language": "en", "task": "translate-marian-grouped", "segments": rows, "groups": groups}, ensure_ascii=False, indent=2)
        )
    return rows


def transcribe(model_handle, memory, wav, out_json, task="transcribe", job_dir=None):
    """Transcribe (or translate) `wav` using whichever Whisper backend was
    selected by load_whisper(). Returns the same {"start", "end", "text"}
    rows regardless of backend so downstream code is uniform.

    We DO NOT call this with task="translate" anymore -- ZH->EN now goes
    through Marian (translate_zh_to_en). This kwarg is kept for API
    compatibility / unusual call sites.
    """
    label = "Chinese transcription" if task == "transcribe" else "English translation"
    if job_dir:
        detail = "正在產生繁體中文字幕" if task == "transcribe" else "正在翻譯英文字幕"
        write_progress(job_dir, "transcribe", detail)
    perf = memory.get("performance", {})
    want_words = task == "transcribe" and perf.get("word_timestamps", True)

    backend, payload = model_handle
    if backend == "mlx":
        return _transcribe_mlx(payload, wav, out_json, task, want_words, label)
    return _transcribe_ctranslate2(payload, perf, wav, out_json, task, want_words, label)


def _transcribe_mlx(payload, wav, out_json, task, want_words, label):
    """MLX backend: Apple Neural Engine + Metal GPU. ~20-60x realtime on
    Apple Silicon -- the whole reason we hit a 1-minute budget on 3-min
    clips. Returns rows in our internal {start,end,text} shape.
    """
    log(f"3/7 Running {label} via mlx-whisper")
    import mlx_whisper
    result = mlx_whisper.transcribe(
        str(wav),
        path_or_hf_repo=payload["repo"],
        language="zh" if task == "transcribe" else "en",
        task=task,
        word_timestamps=bool(want_words),
        # mlx-whisper exposes the same VAD/condition options as openai-whisper:
        condition_on_previous_text=False,
        temperature=0.0,  # greedy -- no temperature fallback chain (faster)
    )
    rows = []
    for seg in result.get("segments", []):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start))
        if want_words and seg.get("words"):
            real_words = [w for w in seg["words"] if (w.get("word") or "").strip()]
            if real_words:
                start = float(real_words[0]["start"])
                end = float(real_words[-1]["end"])
        rows.append({"start": start, "end": end, "text": text})
    out_json.write_text(json.dumps({"language": result.get("language", "zh"), "task": task, "backend": "mlx", "segments": rows}, ensure_ascii=False, indent=2))
    return rows


def _transcribe_ctranslate2(model, perf, wav, out_json, task, want_words, label):
    """Fallback path: faster-whisper / CTranslate2 on CPU. Used on Intel
    macOS, Windows, Linux. Slower than MLX but works everywhere.
    """
    log(f"3/7 Running {label} via faster-whisper (CPU)")
    segments, info = model.transcribe(
        str(wav),
        language="zh",
        task=task,
        vad_filter=True,
        beam_size=int(perf.get("beam_size", 1)),
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
    out_json.write_text(json.dumps({"language": info.language, "task": task, "backend": "ctranslate2", "segments": rows}, ensure_ascii=False, indent=2))
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
    # Chinese-tuned padding: leave 280ms of audio on each side of every cut
    # so the syllable tail (Tone 3 dip, -n/-ng nasal release) and the next
    # syllable's onset are never clipped. Combined with the -42 dB / 0.55s
    # silencedetect threshold, only pauses longer than ~0.74s actually
    # produce a cut.
    cut_head_pad = float(edit.get("cut_head_padding", 0.28))
    cut_tail_pad = float(edit.get("cut_tail_padding", 0.28))
    min_cut_len = float(edit.get("min_cut_length", 0.18))
    protected_tail_start = max(0, duration - preserve_tail)
    cuts = []
    for start, end in silences:
        if end >= protected_tail_start:
            continue
        cut_start = max(0, start + cut_head_pad)
        cut_end = min(protected_tail_start, end - cut_tail_pad)
        if cut_end - cut_start >= min_cut_len:
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


_FULLWIDTH_HALFWIDTH_MAP = {
    # Fullwidth digits 0-9 (U+FF10..U+FF19)
    **{chr(0xFF10 + i): chr(0x30 + i) for i in range(10)},
    # Fullwidth uppercase A-Z (U+FF21..U+FF3A)
    **{chr(0xFF21 + i): chr(0x41 + i) for i in range(26)},
    # Fullwidth lowercase a-z (U+FF41..U+FF5A)
    **{chr(0xFF41 + i): chr(0x61 + i) for i in range(26)},
}


def fullwidth_to_halfwidth_ascii(text):
    """Convert fullwidth ASCII letters/digits to their halfwidth equivalents.

    Whisper occasionally emits fullwidth English letters or digits when it
    interprets them in a CJK context (e.g. "ＡＩ" instead of "AI"). We always
    want halfwidth for English content -- it's narrower and consistent with
    the rest of the burnt-in / subtitle pipeline.

    Punctuation is NOT converted: "，" stays Chinese-style inside Chinese
    text (a fullwidth comma between Chinese characters reads more
    naturally), but if it sits between ASCII tokens the wrap logic + clean_zh
    already strip it down.
    """
    if not text:
        return text
    return "".join(_FULLWIDTH_HALFWIDTH_MAP.get(ch, ch) for ch in text)


def normalize_cjk_ascii_spacing(text):
    """Make sure there is always a single space between Chinese and English /
    digit tokens. Punctuation is left untouched.

    The rule is documented in reels_memory.json (subtitle.mixed_language_spacing)
    so future edits stay consistent.
    """
    if not text:
        return text
    text = fullwidth_to_halfwidth_ascii(text)
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
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return text
    # Safety net for Marian passthrough failures. opus-mt-zh-en sometimes
    # leaks source CJK characters when it can't translate (short fragments,
    # rare phrases, mid-clause noun chunks). If more than ~25% of the
    # non-space characters are CJK, treat the whole EN as untrustworthy
    # rather than letting "And then 要跟大家講的是 you what" reach the burnt-in
    # caption.
    visible = re.sub(r"\s", "", text)
    if visible:
        cjk_count = sum(1 for ch in visible if "㐀" <= ch <= "鿿" or "豈" <= ch <= "﫿")
        if cjk_count / len(visible) > 0.25:
            return ""
    text = _dedupe_en_repetition(text)
    return normalize_cjk_ascii_spacing(text)


def _dedupe_en_repetition(text):
    """Strip Marian's classic repetition pathology that ngram-suppression
    misses: consecutive identical words ("today today"), case variants
    ("design Designs"), and immediate phrase echoes ("of the X of the X").

    Applied AFTER Marian output, so it cleans both the no_repeat_ngram_size
    misses and the post-batch concatenation seams.
    """
    if not text:
        return text
    # Collapse "word word" (case-insensitive) anywhere on the line.
    pattern_word = re.compile(r"\b(\w+)(\s+\1\b)+", flags=re.IGNORECASE)
    prev = None
    while prev != text:
        prev = text
        text = pattern_word.sub(r"\1", text)
    # Collapse "A B A B" -> "A B" for 2-grams.
    pattern_bigram = re.compile(r"\b(\w+\s+\w+)\s+\1\b", flags=re.IGNORECASE)
    prev = None
    while prev != text:
        prev = text
        text = pattern_bigram.sub(r"\1", text)
    return re.sub(r"\s+", " ", text).strip(" ,;:")


_ZH_ASCII_WORD_CHARS = re.compile(r"[A-Za-z0-9/+\-.]")
_ZH_PUNCT_TOKENS = set(",，.。:：;；!！?？、")


def wrap_zh(text, max_width=26):
    """Wrap mixed CJK + ASCII text into at most 2 lines.

    Tokenizing rules:
      * An ASCII word run (letters/digits/in-word `/+-.`) becomes ONE token,
        so "CheckCheck" stays atomic even when adjacent to a comma. Previously
        text like "OK,CheckCheck" fell through to char-by-char tokenisation
        (since the comma broke the fullmatch) and produced "CheckC / heck".
      * Punctuation is its own token so we can wrap around it cleanly.
      * Each CJK char is its own token.
    """
    tokens = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if _ZH_ASCII_WORD_CHARS.match(ch):
            j = i
            while j < n and _ZH_ASCII_WORD_CHARS.match(text[j]):
                j += 1
            tokens.append(text[i:j])
            i = j
            continue
        if ch in _ZH_PUNCT_TOKENS:
            tokens.append(ch)
            i += 1
            continue
        # CJK char or anything else: emit as singleton.
        tokens.append(ch)
        i += 1

    def is_ascii_word(tok):
        return bool(tok) and _ZH_ASCII_WORD_CHARS.match(tok[0]) is not None

    def is_punct(tok):
        return tok in _ZH_PUNCT_TOKENS

    def token_width(tok):
        # Each CJK char or fullwidth punct counts as 2; ASCII counts as 1 per
        # char + 2 leading space when needed -- we'll model the leading space
        # at append time, here just the body width.
        if is_ascii_word(tok):
            return len(tok)
        return 2

    def append_token(line, token):
        if is_ascii_word(token):
            return (line + " " + token).strip() if line else token
        if is_punct(token):
            # Glue punctuation to the previous token (no leading space).
            return line + token
        # CJK: add a space if the previous char was ASCII so we never end up
        # with "AI幫忙" or "Reels影片".
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
    lines = lines[:2]

    # Widow avoidance: if the wrap puts only 1-3 characters on line 2 (e.g.
    # the trailing "的" / "了" / "你" that the user keeps catching), pull the
    # last 2-character chunk from line 1 down so the two lines look balanced
    # instead of having a lonely tail.
    if len(lines) == 2 and len(re.sub(r"\s", "", lines[1])) <= 3:
        head_tokens = list(lines[0])
        tail = lines[1]
        # Walk back: grab whole ASCII words or CJK pairs until tail has >= 4
        # characters (or we'd empty line 1).
        while len(re.sub(r"\s", "", tail)) <= 3 and len(head_tokens) > 4:
            ch = head_tokens.pop()
            tail = (ch + tail).strip()
        lines = ["".join(head_tokens).strip(), tail]
    return r"\N".join(lines)


def wrap_en(text, width=26, max_lines=1):
    """Wrap English text by word boundary.

    `max_lines=1` is the production setting (forces single-line EN under
    bilingual ZH so the two never collide vertically; long EN gets truncated
    at the last whole word that fits). `max_lines=2` is used for English-only
    mode where EN can take the full subtitle zone.
    """
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
    return r"\N".join(lines[:max(1, max_lines)])


def plain_wrap_zh(text, max_chars=9):
    compact = re.sub(r"\s+", " ", clean_zh(text)).strip(" ，,。.!！?")
    if not compact:
        return []
    lines = wrap_zh(compact, max_width=max_chars * 2).split(r"\N")
    return [line.strip() for line in lines[:2] if line.strip()]


def segment_hook_score(segment, index=0):
    """Score a ZH segment as a potential POV / scroll-stop hook.

    Rules derived from creator research (OpusClip 2026 formulas + Chinese
    short-video community 5-type framework). Each pattern detected adds to
    the score; position weighting prefers the first 30 seconds because the
    hook needs to land in the audience's 1.5-second attention window.

    Detected patterns:
      * Numbered-list hook        e.g. "3 個秘密", "5 招", "10 倍"
      * Question hook             e.g. "你知道...", "為什麼...?", "有沒有..."
      * Contrarian / negation     e.g. "其實不是", "別再", "千萬不要", "你以為..."
      * Mistake confession        e.g. "我浪費了", "後悔", "早知道", "我犯了"
      * Secret / exclusivity      e.g. "99% 的人", "沒人說", "大部分人不知道", "一個秘密"
      * Time-promise              e.g. "3 分鐘", "7 天內", "1 小時"
      * Authority                 e.g. "我做了 X 年", "我花了 X"
      * Strong emotion / pattern-break  "絕對", "真的", "居然", "完全", "震驚"
      * Urgency                   "趁早", "趁現在", "再不", "已經太晚"

    The score is a continuous number — higher = better hook material.
    """
    text = clean_zh(segment.get("text", ""))
    if not text:
        return 0.0
    start = float(segment.get("start", 0))
    score = 0.0

    # --- Sentence completeness ---
    # A hook must feel like a complete thought. If the segment ends with a
    # dangling modal ("能不能", "可不可以", "要不要") or a continuation cue
    # ("然後", "所以", "因為"), the speaker hadn't finished -- skip it as a
    # hook candidate even if it has keywords. This kills selections like
    # "剪接軟體的第二部影片能不能夠" (which trails off mid-thought).
    if _segment_looks_complete(text):
        score += 5
    else:
        score -= 8

    # --- Filler / test-content veto ---
    # Reject openings that are obviously soundcheck or warm-up filler so the
    # hook scorer never picks "好啦好啦,來快速測試一下" as the POV title.
    # These patterns dominate the segment if matched at the start OR if the
    # segment is mostly filler (e.g. "test test", "ok ok").
    filler_patterns = [
        r"^(好啦|好的|好|嗯|呃|啊|噢|喔|那個|然後|就是)\s*[,，]?\s*",
        r"^(let'?s\s+)?(quickly\s+)?test(ing)?\b",
        r"^(ok|okay|alright)[,，\s]",
        r"\b(check\s+check|test\s+test|ok\s+ok)\b",
        r"^(我想|我來|我們來)?\s*(測試|試試|看看)\s*(一下)?$",
    ]
    if any(re.search(p, text, flags=re.IGNORECASE) for p in filler_patterns):
        score -= 20  # Hard veto so even early position can't rescue it.

    # --- Position decay: peak in first 6s, falls off after 30s ---
    if start <= 30:
        score += max(0.0, (30 - start) * 0.3) + (4 if start <= 6 else 0)
    # --- Length: ideal 8-22 chars for cover band ---
    n_chars = len(text)
    if 8 <= n_chars <= 22:
        score += 4
    elif n_chars < 8:
        score -= (8 - n_chars) * 0.6
    elif n_chars > 22:
        score -= (n_chars - 22) * 0.3

    # --- Pattern-based scoring (research-backed) ---
    # 1. Numbered list — Arabic OR Chinese numerals 一二三四五六七八九十
    if re.search(r"\b\d{1,2}\s*(?:個|招|件|步|秒|分|天|年|歲|倍|%|％)\b", text):
        score += 8
    elif re.search(r"[一二三四五六七八九十]\s*(?:個|招|件|步|大|秒|分|天|年|倍)", text):
        score += 7

    # 2. Question hook
    if re.search(r"[？?！!]$", text):
        score += 6
    if re.search(r"(?:你知道|為什麼|怎麼|有沒有|可不可以|是不是|哪一|哪個|什麼是|要怎麼)", text):
        score += 6

    # 3. Contrarian / negation pattern interrupt
    if re.search(r"(?:其實不|其實沒|別再|千萬不要|不要再|你以為|你可能不知道|錯了|誤會了)", text):
        score += 7
    # Early negation in first 5 chars
    if re.search(r"^(?:不|沒|別|千萬|錯)", text):
        score += 3

    # 4. Mistake / vulnerability confession
    if re.search(r"(?:我浪費|我花了|我後悔|早知道|犯了|失敗|教訓|繞了|走了彎路)", text):
        score += 6

    # 5. Secret / exclusivity
    if re.search(r"(?:99%|九成|大部分人|大多數人|沒人[會說告訴跟]|沒人講|很少人|一個秘密|不為人知|內行|關鍵在)", text):
        score += 8

    # 6. Time-promise
    if re.search(r"(?:\d+|[一二三四五六七八九十])\s*(?:秒|分鐘|小時|天|週|個月|年)(?:內|就|可以|搞定|學會|做完)", text):
        score += 5

    # 7. Authority — long-form experience claim
    if re.search(r"(?:我做了|我花了|我玩了|我研究了|我用了)\s*\d+\s*(?:年|個月|天)", text):
        score += 6

    # 8. Strong emotion / pattern break
    if re.search(r"(?:絕對|真的超|完全|居然|竟然|震驚|誇張|爆炸|簡直|根本就)", text):
        score += 3

    # 9. Urgency
    if re.search(r"(?:趁早|趁現在|再不|已經太晚|錯過就|現在不|錯過)", text):
        score += 4

    # 10. Topic anchor — keeps the hook on-message for THIS clip
    topic_keywords = ["AI", "自動", "廣告", "小編", "Reels", "剪輯", "成本", "免費"]
    score += sum(2 for kw in topic_keywords if kw in text)

    return score


def best_hook_segment(zh_segments):
    """Return the highest-scoring segment from the first 24 segments, or
    None if no segments exist. Convenience wrapper around
    `ranked_hook_candidates` for callers that only need the top pick.
    """
    ranked = ranked_hook_candidates(zh_segments)
    return ranked[0] if ranked else None


def ranked_hook_candidates(zh_segments, top_k=6):
    """Return the top `top_k` hook candidates sorted by descending score.

    derive_pov_title walks this list until it finds a candidate that ALSO
    splits cleanly into 2 distinct concepts -- so we don't fall back to a
    "POV: + sentence" framing just because the single highest-scoring
    segment was monolithic.

    Also logs the top picks so the user can audit hook selection.
    """
    if not zh_segments:
        return []
    candidates = [(segment_hook_score(seg, index), index, seg) for index, seg in enumerate(zh_segments[:24])]
    candidates.sort(key=lambda x: x[0], reverse=True)
    log("  hook candidates (top 3):")
    for score, index, seg in candidates[:3]:
        snippet = clean_zh(seg.get("text", ""))[:30]
        log(f"    [{seg.get('start', 0):.1f}s, #{index}, score={score:.1f}] {snippet!r}")
    return [seg for _, _, seg in candidates[:top_k]]


def _segment_looks_complete(text):
    """Return True iff the segment ends like a complete thought.

    A hook title MUST be a complete sentence. This is a hard filter in
    `derive_pov_title` -- segments that fail are skipped entirely, never
    just penalised. The rules below catch the specific incompletes that
    keep slipping through (the canonical pathology was
    "剪接軟體的第二部影片能不能夠" where 能不能夠 trailed off).

    Universal incompleteness signals (applies to every clip, every user):

    1. Reduplicated yes-no modal at end, with or without an optional
       supporting verb after it:
         能不能, 能不能夠, 能不能做, 會不會, 會不會去, 要不要,
         可不可以, 可不可以做, 想不想, 是不是, 有沒有, 好不好, 對不對
    2. Trailing modal alone (能/會/要/想/可以/應該/必須)
    3. Trailing connective particle (然後/所以/因為/可是/不過/而且/
       並且/還有/還是/或者/另外/其實/只是/但是)
    4. Trailing topic shifter without comment (那個/這個/那麼/這麼/
       什麼/怎麼/為什麼) -- the speaker hasn't gotten to the point yet
    5. Trailing subject pronoun without verb (我/你/他/她/我們/...)
    6. Trailing 的/了 with very short content (likely cut mid-clause)
    """
    if not text:
        return False
    tail = text.rstrip(" ，,.;: 　")
    if not tail or len(tail) < 4:
        return False
    last = tail[-1]

    # Definitively complete: sentence-final punctuation.
    if last in "。！？.!?":
        return True

    # 1. Reduplicated yes-no modal patterns -- the speaker was asking but
    # didn't finish the question.
    if re.search(r"(?:能不能|會不會|要不要|想不想|是不是|有沒有|可不可以|好不好|對不對)(?:夠|做|去|來|的|過|了|呢|啊)?$", tail):
        return False

    # 2. Lone modal verb at end (no object, no closure).
    if re.search(r"(?:能|會|要|想|可以|應該|必須|可能|可不可以)$", tail):
        return False

    # 3. Connective at end -- "to be continued" cue.
    if re.search(r"(?:然後|所以|因為|可是|不過|但是|而且|並且|還有|還是|或者|或是|另外|其實|只是|那麼)$", tail):
        return False

    # 4. Topic shifter without a comment.
    if re.search(r"(?:那個|這個|什麼|怎麼|為什麼|哪個|哪裡|哪一)$", tail):
        return False

    # 5. Subject pronoun trailing.
    if re.search(r"(?:我|你|他|她|我們|你們|他們|大家|有人)$", tail):
        return False

    # 6. Lone 的/了 with too little context.
    if last in "的了" and len(tail) < 8:
        return False

    # Closing particle -> complete.
    if last in "嗎吧呢啦哦呦":
        return True
    if last == "了" and len(tail) >= 8:
        return True

    # Default: if it survives all the bad patterns and is long enough,
    # treat as complete. Burnt-in title only renders 8-18 chars anyway.
    return len(tail) >= 6


def _split_hook_into_two_concepts(text):
    """Find a natural 2-concept split inside `text`.

    Returns (line_a, line_b) when a clean split exists where BOTH halves
    read as standalone concepts (4-14 chars each). Returns (text, "") when
    no good split is found; callers then render a single-line title in a
    single color rather than fake a 2-concept break.

    Strategies, in priority order:
      1. Explicit internal punctuation (，。、：)
      2. Question/contrast pivot ("真的", "其實", "竟然", "可不可以", etc.)
      3. Topic-comment boundary (after the subject pronoun + 1-2 chars of
         noun phrase, the verb phrase starts -- split there)
      4. Particle anchor (split before sentence-final 嗎/呢/吧 with the
         particle group on line 2)
    """
    text = text.strip(" ，。、,.;:")
    n = len(text)
    if n < 8:
        return text, ""

    # 1. Explicit punctuation - the cleanest signal of two clauses.
    for idx, ch in enumerate(text):
        if ch in "，。、：,.;:" and 4 <= idx <= n - 5:
            left = text[:idx].strip(" ，。、,.;:")
            right = text[idx + 1:].strip(" ，。、,.;:")
            if 4 <= len(left) <= 14 and 4 <= len(right) <= 14:
                return left, right

    # 2. Pivot words - the hook turns on these. Line 2 keeps the pivot
    # because it's what makes the punch land.
    for pivot in ("真的", "其實", "竟然", "居然", "為什麼", "怎麼", "可不可以",
                  "能不能", "會不會", "是不是", "完全", "絕對", "原來"):
        idx = text.find(pivot)
        if 4 <= idx <= n - 4:
            left = text[:idx].strip(" ，。、,.;:")
            right = text[idx:].strip(" ，。、,.;:")
            if 4 <= len(left) <= 14 and 4 <= len(right) <= 14:
                return left, right

    # 3. Topic-comment: short subject noun phrase then verb phrase.
    sub_match = re.match(r"^(我|你|他|她|我們|你們|他們|大家|有人)([^ ，,。.]{1,5})", text)
    if sub_match:
        boundary = len(sub_match.group(0))
        left = text[:boundary].strip()
        right = text[boundary:].strip()
        if 4 <= len(left) <= 12 and 4 <= len(right) <= 14:
            return left, right

    # 4. Balanced break at structural particle (的/了/過/就) closest to mid.
    target = n // 2
    best_pos = None
    best_dist = float("inf")
    for pos, ch in enumerate(text):
        if ch in "的了過就" and 4 <= pos + 1 <= n - 4:
            dist = abs(pos + 1 - target)
            if dist < best_dist:
                best_dist = dist
                best_pos = pos + 1
    if best_pos is not None:
        left = text[:best_pos].strip()
        right = text[best_pos:].strip()
        if 4 <= len(left) <= 14 and 4 <= len(right) <= 14:
            return left, right

    return text, ""


def _split_hook_into_lead_and_punch(text):
    """Split a hook sentence into (lead, punch) where:
      * lead = a short framing label (3-6 chars) that goes on line 1
      * punch = the actual scroll-stop content that goes on line 2
    Each line is a distinct concept rendered in a distinct color so the
    title reads as a "headline 1 / headline 2" pair, not a sentence broken
    arbitrarily mid-clause.

    Detection rules:
      1. If the hook contains 「：」/「:」, use what's before as lead
      2. If the hook starts with a question marker (為什麼/怎麼/有沒有),
         that becomes the lead, the rest is the punch
      3. If the hook starts with a numbered claim ("3 個秘密"), the number
         phrase is the lead, the rest is the punch
      4. If the hook starts with first-person observation (我/你發現/...),
         "POV：" becomes the lead, the hook becomes the punch
      5. Default: "POV：" + the whole hook as punch
    """
    text = text.strip()
    # Rule 1: explicit colon
    for sep in ("：", ":"):
        if sep in text:
            lead, _, punch = text.partition(sep)
            lead = lead.strip()
            punch = punch.strip()
            if 1 <= len(lead) <= 8 and punch:
                return (lead + sep), punch

    # Rule 2: question-form opening
    q_match = re.match(r"^(為什麼|怎麼|有沒有|是不是|你知道|你以為|哪一[個種件])", text)
    if q_match:
        lead = q_match.group(0)
        punch = text[len(lead):].lstrip(" ，,：:")
        if punch:
            return f"{lead}？", punch

    # Rule 3: number opening
    n_match = re.match(r"^(\d{1,2}\s*(?:個|招|件|步|大|秒|分|天|年|倍|%|％)|[一二三四五六七八九十]\s*(?:個|招|件|步|大))", text)
    if n_match:
        lead = n_match.group(0).strip()
        punch = text[len(n_match.group(0)):].lstrip(" ，,：:、")
        if punch:
            return lead, punch

    # Rule 4: first-person POV
    if re.match(r"^[我你他她我們你們]", text):
        return "POV：", text

    # Default: POV framing
    return "POV：", text


def _english_lead_for(zh_lead):
    """Pick an English equivalent lead label that pairs with the ZH lead."""
    if zh_lead in ("POV：", "POV:"):
        return "POV:"
    if "？" in zh_lead or "?" in zh_lead:
        return "Why:"
    if re.match(r"^\d", zh_lead):
        return zh_lead  # numbers translate as-is
    return "POV:"


def derive_pov_title(zh_segments, en_segments, fallback_zh, fallback_en):
    """Pick the best hook from the transcript and shape it into a 2-line
    burnt-in title. Returns (zh_title, en_title) where each title is a
    string formatted as "{line_1}|{line_2}" so the renderer can paint
    line 1 and line 2 in DIFFERENT colors (white intro + accent punch)
    -- they're two separate concepts, not one sentence split by chance.

    Shaping rules:
      * Line 1 = a short framing label ("POV：", "為什麼？", "重點是")
        in the cover's main_color
      * Line 2 = the actual scroll-stop content in accent_color
      * If no clear hook scores high enough, falls back to the static title.
    """
    if not zh_segments:
        return fallback_zh, fallback_en
    # Universal title rules (REGRESSION_CHECKLIST.md):
    #   - Title must be 2 lines in 2 different colors
    #   - Both lines must be complete content (no label-only line)
    #   - Picker MUST try the next candidate when the top one is monolithic
    candidates = ranked_hook_candidates(zh_segments, top_k=8)
    chosen_hook = None
    chosen_split = (None, None)
    for candidate in candidates:
        text = clean_zh(candidate.get("text", "")).strip(" ，。、,.;:")
        # HARD GATE 1: must be a complete sentence. No "能不能夠..." trailing.
        if not _segment_looks_complete(text):
            continue
        # HARD GATE 2: must score above the filler floor.
        score = segment_hook_score(candidate, 0)
        if score < 6:
            continue
        # HARD GATE 3: must split cleanly into TWO independent concepts.
        a, b = _split_hook_into_two_concepts(text)
        if not b:
            continue
        chosen_hook = candidate
        chosen_split = (a, b)
        break

    if chosen_hook is None or not chosen_split[1]:
        # No candidate produced a 2-concept hook. Don't fake one with a
        # POV: label; fall through to the static memory title which the
        # designer already shaped as 2 lines via the "：" split rule.
        return fallback_zh, fallback_en

    line_a, line_b = chosen_split
    zh = f"{line_a}|{line_b}"

    # English side mirrors the 2-line shape so the same color rule applies.
    en_full = nearest_english_segment(en_segments, (chosen_hook["start"] + chosen_hook["end"]) / 2).strip(" ,;:")
    if not en_full:
        en = fallback_en
    else:
        # Pair the EN by sentence-mid comma if present; otherwise balance
        # the EN words across two lines.
        comma_idx = en_full.find(",")
        if 4 <= comma_idx <= len(en_full) - 4:
            en = f"{en_full[:comma_idx].strip()}|{en_full[comma_idx + 1:].strip()}"
        else:
            words = en_full.split()
            mid = max(1, len(words) // 2)
            en = f"{' '.join(words[:mid])}|{' '.join(words[mid:])}"
        # Cap each EN line to ~20 chars so it fits the band
        en_parts = [p[:20] for p in en.split("|")]
        en = "|".join(en_parts)

    return zh, en


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

    # Write a verification transcript: source timestamps + ZH + EN side by
    # side. The GUI uses this to render a scrollable, click-to-seek table
    # under the output video so users can audit cuts and translations on
    # their own uploads without needing a video editor.
    transcript_combined = []
    for zh_index, zh in enumerate(zh_segments):
        for item in intersections(zh, timeline):
            transcript_combined.append({
                "start": round(item["start"], 2),
                "end": round(item["end"], 2),
                "zh": clean_zh(item["text"]),
                "en": clean_en(en_assignments[zh_index]) if zh_index < len(en_assignments) else "",
            })
    transcript_combined.sort(key=lambda r: r["start"])
    combined_path = ass_path.parent / "transcript_combined.json"
    combined_path.write_text(json.dumps(
        {"segments": transcript_combined}, ensure_ascii=False, indent=2,
    ))
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
                # English-only mode: EN is the hero, allow up to 2 lines.
                en_text_wrapped = ass_escape(wrap_en(en_clean_raw, width=22, max_lines=2))
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
                # Bilingual mode: ZH owns the upper band (1-2 lines), EN sits
                # below in its own band (1-2 lines). The vertical margins are
                # chosen (in reels_memory.json + _verify_subtitle_layout) so
                # that even ZH 2-line + EN 2-line maintains a clear gap.
                # We DO NOT truncate EN -- translation completeness matters
                # more than width.
                en_clean = ass_escape(wrap_en(en_text, width=26, max_lines=2)) if (bilingual and en_text) else ""
                rows.append({"start": start, "end": end, "zh": zh_text, "en": en_clean})
                last_zh_norm, last_end = normalized, end

    # ABSOLUTE no-overlap rule: clip each row's end so the next row's lead-in
    # never collides with it. No 0.35s floor -- if rows are so tightly packed
    # that clipping would make them invisible, we just drop them. The user's
    # requirement that subtitles NEVER overlap takes priority over keeping
    # short rows on screen.
    rows.sort(key=lambda r: r["start"])
    min_gap = float(sub.get("min_gap_seconds", 0.04))
    for index in range(len(rows) - 1):
        next_start = rows[index + 1]["start"]
        latest_end = next_start - min_gap
        if rows[index]["end"] > latest_end:
            rows[index]["end"] = latest_end
    # Drop rows that became invisible (clip ate them).
    rows = [r for r in rows if r["end"] - r["start"] > 0.05]

    lines = [header]
    all_events = []
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
            all_events.append((style_name, start, end, margin_v))
            lines.append(
                f"Dialogue: {layer},{ass_ts(start)},{ass_ts(end)},{style_name},,0,0,{margin_v},,{text}\n"
            )
    ass_path.write_text("".join(lines))

    # Production-grade layout assertion. ALWAYS run -- any collision raises
    # so the job fails loudly with a clear log instead of shipping a bad
    # video to the user. See _verify_subtitle_layout() for the rules.
    _verify_subtitle_layout(all_events, zh_size, en_size, en_only=en_only)


def _verify_subtitle_layout(events, zh_size, en_size, en_only=False):
    """Assert subtitle invariants on the produced ASS event list. Raises
    ValueError on any violation so the pipeline fails fast.

    events: list of (style_name, start_seconds, end_seconds, margin_v)

    Invariants:
      (a) No two events with the SAME style and DIFFERENT margin_v overlap
          in time UNLESS they share start/end (those are the intentional
          two-line wrap pair).
      (b) For any moment where a ZH event is active and an EN event is also
          active, their text pixel rectangles must not intersect.

    Pixel math (ASS PlayResY=1920, MarginV measured from bottom, default
    bottom-center alignment so text baseline is at PlayResY - margin_v):
      text body y_top    = PlayResY - margin_v - font_size
      text body y_bottom = PlayResY - margin_v
      We pad +/-4 px for outline+shadow on each side.
    """
    if not events:
        return
    PADDING = 5  # outline + shadow safety
    PLAY_Y = 1920

    def body(margin_v, font_size):
        y_bottom = PLAY_Y - margin_v
        y_top = y_bottom - font_size
        return (y_top - PADDING, y_bottom + PADDING)

    def rects_overlap(a, b):
        return not (a[1] <= b[0] or b[1] <= a[0])

    # (b) ZH vs EN pixel collision
    zh_events = [(s, e, body(mv, zh_size)) for st, s, e, mv in events if st == "ZH"]
    en_events = [(s, e, body(mv, en_size)) for st, s, e, mv in events if st == "EN"]
    for zh_s, zh_e, zh_rect in zh_events:
        for en_s, en_e, en_rect in en_events:
            if en_s >= zh_e or zh_s >= en_e:
                continue  # no time overlap
            if rects_overlap(zh_rect, en_rect):
                raise ValueError(
                    f"Subtitle layout violation: ZH y={zh_rect} and "
                    f"EN y={en_rect} overlap at time [{max(zh_s, en_s):.2f}, "
                    f"{min(zh_e, en_e):.2f}]. Adjust english_bottom_margin "
                    f"in reels_memory.json."
                )

    if en_only:
        return  # ZH style not used in EN-only mode

    log(f"  layout OK: {len(zh_events)} ZH events, {len(en_events)} EN events, no pixel overlap")


def _ffmpeg_text_escape(text):
    # drawtext text= uses single-quote framing, plus colon/backslash escaping.
    return (
        text.replace("\\", "\\\\")
        .replace(":", r"\:")
        .replace("'", r"\'")
        .replace("%", r"\%")
    )


def _title_lines(title, max_per_line=12):
    """Split a ZH title into up to two visually balanced lines so it never
    overflows the band horizontally. `max_per_line` is in CJK-char widths
    (a CJK char counts 2, an ASCII char counts 1). The band at fontsize=46
    in a 1080-wide ASS canvas fits ~12 CJK chars comfortably.

    Strategy, in order of preference:
      0. Honor an explicit `|` separator inserted by derive_pov_title --
         this signals "these are TWO distinct concepts" and must be split
         exactly there so colors render line 1 vs line 2 properly.
      1. Honor a hard split point in the user's text (`：`, `:`, ` 小編`)
      2. Split at a natural CJK punctuation (`，` `,` `。`)
      3. Greedy CJK-aware word-balance split
    """
    # 0. Explicit two-concept marker from derive_pov_title.
    if "|" in title:
        parts = [normalize_cjk_ascii_spacing(p).strip() for p in title.split("|", 1)]
        parts = [p for p in parts if p]
        if len(parts) == 2:
            return parts
        if len(parts) == 1:
            return [parts[0]]

    normalized = normalize_cjk_ascii_spacing(title).strip()

    def cjk_width(s):
        return sum(2 if re.match(r"[　-〿一-鿿＀-￯]", c) else 1 for c in s)

    # 1. Honor hard split points the user (or hook generator) inserted.
    for sep, keep in [(" 小編", "after"), ("：", "before"), (":", "before")]:
        if sep in normalized:
            head, tail = normalized.split(sep, 1)
            if keep == "before":
                return [(head + sep).strip(), tail.strip()]
            return [head.strip(), (sep.strip() + tail).strip()]

    # 2. If short enough, single line.
    if cjk_width(normalized) <= max_per_line * 2:
        return [normalized]

    # 3. Try natural punctuation breaks first.
    for sep in ["，", ",", "。"]:
        if sep in normalized:
            idx = normalized.find(sep)
            head, tail = normalized[: idx + len(sep)], normalized[idx + len(sep):]
            if 4 <= cjk_width(head) <= max_per_line * 2 and tail.strip():
                return [head.strip(), tail.strip()]

    # 4. Greedy balance: find the split that puts both lines closest to
    # equal width without exceeding max_per_line.
    total = cjk_width(normalized)
    target = total // 2
    cum = 0
    best_split = None
    best_delta = float("inf")
    for i, ch in enumerate(normalized):
        cum += 2 if re.match(r"[　-〿一-鿿＀-￯]", ch) else 1
        # Prefer splitting after a non-ASCII boundary (don't split English words)
        next_ch = normalized[i + 1] if i + 1 < len(normalized) else " "
        if not re.match(r"[A-Za-z0-9]", ch) or not re.match(r"[A-Za-z0-9]", next_ch):
            delta = abs(cum - target)
            line2_width = total - cum
            if cum <= max_per_line * 2 and line2_width <= max_per_line * 2 and delta < best_delta:
                best_delta = delta
                best_split = i + 1
    if best_split is None:
        # Hard cut as last resort
        best_split = next((i for i in range(1, len(normalized)) if cjk_width(normalized[:i]) >= max_per_line * 2), len(normalized) // 2)
    return [normalized[:best_split].strip(), normalized[best_split:].strip()]


def _en_title_lines(title):
    """Split an English title into one or two visually balanced lines."""
    if not title:
        return [""]
    # Two-concept marker from derive_pov_title.
    if "|" in title:
        parts = [p.strip() for p in title.split("|", 1) if p.strip()]
        if parts:
            return parts
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
        title_source = en_title
    else:
        title_lines = _title_lines(memory["title"])
        title_source = memory["title"]
    # Universal rule: title is ALWAYS 2 lines in 2 different colors.
    # derive_pov_title guarantees a `|` split by walking ranked candidates
    # and only falling back to the static memory title when NO candidate
    # produces a clean 2-concept hook. The static title has its own
    # natural split (via "：") so 2-color always applies.
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


def _select_video_encoder(export):
    """Pick the fastest encoder available for this OS.

    Apple Silicon and Intel macOS both have h264_videotoolbox (hardware
    H.264 via the dedicated media engine + GPU). On Apple Silicon it's
    ~4x faster than libx264 medium with effectively identical perceptual
    quality at the bitrate we target. On Windows/Linux we fall back to
    libx264 with the `veryfast` preset, which is ~3x faster than `medium`
    and only loses ~5% efficiency for content this short.

    Override via reels_memory.json `export.encoder` if needed:
      "libx264", "h264_videotoolbox", "h264_nvenc", "h264_qsv"
    """
    forced = export.get("encoder")
    if forced:
        return forced
    if platform.system() == "Darwin":
        return "h264_videotoolbox"
    return "libx264"


def render_video(video, filter_path, output, memory):
    write_progress(output.parent, "render", "正在輸出壓縮後的 IG Reels 影片")
    log("5/7 Rendering compressed IG Reels MP4")
    export = memory["export"]
    encoder = _select_video_encoder(export)
    crf = str(int(export.get("crf", 22)))
    log(f"  encoder: {encoder}")

    cmd = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(video),
        "-filter_complex_script", str(filter_path),
        "-map", "[vout]",
        "-map", "[aout]",
        "-c:v", encoder,
    ]

    if encoder == "h264_videotoolbox":
        # VideoToolbox doesn't accept libx264's -crf / -preset / -profile/level
        # flags. We hand it -q:v (constant-quality VBR, 0=worst..100=best)
        # which is the VT equivalent. q=60 maps roughly to libx264 CRF 22 at
        # 720x1280 talking-head content. -allow_sw 1 lets it transparently
        # fall back to software encoding if the HW encoder is busy or refuses
        # the input (e.g. unusual color spaces). No -maxrate/-bufsize on
        # purpose; the same sub-1s first-concat-piece problem applies and CBR
        # would re-introduce the grey first frames.
        cmd += [
            "-q:v", str(export.get("videotoolbox_quality", 60)),
            "-allow_sw", "1",
            "-realtime", "0",
        ]
    else:
        # NOTE: we encode in CRF mode rather than CBR/VBV. The previous CBR
        # config (`-b:v ... -maxrate ... -bufsize ...`) starved the encoder
        # on the very short first trim+concat piece (<1s) and produced a flat
        # grey first ~30 frames. CRF gives consistent per-frame quality and
        # keeps frame 0 painted from the start.
        # `veryfast` here -- not `medium` -- because the savings are huge and
        # the quality drop is invisible at this resolution/duration.
        preset = export.get("x264_preset", "veryfast")
        cmd += [
            "-preset", preset,
            "-profile:v", "high",
            "-level", "4.1",
            "-crf", crf,
        ]

    cmd += [
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


def fit_font_to_width(draw, text, font_path, base_size, max_width=640, stroke_width=4, min_size=42):
    """Shrink font from `base_size` toward `min_size` until the rendered
    text width fits inside `max_width` pixels. Returns the chosen ImageFont.

    Used by cover renderers (especially the Color Pop / centered_hero
    layout) so a hook like "全自動化 AI 小編跟廣告" or a long English
    headline never bleeds past the 720 px canvas edge. We leave 40 px of
    horizontal safe area on each side by default (max_width=640).
    """
    if not text:
        return ImageFont.truetype(font_path, base_size)
    size = base_size
    while size > min_size:
        font = ImageFont.truetype(font_path, size)
        if text_width(draw, text, font, stroke_width) <= max_width:
            return font
        size -= 2
    return ImageFont.truetype(font_path, min_size)


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
            "accent_color": "white",          # all-white style: NO neon accent
            "borderw": 5,
            "border_alpha": 0.85,
        },
        "subtitle": {
            # "全白爆點" / All-White Hook -- the cover is pure white type, so
            # the burnt-in title and BOTH subtitle tracks stay pure white too
            # to keep the visual identity consistent across cover + video.
            "zh_primary": "&H00FFFFFF",
            "zh_outline": "&H50000000",
            "en_primary": "&H00FFFFFF",
            "en_outline": "&H50000000",
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
        base_size = spec["fonts"].get("big_en") or spec["fonts"]["big"]
        font_path = FONT_EN
    else:
        base_size = spec["fonts"]["big"]
        font_path = FONT_ZH
    ys = spec["ys"]
    colors = spec["colors"]
    stroke = spec["stroke"]

    # Auto-fit BOTH lines to the same shrunk size so they look like a unit.
    # 640 px keeps a 40 px safe margin on each side of the 720 px canvas so
    # bold strokes never bleed off the edge.
    fitted_size = base_size
    for candidate in (main_1, main_2):
        if not candidate:
            continue
        font = fit_font_to_width(draw, candidate, font_path, fitted_size, max_width=640, stroke_width=stroke["main"], min_size=46)
        fitted_size = min(fitted_size, font.size)
    big_font = ImageFont.truetype(font_path, fitted_size)

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
    # ZH -> EN translation: we tested Marian opus-mt-zh-en (fast but produces
    # gibberish on conversational talking-head Chinese -- "如果是中文版本的話"
    # came out as "Arabic, but if Chinese...") and NLLB-200-600M (better but
    # still drops key words). Whisper-medium with task='translate' is the
    # only thing that produces actually-readable English at acceptable cost
    # (~98s for 3-min audio on Apple Silicon, since Whisper was pre-trained
    # on subtitled video data exactly like this).
    #
    # On Intel/Windows (no MLX) the bundled Marian model is the fallback.
    if memory["subtitle"]["bilingual"]:
        en_segments = produce_en_segments(memory, wav, zh_segments, en_json, job_dir)
    else:
        en_segments = []
    write_progress(job_dir, "render", "正在 digest 內容，挑選 hook 與封面文案")
    # Pick a content-aware POV title from the actual transcript using the
    # research-backed hook scorer (see segment_hook_score). The default
    # static title in reels_memory.json is the fallback if nothing scores
    # high enough -- we don't want to invent a hook that isn't really there.
    dynamic_zh, dynamic_en = derive_pov_title(
        zh_segments, en_segments,
        memory.get("title", "POV"),
        memory.get("title_en", "POV"),
    )
    if dynamic_zh != memory.get("title"):
        log(f"  hook title: {memory.get('title', '')!r} -> {dynamic_zh!r}")
    memory["title"] = dynamic_zh
    memory["title_en"] = dynamic_en
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


def re_render_with_edited_captions(job_dir, edits):
    """Re-render an existing finished job using user-edited caption text.

    `edits` is a list of {"start", "end", "zh", "en"} dicts. The keys
    `start` (float seconds) match against transcript_combined.json segment
    starts; matched segments have their ZH and EN text replaced before
    `build_ass` + `build_filter` + `render_video` re-run. Segments with
    empty ZH text after editing are dropped from the output (treat as
    "this isn't real speech").

    The original silence detection, hook/cover decisions, and timeline
    stay frozen so this round-trip ONLY changes the captions and the
    burnt-in video. Time cost ~30s (the videotoolbox re-encode).

    Returns the freshly-written result.json dict.
    """
    job_dir = Path(job_dir)
    result_path = job_dir / "result.json"
    if not result_path.exists():
        raise ValueError("result.json missing -- job not finished yet")

    result = json.loads(result_path.read_text())
    memory = result.get("memory") or load_memory(None)

    zh_json = job_dir / "transcript_zh.json"
    en_json = job_dir / "transcript_en.json"
    silence_log = job_dir / "silence.log"
    ass_path = job_dir / "subtitles.ass"
    filter_path = job_dir / "filter.txt"
    input_video = next(job_dir.glob("input.*"), None)
    output = job_dir / "reels_ig_compressed.mp4"

    if input_video is None or not zh_json.exists() or not silence_log.exists():
        raise ValueError("required pipeline inputs missing -- cannot re-render")

    zh_segments = json.loads(zh_json.read_text()).get("segments", [])

    # Apply user edits keyed by segment start (rounded to 0.01s so the JS
    # side can echo the same value back without float-comparison drama).
    edit_map = {}
    for edit in edits or []:
        if not isinstance(edit, dict):
            continue
        try:
            key = round(float(edit.get("start", -1)), 2)
        except (TypeError, ValueError):
            continue
        edit_map[key] = edit

    edited_zh = []
    edited_en_per_zh = []
    for seg in zh_segments:
        key = round(float(seg.get("start", 0)), 2)
        edit = edit_map.get(key)
        if edit is not None:
            zh_text = (edit.get("zh") or "").strip()
            en_text = (edit.get("en") or "").strip()
            if not zh_text:
                # User cleared the line -- drop it.
                continue
            seg = {**seg, "text": zh_text}
            edited_en_per_zh.append({
                "start": seg["start"], "end": seg["end"], "text": en_text,
            })
        else:
            edited_en_per_zh.append(None)
        edited_zh.append(seg)

    # Build en_segments: prefer user-edited rows; fall back to original where
    # the user didn't touch it.
    original_en = json.loads(en_json.read_text()).get("segments", []) if en_json.exists() else []
    en_segments = []
    en_cursor = 0
    for index, override in enumerate(edited_en_per_zh):
        if override is not None:
            if override["text"]:
                en_segments.append(override)
            # else: user cleared the EN field, leave it empty
            continue
        # Find the original EN that overlaps this ZH segment by midpoint.
        zh = edited_zh[index]
        mid = (zh["start"] + zh["end"]) / 2
        nearest = min(original_en, key=lambda s: abs(((s["start"] + s["end"]) / 2) - mid)) if original_en else None
        if nearest and abs(((nearest["start"] + nearest["end"]) / 2) - mid) < 4:
            en_segments.append(nearest)

    # Recompute the timeline + render chain. Hook / cover stay frozen.
    duration = ffprobe_duration(input_video)
    pieces = build_pieces(duration, parse_silences(silence_log), memory)
    timeline = make_timeline(pieces)
    runtime_style = memory.get("runtime_options", {}).get("cover_style", memory["cover"].get("default_style", "editorial"))
    runtime_lang = memory.get("runtime_options", {}).get("language", "zh")

    log(f"Re-rendering job {job_dir.name} with {len(edited_zh)} edited segments")
    build_ass(edited_zh, en_segments, timeline, ass_path, memory, cover_style=runtime_style, language=runtime_lang)
    build_filter(input_video, pieces, ass_path, filter_path, memory)
    render_video(input_video, filter_path, output, memory)

    # Refresh transcript_combined.json so the GUI's verification panel
    # picks up the new text on reload.
    combined = []
    en_by_start = {round(float(s["start"]), 2): s for s in en_segments}
    for seg in edited_zh:
        key = round(float(seg["start"]), 2)
        en = en_by_start.get(key, {})
        combined.append({
            "start": round(float(seg["start"]), 2),
            "end": round(float(seg["end"]), 2),
            "zh": clean_zh(seg.get("text", "")),
            "en": clean_en(en.get("text", "")) if en else "",
        })
    (job_dir / "transcript_combined.json").write_text(
        json.dumps({"segments": combined}, ensure_ascii=False, indent=2)
    )

    return result


def main():
    if len(sys.argv) not in {3, 4}:
        print("Usage: python3 reels_gui_pipeline.py INPUT_VIDEO OUTPUT_DIR [OPTIONS_JSON]", file=sys.stderr)
        raise SystemExit(2)
    options_path = Path(sys.argv[3]) if len(sys.argv) == 4 else None
    result = process_video(Path(sys.argv[1]), Path(sys.argv[2]), options_path)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
