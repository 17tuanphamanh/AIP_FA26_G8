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
| `id`, `family`, `source`, `at` | chuỗi | `id`, `family` vào bản ghi; `source` chỉ nạp; `at`: ISO-8601 có múi giờ, quyết định ca chạy hay `skipped_hours` (G7, dưới đây) |
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
- Đột biến: `scripts/mutation/mutate_g2.py` (51 đột biến) và `scripts/mutation/mutate_v11.py` (hợp đồng v1.1, 11 đột biến).
- Chỉ số G1 (`metrics.py`: `operating_metrics`, `manual_baseline`, `breakeven`): unit `backend/tests/unit/eval/test_metrics_*.py`,
  đột biến `scripts/mutation/mutate_g1.py` (30 đột biến).
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
- Chạy nhiều lượt liên tiếp (vd tái lập G3): nghỉ ≥ 3 phút giữa hai lượt, vì ca `approver_decision: null` để lại ticket chờ duyệt,
  worker đóng bằng E6 sau SLA.
- Đang dùng `LLM_CACHE_MODE=eval` mà sửa preset thì xoá các dòng `llm_cache` của prompt đó (`prompt_id`, `mode = 'eval'` — không hết
  hạn), nếu không sẽ nhận phản hồi cũ.

**Trước khi giao:** Tuấn Anh chạy `--check-only` trên dữ liệu thật. Lệnh này chỉ nạp kịch bản, không gọi stack, không cần
`EVAL_PASSWORD`, và chỉ in `scenarios: loaded=<n> errors=<n>` cùng các dòng lỗi dạng `file #i/N: <vị trí trường>`. Vẫn phải có
`EVAL_MODE=true` dù không gọi stack: `app/eval/__init__.py` chặn import khi thiếu.

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
  - `--per-case`: in thêm mỗi ca một dòng `<scenario_id> <kết cục> <giây>`, kèm tên lớp lỗi hoặc lý do bỏ qua
    (`lech_loai_gio` / `bien_gio`).
  - `--resume <thư mục run>`: xem mục G7 dưới đây. Không dùng kèm `--out`.
  - `--warmup-rounds N`: số vòng làm nóng, mặc định 3.
  - `--prob-method`: mặc định `self_report`.
  - `--run-id`: chỉ để đối chiếu.
- Biến `COMPOSE` (mặc định `docker compose`) giống gate2.

**Đọc đầu ra.** Mặc định stdout có đúng 7 dòng tổng hợp (thêm `ignored_fields=<n>` khi có `--allow-extra-fields`):

```
eval run <run_id> strategy=hybrid split=test timeout_s=<n>
scenarios: loaded=<n>
warmup: rounds=<n> first_ms=<n> last_ms=<n>
outcomes: done=<n> timeout=<n> multi_leaf=<n> error=<n> skipped_hours=<n>
records: written=<n> route_none=<n> calibrated_prob_nonnull=<n> unlabeled=<n>
elapsed_s=<n>
files: predictions.jsonl outcomes.jsonl manifest.json
```

Harness không in câu, id kịch bản, họ, gold, ticket_id, route từng ca, detail, SQL hay thông điệp lỗi. Cảnh báo đi ra stderr.

**Mã thoát:**

| Mã | Nghĩa |
|---|---|
| 0 | Xong (kể cả còn ca `skipped_hours`; `--resume` không còn ca nào thì không ghi gì) |
| 1 | Có ca `timeout` hoặc `error`; file vẫn được ghi |
| 2 | Dừng trước khi ghi `predictions.jsonl`. Dòng cuối `DỪNG: <lý do>` cho biết nguyên nhân: tham số, kịch bản lỗi, chốt an toàn, seed không đọc được, STRATEGY / EVAL_MODE / LLM_CACHE_MODE / APPROVAL_SLA_MINUTES_DEV / APP_GIT_SHA của container, `/api/health`, làm nóng, hoặc điểm log 4 thiếu khoá / sai strategy |

