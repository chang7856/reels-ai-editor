import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.utils import secure_filename


ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / "uploads"
OUTPUTS = ROOT / "outputs"
MEMORY = ROOT / "reels_memory.json"
PIPELINE = ROOT / "reels_gui_pipeline.py"

UPLOADS.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)


def _preflight_check():
    """Catch the two most common "why won't it start" problems and explain
    them in plain language before Flask even boots."""
    missing = [tool for tool in ("ffmpeg", "ffprobe") if shutil.which(tool) is None]
    if missing:
        installer = {
            "Darwin": "brew install ffmpeg",
            "Linux": "sudo apt install ffmpeg   # or your distro's equivalent",
            "Windows": "winget install ffmpeg   # or download from https://ffmpeg.org",
        }.get(platform.system(), "https://ffmpeg.org/download.html")
        sys.stderr.write(
            "\n"
            "╭───────────────────────────────────────────────────────────────╮\n"
            "│  Reels AI Editor — preflight check failed                      │\n"
            "╰───────────────────────────────────────────────────────────────╯\n"
            f"  Missing: {', '.join(missing)}\n\n"
            "  This app uses ffmpeg to read the video and rebuild it after\n"
            "  the auto-edit. Install it with:\n\n"
            f"      {installer}\n\n"
            "  Then re-open this window (or double-click start.command).\n\n"
        )
        sys.exit(1)

    try:
        import faster_whisper  # noqa: F401
        from PIL import Image  # noqa: F401
        from opencc import OpenCC  # noqa: F401
    except ImportError as exc:
        sys.stderr.write(
            "\n"
            "╭───────────────────────────────────────────────────────────────╮\n"
            "│  Reels AI Editor — Python dependencies missing                 │\n"
            "╰───────────────────────────────────────────────────────────────╯\n"
            f"  {exc}\n\n"
            "  Install everything with:\n\n"
            "      pip3 install -r requirements.txt\n\n"
        )
        sys.exit(1)


_preflight_check()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1_200 * 1024 * 1024
jobs = {}

MAX_DURATION_SECONDS = 600
# Uploads + outputs + logs are wiped 15 minutes after the upload lands. The
# user can grab the Reel + cover in seconds once it's rendered, so a tight
# window protects their footage and keeps disk usage near-zero.
MAX_RETENTION_SECONDS = 15 * 60
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v"}
ALLOWED_COVER_STYLES = {"editorial", "hook_caption", "magazine_pop", "creator", "high_contrast"}
ALLOWED_LANGUAGES = {"zh", "en"}
STAGE_MODEL = {
    "upload": {"start": 0, "end": 18, "label": "上傳影片"},
    "validate": {"start": 18, "end": 34, "label": "檢查格式與長度"},
    "transcribe": {"start": 34, "end": 66, "label": "轉錄與翻譯"},
    "render": {"start": 66, "end": 98, "label": "剪輯與輸出"},
    "done": {"start": 100, "end": 100, "label": "完成"},
}


def allowed(filename):
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


@app.errorhandler(RequestEntityTooLarge)
def file_too_large(_error):
    return jsonify({
        "error": "檔案太大，請上傳 1.2GB 以下、10 分鐘內的影片。",
        "code": "file_too_large",
    }), 413


def cleanup_old_files():
    cutoff = time.time() - MAX_RETENTION_SECONDS
    for folder in (UPLOADS, OUTPUTS):
        for path in folder.iterdir():
            if path.name == ".gitkeep":
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    if path.is_dir():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
            except FileNotFoundError:
                pass


def video_duration(path):
    result = subprocess.run([
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nw=1:nk=1",
        str(path),
    ], check=True, text=True, capture_output=True)
    return float(result.stdout.strip())


def stage_estimates(duration):
    duration = duration or 60
    return {
        "upload": 1,
        "validate": max(10, duration * 0.18),
        "transcribe": max(90, duration * 4.0),
        "render": max(55, duration * 1.55),
    }


