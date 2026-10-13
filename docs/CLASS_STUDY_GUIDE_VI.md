# Sổ tay giải thích class dự án DATT

Ngày tổng hợp: 10/10/2026. Nội dung dựa trên mã nguồn trong workspace, không chỉ dựa trên tên class.

Phạm vi chính: **138 khai báo class** trong `src/` và `scripts/`, kể cả class lồng trong hàm. Các entry point `app.py`, `config.py`, `src/main.py` và `scripts/datt.py` chủ yếu dùng hàm. Class của thư viện/venv không phải code dự án nên không liệt kê. Class trong test được đưa vào phụ lục riêng.

## Cách trả lời mentor

> Class này thuộc phần …, dùng để …; đầu vào là …; trạng thái nó giữ là …; method quan trọng là …; kết quả được chuyển cho ….

Phân biệt: model ORM mô tả bảng; DTO/dataclass mang dữ liệu; service điều phối xử lý; repository truy cập DB; interface đặt hợp đồng; exception biểu diễn lỗi. Không phải class nào cũng chạy model AI.

## Bản đồ luồng

```text
RuntimeManager → CameraManager → reader → YOLODetector
    → PersonTracker / CarTracker → ZoneCounter / CarCounter
    → FaceEmbedder / AdaptiveFacePipeline → TargetMatcher
    → PlateDetector / LicensePlateReader → VehiclePlateManager
    → EventManager → DTO → DatabaseWorker → Repository → ORM → Database
    → NotificationService → SMTPEmailAdapter
    → SharedRuntimeState → StreamRequestHandler → web_server → React

Chat API → LangGraph AgentState → model / tools → câu trả lời
    → PostgresSaver hoặc MemorySaver (class thư viện, checkpoint.py cấu hình)
Tài liệu → IngestionService → DocumentChunk → embedding service → KnowledgeChunk
Câu hỏi → KnowledgeRetriever → RetrievedChunk → tool/LLM
```

## Số lượng theo nhóm

| Nhóm | Class |
|---|---:|
| `agent` | 20 |
| `config` | 1 |
| `counter` | 2 |
| `db` | 35 |
| `detector` | 2 |
| `events` | 9 |
| `face` | 5 |
| `notifications` | 4 |
| `ocr` | 10 |
| `ops` | 1 |
| `recognition` | 8 |
| `runtime` | 4 |
| `scripts` | 7 |
| `storage.py` | 5 |
| `stream` | 19 |
| `tracker` | 2 |
| `ui` | 3 |
| `utils` | 1 |

## Danh mục tra nhanh

