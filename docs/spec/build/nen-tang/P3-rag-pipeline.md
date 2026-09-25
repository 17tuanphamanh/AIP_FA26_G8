# P3 — RAG pipeline (M2: `backend/app/rag/`)

*Thuộc bộ `build/`. Dùng bởi B8–B9 (truy vấn) và B10 (câu trả lời có trích dẫn). Phase 3 (KB VPN, cổng K1), Phase 5 (≥ 16 tài liệu, cổng K2). Bản vá v1.2: D-21 (chunk theo token), D-22 (câu âm tính), D-23 (fallback lọc intent), D-24 (mở rộng ngữ cảnh), D-25 (KB có tài liệu gây nhiễu + ablation).*

---

## 0. Ngữ cảnh nạp sẵn

*File nền tảng này **tự đứng được**: khối ngữ cảnh chung dưới đây giúp người đọc hoặc coding agent hiểu phần này nằm ở đâu trong dự án mà không cần mở tài liệu khác. Phần riêng của thành phần bắt đầu từ mục 1.*

### 0.1. Khối ngữ cảnh chung của dự án

*Khối này giống hệt nhau ở mọi file trong `build/` (phiên bản khối: **CTX-1.1, 25/09/2026**). Khi tài liệu gốc thay đổi, cập nhật khối này ở tất cả các file cùng lúc và tăng số phiên bản.*

**Đề tài:** AI Agent tự động hóa hỗ trợ IT Service Desk cấp 1 với cơ chế Human-in-the-Loop (EN: *Agentic AI for Level-1 IT Service Desk Automation with Human-in-the-Loop*). Đồ án tốt nghiệp, ĐH FPT, chuyên ngành AI, nhóm 4 người.

**Ba mục tiêu đã chốt:**

| Mục tiêu | Trọng số | Nội dung |
|---|---|---|
| Obj 1 | 50–60% | Agent xử lý yêu cầu L1: M1 phân loại + slot, M2 RAG, M3 tool + chẩn đoán chủ động, M4 điều phối, cùng lớp kỹ thuật agent (trace, bộ nhớ, harness, LLMOps, riêng tư) |
| Obj 2 | 30–40% | Human-in-the-Loop: M5 quyết định khi nào cần người (đóng góp chính), M6 phê duyệt, M7 audit |
| Obj 3 | 0–20% | Đánh giá: bộ kịch bản, so sánh 4 phương án, ablation (M8) |

**Nguyên tắc dự án:**

- Objective quyết định xây gì → Phase quyết định xây khi nào → RQ chỉ quyết định đo gì.
- Luôn phân biệt **[Chốt] / [Suy luận] / [Đề xuất]**.
- Ưu tiên thay đổi nhỏ, kiểm chứng được.
- Với an toàn: **giảm False Negative trước**, giảm escalate thừa sau.

**Bốn nguyên tắc thiết kế [Chốt]:**

1. An toàn ưu tiên hơn tự động hóa.
2. Mọi quyết định giải thích được.
3. Luật cứng có quyền phủ quyết LLM.
4. Chủ động chẩn đoán trước khi hỏi.

**Phạm vi:**

- 4 loại yêu cầu: `account`, `vpn`, `software`, `access`.
- Tiếng Việt.
- Hệ thống ngoài giả lập bằng mock FastAPI.

**4 vai trò [Chốt 2.2]:**

| Vai trò | Quyền chính |
|---|---|
| Nhân viên | Gửi yêu cầu, xem ticket của mình |
| L1 | Duyệt, ghi đè, nhận escalate |
| Trưởng BP IT | Sửa policy, dashboard/audit toàn bộ, cập nhật KB |
| L2 | Nhận escalate, cập nhật KB, **không duyệt** |

L1 không được sửa policy.

**Luồng 20 bước [Chốt]:**

B1 xác thực → B2 chặn injection (E0) → B3 intent → B4 trong phạm vi? (E1) → B5 tách ý → B6 chẩn đoán chủ động → B7 lỗi hệ thống ≠ rỗng (E2) → B8 tra KB (E2) → B9 có căn cứ? (E3) → B10 chỉ cần trả lời? → B11 đủ thông tin? (E4) → B12 luật → B13 quyết định theo luật → B14 LLM hiệu chỉnh (E5) → B15 xung đột lợi ích + `action_plan_hash` → B16 chờ duyệt (E6) → B17 thực thi (E7/E5) → B18 thông báo → B19 xác nhận (E8) → B20 audit + `close_reason`.