**File trong `--out`:**
- `predictions.jsonl`: hợp đồng v1.1 (P8 v1.4 §5.6, `schema_version` = `"1.1"`), đọc bằng `app.eval.predictions.load_predictions`.
  Mỗi dòng là một lá; ca `multi_leaf` không có dòng ở đây. Ca hết giờ vẫn có bản ghi, với `final_state` = `null`. Kịch bản chưa nhãn
  có bản ghi với `expected_route` = `null` (đếm ở `unlabeled`).
  - `run_started_at`: giờ bắt đầu của từng kịch bản (ISO 8601 có offset), cùng giá trị với `outcomes.jsonl`. Giờ bắt đầu cả lượt nằm
    ở `manifest.started_at`.
  - `fold`, `hidden_factor`, `in_business_hours`: luôn `null` ở lượt stack, vì chưa có nguồn hợp lệ. Tên ba trường này
    được liệt kê ở `manifest.predictions_unavailable`. Lý do từng trường:
    - `fold`: gán phần ở bước offline, từ `SPLIT.md` (V11-Q3).
    - `hidden_factor`: dữ liệu kịch bản chưa có khoá này (V11-Q1).
    - `in_business_hours`: G7 chỉ điền ở `outcomes.jsonl` (G7-Q1); ở predictions cần sửa `collect.py` (V11-Q5).
  - `kb_gap` (P6 22/10): chỉ ca đi lớp LLM (`decided_by = llm`); lấy từ audit điểm log 4 (`step = 'B13/B14'`) `detail->>'kb_gap'` — giá trị
    `b12_assess` truyền vào `decide()`, KHÔNG phải B10 `grounding.kb_gap` (điểm truy hồi dưới `RETRIEVAL_THRESHOLD`, nghĩa khác). Không có dòng log 4 /
    khoá → `null`, đếm ở `manifest.counts.kb_gap_missing`. Ca do luật quyết luôn `null`.
  - `intent`: `tickets.intent`; null thì lấy dòng audit B3 (cột `intent`, dòng cuối khác null); vẫn không có → `null`, đếm ở
    `manifest.counts.intent_missing`.
  - `m5_aborted` (P6 22/10, P8 §5.4): `true` khi ticket có dòng audit của lớp bọc lỗi (`event` = `turn_budget_exceeded` hoặc `unhandled_exception`,
    `graph/boundary.py`) với `from_status = S_ASSESSING`; có audit mà không có dòng đó → `false`; ticket không có dòng audit nào → `null` (đếm ở
    `manifest.counts.m5_aborted_unknown`). `offline.py` và `report.py` dùng cờ này cho lá đã nhãn không có route: `true` → ESCALATE_L2, `false` → ngoài
    mẫu số, `null` → dừng.
  - File v1 (không có `schema_version`) bị `load_predictions` từ chối với lỗi `bản v1`. Muốn có file v1.1 thì chạy lại harness.
- `outcomes.jsonl`: kết cục từng ca (`done` / `timeout` / `multi_leaf` / `error` / `skipped_hours`), tên lớp lỗi, số giây, giờ bắt
  đầu, `in_business_hours` (giờ thật lúc xét ca), `hours_class` (`trong` / `ngoai` / `bien_gio`), `skip_reason`, `pass` (lần chạy).
- `manifest.json`: cấu hình, `run_id`, commit, `dataset_sha256`, `policy_sha256`, `clf_mode`, làm nóng, số đếm (gồm `unlabeled`,
  `confirm_default`), `ignored_fields`, `schema_version`, `predictions_unavailable`.
  Các khoá của 21/10 (`b2_tau`, `b2_judge_model`, SHA hai model, `rate_limits`) để `null` và liệt kê trong `unavailable`.
  Không có manifest thì không đưa số vào báo cáo (P8 §5.1).
  `passes`: mỗi lần chạy (lần đầu + mỗi `--resume`) một phần tử: `started_at` / `finished_at` thật, `ran`, `skipped_hours`,
  `lech_loai_gio`, `bien_gio`, `hours_class`. `counts` = trạng thái cuối (kết cục mới nhất của mỗi ca).

### G7 — khung giờ `at` (`schedule.py`)

- "Trong giờ hành chính" = `app.domain.policy.within_business_hours` với `get_policy().business_hours`, tính TRONG container backend
  (`schedule.HOURS_SCRIPT`): đúng hàm, đúng policy backend đang dùng. Container chỉ trả bool, harness không đọc file policy và không
  in / ghi giờ bắt đầu, giờ kết thúc hay ngày làm việc. Không xét ngày lễ (như hàm backend).
