"""Run from a Colab cell via runpy; reads a DATT snapshot, never loads ArcFace."""

import ast
import hashlib
import inspect
import json
from pathlib import Path
import textwrap

import cv2
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from IPython.display import display


def run(directory):
    directory = Path(directory)
    meta = json.loads((directory / "snapshot.json").read_text())
    payload = (directory / "native_frame.png").read_bytes()
    assert hashlib.sha256(payload).hexdigest() == meta["frame_sha256"], "Snapshot hash mismatch"
    frame = cv2.imdecode(np.frombuffer(payload, np.uint8), cv2.IMREAD_COLOR)
    assert frame is not None
    runtime = meta["runtime"]
    print("SNAPSHOT:", {k: v for k, v in meta.items() if k != "runtime"})
    display(pd.DataFrame([{k: v for k, v in runtime.items() if k != "wrapper_source"}]))
    x1, y1, x2, y2 = meta["person_bbox_xyxy"]
    h, w = frame.shape[:2]
    pw, ph = x2-x1, y2-y1
    px, pt = int(pw*.12), int(ph*.08)
    rois = {"full_person": (x1, y1, x2, y2)}
    for name, fraction in (("upper_58", .58), ("upper_70", .70)):
        rois[name] = (max(0, x1-px), max(0, y1-pt), min(w, x2+px), min(h, y1+int(ph*fraction)))
    print("Upper ROI: padding ngang 12%, trên 8%; bbox theo pixel frame gốc.")
    fig, axes = plt.subplots(1, 2, figsize=(18, 9))
    for ax in axes:
        ax.imshow(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)); ax.axis("off")
    axes[0].set_title("Native frame — chưa overlay")
    axes[1].set_title("ROI trên bản hiển thị riêng")
    for (name, (a, b, c, d)), color in zip(rois.items(), ("lime", "orange", "cyan")):
        axes[1].add_patch(plt.Rectangle((a, b), c-a, d-b, fill=False, color=color, label=name))
    axes[1].legend()
    fig.savefig(directory / "roi_overview.png", bbox_inches="tight")
    plt.show()

    # Read the actual primary production call's override, without inventing one.
    tree = ast.parse(textwrap.dedent(runtime["wrapper_source"]))
    calls = sorted((n for n in ast.walk(tree) if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute) and n.func.attr == "detect"),
                   key=lambda n: n.lineno)
    if not calls:
        raise RuntimeError("Không xác định được lời gọi detect production; dừng.")
    kwargs = {}
    for kw in calls[0].keywords:
        if kw.arg == "det_thresh":
            kwargs["det_thresh"] = ast.literal_eval(kw.value)
    effective_threshold = kwargs.get("det_thresh", runtime["det_thresh"])
    print("Model det_thresh:", runtime["det_thresh"], "| Primary-call threshold:", effective_threshold)
    print("Giữ threshold của primary production call cho cả 24 test; không chạy fallback hạ threshold.")

    if not runtime["model_file"] or not runtime["initialized"]:
        raise RuntimeError(f"Detector chưa được nạp trong DATT: {runtime['init_error']}")
    model_path = Path(runtime["model_file"])
    assert hashlib.sha256(model_path.read_bytes()).hexdigest() == runtime["model_sha256"], "Model hash mismatch"
    from insightface.model_zoo import get_model
    # A separate detection-only session in the notebook; production is untouched.
    detector = get_model(str(model_path), providers=runtime["providers"],
                         provider_options=[runtime["provider_options"].get(p, {})
                                           for p in runtime["providers"]])
    if type(detector).__name__ != runtime["class"]:
        raise RuntimeError("Detector class khác process DATT; không đo tiếp.")
    sizes = runtime.get("det_sizes") or [runtime["det_size"]]
    sizes = [tuple(s) for s in sizes]
    size_arg = sizes[0] if len(sizes) == 1 else sizes
    prepare_kw = {"input_size": size_arg, "det_thresh": runtime["det_thresh"]}
    if runtime["nms_thresh"] is not None:
        prepare_kw["nms_thresh"] = runtime["nms_thresh"]
    detector.prepare(ctx_id=0, **prepare_kw)
    if detector.session.get_providers() != runtime["providers"]:
        raise RuntimeError("Provider offline khác DATT; dừng thay vì âm thầm fallback.")
    if str(inspect.signature(detector.detect)) != runtime["detect_signature"]:
        raise RuntimeError("Signature detector khác DATT; dừng.")
    if detector.det_thresh != runtime["det_thresh"]:
        raise RuntimeError("Threshold offline khác DATT; dừng.")
    actual_sizes = getattr(detector, "input_sizes", None) or [detector.input_size]
    if [tuple(s) for s in actual_sizes] != sizes:
        raise RuntimeError("det_size offline khác DATT; dừng.")

    class SessionProbe:
        # Observe actual tensor shapes in this OFFLINE session only.
        def __init__(self, session):
            self.session, self.shapes = session, []

        def __getattr__(self, key):
            return getattr(self.session, key)

        def run(self, outputs, inputs, *args, **kw):
            self.shapes.extend([list(v.shape) for v in inputs.values()])
            return self.session.run(outputs, inputs, *args, **kw)

    probe = SessionProbe(detector.session)
    detector.session = probe

    def lighting(image):
        L = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)[:, :, 0]
        rh, rw = L.shape
        mask = np.zeros(L.shape, bool)
        mask[int(.2*rh):max(int(.2*rh)+1, int(.8*rh)),
             int(.2*rw):max(int(.2*rw)+1, int(.8*rw))] = True
        mean, center = float(L.mean()), float(L[mask].mean())
        edge = float(L[~mask].mean()) if (~mask).any() else mean
        p90 = float(np.percentile(L, 90))
        cls = "BACKLIT" if (p90 >= 170 and center < 85) or p90-center > 90 else "DARK" if mean < 75 or center < 70 else "NORMAL"
        return dict(mean_luma=mean, center_luma=center, edge_luma=edge, illumination_class=cls)

    rows = []
    for name, (a, b, c, d) in rois.items():
        crop = frame[b:d, a:c].copy()
        rh, rw = crop.shape[:2]
        lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB)
        enhanced = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(8, 8)).apply(lab[:, :, 0])
        lut = np.round(255*(np.arange(256)/255.)**.9).astype(np.uint8)
        lab[:, :, 0] = cv2.LUT(enhanced, lut)
        variants = {"original": crop, "CLAHE_gamma": cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)}
        fig, axes = plt.subplots(2, 4, figsize=(20, 10))
        for row, (variant, image) in enumerate(variants.items()):
            for col, scale in enumerate((1, 2, 3, 4)):
                evaluated = cv2.resize(image, (rw*scale, rh*scale), interpolation=cv2.INTER_CUBIC)
                stem = f"{name}_{variant}_{scale}x"
                cv2.imwrite(str(directory / f"{stem}_input.png"), evaluated)
                record = dict(roi=name, variant=variant, roi_size=[rw, rh], scale=scale,
                              detector_argument_size=[rw*scale, rh*scale], det_thresh=effective_threshold,
                              **lighting(evaluated), face_count=None, confidence=None,
                              face_bbox=None, face_size=None, face_bbox_frame=None, error=None)
                drawn = evaluated.copy()
                probe.shapes = []
                try:
                    boxes, _ = detector.detect(evaluated, max_num=0, **kwargs)
                    boxes = np.empty((0, 5)) if boxes is None else np.asarray(boxes)
                    record["face_count"] = len(boxes)
                    record["confidence"] = 0.0
                    if len(boxes):
                        best = boxes[np.argmax(boxes[:, 4])]
                        bb = best[:4] / scale
                        record.update(confidence=float(best[4]), face_bbox=bb.tolist(),
                                      face_size=(bb[2:]-bb[:2]).tolist(),
                                      face_bbox_frame=(bb+[a,b,a,b]).tolist())
                        for box in boxes:
                            p, q, r, s = np.rint(box[:4]).astype(int)
                            cv2.rectangle(drawn, (p, q), (r, s), (0, 255, 0), 2)
                except Exception as exc:
                    record["error"] = f"{type(exc).__name__}: {exc}"
                record["detector_input_tensor_shapes"] = probe.shapes.copy()
                rows.append(record)
                cv2.imwrite(str(directory / f"{stem}_debug.png"), drawn)
                ax = axes[row, col]
                ax.imshow(cv2.cvtColor(drawn, cv2.COLOR_BGR2RGB)); ax.axis("off")
                ax.set_title(f"{variant} {scale}x | {rw*scale}x{rh*scale}\n"
                             + ("ERROR" if record["error"] else f"n={record['face_count']} conf={record['confidence']:.4f}"))
        fig.suptitle(f"{name} | native ROI={rw}x{rh} | xyxy={a,b,c,d}")
        plt.tight_layout()
        fig.savefig(directory / f"{name}_grid.png", bbox_inches="tight")
        plt.show()
    results = pd.DataFrame(rows)
    results.to_csv(directory / "results.csv", index=False)
    (directory / "results.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    with pd.option_context("display.max_rows", None, "display.max_columns", None, "display.max_colwidth", 150):
        display(results)
    print("face_bbox và face_size W,H tính trên ROI gốc, trước upscale; bbox_frame theo frame gốc.")
    print("Luma là LAB-L 0..255; center=20–80%, edge=phần còn lại. CLAHE=1.5; gamma exponent=0.9.")
    print("Không detect: size=None, không suy ra mặt thật có 0 pixel. Exception được ghi riêng.")
    print("Chưa kết luận A–G: cần xem ROI, mặt nguồn, các tensor input và bảng kết quả.")
    return results
