# DATT Full Code Audit

## 1. Current Runtime Architecture

Audit ngày 24/09/2026, working tree sau thay đổi VOD FFmpeg. **Báo cáo này thay thế kết luận về trạng thái hiện tại trong `YOUTUBE_LIVE_READINESS_AUDIT.md`: lỗi constructor VOD và alias API trong snapshot trước đã được sửa.** Không sửa mã ứng dụng hoặc test trong lần audit này. Chỉ chạy kiểm thử, probe trong process kiểm thử và ghi report/log. Không chạy YouTube Live.

Entrypoint `src/main.py` → `RuntimeManager` → một AI daemon chạy `app.run_pipeline()` và một Uvicorn daemon chạy FastAPI. Internal HTTP/MJPEG mặc định `127.0.0.1:8000`, web proxy `0.0.0.0:8501`. AI khởi tạo YOLO, ByteTrack, ZoneCounter, CameraManager một lần; renderer và UI không load model riêng. EventManager singleton có persistence worker và queue giới hạn100 task. Streamlit dashboard là giao diện legacy đọc HTTP, không phải entrypoint UI chính hiện tại.

| Flow | Runtime thực tế |
|---|---|
| Local MP4 | File → `LocalVideoReader` → OpenCV decode trong reader thread → latest `VideoFrame` → `CameraManager.read` → YOLO → ByteTrack → TargetMatcher → ZoneCounter/renderer/events → shared state → MJPEG/telemetry → FastAPI proxy/web UI. |
| YouTube VOD | URL → `YouTubeVODReader.start` resolve đồng bộ qua singleton yt-dlp resolver → direct URL → FFmpeg subprocess xuất BGR24 → VOD capture thread đọc đủ frame → latest `VideoFrame` → cùng manager/AI/render/UI. **Không còn OpenCV mở direct VOD URL.** |
| YouTube Live | URL → `CameraReader` capture thread → resolver → direct URL/HLS → FFmpeg subprocess → `CapturedFrame` latest slot → cùng manager/AI/render/UI. Thêm stderr daemon và health daemon. |

VOD có capture/stderr thread, local có reader thread. Manager sở hữu active reader; reader sở hữu decoder. Local/VOD/Live đều có lock, sequence và copy khi giao frame cho consumer. Không có unbounded frame queue phía Python. VOD pace theo `target_fps=30` mặc định, scale1280×720; local lấy native FPS. Các buffer pipe/FFmpeg/decoder vẫn tồn tại: latest slot không đồng nghĩa không có độ trễ upstream.

Local EOF: loop seek0 hoặc kết thúc. VOD EOF: `loop=False` dừng; `loop=True` spawn FFmpeg lại với URL hiện có. **VOD đang gộp EOF với mọi process exit/nonzero và read exception trả rỗng**, nên hành vi lỗi không đúng như tên nhánh. Live EOF/partial frame: threshold read failure10 nếu process còn sống, sau đó cleanup/reconnect; Live retry vô hạn với delay có trần.

Local stop set event/join2s. VOD stop set event, cleanup subprocess, join capture3s/stderr1s. Live stop set event, cleanup, join capture5s; không join health/stderr. Timeout join chưa chứng minh resource chết. Cả VOD và Live đóng stdout trước terminate, có thể kẹt trên buffered read.

`set_video_source()` dispatch local/file/mp4, vod/youtube_vod, live/youtube. `start_camera()` từ YAML lại luôn tạo CameraReader, không dispatch theo type. Switch giữ manager RLock, stop cũ, start mới, cập nhật camera. App phát hiện camera ID đổi rồi reset ByteTrack, target tracks, counter/event state. Manager mới cũng reset target tracks. Shared frame không clear; không có generation token để loại frame cũ đang đọc.

Nguồn kiểm tra: app/main/config; runtime/shared state; toàn bộ reader/manager/resolver; HTTP/FastAPI/JS và dashboard; detector/tracker/counter; recognition/face; event/storage; configs, requirements, tests và notebook/script liên quan. Tên thư mục thực tế là `src/detector/`, `src/tracker/`; các package placeholder không tạo pipeline khác. Các module không đổi được đối chiếu Git ngoài việc trace call path; không lấy nội dung report cũ thay cho code mới.

