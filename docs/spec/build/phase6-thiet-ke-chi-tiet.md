# Phase 6 — Thiết kế chi tiết (M5 lớp LLM: toán quyết định, calibrator, estimator, chiến lược, nối B12)

*Thuộc bộ `build/`. Phiên bản **1.2 — 16/10/2026** (1.2: **6D đã hiện thực** — mục 7.7; sửa r5, r7; 7.6 đổi nguồn DB + lệnh chạy trong container; lịch 8; 1.1: **6C đã hiện thực** — mục 6.9; **6D viết chi tiết** — mục 7; 1.0: **6C viết chi tiết** — mục 6, soát `457239d`; 0.9: Q-6-8 chốt C + 3 điều kiện 6C; **6B đã hiện thực** — mục 5.11; 0.8: soát mục 5 trên `fe61fa3` — sửa P1 chỗ estimator giả, P12 chốt, thêm es10; 0.7: **6A đã hiện thực** — mục 4.10 "Chốt khi hiện thực"; 0.6 chỉ cập nhật phối hợp/git theo luật 4.0 của phiên git — mục 0.2, 4.8, 5.9, 8; **nội dung kỹ thuật 6A/6B giữ nguyên từ 0.5**; code nền soát lại tại `3ff63e1`: file 6A/6B dựa vào không đổi). Bản 0.5 — 06/10/2026: soát lại với code `1455b55`; **6A đã chạy thử bằng cài đặt tham chiếu trên đúng bản thư viện đã khoá** — mọi số ở 4.5–4.6 khớp; sửa P8, 4.3, cb3, cb5 theo kết quả chạy; nơi chạy = worktree riêng, mục 0.2. **6A và 6B viết đủ để code ngay**; 6C, 6D ở mức khung (P-x chốt khi mở chặng). Nguồn: `huong-dan-xay-dung-he-thong-2.md` §5 Phase 6, §7.2–7.4; `B12-B14` v1.2 (§3, §4.1, §5, §5.1–5.2, §11); `P8` v1.1 (§5.3, §6.1, §9); `P2` (gateway, prompt registry, cache); `decisions.md` Q8, Q9, D-34; `claude/phase5-6-phan-tich-va-chia-chang.md` v0.1 (G6-x, D-35…D-43, lịch). Code đã đọc trên máy tại `aac90b1`, soát lại tại `1455b55` (03/10) và `3ff63e1` (09/10): các file 6A/6B dựa vào — `risk/*`, `b12_assess.py`, `llm/*`, `config/prompts`, `policy.json`, `.importlinter`, `pyproject`/`uv.lock` — **không đổi** từ `aac90b1`.*

*Nhãn: **[Chốt]** spec gốc · **[Chốt 01/10]** Tuấn Anh chốt Q-6-x ngày 01/10/2026 · **[Đề xuất]** Tuấn Anh soát khi duyệt PLAN · **[Suy luận]** agent kiểm lại trên code.*

**Kế hoạch tóm tắt (đọc trước):**

| Thứ tự | Chặng | Nội dung | Tầng | DỪNG | Model | Mở khi |
|---|---|---|---|---|---|---|
| 1 | **6A** | `decision_math.py` + `calibrator.py` — hàm thuần, số tính tay (mục 4) | B | 1 | **Sonnet** | Commit 4d (làm sớm) |
| 2 | **6B** | Estimator (tự nêu + k = 5), 2 prompt, `factors`, `strategy.py` thuần (mục 5) | **A** | 2 | **Opus** | 6A |
| 3 | **6C** | Nối lớp 2 vào B12, điểm log 4 + lineage, B17 nhận AUTO do LLM, test canary, `full_auto` (mục 6) | **A** | 2 | **Opus** | 6B + **T24** + Q-6-8 |
| 4 | **6D** | Script probe p, script lấy mẫu lý do, checklist cổng 6 (mục 7) | B | 1 | **Sonnet** | 6C (+ D2; probe thật ở mốc G) |

**Làm sớm [Chốt 01/10, D-36]:** 6A, 6B bắt đầu trước cổng 5 + D2, PROGRESS ghi **"chưa tính qua cổng 6"**. **Phase 6 KHÔNG fit calibrator trên dữ liệu thật** — fit + chọn ngưỡng thật = T37 (Phase 10), người không xây M5 chạy [Chốt P8 §1, bất biến 10].

---

## 0. Cách dùng file này

- Bản thiết kế hiện thực **duy nhất của Phase 6**. Lệch `B12-B14`, `P8`, `P2` → **file này thắng**, trừ 13 bất biến và mục **[Chốt]** gốc.
- Code đã xanh mà khác chữ ở đây → agent **báo**, không tự sửa code cũ.
- Agent đọc: mục 0, 1, 2, 3 rồi **đúng mục của chặng**.

### 0.1. Sự thật của code (`aac90b1`, soát lại `1455b55`, `3ff63e1`)