Mọi node có lớp bọc lỗi chưa lường trước → E9.

**14 trạng thái:**

- Xử lý: `S_NEW`, `S_SCREENING`, `S_CLASSIFYING`, `S_DIAGNOSING`, `S_RETRIEVING`, `S_ASSESSING`, `S_EXECUTING`.
- Chờ người: `S_CLARIFYING` (24h), `S_PENDING_APPROVAL` (30 phút), `S_CONFIRMING` (48h).
- Kết thúc hoặc chuyển giao: `S_ESCALATED`, `S_RESOLVED`, `S_REJECTED`, `S_BLOCKED`.

**Mã thoát và ưu tiên hàng đợi L2:**

| Mã | Tình huống | Ưu tiên |
|---|---|---|
| E0 | Prompt injection | An ninh |
| E1 | Ngoài phạm vi | Thường |
| E2 | Tool/RAG lỗi hệ thống sau retry | Hạ tầng |
| E3 | Không có căn cứ (`NO_EVIDENCE`) | Thường, kèm cờ bổ sung KB |
| E4 | Hỏi 3 lần vẫn thiếu | Thường |
| E5 | Rủi ro cao / `deny` / hash lệch | Cao |
| E6 | Hết hạn duyệt (fail-safe) | Có SLA |
| E7 | Thực thi lỗi | Rất cao |
| E8 | Người dùng báo chưa xong | Thường |
| E9 | Lỗi chưa lường trước | Ngang E2 |

**`block_reason`:** `invalid_credentials` (không phải sự cố an ninh), `repeated_auth_failure`, `injection_detected`.

**`close_reason` (8 giá trị):** `resolved_user_confirmed`, `resolved_auto_timeout_48h`, `resolved_after_escalation`, `resolved_after_deny_review`, `rejected_by_approver`, `blocked_invalid_credentials`, `blocked_repeated_auth_failure`, `blocked_injection_detected`.

**8 điểm log bắt buộc:**

| Điểm | Bước | Nội dung |
|---|---|---|
| 1 | B3 | intent |
| 2 | B6 | chẩn đoán |
| 3 | B8 | tra cứu |
| 4 | B12–14 | quyết định rủi ro — quan trọng nhất |
| 5 | B15 | vào hàng đợi duyệt |
| 6 | B16 | kết quả duyệt |
| 7 | B17 | thực thi |
| 8 | B20 | kết thúc |

**Hằng số trong `policy.json`:**

| Hằng số | Giá trị |
|---|---|
| `MAX_LOOPS` | 5 |
| `MAX_CLARIFICATION_TURNS` | 3 |
| `TOOL_RETRY` | 2 (backoff 1s, 2s) |
| `MAX_AUTH_FAILURES` | 5 trong 10 phút |
| `SLA_MINUTES` | 30 |
| `THRESHOLD_LOW` / `THRESHOLD_HIGH` | 0,25 / 0,75 (sẽ chọn lại trên tập calibration) |
| `RETRIEVAL_THRESHOLD` | 0,6 |
| `CLARIFY_TIMEOUT` | 24h |
| `CONFIRM_TIMEOUT` | 48h |

**Công nghệ [Chốt + Đề xuất]:**

- Python 3.12, FastAPI, Pydantic v2.
- LangGraph + checkpoint Postgres.
- PostgreSQL 16 + SQLAlchemy 2 + Alembic.
- Qdrant + bge-m3 + bge-reranker-v2-m3 + BM25/RRF.
- LLM gateway fast/strong, API hoặc local.
- httpx, APScheduler.
- React + Vite + TS.
- Docker Compose, Caddy, GitHub Actions.
- Kiến trúc modular monolith + ml-service + mock (D-13).
- DB 22 bảng (P7).

**Bất biến toàn cục (không nhánh nào được phá):**

