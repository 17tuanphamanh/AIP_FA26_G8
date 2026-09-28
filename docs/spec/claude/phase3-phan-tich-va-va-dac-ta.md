# Phase 3 — Phân tích lỗ hổng đặc tả và kế hoạch vá

*Lập 27/09/2026, đầu Phase 3, trước khi giao agent lập plan. Nguồn đã đối chiếu: `huong-dan-xay-dung-he-thong-2.md` §5.1, `build/decisions.md` (§1.1, §4, §4.1), `01-kien-truc-project.md`, P2, P3, P4, P5, P7, B02, B03-B05, B06-B07, B08-B09, B10, B11, B12-B14, B17-B18, B19.*

*Nhãn: **[Chốt]** = spec đã chốt · **[Suy luận]** = rút ra từ spec, chưa kiểm trên code · **[Đề xuất]** = quyết định mới, cần Tuấn Anh duyệt. Mức: **Chặn** = không vá thì agent sẽ code sai hoặc tự bịa · **Nên** = vá để plan gọn, ít vòng sửa.*

> **Cập nhật 27/09/2026:** các quyết định ở đây đã được hiện thực hóa và chi tiết hóa trong `build/phase3-thiet-ke-chi-tiet.md` (8 chặng 3a–3h, thay cho cách chia 3a–3e ở mục 1.2 dưới đây; 3-Q12, 3-Q13 đã được chỉnh). Khi hai file khác nhau, file thiết kế thắng. File này giữ làm hồ sơ phân tích.

---

## 0. Tóm tắt

1. **Phase 3 là lát cắt VPN B1 → B20**, không chỉ RAG. Cổng 3 phần code cần 11 node thật + 3 nền tảng (P2, P3, P4). Chưa có tài liệu nào chia Phase 3 thành chặng → mục 1 chia sẵn.
2. **Mức chi tiết không đều.** Các node B3, B6, B10, B11, B12, B17, B19 và P2 đã có mã giả và test. P3, P4 và phần privacy guard của B2 mới ở mức "làm gì, vì sao" (mục 2).
3. **Tìm được 35 lỗ hổng** (mục 3). Nghiêm trọng nhất là **4 lỗ hổng an ninh/FN** chứ không phải chỗ thiếu chữ:
   - Slot do LLM trích từ câu người dùng có thể thành "dữ kiện" cho luật M5.
   - Luật R20 tự gia hạn VPN mà không kiểm máy có phải của người gửi.
   - Tin trả lời của người dùng không qua sàng lọc injection.
   - `kb_version` chỉ băm phiên bản, nên sửa nội dung tài liệu mà quên tăng version thì hệ thống âm thầm dùng bản cũ.
4. Mục 4 gom thành **36 quyết định `3-Q…`**. Mục 5 là kế hoạch vá từng file theo thứ tự chặng. Mục 6 là 4 câu còn cần Tuấn Anh chọn.

---

## 1. Phạm vi thật của Phase 3 và cách chia chặng

### 1.1. Cổng 3 phần code đòi gì [Chốt §5.1 + decisions §4]

| Tiêu chí cổng 3 (code, ScriptedLLM) | Node/nền tảng phải là code thật |
|---|---|
| TC02: R20 allow, gia hạn gọi đúng 1 lần, ticket đóng | B3, B6, B8–B9, B10 (need=action), B11, B12–B13, **B17**, B18, B19 |
| TC04, TC05: trả lời có trích dẫn, không sinh Action; TC05 đủ bước (D-24) | P3 (retrieve + expand), P4, B10, P2 |
| TC06: 0 câu hỏi lại; tắt chẩn đoán → phải hỏi | B6 (tự tìm máy theo chủ sở hữu), B11 |
| TC28 (RAG lỗi → E2), TC16 (không có tài liệu → E3) | B8–B9 |
| Mọi luật VPN có test; M5 không nhận câu người dùng; luật khớp thì không gọi LLM | B12 (R16–R20) |
| Hỏi lại ≤ 3 lượt × ≤ 2 slot; lạc đề 2 lần / quá 24 h → E4 | B11, `clarify_wait`, worker |

Phần cần LLM thật (demo 4 ca, intent ≥ 18/20, biểu đồ ngưỡng) dồn về mốc G. Riêng **một lần** chạy luồng VPN với model rẻ sau khi xong cổng code Phase 3 thì giữ lại (decisions §4).

### 1.2. Chia chặng [Đề xuất]

