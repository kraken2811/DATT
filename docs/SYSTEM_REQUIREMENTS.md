# ĐIỀU KIỆN SỬ DỤNG VÀ YÊU CẦU HỆ THỐNG (SYSTEM REQUIREMENTS)
**DATT — Hệ thống Giám sát Thị giác Thông minh (AI Vision Monitoring & Security System)**

---

Tài liệu này xác định các tiêu chuẩn kỹ thuật, điều kiện môi trường, cấu hình phần cứng, phần mềm và các biến môi trường cần thiết để triển khai và vận hành hệ thống DATT ổn định, an toàn và đạt hiệu năng tối ưu.

Mọi thông số kỹ thuật được đối chiếu trực tiếp từ mã nguồn thực tế của dự án (`requirements.txt`, `config.py`, `docker-compose.yml`, `src/storage.py`, `src/face/adaptive_pipeline.py`, `src/ocr/plate_reader.py`).

---

## 1. Yêu cầu Phần cứng (Hardware Requirements)

Hệ thống DATT thực hiện các tác vụ tính toán thị giác máy tính nặng (YOLO11s Object Detection, ByteTrack Tracking, Face Embedding AdaFace, License Plate OCR). Cấu hình phần cứng được chia làm hai mức:

| Thành phần | CẤU HÌNH TỐI THIỂU (MINIMUM) | CẤU HÌNH KHUYẾN NGHỊ (RECOMMENDED) |
|---|---|---|
| **CPU** | Intel Core i5 thế hệ 10 / AMD Ryzen 5 (Tối thiểu 4 nhân, 8 luồng, xung nhịp >= 2.5 GHz) | Intel Core Ultra 7 155H / Intel Core i7 thế hệ 13+ / AMD Ryzen 7 (8 nhân, 16 luồng trở lên) |
| **GPU / Bộ tăng tốc** | Chạy chế độ CPU Fallback (suy luận CPU với OpenVINO / ONNX Runtime CPU) | **NVIDIA GPU có hỗ trợ CUDA** (Tối thiểu 6GB VRAM như RTX 3060 / T4 trên Google Colab; Khuyến nghị RTX 4060, RTX 4070, A100 hoặc GPU Intel Arc Graphics với DirectML) |
| **VRAM GPU** | 4 GB VRAM (chạy mô hình YOLO ở độ phân giải 640x640) | **>= 8 GB VRAM** (để giữ persistent model resident cho YOLO 960x960 FP16, AdaFace IR50 và EasyOCR GPU) |
| **Bộ nhớ RAM** | 8 GB RAM DDR4 | **16 GB – 32 GB RAM DDR5** (hạn chế tràn bộ nhớ khi đệm frame video và lưu trữ cache cục bộ) |
| **Ổ đĩa lưu trữ (Disk)** | Tối thiểu 20 GB dung lượng trống (HDD hoặc SSD SATA) | **>= 100 GB SSD NVMe** (tốc độ đọc/ghi cao phục vụ lưu trữ snapshot bằng chứng, SQLite/PostgreSQL data và video cache) |
| **Băng thông mạng** | 10 Mbps (cho 1 luồng video 720p 15 FPS) | **>= 100 Mbps LAN / Internet cáp quang** (đảm bảo độ trễ thấp khi stream RTSP/HLS từ xa) |

---

## 2. Yêu cầu Phần mềm (Software Requirements)

Hệ thống đã được kiểm thử và hỗ trợ trên các nền tảng hệ điều hành sau:
- **Windows:** Windows 11 x64 (Build 22H2 trở lên) hoặc Windows 10 x64.
- **Linux:** Ubuntu 22.04 LTS / Debian 12 x64.
- **Cloud / Sandbox:** Google Colab (Môi trường runtime Linux x64 với GPU T4/A100).
- **Trình duyệt Web (Client):** Google Chrome >= 115, Microsoft Edge >= 115, Mozilla Firefox >= 115, Safari >= 16. Yêu cầu hỗ trợ HTML5 Canvas, Fetch API, ReadableStream và Blob.

