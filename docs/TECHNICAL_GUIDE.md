# TÀI LIỆU KIẾN TRÚC VÀ ĐẶC TẢ KỸ THUẬT (TECHNICAL GUIDE)
**DATT — Hệ thống Giám sát Thị giác Thông minh (AI Vision Monitoring & Security System)**

---

## 1. Kiến trúc Tổng thể Hệ thống (System Architecture)

Hệ thống DATT được xây dựng theo mô hình kiến trúc phân lớp hướng module (Modular Pipeline Architecture), phân tách hoàn toàn giữa luồng xử lý thị giác máy tính thời gian thực (Realtime CV Loop), luồng ghi nhận dữ liệu bền vững (Asynchronous Persistence Loop), kênh gửi thông báo (Outbox Notification Transport) và giao diện điều khiển (Frontend UI Layer).

```
                            [ CAMERA / VIDEO STREAM ]
       (RTSP / HLS / YouTube Live / CCTV / Local Video MP4)
                                    │
                                    ▼
                          [ 1. CAMERA READER ]
              (DirectHLSReader / CameraReader / LocalVideoReader)
                                    │  (BGR Frame @ 30 FPS)
                                    ▼
                         [ 2. YOLO11s DETECTOR ]
             (PyTorch CUDA FP16, ImgSize 960/768/640, Even Frames)
                                    │
                     ┌──────────────┴──────────────┐
                     ▼                             ▼
           [ 3A. PERSON TRACKER ]        [ 3B. CAR TRACKER ]
         (ByteTrack - Class 0 Person)  (ByteTrack - Classes 2,3,5,7)
                     │                             │
                     ▼                             ▼
         [ 4A. ADAPTIVE FACE ]          [ 4B. ANPR / LPR OCR ]
          - Upper-Body ROI               - Vehicle Crop
          - SCRFD (buffalo_s)            - PlateDetector (YOLOv8n)
          - Landmark Check (5 pts)       - Image Preprocessing
          - Overhead Distortion Calc     - EasyOCR GPU/CPU
          - R2 Homography Rectify        - VN Plate Sanitizer
          - 112x112 Norm Crop            - Multi-crop ECC Fusion
          - AdaFace IR50 (512-d)         - 10-frame Voting Consensus
          - Candidate Buffer & F2        - Vehicle Color Extractor
                     │                             │
                     ▼                             ▼
         [ 5A. TARGET MATCHER ]       [ 5B. WATCHLIST LOOKUP ]
         (Cosine Similarity >= 0.45)   (Exact Normalized Plate Match)
                     │                             │
                     └──────────────┬──────────────┘
                                    │
                                    ▼
                         [ 6. ZONE OCCUPANCY ]
             (ZoneCounter / CarCounter with Polygon ROI)
                                    │
                     ┌──────────────┴──────────────┐
                     ▼                             ▼
           [ 7A. FRAME RENDERER ]         [ 7B. EVENT MANAGER ]
          - Bounding Boxes & HUD         - In-memory Sessions
          - Target & Plate Labels        - Threshold Episodes
          - Single JPEG Encode            (Crowd / Congestion)
                     │                             │
                     ▼                             ▼
          [ 8A. MJPEG / PACKET ]        [ 8B. DATABASE WORKER ]
          - /video_feed                  - Async Queue (max 1000)
          - /frame_packet (DATT)         - Coalescing by session_key
                     │                   - PostgreSQL 17 + pgvector
                     ▼                   - Multi-backend Media Storage
            [ 9. FRONTEND UI ]                     │
        (HTML5 / CSS / Vanilla JS)                 ▼
                                         [ 10. NOTIFICATION ]
                                         - Transactional Outbox
                                         - SMTP Worker with Evidence
                                         - 300s Cooldown & Retries
```

---

## 2. Đặc tả Chi tiết Các Thành phần Hệ thống

### 2.1. Bộ Tiếp nhận và Đồng bộ Khung hình (Camera Ingestion Subsystem)

