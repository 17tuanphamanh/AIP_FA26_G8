# P8 — Khung đánh giá và thực nghiệm (M8, `backend/app/eval/`)

*Thuộc bộ `build/`. Objective 3 (0–20%). Phase 8 (harness, hiệu chỉnh, đóng băng), 9 (nhãn), 10 (RQ1, RQ3 — bắt buộc), 11 (tùy chọn). **Phiên bản 1.4 — 18/10/2026.** Bản này đọc được cho mọi thành viên (không chép bảng luật, không ghi ngưỡng đang dùng, không ghi thành phần dữ liệu). Phần chỉ người giữ dữ liệu đọc nằm ở ghi chú riêng của nhóm, không vào repo trước khi khoá nhãn.*

*Nhãn: **[Chốt]** spec gốc · **[Chốt v1.4]** quyết định 17–18/10 đưa vào bản này · **[Đề xuất]** chờ duyệt · **[Suy luận]**.*

**Thay đổi chính so với v1.3 (đọc trước):**

| # | Đổi | Mục |
|---|---|---|
| 1 | Chia một lần ~65/35 → **kiểm tra chéo 5 phần theo họ**; D1/D2 chỉ để phát triển | 4.3 |
| 2 | Vế an toàn RQ1: **cận trên Clopper–Pearson của FNR < 10 %**, đếm theo **tình huống** | 6.1, 6.5 |
| 3 | Các phương án có lớp LLM: stack chỉ để lấy xác suất thô; **route tính offline** theo từng phần | 5.3, 5.4 |
| 4 | Ablation định nghĩa lại bằng cơ chế sẵn có (không thêm cờ) | 5.4 |
| 5 | Giờ gửi `at`: chạy kịch bản trong khung giờ khớp `at`, không ép đồng hồ; **bỏ FakeClock** | 5.2 |
| 6 | Tái lập: so trường đã chuẩn hoá (bỏ mã ticket), có bản sao bảng cache | 5.5 |
| 7 | Manifest ghi `policy_sha256` (không dùng `policy_version_id`) | 5.1 |
| 8 | Calibrator **riêng từng phương án và từng phần**; chọn biến thể xác suất **lồng trong từng phần** | 5.3 |
| 9 | Thiếu ca L2 hoặc AUC < 0,7 → ngưỡng trên = 1,01 (ghi trước) | 5.3 |
| 10 | FNR báo riêng nhóm tình huống có yếu tố M5 không thấy | 6.1 |
| 11 | Bỏ test gọi `/api/eval/*` (không có route này); bỏ cổng cỡ mẫu theo nhãn khỏi bản này | 9 |
| 12 | Bản đo có 2 model phân loại (D-52, D-53): kiểm trùng câu bắt buộc; manifest ghi `clf_mode`, τ, SHA | 4.3, 5.1, 5.4 |

---

## 0. Ngữ cảnh nạp sẵn

### 0.1. Khối ngữ cảnh chung (CTX-1.1, rút gọn cho file này)

**Đề tài:** AI Agent tự động hóa hỗ trợ IT Service Desk cấp 1 với Human-in-the-Loop. Ba mục tiêu: Obj 1 (50–60 %) agent L1; Obj 2 (30–40 %) HITL — M5 quyết định khi nào cần người (đóng góp chính), M6 phê duyệt, M7 audit; Obj 3 (0–20 %) đánh giá — M8.

**Nguyên tắc:** Objective quyết định xây gì → Phase quyết định khi nào → RQ chỉ quyết định đo gì. An toàn: giảm False Negative trước.

**Luồng 20 bước và 8 điểm log:** như các file `build/` khác. File này dùng **điểm log 4** (B12–B14, quyết định rủi ro: `decided_by`, `route`, xác suất thô, xác suất đã hiệu chỉnh, cách lấy xác suất, `kb_gap`) và **điểm log 8** (B20, kết thúc).

**Hằng số liên quan:** ngưỡng dưới/trên của M5 nằm trong `policy.json` (`constants`) — **bản này không ghi giá trị**; ngưỡng dùng trong báo cáo được chọn lại ở từng phần của kiểm tra chéo (mục 5.3). Ma trận chi phí mặc định tỉ lệ bỏ sót/duyệt 10:1 (Q9) → ngưỡng dưới lý thuyết = 1/10 (hàm ngưỡng dưới lý thuyết của `decision_math`).