---

## 3. Phiên bản Python (Python Version)

- **Phiên bản yêu cầu:** **Python 3.11.x (Chính xác 3.11.0 – 3.11.9)**.
- *Lý do kỹ thuật:* Thư viện `numpy<2.0.0` được ghim cứng trong `requirements.txt` nhằm duy trì tính tương thích nhị phân C-API với `insightface>=0.7.3` và `opencv-contrib-python`. Python 3.12+ có thể gặp lỗi xung đột C-extension khi build InsightFace / NumPy.

---

## 4. Phiên bản Node.js (Node Version)

- **Trạng thái trong dự án:**
  - Phần giao diện người dùng chính (Frontend Web UI) được xây dựng hoàn toàn bằng **Vanilla HTML5, CSS3 và JavaScript chuẩn (ES6+)**, không yêu cầu build tool (không cần Webpack, Vite hay NPM build khi chạy ứng dụng production).
  - Đối với các bài kiểm thử trình duyệt tự động (Automated Browser Test như `tests/test_frame_stream.cjs`, `tests/test_alerts_browser.cjs`), yêu cầu **Node.js >= 18.x** nếu người phát triển muốn chạy test suite Javascript.

---

## 5. Phiên bản PostgreSQL (PostgreSQL Version)

- **Phiên bản yêu cầu:** **PostgreSQL 17** (hoặc tối thiểu PostgreSQL 15+).
- Hệ thống cung cấp sẵn file `docker-compose.yml` sử dụng image chuẩn:
  ```yaml
  image: pgvector/pgvector:pg17
  ```
- Trình điều khiển kết nối: `psycopg[binary]>=3.2.0` (Psycopg phiên bản 3 hiện đại, hỗ trợ native async và UUID).

---

## 6. Tiện ích mở rộng pgvector (pgvector Extension)

- **Bắt buộc đối với triển khai có lưu trữ bền vững (Persistence Deployment):**
  - Tiện ích mở rộng `pgvector` phiên bản `>= 0.3.6`.
  - Cần kích hoạt trên database:
    ```sql
    CREATE EXTENSION IF NOT EXISTS vector;
    ```
  - Bảng `target_embeddings` lưu trữ vector khuôn mặt 512 chiều với kiểu dữ liệu `vector(512)`.
- *Trường hợp không dùng pgvector:* Trong môi trường phát triển cục bộ (Local Development) không bật cờ `DATT_REQUIRE_PERSISTENCE=1`, hệ thống tự động fallback sang SQLite (`datt.db`) và lưu trữ embedding dưới dạng JSON mảng số thực.

---

## 7. Yêu cầu GPU / CUDA (GPU / CUDA Requirements)

Khi chạy trên hệ thống có GPU NVIDIA:
- **NVIDIA CUDA Toolkit:** Phiên bản `11.8` hoặc `12.1+`.
- **NVIDIA Driver:** Tối thiểu phiên bản `525.xx` (khuyến nghị `550.xx` trở lên).
- **PyTorch (torch):** Biên dịch với CUDA support (Ví dụ: `torch>=2.2.0+cu121`).
- **ONNX Runtime:** Cài đặt `onnxruntime-gpu>=1.18.0` để kích hoạt `CUDAExecutionProvider`.
- **Fallback CPU:** Nếu không có GPU hoặc CUDA bị lỗi driver, hệ thống sẽ tự động chuyển sang chạy CPU:
  - YOLO: chuyển `device="cpu"`.
  - Face SCRFD / MobileFaceNet: chạy `CPUExecutionProvider`.
  - EasyOCR: tự động chuyển `gpu=False`.

---

## 8. Dung lượng RAM (Memory Requirements)

