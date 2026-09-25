# Thiết kế Database SQL — AI Agent IT Service Desk L1 + HITL

> **Hiện hành (25/09/2026): 22 bảng.** File này mô tả 17 bảng gốc (3 vòng review). Bộ `build/` thêm 5 bảng (`security_events`, `llm_cache`, `wait_deadlines`, `side_effects`, `child_notices`), mở rộng 6 bảng và thêm 3 role Postgres — xem `build/nen-tang/P7-db-thay-doi.md`. Khi code, `schema.sql`/`models.py` phải theo P7. **Cập nhật 26/09/2026:** `schema.sql`/`models.py` gốc gửi qua chat đã mất; 17 bảng được dựng lại khi làm Phase 1a — nguồn sự thật hiện nay là `backend/app/db/models.py` + migration `0001` trong repo, bảng đối chiếu cột → tài liệu ở `backend/app/db/README.md`. Khác biệt so với file này: xem P7 mục 3 "Chốt khi hiện thực Phase 1a".

Trạng thái: đã qua BA vòng tự review (2 vòng sửa lỗi domain-value/PK + 1 vòng thiết kế lại kiến trúc bảng `tickets`), kiểm thử lại toàn bộ trên PostgreSQL 16 sau mỗi vòng (raw SQL + SQLAlchemy ORM), pass hết. Nguồn: `NGU-CANH-DAY-DU.md`, `huong-dan-xay-dung-he-thong-2.md`, `bo-sung-tang-Monitor-M9.md`.

File giao: `schema.sql` (DDL PostgreSQL thuần) và `models.py` (SQLAlchemy 2.0 ORM ánh xạ 1-1) — đã gửi cho người dùng qua chat, chưa có trong Project docs vì là code, không phải tài liệu đọc.

## Nguyên tắc chú thích dùng xuyên suốt

- **[CHỐT]** — tên bảng/trường lấy trực tiếp từ tài liệu gốc (TicketState, Action, 8 điểm log, tầng Monitor M9).
- **[ĐỀ XUẤT]** — không có trong tài liệu, nhưng cần thiết để CSDL vận hành được (vd: `users`, chi tiết `policy_rules.condition`).
- **[SUY LUẬN — cần chốt lại]** — suy ra từ nhiều đoạn rải rác, chưa có định nghĩa tường minh duy nhất. Riêng nhất: thứ tự ưu tiên hàng đợi L2 (bảng `exit_code_priority`) — vị trí chính xác của E5/E9 so với "hạ tầng"/"cao" trong chuỗi "Rất cao → an ninh → có SLA → hạ tầng → cao → thường" (mục 16.4) chưa được tài liệu chốt 100%, cần xác nhận lại với nhóm/GVHD.

## Vòng review thứ ba (2026-09-24) — thiết kế lại kiến trúc bảng, không chỉ sửa lỗi domain-value

**Vấn đề nêu ra:** "các bảng thiết kế chưa được hợp lí và gắn liền với code dự án cho lắm". Sau khi đối chiếu lại kỹ với mục 3 (TicketState), mục 8.2 (LangGraph checkpoint), mục 9.1/9.2 (Ticket vs Audit log), và mục 17.2 (chính sách lưu trữ 90 ngày), vấn đề thật sự không phải "thiếu bảng" mà là **một dữ kiện có nhiều hơn một chủ sở hữu**: bảng `tickets` bản trước là `TicketState` làm phẳng — chứa cả working state (Action đang diễn giải, diagnostics, 14 trạng thái, bộ đếm vòng lặp) lẫn dữ liệu quyết định (risk/approval) — trùng lặp với cả LangGraph checkpoint (đã tự động lưu working state) lẫn `audit_logs`/`approvals` (đã là chủ sở hữu đúng của dữ liệu quyết định). Khi ba nơi có thể lệch nhau, code không còn biết tin nơi nào.

**Nguyên tắc sửa — phân loại dữ liệu theo tần suất thay đổi, không theo "có vẻ liên quan tới ticket":**

