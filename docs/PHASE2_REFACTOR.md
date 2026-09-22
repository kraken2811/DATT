# Phase 2 Refactor Document: DATT - AI People Counter

Tài liệu này ghi nhận toàn bộ quá trình tái cấu trúc kiến trúc (Refactor Phase 2) của dự án **DATT - AI People Counter** trên nhánh `refactor-colab`.

Mục tiêu chính là chuyển đổi mã nguồn từ dạng **monolithic script** sang **kiến trúc module hóa chuẩn**, chuẩn bị sẵn sàng để thay thế engine detector sang **PyTorch CUDA (Google Colab)** ở Phase 3 mà không cần can thiệp vào tầng Stream, Tracker, Counter hay App orchestrator.

---

## 1. So Sánh Kiến Trúc Cũ vs Kiến Trúc Mới

### 1.1. Kiến Trúc Cũ (Baseline v1.0)
Toàn bộ luồng dữ liệu nằm gộp chung trong file duy nhất `test_tracking_hybrit.py`:
- Khởi tạo ONNX session, cấu hình tham số, đọc stream YouTube qua FFmpeg đa luồng, xử lý ảnh letterbox, chia tile, inference ONNX, NMS IoS, ByteTrack, ZoneCounter và vòng lặp render HUD / OpenCV imshow được viết dính liền trong cùng một file script.
- Các module khác trong `src/` chỉ là các file rỗng `__init__.py`.

### 1.2. Kiến Trúc Mới (Modular Phase 2)
Mã nguồn được phân rã thành các tầng trách nhiệm độc lập (Separation of Concerns):

```
DATT/
├── app.py                      # Bộ điều phối trung tâm (Pipeline Orchestrator)
├── config.py                   # Cấu hình tập trung toàn hệ thống
├── requirements.txt            # Danh sách thư viện phụ thuộc
├── test_tracking_hybrit.py     # Giữ nguyên làm chuẩn baseline đối chiếu
├── src/
│   ├── detector/
│   │   ├── __init__.py
│   │   └── yolo_detector.py    # Class YOLODetector (ONNX Runtime, Letterbox, Tiling, IoS NMS)
│   ├── stream/
│   │   ├── __init__.py
│   │   └── youtube_stream.py   # Class CameraReader (yt-dlp + FFmpeg multi-threaded pipe)
│   ├── tracker/
│   │   ├── __init__.py
│   │   └── bytetrack_tracker.py # Class PersonTracker (Supervision ByteTrack wrapper)
│   ├── counter/
│   │   ├── __init__.py
│   │   └── zone_counter.py     # Class ZoneCounter (Đếm occupancy người theo frame/polygon)
│   └── utils/
│       ├── __init__.py
│       ├── logger.py           # Tiện ích logging chuẩn hóa
│       └── fps.py              # Bộ đo Processing FPS & rolling window
└── docs/
    └── PHASE2_REFACTOR.md      # Tài liệu báo cáo Phase 2
```

---

## 2. Bảng Mapping File Cũ Sang File Mới

| Thành phần Logic | Vị trí cũ trong `test_tracking_hybrit.py` | Vị trí mới sau Refactor |
| :--- | :--- | :--- |
| **Cấu hình toàn hệ thống** | Dòng 17 - 63 (biến toàn cục) | `config.py` |
| **Trích xuất stream YouTube** | Dòng 64 - 85 (`get_stream_url`) | `src/stream/youtube_stream.py` |
| **Đọc frame FFmpeg đa luồng** | Dòng 259 - 353 (`CameraReader`) | `src/stream/youtube_stream.py` (`CameraReader`) |
| **Pre-process (Letterbox & Tile)** | Dòng 87 - 101, 140 - 156 | `src/detector/yolo_detector.py` |
| **Post-process (Decode & IoS NMS)**| Dòng 166 - 257 (`detect_tiled`) | `src/detector/yolo_detector.py` (`YOLODetector.detect`) |
| **Theo dõi đối tượng (ByteTrack)** | Dòng 400 - 406, 475 | `src/tracker/bytetrack_tracker.py` (`PersonTracker`) |
| **Đếm người trong vùng/khung hình** | Dòng 103 - 138 (`ZoneCounter`) | `src/counter/zone_counter.py` (`ZoneCounter`) |
| **Vẽ HUD & Hiển thị** | Dòng 480 - 555 | `app.py` (`draw_hud`) |
| **Vòng lặp điều phối chính** | Dòng 441 - 573 (`main`) | `app.py` (`main`) |

---