**Bất biến dùng ở đây:** (10) ngưỡng và calibrator chỉ fit trên phần huấn luyện; (13) mọi chỉ số tính trên ticket lá (`is_parent = false`, D-30); (1) M5 không đọc câu người dùng.

---

## 1. Mục đích

M8 sinh **bằng chứng** cho đóng góp: kiến trúc lai luật + LLM có hiệu chỉnh quyết định "khi nào cần người" tốt hơn chỉ-luật và chỉ-LLM, mà không làm an toàn tệ đi quá biên chấp nhận (RQ1); chẩn đoán chủ động giảm lượt hỏi lại (RQ3) **[Chốt]**.

Ba yêu cầu không thỏa hiệp **[Chốt]**:
1. **Không rò rỉ:** calibrator, ngưỡng, biến thể xác suất chỉ chọn trên phần huấn luyện của từng phần; số báo cáo tính trên phần đo.
2. **Tái lập:** người thứ hai chạy lại từ cấu hình đã lưu ra cùng kết quả (định nghĩa "cùng" ở 5.5).
3. **Tách vai:** người xây M5 không chạy thực nghiệm, không tự xác nhận cổng của M5.

**M8 khác M9:** M8 offline, theo lô, dữ liệu đã khoá, chỉ khi `EVAL_MODE=true` (`app/eval/__init__.py` từ chối import khi khác). M9 chạy live. Không dùng chung code **[Chốt 17.9.4]**.

### 1.1. RQ → lần chạy → chỉ số

| RQ | Bắt buộc? | Lần chạy (5.4) | Chỉ số chính |
|---|---|---|---|
| RQ1 — lai có giảm chi phí sai lầm so với chỉ-luật, chỉ-LLM? | **Bắt buộc** | Thủ công, Full-auto, Chỉ-luật, Chỉ-LLM, Hybrid, Hybrid-guarded | Chi phí kỳ vọng/ticket, FNR + cận trên, FPR, escalation rate, ECE, Brier |
| RQ3 — chẩn đoán chủ động giảm bao nhiêu lượt hỏi lại? | **Bắt buộc** | Hybrid bật/tắt `ENABLE_PROACTIVE_DIAGNOSIS` | Lượt hỏi lại TB, giải quyết một lượt, độ chính xác route — báo theo intent |
| Ablation | **Bắt buộc** | Định nghĩa ở 5.4 (không thêm cờ mới) | Như trên theo thành phần |
| Ablation RAG 4 cấu hình (D-25) | Nên có | — | **Không làm trong bản đo** (KB nhỏ, Recall@5 chạm trần) → ghi giới hạn |
| RQ2 — so ba cách lấy xác suất | Tùy chọn | — | **Không làm**; thay bằng so "tự nêu" với "hỏi 5 lần" trên dữ liệu phát triển nếu còn thời gian |
| RQ4, RQ5 | Tùy chọn | — | **Không làm** (ghi lý do trong báo cáo: thời gian, phần cứng) |
| Intent: model so với LLM (D-53) | Nên có | Không cần lượt riêng: B3 chỉ **ghi điểm** model (`model_probs` ở audit B3), LLM vẫn quyết intent → so offline trên cùng lượt S1. Cascade bỏ (D-53) | Macro-F1, exact-match câu nhiều ý — số kỹ thuật Obj 1, không phải RQ |

---

## 2. Sơ đồ cấu tạo

