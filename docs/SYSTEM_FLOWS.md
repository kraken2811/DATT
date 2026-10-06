# SƠ ĐỒ LUỒNG HOẠT ĐỘNG HỆ THỐNG (SYSTEM FLOWS)
**DATT — Hệ thống Giám sát Thị giác Thông minh (AI Vision Monitoring & Security System)**

---

Tài liệu này mô tả chi tiết 10 luồng xử lý cốt lõi của hệ thống DATT bằng sơ đồ Mermaid chuẩn, phản ánh chính xác cấu trúc thực thi trong mã nguồn.

---

## 1. Luồng Xử lý Camera & Khung hình (Camera Processing Flow)

Mô tả chu trình từ khi camera tiếp nhận tín hiệu video, qua bộ điều tiết nhịp (Pacer), giải mã và đưa vào vòng lặp xử lý AI:

```mermaid
sequenceDiagram
    autonumber
    participant Source as "Nguồn Video (RTSP / HLS / YouTube / File)"
    participant Reader as "Reader Thread (CameraReader / DirectHLSReader)"
    participant Pacer as "Pacing & Jitter Buffer"
    participant Manager as "CameraManager (Latest-Frame Slot)"
    participant AppLoop as "AI Pipeline Loop (app.py)"
    participant Render as "Frame Renderer & MJPEG Server"

    Source->>Reader: Luồng Video thô (H.264 / Network Packets)
    alt Nguồn YouTube
        Reader->>Reader: stream_resolver trích xuất URL HLS (.m3u8)
    end
    Reader->>Reader: FFmpeg / OpenCV Decode sang khung hình BGR thô
    Reader->>Pacer: Chuyển frame kèm PTS timestamp
    Pacer->>Pacer: Đồng bộ tốc độ khung hình (30 FPS Pacing)
    Pacer->>Manager: Ghi đè vào latest_frame (Không dùng hàng đợi không giới hạn)
    
    loop Mỗi chu kỳ vòng lặp (~30 FPS)
        AppLoop->>Manager: read_with_meta(timeout=2.0)
        Manager-->>AppLoop: frame, frame_seq, frame_pts
        alt Khung hình chẵn (total_frames % 2 == 0)
            AppLoop->>AppLoop: Chạy YOLO11s Detection (Người & Xe)
            AppLoop->>AppLoop: tracker.update(detections)
        else Khung hình lẻ (total_frames % 2 != 0)
            AppLoop->>AppLoop: Bỏ qua YOLO suy luận
            AppLoop->>AppLoop: tracker.predict() (Bộ lọc Kalman nội suy)
        end
        AppLoop->>Render: render_frame(frame, tracks, counts, matches)
        Render->>Render: Mã hóa JPEG (Chất lượng 80)
        Render-->>AppLoop: jpeg_bytes, shared_state.update()
    end
```

---

## 2. Luồng Trích xuất Đặc trưng Khuôn mặt (Face Recognition Flow)

Mô tả thuật toán xử lý khuôn mặt thích ứng đa tầng (Adaptive Face Pipeline) từ hộp bao người đến vector đặc trưng 512 chiều:

```mermaid
flowchart TD
    Start(["Khung hình BGR + Track người"]) --> CropROI["1. Cắt Vùng Thân Trên (Upper-Body ROI: top 55% Bounding Box)"]
    CropROI --> Pass1["2. Pass 1: SCRFD Face Detection (1.0x, det_thresh=0.35)"]
    Pass1 --> CheckPass1{"Tìm thấy khuôn mặt?"}
    
    CheckPass1 -- "Có" --> LandmarkCheck
    CheckPass1 -- "Không & ROI nhỏ (min_dim <= 320px)" --> Upscale["3. Pass 2: Phóng to ROI thích ứng (1.5x - 4.0x)"]
    Upscale --> Pass2["Chạy lại SCRFD nhạy (det_thresh=0.30 hoặc 0.26)"]
    Pass2 --> CheckPass2{"Tìm thấy mặt?"}
    CheckPass2 -- "Không" --> RejectFace["Bỏ qua khung hình này (WAIT_FOR_BETTER_FACE)"]
    CheckPass2 -- "Có" --> RescaleCoords["Quy đổi tọa độ về kích thước ROI gốc"]
    RescaleCoords --> LandmarkCheck

    LandmarkCheck["4. Kiểm định 5 Điểm mốc (Landmarks: Mắt, Mũi, Khóe miệng)"]
    LandmarkCheck --> ValidGeo{"Điểm mốc hợp lệ & Tỷ lệ tam giác dọc in [0.20, 0.88]?"}
    ValidGeo -- "Không" --> RejectGeo["Loại bỏ ứng viên (INVALID_GEOMETRY)"]
    
    ValidGeo -- "Có" --> CalcDistort["5. Tính Điểm méo góc cao (Overhead Distortion Score)"]
    CalcDistort --> CheckDistort{"Distortion >= 8.0 hoặc Aspect < 1.14?"}
    
    CheckDistort -- "Có" --> Homography["6. Áp dụng R2 Homography Rectification (Alpha=0.50, Aspect=1.1544)"]
    Homography --> SafeWarp{"validate_homography_safety = SAFE?"}
    SafeWarp -- "Không an toàn" --> FallbackRAW["Hồi phục về ảnh gốc (RAW_FALLBACK)"]
    SafeWarp -- "An toàn" --> NormCrop112
    FallbackRAW --> NormCrop112
    CheckDistort -- "Không méo" --> NormCrop112

    NormCrop112["7. Chuẩn hóa & Cắt khuôn mặt 112x112 pixel (norm_crop)"]
    NormCrop112 --> CalcQuality["8. Tính Điểm chất lượng ảnh (Sharpness, Frontality, Confidence)"]
    CalcQuality --> AdaFace["9. Đưa vào AdaFace IR50 Model (adaface_ir50_ms1mv2.onnx)"]
    AdaFace --> NormalizeL2["10. Chuẩn hóa vector L2 (512 chiều, ||v|| = 1.0)"]
    NormalizeL2 --> EndFace(["Ứng viên Khuôn mặt Sẵn sàng (Face Candidate)"])
```

---

## 3. Luồng Hợp nhất Ứng viên & So khớp Face Watchlist

Mô tả cách bộ đệm ứng viên (Candidate Buffer) tổng hợp đa khung hình và tính toán tương đồng Cosine:

```mermaid
flowchart TD
    Candidate(["Ứng viên Khuôn mặt mới"]) --> Buffer["CandidateBuffer (Lưu theo cặp Camera ID & Track ID)"]
    Buffer --> CheckSpacing["Kiểm tra khoảng cách khung hình: abs(frame_a - frame_b) >= 2"]
    CheckSpacing --> FilterDistort["Lọc: Chiều rộng mặt in [32, 44px], Distortion <= 40.0"]
    FilterDistort --> SelectTop3["Chọn Top-3 Ứng viên có điểm chất lượng Composite cao nhất"]
    
    SelectTop3 --> CheckPool{"Đủ ít nhất 1-3 ứng viên hợp lệ?"}
    CheckPool -- "Chưa đủ" --> StateChecking["Trạng thái: CHECKING (Tiếp tục tích lũy bằng chứng)"]
    
    CheckPool -- "Đủ" --> F2Fusion["Thuật toán Hợp nhất F2 (Quality-Weighted Vector Sum)"]
    F2Fusion --> NormFused["Chuẩn hóa vector hợp nhất L2"]
    
    NormFused --> QueryTargets["Lấy danh sách Targets đang kích hoạt (Active) trong Database"]
    QueryTargets --> CosineSim["Tính Độ tương đồng Cosine: Similarity = Fused_Vector · Target_Vector"]
    
    CosineSim --> MaxMatch["Tìm mục tiêu có Similarity cao nhất"]
    MaxMatch --> ThreshCheck{"Similarity >= target.face_threshold (Mặc định 0.45)?"}
    
    ThreshCheck -- "Không" --> StateUnknown["Trạng thái: UNKNOWN"]
    ThreshCheck -- "Có" --> StateMatch["Xác nhận: FACE_MATCH"]
    
    StateMatch --> DedupCheck{"Đã phát sự kiện cho Track ID này chưa?"}
    DedupCheck -- "Đã phát rồi" --> SkipEvent["Bỏ qua (Chống tạo sự kiện trùng lặp)"]
    DedupCheck -- "Chưa phát" --> EmitEvent["Phát sự kiện FACE_WATCHLIST_MATCH -> Đưa vào Database Worker"]
```

