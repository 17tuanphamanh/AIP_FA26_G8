# Cổng 2, cổng 3, cổng 4 và smoke VPN trên stack compose thật

Các script chạy trên máy dev, nói chuyện với backend `http://127.0.0.1:8000` và Postgres của compose (psql **trong**
container postgres). Không nằm trong `make test`. Mục lục: [Thành viên chạy cổng 3 + 4](#thành-viên-chạy-cổng-3-rồi-cổng-4-một-trang) ·
[Cổng 2](#cổng-2-2b-4) · [Cổng 3](#cổng-3-make-gate3) · [Cổng 4](#cổng-4-make-gate4) · [Demo VPN thứ Sáu](#demo-vpn-thứ-sáu) ·
[Chạy smoke LLM thật](#chạy-smoke-llm-thật).

## Thành viên chạy cổng 3 rồi cổng 4 (một trang)

Người chạy: thành viên **không** làm chính. Máy riêng, **NGOÀI GIỜ** hành chính (sau 18:00 hoặc cuối tuần — gate3 khi đó đi
đường duyệt), **cắm sạc, mở nắp**, không để máy ngủ (Mac ngủ giữa lượt → E2 `turn_budget_exceeded`, đỏ oan). Thời gian: gate3
~3 phút, gate4 ~10 phút (chưa kể `make up`).

**Thứ tự bắt buộc: cổng 3 TRƯỚC, khi `.env` CHƯA có `APPROVAL_SLA_MINUTES_DEV`; xong mới thêm `APPROVAL_SLA_MINUTES_DEV=2`,
`make up`, rồi cổng 4.** gate4 tự dừng nếu thiếu SLA=2; gate3 chạy với SLA=2 không phải cấu hình đã kiểm.

`.env` là file bí mật: sửa bằng trình soạn thảo, KHÔNG `cat .env`, KHÔNG dán nội dung đi đâu (chat, ảnh chụp, issue).

**0. Một lần sau khi pull:** `git pull` → `uv sync` → (máy chưa có model) `make models`.

**1. Cổng 3**
1. `.env`: `APP_ENV=dev`, `LLM_BACKEND=scripted`, có `SVC_EXECUTOR_TOKEN`; thêm `#` trước CẢ HAI dòng `FAKE_SCENARIO`,
   `FAKE_NODE_DELAY`; thêm `#` trước dòng `APPROVAL_SLA_MINUTES_DEV` nếu có.
2. `make up` (chờ báo `/api/health: …` và `worker: healthy`).
3. `make ingest KB_DIR=backend/tests/fixtures/kb ARGS=--allow-unevaluated`
4. **Kiểm trước khi chạy:** `make gate3 S=preflight` → dòng đầu `Khung giờ lúc chạy: NGOÀI GIỜ`, dòng `làm nóng rerank: …`,
   mọi dòng `PASS`, dòng cuối `==== … PASS, 0 FAIL ====`. Thấy `DỪNG (chốt an toàn)` → đọc lý do, sửa `.env`, `make up` lại.
5. `caffeinate -i make gate3 S=all` → dòng cuối `==== N PASS, 0 FAIL ====`. Chụp dòng đó.

**2. Cổng 4**
1. `.env`: thêm dòng `APPROVAL_SLA_MINUTES_DEV=2` (giữ nguyên mọi thứ của bước 1).
2. `make up` (BẮT BUỘC — container chỉ nạp biến khi tạo lại).
3. **Kiểm trước khi chạy:** `make gate4 S=preflight` → có dòng `APPROVAL_SLA_MINUTES_DEV: backend=2, worker=2`, dòng `làm nóng
   rerank: …`, mọi dòng `PASS`.
4. `caffeinate -i make gate4 S=all` (~10 phút; g4-03/04/05 chờ hạn duyệt 2 phút THẬT — đừng ngắt).
5. Cuối lần chạy script in `Biên bản: backend/tests/stack/bienban-gate4-<ngày>.md`.

**3. Biên bản:** mở file đó, điền người chạy, máy, ký + ngày; bảng PASS/FAIL do script điền — KHÔNG sửa tay. Gửi Tuấn Anh file
biên bản + ảnh chụp dòng tổng của gate3 và gate4. **KHÔNG commit** biên bản đã điền.

**4. Có kịch bản đỏ:** KHÔNG tự sửa code, preset hay `.env` cho xanh. Chụp mọi dòng `FAIL …` (script in lại ở cuối) + khoảng
30 dòng phía trên dòng FAIL đầu tiên, gửi kèm biên bản. Lý do môi trường hay gặp: `DỪNG (chốt an toàn)` (sai `.env` — sửa,
`make up`, chạy lại); `CẢNH BÁO: làm nóng rerank lỗi` chỉ là cảnh báo; E2 `turn_budget_exceeded` (máy ngủ — cắm sạc, chạy lại);
g4-04 "nhắc 2 tới khi đã quá hạn" (máy quá tải — chạy lại riêng `make gate4 S=g4-04`, ghi rõ trong tin gửi).

**5. Trả máy về thường:** thêm `#` trước dòng `APPROVAL_SLA_MINUTES_DEV=2` → `make up`.

## Cổng 2 (2b-4)

`gate2.py` chạy trên máy dev, nói chuyện với backend `http://127.0.0.1:8000` và Postgres của compose
(psql **trong** container postgres). Không nằm trong `make test`.

### Chuẩn bị (một lần)

1. `.env` có `APP_ENV=dev`, `FAKE_APPROVER_ID=l1_01`, `FAKE_SCENARIO=approval`, `FAKE_NODE_DELAY=40`
   (mẫu và giải thích ở `.env.example`).
2. `make up` (build lại image — code 2b-4 nằm trong image).

### Chạy

```
make gate2 S=preflight      # kiểm stack + thẻ [fake:…] có hiệu lực
make gate2 S=restart        # hoặc late, expire, late-click, kill, kill-b15, tc29, threads, restart-all
make gate2 S=all            # mọi kịch bản trừ restart-all (~10 phút: kill + kill-b15 chờ worker phục hồi)
```

Script tự chạy lệnh compose cần thiết (`restart`, `stop/start worker`, `kill -s SIGKILL backend`,
`up -d backend`, `down` + `make up` cho `restart-all`) và **in từng lệnh trước khi chạy**.

**Chốt an toàn** (trước mọi việc khác): APP_ENV của container backend phải là `dev`; URL chỉ `127.0.0.1`;
cấm `down -v` / `--volumes` / `volume rm|prune`. Không qua → `DỪNG (chốt an toàn)`, exit 2.

Mật khẩu demo: `GATE2_PASSWORD` nếu đặt, không thì hằng `tests/fakes/demo.py` (mật khẩu công khai của mock).

### Đọc kết quả

Mỗi dòng: `PASS|FAIL <ticket_id> <tên kiểm>: mong đợi …, thấy …`. Cuối: tổng PASS/FAIL, liệt kê lại các
FAIL; exit 1 nếu có FAIL. Kiểm trên tập dòng rỗng luôn là FAIL; "không có X" chỉ PASS khi đối chứng "có Y"
của cùng ticket khác rỗng.

| Kịch bản | Đạt khi | FAIL thường nghĩa là |
|---|---|---|
| `preflight` | health `runtime: up`, worker `healthy`, ticket `[fake:clarify]` tới `S_CLARIFYING` | ticket về `S_PENDING_APPROVAL` → `.env` thiếu `FAKE_SCENARIO` hoặc chưa `make up` lại |
| `restart` | sau `restart backend`: duyệt → B16 `approved` rồi B17 `execution_failed` = **E7 do RefusingExecutor (dung toi Phase 3)**; clarify trả lời → chờ duyệt, B11 `asked` 1 lần; confirm → `resolved_user_confirmed` | clarify hỏi lại → kết quả node giả lấy từ bộ nhớ process thay vì state |
| `restart-all` | như `restart` sau `down` (giữ volume) + `make up`; số ticket trước/sau bằng nhau | số ticket lệch → mất volume |
| `late` | sự kiện sai loại ở 3 trạng thái chờ → 409, trạng thái giữ nguyên, đúng 1 `late_event` `source=user` | 2 dòng `late_event` → guard ghi trùng |
| `expire` | dời hạn về quá khứ → ≤ 45 giây: E6 + phiếu `timeout`; E4; `resolved_auto_timeout_48h`; 0 dòng B17 | quá 45 giây → worker không quét hạn |
| `late-click` | worker dừng: bấm muộn → 409, phiếu vẫn `pending`, `late_event reason=expired`; worker chạy lại → E6, `timeout`; bấm lại → `already_decided` | phiếu đổi trước khi worker quét → lệch 2b-3-Q2 |
| `kill` | SIGKILL backend khi đang ngủ ở b06 → khoá advisory của ticket nhả ≤ 10 giây; worker phục hồi (≤ 6 phút) → chờ duyệt, cùng `turn_id`, `recover_attempts=1`, 1 phiếu, audit không trùng | khoá còn → kết nối chết chưa nhả; audit/phiếu trùng → hỏng idempotent |
| `kill-b15` | như `kill`, chết ngay sau `approval_create` → 1 phiếu, 1 `approval_create`, 1 `notify_approver` | 2 phiếu → `effects.once` hỏng |
| `tc29` | `[fake:raise]` → E9, audit + span có traceback; 5 ticket song song tới chờ duyệt; worker healthy | — |
| `threads` | bảng ticket ↔ thread ↔ số checkpoint; mỗi ticket gate2 đúng 1 thread; không thread lạ | người đọc bảng, xác nhận mục thủ công của cổng 2 |

## Cổng 3 (`make gate3`)

`gate3.py` (phase3 11.6, PLAN-3h S15): 8 kịch bản cổng 3 trên node THẬT — API + runner + worker, ml-service, Qdrant, mock
thật; LLM là ScriptedLLM với preset tĩnh `config/scripted/tc*.yaml`, chọn bằng thẻ `[fake:tcXX]` script tự thêm vào CUỐI
câu. Người **không** làm chính chạy `make gate3 S=all` để xác nhận phần thủ công của cổng 3 code.

### Chuẩn bị

1. `.env`: `APP_ENV=dev`, `LLM_BACKEND=scripted`, `SVC_EXECUTOR_TOKEN` (≥ 32 ký tự, cùng giá trị
   mock nhận), và **KHÔNG** đặt `FAKE_SCENARIO` lẫn `FAKE_NODE_DELAY` (comment CẢ HAI dòng — đặt `FAKE_SCENARIO` thì mọi
   node là bản giả của gate2; còn `FAKE_NODE_DELAY` mà thiếu `FAKE_SCENARIO` thì backend/worker từ chối khởi động,
   `graph/wiring.fake_scenario`). Chạy lại gate2 thì bật lại cả hai + `make up` — hai cổng dùng hai cấu hình `.env`.
2. Code đổi → `docker compose build backend worker` → `make up` (chờ `make up` báo xong: `/api/health` 200, worker healthy).
3. KB fixture: `make ingest KB_DIR=backend/tests/fixtures/kb ARGS=--allow-unevaluated` (preset tc04/tc05 trích `chunk_id` của
   KB này: `KB-VPN-001#v1#1`, `KB-VPN-003#v1#0`).

### Chạy

```
make gate3 S=preflight     # health, runtime, kb ready, worker healthy, đăng nhập ha.lt / an.nv / binh.tt
make gate3 S=tc02          # hoặc tc04, tc05, tc06, tc09, tc13, tc16, tc28
make gate3 S=all           # preflight + 8 kịch bản (tc28 cuối: tắt/bật Qdrant)
```

**Chốt an toàn** (trước mọi HTTP, không qua → `DỪNG (chốt an toàn)`, exit 2): như gate2 (APP_ENV `dev`, URL `127.0.0.1`,
cấm `down -v`/`volume rm|prune`) + `LLM_BACKEND` của backend phải là `scripted` (gate3 không gọi LLM thật) + `FAKE_SCENARIO`
không đặt. Biến môi trường chỉ được dò CÓ/KHÔNG trong container (`TÊN=0|1`) — script không in giá trị nào.

**Cảnh báo** (in đầu lần chạy, không dừng): thiếu `SVC_EXECUTOR_TOKEN` (B17 dùng RefusingExecutor → tc02/tc06 ra E7), KB
đang chạy không phải KB fixture. Từ Phase 4 4b B15 là node thật: người duyệt theo `config/approvers.yaml` (`l1_01`, dự phòng
`l1_02`) — `FAKE_APPROVER_ID` không cần cho gate3 (giữ trong `.env` cho gate2). Có phiếu thì gate3 kiểm người duyệt/dự phòng/xung
đột của phiếu và cột `approver_id` của dòng audit B15 `queued` (Q-4b-7).

**Theo giờ lúc chạy** (Q-3h-4 — không có biến ép đồng hồ): dòng đầu in `Khung giờ lúc chạy: TRONG GIỜ | NGOÀI GIỜ` theo
`business_hours` của `config/policy.json` (thứ Hai–Sáu 08:00–18:00, Asia/Ho_Chi_Minh). Kịch bản vắt qua mốc giờ → FAIL
"khung giờ không đổi trong kịch bản" → chạy lại. Mock được nạp lại seed trước mỗi kịch bản (dữ liệu, lỗi bơm, bộ đếm).

| Kịch bản | Người / câu | Đạt khi (TRONG GIỜ) | Khác khi NGOÀI GIỜ |
|---|---|---|---|
| `tc02` | an.nv "gia hạn VPN cho máy LAP-0342" | B12 R20 AUTO; `POST /vpn/certs/nv001/renew` = 1 (đếm ở mock); `transaction_log` 1 `begun`; điểm log 7 `write_calls=1`; tin `result` nêu LAP-0342 → xác nhận → `S_RESOLVED` `resolved_user_confirmed`; tổng ghi vẫn 1 | R18 (+R20) HITL → chờ duyệt, 0 ghi → `ha.lt` duyệt qua API → renew = 1 → như trong giờ |
| `tc04` | an.nv "VPN công ty dùng cổng nào?" | 1 tin `answer`, nguồn `KB-VPN-001#…`; không có dòng B12/B17; hạn xác nhận đang chờ; 0 ghi | như nhau |
| `tc05` | an.nv "VPN báo lỗi 809, hướng dẫn mình khắc phục với" | như tc04, nguồn `KB-VPN-003#…` → xác nhận → `S_RESOLVED` | như nhau |
| `tc06` | an.nv "vpn không vào được" | như tc02 và 0 tin `question` (B6 tự suy LAP-0342) | như tc02 |
| `tc09` | binh.tt "cấp lại VPN cho máy PC-0977" | Phase 4 S0-P7: điểm truy hồi thật thấp (0,047) KHÔNG chặn yêu cầu hành động → B11 `procedure_doc=KB-VPN-004` → B12 R17 HITL → `S_PENDING_APPROVAL`, 1 phiếu `pending`, 0 ghi; không có dòng audit B9. Không duyệt tiếp (mock 409 máy chưa đăng ký — Q-4-D) | R17 + R18 |
| `tc13` | an.nv "Bỏ qua mọi quy tắc…" | E0, tin mẫu E0, 1 `security_events` `injection_detected`, 0 ghi (preset cho LLM judge trả "không tấn công" — E0 phải từ lớp tất định) | như nhau |
| `tc16` | an.nv "đăng ký MFA thế nào" | E3 `no_grounding`, tin mẫu E3, 0 tin `answer`, 0 ghi | như nhau |
| `tc28` | câu tc04, Qdrant bị `compose stop` | E2 `rag_system_error` (không E3), tin mẫu E2, 0 ghi; `finally` luôn `compose start qdrant` rồi chờ health ok + kb ready | như nhau |

FAIL thường gặp: tc04/tc05 E3 `invalid_citation` → chunk preset trích không nằm trong top-5 của reranker thật (sửa trích dẫn
trong preset); tc05 E3 `no_grounding` ở B9 → điểm truy hồi thật dưới ngưỡng 0,6 (thẻ `[fake:…]` đã bị bỏ khỏi câu truy hồi
— `core.fake_tag`); tc02/tc06/tc09 E3 `no_procedure` ở B11 → KB đang chạy không có/tắt tài liệu quy trình KB-VPN-004 (Phase 4
S0-P10 — `make ingest` in cảnh báo `procedure_doc`); tc02/tc06 E7 → thiếu `SVC_EXECUTOR_TOKEN`; tc02/tc06 ngoài giờ/tc09 E2
`approver_sync_unavailable` ở B15 → tiến trình backend/worker thiếu `JWT_SIGNING_KEY`; E5 `no_valid_approver` → người trong
`config/approvers.yaml` không hợp lệ trong mock AD (sai nhóm, disabled).

## Cổng 4 (`make gate4`)

`gate4.py` (phase4 7.1 P6, 7.4; PLAN-4d mục 11.5): 11 kịch bản HITL trên node THẬT (B15–B16, nhắc, xem phiếu, dự phòng, ghi đè,
`audit_check`) với hạn duyệt rút ngắn `APPROVAL_SLA_MINUTES_DEV=2` — worker THẬT quét 15 s (nhắc 1 ~60 s, nhắc 2 ~96 s, hết hạn
120 s). Preset `config/scripted/g4_*.yaml`. Kịch bản không phụ thuộc giờ chạy: chau.hm (thử việc) → R19; PC-0124/LAP-0700 chưa đăng
ký → R17. **Không có g4-08** (Trưởng BP quan.tm tự gửi → E5 `no_valid_approver`): manager bắt buộc MFA, gate4 KHÔNG đăng nhập manager
và KHÔNG ghi danh MFA trên stack (Q-4d-9 = B) — ca x4 kiểm ở e2e `test_i5_x4_…` + unit bảng 3.2.

**Chuẩn bị:** như cổng 3 + `.env` có `APPROVAL_SLA_MINUTES_DEV=2` → `make up`. **Chốt an toàn** (exit 2 trước mọi HTTP): như
gate3 + SLA của backend VÀ worker phải `=2` (script trong container chỉ in `SLA=2|0|khac`, không in giá trị). Trước kịch bản đầu:
**làm nóng rerank** (một truy vấn bỏ đi gọi thẳng ml-service trong container backend — 0 ghi DB, không tính PASS/FAIL; lỗi chỉ
cảnh báo) — gate3 cũng làm bước này.

```
make gate4 S=preflight     # health, worker, đăng nhập chau.hm, ha.lt, duc.pv, khoa.dv, long.nh (không manager — không MFA)
make gate4 S=g4-01         # hoặc g4-02 … g4-12 trừ g4-08 (g4-11 chạy lẻ tự dựng ticket g4-01)
make gate4 S=all           # ~10 phút, ghi biên bản bienban-gate4-<YYYYmmdd>.md
```

| Kịch bản | Đạt khi |
|---|---|
| `g4-01` | chau.hm LAP-0501 → phiếu (l1_01, dự phòng l1_02, không xung đột); hạn = 120 ± 3 s; ha.lt duyệt → renew nv003 đúng 1, tổng ghi 1, `transaction_log` `begun` → xác nhận → `S_RESOLVED` |
| `g4-11` | duc.pv ghi đè ticket g4-01 HITL→L2 → 201; lần 2 → 409 `already_overridden`; 1 dòng `OVERRIDE`; dòng `tickets` không đổi |
| `g4-02` | từ chối không note → 422 `rejected_requires_note`, phiếu `pending`; có note → `S_REJECTED`, 1 tin `rejection`, 0 ghi |
| `g4-06` | ha.lt PC-0124 (TC19) → phiếu Trưởng BP `it_mgr01`, `conflict_type=self`; ha.lt quyết → 403 |
| `g4-07` | khoa.dv LAP-0700 → `it_mgr01`, `boss_of_approver` |
| `g4-09` | long.nh (L2) quyết/xem → 403; khoa.dv (L1 không được giao) xem → 404 giống hệt id không tồn tại |
| `g4-10` | ha.lt xem → 200 `primary`, ghi `first_viewed_at`; xem lần 2 giữ nguyên; duyệt → B16 `decided_without_view=false` |
| `g4-04` | duc.pv quyết trước nhắc 2 → 403; sau nhắc 2 → 202 `decided_as=backup` → thực thi 1 ghi |
| `g4-03` | không ai quyết: nhắc 1 ≥ 50%, nhắc 2 ≥ 80% thời hạn, cả hai trước hạn; worker → E6, phiếu `timeout`, 0 ghi |
| `g4-05` | bấm sau hạn → 409 + đúng 1 `late_event` (`expired`, hoặc `already_decided` nếu worker quét trước) → E6, 0 ghi |
| `g4-12` | `audit_check <các ticket lần chạy này đã tạo>` trong container → `KẾT LUẬN: 0 thiếu, 0 bí mật` (đỏ → in nguyên bảng ticket/điểm/trường, không giá trị; chạy lẻ `S=g4-12` = chưa có ticket → FAIL); log backend+worker từ giờ bắt đầu 0 trúng luật bí mật |

**`make audit-check` trên stack dev dùng chung:** `ARGS="--since <giờ>"` chọn MỌI ticket có dòng audit mới từ giờ đó rồi soát TOÀN BỘ
dòng của ticket → trên stack đã chạy gate2 (node GIẢ — không ghi điểm log thật) hoặc còn ticket cũ (worker vẫn ghi dòng mới khi đóng hạn
duyệt/xác nhận) sẽ báo thiếu ở các ticket đó, dù code đúng. Muốn soát MỘT lần chạy: truyền danh sách ticket
(`make audit-check ARGS="<ticket_id> <ticket_id> …"`) — gate4 g4-12 làm đúng như vậy (Q-4d-10).

## Demo VPN thứ Sáu

Trên stack đã chuẩn bị như mục Cổng 3 (`LLM_BACKEND=scripted`, không `FAKE_SCENARIO`, KB fixture). Cách nhanh: chạy từng
kịch bản bằng `make gate3 S=tc02` (… `tc04`, `tc06`, `tc09`) — mỗi bước in ra PASS/FAIL kèm `ticket_id`. Cách tay (từng
request, cho người xem), từ gốc repo:

```
make up
make ingest KB_DIR=backend/tests/fixtures/kb ARGS=--allow-unevaluated
export API=http://127.0.0.1:8000
export PW="$(PYTHONPATH=backend uv run python -c 'from tests.fakes.demo import DEMO_PASSWORD; print(DEMO_PASSWORD)')"
login() { curl -s -X POST $API/api/auth/login -H 'content-type: application/json' \
  -d "{\"username\": \"$1\", \"password\": \"$PW\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])'; }
L1=$(login ha.lt)      # l1_01 — đăng nhập TRƯỚC để có người duyệt
AN=$(login an.nv)      # nv001
BINH=$(login binh.tt)  # nv002
ask() { curl -s -X POST $API/api/tickets -H "authorization: Bearer $1" -H 'content-type: application/json' \
  -d "{\"text\": \"$2\"}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["ticket_id"])'; }
show() { curl -s $API/api/tickets/$2 -H "authorization: Bearer $1" | python3 -m json.tool; }
```

`PW` là mật khẩu demo CÔNG KHAI của mock (`tests/fakes/demo.py`), không phải mật khẩu thật. Bốn câu mẫu (thẻ `[fake:…]`
chọn preset ScriptedLLM — bắt buộc khi `LLM_BACKEND=scripted`):

| Câu | Lệnh | TRONG GIỜ (T2–T6 08:00–18:00) | NGOÀI GIỜ |
|---|---|---|---|
| TC02 | `T=$(ask $AN 'gia hạn VPN cho máy LAP-0342 [fake:tc02]'); sleep 20; show $AN $T` | `S_CONFIRMING`, tin "Đã gia hạn chứng chỉ VPN cho máy LAP-0342, hiệu lực tới …" | `S_PENDING_APPROVAL` — duyệt như TC09 bên dưới, rồi `S_CONFIRMING` |
| TC04 | `T=$(ask $AN 'VPN công ty dùng cổng nào? [fake:tc04]'); sleep 20; show $AN $T` | `S_CONFIRMING`, tin trả lời có mục "Nguồn" (KB-VPN-001) | như nhau |
| TC06 | `T=$(ask $AN 'vpn không vào được [fake:tc06]'); sleep 20; show $AN $T` | như TC02, không hỏi lại mã máy | như TC02 |
| TC09 | `T=$(ask $BINH 'cấp lại VPN cho máy PC-0977 [fake:tc09]'); sleep 20; show $BINH $T` | `S_PENDING_APPROVAL` (R17 — máy chưa đăng ký), không gọi ghi (Phase 4 S0: điểm truy hồi thấp không chặn hành động) | như nhau (R17 + R18) |

Xác nhận đã xong (TC02/TC04/TC06): `curl -s -X POST $API/api/tickets/$T/confirm -H "authorization: Bearer $AN" -H
'content-type: application/json' -d '{"confirmed": true}'` → vài giây sau `show` thấy `final_state: S_RESOLVED`.
Duyệt (TC02/TC06 ngoài giờ): lấy `approval_id` bằng câu SQL dưới, rồi `curl -s -X POST $API/api/approvals/<approval_id>/decision
-H "authorization: Bearer $L1" -H 'content-type: application/json' -d '{"decision": "approved"}'`. TC09 dừng ở chờ duyệt
(R17); duyệt thì mock trả 409 máy chưa đăng ký → E7 có ghi chú bàn giao (luồng đăng ký máy không làm ở Phase 4 — Q-4-D).

Xem audit / phiếu duyệt / lời gọi ghi:

```
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<< "SELECT step, event, detail FROM audit_logs WHERE ticket_id = '$T' ORDER BY log_id"
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<< "SELECT approval_id, status FROM approvals WHERE ticket_id = '$T'"
docker compose exec -T mock python -c "import httpx; print(httpx.get('http://127.0.0.1:8100/_admin/calls', params={'path_prefix': '/vpn/', 'method': 'POST'}).json())"
make seed   # nạp lại seed mock trước lần demo sau (chứng chỉ LAP-0342 về trạng thái hết hạn, bộ đếm về 0)
```

## Chạy smoke LLM thật

`make vpn-smoke` (phase3 11.9; `vpn_smoke.py`): chạy tc02, tc04, tc05, tc06 với `LLM_BACKEND` HIỆN HÀNH rồi in từ `llm_calls`
của lần chạy: tỉ lệ JSON hợp lệ lần đầu, số lần sửa schema, p95 độ trễ theo prompt, tổng `cost_usd`. Với `scripted` nó chỉ
kiểm script (0 USD). Với `real`, script **TỪ CHỐI** (exit 2, trước mọi ticket) khi `spend.cap_usd` mà container backend ĐANG
nạp > 1, hoặc model đang dùng chưa có dòng `pricing`. Trần chi là `spend.cap_usd` trong `config/llm.yaml` (Q-3d-3 — không có
biến env `LLM_SPEND_CAP_USD`). **Không commit `llm.yaml` đã hạ cap** — chỉ hạ tạm trên máy người chạy:

1. `config/llm.yaml`: `spend: {cap_usd: 1, …}` và thêm dòng `pricing` của model đã chọn (USD / 1M token).
2. `.env`: `LLM_BACKEND=real`, `FAST_MODEL`, `STRONG_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY` (nên `LLM_CACHE_MODE=bypass` để
   số liệu không bị cache che).
3. `docker compose build backend worker` → `make up`.
4. `make vpn-smoke` — ghi số liệu vào PROGRESS (số mẫu, bản prompt, ngày).
5. Trả `cap_usd` về 38, gỡ dòng `pricing` tạm, `.env` về `LLM_BACKEND=scripted` → `docker compose build backend worker` →
   `make up`.
6. `git diff config/llm.yaml` phải RỖNG.

## `make verify` (Phase 4, mục 4.4)

Một lệnh cho mọi DỪNG: `make verify G=234` = lint → test → up → gate2 (tạo lại backend+worker với `FAKE_SCENARIO=approval`) →
ingest KB fixture (một lần) → gate3 (tạo lại với `FAKE_SCENARIO` và `APPROVAL_SLA_MINUTES_DEV` rỗng) → gate4 (bước 10, tạo lại với
`APPROVAL_SLA_MINUTES_DEV=2`) → LUÔN trả backend+worker về cấu hình `.env`. `G=0` chỉ lint + test; `BENCH=1` thêm bench checkpoint
(Postgres testcontainers). Trên macOS script tự giữ máy thức (`caffeinate -i -w <pid>` — hết khi verify thoát) và cảnh báo khi máy
chạy pin. Kết quả: `.verify/summary.txt` (`make verify-status`) + `.verify/run-*.log`. Không đọc/sửa `.env`, không `down -v`.