1. M5 không bao giờ đọc câu người dùng. `policy_engine.evaluate(action, ctx)` chỉ nhận hai tham số đó.
2. B17 là điểm ghi duy nhất ra hệ thống ngoài; chỉ `svc_executor` có credential ghi.
3. Mọi đổi trạng thái đi qua `goto()` (kiểm chuyển hợp lệ + ghi audit).
4. Mọi nhánh kết thúc ở B20.
5. Hết hạn duyệt không bao giờ tự thực thi.
6. Lỗi hệ thống ≠ kết quả rỗng.
7. Luật `deny` không bao giờ vào hàng đợi duyệt, và L2 không thực hiện lại hành động bị `deny`.
8. Việc cần làm trước khi chờ người nằm ở node đứng trước; sự kiện đến muộn bị bỏ qua (409). Ngoại lệ: tín hiệu `wake_parent` từ ticket con chỉ để đánh thức ticket cha, không bị 409 (D-17).
9. M9 chỉ đọc.
10. Ngưỡng và calibrator chỉ được fit trên tập calibration.
11. Role của người gửi chỉ lấy từ AD, không từ lời người dùng.
12. Một lượt người dùng — một tin trả lời: ticket con không tự nhắn, ticket cha gom (D-31).
13. Mọi chỉ số M8/M9 tính trên ticket lá (`is_parent = false`) (D-30).

**Mã quyết định mới (đã chốt theo đặc tả 25/09/2026):** D-01…D-33 — danh sách đầy đủ, trạng thái và các quyết định Q1–Q14 ở `build/decisions.md`. Các mã mà file này dùng được liệt kê ở mục 0.5 (file nền tảng: trong thân bài).

**Mã quyết định dùng trong file (bản vá v1.2):** D-09, D-10, D-21, D-22, D-23, D-24, D-25.

---

## 1. Mục đích

- Tìm đúng đoạn tài liệu nội bộ để agent trả lời có căn cứ.
- Tách bạch rõ hai tình huống: không có tài liệu (E3) và hạ tầng hỏng (E2).
- Mọi câu trả lời tái lập được theo `kb_version`.
- **Chứng minh được giá trị của từng thành phần** (dense, BM25, rerank) bằng số liệu, không chỉ bằng lập luận (D-25).

### 1.1. Cấu hình model tóm tắt

| Thành phần | Model / công nghệ | Chạy ở |
|---|---|---|
| Embedding dense | `BAAI/bge-m3`, 1024 chiều, cosine, `max_length=512` | ml-service (CPU) |
| Sparse | BM25 tự tính, tách từ `pyvi`, IDF phía Qdrant | backend + Qdrant |
| Gộp | RRF (Qdrant Query API) | Qdrant |
| Rerank | `BAAI/bge-reranker-v2-m3` (cross-encoder, sigmoid 0..1) | ml-service (CPU) |
| Vector DB | Qdrant, collection theo `kb_version`, alias `kb_current` | service riêng |

## 2. Sơ đồ cấu tạo

```
INGEST (make ingest, offline)
kb/*.md ─► [1 Kiểm front matter] ─► [2 Làm sạch, NFC] ─► [3 Chia đoạn theo H2/H3,
          (Pydantic, đối chiếu       (bỏ HTML, chuẩn      đo bằng TOKEN bge-m3 (D-21):
           kb-facts.md)               khoảng trắng)        120–380 token nội dung, gắn đường
                                                            dẫn heading vào đầu đoạn, lưu seq)]
      ─► [4a Dense: ml-service /embed (bge-m3, 1024 chiều, chuẩn hóa)]
      ─► [4b Sparse: tách từ pyvi + giữ mã lỗi → tần suất từ → sparse vector]
      ─► [5 Upsert collection mới kb_<kb_version> (named vectors: dense, bm25; payload)]
      ─► [6 Kiểm bộ truy hồi trên collection mới: Recall@5 không tụt, tỉ lệ trả lời bừa
           trên câu âm tính không tăng (D-22)]
      ─► [7 Đổi alias kb_current → collection mới (nguyên tử) ─► snapshot ─► xóa bản cũ]
      ─► ghi bảng kb_versions, kb_documents

QUERY (B8, online)
câu đã che + intent + slot chính ─► build_query
      ─► Qdrant Query API trên alias kb_current:
           prefetch dense top-20 (filter) + prefetch bm25 top-20 (filter) ─► Fusion RRF ─► top-20
      ─► ml-service /rerank (bge-reranker-v2-m3, sigmoid 0..1) ─► top-5, bỏ trùng doc_id
      ─► max_score < RETRIEVAL_THRESHOLD ?
             lần 1 (có lọc intent) ─► chạy lại 1 lần KHÔNG lọc intent (D-23)
             vẫn thấp ─► NO_EVIDENCE (E3)
      ─► evidence → B10 (B10 ghép thêm chunk liền kề làm ngữ cảnh, D-24)
      (lỗi Qdrant/ml-service sau retry ─► SYSTEM_ERROR (E2))
```

