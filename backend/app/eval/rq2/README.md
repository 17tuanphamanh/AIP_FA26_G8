# RQ2 — cách lấy p nào hiệu chỉnh tốt nhất (Phase 11)

Package này chỉ import được khi `EVAL_MODE=true`. Chặn thừa hưởng từ `app/eval/__init__.py`, có test subprocess ở `test_rq2_guard.py`.
Code nằm ở `backend/app/eval/rq2/`, `scripts/eval/rq2_collect.py`, `scripts/eval/rq2_report.py`. Không sửa file nào có trong tag v1.0-freeze.

Ba cách lấy p, cùng nghĩa với p của M5 (xác suất "cần người duyệt"). Bản đo dùng `m5.p_method = sampling_k5`.

| Cách | Prompt | Temperature | Lấy p | Gọi LLM |
|---|---|---|---|---|
| (a) tự nói con số | `b14_risk_estimate` | 0 | `prob_needs_human` | **gọi thêm** 1 lần/lá qua gateway (`LlmRiskEstimator._self_report`), `LLM_CACHE_MODE=eval` |
| (b) hỏi 5 lần | `b14_risk_vote` | 0,7 | số phiếu `needs_human=true` / 5 (6 mức: 0; 0,2; …; 1) | **không**: đọc lại phiếu của S1 |
| (c) xác suất token | `b14_risk_vote` (messages nguyên của phiếu `sample_idx=0`) | 0 | P(`true`) chuẩn hoá trên {true, false} của `top_logprobs` tại token giá trị `needs_human` | 1 lần/lá, đường httpx riêng, cờ `--include-c` |

## Model của B14

- Vai `strong` lấy tên model từ `roles.strong.model_setting: strong_model` (`config/llm.yaml`), tức biến môi trường **`STRONG_MODEL`**.
  Giá trị nằm trong `.env` của máy chạy, không có trong repo. Bảng `pricing` của tag có `deepseek-flash` và `deepseek-v4-pro`.
- Manifest ghi **đúng tên model đã chạy S1**, lấy từ `llm_calls.model` của các dòng phiếu (`model`, `s1_models`), và tên model đang cấu
  hình (`configured_model`). Lá có model phiếu khác model đang cấu hình thì không gọi (a)/(c) (lý do `model_mismatch`).
- Quân tra trước khi chạy:
  - xem tên đặt trong `.env` bằng `grep '^STRONG_MODEL=' .env`;
  - xem model S1 thật sự dùng bằng câu `SELECT DISTINCT model FROM llm_calls WHERE prompt_id = 'b14_risk_vote'` trong psql của stack.

## (c) logprobs — tài liệu API và trạng thái khả thi

Gateway cấm `logprobs`/`top_logprobs` (`app/llm/config.py:43-47`, `EXTRA_BODY_FORBIDDEN`), nên (c) đi đường riêng `logprob.HttpxTransport`:
`POST <LLM_BASE_URL>/chat/completions`. Base URL, khoá và model lấy qua `Settings` bằng tên trường của `config/llm.yaml`, như gateway.
Khoá chỉ nằm ở header, không vào thân request, cache, log hay lỗi.