| Loại dữ liệu | Đổi bao nhiêu lần/ticket | Nơi lưu đúng |
|---|---|---|
| Trạng thái hiện tại (14 giá trị), Action đang diễn giải, diagnostics, retrieved_docs, hội thoại, bộ đếm vòng lặp | ~10-14 lần | LangGraph checkpoint — đọc qua `get_state(thread_id)`/`get_state_history(thread_id)` |
| Một quyết định/sự kiện tại B3/B6/B8/B12–14/B16/B17/B20 | 1 lần MỖI LẦN xảy ra (nhiều hàng/ticket) | `audit_logs` (append-only, 1 hàng/sự kiện) |
| Vòng đời phê duyệt cụ thể | 1 lần/lượt duyệt | `approvals` |
| Định danh + kết quả cuối cùng (mục 9.1 + B20) | Ghi 1 lần lúc tạo, hoặc 1 lần lúc đóng — không đổi sau đó | `tickets` |

Dữ liệu ghi-một-lần-tại-một-mốc-cố-định (vd `final_state`, `close_reason`, ghi đúng một lần ở B20) nhân đôi để tiện báo cáo là AN TOÀN — không ai còn sửa nó sau khi ghi. Dữ liệu đổi liên tục (14 trạng thái, Action đang diễn giải) nhân đôi CHẮC CHẮN lệch pha sớm muộn. Đây là ranh giới đã dùng để quyết định giữ/bỏ từng cột.

**Ba thay đổi cụ thể:**

1. **`tickets` thu hẹp từ 40+ cột xuống 21 cột** (16 cột nghiệp vụ + 5 cột thời gian/hệ thống): chỉ còn định danh (`ticket_id`, `parent_ticket_id`, `session_id`), người gửi snapshot (`requester_id/role/dept`), nội dung (`raw_request`, `intent`, `slots` — đúng mục 9.1), và kết quả cuối ghi một lần ở B20 (`final_state`, `exit_code`, `block_reason`, `close_reason`, `resolution_path`, `aggregate_status`, `auto_closed`, `total_turns`, `total_duration_seconds`). Bỏ toàn bộ `action_*` (7 cột), `risk_*`/`decided_by`/`policy_decision`/`matched_rule_id` (6 cột), `approver_*`/`approval_*`/`action_plan_hash` (5 cột, đã trùng y hệt bảng `approvals`), `diagnostics`/`tool_errors`/`tool_retry_count`/`retrieved_doc_ids`/`retrieval_score`/`retrieval_error` (6 cột), `missing_slots`, `clarification_turns`/`reasoning_loops`/`auth_failure_streak` (3 cột), và `state` (14 giá trị). **Hệ quả:** ablation theo `decided_by`/`matched_rule_id` (mục 6, 9) giờ cần một JOIN `tickets ⋈ audit_logs` (lọc step B12–B14) thay vì đọc thẳng cột trên `tickets` — đánh đổi nhỏ, một lần ở tầng truy vấn, để loại bỏ hẳn nguy cơ hai nguồn sự thật lệch nhau.
2. **Bỏ bảng `conversation_messages`** — hội thoại (`TicketState.conversation`) đọc qua LangGraph `get_state()`/`get_state_history()`. Lý do trực tiếp từ mục 17.2: chính sách xóa "hội thoại VÀ checkpoint" cùng lúc sau 90 ngày — một bảng SQL permanent riêng cho hội thoại sẽ vi phạm đúng chính sách đó (không có cơ chế xoá sau 90 ngày nào được thiết kế cho nó) và nhân đôi dữ liệu đã có sẵn trong checkpoint. Nhu cầu UI đã nêu (L2 "ghi chú bàn giao + hội thoại của ticket", mục 16.4) vẫn được đáp ứng đầy đủ qua checkpoint trong cửa sổ 90 ngày ticket còn hoạt động/mới đóng.
3. **Bỏ bảng `tool_registry`** (thêm ở vòng review thứ hai theo yêu cầu, nay xem lại) — chuyển thành registry khai báo bằng Python (vd `backend/app/tools/registry.py`), kiểm tra ngay lúc import. Lý do: (a) `input_schema_ref`/`output_schema_ref` trỏ tới class Pydantic chỉ tồn tại trong code — CHECK constraint SQL không xác nhận được class đó còn đúng tên, chỉ code (import-time) mới đảm bảo; (b) không tính năng UI nào trong tài liệu (mục 16.2–16.5) cần đọc/sửa tool registry qua API — khác hẳn `policy_rules` (Trưởng bộ phận IT sửa qua UI, mục 16.3); (c) cùng lý do đã áp dụng cho circuit breaker (mục 17.3) — cấu hình harness/runtime gắn chặt với code; (d) `audit_logs.tools_called` + `spans` (span_type='tool') đã đủ dữ liệu phân tích lỗi/độ trễ theo tool. Bất biến "tool ghi phải khai báo B17" chuyển từ CHECK constraint SQL sang unit test Python (assert lúc import).