- Trước mỗi ca, harness hỏi bốn thời điểm `at`, `now − 10′`, `now`, `now + 10′`:
  - ba điểm quanh `now` khác nhau → `now` gần biên đầu hoặc biên cuối giờ hành chính (vùng nửa mở `[biên − 10′, biên + 10′)`) →
    `skipped_hours`, lý do `bien_gio`;
  - `now` khác loại giờ với `at` → `skipped_hours`, lý do `lech_loai_gio`;
  - còn lại → chạy. Ca bỏ qua không tạo ticket, không có dòng predictions. Harness không chờ.
- `--timeout-s > 600` → cảnh báo ra stderr: ca dài có thể vượt biên giữa chừng.
- `at` sai / thiếu múi giờ → `--check-only` in `at: errors=<n>`, mã 2; lượt chạy dừng mã 2 trước khi gọi stack.
- `--resume <thư mục run>` (cùng `--scenarios --strategy --split --timeout-s` như lần đầu): chỉ chạy ca có kết cục mới nhất là
  `skipped_hours`. run_id tính lại phải bằng `manifest.run_id`, khác thì dừng mã 2. Ca đã có kết cục chạy thật hoặc dòng predictions mà
  sắp chạy lần 2 → dừng mã 2, không ghi. Kết quả ghi tiếp vào cùng `predictions.jsonl` / `outcomes.jsonl` (dòng cũ giữ nguyên) và
  `manifest.json` (thêm một phần tử `passes`).

```
EVAL_MODE=true EVAL_PASSWORD='<mật khẩu demo>' PYTHONPATH=backend uv run python -m app.eval.runner \
  --scenarios <thư mục kịch bản> --strategy hybrid --split test --timeout-s 300 --resume <thư mục run lần trước>
```

Đã kiểm ở: `backend/tests/unit/eval/test_schedule.py`, `test_harness_hours.py` (policy giả tự dựng trong test); đột biến
`scripts/mutation/mutate_g7.py` (28 đột biến).

## Báo cáo G5 — `report.py` (RQ1, RQ3)

Sinh bảng Markdown + CSV từ `predictions.jsonl` (v1.1) và `manifest.json` của từng lượt chạy (P8 v1.4 §6, §7). Chỉ gọi `metrics.py`,
`stats.py`, `decision_math`; không tính route offline. Không có manifest thì không ra số.

```
EVAL_MODE=true PYTHONPATH=backend uv run python -m app.eval.report \
  --arm S1/predictions.jsonl S1/manifest.json --arm S2/predictions.jsonl S2/manifest.json \
  --arm S3/predictions.jsonl S3/manifest.json [--situations situations.csv] --out <thư mục mới>
```

- Mỗi `--arm` là một phương án (`rule_only`, `llm_only`, `hybrid`, `hybrid_guarded`, theo trường `strategy`); lượt S3 là Hybrid có
  `enable_proactive_diagnosis = false` ở manifest. Thủ công và Full-auto là giải tích, dựng trên phần giao.
- `--situations`: CSV (`scenario_id,situation_id`) hoặc JSON. Có file thì FNR theo tình huống gộp theo `situation_id`; thiếu thì lùi về họ
  và báo CẢNH BÁO ở T3a, T4. Bootstrap luôn theo họ.
- Mọi bảng mang `run_id, dataset_sha256, git_commit, n, n_unlabeled, n_excluded`. Số chính RQ1 = chi phí không trọng số (T1); T5, T6, T7 là số phụ.
- Test: `backend/tests/unit/eval/test_report.py` (golden ở `golden/report/*.golden`; đổi định dạng có chủ ý thì chạy với `UPDATE_GOLDEN=1` rồi đọc lại
  diff). Đột biến: `scripts/mutation/mutate_g5.py`.
- Chưa có: biểu đồ, 10 ca sai tiêu biểu. `folds/<i>.json` và route offline do `offline.py` ghi (mục dưới); biến thể "không trích đoạn" lấy từ `probs.jsonl` (G10).

