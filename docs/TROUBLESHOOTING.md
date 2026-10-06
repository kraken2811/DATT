# HƯỚNG DẪN XỬ LÝ SỰ CỐ VÀ KHẮC PHỤC LỖI (TROUBLESHOOTING)
**DATT — Hệ thống Giám sát Thị giác Thông minh (AI Vision Monitoring & Security System)**

---

Tài liệu này tổng hợp toàn bộ các tình huống lỗi vận hành có thể xảy ra trong quá trình sử dụng hệ thống DATT, phân tích nguyên nhân gốc rễ (Root Cause), câu lệnh kiểm tra và hướng dẫn khắc phục cụ thể theo cấu trúc chuẩn:
- **Triệu chứng (Symptoms)**
- **Nguyên nhân có thể (Possible Causes)**
- **Cách kiểm tra (How to Check)**
- **Cách khắc phục (How to Fix)**

---

## MỤC LỤC SỰ CỐ

1. [Camera không kết nối được](#1-camera-không-kết-nối-được)
2. [Camera đang chạy bị mất luồng (Stream Dropout)](#2-camera-đang-chạy-bị-mất-luồng-stream-dropout)
3. [Video bị giật lag và độ trễ cao (Video Lag / High Latency)](#3-video-bị-giật-lag-và-độ-trễ-cao-video-lag--high-latency)
4. [Tốc độ xử lý FPS thấp (Low FPS)](#4-tốc-độ-xử-lý-fps-thấp-low-fps)
5. [GPU không hoạt động / Tự động chuyển sang CPU](#5-gpu-không-hoạt-động--tự-động-chuyển-sang-cpu)
6. [Khuôn mặt không được phát hiện (Face Not Detected)](#6-khuôn-mặt-không-được-phát-hiện-face-not-detected)
7. [Khuôn mặt có phát hiện nhưng không nhận diện được mục tiêu](#7-khuôn-mặt-có-phát-hiện-nhưng-không-nhận-diện-được-mục-tiêu)
8. [Nhận diện sai khuôn mặt (False Positive Match)](#8-nhận-diện-sai-khuôn-mặt-false-positive-match)
9. [Không tạo sự kiện trong Event Center khi có đối tượng đi qua](#9-không-tạo-sự-kiện-trong-event-center-khi-có-đối-tượng-đi-qua)
10. [Sự kiện bị ghi nhận trùng lặp (Duplicate Events)](#10-sự-kiện-bị-ghi-nhận-trùng-lặp-duplicate-events)
11. [Không đọc được biển số xe (OCR Failure)](#11-không-đọc-được-biển-số-xe-ocr-failure)
12. [OCR đọc sai ký tự biển số (OCR Misread)](#12-ocr-đọc-sai-ký-tự-biển-số-ocr-misread)
13. [Biển số đọc đúng nhưng không khớp Watchlist](#13-biển-số-đọc-đúng-nhưng-không-khớp-watchlist)
14. [Lỗi kết nối Cơ sở dữ liệu (Database Connection Error)](#14-lỗi-kết-nối-cơ-sở-dữ-liệu-database-connection-error)
15. [Lỗi Migration / Lệch phiên bản lược đồ Alembic](#15-lỗi-migration--lệch-phiên-bản-lược-đồ-alembic)
16. [Lỗi Ràng buộc Khóa ngoại (Foreign Key Constraint Error)](#16-lỗi-ràng-buộc-khóa-ngoại-foreign-key-constraint-error)
17. [Thông báo cảnh báo không được tạo (Notification Missing)](#17-thông-báo-cảnh-báo-không-được-tạo-notification-missing)
18. [Email ở trạng thái PENDING kéo dài không gửi đi](#18-email-ở-trạng-thái-pending-kéo-dài-không-gửi-đi)
19. [Email ở trạng thái FAILED (Gửi thất bại)](#19-email-ở-trạng-thái-failed-gửi-thất-bại)
20. [Giao diện Frontend không kết nối được Backend API](#20-giao-diện-frontend-không-kết-nối-được-backend-api)
21. [Lỗi API 4xx (400, 404, 409, 413)](#21-lỗi-api-4xx-400-404-409-413)
22. [Lỗi API 5xx (500, 503)](#22-lỗi-api-5xx-500-503)

---

## 1. Camera không kết nối được

### Triệu chứng (Symptoms)
- Màn hình Live View hiện thông báo lỗi: `Failed to start camera: ...` hoặc `SOURCE_UNREADABLE`.
- Biểu tượng camera trên giao diện chuyển sang màu xám/đỏ với trạng thái `ERROR`.
- Không có hình ảnh hiển thị, bộ đếm FPS chỉ số 0.0.

### Nguyên nhân có thể (Possible Causes)
1. Địa chỉ URL luồng RTSP / HLS bị sai cú pháp, sai IP hoặc sai thông tin đăng nhập (Username/Password).
2. Thiết bị camera IP bị mất nguồn hoặc cổng mạng RTSP (mặc định 554) bị chặn bởi Firewall.
3. Luồng YouTube Live đã kết thúc, bị xóa hoặc bị YouTube yêu cầu xác minh danh tính bot (HTTP 429 / Bot Challenge).
4. File video cục bộ không tồn tại trên đường dẫn đĩa cứng.

### Cách kiểm tra (How to Check)
- Chạy probe kiểm tra kết nối độc lập:
  ```powershell
  python -c "from src.cameras.probe import probe; print(probe('rtsp', 'rtsp://admin:pass@192.168.1.100:554/live'))"
  ```
- Xem log chi tiết của `CameraManager`:
  ```powershell
  Get-Content .datt-runtime/backend.log | Select-String "CameraManager Error|DATT-STREAM STATE CHANGE"
  ```

### Cách khắc phục (How to Fix)
- Nếu là camera IP/RTSP: Dùng phần mềm VLC Media Player mở URL mạng để kiểm tra xem camera có phát hình được không.
- Nếu là luồng YouTube: Cập nhật file cookies Netscape hợp lệ và khai báo biến môi trường:
  ```dotenv
  YTDLP_COOKIE_FILE=configs/cookies.txt
  ```
- Thử kết nối camera qua nút **"Kiểm tra kết nối"** trong màn hình Quản lý Camera để xem mã lỗi chi tiết.

---

## 2. Camera đang chạy bị mất luồng (Stream Dropout)

### Triệu chứng (Symptoms)
- Camera đang hiển thị bình thường thì video bị đứng hình (freeze), sau đó hiện thông báo:
  `Stream delay detected: no new frame for >5s` hoặc `Stream timeout: no frame received for >15s`.

### Nguyên nhân có thể (Possible Causes)
1. Mạng chập chờn, rớt gói tin trên đường truyền Wi-Fi hoặc Internet kết nối tới camera.
2. Máy chủ camera bị quá tải bộ giải mã và ngắt luồng.
3. YouTube Live bị ngắt quãng tín hiệu phát sóng từ phía người phát.

### Cách kiểm tra (How to Check)
- Kiểm tra số lượng khung hình lỗi liên tiếp trong log:
  ```powershell
  Get-Content .datt-runtime/backend.log | Select-String "consecutive frame read failures"
  ```
- Kiểm tra chỉ số `buffer_age_ms` và `last_frame_age` qua endpoint `/telemetry`.

### Cách khắc phục (How to Fix)
- Hệ thống có cơ chế tự động kết nối lại (`STREAM_READ_FAILURE_THRESHOLD = 10`). Chờ 10-15 giây để `CameraReader` kích hoạt luồng kết nối mới.
- Nếu camera vẫn không hồi phục, bấm nút **"Thử kết nối lại"** trên màn hình lỗi để ép buộc khởi tạo lại tiến trình FFmpeg.

---

## 3. Video bị giật lag và độ trễ cao (Video Lag / High Latency)

### Triệu chứng (Symptoms)
- Video hiển thị trên trình duyệt bị trễ từ 5 đến 10 giây so với thực tế bên ngoài.
- Bảng HUD báo `Pipeline latency` tăng cao (> 200 ms).

### Nguyên nhân có thể (Possible Causes)
1. Tốc độ đọc của trình duyệt chậm hơn tốc độ đẩy khung hình, gây tích lũy bộ đệm MJPEG trong socket TCP.
2. Tiến trình suy luận AI bị quá tải tài nguyên CPU/GPU.
3. Trình duyệt bị nghẽn phần cứng (Hardware Acceleration bị tắt).

### Cách kiểm tra (How to Check)
- Xem chỉ số độ trễ các công đoạn (Stage Timing) trong log:
  ```powershell
  Get-Content .datt-runtime/backend.log | Select-String "STAGE_TIMING" -Tail 5
  ```
  *Phân tích mẫu log:* `read=... yolo=... bt=... face[...] plate[...] render=...` để xác định công đoạn nào đang chiếm nhiều thời gian nhất.

### Cách khắc phục (How to Fix)
- Bật tính năng **Hardware Acceleration** trong cài đặt trình duyệt Web (Chrome: *Settings -> System -> Use graphics acceleration when available*).
- Sử dụng kênh truyền luồng Canvas đồng bộ `/frame_stream` thay cho thẻ `<img>` MJPEG thông thường.
- Giảm độ phân giải suy luận YOLO xuống 640x640 bằng cách khởi động lại với tham số `--img-size 640`.

---

## 4. Tốc độ xử lý FPS thấp (Low FPS)

### Triệu chứng (Symptoms)
- `Processing FPS` chỉ đạt dưới 10-15 FPS mặc dù camera gửi luồng 30 FPS.

### Nguyên nhân có thể (Possible Causes)
1. Hệ thống đang chạy ở chế độ CPU Fallback do chưa cài đặt driver CUDA hoặc thư viện PyTorch bản GPU.
2. Chạy quá nhiều tác vụ OCR và Face Alignment trên cùng một luồng.
3. Kích thước ảnh inference đặt ở mức tối đa (960x960) trên phần cứng hạn chế.

### Cách kiểm tra (How to Check)
- Kiểm tra thiết bị suy luận đang sử dụng:
  ```powershell
  python scripts/datt.py gpu-check
  ```
- Xem chỉ số `device` và `gpu_name` trong `/telemetry`. Nếu trả về `CPU` thay vì `CUDA`, hệ thống đang chạy không có bộ tăng tốc phần cứng.

### Cách khắc phục (How to Fix)
- Cài đặt PyTorch hỗ trợ CUDA 12.1:
  ```powershell
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
  ```
- Đảm bảo biến `DEVICE=cuda:0` và `HALF=True` trong `config.py`.

---

## 5. GPU không hoạt động / Tự động chuyển sang CPU

### Triệu chứng (Symptoms)
- Log khởi động báo: `CUDA unavailable, falling back to CPU` hoặc `Torch not compiled with CUDA enabled`.

### Nguyên nhân có thể (Possible Causes)
1. Chưa cài đặt driver NVIDIA chính xác hoặc phiên bản driver quá cũ (< 525.xx).
2. Môi trường ảo (venv) cài đặt nhầm gói `torch` bản CPU mặc định từ PyPI.
3. CUDA Toolkit và phiên bản driver không khớp nhau.

### Cách kiểm tra (How to Check)
Chạy script kiểm tra trong môi trường ảo:
```powershell
python -c "import torch; print('CUDA Available:', torch.cuda.is_available()); print('Device Count:', torch.cuda.device_count()); print('Device Name:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')"
```

### Cách khắc phục (How to Fix)
- Gỡ bỏ bản torch hiện tại: `pip uninstall -y torch torchvision`
- Cài đặt lại bản GPU:
  ```powershell
  pip install torch torchvision --index-url https://download.pytorch.org/whl/cu121
  ```
- Cài đặt `onnxruntime-gpu`:
  ```powershell
  pip uninstall -y onnxruntime
  pip install onnxruntime-gpu>=1.18.0
  ```

---

## 6. Khuôn mặt không được phát hiện (Face Not Detected)

### Triệu chứng (Symptoms)
- Người đi qua camera nhưng trên đầu không xuất hiện khung nhận diện khuôn mặt hoặc nhãn luôn là `WAIT_FOR_BETTER_FACE`.

### Nguyên nhân có thể (Possible Causes)
1. Góc quay camera quá cao hoặc khoảng cách quá xa khiến khuôn mặt có kích thước dưới 32 pixel.
2. Người đi bộ cúi đầu, đeo khẩu trang hoặc quay lưng lại với ống kính.
3. Môi trường thiếu sáng nghiêm trọng hoặc ngược sáng mạnh (Backlit).

### Cách kiểm tra (How to Check)
- Xem chẩn đoán nhận diện khuôn mặt trong log:
  ```powershell
  Get-Content .datt-runtime/backend.log | Select-String "FACE_UPSCALE|LANDMARK" -Tail 10
  ```

### Cách khắc phục (How to Fix)
- Điều chỉnh lại góc nghiêng của camera giám sát (khuyến nghị góc chúc từ trên xuống không quá 30 độ).
- Đảm bảo đối tượng đi bộ hướng mặt về phía ống kính.
- Hệ thống đã tích hợp sẵn cơ chế **Two-pass SCRFD Adaptive Upscale (1.5x - 4x)**, nhưng khuôn mặt vẫn cần đạt độ sắc nét tối thiểu (không bị mờ chuyển động - motion blur).

---

## 7. Khuôn mặt có phát hiện nhưng không nhận diện được mục tiêu

### Triệu chứng (Symptoms)
- Hộp bao khuôn mặt hiển thị nhãn `CHECKING` hoặc `UNKNOWN`, không hiển thị tên mục tiêu mặc dù người đó đã được đăng ký trong Face Watchlist.

### Nguyên nhân có thể (Possible Causes)
1. Ngưỡng nhận diện (`face_threshold`) của mục tiêu đặt quá cao (ví dụ: 0.70 - 0.80).
2. Ảnh chân dung lúc đăng ký mục tiêu chụp ở góc độ, ánh sáng hoặc độ tuổi quá khác biệt so với hình ảnh thực tế từ camera.
3. Mục tiêu chưa được tích chọn kích hoạt (`is_selected = False`).

### Cách kiểm tra (How to Check)
- Truy cập endpoint `/api/targets` để kiểm tra trường `is_selected` và `face_threshold` của đối tượng.
- Xem điểm tương đồng Cosine thực tế đo được trong log:
  ```powershell
  Get-Content .datt-runtime/backend.log | Select-String "TargetMatcher: best_sim=" -Tail 10
  ```

### Cách khắc phục (How to Fix)
- Mở Face Watchlist trên Web UI, hạ ngưỡng nhận diện của đối tượng từ `0.45` xuống `0.40` hoặc `0.38`.
- Bổ sung thêm ảnh mẫu chất lượng cao, chụp thẳng mặt, độ nét cao vào hồ sơ mục tiêu.

---

## 8. Nhận diện sai khuôn mặt (False Positive Match)

### Triệu chứng (Symptoms)
- Người lạ đi qua nhưng hệ thống lại báo khớp với mục tiêu trong Watchlist (`FACE_MATCH`).

### Nguyên nhân có thể (Possible Causes)
1. Ngưỡng `face_threshold` đặt quá thấp (ví dụ: < 0.35).
2. Ảnh đăng ký mục tiêu bị mờ, khiến vector đặc trưng trích xuất bị suy biến về tâm phân phối.

### Cách kiểm tra (How to Check)
- Xem tỷ lệ tương đồng đo được trong sự kiện: Nếu điểm tương đồng chỉ đạt 0.36 - 0.42 nhưng ngưỡng đặt là 0.35 thì hệ thống sẽ nhận diện nhầm.

### Cách khắc phục (How to Fix)
- Nâng ngưỡng nhận diện của đối tượng đó lên `0.50` hoặc `0.55` để thắt chặt điều kiện so khớp.
- Xóa mục tiêu cũ và đăng ký lại bằng ảnh chân dung có độ phân giải cao và độ sắc nét tốt.

---

## 9. Không tạo sự kiện trong Event Center khi có đối tượng đi qua

### Triệu chứng (Symptoms)
- Trên màn hình Live View nhìn thấy nhãn nhận diện khớp `FACE_MATCH` hoặc biển số `CONFIRMED`, nhưng mở Event Center không thấy bản ghi nào xuất hiện.

### Nguyên nhân có thể (Possible Causes)
1. Đối tượng xe chưa hoàn tất lượt di chuyển (chưa rời khỏi khung hình > 3 giây).
2. Đối tượng xe không khớp với bất kỳ biển số nào có trạng thái `active` trong `VehicleWatchlist`.
3. Database Worker bị nghẽn hoặc gặp lỗi kết nối cơ sở dữ liệu.

### Cách kiểm tra (How to Check)
- Kiểm tra log của Database Worker:
  ```powershell
  Get-Content .datt-runtime/backend.log | Select-String "DBWorker" -Tail 20
  ```
- Kiểm tra độ sâu hàng đợi lưu trữ: nếu `queue_depth` tăng liên tục mà không giảm, tiến trình ghi database đang bị treo.

### Cách khắc phục (How to Fix)
- Đối với xe: Hệ thống chỉ ghi nhận sự kiện xe vào bảng khi xe đã kết thúc hành trình qua camera (rời khỏi khung hình) để thu thập đầy đủ thời lượng lưu thông (`duration_ms`).
- Đảm bảo biển số xe cần theo dõi đã được thêm vào **Vehicle Watchlist** với trạng thái `active`.

---

## 10. Sự kiện bị ghi nhận trùng lặp (Duplicate Events)

### Triệu chứng (Symptoms)
- Cùng một người hoặc một chiếc xe đi qua một lần nhưng sinh ra hàng chục sự kiện liên tiếp trong Event Center.

### Nguyên nhân có thể (Possible Causes)
1. Bộ theo dõi ByteTrack bị đứt vết (Track ID switching) liên tục do đối tượng bị che khuất tạm thời hoặc giật khung hình.
2. Cơ chế khóa trùng lặp bị tắt hoặc reset bất thường.

### Cách kiểm tra (How to Check)
- Xem danh sách Track ID xuất hiện trong Event Center: Nếu cùng một người nhưng sinh ra các sự kiện với Track ID khác nhau (ví dụ: Track 12, Track 15, Track 18), nguyên nhân do mất dấu theo dõi (Tracking Fragmentation).

### Cách khắc phục (How to Fix)
- Tăng tham số `LOST_TRACK_BUFFER` trong `config.py` từ 30 lên 60 khung hình để ByteTrack giữ vết đối tượng lâu hơn khi bị che khuất.
- Cải thiện chất lượng đường truyền camera để tránh bị tụt khung hình (drop frames).

---

## 11. Không đọc được biển số xe (OCR Failure)

### Triệu chứng (Symptoms)
- Xe đi qua nhưng nhãn luôn giữ nguyên định dạng `CAR-12 | C-12`, không hiển thị biển số. Trạng thái trong hệ thống là `SEARCHING`.

### Nguyên nhân có thể (Possible Causes)
1. Xe di chuyển quá nhanh khiến biển số bị mờ nhòe do tốc độ màn trập camera thấp (Motion Blur).
2. Biển số xe bị cong vênh, dính bùn đất hoặc bị lốp dự phòng / giá chở hàng che khuất.
3. Kích thước tấm biển số trong ảnh crop nhỏ hơn 15x8 pixel.

### Cách kiểm tra (How to Check)
- Kiểm tra các mẫu ảnh chẩn đoán được lưu tại thư mục `scratch/plate_debug/`:
  Xem các file ảnh crop để đánh giá độ rõ nét của biển số xe.
- Kiểm tra log EasyOCR:
  ```powershell
  Get-Content .datt-runtime/backend.log | Select-String "PLATE_CONFIRM|PLATE_CONFLICT" -Tail 10
  ```

### Cách khắc phục (How to Fix)
- Tăng tốc độ màn trập (Shutter Speed) của camera giám sát (khuyến nghị tối thiểu 1/500s đối với làn xe chạy).
- Hạ thấp góc đặt camera hướng thẳng vào đầu hoặc đuôi xe thay vì góc nhìn chéo từ trên vỉa hè.

---

## 12. OCR đọc sai ký tự biển số (OCR Misread)

### Triệu chứng (Symptoms)
- Biển số xe thực tế là `29A-123.45`, nhưng hệ thống nhận diện thành `29A-128.45` (nhầm số 3 thành số 8) hoặc `29A-I23.45` (nhầm số 1 thành chữ I).

### Nguyên nhân có thể (Possible Causes)
1. Độ tương phản của biển số kém hoặc có bóng đổ cắt ngang các ký tự.
2. Các ký tự quang học dễ gây nhầm lẫn trong font chữ biển số (0/O, 1/I, 8/B, 3/8).

### Cách kiểm tra (How to Check)
- Xem bảng bỏ phiếu trong log:
  ```powershell
  Get-Content .datt-runtime/backend.log | Select-String "PLATE_CONFLICT"
  ```

### Cách khắc phục (How to Fix)
- Hệ thống áp dụng nguyên tắc **Tuyệt đối không tự suy đoán ký tự** (`normalize_plate_text` chỉ bỏ dấu phân cách, không tự hoán đổi 0/O hay 1/I).
- Cơ chế đồng thuận `PLATE_CONSENSUS_RATIO = 0.75` yêu cầu >= 75% các frame đọc khớp hoàn toàn chuỗi. Đảm bảo xe đi qua vùng quan sát đủ thời gian (ít nhất 0.5 - 1.0 giây) để hệ thống tích lũy đủ các khung hình sắc nét nhất.

---

## 13. Biển số có nhưng không match Watchlist

### Triệu chứng (Symptoms)
- Nhãn xe đã hiển thị biển số xác nhận (ví dụ: `CAR-46 | 29K-104.25`), nhưng trong bảng Vehicle Watchlist mục này không tăng `Số lần phát hiện` và không sinh sự kiện khớp Watchlist.

### Nguyên nhân có thể (Possible Causes)
1. Bản ghi biển số trong `Vehicle Watchlist` đang ở trạng thái `disabled` (tạm ngưng).
2. Chuỗi ký tự biển số đăng ký trong Watchlist bị thừa ký tự đặc biệt hoặc gõ nhầm.

### Cách kiểm tra (How to Check)
- Chạy câu lệnh SQL kiểm tra trạng thái biển số trong database:
  ```sql
  SELECT id, plate_number, status FROM vehicle_watchlists WHERE plate_number = '29K10425';
  ```
- Kiểm tra xem kết quả `status` có phải là `active` không.

### Cách khắc phục (How to Fix)
- Mở danh sách Vehicle Watchlist, kiểm tra và chuyển trạng thái phương tiện sang `Active`.
- Hệ thống tự động chuẩn hóa biển số về dạng chữ in hoa không dấu (`29K-104.25` -> `29K10425`). Đảm bảo chuỗi ký tự chữ và số hoàn toàn trùng khớp.

---

## 14. Lỗi kết nối Cơ sở dữ liệu (Database Connection Error)

### Triệu chứng (Symptoms)
- Backend không khởi động được, báo lỗi: `OperationalError: connection to server at "127.0.0.1", port 5432 failed`.
- Các API trả về mã lỗi `HTTP 503: DATABASE_UNAVAILABLE`.

### Nguyên nhân có thể (Possible Causes)
1. Dịch vụ Docker container PostgreSQL chưa được bật.
2. Thông tin đăng nhập trong `DATT_DATABASE_URL` bị sai mật khẩu hoặc sai tên database.
3. Supabase hết hạn ngạch kết nối (Connection Limit Exceeded).

### Cách kiểm tra (How to Check)
- Kiểm tra trạng thái container Docker:
  ```bash
  docker compose ps
  ```
- Thử kết nối trực tiếp bằng công cụ CLI:
  ```powershell
  python scripts/datt.py db-check
  ```

### Cách khắc phục (How to Fix)
- Khởi động lại dịch vụ PostgreSQL:
  ```bash
  docker compose up -d postgres
  ```
- Kiểm tra chuỗi kết nối trong file `.env` đảm bảo cú pháp:
  `postgresql://<user>:<password>@<host>:<port>/<dbname>`

---

## 15. Lỗi Migration / Lệch phiên bản lược đồ Alembic

### Triệu chứng (Symptoms)
- Chạy lệnh `python scripts/datt.py doctor` báo lỗi:
  `alembic_revision=unknown` hoặc `check_error=migration_head_mismatch`.

### Nguyên nhân có thể (Possible Causes)
- Database mới được tạo nhưng chưa áp dụng các script migration trong thư mục `src/db/migrations/versions/`.

### Cách kiểm tra (How to Check)
- Kiểm tra phiên bản hiện tại trong database:
  ```sql
  SELECT * FROM alembic_version;
  ```

### Cách khắc phục (How to Fix)
- Chạy lệnh nâng cấp lược đồ lên phiên bản mới nhất:
  ```powershell
  alembic -c src/db/alembic.ini upgrade head
  ```

---

## 16. Lỗi Ràng buộc Khóa ngoại (Foreign Key Constraint Error)

### Triệu chứng (Symptoms)
- Thao tác xóa camera hoặc xóa video bị từ chối với mã lỗi `HTTP 409: CAMERA_REFERENCED_OR_CONFLICT`.

### Nguyên nhân có thể (Possible Causes)
- Bảng `cameras` và `video_sources` có quan hệ ràng buộc `ondelete="RESTRICT"` với bảng `detection_events` và `vehicle_passages`. Hệ thống ngăn chặn việc xóa cứng các bản ghi đang được tham chiếu để bảo toàn dữ liệu lịch sử bằng chứng.

### Cách kiểm tra (How to Check)
- Xem log chi tiết lỗi SQLAlchemy:
  ```powershell
  Get-Content .datt-runtime/backend.log | Select-String "IntegrityError"
  ```

### Cách khắc phục (How to Fix)
- Thay vì xóa bản ghi, chuyển trạng thái của Camera sang `disabled` hoặc `status='inactive'`.

---

## 17. Thông báo cảnh báo không được tạo (Notification Missing)

### Triệu chứng (Symptoms)
- Sự kiện Watchlist Match xuất hiện trong Event Center, nhưng trong bảng Alerts không có thông báo tương ứng.

### Nguyên nhân có thể (Possible Causes)
1. Biến môi trường cấu hình Email bị thiếu hoặc không hợp lệ.
2. Đang trong thời gian Cooldown (300 giây).

### Cách kiểm tra (How to Check)
- Kiểm tra log của tiến trình Notification:
  ```powershell
  Get-Content .datt-runtime/backend.log | Select-String "NOTIFICATIONS"
  ```
  Nếu xuất hiện `CONFIGURED=false`, hệ thống chưa nhận diện được cấu hình SMTP hợp lệ.

### Cách khắc phục (How to Fix)
- Điền đầy đủ các biến môi trường bắt buộc trong `.env`:
  `DATT_EMAIL_HOST`, `DATT_EMAIL_PORT`, `DATT_EMAIL_USERNAME`, `DATT_EMAIL_PASSWORD`, `DATT_EMAIL_TO`.
- Khởi động lại dịch vụ backend.

---

## 18. Email ở trạng thái PENDING kéo dài không gửi đi

### Triệu chứng (Symptoms)
- Trong Alert Center, các bản ghi cảnh báo luôn hiển thị nhãn màu vàng `PENDING` và không chuyển sang `SENT`.

### Nguyên nhân có thể (Possible Causes)
1. Luồng `NotificationEmailWorker` chưa được khởi động (ví dụ: chạy ở chế độ kiểm thử `DATT_EVENT_AUDIT_ONLY=1`).
2. Tiến trình gửi mail bị treo socket mạng khi kết nối tới máy chủ SMTP.

### Cách kiểm tra (How to Check)
- Kiểm tra danh sách các thread đang hoạt động:
  Đảm bảo thread `NotificationEmailWorker` đang ở trạng thái `alive`.

### Cách khắc phục (How to Fix)
- Kiểm tra thông số kết nối tường lửa chiều ra (Outbound) tới cổng 587 hoặc 465 của máy chủ mail.
- Khởi động lại dịch vụ DATT.

---

## 19. Email ở trạng thái FAILED (Gửi thất bại)

### Triệu chứng (Symptoms)
- Bản ghi trong Alert Center hiển thị nhãn màu đỏ `FAILED` kèm mã lỗi: `smtp_authentication`, `smtp_timeout`, `invalid_recipient`, hoặc `smtp_connection`.

### Nguyên nhân có thể & Cách khắc phục theo từng mã lỗi:

| Mã lỗi hiển thị | Nguyên nhân gốc rễ | Cách khắc phục |
|---|---|---|
| `smtp_authentication` | Sai tài khoản hoặc sai mật khẩu SMTP. Đối với Gmail, dùng mật khẩu thông thường thay vì App Password. | Tạo **App Password 16 ký tự** trong phần Bảo mật tài khoản Google và dán vào `DATT_EMAIL_PASSWORD`. |
| `smtp_timeout` | Máy chủ SMTP không phản hồi trong vòng 15 giây. | Kiểm tra đường truyền Internet hoặc chuyển cổng kết nối giữa 587 (`starttls`) và 465 (`ssl`). |
| `smtp_connection` | Không thể thiết lập kết nối TCP tới `DATT_EMAIL_HOST`. | Kiểm tra DNS hoặc địa chỉ host máy chủ SMTP. |
| `invalid_recipient` | Địa chỉ email người nhận (`DATT_EMAIL_TO`) sai định dạng hoặc bị máy chủ mail từ chối. | Kiểm tra lại danh sách email người nhận trong `.env`. |
| `CONFIGURED=false` | Thiếu một trong các biến cấu hình bắt buộc. | Điền đủ các biến bắt buộc trong file `.env`. |

---

## 20. Giao diện Frontend không kết nối được Backend API

### Triệu chứng (Symptoms)
- Trình duyệt mở được giao diện nhưng các bảng số liệu hiện `Không thể tải dữ liệu: Lỗi kết nối tới máy chủ API`.

### Nguyên nhân có thể (Possible Causes)
1. Máy chủ Uvicorn bị crash hoặc chưa được bật.
2. Trình duyệt chặn kết nối do chính sách Mixed Content (khi mở Web qua HTTPS nhưng API gọi HTTP).
3. CORS bị chặn.

### Cách kiểm tra (How to Check)
- Mở Developer Tools trên trình duyệt (F12) -> Chọn tab **Console** và **Network** để xem mã lỗi của các request gọi tới `/api/telemetry` hoặc `/api/cameras`.

### Cách khắc phục (How to Fix)
- Đảm bảo tiến trình backend đang lắng nghe trên cổng 8501:
  ```powershell
  python scripts/datt.py status
  ```
- Nếu dùng qua domain có HTTPS, cấu hình reverse proxy chuyển tiếp header `X-Forwarded-Proto https`.

---

## 21. Lỗi API 4xx (400, 404, 409, 413)

- **`HTTP 400 Bad Request`:**
  - *Nguyên nhân:* Tham số yêu cầu không hợp lệ (ví dụ: `INVALID_NAME`, `INVALID_SOURCE`, `INVALID_PLATE`).
  - *Khắc phục:* Kiểm tra dữ liệu đầu vào theo đúng đặc tả của API.
- **`HTTP 404 Not Found`:**
  - *Nguyên nhân:* Đối tượng ID không tồn tại (`CAMERA_NOT_FOUND`, `EVENT_NOT_FOUND`, `ALERT_NOT_FOUND`).
  - *Khắc phục:* Kiểm tra lại chuỗi UUID của đối tượng cần truy vấn.
- **`HTTP 409 Conflict`:**
  - *Nguyên nhân:* `CAMERA_ACTIVE_STOP_FIRST` (Cố gắng xóa/sửa camera đang chạy) hoặc `CAMERA_ALREADY_ACTIVE` (Camera đã được kích hoạt ở luồng khác).
  - *Khắc phục:* Dừng camera đang chạy trước khi thực hiện thao tác xóa hoặc chuyển đổi.
- **`HTTP 413 Payload Too Large`:**
  - *Nguyên nhân:* File ảnh upload vượt quá giới hạn 10 MB (`EVIDENCE_TOO_LARGE`).
  - *Khắc phục:* Nén giảm kích thước ảnh trước khi tải lên.

---

## 22. Lỗi API 5xx (500, 503)

- **`HTTP 503 Service Unavailable` (`DATABASE_UNAVAILABLE`):**
  - *Nguyên nhân:* Kết nối cơ sở dữ liệu bị ngắt hoặc pooler quá tải.
  - *Khắc phục:* Kiểm tra container PostgreSQL hoặc trạng thái máy chủ Supabase.
- **`HTTP 503 Service Unavailable` (`THUMBNAIL_UNAVAILABLE` / `EVIDENCE_UNAVAILABLE`):**
  - *Nguyên nhân:* Không tìm thấy file ảnh bằng chứng trên hệ thống Storage hoặc Storage provider bị lỗi mạng.
  - *Khắc phục:* Kiểm tra cấu hình `DATT_STORAGE_BACKEND` và tính toàn vẹn của thư mục `data/events/`.

---

## 23. Giao diện xem luồng (Stream View) không có Sidebar hoặc cần quay lại trang quản lý

### Triệu chứng (Symptoms)
- Khi nhấp vào xem camera từ Dashboard hoặc Camera Management, thanh Sidebar màu trắng biến mất, người dùng không thấy menu điều hướng sang trang khác.

### Nguyên nhân & Thiết kế (Design Behavior)
- Đây là **hành vi thiết kế có chủ đích (Intentional Design)**: Giao diện xem luồng camera (Camera Stream View) được tối giản hóa tối đa để dành 100% không gian cho video giám sát và loại bỏ các thành phần gây xao nhãng.

### Cách khắc phục / Thao tác (How to Fix)
- Để quay trở về trang quản lý có đầy đủ thanh Sidebar dọc, người dùng chỉ cần nhấp vào nút **"← Quay lại"** (Back button) nằm ở góc trên bên trái của thanh tiêu đề luồng video.
- Không cần phải sử dụng nút Back của trình duyệt.

---

## 24. Cảnh báo Toast không xuất hiện hoặc bị che khuất trong chế độ Toàn màn hình

### Triệu chứng (Symptoms)
- Khi ở chế độ Fullscreen, khi có cảnh báo email mới hoặc thông báo Watchlist Match, màn hình không thấy Toast xuất hiện ở góc trên bên phải.

### Nguyên nhân có thể (Possible Causes)
1. Cơ chế bảo mật Fullscreen API của một số trình duyệt (Firefox, Safari) cô lập phần tử được yêu cầu toàn màn hình (`#streamViewport`), che khuất các phần tử nằm ngoài cây DOM (như `body > #globalToastContainer`).
2. Trình duyệt chặn quyền truy cập Fullscreen nếu thao tác không xuất phát từ tương tác người dùng trực tiếp (User Gesture).

### Cách kiểm tra & Khắc phục (How to Fix)
- Trong mã nguồn mới [app.js](../src/ui/static/app.js#L5080-L5140), hệ thống đã cài đặt cơ chế **Dynamic Toast Reparenting**:
  - Khi sự kiện `fullscreenchange` kích hoạt, container `#globalToastContainer` sẽ tự động được di chuyển vào bên trong `#streamViewport`.
  - Nếu gặp hiện tượng bị che, hãy làm mới (F5) trang trình duyệt để nạp mã nguồn JavaScript mới nhất.
  - Đảm bảo người dùng nhấp trực tiếp vào nút **"Toàn màn hình"** (không gọi script tự động).

---

## 25. Tùy chọn Màu sắc Giao diện (Theme Accent Color) bị reset về mặc định

### Triệu chứng (Symptoms)
- Người dùng đã chọn màu Xanh lá/Tím/Cam/Đỏ, nhưng sau khi đóng trình duyệt mở lại thì giao diện quay về màu Xanh dương mặc định.

### Nguyên nhân có thể (Possible Causes)
1. Trình duyệt đang chạy ở chế độ Ẩn danh (Incognito / Private Browsing Mode) - chế độ này xóa sạch bộ nhớ tạm sau khi đóng tab.
2. Tiện ích chặn quảng cáo (AdBlock) hoặc chính sách bảo mật nội bộ chặn tính năng lưu trữ `localStorage`.

### Cách khắc phục (How to Fix)
- Sử dụng trình duyệt ở chế độ thông thường.
- Mở DevTools (F12) -> Console, kiểm tra lệnh:
  ```javascript
  localStorage.setItem("datt_accent_color", "purple");
  console.log(localStorage.getItem("datt_accent_color"));
  ```
- Nếu hiển thị `"purple"`, cấu hình đã lưu thành công.

---

## 26. Bộ đếm Người và Xe trên thanh trạng thái Fullscreen hiển thị 0 hoặc không cập nhật

### Triệu chứng (Symptoms)
- Khi vào chế độ Toàn màn hình, thanh trạng thái xám phía trên hiển thị `NGƯỜI: 0 | XE: 0` mặc dù trên video có người hoặc xe đang di chuyển.

### Nguyên nhân có thể (Possible Causes)
1. Luồng camera đang kết nối ở chế độ ảnh thô MJPEG thông thường (`/video_feed`) thay vì luồng nhị phân đồng bộ (`/frame_stream`).
2. Thuật toán ByteTrack chưa khởi tạo track (đối tượng mới xuất hiện dưới 2 khung hình, chưa được cấp Track ID).
3. Backend AI đang chạy ở chế độ Headless không kết nối telemetry.

### Cách kiểm tra & Khắc phục (How to Fix)
- Kiểm tra header gói khung hình trong DevTools Network tab: Gói tin phải có header `X-Frame-Telemetry` chứa JSON `{ people_count: ..., car_count: ... }`.
- Đảm bảo máy chủ AI `python src/main.py` đang hoạt động ổn định và GPU xử lý >= 20 FPS. Số đếm sẽ lập tức hiển thị chính xác theo số active tracks thời gian thực.

