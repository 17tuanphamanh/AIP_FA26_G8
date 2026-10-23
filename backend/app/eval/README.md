M8 — chỉ bật khi EVAL_MODE=true, P8. Xem docs/spec/build/01-kien-truc-project.md mục 3.

## SPLIT.md + CI (G9)

`eval/SPLIT.md` do phiên git sinh lúc khoá nhãn (25/10). File có đúng một khối ```` ```yaml ```` gồm `seed`, `k`, `dataset_sha256`,
`files` (tên file → sha256), `families` (họ → phần 1..k), `locked`. `scripts/eval/check_split.py` băm lại `eval/scenarios/*.yaml|*.yml`
(cấp 1) bằng chính hàm của `Dataset.sha256` (`scenario_files`, `file_sha256`, `dataset_sha256` trong `dataset.py`).

CI chạy script này ở job `lint-test`, ngay sau bước cài phụ thuộc:

```
EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/check_split.py
```

| Mã | Khi nào |
|---|---|
| 0 | Khớp; chưa có SPLIT.md (cảnh báo); `locked: false` mà dữ liệu lệch (cảnh báo) |
| 1 | `locked: true` mà có file thiếu, thừa, sha lệch hoặc `dataset_sha256` lệch |
| 2 | SPLIT.md sai cấu trúc, kể cả khi `locked: false`: không đúng 1 khối yaml, khoá trùng (một họ ở 2 phần), khoá lạ/thiếu/sai kiểu, phần ngoài 1..k, phần rỗng, `dataset_sha256` không khớp chính `files` |

Log chỉ có số đếm và vị trí `file #i/N`, `họ #i/M`; không có tên file, tên họ hay sha. Kịch bản được sửa sau khoá (vd sửa lỗi nhãn)
thì phải sinh lại SPLIT.md, nếu không CI đỏ.

## κ đồng thuận người gán nhãn (G9)

Hàm thuần nằm trong `stats.py`: `cohen_kappa`, `weighted_kappa_linear`, `pabak`, `agreement`. Công thức ghi ở docstring module, tính
bằng phân số; κ ≥ 0,6 là ĐẠT. CLI so 2 file xlsx của CÙNG một đợt:

```
EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/kappa.py A.xlsx B.xlsx --sheet "Đợt 2" \
  [--bo S1,TH2 | --chi S1,TH2] [--json <ngoài repo>] [--lech <ngoài repo>]
```

- **"Gộp" không cộng đợt 1 với đợt 2.** Gộp nghĩa là chạy trên sheet đợt 2 đủ 66 dòng (17 tình huống đợt 1 đã được gán lại trong
  đợt 2). Không có cờ cộng đợt.
- Cột được tìm theo tiêu đề ở dòng 1: `id` và `Nhãn`. Dòng dữ liệu là dòng có id dạng `S…`/`TH…`. Dòng cam kết sau dòng dữ liệu cuối
  bị bỏ qua; dòng id sai dạng nằm giữa các dòng dữ liệu là lỗi.
- Hai file được ghép theo id. Thiếu, thừa hoặc trùng id, nhãn ngoài AUTO/HITL/ESCALATE_L2, id trong `--bo`/`--chi` không có trong
  file: đều dừng mã 2.
- stdout có 3 dòng chỉ số, không id, không nhãn. `--json` ghi đủ chữ số kèm phân số. `--lech` ghi id và 2 nhãn của các ca lệch. Cả
  hai phải nằm ngoài repo và chưa tồn tại.
- File được đọc bằng openpyxl (nhóm dev) với `read_only=True, data_only=True`, như kiem_d6. Sheet được lấy theo tên `--sheet`, không
  lấy sheet đang mở. Ô công thức đọc theo giá trị cache mà Excel/Sheets lưu kèm file. Không mở được file hoặc không có sheet: mã 2.

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
