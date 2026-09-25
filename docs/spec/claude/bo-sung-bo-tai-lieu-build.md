# Bổ sung: Bộ tài liệu xây dựng `build/` — liên kết và patch cho các tài liệu ngữ cảnh

*25/09/2026. File này chỉ giữ **patch chờ áp** cho các tài liệu ngữ cảnh. Patch đã áp được xóa khỏi file (không giữ nhật ký). Trạng thái quyết định và câu hỏi GVHD: `build/decisions.md`.*

---

## Phần A — Bộ tài liệu `build/` trong project

| Nhóm | File | Dùng khi |
|---|---|---|
| Tổng quan | `build/00-README.md` — mục lục, quy ước, bảng D-01…D-33, thứ tự đọc cho coding agent | Đọc đầu tiên |
| Quyết định | `build/decisions.md` — danh sách duy nhất D-xx, việc nhóm tự chốt, quyết định Q1–Q14, thứ tự chốt | Trước mỗi buổi họp nhóm |
| Kiến trúc code | `build/01-kien-truc-project.md` — modular monolith (không microservices) và lý do; 9 process; cây thư mục; quy tắc import; cấu hình; CI/CD | T01, tạo repo |
| Tầng | `build/02-cac-tang-he-thong.md` — 8 tầng (T0 giao diện … T7 đánh giá): chức năng, được làm/cấm, FR/NFR, tiêu chí đạt; bảng nhánh → tầng → trạng thái → mã thoát | Trước khi code module |
| Nền tảng | `build/nen-tang/P1…P11` — LangGraph runtime, LLM gateway, RAG, ml-service, tool registry + mock, xác thực/phân quyền, thay đổi DB (22 bảng), đánh giá M8, Monitor M9, giao diện, huấn luyện model phân loại | Theo phase |
| Nhánh | `build/nhanh/B01…B20` — 12 file, khuôn 16 mục (sơ đồ, công nghệ, hợp đồng, mã giả, lý do, cấu hình, DB, trace, lỗi, test, phase, mở rộng, sửa lỗi, nhật ký) | Khi làm nhánh đó |

**Quan hệ với tài liệu hiện có:**

- `NGU-CANH-DAY-DU.md` và `huong-dan-xay-dung-he-thong-2.md` trả lời **xây gì và vì sao**.
- `build/` trả lời **xây như thế nào**.
- Khi mâu thuẫn, tài liệu gốc thắng, trừ các D-xx đã được nhóm chốt.

---

## Phần B — Các quyết định chờ xác nhận

Đã chuyển sang `build/decisions.md` (danh sách duy nhất, có cột "Báo GVHD" và "Chốt trước Phase").

---

## Phần C — Patch cho `huong-dan-xay-dung-he-thong-2.md`

### C4. Áp sau khi chốt D-08 — mục 4, dòng "Điều phối workflow"

- **Cũ:** `LangGraph + PostgresSaver, \`interrupt_before\``
- **Mới:** `LangGraph + PostgresSaver, \`interrupt()\` + \`Command(resume=…)\` (tài liệu LangGraph hiện ghi \`interrupt_before\` chỉ dùng để debug)`

### C5. Áp sau khi chốt D-06, D-07, D-09, D-10 — mục 4, thêm các dòng

```markdown
| Riêng tư (privacy guard) | Presidio + recognizer tiếng Việt, chạy ở API trước khi lưu | Bổ sung | Đạt được "mật khẩu không có trong DB" |
| Chặn injection tầng phân loại | Model ~86M (Prompt Guard 2 baseline; fine-tune mDeBERTa) qua ml-service | Bổ sung | LLM chỉ còn chạy ở vùng lưng chừng |
| Phục vụ model | `ml-service` (embed, rerank, classify) | Bổ sung | Nạp model 1 lần thay vì mỗi worker |
| Tách từ BM25 | pyvi/underthesea, sparse vector trong Qdrant | Bổ sung | "mật khẩu" là một từ |
| Xác thực | PyJWT, argon2 (mock AD), pyotp | Bổ sung | Xem `build/nen-tang/P6` |
```

### C6. Áp sau khi chốt D-01 — mục 5.1, cổng 2, dòng B1

- **Cũ:** `B1: sai 1 lần → đóng bình thường; sai 5 lần trong 10 phút → chặn và báo Trưởng BP (TC24, TC25).`
- **Mới:** `Đăng nhập: sai 1 lần → 401, không tạo ticket; sai 5 lần/10 phút → khóa 15 phút và báo Trưởng BP (TC24, TC25 viết lại). B1 trong graph chặn ticket khi phiên bị thu hồi, tài khoản bị khóa hoặc vô hiệu hóa.`

