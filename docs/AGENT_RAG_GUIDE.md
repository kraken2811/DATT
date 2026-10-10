# HƯỚNG DẪN AI AGENT & RAG DATT

**DATT — AI Operations Agent, Conversation, Authentication & Retrieval-Augmented Generation**

Tài liệu này là tài liệu chuẩn cho phân hệ **DATT AI Assistant** trên nhánh `dev`. Nội dung được tổ chức cho ba nhóm: người vận hành, quản trị viên triển khai và kỹ sư phát triển.

> Phạm vi: giao diện `/agent`, API `/api/agent/*`, LangGraph Agent, tool nghiệp vụ, quản lý hội thoại, xác thực phiên, LLM provider, RAG/Knowledge Base và xử lý sự cố liên quan.

---

## 1. Tổng quan

DATT AI Assistant là lớp trợ lý vận hành đặt trên dữ liệu và API nghiệp vụ của DATT. Agent không thay thế pipeline thị giác máy tính; nó cung cấp một giao diện ngôn ngữ tự nhiên để người dùng tra cứu và tổng hợp thông tin từ camera, sự kiện, watchlist, cảnh báo, thống kê, báo cáo và tài liệu vận hành.

Luồng thực thi chính dùng **LangGraph StateGraph**:

```text
START
  ↓
agent_node
  ↓
should_continue
  ├── cần dữ liệu/tool → tool_node → agent_node
  └── đủ thông tin     → END
```

Mỗi lượt chat trả về ba nhóm dữ liệu chính:

- `reply`: câu trả lời cuối cùng;
- `tools_called`: danh sách tool được Agent sử dụng trong lượt hiện tại;
- `sources`: nguồn RAG khi Agent sử dụng `get_knowledge`.

---

## 2. Sử dụng AI Assistant trên giao diện Web

### 2.1. Mở AI Assistant

Trên giao diện React của DATT, chọn **DATT AI Assistant** hoặc truy cập route:

```text
/agent
```

Khi tải trang, giao diện sẽ:

1. lấy danh sách hội thoại của người dùng hiện tại;
2. khôi phục hội thoại đang chọn nếu có;
3. lưu `thread_id` hiện tại trong `localStorage` để tiếp tục sau khi reload;
4. hiển thị trạng thái kết nối Agent API độc lập với trạng thái camera.

### 2.2. Các câu hỏi mẫu

Giao diện cung cấp các quick prompt điển hình:

- `Kiểm tra trạng thái hoạt động của camera_01`
- `Cho tôi xem thống kê phân loại phương tiện và lưu lượng trong 24 giờ qua`
- `Tra cứu danh sách theo dõi biển số xe và đối tượng khuôn mặt`
- `Theo tài liệu hướng dẫn, cách khắc phục khi camera bị offline hoặc mất kết nối?`

Người dùng có thể hỏi tự nhiên hơn, ví dụ:

- camera nào đang offline;
- sự kiện gần nhất của một camera;
- tìm sự kiện trong một khoảng thời gian;
- tra cứu đối tượng/biển số trong watchlist;
- thống kê sự kiện hoặc lưu lượng;
- kiểm tra cảnh báo và trạng thái notification;
- tạo báo cáo vận hành;
- hỏi cách xử lý lỗi dựa trên tài liệu hệ thống.

### 2.3. Quản lý hội thoại

Agent hỗ trợ nhiều hội thoại độc lập.

- **Tạo hội thoại mới:** tạo thread mới và giữ nguyên các thread cũ.
- **Chuyển hội thoại:** chọn một cuộc trò chuyện trong danh sách bên trái.
- **Đổi tên:** sửa title của conversation.
- **Xóa:** xóa registry và checkpoint của đúng conversation được chọn, sau bước xác nhận.
- **Tìm hội thoại:** giao diện lọc theo title hoặc `thread_id`.