```
eval/                                  (dữ liệu, KHÔNG nằm trong backend image)
 ├─ scenarios/*.yaml  ──┐              kịch bản + nhãn 3 mức (2 lượt gán)
 ├─ retrieval/*.yaml  ──┤              bộ câu truy hồi (chỉ số kỹ thuật)
 └─ SPLIT.md          ──┤              thẻ/họ → phần 1..5, seed, sha256 từng file (CI kiểm sau khoá nhãn)
                        ▼
backend/app/eval/  (chỉ import khi EVAL_MODE=true)
 dataset.py    nạp + kiểm schema + kiểm mã băm SPLIT.md
 split.py      gán họ → 5 phần (CV), seed cố định; mọi kịch bản của 1 họ cùng 1 phần
 actors.py     ScriptedUser · SimApprover · (FaultInjector chỉ khi có kịch bản dùng `faults`)
 runner.py     (cấu hình × kịch bản): reset mock → submit qua API thật → lái actors → đọc điểm log 4, 8, lineage
               → predictions.jsonl (hợp đồng v1.1, mục 5.6). Chạy TUẦN TỰ (1 luồng).
 calibrate.py  theo từng phần: fit calibrator + chọn ngưỡng + chọn biến thể trên phần huấn luyện (LeakageError nếu lẫn phần đo)
 offline.py    tính route của các phương án có LLM từ xác suất thô + calibrator/ngưỡng của từng phần
 metrics.py    công thức chỉ số (mục 6) — đã có (T29)
 stats.py      Clopper–Pearson, bootstrap theo họ — đã có (T29)
 report.py     bảng + biểu đồ → eval/reports/<run_id>/
```

**Vì sao chạy qua API thật:** số liệu phản ánh hệ thống đầy đủ (B3 phân sai → Action sai → M5 quyết khác). Quyết định của M5 và xác suất thô đọc từ **audit điểm log 4** — cùng nguồn dashboard dùng **[Chốt 9.1]**. Phần **tính lại route offline** (5.3) chỉ dùng chính xác suất thô đã ghi ở điểm log 4, cộng toán của `app.risk.decision_math` (một nguồn toán, D-37) — không có đường đo thứ hai cho xác suất.

## 3. Công nghệ

| Thành phần | Công nghệ | Ghi chú |
|---|---|---|
| Dữ liệu | YAML + Pydantic | validate khi nạp |
| Chạy | httpx, API backend, `EVAL_MODE=true`, `LLM_CACHE_MODE=eval` | cache B14 tái lập được (D-39); **B2 không bao giờ cache** (5.5) |
| Thời gian | Giờ thật của stack; khung giờ khớp `at` (5.2); `APPROVAL_SLA_MINUTES_DEV` cho ca hết hạn duyệt | **bỏ FakeClock** |
| Hiệu chỉnh | `app.risk.calibrator` (Platt, temperature; tùy chọn làm mượt nhãn — hàm dùng chung, không viết bản thứ hai trong `eval/`) | D-37 |
| Thống kê | `app.risk.decision_math.clopper_pearson_upper`, `app.eval.stats` | đã có |
| Biểu đồ | matplotlib (chỉ trong môi trường chạy báo cáo), xuất PNG + CSV | |

## 4. Dữ liệu

### 4.1. Schema kịch bản

Giữ như v1.3 (`id`, `family`, `source`, `requester`, `at`, `faults`, `turns`, `gold{intents, need_type, expected_route, expected_exit, approver_decision, gold_doc_ids, action, facts}`, `labels`), thêm:

```yaml
family: TH042          # với thẻ mới: 1 thẻ = 1 họ = 1 tình huống (các câu của thẻ là biến thể)
gold:
  hidden_factor: false # true = mức cần người của tình huống phụ thuộc yếu tố M5 không thấy (6.1). Người giữ dữ liệu đặt,
                       # người gán nhãn không đặt, không thấy
```

**Quy tắc gán nhãn [Chốt 8.1]:** "Một L1 có kinh nghiệm có muốn xem trước khi làm không, và việc này có nên làm không?" Người gán nhãn **không mở `policy.json`**. Đơn vị gán là **tình huống** (thẻ/họ); nhãn nhân ra các câu của tình huống.

### 4.2. Dữ liệu dùng ở đâu [Chốt v1.4]

| Bộ | Dùng cho | Không dùng cho |
|---|---|---|
| D1, D2 (17 tình huống cũ) | Phát triển harness, chạy thử, probe xác suất, chỉnh prompt | Fit calibrator, chọn ngưỡng, số báo cáo |
| Thẻ mới (sau khoá nhãn 25/10) | Kiểm tra chéo 5 phần → mọi số RQ1, RQ3 | — |

Lý do: D1/D2 đã được nhìn khi chỉnh prompt và probe, và quá ít tình huống đi qua lớp LLM để hiệu chỉnh.

### 4.3. Kiểm tra chéo 5 phần [Chốt v1.4]

