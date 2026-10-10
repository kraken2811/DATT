# Hệ Thống Giám Sát Thị Giác Thông Minh DATT — Documentation Hub

Bộ tài liệu này là điểm vào chính cho hệ thống **DATT (Deep AI Tracking & Targeting System)** trên nhánh `dev`.

Hệ thống hiện gồm hai nhóm chức năng lớn:

1. **Computer Vision / Security Monitoring** — camera đa nguồn, object detection, tracking, face recognition, ANPR/OCR, watchlist, Event Center, Alert Center và notification.
2. **DATT AI Assistant** — giao diện React `/agent`, LangGraph Single Agent, tool nghiệp vụ, conversation persistence, authentication/tenant isolation và RAG/Knowledge Base.

---

## 1. Danh mục tài liệu chuẩn

| STT | Tài liệu | Đối tượng | Nội dung chính |
|---|---|---|---|
| 01 | [USER_GUIDE.md](USER_GUIDE.md) | Người vận hành | Camera, Watchlist, Event Center, Alert Center, thao tác giao diện và FAQ |
| 02 | [AGENT_RAG_GUIDE.md](AGENT_RAG_GUIDE.md) | Người vận hành, Admin, Developer | AI Assistant, conversation, Agent API, authentication, LLM, RAG, troubleshooting Agent |
| 03 | [SYSTEM_REQUIREMENTS.md](SYSTEM_REQUIREMENTS.md) | IT Ops, triển khai | CPU/GPU/RAM, Python, PostgreSQL/pgvector, camera/video source và điều kiện triển khai |
| 04 | [ADMIN_GUIDE.md](ADMIN_GUIDE.md) | System Admin, DevOps | Cài đặt, database, storage, models, service lifecycle, backup/restore |
| 05 | [TECHNICAL_GUIDE.md](TECHNICAL_GUIDE.md) | Developer, AI Engineer | Kiến trúc pipeline CV, backend, persistence, notification và các module kỹ thuật |
| 06 | [SYSTEM_FLOWS.md](SYSTEM_FLOWS.md) | Architect, Developer | Các flow Camera/CV/Event/Notification hiện có |
| 07 | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Helpdesk, DevOps | Sự cố Camera/GPU/Face/OCR/DB/Notification/Frontend |

### Engineering notes / historical reports

Các file như [agent_colab_integration.md](agent_colab_integration.md) dùng để ghi lại quá trình sửa lỗi, hardening hoặc validation. Chúng hữu ích cho kỹ sư nhưng **không thay thế** tài liệu chuẩn ở bảng trên.

---

## 2. Kiến trúc tổng quan hiện hành

```text
Camera / RTSP / HLS / YouTube / Video File
                │
                ▼
        Video Ingestion / Runtime
                │
                ▼
       YOLO Object Detection
                │
                ▼
            ByteTrack
       ┌────────┴────────┐
       ▼                 ▼
 Face Pipeline       Vehicle Pipeline
 SCRFD + AdaFace     Plate Detect + OCR
       │                 │
       ▼                 ▼
 Face Watchlist      Vehicle Watchlist
       └────────┬────────┘
                ▼
          Event Manager
                │
       ┌────────┴──────────────┐
       ▼                       ▼
 PostgreSQL + pgvector    Notification Outbox
       │                       │
       └──────────┬────────────┘
                  ▼
          FastAPI Backend
                  │
        ┌─────────┴──────────┐
        ▼                    ▼
   React Frontend       DATT AI Agent
 dashboard/camera/      LangGraph + tools
 events/alerts/...      + conversation/RAG
        │                    │
        └─────────┬──────────┘
                  ▼
               User
```

Frontend hiện tại nằm trong `frontend/` và dùng **React + React Router**. Các route chính gồm:

```text
/
/dashboard
/cameras
/cameras/:id
/watchlist
/events
/alerts
/settings
/agent
```

Không sử dụng mô tả kiến trúc cũ “HTML5 / CSS / Vanilla JS” để đại diện cho frontend hiện tại.

---

## 3. DATT AI Assistant

Tài liệu chuẩn: [AGENT_RAG_GUIDE.md](AGENT_RAG_GUIDE.md).

### Thành phần chính