### C7. Áp sau khi chốt D-17, D-18, D-19 — mục 5.1, cổng 2, thêm ba dòng

```markdown
- Ticket cha có 1 con kết thúc **trước** khi cha vào trạng thái chờ tổng hợp → cha vẫn đóng đúng (D-17).
- Giết process ngay sau khi B15 tạo phiếu duyệt, trước khi checkpoint → khởi động lại → đúng 1 phiếu, đúng 1 thông báo (D-18).
- 8 graph đồng thời, mỗi lượt có LLM giả chậm 10 giây → pool DB không cạn, không transaction nào mở quá 1 giây (D-19).
```

### C8. Áp sau khi chốt D-21, D-22, D-25 — mục 5.1, cổng 3 và cổng 5

- Cổng 3, thêm: `Không chunk nào vượt 512 token theo tokenizer bge-m3; ngưỡng truy hồi chọn trên bộ có ≥ 20 câu không có đáp án, báo cáo cả tỉ lệ trả lời bừa và tỉ lệ E3 oan.`
- Cổng 5, thêm: `Ablation RAG 4 cấu hình (dense / BM25 / hybrid / hybrid + rerank) trên cùng bộ câu kiểm tra: Recall@5, MRR, nDCG@5.`

---

### C10. Áp sau khi chốt D-32, D-33 — mục 4 (bảng công nghệ) và mục 11

- Mục 4, dòng "Phân loại intent": "LLM structured output" → "Model phân loại đa nhãn mDeBERTa-v3-base do nhóm huấn luyện (chạy trước); LLM structured output cho vùng lưng chừng và tách span câu nhiều ý".
- Mục 4, dòng "Chặn injection tầng 2": "mở rộng: mô hình phân loại nhỏ fine-tune tiếng Việt" → "model `injection-clf` mDeBERTa-v3-base do nhóm huấn luyện (đường chính); Prompt Guard 2 làm baseline RQ4".
- Mục 11: bỏ "fine-tune PhoBERT/XLM-R cho intent" khỏi danh sách mở rộng (đã thành đường chính); giữ PhoBERT làm baseline so sánh.

---

## Phần D — Patch cho `NGU-CANH-DAY-DU.md` (áp sau khi chốt)

### D1. Phần III mục 11.1 — thay hai dòng TC24, TC25 (sau D-01)

```markdown
| TC24 *(viết lại, D-01)* | Đăng nhập sai một lần rồi đúng | An ninh — ca thường | Middleware → 401, không tạo ticket | 1 dòng `login_failed`, không cảnh báo |
| TC25 *(viết lại, D-01)* | Đăng nhập sai 5 lần trong 10 phút | An ninh — ca thật | Middleware → khóa 15 phút; B1 chặn ticket đang mở (`repeated_auth_failure`) | Cảnh báo Trưởng BP, tính vào chỉ số an ninh |
```

### D2. Phần III mục 11.1 — thêm hai dòng sau TC29 (TC29 đã áp cùng bản vá E9)

```markdown
| TC30 *(D-02)* | Đổi ID trên URL để xem ticket/duyệt phiếu của người khác | An ninh — IDOR | Kiểm tra theo bản ghi | 404 khi đọc, 403 khi duyệt |
| TC31 *(D-01)* | Người dùng bị vô hiệu hóa khi đang có phiên | An ninh — thu hồi | Middleware + B1 + B17 | Mọi phiên mất hiệu lực ≤ 30 giây; không thực thi |
```

### D3. Phần III mục 2.2 — thêm một đoạn sau "Hai quy tắc phân quyền" (sau D-02)

```markdown
**Kiểm tra theo bản ghi (bổ sung):** ma trận trên kiểm ở mức vai trò. Ngoài ra, mỗi thao tác trên một bản ghi cụ thể còn được kiểm riêng — L1 chỉ duyệt được phiếu giao cho chính mình, không ai ghi đè yêu cầu của chính mình, nhân viên chỉ đọc được ticket của mình. Chi tiết: `build/nen-tang/P6-auth-bao-mat.md`.
```

### D4. Phần VI mục 3 nguyên tắc 5 và mục 4 (bảng câu hỏi) — sau khi chốt D-26

- **Cũ:** "…hoặc mở một ticket MỚI đi lại từ B12 nếu xác minh được là hợp lệ…"
- **Mới:** "…hoặc mở một ticket MỚI chạy lại từ B1 (chụp lại danh tính, sàng lọc, dựng lại `intended_action` từ đầu, rồi đi qua B12–B17) nếu xác minh được là hợp lệ…"