```python
def make_folds(scenarios, k=5, seed=20260925):
    fams = sorted(families(scenarios))                    # đơn vị = họ (thẻ)
    strata = stratify(fams, by=("intent", "expected_route"))   # phân tầng theo intent + nhãn tình huống
    folds = assign_round_robin(strata, k, seed)           # MỌI kịch bản của 1 họ vào CÙNG 1 phần
    assert all(len(set(fold_of(f) for s in fam_scenarios(f))) == 1 for f in fams)
    write_split_md(folds, seed, sha256_of_files())        # SPLIT.md: họ → phần, kèm mã băm
```

- Với phần `i`: **phần đo** = phần `i`; **phần huấn luyện** = 4 phần còn lại. Mỗi lượt tính có `LabeledSample.split = "calibration"` cho phần huấn luyện và `"test"` cho phần đo — `require_calibration_split` chặn lẫn (`LeakageError`).
- Mỗi tình huống được đo đúng một lần (ở phần của nó). Số báo cáo = gộp 5 phần đo.
- **Không hạ chuẩn** khi thiếu dữ liệu: báo đúng cỡ mẫu thật và nêu vế nào không kết luận được.
- **Đồng thuận:** Cohen's κ trên nhãn tình huống ≥ 0,6; thấp hơn → thống nhất lại tiêu chí, gán lại phần lệch, ghi biên bản **[Chốt]**.
- **Rò rỉ sang model phân loại (P11 §3.4) [Chốt v1.4 — BẮT BUỘC trước khoá nhãn]:** bản đo chạy B2 ở chế độ `review` (D-52) và B3 ghi điểm (D-53) — cả hai model đều có mặt trong luồng. Mọi câu của thẻ phải được kiểm trùng với dữ liệu huấn luyện của `injection-clf` và `intent-clf` (chuẩn hoá khớp chính xác hoặc cosine bge-m3 ≥ 0,90, theo P11 §3.4; script `training/common/dedup_vs_m8.py` — chưa có, phải viết). Câu trùng: sửa câu của thẻ (không huấn luyện lại model sát giờ cắt); báo số câu đã sửa.

## 5. Chạy thực nghiệm

### 5.1. Cấu hình và manifest

```python
class RunConfig(BaseModel, frozen=True):
    strategy: Literal["hybrid", "llm_only"]            # chiến lược chạy trên stack (5.4); các phương án khác tính từ hai lượt này
    enable_proactive_diagnosis: bool = True             # RQ3 / ablation bỏ tool
    prob_method: Literal["self_report", "sampling_k5"]  # = giá trị của bản đóng băng
    llm_roles: dict                                     # provider/model từng vai
    seed: int = 20260925

run_id = sha256(config_json | dataset_sha256 | git_commit)[:12]
```

`manifest.json` ghi: cấu hình, `run_id`, commit (tag), mã băm dữ liệu + `SPLIT.md`, `kb_version`, **2 model phân loại** — `clf_mode` của B2 (`review`), ngưỡng τ của B2, model LLM chấm của B2, SHA của `injection-clf` và `intent-clf` (D-52, D-53) — ngưỡng chống spam đã nới cho harness (D-54), **`policy_sha256`** (đọc ở điểm log 4; `policy_version_id` hiện luôn NULL — không dùng), phiên bản + sha256 prompt, model + phiên bản, máy chạy, giờ bắt đầu/kết thúc, số ca theo khung giờ (5.2). Calibrator/ngưỡng của từng phần ghi ở `folds/<i>.json` (5.3). **Không có manifest thì không đưa số vào báo cáo.**

### 5.2. Diễn viên và giờ gửi

| Diễn viên | Hành vi |
|---|---|
| `ScriptedUser` | Trả lời câu hỏi B11 theo `turns` (B11 hỏi tối đa 2 slot mỗi lượt → có thể phải ghép 2 câu trả lời); hết câu phù hợp → dừng kịch bản theo giới hạn thời gian của harness, ghi `timeout` (không chờ 24 giờ); xác nhận B19 theo `on_confirm` |
| `SimApprover` | Làm theo `gold.approver_decision`; `ignore` → hết hạn duyệt với `APPROVAL_SLA_MINUTES_DEV` (chỉ dev/test) |
| `FaultInjector` | Chỉ dựng nếu có kịch bản dùng `faults` (hiện không có) |