> Tạo cuộc trò chuyện mới **không được** triển khai bằng cách xóa conversation hiện tại. API chuẩn là `POST /api/agent/conversations`.

### 2.4. Đọc kết quả Agent

Một câu trả lời có thể bao gồm:

- nội dung trả lời;
- danh sách tool đã được gọi;
- nguồn tài liệu khi dùng RAG;
- thông báo lỗi nếu Agent API, history service hoặc LLM provider không khả dụng.

Nếu Agent API vẫn kết nối được nhưng LLM provider lỗi, giao diện có thể báo lỗi mô hình trong phần chat. Trạng thái này khác với việc không kết nối được Agent API.

---

## 3. Các tool nghiệp vụ của Agent

Danh sách tool đăng ký chính thức trong `ALL_AGENT_TOOLS`:

| Tool | Mục đích |
|---|---|
| `get_camera` | Lấy thông tin một camera cụ thể |
| `get_camera_status` | Kiểm tra trạng thái camera |
| `get_event` | Lấy chi tiết một sự kiện |
| `search_events` | Tìm kiếm/lọc sự kiện |
| `search_watchlist` | Tra cứu watchlist |
| `get_event_statistics` | Tổng hợp thống kê sự kiện |
| `get_traffic_analytics` | Phân tích dữ liệu lưu lượng |
| `get_alerts` | Tra cứu cảnh báo |
| `get_notifications_status` | Kiểm tra trạng thái notification |
| `generate_operational_report` | Tạo báo cáo vận hành |
| `get_knowledge` | Tra cứu tài liệu bằng RAG |

Agent có giới hạn số vòng tool và tổng số tool call để ngăn vòng lặp không kiểm soát.

---

## 4. Kiến trúc Agent

### 4.1. Thành phần chính

```text
React AgentPage
    ↓
/api/agent/*
    ↓
Authentication boundary
    ↓
Conversation registry
    ↓
run_agent_message()
    ↓
LangGraph StateGraph
    ├── LLM
    ├── Operational tools
    └── RAG tool
    ↓
PostgreSQL / DATT data / Knowledge Base
    ↓
Checkpoint + conversation metadata
    ↓
API response
    ↓
React UI
```

Các module trọng tâm:

- `frontend/src/pages/AgentPage.jsx`
- `frontend/src/api/agent.js`
- `src/agent/api/routes.py`
- `src/agent/api/auth.py`
- `src/agent/graph.py`
- `src/agent/nodes.py`
- `src/agent/tools/`
- `src/agent/rag/`
- `src/agent/memory/checkpoint.py`
- `src/agent/conversations.py`

### 4.2. Vòng lặp LangGraph

Kiến trúc chuẩn:

```mermaid
flowchart TD
    A[User Message] --> B[Agent Node]
    B --> C{Cần gọi tool?}
    C -- Có --> D[Tool Node]
    D --> B
    C -- Không --> E[Final Answer]
    E --> F[Save Checkpoint / Conversation Activity]
```

Agent không được gọi tool vô hạn. Cấu hình giới hạn được kiểm soát bằng các biến như `AGENT_RECURSION_LIMIT`, `AGENT_MAX_TOOL_REPEATS`, `DATT_AGENT_MAX_TOOL_CYCLES` và `DATT_AGENT_MAX_TOTAL_TOOL_CALLS`.

---

## 5. API Agent

Prefix:

```text
/api/agent
```

### 5.1. Gửi tin nhắn

```http
POST /api/agent/chat
```

Request điển hình:

```json
{
  "message": "Kiểm tra camera_01",
  "thread_id": "thread_abc123",
  "user_id": "operator_ui"
}
```

Response:

```json
{
  "status": "success",
  "thread_id": "thread_abc123",
  "reply": "...",
  "tools_called": ["get_camera_status"],
  "sources": []
}
```

### 5.2. Conversation API

