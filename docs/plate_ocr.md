# Plate OCR and preview streaming

The optional English PP-OCRv4 line recognizer reads detector-localized native
plate crops before the existing EasyOCR fallback. It uses ONNX Runtime already
installed for face inference; PaddleOCR/Paddle are not required in production.
Missing or invalid model files leave EasyOCR available and never trigger an
automatic model download. Install the optional model explicitly, then restart
the CLI-owned backend:

```sh
python scripts/fetch_plate_line_model.py
python scripts/datt.py restart --mode gpu
```

Weights are ignored by Git. A fresh Colab checkout must run the model command or
include the verified model in its existing model archive. No environment,
database migration, dependency reinstall or tracker/face setting change is needed.

Model: [PaddleOCR English PP-OCRv4](https://huggingface.co/PaddlePaddle/en_PP-OCRv4_mobile_rec).
The ONNX conversion is distributed in the
[RapidOCR model manifest](https://github.com/RapidAI/RapidOCR/blob/main/python/rapidocr/default_models.yaml),
release path `v3.9.2/onnx/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile.onnx`.
SHA-256: `e8770c967605983d1570cdf5352041dfb68fa0c21664f49f47b155abd3e0e318`.
The model projects use Apache-2.0 licensing. Inference preserves the model's
BGR normalization, 48-pixel line height and CTC dictionary/blank decoding.

The reader tries at most two regions inside the original detector box: the
original crop and one bounded bright-background crop. Square plates are read
as two rows; wide plates as one row. Each row needs a score of at least 0.80
on this model's score scale, and the existing VN format validator must pass.
Conflicting valid region results are rejected by this recognizer. Missing
characters are never supplied by a watchlist. The existing per-track minimum
observations, agreement ratio, generation isolation and notification gates
remain unchanged. Crop-level gains do not establish whole-video accuracy.

`/frame_stream` delivers paired JPEG/JSON packets through one HTTP connection,
without a browser round trip per image. Each packet starts with two big-endian
uint32 lengths (metadata bytes, JPEG bytes), then UTF-8 JSON and JPEG. An idle
heartbeat has zero JPEG bytes. The browser bounds buffered incomplete packets,
discards older complete frames in a received batch, and cancels on source change.
Three consecutive streaming connection failures activate `/frame_packet` fallback.
After three seconds without a newly painted frame the UI reports a stale stream.
Display FPS measures canvas paints; it is not the source video's capture FPS.
