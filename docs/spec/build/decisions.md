# Quyết định và câu hỏi GVHD — danh sách duy nhất

*Thuộc bộ `build/`. Đây là **nơi duy nhất** theo dõi trạng thái quyết định và câu hỏi gửi GVHD. `huong-dan-xay-dung-he-thong-2.md` Phase 0 gọi file này là `decisions.md`. Khi một mục được chốt: sửa cột "Trạng thái" ở đây, rồi áp patch tương ứng trong `claude/bo-sung-bo-tai-lieu-build.md`.*

*Cập nhật: 25/09/2026.*

---

## 1. Việc nhóm tự chốt (không cần GVHD)

| Mã | Việc | Chặn từ | Mặc định nếu chưa chốt | Trạng thái |
|---|---|---|---|---|
| N1 | Provider LLM + bảng giá + ngân sách (vai trò fast/strong) | Phase 3 | — (bắt buộc chốt) | Chưa |
| N2 | Phần cứng: có GPU không, bao nhiêu VRAM → mức ở `huong-dan` mục 11 | Phase 3 (RQ5 ở Phase 11) | Mức 0: chỉ LLM API | Chưa |
| N3 | Phân bố vận hành giả định cho escalation rate có trọng số | Phase 10 | 70% thường ngày / 20% cần duyệt / 10% nhạy cao | Chưa |
| N5 | Tài nguyên huấn luyện (Colab/Kaggle GPU) và người phụ trách huấn luyện (mặc định TV1) | Phase 1 (luồng dữ liệu) | Colab/Kaggle, fp32 | Chưa |
| N4 | Đánh số lại luật (mã R22 vượt 20 luật) khi viết `policy.json` | Phase 5 (T22a) | — | Chưa |

## 2. Câu hỏi gửi GVHD

Mã Q giữ nguyên như `huong-dan` mục 12 để không vỡ tham chiếu; Q12–Q14 mới. Cột "NGU-CANH" là số thứ tự câu hỏi ở `NGU-CANH-DAY-DU.md` Phần VI mục 1.

| Mã | Câu hỏi | Gắn với | NGU-CANH | Chặn từ | Mặc định đang dùng | Trạng thái |
|---|---|---|---|---|---|---|
| Q1 | TC09/TC10 theo bảng luật §6.3 (cần duyệt) hay xuống lớp LLM (vùng giữa)? | M5, dữ liệu | — | Phase 3 | Theo bảng luật; bù bằng TC37 + họ kịch bản đi xuống LLM | Chưa hỏi |
| Q2 | L2 có được hoàn tất tay ca hết hạn duyệt (E6) không? | B20 | — | Phase 7 | Chặn `completed` cho E6 | Chưa hỏi |
| Q3 | ActionPlan đổi sau khi duyệt: giữ chuyển L2 hay cho chạy lại M5 khi chỉ trường không nhạy cảm đổi? | B17 | 5 | Phase 4 | Chuyển L2 | Chưa hỏi |
| Q6 | Ý nghĩa cột % của objectives (điểm hay khối lượng)? Làm tối giản 2 vai trò (Trưởng BP, L2) có ảnh hưởng đánh giá? | Kế hoạch | 1, 3 | — | — | Chưa hỏi |
| Q8 | Chấp nhận biến thể "LLM chỉ được nâng mức" (`hybrid_guarded`) làm phương án so sánh? | M5, M8 | — | Phase 6 | Có code, chỉ chạy nếu đồng ý | Chưa hỏi |
| Q9 | Tỉ lệ chi phí bỏ sót / một lượt duyệt (quyết định trực tiếp ngưỡng dưới) | M5 | — | Phase 3 | 10:1 → `t_low*` = 0,1 | Chưa hỏi |
| Q10 | Chấp nhận thêm chuyển `S_CLARIFYING → S_DIAGNOSING` (chẩn đoán lại khi người dùng bổ sung slot)? | D-20 | — | Phase 5 | Cờ tắt | Chưa hỏi |
| Q11 | Ticket L2 mở lại sau ca deny chạy từ B1 hay từ B12? | D-26 | — | Phase 7 | B1 | Chưa hỏi |
| Q12 | *(để báo)* Yêu cầu nhiều ý: người dùng nhận một tin tổng hợp, có thể chờ ý chậm nhất (tối đa SLA 30 phút). Chấp nhận đánh đổi? | D-32 | B3 chạy model phân loại intent đa nhãn trước, LLM cho vùng lưng chừng và tách span câu nhiều ý | B03-B05, P4, P11 | 3 | Nên báo | Chờ xác nhận |
| D-33 | Backbone mDeBERTa-v3-base cho `intent-clf` và `injection-clf`; PhoBERT baseline intent; Prompt Guard 2 baseline RQ4 | P11, B02, P4 | 5 | Nên báo | Chờ xác nhận |
| D-31 | 6 | Phase 5 | Giữ đúng "một tin" (nhóm đã chọn) | Chưa hỏi |
| Q13 | Có đổi tên đề tài thành "Risk-Aware Agentic AI…"? | Đề tài | 4 | — | Giữ tên hiện tại | Chưa hỏi |
| Q14 | Phương án fail-safe khi hết hạn duyệt (escalate, không tự làm) có hợp lý? | B16 | 2 | — | Fail-safe | Chưa hỏi |