- **Tối thiểu:** 8 GB RAM khả dụng.
- **Khuyến nghị:** 16 GB – 32 GB RAM.
- *Mức tiêu thụ tài nguyên thực tế:*
  - Process AI Pipeline: ~1.5 GB – 3.0 GB RAM (tùy thuộc độ phân giải frame và cache).
  - VRAM GPU: ~1.2 GB – 2.5 GB VRAM cho YOLO11s (960x960 FP16) + ~800 MB cho EasyOCR và InsightFace.

---

## 9. Dung lượng Ổ đĩa (Disk Requirements)

- **Mã nguồn và môi trường ảo (venv):** ~4 GB – 6 GB.
- **Trọng số các mô hình AI (`models/`):**
  - `yolo11s.pt` / `yolo11s_960.onnx`: ~38 MB.
  - `yolov8n-license-plate.pt`: ~6.2 MB.
  - `adaface_ir50_ms1mv2.onnx`: ~174 MB.
  - `en_PP-OCRv4_rec_mobile.onnx`: ~7.6 MB.
  - InsightFace `buffalo_s` cache: ~200 MB.
- **Không gian lưu trữ sự kiện và cache video (`data/`):** Tối thiểu 10 GB – 50 GB tùy thuộc vào lưu lượng xe và tần suất ghi nhận sự kiện.

---

## 10. Yêu cầu Mạng (Network Requirements)

- **Băng thông kết nối:**
  - Luồng RTSP/HLS 1080p: yêu cầu băng thông tối thiểu 6-8 Mbps ổn định.
  - Luồng RTSP/HLS 720p: yêu cầu băng thông tối thiểu 2-4 Mbps.
- **Giao thức mạng:**
  - Hỗ trợ TCP và UDP cho RTSP.
  - Cổng mở nội bộ: Cổng `8000` (nội bộ AI stream) và Cổng `8501` (FastAPI Web UI).

---

## 11. Yêu cầu Nguồn Camera (Camera Requirements)

Hệ thống tương thích với các nguồn sau:
1. **Camera IP hỗ trợ giao thức RTSP:** Định dạng URL `rtsp://<user>:<password>@<ip>:<port>/<stream_path>`.
2. **Camera phát luồng HLS:** Định dạng file danh sách phát `.m3u8` (`http://...` hoặc `https://...`).
3. **Luồng YouTube Live:** Đường dẫn video trực tiếp công khai trên YouTube.
4. **Camera giao thông công cộng (Public CCTV):** Seattle SDOT hoặc Caltrans (qua dịch vụ REST và image snapshot).
5. **File Video ghi hình sẵn:** Định dạng container `.mp4`, `.avi`, `.mkv` với chuẩn nén H.264.

---

## 12. Điều kiện về Luồng Video (Stream Requirements)

- **Độ phân giải chuẩn hóa khuyến nghị:** **1280x720 (720p)** hoặc **1920x1080 (1080p)**.
- **Tỷ lệ khung hình (Aspect Ratio):** Chuẩn 16:9.
- **Tốc độ khung hình (Frame Rate):** 15 FPS đến 30 FPS.
- **Chuẩn mã hóa Video (Codec):** H.264 (AVC) khuyến nghị để FFmpeg giải mã phần cứng nhanh nhất. H.265 (HEVC) được hỗ trợ nếu FFmpeg có codec tương ứng.

---

## 13. Điều kiện về Ảnh Chân dung Đăng ký (Image Requirements)

Khi đăng ký khuôn mặt vào Watchlist (`/api/register_target`):
- **Định dạng file:** JPEG (`.jpg`, `.jpeg`), PNG (`.png`), WEBP (`.webp`).
- **Kích thước file:** Tối đa **10 MB** (vượt quá sẽ bị chặn với mã lỗi `HTTP 413: EVIDENCE_TOO_LARGE`).
- **Kích thước vùng khuôn mặt:** Chiều rộng tối thiểu của khuôn mặt trong ảnh nên đạt từ **80x80 pixel** trở lên.
- **Ánh sáng:** Đủ sáng, không bị cháy sáng (overexposed) hoặc tối đen (underexposed).
- **Góc chụp:** Góc nghiêng đầu (Yaw / Pitch) không quá 30 độ; không bị che mắt bởi kính râm hoặc khẩu trang.

