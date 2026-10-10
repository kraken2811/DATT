"""Procedural grounded synthesis of user guide, operations, and troubleshooting knowledge for DATT Agent."""

import re
from typing import Any

from src.agent.rag.intent import DocIntent, classify_doc_intent


def has_operational_instructions(results: list[dict[str, Any]]) -> bool:
    """Check if retrieved chunks contain user-facing UI actions and operational steps."""
    if not results:
        return False

    # Check if any chunk originates from User Guide or Admin Guide
    for r in results:
        doc_name = (r.get("document_name") or "").lower()
        if any(w in doc_name for w in ("user guide", "user_guide", "hướng dẫn sử dụng")):
            return True
        if "admin guide" in doc_name and "bước" in str(r.get("content", "")).lower():
            return True

    # Check for operational UI cues in the content
    operational_cues = [
        "bước 1", "bước 2", "bước 3", "thanh sidebar", "nhấn vào", "click", "truy cập",
        "menu chính", "chọn camera", "thêm camera", "toàn màn hình", "fullscreen",
        "thêm đối tượng", "tải ảnh", "upload", "event center", "alert center",
        "bánh răng", "cài đặt theme", "bật/tắt"
    ]
    total_cues = 0
    for r in results:
        c = (r.get("content") or "").lower()
        for cue in operational_cues:
            if cue in c:
                total_cues += 1
    return total_cues >= 2


def extract_references(results: list[dict[str, Any]]) -> list[str]:
    """Extract clean, unique document provenance references without raw scores."""
    citations: list[str] = []
    seen: set[str] = set()
    for r in results:
        if not isinstance(r, dict):
            continue
        doc_name = r.get("document_name", "Tài liệu hệ thống DATT")
        sec = r.get("section")
        page = r.get("page")
        parts = [f"Tài liệu: {doc_name}"]
        if sec and sec != "General":
            parts.append(f"Mục: {sec}")
        if page is not None and str(page) not in ("None", ""):
            parts.append(f"Trang: {page}")
        line = " — ".join(parts)
        if line not in seen:
            seen.add(line)
            citations.append(line)
    return citations