def progress_from_stage(stage, started_at, duration):
    stage = stage if stage in STAGE_MODEL else "validate"
    if stage == "done":
        return 100, 0, 100
    elapsed = max(1, time.time() - started_at)
    estimates = stage_estimates(duration)
    expected = estimates.get(stage, 60)
    stage_percent = min(96, max(4, int((elapsed / expected) * 100)))
    model = STAGE_MODEL[stage]
    percent = model["start"] + (model["end"] - model["start"]) * (stage_percent / 100)
    eta = max(0, int(expected - elapsed))
    return int(percent), eta, stage_percent


def stage_breakdown(active_stage, stage_percent):
    order = ["upload", "validate", "transcribe", "render"]
    active_index = order.index(active_stage) if active_stage in order else len(order)
    rows = {}
    for index, stage in enumerate(order):
        if index < active_index:
            percent = 100
            state = "done"
        elif index == active_index:
            percent = stage_percent
            state = "active"
        else:
            percent = 0
            state = "waiting"
        rows[stage] = {
            "percent": int(max(0, min(100, percent))),
            "state": state,
            "label": STAGE_MODEL[stage]["label"],
        }
    return rows


def parse_progress_state(job_dir):
    progress_path = job_dir / "progress.json"
    if not progress_path.exists():
        return {}
    try:
        return json.loads(progress_path.read_text())
    except json.JSONDecodeError:
        return {}


def processing_progress(log, status, result, started_at, duration, progress_state=None):
    if status == "done" and result:
        return {
            "percent": 100,
            "stage": "done",
            "detail": "影片與封面都完成了",
            "stage_percent": 100,
            "stage_progress": stage_breakdown("done", 100),
            "eta_seconds": 0,
            "elapsed_seconds": max(0, int(time.time() - started_at)),
        }

    progress_state = progress_state or {}
    stage = progress_state.get("stage") or "validate"
    stage_started_at = progress_state.get("stage_started_at") or started_at
    if not progress_state.get("stage"):
        if "7/7" in log:
            stage = "render"
        elif "5/7" in log or "6/7" in log:
            stage = "render"
        elif "3/7" in log:
            stage = "transcribe"
        elif "1/7" in log or "2/7" in log:
            stage = "validate"

    elapsed = max(1, int(time.time() - started_at))
    percent, stage_eta, stage_percent = progress_from_stage(stage, stage_started_at, duration)
    estimates = stage_estimates(duration)
    order = ["upload", "validate", "transcribe", "render"]
    remaining = stage_eta
    if stage in order:
        active_index = order.index(stage)
        for later_stage in order[active_index + 1:]:
            remaining += int(estimates[later_stage])
    return {
        "percent": min(percent, 96),
        "stage": stage,
        "detail": progress_state.get("detail") or STAGE_MODEL.get(stage, STAGE_MODEL["validate"])["label"],
        "stage_percent": stage_percent,
        "stage_progress": stage_breakdown(stage, stage_percent),
        "eta_seconds": remaining,
        "stage_eta_seconds": stage_eta,
        "elapsed_seconds": elapsed,
    }


@app.get("/")
def index():
    cleanup_old_files()
    return render_template("index.html", memory=json.loads(MEMORY.read_text()))