Tài liệu DeepSeek (https://api-docs.deepseek.com/api/create-chat-completion, đọc 30/10/2026), trích nguyên văn:

- `logprobs` (boolean): "Whether to return log probabilities of the output tokens or not. If true, returns the log probabilities of each
  output token returned in the `content` of `message`."
- `top_logprobs` (integer, `<= 20`): "An integer between 0 and 20 specifying the number of most likely tokens to return at each token
  position" … "`logprobs` must be set to `true` if this parameter is used."
- Phản hồi `choices[].logprobs.content[]`: `token`, `logprob` ("The log probability of this token, if it is within the top 20 most likely
  tokens. Otherwise, the value `-9999.0` is used …"), `top_logprobs` ("In rare cases, there may be fewer than the number of requested
  `top_logprobs` returned.").
- Tài liệu **không ghi model nào hỗ trợ hay không hỗ trợ** logprobs. Ở đây không tự kết luận.

**Chưa kiểm khả thi. Quân kiểm khi chạy D1 31/10.** Theo ĐP 30/10 không có lời gọi thử trước (phiếu đã huỷ).
- Hàm kiểm khả thi `logprob.check_logprobs_feasible` chạy trên phản hồi (c) của lá đầu tiên. Đạt khi `choices[0].logprobs.content` có dữ
  liệu, có `top_logprobs` và tìm được token quyết định.
- Không đạt thì manifest ghi `c.status = "infeasible"` kèm `c.feasibility.evidence` (chỉ số đếm, không nội dung). Không dòng nào có
  `p_c`, không có cột (c) trong CSV hay bảng, không suy p từ nguồn khác.
- Báo cáo tự chọn câu trạng thái (`report.c_feasibility_note`) theo `llm_calls.model` của S1:
  - `deepseek-flash` → "(c) khả thi: lời gọi thử 30/10 trả logprobs (file .verify/rq2/logprobs-thu-3010.txt ngoài repo, sha256
    9936e71c03906c841c9d33787b6fb0fe075f46402a3fb0fec243db833b317600)";
  - model khác → "đã thấy logprobs trên deepseek-flash, CHƯA kiểm trên model B14 (<tên>) — Quân kiểm bằng hàm kiểm khả thi khi chạy D1
    31/10".

**Token quyết định.** Prompt vote trả JSON `{"needs_human": true|false, "factors": [...]}`. Vị trí quyết định là token đầu tiên mà chữ
đứng trước nó đã có `"needs_human"` + `:` (+ khoảng trắng), và chính nó mở đầu `true` hoặc `false`. Ghi chú `:` dính vào token cũng nhận.
Mỗi lựa chọn trong `top_logprobs` (mặc định 5) được xếp loại bằng cách ghép vào cùng phần chữ trước nó:
p_c = Σexp(lp | true) / (Σexp(lp | true) + Σexp(lp | false)). Token cắt giữa chữ (vd "tr") không được tính.

**Lệch huong-dan:573.** Hướng dẫn mô tả (c) là "trả lời một token Có/Không". Ở đây dùng `true`/`false` của `needs_human` vì đó là đầu ra
của prompt vote có sẵn: không viết prompt mới, và messages đúng từng byte với S1. BE duyệt 30/10.

## Đầu vào B14 (đã kiểm trên tag)

- `llm_calls.prompt_full` = `json.dumps(rendered.messages)`, chỉ ghi khi `EVAL_MODE=true` (`app/llm/client.py:213-214`), và được ghi
  trước khi tra cache. Nối lá với dòng qua `llm_calls.span_id → spans.turn_id → turns.ticket_id`.
- S1 (`sampling_k5`) có 5 dòng `b14_risk_vote`/lá và không có dòng `b14_risk_estimate`.
- Template `user` của estimate là tiền tố đúng từng byte của template `user` của vote (vote thêm dòng `sample_idx`).
- `source.rebuild` dựng lại biến từ `prompt_full`:
  - `intended_action`, `risk_context` là một dòng JSON → `json.loads`;
  - `evidence` được tách theo đầu khối; `score` không được render nên đặt bằng nhau, giữ đúng thứ tự cắt.
- **Kiểm byte:** render lại `b14_risk_vote` với từng `sample_idx` phải bằng `prompt_full`, và `spans.attributes.trimmed_evidence = 0`.
  Lệch thì lá bị loại khỏi (a), đếm ở manifest `counts["a:<lý do>"]`.
- Manifest: `b14_input_method = "vote_prompt_full_reparse+rerender_check"`.

## Nguồn phiếu (b)

`llm_cache.response_json.needs_human` (mode `eval`, prompt `b14_risk_vote`). Khoá cache được tính lại bằng `app.llm.cache.cache_key` từ
messages của dòng phiếu, với `model_version` lấy từ **cấu hình** (`roles.strong.model_version`).
- p_b phải bằng `raw_prob` ở điểm log 4 của S1 (`predictions.jsonl`), lệch thì loại (`audit_mismatch`).
- Thiếu phiếu thì không có p_b (`vote_cache_missing`). Cờ `--allow-audit-pb` cho lấy `raw_prob` thay vào; khi đó `p_b_source` ghi
  `audit_raw_prob`.

## Hiệu chỉnh và nhãn

- Calibrator cùng loại với T37: Platt, `app.risk.calibrator.fit_platt` (calibrator RQ1 gọi ở `app/eval/calibrate.py:184-186`).
- Nhãn: `y = expected_route != "AUTO"` (`calibrate.py:184`, `risk/calibrator.py:53`, `eval/metrics.py:214`).
- Kiểm tra chéo 5 phần theo họ (`eval/folds.csv`, D-58): fit trên 4 phần, dự đoán phần còn lại, gộp lại.
  - Một họ nằm ở hơn 1 phần → `LeakageError`.
  - Phần mà `fit_platt` từ chối (dưới 10 mẫu, một lớp, a ≤ 0) → lá phần đó không có p hiệu chỉnh, không lấy p thô thay vào.

## Chỉ số

Tính cho 3 cách × trước/sau hiệu chỉnh, phạm vi `common` (cùng tập lá) và `own`.
- ECE 10 ngăn đều: `decision_math.ece`.
- ECE 5 ngăn cùng số mẫu: sắp theo (p, ticket_id), `array_split`.
- Brier.
- Số mức p, tỉ lệ dồn vào 2 mức đông nhất.
- KTC 95% bootstrap theo họ (`stats.family_bootstrap_ci`), **n_boot = 1000** (đặc tả Phase 11; P8 dùng 2000), seed 20260925.

**Reliability diagram:** repo không có matplotlib/pillow, mà thêm thì phải sửa `pyproject.toml` (file trong tag). Vì vậy PNG được vẽ bằng
zlib, không có chữ; bản `.svg` cùng tên có nhãn trục và số lá từng ngăn.

## Đầu ra `results/rq2/<run_id>/`

- `run_id` = sha256(label, run_id S1, sha `predictions.jsonl`, commit, cờ, sha 2 prompt)[:12].
- Thư mục gồm:
  - `manifest_collect.json`, `manifest.json`: model, temperature từng cách, seed, sha prompt, sha dữ liệu, run_id S1, cách dựng đầu vào
    B14, trạng thái (c), tổng chi;
  - `collected.jsonl`;
  - `per_ticket.csv`: thẻ, họ, fold, nhãn, `p_<cách>_raw|cal`;
  - `tables.md`, `metrics.json`, `reliability_*.png|svg`;
  - `cache_a/`, `cache_c/`, `llm_calls_a.jsonl`, `spend.jsonl`.
- Trần chi `--max-usd` (mặc định 2) tính (a) + (c) của run, **không cộng SUM(llm_calls) của PG**.
- D1, D2 và tập chính: mỗi tập một lượt S1, một `--label`, một thư mục run. Không gộp số.
- 25 giá trị self_report của B5 không có trong repo. Truyền `--b5-csv` cho `rq2_report.py` (chỉ mô tả độ phân giải (a)), không commit.

## Lệnh chạy (máy có stack S1 đang chạy; `.env` có `EVAL_MODE=true`, `LLM_CACHE_MODE=eval`, `LLM_BACKEND=real`, `APP_ENV=dev`)

```
# 0. chỉ (b), không gọi LLM — kiểm nguồn phiếu trước
EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/rq2_collect.py \
  --s1-predictions <thư mục lượt S1>/predictions.jsonl --label D1 --only-b
# 1. (a) + (b) + (c)
EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/rq2_collect.py \
  --s1-predictions <thư mục lượt S1>/predictions.jsonl --label D1 --include-c --max-usd 2
# 2. báo cáo (offline)
EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/rq2_report.py results/rq2/<run_id> \
  [--b5-csv <…>/gia-tri-a.csv,<…>/gia-tri-b.csv]
```

- `--only-b` và lượt đầy đủ ra 2 `run_id` khác nhau (cờ nằm trong định danh).
- Chạy lại cùng lệnh thì đọc cache trong thư mục run, 0 lời gọi mạng cho phần đã có.
- stdout chỉ in số đếm và `run_id`.
- Mã 2: thiếu `EVAL_MODE=true`, `APP_ENV` ngoài dev/test, `LLM_CACHE_MODE` ≠ eval, hoặc `LLM_BACKEND` ≠ real khi gọi (a)/(c).

## Test

- Unit (không mạng, không PG): `backend/tests/unit/eval/test_rq2_*.py`.
- PG (testcontainers, **chưa chạy**, chờ GIT xếp lượt): `backend/tests/integration/test_rq2_source_pg.py`.