| Chặng | Phạm vi | Phụ thuộc | TC cổng 3 phủ | Cần KB thật? | Rủi ro | Model |
|---|---|---|---|---|---|---|
| **3a** | ml-service (`/embed`, `/rerank`, `/count_tokens`, `/health`, 2 endpoint classify trả 503), compose, `MlClient`, `FakeMlService` | — | — | Không | Thấp | `opusplan` |
| **3b** | Ingest (front matter, chunk theo token, BM25, `kb_version`, alias, cổng kiểm), `retrieve()`, `expand_for_answer()`, node B8–B9, `/api/health` rag | 3a | TC16, TC28 | Không (KB tổng hợp trong `tests/fixtures`) | TB (lọc theo role) | `opusplan`; lọc role soi bằng Opus |
| **3c** | P2 gateway (registry, router, cache, trace, spend cap, backend `scripted`), ScriptedLLM có ca xấu, B2 thật (L0, L1 privacy guard, L2 regex, L4) | — (song song 3a–3b) | TC13 (sớm), canary | Không | **Cao** (an ninh) | **Opus** |
| **3d** | B3 (VPN, `ENABLED_INTENTS`), B6–B7 VPN, B10, B11 + `clarify_wait`, bảng `notifications` | 3b, 3c | TC04, TC05, TC06, E4 | Không | TB | `opusplan` |
| **3e** | B12–B13 luật R16–R20, estimator giả → E5, B17 gia hạn VPN (thay `RefusingExecutor`), B18, e2e cổng 3, `make gate3` | 3d | TC02, luật VPN, TC09 | Không | **Cao** (M5, B17) | **Opus** |

Nếu kiểm kê cho thấy P2 đã có sẵn một phần, có thể gộp 3c vào trước 3b. Không đảo 3e lên trước 3d vì B12 cần `Action` do B11 dựng.

---

## 2. Mức chi tiết từng tài liệu

| Tài liệu | Mức | Nhận xét |
|---|---|---|
| B03-B05, B06-B07, B10, B11, B12-B14, B17-B18, B19, P2 | Đủ ở mức node | Có mã giả, hợp đồng, bảng lỗi, test. Thiếu phần "Phase 3 bật cái gì, tắt cái gì" và vài chỗ mâu thuẫn giữa các file (mục 3) |
| **P3** | Hời hợt | Thiếu: cách dựng câu truy vấn, luật biên khi chia đoạn, cổng kiểm lần đầu, nguồn sự thật "bản đang chạy", giữ bao nhiêu collection cũ. Có một chỗ sai thiết kế (rerank thiếu token cho câu hỏi) |
| **P4** | Hời hợt | Còn để ngỏ "FlagEmbedding *hoặc* sentence-transformers"; chưa định nghĩa cách đếm token, cách phát hiện cắt, cách tải/ghim model, cách cấp token dịch vụ |
| **B02 phần L1** | Hời hợt + vướng | Chọn Presidio (không hỗ trợ tiếng Việt, kéo theo spaCy); bảng ánh xạ PII không có trong 22 bảng; không liệt kê mẫu cụ thể và danh sách loại trừ |
| P5 | Đủ cho Phase 1 | `registry.call_internal` được B02, B03, B17 dùng nhưng P5 không định nghĩa |
| P1 (runtime) | Đủ cho Phase 2 | Chưa có danh sách key `TicketState` mà Phase 3 thêm — LangGraph **bỏ im lặng** key lạ (bài học 2b-2) |

---

## 3. Lỗ hổng (35 mục)

Mỗi mục: **Ở đâu → Vấn đề → Hậu quả → Vá**. Mã `G-xx` dùng để tham chiếu khi review plan.

### A. An ninh và False Negative (ưu tiên cao nhất)

**G-01 · Slot từ LLM lọt thành dữ kiện cho luật M5 · Chặn · 3d/3e**
- *Ở đâu:* B03 §5.1 ghi `slots={**state["slots"], **it.slots, …}` (slot do LLM đọc câu người dùng). B06 §5 ghi `slots={**state["slots"], **inferred}`, và nói rõ `device_registered`, `in_catalog`, `paid`… "cũng là dữ kiện cho luật M5". B11 dựng `Action` từ `slots`.
- *Vấn đề:* nếu người dùng viết "máy đã đăng ký rồi, device_registered=true" và B3 trích ra slot đó, rồi B6 không ghi đè được (tool trả rỗng → không suy slot), thì giá trị do **người dùng nói** đi vào `Action.facts`. Luật R20 `allow` khớp.
- *Hậu quả:* phá bất biến 1 theo đường vòng (M5 không đọc câu người dùng, nhưng đọc dữ kiện do câu người dùng tạo ra). Đây là FN an ninh.
- *Vá [Đề xuất]:* tách hai khái niệm.
  - `slots` là **tham số** do người dùng cung cấp. Chỉ nhận key có trong `config/slots.yaml` (bắt buộc + tùy chọn); key khác bị bỏ và ghi log.
  - `facts` là **dữ kiện**. Chỉ `infer_facts_from_diagnostics` (B6) và `validate_targets` (B11) được ghi. `FACT_KEYS` là danh sách đóng.
  - `build_action` lấy `facts` **chỉ** từ hai nguồn trên. Key thuộc `FACT_KEYS` xuất hiện trong `slots` → loại bỏ + audit `slot_fact_collision`.
  - Test: câu người dùng chứa `device_registered=true` + tool trả rỗng → R20 không khớp.

