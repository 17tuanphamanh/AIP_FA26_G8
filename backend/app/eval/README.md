M8 — chỉ bật khi EVAL_MODE=true, P8. Xem docs/spec/build/01-kien-truc-project.md mục 3.

## Harness G2 — chạy kịch bản trên stack (RQ1)

| File | Việc |
|---|---|
| `dataset.py` | nạp kịch bản `*.yaml`/`*.yml` theo cấu trúc thật (dưới đây), `dataset_sha256`; lỗi chỉ nêu `file #i/N` + vị trí trường |
| `config.py` | `RunConfig`, `run_id = sha256(config \| dataset_sha256 \| commit)[:12]` (P8 §5.1) |
| `stack.py` | lái stack compose (chép tối thiểu từ `tests/stack/gate2.py`): chốt an toàn, SQL chỉ đọc, hạn kịch bản |
| `actors.py` | `ScriptedUser` (trả lời theo `turns`), `SimApprover` (làm theo `gold.approver_decision`) |
| `collect.py` | DB → `PredictionRecord` (hợp đồng v1.1, `predictions.py`) |
| `warmup.py` | làm nóng rerank, chạy TRONG container backend |
| `runner.py` | CLI, vòng tuần tự, `predictions.jsonl` + `outcomes.jsonl` + `manifest.json` |

### Cấu trúc kịch bản (dữ liệu thật — Tuấn Anh 19/10)

Mọi khoá dưới đây đều bắt buộc. Khoá lạ bị từ chối (trừ khi có `--allow-extra-fields`). Không có `gold.hidden_factor` (P8 v1.4 §4.1):
hợp đồng v1.1 để sẵn trường `hidden_factor` trong bản ghi nhưng ghi `null` cho tới khi chốt nguồn (V11-Q1).

