# RAG (M2) — hiện trạng, điểm yếu và việc cần làm sau Phase 2

*Ghi ngày 26/09/2026, trong lúc làm Phase 2b-2. Mục đích: **khi xong Phase 2**, mở file này và hoàn thiện phần RAG (soạn mẫu KB, bộ câu kiểm tra, kế hoạch Phase 3 cho RAG). Thiết kế gốc: `build/nen-tang/P3-rag-pipeline.md` (bản 1.2).*

---

## 1. Vai trò của RAG trong luồng

| Bước | Vai trò |
|---|---|
| B8 tra KB | Tìm 5 đoạn tài liệu liên quan nhất |
| B9 có căn cứ? | Điểm cao nhất < `RETRIEVAL_THRESHOLD` (0,6) → **E3** (không có tài liệu, cờ "cần bổ sung KB") |
| B10 trả lời | LLM trả lời **chỉ dựa trên** các đoạn tìm được, có trích dẫn |
| Qdrant / ml-service lỗi sau retry | **E2** (lỗi hệ thống) — không được nhầm với E3 (bất biến 6) |

## 2. Hiện trạng repo (kiểm trên máy 26/09/2026)

| Thành phần | Trạng thái |
|---|---|
| Qdrant `v1.19.1` trong docker-compose | ✅ Chạy, `/api/health` kiểm |
| Bảng `kb_versions`, `kb_documents` | ✅ Có trong migration 0001 |
| `backend/app/rag/`, `kb/`, `ml_service/app/` | ⬜ Chỉ có khung + README, chưa có code |
| ml-service trong docker-compose | ⬜ Chưa có (compose mới có `ML_SERVICE_URL`) |
| Nội dung KB | ⬜ Chưa có tài liệu nào |
| Bộ câu kiểm tra truy hồi | ⬜ Chưa có |

## 3. Thiết kế đã chốt (tóm tắt P3)

**Ingest (`make ingest`, offline):** front matter (Pydantic, đối chiếu `kb-facts.md`) → làm sạch NFC → chia đoạn theo H2/H3, đo bằng token bge-m3 (120–380 token nội dung, tổng ≤ 480 kèm tiền tố heading) → dense `bge-m3` 1024 chiều + sparse BM25 (`pyvi`, giữ mã lỗi, từ điển viết tắt) → collection `kb_<kb_version>` → kiểm Recall@5 và tỉ lệ trả lời bừa → đổi alias `kb_current` nguyên tử → snapshot.

**Query (B8):** `redacted_request` + intent + ≤ 3 slot → prefetch dense top-20 + BM25 top-20 (lọc `enabled`, `sensitivity` theo role, `request_type`) → RRF → rerank `bge-reranker-v2-m3` → top-5 bỏ trùng tài liệu → < ngưỡng thì chạy lại **một lần không lọc intent** (D-23, cờ `intent_filter_fallback`) → vẫn thấp → E3. B10 ghép chunk liền kề ±1 (D-24).

**Ablation (Obj 1, D-25):** Dense / BM25 / Hybrid / Hybrid+rerank (+ tắt viết tắt) — Recall@5, MRR, nDCG@5, tỉ lệ trả lời bừa, p95.

## 4. Điểm yếu và cách khắc phục [Suy luận]

| # | Điểm yếu | Mức | Khắc phục |
|---|---|---|---|
| 1 | Chưa có tài liệu KB (K1: 5 VPN trước Phase 3; K2: 16 trước Phase 5; mục tiêu ≥ 50, 30% gây nhiễu) | Cao nhất | Làm song song ngay: soạn 5 tài liệu VPN + `kb-facts.md` |
| 2 | Chưa có bộ kiểm tra truy hồi (30 câu có đáp án + ≥ 20 câu không có, ≥ 8 câu gần chủ đề) | Cao | Soạn cùng KB; dùng để chọn ngưỡng (D-22), **không** trộn với bộ kịch bản M8 |
| 3 | ml-service chưa có; 2 model ~2 GB mỗi cái | Trung bình | Phase 3 thêm service; model ngoài git (N5), cache volume |
| 4 | Rerank CPU có thể > 2 giây p95 (Mac) | Trung bình | Giảm 20 → 10 ứng viên; hoặc ml-service trên máy gaming có GPU |
| 5 | CI không tải model 2 GB | Trung bình | Unit dùng embedder giả; model thật chỉ ở probe/integration riêng |
| 6 | Chọn `pyvi` hay `underthesea`; viết tắt "mk", "ko" | Thấp | Đo Recall@5 + tốc độ ở Phase 3; `config/vi_abbrev.yaml` |
| 7 | KB nhỏ → ablation vô nghĩa | Ảnh hưởng điểm Obj 1 | Tài liệu gây nhiễu 30% (D-25) |

## 5. Việc cần làm khi xong Phase 2 (Claude hoàn thiện cho nhóm)

1. Soạn **mẫu tài liệu KB VPN** (đủ front matter, cấu trúc H2/H3, ví dụ lỗi 809) + **mẫu `kb-facts.md`**.
2. Soạn **mẫu bộ câu kiểm tra truy hồi** (định dạng file, 5 câu có đáp án + 5 câu âm tính gần chủ đề làm ví dụ) và hướng dẫn soạn tiếp.
3. Viết **hướng dẫn giao việc** cho thành viên soạn KB (checklist, cách tự kiểm front matter).
4. Lập **kế hoạch Phase 3 phần RAG** cho coding agent: ml-service (`/embed`, `/rerank`, `/count_tokens`), `make ingest`, `retrieve()`, B8–B9, chọn ngưỡng, test theo P3 mục 11.
5. Chốt các việc còn mở của P3: `pyvi`/`underthesea`, `allowed_sensitivity`, hệ số token/âm tiết thật.

## 6. Lộ trình

| Khi nào | Việc | Ai |
|---|---|---|
| Song song từ bây giờ | 5 tài liệu VPN, `kb-facts.md`, 30 + 20 câu kiểm tra | Thành viên không code |
| Phase 3 | ml-service, ingest, `retrieve()`, B8–B9, chọn ngưỡng | Agent + Tuấn Anh |
| Phase 5 | 16 tài liệu cho 4 loại | Nhóm |
| Phase 8 | Ablation 4 cấu hình, KB ≥ 50 tài liệu | Nhóm |