@app.post("/jobs")
def create_job():
    cleanup_old_files()
    file = request.files.get("video")
    cover_style = request.form.get("cover_style", "editorial")
    language = (request.form.get("language") or "zh").lower()
    if not file or file.filename == "":
        return jsonify({"error": "請選擇影片檔"}), 400
    if not allowed(file.filename):
        return jsonify({"error": "目前只支援 mp4 / mov / m4v"}), 400
    if cover_style not in ALLOWED_COVER_STYLES:
        return jsonify({"error": "不支援的封面風格"}), 400
    if language not in ALLOWED_LANGUAGES:
        return jsonify({"error": "不支援的語言"}), 400

    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    job_dir = OUTPUTS / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    original_name = secure_filename(file.filename)
    source = UPLOADS / f"{job_id}{Path(original_name).suffix.lower()}"
    file.save(source)
    os.chmod(source, 0o600)

    try:
        duration = video_duration(source)
    except (subprocess.CalledProcessError, ValueError):
        source.unlink(missing_ok=True)
        return jsonify({"error": "影片格式無法讀取，請確認檔案不是損毀的影片"}), 400
    if duration > MAX_DURATION_SECONDS:
        source.unlink(missing_ok=True)
        return jsonify({"error": "影片最長 10 分鐘，請重新上傳較短版本"}), 400

    options_path = job_dir / "options.json"
    options_path.write_text(json.dumps({
        "cover_style": cover_style,
        "language": language,
        "original_filename": original_name,
        "duration_seconds": duration,
        "delete_after_minutes": 15,
        "started_at": time.time(),
    }, ensure_ascii=False, indent=2))

    log_path = job_dir / "run.log"
    log_file = log_path.open("w")
    child_env = os.environ.copy()
    child_env.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
    child_env.setdefault("OMP_NUM_THREADS", "4")
    process = subprocess.Popen(
        ["python3", str(PIPELINE), str(source), str(job_dir), str(options_path)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
        env=child_env,
    )
    jobs[job_id] = {
        "process": process,
        "dir": job_dir,
        "log": log_path,
        "started_at": time.time(),
        "duration_seconds": duration,
    }
    return jsonify({"job_id": job_id, "duration_seconds": duration})


@app.get("/jobs/<job_id>")
def job_status(job_id):
    cleanup_old_files()
    job = jobs.get(job_id)
    job_dir = OUTPUTS / job_id
    if not job and not job_dir.exists():
        return jsonify({"error": "找不到這個任務"}), 404
    log_path = job["log"] if job else job_dir / "run.log"
    result_path = job_dir / "result.json"
    running = job["process"].poll() is None if job else False
    status = "running" if running else "done"
    error = None
    if job and not running and job["process"].returncode != 0:
        status = "error"
        error = "處理失敗，請看 log。"
    result = json.loads(result_path.read_text()) if result_path.exists() else None
    log = log_path.read_text(errors="ignore")[-8000:] if log_path.exists() else ""
    if "OMP: Error #15" in log:
        status = "error"
        error = "轉錄引擎初始化失敗，已修正 OpenMP 設定，請重新上傳一次。"
    elif not running and not result:
        status = "error"
        error = "處理中斷，沒有產生輸出檔。請重新上傳一次。"
    options_path = job_dir / "options.json"
    options = json.loads(options_path.read_text()) if options_path.exists() else {}
    started_at = job.get("started_at") if job else options.get("started_at", job_dir.stat().st_mtime)
    duration = job.get("duration_seconds") if job else options.get("duration_seconds", 60)
    progress_state = parse_progress_state(job_dir)
    progress = processing_progress(log, status, result, started_at, duration, progress_state)
    return jsonify({
        "job_id": job_id,
        "status": status,
        "error": error,
        "log": log,
        "result": result,
        "progress": progress,
    })


@app.post("/jobs/<job_id>/cover")
def regenerate_cover(job_id):
    cleanup_old_files()
    job_dir = OUTPUTS / job_id
    result_path = job_dir / "result.json"
    if not result_path.exists():
        return jsonify({"error": "找不到這個任務或結果尚未完成"}), 404

    payload = request.get_json(silent=True) or {}
    result = json.loads(result_path.read_text())
    candidates = result.get("cover_candidates") or []

    # `candidate` is optional — when only `style` is sent we stick with whichever
    # candidate is currently selected so the user can flip palettes without
    # losing their chosen frame.
    candidate_name = (payload.get("candidate") or "").strip()
    if not candidate_name:
        candidate_name = result.get("selected_cover_candidate") or ""
        selected = next((c for c in candidates if c.get("selected")), None)
        if not candidate_name and selected:
            candidate_name = selected["filename"]
    if not candidate_name or "/" in candidate_name or "\\" in candidate_name:
        return jsonify({"error": "請選擇一張候選封面"}), 400

    candidate = next((item for item in candidates if item.get("filename") == candidate_name), None)
    if not candidate:
        return jsonify({"error": "找不到這張候選封面"}), 404

    candidate_path = job_dir / candidate_name
    if not candidate_path.exists():
        return jsonify({"error": "候選封面已被清除，請重新上傳影片"}), 410

    requested_style = (payload.get("style") or "").strip()
    if requested_style and requested_style not in ALLOWED_COVER_STYLES:
        return jsonify({"error": "不支援的封面風格"}), 400
    requested_language = (payload.get("language") or "").lower().strip()
    if requested_language and requested_language not in ALLOWED_LANGUAGES:
        return jsonify({"error": "不支援的語言"}), 400

    # Import lazily so the Flask process does not need to load Whisper at boot.
    from reels_gui_pipeline import render_cover

    memory = result.get("memory") or json.loads(MEMORY.read_text())
    cover_copy = result.get("cover_copy")
    style = (
        requested_style
        or result.get("cover_style")
        or (cover_copy or {}).get("default_style")
        or "editorial"
    )
    language = requested_language or result.get("language") or "zh"
    cover_path = job_dir / result["cover"]
    cover_base = cover_path.with_name("cover_base.jpg")
    shutil.copy2(candidate_path, cover_base)

    try:
        render_cover(cover_base, cover_path, memory, cover_copy, style, language=language)
    except Exception as error:
        return jsonify({"error": f"重新產生封面失敗：{error}"}), 500

    for item in candidates:
        item["selected"] = item.get("filename") == candidate_name
    result["cover_candidates"] = candidates
    result["selected_cover_candidate"] = candidate_name
    result["cover_style"] = style
    result["language"] = language
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))

    cover_url = f"/outputs/{job_id}/{result['cover']}?t={int(time.time())}"
    return jsonify({
        "job_id": job_id,
        "selected_cover_candidate": candidate_name,
        "cover_style": style,
        "language": language,
        "cover_url": cover_url,
        "cover_candidates": candidates,
    })