- **Các lớp Reader chuyên biệt ([src/stream/](../src/stream/)):**
  - [DirectHLSReader](../src/stream/direct_hls.py): Ingestion luồng HLS trực tiếp (`.m3u8`) qua FFmpeg subprocess pipe, chuyển đổi sang định dạng ảnh thô BGR24 mà không thông qua yt-dlp.
  - [CameraReader](../src/stream/youtube_stream.py): Ingestion luồng RTSP và YouTube Live (kết hợp với [stream_resolver](../src/stream/youtube_resolver.py) để trích xuất link HLS). Tích hợp cơ chế tự động kết nối lại (reconnect) và watchdog kiểm tra luồng treo (> 15 giây).
  - [LocalVideoReader](../src/stream/video_source.py): Đọc video MP4 từ ổ đĩa qua OpenCV VideoCapture, hỗ trợ chế độ lặp vô hạn (`loop=True`).
- **Pacing & Synchronization:**
  - `CameraManager` duy trì luồng đọc non-blocking với cơ chế **Latest-Frame Semantics**: Khung hình mới nhất ghi đè vào slot đệm; nếu luồng xử lý AI chậm hơn tốc độ đọc của camera, các khung hình cũ sẽ được loại bỏ tự nhiên mà không gây phình to bộ nhớ (Zero Unbounded Buffering).
  - Mỗi khung hình được gán số thứ tự đơn điệu (`frame_seq`) và nhãn thời gian thu nhận (`frame_pts`).

---

### 2.2. Bộ Phát hiện Đối tượng (Object Detection - YOLO11s)

Được hiện thực hóa trong [src/detector/yolo_detector.py](../src/detector/yolo_detector.py):
- **Kiến trúc mô hình:** Ultralytics **YOLO11s** (`models/yolo11s.pt`).
- **Thiết bị suy luận:** Khởi tạo trên `cuda:0` (nếu có NVIDIA GPU) hoặc tự động fallback sang `cpu`.
- **Độ chính xác số thực:** Tự động kích hoạt bán chính xác **FP16 Half-Precision** (`half=True`) trên CUDA GPU để tăng gấp đôi thông lượng tính toán và tiết kiệm 50% dung lượng VRAM.
- **Độ phân giải suy luận (`config.IMG_SIZE`):** Mặc định **960x960** (hỗ trợ điều chỉnh sang `768x768` hoặc `640x640` qua CLI).
- **Các lớp đối tượng quan tâm (`config.TARGET_CLASSES`):**
  - Class `0`: Người (`person`)
  - Class `2`: Ô tô con (`car`)
  - Class `3`: Xe máy (`motorcycle`)
  - Class `5`: Xe buýt (`bus`)
  - Class `7`: Xe tải (`truck`)
- **Tham số lọc:**
  - Ngưỡng tin cậy phát hiện (`CONF_THRESHOLD`): `0.35`
  - Ngưỡng lọc triệt tiêu phi cực đại (`NMS_THRESHOLD`): `0.45`
  - Số lượng phát hiện tối đa mỗi frame (`MAX_DETECTIONS`): `100`
- **Khởi động làm nóng (Model Warmup):** Phương thức `detector.warmup()` chạy suy luận trên khung hình rỗng ngay khi khởi động để nạp sẵn kernel CUDA vào VRAM, loại bỏ độ trễ giật lag (stutter) ở những khung hình đầu tiên.

---

### 2.3. Bộ Theo dõi Đa Đối tượng (Multi-Object Tracking - ByteTrack)

Được hiện thực hóa trong [src/tracker/bytetrack_tracker.py](../src/tracker/bytetrack_tracker.py):
- **Phân tách bộ theo dõi độc lập (Dual Independent Trackers):**
  - `PersonTracker`: Quản lý danh sách ID cho người đi bộ (Class 0).
  - `CarTracker`: Quản lý danh sách ID cho các loại phương tiện (Classes 2, 3, 5, 7).
  - *Lý do kiến trúc:* Tách biệt hai bộ ByteTrack riêng biệt giúp triệt tiêu hoàn toàn hiện tượng va chạm hoặc hoán đổi mã định danh (Track ID collision) giữa người và xe.
- **Cơ chế Nhịp suy luận AI (Detection Cadence Optimization):**
  - Để đạt tốc độ hiển thị mượt mà 30 FPS trên trình duyệt mà không làm quá tải GPU:
    - **Khung hình chẵn (`total_frames % 2 == 0`):** Chạy toàn bộ mạng nơ-ron YOLO11s Detection, sau đó gọi `tracker.update(detections)` để ghép nối hộp bao và cập nhật bộ lọc Kalman.
    - **Khung hình lẻ (`total_frames % 2 != 0`):** Bỏ qua suy luận YOLO (tiết kiệm ~15-20 ms), chỉ gọi phương thức nội suy toán học `tracker.predict()`. Bộ lọc Kalman tự động dự đoán tọa độ di chuyển của các hộp bao đang hoạt động.
