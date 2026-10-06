# Hệ Thống Giám Sát Thị Giác Thông Minh DATT (Documentation Hub)

Chào mừng bạn đến với bộ tài liệu kỹ thuật và hướng dẫn vận hành toàn diện của **Hệ Thống Giám Sát Thị Giác Thông Minh Đa Luồng DATT** (Deep AI Tracking & Targeting System).

Hệ thống được phát triển nhằm mục đích giám sát video thời gian thực từ nhiều nguồn camera (RTSP, HLS, YouTube Live, WebRTC, Video File), ứng dụng thị giác máy tính và học sâu (Deep Learning) để phát hiện đối tượng, bám vết đa mục tiêu (Multi-Object Tracking), nhận diện khuôn mặt hai pha (Two-pass Face Recognition với SCRFD & AdaFace) và tự động nhận dạng biển số xe (ANPR/ALPR với YOLOv11 & EasyOCR), đối soát danh sách theo dõi (Watchlist) và kích hoạt cảnh báo tức thời qua Event Center và Email Notification.

---

## Danh Mục Tài Liệu Hệ Thống

Bộ tài liệu này được cấu trúc chi tiết dành riêng cho 3 nhóm đối tượng: **Người dùng cuối (End-user)**, **Quản trị viên hệ thống (System Administrator)** và **Kỹ sư phát triển phần mềm (Software/AI Engineer)**.

| STT | Tài Liệu | Đối Tượng Phục Vụ | Nội Dung Chính | Liên Kết Truy Cập |
|---|---|---|---|---|
| **01** | **Hướng Dẫn Sử Dụng Người Dùng** | Người vận hành, Giám sát viên an ninh | Giao diện Live View, Quản lý Camera, Danh sách đối tượng khuôn mặt, Danh sách biển số xe theo dõi, Trung tâm sự kiện (Event Center), Bộ lọc tìm kiếm sự kiện, Cảnh báo thông báo, Câu hỏi thường gặp (FAQ). | [USER_GUIDE.md](USER_GUIDE.md) |
| **02** | **Điều Kiện & Yêu Cầu Kỹ Thuật** | IT Ops, Kỹ sư hạ tầng, Triển khai | Cấu hình phần cứng tối thiểu & khuyến nghị, Yêu cầu GPU NVIDIA CUDA/TensorRT, Phiên bản Python 3.11, PostgreSQL 17 + `pgvector`, Tiêu chuẩn nguồn cấp video camera RTSP/HLS, Điều kiện ảnh khuôn mặt & góc nghiêng biển số, Biến môi trường `.env`. | [SYSTEM_REQUIREMENTS.md](SYSTEM_REQUIREMENTS.md) |
| **03** | **Tài Liệu Quản Trị Hệ Thống** | DevOps, System Admin, DB Admin | Quy trình cài đặt môi trường (Local / Docker / Google Colab), Cấu hình biến môi trường, Khởi tạo và chạy 11 Alembic Migrations, Quản lý Database PostgreSQL/SQLite và Supabase Storage, Tải trọng số AI Models, Khởi động/Dừng dịch vụ qua CLI & FastAPIServer, Giám sát log và Sao lưu phục hồi dữ liệu. | [ADMIN_GUIDE.md](ADMIN_GUIDE.md) |
| **04** | **Tài Liệu Kiến Trúc Kỹ Thuật** | Kỹ sư AI, Backend & Frontend Dev | Kiến trúc chi tiết Pipeline xử lý luồng, AI Models (YOLO11s, ByteTrack, Two-pass SCRFD, AdaFace IR50 512-d, PlateDetector, EasyOCR, Color Extractor), Thuật toán đồng thuận biển số 10-frame consensus (ECC median), Database Worker Thread & Async Engine (`NullPool`), Cơ chế Notification Outbox & Exponential Backoff, Binary Frame Streaming (Giao thức 64-byte Header DATT). | [TECHNICAL_GUIDE.md](TECHNICAL_GUIDE.md) |
| **05** | **Sơ Đồ Luồng Hoạt Động (Mermaid)** | Solution Architect, Developer | 10 biểu đồ Mermaid chuẩn hóa trực quan hóa: Luồng xử lý camera đa luồng, Pipeline nhận diện khuôn mặt hai pha, Đối soát Face Watchlist Cosine Similarity, Nhận diện và chuẩn hóa biển số, Khởi tạo và gom cụm sự kiện (Episode Coalescing), Luồng cảnh báo và gửi Email tự động, Tương tác cơ sở dữ liệu và Luồng API Frontend - Backend - Database. | [SYSTEM_FLOWS.md](SYSTEM_FLOWS.md) |
| **06** | **Cẩm Nang Xử Lý Sự Cố (Troubleshooting)** | Vận hành viên, Helpdesk, DevOps | 22 kịch bản lỗi chi tiết từ thực tế mã nguồn: Camera mất kết nối/lag FPS, CUDA out of memory, Không phát hiện khuôn mặt hoặc nhận diện nhầm, OCR đọc sai ký tự biển số xe, Lỗi kết nối DB và Migration ForeignKey, Email Notification pending/failed, Lỗi mã hóa JSON và Frontend ngắt kết nối WebSocket/Fetch API. Định dạng chuẩn: Triệu chứng -> Nguyên nhân -> Cách kiểm tra -> Cách khắc phục. | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |

---

## Kiến Trúc Tổng Quan Hệ Thống

Hệ thống hoạt động theo mô hình Pipeline phân tán lỏng lẻo (Decoupled Pipeline) qua hàng đợi bất đồng bộ và cơ chế Non-blocking I/O:

```
[ Camera / RTSP / Video Stream ]
                │
                ▼
  [ Ingestion Worker (OpenCV / Decord / FFmpeg) ]
                │
                ▼
      [ YOLO11s Object Detection ] ──(Persons & Vehicles)
                │
                ▼
     [ ByteTrack Multi-Object Tracker ]
        ├── Person Tracks (ID, Tracklet History)
        └── Vehicle Tracks (ID, Tracklet History)
                │
       ┌────────┴─────────────────────────┐
       ▼                                  ▼
[ Person Branch ]                 [ Vehicle Branch ]
 Two-Pass SCRFD Face Detection     YOLO Plate Detection (0.25)
 R2 Homography & Canonical Align   Perspective Warp & Contrast CLAHE
 Quality Filter (Area, Landmarks)  EasyOCR Text Recognition
 AdaFace IR50 (512-d Embedding)    Plate Normalizer & Regex Format
 F2 Candidate Fusion (Top-3)       ECC Median Fusion & Consensus
       │                                  │
       ▼                                  ▼
[ Watchlist Vector Matching ]     [ Vehicle Watchlist Exact Match ]
 Cosine Similarity (>= 0.45)       Normalized License Plate Lookup
       │                                  │
       └────────┬─────────────────────────┘
                │
                ▼
      [ Event Manager Engine ]
        - Track-level Deduplication
        - Episode Coalescing (Cooldown 40 frames)
        - DB Background Worker (Queue -> NullPool Connection)
                │
       ┌────────┴─────────────────────────┐
       ▼                                  ▼
 [ PostgreSQL 17 + pgvector ]     [ Notification Outbox Worker ]
  - Targets & TargetFaces          - Priority Alert Queue
  - Vehicles & PlateEvents         - Rate Limit Cooldown (300s)
  - Episodes & Audit Logs          - SMTP TLS / SSL Dispatcher
  - AlertOutbox (Pending/Sent)     - Exponential Backoff Retries
                │
                ▼
 [ FastAPI Web Server (Port 8000) ]
  - RESTful APIs (/api/v1/...)
  - Binary Frame Stream (/api/frame-stream)
  - Static Single Page Application (HTML5 / Vanilla JS)
```