**Giờ gửi `at` [Chốt v1.4]:** stack dùng giờ thật; harness **không** ép đồng hồ. Trước mỗi kịch bản, runner so "`at` có trong giờ hành chính không" (theo `business_hours` của cấu hình) với giờ hiện tại của stack; lệch → **hoãn** kịch bản sang lượt chạy ở khung giờ khớp (không bỏ, không chạy lệch). Mỗi bản ghi lưu giờ chạy thật. Lý do: lớp luật và ngữ cảnh B14 đọc giờ lúc chạy; chạy lệch làm nhãn (gán theo `at`) và quyết định lệch nhau, cache cũng trượt. Hệ quả lịch: cần cả khung trong giờ và ngoài giờ trong tuần 8.

**Chiến lược `manual`** không chạy hệ thống: mọi ca có hành động coi là "qua người"; chi phí tính giải tích; thời gian xử lý đo trên một mẫu làm tay **[Chốt]**.

### 5.3. Hiệu chỉnh, ngưỡng, biến thể — theo từng phần [Chốt v1.4]

Với **mỗi phương án có lớp LLM** (Hybrid, Chỉ-LLM, Hybrid-guarded) và **mỗi phần** `i`:

```python
# giả mã — tên hàm thật lấy từ app.risk.decision_math / app.risk.calibrator
def fit_fold(train, variants, cost=DEFAULT_COST):
    # train: bản ghi phần huấn luyện có xác suất thô của từng biến thể (5.4); split = "calibration"
    best = None
    for v in variants:                                   # chọn biến thể LỒNG trong phần — không nhìn phần đo
        llm = [r for r in train if goes_to_llm(r, phuong_an)]
        cal = fit_platt(samples(llm, v), now=RUN_TIME)   # calibrator RIÊNG phương án × phần
        th = select_thresholds([cal.transform(r.raw[v]) for r in llm], [r.expected_route for r in llm], cost)
        if too_few_l2(llm) or auc_l2(cal, llm, v) < 0.7:
            th = th.with_upper(1.01)               # bỏ đường LLM → L2 (ghi trước)
        score = expected_cost_on(train, cal, th, v)
        best = min(best, (score, v, cal, th))
    return best    # ghi folds/<i>.json: phương án, biến thể chọn, version calibrator, ngưỡng, độ nhạy 5/10/20
```

- **Thiếu ca L2** = phần huấn luyện có **dưới 10 ca** gold = ESCALATE_L2 trong số ca đi lớp LLM **[Đề xuất — chốt trước khi mở nhãn]**. AUC tính giữa xác suất đã hiệu chỉnh và "gold = ESCALATE_L2".
- **Platt làm mượt nhãn:** tùy chọn của `fit_platt` (`app/risk/calibrator.py`); dùng khi phần huấn luyện **tách hẳn** (một lớp nằm hoàn toàn ở một phía) — hàm tự báo trường hợp này.
- Calibrator phải đạt `a > 0`; fit lỗi → phương án đó ở phần đó dùng "chưa hiệu chỉnh" (không bao giờ AUTO, D-38) và ghi lý do.
- **Route trên phần đo** = `decision_math.route_for(cal.transform(raw), ngưỡng dưới, ngưỡng trên)` của phần cho ca đi lớp LLM; `kb_gap` chặn AUTO (D-34) như trong hệ thống; ca có luật khớp giữ route của luật.
- Báo cáo: mỗi biến thể được chọn ở bao nhiêu phần; ngưỡng từng phần; độ nhạy 5/10/20.

**Vì sao không đọc route của stack cho các phương án có LLM:** bản đóng băng chạy **chưa hiệu chỉnh** (D-38: lớp LLM chỉ ra "chờ duyệt" hoặc "chuyển L2"). Route của stack vì vậy không phản ánh quy trình "fit calibrator + chọn ngưỡng theo chi phí". Số RQ1 của các phương án có LLM là **ước lượng của quy trình đó**, tính bằng kiểm tra chéo trên xác suất thô đã ghi — phải nói rõ trong báo cáo.

### 5.4. Ma trận chạy (Phase 10)

**Lượt chạy trên stack** (thẻ mới, cùng tag, cùng máy, 1 luồng):