---

## 14. Điều kiện Nhận diện Khuôn mặt (Face Recognition Conditions)

Dựa trên thuật toán thích ứng đa tầng trong mã nguồn (`src/face/adaptive_pipeline.py`):
- **Độ đối xứng chính diện (Frontality):** Điểm đối xứng phải đạt `>= 0.20` (tính từ khoảng cách giữa mũi và hai mắt).
- **Khoảng cách hai mắt (Eye Distance):** Tối thiểu `>= 4.0 pixel`.
- **Kích thước chiều rộng khuôn mặt (Face Width):**
  - Chuẩn tối ưu: từ `32.0` đến `44.0` pixel trong hệ thống camera tầm cao.
  - Ngưỡng méo hình học góc cao (Overhead Distortion Score): `<= 40.0`.
- **R2 Homography Rectification:** Tự động nắn chỉnh phối cảnh khuôn mặt với tỷ lệ chuẩn `CANONICAL_ASPECT = 1.1544` và trọng số `HOMOGRAPHY_ALPHA = 0.50`.
- **Ngưỡng so khớp tương đồng (Cosine Similarity Threshold):** Mặc định là **0.45** (Cấu hình linh hoạt từ `0.30` đến `0.85` cho từng đối tượng).
- **Bộ đệm hợp nhất đa khung hình (Temporal F2 Candidate Fusion):** Cần ít nhất 3 khung hình ứng viên độc lập, cách nhau tối thiểu 2 khung hình để tính vector đại diện tổng hợp.

---

## 15. Điều kiện Nhận diện Biển số xe (OCR Conditions)

Dựa trên thuật toán trong `src/ocr/plate_reader.py` và `src/ocr/plate_tracker.py`:
- **Định dạng biển số hợp lệ (`is_valid_plate_format`):**
  - Chuẩn biển số dân sự Việt Nam: Mã tỉnh (2 chữ số: 11, 12, 14-43, 47-99) + Ký hiệu sê-ri (1 chữ cái hoặc 1 chữ cái + 1 số/chữ) + 4 hoặc 5 chữ số thứ tự (khác 0000).
- **Ngưỡng phát hiện hộp biển số (Plate Detection Confidence):** `>= 0.25`.
- **Ngưỡng tin cậy OCR (OCR Confidence Floor):** `>= 0.35`.
- **Kích thước xe tối thiểu để kích hoạt OCR:** Chiều rộng `>= 30 pixel` và Chiều cao `>= 30 pixel`.
- **Quy tắc đồng thuận đa khung hình (Multi-Frame Consensus):**
  - Cần tối thiểu `>= 2` lần quan sát (khuyến nghị 3 lần) đọc ra cùng một chuỗi ký tự biển số chuẩn hóa.
  - Tỷ lệ đồng thuận trong lịch sử 10 khung hình gần nhất: `>= 75%` (`PLATE_CONSENSUS_RATIO = 0.75`).
  - Biển số chỉ chuyển sang trạng thái `CONFIRMED` khi đạt đủ các tiêu chí trên.

---

## 16. Yêu cầu Cơ sở dữ liệu (Database Requirements)

- **Môi trường Production / Persistent:**
  - Bắt buộc dùng PostgreSQL 17 kèm pgvector.
  - Cung cấp chuỗi kết nối qua biến môi trường `DATT_DATABASE_URL`.
  - Phải chạy đầy đủ 11 bản migration của Alembic (`alembic upgrade head`).
  - Hệ thống sử dụng cơ chế `NullPool` khi kết nối PostgreSQL để tương thích an toàn với Session Pooler của Supabase / PgBouncer mà không làm cạn kiệt connection pool.