**Mục nên báo GVHD (không cần GVHD quyết):** D-01, D-07, D-08 (đổi hành vi hoặc công nghệ đã ghi), D-13, D-22, D-25, D-29, D-30, D-32, D-33 — xem cột "Báo GVHD" ở mục 3.

## 3. Quyết định kỹ thuật D-01…D-33

Nội dung đầy đủ và lý do: `build/00-README.md` mục 4 và file được nêu trong từng quyết định. "Chốt trước" = phase phải chốt xong trước khi bắt đầu.

| Mã | Nội dung | Ảnh hưởng | Chốt trước Phase | Báo GVHD | Trạng thái |
|---|---|---|---|---|---|
| D-01 | Đăng nhập tách khỏi graph; B1 chỉ chốt danh tính + `requester_context` từ AD | Đổi hành vi TC24/TC25 | 2 | **Có** | Chờ xác nhận |
| D-02 | RBAC + kiểm tra theo bản ghi (chống IDOR), deny-by-default | Thêm TC30 | 2 | Không | Chờ xác nhận |
| D-03 | 4 service identity; chỉ `svc_executor` có credential ghi | Mock | 1 | Không | Chờ xác nhận |
| D-04 | Bảng `security_events` + view `auth_failures` | DB | 1 | Không | Chờ xác nhận |
| D-05 | 3 role Postgres + trigger append-only | DB | 1 | Không | Chờ xác nhận |
| D-06 | B2 có 5 lớp, thêm model phân loại injection (Prompt Guard 2 baseline / mDeBERTa fine-tune) | B2, chi phí | 5 | Nên báo (gắn RQ4) | Chờ xác nhận |
| D-07 | Privacy guard chạy ở API trước khi lưu ticket | `TicketState` (`raw_request` → `redacted_request`) | 3 | **Có** | Chờ xác nhận |
| D-08 | `interrupt()` thay `interrupt_before` | Cơ chế chờ người | 2 | **Có** (đổi công nghệ đã ghi) | Chờ xác nhận |
| D-09 | Thêm process `ml-service` | Triển khai | 3 | Không | Chờ xác nhận |
| D-10 | BM25 tách từ tiếng Việt, sparse vector trong Qdrant, RRF phía server | M2 | 3 | Không | Chờ xác nhận |
| D-11 | Bảng `llm_cache` | DB | 1 | Không | Chờ xác nhận |
| D-12 | LLM gateway tự viết trên SDK `openai`; LiteLLM là phương án B | M4/LLMOps | 3 | Không | Chờ xác nhận |
| D-13 | Modular monolith + service phụ trợ | Toàn bộ | 1 | Nên báo | Chờ xác nhận |
| D-14 | Audit idempotent — khóa **`(ticket_id, step, event, turn_id, loop_seq)`** (sửa ở v1.2) | M7 | 2 | Không | Chờ xác nhận |
| D-15 | B17 kiểm lại **cả người gửi lẫn người hưởng lợi** trong AD trước khi ghi (sửa ở v1.2) | B17 | 5 | Không | Chờ xác nhận |
| D-16 | Tool chẩn đoán mặc định chỉ tra cứu chính người gửi | B6, M5 ctx | 5 | Không | Chờ xác nhận |
| D-17 | `parent_wait` đối soát trạng thái con từ DB; `child_done` chỉ để đánh thức | Runner, B5, B20 | 2 | Không | Chờ xác nhận |
| D-18 | Side effect idempotent qua bảng `side_effects`; phục hồi giữ `turn_id` | Runner, DB (22 bảng từ v1.3) | 2 | Không | Chờ xác nhận |
| D-19 | Khóa ticket cấp session trên pool riêng | Runner | 2 | Không | Chờ xác nhận |
| D-20 | Chẩn đoán lại B11 → B6 khi slot mới đổi tham số tool; thêm chuyển `S_CLARIFYING → S_DIAGNOSING` | **Máy trạng thái** | 5 | **Có** (Q10) | Chờ xác nhận |
| D-21 | Chunk theo token bge-m3 (≤ 380 token nội dung) | M2 | 3 | Không | Chờ xác nhận |
| D-22 | Bộ ≥ 20 câu không có đáp án để chọn ngưỡng E3 | M2, dữ liệu | 3 | Nên báo | Chờ xác nhận |
| D-23 | Truy hồi lại một lần không lọc intent khi điểm thấp | M2 | 3 | Không | Chờ xác nhận |
| D-24 | Ghép chunk liền kề làm ngữ cảnh cho B10 | M2 | 3 | Không | Chờ xác nhận |
| D-25 | KB mục tiêu ≥ 50 tài liệu có tài liệu gây nhiễu; ablation RAG 4 cấu hình | Khối lượng nội dung, Obj 1 | 5 | Nên báo | Chờ xác nhận |
| D-26 | Ticket mới do L2 mở lại chạy từ B1 | B20, NGU-CANH Phần VI | 7 | **Có** (Q11) | Chờ xác nhận |
| D-27 | Tách `event=intent_low_confidence` khỏi E1 thật | M9, chỉ số | 5 | Không | Chờ xác nhận |
| D-28 | Lập luận "constrained agent" trong P1 | Tài liệu | — | Không | Chờ xác nhận |
| D-29 | `ALLOWED_TRANSITIONS` = bảng 2.1 + 3 quy tắc (giữ nguyên trạng thái xử lý; mọi trạng thái chưa kết thúc → `S_ESCALATED`; chuyển riêng của ticket cha) | **Máy trạng thái** (không thêm trạng thái, không mở đường mới tới `S_EXECUTING`) | 2 | Nên báo | Chờ xác nhận |
| D-30 | Ticket cha: `close_reason = NULL`, không `exit_code`, không `escalations`; chỉ số chỉ tính ticket lá | Chỉ số Obj 3, DB (`tickets.is_parent`) | 5 | Nên báo (ảnh hưởng cách đếm) | Chờ xác nhận |
| D-31 | Một tin tổng hợp cho yêu cầu nhiều ý: con không tự nhắn, cha gửi một tin mỗi lượt người dùng, xác nhận một lần qua cha | B5, B10, B11, B16, B18, B19, B20; DB 22 bảng (`child_notices`) | 5 | **Có** — báo đánh đổi "người dùng chờ ý chậm nhất" (nhóm đã chọn giữ đúng câu chốt) | Chờ xác nhận |