## 3. Công nghệ

| Thành phần | Công nghệ | Cấu hình | Lý do |
|---|---|---|---|
| Nguồn | Markdown + YAML front matter trong `kb/` | nằm trong git | Có lịch sử, review qua PR **[Chốt 17.4]** |
| Tách từ tiếng Việt | `pyvi.ViTokenizer` (hoặc `underthesea.word_tokenize`) | lowercase, giữ nguyên token số/mã lỗi | "mật khẩu" là 1 từ; BM25 theo âm tiết cho nhiễu **[Đề xuất D-10]** |
| Đo độ dài chunk | Tokenizer của `BAAI/bge-m3` (XLM-RoBERTa), gọi qua ml-service `/count_tokens` (P4) | đếm token thật, không đếm từ | **[Đề xuất D-21]** — model cắt ở 512 token, đếm theo từ không bảo đảm được giới hạn này |
| Dense | `BAAI/bge-m3` qua ml-service | 1024 chiều, cosine, max_length 512 | Đa ngôn ngữ, tiếng Việt tốt, chạy local **[Chốt]** |
| Sparse | BM25: vector TF tự tính; Qdrant sparse vector với `modifier: idf` | k1, b mặc định của Qdrant | Qdrant tự tính IDF phía server theo collection |
| Vector DB | Qdrant, `qdrant-client` | 1 collection/phiên bản, alias `kb_current` | **[Chốt]**; đổi alias là thao tác nguyên tử |
| Gộp | Query API: `prefetch` + `FusionQuery(fusion=RRF)` | top-20 mỗi nhánh | RRF không cần quy đổi thang điểm **[Chốt]** |
| Rerank | `BAAI/bge-reranker-v2-m3` qua ml-service | 20 ứng viên (giảm còn 10 nếu p95 > 2 giây) | **[Chốt]** |

## 4. Schema dữ liệu

**Front matter (bắt buộc):**

```yaml
---
doc_id: KB-VPN-003
version: 2
request_type: vpn            # account | vpn | software | access | general
doc_type: troubleshooting    # policy | howto | troubleshooting | faq
owner: truongbp001
updated_at: 2026-09-20
sensitivity: internal        # public | internal | restricted
enabled: true
title: Xử lý lỗi VPN 809
distractor: false            # true = tài liệu gây nhiễu dùng cho đánh giá (D-25), vẫn là tài liệu hợp lệ
---
```

**Payload mỗi điểm (chunk) trong Qdrant:**

`chunk_id` (= `doc_id#v#seq`), `doc_id`, `version`, `seq` (thứ tự trong tài liệu, dùng cho D-24), `request_type`, `doc_type`, `sensitivity`, `enabled`, `heading_path`, `text`, `kb_version`, `token_count`.

**Payload index:** `request_type`, `sensitivity`, `enabled` (keyword), `doc_id` (keyword, cho D-24), để filter nhanh.

**`kb_version`** = sha256 của danh sách đã sắp xếp các cặp `(doc_id, version)` còn `enabled` **[Chốt 17.4]**.

## 5. Chi tiết từng bước ingest

1. **Kiểm front matter.** Thiếu trường hoặc sai giá trị → dừng cả lượt ingest, in đúng file và dòng lỗi. Đối chiếu các con số trong bài với `kb-facts.md` (cổng, mã lỗi, thời hạn) bằng regex **[Chốt]**.
2. **Chia đoạn — theo token [Đề xuất D-21].**
   - Cắt theo H2/H3.
   - Đo bằng tokenizer bge-m3. Đoạn > **380 token nội dung** thì cắt tiếp theo đoạn văn, rồi theo câu. Đoạn < **120 token** thì gộp với đoạn kế tiếp cùng heading.
   - Văn bản mỗi chunk = `"{title} › {heading_path}\n\n{text}"`. Tiền tố thường 20–60 token; trần 380 cho nội dung chừa đủ chỗ để **tổng ≤ 480 token**, dưới giới hạn 512 của cả bge-m3 lẫn reranker (reranker còn phải ghép câu hỏi, xem mục 6).
   - Ghi `seq` = thứ tự chunk trong tài liệu.
   - **Vì sao gắn đường dẫn heading:** đoạn "Bước 3: khởi động lại dịch vụ" đứng một mình thì embedding không biết đó là dịch vụ gì.
   - **Vì sao đổi từ đếm từ sang đếm token (L-04):** bản 1.0 chia 300–450 **từ**. Tokenizer XLM-R thường sinh khoảng 1,3–1,8 token cho mỗi âm tiết tiếng Việt (con số này **phải đo lại** ở Phase 3 trên chính KB của nhóm). 450 từ có thể thành 600–800 token, vượt 512 → phần cuối chunk bị cắt khỏi cả embedding lẫn rerank **mà không có lỗi nào báo ra**. Các bước cuối của một hướng dẫn là thứ hay bị mất nhất.