## Thu `no_evidence` (G10) — `prob_variants.py collect-no-evidence`

**Ngoại lệ (P8 §10):** script đo thêm SAU tag `v1.0-freeze` (bf94df2), chỉ ở `backend/app/eval/` (`llm_factory.py`, `dbread.py`,
`prob_collect.py`), `scripts/eval/prob_variants.py` và test — KHÔNG đổi hành vi hệ thống, không đổi `config/` (prompt, policy). Stack đo vẫn
chạy bf94df2; script chỉ ĐỌC DB của lượt đã chạy và gọi lại B14 với trích đoạn rỗng. Lấy từ nhánh `cloud/g-noi-that` 4ad61fa, bỏ G11.

`offline.py` cần `probs.jsonl` (3 biến thể `with_evidence`, `no_evidence`, `max`) cho S1 (hybrid) và S2 (llm_only). `with_evidence` chép từ
lượt chạy; `no_evidence` = một lần gọi B14 mới với trích đoạn rỗng (sampling_k5 = 5 phiếu `b14_risk_vote`); ca `kb_gap` đã gửi trích đoạn
rỗng sẵn nên CHÉP, không gọi lại.

**Chuẩn bị (một lần):**
- Sao lưu DB của máy đo TRƯỚC (H4): factory GHI vào DB 1 user `svc-eval`, 1 ticket `eval-<run_id>` (`final_state` NULL), 1 turn đã kết thúc,
  cùng `spans`/`llm_calls` (có `prompt_full`)/`llm_cache` (mode `eval`) của từng lời gọi.
- Nạp biến môi trường trong shell (code KHÔNG đọc `.env`, không in khoá): `EVAL_MODE=true`, `APP_ENV=dev`, `LLM_BACKEND=real`, `FAST_MODEL`,
  `STRONG_MODEL`, `LLM_BASE_URL`, `LLM_API_KEY`, `DATABASE_URL` (role `app_rw`, tới Postgres của stack đo từ máy chạy lệnh).
- Factory từ chối (0 lời gọi) nếu thiếu `EVAL_MODE=true`, `LLM_BACKEND` khác `real`, hoặc vai trò trong `config/llm.yaml` có `temperature ≠ 0`.
  B14 tự đặt nhiệt độ từng phiếu (k=5 là 0,7) — giữ nguyên thiết kế.

**Từng bước, làm cho S1 rồi S2** (`RUN` = thư mục lượt harness có `predictions.jsonl` + `manifest.json`; `OUT` = thư mục MỚI):

```
# 1. Thử (không gọi LLM, không ghi file): đọc DB, in số ca, số ca kb_gap, số lời gọi dự kiến
EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/prob_variants.py collect-no-evidence \
    --run RUN_S1 --out OUT_S1 --dry-run

# 2. Thu thật (LLM thật): DB → with.jsonl + cases.jsonl → gọi B14 trích đoạn rỗng → without.jsonl → probs.jsonl + manifest.json
EVAL_MODE=true PYTHONPATH=backend uv run python scripts/eval/prob_variants.py collect-no-evidence \
    --run RUN_S1 --out OUT_S1 --llm-factory app.eval.llm_factory:eval_gateway [--max-usd 2]

# 3. (Tuỳ chọn) dựng lại probs.jsonl từ with/without đã có — bước 2 đã làm sẵn
PYTHONPATH=backend uv run python scripts/eval/prob_variants.py build OUT_S1/with.jsonl OUT_S1/without.jsonl OUT_S1b/probs.jsonl

# 4. So sánh chẩn đoán (không chọn biến thể)
PYTHONPATH=backend uv run python scripts/eval/prob_variants.py compare OUT_S1/with.jsonl OUT_S1/probs.jsonl --json OUT_S1/so-sanh.json

# 5. Sau khi có cả S1 và S2: offline.py (mục dưới) với --s1 RUN_S1/predictions.jsonl RUN_S1/manifest.json OUT_S1/probs.jsonl
#    --s2 RUN_S2/predictions.jsonl RUN_S2/manifest.json OUT_S2/probs.jsonl
```