## 2. Changes Made in the Last ~20 Minutes

Git evidence: HEAD `41873f8`, `2026-09-24T14:23:23+07:00`, message `Phase 4.6`. Hai lệnh `git log --since="20 minutes ago" --oneline --decorate` và `git log --since="20 minutes ago" --stat` không trả commit. `git diff`, `git diff HEAD`, `git diff --stat`, `git diff --name-only` xác định **4 file tracked đang sửa, 302 insertions, 93 deletions**. `git status --short` còn có test mới và report trước chưa tracked.

Không thể xác định tác giả hay thời điểm từng dòng từ uncommitted diff. Các thay đổi ứng dụng dưới đây đã hiện diện khi đọc snapshot mới; **người audit không thực hiện chúng trong lượt này**. “Vì sao” là mục đích suy ra từ diff/test, không phải lịch sử tác giả đã được xác minh. LastWriteTime chỉ là bằng chứng thời gian file, không phải commit history. Cửa sổ khoảng20 phút là tương đối so với lúc bắt đầu yêu cầu, không đủ để phân biệt mọi edit trong và ngoài cửa sổ.

| File / LastWriteTime local | Exact change và mục đích | Git state / mức hoàn tất / regression risk |
|---|---|---|
| `src/stream/camera_manager.py` /15:03:50 | ID nguồn dùng `time.time()` thay `int(time.time())`, giảm trùng ID trong cùng giây. Truyền `loop` vào VOD; metadata lấy width/height của reader. Reset target track khi set source. `read()` lấy diagnostics một lần, dùng `.get('ffmpeg_alive')` và fallback reader_alive thay index bắt buộc. | Uncommitted. Constructor tương thích với reader mới, tests pass. Reset/ID chưa có tính atomic theo generation; timestamp không bảo đảm uniqueness tuyệt đối. Stop reader cũ vẫn phụ thuộc lifecycle lỗi. |
| `src/stream/video_source.py` /15:12:38 | Thêm subprocess/shutil/imageio_ffmpeg và dùng `read_frame_bytes`. Base/local diagnostics thêm source type, alive/PID/exit/time/read-error fields. Thay VOD OpenCV URL bằng FFmpeg pipe; thêm loop,width,height; build command, spawn, stderr drain, cleanup; capture raw BGR24, pacing, EOF loop; stop/join và diagnostics FFmpeg. | Uncommitted. Happy path FFmpeg decode được; **chưa hoàn tất về failure safety**: EOF gộp lỗi, loop bypass budget, stdout close trước terminate, thiếu network read timeout/first-frame watchdog và finally bao worker. |
| `src/ui/video_stream.py` /15:09:23 | Internal handler chọn `data.get('type') or data.get('source_type') or 'local'`. | Uncommitted. Alias hoạt động, probe xác nhận. Khi cả hai khác nhau thì type thắng; schema/boolean chưa strict. |
| `src/ui/web_server.py` /15:09:15 | FastAPI handler dùng cùng alias fallback rồi lower/strip. | Uncommitted. Forward schema đúng theo static trace; timeout15s vẫn không hủy backend operation. |
| `tests/test_youtube_vod_ffmpeg.py` /15:15:31 | Thêm9 test methods bao10 yêu cầu: không OpenCV VOD, raw frame/command, diagnostics, switch hai chiều, stop, EOF, resolve count, start không lặp, Live command/diagnostics. | Untracked. Được full suite collect/pass. Popen/pipe/resolver chủ yếu fake; “no zombie” và “Live remains functional” trong docstring rộng hơn điều thực tế test. Không kiểm tra blocked pipe, nonzero EOF,429 hoặc network stall. |
| `docs/YOUTUBE_LIVE_READINESS_AUDIT.md` /15:12:29 | Report của snapshot trước: có61pass/1fail, khi manager mới nhưng reader cũ chưa nhận loop. | Untracked, do lượt audit trước tạo. Đã lỗi thời ở VOD/alias/test count; **không dùng như kết luận cho bản mới**. |
| `results/readiness_audit/*` | Harness/log/JUnit/JSON/clip phục vụ kiểm chứng; file cũ và mới được phân biệt ở mục7. | Gitignored. Không phải thay đổi production; không tự có trong clone/commit report. |
| `docs/DATT_FULL_CODE_AUDIT.md` | Báo cáo hợp nhất của lượt hiện tại. | File tài liệu mới; không sửa implementation. |

