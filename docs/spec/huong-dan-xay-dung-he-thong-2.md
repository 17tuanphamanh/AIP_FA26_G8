# Hướng dẫn xây dựng hệ thống — AI Agent IT Service Desk cấp 1 với Human-in-the-Loop

*Phiên bản gốc 23/09/2026. Bản này chuyển đổi từ PDF sang Markdown và bổ sung ngữ cảnh về lớp bắt lỗi tổng quát ở tầng graph (E9) để đồng bộ với `NGU-CANH-DAY-DU.md` Phần IV mục 7.2 và `NGU-CANH-DAY-DU.md`. Mọi đoạn bổ sung được đánh dấu rõ bằng khối "> **Bổ sung ngữ cảnh (E9):**" để phân biệt với nội dung gốc.*

*Cập nhật 25/09/2026: sửa công thức `t_low*` ở mục 7.3; thêm mục 18 trỏ sang bộ `build/`.*

*Cập nhật 10/10/2026 (Phase 6, G6-3): "hỏi nhiều lần" thống nhất k = 5 ở mục 7.2, 14.2, 15.1, 15.2 (trước ghi 7); mục 9 — 8 test toán quyết định hiện thực ở Phase 6 chặng 6A, không có sẵn trong scaffold.*

*Cập nhật 17/10/2026 (Phase 5): cổng 5 thủ công ở mục 5.1 — bộ intent 45 câu, macro-F1 tính trên 5 lớp, bộ câu chỉ để đo (chốt 15/10/2026).*

---

## Mục lục

