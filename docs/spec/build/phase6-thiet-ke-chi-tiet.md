# Phase 6 — Thiết kế chi tiết (M5 lớp LLM: toán quyết định, calibrator, estimator, chiến lược, nối B12)

*Thuộc bộ `build/`. Phiên bản **0.8 — 09/10/2026** (0.8: soát mục 5 trên `fe61fa3` — sửa P1 chỗ estimator giả, P12 chốt, thêm es10; 0.7: **6A đã hiện thực** — mục 4.10 "Chốt khi hiện thực"; 0.6 chỉ cập nhật phối hợp/git theo luật 4.0 của phiên git — mục 0.2, 4.8, 5.9, 8; **nội dung kỹ thuật 6A/6B giữ nguyên từ 0.5**; code nền soát lại tại `3ff63e1`: file 6A/6B dựa vào không đổi). Bản 0.5 — 06/10/2026: soát lại với code `1455b55`; **6A đã chạy thử bằng cài đặt tham chiếu trên đúng bản thư viện đã khoá** — mọi số ở 4.5–4.6 khớp; sửa P8, 4.3, cb3, cb5 theo kết quả chạy; nơi chạy = worktree riêng, mục 0.2. **6A và 6B viết đủ để code ngay**; 6C, 6D ở mức khung (P-x chốt khi mở chặng). Nguồn: `huong-dan-xay-dung-he-thong-2.md` §5 Phase 6, §7.2–7.4; `B12-B14` v1.2 (§3, §4.1, §5, §5.1–5.2, §11); `P8` v1.1 (§5.3, §6.1, §9); `P2` (gateway, prompt registry, cache); `decisions.md` Q8, Q9, D-34; `claude/phase5-6-phan-tich-va-chia-chang.md` v0.1 (G6-x, D-35…D-43, lịch). Code đã đọc trên máy tại `aac90b1`, soát lại tại `1455b55` (03/10) và `3ff63e1` (09/10): các file 6A/6B dựa vào — `risk/*`, `b12_assess.py`, `llm/*`, `config/prompts`, `policy.json`, `.importlinter`, `pyproject`/`uv.lock` — **không đổi** từ `aac90b1`.*

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
| Q-6-8 | `full_auto` | **Hoãn — chốt trước 6C** (mục 6.1, khuyến nghị C). 6B chỉ trả tín hiệu `FullAutoBypass` |
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

---

## 6. Chặng 6C — nối lớp 2 vào B12 + B17 (khung, tầng A, Opus)

**Đầu vào:** 6B, **T24** (B17 ổn định), Q-6-8 đã chốt. **Đầu ra:** cổng 6 phần tự động.

**Phạm vi:**
1. **B12** dùng `strategy.needs_rules/needs_llm/decide`; `kb_gap = evidence_for_estimator(...) == []`; `FullAutoBypass` theo Q-6-8. Nhánh lỗi estimator giữ E5 `llm_layer_disabled` (đổi tên `reason_detail` nếu cần — báo M9).
2. **Cấu hình:** `policy.json` thêm khối `m5: {p_method: "self_report", calibrator_version: null}` (+ `PolicyFile`, khối `# Phase 6` trong `settings.py`); Settings `M5_STRATEGY` (mặc định `hybrid`) + `check_strategy` ở `open_runtime` **trước** DB; `LlmRiskEstimator` dựng ở `graph/wiring` thay `DisabledEstimator`; calibrator nạp theo `calibrator_version` (null → None → D-38).
3. **Điểm log 4** thêm vào `detail`: `calibrated_prob`, `thresholds`, `factors`, `kb_gap`, `strategy` (chỉ khi eval), `calibrator_version`; **lineage**: `calibrator_version`, `p_method`, `prompt_id@version`, `model`.
4. **B17 (D-42):** B12 đặt `action_plan_hash = hash_action(action)` cho ca LLM-AUTO; B17 nhánh "không khớp, chưa duyệt" → chấp nhận **chỉ khi** `risk.decided_by=llm ∧ risk.route=AUTO ∧ action_plan_hash == hash_action(action)`; còn lại giữ E5 `recheck_failed`. Kiểm lại luật hiện hành vẫn chạy trước (deny/approval_required mới xuất hiện → E5).
5. **(f) Canary [Chốt cổng 6]:** e2e ScriptedLLM ghi lại mọi bản render `b14_*`; câu yêu cầu chứa `CANARY-M5-<uuid>` ở **phần chữ tự do** (không phải giá trị slot) → chuỗi không có trong bất kỳ bản render nào, không có trong `llm_calls.prompt_full` (EVAL). *[Suy luận]* giá trị slot đã qua `value_rules` (không khoảng trắng, mẫu chặt) và nằm trong `params`/`target` là **hành động sẽ làm**, không phải "câu người dùng" — ghi rõ ở spec để reviewer không coi là vi phạm.
6. E2E TC37 + 4 họ §8.2 (ScriptedLLM): đúng route theo ngưỡng; mọi ticket qua M5 có `decided_by`.
7. **`audit_check` điểm 4 (G6-8):** `policy_decision` chỉ bắt buộc khi `decided_by = rule` **và** có `matched_rule_id`; `decided_by = llm` bắt buộc `raw_prob`, `p_method`, `detail.thresholds`; dòng `full_auto` (Q-6-8 C) không tính là điểm 4 thiếu trường. Test `test_audit_check*` + gate4 g4-12 giữ xanh.
8. **Hồi quy do bật lớp 2 (G6-9):** mọi test/cổng đang mong đợi E5 `llm_layer_disabled` cho ca "không luật nào khớp" (unit `test_b12_assess`, e2e cổng 3/cổng 4 x5, x6, h11, h14, `gate3.py`, `gate4.py`) sẽ đổi: ca đó nay đi lớp LLM → HITL (chưa hiệu chỉnh, D-38) → B15 (ca máy người khác bị chốt phòng thủ B15 chặn: E5 `approval_target_unverified`, 0 phiếu). PLAN-6C phải liệt kê **từng** test đổi kỳ vọng + lý do; preset `config/scripted/*.yaml` thêm phản hồi `b14_risk_estimate` (thiếu → `ScriptExhausted`); `make verify G=234` trên stack (phiếu "dùng stack" cho phiên git).