3. **Sparse BM25.**
   - Tokenizer: `pyvi` → lowercase → loại stopword tiếng Việt (danh sách nhỏ, trong config) → **giữ nguyên** token khớp `\b(0x[0-9a-f]+|\d{3,})\b`.
   - Chuẩn hóa viết tắt trước khi tách từ bằng từ điển nhỏ `config/vi_abbrev.yaml` (`mk → mật khẩu`, `ko/k → không`, `dc/đc → được`, `pm → phần mềm`…), áp cho **cả** tài liệu lúc ingest lẫn câu hỏi lúc truy vấn **[Đề xuất nhỏ, đo bằng ablation mục 11]**.
   - Ánh xạ token → chỉ số bằng hash ổn định: `mmh3(token) mod 2^31`, lưu từ điển để debug.
   - Giá trị = số lần xuất hiện. Qdrant nhân IDF khi truy vấn nhờ `modifier: idf`.
4. **Kiểm trước khi đổi alias.** Chạy bộ kiểm tra truy hồi (mục 11) trên collection mới. Dừng và giữ alias cũ nếu:
   - Recall@5 thấp hơn bản đang chạy quá 0,05; hoặc
   - tỉ lệ "trả lời bừa" trên câu âm tính tăng quá 0,05 (D-22).
   - **Vì sao:** một tài liệu hỏng không được âm thầm làm giảm chất lượng hệ thống đang chạy.

## 6. Chi tiết truy vấn (hàm `retrieve`)

```python
async def retrieve(query: RetrievalQuery, ctx: RequesterContext) -> RetrievalResult:
    res = await _search(query, ctx, filter_intent=True)
    if res.top_score < policy.RETRIEVAL_THRESHOLD and query.intent:           # D-23
        alt = await _search(query, ctx, filter_intent=False)
        if alt.top_score >= policy.RETRIEVAL_THRESHOLD:
            alt.intent_filter_fallback = True        # tín hiệu: B3 có thể đã phân sai intent
            return alt
    return res

async def _search(query, ctx, *, filter_intent: bool) -> RetrievalResult:
    must = [FieldCondition(key="enabled", match=MatchValue(value=True)),
            FieldCondition(key="sensitivity", match=MatchAny(any=allowed_sensitivity(ctx.role)))]
    if filter_intent:
        must.append(FieldCondition(key="request_type", match=MatchAny(any=[query.intent, "general"])))
    flt = Filter(must=must)
    dense = await ml.embed([query.text])                   # span "rag:embed"
    sparse = bm25_vectorize(normalize_abbrev(query.text))
    hits = await qdrant.query_points("kb_current",
        prefetch=[Prefetch(query=dense[0], using="dense", limit=20, filter=flt),
                  Prefetch(query=sparse, using="bm25", limit=20, filter=flt)],
        query=FusionQuery(fusion=Fusion.RRF), limit=20, with_payload=True)
    scores = await ml.rerank(query.text, [h.payload["text"] for h in hits])   # span "rag:rerank"
    top = dedupe_by_doc(sorted(zip(hits, scores), key=lambda x: -x[1]))[:5]
    return RetrievalResult(chunks=[to_ref(h, s) for h, s in top],
                           top_score=top[0][1] if top else 0.0, kb_version=current_kb_version(),
                           intent_filter_fallback=False)
```

