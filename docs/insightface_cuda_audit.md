# InsightFace CUDA fallback audit — Colab T4

Verified on 2026-09-30 in the user's connected Colab runtime:

- Torch 2.11.0+cu128, CUDA 12.8, cuDNN 9.19; Tesla T4.
- InsightFace 2.0, ONNX Runtime GPU 1.30.0.
- CUDA appeared in `get_available_providers()`, but every InsightFace session
  and both direct ORT sessions used only CPU, with options `{'CPUExecutionProvider': {}}`.
- `ldd libonnxruntime_providers_cuda.so` reported missing
  `libcublasLt.so.13`, `libcublas.so.13`, and `libcudart.so.13`.
  Earlier notebook initialization also reported missing `libnvrtc.so.13`
  and `libcufft.so.12`.

The CUDA 13 ORT wheel cannot load its CUDA provider in this CUDA 12 runtime.
This is independent of face matching, model thresholds, and recognition logic.

`FaceEmbedder.initialize()` passes
`[('CUDAExecutionProvider', {'device_id': 0}), 'CPUExecutionProvider']`
with `ctx_id=0`. InsightFace forwards these arguments. Its SCRFD and ArcFace
`prepare()` methods force CPU only for `ctx_id < 0`, which does not apply here.
`initialize() == True` means models loaded successfully, including CPU fallback;
it does not promise GPU execution. Already-initialized singleton sessions remain
CPU until their owning process is restarted.

## Minimal correction

Use the verified CUDA 12 build, `onnxruntime-gpu==1.26.0`. Leave Torch,
CUDA, cuDNN, InsightFace, model files, and thresholds unchanged.
InsightFace 2.0's dependency installation also installs CPU `onnxruntime`;
both distributions share import files, so clean up the overlap **after** all
requirements have been installed:

```python
import subprocess, sys
subprocess.run([sys.executable, '-m', 'pip', 'uninstall', '-y',
                'onnxruntime', 'onnxruntime-gpu'], check=True)
subprocess.run([sys.executable, '-m', 'pip', 'install', '--no-deps',
                'onnxruntime-gpu==1.26.0'], check=True)
```

Restart Python processes which already imported ORT. Do not try `importlib.reload`
to swap a loaded native runtime. Do not subsequently run unpinned
`pip install -U onnxruntime-gpu` (the notebook contained such a command, which
upgraded an earlier 1.26.0 installation back to 1.30.0).

## Verification

First tested 1.26.0 in an isolated target directory and fresh subprocess.
Both direct ORT sessions and all five DATT InsightFace sessions reported
`['CUDAExecutionProvider', 'CPUExecutionProvider']`, with CUDA `device_id='0'`.
Actual ORT profiling on synthetic inputs recorded:

| Model | CUDA node events | CPU node events |
|---|---:|---:|
| SCRFD `det_500m.onnx` (320×320) | 132 | 12 |
| ArcFace `w600k_mbf.onnx` (112×112) | 98 | 0 |

CPU entries remaining in a GPU session are permitted fallback/shape operations;
the node profile proves GPU inference actually executed. The 320×320 direct
SCRFD test emitted output-shape metadata warnings; verification after installation
uses 640×640 synthetic input. DATT detection size and thresholds are unchanged.

Official compatibility table:
https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html

## Installed runtime and live service verification

After the isolated test succeeded, installed GPU ORT 1.26.0 in Colab and
removed the overlapping CPU distribution. Repeated profiling with SCRFD
640x640: 132 CUDA node events and 12 CPU node events; ArcFace: 98 CUDA and
0 CPU. The fresh-process test produced no CUDA initialization errors.

Restarted the idle DATT service in a fresh process. Its actual detection and
recognition sessions both report CUDA followed by CPU, with CUDA device 0.
Both HTTP services (8000 and 8501) return 200; the service process is alive,
and its new log contains no CUDA library loading errors.

The notebook kernel itself still holds its previously imported native ORT
module. Old notebook variables are stale; restart that kernel before using
them to re-audit. The restarted DATT service uses ORT 1.26.0 already.