### D5. Phần III mục 11.1 — thêm hai dòng (sau khi chốt D-17, D-18)

```markdown
| TC32 *(D-17)* | Câu nhiều ý, một con bị E1 ngay lập tức | Đồng thời — cha/con | Con kết thúc trước khi cha chờ | Cha vẫn đóng đúng, một tin nhắn tổng hợp |
| TC33 *(D-18)* | Process chết sau khi tạo phiếu duyệt, trước checkpoint | Phục hồi sau sự cố | Resume từ checkpoint cuối | Đúng 1 phiếu, đúng 1 thông báo |
```

---

## Phần E — Patch cho `NGU-CANH-DAY-DU.md` Phần IV (workflow chi tiết; áp sau khi chốt)

| # | Vị trí | Thay đổi | Quyết định |
|---|---|---|---|
| E1 | Mục 2.1 | Thêm `S_NEW → S_ESCALATED` (E2, AD lỗi khi B1 chạy nền) và `S_SCREENING → S_ESCALATED` (E2, cả classifier và LLM của B2 đều lỗi) | D-01, D-06 |
| E2 | Mục 3, `TicketState` | `raw_request` → `redacted_request`; `requester_id/role/dept` → `requester_context` (thêm `employment_status`, `tenure_days`, `manager_id`); thêm `next`, `is_parent`, `off_topic_streak` | D-01, D-07 |
| E3 | Mục 3, `Action` | Thêm `reversibility` (full/partial/none) và `facts` (dữ kiện cho luật, được băm cùng Action) | B11 |
| E4 | Mục 4, B1 | Thay mã giả bằng `b01_identity` ở `build/nhanh/B01-xac-thuc.md` mục 5 | D-01 |
| E5 | Mục 4, B5 | Thay `S_SPLIT` bằng cờ `is_parent`; ticket con bắt đầu từ B6; cha đối soát con từ DB (D-17) | README mục 5, D-17 |
| E6 | Mục 8.2 | `interrupt_before=[...]` → `interrupt()` trong 3 node chờ, resume bằng `Command(resume=…)` | D-08 |
| E7 | Mục 2.1 | Thêm `S_CLARIFYING → S_DIAGNOSING` (người dùng bổ sung slot làm đổi tham số tool, `reasoning_loops` < 5) | D-20 |
| E8 | Mục 6, bảng bộ đếm | `reasoning_loops` tăng ở B3 và B6, gồm cả lần chẩn đoán lại (D-20) | D-20 |
| E9 | Mục 4, B17 | Kiểm lại trạng thái AD của cả người gửi lẫn `requested_for` | D-15 |
| E11 | Mục 4, B3 (mã giả `b3_classify`) | Thêm bước model phân loại đa nhãn chạy trước LLM, theo `build/nhanh/B03-B05-phan-loai-tach-y.md` mục 5.1 | D-32 |
| E10 | Mục 1.2 | "mở ticket mới đi lại từ B12" → "mở ticket mới chạy lại từ B1" | D-26 |

---

## Phần F — Patch cho `claude/thiet-ke-database.md` (áp sau khi chốt D-04, D-05, D-11, D-14, D-18, D-30, D-31; đầu file đã có ghi chú "hiện hành 22 bảng")

Thêm mục "Vòng review thứ tư (2026-09-25) — bảo mật và vận hành", nội dung theo `build/nen-tang/P7-db-thay-doi.md`:

- **Bảng mới:** `security_events` (+ view `auth_failures`), `llm_cache`, `wait_deadlines`, `side_effects` (D-18), `child_notices` (D-31); cột `tickets.is_parent` (D-30).
- **Mở rộng:** `users` (không có cột mật khẩu), `sessions`, `approvals` (thêm UNIQUE một phiếu `pending` mỗi ticket), `audit_logs` (khóa idempotent mới), `escalations` (`reason_detail`, D-27).
- **Role và trigger:** 3 role Postgres; trigger append-only.
- Bảng `child_notices` và cột `tickets.is_parent` (D-30, D-31).
- Đổi "17 bảng" thành "22 bảng".
- Cập nhật `schema.sql` và `models.py`.

## Phần G — Patch cho `claude/so-do-kien-truc-he-thong.md` và artifact sơ đồ (áp sau khi chốt D-09, D-13)

Thêm vào sơ đồ:

- Khối `ml-service` giữa backend và RAG.
- Khối T1 "Cổng vào & bảo mật" (AuthN/RBAC/privacy guard) trước tầng Agent.
- Nhãn "modular monolith" cho khối backend.

Republish cùng URL để giữ link.