| # | Lượt | Lấy được |
|---|---|---|
| S1 | `STRATEGY=hybrid`, bật chẩn đoán | Route của luật + xác suất thô của ca không khớp luật (biến thể "có trích đoạn") + điểm log 8 |
| S2 | `STRATEGY=llm_only`, bật chẩn đoán | Xác suất thô cho **mọi** ca có hành động (cả ca khớp luật) |
| S3 | `STRATEGY=hybrid`, **tắt** chẩn đoán | RQ3 + ablation bỏ tool |

**Biến thể xác suất (offline, script):** "có trích đoạn" (S1/S2), "không trích đoạn" (`estimate(action, ctx, [])`, `kb_gap` lấy theo bằng chứng **gốc** của ca để biến thể này không bị chặn AUTO giả), "lấy max" của hai biến thể. Đầu vào B14 dựng lại từ `llm_calls.prompt_full` (có khi EVAL).

**Phương án → nguồn số:**

| Phương án | Tính từ |
|---|---|
| Thủ công | Giải tích |
| Full-auto | Giải tích (mọi ca có hành động = AUTO); ghi chú "B17 vẫn chặn khi chạy thật" |
| Chỉ-luật | S1: ca luật khớp giữ route; ca không khớp → HITL |
| Chỉ-LLM | S2 + 5.3 |
| Hybrid | S1 (luật) + 5.3 (ca không khớp) |
| Hybrid-guarded | S1 (luật chặn/cần duyệt) + S2 (xác suất của ca luật cho phép) + 5.3; route ≥ route của luật |

**Ablation [Chốt v1.4]:** bỏ lớp luật = Chỉ-LLM; bỏ lớp LLM = Chỉ-luật; **bỏ tool = tắt chẩn đoán chủ động (S3)** — không tắt kiểm đích bằng tool ở B11 vì đó là lớp an toàn; **bỏ RAG ở M5 = biến thể "không trích đoạn"** — không tắt RAG ở B9/B11 vì khi đó mọi hành động dừng ở "không có căn cứ" (đo được điều hiển nhiên, không đo được đóng góp).

**Ca dừng ở B2 do model nghi** (E1 `injection_suspected`, D-52) không tới M5: không vào mẫu số an toàn, báo số ca theo phương án; chỉ số M5 so giữa các phương án tính trên **phần giao** (ca tới M5 ở mọi phương án so). Báo thêm số cảnh báo `requester_probe` và số câu kích hoạt bước "dính nhau" (D-54, D-55).

**Ca không tới điểm log 4** (hết hạn lượt, lỗi chưa lường trước trong B12–B14): tính là **chuyển L2** với mọi phương án có LLM, không bỏ khỏi mẫu số. Báo số ca này.

### 5.5. Tái lập [Chốt v1.4]

- Cùng tag, cùng mã băm dữ liệu và `SPLIT.md`, cùng `policy_sha256`.
- Người chạy lại nạp **bản sao bảng `llm_cache`** của máy chạy chính (cache nằm trong DB từng máy).
- "Cùng kết quả" = cùng giá trị các trường điểm log 4 và 8 của bản ghi **sau khi bỏ `ticket_id`, `parent_ticket_id`** (uuid4 mỗi lần) và sắp theo `scenario_id`.
- B2 không cache (prompt có biên ngẫu nhiên) → số ca B2 cho kết quả khác giữa hai lần được **đếm và báo**, các ca đó loại khỏi phép so; không sửa code sát giờ cắt.

### 5.6. Hợp đồng `predictions.jsonl` v1.1

Giữ v1 (`app/eval/predictions.py`), thêm: `fold` (1..5), `kb_gap`, `hidden_factor`, `run_started_at`, `in_business_hours`. Xác suất của các biến thể offline ghi file riêng `probs.jsonl` (`scenario_id`, `variant`, `raw_prob`), không sửa bản ghi stack.

## 6. Công thức chỉ số

Mọi chỉ số trên **ticket lá** (D-30). Đơn vị an toàn = ticket lá có hành động đi tới M5.

### 6.1. An toàn và quyết định

Ký hiệu `pred`, `gold` ∈ {AUTO, HITL, ESCALATE_L2}; "cần người" = `gold ≠ AUTO`.