| Khoá | Kiểu | Harness dùng |
|---|---|---|
| `id`, `family`, `source`, `at` | chuỗi | `id`, `family` vào bản ghi; `source` chỉ nạp; `at` chỉ nạp (khung giờ là việc G7) |
| `faults` | danh sách | chỉ nạp |
| `requester` | `{user_id, role, dept, tenure_days}` | `user_id` → `username` tra `mock_services/seed.json` (cờ `--seed`); không có trong seed → lỗi nạp |
| `turns` | `[0]` chuỗi; sau đó `{on_question_about, reply}` hoặc `{on_confirm}` | câu đầu tạo ticket; `reply` gửi THEO THỨ TỰ mỗi lần hệ thống hỏi lại (slot đang hỏi không lộ qua API — G2-Q19); `on_confirm` theo thứ tự ở bước xác nhận, hết thì coi là "Đã ổn" và đếm `confirm_default` |
| `gold` | `{intents, need_type, expected_route, expected_exit, approver_decision, gold_doc_ids, action{type, target, requested_for, params}, facts}` | `expected_route = null` → chưa nhãn: bản ghi vẫn ghi, đếm `unlabeled`; `approver_decision` cho người duyệt giả. Ngoại lệ (#58): `action.requested_for` vắng → người gửi (`requester.user_id`, D-41); `action.params` vắng → `{}`; `approver_decision` bắt buộc có khoá nhưng nhận `null` (không có bước duyệt) — nếu stack vẫn đòi duyệt thì ca ra `error` / `NoApproverDecision` (không tự chọn quyết định), bản ghi vẫn ghi kèm route, đếm `approval_no_decision` |
| `labels` | `{annotator_1, annotator_2}` | chỉ nạp |

Ghép nhãn sau 25/10 cho các lượt đã chạy với `expected_route = null`: chưa làm (G2-Q23).

Harness không gọi `/api/policy` hay endpoint chính sách nào. Đọc DB chỉ qua `SELECT` trong transaction chỉ đọc. Ở `audit_logs`
chỉ đọc `detail->>'route'` và `detail->>'strategy'` (dòng `B13/B14`), cùng `detail->>'turn'` (dòng `B11`).

**Đã kiểm ở đâu:**
- Unit test: `backend/tests/unit/eval/test_harness_*.py`, chạy trên stack giả.
- Đột biến: `scripts/mutation/mutate_g2.py` (37 đột biến) và `scripts/mutation/mutate_v11.py` (hợp đồng v1.1, 11 đột biến).
- Smoke trên stack thật (gói luật giả): `backend/tests/stack/eval_smoke.py` gồm hai ca tới điểm log 4, một ca chờ duyệt rồi được
  SimApprover duyệt, và một lượt phụ hết giờ.
- Việc đọc `detail.turn` ở B11 (`clarification_turns`) chỉ được kiểm bằng unit test và đột biến M-G2-4/5/13. Trên stack gói luật giả
  (b582058), preset `gia_hoi_lai` đi `B11:output_guard_block` rồi ra E3: câu hỏi lại bị output guard chặn, nên không có ca hỏi lại nào
  chạy được trên stack.

### Giao cho Duy Anh (bản 20/10)

**Nhánh:** `g2-harness-duong` (tách từ b582058, chỉ thêm file). Checkout nhánh này để chạy G16, không cần chờ gộp.

**Dựng stack:**
- Chạy `make up` để build lại image backend, vì `app.eval.warmup` chạy trong container.
- `.env` của máy chạy phải có `EVAL_MODE=true`, `LLM_CACHE_MODE=eval`, `STRATEGY=hybrid`, `APPROVAL_SLA_MINUTES_DEV=2`.
- Thiếu `EVAL_MODE=true` thì điểm log 4 không có `detail.strategy`, harness dừng mã 2.
- `APPROVAL_SLA_MINUTES_DEV=2` (G2-Q6, Tuấn Anh 19/10): ca `ignore` hết hạn duyệt sau 2 phút và ra E6, trước khi chạm `--timeout-s`.
  Container không đặt biến này, hoặc để rỗng, thì harness dừng mã 2 trước khi tạo ticket nào. Giá trị được ghi vào `manifest.json`
  mục `approval_sla_minutes_dev`.

**Trước khi giao:** Tuấn Anh chạy `--check-only` trên dữ liệu thật. Lệnh này chỉ nạp kịch bản, không gọi stack, không cần
`EVAL_PASSWORD`, và chỉ in `scenarios: loaded=<n> errors=<n>` cùng các dòng lỗi dạng `file #i/N: <vị trí trường>`:

```
cd ~/code/AIP_FA26_G8
EVAL_MODE=true PYTHONPATH=backend uv run python -m app.eval.runner --scenarios <thư mục kịch bản> --check-only
```

Nếu có trường lạ ngoài cấu trúc thật, thêm `--allow-extra-fields` để bỏ qua chúng. Số trường bị bỏ qua được in thành dòng
`ignored_fields=<n>`; đường dẫn các trường (không có giá trị) ghi ở `manifest.json` mục `ignored_fields`.

**Lệnh chạy S1 hybrid** (máy Duy Anh chỉ chạy S1, không chạy S2):

```
cd ~/code/AIP_FA26_G8
git checkout g2-harness-duong
EVAL_MODE=true EVAL_PASSWORD='<mật khẩu demo>' PYTHONPATH=backend uv run python -m app.eval.runner \
  --scenarios <thư mục kịch bản> --strategy hybrid --split test --timeout-s 300 \
  --out <thư mục NGOÀI repo, vd ~/eval-runs/s1>
```

- `--timeout-s` là giới hạn cho MỖI kịch bản. Tham số bắt buộc, code không có mặc định. **300 giây là số tạm**, sẽ chốt lại khi có
  probe B5 (Tuấn Anh 19/10). Số này chỉ truyền qua CLI, không nằm trong code.
- Nếu `--timeout-s` nhỏ hơn SLA duyệt + 60 giây, harness in cảnh báo ra stderr và các ca `ignore` sẽ ra `timeout` thay vì E6.
  Với SLA 2 phút, ngưỡng là 180 giây, nên 300 không bị cảnh báo.
- `--out` không được nằm trong thư mục kịch bản và không được chứa sẵn file kết quả của lượt trước.
- Sai mật khẩu thì harness dừng với dòng `DỪNG: EVAL_PASSWORD sai (đăng nhập 401)` và mã 2, chưa tạo ticket nào. Trước khi chạy,
  harness thử đăng nhập một lần bằng người gửi của kịch bản đầu. Nếu lỗi mạng hoặc mã HTTP khác 401, dòng `DỪNG:` nêu lý do khác.
  Trong `outcomes.jsonl`, ca lỗi do API có thêm trường `error_http` (mã HTTP).
- Cờ tuỳ chọn:
  - `--per-case`: in thêm mỗi ca một dòng `<scenario_id> <kết cục> <giây>`.
  - `--warmup-rounds N`: số vòng làm nóng, mặc định 3.
  - `--prob-method`: mặc định `self_report`.
  - `--run-id`: chỉ để đối chiếu.
- Biến `COMPOSE` (mặc định `docker compose`) giống gate2.

**Đọc đầu ra.** Mặc định stdout có đúng 7 dòng tổng hợp (thêm `ignored_fields=<n>` khi có `--allow-extra-fields`):

```
eval run <run_id> strategy=hybrid split=test timeout_s=<n>
scenarios: loaded=<n>
warmup: rounds=<n> first_ms=<n> last_ms=<n>
outcomes: done=<n> timeout=<n> multi_leaf=<n> error=<n>
records: written=<n> route_none=<n> calibrated_prob_nonnull=<n> unlabeled=<n>
elapsed_s=<n>
files: predictions.jsonl outcomes.jsonl manifest.json
```

Harness không in câu, id kịch bản, họ, gold, ticket_id, route từng ca, detail, SQL hay thông điệp lỗi. Cảnh báo đi ra stderr.

**Mã thoát:**

| Mã | Nghĩa |
|---|---|
| 0 | Xong |
| 1 | Có ca `timeout` hoặc `error`; file vẫn được ghi |
| 2 | Dừng trước khi ghi `predictions.jsonl`. Dòng cuối `DỪNG: <lý do>` cho biết nguyên nhân: tham số, kịch bản lỗi, chốt an toàn, seed không đọc được, STRATEGY / EVAL_MODE / LLM_CACHE_MODE / APPROVAL_SLA_MINUTES_DEV / APP_GIT_SHA của container, `/api/health`, làm nóng, hoặc điểm log 4 thiếu khoá / sai strategy |

**File trong `--out`:**
- `predictions.jsonl`: hợp đồng v1.1 (P8 v1.4 §5.6, `schema_version` = `"1.1"`), đọc bằng `app.eval.predictions.load_predictions`.
  Mỗi dòng là một lá; ca `multi_leaf` không có dòng ở đây. Ca hết giờ vẫn có bản ghi, với `final_state` = `null`. Kịch bản chưa nhãn
  có bản ghi với `expected_route` = `null` (đếm ở `unlabeled`).
  - `run_started_at`: giờ bắt đầu của từng kịch bản (ISO 8601 có offset), cùng giá trị với `outcomes.jsonl`. Giờ bắt đầu cả lượt nằm
    ở `manifest.started_at`.
  - `fold`, `kb_gap`, `hidden_factor`, `in_business_hours`: luôn `null` ở lượt stack, vì chưa có nguồn hợp lệ. Tên bốn trường này
    được liệt kê ở `manifest.predictions_unavailable`. Lý do từng trường:
    - `fold`: gán phần ở bước offline, từ `SPLIT.md` (V11-Q3).
    - `kb_gap`: không có cột riêng; muốn có phải đọc một khoá `detail` mới, chưa được duyệt (V11-Q2).
    - `hidden_factor`: dữ liệu kịch bản chưa có khoá này (V11-Q1).
    - `in_business_hours`: chờ G7 (V11-Q5).
  - File v1 (không có `schema_version`) bị `load_predictions` từ chối với lỗi `bản v1`. Muốn có file v1.1 thì chạy lại harness.
- `outcomes.jsonl`: kết cục từng ca (`done` / `timeout` / `multi_leaf` / `error`), tên lớp lỗi, số giây, giờ bắt đầu.
- `manifest.json`: cấu hình, `run_id`, commit, `dataset_sha256`, `policy_sha256`, `clf_mode`, làm nóng, số đếm (gồm `unlabeled`,
  `confirm_default`), `ignored_fields`, `schema_version`, `predictions_unavailable`.
  Các khoá của 21/10 (`b2_tau`, `b2_judge_model`, SHA hai model, `rate_limits`) để `null` và liệt kê trong `unavailable`.
  Không có manifest thì không đưa số vào báo cáo (P8 §5.1).

## Groundedness offline (G11) — `groundedness/`

Tách câu trả lời B10 thành từng ý (bằng code) → LLM chấm mỗi ý có được đoạn trích **đã dẫn** hỗ trợ không (`config/prompts/eval_groundedness.yaml`, vai trò strong, một lời gọi/ca) → tỉ lệ ý được hỗ trợ + citation precision → mẫu 30 ca cho người soát + độ đồng thuận LLM–người. Nguồn: `huong-dan` 17.4, B10 mục 9/11, P2 mục 6, P8 v1.5 mục 6.3.1.

**Nhãn.** Yêu cầu đo — offline, tách ý, LLM chấm, người soát 30 mẫu, báo tỉ lệ ý được hỗ trợ + citation precision — là **[Chốt 17.4]**. Cách đo (mọi định nghĩa và quy ước dưới đây) là **[Đề xuất 22/10]**.

```
EVAL_MODE=true python -m app.eval.groundedness judge  --answers answers.jsonl --out DIR --llm-factory pkg.mod:fn
EVAL_MODE=true python -m app.eval.groundedness score  --run DIR
EVAL_MODE=true python -m app.eval.groundedness sample --run DIR --answers answers.jsonl [--n 30] [--seed S] [--random]
EVAL_MODE=true python -m app.eval.groundedness agree  --run DIR --labels review_sample_da_dien.jsonl
```

- **Dữ liệu** [Đề xuất 22/10]: CÂU HỎI THÔNG TIN — bộ `eval/retrieval` và các câu info của probe — chạy với LLM thật. **Không dùng thẻ** giả `[fake:…]` (thẻ chọn phản hồi ScriptedLLM, không phải câu trả lời thật).
- **Đầu vào** `answers.jsonl`, mỗi dòng: `{scenario_id, family, answer, citations[], chunks[{chunk_id, text, doc_id?, title?, heading_path?}], steps?[], cannot_answer?}`.
  - `family` **BẮT BUỘC** (họ = câu hỏi gốc + các biến thể của nó; là đơn vị rút lại của bootstrap). Thiếu hoặc rỗng → lỗi nêu số dòng; **không** suy từ tiền tố `scenario_id`.
  - `chunks[].text` = mọi khối bằng chứng đã gửi cho `b10_answer` ứng với chunk được dẫn, **gồm cả chunk liền kề (D-24)** — đúng như model viết đã thấy. Nguồn khi thu thập: `llm_calls.prompt_full` (`EVAL_MODE`) — việc của mốc G.
  - `answer` có thể là bản đã render (khối "Nguồn:" tự bị bỏ).
- **Đầu ra** trong `DIR` (đề nghị `eval/reports/<run_id>/groundedness/`): `results.jsonl`, `errors.jsonl`, `summary.json`, `manifest.json`; `review_sample.jsonl` (mù — không có verdict LLM), `review_key.jsonl`, `review_meta.json`, `agreement.json`. Mã thoát: 0 ổn; 2 lỗi đầu vào; 3 có ca chấm lỗi.
- **Manifest** ghi model chấm, id/phiên bản/sha256 của prompt chấm, seed, số lời gọi/token/chi phí, sha256 đầu vào.
- **Nhãn người**: Quân điền `human_supported` (true/false) vào chính `review_sample.jsonl`, trả lại làm `--labels`.
- **Mẫu** mặc định phân tầng (nửa số ca có ý không được hỗ trợ theo LLM, nửa còn lại); `--random` rút ngẫu nhiên thuần. Seed mặc định = `SEED` của P8 (20260925).
- **Định nghĩa**: ý được hỗ trợ = verdict `supported`, `partial` báo riêng và không tính là hỗ trợ. Citation precision = số cặp (ca, đoạn được dẫn) mà đoạn đó là bằng chứng `supported` của ≥ 1 ý ÷ tổng số cặp (ca, đoạn được dẫn). Khoảng tin cậy bootstrap theo họ (2000 lần, 95 %).
- **Độ tin cậy của người chấm**: `agreement.json` báo tỉ lệ khớp, Cohen κ (+ khoảng tin cậy rút lại ca), ma trận nhầm và số ý/ca "LLM hỗ trợ / người không". **κ < 0,6 → cờ `low_kappa`** (κ không xác định cũng gắn cờ). Khối `human_agreement` trong `summary.json` đi kèm con số groundedness: tỉ lệ khớp + κ + `low_kappa`.
- **Ca không có trích dẫn**: mọi ý tính là không được hỗ trợ, cờ `no_citation`. Thực tế hiếm — hậu kiểm trích dẫn của B10 (`check_citations`) chặn ca không trích dẫn thành E3 nên gần như không tới được đây; giữ xử lý này để số không bị phồng nếu có.
- **Giới hạn** (đầy đủ ở docstring `groundedness/__init__.py`): tách ý bằng code (câu ghép = một ý; ý xã giao bị chấm như ý thường); **model chấm = model viết** (cấu hình A: fast = strong = cùng model) nên có thể thiên vị cùng họ — mẫu người soát và cờ `low_kappa` là phép kiểm; chỉ chấm trên đoạn đã dẫn; κ của mẫu phân tầng không ngoại suy ra toàn bộ.
- **Nối thật mốc G**: xem mục "Nối thật mốc G (G10 + G11)" bên dưới (collector, `probe-input`, factory gateway thật).

## Nối thật mốc G (G10 + G11)

Mọi thứ dưới đây chỉ chạy khi `EVAL_MODE=true`; code và test **không đọc `.env`** (người chạy tự nạp biến môi trường như compose) và test không dùng mạng.

### Factory gateway thật — `app.eval.llm_factory:eval_gateway`

`--llm-factory app.eval.llm_factory:eval_gateway` (G11 `judge`, G10 `collect-no-evidence`). Cấu hình đọc như backend: `config/llm.yaml` + biến `EVAL_MODE=true`, `APP_ENV` (dev/test/staging), `LLM_BACKEND=real`, `FAST_MODEL`, `STRONG_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY`, `DATABASE_URL` (role `app_rw`).

- **Chỉ chạy factory SAU khi đã sao lưu DB bản đo (H4).** Nó GHI vào DB: `users` (1 dòng `svc-eval`), `tickets` (1 dòng `eval-<run_id>`, `final_state` NULL), `turns` (1 dòng, đã kết thúc), cộng `spans`, `llm_calls` (có `prompt_full`) và `llm_cache` (mode `eval`) cho từng lời gọi. Lượt eval là điều kiện để `llm_calls` ghi được (FK `span → turn → ticket`).
- Từ chối chạy (`EvalConfigError`, 0 lời gọi) nếu thiếu `EVAL_MODE=true`, `LLM_BACKEND` khác `real`, hoặc có vai trò trong `llm.yaml` có `temperature ≠ 0`. Thông báo lỗi chỉ nêu tên biến, không có khoá API hay DSN.
- Cache `eval` (chạy lại cùng đầu vào → cùng đáp án), trần chi dùng chung `spend.cap_usd` (chi của lần đo tính vào N1) và `--max-usd X` đặt thêm trần riêng cho lượt này (= tổng chi lúc bắt đầu + X).
- **Nhiệt độ**: guard `temperature = 0` chỉ áp cho prompt đọc nhiệt độ từ vai trò (`b10_answer`, `eval_groundedness`). B14 tự đặt nhiệt độ từng lời gọi theo thiết kế P5/P6 (self_report 0,0; vote k=5 là **0,7**) — giữ nguyên.
- **Ảnh hưởng tới M9** (kiểm 22/10, không sửa M9; mỗi run thêm 1 ticket lá `final_state` NULL):
  - Không vào mẫu số các tỉ lệ nghiệp vụ và `tokens_per_ticket` (lọc `final_state IS NOT NULL`: `monitor/queries/common.py` `DONE`, `business.py`, `ai.py:85`, `rules_data.py` `DRIFT_DONE`).
  - **Có đếm**: phân bố intent của luật drift (`DRIFT_INTENT_SQL`: +1 ở bin `none`/run, `rules_data.py`, không lọc kết thúc); `cache_hit_rate`, `json_invalid_first_try_rate`, `fallback_rate` (`ai.py:124` — lời gọi của lượt eval vào cả tử lẫn mẫu); `cost_per_day` (chi eval vào chi theo ngày — đúng thực tế); luật 14 ngân sách (`LLM_SPEND_SQL`, tổng toàn bảng — chi eval làm cảnh báo 80 % đến sớm hơn, đúng ý N1).
  - Không ảnh hưởng: các đếm theo `exit_code`/dòng audit (ticket eval không có), recover của worker (`scan_stale_turns` chỉ quét turn chưa kết thúc; turn eval có `ended_at`), quét ticket cha/con (`db/runtime.py`; ticket eval không là cha và không có cha).

### G11 `collect` — dựng `answers.jsonl` từ DB

```
EVAL_MODE=true python -m app.eval.groundedness collect \
    (--questions Q.jsonl | --from-run RUN_DIR --scenarios DIR | --from-probe ket-qua.json --families families.jsonl) \
    --out DIR [--since ISO --until ISO]
```

Chỉ đọc: `DATABASE_URL` (role `app_rw`, vì `app_monitor` không đọc được bảng checkpoint) nhưng **mọi phiên bị ép `default_transaction_read_only=on`**. Nguồn từng trường: xem docstring `groundedness/collect.py` (audit B10/B8, checkpoint `conversation`/`retrieved`, `llm_calls.prompt_full` của `b10_answer`). `Q.jsonl` = `{scenario_id, family, ticket_id}`; `--from-probe` ghép `rows[].{id, ticket}` của `ket-qua.json` (`tests/probe/cong5.py`) với `families.jsonl`. **`family` bắt buộc từ đầu vào** — dòng có ticket mà thiếu họ → lỗi, không suy. Ra `answers.jsonl` + `collect_report.json` (`n_questions`, `n_collected`, `n_families`, `n_cannot_answer`, số ca bỏ theo lý do). `summary.json` của `judge` cũng ghi `n_families` (số họ trong các ca được chấm = số đơn vị rút lại của bootstrap). Mã thoát 3 nếu có ca bị bỏ vì lỗi hệ thống (`no_prompt_full`, `evidence_parse_failed`, `no_checkpoint`, `no_answer_message`).

### `probe-input` — bộ câu cho `make probe` [Đề xuất 22/10 — P6 chốt P8 6.3.1]

```
EVAL_MODE=true python -m app.eval.groundedness probe-input --retrieval-set kb/eval/retrieval_set.yaml --out DIR
make probe F=DIR/probe.jsonl         # rồi: collect --from-probe .verify/cong5/<giờ>/ket-qua.json --families DIR/families.jsonl
```

`probe.jsonl` = `{"id", "kind": "intent", "text": query, "gold": intent}` cho mọi câu `role: employee`. `families.jsonl` = `{scenario_id: id, family}` với **family = `expected_doc_ids[0]` theo đúng thứ tự trong YAML**; câu có `expected_doc_ids` rỗng (âm tính) → **family = id của câu** (mỗi câu một họ, không gộp chung). Bộ hiện tại: 56 câu, 22 câu âm tính.

### G10 `collect-no-evidence`

```
EVAL_MODE=true PYTHONPATH=backend python scripts/eval/prob_variants.py collect-no-evidence \
    --run RUN_DIR --out OUT --llm-factory app.eval.llm_factory:eval_gateway --p-method self_report [--max-usd X]
```

`RUN_DIR` = thư mục lượt harness (một file `predictions.jsonl` = một lượt, một `split`). Chọn ca `decided_by = llm` đã có nhãn; `kb_gap` lấy từ `audit_logs.detail->>'kb_gap'` dòng B13/B14 — đúng giá trị truyền vào `decide()` (**không** dùng `grounding.kb_gap` của B10, nghĩa khác). Action/RiskContext dựng lại từ checkpoint bằng chính `risk.context.build_ctx`; `within_business_hours` tính lại từ giờ dòng audit nên có thể lệch vài ms so với `now` của node ở sát 08:00/18:00 (prompt B14 không dùng `now`). Ra `with.jsonl`, `cases.jsonl`, `without.jsonl`, `probs.jsonl` (ca `kb_gap` chép `raw_prob`), `manifest.json` (gồm tổng hợp `llm_calls` của lượt eval). `p_method` phải khớp audit, lệch thì dừng.

Kiểm: `backend/tests/unit/eval/test_noi_that_unit.py`, `backend/tests/integration/test_noi_that_pg.py` (Postgres), đột biến `scripts/mutation/mutate_noi_that.py` (17 mã).