- **Môi trường Test / Development Cục bộ:**
  - Cho phép dùng SQLite (`sqlite:///datt.db`).
  - Mã nguồn tự động bật `PRAGMA foreign_keys=ON` và `PRAGMA busy_timeout=5000`.

---

## 17. Yêu cầu Lưu trữ File & Ảnh (Storage Requirements)

Hệ thống hỗ trợ 3 backend lưu trữ (`DATT_STORAGE_BACKEND`):
1. **`local` (Mặc định):**
   - Lưu trữ trực tiếp trên ổ đĩa máy chủ dưới thư mục `data/uploads/videos/`, `data/uploads/targets/`, `data/events/`.
   - *Giới hạn:* File sẽ bị mất nếu container hoặc instance Colab bị hủy.
2. **`supabase` (Khuyến nghị cho Cloud / Colab):**
   - Lưu trữ trên Supabase Storage qua REST API (Bucket riêng tư `datt-media`).
   - Cần cấu hình: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `DATT_STORAGE_BUCKET`.
   - Tự động tạo thư mục cache đệm đọc tại `data/media-cache/`.
3. **`external` (S3 / GCS / Azure Blob):**
   - Sử dụng thư viện `fsspec` và `url_to_fs`.
   - Cần cấu hình: `DATT_STORAGE_URL` (Ví dụ: `s3://my-bucket/prefix`) và `DATT_STORAGE_OPTIONS` (JSON chuỗi chứa access key, secret key, endpoint url).

---

## 18. Cấu hình Email Thông báo (Email Configuration)

Để kích hoạt tính năng gửi cảnh báo qua Email:
- **Giao thức:** SMTP / ESMTP.
- **Cổng kết nối:** Cổng `587` (với chế độ mã hóa `starttls`) hoặc Cổng `465` (với chế độ mã hóa `ssl`).
- **Nhà cung cấp hỗ trợ:** Gmail SMTP (`smtp.gmail.com`), Outlook SMTP (`smtp.office365.com`), SendGrid, Amazon SES hoặc máy chủ SMTP nội bộ.
- *Lưu ý Gmail:* Nếu sử dụng tài khoản Gmail, bắt buộc phải bật tính năng Xác thực 2 bước (2FA) và tạo **Mật khẩu ứng dụng (App Password 16 ký tự)**, không dùng mật khẩu đăng nhập chính.

---

## 19. Bảng Biến Môi Trường Hệ Thống (Environment Variables)