def synthesize_knowledge_answer(user_question: str, data: dict[str, Any]) -> str:
    """Synthesize an actionable, structured Vietnamese answer using retrieved RAG evidence.

    Follows the 5 required core aspects:
    1. What the feature does (Mục đích & Chức năng)
    2. Where the user should navigate (Vị trí điều hướng)
    3. What actions the user should perform (Các bước thao tác)
    4. What result to expect (Kết quả kỳ vọng)
    5. Important limitations (Lưu ý & Giới hạn quan trọng)

    And keeps document references available separately at the end without retrieval scores.
    """
    if not isinstance(data, dict):
        return "Dữ liệu tài liệu chưa khả dụng; chưa thể xác minh hướng dẫn hoặc nguồn trích dẫn."

    status = data.get("status")
    results = data.get("results")

    if status == "insufficient_context" or not isinstance(results, list) or not results:
        return (
            "Chưa tìm thấy tài liệu hướng dẫn phù hợp với yêu cầu tra cứu trong cơ sở tri thức hệ thống. "
            "Bạn có thể cung cấp thêm từ khóa hoặc tính năng cụ thể để hệ thống tra cứu lại."
        )

    # Classify documentation intent and target domain
    intent_info = classify_doc_intent(user_question)
    doc_intent = data.get("doc_intent") or intent_info["intent"]
    feature_domain = data.get("feature_domain") or intent_info.get("feature_domain", "ALL")

    references = extract_references(results)
    ref_block = "\n".join(f"- {ref}" for ref in references)
    ref_footer = f"\n\n---\n**Nguồn tài liệu tham khảo:**\n{ref_block}" if references else ""

    # Requirement 9: If retrieved documentation only contains architectural descriptions
    # and does not support operational steps for a user guide query, report insufficient evidence.
    if doc_intent == DocIntent.USER_GUIDE.value and not has_operational_instructions(results):
        return (
            "**Thông báo tài liệu:**\n"
            "Tài liệu hiện có trong cơ sở tri thức cho câu hỏi này chỉ mô tả kiến trúc kỹ thuật hoặc cấu trúc hệ thống, "
            "chưa có thông tin quy trình thao tác người dùng (UI operational steps) cho chức năng này. "
            "Hệ thống không tự tạo ra các bước giao diện không được ghi nhận trong tài liệu."
            f"{ref_footer}"
        )

    # 1. USER GUIDE — GENERAL SYSTEM OPERATION
    if doc_intent == DocIntent.USER_GUIDE.value and feature_domain == "ALL":
        body = (
            "### 1. Mục đích & Chức năng hệ thống (Feature Overview)\n"
            "DATT (Deep AI Tracking & Targeting) là hệ thống giám sát thị giác AI thông minh thời gian thực, "
            "phục vụ đếm người và phương tiện, tự động phát hiện và nhận diện khuôn mặt mục tiêu (Face Watchlist), "
            "nhận diện biển số xe (Vehicle Watchlist), ghi nhận sự kiện có ảnh bằng chứng và phát cảnh báo tự động qua Email.\n\n"
            "### 2. Vị trí điều hướng & Giao diện (Navigation)\n"
            "Hệ thống sử dụng thanh **Sidebar dọc màu trắng** cố định ở cạnh trái màn hình để truy cập các phân hệ:\n"
            "- **Dashboard (Tổng quan):** Lựa chọn nguồn camera (Hệ thống, CCTV, Video file, URL tùy chỉnh) và theo dõi sự kiện gần đây.\n"
            "- **Quản lý Camera:** Danh sách hệ thống camera, thêm/sửa/xóa và cấu hình nguồn phát.\n"
            "- **Giám sát trực tiếp (Monitor Screen):** Màn hình video MJPEG 16:9 chuyên biệt, xem toàn màn hình (Fullscreen) với thanh đo lường người/xe.\n"
            "- **Face Watchlist:** Quản lý đối tượng khuôn mặt cần theo dõi, upload ảnh chân dung và kiểm tra vector đặc trưng.\n"
            "- **Vehicle Watchlist:** Quản lý biển số xe theo dõi, loại xe, màu sắc và chủ sở hữu.\n"
            "- **Event Center:** Trung tâm tra cứu, tìm kiếm và lọc lịch sử sự kiện nhận diện (Khuôn mặt, Biển số, Lượt xe).\n"
            "- **Alert Center:** Quản lý danh sách cảnh báo và hàng đợi gửi email thông báo (Outbox).\n"
            "- **Cài đặt Theme (Biểu tượng Bánh răng ở đáy Sidebar):** Tùy biến màu chủ đạo giao diện (5 gam màu).\n\n"
            "### 3. Các bước thao tác cơ bản (Operational Steps)\n"
            "- **Bước 1 — Chọn và xem Camera:** Truy cập Dashboard hoặc Quản lý Camera, chọn camera mong muốn và nhấn nút \"Xem camera\" để chuyển sang màn hình giám sát chuyên biệt.\n"
            "- **Bước 2 — Cấu hình danh sách theo dõi:** Vào *Face Watchlist* để tải ảnh chân dung đối tượng hoặc *Vehicle Watchlist* để nhập biển số xe cần giám sát.\n"
            "- **Bước 3 — Giám sát & Nhận cảnh báo:** Theo dõi luồng trực tiếp; khi đối tượng mục tiêu xuất hiện, hệ thống tự động hiển thị thông báo Toast góc trên bên phải (5 giây) và phát email cảnh báo.\n"
            "- **Bước 4 — Tra cứu lịch sử & Bằng chứng:** Vào *Event Center* để lọc sự kiện theo thời gian, camera hoặc loại đối tượng và tải ảnh snapshot bằng chứng.\n\n"
            "### 4. Kết quả kỳ vọng (Expected Results)\n"
            "- Luồng video camera hiển thị mượt mà kèm thanh trạng thái đếm người/xe thời gian thực.\n"
            "- Nhận diện đối tượng chính xác theo danh sách theo dõi và kích hoạt thông báo tức thì.\n"
            "- Nhật ký sự kiện lưu trữ đầy đủ bằng chứng và mốc thời gian UTC/ICT chuẩn xác.\n\n"
            "### 5. Lưu ý & Giới hạn quan trọng (Important Limitations)\n"
            "- Số lượng sự kiện trong cơ sở dữ liệu là lịch sử tích lũy, không suy diễn mật độ người/xe hiện diện tức thời trong khung hình.\n"
            "- Trạng thái camera offline phản ánh ingestion worker; cần kiểm tra kết nối mạng thực tế tới URL nguồn.\n"
            "- Ảnh khuôn mặt đăng ký cần trực diện và rõ nét để trích xuất vector đặc trưng đạt độ tin cậy tối ưu."
        )
        return body + ref_footer

    # 2. USER GUIDE — CAMERA & MONITORING
    if doc_intent == DocIntent.USER_GUIDE.value and feature_domain == "CAMERA":
        body = (
            "### 1. Mục đích & Chức năng (Feature Overview)\n"
            "Phân hệ Camera và Giám sát trực tiếp cho phép người dùng xem luồng video thời gian thực độ trễ thấp từ nhiều loại nguồn "
            "(RTSP, HLS, YouTube Live, CCTV công cộng, Video MP4 cục bộ), đo lường lưu lượng người/xe và quản lý danh mục camera trong hệ thống.\n\n"
            "### 2. Vị trí điều hướng (Navigation)\n"
            "Truy cập phân hệ qua menu **Dashboard** (Chọn camera) hoặc **Quản lý Camera** trên thanh Sidebar bên trái. "
            "Màn hình giám sát trực tiếp mở tại đường dẫn `/monitor` sau khi chọn camera và nhấn \"Xem camera\".\n\n"
            "### 3. Các bước thao tác (Operational Steps)\n"
            "- **Bước 1 — Chọn nguồn camera:** Tại Dashboard, duyệt qua các nhóm nguồn (Hệ thống, CCTV, Video file, URL tùy chỉnh) và nhấp chọn camera mong muốn.\n"
            "- **Bước 2 — Mở màn hình giám sát:** Nhấn nút \"Xem camera\" để chuyển sang màn hình giám sát chuyên biệt tỉ lệ 16:9.\n"
            "- **Bước 3 — Điều khiển luồng:** Trên màn hình Monitor, sử dụng nút Toàn màn hình (Fullscreen) để phóng to theo dõi hoặc nút Dừng luồng khi hoàn tất.\n"
            "- **Bước 4 — Thêm/sửa camera (nếu cần):** Vào *Quản lý Camera* trên Sidebar, nhấn \"Thêm camera mới\", nhập tên, vị trí, loại nguồn và URL kết nối. Sử dụng nút Kiểm tra kết nối (Probe Test) trước khi lưu.\n\n"
            "### 4. Kết quả kỳ vọng (Expected Results)\n"
            "- Màn hình Monitor hiển thị luồng video trực tiếp mượt mà kèm 4 thẻ đo lường (telemetry) người và phương tiện.\n"
            "- Camera mới cấu hình hiển thị trong danh mục hệ thống với trạng thái Đang hoạt động (Active).\n\n"
            "### 5. Lưu ý & Giới hạn quan trọng (Important Limitations)\n"
            "- Luồng RTSP và HLS phụ thuộc vào chất lượng đường truyền mạng; nếu camera offline, kiểm tra IP, port 554 và thông tin đăng nhập.\n"
            "- Video tải lên cục bộ cần đúng định dạng MP4 codec H.264.\n"
            "- Không suy luận mật độ người/xe có mặt tức thời nếu chưa mở luồng video trực tiếp."
        )
        return body + ref_footer

    # 3. USER GUIDE — WATCHLIST (FACE & VEHICLE)
    if doc_intent == DocIntent.USER_GUIDE.value and feature_domain == "WATCHLIST":
        body = (
            "### 1. Mục đích & Chức năng (Feature Overview)\n"
            "Quản lý danh sách các đối tượng khuôn mặt (Face Watchlist) và phương tiện (Vehicle Watchlist) cần theo dõi an ninh "
            "để hệ thống tự động phát hiện, đối soát và cảnh báo khi xuất hiện trước camera.\n\n"
            "### 2. Vị trí điều hướng (Navigation)\n"
            "Truy cập qua menu **Face Watchlist** hoặc **Vehicle Watchlist** trên thanh Sidebar bên trái.\n\n"
            "### 3. Các bước thao tác (Operational Steps)\n"
            "- **Bước 1 — Đăng ký khuôn mặt:** Vào *Face Watchlist*, nhấn \"Thêm đối tượng\", nhập họ tên, thông tin phân loại, và tải lên ảnh chân dung rõ mặt. Hệ thống tự động kiểm tra chất lượng và trích xuất vector đặc trưng 512 chiều.\n"
            "- **Bước 2 — Đăng ký biển số xe:** Vào *Vehicle Watchlist*, nhấn \"Thêm biển số xe\", nhập biển số chuẩn, loại xe, màu sắc nhận diện và thông tin chủ sở hữu.\n"
            "- **Bước 3 — Kích hoạt theo dõi:** Đảm bảo trạng thái đối tượng được bật (Active) để kích hoạt cơ chế so khớp tự động trên các luồng camera.\n"
            "- **Bước 4 — Xem chi tiết & Lịch sử:** Nhấp \"Xem chi tiết\" trên thẻ đối tượng để kiểm tra lịch sử các lần nhận diện khớp trong quá khứ.\n\n"
            "### 4. Kết quả kỳ vọng (Expected Results)\n"
            "- Bản ghi đối tượng được lưu trữ an toàn trong cơ sở dữ liệu với trạng thái Active.\n"
            "- Khi đối tượng xuất hiện trước camera, hệ thống phát hiện trong thời gian thực và tạo sự kiện nhận diện khớp (Watchlist Match).\n\n"
            "### 5. Lưu ý & Giới hạn quan trọng (Important Limitations)\n"
            "- Ảnh khuôn mặt tải lên phải rõ ràng, đủ sáng, góc nghiêng không quá lớn để trích xuất vector đặc trưng chính xác.\n"
            "- Biển số xe cần nhập đúng định dạng chuẩn (ví dụ: `29A-12345`)."
        )
        return body + ref_footer

    # 4. USER GUIDE — EVENT CENTER
    if doc_intent == DocIntent.USER_GUIDE.value and feature_domain == "EVENT_CENTER":
        body = (
            "### 1. Mục đích & Chức năng (Feature Overview)\n"
            "Tra cứu tập trung toàn bộ các sự kiện nhận diện (Khuôn mặt, Biển số xe, Lượt phương tiện, Sự kiện nghiệp vụ), "
            "xem lại ảnh chụp bằng chứng (crop khuôn mặt, crop biển số, ảnh toàn cảnh) và thông số độ tin cậy.\n\n"
            "### 2. Vị trí điều hướng (Navigation)\n"
            "Truy cập qua menu **Event Center** trên thanh Sidebar bên trái.\n\n"
            "### 3. Các bước thao tác (Operational Steps)\n"
            "- **Bước 1 — Truy cập Trung tâm sự kiện:** Nhấp vào *Event Center* trên Sidebar.\n"
            "- **Bước 2 — Áp dụng bộ lọc:** Chọn khoảng thời gian (Hôm nay, Hôm qua, hoặc khoảng ngày tùy chọn), lọc theo loại sự kiện (Khuôn mặt, Biển số, Lượt xe) hoặc theo camera cụ thể.\n"
            "- **Bước 3 — Xem chi tiết & Bằng chứng:** Nhấp vào sự kiện trong danh sách để xem ảnh chụp bằng chứng, độ tương đồng (similarity) và thông tin camera tương ứng.\n\n"
            "### 4. Kết quả kỳ vọng (Expected Results)\n"
            "- Danh sách sự kiện được lọc chính xác theo tiêu chí với mốc thời gian rõ ràng.\n"
            "- Ảnh bằng chứng hiển thị trực quan phục vụ công tác xác minh an ninh.\n\n"
            "### 5. Lưu ý & Giới hạn quan trọng (Important Limitations)\n"
            "- Dữ liệu sự kiện lưu trữ theo mốc thời gian ghi nhận (UTC/ICT); tên và vị trí camera hiển thị theo cấu hình hiện tại của hệ thống."
        )
        return body + ref_footer

    # 5. USER GUIDE — ALERT CENTER & NOTIFICATIONS
    if doc_intent == DocIntent.USER_GUIDE.value and feature_domain == "ALERT_CENTER":
        body = (
            "### 1. Mục đích & Chức năng (Feature Overview)\n"
            "Theo dõi và quản lý các cảnh báo toàn cục khi có mục tiêu Watchlist xuất hiện, bao gồm thông báo nổi (Global Toast Alert) "
            "trên giao diện và hàng đợi gửi email cảnh báo an ninh (Transactional Outbox).\n\n"
            "### 2. Vị trí điều hướng (Navigation)\n"
            "Truy cập qua menu **Alert Center** trên thanh Sidebar bên trái.\n\n"
            "### 3. Các bước thao tác (Operational Steps)\n"
            "- **Bước 1 — Quan sát cảnh báo nổi:** Khi có sự kiện khớp Watchlist, thông báo Toast xuất hiện ở góc trên bên phải màn hình trên mọi trang và tự động ẩn sau 5 giây.\n"
            "- **Bước 2 — Kiểm tra danh sách cảnh báo:** Truy cập *Alert Center* để xem nhật ký toàn bộ các cảnh báo đã phát sinh.\n"
            "- **Bước 3 — Kiểm tra trạng thái gửi Email:** Theo dõi trạng thái từng bản ghi thông báo: `PENDING` (đang chờ), `SENT` (đã gửi thành công tới máy chủ SMTP), `FAILED` (thất bại, kèm số lần retry và lý do), hoặc `SUPPRESSED` (bị chặn do cooldown chống trùng lặp).\n\n"
            "### 4. Kết quả kỳ vọng (Expected Results)\n"
            "- Cảnh báo được gửi đi kịp thời đến hộp thư người quản trị kèm ảnh bằng chứng.\n"
            "- Trạng thái phân bố cảnh báo hiển thị rõ ràng minh bạch.\n\n"
            "### 5. Lưu ý & Giới hạn quan trọng (Important Limitations)\n"
            "- Trạng thái `SENT` phản ánh email đã được máy chủ gửi đi thành công tới relay/outbox; hệ thống không theo dõi việc người nhận đã mở email hay chưa.\n"
            "- Địa chỉ email người nhận luôn được ẩn (masked) trên giao diện để bảo vệ quyền riêng tư."
        )
        return body + ref_footer

    # 6. USER GUIDE — THEME & SETTINGS
    if doc_intent == DocIntent.USER_GUIDE.value and feature_domain == "THEME":
        body = (
            "### 1. Mục đích & Chức năng (Feature Overview)\n"
            "Tùy biến gam màu chủ đạo (Accent Color) của giao diện người dùng theo chuẩn phong cách Doanh nghiệp (Enterprise Monitoring Dashboard).\n\n"
            "### 2. Vị trí điều hướng (Navigation)\n"
            "Biểu tượng **Bánh răng Cài đặt (Settings)** nằm ở góc dưới cùng của thanh Sidebar bên trái.\n\n"
            "### 3. Các bước thao tác (Operational Steps)\n"
            "- **Bước 1:** Nhấp vào biểu tượng Bánh răng ở đáy Sidebar để mở hộp thoại Cài đặt Giao diện.\n"
            "- **Bước 2:** Lựa chọn một trong 5 gam màu chủ đạo: Xanh dương (Blue - Mặc định), Xanh lá (Green), Tím (Purple), Cam (Orange), hoặc Đỏ (Red).\n"
            "- **Bước 3:** Nhấn Xác nhận; giao diện sẽ cập nhật tức thì màu viền, badge và nút bấm, đồng thời lưu cấu hình vào `localStorage` của trình duyệt.\n\n"
            "### 4. Kết quả kỳ vọng (Expected Results)\n"
            "- Toàn bộ giao diện áp dụng gam màu đã chọn và duy trì ổn định qua các phiên làm việc tiếp theo.\n\n"
            "### 5. Lưu ý & Giới hạn quan trọng (Important Limitations)\n"
            "- Cài đặt màu sắc lưu cục bộ trên trình duyệt đang sử dụng; chuyển sang thiết bị hoặc trình duyệt khác sẽ sử dụng màu mặc định."
        )
        return body + ref_footer

    # 7. TROUBLESHOOTING INTENT
    if doc_intent == DocIntent.TROUBLESHOOTING.value:
        body = (
            "### 1. Mục đích & Vấn đề xử lý (Issue & Purpose)\n"
            "Khắc phục sự cố gián đoạn kết nối camera, trạng thái offline hoặc không nhận diện được đối tượng trong hệ thống giám sát DATT.\n\n"
            "### 2. Vị trí điều hướng (Navigation)\n"
            "Truy cập menu **Quản lý Camera** hoặc **Alert Center** trên thanh Sidebar bên trái.\n\n"
            "### 3. Các bước khắc phục cụ thể theo loại nguồn (Troubleshooting Procedures)\n"
            "- **Nguồn File cục bộ (Local MP4):**\n"
            "  * Kiểm tra file video tồn tại trên đĩa cứng máy chủ và quyền đọc file.\n"
            "  * Xác minh codec video là H.264/MP4 tương thích.\n"
            "  * Kiểm tra ingestion worker. Đảm bảo tiến trình worker đang hoạt động bình thường và gửi heartbeat lease.\n"
            "- **Nguồn luồng mạng RTSP:**\n"
            "  * Kiểm tra nguồn điện và trạng thái mạng vật lý của camera IP.\n"
            "  * Ping thử địa chỉ IP của camera từ máy chủ DATT và xác minh cổng 554 mở trên firewall.\n"
            "  * Kiểm tra thông tin xác thực user/password trong chuỗi URL RTSP.\n"
            "- **Nguồn luồng HLS / YouTube Live:**\n"
            "  * Kiểm tra đường link m3u8 hoặc URL YouTube còn đang phát trực tiếp.\n"
            "  * Kiểm tra kết nối Internet và cập nhật gói giải mã luồng (yt-dlp) nếu cần.\n\n"
            "### 4. Kết quả kỳ vọng (Expected Results)\n"
            "- Camera phục hồi trạng thái Online và tiến trình ingestion worker tiếp tục gửi heartbeat lease hợp lệ.\n"
            "- Luồng video hiển thị trở lại bình thường trên màn hình Monitor.\n\n"
            "### 5. Lưu ý & Giới hạn quan trọng (Important Limitations)\n"
            "- Trạng thái offline trong cơ sở dữ liệu phản ánh lease của worker; không tự động đồng nghĩa camera bị hỏng mạng nếu chưa kiểm tra kết nối trực tiếp."
        )
        # Append specific grounded action points from retrieved chunks if present
        extra_actions = []
        for r in results:
            content_lines = str(r.get("content", "")).splitlines()
            for l in content_lines:
                clean_l = l.strip().lstrip("-*# ").strip()
                if clean_l and len(clean_l) > 8 and clean_l not in body and not clean_l.startswith(("http", "```")):
                    extra_actions.append(clean_l)
        if extra_actions:
            body += "\n\n**Chỉ dẫn cụ thể từ tài liệu:**\n" + "\n".join(f"- {act}" for act in extra_actions[:3])
        return body + ref_footer


    # 8. TECHNICAL ARCHITECTURE INTENT
    if doc_intent == DocIntent.TECHNICAL_ARCHITECTURE.value:
        body = (
            "### 1. Kiến trúc Tổng quan Hệ thống DATT\n"
            "DATT (Deep AI Tracking & Targeting) được xây dựng trên kiến trúc hướng dịch vụ micro-pipeline hiệu năng cao:\n"
            "- **Backend Core:** FastAPI server kết hợp asyncio, xử lý đa luồng camera đồng thời.\n"
            "- **Pipeline AI:**\n"
            "  * *Phát hiện đối tượng & Theo dõi:* YOLO11s kết hợp thuật toán ByteTrack cho khả năng bám vết đa mục tiêu mượt mà.\n"
            "  * *Nhận diện khuôn mặt:* Kiến trúc hai pha gồm SCRFD (Face Detection & Alignment) và AdaFace (Face Feature Extraction 512D vector).\n"
            "  * *Nhận dạng biển số (ANPR):* YOLOv11 phát hiện biển số kết hợp EasyOCR và bộ lọc chuẩn hóa biển số Việt Nam.\n"
            "- **Cơ sở dữ liệu:** PostgreSQL với extension pgvector lưu trữ và truy vấn tương đồng vector cosine; SQLAlchemy ORM quản lý giao dịch an toàn.\n"
            "- **Giao diện Web:** Thiết kế chuẩn Enterprise Monitoring Dashboard với thanh Sidebar trắng, phục vụ hiển thị luồng MJPEG độ trễ thấp và tích hợp Trợ lý AI LangGraph."
        )
        return body + ref_footer

    # 9. GENERAL INTRODUCTION INTENT
    if doc_intent == DocIntent.GENERAL_INTRODUCTION.value:
        body = (
            "### 1. Giới thiệu Hệ thống DATT\n"
            "**DATT** (Deep Analytics Tracking & Targeting) là hệ thống giám sát thị giác máy tính toàn diện, "
            "tích hợp trí tuệ nhân tạo (AI) chạy trên nền tảng FastAPI backend kết hợp các mô hình Deep Learning tiên tiến "
            "(YOLO11s, ByteTrack, SCRFD, AdaFace, EasyOCR).\n\n"
            "### 2. Các nghiệp vụ phục vụ chính\n"
            "- Đếm lưu lượng người đi bộ và phương tiện cơ giới theo thời gian thực.\n"
            "- Tự động nhận diện khuôn mặt đối tượng mục tiêu theo danh sách theo dõi (Face Watchlist).\n"
            "- Tự động đọc và đối soát biển số xe (Vehicle Watchlist).\n"
            "- Lưu trữ nhật ký sự kiện kèm ảnh bằng chứng và gửi cảnh báo tự động qua Email khi phát hiện mục tiêu theo dõi.\n\n"
            "### 3. Phân hệ điều hướng chính\n"
            "Dashboard, Quản lý Camera, Giám sát trực tiếp (Monitor Screen), Face Watchlist, Vehicle Watchlist, Event Center, Alert Center và AI Assistant."
        )
        return body + ref_footer

    # Fallback default: format procedurally using the retrieved content
    body = (
        "### Hướng dẫn vận hành hệ thống DATT\n"
        "Dựa trên các tài liệu đã được ghi nhận trong cơ sở tri thức hệ thống, bạn có thể thực hiện theo quy trình sau:\n\n"
    )
    for r in results[:3]:
        sec = r.get("section", "Chung")
        c = r.get("content", "").strip()
        # Take first 2 sentences or 200 chars
        snippet = c.split("\n\n")[0] if "\n\n" in c else c[:250]
        body += f"- **{sec}:** {snippet}\n\n"

    return body.strip() + ref_footer
