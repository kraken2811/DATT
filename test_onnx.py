import cv2
import numpy as np
import onnxruntime as ort
from pathlib import Path

# 1. Khởi tạo session ONNX Runtime
MODEL_PATH = Path(__file__).resolve().parent / "models" / "yolov8n.onnx"
PROJECT_ROOT = MODEL_PATH.parent.parent
if not MODEL_PATH.is_file():
    raise FileNotFoundError(f"Không tìm thấy model ONNX: {MODEL_PATH}")
session = ort.InferenceSession(str(MODEL_PATH), providers=['CPUExecutionProvider'])
model_inputs = session.get_inputs()
input_name = model_inputs[0].name
input_shape = model_inputs[0].shape  # [1, 3, 640, 640]

# Danh sách nhãn COCO cơ bản
CLASSES = {0: "person", 2: "car", 3: "motorcycle", 7: "truck"}

# 2. Mở Webcam (0) hoặc file video test
cap = cv2.VideoCapture(0)

print("Dang khoi chay ONNX Runtime... Nhan 'q' de thoat.")

# Một số môi trường cài bản OpenCV headless nên không có cv2.imshow.
GUI_AVAILABLE = True

while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    h_orig, w_orig = frame.shape[:2]

    # Tiền xử lý ảnh: Resize về 640x640, đổi BGR sang RGB, chuẩn hóa [0, 1]
    input_img = cv2.resize(frame, (640, 640))
    input_img = cv2.cvtColor(input_img, cv2.COLOR_BGR2RGB)
    input_img = input_img.transpose((2, 0, 1)).astype(np.float32) / 255.0
    input_tensor = np.expand_dims(input_img, axis=0)

    # Chạy mô hình qua ONNX
    outputs = session.run(None, {input_name: input_tensor})
    
    # Post-processing cơ bản cho YOLOv8 (Output shape: [1, 84, 8400])
    preds = np.asarray(outputs[0]).squeeze(axis=0).T  # [8400, 84]
    scores = np.max(preds[:, 4:], axis=1)
    class_ids = np.argmax(preds[:, 4:], axis=1)
    
    # Lọc ngưỡng tin cậy > 0.4 và đúng class cần tìm
    mask = (scores > 0.4) & np.isin(class_ids, list(CLASSES.keys()))
    valid_boxes = preds[mask, :4]
    valid_scores = scores[mask]
    valid_classes = class_ids[mask]

    # Chuyển đổi tọa độ từ 640x640 về khung hình gốc
    for box, score, cls_id in zip(valid_boxes, valid_scores, valid_classes):
        xc, yc, w, h = box
        x1 = int((xc - w / 2) * (w_orig / 640))
        y1 = int((yc - h / 2) * (h_orig / 640))
        x2 = int((xc + w / 2) * (w_orig / 640))
        y2 = int((yc + h / 2) * (h_orig / 640))

        label = f"{CLASSES[cls_id]}: {score:.2f}"
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
        cv2.putText(frame, label, (x1, max(y1 - 10, 20)), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    if GUI_AVAILABLE:
        try:
            cv2.imshow("ONNX Detection Test", frame)
            key = cv2.waitKey(1) & 0xFF
            if key in (ord('q'), ord('Q'), 27):  # q/Q hoặc Esc
                break
        except cv2.error:
            GUI_AVAILABLE = False
            output_path = PROJECT_ROOT / "results" / "onnx_detection.jpg"
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(output_path), frame)
            print(f"OpenCV không có GUI; đã lưu kết quả tại: {output_path}")
            break

cap.release()
if GUI_AVAILABLE:
    try:
        cv2.destroyAllWindows()
    except cv2.error:
        pass
