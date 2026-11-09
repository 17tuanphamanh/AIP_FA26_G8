P2 — LLM gateway. Xem docs/spec/build/01-kien-truc-project.md mục 3 và docs/spec/build/phase3-thiet-ke-chi-tiet.md
mục 7 (3d). Khi lệch spec: `PROGRESS.md` mục "Phase 3 — chặng 3d" (chốt Q-3d + "Spec cần sửa").

- Cổng DUY NHẤT: `client.py` (`LLMClient.complete(role, prompt_id, variables, schema, …) → (obj, LLMMeta)`) — node chỉ
  thấy `ports.LlmPort` qua `NodeDeps.llm`, bắt 3 lỗi `LLMUnavailable`/`LLMSchemaError`/`LLMBudgetExceeded`
  (`core/errors.py`). Luồng 7 bước ở docstring `client.py`: hợp đồng prompt → render + whitelist + cắt `budget_in` →
  chuỗi đích (strong KHÔNG fallback) → thiếu pricing: 0 request → cache → trần chi + giữ chỗ → retry trong
  `deadline_s` → sửa schema 1 lần → span `llm:<id>` + `llm_calls` (một transaction).
- `config.py` — `config/llm.yaml` (không nội suy `${…}`): model hai vai trò, `base_url`, khoá đọc từ env qua TÊN
  trường `Settings`; `resolve` từ chối khởi động khi `real` thiếu model/giá/URL/khoá; `check_timing` (công thức
  Q-3a-16 < `WORKER_STALE_TURN_SECONDS/2`). `wiring.py` — `check_llm` (trước mọi kết nối) + `open_llm`.
- Vai chat (Q10): ngoài `fast`/`strong`, `config/llm.yaml` có `chat_fast`/`chat_strong` (model từ `CHAT_MODEL`; TRỐNG = dùng đích của
  fast/strong) và bảng `prompt_roles` (prompt id → vai THỰC SỰ dùng: model, `budget_in`, timeout, khoá cache). 5 prompt hội thoại
  (b03, b10_need_type, b10_answer, b11_*) đi vai chat; b02_injection_judge và b14_* bị cấm khỏi bảng (validator từ chối khởi động —
  model đã đo trong báo cáo). File prompt giữ nguyên `role`; `RuntimeLlm.role_of(prompt)` là chỗ duy nhất đổi prompt → vai.
- `registry.py` (prompt YAML: id = tên file, biến template == `allowed_vars`, `sha256`), `context.py` (render MỘT lượt
  — giá trị không bị render lại; `random_boundary` từ `secrets`; ước lượng token `ceil(ký tự/3)`; vượt `budget_in` → cắt
  bằng chứng, tin nhắn, rồi đuôi biến `trim_vars` của prompt — Q11: `user_request` của `b11_clarify_question` — ở ranh giới từ), `schemas.py`
  (6 schema `extra="forbid"`), `cache.py` (khoá 11 thành phần gồm `mode`), `spend.py` (trần chi: đọc SUM mỗi 60 s,
  cộng dồn, giữ chỗ từng request trả phí), `store.py` (`SqlLlmStore`: `llm_cache`, `spans` + `llm_calls`, tổng chi).
- `providers/`: `openai_compat.py` (SDK `openai`, `max_retries=0`, lỗi → `ProviderError` chỉ có loại + host; logger
  `httpx2` nâng WARNING vì in cả URL), `scripted.py` (`ScriptedLLM` cho test; `PresetScriptedLLM` cho stack dev,
  chỉ nạp khi `LLM_BACKEND=scripted` và `APP_ENV` ∈ {dev, test}).
- Không lưu văn bản prompt: `llm_calls` chỉ có `prompt_hash`; `prompt_full` chỉ khi `EVAL_MODE=true` (bị từ chối ở
  `APP_ENV` prod/thiếu). Không log khoá, `base_url`, prompt, đầu ra model.
- Test: unit (`backend/tests/unit/test_llm_*.py`, `test_graph_trace_parent.py` — không cần Docker, không cần khoá; test
  chạm mạng thật của `httpx2` → `NetworkBlocked`) · integration Postgres thật (`backend/tests/integration/
  test_llm_store_pg.py` — người chạy) · mutation (`scripts/mutation/mutate_3d.py`).
