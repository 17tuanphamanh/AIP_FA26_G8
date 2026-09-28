P3 — ingest, truy hồi (retriever), ghép chunk liền kề. Xem docs/spec/build/01-kien-truc-project.md mục 3 và
docs/spec/build/phase3-thiet-ke-chi-tiet.md mục 5 (ingest) + mục 6 (truy hồi).

- `ingest/` (3b) — 14 bước `make ingest`: `loader.py`/`frontmatter.py` (đọc + kiểm KB), `chunker.py` (chia
  đoạn theo mục/token), `kbversion.py` (`kb_version`, `content_sha256`, `pipeline_sha`), `facts_check.py`
  (kb-facts), `gate.py` (cổng kiểm Recall@5/FG/MRR — 3c dùng `Retriever` thật qua `RetrieveGateAdapter`, không
  còn dense-only; `sweep()` cho `eval_cli --sweep`), `pipeline.py` (`run_ingest`), `cli.py` (`make ingest`).
- Truy hồi (3c, node `graph/nodes/b08_retrieve.py`): `filters.py` (DUY NHẤT gọi `Filter(` trong `rag/**` —
  `base_filter`/`query_filter`/`intent_filter`, kiểm bằng AST c36); `query.py` (`build_query`); `models.py`
  (`RetrievalQuery`/`RetrievalResult`/`RetrievalSystemError`/`EvidenceBlock`); `vector_store.py`
  (`VectorIndex` Protocol + `QdrantIndex`: `hybrid_query` RRF, `scroll_window`, phân lớp lỗi Qdrant
  `VectorStoreTransient`/`CollectionNotFound`); `retriever.py` (`Retriever`, `RagConfig` — embed một lần/lượt,
  D-23 lọc intent rồi thử lại không intent, retry qua `tools.retry.call_with_retry`); `expand.py`
  (`expand_for_answer`/`trim_to_budget` — ghép láng giềng D-24, CÙNG collection với lượt truy hồi, không đọc
  lại alias); `ports.py` (`RagPort` Protocol — bản thật `Retriever`, bản giả `tests/fakes/rag.FakeRag`);
  `eval_cli.py` (`make eval-rag` — đo Recall/FG/MRR trên bản KB đang chạy, `--sweep` chỉ để quan sát, không
  chọn ngưỡng — D-22).
- Test: unit (`backend/tests/unit/test_rag_*.py`, không cần Docker) · integration Qdrant/Postgres thật
  (`backend/tests/integration/test_rag_query_qdrant.py`, `test_b08_pg.py`, `test_rag_ingest_pg.py` — cần
  `make up`/testcontainers, người chạy) · mutation (`scripts/mutation/mutate_3b.py`, `mutate_3c.py`).
