import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory
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


def allowed(filename):
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


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
    }, ensure_ascii=False, indent=2))

    log_path = job_dir / "run.log"
    log_file = log_path.open("w")
    process = subprocess.Popen(
        ["python3", str(PIPELINE), str(source), str(job_dir), str(options_path)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
    )
    jobs[job_id] = {"process": process, "dir": job_dir, "log": log_path}
    return jsonify({"job_id": job_id})


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
    return jsonify({
        "job_id": job_id,
        "status": status,
        "error": error,
        "log": log,
        "result": result,
    })


@app.get("/outputs/<job_id>/<path:filename>")
def output_file(job_id, filename):
    cleanup_old_files()
    return send_from_directory(OUTPUTS / job_id, filename, as_attachment=False)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5057, debug=False)
