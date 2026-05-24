import json
import subprocess
import time
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_from_directory


ROOT = Path(__file__).resolve().parent
UPLOADS = ROOT / "uploads"
OUTPUTS = ROOT / "outputs"
MEMORY = ROOT / "reels_memory.json"
PIPELINE = ROOT / "reels_gui_pipeline.py"

UPLOADS.mkdir(exist_ok=True)
OUTPUTS.mkdir(exist_ok=True)

app = Flask(__name__)
jobs = {}


def allowed(filename):
    return Path(filename).suffix.lower() in {".mp4", ".mov", ".m4v", ".avi"}


@app.get("/")
def index():
    return render_template("index.html", memory=json.loads(MEMORY.read_text()))


@app.post("/jobs")
def create_job():
    file = request.files.get("video")
    if not file or file.filename == "":
        return jsonify({"error": "請選擇影片檔"}), 400
    if not allowed(file.filename):
        return jsonify({"error": "目前支援 mp4 / mov / m4v / avi"}), 400

    job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8]
    job_dir = OUTPUTS / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    source = UPLOADS / f"{job_id}{Path(file.filename).suffix.lower()}"
    file.save(source)

    log_path = job_dir / "run.log"
    log_file = log_path.open("w")
    process = subprocess.Popen(
        ["python3", str(PIPELINE), str(source), str(job_dir)],
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=str(ROOT),
    )
    jobs[job_id] = {"process": process, "dir": job_dir, "log": log_path}
    return jsonify({"job_id": job_id})


@app.get("/jobs/<job_id>")
def job_status(job_id):
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
    return send_from_directory(OUTPUTS / job_id, filename, as_attachment=False)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5057, debug=False)