| Chỉ số | Công thức | Ghi chú |
|---|---|---|
| **FNR theo tình huống** (quan trọng nhất) | #(tình huống cần người có **ít nhất một** câu pred = AUTO) / #(tình huống cần người) | Cận trên Clopper–Pearson 95 % **một phía** `beta.ppf(0.95, k+1, n−k)` (`decision_math`); báo thêm hai phía |
| FNR theo câu | như v1.3 (`metrics.safety`) | báo phụ |
| FPR | #(gold = AUTO ∧ pred ≠ AUTO) / #(gold = AUTO) | |
| Accuracy 3 lớp, ma trận 3×3, macro-F1 | | |
| **Chi phí kỳ vọng/ticket** | trung bình `COST[gold][pred]` | đơn vị: một lượt duyệt |
| ECE, Brier | 10 bin đều, chỉ ca đi lớp LLM; trước = xác suất thô, sau = đã hiệu chỉnh (của phần) | |
| Phân bố `decided_by` | % ca do luật / do LLM | |
| **FNR nhóm yếu tố M5 không thấy** | FNR theo tình huống trên `hidden_factor = true`; và FNR chính báo **cả có và không** nhóm này | Nhóm này đo giới hạn của thiết kế (M5 không đọc câu, không thấy các yếu tố đó), không phải lỗi hiệu chỉnh |

**Vì sao đo ở điểm log 4:** RQ1 hỏi M5 có **đưa đúng ca tới người** không; người duyệt đồng ý hay từ chối là hành vi của `SimApprover`.

### 6.2. Hiệu quả (điểm log 8 + `turns`)

Như v1.3 (automation, escalation thô + có trọng số 70/20/10 và độ nhạy, deflection, lượt hỏi lại TB, giải quyết một lượt, độ trễ, chi phí LLM). Với phương án có LLM, route tính offline (5.3) → automation và escalation tính từ route offline cho ca đi lớp LLM; ghi rõ chỗ khác với điểm log 8 của stack.

### 6.3. Kỹ thuật

Như v1.3.

### 6.4. So sánh giữa phương án

Bootstrap **theo họ** 2.000 lần, seed cố định (`app.eval.stats`); hiệu giữa Hybrid và từng phương án bằng bootstrap ghép cặp theo họ. Khoảng chứa 0 → "chưa đủ bằng chứng khác biệt".

### 6.5. Tiêu chí kết luận RQ1 [Chốt v1.4]

"Hybrid tốt hơn" khi **cả hai**:
1. **Chi phí:** khoảng tin cậy của hiệu chi phí (Hybrid − Chỉ-luật, Hybrid − Chỉ-LLM) nằm hẳn dưới 0.
2. **An toàn:** cận trên một phía 95 % của FNR theo tình huống, trên **các tình huống cần người đi qua lớp LLM** của Hybrid, **< 10 %**.

Lý do vế 2: ca khớp luật thì Hybrid quyết y như Chỉ-luật, mà Chỉ-luật đưa mọi ca không khớp tới người — nên FNR của Hybrid không thể thấp hơn Chỉ-luật; câu "không tệ hơn" chỉ kiểm được dưới dạng biên chấp nhận trên phần lớp LLM quyết. Không đạt vế nào thì báo trung thực vế đó.

## 7. Đầu ra báo cáo [Chốt cổng 10]

| # | Đầu ra | Nguồn |
|---|---|---|
| 1 | Bảng so sánh phương án (chi phí, FNR theo tình huống + cận trên, FPR, escalation thô/trọng số, automation) | 5.4 |
| 2 | Bảng ablation | 5.4 |
| 3 | Reliability diagram trước/sau + ECE, Brier (gộp 5 phần đo) | 5.3 |
| 4 | Chi phí theo ngưỡng (một phần minh hoạ) + ngưỡng từng phần + ngưỡng dưới lý thuyết + độ nhạy | 5.3 |
| 5 | Bảng `decided_by`; số lần chọn từng biến thể | S1, 5.3 |
| 6 | 10 ca sai tiêu biểu kèm audit điểm 4 | S1 |
| 7 | Bảng RQ3 theo intent | S1 vs S3 |
| 8 | FNR nhóm yếu tố M5 không thấy | 6.1 |