| Method | Endpoint | Chức năng |
|---|---|---|
| `POST` | `/api/agent/conversations` | Tạo conversation mới |
| `GET` | `/api/agent/conversations` | Liệt kê conversation của user hiện tại |
| `GET` | `/api/agent/conversations/{thread_id}` | Lấy metadata + message history |
| `PATCH` | `/api/agent/conversations/{thread_id}` | Đổi tên conversation |
| `DELETE` | `/api/agent/conversations/{thread_id}` | Xóa conversation + checkpoint |

API kiểm tra ownership trước khi đọc/sửa/xóa hội thoại.

---

## 6. Conversation persistence và memory

### 6.1. Cô lập hội thoại

Thread nội bộ được namespace theo:

```text
<verified_user_id>:<thread_id>
```

Điều này ngăn hai user dùng cùng `thread_id` nhưng đọc chung history.

### 6.2. PostgreSQL và MemorySaver

- Khi có PostgreSQL hợp lệ, Agent dùng `PostgresSaver` với connection pool.
- Khi hệ thống yêu cầu persistent history, việc không khởi tạo được PostgreSQL checkpointer là lỗi và Agent không được âm thầm hạ xuống memory tạm.
- `MemorySaver` chỉ phù hợp cho môi trường phát triển/test khi persistent history không bắt buộc.

### 6.3. Xóa conversation

Xóa conversation phải xóa cả registry và các bảng checkpoint liên quan. Trong PostgreSQL, logic hiện tại xử lý các bảng:

- `checkpoints`
- `checkpoint_blobs`
- `checkpoint_writes`

Việc xóa được cô lập theo internal thread ID của user.

---

## 7. Xác thực và cô lập người dùng

Agent không tin tưởng trực tiếp `user_id` do client gửi.

### 7.1. Các chế độ identity

1. **Trusted reverse proxy**
   - Header `X-Proxy-Secret` phải khớp `DATT_TRUSTED_PROXY_SECRET`.
   - Header `X-User-Id` bắt buộc.

2. **Bearer HMAC token**
   - Header: `Authorization: Bearer <user>:<signature>`.
   - Signature dùng HMAC-SHA256 với signing secret của hệ thống.

3. **Local/development fallback**
   - Chỉ dùng khi strict/production auth không bắt buộc.
   - Client session được namespace bằng session token và IP.
   - Không cho phép client chưa xác thực tự nhận các danh tính đặc quyền như `admin`, `root`, `system`.

### 7.2. Production requirements

Trong deployment yêu cầu authentication production:

- cấu hình signing secret tối thiểu 32 ký tự;
- bật `DATT_STRICT_AUTH=1`;
- không dùng fallback signing key công khai;
- không commit secret vào Git.

---

## 8. Cấu hình LLM

### 8.1. Provider được hỗ trợ

Các provider hiện được code hỗ trợ:

- `openai`
- `google_genai`
- `mock`

`mock` dành cho smoke test/test không phát sinh real LLM request.

### 8.2. Biến môi trường chính

```dotenv
# Primary provider
DATT_AGENT_LLM_PROVIDER=openai
DATT_AGENT_LLM_MODEL=gpt-4o-mini
DATT_AGENT_LLM_TEMPERATURE=0.1
DATT_AGENT_LLM_TIMEOUT_SECONDS=30
DATT_AGENT_LLM_MAX_RETRIES=3

# Credentials - chỉ khai báo provider đang dùng
OPENAI_API_KEY=
GEMINI_API_KEY=
# GOOGLE_API_KEY=  # alias được hỗ trợ cho Gemini

# Optional fallback
DATT_AGENT_LLM_FALLBACK_PROVIDER=
DATT_AGENT_LLM_FALLBACK_MODEL=
```

Nếu provider là `openai` nhưng thiếu `OPENAI_API_KEY`, hoặc `google_genai` nhưng thiếu `GEMINI_API_KEY`/`GOOGLE_API_KEY`, Agent trả trạng thái provider không khả dụng thay vì giả vờ thành công.

### 8.3. Retry và fallback