| Chủ đề | Code hiện có | Hệ quả |
|---|---|---|
| `risk/estimator.py` | `type PMethod = Literal["self_report","sampling_k5"]`; `evidence_for_estimator(chunks, score, threshold)`; `RiskEstimator` Protocol `estimate(action, ctx, retrieved) -> tuple[float, PMethod]`; `DisabledEstimator` ném `LLMUnavailable` | 6B thêm `LlmRiskEstimator`; đổi kiểu trả về thành `RiskEstimate` (tham số giữ nguyên) |
| `b12_assess.py` | Luật khớp → `goto` theo 3 đích; không khớp → `evidence_for_estimator` → `deps.estimator.estimate` → bắt `LLMUnavailable/LLMSchemaError/LLMBudgetExceeded` → E5 `llm_layer_disabled`; estimator trả số → `RuntimeError` (E9) | 6C thay nhánh sau `estimate` |
| `RiskDecision` (`domain/ticket_state.py`) | `decided_by ∈ {rule, llm}`, `policy_decision`, `matched_rule_id`, `raw_prob`, `calibrated_prob`, `p_method`, `risk_level`, `route`, `reason`, `thresholds` | Đủ cho 6B; `full_auto` → Q-6-8 (6C) |
| DB | `audit_logs` CHECK `decided_by`, `p_method`, `raw_prob`/`calibrated_prob ∈ [0,1]`; `lineage.calibrator_version String(64)`, `p_method` | Không migration ở 6A/6B |
| `LlmPort.complete` | `(role, prompt_id, variables, schema, *, sensitivity, cache_policy, n=1, temperature, kb_version) -> (T, LLMMeta)`; `n != 1` → `ValueError` | k = 5 = **5 lời gọi** `n=1` (không dùng `n`) |
| Cache | Khoá = provider·model·model_version·prompt_id·prompt_version·**rendered messages**·schema·temperature·n·kb_version·mode; prompt `cache: bypass` = không cache ở **mọi** chế độ; người gọi chỉ làm chặt hơn (`cache_policy="bypass"`) | Q-6-6 (P-x ở 5.1) |
| Prompt registry | `config/prompts/*.yaml` (`id, version, role, schema, allowed_vars, cache`); tập `{{ biến }}` = đúng `allowed_vars`; biến đặc biệt `evidence` render khối trích đoạn; test d10 đếm đủ 6 file; bản giả `b14_risk_estimate` chỉ ở `tests/fixtures/llm/prompts/` (test d1b) | 6B thêm 2 file thật; nâng số đếm d10 |
| Import-linter | `app.risk` chỉ gọi LLM qua `LlmPort`; cấm `guard`, `api`; **không** có luật risk ↔ eval; `.importlinter` thuộc Dương (M9) | Luật "risk không import eval" làm bằng **test AST** (6A) |
| Thư viện | `numpy 2.5.3`, `scipy 1.18.1`, `scikit-learn 1.9.1` (`uv.lock`) | 6A kiểm API `LogisticRegression` không phạt trên đúng bản này |
| `policy.json` | Ngưỡng ở `constants.THRESHOLD_LOW/HIGH` = 0,25/0,75; chưa có `p_method`, `calibrator_version`, `strategy`, `cost_matrix` | 6A: ma trận chi phí là hằng trong code; 6C: thêm khối `m5` (mục 6) |
| `audit_check` (4d, `app/audit/check.py:123`) | Điểm log 4 = dòng `B13/B14 risk_decided`, **bắt buộc** `decided_by`, `policy_decision`, `risk_level`, `reason`, `detail.route`, `detail.policy_sha256` | Ca LLM có `policy_decision = NULL` → `audit_check` (e2e i17, `make gate4` g4-12) báo thiếu → **6C phải sửa luật điểm 4** (G6-8, mục 6 việc 7) |
| B17 (4d P7) | Qua duyệt: so `hash_action` với hash trong state **và** hash của phiếu | D-42 (nhánh LLM-AUTO, không qua duyệt) không đụng hai lớp này; 6C thêm nhánh riêng |
| B16 (4d DỪNG 2) | Khi `approved` tự so hash state + phiếu trước `S_EXECUTING`; lệch → E5 | Ca LLM → HITL đi đúng đường này, không cần sửa |
| M9 (PR #20–#26, #31) | `decided_by_distribution` lọc `decided_by IS NOT NULL`; job `monitor_rules_minute` (+ `monitor_rules_hourly`, `monitor_rules_daily` từ `3ff63e1`) chạy trong worker | Q-6-8 phương án C (`decided_by = NULL` cho `full_auto`) không làm hỏng chỉ số M9; báo M9 khi 6C thêm khoá `detail` |

### 0.2. Phối hợp

- **M9:** không sửa file/khối M9 (như Phase 4 §0.2). 6C thêm khoá mới vào `detail` điểm log 4 → báo Dương (dashboard "phân bố p", "phân bố `decided_by`").
- **T29 (Dương), T27 (Duy Anh):** import từ `app.risk.decision_math` và `app.risk.calibrator` — **không viết lại** CP, ECE, Brier, AUC, Platt, temperature [Chốt 01/10, D-37]. API mục 4.2–4.3 là hợp đồng (đã đăng ở issue #32); đổi chữ ký sau khi 6A commit → báo hai bạn qua #32.
- **Git/GitHub [Chốt 09/10 — luật 4.0, `claude/ban-giao-phien-git-09-10.md`]:** mọi việc pull/push/merge/rebase, PR, issue/comment, tạo/xoá worktree, dùng Docker stack do **phiên chat git** làm (phiên Phase 6 soạn phiếu `[YÊU CẦU GIT]`). Agent 6x chỉ sửa code, chạy test, **commit cục bộ** trên `m5-tuananh` ở DỪNG khi được bảo (chỉ file của chặng; không `git add -A`; không `--no-verify`).
- **Nơi chạy [Chốt 09/10]:** agent Phase 6 code ở **worktree riêng** `~/Documents/AIP_FA26_G8-m5`, nhánh `m5-tuananh` (phiên git tạo 09/10 từ `origin/dev-tuananh` @ `3ff63e1`, không upstream), **ngay từ 6A**. Lý do: agent Phase 5 (T22a…) dùng thư mục chính — hai agent không cùng một cây. Trong worktree **chỉ** chạy `make verify G=0` (lint + test, testcontainers, không gọi compose; 4 test đánh dấu `tokenizer_real` tự bỏ qua vì worktree không có `models/_tokenizer` — CI vẫn chạy chúng) — **cấm** `make up`, `make verify` có chữ số cổng khác 0, `make gate*`, `docker compose`: compose đặt tên dự án cố định `servicedesk` và worktree không có `.env` (Makefile sẽ lấy `.env.example`) → sẽ dựng đè stack dev. Lượt có cổng (sau gộp 6B, 6C) qua phiếu "dùng stack" cho phiên git. Gộp về `dev-tuananh` bằng PR `m5-tuananh → dev-tuananh` — phiên git làm.
- **Phase 5 song song:** 6A/6B không sửa file Phase 5 sửa. Chỗ đụng duy nhất 6B: `backend/app/llm/schemas.py` (thêm 2 lớp) — T20 có thể thêm lớp schema B3 cùng file → mỗi bên chỉ **thêm** lớp; phiên git rebase trước khi gộp.
- **Tách vai [Chốt 8.1, D-43]:** người gán nhãn (Dương, Duy Anh) không đọc `policy.json` và lý do rủi ro; đọc 10 lý do ở 6D = **Quân**.

---

## 1. Phạm vi và cổng 6

### 1.1. Cổng 6 [Chốt `huong-dan` §5.1, B12 §11]

**Tự động:**
- Ca không luật nào khớp (TC37 + họ bổ sung): quyết định bởi LLM, định tuyến đúng theo ngưỡng. ← 6C
- Chiến lược chỉ dùng cho so sánh bị từ chối khi không ở chế độ đánh giá. ← 6B (`check_strategy`) + 6C (khởi động)
- Mọi ticket qua M5 có `decided_by`; ca LLM có `raw_prob` + `p_method`. ← 6B/6C
- Prompt gửi LLM rủi ro không chứa câu người dùng — chụp prompt thật (canary). ← 6C
- **8 test `decision_math` xanh** (ngưỡng từ chi phí, cận FNR, ECE, Brier). ← **6A** (định nghĩa 8 test ở 4.6)

**Thủ công:** probe ~30 ca xuống LLM, phân phối p, quy tắc 60 %/2 mức → ghi `p_method` (dồn **mốc G**); người không xây M5 đọc 10 lý do (**Quân**, 6D).

### 1.2. Ngoài phạm vi

Fit calibrator + chọn ngưỡng trên dữ liệu thật (T37, Phase 10); harness/`calibrate.py`/`metrics.py` (T27, T28, T29 — Phase 8); cách lấy p thứ 3 "xác suất token" (RQ2, Phase 11).

---

## 2. Quyết định Phase 6 [Chốt 01/10 — Tuấn Anh đồng ý theo khuyến nghị]

| Mã | Vấn đề | Chốt |
|---|---|---|
| Q-6-1 | Lịch 6A | Ngay sau commit 4d, song song FE; Sonnet; merge trước ~05/10 (T29 bắt đầu ~07/10) |
| Q-6-2 | Một nguồn toán | `app/risk/decision_math.py` + `app/risk/calibrator.py`; `eval/*` import lại; test AST cấm `app.risk → app.eval` |
| Q-6-3 | Chưa có calibrator | **Không AUTO:** `calibrator=None` → `raw > t_high` → L2, còn lại HITL; `reason` nêu "chưa hiệu chỉnh" (D-38) |
| Q-6-4 | `LeakageError` | `fit_*` nhận danh sách `LabeledSample(split, family, raw_prob, y)`; một mẫu `split ≠ "calibration"` → `LeakageError` |
| Q-6-5 | Lý do rủi ro | LLM trả `factors` ∈ tập mã đóng `FactorCode`; `reason` ghép theo mẫu; **không** lưu `rationale` (D-40) |
| Q-6-6 | Cache + k = 5 | Prompt `b14_*` để `cache: default`; estimator truyền `cache_policy="bypass"` khi `EVAL_MODE=false`; k = 5 = 5 lời gọi, mỗi lời có biến `sample_idx` (0…4) nằm trong thân prompt → khoá cache khác nhau (D-39) |
| Q-6-7 | B17 với AUTO do LLM | 6C: B17 chấp nhận "không luật khớp, chưa duyệt" chỉ khi `risk.decided_by=llm ∧ risk.route=AUTO ∧ action_plan_hash` (B12 đặt) = `hash_action(action)` (D-42) — xếp **sau T24** |
| Q-6-8 | `full_auto` | **[Chốt 10/10 — Tuấn Anh: C]** `decided_by = NULL` + `detail.strategy = "full_auto"` (mục 6.8). 6B trả tín hiệu `FullAutoBypass` |
| Q-6-9 | Tầng nghi thức | 6A: B · 6B: A · 6C: A · 6D: B |

---

## 3. Lỗ hổng xử lý trong Phase 6

Xem `claude/phase5-6-phan-tich-va-chia-chang.md` mục 2: **G6-1** (B17 → 6C), **G6-2** (cache → 6B), **G6-3** (k = 5 vs 7 → sửa chữ `huong-dan` khi đóng 6B), **G6-4** (một nguồn → 6A), **G6-5** (chưa hiệu chỉnh → 6B), **G6-6** (`rationale` → 6B), **G6-7** (`full_auto` → 6C).

---

## 4. Chặng 6A — `decision_math` + `calibrator` (tầng B)

**Mục tiêu:** toán quyết định và hiệu chỉnh thành **hàm thuần**, số kiểm bằng tay, dùng chung cho M5 (vận hành), T27, T29 (thực nghiệm).
**Đầu vào:** 4d commit. **Đầu ra:** 2 module mới + test; không node, không DB, không cấu hình.
**Nghi thức (tầng B):** PLAN ngắn trong MẪU A · 1 DỪNG · mutation 1 lượt · security-reviewer cuối chặng (chỉ phần `LeakageError` + import). **Model: Sonnet.**

### 4.1. P-x chốt trước

| Mã | Chốt |
|---|---|
| P1 | Hai file mới `backend/app/risk/decision_math.py`, `backend/app/risk/calibrator.py`. Chỉ import `numpy`, `scipy`, `sklearn`, `pydantic`, thư viện chuẩn, `app.core` (nếu cần lỗi chung). **Không** import `app.eval`, `app.graph`, `app.db`, `app.llm`, `app.api` |
| P2 | Tên route dùng đúng `RiskDecision.route`: `"AUTO" \| "HITL" \| "ESCALATE_L2"` |
| P3 | Mọi hàm kiểm đầu vào: rỗng, độ dài lệch, NaN/inf, p ∉ [0, 1], nhãn ∉ {0, 1, False, True}, route lạ, ngưỡng sai → `ValueError` (thông điệp nêu tên tham số, **không** in giá trị dữ liệu) |
| P4 | Ma trận chi phí mặc định = bảng 7.3 [Chốt, Q9 10:1] là **hằng trong code** (`DEFAULT_COST`) — không thêm khoá vào `policy.json` ở 6A |
| P5 | `ece` chia 10 bin đều; chỉ số bin `k = min(floor(round(p·n_bins, 9)), n_bins − 1)` — làm tròn 9 chữ số để `0,7 − 0,4 = 0,29999999999999993` vẫn vào bin 3; p = 1 vào bin cuối |
| P6 | Clopper–Pearson **một phía** 95 %: `beta.ppf(conf, k+1, n−k)`, `k = n` → 1,0 [Chốt P8 §6.1] |
| P7 | Quét lưới: `t_low, t_high ∈ {i/100 : i = 0…100}`, `t_high ≥ t_low`; tối thiểu theo khoá `(round(chi phí, 12), t_low, t_high)` → hoà thì chọn **t_low nhỏ nhất** (ít tự làm hơn — ưu tiên giảm FN), rồi t_high nhỏ nhất [Đề xuất] |
| P8 | Platt: `z = logit(clip(raw, eps, 1−eps))`, `eps = 1e-6`; hồi quy logistic **không phạt** trên `z`: `LogisticRegression(C=np.inf, tol=1e-10, max_iter=1000)` [Đã chạy thử trên 1.9.1 ngày 03/10: không cảnh báo; `penalty=None` sinh `FutureWarning` (bỏ ở 1.10) → **không dùng**; `tol` mặc định 1e-4 lệch nghiệm tới ~1e-4 → phải đặt `tol`]. Chạy test với cảnh báo = lỗi cho file này. Temperature: `T = argmin NLL(sigmoid(z/T))`, `scipy.optimize.minimize_scalar(method="bounded", bounds=(0.05, 20), options={"xatol": 1e-6})` |
| P9 | Calibrator lưu JSON có version ở thư mục truyền vào (mặc định `config/calibrators/`, **không** tạo file nào trong 6A ngoài thư mục tạm của test) |
| P10 | Test AST: không module nào trong `backend/app/risk/` import `app.eval` (D-37) — thay cho hợp đồng import-linter (file của Dương) |
| P11 | **`pyproject.toml` — thêm đúng một khối mypy** [Đã chạy thử 03/10]: chưa file nào trong repo import scipy/sklearn; hai gói này không có type stub → `make lint` (mypy) đỏ 4 lỗi `import-untyped` ngay khi 6A import. Thêm cuối mục mypy, theo tiền lệ `apscheduler`, `pyvi`: `[[tool.mypy.overrides]]` · `module = ["scipy.*", "sklearn.*"]` · `ignore_missing_imports = true` (kèm 1 dòng chú thích). Không đổi `dependencies`, **không đổi `uv.lock`** (`uv lock --check` vẫn đạt). Đây là thay đổi duy nhất ngoài 6 file mới. Hệ quả: `pyproject.toml` đổi → lần `make up` kế tiếp dựng lại lớp cài phụ thuộc của image (có cache, vài phút) |

### 4.2. API `decision_math.py` (hợp đồng cho T27, T29)

```python
type Route = Literal["AUTO", "HITL", "ESCALATE_L2"]
ROUTES: tuple[Route, ...] = ("AUTO", "HITL", "ESCALATE_L2")

class CostMatrix(BaseModel, frozen=True):          # costs[gold][pred], đơn vị = một lượt duyệt
    costs: Mapping[Route, Mapping[Route, float]]    # đủ 3×3, hữu hạn, ≥ 0 — thiếu ô → ValueError

DEFAULT_COST = CostMatrix(costs={                   # [Chốt 7.3, Q9]
    "AUTO":        {"AUTO": 0,  "HITL": 1, "ESCALATE_L2": 3},
    "HITL":        {"AUTO": 10, "HITL": 1, "ESCALATE_L2": 3},
    "ESCALATE_L2": {"AUTO": 20, "HITL": 6, "ESCALATE_L2": 3},
})

def cost_matrix_for_ratio(ratio: float) -> CostMatrix:
    """Độ nhạy tỉ lệ bỏ sót/duyệt ∈ {5, 10, 20} [Chốt]: HITL→AUTO = ratio; L2→AUTO = 2·ratio
    (giữ tỉ lệ 2:1 của bảng gốc); các ô khác như DEFAULT_COST. ratio = 10 → bằng DEFAULT_COST."""   # [Đề xuất]

def t_low_star(cost: CostMatrix = DEFAULT_COST) -> float:
    """t_low* = c_review / c_miss, c_review = cost[AUTO][HITL], c_miss = cost[HITL][AUTO] [Chốt B12 §5.2]."""

def route_for(p: float, t_low: float, t_high: float) -> Route:
    """p < t_low → AUTO; p > t_high → ESCALATE_L2; còn lại HITL (bằng ngưỡng = HITL).
    Ràng buộc 0 ≤ t_low ≤ t_high ≤ 1,01 (1,01 = bỏ đường LLM → L2, P8 §5.3)."""

def expected_cost(probs, golds, t_low, t_high, cost=DEFAULT_COST) -> float:   # trung bình cost[gold][route_for(p)]

class ThresholdChoice(BaseModel, frozen=True):
    t_low: float; t_high: float; expected_cost: float

def select_thresholds(probs, golds, cost=DEFAULT_COST) -> ThresholdChoice:   # P7

def sensitivity(probs, golds, ratios=(5, 10, 20)) -> dict[float, tuple[float, ThresholdChoice]]:
    """ratio → (t_low* của ratio, ngưỡng chọn với cost_matrix_for_ratio(ratio))."""

def clopper_pearson_upper(k: int, n: int, conf: float = 0.95) -> float:     # P6; n ≥ 1, 0 ≤ k ≤ n
def ece(probs, labels, n_bins: int = 10) -> float:                          # P5; labels: 1 = cần người
def brier(probs, labels) -> float:                                          # mean((p − y)²)
def auc(scores, labels) -> float:                                           # Mann–Whitney, hoà = 0,5; thiếu một lớp → ValueError
```

`probs`, `golds`, `labels` nhận `Sequence[float]` / `Sequence[Route]` / `Sequence[bool | int]` hoặc mảng numpy 1 chiều.

### 4.3. API `calibrator.py`

```python
class LeakageError(Exception):
    """Fit calibrator/chọn ngưỡng trên dữ liệu không thuộc split calibration [Chốt bất biến 10]."""

class LabeledSample(BaseModel, frozen=True, extra="forbid"):
    split: Literal["calibration", "test"]
    family: str                       # họ kịch bản (đơn vị chia tập)
    raw_prob: float                   # [0, 1], hữu hạn
    y: bool                           # True = gold ≠ AUTO ("cần người")

class FitInfo(BaseModel, frozen=True, extra="forbid"):
    split: Literal["calibration"]; n: int; n_pos: int; n_families: int; data_sha256: str

class CalibratorParams(BaseModel, frozen=True, extra="forbid"):
    version: str                      # ^(platt|temperature)-\d{8}-[0-9a-f]{8}$
    method: Literal["platt", "temperature"]
    a: float | None = None; b: float | None = None        # platt: cả hai bắt buộc
    temperature: float | None = None                      # temperature: bắt buộc, > 0
    eps: float = 1e-6
    fitted_on: FitInfo
    created_at: datetime

class Calibrator:                     # bất biến sau khi tạo
    params: CalibratorParams
    def transform(self, raw: float) -> float: ...         # raw ∉ [0,1]/NaN → ValueError; kết quả ∈ [0, 1]

def require_calibration_split(samples: Sequence[LabeledSample]) -> None
    # rỗng → ValueError; có mẫu split ≠ "calibration" → LeakageError (thông điệp: số mẫu sai split, KHÔNG in dữ liệu)
def fit_platt(samples, *, now: datetime) -> Calibrator
def fit_temperature(samples, *, now: datetime) -> Calibrator
    # cả hai: require_calibration_split TRƯỚC mọi tính toán; n < 10 hoặc chỉ một lớp y → ValueError
def save_calibrator(cal: Calibrator, directory: Path) -> Path      # <directory>/<version>.json, không ghi đè file đã có → FileExistsError
def load_calibrator(version: str, directory: Path) -> Calibrator   # version không khớp regex (kiểm TRƯỚC khi ghép đường dẫn) / tên file ≠ version / thiếu tham số theo method / khoá lạ → ValueError
```

- **Thứ tự chuẩn [Sửa 03/10 sau chạy thử]:** `fit_platt`/`fit_temperature` **sắp mẫu theo `(family, raw_prob, y)` trước khi tính** (sau `require_calibration_split`). Không sắp → cùng dữ liệu đảo thứ tự cho tham số lệch ở chữ số cuối (cộng số thực không giao hoán) → `version` khác → cb5 đỏ.
- `data_sha256` = sha256 của JSON chuẩn hoá (khoá sắp, không khoảng trắng) danh sách `[family, raw_prob, y]` **đã sắp** theo `(family, raw_prob, y)` → cùng dữ liệu (đổi thứ tự) → cùng hash.
- `version` = `f"{method}-{now:%Y%m%d}-{sha256(json(params_số) + data_sha256)[:8]}"` → tất định với cùng dữ liệu + cùng ngày.
- `now` truyền vào (không đọc đồng hồ trong hàm thuần).

### 4.4. File

```
backend/app/risk/decision_math.py                 # mới
backend/app/risk/calibrator.py                    # mới
backend/tests/unit/test_decision_math.py          # dm1–dm8 (8 test cổng 6) + dm9–dm12
backend/tests/unit/test_calibrator.py             # cb1–cb8
backend/tests/unit/test_risk_no_eval_import.py    # P10
scripts/mutation/mutate_6a.py                     # khuôn mutate_4c.py (không còn chữ MUTATION + mốc xanh trước)
pyproject.toml                                    # P11: 1 khối [[tool.mypy.overrides]] — không đụng dependencies/uv.lock
```

### 4.5. Dữ liệu tính tay dùng trong test

**Bộ H (10 ca, chi phí DEFAULT_COST):**

| # | p | gold | route ở (0,10; 0,75) | chi phí |
|---|---|---|---|---|
| 1 | 0,02 | AUTO | AUTO | 0 |
| 2 | 0,05 | AUTO | AUTO | 0 |
| 3 | 0,08 | AUTO | AUTO | 0 |
| 4 | 0,12 | HITL | HITL | 1 |
| 5 | 0,30 | AUTO | HITL | 1 |
| 6 | 0,45 | HITL | HITL | 1 |
| 7 | 0,60 | HITL | HITL | 1 |
| 8 | 0,80 | ESCALATE_L2 | ESCALATE_L2 | 3 |
| 9 | 0,90 | HITL | ESCALATE_L2 | 3 |
| 10 | 0,97 | ESCALATE_L2 | ESCALATE_L2 | 3 |
| | | | **trung bình** | **1,3** |

Ở (0,25; 0,75): ca 4 (0,12, HITL) thành AUTO → 10; tổng 22 → **2,2**. Quét lưới (P7): chi phí nhỏ nhất **1,3**, có **80** cặp hoà (t_low 0,09…0,12) → chọn **(0,09; 0,60)**.

**Đoạn sinh dữ liệu tổng hợp chuẩn (chép nguyên vào test — thứ tự lời gọi `rng` quyết định con số):**

```python
# dm9 (n = 20_000)
rng = np.random.default_rng(20260925)
p = rng.uniform(0, 1, n)
golds = ["HITL" if u < q else "AUTO" for u, q in zip(rng.uniform(0, 1, n), p)]

# cb2 (n = 5_000), cb3 (n = 40), cb5 (n = 200) — mỗi test tạo rng MỚI với cùng seed
rng = np.random.default_rng(20260925)
p_true = rng.uniform(0.02, 0.98, n)
y = rng.uniform(0, 1, n) < p_true
raw = scipy.special.expit(2 * scipy.special.logit(p_true))
samples = [LabeledSample(split="calibration", family=f"f{i % 50}", raw_prob=float(r), y=bool(v))
           for i, (r, v) in enumerate(zip(raw, y))]
```

Số đo trước bằng cài đặt tham chiếu (03/10, đúng bản thư viện đã khoá): dm9 → `t_low = 0,09`, `t_high = 1,00`, chi phí 0,94565, 0,06 s; cb2 → a = 0,486581, b = 0,011491, T = 2,055188, ECE 0,109665 → 0,011005 (Platt) / 0,012080 (temperature); bộ H `sensitivity` → cả 3 tỉ lệ đều chọn (0,09; 0,60), chi phí 1,3.

### 4.6. Test

**8 test `decision_math` của cổng 6 [Chốt cổng 6 — nội dung định nghĩa ở đây]:**

| # | Test | Đạt khi |
|---|---|---|
| **dm1** | `t_low_star` | DEFAULT → **0,1**; `cost_matrix_for_ratio(5/10/20)` → **0,2 / 0,1 / 0,05**; ratio 10 == DEFAULT_COST |
| **dm2** | `route_for` biên (t = 0,10/0,75) | 0,0999 → AUTO; **0,10 → HITL**; **0,75 → HITL**; 0,7501 → ESCALATE_L2; t_low = 0 và p = 0 → HITL; t_high = 1,01 và p = 1 → HITL; t_low > t_high → `ValueError` |
| **dm3** | `expected_cost` bộ H | (0,10; 0,75) → **1,3**; (0,25; 0,75) → **2,2** (sai số 1e-12) |
| **dm4** | `select_thresholds` bộ H | **(0,09; 0,60)**, chi phí **1,3**; `sensitivity` trả 3 khoá 5/10/20 kèm t_low* 0,2/0,1/0,05 |
| **dm5** | `clopper_pearson_upper` | 0/60 → **0,04870291331** (= 1 − 0,05^(1/60), sai số 1e-9); 1/20 → **0,21610616421**; 2/60 → **0,10123589492**; 60/60 → 1,0; n = 0 → `ValueError`; k > n → `ValueError` |
| **dm6** | `ece` | [0,05; 0,15; 0,15; 0,95] / [0,0,1,1] → **0,2**; [0,0; 0,1; 0,1; 0,95; 1,0] / [0,0,1,1,1] → **0,17**; **biên:** [`0.7 - 0.4`; 0,35] / [1, 0] → **0,175** (cùng bin 3 — không làm tròn sẽ ra 0,525) |
| **dm7** | `brier` | [0,05; 0,15; 0,15; 0,95] / [0,0,1,1] → **0,1875**; [0,0; 0,1; 0,1; 0,95; 1,0] / [0,0,1,1,1] → **0,1645** |
| **dm8** | `auc` | [0,1; 0,4; 0,35; 0,8] / [0,0,1,1] → **0,75**; có hoà [0,5; 0,5; 0,2; 0,9] / [1,0,0,1] → **0,875**; chỉ một lớp → `ValueError` |

**Test bổ sung (không tính vào 8):**

| # | Test | Đạt khi |
|---|---|---|
| dm9 | Ngưỡng dưới gần t_low* trên dữ liệu tổng hợp đã hiệu chỉnh [Chốt cổng 8] | `rng = np.random.default_rng(20260925)`, n = 20 000, `p ~ U(0,1)`, gold = HITL nếu `U(0,1) < p` còn lại AUTO (không có L2) → `select_thresholds(...).t_low` ∈ **[0,08; 0,12]** (đo trước: 0,09); chạy < 5 s |
| dm10 | Kiểm đầu vào (P3) | NaN, inf, p = 1,2, độ dài lệch, rỗng, gold `"L2"`, nhãn 2 → `ValueError`, thông điệp không chứa giá trị |
| dm11 | Thuộc tính (hypothesis) | `ece`, `brier` ∈ [0, 1]; `clopper_pearson_upper` tăng theo k, ≥ k/n; `route_for` đơn điệu theo p |
| dm12 | Hoà quét lưới | bộ H có đúng 80 cặp tối ưu; kết quả không đổi khi đảo thứ tự dữ liệu |
| cb1 | `LeakageError` | 99 mẫu calibration + 1 mẫu test → `LeakageError` (cả `fit_platt`, `fit_temperature`, `require_calibration_split`); thông điệp không chứa `raw_prob` |
| cb2 | Dữ liệu tổng hợp tự tin quá mức [Chốt cổng 8 "Platt giảm ECE"] | `rng = default_rng(20260925)`, n = 5 000, `p_true ~ U(0,02; 0,98)`, `y = U < p_true`, `raw = expit(2·logit(p_true))` → Platt **a ∈ [0,45; 0,53], b ∈ [−0,05; 0,05]** (đo trước 0,487 / 0,011); temperature **T ∈ [1,9; 2,2]** (đo 2,055); ECE sau < 0,03 **và** < ECE trước (đo trước 0,110 → sau 0,011/0,012) |
| cb3 | Đối chiếu tham chiếu độc lập | Dữ liệu **nhỏ n = 40** (cùng cách sinh cb2, `default_rng(20260925)` tạo mới, n = 40 → 21 ca dương): a, b của `fit_platt` so với cực tiểu NLL viết bằng `scipy.optimize.minimize` (BFGS, `gtol=1e-10`, viết trong test) chênh **≤ 1e-3** (đo trước: tham chiếu a = 0,510537, b = 0,277071; chênh < 1e-6). Phải dùng n nhỏ: ở n = 5 000 bản **có phạt mặc định** chỉ lệch 2e-4 → không giết được M-6A-7; ở n = 40 lệch 0,015 |
| cb4 | Số tính tay `transform` | Platt (a = 0,5; b = 0): raw 0,9 → **0,75**; raw 0,2 → **1/3**; Temperature T = 2: raw 0,9 → **0,75**; (a = 1; b = 0) và T = 1: raw = kết quả (trừ clip); raw 1,0 → < 1 và hữu hạn |
| cb5 | Lưu/nạp | `save` → `load` cùng `transform` trên 101 điểm; cùng dữ liệu đảo thứ tự → cùng `data_sha256` và `version` (**cả Platt lẫn temperature** — nhờ sắp mẫu trước khi fit, 4.3); đổi 1 mẫu → khác; `save` lần 2 cùng version → `FileExistsError` |
| cb6 | Kiểm đầu vào | n < 10, một lớp, raw NaN → `ValueError` |
| cb7 | File hỏng | platt thiếu `b`; khoá lạ; tên file ≠ version → `ValueError` |
| cb8 | AST (P10) | không file nào trong `app/risk/` import `app.eval`; `decision_math`, `calibrator` không import `app.graph/db/llm/api` |

### 4.7. Mutation (1 lượt, md5, `mutate_6a.py`)

| Mã | Phá | Test phải đỏ |
|---|---|---|
| M-6A-1 | `route_for`: `<` → `<=` | dm2 |
| M-6A-2 | `t_low_star` đảo thành c_miss/c_review | dm1 |
| M-6A-3 | CP hai phía (`conf` 0,975) | dm5 |
| M-6A-4 | `ece` bỏ làm tròn 9 chữ số | dm6 (biên) |
| M-6A-5 | Hoà chọn t_low lớn nhất | dm4, dm12 |
| M-6A-6 | `LeakageError` chỉ khi **mọi** mẫu là test | cb1 |
| M-6A-7 | Platt có phạt mặc định (`LogisticRegression()` — bỏ `C=np.inf`) | cb3 (n = 40: lệch a ≈ 0,015 > 1e-3) |
| M-6A-8 | `brier` dùng trị tuyệt đối | dm7 |
| M-6A-9 | `require_calibration_split` gọi **sau** khi fit | cb1 (đếm lời gọi fit = 0 bằng spy) |
| M-6A-10 | Bỏ bước sắp mẫu trước khi fit | cb5 (đảo thứ tự → `version` khác; đo trước: đỏ ở cả Platt và temperature với n = 200) |

### 4.8. DỪNG

**DỪNG duy nhất:** code + test + mutation + security-reviewer (bất biến: fit chỉ trên calibration; không rò dữ liệu vào thông điệp lỗi; `app.risk` không import `app.eval`). Lệnh: Tuấn Anh `! make verify G=0` **trong worktree** (lint + test, **không dùng stack**; mục 0.2). Đạt khi: lint xanh (mypy, import-linter 10/10), test xanh, mutation **10/10** đỏ đúng dự đoán. Agent **commit cục bộ** trên nhánh `m5-tuananh` (kèm file spec này) khi được bảo; push nhánh → CI → PR → gộp vào `dev-tuananh` do **phiên chat git** làm (phiếu, mục 0.2).

**Xác nhận:** **Dương** (~30 phút, trước khi bắt đầu T29) tính lại dm3–dm8 bằng tay/Excel và đọc chữ ký API 4.2–4.3 (đã đăng ở issue #32), ghi "đạt" hoặc chỗ lệch.

### 4.9. Spec cần sửa (6A) — agent in nguyên văn khi xong

Dạng tắt phạt `LogisticRegression` đã chọn (P8); mọi chỗ lệch 4.1–4.6; `huong-dan` §9 ("8 test đã có sẵn trong scaffold" → "định nghĩa ở phase6 4.6, hiện thực 6A"); P8 §2 (`stats.py`, `metrics.py` import từ `app.risk.decision_math`).

### 4.10. Chốt khi hiện thực (6A) — 09/10/2026, nhánh `m5-tuananh` trên `3ff63e1`

**Kết quả:** `make verify G=0` XANH (lint: ruff, mypy, import-linter 10/10, gitleaks 0; backend 4774 passed / 4 skipped gồm unit + integration + e2e testcontainers; unit riêng 4285 passed, +160 test 6A so với mốc 4125); mutation **12/12** đỏ đúng dự đoán; security-reviewer 2 vòng, 0 FAIL. Số đo trên Mac arm khớp số đo trước ở 4.5 (cb2 6 chữ số, cb3 lệch < 2e-8, dm9 0,03 s).

**Khác/thêm so với 4.1–4.7 (đã chốt khi duyệt):**
1. **Q-6A-1 = A:** nhãn float (kể cả 0.0/1.0) → `ValueError`; nhận ndarray dtype bool/int. `auc(scores)` chỉ đòi scores hữu hạn (không đòi ∈ [0, 1]).
2. **Q-6A-2 = A:** `CostMatrix.costs` sau kiểm là `MappingProxyType` lồng (sửa `DEFAULT_COST` → `TypeError`); `field_serializer` trả dict để `model_dump` không cảnh báo. Thêm `CostMatrix.matrix()` (mảng 3×3, nội bộ). `sensitivity` khoá `float(ratio)`.
3. **`select_thresholds`:** tìm cặp bằng numpy (`searchsorted` + đếm theo lớp, `lexsort` theo `(round(chi phí,12), t_low, t_high)`); `ThresholdChoice.expected_cost` của cặp thắng tính lại bằng `expected_cost()` (một nguồn ngữ nghĩa).
4. **Q-6A-3 = B:** `select_thresholds`/`sensitivity` không biết split — docstring ghi: chỉ truyền dữ liệu split calibration (P8 bất biến 10); **T27 `calibrate.py` tự gọi `require_calibration_split` trên `LabeledSample` trước khi tách mảng** (hợp đồng T27, đăng ở #32). Lý do không làm hàm bọc: `LabeledSample.y` nhị phân, `select_thresholds` cần gold 3 lớp.
5. **Q-6A-4 = A (chặn FN do hiệu chỉnh đảo chiều):** `CalibratorParams` đòi platt `a > 0`, temperature `T ∈ T_BOUNDS = [0,05; 20]` (đóng), `eps == EPS = 1e-6` (cả lúc dựng tay lẫn lúc nạp); `fit_platt` từ chối `a ≤ 0` ("đảo chiều hiệu chỉnh"), `fit_temperature` từ chối T cách biên < `T_EDGE = 1e-3`; `load_calibrator` tính lại đuôi 8 hex của `version` từ (params_số + eps) và `fitted_on.data_sha256` → lệch = `ValueError` "version không khớp tham số". **Đuôi băm 32 bit chỉ chống sửa nhầm, không phải chữ ký** — rào thật là quyền ghi `config/calibrators/` (review PR).
6. **`Calibrator(params)`** là frozen dataclass. `version`: params_số platt `{a, b, eps}`, temperature `{eps, temperature}`, JSON `sort_keys` + `separators=(",", ":")`; regex `[0-9]{8}` + `re.fullmatch`; `CalibratorParams` kiểm thêm tiền tố version = method, cấm tham số của method kia, `created_at`/`now` có múi giờ. Hằng công khai: `VERSION_PATTERN`, `EPS`, `MIN_SAMPLES`, `T_BOUNDS`, `T_EDGE`.
7. **Lỗi không rò dữ liệu:** mọi model pydantic `hide_input_in_errors=True`; `load_calibrator` đổi lỗi nội dung thành `ValueError` chỉ giữ vị trí + loại (`errors(include_input=False)`, `from None`); `version` phải đúng `str`; thiếu file → `FileNotFoundError`. `save_calibrator` mở `"x"`, không tạo thư mục. `fit_*` chụp `tuple(samples)` trước `require_calibration_split`.
8. **Test:** P10 mở rộng — `test_risk_no_eval_import.py` cấm **mọi import động** (`importlib`, `__import__`) trong `app/risk/**` (bộ dò `app.eval` lọt alias/`package=`/tên tính lúc chạy) → ràng buộc cả 6B/6C và T22a (đã báo P5, tin #5). Thêm cb9 (a–f) + `test_cb7_good_file_loads`; cb5 không ghi cứng hash/version (Mac arm vs CI x86 có thể lệch bit cuối); dm11 `@settings(derandomize=True, deadline=None)`.
9. **Mutation 4.7 thêm:** M-6A-11 bỏ so digest khi nạp → cb9a; M-6A-12 bỏ chặn `a ≤ 0` khi fit → cb9e (khớp chữ "đảo chiều" để không bị validator lớp hai che). Mong đợi **12/12**. M-6A-9 bắt bằng spy `LogisticRegression`/`minimize_scalar` cấp module.
10. **P11:** khối mypy đặt cuối `pyproject.toml`, sau khối `torch.*`.

**Để lại cho chặng sau:** (a) `model_construct`/`model_copy(update=…)` đi vòng validator — **6C** chỉ dựng `Calibrator` qua `load_calibrator` + test AST cấm hai lời gọi này trong `app/risk`; (b) `a ≈ 0⁺` (raw không mang thông tin) vẫn qua — **T27** thêm cổng độ phân biệt tối thiểu (đề xuất ở #32).

**Spec khác cần sửa (Phase 6 giữ):** `huong-dan` §9 "8 test đã có sẵn trong scaffold" → "định nghĩa ở phase6 4.6, hiện thực 6A (`test_decision_math.py` dm1–dm8)"; P8 §2 — `stats.py`, `metrics.py` import từ `app.risk.decision_math`, calibrator từ `app.risk.calibrator`.

---

## 5. Chặng 6B — estimator + logic chiến lược (tầng A)

**Mục tiêu:** lớp 2 của M5 chạy được **ở mức module**: từ `(Action, RiskContext, trích đoạn)` ra `raw_prob` + `factors`; từ (luật, ước lượng, calibrator, ngưỡng, chiến lược) ra `RiskDecision`. Chưa nối B12 (6C).
**Đầu vào:** 6A. **Đầu ra:** `LlmRiskEstimator`, 2 prompt, 2 schema, `FactorCode`, `strategy.py`, test.
**Nghi thức (tầng A):** `PLAN-6B.md` + MẪU A · 2 DỪNG · test-writer viết bảng 5.6 trước code · mutation ×2 + md5 · security-reviewer mỗi DỪNG. **Model: Opus.**
**Trước 6B:** nên chạy NỢ-3-2 (smoke LLM thật) — 6B viết thêm prompt.

### 5.1. P-x chốt trước

| Mã | Chốt |
|---|---|
| P1 | **Interface giữ tham số, đổi kiểu trả về:** `estimate(action: Action, ctx: RiskContext, retrieved: Sequence[ChunkRef]) -> RiskEstimate`, `RiskEstimate` (frozen dataclass): `raw_prob: float`, `p_method: PMethod`, `factors: tuple[FactorCode, ...]`, `prompt_id: str`, `prompt_version: str`, `model: str` (từ `LLMMeta`, cho lineage 6C). Cập nhật Protocol, `DisabledEstimator` (vẫn ném). [Soát `fe61fa3`] Không có estimator giả nào trong `backend/tests/fakes/`; `NodeDeps.estimator` mặc định `DisabledEstimator` nằm ở `backend/app/graph/fakes.py:48,323` (kiểu `RiskEstimator` — đổi kiểu trả về Protocol không buộc sửa file này). Estimator giả trả `RiskEstimate` cho test 6B: **file mới** `backend/tests/fakes/risk_estimator.py`. `b12_assess.py:83` gọi `deps.estimator.estimate(...)` — chỉ đổi chú thích kiểu nếu mypy đòi — **không** đổi logic B12 ở 6B |
| P2 | **Không bao giờ có câu người dùng [Chốt]:** biến prompt chỉ dựng từ `Action`, `RiskContext`, trích đoạn KB qua hàm thuần `estimator_vars(action, ctx, evidence) -> dict` trong `risk/estimator.py`. `allowed_vars` = `[intended_action, risk_context, evidence]` (`b14_risk_estimate`), thêm `sample_idx` (`b14_risk_vote`). Test d1b-tương tự trên **file thật**: tập `allowed_vars` ∩ {`redacted_request`, `conversation`, `slots`, `text`, `recent_messages`, `raw_request`} = ∅ |
| P3 | **`risk_context` render [Đề xuất]:** chỉ `{requester: {role, department, employment_status, tenure_days, is_privileged_account}, within_business_hours, target_is_other}` — **bỏ** `now`, `captured_at`, `user_id`, `manager_id`. Lý do: trường thay đổi theo thời gian làm khoá cache khác nhau mỗi lần chạy (phá tái lập thực nghiệm); định danh không giúp ước lượng. `intended_action` = `Action.model_dump(mode="json")` đầy đủ (gồm `facts`, `params`) |
| P4 | **Trích đoạn:** tối đa **3** chunk điểm cao nhất của `evidence_for_estimator` (B12 truyền vào); rỗng → biến `evidence` render "(không có)" (sẵn có của context builder). **Đổi hình dạng bắt buộc [soát code 03/10]:** renderer của gateway (`llm/context._evidence`) đòi mỗi khối có `anchor_chunk_id, title, heading_path, text, score`, còn `ChunkRef` chỉ có `chunk_id, …, excerpt` (≤ 600 ký tự) → `estimator_vars` phải ánh xạ `{anchor_chunk_id: chunk_id, title, heading_path, text: excerpt, score}`; truyền thẳng `ChunkRef` là `AttributeError` → E9. **Không** gọi `rag.expand_for_answer` (estimator không có cổng RAG; trích đoạn 600 ký tự đủ cho ước lượng) [Đề xuất] |
| P5 | **Tự nêu (`self_report`):** 1 lời gọi `llm.complete("strong", "b14_risk_estimate", vars, RiskEstimateOut, temperature=0.0, cache_policy=("default" if eval_mode else "bypass"))` — Q-6-6 |
| P6 | **Hỏi nhiều lần (`sampling_k5`):** 5 lời gọi `asyncio.gather` tới `b14_risk_vote` (`RiskVoteOut`), `temperature=0.7`, `sample_idx = 0…4` (biến xuất hiện **trong thân** prompt → khoá cache khác nhau), cùng `cache_policy` như P5; `p = số lần needs_human / 5`; `factors` = hợp các lần, sắp theo tần suất giảm rồi theo tên, tối đa 5. **Một lời gọi lỗi → cả ước lượng lỗi** (ném lỗi đó; không bao giờ tính p từ < 5 phiếu) |
| P7 | **Schema** (`llm/schemas.py`, chỉ **thêm** lớp + thêm 2 lớp vào dict `SCHEMAS` — registry tra tên schema ở đó): `RiskEstimateOut {prob_needs_human: float ∈ [0,1] (allow_inf_nan=False), factors: list[FactorCode] (≤ 5, không trùng), rationale: str (≤ 600)}`; `RiskVoteOut {needs_human: bool, factors: list[FactorCode] (≤ 3)}`. `rationale` **không** đi ra khỏi estimator (không vào `RiskEstimate`, audit, log) — Q-6-5 |
| P8 | **`FactorCode`** — `StrEnum` đóng đặt ở **`backend/app/domain/risk_factors.py`** [sửa 03/10: hợp đồng import-linter số 8 cấm `app.llm` import `app.risk`, mà `llm/schemas.py` cần `FactorCode`; `domain` là tầng cả hai được import]; `risk/factors.py` chỉ giữ `FACTOR_LABELS` (nhãn tiếng Việt) và import lại `FactorCode` từ domain. Mã + nhãn: `target_is_other` (tác động lên người/máy khác), `privileged_target` (tài khoản/quyền mức cao), `service_account` (tài khoản dịch vụ), `sensitive_data` (dữ liệu nhạy cảm), `cross_department` (tài nguyên phòng ban khác), `long_duration` (thời hạn dài), `irreversible` (khó hoàn tác), `outside_business_hours` (ngoài giờ hành chính), `new_employee` (nhân viên mới/thử việc), `account_status_abnormal` (tài khoản không ở trạng thái bình thường), `no_policy_evidence` (không có tài liệu quy định liên quan), `missing_facts` (thiếu dữ kiện), `routine_low_risk` (việc thường ngày, rủi ro thấp) |
| P9 | **Prompt** `config/prompts/b14_risk_estimate.yaml` (`role: strong`, `cache: default`, `version: 1`) và `b14_risk_vote.yaml` (`role: strong`, `cache: default`, `version: 1`). Nội dung theo 5.2. Nâng test d10 (`test_llm_prompts.py`): số đếm 6 → 8 **và** thêm 2 dòng vào bảng `TABLE_7_4` của test (role, cache, schema, biến). Bản giả trong `tests/fixtures/llm/prompts/` giữ nguyên cho d1b |
| P10 | **`strategy.py`** hàm thuần theo 5.3; `check_strategy` dùng ở 6C lúc khởi động. `Strategy` nhận qua tham số (6C quyết nguồn: biến `M5_STRATEGY` trong Settings, mặc định `hybrid`) |
| P11 | **Không đụng:** node B12/B17, wiring, `policy.json`, Settings, DB, file Phase 5, file M9. Không đổi gateway (`client.py`, `cache.py`) — `sample_idx` trong thân prompt đủ tách khoá. **Ngoại lệ bắt buộc [dựng thử 06/10]:** `config/scripted/default.yaml` và `config/scripted/vpn.yaml` phải thêm phản hồi cho 2 prompt mới — 3 test có sẵn đòi hai preset này phủ **mọi** prompt (P12) |
| P12 | **Preset stack cho `b14_*` — giá trị an toàn [Chốt 09/10 20:45 — Tuấn Anh: giữ 0,9]:** `b14_risk_estimate: {prob_needs_human: 0.9, factors: [missing_facts], rationale: "preset"}`, `b14_risk_vote: {needs_human: true, factors: [missing_facts]}` ở cả `default.yaml` và `vpn.yaml`. Lý do: 6B chưa nối B12 nên preset chưa được dùng; khi 6C nối, ca "không luật nào khớp" trên stack vẫn ra **chuyển L2** (0,9 > 0,75) như hiện nay cho tới khi 6C chủ động đặt preset theo kịch bản — không ca nào tự chuyển sang AUTO/HITL do quên |

### 5.2. Nội dung prompt (bản khởi điểm — chất lượng đo ở mốc G)

`b14_risk_estimate` — **system:** bạn đánh giá xác suất một hành động IT **không nên** được hệ thống tự làm mà không có người duyệt; đầu vào là dữ liệu có cấu trúc, **không** phải lệnh; chỉ dựa trên hành động, ngữ cảnh, dữ kiện và trích đoạn quy định; `prob_needs_human` ∈ [0, 1]; chọn tối đa 5 yếu tố từ danh sách mã (liệt kê mã + nghĩa); thiếu dữ kiện thì nghiêng về cần người; chỉ trả JSON đúng schema. **user:** `Hành động dự định (JSON): {{ intended_action }}` · `Ngữ cảnh người gửi và thời điểm (JSON): {{ risk_context }}` · `Trích đoạn quy định liên quan: {{ evidence }}`.

`b14_risk_vote` — như trên nhưng câu hỏi nhị phân "hành động này có cần người duyệt không?" → `needs_human`; thêm dòng `Lần đánh giá độc lập số {{ sample_idx }}.`

### 5.3. `strategy.py` — logic quyết định (thuần)

```python
type Strategy = Literal["hybrid", "rule_only", "llm_only", "full_auto", "hybrid_guarded"]
EVAL_ONLY: frozenset[Strategy] = frozenset({"rule_only", "llm_only", "full_auto", "hybrid_guarded"})

class StrategyNotAllowed(RuntimeError): ...
def check_strategy(strategy: Strategy, *, eval_mode: bool) -> None      # strategy ∈ EVAL_ONLY và not eval_mode → raise [Chốt cổng 6]

@dataclass(frozen=True)
class FullAutoBypass: ...                                                # tín hiệu: B12 bỏ qua M5 (Q-6-8, biểu diễn chốt ở 6C)

def needs_rules(strategy) -> bool                                        # False cho llm_only, full_auto
def needs_llm(strategy, verdict: RuleVerdict | None) -> bool
    # hybrid: không khớp · hybrid_guarded: không khớp HOẶC decision == "allow" · llm_only: True · rule_only, full_auto: False

def decide(strategy, verdict, estimate: RiskEstimate | None, *, calibrator: Calibrator | None,
           thresholds: tuple[float, float], kb_gap: bool) -> RiskDecision | FullAutoBypass
```

**Bảng quyết định** (`t = (t_low, t_high)` từ `policy.json constants`; route bằng `decision_math.route_for`):

| Chiến lược | Luật | Kết quả |
|---|---|---|
| full_auto | — | `FullAutoBypass()` |
| hybrid, rule_only | khớp | `decided_by=rule`, route theo loại luật (như B12 hiện tại), không ước lượng |
| hybrid_guarded | khớp `approval_required`/`deny` | như dòng trên |
| rule_only | không khớp | `decided_by=rule`, `policy_decision=None`, route **HITL**, reason "Không luật nào khớp → chờ duyệt (chỉ-luật)" [Chốt B12 §5] |
| hybrid (không khớp), llm_only, hybrid_guarded (không khớp) | — | **Đường LLM** (dưới) |
| hybrid_guarded | khớp `allow` | Đường LLM; `policy_decision="allow"`, `matched_rule_id` = luật allow; route = route LLM (sàn AUTO — LLM chỉ nâng) [Chốt 7.4] |

**Đường LLM** (`estimate` bắt buộc khác None, None → `ValueError` = bug):
1. `calibrator is None` → `calibrated_prob=None`; route = `ESCALATE_L2` nếu `raw > t_high`, còn lại **HITL** (D-38 — **không bao giờ AUTO**).
2. Có calibrator → `p = calibrator.transform(raw)`; route = `route_for(p, *t)`.
3. `kb_gap` và route = AUTO → **HITL** [Chốt D-34].
4. `RiskDecision(decided_by="llm", raw_prob=raw, calibrated_prob=p | None, p_method, route, risk_level = {AUTO: low, HITL: medium, ESCALATE_L2: high}[route], thresholds=t, reason=reason_text(...))`.

**Mẫu `reason`** (số dùng dấu phẩy, 2 chữ số; nhãn route: AUTO "tự xử lý", HITL "chờ người duyệt", ESCALATE_L2 "chuyển L2"; yếu tố = nhãn tiếng Việt nối "; ", rỗng → "(không nêu)"):
- Đã hiệu chỉnh: `Không luật nào khớp. Mô hình ước lượng xác suất cần người duyệt 0,42 (ngưỡng 0,10/0,75) → chờ người duyệt. Yếu tố: tác động lên người/máy khác; dữ liệu nhạy cảm.`
- Chưa hiệu chỉnh: `Không luật nào khớp. Mô hình ước lượng xác suất cần người duyệt 0,02 (chưa hiệu chỉnh — không tự xử lý) → chờ người duyệt. Yếu tố: …`
- Thêm khi bước 3 hạ AUTO → HITL: ` Không có tài liệu quy định đủ liên quan → tối đa chờ người duyệt.`
- `hybrid_guarded` + allow: tiền tố `Luật R11 cho phép; kiểm tra bổ sung bằng mô hình: ` + phần còn lại bắt đầu từ "Mô hình ước lượng…".

### 5.4. File

```
backend/app/risk/estimator.py           # RiskEstimate, LlmRiskEstimator, estimator_vars (+ giữ evidence_for_estimator, DisabledEstimator)
backend/app/domain/risk_factors.py      # FactorCode (mới — domain, vì llm/schemas.py cần import)
backend/app/risk/factors.py             # FACTOR_LABELS (mới; import FactorCode từ domain)
backend/app/risk/strategy.py            # mới
backend/app/llm/schemas.py              # + RiskEstimateOut, RiskVoteOut (chỉ thêm)
config/prompts/b14_risk_estimate.yaml   # mới
config/prompts/b14_risk_vote.yaml       # mới
config/scripted/default.yaml            # + 2 phản hồi b14_* (P12)
config/scripted/vpn.yaml                # + 2 phản hồi b14_* (P12)
backend/tests/fakes/…                   # estimator giả trả RiskEstimate
backend/tests/unit/test_risk_estimator.py   # es1–es9
backend/tests/unit/test_risk_strategy.py    # st1–st18
backend/tests/unit/test_llm_prompts.py      # d10: 2 test — `…exactly_six_prompt_files…` (6 → 8 + 2 dòng `TABLE_7_4`), `…schema_set_has_six_classes` (6 → 8)
scripts/mutation/mutate_6b.py
scripts/mutation/mutate_3h.py           # chỉ khi chuỗi gốc M-3h-9 (DisabledEstimator.estimate) đổi do P1 — giữ ý đột biến; test_mutation_n3 phải xanh
```

### 5.5. ScriptedLLM

Fixture phản hồi cho `b14_risk_estimate` (p, factors) và `b14_risk_vote`, có ca xấu: JSON sai một lần rồi đúng, `prob_needs_human = 1.2`, `NaN`, mã yếu tố lạ, timeout, 429 (P2 mục 9–10). **Fixture `Action` cho cả 4 intent** (vpn renew, account reset, software install, access grant) — dựng bằng `Action(...)` trực tiếp (không cần `build_action` 4 intent của T20). **Lưu ý ScriptedLLM [soát code 03/10]:** kịch bản dạng danh sách bị rút **theo thứ tự lời gọi tới**, không theo `sample_idx` — với `asyncio.gather` thứ tự không được coi là cố định → test es4/es5 không được phụ thuộc "phiếu nào ứng với idx nào"; cần gắn theo idx thì dùng kịch bản dạng **hàm** (`script(req.variables)` — provider đã hỗ trợ).

### 5.6. Test (test-writer viết TRƯỚC code)

| # | Test | Đạt khi |
|---|---|---|
| es1 | Tự nêu | 1 lời gọi `b14_risk_estimate`, role strong, `temperature=0.0`; `cache_policy="bypass"` khi `eval_mode=False`, `"default"` khi True — **kiểm tham số bằng `LlmPort` giả ghi lại lời gọi** (`CallRecord` của ScriptedLLM không có `temperature`/`cache_policy`); trả `RiskEstimate(0.42, "self_report", factors, prompt_id, prompt_version, model)`. Thêm qua gateway thật: `eval_mode=False` → 0 dòng cache; `eval_mode=True` + `cache_mode="eval"` → lần gọi 2 không tới provider |
| es2 | Biến prompt | khoá của `estimator_vars` = đúng `allowed_vars`; `intended_action` có `type`, `facts`, `params`; **`risk_context` không có khoá `now`, `captured_at`, `user_id`, `manager_id`** (kiểm trên dict — không kiểm trên chuỗi render vì `Action.requested_for`/`target` hợp lệ chứa mã người); ≤ 3 trích đoạn, đúng 3 điểm cao nhất, mỗi khối đủ 5 khoá của P4; rỗng → render "(không có)" |
| es3 | 4 intent | Action vpn/account/software/access → render được, mỗi cái đúng 1 lời gọi |
| es4 | k = 5 | 5 lời gọi `b14_risk_vote`, `temperature=0.7`, 5 bản render **khác nhau** (khác `sample_idx`) → tính `llm.cache.cache_key` cho 5 bản → **5 khoá khác nhau**; phiếu [T, T, F, T, F] → **0,6**; `factors` hợp đúng thứ tự P6 |
| es5 | k = 5, một lời gọi lỗi | `LLMUnavailable` ở lời gọi thứ 3 → `estimate` ném `LLMUnavailable` (không trả p) |
| es6 | Schema xấu | 1,2 / NaN / mã yếu tố lạ (sau retry của gateway) → ném `LLMSchemaError` |
| es7 | Whitelist trên file thật (P2) | 2 prompt thật: `allowed_vars` ∩ tập cấm = ∅; `cache: default`; `role: strong` |
| es8 | AST | `risk/estimator.py`, `risk/strategy.py`, `risk/factors.py` không tham chiếu `state`, `redacted_request`, `conversation`, `slots`; không import `app.graph`, `app.api`, `app.guard` |
| es10 | Lời gọi LLM tĩnh trong `risk/` | [Thêm 09/10 — test d10 `test_d10_node_llm_calls_match_prompt_files` chỉ quét `graph/nodes/`, không thấy lời gọi trong `risk/estimator.py`] dùng lại `llm_call_sites`/`site_errors` của `test_llm_prompts.py` trên `backend/app/risk/*.py`: đúng 2 lời gọi (`b14_risk_estimate`, `b14_risk_vote`), role + schema khớp registry; biến không phải dict literal → kiểm biến bằng es2 (khoá `estimator_vars` = `allowed_vars`) thay cho phần kiểm biến của `site_errors` |
| es9 | `rationale` không thoát | `RiskEstimate` không có trường chứa `rationale`; chuỗi canary đặt trong `rationale` của phản hồi giả không xuất hiện trong `repr(RiskEstimate)` và log bắt được (`caplog`) |
| st1 | hybrid + allow | `needs_llm=False`; `decided_by=rule`, AUTO |
| st2 | hybrid + approval_required | rule, HITL |
| st3 | hybrid + deny | rule, ESCALATE_L2 |
| st4 | hybrid, không khớp, calibrator (a=1,b=0 ≈ identity), p 0,05, t (0,10; 0,75) | llm, **AUTO**, `calibrated_prob` ≈ 0,05 |
| st5 | như st4 + `kb_gap=True` | **HITL**, reason có câu "Không có tài liệu quy định đủ liên quan…" |
| st6 | biên | p 0,10 → HITL; 0,75 → HITL; 0,50 → HITL; 0,90 → ESCALATE_L2 |
| st7 | chưa hiệu chỉnh | raw 0,01 → **HITL**; raw 0,80 → ESCALATE_L2; `calibrated_prob=None`; reason có "chưa hiệu chỉnh" |
| st8 | rule_only không khớp | rule, `policy_decision=None`, HITL, reason đúng chữ [Chốt] |
| st9 | rule_only + allow | rule, AUTO |
| st10 | llm_only | `needs_rules=False`; `decide(verdict=None)` → đường LLM |
| st11 | hybrid_guarded + allow + p 0,05 (có calibrator) | llm, AUTO, `policy_decision="allow"`, `matched_rule_id="R11"`, reason có tiền tố "Luật R11 cho phép" |
| st12 | hybrid_guarded + allow + p 0,5 | HITL (LLM nâng mức) |
| st13 | hybrid_guarded + approval_required | rule, HITL, `needs_llm=False` |
| st14 | full_auto | `FullAutoBypass`; `needs_rules=needs_llm=False` |
| st15 | `check_strategy` | `eval_mode=False`: 4 chiến lược `EVAL_ONLY` → `StrategyNotAllowed`, `hybrid` qua; `eval_mode=True`: cả 5 qua |
| st16 | Đường LLM thiếu `estimate` | `ValueError` |
| st17 | Chữ `reason` | 4 mẫu 5.3 khớp **từng ký tự** với chuỗi viết tay trong test |
| st18 | Trường `RiskDecision` | đường LLM: `raw_prob`, `p_method`, `thresholds` có; đường luật: `raw_prob=None`, `p_method=None` |

### 5.7. Mutation bắt buộc (2 lượt, md5)

| Mã | Phá | Test phải đỏ |
|---|---|---|
| M-6B-1 | Luôn `cache_policy="default"` | es1 |
| M-6B-2 | Bỏ `sample_idx` khỏi biến | es4 (khoá trùng) |
| M-6B-3 | k = 5 bỏ qua lời gọi lỗi, tính p trên phần còn lại | es5 |
| M-6B-4 | Chưa hiệu chỉnh vẫn so `t_low` (cho AUTO) | st7 |
| M-6B-5 | Bỏ bước `kb_gap` | st5 |
| M-6B-6 | `check_strategy` cho `llm_only` khi không eval | st15 |
| M-6B-7 | Thêm `redacted_request` vào `allowed_vars` (+ biến trong thân) | es7 |
| M-6B-8 | `risk_context` gồm `now` | es2 |
| M-6B-9 | hybrid_guarded gọi LLM cả khi luật `approval_required` | st13 |

### 5.8. Soát bảo mật (security-reviewer, mỗi DỪNG)

(1) Không đường nào đưa câu người dùng vào prompt B14 (chữ ký, `estimator_vars`, `allowed_vars`, AST); (2) lỗi/thiếu ước lượng không bao giờ ra AUTO; (3) chưa hiệu chỉnh không bao giờ ra AUTO; (4) `kb_gap` chặn AUTO; (5) vận hành không cache B14 (`bypass` khi không eval); (6) `rationale` không vào audit/log; (7) chiến lược so sánh bị chặn khi không eval.

### 5.9. DỪNG

- **DỪNG 1:** P1–P9 (estimator, schema, factors, prompt, fixture) + test es1–es9 (đỏ trước). `make verify G=0`.
- **DỪNG 2:** P10 (`strategy.py`) + st1–st18 + mutation ×2 + security-reviewer + "spec cần sửa (6B)". Trong worktree: `make verify G=0`. Lượt có cổng `make verify G=234` (backend thật nạp 8 prompt lúc khởi động) chạy **sau khi phiên git gộp** PR 6B — gửi phiếu "dùng stack" cho phiên git (nơi chạy và lúc chạy do phiên git xếp theo luật 4.1, 4.8; mục 0.2).
- **Xác nhận:** Duy Anh chạy `make verify G=0` trên máy mình + đọc bảng es7/es8 (không mở `policy.json`).

**Đã dựng thử 06/10 trên bản sao sạch (cùng code với `632e05a`):** `FactorCode` ở domain + 2 schema + 2 prompt + `LlmRiskEstimator` + bảng quyết định 5.3. Kết quả: registry nạp 8 prompt; preset stack nạp được; import-linter 10/10; mypy sạch; qua **gateway thật + ScriptedLLM**: es1 (0,42), es2 (3 khối điểm cao nhất, không lộ `now`), es4 (5 lời gọi, 5 bản render khác nhau, p = 0,6, thứ tự yếu tố đúng), es5 (ném `LLMUnavailable`), es6 (1,2 / mã lạ / NaN → `LLMSchemaError` sau 1 lần sửa), es9 (canary không vào `repr`), bằng chứng rỗng → "(không có)"; 15 phép kiểm st1–st14, st17 đúng, 3 mẫu `reason` khớp từng ký tự. **Test có sẵn bị đỏ khi thêm 2 prompt (5 cái — agent phải xử lý, không phải hồi quy):** `test_llm_prompts` ×2 (sửa số đếm, bảng), và 3 test đòi preset phủ mọi prompt — `test_b03_classify::test_stack_vpn_preset_covers_all_prompts_and_routes_vpn`, `test_llm_client::test_smoke_check_llm_scripted_loads_presets`, `test_llm_scripted::test_d19_repo_default_preset_covers_all_prompts_and_validates` (tự xanh khi làm P12). Ca chưa nêu trong bảng, hành vi đã kiểm: `hybrid_guarded` + allow + chưa hiệu chỉnh → HITL; `hybrid_guarded` + allow + `kb_gap` → HITL (đúng D-38, D-34). Chưa dựng thử: test AST es7/es8, mutation, `tests/fakes` estimator giả.

### 5.10. Spec cần sửa (6B)

`huong-dan` §7.2, §14.2, §15.1: "hỏi 7 lần" → k = 5 (G6-3); B12 §5 (kiểu trả về `RiskEstimate`, đường chưa hiệu chỉnh, `reason` theo mẫu); P2 §7 (`b14_*` `cache: default` + `bypass` khi vận hành, `sample_idx`).

### 5.11. Chốt khi hiện thực (6B) — 10/10/2026, `m5-tuananh` trên `2ffb005`: `d8e3cbe` (DỪNG 1) + `6fda378` (DỪNG 2)

**Kết quả:** `make verify G=0` XANH cả 2 DỪNG (DỪNG 2: backend 4988 passed / 4 skipped, mock 106, ml 77; unit 4499 = mốc 4394 + 105 test 6B); lint xanh (import-linter 10/10, gitleaks 0); mutation lượt 1 5/5, lượt 2 **9/9** đỏ đúng dự đoán; security-reviewer 2 lần, 0 FAIL. `mutate_3h.py` không phải sửa (dòng raise của `DisabledEstimator` giữ nguyên; M-3h-9 vẫn đỏ đúng).

**Khác/thêm so với 5.1–5.7 (đã duyệt):**
1. **5.9:** test có sẵn đỏ khi thêm 2 prompt là **7** (thêm `test_gate3.py:370`, `test_gate4.py:65` — đòi mọi preset kịch bản đủ khoá). **P11/P12 + 5.4:** preset `b14_*` ở **13 file** `config/scripted/` (Q-6B-5 = A), không sửa test.
2. **st6:** ca biên lấy ngưỡng = `cal.transform(0.10)`, `cal.transform(0.75)` (Platt a=1, b=0) — ổn định giữa Mac arm và CI x86.
3. **P1:** `LlmRiskEstimator(llm, *, p_method, eval_mode)` — 2 tham số khoá bắt buộc. `test_s0_grounding.py` đổi chú thích kiểu `RecordingEstimator.estimate` (Q-6B-2). "6" → "8" ở `config/prompts/README.md`, `test_llm_client.py` (Q-6B-3).
4. **P6:** mỗi mã yếu tố đếm tối đa 1 lần/phiếu; k = 5 chờ đủ 5 lời gọi (`gather(return_exceptions=True)`) rồi ném lỗi của `sample_idx` nhỏ nhất (không `TaskGroup` — `ExceptionGroup` làm B12 bắt trượt → E9).
5. **5.3:** đường chưa hiệu chỉnh dùng `route_for(raw)` rồi hạ AUTO → HITL (tương đương bảng); `strategy._ROUTE/_LEVEL` chép từ B12 + test so khớp; verdict mâu thuẫn (không khớp mà có decision/rule_id) và chiến lược lạ → `ValueError`; raw NaN/inf/ngoài [0,1], ngưỡng ngược → `ValueError`.
6. **5.7:** M-6B-2 áp dạng `sample_idx` hằng 0 (bỏ hẳn biến thì gateway ném lỗi biến — không chứng minh khoá trùng).
7. Test: es1–es10, st1–st18, tq (TQ-4, TQ-5, TQ-14, 13 mã trong prompt, `FACTOR_LABELS` đủ 13) + 25 test bổ sung ở DỪNG 2 (4 đường LLM × chưa hiệu chỉnh/kb_gap, đầu vào xấu, calibrator ném lỗi).

**Nợ chuyển 6C (bắt buộc — thêm vào phạm vi mục 6):**
- **N1 (Q-6B-6):** `intended_action` = `Action.model_dump` đầy đủ → `Action.params` có giá trị lấy từ câu người dùng (`software_name` cho chữ + dấu cách) vào prompt B14. **CHẶN:** không nối B12 → estimator cho intent software/access khi chưa có danh sách trắng `params` theo `action_type` + mẫu chặt trong `estimator_vars` + test canary trong giá trị slot. (Bật intent ở T24 vẫn an toàn — `DisabledEstimator` → E5.) Danh sách khoá `params` lấy từ T20a DỪNG 1. *[13/10 — đã nhận bản spec từ Phase 5 (tin P5 #8): `PARAMS_BY_ACTION` ở `domain/action.py`; `software_name` chuẩn hoá `^[a-z0-9][a-z0-9.+#-]{0,63}$` (không dấu cách nhưng vẫn ghép được chữ bằng `-`), `resource_path` cũng cho chữ. **[Đề xuất cho 6C, chốt khi viết spec 6C]:** `estimator_vars` chỉ đưa vào `intended_action.params` các khoá giá trị đóng/mẫu chặt không mang chữ tự do — `device_id`, `account_type`, `permission_level`, `duration_days`; **bỏ** `software_name`, `resource_path` (thông tin rủi ro của chúng đã có ở fact: `in_catalog`, `license_paid`, `requires_local_admin`, `resource_sensitivity`, `same_department`) + test canary đặt chuỗi lệnh trong 2 slot này. **[13/10 — bổ sung sau tin P5 #9, `03b4450`]:** chữ người dùng còn lọt qua 2 trường **ngoài** `params`: `Action.target` = `folder:{resource_path}` (access) và `Action.requested_for` = `target_user` (mẫu `^[a-z0-9_]{3,64}$` — ghép chữ bằng `_`). → danh sách trắng N1 phải phủ **cả** `target`, `requested_for`: chỉ giữ `target` dạng `device:<id>` (mẫu chặt); `folder:`/`user:` thay bằng loại đích (`folder`/`user`); `requested_for` bỏ (đã có `ctx.target_is_other`). Test canary đặt chuỗi lệnh ở `software_name`, `resource_path`, `target_user`.]*
- **N2:** `eval_mode` của estimator và của gateway lấy cùng một nguồn Settings.
- **N3:** cache eval lưu cả `rationale` (hành vi gateway sẵn có) — ghi nhận, không sửa.
- **N4:** gateway cắt hết bằng chứng (`trimmed_evidence`) mà `kb_gap` không biết → 6C tính `kb_gap` sau khi biết phần bằng chứng thực gửi.
- **N5:** `check_strategy` chạy ở `open_runtime` cho **cả API lẫn worker**, test cả 2 tiến trình (quên → `full_auto` bỏ M5, `llm_only` bỏ `deny`).
- **N6:** preset P12 0,9 chỉ "luôn L2" khi **chưa** hiệu chỉnh (Platt a=1, b=−4 đưa 0,9 → ~0,14 → AUTO) → 6C đặt preset `b14_*` theo từng kịch bản, không dựa vào 0,9 làm lưới an toàn khi đã có calibrator.

**Spec khác cần sửa (Phase 6 giữ):** `huong-dan` §7.2, §14.2, §15.1 "hỏi 7 lần" → k = 5 (G6-3); B12 §5 (kiểu trả về `RiskEstimate`, đường chưa hiệu chỉnh không AUTO, `reason` theo mẫu 5.3); P2 §7 (`b14_*` `cache: default` + `bypass` khi vận hành, `sample_idx` trong thân prompt); mục 0.1: d10 đếm 8 file.

---

## 6. Chặng 6C — nối lớp 2 vào B12 + B17 (tầng A, Opus, 2 DỪNG)

**Mục tiêu:** ca "không luật nào khớp" đi lớp LLM thật trong graph: estimator → strategy → route → điểm log 4 + lineage; B17 nhận AUTO do LLM (D-42); `full_auto` theo Q-6-8 = C; đóng nợ N1–N6 của 6B. Đây là phần **tự động của cổng 6**.
**Đầu vào [Chốt 13/10]:** 6B (`d42d5c4`) + T24 (`457239d` — chặng cuối sửa `b17_execute.py`, G6-1) + Q-6-8 = C. Code nền soát tại `457239d` (13/10).
**Nghi thức (tầng A):** `PLAN-6C.md` + MẪU A · 2 DỪNG · test-writer viết bảng 6.4 trước code · mutation ×2 + md5 · security-reviewer mỗi DỪNG. **Model: Opus.**

### 6.0. Sự thật code tại `457239d` (13/10)

| Chỗ | Hiện có | 6C làm |
|---|---|---|
| `graph/nodes/b12_assess.py:79-95` | Không luật khớp → `evidence_for_estimator` → `deps.estimator.estimate(...)` (bỏ kết quả); lỗi LLM → E5 `llm_layer_disabled`; estimator trả số → `RuntimeError` (E9) | Thay bằng `strategy.needs_llm/decide` (6.1 P3) |
| `b12_assess.py:35-48` | `_ROUTE`, `_LEVEL`, `_POINT4` (đã có `raw_prob`, `p_method`) | Giữ; `_point4` thêm khoá 6.1 P5 |
| `graph/fakes.py:323` | `NodeDeps.estimator = DisabledEstimator()` mặc định | Thêm `calibrator`, `strategy` vào `NodeDeps` (mặc định an toàn: `None`, `"hybrid"`) |
| `graph/wiring.py:134` `open_runtime` | Chuỗi kiểm **trước DB** (`check_llm`, `check_guard`, `check_intent_config`, `check_policy_config`, `check_plans`, approvers); gọi từ **cả** `main.py:102` lẫn `worker.py` | Thêm `check_strategy` + nạp calibrator vào chuỗi này (N5) |
| `wiring.py:221` `NodeDeps(...)` | Không truyền estimator | Dựng `LlmRiskEstimator(llm, p_method=…, eval_mode=settings.eval_mode)` (N2) |
| `settings.py:370` `PolicyFile` | `constants` (`THRESHOLD_LOW/HIGH` 0,25/0,75 có kiểm low < high) | Thêm khối `m5` (6.1 P2) |
| `b17_execute.py:161` | `not approved and (approval_required or not matched)` → E5 `recheck_failed` (comment dòng 11: "Phase 3 không có lớp LLM ở đây") | Ngoại lệ D-42 (6.1 P6) |
| `audit/check.py:124` | Điểm 4 bắt buộc `decided_by`, `policy_decision`, `risk_level`, `reason`, `detail.route`, `detail.policy_sha256` | Nới theo `decided_by` (6.1 P7) |
| `db/models.py:518` `Lineage` | Có cột `prompt_id`, `prompt_version`, `model`, `calibrator_version`, `p_method` | Ghi đủ ở ca LLM (6.1 P5) — **không migration** |
| `llm/ports.py:38` `LLMMeta.trimmed_evidence` | Gateway đếm khối bằng chứng bị cắt | Dùng cho N4 (6.1 P9) |
| `llm_layer_disabled` | Có trong `test_b12_assess`, `test_gate3_vpn` (:182, :196, :335, :424), `test_s0_grounding`, `test_audit_check`, `test_final_handoff`, `test_hrule_4b_owner`, `test_policy_rules_vpn`, `test_chain_t20a`, `test_b02_screen`, seed M9 (`monitor_*seed.py`), `mutate_3h.py` | Giữ mã này cho **lỗi estimator**; ca LLM chuyển L2 dùng mã mới (6.1 P3) → danh sách test đổi kỳ vọng ở PLAN (6.3) |
| `config/scripted/` | 22 file, đều có `b14_*` = 0,9 / `needs_human: true` (P12 6B) | Giữ; ca e2e cần route khác đặt preset riêng (N6) |

### 6.1. P-x chốt trước

| Mã | Chốt |
|---|---|
| P1 | **Chiến lược:** Settings `m5_strategy: Strategy = "hybrid"` (env `M5_STRATEGY`). `open_runtime` gọi `check_strategy(settings.m5_strategy, eval_mode=settings.eval_mode)` **trước DB**, cạnh `check_policy_config` → chạy ở **cả API lẫn worker** (N5). Test: dựng runtime cho từng tiến trình với `M5_STRATEGY=llm_only`, `EVAL_MODE=false` → không khởi động |
| P2 | **`policy.json` khối `m5`** (khối riêng, không đụng `rules`/`constants` của Phase 5): `{"p_method": "self_report", "calibrator_version": null}`; `PolicyFile.m5: M5Config` (`p_method: PMethod`, `calibrator_version: str \| None` — có thì phải khớp `VERSION_PATTERN`). Ngưỡng vẫn đọc `constants.THRESHOLD_LOW/HIGH` (chưa đổi giá trị — T37 chọn) |
| P3 | **B12 sau luật:** `needs_rules`/`needs_llm` theo `deps.strategy`; đường LLM: `evidence = evidence_for_estimator(...)` → `est = await deps.estimator.estimate(action, ctx, evidence)` → `kb_gap` (P9) → `strategy.decide(...)`. Đích: AUTO → `S_EXECUTING`/B17 **và** đặt `action_plan_hash = hash_action(action)` trong state (D-42); HITL → B15; ESCALATE_L2 → E5, `escalation_reason_detail="llm_high_risk"`, `event="risk_decided"`. Lỗi estimator (`LLMUnavailable`, `LLMSchemaError`, `LLMBudgetExceeded`) giữ nguyên nhánh E5 `llm_layer_disabled`. **Bỏ** `RuntimeError` dòng 95. `rule_only` + không khớp → HITL theo `decide` |
| P4 | **`full_auto` (Q-6-8 = C):** `decide` trả `FullAutoBypass` → không dựng `RiskDecision`; điểm log 4 `decided_by=NULL`, `detail={strategy:"full_auto", route:"AUTO", policy_sha256}`; `risk=None`; `goto S_EXECUTING`. B17 giữ kiểm lại luật (ca `approval_required`/`deny` → E5 ở B17). Chỉ tới được khi `check_strategy` đã cho qua |
| P5 | **Điểm log 4 + lineage (ca LLM):** `detail` thêm `calibrated_prob`, `thresholds`, `factors` (mã), `kb_gap`, `calibrator_version`, `strategy` (**chỉ khi** `EVAL_MODE`). `lineage` thêm `prompt_id`, `prompt_version`, `model` (từ `RiskEstimate`), `calibrator_version`, `p_method`. Không lưu `rationale` (D-40). Báo Dương (M9): mã mới `llm_high_risk`, khoá `detail` mới |
| P6 | **B17 (D-42):** ở dòng 161, ca **không** qua duyệt và `not verdict.matched` được đi tiếp **chỉ khi** `risk.decided_by == "llm"` ∧ `risk.route == "AUTO"` ∧ `state.action_plan_hash == hash_action(action)`; ngược lại giữ E5 `recheck_failed`. Kiểm lại luật vẫn chạy **trước** (luật mới `deny`/`approval_required` → E5). Ca `hybrid_guarded` + allow: luật khớp allow → đường cũ. Kiểm người (D-15) giữ nguyên |
| P7 | **`audit_check` điểm 4:** `decided_by="rule"` → như cũ; `decided_by="llm"` → bắt buộc `risk_level`, `reason`, `detail.route`, `detail.policy_sha256`, `raw_prob`, `p_method`, `detail.thresholds` (không đòi `policy_decision`); `decided_by` NULL **chỉ** hợp lệ khi `detail.strategy == "full_auto"` ∧ `detail.route == "AUTO"` — NULL không ghi chú → thiếu trường (Q-6-8 điều kiện 1) |
| P8 | **N1 — danh sách trắng trong `estimator_vars`:** `intended_action` render **không** còn `Action.model_dump` đầy đủ: `params` chỉ giữ `device_id`, `account_type`, `permission_level`, `duration_days` (bỏ `software_name`, `resource_path`); `target` chỉ giữ nguyên khi dạng `device:<id>` khớp `^device:[A-Z]{2,4}-\d{3,5}$`, còn lại thay bằng loại đích (`folder`, `user`); **bỏ** `requested_for` (đã có `ctx.target_is_other`). Nguồn khoá: `domain/action.PARAMS_BY_ACTION` (T20a). Sửa es2 của 6B cho khớp (ghi MẪU B) |
| P9 | **N4 — `kb_gap`:** `kb_gap = (evidence == []) or (len(evidence) - est.evidence_trimmed <= 0)`; `RiskEstimate` thêm `evidence_trimmed: int` = `LLMMeta.trimmed_evidence` (k = 5: lấy **max** trong 5 phiếu) |
| P10 | **Calibrator:** nạp **chỉ** qua `load_calibrator(version, settings.config_dir / "calibrators")` khi `m5.calibrator_version` khác null; null → `None` → D-38 (không AUTO). File lỗi/thiếu → không khởi động. Test AST: không `model_construct`/`model_copy(update=` trong `app/risk/**` (nợ 6A) |
| P11 | **N6 — preset:** giữ 0,9 ở 22 file (stack không có calibrator → L2). Ca e2e cần HITL/AUTO dựng gateway + ScriptedLLM với kịch bản riêng (và calibrator tạm trong `tmp_path` cho ca AUTO) — **không** sửa preset dùng chung |
| P12 | **Không đụng:** `rules`/`constants` của `policy.json`, `llm/client.py`, `llm/cache.py`, migration, file M9 (`app/monitor/*`, `.importlinter`), `config/approvers.yaml`, B15/B16 (trừ khi test chỉ ra cần — DỪNG hỏi) |

### 6.2. File

```
backend/app/settings.py                  # m5_strategy; PolicyFile.m5 (M5Config)
config/policy.json                       # + khối "m5" (không đụng rules/constants)
backend/app/graph/fakes.py               # NodeDeps + calibrator, strategy (mặc định an toàn)
backend/app/graph/wiring.py              # check_strategy + nạp calibrator trước DB; LlmRiskEstimator vào NodeDeps
backend/app/graph/nodes/b12_assess.py    # P3–P5, P9
backend/app/graph/nodes/b17_execute.py   # P6
backend/app/audit/check.py               # P7
backend/app/risk/estimator.py            # P8 (estimator_vars), P9 (evidence_trimmed)
backend/tests/…                          # bảng 6.4 + test cũ đổi kỳ vọng (6.3)
scripts/mutation/mutate_6c.py            # 6.5; đồng bộ mutate_3h/4a/4b/4d nếu chuỗi gốc đổi (test_mutation_n3 xanh)
```

### 6.3. Hồi quy (PLAN-6C phải liệt kê **từng** test + lý do)

Ca "không luật nào khớp" trên stack/ScriptedLLM nay đi estimator thật: preset 0,9, chưa hiệu chỉnh → **E5 `llm_high_risk`** (vẫn E5, 0 phiếu, 0 lời gọi ghi) thay cho E5 `llm_layer_disabled`. Kỳ vọng đổi **mã chi tiết + event**, không đổi đích. Test dùng `DisabledEstimator` tường minh (unit) giữ nguyên. Danh sách ứng viên ở 6.0 (hàng `llm_layer_disabled`); seed M9 là dữ liệu mẫu — không sửa.

### 6.4. Test (test-writer viết TRƯỚC code)

| # | Test | Đạt khi |
|---|---|---|
| c1 | `check_strategy` lúc khởi động | API **và** worker: `M5_STRATEGY ∈ {llm_only, rule_only, full_auto, hybrid_guarded}` + `EVAL_MODE=false` → không khởi động; `hybrid` → chạy |
| c2 | `policy.json` khối `m5` | thiếu khối → lỗi khởi động; `calibrator_version` sai mẫu → lỗi; `null` → `deps.calibrator is None` |
| c3 | B12 không khớp + chưa hiệu chỉnh (ScriptedLLM raw 0,02) | **HITL** → B15 (không AUTO); điểm 4 `decided_by=llm`, `raw_prob=0.02`, `calibrated_prob=None` |
| c4 | B12 không khớp + preset 0,9 | E5 `llm_high_risk`, 0 phiếu |
| c5 | B12 không khớp + calibrator (a=1,b=0) + raw 0,05 + có bằng chứng | AUTO → `S_EXECUTING`; state `action_plan_hash == hash_action(action)` |
| c6 | như c5 nhưng `kb_gap` (evidence rỗng) / gateway cắt hết (`trimmed_evidence` = số khối) | HITL (N4) |
| c7 | Lỗi estimator | E5 `llm_layer_disabled` (giữ) |
| c8 | Luật khớp | ScriptedLLM **0** lời gọi `b14_*` |
| c9 | B17 + LLM-AUTO, hash khớp, luật vẫn không khớp | thực thi (≥ 1 lời gọi ghi) |
| c10 | B17 + LLM-AUTO, hash lệch / `decided_by=rule` không duyệt / `route=HITL` | E5 `recheck_failed`, 0 lời gọi ghi |
| c11 | B17 + LLM-AUTO nhưng policy hiện hành nay khớp `deny`/`approval_required` | E5, 0 lời gọi ghi |
| c12 | `full_auto` (EVAL_MODE) + ca luật `deny` | điểm 4 `decided_by=NULL`, `detail.strategy=full_auto`, `route=AUTO`; B17 → E5, 0 lời gọi ghi (Q-6-8 điều kiện 2) |
| c13 | `audit_check` điểm 4 | llm thiếu `raw_prob` → thiếu; NULL + `full_auto` → đạt; NULL không ghi chú → thiếu |
| c14 | Lineage ca LLM | có `prompt_id`, `prompt_version`, `model`, `p_method`; `calibrator_version` khớp policy |
| c15 | **Canary [Chốt cổng 6]** (e2e, ScriptedLLM ghi mọi bản render) | câu yêu cầu chứa `CANARY-M5-<uuid>` ở chữ tự do **và** chuỗi lệnh đặt trong `software_name`, `resource_path`, `target_user` → không chuỗi nào có trong bất kỳ bản render `b14_*` nào, không trong `llm_calls.prompt_full` (EVAL) |
| c16 | N1 `estimator_vars` | `params` chỉ 4 khoá cho phép; `target` `folder:`/`user:` → loại đích; không có `requested_for` |
| c17 | AST | không `model_construct`/`model_copy(update=` trong `app/risk/**` |
| c18 | E2E TC37 + họ §8.2 (ScriptedLLM) | mọi ticket qua M5 có `decided_by` (hoặc NULL + `full_auto`); route đúng ngưỡng |

### 6.5. Mutation (2 lượt, md5)

| Mã | Phá | Test phải đỏ |
|---|---|---|
| M-6C-1 | B17 nhận LLM-AUTO khi hash lệch | c10 |
| M-6C-2 | B12 bỏ `kb_gap` (truyền `False`) | c6 |
| M-6C-3 | Bỏ `check_strategy` khỏi `open_runtime` | c1 |
| M-6C-4 | Điểm 4 ca LLM bỏ `raw_prob` | c13 / c3 |
| M-6C-5 | `estimator_vars` giữ `software_name` | c15, c16 |
| M-6C-6 | B12 không đặt `action_plan_hash` ở ca AUTO | c9 |
| M-6C-7 | `audit_check` chấp nhận NULL không ghi chú | c13 |
| M-6C-8 | `kb_gap` bỏ vế `trimmed_evidence` | c6 |
| M-6C-9 | Calibrator null nhưng vẫn so `t_low` | c3 |

### 6.6. Soát bảo mật (security-reviewer, mỗi DỪNG)

(1) Không đường nào đưa chữ người dùng vào prompt B14 (kể cả slot `software_name`, `resource_path`, `target_user`); (2) lỗi/thiếu ước lượng không ra AUTO; (3) chưa hiệu chỉnh không ra AUTO; (4) `kb_gap` (kể cả bị gateway cắt) chặn AUTO; (5) B17 chỉ nhận LLM-AUTO khi hash khớp + luật hiện hành không khớp; (6) chiến lược so sánh bị chặn ở **cả** API và worker; (7) `rationale` không vào audit/log/lineage; (8) `full_auto` không thực thi ca `deny`.

### 6.7. DỪNG

- **DỪNG 1:** P1, P2, P3 (trừ AUTO→B17 thật), P5, P7, P8, P9, P10 + test c1–c8, c13, c14, c16, c17 + hồi quy đổi kỳ vọng + mutation lượt 1 (M-6C-2,3,4,5,7,8,9) + security-reviewer. `make verify G=0`.
- **DỪNG 2:** P4, P6 (B17), P11 + c9–c12, c15, c18 + mutation lượt 2 (9/9) + security-reviewer + "Spec cần sửa (6C)". `make verify G=0`; sau gộp: `make verify G=2345` qua phiếu "dùng stack".
- **Xác nhận:** Quân (không gán nhãn) chạy `make verify G=0` + đọc bảng c15 + c9–c11.

### 6.8. Q-6-8 — biểu diễn `full_auto` [Chốt 10/10 — C]


| | Cách | Đánh giá |
|---|---|---|
| A | Thêm `"none"` vào `decided_by` | Cần migration CHECK (chuỗi migration do Dương giữ) |
| B | `full_auto` ghi `decided_by="rule"` | Sai nghĩa, làm bẩn bảng `decided_by` |
| **C (đã chốt 10/10)** | B12 không dựng `RiskDecision`; dòng điểm log 4 `decided_by = NULL` (cột đã cho NULL), `detail = {strategy: "full_auto", route: "AUTO"}`; `risk = None`; đi `S_EXECUTING`. B17 giữ nguyên kiểm lại → ca `approval_required`/`deny` kết thúc E5 ở B17 — **không ảnh hưởng số đo** vì M8 đọc quyết định ở điểm log 4 [Chốt P8 §6.1]. Chỉ chạy khi `EVAL_MODE` | Không migration, không nới B17 |

**Chốt C (10/10) — điều kiện bắt buộc cho 6C:**
1. `audit_check` điểm 4: `decided_by` NULL **chỉ** hợp lệ khi `detail.strategy == "full_auto"` (và `detail.route == "AUTO"`); NULL không kèm ghi chú → vẫn báo thiếu trường. Test: 1 ca NULL + full_auto → đạt; 1 ca NULL không ghi chú → lỗi.
2. B12 nhánh `FullAutoBypass`: chỉ đến được khi `check_strategy` đã cho qua (EVAL_MODE); test ca `full_auto` + luật `deny` → điểm 4 ghi AUTO, B17 kiểm lại → E5 `recheck_failed`, **không** thực thi.
3. Báo cáo (T29/Phase 10): FNR, chi phí của `full_auto` đọc ở điểm 4 (đúng); automation rate của `full_auto` ghi chú "theo định nghĩa = 100 % ca có hành động; B17 vẫn chặn khi chạy thử" — không đọc từ điểm 8.


### 6.9. Chốt khi hiện thực (6C) — 14/10/2026, `m5-tuananh`: `f030926` (DỪNG 1) + `b7cb1a4` (DỪNG 2) trên `c45b079`, PR #44

**Kết quả:** `make verify G=0` XANH cả 2 DỪNG (DỪNG 1 trên `457239d`: backend 5756 passed; DỪNG 2 sau rebase lên `c45b079`: backend **6388 passed / 4 skipped**, mock 106, ml 123; unit 5769); lint xanh (import-linter 10/10, gitleaks 0); mutation lượt 1 **10/10**, lượt 2 **14/14** đỏ đúng dự đoán, md5 khớp, `test_mutation_n3` xanh; security-reviewer 4 lượt (DỪNG 1, Q-6C-8/9, DỪNG 2, Q-6C-10/11/12), **0 FAIL**. Rebase DỪNG 1 (`145bfaa` → `f030926`) lên nền A4 + T20b + T29 sạch: 4 file chung (`wiring.py`, `exit_codes.py`, `audit/check.py`, `PROGRESS.md`) không chồng dòng (gộp thử `git merge-file`). Chạy thử stack `G=2345` trên `pull/44/merge` trước khi gộp (15–16/10).

**Khác/thêm so với 6.1–6.5 (đã duyệt):**
1. **Q-6C-1 = B (P1):** không thêm `M5_STRATEGY` — nguồn chiến lược duy nhất là `Settings.strategy` (env `STRATEGY`, đã có trong compose/`.env.example`/Makefile); `manual` (chỉ tính giải tích ở harness M8) bị **từ chối ở mọi chế độ**; kiểm ở `open_runtime` trước DB **và** lần hai ở `_open` (M-6C-3 phải bỏ cả hai mới đỏ).
2. **Q-6C-2 = A:** `llm_high_risk` thêm vào `REASON_DETAILS` (`domain/exit_codes.py` — ngoài danh sách 6.2).
3. **Q-6C-3 = A (P5, P7):** `detail.strategy` ghi ở **mọi** đường điểm 4 khi `EVAL_MODE`; `audit_check` chấp nhận `decided_by=rule` + `policy_decision` NULL **chỉ** khi `rule_only` ∧ HITL.
4. **Q-6C-4 = A + Q-6C-8 = A (P9):** `evidence_sent = min(len(evidence), MAX_EVIDENCE)`; `kb_gap = evidence_sent − evidence_trimmed ≤ 0`; `evidence_trimmed` không phải `int` thật (kể cả `bool`) hoặc âm → `kb_gap = True`.
5. **Q-6C-5 = A:** `tests/fixtures/llm/vpn.py` thêm `b14_*` 0,9 (ngoài 6.2).
6. **Q-6C-6 = A:** c15/c18 ở mức chuỗi node trong bộ nhớ, gateway thật, đi từ câu người dùng ở B2/B3 tới B14 (không e2e testcontainers).
7. **Q-6C-9 = A (mới):** trước B14, B12 gọi lại `check_facts(action.facts)` và đòi `action.type ∈ PARAMS_BY_ACTION`; lệch → E9 (lỗi code — không rơi vào nhánh lỗi estimator `llm_layer_disabled`), estimator không được gọi.
8. **Q-6C-10 = A (mới, D-42 chặt hơn):** B17 `llm_auto` đòi thêm `risk.calibrated_prob is not None` — LLM-AUTO chưa hiệu chỉnh không thực thi kể cả khi state bị ghi sai (D-38 ở cửa thực thi). Không sửa `ticket_state.py`. **Q-6C-11 = A:** `risk` dạng dict hỏng ở B17 → E9, 0 ghi, 0 `begun`.
9. **P8 (N1):** mẫu dùng `[0-9]` thay `\d`; `duration_days` 1…999; khoá trượt mẫu thì **bỏ** (không ném).
10. **TQ-4:** `settings.py` không import `app.risk.calibrator` (import-linter); `VERSION_PATTERN` kiểm trong `load_calibrator` ở `open_runtime` (vẫn trước DB).
11. **Test cũ đổi kỳ vọng:** `test_gate3_vpn.py` 3 ca (h11, h11@20:00, LAP-9999) E5 `llm_layer_disabled` → `llm_high_risk` + `risk_decided`; es2 (N1), es9 (+`evidence_trimmed`) của 6B; `test_b12_assess.py:150` chỉ tên + docstring. Script cổng, `eval/`, preset, frontend, seed M9: không sửa.
12. **6.5 mutation:** thêm M-6C-10 (bỏ chặn `evidence_trimmed` sai kiểu), M-6C-11 (bỏ `check_facts` trước B14), M-6C-12 (bỏ kiểm `type`), M-6C-13 (bỏ vế `not verdict.matched` trong `via_llm` → 3 ca c11 đỏ), M-6C-14 (bỏ vế `calibrated_prob` → test Q-6C-10 đỏ). M-6C-6 bị **c5 + c18** bắt (không phải c9 — c9 ở mức node tự dựng state có sẵn hash). M-6C-5 đỏ ở c15 + c16. `mutate_4a.py` M-S0-5 đồng bộ chuỗi gốc.

**Ghi nhận (không sửa ở 6C):**
- **N3:** `llm_cache` lưu cả `rationale` khi EVAL (`llm/client.py`, ngoài phạm vi).
- **N7 (mới):** tên khoá facts lạ lọt vào `audit.detail.exception`/log (`FactKeyViolation` dùng chung với B11) — vô hại khi khoá do code đặt; **phải lọc** nếu sau này khoá đến từ đầu ra LLM.
- **Khởi động từ chối:** API → runtime 503 ở route ticket/duyệt, tiến trình không thoát; **`/api/health` vẫn HTTP 200** (`status: ok`, `runtime: down`, cache 10 s của A4 không đổi) — mã HTTP chỉ theo phụ thuộc DB/Qdrant/mock/ml; worker thoát. → báo M9.
- **`llm_only` (EVAL):** không chạy luật ở B12 nên ca `deny` có thể vào B15; B17 vẫn chặn — đúng mục đích đo "chỉ LLM, không luật".
- Họ §8.2 "mở khoá không do nhập sai" trong c18 khoá tài khoản tạm bằng `set_lock` trong bộ nhớ (không sửa `seed.json`); không họ nào ra rule với seed hiện có.

**Báo M9 (Dương) — gộp vào tin Phase 5 gửi sau 17/10:** mã E5 mới `llm_high_risk` (`event="risk_decided"`); khoá `detail` điểm 4 mới (`calibrated_prob`, `thresholds`, `factors`, `kb_gap`, `calibrator_version`, `strategy` khi EVAL); `decided_by` NULL ở `full_auto` (EVAL, `detail` đúng 3 khoá `strategy`, `route`, `policy_sha256`); `/api/health` 200 khi runtime down.

**Xác nhận (cổng 6):** Quân chạy `make verify G=0` trên máy mình + đọc bảng c15 (canary) và c9–c11 (B17).


---

## 7. Chặng 6D — công cụ đọc lý do + probe p (tầng B, Sonnet, 1 DỪNG)

**Mục tiêu:** hai công cụ **chỉ đọc** cho phần **thủ công** của cổng 6: (a) lấy mẫu lý do rủi ro cho người không xây M5 đọc; (b) đo phân phối `raw_prob` để chọn `p_method`. Không đổi hành vi hệ thống.
**Đầu vào:** 6C đã gộp (PR #44) — `m5-tuananh` fast-forward lên `dev-tuananh` sau gộp (phiếu phiên git). **Đầu ra:** 1 module + 2 vỏ script + test. Không node, không DB schema, không cấu hình, không prompt.
**Nghi thức (tầng B):** PLAN ngắn trong MẪU A · **1 DỪNG** · mutation 1 lượt + md5 · security-reviewer cuối chặng (chỉ: không rò dữ liệu, chỉ đọc). **Model: Sonnet.** Worktree `-m5`, chỉ `make verify G=0`.
**Sự thật code (soát `b7cb1a4`, 14/10):** dòng điểm log 4 = `audit_logs` có `(step, event) == ("B13/B14", "risk_decided")` (`audit/check.py:143`); đọc DB chỉ-đọc qua `audit/check.readonly_engine` + `load(engine, since=…)`; DSN theo Settings (`MONITOR_DATABASE_URL` → `DATABASE_URL`), không in DSN (khuôn `audit_check.main`); vỏ script khuôn `scripts/audit_check.py`. **Không có `matplotlib`** trong `pyproject` (không thêm phụ thuộc) → histogram dạng CSV + thanh chữ.

### 7.1. P-x chốt trước

| Mã | Chốt |
|---|---|
| P1 | **Một module** `backend/app/audit/m5_review.py` (cạnh `check.py`, tái dùng `readonly_engine`, `load`, `_since`); **không** đặt trong `app/eval` (gói T27/T29) hay `app/risk` (lõi M5 không đọc DB). Hàm thuần tách khỏi lớp DB để test không cần Postgres |
| P2 | **`point4_rows(by_ticket) -> list[Point4]`** — `Point4(frozen)`: `ticket_id`, `decided_by` (`rule`/`llm`/None), `route`, `reason`, `raw_prob`, `p_method`. Chọn đúng bộ lọc điểm 4 của `check.py` (một nguồn: hằng `POINT4_KEY = ("B13/B14", "risk_decided")` dùng chung — sửa `check.py` chỉ để dùng hằng, không đổi logic) |
| P3 | **`sample_reasons(rows, *, n, seed, min_llm) -> list[str]`:** bỏ trùng theo **nguyên văn** `reason` (giữ lần đầu theo `log_id`); lấy ngẫu nhiên `random.Random(seed)`; cố gắng ≥ `min_llm` câu `decided_by="llm"` nếu có đủ, phần còn lại từ luật; thiếu thì lấy hết và báo số thật. Trả **chỉ chuỗi** `reason` — không `ticket_id`, không `route`, không `rule_id`, không `expected_route` |
| P4 | **`template_reasons() -> list[str]`:** 4 mẫu `reason` của 5.3 (đã hiệu chỉnh; chưa hiệu chỉnh; hạ AUTO → HITL do `kb_gap`; `hybrid_guarded` + allow) dựng bằng **chính hàm của `risk/strategy.py`** với số ví dụ cố định (không viết lại chữ) — để người đọc thấy cả đường HITL/AUTO mà stack (chưa hiệu chỉnh, preset 0,9) không sinh ra |
| P5 | **Vỏ `scripts/sample_reasons.py --since <ISO> --n 10 --seed <số> [--min-llm 3] [--templates] [--key-out <file>]`:** in danh sách đánh số 1…n (+ 4 mẫu nếu `--templates`, đánh dấu "mẫu"); `--key-out` ghi riêng file `số → ticket_id, decided_by, route` cho **Tuấn Anh** đối chiếu (không đưa người đọc). Mã thoát: 0 đủ n; 1 thiếu (in số thật); 2 lỗi DB (chỉ in tên lớp lỗi) |
| P6 | **`concentration(values, *, top=2, threshold=0.60) -> Concentration`:** làm tròn 2 chữ số, đếm tần suất, `share = tổng 2 mức nhiều nhất / n`; `recommend = "sampling_k5" if share > threshold else "self_report"` [Chốt "> 60 %" — **bằng 60 % → `self_report`**]; `n < 20` → `recommend = None` ("không đủ dữ liệu"); NaN/ngoài [0, 1] → `ValueError` |
| P7 | **Vỏ `scripts/probe_p_distribution.py --since <ISO> [--csv <file>]`:** lấy `raw_prob` của dòng điểm 4 `decided_by="llm"`; in bảng 10 bin (0,0–0,1 … 0,9–1,0) dạng thanh `#`, `n`, 2 mức nhiều nhất + `share`, khuyến nghị; `--csv` ghi `bin_lo,bin_hi,count`. **Nếu `Settings.llm_backend == "scripted"`** → in dòng cảnh báo đầu tiên "DỮ LIỆU GIẢ (ScriptedLLM) — không dùng để chọn p_method" và mã thoát 3 (vẫn in bảng) |
| P8 | **Chỉ đọc:** mọi truy vấn qua `readonly_engine`; không ghi file nào ngoài `--csv`/`--key-out` người dùng chỉ định; không in DSN, không in `.env`, không in `detail` thô |
| P9 | **Không đụng:** node, wiring, Settings, `policy.json`, prompt, preset, migration, `app/monitor/*`, `app/eval/*`, `app/risk/*` (chỉ **gọi** hàm của `strategy.py`), `pyproject.toml`/`uv.lock` |

### 7.2. File

```
backend/app/audit/m5_review.py            # P1–P4, P6 (+ async load_point4(engine, since))
backend/app/audit/check.py                # chỉ thêm hằng POINT4_KEY và dùng nó (P2)
scripts/sample_reasons.py                 # P5 (vỏ, khuôn audit_check.py)
scripts/probe_p_distribution.py           # P7 (vỏ)
backend/tests/unit/test_m5_review.py      # r1–r10
backend/tests/integration/test_m5_review_pg.py   # r11 (testcontainers)
scripts/mutation/mutate_6d.py
```

### 7.3. Test

| # | Test | Đạt khi |
|---|---|---|
| r1 | `point4_rows` | chỉ lấy dòng `("B13/B14","risk_decided")`; dòng điểm 3/7/8 bị bỏ; giữ `decided_by` NULL (full_auto) |
| r2 | Bỏ trùng | 6 dòng cùng 1 `reason` + 4 câu khác → tối đa 5 câu khác nhau |
| r3 | Tất định | cùng `seed` → cùng danh sách; khác `seed` → khác (trên ≥ 20 câu) |
| r4 | `min_llm` | 3 câu llm + 20 câu luật, `n=10, min_llm=3` → đủ 3 llm; 1 câu llm → 1 llm + 9 luật, báo thiếu |
| r5 | Không rò | đầu ra (và stdout của vỏ) **không** chứa giá trị của các **trường** `ticket_id`, `route`, `rule_id`, `expected_route` — kiểm bằng chuỗi canary đặt trong các trường đó. Chữ `reason` giữ **nguyên văn** (có thể chứa mã/mô tả luật — Quân được đọc) [sửa 1.2, Q-6D-2 = C; bản 1.1 cấm `R0`–`R20` trong đầu ra là sai ý định] |
| r6 | `template_reasons` | 4 câu; khớp **từng ký tự** với `reason` do `strategy.decide` sinh ở cùng tham số (không chép tay chuỗi) |
| r7 | `concentration` biên | 12/20 và 18/30 giá trị ở 2 mức (= 60 %) → `self_report`; 14/20, 21/30 → `sampling_k5`; n = 19 → `None`; [0,9]×20 → `sampling_k5`, share 1,0 [sửa 1.2: bản 1.1 ghi "6/10", mâu thuẫn n < 20 → `None`] |
| r8 | Làm tròn | 0,904 và 0,896 cùng mức 0,90 |
| r9 | Đầu vào xấu | NaN, 1,2, −0,1 → `ValueError` (thông điệp không chứa giá trị) |
| r10 | Cảnh báo dữ liệu giả | `llm_backend="scripted"` → dòng cảnh báo đầu + mã 3; `"real"` → không cảnh báo |
| r11 | Postgres thật (chỉ đọc) | chèn 12 dòng audit (luật + llm + NULL) → `load_point4` trả đúng; thử `INSERT` qua engine → lỗi `read_only_sql_transaction` |

### 7.4. Mutation (1 lượt, md5)

| Mã | Phá | Test phải đỏ |
|---|---|---|
| M-6D-1 | `share >= threshold` | r7 |
| M-6D-2 | Bỏ bỏ-trùng | r2 |
| M-6D-3 | Đầu ra kèm `route` | r5 |
| M-6D-4 | Bỏ cảnh báo ScriptedLLM | r10 |
| M-6D-5 | Bỏ làm tròn 2 chữ số | r8 |
| M-6D-6 | Engine không READ ONLY | r11 |

### 7.5. DỪNG

**DỪNG duy nhất:** code + test + mutation (6/6) + security-reviewer (chỉ đọc; không rò `ticket_id`/route/luật/DSN; không ghi DB). `make verify G=0` trong `-m5`. Commit cục bộ khi được bảo → phiếu push + PR → gộp (phiên git).

### 7.6. Sau 6D — phần thủ công của cổng 6

1. **Đọc lý do (Quân) [Chốt cổng 6]:** nguồn = DB stack của **lượt verify đầy đủ gần nhất trên HEAD có 6C** (mốc main 16/10, HEAD có cả 6D; lượt cổng 5 15/10 00:22 cũng dùng được nếu DB chưa bị dựng lại) — có ticket của gate 3/4/5. Tuấn Anh chạy **trong container backend** (image không có `scripts/` — Q-6D-5 = A), qua phiếu phiên git vì đụng stack: `python -m app.audit.m5_review sample --since <giờ bắt đầu lượt, ISO có múi giờ> --n 10 --seed <số> --min-llm 3 --templates --key-out /tmp/khoa-6d.csv` → chép `/tmp/khoa-6d.csv` ra máy, giữ riêng. Gửi Quân **chỉ** stdout (10 câu + 4 câu `[mẫu]`); ghi lại `--since` và `--seed` vào biên bản để lặp lại được. Stack chạy ScriptedLLM nên câu của ca `decided_by=llm` có thể trùng nhau (bỏ trùng → ít hơn 3; stderr báo "thiếu câu llm", vẫn thoát 0) — 4 mẫu bù phần này. Quân đánh dấu từng câu "hiểu được / không hiểu" + 1 dòng góp ý, ký biên bản. Câu không hiểu → sửa mẫu `reason` (5.3, chặng sau) hoặc `description` luật (báo Phase 5). Dương, Duy Anh **không** nhận danh sách này (D-43).
2. **Probe p (mốc G, LLM thật):** người không xây M5 (Duy Anh) chạy `hybrid` + `EVAL_MODE=true` + `LLM_CACHE_MODE=eval` trên ~30 kịch bản D2 mà `rule_coverage.py` báo "none" → `probe_p_distribution.py --since … --csv …` → Tuấn Anh ghi `m5.p_method` vào `policy.json` theo khuyến nghị; ghi vào "Dồn về mốc G" của PROGRESS. Chạy trên ScriptedLLM chỉ để thử công cụ (mã 3).
3. **Checklist cổng 6** (phiên Phase 6 giữ, `claude/checklist-cong-6.md` trong Project): tự động 1.1 (6A dm1–dm8; 6B st15; 6C c1, c3–c5, c15, c18) · mutation 6A 12/12, 6B 5/5 + 9/9, 6C 10/10 + 14/14, 6D 6/6 · xác nhận người: Dương (dm3–dm8, #32), Duy Anh (6B verify), Quân (6C c9–c11, c15 + biên bản 10 lý do) · probe → mốc G · spec "Chốt khi hiện thực" 6A–6D · `decisions.md` D-36…D-40, D-42 (Phase 5 ghi).

---

### 7.7. Chốt khi hiện thực (6D) — 15/10/2026, `m5-tuananh`: `8c3ce2b` trên `78a25cd`, PR #47 → gộp `1b4b16b` (15/10 tối)

**Kết quả:** `make verify G=0` XANH (backend **6587 passed / 4 skipped**, mock 106, ml 123); unit 5906 → **5948** (+42, r1–r10); r11 **3/3** (Postgres testcontainers); lint xanh (mypy, import-linter 10/10, gitleaks 0); lượt đỏ 42/42 do `NotImplementedError` (không do import); mutation lượt 1 **6/6** đỏ đúng dự đoán (M-6D-6 ở làn `--integration`, Tuấn Anh chạy ngoài sandbox), md5 `m5_review.py` `f4da37cc8e82c102a10419ddc07a5424` trước = sau; security-reviewer **5/5 PASS**, 0 FAIL. Phiên git soát đạt; gộp thử với `93a9090` sạch. 6D chỉ đọc, ngoài luồng → không chạy thử stack trước gộp; lượt verify mốc main 16/10 chạy trên HEAD đã có 6D.

**Khác/thêm so với 7.1–7.4 (đã duyệt MẪU A 15/10):**
1. **Q-6D-1 = A (P5):** `sample` thoát 1 **chỉ khi tổng < n**; thiếu câu `llm` so với `--min-llm` → chỉ báo stderr "thiếu câu llm: k/m", thoát 0. Mã: 0 đủ n · 1 thiếu · 2 lỗi DB/ghi file (chỉ tên lớp lỗi).
2. **Q-6D-2 = C (r5):** giữ nguyên văn `reason`; canary chỉ đặt ở trường riêng (r5 đã sửa ở 7.3).
3. **Q-6D-3 = A (P7):** `probe` thoát 0 có khuyến nghị · 1 n < 20 · 2 lỗi DB/ghi file · 3 `LLM_BACKEND` ≠ `real` — **3 thắng 1**; dòng cảnh báo là dòng đầu stdout, vẫn in bảng.
4. **Q-6D-4 = A (P7):** `LLM_BACKEND` chưa đặt (None) cũng tính là ≠ `real` → cảnh báo + 3.
5. **Q-6D-5 = A:** chạy trong container bằng `python -m app.audit.m5_review sample|probe …` (image không có `scripts/`); hai vỏ `scripts/*.py` chỉ cho chạy trên máy (`PYTHONPATH=backend`). Không sửa Makefile/Dockerfile — **chưa có đích `make`** cho probe (Duy Anh 15/10 hỏi "đích riêng cho phân phối p"): thêm khi chuẩn bị mốc G nếu cần.
6. **Q-6D-6 = A (7.4):** M-6D-6 thuộc làn `--integration` của `mutate_6d.py`; M-6D-1…5 làn unit.
7. **r7:** 12/20, 18/30 (= 60 % → `self_report`), 14/20, 21/30 (→ `sampling_k5`) — đã sửa ở 7.3.
8. **P3/P4 chi tiết:** `pick` lấy ≥ `min_llm` câu llm trước rồi bù câu luật, **xáo thứ tự in** (người đọc không đoán được câu nào từ LLM); 4 mẫu dựng bằng `strategy.decide` với số cố định (`raw_prob` 0,10 / 0,60, calibrator + ngưỡng ví dụ, luật allow giả `rule_id="(mẫu)"`) — không chép tay chuỗi.
9. **Thêm ngoài P1–P9:** `histogram`, `probe_report`, `open_engine` (= `readonly_engine`), `sample_main`/`probe_main`, `python -m` dispatch — đều trong `m5_review.py`.

**Ghi nhận (không sửa ở 6D):**
- **Hai định nghĩa "dòng điểm log 4":** `audit/check.py` (`POINT4_KEY`, chỉ `risk_decided`) và `eval/predictions.py:23` (T29, nhận cả `llm_layer_disabled`). [Suy luận] Khác có lý do: `audit_check`/6D cần dòng có quyết định đủ trường; T29 cần route của **mọi** lá, kể cả lỗi estimator. Chưa gộp một nguồn — nếu gộp, đặt hằng `step` chung, `event` để từng nơi chọn (việc của Phase 5/T29, không gấp).
- **`LLM_BACKEND` của tiến trình probe** có thể khác backend đã sinh dữ liệu → probe ở mốc G phải chạy **trong cùng container** của lượt sinh dữ liệu LLM thật.
- security-reviewer (thấp, cùng khuôn `audit/check.py`): `get_settings()` ngoài `try` (bí mật đều `SecretStr`); mutation khôi phục bằng `write_text` (CRLF trên Windows); exception ngoài dự kiến thoát 1, trùng nghĩa "thiếu".
- **PROGRESS mục 6D** còn ghi "chưa commit" + "Chờ: commit…" (ghi lúc DỪNG) → sửa thành "đã gộp `1b4b16b` (PR #47)" ở commit kế tiếp của Phase 6 (cùng commit spec 1.2).

## 8. Lịch và thứ tự

| Chặng | Ước lượng agent | Phụ thuộc | Người khác |
|---|---|---|---|
| 6A | ~3 giờ, 09/10 (worktree `-m5`) | 4d commit | Dương soát số (issue #32) |
| 6B | ~5 giờ, DỪNG 1 10/10, DỪNG 2 11/10 | 6A, P12 chốt | Duy Anh chạy verify |
| 6C | **Xong** — DỪNG 1 + DỪNG 2 14/10; PR #44; chạy thử stack trên cây gộp `28bfef7` (gate2 89/0, gate3 78/0, gate4 73/0, gate5 227/0); gộp `5f2ece2` 15/10 | 6B, **T24**, Q-6-8 = C | Quân xác nhận trên #44 (chạy pytest 2 file + đọc c9–c11, c15) |
| 6D | **Xong** — 1 DỪNG 15/10 (`8c3ce2b`); PR #47 gộp `1b4b16b` 15/10 tối | 6C gộp; đọc lý do sau lượt verify mốc main 16/10; probe thật ở mốc G (muộn nhất 22/10) | Quân đọc 10 lý do + 4 mẫu; probe thật (Duy Anh) |

Cổng 6 đạt khi: phần tự động 1.1 xanh; mutation 6A ×1, 6B ×2, 6C ×2, 6D ×1; Quân ký biên bản đọc lý do; probe ghi vào "Dồn về mốc G" của PROGRESS; spec "Chốt khi hiện thực" từng chặng; `decisions.md` D-36…D-40, D-42.

## 9. Nhật ký

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 16/10/2026 | 1.2 | 6D hiện thực (`8c3ce2b`, PR #47 → `1b4b16b`): mục 7.7 "Chốt khi hiện thực" (Q-6D-1…6, mutation 6/6, security 5/5, hai định nghĩa điểm 4, `LLM_BACKEND` của probe). Sửa r5 (canary ở trường, giữ nguyên văn `reason`) và r7 (12/20, 18/30). 7.6: nguồn DB = lượt verify mốc main 16/10, chạy `python -m app.audit.m5_review` trong container qua phiếu phiên git; checklist ở `claude/checklist-cong-6.md`. Lịch 8: 6C, 6D xong |
| 14/10/2026 | 1.1 | 6C hiện thực (`f030926` + `b7cb1a4`, PR #44): mục 6.9 "Chốt khi hiện thực" (Q-6C-1…12, mutation 14/14, N7, health 200, báo M9). Mục 7 (6D) viết chi tiết: `audit/m5_review.py` + 2 script chỉ đọc, P1–P9, r1–r11, M-6D-1…6, phần thủ công cổng 6 (Quân đọc 10 lý do + 4 mẫu; probe ở mốc G; checklist). Lịch 8 cập nhật |
| 13/10/2026 | 1.0 | Mục 6 (6C) viết chi tiết trên `457239d` (sau T24): sự thật code 6.0, P1–P12 (chiến lược + `check_strategy` cả API/worker, khối `m5`, B12 đường LLM, `llm_high_risk`, `full_auto` C, điểm 4 + lineage, B17 D-42, `audit_check`, N1 danh sách trắng gồm `target`/`requested_for`, N4 `trimmed_evidence`, calibrator, N6 preset), hồi quy, 18 test, 9 mutation, 8 bất biến, 2 DỪNG. Q-6-8 chuyển 6.8 |
| 10/10/2026 | 0.9 | 6B hiện thực (`d8e3cbe` + `6fda378`): mục 5.11 "Chốt khi hiện thực" + nợ N1–N6 chuyển 6C. Q-6-8 chốt **C** (Tuấn Anh 10/10): `decided_by` NULL + `detail.strategy = "full_auto"`; thêm 3 điều kiện bắt buộc cho 6C (mục 6.8). Không đổi mục 4–5 |
| 09/10/2026 | 0.8 | Soát mục 5 trên `fe61fa3` (+ T22a DỪNG 1 `6ab716e`; soát lại 21:30 trên `2ffb005` = T22a đã gộp: không đụng `llm/`, `config/prompts`, `config/scripted`, `risk/estimator.py`, `graph/`; `mutate_3h.py` chỉ đổi dòng 110 `_TARGET` — M-3h-9 `_ESTIMATE` nguyên; 6B mở trên `2ffb005`): P1 — estimator giả không ở `tests/fakes` mà `NodeDeps` ở `app/graph/fakes.py`; thêm file giả mới; P12 chốt 0,9; thêm es10 (test d10 chỉ quét `graph/nodes/`). Các chỗ khác của mục 5 khớp code: `SCHEMAS` dict (`llm/schemas.py:91`), 6 prompt + preset `default.yaml`/`vpn.yaml`, `test_llm_prompts.py:68` đếm 6 + `TABLE_7_4` (:42) + `…schema_set_has_six_classes` (:84), 3 test preset tồn tại, `llm/context._evidence` đòi 5 khoá, `ChunkRef` (`domain/ticket_state.py:33`) có `chunk_id…excerpt`, `LlmPort.complete` (`llm/ports.py:47`), `cache_key` (`llm/cache.py:28`), ScriptedLLM nhận kịch bản dạng hàm (`providers/scripted.py:69`) |
| 09/10/2026 | 0.7 | 6A hiện thực: mục 4.10 "Chốt khi hiện thực" (Q-6A-1…4, mutation 12/12, verify G=0 xanh) |
| 09/10/2026 | 0.6 | Chỉ phối hợp/git (không đổi kỹ thuật): luật 4.0 phiên git — git/GitHub/worktree/stack qua phiếu cho phiên chat git, agent chỉ commit cục bộ (0.2, 4.8, 5.9, 6 việc 8); worktree `-m5` đã tạo @ `3ff63e1`; API 4.2–4.3 đã đăng issue #32; P12 chờ chốt trước 6B; lịch 8 dời. Soát `3ff63e1`: file 6A/6B dựa vào không đổi |
| 06/10/2026 | 0.5 | Kiểm kỹ lần 3: dựng thử 6B (estimator qua gateway thật, bảng quyết định) — đạt; thêm P12 (preset `default.yaml`, `vpn.yaml` — 3 test có sẵn đòi), 5 test có sẵn phải xử lý, es1 kiểm tham số bằng `LlmPort` giả, es2 kiểm trên dict. Code nền không đổi từ `1455b55` tới `632e05a` |
| 03/10/2026 | 0.4 | Rà soát lần 2 trên bản sao sạch của `1455b55` (uv sync đúng `uv.lock`, chạy lint + unit thật): 6A thêm **P11** (khối mypy cho scipy/sklearn — thiếu thì `make lint` đỏ); 6B sửa **P8** (`FactorCode` phải ở `domain`, không thì vỡ hợp đồng import-linter số 8), **P4** (ánh xạ `ChunkRef` → khối bằng chứng), **P7/P9** (`SCHEMAS`, `TABLE_7_4`), 5.5 (thứ tự ScriptedLLM), đồng bộ `mutate_3h.py`; 6C thêm việc 9 |
| 03/10/2026 | 0.3 | Rà soát trước bàn giao: viết cài đặt tham chiếu 6A theo 4.2–4.3 và chạy trên numpy 2.5.3 / scipy 1.18.1 / scikit-learn 1.9.1 / pydantic 2.13.5 — dm1–dm10, dm12, cb1–cb7 đạt đúng số trong spec. Sửa theo kết quả: P8 ghi rõ `C=np.inf, tol=1e-10` (`penalty=None` cảnh báo); 4.3 sắp mẫu trước khi fit; cb3 đổi sang n = 40 (n = 5 000 không giết M-6A-7); thêm M-6A-10. Mục 0.2: Phase 6 chạy ở worktree từ 6A, cấm lệnh stack trong worktree |
| 03/10/2026 | 0.2 | Soát lại với `1455b55`: file 6A/6B dựa vào không đổi; thêm G6-8 (`audit_check` điểm 4 đòi `policy_decision`), G6-9 (hồi quy test/cổng khi bật lớp 2) vào 6C; ghi B16/B17 của 4d và M9 |
| 01/10/2026 | 0.1 | Tạo file: sự thật code `aac90b1`; Q-6-1…9 (Q-6-8 hoãn tới trước 6C); 6A đủ (API `decision_math`/`calibrator`, bộ H tính tay, 8 test cổng 6 + 12 test bổ sung, 9 mutation); 6B đủ (P1–P11, 2 prompt, `FactorCode`, bảng quyết định + mẫu `reason`, 27 test, 9 mutation); 6C, 6D khung |