Mỗi bảng ghi `run_id`. Kết quả không ủng hộ giả thuyết vẫn báo trung thực **[Chốt]**.

## 8. Cấu hình

`EVAL_MODE=true`, `LLM_CACHE_MODE=eval`, `COST_MATRIX` (10:1), `OPERATING_MIX={routine: .7, approval: .2, sensitive: .1}`, `BOOTSTRAP_N=2000`, `SEED=20260925`, `CV_K=5`.

## 9. Kiểm thử và tiêu chí đạt (cổng 8)

| Loại | Test | Đạt khi |
|---|---|---|
| Unit | Công thức mục 6 trên dữ liệu tính tay (gồm FNR theo tình huống) | khớp 1e-9 |
| Unit | Clopper–Pearson 0/60 | ≈ 0,0487 |
| Unit | `fit_fold` lẫn bản ghi phần đo | `LeakageError` **[Chốt]** |
| Unit | `make_folds` | không họ nào ở 2 phần; cùng seed → cùng kết quả |
| Unit | Platt trên dữ liệu tổng hợp lệch | ECE giảm **[Chốt]** |
| Unit | Chọn ngưỡng trên dữ liệu tổng hợp đã hiệu chỉnh | ngưỡng dưới gần 1/10 **[Chốt]** |
| Unit | Thiếu ca L2 / AUC < 0,7 | ngưỡng trên = 1,01 |
| Integration | 20 kịch bản × 2 lần (LLM giả) | bản ghi đã chuẩn hoá (5.5) giống hệt |
| Integration | Chạy thử S1–S3 trên 20 kịch bản bất kỳ | mọi lượt chạy xong — **không đọc kết quả** **[Chốt]** |
| CI | Mã băm dữ liệu so với `SPLIT.md` (sau khoá nhãn) | lệch → đỏ |

*(Bỏ so với v1.3: test gọi `/api/eval/*` — backend không có route này; module `eval` đã tự từ chối import khi không `EVAL_MODE`.)*

## 10. Phụ thuộc, vai trò

- **Phụ thuộc:** audit điểm 1, 3, 4, 8 + `lineage`; `llm_calls.prompt_full` (EVAL); cache `llm_cache`; `app.risk.decision_math`, `app.risk.calibrator`.
- **Vai trò [Chốt]:** người không xây M5 chạy RQ1, RQ3; người thứ hai chạy lại một lần; người xây M5 không chạy.
- **Sau tag `v1.0-freeze`:** chỉ sửa lỗi, mỗi thay đổi ghi lý do; không sửa code sau khi đã nhìn kết quả **[Chốt]**. Script đo offline (5.4) gộp trước tag hoặc ghi rõ ngoại lệ "script đo, không đổi hành vi".

## 11. Việc còn mở

- Ngưỡng "thiếu ca L2" = 10 (5.3) — [Đề xuất], chốt trước 25/10.
- Script kiểm trùng câu với dữ liệu huấn luyện 2 model (4.3) — người viết, hạn: chốt trước khoá nhãn.
- Lệnh xuất/nhập `llm_cache` cho người chạy lại — làm được sau tag (không đổi hành vi).

## 12. Nhật ký

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 25/09/2026 | 1.0–1.1 | Tạo file; kiểm rò rỉ model phân loại; D-32 |
| 09–13/10/2026 | 1.2–1.3 | `gold.action`, `gold.facts`; 20 fact |
| 18/10/2026 | 1.4 | Bản đo có 2 model phân loại (B2 `review`, B3 ghi điểm — D-52, D-53): kiểm trùng câu bắt buộc, manifest ghi `clf_mode`/τ/SHA, ca E1 B2 ngoài mẫu số M5, so trên phần giao. Kiểm tra chéo 5 phần; D1/D2 chỉ phát triển; vế an toàn theo tình huống (< 10 %); route offline; calibrator theo phương án × phần; biến thể lồng; ngưỡng trên 1,01 khi thiếu L2/AUC < 0,7; ablation định nghĩa lại; giờ `at`; bỏ FakeClock; tái lập; `policy_sha256`; FNR nhóm yếu tố không thấy; bỏ test `/api/eval/*`; bỏ cổng cỡ mẫu theo nhãn và giá trị ngưỡng khỏi bản đọc chung |