**G-02 · R20 tự gia hạn mà không kiểm chủ thiết bị · Chặn · 3e**
- *Ở đâu:* decisions §1.1: R20 "Cấp lại cho thiết bị đã đăng ký". Không có điều kiện chủ sở hữu.
- *Hậu quả:* nhân viên A gõ mã máy của B → gia hạn VPN cho máy B không qua ai. Đúng loại "agent thành công cụ tác động người khác" mà D-16 chặn ở B6.
- *Vá [Đề xuất]:* R20 = `action.type=renew_vpn_cert` ∧ `facts.device_registered=true` ∧ `facts.device_owner_is_requester=true` ∧ `target_is_other=false`. Thiếu fact → không khớp → đi đường "không luật nào khớp" (G-19). Thêm test suýt khớp cho từng điều kiện.

**G-03 · Tin trả lời của người dùng không qua sàng lọc injection · Chặn (cần chốt) · 3c/3d**
- *Ở đâu:* B2 chỉ chạy một lần sau B1. Câu trả lời ở `clarify_wait` và ghi chú xác nhận chỉ qua privacy guard ở API (B02 §2), rồi vào LLM `b11_extract_slots`.
- *Hậu quả:* bất biến 1 vẫn giữ (M5 không đọc câu chữ), nên không thành hành động nguy hiểm trực tiếp. Nhưng (a) không có cảnh báo E0 cho tấn công ở lượt 2, và (b) câu tấn công có thể lái việc trích slot (đã giảm rủi ro nhờ G-01).
- *Vá:* xem Q-mở 1 (mục 6).

**G-04 · `kb_version` không đổi khi sửa nội dung mà quên tăng `version` · Chặn · 3b**
- *Ở đâu:* P3 §4: `kb_version` = sha256 của các cặp `(doc_id, version)`.
- *Hậu quả:* tác giả sửa số cổng VPN nhưng quên tăng `version` → cùng `kb_version` → ingest coi là không đổi (hoặc tạo collection trùng tên). Câu trả lời dùng số cũ, còn lineage lại ghi như đúng bản mới. Sai số liệu mà không ai biết.
- *Vá [Đề xuất]:* `kb_documents` lưu `content_sha256` của từng tài liệu. Ingest gặp cùng `(doc_id, version)` mà khác `content_sha256` → **dừng**, in "sửa nội dung nhưng chưa tăng version". Công thức `kb_version` giữ nguyên [Chốt 17.4].

**G-05 · Lọc `sensitivity` phải phủ đủ 3 đường truy vấn · Nên · 3b**
- *Ở đâu:* P3 §6 đã ghi lọc ở lần 1, lần chạy lại D-23 và chunk liền kề D-24. Nhưng `expand_for_answer` (§6.1) lọc theo `doc_id` + `seq` **mà không có** điều kiện `sensitivity`/`enabled` trong mã giả.
- *Vá:* một hàm dựng filter duy nhất `base_filter(ctx)` (enabled + sensitivity), bắt buộc dùng ở cả 3 chỗ. Test integration: tài liệu restricted nằm liền kề một chunk public → employee không nhận.

### B. Mâu thuẫn giữa các file

**G-06 · Retry hai tầng ở RAG · Chặn · 3b**
- B08 §5 bọc `call_with_retry(rag.retrieve, …)`, còn P3 §6 bọc từng lời gọi embed/query/rerank. Tệ nhất 9 lần gọi; `tool_retry_count` sai.
- *Vá:* retry chỉ ở từng lời gọi ngoài trong `rag/`. B8 gọi `rag.retrieve` trực tiếp; `retrieve` ném `RetrievalSystemError(attempts=…)` khi hết retry; `tool_retry_count` = tổng số lần thử lại của các lời gọi.

**G-07 · `registry.call_internal` không được định nghĩa · Chặn · 3c/3e**
- B02 (`ml_classify`), B03 (`ml_classify_intent`), B17 (`ad_get_user`) gọi `registry.call_internal`; P5 chỉ có `registry.call`.
- *Vá [Đề xuất]:*
  - ml-service **không** phải tool (không có `allowed_steps`, không breaker của hệ thống ngoài). Gọi qua `MlClient` (P4), có `call_with_retry`, trả `(result, error, attempts)` giống kiểu `ToolResult`.
  - `ad_get_user` là **tool đọc** mới trong registry, `allowed_steps={"B11","B17"}`, cho cả `validate_targets` và kiểm lại người ở B17.
  - Bỏ tên `call_internal` khỏi spec.