`youtube_stream.py`, `youtube_resolver.py`, app, detector, tracker, target matcher, frontend JS, requirements **không có diff so với HEAD** trong snapshot này. Các lỗi Live cũ chưa được các thay đổi VOD sửa.

SHA-256 snapshot các file ứng dụng thay đổi và test mới:

```text
camera_manager.py       85CA0A31C62A0DBE23409C6B2889D4B0730B4855A581F97B274191D83D876814
video_source.py         8882D9A57663D02B61DE80D1BF0BB469B2BC58E3DC8C78888911E02AA1FCCB09
ui/video_stream.py      ACAAF66993DF998A6C3B9EF5BB1C4E8495A3900E741A089F345A060D0B6719BD
ui/web_server.py        D999C5DD6A9DD95EE1B5B6759DC29C12D38D1D91684B894D7F519F6A15926287
test_youtube_vod_ffmpeg.py 7F9FAC851B22046CEAC801DAEAF728A5F7D7944C8DA1F61B0451B5A7A27177ED
```

## 3. Verified Recent Fixes

| Fix | Status | Evidence và giới hạn |
|---|---|---|
| VOD không dùng OpenCV direct HTTPS URL | **PASS** | Current `_capture_loop` chỉ đọc FFmpeg stdout; regression test1 kiểm tra cv2 không gọi; smoke FFmpeg thật nhận frame720×1280. |
| Constructor VOD nhận loop/width/height | **PASS** | Code hiện tại có đủ; test switch cũ từng fail nay pass. |
| `KeyError: ffmpeg_alive` | **PASS** cho lỗi cụ thể này | Manager dùng get, local/VOD bổ sung schema; regression test3 và smoke manager. Không bảo đảm mọi diagnostics exception khác không xảy ra. |
| `type` và `source_type` | **PASS** | Cả hai handler cùng fallback; inline probe internal alias forward `source_type=youtube_vod`. Không còn default local khi chỉ truyền alias hợp lệ. |
| local→VOD→local→VOD không restart manager | **PASS có phạm vi** | Regression test mock pass. Smoke thực dùng OpenCV local và FFmpeg thật qua cùng manager, URL resolver thay bằng clip local; sau mỗi lượt gọi stop để kiểm tra resource. Continuous switch với network thật **NOT VERIFIED**. |
| Không zombie process/thread sau mọi switch | **NOT VERIFIED** | Smoke bình thường không còn child, reader thread chết. Không đủ bảo đảm network stall/race; code có blocker cleanup bên dưới. |
| YOLO load một lần, AI/MJPEG tiếp tục | **PASS cho local** | Rerun app smoke trên code mới: model loads1,9 inference, telemetry tiến sau local switch, JPEG header nhận được, pipeline stop chỉ còn MainThread. |
| Live không bị VOD sửa hỏng | **PASS về diff/import/unit; NOT VERIFIED end-to-end** | File Live/resolver không đổi, tests hiện pass. Test Live mới chỉ command builder/diagnostics của reader chưa start. Không chứng minh live ingestion ổn định. |

## 4. Remaining Bugs and Risks

Mỗi đề xuất dưới đây là sửa tối thiểu trên kiến trúc hiện tại; chưa áp dụng.