@app.get("/outputs/<job_id>/<path:filename>")
def output_file(job_id, filename):
    cleanup_old_files()
    job_dir = OUTPUTS / job_id
    if not (job_dir / filename).exists():
        return (
            """
            <!doctype html>
            <html lang="zh-Hant">
            <head>
              <meta charset="utf-8">
              <meta name="viewport" content="width=device-width, initial-scale=1">
              <title>檔案已清除</title>
              <style>
                body { margin: 0; min-height: 100vh; display: grid; place-items: center; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: #f3f5f2; color: #15171c; }
                main { width: min(560px, calc(100% - 32px)); padding: 28px; border: 1px solid #d9dee7; border-radius: 8px; background: white; box-shadow: 0 22px 70px rgba(20, 24, 31, .10); }
                h1 { margin: 0 0 10px; font-size: 28px; }
                p { color: #68707c; font-size: 16px; line-height: 1.55; }
                a { display: inline-flex; margin-top: 10px; padding: 12px 15px; border-radius: 7px; background: #15171c; color: white; text-decoration: none; font-weight: 900; }
              </style>
            </head>
            <body>
              <main>
                <h1>檔案已清除或不存在</h1>
                <p>輸出的 Reels 影片與封面會在上傳 15 分鐘後自動刪除。請回到主頁重新上傳影片產生新版本。</p>
                <a href="/">回到 Reels AI Editor</a>
              </main>
            </body>
            </html>
            """,
            404,
        )
    return send_from_directory(job_dir, filename, as_attachment=False)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5057, debug=False)
