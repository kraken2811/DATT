# HƯỚNG DẪN QUẢN TRỊ VÀ VẬN HÀNH HỆ THỐNG (ADMIN GUIDE)
**DATT — Hệ thống Giám sát Thị giác Thông minh (AI Vision Monitoring & Security System)**

---

## MỤC LỤC

1. [Tổng quan Triển khai Hệ thống](#1-tổng-quan-triển-khai-hệ-thống)
2. [Cài đặt Môi trường Dự án](#2-cài-đặt-môi-trường-dự-án)
   - 2.1. Cài đặt trên Windows 11 x64
   - 2.2. Cài đặt trên Ubuntu 22.04 LTS
   - 2.3. Cài đặt trên Google Colab
3. [Cấu hình Biến Môi trường (.env)](#3-cấu-hình-biến-môi-trường-env)
4. [Thiết lập Cơ sở Dữ liệu (Database Setup)](#4-thiết-lập-cơ-sở-dữ-liệu-database-setup)
   - 4.1. Khởi chạy PostgreSQL 17 + pgvector bằng Docker Compose
   - 4.2. Cấu hình kết nối Supabase PostgreSQL
   - 4.3. Chế độ phát triển cục bộ với SQLite
5. [Quản lý Database Migrations với Alembic](#5-quản-lý-database-migrations-với-alembic)
6. [Cấu hình Hệ thống Lưu trữ File (Storage Backends)](#6-cấu-hình-hệ-thống-lưu-trữ-file-storage-backends)
   - 6.1. Local Storage
   - 6.2. Supabase Storage (Private Bucket)
   - 6.3. External Storage (S3 / GCS / Azure Blob)
7. [Cài đặt và Chuẩn bị các Mô hình AI (AI Models Setup)](#7-cài-đặt-và-chuẩn-bị-các-mô-hình-ai-ai-models-setup)
8. [Khởi động và Dừng Dịch vụ](#8-khởi-động-và-dừng-dịch-vụ)
   - 8.1. Khởi động Hợp nhất (Unified Runtime - Khuyến nghị)
   - 8.2. Khởi động qua Công cụ Quản trị CLI (`scripts/datt.py`)
   - 8.3. Dừng dịch vụ an toàn (Graceful Shutdown)
9. [Cấu hình Camera (Camera Configuration)](#9-cấu-hình-camera-camera-configuration)
10. [Quản trị Danh sách Theo dõi (Watchlist Management)](#10-quản-trị-danh-sách-theo-dõi-watchlist-management)
    - 10.1. Quản lý Face Targets
    - 10.2. Quản lý Vehicle Watchlist & Batch Import CLI
11. [Quản lý Sự kiện & Tinh chỉnh Worker (Event Tuning)](#11-quản-lý-sự-kiện--tinh-chỉnh-worker-event-tuning)
12. [Cấu hình Kênh Cảnh báo & Gửi Email (Notification / Email)](#12-cấu-hình-kênh-cảnh-báo--gửi-email-notification--email)
13. [Hệ thống Log, Telemetry và Giám sát](#13-hệ-thống-log-telemetry-và-giám-sát)
14. [Quy trình Sao lưu và Phục hồi Dữ liệu (Backup & Recovery)](#14-quy-trình-sao-lưu-và-phục-hồi-dữ-liệu-backup--recovery)
15. [Xử lý Sự cố Dành cho Quản trị viên (Admin Troubleshooting)](#15-xử-lý-sự-cố-dành-cho-quản-trị-viên-admin-troubleshooting)

---

## 1. Tổng quan Triển khai Hệ thống

Kiến trúc DATT được chia làm hai tiến trình/luồng chính khi khởi chạy:
1. **AI Processing Pipeline Engine:** Quản lý vòng đời đọc frame (CameraReader), chạy suy luận YOLO11s, theo dõi ByteTrack, nhận diện khuôn mặt (SCRFD + AdaFace), nhận diện biển số (PlateDetector + EasyOCR), bộ đếm Occupancy và DatabaseWorker lưu trữ sự kiện bất đồng bộ.
2. **FastAPI Web Server:** Cung cấp Web UI Dashboard (`/`), phục vụ tài nguyên tĩnh, cung cấp các REST API cho Camera, Watchlist, Event Center, Alert Center và đóng vai trò proxy luồng MJPEG (`/video_feed`).

---

## 2. Cài đặt Môi trường Dự án

### 2.1. Cài đặt trên Windows 11 x64

#### Bước 1: Cài đặt Python 3.11
- Tải và cài đặt **Python 3.11.9** từ [python.org](https://www.python.org/downloads/release/python-3119/).
- **Tích chọn: "Add python.exe to PATH"**.

#### Bước 2: Clone repository và tạo môi trường ảo (Virtual Environment)
Mở PowerShell tại thư mục dự án:
```powershell
# Di chuyển vào thư mục dự án
cd <thư-mục-dự-án>

# Tạo virtual environment với Python 3.11
python -m venv venv

# Kích hoạt virtual environment
.\venv\Scripts\Activate.ps1
```

#### Bước 3: Cài đặt các thư viện phụ thuộc
```powershell
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

> [!IMPORTANT]
> Nếu hệ thống trang bị GPU NVIDIA, đảm bảo cài đặt đúng phiên bản `torch` và `torchvision` hỗ trợ CUDA:
> ```powershell
> pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
> pip install onnxruntime-gpu
> ```

---

### 2.2. Cài đặt trên Ubuntu 22.04 LTS

```bash
# Cập nhật hệ thống và cài đặt dependencies nền tảng
sudo apt-get update && sudo apt-get install -y \
    python3.11 python3.11-venv python3.11-dev \
    ffmpeg libgl1-mesa-glx libglib2.0-0 \
    build-essential curl git

# Tạo và kích hoạt môi trường ảo
python3.11 -m venv venv
source venv/bin/activate

# Nâng cấp pip và cài đặt requirements
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
```

---

### 2.3. Cài đặt trên Google Colab

Dự án cung cấp script bootstrap chuyên biệt cho Google Colab:
```python
# Chạy trong cell đầu tiên của Colab Notebook
!python scripts/colab_install.py
```
Sau đó cấu hình Colab Secrets (`DATT_DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `DATT_EMAIL_PASSWORD`) và khởi chạy hệ thống.

---

## 3. Cấu hình Biến Môi trường (.env)

Sao chép file `.env.example` thành `.env`:
```powershell
Copy-Item .env.example .env
```

Nội dung mẫu của file `.env` hoàn chỉnh cho môi trường Production:

```dotenv
# ==============================================================================
# 1. DATABASE CONFIGURATION (PostgreSQL + pgvector)
# ==============================================================================
POSTGRES_USER=datt
POSTGRES_DB=datt
POSTGRES_PASSWORD=YourStrongSecurePassword123!
POSTGRES_PORT=5432

# Chuỗi kết nối PostgreSQL chính thức (hoặc Supabase Transaction Pooler URL)
DATT_DATABASE_URL=postgresql://datt:YourStrongSecurePassword123!@127.0.0.1:5432/datt

# Đặt = 1 nếu yêu cầu bắt buộc phải có PostgreSQL và Remote Storage (khuyến nghị cho Production)
DATT_REQUIRE_PERSISTENCE=1

# ==============================================================================
# 2. MEDIA STORAGE CONFIGURATION
# ==============================================================================
# Chọn: 'local', 'supabase', hoặc 'external'
DATT_STORAGE_BACKEND=supabase

# Cấu hình Supabase Storage (nếu chọn backend supabase)
SUPABASE_URL=https://your-project-id.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJh...your-service-role-key...
DATT_STORAGE_BUCKET=datt-media
DATT_STORAGE_CACHE=data/media-cache

# ==============================================================================
# 3. NOTIFICATION & EMAIL ALERTS (SMTP)
# ==============================================================================
DATT_EMAIL_HOST=smtp.gmail.com
DATT_EMAIL_PORT=587
DATT_EMAIL_TLS=starttls
DATT_EMAIL_USERNAME=security-alert@yourcompany.com
DATT_EMAIL_PASSWORD=abcd efgh ijkl mnop
DATT_EMAIL_FROM=DATT Vision Security <security-alert@yourcompany.com>
DATT_EMAIL_TO=admin@yourcompany.com,supervisor@yourcompany.com

# Thời gian chặn cảnh báo trùng lặp (giây) - mặc định 300s (5 phút)
DATT_NOTIFICATION_COOLDOWN_SECONDS=300
DATT_NOTIFICATION_MAX_RETRIES=3
DATT_NOTIFICATION_RETRY_SECONDS=30

# ==============================================================================
# 4. YOUTUBE INGESTION & COOKIES (Tùy chọn)
# ==============================================================================
# Đường dẫn file cookies.txt chuẩn Netscape nếu YouTube yêu cầu xác minh bot
# YTDLP_COOKIE_FILE=configs/cookies.txt
```

---

## 4. Thiết lập Cơ sở Dữ liệu (Database Setup)

### 4.1. Khởi chạy PostgreSQL 17 + pgvector bằng Docker Compose

Hệ thống cung cấp sẵn cấu hình Docker trong [docker-compose.yml](../docker-compose.yml):
```bash
# Khởi chạy dịch vụ PostgreSQL có sẵn pgvector
docker compose up -d postgres

# Kiểm tra trạng thái container hoạt động
docker compose ps
```
Khi container chạy, cổng `5432` trên máy chủ sẽ được ánh xạ trực tiếp vào database `datt`.

---

### 4.2. Cấu hình kết nối Supabase PostgreSQL

Nếu sử dụng Supabase Managed PostgreSQL:
1. Vào Supabase Dashboard -> **Project Settings** -> **Database**.
2. Tìm mục **Connection parameters** -> Chọn **Session mode** (Port `5432`) hoặc **Transaction mode** (Port `6543`).
3. Điền chuỗi kết nối vào `DATT_DATABASE_URL` trong file `.env`.
4. *Lưu ý kỹ thuật:* Mã nguồn [src/db/database.py](../src/db/database.py#L44-L45) tự động thiết lập `poolclass=NullPool` khi phát hiện backend PostgreSQL, đảm bảo mỗi transaction được đóng kết nối ngay lập tức, không gây cạn kiệt connection pool của Supabase.

---

### 4.3. Chế độ phát triển cục bộ với SQLite

Nếu chạy ở môi trường phát triển cục bộ không có PostgreSQL:
- Bỏ trống biến `DATT_DATABASE_URL` trong `.env`.
- Đảm bảo `DATT_REQUIRE_PERSISTENCE=0` (hoặc comment dòng này).
- Hệ thống sẽ tự động tạo và sử dụng file cơ sở dữ liệu `datt.db` tại thư mục gốc.

---

## 5. Quản lý Database Migrations với Alembic

Hệ thống quản lý lược đồ dữ liệu qua 11 bản migration chính thức trong [src/db/migrations/versions/](../src/db/migrations/versions/):

| Phiên bản | Tên Revision | Mục đích |
|---|---|---|
| `0001` | `0001_initial_schema` | Tạo các bảng nền tảng: `cameras`, `video_sources`, `targets`, `detection_events`, `vehicle_events`, `plate_events`, `face_events` |
| `0002` | `0002_zones` | Tạo bảng quản lý vùng đếm đa giác `zones` |
| `0003` | `0003_pgvector_embeddings` | Kích hoạt extension `vector` và bảng `target_embeddings` (Vector 512 chiều) |
| `0004` | `0004_vehicle_passages_and_business_events` | Tạo bảng `vehicle_passages` và `business_events` theo dõi phiên lưu thông |
| `0005` | `0005_video_sources` | Mở rộng siêu dữ liệu cho bảng `video_sources` (fps, width, height, metadata) |
| `0006` | `0006_vehicle_event_color_and_image` | Bổ sung cột màu sắc và đường dẫn ảnh vào `vehicle_events` |
| `0007` | `0007_source_traceability` | Bổ sung `video_source_id` để truy vết nguồn gốc video trên tất cả các bảng sự kiện |
| `0008` | `0008_notifications` | Tạo bảng `notifications` quản lý outbox cảnh báo email và trạng thái delivery |
| `0009` | `0009_vehicle_watchlists` | Tạo bảng `vehicle_watchlists` và `vehicle_watchlist_results` |
| `0010` | `0010_camera_vehicle_notifications` | Thêm quan hệ camera và chỉ mục kiểm soát cooldown cho xe |
| `0011` | `0011_vehicle_watchlist_color` | Thêm trường màu xe `vehicle_color` vào bảng `vehicle_watchlists` |

### Lệnh thực hiện Migration:
```powershell
# Chạy migration lên phiên bản mới nhất
alembic -c src/db/alembic.ini upgrade head

# Hoặc sử dụng CLI tiện ích của DATT
python scripts/datt.py migrate
```

### Lệnh kiểm tra tính toàn vẹn cơ sở dữ liệu:
```powershell
python scripts/datt.py db-check
```

---

## 6. Cấu hình Hệ thống Lưu trữ File (Storage Backends)

### 6.1. Local Storage
- Đặt `DATT_STORAGE_BACKEND=local`.
- File ảnh chụp sự kiện được lưu trữ tự động vào `data/events/`, ảnh mẫu mục tiêu lưu vào `data/uploads/targets/`, video upload lưu vào `data/uploads/videos/`.

### 6.2. Supabase Storage
1. Tạo một Private Bucket tên là `datt-media` trên Supabase Storage.
2. Thiết lập các biến môi trường:
   ```dotenv
   DATT_STORAGE_BACKEND=supabase
   SUPABASE_URL=https://<your-project>.supabase.co
   SUPABASE_SERVICE_ROLE_KEY=<your-secret-service-role-key>
   DATT_STORAGE_BUCKET=datt-media
   ```
3. Kiểm tra kết nối lưu trữ:
   ```powershell
   python scripts/datt.py storage-check
   ```

---

## 7. Cài đặt và Chuẩn bị các Mô hình AI (AI Models Setup)

Các file trọng số mô hình AI cần được đặt trong thư mục `models/`:

```text
models/
├── yolo11s.pt                      # Mô hình phát hiện người và xe (Ultralytics)
├── yolov8n-license-plate.pt        # Mô hình phát hiện bounding box biển số xe
├── face/
│   └── adaface_ir50_ms1mv2.onnx    # Mô hình trích xuất đặc trưng khuôn mặt (AdaFace 512-d)
└── ocr/
    └── en_PP-OCRv4_rec_mobile.onnx # Mô hình OCR dự phòng (PaddleOCR line recognizer)
```

### Lệnh tải tự động mô hình thiếu:
```powershell
python scripts/datt.py models
```
*Lưu ý:* Mô hình nhận diện khuôn mặt SCRFD và MobileFaceNet của InsightFace (`buffalo_s`) sẽ được tự động tải về thư mục `~/.insightface/models/buffalo_s/` trong lần đầu tiên khởi chạy.

---

## 8. Khởi động và Dừng Dịch vụ

### 8.1. Khởi động Hợp nhất (Unified Runtime - Khuyến nghị)

Lệnh tiêu chuẩn khởi động toàn bộ hệ thống gồm cả AI Pipeline và Web UI Dashboard trong 1 câu lệnh duy nhất:
```powershell
# Khởi động với camera mặc định (Port 8501)
python src/main.py

# Khởi động với camera chỉ định cụ thể từ configs/cameras.yaml
python src/main.py --camera camera_01 --port 8501

# Khởi động với độ phân giải suy luận YOLO tùy chỉnh (640, 768 hoặc 960)
python src/main.py --img-size 960 --port 8501

# Khởi động chế độ Headless (chỉ chạy AI xử lý và MJPEG stream, không chạy Web UI)
python src/main.py --no-ui --ai-port 8000
```

Các tham số dòng lệnh của `src/main.py`:
- `--camera <ID>`: ID camera ban đầu (ví dụ: `camera_01`, `camera_02`).
- `--port <PORT>`: Cổng phục vụ Web UI Dashboard (Mặc định: `8501`).
- `--host <IP>`: Địa chỉ mạng lắng nghe của Web UI (Mặc định: `0.0.0.0`).
- `--ai-port <PORT>`: Cổng phục vụ luồng stream MJPEG nội bộ (Mặc định: `8000`).
- `--ai-host <IP>`: Địa chỉ lắng nghe của AI stream (Mặc định: `127.0.0.1`).
- `--img-size <SIZE>`: Kích thước ảnh inference cho YOLO (`640`, `768`, hoặc `960`).
- `--max-frames <N>`: Dừng sau khi xử lý N khung hình (dành cho benchmark tự động).

---

### 8.2. Khởi động qua Công cụ Quản trị CLI (`scripts/datt.py`)

Công cụ quản lý tiến trình ngầm (Daemon / Supervisor):
```powershell
# Kiểm tra tình trạng sức khỏe toàn diện hệ thống (Doctor)
python scripts/datt.py doctor

# Khởi động hệ thống chạy ngầm ở chế độ GPU
python scripts/datt.py start --mode gpu --port 8501

# Kiểm tra trạng thái tiến trình (PID, Port, Uptime, Memory)
python scripts/datt.py status

# Khởi động lại dịch vụ
python scripts/datt.py restart

# Dừng dịch vụ đang chạy ngầm
python scripts/datt.py stop
```

---

### 8.3. Dừng dịch vụ an toàn (Graceful Shutdown)

- **Khi chạy trực tiếp trên Terminal:** Nhấn tổ hợp phím `Ctrl + C`.
- **Trình tự tắt tài nguyên của hệ thống:**
  1. Gửi tín hiệu dừng luồng `stop_event` đến vòng lặp AI Pipeline.
  2. Dừng giải mã luồng camera và thu hồi tiến trình đọc FFmpeg.
  3. Xả (drain) hàng đợi tác vụ của Database Worker và commit các sự kiện còn dở dang vào PostgreSQL.
  4. Dừng tiến trình gửi Email Worker (`NotificationService.stop()`).
  5. Giải phóng kết nối cơ sở dữ liệu (`db.dispose()`).
  6. Tắt máy chủ Uvicorn và máy chủ MJPEG stream.

---

## 9. Cấu hình Camera (Camera Configuration)

### 9.1. Cấu hình tĩnh qua `configs/cameras.yaml`
Dùng để nạp danh mục camera cố định ban đầu:
```yaml
cameras:
  camera_01:
    name: "Cổng Chính - Luồng Thử Nghiệm"
    type: local
    url: "scratch/audit_fixture_200.mp4"
    width: 1280
    height: 720
    description: "Camera thử nghiệm 720p cục bộ"

  camera_02:
    name: "YouTube Live - Tokyo Street"
    type: youtube
    url: "https://youtu.be/Cp4RRAEgpeU"
    width: 1280
    height: 720
    description: "Luồng trực tiếp ngã tư người đi bộ"

  camera_03:
    name: "Camera RTSP Tầng Hầm"
    type: rtsp
    url: "rtsp://admin:Pass123@192.168.1.100:554/live"
    width: 1280
    height: 720
    description: "Camera giám sát bãi đỗ xe"
```

### 9.2. Cấu hình động qua REST API & Web UI
Toàn bộ camera tạo qua giao diện Web được lưu trữ trong bảng `cameras` của cơ sở dữ liệu. Quản trị viên có thể thao tác qua API:
- `GET /api/cameras`: Danh sách camera.
- `POST /api/cameras`: Tạo camera mới.
- `PATCH /api/cameras/{id}`: Sửa cấu hình camera.
- `DELETE /api/cameras/{id}`: Xóa camera.
- `POST /api/cameras/{id}/test`: Kiểm tra tính khả dụng của luồng camera.

---

## 10. Quản trị Danh sách Theo dõi (Watchlist Management)

### 10.1. Quản lý Face Targets
- Các mục tiêu khuôn mặt được quản lý trong bảng `targets` và `target_embeddings`.
- Mỗi mục tiêu có thể bật hoặc tắt theo dõi qua endpoint:
  - `POST /api/targets/{id}/select` với tham số `selected=true|false`.
- Xóa mục tiêu: `DELETE /api/targets/{id}` (tự động xóa khóa ngoại liên quan trong `target_embeddings`).

### 10.2. Quản lý Vehicle Watchlist & Batch Import CLI
Dự án cung cấp script tiện ích [src/watchlists/import_vehicles.py](../src/watchlists/import_vehicles.py) cho phép nạp danh sách biển số xe hàng loạt từ file JSON hoặc CSV:

```powershell
# Nạp danh sách xe hàng loạt từ file JSON
python src/watchlists/import_vehicles.py --file data/vehicles_import.json
```

Cấu trúc file JSON import mẫu:
```json
[
  {
    "plate_number": "29A-123.45",
    "vehicle_type": "car",
    "vehicle_color": "red",
    "display_name": "Xe Giám Đốc",
    "owner_info": "Nguyễn Văn B - 0987654321",
    "notes": "Ưu tiên ra vào cổng chính"
  },
  {
    "plate_number": "51K-888.99",
    "vehicle_type": "truck",
    "vehicle_color": "white",
    "display_name": "Xe Tải Giao Hàng",
    "owner_info": "Công ty Vận tải ABC",
    "notes": "Kiểm tra thùng hàng khi vào"
  }
]
```

---

## 11. Quản lý Sự kiện & Tinh chỉnh Worker (Event Tuning)

Các thông số vận hành của `EventManager` và `DatabaseWorker` được định nghĩa tập trung trong mã nguồn:

- **Hàng đợi lưu trữ (`DatabaseWorker`):**
  - `max_queue_size = 1000`: Dung lượng tối đa của hàng đợi lưu sự kiện trước khi kích hoạt cơ chế loại bỏ tác vụ mức ưu tiên thấp.
  - `batch_size = 50`: Số lượng bản ghi được commit gộp trong một transaction.
- **Ngưỡng sự kiện quá tải (`src/events/policy.py`):**
  - `PEOPLE_THRESHOLD = 40`: Kích hoạt sự kiện `CROWD_THRESHOLD` khi số người vượt quá 40.
  - `PEOPLE_DURATION_THRESHOLD = 180.0`: Thời gian duy trì liên tục tối thiểu (180 giây / 3 phút) trước khi ghi nhận sự kiện đông người.
  - `VEHICLE_THRESHOLD = 40`: Kích hoạt sự kiện ùn tắc `VEHICLE_CONGESTION` khi số xe vượt quá 40 xe.
- **Khoảng thời gian lưu ảnh toàn cảnh:**
  - `SNAPSHOT_INTERVAL_SECONDS = 60.0`: Tần suất tối thiểu giữa các lần lưu snapshot toàn cảnh để tránh đầy ổ đĩa.

---

## 12. Cấu hình Kênh Cảnh báo & Gửi Email (Notification / Email)

### Nguyên lý hoạt động:
1. Khi có sự kiện khớp khuôn mặt (`FACE_WATCHLIST_MATCH`) hoặc khớp biển số (`VEHICLE_WATCHLIST_MATCH`), bản ghi được thêm vào bảng `notifications` với trạng thái `pending`.
2. Tiến trình `NotificationEmailWorker` quét bảng định kỳ mỗi 1 giây (sử dụng truy vấn `SELECT ... FOR UPDATE SKIP LOCKED` để đảm bảo an toàn đa luồng/đa worker).
3. Gửi email có đính kèm ảnh bằng chứng (`evidence.jpg`).
4. Nếu gửi thành công: cập nhật `status = 'sent'`, lưu `sent_at = NOW()`.
5. Nếu thất bại do lỗi mạng/timeout: cập nhật `status = 'failed'`, tăng `retry_count` và tính thời điểm thử lại kế tiếp theo công thức lũy thừa:
   $$\text{next\_attempt\_at} = \text{now} + \min(3600, \text{retry\_seconds} \times 2^{\text{retry\_count}})$$
6. Nếu vượt quá số lần thử lại tối đa (`max_retries = 3`), thông báo sẽ giữ nguyên trạng thái `failed`.

---

## 13. Hệ thống Log, Telemetry và Giám sát

### File nhật ký vận hành:
- Khi chạy qua CLI (`scripts/datt.py start`), toàn bộ log hệ thống được ghi vào file `.datt-runtime/backend.log`.
- Khi chạy trực tiếp qua `python src/main.py`, log được xuất ra Standard Output (Console).

### Giám sát thời gian thực qua Telemetry:
Truy cập endpoint `http://<IP>:8501/telemetry` hoặc `http://<IP>:8501/api/telemetry` để lấy dữ liệu JSON đo lường hiệu năng:
```json
{
  "camera_id": "camera_01",
  "camera_name": "Tokyo Street",
  "status": "RUNNING",
  "people_count": 14,
  "car_count": 5,
  "stream_fps": 29.8,
  "processing_fps": 30.1,
  "yolo_latency_ms": 16.4,
  "pipeline_latency_ms": 28.2,
  "device": "CUDA",
  "gpu_name": "NVIDIA GeForce RTX 4070 Laptop GPU",
  "vram_mb": 1420.5
}
```

### 13.3. Giám sát & Quản trị Giao diện Web Dashboard (Enterprise UI Management)
Hệ thống giao diện Web người dùng (Web UI) được phục vụ trực tiếp qua FastAPI (`src/ui/web_server.py`) với các đặc tính vận hành dành cho quản trị viên:
1. **Kiến trúc Tối giản & Tối ưu Hiệu năng:**
   - Hoàn toàn xây dựng bằng HTML5, CSS thuần và JavaScript Vanilla chuẩn hiện đại.
   - Không phụ thuộc framework cồng kềnh (không React, không Vue, không Tailwind runtime build), giúp tải trang gần như tức thì (< 50ms) ngay cả trên mạng băng thông thấp hoặc máy trạm cấu hình thấp.
2. **Phân tách Chế độ Xem Stream & Quản lý:**
   - **Trang Quản lý (Camera Management, Event Center, Watchlist):** Hiển thị Sidebar dọc màu trắng cố định bên trái, thuận tiện cho việc duyệt danh mục và quản trị.
   - **Chế độ Xem Stream Chuyên dụng (Camera Stream View):** Tự động ẩn Sidebar, thanh điều hướng tối giản, căn giữa video và **loại bỏ hoàn toàn Event Feed bên dưới** nhằm tối ưu hóa diện tích cho phòng trực ban hoặc màn hình TV Wall lớn.
   - **Giám sát Toàn màn hình (Fullscreen Monitoring):** Tích hợp thanh xám hiển thị số liệu người và xe thực tế từ ByteTrack (`data.people_count` và `data.car_count`).
3. **Cảnh báo Toàn cục (Global Toast Notification):**
   - Client Web định kỳ thăm dò (poll) endpoint `/api/alerts` mỗi 6 giây để phát hiện bản ghi thông báo mới từ hàng đợi transactional outbox và hiển thị Toast bật lên ở góc trên bên phải trong 5 giây.
   - Khi ở chế độ Fullscreen, toast container tự động được reparent vào container toàn màn hình để không bị trình duyệt che khuất.
4. **Quản lý Tùy biến Màu sắc (Theme Accent Color):**
   - Tùy chọn 5 màu chủ đạo (Blue `#2563EB`, Green `#059669`, Purple `#7C3AED`, Orange `#EA580C`, Red `#DC2626`) được lưu ở phía client thông qua `localStorage.setItem('datt_accent_color', color)`.
   - Quản trị viên có thể đặt trước màu mặc định cho toàn bộ máy trạm bằng cách điều chỉnh thuộc tính `data-theme` trên thẻ `<html>` trong file [index.html](../src/ui/static/index.html).
```

---

## 14. Quy trình Sao lưu và Phục hồi Dữ liệu (Backup & Recovery)

### 14.1. Sao lưu Cơ sở dữ liệu PostgreSQL
```bash
# Thực hiện sao lưu toàn bộ dữ liệu hệ thống ra file dump
pg_dump -h 127.0.0.1 -U datt -d datt -F c -b -v -f "backup_datt_$(date +%Y%m%d_%H%M%S).dump"
```

### 14.2. Phục hồi Cơ sở dữ liệu PostgreSQL
```bash
# Phục hồi dữ liệu từ file dump
pg_restore -h 127.0.0.1 -U datt -d datt -v "backup_datt_20261005_150000.dump"
```

### 14.3. Sao lưu Thư mục Media (Ảnh bằng chứng và khuôn mặt)
Thư mục `data/events/` và `data/uploads/` chứa toàn bộ ảnh chụp sự kiện:
```bash
tar -czvf "backup_media_$(date +%Y%m%d).tar.gz" data/events data/uploads
```

---

## 15. Xử lý Sự cố Dành cho Quản trị viên (Admin Troubleshooting)

1. **Lỗi cổng mạng bị chiếm dụng (`Address already in use` trên Port 8000 hoặc 8501):**
   - *Kiểm tra:*
     ```powershell
     Get-NetTCPConnection -LocalPort 8501,8000
     ```
   - *Khắc phục:* Dừng tiến trình cũ qua PID hiển thị, hoặc chạy lệnh:
     ```powershell
     python scripts/datt.py stop
     ```
2. **Lỗi `pgvector_missing` khi chạy `python scripts/datt.py db-check`:**
   - Database PostgreSQL chưa cài đặt extension `vector`. Kết nối vào PostgreSQL bằng quyền superuser và chạy lệnh SQL:
     ```sql
     CREATE EXTENSION vector;
     ```
3. **Lỗi `migration_head_mismatch`:**
   - Cơ sở dữ liệu chưa được cập nhật phiên bản mới nhất của Alembic. Chạy lệnh:
     ```powershell
     alembic -c src/db/alembic.ini upgrade head
     ```
4. **Tràn bộ nhớ đệm GPU (CUDA Out of Memory - OOM):**
   - Giảm độ phân giải suy luận của YOLO từ 960 xuống 640 bằng cờ:
     ```powershell
     python src/main.py --img-size 640
     ```