| ID / Severity | File / function/class | Root cause, runtime impact, phạm vi | Minimal recommended fix |
|---|---|---|---|
| R1 **BLOCKER** | `video_source.py::YouTubeVODReader._capture_loop` | `exit_code is not None or len(raw)==0` đều thành EOF, không phân exit0/1/HTTP lỗi/read exception. `loop=True` continue không tăng retries/không backoff; manager/API mặc định loopTrue. Probe exit1 spawn3 lần, retry0 đến khi harness chủ động stop. LoopFalse che lỗi thành STOPPED không error. **VOD/UI/request safety.** | Tách clean EOF khỏi abnormal exit, lưu exit/stderr, backoff/cooldown/retry budget cho lỗi; chỉ loop clean EOF. |
| R2 **BLOCKER** | `video_source.py` và `youtube_stream.py::_cleanup_process` | Đóng buffered stdout trước terminate có thể chờ lock reader đang block. Timeout wait không giúp vì chưa chạy tới wait. VOD vừa sao chép lỗi lifecycle này từ Live. **VOD/Live/switch.** | Một lifecycle owner; terminate/kill trước để unblock read, deadline cleanup rồi close/join; test real blocked pipe. |
| R3 **HIGH** | `video_source.py::_build_ffmpeg_cmd`, `_capture_loop`, `_spawn_ffmpeg` | VOD không có `rw_timeout`, first-frame/stale watchdog; worker không có outer try/finally bảo đảm cleanup. Stop có thể xóa `_process` trong lúc spawn đang ngủ0.3s rồi dereference poll; resolve/recovery không kiểm tra stop ngay trước spawn. **VOD/control API.** | Timeout hữu hạn và cancel guard sau blocking step/trước spawn; local proc reference/ownership, finally toàn worker; trạng thái stop dựa thread thật. |
| R4 **BLOCKER** | `youtube_stream.py::read`, `_spawn_ffmpeg` | Timestamp frame đời trước không reset khi reconnect; watchdog >15s có thể terminate process mới trước frame đầu. Timestamp0 lại không có watchdog first-frame. **Live.** | Timestamp/generation riêng mỗi process, first-frame deadline riêng. |
| R5 **BLOCKER** | `youtube_stream.py::stop/_reconnect`, `youtube_resolver.py` | Resolver sleep/extract không cancel-aware; stop join5s có thể trả về, rồi `_reconnect` spawn sau stop. Health/stderr không được join toàn bộ. **Live/overlap source.** | Cancel-aware waits và recheck trước spawn; serialize start/stop, chỉ chuyển nguồn khi owner cũ chết hoặc báo stop failure rõ. |
| R6 **BLOCKER** | Live `_reconnect/_read_loop_impl`, VOD error paths | FFmpeg429 không dùng resolver429 cooldown/counter. Live clearURL/refresh; VOD spawn failure refresh hoặc runtime error đi EOF-loop. **YouTube requests.** | Shared HTTP error policy cho extractor/decoder; cooldown+circuit breaker/budget, Retry-After nếu có. |
| R7 **HIGH** | `youtube_resolver.py::resolve_stream_url` | Check/register in-flight tách lock; waiter timeout60s có thể thay owner; owner cũ finally pop owner mới. Cache key chỉ videoID, không Live/VOD; startup Live invalidate cache trước resolve. **VOD/Live duplicate extraction.** | Atomic owner registration và identity cleanup; key theo mode, cache expiry theo URL; invalidate có lý do. |
| R8 **MEDIUM** | `youtube_resolver.py::_execute_yt_dlp_extraction` | Bare ID dùng literal `watch?v=video_id`; VOD ranking ưu tiên MP4 nhưng không H264 như docstring, >720 chọn height lớn hơn. **VOD/Live ID input/performance.** | Nội suy ID thật; score đúng mục tiêu codec/resolution và test selection. |
| R9 **HIGH** | `runtime_manager.py::start/start_ai_pipeline/run/shutdown`; `app.py::run_pipeline` | Catch mọi TypeError rồi chạy lại AI không stop_event; model/camera start trước bind và trước try/finally. `start()` không guard duplicate; run chỉ thoát khi AI chết nếu max_frames có. Join shutdown không kiểm tra còn sống. **All/startup/leak.** | Bỏ fallback rộng, try/finally từ resource đầu tiên, idempotent start, AI crash propagate, shutdown xác minh owner chết. |
| R10 **MEDIUM** | `camera_manager.py::read/set_video_source`; `app.py`; `shared_state.py` | Read thả lock giữ reader cũ; frame cũ có thể publish sau switch, metadata đổi mà shared frame chưa clear. Reset tracker/target không atomic với frame generation. **All/switch/association/UI.** | Generation token, reject frame đời cũ, clear shared frame và reset ở ranh giới nguồn. |
| R11 **MEDIUM** | `video_source.py::YouTubeVODReader._capture_loop/_build_ffmpeg_cmd` | Raw pipe không mang PTS, phát theo30fps cố định, không native FPS; scale1280×720 không giữ aspect. Video24/60fps có thể chạy sai thời gian và crop matching méo. **VOD/AI.** | Lấy native FPS/timestamps hoặc FFmpeg pacing/resampling rõ; preserve aspect/letterbox khi cần. |
| R12 **MEDIUM** | `video_source.py::LocalVideoReader._capture_loop`; `app.py` | Loop file rỗng/hỏng có thể seek liên tục không sleep. Hai latency list append vô hạn dù latest frame bounded. **Local CPU/all RAM dài hạn.** | Hạn mức invalid-frame loop/backoff; running aggregates/bounded window. |
| R13 **MEDIUM** | `ui/web_server.py::get_video_source/set_video_source`, internal handler | Backend offline fallback RUNNING; proxy15s timeout không hủy switch đồng bộ. `bool('false')` là True, JSON không-object có thể lỗi validation. **UI/VOD.** | Offline status thật, typed request validation, operation state/cancellation hoặc chống trùng request. |
| R14 **MEDIUM** | `app.py`, `shared_state.py`, reader diagnostics | `set_stream_health` chưa được app gọi. Counter starts/drops/403/EOF thiếu hoặc không tăng; resolve count chỉ success. VOD ghi exit code trước terminate; trạng thái alive/RUNNING trước frame đầu. **Observability.** | Snapshot wiring và cumulative counters thật; tách process alive/frames fresh, lưu final exit code. |
| R15 **MEDIUM** | `events/event_manager.py::stop/reset`; global singleton | Stop worker không drain pending queue; start pipeline lần2 cùng interpreter không restart singleton worker. Snapshot từ source cũ có thể hoàn tất sau switch. **Events/notebook restart.** | Định nghĩa drain/cancel khi stop và worker start lifecycle; gắn event generation. |
| R16 **MEDIUM** | `recognition/target_matcher.py::match_tracks` | Unmatched tracks không được skip theo re-eval interval; face cache giữ embedding suốt track, cleanup TTL bị bỏ qua khi không có tracks/targets. **AI latency/association.** | Throttle cả unmatched, TTL cleanup độc lập và invalidation policy rõ. |
| R17 **HIGH** cho Colab | `requirements-colab.txt`, `requirements.txt`, model provisioning | Colab thiếu explicit FastAPI/Uvicorn/HTTPX/YAML/multipart; supervision không pin và warning ByteTrack removal0.31. GPU/model/JS-EJS clean Colab chưa xác minh. **Deployment.** | Bộ deps tương thích đã kiểm chứng, provision model, clean install/local GPU smoke trước Live. |

