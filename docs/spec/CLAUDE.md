# CLAUDE.md — Hướng dẫn cho coding agent

Bạn đang xây **AI Agent tự động hóa IT Service Desk cấp 1 với Human-in-the-Loop** (đồ án tốt nghiệp, ĐH FPT, mục tiêu 8,5+). Thư mục này là toàn bộ đặc tả. **Không đọc hết một lần** (~1 MB). Đọc theo phase như mục 3.

## 1. Nguồn sự thật và thứ tự ưu tiên

1. `NGU-CANH-DAY-DU.md` — ngữ cảnh gốc đã chốt: objectives, luồng 20 bước, 14 trạng thái, E0–E9, bảng luật, kịch bản TC. **Phần IV** là workflow chi tiết (state machine + mã giả gốc).
2. `huong-dan-xay-dung-he-thong-2.md` — xây gì, theo phase nào, cổng nghiệm thu từng phase (mục 5.1).
3. `build/` — xây **như thế nào**: kiến trúc code, tầng, nền tảng P1–P10, nhánh B01–B20.
4. `build/decisions.md` — trạng thái mọi quyết định D-01…D-33, N1–N5 và Q1–Q14 (nhóm tự quyết, không có vòng hỏi GVHD).

Khi mâu thuẫn: tài liệu 1–2 thắng, **trừ** các D-xx trong `build/` (đó là bản sửa đã được viết thành đặc tả). Gặp mâu thuẫn chưa được giải thích → dừng, ghi vào `PROGRESS.md`, hỏi người.

Nhãn trong tài liệu: **[Chốt]** = không được đổi; **[Đề xuất]** = làm theo, nhưng nêu lại khi nộp PR; **[Suy luận]** = giả định, kiểm lại nếu có dấu hiệu sai.

## 2. Luật không được phá (tóm tắt, bản đầy đủ ở khối CTX đầu mỗi file `build/`)

1. M5 không bao giờ đọc câu người dùng: `policy_engine.evaluate(action, ctx)` chỉ có 2 tham số.
2. B17 là điểm ghi duy nhất ra hệ thống ngoài; chỉ `svc_executor` có credential ghi.
3. Mọi đổi trạng thái qua `goto()` (P1 mục 5.1, 5.1.1); mọi side effect qua `effects.once` (P1 mục 5.3).
4. Hết hạn duyệt không bao giờ tự thực thi. Luật `deny` không vào hàng đợi duyệt.
5. Lỗi hệ thống ≠ kết quả rỗng (E2 ≠ E3). Mọi exception chưa lường trước → E9.
6. Ngưỡng và calibrator chỉ fit trên tập calibration (P8).
7. Ticket con không tự nhắn người dùng; một lượt người dùng — một tin trả lời (D-31).
8. B3 (intent) và B2 lớp L3 (injection) dùng model phân loại nhóm tự huấn luyện (P11) chạy trước; LLM chỉ là đường dự phòng cho vùng lưng chừng/câu nhiều ý/khi chưa có model (D-32). Không huấn luyện trên câu thuộc tập test M8.
9. Không đổi tech stack đã chốt (Python 3.12, FastAPI, LangGraph + Postgres checkpoint, PostgreSQL 16, Qdrant + bge-m3 + bge-reranker-v2-m3, React + Vite + TS).

## 3. Làm theo phase — đọc gì, làm gì

**Mỗi lần chỉ làm một phase (hoặc một nhánh).** Không mở phase sau khi cổng phase trước chưa xanh.

**Chế độ xây hiện tại: code trước, gắn API sau** (`build/decisions.md` mục 4). Phase 1–7 **không gọi LLM thật**: dùng `ScriptedLLM` (có cả ca lỗi: JSON sai, 429, timeout). "Cổng xanh" ở Phase 1–7 = mọi test tự động xanh; phần cổng cần LLM thật (demo, probe, kiểm thủ công) ghi vào `PROGRESS.md` mục "Dồn về mốc G" rồi đi tiếp. Không tự thêm key API, không gọi provider nào.