---

## 4. Luồng Nhận diện Biển số xe (Vehicle OCR Flow)

Mô tả chu trình cắt ảnh xe, định vị biển số bằng YOLO, tiền xử lý và giải mã OCR:

```mermaid
flowchart TD
    VehicleTrack(["Hộp bao xe từ ByteTrack (Car/Motorcycle/Truck/Bus)"]) --> SizeCheck{"Kích thước xe >= 30x30 pixel?"}
    SizeCheck -- "Nhỏ hơn" --> SkipFrame["Bỏ qua (Xe ở quá xa)"]
    
    SizeCheck -- "Đủ lớn" --> PlateDet["1. Chạy PlateDetector YOLOv8n trên crop xe (conf >= 0.25)"]
    PlateDet --> FoundBox{"Phát hiện hộp biển số?"}
    FoundBox -- "Không" --> LegacyROI["Dự phòng: Cắt vùng 1/3 phía dưới của xe (Heuristic ROI)"]
    FoundBox -- "Có" --> CropPlate["Cắt ảnh biển số chính xác"]
    LegacyROI --> CropPlate

    CropPlate --> Enhance["2. Tiền xử lý Ảnh (Grayscale, CLAHE tăng tương phản, Khử nhiễu, Adaptive Thresh)"]
    Enhance --> OCR["3. EasyOCR nhận dạng ký tự (en, GPU CUDA / CPU fallback)"]
    OCR --> RawText["Nhận chuỗi ký tự thô + Độ tin cậy (Confidence)"]
    
    RawText --> Clean["4. Chuẩn hóa clean_plate_text (In hoa, chuyển dấu cách/xuyệt thành '-')"]
    Clean --> Normalize["5. Rút gọn normalize_plate_text (Loại bỏ toàn bộ ký tự phân cách)"]
    
    Normalize --> FormatCheck{"6. is_valid_plate_format (Kiểm tra biểu thức chính quy biển số VN)?"}
    FormatCheck -- "Không hợp lệ" --> RejectOCR["Loại bỏ ký tự rác (Ineligible Candidate)"]
    FormatCheck -- "Hợp lệ" --> QualityCheck{"Confidence >= 0.35 & Quality >= 0.0?"}
    QualityCheck -- "Không đạt" --> RejectOCR
    QualityCheck -- "Đạt chuẩn" --> EmitCand(["Ứng viên Biển số Hợp lệ (Eligible Plate Candidate)"])
```

---

## 5. Luồng Đồng thuận Biển số & Đối soát Vehicle Watchlist

Mô tả cơ chế bỏ phiếu đa khung hình chống đọc sai và tra cứu danh sách đen:

```mermaid
flowchart TD
    Cand(["Ứng viên Biển số mới"]) --> AddHistory["Lưu vào Lịch sử 10 khung hình (plate_history)"]
    AddHistory --> MultiCrop["Bộ đệm ảnh: Lưu trữ tối đa 6 ảnh crop biển số thực tế"]
    MultiCrop --> ECCFusion["fuse_plate_crops: Căn chỉnh affine ECC và tính trung vị đa khung hình"]
    
    AddHistory --> CountVotes["Tính tổng điểm số và số lần xuất hiện của từng chuỗi biển số"]
    CountVotes --> FindWinner["Xác định chuỗi biển số có điểm cao nhất (Winner)"]
    
    FindWinner --> CheckConsensus{"Đạt tiêu chí Đồng thuận (Consensus)?<br/>1. Số lần đọc >= 2 khung hình<br/>2. Tỷ lệ phiếu >= 75% tổng quan sát<br/>3. Điểm số chiếm >= 75% tổng điểm"}
    
    CheckConsensus -- "Chưa đủ" --> StatusChecking["Trạng thái: CHECKING / PROVISIONAL (Chưa xác nhận)"]
    CheckConsensus -- "Đủ tiêu chí" --> StatusConfirmed["Trạng thái: CONFIRMED (Biển số chính thức)"]
    
    StatusConfirmed --> StickyLock["Khóa biển số (Sticky: Không bị ghi đè bởi frame sau)"]
    StickyLock --> VehicleExit{"Xe kết thúc lượt di chuyển (Exited camera > 3s)?"}
    
    VehicleExit -- "Chưa" --> WaitExit["Chờ xe rời khung hình"]
    VehicleExit -- "Đã rời đi" --> LookupWatchlist["Tra cứu Bảng vehicle_watchlists (WHERE plate_number = winner AND status = 'active')"]
    
    LookupWatchlist --> MatchCheck{"Có trong Watchlist không?"}
    MatchCheck -- "Không khớp" --> RecordNoMatch["Ghi nhận VehicleWatchlistResult (decision='NO_MATCH')"]
    MatchCheck -- "Khớp mục tiêu" --> RecordMatch["Ghi nhận VehicleWatchlistResult (decision='MATCH')"]
    
    RecordMatch --> ExtractColor["Trích xuất màu xe tự động (analyze_vehicle_color)"]
    ExtractColor --> EnqueueEvents["Tạo VehicleEvent + PlateEvent + BusinessEvent + Enqueue Email"]
```

---

## 6. Luồng Khởi tạo Sự kiện Nghiệp vụ (Event Creation Flow)

Mô tả cách thức các loại sự kiện khác nhau được đóng gói và gửi vào hàng đợi lưu trữ bất đồng bộ:

```mermaid
flowchart LR
    subgraph "Nguồn kích hoạt Sự kiện"
        F1["Khuôn mặt khớp Target<br/>(FACE_MATCH)"]
        F2["Xe có biển số khớp Watchlist<br/>(VEHICLE_WATCHLIST_MATCH)"]
        F3["Đám đông vượt ngưỡng 40 người<br/>duy trì > 180s (CROWD_THRESHOLD)"]
        F4["Ùn tắc phương tiện > 40 xe<br/>(VEHICLE_CONGESTION)"]
    end

    subgraph "EventManager (Bộ quản lý Sự kiện)"
        EM["EventManager.process_*()"]
        BuildDTO["Đóng gói thành DTO bất biến:<br/>- FaceEventDTO<br/>- VehiclePassageDTO<br/>- BusinessEventDTO"]
    end

    subgraph "Hàng đợi Bất đồng bộ (DatabaseWorker)"
        TaskQueue["Bounded Queue<br/>(maxsize=1000)"]
        Priority{"Sự kiện có cờ<br/>is_critical=True?"}
        Evict["Loại bỏ tác vụ thường<br/>để ưu tiên sự kiện an ninh"]
    end

    F1 --> EM
    F2 --> EM
    F3 --> EM
    F4 --> EM

    EM --> BuildDTO
    BuildDTO --> Priority
    Priority -- "Hàng đợi đầy & Critical" --> Evict --> TaskQueue
    Priority -- "Hàng đợi còn chỗ" --> TaskQueue
```

---

## 7. Luồng Khử trùng lặp và Hợp nhất Dữ liệu (Deduplication & Coalescing)

Mô tả 3 tầng bảo vệ chống bùng nổ dữ liệu và trùng lặp sự kiện:

```mermaid
flowchart TD
    subgraph "Tầng 1: In-Memory Throttling (Trong Frame Loop)"
        T1_Face["Khuôn mặt: Khóa chuỗi camera_id:track_id:target_id<br/>Chỉ phát 1 lần cho mỗi lượt người xuất hiện"]
        T1_Veh["Phương tiện: Gộp trạng thái theo session_key<br/>Chỉ ghi nhận khi xe hoàn tất lượt di chuyển"]
    end

    subgraph "Tầng 2: DatabaseWorker Queue Coalescing (Hàng đợi nền)"
        T2_Passage["Nhiều bản cập nhật của cùng 1 session_key trong hàng đợi<br/>được gộp lại thành 1 bản ghi duy nhất có trạng thái mới nhất"]
    end

    subgraph "Tầng 3: Database Constraints (Ràng buộc Cơ sở dữ liệu)"
        T3_Idemp["Bảng business_events: Ràng buộc UNIQUE idempotency_key"]
        T3_Notice["Bảng notifications: Ràng buộc UNIQUE (event_id, channel, recipient)"]
        T3_Watch["Bảng vehicle_watchlists: Ràng buộc UNIQUE plate_number"]
    end

    T1_Face --> T2_Passage
    T1_Veh --> T2_Passage
    T2_Passage --> T3_Idemp
    T2_Passage --> T3_Notice
    T2_Passage --> T3_Watch
```

---

## 8. Luồng Vận chuyển Thông báo & Gửi Email (Notification / Email Flow)

Mô tả cơ chế Transactional Outbox, chống spam (Cooldown) và thử lại lũy thừa (Exponential Backoff):

```mermaid
sequenceDiagram
    autonumber
    participant Worker as "DatabaseWorker"
    participant Outbox as "DB Table: notifications"
    participant EmailWorker as "NotificationEmailWorker"
    participant Storage as "Media Storage (Local / Supabase / S3)"
    participant SMTP as "Máy chủ Mail (SMTP Server)"

    Worker->>Outbox: INSERT notification (status='pending', recipient, payload)
    Note over Outbox: Kiểm tra Cooldown 300s:<br/>Nếu cùng target/xe xuất hiện trong 300s -> status='suppressed'
    
    loop Quét hàng đợi mỗi 1 giây
        EmailWorker->>Outbox: SELECT ... WHERE status='pending' OR retryable<br/>FOR UPDATE SKIP LOCKED LIMIT 1
        Outbox-->>EmailWorker: Trả về bản ghi thông báo
        
        EmailWorker->>Storage: Tải ảnh bằng chứng crop (tối đa 5 MB)
        Storage-->>EmailWorker: Dữ liệu ảnh JPEG (evidence.jpg)
        
        EmailWorker->>EmailWorker: Tạo EmailMessage (Tiêu đề, Bảng thông tin, Đính kèm ảnh)
        
        EmailWorker->>SMTP: Kết nối SMTP (Port 587 STARTTLS / 465 SSL) & client.send_message()
        
        alt Gửi thành công
            SMTP-->>EmailWorker: 250 OK Message accepted
            EmailWorker->>Outbox: UPDATE status='sent', sent_at=NOW(), error=NULL
        else Gửi thất bại (Timeout / Mất mạng / Auth Error)
            SMTP-->>EmailWorker: Error / Exception
            EmailWorker->>EmailWorker: Phân loại lỗi an toàn (safe_error)
            alt retry_count < max_retries (Mặc định 3)
                EmailWorker->>Outbox: UPDATE status='failed', retry_count += 1,<br/>next_attempt_at = now + 30s * 2^retry_count
            else Hết lượt thử lại
                EmailWorker->>Outbox: UPDATE status='failed', giữ nguyên lịch sử lỗi
            end
        end
    end
```

---

## 9. Kiến trúc Tương tác Cơ sở Dữ liệu (Database Interaction Architecture)

Mô tả cơ chế phân bổ kết nối an toàn cho PostgreSQL / Supabase Session Pooler và SQLite:

```mermaid
flowchart TD
    subgraph "Ứng dụng DATT Backend"
        API["FastAPI Web Server Routes"]
        Worker["DatabaseWorker (Thread ngầm)"]
        Alerts["NotificationService (Thread ngầm)"]
    end

    subgraph "Lớp Database Abstraction (src/db/database.py)"
        DBClass["Database Class"]
        Engine["SQLAlchemy 2.0 Engine"]
        Sessionmaker["sessionmaker(expire_on_commit=False)"]
        UnitOfWork["Unit of Work: with db.transaction() as session: ..."]
    end

    subgraph "Chiến lược Connection Pooling"
        PostgresCheck{"Backend là PostgreSQL?"}
        NullPoolStrategy["Sử dụng NullPool (Không giữ kết nối nhàn rỗi)<br/>-> Ngăn chặn cạn kiệt Session Pooler của Supabase"]
        SQLiteStrategy["Sử dụng SQLite QueuePool<br/>Kích hoạt PRAGMA foreign_keys=ON<br/>Kích hoạt PRAGMA busy_timeout=5000"]
    end

    subgraph "Cơ sở Dữ liệu Đích"
        PG[("PostgreSQL 17 + pgvector")]
        SQLITE[("Local SQLite: datt.db")]
    end

    API --> DBClass
    Worker --> DBClass
    Alerts --> DBClass

    DBClass --> Engine
    Engine --> PostgresCheck
    PostgresCheck -- "Đúng" --> NullPoolStrategy --> PG
    PostgresCheck -- "Sai (Local Dev)" --> SQLiteStrategy --> SQLITE

    Engine --> Sessionmaker --> UnitOfWork
```

---

## 10. Kiến trúc Tương tác Frontend → API → Backend

Mô tả cách ứng dụng Single Page Application (SPA) tương tác với backend:

```mermaid
sequenceDiagram
    autonumber
    participant Browser as "Trình duyệt (Vanilla JS - app.js / frame_stream.js)"
    participant WebServer as "FastAPI Web Server (Port 8501)"
    participant AIStream as "Internal MJPEG Server (Port 8000)"
    participant DB as "PostgreSQL / SQLite Database"
    participant Storage as "Media Storage Provider"

    Note over Browser, WebServer: 1. Khởi động Giao diện
    Browser->>WebServer: GET / (Tải index.html, style.css, app.js)
    WebServer-->>Browser: Trả về tài nguyên tĩnh

    Note over Browser, AIStream: 2. Luồng Video & Telemetry Đồng bộ
    Browser->>WebServer: GET /frame_stream
    WebServer->>AIStream: Proxy luồng nhị phân /frame_packet
    AIStream-->>Browser: Stream nhị phân liên tục (Header 64-byte DATT + JSON Metrics + JPEG Bytes)
    Browser->>Browser: DattFrameStreamParser vẽ Canvas & cập nhật HUD

    Note over Browser, DB: 3. Tương tác Nghiệp vụ Watchlist & Camera
    Browser->>WebServer: POST /api/watchlist/vehicles (Thêm xe mới)
    WebServer->>DB: INSERT INTO vehicle_watchlists
    DB-->>WebServer: Bản ghi xe đã lưu
    WebServer-->>Browser: JSON 201 Created

    Browser->>WebServer: POST /api/register_target (Upload ảnh mặt mục tiêu)
    WebServer->>WebServer: SCRFD detect + AdaFace trích xuất vector 512-d
    WebServer->>Storage: Lưu ảnh gốc vào data/uploads/targets/
    WebServer->>DB: INSERT INTO targets & target_embeddings
    WebServer-->>Browser: JSON 201 Created

    Note over Browser, Storage: 4. Tra cứu Bằng chứng Sự kiện (Event Center)
    Browser->>WebServer: GET /api/event_center/events?watchlist_match=true
    WebServer->>DB: SQL UNION ALL projection từ các bảng sự kiện
    DB-->>WebServer: Danh sách sự kiện hợp nhất
    WebServer-->>Browser: JSON danh sách sự kiện
    
    Browser->>WebServer: GET /api/event_center/events/{event_id}/evidence
    WebServer->>Storage: get_storage().open(evidence_key)
    Storage-->>WebServer: File stream ảnh bằng chứng
    WebServer-->>Browser: Binary Response (image/jpeg) hiển thị trên Drawer
```

---

## 11. Luồng Chuyển đổi Giao diện Stream View & Fullscreen (Stream View & Fullscreen Transition)

Mô tả cơ chế chuyển đổi giữa giao diện quản lý có Sidebar dọc và giao diện xem luồng camera tối giản chuyên dụng:

```mermaid
sequenceDiagram
    autonumber
    participant User as "Người Dùng (Operator)"
    participant Nav as "Thanh Sidebar & Camera List"
    participant AppState as "Client State (app.js)"
    participant StreamView as "Dedicated Stream Screen"
    participant Viewport as "Fullscreen Viewport & Status Bar"
    participant Canvas as "Video Canvas (No Restart)"

    User->>Nav: Click "Xem Camera" / "Quick View"
    Nav->>AppState: setUiState(UI_STATE.MONITORING, { name, ... })
    AppState->>AppState: Ẩn appContainer (Ẩn hoàn toàn Sidebar dọc)
    AppState->>StreamView: Hiển thị streamScreen (Tối giản, không Event Feed)
    AppState->>Canvas: Kết nối luồng video /frame_stream (giữ aspect ratio)
    
    alt Người dùng kích hoạt Toàn màn hình
        User->>StreamView: Click nút "Toàn màn hình"
        StreamView->>Viewport: streamViewport.requestFullscreen()
        Viewport->>Viewport: Hiện thanh trạng thái xám (Tên, LIVE, Người, Xe)
        Viewport->>Viewport: Tự động reparent #globalToastContainer vào viewport
        Note over Canvas: Video mở rộng tối đa, KHÔNG restart stream
    else Thoát Toàn màn hình
        User->>Viewport: Nhấn nút "Thoát" hoặc phím ESC
        Viewport->>StreamView: Thoát fullscreen API
        Viewport->>StreamView: Ẩn status bar, trả toast container về document.body
    end

    User->>StreamView: Nhấn nút "← Quay lại"
    StreamView->>AppState: setUiState(UI_STATE.CAMERA_MANAGEMENT)
    AppState->>AppState: Hiển thị lại appContainer & Sidebar dọc màu trắng
```

---

## 12. Luồng Cảnh báo Toàn cục & Đồng bộ Outbox Email (Global Alert Toast & Outbox Sync)

Mô tả chu trình phát cảnh báo tức thì góc trên bên phải màn hình dựa trên dữ liệu outbox bất đồng bộ:

```mermaid
sequenceDiagram
    autonumber
    participant AI as "AI Detection Pipeline"
    participant DB as "PostgreSQL (notifications outbox)"
    participant Worker as "NotificationEmailWorker"
    participant API as "FastAPI (/api/alerts)"
    participant Client as "Client Poller (pollAlertsForGlobalToast)"
    participant Toast as "Global Toast (Top-Right 5s)"

    AI->>DB: Phát hiện Watchlist Match -> INSERT notification (status='PENDING')
    
    loop Mỗi 6 giây (Realtime Outbox Sync)
        Client->>API: GET /api/alerts?page=1&page_size=10
        API->>DB: Query notifications mới nhất
        DB-->>API: Danh sách alerts
        API-->>Client: JSON alerts
        Client->>Client: So sánh ID bản ghi mới nhận
        alt Phát hiện bản ghi trạng thái PENDING
            Client->>Toast: showGlobalToast('Cảnh báo email đang chờ gửi', ..., 'warning', 5000)
        end
    end

    Worker->>DB: Đọc bản ghi PENDING & Gửi SMTP qua máy chủ Mail
    alt Gửi email thành công
        Worker->>DB: UPDATE notification SET status='SENT', sent_at=NOW()
    else Gửi email thất bại
        Worker->>DB: UPDATE notification SET status='FAILED', error='...'
    end

    loop Chu kỳ thăm dò tiếp theo
        Client->>API: GET /api/alerts
        API-->>Client: Trạng thái cập nhật (SENT hoặc FAILED)
        alt Trạng thái SENT
            Client->>Toast: showGlobalToast('Đã gửi cảnh báo qua email', ..., 'success', 5000)
        else Trạng thái FAILED
            Client->>Toast: showGlobalToast('Gửi cảnh báo qua email thất bại', ..., 'error', 5000)
        end
    end

    Note over Toast: Toast tự đếm ngược 5s hoặc đóng khi bấm '✕' (Không xóa DB)
```