## 5. Resource and Concurrency Audit

**FFmpeg/process:** happy path VOD smoke chạy hai PID19200/1880, mỗi lượt nhận frame rồi stop; process_alive_after_stop=False, children_after=[]. Đây là subprocess thật đọc fixture, không phải Googlevideo network. Không có bằng chứng zombie trong lần smoke này. Không thể tuyên bố “no zombies” toàn hệ thống do R2/R3/R5. Linux zombie-state cụ thể **NOT VERIFIED** trên Windows.

**Threads/locks:** RLock bảo vệ shared slots nhưng không bảo vệ toàn vòng đời resource. Manager giữ lock trong resolve/stop nên một thao tác kẹt có thể chặn status/source API khác. VOD start resolve khi giữ lock; stop set event nhưng có thể đợi lock, start lại clear event sau resolve. Các timeout join không buộc thread chết. VOD stderr list dùng chung giữa đời process, old drain thread có thể vẫn tác động list mới. Current smoke reader threads chết; một timer harness vừa cancel còn hiện `Thread-4` tại thời điểm enumerate, không phải reader. Local AI smoke cuối chỉ còn MainThread.

**Duplicate instances:** start guard reader là check thread alive, không global process lock. RuntimeManager không guard start lần2; check port rồi release không reserve; headless không có port guard, hai port bằng nhau chưa reject. Process/notebook khác có resolver/semaphore khác, có thể cùng ingest YouTube. Không có bằng chứng duplicate Live đang chạy trong audit; có đường code cho phép xảy ra.