**G-08 · B6 gọi tool thiếu `device_id` sẽ là lỗi hợp đồng → E9 · Chặn · 3d**
- P5 §6 (chốt 1c): "tool có `arg_slots` bắt buộc mà thiếu slot → lỗi hợp đồng (raise)". Còn TC06 thì người dùng không nói máy nào, và B6 §5 gọi cả 3 tool VPN.
- *Vá [Đề xuất]:* B6 VPN chạy **hai pha**.
  1. Chưa có `device_id` → gọi `list_devices_by_owner(requester)` (mock đã có `GET /vpn/devices?owner_id=`).
  2. Đúng 1 máy → gán `device_id` (nguồn: chẩn đoán) rồi gọi các tool cần `device_id`. 0 máy → `facts.has_registered_device=false`, bỏ qua tool cần `device_id`. ≥ 2 máy → không suy; B11 hỏi `device_id`.
  - Tool có `arg_slots` chưa đủ thì **không gọi** (lọc trước), đúng như P5 §6 yêu cầu.

**G-09 · `/api/health` khi chưa có alias · Nên · 3b**
- P3 §10 ghi "báo đỏ". Nhưng 2b-3-QD đã chốt kiểu: health 200 + trường trạng thái (`runtime: up|down`).
- *Vá:* thêm `rag: up|down` (alias `kb_current` tồn tại và Qdrant trả lời) và `ml: up|down`, cùng kiểu với `runtime`. Truy vấn khi `rag=down` → E2.

**G-10 · Lỗi structured output: E2 mở rộng hay mã riêng · Nên · 3c**
- P2 §10 và huong-dan 17.3 để mở.
- *Vá [Đề xuất]:* chốt **E2 mở rộng** cho B3/B10/B11, `escalations.reason_detail='llm_schema_error'` để M9 tách. Không thêm mã thoát (giữ E0–E9 [Chốt]).

**G-11 · Lần chạy lại D-23 bị lỗi hệ thống · Chặn · 3b**
- P3 §6 không nói. Code dễ trả kết quả lần 1 (điểm thấp) → E3 oan cho một lỗi hạ tầng.
- *Vá:* lần chạy lại lỗi hệ thống sau retry → **E2** (bất biến 6).

### C. Thiếu hợp đồng hiện thực

*RAG (P3, B08)*

**G-12 · Không đủ token cho câu hỏi khi rerank · Chặn · 3a/3b.** Chunk tối đa 480 token + câu hỏi phải lọt vào 512 của reranker. `redacted_request` có thể dài hàng trăm token.
- *Vá:* câu truy vấn cắt còn ≤ 128 token (tokenizer bge-m3, cắt phần đuôi, cờ `query_truncated`). Reranker `max_length=640`. `truncated` ở `/rerank` chỉ tính theo phần đoạn tài liệu, phải = 0. Đo lại p95 rerank; vượt 2 s thì giảm ứng viên 20 → 10 như P3 đã cho phép.

**G-13 · Dựng câu truy vấn chưa định nghĩa · Chặn · 3b.** P3 ghi "`redacted_request` + intent + tối đa 3 slot quan trọng" nhưng không nói slot nào, ghép thế nào.
- *Vá:* `text = redacted_request` (đã cắt ≤ 128 token). Chỉ nối thêm giá trị slot thuộc danh sách `QUERY_SLOTS = {error_code, software_name}`. **Không** nối `device_id` (vô nghĩa với KB). Intent chỉ dùng để lọc, không nối vào văn bản.

**G-14 · Một lượt truy hồi có thể đọc hai phiên bản KB · Chặn · 3b.** `current_kb_version()` gọi riêng với lúc truy vấn; alias đổi giữa chừng → lineage ghi sai.
- *Vá:* đầu `retrieve()` tra alias ra **tên collection một lần** (`kb_<version>`), mọi truy vấn trong lượt (lần 1, D-23, D-24) dùng tên đó; `kb_version` lấy từ tên collection.

**G-15 · Cổng kiểm trước khi đổi alias khi chưa có bộ kiểm tra / chưa có bản cũ · Chặn · 3b.**
- *Vá:* (a) chưa có `kb/eval/retrieval_set.yaml` → chỉ đổi alias với cờ `--allow-unevaluated`, ghi `recall_at5`/`false_grounding_rate` = NULL; (b) có bộ nhưng chưa có bản cũ → so ngưỡng tuyệt đối (Recall@5 ≥ 0,8; trả lời bừa ≤ 5%); (c) có cả hai → quy tắc so sánh P3 §5.4.

**G-16 · Nguồn sự thật "bản đang chạy" giữa Qdrant và Postgres · Nên · 3b.** Đổi alias (Qdrant) và cập nhật `kb_versions.is_current` (Postgres) không nguyên tử được.
- *Vá:* **alias là nguồn sự thật** (đó là thứ truy vấn dùng). Ghi `kb_versions` sau khi đổi alias. Chạy lại `make ingest` tự sửa lệch. Giữ **2 collection cũ** để quay lui (không xóa ngay như P3 §2 bước 7).