- **Tham số cấu hình ByteTrack:**
  - `TRACK_ACTIVATION_THRESHOLD`: `0.40`
  - `LOST_TRACK_BUFFER`: `30` (giữ vết đối tượng mất dấu trong tối đa 30 frame)
  - `MINIMUM_MATCHING_THRESHOLD`: `0.80`
  - `MINIMUM_CONSECUTIVE_FRAMES`: `2`

---

### 2.4. Phân hệ Nhận diện Khuôn mặt Thích ứng (Adaptive Face Pipeline)

Hiện thực hóa tại [src/face/adaptive_pipeline.py](../src/face/adaptive_pipeline.py), [src/face/face_embedder.py](../src/face/face_embedder.py) và [src/recognition/target_matcher.py](../src/recognition/target_matcher.py):

#### 1. Trích xuất Vùng quan tâm (Upper-Body / Head ROI)
Từ bounding box của người do ByteTrack cung cấp, thuật toán cắt lấy vùng 55% nửa trên của cơ thể để tìm kiếm khuôn mặt, loại bỏ các chi tiết thừa từ phần thân và chân.

#### 2. Phát hiện Khuôn mặt Đa tầng thích ứng (Two-Pass SCRFD)
- Sử dụng mô hình SCRFD trong gói InsightFace (`buffalo_s`).
- **Pass 1:** Chạy phát hiện trên ROI gốc với ngưỡng `det_thresh = 0.35`.
- **Pass 2 (Adaptive Upscale):** Nếu kích thước ROI nhỏ (đặc trưng của camera giám sát lắp trên cao), hệ thống tự động nội suy phóng to ROI từ 1.5x đến 4.0x:
  - $\text{min\_dim} \le 80\text{px} \rightarrow 4.0\text{x}$
  - $\text{min\_dim} \le 125\text{px} \rightarrow 3.0\text{x}$
  - $\text{min\_dim} \le 220\text{px} \rightarrow 2.0\text{x}$
  - $\text{min\_dim} \le 320\text{px} \rightarrow 1.5\text{x}$
  - Giảm ngưỡng phát hiện xuống `det_thresh = 0.30` (hoặc `0.26` cho các mặt cực nhỏ).

#### 3. Kiểm định Hình học và Điểm mốc (Landmark Validation)
Kiểm tra 5 điểm mốc (2 mắt, mũi, 2 khóe miệng):
- Tọa độ điểm mốc phải nằm trong hộp bao khuôn mặt.
- Mắt trái phải nằm bên trái mắt phải ($x_{\text{left}} < x_{\text{right}}$).
- Khoảng cách hai mắt tối thiểu $\ge 4.0\text{ px}$.
- Tỷ lệ tam giác khuôn mặt theo chiều dọc:
  $$V_{\text{ratio}} = \frac{y_{\text{nose}} - y_{\text{eye\_mid}}}{y_{\text{mouth\_mid}} - y_{\text{eye\_mid}}} \in [0.20, 0.88]$$

#### 4. Đánh giá Méo Phối cảnh Góc cao (Overhead Distortion Score)
Camera giám sát tầm cao thường nhìn chúc từ trên xuống khiến trán bị phình to, cằm bị thu nhỏ. Hệ thống tính toán điểm biến dạng:
$$\text{Distortion} = 0.40 \times \text{Deficit}_{\text{aspect}} + 0.35 \times \text{Deficit}_{\text{eye\_ratio}} + 0.25 \times \text{Surplus}_{\text{forehead}}$$