- **p_method = sampling_k5 bắt buộc** (bản đóng băng, P8 §5.1). Trước mọi lời gọi: manifest lượt phải có `config.prob_method = sampling_k5`
  và `counts.p_method_mismatch = 0`, mọi bản ghi đi lớp LLM trong `predictions.jsonl` có `p_method = sampling_k5`, dòng audit B13/B14 cũng vậy.
  Lệch ở bất kỳ đâu → dừng cả lượt (mã 2), 0 lời gọi. `--p-method` chỉ nhận `sampling_k5`.
- **Chọn ca:** `decided_by = llm`, đã có nhãn (`expected_route`). S1: ca không khớp luật; S2 (llm_only): mọi ca có route. `kb_gap` lấy từ
  `audit_logs.detail->>'kb_gap'` dòng B13/B14 (giá trị đã truyền vào `decide()`); Action/RiskContext dựng lại từ checkpoint bằng chính
  `risk.context.build_ctx`. Ca thiếu dữ liệu bị bỏ và đếm theo lý do (`unlabeled`, `llm_no_raw_prob`, `no_log4`, `raw_prob_mismatch`, `no_kb_gap`,
  `no_state`) — không đoán. Ca `llm_no_raw_prob` không có dòng nào trong `probs.jsonl`; `offline.py` giữ route hệ thống cho ca đó (mục dưới).
- **Số lời gọi dự kiến** = (ca đi lớp LLM − ca kb_gap) × 5, in ở cả `--dry-run` lẫn lượt thật trước khi gọi; ít hơn nếu trúng cache `eval`.
- **Lỗi LLM** (`LLMUnavailable`, `LLMSchemaError`, `LLMBudgetExceeded`, `TurnBudgetExceeded`) → dòng `{"scenario_id", "error"}` trong
  `without.jsonl` (hợp đồng WITHOUT.jsonl), ca đó mất `no_evidence` + `max`, lượt không dừng; mã thoát 3, số lỗi ở `manifest.json`
  `build.failed`. Chạy lại vào thư mục `OUT` mới: ca đã thành công trúng cache `eval` (cùng đáp án), chỉ ca lỗi gọi lại.
- **DB chỉ đọc** khi thu dữ liệu: mọi phiên của `open_reader` bị ép `default_transaction_read_only=on` (cả engine lẫn pool checkpoint).
- `OUT` đã có file kết quả → dừng trước khi đọc DB. `manifest.json` ghi `predictions_sha256`, `run_manifest` (run_id, strategy,
  policy_sha256, git_commit của lượt), báo cáo chọn ca, kết quả build, tổng `llm_calls` của lượt eval và giới hạn.
- Giới hạn: `within_business_hours` tính lại từ giờ dòng audit (lệch vài ms ở sát 08:00/18:00; prompt B14 không dùng `now`).
- Kiểm: `backend/tests/unit/eval/test_g10_collect.py`, `backend/tests/integration/test_g10_pg.py` (Postgres, ScriptedLLM, không mạng).

## Route offline và hiệu chỉnh theo phần — `calibrate.py`, `offline.py` (N18, G4)

Bản đóng băng chạy chưa hiệu chỉnh (D-38), nên route của stack không phản ánh quy trình "fit calibrator + chọn ngưỡng theo chi phí". `offline.py`
tính lại route cho Hybrid, Chỉ-LLM, Hybrid-guarded bằng kiểm tra chéo 5 phần: với phần đo `i`, `calibrate.fit_fold` fit trên 4 phần còn lại
(Platt riêng từng phương án × từng phần, chọn ngưỡng theo ma trận chi phí 10:1, chọn biến thể xác suất `with_evidence` / `no_evidence` / `max`),
rồi tính route cho phần đo. Số RQ1 của các phương án có LLM là ước lượng của quy trình đó, không phải route đã chạy trên stack.

```
EVAL_MODE=true PYTHONPATH=backend uv run python -m app.eval.offline \
  --s1 S1/predictions.jsonl S1/manifest.json S1/probs.jsonl --s2 S2/predictions.jsonl S2/manifest.json S2/probs.jsonl \
  --folds folds.csv --policy config/policy.json --out <thư mục mới>
```