**Queue/latency:** frame/latest state bounded; timestamp deque30; stderr tối đa50 dòng. Event queue100 có thể giữ bản sao ảnh, nhưng không phải hàng đợi frame cho inference. Pipe/backpressure VOD cộng pacing30fps vẫn tích lũy độ trễ theo playback timing; input read FPS không phải source native FPS. Main latency lists tăng theo phiên. Không đo RAM nhiều giờ hoặc GPU VRAM thật.

**Telemetry inventory:**

| Metric | Current evidence |
|---|---|
| Source type | Có trong local/VOD diagnostics và metadata; Live diagnostics chưa cùng schema. |
| Reader/FFmpeg alive, PID | Có; local FFmpeg=None hợp lý. Cần phân process đang sống với frame mới. |
| Frames received, input FPS, frame age | Reader có; key Live `last_frame_age`, VOD/local `frame_age_seconds` chưa thống nhất. |
| Inference FPS/latency | App shared telemetry có; CPU smoke xác minh. |
| Reconnect / FFmpeg starts | Attempt Live reset khi khỏe; `stream_restarts` không tăng. Chưa đủ cumulative. |
| yt-dlp resolve count | `total_resolves` chỉ successful resolution; attempts thật chưa count đầy đủ. |
| 429 | Chỉ resolver đếm, decoder không cập nhật chung. |
| 403 / EOF | Chưa có cumulative counter riêng. |
| Read errors | VOD có, Live chủ yếu log; EOF/partial frame không đồng nghĩa read exception. |
| Runtime/RAM | Có log Live, chưa thống nhất API; long-run trend NOT VERIFIED. |
| GPU memory | Detector hỗ trợ torch allocation; local CPU trả0, Colab GPU NOT VERIFIED. |
| Shared stream_health / dropped frames | Health wiring chưa gọi; dropped counter0 không chứng minh không drop. |

## 6. YouTube Live / 429 Audit

**Normal operation:** YouTube URL → resolver → direct HLS/video URL → FFmpeg → raw BGR24 latest slot → AI/UI. Không yt-dlp mỗi frame; health thread chỉ log, UI poll telemetry/events không mở ingest. Playlist/segment/playlist refresh là request HLS bình thường, không tự coi là request dư.

**Cache/resolve:** TTL4h, failure threshold3, semaphore1 trong process, spacing3s giữa extraction sessions. Một yt-dlp extraction có thể gửi nhiều request tới các client/endpoints. Live reader mới invalidate cache ở refresh/start; direct reconnect max3 nhưng counter không reset ở healthy frame, có thể refresh sớm sau nhiều lỗi rời nhau. Cache key không bao mode. In-flight race R7 còn nguyên.

**Network failure:** FFmpeg internal HTTP reconnect1/reconnect_streamed1/delay_max5, rw_timeout15s → Python đọc thiếu/EOF hoặc process exit → clear latest/cleanup → `_reconnect` → thử cached direct hoặc resolve lại → spawn. Python delay3,5,10,20,40,60,120,300 giây+jitter tối đa5; initial start có thể0. Vòng ngoài vô hạn đến stop. Hai tầng reconnect có thể khuếch đại recovery, nhất là watchdog/stop race, dù không có bằng chứng cứ mỗi lần lỗi là hai FFmpeg đồng thời.