- **`allowed_sensitivity`:** employee → `{public, internal}`; l1, l2, manager → thêm `restricted` **[Đề xuất]**. Đây là cách nối phân quyền (P6) vào RAG. Lần chạy lại của D-23 **vẫn giữ** lọc `sensitivity` và `enabled`, chỉ bỏ lọc `request_type`.
- **Câu truy vấn:** `redacted_request` + intent + tối đa 3 slot quan trọng. Không dùng LLM viết lại truy vấn, để tiết kiệm 1 lời gọi và 1–3 giây.
- **Retry:** cả `ml.embed`, `qdrant.query_points`, `ml.rerank` đều bọc trong `call_with_retry` (2 lần, backoff 1s/2s) **[Chốt]**. Hết retry → `RetrievalSystemError` → node trả E2. Lần chạy lại D-23 là một truy vấn bình thường, không tính vào `tool_retry`.
- **Vì sao chỉ chạy lại một lần không lọc intent (D-23, L-06):** lọc cứng theo intent làm lỗi phân loại ở B3 biến thành "không có tài liệu" (E3 oan). Chạy lại một lần tốn thêm khoảng 1 lượt embed + rerank (≤ 2 giây) và **chỉ** ở những ca sắp E3. Cờ `intent_filter_fallback` giúp M9 thấy B3 phân sai thay vì đổ lỗi cho KB.

### 6.1. Ngữ cảnh cho B10 — ghép chunk liền kề [Đề xuất D-24]

`dedupe_by_doc` giữ một chunk mỗi tài liệu để top-5 đa dạng. Nhưng một hướng dẫn nhiều bước thường trải trên 2–3 chunk liền nhau, nên B10 có thể thiếu bước (L-09).

```python
async def expand_for_answer(chunks: list[ChunkRef], max_tokens=4000) -> list[EvidenceBlock]:
    blocks = []
    for c in chunks:                                         # giữ nguyên thứ tự và điểm
        neigh = await qdrant.scroll("kb_current", filter=Filter(must=[
                    FieldCondition(key="doc_id", match=MatchValue(value=c.doc_id)),
                    FieldCondition(key="seq", range=Range(gte=c.seq - 1, lte=c.seq + 1))]))
        blocks.append(EvidenceBlock(anchor_chunk_id=c.chunk_id,
                                    text=join_in_seq_order(neigh)))
    return trim_to_budget(blocks, max_tokens)                # cắt khối điểm thấp trước [Chốt 17.2]
```

- Không đổi `retrieval_score`, không đổi top-5, không đổi ngưỡng B9.
- Trích dẫn trong câu trả lời vẫn dùng `anchor_chunk_id`. Hậu kiểm trích dẫn của B10 không đổi.
- Chunk liền kề đi qua cùng lọc `sensitivity`.

## 7. Cấu hình

| Khóa | Giá trị | Ở đâu |
|---|---|---|
| `RETRIEVAL_THRESHOLD` | 0,6 (chọn lại ở Phase 3 trên bộ có câu âm tính, D-22) | `policy.json` **[Chốt]** |
| `RAG_PREFETCH_K` | 20 | `settings` |
| `RAG_RERANK_K` | 20 (hạ còn 10 nếu chậm) | `settings` |
| `RAG_TOP_N` | 5 | `settings` **[Chốt]** |
| `CHUNK_TOKENS_MIN` / `CHUNK_TOKENS_MAX` | 120 / 380 token nội dung (tổng ≤ 480 kèm tiền tố) | `rag/ingest/config.py` **[Đề xuất D-21]** |
| `RAG_INTENT_FALLBACK` | `true` | `settings` **[Đề xuất D-23]** |
| `RAG_NEIGHBOR_WINDOW` | 1 (±1 chunk) | `settings` **[Đề xuất D-24]** |

### 7.1. Cách chọn `RETRIEVAL_THRESHOLD` [Đề xuất D-22]

Bản 1.0 chọn ngưỡng bằng "biểu đồ phân phối điểm" trên 30 câu **có** đáp án. Không có câu **không có** đáp án thì không đo được hai loại lỗi của B9 (L-05):

| Lỗi | Nghĩa | Hậu quả |
|---|---|---|
| **Trả lời bừa** (false grounding) | KB không có đáp án nhưng điểm ≥ ngưỡng | B10 trả lời bằng tài liệu không liên quan — đúng loại lỗi "bịa chính sách" mà B9 tồn tại để chặn |
| **E3 oan** | KB có đáp án nhưng điểm < ngưỡng | Chuyển L2 thừa, giảm deflection |

**Quy trình:**

