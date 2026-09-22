import cv2
import numpy as np
import onnxruntime as ort
import supervision as sv
from pathlib import Path

# 1. Khởi tạo ONNX Runtime
MODEL_PATH = Path(__file__).resolve().parent / "models" / "yolov8n.onnx"
session = ort.InferenceSession(str(MODEL_PATH), providers=['CPUExecutionProvider'])
model_inputs = session.get_inputs()
input_name = model_inputs[0].name

# 2. Tracker và Annotator
tracker = sv.ByteTrack()
box_annotator = sv.BoxAnnotator(thickness=2)
label_annotator = sv.LabelAnnotator(text_scale=0.5, text_thickness=1)

# Biến đếm và bộ nhớ theo dõi ID
fallback_counter = 0
counted_ids = set()           # Lưu các ID đã được đếm (chống đếm trùng)
track_frame_count = {}        # Đếm số frame mà mỗi ID đã xuất hiện {track_id: so_frame}
TRIGGER_FRAME_THRESHOLD = 45  # Xuất hiện liên tục ~1.5 giây thì tự cộng 1

cap = cv2.VideoCapture(0)
print("Auto-increment Test dang chay... Nhan 'q' de thoat.")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    h_orig, w_orig = frame.shape[:2]

    # Preprocessing
    input_img = cv2.resize(frame, (640, 640))
    input_img = cv2.cvtColor(input_img, cv2.COLOR_BGR2RGB)
    input_img = input_img.transpose((2, 0, 1)).astype(np.float32) / 255.0
    input_tensor = np.expand_dims(input_img, axis=0)

    # Inference
    outputs = session.run(None, {input_name: input_tensor})
    preds = np.asarray(outputs[0]).squeeze(axis=0).T

    scores = np.max(preds[:, 4:], axis=1)
    class_ids = np.argmax(preds[:, 4:], axis=1)

    mask = (scores > 0.45) & (class_ids == 0)
    valid_boxes = preds[mask, :4]
    valid_scores = scores[mask]

    xyxy = []
    for box in valid_boxes:
        xc, yc, w, h = box
        x1 = (xc - w / 2) * (w_orig / 640)
        y1 = (yc - h / 2) * (h_orig / 640)
        x2 = (xc + w / 2) * (w_orig / 640)
        y2 = (yc + h / 2) * (h_orig / 640)
        xyxy.append([x1, y1, x2, y2])

    xyxy = np.array(xyxy) if len(xyxy) > 0 else np.empty((0, 4))

    detections = sv.Detections(
        xyxy=xyxy,
        confidence=valid_scores,
        class_id=np.zeros(len(valid_scores), dtype=int)
    )
    detections = detections.with_nms(threshold=0.5)
    detections = tracker.update_with_detections(detections)

    # --- LOGIC TỰ ĐỘNG CỘNG 1 KHI CHƯA ĐƯỢC ĐẾM ---
    labels = []
    if detections.tracker_id is not None:
        for track_id, conf in zip(detections.tracker_id, detections.confidence):
            # Tăng số khung hình mà ID này xuất hiện
            track_frame_count[track_id] = track_frame_count.get(track_id, 0) + 1

            # Nếu ID này chưa đếm và đã xuất hiện đủ ngưỡng khung hình
            if track_id not in counted_ids:
                if track_frame_count[track_id] >= TRIGGER_FRAME_THRESHOLD:
                    fallback_counter += 1
                    counted_ids.add(track_id)
                    print(f"[EVENT] Auto Counted ID #{track_id} -> Tong: {fallback_counter}")

            status = "COUNTED" if track_id in counted_ids else f"Waiting ({track_frame_count[track_id]}/{TRIGGER_FRAME_THRESHOLD})"
            labels.append(f"ID #{track_id} | {status}")

    # Vẽ kết quả
    frame = box_annotator.annotate(scene=frame, detections=detections)  # type: ignore
    frame = label_annotator.annotate(scene=frame, detections=detections, labels=labels)  # type: ignore

    # Hiển thị HUD bảng đếm trên góc trái màn hình
    cv2.rectangle(frame, (10, 10), (280, 60), (0, 0, 0), -1)
    cv2.putText(frame, f"TOTAL COUNT: {fallback_counter}", (20, 45),
                cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 255), 2)

    cv2.imshow("Auto Count Fallback Test", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()