**403:** FFmpeg báo lỗi → generic reconnect/cached URL retry → refresh khi hết direct budget. Resolver DownloadError không429 raise; không cooldown/category403 riêng. Không xác minh403 thật hay expiry thật.

**429 tại yt-dlp:** error → counter429 → global cooldown → backoff10/20/40 giây+jitter0..5, max3 attempts mỗi execute, cap config120; sau lần cuối trả lỗi ra reader. Không Retry-After parser; các sleep không cancel-aware. Outer reader vẫn có thể retry ở phiên execute sau.

**429 tại Live FFmpeg:** stderr429 → force refresh/URL=None → cleanup → Python reconnect delay → invalidate → yt-dlp → FFmpeg mới. Không cập nhật resolver global cooldown/429 metric. Probe cũ trên **file Live/resolver vẫn không đổi** cho thấy hai resolve/spawn và cooldown0/metric4290; đây là injected failure, không phải HTTP429 thật.

**429 tại VOD mới:** nếu FFmpeg thoát trước startup check thì invalidate/resolve sau delay2s và spawn retry budget; nếu đã qua startup check rồi pipe rỗng/process exit thì bị coi EOF. LoopTrue tiếp tục dùng URL cũ, không cooldown/budget. Probe hiện tại exit1→spawn3→retries0 xác minh control flow; không cố tình gửi429 tới YouTube.

**Stale frame Live:** `read()` kiểm tra age>15s và timestamp>0 → terminate FFmpeg → reader cleanup/reconnect. Health chỉ log10s; timestamp đời cũ chưa reset khi spawn nên process mới bị watchdog giết sớm. Nếu không nhận frame đầu, timestamp0 không kích hoạt watchdog này. VOD mới không có watchdog tương đương và không rw_timeout.

**Kết luận:** nguy cơ retry/reconnect amplification **vẫn tồn tại**, VOD mới thêm đường EOF-loop bỏ qua error budget. Chưa đo request/phút Live thật và không khẳng định đã có storm mạng trong lượt này. Bằng chứng code/probe đủ để không chạy Live trước khi xử lý blocker.

## 7. Test Results

Chạy bằng `.\venv\Scripts\python.exe`, mỗi lệnh có `--junitxml` và log trong `results/readiness_audit/`. Các lệnh và kết quả:

| Command | Result | Artifact |
|---|---|---|
| `python -m pytest tests/test_video_sources.py -v` | **PASS:6**,3.58s | `current_video_sources.txt/xml` |
| `python -m pytest tests/test_target_matcher.py -v` | **PASS:10**,0.19s | `current_test_target_matcher.txt/xml` |
| `python -m pytest tests/test_target_api.py -v` | **PASS:8**,2 warnings,7.46s | `current_test_target_api.txt/xml` |
| `python -m pytest tests/test_e2e_target_tracking.py -v` | **PASS:1**,1 warning,5.20s | `current_test_e2e_target_tracking.txt/xml` |
| `python -m pytest tests -v` | **PASS:71**,3 warnings,43.76s | `current_full.txt/xml` |
| Inline Python FFmpeg/manager smoke | **PASS trong phạm vi fixture**,command exit0 | `current_ffmpeg_smoke.json/txt`;4 lượt local/VOD/local/VOD, FFmpeg thật, resolver thay bằng đường file. |
| Inline Python error/alias probes | **Alias PASS; failure safety FAIL**,probe command exit0 | `current_behavior_probes.json`; exit1+loopFalse che lỗi, exit1+loopTrue restart không budget. |
| `python results/readiness_audit/local_pipeline_smoke.py` | **Functional smoke PASS theo JSON**,shell wrapper exit1 | `current_local_pipeline.txt`, `local_pipeline.json`; native stderr FutureWarning bị PowerShell ghi error stream; pipeline vẫn hoàn tất,9frame/model load1/stop sạch. Không coi exit-code là0. |