## 3. Chi Tiết Những Phần Giữ Nguyên (Preserved Logic)

1. **Thuật toán & Toán học Detection**:
   - `letterbox`: Giữ nguyên tỷ lệ khung hình, resize và bù viền đen đối xứng.
   - `make_tiles`: Giữ nguyên công thức chia tile chồng lấn (overlap 15%).
   - `decode_person_boxes`: Giữ nguyên cách reshape tensor `(1, 4+C, N) -> (N, 4+C)`, lọc nhãn `PERSON_CLASS_ID = 0`, ngưỡng tin cậy `0.35`, unpad tọa độ về frame gốc và giới hạn clip vào kích thước ảnh.
   - `IoS NMS`: Sử dụng metric `OverlapMetric.IOS` ở ngưỡng `0.45` để khử hộp trùng lặp ở mép các tile liền kề.
2. **Model & Runtime**:
   - Vẫn sử dụng mô hình ONNX: `models/yolo11s_640.onnx`.
   - Vẫn sử dụng `onnxruntime` với danh sách providers ưu tiên `DmlExecutionProvider` và fallback `CPUExecutionProvider`.
3. **Logic Ingestion**:
   - Luồng FFmpeg đọc trực tiếp từ `stdout.PIPE` theo block bytes `WIDTH * HEIGHT * 3` định dạng `bgr24`.
   - Cơ chế zero-queue: chỉ lưu `latest_frame`, không tích lũy frame cũ gây trễ.
4. **ByteTrack Hyperparameters**:
   - `track_activation_threshold = 0.40`
   - `lost_track_buffer = 30`
   - `minimum_matching_threshold = 0.80`
   - `minimum_consecutive_frames = 2`
5. **File tham chiếu gốc**:
   - File `test_tracking_hybrit.py` được giữ nguyên vẹn 100% làm chuẩn baseline.

---

## 4. Chi Tiết Những Phần Thay Đổi & Cải Tiến

1. **Chuẩn Hóa Interface Đầu Ra Của Detector**:
   - `YOLODetector.detect(frame)` trả về định dạng độc lập:
     ```python
     {
         "xyxy": np.ndarray,        # Bounding box [N, 4]
         "confidence": np.ndarray,  # Độ tin cậy [N]
         "class_id": np.ndarray     # Class ID [N]
     }
     ```
   - Lớp `PersonTracker` chỉ nhận dict/object chứa 3 trường dữ liệu này, hoàn toàn không phụ thuộc vào `onnxruntime` hay định dạng tensor cụ thể. Khi sang Phase 3 chuyển sang PyTorch CUDA, chỉ cần viết `pytorch_detector.py` trả về đúng format này mà không sửa các phần còn lại.
2. **Tương Thích FFmpeg 7+ và 9+**:
   - Loại bỏ cờ `-vsync 0` (đã bị FFmpeg 7+ deprecated và FFmpeg 9+ loại bỏ hoàn toàn) trong cấu hình subprocess, đảm bảo stream chạy ổn định trên mọi phiên bản FFmpeg hiện đại.
3. **Hỗ Trợ Môi Trường Headless (Google Colab)**:
   - Trong `app.py`, việc hiển thị qua `cv2.imshow` được bọc try-except bắt lỗi `cv2.error`. Khi chạy trên Colab hoặc server không có giao diện đồ họa, ứng dụng tự động chuyển sang chế độ headless và ghi log console mà không crash.
4. **Quản Lý Cấu Hình Tập Trung**:
   - Toàn bộ siêu tham số được đặt tại `config.py`. Không còn tham số nào bị hard-code trong mã nguồn các module.

---

## 5. Kết Quả Kiểm Tra Hồi Quy (Regression Testing)

Đã thực hiện kiểm thử tự động so sánh trực tiếp kết quả giữa baseline và refactored pipeline:
1. **Kiểm thử trên ảnh tĩnh (`results/onnx_detection.jpg`)**:
   - Số lượng detection: **1 vs 1** (Trùng khớp 100%).
   - Độ lệch tọa độ bounding box (`xyxy`): **0.000000** (Chính xác tuyệt đối).
   - Độ lệch điểm tin cậy (`confidence`): **0.000000** (Chính xác tuyệt đối).
   - Số lượng track và count: **0 vs 0** (Trùng khớp 100%).
2. **Kiểm thử trên Live Stream YouTube**:
   - Nhận diện và trích xuất stream thành công.
   - Luồng camera đạt tốc độ nhận khung hình 30 - 100+ FPS.
   - Pipeline xử lý và cập nhật chỉ số HUD mượt mà.