1. Bộ kiểm tra truy hồi gồm **30 câu có đáp án** (đã có) và **≥ 20 câu không có đáp án**. Trong 20 câu này có ít nhất 8 câu **gần chủ đề** (ví dụ MFA — cố ý không có tài liệu cho TC16; VPN trên Linux khi KB chỉ có Windows/Mac).
2. Quét ngưỡng 0,30…0,90 bước 0,05; với mỗi ngưỡng tính tỉ lệ trả lời bừa và tỉ lệ E3 oan.
3. Chọn ngưỡng **thấp nhất** sao cho tỉ lệ trả lời bừa ≤ 5% (ưu tiên giảm trả lời bừa, đúng nguyên tắc giảm False Negative của dự án), rồi báo cáo tỉ lệ E3 oan tại ngưỡng đó.
4. Ghi vào `policy.json` kèm biểu đồ hai đường.

Bộ này dùng để **chọn ngưỡng ở Phase 3**, không phải tập test của RQ. Không trộn với bộ kịch bản đánh giá.

## 8. Dữ liệu và DB

- **Postgres:**
  - `kb_versions` (`kb_version`, `created_at`, `doc_count`, `recall_at5`, `false_grounding_rate`, `is_current`)
  - `kb_documents` (metadata từng tài liệu) **[Chốt]**
- **Điểm log 3 (B8):** `query`, `top_score`, `doc_ids`, `retrieval_error`, `tool_retry_count` **[Chốt]**. Bổ sung thêm `kb_version`, `intent_filter_fallback`.
- **Qdrant:** snapshot sau mỗi lần ingest **[Chốt 13.4]**.
- **Nội dung KB [Chốt K1, K2 + Đề xuất D-25]:**
  - Cổng K1: 5 tài liệu VPN trước Phase 3. Cổng K2: **16 tài liệu tối thiểu** (4 mỗi loại) trước Phase 5 — giữ nguyên.
  - Mục tiêu mở rộng: **≥ 50 tài liệu**, trong đó khoảng 30% là **tài liệu gây nhiễu**: gần chủ đề nhưng khác đối tượng (VPN Windows / VPN macOS), khác phiên bản quy trình (quy trình cũ đã `enabled=false` và quy trình mới), khác phạm vi (quyền thư mục phòng khác). Tài liệu gây nhiễu là tài liệu hợp lệ, số liệu vẫn khớp `kb-facts.md`.
  - **Vì sao (L-10):** với 16 tài liệu × 300–800 từ, KB chỉ có khoảng 30–50 chunk. Hybrid + RRF + rerank top-20 khi đó gần như rerank toàn bộ KB, và Recall@5 ≥ 0,8 gần như chắc đạt — không chứng minh được thành phần nào đáng giá. Tài liệu gây nhiễu tạo ra đúng loại khó mà BM25 và reranker phải xử lý.

## 9. Trace và giám sát

- **Span:** `rag:embed`, `rag:search`, `rag:rerank`, mỗi span có thời lượng. Lần chạy lại D-23 có span riêng `rag:search_nofilter`.
- **M9:**
  - Tỉ lệ E3 theo tuần.
  - Danh sách query E3 → "lỗ hổng KB" cho Trưởng BP **[Chốt 16.3]**.
  - **Tỉ lệ `intent_filter_fallback`** theo intent → tín hiệu B3 phân sai (D-23).
  - p95 rerank.
  - Drift điểm truy hồi cao nhất (Nên có).

## 10. Lỗi và ca biên

| Tình huống | Kết quả | Mã |
|---|---|---|
| Qdrant timeout/5xx sau 2 lần retry | `SYSTEM_ERROR` | E2 **[Chốt]** |
| ml-service chết | `SYSTEM_ERROR` | E2 |
| Trả về rỗng | `NO_EVIDENCE` | E3 |
| Điểm cao nhất < ngưỡng, kể cả sau khi chạy lại không lọc intent | `NO_EVIDENCE` | E3 |
| B3 phân `account` thành `access`, tài liệu đúng bị lọc | Chạy lại không lọc → tìm thấy → đi tiếp, ghi `intent_filter_fallback` | — |
| Alias `kb_current` chưa tồn tại (chưa ingest) | `/api/health` báo đỏ; truy vấn → E2 | E2 |
| Tài liệu bị tắt (`enabled=false`) | Không có trong index mới | — |
| Chunk dài hơn giới hạn sau khi ghép tiền tố | Ingest báo lỗi, dừng lượt ingest | — |

## 11. Kiểm thử và tiêu chí đạt

