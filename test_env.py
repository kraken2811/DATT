"""Environment-only validation; no weights, inference, or training."""

import importlib.util
import sqlite3
import sys


def check_import(name: str, module: str | None = None) -> None:
    try:
        __import__(module or name)
        print(f"[OK] {name}")
    except Exception as exc:
        print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")


print(f"Python: {sys.version.split()[0]}")
print(f"Executable: {sys.executable}")
print("--- Core CV and acceleration ---")
for name in ("numpy", "cv2", "Pillow", "scipy", "matplotlib", "pandas"):
    check_import(name, "PIL" if name == "Pillow" else None)
for name in ("openvino", "onnx", "onnxruntime"):
    check_import(name)

print("--- Detection, tracking, OCR, face, vector ---")
for name, module in (
    ("ultralytics", "ultralytics"),
    ("supervision", "supervision"),
    ("lapx", "lap"),
    ("deep-sort-realtime", "deep_sort_realtime"),
    ("easyocr", "easyocr"),
    ("paddleocr", "paddleocr"),
    ("insightface", "insightface"),
    ("faiss", "faiss"),
):
    check_import(name, module)

print("--- Backend, database, dashboard ---")
for name in ("fastapi", "uvicorn", "websockets", "sqlalchemy", "aiosqlite", "psycopg", "streamlit", "ipykernel"):
    check_import(name)
try:
    with sqlite3.connect(":memory:") as db:
        db.execute("select 1")
    print("[OK] SQLite connection")
except Exception as exc:
    print(f"[FAIL] SQLite connection: {exc}")

print("--- Environment metadata ---")
print(f"onnx module discoverable: {bool(importlib.util.find_spec('onnx'))}")
print(f"onnxruntime module discoverable: {bool(importlib.util.find_spec('onnxruntime'))}")
print("No model download or inference was performed.")