## 4. Thứ tự chốt khuyến nghị

1. **Trước Phase 1 (một buổi họp nhóm):** D-03, D-04, D-05, D-11, D-13.
2. **Trước Phase 2:** D-01, D-02, D-08, D-14, D-17, D-18, D-19, D-29. Sửa sau khi đã code khung graph rất đắt.
3. **Trước Phase 3:** N1, N2, Q1, Q9 + D-07, D-09, D-10, D-12, D-21…D-24, D-32 (endpoint + đường dự phòng; model có thể vào sau).
4. **Trước Phase 5:** Q10, Q12 + D-06, D-15, D-16, D-20, D-25, D-27, D-30, D-31, D-33 (model v1 đã huấn luyện theo P11).
5. **Trước Phase 7:** Q2, Q11 + D-26.
6. **Trước Phase 10:** N3; Q8 nếu muốn chạy `hybrid_guarded`.

## 5. Nhật ký

| Ngày | Thay đổi |
|---|---|
| 25/09/2026 | Tạo file: gộp D-01…D-33 và mọi câu hỏi GVHD (từ `huong-dan` mục 12, `NGU-CANH` Phần VI mục 1, `bo-sung`) thành một danh sách |
| 25/09/2026 | Thêm D-32, D-33 (model phân loại do nhóm huấn luyện), N5 |