**G-17 · Luật biên khi chia đoạn · Nên · 3b.** P3 chỉ nói "< 120 thì gộp với đoạn kế cùng heading".
- *Vá:* gộp với đoạn kế cùng H2; đoạn cuối thì gộp với đoạn trước; gộp mà vượt 380 thì giữ nguyên đoạn ngắn; tài liệu ngắn cả bài < 120 là một chunk hợp lệ; một **câu** > 380 token → lỗi ingest. BM25 tính trên **cùng văn bản** với dense (có tiền tố heading). Tách từ dùng `pyvi` (underthesea để ablation).

**G-18 · E3 lưu `kb_gap_query` ở đâu · Nên · 3b.** B08 §8 nhắc cột này nhưng P7 không có.
- *Vá:* không thêm cột. `reason_detail='no_grounding'`; câu truy vấn đã che nằm ở điểm log 3 (`audit_logs.detail`). M9 đọc từ audit.

*ml-service (P4)*

**G-19 · Chọn thư viện · Chặn · 3a.** *Vá:* `sentence-transformers` (bge-m3 chỉ lấy dense; reranker bằng `CrossEncoder`, sigmoid). Không FlagEmbedding (thừa sparse/colbert, phụ thuộc nặng). Ghim `revision` (commit HF) trong config, trả về qua header `X-Model-Version`.

**G-20 · Đếm token và phát hiện cắt · Chặn · 3a.** *Vá:* `/count_tokens` đếm **cả** token đặc biệt (khớp cách model cắt). `truncated[i] = len(tokenize(text_i)) > max_length`, tính trước khi encode. Test tất định so vector bằng `allclose(atol=1e-6)` với cùng cách chia batch.

**G-21 · Tải model và bí mật dịch vụ · Chặn · 3a.** *Vá:*
- `make models` tải bằng `huggingface_hub.snapshot_download(revision=…)` vào `./models` (gitignored), mount read-only, container chạy với `HF_HUB_OFFLINE=1`.
- `ML_SERVICE_TOKEN` bắt buộc ở **mọi** env; thiếu thì ml-service không khởi động (fail-closed, cùng tinh thần 2b-Q2). Agent chỉ ghi tên biến vào `.env.example`.

*B2 (privacy guard + sàng lọc)*

**G-22 · Presidio không phù hợp · Chặn · 3c.** *Vá:* bỏ Presidio ở Phase 3; regex + entropy tự viết trong `guard/privacy.py`. Lý do: không có NLP tiếng Việt, mọi recognizer vẫn là regex; Presidio còn kéo theo spaCy.

**G-23 · Bảng ánh xạ PII không tồn tại · Chặn · 3c.** *Vá:* Phase 3 **không lưu** giá trị gốc: thay bằng nhãn đánh số (`<SĐT_1>`), không giữ ánh xạ. Lý do: slot không cần PII; không có bảng; không lưu thì không thể rò. Nếu sau cần thì thêm bảng + migration + khóa riêng.

**G-24 · Danh sách mẫu và loại trừ · Chặn · 3c.** *Vá:* chốt trong `config/privacy_patterns.json`:
- **Bí mật:** cụm "mật khẩu / mk / pass / password / pwd" + ("là" | ":" | "=") + chuỗi; JWT; PEM; `sk-…`; chuỗi ≥ 20 ký tự không khoảng trắng có entropy ≥ 4,0.
- **PII:** SĐT VN `(\+84|0)(3|5|7|8|9)\d{8}`, CCCD 12 số, email.
- **Loại trừ khỏi entropy:** đường dẫn thư mục, mã thiết bị `[A-Z]{2,4}-\d{3,5}`, username theo mẫu AD, mã lỗi `0x…`.
- Test mỗi mẫu có ca khớp + suýt khớp.

**G-25 · Guard áp ở đâu, lỗi thì sao, báo người dùng thế nào · Chặn · 3c.** *Vá:*
- Áp cho: tạo ticket, messages, note duyệt, confirm, reply.
- Guard ném lỗi → **503, không lưu gì**.
- `notices` trả trong body 202.
- `security_events(privacy_secret_redacted)` ghi cùng transaction với INSERT.

*LLM (P2) và ScriptedLLM*

**G-26 · Phase 3 chưa có provider thật · Chặn · 3c.** *Vá:*
- `LLM_BACKEND=scripted|real`; `scripted` chỉ được dùng khi `APP_ENV ∈ {dev,test}` (cùng khuôn `NotRedactingGuard`).
- Model không có dòng `pricing` → **từ chối gọi** (`LLMBudgetExceeded`) để bảo vệ ngân sách.
- ScriptedLLM **thiếu kịch bản cho một prompt → ném lỗi** (test đỏ, không tự trả mặc định). Có fixture `vpn_scripts()` dùng chung.
- Trên stack compose, kịch bản chọn theo thẻ `[fake:<preset>]` như 2b-4.