Test mới `test_youtube_vod_ffmpeg.py` có9 methods (một method gộp yêu cầu4&5), đã chạy trong71tests. `test_10_existing_youtube_live_stream_remains_functional` chỉ kiểm command và diagnostics chưa start; không xác nhận YouTube Live hoạt động. Fake pipe không có blocking lock như real buffered stdout, do đó fake cleanup test không chứng minh stop an toàn khi network stall. E2E tracking dùng detection mô phỏng, không phải accuracy/GPU test; local app smoke mới là YOLO thật trên CPU.

Warnings: Starlette HTTPX integration, AnyIO BlockingPortal deprecated; supervision ByteTrack future removal0.31. Không sửa test để pass.

**Historical evidence, không gán cho bản VOD mới:** `vod_smoke.json` có5frame Googlevideo thật, nhưng chạy reader OpenCV trước khi thay FFmpeg. `pytest_final.*`61pass/1fail thuộc snapshot trung gian, không phải current result. Các Live probes trong `probes.json` vẫn hữu ích vì file Live/resolver không đổi; các entry VOD/alias cũ đã bị supersede.

**NOT VERIFIED:** YouTube network→FFmpeg VOD mới→AI→browser toàn chuỗi; repeated network switch; long Live;429/403 thật; signed expiry; browser visual rendering; Linux zombies; clean Colab dependencies/Node-EJS; CUDA; InsightFace model thật; memory stability dài hạn. Không cần thêm request YouTube để xác nhận blocker đã thấy qua deterministic probe.

## 8. Regression Check

| Thành phần | Kết quả hiện tại |
|---|---|
| Local MP4 | Không thấy regression trong6 source tests và local AI smoke. Diagnostics mở rộng, decode/EOF code không đổi. Invalid/empty-loop risk là tồn tại trước. |
| YouTube Live | File không đổi, tests pass; không chứng minh end-to-end Live. R4–R7 vẫn có. VOD import helper từ Live không tạo pipeline mới. |
| CameraManager | Constructor mismatch snapshot trước đã hết. Actual FFmpeg fixture đọc qua manager được. Source-switch generation và cleanup atomicity chưa đạt. |
| API | `source_type` alias đã sửa cả hai lớp. Proxy timeout/validation/offline fallback còn rủi ro, không bị alias fix xử lý. |
| UI | Local telemetry/MJPEG tiếp tục, JS không đổi. Browser visual và network source-switch feedback NOT VERIFIED; stale frame/source label mismatch vẫn có thể xảy ra. |
| YOLO | Code không đổi; current local smoke constructor1, inference9frame CPU. GPU NOT VERIFIED. |
| ByteTrack | Unit/E2E pass, app reset khi camera ID đổi. Dependency warning còn, identity accuracy trên người thật NOT VERIFIED. |
| TargetMatcher | Tests pass; thêm reset ở manager không thay matching rules. Race source generation và reevaluation/cache risks còn. |
| Telemetry | VOD/local schema tốt hơn; Live schema/stream_health/cumulative counters chưa đồng nhất. Không gọi metric0 là đã khỏe. |
| VOD mới | Thay OpenCV bằng FFmpeg thành công ở happy path, nhưng thêm cleanup subprocess và EOF-loop error regression R1–R3; pacing mặc định30fps không chứng minh native playback. |

## 9. Readiness Verdict

**NOT READY.**

71tests pass xác minh được constructor/API/reader happy path và nhiều thành phần AI/UI. Tuy nhiên VOD mới coi exit lỗi là EOF, loop bỏ qua retry budget; cleanup VOD/Live có thể kẹt trước terminate; Live còn spawn-after-stop, stale timestamp và429 decoder không vào cooldown chung. Các vấn đề này liên quan trực tiếp đến nguồn không dừng, nguồn trùng và request churn, nên không thể chọn READY chỉ từ test pass.

Cần sửa tối thiểu lifecycle/cancellation, phân loại EOF/error và shared429 policy, rồi bổ sung kiểm thử các failure path tương ứng; tiếp theo mới kiểm tra clean Colab, GPU, VOD network end-to-end và đánh giá lại controlled Live. Audit này không triển khai các sửa đổi đó và không chạy Live dài hạn.