- Đầu vào: hai lượt stack (S1 = hybrid, S2 = llm_only; mỗi lượt kèm `probs.jsonl` do `scripts/eval/prob_variants.py` ghi), `--folds` CSV
  `family,fold` (tạm, tới khi có `split.py`/`SPLIT.md`), `--policy` (sha256 phải khớp `policy_sha256` của mọi manifest; ngưỡng trên của policy chỉ
  dùng cho phần chưa hiệu chỉnh). `now` của `fit_platt` = `started_at` trong manifest S1 để chạy lại ra cùng `version`.
- Đầu ra, mỗi phương án (`hybrid`, `llm_only`, `hybrid_guarded`): `predictions.jsonl` (v1.1, `route`/`calibrated_prob` offline, `fold` đã điền),
  `manifest.json` (+ khối `offline`; Hybrid-guarded có `run_id` mới và `derived_from`), `folds/<i>.json`, `calibrators/<version>.json`. Đưa thẳng vào
  `report.py` bằng `--arm`.
- Ca đi lớp LLM (P8 §5.4): Hybrid = `decided_by = llm` của S1; Chỉ-LLM = mọi ca có route của S2; Hybrid-guarded = ca `llm` của S1 cộng ca luật CHO PHÉP
  (route AUTO), p lấy từ S2; luật chặn/cần duyệt giữ route luật. Ca đã nhãn có `route` null (P8 §5.4 [Chốt 22/10]): `m5_aborted = true` → ESCALATE_L2; `false` (E1, lỗi ở bước khác, kẹt B11…) → ngoài mẫu số; `null` → dừng. `report.py` áp cùng quy tắc cho mọi phương án kể cả Chỉ-luật.
- Quy tắc: `kb_gap` hạ AUTO → HITL và là của ca (mọi biến thể dùng chung); hoà chi phí → with_evidence > no_evidence > max; ngưỡng trên 1,01 =
  lớp LLM không bao giờ đưa ca sang L2, bật khi dưới `MIN_L2_CASES` ca L2 trong ca đi lớp LLM của phần huấn luyện hoặc AUC L2 < 0,7 hoặc không tính được;
  biến thể `fit_platt` lỗi bị loại; cả ba lỗi → phần đó chưa hiệu chỉnh (không bao giờ AUTO, ngưỡng dưới 0; raw > ngưỡng trên của policy → L2).
- Ca đi lớp LLM **không có xác suất**: `raw_prob` null ở dòng nguồn (S1 cho Hybrid, S2 cho Chỉ-LLM và Hybrid-guarded, S3 cho `hybrid_no_diag`)
  VÀ `probs.jsonl` không có `with_evidence` của ca (G10 bỏ ca này, đếm `skipped.llm_no_raw_prob`). Không có p thì không hiệu chỉnh được, nên
  offline giữ route hệ thống đã ra lúc chạy (route của dòng nguồn ghi ra; ca vào nhóm route cố định, đếm `llm_no_prob` ở `manifest.offline.counts`).
  An toàn vì bản đóng băng lớp LLM không bao giờ ra AUTO (D-38); nếu route đó là AUTO thì dữ liệu lạ → dừng, không đoán. Ca CÓ `raw_prob` mà
  thiếu `with_evidence` vẫn dừng (nhầm file hoặc thu thiếu).
- Dừng (mã 2) khi: `kb_gap` null ở ca đi lớp LLM (harness phải điền `kb_gap`), họ không có phần hoặc `fold` lệch CSV, `policy_sha256` thiếu/lệch,
  thiếu `started_at`, `probs.jsonl` không khớp predictions cùng lượt.
- Giới hạn: Platt thường, không làm mượt nhãn (F3 không làm); `select_thresholds` không biết `kb_gap`; `fold` từ CSV tạm.
- `--s3` (tuỳ chọn): Hybrid tắt chẩn đoán — chạy lại phép tính của Hybrid với S3 làm nguồn (calibrator fit trên phần huấn luyện của chính S3) → thư mục `hybrid_no_diag`
  (manifest tắt chẩn đoán → `report.py` nhận là phương án "bỏ tool").
- Test: `tests/unit/eval/test_calibrate.py`, `test_offline.py`. Đột biến: `scripts/mutation/mutate_n18.py`.
