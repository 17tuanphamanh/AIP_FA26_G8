# B8 — Recall@5 cổng ingest tại giờ cắt 22/10/2026 23:59 (giờ VN)

> **Đây là số TÁI LẬP ngày 23–24/10/2026 trên commit `bc7eaae`, KHÔNG phải log gốc của lần chạy verify ngày 22/10.**
> Máy chạy lại không có `.verify/run-*.log` của ngày 22/10; CI (`.github/workflows/ci.yml`) không chạy `scripts/verify.sh`.

## Kết quả

| Chỉ số (bộ `kb/eval/retrieval_set.yaml`) | Giá trị |
|---|---|
| **Recall@5 (hit@5, như cổng — `gate.metrics`)** | **1.000 = 34/34 câu có đáp án** |
| Recall@5 trung bình tỉ lệ (`app.eval.metrics.recall_at_k`) | 1.000 (mọi câu chỉ có 1 tài liệu đúng → bằng hit@5) |
| MRR@5 | 0.882 (26 câu đúng ở hạng 1, 8 câu ở hạng 2) |
| Tỉ lệ trả lời bừa (22 câu âm tính, ngưỡng `RETRIEVAL_THRESHOLD` theo cấu hình hiện hành trong `config/policy.json`) | 0.000 |
| **So với ngưỡng 0,8** (`huong-dan-xay-dung-he-thong-2.md:315`, `GATE_MIN_RECALL`) | **ĐẠT** |
| Số câu trượt | **0** |

Dòng cổng (nguyên văn, `reports/b8_run.log` (lưu cục bộ, không đưa lên repo)):

```
cổng kiểm (nhánh c, retrieve): Recall@5 1.000, trả lời bừa 0.000, MRR 0.882; câu có đáp án 34, câu âm tính 22; bản đang chạy: Recall@5 1.000 (đổi +0.000), trả lời bừa 0.000 (đổi +0.000)
```

`SELECT recall_at5, eval_status, created_at FROM kb_versions ORDER BY created_at DESC LIMIT 1`:

```
 recall_at5 | eval_status |          created_at
------------+-------------+-------------------------------
          1 | evaluated   | 2026-10-23 17:16:45.139146+00     (= 24/10 00:16:45 giờ VN)
```

`created_at` là thời điểm tái lập, không phải 22/10 — DB là DB mới dựng cho lần chạy này.

### Câu trượt

Không có. Câu đúng ở **hạng 2** (vẫn trong top 5, kéo MRR xuống): P004, P007, P012, P018, P020, P029, P030, P032.
Top-5 từng câu (56 dòng JSON) nằm trong `reports/b8_run.log` (lưu cục bộ, không đưa lên repo), mục `[CHÍNH] per-item`.

### Tham khảo: KB trước 13:56 (tree `6cf1091`)