Agent retry có giới hạn với các lỗi có khả năng tạm thời như timeout, rate-limit, HTTP 5xx hoặc connection reset.

Lỗi authentication/API key không hợp lệ không được retry mù quáng.

Nếu cấu hình fallback provider/model, hệ thống chuyển sang fallback khi primary thất bại.

---

## 9. Cấu hình giới hạn Agent

```dotenv
AGENT_RECURSION_LIMIT=15
AGENT_TIMEOUT_SEC=30
AGENT_TOOL_TIMEOUT_SEC=10
AGENT_MAX_TOOL_REPEATS=2
DATT_AGENT_MAX_TOOL_CYCLES=4
DATT_AGENT_MAX_TOTAL_TOOL_CALLS=8

AGENT_MAX_HISTORY_MESSAGES=20
AGENT_TRIM_THRESHOLD_TOKENS=4000
```

Mục tiêu của các giới hạn này:

- chặn tool loop;
- giới hạn thời gian treo;
- giới hạn context tăng vô hạn;
- giảm chi phí và rủi ro từ prompt không tốt.

---

## 10. RAG / Knowledge Base

### 10.1. Thành phần

RAG được chia thành:

- `chunking.py`: chia tài liệu thành chunk;
- `embeddings.py`: tạo vector embedding;
- `ingestion.py`: ingest/cập nhật knowledge base;
- `retrieval.py`: truy hồi chunk liên quan;
- `seed.py`: seed tài liệu nền;
- `tools/knowledge.py`: expose retrieval dưới dạng Agent tool.

### 10.2. Cấu hình RAG

```dotenv
DATT_AGENT_EMBEDDING_PROVIDER=fastembed
DATT_AGENT_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
DATT_AGENT_EMBEDDING_DIM=384

AGENT_RAG_CHUNK_SIZE=800
AGENT_RAG_CHUNK_OVERLAP=100
AGENT_RAG_TOP_K=4
AGENT_RAG_SCORE_THRESHOLD=0.50
```

Thư mục tài liệu mặc định của Agent là `docs/`.

### 10.3. PostgreSQL / pgvector

Knowledge Base có migration riêng sau nhóm migration CV cũ. Trên nhánh `dev`, schema hiện có:

- `0012_knowledge_base.py`
- `0013_knowledge_chunks_hnsw_index.py`

Do đó deployment mới phải chạy Alembic đến `head`, không dừng ở `0011`.

### 10.4. Luồng RAG

```mermaid
flowchart TD
    A[User question] --> B[Agent decides get_knowledge]
    B --> C[Embed query]
    C --> D[Vector / fallback retrieval]
    D --> E[Top-K chunks above threshold]
    E --> F[ToolMessage]
    F --> G[LLM synthesis]
    G --> H[Reply + sources]
```

Khi `get_knowledge` trả kết quả, API cố gắng trả metadata nguồn gồm title/document, section, score và page nếu dữ liệu có trường tương ứng.

---

## 11. Cấu hình Authentication cho Agent

```dotenv
# Signing secret cho Bearer HMAC; production nên >= 32 ký tự
DATT_AGENT_AUTH_SECRET=
# Hoặc dùng secret chung
# DATT_SECRET_KEY=

# Production strict mode
DATT_STRICT_AUTH=1

# Chỉ khi có trusted reverse proxy
DATT_TRUSTED_PROXY_SECRET=
```

Không dán secret vào notebook source, Markdown, log hoặc commit Git.

---

## 12. `.env` tham chiếu cho deployment có Agent

Ví dụ tối thiểu khi dùng PostgreSQL + OpenAI:

```dotenv
DATT_DATABASE_URL=postgresql://user:password@host:5432/datt
DATT_REQUIRE_PERSISTENCE=1

DATT_AGENT_LLM_PROVIDER=openai
DATT_AGENT_LLM_MODEL=gpt-4o-mini
OPENAI_API_KEY=<secret>

DATT_AGENT_EMBEDDING_PROVIDER=fastembed
DATT_AGENT_EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
DATT_AGENT_EMBEDDING_DIM=384

DATT_AGENT_AUTH_SECRET=<random-secret-at-least-32-characters>
DATT_STRICT_AUTH=1
```