**Một làm rõ (chỉ sửa comment, không đổi DDL):** `policy_rules` là bản mirror có cấu trúc phục vụ UI Trưởng bộ phận IT (sửa policy, xem lịch sử, quay lui — mục 16.3), được ghi đồng thời với `policy_versions` mỗi khi lưu policy mới. `policy_engine.evaluate()` KHÔNG query bảng này theo từng ticket (sai hợp đồng "chỉ nhận action và ctx", mục 6.2) — nó đọc `policy_versions.policy_json` (bản `is_current=TRUE`) đã nạp vào bộ nhớ process.

Toàn bộ lập luận chi tiết (kể cả bảng phân loại ở trên) đã được ghi thành comment trong `schema.sql` (mục "GHI CHÚ KIẾN TRÚC" cuối file) để hội đồng/GVHD đọc trực tiếp trong code khi cần.

## 17 bảng (sau vòng review thứ ba)

| Bảng | Vai trò | Trạng thái |
|---|---|---|
| `users` | Actor người: employee/l1/manager/l2 (Ma trận phân quyền mục 2.2) | ĐỀ XUẤT |
| `sessions` | user_id → session_id trong chuỗi định danh (mục 17.1) | CHỐT (khung) |
| `policy_versions` | Lịch sử phiên bản `policy.json`, phục vụ "quay lui" (mục 16.3) — nguồn sự thật engine đọc lúc runtime | ĐỀ XUẤT chi tiết hoá |
| `policy_rules` | Bản mirror có cấu trúc của `policy_versions.policy_json`, phục vụ UI Trưởng bộ phận IT — R01/R07/R12... PK `(rule_id, version_id)` | CHỐT khung + ĐỀ XUẤT cấu trúc `condition` |
| `kb_versions` | `kb_version` = hash(doc_id, version) mỗi lần ingest (mục 17.4) | CHỐT |
| `kb_documents` | Metadata tài liệu KB: loại yêu cầu, mức nhạy, bật/tắt... | CHỐT |
| `tickets` | Bản ghi nghiệp vụ LÂU DÀI (mục 9.1 + điểm log B20) — 21 cột, KHÔNG phải TicketState làm phẳng | CHỐT |
| `approvals` | B15/B16 — bảng `approvals` nêu tên trong tài liệu (mục 6); CHECK bắt buộc `note` khi `result='rejected'`; sở hữu riêng vòng đời phê duyệt | CHỐT |
| `transaction_log` | `class TransactionLog` rollback per-step, chỉ 2 giá trị `undone`/`undo_failed` (không có `not_attempted` ở cấp step) | CHỐT |
| `exit_code_priority` | Mapping E0–E9 → mức ưu tiên hàng đợi L2 (mục 16.4 + bổ sung E9) | SUY LUẬN — cần chốt lại |
| `escalations` | E0–E9 → L2 (mục 4.2, 6.4) | CHỐT khung + ĐỀ XUẤT `close_result` (tài liệu chỉ nói "3 kết quả", chưa đặt tên) |
| `audit_logs` | 8 điểm log bắt buộc (mục 9, 9.1, 9.2), append-only, CHECK domain-value đầy đủ — chủ sở hữu DUY NHẤT của mọi quyết định/sự kiện | CHỐT |
| `lineage` | Phiên bản policy/prompt/model/KB/calibrator/commit mỗi quyết định M5, B10 (mục 17.1) | CHỐT |
| `turns` / `spans` / `llm_calls` | Session/trace/lineage tầng Monitor (mục 17.1, 17.9.3) | CHỐT |
| `alerts` | Instance của "bảng luật cảnh báo" M9 (mục 17.9.3) | ĐỀ XUẤT (khung luật là CHỐT, bảng lưu instance là ĐỀ XUẤT) |