| KB | Nhánh cổng | Recall@5 | MRR | Trả lời bừa |
|---|---|---|---|---|
| `6cf1091` (trước PR #57) | b (lần đầu, so ngưỡng tuyệt đối) | 1.000 (34/34) | 0.848 | 0.000 |
| `bc7eaae` → kb/ = `2703720` (sau PR #57) | c (so với bản đang chạy) | 1.000 (34/34) | 0.882 | 0.000 |

Chạy chung code `bc7eaae`, chỉ thay thư mục KB. Bản 6cf1091 chỉ có dòng cổng (không chạy per-item — đã quá 15 phút cho phần tham khảo).

## Nguồn số liệu

- **Commit:** `bc7eaae` (Merge PR #61, 22/10 13:56) — commit cuối trên mainline `origin/dev-tuananh` trước 22/10 23:59 (+07).
  `kb/` tại commit này có tree `6317daf` = tree của `2703720` ("kb: sua noi dung 11 bai huong dan", merge vào
  `dev-tuananh` qua PR #57 lúc 22/10 13:56). `kb/eval/retrieval_set.yaml` giống nhau ở `6cf1091` và `2703720`.
- **KB version:** `8479e79f85c3…` (collection `kb_8479e79f…`, 18 tài liệu, 77 đoạn).
- **Lưu ý về log gốc:** `scripts/verify.sh` chỉ ingest `kb/` (bước 11) khi `G` có gate5; và khi KB không đổi so với
  alias đang chạy, ingest dừng ở "KB không đổi" mà không chạy cổng (`pipeline.py:187`). Vì vậy log gốc ngày 22/10 có
  thể **không có** dòng "cổng kiểm … Recall@5". Số gốc (nếu có) nằm ở `kb_versions.recall_at5` trên DB của máy đã chạy.
- **Bộ câu:** 56 câu = 34 có đáp án + 22 âm tính — **không phải 30** như "Recall@5 ≥ 0,8 trên 30 câu" của đặc tả. Recall@5
  tính trên 34 câu có đáp án như cổng. Chỗ lệch này chưa ghi vào `PROGRESS.md`.

## Cách chạy lại

Môi trường: Windows 11 + Docker Desktop 4.96.3 (WSL2, 12 CPU, ~8 GB RAM), ml-service **CPU** (`device="cpu"` ghim trong
`ml_service/app/loader.py`, torch CPU — không có chế độ GPU), `ML_THREADS=4`, model bge-m3 + bge-reranker-v2-m3 đúng
revision trong `ml_service/models.lock.json` (4,3 GB ở `models/`).

Phiên bản (ghi bổ sung 24/10/2026):
- **Python trong container:** 3.12.15 (`FROM python:3.12-slim` ở `backend/Dockerfile`, `ml_service/Dockerfile` @ `bc7eaae`).
  Kiểm trên image `servicedesk-backend:dev` / `servicedesk-ml:dev` do lần build `bc7eaae` tạo (backend `Created`
  2026-10-23T16:33:43Z) bằng `docker run --rm --entrypoint python <image> --version`.
- **Trên máy:** CPython 3.12.15 qua uv 0.13.1. Các lệnh dưới đây đều chạy trong container, không dùng Python của máy.
- Docker Compose v5.6.1.

Cách chạy: code **`bc7eaae`** ở worktree tách rời tạo với `core.autocrlf=false`. Docker Compose với `--env-file b8.env`, là file
env tạm sinh từ `.env.example`, không dùng `.env`. Lệnh chạy trong Git Bash với `MSYS_NO_PATHCONV=1`. Lần B8 không chạy script
Python phía máy nên không cần `PYTHONUTF8`. Nếu chạy script phía máy trên Windows (gate, `seed validate`…) thì phải đặt
`PYTHONUTF8=1`, xem `reports/b10_bien_ban.md`.

```bash
git -c core.autocrlf=false worktree add --detach <wt> bc7eaae      # autocrlf=true làm init-roles.sh CRLF → postgres exit 127
cp <wt>/.env.example b8.env  # + ML_SERVICE_TOKEN ngẫu nhiên ≥ 32 ký tự (mẫu để trống, compose bắt buộc). Không cần LLM key.
export MODELS_DIR=<repo>/models MSYS_NO_PATHCONV=1                  # Git Bash: tắt đổi đường dẫn /srv/...
C="docker compose --env-file b8.env"                                 # không có make trên Windows → lệnh tương đương Makefile
$C build --build-arg GIT_SHA=bc7eaae… backend && $C build ml-service
$C up -d --wait postgres qdrant
$C run --rm --no-deps backend alembic upgrade head
$C up -d --wait --wait-timeout 600 ml-service
$C run --rm --no-deps -v <wt>/kb:/srv/kb:ro backend python -m app.rag.ingest.cli --kb-dir /srv/kb      # = make ingest KB_DIR=kb
$C run --rm --no-deps -e EVAL_MODE=true -v <wt>/kb:/srv/kb:ro -v <repo>/reports:/srv/b8:ro backend \
    python /srv/b8/b8_per_item.py --kb-dir /srv/kb                    # top-5 từng câu (b8_per_item.py (lưu cục bộ, không đưa lên repo))
$C down                                                               # giữ volume
```

Lần tái lập thực tế nạp `6cf1091` trước rồi mới nạp `bc7eaae` (thứ tự thời gian, version tài liệu tăng dần) nên cổng
lần chính chạy nhánh c. Recall@5 của bản mới đo trên collection của chính nó, không phụ thuộc thứ tự.

`EVAL_MODE=true` chỉ để mở chốt import `app.eval` (dùng `recall_at_k`); trong backend biến này chỉ tác động graph/LLM
(B12, M5), không đụng retriever. Thời gian: ingest chính 24 phút (cổng nhánh c đánh giá cả bản cũ lẫn mới trên CPU),
per-item 12 phút.

## Kiểm tay

| Câu | Loại | YAML `expected_doc_ids` | Top-5 trong log | Khớp |
|---|---|---|---|---|
| P001 "vpn mở port mấy" | trúng hạng 1 | KB-VPN-001 | **KB-VPN-001**, VPN-003, VPN-002, VPN-004, VPN-005 | ✓ |
| P029 "xin quyền folder ai duyệt" | trúng hạng 2 (không có câu trượt) | KB-ACS-002 | ACS-001, **KB-ACS-002**, ACS-003, ACS-004, ACS-005 | ✓ |
| P018 (ngẫu nhiên) "loi mat khau muon nho IT…" | trúng hạng 2 | KB-ACC-004 | ACC-001, **KB-ACC-004**, ACC-002, ACC-003 | ✓ |

Tính lại độc lập từ 34 dòng JSON: hạng 1 = 26, hạng 2 = 8 → MRR 0,8824, khớp dòng cổng 0.882.

## File

- `reports/b8_run.log` (lưu cục bộ, không đưa lên repo) — toàn bộ output (gồm 2 lần thử hỏng đầu: đường dẫn Git Bash, thiếu env file — không ghi gì).
- `reports/b8_per_item.py` (lưu cục bộ, không đưa lên repo) — script top-5 từng câu (dùng lại `eval_cli._build_deps`, `RetrieveGateAdapter`,
  `gate.metrics`, `recall_at_k`; chỉ đọc).
- `reports/b8_models_download.log` (lưu cục bộ, không đưa lên repo) — log tải model.