9. **Đồng bộ script mutation cũ:** `test_mutation_n3.py` kiểm chuỗi gốc của `mutate_3g/3h/4a` còn đúng 1 lần trong file đích; 6C sửa `b12_assess.py`, `b17_execute.py` → cập nhật chuỗi gốc trong `mutate_3h.py`, `mutate_4a.py` (và `mutate_4b.py`, `mutate_4d.py` nếu đụng), giữ ý đột biến [soát code 03/10].

### 6.1. Q-6-8 — biểu diễn `full_auto` (chốt trước 6C)

| | Cách | Đánh giá |
|---|---|---|
| A | Thêm `"none"` vào `decided_by` | Cần migration CHECK (chuỗi migration do Dương giữ) |
| B | `full_auto` ghi `decided_by="rule"` | Sai nghĩa, làm bẩn bảng `decided_by` |
| **C (khuyến nghị)** | B12 không dựng `RiskDecision`; dòng điểm log 4 `decided_by = NULL` (cột đã cho NULL), `detail = {strategy: "full_auto", route: "AUTO"}`; `risk = None`; đi `S_EXECUTING`. B17 giữ nguyên kiểm lại → ca `approval_required`/`deny` kết thúc E5 ở B17 — **không ảnh hưởng số đo** vì M8 đọc quyết định ở điểm log 4 [Chốt P8 §6.1]. Chỉ chạy khi `EVAL_MODE` | Không migration, không nới B17 |

**Mutation gợi ý 6C:** B17 chấp nhận LLM-AUTO khi hash lệch; B12 bỏ `kb_gap`; `check_strategy` không gọi lúc khởi động; điểm log 4 thiếu `raw_prob` ở ca LLM; canary: đưa `redacted_request` vào biến.

---

## 7. Chặng 6D — probe + cổng 6 (khung, tầng B, Sonnet)

1. `scripts/probe_p_distribution.py`: chạy `hybrid` với `EVAL_MODE=true`, `LLM_CACHE_MODE=eval` trên ~30 kịch bản D2 mà `rule_coverage.py` báo "none"; đọc `raw_prob` từ điểm log 4; vẽ histogram (PNG + CSV); quy tắc **"> 60 % giá trị (làm tròn 2 chữ số) dồn vào 2 mức → khuyến nghị `sampling_k5`"** [Chốt]; in kết luận. **Chạy thật ở mốc G** bởi người không xây M5 (Duy Anh); Tuấn Anh ghi `p_method` vào `policy.json` theo kết quả.
2. `scripts/sample_reasons.py --n 10 --seed <số>`: lấy ngẫu nhiên 10 dòng điểm log 4 (cả luật lẫn LLM) của một lượt chạy ScriptedLLM trên D2, in **chỉ** `reason` (không in `expected_route`, không in điều kiện luật).
3. **Quân** đọc 10 lý do, đánh dấu từng câu "hiểu được / không hiểu", ghi biên bản [Chốt cổng 6 thủ công]. Câu không hiểu → sửa mẫu `reason` (5.3) hoặc `description` luật.
4. Checklist cổng 6 + "Chốt khi hiện thực" 6A–6D + `decisions.md` D-36…D-40, D-42.

---

## 8. Lịch và thứ tự