| Class | File | Dùng để làm gì? |
|---|---|---|
| [ChatRequest](#class-1) | `src/agent/api/routes.py` | Kiểm tra và mô tả dữ liệu gửi lên API chat: message, thread_id và các thông tin phiên. user_id do client gửi không tự chứng minh người dùng đã đăng nhập. |
| [ChatResponse](#class-2) | `src/agent/api/routes.py` | Định nghĩa dữ liệu trả về sau một lượt chat: trạng thái, thread_id, câu trả lời, tool đã gọi và nguồn tham khảo. |
| [CreateConversationRequest](#class-3) | `src/agent/api/routes.py` | Kiểm tra payload tạo hội thoại: tiêu đề và thread_id tùy chọn cùng thông tin phiên. |
| [RenameConversationRequest](#class-4) | `src/agent/api/routes.py` | Kiểm tra payload đổi tên hội thoại, đặc biệt yêu cầu tiêu đề không rỗng và giới hạn độ dài. |
| [AgentConfig](#class-5) | `src/agent/config.py` | Tập trung cấu hình LLM, giới hạn thực thi agent, embedding và RAG; lấy cấu hình từ biến môi trường và cung cấp truy cập Database. |
| [LLMUnavailableException](#class-6) | `src/agent/llm.py` | Biểu diễn lỗi khi dịch vụ LLM chính và phương án dự phòng không đáp ứng được yêu cầu. |
| [ResilientChatModel](#class-7) | `src/agent/llm.py` | Bọc model chat bằng timeout, retry có backoff và fallback; cung cấp cùng giao diện bind_tools/invoke cho phần agent. |
| [CheckpointUnavailable](#class-8) | `src/agent/memory/checkpoint.py` | Báo rằng hệ thống không thể cung cấp lịch sử hội thoại bền vững theo chính sách cấu hình. |
| [MockChatModel](#class-9) | `src/agent/nodes.py` | Mô phỏng model chat bằng quy tắc xác định để kiểm thử/offline, không phải model LLM thật. |
| [DocumentChunk](#class-10) | `src/agent/rag/chunking.py` | Mang một đoạn tài liệu đã chia nhỏ: nội dung, số thứ tự và metadata. Đây là dữ liệu trung gian, không phải bản ghi ORM. |
| [BaseEmbeddingService](#class-11) | `src/agent/rag/embeddings.py` | Định nghĩa hợp đồng chung tạo vector cho tài liệu/câu hỏi và số chiều vector; các provider phải triển khai hợp đồng này. |
| [MockEmbeddingService](#class-12) | `src/agent/rag/embeddings.py` | Tạo vector giả ổn định bằng hash và chuẩn hóa L2 để kiểm thử; vector không biểu diễn ý nghĩa ngữ nghĩa. |
| [FastEmbedService](#class-13) | `src/agent/rag/embeddings.py` | Tạo embedding văn bản bằng model ONNX qua FastEmbed, tải model khi cần. Code hiện fallback sang Mock nếu tải hoặc suy luận lỗi. |
| [OpenAIEmbeddingService](#class-14) | `src/agent/rag/embeddings.py` | Tạo embedding văn bản qua OpenAIEmbeddings, tải client khi cần; thiếu API key thì fallback sang FastEmbed. |
| [IngestionResult](#class-15) | `src/agent/rag/ingestion.py` | Mang báo cáo nhập tài liệu: ID, tiêu đề, nguồn, loại, số chunk tạo được, trạng thái và lỗi. |
| [IngestionService](#class-16) | `src/agent/rag/ingestion.py` | Điều phối đọc tài liệu, tính hash, chia đoạn, tạo embedding và ghi tài liệu/chunk vào database; quản lý vòng đời DB qua context manager. |
| [DocIntent](#class-17) | `src/agent/rag/intent.py` | Enum phân loại ý định tra cứu tài liệu để retrieval chọn/lọc nguồn phù hợp. |
| [RetrievedChunk](#class-18) | `src/agent/rag/retrieval.py` | Mang kết quả tìm kiếm một đoạn tài liệu với điểm liên quan và thông tin trích dẫn như tên tài liệu, mục, trang. |
| [KnowledgeRetriever](#class-19) | `src/agent/rag/retrieval.py` | Tạo embedding câu hỏi, truy xuất và lọc các đoạn liên quan theo vector/ý định; dùng RetrievedChunk nội bộ rồi trả dictionary có status/results cho tool. |
| [AgentState](#class-20) | `src/agent/state.py` | Schema trạng thái của graph gồm lịch sử messages kế thừa và thông tin user/thread, xác thực, bộ đếm tool và lỗi; không phải service tự chạy. |
| [CameraInfo](#class-21) | `src/config/camera_config.py` | Mang cấu hình nguồn camera: ID, tên, loại, URL, kích thước, trạng thái và liên kết video; có thể chuyển thành dictionary. |
| [ZoneCounter](#class-22) | `src/counter/zone_counter.py` | Đếm số track hiện diện trong khung hình hoặc vùng polygon, đồng thời trả tập ID hiển thị; không phải tổng người duy nhất đã từng xuất hiện. |
| [CarCounter](#class-23) | `src/counter/zone_counter.py` | Chuyên biệt ZoneCounter cho occupancy của xe; tái sử dụng logic vùng và reset. |
| [Database](#class-24) | `src/db/database.py` | Quản lý SQLAlchemy engine, pool kết nối và session; cung cấp transaction tự commit/rollback và quản lý engine dùng chung trong tiến trình. |
| [MigrationHeadError](#class-25) | `src/db/migration_head.py` | Báo lỗi khi không xác định được duy nhất migration head của repository. |
| [UTCDateTime](#class-26) | `src/db/models.py` | Kiểu SQLAlchemy tùy biến cho datetime: từ chối thời gian không có timezone khi ghi và khôi phục timezone khi đọc SQLite. |
| [Base](#class-27) | `src/db/models.py` | Lớp gốc SQLAlchemy declarative để các model cùng tham gia registry và metadata của schema. |
| [Identity](#class-28) | `src/db/models.py` | Mixin cung cấp cột ID UUID làm khóa chính dùng chung cho các model database. |
| [Camera](#class-29) | `src/db/models.py` | Model ORM của bảng cameras: cấu hình camera, nguồn liên kết, thông tin hoạt động và trạng thái. |
| [VideoSource](#class-30) | `src/db/models.py` | Model ORM của bảng video_sources: metadata file video, storage_path, kích thước, thời lượng, FPS và trạng thái; không chứa trực tiếp byte video. |
| [Zone](#class-31) | `src/db/models.py` | Model ORM lưu vùng polygon của camera và trạng thái bật/tắt vùng. |
| [Target](#class-32) | `src/db/models.py` | Model ORM bảng targets: danh tính/đối tượng cần theo dõi, ảnh tham chiếu, embedding và trạng thái. |
| [TargetEmbedding](#class-33) | `src/db/models.py` | Model ORM lưu vector khuôn mặt 512 chiều gắn với target, kèm model và ảnh nguồn. |
| [DetectionEvent](#class-34) | `src/db/models.py` | Model ORM lưu một sự kiện phát hiện: camera/video, frame, track, thời gian và dữ liệu phát hiện. |
| [VehicleEvent](#class-35) | `src/db/models.py` | Model ORM lưu thông tin sự kiện xe và liên kết với sự kiện phát hiện/video. |
| [PlateEvent](#class-36) | `src/db/models.py` | Model ORM lưu kết quả đọc biển số, confidence, crop và trạng thái, liên kết với VehicleEvent. |
| [FaceEvent](#class-37) | `src/db/models.py` | Model ORM lưu kết quả nhận diện khuôn mặt: target, similarity, quyết định, track và bằng chứng. |
| [VehiclePassage](#class-38) | `src/db/models.py` | Model ORM lưu một lần xe xuất hiện liên tục tại camera, từ lúc thấy đến kết thúc, gồm biển số và bằng chứng. |
| [BusinessEvent](#class-39) | `src/db/models.py` | Model ORM lưu sự kiện nghiệp vụ có ý nghĩa và khóa idempotency để tránh ghi lặp. |
| [Notification](#class-40) | `src/db/models.py` | Model ORM của outbox gửi thông báo và lịch sử giao nhận: người nhận, trạng thái, retry và liên kết sự kiện; không phải email đã gửi chắc chắn. |
| [VehicleWatchlist](#class-41) | `src/db/models.py` | Model ORM lưu danh sách biển số cần theo dõi cùng thông tin xe/chủ xe và trạng thái. |
| [VehicleWatchlistResult](#class-42) | `src/db/models.py` | Model ORM lưu snapshot quyết định đối chiếu watchlist tại lúc ghi PlateEvent, để giữ kết quả lịch sử. |
| [KnowledgeDocument](#class-43) | `src/db/models.py` | Model ORM lưu danh mục tài liệu RAG: tiêu đề, nguồn, loại, hash chống trùng và metadata. |
| [KnowledgeChunk](#class-44) | `src/db/models.py` | Model ORM lưu nội dung chunk của tài liệu và embedding 384 chiều phục vụ tìm kiếm. |
| [AgentConversation](#class-45) | `src/db/models.py` | Model ORM lưu registry hội thoại: user, thread, tiêu đề, thời gian và trạng thái; messages được lưu riêng qua checkpoint LangGraph. |
| [VectorSearchResult](#class-46) | `src/db/repositories/__init__.py` | Mang kết quả tìm kiếm vector và dữ liệu target liên quan; hỗ trợ truy cập/chuyển thành dictionary. |
| [CameraRepository](#class-47) | `src/db/repositories/__init__.py` | Repository CRUD cho Camera; kế thừa các method của Repository dù không khai báo method riêng. |
| [VideoSourceRepository](#class-48) | `src/db/repositories/__init__.py` | Repository quản lý VideoSource, bổ sung tìm theo storage_path và truy vấn danh sách nguồn. |
| [ZoneRepository](#class-49) | `src/db/repositories/__init__.py` | Repository CRUD cho vùng camera; dùng các method kế thừa từ Repository. |
| [TargetRepository](#class-50) | `src/db/repositories/__init__.py` | Repository quản lý target và logic tạo bản ghi target. |
| [DetectionEventRepository](#class-51) | `src/db/repositories/__init__.py` | Repository truy vấn và CRUD sự kiện phát hiện theo bộ lọc. |
| [VehicleEventRepository](#class-52) | `src/db/repositories/__init__.py` | Repository ghi và truy vấn sự kiện xe. |
| [PlateEventRepository](#class-53) | `src/db/repositories/__init__.py` | Repository ghi/truy vấn biển số và tìm bản ghi theo sự kiện xe. |
| [FaceEventRepository](#class-54) | `src/db/repositories/__init__.py` | Repository ghi và truy vấn sự kiện khuôn mặt. |
| [VehiclePassageRepository](#class-55) | `src/db/repositories/__init__.py` | Repository quản lý lần xuất hiện liên tục của xe, upsert theo session_key và thống kê loại xe. |
| [BusinessEventRepository](#class-56) | `src/db/repositories/__init__.py` | Repository sự kiện nghiệp vụ; insert idempotent theo khóa chống trùng và truy vấn sự kiện. |
| [TargetEmbeddingRepository](#class-57) | `src/db/repositories/__init__.py` | Repository kiểm tra vector khuôn mặt, ghi/cập nhật embedding và tìm target tương tự. |
| [Repository](#class-58) | `src/db/repositories/base.py` | Lớp CRUD generic trên SQLAlchemy session: create/get/list/update/delete, kiểm tra field/filter và phân trang; không tự sở hữu toàn bộ transaction nghiệp vụ. |
| [DetectionsData](#class-59) | `src/detector/yolo_detector.py` | Container kết quả detector dạng dictionary nhưng hỗ trợ truy cập thuộc tính xyxy/confidence/class_id; tách output khỏi framework Ultralytics. |
| [YOLODetector](#class-60) | `src/detector/yolo_detector.py` | Bọc model YOLO để tải/warmup và phát hiện đối tượng trong frame; trả bounding box, confidence, class_id chứ chưa gán track ID. |
| [DatabaseWorker](#class-61) | `src/events/db_worker.py` | Worker nền nhận snapshot DTO qua queue rồi ghi DB theo batch/transaction; tách độ trễ ghi DB khỏi vòng xử lý frame. |
| [VehiclePassageDTO](#class-62) | `src/events/event_dto.py` | Snapshot dữ liệu passage của xe gửi từ runtime sang worker DB; mang ID, thời gian, biển số và đường dẫn bằng chứng. |
| [BusinessEventDTO](#class-63) | `src/events/event_dto.py` | Snapshot sự kiện nghiệp vụ chuyển sang worker DB, gồm thời gian, metadata và idempotency_key. |
| [FaceEventDTO](#class-64) | `src/events/event_dto.py` | Snapshot kết quả nhận diện khuôn mặt chuyển sang worker DB, gồm target, similarity, quyết định và crop. |
| [VehiclePassage](#class-65) | `src/events/event_manager.py` | Trạng thái passage xe đang chạy trong RAM, tích lũy thời gian/ảnh/biển số rồi chuyển thành VehiclePassageDTO để ghi DB. |
| [EventManager](#class-66) | `src/events/event_manager.py` | Chuyển kết quả tracking/đếm/nhận diện thành sự kiện nghiệp vụ, quản lý passage và đưa DTO vào worker ghi DB; không tự thực hiện YOLO. |
| [EventStorage](#class-67) | `src/events/event_storage.py` | Nhánh lưu sự kiện đếm người và snapshot bằng SQLite, có lưu passage; cần phân biệt với DatabaseWorker và PostgreSQL chính. |
| [Episode](#class-68) | `src/events/policy.py` | Mang trạng thái một đợt vượt ngưỡng: lúc bắt đầu, token và trạng thái đã kích hoạt. |
| [ThresholdEpisodes](#class-69) | `src/events/policy.py` | Quản lý đợt vượt ngưỡng theo camera/vị trí, phát sự kiện khi đủ điều kiện và tránh phát lặp trong cùng đợt. |
| [CandidateBuffer](#class-70) | `src/face/adaptive_pipeline.py` | Giữ lịch sử ứng viên khuôn mặt có giới hạn theo camera/track; tránh nhận nhiều representation của cùng frame. |
| [AdaptiveFacePipeline](#class-71) | `src/face/adaptive_pipeline.py` | Xử lý khuôn mặt sau phát hiện SCRFD: kiểm tra hình học, căn chỉnh/biến đổi theo điều kiện và tạo embedding AdaFace; không tự đối chiếu gallery. |
| [AdaFaceEmbedder](#class-72) | `src/face/experimental_adaface.py` | Bọc model AdaFace ONNX để tạo vector khuôn mặt 512 chiều được chuẩn hóa; module đặt tên experimental nhưng có thể được code khác gọi. |
| [FaceDiagInfo](#class-73) | `src/face/face_embedder.py` | Mang thông tin chẩn đoán phát hiện/embedding khuôn mặt: model/provider, bbox, confidence, lý do từ chối và kiểm tra vector. |
| [FaceEmbedder](#class-74) | `src/face/face_embedder.py` | Singleton phân tích khuôn mặt: phát hiện SCRFD, kiểm tra ánh sáng/landmark/chất lượng, căn chỉnh và trích xuất embedding; không quyết định target nào khớp. |
| [NotificationAdapter](#class-75) | `src/notifications/base.py` | Protocol giao diện send cho kênh thông báo; cho phép service dùng adapter thật hoặc giả trong test mà không phụ thuộc SMTP cụ thể. |
| [EmailConfig](#class-76) | `src/notifications/config.py` | Mang cấu hình SMTP và chính sách cooldown/retry, đọc từ môi trường và kiểm tra cấu hình có đủ không. |
| [SMTPEmailAdapter](#class-77) | `src/notifications/email.py` | Tạo email và gửi bằng SMTP theo EmailConfig; thực thi giao diện gửi thông báo. |
| [NotificationService](#class-78) | `src/notifications/service.py` | Quản lý transactional outbox, chống gửi trùng/cooldown và worker giao email có retry; chỉ worker giao nhận thực hiện kết nối gửi email. |
| [PlateBox](#class-79) | `src/ocr/plate_detector.py` | NamedTuple mang bounding box biển số được phát hiện và confidence. |
| [PlateDetector](#class-80) | `src/ocr/plate_detector.py` | Singleton bọc model phát hiện vị trí biển số trong ảnh; tìm vùng biển số, không đọc ký tự. |
| [LinePlate](#class-81) | `src/ocr/plate_line_recognizer.py` | Mang kết quả đọc một dòng/biển số cùng điểm và thông tin phụ do recognizer tạo. |
| [PlateLineRecognizer](#class-82) | `src/ocr/plate_line_recognizer.py` | Chuẩn bị ảnh và đọc ký tự theo dòng/vùng biển số bằng recognizer; hỗ trợ lựa chọn vùng và đọc cả biển. |
| [PlateCandidate](#class-83) | `src/ocr/plate_reader.py` | Mang ứng viên kết quả biển số từ OCR để đánh giá và lựa chọn. |
| [LicensePlateReader](#class-84) | `src/ocr/plate_reader.py` | Điều phối tìm/cắt biển số, chỉnh phối cảnh/nghiêng, tạo biến thể tiền xử lý và OCR để lấy nội dung biển số. |
| [PlateTrackState](#class-85) | `src/ocr/plate_tracker.py` | Giữ trạng thái đọc biển số theo track qua nhiều frame, gồm ứng viên và kết quả xác nhận; không tương đương bản ghi PlateEvent. |
| [_OcrJob](#class-86) | `src/ocr/plate_tracker.py` | NamedTuple đóng gói tác vụ OCR để chuyển từ vòng tracking sang worker nền. |
| [_OcrWorker](#class-87) | `src/ocr/plate_tracker.py` | Worker OCR nền có queue, nhận job và trả kết quả; cho phép hủy/xóa job và tách inference OCR khỏi vòng frame. |
| [VehiclePlateManager](#class-88) | `src/ocr/plate_tracker.py` | Quản lý PlateTrackState theo xe, chọn/lập lịch job OCR và hợp nhất kết quả qua nhiều frame. |
| [SafeOutput](#class-89) | `src/ops/runner.py` | Bọc stdout/stderr để che giá trị bí mật và URL trong log tiến trình được CLI giám sát; không thay đổi cấu hình kết nối. |
| [ColorAnalysisResult](#class-90) | `src/recognition/color_extractor.py` | Mang kết quả phân tích màu trang phục: tên màu và thông tin định lượng đi kèm. |
| [ClothingColorExtractor](#class-91) | `src/recognition/color_extractor.py` | Cắt vùng thân người và phân tích màu trang phục; không dùng để nhận diện khuôn mặt. |
| [TargetRegistrationError](#class-92) | `src/recognition/target_matcher.py` | Lỗi nghiệp vụ đăng ký target khi ảnh/embedding không đáp ứng yêu cầu, để caller trả lỗi phù hợp. |
| [Target](#class-93) | `src/recognition/target_matcher.py` | Đối tượng target trong gallery RAM: tên, vector và thông tin tham chiếu dùng để đối chiếu runtime; khác model ORM Target. |
| [BestFaceState](#class-94) | `src/recognition/target_matcher.py` | Giữ ứng viên khuôn mặt và trạng thái nhận diện tốt nhất theo track qua nhiều frame. |
| [TargetMatchInfo](#class-95) | `src/recognition/target_matcher.py` | Mang kết quả đối chiếu một track với target cùng thông tin quyết định/độ tương đồng. |
| [TargetManager](#class-96) | `src/recognition/target_matcher.py` | Quản lý gallery target trong RAM: đăng ký từ ảnh, thêm từ DB, chọn target cần theo dõi và xóa target. |
| [TargetMatcher](#class-97) | `src/recognition/target_matcher.py` | Duyệt track người, lấy khuôn mặt đủ chất lượng, tạo embedding và đối chiếu gallery; giữ trạng thái theo track và trả kết quả matching. |
| [RuntimeManager](#class-98) | `src/runtime/runtime_manager.py` | Điều phối pipeline AI và web server, kiểm tra cổng, quản lý thread/tín hiệu và shutdown; không phải model inference. |
| [TelemetrySnapshot](#class-99) | `src/runtime/shared_state.py` | Snapshot các chỉ số vận hành để trả qua API: FPS, độ trễ, thiết bị, số đối tượng và trạng thái. |
| [Observation](#class-100) | `src/runtime/shared_state.py` | Mang một quan sát/frame và metadata đồng bộ để gắn hình ảnh với đúng thời điểm/nguồn. |
| [SharedRuntimeState](#class-101) | `src/runtime/shared_state.py` | Kho trạng thái dùng chung có đồng bộ thread giữa pipeline và HTTP: frame mới nhất, observation, telemetry, nguồn và trạng thái. |
| [StorageUploadTooLarge](#class-102) | `src/storage.py` | Loại lỗi riêng khi storage từ chối object vượt giới hạn kích thước. |
| [StorageBackend](#class-103) | `src/storage.py` | Interface lưu file: save/open/exists/delete/materialize; DB chỉ cần giữ object key, không phụ thuộc nhà cung cấp. |
| [LocalStorageBackend](#class-104) | `src/storage.py` | Đọc/ghi media trên filesystem local trong root cấu hình, có kiểm tra key/đường dẫn. |
| [ExternalStorageBackend](#class-105) | `src/storage.py` | Đọc/ghi media qua filesystem fsspec bên ngoài và materialize thành bản local dùng tạm. |
| [SupabaseStorageBackend](#class-106) | `src/storage.py` | Đọc/ghi media qua API Supabase Storage; tải object thành file local khi cần xử lý. |
| [NormalizedCamera](#class-107) | `src/stream/caltrans_service.py` | Cấu trúc chuẩn hóa metadata camera từ catalog Caltrans để hệ thống sử dụng thống nhất. |
| [CaltransCameraService](#class-108) | `src/stream/caltrans_service.py` | Lấy catalog camera Caltrans, cache và hỗ trợ tìm camera theo ID; có cơ chế phục vụ dữ liệu dự phòng. |
| [CameraManager](#class-109) | `src/stream/camera_manager.py` | Chọn/đổi/dừng nguồn video và quản lý reader tương ứng; cung cấp frame và chỉ số sức khỏe cho pipeline. |
| [HLSFrame](#class-110) | `src/stream/direct_hls.py` | Mang frame HLS và metadata thời gian/sequence để reader và pacer trao đổi dữ liệu. |
| [DirectHLSReader](#class-111) | `src/stream/direct_hls.py` | Đọc HLS trực tiếp bằng FFmpeg, có worker giải mã, buffer/pacer và thống kê jitter/độ trễ để cấp frame ổn định. |
| [PreviewManager](#class-112) | `src/stream/preview_manager.py` | Quản lý xem trước nguồn video nhẹ không chạy AI, lấy snapshot hoặc JPEG frame và dừng tài nguyên preview. |
| [SeattleCamera](#class-113) | `src/stream/seattle_sdot_service.py` | Mang metadata camera từ Seattle SDOT và chuyển sang dictionary dùng cho API. |
| [SeattleSDOTService](#class-114) | `src/stream/seattle_sdot_service.py` | Lấy/cache catalog Seattle SDOT, chuẩn bị URL stream và tìm camera theo stream name. |
| [ThumbnailService](#class-115) | `src/stream/thumbnail_service.py` | Lấy ảnh đại diện camera từ snapshot hoặc frame HLS, lưu cache và xóa cache khi cần. |
| [VideoFrame](#class-116) | `src/stream/video_source.py` | Mang frame video và metadata phục vụ giao diện đọc frame của các reader. |
| [BaseVideoReader](#class-117) | `src/stream/video_source.py` | Định nghĩa giao diện vòng đời reader start/stop/read và các chỉ số trạng thái; reader file/VOD triển khai cùng giao diện. |
| [LocalVideoReader](#class-118) | `src/stream/video_source.py` | Đọc file video local trong thread với pacing/buffer, cung cấp frame mới và quản lý EOF/vòng đời. |
| [YouTubeVODReader](#class-119) | `src/stream/video_source.py` | Resolve URL YouTube VOD rồi giải mã bằng FFmpeg, điều tiết phát frame và xử lý EOF/loop/dừng subprocess. |
| [StreamCacheEntry](#class-120) | `src/stream/youtube_resolver.py` | Mang URL stream đã resolve cùng TTL, thời gian thành công/thất bại và trạng thái còn dùng được. |
| [ResolverMetrics](#class-121) | `src/stream/youtube_resolver.py` | Mang bộ đếm hoạt động resolve YouTube, cache hit/miss và các lỗi mạng để phục vụ telemetry. |
| [SharedRateLimitPolicy](#class-122) | `src/stream/youtube_resolver.py` | Giữ trạng thái cooldown/backoff dùng chung khi truy cập YouTube bị giới hạn hoặc lỗi. |
| [YouTubeStreamResolver](#class-123) | `src/stream/youtube_resolver.py` | Resolve link YouTube thành URL media trực tiếp bằng yt-dlp; cache, gộp request đồng thời và rate limit/backoff để không resolve mỗi frame. |
| [CapturedFrame](#class-124) | `src/stream/youtube_stream.py` | Mang frame camera cùng sequence, thời điểm capture và latency capture. |
| [CameraReader](#class-125) | `src/stream/youtube_stream.py` | Đọc luồng video qua FFmpeg với frame mới nhất, reconnect và giám sát stale frame; là reader, khác CameraManager quản lý nguồn. |
| [PersonTracker](#class-126) | `src/tracker/bytetrack_tracker.py` | Bọc ByteTrack cho người, gán ID qua nhiều frame và predict giữa các lần chạy detector. |
| [CarTracker](#class-127) | `src/tracker/bytetrack_tracker.py` | Bọc ByteTrack độc lập cho xe để tách trạng thái tracking người/xe; ID phải được hiểu trong đúng loại/nguồn. |
| [MJPEGReader](#class-128) | `src/ui/mjpeg_client.py` | Client đọc stream MJPEG, giữ frame mới nhất theo phiên, retry và dọn kết nối khi phiên không còn được sử dụng. |
| [StreamRequestHandler](#class-129) | `src/ui/video_stream.py` | HTTP handler của server pipeline AI: route stream, telemetry, điều khiển camera, preview và một số thao tác target/sự kiện. |
| [MJPEGServer](#class-130) | `src/ui/video_stream.py` | Quản lý vòng đời HTTP server có thread cho stream MJPEG và quản lý client stream đồng thời. |
| [FPSMeter](#class-131) | `src/utils/fps.py` | Đo FPS bằng cửa sổ trượt các timestamp frame; phục vụ HUD/log chứ không tạo thêm tốc độ xử lý. |
| [Blocker](#class-132) | `scripts/colab_startup.py` | Lỗi dừng quy trình startup Colab với thông điệp tĩnh không chứa credential. |
| [Startup](#class-133) | `scripts/colab_startup.py` | Điều phối các bước startup/validation Colab: kiểm tra môi trường, gọi CLI, khởi động và kiểm tra HTTP/runtime. |
| [SessionProbe](#class-134) | `scripts/diagnose_face_snapshot.py` | Wrapper session trong script chẩn đoán khuôn mặt, ghi nhận thao tác suy luận để quan sát hành vi; không phải session DB nghiệp vụ. |
| [DummyTracks](#class-135) | `scripts/validate_e2e_postgres.py` | Dữ liệu track giả trong script kiểm tra end-to-end PostgreSQL, thay detector thật để mô phỏng. |
| [DummyPlateState](#class-136) | `scripts/validate_e2e_postgres.py` | Trạng thái biển số giả trong script kiểm tra end-to-end PostgreSQL. |
| [AuditManager](#class-137) | `scripts/validate_plate_runtime.py` | Subclass VehiclePlateManager dùng trong script validation để quan sát việc áp dụng kết quả OCR. |
| [MockDetections](#class-138) | `scripts/verify_overlay_on_real_frame.py` | Mô phỏng kết quả detections cho script xác minh overlay trên frame thật. |

## Module `src/agent/api/routes.py`

<a id="class-1"></a>

### 1. `ChatRequest`

Nguồn: [src/agent/api/routes.py:48](../src/agent/api/routes.py#L48). Loại: **Schema API Pydantic**.

**Dùng để làm gì / câu trả lời ngắn:** Kiểm tra và mô tả dữ liệu gửi lên API chat: message, thread_id và các thông tin phiên. user_id do client gửi không tự chứng minh người dùng đã đăng nhập.

**Kế thừa trực tiếp:** `BaseModel`

**Các trường khai báo trực tiếp:**

```python
message: str = Field(..., min_length=1, description='User prompt or query')
thread_id: str | None = Field(default=None, description='Conversation session identifier')
user_id: str | None = Field(default=None, description='Optional client user ID claim')
session_id: str | None = Field(default=None, description='Optional client session identifier')
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-2"></a>

### 2. `ChatResponse`

Nguồn: [src/agent/api/routes.py:55](../src/agent/api/routes.py#L55). Loại: **Schema API Pydantic**.

**Dùng để làm gì / câu trả lời ngắn:** Định nghĩa dữ liệu trả về sau một lượt chat: trạng thái, thread_id, câu trả lời, tool đã gọi và nguồn tham khảo.

**Kế thừa trực tiếp:** `BaseModel`

**Các trường khai báo trực tiếp:**

```python
status: str
thread_id: str
reply: str
tools_called: list[str] = Field(default_factory=list)
sources: list[dict[str, Any]] = Field(default_factory=list)
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-3"></a>

### 3. `CreateConversationRequest`

Nguồn: [src/agent/api/routes.py:63](../src/agent/api/routes.py#L63). Loại: **Schema API Pydantic**.

**Dùng để làm gì / câu trả lời ngắn:** Kiểm tra payload tạo hội thoại: tiêu đề và thread_id tùy chọn cùng thông tin phiên.

**Kế thừa trực tiếp:** `BaseModel`

**Các trường khai báo trực tiếp:**

```python
title: str | None = Field(default=None, max_length=255, description='Initial conversation title')
thread_id: str | None = Field(default=None, max_length=128, description='Optional pre-allocated thread ID')
user_id: str | None = Field(default=None, description='Optional client user ID claim')
session_id: str | None = Field(default=None, description='Optional client session identifier')
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-4"></a>

### 4. `RenameConversationRequest`

Nguồn: [src/agent/api/routes.py:70](../src/agent/api/routes.py#L70). Loại: **Schema API Pydantic**.

**Dùng để làm gì / câu trả lời ngắn:** Kiểm tra payload đổi tên hội thoại, đặc biệt yêu cầu tiêu đề không rỗng và giới hạn độ dài.

**Kế thừa trực tiếp:** `BaseModel`

**Các trường khai báo trực tiếp:**

```python
title: str = Field(..., min_length=1, max_length=255, description='New conversation title')
user_id: str | None = Field(default=None, description='Optional client user ID claim')
session_id: str | None = Field(default=None, description='Optional client session identifier')
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/agent/config.py`

<a id="class-5"></a>

### 5. `AgentConfig`

Nguồn: [src/agent/config.py:14](../src/agent/config.py#L14). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Tập trung cấu hình LLM, giới hạn thực thi agent, embedding và RAG; lấy cấu hình từ biến môi trường và cung cấp truy cập Database.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
llm_provider: str = os.getenv('DATT_AGENT_LLM_PROVIDER') or os.getenv('AGENT_LLM_PROVIDER', 'google_genai')
model_name: str = os.getenv('DATT_AGENT_LLM_MODEL') or os.getenv('AGENT_MODEL_NAME', 'gemini-3.8-flash')
temperature: float = float(os.getenv('DATT_AGENT_LLM_TEMPERATURE') or os.getenv('AGENT_TEMPERATURE', '0.1'))
timeout_seconds: float = float(os.getenv('DATT_AGENT_LLM_TIMEOUT_SECONDS') or os.getenv('AGENT_TIMEOUT_SEC', '30.0'))
max_retries: int = int(os.getenv('DATT_AGENT_LLM_MAX_RETRIES', '3'))
fallback_provider: str | None = os.getenv('DATT_AGENT_LLM_FALLBACK_PROVIDER')
fallback_model: str | None = os.getenv('DATT_AGENT_LLM_FALLBACK_MODEL')
openai_api_key: str | None = os.getenv('OPENAI_API_KEY')
gemini_api_key: str | None = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
recursion_limit: int = int(os.getenv('AGENT_RECURSION_LIMIT', '15'))
execution_timeout_sec: float = float(os.getenv('AGENT_TIMEOUT_SEC', '30.0'))
tool_timeout_sec: float = float(os.getenv('AGENT_TOOL_TIMEOUT_SEC', '10.0'))
max_tool_repeats: int = int(os.getenv('AGENT_MAX_TOOL_REPEATS', '2'))
max_tool_cycles: int = int(os.getenv('DATT_AGENT_MAX_TOOL_CYCLES') or os.getenv('AGENT_MAX_TOOL_CYCLES', '4'))
max_total_tool_calls: int = int(os.getenv('DATT_AGENT_MAX_TOTAL_TOOL_CALLS') or os.getenv('AGENT_MAX_TOTAL_TOOL_CALLS', '8'))
max_history_messages: int = int(os.getenv('AGENT_MAX_HISTORY_MESSAGES', '20'))
trim_threshold_tokens: int = int(os.getenv('AGENT_TRIM_THRESHOLD_TOKENS', '4000'))
embedding_provider: str = os.getenv('DATT_AGENT_EMBEDDING_PROVIDER') or os.getenv('AGENT_EMBEDDING_PROVIDER', 'fastembed')
embedding_model: str = os.getenv('DATT_AGENT_EMBEDDING_MODEL') or os.getenv('AGENT_EMBEDDING_MODEL', 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
embedding_dim: int = int(os.getenv('DATT_AGENT_EMBEDDING_DIM') or os.getenv('AGENT_EMBEDDING_DIM', '384'))
rag_chunk_size: int = int(os.getenv('AGENT_RAG_CHUNK_SIZE', '800'))
rag_chunk_overlap: int = int(os.getenv('AGENT_RAG_CHUNK_OVERLAP', '100'))
rag_top_k: int = int(os.getenv('AGENT_RAG_TOP_K', '4'))
rag_score_threshold: float = float(os.getenv('AGENT_RAG_SCORE_THRESHOLD', '0.50'))
docs_dir: Path = PROJECT_ROOT / 'docs'
database_url: str | None = os.getenv('DATT_DATABASE_URL')
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `get_database(self) → Any` | Instantiate a Database instance bound directly to the resolved database URL. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/agent/llm.py`

<a id="class-6"></a>

### 6. `LLMUnavailableException`

Nguồn: [src/agent/llm.py:14](../src/agent/llm.py#L14). Loại: **Exception / loại lỗi**.

**Dùng để làm gì / câu trả lời ngắn:** Biểu diễn lỗi khi dịch vụ LLM chính và phương án dự phòng không đáp ứng được yêu cầu.

**Kế thừa trực tiếp:** `Exception`

**Trạng thái được gán trong constructor:** `reason`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, message: str='LLM service unavailable', reason: str='provider_error')` | Khởi tạo cấu hình, dependency và trạng thái của instance. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/nodes.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-7"></a>

### 7. `ResilientChatModel`

Nguồn: [src/agent/llm.py:22](../src/agent/llm.py#L22). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Bọc model chat bằng timeout, retry có backoff và fallback; cung cấp cùng giao diện bind_tools/invoke cho phần agent.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `backoff_base_sec`, `fallback_model`, `max_retries`, `primary_model`, `timeout_seconds`, `tools`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, primary_model: Any, fallback_model: Any \| None=None, timeout_seconds: float \| None=None, max_retries: int \| None=None, backoff_base_sec: float=0.5)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `bind_tools(self, tools: list[Any]) → 'ResilientChatModel'` | Bind tools to both primary and fallback models. |
| `_is_auth_error(exc: Exception) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `_is_retriable_error(exc: Exception) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `_invoke_with_retry(self, model: Any, messages: list[BaseMessage]) → AIMessage` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `invoke(self, messages: list[BaseMessage]) → AIMessage` | Invoke LLM with primary model, bounded retries, and optional fallback. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/agent/memory/checkpoint.py`

<a id="class-8"></a>

### 8. `CheckpointUnavailable`

Nguồn: [src/agent/memory/checkpoint.py:38](../src/agent/memory/checkpoint.py#L38). Loại: **Exception / loại lỗi**.

**Dùng để làm gì / câu trả lời ngắn:** Báo rằng hệ thống không thể cung cấp lịch sử hội thoại bền vững theo chính sách cấu hình.

**Kế thừa trực tiếp:** `RuntimeError`

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/agent/nodes.py`

<a id="class-9"></a>

### 9. `MockChatModel`

Nguồn: [src/agent/nodes.py:59](../src/agent/nodes.py#L59). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Mô phỏng model chat bằng quy tắc xác định để kiểm thử/offline, không phải model LLM thật.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `tools`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, tools: list[Any] \| None=None) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `bind_tools(self, tools: list[Any]) → 'MockChatModel'` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `invoke(self, messages: list[BaseMessage]) → AIMessage` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/llm.py`, `scripts/agent_smoke.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/agent/rag/chunking.py`

<a id="class-10"></a>

### 10. `DocumentChunk`

Nguồn: [src/agent/rag/chunking.py:13](../src/agent/rag/chunking.py#L13). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang một đoạn tài liệu đã chia nhỏ: nội dung, số thứ tự và metadata. Đây là dữ liệu trung gian, không phải bản ghi ORM.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
content: str
chunk_index: int
metadata: dict[str, Any] = field(default_factory=dict)
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/agent/rag/embeddings.py`

<a id="class-11"></a>

### 11. `BaseEmbeddingService`

Nguồn: [src/agent/rag/embeddings.py:16](../src/agent/rag/embeddings.py#L16). Loại: **Interface / hợp đồng**.

**Dùng để làm gì / câu trả lời ngắn:** Định nghĩa hợp đồng chung tạo vector cho tài liệu/câu hỏi và số chiều vector; các provider phải triển khai hợp đồng này.

**Kế thừa trực tiếp:** `ABC`

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `embed_documents(self, texts: list[str]) → list[list[float]]` | Generate embeddings for a batch of texts. |
| `embed_query(self, text: str) → list[float]` | Generate embedding for a single query text. |
| `dimension(self) → int` | Vector dimensionality. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/rag/ingestion.py`, `src/agent/rag/retrieval.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-12"></a>

### 12. `MockEmbeddingService`

Nguồn: [src/agent/rag/embeddings.py:36](../src/agent/rag/embeddings.py#L36). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Tạo vector giả ổn định bằng hash và chuẩn hóa L2 để kiểm thử; vector không biểu diễn ý nghĩa ngữ nghĩa.

**Kế thừa trực tiếp:** `BaseEmbeddingService`

**Trạng thái được gán trong constructor:** `_dim`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, dimension: int=384) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `dimension(self) → int` | Trả số chiều embedding. |
| `_generate(self, text: str) → list[float]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `embed_documents(self, texts: list[str]) → list[list[float]]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `embed_query(self, text: str) → list[float]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-13"></a>

### 13. `FastEmbedService`

Nguồn: [src/agent/rag/embeddings.py:64](../src/agent/rag/embeddings.py#L64). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Tạo embedding văn bản bằng model ONNX qua FastEmbed, tải model khi cần. Code hiện fallback sang Mock nếu tải hoặc suy luận lỗi.

**Kế thừa trực tiếp:** `BaseEmbeddingService`

**Trạng thái được gán trong constructor:** `_dim`, `_model`, `_model_name`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, model_name: str='BAAI/bge-small-en-v1.5', dimension: int=384) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `_load_model(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `dimension(self) → int` | Trả số chiều embedding. |
| `embed_documents(self, texts: list[str]) → list[list[float]]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `embed_query(self, text: str) → list[float]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-14"></a>

### 14. `OpenAIEmbeddingService`

Nguồn: [src/agent/rag/embeddings.py:104](../src/agent/rag/embeddings.py#L104). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Tạo embedding văn bản qua OpenAIEmbeddings, tải client khi cần; thiếu API key thì fallback sang FastEmbed.

**Kế thừa trực tiếp:** `BaseEmbeddingService`

**Trạng thái được gán trong constructor:** `_api_key`, `_client`, `_dim`, `_model`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, api_key: str \| None=None, model: str='text-embedding-3-small', dimension: int=1536) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `_load_client(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `dimension(self) → int` | Trả số chiều embedding. |
| `embed_documents(self, texts: list[str]) → list[list[float]]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `embed_query(self, text: str) → list[float]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/agent/rag/ingestion.py`

<a id="class-15"></a>

### 15. `IngestionResult`

Nguồn: [src/agent/rag/ingestion.py:30](../src/agent/rag/ingestion.py#L30). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang báo cáo nhập tài liệu: ID, tiêu đề, nguồn, loại, số chunk tạo được, trạng thái và lỗi.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
document_id: str
title: str
source: str
document_type: str
chunks_created: int
status: str
error: str | None = None
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-16"></a>

### 16. `IngestionService`

Nguồn: [src/agent/rag/ingestion.py:41](../src/agent/rag/ingestion.py#L41). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Điều phối đọc tài liệu, tính hash, chia đoạn, tạo embedding và ghi tài liệu/chunk vào database; quản lý vòng đời DB qua context manager.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_owns_db`, `db`, `embedder`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, db: Database \| None=None, embedding_service: BaseEmbeddingService \| None=None) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `close(self) → None` | Đóng tài nguyên do instance quản lý. |
| `__enter__(self)` | Cho phép sử dụng instance trong khối with. |
| `__exit__(self, exc_type, exc_val, exc_tb)` | Dọn tài nguyên khi rời khối with. |
| `compute_hash(text: str) → str` | Calculate SHA-256 hash of text content. |
| `extract_text_from_file(self, file_path: Path \| str) → tuple[str, str]` | Extract plain text and determine document type from a file path. |
| `ingest_text(self, title: str, text: str, source: str='manual_entry', document_type: str='manual', metadata: dict[str, Any] \| None=None, force_update: bool=False) → IngestionResult` | Ingest raw text content into the knowledge base. |
| `ingest_file(self, file_path: Path \| str, title: str \| None=None, force_update: bool=False) → IngestionResult` | Extract text from file and ingest into knowledge base. |
| `ingest_directory(self, directory_path: Path \| str, glob_patterns: list[str] \| None=None, force_update: bool=False) → list[IngestionResult]` | Ingest all supported documents in a directory. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/rag/seed.py`, `src/agent/rag/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/agent/rag/intent.py`

<a id="class-17"></a>

### 17. `DocIntent`

Nguồn: [src/agent/rag/intent.py:9](../src/agent/rag/intent.py#L9). Loại: **Enum / tập giá trị**.

**Dùng để làm gì / câu trả lời ngắn:** Enum phân loại ý định tra cứu tài liệu để retrieval chọn/lọc nguồn phù hợp.

**Kế thừa trực tiếp:** `str`, `Enum`

**Các trường khai báo trực tiếp:**

```python
GENERAL_INTRODUCTION = 'general_introduction'
USER_GUIDE = 'user_guide'
TECHNICAL_ARCHITECTURE = 'technical_architecture'
TROUBLESHOOTING = 'troubleshooting'
INSTALLATION_DEPLOYMENT = 'installation_deployment'
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/knowledge_synthesis.py`, `src/agent/rag/retrieval.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/agent/rag/retrieval.py`

<a id="class-18"></a>

### 18. `RetrievedChunk`

Nguồn: [src/agent/rag/retrieval.py:21](../src/agent/rag/retrieval.py#L21). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang kết quả tìm kiếm một đoạn tài liệu với điểm liên quan và thông tin trích dẫn như tên tài liệu, mục, trang.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
chunk_id: str
document_id: str
document_name: str
content: str
score: float
section: str = 'General'
page: int | None = None
document_type: str = 'markdown'
metadata: dict[str, Any] = field(default_factory=dict)
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `to_dict(self) → dict[str, Any]` | Chuyển dữ liệu sang dictionary. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-19"></a>

### 19. `KnowledgeRetriever`

Nguồn: [src/agent/rag/retrieval.py:46](../src/agent/rag/retrieval.py#L46). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Tạo embedding câu hỏi, truy xuất và lọc các đoạn liên quan theo vector/ý định; dùng RetrievedChunk nội bộ rồi trả dictionary có status/results cho tool.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_owns_db`, `db`, `embedder`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, db: Database \| None=None, embedding_service: BaseEmbeddingService \| None=None) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `close(self) → None` | Đóng tài nguyên do instance quản lý. |
| `__enter__(self)` | Cho phép sử dụng instance trong khối with. |
| `__exit__(self, exc_type, exc_val, exc_tb)` | Dọn tài nguyên khi rời khối with. |
| `retrieve(self, query: str, top_k: int \| None=None, document_type: str \| None=None, score_threshold: float \| None=None) → dict[str, Any]` | Retrieve relevant knowledge chunks for a user query. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/rag/__init__.py`, `src/agent/tools/knowledge.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/agent/state.py`

<a id="class-20"></a>

### 20. `AgentState`

Nguồn: [src/agent/state.py:8](../src/agent/state.py#L8). Loại: **Schema trạng thái graph**.

**Dùng để làm gì / câu trả lời ngắn:** Schema trạng thái của graph gồm lịch sử messages kế thừa và thông tin user/thread, xác thực, bộ đếm tool và lỗi; không phải service tự chạy.

**Kế thừa trực tiếp:** `MessagesState`

**Các trường khai báo trực tiếp:**

```python
thread_id: str
user_id: str
is_authenticated: bool
tool_call_counts: dict[str, int]
repeated_tool_calls: int
tool_cycles: int
total_tool_calls: int
error: str | None
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/graph.py`, `src/agent/nodes.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/config/camera_config.py`

<a id="class-21"></a>

### 21. `CameraInfo`

Nguồn: [src/config/camera_config.py:18](../src/config/camera_config.py#L18). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang cấu hình nguồn camera: ID, tên, loại, URL, kích thước, trạng thái và liên kết video; có thể chuyển thành dictionary.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
id: str
name: str
type: str
url: str
width: int = 1280
height: int = 720
description: str = ''
video_source_id: str | None = None
enabled: bool = True
status: str = 'offline'
location: str | None = None
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `to_dict(self) → dict[str, Any]` | Serialize camera metadata to dictionary. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/config/__init__.py`, `src/stream/camera_manager.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/counter/zone_counter.py`

<a id="class-22"></a>

### 22. `ZoneCounter`

Nguồn: [src/counter/zone_counter.py:16](../src/counter/zone_counter.py#L16). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Đếm số track hiện diện trong khung hình hoặc vùng polygon, đồng thời trả tập ID hiển thị; không phải tổng người duy nhất đã từng xuất hiện.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `count`, `people_count`, `person_class_id`, `polygon`, `target_class_id`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, polygon: list[tuple[int, int]] \| None=None, person_class_id: int=0, target_class_id: int \| None=None, *args: Any, **kwargs: Any)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `update(self, tracks: sv.Detections, frame_shape: tuple[int, ...] \| None=None) → int` | Calculate current occupancy in the frame or zone. |
| `update_and_get_visible_ids(self, tracks: sv.Detections, frame_shape: tuple[int, ...] \| None=None) → tuple[int, frozenset[int]]` | Calculate occupancy and return the visible tracker-ID set. |
| `current_count(self) → int` | Current number of active tracks in view. |
| `reset(self) → None` | Reset counter to 0. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/counter/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-23"></a>

### 23. `CarCounter`

Nguồn: [src/counter/zone_counter.py:132](../src/counter/zone_counter.py#L132). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Chuyên biệt ZoneCounter cho occupancy của xe; tái sử dụng logic vùng và reset.

**Kế thừa trực tiếp:** `ZoneCounter`

**Trạng thái được gán trong constructor:** `car_count`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, polygon: list[tuple[int, int]] \| None=None, car_class_id: int=2, target_class_id: int \| list[int] \| None=None, *args: Any, **kwargs: Any)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `update(self, tracks: sv.Detections, frame_shape: tuple[int, ...] \| None=None) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `reset(self) → None` | Reset car counter to 0. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/db/database.py`

<a id="class-24"></a>

### 24. `Database`

Nguồn: [src/db/database.py:17](../src/db/database.py#L17). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Quản lý SQLAlchemy engine, pool kết nối và session; cung cấp transaction tự commit/rollback và quản lý engine dùng chung trong tiến trình.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_is_shared`, `_sessions`, `engine`, `url`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, url: str \| None=None, *, echo: bool=False, shared: bool=True)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `_create_engine_and_sessions(parsed, *, echo: bool=False) → tuple[Engine, sessionmaker]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `transaction(self) → Iterator[Session]` | One session per unit of work; commit on success, rollback on error. |
| `dispose(self) → None` | Dispose the underlying engine if this instance owns an unshared engine. |
| `dispose_shared(cls) → None` | Explicitly dispose all shared engines (useful in test teardown). |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/persistence.py`, `src/agent/config.py`, `src/agent/rag/ingestion.py`, `src/agent/rag/retrieval.py`, `src/agent/tools/analytics.py`, `src/cameras/service.py`, `src/db/__init__.py`, `src/db/migrations/env.py`, `src/events/db_worker.py`, `src/events/event_storage.py`, `src/ops/checks.py`, `src/recognition/target_selection.py`, `src/stream/camera_manager.py`, `src/ui/video_stream.py`, `src/ui/web_server.py`, `src/watchlists/import_vehicles.py`, `src/watchlists/vehicle_api.py`, `scripts/colab_bootstrap.py`, `scripts/explain_queries.py`, `scripts/test_dev.py`, `scripts/validate_agent_responses.py`, `scripts/validate_e2e_postgres.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/db/migration_head.py`

<a id="class-25"></a>

### 25. `MigrationHeadError`

Nguồn: [src/db/migration_head.py:12](../src/db/migration_head.py#L12). Loại: **Exception / loại lỗi**.

**Dùng để làm gì / câu trả lời ngắn:** Báo lỗi khi không xác định được duy nhất migration head của repository.

**Kế thừa trực tiếp:** `RuntimeError`

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `scripts/colab_startup.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/db/models.py`

<a id="class-26"></a>

### 26. `UTCDateTime`

Nguồn: [src/db/models.py:18](../src/db/models.py#L18). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Kiểu SQLAlchemy tùy biến cho datetime: từ chối thời gian không có timezone khi ghi và khôi phục timezone khi đọc SQLite.

**Kế thừa trực tiếp:** `TypeDecorator`

**Các trường khai báo trực tiếp:**

```python
impl = DateTime(timezone=True)
cache_ok = True
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `process_bind_param(self, value, dialect)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `process_result_value(self, value, dialect)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/db/migrations/env.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-27"></a>

### 27. `Base`

Nguồn: [src/db/models.py:38](../src/db/models.py#L38). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Lớp gốc SQLAlchemy declarative để các model cùng tham gia registry và metadata của schema.

**Kế thừa trực tiếp:** `DeclarativeBase`

**Các trường khai báo trực tiếp:**

```python
metadata = MetaData(naming_convention={'ix': 'ix_%(table_name)s_%(column_0_name)s', 'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s', 'pk': 'pk_%(table_name)s', 'uq': 'uq_%(table_name)s_%(column_0_name)s'})
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/db/migrations/env.py`, `src/db/repositories/base.py`, `src/ops/checks.py`, `scripts/test_dev.py`, `scripts/validate_agent_responses.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-28"></a>

### 28. `Identity`

Nguồn: [src/db/models.py:50](../src/db/models.py#L50). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Mixin cung cấp cột ID UUID làm khóa chính dùng chung cho các model database.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-29"></a>

### 29. `Camera`

Nguồn: [src/db/models.py:54](../src/db/models.py#L54). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM của bảng cameras: cấu hình camera, nguồn liên kết, thông tin hoạt động và trạng thái.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `cameras`.

**Các trường khai báo trực tiếp:**

```python
registry_key: Mapped[str | None] = mapped_column(String(255), unique=True)
description: Mapped[str | None] = mapped_column(Text)
thumbnail_path: Mapped[str | None] = mapped_column(Text)
last_active: Mapped[datetime | None] = mapped_column(UTCDateTime())
active_token: Mapped[str | None] = mapped_column(String(64))
active_until: Mapped[datetime | None] = mapped_column(UTCDateTime())
video_source_id: Mapped[UUID | None] = mapped_column(ForeignKey('video_sources.id', ondelete='RESTRICT'))
name: Mapped[str] = mapped_column(String(255))
source_type: Mapped[str] = mapped_column(String(50))
source: Mapped[str] = mapped_column(Text)
location: Mapped[str | None] = mapped_column(Text)
enabled: Mapped[bool] = mapped_column(Boolean, default=True)
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
__tablename__ = 'cameras'
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/tools/alerts.py`, `src/agent/tools/camera.py`, `src/agent/tools/events.py`, `src/agent/tools/notifications.py`, `src/agent/tools/notification_queries.py`, `src/agent/tools/reports.py`, `src/cameras/import_registry.py`, `src/cameras/service.py`, `src/config/camera_config.py`, `src/db/repositories/__init__.py`, `src/notifications/alerts.py`, `src/ui/web_server.py`, `scripts/explain_queries.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-30"></a>

### 30. `VideoSource`

Nguồn: [src/db/models.py:72](../src/db/models.py#L72). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM của bảng video_sources: metadata file video, storage_path, kích thước, thời lượng, FPS và trạng thái; không chứa trực tiếp byte video.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `video_sources`.

**Các trường khai báo trực tiếp:**

```python
original_filename: Mapped[str] = mapped_column(String(255))
storage_path: Mapped[str] = mapped_column(Text)
status: Mapped[str] = mapped_column(String(50), default='ready', index=True)
file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
fps: Mapped[float | None] = mapped_column(Float, nullable=True)
width: Mapped[int | None] = mapped_column(Integer, nullable=True)
height: Mapped[int | None] = mapped_column(Integer, nullable=True)
video_metadata: Mapped[dict[str, Any]] = mapped_column('metadata', JSON_DATA, default=dict)
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)
updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
__tablename__ = 'video_sources'
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/cameras/service.py`, `src/db/repositories/__init__.py`, `src/ops/checks.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-31"></a>

### 31. `Zone`

Nguồn: [src/db/models.py:87](../src/db/models.py#L87). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM lưu vùng polygon của camera và trạng thái bật/tắt vùng.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `zones`.

**Các trường khai báo trực tiếp:**

```python
camera_id: Mapped[UUID] = mapped_column(ForeignKey('cameras.id', ondelete='RESTRICT'), index=True)
name: Mapped[str] = mapped_column(String(255))
polygon: Mapped[list[list[float]]] = mapped_column(JSON_DATA)
enabled: Mapped[bool] = mapped_column(Boolean, default=True)
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
__tablename__ = 'zones'
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/db/repositories/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-32"></a>

### 32. `Target`

Nguồn: [src/db/models.py:97](../src/db/models.py#L97). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM bảng targets: danh tính/đối tượng cần theo dõi, ảnh tham chiếu, embedding và trạng thái.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `targets`.

**Các trường khai báo trực tiếp:**

```python
name: Mapped[str] = mapped_column(String(255))
target_type: Mapped[str] = mapped_column(String(50))
embedding: Mapped[list[float] | None] = mapped_column(JSON_DATA)
reference_metadata: Mapped[dict[str, Any]] = mapped_column(JSON_DATA, default=dict)
image_path: Mapped[str | None] = mapped_column(Text)
active: Mapped[bool] = mapped_column(Boolean, default=True)
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
__tablename__ = 'targets'
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/identity_resolution.py`, `src/agent/tools/alerts.py`, `src/agent/tools/notifications.py`, `src/agent/tools/notification_queries.py`, `src/agent/tools/watchlist.py`, `src/db/repositories/__init__.py`, `src/events/db_worker.py`, `src/notifications/alerts.py`, `src/notifications/service.py`, `src/recognition/target_matcher.py`, `src/recognition/target_selection.py`, `src/ui/web_server.py`, `scripts/explain_queries.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-33"></a>

### 33. `TargetEmbedding`

Nguồn: [src/db/models.py:108](../src/db/models.py#L108). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM lưu vector khuôn mặt 512 chiều gắn với target, kèm model và ảnh nguồn.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `target_embeddings`.

**Các trường khai báo trực tiếp:**

```python
target_id: Mapped[UUID] = mapped_column(ForeignKey('targets.id', ondelete='CASCADE'), index=True)
embedding: Mapped[Any] = mapped_column(Vector(512), nullable=False)
model_name: Mapped[str] = mapped_column(String(255))
model_version: Mapped[str | None] = mapped_column(String(255))
source_image_path: Mapped[str | None] = mapped_column(Text)
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
__tablename__ = 'target_embeddings'
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/db/repositories/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-34"></a>

### 34. `DetectionEvent`

Nguồn: [src/db/models.py:118](../src/db/models.py#L118). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM lưu một sự kiện phát hiện: camera/video, frame, track, thời gian và dữ liệu phát hiện.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `detection_events`.

**Các trường khai báo trực tiếp:**

```python
camera_id: Mapped[UUID | None] = mapped_column(ForeignKey('cameras.id', ondelete='RESTRICT'), nullable=True, index=True)
video_source_id: Mapped[UUID | None] = mapped_column(ForeignKey('video_sources.id', ondelete='SET NULL'), nullable=True, index=True)
event_type: Mapped[str] = mapped_column(String(50), index=True)
frame_id: Mapped[int] = mapped_column(Integer)
timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)
track_id: Mapped[int | None] = mapped_column(Integer, index=True)
class_name: Mapped[str | None] = mapped_column(String(100))
confidence: Mapped[float | None] = mapped_column(Float)
bbox: Mapped[list[float] | None] = mapped_column(JSON_DATA)
snapshot_path: Mapped[str | None] = mapped_column(Text)
event_metadata: Mapped[dict[str, Any]] = mapped_column('metadata', JSON_DATA, default=dict)
__tablename__ = 'detection_events'
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/db/repositories/__init__.py`, `src/event_center/service.py`, `src/ui/web_server.py`, `src/watchlists/vehicles.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-35"></a>

### 35. `VehicleEvent`

Nguồn: [src/db/models.py:133](../src/db/models.py#L133). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM lưu thông tin sự kiện xe và liên kết với sự kiện phát hiện/video.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `vehicle_events`.

**Các trường khai báo trực tiếp:**

```python
detection_event_id: Mapped[UUID | None] = mapped_column(ForeignKey('detection_events.id', ondelete='CASCADE'), nullable=True, index=True)
video_source_id: Mapped[UUID | None] = mapped_column(ForeignKey('video_sources.id', ondelete='SET NULL'), nullable=True, index=True)
vehicle_class: Mapped[str] = mapped_column(String(100))
track_id: Mapped[int] = mapped_column(Integer, index=True)
zone_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
vehicle_color: Mapped[str | None] = mapped_column(String(50), nullable=True)
vehicle_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
first_seen: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
last_seen: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
__tablename__ = 'vehicle_events'
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/db/repositories/__init__.py`, `src/events/db_worker.py`, `src/event_center/service.py`, `src/ui/web_server.py`, `src/watchlists/vehicles.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-36"></a>

### 36. `PlateEvent`

Nguồn: [src/db/models.py:146](../src/db/models.py#L146). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM lưu kết quả đọc biển số, confidence, crop và trạng thái, liên kết với VehicleEvent.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `plate_events`.

**Các trường khai báo trực tiếp:**

```python
vehicle_event_id: Mapped[UUID] = mapped_column(ForeignKey('vehicle_events.id', ondelete='CASCADE'), index=True)
plate_text: Mapped[str] = mapped_column(String(100), index=True)
normalized_plate: Mapped[str | None] = mapped_column(String(100), index=True)
confidence: Mapped[float | None] = mapped_column(Float)
plate_bbox: Mapped[list[float] | None] = mapped_column(JSON_DATA)
plate_crop_path: Mapped[str | None] = mapped_column(Text)
status: Mapped[str] = mapped_column(String(50), default='pending')
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
__tablename__ = 'plate_events'
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/tools/alerts.py`, `src/agent/tools/analytics.py`, `src/agent/tools/notifications.py`, `src/agent/tools/notification_queries.py`, `src/agent/tools/reports.py`, `src/db/repositories/__init__.py`, `src/event_center/service.py`, `src/notifications/alerts.py`, `src/notifications/service.py`, `src/ui/web_server.py`, `src/watchlists/vehicles.py`, `scripts/explain_queries.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-37"></a>

### 37. `FaceEvent`

Nguồn: [src/db/models.py:158](../src/db/models.py#L158). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM lưu kết quả nhận diện khuôn mặt: target, similarity, quyết định, track và bằng chứng.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `face_events`.

**Các trường khai báo trực tiếp:**

```python
camera_id: Mapped[str | None] = mapped_column(String(255), index=True)
detection_event_id: Mapped[UUID | None] = mapped_column(ForeignKey('detection_events.id', ondelete='CASCADE'), nullable=True, index=True)
video_source_id: Mapped[UUID | None] = mapped_column(ForeignKey('video_sources.id', ondelete='SET NULL'), nullable=True, index=True)
target_id: Mapped[UUID | None] = mapped_column(ForeignKey('targets.id', ondelete='SET NULL'), index=True)
track_id: Mapped[int | None] = mapped_column(Integer, index=True)
frame_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
similarity: Mapped[float | None] = mapped_column(Float)
decision: Mapped[str] = mapped_column(String(50))
face_crop_path: Mapped[str | None] = mapped_column(Text)
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
__tablename__ = 'face_events'
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/tools/alerts.py`, `src/agent/tools/analytics.py`, `src/agent/tools/notifications.py`, `src/agent/tools/notification_queries.py`, `src/agent/tools/reports.py`, `src/db/repositories/__init__.py`, `src/events/db_worker.py`, `src/event_center/service.py`, `src/notifications/alerts.py`, `src/notifications/service.py`, `src/ui/web_server.py`, `scripts/explain_queries.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-38"></a>

### 38. `VehiclePassage`

Nguồn: [src/db/models.py:172](../src/db/models.py#L172). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM lưu một lần xe xuất hiện liên tục tại camera, từ lúc thấy đến kết thúc, gồm biển số và bằng chứng.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `vehicle_passages`.

**Các trường khai báo trực tiếp:**

```python
camera_id: Mapped[str] = mapped_column(String(255), index=True)
video_source_id: Mapped[UUID | None] = mapped_column(ForeignKey('video_sources.id', ondelete='SET NULL'), nullable=True, index=True)
zone_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
track_id: Mapped[int] = mapped_column(Integer, index=True)
session_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
vehicle_type: Mapped[str] = mapped_column(String(100), default='vehicle')
vehicle_color: Mapped[str | None] = mapped_column(String(50), nullable=True)
vehicle_type_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
vehicle_color_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
plate_text: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
plate_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
plate_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
direction: Mapped[str | None] = mapped_column(String(50), nullable=True)
first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)
last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
best_vehicle_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
best_plate_image_path: Mapped[str | None] = mapped_column(Text, nullable=True)
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
finalized_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
__tablename__ = 'vehicle_passages'
__table_args__ = (Index('ix_vehicle_passages_cam_first_seen', 'camera_id', 'first_seen_at'), Index('ix_vehicle_passages_zone_first_seen', 'zone_id', 'first_seen_at'), Index('ix_vehicle_passages_type_first_seen', 'vehicle_type', 'first_seen_at'))
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/tools/analytics.py`, `src/agent/tools/reports.py`, `src/db/repositories/__init__.py`, `src/events/event_manager.py`, `src/events/__init__.py`, `src/event_center/service.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-39"></a>

### 39. `BusinessEvent`

Nguồn: [src/db/models.py:218](../src/db/models.py#L218). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM lưu sự kiện nghiệp vụ có ý nghĩa và khóa idempotency để tránh ghi lặp.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `business_events`.

**Các trường khai báo trực tiếp:**

```python
passage_id: Mapped[UUID | None] = mapped_column(ForeignKey('vehicle_passages.id', ondelete='CASCADE'), nullable=True, index=True)
video_source_id: Mapped[UUID | None] = mapped_column(ForeignKey('video_sources.id', ondelete='SET NULL'), nullable=True, index=True)
camera_id: Mapped[str] = mapped_column(String(255), index=True)
zone_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
track_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
event_type: Mapped[str] = mapped_column(String(50), index=True)
event_time: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, index=True)
vehicle_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
plate_text: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
direction: Mapped[str | None] = mapped_column(String(50), nullable=True)
idempotency_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
event_metadata: Mapped[dict[str, Any]] = mapped_column('metadata', JSON_DATA, default=dict)
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
__tablename__ = 'business_events'
__table_args__ = (Index('ix_business_events_cam_time', 'camera_id', 'event_time'),)
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/tools/analytics.py`, `src/db/repositories/__init__.py`, `src/events/event_storage.py`, `src/event_center/service.py`, `src/ui/web_server.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-40"></a>

### 40. `Notification`

Nguồn: [src/db/models.py:249](../src/db/models.py#L249). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM của outbox gửi thông báo và lịch sử giao nhận: người nhận, trạng thái, retry và liên kết sự kiện; không phải email đã gửi chắc chắn.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `notifications`.

**Các trường khai báo trực tiếp:**

```python
event_id: Mapped[UUID | None] = mapped_column(ForeignKey('face_events.id', ondelete='CASCADE'))
plate_event_id: Mapped[UUID | None] = mapped_column(ForeignKey('plate_events.id', ondelete='CASCADE'))
vehicle_watchlist_id: Mapped[UUID | None] = mapped_column(ForeignKey('vehicle_watchlists.id', ondelete='SET NULL'))
target_id: Mapped[UUID | None] = mapped_column(ForeignKey('targets.id', ondelete='SET NULL'))
camera_id: Mapped[str] = mapped_column(String(255))
channel: Mapped[str] = mapped_column(String(30), default='email')
recipient: Mapped[str] = mapped_column(String(320))
status: Mapped[str] = mapped_column(String(20), default='pending')
retry_count: Mapped[int] = mapped_column(Integer, default=0)
error: Mapped[str | None] = mapped_column(String(100))
payload: Mapped[dict[str, Any]] = mapped_column(JSON_DATA)
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
__tablename__ = 'notifications'
__table_args__ = (UniqueConstraint('event_id', 'channel', 'recipient', name='uq_notifications_event_channel_recipient'), CheckConstraint("status IN ('pending','sent','failed','suppressed')", name='notification_status'), UniqueConstraint('plate_event_id', 'channel', 'recipient', name='uq_notifications_plate_channel_recipient'), CheckConstraint('(event_id IS NOT NULL AND plate_event_id IS NULL) OR (event_id IS NULL AND plate_event_id IS NOT NULL)', name='notification_event_kind'), Index('ix_notifications_vehicle_cooldown', 'vehicle_watchlist_id', 'camera_id', 'created_at'), Index('ix_notifications_due', 'status', 'next_attempt_at'), Index('ix_notifications_cooldown', 'target_id', 'camera_id', 'created_at'))
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/tools/alerts.py`, `src/agent/tools/notifications.py`, `src/agent/tools/notification_queries.py`, `src/agent/tools/reports.py`, `src/event_center/service.py`, `src/notifications/alerts.py`, `src/notifications/service.py`, `scripts/explain_queries.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-41"></a>

### 41. `VehicleWatchlist`

Nguồn: [src/db/models.py:277](../src/db/models.py#L277). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM lưu danh sách biển số cần theo dõi cùng thông tin xe/chủ xe và trạng thái.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `vehicle_watchlists`.

**Các trường khai báo trực tiếp:**

```python
plate_number: Mapped[str] = mapped_column(String(100), unique=True)
vehicle_type: Mapped[str] = mapped_column(String(100), default='car')
vehicle_color: Mapped[str | None] = mapped_column(String(20), nullable=True)
display_name: Mapped[str] = mapped_column(String(255), default='')
owner_info: Mapped[str] = mapped_column(Text, default='')
notes: Mapped[str] = mapped_column(Text, default='')
status: Mapped[str] = mapped_column(String(20), default='active')
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
__tablename__ = 'vehicle_watchlists'
__table_args__ = (CheckConstraint("status IN ('active','disabled')", name='vehicle_watchlist_status'),)
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/tools/alerts.py`, `src/agent/tools/notifications.py`, `src/agent/tools/notification_queries.py`, `src/agent/tools/watchlist.py`, `src/events/db_worker.py`, `src/notifications/alerts.py`, `src/notifications/service.py`, `src/watchlists/import_vehicles.py`, `src/watchlists/vehicles.py`, `scripts/explain_queries.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-42"></a>

### 42. `VehicleWatchlistResult`

Nguồn: [src/db/models.py:291](../src/db/models.py#L291). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM lưu snapshot quyết định đối chiếu watchlist tại lúc ghi PlateEvent, để giữ kết quả lịch sử.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `vehicle_watchlist_results`.

**Các trường khai báo trực tiếp:**

```python
plate_event_id: Mapped[UUID] = mapped_column(ForeignKey('plate_events.id', ondelete='CASCADE'), unique=True)
watchlist_id: Mapped[UUID | None] = mapped_column(ForeignKey('vehicle_watchlists.id', ondelete='SET NULL'), index=True)
normalized_plate: Mapped[str] = mapped_column(String(100), index=True)
decision: Mapped[str] = mapped_column(String(20))
display_name: Mapped[str | None] = mapped_column(String(255))
camera_id: Mapped[str | None] = mapped_column(String(255))
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
__tablename__ = 'vehicle_watchlist_results'
__table_args__ = (CheckConstraint("decision IN ('MATCH','NO_MATCH')", name='vehicle_watchlist_decision'),)
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/tools/analytics.py`, `src/agent/tools/reports.py`, `src/event_center/service.py`, `src/notifications/service.py`, `src/watchlists/vehicles.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-43"></a>

### 43. `KnowledgeDocument`

Nguồn: [src/db/models.py:304](../src/db/models.py#L304). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM lưu danh mục tài liệu RAG: tiêu đề, nguồn, loại, hash chống trùng và metadata.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `knowledge_documents`.

**Các trường khai báo trực tiếp:**

```python
title: Mapped[str] = mapped_column(String(255))
source: Mapped[str] = mapped_column(String(1024), index=True)
document_type: Mapped[str] = mapped_column(String(50), default='markdown', index=True)
content_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
chunk_count: Mapped[int] = mapped_column(Integer, default=0)
doc_metadata: Mapped[dict[str, Any]] = mapped_column('metadata', JSON_DATA, default=dict)
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
__tablename__ = 'knowledge_documents'
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/rag/ingestion.py`, `src/agent/rag/retrieval.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-44"></a>

### 44. `KnowledgeChunk`

Nguồn: [src/db/models.py:317](../src/db/models.py#L317). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM lưu nội dung chunk của tài liệu và embedding 384 chiều phục vụ tìm kiếm.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `knowledge_chunks`.

**Các trường khai báo trực tiếp:**

```python
document_id: Mapped[UUID] = mapped_column(ForeignKey('knowledge_documents.id', ondelete='CASCADE'), index=True)
chunk_index: Mapped[int] = mapped_column(Integer)
content: Mapped[str] = mapped_column(Text)
embedding: Mapped[Any] = mapped_column(Vector(384), nullable=True)
chunk_metadata: Mapped[dict[str, Any]] = mapped_column('metadata', JSON_DATA, default=dict)
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
__tablename__ = 'knowledge_chunks'
__table_args__ = (Index('ix_knowledge_chunks_doc_idx', 'document_id', 'chunk_index'),)
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/rag/ingestion.py`, `src/agent/rag/retrieval.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-45"></a>

### 45. `AgentConversation`

Nguồn: [src/db/models.py:333](../src/db/models.py#L333). Loại: **Model ORM / bảng database**.

**Dùng để làm gì / câu trả lời ngắn:** Model ORM lưu registry hội thoại: user, thread, tiêu đề, thời gian và trạng thái; messages được lưu riêng qua checkpoint LangGraph.

**Kế thừa trực tiếp:** `Identity`, `Base`

**Bảng DB:** `agent_conversations`.

**Các trường khai báo trực tiếp:**

```python
thread_id: Mapped[str] = mapped_column(String(128), index=True)
user_id: Mapped[str] = mapped_column(String(255), index=True)
title: Mapped[str] = mapped_column(String(255), default='Cuộc trò chuyện mới')
created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
last_message_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
status: Mapped[str] = mapped_column(String(20), default='active', index=True)
__tablename__ = 'agent_conversations'
__table_args__ = (UniqueConstraint('thread_id', name='uq_agent_conversations_thread_id'), Index('ix_agent_conversations_user_updated', 'user_id', 'updated_at'), Index('ix_agent_conversations_user_last_msg', 'user_id', 'last_message_at'))
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/conversations.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/db/repositories/__init__.py`

<a id="class-46"></a>

### 46. `VectorSearchResult`

Nguồn: [src/db/repositories/__init__.py:20](../src/db/repositories/__init__.py#L20). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang kết quả tìm kiếm vector và dữ liệu target liên quan; hỗ trợ truy cập/chuyển thành dictionary.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
target_embedding_id: UUID
target_id: UUID
distance: float
similarity: float
model_name: str
model_version: str | None
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__getitem__(self, item: str) → Any` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `to_dict(self) → dict[str, Any]` | Chuyển dữ liệu sang dictionary. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-47"></a>

### 47. `CameraRepository`

Nguồn: [src/db/repositories/__init__.py:35](../src/db/repositories/__init__.py#L35). Loại: **Repository / truy cập database**.

**Dùng để làm gì / câu trả lời ngắn:** Repository CRUD cho Camera; kế thừa các method của Repository dù không khai báo method riêng.

**Kế thừa trực tiếp:** `Repository[Camera]`

**Các trường khai báo trực tiếp:**

```python
model = Camera
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/db_worker.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-48"></a>

### 48. `VideoSourceRepository`

Nguồn: [src/db/repositories/__init__.py:39](../src/db/repositories/__init__.py#L39). Loại: **Repository / truy cập database**.

**Dùng để làm gì / câu trả lời ngắn:** Repository quản lý VideoSource, bổ sung tìm theo storage_path và truy vấn danh sách nguồn.

**Kế thừa trực tiếp:** `Repository[VideoSource]`

**Các trường khai báo trực tiếp:**

```python
model = VideoSource
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `get_by_storage_path(self, storage_path: str) → VideoSource \| None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `query_sources(self, *, status: str \| None=None, limit: int=100, offset: int=0) → list[VideoSource]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/stream/camera_manager.py`, `src/ui/web_server.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-49"></a>

### 49. `ZoneRepository`

Nguồn: [src/db/repositories/__init__.py:59](../src/db/repositories/__init__.py#L59). Loại: **Repository / truy cập database**.

**Dùng để làm gì / câu trả lời ngắn:** Repository CRUD cho vùng camera; dùng các method kế thừa từ Repository.

**Kế thừa trực tiếp:** `Repository[Zone]`

**Các trường khai báo trực tiếp:**

```python
model = Zone
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-50"></a>

### 50. `TargetRepository`

Nguồn: [src/db/repositories/__init__.py:63](../src/db/repositories/__init__.py#L63). Loại: **Repository / truy cập database**.

**Dùng để làm gì / câu trả lời ngắn:** Repository quản lý target và logic tạo bản ghi target.

**Kế thừa trực tiếp:** `Repository[Target]`

**Các trường khai báo trực tiếp:**

```python
model = Target
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `create(self, **values) → Target` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/ui/video_stream.py`, `src/ui/web_server.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-51"></a>

### 51. `DetectionEventRepository`

Nguồn: [src/db/repositories/__init__.py:79](../src/db/repositories/__init__.py#L79). Loại: **Repository / truy cập database**.

**Dùng để làm gì / câu trả lời ngắn:** Repository truy vấn và CRUD sự kiện phát hiện theo bộ lọc.

**Kế thừa trực tiếp:** `Repository[DetectionEvent]`

**Các trường khai báo trực tiếp:**

```python
model = DetectionEvent
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `query(self, *, camera_id: UUID \| None=None, event_type: str \| None=None, track_id: int \| None=None, video_source_id: UUID \| None=None, since: datetime \| None=None, until: datetime \| None=None, limit: int=100, offset: int=0)` | Newest first; UTC time interval is [since, until). |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/db_worker.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-52"></a>

### 52. `VehicleEventRepository`

Nguồn: [src/db/repositories/__init__.py:103](../src/db/repositories/__init__.py#L103). Loại: **Repository / truy cập database**.

**Dùng để làm gì / câu trả lời ngắn:** Repository ghi và truy vấn sự kiện xe.

**Kế thừa trực tiếp:** `Repository[VehicleEvent]`

**Các trường khai báo trực tiếp:**

```python
model = VehicleEvent
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `create(self, **values) → VehicleEvent` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `query_events(self, *, track_id: int \| None=None, vehicle_class: str \| None=None, vehicle_color: str \| None=None, zone_id: str \| None=None, video_source_id: UUID \| None=None, since: datetime \| None=None, until: datetime \| None=None, limit: int=100, offset: int=0) → list[VehicleEvent]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/db_worker.py`, `src/ui/web_server.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-53"></a>

### 53. `PlateEventRepository`

Nguồn: [src/db/repositories/__init__.py:151](../src/db/repositories/__init__.py#L151). Loại: **Repository / truy cập database**.

**Dùng để làm gì / câu trả lời ngắn:** Repository ghi/truy vấn biển số và tìm bản ghi theo sự kiện xe.

**Kế thừa trực tiếp:** `Repository[PlateEvent]`

**Các trường khai báo trực tiếp:**

```python
model = PlateEvent
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `create(self, **values) → PlateEvent` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get_by_vehicle_event(self, vehicle_event_id: UUID) → list[PlateEvent]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `query_events(self, *, vehicle_event_id: UUID \| None=None, plate_text: str \| None=None, status: str \| None=None, since: datetime \| None=None, until: datetime \| None=None, limit: int=100, offset: int=0) → list[PlateEvent]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/db_worker.py`, `src/ui/web_server.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-54"></a>

### 54. `FaceEventRepository`

Nguồn: [src/db/repositories/__init__.py:197](../src/db/repositories/__init__.py#L197). Loại: **Repository / truy cập database**.

**Dùng để làm gì / câu trả lời ngắn:** Repository ghi và truy vấn sự kiện khuôn mặt.

**Kế thừa trực tiếp:** `Repository[FaceEvent]`

**Các trường khai báo trực tiếp:**

```python
model = FaceEvent
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `create(self, **values) → FaceEvent` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `query_events(self, *, target_id: UUID \| None=None, track_id: int \| None=None, video_source_id: UUID \| None=None, decision: str \| None=None, since: datetime \| None=None, until: datetime \| None=None, limit: int=100, offset: int=0) → list[FaceEvent]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/db_worker.py`, `src/ui/web_server.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-55"></a>

### 55. `VehiclePassageRepository`

Nguồn: [src/db/repositories/__init__.py:242](../src/db/repositories/__init__.py#L242). Loại: **Repository / truy cập database**.

**Dùng để làm gì / câu trả lời ngắn:** Repository quản lý lần xuất hiện liên tục của xe, upsert theo session_key và thống kê loại xe.

**Kế thừa trực tiếp:** `Repository[VehiclePassage]`

**Các trường khai báo trực tiếp:**

```python
model = VehiclePassage
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `create(self, **values) → VehiclePassage` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get_by_session_key(self, session_key: str) → VehiclePassage \| None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `upsert_passage(self, session_key: str, **values) → tuple[VehiclePassage, bool]` | Insert or update a passage by session_key. |
| `query_passages(self, *, plate_text: str \| None=None, camera_id: str \| None=None, video_source_id: UUID \| None=None, zone_id: str \| None=None, vehicle_type: str \| None=None, since: datetime \| None=None, until: datetime \| None=None, limit: int=100, offset: int=0) → list[VehiclePassage]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `count_vehicle_types(self, *, camera_id: str \| None=None, since: datetime \| None=None, until: datetime \| None=None) → dict[str, int]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/db_worker.py`, `scripts/validate_e2e_postgres.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-56"></a>

### 56. `BusinessEventRepository`

Nguồn: [src/db/repositories/__init__.py:329](../src/db/repositories/__init__.py#L329). Loại: **Repository / truy cập database**.

**Dùng để làm gì / câu trả lời ngắn:** Repository sự kiện nghiệp vụ; insert idempotent theo khóa chống trùng và truy vấn sự kiện.

**Kế thừa trực tiếp:** `Repository[BusinessEvent]`

**Các trường khai báo trực tiếp:**

```python
model = BusinessEvent
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `create(self, **values) → BusinessEvent` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get_by_idempotency_key(self, idempotency_key: str) → BusinessEvent \| None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `insert_idempotent(self, **values) → tuple[BusinessEvent, bool]` | Insert business event idempotently. |
| `query_events(self, *, camera_id: str \| None=None, video_source_id: UUID \| None=None, event_type: str \| None=None, passage_id: UUID \| None=None, plate_text: str \| None=None, since: datetime \| None=None, until: datetime \| None=None, limit: int=100, offset: int=0) → list[BusinessEvent]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/db_worker.py`, `src/events/event_storage.py`, `scripts/validate_e2e_postgres.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-57"></a>

### 57. `TargetEmbeddingRepository`

Nguồn: [src/db/repositories/__init__.py:394](../src/db/repositories/__init__.py#L394). Loại: **Repository / truy cập database**.

**Dùng để làm gì / câu trả lời ngắn:** Repository kiểm tra vector khuôn mặt, ghi/cập nhật embedding và tìm target tương tự.

**Kế thừa trực tiếp:** `Repository[TargetEmbedding]`

**Các trường khai báo trực tiếp:**

```python
model = TargetEmbedding
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `_validate_embedding(self, embedding: Any) → list[float]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `create(self, **values) → TargetEmbedding` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `update(self, item_id: UUID, **values) → TargetEmbedding \| None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `search_similar(self, embedding: Sequence[float], limit: int=5, max_distance: float \| None=None) → list[VectorSearchResult]` | Perform exact cosine nearest-neighbor vector search. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/ui/video_stream.py`, `src/ui/web_server.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/db/repositories/base.py`

<a id="class-58"></a>

### 58. `Repository`

Nguồn: [src/db/repositories/base.py:14](../src/db/repositories/base.py#L14). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Lớp CRUD generic trên SQLAlchemy session: create/get/list/update/delete, kiểm tra field/filter và phân trang; không tự sở hữu toàn bộ transaction nghiệp vụ.

**Kế thừa trực tiếp:** `Generic[Model]`

**Các trường khai báo trực tiếp:**

```python
model: type[Model]
```

**Trạng thái được gán trong constructor:** `session`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, session: Session)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `_validate_fields(self, values)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `create(self, **values) → Model` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get(self, item_id: UUID) → Model \| None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `list(self, *, limit: int=100, offset: int=0, **filters) → list[Model]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `_validate_filters(self, filters)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `_page(self, statement, limit, offset)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `update(self, item_id: UUID, **values) → Model \| None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `delete(self, item_id: UUID) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/db/repositories/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/detector/yolo_detector.py`

<a id="class-59"></a>

### 59. `DetectionsData`

Nguồn: [src/detector/yolo_detector.py:19](../src/detector/yolo_detector.py#L19). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Container kết quả detector dạng dictionary nhưng hỗ trợ truy cập thuộc tính xyxy/confidence/class_id; tách output khỏi framework Ultralytics.

**Kế thừa trực tiếp:** `dict`

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `xyxy(self) → np.ndarray` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `confidence(self) → np.ndarray` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `class_id(self) → np.ndarray` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `__len__(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/detector/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-60"></a>

### 60. `YOLODetector`

Nguồn: [src/detector/yolo_detector.py:42](../src/detector/yolo_detector.py#L42). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Bọc model YOLO để tải/warmup và phát hiện đối tượng trong frame; trả bounding box, confidence, class_id chứ chưa gán track ID.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_warmed_up`, `config`, `device`, `device_name`, `device_type`, `last_after_nms`, `last_before_nms`, `last_tile_count`, `last_yolo_ms`, `model`, `model_path`, `vram_allocated_mb`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, config: Any)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `warmup(self, img_size: int \| None=None) → None` | Warm up YOLO model once to initialize CUDA kernels and persistent VRAM residency. |
| `detect(self, frame: np.ndarray) → DetectionsData` | Run YOLO11s inference on frame and return decoupled {xyxy, confidence, class_id}. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/detector/__init__.py`, `scripts/colab_startup.py`, `scripts/validate_plate_runtime.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/events/db_worker.py`

<a id="class-61"></a>

### 61. `DatabaseWorker`

Nguồn: [src/events/db_worker.py:44](../src/events/db_worker.py#L44). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Worker nền nhận snapshot DTO qua queue rồi ghi DB theo batch/transaction; tách độ trễ ghi DB khỏi vòng xử lý frame.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_retry_buffer`, `_stop_event`, `_task_queue`, `_worker_thread`, `batch_size`, `db`, `db_failures`, `enqueue_latencies`, `last_write_ms`, `max_queue_size`, `notifications`, `queue_coalesced`, `queue_dropped`, `retry_count`, `snapshot_dir`, `write_latencies`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, db_url: str \| None=None, max_queue_size: int=1000, batch_size: int=50, snapshot_dir: Path \| str \| None=None) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `queue_depth(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `enqueue_passage(self, dto: VehiclePassageDTO, vehicle_crop: np.ndarray \| None=None, plate_crop: np.ndarray \| None=None, is_critical: bool=False) → bool` | Enqueue a VehiclePassageDTO non-blockingly. |
| `enqueue_business_event(self, dto: BusinessEventDTO, is_critical: bool=True, snapshot: np.ndarray \| None=None) → bool` | Enqueue a BusinessEventDTO non-blockingly. |
| `enqueue_face_event(self, dto: FaceEventDTO, face_crop: np.ndarray \| None=None, is_critical: bool=True) → bool` | Enqueue a FaceEventDTO non-blockingly. |
| `_put_task(self, task: tuple[str, Any, Any], is_critical: bool) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `_worker_loop(self) → None` | Dedicated worker loop owning its DB session/transaction lifecycle. |
| `_persist_batch(self, batch: list[tuple[str, Any, Any]]) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get_latency_stats(self) → dict[str, float]` | Return p50, p95, p99 latencies for enqueue and worker writes. |
| `stop(self, timeout: float=5.0) → None` | Clean shutdown: flush queue, commit transactions, close connections. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/event_manager.py`, `src/events/__init__.py`, `scripts/validate_e2e_postgres.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/events/event_dto.py`

<a id="class-62"></a>

### 62. `VehiclePassageDTO`

Nguồn: [src/events/event_dto.py:14](../src/events/event_dto.py#L14). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Snapshot dữ liệu passage của xe gửi từ runtime sang worker DB; mang ID, thời gian, biển số và đường dẫn bằng chứng.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
id: UUID
session_key: str
camera_id: str
track_id: int
first_seen_at: datetime
last_seen_at: datetime
video_source_id: UUID | None = None
vehicle_type: str = 'vehicle'
vehicle_color: str | None = None
vehicle_type_confidence: float | None = None
vehicle_color_confidence: float | None = None
zone_id: str | None = None
plate_text: str | None = None
plate_status: str | None = None
plate_confidence: float | None = None
direction: str | None = None
duration_ms: float = 0.0
best_vehicle_image_path: str | None = None
best_plate_image_path: str | None = None
created_at: datetime = field(default_factory=datetime.utcnow)
updated_at: datetime = field(default_factory=datetime.utcnow)
finalized_at: datetime | None = None
is_final: bool = False
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/db_worker.py`, `src/events/event_manager.py`, `src/events/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-63"></a>

### 63. `BusinessEventDTO`

Nguồn: [src/events/event_dto.py:42](../src/events/event_dto.py#L42). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Snapshot sự kiện nghiệp vụ chuyển sang worker DB, gồm thời gian, metadata và idempotency_key.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
id: UUID
passage_id: UUID | None
camera_id: str
event_type: str
event_time: datetime
idempotency_key: str
video_source_id: UUID | None = None
zone_id: str | None = None
track_id: int | None = None
vehicle_type: str | None = None
plate_text: str | None = None
direction: str | None = None
metadata: dict[str, Any] = field(default_factory=dict)
created_at: datetime = field(default_factory=datetime.utcnow)
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/db_worker.py`, `src/events/event_manager.py`, `src/events/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-64"></a>

### 64. `FaceEventDTO`

Nguồn: [src/events/event_dto.py:61](../src/events/event_dto.py#L61). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Snapshot kết quả nhận diện khuôn mặt chuyển sang worker DB, gồm target, similarity, quyết định và crop.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
id: UUID
track_id: int
camera_id: str
target_id: UUID | None = None
target_name: str | None = None
similarity: float | None = None
decision: str = 'FACE_MATCH'
video_source_id: UUID | None = None
frame_id: int | None = None
face_crop_path: str | None = None
metadata: dict[str, Any] = field(default_factory=dict)
created_at: datetime = field(default_factory=datetime.utcnow)
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/db_worker.py`, `src/events/event_manager.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/events/event_manager.py`

<a id="class-65"></a>

### 65. `VehiclePassage`

Nguồn: [src/events/event_manager.py:45](../src/events/event_manager.py#L45). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Trạng thái passage xe đang chạy trong RAM, tích lũy thời gian/ảnh/biển số rồi chuyển thành VehiclePassageDTO để ghi DB.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
camera_id: str
track_id: int
id: UUID = field(default_factory=uuid4)
session_key: str = ''
vehicle_type: str = 'vehicle'
vehicle_color: str | None = None
vehicle_type_confidence: float | None = None
vehicle_color_confidence: float | None = None
zone_id: str | None = None
video_source_id: UUID | None = None
plate_text: str = ''
plate_status: str = 'SEARCHING'
plate_confidence: float = 0.0
direction: str = 'UNKNOWN'
first_seen: float = 0.0
last_seen: float = 0.0
duration: float = 0.0
best_vehicle_image: np.ndarray | None = None
best_plate_image: np.ndarray | None = None
best_vehicle_image_path: str | None = None
best_plate_image_path: str | None = None
entered: bool = False
in_zone: bool = False
exited: bool = False
best_vehicle_crop_quality: float = -1.0
best_vehicle_frame_id: int = -1
last_crop_frame_id: int = -999
plate_state: Any = None
best_vehicle_area: float = 0.0
plate_confirmed_emitted: bool = False
confirmed_plate: str = ''
created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
finalized_at: datetime | None = None
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__post_init__(self) → None` | Hoàn thiện/chuẩn hóa trạng thái sau constructor dataclass. |
| `to_dto(self, is_final: bool=False) → VehiclePassageDTO` | Convert internal RAM session state to immutable DTO for DB worker. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/tools/analytics.py`, `src/agent/tools/reports.py`, `src/db/repositories/__init__.py`, `src/events/__init__.py`, `src/event_center/service.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-66"></a>

### 66. `EventManager`

Nguồn: [src/events/event_manager.py:134](../src/events/event_manager.py#L134). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Chuyển kết quả tracking/đếm/nhận diện thành sự kiện nghiệp vụ, quản lý passage và đưa DTO vào worker ghi DB; không tự thực hiện YOLO.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_active_passages`, `_candidate_count`, `_candidate_since`, `_emitted_face_tracks`, `_episodes`, `_last_camera_id`, `_last_event_time`, `_last_people_count`, `_last_report_time`, `_last_saved_count`, `db_worker`, `event_report_interval`, `last_db_work_ms`, `last_event_build_ms`, `min_snapshot_interval_sec`, `state`, `storage`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, storage: EventStorage=event_storage, state: SharedRuntimeState=shared_state, min_snapshot_interval_sec: float=SNAPSHOT_INTERVAL_SECONDS, event_report_interval: float=EVENT_REPORT_INTERVAL, db_worker: DatabaseWorker \| None=None) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `process_frame(self, camera_id, people_count, annotated_frame=None, video_source_id=None, location=None)` | Persist only a continuously sustained crowd threshold episode. |
| `_persist_threshold(self, camera_id, event, frame, video_source_id)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `process_vehicle_frame(self, camera_id, vehicle_tracks, plate_results=None, in_zone_ids=None, zone_id=None, frame=None, video_source_id=None, frame_id=0)` | Keep normal tracks in RAM; finalize through the existing watchlist gate. |
| `_collect_confirmed_plate(passage)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `_finalize_vehicle(self, passage)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `process_face_matches(self, camera_id: str, target_matches: dict[int, Any] \| None, track_states: dict[int, Any] \| None=None, tracks: Any=None, frame: np.ndarray \| None=None, video_source_id: UUID \| str \| None=None, frame_id: int=0) → list[dict[str, Any]]` | Process target matcher face recognition results and emit FaceEvents asynchronously. |
| `reset(self)` | Finalize pending vehicle sessions and end continuity on a source reset. |
| `stop(self) → None` | Cleanly terminate background worker, draining any queued items. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/__init__.py`, `scripts/validate_e2e_postgres.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/events/event_storage.py`

<a id="class-67"></a>

### 67. `EventStorage`

Nguồn: [src/events/event_storage.py:25](../src/events/event_storage.py#L25). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Nhánh lưu sự kiện đếm người và snapshot bằng SQLite, có lưu passage; cần phân biệt với DatabaseWorker và PostgreSQL chính.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_lock`, `db_path`, `snapshot_dir`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, db_path: Path \| str \| None=None, snapshot_dir: Path \| str \| None=None) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `_init_storage(self) → None` | Create database file, parent directories, and schema table. |
| `save_event(self, timestamp: str, camera_id: str, event_type: str, old_value: int, new_value: int, annotated_frame: np.ndarray \| None=None) → tuple[int, str]` | Save event record and optional image snapshot to SQLite. |
| `get_recent_events(self, limit: int=20, camera_id: str \| None=None) → list[dict[str, Any]]` | Fetch the most recent events ordered by timestamp descending. |
| `get_event_count_today(self) → int` | Count total events logged today (local date). |
| `save_passage(self, passage: Any) → int` | Save a finalized VehiclePassage record and best images to SQLite. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/event_manager.py`, `src/events/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/events/policy.py`

<a id="class-68"></a>

### 68. `Episode`

Nguồn: [src/events/policy.py:15](../src/events/policy.py#L15). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang trạng thái một đợt vượt ngưỡng: lúc bắt đầu, token và trạng thái đã kích hoạt.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
started: float
wall_started: float
token: str
active: bool = False
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-69"></a>

### 69. `ThresholdEpisodes`

Nguồn: [src/events/policy.py:22](../src/events/policy.py#L22). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Quản lý đợt vượt ngưỡng theo camera/vị trí, phát sự kiện khi đủ điều kiện và tránh phát lặp trong cùng đợt.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `crowds`, `vehicles`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `people(self, camera_id, count, now, wall, location=None)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `congestion(self, camera_id, count, now, wall, location=None)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `reset(self)` | Đặt lại trạng thái. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/event_manager.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/face/adaptive_pipeline.py`

<a id="class-70"></a>

### 70. `CandidateBuffer`

Nguồn: [src/face/adaptive_pipeline.py:212](../src/face/adaptive_pipeline.py#L212). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Giữ lịch sử ứng viên khuôn mặt có giới hạn theo camera/track; tránh nhận nhiều representation của cùng frame.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `candidates`, `capacity`, `key`, `last_frame_id`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, camera_id: str, track_id: int, capacity: int=64)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `add(self, candidate: dict) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `selected(self) → list[dict]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/recognition/target_matcher.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-71"></a>

### 71. `AdaptiveFacePipeline`

Nguồn: [src/face/adaptive_pipeline.py:234](../src/face/adaptive_pipeline.py#L234). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Xử lý khuôn mặt sau phát hiện SCRFD: kiểm tra hình học, căn chỉnh/biến đổi theo điều kiện và tạo embedding AdaFace; không tự đối chiếu gallery.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `counters`, `embedder`, `last_observation`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, embedder=None)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `enroll_original(self, image)` | One original-only enrollment vector; no synthetic gallery or live regeneration. |
| `process(self, roi, bbox, score, kps, *, camera_id, track_id, frame_id, timestamp)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `valid_embedding(embedding)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/recognition/target_matcher.py`, `scripts/colab_startup.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/face/experimental_adaface.py`

<a id="class-72"></a>

### 72. `AdaFaceEmbedder`

Nguồn: [src/face/experimental_adaface.py:31](../src/face/experimental_adaface.py#L31). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Bọc model AdaFace ONNX để tạo vector khuôn mặt 512 chiều được chuẩn hóa; module đặt tên experimental nhưng có thể được code khác gọi.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
_instance: 'AdaFaceEmbedder | None' = None
_lock = threading.Lock()
```

**Trạng thái được gán trong constructor:** `_infer_lock`, `_init_error`, `_initialized`, `_session`, `embedding_dim`, `execution_provider`, `input_name`, `model_name`, `model_path`, `model_version`, `output_name`, `prefer_gpu`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, model_path: str \| Path \| None=None, prefer_gpu: bool=True) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `get_instance(cls, model_path: str \| Path \| None=None) → 'AdaFaceEmbedder'` | Thread-safe access to singleton instance. |
| `initialize(self) → bool` | Load AdaFace ONNX model on CUDA (GPU) or log fallback to CPU. |
| `align_and_embed(self, native_frame: np.ndarray, kps: np.ndarray) → np.ndarray \| None` | Extract 512D AdaFace embedding from native frame using SCRFD 5-point landmarks. |
| `embed_aligned_face(self, aligned_bgr_112: np.ndarray) → np.ndarray \| None` | Extract L2-normalized 512D AdaFace embedding from already aligned 112x112 BGR face. |
| `extract_face_embedding(self, image: np.ndarray) → tuple[np.ndarray \| None, dict[str, Any]]` | Detect best face using SCRFD and return L2-normalized AdaFace embedding. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/face/adaptive_pipeline.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/face/face_embedder.py`

<a id="class-73"></a>

### 73. `FaceDiagInfo`

Nguồn: [src/face/face_embedder.py:28](../src/face/face_embedder.py#L28). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang thông tin chẩn đoán phát hiện/embedding khuôn mặt: model/provider, bbox, confidence, lý do từ chối và kiểm tra vector.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
model_name: str = 'buffalo_s'
model_path: str = ''
model_loaded: bool = False
execution_provider: str = 'CPUExecutionProvider'
det_size: tuple[int, int] = (320, 320)
faces_detected: int = 0
confidences: list[float] = field(default_factory=list)
bounding_boxes: list[list[float]] = field(default_factory=list)
landmarks_count: int = 0
rejection_reason: str | None = None
user_message: str = ''
embedding_norm: float | None = None
embedding_dims: int | None = None
has_nan: bool = False
has_inf: bool = False
is_zero: bool = False
rotation_applied: int = 0
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `to_dict(self) → dict[str, Any]` | Chuyển dữ liệu sang dictionary. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-74"></a>

### 74. `FaceEmbedder`

Nguồn: [src/face/face_embedder.py:174](../src/face/face_embedder.py#L174). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Singleton phân tích khuôn mặt: phát hiện SCRFD, kiểm tra ánh sáng/landmark/chất lượng, căn chỉnh và trích xuất embedding; không quyết định target nào khớp.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
_instance: 'FaceEmbedder | None' = None
_lock = threading.Lock()
```

**Trạng thái được gán trong constructor:** `_app`, `_infer_lock`, `_init_error`, `_initialized`, `_model_path`, `det_size`, `execution_provider`, `model_name`, `prefer_gpu`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, model_name: str='buffalo_s', det_size: list[tuple[int, int]] \| tuple[int, int]=[(320, 320), (640, 640)], prefer_gpu: bool=True) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `get_instance(cls) → 'FaceEmbedder'` | Thread-safe access to singleton instance. |
| `initialize(self) → bool` | Load InsightFace models into memory on GPU (CUDA) or fallback to CPU. |
| `analyze_illumination(roi: np.ndarray) → dict[str, Any]` | Analyze local illumination statistics on head/face ROI using luminance. |
| `check_illumination(cls, roi: np.ndarray) → tuple[str, str, np.ndarray]` | Check illumination of head/face ROI using luminance statistics. |
| `validate_landmarks(kps: np.ndarray, face_bbox: list \| tuple) → tuple[bool, str]` | Validate 5-point facial landmark geometry before embedding. |
| `detect_faces_in_roi(self, roi: np.ndarray, illumination: str='NORMAL', enhanced_roi: np.ndarray \| None=None, return_diag: bool=False, single_pass: bool=False) → list[dict[str, Any]] \| tuple[list[dict[str, Any]], dict[str, Any]]` | Detect faces within upper-body/head ROI using SCRFD. |
| `calculate_face_quality(self, native_frame: np.ndarray, face_bbox: Any, conf: float, illumination: str, kps: np.ndarray \| None=None) → tuple[float, float, float, str]` | Evaluate face quality against quality gates from native face pixels. |
| `align_and_embed(self, native_frame: np.ndarray, kps: np.ndarray, illumination: str='NORMAL', variant: str='RAW') → np.ndarray \| None` | Preprocess face with landmark alignment and extract ArcFace embedding. |
| `extract_face_embedding_detailed(self, image: np.ndarray, is_registration: bool=False, min_confidence: float=0.35) → tuple[np.ndarray \| None, FaceDiagInfo]` | Detect the best face in BGR image and return normalized embedding with full diagnostics. |
| `extract_face_embedding(self, image: np.ndarray) → np.ndarray \| None` | Detect the largest face in image and return normalized 512-dim embedding. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/face/adaptive_pipeline.py`, `src/face/experimental_adaface.py`, `scripts/colab_startup.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/notifications/base.py`

<a id="class-75"></a>

### 75. `NotificationAdapter`

Nguồn: [src/notifications/base.py:8](../src/notifications/base.py#L8). Loại: **Interface / hợp đồng**.

**Dùng để làm gì / câu trả lời ngắn:** Protocol giao diện send cho kênh thông báo; cho phép service dùng adapter thật hoặc giả trong test mà không phụ thuộc SMTP cụ thể.

**Kế thừa trực tiếp:** `Protocol`

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `send(self, notification) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/notifications/email.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/notifications/config.py`

<a id="class-76"></a>

### 76. `EmailConfig`

Nguồn: [src/notifications/config.py:35](../src/notifications/config.py#L35). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang cấu hình SMTP và chính sách cooldown/retry, đọc từ môi trường và kiểm tra cấu hình có đủ không.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
host: str = ''
port: int = 587
username: str = field(default='', repr=False)
password: str = field(default='', repr=False)
sender: str = field(default='', repr=False)
recipients: tuple[str, ...] = field(default=(), repr=False)
tls: str = 'starttls'
cooldown: int = 300
max_retries: int = 3
retry_seconds: int = 30
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `configured(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `from_env(cls)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/notifications/alerts.py`, `src/notifications/service.py`, `scripts/colab_startup.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/notifications/email.py`

<a id="class-77"></a>

### 77. `SMTPEmailAdapter`

Nguồn: [src/notifications/email.py:9](../src/notifications/email.py#L9). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Tạo email và gửi bằng SMTP theo EmailConfig; thực thi giao diện gửi thông báo.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `config`, `storage_factory`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, config, storage_factory=None)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `message(self, item)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `send(self, item)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/notifications/service.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/notifications/service.py`

<a id="class-78"></a>

### 78. `NotificationService`

Nguồn: [src/notifications/service.py:14](../src/notifications/service.py#L14). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Quản lý transactional outbox, chống gửi trùng/cooldown và worker giao email có retry; chỉ worker giao nhận thực hiện kết nối gửi email.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_stop`, `_thread`, `adapters`, `config`, `db`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, db, config=None, adapters=None)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `_retryable(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `_reserved(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `enqueue_face(self, session, event, dto)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `enqueue_vehicle(self, session, event, match)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `deliver_one(self, now=None)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `start(self)` | Khởi động xử lý/tài nguyên. |
| `stop(self, timeout=1)` | Dừng xử lý và dọn tài nguyên. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/db_worker.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/ocr/plate_detector.py`

<a id="class-79"></a>

### 79. `PlateBox`

Nguồn: [src/ocr/plate_detector.py:27](../src/ocr/plate_detector.py#L27). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** NamedTuple mang bounding box biển số được phát hiện và confidence.

**Kế thừa trực tiếp:** `NamedTuple`

**Các trường khai báo trực tiếp:**

```python
x1: int
y1: int
x2: int
y2: int
confidence: float
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-80"></a>

### 80. `PlateDetector`

Nguồn: [src/ocr/plate_detector.py:37](../src/ocr/plate_detector.py#L37). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Singleton bọc model phát hiện vị trí biển số trong ảnh; tìm vùng biển số, không đọc ký tự.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
_instance: 'PlateDetector | None' = None
```

**Trạng thái được gán trong constructor:** `_conf_threshold`, `_device`, `_error`, `_initialized`, `_model`, `_model_path`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, model_path: str \| None=None, conf_threshold: float=0.25, device: str='cpu') → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `get_instance(cls) → 'PlateDetector'` | Return the process-level singleton, initializing on first call. |
| `initialize(self) → bool` | Load the plate detection model.  Returns True on success. |
| `detect(self, vehicle_crop: np.ndarray) → list[PlateBox]` | Detect license plate regions within a vehicle crop. |
| `is_available(self) → bool` | True if model loaded successfully. |
| `model_name(self) → str` | Human-readable model identifier. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/ocr/plate_reader.py`, `scripts/colab_startup.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/ocr/plate_line_recognizer.py`

<a id="class-81"></a>

### 81. `LinePlate`

Nguồn: [src/ocr/plate_line_recognizer.py:23](../src/ocr/plate_line_recognizer.py#L23). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang kết quả đọc một dòng/biển số cùng điểm và thông tin phụ do recognizer tạo.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
text: str
confidence: float
raw_text: str
bbox: tuple[int, int, int, int]
crop: np.ndarray
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-82"></a>

### 82. `PlateLineRecognizer`

Nguồn: [src/ocr/plate_line_recognizer.py:31](../src/ocr/plate_line_recognizer.py#L31). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Chuẩn bị ảnh và đọc ký tự theo dòng/vùng biển số bằng recognizer; hỗ trợ lựa chọn vùng và đọc cả biển.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_lock`, `characters`, `input_name`, `session`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, path=MODEL_PATH)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `prepare(image)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `read_line(self, image)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `plate_regions(image, bbox)` | Keep original detector ROI plus one bounded bright-background crop. |
| `read_plate(self, image, bbox, validator)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/ocr/plate_reader.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/ocr/plate_reader.py`

<a id="class-83"></a>

### 83. `PlateCandidate`

Nguồn: [src/ocr/plate_reader.py:43](../src/ocr/plate_reader.py#L43). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang ứng viên kết quả biển số từ OCR để đánh giá và lựa chọn.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
plate_text: str
confidence: float
bbox_vehicle: tuple[int, int, int, int]
bbox_native: tuple[int, int, int, int]
raw_crop: np.ndarray
preprocessed_crop: np.ndarray
sharpness: float
quality_score: float
raw_text: str = ''
normalized_text: str = ''
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__post_init__(self)` | Hoàn thiện/chuẩn hóa trạng thái sau constructor dataclass. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/ocr/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-84"></a>

### 84. `LicensePlateReader`

Nguồn: [src/ocr/plate_reader.py:172](../src/ocr/plate_reader.py#L172). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Điều phối tìm/cắt biển số, chỉnh phối cảnh/nghiêng, tạo biến thể tiền xử lý và OCR để lấy nội dung biển số.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
_instance: 'LicensePlateReader | None' = None
_lock = threading.Lock()
```

**Trạng thái được gán trong constructor:** `_debug_dir`, `_debug_sample_count`, `_device`, `_infer_lock`, `_line_recognizer`, `_line_recognizer_attempted`, `_max_debug_samples`, `_ocr_context`, `_plate_detector`, `_reader`, `_reader_error`, `_reader_initialized`, `min_confidence`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, min_confidence: float=0.35) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `device(self) → str` | Current execution device for EasyOCR ('CUDA' or 'CPU'). |
| `get_instance(cls) → 'LicensePlateReader'` | Thread-safe singleton accessor. |
| `initialize(self) → bool` | Initialize EasyOCR reader with GPU acceleration when CUDA is available, with safe CPU fallback. |
| `rectify_plate_perspective(self, vehicle_crop: np.ndarray, plate_bbox: tuple[int, int, int, int] \| Sequence[int]) → tuple[np.ndarray, float]` | Detect plate orientation/corners and apply perspective rectification / deskew into a normalized crop. |
| `deskew_plate(self, crop: np.ndarray) → tuple[np.ndarray, float]` | Detect tilt angle and apply perspective / affine deskew correction. |
| `generate_preprocessing_variants(self, crop: np.ndarray) → tuple[dict[str, np.ndarray], dict[str, Any]]` | Generate 3 image variants for OCR and extract diagnostic metadata. |
| `preprocess_plate_crop(self, crop: np.ndarray) → np.ndarray` | Enhance plate readability via deskew, adaptive resize, gamma, CLAHE, bilateral denoise, and sharpening. |
| `_parse_plate_text_from_ocr_boxes(self, ocr_results: list[Any]) → tuple[str, float]` | Extract plate text and confidence from EasyOCR bounding boxes on a plate crop. |
| `evaluate_variants(self, variants: dict[str, np.ndarray], baseline_text: str='', baseline_conf: float=0.0, track_id: int=-1, frame_id: int=-1) → tuple[str, str, float, np.ndarray]` | Run EasyOCR on variants and select the best candidate. |
| `_save_debug_sample(self, vehicle_crop: np.ndarray, plate_crop: np.ndarray, preprocessed_crop: np.ndarray, track_id: int, frame_id: int, plate_text: str, conf: float, rectified_crop: np.ndarray \| None=None, binary_crop: np.ndarray \| None=None) → None` | Save bounded proof of plate acquisition in scratch/plate_debug/. |
| `_parse_plate_candidates(self, ocr_results: list[Any], vehicle_crop: np.ndarray, roi_y1: int, vx1: int, vy1: int, vw: int, vh: int, track_id: int=-1, frame_id: int=-1) → list[PlateCandidate]` | Group and assemble OCR text boxes into 1-line or 2-tier plate candidates. |
| `_detect_plate_bbox(self, vehicle_crop: np.ndarray, track_id: int=-1, frame_id: int=-1) → 'tuple[int, int, int, int, float] \| None'` | Run the dedicated YOLO plate detector on the vehicle crop. |
| `_adaptive_upscale_plate(crop: np.ndarray) → tuple[np.ndarray, float]` | Bounded adaptive upscale for tight plate crops (aspect-ratio preserved, INTER_CUBIC). |
| `extract_license_plate(self, vehicle_crop: np.ndarray, native_vehicle_bbox: Sequence[int], track_id: int=-1, frame_id: int=-1) → PlateCandidate \| None` | Localize and recognize license plate within vehicle crop. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/ocr/plate_tracker.py`, `src/ocr/__init__.py`, `scripts/colab_startup.py`, `scripts/validate_plate_runtime.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/ocr/plate_tracker.py`

<a id="class-85"></a>

### 85. `PlateTrackState`

Nguồn: [src/ocr/plate_tracker.py:33](../src/ocr/plate_tracker.py#L33). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Giữ trạng thái đọc biển số theo track qua nhiều frame, gồm ứng viên và kết quả xác nhận; không tương đương bản ghi PlateEvent.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
track_id: int
vehicle_class: str = 'vehicle'
plate_text: str = ''
confidence: float = 0.0
plate_bbox_native: tuple[int, int, int, int] | None = None
plate_crop: np.ndarray | None = None
plate_quality: float = 0.0
frame_id: int = -1
last_eval_frame: int = -999
last_bbox_area: float = 0.0
max_bbox_area: float = 0.0
eval_count: int = 0
status: str = 'SEARCHING'
provisional_plate: str = ''
provisional_confidence: float = 0.0
provisional_score: float = 0.0
provisional_frame_id: int = -1
confirmed_plate: str = ''
confirmed_frame_id: int = -1
raw_text: str = ''
normalized_text: str = ''
candidate_text: str = ''
consensus_count: int = 0
last_result_frame: int = -1
generation: int = 0
plate_history: list[Any] = None
vote_scores: dict[str, float] = None
candidate_crops: list[Any] = None
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__post_init__(self) → None` | Hoàn thiện/chuẩn hóa trạng thái sau constructor dataclass. |
| `to_dict(self) → dict[str, Any]` | Chuyển dữ liệu sang dictionary. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/ocr/__init__.py`, `scripts/verify_overlay_on_real_frame.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-86"></a>

### 86. `_OcrJob`

Nguồn: [src/ocr/plate_tracker.py:182](../src/ocr/plate_tracker.py#L182). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** NamedTuple đóng gói tác vụ OCR để chuyển từ vòng tracking sang worker nền.

**Kế thừa trực tiếp:** `NamedTuple`

**Các trường khai báo trực tiếp:**

```python
track_id: int
frame_id: int
vehicle_crop: np.ndarray
native_vehicle_bbox: tuple[int, int, int, int]
vehicle_class: str
eval_count: int
generation: int = 0
quality_score: float = 0.0
plate_det_conf: float = 0.0
plate_w: int = 0
plate_h: int = 0
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-87"></a>

### 87. `_OcrWorker`

Nguồn: [src/ocr/plate_tracker.py:197](../src/ocr/plate_tracker.py#L197). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Worker OCR nền có queue, nhận job và trả kết quả; cho phép hủy/xóa job và tách inference OCR khỏi vòng frame.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_condition`, `_last_ocr_worker_ms`, `_manager`, `_pending`, `_stopped`, `_thread`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, manager, start_thread: bool=True)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `last_ocr_worker_ms(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `queue_size(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get_pending_job(self, track_id: int) → _OcrJob \| None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `enqueue(self, job: _OcrJob) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `discard(self, track_id: int) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `clear(self) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `stop(self) → None` | Dừng xử lý và dọn tài nguyên. |
| `_run(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-88"></a>

### 88. `VehiclePlateManager`

Nguồn: [src/ocr/plate_tracker.py:289](../src/ocr/plate_tracker.py#L289). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Quản lý PlateTrackState theo xe, chọn/lập lịch job OCR và hợp nhất kết quả qua nhiều frame.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_generation`, `_lock`, `_plate_states`, `_track_last_seen`, `_worker`, `_worker_lock`, `async_worker`, `consensus_ratio`, `eval_interval`, `history_size`, `last_timings`, `min_confidence`, `min_observations`, `min_quality`, `reader`, `recheck_interval`, `ttl_frames`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, reader: LicensePlateReader \| None=None, eval_interval: int=CADENCE_UNRECOGNIZED_FRAMES, ttl_frames: int=EXPIRATION_TTL_FRAMES, async_worker: bool=False, min_observations: int \| None=None, min_confidence: float \| None=None, min_quality: float \| None=None, history_size: int \| None=None, consensus_ratio: float \| None=None, recheck_interval: int \| None=None) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `last_ocr_worker_ms(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `ocr_queue_size(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `stop(self) → None` | Stop the async OCR worker thread. |
| `_get_worker(self) → _OcrWorker` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `_apply_ocr_result(self, job: _OcrJob, cand: Any) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get_plate_state(self, track_id: int) → PlateTrackState \| None` | Retrieve PlateTrackState for a specific vehicle track. |
| `get_all_plate_states(self) → dict[int, PlateTrackState]` | Retrieve copy of all active plate states. |
| `process_vehicle_tracks(self, frame: np.ndarray, car_tracks: Any=None, frame_id: int=0, vehicle_tracks: Any=None) → dict[int, PlateTrackState]` | Evaluate active vehicle tracks for license plate detection & OCR. |
| `get_pending_ocr_job(self, track_id: int) → _OcrJob \| None` | Retrieve the pending _OcrJob for track_id if currently queued. |
| `reset_tracks(self) → None` | Clear all vehicle track associations (called on camera/source switch). |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/ocr/__init__.py`, `scripts/validate_plate_runtime.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/ops/runner.py`

<a id="class-89"></a>

### 89. `SafeOutput`

Nguồn: [src/ops/runner.py:13](../src/ops/runner.py#L13). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Bọc stdout/stderr để che giá trị bí mật và URL trong log tiến trình được CLI giám sát; không thay đổi cấu hình kết nối.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `secrets`, `stream`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, stream)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `write(self, value)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `flush(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `isatty(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/recognition/color_extractor.py`

<a id="class-90"></a>

### 90. `ColorAnalysisResult`

Nguồn: [src/recognition/color_extractor.py:28](../src/recognition/color_extractor.py#L28). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang kết quả phân tích màu trang phục: tên màu và thông tin định lượng đi kèm.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
dominant_color: str
confidence: float
color_distribution: dict[str, float]
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-91"></a>

### 91. `ClothingColorExtractor`

Nguồn: [src/recognition/color_extractor.py:35](../src/recognition/color_extractor.py#L35). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Cắt vùng thân người và phân tích màu trang phục; không dùng để nhận diện khuôn mặt.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `min_valid_pixels`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, min_valid_pixels: int=40) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `extract_torso_crop(self, frame: np.ndarray, bbox: Sequence[float \| int]) → np.ndarray \| None` | Extract central upper-body torso region from a full frame and person bbox. |
| `analyze_crop(self, crop: np.ndarray) → ColorAnalysisResult \| None` | Classify dominant color of a cropped torso image in HSV space. |
| `extract_clothing_color(self, frame: np.ndarray, bbox: Sequence[float \| int]) → ColorAnalysisResult \| None` | Convenience method combining crop and color analysis. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/recognition/target_matcher.py`

<a id="class-92"></a>

### 92. `TargetRegistrationError`

Nguồn: [src/recognition/target_matcher.py:41](../src/recognition/target_matcher.py#L41). Loại: **Exception / loại lỗi**.

**Dùng để làm gì / câu trả lời ngắn:** Lỗi nghiệp vụ đăng ký target khi ảnh/embedding không đáp ứng yêu cầu, để caller trả lỗi phù hợp.

**Kế thừa trực tiếp:** `ValueError`

**Trạng thái được gán trong constructor:** `code`, `details`, `message`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, code: str, message: str, details: dict[str, Any] \| None=None) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/ui/video_stream.py`, `src/ui/web_server.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-93"></a>

### 93. `Target`

Nguồn: [src/recognition/target_matcher.py:52](../src/recognition/target_matcher.py#L52). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Đối tượng target trong gallery RAM: tên, vector và thông tin tham chiếu dùng để đối chiếu runtime; khác model ORM Target.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
id: str
name: str
face_embedding: np.ndarray | None = None
clothing_color: str | None = None
face_threshold: float = DEFAULT_FACE_THRESHOLD
has_face: bool = False
source_image_path: str | None = None
db_id: str | None = None
is_selected: bool = True
embedding_model: str = 'adaface_ir50_ms1mv2'
created_at: str = field(default_factory=lambda: datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `to_dict(self) → dict[str, Any]` | Chuyển dữ liệu sang dictionary. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/agent/identity_resolution.py`, `src/agent/tools/alerts.py`, `src/agent/tools/notifications.py`, `src/agent/tools/notification_queries.py`, `src/agent/tools/watchlist.py`, `src/db/repositories/__init__.py`, `src/events/db_worker.py`, `src/notifications/alerts.py`, `src/notifications/service.py`, `src/recognition/target_selection.py`, `src/ui/web_server.py`, `scripts/explain_queries.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-94"></a>

### 94. `BestFaceState`

Nguồn: [src/recognition/target_matcher.py:83](../src/recognition/target_matcher.py#L83). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Giữ ứng viên khuôn mặt và trạng thái nhận diện tốt nhất theo track qua nhiều frame.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
track_id: int
face_size: float = 0.0
confidence: float = 0.0
sharpness: float = 0.0
lighting: str = 'NORMAL'
quality_score: float = 0.0
frontality: float = 0.0
frame_id: int = -1
embedding: np.ndarray | None = None
similarity: float = 0.0
threshold: float = DEFAULT_FACE_THRESHOLD
decision: str = 'WAIT_FOR_BETTER_FACE'
matched_target_id: str | None = None
matched_target_name: str | None = None
last_eval_frame: int = -1
last_bbox_area: float = 0.0
attempts_count: int = 0
consecutive_below_thresh: int = 0
candidate_face_size: float = 0.0
candidate_confidence: float = 0.0
candidate_sharpness: float = 0.0
candidate_quality_score: float = 0.0
candidates: list[dict] = field(default_factory=list)
fused_embedding: np.ndarray | None = None
camera_id: str = ''
candidate_buffer: CandidateBuffer | None = None
selected_candidates: list[dict] = field(default_factory=list)
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-95"></a>

### 95. `TargetMatchInfo`

Nguồn: [src/recognition/target_matcher.py:143](../src/recognition/target_matcher.py#L143). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang kết quả đối chiếu một track với target cùng thông tin quyết định/độ tương đồng.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
track_id: int
target_id: str
target_name: str
score: float
match_type: str
evaluated_at_frame: int
decision: str = 'FACE_MATCH'
face_size: float = 0.0
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-96"></a>

### 96. `TargetManager`

Nguồn: [src/recognition/target_matcher.py:155](../src/recognition/target_matcher.py#L155). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Quản lý gallery target trong RAM: đăng ký từ ảnh, thêm từ DB, chọn target cần theo dõi và xóa target.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_lock`, `_targets`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `register_target(self, name: str, face_image: np.ndarray \| None=None, clothing_color: str \| None=None, face_threshold: float=DEFAULT_FACE_THRESHOLD, target_id: str \| None=None, source_image_path: str \| None=None) → Target` | Register a new target with optional face and/or clothing color. |
| `remove_target(self, target_id: str) → bool` | Remove a target by ID. |
| `get_target(self, target_id: str) → Target \| None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `list_targets(self) → list[Target]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `set_target_selection(self, target_id: str, is_selected: bool) → bool` | Update selection status of a target. |
| `select_targets(self, target_ids: Sequence[str]) → None` | Select specific targets or all if target_ids is empty. |
| `add_target_from_db(self, target_id: str, name: str, face_embedding: np.ndarray \| None=None, clothing_color: str \| None=None, face_threshold: float=DEFAULT_FACE_THRESHOLD, source_image_path: str \| None=None, db_id: str \| None=None, embedding_model: str='adaface_ir50_ms1mv2') → Target` | Add or restore an existing target loaded from database. |
| `clear(self) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-97"></a>

### 97. `TargetMatcher`

Nguồn: [src/recognition/target_matcher.py:326](../src/recognition/target_matcher.py#L326). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Duyệt track người, lấy khuôn mặt đủ chất lượng, tạo embedding và đối chiếu gallery; giữ trạng thái theo track và trả kết quả matching.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_best_faces`, `_camera_id`, `_debug_sample_count`, `_debug_sample_dir`, `_last_logs`, `_lock`, `_matched_tracks`, `_max_debug_samples`, `_track_face_cache`, `_track_last_eval`, `_track_last_seen`, `face_pipeline`, `last_timings`, `manager`, `re_eval_interval`, `ttl_frames`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, manager: TargetManager, re_eval_interval: int=RE_EVALUATION_INTERVAL_FRAMES, ttl_frames: int=TRACK_EXPIRATION_TTL_FRAMES) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `_save_face_debug_sample(self, source_native: np.ndarray, person_bbox: Sequence[int], roi_bbox: Sequence[int], roi_before: np.ndarray, roi_after: np.ndarray \| None, enhanced_roi: np.ndarray \| None, track_id: int, frame_id: int, face_bbox_native: Sequence[float] \| None=None) → None` | Save visual proof of face acquisition in scratch/face_debug/ (bounded). |
| `get_track_state(self, track_id: int) → BestFaceState \| None` | Retrieve the BestFaceState for a specific track. |
| `get_all_track_states(self) → dict[int, BestFaceState]` | Retrieve copy of all active BestFaceStates. |
| `_log_face_rec(self, track_id: int, frame_id: int, native_w: int, native_h: int, bbox: Sequence[int], roi_size: tuple[int, int], illumination: str, enhancement_applied: str, face_size: int, face_conf: float, sharpness: float, best_replaced: bool, emb_recomputed: bool, similarity: float, threshold: float, decision: str, target_name: str \| None) → None` | Structured single-line log conforming to Point 11 with de-duplication. |
| `match_tracks(self, frame, tracks, frame_id, native_frame=None, camera_id='', timestamp=None)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `_match_tracks(self, frame: np.ndarray, tracks: Any, frame_id: int, native_frame: np.ndarray \| None=None, camera_id: str='', timestamp: float \| None=None) → dict[int, TargetMatchInfo]` | Evaluate and associate tracks with targets. |
| `_evaluate_single_track_native(self, source_native: np.ndarray, native_bbox: list[int], track_id: int, targets: list[Target], frame_id: int, bbox_area: float, state: BestFaceState) → TargetMatchInfo \| None` | Extract features from native frame and compare against registered targets. |
| `reset_tracks(self) → None` | Clear all track associations (called when camera/source switches). |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/runtime/runtime_manager.py`

<a id="class-98"></a>

### 98. `RuntimeManager`

Nguồn: [src/runtime/runtime_manager.py:53](../src/runtime/runtime_manager.py#L53). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Điều phối pipeline AI và web server, kiểm tra cổng, quản lý thread/tín hiệu và shutdown; không phải model inference.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_ai_thread`, `_is_shutting_down`, `_lock`, `_stop_event`, `_uvicorn_server`, `_web_thread`, `ai_host`, `ai_port`, `camera_id`, `img_size`, `max_frames`, `ui_enabled`, `web_host`, `web_port`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, camera_id: str \| None=None, web_host: str='0.0.0.0', web_port: int=8501, ai_host: str='127.0.0.1', ai_port: int=8000, ui_enabled: bool=True, max_frames: int \| None=None, img_size: int=960) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `validate_ports(self) → None` | Validate network ports before launching services to prevent binding errors. |
| `start_ai_pipeline(self) → None` | Start the AI detection and tracking pipeline in a dedicated worker thread. |
| `start_web_server(self) → None` | Start FastAPI dashboard in a dedicated daemon thread. |
| `_setup_signal_handlers(self) → None` | Register signal handlers for clean OS termination. |
| `_handle_signal(self, signum: int, frame: Any) → None` | Handle incoming termination signal. |
| `start(self) → None` | Start both the AI pipeline and the web server. |
| `run(self) → None` | Run runtime manager synchronously, blocking until interrupted. |
| `shutdown(self) → None` | Coordinate graceful shutdown of all threads and release resources. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/main.py`, `src/runtime/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/runtime/shared_state.py`

<a id="class-99"></a>

### 99. `TelemetrySnapshot`

Nguồn: [src/runtime/shared_state.py:17](../src/runtime/shared_state.py#L17). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Snapshot các chỉ số vận hành để trả qua API: FPS, độ trễ, thiết bị, số đối tượng và trạng thái.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
frame_id: int = 0
timestamp: float = 0.0
status: str = 'STOPPED'
camera_status: str = 'STOPPED'
stream_alive: bool = False
last_frame_time: float = 0.0
error_message: str = ''
people_count: int = 0
car_count: int = 0
detection_count: int | None = 0
track_count: int = 0
is_fallback: bool = False
stream_fps: float = 0.0
processing_fps: float = 0.0
yolo_latency_ms: float = 0.0
pipeline_latency_ms: float = 0.0
device: str = 'CPU'
gpu_name: str = 'CPU'
vram_mb: float = 0.0
model_name: str = 'YOLO11s'
input_size: str = '640x640'
camera_id: str = 'camera_01'
camera_name: str = ''
last_event: str = 'None'
event_count_today: int = 0
filtered_event_count: int = 0
last_event_time: str = 'None'
last_saved_people_count: int = 0
stream_health: dict[str, Any] | None = None
capture_fps: float = 0.0
inference_fps: float = 0.0
display_fps: float = 0.0
dropped_frames: int = 0
buffer_age_ms: float = 0.0
zone_enabled: bool = False
zone_mode: str = 'full_view'
car_count_label: str = 'VEHICLES IN VIEW'
vehicles_in_view: int = 0
vehicles_in_zone: int = 0
source_generation: int = 1
mjpeg_clients: int = 0
mjpeg_connection_generation: int = 0
last_jpeg_success: bool = True
last_jpeg_error: str = ''
decoded_frames_total: int = 0
decoded_fps: float = 0.0
paced_frames_total: int = 0
paced_fps: float = 0.0
published_frames_total: int = 0
publish_fps: float = 0.0
frames_dropped_by_pacer: int = 0
jitter_buffer_frames: int = 0
jitter_buffer_ms: float = 0.0
last_decoded_frame_age: float = 0.0
last_paced_frame_age: float = 0.0
last_published_frame_age: float = 0.0
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `to_dict(self) → dict[str, Any]` | Convert snapshot to standard Python dict. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-100"></a>

### 100. `Observation`

Nguồn: [src/runtime/shared_state.py:90](../src/runtime/shared_state.py#L90). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang một quan sát/frame và metadata đồng bộ để gắn hình ảnh với đúng thời điểm/nguồn.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
frame_id: int = 0
frame_pts: float = 0.0
timestamp: float = 0.0
annotated_frame: np.ndarray | None = None
raw_frame: np.ndarray | None = None
people_count: int = 0
car_count: int = 0
detection_count: int | None = 0
track_count: int = 0
is_fallback: bool = False
source_generation: int = 1
zone_enabled: bool = False
zone_mode: str = 'full_view'
car_count_label: str = 'VEHICLES IN VIEW'
vehicles_in_view: int = 0
vehicles_in_zone: int = 0
jpeg_bytes: bytes | None = None
telemetry: dict[str, Any] | None = None
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-101"></a>

### 101. `SharedRuntimeState`

Nguồn: [src/runtime/shared_state.py:113](../src/runtime/shared_state.py#L113). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Kho trạng thái dùng chung có đồng bộ thread giữa pipeline và HTTP: frame mới nhất, observation, telemetry, nguồn và trạng thái.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_annotated_frame`, `_buffer_age_ms`, `_camera_id`, `_camera_name`, `_capture_fps`, `_car_count`, `_current_obs`, `_decoded_fps`, `_decoded_frames_total`, `_detection_count`, `_device`, `_display_fps`, `_dropped_frames`, `_error_message`, `_event_count_today`, `_filtered_event_count`, `_frame_id`, `_frames_dropped_by_pacer`, `_gpu_name`, `_inference_fps`, `_input_size`, `_is_serving_fallback`, `_jitter_buffer_frames`, `_jitter_buffer_ms`, `_last_annotated_frame_time`, `_last_decoded_frame_age`, `_last_event`, `_last_event_time`, `_last_good_annotated_frame`, `_last_good_obs`, `_last_good_source_generation`, `_last_jpeg_encode_time`, `_last_jpeg_error`, `_last_jpeg_success`, `_last_mjpeg_publish_time`, `_last_paced_frame_age`, `_last_processed_frame_time`, `_last_published_frame_age`, `_last_saved_people_count`, `_latest_frame`, `_latest_jpeg_bytes`, `_latest_jpeg_frame_id`, `_lock`, `_mjpeg_clients_count`, `_mjpeg_connection_generation`, `_model_name`, `_paced_fps`, `_paced_frames_total`, `_people_count`, `_pipeline_latency_ms`, `_processing_fps`, `_publish_fps`, `_published_frames_total`, `_source_generation`, `_status`, `_stream_fps`, `_stream_health`, `_switching`, `_timestamp`, `_track_count`, `_vehicles_in_view`, `_vehicles_in_zone`, `_vram_mb`, `_yolo_latency_ms`, `_zone_enabled`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `status(self) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `is_idle(self) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `is_running(self) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `error_message(self) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `source_generation(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `mjpeg_clients_count(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `zone_enabled(self) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `set_zone_enabled(self, enabled: bool) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get_latest_jpeg_bytes(self, expected_frame_id: int \| None=None) → bytes \| None` | Return cached JPEG bytes encoded once per new frame. |
| `clear_frames(self, increment_generation: bool=True) → None` | Clear cached frames to avoid serving stale video on camera switch or idle. |
| `update(self, latest_frame: np.ndarray \| None=None, annotated_frame: np.ndarray \| None=None, people_count: int=0, car_count: int=0, detection_count: int \| None=0, track_count: int=0, stream_fps: float=0.0, processing_fps: float=0.0, yolo_latency_ms: float=0.0, pipeline_latency_ms: float=0.0, device: str='CPU', gpu_name: str='CPU', vram_mb: float=0.0, model_name: str='YOLO11s', input_size: str='640x640', capture_fps: float \| None=None, inference_fps: float \| None=None, display_fps: float \| None=None, dropped_frames: int \| None=None, buffer_age_ms: float \| None=None, camera_id: str \| None=None, camera_name: str \| None=None, last_event: str \| None=None, event_count_today: int \| None=None, last_saved_people_count: int \| None=None, decoded_frames_total: int \| None=None, decoded_fps: float \| None=None, paced_frames_total: int \| None=None, paced_fps: float \| None=None, published_frames_total: int \| None=None, publish_fps: float \| None=None, frames_dropped_by_pacer: int \| None=None, jitter_buffer_frames: int \| None=None, jitter_buffer_ms: float \| None=None, last_decoded_frame_age: float \| None=None, last_paced_frame_age: float \| None=None, zone_enabled: bool \| None=None, zone_mode: str \| None=None, car_count_label: str \| None=None, vehicles_in_view: int \| None=None, vehicles_in_zone: int \| None=None, jpeg_bytes: bytes \| None=None, frame_id: int \| None=None, frame_pts: float \| None=None) → None` | Atomically update state with the newest frame and metrics. |
| `set_camera(self, camera_id: str, camera_name: str) → None` | Update the active camera identifiers. |
| `record_event(self, event_desc: str, count_today: int \| None=None) → None` | Record an event description and update today's event count. |
| `record_filtered_event(self) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `record_saved_event(self, event_desc: str, timestamp: str, people_count: int, count_today: int) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `set_status(self, status: str, error_message: str='') → None` | Update the operational status of the pipeline. |
| `set_switching(self) → None` | Enter camera-switching mode — suppresses transient ERROR from AI pipeline. |
| `clear_switching(self) → None` | Exit camera-switching mode — allows ERROR status writes again. |
| `set_stream_health(self, health: dict[str, Any]) → None` | Publish runtime stream diagnostics for the telemetry endpoint. |
| `set_mjpeg_clients(self, count: int, generation: int) → None` | Track active MJPEG streaming client count and connection generation. |
| `record_mjpeg_publish(self, success: bool, error: str='') → None` | Record MJPEG frame publish event and latency diagnostics. |
| `update_telemetry(self, snapshot: TelemetrySnapshot) → None` | Update telemetry fields from a TelemetrySnapshot. |
| `get_annotated_frame(self) → tuple[int, np.ndarray \| None]` | Fetch the newest annotated frame and its frame ID. |
| `_stream_observation_locked(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get_frame_for_stream(self) → tuple[int, np.ndarray \| None, bool, int]` | Use the same observation selection as telemetry, including zero-count frames. |
| `get_raw_frame(self) → tuple[int, np.ndarray \| None]` | Fetch the newest raw frame and its frame ID. |
| `capture_camera_frame(self)` | Copy a fresh raw camera frame with its metadata under the same lock. |
| `get_frame_packet(self) → tuple[bytes, dict[str, Any]] \| None` | Read the JPEG and its publication-time metrics as one atomic packet. |
| `get_observation(self) → Observation \| None` | Fetch current synchronized observation snapshot. |
| `get_telemetry(self) → TelemetrySnapshot` | Fetch an immutable point-in-time telemetry snapshot with dynamic camera status. |
| `reset(self) → None` | Reset state when pipeline stops. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/events/event_manager.py`, `src/runtime/__init__.py`, `src/ui/video_stream.py`, `scripts/validate_plate_runtime.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/storage.py`

<a id="class-102"></a>

### 102. `StorageUploadTooLarge`

Nguồn: [src/storage.py:23](../src/storage.py#L23). Loại: **Exception / loại lỗi**.

**Dùng để làm gì / câu trả lời ngắn:** Loại lỗi riêng khi storage từ chối object vượt giới hạn kích thước.

**Kế thừa trực tiếp:** `OSError`

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/ui/web_server.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-103"></a>

### 103. `StorageBackend`

Nguồn: [src/storage.py:37](../src/storage.py#L37). Loại: **Interface / hợp đồng**.

**Dùng để làm gì / câu trả lời ngắn:** Interface lưu file: save/open/exists/delete/materialize; DB chỉ cần giữ object key, không phụ thuộc nhà cung cấp.

**Kế thừa trực tiếp:** `ABC`

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `save(self, key: str, source: BinaryIO) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `open(self, key: str) → BinaryIO` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `exists(self, key: str) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `delete(self, key: str) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `materialize(self, key: str) → Path` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `save_bytes(self, key: str, data: bytes) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-104"></a>

### 104. `LocalStorageBackend`

Nguồn: [src/storage.py:57](../src/storage.py#L57). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Đọc/ghi media trên filesystem local trong root cấu hình, có kiểm tra key/đường dẫn.

**Kế thừa trực tiếp:** `StorageBackend`

**Trạng thái được gán trong constructor:** `root`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, root: Path=PROJECT_ROOT)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `path(self, key: str) → Path` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `save(self, key: str, source: BinaryIO) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `open(self, key: str) → BinaryIO` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `exists(self, key: str) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `delete(self, key: str) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `materialize(self, key: str) → Path` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `scripts/migrate_media_to_storage.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-105"></a>

### 105. `ExternalStorageBackend`

Nguồn: [src/storage.py:105](../src/storage.py#L105). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Đọc/ghi media qua filesystem fsspec bên ngoài và materialize thành bản local dùng tạm.

**Kế thừa trực tiếp:** `StorageBackend`

**Trạng thái được gán trong constructor:** `cache`, `fs`, `prefix`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, url: str, options: dict, cache_dir: Path)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `_path(self, key: str) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `save(self, key: str, source: BinaryIO) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `open(self, key: str) → BinaryIO` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `exists(self, key: str) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `delete(self, key: str) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `materialize(self, key: str) → Path` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/persistence.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-106"></a>

### 106. `SupabaseStorageBackend`

Nguồn: [src/storage.py:149](../src/storage.py#L149). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Đọc/ghi media qua API Supabase Storage; tải object thành file local khi cần xử lý.

**Kế thừa trực tiếp:** `StorageBackend`

**Trạng thái được gán trong constructor:** `base`, `cache`, `headers`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, url: str, token: str, bucket: str, cache_dir: Path)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `_request(self, method, key, **kwargs)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `save(self, key: str, source: BinaryIO) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `open(self, key: str) → BinaryIO` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `exists(self, key: str) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `delete(self, key: str) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `materialize(self, key: str) → Path` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/persistence.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/stream/caltrans_service.py`

<a id="class-107"></a>

### 107. `NormalizedCamera`

Nguồn: [src/stream/caltrans_service.py:142](../src/stream/caltrans_service.py#L142). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Cấu trúc chuẩn hóa metadata camera từ catalog Caltrans để hệ thống sử dụng thống nhất.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
id: str
name: str
provider: str
source_type: str
stream_url: str
snapshot_url: str
update_frequency: int = 30
district: str = ''
county: str = ''
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `to_dict(self) → dict[str, Any]` | Chuyển dữ liệu sang dictionary. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-108"></a>

### 108. `CaltransCameraService`

Nguồn: [src/stream/caltrans_service.py:229](../src/stream/caltrans_service.py#L229). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Lấy catalog camera Caltrans, cache và hỗ trợ tìm camera theo ID; có cơ chế phục vụ dữ liệu dự phòng.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_cache_timestamp`, `_cached_cameras`, `_is_fetching`, `_last_error`, `_lock`, `cache_ttl`, `endpoint_url`, `timeout`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, endpoint_url: str=CALTRANS_QUERY_URL, cache_ttl: float=CACHE_TTL_SECONDS, timeout: float=6.0) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `is_cache_valid(self) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get_cameras(self, force_refresh: bool=False, query: str='') → list[dict[str, Any]]` | Retrieve Caltrans cameras, utilizing 10-minute cache with fallback. |
| `_background_fetch(self) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `_fetch_and_cache(self, force_refresh: bool=False) → list[NormalizedCamera]` | Fetch latest camera records from ArcGIS endpoint or fallback. |
| `get_camera_by_id(self, camera_id: str) → dict[str, Any] \| None` | Find a single camera by normalized ID. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/stream/camera_manager.py`

<a id="class-109"></a>

### 109. `CameraManager`

Nguồn: [src/stream/camera_manager.py:32](../src/stream/camera_manager.py#L32). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Chọn/đổi/dừng nguồn video và quản lý reader tương ứng; cung cấp frame và chỉ số sức khỏe cho pipeline.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_active_camera`, `_error_reason`, `_last_camera_started_at`, `_lock`, `_reader`, `_status`, `config_path`, `last_read_pts`, `last_read_sequence`, `last_source_wait_ms`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, config_path: Path \| str \| None=None) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `status(self) → str` | Current operational status of the camera. |
| `error_reason(self) → str` | Failure description if camera status is ERROR. |
| `stream_fps(self) → float` | Ingestion FPS from the active camera reader. |
| `capture_fps(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `dropped_frames(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `buffer_age_ms(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `decoded_frames_total(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `decoded_fps(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `paced_frames_total(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `paced_fps(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `frames_dropped_by_pacer(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `jitter_buffer_frames(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `jitter_buffer_ms(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `last_decoded_frame_age(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `last_paced_frame_age(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `stream_alive(self) → bool` | Whether the active stream is alive and publishing frames. |
| `last_frame_time(self) → float` | Timestamp of newest frame from active camera reader. |
| `frame_age_seconds(self) → float` | Seconds since newest frame was captured. |
| `finished(self) → bool` | Whether the active stream has reached EOF or stopped. |
| `stream_diagnostics(self) → dict[str, Any]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get_active_camera(self) → CameraInfo \| None` | Return the currently active CameraInfo metadata. |
| `start_camera(self, camera_id: str \| None=None) → CameraInfo` | Initialize and start the camera stream for the given camera ID. |
| `stop_camera(self) → None` | Stop the currently running camera stream cleanly. |
| `has_active_camera(self) → bool` | Check if an active camera source is configured and running. |
| `is_connection_ready(self, max_frame_age: float=5.0) → bool` | Check if active source satisfies connection criteria: - frames_received > 0 - frame_age_seconds <= max_frame_age - stream_alive is True |
| `switch_camera(self, camera_id: str) → CameraInfo` | Switch active camera to a new source dynamically. |
| `set_video_source(self, source_type: str, source: str, loop: bool=True, name: str \| None=None, headers: dict[str, str] \| None=None, video_source_id: str \| None=None, _registry_checked: bool=False) → CameraInfo` | Switch active stream dynamically to a Local MP4, Direct HLS, or YouTube source. |
| `get_current_source_info(self) → dict[str, Any]` | Return runtime details of the current video source. |
| `read(self, timeout: float=2.0) → np.ndarray \| None` | Read the latest frame from the active camera reader. |
| `read_with_meta(self, timeout: float=2.0) → tuple[np.ndarray \| None, int, float]` | Read latest frame with its monotonic sequence ID and capture PTS timestamp. |
| `_stop_reader_internal(self) → None` | Internal helper to stop reader without mutating external status. |
| `stop_camera(self) → None` | Public method to stop active camera reader and transition to STOPPED / IDLE. |
| `stop(self) → None` | Alias for stop_camera. |
| `get_active_reader(self) → Any` | Return the current active reader instance or None. |
| `active_camera_id(self) → str` | Return ID of currently active camera, or empty string. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/ui/video_stream.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/stream/direct_hls.py`

<a id="class-110"></a>

### 110. `HLSFrame`

Nguồn: [src/stream/direct_hls.py:29](../src/stream/direct_hls.py#L29). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang frame HLS và metadata thời gian/sequence để reader và pacer trao đổi dữ liệu.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
sequence: int
captured_at: float
capture_latency_ms: float
frame: np.ndarray
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-111"></a>

### 111. `DirectHLSReader`

Nguồn: [src/stream/direct_hls.py:97](../src/stream/direct_hls.py#L97). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Đọc HLS trực tiếp bằng FFmpeg, có worker giải mã, buffer/pacer và thống kê jitter/độ trễ để cấp frame ổn định.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_decoded_fps`, `_decoded_frames_total`, `_decoded_timestamps`, `_frames_dropped_by_pacer`, `_frames_received`, `_jitter_buffer`, `_last_decoded_time`, `_last_error_message`, `_last_ffmpeg_exit_code`, `_last_ffmpeg_pid`, `_last_ffmpeg_stderr`, `_last_frame_timestamp`, `_last_paced_time`, `_last_read_sequence`, `_latest`, `_lock`, `_max_jitter_age_seconds`, `_max_jitter_frames`, `_paced_fps`, `_paced_frames_total`, `_paced_timestamps`, `_pacer_thread`, `_process`, `_started_at`, `_stderr_thread`, `_stream_alive`, `_stream_fps`, `_target_cadence_seconds`, `_thread`, `_timestamps`, `abnormal_exit_count`, `clean_eof_count`, `dropped_frames`, `ffmpeg_start_count`, `finished`, `frame_size`, `headers`, `height`, `process_generation`, `reconnect_count`, `source_type`, `stderr_lines`, `stop_event`, `url`, `width`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, url: str='', width: int=1280, height: int=720, headers: dict[str, str] \| None=None, stream_url: str \| None=None) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `stream_fps(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `fps(self) → float` | Alias for stream_fps. |
| `capture_fps(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `decoded_frames_total(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `decoded_fps(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `paced_frames_total(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `paced_fps(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `frames_dropped_by_pacer(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `jitter_buffer_frames(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `jitter_buffer_ms(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `last_decoded_frame_age(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `last_paced_frame_age(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `buffer_age_ms(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `last_frame_time(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `frame_age_seconds(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `stream_alive(self) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `status(self) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `diagnostics(self) → dict[str, Any]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `start(self) → None` | Start background FFmpeg reader and pacer threads. |
| `stop(self) → None` | Cleanly terminate FFmpeg process and join worker and pacer threads. |
| `read(self, timeout: float=2.0) → np.ndarray \| None` | Return the newest paced BGR24 frame (Requirement B1-B3). |
| `_spawn_ffmpeg(self) → None` | Spawn FFmpeg process targeting direct HLS URL. |
| `_drain_stderr(self, pipe) → None` | Drain stderr to avoid buffer saturation deadlocks. |
| `_cleanup_process(self) → None` | Safe cancel-safe order: terminate -> wait -> kill -> close pipes. |
| `_worker_loop(self) → None` | Read stdout pipe frames continuously and append to bounded jitter buffer. |
| `_pacer_loop(self) → None` | Cadence-aware frame pacer loop (Requirement B2, B3). |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/stream/camera_manager.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/stream/preview_manager.py`

<a id="class-112"></a>

### 112. `PreviewManager`

Nguồn: [src/stream/preview_manager.py:30](../src/stream/preview_manager.py#L30). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Quản lý xem trước nguồn video nhẹ không chạy AI, lấy snapshot hoặc JPEG frame và dừng tài nguyên preview.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_active_url`, `_frame_count`, `_last_frame_time`, `_latest_jpeg`, `_lock`, `_process`, `_snapshot_cache`, `_stop_event`, `_thread`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `is_active(self) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get_active_url(self) → str \| None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `fetch_snapshot_image(self, snapshot_url: str, timeout: float=4.0) → bytes \| None` | Fetch remote snapshot JPEG with in-memory caching. |
| `start_preview(self, stream_url: str, width: int=640, height: int=360, headers: dict[str, str] \| None=None) → None` | Start lightweight preview FFmpeg process (scaled down, zero AI). |
| `stop_preview(self) → None` | Safely terminate preview FFmpeg and release all resources. |
| `_stop_preview_internal(self) → None` | Internal worker to kill preview subprocess and drain pipes. |
| `get_latest_frame_jpeg(self) → bytes \| None` | Return the newest preview JPEG frame. |
| `_preview_worker(self, proc: subprocess.Popen, width: int, height: int) → None` | Background worker reading raw preview frames and encoding to JPEG. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/stream/seattle_sdot_service.py`

<a id="class-113"></a>

### 113. `SeattleCamera`

Nguồn: [src/stream/seattle_sdot_service.py:80](../src/stream/seattle_sdot_service.py#L80). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang metadata camera từ Seattle SDOT và chuyển sang dictionary dùng cho API.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
id: str
name: str
provider: str
city: str
state: str
stream_name: str
stream_url: str
snapshot_url: str
latitude: float | None
longitude: float | None
source_type: str = 'direct_hls'
status: str = 'ACTV'
headers: dict[str, str] | None = None
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `to_dict(self) → dict[str, Any]` | Chuyển dữ liệu sang dictionary. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-114"></a>

### 114. `SeattleSDOTService`

Nguồn: [src/stream/seattle_sdot_service.py:198](../src/stream/seattle_sdot_service.py#L198). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Lấy/cache catalog Seattle SDOT, chuẩn bị URL stream và tìm camera theo stream name.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_cached_cameras`, `_cached_template`, `_catalog_timestamp`, `_is_fetching`, `_last_error`, `_lock`, `_template_timestamp`, `arcgis_url`, `catalog_ttl`, `template_ttl`, `template_url`, `timeout`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, arcgis_url: str=SEATTLE_ARCGIS_QUERY_URL, template_url: str=SEATTLE_WOWZA_TEMPLATE_URL, catalog_ttl: float=CATALOG_CACHE_TTL_SECONDS, template_ttl: float=TEMPLATE_CACHE_TTL_SECONDS, timeout: float=6.0) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `get_wowza_template(self, force_refresh: bool=False) → str` | Fetch current Wowza HLS template dynamically. |
| `_background_fetch(self, whitelist: set[str] \| None) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get_cameras(self, force_refresh: bool=False, query: str='', whitelist: set[str] \| None=SEATTLE_WHITELIST_CAMERAS) → list[dict[str, Any]]` | Retrieve normalized Seattle SDOT cameras from real upstream with resilient caching. |
| `_fetch_and_cache(self, force_refresh: bool=False, whitelist: set[str] \| None=SEATTLE_WHITELIST_CAMERAS) → list[SeattleCamera]` | Fetch latest Wowza template and ArcGIS features, parse and cache. |
| `get_camera_by_stream_name(self, stream_name: str) → dict[str, Any] \| None` | Find a single camera by STREAM_NAME. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/stream/thumbnail_service.py`

<a id="class-115"></a>

### 115. `ThumbnailService`

Nguồn: [src/stream/thumbnail_service.py:49](../src/stream/thumbnail_service.py#L49). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Lấy ảnh đại diện camera từ snapshot hoặc frame HLS, lưu cache và xóa cache khi cần.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_broken_snapshots`, `_cache`, `_lock`, `_max_cache_size`, `_semaphore`, `cache_ttl`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, cache_ttl: float=THUMBNAIL_CACHE_TTL, max_concurrency: int=MAX_CONCURRENT_EXTRACTIONS, cache_ttl_seconds: float \| None=None) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `get_thumbnail(self, camera_id: str, stream_url: str \| None=None, snapshot_url: str \| None=None, provider: str \| None=None) → tuple[bytes, str]` | Fetch or generate representative thumbnail image. |
| `_fetch_remote_snapshot(self, url: str, timeout: float=1.5) → bytes \| None` | Fetch remote snapshot with short timeout and validation. |
| `_extract_hls_frame(self, stream_url: str, provider: str \| None=None, timeout: float=5.0) → bytes \| None` | Extract a single frame from HLS stream using short-lived lightweight FFmpeg. |
| `_store_cache(self, key: str, data: bytes, content_type: str) → None` | Store thumbnail in bounded LRU cache. |
| `clear_cache(self) → None` | Clear all cached thumbnails. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/stream/video_source.py`

<a id="class-116"></a>

### 116. `VideoFrame`

Nguồn: [src/stream/video_source.py:50](../src/stream/video_source.py#L50). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang frame video và metadata phục vụ giao diện đọc frame của các reader.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
sequence: int
captured_at: float
frame: np.ndarray
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-117"></a>

### 117. `BaseVideoReader`

Nguồn: [src/stream/video_source.py:57](../src/stream/video_source.py#L57). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Định nghĩa giao diện vòng đời reader start/stop/read và các chỉ số trạng thái; reader file/VOD triển khai cùng giao diện.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `start(self) → None` | Khởi động xử lý/tài nguyên. |
| `stop(self) → None` | Dừng xử lý và dọn tài nguyên. |
| `read(self, timeout: float=1.0) → np.ndarray \| None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `status(self) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `error_reason(self) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `stream_fps(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `dropped_frames(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `buffer_age_ms(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `stream_alive(self) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `last_frame_time(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `frame_age_seconds(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `finished(self) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `diagnostics(self) → dict[str, Any]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-118"></a>

### 118. `LocalVideoReader`

Nguồn: [src/stream/video_source.py:137](../src/stream/video_source.py#L137). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Đọc file video local trong thread với pacing/buffer, cung cấp frame mới và quản lý EOF/vòng đời.

**Kế thừa trực tiếp:** `BaseVideoReader`

**Trạng thái được gán trong constructor:** `_dropped_frames`, `_error_reason`, `_finished`, `_first_frame_received`, `_frames_received`, `_last_frame_timestamp`, `_last_read_sequence`, `_latest`, `_lock`, `_read_errors`, `_status`, `_stop_event`, `_stream_alive`, `_stream_fps`, `_thread`, `_timestamps`, `abnormal_exit_count`, `clean_eof_count`, `ffmpeg_start_count`, `file_path`, `first_frame_timeout_count`, `height`, `last_error_message`, `last_error_type`, `loop`, `process_generation`, `reconnect_count`, `source_type`, `stale_frame_timeout_count`, `target_fps`, `total_frames`, `video_fps`, `width`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, file_path: str \| Path, loop: bool=True, target_fps: float \| None=None) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `start(self) → None` | Start reading thread. |
| `_capture_loop(self) → None` | Background worker reading frames at target FPS pace (timestamp-based). |
| `read(self, timeout: float=1.0) → np.ndarray \| None` | Read newest available frame. |
| `stop(self) → None` | Stop reader cleanly and wait for worker thread. |
| `status(self) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `error_reason(self) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `stream_fps(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `dropped_frames(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `buffer_age_ms(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `stream_alive(self) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `last_frame_time(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `frame_age_seconds(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `finished(self) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `diagnostics(self) → dict[str, Any]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/stream/camera_manager.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-119"></a>

### 119. `YouTubeVODReader`

Nguồn: [src/stream/video_source.py:447](../src/stream/video_source.py#L447). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Resolve URL YouTube VOD rồi giải mã bằng FFmpeg, điều tiết phát frame và xử lý EOF/loop/dừng subprocess.

**Kế thừa trực tiếp:** `BaseVideoReader`

**Trạng thái được gán trong constructor:** `_direct_url`, `_dropped_frames`, `_error_reason`, `_finished`, `_first_frame_received`, `_frames_received`, `_last_ffmpeg_exit_code`, `_last_ffmpeg_pid`, `_last_ffmpeg_stderr`, `_last_frame_timestamp`, `_last_read_sequence`, `_latest`, `_lock`, `_process`, `_process_started_at`, `_read_errors`, `_retries_used`, `_status`, `_stderr_lines`, `_stderr_thread`, `_stop_event`, `_stream_alive`, `_stream_fps`, `_thread`, `_timestamps`, `abnormal_exit_count`, `clean_eof_count`, `ffmpeg_start_count`, `first_frame_timeout_count`, `frame_size`, `height`, `last_error_message`, `last_error_type`, `last_ffmpeg_error_type`, `last_resolver_error_type`, `loop`, `max_retries`, `process_generation`, `reconnect_count`, `source_type`, `stale_frame_timeout_count`, `target_fps`, `width`, `youtube_url`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, youtube_url: str, loop: bool=False, width: int=1280, height: int=720, target_fps: float=30.0, max_retries: int=3) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `resolve_vod_url(url: str) → str` | Extract direct video stream URL using stream_resolver for YouTube VOD. |
| `_build_ffmpeg_cmd(ffmpeg_path: str, stream_url: str, width: int, height: int) → list[str]` | Build FFmpeg command for raw BGR24 decoding to stdout. |
| `_drain_stderr(self, pipe) → None` | Continuously drain FFmpeg stderr to prevent pipe buffer deadlocks. |
| `_cleanup_process(self) → None` | Safely terminate FFmpeg process according to cancel-safe cleanup order: 1. mark stopping / prevent race 2. terminate FFmpeg first 3. allow blocked pipe reads to unblock 4. wait with deadline 5. kill if still alive 6. close stdout / stderr 7. verify process is gone |
| `_spawn_ffmpeg(self, stream_url: str) → None` | Construct FFmpeg command, spawn subprocess, and start stderr drain thread. |
| `start(self) → None` | Resolve URL and start reader thread. |
| `_capture_loop(self) → None` | Capture frames from FFmpeg stdout pipe with pacing, clean EOF and abnormal exit handling. |
| `read(self, timeout: float=1.0) → np.ndarray \| None` | Read newest available frame. |
| `stop(self) → None` | Stop reader cleanly. |
| `status(self) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `error_reason(self) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `stream_fps(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `dropped_frames(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `buffer_age_ms(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `stream_alive(self) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `last_frame_time(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `frame_age_seconds(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `finished(self) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `diagnostics(self) → dict[str, Any]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/stream/camera_manager.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/stream/youtube_resolver.py`

<a id="class-120"></a>

### 120. `StreamCacheEntry`

Nguồn: [src/stream/youtube_resolver.py:38](../src/stream/youtube_resolver.py#L38). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang URL stream đã resolve cùng TTL, thời gian thành công/thất bại và trạng thái còn dùng được.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
video_id: str
stream_url: str
created_at: float = field(default_factory=time.time)
last_success: float = field(default_factory=time.time)
last_failure: float = 0.0
failure_count: int = 0
is_live: bool = True
ttl_seconds: float = 14400.0
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `is_expired(self) → bool` | Check if cache entry has exceeded its TTL. |
| `is_valid(self) → bool` | Valid if not expired and not marked dead by excessive failures. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-121"></a>

### 121. `ResolverMetrics`

Nguồn: [src/stream/youtube_resolver.py:191](../src/stream/youtube_resolver.py#L191). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang bộ đếm hoạt động resolve YouTube, cache hit/miss và các lỗi mạng để phục vụ telemetry.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
total_resolves: int = 0
cache_hits: int = 0
cache_misses: int = 0
direct_url_reconnects: int = 0
http_429_count: int = 0
http_403_count: int = 0
no_formats_count: int = 0
bot_challenge_count: int = 0
resolve_failures: int = 0
stream_restarts: int = 0
dedup_waits: int = 0
resolver_attempt_count: int = 0
resolver_success_count: int = 0
last_resolver_error_type: str = ''
last_resolver_error_message: str = ''
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `to_dict(self) → dict[str, Any]` | Chuyển dữ liệu sang dictionary. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-122"></a>

### 122. `SharedRateLimitPolicy`

Nguồn: [src/stream/youtube_resolver.py:230](../src/stream/youtube_resolver.py#L230). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Giữ trạng thái cooldown/backoff dùng chung khi truy cập YouTube bị giới hạn hoặc lỗi.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
http_429_count: int = 0
http_403_count: int = 0
last_429_timestamp: float = 0.0
cooldown_until: float = 0.0
current_backoff_level: int = 0
base_cooldown: float = 10.0
max_cooldown: float = 120.0
jitter: float = 5.0
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `is_in_cooldown(self) → bool` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `cooldown_remaining(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-123"></a>

### 123. `YouTubeStreamResolver`

Nguồn: [src/stream/youtube_resolver.py:480](../src/stream/youtube_resolver.py#L480). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Resolve link YouTube thành URL media trực tiếp bằng yt-dlp; cache, gộp request đồng thời và rate limit/backoff để không resolve mỗi frame.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_cache`, `_global_429_cooldown_until`, `_in_flight`, `_in_flight_results`, `_last_extraction_finished_at`, `_lock`, `_metrics`, `_policy`, `_resolve_semaphore`, `last_resolver_error_message`, `last_resolver_error_type`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `metrics(self) → ResolverMetrics` | Return snapshot of resolver metrics. |
| `policy(self) → SharedRateLimitPolicy` | Return shared 429 rate-limit policy. |
| `record_429(self, source: str='general', retry_after: float \| None=None, count: bool=True) → float` | Record an HTTP 429 event from yt-dlp or FFmpeg and calculate shared cooldown. |
| `record_403(self, url_or_id: str='', source: str='general') → None` | Record an HTTP 403 Forbidden event (e.g. expired googlevideo token) and invalidate cache. |
| `is_in_cooldown(self) → bool` | Check if global 429 cooldown is currently active. |
| `get_cooldown_remaining(self) → float` | Return remaining seconds of 429 cooldown, or 0.0 if not in cooldown. |
| `reset_backoff_level(self) → None` | Reset or decay backoff level after stable operation. |
| `reset_state(self) → None` | Reset internal cache, metrics, in-flight state, and shared rate-limit policy. |
| `reset_for_testing(self) → None` | Alias for reset_state() in test environments. |
| `get_metrics_dict(self) → dict[str, Any]` | Return metrics as a dictionary for telemetry APIs. |
| `get_cached_url(self, url_or_id: str) → str \| None` | Return active cached stream URL if valid, or None if expired/missing. |
| `invalidate_cache(self, url_or_id: str, reason: str='manual') → None` | Explicitly invalidate cached URL for the given video. |
| `record_success(self, url_or_id: str) → None` | Mark video stream working successfully, resetting failure counter. |
| `record_failure(self, url_or_id: str) → int` | Record a stream failure for the given video; return updated failure count. |
| `probe_stream_metadata(self, url_or_id: str) → dict[str, Any]` | Probe YouTube video/stream metadata without downloading. |
| `is_live_stream(self, url_or_id: str) → bool` | Determine whether a YouTube URL is a Live stream (True) or VOD (False). |
| `resolve_stream_url(self, url_or_id: str, is_vod: bool=False, force_refresh: bool=False) → str` | Resolve a playable direct stream URL for a YouTube video or stream. |
| `_execute_yt_dlp_extraction(self, original_url: str, video_id: str, is_vod: bool) → str` | Execute yt-dlp under global rate limiter with request spacing and backoff. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/stream/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/stream/youtube_stream.py`

<a id="class-124"></a>

### 124. `CapturedFrame`

Nguồn: [src/stream/youtube_stream.py:38](../src/stream/youtube_stream.py#L38). Loại: **Cấu trúc dữ liệu**.

**Dùng để làm gì / câu trả lời ngắn:** Mang frame camera cùng sequence, thời điểm capture và latency capture.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Các trường khai báo trực tiếp:**

```python
sequence: int
captured_at: float
capture_latency_ms: float
frame: np.ndarray
```

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** `src/stream/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-125"></a>

### 125. `CameraReader`

Nguồn: [src/stream/youtube_stream.py:180](../src/stream/youtube_stream.py#L180). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Đọc luồng video qua FFmpeg với frame mới nhất, reconnect và giám sát stale frame; là reader, khác CameraManager quản lý nguồn.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_consecutive_frame_failures`, `_direct_reconnect_attempts`, `_first_frame_received`, `_first_frame_timeout_count`, `_force_url_refresh`, `_frames_received`, `_generation_frame_timestamp`, `_health_thread`, `_last_ffmpeg_exit_code`, `_last_ffmpeg_pid`, `_last_ffmpeg_stderr`, `_last_frame_timestamp`, `_last_pipe_warning`, `_last_status`, `_last_ytdlp_call_at`, `_process_started_at`, `_read_errors`, `_recovery_started_at`, `_stale_frame_timeout_count`, `_stale_termination_requested`, `_status`, `_stderr_thread`, `_stream_alive`, `_stream_timestamps`, `_stream_url`, `_thread`, `_ytdlp_attempt`, `abnormal_exit_count`, `clean_eof_count`, `dropped_frames`, `error`, `error_reason`, `ffmpeg_start_count`, `finished`, `first_frame_timeout_seconds`, `frame_size`, `height`, `is_vod`, `last_capture_latency_ms`, `last_error_message`, `last_error_type`, `last_ffmpeg_error_type`, `last_frame_age_ms`, `last_read_sequence`, `last_resolver_error_type`, `latest`, `lock`, `process`, `process_generation`, `reconnect_attempts`, `reconnect_count`, `reconnect_delays`, `recovery_state`, `source_type`, `stale_frame_timeout_seconds`, `stderr_lines`, `stop_event`, `stream_fps`, `url`, `width`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, url: str, width: int=1280, height: int=720, is_vod: bool=False)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `first_frame_timeout_count(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `stale_frame_timeout_count(self) → int` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `last_frame_time(self) → float` | Timestamp of newest captured frame. |
| `frame_age_seconds(self) → float` | Elapsed seconds since newest frame was captured. |
| `stream_alive(self) → bool` | Health flag indicating stream process is active and publishing recent frames. |
| `status(self) → str` | Operational status based on frame age: - RUNNING: frame_age <= 5s - WARNING: 5s < frame_age <= 15s - ERROR: frame_age > 15s or process stopped |
| `_spawn_ffmpeg(self, stream_url: str) → None` | Construct FFmpeg command, spawn subprocess, and start stderr drain thread. |
| `start(self) → None` | Start capture asynchronously; startup failures use the same retry loop. |
| `_drain_stderr(self, pipe) → None` | Continuously drain FFmpeg stderr to prevent pipe buffer deadlocks. |
| `_cleanup_process(self) → None` | Safely terminate FFmpeg process according to cancel-safe cleanup order: 1. mark stopping / prevent race 2. terminate FFmpeg first 3. allow blocked pipe reads to unblock 4. wait with deadline 5. kill if still alive 6. close stdout / stderr 7. verify process is gone |
| `_reconnect(self) → bool` | Retry indefinitely with bounded delays until stopped or recovered. |
| `_get_stream_url_with_diagnostics(self, reason: str) → str` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `_read_loop(self) → None` | Reader thread boundary that preserves an unexpected traceback. |
| `_read_loop_impl(self) → None` | Read frame bytes from FFmpeg pipe continuously with auto-reconnection. |
| `_log_thread_error(self, name: str, exc: Exception) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `_health_loop(self) → None` | Periodic lifecycle/resource diagnostics; intentionally no recovery actions. |
| `diagnostics(self) → dict[str, Any]` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `buffer_age_ms(self) → float` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `read(self, timeout: float=1.0) → np.ndarray \| None` | Read the newest available frame. |
| `stop(self) → None` | Safely terminate FFmpeg subprocess and reader thread. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/stream/camera_manager.py`, `src/stream/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/tracker/bytetrack_tracker.py`

<a id="class-126"></a>

### 126. `PersonTracker`

Nguồn: [src/tracker/bytetrack_tracker.py:13](../src/tracker/bytetrack_tracker.py#L13). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Bọc ByteTrack cho người, gán ID qua nhiều frame và predict giữa các lần chạy detector.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `tracker`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, config: Any=None, frame_rate: float \| None=None)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `update(self, detections: Any) → sv.Detections` | Update tracker state with new detections. |
| `predict(self) → sv.Detections` | Smoothly advance active tracks with Kalman prediction between detector updates. |
| `reset(self) → None` | Reset internal tracker state. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/tracker/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-127"></a>

### 127. `CarTracker`

Nguồn: [src/tracker/bytetrack_tracker.py:94](../src/tracker/bytetrack_tracker.py#L94). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Bọc ByteTrack độc lập cho xe để tách trạng thái tracking người/xe; ID phải được hiểu trong đúng loại/nguồn.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_track_class_ids`, `tracker`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, config: Any=None, frame_rate: float \| None=None)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `update(self, detections: Any) → sv.Detections` | Update tracker state with new car detections. |
| `predict(self) → sv.Detections` | Smoothly advance active vehicle tracks with Kalman prediction between detector updates. |
| `reset(self) → None` | Reset internal car tracker state. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `scripts/validate_plate_runtime.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/ui/mjpeg_client.py`

<a id="class-128"></a>

### 128. `MJPEGReader`

Nguồn: [src/ui/mjpeg_client.py:59](../src/ui/mjpeg_client.py#L59). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Client đọc stream MJPEG, giữ frame mới nhất theo phiên, retry và dọn kết nối khi phiên không còn được sử dụng.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_error`, `_image`, `_last_poll`, `_lock`, `_status`, `_stop`, `_thread`, `endpoint`, `idle_timeout`, `retry_delay`, `timeout`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, endpoint, timeout=5.0, idle_timeout=30.0, retry_delay=1.0)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `poll(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `close(self)` | Đóng tài nguyên do instance quản lý. |
| `_active(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `_run(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/ui/dashboard.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/ui/video_stream.py`

<a id="class-129"></a>

### 129. `StreamRequestHandler`

Nguồn: [src/ui/video_stream.py:85](../src/ui/video_stream.py#L85). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** HTTP handler của server pipeline AI: route stream, telemetry, điều khiển camera, preview và một số thao tác target/sự kiện.

**Kế thừa trực tiếp:** `BaseHTTPRequestHandler`

**Các trường khai báo trực tiếp:**

```python
state: SharedRuntimeState = shared_state
camera_manager: CameraManager | None = None
protocol_version = 'HTTP/1.1'
```

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `setup(self) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `finish(self) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `log_message(self, format: str, *args: Any) → None` | Suppress standard HTTP server access logs to keep terminal clean. |
| `do_OPTIONS(self) → None` | Handle CORS pre-flight requests. |
| `do_GET(self) → None` | Route GET requests to video feed, telemetry, camera control, or events. |
| `do_POST(self) → None` | Route POST requests (switch_camera, set_video_source, select_source, stop_camera, register_target). |
| `do_DELETE(self) → None` | Route DELETE requests (remove target). |
| `handle_video_feed(self) → None` | Stream MJPEG multipart video feed using latest-frame semantics and stable pacing. |
| `_write_frame(self, frame_bytes: bytes) → None` | Write a single boundary JPEG frame to client socket. |
| `handle_frame_packet(self) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `handle_telemetry(self) → None` | Return realtime telemetry JSON. |
| `handle_status(self) → None` | Return operational pipeline status. |
| `handle_cameras(self) → None` | Return list of configured cameras. |
| `handle_switch_camera(self, query: dict[str, list[str]]) → None` | Handle camera switch request via GET query param (e.g. /switch_camera?id=camera_02). |
| `_execute_camera_switch(self, camera_id: str \| None) → None` | Execute dynamic camera switch on CameraManager. |
| `handle_video_source(self) → None` | Return runtime details of current video source. |
| `handle_zone_mode(self) → None` | Return counting zone mode status. |
| `_execute_set_zone_mode(self, data: dict[str, Any]) → None` | Toggle or set counting zone mode. |
| `handle_targets(self) → None` | Return list of currently registered targets. |
| `_execute_set_video_source(self, data: dict[str, Any]) → None` | Switch video source to Local MP4 or YouTube VOD. |
| `_execute_register_target(self, data: dict[str, Any]) → None` | Register target via JSON payload. |
| `handle_public_cameras(self, query: dict[str, list[str]]) → None` | Return public CCTV camera catalog for Caltrans and/or Seattle SDOT. |
| `handle_source_status(self) → None` | Return connection verification status for active video source. |
| `handle_camera_snapshot(self, query: dict[str, list[str]]) → None` | Proxy remote camera snapshot JPEG image. |
| `handle_camera_thumbnail(self, query: dict[str, list[str]]) → None` | Serve representative camera thumbnail via ThumbnailService. |
| `handle_preview_feed(self, query: dict[str, list[str]]) → None` | Stream lightweight preview MJPEG (zero AI). |
| `_execute_select_source(self, data: dict[str, Any]) → None` | Safely switch or start a selected camera source. |
| `_execute_stop_camera(self) → None` | Stop active camera and transition pipeline to IDLE state. |
| `_execute_stop_preview(self) → None` | Stop active preview. |
| `handle_events(self, query: dict[str, list[str]]) → None` | Return recent occupancy events from SQLite. |
| `handle_event_snapshot(self, query: dict[str, list[str]]) → None` | Serve JPEG image snapshot from data/events/. |
| `_send_json_response(self, data: dict[str, Any], code: int=200) → None` | Convenience helper to send JSON response. |
| `handle_root(self) → None` | Serve lightweight web monitoring preview. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-130"></a>

### 130. `MJPEGServer`

Nguồn: [src/ui/video_stream.py:1057](../src/ui/video_stream.py#L1057). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Quản lý vòng đời HTTP server có thread cho stream MJPEG và quản lý client stream đồng thời.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `_active_clients`, `_client_generation`, `_client_lock`, `_max_clients`, `_server`, `_thread`, `camera_manager`, `host`, `port`, `state`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, host: str='0.0.0.0', port: int=8000, state: SharedRuntimeState=shared_state, camera_manager: CameraManager \| None=None) → None` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `claim_video_client(self, handler: StreamRequestHandler) → int` | Allow concurrent streams without violent eviction (Requirement C5). |
| `release_video_client(self, handler: StreamRequestHandler, token: int \| None) → None` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `start(self) → None` | Start the MJPEG HTTP server in a daemon thread. |
| `stop(self) → None` | Cleanly shutdown the server. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `src/utils/fps.py`

<a id="class-131"></a>

### 131. `FPSMeter`

Nguồn: [src/utils/fps.py:7](../src/utils/fps.py#L7). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Đo FPS bằng cửa sổ trượt các timestamp frame; phục vụ HUD/log chứ không tạo thêm tốc độ xử lý.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `fps`, `last_update_time`, `timestamps`, `window_seconds`, `window_size`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, window_size: int=90, window_seconds: float=1.0)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `tick(self) → bool` | Record one processed frame timestamp and update sliding window FPS. |

**Các file có tham chiếu tên class (phân tích tĩnh):** `src/utils/__init__.py`.

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `scripts/colab_startup.py`

<a id="class-132"></a>

### 132. `Blocker`

Nguồn: [scripts/colab_startup.py:19](../scripts/colab_startup.py#L19). Loại: **Exception / loại lỗi**.

**Dùng để làm gì / câu trả lời ngắn:** Lỗi dừng quy trình startup Colab với thông điệp tĩnh không chứa credential.

**Kế thừa trực tiếp:** `RuntimeError`

**Method:** không khai báo method riêng. Với ORM/schema/dataclass, chức năng chính là mô tả dữ liệu; method có thể đến từ lớp cha hoặc được framework sinh.


**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-133"></a>

### 133. `Startup`

Nguồn: [scripts/colab_startup.py:115](../scripts/colab_startup.py#L115). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Điều phối các bước startup/validation Colab: kiểm tra môi trường, gọi CLI, khởi động và kiểm tra HTTP/runtime.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `completed`, `failed`, `report`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, runtime)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `git_commit()` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `cli(self, action, *, timeout=120, allow_failure=False, **options)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `run(self, number)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `cell_3(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `cell_4(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `cell_5(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `cell_6(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `cell_7(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `cell_8(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `cell_9(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `get(self, path, port=8501)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `cell_10(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `cell_11(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `cell_12(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `cell_13(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `scripts/diagnose_face_snapshot.py`

<a id="class-134"></a>

### 134. `SessionProbe`

Nguồn: [scripts/diagnose_face_snapshot.py:89](../scripts/diagnose_face_snapshot.py#L89). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Wrapper session trong script chẩn đoán khuôn mặt, ghi nhận thao tác suy luận để quan sát hành vi; không phải session DB nghiệp vụ.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `session`, `shapes`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, session)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `__getattr__(self, key)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |
| `run(self, outputs, inputs, *args, **kw)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `scripts/validate_e2e_postgres.py`

<a id="class-135"></a>

### 135. `DummyTracks`

Nguồn: [scripts/validate_e2e_postgres.py:29](../scripts/validate_e2e_postgres.py#L29). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Dữ liệu track giả trong script kiểm tra end-to-end PostgreSQL, thay detector thật để mô phỏng.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `class_id`, `confidence`, `tracker_id`, `xyxy`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, tids, boxes, class_ids, confs)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

<a id="class-136"></a>

### 136. `DummyPlateState`

Nguồn: [scripts/validate_e2e_postgres.py:38](../scripts/validate_e2e_postgres.py#L38). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Trạng thái biển số giả trong script kiểm tra end-to-end PostgreSQL.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `confidence`, `plate_crop`, `plate_text`, `status`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, text, status='CONFIRMED', conf=0.95)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `scripts/validate_plate_runtime.py`

<a id="class-137"></a>

### 137. `AuditManager`

Nguồn: [scripts/validate_plate_runtime.py:27](../scripts/validate_plate_runtime.py#L27). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Subclass VehiclePlateManager dùng trong script validation để quan sát việc áp dụng kết quả OCR.

**Kế thừa trực tiếp:** `VehiclePlateManager`

**Trạng thái được gán trong constructor:** `observations`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, reader)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `_apply_ocr_result(self, job, candidate)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.


## Module `scripts/verify_overlay_on_real_frame.py`

<a id="class-138"></a>

### 138. `MockDetections`

Nguồn: [scripts/verify_overlay_on_real_frame.py:32](../scripts/verify_overlay_on_real_frame.py#L32). Loại: **Class xử lý hoặc lớp nền; xem mục đích bên dưới**.

**Dùng để làm gì / câu trả lời ngắn:** Mô phỏng kết quả detections cho script xác minh overlay trên frame thật.

**Kế thừa trực tiếp:** Không khai báo lớp cha riêng.

**Trạng thái được gán trong constructor:** `class_id`, `confidence`, `tracker_id`, `xyxy`.

**Method khai báo trong class:**

| Method / chữ ký | Vai trò theo code hoặc docstring |
|---|---|
| `__init__(self, xyxy, tracker_id=None, confidence=None, class_id=None)` | Khởi tạo cấu hình, dependency và trạng thái của instance. |
| `__len__(self)` | Không có docstring riêng; xem thân method tại liên kết nguồn. Method được liệt kê để không bỏ sót khi ôn. |

**Các file có tham chiếu tên class (phân tích tĩnh):** Không tìm thấy tham chiếu tên trực tiếp ngoài module trong src/scripts..

Danh sách tham chiếu hỗ trợ tìm đường đọc; có thể gồm import hoặc class trùng tên, không khẳng định mọi file đều khởi tạo class. Singleton còn được dùng qua tên instance.

## Các điểm cần hiểu để không trả lời sai

- `Target` ORM khác `Target` trong gallery RAM; `VehiclePassage` ORM khác passage RAM và DTO.
- Detector tạo bbox/class/confidence; tracker gán ID theo thời gian; matcher so sánh với đối tượng tham chiếu.
- Face embedding và text embedding khác model, số chiều và mục đích; không dùng lẫn hai loại vector.
- `KnowledgeChunk` khai báo Vector(384), còn `TargetEmbedding` khai báo Vector(512). Provider embedding phải tương thích dữ liệu/schema. OpenAIEmbeddingService có default riêng 1536; factory truyền cấu hình, nên phải kiểm tra model thực sự trả đúng số chiều.
- Mock embedding/chat phục vụ kiểm thử; không chứng minh chất lượng tìm kiếm hoặc LLM thật. FastEmbed hiện fallback sang Mock khi lỗi.
- Class mang tên experimental không đồng nghĩa không được dùng: AdaptiveFacePipeline có thể lấy AdaFaceEmbedder.
- `AgentConversation` lưu metadata hội thoại; nội dung messages nằm trong checkpoint, không có cột messages ở registry này.
- `EventStorage` dùng SQLite là nhánh riêng; không thể kết luận toàn bộ dự án chỉ ghi vào DATT_DATABASE_URL.
- `ThresholdEpisodes.people` trong code hiện yêu cầu hơn 40 người liên tục ít nhất 180 giây; congestion dùng hơn 40 xe và chống lặp trong đợt.
- CLI API mode chạy web/API, không tự chạy pipeline CV; hiện AI_SERVER_URL được dùng cho đích pipeline từ xa trong API mode.
- Thay đổi tách model Colab và DB/backend local chưa hoàn tất; code pipeline vẫn có thao tác DB. Không trình bày kiến trúc mong muốn như kiến trúc đã triển khai.

## Các phần không dùng class nhưng vẫn phải ôn

- `app.py`: vòng xử lý frame và điều phối CV.
- `src/main.py`, `src/ops/cli.py`, `scripts/datt.py`: entry point/lệnh vận hành.
- `src/agent/graph.py`, `nodes.py`, `tools/`: graph, node và tool của agent.
- `src/agent/memory/checkpoint.py`: các hàm khởi tạo checkpointer, tạo thread config và xóa trạng thái.
- `src/agent/rag/chunking.py`: các hàm phát hiện tiêu đề, chia đoạn, gắn metadata.
- `src/agent/identity_resolution.py`: hàm xác định/giải quyết đối tượng được nhắc tới; không có class trực tiếp trong inventory.
- `src/ui/web_server.py` và các API/service nghiệp vụ: nhiều route/hàm, không phải mỗi module đều có class.
- Frontend React chủ yếu là function component và hook; không có class Python tương ứng cho mỗi màn hình.

## Phụ lục class trong test và file Python ngoài src/scripts

Các class sau chủ yếu là fixture/fake/helper kiểm thử. Mục đích có docstring được trích trực tiếp; nếu thiếu thì ghi rõ, không suy đoán là class nghiệp vụ.

| File | Class | Mô tả / method |
|---|---|---|
| [test_tracking_hybrit.py:103](../test_tracking_hybrit.py#L103) | `ZoneCounter` | Current frame-wide occupancy counter for active ByteTrack person tracks. Method: `__init__, update` |
| [test_tracking_hybrit.py:272](../test_tracking_hybrit.py#L272) | `CapturedFrame` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `không có` |
| [test_tracking_hybrit.py:279](../test_tracking_hybrit.py#L279) | `CameraReader` | Continuously reads FFmpeg and keeps only the newest frame. Method: `__init__, start, _read_loop, latest_frame, close` |
| [tests/test_agent_e2e.py:19](../tests/test_agent_e2e.py#L19) | `TestAgentEndToEnd` | Suite validating core business scenarios and grounding requirements. Method: `test_e2e_camera_operational_query, test_e2e_knowledge_rag_query, test_e2e_event_and_watchlist_queries, test_e2e_analytics_traffic_query, test_e2e_multi_turn_conversation_continuity, test_e2e_thread_isolation` |
| [tests/test_agent_face_history.py:228](../tests/test_agent_face_history.py#L228) | `FixedDateTime` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `now` |
| [tests/test_agent_face_history.py:311](../tests/test_agent_face_history.py#L311) | `FixtureGraph` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `invoke` |
| [tests/test_agent_llm.py:10](../tests/test_agent_llm.py#L10) | `FailingModel` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `__init__, invoke` |
| [tests/test_agent_natural_responses.py:139](../tests/test_agent_natural_responses.py#L139) | `CountingMock` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `invoke` |
| [tests/test_async_plate_scheduling.py:48](../tests/test_async_plate_scheduling.py#L48) | `MockDetections` | Mock detections for supervisor/tracker tracks. Method: `__init__, __len__` |
| [tests/test_async_plate_scheduling.py:61](../tests/test_async_plate_scheduling.py#L61) | `TestAsyncPlateScheduling` | Test suite for quality-based OCR job scheduling. Method: `test_quality_scoring_favors_large_over_small_vehicle, test_quality_scoring_sharpness_impact, test_queue_keeps_best_quality_job_when_newer_frame_is_worse, test_queue_replaces_job_when_newer_frame_is_better, test_queue_remains_bounded_under_load, test_track_29_e2e_retains_peak_frame_and_confirms_plate` |
| [tests/test_blockers_regression.py:45](../tests/test_blockers_regression.py#L45) | `TestBlockersRegression` | Regression test suite for Blockers 1 through 5. Method: `setUp, tearDown, test_1_vod_clean_eof_loop_false_stops_cleanly, test_2_vod_clean_eof_loop_true_controlled_restart, test_3_vod_ffmpeg_exit_code_nonzero_classified_as_error, test_4_vod_abnormal_exit_loop_true_consumes_retry_budget, test_5_blocked_stdout_cleanup_terminates_first, test_6_live_reconnect_previous_timestamp_does_not_kill_new_process, test_7_live_first_frame_timeout_recovers_unresponsive_process, test_8_stop_during_reconnect_sleep_no_spawn, test_9_stop_while_resolver_returning_no_post_stop_spawn, test_10_source_switch_during_recovery_clean_transition, test_11_ffmpeg_stderr_429_increments_shared_rate_limit, test_12_ffmpeg_429_ytdlp_not_immediately_called, test_13_resolver_and_ffmpeg_share_same_cooldown_state, test_14_cooldown_expires_single_recovery_attempt, test_15_http_403_handled_separately_from_429, test_16_no_duplicate_ffmpeg_processes_for_one_reader_generation, test_17_no_zombie_subprocess_after_stop, test_18_diagnostics_remain_compatible` |
| [tests/test_camera_selection.py:66](../tests/test_camera_selection.py#L66) | `TestCameraSelectionSystem` | Deterministic test suite for Camera Selection, Caltrans, and Direct HLS. Method: `setUp, test_app_opens_on_camera_selection_instead_of_dashboard, test_caltrans_camera_catalog_parsing, test_only_cameras_with_streamingVideoURL_are_returned, test_camera_catalog_cache, test_direct_hls_does_not_call_ytdlp, test_selecting_camera_starts_direct_hls_reader, test_dashboard_opens_only_after_first_frame, test_failed_camera_remains_on_selection_or_error_screen, test_changing_camera_stops_previous_ffmpeg, test_returning_to_camera_selection_cleans_resources, test_preview_cleanup_and_safety, test_existing_local_video_still_works, test_existing_youtube_source_still_works` |
| [tests/test_checking_hang_and_best_face_fix.py:20](../tests/test_checking_hang_and_best_face_fix.py#L20) | `TestCheckingHangAndBestFaceFix` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `setUp, evaluate, test_frontality_calculation, test_eligible_face_progresses_to_unknown_after_three_evaluations, test_invalid_embedding_waits_without_counting_an_attempt, test_large_face_is_rejected_even_with_high_confidence, test_rejected_frames_do_not_advance_unknown_counter, test_similarity_above_threshold_matches_with_one_candidate, test_rejected_candidate_preserves_best_metadata, test_small_quality_improvement_updates_best_and_fuses_both, test_registered_threshold_is_preserved, test_worse_valid_frame_preserves_best_but_participates_in_fusion, test_stale_track_does_not_transfer_match_to_reused_id, test_per_frame_face_diagnostics_do_not_spam_info` |
| [tests/test_cli.py:216](../tests/test_cli.py#L216) | `LaunchReached` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `không có` |
| [tests/test_colab_runtime_cell.py:28](../tests/test_colab_runtime_cell.py#L28) | `Socket` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `__enter__, __exit__, settimeout, connect_ex` |
| [tests/test_colab_startup.py:75](../tests/test_colab_startup.py#L75) | `Session` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `__enter__, __exit__, get, post` |
| [tests/test_db.py:25](../tests/test_db.py#L25) | `DatabaseTests` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `setUp, camera, graph, test_camera_target_crud, test_zone_crud_and_foreign_key, test_zone_migration_preserves_existing_data, test_event_insert_query_and_utc_json_roundtrip, test_exception_rolls_back_whole_event_graph, test_fk_failure_rolls_back_and_next_transaction_works, test_delete_policies, test_naive_time_rejected, test_query_pagination_and_validation, test_migration_indexes_schema_drift_and_roundtrip, test_postgresql_migration_sql` |
| [tests/test_e2e_backend_database.py:69](../tests/test_e2e_backend_database.py#L69) | `TestEndToEndBackendDatabase` | End-to-end integration tests for backend, database, and computer vision pipelines. Method: `setup_and_teardown, test_01_video_library_e2e_flow, test_02_target_person_e2e_flow, test_03_motorcycle_plate_ocr_independent_of_person, test_04_vehicle_event_persistence_and_traceability, test_05_face_event_persistence_and_traceability, test_06_event_query_apis` |
| [tests/test_e2e_backend_database.py:266](../tests/test_e2e_backend_database.py#L266) | `MockMotorcycleTracks` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `không có` |
| [tests/test_e2e_target_tracking.py:55](../tests/test_e2e_target_tracking.py#L55) | `TestEndToEndTargetTracking` | End-to-End test suite for Target Tracking, Highlight, and Runtime Source Switch. Method: `setUp, tearDown, test_e2e_flow_and_runtime_switch` |
| [tests/test_error_classification_regression.py:43](../tests/test_error_classification_regression.py#L43) | `TestErrorClassificationRegression` | Deterministic regression tests for YouTube error classification and reconnect behavior. Method: `setUp, tearDown, test_1_no_video_formats_found_classification, test_2_http_429_too_many_requests, test_3_http_403_forbidden, test_4_bot_challenge_distinct_from_429, test_5_generic_download_error, test_6_ffmpeg_nonzero_exit_without_http_status, test_7_ffmpeg_stderr_explicit_429, test_8_no_formats_during_camera_reconnect, test_9_recovery_after_temporary_no_formats, test_10_dead_ffmpeg_pid_cleared_from_diagnostics` |
| [tests/test_face_diagnostic_snapshot.py:17](../tests/test_face_diagnostic_snapshot.py#L17) | `FakeEmbedder` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `detect_faces_in_roi` |
| [tests/test_face_diagnostic_snapshot.py:22](../tests/test_face_diagnostic_snapshot.py#L22) | `SnapshotTests` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `test_exact_frame_native_coordinates_and_one_shot, test_no_request_does_nothing, test_missing_track_keeps_request_pending` |
| [tests/test_face_registration_fix.py:41](../tests/test_face_registration_fix.py#L41) | `TestFaceRegistrationFix` | Test suite ensuring target face registration and matching behave correctly. Method: `setUp, tearDown, _create_synthetic_face_portrait, test_exif_orientation_decode, test_register_target_exif_portrait_multipart, test_register_target_blank_image_rejected, test_register_target_unsupported_extension_rejected, test_live_target_matching_end_to_end` |
| [tests/test_live_face_detection_fix.py:24](../tests/test_live_face_detection_fix.py#L24) | `MockDetections` | Mock detections for Tracker. Method: `__init__` |
| [tests/test_live_face_detection_fix.py:32](../tests/test_live_face_detection_fix.py#L32) | `TestLiveFaceDetectionFix` | Test suite covering the 7 focused requirements for live face detection. Method: `setUpClass, setUp, tearDown, test_point_3_and_6_adaptive_upscale_and_normal_illum_independence, test_point_3_adaptive_upscale_159x193, test_point_1_and_2_diagnostics_and_bounded_debug_samples, test_production_does_not_retry_with_a_second_roi, test_real_face_outside_candidate_width_is_rejected` |
| [tests/test_live_scenarios_and_counter_sync.py:48](../tests/test_live_scenarios_and_counter_sync.py#L48) | `TestLiveFaceRecAndCounterSync` | Test suite for live face recognition scenarios and telemetry-video synchronization. Method: `setUpClass, setUp, _require_cuda_face_runtime, tearDown, _compose_frame_with_face, test_scenario_1_normal_lighting_clear_face, test_scenario_2_backlit_face_enhancement, test_scenario_3_fast_passing_person_cadence, test_scenario_4_approaching_person_quality_progression, test_scenario_5_stranger_unknown_progression, test_scenario_6_counter_sync_and_fallback_consistency, test_scenario_7_port_8501_live_endpoints` |
| [tests/test_media_persistence.py:62](../tests/test_media_persistence.py#L62) | `TestMediaPersistence` | Test suite verifying persistence of uploaded MP4s and target registration images. Method: `setUp, tearDown, test_01_upload_mp4_persistence_and_db_record, test_02_target_registration_persistence_and_embeddings, test_03_event_flow_links_video_source_id` |
| [tests/test_media_persistence.py:246](../tests/test_media_persistence.py#L246) | `MockTracks` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `không có` |
| [tests/test_pacing_and_stability.py:21](../tests/test_pacing_and_stability.py#L21) | `TestPacingAndStability` | Test suite for burst pacing and black-screen prevention mechanisms. Method: `test_shared_state_source_generation_and_fallback, test_status_placeholder_creation, test_concurrent_mjpeg_clients, test_bounded_jitter_buffer_and_drop_policy, test_telemetry_snapshot_contains_pacing_and_black_screen_fields` |
| [tests/test_pacing_and_stability.py:88](../tests/test_pacing_and_stability.py#L88) | `DummyHandler` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `__init__` |
| [tests/test_plate_ocr.py:40](../tests/test_plate_ocr.py#L40) | `TestPlateOCR` | Test suite covering decoupled license plate OCR detection, tracking, and rendering. Method: `setUp, tearDown, test_text_cleaning_and_validation, test_plate_extraction_on_synthetic_vehicle, test_two_tier_plate_grouping_29A_12345, test_two_tier_plate_grouping_30G_56789, test_cadence_control_does_not_ocr_every_frame, test_best_plate_retention_per_track, test_debug_sample_saving, test_frame_renderer_overlay_with_plate, test_manager_ttl_expiration_and_reset, test_real_easyocr_end_to_end_on_vehicle, test_real_easyocr_on_two_tier_plate_29A_12345, test_real_easyocr_on_two_tier_plate_30G_56789, test_small_plate_adaptation, test_tilted_plate_deskew, test_dark_plate_gamma_enhancement, test_glare_plate_enhancement, test_one_line_plate_preprocessing_and_ocr, test_vietnamese_two_tier_plate_preprocessing_and_ocr, test_multi_variant_ocr_selection, test_plate_preprocess_logging_and_debug_files, test_easyocr_gpu_initialization_when_cuda_available, test_easyocr_cpu_fallback_when_cuda_unavailable, test_easyocr_cpu_fallback_when_gpu_init_fails, test_easyocr_reader_initialized_only_once` |
| [tests/test_plate_ocr.py:562](../tests/test_plate_ocr.py#L562) | `ListHandler` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `emit` |
| [tests/test_runtime_manager.py:24](../tests/test_runtime_manager.py#L24) | `TestRuntimeManager` | Test suite for unified RuntimeManager. Method: `test_cli_argument_parsing, test_port_availability_detection, test_graceful_shutdown_cleans_threads` |
| [tests/test_runtime_stabilization.py:70](../tests/test_runtime_stabilization.py#L70) | `TestRuntimeStabilization` | Regression test suite for runtime stabilization, camera switching, uploads, and tracking. Method: `setUp, test_01_shared_state_status_property_and_accessors, test_02_stop_camera_transitions_to_idle_without_crash, test_03_camera_manager_single_reader_invariant, test_04_repeated_10_camera_switches_in_one_process, test_05_changing_direct_hls_camera_stops_old_ffmpeg, test_06_upload_video_valid_mp4, test_07_upload_video_invalid_extension_rejected, test_08_upload_video_empty_file_rejected, test_09_thumbnail_service_snapshot_success, test_10_thumbnail_service_snapshot_failure_falls_back_to_hls, test_11_thumbnail_service_complete_failure_returns_svg_placeholder, test_12_config_target_classes_contains_person_and_car, test_13_independent_trackers_maintain_separate_identities, test_14_counters_track_people_and_cars_separately, test_15_telemetry_includes_both_people_and_car_count, test_16_frame_renderer_renders_distinguishable_labels, test_17_stream_fps_bounded_window_prevents_burst_spike` |
| [tests/test_seattle_sdot.py:123](../tests/test_seattle_sdot.py#L123) | `TestSeattleSDOTIntegration` | Deterministic unit and integration tests for Seattle SDOT Live CCTV. Method: `test_1_seattle_arcgis_parsing, test_2_stream_name_to_stream_conversion, test_3_wowza_template_replacement, test_4_no_hardcoded_streamlock_hostname, test_5_missing_stream_name_ignored, test_6_whitelist_filters_correctly, test_7_seattle_camera_source_type_is_direct_hls, test_8_seattle_selection_starts_direct_hls_reader, test_9_seattle_direct_hls_never_invokes_ytdlp, test_10_failed_seattle_stream_does_not_enter_dashboard, test_11_switching_seattle_to_seattle_cleans_old_ffmpeg, test_12_switching_caltrans_to_seattle, test_13_switching_seattle_to_local, test_14_existing_caltrans_tests_still_pass, test_15_existing_youtube_source_still_works, test_16_existing_local_mp4_still_works` |
| [tests/test_supabase_storage.py:19](../tests/test_supabase_storage.py#L19) | `Response` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `__init__, close, __enter__, __exit__, iter_content` |
| [tests/test_target_api.py:33](../tests/test_target_api.py#L33) | `TestTargetAPI` | Test suite for Target & Video Source FastAPI endpoints. Method: `setUp, tearDown, test_get_targets_empty, test_register_target_json_color_only, test_register_target_missing_name_fails, test_register_target_missing_features_fails, test_register_target_multipart_form, test_delete_target, test_set_video_source_api_validation, test_get_video_source_api` |
| [tests/test_target_matcher.py:37](../tests/test_target_matcher.py#L37) | `MockDetections` | Mock for supervision.Detections. Method: `__init__` |
| [tests/test_target_matcher.py:45](../tests/test_target_matcher.py#L45) | `TestTargetMatcher` | Test suite for TargetManager, TargetMatcher, and ColorExtractor. Method: `setUp, test_register_target_color_only, test_register_target_face_only, test_register_target_face_and_color, test_register_target_no_attributes_rejected, test_clothing_color_extraction_hsv, test_matcher_robust_to_invalid_crops, test_target_association_with_bytetrack_id, test_track_association_cleanup_on_ttl, test_combined_rule_no_false_match_when_face_missing, test_cosine_similarity_edge_cases` |
| [tests/test_ui_video.py:12](../tests/test_ui_video.py#L12) | `Headers` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `get` |
| [tests/test_ui_video.py:15](../tests/test_ui_video.py#L15) | `Response` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `không có` |
| [tests/test_vehicle_classes_and_truck_detection.py:25](../tests/test_vehicle_classes_and_truck_detection.py#L25) | `MockDetections` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `__init__, __len__` |
| [tests/test_vehicle_classes_and_truck_detection.py:36](../tests/test_vehicle_classes_and_truck_detection.py#L36) | `TestVehicleClassesAndTruckDetection` | Test suite for multi-vehicle class expansion and truck detection. Method: `test_1_config_target_classes_include_all_vehicle_types, test_2_detector_passes_all_vehicle_classes_to_yolo_model, test_3_bytetrack_preserves_truck_and_vehicle_subtypes, test_4_vehicle_plate_manager_logs_vehicle_det_and_evaluates_truck, test_5_motorcycle_eligible_for_plate_ocr, test_6_car_counter_counts_all_active_vehicles, test_7_frame_renderer_renders_truck_label` |
| [tests/test_vehicle_event.py:32](../tests/test_vehicle_event.py#L32) | `TestVehicleColorExtraction` | Unit tests for HSV lightweight vehicle color extraction. Method: `test_color_names_specification, test_white_vehicle_crop, test_black_vehicle_crop, test_gray_silver_vehicle_crop, test_red_vehicle_crop, test_blue_vehicle_crop, test_green_vehicle_crop, test_yellow_vehicle_crop, test_invalid_or_empty_crop` |
| [tests/test_vehicle_event.py:91](../tests/test_vehicle_event.py#L91) | `TestVehicleEventPersistence` | Integration tests for VehicleEvent and PlateEvent PostgreSQL persistence. Method: `setup_method, teardown_method, test_single_vehicle_event_per_track_and_plate_linkage, test_event_manager_e2e_track_lifecycle_vehicle_event` |
| [tests/test_vehicle_tracking_overlay_format.py:35](../tests/test_vehicle_tracking_overlay_format.py#L35) | `MockDetections` | Mock supervision.Detections container for testing. Method: `__init__, __len__` |
| [tests/test_vehicle_tracking_overlay_format.py:54](../tests/test_vehicle_tracking_overlay_format.py#L54) | `TestVehicleTrackingOverlayFormat` | Test suite for vehicle tracking overlay format and presentation rules. Method: `test_format_plate_display_standard_vietnamese_plates, test_get_vehicle_track_label_confirmed_car_motorcycle_truck, test_unconfirmed_checking_plate_not_displayed, test_unconfirmed_searching_plate_not_displayed, test_zone_prefix_preservation, test_render_frame_with_confirmed_plate_draws_label_and_bbox` |
| [tests/test_video_sources.py:49](../tests/test_video_sources.py#L49) | `TestVideoSources` | Test suite for Local MP4 and YouTube VOD video sources. Method: `setUp, tearDown, test_local_mp4_opens_and_reads, test_local_mp4_loop_behavior, test_invalid_local_path, test_youtube_vod_resolve_and_read, test_invalid_youtube_vod_url, test_runtime_video_source_switch_and_release` |
| [tests/test_watchlist_ui_and_connection_regression.py:33](../tests/test_watchlist_ui_and_connection_regression.py#L33) | `TestWatchlistUIAndConnectionRegression` | Không có docstring riêng; xem nơi khai báo và test bao quanh để biết kịch bản mô phỏng. Method: `setUp, tearDown, test_camera_offline_does_not_affect_watchlist_api, test_target_list_query_defers_embeddings_and_includes_metadata, test_get_target_detail_endpoint_success_and_safety, test_get_target_detail_not_found, test_toggle_target_selection_in_modal, test_vehicle_detail_and_detections_endpoints` |
| [tests/test_web_server.py:27](../tests/test_web_server.py#L27) | `TestWebServer` | Test suite for DATT FastAPI monitoring web server. Method: `setUp, test_root_returns_index_html, test_static_assets_load, test_favicon_ico, test_static_favicon_ico, test_telemetry_offline_handling, test_telemetry_online_handling, test_shared_state_camera_status_lifecycle, test_shared_state_explicit_error_and_recovery, test_events_endpoint_returns_latest_five_normalized, test_camera_list_endpoint, test_switch_camera_missing_param_returns_400, test_switch_camera_success, test_event_snapshot_missing_params` |
| [tests/test_youtube_resolver.py:40](../tests/test_youtube_resolver.py#L40) | `TestYouTubeResolver` | Test suite for YouTubeStreamResolver and smart reconnection mechanisms. Method: `setUp, test_url_and_id_extraction, test_stream_cache_hit_and_miss, test_single_flight_deduplication, test_global_rate_limiter_concurrency, test_http_429_exponential_backoff, test_request_spacing_enforced, test_smart_reconnect_tries_existing_direct_url_first, test_direct_url_exhausted_calls_fresh_resolve, test_frame_read_drop_below_threshold_does_not_kill_stream, test_no_process_or_thread_leak_on_repeated_reconnect` |
| [tests/test_youtube_stream.py:29](../tests/test_youtube_stream.py#L29) | `TestYouTubeStream` | Test suite for YouTube stream format selection, FFmpeg command generation, and retries. Method: `test_mock_ytdlp_selects_video_format, test_invalid_ytdlp_response_raises_runtime_error, test_ffmpeg_command_generation, test_sliding_window_fps_meter, test_camera_reader_stale_frame_status, test_camera_reader_auto_recovery_reconnect, test_camera_reader_zombie_prevention` |
| [tests/test_youtube_vod_ffmpeg.py:53](../tests/test_youtube_vod_ffmpeg.py#L53) | `FakeStdoutPipe` | Simulates FFmpeg stdout pipe generating raw BGR24 frames. Method: `__init__, read, readline, close` |
| [tests/test_youtube_vod_ffmpeg.py:76](../tests/test_youtube_vod_ffmpeg.py#L76) | `FakePopen` | Simulates FFmpeg subprocess.Popen. Method: `__init__, poll, terminate, kill, wait` |
| [tests/test_youtube_vod_ffmpeg.py:106](../tests/test_youtube_vod_ffmpeg.py#L106) | `TestYouTubeVODRegression` | Regression test suite for YouTube VOD FFmpeg ingestion & diagnostics. Method: `setUp, tearDown, test_1_youtube_vod_never_calls_cv2_videocapture, test_2_mock_ytdlp_spawns_ffmpeg_and_reads_frame, test_3_diagnostics_no_keyerror_in_camera_manager, test_4_and_5_source_switching_local_vod_local, test_6_stop_cleanly_terminates_ffmpeg_process, test_7_vod_eof_terminates_cleanly_when_loop_false, test_8_ytdlp_not_called_per_frame, test_9_no_multiple_ffmpeg_processes_spawned, test_10_existing_youtube_live_stream_remains_functional` |
| [tests/test_youtube_vod_workflow.py:33](../tests/test_youtube_vod_workflow.py#L33) | `TestYouTubeVODWorkflow` | Test suite covering YouTube Live vs VOD separation, EOF handling, and anti-bot challenge. Method: `setUp, tearDown, test_live_vs_vod_differentiation, test_camera_manager_routes_vod_to_youtube_vod_reader, test_camera_manager_routes_live_to_camera_reader, test_vod_passes_is_vod_true_to_resolver, test_vod_clean_eof_transitions_to_video_finished, test_camera_reader_vod_clean_eof_stops_without_reconnect, test_camera_manager_surfaces_video_finished, test_bot_challenge_in_resolver_raises_auth_anti_bot, test_bot_challenge_stops_reconnect_immediately, test_bot_challenge_in_vod_reader_start_aborts_retries, test_build_ydl_opts_unified_cookie_and_js_runtime, test_build_ydl_opts_raises_if_cookie_path_not_found, test_target_url_3zTBsryvZjQ_probe_and_camera_manager_selection` |

Kiểm kê: 138 class src/scripts; 57 khai báo class bổ sung trong tests và file Python ở root. Không bao gồm dependencies, cache, notebook hoặc file backup.

## Cách học từng class

1. Đọc câu mục đích trong tài liệu này.
2. Mở constructor để thấy dependency và trạng thái.
3. Chọn một method public chính, theo đầu vào → xử lý → đầu ra.
4. Tìm call site bằng tên class hoặc tên singleton để biết ai sử dụng kết quả.
5. Đọc test liên quan để hiểu trường hợp thành công/thất bại.
6. Trả lời bằng một ví dụ cụ thể trong hệ thống, không chỉ diễn giải tên class.
