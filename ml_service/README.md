P4 — ml-service, cổng 8200 (chỉ mạng nội bộ compose). Thiết kế Phase 3: docs/spec/build/phase3-thiet-ke-chi-tiet.md mục 4.

- Endpoint: `/embed` (bge-m3), `/rerank` (bge-reranker-v2-m3), `/count_tokens`, `/health`; `/classify`,
  `/classify_intent` trả 503 `model_missing` tới Phase 5. Mọi endpoint trừ `/health` cần `X-Service-Token`
  (`ML_SERVICE_TOKEN`, bắt buộc); body > 256 KB → 413.
- Model: `make models` tải về `./models/<repo>@<sha>` (ghim ở `models.lock.json` — commit file này), compose
  mount read-only; image chạy offline (`HF_HUB_OFFLINE=1`).
- Test: `make test` (loader giả, không torch) · `make test-ml` (model thật, cần `make models`) · đo: `make ml-bench`.
- Package `app` trùng tên với backend → pytest/mypy chạy riêng (`-o pythonpath=ml_service`).