**Không còn là bảng SQL (đã bỏ ở vòng review thứ ba):** `conversation_messages` (→ đọc qua LangGraph checkpoint), `tool_registry` (→ Python declarative registry, `backend/app/tools/registry.py`).

**Dữ liệu KHÔNG nằm trong Postgres schema này (nhắc lại, không đổi từ trước):** working state đầy đủ của `TicketState` (Action đang diễn giải, diagnostics, hội thoại, 14 trạng thái, bộ đếm vòng lặp) — sống trong LangGraph `PostgresSaver` checkpoint, đọc qua `get_state(thread_id)`/`get_state_history(thread_id)`; circuit breaker (mục 17.3) — runtime state ngắn hạn, trong bộ nhớ process/Redis.

## Quyết định triển khai (không đổi kiến trúc, chỉ là lựa chọn kỹ thuật)

- CHECK constraint (VARCHAR) thay vì PostgreSQL native ENUM cho các trường "đang tiến hoá" — có tiền lệ E9 được bổ sung sau, `whitelist/blacklist` → `allow/approval_required/deny`. Alembic sửa CHECK dễ hơn `ALTER TYPE`.
- LangGraph `PostgresSaver` tự tạo bảng checkpoint riêng, không định nghĩa lại trong `schema.sql` — dùng chung một Postgres instance.
- Circuit breaker (mục 17.3) là trạng thái runtime ngắn hạn, không lưu DB.
- Tool registry (mục 17.3) là registry khai báo bằng Python, không lưu DB (xem vòng review thứ ba ở trên).
- `close_reason` dùng đúng 8 giá trị đã liệt kê tường minh trong tài liệu (mục 3): `resolved_user_confirmed`, `resolved_auto_timeout_48h`, `resolved_after_escalation`, `resolved_after_deny_review`, `rejected_by_approver`, `blocked_invalid_credentials`, `blocked_repeated_auth_failure`, `blocked_injection_detected`.

## Sửa đổi sau vòng tự review thứ hai (trước khi ghi bản này lần đầu)