| Chặng | Ước lượng agent | Phụ thuộc | Người khác |
|---|---|---|---|
| 6A | ~3 giờ, 09/10 (worktree `-m5`) | 4d commit | Dương soát số (issue #32) |
| 6B | ~5 giờ, DỪNG 1 10/10, DỪNG 2 11/10 | 6A, P12 chốt | Duy Anh chạy verify |
| 6C | ~5 giờ, sau T24 | 6B, **T24**, Q-6-8 | Thành viên chạy `make verify G=234` + e2e TC37 |
| 6D | ~2 giờ, ~15/10 | 6C, D2 | Quân đọc lý do; probe thật ở mốc G (Duy Anh) |

Cổng 6 đạt khi: phần tự động 1.1 xanh; mutation 6A ×1, 6B ×2, 6C ×2; Quân ký biên bản đọc lý do; probe ghi vào "Dồn về mốc G" của PROGRESS; spec "Chốt khi hiện thực" từng chặng; `decisions.md` D-36…D-40, D-42.

## 9. Nhật ký

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 09/10/2026 | 0.8 | Soát mục 5 trên `fe61fa3` (+ T22a DỪNG 1 `6ab716e`; soát lại 21:30 trên `2ffb005` = T22a đã gộp: không đụng `llm/`, `config/prompts`, `config/scripted`, `risk/estimator.py`, `graph/`; `mutate_3h.py` chỉ đổi dòng 110 `_TARGET` — M-3h-9 `_ESTIMATE` nguyên; 6B mở trên `2ffb005`): P1 — estimator giả không ở `tests/fakes` mà `NodeDeps` ở `app/graph/fakes.py`; thêm file giả mới; P12 chốt 0,9; thêm es10 (test d10 chỉ quét `graph/nodes/`). Các chỗ khác của mục 5 khớp code: `SCHEMAS` dict (`llm/schemas.py:91`), 6 prompt + preset `default.yaml`/`vpn.yaml`, `test_llm_prompts.py:68` đếm 6 + `TABLE_7_4` (:42) + `…schema_set_has_six_classes` (:84), 3 test preset tồn tại, `llm/context._evidence` đòi 5 khoá, `ChunkRef` (`domain/ticket_state.py:33`) có `chunk_id…excerpt`, `LlmPort.complete` (`llm/ports.py:47`), `cache_key` (`llm/cache.py:28`), ScriptedLLM nhận kịch bản dạng hàm (`providers/scripted.py:69`) |
| 09/10/2026 | 0.7 | 6A hiện thực: mục 4.10 "Chốt khi hiện thực" (Q-6A-1…4, mutation 12/12, verify G=0 xanh) |
| 09/10/2026 | 0.6 | Chỉ phối hợp/git (không đổi kỹ thuật): luật 4.0 phiên git — git/GitHub/worktree/stack qua phiếu cho phiên chat git, agent chỉ commit cục bộ (0.2, 4.8, 5.9, 6 việc 8); worktree `-m5` đã tạo @ `3ff63e1`; API 4.2–4.3 đã đăng issue #32; P12 chờ chốt trước 6B; lịch 8 dời. Soát `3ff63e1`: file 6A/6B dựa vào không đổi |
| 06/10/2026 | 0.5 | Kiểm kỹ lần 3: dựng thử 6B (estimator qua gateway thật, bảng quyết định) — đạt; thêm P12 (preset `default.yaml`, `vpn.yaml` — 3 test có sẵn đòi), 5 test có sẵn phải xử lý, es1 kiểm tham số bằng `LlmPort` giả, es2 kiểm trên dict. Code nền không đổi từ `1455b55` tới `632e05a` |
| 03/10/2026 | 0.4 | Rà soát lần 2 trên bản sao sạch của `1455b55` (uv sync đúng `uv.lock`, chạy lint + unit thật): 6A thêm **P11** (khối mypy cho scipy/sklearn — thiếu thì `make lint` đỏ); 6B sửa **P8** (`FactorCode` phải ở `domain`, không thì vỡ hợp đồng import-linter số 8), **P4** (ánh xạ `ChunkRef` → khối bằng chứng), **P7/P9** (`SCHEMAS`, `TABLE_7_4`), 5.5 (thứ tự ScriptedLLM), đồng bộ `mutate_3h.py`; 6C thêm việc 9 |
| 03/10/2026 | 0.3 | Rà soát trước bàn giao: viết cài đặt tham chiếu 6A theo 4.2–4.3 và chạy trên numpy 2.5.3 / scipy 1.18.1 / scikit-learn 1.9.1 / pydantic 2.13.5 — dm1–dm10, dm12, cb1–cb7 đạt đúng số trong spec. Sửa theo kết quả: P8 ghi rõ `C=np.inf, tol=1e-10` (`penalty=None` cảnh báo); 4.3 sắp mẫu trước khi fit; cb3 đổi sang n = 40 (n = 5 000 không giết M-6A-7); thêm M-6A-10. Mục 0.2: Phase 6 chạy ở worktree từ 6A, cấm lệnh stack trong worktree |
| 03/10/2026 | 0.2 | Soát lại với `1455b55`: file 6A/6B dựa vào không đổi; thêm G6-8 (`audit_check` điểm 4 đòi `policy_decision`), G6-9 (hồi quy test/cổng khi bật lớp 2) vào 6C; ghi B16/B17 của 4d và M9 |
| 01/10/2026 | 0.1 | Tạo file: sự thật code `aac90b1`; Q-6-1…9 (Q-6-8 hoãn tới trước 6C); 6A đủ (API `decision_math`/`calibrator`, bộ H tính tay, 8 test cổng 6 + 12 test bổ sung, 9 mutation); 6B đủ (P1–P11, 2 prompt, `FactorCode`, bảng quyết định + mẫu `reason`, 27 test, 9 mutation); 6C, 6D khung |