---

## Thông Tin Các File Mã Nguồn Trọng Tâm

Khi cần đọc và chỉnh sửa code lõi, hãy tham khảo các file tương ứng trong workspace:

* **Entrypoint & CLI Pipeline:**
  * [app.py](../app.py) - Script điều phối chính, xử lý video offline, trích xuất sự kiện và benchmark.
  * [src/runtime/runtime_manager.py](../src/runtime/runtime_manager.py) - Quản lý vòng đời tiến trình camera con (Child Process / Subprocess).
* **Backend Web Server & APIs:**
  * [src/ui/web_server.py](../src/ui/web_server.py) - Ứng dụng FastAPI, khai báo toàn bộ Router, Endpoint quản lý Camera, Watchlist, Events, Alerts và Binary Video Streaming.
* **Mô Hình AI & Xử Lý Thị Giác:**
  * [src/detector/yolo_detector.py](../src/detector/yolo_detector.py) - Module phát hiện người và phương tiện YOLOv11.
  * [src/face/adaptive_pipeline.py](../src/face/adaptive_pipeline.py) - Pipeline nhận diện khuôn mặt hai pha SCRFD + AdaFace.
  * [src/ocr/plate_reader.py](../src/ocr/plate_reader.py) - Pipeline nhận diện biển số xe Plate Detector + EasyOCR.
  * [src/recognition/color_extractor.py](../src/recognition/color_extractor.py) - Trích xuất màu xe theo không gian màu HSV & Lab.
  * [src/tracker/bytetrack_tracker.py](../src/tracker/bytetrack_tracker.py) - Thuật toán theo dõi ByteTrack.
* **Quản Lý Sự Kiện & Lưu Trữ:**
  * [src/events/event_manager.py](../src/events/event_manager.py) - Logic lọc trùng, gom cụm Episode và chuyển giao event.
  * [src/events/db_worker.py](../src/events/db_worker.py) - Worker tiến trình nền ghi sự kiện vào Database qua `NullPool`.
  * [src/notifications/service.py](../src/notifications/service.py) - Quản lý hàng đợi gửi thông báo và cơ chế thử lại (Retry).
  * [src/storage.py](../src/storage.py) - Bộ điều phối lưu trữ ảnh snapshot (Local, Supabase Storage, External).
* **Database Models & Migrations:**
  * [src/db/models.py](../src/db/models.py) - Khai báo các thực thể SQLAlchemy 2.0 (`Target`, `TargetFace`, `Vehicle`, `PlateEvent`, `Episode`, `AlertOutbox`).
  * [src/db/database.py](../src/db/database.py) - Khởi tạo Engine, Async Sessionmaker và cấu hình Pooling.
  * [src/db/migrations/versions/](../src/db/migrations/versions/) - 11 phiên bản Migration Schema từ `0001` đến `0011`.
* **Giao Diện Người Dùng (Frontend SPA):**
  * [src/ui/static/index.html](../src/ui/static/index.html) - Cấu trúc HTML Dashboard & Sidebar điều khiển.
  * [src/ui/static/app.js](../src/ui/static/app.js) - Logic điều hướng DOM, gọi API, bộ lọc sự kiện và quản trị danh sách.
  * [src/ui/static/frame_stream.js](../src/ui/static/frame_stream.js) - Trình đọc luồng nhị phân tốc độ cao với 64-byte Header và vẽ khung hình Canvas.
  * [src/ui/static/alerts.js](../src/ui/static/alerts.js) - Bảng theo dõi trạng thái gửi email thông báo (Pending / Sent / Failed).

---

> [!NOTE]
> Bộ tài liệu này được biên soạn và kiểm chứng trực tiếp từ mã nguồn thực tế của hệ thống. Tất cả các tham số, đường dẫn endpoint, tên bảng cơ sở dữ liệu và thuật toán trong các tài liệu đều phản ánh chính xác cấu trúc hiện hành.