1. [Mục đích và cách đọc](#1-mục-đích-và-cách-đọc)
2. [Logic xây dựng](#2-logic-xây-dựng)
3. [Kiến trúc tổng thể](#3-kiến-trúc-tổng-thể)
4. [Công nghệ và lý do chọn](#4-công-nghệ-và-lý-do-chọn)
5. [Thứ tự xây dựng](#5-thứ-tự-xây-dựng)
6. [Xây từng nhánh workflow](#6-xây-từng-nhánh-workflow)
7. [M5 — quyết định khi nào cần người](#7-m5--quyết-định-khi-nào-cần-người)
8. [Dữ liệu](#8-dữ-liệu)
9. [Kiểm thử](#9-kiểm-thử)
10. [Đánh giá và thực nghiệm](#10-đánh-giá-và-thực-nghiệm)
11. [Phần cứng và LLM local (bổ sung)](#11-phần-cứng-và-llm-local-bổ-sung)
12. [Rủi ro và việc cần chốt](#12-rủi-ro-và-việc-cần-chốt)
13. [Triển khai (bổ sung)](#13-triển-khai-bổ-sung)
14. [Chịu tải (bổ sung)](#14-chịu-tải-bổ-sung)
15. [Chi phí (bổ sung)](#15-chi-phí-bổ-sung)
16. [Tính năng bổ trợ cho từng actor (bổ sung)](#16-tính-năng-bổ-trợ-cho-từng-actor-bổ-sung)
17. [Kỹ thuật agent — lớp quản trị quanh agent (Objective 1, bổ sung)](#17-kỹ-thuật-agent--lớp-quản-trị-quanh-agent-objective-1-bổ-sung)
18. [Bộ tài liệu xây dựng chi tiết `build/` (bổ sung)](#18-bộ-tài-liệu-xây-dựng-chi-tiết-build-bổ-sung)

---

## 1. Mục đích và cách đọc

Tài liệu này mô tả cách xây toàn bộ hệ thống theo một chuỗi logic duy nhất: mỗi thành phần tồn tại để phục vụ một trong ba Project Objectives đã chốt; các câu hỏi nghiên cứu (RQ) chỉ dùng để đánh giá một số thành phần. Thành phần được xây theo thứ tự giảm rủi ro từ thấp lên cao.

**Nguồn:** hai tài liệu gốc của nhóm — `NGU-CANH-DAY-DU.md` Phần IV (máy trạng thái, mã giả B1–B20) và `NGU-CANH-DAY-DU.md` (bài toán, bảng luật, kịch bản, chỉ số), bản 19/09/2026.

**Quan hệ với bộ tài liệu cho coding agent (`servicedesk-agent-docs`):** tài liệu này là bản tổng quan cho người đọc (nhóm, GVHD). Chi tiết để code — mã giả từng bước, hợp đồng, test — nằm trong bộ tài liệu đó; mỗi mục dưới đây chỉ ra file tương ứng.

**Phạm vi:** 4 loại yêu cầu (tài khoản, VPN, phần mềm, quyền truy cập), hệ thống ngoài giả lập, tiếng Việt.

**Cách đọc:** mục 2 (logic) → mục 3–4 (kiến trúc, công nghệ) → mục 5 (thứ tự xây) → mục 6–7 (chi tiết workflow và M5) → mục 8–10 (dữ liệu, kiểm thử, đánh giá) → mục 12 (việc cần chốt).

**Quy ước nhãn:** phần có trong tài liệu gốc không đánh dấu; phần bổ sung để đồ án chặt hơn ghi **(bổ sung)** — mỗi phần bổ sung cần nhóm xác nhận và báo GVHD.

### 1.1. Ba mục tiêu và phân bổ công sức

Ba mục tiêu đã chốt với GVHD là thang đo của cả đồ án. Công sức xây dựng phải chia theo đúng trọng số này, không theo độ mới của từng thành phần.

| Mục tiêu (đã chốt) | Trọng số | Thành phần | Mục trong tài liệu | Phase chính |
|---|---|---|---|---|
| 1. Xây dựng AI Agent tự động hóa xử lý yêu cầu IT cấp 1 | 50–60% | M1 phân loại + slot, M2 RAG, M3 tool + chẩn đoán, M4 điều phối; và lớp kỹ thuật agent: session/trace, bộ nhớ và ngữ cảnh, harness, tool registry, vòng đời dữ liệu RAG, tối ưu chi phí, LLMOps, riêng tư | 3, 4, 6, 11, 13–15, 17 | 1, 2, 3, 5, 7 |
| 2. Xây dựng cơ chế Human-in-the-Loop cho hành động nhạy cảm | 30–40% | M5 bộ phân loại rủi ro, M6 phê duyệt, M7 audit; giao diện duyệt, ghi đè, L2 | 7, 16 | 4, 6, 7 |
| 3. Đánh giá hiệu quả và độ an toàn | 0–20% | M8: bộ kịch bản, harness đánh giá, chỉ số, so sánh phương án | 8–10 | 8, 9, 10 |

**Nguyên tắc nhất quán của cả tài liệu:** Objective quyết định xây gì → Phase quyết định xây khi nào → RQ chỉ quyết định đo cái gì. Một thứ đã được ghi là phải xây thì không phụ thuộc việc thực nghiệm RQ tương ứng có làm hay không.

Hệ quả cho cách xây:
- **Objective 1** là phần lớn nhất. Agent phải là một hệ thống được thiết kế kỹ — có trace, quản lý ngữ cảnh, quản trị tool, vòng đời dữ liệu, kiểm soát chi phí và riêng tư — không chỉ là chuỗi lời gọi LLM chạy được. Mục 17 mô tả phần này.
- **Objective 2** là điểm khác biệt. M5 vẫn là đóng góp nghiên cứu (quyết định khi nào cần người), nhưng chỉ chiếm khoảng một phần ba công sức.
- **Objective 3** làm vừa đủ và chặt. Các câu hỏi nghiên cứu ở mục 2 là khung đánh giá, không phải trục của cả đồ án. Phần bắt buộc: bộ kịch bản, so sánh 4 phương án, ablation, chỉ số chất lượng agent. Các thực nghiệm sâu (so 3 cách lấy xác suất, LLM local) chỉ làm khi còn thời gian.

---

## 2. Logic xây dựng

Hệ thống phải đạt cả ba mục tiêu ở mục 1.1. Riêng phần đánh giá (Objective 3) được tổ chức quanh các câu hỏi nghiên cứu dưới đây, để mỗi con số báo cáo trả lời một câu hỏi cụ thể. Câu hỏi quan trọng nhất về mặt học thuật là: **quyết định "tự làm / cần duyệt / chuyển L2" thế nào để vừa an toàn vừa không escalate thừa?**

Sơ đồ bài toán: Bài toán "L1 tốn người cho việc lặp lại" → Khoảng trống "11 sản phẩm không công bố khi nào cần người" → RQ1 "quyết định HITL an toàn, không thừa" → Thành phần chính M5 "luật → LLM → hiệu chỉnh → ngưỡng" → Điều kiện đo "agent chạy đầu–cuối M1–M4, M6–M7" → Dữ liệu "kịch bản nhãn 3 mức" → Thực nghiệm "4 phương án + ablation".

*Đọc sơ đồ: không có agent chạy đầu–cuối thì không có ticket để M5 quyết định; không có nhãn thì không đo được quyết định đúng hay sai.*

### Bảng câu hỏi nghiên cứu (RQ)

| RQ | Câu hỏi | Giả thuyết | Đo bằng | Mức |
|---|---|---|---|---|
| RQ1 | Kiến trúc lai luật + LLM có giảm tổng chi phí sai lầm so với chỉ-luật và chỉ-LLM không? | Có, và FNR không tệ hơn chỉ-luật | Chi phí kỳ vọng/ticket, FNR, FPR kèm khoảng tin cậy | Bắt buộc — đóng góp chính |
| RQ2 | Cách lấy xác suất nào từ LLM hiệu chỉnh tốt nhất? (bổ sung) | Hỏi nhiều lần hoặc đọc xác suất token tốt hơn để LLM tự nói con số | ECE, Brier, reliability diagram | Nên có — làm khi còn thời gian (M5 vẫn hoàn chỉnh khi không làm) |
| RQ3 | Chẩn đoán chủ động giảm bao nhiêu lượt hỏi lại? | Giảm rõ, không mất độ chính xác | Lượt hỏi lại TB, tỉ lệ giải quyết một lượt | Bắt buộc (gốc) |
| RQ4 | Bộ lọc injection dạng tầng có đạt recall như LLM với chi phí thấp hơn? (bổ sung) | Có | Recall, tỉ lệ chặn nhầm, độ trễ, chi phí | Xây dựng: bắt buộc (O1) · Thực nghiệm so sánh: mở rộng (Phase 11) |
| RQ5 | LLM local có thay được LLM API ở bước đơn giản? (bổ sung) | Có ở vai trò fast | F1 intent, tỉ lệ JSON hợp lệ, độ trễ | Xây dựng: bắt buộc (O1) · Thực nghiệm so sánh: mở rộng (Phase 11, cần GPU) |

RQ1 và RQ3 là phần bắt buộc của Objective 3. RQ2 là Nên có. Với RQ4 và RQ5, phần xây dựng thuộc Objective 1 và bắt buộc: B2 có cơ chế chặn injection hai tầng; LLM gateway hỗ trợ API và model local bằng cấu hình; router fast/strong hoạt động. Phần thực nghiệm so sánh (regex/mô hình phân loại/fine-tune/LLM; chạy model local thật so với API) là tùy chọn ở Phase 11.

Chi tiết: `docs/00-context/research-design.md`.

---

## 3. Kiến trúc tổng thể

Hệ thống có ba tầng trách nhiệm tách bạch: tầng agent hiểu và chuẩn bị hành động, tầng kiểm soát quyết định có được làm không, và chỉ một điểm duy nhất (B17) được gọi API ghi vào hệ thống ngoài.

**Sơ đồ khối:** Giao diện React (4 vai trò) → Backend FastAPI, gồm tầng agent (M1 M2 M3 M4) và tầng kiểm soát (M5 M6 M7) → B17 thực thi (điểm ghi duy nhất) → Mock AD/VPN/phần mềm/file. Song song, Postgres lưu ticket, audit, checkpoint.

*Đọc sơ đồ: LLM chỉ nằm trong tầng agent và lớp 2 của M5; nó không bao giờ tự gọi API ghi.*

| Module | Tên | Tầng | Bước workflow |
|---|---|---|---|
| M1 | Phân loại intent + trích slot | Agent | B3–B5, B11 |
| M2 | RAG Knowledge Base | Agent | B8–B10 |
| M3 | Tool + chẩn đoán chủ động | Agent | B6–B7 |
| M4 | Điều phối (LangGraph) | Agent | Toàn bộ |
| M5 | Bộ phân loại rủi ro — đóng góp chính | Kiểm soát | B12–B14 |
| M6 | Phê duyệt Human-in-the-Loop | Kiểm soát | B15–B16 |
| M7 | Audit log | Kiểm soát | B20, 8 điểm log |
| M8 | Khung đánh giá | Đánh giá | Ngoài luồng |

**Luồng chính (gốc):** B1 xác thực → B2 chặn injection → B3–B5 phân loại, tách ý → B6–B7 chẩn đoán → B8–B9 tra cứu → B10 chỉ cần trả lời? → B11 đủ thông tin? → B12–B14 đánh giá rủi ro → B15–B16 phê duyệt → B17 thực thi → B18–B19 xác nhận → B20 ghi audit. Có 14 trạng thái, 3 trạng thái chờ người (chờ bổ sung thông tin, chờ duyệt, chờ xác nhận).

> **Bổ sung ngữ cảnh (E9):** bản gốc ghi "9 mã thoát E0–E8". Sau khi bổ sung lớp bắt lỗi tổng quát ở tầng graph (xem mục 6.4 dưới đây, đồng bộ với `NGU-CANH-DAY-DU.md` Phần IV mục 7.2), hệ thống có **10 mã thoát E0–E9** — E9 là mã cho lỗi hệ thống *chưa lường trước*, xảy ra ở bất kỳ node nào, không gắn với một bước cụ thể.

> **Bổ sung ngữ cảnh (Tầng Monitor, M9):** bản gốc chỉ vẽ ba tầng nghiệp vụ (agent / kiểm soát / điểm thực thi B17). Nhưng tài liệu đã có sẵn rất nhiều thành phần làm chức năng giám sát — M7 (audit), mục 17.1 (session/trace/lineage), mục 17.5 (dashboard AI/LLMOps, drift), mục 16.3 (dashboard Trưởng bộ phận IT), mục 16.5 (`/api/health`) — nhưng rải rác, chưa được gọi tên là một tầng kiến trúc. Mục 17.9 (mới) hợp nhất các thành phần này thành **tầng Monitor**, một tầng thứ tư đứng **song song** với ba tầng nghiệp vụ (không xen vào giữa), chỉ đọc dữ liệu các tầng kia phát ra và không bao giờ ảnh hưởng ngược lại quyết định của agent. Sơ đồ khối đầy đủ 4 tầng, bảng module (thêm M9) và ranh giới "chỉ đọc, không quyết định" nằm ở mục 17.9 — xem tại đó thay vì lặp lại ở đây.

Các process chạy: postgres, qdrant, mock (cổng 8100), backend (8000), worker (quét hạn chờ), frontend (5173, bật sau). Dựng bằng một lệnh `make up`.

Chi tiết: `docs/02-spec/architecture.md`, `state-machine.md`.

---

## 4. Công nghệ và lý do chọn

LangGraph, FastAPI, PostgreSQL, vector DB, embedding + rerank là lựa chọn của tài liệu gốc; phần còn lại được chọn để hiện thực chúng với ít rủi ro nhất cho một nhóm sinh viên.

| Thành phần | Công nghệ | Nguồn | Vì sao |
|---|---|---|---|
| Điều phối workflow | LangGraph + PostgresSaver, `interrupt_before` | Gốc | Máy trạng thái có 3 chỗ chờ người tới 48 giờ; checkpoint Postgres giúp khởi động lại vẫn chạy tiếp đúng chỗ |
| API backend và mock | FastAPI | Gốc | Dùng Pydantic sẵn, có Swagger để demo trước khi có UI; mock dùng cùng framework |
| Kiểm tra dữ liệu | Pydantic v2 | Bổ sung | Một công cụ cho API, state của graph và output LLM; sai schema bị bắt ngay |
| Cơ sở dữ liệu | PostgreSQL + SQLAlchemy + Alembic | Gốc (Postgres) | Ticket, audit, checkpoint chung một DB; transaction giữ audit và trạng thái không lệch; `SELECT FOR UPDATE` chặn sự kiện đến muộn |
| LLM | `LLMClient` với hai vai trò fast/strong, structured output | Bổ sung | Chưa chốt provider; đổi API ↔ local chỉ đổi cấu hình; structured output tránh parse văn bản tự do |
| Vector DB | Qdrant | Gốc cho phép Chroma hoặc Qdrant | Chạy thành service riêng, lọc theo loại yêu cầu; ổn định khi nhiều process cùng dùng |
| Embedding + rerank | `bge-m3`, `bge-reranker-v2-m3` | Gốc (loại), bổ sung (model) | Hỗ trợ tiếng Việt, chạy local miễn phí, kết quả tái lập được |
| Tìm từ khóa | BM25 + gộp RRF | Gốc (hybrid search) | Bắt mã lỗi như "809" mà vector hay bỏ sót; RRF gộp mà không cần quy đổi thang điểm |
| Hiệu chỉnh xác suất | Platt/temperature scaling (scikit-learn) | Gốc | LLM thường tự tin quá mức; ngưỡng chỉ có nghĩa khi p đã hiệu chỉnh |
| Chặn injection tầng 2 | LLM phân loại riêng; mở rộng: mô hình phân loại nhỏ fine-tune tiếng Việt | Gốc; mở rộng bổ sung | Xem mục 6 (B2) và RQ4 |
| Gọi hệ thống ngoài | httpx + `call_with_retry` | Gốc (retry) | Timeout, dễ giả lập lỗi; tách lỗi hệ thống khỏi "không tồn tại" |
| Quét hạn chờ | APScheduler | Bổ sung | Chỉ cần quét định kỳ, không cần hàng đợi như Celery |
| Giao diện | React + Vite + TypeScript + Tailwind + TanStack Query | Bổ sung | 4 vai trò, hàng đợi duyệt có đồng hồ, polling gọn. Nhóm yếu frontend có thể dùng Streamlit nhưng khó phân quyền |
| Kiểm thử | pytest + ScriptedLLM + FakeClock + respx | Bổ sung | Test luồng tất định, không tốn tiền LLM; tua giờ để test timeout 30 phút/24 giờ/48 giờ trong vài giây |
| Triển khai | Docker Compose | Bổ sung | Một lệnh dựng đủ hệ thống; demo và chạy lại thực nghiệm giống nhau |

Chi tiết: `docs/02-spec/architecture.md`, `build/decisions.md`.

---

## 5. Thứ tự xây dựng

Xây theo phase tuần tự, mỗi phase chỉ mở khi phase trước qua cổng nghiệm thu; thứ tự đi từ phần rủi ro thấp, không phụ thuộc LLM, tới phần đóng góp chính cần dữ liệu có nhãn.

| Phase | Xây gì | Cổng nghiệm thu (tóm tắt — đầy đủ ở 5.1) | Vì sao ở vị trí này |
|---|---|---|---|
| 0 | Chốt quyết định: provider LLM, chi phí sai lầm, Q1 | Quyết định ghi vào `build/decisions.md` | Đổi sau khi code sẽ phải làm lại |
| 1 | Hạ tầng, DB, domain, mock, tool chẩn đoán | `make up` chạy; 245 test hợp đồng xanh | Mọi phần sau dựa vào; không cần LLM |
| 2 | Khung graph, cơ chế chờ người, B1, B20 | Dừng → khởi động lại → chạy tiếp đúng chỗ; sự kiện muộn bị chặn | Chứng minh cơ chế HITL trước khi có logic thật |
| 3 | Lát cắt VPN B1 → B20 | Một yêu cầu VPN đi hết luồng, audit đủ | Lộ lỗi tích hợp khi mới có một loại yêu cầu |
| 4 | Phê duyệt + audit 8 điểm | TC07, TC08, TC19, TC20, TC26, TC27 xanh | Không có audit điểm 4 thì không đo được RQ1 |
| 5 | Đủ 4 loại yêu cầu, B2, executor còn lại | Đủ 20 luật có test; TC13 xanh | Phủ đủ bảng luật §6.3 |
| 6 | M5 lớp LLM: 1 cách lấy p (tự nêu; dự phòng hỏi nhiều lần), calibrator, toán quyết định | Cổng dữ liệu D2 đạt; probe phân phối p | Trái tim của M5 (Objective 2) và RQ1; cần đủ ca đi xuống LLM để fit calibrator |
| 7 | L2 + giao diện | Checklist demo 12 ca | Cần cho demo, không cần cho số liệu |
| 8 | Harness, chọn ngưỡng, đóng băng code | Chạy 150 kịch bản không lỗi; tag freeze | Chỉ chọn ngưỡng khi code không đổi nữa |
| 9 | Gán nhãn 3 mức, Kappa, chia tập | Kappa ≥ 0.6; không họ kịch bản nào ở hai tập | Phải xong trước khi chạm tập test |
| 10 | Thực nghiệm bắt buộc RQ1, RQ3 | Đủ bảng + biểu đồ; người thứ hai chạy lại ra cùng số | Kết quả chính của đồ án |
| 11 | Thực nghiệm mở rộng RQ2, RQ4, RQ5 (tùy chọn) | Như phase 10 | Chỉ khi phase 10 có số liệu |

> **Chế độ xây đã chốt (25/09/2026): code trước, gắn API sau.** Phase 1–7 chạy bằng `ScriptedLLM`; mọi phần cổng cần LLM thật (demo cổng 3, cổng 5 thủ công, probe cổng 6) dồn về **mốc G** sau Phase 7, trước Phase 8. Chi tiết và đánh đổi: `build/decisions.md` mục 4.

### 5.1. Chi tiết từng phase

Mỗi phase dưới đây ghi: mục tiêu, việc làm (mã task trong `backlog.md`), điều kiện mở, sản phẩm bàn giao, cổng nghiệm thu đầy đủ, việc triển khai đi kèm và rủi ro chính. Cổng chỉ đạt khi mọi ô được đánh dấu và người xác nhận không phải người làm chính.

#### Phase 0 — Chốt quyết định

**Mục tiêu:** khóa các lựa chọn mà nếu đổi sau khi code sẽ phải làm lại.

**Việc làm:** họp nhóm theo `build/decisions.md`; chốt các mục còn mở. Các vấn đề trước đây định hỏi GVHD (Q1–Q14) đã được nhóm tự quyết ở `decisions.md` mục 2 và chỉ **báo cáo** GVHD trong báo cáo tuần.

**Mở khi:** ngay.

**Bàn giao:** `build/decisions.md` cập nhật; `PROGRESS.md` ghi phase đang mở.

**Cổng 0:**
- Chốt provider LLM và ngân sách; chạy thử được một lời gọi structured output bằng API key thật.
- Q1 (TC09/TC10 theo bảng luật) và Q9 (10:1, độ nhạy 5/10/20) đã chốt ở `decisions.md` mục 2.
- Xác định mức phần cứng (mục 11).
- Đã đưa các quyết định Q1–Q14 vào báo cáo tuần gửi GVHD (báo cáo, không chờ trả lời).

**Rủi ro:** kéo dài họp. Giới hạn một buổi; điểm chưa chốt thì dùng mặc định trong tài liệu và ghi "tạm".

#### Phase 1 — Nền móng

**Mục tiêu:** hạ tầng, cơ sở dữ liệu, mô hình dữ liệu, hệ thống giả lập và tool chẩn đoán chạy được, chưa cần LLM.

**Việc làm:** T01 → T02 → T03 → T04; song song T05 → T06.

**Mở khi:** cổng 0 đạt.

**Bàn giao:** repo có Docker Compose, CI, migration, mock đủ endpoint, 12 tool chẩn đoán, 245 test hợp đồng.

**Cổng 1 — tự động:**
- `make up` chạy 5 service; backend và mock trả `/health` 200; migration chạy trên DB trống.
- `make test` xanh: mọi cặp trạng thái (có trong bảng thì qua, không có thì bị chặn); 6 chuyển bị cấm đều bị chặn.
- `call_with_retry`: 404 → không lỗi, không retry; 500 liên tục → đúng 3 lần gọi, chờ 1 giây rồi 2 giây; danh sách rỗng → `[]`.
- Hash của Action không đổi khi đổi thứ tự khóa.
- CI trên GitHub xanh.

**Cổng 1 — thủ công và tài liệu:**
- Người xác nhận gọi tay 12 tool với dữ liệu seed, đối chiếu với bảng kết quả mong đợi.
- Bật lỗi 500 qua `/_admin/faults` → tool báo lỗi hệ thống; tắt lỗi → chạy lại bình thường.
- Ghi audit thiếu trường bắt buộc bị từ chối (có test).

**Triển khai:** Dockerfile, Compose, CI chạy test; dựng VM staging.

**Rủi ro:** lệch phiên bản LangGraph — pin phiên bản ngay ở T01.

#### Phase 2 — Khung agent

**Mục tiêu:** chứng minh cơ chế chờ người hoạt động trước khi có logic thật.

**Việc làm:** T11 — graph với node giả, định tuyến riêng từng node, hàm `goto`, guard sự kiện muộn, B1, B20.

**Mở khi:** cổng 1 đạt.

**Bàn giao:** graph chạy được từ B1 tới B20 với node giả; dịch vụ ticket.

**Cổng 2:**
- Tạo ticket → graph dừng đúng ở node chờ → khởi động lại backend → gửi sự kiện → chạy tiếp đúng chỗ.
- Mọi trạng thái ra của mỗi node có đích định tuyến; không lặp, không lỗi thiếu khóa.
- Sự kiện đến khi ticket không ở trạng thái chờ tương ứng → 409, audit ghi `late_event`, trạng thái không đổi (cả 3 trạng thái chờ).
- ~~Node gặp lỗi bất ngờ → ticket chuyển E2, không kẹt.~~

> **Bổ sung ngữ cảnh (E9):** dòng gốc ở trên dùng E2 cho "node gặp lỗi bất ngờ" — nhưng theo Ma trận xử lý ngoại lệ của `NGU-CANH-DAY-DU.md` Phần IV mục 7, **E2 chỉ dành riêng cho lỗi hệ thống của tool/RAG đã hết lượt retry** (B6–B8), không phải cho một exception bất kỳ ném ra từ một node bất kỳ. Dùng chung E2 cho cả hai loại sẽ làm mất khả năng phân biệt "RAG chết" với "bug trong code node". Tiêu chí đúng của cổng 2, sau khi đồng bộ với mục 6.4 dưới đây, phải là:
>
> **Node gặp lỗi bất ngờ (unhandled exception, không thuộc loại đã lường trước) → ticket chuyển `S_ESCALATED` với `exit_code=E9`, không kẹt, không làm crash worker.**
>
> Vì Phase 2 build khung graph với **node giả** (chưa có logic thật), đây chính là nơi tự nhiên nhất để dựng lớp bắt lỗi tổng quát `with_error_boundary` (mục 6.4) — bọc mọi node ngay từ lúc khung graph còn trống, để các phase sau tự động thừa hưởng mà không cần nhớ thêm try/except cho từng node mới.

- B1: sai 1 lần → đóng bình thường; sai 5 lần trong 10 phút → chặn và báo Trưởng BP (TC24, TC25).

**Thủ công:** đọc bảng checkpoint trong Postgres, xác nhận mỗi ticket một luồng riêng.

**Rủi ro:** đặt việc gửi thông báo trong node chờ → chạy hai lần khi resume. Có test đếm bản ghi.

#### Phase 3 — Lát cắt VPN đầu–cuối

**Mục tiêu:** một loại yêu cầu đi hết B1 → B20 với LLM thật, để lộ lỗi tích hợp sớm.

**Việc làm:** T07, T08, T16 song song → T12, T13 → T14 → T15.

**Mở khi:** cổng 2 đạt và cổng nội dung K1 (5 tài liệu KB VPN).

**Bàn giao:** VPN chạy đủ các nhánh tự làm, chỉ trả lời, hỏi lại, lỗi hệ thống, không có căn cứ; API cho nhân viên; worker hạn chờ.

**Cổng 3 — tự động (LLM giả lập):**
- TC02: khớp luật R20, gia hạn gọi đúng 1 lần, ticket đóng, đường đi "tự làm".
- TC04, TC05: trả lời kèm trích dẫn, không sinh Action.
- TC06: 0 câu hỏi lại, thiết bị suy từ chẩn đoán; tắt chẩn đoán chủ động → agent phải hỏi.
- RAG lỗi → E2; điểm thấp → E3 (TC28, TC16).
- Mọi luật VPN có test; M5 không nhận câu người dùng; luật khớp thì không gọi LLM.
- Hỏi lại tối đa 3 lượt, mỗi lượt tối đa 2 thông tin; lạc đề 2 lần hoặc quá 24 giờ → E4.

**Cổng 3 — thủ công và tài liệu:**
- Demo 4 ca trên với LLM thật, quay màn hình — dùng làm bản demo cho GVHD.
- Phân loại intent VPN đúng ≥ 18/20 câu tiếng Việt (có viết tắt, không dấu).
- Biểu đồ phân phối điểm truy hồi và ngưỡng đề xuất đã cập nhật vào `policy.json`.
- Audit của 4 ticket demo đủ điểm log 1, 2, 3, 4, 7, 8.

**Triển khai:** bật triển khai staging tự động khi merge; demo trên staging.

**Rủi ro:** chất lượng LLM tiếng Việt thấp → sửa prompt trước khi mở rộng sang 3 loại còn lại.

#### Phase 4 — Phê duyệt và audit

**Mục tiêu:** vòng Human-in-the-Loop hoàn chỉnh: chọn người duyệt, xung đột lợi ích, hạn chờ, nhắc, hết hạn, duyệt muộn, ghi đè, đủ 8 điểm log.

**Việc làm:** T18 → T19. Kịch bản thử dùng VPN cho thiết bị chưa đăng ký (luật R17 → cần duyệt; tài liệu cũ ghi R22, xem `decisions.md` N4).

**Mở khi:** cổng 3 đạt.

**Bàn giao:** B15, B16, API duyệt, nhắc duyệt trong worker, API ghi đè, script kiểm tra audit.

**Cổng 4:**
- Duyệt → thực thi; từ chối có lý do → đóng "bị từ chối"; từ chối không lý do → lỗi 422.
- TC19: người gửi chính là người duyệt → chuyển Trưởng BP; thêm 2 ca xung đột còn lại (người gửi là cấp trên của người duyệt; hành động tác động tài khoản của người duyệt).
- TC20: tua giờ quá 30 phút → E6, không có lời gọi thực thi nào.
- TC26: sửa Action sau khi duyệt → E5, không thực thi.
- TC27: bấm duyệt sau khi đã hết hạn → 409, phiếu đánh dấu "bỏ qua vì muộn".
- Luật deny không bao giờ tạo phiếu duyệt; L2 gọi API duyệt → 403.
- Nhắc lần 1 ở 50% thời hạn, lần 2 ở 80% kèm người dự phòng; mở trang chi tiết lần đầu ghi thời điểm xem.
- TC23: ghi đè tạo bản ghi, không đổi trạng thái ticket.
- Script kiểm tra audit: 100% ticket e2e đủ trường ở mọi điểm log áp dụng; log không chứa token hay mật khẩu.

**Rủi ro:** hai tiến trình (API và worker) cùng xử lý một ticket. Khóa theo ticket bằng `SELECT FOR UPDATE`, có test tranh chấp.

#### Phase 5 — Đủ 4 loại yêu cầu

**Mục tiêu:** phủ toàn bộ bảng luật §6.3 và các nhánh ngoại lệ còn lại.

**Việc làm:** T22a (đủ 20 luật), T20 (phân loại đủ 4 loại + tách ticket), T23 (chặn injection), T24 (executor còn lại + hoàn tác).

**Mở khi:** cổng 4 đạt và cổng nội dung K2 (≥ 16 tài liệu KB).

**Bàn giao:** agent xử lý đủ 4 loại; ticket nhiều ý; chặn injection; hoàn tác.

**Cổng 5 — tự động:**
- TC01, TC03, TC07, TC08, TC12, TC13, TC15, TC16, TC17, TC18, TC21, TC28 xanh.
- Phần mềm có phí lỗi khi cài → không gọi hoàn tác (hành động không hoàn tác được).
- Ticket cha tổng hợp đúng cả 6 trường hợp của bảng B5 gốc và tổ hợp có cả ba loại kết quả.
- 20 luật đều có ca khớp và ca suýt khớp; nhiều luật khớp → luật chặt nhất thắng.

**Cổng 5 — thủ công (LLM thật):**
- Intent macro-F1 ≥ 0,85 trên 45 câu mẫu (10 câu mỗi loại × 4 loại + 5 ngoài phạm vi; macro-F1 tính trên 5 lớp — chốt 15/10/2026). Bộ câu này chỉ để đo, không dùng chỉnh ngưỡng hay prompt.
- Chặn ≥ 13/15 câu tấn công; không chặn nhầm quá 1/30 câu thường; thông báo trung tính.
- Recall@5 ≥ 0,8 trên 30 câu kiểm tra truy hồi.
- Ghi chú bàn giao của ca E7 nêu rõ bước đã làm, đã hoàn tác tới đâu, phần L2 cần làm tay.

**Rủi ro:** câu nhiều ý bị tách sai. Có bộ 10 câu nhiều ý riêng trong probe.

#### Phase 6 — M5 lớp LLM (đóng góp chính)

**Mục tiêu:** lớp 2 của M5 hoàn chỉnh — một cách lấy p bắt buộc, calibrator, toán quyết định theo chi phí; sẵn sàng cho RQ1. Chuỗi bắt buộc: xác suất thô → calibrator → hai ngưỡng → tự làm/chờ duyệt/chuyển L2.

**Việc làm:** T22b — estimator theo cách LLM tự nêu xác suất (gốc) kèm quy tắc dự phòng hỏi nhiều lần (k = 5); calibrator Platt/temperature; `decision_math`; 4 chiến lược + `hybrid_guarded` (Q8: code ở Phase 6, chạy ở Phase 10). Cách đọc xác suất token và việc so sánh cả ba cách thuộc Phase 11 (RQ2).

**Mở khi:** cổng 5 đạt và cổng dữ liệu D2 (≥ 80 kịch bản, trong đó đủ họ kịch bản đi xuống LLM — mục 8.2).

**Bàn giao:** M5 hoàn chỉnh; báo cáo probe phân phối p.

**Cổng 6 — tự động:**
- Ca không luật nào khớp (TC37 và họ kịch bản bổ sung): quyết định bởi LLM, định tuyến đúng theo ngưỡng.
- Chiến lược chỉ dùng cho so sánh bị từ chối khi không ở chế độ đánh giá.
- Mọi ticket qua M5 có `decided_by`; có `raw_prob` và phương pháp lấy p khi quyết định bởi LLM.
- Prompt gửi tới LLM rủi ro không chứa câu người dùng — kiểm bằng cách chụp prompt thật.
- Toán quyết định: 8 test của `decision_math` xanh (ngưỡng suy từ chi phí, cận FNR, ECE, Brier).

**Cổng 6 — thủ công:**
- Chạy LLM thật trên ~30 kịch bản đi xuống LLM, vẽ phân phối p. Nếu hơn 60% giá trị dồn vào 2 mức → bật hỏi nhiều lần (k = 5) và vẽ lại; ghi cách đã chọn vào `policy.json`.
- Người không xây M5 đọc 10 lý do rủi ro ngẫu nhiên, xác nhận đọc hiểu được.

**Rủi ro:** quá ít ca đi xuống LLM → không fit được calibrator và thiếu số liệu cho RQ1. Kiểm cổng D2 theo số ca đi xuống LLM, không chỉ theo tổng số kịch bản.

#### Phase 7 — L2 và giao diện

**Mục tiêu:** đủ màn hình cho 4 vai trò để demo; các tính năng "Phải có" ở mục 16.

**Việc làm:** T31 (L2) → T25 (giao diện nhân viên + L1) → T30 (L2, dashboard, policy).

**Mở khi:** cổng 4 đạt (có thể chạy song song với Phase 5–6).

**Bàn giao:** giao diện 4 vai trò; tài khoản demo.

**Cổng 7 — tự động:**
- Ca bị deny: L2 chọn "hoàn tất" → 422; "mở ticket mới" tạo ticket chạy từ B1, liên kết ticket cũ.
- L2 đóng ticket ghi điểm log 8 với lý do đóng đúng cho cả ca kỹ thuật và ca bị deny.
- Frontend lint và build sạch.

**Cổng 7 — thủ công (người không làm giao diện chạy, ghi biên bản):**
- Trên giao diện: TC02, TC06, TC07 (duyệt), TC08 (từ chối có lý do), TC20 (SLA rút còn 2 phút), 1 ca L2 xử lý.
- L1 không thấy trang policy; lưu policy sai → báo lỗi rõ từng dòng.
- Theme sáng, chữ đọc được trên máy chiếu.

**Triển khai:** reverse proxy + HTTPS, frontend bản build tĩnh, tài khoản demo 4 vai trò.

**Rủi ro:** giao diện ngốn thời gian của luồng chính — chỉ làm "Nên có" sau khi "Phải có" xong.

#### Phase 8 — Harness, calibration, đóng băng

**Mục tiêu:** công cụ chạy thực nghiệm tái lập được; code đóng băng trước khi đo.

**Việc làm:** T28 (harness), T27 (fit calibrator + chọn ngưỡng theo chi phí — code), T29 (công thức chỉ số + báo cáo) song song → T32 (e2e toàn bộ); T34 (đồng bộ sơ đồ drawio).

**Mở khi:** cổng 6 đạt và cổng dữ liệu D3 (≥ 120 kịch bản).

**Bàn giao:** harness, script chọn ngưỡng, script báo cáo, tag `v1.0-freeze`.

**Cổng 8 — tự động:**
- E2E xanh toàn bộ TC01–TC28 và các kịch bản bổ sung.
- Harness chạy 20 kịch bản hai lần với cache → kết quả giống hệt.
- Fit calibrator hoặc chọn ngưỡng trên tập test → bị từ chối; với dữ liệu tổng hợp, Platt scaling làm giảm ECE.
- Chọn ngưỡng trên dữ liệu tổng hợp đã hiệu chỉnh cho ngưỡng dưới gần t_low* (mục 7.3).
- Mỗi công thức chỉ số có unit test trên dữ liệu tính tay.

**Cổng 8 — thủ công và tài liệu:**
- Chạy thử toàn bộ ma trận thực nghiệm trên 20 kịch bản bất kỳ để chắc mọi cấu hình chạy được — không đọc kết quả.
- Sơ đồ drawio và đặc tả đồng bộ thuật ngữ.
- Tag `v1.0-freeze`; từ đây chỉ merge sửa lỗi.

**Triển khai:** đóng băng staging; sao lưu; ghi lại cấu hình máy chạy thực nghiệm.

**Rủi ro:** sửa code sau khi đã nhìn kết quả → số liệu thiếu khách quan. Sau tag, mọi thay đổi phải ghi lý do.

#### Phase 9 — Gán nhãn và chia tập

**Mục tiêu:** bộ dữ liệu có nhãn 3 mức, đủ cỡ mẫu (mục 8.2), chia tập không rò rỉ.

**Việc làm:** T35 (gán nhãn hai lượt) → T36 (chia tập).

**Mở khi:** cổng 8 đạt và cổng dữ liệu D4 (150–180 kịch bản).

**Bàn giao:** file dữ liệu đã khóa, `SPLIT.md` có mã băm.

**Cổng 9:**
- Kappa trên route ≥ 0,6, hoặc có biên bản họp thống nhất tiêu chí và gán lại phần bất đồng.
- Chia theo họ kịch bản ~65/35; không họ nào nằm ở cả hai tập; mỗi tập có đủ nhóm thường, nhạy cảm, biên, ngoại lệ.
- Tập calibration có ≥ 50 ca đi xuống LLM và ≥ 30 ca "chuyển L2"; tập test có ≥ 60 ca "cần người". Không đạt → soạn thêm trước khi sang Phase 10.
- Mã băm file dữ liệu được CI kiểm tra.

**Rủi ro:** nhãn chép theo luật. Người gán nhãn không mở `policy.json`.

#### Phase 10 — Thực nghiệm bắt buộc (RQ1, RQ3)

**Mục tiêu:** kết quả chính của đồ án.

**Việc làm:** T37 (fit calibrator, chọn ngưỡng trên calibration) → T38 (chạy ma trận mục 10 trên tập test) → T39 (bảng, biểu đồ). Người chạy không phải người xây M5.

**Mở khi:** cổng 9 đạt.

**Bàn giao:** thư mục báo cáo thực nghiệm; policy phiên bản mới chứa ngưỡng đã chọn.

**Cổng 10:**
- Calibrator ghi rõ đã fit trên tập calibration; ngưỡng nằm trong policy phiên bản mới, kèm t_low* và phân tích độ nhạy.
- Đủ kết quả và cấu hình chạy cho mọi lần chạy trong ma trận.
- Xuất: bảng so sánh các phương án, bảng ablation, biểu đồ hiệu chỉnh trước/sau, biểu đồ chi phí theo ngưỡng, bảng `decided_by`, 10 ca sai tiêu biểu.
- FNR báo cáo kèm cận trên tin cậy 95%.
- Người thứ hai chạy lại một lần bất kỳ từ cấu hình đã lưu, ra đúng kết quả.

**Rủi ro:** kết quả không ủng hộ giả thuyết. Vẫn báo cáo trung thực — phân tích vì sao cũng là đóng góp.

#### Phase 11 — Thực nghiệm mở rộng RQ2, RQ4, RQ5 (tùy chọn)

**Mục tiêu:** các thực nghiệm so sánh sâu. Phần xây dựng tương ứng đã bắt buộc ở các phase trước và không chờ phase này: B2 chặn injection hai tầng (Phase 5); LLM gateway hỗ trợ API và model local bằng cấu hình, router fast/strong (Phase 3); M5 với một cách lấy p (Phase 6).

**Mở khi:** cổng 10 đạt và còn thời gian; RQ5 cần phần cứng mức 1 trở lên.

**Việc làm:**
- RQ2: thêm cách hỏi nhiều lần và đọc xác suất token → so cả ba cách lấy p, trước và sau hiệu chỉnh.
- RQ4: soạn bộ injection tiếng Việt → đo mô hình phân loại có sẵn → fine-tune → so regex/mô hình có sẵn/fine-tune/LLM.
- RQ5: chuyển vai trò fast sang model local thật → lặp lại probe intent và benchmark định tuyến (mục 17.5).

**Cổng 11:**
- RQ2: bảng ECE, Brier và reliability diagram cho cả ba cách lấy p, trước và sau hiệu chỉnh.
- RQ4: bộ injection chia tập theo mẫu tấn công, không rò rỉ giữa huấn luyện và kiểm tra; bảng recall, tỉ lệ chặn nhầm, độ trễ, chi phí cho từng phương án.
- RQ5: bảng API và local — intent F1, tỉ lệ JSON hợp lệ, độ trễ, chi phí.

**Rủi ro:** làm mở rộng khi kết quả chính chưa xong. Không mở Phase 11 trước cổng 10.

Luồng nội dung chạy song song với luồng code: tài liệu KB (cổng K1: 5 tài liệu VPN trước Phase 3; K2: 16 tài liệu trước Phase 5) và bộ kịch bản (D1–D4: 40 → 80 → 120 → 150–180 kịch bản).

Hai quy tắc tách vai (gốc): người xây M5 không tự chạy thực nghiệm và không tự xác nhận cổng của M5; người kiểm giao diện không phải người làm giao diện.

Chi tiết từng task, file cần đọc, tiêu chí đạt: `docs/01-plan/plan.md`, `backlog.md`.

---

## 6. Xây từng nhánh workflow

Mỗi nhánh là một node LangGraph viết đúng theo mã giả gốc; mọi lần đổi trạng thái đi qua hàm `goto()` (kiểm tra chuyển hợp lệ + ghi audit trong cùng transaction), và mọi nhánh kết thúc ở B20.

| Nhánh | Làm gì | Dùng gì | Lưu ý quan trọng |
|---|---|---|---|
| B1 Xác thực | Gọi mock AD; sai 1 lần → đóng bình thường; sai 5 lần/10 phút → cảnh báo Trưởng BP | httpx, bảng `auth_failures` | Một lần sai không phải sự cố an ninh; AD lỗi → 503, không tạo ticket |
| B2 Chặn injection → E0 | Tầng 1 regex; tầng 2 phân loại riêng | `injection_patterns.json`, LLM fast | Lời gọi tách khỏi agent chính; thông báo trung tính, không tiết lộ đã phát hiện |
| B3–B5 Phân loại, tách ý → E1 | LLM trả intent + đoạn câu + slot; nhiều ý → ticket con quay lại B3 | Structured output, mỗi con một `thread_id` | Mỗi ý được đánh giá rủi ro riêng; cha đóng khi mọi con xong, gom một tin |
| B6–B7 Chẩn đoán → E2 | Code gọi 3 tool theo loại yêu cầu, suy slot từ kết quả | httpx, `call_with_retry` (2 lần, backoff 1s/2s) | 404/rỗng là dữ liệu hợp lệ, không phải lỗi; LLM không tự chọn tool |
| B8–B9 Tra cứu → E2/E3 | Tìm hybrid, rerank, lấy top 5; điểm < 0.6 → E3 | Qdrant, `bge-m3`, BM25, RRF, `bge-reranker-v2-m3` | RAG lỗi hạ tầng là E2, không phải E3 |
| B10 Chỉ cần trả lời | LLM phân biệt thông tin/hành động; trả lời chỉ từ tài liệu | LLM fast + strong | Code hậu kiểm trích dẫn; không có trích dẫn hợp lệ → E3 |
| B11 Đủ thông tin? → E4 | So bảng slot; thiếu → hỏi ≤ 2 slot/lượt, ≤ 3 lượt; đủ → dựng Action | `build_action` (hàm thuần), `clarify_node` | Lạc đề 2 lần → E4; không hỏi lại slot đã suy từ chẩn đoán |
| B12–B14 Rủi ro → E5 | Luật trước, LLM sau (mục 7) | `policy.json`, policy engine, LLM strong, calibrator | M5 không bao giờ đọc câu người dùng |
| B15–B16 Phê duyệt → E6 | Chọn người duyệt, kiểm 3 xung đột lợi ích, băm Action, chờ; nhắc 50%/80%; hết 30 phút → E6 | SHA-256, bảng `approvals`, APScheduler, `on_late_event` | Hết hạn không bao giờ tự làm; duyệt muộn bị bỏ qua (409) |
| B17–B18 Thực thi → E7/E5 | Kiểm tra lại luật, so hash, gọi API ghi từng bước, lỗi → hoàn tác nếu được | Executor httpx, `TransactionLog` | Không retry lệnh ghi; deny lúc kiểm tra lại luôn chặn |
| B19 Xác nhận → E8 | Chờ người dùng; im lặng 48h → tự đóng, nhãn riêng | `confirm_node` | Tự đóng không được tính là xác nhận thật |
| B20 Audit | Ghi điểm log 8 với lý do đóng | Bảng `audit_logs` | Mọi nhánh, kể cả lỗi và escalate |
| E0–E8 → L2 | Tạo bản ghi escalate có mức ưu tiên + ghi chú bàn giao | Bảng `escalations`, UI L2 | Ca deny: L2 chỉ xác nhận từ chối hoặc mở ticket mới |

> **Bổ sung ngữ cảnh (E9):** dòng cuối bảng trên mở rộng thành **E0–E9 → L2**, vì E9 (lỗi hệ thống không lường trước, xem mục 6.4) cũng hội tụ về cùng hàng đợi L2 như mọi mã thoát khác.

### Ba điểm hiện thực dễ sai

1. **Định tuyến riêng từng node.** Sau B12 với rủi ro trung bình, ticket vẫn ở `S_ASSESSING`; route chung theo trạng thái sẽ lặp vô hạn.
2. **Việc cần làm trước khi chờ nằm ở node đứng trước.** Node chờ dùng `interrupt_before` (gốc); đặt gửi thông báo trong node chờ sẽ chạy hai lần khi resume.
3. **Hạn chờ do node đứng trước đặt**, worker phát sự kiện timeout qua cùng guard với sự kiện của người.

> **Bổ sung ngữ cảnh (E9) — điểm dễ sai thứ tư:** wrap từng node bằng try/except thủ công, rải rác trong logic nghiệp vụ của node, thay vì bọc ở **tầng build graph** (một hàm `with_error_boundary` áp cho toàn bộ `ALL_NODES` khi gọi `builder.add_node(...)`, xem mục 6.4). Làm thủ công dễ bỏ sót node mới thêm sau này, và dễ lẫn lộn giữa lỗi nghiệp vụ đã lường trước (nên trả đúng mã E0–E8 từ bên trong node) với lỗi hệ thống chưa lường trước (phải luôn là E9, bắt ở lớp bọc ngoài).

Chi tiết mã giả từng bước: `docs/02-spec/workflow-steps.md`.

### 6.4. E9 — lớp bắt lỗi tổng quát ở tầng graph (bổ sung)

> **Bổ sung ngữ cảnh (E9), đồng bộ với `NGU-CANH-DAY-DU.md` Phần IV mục 7.2 và `NGU-CANH-DAY-DU.md`.**

Chín mã thoát E0–E8 ở bảng mục 6 đều là lỗi *đã lường trước*, mỗi loại đã có xử lý riêng chi tiết hơn một khối try/except chung: B6/B8 dùng `call_with_retry` để phân biệt lỗi hệ thống tạm thời với kết quả rỗng, B17 dùng `TransactionLog` để rollback có điều kiện theo `reversible`, B16 có fail-safe timeout, v.v. Nhưng các try/except đó chỉ nằm *bên trong* từng node, cho đúng loại lỗi mà node đó lường trước được. Nếu một node ném ra một exception nằm *ngoài* những gì nó tự bắt (một bug, một kiểu dữ liệu sai, một thư viện thứ ba ném lỗi lạ, một lỗi parse JSON output của LLM chưa được `LLMClient` bắt...), sẽ không có mã thoát nào trong E0–E8 khớp — và nếu không xử lý, exception đó có thể làm crash worker đang chạy graph nền (mục 14.3) hoặc để ticket kẹt lại ở một trạng thái dở dang không ai biết.

`E9` là lưới an toàn cuối cùng cho đúng nhóm lỗi này — **không thay thế** bất kỳ try/except cụ thể nào đã có, chỉ bổ sung một tầng bọc ngoài cùng ở mức graph, áp dụng cho **mọi node**, không riêng một bước nào:

```python
def with_error_boundary(node_fn):
    """Bọc MỌI node của graph bằng một lớp bắt lỗi chung khi build graph.
    KHÔNG thay thế các try/except cụ thể đã có bên trong từng node (call_with_retry
    ở B6/B8, TransactionLog.rollback ở B17...) — những try/except đó vẫn xử lý
    đúng các lỗi đã lường trước như cũ, với mã thoát E0-E8 tương ứng. Lớp này chỉ
    là lưới an toàn cho lỗi CHƯA lường trước, để không node nào có thể làm crash
    worker hoặc để ticket kẹt vô thời hạn ở một trạng thái dở dang không ai biết.
    """
    @wraps(node_fn)
    def wrapped(state):
        try:
            return node_fn(state)
        except Exception as e:
            log(state, node_fn.__name__,
                f"unhandled_exception: {type(e).__name__}: {e}",
                level="error", include_traceback=True)
            return goto(S_ESCALATED, exit_code="E9",
                         escalation_note=f"Lỗi hệ thống không lường trước tại {node_fn.__name__}")
    return wrapped


builder = StateGraph(TicketState)
for node_name, node_fn in ALL_NODES.items():   # {"b1_authenticate": b1_authenticate, "b2_screen": b2_screen, ...}
    builder.add_node(node_name, with_error_boundary(node_fn))
```

**Nên dựng ở Phase 2** (mục 5.1), cùng lúc với khung graph node giả, `goto()` và guard sự kiện muộn — đây là lý do cổng 2 ở mục 5.1 được viết lại để yêu cầu `exit_code=E9` thay vì tái dùng E2. Dựng sớm ở Phase 2 nghĩa là mọi node thật thêm vào từ Phase 3 trở đi tự động được bọc, không cần nhớ thêm gì ở các phase sau.

**Vì sao bọc ở tầng build graph thay vì thêm try/except thủ công vào từng node:**
1. Không node nào bị bỏ sót — một node mới thêm sau này tự động được bọc, không cần nhớ thêm try/except mỗi lần viết node mới.
2. Tách bạch rõ hai loại lỗi: lỗi nghiệp vụ đã lường trước (node tự try/except, tự trả về đúng `goto()` với mã E0-E8 tương ứng) và lỗi hệ thống chưa lường trước (bị lớp bọc ngoài bắt, luôn là E9) — không lẫn hai loại vào cùng một exit code.
3. `except Exception` ở lớp bọc **không** can thiệp vào luồng điều khiển hợp lệ: các node khác trả kết quả qua `return goto(...)` như bình thường, đó là giá trị trả về chứ không phải exception, nên không bao giờ bị lớp bọc này nuốt mất.
4. Khớp với nguyên tắc "mọi lần đổi trạng thái đi qua `goto()`" đã có ở đầu mục 6 — mở rộng nguyên tắc đó cho cả trường hợp lỗi ngoài dự kiến.

**Khác biệt với E2:** E2 là lỗi hạ tầng đã biết trước loại (tool/RAG timeout, 5xx, mất kết nối) và đã hết lượt retry theo đúng chính sách `call_with_retry`. E9 là lỗi *chưa biết trước loại*, không đi qua bất kỳ retry nào — xảy ra một lần là escalate ngay, vì không có chính sách retry nào được thiết kế cho một loại lỗi chưa biết trước.

**Test case cần thêm (đưa vào cổng 2, mục 5.1):** TC29 — ép một node bất kỳ ném ra một exception không thuộc các loại đã lường trước (ví dụ lỗi parse JSON output của LLM) → kỳ vọng: ticket chuyển sang `S_ESCALATED` với `exit_code=E9`, audit log có traceback, worker không crash, các ticket khác đang chạy song song không bị ảnh hưởng.

---

## 7. M5 — quyết định khi nào cần người

M5 quyết định bằng hai lớp: luật cứng chạy trước và có quyền phủ quyết; LLM chỉ chạy khi không luật nào khớp, cho ra xác suất p đã hiệu chỉnh, rồi so với hai ngưỡng suy ra từ chi phí sai lầm.

**Sơ đồ quyết định:** Action + ngữ cảnh → Lớp 1: 20 luật → không khớp / khớp allow / khớp approval_required / khớp deny → nếu không khớp → Lớp 2: LLM → p → hiệu chỉnh → so ngưỡng → **Tự làm** (p < t_low) / **Chờ duyệt** (giữa hai ngưỡng) / **Chuyển L2** (p > t_high). Luật `allow` → Tự làm; `approval_required` → Chờ duyệt; `deny` → Chuyển L2.

**Định nghĩa p (gốc):** xác suất hành động này không nên được agent tự làm mà không có người duyệt, biết Action, ngữ cảnh người gửi, kết quả chẩn đoán và tài liệu tra được. M5 không bao giờ đọc câu người dùng, nên câu tấn công lọt qua B2 cũng không thay được quyết định của luật.

### 7.1. Lớp 1 — luật

20 luật mã hóa đúng bảng §6.3 của tài liệu gốc (`config/policy.json`), giữ id R01, R07, R12 như ví dụ gốc.

Nhiều luật cùng khớp → luật chặt nhất thắng (`deny` > `approval_required` > `allow`). Thiếu dữ kiện → điều kiện không thỏa, nên luật allow không bao giờ khớp nhờ thiếu dữ liệu.

### 7.2. Lớp 2 — cách lấy p: bắt buộc và so sánh RQ2 (bổ sung)

**Bắt buộc (Phase 6):** LLM tự nêu xác suất — cách của tài liệu gốc, chạy được với mọi provider. Quy tắc dự phòng: nếu hơn 60% giá trị p dồn vào 2 mức, chuyển sang hỏi nhiều lần (k = 5), vì calibrator không hiệu chỉnh được trên giá trị quá thô. **Tùy chọn (RQ2, Phase 11):** so sánh cả ba cách trong bảng dưới.

| Cách | Làm thế nào | Ưu | Nhược |
|---|---|---|---|
| Tự nêu (gốc) | LLM trả con số trong JSON | Một lời gọi, mọi provider | Giá trị thô (0.1/0.7/0.9), hiệu chỉnh kém |
| Hỏi nhiều lần | Hỏi 5 lần (k = 5), temperature 0.7; p = tỉ lệ lần trả lời "cần người" | Không cần logprob, p mịn hơn | Tốn 5 lời gọi |
| Xác suất token | Trả lời một token "Có"/"Không"; p = xác suất chuẩn hóa của "Có" | Mịn nhất, một lời gọi | Cần provider cho đọc logprob (LLM local có) |

Cách nào cũng qua cùng calibrator Platt hoặc temperature scaling, fit trên tập calibration. Vì vậy M5 luôn hoàn chỉnh dù RQ2 có được làm hay không.

### 7.3. Ngưỡng suy ra từ chi phí (bổ sung)

Chi phí khi chọn route (cột) trong khi route đúng là (dòng), đơn vị = một lượt duyệt. Giá trị là giả định do nhóm chốt (Q9, `decisions.md` mục 2), báo cáo GVHD:

| Đúng \ Chọn | Tự làm | Chờ duyệt | Chuyển L2 |
|---|---|---|---|
| Tự làm | 0 | 1 | 3 |
| Chờ duyệt | 10 (bỏ sót) | 1 | 3 |
| Chuyển L2 | 20 (bỏ sót nặng) | 1 + 5 (rủi ro duyệt theo phản xạ) | 3 |

Tự làm chỉ khi chi phí kỳ vọng thấp hơn một lượt duyệt: `p · c_miss < c_review ⟺ p < t_low* = c_review / c_miss` (với tỉ lệ mặc định 10:1, `t_low* = 0,1`).

*Sửa 25/09/2026: bản trước ghi `t_low* = c_miss / c_review` — lỗi gõ khi biến đổi bất đẳng thức; câu tiếp theo đã dùng đúng dạng `c_review / c_miss`.*

Ngưỡng 0.25 của tài liệu gốc tương đương ngầm coi bỏ sót chỉ đắt gấp 4 lần một lượt duyệt, mâu thuẫn với "FNR là chỉ số quan trọng nhất". Quy trình chọn:

1. Tính t_low* từ chi phí.
2. Trên tập calibration, quét lưới (t_low, t_high), chọn cặp có tổng chi phí thấp nhất.
3. Ngưỡng dưới đánh giá trên nhãn "route ≠ tự làm"; ngưỡng trên trên nhãn "route = chuyển L2" — cần nhãn 3 mức (mục 8).
4. Báo cáo khoảng cách giữa ngưỡng thực nghiệm và t_low*, kèm phân tích độ nhạy khi tỉ lệ bỏ sót/duyệt ∈ {5, 10, 20}.
5. Nếu p không tách được "chuyển L2" (AUC < 0.7), bỏ đường LLM → chuyển L2; chỉ luật deny được chuyển L2.

### 7.4. Biến thể "LLM chỉ được nâng mức" (bổ sung, đã chốt Q8)

Gốc: luật khớp → trả về ngay. Hệ quả: ngữ cảnh bất thường không có ô luật (VPN hợp lệ nhưng kết nối gần nhất từ nước ngoài) bị luật allow cho qua. Biến thể `hybrid_guarded`: luật allow vẫn gọi LLM, LLM chỉ được nâng lên chờ duyệt hoặc chuyển L2, không bao giờ hạ. Chạy như phương án so sánh thứ sáu (sau 5 phương án ở P8), không phải mặc định.

Code tham chiếu: `scaffold/backend/app/risk/policy_engine.py`, `decision_math.py`; đặc tả: `docs/02-spec/risk-engine.md`, `docs/00-context/research-design.md` §3.

---

## 8. Dữ liệu

Hệ thống cần bốn loại dữ liệu; cỡ của bộ kịch bản được suy ra từ phép đo cần làm, không chọn theo cảm tính.

| Loại | Nội dung | Hiện có | Cần đạt |
|---|---|---|---|
| Seed hệ thống giả lập | Người dùng, tài khoản, thiết bị, chứng chỉ, danh mục phần mềm, license, thư mục, quyền | Đủ (`mock_services/seed.json`) | Thêm dữ liệu cho các kịch bản đi xuống LLM |
| Knowledge Base | Tài liệu tiếng Việt 300–800 từ, số liệu khớp `kb-facts.md` | 1 tài liệu mẫu + template | 16 tài liệu (4 mỗi loại); cố ý không có tài liệu MFA cho TC16 |
| Bộ kịch bản | Câu người dùng, người gửi, giờ, lỗi giả lập, các lượt, nhãn chuẩn | 40 kịch bản gốc có nhãn | 150–180 kịch bản, ~20% ca biên |
| Bộ injection (RQ4) | Câu tấn công và câu thường tiếng Việt | 11 ví dụ từ tài liệu gốc | ≥ 150 tấn công + ≥ 300 câu thường |

### 8.1. Nhãn 3 mức

Mỗi kịch bản có hành động được gán `expected_route` ∈ {tự làm, chờ duyệt, chuyển L2}, theo câu hỏi: một L1 có kinh nghiệm có muốn xem trước khi làm không, và việc này có nên làm không? Không mở `policy.json` khi gán nhãn — nếu chép luật vào nhãn, phương án chỉ-luật sẽ đạt 100% giả tạo.

Quy trình (gốc): lượt 1 hai người ngồi chung; lượt 2 một người độc lập; Kappa < 0.6 → thống nhất lại tiêu chí; chia tập theo họ kịch bản ~65/35 trước khi chọn ngưỡng.

### 8.2. Yêu cầu cỡ mẫu (bổ sung)

| Yêu cầu | Tối thiểu | Vì sao |
|---|---|---|
| Ca đi xuống lớp LLM trong tập calibration | ≥ 50 | Ít hơn thì Platt scaling và chọn ngưỡng không có ý nghĩa thống kê |
| Ca "chuyển L2" trong tập calibration | ≥ 30 | Để chọn được ngưỡng trên |
| Ca "cần người" trong tập test | ≥ 60 | Không lỗi trên n ca → cận trên FNR ≈ 3/n; muốn khẳng định FNR < 5% cần n ≥ 60 |

Với bảng luật §6.3, 28 kịch bản gốc gần như không có ca nào chắc chắn đi xuống LLM (TC09/TC10 đi theo luật cần duyệt — Q1; TC21 là ca lỗi thực thi ở B17). Vì vậy cần TC37 và thêm các họ kịch bản thiết kế để không luật nào khớp, ví dụ: cấp quyền mới vào thư mục độ nhạy thấp/trung bình cùng phòng ban (đọc hoặc ghi); đặt lại mật khẩu cho tài khoản thường của đồng nghiệp; mở khóa tài khoản bị khóa không phải do nhập sai; cấp quyền 180 ngày. Mỗi họ 6–8 biến thể.

### 8.3. Tỉ lệ escalate

Tỉ lệ ca nhạy cảm do nhóm tự soạn, nên tỉ lệ escalate thô không phản ánh vận hành thật. Báo cáo theo từng loại yêu cầu và trên một phân bố vận hành giả định (ví dụ 70% thường ngày, 20% cần duyệt, 10% nhạy cao); ngưỡng cảnh báo 40% của gốc áp dụng trên phân bố này.

Chi tiết: `docs/03-quality/evaluation.md`, `docs/02-spec/seed-and-scenarios.md`, `kb-facts.md`.

---

## 9. Kiểm thử

Kiểm thử tách hai việc: test chứng minh hệ thống chạy đúng luồng (tất định, dùng LLM giả lập, chạy mỗi lần commit), còn chất lượng của LLM được đo riêng ở phần đánh giá.

| Tầng | Kiểm gì | LLM | Chạy khi |
|---|---|---|---|
| Unit | Hàm thuần: bảng chuyển trạng thái, policy engine, `build_action`, `build_ctx`, retry, hash, toán quyết định | Không | Mỗi commit |
| Integration | Node + dịch vụ + DB + checkpoint | ScriptedLLM (trả kết quả soạn sẵn) | Mỗi PR |
| E2E | TC01–TC28 và các kịch bản bổ sung qua API, so với bảng kết quả mong đợi | ScriptedLLM | Mỗi PR |
| Probe | Intent, injection, phân phối p với LLM thật | Thật + cache | Khi đóng cổng phase |
| Thủ công | 12 ca demo qua giao diện | Thật | Cổng Phase 7 |

19 bất biến, mỗi bất biến có test, ví dụ: M5 không nhận câu người dùng; luật khớp thì không gọi LLM; deny không bao giờ vào hàng đợi duyệt; hết hạn duyệt không bao giờ thực thi; hash lệch thì không thực thi; hoàn tác chỉ khi hành động hoàn tác được; lỗi hệ thống khác "không tồn tại"; mọi nhánh có audit điểm 8; sự kiện muộn bị bỏ qua ở cả 3 trạng thái chờ; ngưỡng chỉ được chọn trên tập calibration.

> **Bổ sung ngữ cảnh (E9):** thêm vào danh sách bất biến trên — *một exception bất kỳ ném ra từ bất kỳ node nào luôn đưa ticket về `S_ESCALATED` với `exit_code=E9`, không bao giờ làm crash worker hay để ticket kẹt lại*. Test tương ứng là TC29 (xem mục 6.4).

**Công cụ:** pytest, respx (giả lập HTTP), FakeClock (tua giờ để test hạn 30 phút/24 giờ/48 giờ trong vài giây), mock `/_admin/faults` (bơm lỗi 500, 429, timeout), ScriptedLLM.

Hiện đã có sẵn 245 test hợp đồng trong scaffold; 8 test toán quyết định định nghĩa ở `build/phase6-thiet-ke-chi-tiet.md` mục 4.6, hiện thực ở Phase 6 chặng 6A (`test_decision_math.py` dm1–dm8). Chi tiết: `docs/03-quality/testing.md`.

---

## 10. Đánh giá và thực nghiệm

Mọi thực nghiệm chạy trên tập test đã khóa, với ngưỡng chọn trước trên tập calibration; mỗi con số báo cáo kèm khoảng tin cậy và mã lần chạy.

| Lần chạy | Cấu hình | Trả lời RQ |
|---|---|---|
| Thủ công | Mọi ca qua người (tính giải tích; đo thời gian trên một mẫu) | RQ1 — mốc so sánh |
| Full-auto | Bỏ M5, agent tự làm hết | RQ1 — cận trên tự động, cận dưới an toàn |
| Chỉ-luật | Lớp 1; không khớp → chờ duyệt | RQ1 |
| Chỉ-LLM | Lớp 2 cho mọi ca | RQ1, ablation bỏ lớp luật |
| Hybrid (đề xuất) | Lớp 1 + lớp 2, ngưỡng theo chi phí | RQ1 |
| Hybrid-guarded (bổ sung) | LLM chỉ được nâng mức | RQ1, chạy sau 5 phương án chính (Q8) |
| 3 cách lấy p × trước/sau hiệu chỉnh | Tự nêu/hỏi nhiều lần/xác suất token | RQ2 — tùy chọn |
| Bỏ RAG/bỏ tool/bỏ chẩn đoán chủ động | Ablation của gốc | RQ3 và giá trị từng thành phần |
| B2 dạng tầng (mở rộng) | Regex/mô hình nhỏ/fine-tune/LLM | RQ4 |
| LLM local (mở rộng) | Lặp lại RQ2 và vai trò fast với model local | RQ5 |

**Chỉ số chính:**
- **An toàn:** FNR (quan trọng nhất), FPR, escalation accuracy — kèm cận trên Clopper–Pearson.
- **Hiệu chỉnh:** ECE, Brier, reliability diagram.
- **Chi phí:** chi phí kỳ vọng/ticket theo ma trận mục 7.3, có phân tích độ nhạy.
- **Hiệu quả:** automation rate, escalation rate (trên phân bố giả định), deflection rate, độ trễ, chi phí LLM/ticket.
- **Trải nghiệm:** lượt hỏi lại trung bình, tỉ lệ giải quyết một lượt.
- **Kỹ thuật:** intent F1, Recall@5, tỉ lệ có trích nguồn, tỉ lệ gọi tool thành công, tỉ lệ log đủ trường.
- **Duyệt cho có:** thời gian người duyệt xem mỗi ticket; dưới 5 giây là dấu hiệu bấm theo phản xạ (gốc).

**Báo cáo:** bảng so sánh các phương án, bảng ablation, biểu đồ hiệu chỉnh trước/sau, biểu đồ chi phí theo ngưỡng (đánh dấu điểm chọn và t_low*), 10 ca sai tiêu biểu kèm audit. Người chạy thực nghiệm không phải người xây M5; người thứ hai chạy lại một lần phải ra cùng số.

Chi tiết: `docs/03-quality/evaluation.md`.

---

## 11. Phần cứng và LLM local (bổ sung)

Hệ thống chạy được ở mức 0 không cần GPU; LLM local là tùy chọn bật bằng cấu hình, vì `LLMClient` gọi Ollama/vLLM qua API tương thích OpenAI giống như gọi LLM API.

| Mức | Máy | Cấu hình | Làm được |
|---|---|---|---|
| 0 (mặc định) | Không GPU | LLM qua API; embedding, rerank, mô hình phân loại injection cỡ ~86M tham số chạy CPU | RQ1–RQ4 |
| 1 | GPU khoảng 8–16 GB VRAM | Vai trò fast (intent, phân loại info/action, câu hỏi, trích slot, injection) dùng model local cỡ 7–8B lượng tử 4-bit; B14 thêm cách "xác suất token" | Thêm RQ5 phần fast |
| 2 | GPU ≥ 24 GB | Thêm model cỡ 14B trở lên để lặp lại RQ2 ở vai trò strong | RQ5 đầy đủ |

Số VRAM ở trên là mức tham khảo; đo lại khi cài đặt.

**Bước nào nên chuyển local, bước nào giữ API:**

| Bước | Đề xuất | Lý do |
|---|---|---|
| B2 tầng 2 | Mô hình phân loại nhỏ + LLM cho vùng lưng chừng | Nhanh, rẻ, có số liệu đo; model đa ngôn ngữ có sẵn chưa chắc tốt với tiếng Việt → fine-tune và đo lại |
| B3 intent | Có thể fine-tune PhoBERT/XLM-R; slot vẫn dùng LLM | Thêm một thành phần học máy có huấn luyện |
| B10 phân loại, B11 câu hỏi và trích slot | Local cỡ 7–8B | Tác vụ đơn giản, gọi nhiều lần |
| B10 viết câu trả lời có trích dẫn | Giữ API | Chất lượng tiếng Việt quan trọng |
| B14 ước lượng rủi ro | Thực nghiệm cả hai | Là câu hỏi RQ2/RQ5 |

Lợi ích cho đồ án: model local không bị nhà cung cấp đổi phiên bản giữa các lần chạy (kết quả tái lập được) và cho đọc xác suất token. Rủi ro: chất lượng tiếng Việt và độ ổn định khi trả JSON của model nhỏ phải đo, không mặc định là đủ.

Chi tiết: `docs/02-spec/llm-contracts.md`, `docs/00-context/research-design.md` §5.

---

## 12. Rủi ro và việc cần chốt

Trạng thái chốt ở `build/decisions.md` (nhóm tự quyết, báo cáo GVHD; không có vòng hỏi GVHD). Tóm tắt những gì ảnh hưởng Phase 3 trở đi:

- **Provider LLM và ngân sách (N1):** đa provider, trần tổng ≤ 1.000.000 đ; model cụ thể chọn bằng probe ở Phase 3; `spend_cap` chặn cứng (P2 mục 5).
- **Q1:** TC09/TC10 theo bảng luật (R17/R18, R13/R14 → cần duyệt); dữ liệu cho lớp LLM lấy từ TC37 và các họ kịch bản mục 8.2.
- **Q9:** 10:1 → `t_low*` = 0,1; báo cáo độ nhạy 5/10/20.
- **Phần cứng (N2):** 3 máy gaming + 1 Mac; mức 1 nếu có máy ≥ 8 GB VRAM (ghi số VRAM vào `decisions.md` mục 1.3).
- Q2, Q3, Q6, Q8, Q10–Q14: đã chốt theo nguyên tắc "xây bản đơn giản trước, tối ưu sau" — xem `decisions.md` mục 2.

| Rủi ro | Dấu hiệu sớm | Cách xử lý |
|---|---|---|
| Quá ít ca đi xuống LLM → không fit được calibrator, RQ1 thiếu số liệu | Cổng D2 thiếu ca đi xuống LLM | Soạn thêm họ kịch bản mục 8.2 trước Phase 6 |
| Không đủ ca để khẳng định FNR | Tập test < 60 ca "cần người" | Tăng ca hoặc báo cáo cận trên thay vì "FNR = 0%" |
| Luồng nội dung (KB, kịch bản) chậm hơn code | Cổng K1/D1 trễ | Dùng LLM sinh biến thể, người soát từng dòng; tối thiểu 120 kịch bản |
| Chất lượng LLM tiếng Việt thấp | Probe intent < 18/20 | Sửa prompt; đổi model ở vai trò đó |
| Phạm vi phình to | Làm thực nghiệm RQ2, RQ4, RQ5 trước khi RQ1, RQ3 có số liệu | Giữ đúng thứ tự phase; các thực nghiệm này chỉ sau Phase 10 (phần xây dựng tương ứng vẫn làm đúng phase) |

**Bắt đầu thế nào:** trong project, đọc `build/00-README.md` mục 6 (thứ tự đọc cho coding agent). Trong repo của nhóm: giao coding agent task T01 với câu "Làm T01. Đọc CLAUDE.md rồi context pack của T01 trong `docs/01-plan/backlog.md`." Song song, một người soạn 5 tài liệu KB VPN và mở rộng bộ kịch bản.

---

## 13. Triển khai (bổ sung)

Triển khai lên một máy chủ ảo chạy Docker Compose là đủ cho quy mô đồ án; pipeline triển khai được dựng từ Phase 1 để mọi phase sau đều demo được trên cùng một môi trường, không dồn việc triển khai vào cuối.

### 13.1. Ba môi trường

| Môi trường | Ở đâu | Dùng để | LLM |
|---|---|---|---|
| Dev | Máy từng người | Code, chạy test | ScriptedLLM hoặc API với cache |
| Staging/demo | 1 VM (khuyến nghị 4 vCPU, 16 GB RAM, 50 GB SSD) | Demo cho GVHD sau mỗi cổng phase, chạy thực nghiệm | API thật; local nếu VM có GPU |
| Bảo vệ | Staging đã đóng băng + bản chạy offline trên laptop | Buổi bảo vệ | API + cache; bản offline dùng cache LLM của các ca demo |

Cấu hình VM là ước lượng: tải model embedding và rerank (~3–4 GB RAM) cộng Postgres, Qdrant và 4 process Python. Đo lại ở Phase 3.

### 13.2. Kiến trúc triển khai

Trình duyệt → Reverse proxy (Caddy + HTTPS) → frontend (bản build tĩnh) và backend (2–4 worker uvicorn) → Postgres, Qdrant, mock, worker hạn chờ, LLM API hoặc Ollama/vLLM.

*Đọc sơ đồ: chỉ reverse proxy mở ra Internet (cổng 443); Postgres, Qdrant, mock và endpoint `/api/eval/*` chỉ nghe trong mạng nội bộ Docker. Frontend bản triển khai là bản build tĩnh do reverse proxy phục vụ, không chạy `npm run dev`.*

### 13.3. CI/CD

1. **Mỗi PR:** GitHub Actions chạy lint (ruff, mypy) + test unit/integration/e2e với ScriptedLLM. Đỏ thì không merge.
2. **Merge vào main:** build image `backend`, `mock`, `frontend`, gắn tag = mã commit, đẩy lên GitHub Container Registry.
3. **Triển khai staging:** job SSH vào VM → `docker compose pull` → chạy migration → `docker compose up -d` → gọi `/api/health` và một kịch bản khói (TC01 với ScriptedLLM). Khói lỗi thì tự quay về tag trước.
4. **Quay lui:** đổi biến `IMAGE_TAG` về tag cũ, chạy lại bước 3. Migration phải viết để không phá bản cũ (chỉ thêm cột/bảng trong cùng một đợt).

### 13.4. Vận hành

| Việc | Cách làm |
|---|---|
| Bí mật | Khóa LLM, JWT secret trong GitHub Secrets và file `.env` trên VM (quyền 600); không commit |
| Sao lưu | `pg_dump` mỗi đêm giữ 7 bản; snapshot Qdrant sau mỗi lần ingest; `policy.json` và KB đã nằm trong git |
| Model | Tải sẵn `bge-m3`, reranker vào volume khi build, để khởi động không phải tải lại |
| Giám sát | `/api/health` (DB, Qdrant, mock, LLM); log JSON có mã ticket; trang dashboard của Trưởng BP cho số liệu nghiệp vụ |
| Chế độ eval | `EVAL_MODE=true` chỉ bật trên bản chạy thực nghiệm, không bật trên bản demo mở ra ngoài |

### 13.5. Gắn vào các phase

| Phase | Việc triển khai |
|---|---|
| 1 | Dockerfile, Compose, CI chạy test; dựng VM staging |
| 3 | Triển khai staging tự động; demo lát cắt VPN trên staging |
| 7 | Reverse proxy + HTTPS, frontend build tĩnh, tài khoản demo cho 4 vai trò |
| 8 | Đóng băng: tag `v1.0-freeze`, sao lưu, ghi lại cấu hình máy chạy thực nghiệm |
| Trước bảo vệ | Diễn tập: khôi phục từ bản sao lưu, chạy bản offline, kịch bản demo SLA 2 phút |

---

## 14. Chịu tải (bổ sung)

Lưu lượng của một service desk cấp 1 rất nhỏ so với năng lực một VM; điểm nghẽn thật là độ trễ mỗi lượt (nhiều lời gọi LLM nối tiếp, rerank trên CPU) và giới hạn tốc độ của nhà cung cấp LLM khi chạy thực nghiệm, không phải số request mỗi giây.

### 14.1. Ước lượng lưu lượng

Giả định (cần thay bằng số của doanh nghiệp tham chiếu nếu có): công ty 1.500 nhân viên, 0,8 yêu cầu L1/người/tháng, 22 ngày làm việc, giờ cao điểm chiếm 20% lượng trong ngày, trung bình 3 lượt tương tác/ticket.

Tính: (1.500 × 0,8) / 22 ≈ 55 ticket/ngày ⇒ 55 × 0,2 ≈ 11 ticket/giờ cao điểm ⇒ ≈ 33 lượt/giờ.

Mục tiêu thiết kế lấy gấp 10 lần con số này: **110 ticket/giờ cao điểm, 50 người dùng đồng thời.**

### 14.2. Độ trễ một lượt

| Thành phần | Số lần gọi ở lượt đầu | Ước lượng |
|---|---|---|
| LLM B2, B3, B10 (phân loại) | 3 lời gọi nối tiếp | 1–3 giây mỗi lời gọi |
| LLM B10 trả lời hoặc B11 hỏi lại | 1 | 1–4 giây |
| LLM B14 (chỉ khi không luật nào khớp) | 1, hoặc 5 nếu "hỏi nhiều lần" | 1–3 giây; 5 lời gọi chạy song song |
| Embedding câu hỏi (CPU) | 1 | 0,1–0,3 giây |
| Rerank 20 đoạn (CPU) | 1 | 1–3 giây — dễ thành điểm nghẽn |
| Tool chẩn đoán gọi mock | 3 | vài chục ms |

Mục tiêu: p95 lượt đầu < 15 giây, lượt sau < 8 giây. Nếu rerank vượt 2 giây: giảm ứng viên từ 20 xuống 10, dùng reranker nhỏ hơn, hoặc chạy trên GPU.

### 14.3. Năng lực và thiết kế

Với 4 worker uvicorn và ~10 giây mỗi lượt, năng lực ≈ 4/10 = 0,4 lượt/giây ≈ 1.400 lượt/giờ — gấp hơn 40 lần mức cao điểm ước lượng.

- **Chạy graph nền:** API trả mã ticket ngay, graph chạy trong tác vụ nền, giao diện polling (đã có). Tránh request HTTP treo 10–15 giây và timeout ở reverse proxy.
- **Khóa theo ticket** (`SELECT FOR UPDATE`) để hai sự kiện cùng lúc không làm graph chạy song song trên một ticket.
- **Giới hạn đồng thời lời gọi LLM** (semaphore trong `LLMClient`) + retry 429 có backoff, để thực nghiệm chạy 180 kịch bản không bị nhà cung cấp chặn.
- **Cache LLM** khi chạy lại thực nghiệm: không gọi lại, không tốn tiền, kết quả giống hệt.

> **Bổ sung ngữ cảnh (E9):** phần "giới hạn đồng thời + retry 429 có backoff" ở trên là try/except *đã lường trước* nằm trong `LLMClient` (retry theo policy, tương tự `call_with_retry`). Nếu `LLMClient` đã hết lượt retry 429/5xx mà vẫn lỗi, hoặc trả về một exception khác (không phải 429/5xx đã lường trước — ví dụ lỗi parse response), lỗi đó thuộc phạm vi cần escalate. Node gọi `LLMClient` nên coi lỗi 429/5xx đã hết retry là một trường hợp nghiệp vụ cụ thể (ánh xạ về mã thoát phù hợp của bước đó, ví dụ E2 hoặc E5 tuỳ ngữ cảnh), còn mọi exception khác không thuộc danh sách đã lường trước sẽ tự động rơi vào lớp `with_error_boundary` và trở thành E9 — không cần node tự viết thêm try/except cho trường hợp "chưa biết trước" này.

### 14.4. Kiểm thử tải

Công cụ: Locust (Python, cùng ngôn ngữ với backend) hoặc k6.

| Kịch bản | Cách chạy | Đạt khi |
|---|---|---|
| Chi phí hệ thống thuần | 50 người dùng đồng thời, 110 ticket/giờ, LLM giả lập trả trong 1 giây | p95 phần không phải LLM < 1 giây; lỗi < 1% |
| Tải thật nhỏ | 20 người dùng đồng thời, LLM thật | p95 lượt đầu < 15 giây; không có E2 do 429 |
| Dồn hạn chờ | 200 phiếu duyệt hết hạn trong cùng một phút | Worker xử lý hết trong 1 chu kỳ quét (15 giây); không thực thi nào |
| Tranh chấp duyệt | 2 người cùng bấm đồng ý một phiếu | Đúng 1 lần thực thi; lần còn lại nhận 409 |
| Chạy dài | 1 giờ ở mức cao điểm | RAM không tăng liên tục; số kết nối DB ổn định |

Kết quả kiểm thử tải đưa vào báo cáo như chỉ số "độ trễ" của nhóm hiệu quả (gốc NC III §10.2).

---

## 15. Chi phí (bổ sung)

Chi phí LLM vận hành ước lượng dưới 0,01 USD mỗi ticket; khoản đáng kể nhất là chạy thực nghiệm lặp lại, và cache LLM đưa chi phí chạy lại về 0. Mọi đơn giá dưới đây là giả định minh họa — thay bằng bảng giá thật khi chốt provider (`build/decisions.md`, mục Phase 0).

### 15.1. Chi phí LLM mỗi ticket

Công thức: `C_ticket = Σ_bước P_gọi × (T_in · g_in + T_out · g_out)`, trong đó P là xác suất bước đó có gọi LLM, T là số token, g là đơn giá mỗi token.

| Bước | Vai trò | P gọi | Token vào | Token ra |
|---|---|---|---|---|
| B2 chặn injection | fast | 100% | 500 | 60 |
| B3 phân loại | fast | 100% | 1.200 | 200 |
| B10 info hay action | fast | 100% | 800 | 30 |
| B11 câu hỏi bổ sung | fast | ~40% | 900 | 80 |
| B10 trả lời có trích dẫn | strong | ~30% (ca chỉ cần thông tin) | 2.500 | 350 |
| B14 ước lượng rủi ro | strong | ~25% (ca không luật nào khớp) | 1.800 | 150 |

Với đơn giá minh họa — fast 0,25/1,0 USD và strong 3/15 USD mỗi 1 triệu token vào/ra:
- fast ≈ 2.860 token vào + 322 token ra ≈ 0,001 USD;
- strong ≈ 1.200 token vào + 143 token ra ≈ 0,006 USD;
- tổng ≈ 0,007 USD/ticket ≈ 8 USD/tháng cho 1.200 ticket (quy mô mục 14.1).

Nếu B14 dùng "hỏi nhiều lần" (5 lời gọi), cộng thêm khoảng 0,008 USD/ticket. Chuyển vai trò fast sang LLM local làm phần fast gần như bằng 0, đổi lại cần GPU.

### 15.2. Chi phí thực nghiệm

| Khoản | Ước lượng |
|---|---|
| Ma trận RQ1 + ablation: khoảng 10 lần chạy × 180 kịch bản | 180 × 10 × ~0,01–0,02 USD ≈ 20–40 USD |
| RQ2 (tùy chọn): 3 cách lấy p, gồm "hỏi nhiều lần" 5 lời gọi, trên calibration + test | ≈ 10–20 USD |
| Probe, sửa prompt trong lúc phát triển | ≈ 20–40 USD |
| **Tổng** | **khoảng 50–100 USD với giá minh họa** |

Giữ chi phí thấp: bật `LLM_CACHE` (chạy lại không tốn tiền, kết quả giống hệt); test luồng luôn dùng ScriptedLLM; chỉ chạy lại không cache cho một lần đo độ dao động của LLM.

### 15.3. Hạ tầng

| Khoản | Phương án | Ghi chú |
|---|---|---|
| VM staging | 4 vCPU, 16 GB RAM | Giá thay đổi theo nhà cung cấp; ưu tiên tín dụng sinh viên hoặc máy của trường/lab |
| GPU (mức 1–2, tùy chọn) | Máy sẵn có của nhóm, hoặc thuê GPU theo giờ chỉ lúc chạy RQ5 | Tắt ngay sau khi chạy xong |
| Tên miền + HTTPS | Tùy chọn; Caddy cấp chứng chỉ miễn phí | Có thể dùng IP + cổng cho demo nội bộ |

### 15.4. Lợi ích — cùng đơn vị với RQ1

So với xử lý thủ công, chi phí người mỗi ticket: `C_người = r_duyệt · t_duyệt + r_L2 · t_L2` so với `C_thủ_công = t_thủ_công`.

r là tỉ lệ ticket đi vào duyệt/chuyển L2 (đo từ thực nghiệm), t là phút người cho mỗi loại (đo trên một mẫu ở lần chạy "Thủ công"). Lợi ích ròng = (C_thủ công − C_người) × lương mỗi phút × số ticket − chi phí LLM − hạ tầng. Báo cáo con số này kèm chi phí kỳ vọng của sai lầm (mục 7.3): tự động hóa chỉ có lợi khi không đổi lấy bỏ sót.

---

## 16. Tính năng bổ trợ cho từng actor (bổ sung)

Mỗi actor có một nhóm tính năng lõi (Phải có) phục vụ luồng chính và vài tính năng bổ trợ (Nên có/Có thể) làm tăng giá trị sử dụng; mọi tính năng tuân theo ma trận quyền của gốc (NC III §2.2) và không thêm trạng thái mới vào máy trạng thái.

**Quy tắc làm:** chỉ làm "Nên có" của một phase sau khi "Phải có" của phase đó đã qua cổng. Tính năng "hủy yêu cầu đang chờ duyệt" cố ý không đưa vào, vì cần thêm một chuyển trạng thái không có trong gốc.

### 16.1. Nhân viên

| Tính năng | Phục vụ | Ưu tiên | Phase |
|---|---|---|---|
| Chat gửi yêu cầu, trạng thái dễ hiểu, đồng hồ khi đang chờ | Luồng chính | Phải có | 7 |
| Thông báo trong app khi có kết quả duyệt hoặc L2 đóng ticket | Không phải hỏi lại | Phải có | 4–7 |
| Hiện nguồn tài liệu đã trích trong câu trả lời | Minh bạch, chống bịa (gốc B9) | Phải có | 7 |
| Nút gợi ý nhanh: quên mật khẩu, lỗi VPN, cài phần mềm, xin quyền | Giảm câu mơ hồ, giảm lượt hỏi lại (RQ3) | Nên có | 7 |
| Lịch sử ticket; tạo yêu cầu mới liên kết ticket cũ đã đóng | Gốc §8.3: không mở lại ticket cũ | Nên có | 7 |
| Chấm mức hài lòng 1–5 sau khi đóng | Thêm chỉ số trải nghiệm | Có thể | 7 |

### 16.2. IT Helpdesk L1

| Tính năng | Phục vụ | Ưu tiên | Phase |
|---|---|---|---|
| Hàng đợi duyệt sắp theo hạn, đồng hồ đỏ khi còn dưới 20% thời gian | Tránh hết hạn (E6) | Phải có | 4–7 |
| Trang chi tiết duyệt: yêu cầu gốc, Action đã băm, luật khớp hoặc p, kết quả chẩn đoán | Gốc §5.2.1: người duyệt thấy đúng ActionPlan | Phải có | 4–7 |
| Ghi đè quyết định kèm lý do | Gốc §5.4, TC23 | Phải có | 4 |
| Mẫu lý do từ chối chọn nhanh + ô tự do bắt buộc | Nhanh hơn nhưng vẫn có lý do | Nên có | 7 |
| Nhắc chống duyệt theo phản xạ: xem dưới 5 giây thì hỏi xác nhận lại | Vấn đề thiết kế "duyệt cho có" (gốc §8.3) | Nên có | 7 |
| Dashboard phần của mình: số phiếu đã duyệt, thời gian phản hồi, số lần hết hạn | Quyền gốc: L1 xem phần của mình | Nên có | 7 |

### 16.3. Trưởng bộ phận IT

| Tính năng | Phục vụ | Ưu tiên | Phase |
|---|---|---|---|
| Sửa policy JSON có kiểm tra hợp lệ, lịch sử phiên bản, quay lui | Gốc: cấu hình không cần build lại | Phải có | 7 |
| Dashboard: automation, escalation (cảnh báo 40%), deflection, hết hạn duyệt, phân bố `decided_by`, top luật, số lần ghi đè | Giám sát M5 | Phải có | 7 |
| Cảnh báo an ninh: injection (E0), dò mật khẩu | Gốc §1.3 | Phải có | 2–5 |
| Mô phỏng tác động trước khi lưu policy: chạy policy mới trên N ticket gần nhất, hiện số ca đổi route | Tránh nới lỏng mù; gắn trực tiếp M5 | Nên có | 7 |
| Danh sách lỗ hổng KB (các ca E3) để giao viết tài liệu | Gốc §8.4 | Nên có | 7 |
| Xuất báo cáo CSV theo khoảng ngày | Báo cáo định kỳ | Có thể | 7 |

### 16.4. Kỹ thuật viên L2

| Tính năng | Phục vụ | Ưu tiên | Phase |
|---|---|---|---|
| Hàng đợi escalate theo mức ưu tiên (Rất cao → an ninh → có SLA → hạ tầng → cao → thường) | Gốc §7 | Phải có | 7 |
| Ghi chú bàn giao 4 phần + hội thoại của ticket | Gốc §5.3: biết đã làm tới đâu | Phải có | 7 |
| Đóng với 3 kết quả; chặn "hoàn tất" cho ca bị deny | Gốc §1.2 | Phải có | 7 |
| Soạn tài liệu KB từ ca E3 vừa xử lý | Quyền gốc: L2 cập nhật KB | Nên có | 7 |

> **Bổ sung ngữ cảnh (E9):** hàng đợi escalate ưu tiên ở trên (Rất cao → an ninh → có SLA → hạ tầng → cao → thường) cần thêm E9 vào nhóm mức ưu tiên "Cao" — ngang với nhóm hạ tầng (E2), vì một lỗi chưa lường trước có thể là bug thật sự cần kỹ thuật viên/dev xem trực tiếp, không chỉ là một ca nghiệp vụ thông thường (xem `NGU-CANH-DAY-DU.md` Phần IV mục 7, dòng E9).

### 16.5. Hệ thống và vận hành

| Tính năng | Phục vụ | Ưu tiên | Phase |
|---|---|---|---|
| Trang health + log JSON có mã ticket | Vận hành, gỡ lỗi | Phải có | 1 |
| Chế độ demo: SLA 2 phút, dữ liệu mẫu, đặt lại mock bằng một nút | Buổi bảo vệ | Nên có | 7 |
| Xuất audit của một ticket ra JSON | Kiểm toán | Có thể | 8 |

---

## 17. Kỹ thuật agent — lớp quản trị quanh agent (Objective 1, bổ sung)

Một agent chạy được chưa phải một hệ thống agent vận hành được. Mục này thêm sáu lớp quanh agent: **session và trace, bộ nhớ và ngữ cảnh, harness và tool, dữ liệu RAG, chi phí và LLMOps, riêng tư.** Mỗi thiết kế ghi mức (Phải có/Nên có/Hướng phát triển) và phase làm.

**Sơ đồ:** Yêu cầu người dùng → Privacy guard (chặn bí mật, che dữ liệu cá nhân) → Context builder (bộ nhớ + ngân sách token) → LLM gateway (router, cache, timeout, fallback) và Tool registry (đọc/ghi, circuit breaker) và RAG (index có version) → Trace (turn, span, `llm_calls`, version) → Dashboard LLMOps (chi phí, độ trễ, drift).

*Đọc sơ đồ: mọi lời gọi LLM, tool và RAG đều đi qua một lớp quản lý chung và để lại dấu vết. Không thành phần nào gọi thẳng ra ngoài.*

### 17.1. Session, trace và lineage — Phải có, Phase 2 và 4

Vì sao: audit trả lời "ai quyết định gì, khi nào"; trace trả lời "hệ thống đã chạy qua những gì, tốn bao nhiêu, bằng phiên bản nào". Thiếu trace thì không giải thích được một quyết định AUTO sai và không đo được chi phí thật.

**Cấp định danh:** `user_id → session_id (phiên đăng nhập) → ticket_id (= thread_id; con: ticket_id-n) → turn_id (mỗi lần graph chạy vì một sự kiện) → trace_id → span (node/LLM/tool/RAG)`

| Bảng | Mỗi dòng | Trường chính |
|---|---|---|
| `turns` | một lượt xử lý | `turn_id`, `ticket_id`, `session_id`, loại sự kiện, bắt đầu, kết thúc |
| `spans` | một bước chạy | `span_id`, `trace_id`, `turn_id`, loại (node/llm/tool/rag), tên, thời lượng, trạng thái, thuộc tính |
| `llm_calls` | một lời gọi LLM | `span_id`, provider, model + phiên bản, prompt + phiên bản, token vào/ra, chi phí, cache hit, JSON hợp lệ, lỗi |

> **Bổ sung ngữ cảnh (E9):** khi `with_error_boundary` (mục 6.4) bắt một exception chưa lường trước, dòng `spans` tương ứng nên ghi `trạng thái = "error"` và `thuộc tính` chứa `unhandled_exception` + traceback rút gọn — để dashboard LLMOps (17.5) và dashboard Trưởng bộ phận IT (16.3) đều nhìn thấy được số ca E9 như một chỉ số riêng, tách khỏi số ca E2 (lỗi hạ tầng đã biết).

**Lineage:** mỗi quyết định M5 (điểm log 4) và mỗi câu trả lời B10 ghi đủ phiên bản policy, prompt, model, KB (`kb_version`), calibrator và mã commit — để một lỗi hôm nay tái hiện được đúng cấu hình đã chạy.

Đặt tên span theo quy ước OpenTelemetry để sau này xuất sang công cụ như Langfuse hay Jaeger; trong đồ án lưu thẳng vào Postgres cho đơn giản.

### 17.2. Bộ nhớ và ngữ cảnh — Phải có (bộ nhớ trong ticket, context builder), Nên có (bộ nhớ phiên), Phase 3

Checkpoint của LangGraph cho biết graph đang ở đâu; bộ nhớ cho biết agent đã biết gì. Thiết kế ba lớp:

| Lớp | Nội dung | Phạm vi | Mức |
|---|---|---|---|
| Working memory | Slot đã có, kết quả chẩn đoán, câu đã hỏi, slot còn thiếu, tool đã chạy (có hạn 5 phút) — lấy từ `TicketState` | Một ticket | Phải có |
| Tóm tắt hội thoại có cấu trúc | Khi hội thoại vượt 4 tin gần nhất, tin cũ được gom thành dữ kiện có cấu trúc (không phải đoạn văn tự do) | Một ticket | Phải có |
| Bộ nhớ phiên | Các ticket đang mở và ticket vừa đóng trong 24 giờ của cùng người dùng — để báo "bạn đang có một yêu cầu VPN chờ duyệt" thay vì tạo trùng | Một người dùng | Nên có — cần GVHD đồng ý vì gốc ghi "không nhớ ticket cũ"; M5 không bao giờ đọc lớp này |

**Context builder:** mỗi prompt có danh sách trường được phép đọc và trần token (vai trò fast ≤ 2.000, strong ≤ 6.000). Thứ tự ghép: nhiệm vụ → dữ kiện có cấu trúc → bằng chứng (top-k, bỏ đoạn trùng, cắt theo điểm) → tối đa 4 tin nhắn gần nhất. Vượt trần → cắt bằng chứng điểm thấp trước. Số token thực tế ghi vào `llm_calls` để kiểm chứng.

Thời gian lưu: hội thoại và checkpoint giữ 90 ngày (cấu hình được), sau đó xóa văn bản gốc; audit giữ lại nhưng đã che dữ liệu cá nhân.

### 17.3. Agent harness và quản trị tool — Phải có, Phase 1–3

Vì sao: hiện cache, retry, kiểm schema, log nằm rải rác. Gom vào hai cổng duy nhất — một cho LLM, một cho tool — để mọi chính sách (thời gian chờ, ngân sách, dự phòng, trace) áp dụng thống nhất và test được một chỗ.

**LLM gateway (mở rộng `LLMClient`):**

| Chức năng | Thiết kế |
|---|---|
| Prompt registry | Mỗi prompt là file có `id`, `version` và mã băm nội dung; lời gọi ghi `prompt_id@version` |
| Router | Chọn model theo vai trò (fast/strong) và độ nhạy dữ liệu (17.6) |
| Kiểm tra đầu ra | Structured output theo schema; sai → thử lại 1 lần; vẫn sai → lỗi rõ ràng (E2 ở bước đó) |
| Thời gian chờ và ngân sách | Timeout theo vai trò; trần token (17.2); giới hạn số lời gọi đồng thời |
| Retry và dự phòng | Retry 429/5xx có backoff; chuỗi dự phòng tùy chọn: model chính → provider thứ hai hoặc model local |
| Cache | Theo chính sách 17.5 |
| Trace | Mọi lời gọi sinh một span và một dòng `llm_calls` |

> **Bổ sung ngữ cảnh (E9):** dòng "Kiểm tra đầu ra" ở trên dùng lại E2 cho lỗi structured-output-invalid sau khi đã thử lại. Đây là một lỗi *đã lường trước theo loại* (schema sai) dù không phải tool/RAG timeout — nên việc gán E2 hay một mã riêng là quyết định thiết kế nằm ngoài phạm vi bổ sung E9 lần này (E9 chỉ dành cho lỗi *chưa* biết trước loại). Điểm cần nhất quán: nếu nhóm giữ nguyên E2 cho trường hợp này, thì Ma trận xử lý ngoại lệ ở `NGU-CANH-DAY-DU.md` Phần IV mục 7 nên nói rõ E2 gồm cả "tool/RAG hết retry" *và* "LLM gateway trả lỗi structured-output sau khi thử lại" — tránh định nghĩa hẹp "chỉ tool hoặc RAG" như hiện tại gây hiểu lầm. Nếu chưa muốn mở rộng định nghĩa E2, nhóm có thể nêu câu hỏi này với GVHD cùng đợt với Q2/Q3/Q8/Q9 ở mục 12.

**Tool registry** — mỗi tool khai báo một lần, runtime kiểm tra theo khai báo:

| Thuộc tính | Ví dụ | Kiểm tra lúc chạy |
|---|---|---|
| Loại | đọc (`check_vpn_cert_expiry`)/ghi (`reset_password`) | Tool ghi gọi ngoài B17 → lỗi ngay |
| Hệ thống đích | AD, VPN, phần mềm, file | Circuit breaker theo hệ thống |
| Schema vào/ra | Pydantic | Sai schema → lỗi hợp đồng, không retry |
| Timeout, số lần retry | đọc: 5 giây, 2 lần; ghi: 5 giây, 0 lần | Áp trong `call_with_retry` |
| Có hoàn tác không, tool hoàn tác | `reset_password → lock_account` (một phần) | Dùng cho `TransactionLog` |
| Bước được phép gọi | B6, B11 (đọc); B17 (ghi) | Kiểm theo node đang chạy |

Circuit breaker theo hệ thống ngoài: 5 lỗi liên tiếp trong 60 giây → ngắt 30 giây, mọi lời gọi tới hệ thống đó trả lỗi ngay (không tốn thời gian retry) → ticket đi E2 nhanh; hết 30 giây cho thử một lời gọi.

Adapter: mỗi hệ thống ngoài có một interface (`IdentityProvider`, `VpnGateway`, `SoftwareCatalog`, `FileServer`) và một bản mock. Thay mock bằng hệ thống thật chỉ cần viết adapter mới và đổi cấu hình — đây là cách trả lời câu hỏi "có dùng được với hệ thống thật không".

### 17.4. Kỹ thuật dữ liệu RAG — Phải có (vòng đời, groundedness offline), Nên có (benchmark chunking, kiểm chứng online), Phase 3, 5, 8

**Vòng đời tài liệu:** Kiểm front matter → Làm sạch → Chia đoạn theo heading → Gắn metadata → Embed + BM25 → Index mới `kb_version` → Đổi alias sang index mới → Xóa index cũ.

Metadata mỗi đoạn: `doc_id`, phiên bản, loại yêu cầu, loại tài liệu, người phụ trách, ngày cập nhật, mức nhạy, trạng thái bật/tắt.

`kb_version`: mã băm của mọi cặp (`doc_id`, phiên bản). Mỗi lần ingest tạo index mới rồi đổi alias một lần, để không có lúc tìm kiếm trên index dở dang. Tài liệu bị tắt bị loại khỏi index mới.

**Benchmark chunking (Nên có):** so 3 cỡ đoạn (300/450/600 từ) trên bộ câu kiểm tra truy hồi bằng Recall@5, MRR, nDCG@5; chọn cấu hình tốt nhất.

**Groundedness:** tách câu trả lời thành từng ý, kiểm từng ý có được đoạn trích dẫn hỗ trợ không (LLM chấm, người soát 30 mẫu để đo độ tin cậy của LLM chấm). Báo cáo tỉ lệ ý được hỗ trợ và citation precision. Bản offline là bắt buộc; kiểm chứng online trước khi gửi câu trả lời là Nên có (tăng độ trễ và chi phí).

**Phân quyền tài liệu:** KB hiện là hướng dẫn nội bộ dùng chung. Metadata mức nhạy cho phép lọc theo vai trò khi có tài liệu nhạy cảm.

### 17.5. Tối ưu chi phí và LLMOps — Phải có (telemetry, dashboard, chính sách cache), Nên có (benchmark định tuyến, drift, vòng phản hồi), Phase 3 và 8

Dashboard AI (đọc từ `turns`, `spans`, `llm_calls`): token/ticket, chi phí/ngày, độ trễ p95 theo từng bước, tỉ lệ cache hit, tỉ lệ JSON lỗi, tỉ lệ dùng dự phòng, **số ticket E2 do LLM lỗi**. Tách khỏi dashboard nghiệp vụ của Trưởng BP.

> **Bổ sung ngữ cảnh (E9):** thêm vào danh sách chỉ số trên **số ticket E9** (lỗi chưa lường trước, mục 6.4) như một chỉ số riêng — một dashboard chỉ đếm E2 sẽ bỏ sót đúng loại lỗi mà E9 tồn tại để bắt (bug, exception lạ). Số E9 tăng đột biến là tín hiệu sớm cho dev, khác hẳn ý nghĩa vận hành của số E2 tăng (thường là hạ tầng/nhà cung cấp LLM có vấn đề).

**Benchmark định tuyến model (gộp RQ5):**

| Cấu hình | Đo |
|---|---|
| strong ở mọi bước | Mốc chất lượng cao nhất, chi phí cao nhất |
| fast + strong theo vai trò (mặc định) | Chi phí/ticket, độ trễ, F1 intent, groundedness |
| Local cho fast + API cho strong | Như trên + tỉ lệ JSON hợp lệ (cần GPU) |

**Chính sách cache:**

| Quy tắc | Lý do |
|---|---|
| Khóa cache = provider + model + phiên bản + prompt + phiên bản prompt + nội dung đã ghép + schema + temperature + `kb_version` | Không dùng lại kết quả của cấu hình khác |
| Chỉ khớp chính xác; hết hạn sau 24 giờ khi vận hành, không hết hạn khi chạy thực nghiệm | Vận hành cần dữ liệu mới; thực nghiệm cần tái lập |
| Không cache B2 và B14 khi vận hành | Quyết định an ninh và rủi ro phải phản ánh trạng thái hiện tại |
| Cache ngữ nghĩa chỉ cho câu trả lời thông tin ở B10, độ giống ≥ 0,95, khóa chứa `kb_version` (Có thể) | Câu gần giống nhưng dữ kiện khác thì quyết định hành động khác — không bao giờ dùng cache ngữ nghĩa cho hành động |

**Theo dõi drift (Nên có):** mỗi tuần so phân bố intent, độ tin cậy trung bình, điểm truy hồi cao nhất, tỉ lệ E3, tỉ lệ escalate, tỉ lệ ghi đè với tuần mốc (chỉ số PSI); lệch quá ngưỡng → cảnh báo trên dashboard. Trong đồ án chỉ chứng minh được cơ chế trên dữ liệu mô phỏng — đo drift thật cần lưu lượng thật (ghi rõ ở giới hạn).

**Vòng phản hồi (Nên có):** ca bị ghi đè, ca E3, ca E8 và ghi chú của L2 → hàng đợi "ca xấu" → người xem xét → thêm vào bộ kịch bản hoặc KB → chạy lại đánh giá → phát hành phiên bản mới của prompt/policy/calibrator/KB. Trong đồ án làm đến bước xuất hàng đợi và cập nhật dữ liệu; tự động huấn luyện lại là hướng phát triển.

### 17.6. Riêng tư và chống lộ dữ liệu — Phải có, Phase 5

Vì sao: người dùng có thể gõ mật khẩu, số điện thoại, hoặc dán thông tin cấu hình vào chat, và câu đó được gửi lên LLM cloud.

**Sơ đồ:** Câu người dùng → Phát hiện bí mật (mật khẩu, token, khóa) → có → Che hoặc chặn + cảnh báo người dùng; không → Che dữ liệu cá nhân không cần cho slot → Phân loại độ nhạy → LLM theo tuyến → Kiểm đầu ra (không lộ bí mật, prompt hệ thống).

- **Phát hiện bí mật** trước mọi lời gọi LLM: mẫu "mật khẩu là…", chuỗi giống token/khóa. Có bí mật → thay bằng nhãn che, báo người dùng không gửi mật khẩu qua chat. Văn bản gốc không lưu.
- **Che dữ liệu cá nhân** không cần cho slot (số điện thoại, email cá nhân, số giấy tờ). Giữ nguyên định danh cần cho xử lý (tên đăng nhập, mã thiết bị, đường dẫn thư mục). Bảng ánh xạ nhãn che ↔ giá trị thật chỉ nằm ở server.
- **Phân loại độ nhạy và định tuyến:** công khai/nội bộ/nhạy cảm. Nhạy cảm → model local nếu có; nếu không có thì chỉ gửi phần đã che, tối thiểu trường cần thiết. Đây là lý do thứ hai (ngoài chi phí) để có model local.
- **Kiểm đầu ra:** câu trả lời không chứa bí mật, dữ liệu của người khác, hay đoạn prompt hệ thống.
- **Bộ test lộ dữ liệu:** cài chuỗi "canary" vào KB và prompt hệ thống, chạy bộ câu tấn công đòi lộ dữ liệu; chỉ số tỉ lệ lộ phải bằng 0.

### 17.7. Hướng phát triển — ghi vào báo cáo, không xây

| Nội dung | Vì sao chưa làm |
|---|---|
| Tích hợp AD/VPN/file server thật | Ngoài phạm vi gốc; đã có adapter để thay (17.3) |
| Dự phòng nhiều provider ở quy mô vận hành | Cần hạ tầng và lưu lượng thật; đồ án có chuỗi dự phòng mức đơn giản |
| Tự động huấn luyện lại/hiệu chỉnh lại từ phản hồi vận hành | Cần dữ liệu vận hành thật; đồ án làm đến bước hàng đợi ca xấu |
| Bộ nhớ dài hạn giữa các ticket | Gốc ghi rõ ngoài phạm vi; đồ án chỉ có bộ nhớ phiên đọc-chỉ (17.2) |
| Đo drift trên dữ liệu thật | Cần thời gian vận hành |

### 17.8. Gắn vào kế hoạch

| Phần | Phase | Mức |
|---|---|---|
| Tool registry, adapter, circuit breaker | 1 | Phải có |
| Session, turn, trace, `llm_calls` | 2 | Phải có |
| **Lớp bắt lỗi tổng quát `with_error_boundary` / E9 (bổ sung)** | **2** | **Phải có** |
| LLM gateway, context builder, working memory | 3 | Phải có |
| Vòng đời RAG, `kb_version`, lineage đủ phiên bản | 3–5 | Phải có |
| Privacy guard, bộ test lộ dữ liệu | 5 | Phải có |
| Dashboard AI, chính sách cache | 7–8 | Phải có |
| Groundedness offline | 8 | Phải có |
| Bộ nhớ phiên, benchmark chunking, benchmark định tuyến, drift, vòng phản hồi | 7–11 | Nên có |
| **Khung bảng `turns`/`spans`/`llm_calls`/`escalations` rỗng + `/api/health` (nền của tầng Monitor, M9 — bổ sung)** | **1–2** | **Phải có** |
| **Hợp nhất M9 (dashboard + alert): việc riêng đã Phải có ở 17.1/17.5/16.3/16.5, chỉ còn việc gọi chung tên "tầng Monitor" và nối luật cảnh báo (mục 17.9 — bổ sung)** | **7–8** | **Phải có** |

### 17.9. Tầng Monitor — hợp nhất giám sát thành một tầng kiến trúc chính thức (bổ sung)

> **Bổ sung ngữ cảnh (Tầng Monitor, M9):** mục này gọi tên và vẽ ranh giới cho một tầng đã tồn tại rải rác trong tài liệu (M7, 17.1, 17.5, 16.3, 16.5), không phải xây thêm một hệ thống mới. Việc "thiết kế" ở đây là: (1) đặt cho nó một vị trí rõ ràng trong sơ đồ kiến trúc mục 3, (2) viết tường minh ranh giới nó **không được** làm, và (3) gộp các luật cảnh báo đang nằm tản mát (ngưỡng 40% ở mục 8.3 gốc, cảnh báo an ninh mục 1.3 gốc, drift ở 17.5...) thành một bảng duy nhất để không sót luật nào khi code.

**Vì sao cần chính thức hoá:** khi trình bày kiến trúc trước hội đồng, việc M7/17.1/17.5/16.3/16.5 nằm rải rác ở 5 mục khác nhau khiến câu hỏi "hệ thống có tầng giám sát không" khó trả lời gọn — mỗi lần phải liệt kê lại 5 chỗ. Gộp lại một tầng, có sơ đồ và ranh giới riêng, trả lời được câu hỏi đó bằng một câu.

#### 17.9.1. Ranh giới bắt buộc: chỉ đọc, không quyết định

Đây là ràng buộc quan trọng nhất, nối tiếp đúng tinh thần "an toàn ưu tiên tự động hoá" đã có ở tài liệu gốc (`NGU-CANH-DAY-DU.md` Phần III mục 1.3) và ràng buộc `raw_request`/`intended_action` tách bạch (`NGU-CANH-DAY-DU.md` Phần IV mục 3.1). Tầng Monitor:

- **Không bao giờ gọi `goto()`, không sửa `TicketState`, không gọi API ghi.** Nó chỉ đọc các bảng do ba tầng nghiệp vụ ghi ra (`audit_logs`, `escalations`, `turns`, `spans`, `llm_calls`) — một chiều, không có đường ghi ngược.
- **Cảnh báo chỉ tạo thông báo cho người**, không tự động hành động. Ví dụ: escalation rate vượt 40% → hiện cảnh báo đỏ trên dashboard Trưởng bộ phận IT, **không** tự động đổi `THRESHOLD_LOW`/`THRESHOLD_HIGH` trong `policy.json`. Đổi ngưỡng vẫn phải qua đúng quy trình "mô phỏng tác động trước khi lưu" (mục 16.3).
- **Không phải một nguồn dữ liệu cho M5.** Vòng phản hồi ở mục 17.5 (hàng đợi "ca xấu" → cập nhật KB/prompt/policy) đi qua một người xem xét trước khi trở thành thay đổi thật — tầng Monitor không tự động fine-tune hay tự sửa calibrator.

Ba điều "không" này là điều cần kiểm tra kỹ nhất khi code: một dashboard đọc-ghi lẫn lộn, hoặc một cron job tự động siết policy khi thấy escalation cao, sẽ phá vỡ tính minh bạch/giải thích được mà toàn bộ M5-M6-M7 được thiết kế để bảo đảm.

#### 17.9.2. Sơ đồ 4 tầng

**Sơ đồ khối (thay cho sơ đồ 3 tầng ở mục 3):** Giao diện React (4 vai trò, gồm dashboard Trưởng BP + dashboard AI) → Backend FastAPI, gồm ba tầng nghiệp vụ cũ (Agent M1–M4 / Kiểm soát M5–M7 / B17 điểm ghi duy nhất) **cộng một tầng thứ tư đứng song song**: **Tầng Monitor (M9)**, đọc từ `audit_logs`, `escalations`, `turns`, `spans`, `llm_calls` → hiển thị qua Dashboard AI (17.5), Dashboard nghiệp vụ (16.3), `/api/health` (16.5), và phát cảnh báo (bảng 17.9.3) → Mock AD/VPN/phần mềm/file (chỉ ba tầng nghiệp vụ gọi tới, Monitor không bao giờ gọi). Postgres lưu chung ticket, audit, checkpoint, `turns`/`spans`/`llm_calls`/`escalations`.

*Đọc sơ đồ: mũi tên vào tầng Monitor chỉ đi một chiều (đọc); không có mũi tên nào từ Monitor quay lại Agent, Kiểm soát hay B17.*

#### 17.9.3. Thành phần và bảng luật cảnh báo

| Thành phần | Nguồn dữ liệu | Người xem | Đã thiết kế ở |
|---|---|---|---|
| Health & liveness | `/api/health` (DB, Qdrant, mock, LLM) | Vận hành/dev | Mục 13.4, 16.5 |
| Session/trace/lineage | Bảng `turns`, `spans`, `llm_calls` | Dev (debug), Monitor tier | Mục 17.1 |
| Dashboard AI/LLMOps | `turns`/`spans`/`llm_calls` | Dev/LLMOps | Mục 17.5 |
| Dashboard nghiệp vụ | `audit_logs`, `escalations`, `decided_by` | Trưởng bộ phận IT | Mục 16.3 |
| Hàng đợi escalate ưu tiên | `escalations` (E0–E9) | Kỹ thuật viên L2 | Mục 16.4 |
| Theo dõi drift | Phân bố intent/điểm truy hồi/tỉ lệ E3 theo tuần | Trưởng bộ phận IT | Mục 17.5 |
| Vòng phản hồi "ca xấu" | Ca ghi đè, E3, E8 | Người xem xét (thủ công) | Mục 17.5 |

**Bảng luật cảnh báo (gộp lại từ các mục đã thiết kế rải rác, không đổi ngưỡng gốc):**

| Cảnh báo | Ngưỡng | Nguồn ngưỡng | Hành động khi vượt |
|---|---|---|---|
| Escalation rate cao | > 40% trên phân bố vận hành giả định | Mục 8.3 (`NGU-CANH-DAY-DU.md` gốc) | Hiện cảnh báo đỏ trên dashboard Trưởng BP — không tự đổi ngưỡng |
| An ninh — injection | Mỗi lần `exit_code=E0` | Mục 1.3 gốc | Ghi log cảnh báo, báo Trưởng bộ phận IT ngay |
| An ninh — dò mật khẩu | `auth_failure_streak` ≥ `MAX_AUTH_FAILURES` (mặc định 5/10 phút) | Mục 6, `NGU-CANH-DAY-DU.md` Phần IV | Ghi log cảnh báo, báo Trưởng bộ phận IT ngay |
| Bug/lỗi chưa lường trước | Số ticket `exit_code=E9` tăng đột biến so với đường nền | Mục 17.5 (bổ sung E9) | Báo dev — khác ý nghĩa với cảnh báo hạ tầng (E2) |
| Hạ tầng ngoài yếu | Circuit breaker mở (5 lỗi liên tiếp/60 giây) | Mục 17.3 | Báo vận hành/dev; ticket liên quan tự đi E2, Monitor chỉ hiển thị tần suất |
| Dồn hạn chờ duyệt | `S_PENDING_APPROVAL` timeout (`exit_code=E6`) tăng bất thường trong một khung giờ | Mục 6, 8.2 (gốc) | Báo Trưởng bộ phận IT — có thể thiếu người duyệt trực |
| Duyệt theo phản xạ | Thời gian xem trang duyệt < 5 giây, lặp lại | Mục 8.3 gốc ("duyệt cho có") | Hỏi xác nhận lại ngay trên giao diện (mục 16.2), đồng thời đưa vào chỉ số cho Trưởng BP |
| Drift dữ liệu/mô hình | Chỉ số PSI vượt ngưỡng khi so tuần hiện tại với tuần mốc | Mục 17.5 | Cảnh báo trên dashboard — quyết định có cập nhật KB/prompt/policy vẫn do người |

Mọi hàng trong bảng trên đều dừng ở "hiện cảnh báo/báo người" — không có hàng nào tự động thay đổi hành vi hệ thống, đúng ranh giới ở mục 17.9.1.

#### 17.9.4. Cập nhật bảng Module (mục 3)

Thêm một dòng vào bảng Module ở mục 3:

| Module | Tên | Tầng | Bước workflow |
|---|---|---|---|
| M9 (bổ sung) | Monitor — trace, dashboard, cảnh báo, drift | Monitor | Ngoài luồng B1–B20, đọc sau khi B20/escalate ghi xong |

M9 đứng cạnh M8 (Khung đánh giá) ở cột "ngoài luồng", nhưng khác nhau về bản chất: **M8 chạy offline, theo lô, phục vụ thực nghiệm RQ trên tập dữ liệu đã khoá (mục 10)**; **M9 chạy live, liên tục, phục vụ vận hành production** — hai module không dùng chung code hay chung chu kỳ chạy, dù có thể đọc chung một số bảng nguồn (ví dụ cả hai đều có thể đọc `audit_logs`).

---

## 18. Bộ tài liệu xây dựng chi tiết `build/` (bổ sung)

Mục 6 mô tả mỗi nhánh bằng một dòng bảng; bộ `build/` mở rộng mỗi nhánh thành một tài liệu riêng đủ để giao cho coding agent: sơ đồ cấu tạo, công nghệ, hợp đồng dữ liệu, mã giả, lý do thiết kế, cấu hình, bảng DB, trace, ca lỗi, kiểm thử và tiêu chí đạt. Mục lục và thứ tự đọc: `build/00-README.md`.

- Kiến trúc code: `build/01-kien-truc-project.md` (modular monolith, cây thư mục, quy tắc import).
- Tầng: `build/02-cac-tang-he-thong.md` (mở rộng sơ đồ 4 tầng của mục 3 và 17.9).
- Nền tảng: `build/nen-tang/P1–P7`.
- Nhánh: `build/nhanh/B01–B20`.

Các quyết định mới trong bộ này (D-01…D-33) đang ở trạng thái **chờ xác nhận**; danh sách và mức ảnh hưởng ở `claude/bo-sung-bo-tai-lieu-build.md` Phần B. Mục này không thay đổi thiết kế nào của các mục 1–17.

### 18.1. Các quyết định bổ sung trong bộ `build/`

Bộ `build/` bổ sung các quyết định D-01…D-33 (danh sách, trạng thái và các quyết định Q1–Q14 ở `build/decisions.md`).

**Tài liệu `docs/…` được nhắc ở các mục trên nằm trong repo của nhóm, không có trong project.** Bản tương đương trong project:

| Nhắc ở trên | Đọc trong project |
|---|---|
| `docs/00-context/research-design.md` | Mục 2 (RQ) của tài liệu này; `build/nen-tang/P8-danh-gia-M8.md` mục 1.1 |
| `docs/02-spec/architecture.md`, `state-machine.md` | `build/01-kien-truc-project.md`, `build/02-cac-tang-he-thong.md`, `NGU-CANH-DAY-DU.md` Phần IV mục 1–2, P1 |
| `docs/01-plan/decisions.md` | `build/decisions.md` |
| `docs/01-plan/plan.md`, `backlog.md` | Mục 5.1 của tài liệu này; `build/00-README.md` mục 6 |
| `docs/02-spec/workflow-steps.md` | `build/nhanh/B01…B20` |
| `docs/02-spec/risk-engine.md` | `build/nhanh/B12-B14-danh-gia-rui-ro.md` |
| `docs/02-spec/llm-contracts.md` | `build/nen-tang/P2-llm-gateway.md` |
| `docs/02-spec/seed-and-scenarios.md` | `build/nen-tang/P5-tool-registry-mock.md`, P8 mục 4 |
| `docs/03-quality/evaluation.md` | `build/nen-tang/P8-danh-gia-M8.md` |
| `docs/03-quality/testing.md` | Mục 9 của tài liệu này + mục "Kiểm thử" của từng file `build/` |
| `kb-facts.md`, `SPLIT.md`, `PROGRESS.md` | Sản phẩm tạo trong repo khi làm (Phase 0, 3, 9) — chưa tồn tại là đúng | Những quyết định làm đổi chi tiết của các mục 1–17:

- **Runtime (mục 6, 14.3):** side effect idempotent (D-18), khóa ticket cấp session (D-19), bảng chuyển trạng thái tường minh (D-29).
- **RAG (mục 6 B8–B10, 17.4):** chunk theo token bge-m3 (D-21), bộ câu không có đáp án để chọn ngưỡng E3 (D-22), truy hồi lại không lọc intent (D-23), ghép đoạn liền kề cho B10 (D-24), ablation RAG (D-25).
- **Yêu cầu nhiều ý (mục 6 B5, B19):** cha đối soát con từ DB (D-17), cha không mã thoát và chỉ số tính trên ticket lá (D-30), một tin trả lời mỗi lượt người dùng (D-31).
- **Model phân loại do nhóm huấn luyện (mục 4, 11; B2, B3):** B3 chạy model intent đa nhãn trước, LLM cho vùng lưng chừng và tách span (D-32); backbone mDeBERTa-v3-base cho cả model intent và model injection (D-33). Quy trình huấn luyện: `build/nen-tang/P11-huan-luyen-model.md`.
- **Khác:** B17 kiểm cả người gửi và người hưởng lợi (D-15), ticket L2 mở lại chạy từ B1 (D-26), tách `intent_low_confidence` (D-27).

Các mục 1–17 chưa đổi theo; patch chờ chốt ở `claude/bo-sung-bo-tai-lieu-build.md`.
