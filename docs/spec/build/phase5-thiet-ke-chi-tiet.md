# Phase 5 — Thiết kế chi tiết (đủ 4 loại yêu cầu: T22a luật, T20 phân loại + tách ý, T23 B2, T24 executor + hoàn tác)

*Thuộc bộ `build/`. Phiên bản **0.2 — 10/10/2026** (0.2: **T22a đóng** `2ffb005`; kế hoạch sau T22a theo phiên PHAN-TICH-P5 — T23a viết đủ để code ngay (mục 6), T20 tách T20a/T20b, bật intent dời sang T24, lịch mục 8; D-44…D-46. Bản 0.1f — 09/10/2026 (bảng 4.2 `procedure_doc` **chốt theo K2 thật** 18 bài; mục 0.2 theo luật git 4.0 + thư mục chính dùng chung + giao thức Phase 5–6 (sửa 13:00); mốc code `3ff63e1`). Lớp luật T22a đã **dựng thử trên engine thật** ở bản sao sạch của `1455b55`: 57 ca của bảng 4.7 đúng cả 57; lượt thử lộ 13 test cũ + 2 file ngoài danh sách phải đổi — mục 4.7b. **T22a viết đủ để code ngay**; T20, T23, T24 ở mức khung (P-x chốt khi mở chặng, sau khi soát code mới nhất). Nguồn: `huong-dan-xay-dung-he-thong-2.md` §5 Phase 5, §7.1; `NGU-CANH-DAY-DU.md` Phần I §6.3 (bảng luật); `build/decisions.md` §1.1 (R01–R20), D-34; `B12-B14` v1.2 (DSL §4.2); `B11` v1.5 (slot, `Action`); `P8` §4; `claude/phase5-6-phan-tich-va-chia-chang.md` (G5-x, lịch). Code đã đọc trên máy tại `aac90b1`; soát lại tại `1455b55` (03/10) và `3ff63e1` (09/10): mọi file T22a sửa (`policy.json`, `slots.yaml`, `action_metadata.yaml`, `domain/*`, `risk/*`, `tools/`, `mock_services/`, `scripts/`) **không đổi** từ `632e05a`; `3ff63e1` chỉ thêm tài liệu + M9 B2 (`backend/app/monitor/`, khối M9 của `worker.py`); cổng kiểm gồm cả gate4 (`make verify G=234`).*

*Nhãn: **[Chốt]** spec gốc đã chốt · **[Chốt 01/10]**, **[Chốt 09/10]** Tuấn Anh chốt ngày đó · **[Đề xuất]** Claude chat đề xuất, Tuấn Anh soát khi duyệt PLAN · **[Suy luận]** agent phải kiểm lại trên code.*

**Kế hoạch tóm tắt (đọc trước):**

| Thứ tự | Chặng | Nội dung | Tầng | DỪNG | Model | Mở khi |
|---|---|---|---|---|---|---|
| 1 | **T22a** | 15 luật R01–R15 + fact mới + nguồn `action.params` + `build_ctx` theo đích + khai báo 3 intent (không bật) + seed 3 trường + `rule_coverage.py` (mục 4) | **A** | 2 | **Opus** | Cây chính sạch + bảng 4.2 chốt + đã pull `3ff63e1` — **đạt 09/10** (làm sớm — "chưa tính qua cổng 5") |
| 2 | **T20** | B3/B5/B6/B11 đủ 4 intent, tách ticket cha/con (D-31), bật `ENABLED_INTENTS` (mục 5) | B (+A cho gom tin cha/con) | 2 | **Opus** | T22a đẩy + K2 gộp (PR #29) + quyết `ml-gan` + **6B đã gộp** (giao thức Phase 5–6 mục 2.3) |
| 3 | **T23** | B2 lớp 3 `injection-clf` (mục 6) | **A** | 1–2 | **Opus** | Quyết `ml-gan` |
| 4 | **T24** | `PLAN` + hoàn tác cho 6 hành động mới (mục 7) | **A** | 2 | **Opus** | T20 |

Mỗi chặng = **một phiên agent mới**. Tối đa 2 phiên coding agent cùng lúc trên cả dự án (lịch: `claude/phase5-6-phan-tich-va-chia-chang.md` mục 5).

---

## 0. Cách dùng file này

- Đây là **bản thiết kế hiện thực duy nhất của Phase 5**. Lệch với `B03-B05`, `B11`, `B12-B14`, `B17-B18`, `P8` → **file này thắng**, trừ 13 bất biến toàn cục và mục **[Chốt]** gốc.
- Code đã xanh ở Phase 1–4 mà khác chữ ở đây → agent **báo**, không tự sửa code cũ.
- Agent đọc: mục 0, 1, 2 rồi **đúng mục của chặng**.
- **Lời mở chặng thắng mục 0.2 khi lệch về thao tác git/stack** (lời mở viết theo trạng thái điều phối mới nhất).

### 0.1. Sự thật của code (`aac90b1`, không đổi tới `3ff63e1`) mà Phase 5 phải theo

| Chủ đề | Code hiện có | Hệ quả |
|---|---|---|
| Luật | `config/policy.json`: `constants`, `business_hours`, `rules` (R16–R20). `Rule` (`domain/policy.py`, `extra=forbid`): `id ^R\d{2}$`, `type`, `intent`, `action` (chuỗi/danh sách), `conditions {all|any}`, `description` | T22a chỉ **thêm** luật, không đổi R16–R20 |
| DSL | `FACT_SOURCES`: `action` (8 trường), `action.facts` (= `FACT_KEYS`), `requester` (6 trường), `time` (`within_business_hours`), `ctx` (`target_is_other`). Toán tử `eq ne in not_in lt lte gt gte is_true is_false`; kiểu chặt; thiếu fact → **sai** (kể cả `ne`, `not_in`, `is_false`) | Không có `action.params`; không so fact với fact (G5-2, Q-5-4) |
| Khởi động | `check_policy_config`: mọi `action` của luật ∈ `slots.yaml intents[rule.intent].action_types` **và** metadata thuộc đúng intent. `check_intent_config`: `ENABLED_INTENTS ⊆ slots.intents`; mọi `action_type` có metadata. `check_plans` + roster: **chỉ intent đang bật** | Khai báo 3 intent mới (slots + metadata) mà **không bật** → khởi động được, không cần `PLAN`/roster |
| B3 | `b03_classify.py:112` bỏ intent ∉ `deps.enabled_intents` | Không bật → không ticket nào của 3 intent mới tới B6–B17 trong T22a |
| `Action` | `domain/action.py`: `type, target, requested_for, scope, privilege_level, reversible, reversibility, data_sensitivity, params, facts`. `build_action` chỉ `vpn` (intent khác → `ValueError` → E9) | `build_action` 4 intent = T20 |
| `facts` | `domain/facts.py`: `FACT_TYPES` (7 fact VPN), `check_facts` kiểm key + kiểu chặt + tập giá trị `cert_status` | T22a thêm fact + tập giá trị |
| `build_ctx` | `risk/context.py:21–33`: `target_is_other = cờ B6 ∨ requested_for ≠ người gửi ∨ facts.device_owner_is_requester is not True` | **G5-1**: sai với đích không phải máy → T22a P5 |
| `RiskContext` | `risk/models.py:11–16`: `requester`, `facts`, `now`, `within_business_hours`, `target_is_other` | T22a **không** sửa file này (giao thức Phase 5–6 mục 2.2) |
| Mutation cũ | `scripts/mutation/mutate_3h.py`: `_CTX_FACTS` (:105, gốc của M-3h-8), `_ESTIMATE` (:106, M-3h-9), `_TARGET` (:107–111, M-3h-10). `test_mutation_n3.py:53` parametrize cố định `mutate_3g/3h/4a` | T22a chỉ đổi `_TARGET`; giữ nguyên dòng `requester=requester, facts=dict(action.facts), now=now,` trong `context.py` (gốc M-3h-8); không đụng `_ESTIMATE` (6B sửa) |
| Tool | Registry đủ 12 tool đọc 4 intent; `PLAN` chỉ VPN | B6/B11/B17 cho 3 intent = T20/T24 |
| Seed mock | 17 người; `nv004` `disabled` (không ghi lý do); `nv006` `terminated`; `svc_backup` (`is_privileged_account=true`, `ad.privilege=admin`); `nv007` email khoá `bad_password`; catalog 7 phần mềm (`license_type`, `requires_approval`); 5 thư mục (`sensitivity`, `owner_department`); 5 dòng quyền | Thiếu `is_service_account`, `disable_reason`, `requires_local_admin` (G5-3) |
| Người duyệt | `config/approvers.yaml` chỉ có `vpn`; `ApproversFile` đòi mọi intent trong `ENABLED_INTENTS` có dòng | T22a không bật intent → không cần; **T20 thêm roster `account`/`software`/`access`** |
| Test luật | `unit/test_policy_rules_vpn.py` (h-rule: `BANG_11_2`, `LUAT_C5`), `test_policy_engine_signature.py`, `test_b12_assess.py` | T22a theo khuôn `LUAT_C5` |

### 0.2. Phối hợp với M9, Phase 6, frontend và phiên git

- **Luật git 4.0 (từ 09/10, `claude/ban-giao-phien-git-09-10.md` mục 4.0):** mọi việc git/GitHub do **phiên chat git** lo — pull/push/merge/rebase trên nhánh chung, PR, comment/issue, tạo/xoá worktree, xếp lượt Docker stack. Agent chặng Phase 5 **được**: sửa code, chạy test/lint, **commit cục bộ** ở DỪNG theo lời mở (đích danh, không `git add -A`, không `--no-verify`). Agent **không** pull/push/merge/rebase, không đụng GitHub/worktree, không dùng Docker stack khi chưa có "OK phiên git" do Tuấn Anh chuyển. Pull đầu chặng do phiên git làm **trước** khi mở agent; push cuối chặng: agent in sẵn phiếu `[YÊU CẦU GIT]` trong MẪU B DỪNG cuối.
- **Thư mục chính dùng chung:** từ lúc phiên git pull đầu chặng **tới hết DỪNG cuối (commit + push)**, không phiên nào khác `pull`/`checkout`/`commit`/`merge` ở thư mục chính; image stack của phiên khác (frontend verify) dựng từ **worktree tạm sạch**. **Không chạy `make ingest` khi chặng còn mở** (đích ingest dựng lại image backend từ thư mục chính → mang code/config dở) — ingest trước khi mở chặng hoặc sau DỪNG cuối. Sau lượt `make verify G=234` của chặng, image stack mang code chặng → bên khác phải dựng lại image sạch.
- **Stack Docker:** một bên một lúc, không có thứ tự lượt. Agent sẵn sàng verify thì hỏi Tuấn Anh "Stack rảnh không?" → Tuấn Anh gửi phiếu "dùng stack" cho phiên git → trả "rảnh" → agent đưa lệnh `make verify G=234` → xong nhắc "trả stack". Không chạy chồng với lượt `make verify G=0` của Phase 6 ở `-m5`.
- **Song song Phase 6 (`claude/giao-thuc-phase5-6.md`, Phase 6 giữ bút):** tối đa 2 agent cùng lúc trên cả dự án; không hai DỪNG tầng A cùng ngày; T22a ↔ 6A chỉ chung `PROGRESS.md` (bên gộp sau: phiên git giữ cả hai mục, agent không tự giải); không thêm module/import `app.eval` vào `backend/app/risk/` (test AST của 6A quét cả thư mục); 6B mở sau khi T22a đẩy; T20 mở sau khi 6B gộp; 6C mở sau khi T24 đẩy. Tin chéo phase qua `claude/tin-p5-sang-p6.md` / `claude/tin-p6-sang-p5.md`.
- **Không** sửa file/khối M9: `worker.py` (khối M9, nay có `monitor_rules_hourly`/`monitor_rules_daily` từ `3ff63e1`), `main.py` khối `# M9`, `backend/app/monitor/*`, migration `*_monitor_*`, `.importlinter`, khối `# M9` trong `settings.py`/`docker-compose.yml`/`.env.example`. Cần sửa `worker.py` ngoài khối M9 → đọc đầu khối M9 trước, báo trong MẪU A.
- Phase 5 thêm trường/biến ở khối riêng có chú thích `# Phase 5`.
- **Báo M9 khi merge:** T22a thêm `reason`/`matched_rule_id` mới (R01–R15) vào điểm log 4 — dashboard "top luật khớp" tự có; T20 bật 3 intent → phân bố intent đổi; T20/T23 bật nguồn `b3_cascade`/`b2_classifier` → báo Duy Anh (luật M9 12/13 đang `pending`, Q-M9-B2-13) và Dương (`PENDING_SOURCES` trong `monitor/metrics.py`).
- **Nơi chạy:** agent Phase 5 code ở **thư mục chính** `~/Documents/AIP_FA26_G8`, nhánh `dev-tuananh` (lệnh stack chỉ chạy được ở đây). Phase 6 ở worktree riêng `-m5` (`m5-tuananh`) → không chung cây.
- **GitHub:** agent trong sandbox không chạy được `gh` → cần đăng gì thì soạn nội dung, Tuấn Anh chuyển phiên git đăng (outbox).
- **PROGRESS.md:** mỗi chặng chèn một mục mới ngay trước `## Dồn về mốc G`; không sửa mục của chặng khác.
- **Luật cho mọi PLAN-5x:** Bước 0 kiểm HEAD đã ở mốc lời mở ghi (phiên git đã pull) — **không tự pull**; sau đó `uv run alembic heads` = 1, `make lint` + unit mốc.

---

## 1. Phạm vi và cổng 5

### 1.1. Trong phạm vi

Đủ 20 luật (T22a); phân loại + tách ý + chẩn đoán + dựng `Action` cho `account`, `software`, `access` (T20); B2 lớp 3 (T23); executor + hoàn tác cho 6 hành động mới (T24).

### 1.2. Ngoài phạm vi

| Việc | Để khi nào |
|---|---|
| Lớp LLM của M5 (B14), calibrator, ngưỡng | Phase 6 (6A làm sớm song song) |
| Luồng đăng ký máy (3-Q38, Q-4-D) | Sau Phase 5 nếu còn thời gian — không thuộc cổng 5 |
| Chẩn đoán lại D-20 | Giữ cờ tắt (Q10) |
| Cổng 5 thủ công (LLM thật) | Mốc G [Chốt `decisions.md` §4] |

### 1.3. Cổng 5 [Chốt `huong-dan` §5.1]

**Tự động:**
- TC01, TC03, TC07, TC08, TC12, TC13, TC15, TC16, TC17, TC18, TC21, TC28 xanh.
- Phần mềm có phí lỗi khi cài → không gọi hoàn tác.
- Ticket cha tổng hợp đúng 6 trường hợp bảng B5 gốc + tổ hợp có cả 3 loại kết quả.
- **20 luật đều có ca khớp và ca suýt khớp; nhiều luật khớp → chặt nhất thắng** ← T22a.

**Thủ công (dồn mốc G):** intent macro-F1 ≥ 0,85 / 40 câu; chặn ≥ 13/15 tấn công, chặn nhầm ≤ 1/30; Recall@5 ≥ 0,8 / 30 câu; ghi chú bàn giao E7 đủ 4 phần.

**Sửa chữ [Đề xuất]:** TC07/TC08 gốc (reset tài khoản quản trị; cấp quyền thư mục tài chính) chạy trên intent thật ở Phase 5 — không còn biến thể VPN của Phase 4 (Q-4-C chỉ cho Phase 4).

---

## 2. Quyết định Phase 5 [Chốt 01/10 — Tuấn Anh đồng ý theo khuyến nghị]

| Mã | Vấn đề | Chốt |
|---|---|---|
| Q-5-1 | T22a làm sớm | Ngay sau commit 4d, trước cổng 4/K2; PROGRESS ghi "chưa tính qua cổng 5" |
| Q-5-2 | Phạm vi T22a | Luật + fact + metadata + test trên `Action` dựng tay. B6 sinh fact cho 3 intent mới = T20 |
| Q-5-3 | Luật đọc tham số | Nguồn mới `action.params` với **danh sách trắng đích danh** `permission_level: str`, `duration_days: int`, kiểu chặt. Lý do: `params` là đúng thứ B17 thực thi và đã băm vào `action_plan_hash` → luật xét đúng hành động thật; `facts` vẫn "chỉ từ tool" |
| Q-5-4 | R09 "vượt cấp quản lý" | = xin quyền vào tài nguyên **phòng ban khác**: fact bool `same_department` (B6 tính từ `check_resource_sensitivity.owner_department` và phòng ban người được cấp quyền lấy từ AD). DSL không so hai fact → fact tính sẵn |
| Q-5-5 | Đếm D2 | Schema kịch bản thêm `gold.action {type, target, requested_for?, params}` + `gold.facts`; `scripts/rule_coverage.py` kiểm kiểu, đối chiếu seed, chạy lớp luật, đếm theo họ |
| Q-5-6 | `procedure_doc` 6 hành động mới | **[Chốt 09/10]** theo K2 thật (18 bài) — bảng 4.2 |

---

## 3. Lỗ hổng xử lý trong Phase 5

Xem `claude/phase5-6-phan-tich-va-chia-chang.md` mục 2: **G5-1** (`build_ctx`), **G5-2** (`action.params`), **G5-3** (seed), **G5-4** (allow phải khẳng định dương), **G5-4b** (gia hạn quyền khác phòng/độ nhạy cao), **G5-5** (schema kịch bản), **G5-6** (Việc treo 19), **G5-7** (Việc treo 26). Tất cả xử lý ở T22a (mục 4), riêng G5-7 kiểm thêm ở T20.

---

## 4. Chặng T22a — đủ 20 luật (tầng A)

**Mục tiêu:** lớp luật phủ đủ bảng §6.3 (20 luật: 7 `allow`, 12 `approval_required`, 1 `deny`); không luật `allow` nào khớp nhờ thiếu dữ kiện; đếm được "ca đi xuống LLM" cho cổng D2.
**Đầu vào:** thư mục chính ở `3ff63e1` (phiên git đã pull 09/10 01:04; hoặc mới hơn chỉ đổi tài liệu/M9), cây sạch. **Đầu ra:** `policy.json` 20 luật; fact mới; nguồn `action.params`; `build_ctx` sửa; 3 intent khai báo (không bật); seed 3 trường; `scripts/rule_coverage.py`; ≥ 60 test luật.
**Nghi thức (tầng A):** `PLAN-T22a.md` + MẪU A · **2 DỪNG** · test-writer viết test bảng 4.7 **trước** code · mutation ×2 lượt + md5 · security-reviewer mỗi DỪNG.
**Model:** Opus (lời mở ghi `/model opus`).

### 4.1. P-x chốt trước (agent không hỏi lại)

| Mã | Chốt |
|---|---|
| **P1** | **Nguyên tắc luật `allow` [Chốt 01/10, G5-4]:** mọi luật `allow` phải **khẳng định dương** mọi điều kiện an toàn mà luật chặt hơn cùng hành động kiểm (vd R01 đòi `target_account_privilege == "standard_user"` chứ không chỉ dựa vào R04 bắt `admin`). Lý do: fact thiếu thì luật chặt không khớp → nếu allow không tự đòi, ca thiếu fact thành AUTO (FN). Mọi luật allow có test "thiếu từng fact → không khớp" |
| **P2** | **Fact mới** (`domain/facts.py`, thêm vào `FACT_TYPES`, kiểu chặt; tập giá trị trong hằng `FACT_VALUE_SETS` — `check_facts` kiểm như `cert_status`). Bảng 4.3. Không đổi 7 fact VPN |
| **P3** | **Nguồn `action.params`** (Q-5-3): `FACT_SOURCES["action.params"] = {"permission_level", "duration_days"}`; `PARAM_TYPES = {"permission_level": str, "duration_days": int}` + tập giá trị `permission_level ∈ {read, write, full}`, `duration_days` 1–365. `fact_view` thêm `"action.params"`: chỉ khoá trong danh sách trắng **và** đúng kiểu (sai kiểu/ngoài tập → coi như **thiếu** → điều kiện sai). `split_fact` nhận nguồn dài nhất trước (đã có) — `action.params.*` không bị nuốt bởi `action.*` |
| **P4** | **Quy ước `requested_for` [Chốt 01/10, G5-7]:** = **người bị tác động** — account: chủ tài khoản đích; access: người được cấp/gia hạn/xem quyền; software, vpn: người gửi (chủ máy kiểm bằng fact). Fact `target_*` (bảng 4.3) mô tả **người `requested_for`**. Ghi vào docstring `Action` + `domain/facts.py`. T22a không đổi B15 (`targets_approver` so `requested_for` — đủ khi theo quy ước này) |
| **P5** | **`build_ctx` (G5-1):** `device_target = action.target.startswith("device:")`; `target_is_other = (cờ B6 is not False) ∨ (requested_for ≠ requester.user_id) ∨ (device_target ∧ facts.device_owner_is_requester is not True)`. VPN không đổi (mọi đích VPN là `device:`). Docstring ghi lý do. Test AST h21 (chỉ đọc 3 khoá state) giữ xanh. Chỉ đổi biểu thức `target_is_other`; dòng `requester=requester, facts=dict(action.facts), now=now,` giữ nguyên (gốc M-3h-8); `risk/models.py` không đổi |
| **P6** | **Khai báo 3 intent, KHÔNG bật** (`ENABLED_INTENTS` giữ `["vpn"]`): `slots.yaml` thêm `account`, `software`, `access` (slot bắt buộc/tùy chọn theo `B11` §4 [Chốt]; `action_types` bảng 4.2; `value_rules` mục 4.2); `action_metadata.yaml` thêm 6 hành động (bảng 4.2). Nếu schema `SlotsFile` đòi điều kiện mà 3 intent mới không thỏa (vd `action` bắt buộc trong `required`) → **DỪNG, Q**, không đổi schema tự ý |
| **P7** | **Seed mock (G5-3)** `mock_services/seed.json` + model đầu ra tool `backend/app/tools/models.py` + model mock tương ứng: user thêm `is_service_account: bool` (`svc_backup` = `true`, còn lại `false`), `disable_reason: "security" \| "other" \| null` (chỉ có giá trị khi `employment_status == "disabled"`; `nv004` = `"security"`); catalog thêm `requires_local_admin: bool` (`autocad` = `true`, còn lại `false`). Test mock + test tool-vs-mock sửa kỳ vọng có lý do. Endpoint quản trị đổi trạng thái (`mock_services/app/admin_calls.py` `POST /_admin/users/{id}/status`): chuyển khỏi `disabled` → đặt `disable_reason = null`; chuyển sang `disabled` không kèm lý do → `null` (hợp lệ: thiếu lý do ⇒ R12 không khớp, R10 cũng không — ca e12b). Không thêm người/máy mới ở T22a (cần thì T20 thêm). Hình dạng model tool: xem cuối mục 4.7b |
| **P8** | **`policy.json`**: thêm R01–R15 theo **bảng 4.4 nguyên văn** (thứ tự R01…R20 tăng dần trong file); `description` là câu tiếng Việt ngắn đọc được bởi Trưởng BP (bảng 4.4 cột "Mô tả"). Không đổi `constants`, `business_hours`, R16–R20 |
| **P9** | **`scripts/rule_coverage.py`** (Q-5-5, mục 4.6) — chỉ đọc, không gọi mạng, không cần stack; dùng `app.domain`, `app.risk.policy_engine.evaluate_rules`, `app.settings` (không import `app.eval`) |
| **P10** | **Việc treo 19 (G5-6):** test ghim "không luật nào trong `policy.json` tham chiếu `action.target`" (giữ trong danh sách trắng DSL, không xoá — xoá là đổi hợp đồng 3h) |
| **P11** | Không đụng: B3/B5/B6/B11/B12 node, executor, B17, `.env*`, `docs/spec/` (trừ 2 file Tuấn Anh chép vào trước khi mở phiên), file/khối M9, `approvers.yaml`, `risk/models.py`, `config/prompts/*`, `config/scripted/*`, `backend/app/llm/*`, `pyproject.toml`/`uv.lock`. `ENABLED_INTENTS` không đổi. Không thêm luật thứ 21. Không thêm module/import `app.eval` vào `backend/app/risk/` |

### 4.2. Hành động mới và metadata [`procedure_doc` Chốt 09/10; các cột khác Đề xuất — Tuấn Anh soát ở PLAN]

| Intent | `action_type` | `reversible` / `reversibility` | `data_sensitivity` | `scope` | `privilege_level` | `procedure_doc` |
|---|---|---|---|---|---|---|
| account | `reset_password` | true / partial (hoàn tác = khoá lại) | medium | single_account | standard_user | KB-ACC-001 |
| account | `unlock_account` | true / full | low | single_account | standard_user | KB-ACC-002 |
| software | `install_software` | true / partial (license có phí không hoàn tác — T24 xét theo bước) | low | single_device | standard_user | KB-SW-001 |
| access | `view_permissions` | true / full (chỉ đọc) | low | single_account | standard_user | KB-ACS-005 |
| access | `grant_permission` | true / full | medium | single_account | standard_user | KB-ACS-001 |
| access | `extend_permission` | true / full | medium | single_account | standard_user | KB-ACS-003 |

- **`procedure_doc` [Chốt 09/10]** theo K2 thật (PR #29, 18 bài): `KB-ACC-001` "Tự đặt lại mật khẩu tài khoản cá nhân", `KB-ACC-002` "Tài khoản bị khóa: nguyên nhân và cách mở", `KB-SW-001` "Danh mục phần mềm duyệt sẵn và cách tự cài", `KB-ACS-005` "Xem quyền truy cập hiện có của mình", `KB-ACS-001` "Quy trình xin quyền thư mục dùng chung", `KB-ACS-003` "Quyền truy cập có thời hạn và gia hạn quyền". Mỗi hành động trỏ đúng bài mô tả nó; khi K2 gộp, `procedure_warnings` của 6 hành động = 0 dòng. (`KB-ACS-002` "Mức độ nhạy của thư mục và ai duyệt" là bài chính sách, không phải quy trình của hành động nào.)
- `data_sensitivity`, `privilege_level` là **tĩnh** theo bảng [Chốt B11 §0.3]; độ nhạy thật của tài nguyên và quyền của tài khoản đích nằm ở **fact** (bảng 4.3) — luật đọc fact, không đọc hai trường tĩnh này.
- Thiếu tài liệu trong KB → `make ingest` chỉ cảnh báo; B11 chỉ kiểm khi intent được bật (T20). T22a chạy trước khi PR #29 gộp → KB thật trên `dev-tuananh` lúc đó chưa có 6 bài (bình thường).
- `value_rules` (slots.yaml): `account_type` pattern `^(ad|email|erp)$`; `target_user` `^[a-z0-9_]{3,64}$`; `software_name` `^[A-Za-z0-9][A-Za-z0-9 .+#-]{0,63}$`; `resource_path` `^[A-Za-z0-9_-]+(/[A-Za-z0-9_.-]+){0,4}$` (nhận chữ hoa: tên hiển thị "Zoom Workplace", "AutoCAD", thư mục `finance/Q3`; mock tự chuẩn hoá tên phần mềm nên slot nhận tên người dùng gõ); `permission_level` `^(read|write|full)$`; `duration` `^\d{1,3}$`. Slot `target_user` là **tùy chọn** của account (đặt lại cho người khác) — chỉ là tham số, B11 vẫn `validate_targets` qua AD (T20).

### 4.3. Fact mới (P2) — nguồn mà T20 phải đọc từ tool

| Fact | Kiểu / tập giá trị | Ý nghĩa | Tool nguồn (T20) | Seed ví dụ |
|---|---|---|---|---|
| `target_account_privilege` | str ∈ {standard_user, elevated, admin} | Mức quyền tài khoản đích | `check_privilege_level.level` | nv001 `standard_user`; l1_01 `elevated`; svc_backup `admin` |
| `target_is_service_account` | bool | Tài khoản đích là tài khoản dịch vụ | `check_account_status.is_service_account` (P7) | svc_backup `true` |
| `target_user_status` | str ∈ {active, probation, disabled, terminated} | Trạng thái nhân sự của `requested_for` | `check_account_status.employment_status` | nv004 `disabled`, nv006 `terminated` |
| `target_disable_reason` | str ∈ {security, other} | Lý do vô hiệu hoá (chỉ khi `disabled`) | `check_account_status.disable_reason` (P7) | nv004 `security` |
| `target_account_locked` | bool | Tài khoản (theo `account_type`) đang khoá | `check_account_status.account.locked` | nv007 email `true` |
| `target_lock_reason` | str ∈ {bad_password, admin, inactivity, other} (theo 3 giá trị của mock `lock_reason` + `other`) | Lý do khoá (chỉ khi khoá) | `check_account_status.account.lock_reason` (giá trị lạ → `other`) | nv007 email `bad_password` |
| `in_catalog` | bool | Phần mềm có trong danh mục duyệt sẵn | `check_catalog_entry.in_catalog` | zoom `true` |
| `license_paid` | bool | Phần mềm có phí license | `check_catalog_entry.paid` | autocad `true` |
| `requires_local_admin` | bool | Cài cần quyền quản trị máy | `check_catalog_entry.requires_local_admin` (P7) | autocad `true` |
| `resource_sensitivity` | str ∈ {low, medium, high} | Độ nhạy thư mục | `check_resource_sensitivity.sensitivity` | finance/Q3 `high` |
| `same_department` | bool | Thư mục thuộc phòng ban của `requested_for` | `owner_department == phòng ban requested_for (AD)` | nv001 + finance/* `true`; nv002 + finance/Q3 `false` |
| `has_permission_record` | bool | `requested_for` đã có dòng quyền trên thư mục (còn hạn hoặc hết hạn) | `check_current_permissions` | nv002 + finance/Q3 `true` (hết hạn) |

Fact VPN giữ nguyên (`device_registered`, `device_owner_is_requester`, …). Software dùng lại `device_owner_is_requester` cho máy đích (T20 gọi `check_device_registered`).

### 4.4. Bảng 20 luật [Chốt nội dung §6.3; Chốt 01/10 cho R09; Đề xuất điều kiện cụ thể]

Ký hiệu: `F.x` = `action.facts.x`; `P.x` = `action.params.x`; `other` = `ctx.target_is_other`.

| Mã | Loại | Intent | Hành động | Điều kiện (`all`) | Mô tả (`description`) |
|---|---|---|---|---|---|
| R01 | allow | account | reset_password | `other` is_false · `F.target_account_privilege` eq standard_user · `F.target_is_service_account` is_false · `F.target_user_status` in [active, probation] | Đặt lại mật khẩu tài khoản thường của chính mình |
| R02 | allow | account | unlock_account | `other` is_false · `F.target_account_locked` is_true · `F.target_lock_reason` eq bad_password · `F.target_account_privilege` eq standard_user · `F.target_is_service_account` is_false · `F.target_user_status` in [active, probation] | Mở khoá tài khoản thường của chính mình bị khoá do nhập sai mật khẩu |
| R03 | approval_required | account | [reset_password, unlock_account] | `F.target_is_service_account` is_true | Thao tác trên tài khoản dịch vụ cần người duyệt |
| R04 | approval_required | account | [reset_password, unlock_account] | `F.target_account_privilege` eq admin | Thao tác trên tài khoản quản trị cần người duyệt |
| R05 | approval_required | account | [reset_password, unlock_account] | `F.target_user_status` eq terminated | Thao tác trên tài khoản của người đã nghỉ việc cần người duyệt |
| R06 | allow | access | view_permissions | `other` is_false | Xem quyền hiện có của chính mình |
| R07 | approval_required | access | grant_permission | `F.resource_sensitivity` eq high | Cấp quyền mới vào dữ liệu nhạy cảm cần người duyệt |
| R08 | approval_required | access | grant_permission | `P.permission_level` eq full | Cấp quyền quản trị (toàn quyền) thư mục cần người duyệt |
| R09 | approval_required | access | [grant_permission, extend_permission] | `F.same_department` is_false | Cấp/gia hạn quyền vào tài nguyên phòng ban khác (vượt cấp quản lý) cần người duyệt |
| R10 | allow | access | extend_permission | `other` is_false · `F.has_permission_record` is_true · `F.same_department` is_true · `F.resource_sensitivity` in [low, medium] · `F.target_user_status` in [active, probation] · `P.duration_days` lte 90 | Gia hạn quyền cũ (≤ 90 ngày) vào thư mục không nhạy cảm của phòng mình |
| R11 | allow | software | install_software | `other` is_false · `F.in_catalog` is_true · `F.license_paid` is_false · `F.requires_local_admin` is_false | Cài phần mềm miễn phí trong danh mục lên máy của mình |
| R12 | **deny** | access | [grant_permission, extend_permission] | `F.target_user_status` eq disabled · `F.target_disable_reason` eq security | Cấm cấp quyền cho tài khoản bị vô hiệu hoá vì lý do bảo mật |
| R13 | approval_required | software | install_software | `F.in_catalog` is_false | Cài phần mềm ngoài danh mục cần người duyệt |
| R14 | approval_required | software | install_software | `F.license_paid` is_true | Cài phần mềm có phí license cần người duyệt |
| R15 | approval_required | software | install_software | `F.requires_local_admin` is_true | Cài phần mềm cần quyền quản trị máy cần người duyệt |
| R16–R20 | — | vpn | — | **Giữ nguyên** (`decisions.md` §1.1, 4b P7) | — |

**Kiểm đếm:** allow = R01, R02, R06, R10, R11, R16, R20 (7) · approval_required = R03, R04, R05, R07, R08, R09, R13, R14, R15, R17, R18, R19 (12) · deny = R12 (1) [Chốt N4].

**Lý do các điều kiện [Đề xuất] đáng soát:**
- **R10 (G5-4b, P1):** đòi `same_department`, độ nhạy ≠ high, ≤ 90 ngày, `target_user_status ∈ {active, probation}` (thiếu `target_disable_reason` thì R12 không khớp — R10 tự đòi trạng thái bình thường để không AUTO cho tài khoản bị vô hiệu) → gia hạn quyền khác phòng (vd `nv002` gia hạn `finance/Q3` đã hết hạn) không bao giờ AUTO: R09 bắt (khác phòng → duyệt); gia hạn > 90 ngày hoặc độ nhạy cao cùng phòng → **không luật nào** → lớp LLM (họ "cấp quyền 180 ngày" của §8.2 [Chốt]).
- **R12 áp cả `extend_permission`:** gia hạn cũng là trao quyền cho tài khoản bị khoá vì bảo mật.
- **R01/R02 đòi `target_user_status ∈ {active, probation}`:** tài khoản `disabled` không bao giờ AUTO qua luật (đi lớp LLM hoặc luật chặt hơn).

**Họ kịch bản đi xuống LLM [Chốt §8.2] — kiểm bằng bảng trên:**

| Họ | Ví dụ | Vì sao không luật nào khớp |
|---|---|---|
| L1 cấp quyền mới thư mục độ nhạy thấp/trung bình, cùng phòng | nv001 xin `read` `finance/public-reports` 30 ngày | R07 (không high), R08 (không full), R09 (cùng phòng), R12 (active); không có luật allow cho `grant_permission` |
| L2 đặt lại mật khẩu tài khoản thường của đồng nghiệp | nv005 xin đặt lại mật khẩu cho tài khoản thường của nv001 | R01 đòi `other` is_false; R03–R05 không thỏa |
| L3 mở khoá không phải do nhập sai | khoá `admin` hoặc `inactivity` | R02 đòi `bad_password` |
| L4 cấp/gia hạn quyền 180 ngày | nv001 gia hạn `finance/public-reports` 180 ngày | R10 đòi ≤ 90; R09 không (cùng phòng) |

### 4.5. File

```
config/policy.json                         # P8: + R01–R15
config/slots.yaml                          # P6: + account, software, access (không bật)
config/action_metadata.yaml                # P6: + 6 hành động (bảng 4.2)
backend/app/domain/facts.py                # P2: + 12 fact, FACT_VALUE_SETS; docstring P4
backend/app/domain/policy.py               # P3: FACT_SOURCES["action.params"]
backend/app/domain/action.py               # P3: PARAM_TYPES (+ docstring P4) — không đổi build_action
backend/app/risk/policy_engine.py          # P3: fact_view thêm "action.params"
backend/app/risk/context.py                # P5
backend/app/domain/messages.py             # ACTION_LABELS + 6 nhãn (test d4 bắt mọi action_type phải có nhãn) — mục 4.7b
scripts/mutation/mutate_3h.py              # chỉ sửa hằng _TARGET (chuỗi gốc M-3h-10) + tên test kỳ vọng nếu đổi — mục 4.7b
backend/app/tools/models.py                # P7: is_service_account, disable_reason, requires_local_admin
mock_services/seed.json + mock_services/app/… (model)   # P7
scripts/rule_coverage.py                   # P9 (mới)
scripts/mutation/mutate_t22a.py            # 4.8 (mới)
backend/tests/unit/test_policy_rules_all.py         # 4.7 (mới, test-writer)
backend/tests/unit/test_rule_coverage.py            # 4.7 (mới)
backend/tests/unit/test_build_ctx_targets.py        # 4.7 (mới)
eval/scenarios/_mau/T22A-*.yaml            # 3 kịch bản mẫu cho test script (họ L1, R01, R12)
```

### 4.6. `scripts/rule_coverage.py` (P9, Q-5-5)

**Gọi:** `uv run python scripts/rule_coverage.py eval/scenarios` (thư mục hoặc danh sách file) `[--seed mock_services/seed.json] [--csv out.csv]`.

**Mỗi kịch bản** (YAML theo P8 §4.1 + 2 trường mới):

```yaml
gold:
  action:                       # MỚI — bắt buộc khi need_type = action
    type: grant_permission      # ∈ action_types (slots.yaml)
    target: "folder:finance/public-reports"   # user:<id> | device:<id> | folder:<path>
    requested_for: nv001        # bỏ trống = người gửi (P4)
    params: {permission_level: read, duration_days: 30}
  facts:                        # MỚI — chỉ khoá trong FACT_KEYS (bảng 4.3 + fact VPN)
    resource_sensitivity: low
    same_department: true
    has_permission_record: true
    target_user_status: active
```

**Xử lý:**
1. Nạp YAML; kịch bản `need_type: info` hoặc không có `gold.action` → bỏ qua (đếm riêng "không có hành động").
2. `requester` → tìm `user_id` trong seed → `RequesterContext` (cùng cách B1 dựng từ AD; `captured_at = at`). Không có trong seed → **lỗi kịch bản** (in id, không dừng cả lượt).
3. `Action`: metadata từ `action_metadata.yaml` theo `type`; `params` kiểm `PARAM_TYPES`; `facts` qua `check_facts` (sai key/kiểu/tập → lỗi kịch bản).
4. **Đối chiếu seed** (cảnh báo, không lỗi): với fact suy được trực tiếp từ seed (bảng 4.3 cột "Seed ví dụ" — privilege, service, status, disable_reason, sensitivity, same_department, in_catalog, license_paid, requires_local_admin, device_registered, device_owner_is_requester) mà giá trị kịch bản khác seed → in `CẢNH BÁO <id>: <fact> kịch bản=<x> seed=<y>`.
5. `RiskContext`: `now = at`, giờ hành chính theo `policy.json.business_hours`, `target_is_other` theo P5 (cờ B6 = False).
6. `evaluate_rules(get_policy().rules, action, ctx, intents=action_intents())` → `allow | approval_required | deny | none`.

**In ra:** bảng `họ | số kịch bản | allow | approval_required | deny | none (→ LLM) | lỗi`, dòng tổng, danh sách lỗi/cảnh báo; `--csv` ghi từng kịch bản (`id, family, rule_decision, matched_rule_id, all_matched, expected_route`). Thoát `1` nếu có **lỗi kịch bản**, `0` nếu chỉ cảnh báo. **Không** in `expected_route` ở bảng tổng (người gán nhãn có thể chạy script).

**Dữ liệu thật để thử sau khi xong (không phải test):** D1 40 kịch bản ở PR #29 (hiện `kb/eval/scenarios/` trên nhánh `kb-quan`, sẽ chuyển `eval/scenarios/`). Agent **không** checkout/merge nhánh đó; chạy script trên D1 là việc của phiên Cowork sau khi #29 gộp.

### 4.7. Test (test-writer viết từ bảng này TRƯỚC code — bước S của PLAN)

Khuôn `LUAT_C5` của `test_policy_rules_vpn.py`: gọi thẳng `evaluate_rules(rules_from_file, action, ctx, intents=…)` với `RiskContext` dựng tay; mỗi ca ghi **kỳ vọng chép từ bảng 4.4**, không suy từ code.

**Ca gốc (an toàn) mỗi hành động** — các test dưới đổi đúng **một** thứ so với ca gốc:

| Ký hiệu | Người gửi | Action | Facts gốc |
|---|---|---|---|
| G-RESET | nv001 | reset_password, `user:nv001`, rf nv001 | privilege standard_user, service false, status active |
| G-UNLOCK | nv007 | unlock_account, `user:nv007`, rf nv007, params {} | locked true, lock_reason bad_password, privilege standard_user, service false, status active |
| G-VIEW | nv001 | view_permissions, `user:nv001`, rf nv001 | {} |
| G-GRANT | nv001 | grant_permission, `folder:finance/public-reports`, rf nv001, params {read, 30} | sensitivity low, same_department true, has_permission_record false, status active |
| G-EXTEND | nv001 | extend_permission, `folder:finance/public-reports`, rf nv001, params {read, 30} | has_permission_record true, same_department true, sensitivity low, status active |
| G-INSTALL | nv001 | install_software, `device:LAP-0342`, rf nv001, params {} | in_catalog true, license_paid false, requires_local_admin false, device_owner_is_requester true, device_registered true |

**Bảng ca (≥ 60):**

| # | Ca | Đổi so với gốc | Kỳ vọng `decision` / `rule_id` / `all_matched` |
|---|---|---|---|
| a1 | R01 khớp | G-RESET | allow / R01 / [R01] |
| a2–a4 | R01 thiếu từng fact (privilege, service, status) | xoá 1 fact | none / — / [] (thiếu fact → sai) |
| a6 | R01 người khác | rf nv005, target `user:nv005` | none (→ LLM, họ L2) |
| a7 | R01 + R04 | privilege admin | approval_required / R04 / [R04] (R01 không khớp vì privilege ≠ standard) |
| a8 | R01 privilege elevated | elevated | none |
| a9 | R03 | service true | approval_required / R03 |
| a10 | R05 | status terminated | approval_required / R05 |
| a11 | status disabled | disabled (+ disable_reason security) | none (R12 chỉ cho access) |
| a12 | R03 + R04 + R05 cùng lúc | service true, admin, terminated | approval_required / R03 (đứng trước) / [R03, R04, R05] |
| b1 | R02 khớp | G-UNLOCK | allow / R02 |
| b2 | lock_reason `admin` (và `inactivity`) | đổi | none (họ L3) |
| b3–b7 | R02 thiếu từng fact (5 fact: locked, lock_reason, privilege, service, status) | xoá 1 | none |
| b9 | R02 + R04 | privilege admin | approval_required / R04 |
| c1 | R06 khớp | G-VIEW | allow / R06 |
| c2 | R06 người khác | rf nv005 | none |
| d1 | G-GRANT (họ L1) | — | none |
| d2 | R07 | sensitivity high | approval_required / R07 |
| d3 | R08 | permission_level full | approval_required / R08 |
| d4 | R09 | same_department false | approval_required / R09 |
| d5 | R07 + R08 + R09 | high, full, khác phòng | approval_required / R07 / [R07, R08, R09] |
| d6 | R12 | status disabled, disable_reason security | **deny / R12** |
| d7 | R12 + R07 | + high | **deny / R12** / [R07, R12] (chặt nhất thắng) |
| d8 | disabled lý do other | disable_reason other | none |
| d9 | R12 thiếu disable_reason | status disabled, không có disable_reason | none (thiếu fact → sai; ca này đi lớp LLM — LLM thấy `target_user_status=disabled`; trước khi có calibrator không ca LLM nào AUTO (D-38); theo dõi trong 10 ca sai tiêu biểu Phase 10) |
| d10 | `P.permission_level` sai kiểu (`"FULL"` / 1) | params lỗi | không ném lỗi; R08 không khớp (coi như thiếu) |
| e1 | R10 khớp | G-EXTEND | allow / R10 |
| e2 | 180 ngày (họ L4) | duration_days 180 | none |
| e3 | đúng 90 ngày | 90 | allow / R10 (`lte`) |
| e4 | 91 ngày | 91 | none |
| e5 | độ nhạy high | high | none (R07 chỉ grant) |
| e6 | khác phòng | same_department false | approval_required / R09 |
| e7–e12 | R10 thiếu từng fact/param (record, same_department, sensitivity, target_user_status, duration_days) + `other` true | xoá/đổi 1 | none (ca `same_department` thiếu → none, **không** allow) |
| e12b | gia hạn cho tài khoản `disabled` thiếu `target_disable_reason` | status disabled, không disable_reason | none (R12 không khớp, R10 cũng không — **không** AUTO) |
| e13 | R12 trên extend | disabled + security | deny / R12 / [R12] |
| e14 | `duration_days` kiểu str `"30"` | đổi | none |
| f1 | R11 khớp | G-INSTALL | allow / R11 |
| f2 | R13 | in_catalog false | approval_required / R13 |
| f3 | R14 | license_paid true | approval_required / R14 |
| f4 | R15 | requires_local_admin true | approval_required / R15 |
| f5 | R11 + R14 | paid true (còn lại như gốc) | approval_required / R14 / [R14] |
| f6 | R13 + R14 + R15 | đủ 3 | approval_required / R13 / [R13, R14, R15] |
| f7–f9 | R11 thiếu từng fact (in_catalog, license_paid, requires_local_admin) | xoá 1 | none |
| f10 | máy người khác | device_owner_is_requester false | none (`other` = true) |
| f11 | máy thiếu fact chủ máy | xoá `device_owner_is_requester` | none (P5: đích `device:` + thiếu → người khác) |
| g1 | `build_ctx` account tự làm | target `user:nv001`, rf = người gửi, không fact máy | `target_is_other` **False** |
| g2 | `build_ctx` account người khác | rf nv005 | True |
| g3 | `build_ctx` cờ B6 | `ctx_flags.target_is_other = True` | True |
| g4 | `build_ctx` VPN thiếu fact chủ máy | target `device:LAP-0342`, không fact | True (không đổi so với 3h) |
| g5 | `build_ctx` access tự xem | target `user:nv001` | False |
| h1 | Đếm luật | `policy.json` | đúng 20 id R01…R20, không trùng; 7/12/1 theo loại |
| h2 | Hành động của luật | mọi `action` | ∈ `action_types` của đúng intent (dùng `check_policy_config` thật) |
| h3 | Việc treo 19 | mọi điều kiện | không có `action.target` |
| h4 | Luật allow khẳng định dương (P1) | mỗi luật allow | có ≥ 1 test "thiếu fact" trong file (test meta đếm theo id) |
| h5 | Khởi động | settings thật, `ENABLED_INTENTS=["vpn"]` | `check_policy_config`, `check_intent_config`, `check_plans` xanh |
| h6 | Không bật intent mới | `enabled_intents` mặc định | `["vpn"]` |
| h7 | `check_facts` | fact ngoài tập (`target_user_status="on_leave"`) | `FactKeyViolation` |
| h8 | `procedure_doc` 6 hành động | `action_metadata.yaml` | đúng bảng 4.2 [Chốt 09/10] (KB-ACC-001, KB-ACC-002, KB-SW-001, KB-ACS-005, KB-ACS-001, KB-ACS-003) |
| r1 | `rule_coverage.py` 3 kịch bản mẫu | `eval/scenarios/_mau` | L1 → none, R01 → allow, R12 → deny; tổng "none" = 1 |
| r2 | Kịch bản fact sai kiểu | fixture tạm | lỗi kịch bản, thoát 1 |
| r3 | Fact lệch seed | `target_account_privilege: admin` cho nv001 | cảnh báo, thoát 0 |
| r4 | Không in `expected_route` ở bảng tổng | stdout | chuỗi `expected_route` không có trong bảng tổng |
| v1 | Hồi quy VPN | `test_policy_rules_vpn.py` (bảng `BANG_11_2`, `LUAT_C5`, P3, giờ), `test_hrule_4b_owner.py` (bảng `LUAT_P7`), `test_b12_assess.py`, e2e cổng 3 | xanh, **không đổi kỳ vọng của ca luật nào**; chỉ các test "ghim nguyên file" ở 4.7b được sửa |

### 4.7b. Test cũ và file phụ PHẢI đổi [Đã chạy thử 03/10 — không phải suy luận]

Dựng thử P2, P3, P5, P6, P8 trên bản sao sạch của `1455b55` rồi chạy toàn bộ `backend/tests/unit`: **57 ca bảng 4.7 đúng 57**; `check_policy_config`, `check_intent_config` qua với `ENABLED_INTENTS=["vpn"]`; đếm loại luật 7/12/1. Nhưng **13 test cũ đỏ** — đỏ vì chúng ghim "file chỉ có VPN", không phải vì hành vi VPN đổi. Agent **phải** sửa đúng các test này, giữ nguyên **ý** của từng test, ghi lý do vào MẪU B; test cũ nào khác đỏ → DỪNG hỏi.

| File | Test | Vì sao đỏ | Sửa thế nào (giữ ý) |
|---|---|---|---|
| `test_config_files.py` | `test_policy_json_rules_are_exactly_spec_11_2` | so `raw["rules"] ==` đúng 5 luật | so **5 phần tử có id R16–R20** với `SPEC_11_2["rules"]` (nguyên văn, không đổi) |
| | `test_nested_any_group_accepted` | lấy luật theo vị trí `rules[4]` | lấy theo `id == "R20"` |
| | `test_q3h1_rule_action_outside_intent_refuses_start` | sửa luật theo vị trí `rules[1]`; dùng `intent="account"`, `reset_password` làm "không tồn tại" | lấy theo `id == "R17"`; dùng hành động/intent **không khai báo** (vd `print_document`, `printer`) |
| | `test_missing_action_metadata_refuses_startup` | thông điệp nay báo intent khác trước (thứ tự chữ cái) | file metadata tạm chứa đủ 3 intent mới, chỉ thiếu 2 hành động VPN — giữ `match` cũ |
| | `test_enabled_intent_without_slots_refuses_startup` | `"account"` nay đã khai báo | dùng intent không khai báo (`"printer"`) |
| | `test_q3h1_open_runtime_refuses_bad_policy_before_db` | như dòng 3 | như dòng 3 |
| `test_hrule_4b_owner.py` | `test_hrule_p7_policy_json_r17_r18_r19_carry_owner_condition` | `set(rules) == {R16…R20}` | `{R16…R20} ⊆ set(rules)`; thứ tự R16…R20 giữ trong danh sách id |
| `test_policy_rules_vpn.py` | `test_hrule_policy_json_khop_spec_11_2` | `raw["rules"] ==`, `len == 5` | như dòng 1; đếm 20 do h1 (file mới) giữ |
| `test_slots_facts.py` | `test_fact_keys_closed_list` | ghim đúng 7 fact | ghim đúng **19** fact (7 VPN + 12 bảng 4.3) — vẫn là danh sách đóng |
| `test_rejection_text.py` | `test_d4_every_action_type_has_label` | 6 hành động mới chưa có nhãn | **không sửa test** — thêm 6 nhãn vào `domain/messages.py` `ACTION_LABELS`: `reset_password` "đặt lại mật khẩu", `unlock_account` "mở khoá tài khoản", `install_software` "cài đặt phần mềm", `view_permissions` "xem quyền truy cập", `grant_permission` "cấp quyền truy cập", `extend_permission` "gia hạn quyền truy cập" [Đề xuất chữ]. Câu `rejection_text` hiện ghép "cho máy …" — sai nghĩa với đích không phải máy → **ghi nợ cho T20** (T22a không bật intent nên chưa lộ) |
| `test_s0_grounding.py` | `test_ingest_procedure_warnings_repo_config_on_fixture_kb_is_clean` | KB fixture của test (`backend/tests/fixtures/kb/`, chỉ VPN) không có 6 tài liệu quy trình mới → 6 cảnh báo | giữ `procedure_warnings` nguyên (cảnh báo mọi intent — đúng thực tế tới khi K2 gộp); test đổi thành: cảnh báo = **đúng 6 dòng**, mỗi hành động mới một dòng với đúng mã bảng 4.2 [Chốt 09/10] (`KB-ACC-001`, `KB-ACC-002`, `KB-SW-001`, `KB-ACS-005`, `KB-ACS-001`, `KB-ACS-003`), **0 dòng `vpn/`**. Hàm in theo hành động hay gộp theo mã → agent kiểm trên code, ghi vào giả định [Suy luận] |
| | `test_ingest_prints_procedure_warning_without_blocking` | ghim `lines[0]` là cảnh báo KB-VPN-009 | tìm dòng KB-VPN-009 trong các dòng cảnh báo (không ghim vị trí) |
| `test_mutation_n3.py` | `test_every_mutation_leaves_the_mark[mutate_3h]` | chuỗi gốc của M-3h-10 (hằng `_TARGET`, 3 dòng `target_is_other` trong `risk/context.py`) không còn | **không sửa test** — sửa `scripts/mutation/mutate_3h.py`: chỉ hằng `_TARGET` theo code mới, ý đột biến giữ ("chỉ so `requested_for`"); tên test kỳ vọng của M-3h-10 cập nhật nếu đổi tên test; không đụng `_CTX_FACTS`, `_ESTIMATE` |

Hệ quả vận hành: sau T22a, `make ingest` trên KB thật của `dev-tuananh` in cảnh báo `procedure_doc … không có trong KB` cho tới khi PR #29 (K2) gộp — **không chặn**; sau khi gộp, 0 cảnh báo. Agent soát `tests/stack/gate3.py`, `gate4.py`, e2e xem có chỗ nào đòi stderr của ingest sạch không (grep 03/10: không thấy) [Suy luận — kiểm lại].

**P7 đã dựng thử 06/10:** thêm 3 trường vào `seed_model.py`, `state.py`, `ad.py` (`user_view`), `software.py`, `seed.json` và model tool → `mock_services/tests` xanh, e2e `test_tools_vs_mock`, `test_b06_vs_mock`, `test_b01_vs_mock` xanh, unit liên quan xanh, **không test cũ nào phải sửa**. Chốt hình dạng model tool: `is_service_account: bool` và `disable_reason` đặt ở **`AccountStatus`** (đầu ra `check_account_status`), **không** ở `AdUser` (B1 dùng — không cần); `requires_local_admin: bool` ở `CatalogEntry`; cả ba **bắt buộc, không mặc định** (mock cũ thiếu trường → lỗi rõ, không âm thầm coi là `false` — an toàn cho R01/R02/R11). Model tool đang `extra="ignore"` nên đổi mock trước không làm vỡ backend.

Chưa dựng thử: P9 (`rule_coverage.py`), integration/e2e cần Docker.

### 4.8. Mutation bắt buộc (2 lượt, md5, `scripts/mutation/mutate_t22a.py` theo khuôn `mutate_4c.py`: kiểm không còn chữ `MUTATION` + mốc xanh trước)

| Mã | Phá | Test phải đỏ |
|---|---|---|
| M-T22a-1 | R01 bỏ điều kiện privilege | a2 (thiếu privilege), a8 (elevated) |
| M-T22a-2 | R02 bỏ `lock_reason` | b2 |
| M-T22a-3 | R11 bỏ `license_paid is_false` | f7/f8 (thiếu fact) |
| M-T22a-4 | R10 bỏ `duration_days lte 90` | e2, e4 |
| M-T22a-5 | R10 bỏ `same_department is_true` | e7–e12 (ca thiếu `same_department`) |
| M-T22a-5b | R10 bỏ `target_user_status in [active, probation]` | e12b |
| M-T22a-6 | R12 đổi `deny` → `approval_required` | d6, d7, e13 |
| M-T22a-7 | R09 chỉ `grant_permission` | e6 |
| M-T22a-8 | `build_ctx` áp vế chủ máy cho mọi đích | g1, g5, a1, c1 |
| M-T22a-9 | `build_ctx` bỏ vế chủ máy | g4, f11 |
| M-T22a-10 | `fact_view` nhận `action.params` sai kiểu | d10, e14 |
| M-T22a-11 | `rule_coverage.py` đếm `approval_required` vào "none" | r1 |
| M-T22a-12 | `check_facts` bỏ kiểm tập giá trị | h7 |

### 4.9. Soát bảo mật (security-reviewer, mỗi DỪNG)

Bất biến: (1) `evaluate` vẫn chỉ nhận `action, ctx` (h22); không nguồn DSL nào chứa câu người dùng — `action.params` chỉ 2 khoá danh sách trắng, giá trị đã qua `value_rules` + `build_action`; (2) không luật allow nào khớp nhờ thiếu fact (P1) — soát từng luật allow so với các luật chặt hơn cùng hành động; (3) `deny` duy nhất R12, không vào hàng đợi duyệt (B12 đã có); (4) `build_ctx` không đọc khoá state mới; (5) không intent mới nào được bật; (6) `rule_coverage.py` không ghi file ngoài `--csv`, không gọi mạng, không in `expected_route` ở bảng tổng; (7) 3 trường mới ở model tool bắt buộc, không mặc định; (8) không module nào trong `backend/app/risk/` import `app.eval`.

### 4.10. DỪNG

- **DỪNG 1:** P2, P3, P4, P5, P6, P7 (fact, nguồn params, `build_ctx`, khai báo intent, seed) + test-writer viết **toàn bộ** bảng 4.7 (đỏ trước code — ghi số đỏ/xanh, đỏ đúng lý do) + code để g*, h5–h8, v1 xanh + 13 test 4.7b xanh + mutation lượt 1 (phần có thể chạy) + security-reviewer. `make verify G=234` khi phiên git OK stack. Commit cục bộ. MẪU B in chuỗi `_TARGET` mới + xác nhận `risk/models.py` không đổi (bàn giao cho Phase 6).
- **DỪNG 2:** P8 (15 luật) + P9 (`rule_coverage.py`) + P10 + mọi test 4.7 xanh + mutation lượt 2 (đủ 13) + security-reviewer + "spec cần sửa (T22a)". `make verify G=234`. Commit cục bộ + phiếu push cho phiên git. **Quân** soát bảng 20 luật theo checklist 4.12 (không cần chạy code) và chỉnh bài KB Access/Software theo luật đã chốt.

### 4.11. Tuấn Anh / thành viên cần biết

- Không thêm biến `.env`; thành viên chỉ cần pull + `make up` lại (seed mock đổi → `make up` dựng lại mock).
- **Quân:** K2 đã có đủ 6 tài liệu quy trình theo bảng 4.2 (không cần đặt lại mã). Sau DỪNG 2: soát bảng 20 luật (4.12) **và** chỉnh bài KB Access/Software theo luật đã chốt (ghi ngưỡng gia hạn ≤ 90 ngày của R10, phần mềm cần quyền quản trị máy của R15…; tăng `version`; số liệu mới thêm vào `kb/kb-facts.md`). Tin gửi qua phiên git (outbox).
- **Dương, Duy Anh (người gán nhãn D1):** **không** mở `policy.json`, `PLAN-T22a.md`, file spec này mục 4.4, test `test_policy_rules_all.py` [Chốt 8.1].

### 4.12. Checklist cho Quân (xác nhận DỪNG 2, ~30 phút, không cần code)

Mở `config/policy.json` bản đã commit + bảng §6.3 (`NGU-CANH-DAY-DU.md` Phần I) + bảng 4.4 ở trên:
1. Đủ 20 luật, mã R01…R20 không trùng, 7 allow / 12 approval_required / 1 deny.
2. Mỗi ô của bảng §6.3 (4 loại × allow/approval_required) có đúng một luật tương ứng; R12 là luật cấm duy nhất.
3. `description` mỗi luật đọc hiểu được, khớp ô §6.3.
4. Ghi biên bản: tên, commit, ngày, "đạt"/danh sách chỗ lệch → gửi Tuấn Anh.

### 4.13. Spec cần sửa (T22a) — agent in nguyên văn khi xong

Mọi chỗ lệch 4.1–4.7; `decisions.md` §1.1 (bảng 20 luật kèm điều kiện), D-41; P8 §4.1 (schema `gold.action`, `gold.facts`); B12 §4.2 (nguồn `action.params`); B11 §4 (quy ước `requested_for`); Việc treo 19, 26 → đóng/ghi.

---

## 5. Chặng T20 — tách T20a (đơn ý) / T20b (nhiều ý) [Chốt 10/10 — phiên PHAN-TICH-P5]

**Vì sao tách:** soát code 10/10 (`.verify/phan-tich-p5/bao-cao.md` mục 5) ước cả T20 **19–25 giờ** (bản 0.1f ghi 6–8): B5 cha/con mới có hạ tầng dữ liệu (cột `parent_ticket_id`, `child_notices`, `wake_parent`, 409 cho con) — `parent_wait`/`parent_reply_wait` còn là node **giả** (`builder.py` `_NODE_MODULES`), chưa có `b05_split`, `compose_digest`, `POST /reply`. **Bật `ENABLED_INTENTS` không làm được ở T20**: `check_plans` (`executor/plans.py:60–64`) từ chối khởi động khi intent bật thiếu `PLAN`/mẫu B18 → bật ở **T24** (Q-5-7). T24 chỉ cần T20a.

### 5.1. T20a — đơn ý cho account / software / access (khung — viết đủ 11–12/10)
**Đầu vào:** 6B gộp; T23a đẩy (dùng chung thư mục chính, tuần tự); K2 (#29) gộp + ingest. **Đầu ra:** B3 prompt (ví dụ 6 hành động; sha/preset đổi → phối hợp 6B ở `test_llm_prompts`); B6 `infer_account/software/access` thuần theo bảng 4.3 + `TOOL_MAP` mở rộng (D-46); B11 `build_action` 4 intent (đích `user:`/`folder:`/`device:`; `duration` → `params.duration_days`; slot `action` cho access + bắt buộc theo `action_type` — Q-T22a-2) + `validate_targets`; fact **`existing_permission_level`** (Q-5-8) + R10 `in [read, write]` (Q-T22a-8, khuôn T22a: test thiếu fact + mutation); roster `approvers.yaml` 3 intent (+ test B15 `l1_01` → `it_mgr01`, G5-7); `rejection_text` theo đích. **Bất biến nợ T22a:** `install_software` luôn đích `device:<id>`; account/access `target == f"user:{requested_for}"` hoặc `folder:` đúng thư mục. **Hợp đồng `params`** chốt trong spec T20a để T24 không sửa `build_action`. **Không** bật `ENABLED_INTENTS` (test bật bằng tiêm `enabled_intents` + `plans=`). **Tầng A** (B11, R10) + B; Opus; **2 DỪNG** (DỪNG 1: B6 + fact/R10; DỪNG 2: B11 + roster); ~9–12 giờ.

### 5.2. T20b — nhiều ý (khung — viết spec 16/10)
**Đầu vào:** T24 đẩy (ticket con chạy được tới B17 thật). **Đầu ra:** `b05_split`, `create_child`/`mark_parent_once`, `parent_wait`/`parent_reply_wait` thật, notifier ghi `child_notices`, `compose_digest` + bảng 6 trường hợp đóng cha, quét đối soát ở worker (ngoài khối M9), `POST /api/tickets/{cha}/reply` + 4 điểm hợp đồng FE (`claude/viec-cho-phase5.md` mục 5, chốt 10/10: (a) `title` server ghép từ `ACTION_LABELS`, ý chưa có Action → nhãn loại yêu cầu; (b) giữ `options`, chưa phát; (c) ý ngoài `awaiting` → 422 kèm `child_id`, cha hết chờ → 409; (d) backend ghi tin người dùng đã che). **Q5 mở:** con vào ở B6 (B03 §5.3 [Đề xuất]) hay quay lại B3 (bảng 2.1 [Chốt `S_CLASSIFYING`]) — chốt khi viết spec. Đụng file lõi (`routing.py`, `builder.py`, `runner.py`, `wiring.py`) → không giao subagent. **Tầng A**; Opus; **2 DỪNG**; ~9–12 giờ.

## 6. Chặng T23a — đóng nhánh `ml-gan`: B2 lớp 3 chế độ `shadow` (tầng A, Opus, 1 DỪNG) [Chốt 10/10]

**Mục tiêu:** đưa phần đã viết của `ml-gan` (`f045e30`) vào `dev-tuananh` sau khi đủ test, mutation, soát bảo mật — **không đổi hành vi mặc định** của hệ thống.
**Mở 10/10 chiều** (6B đã gộp sớm — `d42d5c4`). **Đầu vào:** thư mục chính ở `d42d5c4` (A3 + 6B; cherry-pick `f045e30` thử lại trên `d42d5c4`: sạch, tự gộp `test_llm_client.py`) **cộng** thay đổi chưa commit của `f045e30` (phiên git `cherry-pick --no-commit` rồi bỏ stage — đã thử 10/10: sạch, 20 file, không xung đột) + 2 file spec. **Đầu ra:** 2 commit cục bộ (mục 6.4) + phiếu push.
**Không thuộc T23a:** model phân loại của Duy (`/classify_intent` giữ 503 — D-44, Q7); chuyển `active`; `thresholds.json`; ONNX; cascade B3; sửa M9.

### 6.1. P-T23a (agent không hỏi lại)

| Mã | Chốt |
|---|---|
| **P1** | Phạm vi code = đúng 20 file của `f045e30` + `backend/app/ml/client.py` (P4) + test tương ứng + `scripts/mutation/mutate_t23a.py` + `PROGRESS.md` + 2 file spec. Không thêm tính năng ngoài `f045e30` |
| **P2** | **Mặc định không đổi hành vi (D-44):** `B2_CLASSIFIER_MODE` mặc định `shadow`; compose `GUARD_MODEL_DIR: ${GUARD_MODEL_DIR:-}` rỗng → `/classify` 503 `model_missing` như Phase 3; `/classify_intent` luôn 503 |
| **P3** | `shadow`: gọi L3, ghi `p_mal` + `clf_mode` vào `screening`/audit (kể cả nhánh E2), **không** chặn/cho qua theo điểm — luôn xuống L4. `active`: hành vi 0,90/0,10 như Phase 3. Giá trị lạ → không khởi động (backend VÀ worker) |
| **P4** | **Q-5-9:** `ml/client.py` — `/classify` trả 422 `{"error":"too_many_windows",…}` → `MlResult(error="too_many_windows")` (B2 coi là lỗi L3 → L4, KHÔNG E9); mọi 422 khác (và 401/413/404, sai schema) giữ `MlContractError`. Không đổi timeout/retry |
| **P5** | Fail-closed khi nạp model (giữ code `f045e30`): thư mục thiếu / thiếu file / SHA lệch (khi đặt) / có `.bin .pt .pth .pkl .pickle .ckpt .py` (quét đệ quy) / thiếu nhãn INJECTION / tokenizer tự cắt → ml-service **không khởi động**; kiểm trước `import torch`; `use_safetensors=True, trust_remote_code=False, local_files_only=True` |
| **P6** | Tự cắt cửa sổ (không dùng `stride`/`return_overflowing_tokens` của thư viện — làm mất nội dung, ML-KIEM 03/10); điểm = **max** các cửa sổ; > 48 cửa sổ → 422, không chấm một phần |
| **P7** | Không văn bản người dùng trong log/phản hồi/audit (chỉ `chars`, `windows`, `ms`, `p_mal`, `clf_mode`) |
| **P8** | M9: **không sửa**; `b2_classifier`, `b3_cascade` giữ `pending` (shadow → tỉ lệ L4 ≈ 1,0 — bỏ `pending` sẽ cảnh báo giả). Không đụng khối `# M9` |
| **P9** | Trường mới ở `settings.py`/compose/`.env.example` có chú thích `Phase 5 (T23a)`; giữ vị trí `f045e30` (ngoài khối M9). B2 đọc `get_settings().b2_classifier_mode` một lần trong `make` — giữ như `f045e30` (lệch quy ước NodeDeps — ghi "Spec cần sửa", không sửa `fakes.py`/NodeDeps) |
| **P10** | `.gitignore`: hai luật trùng ý (`/ml_models/*/*/` của `ml-gan`, `ml_models/*-clf/` của dev) → giữ **một** cách viết không làm lộ file model; `ml_models/README.md` (đang track) vẫn track. Báo lựa chọn trong MẪU A |
| **P11** | `json_object` (`llm/providers/openai_compat.py` + `test_llm_client.py`) là **commit riêng** (commit 2), không trộn với B2. Không sửa file `llm/` khác |

### 6.2. Test (đã có trong `f045e30` — chạy lại trên cây mới; thêm 3 nhóm)
Có sẵn (soát 10/10, chưa chạy): 503 khi không đặt; hình dạng hợp đồng; max không mean; phủ đủ N token (≥ 3 cửa sổ, đáng ngờ ở cửa sổ cuối); 48 chấm / 49 → 422; chỉ số lớp theo `id2label`; thiếu nhãn INJECTION; SHA lệch (kể cả trước torch); không văn bản trong log; shadow 0,95/0,05/0,5 → cả ba L4, `p_mal` trong audit; shadow + LLM lỗi → E2 giữ `p_mal`; active → E0/qua/L4; mode lạ; mặc định shadow; compose truyền biến cho backend + worker.
**Thêm:** (t1) client: 422 `too_many_windows` → `MlResult.error == "too_many_windows"`, 422 khác → `MlContractError`; (t2) B2 với lỗi `too_many_windows` ở `shadow` và `active` → L4 (không E9), audit `ml_error`; (t3) test khẳng định `/classify_intent` vẫn 503 khi đặt `GUARD_MODEL_DIR` (không vô tình bật intent). Mọi test cũ khác đỏ trên cây mới → DỪNG hỏi.

### 6.3. Mutation (`scripts/mutation/mutate_t23a.py`, khuôn `mutate_4c.py` + `n3.py`, md5; 1 lượt ở T23a, lượt 2 ở ngày đệm trước cổng 5)

| Mã | Phá | Test phải đỏ |
|---|---|---|
| M-T23a-1 | Chỉ chấm cửa sổ đầu | `test_suspicious_tail_in_last_window_is_scored` |
| M-T23a-2 | `shadow` vẫn chặn ≥ TAU_BLOCK | `test_shadow_classifier_never_decides[0.95]` |
| M-T23a-3 | `shadow` vẫn cho qua ≤ TAU_PASS | `[0.05]`, `test_shadow_low_score_attack_still_judged_by_llm` |
| M-T23a-4 | Mặc định → `active` | `test_mode_defaults_to_shadow` |
| M-T23a-5 | max → mean | `test_max_over_windows_not_mean` |
| M-T23a-6 | Lật chỉ số lớp | `test_class_index_from_id2label` |
| M-T23a-7 | Bỏ kiểm SHA | `test_sha_mismatch_refuses` |
| M-T23a-8 | Vượt trần cắt bớt vẫn trả điểm | `test_48_windows_scored_49_rejected_without_scoring` |
| M-T23a-9 | 422 `too_many_windows` → `MlContractError` (về E9) | t1, t2 |

### 6.4. Commit, soát, verify
- **Commit 1** (B2 L3 + P4 + mutation + test + `PROGRESS.md` + 2 file spec): message không nhắc "intent". **Commit 2** (`json_object`). Stage đích danh.
- **security-reviewer** một lần trước commit, chỉ diff T23a: (1) không nạp pickle/không exec file trong `ml_models/`; (2) đường dẫn model không thoát thư mục mount; (3) không văn bản người dùng trong log/phản hồi/audit; (4) mọi lỗi nạp → không khởi động, mọi lỗi chấm → L4 (không "cho qua"); (5) `shadow` không có nhánh nào quyết định theo `p_mal`; (6) mặc định không nạp + mặc định `shadow`; (7) không đụng khối M9/`monitor/*`, `risk/*`, `policy.json`, `config/prompts`, `config/scripted`.
- **Verify:** `make verify G=234` qua phiếu "dùng stack" (mặc định không nạp model → phải xanh như trước). **Tuỳ chọn, không chặn commit:** đo với model thật (Tuấn Anh tự thêm 3 dòng `.env`: `GUARD_MODEL_DIR`, `GUARD_MODEL_SHA256`, `B2_CLASSIFIER_MODE=shadow`) — 5 câu đối chiếu điểm của Dương (lệch ≤ 0,01), `docker stats`, `make gate3 S="preflight tc04"`; xong gỡ 3 dòng.
- **Spec cần sửa (T23a):** in nguyên văn trong MẪU B (gồm: P9 lệch NodeDeps; B02 §7 / P11 §4.3 `thresholds.json` là nợ trước `active`; độ trễ hàng chờ chung rerank chưa đo).

## 7. Chặng T24 — executor + hoàn tác + **bật 4 intent** (khung)

**Đầu vào:** **T20a**. **Đầu ra:** `PLAN` + mẫu tin B18 cho `reset_password`, `unlock_account`, `install_software`, `view_permissions`, `grant_permission`, `extend_permission`; `TransactionLog` hoàn tác theo `reversibility` từng bước; license có phí (`assign_paid_license`, `reversible=none`) lỗi khi cài → **không** gọi hoàn tác (cổng 5 [Chốt]); handoff E7 4 phần; **bật `ENABLED_INTENTS` 4 intent** (Q-5-7) + e2e TC đơn ý của cổng 5 (TC01, TC03, TC07, TC08, TC12, TC13, TC15–TC18, TC21). Giữ hợp đồng `ExtendIn` không nhận mức quyền (Q-T22a-8). **Tầng A, Opus, 2 DỪNG.** Mutation: hoàn tác hành động không hoàn tác được; bỏ kiểm `reversibility`; retry lệnh ghi. **Lưu ý cho 6C:** T24 là chặng cuối sửa `b17_execute.py` trước 6C (G6-1) — khi T24 đẩy, báo Phase 6 "6C mở được".

---

## 8. Lịch và thứ tự [làm mới 10/10 — phiên PHAN-TICH-P5 + Tuấn Anh chốt]

| Ngày | Chặng | Tầng / DỪNG | Phụ thuộc | Phase 6 |
|---|---|---|---|---|
| 09/10 | ~~T22a~~ xong `2ffb005` | A / 2 | — | 6A gộp |
| 10 sáng | — | — | — | **6B** xong DỪNG 1 + 2, gộp `d42d5c4` (12:28) |
| **10 chiều** | **T23a** (thư mục chính) | A / 1 | 6B đã gộp; phiên git cherry-pick `f045e30` không commit | — |
| 11–12 | (Claude chat: spec T20a, áp 17 mục "Spec cần sửa (T22a)") | — | — | — |
| 13–14 | **T20a** | A+B / 2 | 6B gộp, K2 gộp + ingest (T23a khác file — không bắt buộc đẩy trước, nhưng thư mục chính dùng tuần tự) | — |
| 15–16 | **T24** + bật 4 intent | A / 2 | T20a | — |
| 16 | (Claude chat: spec T20b, chốt Q5) | — | — | — |
| 17–18 | **T20b** | A / 2 | T24 | 6C (DỪNG lệch ngày với T20b) |
| 19 | Đệm + mutation lượt 2 (T23a, T24) | — | — | — |
| **~20–21** | **Cổng 5** | — | T22a–T24, T20b | — |

Cổng 5 đạt khi: `make lint`, `make test` xanh; CI xanh; cổng 5 tự động đủ; mutation T22a/T23a/T24 ×2, T20a/T20b ×1 (phần A ×2); thành viên chạy `make verify` + biên bản; spec "Chốt khi hiện thực" từng chặng; `decisions.md` D-35, D-41, D-44…46. **Bỏ khỏi Phase 5 (D-44):** model phân loại của Duy + cascade B3 — làm sau cổng 5 khi có τ_hi/τ_lo + SHA.

## 9. Nhật ký

| Ngày | Phiên bản | Thay đổi |
|---|---|---|
| 10/10/2026 | 0.2 | T22a đóng (`2ffb005`). Kế hoạch sau T22a theo phiên PHAN-TICH-P5 (soát code chỉ đọc) + Tuấn Anh chốt: mục 5 tách T20a/T20b (ước 19–25 giờ, bật intent dời sang T24 — Q-5-7); mục 6 **T23a viết đủ** (đóng `ml-gan`, `shadow`, mặc định không nạp, 422 → L4 — Q-5-9, 9 mutation, `json_object` commit riêng); mục 7 T24 bật 4 intent; mục 8 lịch mới (cổng 5 ~20–21/10); model của Duy ra khỏi Phase 5 (D-44). 17 mục "Spec cần sửa (T22a)" CHƯA áp — làm 11–12/10 |
| 09/10/2026 | 0.1f (sửa 13:00) | Mục 0.2 viết lại theo luật git 4.0 (agent không tự pull/push/stack; phiếu cho phiên git), khoá thư mục chính tới hết DỪNG cuối, cấm ingest khi chặng mở, giao thức Phase 5–6 (2 agent, `PROGRESS.md`, `app.eval`, thứ tự 6B → T20, T24 → 6C); 0.1 thêm `RiskContext`, hằng `mutate_3h.py`; P5/P11 thêm cấm `risk/models.py`, `config/scripted`, `app.eval`; 4.9 thêm bất biến (8); 4.10 nêu bàn giao DỪNG 1 + phiếu push; T20 phụ thuộc 6B; lịch mục 8 theo lịch chung v0.6. **Lời mở chặng thắng mục 0.2 về thao tác git/stack** |
| 09/10/2026 | 0.1f (sửa 01:20) | Mục 0.2: khoá thư mục chính tới hết DỪNG 2 (commit + push); cấm `make ingest` khi chặng còn mở. Tuấn Anh chốt bảng 4.2 `procedure_doc` theo K2 thật (Q-5-6): `view_permissions` → KB-ACS-005, `grant_permission` → KB-ACS-001; sửa 4.11, dòng `test_s0_grounding` ở 4.7b, thêm ca h8; mốc `3ff63e1` (file T22a không đổi); 0.1 thêm dòng `approvers.yaml`; T20/T23 cập nhật đầu vào (`ml-gan`, K2 PR #29) |
| 06/10/2026 | 0.1e | Kiểm kỹ lần 3: dựng thử P7 (không vỡ test nào; chốt vị trí 3 trường ở model tool); sửa 2 `value_rules` sai (tên phần mềm, đường dẫn thư mục có chữ hoa); `target_lock_reason` theo giá trị thật của mock; K2 qua `load_kb` |
| 03/10/2026 | 0.1c | Rà soát lần 2: dựng thử lớp luật trên engine thật (57/57 ca đúng, khởi động qua, 7/12/1). Thêm mục 4.7b: 13 test cũ phải đổi + cách đổi; 4.5 thêm `domain/messages.py` (6 nhãn), `mutate_3h.py`; P7 thêm quy tắc `disable_reason` ở endpoint quản trị; v1 sửa lại phạm vi "không đổi kỳ vọng" |
| 01/10/2026 | 0.1 | Tạo file: sự thật code `aac90b1`; Q-5-1…5 chốt; T22a đủ (P1–P11, metadata 6 hành động, 12 fact, bảng 20 luật kèm điều kiện, `rule_coverage.py`, ≥ 60 test, 12 mutation, checklist Quân); T20, T23, T24 mức khung |