| Tên biến | Kiểu giá trị | Mặc định | Mô tả |
|---|---|---|---|
| `DATT_DATABASE_URL` | String | Trống (fallback SQLite) | Chuỗi kết nối PostgreSQL (Ví dụ: `postgresql://user:pass@host:5432/datt`) |
| `POSTGRES_USER` | String | `datt` | Tên người dùng PostgreSQL cho docker-compose |
| `POSTGRES_PASSWORD` | String | Bắt buộc nếu dùng Docker | Mật khẩu tài khoản PostgreSQL |
| `POSTGRES_DB` | String | `datt` | Tên cơ sở dữ liệu PostgreSQL |
| `POSTGRES_PORT` | Integer | `5432` | Cổng dịch vụ PostgreSQL |
| `DATT_REQUIRE_PERSISTENCE` | Integer (0/1) | `0` | Nếu đặt là `1`, hệ thống sẽ từ chối khởi động nếu thiếu PostgreSQL hoặc thiếu Storage từ xa |
| `DATT_STORAGE_BACKEND` | Enum | `local` | Chọn backend lưu trữ: `local`, `supabase`, `external` |
| `DATT_STORAGE_ROOT` | Path | Thư mục gốc dự án | Thư mục lưu trữ khi dùng backend `local` |
| `DATT_STORAGE_CACHE` | Path | `data/media-cache` | Thư mục lưu cache đọc cho Supabase/External |
| `SUPABASE_URL` | String | Trống | Địa chỉ URL HTTPS của dự án Supabase |
| `SUPABASE_SERVICE_ROLE_KEY` | String | Trống | Service Role API Key của Supabase Storage |
| `DATT_STORAGE_BUCKET` | String | `datt-media` | Tên bucket lưu trữ trên Supabase |
| `DATT_STORAGE_URL` | String | Trống | URL bucket khi dùng `DATT_STORAGE_BACKEND=external` (s3://...) |
| `DATT_STORAGE_OPTIONS` | JSON String | `{}` | Tùy chọn cấu hình chứng thực cho fsspec (JSON format) |
| `DATT_EMAIL_HOST` | String | `smtp.gmail.com` | Địa chỉ máy chủ SMTP gửi mail |
| `DATT_EMAIL_PORT` | Integer | `587` | Cổng SMTP (587 hoặc 465) |
| `DATT_EMAIL_USERNAME` | String | Trống | Tài khoản đăng nhập máy chủ SMTP |
| `DATT_EMAIL_PASSWORD` | String | Trống | Mật khẩu đăng nhập SMTP (hoặc App Password) |
| `DATT_EMAIL_FROM` | String | Giống `DATT_EMAIL_USERNAME` | Địa chỉ email người gửi hiển thị |
| `DATT_EMAIL_TO` | String (phẩy) | Trống | Danh sách email người nhận thông báo, cách nhau bởi dấu phẩy |
| `DATT_EMAIL_TLS` | Enum | `starttls` | Chế độ bảo mật: `starttls` hoặc `ssl` |
| `DATT_NOTIFICATION_COOLDOWN_SECONDS` | Integer | `300` | Thời gian chặn gửi trùng lặp cảnh báo (giây) |
| `DATT_NOTIFICATION_MAX_RETRIES` | Integer | `3` | Số lần thử lại tối đa khi gửi email thất bại (tối đa 10) |
| `DATT_NOTIFICATION_RETRY_SECONDS` | Integer | `30` | Khoảng thời gian cơ sở để tính exponential backoff retry |
| `YTDLP_COOKIE_FILE` | Path | Trống | Đường dẫn file cookie định dạng Netscape để vượt xác thực YouTube |
| `AI_SERVER_URL` | String | `http://localhost:8000` | Địa chỉ URL nội bộ của AI streaming server |

---

## 20. Lưu ý An Toàn & Bảo mật (Security Considerations)

1. **Thiếu cơ chế Xác thực (No Built-in Authentication):**
   - Hệ thống hiện tại không có tính năng phân quyền đăng nhập người dùng. Bất kỳ ai có quyền truy cập vào cổng `8501` đều có thể cấu hình camera, thêm/xóa Watchlist hoặc tải ảnh bằng chứng.
   - **Giải pháp bắt buộc:** Triển khai hệ thống trong mạng nội bộ (Private LAN / VPN) hoặc đặt sau Reverse Proxy (Nginx) có cấu hình Basic Auth hoặc Cloudflare Zero Trust.
2. **Bảo mật Tệp cấu hình `.env`:**
   - Tuyệt đối không commit file `.env` chứa mật khẩu cơ sở dữ liệu và mật khẩu hòm thư SMTP lên Git repository công khai.
3. **Che giấu Thông tin Chứng thực trong Log (Credential Redaction):**
   - Mã nguồn DATT được thiết kế để không bao giờ ghi mật khẩu SMTP, Token Supabase hoặc Connection String chứa mật khẩu ra file log hoặc qua thông báo lỗi API.
4. **An toàn Tải lên File (Media Upload Safety):**
   - Mọi khóa lưu trữ (storage key) đều được kiểm tra nghiêm ngặt qua hàm `validate_key()` nhằm ngăn chặn triệt để lỗi tấn công vượt quyền thư mục (Path Traversal `../`).
   - File tải lên bị giới hạn kích thước tối đa (10 MB cho ảnh bằng chứng, từ chối file rỗng).