#### 5. Nắn chỉnh Phối cảnh R2 Homography Rectification
Nếu $\text{Overhead Distortion} \ge 8.0$ hoặc $\text{Aspect} < 1.14$, hệ thống áp dụng phép biến đổi phối cảnh 4 điểm ngoài (Homography) để kéo dãn mặt về tỷ lệ chuẩn $\text{CANONICAL\_ASPECT} = 1.1544$ với trọng số hòa trộn $\alpha = 0.50$:
$$H_{\alpha} = I \times (1 - \alpha) + H_{\text{full}} \times \alpha$$
Mọi phép biến đổi đều phải vượt qua hàm an toàn [validate_homography_safety](../src/face/adaptive_pipeline.py#L116-L141). Nếu phát hiện điểm mốc bị lật hoặc vỡ ảnh, hệ thống tự động fallback về ảnh gốc RAW.

#### 6. Trích xuất Vector Đặc trưng (AdaFace IR50)
- Ảnh sau khi nắn chỉnh được chuẩn hóa kích thước 112x112 pixel qua `insightface.utils.face_align.norm_crop`.
- Mô hình **AdaFace IR50** (`models/face/adaface_ir50_ms1mv2.onnx`) trích xuất vector đặc trưng 512 chiều.
- Vector được chuẩn hóa chuẩn $L_2$ ($\|v\|_2 = 1.0$).

#### 7. Bộ đệm Ứng viên & Hợp nhất Đa khung hình (F2 Candidate Fusion)
- Mỗi đối tượng (Track ID) sở hữu một `CandidateBuffer`.
- Thuật toán lựa chọn Top-3 ứng viên có điểm chất lượng cao nhất, với điều kiện bắt buộc: **mỗi ứng viên phải cách nhau tối thiểu 2 khung hình** để đảm bảo tính độc lập về bằng chứng.
- Hợp nhất theo trọng số chất lượng ảnh và chuẩn hóa lại:
  $$V_{\text{fused}} = \text{Normalize}\left(\sum_{i=1}^K w_i \cdot V_i\right)$$

#### 8. So khớp Mục tiêu (Target Matching)
- Tính toán độ tương đồng Cosine giữa vector $V_{\text{fused}}$ và vector các mục tiêu đang kích hoạt trong Watchlist:
  $$\text{Similarity}(A, B) = A \cdot B = \sum_{j=1}^{512} A_j B_j$$
- Nếu $\text{Similarity} \ge \text{target.face\_threshold}$ (mặc định 0.45): Xác nhận `FACE_MATCH`.

---

### 2.5. Phân hệ Nhận diện Biển số xe Tự động (ANPR / LPR Pipeline)

Hiện thực hóa tại [src/ocr/plate_detector.py](../src/ocr/plate_detector.py), [src/ocr/plate_reader.py](../src/ocr/plate_reader.py) và [src/ocr/plate_tracker.py](../src/ocr/plate_tracker.py):

#### 1. Định vị Biển số Chuyên dụng (Dedicated Plate YOLO Detector)
- Xe cơ giới (Car, Motorcycle, Truck, Bus) được cắt crop từ frame gốc.
- Mô hình `yolov8n-license-plate.pt` quét bên trong crop xe để tìm tọa độ chính xác của tấm biển số với ngưỡng `conf = 0.25`.

#### 2. Tiền xử lý Ảnh Biển số (Image Enhancement)
Ảnh crop biển số được tăng cường chất lượng thị giác trước khi đưa vào OCR:
- Chuyển đổi sang ảnh xám (Grayscale).
- Cân bằng độ tương phản cục bộ thích ứng (CLAHE).
- Khử nhiễu Gaussian và phân ngưỡng thích ứng (Adaptive Thresholding).

#### 3. Nhận dạng Ký tự Quang học (EasyOCR & Line Recognizer)
- Mô hình **EasyOCR** (ngôn ngữ Tiếng Anh `en` hỗ trợ GPU CUDA) đọc các dòng ký tự trên biển.
- Tích hợp mô hình dự phòng nhẹ `en_PP-OCRv4_rec_mobile.onnx` khi chạy trên CPU.

#### 4. Chuẩn hóa và Kiểm định Biển số Việt Nam
- Hàm `clean_plate_text`: Chuyển thành chữ in hoa, chuẩn hóa dấu cách, dấu gạch chéo thành dấu gạch nối (`-`).
- Hàm `normalize_plate_text`: Loại bỏ toàn bộ dấu phân cách `[\s./-]`, giữ lại duy nhất ký tự chữ và số.
- Hàm `is_valid_plate_format`: Kiểm tra biểu thức chính quy (Regex) theo quy chuẩn biển số xe cơ giới dân sự Việt Nam:
  `^([0-9]{2})([A-Z][A-Z0-9]?)([0-9]{4,5})$`
  đồng thời xác thực mã tỉnh nằm trong tập hợp các tỉnh thành hợp lệ (`11, 12, 14-43, 47-99`).

#### 5. Hợp nhất Đa Khung hình Biển số (ECC Affine Crop Fusion)
Hàm `fuse_plate_crops` thu thập tối đa 6 ảnh crop biển số qua các frame, tìm ảnh có độ sắc nét Laplacian cao nhất làm mốc, sau đó căn chỉnh các ảnh còn lại bằng thuật toán **Enhanced Correlation Coefficient (ECC)** và tính ảnh trung vị theo thời gian (Temporal Median Stack) để làm rõ nét các nét chữ bị mờ.

#### 6. Cơ chế Đồng thuận Đa khung hình (Multi-Frame Voting Consensus)
Được quản lý bởi tiến trình nền `_OcrWorker` (hàng đợi tối đa 8 job):
- Lưu trữ lịch sử 10 lần nhận diện gần nhất (`PLATE_HISTORY_SIZE = 10`).
- Biển số chỉ được chuyển từ trạng thái `CHECKING` / `PROVISIONAL` sang **`CONFIRMED`** khi:
  1. Số lần đọc ra cùng một biển số hợp lệ $\ge \text{max}(2, \text{PLATE\_MIN\_OBSERVATIONS})$.
  2. Tỷ lệ phiếu bầu của chuỗi biển số chiến thắng đạt $\ge 75\%$ tổng số quan sát (`PLATE_CONSENSUS_RATIO = 0.75`).
  3. Độ tin cậy OCR $\ge 0.35$ (`PLATE_CONSENSUS_CONFIDENCE`).

---

### 2.6. Nhận diện Màu sắc Phương tiện (Vehicle Color Extraction)

Được hiện thực hóa trong [src/recognition/color_extractor.py](../src/recognition/color_extractor.py):
- Nhận diện màu sắc chỉ được kích hoạt **SAU KHI** xe đã có biển số xác nhận (`CONFIRMED`) và khớp với một xe trong Watchlist.
- Phân tích biểu đồ màu không gian HSV trên vùng thân xe (loại bỏ vùng kính chắn gió và lốp xe).
- Phân loại vào 11 nhóm màu tiêu chuẩn: `black`, `white`, `gray`, `silver`, `red`, `blue`, `green`, `yellow`, `orange`, `brown`, `other`.

---

### 2.7. Quản lý Sự kiện & Lưu trữ Bất đồng bộ (EventManager & DatabaseWorker)

Hiện thực hóa tại [src/events/event_manager.py](../src/events/event_manager.py) và [src/events/db_worker.py](../src/events/db_worker.py):

#### Nguyên lý Không Gây Chặn (Zero Realtime Blocking I/O):
- Vòng lặp thị giác AI xử lý frame ở tần số 30 FPS không bao giờ gọi câu lệnh `INSERT` vào database hoặc ghi file đĩa trực tiếp.
- Mọi dữ liệu phát hiện được đóng gói thành các đối tượng truyền dữ liệu bất biến (Data Transfer Object - DTO):
  - `FaceEventDTO`
  - `VehiclePassageDTO`
  - `BusinessEventDTO`
- DTO được đưa vào hàng đợi `queue.Queue(maxsize=1000)` của `DatabaseWorker` chạy trên một thread nền chuyên trách.

#### Cơ chế Gộp trạng thái (Coalescing) & Chống Trùng lặp:
- Khi một xe di chuyển trong khung hình, các bản ghi cập nhật được gộp theo `session_key = "<camera_id>:<track_id>:<timestamp>"`. DatabaseWorker chỉ thực thi ghi nhận bản ghi tổng kết khi xe rời khỏi khung hình (`is_final = True`).
- Sự kiện khuôn mặt được lọc trùng lặp tức thời qua khóa in-memory `_emitted_face_tracks: set = "<camera_id>:<track_id>:<target_id>"`. Mỗi đối tượng đi qua chỉ phát 1 sự kiện duy nhất cho mỗi lượt xuất hiện.

---

### 2.8. Hệ thống Cơ sở Dữ liệu & Lưu trữ (Database & Media Storage)

#### Mô hình Quan hệ Bảng (SQLAlchemy 2.0 Models):
- `cameras`: Quản lý danh mục camera, URL nguồn, vị trí, token lease kích hoạt.
- `video_sources`: Quản lý file video MP4 tải lên, thời lượng, độ phân giải, fps.
- `zones`: Quản lý tọa độ đa giác ROI theo từng camera.
- `targets`: Hồ sơ đối tượng khuôn mặt cần theo dõi.
- `target_embeddings`: Vector đặc trưng 512 chiều kiểu dữ liệu `VECTOR(512)` của pgvector.
- `detection_events`: Bản ghi phát hiện cơ bản.
- `vehicle_events`: Bản ghi sự kiện phương tiện, màu xe nhận diện được, đường dẫn ảnh xe.
- `plate_events`: Bản ghi sự kiện biển số, chuỗi biển số gốc, chuỗi chuẩn hóa, đường dẫn ảnh crop biển số.
- `face_events`: Bản ghi sự kiện khuôn mặt, độ tương đồng similarity, đường dẫn ảnh crop mặt.
- `vehicle_passages`: Phiên lưu thông hoàn chỉnh của phương tiện (thời điểm vào, ra, thời lượng lưu thông, hướng di chuyển).
- `business_events`: Sự kiện nghiệp vụ cấp cao (`FACE_WATCHLIST_MATCH`, `VEHICLE_WATCHLIST_MATCH`, `CROWD_THRESHOLD`, `VEHICLE_CONGESTION`). Có khóa `idempotency_key` chống ghi trùng lặp.
- `vehicle_watchlists`: Danh sách biển số xe cần theo dõi.
- `vehicle_watchlist_results`: Bảng đối soát kết quả khớp biển số tại thời điểm ghi nhận sự kiện (`MATCH` hoặc `NO_MATCH`).
- `notifications`: Hàng đợi gửi thông báo cảnh báo qua Email.

---

### 2.9. Phân hệ Cảnh báo & Gửi Email (Notification Service)

Hiện thực hóa tại [src/notifications/service.py](../src/notifications/service.py) và [src/notifications/email.py](../src/notifications/email.py):
- Hoạt động theo mô hình **Transactional Outbox Pattern**: Bản ghi notification được sinh ra cùng transaction với FaceEvent hoặc PlateEvent.
- **Tiến trình gửi mail ngầm:** `NotificationEmailWorker` quét các bản ghi có trạng thái `pending` hoặc `failed` (trong hạn ngạch retry) mỗi 1 giây.
- **Đính kèm bằng chứng:** Tự động đọc file ảnh từ Storage backend (tối đa 5 MB) và đính kèm vào email dưới dạng file `evidence.jpg`.
- **Cơ chế Cooldown:** Chặn gửi lặp trong vòng 300 giây cho cùng một cặp `(target_id, camera_id)` hoặc `(vehicle_watchlist_id, camera_id)`.
- **Thử lại theo số mũ (Exponential Backoff):**
  $$\Delta t_{\text{retry}} = \min(3600, 30 \times 2^{\text{retry\_count}})$$

---

### 2.10. Web Server & Giao thức Truyền luồng (Web Streaming & Frontend)

- **FastAPI Backend Server ([src/ui/web_server.py](../src/ui/web_server.py)):**
  - Cung cấp các endpoint JSON REST API cho toàn bộ hệ thống.
  - Phục vụ ứng dụng Single Page Application (SPA) qua `index.html`.
- **Giao thức Truyền luồng Video Đồng bộ:**
  - **Kênh truyền thống:** `/video_feed` trả về luồng `multipart/x-mixed-replace; boundary=frame` MJPEG tiêu chuẩn.
  - **Kênh nhị phân đồng bộ cao cấp:** `/frame_stream` và `/frame_packet`. Mỗi frame được đóng gói thành một gói nhị phân gồm:
    - **Header cố định 64 bytes:** Bắt đầu bằng 4 byte Magic `b"DATT"`, tiếp theo là Sequence ID, PTS Timestamp, độ dài JSON telemetry và độ dài JPEG payload.
    - **JSON Telemetry Payload:** Chứa toàn bộ thông số người/xe, FPS, latency đo được đúng tại khung hình đó.
    - **Raw JPEG Payload:** Dữ liệu ảnh nén của frame.
    - Phía trình duyệt, lớp [DattFrameStreamParser](../src/ui/static/frame_stream.js#L2-L24) giải mã nhị phân và vẽ frame lên thẻ `<canvas>` đồng thời cập nhật số liệu HUD, loại bỏ hoàn toàn hiện tượng số liệu đếm đi trước hoặc đi sau hình ảnh video.

---

### 2.11. Kiến trúc Giao diện Người dùng Enterprise (Enterprise Frontend Architecture)

Toàn bộ giao diện hệ thống được thiết kế theo kiến trúc chuẩn Enterprise Monitoring Dashboard với các module chuyên biệt:

#### 1. Hệ thống Design Tokens (CSS Variables):
Khai báo tại [src/ui/static/style.css](../src/ui/static/style.css):
- **Phông chữ toàn cục:** Chuẩn hóa về phông `Inter` / system-ui, cỡ chữ mặc định toàn bộ ứng dụng là **13px**.
- **Bảng màu giao diện:**
  - Sidebar: `#FFFFFF` | Border `#E5E7EB` | Text `#374151` | Hover `#F3F4F6`.
  - Workspace: `#F5F6F8`.
  - Content Cards: `#FFFFFF` | Border `#E5E7EB`.
  - Biểu tượng: Monochrome Outline SVGs thống nhất, không dùng emoji, không gradient.
- **Tùy biến Theme Accent Color:**
  - 5 phối màu chủ đạo: Blue (`#2563EB`), Green (`#059669`), Purple (`#7C3AED`), Orange (`#EA580C`), Red (`#DC2626`).
  - Được lưu trữ bền vững tại `localStorage.getItem('datt_accent_color')`.
  - Giữ nguyên màu ngữ nghĩa trạng thái (Semantic Colors: Success Green, Warning Amber, Error Red, Info Blue).

#### 2. Phân tách Chế độ Camera Management & Dedicated Stream View:
- **Camera Management (`UI_STATE.CAMERA_MANAGEMENT`):**
  - Giữ nguyên thanh Sidebar dọc `#mainSidebar`.
  - Không gian làm việc chứa bảng danh mục camera, thao tác probe kết nối, tạo mới và chỉnh sửa camera.
- **Dedicated Camera Stream View (`UI_STATE.MONITORING`):**
  - **Ẩn hoàn toàn Sidebar:** Thiết lập `#appContainer.style.display = 'none'`, kích hoạt `#streamScreen.style.display = 'flex'`.
  - **Thanh điều hướng tối giản (Stream Header Bar):** Nút quay lại (`#btnBackFromStream`), Tiêu đề Camera (`#streamCamTitle`), Trạng thái trực tiếp (`#streamStatusPill`), nút Fullscreen (`#btnFullscreenStream`).
  - **Khung hình Canvas trung tâm:** Canvas `#videoFeed` đặt trong `#videoCanvasBox` với `object-fit: contain`, bảo toàn tỷ lệ khung hình, chống biến dạng.
  - **Loại bỏ Event Feed bên dưới:** Toàn bộ thành phần UI sự kiện phía dưới video được loại bỏ hoàn toàn khỏi luồng DOM của Stream View.

#### 3. Chế độ Giám sát Toàn màn hình (Fullscreen Monitoring):
- Container `#streamViewport` gọi Fullscreen API trình duyệt mà không khởi động lại video stream.
- Thanh trạng thái `#fullscreenStatusBar` hiển thị thông số:
  - **PEOPLE COUNT:** Lấy từ trường `data.people_count` của telemetry ByteTrack.
  - **VEHICLE COUNT:** Lấy từ trường `data.car_count` của telemetry ByteTrack.
- Hỗ trợ nút Thoát và phím tắt `ESC` để quay lại Stream View thông thường.

#### 4. Cơ chế Cảnh báo Toàn cục (Global Alert Toast System):
- Triển khai hàm `showGlobalToast(title, message, severity, durationMs = 5000)`:
  - Hiển thị cố định tại góc trên bên phải màn hình.
  - Tự động đóng sau đúng 5000ms với bộ đếm thời gian độc lập.
  - Nút `✕` cho phép người dùng đóng ngay lập tức mà không làm ảnh hưởng hay xóa dữ liệu trong cơ sở dữ liệu.
  - **Cơ chế Reparenting khi Fullscreen:** Trình lắng nghe sự kiện `fullscreenchange` tự động di chuyển container `#globalToastContainer` vào bên trong `#streamViewport` khi vào toàn màn hình và đưa trở lại `document.body` khi thoát toàn màn hình, đảm bảo thông báo không bao giờ bị lớp phủ Fullscreen của trình duyệt che khuất.
- **Đồng bộ Outbox:** Định kỳ mỗi 6 giây, hàm `pollAlertsForGlobalToast()` thăm dò endpoint `/api/alerts` và kích hoạt toast thông báo theo đúng trạng thái thực tế của email (`PENDING`, `SENT`, `FAILED`, `SUPPRESSED`).
