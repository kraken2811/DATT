# HƯỚNG DẪN SỬ DỤNG HỆ THỐNG DATT (USER GUIDE)
**DATT — Hệ thống Giám sát Thị giác Thông minh (AI Vision Monitoring & Security System)**

---

## MỤC LỤC

1. [Giới thiệu hệ thống](#1-giới-thiệu-hệ-thống)
2. [Hệ thống dùng để làm gì](#2-hệ-thống-dùng-để-làm-gì)
3. [Các chức năng chính](#3-các-chức-năng-chính)
4. [Thiết kế Giao diện Doanh nghiệp, Điều hướng & Tùy biến Theme](#4-thiết-kế-giao-diện-doanh-nghiệp-điều-hướng--tùy-biến-theme)
   - 4.1. Cấu trúc Design System Chuẩn Enterprise
   - 4.2. Thanh Sidebar Trắng & Nút Settings Bánh Răng ở cuối
   - 4.3. Chức năng Đổi Màu Chủ Đạo Giao diện (Theme Accent Color)
5. [Giao diện Giám sát Trực tiếp (Camera Stream View & Fullscreen Monitoring)](#5-giao-diện-giám-sát-trực-tiếp-camera-stream-view--fullscreen-monitoring)
6. [Quản lý Camera (Camera Management)](#6-quản-lý-camera-camera-management)
7. [Thêm Camera mới](#7-thêm-camera-mới)
8. [Chỉnh sửa thông tin Camera](#8-chỉnh-sửa-thông-tin-camera)
9. [Xóa Camera](#9-xóa-camera)
10. [Bật / Tắt trạng thái Camera](#10-bật--tắt-trạng-thái-camera)
11. [Xem và chuyển đổi luồng Camera](#11-xem-và-chuyển-đổi-luồng-camera)
12. [Danh sách theo dõi Khuôn mặt (Face Watchlist)](#12-danh-sách-theo-dõi-khuôn-mặt-face-watchlist)
13. [Thêm đối tượng theo dõi Khuôn mặt](#13-thêm-đối-tượng-theo-dõi-khuôn-mặt)
14. [Upload ảnh và Kiểm tra đặc trưng khuôn mặt](#14-upload-ảnh-và-kiểm-tra-đặc-trưng-khuôn-mặt)
15. [Danh sách theo dõi Phương tiện (Vehicle Watchlist)](#15-danh-sách-theo-dõi-phương-tiện-vehicle-watchlist)
16. [Thêm biển số xe vào Watchlist](#16-thêm-biển-số-xe-vào-watchlist)
17. [Sửa và Xóa biển số xe](#17-sửa-và-xóa-biển-số-xe)
18. [Trung tâm Sự kiện (Event Center)](#18-trung-tâm-sự-kiện-event-center)
19. [Sự kiện Biển số & Nhận diện Đối tượng (Plate & Face Events)](#19-sự-kiện-biển-số--nhận-diện-đối-tượng-plate--face-events)
20. [Tìm kiếm và Lọc sự kiện](#20-tìm-kiếm-và-lọc-sự-kiện)
21. [Hệ thống Cảnh báo Toàn cục & Thông báo Email (Global Alert & Toast Notification)](#21-hệ-thống-cảnh-báo-toàn-cục--thông-báo-email-global-alert--toast-notification)
   - 21.1. Cảnh báo Thông báo Toàn cục (Global Toast 5 Giây)
   - 21.2. Cơ chế Transactional Outbox & Trạng thái Email
22. [Xem trạng thái gửi Notification và Lịch sử cảnh báo](#22-xem-trạng-thái-gửi-notification-và-lịch-sử-cảnh-báo)
23. [Các lỗi thường gặp đối với người dùng](#23-các-lỗi-thường-gặp-đối-với-người-dùng)
24. [Câu hỏi thường gặp (FAQ)](#24-câu-hỏi-thường-gặp-faq)

---

## 1. Giới thiệu hệ thống

**DATT** (Deep Analytics Tracking & Targeting) là hệ thống giám sát thị giác máy tính toàn diện, tích hợp trí tuệ nhân tạo (AI) chạy trên nền tảng FastAPI backend kết hợp mô hình Deep Learning tiên tiến (YOLO11s, ByteTrack, SCRFD, AdaFace, EasyOCR). Hệ thống được thiết kế để xử lý luồng video thời gian thực từ nhiều loại nguồn (RTSP, HLS, YouTube Live, CCTV công cộng, Video MP4 cục bộ) và cung cấp giao diện Web người dùng trực quan, hiện đại, không cần cài đặt phần mềm client phức tạp.

---

## 2. Hệ thống dùng để làm gì

Hệ thống DATT phục vụ các nghiệp vụ an ninh, giám sát trật tự và quản lý phương tiện:
- **Đếm người và phương tiện theo thời gian thực:** Đo lường mật độ người đi bộ và lưu lượng xe cơ giới trong khung hình hoặc trong một vùng giới hạn (ROI Zone).
- **Phát hiện và nhận diện khuôn mặt mục tiêu (Face Watchlist):** Tự động phát hiện khuôn mặt của người đi qua camera, trích xuất vector đặc trưng 512 chiều, so khớp với cơ sở dữ liệu mục tiêu cần theo dõi và tạo sự kiện cảnh báo tức thời.
- **Tự động nhận diện biển số xe (ANPR / LPR):** Định vị biển số, nhận diện ký tự quang học qua mô hình OCR, chuẩn hóa biển số Việt Nam và đối soát tức thì với danh sách xe cần theo dõi (Vehicle Watchlist).
- **Phân loại màu sắc phương tiện:** Tự động trích xuất và phân tích màu sắc nhận diện của xe (đen, trắng, bạc, đỏ, xanh, vàng, v.v.).
- **Ghi nhận sự kiện nghiệp vụ và lưu trữ bằng chứng:** Ghi lại ảnh bằng chứng (snapshot, crop mặt, crop biển số), thông số độ tin cậy và mốc thời gian UTC chính xác.
- **Phát cảnh báo tự động qua Email:** Gửi thông báo có đính kèm ảnh bằng chứng trực tiếp đến hộp thư người quản lý khi có đối tượng trong danh sách theo dõi xuất hiện.

---

## 3. Các chức năng chính

Bảng tổng hợp các phân hệ chức năng trong hệ thống:

| Phân hệ | Chức năng chính | Trạng thái kỹ thuật |
|---|---|---|
| **Giám sát trực tiếp (Live Stream View)** | Xem luồng video MJPEG độ trễ thấp, không sidebar, không event feed, chế độ toàn màn hình có status bar người/xe | Hoạt động đầy đủ (Full) |
| **Vùng đếm (Zone Mode)** | Bật/tắt chế độ đếm theo đa giác ROI (Counting Zone) thay vì toàn khung hình | Hoạt động đầy đủ (Full) |
| **Quản lý Camera (Camera Management)** | Thêm, sửa, xóa, bật/tắt camera, kiểm tra kết nối (Probe Test), xem ảnh chụp thử (Thumbnail) | Hoạt động đầy đủ (Full) |
| **Nguồn Camera đa dạng** | Hỗ trợ RTSP, HLS (.m3u8), YouTube Live/VOD, Public CCTV (Seattle SDOT, Caltrans), File MP4 upload | Hoạt động đầy đủ (Full) |
| **Face Watchlist** | Đăng ký khuôn mặt mục tiêu, upload ảnh chân dung, kiểm tra góc mặt/chất lượng, bật/tắt theo dõi, xem số lần phát hiện | Hoạt động đầy đủ (Full) |
| **Vehicle Watchlist** | Quản lý biển số xe theo dõi, loại xe, màu xe, chủ sở hữu, ghi chú, xem lịch sử các lần xe xuất hiện | Hoạt động đầy đủ (Full) |
| **Event Center** | Tra cứu hợp nhất sự kiện (Face, Plate, Vehicle, Passage, Crowd/Congestion), bộ lọc đa tiêu chí, tải ảnh bằng chứng | Hoạt động đầy đủ (Full) |
| **Alert Center** | Quản lý outbox cảnh báo email: Trạng thái (PENDING, SENT, FAILED, SUPPRESSED), số lần retry, thông tin lỗi an toàn | Hoạt động đầy đủ (Full) |
| **Global Toast Alerts** | Cảnh báo góc trên bên phải màn hình trên mọi trang (5 giây tự biến mất, nút đóng X, hiển thị cả khi Fullscreen) | Hoạt động đầy đủ (Full) |
| **Tùy biến Giao diện (Theme)** | Chọn 5 gam màu chủ đạo (Xanh dương, Xanh lá, Tím, Cam, Đỏ) qua icon Bánh răng ở đáy Sidebar, lưu localStorage | Hoạt động đầy đủ (Full) |

---

## 4. Thiết kế Giao diện Doanh nghiệp, Điều hướng & Tùy biến Theme

### 4.1. Cấu trúc Design System Chuẩn Enterprise
Giao diện hệ thống DATT được xây dựng theo phong cách **Enterprise Monitoring Dashboard** chuẩn mực:
- **Thanh Sidebar Trắng Dọc (White Sidebar):** Nền trắng `#FFFFFF`, viền mỏng `#E5E7EB`, chữ xám đậm `#374151`, hiệu ứng hover `#F3F4F6`. Sidebar luôn nằm dọc cố định bên trái màn hình trên toàn bộ các trang quản lý.
- **Không gian Làm việc Xám Nhẹ (Light Gray Workspace):** Nền `#F5F6F8`, tạo độ tương phản dịu mắt, tăng khả năng tập trung khi theo dõi màn hình trong thời gian dài.
- **Thẻ Nội Dung Trắng (White Cards):** Nền `#FFFFFF` với đường viền mảnh `#E5E7EB`, bán kính bo góc 6px, đổ bóng siêu nhẹ hoặc không shadow để tránh cảm giác rối mắt.
- **Hệ thống Biểu tượng Monochrome Outline:** Toàn bộ icon được chuẩn hóa sang dạng vector SVG nét mảnh đơn sắc, kích thước 16x16px / 18x18px, hoàn toàn không sử dụng biểu tượng cảm xúc (emoji) hay gradient đa sắc.
- **Quy chuẩn Typography (Phông chữ):** Toàn bộ giao diện sử dụng phông chữ chuẩn `Inter` (với fallback sang hệ thống sans-serif ổn định), hỗ trợ tiếng Việt đầy đủ. Cỡ chữ chuẩn giao diện mặc định là **13px** (Page Title: 20px, Section Title: 16px, Card Title: 14px, UI Default: 13px, Meta/Badge: 12px).

### 4.2. Thanh Sidebar Trắng & Nút Settings Bánh Răng ở cuối
Cấu trúc điều hướng thanh Sidebar bên trái:
```
Sidebar
├── Logo DATT & Tiêu đề Phân hệ
├── Main Navigation (Menu chính)
│   ├── Dashboard (Tổng quan)
│   ├── Quản lý Camera
│   ├── Event Center
│   ├── Face Watchlist
│   ├── Vehicle Watchlist
│   └── Alert Center
│
├── [flex-grow: Khoảng cách giãn tự động]
│
└── Cài đặt & Giao diện (Icon Bánh răng - Settings Gear)
```
- Mục **Settings** không còn nằm trong danh sách navigation chính mà được đưa xuống góc dưới cùng của Sidebar.
- Nút sử dụng biểu tượng Bánh răng (Gear) đơn sắc cùng phong cách outline SVG. Khi rê chuột (hover) hiển thị tooltip "Cài đặt & Giao diện".
- Khi nhấp vào nút Bánh răng, một hộp thoại cài đặt mở ra cho phép người dùng cấu hình giao diện.

### 4.3. Chức năng Đổi Màu Chủ Đạo Giao diện (Theme Accent Color)
Hệ thống cho phép người dùng tùy chỉnh màu nhấn (Accent Color) của giao diện theo sở thích hoặc nhận diện thương hiệu:
- **5 Tùy chọn Màu sắc:**
  - **Xanh dương (Blue - Mặc định):** `#2563EB` (Phong cách Enterprise chuẩn)
  - **Xanh lá (Green):** `#059669`
  - **Tím (Purple):** `#7C3AED`
  - **Cam (Orange):** `#EA580C`
  - **Đỏ (Red):** `#DC2626`
- **Phạm vi áp dụng Accent Color:** Mục menu đang chọn trên Sidebar, Nút bấm chính (Primary Button), Tab đang chọn, Viền focus ô nhập liệu, và các liên kết hành động.
- **Bảo toàn Tuyệt đối Màu Ngữ Nghĩa (Semantic Colors):** Màu chủ đạo **KHÔNG BAO GIỜ** làm thay đổi ý nghĩa của các trạng thái hệ thống:
  - Thành công / Online: Luôn là màu **Xanh lá (Green)**.
  - Cảnh báo / Warning / PENDING: Luôn là màu **Vàng hổ phách (Amber)**.
  - Lỗi / Error / Offline / FAILED: Luôn là màu **Đỏ (Red)**.
  - Thông tin / Info: Luôn là màu **Xanh dương trung tính (Blue)**.
- **Lưu trữ Tự động:** Lựa chọn màu sắc được lưu trữ trực tiếp trong `localStorage` (`datt_accent_color`). Khi người dùng tải lại trang hoặc mở ở tab mới, giao diện vẫn duy trì màu đã chọn mà không bị nhấp nháy.

---

---

## 5. Giao diện Giám sát Trực tiếp (Camera Stream View & Fullscreen Monitoring)

### 5.1. Thiết kế Giao diện Stream View Tối giản (Dedicated Minimal Stream View)
Giao diện xem luồng camera trực tiếp được thiết kế theo phong cách chuyên dụng, tập trung tối đa vào hình ảnh giám sát:
- **KHÔNG CÓ Sidebar:** Khi người dùng nhấn xem camera, thanh Sidebar bên trái và các menu quản lý sẽ được ẩn hoàn toàn để nhường diện tích cho luồng video.
- **Thanh điều hướng tối giản trên cùng (Stream Header Bar):**
  - **Nút "← Quay lại" (Back button):** Cho phép người dùng nhanh chóng quay trở lại trang **Quản lý Camera (Camera Management)** mà không cần nhấn phím Back của trình duyệt.
  - **Thông tin nguồn:** Hiển thị Tên camera đang phát cùng biểu tượng trạng thái phát sóng xanh lục `● LIVE`.
  - **Nút "Toàn màn hình" (Fullscreen):** Nằm ở góc phải với biểu tượng mở rộng monochrome, chuyển ngay sang chế độ giám sát toàn màn hình.
- **Khung video trung tâm (Live Video Canvas):**
  - Luồng video MJPEG độ trễ thấp (`/video_feed`) hoặc bộ dựng Canvas đồng bộ (`/frame_stream` qua [DattFrameStreamParser](../src/ui/static/frame_stream.js#L2-L24)).
  - Video được căn giữa hoàn hảo, duy trì đúng tỷ lệ khung hình (Aspect Ratio), sử dụng `object-fit: contain`, không bị méo hình hoặc kéo dãn.
  - **Bounding Box người & xe:** Hiển thị mã theo dõi ByteTrack, độ tin cậy và nhãn nhận diện khuôn mặt / biển số trực tiếp trên khung hình.
- **ĐÃ BỎ HOÀN TOÀN Event Feed bên dưới video:** Khác với các phiên bản cũ có danh sách sự kiện hiển thị bên dưới làm rối mắt, giao diện mới đã loại bỏ hoàn toàn phần Event Feed khỏi Stream View. Toàn bộ sự kiện vẫn được hệ thống AI tạo và lưu trữ đầy đủ trong cơ sở dữ liệu và hiển thị chi tiết tại **Event Center**.

### 5.2. Chế độ Giám sát Toàn màn hình (Fullscreen Monitoring Mode)
Khi nhấn nút **"Toàn màn hình"** hoặc kích hoạt Fullscreen:
- **Thanh trạng thái giám sát màu xám (Monitoring Status Bar):** Nằm gọn gàng ở cạnh trên cùng với phông chữ chuẩn 13px và biểu tượng monochrome tối giản:
  ```
  ┌──────────────────────────────────────────────────────────┐
  │ CAMERA 01 | LIVE | NGƯỜI: 8 | XE: 3       [Thoát]        │
  ├──────────────────────────────────────────────────────────┤
  │                                                          │
  │                       VIDEO                              │
  │                                                          │
  └──────────────────────────────────────────────────────────┘
  ```
- **Số liệu Thực tế (Real Monitoring Metrics):**
  - **NGƯỜI (People Count):** Số lượng người đang hoạt động đồng thời (Active Person Tracks) trích xuất trực tiếp từ thuật toán ByteTrack (`data.people_count`).
  - **XE (Vehicle Count):** Số lượng phương tiện giao thông đang bám vết (Active Vehicle Tracks) từ thuật toán ByteTrack (`data.car_count`).
  - *Tuyệt đối không dùng dữ liệu ngẫu nhiên hoặc hard-code.*
- **Duy trì luồng mượt mà:** Việc vào và thoát toàn màn hình sử dụng trực tiếp container viewport, không khởi động lại kết nối stream (không reconnect video feed).
- **Thoát toàn màn hình:** Người dùng có thể nhấn nút **"Thoát"** trên thanh trạng thái hoặc bấm phím **ESC** trên bàn phím để trở về giao diện Stream View thông thường.

---

## 6. Quản lý Camera (Camera Management)

### 6.1. Mục đích
Quản lý tập trung toàn bộ danh sách các điểm đặt camera giám sát của cơ quan, doanh nghiệp; cấu hình địa chỉ luồng mạng, vị trí lắp đặt và kiểm soát trạng thái kích hoạt.

### 6.2. Thiết kế Giao diện Phân hệ Camera
- **Sử dụng Sidebar Dọc chung:** Trang Quản lý Camera luôn giữ nguyên thanh Sidebar màu trắng nằm dọc bên trái (`#FFFFFF`, viền `#E5E7EB`). Hệ thống không tạo thanh điều hướng ngang riêng biệt cho trang camera.
- **Không gian làm việc xám nhẹ (`#F5F6F8`):** Thẻ thông tin (Cards) và bảng dữ liệu nền trắng tinh tế với viền mỏng `#E5E7EB`.
- **Hệ thống biểu tượng Outline Monochrome:** Toàn bộ nút chức năng (Xem, Sửa, Tạm ngưng, Xóa) sử dụng icon đơn sắc đồng nhất kèm tooltip hướng dẫn.
- **Trạng thái kết nối chuẩn hóa:**
  - `Online` / `Running`: Màu xanh lá cây (Success Green).
  - `Offline` / `Disabled`: Màu xám trung tính hoặc đỏ cam (Warning).
  - `Error`: Màu đỏ (Error Red).

---

## 7. Thêm Camera mới

### 7.1. Mục đích
Khai báo một camera vật lý mới (RTSP, HLS, HTTP, CCTV) hoặc liên kết luồng phát trực tiếp vào hệ thống.

### 7.2. Điều kiện sử dụng
- Có sẵn địa chỉ URL của luồng video hợp lệ.
- URL phải có giao thức được hỗ trợ:
  - RTSP: `rtsp://...` hoặc `rtsps://...`
  - HLS: `http://.../playlist.m3u8` hoặc `https://...`
  - YouTube: `https://www.youtube.com/watch?v=...` hoặc `https://youtu.be/...`
  - Public CCTV: URL ảnh snapshot định kỳ hoặc luồng video HTTP.
  - Local Video: File video MP4 đã được upload vào thư viện (bắt đầu bằng `data/uploads/videos/`).

### 7.3. Các bước thao tác
1. Tại trang **Camera Management**, nhấn nút **"➕ Thêm camera"** ở góc trên bên phải.
2. Hộp thoại **"Thêm Camera Mới"** xuất hiện.
3. Điền các trường thông tin:
   - **Tên Camera:** Tên gợi nhớ (Ví dụ: `Camera Cổng Chính`, `Ngã tư Lê Lợi`). Tối đa 255 ký tự.
   - **Loại nguồn (Source Type):** Chọn trong menu thả xuống (`RTSP`, `Direct HLS`, `YouTube`, `File Video`, `Public CCTV`, `HTTP/HTTPS`).
   - **URL / Đường dẫn luồng:** Dán địa chỉ URL của camera.
   - **Khu vực / Zone:** Nhập vị trí hoặc phân khu (Ví dụ: `Khu A`, `Tầng hầm B1`, `Cổng số 2`).
   - **Mô tả:** Ghi chú thêm chi tiết về góc quay hoặc đặc điểm camera (tùy chọn).
4. Nhấn nút **"Kiểm tra kết nối"** (Test Connection):
   - Hệ thống sẽ gọi backend probe độc lập (`src/cameras/probe.py`) để thử đọc khung hình từ URL trong tối đa 10 giây.
   - Nếu thành công: hiển thị thông báo màu xanh `FRAME_READ` kèm độ trễ đo được (ms).
   - Nếu thất bại: hiển thị mã lỗi `SOURCE_UNREADABLE`, `TIMEOUT` hoặc `INVALID_SOURCE`.
5. Nhấn nút **"Lưu Camera"**.

### 7.4. Kết quả mong đợi
Camera mới xuất hiện ngay lập tức trong bảng danh sách camera với trạng thái ban đầu là `offline` hoặc `enabled`.

### 7.5. Lỗi có thể gặp & Cách xử lý
- **Lỗi `INVALID_NAME`:** Tên camera để trống hoặc quá 255 ký tự. Cần nhập tên hợp lệ.
- **Lỗi `INVALID_SOURCE` / `INVALID_PORT`:** URL luồng không đúng cú pháp, thiếu scheme hoặc số port không hợp lệ. Kiểm tra lại địa chỉ kết nối RTSP/HTTP.
- **Lỗi `INVALID_FILE_SOURCE`:** Chọn loại nguồn File nhưng đường dẫn không thuộc thư mục `data/uploads/videos/`. Cần upload video qua tab Local Video trước.

---

## 8. Chỉnh sửa thông tin Camera

### 8.1. Mục đích
Cập nhật lại tên, đường dẫn stream, vị trí khu vực hoặc mô tả khi có sự thay đổi cấu hình mạng của camera.

### 8.2. Điều kiện sử dụng
Camera đã tồn tại trong hệ thống.

### 8.3. Các bước thao tác
1. Trong danh sách camera, tìm đến dòng camera cần chỉnh sửa.
2. Nhấn biểu tượng nút **✏️ (Edit)** ở cột Thao tác (Actions).
3. Hộp thoại **"Chỉnh sửa Camera"** mở ra với các thông tin hiện tại được điền sẵn.
4. Thay đổi các trường cần cập nhật.
5. Nhấn **"Lưu thay đổi"**.

### 8.4. Kết quả mong đợi
Dữ liệu cập nhật thành công, danh sách tự động làm mới với thông tin mới.

### 8.5. Lưu ý đặc biệt
Nếu người dùng chuyển trạng thái camera sang `disabled` trong khi camera đó **đang chạy xử lý AI trực tiếp**, hệ thống sẽ từ chối và trả về lỗi: `CAMERA_ACTIVE_STOP_FIRST`. Người dùng cần dừng camera trước khi vô hiệu hóa hoặc sửa luồng.

---

## 9. Xóa Camera

### 9.1. Mục đích
Loại bỏ một camera không còn sử dụng ra khỏi cơ sở dữ liệu hệ thống.

### 9.2. Điều kiện sử dụng
Camera không đang ở trạng thái chạy trực tiếp (`active_until` đang có hiệu lực).

### 9.3. Các bước thao tác
1. Nhấn nút biểu tượng **🗑️ (Delete)** trên dòng camera tương ứng.
2. Hộp thoại xác nhận xuất hiện: *"Bạn có chắc chắn muốn xóa camera [Tên Camera] không?"*.
3. Nhấn **"Xác nhận xóa"**.

### 9.4. Kết quả mong đợi
Camera bị xóa khỏi bảng cơ sở dữ liệu `cameras`.

### 9.5. Lỗi có thể gặp
- **Lỗi `CAMERA_ACTIVE_STOP_FIRST`:** Camera này đang được AI Pipeline đọc và phân tích. Cần bấm "Dừng camera" hoặc chuyển sang camera khác trước khi xóa.
- **Lỗi `CAMERA_REFERENCED_OR_CONFLICT`:** Camera có liên kết khóa ngoại với các sự kiện trong quá khứ không thể xóa cứng (ràng buộc RESTRICT). Khi đó nên chuyển trạng thái sang `disabled` thay vì xóa.

---

## 10. Bật / Tắt camera

### 10.1. Mục đích
Tạm ngưng kích hoạt camera mà không cần xóa cấu hình khỏi hệ thống (ví dụ: khi camera bảo trì hoặc mất điện tạm thời).

### 10.2. Các bước thao tác
- Trong danh sách camera, nhấn vào nút chuyển đổi trạng thái (Toggle) hoặc nút menu **Enable / Disable**.
- Khi tắt (Disabled): camera chuyển sang trạng thái màu xám `disabled` và bị chặn không cho phép khởi động vào AI Pipeline.
- Khi bật (Enabled): camera sẵn sàng cho phép kết nối.

---

## 11. Xem camera

### 11.1. Mục đích
Chuyển đổi luồng quan sát của AI Pipeline sang camera mong muốn.

### 11.2. Thao tác kích hoạt
Người dùng có 2 cách để kích hoạt camera:
1. **Từ màn hình Chọn Camera (Landing Selection Screen):**
   - Tab **Public CCTV:** Duyệt danh mục camera Seattle SDOT hoặc Caltrans. Nhập từ khóa tìm kiếm đường phố, bấm thẻ camera để kết nối.
   - Tab **Direct HLS:** Nhập link `.m3u8`, bấm **"Xem trước"** (Preview) để kiểm tra luồng, sau đó bấm **"Sử dụng camera"**.
   - Tab **YouTube Live:** Chọn camera cấu hình sẵn trong danh sách thả xuống hoặc dán link YouTube Live, bấm **"Sử dụng camera"**.
   - Tab **Local Video:** Chọn file video có sẵn trong thư viện hoặc kéo thả file `.mp4` mới vào khu vực upload, bấm **"Chọn video này"**.
2. **Từ danh sách Quản lý Camera:**
   - Nhấn nút **▶️ (Kích hoạt / Sử dụng)** ở cột Actions của camera mong muốn.

### 11.3. Kết quả mong đợi
- Hệ thống dừng camera trước đó một cách an toàn.
- Đặt lại bộ đếm đối tượng, bộ theo dõi ByteTrack, trạng thái khuôn mặt và biển số xe.
- Chuyển hướng người dùng sang màn hình **Live Monitoring Dashboard** và hiển thị luồng video mới trong vòng 1-3 giây.

---

## 12. Danh sách theo dõi Khuôn mặt (Face Watchlist)

### 12.1. Mục đích
Quản lý hồ sơ các cá nhân cần giám sát (khách VIP, nhân viên, hoặc đối tượng cần theo dõi an ninh). Khi người này đi qua camera, hệ thống sẽ tự động so khớp đặc trưng khuôn mặt và phát cảnh báo.

### 12.2. Điều kiện sử dụng
- Truy cập menu **🎯 Watchlist** trên thanh điều hướng, chọn tab **👤 KHUÔN MẶT (Face Watchlist)**.

---

## 13. Thêm đối tượng theo dõi Khuôn mặt

### 13.1. Các bước thao tác
1. Tại tab Khuôn mặt, nhấn nút **"➕ Thêm khuôn mặt"**.
2. Hộp thoại modal xuất hiện gồm các trường:
   - **Họ và tên đối tượng (bắt buộc):** Nhập tên đầy đủ (Ví dụ: `Nguyễn Văn A`).
   - **Màu áo nhận diện phụ (Clothing Color - tùy chọn):** Chọn màu sắc trang phục thường mặc (`red`, `blue`, `green`, `yellow`, `black`, `white`) nếu muốn kết hợp nhận diện màu áo.
   - **Ngưỡng nhận diện (Face Threshold):** Mặc định là `0.45` (Giá trị từ 0.30 đến 0.85; giá trị càng cao yêu cầu độ giống càng khắt khe, giá trị thấp dễ bắt nhưng có thể nhầm lẫn).
   - **Chọn ảnh chân dung (Ảnh mẫu khuôn mặt):** Nhấn vùng upload để chọn file ảnh từ máy tính (JPEG, PNG, WEBP).
3. Sau khi chọn ảnh, hệ thống hiển thị bản xem trước ảnh mẫu (Preview).
4. Nhấn nút **"Đăng ký đối tượng"**.

### 13.2. Kết quả mong đợi
- Backend giải mã ảnh (xử lý xoay theo chuẩn EXIF), sử dụng mạng nơ-ron **SCRFD** phát hiện vị trí khuôn mặt và 5 điểm mốc (landmarks: 2 mắt, mũi, 2 khóe miệng).
- Mô hình **AdaFace** (`models/face/adaface_ir50_ms1mv2.onnx`) trích xuất vector đặc trưng 512 chiều được chuẩn hóa L2.
- Vector đặc trưng và ảnh mẫu được lưu bền vững vào bảng `targets` (và `target_embeddings` qua pgvector trên PostgreSQL).
- Đối tượng xuất hiện ngay trong bảng Face Watchlist với thẻ `Active`.

### 13.3. Lỗi có thể gặp khi đăng ký khuôn mặt
- **`NO_FACE_DETECTED`:** Không tìm thấy khuôn mặt nào trong ảnh upload.
  - *Cách xử lý:* Chọn ảnh chân dung rõ mặt, chụp thẳng, đủ ánh sáng, không bị che khuất bởi khẩu trang hay kính râm tối màu.
- **`INVALID_LANDMARKS` / `LANDMARKS_OUTSIDE_BBOX`:** Điểm mốc khuôn mặt bị méo hoặc nằm ngoài hộp bao.
  - *Cách xử lý:* Tránh ảnh chụp từ góc nghiêng quá lớn (trên 45 độ) hoặc ảnh bị biến dạng hình học.
- **`IMAGE_DECODE_FAILED`:** File tải lên bị hỏng hoặc dung lượng bằng 0 byte.
  - *Cách xử lý:* Kiểm tra lại định dạng file ảnh trên máy tính.

---

## 14. Upload ảnh và Kiểm tra đặc trưng khuôn mặt

Hệ thống DATT áp dụng bộ lọc chất lượng nghiêm ngặt khi đăng ký ảnh mẫu:
- **Độ phân giải khuôn mặt:** Khuyến nghị kích thước vùng mặt tối thiểu từ `80x80` pixel trở lên.
- **Độ sắc nét (Sharpness):** Đo lường phương sai toán tử Laplacian; ảnh quá mờ nhòe do chuyển động sẽ bị cảnh báo hoặc cho độ tương đồng thấp khi đối soát.
- **Tính đối xứng chính diện (Frontality):** Điểm đánh giá góc quay khuôn mặt từ `0.0` đến `1.0`. Hệ thống ưu tiên ảnh mẫu có độ đối xứng cao (mặt nhìn thẳng vào ống kính).

---

## 15. Danh sách theo dõi Phương tiện (Vehicle Watchlist)

### 15.1. Mục đích
Quản lý danh sách các biển số xe cần kiểm soát ra vào, xe của đối tượng truy vết, xe vi phạm hoặc xe ưu tiên.

### 15.2. Điều kiện sử dụng
Truy cập menu **🎯 Watchlist**, nhấn chuyển sang tab **🚗 PHƯƠNG TIỆN (Vehicle Watchlist)**.

---

## 16. Thêm biển số xe vào Watchlist

### 16.1. Các bước thao tác
1. Nhấn nút **"➕ Thêm phương tiện"**.
2. Điền thông tin phương tiện trong hộp thoại:
   - **Biển số xe (Bắt buộc):** Nhập biển số (Ví dụ: `29A-123.45`, `51K-999.88`, `43B1-1234`). Hệ thống sẽ tự động chuẩn hóa loại bỏ các ký tự dấu phân cách khi lưu trữ.
   - **Tên hiển thị / Nhãn xe:** Nhập tên xe hoặc tên người dùng (Ví dụ: `Xe Giao Hàng 01`, `Toyota Vios Đỏ`).
   - **Loại phương tiện:** Chọn loại xe (`Ô tô`, `Xe máy`, `Xe tải`, `Xe buýt`, `Container`, `Khác`).
   - **Màu sắc xe:** Chọn màu đăng ký của xe (`black`, `white`, `gray`, `silver`, `red`, `blue`, `green`, `yellow`, `orange`, `brown`, `other`).
   - **Thông tin chủ sở hữu (Owner Info):** Tên chủ xe, số điện thoại, phòng ban (tùy chọn).
   - **Ghi chú (Notes):** Lý do theo dõi, số lệnh điều xe hoặc lưu ý nghiệp vụ.
3. Nhấn **"Lưu phương tiện"**.

### 16.2. Kết quả mong đợi
Biển số xe được lưu vào bảng `vehicle_watchlists` với trạng thái `active`.

### 16.3. Lỗi có thể gặp
- **Lỗi `DUPLICATE_PLATE` (Plate already registered):** Biển số này đã tồn tại trong danh sách. Mỗi biển số chỉ được tạo 1 bản ghi duy nhất.
  - *Cách xử lý:* Tìm lại biển số trong danh sách để chỉnh sửa thay vì tạo mới.
- **Lỗi `INVALID_PLATE`:** Biển số nhập quá ngắn (dưới 3 ký tự) hoặc chứa ký tự không hợp lệ.

---

## 17. Sửa / Xóa biển số xe

### 17.1. Chỉnh sửa biển số
1. Nhấn biểu tượng nút **Chi tiết / Sửa** trên dòng phương tiện trong danh sách.
2. Ngăn chi tiết phương tiện (Vehicle Drawer) mở ra từ bên phải màn hình.
3. Cho phép chỉnh sửa: Loại xe, Màu sắc, Tên hiển thị, Chủ xe, Ghi chú và Trạng thái (`Active` hoặc `Disabled`).
4. Nhấn **"Cập nhật"**.

### 17.2. Xóa biển số
1. Mở ngăn chi tiết phương tiện cần xóa.
2. Nhấn nút **"Xóa khỏi Watchlist"** màu đỏ ở cuối ngăn.
3. Xác nhận xóa khi có thông báo. Biển số sẽ bị gỡ bỏ khỏi danh sách theo dõi.

---

## 18. Trung tâm Sự kiện (Event Center)

### 18.1. Mục đích
Là trung tâm tra cứu toàn diện (Audit Log) mọi sự kiện thị giác được hệ thống phát hiện và lưu trữ bền vững trong cơ sở dữ liệu. Giao diện được thiết kế theo triết lý **tối giản bảng dữ liệu (Minimalist Table)** kết hợp với **hộp thoại chi tiết thông minh (Type-Adaptive Event Detail Popup)**.

### 18.2. Điều kiện sử dụng
Nhấn vào biểu tượng **Event Center** trên thanh điều hướng bên trái hoặc chuyển đổi qua đường dẫn `/?view=events`.

### 18.3. Bảng sự kiện tối giản (Chuẩn 5 cột)
Bảng chính CHỈ hiển thị đúng 5 cột thông tin cốt lõi, không nhồi nhét dữ liệu kỹ thuật:

| Cột | Nội dung & Quy cách hiển thị |
| :--- | :--- |
| **1. THỜI GIAN** | Thời điểm ghi nhận sự kiện (`HH:mm:ss` in đậm, ngày tháng `DD/MM/YYYY` phụ bên dưới theo font mono sạch sẽ). |
| **2. HÌNH ẢNH** | Ảnh thu nhỏ (Thumbnail 68x42px, bo góc nhẹ, giữ nguyên aspect ratio, không stretch). Nếu không có ảnh chụp hoặc ảnh hỏng, hiển thị biểu tượng placeholder SVG trang nhã, không lỗi broken image. Bấm vào thumbnail để mở popup xem chi tiết. |
| **3. LOẠI SỰ KIỆN** | Huy hiệu phân loại sự kiện rõ ràng: `Face Watchlist` (màu đỏ nổi bật khi khớp mục tiêu), `Khuôn mặt`, `Vehicle Watchlist` (màu cam vàng khi khớp biển số), `Biển số xe`, `Phương tiện`, `Lượt xe qua`, `Nghiệp vụ`. |
| **4. CAMERA** | Biểu tượng máy quay kèm tên và định danh camera phát hiện sự kiện. |
| **5. CHI TIẾT** | **CHỈ DUY NHẤT một biểu tượng con mắt (Eye Icon)** monochrome outline chuẩn hệ thống, có tooltip *"Xem chi tiết"*. Bấm vào để mở **Event Detail Popup**. Không có nút Edit, Delete, More hay các action gây rối mắt. |

---

## 19. Hộp thoại Chi tiết Sự kiện (Event Detail Popup)

Khi người dùng bấm vào biểu tượng con mắt hoặc ảnh thumbnail ở bất kỳ dòng nào, hệ thống mở **Event Detail Popup** hiển thị toàn bộ hồ sơ sự kiện một cách trực quan, khoa học:

### 19.1. Ảnh bằng chứng kích thước lớn (Evidence Image)
- Đặt ở phía trên cùng của popup trong khung nền tối chuyên dụng (`#0F172A`).
- Tự động co giãn theo tỷ lệ thực (`object-fit: contain`), không bị méo ảnh, giới hạn chiều cao tối đa `38vh - 45vh` để không vượt màn hình.
- Nếu sự kiện không có ảnh đính kèm: hiển thị trạng thái *"Không có hình ảnh"* tinh tế.

### 19.2. Bố cục Label — Value theo Section (Không hiển thị JSON thô)
Dữ liệu được trình bày dạng cặp nhãn - giá trị rõ ràng, chia thành các phần:
1. **Thông tin sự kiện:** Thời gian đầy đủ (`DD/MM/YYYY HH:mm:ss`), Camera phát hiện, Loại sự kiện, Phân loại nghiệp vụ, Quyết định Watchlist.
2. **Thông tin nhận diện & đối tượng (Thích ứng thông minh theo loại sự kiện):**
   - **Sự kiện Khuôn mặt (Face Event):** Tên đối tượng mục tiêu (nếu đã đăng ký), Độ tương đồng (`Similarity %`), Quyết định so khớp (`✓ MATCH WATCHLIST` hoặc Bình thường), Track ID (nếu có).
   - **Sự kiện Phương tiện & Biển số xe (Vehicle / Plate Event):** Biển số xe (huy hiệu biển số chuẩn font mono), Loại phương tiện, Màu xe phát hiện thực tế (Đen, Trắng, Đỏ...), Độ tin cậy nhận diện màu, Màu xe đăng ký Watchlist, Độ tin cậy OCR (`Confidence %`), Trạng thái khớp Watchlist, Track ID (nếu có).
   - **Sự kiện Chung / Nghiệp vụ (Generic / Business Event):** Tự động render các trường dữ liệu thực tế tồn tại.
   - **Quy tắc hiển thị sạch:** Các trường rỗng, `null` hoặc `undefined` được **bỏ hoàn toàn**, không hiển thị `null` hay `undefined` trên giao diện.
3. **Thông tin cảnh báo (Notification Section):**
   - Hiển thị khi sự kiện có trạng thái thông báo: `✓ Đã gửi thông báo thành công` (Sent), `⏳ Đang chờ gửi` (Pending), `✕ Gửi thất bại` (Failed), hoặc `Bị chặn` (Suppressed).
4. **Thông tin kỹ thuật (Technical Section):**
   - Đặt ở phần cuối popup để người dùng thông thường không bị rối: Mã sự kiện (`Event ID`), Source Event ID, Target ID, Điểm tin cậy gốc, Khóa lưu trữ (`Storage Key`).

### 19.3. Đóng popup linh hoạt
Người dùng có thể đóng popup mà **không bao giờ reload lại trang** bằng 4 cách:
- Bấm nút **[X]** ở góc trên bên phải tiêu đề.
- Bấm nút **"Đóng"** ở chân popup.
- Bấm phím **ESC** trên bàn phím.
- Bấm vào vùng nền đen mờ (Overlay Backdrop) xung quanh modal.

---

## 20. Tìm kiếm và Lọc sự kiện

Phía trên bảng sự kiện chỉ giữ các bộ lọc thiết thực, không đưa bộ lọc kỹ thuật vào giao diện chính:
1. **Tìm kiếm (Search):** Nhập biển số xe (ví dụ `29A-123.45`, `29A12345`) hoặc mã định danh mục tiêu. Bấm `Enter` hoặc nút `Lọc` để tìm kiếm tức thì.
2. **Loại sự kiện:** Lọc theo danh mục: Khuôn mặt (Face), Biển số xe (Plate), Phương tiện (Vehicle), Lượt xe qua (Passage), Nghiệp vụ (Business).
3. **Camera:** Lọc sự kiện ghi nhận từ camera được chọn.
4. **Khoảng thời gian:** Chọn khoảng thời gian cụ thể (Từ ngày giờ đến Ngày giờ).
5. **Thao tác nhanh:**
   - Nút **"Lọc"**: Áp dụng các tiêu chí tìm kiếm.
   - Nút **"Đặt lại"**: Xóa toàn bộ bộ lọc và hiển thị lại toàn bộ sự kiện mới nhất.
   - Menu sắp xếp: Cho phép chuyển đổi giữa `Mới nhất` (giảm dần) và `Cũ nhất` (tăng dần).

---

---

## 21. Hệ thống Cảnh báo Toàn cục & Thông báo Email (Global Alert & Toast Notification)

### 21.1. Cảnh báo Thông báo Toàn cục (Global Toast Notification)
Nhằm đảm bảo nhân viên trực ban không bỏ sót bất kỳ sự kiện an ninh trọng điểm nào ngay cả khi đang duyệt danh sách camera hay xem luồng trực tiếp, hệ thống tích hợp cơ chế **Global Toast Notification**:
- **Vị trí cố định:** Thông báo luôn bật lên ở **Góc trên bên phải (Top-Right)** của màn hình trên MỌI trang:
  - Dashboard
  - Quản lý Camera (Camera Management)
  - Xem luồng trực tiếp (Dedicated Stream View)
  - Chế độ Toàn màn hình (Fullscreen Monitoring)
  - Event Center
  - Face Watchlist & Vehicle Watchlist
  - Alert Center
- **Thời gian hiển thị tự động (5 Giây):**
  - Mỗi Toast tự động đếm ngược đúng **5 giây (5000ms)** và tự đóng dần với hiệu ứng mờ nhẹ (`fade/slide`).
  - Mỗi thông báo có bộ đếm thời gian (Timer) hoàn toàn độc lập.
- **Nút đóng tức thời (Close Button '✕'):**
  - Ở góc trên bên phải mỗi Toast có nút đóng hình chữ `✕`. Người dùng có thể nhấn `✕` để tắt thông báo ngay lập tức mà không cần đợi 5 giây.
- **Xếp chồng dọc (Vertical Stacking):**
  - Khi có nhiều cảnh báo xuất hiện đồng thời hoặc cách nhau khoảng thời gian ngắn, các Toast sẽ xếp chồng ngay ngắn theo chiều dọc từ trên xuống dưới, không bị đè lấp lên nhau.
- **Hoạt động trong Chế độ Toàn màn hình (Fullscreen Support):**
  - Khi người dùng phóng to toàn màn hình camera (`requestFullscreen`), hệ thống tự động đưa container của Toast vào trong phần tử toàn màn hình (`#streamViewport`). Nhờ đó, người giám sát vẫn nhận được cảnh báo bảo mật bình thường mà không bị trình duyệt che khuất.
- **QUAN TRỌNG - Bảo toàn Lịch sử:**
  - Thao tác đóng Toast chỉ đơn thuần là đóng cửa sổ thông báo trên giao diện người dùng.
  - **TUYỆT ĐỐI KHÔNG:** xóa cảnh báo trong cơ sở dữ liệu, không xóa sự kiện, không thay đổi bảng `notifications` hay `AlertOutbox`. Toàn bộ lịch sử vẫn được lưu trữ nguyên vẹn trong **Alert Center**.

### 21.2. Ánh xạ Trạng thái Thông báo Email từ Outbox Backend
Hệ thống tận dụng trực tiếp bảng điều phối thông báo (`notifications` outbox) hiện có ở backend, tự động đồng bộ và hiển thị trạng thái email theo bảng mã chuẩn:

| Trạng thái Backend | Mức độ cảnh báo (Severity) | Tiêu đề Toast | Nội dung hiển thị |
|---|---|---|---|
| **`PENDING`** | Cảnh báo / Warning (Vàng) | **Cảnh báo email đang chờ gửi** | Chuẩn bị gửi email thông báo đối tượng mục tiêu |
| **`SENT`** | Thành công / Success (Xanh lá) | **Đã gửi cảnh báo qua email** | Gửi thành công tới địa chỉ hộp thư nhận |
| **`FAILED`** | Lỗi / Error (Đỏ) | **Gửi cảnh báo qua email thất bại** | Báo lỗi chi tiết (SMTP, Timeout hoặc Chưa cấu hình) |
| **`SUPPRESSED`** | Thông tin / Info (Xanh/Trung tính) | **Không gửi cảnh báo (đã chặn)** | Cảnh báo bị chặn do chính sách chống spam Cooldown 300s |

---

## 22. Xem trạng thái gửi Notification và Lịch sử cảnh báo

### 22.1. Phân hệ Alert Center
Người dùng truy cập vào mục **Alert Center** trên thanh điều hướng bên trái để mở trung tâm kiểm tra lịch sử chi tiết toàn bộ các cảnh báo đã và đang được gửi.

### 22.2. Ý nghĩa các trạng thái cảnh báo trong Alert Center
- **`SENT` (Màu xanh lá):** Email cảnh báo đã được máy chủ SMTP tiếp nhận và gửi đi thành công tới hòm thư người nhận. Có hiển thị mốc thời gian `Sent At`.
- **`PENDING` (Màu vàng):** Thông báo đang nằm trong hàng đợi chờ tiến trình gửi email xử lý.
- **`FAILED` (Màu đỏ):** Gửi email không thành công sau các lần thử lại. Có hiển thị mã lỗi chẩn đoán an toàn (Ví dụ: `smtp_authentication`, `smtp_timeout`, `invalid_recipient`, hoặc `CONFIGURED=false` nếu chưa cấu hình tài khoản gửi mail trong `.env`).
- **`SUPPRESSED` (Màu xám):** Thông báo bị ngăn chặn có chủ đích (do cơ chế Cooldown chống gửi trùng lặp).

### 22.3. Chi tiết nội dung Email cảnh báo
Email gửi tới người nhận sẽ bao gồm:
- **Tiêu đề:** `DATT Face Watchlist MATCH` hoặc `DATT Vehicle Watchlist MATCH`.
- **Nội dung:** Tên mục tiêu / Biển số xe, ID sự kiện, Tên camera, Vị trí khu vực, Mốc thời gian UTC, Điểm độ tin cậy / Tỷ lệ tương đồng.
- **File đính kèm:** Ảnh chụp bằng chứng khuôn mặt hoặc biển số xe (`evidence.jpg`).

---

## 23. Các lỗi thường gặp đối với người dùng

| Hiện tượng | Nguyên nhân có thể | Cách xử lý |
|---|---|---|
| **Màn hình Live View hiện biểu tượng Aperture "CONNECTING TO CAMERA..."** | Camera đang khởi động luồng kết nối hoặc đường truyền mạng đang buffer. | Chờ 3-5 giây. Nếu quá 15 giây vẫn không lên hình, kiểm tra lại nguồn camera hoặc switch sang camera khác. |
| **Màn hình Live View báo "Stream ended or camera disconnected"** | Camera bị mất nguồn điện, đứt cáp mạng, hoặc luồng RTSP/YouTube bị gián đoạn. | Bấm nút **"Thử kết nối lại"** (Reconnect) trên màn hình lỗi hoặc vào Camera Management để test kết nối. |
| **Đăng ký khuôn mặt báo lỗi `NO_FACE_DETECTED`** | Ảnh upload có mặt quá nhỏ, quá tối, hoặc góc nghiêng quá lớn. | Dùng ảnh chụp rõ mặt, nhìn thẳng, khoảng cách gần, độ phân giải tối thiểu 300x300 pixel. |
| **Thêm biển số báo lỗi `Plate already registered`** | Biển số này đã được thêm trước đó vào Watchlist. | Nhập biển số vào ô tìm kiếm của Vehicle Watchlist để kiểm tra và sửa thông tin nếu cần. |
| **Xe chạy qua nhưng không hiện biển số trên nhãn** | Xe đi quá nhanh, biển số bị mờ/bẩn/che khuất, hoặc chưa đủ số khung hình đồng thuận (yêu cầu >= 2 khung hình đọc khớp nhau). | Điều chỉnh góc quay camera thấp hơn và hướng thẳng vào làn xe chạy để camera bắt được góc biển số rõ nét nhất. |
| **Không nhận được email cảnh báo** | Chưa cấu hình thông tin SMTP trong file `.env` hoặc thông báo đang trong thời gian Cooldown (300 giây). | Kiểm tra trạng thái trong màn hình **Alerts**: nếu là `CONFIGURED=false`, liên hệ Admin cấu hình SMTP; nếu là `suppressed`, đây là tính năng chống spam của hệ thống. |

---

## 24. Câu hỏi thường gặp (FAQ)

**Q1: Hệ thống DATT có thể chạy đồng thời bao nhiêu camera cùng lúc?**  
*A:* Trong kiến trúc hiện tại, AI Processing Pipeline được thiết kế để phân tích chuyên sâu **01 Camera Hoạt động Trọng điểm (Active Camera)** tại một thời điểm để tối ưu hóa hiệu năng GPU CUDA (đạt 30 FPS mượt mà cho cả Detection, Tracking, Face AdaFace và Plate OCR). Bạn có thể cấu hình danh bạ hàng trăm camera trong Camera Management và chuyển đổi luồng giám sát chỉ bằng 1 cú click chuột.

**Q2: Tại sao số lượng người trong đếm xe và người lúc tăng lúc giảm?**  
*A:* Hệ thống hiển thị chỉ số **Số người / Số xe đang có mặt trong khung hình thời gian thực (Occupancy / In-View Count)** chứ không phải số cộng dồn lũy kế. Khi một người đi ra khỏi tầm nhìn của camera, chỉ số sẽ giảm tương ứng.

**Q3: Tôi có thể sử dụng video quay sẵn từ điện thoại để phân tích không?**  
*A:* Hoàn toàn được. Vào tab **Local Video**, kéo thả file `.mp4` vào khu vực tải lên. Hệ thống sẽ lưu trữ và bắt đầu chạy phát hiện đối tượng trên file video đó với chế độ lặp (Loop).

**Q4: Ngưỡng nhận diện khuôn mặt nên đặt bao nhiêu là tối ưu?**  
*A:* Giá trị mặc định là **0.45**. 
- Nếu môi trường ánh sáng tốt, camera nhìn thẳng: có thể tăng lên **0.50 - 0.55** để giảm tối đa tỷ lệ nhận diện nhầm.
- Nếu camera lắp trên cao nhìn nghiêng (CCTV góc rộng): nên giữ ở mức **0.40 - 0.45**.
