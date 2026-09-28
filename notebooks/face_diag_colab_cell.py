# Paste this ENTIRE file into ONE Colab cell, after restarting DATT with the
# diagnostic export hook. Run from the repository directory (%cd /content/datt).
from pathlib import Path
import json
import os
import runpy
import time
import uuid

ROOT = Path.cwd()
assert (ROOT / "src/main.py").is_file(), "Hãy %cd vào thư mục repository DATT."
DIAG = ROOT / "scratch/face_diag"
DIAG.mkdir(parents=True, exist_ok=True)
TRACK_ID = None  # Set to a visible person's track ID, or select the largest person.

if (DIAG / "request.processing.json").exists():
    raise RuntimeError("Đang xuất snapshot hoặc lần xuất trước lỗi; kiểm tra scratch/face_diag/error.json và log DATT.")
if (DIAG / "request.json").exists():
    request_id = json.loads((DIAG / "request.json").read_text())["request_id"]
    print("Chờ request đang có:", request_id)
else:
    request_id = uuid.uuid4().hex
    pending = DIAG / "request.tmp.json"
    pending.write_text(json.dumps({"request_id": request_id, "track_id": TRACK_ID}))
    os.replace(pending, DIAG / "request.json")

print("Đang chờ DATT xuất 1 snapshot; không đọc MJPEG, không mở lại source...")
deadline = time.monotonic() + 60
while True:
    error_file = DIAG / "error.json"
    if error_file.exists():
        try:
            error = json.loads(error_file.read_text())
        except json.JSONDecodeError:
            error = {}
        if error.get("request_id") == request_id:
            raise RuntimeError(error["error"])
    snapshot_file = DIAG / "snapshot.json"
    if snapshot_file.exists():
        metadata = json.loads(snapshot_file.read_text())
        if metadata.get("request_id") == request_id:
            break
    if time.monotonic() >= deadline:
        raise TimeoutError(
            "Chưa có snapshot. DATT cần nạp hook bằng restart một lần, chạy đúng repo, "
            "và có person track. Request vẫn đang chờ; chạy lại cell để chờ tiếp."
        )
    time.sleep(.25)

SCRFD_DIAG_RESULTS = runpy.run_path(str(ROOT / "scripts/diagnose_face_snapshot.py"))["run"](DIAG)
print("Ảnh và kết quả:", DIAG)
