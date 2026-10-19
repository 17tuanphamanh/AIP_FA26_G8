M8 — chỉ bật khi EVAL_MODE=true, P8. Xem docs/spec/build/01-kien-truc-project.md mục 3.

## Harness G2 — chạy kịch bản trên stack (RQ1)

| File | Việc |
|---|---|
| `dataset.py` | nạp kịch bản `*.yaml`/`*.yml` theo cấu trúc thật (dưới đây), `dataset_sha256`; lỗi chỉ nêu `file #i/N` + vị trí trường |
| `config.py` | `RunConfig`, `run_id = sha256(config \| dataset_sha256 \| commit)[:12]` (P8 §5.1) |
| `stack.py` | lái stack compose (chép tối thiểu từ `tests/stack/gate2.py`): chốt an toàn, SQL chỉ đọc, hạn kịch bản |
| `actors.py` | `ScriptedUser` (trả lời theo `turns`), `SimApprover` (làm theo `gold.approver_decision`) |
| `collect.py` | DB → `PredictionRecord` (hợp đồng v1, `predictions.py`) |
| `warmup.py` | làm nóng rerank, chạy TRONG container backend |
| `runner.py` | CLI, vòng tuần tự, `predictions.jsonl` + `outcomes.jsonl` + `manifest.json` |

### Cấu trúc kịch bản (dữ liệu thật — Tuấn Anh 19/10)

Mọi khoá dưới đây đều bắt buộc. Khoá lạ bị từ chối (trừ khi có `--allow-extra-fields`). Không có `gold.hidden_factor`; khoá này để
PR hợp đồng v1.1.

| Khoá | Kiểu | Harness dùng |
|---|---|---|
| `id`, `family`, `source`, `at` | chuỗi | `id`, `family` vào bản ghi; `source` chỉ nạp; `at` chỉ nạp (khung giờ là việc G7) |
| `faults` | danh sách | chỉ nạp |
| `requester` | `{user_id, role, dept, tenure_days}` | `user_id` → `username` tra `mock_services/seed.json` (cờ `--seed`); không có trong seed → lỗi nạp |
| `turns` | `[0]` chuỗi; sau đó `{on_question_about, reply}` hoặc `{on_confirm}` | câu đầu tạo ticket; `reply` gửi THEO THỨ TỰ mỗi lần hệ thống hỏi lại (slot đang hỏi không lộ qua API — G2-Q19); `on_confirm` theo thứ tự ở bước xác nhận, hết thì coi là "Đã ổn" và đếm `confirm_default` |
| `gold` | `{intents, need_type, expected_route, expected_exit, approver_decision, gold_doc_ids, action{type, target, requested_for, params}, facts}` | `expected_route = null` → chưa nhãn: bản ghi vẫn ghi, đếm `unlabeled`; `approver_decision` cho người duyệt giả |
| `labels` | `{annotator_1, annotator_2}` | chỉ nạp |

Ghép nhãn sau 25/10 cho các lượt đã chạy với `expected_route = null`: chưa làm (G2-Q23).

Harness không gọi `/api/policy` hay endpoint chính sách nào. Đọc DB chỉ qua `SELECT` trong transaction chỉ đọc. Ở `audit_logs`
chỉ đọc `detail->>'route'` và `detail->>'strategy'` (dòng `B13/B14`), cùng `detail->>'turn'` (dòng `B11`).

**Đã kiểm ở đâu:**
- Unit test: `backend/tests/unit/eval/test_harness_*.py`, chạy trên stack giả.
- Đột biến: `scripts/mutation/mutate_g2.py`, 28 đột biến.
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
- `predictions.jsonl`: hợp đồng v1, đọc bằng `app.eval.predictions.load_predictions`. Mỗi dòng là một lá; ca `multi_leaf` không có
  dòng ở đây. Ca hết giờ vẫn có bản ghi, với `final_state` = `null`. Kịch bản chưa nhãn có bản ghi với `expected_route` = `null`
  (đếm ở `unlabeled`).
- `outcomes.jsonl`: kết cục từng ca (`done` / `timeout` / `multi_leaf` / `error`), tên lớp lỗi, số giây, giờ bắt đầu.
- `manifest.json`: cấu hình, `run_id`, commit, `dataset_sha256`, `policy_sha256`, `clf_mode`, làm nóng, số đếm (gồm `unlabeled`,
  `confirm_default`), `ignored_fields`.
  Các khoá của 21/10 (`b2_tau`, `b2_judge_model`, SHA hai model, `rate_limits`) để `null` và liệt kê trong `unavailable`.
  Không có manifest thì không đưa số vào báo cáo (P8 §5.1).
