Node của graph, một file mỗi nhánh (b01_identity.py … b20_audit.py). Xem docs/spec/build/01-kien-truc-project.md mục 3.

- Hầu hết các file ở đây (b01, b02, b03, b06, b10, b11, b12, b15, b17, b20, các node `*_wait`) đã là bản THẬT
  từ các phase trước — "giả" chỉ còn ở NHỮNG CHỖ chưa tới phase (vd `b03_classify`/`b06_diagnose` hiện còn
  Phase 2a: cố định `intent="vpn"`, không đọc câu — sẽ thay ở Phase 5).
- `b08_retrieve.py`: node THẬT (Phase 3 chặng 3c) — gọi `deps.rag.retrieve()` (`RagPort`, thật là
  `rag.retriever.Retriever`), chỉ bắt `RetrievalSystemError` (E2); rỗng/dưới ngưỡng → E3 (B9). Bản GIẢ (Phase
  2, đọc `deps.scenario`) nằm ở `graph/nodes/fake/b08_retrieve.py`. `graph/builder.py::select_nodes` (qua
  `FAKE_SCENARIO`) hoặc `real_nodes`/`fake_nodes` chọn bản nào chạy — xem `graph/wiring.py`.