1. **`policy_rules` đổi PK** từ `rule_id` đơn sang `(rule_id, version_id)` — tài liệu nói rule_id (R01, R07, R12) được giữ ổn định qua nhiều phiên bản chính sách, nghĩa là cùng rule_id có thể tái xuất hiện với `condition`/`decision` khác ở version mới; PK đơn cột sẽ vi phạm ràng buộc trong trường hợp đó.
2. **Bỏ FK cứng `tickets.matched_rule_id → policy_rules(rule_id)`** — giữ text + index (nay cột này chỉ còn tồn tại ở `audit_logs`, xem vòng review thứ ba). Nguồn sự thật để tái lập đúng cấu hình đã chạy (nguyên tắc lineage, mục 17.1) là `lineage.policy_version_id` + snapshot `policy_versions.policy_json`, không phải trạng thái *hiện tại* của `policy_rules`.
3. **Thêm CHECK constraint domain-value đầy đủ cho `audit_logs`** (intent, risk_level, decided_by, policy_decision, approval_result, rollback_status, final_state, exit_code, block_reason, close_reason) — trước đây chỉ có ở `tickets`, trong khi `audit_logs` mới là nguồn dữ liệu duy nhất cho ablation study và tầng Monitor.
4. **Thêm CHECK `approvals`**: `result IS DISTINCT FROM 'rejected' OR note IS NOT NULL` — đúng nguyên văn "khi từ chối, trường note là bắt buộc" (B16), ép ở DB thay vì chỉ ở tầng ứng dụng.
5. **Sửa `transaction_log.status`**: bỏ giá trị `not_attempted` — theo `class TransactionLog` (mục 5.3), khi `Action.reversible=False` thì `record()` không bao giờ được gọi nên không có row nào ở bảng này cho ticket đó, chứ không phải một row `status='not_attempted'`. Ý nghĩa đó chuyển sang `audit_logs.rollback_status` (điểm log #7, tổng hợp cấp ticket, có thêm `partial` theo 3 mức hoàn tác ở mục 5.3).
6. **Thêm bảng `tool_registry`** (mục 17.3, theo yêu cầu người dùng) — có CHECK ràng buộc "tool ghi phải khai báo B17 là bước được phép gọi". *(Đảo ngược ở vòng review thứ ba — xem ở trên — sau phân tích sâu hơn về chi phí đồng bộ tay DB↔code so với lợi ích thực tế.)*

## Đã kiểm thử

**Vòng 1 và vòng 2** (bản đầu và bản sau review sửa lỗi domain-value/PK): chạy sạch trên PostgreSQL 16. Vòng 2 kiểm thêm: `policy_rules` chèn được 2 version cho cùng `rule_id='R01'` (raw SQL + ORM); `approvals` reject đúng khi `result='rejected'` mà thiếu `note` (raw SQL + ORM, bắt được `IntegrityError`); `tool_registry` (khi còn là bảng) reject đúng tool `kind='write'` không khai báo `B17` trong `allowed_steps` (raw SQL + ORM).

**Vòng 3** (thiết kế lại kiến trúc `tickets`/bỏ 2 bảng): áp lại toàn bộ `schema.sql` trên PostgreSQL 16 sạch, không lỗi. Xác nhận đúng 17 bảng (raw SQL `\dt` và `Base.metadata.create_all()` — cả hai khớp nhau, không còn `conversation_messages`/`tool_registry`). Test luồng đầy đủ: tạo `users`/`sessions`/`tickets` (lean, 21 cột) → ghi 3 sự kiện quyết định vào `audit_logs` (B3, B12–14, B17) → cập nhật `tickets` một lần ở B20 (`final_state`/`close_reason`/...) → chạy đúng JOIN `tickets ⋈ audit_logs` mà kiến trúc mới yêu cầu cho ablation (`decided_by`, `matched_rule_id` ra đúng kết quả) → chạy đúng aggregate thuần trên `tickets` (`resolution_path` GROUP BY, phục vụ dashboard mục 16.3) → xác nhận `to_regclass()` trả NULL cho `conversation_messages`/`tool_registry` (bảng đã bị xoá thật). Phía ORM: `create_all()` tạo đúng 17 bảng; test round-trip quan hệ tự tham chiếu `Ticket.parent`/`Ticket.children` vẫn đúng sau khi thu hẹp cột; assert bằng code rằng các thuộc tính đã bỏ (`action_type`, `risk_level`, `decided_by`, `approver_id`, `state`, `diagnostics`, `missing_slots`, `clarification_turns`...) không còn tồn tại trên class `Ticket`. Toàn bộ test DB (`test_servicedesk3`, `test_models3`) đã được xoá sau khi test xong.

## Việc còn để mở, cần nhóm/GVHD chốt

1. Thứ tự ưu tiên chính xác của E5/E9 trong hàng đợi L2 (`exit_code_priority`).
2. Tên 3 giá trị `close_result` khi L2 đóng một escalation (tài liệu chỉ nói "3 kết quả").
3. Nội dung 4 phần của "ghi chú bàn giao" L2 (`escalations.handoff_note` hiện là text tự do).
4. Cấu trúc chính xác của `policy_rules.condition` (điều kiện khớp luật) khi hiện thực `policy_engine.evaluate()`.
5. *(Không phải việc cần GVHD chốt, chỉ là ghi chú triển khai)* Registry Python cho tool (thay `tool_registry` bảng SQL) chưa được viết thành code thật — mới dừng ở quyết định kiến trúc + comment trong `schema.sql`. Khi hiện thực `backend/app/tools/registry.py`, cần kèm unit test assert mọi tool `kind='write'` khai báo `'B17'` trong `allowed_steps`, đúng bất biến đã bỏ khỏi CHECK constraint DB.