| Phase | Đọc | Làm | Cổng (điều kiện xong) |
|---|---|---|---|
| 0 | `build/decisions.md` | **Đã xong** (D-01…D-33, Q1–Q14 đã chốt theo đặc tả) | — |
| 1 | `build/00-README.md`, `01`, `02`, P7, P5, P6 | Repo, compose, DB 22 bảng + role, mock hệ thống ngoài, auth | `huong-dan` cổng 1 + P5/P6/P7 mục kiểm thử |
| 2 | P1, B01, B20 | Runtime LangGraph, `goto`, `effects.once`, khóa, E9, audit | Cổng 2 + P1 mục 11 |
| 3 | P2, P4, P3, P11 (mục 1, 4.3 — định dạng model), B03-B05, B06-B07, B08-B09, B10, B11, B12-B14 (luật VPN), B17-B18, B19 | Luồng VPN end-to-end | Cổng 3 |
| 4 | B15-B16, P10 (màn hình L1 tối thiểu), P9 (view) | Phê duyệt + audit 8 điểm | Cổng 4 |
| 5 | B02, phần còn lại B03-B05, B12-B14, B17-B18 | Đủ 4 loại, tách ý, injection, hoàn tác | Cổng 5 |
| 6 | B12-B14 lớp 2 | Estimator, calibrator, `decision_math` | Cổng 6 |
| 7 | P10, P9 | Giao diện 4 vai trò, dashboard, cảnh báo | Cổng 7 |
| G | P2 mục 12–13, `decisions.md` mục 4 | **Gắn LLM API thật**: chọn model, chạy các phần cổng 3/5/6 cần LLM thật đã dồn lại | Mọi phần dồn đã xanh |
| 8–10 | P8 | Harness, chia tập, thực nghiệm RQ1/RQ3 (LLM thật) | Cổng 8–10 |
| Song song | P11 | Dữ liệu + huấn luyện `intent-clf`, `injection-clf`; xuất vào `ml_models/`. Code chạy được khi chưa có model (ml-service trả 503 → đường LLM) | P11 mục 5 |

Mỗi file `build/` có mục **"Kiểm thử và tiêu chí đạt"** — đó là định nghĩa "xong" của file đó.

## 4. Cách làm việc

- Trước khi code một nhánh: đọc khối "0. Ngữ cảnh nạp sẵn" của file nhánh đó + các file nền tảng nó ghi ở mục "Phụ thuộc".
- Code theo đúng cây thư mục ở `build/01-kien-truc-project.md` mục 3 và hợp đồng import-linter mục 4.3.
- Test chạy với `ScriptedLLM` (không gọi LLM thật) trừ khi file ghi "probe".
- Ghi tiến độ vào `PROGRESS.md` (phase đang mở, task xong, cổng nào xanh, câu hỏi mở).
- Không tự thêm trạng thái mới, mã thoát mới, giá trị `close_reason` mới, hay bảng DB mới ngoài P7. Cần thì dừng và hỏi.
- Các file `docs/…`, `backlog.md`, `kb-facts.md`, `SPLIT.md` được nhắc trong `huong-dan` **không có ở đây**; bảng đối chiếu ở `huong-dan` mục 18.1. `kb-facts.md`, `SPLIT.md`, `PROGRESS.md` là file bạn tạo khi làm.

## 5. Câu giao task mẫu

> "Làm Phase 2. Đọc `CLAUDE.md`, `build/00-README.md`, `build/01-kien-truc-project.md`, `build/nen-tang/P1-langgraph-runtime.md`, `build/nhanh/B01-xac-thuc.md`, `build/nhanh/B20-audit-escalate-L2.md`. Chỉ sửa trong `backend/app/graph/`, `backend/app/domain/`, `backend/app/audit/`. Xong khi mọi test ở P1 mục 11 xanh. Ghi `PROGRESS.md`."