```text
frontend/src/pages/AgentPage.jsx
frontend/src/api/agent.js
src/agent/api/routes.py
src/agent/api/auth.py
src/agent/graph.py
src/agent/tools/
src/agent/rag/
src/agent/memory/checkpoint.py
src/agent/conversations.py
```

### API prefix

```text
/api/agent
```

Các route conversation/chat hiện tại:

```text
POST   /api/agent/chat
POST   /api/agent/conversations
GET    /api/agent/conversations
GET    /api/agent/conversations/{thread_id}
PATCH  /api/agent/conversations/{thread_id}
DELETE /api/agent/conversations/{thread_id}
```

### Agent tools

Agent đăng ký các nhóm tool: camera, event, watchlist, analytics, alerts, notification status, operational report và knowledge/RAG.

---

## 4. Database migrations

Deployment không nên hard-code giả định rằng migration chỉ dừng ở `0011`.

Trên nhánh `dev`, migration hiện đã bao gồm Knowledge Base và vector index:

```text
0001 ... 0011  Core CV / watchlist / notification schema
0012_knowledge_base.py
0013_knowledge_chunks_hnsw_index.py
```

Quy tắc vận hành: chạy Alembic đến **`head`** theo version code đang deploy.

---

## 5. Cấu hình môi trường

File tham chiếu:

```text
.env.example
```

`.env.example` hiện bao gồm các nhóm cấu hình:

- LLM provider/model/API key;
- optional fallback LLM;
- Agent execution/tool-loop limits;
- conversation/context trimming;
- RAG embedding/chunk/retrieval settings;
- Agent authentication và trusted proxy;
- PostgreSQL/persistence;
- external storage.

Không commit `.env` thật hoặc bất kỳ API key/password/signing secret nào.

---

## 6. Colab

Notebook chính:

```text
notebooks/DATT_Colab_GPU.ipynb
```

Notebook hiện có cơ chế cập nhật checkout sạch về `origin/dev` bằng fast-forward trước khi startup. Tài liệu kỹ thuật chi tiết về quá trình hardening Agent/Colab nằm tại [agent_colab_integration.md](agent_colab_integration.md).

Khi nghiệm thu Colab, cần phân biệt:

- **Source/runtime readiness** — đúng commit, dependency, API routes, smoke tests;
- **Real Camera Acceptance** — camera thật, stream thật, inference và event thực tế.

`SYSTEM_READY=YES` không tự động chứng minh Real Camera Acceptance.

---

## 7. File mã nguồn trọng tâm

### Backend / runtime

- `src/ui/web_server.py` — FastAPI application và backend routes.
- `src/runtime/runtime_manager.py` — quản lý lifecycle camera/runtime.
- `src/events/event_manager.py` — event logic và dedup/coalescing.
- `src/events/db_worker.py` — ghi DB nền.
- `src/notifications/service.py` — notification/outbox.
- `src/storage.py` — storage abstraction.

### Computer Vision

- `src/detector/yolo_detector.py`
- `src/tracker/bytetrack_tracker.py`
- `src/face/adaptive_pipeline.py`
- `src/ocr/plate_reader.py`
- `src/recognition/color_extractor.py`

### Database

- `src/db/models.py`
- `src/db/database.py`
- `src/db/migrations/versions/`

### React frontend

- `frontend/src/App.jsx` — route composition.
- `frontend/src/pages/` — các trang Dashboard/Camera/Watchlist/Event/Alert/Settings/Agent.
- `frontend/src/api/` — API clients.
- `frontend/src/components/` — UI components dùng chung.
- `frontend/src/context/` — React contexts.

### AI Agent / RAG

- `src/agent/config.py`
- `src/agent/graph.py`
- `src/agent/nodes.py`
- `src/agent/api/routes.py`
- `src/agent/api/auth.py`
- `src/agent/tools/`
- `src/agent/rag/`
- `src/agent/memory/`

---

## 8. Quy tắc đồng bộ tài liệu với code

Khi thay đổi một trong các phần sau, pull request/commit tương ứng phải cập nhật tài liệu liên quan:

- route frontend hoặc API;
- Agent tool;
- authentication contract;
- environment variable;
- migration/schema;
- RAG embedding/index/chunking;
- deployment/Colab startup flow;
- yêu cầu phần cứng/phần mềm.

Không sử dụng câu khẳng định “tài liệu phản ánh chính xác code hiện hành” nếu chưa kiểm tra lại code của cùng commit.