Không dùng ví dụ này như secret thật.

---

## 13. Kiểm tra sau triển khai

### 13.1. Kiểm tra route

OpenAPI của ứng dụng phải có tối thiểu:

```text
POST   /api/agent/chat
POST   /api/agent/conversations
GET    /api/agent/conversations
GET    /api/agent/conversations/{thread_id}
PATCH  /api/agent/conversations/{thread_id}
DELETE /api/agent/conversations/{thread_id}
```

### 13.2. Smoke test không dùng quota LLM

Repo có script:

```bash
python -m scripts.agent_smoke
```

Smoke test dùng mock provider và phải được ưu tiên để xác nhận integration trước khi gửi real LLM request.

### 13.3. Colab

Notebook chính:

```text
notebooks/DATT_Colab_GPU.ipynb
```

Khi dùng notebook hiện tại, cần kiểm tra:

- source commit trùng `origin/dev`;
- application module đúng;
- Agent routes xuất hiện trong OpenAPI;
- mock Agent smoke PASS;
- live API schema PASS;
- `SYSTEM_READY=YES` chỉ sau khi các bước startup/smoke thành công.

`SYSTEM_READY=YES` không thay thế Real Camera Acceptance.

---

## 14. Xử lý sự cố Agent / RAG / Auth

### 14.1. `/api/agent/*` trả 404

**Nguyên nhân thường gặp**

- runtime đang chạy checkout cũ;
- process cũ chưa restart sau khi source đổi;
- frontend đang trỏ nhầm backend URL/port;
- đang truy cập một app FastAPI khác không có Agent router.

**Kiểm tra**

- `/healthz` và commit đang chạy;
- `/openapi.json` có `/api/agent/chat`;
- backend URL override trong browser;
- module ứng dụng đang được runner load.

### 14.2. Agent API kết nối được nhưng báo LLM unavailable

**Kiểm tra**

- `DATT_AGENT_LLM_PROVIDER`;
- model name;
- credential tương ứng;
- quota/rate-limit/provider outage;
- fallback provider nếu có.

Không coi lỗi provider là lỗi network của Agent API.

### 14.3. `401 Unauthorized`

Kiểm tra:

- `DATT_STRICT_AUTH`;
- header `Authorization`;
- token có đúng dạng `user:signature`;
- signing secret giữa nơi phát token và server có giống nhau;
- reverse proxy có gửi đúng secret/user header hay không.

### 14.4. `403 Forbidden` khi đọc conversation

Nguyên nhân thường là ownership không khớp. Không sửa bằng cách bỏ kiểm tra user/thread isolation.

Kiểm tra identity được server xác minh và thread có thuộc user đó không.

### 14.5. History không lưu hoặc mất sau restart

Kiểm tra:

- `DATT_DATABASE_URL` có thật sự trỏ PostgreSQL;
- môi trường có bắt buộc persistence hay không;
- PostgresSaver setup thành công;
- migration/database có khả dụng;
- không vô tình chạy test/dev bằng MemorySaver rồi kỳ vọng persistence.

### 14.6. Conversation list có nhưng message history lỗi 503

Registry và checkpoint là hai lớp khác nhau. Tình huống này có thể xảy ra nếu registry DB hoạt động nhưng checkpoint service/PostgreSQL saver lỗi.

Kiểm tra connection pool, checkpoint tables và log `datt.agent.memory`.

### 14.7. RAG không tìm thấy tài liệu

Kiểm tra theo thứ tự:

1. tài liệu có nằm trong nguồn ingest hay không;
2. migration `0012`/`0013` đã áp dụng;
3. knowledge base đã ingest/seed;
4. embedding provider/model/dimension có khớp dữ liệu index;
5. `AGENT_RAG_SCORE_THRESHOLD` có đặt quá cao;
6. query có đủ ngữ nghĩa để retrieval tìm đúng chunk.

### 14.8. Embedding dimension mismatch

Không đổi `DATT_AGENT_EMBEDDING_DIM` tùy ý trên database đã ingest bằng dimension khác. Nếu đổi embedding model/dimension, phải có quy trình re-index/re-ingest phù hợp.

### 14.9. Agent lặp tool hoặc trả chậm

Kiểm tra:

- prompt có mơ hồ khiến model gọi lặp tool;
- `AGENT_MAX_TOOL_REPEATS`;
- `DATT_AGENT_MAX_TOOL_CYCLES`;
- `DATT_AGENT_MAX_TOTAL_TOOL_CALLS`;
- `AGENT_TOOL_TIMEOUT_SEC`;
- thời gian phản hồi của DB/provider.

Không khắc phục bằng cách tăng vô hạn recursion/tool limits.

### 14.10. Frontend Agent báo disconnected nhưng camera vẫn chạy

Đây có thể là lỗi riêng của Agent API. Agent status và camera telemetry là hai tín hiệu khác nhau.

Kiểm tra API base URL và `/api/agent/conversations`/OpenAPI trước khi chỉnh camera service.

---

## 15. Nguyên tắc vận hành an toàn

- Không commit API key, database password, auth signing secret hoặc proxy secret.
- Không tắt ownership check để “sửa nhanh” lỗi history.
- Không dùng `user_id` client gửi như bằng chứng xác thực.
- Không tăng vô hạn retry/tool loop.
- Không giả định `SYSTEM_READY=YES` đồng nghĩa camera thực tế đã được nghiệm thu.
- Không dùng real LLM request cho smoke test nếu mock provider đủ để xác minh integration.
- Không thay embedding dimension trên knowledge base hiện hữu mà không re-index.

---

## 16. Checklist bàn giao Agent

- [ ] `/agent` tải được trên React UI.
- [ ] OpenAPI có đầy đủ Agent routes.
- [ ] Tạo conversation mới không xóa conversation cũ.
- [ ] Reload trình duyệt khôi phục được history mong đợi.
- [ ] User A không đọc/sửa/xóa được conversation của User B.
- [ ] Provider thật có credential hợp lệ hoặc hệ thống chủ động chạy `mock` trong test.
- [ ] RAG trả nguồn khi truy vấn tài liệu phù hợp.
- [ ] PostgreSQL persistence hoạt động trong deployment yêu cầu history bền vững.
- [ ] Migration chạy đến Alembic `head`, bao gồm Knowledge Base/HNSW.
- [ ] Agent smoke test PASS trước khi nghiệm thu real provider.
- [ ] Secret không xuất hiện trong source, notebook hoặc log công khai.

---

## 17. Tài liệu liên quan

- [USER_GUIDE.md](USER_GUIDE.md) — Camera, Watchlist, Events, Alerts và thao tác người dùng chung.
- [ADMIN_GUIDE.md](ADMIN_GUIDE.md) — Cài đặt, database, storage, model, runtime.
- [TECHNICAL_GUIDE.md](TECHNICAL_GUIDE.md) — Pipeline thị giác máy tính và kiến trúc backend.
- [SYSTEM_FLOWS.md](SYSTEM_FLOWS.md) — Các flow CV/Event hiện có.
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) — Sự cố Camera/GPU/OCR/DB/Notification.
- [agent_colab_integration.md](agent_colab_integration.md) — Ghi chú kỹ thuật lịch sử về quá trình sửa Agent/Colab; không dùng thay cho manual chuẩn này.

---

> Khi code Agent, API contract, authentication, migration hoặc cấu hình RAG thay đổi, tài liệu này phải được cập nhật cùng pull request/commit để tránh docs drift.