| Test | Đạt khi |
|---|---|
| Unit: tokenizer BM25 | "mật khẩu" → 1 token; "lỗi 809" giữ "809"; "0x8004010F" giữ nguyên; "mk" → "mật khẩu" |
| Unit: chunker | **Không chunk nào > 480 token (tính cả tiền tố) theo tokenizer bge-m3**; mỗi đoạn có `heading_path`, `seq` liên tục (D-21) |
| Unit: `kb_version` | Ingest 2 lần cùng nội dung → cùng giá trị; đổi 1 `version` → khác |
| Unit: `expand_for_answer` | Chunk `seq=3` → ghép `seq=2,3,4` cùng `doc_id`; trích dẫn vẫn là `chunk_id` gốc (D-24) |
| Integration (Qdrant testcontainer) | Filter theo role: employee không nhận đoạn `restricted`, kể cả ở lần chạy lại D-23 và ở chunk liền kề D-24 |
| Integration | Qdrant tắt → E2 (TC28); KB không có tài liệu MFA → E3 (TC16) **[Chốt]** |
| Integration | Câu về "reset mật khẩu" gắn nhầm intent `access` → lần chạy lại tìm thấy tài liệu account, `intent_filter_fallback=true` (D-23) |
| Ablation nhỏ | Câu có "809": tắt nhánh bm25 thì tài liệu đúng rời top-5, bật thì vào top-5 |
| Probe | Recall@5 ≥ 0,8 trên 30 câu **[Chốt cổng 5]** |
| Probe (D-22) | Trên ≥ 20 câu không có đáp án: tỉ lệ trả lời bừa ≤ 5% tại ngưỡng đã chọn; báo cáo kèm tỉ lệ E3 oan |
| Hiệu năng | Rerank 20 đoạn p95 < 2 giây trên CPU **[Chốt 14.2]** |

### 11.1. Ablation RAG — số liệu cho Obj 1 [Đề xuất D-25]

Chạy trên bộ kiểm tra truy hồi mở rộng (KB có tài liệu gây nhiễu), cùng một `kb_version`:

| Cấu hình | Mô tả |
|---|---|
| A. Dense | Chỉ bge-m3, top-5 theo cosine |
| B. BM25 | Chỉ sparse |
| C. Hybrid | Dense + BM25, RRF, không rerank |
| D. Hybrid + rerank (mặc định) | Như hệ thống chạy thật |

Chỉ số: Recall@5, MRR, nDCG@5, tỉ lệ trả lời bừa trên câu âm tính, p95 độ trễ. Thêm một dòng "D nhưng tắt chuẩn hóa viết tắt" để đo giá trị của từ điển viết tắt. Đây là bằng chứng cho câu hỏi "vì sao cần Qdrant + BM25 + reranker": nếu D không hơn C rõ rệt thì báo cáo trung thực và cân nhắc bỏ rerank để giảm độ trễ.

## 12. Phụ thuộc, phase, việc còn mở

- **Phụ thuộc:** P4 (ml-service, tokenizer bge-m3); P5 (`call_with_retry`); P6 (role → sensitivity); nội dung KB (cổng K1, K2).
- **Phase:** 3 (VPN, chunk theo token, chọn ngưỡng có câu âm tính), 5 (đủ 4 loại), 8 (groundedness offline, ablation RAG).
- **Việc còn mở:**
  - Chọn `pyvi` hay `underthesea` bằng đo tốc độ + Recall@5.
  - Quy tắc `allowed_sensitivity` cần Trưởng BP xác nhận.
  - Đo hệ số token/âm tiết thật trên KB của nhóm; nếu thấp hơn dự kiến, có thể nâng `CHUNK_TOKENS_MAX`.
  - D-25 làm tăng khối lượng soạn KB (≥ 50 tài liệu) — cần nhóm cân đối với luồng soạn kịch bản.

## 13. Nhật ký thay đổi của file

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0 | Tạo file |
| 25/09/2026 | 1.1 | Nạp ngữ cảnh chung CTX-1.0 |
| 25/09/2026 | 1.2 | Bản vá lõi AI: chunk theo token (D-21); chọn ngưỡng có câu âm tính (D-22); chạy lại không lọc intent (D-23); ghép chunk liền kề cho B10 (D-24); KB có tài liệu gây nhiễu + ablation 4 cấu hình (D-25); từ điển viết tắt |