*Node*

**G-27 · Phase 3 chỉ bật VPN: intent khác và câu nhiều ý đi đâu · Chặn · 3d.** *Vá:* `ENABLED_INTENTS=["vpn"]` (settings). Intent khác → E1 `reason_detail='intent_not_enabled'`; câu nhiều ý → E1 `reason_detail='multi_intent_not_enabled'`. Phase 5 bỏ cờ. An toàn: không đoán, không đi tiếp.

**G-28 · Tin nhắn gửi người dùng nằm ở đâu để GET đọc được · Chặn · 3d.** Việc treo ghi "bảng `notifications` trước Phase 4", nhưng B10/B11/B18 ở Phase 3 đã gửi tin thật.
- *Vá [Đề xuất]:* đưa bảng `notifications` vào **chặng 3d** (migration mới, P7 lên 23 bảng). `notify_user` qua `effects.once` ghi một dòng; `GET /api/tickets/{id}` trả danh sách tin.

**G-29 · Giờ hành chính cho R18 chưa định nghĩa · Chặn · 3e.** *Vá:* `policy.json.business_hours = {tz: "Asia/Ho_Chi_Minh", days: [1..5], start: "08:00", end: "18:00"}`. Giờ lấy từ `Clock` (FakeClock test được). Không xét ngày lễ ở bản đầu.

**G-30 · Không luật nào khớp ở Phase 3 (lớp LLM là Phase 6) · Chặn · 3e.** *Vá:* estimator Phase 3 là `DisabledEstimator` ném `LLMUnavailable`. Nhánh sẵn có của B12 xử lý → **E5** ("không ước lượng được rủi ro → không tự làm"). Không thêm ngữ nghĩa mới. `reason_detail='llm_layer_disabled'`.

**G-31 · Luật R16 "kiểm tra trạng thái VPN" không có hành động ghi · Nên · 3e.** *Vá:* R16 áp cho `action.type=check_vpn_status` với `PLAN=[]`. B17 không gọi tool ghi nào, B18 gửi kết quả chẩn đoán. Kiểm lại luật/người ở B17 vẫn chạy.

### D. Hạ tầng và kiểm thử

**G-32 · Thay node giả có thể làm hỏng `make gate2` · Chặn · mọi chặng.** [Suy luận] Các preset của 2b-4 dựa vào node giả + `FAKE_SCENARIO`. Thay bằng node thật mà không giữ đường cho gate2 → cổng 2 không chạy lại được.
- *Vá:* (a) thành viên xác nhận cổng 2 chạy trên **commit `2a9f3ee`** (`git checkout 2a9f3ee`), không chạy trên nhánh đang làm Phase 3; (b) agent giữ gate2 chạy được (builder chọn node giả khi `FAKE_SCENARIO` đặt, chỉ dev/test) **hoặc** chuyển các preset sang ScriptedLLM trên node thật. Chọn trong plan 3d.

**G-33 · `TicketState` chưa có danh sách key của Phase 3 · Chặn · 3b trở đi.** LangGraph bỏ im lặng key lạ (bài học 2b-2).
- *Vá:* P1 thêm bảng key Phase 3 (mục 5). Mỗi kiểu Pydantic mới trong state (`Action`, `ChunkRef`, `RiskDecision`, `ExecutionResult`) có test **round-trip qua checkpoint Postgres**.

**G-34 · Dữ liệu test dùng chung chưa định nghĩa · Nên · 3b/3d.** *Vá:*
- `tests/fixtures/kb/`: 5–6 tài liệu VPN tổng hợp — hỏi cổng (TC04), xử lý lỗi 809 trải 3 chunk (TC05, D-24), 1 tài liệu `restricted`, 1 tài liệu `enabled=false`; **không** có MFA (TC16).
- Seed mock: user có 1 máy đã đăng ký + cert hết hạn (TC02, TC06); user có 2 máy; user `probation` (R19); máy của người khác (G-02).
- Bộ kiểm tra truy hồi thật (`kb/eval/retrieval_set.yaml`) do TV1 soạn, **không** dùng trong CI.

**G-35 · Xác nhận cổng 3 thủ công bằng gì · Nên · 3e.** *Vá:* thêm `make gate3` (chỉ dev, cùng khuôn gate2): TC02, TC04, TC05, TC06, TC16, TC28 trên stack compose với ScriptedLLM preset; người không làm chính chạy.

---

## 4. Danh sách quyết định đề xuất (`3-Q…`, ghi vào `decisions.md` §4.1)

