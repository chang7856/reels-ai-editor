import json
import os
import shutil
import subprocess
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

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1_200 * 1024 * 1024
jobs = {}

MAX_DURATION_SECONDS = 600
MAX_RETENTION_SECONDS = 3 * 60 * 60
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v"}
ALLOWED_COVER_STYLES = {"editorial", "creator", "high_contrast"}
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
    if not file or file.filename == "":
        return jsonify({"error": "請選擇影片檔"}), 400
    if not allowed(file.filename):
        return jsonify({"error": "目前只支援 mp4 / mov / m4v"}), 400
    if cover_style not in ALLOWED_COVER_STYLES:
        return jsonify({"error": "不支援的封面風格"}), 400

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
        "original_filename": original_name,
        "duration_seconds": duration,
        "delete_after_hours": 3,
        "started_at": time.time(),
    }, ensure_ascii=False, indent=2))

    log_path = job_dir / "run.log"
    log_file = log_path.open("w")
    process = subprocess.Popen(
        ["python3", str(PIPELINE), str(source), str(job_dir), str(options_path)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
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


@app.get("/outputs/<job_id>/<path:filename>")
def output_file(job_id, filename):
    cleanup_old_files()
    return send_from_directory(OUTPUTS / job_id, filename, as_attachment=False)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5057, debug=False)
