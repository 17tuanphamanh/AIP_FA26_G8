Prompt của từng nhánh (b02_injection_judge.yaml, b03_classify.yaml, …) — sửa là đổi hành vi agent. Xem docs/spec/build/01-kien-truc-project.md mục 3.

Mỗi file là nguồn DUY NHẤT của prompt đó (PLAN-3d Q-3d-5; nạp bởi `backend/app/llm/registry.py`, sai → backend/worker
không khởi động):

- `id` trùng tên file; `version` — **tăng mỗi lần sửa nội dung** (khoá cache và `llm_calls.prompt_version` dựa vào nó;
  `prompt_hash` = sha256 cả file).
- `role` (`fast`/`strong`), `schema` (tên lớp trong `backend/app/llm/schemas.py`), `cache` (`default`/`bypass`): node
  truyền lệch → `PromptContractError` (E9).
- `allowed_vars` — whitelist biến; tập `{{ biến }}` trong `system` + `user` phải BẰNG đúng danh sách này. Không đưa
  `redacted_request`/`conversation` vào prompt của B14 (P2 mục 7 [Chốt 6.2]; test d1b).
- `random_boundary: true` (chỉ `b02_injection_judge`) — renderer sinh `{{ boundary }}` ngẫu nhiên mỗi lần (`secrets`),
  văn bản người dùng không đoán trước được dấu đóng khối.
- Renderer thay `{{ biến }}` MỘT lượt: giá trị chứa `{{ … }}` được giữ nguyên chữ. Không có Jinja, không điều kiện/vòng lặp.

Sửa xong: `uv run pytest backend/tests/unit -q -k llm` (d10 kiểm đủ 6 file, biến, schema). Chất lượng câu trả lời chỉ
đo được với LLM thật ở mốc G (PROGRESS "Dồn về mốc G"). Phản hồi giả cho stack dev (`LLM_BACKEND=scripted`) ở
`config/scripted/*.yaml` — phải hợp lệ với schema của prompt (kiểm lúc khởi động).