| Mã | Chốt | Vá lỗ hổng | File spec nhận mục 5.1 |
|---|---|---|---|
| 3-Q1 | Tách `slots` (tham số, whitelist `slots.yaml`) khỏi `facts` (chỉ từ chẩn đoán + `validate_targets`, `FACT_KEYS` đóng) | G-01 | B03, B06, B11, B12 |
| 3-Q2 | R20 thêm `device_owner_is_requester` + `target_is_other=false` | G-02 | decisions §1.1, B12 |
| 3-Q3 | Tin trả lời qua sàng lọc — **chờ Q-mở 1** | G-03 | B02, B11, B19 |
| 3-Q4 | `kb_documents.content_sha256`; cùng version khác nội dung → ingest dừng | G-04 | P3, P7 |
| 3-Q5 | `base_filter(ctx)` duy nhất cho lần 1, D-23, D-24 | G-05 | P3, B08 |
| 3-Q6 | Retry một tầng trong `rag/` | G-06 | P3, B08 |
| 3-Q7 | Bỏ `call_internal`: ml-service qua `MlClient`; `ad_get_user` là tool đọc `{B11,B17}` | G-07 | P4, P5, B02, B03, B17 |
| 3-Q8 | B6 VPN hai pha, tìm máy theo chủ sở hữu; tool thiếu slot thì không gọi | G-08 | B06 |
| 3-Q9 | Health thêm `rag`, `ml` (up/down), 200 như `runtime` | G-09 | P3, P4, 01 |
| 3-Q10 | Structured output lỗi → E2 mở rộng, `reason_detail='llm_schema_error'` | G-10 | P2 |
| 3-Q11 | Lần chạy lại D-23 lỗi hệ thống → E2 | G-11 | P3, B08 |
| 3-Q12 | Câu truy vấn ≤ 128 token; reranker `max_length=640`; đo lại p95 | G-12 | P3, P4 |
| 3-Q13 | Câu truy vấn = `redacted_request` + `QUERY_SLOTS={error_code, software_name}` | G-13 | P3 |
| 3-Q14 | Ghim collection một lần mỗi lượt truy hồi | G-14 | P3 |
| 3-Q15 | Cổng kiểm alias 3 trường hợp (chưa có bộ / chưa có bản cũ / đủ) | G-15 | P3 |
| 3-Q16 | Alias là nguồn sự thật; giữ 2 collection cũ | G-16 | P3 |
| 3-Q17 | Luật biên chunk; BM25 cùng văn bản với dense; `pyvi` | G-17 | P3 |
| 3-Q18 | `kb_gap_query` nằm ở điểm log 3; `reason_detail='no_grounding'` | G-18 | B08 |
| 3-Q19 | `sentence-transformers`; ghim revision HF | G-19 | P4, 01 §6 |
| 3-Q20 | `/count_tokens` gồm token đặc biệt; cách tính `truncated`; so vector bằng allclose | G-20 | P4 |
| 3-Q21 | `make models`, `HF_HUB_OFFLINE=1`; `ML_SERVICE_TOKEN` bắt buộc | G-21 | P4, 01 |
| 3-Q22 | Bỏ Presidio | G-22 | B02, 01 §6 |
| 3-Q23 | Không lưu ánh xạ PII ở Phase 3 | G-23 | B02 |
| 3-Q24 | Danh sách mẫu + loại trừ trong `privacy_patterns.json` | G-24 | B02 |
| 3-Q25 | Guard: 5 điểm áp, lỗi → 503, `notices` trong 202, `security_events` cùng transaction | G-25 | B02 |
| 3-Q26 | `LLM_BACKEND=scripted` chỉ dev/test; thiếu `pricing` → từ chối; ScriptedLLM thiếu kịch bản → lỗi | G-26 | P2 |
| 3-Q27 | `ENABLED_INTENTS=["vpn"]`; khác / nhiều ý → E1 có `reason_detail` | G-27 | B03 |
| 3-Q28 | Bảng `notifications` vào chặng 3d | G-28 | P7, B10, B11, B17 |
| 3-Q29 | `business_hours` trong `policy.json` | G-29 | B12 |
| 3-Q30 | Phase 3: `DisabledEstimator` → E5 `llm_layer_disabled` | G-30 | B12 |
| 3-Q31 | R16 `check_vpn_status` với `PLAN=[]` | G-31 | B12, B17 |
| 3-Q32 | Cổng 2 xác nhận trên `2a9f3ee`; giữ gate2 chạy được | G-32 | decisions §4.1 |
| 3-Q33 | Bảng key `TicketState` Phase 3 + test round-trip checkpoint | G-33 | P1 |
| 3-Q34 | Fixture KB + seed dùng chung | G-34 | P3, P5 |
| 3-Q35 | `make gate3` (chỉ dev) | G-35 | 01 §7.1 |
| 3-Q36 | Chia chặng 3a–3e như mục 1.2 | — | decisions §4.1 |

---

## 5. Kế hoạch vá tài liệu

Làm theo quy trình mục 7 của `claude/ngu-canh-phien-review.md`: thêm mục **"5.1 Chốt khi hiện thực Phase 3"** (bảng Điểm | Chốt | Lý do), dòng nhật ký, tăng phiên bản; không viết lại mã giả gốc. Vá **theo chặng**, để agent 3a không phải chờ phần B2/B17.

| Đợt | Trước chặng | File và nội dung |
|---|---|---|
| **1** | 3a, 3b | **P4** §5.1 (3-Q7 phần ml, Q9, Q12, Q19–Q21) · **P3** §5.1 (Q4–Q6, Q11–Q17, Q34 phần KB) · **B08-B09** §5.1 (Q5, Q6, Q11, Q18) · **P7** (`kb_documents.content_sha256`) · **P1** §5.1 (bảng key `TicketState` Phase 3 — Q33) · **decisions** §4.1 (Q36 chia chặng, Q32) · **01** §6 (thư viện), §7.1 (`make models`) |
| **2** | 3c | **P2** §5.1 (Q10, Q26) · **B02** §5.1 (Q3 sau khi chốt, Q22–Q25) · **P5** §6.2 (Q7: bỏ `call_internal`, thêm `ad_get_user`) |
| **3** | 3d | **B03** §5.1 (Q1 phần slot, Q27) · **B06** §5.1 (Q1 phần facts, Q8) · **B10** §5.1 (Q28) · **B11** §5.1 (Q1, Q28) · **P7** (bảng `notifications`) · **P5** (seed, Q34) |
| **4** | 3e | **B12-B14** §5.1 (Q2, Q29–Q31) · **decisions** §1.1 (điều kiện R20) · **B17-B18** §5.1 (Q7 phần AD, Q31, PLAN gia hạn VPN) · **01** §7.1 (`make gate3`) |

Mỗi đợt: sửa trong Project → chép xuống `docs/spec/` qua cầu nối máy → kiểm md5 → báo agent danh sách file để stage chung commit của chặng đó.

---

## 6. Câu còn cần Tuấn Anh chọn

**Q-mở 1 — Sàng lọc tin trả lời (G-03).**

| Phương án | Làm gì | Đánh đổi |
|---|---|---|
| **A (khuyên)** | Chạy L0 + L2 (regex, rẻ) trên mọi tin trả lời trong node chờ. Khớp → `S_ESCALATED` + `exit_code=E0` + `security_events`, thông báo trung tính | Bắt được tấn công lượt 2, gần như không tốn gì. Phải kiểm lại bảng chuyển trạng thái: từ `S_CLARIFYING`/`S_CONFIRMING` sang `S_BLOCKED` có được phép không; D-29 chắc chắn cho mọi trạng thái chưa kết thúc → `S_ESCALATED` |
| B | Chạy đủ L0–L4 cho mọi tin trả lời | Chặt nhất nhưng thêm 1 lời gọi LLM mỗi lượt trả lời |
| C | Không sàng lọc, dựa vào bất biến 1 + 3-Q1 | Rẻ nhất; mất tín hiệu an ninh ở lượt 2 |

**Q-mở 2 — Đưa bảng `notifications` vào Phase 3 (G-28).** Khuyên: có. Nếu không thì tin nhắn chỉ nằm trong checkpoint, và mọi test "đúng 1 tin" phải đọc checkpoint.

**Q-mở 3 — Không lưu ánh xạ PII (G-23).** Khuyên: không lưu ở Phase 3. Nếu nhóm muốn L2 xem được SĐT thật thì phải thêm bảng mã hóa + khóa riêng.

**Q-mở 4 — Chọn giữ gate2 hay chuyển preset (G-32).** Khuyên: để agent đề xuất trong plan 3d. Trước mắt, thành viên xác nhận cổng 2 phải chạy trên `2a9f3ee`.

---

## 7. Việc dữ liệu chạy song song (không chặn code)

- **TV1:** 5 tài liệu KB VPN + `kb-facts.md` + `kb/eval/retrieval_set.yaml` (30 câu có đáp án + ≥ 20 câu không, ≥ 8 câu gần chủ đề) theo định dạng 3-Q15/3-Q34. Claude chat soạn mẫu trước.
- **Thành viên xác nhận cổng 2:** `git checkout 2a9f3ee` rồi `make gate2 S=all` + `nvidia-smi`.
- **Tuấn Anh (sau 3a):** đo RAM khi nạp 2 model, embed p95, rerank 20 đoạn p95 trên Mac.

## 8. Nhật ký

| Ngày | Thay đổi |
|---|---|
| 27/09/2026 | Tạo file |
